"""A counterparty's email address says where it came from (Final session 2A, Phase 3; N-195).

Helm learns a supplier's or customer's address from the invoices it reads, and the GST reminder, the supplier document
request and Helm's emails sent to it. A document can print any address, so a learned address is now only a suggestion:
`contact_source` is DOCUMENT (read from an invoice, never a recipient) or PERSON (typed or confirmed by an owner or admin,
a recipient), with who confirmed it and when.

Existing addresses cannot be told apart (the old code wrote both kinds to the same column), so every existing address is
marked DOCUMENT: it stays visible and an owner confirms it once (Helm, Settings, Suppliers and customers). That is the
safe reading; the cost is that reminders to those contacts wait for one click (N-195).

Downgrade drops the three columns and the check.

Revision ID: s2a3_counterparty_contact_source
Revises: s2a2_deletion_notice_sends
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "s2a3_counterparty_contact_source"
down_revision = "s2a2_deletion_notice_sends"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("helm_counterparties", sa.Column("contact_source", sa.String(12), nullable=True))
    op.add_column("helm_counterparties", sa.Column("contact_confirmed_by_user_id", UUID(as_uuid=True), nullable=True))
    op.add_column("helm_counterparties", sa.Column("contact_confirmed_at", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key("fk_helm_counterparties_contact_confirmed_by_user_id_users", "helm_counterparties", "users",
                          ["contact_confirmed_by_user_id"], ["id"], ondelete="SET NULL")
    op.create_check_constraint("ck_helm_counterparties_contact_source", "helm_counterparties",
                               "contact_source IS NULL OR contact_source IN ('DOCUMENT', 'PERSON')")
    op.execute("UPDATE helm_counterparties SET contact_source = 'DOCUMENT' WHERE contact_email IS NOT NULL")


def downgrade() -> None:
    op.drop_constraint("ck_helm_counterparties_contact_source", "helm_counterparties", type_="check")
    op.drop_constraint("fk_helm_counterparties_contact_confirmed_by_user_id_users", "helm_counterparties",
                       type_="foreignkey")
    op.drop_column("helm_counterparties", "contact_confirmed_at")
    op.drop_column("helm_counterparties", "contact_confirmed_by_user_id")
    op.drop_column("helm_counterparties", "contact_source")
