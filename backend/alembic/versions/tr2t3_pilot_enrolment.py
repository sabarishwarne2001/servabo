"""TRINETRA's pilot mode: the organizations a platform administrator enrolled (Final 2T, Phase 2.1).

One row per enrolled organization (with who enrolled it and why). Downgrade drops the table: every organization is then
simply not enrolled, which is the safe direction.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "tr2t3_pilot_enrolment"
down_revision = "tr2t2_one_profile_per_entity"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "trinetra_pilot",
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                  primary_key=True),
        sa.Column("enrolled_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade():
    op.drop_table("trinetra_pilot")
