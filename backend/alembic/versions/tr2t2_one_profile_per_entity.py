"""One legal entity, one TRINETRA profile per organization (Final 2T, Phase 1.4).

Adds `trinetra_org_keys` (a random encrypted salt per organization) and `trinetra_profiles.org_pan_fingerprint` (the PAN
keyed with that salt) with a partial unique index. Existing profiles keep NULL until the organization next creates a
profile (the service fills them in). Downgrade drops both; nothing else depends on them.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "tr2t2_one_profile_per_entity"
down_revision = "tr2t1_evidence_fingerprints"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "trinetra_org_keys",
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                  primary_key=True),
        sa.Column("salt_ciphertext", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.add_column("trinetra_profiles", sa.Column("org_pan_fingerprint", sa.String(64), nullable=True))
    op.create_index("uq_trinetra_org_pan", "trinetra_profiles", ["organization_id", "org_pan_fingerprint"], unique=True,
                    postgresql_where=sa.text("org_pan_fingerprint IS NOT NULL"))


def downgrade():
    op.drop_index("uq_trinetra_org_pan", table_name="trinetra_profiles")
    op.drop_column("trinetra_profiles", "org_pan_fingerprint")
    op.drop_table("trinetra_org_keys")
