"""TRINETRA resolution end to end (Final 2T, Phase 6): inquiries, approval chains, the closure ledger.

`trinetra_inquiries`: a customer inquiry a person approved and sent (to the confirmed contact, with a secure document-request
link). `trinetra_policies` and `trinetra_approvals`: an Enterprise organization's approval chain for closing cases.
`trinetra_outcomes`: the closure ledger, one row per (case, confirming snapshot). Downgrade drops all four.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "tr2t7_resolution"
down_revision = "tr2t6_money_model"
branch_labels = None
depends_on = None


def _scope(table):
    return [
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def _credit_constraints(table):
    return [
        sa.ForeignKeyConstraint(["workspace_id", "organization_id"], ["workspaces.id", "workspaces.organization_id"],
                                ondelete="CASCADE", name=f"fk_{table}_scope"),
        sa.UniqueConstraint("id", "workspace_id", name=f"uq_{table}_scope"),
        sa.ForeignKeyConstraint(["credit_id", "workspace_id"], ["trinetra_credits.id", "trinetra_credits.workspace_id"], ondelete="CASCADE"),
    ]


def _users(name, nullable=True):
    return sa.Column(name, postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=nullable)


def upgrade():
    op.create_table(
        "trinetra_inquiries", *_scope("trinetra_inquiries"),
        sa.Column("credit_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_kind", sa.String(24), nullable=False),
        sa.Column("subject", sa.String(200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("status", sa.String(12), nullable=False, server_default="DRAFT"),
        sa.Column("recipient_label", sa.String(200), nullable=False, server_default=""),
        sa.Column("recipient_masked", sa.String(120), nullable=True),
        _users("created_by"), _users("approved_by"),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        _users("sent_by"),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivery_state", sa.String(12), nullable=True),
        sa.Column("delivery_detail", sa.String(300), nullable=True),
        sa.Column("override_reason", sa.Text(), nullable=True),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reply_work_item_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("replied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        *_credit_constraints("trinetra_inquiries"),
        sa.CheckConstraint("status IN ('DRAFT','APPROVED','SENT','FAILED','REPLIED','WITHDRAWN')", name="ck_trinetra_inquiry_status"),
        sa.CheckConstraint("document_kind IN ('CERTIFICATE','DEDUCTOR_ADVICE','CORRECTION_RESPONSE')", name="ck_trinetra_inquiry_kind"),
    )
    op.create_index("ix_trinetra_inquiries_organization_id", "trinetra_inquiries", ["organization_id"])
    op.create_index("ix_trinetra_inquiries_workspace_id", "trinetra_inquiries", ["workspace_id"])
    op.create_index("ix_trinetra_inquiries_month", "trinetra_inquiries", ["organization_id", "sent_at"])
    op.create_table(
        "trinetra_policies",
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("threshold_micros", sa.BigInteger(), nullable=False),
        sa.Column("actions", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("approver_role", sa.String(10), nullable=False),
        _users("updated_by"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("threshold_micros >= 0", name="ck_trinetra_policy_threshold"),
        sa.CheckConstraint("approver_role IN ('ADMIN','OWNER')", name="ck_trinetra_policy_role"),
    )
    op.create_table(
        "trinetra_approvals", *_scope("trinetra_approvals"),
        sa.Column("credit_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("amount_micros", sa.BigInteger(), nullable=False),
        sa.Column("case_revision", sa.Integer(), nullable=False),
        sa.Column("approver_role", sa.String(10), nullable=False),
        _users("requested_by"),
        sa.Column("status", sa.String(10), nullable=False, server_default="PENDING"),
        _users("decided_by"),
        sa.Column("decided_reason", sa.Text(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        *_credit_constraints("trinetra_approvals"),
        sa.CheckConstraint("status IN ('PENDING','APPROVED','REJECTED','STALE')", name="ck_trinetra_approval_status"),
        sa.CheckConstraint("action IN ('CA_REVIEWED','EXPLAINED','UNRESOLVED')", name="ck_trinetra_approval_action"),
    )
    op.create_index("ix_trinetra_approvals_organization_id", "trinetra_approvals", ["organization_id"])
    op.create_index("ix_trinetra_approvals_workspace_id", "trinetra_approvals", ["workspace_id"])
    op.create_index("uq_trinetra_approval_pending", "trinetra_approvals", ["credit_id"], unique=True,
                    postgresql_where=sa.text("status = 'PENDING'"))
    op.create_table(
        "trinetra_outcomes", *_scope("trinetra_outcomes"),
        sa.Column("credit_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("snapshot_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("amount_micros", sa.BigInteger(), nullable=False),
        sa.Column("was_gap", sa.Boolean(), nullable=False, server_default=sa.false()),
        _users("confirmed_by"),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        *_credit_constraints("trinetra_outcomes"),
        sa.UniqueConstraint("credit_id", "snapshot_id", name="uq_trinetra_outcome"),
        sa.CheckConstraint("amount_micros >= 0", name="ck_trinetra_outcome_amount"),
    )
    op.create_index("ix_trinetra_outcomes_organization_id", "trinetra_outcomes", ["organization_id"])
    op.create_index("ix_trinetra_outcomes_workspace_id", "trinetra_outcomes", ["workspace_id"])
    op.create_index("ix_trinetra_outcomes_confirmed", "trinetra_outcomes", ["organization_id", "confirmed_at"])


def downgrade():
    op.drop_table("trinetra_outcomes")
    op.drop_table("trinetra_approvals")
    op.drop_table("trinetra_policies")
    op.drop_table("trinetra_inquiries")
