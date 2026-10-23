"""Document packs propose their suggested checks (Final session 1, Phase 6, F-408): what a workspace turned down.

Enabling a pack now proposes its suggested checks in Clause assertions, one click to accept each. A check the workspace's
administrator declined must not be proposed again, so the workspace's row for that pack remembers the keys it turned down.
Expand-only: one nullable-free column with a default. Downgrade drops it (the declined checks are proposed again).

Revision ID: k1a7_pack_check_dismissals
Revises: k1a6_engine_webhook_events
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "k1a7_pack_check_dismissals"
down_revision = "k1a6_engine_webhook_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "workspace_schema_presets",
        sa.Column("dismissed_checks", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
    )


def downgrade() -> None:
    op.drop_column("workspace_schema_presets", "dismissed_checks")
