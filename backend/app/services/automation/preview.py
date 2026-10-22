"""Session J, Phase 4 — "what would this rule have done on the last 30 days?" and "why didn't my rule run?".

Both are READ-ONLY and share the one evaluator the engine runs (`conditions.trace_node_config`), so what a preview or an
explanation says is what the rule would decide.

PREVIEW replays the stored trigger events of the last 30 days (the outbox) through a rule's conditions, and, for the
document triggers whose events are not kept, the documents themselves. It is bounded three ways: the most recent
`MAX_EVENTS` events, `TIME_BUDGET_S` seconds, and a read-only transaction that is rolled back at the end, so a preview
cannot write an outbox row, a notification or a run. It counts; it never acts.

EXPLAIN answers, for one document, what each rule did and why not: did the trigger fire for it, which condition failed
with what value, or was the run held back (paused, throttled, cooldown).
"""

from __future__ import annotations

import time
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, Optional

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models.automation import AutomationRule
from app.models.automation_execution import AutomationExecution, AutomationExecutionStatus
from app.models.outbox_event import OutboxEvent
from app.models.work_item import WorkItem
from app.models.workspace import Workspace
from app.services.automation import actions as action_registry
from app.services.automation import conditions, evaluator, volume
from app.services.automation.triggers import TRIGGER_BY_EVENT

PREVIEW_DAYS = 30
MAX_EVENTS = 2000
TIME_BUDGET_S = 8.0
MAX_SAMPLES = 10
#: A rule that would send more than this many messages in a day gets a warning.
MESSAGES_PER_DAY_WARNING = 50
#: Document triggers whose events are not kept; the preview walks the recent documents instead.
DOCUMENT_REPLAY_TRIGGERS = frozenset({"document.completed", "document.ready", "document.created"})


def rule_conditions_config(rule: Any) -> dict[str, Any]:
    spec = rule.flow_spec if isinstance(getattr(rule, "flow_spec", None), dict) else None
    if spec is not None:
        return {"groups": list(spec.get("condition_groups") or []), "groups_operator": spec.get("groups_operator")}
    return {"conditions": list(rule.conditions or []), "logic_operator": rule.logic_operator}


def draft_rule(normalised: Any, *, max_runs_per_hour: Optional[int] = None) -> Any:
    """A rule that is not saved yet, shaped like the stored one for the evaluator."""
    return SimpleNamespace(
        id=None, name="", flow_spec=normalised.flow_spec, conditions=normalised.conditions,
        logic_operator=normalised.logic_operator, actions=normalised.actions, is_active=True,
        max_runs_per_hour=max_runs_per_hour, cooldown_hours=None, throttle_notified_at=None,
        event_types=list(normalised.event_types), trigger_keys=list(normalised.trigger_keys),
    )


def _planned_actions(rule: Any, matched: bool) -> list[dict[str, Any]]:
    spec = rule.flow_spec if isinstance(getattr(rule, "flow_spec", None), dict) else None
    if matched:
        return [a for a in (rule.actions or []) if isinstance(a, dict)]
    return [a for a in ((spec or {}).get("else_actions") or []) if isinstance(a, dict)]


def _action_info(entry: dict[str, Any]) -> tuple[str, str, bool]:
    definition = action_registry.get(str(entry.get("action_type") or ""))
    if definition is None:
        kind = str(entry.get("action_type") or "an action")
        return kind, kind, True
    return definition.action_type, definition.label, definition.idempotent


def _local_day(moment: datetime, ctx: evaluator.EvalContext) -> str:
    return ctx.local_date(moment).isoformat()


def _read_only(db: Session) -> None:
    """The rest of the transaction cannot write: a stray write raises instead of landing."""
    db.execute(text("SET LOCAL transaction_read_only = on"))


def preview(
    db: Session,
    *,
    rule: Any,
    event_types: list[str],
    workspace_id: uuid.UUID,
    days: int = PREVIEW_DAYS,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    started = time.monotonic()
    moment = now or datetime.now(timezone.utc)
    since = moment - timedelta(days=days)
    _read_only(db)
    workspace = db.get(Workspace, workspace_id)
    ctx = evaluator.EvalContext.for_workspace(workspace) if workspace is not None else evaluator.EvalContext()
    config = rule_conditions_config(rule)

    events = list(
        db.execute(
            select(OutboxEvent)
            .where(
                OutboxEvent.workspace_id == workspace_id,
                OutboxEvent.visibility == "INTERNAL",
                OutboxEvent.event_type.in_(event_types),
                OutboxEvent.created_at >= since,
            )
            .order_by(OutboxEvent.created_at.desc())
            .limit(MAX_EVENTS + 1)
        ).scalars()
    ) if event_types else []
    truncated = len(events) > MAX_EVENTS
    events = events[:MAX_EVENTS]

    occurrences: list[tuple[datetime, Optional[uuid.UUID], str, Optional[dict[str, Any]]]] = [
        (e.created_at, e.resource_id or _uuid(e.payload, "work_item_id"), e.event_type, dict(e.payload or {})) for e in events
    ]
    trigger_keys = list(getattr(rule, "trigger_keys", None) or [])
    covered = {e.event_type for e in events}
    no_history: list[str] = []
    document_replay = False
    for event_type in event_types:
        if event_type in covered:
            continue
        spec = TRIGGER_BY_EVENT.get(event_type)
        if spec is not None and spec.key in DOCUMENT_REPLAY_TRIGGERS:
            document_replay = True
        elif spec is not None:
            no_history.append(spec.label)
    if document_replay and len(occurrences) < MAX_EVENTS:
        remaining = MAX_EVENTS - len(occurrences) + 1
        docs = list(
            db.execute(
                select(WorkItem.id, WorkItem.created_at)
                .where(WorkItem.workspace_id == workspace_id, WorkItem.created_at >= since)
                .order_by(WorkItem.created_at.desc())
                .limit(remaining)
            ).all()
        )
        if len(docs) == remaining:
            truncated = True
            docs = docs[:-1]
        occurrences += [(created, doc_id, "document.replay", None) for doc_id, created in docs]

    matches: list[tuple[datetime, Optional[uuid.UUID], Optional[dict[str, Any]], str]] = []
    examined = 0
    out_of_time = False
    items: dict[uuid.UUID, Any] = {}
    for occurred_at, work_item_id, event_type, payload in occurrences:
        if time.monotonic() - started > TIME_BUDGET_S:
            out_of_time = True
            break
        examined += 1
        work_item = None
        if work_item_id is not None:
            if work_item_id not in items:
                items[work_item_id] = db.execute(
                    select(WorkItem).where(WorkItem.id == work_item_id, WorkItem.workspace_id == workspace_id)
                ).scalar_one_or_none()
            work_item = items[work_item_id]
        matched, _ = conditions.trace_node_config(
            config, work_item=work_item, event_payload=payload,
            event_type=None if event_type == "document.replay" else event_type, context=ctx,
        )
        if matched:
            matches.append((occurred_at, work_item_id, payload, event_type))

    per_day: Counter[str] = Counter(_local_day(m[0], ctx) for m in matches)
    per_hour: Counter[str] = Counter(m[0].astimezone(timezone.utc).strftime("%Y-%m-%d %H") for m in matches)
    planned = _planned_actions(rule, True)
    action_rows: list[dict[str, Any]] = []
    messages_per_run = 0
    for entry in planned:
        kind, label, idempotent = _action_info(entry)
        action_rows.append({"action_type": kind, "label": label, "times": len(matches)})
        if not idempotent:
            messages_per_run += 1

    peak_day = max(per_day.values(), default=0)
    average = round(len(matches) / max(days, 1), 1)
    limit = volume.effective_runs_per_hour(rule)
    throttled = sum(max(0, n - limit) for n in per_hour.values()) if limit else 0
    warnings: list[str] = []
    if messages_per_run and peak_day * messages_per_run > MESSAGES_PER_DAY_WARNING:
        warnings.append(
            f"On its busiest day this rule would have sent about {peak_day * messages_per_run} messages "
            f"({peak_day} runs). Consider a limit or a cooldown so nobody is flooded."
        )
    if throttled:
        warnings.append(f"{throttled} of those runs would have been held back by the limit of {limit} runs an hour.")
    if truncated:
        warnings.append(f"Only the most recent {MAX_EVENTS} events were looked at, so the real numbers may be higher.")
    if out_of_time:
        warnings.append("The preview ran out of time and stopped early. The real numbers may be higher.")
    for label in no_history:
        warnings.append(
            f"“{label}” only starts being recorded once a rule listens to it, so there is no history to replay yet."
        )

    samples = []
    for occurred_at, work_item_id, payload, event_type in matches[:MAX_SAMPLES]:
        item = items.get(work_item_id) if work_item_id else None
        spec = TRIGGER_BY_EVENT.get(event_type)
        samples.append({
            "occurred_at": occurred_at,
            "work_item_id": work_item_id,
            "filename": getattr(item, "original_filename", None),
            "trigger": spec.label if spec else "A recent document",
        })

    db.rollback()  # ends the read-only transaction; nothing was written
    return {
        "days": days,
        "events_examined": examined,
        "truncated": truncated or out_of_time,
        "would_run": len(matches),
        "average_per_day": average,
        "peak_per_day": peak_day,
        "per_day": dict(sorted(per_day.items())),
        "actions": action_rows,
        "messages_per_day_peak": peak_day * messages_per_run,
        "would_be_throttled": throttled,
        "warnings": warnings,
        "samples": samples,
        "no_history": no_history,
        "trigger_keys": trigger_keys,
    }


def _uuid(payload: Any, key: str) -> Optional[uuid.UUID]:
    try:
        return uuid.UUID(str((payload or {}).get(key))) if (payload or {}).get(key) else None
    except ValueError:
        return None


# ------------------------------------------------------------------------------------------------- explainer


def explain_document(db: Session, *, workspace_id: uuid.UUID, work_item: WorkItem) -> list[dict[str, Any]]:
    """For each rule in the workspace: what it did for this document, or the first reason it did not."""
    _read_only(db)
    workspace = db.get(Workspace, workspace_id)
    ctx = evaluator.EvalContext.for_workspace(workspace) if workspace is not None else evaluator.EvalContext()
    rules = list(
        db.execute(
            select(AutomationRule)
            .where(AutomationRule.workspace_id == workspace_id, AutomationRule.deleted_at.is_(None))
            .order_by(AutomationRule.priority.asc(), AutomationRule.created_at.asc())
            .limit(200)
        ).scalars()
    )
    from app.services.automation import rule_triggers

    types_by_rule = rule_triggers.event_types_of(db, rule_ids=[r.id for r in rules])
    events = list(
        db.execute(
            select(OutboxEvent)
            .where(
                OutboxEvent.workspace_id == workspace_id,
                OutboxEvent.visibility == "INTERNAL",
                OutboxEvent.resource_id == work_item.id,
            )
            .order_by(OutboxEvent.created_at.desc())
            .limit(500)
        ).scalars()
    )
    last_event: dict[str, OutboxEvent] = {}
    for event in events:
        last_event.setdefault(event.event_type, event)
    runs: dict[uuid.UUID, AutomationExecution] = {}
    for run in db.execute(
        select(AutomationExecution)
        .where(AutomationExecution.workspace_id == workspace_id, AutomationExecution.work_item_id == work_item.id)
        .order_by(AutomationExecution.created_at.desc())
        .limit(500)
    ).scalars():
        runs.setdefault(run.rule_id, run)

    out: list[dict[str, Any]] = []
    for rule in rules:
        event_types = types_by_rule.get(rule.id, [])
        trigger_labels = [TRIGGER_BY_EVENT[e].label for e in event_types if e in TRIGGER_BY_EVENT]
        entry: dict[str, Any] = {
            "rule_id": rule.id, "rule_name": rule.name, "is_active": rule.is_active, "triggers": trigger_labels,
            "trigger_fired": False, "conditions": [], "conditions_met": None, "last_run": None,
            "verdict": "", "outcome": "",
        }
        run = runs.get(rule.id)
        if run is not None:
            entry["last_run"] = {
                "execution_id": run.id, "status": run.status.value, "at": run.created_at,
                "actions_executed": run.actions_executed, "reason": run.error,
            }
        fired = [last_event[e] for e in event_types if e in last_event]
        document_trigger = any(
            (TRIGGER_BY_EVENT.get(e) is not None and TRIGGER_BY_EVENT[e].key in DOCUMENT_REPLAY_TRIGGERS) for e in event_types
        )
        entry["trigger_fired"] = bool(fired) or (document_trigger and run is not None)
        payload = dict(fired[0].payload or {}) if fired else None
        matched, traced = conditions.trace_node_config(
            rule_conditions_config(rule), work_item=work_item, event_payload=payload,
            event_type=fired[0].event_type if fired else None, context=ctx,
        )
        entry["conditions"] = traced
        entry["conditions_met"] = bool(matched)

        if not rule.is_active:
            entry.update(outcome="off", verdict="This rule is switched off.")
        elif run is not None and run.status.value.startswith("SKIPPED"):
            entry.update(outcome="held_back", verdict=run.error or "The run was held back.")
        elif run is not None and run.actions_executed > 0:
            entry.update(outcome="ran", verdict=f"It ran on this document and took {run.actions_executed} step"
                                                f"{'s' if run.actions_executed != 1 else ''}.")
        elif run is not None and run.status.value in ("FAILED", "TIMED_OUT", "BUDGET_EXHAUSTED"):
            entry.update(outcome="failed", verdict=run.error or "It started, but a step failed.")
        elif not fired and not (document_trigger and run is not None):
            if document_trigger:
                entry.update(outcome="not_triggered", verdict=(
                    "It has not run on this document. If the document was processed before the rule was switched on, "
                    "or while a verification was open, the trigger did not reach this rule."))
            else:
                entry.update(outcome="not_triggered", verdict=(
                    f"Its trigger has not fired for this document ({', '.join(trigger_labels) or 'no trigger'})."))
        elif not matched:
            failed = next((c for c in traced if not c.get("matched")), None)
            why = f" {failed['reason']}" if failed and failed.get("reason") else ""
            entry.update(outcome="conditions_not_met", verdict="Its trigger fired, but the conditions were not met." + why)
        else:
            entry.update(outcome="no_actions", verdict="Its trigger fired and the conditions are met, but no step ran. "
                                                        "Check the rule's steps and Run history.")
        out.append(entry)
    db.rollback()
    return out


# ------------------------------------------------------------------------------------- try a draft on a document


def try_draft(db: Session, *, rule: Any, event_types: list[str], work_item: WorkItem, workspace_id: uuid.UUID) -> dict[str, Any]:
    """Read-only: run a rule that may not be saved yet against one document and say, step by step, what it would do.

    The conditions are decided by the engine's own evaluator (with the document's latest matching event, when there is
    one, for the trigger's own fields); each step names itself and shows the text it would send with the variables filled
    in from this document. Nothing is performed, sent or written."""
    from pydantic import ValidationError

    from app.services.automation.actions import base as action_base
    from app.services.automation.contracts import ActionNodeConfig

    _read_only(db)
    workspace = db.get(Workspace, workspace_id)
    ctx = evaluator.EvalContext.for_workspace(workspace) if workspace is not None else evaluator.EvalContext()
    event = None
    if event_types:
        event = db.execute(
            select(OutboxEvent)
            .where(
                OutboxEvent.workspace_id == workspace_id,
                OutboxEvent.visibility == "INTERNAL",
                OutboxEvent.resource_id == work_item.id,
                OutboxEvent.event_type.in_(event_types),
            )
            .order_by(OutboxEvent.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()
    payload = dict(event.payload or {}) if event is not None else None
    matched, traced = conditions.trace_node_config(
        rule_conditions_config(rule), work_item=work_item, event_payload=payload,
        event_type=event.event_type if event is not None else None, context=ctx,
    )
    spec = rule.flow_spec if isinstance(getattr(rule, "flow_spec", None), dict) else None
    planned = _planned_actions(rule, matched)
    branch = "then" if matched else ("otherwise" if planned else "none")

    state = SimpleNamespace(
        db=db, work_item=work_item, trigger_event=event, rule=SimpleNamespace(name=getattr(rule, "name", "") or "This rule"),
        execution=SimpleNamespace(workspace_id=workspace_id),
    )
    values = action_base.plain_variables_for(state)
    steps: list[dict[str, Any]] = []
    for index, entry in enumerate(planned):
        node = ActionNodeConfig.from_node_config(entry)
        definition = action_registry.get(node.action_type)
        if definition is None:
            steps.append({"index": index + 1, "label": node.action_type, "ok": False, "problem": "This step no longer exists.", "rendered": {}})
            continue
        problem = None
        config: dict[str, Any] = dict(node.authored_parameters())
        try:
            definition.parse(config)
        except ValidationError as exc:
            first = exc.errors()[0] if exc.errors() else {}
            problem = f"{first.get('msg', 'This step is not set up correctly.')}"
        rendered = {
            key: action_base.render(str(config[key]), values)
            for key in definition.template_fields
            if isinstance(config.get(key), str) and config.get(key)
        }
        steps.append({
            "index": index + 1, "label": definition.label, "action_type": definition.action_type, "ok": problem is None,
            "problem": problem, "idempotent": definition.idempotent, "rendered": rendered,
        })
    db.rollback()
    return {
        "matched": bool(matched),
        "branch": branch,
        "conditions": traced,
        "steps": steps,
        "document": getattr(work_item, "original_filename", None),
        "event": {"type": event.event_type, "occurred_at": event.created_at} if event is not None else None,
        "has_otherwise": bool((spec or {}).get("else_actions")),
    }


# ------------------------------------------------------------------------------------------- health of each rule

FAILED_STATUSES = ("FAILED", "TIMED_OUT", "BUDGET_EXHAUSTED")


def rule_health(db: Session, *, workspace_id: uuid.UUID, days: int = 7, now: Optional[datetime] = None) -> dict[str, dict[str, Any]]:
    """Per rule: the last real run, runs in the last 7 days, how many failed, and how many were held back by a limit."""
    from sqlalchemy import case, func

    since = (now or datetime.now(timezone.utc)) - timedelta(days=days)
    skipped = AutomationExecution.status.in_(
        [s for s in AutomationExecutionStatus if s.value.startswith("SKIPPED")]
    )
    failed = AutomationExecution.status.in_([s for s in AutomationExecutionStatus if s.value in FAILED_STATUSES])
    rows = db.execute(
        select(
            AutomationExecution.rule_id,
            func.count().filter(~skipped).label("runs"),
            func.count().filter(failed).label("failed"),
            func.count().filter(AutomationExecution.status == AutomationExecutionStatus.SKIPPED_THROTTLED).label("throttled"),
            func.count().filter(AutomationExecution.status == AutomationExecutionStatus.SKIPPED_PAUSED).label("paused"),
        )
        .where(AutomationExecution.workspace_id == workspace_id, AutomationExecution.created_at >= since)
        .group_by(AutomationExecution.rule_id)
    ).all()
    last = dict(
        db.execute(
            select(AutomationExecution.rule_id, func.max(AutomationExecution.created_at))
            .where(AutomationExecution.workspace_id == workspace_id, ~skipped)
            .group_by(AutomationExecution.rule_id)
        ).all()
    )
    out: dict[str, dict[str, Any]] = {}
    for rule_id, at in last.items():
        out[str(rule_id)] = {"last_run_at": at, "runs_7d": 0, "failed_7d": 0, "throttled_7d": 0, "paused_7d": 0, "failure_rate": 0}
    for rule_id, runs, bad, throttled, paused in rows:
        entry = out.setdefault(str(rule_id), {"last_run_at": None, "runs_7d": 0, "failed_7d": 0, "throttled_7d": 0, "paused_7d": 0, "failure_rate": 0})
        entry.update(runs_7d=int(runs), failed_7d=int(bad), throttled_7d=int(throttled), paused_7d=int(paused),
                     failure_rate=round(100 * int(bad) / int(runs)) if runs else 0)
    return out


__all__ = ["draft_rule", "explain_document", "preview", "rule_conditions_config", "rule_health", "try_draft"]
