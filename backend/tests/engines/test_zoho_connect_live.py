"""Final session 1 (3C): "Connect Zoho Books" with a sign-in at Zoho, against a stand-in Zoho (tests/fakes/fake_zoho.py).

Proven: the button needs the app's settings and the ERP posting plan and an administrator; the consent address carries the scope,
`access_type=offline` and a signed state; the callback accepts the state once, within ten minutes, for the person and workspace that
started it, and exchanges the code at the data centre the STATE names; the refresh token is stored encrypted and never returned;
one organization is chosen automatically, several are chosen by the customer and nothing can post until one is; disconnecting revokes
the token at Zoho and forgets it here; a refused token says "Reconnect Zoho Books", and a posting that met it is retried by itself
after the customer reconnects.
"""

from __future__ import annotations

import time
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import select

from app.core.config import settings
from app.models.erp import ErpOauthState, ErpTarget
from app.services.erp import service as erp_service
from app.services.erp import vocabulary as v
from app.services.erp import zoho
from tests.engines.conftest import Engines
from tests.fakes.fake_zoho import FakeZoho

CALLBACK = "http://testserver/api/v1/erp/zoho/callback"


@pytest.fixture()
def fake():
    with FakeZoho() as server:
        yield server


@pytest.fixture()
def zo(engines: Engines, fake: FakeZoho, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "ZOHO_CLIENT_ID", "1000.APPCLIENT")
    monkeypatch.setattr(settings, "ZOHO_CLIENT_SECRET", SecretStr("app-secret-value"))
    monkeypatch.setattr(settings, "ZOHO_REDIRECT_URI", CALLBACK)
    monkeypatch.setattr(settings, "ZOHO_ACCOUNTS_URL_OVERRIDE", fake.url)
    monkeypatch.setattr(settings, "ZOHO_API_URL_OVERRIDE", fake.url)
    engines.plan("business")

    class Z:
        e = engines
        zoho = fake

        @staticmethod
        def connect(dc: str = "IN", target_id=None, as_user=None):
            body = {"data_centre": dc, **({"target_id": str(target_id)} if target_id else {})}
            return engines.post("/erp/zoho/connect", body, as_user=as_user)

        @staticmethod
        def consent(url: str) -> str:
            """What the customer does at Zoho: clicks Accept. Returns the address Zoho sends the browser back to."""
            response = httpx.get(url, follow_redirects=False)
            assert response.status_code == 302, response.text
            return response.headers["location"]

        @staticmethod
        def callback(redirect: str, **override: str):
            parts = urlsplit(redirect)
            query = {k: v[0] for k, v in parse_qs(parts.query).items()}
            query.update(override)
            return engines.client.get("/api/v1/erp/zoho/callback", params=query, follow_redirects=False)

        @classmethod
        def sign_in(cls, dc: str = "IN"):
            url = cls.connect(dc).json()["authorize_url"]
            return cls.callback(cls.consent(url))

        @staticmethod
        def targets():
            engines.db.expire_all()
            return engines.db.execute(select(ErpTarget).where(ErpTarget.workspace_id == engines.ws)).scalars().all()

    return Z


def _where(response) -> tuple[dict[str, str], str]:
    parts = urlsplit(response.headers["location"])
    return {k: v[0] for k, v in parse_qs(parts.query).items()}, parts.path


# ------------------------------------------------------------------------------------------ who may start it

def test_the_button_needs_the_app_settings_the_plan_and_an_administrator(engines: Engines, monkeypatch, fake):
    engines.plan("business")
    assert engines.post("/erp/zoho/connect", {"data_centre": "IN"}).status_code == 503       # not set up on this installation
    monkeypatch.setattr(settings, "ZOHO_CLIENT_ID", "id")
    monkeypatch.setattr(settings, "ZOHO_CLIENT_SECRET", SecretStr("s"))
    monkeypatch.setattr(settings, "ZOHO_REDIRECT_URI", CALLBACK)
    assert engines.get("/erp/zoho").json()["configured"] is True
    assert engines.post("/erp/zoho/connect", {"data_centre": "IN"}, as_user=engines.tenant.contributor).status_code == 403
    assert engines.post("/erp/zoho/connect", {"data_centre": "IN"}, as_user=engines.tenant.viewer).status_code == 403
    assert engines.post("/erp/zoho/connect", {"data_centre": "MARS"}).status_code == 422
    engines.plan("developer")
    assert engines.post("/erp/zoho/connect", {"data_centre": "IN"}).status_code == 402        # ERP posting is not in the plan


def test_the_consent_address_asks_for_a_refresh_token_with_a_signed_state_and_the_right_scopes(zo):
    url = zo.connect().json()["authorize_url"]
    query = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
    assert urlsplit(url).path == "/oauth/v2/auth"
    assert query["access_type"] == "offline" and query["prompt"] == "consent" and query["response_type"] == "code"
    assert query["client_id"] == "1000.APPCLIENT" and query["redirect_uri"] == CALLBACK
    assert "ZohoBooks.bills.CREATE" in query["scope"] and not any(s.endswith(".DELETE") for s in query["scope"].split(","))
    assert "." in query["state"] and "app-secret-value" not in url


def test_each_data_centre_has_its_own_accounts_address(engines: Engines, monkeypatch):
    monkeypatch.setattr(settings, "ZOHO_CLIENT_ID", "id")
    monkeypatch.setattr(settings, "ZOHO_CLIENT_SECRET", SecretStr("s"))
    monkeypatch.setattr(settings, "ZOHO_REDIRECT_URI", CALLBACK)
    engines.plan("business")
    seen = {}
    for key, centre in zoho.DATA_CENTRES.items():
        url = engines.post("/erp/zoho/connect", {"data_centre": key}).json()["authorize_url"]
        seen[key] = urlsplit(url).netloc
        assert url.startswith(centre.accounts + "/oauth/v2/auth?")
    assert seen["IN"] == "accounts.zoho.in" and seen["EU"] == "accounts.zoho.eu" and seen["US"] == "accounts.zoho.com"
    assert zoho.DEFAULT_DATA_CENTRE == "IN"


# ------------------------------------------------------------------------------------------ the callback

def test_a_sign_in_with_several_organizations_waits_for_a_choice_and_posts_nothing_meanwhile(zo, engines: Engines):
    done = zo.sign_in()
    assert done.status_code == 302
    query, path = _where(done)
    assert query["zoho"] == "choose" and path.endswith("/erp")
    [target] = zo.targets()
    assert target.preset == v.PRESET_ZOHO and target.auth_mode == v.AUTH_OAUTH2_REFRESH and target.status == v.TARGET_DISABLED
    assert target.config["oauth"] == {"token_url": "https://accounts.zoho.in/oauth/v2/token", "client_auth": "body"}
    assert target.config["http"]["base_url"] == "https://www.zohoapis.in"
    # The refresh token is stored encrypted, comes back from nowhere, and the app's secret travelled to Zoho.
    credential = erp_service.credential_of(target)
    assert credential["refresh_token"].startswith("1000.refresh.")
    assert credential["refresh_token"] not in target.credential_ciphertext and "app-secret-value" not in target.credential_ciphertext
    assert zo.zoho.token_forms[0]["client_secret"] == "app-secret-value" and zo.zoho.token_forms[0]["redirect_uri"] == CALLBACK
    shown = engines.get("/erp/zoho").text
    assert credential["refresh_token"] not in shown and "app-secret-value" not in shown
    view = engines.get("/erp/zoho").json()["connections"][0]
    assert view["state"] == "CHOOSE_ORGANIZATION" and view["organization_id"] is None
    orgs = engines.get(f"/erp/targets/{target.id}/zoho/organizations").json()["items"]
    assert [o["name"] for o in orgs] == ["Meridian Wholesale Pvt Ltd", "Meridian Retail LLP"]
    chosen = engines.post(f"/erp/targets/{target.id}/zoho/organization", {"organization_id": orgs[1]["organization_id"]}).json()
    assert chosen["state"] == "CONNECTED" and chosen["organization_name"] == "Meridian Retail LLP"
    [target] = zo.targets()
    assert target.status == v.TARGET_ACTIVE and target.config["zoho"]["organization_id"] == orgs[1]["organization_id"]
    refused = engines.post(f"/erp/targets/{target.id}/zoho/organization", {"organization_id": "999"})
    assert refused.status_code == 422


def test_a_sign_in_with_one_organization_is_connected_at_once(zo, engines: Engines):
    zo.zoho.organizations = zo.zoho.organizations[:1]
    query, _path = _where(zo.sign_in())
    assert query["zoho"] == "connected"
    [target] = zo.targets()
    assert target.status == v.TARGET_ACTIVE and target.config["zoho"]["organization_id"] == "60001000001"


def test_the_state_works_once(zo):
    location = zo.consent(zo.connect().json()["authorize_url"])
    first = zo.callback(location)
    assert _where(first)[0]["zoho"] == "choose"
    again = zo.callback(location)
    query, _path = _where(again)
    assert query["zoho"] == "error" and query["reason"] in ("USED", "EXCHANGE_FAILED")
    assert len(zo.targets()) == 1


def test_a_changed_state_is_refused(zo):
    location = zo.consent(zo.connect().json()["authorize_url"])
    state = parse_qs(urlsplit(location).query)["state"][0]
    body, mac = state.rsplit(".", 1)
    forged = f"{body[:-2]}AA.{mac}"
    assert _where(zo.callback(location, state=forged))[0]["reason"] == "BAD_STATE"
    assert _where(zo.callback(location, state="nonsense"))[0]["reason"] == "BAD_STATE"
    assert zo.targets() == []


def test_an_old_state_is_refused(zo, engines: Engines):
    location = zo.consent(zo.connect().json()["authorize_url"])
    engines.db.query(ErpOauthState).update({"expires_at": zoho_past()})
    engines.db.commit()
    assert _where(zo.callback(location))[0]["reason"] == "USED"          # the stored state has expired: it can no longer be taken
    assert zo.targets() == []


def zoho_past():
    from datetime import datetime, timedelta, timezone

    return datetime.now(timezone.utc) - timedelta(minutes=1)


def test_a_denied_consent_comes_back_with_a_short_reason(zo):
    location = zo.consent(zo.connect().json()["authorize_url"])
    state = parse_qs(urlsplit(location).query)["state"][0]
    response = zo.e.client.get("/api/v1/erp/zoho/callback", params={"error": "access_denied", "state": state}, follow_redirects=False)
    assert _where(response)[0] == {"zoho": "error", "reason": "DENIED"}
    assert zo.targets() == []


def test_a_customer_in_another_data_centre_is_told_which(zo):
    location = zo.consent(zo.connect("IN").json()["authorize_url"])
    query, _path = _where(zo.callback(location, location="eu"))
    assert query["reason"] == "WRONG_DATA_CENTRE" and zo.targets() == []


# ------------------------------------------------------------------------------------------ disconnect and reconnect

def _connected(zo) -> ErpTarget:
    zo.zoho.organizations = zo.zoho.organizations[:1]
    zo.sign_in()
    [target] = zo.targets()
    return target


def test_disconnecting_revokes_the_token_at_zoho_and_forgets_it_here(zo, engines: Engines):
    target = _connected(zo)
    token = erp_service.credential_of(target)["refresh_token"]
    result = engines.post(f"/erp/targets/{target.id}/zoho/disconnect").json()
    assert result["revoked_at_zoho"] is True and result["state"] == "DISCONNECTED"
    assert token in zo.zoho.revoked
    [target] = zo.targets()
    assert target.credential_ciphertext is None and target.status == v.TARGET_DISABLED
    assert engines.post(f"/erp/targets/{target.id}/zoho/check").status_code == 409        # nothing to check: not connected


def test_a_refused_token_says_reconnect_and_reconnecting_keeps_the_target_and_its_organization(zo, engines: Engines):
    target = _connected(zo)
    zo.zoho.refresh_tokens = {t: False for t in zo.zoho.refresh_tokens}          # the customer removed the app in Zoho
    view = engines.post(f"/erp/targets/{target.id}/zoho/check").json()
    assert view["state"] == "RECONNECT"
    assert "raw" not in str(view).lower() and "invalid_code" not in str(view)
    assert engines.get("/erp/zoho").json()["connections"][0]["state"] == "RECONNECT"
    # Reconnect: the same target, a new credential, the organization kept.
    done = zo.callback(zo.consent(zo.connect(target_id=target.id).json()["authorize_url"]))
    assert _where(done)[0]["zoho"] in ("connected", "choose")
    [again] = zo.targets()
    assert again.id == target.id and again.config["zoho"]["organization_id"] == "60001000001"
    assert engines.get("/erp/zoho").json()["connections"][0]["state"] == "CONNECTED"
    assert len(zo.targets()) == 1


def test_a_connection_belongs_to_its_workspace(zo, engines: Engines):
    from app.models.organization import Organization
    from tests.security.plans import put_on_plan

    target = _connected(zo)
    put_on_plan(engines.db, engines.db.get(Organization, engines.tenant.foreign_workspace.organization_id), "business")
    engines.db.commit()
    other = engines.client.post(f"/api/v1/workspaces/{engines.tenant.foreign_workspace.id}/erp/targets/{target.id}/zoho/check",
                                headers=engines.tenant.other_org_member.headers)
    assert other.status_code in (403, 404)


# ------------------------------------------------------------------------------------------ a posting that meets a refused token

def test_a_posting_that_meets_a_refused_token_fails_with_the_reconnect_sentence_and_is_flagged(zo, engines: Engines, monkeypatch):
    from app.services.erp.transport import http as erp_http

    target = _connected(zo)
    snapshot = erp_service._Snapshot(  # noqa: SLF001
        posting_id=target.id, object_kind=v.OBJECT_VENDOR_BILL,
        rendered=b'{"vendor_id":"v1","bill_number":"B-1","date":"2026-09-01","line_items":[{"account_id":"a","rate":1,"quantity":1}]}',
        filename="b.json", sha256="0" * 64, idempotency_key="0" * 32, control_numbers={}, preset=v.PRESET_ZOHO, format=v.FORMAT_JSON,
        ack_mode=v.ACK_SYNC, auth_mode=v.AUTH_OAUTH2_REFRESH, config=dict(target.config), remote_path=None)

    def refuse(self, *args, **kwargs):
        return erp_http.Response(v.OUTCOME_PERMANENT, message="token endpoint refused the credential (400): invalid_code")

    monkeypatch.setattr(erp_http.Session, "request", refuse)
    result = erp_service._talk_http(snapshot, erp_service.credential_of(target), False)  # noqa: SLF001
    assert result.state == v.STATE_FAILED and result.reconnect is True
    assert result.message.startswith(zoho.RECONNECT_SENTENCE)
    assert "invalid_code" not in result.message


def test_postings_that_waited_for_a_reconnection_are_retried_by_themselves(zo, engines: Engines):
    import hashlib
    import uuid

    from app.models.erp import ErpPosting

    target = _connected(zo)
    body = b'{"vendor_id":"v1","bill_number":"B-1","date":"2026-09-01","line_items":[{"account_id":"a","rate":1,"quantity":1}]}'

    def posting(state: str, error: str, number: str) -> uuid.UUID:
        row = ErpPosting(
            id=uuid.uuid4(), organization_id=target.organization_id, workspace_id=target.workspace_id, target_id=target.id,
            object_kind=v.OBJECT_VENDOR_BILL, source_kind=v.SOURCE_TABLE, source_id=uuid.uuid4(), origin="MANUAL", state=state,
            idempotency_key=hashlib.sha256(number.encode()).hexdigest(), engine_version=v.ENGINE_VERSION, document_number=number,
            rendered=body, rendered_media_type="application/json", rendered_filename=f"{number}.json",
            content_sha=hashlib.sha256(body).hexdigest(), last_error=error, ack={}, control_numbers={}, exception_seq=1)
        engines.db.add(row)
        engines.db.commit()
        return row.id

    waiting = posting(v.STATE_FAILED, f"{zoho.RECONNECT_SENTENCE} Reconnect it under ERP targets and this posting is sent again.", "W-1")
    other = posting(v.STATE_FAILED, "the target answered 422: tax_id is invalid", "W-2")
    zo.zoho.refresh_tokens = {t: False for t in zo.zoho.refresh_tokens}
    engines.post(f"/erp/targets/{target.id}/zoho/check")
    zo.callback(zo.consent(zo.connect(target_id=target.id).json()["authorize_url"]))
    engines.db.expire_all()
    assert engines.db.get(ErpPosting, waiting).state in (v.STATE_PENDING, v.STATE_RETRYING)
    assert engines.db.get(ErpPosting, other).state == v.STATE_FAILED, "a posting Zoho refused for its content is not retried blindly"
