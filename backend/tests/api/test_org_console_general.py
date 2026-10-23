"""Organization console, tab 1 (General): the name is a real name, and who may change it.

Found by the browser pass over the organization tabs (Final session 1, F-581): the API accepted a name made of
spaces and kept leading and trailing spaces, so an organization could be saved with a blank-looking name that
then showed as an empty heading, an empty switcher entry and an empty sender on its invitations.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.conftest import Fixture


def url(tenant: Fixture) -> str:
    return f"/api/v1/organizations/{tenant.organization.id}"


@pytest.mark.parametrize("blank", ["", " ", "     ", "\t", "\n  \t"])
def test_a_name_of_spaces_is_refused_and_the_old_name_stays(client: TestClient, tenant: Fixture, blank: str) -> None:
    before = client.get(url(tenant), headers=tenant.owner.headers).json()["name"]
    response = client.patch(url(tenant), json={"name": blank}, headers=tenant.owner.headers)
    assert response.status_code == 422, response.text
    assert client.get(url(tenant), headers=tenant.owner.headers).json()["name"] == before


def test_a_name_is_kept_without_its_surrounding_spaces(client: TestClient, tenant: Fixture) -> None:
    response = client.patch(url(tenant), json={"name": "  Padded Name \t"}, headers=tenant.owner.headers)
    assert response.status_code == 200, response.text
    assert response.json()["name"] == "Padded Name"


def test_markup_in_a_name_is_kept_as_text_not_removed_or_run(client: TestClient, tenant: Fixture) -> None:
    # The page and the emails escape it; the API stores what was typed.
    response = client.patch(url(tenant), json={"name": "R&D <b>Ltd</b>"}, headers=tenant.owner.headers)
    assert response.status_code == 200, response.text
    assert response.json()["name"] == "R&D <b>Ltd</b>"


def test_the_longest_name_is_150_characters(client: TestClient, tenant: Fixture) -> None:
    assert client.patch(url(tenant), json={"name": "n" * 150}, headers=tenant.owner.headers).status_code == 200
    assert client.patch(url(tenant), json={"name": "n" * 151}, headers=tenant.owner.headers).status_code == 422


def test_a_new_organization_cannot_be_created_with_a_blank_name(client: TestClient, tenant: Fixture) -> None:
    response = client.post(
        "/api/v1/organizations",
        json={"organization_name": "   ", "workspace_name": "Main"},
        headers=tenant.non_member.headers,
    )
    assert response.status_code == 422, response.text


def test_a_blank_workspace_name_falls_back_to_the_default_instead_of_being_kept_blank(
    client: TestClient, tenant: Fixture
) -> None:
    response = client.post(
        "/api/v1/organizations",
        json={"organization_name": "Fresh Co", "workspace_name": "    "},
        headers=tenant.non_member.headers,
    )
    assert response.status_code == 201, response.text
    workspaces = client.get(
        f"/api/v1/organizations/{response.json()['id']}/workspaces", headers=tenant.non_member.headers
    ).json()
    names = [item["workspace_name"] for item in (workspaces["items"] if isinstance(workspaces, dict) else workspaces)]
    assert names and all(name.strip() for name in names), names


def test_an_update_with_no_name_leaves_it_alone(client: TestClient, tenant: Fixture) -> None:
    before = client.get(url(tenant), headers=tenant.owner.headers).json()["name"]
    response = client.patch(url(tenant), json={"legal_name": "Acme Private Limited"}, headers=tenant.owner.headers)
    assert response.status_code == 200, response.text
    assert response.json()["name"] == before
    assert response.json()["legal_name"] == "Acme Private Limited"


def test_a_change_is_written_to_the_audit_trail_with_who_made_it(
    client: TestClient, db_session: Session, tenant: Fixture
) -> None:
    client.patch(url(tenant), json={"name": "Audited Name"}, headers=tenant.org_admin.headers)
    listed = client.get(f"{url(tenant)}/audit-logs?limit=20", headers=tenant.owner.headers).json()
    rows = listed["items"] if isinstance(listed, dict) else listed
    updates = [row for row in rows if row["action"] == "UPDATED" and row["resource_type"] == "ORGANIZATION"]
    assert updates, rows
    assert updates[0]["actor_id"] == str(tenant.org_admin.user.id)
    assert updates[0]["details"]["name"] == "Audited Name"


@pytest.mark.parametrize("who", ["ws_admin", "contributor", "viewer", "non_member", "other_org_member"])
def test_only_owners_and_admins_can_rename(client: TestClient, tenant: Fixture, who: str) -> None:
    response = client.patch(url(tenant), json={"name": "Hijacked"}, headers=getattr(tenant, who).headers)
    assert response.status_code in (403, 404), response.text
    assert client.get(url(tenant), headers=tenant.owner.headers).json()["name"] != "Hijacked"


def test_a_member_can_read_the_organization_but_an_outsider_cannot(client: TestClient, tenant: Fixture) -> None:
    assert client.get(url(tenant), headers=tenant.viewer.headers).status_code == 200
    assert client.get(url(tenant), headers=tenant.other_org_member.headers).status_code in (403, 404)
