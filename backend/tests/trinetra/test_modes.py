"""Three modes instead of one switch (Final 2T, Phase 2.1; N-201).

off: nobody has live TRINETRA. pilot (the shipped default): only organizations a platform administrator enrolled, with a
reason, audited. on: every organization whose plan includes capability.trinetra. One helper, `mode.live_for`, decides
"is TRINETRA live for this organization", and every gate uses it: the routes, the worker, the hooks, the review event,
the Helm annotation and /access. `TRINETRA_LIVE_ENABLED` stays as an alias (true means on, false means off)."""

import uuid
from datetime import date, datetime, timezone

import pytest
from pydantic import ValidationError

from app.core.config import Settings, settings
from app.models.audit_log import AuditLog
from app.services.trinetra import mode
from tests.security.plans import put_on_plan
from tests.trinetra.test_api import world  # noqa: F401
from tests.trinetra.test_workflows import setup_case


def set_mode(monkeypatch, value):
    monkeypatch.setattr(settings, "TRINETRA_LIVE_ENABLED", None)
    monkeypatch.setattr(settings, "TRINETRA_MODE", value)


def enrol(db, tenant, reason="Pilot: the owner's own organization, for Final session 2B."):
    mode.enrol(db, organization_id=tenant.organization.id, actor_id=tenant.owner.user.id, reason=reason)
    db.commit()


@pytest.mark.no_db
def test_the_default_is_pilot_and_the_old_switch_is_an_alias(monkeypatch):
    assert Settings.model_fields["TRINETRA_MODE"].default == "pilot"
    monkeypatch.setattr(settings, "TRINETRA_LIVE_ENABLED", None)
    monkeypatch.setattr(settings, "TRINETRA_MODE", "pilot")
    assert mode.deployment_mode() == "pilot"
    monkeypatch.setattr(settings, "TRINETRA_LIVE_ENABLED", True)
    assert mode.deployment_mode() == "on"
    monkeypatch.setattr(settings, "TRINETRA_LIVE_ENABLED", False)
    assert mode.deployment_mode() == "off"
    with pytest.raises(ValidationError):
        Settings(TRINETRA_MODE="maybe", _env_file=None)


@pytest.mark.parametrize("deployment,enrolled,entitled,expected", [
    ("off", True, True, False), ("off", False, True, False),
    ("pilot", True, True, True), ("pilot", False, True, False),
    ("on", False, True, True), ("on", True, True, True),
    ("on", True, False, False), ("pilot", True, False, False), ("off", False, False, False),
])
def test_live_for_in_every_mode(db_session, tenant, monkeypatch, deployment, enrolled, entitled, expected):
    put_on_plan(db_session, tenant.organization, "business" if entitled else "developer")
    if enrolled:
        enrol(db_session, tenant)
    db_session.commit()
    set_mode(monkeypatch, deployment)
    assert mode.live_for(db_session, tenant.organization.id) is expected
    state = mode.state(db_session, tenant.organization.id)
    assert state.live is expected and state.mode == deployment and state.enrolled is enrolled


def test_every_route_gate_follows_the_mode(client, tenant, world, db_session, monkeypatch):
    url = world[0]
    body = {"name": "Synthetic Ltd", "pan": "ABCDE1234F"}
    set_mode(monkeypatch, "off")
    r = client.post(url + "/profiles", headers=tenant.owner.headers, json=body)
    assert r.status_code == 409 and "TRINETRA_SOURCE_REVIEW_REQUIRED" in r.text
    set_mode(monkeypatch, "pilot")
    r = client.post(url + "/profiles", headers=tenant.owner.headers, json=body)
    assert r.status_code == 409 and "TRINETRA_NOT_ENROLLED" in r.text
    enrol(db_session, tenant)
    assert client.post(url + "/profiles", headers=tenant.owner.headers, json=body).status_code == 200
    # Reads are gated the same way: a pilot organization that is not enrolled reads nothing live.
    set_mode(monkeypatch, "on")
    assert client.get(url + "/credits", headers=tenant.owner.headers).status_code == 200


def test_access_reports_the_mode_and_whether_this_organization_is_live(client, tenant, world, db_session, monkeypatch):
    url = world[0]
    set_mode(monkeypatch, "pilot")
    out = client.get(url + "/access", headers=tenant.viewer.headers).json()
    assert (out["mode"], out["enrolled"], out["live_enabled"], out["entitled"]) == ("pilot", False, False, True)
    enrol(db_session, tenant)
    out = client.get(url + "/access", headers=tenant.viewer.headers).json()
    assert (out["enrolled"], out["live_enabled"]) == (True, True) and out["enrolled_since"]


def test_the_worker_hooks_event_and_helm_annotation_follow_the_mode(client, tenant, world, db_session, monkeypatch):
    from app.models.job import Job
    from app.services.trinetra import hooks
    from app.workers.handlers import trinetra as handler

    url, _, case = setup_case(client, tenant, world)
    payload = {"organization_id": str(tenant.organization.id), "workspace_id": str(tenant.workspace.id)}
    set_mode(monkeypatch, "pilot")
    assert handler.handle_recompute(payload)["status"] == "blocked"
    before = db_session.query(Job).filter(Job.job_type == "trinetra.recompute").count()
    hooks.document_changed(db_session, workspace_id=tenant.workspace.id, organization_id=tenant.organization.id)
    assert db_session.query(Job).filter(Job.job_type == "trinetra.recompute").count() == before
    enrol(db_session, tenant)
    assert handler.handle_recompute(payload)["status"] == "complete"
    hooks.document_changed(db_session, workspace_id=tenant.workspace.id, organization_id=tenant.organization.id)
    assert db_session.query(Job).filter(Job.job_type == "trinetra.recompute").count() == before + 1
    set_mode(monkeypatch, "off")
    assert handler.handle_recompute(payload)["status"] == "blocked"


def test_platform_administrators_enrol_with_a_reason_and_it_is_audited(client, tenant, world, db_session, monkeypatch):
    set_mode(monkeypatch, "pilot")
    org = str(tenant.organization.id)
    path = f"/api/v1/admin/trinetra/pilot/{org}"
    # Only a platform superadmin: anyone else sees a 404.
    assert client.put(path, headers=tenant.owner.headers, json={"reason": "Not an operator, so not allowed."}).status_code == 404
    admin = tenant.org_admin
    admin.user.is_superuser = True
    db_session.commit()
    assert client.put(path, headers=admin.headers, json={"reason": "short"}).status_code == 422  # a real reason
    ok = client.put(path, headers=admin.headers, json={"reason": "The owner's own organization for the pilot."})
    assert ok.status_code == 200, ok.text
    assert mode.live_for(db_session, tenant.organization.id)
    listed = client.get("/api/v1/admin/trinetra/pilot", headers=admin.headers).json()
    assert [e["organization_id"] for e in listed["items"]] == [org] and listed["mode"] == "pilot"
    entries = db_session.query(AuditLog).filter(AuditLog.organization_id == tenant.organization.id).all()
    assert any((e.details or {}).get("operation") == "trinetra.pilot_enrolled" for e in entries)
    gone = client.post(path + "/withdraw", headers=admin.headers, json={"reason": "The pilot is finished for this organization."})
    assert gone.status_code == 200 and not mode.live_for(db_session, tenant.organization.id)
    entries = db_session.query(AuditLog).filter(AuditLog.organization_id == tenant.organization.id).all()
    assert any((e.details or {}).get("operation") == "trinetra.pilot_withdrawn" for e in entries)
