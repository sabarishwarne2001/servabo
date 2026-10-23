"""Deleting a workspace or an organization eventually deletes its data (Final session 1, 1A, F-548).

Before this, "delete" only archived: the documents, files and conversations stayed forever. Now a workspace or
organization archived more than 30 days ago is purged by `sweep_compliance.py --archived`, its money records and audit
trail stay, and an organization archived 72 months ago is deleted.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text
from sqlalchemy.orm import sessionmaker

from app.core.storage import get_storage_driver
from app.models.assistant import Conversation
from app.models.audit_log import AuditAction, AuditLog, AuditResourceType
from app.models.gst import GstMatch, GstReturn, GstReturnRecord
from app.models.organization import Organization, OrganizationStatus
from app.models.uploaded_file import UploadedFile
from app.models.work_item import WorkItem
from app.models.workspace import Workspace, WorkspaceStatus
from app.services.compliance import purge_service
from tests.engines.conftest import Engines

PAGE = ["TAX INVOICE", "Sahyadri Packaging, INV-2048, total INR 1,48,000.00"]


def _archive(engines: Engines, *, days_ago: int, what: str) -> None:
    when = datetime.now(timezone.utc) - timedelta(days=days_ago)
    if what == "workspace":
        engines.db.execute(text("UPDATE workspaces SET status = 'ARCHIVED' WHERE id = :i"), {"i": engines.ws})
        resource_type, resource_id = AuditResourceType.WORKSPACE, engines.ws
    else:
        engines.db.execute(text("UPDATE organizations SET status = 'ARCHIVED' WHERE id = :i"), {"i": engines.org})
        resource_type, resource_id = AuditResourceType.ORGANIZATION, engines.org
    engines.db.add(AuditLog(organization_id=engines.org, workspace_id=engines.ws if what == "workspace" else None,
                            actor_id=engines.tenant.owner.user.id, resource_type=resource_type, resource_id=resource_id,
                            action=AuditAction.ARCHIVED, details={}, created_at=when))
    engines.db.commit()


def _seed(engines: Engines):
    work_item_id = engines.process("inv-2048.pdf", [PAGE])
    item = engines.item(work_item_id)
    record = engines.db.execute(select(UploadedFile).where(UploadedFile.id == item.uploaded_file_id)).scalar_one()
    key = record.file_path
    ret = GstReturn(organization_id=engines.org, workspace_id=engines.ws, gstin="27AAAAA0000A1Z5", period="2026-09", rtnprd="092026",
                    file_sha256="0" * 64, file_name="r.json")
    engines.db.add(ret)
    engines.db.flush()
    from app.models.gst import GstReturnRecord as Rec

    rec = Rec(organization_id=engines.org, workspace_id=engines.ws, return_id=ret.id, gstin="27AAAAA0000A1Z5", period="2026-09",
              section="b2b", kind="INVOICE", supplier_gstin="29BBBBB1111B1Z6", supplier_name="Sahyadri Packaging", doc_number="INV-2048")
    engines.db.add(rec)
    engines.db.flush()
    match = GstMatch(organization_id=engines.org, workspace_id=engines.ws, gstin="27AAAAA0000A1Z5", status="MATCHED", record_id=rec.id,
                     work_item_id=work_item_id, supplier_gstin="29BBBBB1111B1Z6", doc_number="INV-2048", itc_micros=1_000_000)
    engines.db.add(match)
    conversation = Conversation(workspace_id=engines.ws, user_id=engines.tenant.owner.user.id, title="About INV-2048")
    engines.db.add(conversation)
    engines.db.commit()
    return work_item_id, key, match.id, conversation.id


def _factory(engines: Engines):
    return sessionmaker(bind=engines.db.get_bind())


def test_an_archived_workspace_is_purged_after_the_grace_period_and_keeps_its_money_records(engines: Engines) -> None:
    work_item_id, key, match_id, conversation_id = _seed(engines)
    driver = get_storage_driver()
    assert driver.exists(key)
    _archive(engines, days_ago=31, what="workspace")

    report = purge_service.sweep_archived(_factory(engines), apply=True)

    engines.db.expire_all()
    assert report.workspaces
    assert engines.db.get(WorkItem, work_item_id) is None, "the document is gone"
    assert engines.db.get(Conversation, conversation_id) is None, "and the conversation"
    assert not driver.exists(key), "and the stored original"
    kept = engines.db.get(GstMatch, match_id)
    assert kept is not None and kept.work_item_id is None and kept.itc_micros == 1_000_000, "the money record stays, detached"
    assert engines.db.execute(select(GstReturnRecord)).scalars().first() is not None, "the books stay"
    assert engines.db.get(Workspace, engines.ws).status == WorkspaceStatus.ARCHIVED
    assert engines.db.execute(select(AuditLog).where(AuditLog.action == AuditAction.ARCHIVED)).scalars().first() is not None


def test_an_archived_workspace_inside_the_grace_period_is_left_alone(engines: Engines) -> None:
    work_item_id, key, _match, conversation_id = _seed(engines)
    _archive(engines, days_ago=10, what="workspace")

    report = purge_service.sweep_archived(_factory(engines), apply=True)

    engines.db.expire_all()
    assert report.workspaces == [] and engines.db.get(WorkItem, work_item_id) is not None
    assert get_storage_driver().exists(key), "it can still be restored"


def test_a_dry_run_changes_nothing(engines: Engines) -> None:
    work_item_id, key, _match, _conv = _seed(engines)
    _archive(engines, days_ago=40, what="workspace")

    report = purge_service.sweep_archived(_factory(engines), apply=False)

    engines.db.expire_all()
    assert report.workspaces, "it says what it would do"
    assert engines.db.get(WorkItem, work_item_id) is not None and get_storage_driver().exists(key)


def test_an_archived_organization_keeps_its_books_inside_72_months(engines: Engines) -> None:
    work_item_id, key, match_id, _conv = _seed(engines)
    _archive(engines, days_ago=60, what="organization")
    report = purge_service.sweep_archived(_factory(engines), apply=True)
    engines.db.expire_all()
    assert report.organizations and not report.finally_deleted
    assert engines.db.get(WorkItem, work_item_id) is None and not get_storage_driver().exists(key)
    assert engines.db.get(GstMatch, match_id) is not None, "the books stay for 72 months (CGST Act s.36)"
    assert engines.db.get(Organization, engines.org) is not None


def _old_organization(engines: Engines) -> uuid.UUID:
    """An organization whose whole trail is older than 400 days, archived 73 months ago."""
    suffix = uuid.uuid4().hex[:8]
    org = Organization(slug=f"old-{suffix}", name="Old Ltd", status=OrganizationStatus.ARCHIVED)
    engines.db.add(org)
    engines.db.flush()
    engines.db.add(Workspace(organization_id=org.id, slug=f"old-ws-{suffix}", workspace_name="Old", status=WorkspaceStatus.ARCHIVED))
    long_ago = datetime.now(timezone.utc) - timedelta(days=30 * 73)
    for action in (AuditAction.CREATED, AuditAction.ARCHIVED):
        engines.db.add(AuditLog(organization_id=org.id, actor_id=engines.tenant.owner.user.id, resource_type=AuditResourceType.ORGANIZATION,
                                resource_id=org.id, action=action, details={}, created_at=long_ago))
    engines.db.commit()
    return org.id


def test_an_organization_archived_72_months_ago_is_deleted(engines: Engines) -> None:
    org_id = _old_organization(engines)
    report = purge_service.sweep_archived(_factory(engines), apply=True)
    engines.db.expire_all()
    assert "old-" in "".join(report.finally_deleted)
    assert engines.db.get(Organization, org_id) is None


def test_final_deletion_never_shortens_the_audit_trail(engines: Engines) -> None:
    """Entries younger than 400 days block the deletion rather than being deleted: the trail's own rule wins."""
    _seed(engines)
    _archive(engines, days_ago=30 * 73, what="organization")
    report = purge_service.sweep_archived(_factory(engines), apply=True)
    engines.db.expire_all()
    assert report.audit_blocked
    assert engines.db.get(Organization, engines.org) is not None
