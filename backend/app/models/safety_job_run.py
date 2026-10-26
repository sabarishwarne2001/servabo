"""Final session 2A (Phase 2) — what the host's safety jobs last reported.

One row per job (`app/services/ops/safety_jobs.py` names them): when it last started, succeeded and failed, and a short
detail. Written only by the reporting path (`POST /api/v1/ops/safety-jobs/{name}/runs`); read by the hourly check, the
readiness answer, the platform admin's jobs page and `scripts/preflight.py`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import CheckConstraint, DateTime, Integer, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

SAFETY_JOB_OUTCOMES: tuple[str, ...] = ("STARTED", "SUCCEEDED", "FAILED")


class SafetyJobRun(Base):
    __tablename__ = "safety_job_runs"
    __table_args__ = (
        CheckConstraint("last_outcome IS NULL OR last_outcome IN ('STARTED', 'SUCCEEDED', 'FAILED')",
                        name="ck_safety_job_runs_outcome"),
    )

    name: Mapped[str] = mapped_column(String(40), primary_key=True)
    last_started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_success_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_failure_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_outcome: Mapped[Optional[str]] = mapped_column(String(12), nullable=True)
    last_detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reports: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


__all__ = ["SAFETY_JOB_OUTCOMES", "SafetyJobRun"]
