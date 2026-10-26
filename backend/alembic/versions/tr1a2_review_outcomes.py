"""Immutable import comparisons and explicitly recorded reviewer effort.

Additive defaults preserve existing snapshots and decisions. Downgrade removes only
the outcome baseline and recorded minutes; export the dossier before rollback.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "tr1a2_review_outcomes"
down_revision = "tr1a1_credit_assurance"
branch_labels = None
depends_on = None


def upgrade():
    for table in ("trinetra_statements", "trinetra_credits", "trinetra_decisions"):
        op.add_column(
            table,
            sa.Column(
                "evidence_work_item_ids",
                postgresql.JSONB(),
                nullable=False,
                server_default=sa.text("'[]'::jsonb"),
            ),
        )
    op.execute(
        """UPDATE trinetra_credits SET evidence_work_item_ids = COALESCE(
        (SELECT jsonb_agg(e->'work_item_id') FROM jsonb_array_elements(review->'evidence') e), '[]'::jsonb)"""
    )
    op.execute(
        """UPDATE trinetra_decisions d SET evidence_work_item_ids = c.evidence_work_item_ids
        FROM trinetra_credits c WHERE c.id = d.credit_id"""
    )
    op.add_column(
        "trinetra_statements",
        sa.Column(
            "comparison",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column(
        "trinetra_decisions",
        sa.Column(
            "review_minutes", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
    )
    op.create_check_constraint(
        "ck_trinetra_review_minutes",
        "trinetra_decisions",
        "review_minutes BETWEEN 0 AND 480",
    )


def downgrade():
    op.drop_constraint(
        "ck_trinetra_review_minutes", "trinetra_decisions", type_="check"
    )
    op.drop_column("trinetra_decisions", "review_minutes")
    op.drop_column("trinetra_statements", "comparison")
    for table in ("trinetra_decisions", "trinetra_credits", "trinetra_statements"):
        op.drop_column(table, "evidence_work_item_ids")
