"""TRINETRA in Recoveries (Final 2T, Phase 7.10): "TDS not yet in your statement" is its own kind. Its figure is a possible credit
gap kept in the issue's details, NEVER an exposure in cash: it is not in Recoveries' "found" money, not in the GST digest's "worth"
line, and closing it as verified records NO recovered outcome."""

import pytest

from app.models.recovery import RecoveryIssue, RecoveryOutcome
from app.services.recoveries import adapters, service
from app.services.recoveries import vocabulary as v
from tests.security.plans import put_on_plan
from tests.trinetra.test_api import world  # noqa: F401
from tests.trinetra.test_money_model import HEAD, allocate, decide, get, statement  # noqa: F401
from tests.trinetra.test_workflows import setup_case

OTHER = "MUMB54321K,10.00,x0,194C,15-Jun-2025,F,FY 2025-26 / AY 2026-27"


def issues(db, tenant):
    return db.query(RecoveryIssue).filter_by(workspace_id=tenant.workspace.id, kind=v.TDS_CREDIT).all()


def test_the_kind_is_in_the_vocabulary_and_the_adapter_is_registered_behind_the_trinetra_capability():
    assert v.TDS_CREDIT in v.KINDS and v.TDS_CREDIT in v.KIND_LABELS
    adapter = adapters.BY_KIND[v.TDS_CREDIT]
    assert adapter.capability == "capability.trinetra" and adapter.heavy is True


def test_a_gap_becomes_an_issue_whose_figure_is_never_an_exposure_in_cash(client, tenant, world, db_session):
    url, body, case = setup_case(client, tenant, world, reference="TR-REC-1")
    statement(client, tenant, url, body, [OTHER])
    service.sweep(db_session, tenant.workspace, heavy=True)
    [issue] = issues(db_session, tenant)
    assert issue.subject_key == case["id"] and issue.state == v.FOUND and str(issue.work_item_id) == str(world[1].id)
    assert issue.exposure_micros is None and issue.found_exposure_micros is None
    assert issue.details["gap_micros"] == 2_000_000_000 and issue.details["currency"] == "INR"
    assert "TDS not yet in your statement" in issue.title and "2,000" in issue.title
    assert "ABCDE1234F" not in str(issue.details) + issue.title and "ABCD12345E" not in str(issue.details) + issue.title
    summary = service.summary(db_session, tenant.workspace)
    assert summary["counts"][v.FOUND] == 1 and summary["found"] == {}                 # counted as an issue, never as found money
    assert summary["recovered_verified"] == {}
    service.sweep(db_session, tenant.workspace, heavy=True)
    assert len(issues(db_session, tenant)) == 1                                       # idempotent


def test_the_gst_digest_line_about_money_issues_leaves_tds_out(client, tenant, world, db_session):
    url, body, case = setup_case(client, tenant, world)
    statement(client, tenant, url, body, [OTHER])
    put_on_plan(db_session, tenant.organization, "business")
    service.sweep(db_session, tenant.workspace, heavy=True)
    db_session.commit()
    assert service.needs_owner(db_session, tenant.organization.id) is None


def test_a_confirmed_closure_verifies_the_issue_but_records_no_recovered_outcome(client, tenant, world, db_session):
    url, body, case = setup_case(client, tenant, world)
    statement(client, tenant, url, body, [OTHER])
    service.sweep(db_session, tenant.workspace, heavy=True)
    second = statement(client, tenant, url, body, ["ABCD12345E,2000.00,y0,194C,15-Jun-2025,F,FY 2025-26 / AY 2026-27"])
    done = decide(client, tenant, url, get(client, tenant, url, case), "ALLOCATE", allocations=[allocate(second, 0, "2000")])
    service.sweep(db_session, tenant.workspace, heavy=True)
    [issue] = issues(db_session, tenant)
    assert issue.state == v.FOUND                                                      # posted but nobody has confirmed it yet
    decide(client, tenant, url, done.json(), "CA_REVIEWED", reason="Accountant confirmed it in the new statement.")
    service.sweep(db_session, tenant.workspace, heavy=True)
    db_session.refresh(issue)
    assert issue.state == v.VERIFIED and "accountant" in (issue.close_reason or "").lower()
    assert db_session.query(RecoveryOutcome).count() == 0                              # evidence it is visible; not recovered cash
    reopened = decide(client, tenant, url, get(client, tenant, url, case), "REOPEN", reason="Reopened to check the amount again.")
    assert reopened.status_code == 200
    service.sweep(db_session, tenant.workspace, heavy=True)
    db_session.refresh(issue)
    assert issue.state in (v.FOUND, v.BEING_FIXED)


def test_a_withdrawn_case_closes_the_issue_without_counting_it(client, tenant, world, db_session):
    url, body, case = setup_case(client, tenant, world)
    statement(client, tenant, url, body, [OTHER])
    service.sweep(db_session, tenant.workspace, heavy=True)
    decide(client, tenant, url, get(client, tenant, url, case), "WITHDRAWN", reason="This invoice was cancelled by the customer.")
    service.sweep(db_session, tenant.workspace, heavy=True)
    [issue] = issues(db_session, tenant)
    assert issue.state == v.CLOSED and db_session.query(RecoveryOutcome).count() == 0


def test_nothing_is_swept_when_trinetra_is_not_live_for_the_organization(client, tenant, world, db_session, monkeypatch):
    from app.core.config import settings

    url, body, case = setup_case(client, tenant, world)
    statement(client, tenant, url, body, [OTHER])
    monkeypatch.setattr(settings, "TRINETRA_LIVE_ENABLED", None)
    monkeypatch.setattr(settings, "TRINETRA_MODE", "off")
    service.sweep(db_session, tenant.workspace, heavy=True)
    assert issues(db_session, tenant) == []


def test_the_recoveries_page_lists_the_issue_in_words_with_a_way_back_to_the_case(client, tenant, world, db_session):
    url, body, case = setup_case(client, tenant, world, reference="TR-REC-9")
    statement(client, tenant, url, body, [OTHER])
    service.sweep(db_session, tenant.workspace, heavy=True)
    db_session.commit()
    listed = client.get(f"/api/v1/workspaces/{tenant.workspace.id}/recoveries", headers=tenant.owner.headers)
    assert listed.status_code == 200, listed.text
    [issue] = [i for i in listed.json()["items"] if i["kind"] == "TDS_CREDIT"]
    assert issue["kind_label"] == "TDS not yet in your statement" and issue["exposure_micros"] is None
    assert issue["details"]["gap_micros"] == 2_000_000_000
    one = client.get(f"/api/v1/workspaces/{tenant.workspace.id}/recoveries/{issue['id']}", headers=tenant.owner.headers).json()
    assert [a["path"] for a in one["next_actions"] if a["key"] == "trinetra"] == [f"trinetra?case={case['id']}"]
    assert listed.json()["summary"]["found"] == []
