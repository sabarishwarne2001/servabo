"""The operator's Background jobs console shows the dead-letter queue and can retry it (campaign session 2, brief D).

    pytest tests/engines/test_platform_jobs_console_live.py -q

A job that failed every attempt went DEAD and was visible only as a failed document or a
database row: no page listed what was dead, why, or for whom, and nothing could send a job
round again once its cause was fixed. Platform staff now have /admin/jobs; anyone else gets
404, as on the other platform consoles.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select, text

from app.models.job import Job, JobStatus
from app.services import job_service
from tests.engines.conftest import Engines, drain

SUMMARY = "/api/v1/admin/jobs/summary"
DEAD = "/api/v1/admin/jobs/dead"
SAFETY = "/api/v1/admin/jobs/safety"


def _staff(engines: Engines) -> dict[str, str]:
    engines.tenant.owner.user.is_superuser = True
    engines.db.add(engines.tenant.owner.user)
    engines.db.commit()
    return engines.tenant.owner.headers


def _dead_job(engines: Engines) -> uuid.UUID:
    work_item_id = uuid.uuid4()
    job = job_service.enqueue(engines.db, job_type="test.always_fails", organization_id=engines.org, max_attempts=1,
                              payload={"reason": "supplier API down", "work_item_id": str(work_item_id)},
                              idempotency_key=f"test.always_fails:{uuid.uuid4()}")
    engines.db.commit()
    drain(only=["test.always_fails"], allow_failures=True)
    engines.refresh()
    assert engines.db.get(Job, job.id).status == JobStatus.DEAD
    return job.id


def test_only_platform_staff_can_see_the_jobs_console(engines: Engines) -> None:
    for path in (SUMMARY, DEAD, SAFETY):
        assert engines.client.get(path, headers=engines.tenant.owner.headers).status_code == 404
    assert engines.client.post(f"/api/v1/admin/jobs/{uuid.uuid4()}/retry",
                               headers=engines.tenant.owner.headers).status_code == 404


def test_a_dead_job_is_listed_with_its_reason_and_can_be_retried_once(engines: Engines) -> None:
    job_id = _dead_job(engines)
    headers = _staff(engines)

    summary = engines.client.get(SUMMARY, headers=headers)
    assert summary.status_code == 200, summary.text
    row = next(r for r in summary.json()["by_type"] if r["job_type"] == "test.always_fails")
    assert row["dead"] >= 1 and summary.json()["totals"]["dead"] >= 1

    listed = engines.client.get(DEAD, params={"job_type": "test.always_fails"}, headers=headers)
    assert listed.status_code == 200, listed.text
    item = next(i for i in listed.json()["items"] if i["id"] == str(job_id))
    assert "supplier API down" in item["last_error"]
    assert item["organization_id"] == str(engines.org) and item["organization_name"]
    assert item["work_item_id"]

    retried = engines.client.post(f"/api/v1/admin/jobs/{job_id}/retry", headers=headers)
    assert retried.status_code == 200, retried.text
    engines.refresh()
    job = engines.db.get(Job, job_id)
    assert (job.status, job.attempts, job.claimed_by) == (JobStatus.PENDING, 0, None)

    again = engines.client.post(f"/api/v1/admin/jobs/{job_id}/retry", headers=headers)
    assert again.status_code == 409, again.text
    assert engines.client.post(f"/api/v1/admin/jobs/{uuid.uuid4()}/retry", headers=headers).status_code == 404

    trail = engines.db.execute(text(
        "SELECT count(*) FROM audit_logs WHERE organization_id = :org AND details::text LIKE '%job.retried_from_dead%'"
    ), {"org": str(engines.org)}).scalar_one()
    assert trail == 1, "the organization's audit trail does not show the retry"

    # The retried job really runs again (and, still failing, goes back to the dead-letter queue).
    drain(only=["test.always_fails"], allow_failures=True)
    engines.refresh()
    assert engines.db.execute(select(Job.status).where(Job.id == job_id)).scalar_one() == JobStatus.DEAD


def test_the_safety_jobs_cron_runs_are_listed_and_a_late_one_marks_the_page(engines: Engines) -> None:
    """Final session 2A, Phase 2: the host's safety jobs, as last reported; a job never seen a day after the watching
    started is NEVER_RAN and the answer is degraded (the page turns red)."""
    from datetime import datetime, timedelta, timezone

    from app.models.safety_job_run import SafetyJobRun
    from app.services.ops import safety_jobs

    engines.db.execute(text("DELETE FROM safety_job_runs"))
    safety_jobs.watching_since(engines.db, now=datetime.now(timezone.utc) - timedelta(days=2))
    safety_jobs.record(engines.db, name="compliance", outcome="succeeded")
    engines.db.commit()
    body = engines.client.get(SAFETY, headers=_staff(engines)).json()
    states = {row["name"]: row["state"] for row in body["jobs"]}
    assert body["degraded"] is True and states["compliance"] == "OK" and states["backup"] == "NEVER_RAN"
    assert states["pitr-drill"] == "UNWATCHED" and all(row["run"] for row in body["jobs"])
    engines.db.execute(text("DELETE FROM safety_job_runs"))
    engines.db.commit()
    assert engines.db.execute(select(SafetyJobRun)).first() is None
