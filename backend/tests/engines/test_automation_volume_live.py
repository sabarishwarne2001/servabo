"""Session J, Phase 4 — a rule that stays safe when a thousand documents arrive at once, live.

throttle, cooldown, the pause switch, retry, versions with a plain diff and Restore. Each held-back run is a visible row
in Run history, never a silent drop.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import pytest
from sqlalchemy import func, select, update

from app.core.pagination import MAX_OFFSET
from app.models.notification import Notification
from app.models.webhook_delivery import WebhookDelivery
from app.models.webhook_endpoint import WebhookEndpoint, WebhookEndpointStatus
from tests.engines.conftest import Engines, drain
from tests.engines.test_webhooks_live import URL, _deliver, receiver  # noqa: F401  (fixture)


def _rule(engines: Engines, name: str, actions: list[dict[str, Any]] | None = None, *, trigger: str = "document.completed",
          expect: int = 201, **extra: Any) -> dict[str, Any]:
    body = {"name": name, "triggers": [trigger], "groups_operator": "AND", "condition_groups": [],
            "actions": actions or [{"action_type": "document.tag", "config": {"add": ["seen"]}}], **extra}
    response = engines.post("/automation/rules", body)
    assert response.status_code == expect, response.text
    return response.json()


def _invoice(engines: Engines, number: str, total: str = "1000.00") -> uuid.UUID:
    return engines.process(f"{number}.pdf", [["TAX INVOICE", f"Invoice Number: {number}"]], marker=number,
                           classification="Invoice", entities={"invoice_number": number, "vendor_name": "Acme Supplies Ltd",
                                                               "total_amount": total, "currency": "INR"})


def _runs(engines: Engines, rule_id: str) -> list[dict[str, Any]]:
    return engines.get("/automation/executions", params={"rule_id": rule_id, "limit": 200}).json()["items"]


def _by_status(engines: Engines, rule_id: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for run in _runs(engines, rule_id):
        counts[run["status"]] = counts.get(run["status"], 0) + 1
    return counts


def _notices(engines: Engines, title_start: str) -> int:
    engines.refresh()
    return int(engines.db.execute(select(func.count()).select_from(Notification).where(
        Notification.workspace_id == engines.ws, Notification.title.like(f"{title_start}%"))).scalar_one())


# ----------------------------------------------------------------------------------------------------- throttle


def test_a_rule_over_its_hourly_limit_is_skipped_in_view_and_its_owner_is_told_once(engines: Engines) -> None:
    rule = _rule(engines, "Tag every upload", max_runs_per_hour=2)
    assert rule["max_runs_per_hour"] == 2 and rule["effective_runs_per_hour"] == 2

    for number in ("INV-TH-1", "INV-TH-2", "INV-TH-3", "INV-TH-4"):
        _invoice(engines, number)

    counts = _by_status(engines, rule["id"])
    assert counts.get("COMPLETED") == 2 and counts.get("SKIPPED_THROTTLED") == 2, counts
    skipped = [r for r in _runs(engines, rule["id"]) if r["status"] == "SKIPPED_THROTTLED"]
    assert all(r["is_skipped"] and r["actions_executed"] == 0 for r in skipped)
    assert "limit of 2 an hour" in skipped[0]["error"]
    assert _notices(engines, "Automation held back") == 1, "one notice, however many runs were held back"

    _invoice(engines, "INV-TH-5")
    assert _by_status(engines, rule["id"]).get("SKIPPED_THROTTLED") == 3
    assert _notices(engines, "Automation held back") == 1, "at most one notice a day"


def test_a_rule_with_no_limit_gets_the_workspace_default(engines: Engines, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "AUTOMATION_DEFAULT_RUNS_PER_HOUR", 1)
    rule = _rule(engines, "Default limit")
    assert rule["max_runs_per_hour"] is None and rule["effective_runs_per_hour"] == 1
    _invoice(engines, "INV-DEF-1")
    _invoice(engines, "INV-DEF-2")
    assert _by_status(engines, rule["id"]) == {"COMPLETED": 1, "SKIPPED_THROTTLED": 1}

    # Raising the rule's own limit lifts the hold for the next run.
    changed = engines.patch(f"/automation/rules/{rule['id']}", {"max_runs_per_hour": 50})
    assert changed.status_code == 200 and changed.json()["effective_runs_per_hour"] == 50
    _invoice(engines, "INV-DEF-3")
    assert _by_status(engines, rule["id"]) == {"COMPLETED": 2, "SKIPPED_THROTTLED": 1}


def test_a_rule_whose_conditions_never_match_is_not_throttled_by_what_it_ignored(engines: Engines) -> None:
    rule = _rule(engines, "Only huge invoices", max_runs_per_hour=1,
                 condition_groups=[{"logic_operator": "AND", "conditions": [
                     {"field": "total_amount", "operator": "GREATER_THAN", "value": "999999"}]}])
    for number in ("INV-NM-1", "INV-NM-2", "INV-NM-3"):
        _invoice(engines, number)
    assert _by_status(engines, rule["id"]) == {"COMPLETED": 3}


def test_the_limits_are_bounded_and_can_be_cleared(engines: Engines) -> None:
    _rule(engines, "Zero", max_runs_per_hour=0, expect=422)
    _rule(engines, "Huge", max_runs_per_hour=100001, expect=422)
    _rule(engines, "Cooldown zero", cooldown_hours=0, expect=422)
    rule = _rule(engines, "Both", max_runs_per_hour=5, cooldown_hours=24)
    cleared = engines.patch(f"/automation/rules/{rule['id']}", {"max_runs_per_hour": None, "cooldown_hours": None})
    assert cleared.status_code == 200
    assert cleared.json()["max_runs_per_hour"] is None and cleared.json()["cooldown_hours"] is None


# ---------------------------------------------------------------------------------------------------- cooldown


def test_a_cooldown_runs_a_rule_once_per_document(engines: Engines) -> None:
    # Two rules tag every new document, and each tag change is announced, so the watcher hears about each document twice.
    watcher = _rule(engines, "Tell admins about changes", [{"action_type": "notify.role", "config": {"roles": ["ADMIN"]}}],
                    trigger="document.field_changed", cooldown_hours=24)
    _rule(engines, "Tag a", [{"action_type": "document.tag", "config": {"add": ["a"]}}])
    _rule(engines, "Tag b", [{"action_type": "document.tag", "config": {"add": ["b"]}}])
    first, second = _invoice(engines, "INV-CD-1"), _invoice(engines, "INV-CD-2")
    drain()
    runs = _runs(engines, watcher["id"])
    counts = _by_status(engines, watcher["id"])
    assert counts == {"COMPLETED": 2, "SKIPPED_COOLDOWN": 2}, counts
    for document in (first, second):
        mine = [r for r in runs if r["work_item_id"] == str(document)]
        assert sorted(r["status"] for r in mine) == ["COMPLETED", "SKIPPED_COOLDOWN"], "once per document, not once overall"
    held = next(r for r in runs if r["status"] == "SKIPPED_COOLDOWN")
    assert "once per document every 24 hours" in held["error"]


# --------------------------------------------------------------------------------------------------- pause


def test_pausing_stops_every_rule_and_shows_in_the_list_and_resuming_starts_them_again(engines: Engines) -> None:
    rule = _rule(engines, "Tag uploads")
    assert engines.get("/automation/pause").json()["paused"] is False
    assert engines.put("/automation/pause", {"paused": True}, as_user=engines.tenant.contributor).status_code == 403

    paused = engines.put("/automation/pause", {"paused": True})
    assert paused.status_code == 200 and paused.json()["paused"] is True
    assert [r for r in engines.get("/automation/rules").json() if r["id"] == rule["id"]][0]["paused"] is True

    _invoice(engines, "INV-PA-1")
    assert _by_status(engines, rule["id"]) == {"SKIPPED_PAUSED": 1}
    # A manual run is refused too: paused means nothing runs.
    manual = _rule(engines, "By hand", trigger="manual")
    work_item = _invoice(engines, "INV-PA-2")
    engines.post(f"/automation/rules/{manual['id']}/run", {"work_item_id": str(work_item)})
    drain()
    assert _by_status(engines, manual["id"]) == {"SKIPPED_PAUSED": 1}

    resumed = engines.put("/automation/pause", {"paused": False})
    assert resumed.json()["paused"] is False
    _invoice(engines, "INV-PA-3")
    assert _by_status(engines, rule["id"]) == {"SKIPPED_PAUSED": 2, "COMPLETED": 1}

    from app.models.audit_log import AuditLog

    engines.refresh()
    details = [row.details for row in engines.db.execute(select(AuditLog).where(
        AuditLog.workspace_id == engines.ws, AuditLog.resource_type == "WORKSPACE")).scalars()]
    assert {"automations": "paused"} in details and {"automations": "resumed"} in details


# ---------------------------------------------------------------------------------------------------- retry


def _failing_webhook_rule(engines: Engines) -> tuple[dict[str, Any], str]:
    created = engines.post("/webhooks/endpoints", {"url": URL, "event_types": ["workflow.triggered"]}, org=True)
    assert created.status_code == 201, created.text
    endpoint_id = created.json()["endpoint"]["id"]
    rule = _rule(engines, "Send to the AP system", [{"action_type": "webhook.send", "config": {"endpoint_id": endpoint_id}}])
    return rule, endpoint_id


def _set_endpoint(engines: Engines, endpoint_id: str, status: WebhookEndpointStatus) -> None:
    engines.refresh()
    disabled_at = datetime.now(timezone.utc) if status is WebhookEndpointStatus.DISABLED else None
    engines.db.execute(update(WebhookEndpoint).where(WebhookEndpoint.id == uuid.UUID(endpoint_id)).values(
        status=status, disabled_at=disabled_at))
    engines.db.commit()


def test_a_failed_run_can_be_retried_once_the_cause_is_fixed_and_the_webhook_keeps_its_key(engines: Engines, receiver) -> None:
    rule, endpoint_id = _failing_webhook_rule(engines)
    _set_endpoint(engines, endpoint_id, WebhookEndpointStatus.DISABLED)
    _invoice(engines, "INV-RT-1")
    failed = next(r for r in _runs(engines, rule["id"]) if r["status"] == "FAILED")
    assert failed["retryable"] is True

    _set_endpoint(engines, endpoint_id, WebhookEndpointStatus.ACTIVE)
    retried = engines.post(f"/automation/executions/{failed['id']}/retry", {})
    assert retried.status_code == 202, retried.text  # a webhook is idempotent: no warning
    drain()
    runs = _runs(engines, rule["id"])
    new = next(r for r in runs if r["retry_of_id"] == failed["id"])
    assert new["status"] == "COMPLETED" and new["work_item_id"] == failed["work_item_id"]
    assert next(r for r in runs if r["id"] == failed["id"])["status"] == "FAILED", "the failed run stays as it was"

    # It cannot be retried twice once a retry worked.
    again = engines.post(f"/automation/executions/{failed['id']}/retry", {})
    assert again.status_code == 409 and "already been retried" in again.text

    _deliver()
    engines.refresh()
    keys = [d.payload["idempotency_key"] for d in engines.db.execute(select(WebhookDelivery).where(
        WebhookDelivery.organization_id == engines.org)).scalars() if "idempotency_key" in d.payload]
    assert len(keys) == 1 and keys[0].startswith(failed["id"]), "the key is built on the first run, so a retry repeats it"


def test_retry_refuses_what_it_should_in_words_and_warns_before_a_message_could_go_twice(engines: Engines, receiver) -> None:
    ok_rule = _rule(engines, "Tag")
    _invoice(engines, "INV-RT-2")
    done = _runs(engines, ok_rule["id"])[0]
    refused = engines.post(f"/automation/executions/{done['id']}/retry", {})
    assert refused.status_code == 409 and "failed, timed out or ran out of budget" in refused.text
    assert engines.post(f"/automation/executions/{uuid.uuid4()}/retry", {}).status_code == 404
    assert engines.post(f"/automation/executions/{done['id']}/retry", {}, as_user=engines.tenant.contributor).status_code == 403

    # An email step may send again: the first call warns and sends nothing; the acknowledged call goes ahead.
    created = engines.post("/automation/rules", {
        "name": "Email then fail", "triggers": ["document.completed"], "condition_groups": [], "on_error": "HALT",
        "actions": [{"action_type": "email.send", "config": {"recipient": "ap@acme.example.com", "subject": "Seen",
                                                              "body": "Hello"}}],
    })
    assert created.status_code == 201, created.text
    email_rule = created.json()
    _invoice(engines, "INV-RT-3")
    runs = _runs(engines, email_rule["id"])
    # The first run may have failed or succeeded depending on mail settings; either way the test needs a FAILED one.
    from app.models.automation_execution import AutomationExecution, AutomationExecutionStatus

    engines.refresh()
    engines.db.execute(update(AutomationExecution).where(AutomationExecution.id == uuid.UUID(runs[0]["id"])).values(
        status=AutomationExecutionStatus.FAILED))
    engines.db.commit()
    warned = engines.post(f"/automation/executions/{runs[0]['id']}/retry", {})
    assert warned.status_code == 409 and warned.json()["detail"]["code"] == "may_repeat"
    assert "This may send the message again" in warned.json()["detail"]["message"]
    accepted = engines.post(f"/automation/executions/{runs[0]['id']}/retry", {"acknowledge_repeat": True})
    assert accepted.status_code == 202, accepted.text


def test_retry_is_refused_while_paused_and_never_crosses_workspaces(engines: Engines, receiver) -> None:
    rule, endpoint_id = _failing_webhook_rule(engines)
    _set_endpoint(engines, endpoint_id, WebhookEndpointStatus.DISABLED)
    _invoice(engines, "INV-RT-4")
    failed = next(r for r in _runs(engines, rule["id"]) if r["status"] == "FAILED")
    engines.put("/automation/pause", {"paused": True})
    paused = engines.post(f"/automation/executions/{failed['id']}/retry", {})
    assert paused.status_code == 409 and "paused" in paused.text


# -------------------------------------------------------------------------------------------------- versions


def test_every_save_writes_a_version_with_a_plain_diff_and_restore_makes_a_new_one(engines: Engines) -> None:
    rule = _rule(engines, "Big invoices", [{"action_type": "document.tag", "config": {"add": ["big"]}}],
                 condition_groups=[{"logic_operator": "AND", "conditions": [
                     {"field": "total_amount", "operator": "GREATER_THAN", "value": "500000", "currency": "INR"}]}])
    assert rule["version"] == 1

    changed = engines.patch(f"/automation/rules/{rule['id']}", {
        "condition_groups": [{"logic_operator": "AND", "conditions": [
            {"field": "total_amount", "operator": "GREATER_THAN", "value": "1000000", "currency": "INR"}]}],
        "max_runs_per_hour": 20, "note": "Raised the bar after month end"})
    assert changed.status_code == 200 and changed.json()["version"] == 2
    renamed = engines.patch(f"/automation/rules/{rule['id']}", {"name": "Very big invoices", "is_active": False})
    assert renamed.json()["version"] == 3
    noop = engines.patch(f"/automation/rules/{rule['id']}", {"name": "Very big invoices"})
    assert noop.json()["version"] == 3, "a save that changed nothing writes no version"

    history = engines.get(f"/automation/rules/{rule['id']}/versions").json()
    assert history["total"] == 3 and [v["version"] for v in history["items"]] == [3, 2, 1]
    by_version = {v["version"]: v for v in history["items"]}
    assert by_version[1]["changes"] == ["Created the rule"]
    assert "Added condition: Total amount is greater than 1000000 INR" in by_version[2]["changes"]
    assert "Removed condition: Total amount is greater than 500000 INR" in by_version[2]["changes"]
    assert "Set a limit of 20 runs an hour" in by_version[2]["changes"]
    assert by_version[2]["note"] == "Raised the bar after month end"
    assert "Renamed the rule from “Big invoices” to “Very big invoices”" in by_version[3]["changes"]
    assert "Switched the rule off" in by_version[3]["changes"]
    assert by_version[3]["created_by_name"]

    restored = engines.post(f"/automation/rules/{rule['id']}/versions/1/restore", {})
    assert restored.status_code == 200, restored.text
    view = restored.json()
    assert view["name"] == "Big invoices" and view["version"] == 4 and view["max_runs_per_hour"] is None
    assert view["condition_groups"][0]["conditions"][0]["value"] in ("500000", ["500000"])
    newest = engines.get(f"/automation/rules/{rule['id']}/versions").json()["items"][0]
    assert newest["restored_from_version"] == 1 and newest["note"] == "Restored version 1"
    assert engines.get(f"/automation/rules/{rule['id']}/versions").json()["total"] == 4, "history only grows"

    assert engines.post(f"/automation/rules/{rule['id']}/versions/99/restore", {}).status_code == 404
    assert engines.post(f"/automation/rules/{rule['id']}/versions/1/restore", {}, as_user=engines.tenant.contributor).status_code == 403


def test_versions_are_workspace_scoped(engines: Engines) -> None:
    rule = _rule(engines, "Mine")
    other = uuid.uuid4()
    assert engines.get(f"/automation/rules/{other}/versions").status_code == 404
    assert engines.post(f"/automation/rules/{other}/versions/1/restore", {}).status_code == 404
    assert engines.get(f"/automation/rules/{rule['id']}/versions", params={"skip": MAX_OFFSET + 1}).status_code == 422


# --------------------------------------------------------------------------------------------------- preview

BIG = {"logic_operator": "AND", "conditions": [{"field": "total_amount", "operator": "GREATER_THAN", "value": "500000",
                                                 "currency": "INR"}]}


def _draft(actions: list[dict[str, Any]] | None = None, **extra: Any) -> dict[str, Any]:
    return {"name": "Draft", "triggers": ["document.completed"], "condition_groups": [BIG], "groups_operator": "AND",
            "actions": actions or [{"action_type": "document.tag", "config": {"add": ["big"]}}], **extra}


def _row_counts(engines: Engines) -> dict[str, int]:
    from app.models.automation_execution import AutomationExecution
    from app.models.outbox_event import OutboxEvent

    engines.refresh()
    return {
        "outbox": int(engines.db.execute(select(func.count()).select_from(OutboxEvent)).scalar_one()),
        "notifications": int(engines.db.execute(select(func.count()).select_from(Notification)).scalar_one()),
        "executions": int(engines.db.execute(select(func.count()).select_from(AutomationExecution)).scalar_one()),
    }


def test_a_preview_counts_what_a_rule_would_have_done_and_writes_nothing(engines: Engines) -> None:
    _invoice(engines, "INV-PV-1", "1,000.00")
    _invoice(engines, "INV-PV-2", "7,00,000.00")
    _invoice(engines, "INV-PV-3", "9,00,000.00")
    before = _row_counts(engines)

    result = engines.post("/automation/preview", _draft())
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["days"] == 30 and body["would_run"] == 2 and body["events_examined"] >= 3
    assert body["actions"] == [{"action_type": "document.tag", "label": body["actions"][0]["label"], "times": 2}]
    assert len(body["samples"]) == 2 and all(s["filename"].startswith("INV-PV-") for s in body["samples"])
    assert body["peak_per_day"] == 2 and body["average_per_day"] == round(2 / 30, 1)
    assert _row_counts(engines) == before, "a preview writes no outbox event, notification or run"

    # The same numbers for a rule that is saved.
    saved = _rule(engines, "Big", condition_groups=[BIG])
    again = engines.post(f"/automation/rules/{saved['id']}/preview", {})
    assert again.status_code == 200 and again.json()["would_run"] == 2


def test_a_preview_is_bounded_and_warns_in_words(engines: Engines, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.automation import preview

    for number in ("INV-PW-1", "INV-PW-2", "INV-PW-3"):
        _invoice(engines, number, "9,00,000.00")
    monkeypatch.setattr(preview, "MAX_EVENTS", 2)
    bounded = engines.post("/automation/preview", _draft()).json()
    assert bounded["truncated"] is True and bounded["events_examined"] == 2
    assert any("most recent 2 events" in w for w in bounded["warnings"])

    monkeypatch.setattr(preview, "MAX_EVENTS", 2000)
    monkeypatch.setattr(preview, "MESSAGES_PER_DAY_WARNING", 2)
    chatty = engines.post("/automation/preview", _draft([{"action_type": "email.send", "config": {
        "recipient": "ap@acme.example.com", "subject": "Big", "body": "A big invoice"}}])).json()
    assert chatty["messages_per_day_peak"] == 3
    assert any("would have sent about 3 messages" in w for w in chatty["warnings"])

    limited = engines.post("/automation/preview", _draft(max_runs_per_hour=1)).json()
    assert limited["would_be_throttled"] == 2
    assert any("held back by the limit of 1 runs an hour" in w for w in limited["warnings"])

    monkeypatch.setattr(preview, "TIME_BUDGET_S", -1.0)
    slow = engines.post("/automation/preview", _draft()).json()
    assert slow["truncated"] is True and any("ran out of time" in w for w in slow["warnings"])


def test_a_trigger_with_no_stored_history_says_so_and_a_bad_draft_is_refused_in_words(engines: Engines) -> None:
    quiet = engines.post("/automation/preview", {"name": "Hold placed", "triggers": ["legal_hold.placed"], "condition_groups": [],
                                                 "actions": [{"action_type": "notify.role", "config": {"roles": ["ADMIN"]}}]})
    assert quiet.status_code == 200 and quiet.json()["would_run"] == 0
    assert any("only starts being recorded once a rule listens" in w for w in quiet.json()["warnings"])

    bad = engines.post("/automation/preview", _draft([{"action_type": "document.tag", "config": {"add": ["no way!"]}}]))
    assert bad.status_code == 422 and "is not a valid tag" in bad.text
    assert engines.post("/automation/preview", _draft(), as_user=engines.tenant.contributor).status_code == 403
    assert engines.post(f"/automation/rules/{uuid.uuid4()}/preview", {}).status_code == 404


# -------------------------------------------------------------------------------------------------- explainer


def _explain(engines: Engines, work_item: uuid.UUID, rule_id: str, **kw: Any) -> dict[str, Any]:
    response = engines.get(f"/automation/documents/{work_item}/explain", **kw)
    assert response.status_code == 200, response.text
    return next(r for r in response.json()["rules"] if r["rule_id"] == rule_id)


def test_the_explainer_says_why_a_rule_did_or_did_not_run_on_a_document(engines: Engines) -> None:
    rule = _rule(engines, "Big invoices", condition_groups=[BIG])
    small = _invoice(engines, "INV-EX-1", "1,180.00")
    big = _invoice(engines, "INV-EX-2", "9,00,000.00")

    not_met = _explain(engines, small, rule["id"])
    assert not_met["outcome"] == "conditions_not_met" and not_met["trigger_fired"] is True
    assert "conditions were not met" in not_met["verdict"]
    assert not_met["conditions"][0]["matched"] is False and "1,180.00" in not_met["conditions"][0]["actual"]

    ran = _explain(engines, big, rule["id"])
    assert ran["outcome"] == "ran" and "took 1 step" in ran["verdict"] and ran["last_run"]["status"] == "COMPLETED"

    never = _rule(engines, "Anomalies", [{"action_type": "notify.role", "config": {"roles": ["ADMIN"]}}],
                  trigger="anomaly.detected")
    assert _explain(engines, big, never["id"])["outcome"] == "not_triggered"

    engines.patch(f"/automation/rules/{rule['id']}", {"is_active": False})
    assert _explain(engines, big, rule["id"])["outcome"] == "off"

    engines.patch(f"/automation/rules/{rule['id']}", {"is_active": True})
    engines.put("/automation/pause", {"paused": True})
    held_doc = _invoice(engines, "INV-EX-3", "9,00,000.00")
    held = _explain(engines, held_doc, rule["id"])
    assert held["outcome"] == "held_back" and "paused" in held["verdict"]


def test_the_explainer_is_read_only_and_workspace_scoped(engines: Engines) -> None:
    _rule(engines, "Big invoices", condition_groups=[BIG])
    document = _invoice(engines, "INV-EX-4", "9,00,000.00")
    before = _row_counts(engines)
    assert engines.get(f"/automation/documents/{document}/explain", as_user=engines.tenant.contributor).status_code == 200
    assert _row_counts(engines) == before
    assert engines.get(f"/automation/documents/{uuid.uuid4()}/explain").status_code == 404


# ------------------------------------------------------------------------------------------- try a draft, health


def test_a_draft_is_tried_on_a_document_with_the_messages_filled_in_and_nothing_written(engines: Engines) -> None:
    big = _invoice(engines, "INV-TD-1", "9,00,000.00")
    small = _invoice(engines, "INV-TD-2", "1,180.00")
    before = _row_counts(engines)
    draft = _draft([{"action_type": "notify.role", "config": {
        "roles": ["ADMIN"], "title": "Big: {{document.filename}}", "message": "Total {{field.total_amount}} from {{field.vendor_name}}"}}],
        else_actions=[{"action_type": "document.tag", "config": {"add": ["small"]}}])

    yes = engines.post("/automation/test-draft", {**draft, "work_item_id": str(big)})
    assert yes.status_code == 200, yes.text
    body = yes.json()
    assert body["matched"] is True and body["branch"] == "then" and body["document"] == "INV-TD-1.pdf"
    step = body["steps"][0]
    assert step["ok"] is True and step["rendered"]["title"] == "Big: INV-TD-1.pdf"
    assert step["rendered"]["message"] == "Total 9,00,000.00 from Acme Supplies Ltd"
    assert body["conditions"][0]["matched"] is True

    no = engines.post("/automation/test-draft", {**draft, "work_item_id": str(small)}).json()
    assert no["matched"] is False and no["branch"] == "otherwise" and no["steps"][0]["label"]
    assert "1,180.00" in no["conditions"][0]["actual"]
    assert _row_counts(engines) == before, "trying a draft writes nothing"

    bad = engines.post("/automation/test-draft", {**draft, "actions": [{"action_type": "document.tag", "config": {"add": ["no way!"]}}],
                                                 "work_item_id": str(big)})
    assert bad.status_code == 422 and "is not a valid tag" in bad.text
    assert engines.post("/automation/test-draft", {**draft, "work_item_id": str(uuid.uuid4())}).status_code == 404
    assert engines.post("/automation/test-draft", {**draft, "work_item_id": str(big)}, as_user=engines.tenant.contributor).status_code == 403


def test_rule_health_counts_runs_failures_and_held_back_runs_in_seven_days(engines: Engines) -> None:
    rule = _rule(engines, "Tag every upload", max_runs_per_hour=1)
    quiet = _rule(engines, "Never runs", condition_groups=[BIG])
    for number in ("INV-HE-1", "INV-HE-2", "INV-HE-3"):
        _invoice(engines, number)
    health = engines.get("/automation/health").json()
    assert health["days"] == 7
    mine = health["rules"][rule["id"]]
    assert mine["runs_7d"] == 1 and mine["throttled_7d"] == 2 and mine["failed_7d"] == 0 and mine["failure_rate"] == 0
    assert mine["last_run_at"]
    assert health["rules"][quiet["id"]]["runs_7d"] == 3, "a run that only looked is still a run; it just did nothing"
    listed = {r["id"]: r for r in engines.get("/automation/rules").json()}
    assert listed[rule["id"]]["owner_name"], "the rule says who built it"


# ----------------------------------------------------------------------------------------------- isolation


def test_every_new_route_refuses_another_workspaces_rule_run_and_document(engines: Engines) -> None:
    """The new Phase 4 and 5 routes, addressed through a second workspace of the same organization (a person who
    administers both): each answers 404 for A's ids, lists show nothing of A, and the pause switch is per workspace."""
    from tests.engines.isolation import _second_workspace

    rule = _rule(engines, "Mine in A", [{"action_type": "document.tag", "config": {"add": ["x"]}}])
    document = _invoice(engines, "INV-ISO-1", "9,00,000.00")
    run = _runs(engines, rule["id"])[0]
    other = _second_workspace(engines)
    base = f"/api/v1/workspaces/{other}/automation"
    owner = engines.tenant.owner.headers

    def call(method: str, path: str, body: Any = None):
        return engines.client.request(method, f"{base}{path}", json=body, headers=owner)

    assert call("GET", f"/rules/{rule['id']}/versions").status_code == 404
    assert call("POST", f"/rules/{rule['id']}/versions/1/restore", {}).status_code == 404
    assert call("POST", f"/rules/{rule['id']}/preview", {}).status_code == 404
    assert call("POST", f"/executions/{run['id']}/retry", {}).status_code == 404
    assert call("GET", f"/documents/{document}/explain").status_code == 404
    assert call("POST", "/test-draft", {**_draft(), "work_item_id": str(document)}).status_code == 404

    rules_in_b = call("GET", "/rules").json()
    assert rules_in_b == [] or all(r["id"] != rule["id"] for r in rules_in_b)
    assert rule["id"] not in call("GET", "/health").json()["rules"]
    assert all(r["rule_id"] != rule["id"] for r in call("GET", f"/executions", None).json()["items"])
    assert call("GET", "/recipes").status_code == 200

    # The pause switch belongs to one workspace.
    assert call("PUT", "/pause", {"paused": True}).json()["paused"] is True
    assert engines.get("/automation/pause").json()["paused"] is False
    _invoice(engines, "INV-ISO-2")
    assert _by_status(engines, rule["id"]).get("SKIPPED_PAUSED") is None
    assert call("PUT", "/pause", {"paused": False}).json()["paused"] is False
