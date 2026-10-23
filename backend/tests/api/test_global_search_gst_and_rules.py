"""Global search (Ctrl+K) also finds GST suppliers (by GSTIN or name), invoices in the GST books (by invoice number) and
automation rules (by name), each only where the person may look (Final session 1, Phase 5).

* a workspace a person has no grant on contributes nothing, and another organization's member is refused;
* a workspace whose plan does not open the GST supplier and invoice lists contributes no GST result (a locked result shows
  nothing), and a viewer is offered no automation rule (workflows are a contributor's to see, N-019);
* the text is matched literally.

    pytest tests/api/test_global_search_gst_and_rules.py -q
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.workspace import Workspace, WorkspaceMember, WorkspaceRole, WorkspaceStatus
from app.models.organization import MembershipStatus
from app.services.gst import store
from tests.conftest import Fixture
from tests.security.plans import put_on_plan
from tests.services.gst.helpers import SUPPLIER_A, SUPPLIER_B, statement


def search(client: TestClient, tenant: Fixture, q: str, who: str = "owner", **params) -> dict:
    response = client.get(
        f"/api/v1/organizations/{tenant.organization.id}/search", params={"q": q, **params}, headers=getattr(tenant, who).headers
    )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture()
def second_workspace(db_session: Session, tenant: Fixture) -> Workspace:
    workspace = Workspace(organization_id=tenant.organization.id, slug="branch", workspace_name="Branch office", status=WorkspaceStatus.ACTIVE)
    db_session.add(workspace)
    db_session.flush()
    db_session.commit()
    return workspace


@pytest.fixture()
def books(db_session: Session, tenant: Fixture, second_workspace: Workspace) -> Fixture:
    """GSTR-2B statements imported in both workspaces, on a plan that opens the supplier and invoice lists."""
    put_on_plan(db_session, tenant.organization, "business")
    for workspace in (tenant.workspace, second_workspace):
        workspace.timezone = "UTC"
        store.import_file(db_session, workspace=workspace, user_id=tenant.owner.user.id, file_name="gstr2b.json", data=statement())
    db_session.commit()
    return tenant


class TestGstSuppliers:
    def test_a_supplier_is_found_by_its_gstin_and_by_part_of_its_name(self, client, books) -> None:
        by_gstin = search(client, books, SUPPLIER_A.lower())["suppliers"]
        assert {h["workspace_slug"] for h in by_gstin} == {"engineering", "branch"}
        hit = by_gstin[0]
        assert hit["kind"] == "GST_SUPPLIER" and hit["title"] == "Sahyadri Packaging" and hit["reference"] == SUPPLIER_A
        assert hit["subtitle"].startswith(f"GSTIN {SUPPLIER_A}") and "documents" in hit["subtitle"]
        by_name = search(client, books, "deccan plas")["suppliers"]
        assert {h["reference"] for h in by_name} == {SUPPLIER_B} and {h["workspace_name"] for h in by_name} == {"Engineering", "Branch office"}

    def test_a_supplier_is_one_result_per_workspace_not_one_per_invoice(self, client, books) -> None:
        hits = search(client, books, "sahyadri")["suppliers"]
        assert len(hits) == 2
        assert len({h["id"] for h in hits}) == 2

    def test_a_person_granted_one_workspace_finds_only_its_suppliers(self, client, db_session, books, second_workspace) -> None:
        # The contributor holds a grant on "engineering" only.
        hits = search(client, books, "sahyadri", who="contributor")
        assert {h["workspace_slug"] for h in hits["suppliers"]} == {"engineering"}
        assert hits["workspaces_searched"] == 1
        db_session.add(WorkspaceMember(workspace_id=second_workspace.id, user_id=books.contributor.user.id,
                                       role=WorkspaceRole.VIEWER, status=MembershipStatus.ACTIVE))
        db_session.commit()
        assert {h["workspace_slug"] for h in search(client, books, "sahyadri", who="contributor")["suppliers"]} == {"engineering", "branch"}

    def test_a_viewer_reads_gst_so_finds_it(self, client, books) -> None:
        assert search(client, books, "sahyadri", who="viewer")["suppliers"]

    def test_someone_with_no_grant_finds_nothing(self, client, db_session, books) -> None:
        # An organization member with no workspace grant at all.
        hits = search(client, books, "sahyadri", who="ws_admin")
        assert hits["workspaces_searched"] >= 1  # ws_admin holds a grant on engineering
        db_session.query(WorkspaceMember).filter(WorkspaceMember.user_id == books.ws_admin.user.id).delete()
        db_session.commit()
        empty = search(client, books, "sahyadri", who="ws_admin")
        assert empty["workspaces_searched"] == 0 and empty["suppliers"] == [] and empty["gst_invoices"] == []

    def test_below_the_plan_a_gst_result_is_not_shown(self, client, db_session, books) -> None:
        put_on_plan(db_session, books.organization, "free")
        hits = search(client, books, "sahyadri")
        assert hits["suppliers"] == [] and hits["gst_invoices"] == []

    def test_the_sample_company_is_searchable_without_the_plan(self, client, db_session, books) -> None:
        put_on_plan(db_session, books.organization, "free")
        books.workspace.is_sample = True
        db_session.commit()
        hits = search(client, books, "sahyadri")
        assert {h["workspace_slug"] for h in hits["suppliers"]} == {"engineering"}

    def test_another_organizations_member_is_refused(self, client, books) -> None:
        response = client.get(f"/api/v1/organizations/{books.organization.id}/search", params={"q": "sahyadri"}, headers=books.other_org_member.headers)
        assert response.status_code in (403, 404)

    def test_the_text_is_literal(self, client, books) -> None:
        for q in ("%%", "__", "%a", "\\\\"):
            hits = search(client, books, q)
            assert hits["suppliers"] == [] and hits["gst_invoices"] == [] and hits["rules"] == [], q


class TestGstInvoices:
    def test_an_invoice_is_found_by_its_number_with_its_supplier(self, client, books) -> None:
        hits = search(client, books, "inv-1001")["gst_invoices"]
        assert {h["workspace_slug"] for h in hits} == {"engineering", "branch"}
        hit = hits[0]
        assert hit["kind"] == "GST_INVOICE" and hit["title"] == "INV-1001" and hit["reference"] == "INV-1001"
        assert "Sahyadri Packaging" in hit["subtitle"]

    def test_a_part_of_the_number_finds_several(self, client, books) -> None:
        titles = {h["title"] for h in search(client, books, "INV-", limit=20)["gst_invoices"]}
        assert {"INV-1001", "INV-1003", "INV-2001"} <= titles

    def test_the_limit_applies_to_each_list(self, client, books) -> None:
        assert len(search(client, books, "INV-", limit=1)["gst_invoices"]) == 1

    def test_the_workspace_scope_holds_for_invoices_too(self, client, books) -> None:
        hits = search(client, books, "inv-1001", who="contributor")["gst_invoices"]
        assert {h["workspace_slug"] for h in hits} == {"engineering"}

    def test_a_short_query_is_refused(self, client, books) -> None:
        response = client.get(f"/api/v1/organizations/{books.organization.id}/search", params={"q": "x"}, headers=books.owner.headers)
        assert response.status_code == 422


class TestRules:
    def test_a_rule_is_found_by_name_in_its_workspace(self, client, books, rule_factory) -> None:
        rule = rule_factory(name="Chase late GST suppliers")
        hits = search(client, books, "late gst")["rules"]
        assert [(h["kind"], h["id"], h["title"], h["workspace_slug"], h["subtitle"]) for h in hits] == [
            ("RULE", str(rule.id), "Chase late GST suppliers", "engineering", "Active")
        ]

    def test_a_paused_rule_says_so_and_a_deleted_one_is_gone(self, client, db_session, books, rule_factory) -> None:
        paused = rule_factory(name="Quarterly review", is_active=False)
        gone = rule_factory(name="Quarterly cleanup")
        from datetime import datetime, timezone

        gone.deleted_at = datetime.now(timezone.utc)
        db_session.commit()
        hits = search(client, books, "quarterly")["rules"]
        assert [(h["id"], h["subtitle"]) for h in hits] == [(str(paused.id), "Paused")]

    def test_a_contributor_finds_rules_a_viewer_does_not(self, client, books, rule_factory) -> None:
        rule_factory(name="Route big invoices")
        assert [h["title"] for h in search(client, books, "big invoices", who="contributor")["rules"]] == ["Route big invoices"]
        assert [h["title"] for h in search(client, books, "big invoices", who="ws_admin")["rules"]] == ["Route big invoices"]
        assert search(client, books, "big invoices", who="viewer")["rules"] == []

    def test_a_rule_in_a_workspace_the_person_cannot_open_is_never_shown(self, client, books, second_workspace, rule_factory) -> None:
        rule_factory(name="Branch only rule", workspace_id=second_workspace.id)
        assert [h["workspace_slug"] for h in search(client, books, "branch only")["rules"]] == ["branch"]
        assert search(client, books, "branch only", who="contributor")["rules"] == []

    def test_rules_need_no_plan_but_follow_the_role(self, client, db_session, books, rule_factory) -> None:
        put_on_plan(db_session, books.organization, "free")
        rule_factory(name="Free plan workflow")
        assert [h["title"] for h in search(client, books, "free plan workflow")["rules"]] == ["Free plan workflow"]

    def test_the_text_is_literal_for_rules(self, client, books, rule_factory) -> None:
        rule_factory(name="100% match")
        assert [h["title"] for h in search(client, books, "100%")["rules"]] == ["100% match"]
        assert search(client, books, "%%")["rules"] == []
