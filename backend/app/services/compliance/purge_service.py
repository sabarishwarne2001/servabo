"""Purging documents, and purging what an archived workspace or organization leaves behind (Final session 1, 1A, F-548).

Until this session "delete workspace" and "delete organization" only ARCHIVED: status changed, API keys were turned off,
and every document, conversation and credential stayed forever. The honest answer to the enterprise question "what
happens to our data when we leave?" was "it stays". This module makes the answer true, in two stages (N-164):

1. **Content purge, `ARCHIVED_PURGE_GRACE_DAYS` (30) after archiving.** An archived workspace (or organization) is no
   longer restorable once this runs. Documents are purged (`purge_documents`, the same path as the retention sweep:
   money records are DETACHED and kept, copies are destroyed), conversations and every table the data map marks
   `OrgPurge.DELETE` are emptied, and the stored files are removed. What stays is what the data map marks `KEEP`:
   money records (GST books, the Helm ledger, invoices and usage) and the audit trail.
2. **Final deletion, `ARCHIVED_FINAL_DELETE_MONTHS` (72) after archiving** (CGST Act 2017 s.36: books are kept until 72
   months after the due date of the annual return for their year). Only an organization is finally deleted; its row and
   everything that cascades from it go. A workspace row stays with its organization.

The operator runs it with `scripts/sweep_compliance.py --archived` (dry run unless `--apply`).
"""

from __future__ import annotations

import logging
import uuid
import warnings
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterable, Optional

import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.core.config import settings
from app.db.base import Base
from app.models.audit_log import AuditAction, AuditLog, AuditResourceType
from app.models.organization import Organization, OrganizationStatus
from app.models.workspace import Workspace, WorkspaceStatus
from app.services.compliance import document_content
from app.services.compliance.data_map import REGISTRY, OrgPurge

logger = logging.getLogger("app.services.compliance.purge")

__all__ = ["PurgeReport", "archived_at", "purge_documents", "sweep_archived"]

with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    _TABLES = dict(Base.metadata.tables)

DOCUMENT_BATCH = 200


def purge_documents(db: Session, work_item_ids: list[uuid.UUID]) -> set[str]:
    """Delete these documents the way the retention sweep does. Returns the storage keys to remove AFTER the commit.

    The original upload goes with the document (F-183), except a file a supplier invoice keeps as its source document.
    Copies of the content are destroyed and money records detached (`document_content`, mode "purge") before the rows
    are deleted, so the foreign keys find nothing to cascade into them.
    """
    from app.db import chunk_scope
    from app.models import helm_dirty
    from app.services import storage_cleanup
    from app.services.truthmesh import service as truthmesh_service

    if not work_item_ids:
        return set()
    ids = list(work_item_ids)
    files = db.execute(
        text(
            """
            SELECT uf.id, uf.file_path, wi.stored_filename
            FROM work_items wi
            JOIN uploaded_files uf ON uf.id = wi.uploaded_file_id
            WHERE wi.id = ANY(:ids) AND uf.deleted_at IS NULL
            """
        ),
        {"ids": ids},
    ).fetchall()
    keys = set(storage_cleanup.deletable_keys(db, [row.file_path for row in files]))
    for row in files:
        if row.file_path in keys and row.stored_filename:
            keys.add(row.stored_filename)
    if files:
        db.execute(text("UPDATE uploaded_files SET deleted_at = now() WHERE id = ANY(:ids)"), {"ids": [row.id for row in files]})
    # TruthMesh: the documents leave the mesh and their conflicts are resolved in the same transaction.
    by_workspace: dict[uuid.UUID, list[uuid.UUID]] = {}
    for item_id, workspace_id in db.execute(
        text("SELECT id, workspace_id FROM work_items WHERE id = ANY(:ids)"), {"ids": ids}
    ).fetchall():
        by_workspace.setdefault(workspace_id, []).append(item_id)
    for workspace_id, in_workspace in by_workspace.items():
        truthmesh_service.forget_documents(db, workspace_id=workspace_id, work_item_ids=in_workspace)
    # Helm's Promise ledger re-projects at the next update (a raw delete is not seen by the ORM).
    helm_dirty.mark_deleted(db.connection(), ids, "retention purge")
    document_content.destroy_copies(db, ids, mode="purge")
    for workspace_id, in_workspace in by_workspace.items():
        for item_id in in_workspace:
            chunk_scope.delete_chunks_for_work_item(db, workspace_id=workspace_id, work_item_id=item_id)
    db.execute(text("DELETE FROM work_items WHERE id = ANY(:ids)"), {"ids": ids})
    return keys


# ------------------------------------------------------------------------------------------ archived scopes

def archived_at(db: Session, resource_type: AuditResourceType, resource_id: uuid.UUID) -> Optional[datetime]:
    """When the organization or workspace was last archived (the audit trail is the record of it)."""
    return db.execute(
        sa.select(sa.func.max(AuditLog.created_at)).where(
            AuditLog.resource_type == resource_type,
            AuditLog.resource_id == resource_id,
            AuditLog.action == AuditAction.ARCHIVED,
        )
    ).scalar_one_or_none()


@dataclass
class PurgeReport:
    organizations: list[str] = field(default_factory=list)   # content purged
    workspaces: list[str] = field(default_factory=list)      # content purged
    finally_deleted: list[str] = field(default_factory=list)
    rows: dict[str, int] = field(default_factory=dict)
    kept_because_referenced: list[str] = field(default_factory=list)
    audit_blocked: list[str] = field(default_factory=list)   # final deletion refused: audit entries younger than 400 days remain
    storage_keys: set[str] = field(default_factory=set)

    def add(self, table: str, count: int) -> None:
        if count:
            self.rows[table] = self.rows.get(table, 0) + int(count)


def _delete_tables(db: Session, *, organization_id: uuid.UUID, workspace_ids: list[uuid.UUID], whole_organization: bool,
                   report: PurgeReport) -> None:
    """Empty every table the data map marks OrgPurge.DELETE, for this scope. Foreign keys decide the order, so a
    table that is still referenced is retried after the others and reported if it never frees up."""
    pending: list[str] = []
    for name, rule in REGISTRY.items():
        if rule.org_purge is not OrgPurge.DELETE:
            continue
        cols = _TABLES[name].c
        if "workspace_id" in cols or (whole_organization and "organization_id" in cols):
            pending.append(name)
    for _ in range(4):
        retry: list[str] = []
        for name in pending:
            table = _TABLES[name]
            conditions = []
            if "workspace_id" in table.c:
                conditions.append(table.c.workspace_id.in_(workspace_ids))
            if whole_organization and "organization_id" in table.c:
                conditions.append(table.c.organization_id == organization_id)
            try:
                with db.begin_nested():
                    result = db.execute(sa.delete(table).where(sa.or_(*conditions)))
                report.add(name, result.rowcount or 0)
            except IntegrityError:
                retry.append(name)
        if not retry:
            return
        pending = retry
    report.kept_because_referenced.extend(pending)


def _delete_audit_rows(db: Session, organization_id: uuid.UUID) -> int:
    """The organization's audit entries older than 400 days, deleted as the audit sweeper (the only path the append-only
    trigger allows; see `scripts/sweep_arch07.delete_as_sweeper`). Younger entries remain and block the final deletion
    until they too are 400 days old: the trail is never shortened by this process."""
    from scripts import sweep_arch07

    total = 0
    while True:
        deleted = sweep_arch07.delete_as_sweeper(
            db, "organization_id = :organization AND created_at < now() - interval '400 days'", {"organization": organization_id}
        )
        total += deleted
        if deleted < sweep_arch07.BATCH_SIZE:
            return total


def _purge_scope(db: Session, *, organization_id: uuid.UUID, workspace_ids: list[uuid.UUID], whole_organization: bool,
                 report: PurgeReport) -> None:
    while True:
        ids = [
            row[0]
            for row in db.execute(
                text("SELECT id FROM work_items WHERE workspace_id = ANY(:ws) LIMIT :n"),
                {"ws": workspace_ids, "n": DOCUMENT_BATCH},
            ).fetchall()
        ]
        if not ids:
            break
        report.storage_keys |= purge_documents(db, ids)
        report.add("work_items", len(ids))
    _delete_tables(db, organization_id=organization_id, workspace_ids=workspace_ids,
                   whole_organization=whole_organization, report=report)


def sweep_archived(
    session_factory: Callable[[], Session],
    *,
    apply: bool,
    now: Optional[datetime] = None,
    grace_days: Optional[int] = None,
    final_months: Optional[int] = None,
    remove_storage: Optional[Callable[[Iterable[str]], Any]] = None,
) -> PurgeReport:
    """Stage 1 and stage 2 for every archived workspace and organization that is old enough."""
    now = now or datetime.now(timezone.utc)
    grace = timedelta(days=settings.ARCHIVED_PURGE_GRACE_DAYS if grace_days is None else grace_days)
    final = timedelta(days=30 * (settings.ARCHIVED_FINAL_DELETE_MONTHS if final_months is None else final_months))
    report = PurgeReport()

    with session_factory() as db:
        archived_orgs = db.execute(sa.select(Organization).where(Organization.status == OrganizationStatus.ARCHIVED)).scalars().all()
        org_jobs: list[tuple[uuid.UUID, str, bool]] = []
        for org in archived_orgs:
            when = archived_at(db, AuditResourceType.ORGANIZATION, org.id)
            if when is None or now - when < grace:
                continue
            org_jobs.append((org.id, org.slug, now - when >= final))
        ws_jobs: list[tuple[uuid.UUID, uuid.UUID, str]] = []
        org_ids = {job[0] for job in org_jobs}
        for ws in db.execute(sa.select(Workspace).where(Workspace.status == WorkspaceStatus.ARCHIVED)).scalars().all():
            if ws.organization_id in org_ids:
                continue  # handled with its organization
            when = archived_at(db, AuditResourceType.WORKSPACE, ws.id)
            if when is not None and now - when >= grace:
                ws_jobs.append((ws.organization_id, ws.id, ws.slug))

    for organization_id, workspace_id, slug in ws_jobs:
        report.workspaces.append(slug)
        if not apply:
            continue
        with session_factory() as db:
            _purge_scope(db, organization_id=organization_id, workspace_ids=[workspace_id], whole_organization=False, report=report)
            db.commit()

    for organization_id, slug, is_final in org_jobs:
        report.organizations.append(slug)
        if is_final:
            report.finally_deleted.append(slug)
        if not apply:
            continue
        with session_factory() as db:
            workspace_ids = list(db.execute(sa.select(Workspace.id).where(Workspace.organization_id == organization_id)).scalars())
            _purge_scope(db, organization_id=organization_id, workspace_ids=workspace_ids, whole_organization=True, report=report)
            db.commit()
            if is_final:
                try:
                    with db.begin_nested():
                        _delete_audit_rows(db, organization_id)
                        db.execute(sa.delete(Organization).where(Organization.id == organization_id))
                    db.commit()
                except DBAPIError:
                    db.rollback()
                    report.audit_blocked.append(slug)

    if apply and report.storage_keys:
        if remove_storage is None:
            from app.services import storage_cleanup

            remove_storage = storage_cleanup.delete_stored_objects
        remove_storage(report.storage_keys)
    logger.info("compliance.archived_purge", extra={"organizations": len(report.organizations), "workspaces": len(report.workspaces),
                                                    "final": len(report.finally_deleted), "apply": apply})
    return report
