"""Organization console, tabs 2 and 3 (Notifications and Members): the feed a person sees, and who may change whom.

The role rules are swept for every route in tests/security/test_role_matrix.py; these are the behaviours behind the two
tabs: the filters and pages of the feed, a notice that belongs to someone else staying invisible, a role change telling the
person it happened to, and the organization never being left without an owner.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.notification import (
    Notification,
    NotificationChannel,
    NotificationPriority,
    NotificationType,
)
from tests.conftest import Fixture

PREFIX = "/api/v1/organizations"


def _note(db: Session, *, organization_id, user_id, title: str, kind=NotificationType.SYSTEM, read=False) -> Notification:
    row = Notification(
        title=title,
        message=f"{title} (message)",
        notification_type=kind,
        priority=NotificationPriority.INFO,
        delivery_channel=NotificationChannel.IN_APP,
        workspace_id=None,
        organization_id=organization_id,
        user_id=user_id,
        is_read=read,
    )
    db.add(row)
    db.flush()
    return row


@pytest.fixture()
def feed(db_session: Session, tenant: Fixture) -> dict[str, list[Notification]]:
    org, user = tenant.organization.id, tenant.owner.user.id
    rows: dict[str, list[Notification]] = {"system": [], "security": [], "email": []}
    for index in range(18):
        rows["system"].append(_note(db_session, organization_id=org, user_id=user, title=f"sys {index:02d}"))
    for index in range(6):
        rows["security"].append(
            _note(db_session, organization_id=org, user_id=user, title=f"sec {index}", kind=NotificationType.SECURITY,
                  read=index % 2 == 0)
        )
    for index in range(3):
        rows["email"].append(
            _note(db_session, organization_id=org, user_id=user, title=f"mail {index}", kind=NotificationType.EMAIL)
        )
    db_session.commit()
    return rows


def _get(client: TestClient, tenant: Fixture, query: str = "", who="owner"):
    return client.get(f"{PREFIX}/{tenant.organization.id}/notifications{query}", headers=getattr(tenant, who).headers)


class TestNotifications:
    def test_the_first_page_has_the_totals_and_the_unread_count(self, client, tenant, feed) -> None:
        body = _get(client, tenant, "?limit=10").json()
        assert (body["total"], body["limit"], body["offset"]) == (27, 10, 0)
        assert len(body["items"]) == 10
        assert body["unread_count"] == 24  # three of the six security notices are already read

    def test_pages_do_not_overlap_and_together_hold_everything(self, client, tenant, feed) -> None:
        seen: list[str] = []
        for offset in (0, 10, 20):
            seen += [n["id"] for n in _get(client, tenant, f"?limit=10&offset={offset}").json()["items"]]
        assert len(seen) == 27 and len(set(seen)) == 27

    def test_a_page_past_the_end_is_empty_but_still_reports_the_total(self, client, tenant, feed) -> None:
        body = _get(client, tenant, "?limit=10&offset=100").json()
        assert body["items"] == [] and body["total"] == 27

    @pytest.mark.parametrize("query", ["?limit=0", "?limit=100000", "?offset=-1", "?is_read=maybe", "?notification_type=NOPE"])
    def test_nonsense_filters_are_refused_not_ignored(self, client, tenant, feed, query: str) -> None:
        assert _get(client, tenant, query).status_code == 422

    def test_the_category_and_unread_filters_combine(self, client, tenant, feed) -> None:
        security = _get(client, tenant, "?notification_type=SECURITY").json()
        assert security["total"] == 6
        unread_security = _get(client, tenant, "?notification_type=SECURITY&is_read=false").json()
        assert unread_security["total"] == 3
        assert {n["is_read"] for n in unread_security["items"]} == {False}
        assert _get(client, tenant, "?notification_type=DOCUMENT").json()["total"] == 0

    def test_the_newest_notice_comes_first(self, client, tenant, feed) -> None:
        stamps = [n["created_at"] for n in _get(client, tenant, "?limit=25").json()["items"]]
        assert stamps == sorted(stamps, reverse=True)

    def test_a_notice_can_be_marked_read_and_unread_again(self, client, tenant, feed) -> None:
        target = feed["system"][0]
        url = f"{PREFIX}/{tenant.organization.id}/notifications/{target.id}"
        assert client.patch(url, json={"is_read": True}, headers=tenant.owner.headers).json()["is_read"] is True
        assert _get(client, tenant).json()["unread_count"] == 23
        assert client.patch(url, json={"is_read": True}, headers=tenant.owner.headers).status_code == 200  # again: no change
        assert client.patch(url, json={"is_read": False}, headers=tenant.owner.headers).json()["is_read"] is False
        assert _get(client, tenant).json()["unread_count"] == 24

    def test_a_marking_with_no_state_is_refused(self, client, tenant, feed) -> None:
        url = f"{PREFIX}/{tenant.organization.id}/notifications/{feed['system'][0].id}"
        assert client.patch(url, json={}, headers=tenant.owner.headers).status_code == 422

    def test_everyone_sees_only_their_own_feed(self, client, tenant, feed) -> None:
        assert _get(client, tenant, who="org_admin").json()["total"] == 0
        assert _get(client, tenant, who="viewer").json()["total"] == 0

    def test_someone_elses_notice_cannot_be_read_or_marked(self, client, tenant, feed) -> None:
        url = f"{PREFIX}/{tenant.organization.id}/notifications/{feed['system'][0].id}"
        assert client.patch(url, json={"is_read": True}, headers=tenant.org_admin.headers).status_code == 404
        assert _get(client, tenant).json()["unread_count"] == 24

    def test_a_notice_from_another_organization_is_not_in_this_feed_or_markable_through_it(
        self, client, db_session, tenant, feed
    ) -> None:
        other = tenant.foreign_workspace.organization_id
        stray = _note(db_session, organization_id=other, user_id=tenant.owner.user.id, title="from the other org")
        db_session.commit()
        titles = {n["title"] for n in _get(client, tenant, "?limit=100").json()["items"]}
        assert "from the other org" not in titles
        url = f"{PREFIX}/{tenant.organization.id}/notifications/{stray.id}"
        assert client.patch(url, json={"is_read": True}, headers=tenant.owner.headers).status_code == 404

    def test_an_unknown_notice_is_not_found(self, client, tenant, feed) -> None:
        url = f"{PREFIX}/{tenant.organization.id}/notifications/{uuid.uuid4()}"
        assert client.patch(url, json={"is_read": True}, headers=tenant.owner.headers).status_code == 404

    def test_outsiders_and_signed_out_callers_get_nothing(self, client, tenant, feed) -> None:
        assert _get(client, tenant, who="non_member").status_code in (403, 404)
        assert _get(client, tenant, who="other_org_member").status_code in (403, 404)
        url = f"{PREFIX}/{tenant.organization.id}/notifications"
        assert client.get(url).status_code == 401


def _members(client: TestClient, tenant: Fixture, who="owner", query="") -> dict:
    response = client.get(f"{PREFIX}/{tenant.organization.id}/members{query}", headers=getattr(tenant, who).headers)
    assert response.status_code == 200, response.text
    return response.json()


def _membership(client: TestClient, tenant: Fixture, persona: str) -> str:
    email = getattr(tenant, persona).user.email
    return next(m["id"] for m in _members(client, tenant)["items"] if m["user"]["email"] == email)


def _change(client: TestClient, tenant: Fixture, actor: str, persona: str, role: str):
    return client.patch(
        f"{PREFIX}/{tenant.organization.id}/members/{_membership(client, tenant, persona)}",
        json={"role": role}, headers=getattr(tenant, actor).headers,
    )


def _remove(client: TestClient, tenant: Fixture, actor: str, persona: str):
    return client.post(
        f"{PREFIX}/{tenant.organization.id}/members/{_membership(client, tenant, persona)}/deactivate",
        headers=getattr(tenant, actor).headers,
    )


class TestMembers:
    def test_the_directory_lists_everyone_with_their_role_and_the_seats_used(self, client, tenant) -> None:
        body = _members(client, tenant)
        roles = {m["user"]["email"]: m["role"] for m in body["items"]}
        assert roles[tenant.owner.user.email] == "OWNER"
        assert roles[tenant.org_admin.user.email] == "ADMIN"
        assert roles[tenant.viewer.user.email] == "MEMBER"
        assert body["total"] == 5 == len(body["items"])
        assert body["seats_consumed"] >= 5

    def test_a_plain_member_can_read_the_directory_but_not_see_removed_people(self, client, tenant) -> None:
        assert _members(client, tenant, who="viewer")["total"] == 5
        response = client.get(f"{PREFIX}/{tenant.organization.id}/members?include_inactive=true", headers=tenant.viewer.headers)
        assert response.status_code in (403, 404), response.text

    def test_the_owner_can_make_a_member_an_admin_and_back(self, client, tenant) -> None:
        assert _change(client, tenant, "owner", "contributor", "ADMIN").json()["role"] == "ADMIN"
        assert _change(client, tenant, "owner", "contributor", "MEMBER").json()["role"] == "MEMBER"

    def test_the_person_whose_role_changed_is_told_in_their_own_feed(self, client, tenant) -> None:
        _change(client, tenant, "owner", "contributor", "ADMIN")
        feed = _get(client, tenant, "?notification_type=SECURITY", who="contributor").json()
        assert feed["total"] == 1
        note = feed["items"][0]
        assert "role" in note["title"].lower() and "MEMBER to ADMIN" in note["message"]
        assert _get(client, tenant, who="owner").json()["total"] == 0

    def test_an_admin_cannot_make_anyone_an_owner_or_change_the_owner(self, client, tenant) -> None:
        assert _change(client, tenant, "org_admin", "contributor", "OWNER").status_code == 403
        assert _change(client, tenant, "org_admin", "owner", "MEMBER").status_code == 403
        assert _members(client, tenant)["items"][0] is not None
        roles = {m["user"]["email"]: m["role"] for m in _members(client, tenant)["items"]}
        assert roles[tenant.owner.user.email] == "OWNER" and roles[tenant.contributor.user.email] == "MEMBER"

    def test_a_refused_change_is_recorded_as_denied_in_the_audit_trail(self, client, tenant) -> None:
        _change(client, tenant, "org_admin", "contributor", "OWNER")
        rows = client.get(f"{PREFIX}/{tenant.organization.id}/audit-logs?limit=20", headers=tenant.owner.headers).json()
        rows = rows["items"] if isinstance(rows, dict) else rows
        denied = [r for r in rows if r["action"] == "ROLE_CHANGED" and r["outcome"] == "DENIED"]
        assert denied and denied[0]["details"]["attempted_role"] == "OWNER"

    def test_nobody_changes_their_own_role(self, client, tenant) -> None:
        response = _change(client, tenant, "owner", "owner", "ADMIN")
        assert response.status_code in (400, 403, 409, 422), response.text
        assert {m["user"]["email"]: m["role"] for m in _members(client, tenant)["items"]}[tenant.owner.user.email] == "OWNER"

    def test_the_organization_is_never_left_without_an_owner(self, client, tenant) -> None:
        # Two owners are peers: neither can demote the other (that is what ownership transfer is for) ...
        assert _change(client, tenant, "owner", "org_admin", "OWNER").status_code == 200
        assert _change(client, tenant, "org_admin", "owner", "MEMBER").status_code == 403
        # ... one may leave while the other stays, and the one who stays can never leave or be removed.
        assert client.post(f"{PREFIX}/{tenant.organization.id}/leave", headers=tenant.owner.headers).status_code == 200
        assert client.post(f"{PREFIX}/{tenant.organization.id}/leave", headers=tenant.org_admin.headers).status_code in (400, 403, 409)
        owners = [m for m in _members(client, tenant, who="org_admin")["items"] if m["role"] == "OWNER"]
        assert [m["user"]["email"] for m in owners] == [tenant.org_admin.user.email]

    def test_the_last_owner_cannot_be_removed(self, client, tenant) -> None:
        assert _remove(client, tenant, "org_admin", "owner").status_code in (403, 409)
        assert any(m["role"] == "OWNER" for m in _members(client, tenant)["items"])

    def test_removing_a_member_frees_their_seat_and_hides_them_unless_asked(self, client, tenant) -> None:
        before = _members(client, tenant)["seats_consumed"]
        assert _remove(client, tenant, "owner", "viewer").status_code == 200
        after = _members(client, tenant)
        assert tenant.viewer.user.email not in {m["user"]["email"] for m in after["items"]}
        assert after["seats_consumed"] == before - 1
        everyone = _members(client, tenant, query="?include_inactive=true")
        gone = next(m for m in everyone["items"] if m["user"]["email"] == tenant.viewer.user.email)
        assert gone["status"] != "ACTIVE" and gone["deactivated_at"]

    def test_a_removed_member_loses_access_at_once(self, client, tenant) -> None:
        assert client.get(f"{PREFIX}/{tenant.organization.id}", headers=tenant.viewer.headers).status_code == 200
        _remove(client, tenant, "owner", "viewer")
        assert client.get(f"{PREFIX}/{tenant.organization.id}", headers=tenant.viewer.headers).status_code in (401, 403, 404)

    def test_an_admin_can_remove_a_member_but_not_the_owner_or_another_admin_peer_rules_hold(self, client, tenant) -> None:
        assert _remove(client, tenant, "org_admin", "contributor").status_code == 200
        assert _remove(client, tenant, "org_admin", "owner").status_code in (403, 409)

    def test_nobody_removes_themselves_through_the_remove_route(self, client, tenant) -> None:
        assert _remove(client, tenant, "org_admin", "org_admin").status_code in (400, 403, 409)

    def test_a_plain_member_cannot_remove_or_promote_anyone(self, client, tenant) -> None:
        assert _remove(client, tenant, "viewer", "contributor").status_code in (403, 404)
        assert _change(client, tenant, "viewer", "contributor", "ADMIN").status_code in (403, 404)

    def test_a_membership_from_another_organization_is_not_reachable_through_this_one(self, client, tenant) -> None:
        other_org = tenant.foreign_workspace.organization_id
        foreign = client.get(f"{PREFIX}/{other_org}/members", headers=tenant.other_org_member.headers).json()["items"][0]["id"]
        response = client.patch(
            f"{PREFIX}/{tenant.organization.id}/members/{foreign}", json={"role": "ADMIN"}, headers=tenant.owner.headers
        )
        assert response.status_code in (400, 404), response.text
        response = client.post(f"{PREFIX}/{tenant.organization.id}/members/{foreign}/deactivate", headers=tenant.owner.headers)
        assert response.status_code in (400, 404), response.text

    def test_a_role_that_does_not_exist_is_refused(self, client, tenant) -> None:
        for role in ("SUPERUSER", "", "owner"):
            assert _change(client, tenant, "owner", "contributor", role).status_code == 422

    def test_a_member_can_leave_but_the_only_owner_cannot(self, client, tenant) -> None:
        assert client.post(f"{PREFIX}/{tenant.organization.id}/leave", headers=tenant.owner.headers).status_code in (400, 403, 409)
        assert client.post(f"{PREFIX}/{tenant.organization.id}/leave", headers=tenant.viewer.headers).status_code == 200
        assert tenant.viewer.user.email not in {m["user"]["email"] for m in _members(client, tenant)["items"]}
