"""TRINETRA evidence reference views, gated pending source validation.

New tables and additive API-key/webhook vocabularies. Downgrade removes TRINETRA
data and subscriptions to its event; export before rollback.
"""

from alembic import op

revision = "tr1a1_credit_assurance"
down_revision = "k1a7_pack_check_dismissals"
branch_labels = None
depends_on = None


SCOPES_BEFORE = (
    "organizations:read",
    "workspaces:read",
    "workspaces:write",
    "members:read",
    "work_items:read",
    "work_items:write",
    "audit_logs:read",
    "files:read",
    "files:write",
    "webhooks:read",
    "webhooks:write",
    "webhooks:admin",
    "billing:read",
    "helm:read",
    "helm:write",
    "gst:read",
    "public_documents:read",
    "public_query:write",
    "public_workflows:read",
    "public_workflows:write",
)


def _scope_constraint(scopes):
    values = ",".join("'" + s + "'" for s in scopes)
    op.execute(
        "ALTER TABLE api_keys DROP CONSTRAINT IF EXISTS ck_api_keys_scopes_allowed"
    )
    op.execute(
        "ALTER TABLE api_keys ADD CONSTRAINT ck_api_keys_scopes_allowed CHECK (scopes <@ ARRAY["
        + values
        + "]::text[])"
    )


EVENTS_BEFORE = (
    "organization.updated",
    "member.invited",
    "member.joined",
    "member.role_changed",
    "member.deactivated",
    "member.reactivated",
    "invitation.created",
    "invitation.accepted",
    "invitation.rejected",
    "invitation.revoked",
    "invitation.expired",
    "workspace.created",
    "workspace.updated",
    "workspace.archived",
    "workspace.restored",
    "work_item.created",
    "work_item.updated",
    "work_item.deleted",
    "document.queued",
    "document.processing",
    "document.completed",
    "document.failed",
    "procurement.completed",
    "procurement.approved",
    "procurement.disputed",
    "anomaly.detected",
    "workflow.triggered",
    "helm.plan.ready",
    "helm.action.executed",
    "helm.mandate.breached",
    "gst.return.imported",
    "gst.invoice.at_risk",
    "gst.supplier.not_reported",
    "automation.run.failed",
    "automation.run.held",
)


def _events(values):
    names = ", ".join("'" + v + "'" for v in values)
    op.execute(
        "ALTER TABLE webhook_endpoints DROP CONSTRAINT ck_webhook_endpoints_event_types_vocabulary"
    )
    op.execute(
        "ALTER TABLE webhook_endpoints ADD CONSTRAINT ck_webhook_endpoints_event_types_vocabulary CHECK (event_types <@ ARRAY["
        + names
        + "]::varchar[])"
    )
    op.execute(
        "ALTER TABLE webhook_deliveries DROP CONSTRAINT ck_webhook_deliveries_event_type_vocabulary"
    )
    op.execute(
        "ALTER TABLE webhook_deliveries ADD CONSTRAINT ck_webhook_deliveries_event_type_vocabulary CHECK (event_type IN ("
        + names
        + ", 'webhook.test'))"
    )


def upgrade():
    _events(EVENTS_BEFORE + ("trinetra.case.reviewed",))
    _scope_constraint((*SCOPES_BEFORE, "trinetra:read"))
    op.execute("""
CREATE TABLE trinetra_profiles (
	name VARCHAR(120) NOT NULL,
	pan_ciphertext TEXT NOT NULL,
	identity_salt_ciphertext TEXT NOT NULL,
	pan_fingerprint VARCHAR(64) NOT NULL,
	pan_masked VARCHAR(10) NOT NULL,
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	organization_id UUID NOT NULL,
	workspace_id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_trinetra_profiles PRIMARY KEY (id),
	CONSTRAINT fk_trinetra_profiles_scope FOREIGN KEY(workspace_id, organization_id) REFERENCES workspaces (id, organization_id) ON DELETE CASCADE,
	CONSTRAINT uq_trinetra_profiles_scope UNIQUE (id, workspace_id),
	CONSTRAINT fk_trinetra_profiles_organization_id_organizations FOREIGN KEY(organization_id) REFERENCES organizations (id) ON DELETE CASCADE
)
    """)
    op.execute(
        "CREATE INDEX ix_trinetra_profiles_organization_id ON trinetra_profiles (organization_id)"
    )
    op.execute(
        "CREATE INDEX ix_trinetra_profiles_workspace_id ON trinetra_profiles (workspace_id)"
    )
    op.execute("""
CREATE TABLE trinetra_statements (
	profile_id UUID NOT NULL,
	source_work_item_id UUID NOT NULL,
	source_version VARCHAR(64) NOT NULL,
	year INTEGER NOT NULL,
	fingerprint VARCHAR(64) NOT NULL,
	parser_version VARCHAR(40) NOT NULL,
	rows JSONB NOT NULL,
	active BOOLEAN NOT NULL,
	revision INTEGER NOT NULL,
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	organization_id UUID NOT NULL,
	workspace_id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_trinetra_statements PRIMARY KEY (id),
	CONSTRAINT fk_trinetra_statements_scope FOREIGN KEY(workspace_id, organization_id) REFERENCES workspaces (id, organization_id) ON DELETE CASCADE,
	CONSTRAINT uq_trinetra_statements_scope UNIQUE (id, workspace_id),
	CONSTRAINT fk_trinetra_statements_profile_id_trinetra_profiles FOREIGN KEY(profile_id, workspace_id) REFERENCES trinetra_profiles (id, workspace_id) ON DELETE CASCADE,
	CONSTRAINT fk_trinetra_statements_source_work_item_id_work_items FOREIGN KEY(source_work_item_id, workspace_id) REFERENCES work_items (id, workspace_id) ON DELETE CASCADE,
	CONSTRAINT uq_trinetra_snapshot UNIQUE (profile_id, year, fingerprint),
	CONSTRAINT ck_trinetra_statements_ck_trinetra_statement_year CHECK (year BETWEEN 2000 AND 2100 AND revision > 0),
	CONSTRAINT fk_trinetra_statements_organization_id_organizations FOREIGN KEY(organization_id) REFERENCES organizations (id) ON DELETE CASCADE
)
    """)
    op.execute(
        "CREATE INDEX ix_trinetra_statements_organization_id ON trinetra_statements (organization_id)"
    )
    op.execute(
        "CREATE INDEX ix_trinetra_statements_workspace_id ON trinetra_statements (workspace_id)"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_trinetra_active_snapshot ON trinetra_statements (profile_id, year) WHERE active"
    )
    op.execute("""
CREATE TABLE trinetra_credits (
	profile_id UUID NOT NULL,
	work_item_id UUID NOT NULL,
	year INTEGER NOT NULL,
	counterparty VARCHAR(120) NOT NULL,
	deductor_key VARCHAR(64) NOT NULL,
	expected_micros BIGINT NOT NULL,
	reference VARCHAR(100) NOT NULL,
	source_version VARCHAR(64) NOT NULL,
	revision INTEGER NOT NULL,
	state VARCHAR(30) NOT NULL,
	review JSONB NOT NULL,
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	organization_id UUID NOT NULL,
	workspace_id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_trinetra_credits PRIMARY KEY (id),
	CONSTRAINT fk_trinetra_credits_scope FOREIGN KEY(workspace_id, organization_id) REFERENCES workspaces (id, organization_id) ON DELETE CASCADE,
	CONSTRAINT uq_trinetra_credits_scope UNIQUE (id, workspace_id),
	CONSTRAINT fk_trinetra_credits_profile_id_trinetra_profiles FOREIGN KEY(profile_id, workspace_id) REFERENCES trinetra_profiles (id, workspace_id) ON DELETE CASCADE,
	CONSTRAINT fk_trinetra_credits_work_item_id_work_items FOREIGN KEY(work_item_id, workspace_id) REFERENCES work_items (id, workspace_id) ON DELETE CASCADE,
	CONSTRAINT uq_trinetra_credit_source UNIQUE (profile_id, work_item_id, year),
	CONSTRAINT ck_trinetra_credits_ck_trinetra_credit_amount CHECK (expected_micros >= 0 AND expected_micros <= 9000000000000000 AND revision > 0),
	CONSTRAINT ck_trinetra_credits_ck_trinetra_credit_year CHECK (year BETWEEN 2000 AND 2100),
	CONSTRAINT ck_trinetra_credits_ck_trinetra_credit_state CHECK (state IN ('OPEN','DISPUTED','EXPLAINED','WITHDRAWN','CA_REVIEWED')),
	CONSTRAINT fk_trinetra_credits_organization_id_organizations FOREIGN KEY(organization_id) REFERENCES organizations (id) ON DELETE CASCADE
)
    """)
    op.execute(
        "CREATE INDEX ix_trinetra_credits_organization_id ON trinetra_credits (organization_id)"
    )
    op.execute(
        "CREATE INDEX ix_trinetra_credits_workspace_id ON trinetra_credits (workspace_id)"
    )
    op.execute("""
CREATE TABLE trinetra_decisions (
	credit_id UUID NOT NULL,
	actor_id UUID,
	revision INTEGER NOT NULL,
	action VARCHAR(30) NOT NULL,
	reason TEXT NOT NULL,
	allocations JSONB NOT NULL,
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	organization_id UUID NOT NULL,
	workspace_id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_trinetra_decisions PRIMARY KEY (id),
	CONSTRAINT fk_trinetra_decisions_scope FOREIGN KEY(workspace_id, organization_id) REFERENCES workspaces (id, organization_id) ON DELETE CASCADE,
	CONSTRAINT uq_trinetra_decisions_scope UNIQUE (id, workspace_id),
	CONSTRAINT fk_trinetra_decisions_credit_id_trinetra_credits FOREIGN KEY(credit_id, workspace_id) REFERENCES trinetra_credits (id, workspace_id) ON DELETE CASCADE,
	CONSTRAINT uq_trinetra_decision_revision UNIQUE (credit_id, revision),
	CONSTRAINT fk_trinetra_decisions_actor_id_users FOREIGN KEY(actor_id) REFERENCES users (id) ON DELETE SET NULL,
	CONSTRAINT fk_trinetra_decisions_organization_id_organizations FOREIGN KEY(organization_id) REFERENCES organizations (id) ON DELETE CASCADE
)
    """)
    op.execute(
        "CREATE INDEX ix_trinetra_decisions_organization_id ON trinetra_decisions (organization_id)"
    )
    op.execute(
        "CREATE INDEX ix_trinetra_decisions_workspace_id ON trinetra_decisions (workspace_id)"
    )


def downgrade():
    op.execute(
        "DELETE FROM webhook_deliveries WHERE event_type = 'trinetra.case.reviewed'"
    )
    op.execute(
        "DELETE FROM webhook_endpoints WHERE event_types = ARRAY['trinetra.case.reviewed']::varchar[]"
    )
    op.execute(
        "UPDATE webhook_endpoints SET event_types = array_remove(event_types, 'trinetra.case.reviewed') WHERE 'trinetra.case.reviewed'=ANY(event_types)"
    )
    _events(EVENTS_BEFORE)
    op.execute(
        "UPDATE api_keys SET scopes = array_remove(scopes, 'trinetra:read') WHERE 'trinetra:read'=ANY(scopes)"
    )
    _scope_constraint(SCOPES_BEFORE)
    op.drop_table("trinetra_decisions")
    op.drop_table("trinetra_credits")
    op.drop_table("trinetra_statements")
    op.drop_table("trinetra_profiles")
