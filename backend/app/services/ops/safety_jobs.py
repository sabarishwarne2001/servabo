"""Safety jobs that cannot stop silently (Final session 2A, Phase 2).

The data-retention and erasure sweeps, the ERP retries, the obligation reminders, the backups, the weekly restore drill and
the uptime heartbeat run on the server by cron (`backend/deploy/cron.d/`), outside the app. Before this, if cron stopped,
nothing inside the app noticed, and the host's own watchdog ran from the same cron.

    record(db, name, outcome, detail)   a host wrapper reports a run (started / succeeded / failed)
    statuses(db, now)                   every watched job: its state, last success, last failure, what to run
    check(db, now)                      the hourly `ops.safety_jobs` job: one operator alert a day per stale job
    readiness(db, now)                  "ok" or "degraded" for the readiness answer (never fails readiness)

A job is **stale** when its last success is older than its deadline (each job's own, from its schedule). A job that
**never reported** counts as stale once the app has been watching for a day (`WATCHER` row), so a fresh install is not
alarmed before the first night. Reporting never makes a job fail: the wrappers ignore a failed report.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.operator_alert import OperatorAlert
from app.models.safety_job_run import SafetyJobRun

logger = logging.getLogger("app.services.ops.safety_jobs")

JOB_TYPE = "ops.safety_jobs"
#: The row that remembers when the app started watching (not a job).
WATCHER = "_watcher"
#: "Never ran" waits this long after the watching started.
GRACE_AFTER_START = timedelta(days=1)
DETAIL_LIMIT = 500

OK, STALE, NEVER, WAITING, UNWATCHED = "OK", "STALE", "NEVER_RAN", "WAITING", "UNWATCHED"
OUTCOMES = ("STARTED", "SUCCEEDED", "FAILED")

_RUN = "/srv/servabo/backend/deploy/bin/servabo-sweep"


@dataclass(frozen=True)
class SafetyJob:
    name: str
    label: str
    #: How often cron runs it, in words.
    schedule: str
    #: How old the last success may be before the job is stale (a little over two intervals).
    deadline: timedelta
    #: What to run by hand to catch up, in words a person can paste.
    run: str


# The jobs in backend/deploy/cron.d (servabo-sweepers, servabo-compose-backups, servabo-backups). Deadlines: a daily job
# 26 hours (as the host watchdog), an hourly one 3 hours, a 10- or 15-minute one 1 hour, the weekly drill 8 days, the
# every-minute heartbeat 15 minutes. tests/ops/test_safety_jobs.py proves every cron line is listed here.
SAFETY_JOBS: tuple[SafetyJob, ...] = (
    SafetyJob("arch07", "Retention: export and data clean-up", "daily 03:17", timedelta(hours=26), f"{_RUN} arch07 --all --apply --json"),
    SafetyJob("identity", "Identity clean-up (sessions, tokens)", "daily 03:23", timedelta(hours=26), f"{_RUN} identity --retain-days 30"),
    SafetyJob("invitations", "Invitation emails and expiry", "daily 03:31", timedelta(hours=26), f"{_RUN} invitations --send-delay-ms 250"),
    SafetyJob("arch09", "Retention: chat and memory", "daily 03:41", timedelta(hours=26), f"{_RUN} arch09 --all --apply"),
    SafetyJob("compliance", "Retention, erasure and deleted-workspace purge", "daily 03:53", timedelta(hours=26),
              f"{_RUN} compliance --all --purge --archived --inbound --apply"),
    SafetyJob("extraction_memory", "Extraction memory upkeep", "daily 04:29", timedelta(hours=26), f"{_RUN} extraction_memory --apply"),
    SafetyJob("entities", "Entity graph upkeep", "daily 04:47", timedelta(hours=26), f"{_RUN} entities --apply"),
    SafetyJob("cases", "Case files: expire requests, re-check cases", "daily 05:17", timedelta(hours=26), f"{_RUN} cases --apply"),
    SafetyJob("corroboration", "Document comparisons upkeep", "daily 05:37", timedelta(hours=26), f"{_RUN} corroboration --apply"),
    SafetyJob("obligations", "Obligation due dates and reminders", "hourly", timedelta(hours=3), f"{_RUN} obligations --apply"),
    SafetyJob("erp_postings", "ERP posting retries and acknowledgements", "every 10 minutes", timedelta(hours=1), f"{_RUN} erp_postings --apply"),
    SafetyJob("process", "Process intelligence sweep", "every 15 minutes", timedelta(hours=1), f"{_RUN} process --apply"),
    SafetyJob("revops", "Contracts, invoices and promo upkeep", "daily 03:23", timedelta(hours=26), f"{_RUN} revops --apply"),
    SafetyJob("backup", "Database backup", "daily 02:11", timedelta(hours=26),
              "/srv/servabo/backend/deploy/bin/servabo-compose-backup (or servabo-sweep backup without Docker)"),
    SafetyJob("restore-drill", "Weekly restore drill", "Sundays 04:37", timedelta(days=8),
              "/srv/servabo/backend/deploy/bin/servabo-compose-restore-drill (or servabo-sweep restore-drill --record)"),
    SafetyJob("uptime", "Uptime heartbeat", "every minute", timedelta(minutes=15),
              "/srv/servabo/backend/deploy/bin/servabo-uptime-heartbeat"),
    SafetyJob("dr-heartbeat", "Point-in-time recovery heartbeat", "every minute", timedelta(minutes=15), f"{_RUN} dr-heartbeat"),
    SafetyJob("base-backup", "Point-in-time recovery base backup", "daily 01:41", timedelta(hours=26), f"{_RUN} base-backup"),
    SafetyJob("pitr-drill", "Point-in-time recovery drill", "Saturdays 05:53", timedelta(days=8), f"{_RUN} pitr-drill"),
)
BY_NAME = {job.name: job for job in SAFETY_JOBS}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def unwatched() -> set[str]:
    return {part.strip() for part in (settings.SAFETY_JOBS_UNWATCHED or "").split(",") if part.strip()}


def watched() -> list[SafetyJob]:
    skip = unwatched()
    return [job for job in SAFETY_JOBS if job.name not in skip]


class UnknownSafetyJob(ValueError):
    pass


def record(db: Session, *, name: str, outcome: str, detail: Optional[str] = None,
           now: Optional[datetime] = None) -> SafetyJobRun:
    """Store one report. Flushes. Raises UnknownSafetyJob for a name not in SAFETY_JOBS."""
    if name not in BY_NAME:
        raise UnknownSafetyJob(f"{name!r} is not a safety job")
    outcome = outcome.upper()
    if outcome not in OUTCOMES:
        raise ValueError(f"outcome must be one of {OUTCOMES}")
    moment = now or _now()
    text = (detail or "").strip()[:DETAIL_LIMIT] or None
    row = db.get(SafetyJobRun, name, with_for_update=True)
    if row is None:
        row = SafetyJobRun(name=name, reports=0)
        db.add(row)
    row.reports = int(row.reports or 0) + 1
    row.last_outcome = outcome
    row.updated_at = moment
    if outcome == "STARTED":
        row.last_started_at = moment
    elif outcome == "SUCCEEDED":
        row.last_success_at = moment
        row.last_detail = text
    else:
        row.last_failure_at = moment
        row.last_detail = text
    db.flush()
    return row


def watching_since(db: Session, *, now: Optional[datetime] = None) -> datetime:
    """When the app started watching (the first check); recorded on first call."""
    moment = now or _now()
    db.execute(pg_insert(SafetyJobRun.__table__).values(name=WATCHER, reports=0, created_at=moment, updated_at=moment)
               .on_conflict_do_nothing(index_elements=["name"]))
    return db.execute(select(SafetyJobRun.created_at).where(SafetyJobRun.name == WATCHER)).scalar_one()


def statuses(db: Session, *, now: Optional[datetime] = None) -> list[dict[str, Any]]:
    moment = now or _now()
    rows = {row.name: row for row in db.execute(select(SafetyJobRun)).scalars()}
    started = rows[WATCHER].created_at if WATCHER in rows else moment
    skip = unwatched()
    out = []
    for job in SAFETY_JOBS:
        row = rows.get(job.name)
        last_success = row.last_success_at if row else None
        if job.name in skip:
            state = UNWATCHED
        elif last_success is not None:
            state = OK if moment - last_success <= job.deadline else STALE
        elif moment - started >= GRACE_AFTER_START:
            state = NEVER
        else:
            state = WAITING
        out.append({
            "name": job.name, "label": job.label, "schedule": job.schedule, "state": state,
            "deadline_hours": round(job.deadline.total_seconds() / 3600, 2),
            "last_success_at": last_success, "last_failure_at": row.last_failure_at if row else None,
            "last_started_at": row.last_started_at if row else None,
            "last_outcome": row.last_outcome if row else None, "last_detail": row.last_detail if row else None,
            "run": job.run,
        })
    return out


def readiness(db: Session, *, now: Optional[datetime] = None) -> str:
    """"degraded" when any watched job is stale or never reported (after the first day), else "ok"."""
    return "degraded" if any(s["state"] in (STALE, NEVER) for s in statuses(db, now=now)) else "ok"


def _alert_text(status: dict[str, Any]) -> tuple[str, str]:
    if status["state"] == NEVER:
        subject = f"Safety job never reported: {status['label']} ({status['name']})"
        what = ("has never reported a run since Servabo started watching a day ago. Either cron is not installed or "
                "running on the server, or the job cannot reach the app to report (SAFETY_JOB_REPORT_TOKEN in "
                "/etc/servabo/sweepers.env and .env.production must match).")
    else:
        when = status["last_success_at"].strftime("%Y-%m-%d %H:%M UTC")
        subject = f"Safety job stopped: {status['label']} ({status['name']}) has not succeeded since {when}"
        what = (f"last succeeded at {when}; it should succeed at least every {status['deadline_hours']:g} hours "
                f"({status['schedule']}).")
        if status["last_failure_at"] and status["last_failure_at"] > status["last_success_at"]:
            what += f" Its last run failed: {status['last_detail'] or '(no detail)'}."
    body = (f"{status['label']} ({status['name']}) {what} Check cron on the server (`systemctl status cron`, "
            f"`grep CRON /var/log/syslog`) and the job's log in /srv/servabo/logs, then run it once by hand: "
            f"{status['run']}. Platform admin, Background jobs, shows every safety job. RUNBOOK section 9.6.")
    return subject, body


def _post_webhook(subject: str) -> None:
    url = (settings.ALERT_WEBHOOK or "").strip()
    if not url:
        return
    try:
        import httpx

        httpx.post(url, json={"severity": "page", "summary": subject}, timeout=10)
    except Exception:  # noqa: BLE001 - the email still goes; a webhook outage never stops the check
        logger.warning("ops.safety_jobs_webhook_failed", exc_info=True)


def check(db: Session, *, now: Optional[datetime] = None) -> dict[str, Any]:
    """Alert, at most once a day per job, about every stale or never-reported safety job. Flushes."""
    moment = now or _now()
    watching_since(db, now=moment)
    stale = [s for s in statuses(db, now=moment) if s["state"] in (STALE, NEVER)]
    raised = []
    for status in stale:
        subject, body = _alert_text(status)
        key = f"safety_job:{status['name']}:{moment.date().isoformat()}"
        # One row per job and day, never refreshed: `operator_alert_service.send_due` emails it once.
        result = db.execute(pg_insert(OperatorAlert.__table__).values(
            kind="SAFETY_JOB_STALE", dedupe_key=key, subject=subject[:500], body=body, occurrences=1,
            first_seen_at=moment, last_seen_at=moment,
        ).on_conflict_do_nothing(index_elements=["dedupe_key"]))
        if result.rowcount:
            raised.append(status["name"])
            _post_webhook(subject)
    db.flush()
    if raised:
        logger.warning("ops.safety_jobs_stale", extra={"jobs": raised})
    return {"stale": [s["name"] for s in stale], "alerted": raised}


__all__ = ["BY_NAME", "GRACE_AFTER_START", "JOB_TYPE", "NEVER", "OK", "SAFETY_JOBS", "STALE", "SafetyJob",
           "UNWATCHED", "UnknownSafetyJob", "WAITING", "WATCHER", "check", "readiness", "record", "statuses",
           "unwatched", "watched", "watching_since"]
