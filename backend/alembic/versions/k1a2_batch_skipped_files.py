"""A batch remembers the files it skipped (Final session 1, 2A: zip upload).

When a zip is unpacked, a member that is not a document (a stray .txt, a GSTR-2B JSON that belongs on the GST credit page) is
skipped and reported, not refused and not counted as a failure. The tray reads the list from the batch to say "38 documents
added, 2 skipped: not a supported file type". Each entry is {"name", "code", "message"}; the handler keeps at most 200.

Expand-only: a NOT NULL column with a default of an empty list. Downgrade drops it.

Revision ID: k1a2_batch_skipped_files
Revises: k1a1_helm_settlement_detachable
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "k1a2_batch_skipped_files"
down_revision = "k1a1_helm_settlement_detachable"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ingestion_batches",
        sa.Column("skipped", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
    )
    op.create_check_constraint("ck_ingestion_batches_skipped_is_list", "ingestion_batches", "jsonb_typeof(skipped) = 'array'")


def downgrade() -> None:
    op.drop_constraint("ck_ingestion_batches_skipped_is_list", "ingestion_batches", type_="check")
    op.drop_column("ingestion_batches", "skipped")
