"""What the plan capacities count (Final 2T, Phase 2.2; N-202).

Profiles are counted as before. Snapshots count ACTIVE ones (one per profile and tax year): a new import supersedes the old
one and costs nothing. Cases count OPEN ones: closing a case frees its slot. Superseded snapshots and closed cases go
against a much higher retention ceiling and age out with the documents under the retention policy. A real year never hits
a permanent wall, and a refusal names the plan that raises the limit."""

import uuid
from datetime import date

import pytest

from app.models.trinetra import TrinetraCredit, TrinetraProfile, TrinetraStatement
from app.services.trinetra import service
from tests.security.plans import put_on_plan
from tests.trinetra.test_api import world  # noqa: F401
from tests.trinetra.test_case_list_batches import add_cases
from tests.trinetra.test_workflows import setup_case


def statement(world, body, year, n):
    return {
        "profile_id": body["profile_id"], "source_work_item_id": str(world[2].id), "year": year, "pan": "ABCDE1234F",
        "confirmed": True, "rows": [{"tan": "ABCD12345E", "amount": str(1000 + n), "reference": f"Q source row {n}"}],
    }


def test_a_year_of_quarterly_imports_and_more_never_hits_the_wall(client, tenant, world, db_session):
    url, body, _ = setup_case(client, tenant, world)
    for n in range(14):  # the 13th and 14th import would have been refused as "the 13th snapshot"
        r = client.post(url + "/reviewed-statements", headers=tenant.owner.headers, json=statement(world, body, 2025, n))
        assert r.status_code == 200, (n, r.text)
    rows = db_session.query(TrinetraStatement).all()
    assert len(rows) == 14 and sum(1 for r in rows if r.active) == 1


def test_active_snapshots_are_capped_per_profile_and_year_and_the_refusal_names_the_plan(client, tenant, world, db_session, monkeypatch):
    url, body, _ = setup_case(client, tenant, world)
    real = service.capacity
    monkeypatch.setattr(service, "capacity", lambda db, w, kind: 2 if kind == "snapshots" else real(db, w, kind))
    for year in (2023, 2024):
        assert client.post(url + "/reviewed-statements", headers=tenant.owner.headers, json=statement(world, body, year, 1)).status_code == 200
    # Re-importing a year that is already active supersedes it: no new active snapshot, so it is allowed.
    assert client.post(url + "/reviewed-statements", headers=tenant.owner.headers, json=statement(world, body, 2024, 2)).status_code == 200
    refused = client.post(url + "/reviewed-statements", headers=tenant.owner.headers, json=statement(world, body, 2022, 1))
    assert refused.status_code == 409 and "Enterprise" in refused.text and "active" in refused.text


def test_open_cases_are_capped_and_closing_one_frees_its_slot(client, tenant, world, db_session, monkeypatch):
    url, body, first = setup_case(client, tenant, world)
    profile = db_session.get(TrinetraProfile, uuid.UUID(body["profile_id"]))
    real = service.capacity
    monkeypatch.setattr(service, "capacity", lambda db, w, kind: 3 if kind == "cases" else real(db, w, kind))
    add_cases(db_session, tenant, profile, 2, "CAP")  # 3 open now
    from tests.services.gst.helpers import book_invoice
    from tests.trinetra.test_api import SUPPLIER_A

    def next_case(number):
        invoice = book_invoice(db_session, tenant, number=number, supplier="a", gstin=SUPPLIER_A, on=date(2026, 3, 1),
                               taxable=100000, extra={"vendor_pan": "ABCDE1234F"})
        db_session.commit()
        return client.post(url + "/credits", headers=tenant.owner.headers, json={**body, "work_item_id": str(invoice.id), "reference": number})

    refused = next_case("CAP-X")
    assert refused.status_code == 409 and "open" in refused.text and "Enterprise" in refused.text
    # Close one: withdrawn is closed, so the next one fits ("over time" the 501st case succeeds).
    db_session.query(TrinetraCredit).filter_by(reference="CAP-0").update({"state": "WITHDRAWN"})
    db_session.commit()
    assert next_case("CAP-Y").status_code == 200


def test_closed_cases_and_old_snapshots_count_against_a_much_higher_retention_ceiling(client, tenant, world, db_session, monkeypatch):
    url, body, _ = setup_case(client, tenant, world)
    profile = db_session.get(TrinetraProfile, uuid.UUID(body["profile_id"]))
    real = service.capacity
    monkeypatch.setattr(service, "capacity", lambda db, w, kind: 1 if kind == "cases" else real(db, w, kind))
    monkeypatch.setattr(service, "RETENTION_MULTIPLIER", {"snapshots": 20, "cases": 3})
    add_cases(db_session, tenant, profile, 2, "RET")
    db_session.query(TrinetraCredit).update({"state": "WITHDRAWN"})  # three closed cases = the ceiling (1 x 3)
    db_session.commit()
    from tests.services.gst.helpers import book_invoice
    from tests.trinetra.test_api import SUPPLIER_A

    invoice = book_invoice(db_session, tenant, number="RET-X", supplier="a", gstin=SUPPLIER_A, on=date(2026, 3, 1),
                           taxable=100000, extra={"vendor_pan": "ABCDE1234F"})
    db_session.commit()
    refused = client.post(url + "/credits", headers=tenant.owner.headers,
                          json={**body, "work_item_id": str(invoice.id), "reference": "RET-X"})
    assert refused.status_code == 409 and "retention" in refused.text.lower()


def test_old_closed_cases_stay_out_of_the_working_set_so_the_summary_never_refuses_for_them(client, tenant, world, db_session, monkeypatch):
    url, body, _ = setup_case(client, tenant, world)
    profile = db_session.get(TrinetraProfile, uuid.UUID(body["profile_id"]))
    monkeypatch.setattr(service, "WORKING_SET_LIMIT", 3)
    add_cases(db_session, tenant, profile, 5, "OLD")
    db_session.query(TrinetraCredit).filter(TrinetraCredit.reference.like("OLD-%")).update({"state": "EXPLAINED", "year": 2015})
    db_session.commit()
    result = service.summary(db_session, tenant.workspace)
    assert result["total"] == 1  # only the open case; five old closed ones are retained but not in the working set
    listed = client.get(url + "/credits?year=2015", headers=tenant.owner.headers).json()
    assert listed["total"] == 5  # still reachable by year


def test_a_starter_organization_is_refused_with_the_plans_that_include_it(client, tenant, world, db_session):
    put_on_plan(db_session, tenant.organization, "developer")
    r = client.post(world[0] + "/profiles", headers=tenant.owner.headers, json={"name": "X", "pan": "ABCDE1234F"})
    assert r.status_code == 402 and "Business" in r.text


def test_the_published_figures():
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location("seed", Path(__file__).parents[2] / "scripts" / "seed_quota_tiers.py")
    seed = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(seed)

    def limits(tier):
        return {e["limit_key"]: int(e["max_quantity"]) for e in seed.PLACEHOLDER_TIERS[tier]["entries"] if e["limit_key"].startswith("limit.trinetra")}

    business, enterprise = limits("business"), limits("enterprise")
    assert business["limit.trinetra_profiles"] == 2 and business["limit.trinetra_snapshots"] == 12
    assert business["limit.trinetra_cases"] == 500 and business["limit.trinetra_inquiries_per_month"] == 50
    assert enterprise["limit.trinetra_inquiries_per_month"] > 50 and enterprise["limit.trinetra_cases"] > 500
