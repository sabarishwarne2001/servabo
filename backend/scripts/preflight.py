#!/usr/bin/env python3
"""One command that says whether a Servabo setup is ready (Final session 1, 4B).

    python scripts/preflight.py                        # configuration only; contacts nothing (the default, --offline)
    python scripts/preflight.py --online               # also makes READ-ONLY calls: database, Redis, storage bucket, SMTP login (no
                                                       #   mail sent), Groq's model list, Dodo's product list, Postmark's server record
    python scripts/preflight.py --send-test-email you@example.com   # sends exactly one message
    python scripts/preflight.py --send-test-error      # sends exactly one test error to the error tracker (needs SENTRY_DSN)
    python scripts/preflight.py --json                 # machine-readable
    python scripts/preflight.py --online --i-mean-live # needed before --online will talk to a LIVE Dodo account (it still only reads)

Each item is OK, MISSING (not set), WRONG (set to something that will not work) or SKIPPED (optional and off, or needs --online), with
a one-line fix and where to click. Exit code 0 = ready (nothing MISSING or WRONG), 1 = not ready.

It reads the settings exactly as the app does (`app.core.config`). **It never prints a secret**: at most "set", and the last four characters
of a public id. Run it before the first start, after every change of settings, and before each launch step.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import smtplib
import ssl
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

OK, MISSING, WRONG, SKIPPED = "OK", "MISSING", "WRONG", "SKIPPED"
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}


@dataclass
class Item:
    group: str
    name: str
    status: str
    detail: str = ""     # what was found, never a secret
    fix: str = ""        # one line: what to do
    where: str = ""      # where to click or which file


class Report:
    def __init__(self) -> None:
        self.items: list[Item] = []

    def add(self, group: str, name: str, status: str, detail: str = "", fix: str = "", where: str = "") -> None:
        self.items.append(Item(group, name, status, detail, fix, where))

    @property
    def ready(self) -> bool:
        return not any(i.status in (MISSING, WRONG) for i in self.items)


def tail(value: Any, n: int = 4) -> str:
    """The last four characters of a PUBLIC id; secrets are never passed here."""
    text = str(value or "")
    return f"set (…{text[-n:]})" if len(text) > n else "set"


def secret_state(value: Any) -> bool:
    if value is None:
        return False
    getter = getattr(value, "get_secret_value", None)
    return bool((getter() if getter else str(value)).strip())


def secret_text(value: Any) -> str:
    getter = getattr(value, "get_secret_value", None)
    return (getter() if getter else str(value or "")).strip()


# ---------------------------------------------------------------------------------------------- the probes (replaced by tests)

def _http_client():
    import httpx

    return httpx.Client(timeout=10.0, follow_redirects=False)


HTTP_CLIENT: Callable[[], Any] = _http_client


def probe_database(settings: Any) -> None:
    import sqlalchemy as sa

    from app.db.session import engine

    with engine.connect() as connection:
        connection.execute(sa.text("SELECT 1"))


def probe_redis(settings: Any) -> None:
    import redis

    if not redis.Redis.from_url(settings.REDIS_URL, socket_connect_timeout=5).ping():
        raise RuntimeError("no answer to PING")


def probe_storage(settings: Any) -> None:
    import boto3

    client = boto3.client(
        "s3", endpoint_url=settings.S3_ENDPOINT_URL or None, region_name=settings.S3_REGION or "auto",
        aws_access_key_id=settings.S3_ACCESS_KEY_ID, aws_secret_access_key=secret_text(settings.S3_SECRET_ACCESS_KEY) or None)
    client.head_bucket(Bucket=settings.S3_BUCKET)


def probe_smtp(settings: Any) -> None:
    host, port = settings.PLATFORM_SMTP_HOST, int(settings.PLATFORM_SMTP_PORT)
    mode = (settings.PLATFORM_SMTP_ENCRYPTION or "TLS").upper()
    context = ssl.create_default_context()
    server = smtplib.SMTP_SSL(host, port, timeout=10, context=context) if mode == "SSL" else smtplib.SMTP(host, port, timeout=10)
    try:
        server.ehlo()
        if mode == "TLS":
            server.starttls(context=context)
            server.ehlo()
        if settings.PLATFORM_SMTP_USERNAME:
            server.login(settings.PLATFORM_SMTP_USERNAME, secret_text(settings.PLATFORM_SMTP_PASSWORD))
    finally:
        try:
            server.quit()
        except Exception:  # noqa: BLE001
            pass


def send_test_email(settings: Any, recipient: str) -> tuple[bool, str]:
    from app.core.platform_email import send_platform_email

    return send_platform_email(recipient=recipient, subject="Servabo preflight test", html_body="<p>This is the one test message from "
                               "<code>scripts/preflight.py</code>. If you can read it, the mail relay works.</p>",
                               text_body="This is the one test message from scripts/preflight.py. If you can read it, the mail relay works.\n")


# ---------------------------------------------------------------------------------------------- the checks

def check_environment(report: Report, s: Any, strict: bool) -> None:
    g = "environment"
    env = (s.ENVIRONMENT or "").strip().lower()
    if strict:
        report.add(g, "ENVIRONMENT", OK, env)
    else:
        report.add(g, "ENVIRONMENT", SKIPPED, f"{env or 'unset'}: the stricter production checks are relaxed", "Set ENVIRONMENT=production on the server.",
                   ".env")
    for name in ("FRONTEND_URL", "WEBSITE_URL"):
        value = (getattr(s, name, "") or "").strip()
        parts = urlsplit(value)
        if not value:
            report.add(g, name, MISSING, "", f"Set {name} to the public https address.", ".env")
        elif strict and (parts.scheme != "https" or (parts.hostname or "") in LOCAL_HOSTS):
            report.add(g, name, WRONG, value, f"{name} must be a public https:// address in production.", ".env")
        else:
            report.add(g, name, OK, value)
    origins = [o.strip().rstrip("/") for o in (s.CORS_ORIGINS or "").split(",") if o.strip()]
    front = (s.FRONTEND_URL or "").strip().rstrip("/")
    if front and origins and front not in origins:
        report.add(g, "CORS_ORIGINS", WRONG, ", ".join(origins), "It must include FRONTEND_URL exactly, or the browser cannot call the API.", ".env")
    else:
        report.add(g, "CORS_ORIGINS", OK if origins else MISSING, ", ".join(origins), "" if origins else "Set CORS_ORIGINS to FRONTEND_URL.")


def check_guard(report: Report, s: Any, strict: bool) -> None:
    if not strict:
        report.add("production guard", "start-up guard", SKIPPED, "only checked when ENVIRONMENT is production or staging")
        return
    from app.core.production_guard import production_config_problems

    problems = production_config_problems(s, (s.ENVIRONMENT or "production").strip().lower())
    if not problems:
        report.add("production guard", "start-up guard", OK, "the app's own start-up checks pass")
    for problem in problems:
        name, _, rest = problem.partition(":")
        report.add("production guard", name.strip()[:60], MISSING if "is not set" in rest else WRONG, rest.strip()[:160],
                   "Fix it as the line says; the app refuses to start until it is.", ".env")


def check_infrastructure(report: Report, s: Any, strict: bool, online: bool) -> None:
    g = "infrastructure"
    ok = bool(secret_state(s.POSTGRES_PASSWORD) and s.POSTGRES_HOST)
    report.add(g, "database", OK if ok else MISSING, f"{s.POSTGRES_HOST}:{s.POSTGRES_PORT}" if ok else "",
               "" if ok else "Set POSTGRES_HOST and POSTGRES_PASSWORD.", ".env")
    report.add(g, "Redis", OK if s.REDIS_URL else MISSING, "REDIS_URL set" if s.REDIS_URL else "", "" if s.REDIS_URL else "Set REDIS_URL.", ".env")
    backend = (s.STORAGE_BACKEND or "").strip().lower()
    if backend == "local":
        report.add(g, "storage", WRONG if strict else SKIPPED, "local disk", "Use R2, S3 or B2 in production: one server disk is not durable storage.",
                   "RUNBOOK §4 (storage)")
    elif backend in ("s3", "r2", "minio"):
        missing = [n for n, v in (("S3_BUCKET", s.S3_BUCKET), ("S3_ACCESS_KEY_ID", s.S3_ACCESS_KEY_ID),
                                  ("S3_SECRET_ACCESS_KEY", secret_text(s.S3_SECRET_ACCESS_KEY))) if not v]
        if missing:
            report.add(g, "storage", MISSING, backend, f"Set {', '.join(missing)}.", ".env")
        else:
            report.add(g, "storage", OK, f"{backend}, bucket {s.S3_BUCKET}, key {tail(s.S3_ACCESS_KEY_ID)}")
        endpoint = (s.S3_ENDPOINT_URL or "").lower()
        if backend == "r2" or "r2.cloudflarestorage.com" in endpoint:
            if ".eu." not in endpoint:
                report.add(g, "R2 jurisdiction", WRONG if strict else SKIPPED, endpoint or "no endpoint",
                           "Customers' documents are kept in the EU: use the bucket's EU endpoint https://<account>.eu.r2.cloudflarestorage.com.",
                           "Cloudflare dashboard → R2 → bucket → Settings")
            else:
                report.add(g, "R2 jurisdiction", OK, "EU endpoint")
    else:
        report.add(g, "storage", WRONG, backend, "STORAGE_BACKEND is local, s3, r2 or minio.", ".env")
    host = (s.PLATFORM_SMTP_HOST or "").strip()
    smtp_ok = bool(host and s.PLATFORM_SMTP_USERNAME and secret_state(s.PLATFORM_SMTP_PASSWORD))
    report.add(g, "mail relay", OK if smtp_ok else MISSING, f"{host}:{s.PLATFORM_SMTP_PORT}" if host else "",
               "" if smtp_ok else "Set PLATFORM_SMTP_HOST, _USERNAME and _PASSWORD (Postmark: Servers → your server → API Tokens).", ".env")
    if online:
        for name, probe, configured in (("database (online)", probe_database, ok), ("Redis (online)", probe_redis, bool(s.REDIS_URL)),
                                        ("storage bucket (online)", probe_storage, backend in ("s3", "r2", "minio") and bool(s.S3_BUCKET)),
                                        ("mail relay login (online)", probe_smtp, smtp_ok)):
            if not configured:
                report.add(g, name, SKIPPED, "not configured")
                continue
            try:
                probe(s)
                report.add(g, name, OK, "answered" if "login" not in name else "logged in; nothing sent")
            except Exception as exc:  # noqa: BLE001
                report.add(g, name, WRONG, type(exc).__name__, "It did not answer: check the address, the credentials and the firewall.", ".env")


def check_ai(report: Report, s: Any, online: bool) -> None:
    g = "AI and encryption"
    groq = secret_state(s.GROQ_API_KEY)
    local = (s.LOCAL_LLM_MODE or "").lower() == "exclusive" and bool(s.LOCAL_LLM_BASE_URL)
    report.add(g, "Groq key", OK if groq else (SKIPPED if local else MISSING), "set" if groq else ("own model serves everything" if local else ""),
               "" if groq or local else "Create a key at console.groq.com/keys and set GROQ_API_KEY.", "console.groq.com → API Keys")
    report.add(g, "Gemini key", OK if secret_state(s.GEMINI_API_KEY) else SKIPPED, "set" if secret_state(s.GEMINI_API_KEY) else "off (optional)")
    keys = secret_text(s.EMAIL_ENCRYPTION_KEYS)
    valid = bool(keys)
    for part in [k.strip() for k in keys.split(",") if k.strip()]:
        try:
            if len(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))) != 32:
                valid = False
        except Exception:  # noqa: BLE001
            valid = False
    report.add(g, "BYOK / secret encryption keys", OK if valid else (WRONG if keys else MISSING), "set" if keys else "",
               "" if valid else "EMAIL_ENCRYPTION_KEYS: one or more 32-byte url-safe base64 keys; generate with "
               "python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"", ".env")
    if online:
        if not groq:
            report.add(g, "Groq models (online)", SKIPPED, "no key")
            return
        try:
            with HTTP_CLIENT() as client:
                r = client.get("https://api.groq.com/openai/v1/models", headers={"Authorization": f"Bearer {secret_text(s.GROQ_API_KEY)}"})
            report.add(g, "Groq models (online)", OK if r.status_code == 200 else WRONG, f"HTTP {r.status_code}",
                       "" if r.status_code == 200 else "Groq refused the key: make a new one.", "console.groq.com → API Keys")
        except Exception as exc:  # noqa: BLE001
            report.add(g, "Groq models (online)", WRONG, type(exc).__name__, "Groq could not be reached.")


def _dodo_wanted() -> list[Any]:
    from scripts import dodo_setup

    return dodo_setup.wanted_products()


def check_dodo(report: Report, s: Any, online: bool, i_mean_live: bool) -> None:
    g = "Dodo Payments"
    if (s.BILLING_GATEWAY or "").upper() != "DODO":
        report.add(g, "gateway", SKIPPED, f"BILLING_GATEWAY={s.BILLING_GATEWAY}")
        return
    from scripts import dodo_setup

    key = secret_state(s.DODO_API_KEY)
    base = (s.DODO_API_BASE or "").rstrip("/")
    live_host = base == dodo_setup.LIVE_HOST
    report.add(g, "API key", OK if key else MISSING, "set" if key else "", "" if key else "Copy the API key from Dodo → Developer → API keys.",
               "app.dodopayments.com")
    consistent = (live_host == bool(s.DODO_LIVEMODE)) and base in (dodo_setup.LIVE_HOST, dodo_setup.TEST_HOST)
    report.add(g, "test or live", OK if consistent else WRONG, f"{'live' if s.DODO_LIVEMODE else 'test'} mode, {urlsplit(base).hostname or 'no host'}",
               "" if consistent else "DODO_LIVEMODE and DODO_API_BASE disagree: use live.dodopayments.com with true, test.dodopayments.com with false.", ".env")
    report.add(g, "webhook secret", OK if secret_state(s.DODO_WEBHOOK_SECRET) else MISSING, "set" if secret_state(s.DODO_WEBHOOK_SECRET) else "",
               "" if secret_state(s.DODO_WEBHOOK_SECRET) else "Dodo → Developer → Webhooks → your endpoint → signing secret.", "app.dodopayments.com")
    wanted = _dodo_wanted()
    ids: dict[str, str] = {}
    for item in wanted:
        value = str(getattr(s, item.env, None) or os.environ.get(item.env, "") or "").strip()
        ids[item.env] = value
    missing = [n for n, v in ids.items() if not v]
    report.add(g, f"product ids ({len(wanted) - len(missing)} of {len(wanted)})", WRONG if missing else OK,
               ("missing: " + ", ".join(missing)) if missing else "all set",
               "Run `python scripts/dodo_setup.py` against the TEST account, or create the products by hand and set each variable." if missing else "",
               "app.dodopayments.com → Products")
    if online:
        if live_host and not i_mean_live:
            report.add(g, "products (online)", SKIPPED, "this is a LIVE account", "Add --i-mean-live to let it read the live account (it only reads).")
            return
        if not key:
            report.add(g, "products (online)", SKIPPED, "no key")
            return
        try:
            with HTTP_CLIENT() as client:
                r = client.get(f"{base}/products", params={"page_size": 100, "page_number": 0},
                               headers={"Authorization": f"Bearer {secret_text(s.DODO_API_KEY)}"})
            if r.status_code != 200:
                report.add(g, "products (online)", WRONG, f"HTTP {r.status_code}", "Dodo refused the key.", "app.dodopayments.com")
                return
            present = {p.get("product_id") for p in (r.json().get("items") or [])}
            absent = [n for n, v in ids.items() if v and v not in present]
            report.add(g, "products (online)", WRONG if absent else OK, ("not in the account: " + ", ".join(absent)) if absent else "every product found",
                       "Create them or fix the ids." if absent else "")
        except Exception as exc:  # noqa: BLE001
            report.add(g, "products (online)", WRONG, type(exc).__name__, "Dodo could not be reached.")


def check_features(report: Report, s: Any, online: bool) -> None:
    g = "features"
    user, password = bool(s.POSTMARK_INBOUND_WEBHOOK_USER), secret_state(s.POSTMARK_INBOUND_WEBHOOK_PASSWORD)
    address = bool(s.POSTMARK_INBOUND_HASH or s.INBOUND_EMAIL_DOMAIN)
    if not (user or password or address):
        report.add(g, "email-in", SKIPPED, "off", "Optional. See RUNBOOK §9.10 to switch it on.")
    elif user and password and address:
        report.add(g, "email-in", OK, "webhook credential and address set")
    else:
        report.add(g, "email-in", WRONG, "half set", "Set POSTMARK_INBOUND_WEBHOOK_USER, _PASSWORD and POSTMARK_INBOUND_HASH (or INBOUND_EMAIL_DOMAIN).", ".env")
    zoho = [bool(s.ZOHO_CLIENT_ID), secret_state(s.ZOHO_CLIENT_SECRET), bool(s.ZOHO_REDIRECT_URI)]
    if not any(zoho):
        report.add(g, "Zoho Books", SKIPPED, "off", "Optional. See RUNBOOK §9.12.")
    elif all(zoho):
        uri_ok = s.ZOHO_REDIRECT_URI.endswith("/api/v1/public/erp/zoho/callback")
        report.add(g, "Zoho Books", OK if uri_ok else WRONG, f"client {tail(s.ZOHO_CLIENT_ID)}",
                   "" if uri_ok else "ZOHO_REDIRECT_URI must end /api/v1/public/erp/zoho/callback, exactly as registered at Zoho.", "api-console.zoho.in")
    else:
        report.add(g, "Zoho Books", WRONG, "half set", "Set all of ZOHO_CLIENT_ID, ZOHO_CLIENT_SECRET, ZOHO_REDIRECT_URI, or none.", ".env")
    from app.core.error_tracking import ingest_host

    dsn = (s.SENTRY_DSN or "").strip()
    if not dsn:
        report.add(g, "error tracking", SKIPPED, "off", "Optional but recommended. See RUNBOOK §9.13.")
    else:
        host = ingest_host(dsn)
        if urlsplit(dsn).scheme != "https" or not host:
            report.add(g, "error tracking", WRONG, "the DSN is not an https address", "Copy the DSN from the project's Client Keys.", "sentry.io → Settings → Client Keys")
        else:
            report.add(g, "error tracking", OK, f"reports to {host}")
            allowed = os.environ.get("SENTRY_INGEST_HOST", "").strip()
            report.add(g, "web app ingest host", OK if allowed else MISSING, f"CSP allows {allowed}" if allowed else "",
                       "" if allowed else f"For the web app's own errors set SENTRY_INGEST_HOST to the web project's DSN host (this project's is {host}).", ".env")
            if online:
                report.add(g, "error tracking DSN (online)", OK, "parsed; nothing sent")
    nic = (s.EINVOICE_QR_PUBLIC_KEY_PEM or "").strip()
    if not nic:
        report.add(g, "NIC e-invoice key", SKIPPED, "off: QR signatures read 'not checked'", "Optional: NIC's published public key.")
    else:
        try:
            from cryptography.hazmat.primitives.serialization import load_pem_public_key

            load_pem_public_key(nic.encode())
            report.add(g, "NIC e-invoice key", OK, "a public key")
        except Exception:  # noqa: BLE001
            report.add(g, "NIC e-invoice key", WRONG, "not a PEM public key", "A wrong key makes every QR code read 'signature does not match'.", ".env")
    if online:
        host = (s.PLATFORM_SMTP_HOST or "").lower()
        if "postmark" in host and secret_state(s.PLATFORM_SMTP_PASSWORD):
            try:
                with HTTP_CLIENT() as client:
                    r = client.get("https://api.postmarkapp.com/server", headers={"X-Postmark-Server-Token": secret_text(s.PLATFORM_SMTP_PASSWORD),
                                                                                   "Accept": "application/json"})
                report.add(g, "Postmark server (online)", OK if r.status_code == 200 else WRONG, f"HTTP {r.status_code}",
                           "" if r.status_code == 200 else "Postmark refused the token.", "account.postmarkapp.com")
            except Exception as exc:  # noqa: BLE001
                report.add(g, "Postmark server (online)", WRONG, type(exc).__name__, "Postmark could not be reached.")
        else:
            report.add(g, "Postmark server (online)", SKIPPED, "the relay is not Postmark")


def check_operations(report: Report, s: Any, strict: bool) -> None:
    g = "operations"
    raw = os.environ.get("SERVABO_BACKUP_KEY", "").strip()
    if not raw:
        report.add(g, "backup key", MISSING if strict else SKIPPED, "", "python scripts/backup_floor.py --generate-key, keep a copy off this machine, set SERVABO_BACKUP_KEY.", "RUNBOOK §6")
    else:
        try:
            good = len(base64.b64decode(raw, validate=True)) == 32
        except Exception:  # noqa: BLE001
            good = False
        report.add(g, "backup key", OK if good else WRONG, "set" if good else "", "" if good else "SERVABO_BACKUP_KEY must be 32 random bytes, base64.", "RUNBOOK §6")
    directory = Path(os.environ.get("SERVABO_BACKUP_DIR") or (Path(__file__).resolve().parents[1] / ".servabo_backups"))
    writable = directory.exists() and os.access(directory, os.W_OK)
    report.add(g, "backup folder", OK if writable else (MISSING if strict else SKIPPED), str(directory) if writable else "",
               "" if writable else f"Create {directory} and make it writable by the backup job.")
    hook = os.environ.get("ALERT_WEBHOOK", "").strip()
    report.add(g, "ALERT_WEBHOOK", OK if hook.startswith("https://") else (WRONG if hook else (MISSING if strict else SKIPPED)),
               urlsplit(hook).hostname or "" if hook else "", "" if hook.startswith("https://") else
               "Point ALERT_WEBHOOK at a Healthchecks.io failure address (https://hc-ping.com/<id>/fail).", "RUNBOOK §9.7")
    recipients = s.operator_alert_recipients
    bad = [r for r in recipients if "@" not in r or "." not in r.partition("@")[2]]
    report.add(g, "OPERATOR_ALERT_EMAILS", OK if recipients and not bad else (WRONG if bad else (MISSING if strict else SKIPPED)),
               f"{len(recipients)} address(es)" if recipients else "", "" if recipients and not bad else "Set OPERATOR_ALERT_EMAILS to the address(es) to email about failures.", ".env")
    if s.ML_STUBS:
        report.add(g, "model stubs", WRONG if strict else SKIPPED, "ML_STUBS=true", "OCR and embeddings are stubs: set ML_STUBS=false.", ".env")
    try:
        import torch  # type: ignore[import-not-found]

        cuda = getattr(torch.version, "cuda", None)
        report.add(g, "CPU-only image", (WRONG if strict else SKIPPED) if cuda else OK, "torch built with CUDA" if cuda else "torch is the CPU build",
                   "Build the image with the CPU wheel of torch (RUNBOOK, F-045): the CUDA build is several GB larger." if cuda else "")
    except Exception:  # noqa: BLE001
        report.add(g, "CPU-only image", SKIPPED, "torch is not installed here (the web image carries none)")


# ---------------------------------------------------------------------------------------------- running and printing

def send_test_error() -> tuple[bool, str]:
    """Send ONE deliberately raised error through the app's own error tracking (the same DSN, scrubber and tags), then flush.

    Returns (sent, a short sentence). Nothing is sent when SENTRY_DSN is empty. The message carries no data: it is safe to ignore in the tracker."""
    from app.core import error_tracking

    if not error_tracking.init("preflight"):
        return False, "SENTRY_DSN is empty, so error tracking is off"
    try:
        error_tracking.capture(RuntimeError("Servabo preflight test error (safe to ignore)"), area="preflight")
    finally:
        error_tracking.shutdown()  # flushes
    return True, "one test error sent: look for it in the project (tag area=preflight)"


def load_settings() -> tuple[Optional[Any], Optional[list[str]]]:
    """The settings as the app reads them; when the app itself would refuse to start, the reasons (variable names and sentences, no values)."""
    try:
        from app.core.config import settings

        return settings, None
    except Exception as exc:  # noqa: BLE001 - UnsafeConfigurationError carries only the list of problems
        text = str(exc).strip().splitlines()
        return None, [line.strip("- •\t ")[:200] for line in text if line.strip()][:40]


def run(settings: Any, *, online: bool = False, i_mean_live: bool = False) -> Report:
    report = Report()
    strict = (settings.ENVIRONMENT or "").strip().lower() in ("production", "staging")
    check_environment(report, settings, strict)
    check_guard(report, settings, strict)
    check_infrastructure(report, settings, strict, online)
    check_ai(report, settings, online)
    check_dodo(report, settings, online, i_mean_live)
    check_features(report, settings, online)
    check_operations(report, settings, strict)
    return report


def render_table(report: Report) -> str:
    width = max((len(i.name) for i in report.items), default=10)
    lines, group = [], None
    for item in report.items:
        if item.group != group:
            group = item.group
            lines += ["", group.upper()]
        lines.append(f"  {item.status:<8} {item.name:<{width}}  {item.detail}")
        if item.status in (MISSING, WRONG) and item.fix:
            lines.append(f"  {'':<8} {'':<{width}}  → {item.fix}" + (f"  [{item.where}]" if item.where else ""))
    counts = {s: sum(1 for i in report.items if i.status == s) for s in (OK, MISSING, WRONG, SKIPPED)}
    lines += ["", f"{counts[OK]} OK, {counts[MISSING]} missing, {counts[WRONG]} wrong, {counts[SKIPPED]} skipped. "
              + ("READY." if report.ready else "NOT READY: fix the MISSING and WRONG lines above.")]
    return "\n".join(lines).lstrip("\n")


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Is this Servabo setup ready?")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--offline", action="store_true", help="configuration only; contacts nothing (the default)")
    mode.add_argument("--online", action="store_true", help="also make read-only calls to the services")
    parser.add_argument("--send-test-email", metavar="ADDRESS", help="send exactly one message to this address")
    parser.add_argument("--send-test-error", action="store_true",
                        help="send exactly one test error to the error tracker (SENTRY_DSN), tagged area=preflight, through the same scrubber")
    parser.add_argument("--i-mean-live", action="store_true", help="allow --online to read a LIVE Dodo account")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)

    settings, problems = load_settings()
    if settings is None:
        report = Report()
        for line in problems or ["the settings could not be read"]:
            name, _, rest = line.partition(":")
            report.add("settings", name.strip()[:60] or "settings", WRONG, rest.strip()[:160], "The app would refuse to start until this is fixed.", ".env")
    else:
        report = run(settings, online=args.online, i_mean_live=args.i_mean_live)
        if args.send_test_email:
            try:
                delivered, detail = send_test_email(settings, args.send_test_email)
                report.add("mail relay", "test email", OK if delivered else WRONG, "one message sent" if delivered else "the relay refused it",
                           "" if delivered else "Check the relay's credentials and the sender address.")
            except Exception as exc:  # noqa: BLE001
                report.add("mail relay", "test email", WRONG, type(exc).__name__, "The message could not be sent.")
        if args.send_test_error:
            delivered, detail = send_test_error()
            report.add("error tracking", "test error", OK if delivered else WRONG, detail,
                       "" if delivered else "Set SENTRY_DSN (RUNBOOK 9.13) and run this again.")
    if args.json:
        print(json.dumps({"ready": report.ready, "items": [asdict(i) for i in report.items]}, indent=2))
    else:
        print(render_table(report))
    return 0 if report.ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
