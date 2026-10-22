"""Importing a GSTR-2B: parse, replace the active return of that GSTIN and period (keeping history), store the
records, audit it and reconcile.

Re-importing the same GSTIN and period replaces the active return and keeps the old one as SUPERSEDED. The exact
same file again (same SHA-256) is a no-op. Every record is stored with a bounded raw copy.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.audit_log import AuditAction, AuditResourceType
from app.models.gst import GstReturn, GstReturnRecord
from app.models.workspace import Workspace
from app.services import audit_service
from app.services.gst import bulk, engine, parse
from app.services.gst.gcpause import collector_paused
from app.services.gst import vocabulary as v

IMPORTED = "IMPORTED"
REPLACED = "REPLACED"
UNCHANGED = "UNCHANGED"


def _record_row(parsed: parse.ParsedRecord, *, workspace: Workspace, return_id: uuid.UUID, gstin: str,
                period: str) -> dict[str, Any]:
    data = asdict(parsed)
    data.pop("number_key")
    return {
        "id": uuid.uuid4(), "organization_id": workspace.organization_id, "workspace_id": workspace.id,
        "return_id": return_id, "gstin": gstin, "period": period, "doc_number": data.pop("number"),
        "doc_key": parsed.number_key, "supplier_filed_on": data.pop("supplier_filed_on"), **data,
    }


def import_parsed(db: Session, *, workspace: Workspace, parsed: parse.ParsedReturn, user_id: Optional[uuid.UUID],
                  ) -> dict[str, Any]:
    existing = db.execute(select(GstReturn).where(
        GstReturn.workspace_id == workspace.id, GstReturn.gstin == parsed.gstin, GstReturn.period == parsed.period,
        GstReturn.status == v.RETURN_ACTIVE)).scalar_one_or_none()
    result: dict[str, Any] = {
        "gstin": parsed.gstin, "period": parsed.period, "version": parsed.version,
        "generated_on": parsed.generated_on.isoformat() if parsed.generated_on else None,
        "file_name": parsed.file_name, "record_count": len(parsed.records), "counts": parsed.counts(),
        "problems": [{"code": p.code, "message": p.message, "count": p.count, "examples": p.examples}
                     for p in parsed.problems],
    }
    if existing is not None and existing.file_sha256 == parsed.sha256:
        return {**result, "status": UNCHANGED, "return_id": str(existing.id),
                "message": "This exact file was already imported; nothing changed."}
    status = IMPORTED
    supersedes: Optional[uuid.UUID] = None
    if existing is not None:
        existing.status = v.RETURN_SUPERSEDED
        supersedes = existing.id
        status = REPLACED
        db.flush()
    created = GstReturn(
        organization_id=workspace.organization_id, workspace_id=workspace.id, gstin=parsed.gstin, period=parsed.period,
        rtnprd=parsed.rtnprd, version=parsed.version, generated_on=parsed.generated_on, file_sha256=parsed.sha256,
        file_name=parsed.file_name, record_count=len(parsed.records), itc_summary=parsed.itc_summary,
        problems=result["problems"], status=v.RETURN_ACTIVE, supersedes_id=supersedes, imported_by_user_id=user_id)
    db.add(created)
    db.flush()
    rows = [_record_row(r, workspace=workspace, return_id=created.id, gstin=parsed.gstin, period=parsed.period)
            for r in parsed.records]
    bulk.insert_rows(db, GstReturnRecord, rows)
    audit_service.record(
        db, organization_id=workspace.organization_id, workspace_id=workspace.id, actor_id=user_id,
        resource_type=AuditResourceType.GST_RETURN, resource_id=created.id, action=AuditAction.CREATED,
        details={"gstin": parsed.gstin, "period": parsed.period, "records": len(rows), "file_sha256": parsed.sha256,
                 "replaced": supersedes is not None, "problems": len(parsed.problems)})
    engine.recompute(db, workspace, parsed.gstin)
    from app.services.automation import emitters

    emitters.gst_return_imported(db, workspace=workspace, gstin=parsed.gstin, period=parsed.period,
                                 return_id=created.id, records=len(rows), replaced=supersedes is not None)
    from app.services.gst import notices

    notices.import_finished(db, workspace=workspace, return_id=created.id, gstin=parsed.gstin, period=parsed.period, records=len(rows))
    return {**result, "status": status, "return_id": str(created.id),
            "message": ("Replaced the earlier import of this period." if status == REPLACED else "Imported.")}


def import_file(db: Session, *, workspace: Workspace, user_id: Optional[uuid.UUID], file_name: str,
                data: bytes) -> list[dict[str, Any]]:
    """Import an uploaded `.json` or `.zip`. Raises `parse.ReturnFileError` (a sentence a person can act on)."""
    with collector_paused():  # a return is tens of thousands of small objects and no cycles: see gcpause.py
        return [import_parsed(db, workspace=workspace, parsed=parsed, user_id=user_id)
                for parsed in parse.parse_file(file_name, data)]


__all__ = ["IMPORTED", "REPLACED", "UNCHANGED", "import_file", "import_parsed"]
