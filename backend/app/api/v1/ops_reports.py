"""Final session 2A (Phase 2) — the host's safety jobs report their runs here.

    POST /api/v1/ops/safety-jobs/{name}/runs   {"outcome": "started"|"succeeded"|"failed", "detail": "..."}

Called by the cron wrappers on the server (`deploy/bin/servabo-report-run`, from `servabo-sweep`, the backup, the restore
drill and the uptime heartbeat) through the public address, because the `/api/v1/internal/*` namespace is not published by
Caddy and the API container's port is not published on the host. Authenticated by the shared secret
`SAFETY_JOB_REPORT_TOKEN` in the `X-Servabo-Report-Token` header (compared in constant time); no user, no organization.
Hidden from the OpenAPI schema like the other machine-to-machine webhooks. A report holds a job name, an outcome and a
short detail; it can only say that a job ran, and a forged success could at worst hide a stopped job, which is why the
secret lives only in root-readable files (`.env.production`, `/etc/servabo/sweepers.env`).
"""

from __future__ import annotations

import hmac
import logging
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.config import settings
from app.services.ops import safety_jobs

logger = logging.getLogger("app.api.ops_reports")

router = APIRouter(tags=["Operations (host jobs)"])


class RunReport(BaseModel):
    outcome: Literal["started", "succeeded", "failed"]
    detail: Optional[str] = Field(default=None, max_length=2000)


def _authorized(token: Optional[str]) -> bool:
    expected = settings.SAFETY_JOB_REPORT_TOKEN.get_secret_value() if settings.SAFETY_JOB_REPORT_TOKEN else ""
    return bool(expected) and bool(token) and hmac.compare_digest(token.encode("utf-8"), expected.encode("utf-8"))


@router.post("/ops/safety-jobs/{name}/runs", status_code=status.HTTP_202_ACCEPTED, include_in_schema=False)
def report_run(name: str, body: RunReport, db: Session = Depends(get_db),
               x_servabo_report_token: Optional[str] = Header(default=None)) -> dict[str, str]:
    if not _authorized(x_servabo_report_token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authorized.")
    try:
        safety_jobs.record(db, name=name, outcome=body.outcome, detail=body.detail)
    except safety_jobs.UnknownSafetyJob as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such safety job.") from exc
    db.commit()
    logger.info("ops.safety_job_reported", extra={"job": name, "outcome": body.outcome})
    return {"recorded": name}


__all__ = ["router"]
