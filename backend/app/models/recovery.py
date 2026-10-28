"""Recoveries (Final session 2A, Phase 6; N-191): the state of a money issue and the outcomes it proved.

`RecoveryIssue` holds only what no engine holds: when the issue was first found, its owner, a due date a person set where
the law and the terms give none, and a person's "Not money: <reason>". The amounts and the evidence are read from the
engines' own tables (`app/services/recoveries/adapters.py`). `RecoveryOutcome` is an outcome proved by evidence, counted
once; it shares Helm's dedupe keys so the two ledgers never count one outcome twice.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Optional

from sqlalchemy import (BigInteger, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, String, Text,
                        UniqueConstraint, func, text)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.services.recoveries import vocabulary as v


def _in(values: tuple[str, ...]) -> str:
    return "(" + ", ".join(f"'{value}'" for value in values) + ")"


class RecoveryIssue(Base):
    __tablename__ = "recovery_issues"
    __table_args__ = (
        UniqueConstraint("workspace_id", "kind", "subject_key", name="uq_recovery_issues_subject"),
        CheckConstraint(f"kind IN {_in(v.KINDS)}", name="ck_recovery_issues_kind"),
        CheckConstraint(f"state IN {_in(v.STATES)}", name="ck_recovery_issues_state"),
        CheckConstraint("currency IS NULL OR currency ~ '^[A-Z]{3}$'", name="ck_recovery_issues_currency"),
        Index("ix_recovery_issues_workspace_state", "workspace_id", "state"),
        Index("ix_recovery_issues_organization", "organization_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    subject_key: Mapped[str] = mapped_column(String(200), nullable=False)
    work_item_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("work_items.id", ondelete="SET NULL"), nullable=True)
    state: Mapped[str] = mapped_column(String(12), nullable=False, server_default=text("'FOUND'"))
    title: Mapped[str] = mapped_column(Text, nullable=False)
    currency: Mapped[Optional[str]] = mapped_column(String(3), nullable=True)
    #: The engine's stored figure now, and when the issue was first found (never estimated).
    exposure_micros: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    found_exposure_micros: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    due_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    due_basis: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    owner_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    assigned_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    close_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    closed_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    first_found_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))


class RecoveryOutcome(Base):
    __tablename__ = "recovery_outcomes"
    __table_args__ = (
        UniqueConstraint("dedupe_key", name="uq_recovery_outcomes_dedupe_key"),
        CheckConstraint(f"category IN {_in(v.CATEGORIES)}", name="ck_recovery_outcomes_category"),
        CheckConstraint("amount_micros > 0", name="ck_recovery_outcomes_positive"),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="ck_recovery_outcomes_currency"),
        Index("ix_recovery_outcomes_workspace_occurred", "workspace_id", "occurred_on"),
        Index("ix_recovery_outcomes_issue", "issue_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    issue_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("recovery_issues.id", ondelete="CASCADE"), nullable=False)
    work_item_id: Mapped[Optional[uuid.UUID]] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    category: Mapped[str] = mapped_column(String(24), nullable=False)
    dedupe_key: Mapped[str] = mapped_column(String(64), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    amount_micros: Mapped[int] = mapped_column(BigInteger, nullable=False)
    occurred_on: Mapped[date] = mapped_column(Date, nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    withdrawn_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


__all__ = ["RecoveryIssue", "RecoveryOutcome"]
