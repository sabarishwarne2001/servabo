"""TRINETRA's whole money model: unresolved closures and reviewed reversal pairings (Final 2T, Phase 5).

A case may now close as UNRESOLVED (closed without resolution, with a reason). `trinetra_pairings` records the reversals a
person paired with the row they reverse: netting happens only through a pairing. Downgrade closes UNRESOLVED cases as
EXPLAINED (the nearest closed state the old constraint knows) and drops the pairings.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "tr2t6_money_model"
down_revision = "tr2t5_suggestions_and_directory"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint("ck_trinetra_credit_state", "trinetra_credits", type_="check")
    op.create_check_constraint("ck_trinetra_credit_state", "trinetra_credits",
                               "state IN ('OPEN','DISPUTED','EXPLAINED','WITHDRAWN','CA_REVIEWED','UNRESOLVED')")
    op.create_table(
        "trinetra_pairings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("profile_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("statement_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("positive_line", sa.Integer(), nullable=False),
        sa.Column("negative_line", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("withdrawn_reason", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["workspace_id", "organization_id"], ["workspaces.id", "workspaces.organization_id"],
                                ondelete="CASCADE", name="fk_trinetra_pairings_scope"),
        sa.UniqueConstraint("id", "workspace_id", name="uq_trinetra_pairings_scope"),
        sa.ForeignKeyConstraint(["profile_id", "workspace_id"], ["trinetra_profiles.id", "trinetra_profiles.workspace_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["statement_id", "workspace_id"], ["trinetra_statements.id", "trinetra_statements.workspace_id"], ondelete="CASCADE"),
        sa.CheckConstraint("positive_line >= 0 AND negative_line >= 0 AND positive_line <> negative_line", name="ck_trinetra_pairing_lines"),
    )
    op.create_index("ix_trinetra_pairings_organization_id", "trinetra_pairings", ["organization_id"])
    op.create_index("ix_trinetra_pairings_workspace_id", "trinetra_pairings", ["workspace_id"])
    op.create_index("uq_trinetra_pairing_negative", "trinetra_pairings", ["statement_id", "negative_line"], unique=True,
                    postgresql_where=sa.text("active"))


def downgrade():
    op.drop_table("trinetra_pairings")
    op.execute("UPDATE trinetra_credits SET state = 'EXPLAINED' WHERE state = 'UNRESOLVED'")
    op.drop_constraint("ck_trinetra_credit_state", "trinetra_credits", type_="check")
    op.create_check_constraint("ck_trinetra_credit_state", "trinetra_credits",
                               "state IN ('OPEN','DISPUTED','EXPLAINED','WITHDRAWN','CA_REVIEWED')")
