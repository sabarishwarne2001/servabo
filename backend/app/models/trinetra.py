"""TRINETRA reference views; canonical documents and bank records remain their owners'."""

import uuid
from datetime import datetime
from sqlalchemy import (
    String,
    Text,
    Integer,
    BigInteger,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    UniqueConstraint,
    CheckConstraint,
    Index,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, declared_attr
from app.db.base import Base


def scope_constraints(table):
    return (
        ForeignKeyConstraint(
            ["workspace_id", "organization_id"],
            ["workspaces.id", "workspaces.organization_id"],
            ondelete="CASCADE",
            name=f"fk_{table}_scope",
        ),
        UniqueConstraint("id", "workspace_id", name=f"uq_{table}_scope"),
    )


class Scoped:
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    @declared_attr.directive
    def __table_args__(cls):
        return (
            ForeignKeyConstraint(
                ["workspace_id", "organization_id"],
                ["workspaces.id", "workspaces.organization_id"],
                ondelete="CASCADE",
                name=f"fk_{cls.__tablename__}_scope",
            ),
            UniqueConstraint(
                "id", "workspace_id", name=f"uq_{cls.__tablename__}_scope"
            ),
        )


class TrinetraProfile(Scoped, Base):
    __tablename__ = "trinetra_profiles"
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    pan_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    identity_salt_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    pan_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    pan_masked: Mapped[str] = mapped_column(String(10), nullable=False)


class TrinetraStatement(Scoped, Base):
    __tablename__ = "trinetra_statements"
    evidence_work_item_ids: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    profile_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    source_work_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    source_version: Mapped[str] = mapped_column(String(64), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(40), nullable=False)
    # Human-confirmed transcription. Never presented as machine-verified official format.
    rows: Mapped[list] = mapped_column(JSONB, nullable=False)
    active: Mapped[bool] = mapped_column(default=True, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    comparison: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    __table_args__ = (
        *scope_constraints("trinetra_statements"),
        ForeignKeyConstraint(
            ["profile_id", "workspace_id"],
            ["trinetra_profiles.id", "trinetra_profiles.workspace_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["source_work_item_id", "workspace_id"],
            ["work_items.id", "work_items.workspace_id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "profile_id", "year", "fingerprint", name="uq_trinetra_snapshot"
        ),
        Index(
            "uq_trinetra_active_snapshot",
            "profile_id",
            "year",
            unique=True,
            postgresql_where=text("active"),
        ),
        CheckConstraint(
            "year BETWEEN 2000 AND 2100 AND revision > 0",
            name="ck_trinetra_statement_year",
        ),
    )


class TrinetraCredit(Scoped, Base):
    __tablename__ = "trinetra_credits"
    evidence_work_item_ids: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    profile_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    work_item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    counterparty: Mapped[str] = mapped_column(String(120), nullable=False)
    deductor_key: Mapped[str] = mapped_column(String(64), nullable=False)
    expected_micros: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reference: Mapped[str] = mapped_column(String(100), nullable=False)
    source_version: Mapped[str] = mapped_column(String(64), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    state: Mapped[str] = mapped_column(String(30), nullable=False, default="OPEN")
    # References to canonical evidence plus review ownership; no bank/accounting ledger.
    review: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    __table_args__ = (
        *scope_constraints("trinetra_credits"),
        ForeignKeyConstraint(
            ["profile_id", "workspace_id"],
            ["trinetra_profiles.id", "trinetra_profiles.workspace_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["work_item_id", "workspace_id"],
            ["work_items.id", "work_items.workspace_id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "profile_id", "work_item_id", "year", name="uq_trinetra_credit_source"
        ),
        CheckConstraint(
            "expected_micros >= 0 AND expected_micros <= 9000000000000000 AND revision > 0",
            name="ck_trinetra_credit_amount",
        ),
        CheckConstraint("year BETWEEN 2000 AND 2100", name="ck_trinetra_credit_year"),
        CheckConstraint(
            "state IN ('OPEN','DISPUTED','EXPLAINED','WITHDRAWN','CA_REVIEWED')",
            name="ck_trinetra_credit_state",
        ),
    )


class TrinetraDecision(Scoped, Base):
    __tablename__ = "trinetra_decisions"
    evidence_work_item_ids: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    credit_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(String(30), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    allocations: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    review_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    __table_args__ = (
        *scope_constraints("trinetra_decisions"),
        CheckConstraint(
            "review_minutes BETWEEN 0 AND 480", name="ck_trinetra_review_minutes"
        ),
        ForeignKeyConstraint(
            ["credit_id", "workspace_id"],
            ["trinetra_credits.id", "trinetra_credits.workspace_id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("credit_id", "revision", name="uq_trinetra_decision_revision"),
    )
