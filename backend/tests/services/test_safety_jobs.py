"""Safety jobs that cannot stop silently (Final session 2A, Phase 2).

The sweeps, the backups, the restore drill and the uptime heartbeat run by cron on the server. Each now reports its runs
into the app; the hourly `ops.safety_jobs` check alerts the operator, once a day per job, when one has not succeeded within
its deadline or has never reported a day after the app started watching; readiness says `safety_jobs: degraded` without
failing; and every line in the cron files is a job the app knows.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import SecretStr
from sqlalchemy import delete, select

from app.core.config import settings
from app.models.operator_alert import OperatorAlert
from app.models.safety_job_run import SafetyJobRun
from app.services.ops import safety_jobs

T0 = datetime(2026, 10, 1, 3, 0, tzinfo=timezone.utc)
TOKEN = "report-token-for-tests-0123456789"
CRON_DIR = Path(__file__).resolve().parents[2] / "deploy" / "cron.d"


@pytest.fixture(autouse=True)
def _clean(db):
    db.execute(delete(SafetyJobRun))
    db.execute(delete(OperatorAlert).where(OperatorAlert.kind == "SAFETY_JOB_STALE"))
    db.flush()
    yield


@pytest.fixture()
def token(monkeypatch):
    monkeypatch.setattr(settings, "SAFETY_JOB_REPORT_TOKEN", SecretStr(TOKEN))
    return TOKEN


def _state(db, name: str, now: datetime) -> str:
    return next(s["state"] for s in safety_jobs.statuses(db, now=now) if s["name"] == name)


def _all_succeed(db, at: datetime) -> None:
    for job in safety_jobs.watched():
        safety_jobs.record(db, name=job.name, outcome="succeeded", now=at)


# ------------------------------------------------------------------------------------------- what cron runs


def _cron_jobs() -> set[str]:
    names: set[str] = set()
    for path in CRON_DIR.iterdir():
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip() or line.lstrip().startswith("#") or "=" in line.split()[0]:
                continue
            if (match := re.search(r"servabo-sweep (\S+)", line)) and "watchdog" not in line:
                names.add(match.group(1))
            elif "servabo-compose-backup" in line:
                names.add("backup")
            elif "servabo-compose-restore-drill" in line:
                names.add("restore-drill")
            elif "servabo-uptime-heartbeat" in line:
                names.add("uptime")
    return names


def test_every_job_cron_runs_is_a_watched_or_switched_off_safety_job() -> None:
    found = _cron_jobs()
    assert found, "no cron lines parsed"
    unknown = found - set(safety_jobs.BY_NAME)
    assert not unknown, f"cron runs jobs the app does not watch: {sorted(unknown)} (add them to SAFETY_JOBS)"
    assert set(safety_jobs.BY_NAME) - found == set(), "SAFETY_JOBS lists a job no cron file runs"


def test_every_wrapper_reports_its_runs() -> None:
    bin_dir = CRON_DIR.parent / "bin"
    for script in ("servabo-sweep", "servabo-compose-backup", "servabo-compose-restore-drill", "servabo-uptime-heartbeat"):
        text = (bin_dir / script).read_text(encoding="utf-8")
        assert "servabo-report-run" in text, f"{script} does not report its runs"


# ------------------------------------------------------------------------------------------- the report path


def test_a_report_needs_the_token(client, db, token) -> None:
    url = "/api/v1/ops/safety-jobs/compliance/runs"
    assert client.post(url, json={"outcome": "succeeded"}).status_code == 401
    assert client.post(url, json={"outcome": "succeeded"}, headers={"X-Servabo-Report-Token": "wrong"}).status_code == 401
    assert client.post("/api/v1/ops/safety-jobs/nope/runs", json={"outcome": "succeeded"},
                       headers={"X-Servabo-Report-Token": token}).status_code == 404
    ok = client.post(url, json={"outcome": "succeeded", "detail": "purged 3 archived workspaces"},
                     headers={"X-Servabo-Report-Token": token})
    assert ok.status_code == 202, ok.text
    db.expire_all()
    row = db.get(SafetyJobRun, "compliance")
    assert row.last_outcome == "SUCCEEDED" and row.last_detail == "purged 3 archived workspaces"


def test_without_a_configured_token_every_report_is_refused(client, monkeypatch) -> None:
    monkeypatch.setattr(settings, "SAFETY_JOB_REPORT_TOKEN", None)
    response = client.post("/api/v1/ops/safety-jobs/compliance/runs", json={"outcome": "succeeded"},
                           headers={"X-Servabo-Report-Token": ""})
    assert response.status_code == 401


def test_the_report_route_is_not_in_the_public_schema(client) -> None:
    assert "/api/v1/ops/safety-jobs/{name}/runs" not in client.get("/api/v1/openapi.json").json()["paths"]


# ------------------------------------------------------------------------------------------- stale and never ran


def test_a_job_past_its_deadline_is_stale(db) -> None:
    safety_jobs.watching_since(db, now=T0)
    safety_jobs.record(db, name="compliance", outcome="succeeded", now=T0)
    safety_jobs.record(db, name="erp_postings", outcome="succeeded", now=T0)
    assert _state(db, "compliance", T0 + timedelta(hours=25)) == safety_jobs.OK
    assert _state(db, "compliance", T0 + timedelta(hours=27)) == safety_jobs.STALE
    # Each job has its own deadline: the 10-minute ERP sweep is stale after an hour.
    assert _state(db, "erp_postings", T0 + timedelta(minutes=50)) == safety_jobs.OK
    assert _state(db, "erp_postings", T0 + timedelta(minutes=70)) == safety_jobs.STALE


def test_a_failure_after_the_last_success_does_not_hide_staleness(db) -> None:
    safety_jobs.watching_since(db, now=T0)
    safety_jobs.record(db, name="backup", outcome="succeeded", now=T0)
    safety_jobs.record(db, name="backup", outcome="started", now=T0 + timedelta(hours=24))
    safety_jobs.record(db, name="backup", outcome="failed", detail="disk full", now=T0 + timedelta(hours=24))
    assert _state(db, "backup", T0 + timedelta(hours=27)) == safety_jobs.STALE
    subject, body = safety_jobs._alert_text(next(s for s in safety_jobs.statuses(db, now=T0 + timedelta(hours=27))
                                                 if s["name"] == "backup"))
    assert "has not succeeded since" in subject and "disk full" in body


def test_never_ran_counts_only_after_a_day_of_watching(db) -> None:
    safety_jobs.watching_since(db, now=T0)
    assert _state(db, "compliance", T0 + timedelta(hours=23)) == safety_jobs.WAITING
    assert _state(db, "compliance", T0 + timedelta(hours=25)) == safety_jobs.NEVER


def test_switched_off_jobs_are_not_watched(db, monkeypatch) -> None:
    safety_jobs.watching_since(db, now=T0)
    assert _state(db, "pitr-drill", T0 + timedelta(days=3)) == safety_jobs.UNWATCHED
    monkeypatch.setattr(settings, "SAFETY_JOBS_UNWATCHED", "")
    assert _state(db, "pitr-drill", T0 + timedelta(days=3)) == safety_jobs.NEVER


# ------------------------------------------------------------------------------------------- one alert a day


def _alerts(db) -> list[OperatorAlert]:
    return list(db.execute(select(OperatorAlert).where(OperatorAlert.kind == "SAFETY_JOB_STALE")).scalars())


def test_a_stale_job_is_one_alert_a_day_and_the_webhook_hears_it_once(db, monkeypatch) -> None:
    posted = []
    monkeypatch.setattr(settings, "ALERT_WEBHOOK", "https://hc-ping.example/abc/fail")
    import json

    from app.core import ssrf_client

    monkeypatch.setattr(ssrf_client.SSRFSafeHTTPClient, "request",
                        lambda self, method, url, headers=None, body=b"": posted.append((url, json.loads(body))))
    safety_jobs.watching_since(db, now=T0)
    _all_succeed(db, T0)
    safety_jobs.record(db, name="compliance", outcome="succeeded", now=T0 + timedelta(hours=1))
    later = T0 + timedelta(hours=28)
    for jobs in safety_jobs.watched():
        if jobs.name != "compliance":
            safety_jobs.record(db, name=jobs.name, outcome="succeeded", now=later)
    first = safety_jobs.check(db, now=later)
    again = safety_jobs.check(db, now=later + timedelta(minutes=10))  # within the 15-minute heartbeat's deadline
    assert first["alerted"] == ["compliance"] and again["alerted"] == []
    assert len(_alerts(db)) == 1 and len(posted) == 1
    assert "compliance" in posted[0][1]["summary"]
    next_day = safety_jobs.check(db, now=later + timedelta(days=1))
    assert "compliance" in next_day["alerted"] and len(_alerts(db)) >= 2


def test_the_alert_is_emailed_once(db, monkeypatch) -> None:
    from app.services import operator_alert_service

    sent = []
    monkeypatch.setattr(settings, "OPERATOR_ALERT_EMAILS", "owner@example.com")
    monkeypatch.setattr(operator_alert_service, "_send", lambda **kw: sent.append(kw["subject"]) or True)
    safety_jobs.watching_since(db, now=T0)
    moment = T0 + timedelta(hours=30)
    safety_jobs.check(db, now=moment)
    operator_alert_service.send_due(db, now=moment)
    safety_jobs.check(db, now=moment + timedelta(hours=1))
    operator_alert_service.send_due(db, now=moment + timedelta(hours=2))
    stale_mail = [s for s in sent if "Safety job" in s]
    assert stale_mail and len(stale_mail) == len({s for s in stale_mail}), "each stale job is emailed once that day"


# ------------------------------------------------------------------------------------------- scheduling (readiness: tests/api/test_safety_jobs_readiness.py)


def test_the_check_is_scheduled_hourly_and_claimed_by_a_worker() -> None:
    from app.workers.profiles import PROFILES
    from app.workers.scheduler import DEFAULT_SCHEDULE

    entry = next(e for e in DEFAULT_SCHEDULE if e.job_type == safety_jobs.JOB_TYPE)
    assert entry.interval_seconds == 3_600
    assert any(p.job_types and safety_jobs.JOB_TYPE in p.job_types for p in PROFILES.values())

