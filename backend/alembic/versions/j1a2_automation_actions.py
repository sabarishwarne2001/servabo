"""Chat endpoints and review due times (Session J, Phase 3).

Two expand-only changes for the new automation actions:

1. `webhook_endpoints.kind` ('GENERIC' | 'SLACK' | 'TEAMS', default GENERIC) and `url_encrypted`. A Slack or Teams
   incoming-webhook URL is a secret (anyone holding it can post to the channel), so for a chat endpoint the URL is stored
   encrypted with the existing MultiFernet keys and `url` holds only a masked, display-safe form
   ("https://hooks.slack.com/services/…"). Encryption, egress, retries and the delivery log are the webhook registry's own.
2. `review_assignments.due_at`: when a review that an automation rule assigned to a person is due.

Downgrade drops both columns. A chat endpoint cannot exist without its encrypted URL, so downgrading deletes them first.

Revision ID: j1a2_automation_actions
Revises: j1a1_automation_triggers
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "j1a2_automation_actions"
down_revision = "j1a1_automation_triggers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("webhook_endpoints", sa.Column("kind", sa.String(8), nullable=False, server_default="GENERIC"))
    op.add_column("webhook_endpoints", sa.Column("url_encrypted", sa.Text(), nullable=True))
    op.create_check_constraint("ck_webhook_endpoints_kind", "webhook_endpoints",
                               "kind IN ('GENERIC', 'SLACK', 'TEAMS')")
    op.create_check_constraint("ck_webhook_endpoints_chat_url_encrypted", "webhook_endpoints",
                               "(kind = 'GENERIC') = (url_encrypted IS NULL)")
    op.add_column("review_assignments", sa.Column("due_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("review_assignments", "due_at")
    op.execute("DELETE FROM webhook_endpoints WHERE kind <> 'GENERIC'")
    op.drop_constraint("ck_webhook_endpoints_chat_url_encrypted", "webhook_endpoints", type_="check")
    op.drop_constraint("ck_webhook_endpoints_kind", "webhook_endpoints", type_="check")
    op.drop_column("webhook_endpoints", "url_encrypted")
    op.drop_column("webhook_endpoints", "kind")
