"""TRINETRA expectations from the records a business already has, and the deductor directory (Final 2T, Phase 4).

`trinetra_suggestions`: a suggested expectation (printed on an invoice, typed in the expectations template, or read from
Zoho Books) that a person accepts or dismisses. `trinetra_deductors`: a customer's TAN mapped to the customer once, reviewed
by a person. Both are scoped to the workspace and profile with composite foreign keys. Downgrade drops both; no case depends
on a suggestion (a case keeps its own record of where its expectation came from).
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "tr2t5_suggestions_and_directory"
down_revision = "tr2t4_statement_files"
branch_labels = None
depends_on = None


def _scope(table):
    return [
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def _scope_constraints(table):
    return [
        sa.ForeignKeyConstraint(["workspace_id", "organization_id"], ["workspaces.id", "workspaces.organization_id"],
                                ondelete="CASCADE", name=f"fk_{table}_scope"),
        sa.UniqueConstraint("id", "workspace_id", name=f"uq_{table}_scope"),
        sa.ForeignKeyConstraint(["profile_id", "workspace_id"], ["trinetra_profiles.id", "trinetra_profiles.workspace_id"],
                                ondelete="CASCADE"),
    ]


def upgrade():
    op.create_table(
        "trinetra_suggestions",
        *_scope("trinetra_suggestions"),
        sa.Column("profile_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("work_item_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("amount_micros", sa.BigInteger(), nullable=False),
        sa.Column("deductor_key", sa.String(64), nullable=True),
        sa.Column("tan_masked", sa.String(10), nullable=True),
        sa.Column("section_text", sa.String(100), nullable=True),
        sa.Column("counterparty", sa.String(120), nullable=False),
        sa.Column("reference", sa.String(100), nullable=False),
        sa.Column("source_version", sa.String(64), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("evidence", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.String(12), nullable=False, server_default="OPEN"),
        sa.Column("decided_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("decided_reason", sa.Text(), nullable=True),
        sa.Column("credit_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        *_scope_constraints("trinetra_suggestions"),
        sa.ForeignKeyConstraint(["work_item_id", "workspace_id"], ["work_items.id", "work_items.workspace_id"], ondelete="CASCADE"),
        sa.UniqueConstraint("profile_id", "work_item_id", "year", "source", name="uq_trinetra_suggestion_source"),
        sa.CheckConstraint("source IN ('PRINTED_HINT','TEMPLATE','ZOHO')", name="ck_trinetra_suggestion_source"),
        sa.CheckConstraint("status IN ('OPEN','ACCEPTED','DISMISSED')", name="ck_trinetra_suggestion_status"),
        sa.CheckConstraint("amount_micros > 0 AND amount_micros <= 9000000000000000", name="ck_trinetra_suggestion_amount"),
        sa.CheckConstraint("year BETWEEN 2000 AND 2100", name="ck_trinetra_suggestion_year"),
    )
    op.create_index("ix_trinetra_suggestions_organization_id", "trinetra_suggestions", ["organization_id"])
    op.create_index("ix_trinetra_suggestions_workspace_id", "trinetra_suggestions", ["workspace_id"])
    op.create_table(
        "trinetra_deductors",
        *_scope("trinetra_deductors"),
        sa.Column("profile_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("deductor_key", sa.String(64), nullable=False),
        sa.Column("tan_masked", sa.String(10), nullable=False),
        sa.Column("counterparty_key", sa.String(255), nullable=False),
        sa.Column("counterparty_name", sa.String(120), nullable=False),
        sa.Column("status", sa.String(12), nullable=False, server_default="PROPOSED"),
        sa.Column("seen_as", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("reviewed_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("review_reason", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        *_scope_constraints("trinetra_deductors"),
        sa.UniqueConstraint("profile_id", "deductor_key", name="uq_trinetra_deductor"),
        sa.CheckConstraint("status IN ('PROPOSED','CONFIRMED','FLAGGED')", name="ck_trinetra_deductor_status"),
    )
    op.create_index("ix_trinetra_deductors_organization_id", "trinetra_deductors", ["organization_id"])
    op.create_index("ix_trinetra_deductors_workspace_id", "trinetra_deductors", ["workspace_id"])


def downgrade():
    op.drop_table("trinetra_deductors")
    op.drop_table("trinetra_suggestions")
