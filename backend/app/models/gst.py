"""GST Credit: the ORM mapping of migration `g1a1_gst_credit` (docs/product/GST-CREDIT.md).

`gst_returns` are imported GSTR-2B statements, `gst_return_records` their supplier documents, `gst_matches` the
engine's reconciliation (rebuilt, never hand-edited), `gst_decisions` what a person decided (keyed by the
document's natural key so a re-import keeps it). Money is in micros. Every row carries `organization_id` and
`workspace_id` with the ARCH-41 composite keys.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.services.gst import vocabulary as v


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
                         server_default=text("gen_random_uuid()"))


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


def _work_item_fk(table: str) -> ForeignKeyConstraint:
    return ForeignKeyConstraint(
        ["work_item_id", "workspace_id"], ["work_items.id", "work_items.workspace_id"],
        name=f"fk_{table}_work_item", ondelete="CASCADE",
    )


class GstReturn(Base):
    """One imported GSTR-2B."""

    __tablename__ = "gst_returns"
    __table_args__ = (
        _workspace_fk("gst_returns"),
        UniqueConstraint("id", "workspace_id", name="uq_gst_returns_id_workspace"),
        CheckConstraint("status IN ('ACTIVE', 'SUPERSEDED')", name="ck_gst_returns_status"),
        CheckConstraint("record_count >= 0", name="ck_gst_returns_count"),
        Index("uq_gst_returns_active", "workspace_id", "gstin", "period", unique=True,
              postgresql_where=text("status = 'ACTIVE'")),
        Index("ix_gst_returns_workspace_gstin", "workspace_id", "gstin"),
        Index("ix_gst_returns_organization", "organization_id"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    organization_id: Mapped[uuid.UUID] = _org()
    workspace_id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    gstin: Mapped[str] = mapped_column(String(15), nullable=False)
    #: "YYYY-MM"
    period: Mapped[str] = mapped_column(String(7), nullable=False)
    rtnprd: Mapped[str] = mapped_column(String(6), nullable=False)
    version: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    generated_on: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    file_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    record_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    itc_summary: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    problems: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    status: Mapped[str] = mapped_column(String(10), nullable=False, server_default=text("'ACTIVE'"))
    supersedes_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("gst_returns.id", ondelete="SET NULL"), nullable=True)
    imported_by_user_id: Mapped[Optional[uuid.UUID]] = _user()
    imported_at: Mapped[datetime] = _ts()
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = _ts()


class GstReturnRecord(Base):
    """One supplier document in a return."""

    __tablename__ = "gst_return_records"
    __table_args__ = (
        _workspace_fk("gst_return_records"),
        ForeignKeyConstraint(["return_id", "workspace_id"], ["gst_returns.id", "gst_returns.workspace_id"],
                             name="fk_gst_return_records_return", ondelete="CASCADE"),
        UniqueConstraint("id", "workspace_id", name="uq_gst_return_records_id_workspace"),
        CheckConstraint(f"section IN ({_in(v.SECTIONS)})", name="ck_gst_return_records_section"),
        CheckConstraint(f"kind IN ({_in(v.KINDS)})", name="ck_gst_return_records_kind"),
        Index("ix_gst_return_records_return", "return_id"),
        Index("ix_gst_return_records_lookup", "workspace_id", "gstin", "supplier_gstin", "doc_key"),
        Index("ix_gst_return_records_irn", "workspace_id", "irn", postgresql_where=text("irn IS NOT NULL")),
        Index("ix_gst_return_records_organization", "organization_id"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    organization_id: Mapped[uuid.UUID] = _org()
    workspace_id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    return_id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    gstin: Mapped[str] = mapped_column(String(15), nullable=False)
    period: Mapped[str] = mapped_column(String(7), nullable=False)
    section: Mapped[str] = mapped_column(String(8), nullable=False)
    kind: Mapped[str] = mapped_column(String(12), nullable=False)
    supplier_gstin: Mapped[Optional[str]] = mapped_column(String(15), nullable=True)
    supplier_name: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    supplier_filed_on: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    supplier_period: Mapped[Optional[str]] = mapped_column(String(12), nullable=True)
    doc_number: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    doc_key: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    doc_type: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    doc_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    value_micros: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    taxable_micros: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    igst_micros: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    cgst_micros: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    sgst_micros: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    cess_micros: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    place_of_supply: Mapped[Optional[str]] = mapped_column(String(2), nullable=True)
    reverse_charge: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    itc_available: Mapped[Optional[str]] = mapped_column(String(1), nullable=True)
    reason: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    diff_percent: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    source_type: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    irn: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    irn_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    original_number: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    original_key: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    original_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    raw: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = _ts()

    @property
    def tax_micros(self) -> int:
        return self.igst_micros + self.cgst_micros + self.sgst_micros + self.cess_micros


class GstMatch(Base):
    """The reconciliation of one supplier record and/or one book document. Rebuilt by the engine."""

    __tablename__ = "gst_matches"
    __table_args__ = (
        _workspace_fk("gst_matches"),
        ForeignKeyConstraint(["record_id", "workspace_id"],
                             ["gst_return_records.id", "gst_return_records.workspace_id"],
                             name="fk_gst_matches_record", ondelete="CASCADE"),
        _work_item_fk("gst_matches"),
        CheckConstraint(f"status IN ({_in(v.STATUSES)})", name="ck_gst_matches_status"),
        CheckConstraint("record_id IS NOT NULL OR work_item_id IS NOT NULL", name="ck_gst_matches_side"),
        CheckConstraint("ims_action IS NULL OR ims_action IN ('ACCEPT', 'PENDING', 'REJECT')",
                        name="ck_gst_matches_ims"),
        Index("uq_gst_matches_record", "workspace_id", "gstin", "record_id", unique=True,
              postgresql_where=text("record_id IS NOT NULL")),
        Index("uq_gst_matches_work_item", "workspace_id", "gstin", "work_item_id", unique=True,
              postgresql_where=text("work_item_id IS NOT NULL")),
        Index("ix_gst_matches_status", "workspace_id", "gstin", "status"),
        Index("ix_gst_matches_supplier", "workspace_id", "gstin", "supplier_gstin"),
        Index("ix_gst_matches_organization", "organization_id"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    organization_id: Mapped[uuid.UUID] = _org()
    workspace_id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    gstin: Mapped[str] = mapped_column(String(15), nullable=False)
    record_id: Mapped[Optional[uuid.UUID]] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    work_item_id: Mapped[Optional[uuid.UUID]] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    method: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    supplier_gstin: Mapped[Optional[str]] = mapped_column(String(15), nullable=True)
    supplier_name: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    doc_number: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    doc_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    value_micros: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    tax_micros: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    itc_micros: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    differences: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    notes: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    ims_action: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    ims_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    period_first_seen: Mapped[Optional[str]] = mapped_column(String(7), nullable=True)
    reported_late: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    risk: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB(none_as_null=True), nullable=True)
    decision: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    computed_at: Mapped[datetime] = _ts()


class GstDecision(Base):
    """A person's decision about one supplier document, keyed by its natural key."""

    __tablename__ = "gst_decisions"
    __table_args__ = (
        _workspace_fk("gst_decisions"),
        _work_item_fk("gst_decisions"),
        UniqueConstraint("workspace_id", "gstin", "supplier_gstin", "doc_key", "kind",
                         name="uq_gst_decisions_document"),
        CheckConstraint("decision IN ('CONFIRM', 'NOT_OURS', 'LINK')", name="ck_gst_decisions_decision"),
        CheckConstraint("decision = 'NOT_OURS' OR work_item_id IS NOT NULL", name="ck_gst_decisions_needs_book"),
        Index("ix_gst_decisions_organization", "organization_id"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    organization_id: Mapped[uuid.UUID] = _org()
    workspace_id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    gstin: Mapped[str] = mapped_column(String(15), nullable=False)
    supplier_gstin: Mapped[str] = mapped_column(String(15), nullable=False)
    doc_key: Mapped[str] = mapped_column(String(64), nullable=False)
    kind: Mapped[str] = mapped_column(String(12), nullable=False)
    decision: Mapped[str] = mapped_column(String(10), nullable=False)
    work_item_id: Mapped[Optional[uuid.UUID]] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    decided_by_user_id: Mapped[Optional[uuid.UUID]] = _user()
    decided_at: Mapped[datetime] = _ts()


class GstSettings(Base):
    """Per workspace: the rounding tolerance per amount head."""

    __tablename__ = "gst_settings"
    __table_args__ = (
        _workspace_fk("gst_settings"),
        CheckConstraint("tolerance_micros >= 0 AND tolerance_micros <= 1000000000", name="ck_gst_settings_tolerance"),
        CheckConstraint("waiting_notice_days >= 1 AND waiting_notice_days <= 365", name="ck_gst_settings_waiting_notice_days"),
        Index("ix_gst_settings_organization", "organization_id"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[uuid.UUID] = _org()
    tolerance_micros: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("1000000"))
    #: Session J: a purchase invoice still missing from every GSTR-2B after this many days is announced to the rules.
    waiting_notice_days: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("30"))
    updated_by_user_id: Mapped[Optional[uuid.UUID]] = _user()
    updated_at: Mapped[datetime] = _ts()
