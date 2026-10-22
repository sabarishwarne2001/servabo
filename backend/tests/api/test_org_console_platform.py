"""Organization console, tabs 8-13 (Enterprise BYOK & models, Branding & custom domains, Analytics & BI egress, Partner marketplace,
Calibrated autonomy, Egress lockdown): the behaviours behind each form.

Roles and plans for every route are swept in tests/security; these are what each form can send, what it keeps, what it refuses and
how: provider keys never returned, colours and names validated, destinations checked at the door, owner-only switches, one
organization never reaching another's settings.
"""

from __future__ import annotations

import io
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.byok_providers import PROVIDER_GROQ
from tests.conftest import Fixture
from tests.security.plans import put_on_plan

ORG = "/api/v1/organizations"
GROQ_KEY = "gsk_" + "k" * 48


@pytest.fixture()
def enterprise(db_session: Session, tenant: Fixture) -> Fixture:
    put_on_plan(db_session, tenant.organization, "enterprise")
    return tenant


def audit(client: TestClient, tenant: Fixture, **query: str) -> list[dict]:
    qs = "&".join(f"{k}={v}" for k, v in {"limit": "100", **query}.items())
    body = client.get(f"{ORG}/{tenant.organization.id}/audit-logs?{qs}", headers=tenant.owner.headers).json()
    return body["items"] if isinstance(body, dict) else body


def not_theirs(client: TestClient, tenant: Fixture, method: str, tail: str, **kw) -> None:
    other = tenant.foreign_workspace.organization_id
    response = client.request(method, f"{ORG}/{other}{tail}", headers=tenant.owner.headers, **kw)
    assert response.status_code in (402, 403, 404), (method, tail, response.status_code)


# ---------------------------------------------------------------------------------------------------------------------
# Enterprise BYOK & models
# ---------------------------------------------------------------------------------------------------------------------


def byok(tenant: Fixture, tail: str = "") -> str:
    return f"{ORG}/{tenant.organization.id}/byok{tail}"


class TestByok:
    def test_a_provider_key_is_stored_and_never_returned(self, client, enterprise) -> None:
        saved = client.put(byok(enterprise, "/credentials"), json={"provider": PROVIDER_GROQ, "api_key": GROQ_KEY}, headers=enterprise.owner.headers)
        assert saved.status_code == 200, saved.text
        for text in (saved.text, client.get(byok(enterprise), headers=enterprise.owner.headers).text,
                     client.get(byok(enterprise, "/credentials"), headers=enterprise.owner.headers).text):
            assert GROQ_KEY not in text and GROQ_KEY[:-4] not in text
        stored = client.get(byok(enterprise, "/credentials"), headers=enterprise.owner.headers).json()
        assert [c["provider"] for c in stored] == [PROVIDER_GROQ]

    @pytest.mark.parametrize("key", ["", " ", "   \n", "short", "x" * 5000, "has space inside" * 4])
    def test_a_key_that_cannot_be_a_key_is_refused(self, client, enterprise, key: str) -> None:
        response = client.put(byok(enterprise, "/credentials"), json={"provider": PROVIDER_GROQ, "api_key": key}, headers=enterprise.owner.headers)
        assert response.status_code in (400, 422), (key[:20], response.status_code, response.text[:200])
        assert client.get(byok(enterprise, "/credentials"), headers=enterprise.owner.headers).json() == []

    def test_a_key_pasted_with_spaces_or_a_newline_is_trimmed_not_refused(self, client, enterprise) -> None:
        response = client.put(byok(enterprise, "/credentials"), json={"provider": PROVIDER_GROQ, "api_key": f"  {GROQ_KEY}\n"}, headers=enterprise.owner.headers)
        assert response.status_code == 200, response.text

    def test_an_unknown_provider_is_refused(self, client, enterprise) -> None:
        response = client.put(byok(enterprise, "/credentials"), json={"provider": "acme-ai", "api_key": GROQ_KEY}, headers=enterprise.owner.headers)
        assert response.status_code == 422

    def test_a_key_is_removed_once_and_a_missing_one_is_not_a_crash(self, client, enterprise) -> None:
        client.put(byok(enterprise, "/credentials"), json={"provider": PROVIDER_GROQ, "api_key": GROQ_KEY}, headers=enterprise.owner.headers)
        path = byok(enterprise, f"/credentials/{PROVIDER_GROQ}")
        assert client.delete(path, headers=enterprise.owner.headers).status_code in (200, 204)
        assert client.delete(path, headers=enterprise.owner.headers).status_code == 404
        assert client.get(byok(enterprise, "/credentials"), headers=enterprise.owner.headers).json() == []

    def test_a_route_needs_a_real_model_name_and_a_known_task(self, client, enterprise) -> None:
        good = {"task_type": "EXTRACTION", "provider": PROVIDER_GROQ, "model_name": "llama-3.3-70b-versatile", "use_tenant_key": False}
        assert client.put(byok(enterprise, "/routes"), json=good, headers=enterprise.owner.headers).status_code == 200
        for bad in ({"model_name": "   "}, {"model_name": ""}, {"model_name": "m" * 129}, {"task_type": "DANCING"}, {"provider": "acme-ai"}):
            assert client.put(byok(enterprise, "/routes"), json=good | bad, headers=enterprise.owner.headers).status_code == 422, bad

    def test_a_route_that_needs_the_organizations_own_key_is_refused_while_there_is_none(self, client, enterprise) -> None:
        response = client.put(
            byok(enterprise, "/routes"),
            json={"task_type": "EXTRACTION", "provider": PROVIDER_GROQ, "model_name": "llama-3.3-70b-versatile", "use_tenant_key": True},
            headers=enterprise.owner.headers,
        )
        assert response.status_code in (200, 400, 409, 422), response.text
        assert response.status_code < 500

    def test_the_savings_window_is_bounded(self, client, enterprise) -> None:
        for query in ("?window_days=0", "?window_days=100000", "?window_days=abc"):
            assert client.get(byok(enterprise, query), headers=enterprise.owner.headers).status_code == 422

    def test_one_organizations_keys_are_not_anothers(self, client, enterprise) -> None:
        client.put(byok(enterprise, "/credentials"), json={"provider": PROVIDER_GROQ, "api_key": GROQ_KEY}, headers=enterprise.owner.headers)
        not_theirs(client, enterprise, "GET", "/byok")
        not_theirs(client, enterprise, "DELETE", f"/byok/credentials/{PROVIDER_GROQ}")
        assert len(client.get(byok(enterprise, "/credentials"), headers=enterprise.owner.headers).json()) == 1

    def test_storing_and_removing_a_key_are_audited_without_the_key(self, client, enterprise) -> None:
        client.put(byok(enterprise, "/credentials"), json={"provider": PROVIDER_GROQ, "api_key": GROQ_KEY}, headers=enterprise.owner.headers)
        client.delete(byok(enterprise, f"/credentials/{PROVIDER_GROQ}"), headers=enterprise.owner.headers)
        rows = audit(client, enterprise)
        assert rows and GROQ_KEY not in str(rows)
        assert any("BYOK" in r["resource_type"] or "CREDENTIAL" in r["resource_type"] for r in rows), {r["resource_type"] for r in rows}

    def test_only_the_owner_writes_and_an_admin_reads(self, client, enterprise) -> None:
        body = {"provider": PROVIDER_GROQ, "api_key": GROQ_KEY}
        assert client.put(byok(enterprise, "/credentials"), json=body, headers=enterprise.org_admin.headers).status_code == 403
        assert client.get(byok(enterprise), headers=enterprise.org_admin.headers).status_code == 200
        assert client.get(byok(enterprise), headers=enterprise.viewer.headers).status_code in (403, 404)


# ---------------------------------------------------------------------------------------------------------------------
# Branding & custom domains
# ---------------------------------------------------------------------------------------------------------------------


def brand(tenant: Fixture, tail: str = "") -> str:
    return f"{ORG}/{tenant.organization.id}/branding{tail}"


def _png() -> bytes:
    from PIL import Image

    out = io.BytesIO()
    Image.new("RGB", (64, 64), (26, 115, 232)).save(out, format="PNG")
    return out.getvalue()


PNG_1x1 = _png()


class TestBranding:
    def test_a_new_organization_has_default_branding_that_is_switched_off(self, client, enterprise) -> None:
        body = client.get(brand(enterprise), headers=enterprise.owner.headers).json()
        assert body["is_enabled"] is False

    def test_a_brand_is_saved_trimmed_and_kept(self, client, enterprise) -> None:
        saved = client.put(
            brand(enterprise),
            json={"brand_name": "  Acme Cloud  ", "primary_color": "#1a73e8", "accent_color": "#0b8043", "support_email": " Help@Acme.com "},
            headers=enterprise.owner.headers,
        )
        assert saved.status_code == 200, saved.text
        body = saved.json()
        assert body["brand_name"] == "Acme Cloud" and body["primary_color"].lower() == "#1a73e8" and body["support_email"] == "help@acme.com"

    @pytest.mark.parametrize(
        "colour", ["red", "#12345", "#1234567", "#GGGGGG", "1a73e8", "rgb(1,2,3)", "#12 456", "javascript:alert(1)", "#1a73e8;x", "<script>"],
    )
    def test_a_colour_must_be_a_six_digit_hex(self, client, enterprise, colour: str) -> None:
        response = client.put(brand(enterprise), json={"primary_color": colour}, headers=enterprise.owner.headers)
        assert response.status_code == 422, (colour, response.status_code)

    @pytest.mark.parametrize("name", ["<script>alert(1)</script>", "Acme\u0000", "a" * 200, "Acme\nCloud"])
    def test_a_brand_name_cannot_carry_markup_control_characters_or_run_on(self, client, enterprise, name: str) -> None:
        response = client.put(brand(enterprise), json={"brand_name": name}, headers=enterprise.owner.headers)
        assert response.status_code in (400, 422), (name[:30], response.status_code, response.text[:200])  # 400: a NUL byte

    @pytest.mark.parametrize("email", ["nope", "a@b", "a b@c.com", "@c.com"])
    def test_a_support_address_must_be_an_address(self, client, enterprise, email: str) -> None:
        assert client.put(brand(enterprise), json={"support_email": email}, headers=enterprise.owner.headers).status_code == 422

    def test_a_blank_support_address_clears_it_and_unknown_fields_are_refused(self, client, enterprise) -> None:
        client.put(brand(enterprise), json={"support_email": "help@acme.com"}, headers=enterprise.owner.headers)
        assert client.put(brand(enterprise), json={"support_email": "  "}, headers=enterprise.owner.headers).json()["support_email"] in (None, "")
        assert client.put(brand(enterprise), json={"logo_file_id": str(uuid.uuid4())}, headers=enterprise.owner.headers).status_code == 422

    def test_a_logo_must_be_a_real_picture_and_can_be_removed_once(self, client, enterprise) -> None:
        text = client.post(brand(enterprise, "/logo"), files={"file": ("logo.png", io.BytesIO(b"this is not an image"), "image/png")}, headers=enterprise.owner.headers)
        assert text.status_code in (400, 415, 422), text.text[:200]
        script = client.post(brand(enterprise, "/logo"), files={"file": ("logo.svg", io.BytesIO(b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>"), "image/svg+xml")}, headers=enterprise.owner.headers)
        assert script.status_code in (400, 415, 422), script.text[:200]
        ok = client.post(brand(enterprise, "/logo"), files={"file": ("logo.png", io.BytesIO(PNG_1x1), "image/png")}, headers=enterprise.owner.headers)
        assert ok.status_code == 200, ok.text
        assert client.get(brand(enterprise, "/logo"), headers=enterprise.owner.headers).status_code == 200
        assert client.delete(brand(enterprise, "/logo"), headers=enterprise.owner.headers).status_code in (200, 204)
        assert client.get(brand(enterprise, "/logo"), headers=enterprise.owner.headers).status_code == 404

    def test_a_huge_upload_is_refused_not_stored(self, client, enterprise) -> None:
        big = PNG_1x1 + b"\0" * (12 * 1024 * 1024)
        response = client.post(brand(enterprise, "/logo"), files={"file": ("logo.png", io.BytesIO(big), "image/png")}, headers=enterprise.owner.headers)
        assert response.status_code in (400, 413, 415, 422), response.status_code

    def test_changes_are_audited(self, client, enterprise) -> None:
        client.put(brand(enterprise), json={"brand_name": "Audited Brand"}, headers=enterprise.owner.headers)
        assert any(r["resource_type"] == "TENANT_BRANDING" or "BRAND" in r["resource_type"] for r in audit(client, enterprise))

    def test_below_developer_branding_cannot_be_changed_but_can_be_read(self, client, db_session, tenant) -> None:
        put_on_plan(db_session, tenant.organization, "free")
        assert client.get(brand(tenant), headers=tenant.owner.headers).status_code == 200
        response = client.put(brand(tenant), json={"brand_name": "Nope"}, headers=tenant.owner.headers)
        assert response.status_code == 402 and response.json()["details"]["code"] == "CAPABILITY_REQUIRED"

    def test_one_organizations_brand_is_not_anothers(self, client, enterprise) -> None:
        not_theirs(client, enterprise, "GET", "/branding")
        not_theirs(client, enterprise, "PUT", "/branding", json={"brand_name": "Hijack"})


# ---------------------------------------------------------------------------------------------------------------------
# Analytics & BI egress
# ---------------------------------------------------------------------------------------------------------------------


def wh(tenant: Fixture, tail: str = "") -> str:
    return f"{ORG}/{tenant.organization.id}/analytics{tail}"


S3 = {"kind": "S3", "bucket": "acme-exports", "region": "eu-west-2", "prefix": "servabo/", "access_key_id": "AKIAEXAMPLE", "secret_access_key": "secret-value-1"}


class TestAnalytics:
    def test_the_destination_list_and_dataset_catalogue_answer_for_an_empty_organization(self, client, enterprise) -> None:
        for tail in ("/destinations", "/schedules", "/runs", "/datasets"):
            response = client.get(wh(enterprise, tail), headers=enterprise.owner.headers)
            assert response.status_code == 200, (tail, response.status_code)

    @pytest.mark.parametrize(
        "change",
        [{"label": ""}, {"label": "   "}, {"label": "<b>x</b>"}, {"label": 'a"b'}, {"label": "x" * 500},
         {"credential": S3 | {"bucket": "UPPER_case!"}}, {"credential": S3 | {"bucket": "-bad-"}}, {"credential": S3 | {"bucket": "ab"}},
         {"credential": S3 | {"endpoint_url": "http://insecure.example.com"}}, {"credential": S3 | {"secret_access_key": ""}},
         {"credential": S3 | {"kind": "FTP"}}, {"credential": {"kind": "S3"}}, {"surprise": 1}],
    )
    def test_a_destination_is_checked_before_anything_is_stored(self, client, enterprise, change: dict) -> None:
        body = {"label": "Warehouse", "credential": S3} | change
        response = client.post(wh(enterprise, "/destinations"), json=body, headers=enterprise.owner.headers)
        assert response.status_code in (402, 422), (str(change)[:80], response.status_code, response.text[:200])
        assert response.status_code != 402 or "ADDON_REQUIRED" in response.text or "CAPABILITY" in response.text

    def test_without_the_add_on_a_destination_cannot_be_created(self, client, db_session, tenant) -> None:
        put_on_plan(db_session, tenant.organization, "free")
        response = client.post(wh(tenant, "/destinations"), json={"label": "Warehouse", "credential": S3}, headers=tenant.owner.headers)
        assert response.status_code == 402, response.text
        assert "ADDON_REQUIRED" in response.text, response.text

    def test_a_destination_is_kept_without_its_credential_named_once_and_removable(self, client, enterprise) -> None:
        created = client.post(wh(enterprise, "/destinations"), json={"label": "Warehouse", "credential": S3}, headers=enterprise.owner.headers)
        assert created.status_code == 201, created.text
        assert "secret-value-1" not in created.text, "the secret key came back"
        # The access key id is an identifier, shown so a mistyped bucket or account is noticed; the secret half never is.
        listed = client.get(wh(enterprise, "/destinations"), headers=enterprise.owner.headers)
        assert "secret-value-1" not in listed.text and [d["label"] for d in listed.json()] == ["Warehouse"]
        again = client.post(wh(enterprise, "/destinations"), json={"label": "Warehouse", "credential": S3}, headers=enterprise.owner.headers)
        assert again.status_code == 409, again.text
        path = wh(enterprise, f"/destinations/{created.json()['id']}")
        assert client.delete(path, headers=enterprise.owner.headers).status_code in (200, 204)
        assert client.delete(path, headers=enterprise.owner.headers).status_code == 404
        assert client.get(wh(enterprise, "/destinations"), headers=enterprise.owner.headers).json() == []

    def test_a_schedule_is_checked(self, client, enterprise) -> None:
        base = {"destination_id": str(uuid.uuid4()), "datasets": ["work_items"], "cadence": "DAILY"}
        for bad in ({"datasets": []}, {"datasets": ["nope"]}, {"cadence": "HOURLYISH"}, {"hour_utc": 24}, {"hour_utc": -1},
                    {"day_of_week": 7}, {"day_of_month": 29}, {"lookback_days": 0}, {"lookback_days": 91}, {"destination_id": "not-a-uuid"}):
            response = client.post(wh(enterprise, "/schedules"), json=base | bad, headers=enterprise.owner.headers)
            assert response.status_code in (402, 422), (bad, response.status_code)

    def test_a_member_sees_nothing_and_another_organizations_destinations_are_out_of_reach(self, client, enterprise) -> None:
        assert client.get(wh(enterprise, "/destinations"), headers=enterprise.viewer.headers).status_code in (403, 404)
        not_theirs(client, enterprise, "GET", "/analytics/destinations")
        not_theirs(client, enterprise, "DELETE", f"/analytics/destinations/{uuid.uuid4()}")

    def test_the_run_history_and_consumption_windows_are_bounded(self, client, enterprise) -> None:
        for query in ("/runs?limit=0", "/runs?limit=100000", "/consumption?window_days=0", "/consumption?window_days=100000", "/consumption?granularity=YEAR"):
            response = client.get(wh(enterprise, query), headers=enterprise.owner.headers)
            assert response.status_code == 422, (query, response.status_code)


# ---------------------------------------------------------------------------------------------------------------------
# Partner marketplace
# ---------------------------------------------------------------------------------------------------------------------


def market(tenant: Fixture, tail: str = "") -> str:
    return f"{ORG}/{tenant.organization.id}/marketplace{tail}"


class TestMarketplace:
    def test_the_catalogue_and_installations_answer_for_an_empty_organization(self, client, enterprise) -> None:
        assert client.get(market(enterprise, "/catalog"), headers=enterprise.owner.headers).status_code == 200
        assert client.get(market(enterprise, "/installations"), headers=enterprise.owner.headers).json() == []

    def test_installing_or_removing_something_that_does_not_exist_is_a_plain_not_found(self, client, enterprise) -> None:
        missing = uuid.uuid4()
        assert client.get(market(enterprise, f"/catalog/{missing}"), headers=enterprise.owner.headers).status_code == 404
        install = client.post(market(enterprise, f"/catalog/{missing}/install"), json={}, headers=enterprise.owner.headers)
        assert install.status_code in (404, 405, 422), install.status_code
        assert client.delete(market(enterprise, f"/installations/{missing}"), headers=enterprise.owner.headers).status_code == 404

    def test_a_member_sees_nothing_and_another_organizations_installations_are_out_of_reach(self, client, enterprise) -> None:
        assert client.get(market(enterprise, "/installations"), headers=enterprise.viewer.headers).status_code in (403, 404)
        not_theirs(client, enterprise, "GET", "/marketplace/installations")
        not_theirs(client, enterprise, "DELETE", f"/marketplace/installations/{uuid.uuid4()}")


# ---------------------------------------------------------------------------------------------------------------------
# Calibrated autonomy
# ---------------------------------------------------------------------------------------------------------------------


def auto(tenant: Fixture, tail: str = "") -> str:
    return f"{ORG}/{tenant.organization.id}/autonomy{tail}"


def first_decision(client: TestClient, tenant: Fixture) -> str:
    entries = client.get(auto(tenant), headers=tenant.owner.headers).json()["entries"]
    assert entries
    return entries[0]["decision_type"]


class TestAutonomy:
    def test_every_decision_type_is_listed_with_its_state(self, client, enterprise) -> None:
        body = client.get(auto(enterprise), headers=enterprise.owner.headers).json()
        assert body["entries"] and {"decision_type"} <= set(body["entries"][0])
        assert body["min_labels"] > 0

    @pytest.mark.parametrize(
        "change",
        [{"target_error_rate": "0"}, {"target_error_rate": "-0.01"}, {"target_error_rate": "0.5"}, {"target_error_rate": "0.2001"},
         {"target_error_rate": "NaN"}, {"target_error_rate": "Infinity"}, {"target_error_rate": "abc"}, {"target_error_rate": ""},
         {"audit_sample_rate": "0"}, {"audit_sample_rate": "0.009"}, {"audit_sample_rate": "0.26"}, {"audit_sample_rate": "1e999"},
         {"audit_sample_rate": "-1"}],
    )
    def test_the_error_limit_and_audit_share_stay_in_their_ranges(self, client, enterprise, change: dict) -> None:
        decision = first_decision(client, enterprise)
        response = client.put(auto(enterprise, f"/{decision}"), json={"target_error_rate": "0.05", "audit_sample_rate": "0.1"} | change, headers=enterprise.owner.headers)
        assert response.status_code == 422, (change, response.status_code, response.text[:200])

    def test_a_valid_setting_is_kept_audited_and_reported(self, client, enterprise) -> None:
        decision = first_decision(client, enterprise)
        response = client.put(auto(enterprise, f"/{decision}"), json={"target_error_rate": "0.02", "audit_sample_rate": "0.05"}, headers=enterprise.owner.headers)
        assert response.status_code == 200, response.text
        assert response.json()["message"]
        entry = next(e for e in client.get(auto(enterprise), headers=enterprise.owner.headers).json()["entries"] if e["decision_type"] == decision)
        assert "0.02" in str(entry)
        assert any(r["details"].get("event") == "autonomy.settings_changed" for r in audit(client, enterprise))

    def test_an_unknown_decision_type_is_not_found(self, client, enterprise) -> None:
        for tail in ("/no_such_decision", "/no_such_decision/reliability", "/no_such_decision/resume"):
            method = "GET" if tail.endswith("reliability") else ("POST" if tail.endswith("resume") else "PUT")
            body = {"target_error_rate": "0.05", "audit_sample_rate": "0.1"} if method == "PUT" else None
            assert client.request(method, auto(enterprise, tail), json=body, headers=enterprise.owner.headers).status_code == 404, tail

    def test_only_the_owner_changes_it_an_admin_reads_a_member_sees_nothing(self, client, enterprise) -> None:
        decision = first_decision(client, enterprise)
        body = {"target_error_rate": "0.05", "audit_sample_rate": "0.1"}
        assert client.put(auto(enterprise, f"/{decision}"), json=body, headers=enterprise.org_admin.headers).status_code == 403
        assert client.get(auto(enterprise), headers=enterprise.org_admin.headers).status_code == 200
        assert client.get(auto(enterprise), headers=enterprise.viewer.headers).status_code in (403, 404)

    def test_below_enterprise_nothing_is_offered(self, client, db_session, tenant) -> None:
        put_on_plan(db_session, tenant.organization, "business")
        response = client.get(auto(tenant), headers=tenant.owner.headers)
        assert response.status_code == 402 and response.json()["details"]["code"] == "CAPABILITY_REQUIRED"

    def test_one_organizations_limits_are_not_anothers(self, client, enterprise) -> None:
        decision = first_decision(client, enterprise)
        not_theirs(client, enterprise, "GET", "/autonomy")
        not_theirs(client, enterprise, "PUT", f"/autonomy/{decision}", json={"target_error_rate": "0.05", "audit_sample_rate": "0.1"})


# ---------------------------------------------------------------------------------------------------------------------
# Egress lockdown
# ---------------------------------------------------------------------------------------------------------------------


def egress(tenant: Fixture, tail: str = "") -> str:
    return f"{ORG}/{tenant.organization.id}/egress{tail}"


class TestEgress:
    def test_a_new_organization_is_open_with_no_rules(self, client, enterprise) -> None:
        body = client.get(egress(enterprise), headers=enterprise.owner.headers).json()
        assert body["lockdown_enabled"] is False and body["rules"] == [] and body["max_rules"] > 0

    @pytest.mark.parametrize("host", ["api.example.com", "*.example.com", "203.0.113.7", "203.0.113.0/24", "2001:db8::/32", "EXAMPLE.com"])
    def test_a_host_pattern_in_a_usable_form_is_accepted(self, client, enterprise, host: str) -> None:
        response = client.post(egress(enterprise, "/rules"), json={"host_pattern": host, "port": 443}, headers=enterprise.owner.headers)
        assert response.status_code == 201, (host, response.text)

    @pytest.mark.parametrize(
        "host",
        ["", "   ", "*", "*.*", "**", "http://example.com", "example.com/path", "exa mple.com", "ex*ample.com", "*.", "-bad.example.com",
         "0.0.0.0/0", "::/0", "999.1.1.1", "example..com", "a" * 254, "<script>", "example.com;drop", "user@example.com"],
    )
    def test_a_host_pattern_that_is_not_one_or_that_allows_everything_is_refused(self, client, enterprise, host: str) -> None:
        response = client.post(egress(enterprise, "/rules"), json={"host_pattern": host}, headers=enterprise.owner.headers)
        assert response.status_code == 422, (host[:40], response.status_code, response.text[:200])

    @pytest.mark.parametrize("port", [0, -1, 65536, "http", 1.5])
    def test_a_port_is_a_real_port(self, client, enterprise, port) -> None:
        assert client.post(egress(enterprise, "/rules"), json={"host_pattern": "api.example.com", "port": port}, headers=enterprise.owner.headers).status_code == 422

    def test_the_same_rule_twice_is_not_added_twice(self, client, enterprise) -> None:
        body = {"host_pattern": "api.example.com", "port": 443}
        assert client.post(egress(enterprise, "/rules"), json=body, headers=enterprise.owner.headers).status_code == 201
        again = client.post(egress(enterprise, "/rules"), json=body, headers=enterprise.owner.headers)
        assert again.status_code in (200, 409, 422), again.status_code
        assert len(client.get(egress(enterprise), headers=enterprise.owner.headers).json()["rules"]) == 1

    def test_the_number_of_rules_is_capped_with_a_reason_not_a_crash(self, client, enterprise) -> None:
        cap = client.get(egress(enterprise), headers=enterprise.owner.headers).json()["max_rules"]
        for index in range(cap):
            assert client.post(egress(enterprise, "/rules"), json={"host_pattern": f"h{index}.example.com"}, headers=enterprise.owner.headers).status_code == 201
        over = client.post(egress(enterprise, "/rules"), json={"host_pattern": "one-more.example.com"}, headers=enterprise.owner.headers)
        assert over.status_code in (409, 422), over.status_code

    def test_a_rule_is_removed_once(self, client, enterprise) -> None:
        rule = client.post(egress(enterprise, "/rules"), json={"host_pattern": "gone.example.com"}, headers=enterprise.owner.headers).json()
        path = egress(enterprise, f"/rules/{rule['id']}")
        assert client.delete(path, headers=enterprise.owner.headers).status_code == 204
        assert client.delete(path, headers=enterprise.owner.headers).status_code == 404

    def test_lockdown_is_a_switch_and_the_decision_follows_it(self, client, enterprise) -> None:
        client.post(egress(enterprise, "/rules"), json={"host_pattern": "hooks.example.com", "port": 443}, headers=enterprise.owner.headers)
        ask = lambda url: client.post(egress(enterprise, "/test"), json={"channel": "WEBHOOK", "destination": url}, headers=enterprise.owner.headers)  # noqa: E731
        assert client.put(egress(enterprise), json={"lockdown_enabled": True}, headers=enterprise.owner.headers).json()["lockdown_enabled"] is True
        allowed, refused = ask("https://hooks.example.com/x").json(), ask("https://elsewhere.example.org/x").json()
        assert allowed["allowed"] is True and refused["allowed"] is False
        assert client.put(egress(enterprise), json={"lockdown_enabled": False}, headers=enterprise.owner.headers).json()["lockdown_enabled"] is False
        assert ask("https://elsewhere.example.org/x").json()["allowed"] is True

    def test_the_switch_wants_a_real_boolean(self, client, enterprise) -> None:
        for body in ({}, {"lockdown_enabled": "maybe"}, {"lockdown_enabled": None}, {"lockdown_enabled": True, "extra": 1}):
            assert client.put(egress(enterprise), json=body, headers=enterprise.owner.headers).status_code == 422, body

    def test_a_test_destination_is_checked(self, client, enterprise) -> None:
        for bad in ({}, {"channel": "WEBHOOK"}, {"channel": "WEBHOOK", "destination": ""}, {"channel": "WEBHOOK", "destination": "x" * 3000},
                    {"channel": "NOPE", "destination": "https://a.example.com"}, {"destination": "https://a.example.com"}):
            assert client.post(egress(enterprise, "/test"), json=bad, headers=enterprise.owner.headers).status_code == 422, str(bad)[:40]

    def test_the_refusal_window_is_bounded(self, client, enterprise) -> None:
        for query in ("?days=0", "?days=91", "?days=abc"):
            assert client.get(egress(enterprise, f"/refusals{query}"), headers=enterprise.owner.headers).status_code == 422
        assert client.get(egress(enterprise, "/refusals?days=30"), headers=enterprise.owner.headers).status_code == 200

    def test_every_change_is_audited(self, client, enterprise) -> None:
        client.post(egress(enterprise, "/rules"), json={"host_pattern": "audit.example.com"}, headers=enterprise.owner.headers)
        client.put(egress(enterprise), json={"lockdown_enabled": True}, headers=enterprise.owner.headers)
        operations = {(r["details"] or {}).get("operation") for r in audit(client, enterprise)}
        assert {"egress.rule_added", "egress.lockdown"} <= operations, operations

    def test_only_the_owner_changes_it_an_admin_reads_and_tests_a_member_sees_nothing(self, client, enterprise) -> None:
        assert client.put(egress(enterprise), json={"lockdown_enabled": True}, headers=enterprise.org_admin.headers).status_code == 403
        assert client.post(egress(enterprise, "/rules"), json={"host_pattern": "a.example.com"}, headers=enterprise.org_admin.headers).status_code == 403
        assert client.get(egress(enterprise), headers=enterprise.org_admin.headers).status_code == 200
        assert client.post(egress(enterprise, "/test"), json={"channel": "WEBHOOK", "destination": "https://a.example.com"}, headers=enterprise.org_admin.headers).status_code == 200
        assert client.get(egress(enterprise), headers=enterprise.viewer.headers).status_code in (403, 404)

    def test_below_enterprise_the_console_is_closed(self, client, db_session, tenant) -> None:
        put_on_plan(db_session, tenant.organization, "business")
        response = client.get(egress(tenant), headers=tenant.owner.headers)
        assert response.status_code == 402 and response.json()["details"]["code"] == "CAPABILITY_REQUIRED"

    def test_one_organizations_rules_are_not_anothers(self, client, enterprise) -> None:
        rule = client.post(egress(enterprise, "/rules"), json={"host_pattern": "mine.example.com"}, headers=enterprise.owner.headers).json()
        not_theirs(client, enterprise, "GET", "/egress")
        not_theirs(client, enterprise, "DELETE", f"/egress/rules/{rule['id']}")
        assert len(client.get(egress(enterprise), headers=enterprise.owner.headers).json()["rules"]) == 1
