"""Final session 1 (4A): a background job that fails is reported by the real worker loop, scrubbed, with the organization's opaque id.

The email-in handler's failure is reported the same way (a message that cannot be processed answers 500 and is reported with the workspace's id).
"""

from __future__ import annotations

import json

import pytest

from app.core import error_tracking
from app.core.config import settings
from app.services import job_service
from tests.engines.conftest import Engines
from tests.engines.test_job_slos_are_measured_live import _StopAfter
from tests.fakes.fake_sentry import FakeSentry

LEAKY = "could not read INV-2026-04417 for priya.sharma@sahyadri.example, GSTIN 27AABCS5555K1Z5, total ₹12,50,000.00, account 50100234567891"


@pytest.fixture()
def sentry(monkeypatch):
    with FakeSentry() as fake:
        monkeypatch.setattr(settings, "SENTRY_DSN", fake.dsn)
        error_tracking.init("worker")
        try:
            yield fake
        finally:
            error_tracking.shutdown()


def test_a_failing_job_is_reported_by_the_real_worker_loop(engines: Engines, sentry, monkeypatch):
    import app.worker as worker
    from app.workers.handlers import register_all

    register_all(replace=True)

    def boom(payload):
        raise RuntimeError(LEAKY)

    job_service.JOB_HANDLERS["test.boom"] = boom
    monkeypatch.setattr(worker, "_idle_sleep", lambda seconds: None)
    try:
        job_service.enqueue(engines.db, job_type="test.boom", payload={"x": 1}, organization_id=engines.org, max_attempts=1)
        engines.db.commit()
        worker.run_jobs_loop(shutdown=_StopAfter(20), batch_size=5, lease_seconds=60, idle_sleep_seconds=0, reap_every_n_passes=10_000)
    finally:
        job_service.JOB_HANDLERS.pop("test.boom", None)
    [event] = sentry.wait_for(1)
    blob = json.dumps(event)
    for leak in ("INV-2026-04417", "priya.sharma", "27AABCS5555K1Z5", "12,50,000", "50100234567891"):
        assert leak not in blob, leak
    assert event["tags"]["job_type"] == "test.boom" and event["tags"]["organization_id"] == str(engines.org)
    assert event["tags"]["service"] == "worker" and event["tags"]["area"] == "job"
    assert event["exception"]["values"][0]["type"] == "RuntimeError"


def test_an_email_in_message_that_breaks_is_reported_with_the_workspace_id_only(engines: Engines, sentry, monkeypatch):
    from pydantic import SecretStr

    from app.services.inbound_email import service
    from tests.fakes import fake_postmark_inbound as pm

    monkeypatch.setattr(settings, "POSTMARK_INBOUND_WEBHOOK_USER", pm.DEFAULT_USER)
    monkeypatch.setattr(settings, "POSTMARK_INBOUND_WEBHOOK_PASSWORD", SecretStr(pm.DEFAULT_PASSWORD))
    monkeypatch.setattr(settings, "POSTMARK_INBOUND_HASH", pm.DEFAULT_HASH)
    engines.plan("business")
    address = engines.get("/inbound-email").json()["address"]

    def broken(*args, **kwargs):
        raise RuntimeError(LEAKY)

    monkeypatch.setattr(service, "receive", broken)
    response = pm.post(engines.client, pm.for_address(address, sender="ap@supplier.example", subject="Invoice INV-2026-04417", attachments=[]))
    assert response.status_code == 500
    [event] = sentry.wait_for(1)
    blob = json.dumps(event)
    for leak in ("INV-2026-04417", "priya.sharma", "ap@supplier.example", "12,50,000"):
        assert leak not in blob, leak
    assert event["tags"]["area"] == "email_in" and event["tags"]["workspace_id"] == str(engines.ws)
