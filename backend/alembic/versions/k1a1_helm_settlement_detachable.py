"""A Helm settlement can outlive the document it was made for (Final session 1, 1A).

Whether an invoice was paid cannot be rebuilt from documents, so the settlement is a money record the organization keeps
(HANDOFF and NEEDS-OWNER N-162). When the retention sweep deletes a document, the sweep now clears the settlement's link to
it (`document_content.destroy_copies(mode="purge")`) instead of letting `ON DELETE CASCADE` delete the settlement. That
needs the link to be able to hold NULL. The composite foreign key (work_item_id, workspace_id) is MATCH SIMPLE, so a NULL
link is simply not checked. The unique constraint on `work_item_id` keeps holding for linked rows (NULLs never collide).

Downgrade: settlements that lost their document cannot satisfy NOT NULL, so they are deleted first.

Revision ID: k1a1_helm_settlement_detachable
Revises: j1a3_automation_volume_safety
"""

from __future__ import annotations

from alembic import op

revision = "k1a1_helm_settlement_detachable"
down_revision = "j1a3_automation_volume_safety"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("helm_settlements", "work_item_id", nullable=True)


def downgrade() -> None:
    op.execute("DELETE FROM helm_settlements WHERE work_item_id IS NULL")
    op.alter_column("helm_settlements", "work_item_id", nullable=False)
