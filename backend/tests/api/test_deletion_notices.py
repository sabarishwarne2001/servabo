"""Warning emails after a workspace or organization is deleted (Final session 2A, Phase 4; N-164).

With a controlled clock: the owners and admins (and nobody else) get one email at once ("will be erased on <date>; restore
until then") and one 5 days before the erasure ("last chance"), each exactly once however often the hourly job runs; a
restore stops them, a new deletion is warned again, a relay that took nothing is retried, and nothing is sent after the
erasure date. A workspace inside a deleted organization is covered by the organization's email.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import delete, text

from app.models.audit_log import AuditAction, AuditLog, AuditResourceType
from app.models.deletion_notice_send import DeletionNoticeSend
from app.services.compliance import deletion_notices

T0 = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)


@pytest.fixture()
def outbox(monkeypatch):
    sent: list[tuple[str, str, str]] = []

    def fake_send(*, recipient, subject, html_body, text_body, reply_to=None):
        sent.append((recipient, subject, text_body))
        return True, "accepted"

    monkeypatch.setattr("app.core.platform_email.send_platform_email", fake_send)
    return sent


def _archive(db, tenant, what: str, at: datetime) -> None:
    if what == "workspace":
        db.execute(text("UPDATE workspaces SET status = 'ARCHIVED' WHERE id = :i"), {"i": tenant.workspace.id})
        kind, rid = AuditResourceType.WORKSPACE, tenant.workspace.id
    else:
        db.execute(text("UPDATE organizations SET status = 'ARCHIVED' WHERE id = :i"), {"i": tenant.organization.id})
        kind, rid = AuditResourceType.ORGANIZATION, tenant.organization.id
    db.add(AuditLog(organization_id=tenant.organization.id, workspace_id=tenant.workspace.id if what == "workspace" else None,
                    actor_id=tenant.owner.user.id, resource_type=kind, resource_id=rid, action=AuditAction.ARCHIVED,
                    details={}, created_at=at))
    db.commit()


def _to(outbox) -> set[str]:
    return {recipient for recipient, _, _ in outbox}


def test_a_deleted_workspace_is_warned_at_once_and_five_days_before_each_once(db_session, tenant, outbox) -> None:
    db_session.execute(delete(DeletionNoticeSend))
    _archive(db_session, tenant, "workspace", T0)
    first = deletion_notices.run(db_session, now=T0 + timedelta(hours=1))
    owners_and_admins = {tenant.owner.user.email, tenant.org_admin.user.email}
    assert first["warnings"] == 1 and _to(outbox) == owners_and_admins
    subject, body = outbox[0][1], outbox[0][2]
    assert "will be erased on 31 October 2026" in subject and tenant.workspace.workspace_name in subject
    assert "restore it" in body.lower() and "/workspaces" in body

    outbox.clear()
    for hours in (2, 3, 24 * 10):  # the hourly job runs on: nothing more until five days before
        assert deletion_notices.run(db_session, now=T0 + timedelta(hours=hours))["warnings"] == 0
    assert outbox == []

    last = deletion_notices.run(db_session, now=T0 + timedelta(days=25, hours=1))
    assert last["warnings"] == 1 and _to(outbox) == owners_and_admins
    assert outbox[0][1].startswith("Last chance:")
    outbox.clear()
    assert deletion_notices.run(db_session, now=T0 + timedelta(days=26))["warnings"] == 0
    assert deletion_notices.run(db_session, now=T0 + timedelta(days=31))["warnings"] == 0  # erased: nothing to restore
    assert outbox == []


def test_a_member_viewer_or_contributor_is_not_emailed(db_session, tenant, outbox) -> None:
    db_session.execute(delete(DeletionNoticeSend))
    _archive(db_session, tenant, "workspace", T0)
    deletion_notices.run(db_session, now=T0 + timedelta(hours=1))
    others = {tenant.contributor.user.email, tenant.viewer.user.email, tenant.ws_admin.user.email,
              tenant.other_org_member.user.email, tenant.non_member.user.email}
    assert not (_to(outbox) & others)


def test_a_restore_stops_the_warnings_and_a_new_deletion_is_warned_again(db_session, tenant, outbox) -> None:
    db_session.execute(delete(DeletionNoticeSend))
    _archive(db_session, tenant, "workspace", T0)
    deletion_notices.run(db_session, now=T0 + timedelta(hours=1))
    db_session.execute(text("UPDATE workspaces SET status = 'ACTIVE' WHERE id = :i"), {"i": tenant.workspace.id})
    db_session.commit()
    outbox.clear()
    assert deletion_notices.run(db_session, now=T0 + timedelta(days=26))["warnings"] == 0
    again = T0 + timedelta(days=40)
    _archive(db_session, tenant, "workspace", again)
    assert deletion_notices.run(db_session, now=again + timedelta(minutes=5))["warnings"] == 1
    assert "will be erased on 10 December 2026" in outbox[0][1]


def test_a_deleted_organization_gets_one_email_for_itself_not_one_per_workspace(db_session, tenant, outbox) -> None:
    db_session.execute(delete(DeletionNoticeSend))
    _archive(db_session, tenant, "workspace", T0)
    _archive(db_session, tenant, "organization", T0 + timedelta(minutes=1))
    result = deletion_notices.run(db_session, now=T0 + timedelta(hours=1))
    assert result["warnings"] == 1
    name = tenant.organization.legal_name or tenant.organization.name
    assert all(name in subject for _, subject, _ in outbox) and len(outbox) == 2


def test_a_deletion_found_inside_the_last_five_days_gets_only_the_last_chance(db_session, tenant, outbox) -> None:
    db_session.execute(delete(DeletionNoticeSend))
    _archive(db_session, tenant, "workspace", T0)
    assert deletion_notices.run(db_session, now=T0 + timedelta(days=27))["warnings"] == 1
    assert all(subject.startswith("Last chance:") for _, subject, _ in outbox)


def test_a_relay_that_took_nothing_is_tried_again_next_hour(db_session, tenant, monkeypatch) -> None:
    db_session.execute(delete(DeletionNoticeSend))
    _archive(db_session, tenant, "workspace", T0)
    monkeypatch.setattr("app.core.platform_email.send_platform_email", lambda **kw: (False, "refused"))
    assert deletion_notices.run(db_session, now=T0 + timedelta(hours=1))["warnings"] == 0
    sent = []
    monkeypatch.setattr("app.core.platform_email.send_platform_email", lambda **kw: sent.append(kw["recipient"]) or (True, "ok"))
    assert deletion_notices.run(db_session, now=T0 + timedelta(hours=2))["warnings"] == 1 and len(sent) == 2


def test_the_job_is_scheduled_hourly_and_claimed_by_a_worker() -> None:
    from app.workers.profiles import PROFILES
    from app.workers.scheduler import DEFAULT_SCHEDULE

    entry = next(e for e in DEFAULT_SCHEDULE if e.job_type == deletion_notices.JOB_TYPE)
    assert entry.interval_seconds == 3_600
    assert any(p.job_types and deletion_notices.JOB_TYPE in p.job_types for p in PROFILES.values())
