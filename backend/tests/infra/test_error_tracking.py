"""Final session 1 (4A): error tracking sends the failure and none of the customer.

A stand-in ingest (tests/fakes/fake_sentry.py) receives what the real SDK sends. Proven: empty DSN means off and nothing is sent; a 5xx and an
unhandled exception are sent and a 4xx is not; the worst the data of a customer can offer (an email, a token, an API key, a GSTIN, a PAN, an
IRN, a bank account number, an amount, a query string with a secret, a request body, a cookie, an Authorization header, a document's text, an
email-in sender) is gone from the event; organization and workspace ids are kept; a DSN that is not https is refused in production.
"""

from __future__ import annotations

import json

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.core import error_tracking
from app.core.config import settings
from tests.fakes.fake_sentry import FakeSentry

pytestmark = pytest.mark.no_db

SENSITIVE = {
    "email": "priya.sharma@sahyadri-packaging.example",
    "jwt": "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiIxMjM0NTYifQ.c2lnbmF0dXJlYnl0ZXM",
    "bearer": "Bearer abcdef1234567890abcdef",
    "api_key": "gsk_live_abcdefghijklmnop1234",
    "gstin": "27AABCS5555K1Z5",
    "pan": "AABCS5555K",
    "irn": "9f1c" * 16,
    "bank": "50100234567891",
    "amount": "₹12,50,000.00",
    "amount2": "INR 1,80,000.00",
    "invoice": "INV-2026-04417",
    "secret": "client_secret=hunter2hunter2",
}
TEXT = "failed on " + "; ".join(SENSITIVE.values())


@pytest.fixture()
def sentry(monkeypatch: pytest.MonkeyPatch):
    with FakeSentry() as fake:
        monkeypatch.setattr(settings, "SENTRY_DSN", fake.dsn)
        monkeypatch.setattr(settings, "SENTRY_TRACES_SAMPLE_RATE", 0.0)
        error_tracking.init("api")
        try:
            yield fake
        finally:
            error_tracking.shutdown()


def _leaks(event: dict) -> list[str]:
    blob = json.dumps(event)
    return [name for name, value in SENSITIVE.items() if value.split("=")[-1] in blob or value in blob]


def test_empty_dsn_is_off_and_sends_nothing(monkeypatch):
    with FakeSentry() as fake:
        monkeypatch.setattr(settings, "SENTRY_DSN", "")
        assert error_tracking.init("api") is False and error_tracking.enabled() is False
        error_tracking.capture(RuntimeError(TEXT), area="job")
        assert fake.requests == []


def test_scrub_text_removes_every_kind_of_customer_data():
    out = error_tracking.scrub_text(TEXT)
    for name, value in SENSITIVE.items():
        assert value.split("=")[-1] not in out, (name, out)
    assert "[email]" in out and "[gstin]" in out and "[amount]" in out


def test_an_unhandled_exception_and_a_5xx_are_sent_scrubbed_and_a_4xx_is_not(sentry):
    app = FastAPI()

    @app.get("/boom")
    def boom():
        raise RuntimeError(TEXT)

    @app.get("/missing")
    def missing():
        raise HTTPException(404, TEXT)

    @app.get("/unavailable")
    def unavailable():
        raise HTTPException(503, TEXT)

    client = TestClient(app, raise_server_exceptions=False)
    headers = {"Authorization": SENSITIVE["bearer"], "Cookie": "servabo_refresh=" + SENSITIVE["jwt"], "X-API-Key": SENSITIVE["api_key"]}
    assert client.get("/missing?token=" + SENSITIVE["jwt"], headers=headers).status_code == 404
    assert client.get("/boom?email=" + SENSITIVE["email"], headers=headers).status_code == 500
    assert client.post("/boom", json={"text": TEXT, "email": SENSITIVE["email"]}, headers=headers).status_code in (405, 500)
    assert client.get("/unavailable?q=" + SENSITIVE["gstin"], headers=headers).status_code == 503
    events = sentry.wait_for(2)
    assert len(events) >= 2, "the 500 and the 503 are sent"
    for event in events:
        assert _leaks(event) == [], (_leaks(event), event)
        assert "headers" in event["request"] and all(v == "[dropped]" for v in event["request"]["headers"].values())
        assert "?" not in event["request"]["url"] and "data" not in event["request"] and "cookies" not in event["request"]
        assert event.get("user") is None and not event.get("breadcrumbs") and event["tags"]["service"] == "api"
    blob = json.dumps(events)
    assert "/missing" not in blob, "an expected 404 is not an error"


def test_a_captured_job_failure_keeps_the_opaque_ids_and_drops_the_rest(sentry):
    error_tracking.capture(RuntimeError(TEXT), area="job", job_type="receipt.monthly", organization_id="5d11d699-e466-49c2-99d8-9efdf2cbcce3",
                           attempt="2/6", customer_email=SENSITIVE["email"])
    [event] = sentry.wait_for(1)
    assert _leaks(event) == []
    assert event["tags"]["job_type"] == "receipt.monthly" and event["tags"]["organization_id"] == "5d11d699-e466-49c2-99d8-9efdf2cbcce3"
    assert event["tags"]["area"] == "job" and event["tags"].get("customer_email") == "[dropped]"


def test_source_lines_and_local_variables_are_not_sent(sentry):
    secret_local = SENSITIVE["bank"]  # noqa: F841 - a local variable the SDK would send by default

    def fails():
        raise ValueError("boom " + SENSITIVE["bank"])

    try:
        fails()
    except ValueError as exc:
        error_tracking.capture(exc, area="job", job_type="x")
    [event] = sentry.wait_for(1)
    for frame in event["exception"]["values"][0]["stacktrace"]["frames"]:
        assert "vars" not in frame and "context_line" not in frame
    assert SENSITIVE["bank"] not in json.dumps(event)


def test_the_ingest_host_is_read_from_the_dsn_for_the_content_security_policy():
    assert error_tracking.ingest_host("https://abc123@o4500000.ingest.de.sentry.io/4500001") == "o4500000.ingest.de.sentry.io"
    assert error_tracking.ingest_host("") is None and error_tracking.ingest_host("not a dsn") is None


def test_a_dsn_that_is_not_https_is_refused_in_production():
    from app.core.production_guard import production_config_problems

    class S:
        pass

    base = settings.model_copy(update={"SENTRY_DSN": "http://abc@errors.example.com/1"})
    assert any(p.startswith("SENTRY_DSN") for p in production_config_problems(base, "production"))
    ok = settings.model_copy(update={"SENTRY_DSN": "https://abc@o1.ingest.de.sentry.io/1"})
    assert not any(p.startswith("SENTRY_DSN") for p in production_config_problems(ok, "production"))
    off = settings.model_copy(update={"SENTRY_DSN": ""})
    assert not any(p.startswith("SENTRY_DSN") for p in production_config_problems(off, "production"))


def test_a_tan_is_scrubbed_as_a_tan_and_never_reaches_the_ingest():
    """Final 2T, Phase 9: a deductor's TAN (four letters, five digits, a letter) is a tax identifier like a PAN."""
    from app.core.error_tracking import scrub_event, scrub_text

    assert scrub_text("deductor ABCD12345E withheld") == "deductor [tan] withheld"
    assert scrub_text("PAN ABCDE1234F and TAN ABCD12345E") == "PAN [pan] and TAN [tan]"
    assert "ABCD12345E" not in scrub_text("https://x.example/trinetra?tan=ABCD12345E&x=1")
    event = scrub_event({"message": "failed for ABCD12345E", "exception": {"values": [{"value": "TAN ABCD12345E rejected"}]}}, {})
    assert "ABCD12345E" not in str(event)
