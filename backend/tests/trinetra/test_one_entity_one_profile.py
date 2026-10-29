"""One legal entity, one profile, per organization (Final 2T, Phase 1.4).

The same PAN cannot have a profile in a second workspace of one organization (the same government posting could otherwise
be allocated once in each, counting a credit twice). The comparison uses an organization-level keyed fingerprint and never
decrypts another workspace's PAN. A shared profile across workspaces is the later option (docs/trinetra/ARCHITECTURE.md)."""

import uuid

from sqlalchemy import text

from app.core import encryption
from app.models.trinetra import TrinetraOrgKey, TrinetraProfile
from app.models.workspace import Workspace, WorkspaceMember, WorkspaceRole, MembershipStatus, WorkspaceStatus
from tests.security.plans import put_on_plan
from tests.trinetra.test_api import world  # noqa: F401


def second_workspace(db, tenant, name="Finance"):
    w = Workspace(organization_id=tenant.organization.id, slug=name.lower(), workspace_name=name,
                  status=WorkspaceStatus.ACTIVE)
    db.add(w)
    db.flush()
    db.add(WorkspaceMember(workspace_id=w.id, user_id=tenant.owner.user.id, role=WorkspaceRole.ADMIN,
                           status=MembershipStatus.ACTIVE))
    db.commit()
    return w


def make(client, tenant, workspace_id, pan="ABCDE1234F", name="Synthetic Ltd"):
    return client.post(f"/api/v1/workspaces/{workspace_id}/trinetra/profiles", headers=tenant.owner.headers,
                       json={"name": name, "pan": pan})


def test_a_second_workspace_cannot_profile_the_same_pan_and_the_refusal_names_the_workspace(client, tenant, world, db_session):
    other = second_workspace(db_session, tenant)
    assert make(client, tenant, tenant.workspace.id).status_code == 200
    refused = make(client, tenant, other.id)
    assert refused.status_code == 409, refused.text
    assert "Engineering" in refused.text and "ABCDE1234F" not in refused.text
    # A different PAN is a different legal entity.
    assert make(client, tenant, other.id, pan="AABCS5555K", name="Another Ltd").status_code == 200
    # Within the first workspace the same PAN still returns its existing profile.
    again = make(client, tenant, tenant.workspace.id)
    assert again.status_code == 200 and db_session.query(TrinetraProfile).count() == 2


def test_the_comparison_never_decrypts_another_workspaces_pan(client, tenant, world, db_session, monkeypatch):
    other = second_workspace(db_session, tenant)
    assert make(client, tenant, tenant.workspace.id).status_code == 200
    first = db_session.query(TrinetraProfile).one()
    real = encryption.decrypt_secret
    seen = []

    def spy(token, *a, **k):
        seen.append(token)
        return real(token, *a, **k)

    monkeypatch.setattr(encryption, "decrypt_secret", spy)
    assert make(client, tenant, other.id).status_code == 409
    assert first.pan_ciphertext not in seen


def test_a_profile_made_before_the_fingerprint_existed_is_still_found(client, tenant, world, db_session):
    other = second_workspace(db_session, tenant)
    assert make(client, tenant, tenant.workspace.id).status_code == 200
    db_session.execute(text("UPDATE trinetra_profiles SET org_pan_fingerprint = NULL"))
    db_session.commit()
    assert make(client, tenant, other.id).status_code == 409
    assert db_session.query(TrinetraProfile).filter(TrinetraProfile.org_pan_fingerprint.isnot(None)).count() == 1


def test_another_organization_may_profile_the_same_pan_and_the_key_is_encrypted(client, tenant, world, db_session):
    assert make(client, tenant, tenant.workspace.id).status_code == 200
    put_on_plan(db_session, tenant.other_org_member.organization if hasattr(tenant.other_org_member, "organization")
                else db_session.get(type(tenant.organization), tenant.foreign_workspace.organization_id), "business")
    db_session.commit()
    ok = client.post(f"/api/v1/workspaces/{tenant.foreign_workspace.id}/trinetra/profiles",
                     headers=tenant.other_org_member.headers, json={"name": "Synthetic Ltd", "pan": "ABCDE1234F"})
    # (409 here would be the deployment gate; the point is that it is not the duplicate refusal.)
    assert "already has a profile" not in ok.text
    keys = db_session.query(TrinetraOrgKey).all()
    assert keys and all(k.salt_ciphertext and len(encryption.decrypt_secret(k.salt_ciphertext)) == 64 for k in keys)
    fingerprints = [p.org_pan_fingerprint for p in db_session.query(TrinetraProfile).all()]
    assert len(set(fingerprints)) == len(fingerprints)  # the same PAN differs across organizations
