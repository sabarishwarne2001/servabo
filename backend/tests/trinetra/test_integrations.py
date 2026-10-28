"""TRINETRA woven into the rest of Servabo (Final 2T, Phase 7): Getting started, search, notifications, the digest, the value receipt,
automation, the public API, the warehouse, the organization view, Recoveries, Helm and the Enterprise controls."""

from datetime import datetime, timezone

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
