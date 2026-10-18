"""Helm: the Promise ledger updates incrementally (Session B).

  helm_ledger_state   one row per workspace the ledger is built for: the day its promises were computed
                      for (`as_of`), when that build started, how many incremental updates ran since,
                      and two counters for "the next update must be a full one" (`full_requests` is
                      raised by a change that cannot be attributed to documents, such as a change of
                      "who we are"; `full_served` is the value a full build read before it began; a
                      request raised while a build ran is therefore never lost). The last nightly
                      check's time and mismatch count are kept for the operator
  helm_ledger_dirty   the documents (and the payments settled on them) changed since the ledger was last
                      updated: the next update re-projects these and what depends on them, nothing else.
                      `marks` counts the changes, so an update clears only the changes it saw; `claims`
                      and `numbers` remember what the stored promises of the document said when it
                      was first marked (the amounts it could have taken a bank line for, its invoice
                      number), because a deleted document takes its promises with it and the invoices
                      that competed with it for a bank line still have to be found. No
                      foreign key to the document on purpose: a deleted document's id must survive its
                      deletion, because what it was part of (a credit note's invoice, a statement's
                      matches, a receipt's purchase order) has to be re-projected too

The operator alert kinds gain HELM_LEDGER_DRIFT: the nightly check found stored promises that a full
recomputation does not produce.

Before this, every change to one document recomputed the whole workspace (2.9 s at 10,000 documents,
budget 1 s). Expand only; the downgrade drops both tables, after which every update is a full rebuild
again, as before.

Revision ID: h1a5_helm_ledger_incremental
Revises: b1a1_pan_card_phrase
"""

from __future__ import annotations

from alembic import op

revision = "h1a5_helm_ledger_incremental"
down_revision = "b1a1_pan_card_phrase"
branch_labels = None
depends_on = None

TS = "timestamptz NOT NULL DEFAULT now()"
WORKSPACE_FK = ("CONSTRAINT fk_{table}_workspace_org FOREIGN KEY (workspace_id, organization_id) "
                "REFERENCES workspaces (id, organization_id) ON DELETE CASCADE")


_KINDS_BEFORE = ("DEAD_JOBS", "DEAD_GATEWAY_EVENTS", "SERVER_ERRORS", "DUPLICATE_SUBSCRIPTION",
                 "PAYMENT_DISPUTED", "PAYMENT_REVERSED")
_KINDS_AFTER = _KINDS_BEFORE + ("HELM_LEDGER_DRIFT",)


def _alert_kinds(kinds: tuple[str, ...]) -> None:
    op.execute("ALTER TABLE operator_alerts DROP CONSTRAINT ck_operator_alerts_kind_known")
    op.execute("ALTER TABLE operator_alerts ADD CONSTRAINT ck_operator_alerts_kind_known CHECK (kind IN ("
               + ", ".join(f"'{k}'" for k in kinds) + "))")


def upgrade() -> None:
    _alert_kinds(_KINDS_AFTER)
    op.execute(
        f"""
        CREATE TABLE helm_ledger_state (
            workspace_id uuid PRIMARY KEY,
            organization_id uuid NOT NULL,
            as_of date,
            built_at timestamptz,
            full_requests bigint NOT NULL DEFAULT 0,
            full_served bigint NOT NULL DEFAULT 0,
            incremental_runs integer NOT NULL DEFAULT 0,
            checked_at timestamptz,
            check_mismatches integer NOT NULL DEFAULT 0,
            created_at {TS},
            updated_at {TS},
            {WORKSPACE_FK.format(table="helm_ledger_state")},
            CONSTRAINT ck_helm_ledger_state_runs CHECK (incremental_runs >= 0 AND check_mismatches >= 0 AND full_requests >= 0 AND full_served >= 0)
        )
        """
    )
    op.execute("CREATE INDEX ix_helm_ledger_state_organization ON helm_ledger_state (organization_id)")
    op.execute(
        f"""
        CREATE TABLE helm_ledger_dirty (
            workspace_id uuid NOT NULL,
            organization_id uuid NOT NULL,
            work_item_id uuid NOT NULL,
            reason varchar(60) NOT NULL,
            marks integer NOT NULL DEFAULT 1,
            claims bigint[] NOT NULL DEFAULT '{{}}',
            numbers text[] NOT NULL DEFAULT '{{}}',
            marked_at {TS},
            CONSTRAINT pk_helm_ledger_dirty PRIMARY KEY (workspace_id, work_item_id),
            {WORKSPACE_FK.format(table="helm_ledger_dirty")}
        )
        """
    )
    op.execute("CREATE INDEX ix_helm_ledger_dirty_organization ON helm_ledger_dirty (organization_id)")
    # "Which promises were fulfilled by this document?" (a credit note's invoice, a receipt's order, an
    # invoice's price line): how an update finds what a changed or deleted document was part of.
    op.execute("CREATE INDEX ix_helm_promises_fulfilments ON helm_promises USING gin (fulfilments jsonb_path_ops)")


def downgrade() -> None:
    op.execute("DELETE FROM operator_alerts WHERE kind = 'HELM_LEDGER_DRIFT'")
    _alert_kinds(_KINDS_BEFORE)
    op.execute("DROP INDEX IF EXISTS ix_helm_promises_fulfilments")
    op.execute("DROP TABLE IF EXISTS helm_ledger_dirty")
    op.execute("DROP TABLE IF EXISTS helm_ledger_state")
