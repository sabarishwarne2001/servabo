"""Safety jobs report their runs into the app (Final session 2A, Phase 2).

`safety_job_runs`: one row per job the host runs by cron (each sweep, the backup, the restore drill, the uptime heartbeat):
when it last started, succeeded and failed, and a short detail. The host wrappers report through
`POST /api/v1/ops/safety-jobs/{name}/runs`; the hourly `ops.safety_jobs` check compares each job's last success with its
deadline and alerts the operator. A row named `_watcher` remembers when the watching started, so "never ran" counts as
stale only after the app has been up a day. Also adds `SAFETY_JOB_STALE` to `operator_alerts.kind`.

Expand-only: a new table and one more allowed alert kind. Downgrade drops both (stale-job alerts are deleted first).

Revision ID: s2a1_safety_job_runs
Revises: tr1a2_review_outcomes
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "s2a1_safety_job_runs"
down_revision = "tr1a2_review_outcomes"
branch_labels = None
depends_on = None

_KINDS_BEFORE = ("DEAD_JOBS", "DEAD_GATEWAY_EVENTS", "SERVER_ERRORS", "DUPLICATE_SUBSCRIPTION", "PAYMENT_DISPUTED",
                 "PAYMENT_REVERSED", "HELM_LEDGER_DRIFT")
_KINDS_AFTER = (*_KINDS_BEFORE, "SAFETY_JOB_STALE")


def _alert_kinds(kinds: tuple[str, ...]) -> None:
    op.execute("ALTER TABLE operator_alerts DROP CONSTRAINT ck_operator_alerts_kind_known")
    op.execute("ALTER TABLE operator_alerts ADD CONSTRAINT ck_operator_alerts_kind_known CHECK (kind IN ("
               + ", ".join(f"'{k}'" for k in kinds) + "))")


def upgrade() -> None:
    _alert_kinds(_KINDS_AFTER)
    op.create_table(
        "safety_job_runs",
        sa.Column("name", sa.String(40), primary_key=True),
        sa.Column("last_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_failure_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_outcome", sa.String(12), nullable=True),
        sa.Column("last_detail", sa.Text(), nullable=True),
        sa.Column("reports", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("last_outcome IS NULL OR last_outcome IN ('STARTED', 'SUCCEEDED', 'FAILED')",
                           name="ck_safety_job_runs_outcome"),
    )


def downgrade() -> None:
    op.drop_table("safety_job_runs")
    op.execute("DELETE FROM operator_alerts WHERE kind = 'SAFETY_JOB_STALE'")
    _alert_kinds(_KINDS_BEFORE)
