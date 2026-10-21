"""Session J — the hourly sweep that announces what TIME has made true: schedules and the two GST clocks.

Two kinds of trigger come from the clock and not from a change somebody made:

  * `schedule.daily` / `schedule.weekly`: 08:00 in the workspace's time zone (Monday for the weekly one). A run at 09:00,
    or after a worker was down, still announces the day once: the mark is the local date.
  * `gst.waiting_for_supplier` / `gst.reversal_risk`: a purchase invoice that has waited N days for its supplier (N is
    the workspace's, 30 by default, set on the GST page), and an unpaid one that reached 150 days of age (a month before
    the 180-day rule). Once per invoice and threshold.

ONE JOB, ONLY WHERE SOMEONE LISTENS. The sweep looks at a workspace only if it has an active rule on one of these
triggers, so it costs nothing for the rest, and a new rule sees today's backlog on the next hour (the marks are written
only when an event is).
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.services.automation import emitters

logger = logging.getLogger("app.services.automation.sweeps")

SCHEDULE_HOUR = 8
#: The GST 180-day rule warns at this age; the limit is `gst.vocabulary.RISK_LIMIT_DAYS`.
REVERSAL_WARNING_DAYS = 150
DEFAULT_WAITING_DAYS = 30
MAX_ROWS_PER_WORKSPACE = 5000


def _now(now: Optional[datetime]) -> datetime:
    return now or datetime.now(timezone.utc)


def _listening_workspaces(db: Session, event_types: tuple[str, ...]) -> list[uuid.UUID]:
    from app.models.automation import AutomationRule
    from app.models.automation_trigger import AutomationRuleTrigger

    return list(db.execute(
        select(AutomationRuleTrigger.workspace_id)
        .join(AutomationRule, AutomationRule.id == AutomationRuleTrigger.rule_id)
        .where(AutomationRuleTrigger.event_type.in_(event_types), AutomationRule.is_active.is_(True),
               AutomationRule.deleted_at.is_(None))
        .distinct().order_by(AutomationRuleTrigger.workspace_id)
    ).scalars())


def _local_today(workspace: Any, now: datetime) -> tuple[date, int]:
    from app.services.automation import evaluator

    ctx = evaluator.EvalContext(timezone=workspace.timezone or "UTC", now=now)
    local = now.astimezone(ctx._zone())  # noqa: SLF001 - the one zone rule the evaluator already owns
    return local.date(), local.hour


def schedules(db: Session, *, now: Optional[datetime] = None) -> int:
    """Announce today to every workspace with a schedule rule whose local time has reached 08:00."""
    from app.models.workspace import Workspace

    now = _now(now)
    announced = 0
    for workspace_id in _listening_workspaces(db, (emitters.SCHEDULE_DAILY, emitters.SCHEDULE_WEEKLY)):
        workspace = db.get(Workspace, workspace_id)
        if workspace is None or workspace.is_sample:
            continue
        today, hour = _local_today(workspace, now)
        if hour < SCHEDULE_HOUR:
            continue
        if emitters.schedule(db, workspace=workspace, weekly=False, local_date=today) is not None:
            announced += 1
        if today.weekday() == 0 and emitters.schedule(db, workspace=workspace, weekly=True, local_date=today) is not None:
            announced += 1
    return announced


def gst_clocks(db: Session, *, now: Optional[datetime] = None) -> dict[str, int]:
    from app.models.gst import GstMatch, GstSettings
    from app.models.work_item import WorkItem
    from app.models.workspace import Workspace
    from app.services.gst import gate, ims
    from app.services.gst import vocabulary as v

    now = _now(now)
    out = {"waiting": 0, "reversal": 0}
    workspaces = _listening_workspaces(db, (emitters.GST_WAITING, emitters.GST_REVERSAL))
    for workspace_id in workspaces:
        workspace = db.get(Workspace, workspace_id)
        if workspace is None or workspace.is_sample or not gate.full_access(db, workspace):
            continue
        today, _hour = _local_today(workspace, now)
        settings = db.get(GstSettings, workspace_id)
        threshold = int(settings.waiting_notice_days) if settings is not None else DEFAULT_WAITING_DAYS
        if emitters.listening(db, workspace_id, emitters.GST_WAITING):
            rows = db.execute(
                select(GstMatch, WorkItem.created_at)
                .join(WorkItem, WorkItem.id == GstMatch.work_item_id)
                .where(GstMatch.workspace_id == workspace_id, GstMatch.status == v.WAITING_FOR_SUPPLIER,
                       GstMatch.work_item_id.is_not(None))
                .order_by(GstMatch.doc_date.asc().nulls_last()).limit(MAX_ROWS_PER_WORKSPACE)
            ).all()
            for row, created_at in rows:
                started = row.doc_date
                entered = created_at.astimezone(timezone.utc).date() if created_at is not None else None
                if entered is not None and (started is None or entered > started):
                    started = entered  # an invoice entered late has not waited since its own date
                if started is None:
                    continue
                days = (today - started).days
                if days >= threshold and emitters.gst_waiting_for_supplier(
                        db, workspace=workspace, row=row, work_item_id=row.work_item_id, days_waiting=days,
                        threshold_days=threshold) is not None:
                    out["waiting"] += 1
        if emitters.listening(db, workspace_id, emitters.GST_REVERSAL):
            rows2 = db.execute(
                select(GstMatch).where(
                    GstMatch.workspace_id == workspace_id, GstMatch.work_item_id.is_not(None),
                    GstMatch.risk.is_not(None), GstMatch.status.not_in((v.NOT_ELIGIBLE, v.REVERSE_CHARGE, v.NOTE)))
                .order_by(GstMatch.doc_date.asc().nulls_last()).limit(MAX_ROWS_PER_WORKSPACE)
            ).scalars().all()
            for row in rows2:
                risk = row.risk or {}
                if risk.get("paid"):
                    continue
                age = ims.age_days(risk, today)
                if age is None or age < REVERSAL_WARNING_DAYS:
                    continue
                reversal = date.fromisoformat(risk["reversal_date"]) if risk.get("reversal_date") else \
                    today + timedelta(days=max(0, v.RISK_LIMIT_DAYS - age))
                if emitters.gst_reversal_risk(
                        db, workspace=workspace, row=row, work_item_id=row.work_item_id, age_days=age,
                        reversal_date=reversal, limit_days=v.RISK_LIMIT_DAYS,
                        warn_at_days=REVERSAL_WARNING_DAYS) is not None:
                    out["reversal"] += 1
    return out


def run(db: Session, *, now: Optional[datetime] = None) -> dict[str, Any]:
    """What the hourly `automation.sweep` job does. The caller commits."""
    result: dict[str, Any] = {}
    for name, step in (("schedules", schedules), ("gst", gst_clocks)):
        try:
            result[name] = step(db, now=now)
        except Exception:  # noqa: BLE001 - one clock failing must not stop the other
            logger.exception("automation.sweep_failed", extra={"step": name})
            result[name] = "failed"
    return result


__all__ = ["gst_clocks", "run", "schedules"]
