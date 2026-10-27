"""`recoveries.sweep` (hourly, LIGHT): bring every entitled workspace's Recoveries up to date (Final session 2A, N-191).

The hourly run (no `workspace_id`) sweeps nothing itself: it queues one `recoveries.sweep` per workspace of an
organization whose plan includes Recoveries, unless that workspace's sweep is still waiting or running (`fan_out`).
One job sweeping every workspace in turn held the worker's queue for minutes, and every document waiting behind it
waited too (CI runs 510 and 511). A payload with `workspace_id` sweeps that workspace with every adapter, the supplier
statements included (`service.sweep(heavy=True)`). Reads the engines' tables; writes only `recovery_issues` and
`recovery_outcomes`.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

logger = logging.getLogger("app.workers.handlers.recoveries")

JOB_TYPE = "recoveries.sweep"


def fan_out(db: Session) -> int:
    """Queue one sweep per entitled, active workspace, skipping one whose sweep is still waiting or running (a slow
    hour never piles sweeps up). Returns the sweeps it queued. Caller commits."""
    from app.models.job import Job, JobStatus
    from app.models.workspace import Workspace, WorkspaceStatus
    from app.services import job_service
    from app.services.recoveries import service
    from app.workers.handlers import ensure_registered

    ensure_registered(JOB_TYPE)
    waiting = {str((payload or {}).get("workspace_id")) for (payload,) in db.execute(select(Job.payload).where(
        Job.job_type == JOB_TYPE, Job.status.in_((JobStatus.PENDING, JobStatus.CLAIMED, JobStatus.FAILED))))}
    targets = db.execute(select(Workspace.id, Workspace.organization_id)
                         .where(Workspace.status == WorkspaceStatus.ACTIVE).order_by(Workspace.id)).all()
    entitled: dict[uuid.UUID, bool] = {}
    covered = 0
    for workspace_id, organization_id in targets:
        if organization_id not in entitled:
            entitled[organization_id] = service.entitled(db, organization_id)
        if not entitled[organization_id] or str(workspace_id) in waiting:
            continue
        job_service.enqueue(db, job_type=JOB_TYPE, payload={"workspace_id": str(workspace_id)},
                            organization_id=organization_id, max_attempts=2)
        covered += 1
    return covered


def _sweep_one(db: Session, workspace_id: uuid.UUID) -> dict[str, Any]:
    from app.models.workspace import Workspace, WorkspaceStatus
    from app.services.recoveries import service

    workspace = db.get(Workspace, workspace_id)
    if workspace is None or workspace.status != WorkspaceStatus.ACTIVE \
            or not service.entitled(db, workspace.organization_id):
        return {"workspaces": 0}  # deleted, or the plan changed, since it was queued
    return {"workspaces": 1, **service.sweep(db, workspace, heavy=True)}


def handle(payload: dict[str, Any]) -> dict[str, Any]:
    from app.db.session import SessionLocal

    with SessionLocal() as db:
        if not payload.get("workspace_id"):
            queued = fan_out(db)
            db.commit()
            return {"outcome": "COMPLETED", "queued": queued}
        result = _sweep_one(db, uuid.UUID(str(payload["workspace_id"])))
        db.commit()
    return {"outcome": "COMPLETED", **result}


__all__ = ["JOB_TYPE", "fan_out", "handle"]
