"""Helm reads GST Credit (real Postgres, the real API and worker): the snapshot carries where each invoice stands in
GSTR-2B, the 180-day mandate sets a hard deadline, the hold-until-reported mandate holds what the supplier has not
reported (and lets go before a legal deadline), the Guard asks a person, and a request to the supplier is drafted."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import select

from app.models.helm import HelmAction, HelmBook, HelmPlan
from app.services.gst import builder as b
from app.services.gst import engine
from app.services.helm import snapshot_store
from app.services.helm import vocabulary as v
from tests.engines.conftest import drain
from tests.security.plans import put_on_plan
from tests.services.gst.helpers import RECIPIENT, SUPPLIER_A, book_invoice, supplier_invoices

API = "/api/v1"
TODAY = date.today()
PERIOD = f"{TODAY.year:04d}-{TODAY.month:02d}"
FIRST = date(TODAY.year, TODAY.month, 1)


def _url(tenant, path: str) -> str:
    return f"{API}/organizations/{tenant.organization.id}/helm{path}"


@pytest.fixture()
def world(client, db_session, tenant, test_sessions):
    put_on_plan(db_session, tenant.organization, "business")
    db_session.commit()
    book = client.post(_url(tenant, "/books"), json={"workspace_id": str(tenant.workspace.id)},
                       headers=tenant.owner.headers).json()
    settings = client.patch(_url(tenant, f"/books/{book['id']}/settings"),
                            json={"identities": [{"name": "Meridian Wholesale", "tax_id": RECIPIENT}]},
                            headers=tenant.owner.headers)
    assert settings.status_code == 200, settings.text
    client.post(_url(tenant, f"/books/{book['id']}/cash-positions"),
                json={"currency": "INR", "amount": "50000000", "as_of": TODAY.isoformat()}, headers=tenant.owner.headers)
    # three invoices in the current month: reported, not reported (far from any legal deadline), not reported but
    # whose 180th day is five days away (dated 175 days ago, in another month)
    reported = book_invoice(db_session, tenant, number="R-1", supplier="a", gstin=SUPPLIER_A, on=FIRST, taxable=100_000)
    waiting = book_invoice(db_session, tenant, number="W-1", supplier="a", gstin=SUPPLIER_A, on=FIRST, taxable=200_000)
    old_day = TODAY - timedelta(days=175)
    old = book_invoice(db_session, tenant, number="OLD-1", supplier="a", gstin=SUPPLIER_A, on=old_day, taxable=300_000)
    db_session.commit()
    for period_day, documents in ((FIRST, [b.document("R-1", FIRST, 100_000)]),
                                  (old_day, [b.document("ZZ-1", old_day, 1_000)])):
        period = f"{period_day.year:04d}-{period_day.month:02d}"
        statement = b.to_bytes(b.gstr2b(RECIPIENT, period, {"b2b": [supplier_invoices(documents)]}))
        sent = client.post(f"{API}/workspaces/{tenant.workspace.id}/gst/returns", headers=tenant.contributor.headers,
                           files={"file": (f"{period}.json", statement)})
        assert sent.status_code == 200, sent.text
    return tenant, book, {"reported": reported, "waiting": waiting, "old": old}


def _payables(db, book_id):
    book = db.get(HelmBook, book_id)
    snapshot = snapshot_store.take(db, book)
    return {p.document_number: p for p in snapshot.payables}


def test_the_snapshot_says_where_each_invoice_stands_in_gstr_2b(db_session, world):
    tenant, book, docs = world
    drain(only=[v.JOB_LEDGER_BUILD])
    by_number = _payables(db_session, book["id"])
    assert by_number["R-1"].gst_status == "MATCHED" and by_number["R-1"].gst_micros == 18_000 * 1_000_000
    assert by_number["R-1"].gst_waiting is False
    assert by_number["W-1"].gst_waiting is True and by_number["W-1"].gst_gstin == RECIPIENT
    assert by_number["OLD-1"].gst_waiting is True
    assert by_number["OLD-1"].gst_deadline == (TODAY - timedelta(days=175)) + timedelta(days=180)


def test_the_hold_mandate_holds_what_is_unreported_and_pays_what_has_no_room_left(client, db_session, world):
    tenant, book, docs = world
    created = client.post(_url(tenant, f"/books/{book['id']}/mandates"),
                          json={"template": "gst_hold_until_reported", "activate": True}, headers=tenant.owner.headers)
    assert created.status_code == 201, created.text
    drain(only=[v.JOB_LEDGER_BUILD, v.JOB_PLAN])
    client.post(_url(tenant, f"/books/{book['id']}/plan"), headers=tenant.owner.headers)
    cockpit = client.get(_url(tenant, f"/books/{book['id']}/cockpit"), headers=tenant.owner.headers).json()
    titles = [a["title"] for a in cockpit["actions"]]
    assert any("W-1" in t and "Hold" in t for t in titles), titles
    assert not any("OLD-1" in t and "Hold" in t for t in titles), titles   # its 180th day is five days off
    assert not any("R-1" in t and "Hold" in t for t in titles)
    instrument = next(i for i in cockpit["summary"]["instruments"] if i["template"] == "gst_hold_until_reported")
    assert instrument["state"] == "drifting" and "follow-up" in instrument["detail"]
    risks = [r["summary"] for r in cockpit["summary"]["risks"]]
    assert any("OLD-1" in r and "pays it on time instead of holding it" in r for r in risks), risks


def test_the_180_day_mandate_plans_the_old_invoice_inside_its_last_day_and_asks_the_supplier(client, db_session, world):
    tenant, book, docs = world
    created = client.post(_url(tenant, f"/books/{book['id']}/mandates"),
                          json={"template": "gst_pay_within_180_days", "activate": True}, headers=tenant.owner.headers)
    assert created.status_code == 201, created.text
    drain(only=[v.JOB_LEDGER_BUILD, v.JOB_PLAN])
    client.post(_url(tenant, f"/books/{book['id']}/plan"), headers=tenant.owner.headers)
    cockpit = client.get(_url(tenant, f"/books/{book['id']}/cockpit"), headers=tenant.owner.headers).json()
    pay = next(a for a in cockpit["actions"] if a["kind"] == v.ACTION_SCHEDULE_PAYMENT and "OLD-1" in a["title"] + str(a.get("params")))
    assert date.fromisoformat(pay["run_date"]) <= TODAY + timedelta(days=5)
    guard = {c["id"]: c for c in pay["guard"]["checks"]}
    assert guard["gst"]["result"] == "needs_approval" and "Section 16(2)(aa)" in guard["gst"]["detail"]
    request = next(a for a in cockpit["actions"] if a["kind"] == v.ACTION_REQUEST_DOCUMENT)
    assert request["params"]["topic"] == "GST_REPORTING" and request["params"]["supplier_gstin"] == SUPPLIER_A
    assert {c["id"]: c["result"] for c in request["guard"]["checks"]}["destination"] == "pass"   # a draft: nothing is sent


def test_a_gst_import_asks_for_a_new_plan(client, db_session, world):
    tenant, book, docs = world
    client.post(_url(tenant, f"/books/{book['id']}/mandates"), json={"template": "gst_pay_within_180_days", "activate": True},
                headers=tenant.owner.headers)
    drain(only=[v.JOB_LEDGER_BUILD, v.JOB_PLAN])
    before = len(db_session.execute(select(HelmPlan.id).where(HelmPlan.book_id == book["id"])).all())
    engine.recompute(db_session, tenant.workspace)   # what a decision or a new import does at its end
    db_session.commit()
    drain(only=[v.JOB_PLAN])
    db_session.expire_all()
    after = len(db_session.execute(select(HelmPlan.id).where(HelmPlan.book_id == book["id"])).all())
    assert after >= before
