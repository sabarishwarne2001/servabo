"""Email-in (Final session 1, 2B): the address a workspace receives documents at, who may send to it, what arrived, and where a
document came from. Migration `k1a3_inbound_email`.

* `inbound_email_addresses` — a long random token per workspace (never the workspace's name or slug), rotatable. A rotated
  token is kept, retired, so mail still addressed to it is refused (403) and Postmark stops retrying.
* `inbound_email_senders` — the senders or domains whose mail is accepted directly. Everyone else's is held.
* `inbound_messages` — one row per message Postmark delivered (idempotent on its MessageID): accepted, held for an admin, or
  discarded. Held messages keep their attachments in object storage until approved or discarded.
* `work_item_sources` — "Arrived by email from ...", shown on the document.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, Index, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

MESSAGE_STATUSES: tuple[str, ...] = ("ACCEPTED", "HELD", "DISCARDED")
SOURCE_KINDS: tuple[str, ...] = ("EMAIL",)


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))


def _org() -> Mapped[uuid.UUID]:
    return mapped_column(PgUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)


def _user() -> Mapped[Optional[uuid.UUID]]:
    return mapped_column(PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


def _ts() -> Mapped[Any]:
    return mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


def _workspace_fk(table: str) -> ForeignKeyConstraint:
    return ForeignKeyConstraint(
        ["workspace_id", "organization_id"], ["workspaces.id", "workspaces.organization_id"],
        name=f"fk_{table}_workspace_org", ondelete="CASCADE",
    )


class InboundEmailAddress(Base):
    __tablename__ = "inbound_email_addresses"
    __table_args__ = (
        _workspace_fk("inbound_email_addresses"),
        UniqueConstraint("token", name="uq_inbound_email_addresses_token"),
        Index("uq_inbound_email_addresses_active", "workspace_id", unique=True, postgresql_where=text("retired_at IS NULL")),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    organization_id: Mapped[uuid.UUID] = _org()
    workspace_id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    token: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by_user_id: Mapped[Optional[uuid.UUID]] = _user()
    created_at: Mapped[datetime] = _ts()
    retired_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class InboundEmailSender(Base):
    __tablename__ = "inbound_email_senders"
    __table_args__ = (
        _workspace_fk("inbound_email_senders"),
        UniqueConstraint("workspace_id", "pattern", name="uq_inbound_email_senders_pattern"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    organization_id: Mapped[uuid.UUID] = _org()
    workspace_id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    #: A lower-case address ("ap@supplier.in") or a domain ("supplier.in").
    pattern: Mapped[str] = mapped_column(String(255), nullable=False)
    created_by_user_id: Mapped[Optional[uuid.UUID]] = _user()
    created_at: Mapped[datetime] = _ts()


class InboundMessage(Base):
    __tablename__ = "inbound_messages"
    __table_args__ = (
        _workspace_fk("inbound_messages"),
        UniqueConstraint("workspace_id", "message_id", name="uq_inbound_messages_message"),
        CheckConstraint("status IN ('ACCEPTED', 'HELD', 'DISCARDED')", name="ck_inbound_messages_status"),
        CheckConstraint("jsonb_typeof(attachments) = 'array'", name="ck_inbound_messages_attachments_list"),
        CheckConstraint("jsonb_typeof(work_item_ids) = 'array'", name="ck_inbound_messages_work_items_list"),
        Index("ix_inbound_messages_workspace_received", "workspace_id", "received_at"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    organization_id: Mapped[uuid.UUID] = _org()
    workspace_id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    #: Postmark's MessageID: a second delivery of the same message is answered 200 and changes nothing.
    message_id: Mapped[str] = mapped_column(String(200), nullable=False)
    from_address: Mapped[str] = mapped_column(String(320), nullable=False)
    from_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    subject: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    received_at: Mapped[datetime] = _ts()
    status: Mapped[str] = mapped_column(String(12), nullable=False)
    #: Why a held message waits: SENDER_NOT_ALLOWED, NO_ATTACHMENT, GSTR2B_ONLY, OVER_LIMIT, TRIAL_ENDED.
    hold_code: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    hold_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    #: [{name, content_type, size, outcome, note?, work_item_id?, batch_id?, storage_key?}] — no attachment bytes.
    attachments: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    #: The documents this message added (a zip's are counted by its batch), so erasing them reaches this row.
    work_item_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    decided_by_user_id: Mapped[Optional[uuid.UUID]] = _user()
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = _ts()


class WorkItemSource(Base):
    """Where a document came from, beyond "someone uploaded it". One row per document that arrived by email."""

    __tablename__ = "work_item_sources"
    __table_args__ = (
        ForeignKeyConstraint(
            ["work_item_id", "workspace_id"], ["work_items.id", "work_items.workspace_id"],
            name="fk_work_item_sources_work_item", ondelete="CASCADE",
        ),
        _workspace_fk("work_item_sources"),
        CheckConstraint("kind IN ('EMAIL')", name="ck_work_item_sources_kind"),
    )

    work_item_id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[uuid.UUID] = _org()
    workspace_id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    sender: Mapped[Optional[str]] = mapped_column(String(320), nullable=True)
    subject: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    received_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    inbound_message_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("inbound_messages.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = _ts()


__all__ = ["InboundEmailAddress", "InboundEmailSender", "InboundMessage", "MESSAGE_STATUSES", "SOURCE_KINDS", "WorkItemSource"]
