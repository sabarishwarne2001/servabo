"""Final session 2A (Phase 4, N-164) — the warning emails sent after a workspace or organization is deleted.

One row per warning: `ARCHIVED` (at once) or `LAST_CHANCE` (5 days before the purge), keyed by what was deleted and when,
so a doubled job never sends one twice and a restore followed by a new deletion is warned again. Written only by
`app/services/compliance/deletion_notices.py`.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, func, text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

DELETION_NOTICE_KINDS: tuple[str, ...] = ("ARCHIVED", "LAST_CHANCE")


class DeletionNoticeSend(Base):
    __tablename__ = "deletion_notice_sends"
    __table_args__ = (
        CheckConstraint("kind IN ('ARCHIVED', 'LAST_CHANCE')", name="ck_deletion_notice_sends_kind"),
        CheckConstraint("scope_type IN ('WORKSPACE', 'ORGANIZATION')", name="ck_deletion_notice_sends_scope"),
        Index("ix_deletion_notice_sends_organization", "organization_id"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    scope_id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), primary_key=True)
    archived_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    scope_type: Mapped[str] = mapped_column(String(16), nullable=False)
    recipients: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


__all__ = ["DELETION_NOTICE_KINDS", "DeletionNoticeSend"]
