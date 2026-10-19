"""GST Credit (Session F): imported GSTR-2B statements and their reconciliation against the books.

  gst_returns          one imported GSTR-2B (recipient GSTIN, period). A re-import of the same GSTIN and period
                       replaces the active one and keeps the old as SUPERSEDED; the exact same file again is a
                       no-op (decided in the importer, by the file's SHA-256)
  gst_return_records   one supplier document in a return (invoice, credit or debit note, amendment, ...)
  gst_matches          the reconciliation result, rebuilt by the engine and never edited by hand
  gst_decisions        what a person decided (confirm a suggested match, "not ours", link by hand). Keyed by the
                       document's natural key, not a record id, so a re-import does not lose it
  gst_settings         per workspace: the per-head rounding tolerance

Money is in micros (millionths of a rupee). Every row carries organization_id and workspace_id with the
ARCH-41 composite keys, so PostgreSQL refuses a row that names another tenant's data. The audit vocabulary gains
GST_RETURN and GST_MATCH. Expand only: the downgrade drops the five tables (enum values cannot be removed).

Revision ID: g1a1_gst_credit
Revises: h1a5_helm_ledger_incremental
"""

from __future__ import annotations

from alembic import op

revision = "g1a1_gst_credit"
down_revision = "h1a5_helm_ledger_incremental"
branch_labels = None
depends_on = None

TS = "timestamptz NOT NULL DEFAULT now()"
WS_FK = ("CONSTRAINT fk_{table}_workspace_org FOREIGN KEY (workspace_id, organization_id) "
         "REFERENCES workspaces (id, organization_id) ON DELETE CASCADE")
STATUSES = ("MATCHED", "MATCHED_WITH_DIFFERENCES", "SUGGESTED", "WAITING_FOR_SUPPLIER", "NOT_IN_BOOKS",
            "NOT_ELIGIBLE", "REVERSE_CHARGE", "NOTE")
SECTIONS = ("b2b", "b2ba", "cdnr", "cdnra", "isd", "isda", "impg", "impgsez", "ecom", "ecoma")
KINDS = ("INVOICE", "CREDIT_NOTE", "DEBIT_NOTE", "OTHER")


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE audit_resource_type ADD VALUE IF NOT EXISTS 'GST_RETURN'")
        op.execute("ALTER TYPE audit_resource_type ADD VALUE IF NOT EXISTS 'GST_MATCH'")

    op.execute(f"""
        CREATE TABLE gst_returns (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id uuid NOT NULL REFERENCES organizations (id) ON DELETE CASCADE,
            workspace_id uuid NOT NULL,
            gstin varchar(15) NOT NULL,
            period varchar(7) NOT NULL,
            rtnprd varchar(6) NOT NULL,
            version varchar(16),
            generated_on date,
            file_sha256 varchar(64) NOT NULL,
            file_name varchar(255) NOT NULL,
            record_count integer NOT NULL DEFAULT 0,
            itc_summary jsonb NOT NULL DEFAULT '{{}}'::jsonb,
            problems jsonb NOT NULL DEFAULT '[]'::jsonb,
            status varchar(10) NOT NULL DEFAULT 'ACTIVE',
            supersedes_id uuid REFERENCES gst_returns (id) ON DELETE SET NULL,
            imported_by_user_id uuid REFERENCES users (id) ON DELETE SET NULL,
            imported_at {TS},
            created_at {TS},
            updated_at {TS},
            {WS_FK.format(table="gst_returns")},
            CONSTRAINT uq_gst_returns_id_workspace UNIQUE (id, workspace_id),
            CONSTRAINT ck_gst_returns_status CHECK (status IN ('ACTIVE', 'SUPERSEDED')),
            CONSTRAINT ck_gst_returns_count CHECK (record_count >= 0)
        )""")
    op.execute("CREATE UNIQUE INDEX uq_gst_returns_active ON gst_returns (workspace_id, gstin, period) "
               "WHERE status = 'ACTIVE'")
    op.execute("CREATE INDEX ix_gst_returns_workspace_gstin ON gst_returns (workspace_id, gstin)")
    op.execute("CREATE INDEX ix_gst_returns_organization ON gst_returns (organization_id)")

    op.execute(f"""
        CREATE TABLE gst_return_records (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id uuid NOT NULL REFERENCES organizations (id) ON DELETE CASCADE,
            workspace_id uuid NOT NULL,
            return_id uuid NOT NULL,
            gstin varchar(15) NOT NULL,
            period varchar(7) NOT NULL,
            section varchar(8) NOT NULL,
            kind varchar(12) NOT NULL,
            supplier_gstin varchar(15),
            supplier_name varchar(300),
            supplier_filed_on date,
            supplier_period varchar(12),
            doc_number varchar(64),
            doc_key varchar(64),
            doc_type varchar(8),
            doc_date date,
            value_micros bigint,
            taxable_micros bigint,
            igst_micros bigint NOT NULL DEFAULT 0,
            cgst_micros bigint NOT NULL DEFAULT 0,
            sgst_micros bigint NOT NULL DEFAULT 0,
            cess_micros bigint NOT NULL DEFAULT 0,
            place_of_supply varchar(2),
            reverse_charge boolean NOT NULL DEFAULT false,
            itc_available varchar(1),
            reason varchar(16),
            diff_percent varchar(8),
            source_type varchar(16),
            irn varchar(64),
            irn_date date,
            original_number varchar(64),
            original_key varchar(64),
            original_date date,
            raw jsonb NOT NULL DEFAULT '{{}}'::jsonb,
            created_at {TS},
            {WS_FK.format(table="gst_return_records")},
            CONSTRAINT fk_gst_return_records_return FOREIGN KEY (return_id, workspace_id)
                REFERENCES gst_returns (id, workspace_id) ON DELETE CASCADE,
            CONSTRAINT uq_gst_return_records_id_workspace UNIQUE (id, workspace_id),
            CONSTRAINT ck_gst_return_records_section CHECK (section IN ({_in(SECTIONS)})),
            CONSTRAINT ck_gst_return_records_kind CHECK (kind IN ({_in(KINDS)}))
        )""")
    op.execute("CREATE INDEX ix_gst_return_records_return ON gst_return_records (return_id)")
    op.execute("CREATE INDEX ix_gst_return_records_lookup ON gst_return_records "
               "(workspace_id, gstin, supplier_gstin, doc_key)")
    op.execute("CREATE INDEX ix_gst_return_records_irn ON gst_return_records (workspace_id, irn) WHERE irn IS NOT NULL")
    op.execute("CREATE INDEX ix_gst_return_records_organization ON gst_return_records (organization_id)")

    op.execute(f"""
        CREATE TABLE gst_matches (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id uuid NOT NULL REFERENCES organizations (id) ON DELETE CASCADE,
            workspace_id uuid NOT NULL,
            gstin varchar(15) NOT NULL,
            record_id uuid,
            work_item_id uuid,
            status varchar(24) NOT NULL,
            method varchar(10),
            supplier_gstin varchar(15),
            supplier_name varchar(300),
            doc_number varchar(64),
            doc_date date,
            value_micros bigint,
            tax_micros bigint,
            itc_micros bigint,
            differences jsonb NOT NULL DEFAULT '[]'::jsonb,
            notes jsonb NOT NULL DEFAULT '[]'::jsonb,
            ims_action varchar(8),
            ims_reason text,
            period_first_seen varchar(7),
            reported_late boolean NOT NULL DEFAULT false,
            risk jsonb,
            decision varchar(10),
            computed_at {TS},
            {WS_FK.format(table="gst_matches")},
            CONSTRAINT fk_gst_matches_record FOREIGN KEY (record_id, workspace_id)
                REFERENCES gst_return_records (id, workspace_id) ON DELETE CASCADE,
            CONSTRAINT fk_gst_matches_work_item FOREIGN KEY (work_item_id, workspace_id)
                REFERENCES work_items (id, workspace_id) ON DELETE CASCADE,
            CONSTRAINT ck_gst_matches_status CHECK (status IN ({_in(STATUSES)})),
            CONSTRAINT ck_gst_matches_side CHECK (record_id IS NOT NULL OR work_item_id IS NOT NULL),
            CONSTRAINT ck_gst_matches_ims CHECK (ims_action IS NULL OR ims_action IN ('ACCEPT', 'PENDING', 'REJECT'))
        )""")
    op.execute("CREATE UNIQUE INDEX uq_gst_matches_record ON gst_matches (workspace_id, gstin, record_id) "
               "WHERE record_id IS NOT NULL")
    op.execute("CREATE UNIQUE INDEX uq_gst_matches_work_item ON gst_matches (workspace_id, gstin, work_item_id) "
               "WHERE work_item_id IS NOT NULL")
    op.execute("CREATE INDEX ix_gst_matches_status ON gst_matches (workspace_id, gstin, status)")
    op.execute("CREATE INDEX ix_gst_matches_supplier ON gst_matches (workspace_id, gstin, supplier_gstin)")
    op.execute("CREATE INDEX ix_gst_matches_organization ON gst_matches (organization_id)")

    op.execute(f"""
        CREATE TABLE gst_decisions (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id uuid NOT NULL REFERENCES organizations (id) ON DELETE CASCADE,
            workspace_id uuid NOT NULL,
            gstin varchar(15) NOT NULL,
            supplier_gstin varchar(15) NOT NULL,
            doc_key varchar(64) NOT NULL,
            kind varchar(12) NOT NULL,
            decision varchar(10) NOT NULL,
            work_item_id uuid,
            note text,
            decided_by_user_id uuid REFERENCES users (id) ON DELETE SET NULL,
            decided_at {TS},
            {WS_FK.format(table="gst_decisions")},
            CONSTRAINT fk_gst_decisions_work_item FOREIGN KEY (work_item_id, workspace_id)
                REFERENCES work_items (id, workspace_id) ON DELETE CASCADE,
            CONSTRAINT uq_gst_decisions_document UNIQUE (workspace_id, gstin, supplier_gstin, doc_key, kind),
            CONSTRAINT ck_gst_decisions_decision CHECK (decision IN ('CONFIRM', 'NOT_OURS', 'LINK')),
            CONSTRAINT ck_gst_decisions_needs_book CHECK (decision = 'NOT_OURS' OR work_item_id IS NOT NULL)
        )""")
    op.execute("CREATE INDEX ix_gst_decisions_organization ON gst_decisions (organization_id)")

    op.execute(f"""
        CREATE TABLE gst_settings (
            workspace_id uuid PRIMARY KEY,
            organization_id uuid NOT NULL REFERENCES organizations (id) ON DELETE CASCADE,
            tolerance_micros bigint NOT NULL DEFAULT 1000000,
            updated_by_user_id uuid REFERENCES users (id) ON DELETE SET NULL,
            updated_at {TS},
            {WS_FK.format(table="gst_settings")},
            CONSTRAINT ck_gst_settings_tolerance CHECK (tolerance_micros >= 0 AND tolerance_micros <= 1000000000)
        )""")
    op.execute("CREATE INDEX ix_gst_settings_organization ON gst_settings (organization_id)")


def downgrade() -> None:
    for table in ("gst_settings", "gst_decisions", "gst_matches", "gst_return_records", "gst_returns"):
        op.execute(f"DROP TABLE IF EXISTS {table}")
