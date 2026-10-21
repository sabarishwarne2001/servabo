"""Session J, Phase 4 — a rule that stays safe when a thousand documents arrive at once.

Three things hold a run back before any step runs, and each one leaves a visible row in Run history
(`SKIPPED_THROTTLED`, `SKIPPED_COOLDOWN`, `SKIPPED_PAUSED`) so nothing is ever dropped silently:

* the workspace's PAUSE switch (a workspace admin, audited);
* the rule's THROTTLE, "at most N runs per hour" (a rule that sets none gets `AUTOMATION_DEFAULT_RUNS_PER_HOUR`);
* the rule's COOLDOWN, "at most once per document every X hours" (off unless set).

Only runs that DID something count toward a throttle or a cooldown: a run that took at least one action, or one that is
still in flight. A rule whose conditions rarely match is not throttled by the events it looked at and ignored.

A manual run (a person pressed "Run on this document") and a retry skip the throttle and the cooldown, because a person
asked for exactly that run, but not the pause: when a workspace admin has paused automations, nothing runs.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.automation_execution import (
    SKIPPED_STATUSES,
    SUPPRESSED_STATUSES,
    AutomationExecution,
    AutomationExecutionStatus,
)

THROTTLE_NOTICE_INTERVAL = timedelta(days=1)

#: A run that counts toward the throttle and the cooldown: it took an action, or it is still going.
_IN_FLIGHT = (AutomationExecutionStatus.QUEUED, AutomationExecutionStatus.RUNNING)


@dataclass(frozen=True)
class Hold:
    """A reason this run was held back, in words a person reads in Run history."""

    status: AutomationExecutionStatus
    reason: str
    details: dict[str, Any] = field(default_factory=dict)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def effective_runs_per_hour(rule: Any) -> int:
    """The rule's own limit, else the workspace default. 0 means no limit (the default switched off)."""
    own = getattr(rule, "max_runs_per_hour", None)
    if own:
        return int(own)
    return max(0, int(settings.AUTOMATION_DEFAULT_RUNS_PER_HOUR))


def is_paused(workspace: Any) -> bool:
    return workspace is not None and getattr(workspace, "automations_paused_at", None) is not None


def _counts_as_a_run():
    return (AutomationExecution.actions_executed > 0) | AutomationExecution.status.in_(_IN_FLIGHT)


def runs_in_last_hour(db: Session, *, rule_id: uuid.UUID, now: Optional[datetime] = None) -> int:
    since = (now or _now()) - timedelta(hours=1)
    return int(
        db.execute(
            select(func.count())
            .select_from(AutomationExecution)
            .where(
                AutomationExecution.rule_id == rule_id,
                AutomationExecution.created_at >= since,
                _counts_as_a_run(),
            )
        ).scalar_one()
    )


def last_run_for_document(
    db: Session, *, rule_id: uuid.UUID, work_item_id: uuid.UUID, within_hours: int, now: Optional[datetime] = None
) -> Optional[datetime]:
    since = (now or _now()) - timedelta(hours=within_hours)
    return db.execute(
        select(func.max(AutomationExecution.created_at)).where(
            AutomationExecution.rule_id == rule_id,
            AutomationExecution.work_item_id == work_item_id,
            AutomationExecution.created_at >= since,
            _counts_as_a_run(),
        )
    ).scalar_one()


def _ago(then: datetime, now: datetime) -> str:
    minutes = max(0, int((now - then).total_seconds() // 60))
    if minutes < 1:
        return "less than a minute ago"
    if minutes < 90:
        return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    hours = round(minutes / 60)
    return f"{hours} hours ago"


def gate(
    db: Session,
    *,
    rule: Any,
    workspace: Any,
    work_item_id: Optional[uuid.UUID],
    manual: bool = False,
    now: Optional[datetime] = None,
) -> Optional[Hold]:
    """None when the run may go ahead, else the `Hold` that stops it. Pause first, then throttle, then cooldown."""
    moment = now or _now()
    if is_paused(workspace):
        return Hold(
            AutomationExecutionStatus.SKIPPED_PAUSED,
            "This workspace's automations are paused, so this rule did not run. "
            "A workspace admin can resume them from the Automation page.",
            {"paused_at": workspace.automations_paused_at.isoformat()},
        )
    if manual:
        return None

    # One rule is counted by one worker at a time, so two parallel workers cannot both squeeze in under the limit.
    # The lock is released by the caller's commit, which writes the execution row that the next count will see.
    db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": f"automation.volume:{rule.id}"})

    limit = effective_runs_per_hour(rule)
    if limit:
        used = runs_in_last_hour(db, rule_id=rule.id, now=moment)
        if used >= limit:
            return Hold(
                AutomationExecutionStatus.SKIPPED_THROTTLED,
                f"This rule has already run {used} times in the last hour, which is its limit of {limit} an hour, "
                "so this run was held back. Raise the limit on the rule if that is too low.",
                {"limit_per_hour": limit, "runs_in_last_hour": used},
            )

    cooldown = getattr(rule, "cooldown_hours", None)
    if cooldown and work_item_id is not None:
        last = last_run_for_document(
            db, rule_id=rule.id, work_item_id=work_item_id, within_hours=int(cooldown), now=moment
        )
        if last is not None:
            return Hold(
                AutomationExecutionStatus.SKIPPED_COOLDOWN,
                f"This rule already ran for this document {_ago(last, moment)}, and it is set to run at most once "
                f"per document every {int(cooldown)} hour{'s' if int(cooldown) != 1 else ''}, so it was not run again.",
                {"cooldown_hours": int(cooldown), "last_run_at": last.isoformat()},
            )
    return None


def should_notify_throttled(rule: Any, *, now: Optional[datetime] = None) -> bool:
    last = getattr(rule, "throttle_notified_at", None)
    return last is None or (now or _now()) - last >= THROTTLE_NOTICE_INTERVAL


def root_execution_id(db: Session, execution: AutomationExecution) -> uuid.UUID:
    """The first run of a chain of retries. A webhook's idempotency key is built on it, so a retry repeats the key."""
    current = execution
    for _ in range(25):
        if current.retry_of_id is None:
            return current.id
        parent = db.get(AutomationExecution, current.retry_of_id)
        if parent is None:
            return current.retry_of_id
        current = parent
    return current.id


# ------------------------------------------------------------------------------------------------------- retry

#: Failures worth trying again: the run broke part way (a webhook endpoint was down, the model timed out) rather than
#: being refused on purpose.
RETRYABLE_STATUSES = (
    AutomationExecutionStatus.FAILED,
    AutomationExecutionStatus.TIMED_OUT,
    AutomationExecutionStatus.BUDGET_EXHAUSTED,
)

def retry_blocker(db: Session, execution: AutomationExecution, rule: Any) -> Optional[str]:
    """Why this run cannot be retried, in words; None when it can."""
    if execution.status not in RETRYABLE_STATUSES:
        return "Only a run that failed, timed out or ran out of budget can be retried."
    if rule is None or getattr(rule, "deleted_at", None) is not None:
        return "The rule this run belonged to has been deleted."
    child = db.execute(
        select(AutomationExecution.id, AutomationExecution.status)
        .where(AutomationExecution.retry_of_id == execution.id)
        .order_by(AutomationExecution.created_at.desc())
        .limit(1)
    ).first()
    if child is not None and child.status not in (
        AutomationExecutionStatus.FAILED,
        AutomationExecutionStatus.TIMED_OUT,
        AutomationExecutionStatus.BUDGET_EXHAUSTED,
    ):
        return "This run has already been retried."
    return None


def repeatable_actions(rule: Any) -> list[str]:
    """The labels of the rule's actions that would do something noticeable twice (an email, a chat post)."""
    from app.services.automation import actions as registry

    labels: list[str] = []
    specs = list(getattr(rule, "actions", None) or [])
    spec = rule.flow_spec if isinstance(getattr(rule, "flow_spec", None), dict) else {}
    specs += list(spec.get("else_actions") or [])
    for entry in specs:
        definition = registry.get(str(entry.get("action_type") or "")) if isinstance(entry, dict) else None
        if definition is not None and not definition.idempotent and definition.label not in labels:
            labels.append(definition.label)
    return labels


def is_skipped_status(status: AutomationExecutionStatus) -> bool:
    return status in SKIPPED_STATUSES


__all__ = [
    "Hold",
    "RETRYABLE_STATUSES",
    "SUPPRESSED_STATUSES",
    "effective_runs_per_hour",
    "gate",
    "is_paused",
    "is_skipped_status",
    "last_run_for_document",
    "repeatable_actions",
    "retry_blocker",
    "root_execution_id",
    "runs_in_last_hour",
    "should_notify_throttled",
]
