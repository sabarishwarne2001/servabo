"""Zoho Books "Connect" (Final session 1, 3C): the customer signs in at Zoho instead of pasting a token.

THE FLOW (OAuth 2.0 authorization code, as Zoho documents it: accounts.zoho.<dc>/oauth/v2/auth, /token, /token/revoke):

  1. `start`      the owner or administrator picks the data centre (India by default). We sign a state (workspace, person, data
                  centre, nonce, ten-minute expiry), keep the nonce in `erp_oauth_states`, and send the browser to Zoho's consent screen
                  with `access_type=offline` (so a refresh token comes back) and `prompt=consent`.
  2. `complete`   Zoho returns `code` and our state. The state's signature, expiry, single use and person are checked; the code is
                  exchanged at the data centre the STATE names (never one the callback's query claims); the refresh token is stored
                  encrypted in the target's credential (the ERP engine's own secret encryption and its rotation sweep).
  3. `organizations` / `choose_organization`   a Zoho login can hold several organizations; the customer picks the one whose books
                  these bills go to. Until one is chosen the target stays DISABLED, so nothing is posted anywhere.
  4. `disconnect` revokes the refresh token at Zoho (where its API allows it) and forgets it here.
  5. `check`      a refused or expired token marks the target "Reconnect Zoho Books" (never a raw error). A posting that met a refused
                  token fails with that sentence and is retried by itself once the customer reconnects.

WHAT IS UNVERIFIED. Zoho's pages could not be opened from the build sandbox; the data-centre hosts, the scope names, the token and
revoke paths and the organizations endpoint are from the documentation as it was known and a search summary on 2026-10-22. Final
session 2 runs this against a real Zoho Books India trial (docs/hardening/LIVE-VERIFICATION.md).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import secrets
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Optional
from urllib.parse import urlencode

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.audit_log import AuditAction
from app.models.erp import ErpOauthState, ErpPosting, ErpTarget
from app.services.erp import service
from app.services.erp import vocabulary as v

logger = logging.getLogger("app.services.erp.zoho")

STATE_TTL = timedelta(minutes=10)
#: What the application asks Zoho for: create and read bills, purchase orders, journals and vendor payments, read the vendors and
#: settings (accounts, taxes) and the organizations. Nothing that deletes.
SCOPES = ("ZohoBooks.bills.CREATE", "ZohoBooks.bills.READ", "ZohoBooks.purchaseorders.CREATE", "ZohoBooks.purchaseorders.READ",
          "ZohoBooks.accountants.CREATE", "ZohoBooks.accountants.READ", "ZohoBooks.vendorpayments.CREATE",
          "ZohoBooks.vendorpayments.READ", "ZohoBooks.contacts.READ", "ZohoBooks.settings.READ",
          # Final session 2T (Phase 4): TRINETRA reads the TDS a customer withheld from `customerpayments`, and the invoices they
          # were applied to. Read only. A connection made before this release lacks them and is asked to reconnect.
          "ZohoBooks.customerpayments.READ", "ZohoBooks.invoices.READ")
PAYMENTS_SCOPE = "ZohoBooks.customerpayments.READ"
RECONNECT_SENTENCE = "Zoho Books needs to be reconnected: Zoho no longer accepts the saved sign-in."


@dataclass(frozen=True)
class DataCentre:
    key: str
    label: str
    accounts: str      # https://accounts.zoho.in
    api: str           # https://www.zohoapis.in


DATA_CENTRES: dict[str, DataCentre] = {d.key: d for d in (
    DataCentre("IN", "India (zoho.in)", "https://accounts.zoho.in", "https://www.zohoapis.in"),
    DataCentre("US", "United States (zoho.com)", "https://accounts.zoho.com", "https://www.zohoapis.com"),
    DataCentre("EU", "Europe (zoho.eu)", "https://accounts.zoho.eu", "https://www.zohoapis.eu"),
    DataCentre("AU", "Australia (zoho.com.au)", "https://accounts.zoho.com.au", "https://www.zohoapis.com.au"),
    DataCentre("JP", "Japan (zoho.jp)", "https://accounts.zoho.jp", "https://www.zohoapis.jp"),
    DataCentre("CA", "Canada (zohocloud.ca)", "https://accounts.zohocloud.ca", "https://www.zohoapis.ca"),
    DataCentre("SA", "Saudi Arabia (zoho.sa)", "https://accounts.zoho.sa", "https://www.zohoapis.sa"),
    DataCentre("CN", "China (zoho.com.cn)", "https://accounts.zoho.com.cn", "https://www.zohoapis.com.cn"),
)}
DEFAULT_DATA_CENTRE = "IN"
#: Zoho's `location` query parameter (lower case) back to our key.
_LOCATIONS = {k.lower(): k for k in DATA_CENTRES}


class ZohoError(RuntimeError):
    """`code` is a short reason a page can show; the message is a sentence a person can act on."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def configured() -> bool:
    return bool(settings.ZOHO_CLIENT_ID and settings.ZOHO_CLIENT_SECRET and settings.ZOHO_REDIRECT_URI)


def _require_configured() -> tuple[str, str, str]:
    if not configured():
        raise ZohoError("NOT_CONFIGURED", "Zoho Books sign-in is not set up on this Servabo installation (ZOHO_CLIENT_ID, "
                                          "ZOHO_CLIENT_SECRET and ZOHO_REDIRECT_URI).")
    return settings.ZOHO_CLIENT_ID, settings.ZOHO_CLIENT_SECRET.get_secret_value(), settings.ZOHO_REDIRECT_URI


def data_centre(key: str) -> DataCentre:
    try:
        return DATA_CENTRES[(key or "").upper()]
    except KeyError as exc:
        raise ZohoError("UNKNOWN_DATA_CENTRE", f"{key!r} is not a Zoho data centre") from exc


def _accounts(dc: DataCentre) -> str:
    return (settings.ZOHO_ACCOUNTS_URL_OVERRIDE or dc.accounts).rstrip("/")


def _api(dc: DataCentre) -> str:
    return (settings.ZOHO_API_URL_OVERRIDE or dc.api).rstrip("/")


# ------------------------------------------------------------------------------------------------ the signed state

def _key() -> bytes:
    return hmac.new(settings.JWT_SECRET_KEY.get_secret_value().encode(), b"servabo:zoho-oauth-state:v1", hashlib.sha256).digest()


def _sign(payload: Mapping[str, Any]) -> str:
    body = base64.urlsafe_b64encode(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).decode().rstrip("=")
    mac = hmac.new(_key(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{mac}"


def _unsign(state: str) -> dict[str, Any]:
    try:
        body, mac = state.rsplit(".", 1)
        expected = hmac.new(_key(), body.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(mac, expected):
            raise ValueError("signature")
        return json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    except Exception as exc:  # noqa: BLE001 - anything wrong with a state is the same answer
        raise ZohoError("BAD_STATE", "This sign-in link is not valid. Start again from Connect Zoho Books.") from exc


def start(db: Session, *, organization_id: uuid.UUID, workspace_id: uuid.UUID, user_id: uuid.UUID, dc: str,
          target_id: Optional[uuid.UUID] = None) -> str:
    """The address of Zoho's consent screen for this person, workspace and data centre."""
    client_id, _secret, redirect_uri = _require_configured()
    centre = data_centre(dc)
    nonce = secrets.token_hex(24)
    expires = datetime.now(timezone.utc) + STATE_TTL
    db.add(ErpOauthState(nonce=nonce, organization_id=organization_id, workspace_id=workspace_id, user_id=user_id,
                         target_id=target_id, provider="zoho", data_centre=centre.key, expires_at=expires))
    db.flush()
    state = _sign({"n": nonce, "o": str(organization_id), "w": str(workspace_id), "u": str(user_id), "d": centre.key,
                   "t": str(target_id) if target_id else None, "x": int(expires.timestamp())})
    query = urlencode({"scope": ",".join(SCOPES), "client_id": client_id, "response_type": "code", "access_type": "offline",
                       "prompt": "consent", "redirect_uri": redirect_uri, "state": state})
    return f"{_accounts(centre)}/oauth/v2/auth?{query}"


# ------------------------------------------------------------------------------------------------ talking to Zoho

def _client(organization_id: uuid.UUID):
    from app.core import egress

    return egress.httpx_client(egress.ERP_HTTP, organization_id=organization_id, timeout=20.0)


def _post_form(organization_id: uuid.UUID, url: str, form: Mapping[str, str]) -> tuple[int, Any]:
    try:
        with _client(organization_id) as client:
            r = client.post(url, data=dict(form), headers={"Accept": "application/json"})
    except Exception as exc:  # noqa: BLE001
        raise ZohoError("UNREACHABLE", f"Zoho could not be reached ({type(exc).__name__}). Try again in a moment.") from exc
    return r.status_code, _json(r)


def _get(organization_id: uuid.UUID, url: str, token: str) -> tuple[int, Any]:
    try:
        with _client(organization_id) as client:
            r = client.get(url, headers={"Authorization": f"Zoho-oauthtoken {token}", "Accept": "application/json"})
    except Exception as exc:  # noqa: BLE001
        raise ZohoError("UNREACHABLE", f"Zoho could not be reached ({type(exc).__name__}). Try again in a moment.") from exc
    return r.status_code, _json(r)


def _json(response: Any) -> Any:
    try:
        return response.json()
    except Exception:  # noqa: BLE001
        return None


def _exchange(organization_id: uuid.UUID, centre: DataCentre, code: str) -> dict[str, Any]:
    client_id, secret, redirect_uri = _require_configured()
    status, body = _post_form(organization_id, f"{_accounts(centre)}/oauth/v2/token",
                              {"grant_type": "authorization_code", "code": code, "client_id": client_id,
                               "client_secret": secret, "redirect_uri": redirect_uri})
    if status != 200 or not isinstance(body, dict) or not body.get("refresh_token"):
        detail = body.get("error") if isinstance(body, dict) else None
        raise ZohoError("EXCHANGE_FAILED", "Zoho did not accept the sign-in" + (f" ({detail})" if detail else "")
                        + ". Start again from Connect Zoho Books.")
    return body


def _access_token(db: Session, target: ErpTarget) -> str:
    """A working access token from the stored refresh token. A refusal marks the target for reconnection."""
    credential = service.credential_of(target)
    if not credential or not credential.get("refresh_token"):
        raise ZohoError("NOT_CONNECTED", "Zoho Books is not connected.")
    centre = data_centre(((target.config or {}).get("zoho") or {}).get("data_centre") or DEFAULT_DATA_CENTRE)
    status, body = _post_form(target.organization_id, f"{_accounts(centre)}/oauth/v2/token",
                              {"grant_type": "refresh_token", "refresh_token": credential["refresh_token"],
                               "client_id": credential["client_id"], "client_secret": credential["client_secret"]})
    if status != 200 or not isinstance(body, dict) or not body.get("access_token"):
        if status in (400, 401) or (isinstance(body, dict) and body.get("error") in ("invalid_code", "invalid_client", "invalid_grant")):
            mark_reconnect(db, target)
            raise ZohoError("RECONNECT", RECONNECT_SENTENCE)
        raise ZohoError("UNREACHABLE", "Zoho answered something unexpected. Try again in a moment.")
    return str(body["access_token"])


# ------------------------------------------------------------------------------------------------ the target

def _settings_of(target: ErpTarget) -> dict[str, Any]:
    return dict((target.config or {}).get("zoho") or {})


def _set_settings(target: ErpTarget, **changes: Any) -> None:
    config = dict(target.config or {})
    config["zoho"] = {**_settings_of(target), **changes}
    target.config = config
    target.updated_at = service.now()
    target.revision = (target.revision or 0) + 1


def connection_view(target: ErpTarget) -> dict[str, Any]:
    """What the page needs of a Zoho target, never the credential."""
    z = _settings_of(target)
    state = ("RECONNECT" if z.get("needs_reconnect") else "DISCONNECTED" if z.get("disconnected")
             else "CHOOSE_ORGANIZATION" if not z.get("organization_chosen") else "CONNECTED")
    centre = DATA_CENTRES.get(z.get("data_centre") or "")
    return {"state": state, "data_centre": z.get("data_centre"), "data_centre_label": centre.label if centre else None,
            "organization_id": z.get("organization_id") if z.get("organization_chosen") else None,
            "organization_name": z.get("organization_name"), "connected_by": z.get("connected_by"),
            "can_read_payments": PAYMENTS_SCOPE in (z.get("scopes") or [])}


def customer_payments(db: Session, target: ErpTarget, *, date_start: str, date_end: str, limit: int = 200) -> list[dict[str, Any]]:
    """The TDS customers withheld, from Zoho Books customer payments (read only), one record per payment and invoice:

        {payment_id, date, customer, invoice_number, withheld_micros}

    Zoho API v3 customer payments: the list answers with payment summaries, the payment itself with `tax_amount_withheld` and
    `invoices[].tax_amount_withheld`. UNVERIFIED until Final session 2B runs against a real Zoho Books organization (the page could
    not be opened from the build sandbox). Asks for at most `limit` payments, with the person's own sign-in."""
    from decimal import Decimal, InvalidOperation

    z = _settings_of(target)
    if PAYMENTS_SCOPE not in (z.get("scopes") or []):
        raise ZohoError("SCOPE", "Reconnect Zoho Books so Servabo can read your customer payments (read only).")
    if not z.get("organization_chosen"):
        raise ZohoError("NOT_CONNECTED", "Zoho Books is not connected to an organization yet.")
    token = _access_token(db, target)
    centre = data_centre(z.get("data_centre") or DEFAULT_DATA_CENTRE)
    base = f"{_api(centre)}/books/v3/customerpayments"
    organization = urlencode({"organization_id": z["organization_id"]})

    def get(url: str) -> Any:
        status, body = _get(target.organization_id, url, token)
        if status in (401, 403):
            mark_reconnect(db, target)
            raise ZohoError("RECONNECT", RECONNECT_SENTENCE)
        if status != 200 or not isinstance(body, dict):
            raise ZohoError("UNREACHABLE", "Zoho could not list your customer payments. Try again in a moment.")
        return body

    def micros(value: Any) -> int:
        try:
            amount = Decimal(str(value or 0))
        except InvalidOperation:
            return 0
        if amount <= 0 or amount.as_tuple().exponent < -2:
            return 0
        return int(amount * 1_000_000)

    summaries: list[dict[str, Any]] = []
    page = 1
    while len(summaries) < limit:
        body = get(f"{base}?{organization}&" + urlencode({"date_start": date_start, "date_end": date_end, "page": page,
                                                          "per_page": min(200, limit)}))
        summaries += [p for p in body.get("customerpayments") or [] if isinstance(p, dict) and p.get("payment_id")]
        if not (body.get("page_context") or {}).get("has_more_page"):
            break
        page += 1
    out: list[dict[str, Any]] = []
    for summary in summaries[:limit]:
        payment = get(f"{base}/{summary['payment_id']}?{organization}").get("payment") or {}
        applied = [a for a in payment.get("invoices") or [] if isinstance(a, dict) and a.get("invoice_number")]
        for application in applied:
            withheld = micros(application.get("tax_amount_withheld"))
            if not withheld and len(applied) == 1:
                withheld = micros(payment.get("tax_amount_withheld"))     # the payment-level figure, for a single invoice only
            if withheld:
                out.append({"payment_id": str(summary["payment_id"]), "date": str(payment.get("date") or summary.get("date") or ""),
                            "customer": str(payment.get("customer_name") or summary.get("customer_name") or "")[:120],
                            "invoice_number": str(application["invoice_number"]), "withheld_micros": withheld})
    return out


def mark_reconnect(db: Session, target: ErpTarget) -> None:
    if not _settings_of(target).get("needs_reconnect"):
        _set_settings(target, needs_reconnect=True)
        db.flush()


def _build_config(centre: DataCentre, previous: Mapping[str, Any]) -> dict[str, Any]:
    config = dict(previous)
    config["http"] = {**(previous.get("http") or {}), "base_url": centre.api}
    config["oauth"] = {"token_url": f"{centre.accounts}/oauth/v2/token", "client_auth": "body"}
    return config


@dataclass
class Completed:
    target: ErpTarget
    workspace_id: uuid.UUID
    organization_id: uuid.UUID
    state: str          # CONNECTED | CHOOSE_ORGANIZATION
    reconnected: bool


def complete(db: Session, *, code: str, state: str, location: Optional[str] = None) -> Completed:
    """The callback. Everything about WHO and WHICH workspace comes from the state, never from the query."""
    client_id, secret, _redirect = _require_configured()
    payload = _unsign(state)
    if int(payload.get("x", 0)) < int(time.time()):
        raise ZohoError("EXPIRED", "This sign-in took too long (more than ten minutes). Start again from Connect Zoho Books.")
    claimed = db.execute(
        sa.update(ErpOauthState).where(ErpOauthState.nonce == payload.get("n"), ErpOauthState.used_at.is_(None),
                                       ErpOauthState.expires_at > sa.func.now())
        .values(used_at=sa.func.now()).returning(ErpOauthState.user_id, ErpOauthState.workspace_id,
                                                 ErpOauthState.organization_id, ErpOauthState.target_id,
                                                 ErpOauthState.data_centre)).first()
    if claimed is None:
        raise ZohoError("USED", "This sign-in link was already used. Start again from Connect Zoho Books.")
    user_id, workspace_id, organization_id, target_id, dc_key = claimed
    if (str(user_id), str(workspace_id), str(organization_id), dc_key) != (payload.get("u"), payload.get("w"), payload.get("o"),
                                                                           payload.get("d")):
        raise ZohoError("BAD_STATE", "This sign-in link is not valid. Start again from Connect Zoho Books.")
    centre = data_centre(dc_key)
    if location and _LOCATIONS.get(location.lower()) not in (None, centre.key):
        other = DATA_CENTRES[_LOCATIONS[location.lower()]]
        raise ZohoError("WRONG_DATA_CENTRE", f"Your Zoho account is in the {other.label} data centre, not {centre.label}. "
                                             "Choose the right one and connect again.")
    tokens = _exchange(organization_id, centre, code)
    credential = {"client_id": client_id, "client_secret": secret, "refresh_token": str(tokens["refresh_token"])}
    if tokens.get("access_token"):
        credential["access_token"] = str(tokens["access_token"])
        credential["expires_at"] = time.time() + float(tokens.get("expires_in") or 3600)
    reconnected = False
    if target_id is not None:
        target = db.get(ErpTarget, target_id)
        if target is None or target.workspace_id != workspace_id:
            raise ZohoError("BAD_STATE", "That Zoho Books connection no longer exists. Start again.")
        config = _build_config(centre, target.config or {})
        previous = _settings_of(target)
        service.set_credential(db, target=target, credential=credential, actor_user_id=user_id)
        target.config = config
        _set_settings(target, data_centre=centre.key, needs_reconnect=False, disconnected=False, connected_by=str(user_id),
                      scopes=list(SCOPES))
        reconnected = bool(previous.get("organization_chosen"))
        if reconnected and target.status != v.TARGET_ACTIVE:
            target.status = v.TARGET_ACTIVE
        requeue_waiting(db, target, actor_user_id=user_id)
    else:
        name = _free_name(db, workspace_id, "Zoho Books")
        config = _build_config(centre, {"zoho": {"organization_id": "pending", "data_centre": centre.key,
                                                 "organization_chosen": False, "connected_by": str(user_id),
                                                 "scopes": list(SCOPES)}})
        target = service.create_target(
            db, organization_id=organization_id, workspace_id=workspace_id, actor_user_id=user_id, name=name,
            format=v.FORMAT_JSON, transport=v.TRANSPORT_HTTP, preset=v.PRESET_ZOHO, ack_mode=v.ACK_SYNC,
            auth_mode=v.AUTH_OAUTH2_REFRESH, config=config, credential=credential, check_network=False)
        target.status = v.TARGET_DISABLED          # nothing is posted before an organization is chosen
    db.flush()
    chosen = bool(_settings_of(target).get("organization_chosen"))
    if not chosen:
        orgs = organizations(db, target)
        if len(orgs) == 1:
            choose_organization(db, target, orgs[0]["organization_id"], actor_user_id=user_id)
            chosen = True
    return Completed(target, workspace_id, organization_id, "CONNECTED" if chosen else "CHOOSE_ORGANIZATION", reconnected)


def _free_name(db: Session, workspace_id: uuid.UUID, base: str) -> str:
    names = set(db.execute(sa.select(ErpTarget.name).where(ErpTarget.workspace_id == workspace_id)).scalars())
    if base not in names:
        return base
    n = 2
    while f"{base} ({n})" in names:
        n += 1
    return f"{base} ({n})"


def organizations(db: Session, target: ErpTarget) -> list[dict[str, Any]]:
    """The Zoho organizations this login can post to: [{organization_id, name, country}]."""
    token = _access_token(db, target)
    centre = data_centre(_settings_of(target).get("data_centre") or DEFAULT_DATA_CENTRE)
    status, body = _get(target.organization_id, f"{_api(centre)}/books/v3/organizations", token)
    if status in (401, 403):
        mark_reconnect(db, target)
        raise ZohoError("RECONNECT", RECONNECT_SENTENCE)
    if status != 200 or not isinstance(body, dict):
        raise ZohoError("UNREACHABLE", "Zoho could not list your organizations. Try again in a moment.")
    return [{"organization_id": str(o.get("organization_id")), "name": str(o.get("name") or ""), "country": o.get("country_code") or None}
            for o in body.get("organizations") or [] if o.get("organization_id")]


def choose_organization(db: Session, target: ErpTarget, organization_id: str, *, actor_user_id: uuid.UUID) -> ErpTarget:
    found = {o["organization_id"]: o for o in organizations(db, target)}
    chosen = found.get(str(organization_id))
    if chosen is None:
        raise ZohoError("UNKNOWN_ORGANIZATION", "That Zoho organization is not one this sign-in can reach.")
    _set_settings(target, organization_id=chosen["organization_id"], organization_name=chosen["name"], organization_chosen=True)
    target.status = v.TARGET_ACTIVE
    db.flush()
    return target


def disconnect(db: Session, target: ErpTarget, *, actor_user_id: uuid.UUID) -> bool:
    """Revoke the refresh token at Zoho (best effort: where it is refused or unreachable it is still forgotten here) and forget it.
    Returns whether Zoho confirmed the revocation."""
    credential = service.credential_of(target) or {}
    centre = data_centre(_settings_of(target).get("data_centre") or DEFAULT_DATA_CENTRE)
    revoked = False
    if credential.get("refresh_token"):
        try:
            status, _body = _post_form(target.organization_id, f"{_accounts(centre)}/oauth/v2/token/revoke?"
                                       + urlencode({"token": credential["refresh_token"]}), {})
            revoked = status == 200
        except ZohoError:
            revoked = False
    target.credential_ciphertext = target.credential_fingerprint = None
    target.credential_updated_at = None
    target.status = v.TARGET_DISABLED
    _set_settings(target, disconnected=True, needs_reconnect=False, organization_chosen=False)
    service._audit(db, organization_id=target.organization_id, workspace_id=target.workspace_id, actor=actor_user_id,  # noqa: SLF001
                   operation="zoho_disconnected", action=AuditAction.UPDATED, target_id=str(target.id), revoked=revoked)
    db.flush()
    return revoked


def check(db: Session, target: ErpTarget) -> dict[str, Any]:
    """Ask Zoho whether the saved sign-in still works; the answer is on the target afterwards."""
    try:
        _access_token(db, target)
        if _settings_of(target).get("needs_reconnect"):
            _set_settings(target, needs_reconnect=False)
    except ZohoError as exc:
        if exc.code != "RECONNECT":
            raise
    db.flush()
    return connection_view(target)


def requeue_waiting(db: Session, target: ErpTarget, *, actor_user_id: uuid.UUID) -> int:
    """After a reconnection: the postings that failed because Zoho refused the sign-in are retried."""
    rows = db.execute(sa.select(ErpPosting).where(ErpPosting.target_id == target.id, ErpPosting.state == v.STATE_FAILED,
                                                  ErpPosting.last_error.like(f"{RECONNECT_SENTENCE[:40]}%"))).scalars().all()
    for posting in rows:
        service.review(db, posting=posting, verdict=v.VERDICT_RETRY, actor_user_id=actor_user_id,
                       note="Zoho Books was reconnected")
    return len(rows)


__all__ = ["Completed", "DATA_CENTRES", "PAYMENTS_SCOPE", "customer_payments", "DEFAULT_DATA_CENTRE", "RECONNECT_SENTENCE", "SCOPES", "ZohoError", "check", "complete",
           "configured", "connection_view", "data_centre", "disconnect", "mark_reconnect", "organizations", "requeue_waiting",
           "start"]
