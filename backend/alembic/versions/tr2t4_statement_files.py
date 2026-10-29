"""A TRINETRA statement can come from an uploaded file (Final 2T, Phase 3).

A snapshot read by the template or an official-download reader has no document in Documents: it is identified by the file's
SHA-256 and keeps which reader read it and what the file said about itself (`source_meta`). So `source_work_item_id` becomes
nullable, guarded by a check that one of the two identifies the source. Downgrade deletes the file-sourced snapshots (they
cannot satisfy the old NOT NULL), after which every remaining snapshot has its document; export dossiers first.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "tr2t4_statement_files"
down_revision = "tr2t3_pilot_enrolment"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column("trinetra_statements", "source_work_item_id", nullable=True)
    op.add_column("trinetra_statements", sa.Column("source_sha256", sa.String(64), nullable=True))
    op.add_column("trinetra_statements", sa.Column("source_meta", postgresql.JSONB(), nullable=False,
                                                   server_default=sa.text("'{}'::jsonb")))
    op.create_check_constraint("ck_trinetra_statement_source", "trinetra_statements",
                               "source_work_item_id IS NOT NULL OR source_sha256 IS NOT NULL")


def downgrade():
    op.drop_constraint("ck_trinetra_statement_source", "trinetra_statements", type_="check")
    op.execute("DELETE FROM trinetra_statements WHERE source_work_item_id IS NULL")
    op.drop_column("trinetra_statements", "source_meta")
    op.drop_column("trinetra_statements", "source_sha256")
    op.alter_column("trinetra_statements", "source_work_item_id", nullable=False)
