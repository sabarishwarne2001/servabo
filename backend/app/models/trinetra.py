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
    #: Final 2T (Phase 1.4): the PAN keyed with the ORGANIZATION's salt, so one legal entity has one profile per
    #: organization without ever decrypting another workspace's PAN. NULL only for a profile made before it existed
    #: (filled in when the organization next creates a profile).
    org_pan_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    __table_args__ = (
        *scope_constraints("trinetra_profiles"),
        Index(
            "uq_trinetra_org_pan",
            "organization_id",
            "org_pan_fingerprint",
            unique=True,
            postgresql_where=text("org_pan_fingerprint IS NOT NULL"),
        ),
    )


class TrinetraOrgKey(Base):
    """One random, encrypted salt per organization: the key of `org_pan_fingerprint` (never derived from a JWT secret)."""

    __tablename__ = "trinetra_org_keys"
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True
    )
    salt_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class TrinetraPilot(Base):
    """An organization a platform administrator enrolled in the TRINETRA pilot (mode "pilot"). The reason is required."""

    __tablename__ = "trinetra_pilot"
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True
    )
    enrolled_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class TrinetraStatement(Scoped, Base):
    __tablename__ = "trinetra_statements"
    evidence_work_item_ids: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    profile_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    #: The document the typed rows were read from. NULL for a snapshot read from an uploaded statement file
    #: (Final 2T, Phase 3): that snapshot is identified by the file's SHA-256 instead, and no file name is kept.
    source_work_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    source_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: Which reader, its tax-year label exactly as the file states it, whether the reader was verified, the file's own
    #: totals check, and what was left out. Never a PAN or a file name.
    source_meta: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
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
        CheckConstraint(
            "source_work_item_id IS NOT NULL OR source_sha256 IS NOT NULL",
            name="ck_trinetra_statement_source",
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
