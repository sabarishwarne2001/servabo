"""GST Credit across every workspace (Enterprise): one reconciliation per GSTIN over the purchase invoices of every
workspace, for organization owners, admins and billing, and for API keys with `gst:read`. Real Postgres, real routes.

  * the books of two workspaces are matched with a return imported in one of them;
  * with one workspace the organization's figures are the workspace's own (the SQL and the in-memory reading agree);
  * roles: owners, admins and billing read; members and strangers are refused; billing's lists are cut to the
    workspaces it has grants on;
  * the plan: 402 without `capability.gst_credit_all_workspaces`, for people and for keys alike;
  * scope: a key with `gst:read` reads the three routes; without it, refused naming the scope; it can do nothing else;
  * isolation: another organization's people and keys see none of it; the sample company is never part of it.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest

from app.models.organization import OrganizationMember, OrganizationRole
from app.models.workspace import Workspace, WorkspaceRole, WorkspaceStatus
from app.services import api_key_service
from app.services.gst import builder as b
from app.services.gst import org as gst_org
from tests.conftest import _grant, _make_user, _seat
from tests.security.plans import put_on_plan
from tests.services.gst.helpers import RECIPIENT, SUPPLIER_A, book_invoice, supplier_invoices

API = "/api/v1"


def statement(documents) -> bytes:
    return b.to_bytes(b.gstr2b(RECIPIENT, "2026-09", {"b2b": [supplier_invoices(documents)]}))


@pytest.fixture()
def world(client, db_session, tenant):
    """Enterprise. Workspace A (Engineering) imported the return; workspace B (Branch) holds more of the purchases."""
    gst_org.forget()
    put_on_plan(db_session, tenant.organization, "enterprise")
    branch = Workspace(organization_id=tenant.organization.id, slug="branch", workspace_name="Branch",
                       status=WorkspaceStatus.ACTIVE)
    db_session.add(branch)
    db_session.flush()
    _grant(db_session, branch, tenant.owner, WorkspaceRole.ADMIN)
    billing = _make_user(db_session, f"billing-{uuid.uuid4().hex[:6]}@acme.com")
    _seat(db_session, tenant.organization, billing, OrganizationRole.BILLING)
    _grant(db_session, tenant.workspace, billing, WorkspaceRole.VIEWER)   # reads Engineering, not Branch
    book_invoice(db_session, tenant, number="A-1", supplier="a", gstin=SUPPLIER_A, on=date(2026, 9, 5), taxable=1000)
    book_invoice(db_session, tenant, number="B-1", supplier="a", gstin=SUPPLIER_A, on=date(2026, 9, 6), taxable=2000,
                 workspace=branch)
    book_invoice(db_session, tenant, number="B-2", supplier="a", gstin=SUPPLIER_A, on=date(2026, 9, 10), taxable=4000,
                 workspace=branch)   # never reported
    db_session.commit()
    sent = client.post(f"{API}/workspaces/{tenant.workspace.id}/gst/returns", headers=tenant.contributor.headers, files={
        "file": ("GSTR2B_092026.json", statement([b.document("A-1", date(2026, 9, 5), 1000),
                                                  b.document("B-1", date(2026, 9, 6), 2000),
                                                  b.document("U-1", date(2026, 9, 7), 300)]))})
    assert sent.status_code == 200, sent.text
    return branch, billing


def org_url(tenant, tail: str) -> str:
    return f"{API}/organizations/{tenant.organization.id}/gst{tail}"


def figures(body) -> dict[str, dict]:
    return {f["key"]: f for f in body["figures"]}


def key_headers(db, tenant, scopes: list[str]) -> dict[str, str]:
    membership = db.query(OrganizationMember).filter_by(organization_id=tenant.organization.id,
                                                        user_id=tenant.owner.user.id).one()
    _row, token = api_key_service.issue_api_key(db, organization_id=tenant.organization.id, actor=membership,
                                                name=f"gst probe {uuid.uuid4().hex[:6]}", scopes=scopes)
    db.commit()
    return {"Authorization": f"Bearer {token}"}


def test_the_books_of_every_workspace_are_matched_with_one_return(client, tenant, world):
    branch, _billing = world
    body = client.get(org_url(tenant, "/summary"), headers=tenant.owner.headers).json()
    f = figures(body)
    assert body["gstin"] == RECIPIENT and body["gstins"] == [RECIPIENT] and body["periods"] == ["2026-09"]
    assert f["claimable_now"]["count"] == 2 and f["claimable_now"]["amount_micros"] == (180 + 360) * 1_000_000
    assert f["waiting"]["count"] == 1 and f["waiting"]["amount_micros"] == 720 * 1_000_000
    assert f["not_in_books"]["count"] == 1 and body["lines"] == 4
    assert {w["workspace_name"]: w["lines"] for w in body["workspaces"]} == {"Engineering": 2, "Branch": 2}
    # the workspace alone cannot see its sibling's invoice: it reports B-1 as missing from its books
    alone = client.get(f"{API}/workspaces/{tenant.workspace.id}/gst/summary", headers=tenant.owner.headers).json()
    assert figures(alone)["not_in_books"]["count"] == 2 and figures(alone)["claimable_now"]["count"] == 1

    records = client.get(org_url(tenant, "/records"), headers=tenant.owner.headers).json()
    by_number = {r["number"]: r for r in records["items"]}
    assert by_number["B-1"]["status"] == "MATCHED" and by_number["B-1"]["workspace_name"] == "Branch"
    assert by_number["B-2"]["status"] == "WAITING_FOR_SUPPLIER" and by_number["B-2"]["workspace_name"] == "Branch"
    assert by_number["U-1"]["status"] == "NOT_IN_BOOKS" and by_number["U-1"]["workspace_name"] == "Engineering"
    only_branch = client.get(org_url(tenant, "/records"), headers=tenant.owner.headers,
                             params={"workspace_id": str(branch.id)}).json()
    assert sorted(r["number"] for r in only_branch["items"]) == ["B-1", "B-2"]
    waiting = client.get(org_url(tenant, "/suppliers"), headers=tenant.owner.headers).json()
    assert waiting["items"][0]["waiting_count"] == 1 and waiting["items"][0]["supplier_gstin"] == SUPPLIER_A


def test_with_one_workspace_the_organizations_figures_are_the_workspaces_own(client, db_session, tenant):
    gst_org.forget()
    put_on_plan(db_session, tenant.organization, "enterprise")
    book_invoice(db_session, tenant, number="A-1", supplier="a", gstin=SUPPLIER_A, on=date(2026, 9, 5), taxable=1000)
    book_invoice(db_session, tenant, number="A-2", supplier="a", gstin=SUPPLIER_A, on=date(2026, 9, 6), taxable=2200)
    book_invoice(db_session, tenant, number="A-3", supplier="a", gstin=SUPPLIER_A, on=date(2026, 9, 8), taxable=900)
    db_session.commit()
    client.post(f"{API}/workspaces/{tenant.workspace.id}/gst/returns", headers=tenant.contributor.headers, files={
        "file": ("g.json", statement([b.document("A-1", date(2026, 9, 5), 1000), b.document("A-2", date(2026, 9, 6), 2000),
                                      b.document("Z-9", date(2026, 9, 9), 800)]))})
    ours = client.get(f"{API}/workspaces/{tenant.workspace.id}/gst/summary", headers=tenant.owner.headers).json()
    org = client.get(org_url(tenant, "/summary"), headers=tenant.owner.headers).json()
    strip = lambda body: {k: (f["amount_micros"], f["count"]) for k, f in figures(body).items()}  # noqa: E731
    assert strip(org) == strip(ours)
    assert (org["suggested"], org["reverse_charge"], org["notes"], org["lines"]) == (
        ours["suggested"], ours["reverse_charge"], ours["notes"], ours["lines"])
    mine = client.get(f"{API}/workspaces/{tenant.workspace.id}/gst/records", headers=tenant.owner.headers,
                      params={"limit": 200}).json()
    theirs = client.get(org_url(tenant, "/records"), headers=tenant.owner.headers, params={"limit": 200}).json()
    assert [(r["number"], r["status"], r["itc_micros"]) for r in theirs["items"]] == [
        (r["number"], r["status"], r["itc_micros"]) for r in mine["items"]]


def test_roles_owners_admins_and_billing_read_everyone_else_is_refused(client, tenant, world):
    _branch, billing = world
    for persona in (tenant.owner, tenant.org_admin, billing):
        assert client.get(org_url(tenant, "/summary"), headers=persona.headers).status_code == 200
    for persona in (tenant.ws_admin, tenant.contributor, tenant.viewer, tenant.non_member, tenant.other_org_member):
        for tail in ("/summary", "/suppliers", "/records"):
            assert client.get(org_url(tenant, tail), headers=persona.headers).status_code in (403, 404), (persona, tail)
    # billing sees the organization's figures, and lists only for the workspace it has a grant on
    body = client.get(org_url(tenant, "/summary"), headers=billing.headers).json()
    assert figures(body)["claimable_now"]["count"] == 2 and len(body["workspaces"]) == 2
    records = client.get(org_url(tenant, "/records"), headers=billing.headers).json()
    assert sorted(r["number"] for r in records["items"]) == ["A-1", "U-1"]
    assert all(r["workspace_name"] == "Engineering" for r in records["items"])
    suppliers = client.get(org_url(tenant, "/suppliers"), headers=billing.headers).json()
    assert all(s["waiting_count"] == 0 for s in suppliers["items"])   # the waiting invoice is in Branch


def test_without_the_enterprise_capability_every_route_asks_for_an_upgrade(client, db_session, tenant, world):
    put_on_plan(db_session, tenant.organization, "business")
    db_session.commit()
    for tail in ("/summary", "/suppliers", "/records"):
        response = client.get(org_url(tenant, tail), headers=tenant.owner.headers)
        assert response.status_code == 402, (tail, response.text)
        assert "capability.gst_credit_all_workspaces" in response.text


def test_an_api_key_needs_gst_read_and_reaches_nothing_else_of_gst(client, db_session, tenant, world):
    others = [s for s in ("organizations:read", "workspaces:read", "work_items:read", "billing:read", "helm:read")]
    blind = key_headers(db_session, tenant, others)
    for tail in ("/summary", "/suppliers", "/records"):
        refused = client.get(org_url(tenant, tail), headers=blind)
        assert refused.status_code == 403 and "gst:read" in refused.text, (tail, refused.text)
    reader = key_headers(db_session, tenant, ["gst:read"])
    for tail in ("/summary", "/suppliers", "/records"):
        assert client.get(org_url(tenant, tail), headers=reader).status_code == 200, tail
    body = client.get(org_url(tenant, "/summary"), headers=reader).json()
    assert figures(body)["claimable_now"]["count"] == 2
    # nothing else: no import, no workspace-level GST route, and no write at all
    ws = f"{API}/workspaces/{tenant.workspace.id}/gst"
    assert client.get(ws + "/summary", headers=reader).status_code == 403
    assert client.post(ws + "/returns", headers=reader, files={"file": ("g.json", b"{}")}).status_code == 403
    assert client.post(org_url(tenant, "/summary"), headers=reader).status_code == 405   # no write route exists
    # the scope is not enough on a plan without the capability
    put_on_plan(db_session, tenant.organization, "business")
    db_session.commit()
    assert client.get(org_url(tenant, "/summary"), headers=reader).status_code == 402


def test_another_organization_sees_none_of_it_and_the_sample_company_is_left_out(client, db_session, tenant, world):
    stranger = client.get(org_url(tenant, "/records"), headers=tenant.other_org_member.headers)
    assert stranger.status_code in (403, 404) and "A-1" not in stranger.text
    # a sample workspace holding its own GSTR-2B does not enter the organization's figures
    sample = Workspace(organization_id=tenant.organization.id, slug="sample", workspace_name="Sample company",
                       status=WorkspaceStatus.ACTIVE, is_sample=True)
    db_session.add(sample)
    db_session.flush()
    from app.services.gst import store

    store.import_file(db_session, workspace=sample, user_id=tenant.owner.user.id, file_name="s.json",
                      data=statement([b.document("S-1", date(2026, 9, 5), 9999)]))
    db_session.commit()
    gst_org.forget()
    body = client.get(org_url(tenant, "/records"), headers=tenant.owner.headers, params={"limit": 200}).json()
    assert "S-1" not in [r["number"] for r in body["items"]] and body["total"] == 4
    assert all(w["workspace_name"] != "Sample company" for w in
               client.get(org_url(tenant, "/summary"), headers=tenant.owner.headers).json()["workspaces"])


def test_a_decision_in_one_workspace_applies_to_the_organizations_reading(client, tenant, world):
    """"Not ours" on a supplier record, decided in the workspace that imported it, leaves the organization's list too."""
    unseen = next(r for r in client.get(org_url(tenant, "/records"), headers=tenant.owner.headers).json()["items"]
                  if r["number"] == "U-1")
    decided = client.post(f"{API}/workspaces/{tenant.workspace.id}/gst/records/{unseen['id']}/decision",
                          headers=tenant.contributor.headers, json={"decision": "NOT_OURS"})
    assert decided.status_code == 200, decided.text
    body = client.get(org_url(tenant, "/summary"), headers=tenant.owner.headers).json()
    assert figures(body)["not_in_books"]["count"] == 0
