"""TDS withheld, read from Zoho Books customer payments through the existing Connect (Final 2T, Phase 4; N-204).

Zoho's `tax_amount_withheld` (payment level and per applied invoice) is read for invoices Servabo knows. It is shown as
accounting evidence and as a SUGGESTED expectation; a person accepts it. The field names are UNVERIFIED until Final session 2B
runs against a real Zoho Books organization (the stand-in is tests/fakes/fake_zoho.py)."""

import secrets
import time
from datetime import date

import pytest
from pydantic import SecretStr

from app.core.config import settings
from app.models.erp import ErpTarget
from app.models.trinetra import TrinetraCredit, TrinetraSuggestion
from app.services.erp import service as erp_service
from app.services.erp import vocabulary as v
from app.services.erp import zoho
from tests.fakes.fake_zoho import FakeZoho
from tests.services.gst.helpers import book_invoice
from tests.trinetra.test_api import world, SUPPLIER_A  # noqa: F401
from tests.trinetra.test_suggestions import accept, listed, profile


@pytest.fixture()
def fake(monkeypatch):
    with FakeZoho() as server:
        monkeypatch.setattr(settings, "ZOHO_CLIENT_ID", "1000.APPCLIENT")
        monkeypatch.setattr(settings, "ZOHO_CLIENT_SECRET", SecretStr("app-secret-value"))
        monkeypatch.setattr(settings, "ZOHO_REDIRECT_URI", "http://testserver/api/v1/erp/zoho/callback")
        monkeypatch.setattr(settings, "ZOHO_ACCOUNTS_URL_OVERRIDE", server.url)
        monkeypatch.setattr(settings, "ZOHO_API_URL_OVERRIDE", server.url)
        yield server


def connect(db, tenant, fake, *, scopes=None, chosen=True):
    refresh = "1000.refresh." + secrets.token_hex(8)
    fake.refresh_tokens[refresh] = True
    target = erp_service.create_target(
        db, organization_id=tenant.organization.id, workspace_id=tenant.workspace.id, actor_user_id=tenant.owner.user.id,
        name="Zoho Books", format=v.FORMAT_JSON, transport=v.TRANSPORT_HTTP, preset=v.PRESET_ZOHO, ack_mode=v.ACK_SYNC,
        auth_mode=v.AUTH_OAUTH2_REFRESH,
        config=zoho._build_config(zoho.data_centre("IN"), {  # noqa: SLF001 - the connect flow's own config
            "zoho": {"organization_id": "60001000001", "data_centre": "IN", "organization_chosen": chosen,
                     "scopes": list(zoho.SCOPES) if scopes is None else scopes}}),
        credential={"client_id": "1000.APPCLIENT", "client_secret": "app-secret-value", "refresh_token": refresh},
        check_network=False)
    target.status = v.TARGET_ACTIVE
    db.commit()
    return target


def payment(pid, number, withheld, *, applied=118000.0, on="2026-03-20", customer="First Customer Pvt Ltd", top=None):
    return {"payment_id": pid, "payment_number": pid, "date": on, "customer_name": customer, "amount": applied - withheld,
            "invoice_numbers": number, **({"tax_amount_withheld": top} if top is not None else {}),
            "invoices": [{"invoice_id": "i-" + number, "invoice_number": number, "amount_applied": applied - withheld,
                          "tax_amount_withheld": withheld}]}


def make_invoice(db, tenant, number):
    item = book_invoice(db, tenant, number=number, supplier="a", gstin=SUPPLIER_A, on=date(2026, 3, 1), taxable=100000,
                        extra={"vendor_pan": "ABCDE1234F", "bill_to": "First Customer Pvt Ltd"})
    db.commit()
    return item


def scan(client, tenant, world, pid, **body):
    return client.post(world[0] + "/suggestions/zoho/scan", headers=tenant.owner.headers, json={"profile_id": pid, **body})


def test_the_scan_needs_a_connected_zoho_with_the_new_read_scope(client, tenant, world, db_session, fake):
    pid = profile(client, tenant, world)
    none = scan(client, tenant, world, pid)
    assert none.status_code == 409 and "TRINETRA_ZOHO_NOT_CONNECTED" in none.text
    connect(db_session, tenant, fake, scopes=["ZohoBooks.bills.CREATE"])            # signed in before TRINETRA asked for payments
    old = scan(client, tenant, world, pid)
    assert old.status_code == 409 and "TRINETRA_ZOHO_RECONNECT" in old.text and "Reconnect Zoho Books" in old.text
    assert "customerpayments.READ" in ",".join(zoho.SCOPES) and not any(s.endswith(".DELETE") for s in zoho.SCOPES)


def test_withheld_tax_on_customer_payments_becomes_a_suggestion_and_accounting_evidence(client, tenant, world, db_session, fake):
    pid = profile(client, tenant, world)
    invoice = make_invoice(db_session, tenant, "ZB-1")
    make_invoice(db_session, tenant, "ZB-2")
    connect(db_session, tenant, fake)
    fake.payments = [
        payment("p1", "ZB-1", 1500.0, on="2026-03-10"),
        payment("p2", "ZB-1", 500.0, on="2026-03-25"),                              # a second, split payment on the same invoice
        payment("p3", "ZB-2", 0.0),                                                 # nothing withheld: no suggestion
        payment("p4", "NOT-OURS", 900.0),                                           # an invoice Servabo does not know
    ]
    out = scan(client, tenant, world, pid)
    assert out.status_code == 200, out.text
    assert out.json()["created"] == 1 and out.json()["unknown_invoices"] == 1
    s = listed(client, tenant, world)["items"][0]
    assert s["source"] == "ZOHO" and s["amount_micros"] == "2000000000" and s["needs_tan"] is True
    assert s["work_item_id"] == str(invoice.id) and s["evidence"]["accounting_record"] is True
    assert db_session.query(TrinetraCredit).count() == 0                                # only a suggestion
    # Zoho's payments are read by the person's own sign-in and asked for the right year.
    assert any(q.get("date_start") for q in fake.payment_queries)
    # Without the customer's TAN it cannot be accepted; with it, it becomes a case with the Zoho record as evidence.
    assert accept(client, tenant, world, s["id"]).status_code == 422
    ok = accept(client, tenant, world, s["id"], tan="ABCD12345E")
    assert ok.status_code == 200, ok.text
    case = db_session.query(TrinetraCredit).one()
    assert case.review["origin"] == "suggestion:ZOHO"
    [record] = [e for e in case.review["evidence"] if e["kind"] == "ACCOUNTING_RECORD"]
    assert record["source"] == "ZOHO" and record["amount_micros"] == 2_000_000_000 and record["work_item_id"] is None
    detail = client.get(world[0] + f"/credits/{ok.json()['id']}", headers=tenant.owner.headers)
    assert detail.status_code == 200 and detail.json()["review"]["evidence"][0]["current"] is True


def test_the_payment_level_amount_is_used_only_when_one_invoice_was_paid(client, tenant, world, db_session, fake):
    pid = profile(client, tenant, world)
    make_invoice(db_session, tenant, "ZB-3")
    connect(db_session, tenant, fake)
    single = payment("p9", "ZB-3", 0.0, top=700.0)
    single["invoices"][0].pop("tax_amount_withheld")
    fake.payments = [single]
    assert scan(client, tenant, world, pid).json()["created"] == 1
    assert listed(client, tenant, world)["items"][0]["amount_micros"] == "700000000"


def test_the_scan_is_read_only_for_a_viewer_gated_and_never_writes_to_zoho(client, tenant, world, db_session, fake):
    pid = profile(client, tenant, world)
    connect(db_session, tenant, fake)
    assert client.post(world[0] + "/suggestions/zoho/scan", headers=tenant.viewer.headers, json={"profile_id": pid}).status_code == 403
    scan(client, tenant, world, pid)
    assert {m for m, _ in fake.requests if m == "POST"} <= {"POST"} and not fake.bills
    assert all(m == "GET" or path.startswith("/oauth/") for m, path in fake.requests)
