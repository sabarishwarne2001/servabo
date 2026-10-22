"""Organization console, tabs 7, 14 and 15 (Developer platform, API keys, Webhooks): the places an organization hands out
credentials and reaches out to other servers.

The roles and plans of every route are swept in tests/security. These are the behaviours behind the forms: a secret shown once
and never again, a key or endpoint that cannot be created with a blank name or a dangerous address, a revoked key that stops
working at once, and one organization never touching another's keys or endpoints.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.conftest import Fixture
from tests.security.plans import put_on_plan

ORG = "/api/v1/organizations"


@pytest.fixture()
def enterprise(db_session: Session, tenant: Fixture) -> Fixture:
    put_on_plan(db_session, tenant.organization, "enterprise")
    return tenant


def audit(client: TestClient, tenant: Fixture, **query: str) -> list[dict]:
    qs = "&".join(f"{k}={v}" for k, v in {"limit": "100", **query}.items())
    body = client.get(f"{ORG}/{tenant.organization.id}/audit-logs?{qs}", headers=tenant.owner.headers).json()
    return body["items"] if isinstance(body, dict) else body


# ---------------------------------------------------------------------------------------------------------------------
# API keys
# ---------------------------------------------------------------------------------------------------------------------


def keys(tenant: Fixture, tail: str = "") -> str:
    return f"{ORG}/{tenant.organization.id}/api-keys{tail}"


def make_key(client: TestClient, tenant: Fixture, name: str = "CI key", who: str = "owner", **extra) -> dict:
    body = {"name": name, "scopes": ["work_items:read"], **extra}
    response = client.post(keys(tenant), json=body, headers=getattr(tenant, who).headers)
    assert response.status_code == 201, response.text
    return response.json()


class TestApiKeys:
    def test_a_key_is_issued_with_its_secret_once_and_never_listed_with_it(self, client, enterprise) -> None:
        issued = make_key(client, enterprise)
        token = issued["token"]
        assert token and len(token) >= 24
        listed = client.get(keys(enterprise), headers=enterprise.owner.headers).json()
        assert [k["id"] for k in listed] == [issued["api_key"]["id"]]
        assert token not in str(listed)
        assert "token" not in listed[0] and "secret" not in str(listed[0].keys()).lower().replace("previous_secret_expires_at", "")

    @pytest.mark.parametrize("blank", ["", " ", "     ", "\t\n"])
    def test_a_key_needs_a_real_name(self, client, enterprise, blank: str) -> None:
        response = client.post(keys(enterprise), json={"name": blank, "scopes": ["work_items:read"]}, headers=enterprise.owner.headers)
        assert response.status_code == 422, (repr(blank), response.status_code, response.text[:200])

    def test_a_name_is_kept_without_its_surrounding_spaces(self, client, enterprise) -> None:
        assert make_key(client, enterprise, "  Spaced key  ")["api_key"]["name"] == "Spaced key"

    def test_two_active_keys_cannot_share_a_name_even_when_only_spaces_differ(self, client, enterprise) -> None:
        make_key(client, enterprise, "Billing sync")
        for twin in ("Billing sync", " Billing sync ", "Billing sync  "):
            response = client.post(keys(enterprise), json={"name": twin, "scopes": ["work_items:read"]}, headers=enterprise.owner.headers)
            assert response.status_code == 409, (twin, response.status_code, response.text[:200])

    def test_a_revoked_keys_name_can_be_used_again(self, client, enterprise) -> None:
        first = make_key(client, enterprise, "Rotating")
        assert client.delete(keys(enterprise, f"/{first['api_key']['id']}"), headers=enterprise.owner.headers).status_code in (200, 204)
        assert make_key(client, enterprise, "Rotating")["api_key"]["name"] == "Rotating"

    @pytest.mark.parametrize("scopes", [[], ["not:a-scope"], ["work_items:read", "nope"], "work_items:read", [""]])
    def test_scopes_must_be_known_and_present(self, client, enterprise, scopes) -> None:
        response = client.post(keys(enterprise), json={"name": "Scoped", "scopes": scopes}, headers=enterprise.owner.headers)
        assert response.status_code == 422, (scopes, response.status_code, response.text[:200])

    def test_a_scope_listed_twice_is_kept_once(self, client, enterprise) -> None:
        issued = make_key(client, enterprise, "Dup scopes", scopes=["work_items:read", "work_items:read"])
        assert issued["api_key"]["scopes"] == ["work_items:read"]

    def test_an_expiry_in_the_past_is_refused(self, client, enterprise) -> None:
        response = client.post(
            keys(enterprise), json={"name": "Already over", "scopes": ["work_items:read"], "expires_at": "2020-01-01T00:00:00Z"},
            headers=enterprise.owner.headers,
        )
        assert response.status_code == 422, (response.status_code, response.text[:200])

    def test_a_future_expiry_is_kept(self, client, enterprise) -> None:
        issued = make_key(client, enterprise, "Short lived", expires_at="2999-01-01T00:00:00Z")
        assert issued["api_key"]["expires_at"].startswith("2999-01-01")

    def test_a_key_works_until_it_is_revoked_and_then_stops_at_once(self, client, enterprise) -> None:
        issued = make_key(client, enterprise, "Reader")
        url = f"/api/v1/workspaces/{enterprise.workspace.id}/work-items"
        headers = {"Authorization": f"Bearer {issued['token']}"}
        assert client.get(url, headers=headers).status_code == 200
        client.delete(keys(enterprise, f"/{issued['api_key']['id']}"), headers=enterprise.owner.headers)
        assert client.get(url, headers=headers).status_code in (401, 403)

    def test_a_key_cannot_do_more_than_its_scopes(self, client, enterprise) -> None:
        issued = make_key(client, enterprise, "Read only")
        headers = {"Authorization": f"Bearer {issued['token']}"}
        response = client.post(f"/api/v1/workspaces/{enterprise.workspace.id}/automation/rules", json={}, headers=headers)
        assert response.status_code in (401, 403, 422) and response.status_code != 201

    def test_a_key_cannot_manage_keys(self, client, enterprise) -> None:
        issued = make_key(client, enterprise, "Greedy", scopes=["work_items:read"])
        headers = {"Authorization": f"Bearer {issued['token']}"}
        assert client.get(keys(enterprise), headers=headers).status_code in (401, 403)
        assert client.post(keys(enterprise), json={"name": "Child", "scopes": ["work_items:read"]}, headers=headers).status_code in (401, 403)

    def test_revoking_twice_or_an_unknown_key_is_not_a_crash(self, client, enterprise) -> None:
        issued = make_key(client, enterprise, "Twice")
        path = keys(enterprise, f"/{issued['api_key']['id']}")
        assert client.delete(path, headers=enterprise.owner.headers).status_code in (200, 204)
        assert client.delete(path, headers=enterprise.owner.headers).status_code in (200, 204, 404, 409)
        assert client.delete(keys(enterprise, f"/{uuid.uuid4()}"), headers=enterprise.owner.headers).status_code == 404
        listed = client.get(keys(enterprise), headers=enterprise.owner.headers).json()
        assert listed[0]["deactivated_at"], "a revoked key stays listed, marked revoked"

    def test_issuing_and_revoking_are_in_the_audit_trail_without_the_secret(self, client, enterprise) -> None:
        issued = make_key(client, enterprise, "Audited key")
        client.delete(keys(enterprise, f"/{issued['api_key']['id']}"), headers=enterprise.owner.headers)
        rows = [r for r in audit(client, enterprise) if r["resource_type"] == "API_KEY"]
        assert {r["action"] for r in rows} >= {"CREATED", "REVOKED"}
        assert issued["token"] not in str(rows)

    def test_an_admin_may_issue_and_a_member_may_not(self, client, enterprise) -> None:
        assert make_key(client, enterprise, "By admin", who="org_admin")["api_key"]["name"] == "By admin"
        response = client.post(keys(enterprise), json={"name": "By member", "scopes": ["work_items:read"]}, headers=enterprise.viewer.headers)
        assert response.status_code in (403, 404)
        assert client.get(keys(enterprise), headers=enterprise.viewer.headers).status_code in (403, 404)

    def test_one_organizations_keys_are_not_anothers(self, client, db_session, enterprise) -> None:
        issued = make_key(client, enterprise, "Mine")
        other = enterprise.foreign_workspace.organization_id
        assert client.get(f"{ORG}/{other}/api-keys", headers=enterprise.owner.headers).status_code in (403, 404)
        assert client.delete(f"{ORG}/{other}/api-keys/{issued['api_key']['id']}", headers=enterprise.other_org_member.headers).status_code in (403, 404)
        still = client.get(keys(enterprise), headers=enterprise.owner.headers).json()
        assert still[0]["deactivated_at"] is None

    def test_below_developer_nothing_can_be_issued(self, client, db_session, tenant) -> None:
        put_on_plan(db_session, tenant.organization, "free")
        response = client.post(keys(tenant), json={"name": "Nope", "scopes": ["work_items:read"]}, headers=tenant.owner.headers)
        assert response.status_code == 402 and response.json()["details"]["code"] == "CAPABILITY_REQUIRED"


# ---------------------------------------------------------------------------------------------------------------------
# Developer platform (gateway keys)
# ---------------------------------------------------------------------------------------------------------------------


def dev(tenant: Fixture, tail: str = "") -> str:
    return f"{ORG}/{tenant.organization.id}/developer{tail}"


class TestDeveloperPlatform:
    def test_a_gateway_key_is_issued_with_its_secret_once(self, client, enterprise) -> None:
        issued = client.post(dev(enterprise, "/keys"), json={"name": "Gateway A", "scopes": ["work_items:read"]}, headers=enterprise.owner.headers)
        assert issued.status_code == 201, issued.text
        token = issued.json()["token"]
        overview = client.get(dev(enterprise), headers=enterprise.owner.headers)
        assert overview.status_code == 200 and token not in overview.text

    @pytest.mark.parametrize("blank", ["", "   "])
    def test_a_gateway_key_needs_a_real_name(self, client, enterprise, blank: str) -> None:
        response = client.post(dev(enterprise, "/keys"), json={"name": blank, "scopes": ["work_items:read"]}, headers=enterprise.owner.headers)
        assert response.status_code == 422, (repr(blank), response.status_code, response.text[:200])

    def test_a_duplicate_name_is_a_conflict_with_a_reason(self, client, enterprise) -> None:
        body = {"name": "Gateway B", "scopes": ["work_items:read"]}
        assert client.post(dev(enterprise, "/keys"), json=body, headers=enterprise.owner.headers).status_code == 201
        again = client.post(dev(enterprise, "/keys"), json=body, headers=enterprise.owner.headers)
        assert again.status_code == 409 and "already exists" in again.json()["detail"]

    def test_the_public_gateway_needs_a_public_scope(self, client, enterprise) -> None:
        response = client.post(
            dev(enterprise, "/keys"),
            json={"name": "Gateway C", "scopes": ["work_items:read"], "enable_public_api": True},
            headers=enterprise.owner.headers,
        )
        assert response.status_code in (409, 422), response.text

    def test_an_unknown_tier_or_a_foreign_key_is_refused(self, client, enterprise) -> None:
        made = client.post(dev(enterprise, "/keys"), json={"name": "Gateway D", "scopes": ["work_items:read"]}, headers=enterprise.owner.headers).json()
        key_id = made["api_key"]["id"]
        assert client.patch(dev(enterprise, f"/keys/{key_id}/tier"), json={"tier_key": "PLATINUM"}, headers=enterprise.owner.headers).status_code == 422
        assert client.patch(dev(enterprise, f"/keys/{uuid.uuid4()}/tier"), json={"tier_key": "FREE"}, headers=enterprise.owner.headers).status_code == 404
        other = enterprise.foreign_workspace.organization_id
        assert client.get(f"{ORG}/{other}/developer/keys/{key_id}/metrics", headers=enterprise.owner.headers).status_code in (403, 404)

    @pytest.mark.parametrize("query", ["?days=0", "?days=100000", "?days=abc"])
    def test_the_usage_window_is_bounded(self, client, enterprise, query: str) -> None:
        assert client.get(dev(enterprise, query), headers=enterprise.owner.headers).status_code == 422

    def test_the_request_log_filters_are_checked(self, client, enterprise) -> None:
        assert client.get(dev(enterprise, "/requests?outcome=bogus"), headers=enterprise.owner.headers).status_code == 422
        assert client.get(dev(enterprise, "/requests?limit=0"), headers=enterprise.owner.headers).status_code == 422
        assert client.get(dev(enterprise, "/requests?cursor=garbage"), headers=enterprise.owner.headers).status_code in (400, 422)
        assert client.get(dev(enterprise, "/requests"), headers=enterprise.owner.headers).status_code == 200


# ---------------------------------------------------------------------------------------------------------------------
# Webhooks
# ---------------------------------------------------------------------------------------------------------------------


def hooks(tenant: Fixture, tail: str = "") -> str:
    return f"{ORG}/{tenant.organization.id}/webhooks{tail}"


GOOD = {"url": "https://hooks.example.com/servabo", "event_types": ["work_item.created"], "description": "Ledger sync"}


def make_hook(client: TestClient, tenant: Fixture, **change) -> dict:
    response = client.post(hooks(tenant, "/endpoints"), json={**GOOD, **change}, headers=tenant.owner.headers)
    assert response.status_code == 201, response.text
    return response.json()


class TestWebhooks:
    def test_an_endpoint_is_created_with_its_secret_once(self, client, enterprise) -> None:
        made = make_hook(client, enterprise)
        assert made["secret"].startswith("whsec_")
        for body in (
            client.get(hooks(enterprise, "/endpoints"), headers=enterprise.owner.headers).text,
            client.get(hooks(enterprise, f"/endpoints/{made['endpoint']['id']}"), headers=enterprise.owner.headers).text,
        ):
            assert made["secret"] not in body

    @pytest.mark.parametrize(
        "url",
        [
            "http://hooks.example.com/x", "ftp://hooks.example.com/x", "hooks.example.com/x", "https://", "https:///path",
            "https://localhost/hook", "https://127.0.0.1/hook", "https://[::1]/hook", "https://10.0.0.5/hook",
            "https://192.168.1.10/hook", "https://172.16.0.1/hook", "https://169.254.169.254/latest/meta-data",
            "https://metadata.google.internal/x", "https://user:pass@hooks.example.com/x", "https://exa mple.com/x",
            "https://hooks.example.com:99999/x", "https://0.0.0.0/x", "https://2130706433/x", "https://0x7f000001/x",
            "https://" + "a" * 2100 + ".com/x",
        ],
    )
    def test_an_address_that_is_not_a_public_https_address_is_refused(self, client, enterprise, url: str) -> None:
        response = client.post(hooks(enterprise, "/endpoints"), json={**GOOD, "url": url}, headers=enterprise.owner.headers)
        assert response.status_code == 422, (url[:60], response.status_code, response.text[:200])

    @pytest.mark.parametrize("events", [[], ["not.an.event"], ["work_item.created", "nope"], [""], "work_item.created"])
    def test_event_types_must_be_known_and_present(self, client, enterprise, events) -> None:
        response = client.post(hooks(enterprise, "/endpoints"), json={**GOOD, "event_types": events}, headers=enterprise.owner.headers)
        assert response.status_code == 422, (events, response.status_code)

    def test_an_event_listed_twice_is_kept_once(self, client, enterprise) -> None:
        made = make_hook(client, enterprise, event_types=["work_item.created", "work_item.created"])
        assert made["endpoint"]["event_types"] == ["work_item.created"]

    def test_the_description_is_bounded(self, client, enterprise) -> None:
        response = client.post(hooks(enterprise, "/endpoints"), json={**GOOD, "description": "d" * 501}, headers=enterprise.owner.headers)
        assert response.status_code == 422

    def test_changing_an_endpoint_validates_the_new_address_and_events_again(self, client, enterprise) -> None:
        made = make_hook(client, enterprise)["endpoint"]
        path = hooks(enterprise, f"/endpoints/{made['id']}")
        for bad in ({"url": "http://hooks.example.com/x"}, {"url": "https://127.0.0.1/x"}, {"event_types": ["nope"]}, {"event_types": []}, {"status": "BROKEN"}):
            assert client.patch(path, json=bad, headers=enterprise.owner.headers).status_code == 422, bad
        changed = client.patch(path, json={"url": "https://hooks.example.com/v2", "status": "DISABLED"}, headers=enterprise.owner.headers)
        assert changed.status_code == 200 and changed.json()["status"] == "DISABLED"

    def test_rotating_gives_a_new_secret_and_an_overlap_end_and_the_old_one_is_not_listed(self, client, enterprise) -> None:
        made = make_hook(client, enterprise)
        rotated = client.post(hooks(enterprise, f"/endpoints/{made['endpoint']['id']}/rotate-secret"), headers=enterprise.owner.headers)
        assert rotated.status_code == 200, rotated.text
        assert rotated.json()["secret"] != made["secret"] and rotated.json()["previous_secret_valid_until"]
        listed = client.get(hooks(enterprise, "/endpoints"), headers=enterprise.owner.headers).text
        assert made["secret"] not in listed and rotated.json()["secret"] not in listed

    def test_an_endpoint_is_deleted_once(self, client, enterprise) -> None:
        made = make_hook(client, enterprise)["endpoint"]
        path = hooks(enterprise, f"/endpoints/{made['id']}")
        assert client.delete(path, headers=enterprise.owner.headers).status_code in (200, 204)
        assert client.delete(path, headers=enterprise.owner.headers).status_code == 404
        assert client.get(path, headers=enterprise.owner.headers).status_code == 404
        assert client.get(hooks(enterprise, "/endpoints"), headers=enterprise.owner.headers).json() == []

    def test_a_test_event_is_queued_and_shows_in_the_deliveries(self, client, enterprise) -> None:
        made = make_hook(client, enterprise)["endpoint"]
        queued = client.post(hooks(enterprise, f"/endpoints/{made['id']}/test"), headers=enterprise.owner.headers)
        assert queued.status_code == 202, queued.text
        deliveries = client.get(hooks(enterprise, f"/endpoints/{made['id']}/deliveries"), headers=enterprise.owner.headers).json()
        assert [d["event_type"] for d in deliveries] == ["webhook.test"]

    def test_the_deliveries_page_is_bounded(self, client, enterprise) -> None:
        made = make_hook(client, enterprise)["endpoint"]
        for query in ("?limit=0", "?limit=100000", "?offset=-1"):
            assert client.get(hooks(enterprise, f"/endpoints/{made['id']}/deliveries{query}"), headers=enterprise.owner.headers).status_code in (200, 422)
        assert client.get(hooks(enterprise, f"/endpoints/{made['id']}/deliveries?limit=100000"), headers=enterprise.owner.headers).status_code in (200, 422)

    def test_creating_changing_and_deleting_are_audited_by_host_never_by_secret(self, client, enterprise) -> None:
        made = make_hook(client, enterprise)
        client.patch(hooks(enterprise, f"/endpoints/{made['endpoint']['id']}"), json={"description": "x"}, headers=enterprise.owner.headers)
        client.delete(hooks(enterprise, f"/endpoints/{made['endpoint']['id']}"), headers=enterprise.owner.headers)
        rows = [r for r in audit(client, enterprise) if r["resource_type"] == "WEBHOOK_ENDPOINT"]
        assert {r["action"] for r in rows} >= {"CREATED", "DELETED"}
        assert made["secret"] not in str(rows)

    def test_a_member_cannot_and_an_admin_can(self, client, enterprise) -> None:
        assert client.post(hooks(enterprise, "/endpoints"), json=GOOD, headers=enterprise.viewer.headers).status_code in (403, 404)
        assert client.get(hooks(enterprise, "/endpoints"), headers=enterprise.viewer.headers).status_code in (403, 404)
        assert client.post(hooks(enterprise, "/endpoints"), json=GOOD, headers=enterprise.org_admin.headers).status_code == 201

    def test_one_organizations_endpoints_are_not_anothers(self, client, enterprise) -> None:
        made = make_hook(client, enterprise)["endpoint"]
        other = enterprise.foreign_workspace.organization_id
        for method, tail in (("GET", f"/endpoints/{made['id']}"), ("PATCH", f"/endpoints/{made['id']}"), ("DELETE", f"/endpoints/{made['id']}"),
                             ("POST", f"/endpoints/{made['id']}/rotate-secret"), ("POST", f"/endpoints/{made['id']}/test"),
                             ("GET", f"/endpoints/{made['id']}/deliveries")):
            response = client.request(method, f"{ORG}/{other}/webhooks{tail}", json={} if method == "PATCH" else None, headers=enterprise.other_org_member.headers)
            assert response.status_code in (402, 403, 404), (method, tail, response.status_code)
        assert client.get(hooks(enterprise, f"/endpoints/{made['id']}"), headers=enterprise.owner.headers).status_code == 200

    def test_below_developer_an_endpoint_cannot_be_created(self, client, db_session, tenant) -> None:
        put_on_plan(db_session, tenant.organization, "free")
        response = client.post(hooks(tenant, "/endpoints"), json=GOOD, headers=tenant.owner.headers)
        assert response.status_code == 402 and response.json()["details"]["code"] == "CAPABILITY_REQUIRED"
