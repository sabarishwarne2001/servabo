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
            "state IN ('OPEN','DISPUTED','EXPLAINED','WITHDRAWN','CA_REVIEWED','UNRESOLVED')",
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


class TrinetraSuggestion(Scoped, Base):
    """A SUGGESTED expectation (Final 2T, Phase 4): printed on an invoice, typed in the expectations template, or read from
    Zoho Books. It becomes a case only when a person accepts it, with a reason. Never confirmed automatically."""

    __tablename__ = "trinetra_suggestions"
    profile_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    work_item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    amount_micros: Mapped[int] = mapped_column(BigInteger, nullable=False)
    #: The deductor's TAN keyed with the profile's salt; NULL when the source does not carry one (the person supplies it).
    deductor_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tan_masked: Mapped[str | None] = mapped_column(String(10), nullable=True)
    section_text: Mapped[str | None] = mapped_column(String(100), nullable=True)
    counterparty: Mapped[str] = mapped_column(String(120), nullable=False)
    reference: Mapped[str] = mapped_column(String(100), nullable=False)
    #: The invoice's fingerprint when it was suggested; a changed invoice is suggested again, not silently accepted.
    source_version: Mapped[str] = mapped_column(String(64), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="OPEN")
    decided_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    decided_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    credit_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    __table_args__ = (
        *scope_constraints("trinetra_suggestions"),
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
        UniqueConstraint("profile_id", "work_item_id", "year", "source", name="uq_trinetra_suggestion_source"),
        CheckConstraint("source IN ('PRINTED_HINT','TEMPLATE','ZOHO')", name="ck_trinetra_suggestion_source"),
        CheckConstraint("status IN ('OPEN','ACCEPTED','DISMISSED')", name="ck_trinetra_suggestion_status"),
        CheckConstraint("amount_micros > 0 AND amount_micros <= 9000000000000000", name="ck_trinetra_suggestion_amount"),
        CheckConstraint("year BETWEEN 2000 AND 2100", name="ck_trinetra_suggestion_year"),
    )


class TrinetraDeductor(Scoped, Base):
    """The deductor directory (Final 2T, Phase 4): a customer's TAN mapped to the customer once, reviewed by a person, then
    used for suggestions and display with the TAN masked. A TAN seen under two customers is FLAGGED for review and never merged."""

    __tablename__ = "trinetra_deductors"
    profile_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    deductor_key: Mapped[str] = mapped_column(String(64), nullable=False)
    tan_masked: Mapped[str] = mapped_column(String(10), nullable=False)
    counterparty_key: Mapped[str] = mapped_column(String(255), nullable=False)
    counterparty_name: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="PROPOSED")
    #: The other customer names this TAN was seen under (only while FLAGGED), for the reviewer to choose from.
    seen_as: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb"))
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    review_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    __table_args__ = (
        *scope_constraints("trinetra_deductors"),
        ForeignKeyConstraint(
            ["profile_id", "workspace_id"],
            ["trinetra_profiles.id", "trinetra_profiles.workspace_id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("profile_id", "deductor_key", name="uq_trinetra_deductor"),
        CheckConstraint("status IN ('PROPOSED','CONFIRMED','FLAGGED')", name="ck_trinetra_deductor_status"),
    )


class TrinetraPairing(Scoped, Base):
    """A reviewed pairing of a reversal (a negative statement row) with the row it reverses (Final 2T, Phase 5). Rows are
    netted per deductor ONLY through a pairing a person made; an unpaired reversal stays an exception."""

    __tablename__ = "trinetra_pairings"
    profile_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    statement_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    positive_line: Mapped[int] = mapped_column(Integer, nullable=False)
    negative_line: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    active: Mapped[bool] = mapped_column(default=True, nullable=False)
    withdrawn_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    __table_args__ = (
        *scope_constraints("trinetra_pairings"),
        ForeignKeyConstraint(
            ["profile_id", "workspace_id"],
            ["trinetra_profiles.id", "trinetra_profiles.workspace_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["statement_id", "workspace_id"],
            ["trinetra_statements.id", "trinetra_statements.workspace_id"],
            ondelete="CASCADE",
        ),
        CheckConstraint("positive_line >= 0 AND negative_line >= 0 AND positive_line <> negative_line", name="ck_trinetra_pairing_lines"),
        Index("uq_trinetra_pairing_negative", "statement_id", "negative_line", unique=True, postgresql_where=text("active")),
    )


class TrinetraInquiry(Scoped, Base):
    """A customer inquiry about a case (Final 2T, Phase 6): drafted, approved by a person, SENT by a person who pressed Send,
    to the customer's confirmed contact, with a secure document-request link. Never automatic. The recipient's address is not
    stored here (it is read from the confirmed Helm contact at send time); only a masked form is kept."""

    __tablename__ = "trinetra_inquiries"
    credit_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    document_kind: Mapped[str] = mapped_column(String(24), nullable=False)
    subject: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="DRAFT")
    recipient_label: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    recipient_masked: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivery_state: Mapped[str | None] = mapped_column(String(12), nullable=True)
    delivery_detail: Mapped[str | None] = mapped_column(String(300), nullable=True)
    override_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    request_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    reply_work_item_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    replied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    __table_args__ = (
        *scope_constraints("trinetra_inquiries"),
        ForeignKeyConstraint(
            ["credit_id", "workspace_id"],
            ["trinetra_credits.id", "trinetra_credits.workspace_id"],
            ondelete="CASCADE",
        ),
        CheckConstraint("status IN ('DRAFT','APPROVED','SENT','FAILED','REPLIED','WITHDRAWN')", name="ck_trinetra_inquiry_status"),
        CheckConstraint("document_kind IN ('CERTIFICATE','DEDUCTOR_ADVICE','CORRECTION_RESPONSE')", name="ck_trinetra_inquiry_kind"),
        Index("ix_trinetra_inquiries_month", "organization_id", "sent_at"),
    )


class TrinetraPolicy(Base):
    """An Enterprise organization's approval chain for closing cases (Final 2T, Phase 6): closing a case worth at least the
    threshold, in one of the listed ways, needs the approval of the named role, by a different person."""

    __tablename__ = "trinetra_policies"
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True
    )
    threshold_micros: Mapped[int] = mapped_column(BigInteger, nullable=False)
    actions: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    approver_role: Mapped[str] = mapped_column(String(10), nullable=False)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    __table_args__ = (
        CheckConstraint("threshold_micros >= 0", name="ck_trinetra_policy_threshold"),
        CheckConstraint("approver_role IN ('ADMIN','OWNER')", name="ck_trinetra_policy_role"),
    )


class TrinetraApproval(Scoped, Base):
    """A closure waiting for (or decided by) the approval a policy asks for. Valid only for the revision it was asked on."""

    __tablename__ = "trinetra_approvals"
    credit_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    amount_micros: Mapped[int] = mapped_column(BigInteger, nullable=False)
    case_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    approver_role: Mapped[str] = mapped_column(String(10), nullable=False)
    requested_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="PENDING")
    decided_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    decided_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    __table_args__ = (
        *scope_constraints("trinetra_approvals"),
        ForeignKeyConstraint(
            ["credit_id", "workspace_id"],
            ["trinetra_credits.id", "trinetra_credits.workspace_id"],
            ondelete="CASCADE",
        ),
        CheckConstraint("status IN ('PENDING','APPROVED','REJECTED','STALE')", name="ck_trinetra_approval_status"),
        CheckConstraint("action IN ('CA_REVIEWED','EXPLAINED','UNRESOLVED')", name="ck_trinetra_approval_action"),
        Index("uq_trinetra_approval_pending", "credit_id", unique=True, postgresql_where=text("status = 'PENDING'")),
    )


class TrinetraOutcome(Scoped, Base):
    """The closure ledger (Final 2T, Phase 6): one row each time a closure is confirmed, deduplicated by (case, the snapshot
    that confirmed it), so monthly and yearly figures add up without counting anything twice and survive later imports.
    "TDS now visible in your statement" is NEVER cash recovered."""

    __tablename__ = "trinetra_outcomes"
    credit_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    snapshot_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    amount_micros: Mapped[int] = mapped_column(BigInteger, nullable=False)
    #: The case had a gap in an earlier import: only these count as "now visible" (a first-import posting never had a gap).
    was_gap: Mapped[bool] = mapped_column(nullable=False, default=False)
    confirmed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    __table_args__ = (
        *scope_constraints("trinetra_outcomes"),
        ForeignKeyConstraint(
            ["credit_id", "workspace_id"],
            ["trinetra_credits.id", "trinetra_credits.workspace_id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("credit_id", "snapshot_id", name="uq_trinetra_outcome"),
        CheckConstraint("amount_micros >= 0", name="ck_trinetra_outcome_amount"),
        Index("ix_trinetra_outcomes_confirmed", "organization_id", "confirmed_at"),
    )
