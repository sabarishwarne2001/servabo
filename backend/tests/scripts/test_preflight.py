"""Final session 1 (4B): `scripts/preflight.py` says whether a setup is ready, and never prints a secret.

Each check is proven with a production-like environment built exactly as the app builds its settings, one thing wrong at a time; the online
probes run against stand-ins (httpx.MockTransport, a fake SMTP, fake database and storage probes). Across every mode, no secret value appears in the
output.
"""

from __future__ import annotations

import json
import secrets

import httpx
import pytest
from pydantic import SecretStr

from app.core.config import Settings
from scripts import dodo_setup, preflight
from tests.infra.test_configuration_contract import REQUIRED_IN_PRODUCTION, _aliases, FIELDS, good_production_env

pytestmark = pytest.mark.no_db

SECRETS = {
    "POSTGRES_PASSWORD": secrets.token_urlsafe(24),
    "JWT_SECRET_KEY": secrets.token_hex(32),
    "GROQ_API_KEY": "gsk_" + secrets.token_hex(24),
    "DODO_API_KEY": "dodo_live_secret_" + secrets.token_hex(12),
    "DODO_WEBHOOK_SECRET": "whsec_" + secrets.token_hex(16),
    "S3_SECRET_ACCESS_KEY": secrets.token_urlsafe(30),
    "PLATFORM_SMTP_PASSWORD": "smtp_pw_" + secrets.token_hex(12),
    "ZOHO_CLIENT_SECRET": "zoho_secret_" + secrets.token_hex(12),
    "POSTMARK_INBOUND_WEBHOOK_PASSWORD": "inbound_pw_" + secrets.token_hex(12),
}


def environment() -> dict[str, str]:
    values = good_production_env()
    for needs in REQUIRED_IN_PRODUCTION.values():
        values.update(needs)
    values.update(SECRETS)
    values.update({
        "WEBSITE_URL": "https://servabo.app", "S3_ENDPOINT_URL": "https://acc123.eu.r2.cloudflarestorage.com", "STORAGE_BACKEND": "r2",
        "PLATFORM_SMTP_USERNAME": "postmark-user", "BILLING_GATEWAY": "DODO", "DODO_LIVEMODE": "false", "DODO_API_BASE": dodo_setup.TEST_HOST,
        "ZOHO_CLIENT_ID": "1000.ABCDEFGHIJKLMN", "ZOHO_REDIRECT_URI": "https://app.example.com/api/v1/public/erp/zoho/callback",
        "POSTMARK_INBOUND_WEBHOOK_USER": "pm", "POSTMARK_INBOUND_HASH": "abc123hash", "SENTRY_DSN": "https://publickey@o1.ingest.de.sentry.io/1",
    })
    for item in dodo_setup.wanted_products():
        values[item.env] = "pdt_" + item.env.lower()[-10:]
    return values


@pytest.fixture()
def boot(monkeypatch: pytest.MonkeyPatch):
    for name in set(FIELDS) | _aliases() | {"EMAIL_ENCRYPTION_KEY", "SERVICE_ROLE"}:
        monkeypatch.delenv(name, raising=False)
    for name in [n for n in list(__import__("os").environ) if n.startswith(("GATEWAY_PRICE_ID_", "DODO_ADDON_"))]:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("SERVABO_BACKUP_KEY", __import__("base64").b64encode(secrets.token_bytes(32)).decode())
    monkeypatch.setenv("SERVABO_BACKUP_DIR", __import__("tempfile").mkdtemp())
    monkeypatch.setenv("ALERT_WEBHOOK", "https://hc-ping.com/abc-def/fail")
    monkeypatch.setenv("SENTRY_INGEST_HOST", "o2.ingest.de.sentry.io")
    monkeypatch.setattr(preflight, "probe_database", lambda s: None)
    monkeypatch.setattr(preflight, "probe_redis", lambda s: None)
    monkeypatch.setattr(preflight, "probe_storage", lambda s: None)
    monkeypatch.setattr(preflight, "probe_smtp", lambda s: None)

    import sys
    import types

    cpu_torch = types.ModuleType("torch")
    cpu_torch.version = types.SimpleNamespace(cuda=None)          # the web image carries the CPU build
    monkeypatch.setitem(sys.modules, "torch", cpu_torch)

    def _boot(**changes: str) -> Settings:
        """The valid production settings, then `changes` applied AFTER validation: the app itself would refuse to start on some of them, and
        preflight must still be able to say what is wrong with them."""
        for key, value in environment().items():
            monkeypatch.setenv(key, value)
        settings = Settings(_env_file=None)
        secret_fields = {n for n, f in Settings.model_fields.items() if "SecretStr" in str(f.annotation)}
        for key in [k for k in changes if k not in Settings.model_fields]:          # read straight from the environment (the price ids)
            monkeypatch.setenv(key, changes[key])
        changes = {k: v for k, v in changes.items() if k in Settings.model_fields}
        update = {k: (SecretStr(v) if k in secret_fields and v != "" else (None if k in secret_fields else v)) for k, v in changes.items()}
        if "DODO_LIVEMODE" in update:
            update["DODO_LIVEMODE"] = update["DODO_LIVEMODE"] == "true"
        return settings.model_copy(update=update)

    return _boot


def status_of(report: preflight.Report, name: str) -> str:
    return next(i.status for i in report.items if i.name.startswith(name))


def test_a_complete_production_setup_is_ready(boot):
    report = preflight.run(boot())
    bad = [(i.name, i.status, i.detail) for i in report.items if i.status in (preflight.MISSING, preflight.WRONG)]
    assert bad == [] and report.ready


@pytest.mark.parametrize("change,item,expected", [
    ({"FRONTEND_URL": "http://app.example.com"}, "FRONTEND_URL", preflight.WRONG),
    ({"CORS_ORIGINS": "https://other.example.com"}, "CORS_ORIGINS", preflight.WRONG),
    ({"S3_ENDPOINT_URL": "https://acc123.r2.cloudflarestorage.com"}, "R2 jurisdiction", preflight.WRONG),
    ({"GROQ_API_KEY": ""}, "Groq key", preflight.MISSING),
    ({"DODO_LIVEMODE": "true"}, "test or live", preflight.WRONG),
    ({"DODO_WEBHOOK_SECRET": ""}, "webhook secret", preflight.MISSING),
    ({"GATEWAY_PRICE_ID_BUSINESS": ""}, "product ids", preflight.WRONG),
    ({"ZOHO_CLIENT_SECRET": ""}, "Zoho Books", preflight.WRONG),
    ({"ZOHO_REDIRECT_URI": "https://app.example.com/callback"}, "Zoho Books", preflight.WRONG),
    ({"POSTMARK_INBOUND_HASH": ""}, "email-in", preflight.WRONG),
    ({"EINVOICE_QR_PUBLIC_KEY_PEM": "not a key"}, "NIC e-invoice key", preflight.WRONG),
    ({"OPERATOR_ALERT_EMAILS": "ops-at-example"}, "OPERATOR_ALERT_EMAILS", preflight.WRONG),
])
def test_each_thing_wrong_is_named(boot, change, item, expected):
    report = preflight.run(boot(**change))
    assert status_of(report, item) == expected, [(i.name, i.status) for i in report.items]
    assert not report.ready or expected == preflight.SKIPPED


def test_optional_things_that_are_off_are_skipped_not_wrong(boot):
    report = preflight.run(boot(SENTRY_DSN="", ZOHO_CLIENT_ID="", ZOHO_CLIENT_SECRET="", ZOHO_REDIRECT_URI="", POSTMARK_INBOUND_WEBHOOK_USER="",
                                POSTMARK_INBOUND_WEBHOOK_PASSWORD="", POSTMARK_INBOUND_HASH="", GEMINI_API_KEY=""))
    for name in ("error tracking", "Zoho Books", "email-in", "Gemini key", "NIC e-invoice key"):
        assert status_of(report, name) == preflight.SKIPPED, name
    assert report.ready


def test_a_dsn_without_the_web_hosts_csp_entry_is_missing(boot, monkeypatch):
    monkeypatch.delenv("SENTRY_INGEST_HOST", raising=False)
    report = preflight.run(boot())
    assert status_of(report, "web app ingest host") == preflight.MISSING
    assert "o1.ingest.de.sentry.io" in next(i.fix for i in report.items if i.name == "web app ingest host")


def test_a_local_setup_is_not_held_to_production_rules(boot):
    report = preflight.run(boot(ENVIRONMENT="development", STORAGE_BACKEND="local", FRONTEND_URL="http://localhost:3000", CORS_ORIGINS="http://localhost:3000"))
    assert status_of(report, "storage") == preflight.SKIPPED and status_of(report, "FRONTEND_URL") == preflight.OK


def test_online_probes_report_what_they_find(boot, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.groq.com":
            return httpx.Response(200, json={"data": []})
        if request.url.host == "test.dodopayments.com":
            return httpx.Response(200, json={"items": [{"product_id": "pdt_" + i.env.lower()[-10:]} for i in dodo_setup.wanted_products()]})
        if request.url.host == "api.postmarkapp.com":
            return httpx.Response(200, json={"Name": "server"})
        return httpx.Response(404)

    monkeypatch.setattr(preflight, "HTTP_CLIENT", lambda: httpx.Client(transport=httpx.MockTransport(handler)))
    report = preflight.run(boot(), online=True)
    online = {i.name: i.status for i in report.items if "(online)" in i.name}
    assert online and set(online.values()) == {preflight.OK}, online
    # a product the account lacks, and a key Groq refuses
    monkeypatch.setattr(preflight, "HTTP_CLIENT", lambda: httpx.Client(transport=httpx.MockTransport(
        lambda r: httpx.Response(401) if r.url.host == "api.groq.com" else httpx.Response(200, json={"items": []}))))
    report = preflight.run(boot(), online=True)
    assert status_of(report, "Groq models (online)") == preflight.WRONG and status_of(report, "products (online)") == preflight.WRONG


def test_online_never_reads_a_live_dodo_account_without_the_flag(boot, monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(preflight, "HTTP_CLIENT", lambda: httpx.Client(transport=httpx.MockTransport(lambda r: calls.append(r.url.host) or httpx.Response(200, json={"items": []}))))
    live = boot(DODO_LIVEMODE="true", DODO_API_BASE=dodo_setup.LIVE_HOST)
    report = preflight.run(live, online=True)
    assert status_of(report, "products (online)") == preflight.SKIPPED and "live.dodopayments.com" not in calls
    preflight.run(live, online=True, i_mean_live=True)
    assert "live.dodopayments.com" in calls


def test_offline_contacts_nothing(boot, monkeypatch):
    def explode(*a, **k):
        raise AssertionError("offline mode made a connection")

    monkeypatch.setattr(preflight, "HTTP_CLIENT", explode)
    for probe in ("probe_database", "probe_redis", "probe_storage", "probe_smtp"):
        monkeypatch.setattr(preflight, probe, explode)
    assert preflight.run(boot()).ready


def test_no_secret_ever_appears_in_the_output_in_any_mode(boot, monkeypatch, capsys):
    monkeypatch.setattr(preflight, "HTTP_CLIENT", lambda: httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"items": []}))))
    monkeypatch.setattr(preflight, "send_test_email", lambda s, to: (True, "ok"))
    settings = boot(GROQ_API_KEY=SECRETS["GROQ_API_KEY"])
    monkeypatch.setattr(preflight, "load_settings", lambda: (settings, None))
    outputs = []
    for argv in ([], ["--offline"], ["--online"], ["--online", "--i-mean-live"], ["--json"], ["--online", "--json"], ["--send-test-email", "me@example.com"]):
        preflight.main(argv)
        outputs.append(capsys.readouterr().out)
    blob = "\n".join(outputs)
    for name, secret in SECRETS.items():
        assert secret not in blob, f"{name} printed"
    assert "1000.ABCDEFGHIJKLMN" not in blob and "…KLMN" in blob          # a public id shows its last four only
    assert json.loads(outputs[4])["ready"] is True


def test_the_exit_code_and_json(boot, monkeypatch, capsys):
    monkeypatch.setattr(preflight, "load_settings", lambda: (boot(), None))
    assert preflight.main([]) == 0
    capsys.readouterr()
    monkeypatch.setattr(preflight, "load_settings", lambda: (boot(GROQ_API_KEY=""), None))
    assert preflight.main(["--json"]) == 1
    body = json.loads(capsys.readouterr().out)
    assert body["ready"] is False and any(i["status"] == "MISSING" for i in body["items"])


def test_when_the_app_would_refuse_to_start_the_reasons_are_reported_without_values(monkeypatch, capsys):
    monkeypatch.setattr(preflight, "load_settings", lambda: (None, ["JWT_SECRET_KEY: is shorter than 32 characters.", "REDIS_URL: is not set."]))
    assert preflight.main([]) == 1
    out = capsys.readouterr().out
    assert "JWT_SECRET_KEY" in out and "REDIS_URL" in out and "NOT READY" in out


def test_send_test_error_sends_one_error_through_the_apps_own_tracking_and_nothing_secret(boot, monkeypatch, capsys):
    from app.core import error_tracking

    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(error_tracking, "init", lambda service: sent.append(("init", service)) or True)
    monkeypatch.setattr(error_tracking, "capture", lambda exc, *, area, **tags: sent.append((area, str(exc))))
    monkeypatch.setattr(error_tracking, "shutdown", lambda: sent.append(("shutdown", "")))
    settings = boot()
    monkeypatch.setattr(preflight, "load_settings", lambda: (settings, None))
    preflight.main(["--send-test-error"])
    out = capsys.readouterr().out
    assert sent == [("init", "preflight"), ("preflight", "Servabo preflight test error (safe to ignore)"), ("shutdown", "")]
    assert "one test error sent" in out and "publickey" not in out, "the DSN's key never prints"


def test_send_test_error_says_so_when_error_tracking_is_off(boot, monkeypatch, capsys):
    from app.core import error_tracking

    monkeypatch.setattr(error_tracking, "init", lambda service: False)
    monkeypatch.setattr(error_tracking, "capture", lambda *a, **k: pytest.fail("nothing may be sent when tracking is off"))
    settings = boot()
    monkeypatch.setattr(preflight, "load_settings", lambda: (settings, None))
    assert preflight.main(["--send-test-error"]) == 1
    assert "SENTRY_DSN is empty" in capsys.readouterr().out
