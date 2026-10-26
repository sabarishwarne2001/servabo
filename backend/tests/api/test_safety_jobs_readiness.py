"""Final session 2A, Phase 2: readiness says `safety_jobs: degraded` when a host safety job is stale, and stays 200.

A stopped sweep must not take the app out of the load balancer; it is reported, not enforced. When every job is fine the
answer is the plain `{"status": "ready"}` it always was (tests/api/test_health_readiness.py, F-042).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import delete

from app.models.safety_job_run import SafetyJobRun
from app.services.ops import safety_jobs


def _fresh(db) -> None:
    db.execute(delete(SafetyJobRun))
    db.commit()


def test_readiness_stays_up_and_says_degraded(client, db_session) -> None:
    _fresh(db_session)
    safety_jobs.watching_since(db_session, now=datetime.now(timezone.utc) - timedelta(days=2))
    db_session.commit()
    response = client.get("/api/v1/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready", "safety_jobs": "degraded"}


def test_readiness_is_plain_when_every_job_succeeded_in_time(client, db_session) -> None:
    _fresh(db_session)
    now = datetime.now(timezone.utc)
    safety_jobs.watching_since(db_session, now=now - timedelta(days=2))
    for job in safety_jobs.watched():
        safety_jobs.record(db_session, name=job.name, outcome="succeeded", now=now - timedelta(minutes=1))
    db_session.commit()
    response = client.get("/api/v1/health/ready")
    assert response.status_code == 200 and response.json() == {"status": "ready"}
