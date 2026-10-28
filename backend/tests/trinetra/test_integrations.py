"""TRINETRA woven into the rest of Servabo (Final 2T, Phase 7): Getting started, search, notifications, the digest, the value receipt,
automation, the public API, the warehouse, the organization view, Recoveries, Helm and the Enterprise controls."""

import uuid
from datetime import datetime, timezone

from app.core.config import settings

import pytest

from app.models.organization import OrganizationRole
from app.models.trinetra import TrinetraProfile, TrinetraStatement
from app.models.workspace import WorkspaceRole
from app.services import getting_started as gs
from tests.security.plans import put_on_plan
from tests.trinetra.test_api import world  # noqa: F401
from tests.trinetra.test_workflows import setup_case


def _view(db, tenant, *, ws_role=WorkspaceRole.ADMIN, org_role=OrganizationRole.OWNER):
    return gs.evaluate(db, organization=tenant.organization, workspace=tenant.workspace, workspace_role=ws_role, organization_role=org_role)


# --- 1. Getting started -----------------------------------------------------------------------------------------------------


def test_the_trinetra_step_ticks_only_when_a_statement_has_really_been_imported(client, tenant, world, db_session):
    assert gs.tick_trinetra(db_session, tenant.workspace.id) is False
    setup_case(client, tenant, world)
    profile = db_session.query(TrinetraProfile).one()
    assert gs.tick_trinetra(db_session, tenant.workspace.id) is False          # a profile and a case are not a statement
    db_session.add(TrinetraStatement(workspace_id=tenant.workspace.id, organization_id=tenant.organization.id, profile_id=profile.id,
                                     year=2025, source_sha256="0" * 64, rows=[], active=True, source_version="t", fingerprint="0" * 64,
                                     parser_version="t", revision=1))
    db_session.flush()
    assert gs.tick_trinetra(db_session, tenant.workspace.id) is True


def test_the_step_is_shown_to_workspace_admins_only_and_says_what_blocks_it(db_session, tenant, monkeypatch):
    from app.core.config import settings

    put_on_plan(db_session, tenant.organization, "business")
    monkeypatch.setattr(settings, "TRINETRA_MODE", "on")
    db_session.flush()
    step = next(s for s in _view(db_session, tenant)["steps"] if s["key"] == "trinetra")
    assert "TDS" in step["title"] and step["note"] is None and step["done"] is False
    assert "trinetra" not in [s["key"] for s in _view(db_session, tenant, ws_role=WorkspaceRole.CONTRIBUTOR)["steps"]]
    assert "trinetra" not in [s["key"] for s in _view(db_session, tenant, ws_role=WorkspaceRole.VIEWER, org_role=OrganizationRole.MEMBER)["steps"]]
    monkeypatch.setattr(settings, "TRINETRA_MODE", "pilot")                    # shipped state: not enrolled yet
    note = next(s for s in _view(db_session, tenant)["steps"] if s["key"] == "trinetra")["note"]
    assert note and "pilot" in note.lower()
    put_on_plan(db_session, tenant.organization, "developer")
    db_session.flush()
    monkeypatch.setattr(settings, "TRINETRA_MODE", "on")
    note = next(s for s in _view(db_session, tenant)["steps"] if s["key"] == "trinetra")["note"]
    assert note and "Business" in note and "Enterprise" in note


# --- 2. Global search -------------------------------------------------------------------------------------------------------


def _search(client, tenant, q, who="owner"):
    r = client.get(f"/api/v1/organizations/{tenant.organization.id}/search", params={"q": q}, headers=getattr(tenant, who).headers)
    assert r.status_code == 200, r.text
    return r.json()


def test_search_finds_a_case_by_invoice_reference_and_customer_name_but_never_by_pan_or_tan(client, tenant, world):
    setup_case(client, tenant, world, reference="TR-SEARCH-9")
    by_reference = _search(client, tenant, "tr-search")["tds_cases"]
    assert len(by_reference) == 1 and by_reference[0]["kind"] == "TDS_CASE" and by_reference[0]["title"] == "TR-SEARCH-9"
    assert "Synthetic deductor" in by_reference[0]["subtitle"] and by_reference[0]["workspace_slug"] == tenant.workspace.slug
    assert [h["title"] for h in _search(client, tenant, "synthetic ded")["tds_cases"]] == ["TR-SEARCH-9"]
    for identifier in ("ABCDE1234F", "ABCD12345E", "abcd1234"):
        assert _search(client, tenant, identifier)["tds_cases"] == []
    assert "ABCDE1234F" not in str(_search(client, tenant, "TR-SEARCH")) and "ABCD12345E" not in str(_search(client, tenant, "TR-SEARCH"))


def test_search_shows_nothing_where_the_page_itself_would_be_locked(client, tenant, world, db_session, monkeypatch):
    from app.core.config import settings

    setup_case(client, tenant, world, reference="TR-LOCK-1")
    assert len(_search(client, tenant, "TR-LOCK")["tds_cases"]) == 1
    monkeypatch.setattr(settings, "TRINETRA_LIVE_ENABLED", None)               # the old yes/no alias would otherwise win
    monkeypatch.setattr(settings, "TRINETRA_MODE", "pilot")                    # not enrolled: the page says so, search stays silent
    assert _search(client, tenant, "TR-LOCK")["tds_cases"] == []
    monkeypatch.setattr(settings, "TRINETRA_MODE", "on")
    put_on_plan(db_session, tenant.organization, "developer")
    db_session.commit()
    assert _search(client, tenant, "TR-LOCK")["tds_cases"] == []


def test_a_person_with_no_grant_on_the_workspace_and_another_organizations_member_find_nothing(client, tenant, world, db_session):
    from app.models.workspace import Workspace, WorkspaceStatus

    setup_case(client, tenant, world, reference="TR-GRANT-1")
    other = Workspace(organization_id=tenant.organization.id, slug="branch", workspace_name="Branch office", status=WorkspaceStatus.ACTIVE)
    db_session.add(other)
    db_session.commit()
    # The contributor holds a grant on "engineering" (where the case is) and may see it; remove that grant and nothing is found.
    assert len(_search(client, tenant, "TR-GRANT", who="contributor")["tds_cases"]) == 1
    from app.models.workspace import WorkspaceMember

    db_session.query(WorkspaceMember).filter_by(workspace_id=tenant.workspace.id, user_id=tenant.contributor.user.id).delete()
    db_session.commit()
    assert _search(client, tenant, "TR-GRANT", who="contributor")["tds_cases"] == []
    r = client.get(f"/api/v1/organizations/{tenant.organization.id}/search", params={"q": "TR-GRANT"}, headers=tenant.other_org_member.headers)
    assert r.status_code in (403, 404) and "TR-GRANT" not in r.text


# --- 5. The value receipt and the monthly summary ----------------------------------------------------------------------------

from tests.trinetra.test_money_model import allocate, decide, get, statement  # noqa: E402


def _receipt(db, tenant, period="month"):
    from app.services import value_receipt

    value_receipt.forget(tenant.organization.id)
    return value_receipt.receipt(db, tenant.organization.id, period)


def test_the_receipt_shows_tds_not_yet_in_the_statement_as_its_own_line_that_never_leads_or_adds(client, tenant, world, db_session):
    url, body, case = setup_case(client, tenant, world)
    assert [f for f in _receipt(db_session, tenant)["found"] if f["key"].startswith("tds_")] == []        # no statement, no figure
    statement(client, tenant, url, body, ["MUMB54321K,10.00,x0,194C,15-Jun-2025,F,FY 2025-26 / AY 2026-27"])
    receipt = _receipt(db_session, tenant)
    [gap] = [f for f in receipt["found"] if f["key"] == "tds_not_in_statement"]
    assert gap["amount_micros"] == 2_000_000_000 and gap["currency"] == "INR" and gap["count"] == 1
    assert "TDS not yet in your statement" in gap["label"] and gap["source"].endswith("/trinetra")
    assert gap["honesty"] == "potential"                         # a possible gap in a tax statement: never confirmed, never money
    assert "TDS" not in (receipt["headline"] or "")             # it never leads the sentence about what Servabo found
    assert not any(f["key"] not in ("tds_not_in_statement",) and f["amount_micros"] == gap["amount_micros"] and f["key"].startswith("gst")
                   for f in receipt["found"])                    # and is never folded into a GST or cash line


def test_tds_now_visible_comes_from_the_closure_ledger_and_is_labelled_as_not_cash(client, tenant, world, db_session):
    url, body, case = setup_case(client, tenant, world)
    statement(client, tenant, url, body, ["MUMB54321K,10.00,x0,194C,15-Jun-2025,F,FY 2025-26 / AY 2026-27"])
    second = statement(client, tenant, url, body, ["ABCD12345E,2000.00,y0,194C,15-Jun-2025,F,FY 2025-26 / AY 2026-27"])
    done = decide(client, tenant, url, get(client, tenant, url, case), "ALLOCATE", allocations=[allocate(second, 0, "2000")])
    decide(client, tenant, url, done.json(), "CA_REVIEWED", reason="Accountant confirmed it in the new statement.")
    receipt = _receipt(db_session, tenant)
    [visible] = [f for f in receipt["found"] if f["key"] == "tds_now_visible"]
    assert visible["amount_micros"] == 2_000_000_000 and "not cash" in visible["label"].lower() and visible["honesty"] == "confirmed"
    assert [f for f in receipt["found"] if f["key"] == "tds_not_in_statement"] == []      # nothing is left unposted
    assert "TDS" not in (receipt["headline"] or "")
    from app.services import getting_started

    assert getting_started.first_money(db_session, tenant.organization.id) is None        # TDS is never "first money found"


def test_the_receipt_has_no_tds_line_when_trinetra_is_not_live_for_the_organization(client, tenant, world, db_session, monkeypatch):
    url, body, case = setup_case(client, tenant, world)
    statement(client, tenant, url, body, ["MUMB54321K,10.00,x0,194C,15-Jun-2025,F,FY 2025-26 / AY 2026-27"])
    monkeypatch.setattr(settings, "TRINETRA_LIVE_ENABLED", None)
    monkeypatch.setattr(settings, "TRINETRA_MODE", "off")
    assert [f for f in _receipt(db_session, tenant)["found"] if f["key"].startswith("tds_")] == []


# --- 7. The public API (Enterprise) -----------------------------------------------------------------------------------------


def test_enterprise_keys_read_cases_and_nothing_else_with_amounts_as_strings_and_no_tax_identifier(client, tenant, world, db_session):
    from tests.security.test_non_human_principals_default_deny import _key
    from tests.trinetra.test_money_model import statement

    url, body, case = setup_case(client, tenant, world, reference="TR-API-1")
    statement(client, tenant, url, body, ["MUMB54321K,10.00,x0,194C,15-Jun-2025,F,FY 2025-26 / AY 2026-27"])
    path = f"/api/v1/organizations/{tenant.organization.id}/trinetra/cases"
    assert client.get(path, headers=tenant.owner.headers).status_code == 402                 # Business: an Enterprise capability
    headers = _key(db_session, tenant, ["trinetra:read"])
    result = client.get(path, headers=headers)
    assert result.status_code == 200, result.text
    data = result.json()
    assert data["total"] == 1 and data["is_sample"] is False
    [item] = data["items"]
    assert item["id"] == case["id"] and item["workspace_id"] == str(tenant.workspace.id) and item["reference"] == "TR-API-1"
    assert item["review_state"] == "OPEN" and item["status"] == "POSSIBLE_MISSING_POSTING" and item["revision"] == case["revision"]
    assert item["expected_micros"] == "2000000000" and item["posted_micros"] == "0" and item["gap_micros"] == "2000000000"
    assert item["currency"] == "INR"
    assert "ABCDE1234F" not in result.text and "ABCD12345E" not in result.text and "deductor_key" not in result.text
    assert client.get(path, params={"limit": 1, "offset": 1}, headers=headers).json()["items"] == []
    assert client.get(path, params={"workspace_id": str(uuid.uuid4())}, headers=headers).json()["total"] == 0
    # A key reads; it never writes, never reads another route, and a person's viewer role does not reach it.
    assert client.post(path, headers=headers, json={}).status_code in (403, 405)
    assert client.get(world[0] + "/credits", headers=headers).status_code == 403
    assert client.get(path, headers=tenant.viewer.headers).status_code == 403
