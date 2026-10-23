"""Email-in (Final session 1, 2B): addresses, allowed senders, arrived messages and where a document came from.

Four new tables, all expand-only. Every row carries the organization and workspace with the composite key every tenant table
uses, so a row can never name another tenant's workspace. `work_item_sources` is keyed by the document (one source each) and
cascades with it. Downgrade drops the four tables.

Revision ID: k1a3_inbound_email
Revises: k1a2_batch_skipped_files
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "k1a3_inbound_email"
down_revision = "k1a2_batch_skipped_files"
branch_labels = None
depends_on = None


def _id() -> sa.Column:
    return sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()"))


def _org() -> sa.Column:
    return sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)


def _ws() -> sa.Column:
    return sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False)


def _ws_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["workspace_id", "organization_id"], ["workspaces.id", "workspaces.organization_id"],
        name=f"fk_{table}_workspace_org", ondelete="CASCADE",
    )


def _user(name: str = "created_by_user_id") -> sa.Column:
    return sa.Column(name, postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


def _now() -> sa.Column:
    return sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())


def upgrade() -> None:
    op.create_table(
        "inbound_email_addresses", _id(), _org(), _ws(),
        sa.Column("token", sa.String(64), nullable=False), _user(), _now(),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        _ws_fk("inbound_email_addresses"),
        sa.UniqueConstraint("token", name="uq_inbound_email_addresses_token"),
    )
    op.create_index(
        "uq_inbound_email_addresses_active", "inbound_email_addresses", ["workspace_id"], unique=True,
        postgresql_where=sa.text("retired_at IS NULL"),
    )

    op.create_table(
        "inbound_email_senders", _id(), _org(), _ws(), sa.Column("pattern", sa.String(255), nullable=False), _user(), _now(),
        _ws_fk("inbound_email_senders"),
        sa.UniqueConstraint("workspace_id", "pattern", name="uq_inbound_email_senders_pattern"),
    )

    op.create_table(
        "inbound_messages", _id(), _org(), _ws(),
        sa.Column("message_id", sa.String(200), nullable=False),
        sa.Column("from_address", sa.String(320), nullable=False),
        sa.Column("from_name", sa.String(200), nullable=True),
        sa.Column("subject", sa.String(500), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("hold_code", sa.String(32), nullable=True),
        sa.Column("hold_message", sa.Text(), nullable=True),
        sa.Column("attachments", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("work_item_ids", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        _user("decided_by_user_id"),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        _now(),
        _ws_fk("inbound_messages"),
        sa.UniqueConstraint("workspace_id", "message_id", name="uq_inbound_messages_message"),
        sa.CheckConstraint("status IN ('ACCEPTED', 'HELD', 'DISCARDED')", name="ck_inbound_messages_status"),
        sa.CheckConstraint("jsonb_typeof(attachments) = 'array'", name="ck_inbound_messages_attachments_list"),
        sa.CheckConstraint("jsonb_typeof(work_item_ids) = 'array'", name="ck_inbound_messages_work_items_list"),
    )
    op.create_index("ix_inbound_messages_workspace_received", "inbound_messages", ["workspace_id", "received_at"])

    op.create_table(
        "work_item_sources",
        sa.Column("work_item_id", postgresql.UUID(as_uuid=True), primary_key=True),
        _org(), _ws(),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("sender", sa.String(320), nullable=True),
        sa.Column("subject", sa.String(500), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("inbound_message_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("inbound_messages.id", ondelete="SET NULL"), nullable=True),
        _now(),
        sa.ForeignKeyConstraint(
            ["work_item_id", "workspace_id"], ["work_items.id", "work_items.workspace_id"],
            name="fk_work_item_sources_work_item", ondelete="CASCADE",
        ),
        _ws_fk("work_item_sources"),
        sa.CheckConstraint("kind IN ('EMAIL')", name="ck_work_item_sources_kind"),
    )


def downgrade() -> None:
    op.drop_table("work_item_sources")
    op.drop_index("ix_inbound_messages_workspace_received", table_name="inbound_messages")
    op.drop_table("inbound_messages")
    op.drop_table("inbound_email_senders")
    op.drop_index("uq_inbound_email_addresses_active", table_name="inbound_email_addresses")
    op.drop_table("inbound_email_addresses")
