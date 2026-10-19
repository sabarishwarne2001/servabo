"""GST Credit becomes the third add-on (Session H, N-145).

`ck_organization_addons_key_known` lists the add-on keys the ledger may hold. It gains `addon.gst_credit`, the add-on
a Developer organization buys to get the GST Credit lists (Business and Enterprise include them through their plan).
Nothing else changes: the add-on uses the ledger columns the other two use.

The downgrade puts the two-key constraint back. Rows for the new key are deleted first, because they could not
satisfy it: only an organization that bought the add-on has one, and the add-on does not exist at the older revision.

Revision ID: h1a6_gst_credit_addon
Revises: g1a1_gst_credit
"""

from __future__ import annotations

from alembic import op

revision = "h1a6_gst_credit_addon"
down_revision = "g1a1_gst_credit"
branch_labels = None
depends_on = None

CONSTRAINT = "ck_organization_addons_key_known"
BEFORE = "addon_key IN ('addon.custom_domain', 'addon.warehouse_sync')"
AFTER = "addon_key IN ('addon.custom_domain', 'addon.warehouse_sync', 'addon.gst_credit')"


def upgrade() -> None:
    op.drop_constraint(CONSTRAINT, "organization_addons", type_="check")
    op.create_check_constraint(CONSTRAINT, "organization_addons", AFTER)


def downgrade() -> None:
    op.execute("DELETE FROM organization_addons WHERE addon_key = 'addon.gst_credit'")
    op.drop_constraint(CONSTRAINT, "organization_addons", type_="check")
    op.create_check_constraint(CONSTRAINT, "organization_addons", BEFORE)
