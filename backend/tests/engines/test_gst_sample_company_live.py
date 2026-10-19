"""Meridian Wholesale's GSTR-2B (the sample company, every plan): the reconciliation finds exactly what was planted.

The sample's own invoices are reported through the real parser and engine, with a supplier that never filed, a late
report, a value difference, a near match for a person to confirm, a credit note, a record GSTR-2B marks not
eligible, a record Meridian never received, a reverse-charge record and an unpaid invoice near the 180-day limit.
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import select

from app.models.gst import GstMatch, GstReturn
from app.services.gst import sample as gst_sample
from app.services.gst import vocabulary as v
from app.services.helm import sample_company
from tests.security.plans import put_on_plan

TODAY = date(2026, 10, 19)
API = "/api/v1"


@pytest.fixture()
def sample(client, db_session, tenant, test_sessions):
    put_on_plan(db_session, tenant.organization, "developer")  # the sample is open on every plan
    book = sample_company.build(db_session, organization_id=tenant.organization.id,
                                actor_user_id=tenant.owner.user.id, today=TODAY)
    db_session.commit()
    workspace = sample_company.sample_workspace(db_session, tenant.organization.id)
    planted = gst_sample.build_returns(db_session, workspace, today=TODAY)
    return tenant, workspace, planted


def lines(client, tenant, workspace, **params):
    response = client.get(f"{API}/workspaces/{workspace.id}/gst/records", headers=tenant.owner.headers,
                          params={"limit": 200, **params})
    assert response.status_code == 200, response.text
    return response.json()["items"]


def by_number(items):
    out = {}
    for item in items:
        out.setdefault(item["number"], []).append(item)
    return out


def test_the_returns_cover_the_sample_months_with_valid_gstins(db_session, sample):
    tenant, workspace, planted = sample
    returns = db_session.execute(select(GstReturn).where(GstReturn.workspace_id == workspace.id,
                                                         GstReturn.status == "ACTIVE")).scalars().all()
    assert {r.gstin for r in returns} == {sample_company.GSTIN}
    assert sorted(r.period for r in returns) == planted.periods and len(planted.periods) >= 8
    assert "2026-10" not in planted.periods  # the current month's statement does not exist yet
    assert all(not r.problems for r in returns), [r.problems for r in returns if r.problems]


def test_every_planted_case_is_found_where_it_was_planted(client, sample):
    tenant, workspace, planted = sample
    items = by_number(lines(client, tenant, workspace))
    status_of = lambda number: {i["status"] for i in items[number]}  # noqa: E731
    assert planted.never_filed_invoices and all(status_of(n) == {v.WAITING_FOR_SUPPLIER} for n in planted.never_filed_invoices)
    late = items[planted.late_number][0]
    assert late["status"] == v.MATCHED and late["reported_late"] is True and late["period_first_seen"]
    diff = items[planted.difference_number][0]
    assert diff["status"] == v.MATCHED_WITH_DIFFERENCES and diff["differences"][0]["field"] == "taxable"
    assert diff["differences"][0]["delta_micros"] == -1_000_000_000
    assert status_of(planted.suggested_record_number) == {v.SUGGESTED}
    assert items[planted.suggested_record_number][0]["work_item_id"]
    assert status_of(planted.credit_note_number) == {v.NOTE} and items[planted.credit_note_number][0]["method"] == "NUMBER"
    assert status_of(planted.not_eligible_number) == {v.NOT_ELIGIBLE}
    assert status_of(planted.not_in_books_number) == {v.NOT_IN_BOOKS}
    assert status_of(planted.reverse_charge_number) == {v.REVERSE_CHARGE}
    unpaid = items[planted.unpaid_number][0]
    assert unpaid["risk"]["at_risk"] is True and unpaid["risk"]["paid"] is False and unpaid["risk"]["age_days"] >= 150


def test_the_totals_are_exactly_what_was_planted(client, db_session, sample):
    tenant, workspace, planted = sample
    summary = client.get(f"{API}/workspaces/{workspace.id}/gst/summary", headers=tenant.owner.headers)
    assert summary.status_code == 200, summary.text
    body = summary.json()
    figures = {f["key"]: f for f in body["figures"]}
    never_filed = len(planted.never_filed_invoices)
    assert figures["waiting"]["count"] == never_filed and figures["waiting"]["suppliers"] == 1
    assert figures["differences"]["count"] == 1 and figures["differences"]["amount_micros"] == 180_000_000  # 18% of 1,000
    assert figures["not_in_books"]["count"] == 1
    assert figures["not_eligible"]["count"] == 1
    assert figures["at_risk_180"]["count"] == 1
    assert body["suggested"] == 1 and body["reverse_charge"] == 1 and body["notes"] == 1
    assert body["is_sample"] is True and body["access"]["full"] is True
    claimable = figures["claimable_now"]
    assert claimable["count"] > 20 and claimable["amount_micros"] > 0


def test_the_sample_is_open_to_a_developer_plan_and_read_only_for_everyone(client, tenant, sample):
    _, workspace, planted = sample
    for tail in ("/records", "/suppliers"):
        assert client.get(f"{API}/workspaces/{workspace.id}/gst{tail}", headers=tenant.owner.headers).status_code == 200
    first = lines(client, tenant, workspace)[0]
    refused = client.post(f"{API}/workspaces/{workspace.id}/gst/records/{first['record_id'] or first['id']}/decision",
                          headers=tenant.owner.headers, json={"decision": "NOT_OURS"})
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "SAMPLE_READ_ONLY"
    upload = client.post(f"{API}/workspaces/{workspace.id}/gst/returns", headers=tenant.owner.headers,
                         files={"file": ("x.json", b"{}")})
    assert upload.status_code == 409


def test_a_sample_built_before_gst_credit_gets_its_returns_the_first_time_it_is_opened(client, db_session, sample):
    tenant, workspace, planted = sample
    db_session.execute(GstMatch.__table__.delete().where(GstMatch.workspace_id == workspace.id))
    db_session.execute(GstReturn.__table__.delete().where(GstReturn.workspace_id == workspace.id))
    db_session.commit()
    assert not db_session.execute(select(GstMatch).where(GstMatch.workspace_id == workspace.id)).first()
    body = client.get(f"{API}/workspaces/{workspace.id}/gst/summary", headers=tenant.owner.headers).json()
    assert body["gstins"] == [sample_company.GSTIN] and body["lines"] > 20


def test_the_supplier_list_names_the_supplier_that_never_filed_first(client, tenant, sample):
    _, workspace, planted = sample
    body = client.get(f"{API}/workspaces/{workspace.id}/gst/suppliers", headers=tenant.owner.headers).json()
    first = body["items"][0]
    assert first["supplier_gstin"] == planted.never_filed_gstin and first["waiting_count"] == len(planted.never_filed_invoices)
    draft = client.get(f"{API}/workspaces/{workspace.id}/gst/suppliers/{planted.never_filed_gstin}/reminder",
                       headers=tenant.owner.headers, params={"gstin": sample_company.GSTIN}).json()
    assert draft["can_send"] is False and planted.never_filed_invoices[0] in draft["text"]
