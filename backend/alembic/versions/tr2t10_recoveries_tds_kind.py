"""Recoveries learns a new kind, TDS_CREDIT (Final 2T, Phase 7.10).

`ck_recovery_issues_kind` admits `TDS_CREDIT`: tax a customer withheld that is not yet in the imported tax statement. The list is
written out in full, not imported. Expand only. The downgrade deletes the issues of that kind (their outcomes cascade; there are none:
a TDS issue never records an outcome) and narrows the CHECK again.

Revision ID: tr2t10_recoveries_tds_kind
Revises: tr2t9_case_events
"""

from alembic import op

revision = "tr2t10_recoveries_tds_kind"
down_revision = "tr2t9_case_events"
branch_labels = None
depends_on = None

BEFORE = "('GST_CREDIT', 'DUPLICATE', 'OVERCHARGE', 'STATEMENT_DIFFERENCE', 'PAYMENT_DEADLINE')"
AFTER = "('GST_CREDIT', 'DUPLICATE', 'OVERCHARGE', 'STATEMENT_DIFFERENCE', 'PAYMENT_DEADLINE', 'TDS_CREDIT')"


#: The name the database holds: the metadata's naming convention prefixes the model's own "ck_recovery_issues_kind".
CHECK_NAME = "ck_recovery_issues_ck_recovery_issues_kind"


def _kinds(values: str) -> None:
    op.execute(f"ALTER TABLE recovery_issues DROP CONSTRAINT IF EXISTS {CHECK_NAME}")
    op.execute(f"ALTER TABLE recovery_issues ADD CONSTRAINT {CHECK_NAME} CHECK (kind IN {values})")


def upgrade() -> None:
    _kinds(AFTER)


def downgrade() -> None:
    op.execute("DELETE FROM recovery_issues WHERE kind = 'TDS_CREDIT'")
    _kinds(BEFORE)
