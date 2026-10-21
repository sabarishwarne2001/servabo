"""Automation safe at volume (Session J, Phase 4).

Expand-only:

1. Three new terminal execution statuses, so a run that was held back is a visible row in Run history and never a silent
   drop: SKIPPED_THROTTLED (the rule hit its runs-per-hour limit), SKIPPED_COOLDOWN (the rule already ran for this
   document inside its cooldown) and SKIPPED_PAUSED (the workspace's automations are paused). The terminal-status CHECK
   is rebuilt to include them.
2. Per-rule settings: `max_runs_per_hour` (NULL = the workspace default), `cooldown_hours` (NULL = off) and
   `throttle_notified_at` (the owner is told once a day at most).
3. The workspace pause switch: `automations_paused_at` and `automations_paused_by_user_id`.
4. `automation_executions.retry_of_id`: a retried run points at the run it retries.
5. `automation_rule_versions`: every save of a rule writes a snapshot (who, when, a note), for the history and Restore.

Postgres cannot drop an enum value, so the downgrade deletes the skipped rows and restores the narrower CHECK but leaves
the three enum labels in place (unused, harmless; `ADD VALUE IF NOT EXISTS` makes the next upgrade a no-op for them).

Revision ID: j1a3_automation_volume_safety
Revises: j1a2_automation_actions
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "j1a3_automation_volume_safety"
down_revision = "j1a2_automation_actions"
branch_labels = None
depends_on = None

_OLD_TERMINAL = ("COMPLETED", "FAILED", "TIMED_OUT", "SUPPRESSED_CYCLE", "SUPPRESSED_DEPTH", "BUDGET_EXHAUSTED")
_NEW_STATUSES = ("SKIPPED_THROTTLED", "SKIPPED_COOLDOWN", "SKIPPED_PAUSED")
_CHECK = "ck_automation_executions_completed_at_matches_status"


def _terminal_check(statuses: tuple[str, ...]) -> str:
    listed = ", ".join(f"'{s}'" for s in statuses)
    return f"(status IN ({listed})) = (completed_at IS NOT NULL)"


def upgrade() -> None:
    with op.get_context().autocommit_block():
        for value in _NEW_STATUSES:
            op.execute(f"ALTER TYPE automation_execution_status ADD VALUE IF NOT EXISTS '{value}'")

    op.drop_constraint(_CHECK, "automation_executions", type_="check")
    op.create_check_constraint(_CHECK, "automation_executions", _terminal_check(_OLD_TERMINAL + _NEW_STATUSES))

    op.add_column("automation_rules", sa.Column("max_runs_per_hour", sa.Integer(), nullable=True))
    op.add_column("automation_rules", sa.Column("cooldown_hours", sa.Integer(), nullable=True))
    op.add_column("automation_rules", sa.Column("throttle_notified_at", sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint(
        "ck_automation_rules_max_runs_per_hour_bounded", "automation_rules",
        "max_runs_per_hour IS NULL OR (max_runs_per_hour >= 1 AND max_runs_per_hour <= 100000)",
    )
    op.create_check_constraint(
        "ck_automation_rules_cooldown_hours_bounded", "automation_rules",
        "cooldown_hours IS NULL OR (cooldown_hours >= 1 AND cooldown_hours <= 8760)",
    )

    op.add_column("workspaces", sa.Column("automations_paused_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "workspaces",
        sa.Column("automations_paused_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_workspaces_automations_paused_by_user", "workspaces", "users",
        ["automations_paused_by_user_id"], ["id"], ondelete="SET NULL",
    )

    op.add_column("automation_executions", sa.Column("retry_of_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_automation_executions_retry_of", "automation_executions", "automation_executions",
        ["retry_of_id"], ["id"], ondelete="SET NULL",
    )
    op.create_index(
        "ix_automation_executions_rule_work_item_created", "automation_executions",
        ["rule_id", "work_item_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_automation_executions_rule_created", "automation_executions",
        ["rule_id", sa.text("created_at DESC")],
    )

    op.create_table(
        "automation_rule_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("rule_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("automation_rules.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("note", sa.String(200), nullable=False, server_default=""),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("restored_from_version", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("rule_id", "version", name="uq_automation_rule_versions_rule_version"),
        sa.CheckConstraint("version >= 1", name="ck_automation_rule_versions_version_positive"),
        sa.CheckConstraint("jsonb_typeof(snapshot) = 'object'", name="ck_automation_rule_versions_snapshot_is_object"),
    )
    op.create_index("ix_automation_rule_versions_workspace", "automation_rule_versions", ["workspace_id"])


def downgrade() -> None:
    op.drop_index("ix_automation_rule_versions_workspace", table_name="automation_rule_versions")
    op.drop_table("automation_rule_versions")

    op.drop_index("ix_automation_executions_rule_created", table_name="automation_executions")
    op.drop_index("ix_automation_executions_rule_work_item_created", table_name="automation_executions")
    op.drop_constraint("fk_automation_executions_retry_of", "automation_executions", type_="foreignkey")
    op.drop_column("automation_executions", "retry_of_id")

    op.drop_constraint("fk_workspaces_automations_paused_by_user", "workspaces", type_="foreignkey")
    op.drop_column("workspaces", "automations_paused_by_user_id")
    op.drop_column("workspaces", "automations_paused_at")

    op.drop_constraint("ck_automation_rules_cooldown_hours_bounded", "automation_rules", type_="check")
    op.drop_constraint("ck_automation_rules_max_runs_per_hour_bounded", "automation_rules", type_="check")
    op.drop_column("automation_rules", "throttle_notified_at")
    op.drop_column("automation_rules", "cooldown_hours")
    op.drop_column("automation_rules", "max_runs_per_hour")

    # The runs that were held back go; the narrower CHECK would refuse them.
    op.execute(
        "DELETE FROM automation_executions WHERE status::text IN ("
        + ", ".join(f"'{s}'" for s in _NEW_STATUSES) + ")"
    )
    op.drop_constraint(_CHECK, "automation_executions", type_="check")
    op.create_check_constraint(_CHECK, "automation_executions", _terminal_check(_OLD_TERMINAL))
