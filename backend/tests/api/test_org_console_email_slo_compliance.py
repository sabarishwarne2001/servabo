"""Organization console, tabs 4-6 (Transactional email, Service levels, Data governance & compliance): what each tab's
form can send, what the server keeps, what it refuses and how.

Roles and plans for every route are swept in tests/security (role matrix, plan gating); these are the behaviours behind the
forms: the secret never coming back, nonsense numbers being refused with a reason (not a crash), a changed setting being
written to the audit trail, and one organization never reaching another's data.
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
    qs = "&".join(f"{k}={v}" for k, v in {"limit": "50", **query}.items())
    body = client.get(f"{ORG}/{tenant.organization.id}/audit-logs?{qs}", headers=tenant.owner.headers).json()
    return body["items"] if isinstance(body, dict) else body


# ---------------------------------------------------------------------------------------------------------------------
# Transactional email
# ---------------------------------------------------------------------------------------------------------------------

EMAIL_OK = {
    "smtp_host": "smtp.example.com",
    "smtp_port": 587,
    "smtp_username": "mailer",
    "smtp_password": "s3cret-pass",
    "sender_name": "Acme Mail",
    "sender_email": "noreply@acme.example.com",
    "encryption": "TLS",
}


def email_url(tenant: Fixture) -> str:
    return f"{ORG}/{tenant.organization.id}/email-settings"


class TestTransactionalEmail:
    def test_a_new_organization_has_no_server_and_is_not_enabled(self, client, enterprise) -> None:
        body = client.get(email_url(enterprise), headers=enterprise.owner.headers).json()
        assert body["is_enabled"] is False and body["is_complete"] is False and body["has_password"] is False
        assert body["smtp_host"] is None

    def test_a_saved_configuration_never_returns_the_password(self, client, enterprise) -> None:
        saved = client.patch(email_url(enterprise), json={**EMAIL_OK, "is_enabled": True}, headers=enterprise.owner.headers)
        assert saved.status_code == 200, saved.text
        for body in (saved.json(), client.get(email_url(enterprise), headers=enterprise.owner.headers).json()):
            assert body["has_password"] is True and body["is_complete"] is True and body["is_enabled"] is True
            assert "s3cret-pass" not in str(body)
            assert "smtp_password" not in body and "encrypted_password" not in body

    def test_leaving_the_password_out_keeps_the_stored_one(self, client, enterprise) -> None:
        client.patch(email_url(enterprise), json=EMAIL_OK, headers=enterprise.owner.headers)
        change = {k: v for k, v in EMAIL_OK.items() if k != "smtp_password"} | {"sender_name": "Renamed Mail"}
        body = client.patch(email_url(enterprise), json=change, headers=enterprise.owner.headers).json()
        assert body["sender_name"] == "Renamed Mail" and body["has_password"] is True

    def test_it_cannot_be_switched_on_while_incomplete(self, client, enterprise) -> None:
        response = client.patch(
            email_url(enterprise), json={"smtp_host": "smtp.example.com", "is_enabled": True}, headers=enterprise.owner.headers
        )
        assert response.status_code == 422, response.text

    @pytest.mark.parametrize(
        "change",
        [
            {"smtp_port": 0}, {"smtp_port": 65536}, {"smtp_port": -1}, {"smtp_port": "abc"},
            {"smtp_host": ""}, {"smtp_host": "   "}, {"smtp_host": "h" * 256},
            {"sender_email": "not-an-address"}, {"sender_email": "a@b"},
            {"encryption": "ROT13"}, {"smtp_password": "   "}, {"smtp_password": ""},
            {"unknown_field": "x"}, {"sender_name": ""},
        ],
    )
    def test_nonsense_is_refused_with_a_reason_and_nothing_is_kept(self, client, enterprise, change: dict) -> None:
        before = client.get(email_url(enterprise), headers=enterprise.owner.headers).json()
        response = client.patch(email_url(enterprise), json=change, headers=enterprise.owner.headers)
        assert response.status_code == 422, (change, response.text)
        assert client.get(email_url(enterprise), headers=enterprise.owner.headers).json() == before

    def test_a_test_message_with_no_server_says_so_instead_of_failing(self, client, enterprise) -> None:
        response = client.post(
            f"{email_url(enterprise)}/test", json={"recipient": "me@example.com"}, headers=enterprise.owner.headers
        )
        assert response.status_code == 200, response.text
        assert response.json()["success"] is False and "incomplete" in response.json()["message"].lower()

    def test_a_test_message_to_an_address_that_is_not_one_is_refused(self, client, enterprise) -> None:
        response = client.post(f"{email_url(enterprise)}/test", json={"recipient": "nope"}, headers=enterprise.owner.headers)
        assert response.status_code == 422

    def test_a_server_that_cannot_be_reached_is_reported_not_crashed(self, client, enterprise) -> None:
        client.patch(
            email_url(enterprise), json=EMAIL_OK | {"smtp_host": "127.0.0.1", "smtp_port": 1, "is_enabled": True},
            headers=enterprise.owner.headers,
        )
        response = client.post(f"{email_url(enterprise)}/test", json={"recipient": "me@example.com"}, headers=enterprise.owner.headers)
        assert response.status_code == 200, response.text
        assert response.json()["success"] is False and response.json()["message"]

    def test_an_admin_may_configure_it_and_a_member_may_not(self, client, enterprise) -> None:
        assert client.patch(email_url(enterprise), json=EMAIL_OK, headers=enterprise.org_admin.headers).status_code == 200
        assert client.get(email_url(enterprise), headers=enterprise.viewer.headers).status_code in (403, 404)
        assert client.patch(email_url(enterprise), json=EMAIL_OK, headers=enterprise.viewer.headers).status_code in (403, 404)

    def test_each_organization_has_its_own_configuration(self, client, db_session, enterprise) -> None:
        client.patch(email_url(enterprise), json=EMAIL_OK, headers=enterprise.owner.headers)
        other = enterprise.foreign_workspace.organization_id
        theirs = client.get(f"{ORG}/{other}/email-settings", headers=enterprise.other_org_member.headers)
        assert theirs.status_code in (200, 402, 403), theirs.text
        if theirs.status_code == 200:
            assert theirs.json()["smtp_host"] is None
        assert client.get(f"{ORG}/{other}/email-settings", headers=enterprise.owner.headers).status_code in (403, 404)

    def test_below_business_it_can_be_read_but_not_changed(self, client, db_session, tenant) -> None:
        put_on_plan(db_session, tenant.organization, "developer")
        assert client.get(email_url(tenant), headers=tenant.owner.headers).status_code == 200
        response = client.patch(email_url(tenant), json=EMAIL_OK, headers=tenant.owner.headers)
        assert response.status_code == 402 and response.json()["details"]["code"] == "CAPABILITY_REQUIRED"


# ---------------------------------------------------------------------------------------------------------------------
# Service levels
# ---------------------------------------------------------------------------------------------------------------------


def slo_url(tenant: Fixture, key: str = "") -> str:
    return f"{ORG}/{tenant.organization.id}/slos" + (f"/{key}" if key else "")


def first_ratio_key(client: TestClient, tenant: Fixture) -> str:
    entries = client.get(slo_url(tenant), headers=tenant.owner.headers).json()["entries"]
    return next(e["slo_key"] for e in entries if e["target"]["unit"] == "RATIO")


def first_latency_key(client: TestClient, tenant: Fixture) -> str:
    entries = client.get(slo_url(tenant), headers=tenant.owner.headers).json()["entries"]
    return next(e["slo_key"] for e in entries if e["target"]["unit"] != "RATIO")


class TestServiceLevels:
    def test_every_target_starts_from_the_platform_default(self, client, enterprise) -> None:
        body = client.get(slo_url(enterprise), headers=enterprise.owner.headers).json()
        assert len(body["entries"]) >= 3
        assert {e["target"]["source"] for e in body["entries"]} <= {"PLATFORM_DEFAULT", "PLATFORM_DEFAULT_UNCONFIGURED", "REGISTRY_DEFAULT"}
        assert body["contractual_breaches"] == 0

    @pytest.mark.parametrize("period", ["HOUR", "DAY", "MONTH"])
    def test_each_history_period_answers(self, client, enterprise, period: str) -> None:
        response = client.get(f"{slo_url(enterprise)}?period={period}", headers=enterprise.owner.headers)
        assert response.status_code == 200 and response.json()["period"] == period

    def test_an_unknown_period_is_refused(self, client, enterprise) -> None:
        assert client.get(f"{slo_url(enterprise)}?period=FORTNIGHT", headers=enterprise.owner.headers).status_code == 422

    def test_a_custom_target_replaces_the_default_and_marks_its_source(self, client, enterprise) -> None:
        key = first_ratio_key(client, enterprise)
        saved = client.put(slo_url(enterprise, key), json={"target_value": "0.995", "is_contractual": True}, headers=enterprise.owner.headers)
        assert saved.status_code == 200, saved.text
        assert saved.json()["source"] == "ORGANIZATION" and saved.json()["is_contractual"] is True
        entry = next(e for e in client.get(slo_url(enterprise), headers=enterprise.owner.headers).json()["entries"] if e["slo_key"] == key)
        assert entry["target"]["source"] == "ORGANIZATION" and float(entry["target"]["target_value"]) == 0.995

    @pytest.mark.parametrize("value", ["-1", "1.5", "2", "abc", "", "NaN", "Infinity", "-Infinity", "1e999"])
    def test_a_ratio_must_be_a_proportion_between_0_and_1(self, client, enterprise, value: str) -> None:
        key = first_ratio_key(client, enterprise)
        response = client.put(slo_url(enterprise, key), json={"target_value": value}, headers=enterprise.owner.headers)
        assert response.status_code in (400, 422), (value, response.status_code, response.text[:200])

    @pytest.mark.parametrize("value", ["NaN", "Infinity", "-5", "abc", "1e999"])
    def test_a_latency_target_must_be_a_real_positive_number_of_milliseconds(self, client, enterprise, value: str) -> None:
        key = first_latency_key(client, enterprise)
        response = client.put(slo_url(enterprise, key), json={"target_value": value}, headers=enterprise.owner.headers)
        assert response.status_code in (400, 422), (value, response.status_code, response.text[:200])

    def test_an_unknown_target_is_refused(self, client, enterprise) -> None:
        response = client.put(slo_url(enterprise, "no_such_slo"), json={"target_value": "0.9"}, headers=enterprise.owner.headers)
        assert response.status_code in (404, 422)

    def test_going_back_to_the_default_removes_the_override_once(self, client, enterprise) -> None:
        key = first_ratio_key(client, enterprise)
        client.put(slo_url(enterprise, key), json={"target_value": "0.99"}, headers=enterprise.owner.headers)
        assert client.delete(slo_url(enterprise, key), headers=enterprise.owner.headers).status_code == 204
        assert client.delete(slo_url(enterprise, key), headers=enterprise.owner.headers).status_code == 404
        entry = next(e for e in client.get(slo_url(enterprise), headers=enterprise.owner.headers).json()["entries"] if e["slo_key"] == key)
        assert entry["target"]["source"] != "ORGANIZATION"

    def test_a_tenant_that_downgrades_keeps_its_targets_readable_and_can_drop_them(self, client, db_session, enterprise) -> None:
        key = first_ratio_key(client, enterprise)
        client.put(slo_url(enterprise, key), json={"target_value": "0.99"}, headers=enterprise.owner.headers)
        put_on_plan(db_session, enterprise.organization, "business")
        assert client.get(slo_url(enterprise), headers=enterprise.owner.headers).status_code == 200
        blocked = client.put(slo_url(enterprise, key), json={"target_value": "0.98"}, headers=enterprise.owner.headers)
        assert blocked.status_code == 402 and blocked.json()["details"]["code"] == "CAPABILITY_REQUIRED"
        assert client.delete(slo_url(enterprise, key), headers=enterprise.owner.headers).status_code == 204

    def test_one_organizations_targets_are_not_anothers(self, client, db_session, enterprise) -> None:
        key = first_ratio_key(client, enterprise)
        client.put(slo_url(enterprise, key), json={"target_value": "0.9"}, headers=enterprise.owner.headers)
        other = enterprise.foreign_workspace.organization_id
        assert client.get(f"{ORG}/{other}/slos", headers=enterprise.owner.headers).status_code in (403, 404)
        assert client.put(f"{ORG}/{other}/slos/{key}", json={"target_value": "0.5"}, headers=enterprise.owner.headers).status_code in (403, 404)

    def test_a_member_cannot_read_or_set_targets(self, client, enterprise) -> None:
        assert client.get(slo_url(enterprise), headers=enterprise.viewer.headers).status_code in (403, 404)
        key = first_ratio_key(client, enterprise)
        assert client.put(slo_url(enterprise, key), json={"target_value": "0.9"}, headers=enterprise.viewer.headers).status_code in (403, 404)


# ---------------------------------------------------------------------------------------------------------------------
# Data governance & compliance
# ---------------------------------------------------------------------------------------------------------------------


def comp(tenant: Fixture, tail: str = "") -> str:
    return f"{ORG}/{tenant.organization.id}/compliance{tail}"


class TestCompliance:
    def test_the_overview_holds_residency_retention_and_counts(self, client, tenant) -> None:
        body = client.get(comp(tenant), headers=tenant.owner.headers).json()
        assert {"residency", "retention", "erasure_count", "export_count", "latest_export"} <= set(body)
        assert body["erasure_count"] == 0 and body["export_count"] == 0 and body["latest_export"] is None

    def test_a_retention_policy_is_kept_replaced_and_audited(self, client, tenant) -> None:
        first = client.put(comp(tenant, "/retention"), json={"work_item_retention_days": 365, "auto_purge_enabled": False}, headers=tenant.owner.headers)
        assert first.status_code == 200, first.text
        assert first.json()["work_item_retention_days"] == 365
        # A second save is a replacement: what is left out goes back to "forever".
        second = client.put(comp(tenant, "/retention"), json={"conversation_retention_days": 90}, headers=tenant.owner.headers).json()
        assert second["conversation_retention_days"] == 90 and second["work_item_retention_days"] is None
        got = client.get(comp(tenant, "/retention"), headers=tenant.owner.headers).json()
        assert got["conversation_retention_days"] == 90 and got["work_item_retention_days"] is None
        changes = [r for r in audit(client, tenant) if r["action"] == "RETENTION_CHANGED"]
        assert len(changes) == 2 and changes[0]["details"]["conversation_retention_days"] == 90

    @pytest.mark.parametrize(
        "change",
        [{"work_item_retention_days": 0}, {"work_item_retention_days": -30}, {"work_item_retention_days": "ninety"},
         {"work_item_retention_days": 1.5}, {"audit_retention_days": 1}, {"conversation_retention_days": 0},
         {"auto_purge_enabled": "sometimes"}, {"something_else": 1}],
    )
    def test_nonsense_retention_is_refused(self, client, tenant, change: dict) -> None:
        assert client.put(comp(tenant, "/retention"), json=change, headers=tenant.owner.headers).status_code == 422

    @pytest.mark.parametrize("days", [2**31, 2**40, 10**15])
    def test_an_absurd_number_of_days_is_refused_not_crashed(self, client, tenant, days: int) -> None:
        response = client.put(comp(tenant, "/retention"), json={"work_item_retention_days": days}, headers=tenant.owner.headers)
        assert response.status_code == 422, (days, response.status_code, response.text[:200])

    def test_only_the_owner_sets_retention_but_an_admin_reads_it(self, client, tenant) -> None:
        assert client.put(comp(tenant, "/retention"), json={"work_item_retention_days": 400}, headers=tenant.org_admin.headers).status_code == 403
        assert client.get(comp(tenant, "/retention"), headers=tenant.org_admin.headers).status_code == 200

    def test_moving_the_region_needs_the_acknowledgement_and_a_known_region(self, client, tenant) -> None:
        current = client.get(comp(tenant, "/residency"), headers=tenant.owner.headers).json()
        assert current["region"] and current["available_regions"]
        assert client.put(comp(tenant, "/residency"), json={"region": current["region"]}, headers=tenant.owner.headers).status_code == 422
        refused = client.put(comp(tenant, "/residency"), json={"region": "MARS", "acknowledge_no_migration": True}, headers=tenant.owner.headers)
        assert refused.status_code == 422
        assert client.put(comp(tenant, "/residency"), json={"region": current["region"], "acknowledge_no_migration": True}, headers=tenant.org_admin.headers).status_code == 403

    def test_an_export_bundle_is_made_listed_and_downloadable_only_by_its_own_organization(self, client, tenant) -> None:
        made = client.post(comp(tenant, "/exports"), headers=tenant.owner.headers)
        assert made.status_code == 201, made.text
        export_id = made.json()["id"]
        listed = client.get(comp(tenant, "/exports"), headers=tenant.owner.headers).json()
        assert [e["id"] for e in listed] == [export_id]
        assert client.get(comp(tenant), headers=tenant.owner.headers).json()["export_count"] == 1
        other = tenant.foreign_workspace.organization_id
        stolen = client.get(f"{ORG}/{other}/compliance/exports/{export_id}/download", headers=tenant.other_org_member.headers)
        assert stolen.status_code in (403, 404)
        assert client.get(comp(tenant, f"/exports/{uuid.uuid4()}/download"), headers=tenant.owner.headers).status_code == 404

    def test_the_export_list_limit_is_bounded(self, client, tenant) -> None:
        assert client.get(comp(tenant, "/exports?limit=0"), headers=tenant.owner.headers).status_code == 422
        assert client.get(comp(tenant, "/exports?limit=201"), headers=tenant.owner.headers).status_code == 422

    def test_erasure_needs_a_member_a_ticket_and_the_retyped_address(self, client, tenant) -> None:
        subject = tenant.contributor.user
        base = {"subject_user_id": str(subject.id), "erasure_ticket": "DSAR-1", "confirm_subject_email": subject.email}
        preview = client.get(comp(tenant, f"/erasures/preview?subject_user_id={subject.id}"), headers=tenant.owner.headers)
        assert preview.status_code == 200 and "counts" in preview.json()
        wrong = client.post(comp(tenant, "/erasures"), json=base | {"confirm_subject_email": "someone@else.com"}, headers=tenant.owner.headers)
        assert wrong.status_code == 400
        blank = client.post(comp(tenant, "/erasures"), json=base | {"erasure_ticket": "   "}, headers=tenant.owner.headers)
        assert blank.status_code == 422
        stranger = client.post(
            comp(tenant, "/erasures"),
            json=base | {"subject_user_id": str(tenant.other_org_member.user.id), "confirm_subject_email": tenant.other_org_member.user.email},
            headers=tenant.owner.headers,
        )
        assert stranger.status_code == 404
        assert client.get(comp(tenant, f"/erasures/preview?subject_user_id={tenant.other_org_member.user.id}"), headers=tenant.owner.headers).status_code == 404
        assert client.get(comp(tenant), headers=tenant.owner.headers).json()["erasure_count"] == 0

    def test_an_erasure_is_done_once_recorded_and_owner_only(self, client, tenant) -> None:
        subject = tenant.viewer.user
        body = {"subject_user_id": str(subject.id), "erasure_ticket": "DSAR-2", "confirm_subject_email": subject.email.upper()}
        assert client.post(comp(tenant, "/erasures"), json=body, headers=tenant.org_admin.headers).status_code == 403
        done = client.post(comp(tenant, "/erasures"), json=body, headers=tenant.owner.headers)
        assert done.status_code == 201, done.text
        assert done.json()["already_erased"] is False
        listed = client.get(comp(tenant, "/erasures"), headers=tenant.owner.headers).json()
        assert [e["erasure_ticket"] for e in listed] == ["DSAR-2"]
        assert "viewer" not in str(listed).lower().replace("subject_email_hash", "")  # a hash is kept, never the address

    def test_the_owner_cannot_erase_themselves_out_of_their_own_organization(self, client, tenant) -> None:
        owner = tenant.owner.user
        response = client.post(
            comp(tenant, "/erasures"),
            json={"subject_user_id": str(owner.id), "erasure_ticket": "DSAR-3", "confirm_subject_email": owner.email},
            headers=tenant.owner.headers,
        )
        assert response.status_code in (400, 403, 409), response.text

    def test_a_member_sees_nothing_of_the_console(self, client, tenant) -> None:
        for tail in ("", "/retention", "/residency", "/exports", "/erasures"):
            assert client.get(comp(tenant, tail), headers=tenant.viewer.headers).status_code in (403, 404), tail
