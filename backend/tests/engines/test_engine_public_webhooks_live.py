"""The engines' public webhook events, live (Final session 1, Phase 6).

    gst.return.imported · gst.invoice.at_risk · gst.supplier.not_reported · automation.run.failed · automation.run.held

Each is written once per occurrence, only when an endpoint listens, in the caller's transaction, and carries ids and
figures only. A rule listening to the internal twin is unaffected: both audiences get the occurrence.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

import pytest
from sqlalchemy import func, select

from app.core import automation_events, webhook_events
from app.models.outbox_event import OutboxEvent
from app.models.webhook_endpoint import WebhookEndpointStatus
from app.services import outbox_service
from tests.engines.conftest import Engines, drain
from tests.engines.test_automation_triggers_live import _gst_world, _import, _sweep
from tests.engines.test_automation_volume_live import (_failing_webhook_rule, _invoice, _rule, _runs,  # noqa: F401
                                                      _set_endpoint)
from tests.engines.test_webhooks_live import receiver  # noqa: F401  (fixture)

pytestmark = pytest.mark.usefixtures("test_database")

EVENTS = ("gst.return.imported", "gst.invoice.at_risk", "gst.supplier.not_reported", "automation.run.failed",
          "automation.run.held")

#: Words a payload must never carry: a person's or company's name, an invoice number, a message, a rule's name.
FORBIDDEN_KEYS = {"supplier_name", "invoice_number", "error", "message", "name", "title", "rule_name", "email"}


def _listen(engines: Engines, *events: str) -> str:
    created = engines.post("/webhooks/endpoints", {"url": "https://hooks.acme.example.com/servabo", "event_types": list(events)},
                           org=True)
    assert created.status_code == 201, created.text
    return created.json()["endpoint"]["id"]


def _rows(engines: Engines, event_type: str) -> list[OutboxEvent]:
    engines.refresh()
    return list(engines.db.execute(select(OutboxEvent).where(
        OutboxEvent.organization_id == engines.org, OutboxEvent.event_type == event_type)
        .order_by(OutboxEvent.created_at)).scalars())


def _only_ids_and_figures(payload: dict[str, Any]) -> None:
    assert not (set(payload) & FORBIDDEN_KEYS), sorted(set(payload) & FORBIDDEN_KEYS)
    for key, value in payload.items():
        assert isinstance(value, (str, int, float, bool, type(None))), (key, value)


# ------------------------------------------------------------------------------------------- the vocabulary


@pytest.mark.parametrize("event_type", EVENTS)
def test_each_event_is_publishable_public_and_not_an_internal_event(event_type: str) -> None:
    assert event_type in webhook_events.WEBHOOK_EVENT_TYPES
    assert event_type not in automation_events.INTERNAL_EVENT_TYPES
    assert automation_events.visibility_for(event_type) == automation_events.VISIBILITY_PUBLIC


def test_only_the_two_run_events_are_public_under_the_reserved_automation_namespace() -> None:
    under = {e for e in webhook_events.WEBHOOK_EVENT_TYPES if e.startswith("automation.")}
    assert under == {"automation.run.failed", "automation.run.held"} == set(automation_events.PUBLIC_AUTOMATION_EVENTS)


# ------------------------------------------------------------------------------------------------ GST events


def test_a_gstr_2b_import_is_announced_once_to_a_listening_endpoint_and_never_to_nobody(engines: Engines) -> None:
    from app.services.gst import builder as b

    recipient, supplier, book_invoice = _gst_world(engines)
    today = date.today()
    period = f"{today.year:04d}-{today.month:02d}"
    documents = [b.document("ZZ-1", today - timedelta(days=2), 1_000)]

    assert _import(engines, recipient, period, documents).status_code == 200
    assert _rows(engines, "gst.return.imported") == [], "nobody listens, so nothing is written"

    _listen(engines, "gst.return.imported")
    replaced = _import(engines, recipient, period, documents + [b.document("ZZ-2", today - timedelta(days=1), 2_000)])
    assert replaced.status_code == 200, replaced.text
    rows = _rows(engines, "gst.return.imported")
    assert len(rows) == 1
    payload = rows[0].payload
    assert payload["gstin"] == recipient and payload["period"] == period and payload["currency"] == "INR"
    assert payload["workspace_id"] == str(engines.ws) and payload["records"] >= 2
    _only_ids_and_figures(payload)
    assert str(rows[0].visibility).endswith("PUBLIC")

    again = _import(engines, recipient, period, documents + [b.document("ZZ-2", today - timedelta(days=1), 2_000)])
    assert again.json()["results"][0]["status"] == "UNCHANGED"
    assert len(_rows(engines, "gst.return.imported")) == 1, "the same file again announces nothing"


def test_the_gst_clocks_send_an_invoice_at_risk_and_a_supplier_not_reported_once_each(engines: Engines) -> None:
    from app.services.gst import builder as b

    recipient, supplier, book_invoice = _gst_world(engines)
    _listen(engines, "gst.invoice.at_risk", "gst.supplier.not_reported")
    today = date.today()
    old_day, fresh_day = today - timedelta(days=155), today - timedelta(days=5)
    old = book_invoice(engines.db, engines.tenant, number="OLD-1", supplier="a", gstin=supplier, on=old_day, taxable=300_000)
    fresh = book_invoice(engines.db, engines.tenant, number="NEW-1", supplier="a", gstin=supplier, on=fresh_day, taxable=500_000)
    for item, day in ((old, old_day), (fresh, fresh_day)):
        item.created_at = datetime(day.year, day.month, day.day, 6, 0, tzinfo=timezone.utc)
    engines.db.commit()
    for day in (old_day, fresh_day):
        period = f"{day.year:04d}-{day.month:02d}"
        assert _import(engines, recipient, period, [b.document(f"ZZ-{period}", day, 1_000)]).status_code == 200
    drain()
    now = datetime.now(timezone.utc)

    _sweep(engines, now)
    risk, waiting = _rows(engines, "gst.invoice.at_risk"), _rows(engines, "gst.supplier.not_reported")
    assert [r.payload["work_item_id"] for r in risk] == [str(old.id)]
    assert {r.payload["work_item_id"] for r in waiting} == {str(old.id)}, "the 5-day-old invoice has not waited long enough"
    assert risk[0].payload["days_left"] <= 30 and risk[0].payload["currency"] == "INR"
    assert waiting[0].payload["supplier_gstin"] == supplier and waiting[0].payload["days_waiting"] >= 150
    for row in (*risk, *waiting):
        _only_ids_and_figures(row.payload)

    _sweep(engines, now + timedelta(hours=1))
    assert len(_rows(engines, "gst.invoice.at_risk")) == 1 and len(_rows(engines, "gst.supplier.not_reported")) == 1


# ---------------------------------------------------------------------------------------------- workflow runs


def test_a_failed_run_is_announced_once_without_its_error_text(engines: Engines, receiver) -> None:  # noqa: F811
    _listen(engines, "automation.run.failed")
    rule, endpoint_id = _failing_webhook_rule(engines)
    _set_endpoint(engines, endpoint_id, WebhookEndpointStatus.DISABLED)
    _invoice(engines, "INV-PUB-1")
    failed = next(r for r in _runs(engines, rule["id"]) if r["status"] == "FAILED")
    assert failed["error"], "the run itself keeps its explanation for people who may read it"

    rows = _rows(engines, "automation.run.failed")
    assert len(rows) == 1
    payload = rows[0].payload
    assert payload["execution_id"] == failed["id"] and payload["rule_id"] == rule["id"] and payload["status"] == "FAILED"
    assert payload["workspace_id"] == str(engines.ws) and payload["work_item_id"] == failed["work_item_id"]
    _only_ids_and_figures(payload)
    assert failed["error"] not in str(payload)

    drain()
    assert len(_rows(engines, "automation.run.failed")) == 1, "draining the queue announces nothing twice"


def test_a_stranded_run_that_the_reaper_times_out_is_announced_once(engines: Engines) -> None:
    from app.models.automation import AutomationRule
    from app.models.automation_execution import AutomationExecution, AutomationExecutionStatus
    from app.services.automation import executor

    _listen(engines, "automation.run.failed")
    rule = _rule(engines, "Tag every upload")
    row = engines.db.get(AutomationRule, uuid.UUID(rule["id"]))
    execution, _ = executor.create_execution(engines.db, rule=row, organization_id=engines.org, workspace_id=engines.ws)
    execution.status = AutomationExecutionStatus.RUNNING
    execution.deadline_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    execution.completed_at = None
    engines.db.commit()

    assert executor.reap_stranded(engines.db) == 1
    rows = _rows(engines, "automation.run.failed")
    assert [r.payload["status"] for r in rows] == ["TIMED_OUT"]
    assert executor.reap_stranded(engines.db) == 0
    assert len(_rows(engines, "automation.run.failed")) == 1
    assert engines.db.get(AutomationExecution, execution.id).status is AutomationExecutionStatus.TIMED_OUT


def test_a_held_back_run_is_announced_once_with_its_state(engines: Engines) -> None:
    _listen(engines, "automation.run.held")
    rule = _rule(engines, "Tag every upload", max_runs_per_hour=1)
    for number in ("INV-HELD-1", "INV-HELD-2", "INV-HELD-3"):
        _invoice(engines, number)
    held = [r for r in _runs(engines, rule["id"]) if r["status"] == "SKIPPED_THROTTLED"]
    assert len(held) == 2

    rows = _rows(engines, "automation.run.held")
    assert {r.payload["execution_id"] for r in rows} == {r["id"] for r in held}, "one event per held run"
    for row in rows:
        assert row.payload["status"] == "SKIPPED_THROTTLED" and row.payload["actions_executed"] == 0
        _only_ids_and_figures(row.payload)


def test_no_listener_no_row_and_a_rule_listening_still_hears_its_own_twin(engines: Engines) -> None:
    rule = _rule(engines, "Tag every upload", max_runs_per_hour=1)
    for number in ("INV-NL-1", "INV-NL-2"):
        _invoice(engines, number)
    assert _rows(engines, "automation.run.held") == []
    count = engines.db.execute(select(func.count()).select_from(OutboxEvent).where(
        OutboxEvent.organization_id == engines.org, OutboxEvent.event_type.like("automation.run.%"))).scalar_one()
    assert count == 0
    assert any(r["status"] == "SKIPPED_THROTTLED" for r in _runs(engines, rule["id"]))


def test_the_public_emit_never_raises_into_the_engine(engines: Engines, monkeypatch) -> None:
    _listen(engines, "automation.run.held")

    real_emit = outbox_service.emit

    def boom(*args: Any, **kwargs: Any) -> Any:
        if kwargs.get("event_type") == "automation.run.held":
            raise RuntimeError("the outbox is down")
        return real_emit(*args, **kwargs)

    monkeypatch.setattr(outbox_service, "emit", boom)
    rule = _rule(engines, "Tag every upload", max_runs_per_hour=1)
    for number in ("INV-BOOM-1", "INV-BOOM-2"):
        _invoice(engines, number)
    assert any(r["status"] == "SKIPPED_THROTTLED" for r in _runs(engines, rule["id"])), "the run was still recorded as held"
    assert _rows(engines, "automation.run.held") == [], "the write failed, was logged and dropped"
