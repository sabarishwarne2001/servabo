"""Organization console, tabs 16 and 17 (Enterprise identity, Audit log): the claims an organization makes about its sign-in and the
record it keeps of what happened.

Roles and plans for every route are swept in tests/security. These are the behaviours behind the forms: a domain claimed only in a
usable form and only once, a security policy that refuses what would lock the organization out, secrets shown once, and an audit
trail that can be filtered and exported but never changed or read across organizations.
"""

from __future__ import annotations

import csv
import io
import json
import uuid
from datetime import datetime, timedelta, timezone

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


def ident(tenant: Fixture, tail: str = "") -> str:
    return f"{ORG}/{tenant.organization.id}/identity{tail}"


def logs(tenant: Fixture, tail: str = "") -> str:
    return f"{ORG}/{tenant.organization.id}/audit-logs{tail}"


def not_theirs(client: TestClient, tenant: Fixture, method: str, tail: str, **kw) -> None:
    other = tenant.foreign_workspace.organization_id
    response = client.request(method, f"{ORG}/{other}{tail}", headers=tenant.owner.headers, **kw)
    assert response.status_code in (402, 403, 404), (method, tail, response.status_code)


# ---------------------------------------------------------------------------------------------------------------------
# Enterprise identity
# ---------------------------------------------------------------------------------------------------------------------


class TestIdentityDomains:
    def test_a_claimed_domain_comes_back_pending_with_the_record_to_publish(self, client, enterprise) -> None:
        response = client.post(ident(enterprise, "/domains"), json={"domain": "Acme-Corp.co.uk"}, headers=enterprise.owner.headers)
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["domain"] == "acme-corp.co.uk" and body["status"] in ("PENDING", "UNVERIFIED")
        assert body["expected_txt_record"]
        assert client.get(ident(enterprise, "/domains"), headers=enterprise.owner.headers).json()[0]["domain"] == "acme-corp.co.uk"

    @pytest.mark.parametrize(
        "domain",
        ["", "   ", "a", "com", "co.uk", "localhost", "-bad.example.com", "bad-.example.com", "bad..example.com",
         "exa mple.com", "192.168.1.1", "10.0.0.1", "[::1]", "*.example.com", "x" * 300 + ".com", "exa_mple.co.uk",
         "example.invalid", "example.local", "example.internal", "example.localhost", "example.test"],
    )
    def test_only_a_real_registrable_domain_can_be_claimed(self, client, enterprise, domain: str) -> None:
        response = client.post(ident(enterprise, "/domains"), json={"domain": domain}, headers=enterprise.owner.headers)
        assert response.status_code in (400, 422), (domain[:40], response.status_code, response.text[:200])
        assert client.get(ident(enterprise, "/domains"), headers=enterprise.owner.headers).json() == []

    def test_a_pasted_address_is_reduced_to_its_domain(self, client, enterprise) -> None:
        for pasted in ("https://Normalised-Co.co.uk/some/path", "user@normalised-co.co.uk", "normalised-co.co.uk:8443", " NORMALISED-CO.CO.UK. "):
            response = client.post(ident(enterprise, "/domains"), json={"domain": pasted}, headers=enterprise.owner.headers)
            assert response.status_code == 201 and response.json()["domain"] == "normalised-co.co.uk", (pasted, response.text[:200])
        assert len(client.get(ident(enterprise, "/domains"), headers=enterprise.owner.headers).json()) == 1

    def test_a_missing_or_wrongly_typed_domain_is_refused_not_a_crash(self, client, enterprise) -> None:
        for body in ({}, {"domain": None}, {"domain": 5}, {"domain": ["a.com"]}, {"domains": "a.com"}):
            response = client.post(ident(enterprise, "/domains"), json=body, headers=enterprise.owner.headers)
            assert response.status_code in (400, 422), (body, response.status_code, response.text[:200])

    def test_the_same_domain_is_claimed_once_per_organization(self, client, enterprise) -> None:
        first = client.post(ident(enterprise, "/domains"), json={"domain": "dupe-claim.co.uk"}, headers=enterprise.owner.headers)
        again = client.post(ident(enterprise, "/domains"), json={"domain": " DUPE-CLAIM.co.uk "}, headers=enterprise.owner.headers)
        assert first.status_code == 201 and again.status_code in (200, 201), again.text
        assert again.json()["id"] == first.json()["id"], "a second claim made a second row"
        assert len(client.get(ident(enterprise, "/domains"), headers=enterprise.owner.headers).json()) == 1

    def test_verifying_without_the_record_in_dns_says_not_yet(self, client, enterprise) -> None:
        made = client.post(ident(enterprise, "/domains"), json={"domain": "never-published.co.uk"}, headers=enterprise.owner.headers).json()
        response = client.post(ident(enterprise, f"/domains/{made['id']}/verify"), headers=enterprise.owner.headers)
        assert response.status_code in (200, 400, 409, 422), response.status_code
        assert response.status_code < 500
        stored = client.get(ident(enterprise, "/domains"), headers=enterprise.owner.headers).json()[0]
        assert stored["status"] != "VERIFIED"

    def test_a_domain_that_does_not_exist_or_is_another_organizations_is_not_found(self, client, enterprise) -> None:
        made = client.post(ident(enterprise, "/domains"), json={"domain": "mine-only.co.uk"}, headers=enterprise.owner.headers).json()
        assert client.post(ident(enterprise, f"/domains/{uuid.uuid4()}/verify"), headers=enterprise.owner.headers).status_code == 404
        not_theirs(client, enterprise, "POST", f"/identity/domains/{made['id']}/verify")
        not_theirs(client, enterprise, "GET", "/identity/domains")

    def test_only_the_owner_writes_an_admin_reads_a_member_sees_nothing(self, client, enterprise) -> None:
        body = {"domain": "owner-only.co.uk"}
        assert client.post(ident(enterprise, "/domains"), json=body, headers=enterprise.org_admin.headers).status_code == 403
        assert client.get(ident(enterprise, "/domains"), headers=enterprise.org_admin.headers).status_code == 200
        assert client.get(ident(enterprise, "/domains"), headers=enterprise.viewer.headers).status_code in (403, 404)

    def test_below_enterprise_a_domain_cannot_be_claimed(self, client, db_session, tenant) -> None:
        put_on_plan(db_session, tenant.organization, "business")
        response = client.post(ident(tenant, "/domains"), json={"domain": "business-plan.co.uk"}, headers=tenant.owner.headers)
        assert response.status_code == 402 and response.json()["details"]["code"] == "CAPABILITY_REQUIRED"


class TestSecurityPolicy:
    def test_the_defaults_leave_everything_open_and_say_who_you_are(self, client, enterprise) -> None:
        body = client.get(ident(enterprise, "/security-policy"), headers=enterprise.owner.headers).json()
        assert body["require_sso"] is False and body["ip_pinning"] == "OFF" and body["ip_allowlist"] == []
        assert "platform_max_session_age_s" in body

    @pytest.mark.parametrize(
        "change",
        [{"ip_pinning": "SOMETIMES"}, {"ip_prefix_v4": 7}, {"ip_prefix_v4": 33}, {"ip_prefix_v6": 31}, {"ip_prefix_v6": 129},
         {"ip_allowlist": ["not-a-network"]}, {"ip_allowlist": ["10.0.0.0/33"]}, {"ip_allowlist": ["300.1.1.1"]}, {"ip_allowlist": [""]},
         {"ip_allowlist": ["10.0.0.0/8"] * 101}, {"max_session_age_s": 60}, {"max_session_age_s": 299}, {"max_session_age_s": 10**9},
         {"max_session_age_s": True}, {"max_session_age_s": "3600"}, {"max_session_age_s": 3600.5}, {"idp_session_sync": True}, {"unknown": 1}],
    )
    def test_nonsense_is_refused_and_the_policy_is_unchanged(self, client, enterprise, change: dict) -> None:
        before = client.get(ident(enterprise, "/security-policy"), headers=enterprise.owner.headers).json()
        response = client.put(ident(enterprise, "/security-policy"), json=change, headers=enterprise.owner.headers)
        assert response.status_code in (400, 422), (change, response.status_code, response.text[:200])
        assert client.get(ident(enterprise, "/security-policy"), headers=enterprise.owner.headers).json() == before

    def test_a_valid_policy_is_kept_and_audited(self, client, enterprise) -> None:
        saved = client.put(
            ident(enterprise, "/security-policy"),
            json={"max_session_age_s": 86400, "ip_prefix_v4": 24}, headers=enterprise.owner.headers,
        )
        assert saved.status_code == 200, saved.text
        got = client.get(ident(enterprise, "/security-policy"), headers=enterprise.owner.headers).json()
        assert got["max_session_age_s"] == 86400 and got["ip_prefix_v4"] == 24
        rows = client.get(logs(enterprise, "?limit=50"), headers=enterprise.owner.headers).json()
        rows = rows["items"] if isinstance(rows, dict) else rows
        assert any("SECURITY" in r["resource_type"] or "IDENTITY" in r["resource_type"] or "POLICY" in r["resource_type"] for r in rows), \
            {r["resource_type"] for r in rows}

    def test_single_sign_on_cannot_be_required_while_none_is_set_up(self, client, enterprise) -> None:
        response = client.put(ident(enterprise, "/security-policy"), json={"require_sso": True}, headers=enterprise.owner.headers)
        assert response.status_code == 409 and "identity provider" in response.json()["detail"], (
            "requiring SSO with no identity provider would lock every member out", response.status_code, response.text[:200],
        )
        assert client.get(ident(enterprise, "/security-policy"), headers=enterprise.owner.headers).json()["require_sso"] is False

    def test_an_address_list_that_leaves_the_person_changing_it_outside_is_refused(self, client, enterprise) -> None:
        # The test client is not on 203.0.113.0/24. Pinning the organization to a network the owner is not on would end their own session.
        response = client.put(
            ident(enterprise, "/security-policy"),
            json={"ip_pinning": "STRICT", "ip_allowlist": ["203.0.113.0/24"]}, headers=enterprise.owner.headers,
        )
        assert response.status_code == 409 and "lock you out" in response.json()["detail"], response.text[:200]
        assert client.get(ident(enterprise, "/security-policy"), headers=enterprise.owner.headers).json()["ip_allowlist"] == []

    def test_only_the_owner_writes_and_an_admin_reads(self, client, enterprise) -> None:
        assert client.put(ident(enterprise, "/security-policy"), json={"max_session_age_s": 3600}, headers=enterprise.org_admin.headers).status_code == 403
        assert client.get(ident(enterprise, "/security-policy"), headers=enterprise.org_admin.headers).status_code == 200
        assert client.get(ident(enterprise, "/security-policy"), headers=enterprise.viewer.headers).status_code in (403, 404)

    def test_one_organizations_policy_is_not_anothers(self, client, enterprise) -> None:
        not_theirs(client, enterprise, "GET", "/identity/security-policy")
        not_theirs(client, enterprise, "PUT", "/identity/security-policy", json={"max_session_age_s": 3600})


class TestScim:
    def test_a_directory_key_needs_an_identity_provider_to_belong_to(self, client, enterprise) -> None:
        for body in ({}, {"idp_config_id": "nope"}, {"idp_config_id": str(uuid.uuid4())}, {"idp_config_id": str(uuid.uuid4()), "display_name": "x" * 201}):
            response = client.post(ident(enterprise, "/scim-keys"), json=body, headers=enterprise.owner.headers)
            assert response.status_code in (400, 404, 422), (body, response.status_code, response.text[:200])
        assert client.get(ident(enterprise, "/scim-keys"), headers=enterprise.owner.headers).json() == []

    def test_revoking_or_rotating_a_key_that_does_not_exist_is_not_found(self, client, enterprise) -> None:
        missing = uuid.uuid4()
        assert client.delete(ident(enterprise, f"/scim-keys/{missing}"), headers=enterprise.owner.headers).status_code == 404
        assert client.post(ident(enterprise, f"/scim-keys/{missing}/rotate"), headers=enterprise.owner.headers).status_code == 404

    def test_a_member_and_an_admin_cannot_create_keys(self, client, enterprise) -> None:
        body = {"idp_config_id": str(uuid.uuid4())}
        assert client.post(ident(enterprise, "/scim-keys"), json=body, headers=enterprise.viewer.headers).status_code in (403, 404)
        assert client.post(ident(enterprise, "/scim-keys"), json=body, headers=enterprise.org_admin.headers).status_code in (403, 404)

    def test_the_provider_list_and_directory_answer_for_an_empty_organization(self, client, enterprise) -> None:
        assert client.get(ident(enterprise, "/idp-configs"), headers=enterprise.owner.headers).json() == []
        assert client.get(ident(enterprise, "/directory"), headers=enterprise.owner.headers).status_code == 200


# ---------------------------------------------------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------------------------------------------------


@pytest.fixture()
def trail(client: TestClient, enterprise: Fixture) -> Fixture:
    """A dozen real entries: renames and a role change, by two different people."""
    for index in range(6):
        client.patch(f"{ORG}/{enterprise.organization.id}", json={"name": f"Trail Name {index}"}, headers=enterprise.owner.headers)
    for index in range(3):
        client.patch(f"{ORG}/{enterprise.organization.id}", json={"legal_name": f"Trail Legal {index}"}, headers=enterprise.org_admin.headers)
    return enterprise


def rows_of(response) -> list[dict]:
    body = response.json()
    return body["items"] if isinstance(body, dict) else body


class TestAuditLog:
    def test_entries_name_who_did_what_and_when_newest_first(self, client, trail) -> None:
        rows = rows_of(client.get(logs(trail, "?limit=50"), headers=trail.owner.headers))
        updates = [r for r in rows if r["action"] == "UPDATED" and r["resource_type"] == "ORGANIZATION"]
        assert len(updates) >= 9
        stamps = [r["created_at"] for r in rows]
        assert stamps == sorted(stamps, reverse=True)
        assert {r["actor_id"] for r in updates} == {str(trail.owner.user.id), str(trail.org_admin.user.id)}

    def test_filters_narrow_the_list_and_combine(self, client, trail) -> None:
        by_admin = rows_of(client.get(logs(trail, f"?actor_id={trail.org_admin.user.id}&action=UPDATED"), headers=trail.owner.headers))
        assert by_admin and {r["actor_id"] for r in by_admin} == {str(trail.org_admin.user.id)}
        assert rows_of(client.get(logs(trail, "?resource_type=API_KEY"), headers=trail.owner.headers)) == []
        assert rows_of(client.get(logs(trail, f"?actor_id={uuid.uuid4()}"), headers=trail.owner.headers)) == []

    def test_a_date_window_includes_and_excludes(self, client, trail) -> None:
        now = datetime.now(timezone.utc)
        inside = client.get(logs(trail, "?date_from=" + (now - timedelta(hours=1)).isoformat().replace("+00:00", "Z")), headers=trail.owner.headers)
        assert rows_of(inside)
        past = client.get(logs(trail, "?date_to=" + (now - timedelta(days=1)).isoformat().replace("+00:00", "Z")), headers=trail.owner.headers)
        assert rows_of(past) == []
        backwards = client.get(
            logs(trail, "?date_from=" + now.isoformat().replace("+00:00", "Z") + "&date_to=" + (now - timedelta(days=1)).isoformat().replace("+00:00", "Z")),
            headers=trail.owner.headers,
        )
        assert backwards.status_code in (200, 422)

    @pytest.mark.parametrize("query", ["?limit=0", "?limit=100000", "?action=NOT_AN_ACTION", "?resource_type=NOPE", "?actor_id=abc", "?date_from=yesterday", "?cursor=garbage", "?offset=-1"])
    def test_nonsense_filters_are_refused_not_ignored(self, client, trail, query: str) -> None:
        assert client.get(logs(trail, query), headers=trail.owner.headers).status_code == 422

    def test_pages_hold_everything_once(self, client, trail) -> None:
        seen: list[str] = []
        cursor = None
        for _ in range(20):
            query = "?limit=4" + (f"&cursor={cursor}" if cursor else "")
            body = client.get(logs(trail, query), headers=trail.owner.headers).json()
            seen += [r["id"] for r in body["items"]]
            cursor = body.get("next_cursor")
            if not cursor:
                break
        assert len(seen) == len(set(seen)) >= 9

    def test_a_cursor_cannot_be_reused_with_other_filters(self, client, trail) -> None:
        first = client.get(logs(trail, "?limit=2"), headers=trail.owner.headers).json()
        if not first.get("next_cursor"):
            pytest.skip("not enough entries to page")
        reused = client.get(logs(trail, f"?limit=2&action=CREATED&cursor={first['next_cursor']}"), headers=trail.owner.headers)
        assert reused.status_code == 422

    def test_one_entry_can_be_read_and_one_from_elsewhere_cannot(self, client, trail) -> None:
        entry = rows_of(client.get(logs(trail, "?limit=1"), headers=trail.owner.headers))[0]
        assert client.get(logs(trail, f"/{entry['id']}"), headers=trail.owner.headers).json()["id"] == entry["id"]
        assert client.get(logs(trail, f"/{uuid.uuid4()}"), headers=trail.owner.headers).status_code == 404
        other = trail.foreign_workspace.organization_id
        assert client.get(f"{ORG}/{other}/audit-logs/{entry['id']}", headers=trail.owner.headers).status_code in (403, 404)
        assert client.get(f"{ORG}/{other}/audit-logs", headers=trail.owner.headers).status_code in (403, 404)

    @pytest.mark.parametrize("method", ["PATCH", "PUT", "DELETE", "POST"])
    def test_the_trail_cannot_be_changed_through_the_api(self, client, trail, method: str) -> None:
        entry = rows_of(client.get(logs(trail, "?limit=1"), headers=trail.owner.headers))[0]
        response = client.request(method, logs(trail, f"/{entry['id']}"), json={"action": "X"}, headers=trail.owner.headers)
        assert response.status_code in (403, 404, 405), (method, response.status_code)
        assert client.get(logs(trail, f"/{entry['id']}"), headers=trail.owner.headers).json()["action"] == entry["action"]

    def test_an_export_is_a_real_csv_whose_cells_cannot_run_as_formulas_and_is_itself_recorded(self, client, trail) -> None:
        client.patch(f"{ORG}/{trail.organization.id}", json={"name": "=HYPERLINK(\"http://evil\",\"x\")"}, headers=trail.owner.headers)
        response = client.get(logs(trail, "/export?format=csv"), headers=trail.owner.headers)
        assert response.status_code == 200 and response.headers["content-type"].startswith("text/csv")
        assert "attachment" in response.headers["content-disposition"] and response.headers["x-content-type-options"] == "nosniff"
        parsed = list(csv.reader(io.StringIO(response.text)))
        assert len(parsed) > 9 and "created_at" in parsed[0] or "action" in parsed[0]
        for row in parsed[1:]:
            for cell in row:
                assert not cell.startswith(("=", "+", "-", "@")) or cell.lstrip("-").replace(".", "").isdigit() or cell.startswith("-") and len(cell) > 1 and cell[1].isdigit(), cell[:60]
        again = rows_of(client.get(logs(trail, "?action=EXPORTED"), headers=trail.owner.headers))
        assert again and again[0]["details"]["format"] == "csv"

    def test_the_other_export_format_is_json_lines_and_a_wrong_one_is_refused(self, client, trail) -> None:
        good = client.get(logs(trail, "/export?format=jsonl"), headers=trail.owner.headers)
        assert good.status_code == 200
        for line in [ln for ln in good.text.splitlines() if ln]:
            json.loads(line)
        assert client.get(logs(trail, "/export?format=xml"), headers=trail.owner.headers).status_code == 422

    def test_an_export_respects_the_filters(self, client, trail) -> None:
        response = client.get(logs(trail, f"/export?format=jsonl&actor_id={trail.org_admin.user.id}"), headers=trail.owner.headers)
        records = [json.loads(ln) for ln in response.text.splitlines() if ln]
        assert records and {r["actor_id"] for r in records} == {str(trail.org_admin.user.id)}

    def test_only_owners_and_admins_read_it(self, client, trail) -> None:
        assert client.get(logs(trail), headers=trail.org_admin.headers).status_code == 200
        for who in ("ws_admin", "contributor", "viewer", "non_member", "other_org_member"):
            assert client.get(logs(trail), headers=getattr(trail, who).headers).status_code in (403, 404), who
            assert client.get(logs(trail, "/export"), headers=getattr(trail, who).headers).status_code in (403, 404), who

    def test_the_filter_vocabulary_lists_every_choice(self, client, trail) -> None:
        body = client.get(logs(trail, "/vocabulary"), headers=trail.owner.headers).json()
        assert {"UPDATED", "CREATED"} <= {a["value"] for a in body["actions"]}
        assert "ORGANIZATION" in {r["value"] for r in body["resource_types"]}
