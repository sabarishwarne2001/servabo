"""Isolation sweep over every TRINETRA route (Final 2T, Phase 9).

The routes are read from the live OpenAPI document, so a route added later is swept with no edit here, and a completeness check
fails the build if one was not exercised. Workspace A holds a real case, snapshot, inquiry, suggestion, deductor, pairing and
approval. Each route is called with A's real ids by:

* a member of another organization (on Enterprise and live, so a refusal is the tenancy rule, not the plan or the gate),
* a user who belongs to no organization,
* the other organization's own workspace id with A's ids in the path (the id belongs to someone else, so it must read as absent).

None may succeed, and nothing A typed (its case reference, its customer name) may come back. A positive control shows the same
route answers A's own owner, and the platform-admin routes refuse even A's organization owner.
"""

import uuid
from datetime import datetime, timezone

import pytest

from app.core.config import settings
from app.main import app
from app.models.trinetra import TrinetraApproval, TrinetraDeductor, TrinetraPairing, TrinetraSuggestion
from tests.security.plans import put_on_plan
from tests.trinetra.test_api import world  # noqa: F401
from tests.trinetra.test_money_model import statement
from tests.trinetra.test_resolution import customer, draft, mailbox  # noqa: F401
from tests.trinetra.test_workflows import setup_case

SECRET_REFERENCE = "TR-ISO-ALPHA"
SECRET_NAME = "Synthetic deductor"
ADMIN_PREFIX = "/api/v1/admin/trinetra"
ROUTES = sorted(
    (method.upper(), path)
    for path, operations in app.openapi()["paths"].items()
    if "/trinetra" in path
    for method in operations
    if method in {"get", "post", "put", "patch", "delete"}
)
EXERCISED: set[tuple[str, str]] = set()


@pytest.fixture()
def seeded(client, tenant, world, db_session, mailbox, monkeypatch):  # noqa: F811
    put_on_plan(db_session, tenant.organization, "enterprise")
    from app.models.organization import Organization

    foreign_org = db_session.get(Organization, tenant.foreign_workspace.organization_id)
    put_on_plan(db_session, foreign_org, "enterprise")
    monkeypatch.setattr(settings, "TRINETRA_LIVE_ENABLED", True)

    url, body, case = setup_case(client, tenant, world, reference=SECRET_REFERENCE)
    customer(db_session, tenant, name=SECRET_NAME)
    snap = statement(client, tenant, url, body, ["ZZZZ99999Z,10.00,x0,194C,15-Jun-2025,F,FY 2025-26 / AY 2026-27",
                                        "ZZZZ99999Z,-10.00,x1,194C,16-Jun-2025,F,FY 2025-26 / AY 2026-27"])
    inquiry = draft(client, tenant, url, case, document_kind="CERTIFICATE")
    assert inquiry.status_code in (200, 201), inquiry.text

    common = dict(organization_id=tenant.organization.id, workspace_id=tenant.workspace.id)
    suggestion = TrinetraSuggestion(**common, profile_id=uuid.UUID(body["profile_id"]), work_item_id=uuid.UUID(body["work_item_id"]),
                                    year=2025, source="TEMPLATE", amount_micros=2_000_000_000, counterparty=SECRET_NAME,
                                    reference=SECRET_REFERENCE, source_version="v", content_hash="h" * 64, status="OPEN")
    deductor = TrinetraDeductor(**common, profile_id=uuid.UUID(body["profile_id"]), deductor_key="k" * 64, tan_masked="******345E",
                                counterparty_key="synthetic deductor", counterparty_name=SECRET_NAME, status="PROPOSED")
    pairing = TrinetraPairing(**common, profile_id=uuid.UUID(body["profile_id"]), statement_id=uuid.UUID(snap), positive_line=0,
                              negative_line=1, reason="A reason typed by A.")
    approval = TrinetraApproval(**common, credit_id=uuid.UUID(case["id"]), action="CA_REVIEWED", reason="A reason typed by A.",
                                amount_micros=2_000_000_000, case_revision=1, approver_role="OWNER", status="PENDING")
    db_session.add_all([suggestion, deductor, pairing, approval])
    db_session.commit()
    return {
        "workspace_id": str(tenant.workspace.id),
        "organization_id": str(tenant.organization.id),
        "credit_id": case["id"],
        "inquiry_id": inquiry.json()["id"],
        "suggestion_id": str(suggestion.id),
        "deductor_id": str(deductor.id),
        "pairing_id": str(pairing.id),
        "approval_id": str(approval.id),
        "job_id": str(uuid.uuid4()),
        "format": "csv",
    }


def fill(path: str, ids: dict, *, workspace: str | None = None, organization: str | None = None) -> str:
    values = dict(ids)
    if workspace:
        values["workspace_id"] = workspace
    if organization:
        values["organization_id"] = organization
    return path.format(**values)


def call(client, method, url, headers):
    kwargs = {"headers": headers}
    if method in {"POST", "PUT", "PATCH"}:
        kwargs["json"] = {}
    return client.request(method, url, **kwargs)


def leaks(text: str) -> bool:
    return SECRET_REFERENCE in text or SECRET_NAME in text


@pytest.mark.parametrize("method,path", ROUTES, ids=[f"{m} {p.split('/trinetra', 1)[1] or '/'}" for m, p in ROUTES])
def test_a_route_refuses_everyone_outside_the_workspace(client, tenant, seeded, method, path):
    EXERCISED.add((method, path))
    strangers = {"other organization": tenant.other_org_member, "no organization": tenant.non_member}
    for who, persona in strangers.items():
        response = call(client, method, fill(path, seeded), persona.headers)
        assert response.status_code in (401, 403, 404), f"{who}: {method} {path} -> {response.status_code}"
        assert not leaks(response.text), f"{who}: {method} {path} returned A's data"

    # The other organization's own workspace or organization id with A's object ids in the path: absent, never A's row.
    own_workspace = str(tenant.foreign_workspace.id)
    own_organization = str(tenant.foreign_workspace.organization_id)
    response = call(client, method, fill(path, seeded, workspace=own_workspace, organization=own_organization),
                    tenant.other_org_member.headers)
    assert not leaks(response.text), f"cross-id: {method} {path} returned A's data"
    if "{credit_id}" in path or "{inquiry_id}" in path or "{suggestion_id}" in path or "{deductor_id}" in path \
            or "{pairing_id}" in path or "{approval_id}" in path:
        assert response.status_code in (403, 404, 422), f"cross-id: {method} {path} -> {response.status_code}"

    # A's organization route with the other organization's persona is refused; the platform-admin routes refuse A's own owner.
    if path.startswith(ADMIN_PREFIX):
        response = call(client, method, fill(path, seeded), tenant.owner.headers)
        assert response.status_code in (401, 403, 404), f"owner: {method} {path} -> {response.status_code}"


def test_the_same_routes_answer_the_owner_of_the_workspace(client, tenant, seeded):
    """Positive control: the refusals above are about who is asking, not a route that is broken for everyone."""
    answered = 0
    for method, path in ROUTES:
        if method != "GET" or path.startswith(ADMIN_PREFIX) or "{job_id}" in path:
            continue
        response = client.get(fill(path, seeded), headers=tenant.owner.headers)
        assert response.status_code == 200, f"owner: GET {path} -> {response.status_code} {response.text[:120]}"
        answered += 1
    assert answered >= 20
    listing = client.get(fill("/api/v1/workspaces/{workspace_id}/trinetra/credits", seeded), headers=tenant.owner.headers)
    assert SECRET_REFERENCE in listing.text


def test_the_other_organizations_own_views_never_contain_this_organizations_cases(client, tenant, seeded):
    own = str(tenant.foreign_workspace.organization_id)
    for path in ("/summary", "/cases", "/access"):
        response = client.get(f"/api/v1/organizations/{own}/trinetra{path}", headers=tenant.other_org_member.headers)
        assert not leaks(response.text), path
    for path in ("/summary", "/credits", "/suggestions", "/deductors", "/exceptions", "/outcomes", "/approvals", "/profiles"):
        response = client.get(f"/api/v1/workspaces/{tenant.foreign_workspace.id}/trinetra{path}", headers=tenant.other_org_member.headers)
        assert not leaks(response.text), path


def test_the_sweep_covers_every_trinetra_route():
    """Runs last in this file: every route in the OpenAPI document was swept by the parametrized test above."""
    assert len(ROUTES) >= 50
    missing = set(ROUTES) - EXERCISED
    if len(EXERCISED) == 0:
        pytest.skip("run the whole file: the sweep records the routes it exercised")
    assert not missing, sorted(missing)
