"""GST Credit's API (docs/product/GST-CREDIT.md). Workspace-scoped; every route is a plain `def`.

    POST   /workspaces/{wid}/gst/returns                       import a GSTR-2B (.json or .zip)     [CONTRIBUTOR]
    GET    /workspaces/{wid}/gst/returns                       the imports                           [VIEWER]
    GET    /workspaces/{wid}/gst/summary                       the six figures (+ what the plan shows) [VIEWER]
    GET    /workspaces/{wid}/gst/suppliers                     who has not reported what             [VIEWER, plan]
    GET    /workspaces/{wid}/gst/records                       the invoice list, filtered            [VIEWER, plan]
    GET    /workspaces/{wid}/gst/records/{id}                  one line, books beside GSTR-2B        [VIEWER, plan]
    POST   /workspaces/{wid}/gst/records/{id}/decision         confirm / not ours / link by hand     [CONTRIBUTOR, plan]
    DELETE /workspaces/{wid}/gst/records/{id}/decision         undo a decision                       [CONTRIBUTOR, plan]
    GET    /workspaces/{wid}/gst/export.xlsx                   the workbook                          [CONTRIBUTOR, plan]
    GET    /workspaces/{wid}/gst/suppliers/{gstin}/reminder    a drafted email to the supplier       [CONTRIBUTOR, plan]
    POST   /workspaces/{wid}/gst/suppliers/{gstin}/reminder/send   send it to a known contact        [CONTRIBUTOR, plan]
    GET    /workspaces/{wid}/gst/settings | PATCH              the rounding tolerance                [VIEWER | ADMIN]

Enterprise, across every workspace (`capability.gst_credit_all_workspaces`), read-only, for organization owners, admins
and billing, and for API keys holding `gst:read`:

    GET    /organizations/{oid}/gst/summary                    the six figures of one GSTIN across the workspaces
    GET    /organizations/{oid}/gst/suppliers                  who has not reported what
    GET    /organizations/{oid}/gst/records                    the invoice list (the workspaces the person may read)

"plan" = `capability.gst_credit` (Business, Enterprise). Importing and the headline figures need no capability (the GST
Credit preview), and the sample company is open to everyone, read-only. Viewers read; owners, admins and workspace
contributors import, decide and export. Everything is a recommendation, never tax advice.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.orm import Session

from app.api import capability_gate
from app.api.deps import OrganizationContext, RequireOrgRole, RequireWorkspaceRole, TenantContext, get_db
from app.core import entitlements
from app.core.pagination import MAX_OFFSET
from app.models.audit_log import AuditAction, AuditResourceType
from app.models.gst import GstReturn, GstSettings
from app.models.organization import OrganizationRole
from app.models.workspace import Workspace, WorkspaceRole
from app.services import audit_service
from app.services.gst import engine, export, gate, parse, queries, reminder, store, summary
from app.services.gst import org as gst_org
from app.services.gst import fields as gst_fields
from app.services.gst import vocabulary as v

router = APIRouter(tags=["GST Credit"])

RequireViewer = RequireWorkspaceRole(WorkspaceRole.VIEWER)
RequireContributor = RequireWorkspaceRole(WorkspaceRole.CONTRIBUTOR)
RequireAdmin = RequireWorkspaceRole(WorkspaceRole.ADMIN)
P = "/workspaces/{workspace_id}/gst"


def _workspace(db: Session, context: TenantContext, workspace_id: uuid.UUID) -> Workspace:
    if context.workspace_id != workspace_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found.")
    workspace = db.get(Workspace, workspace_id)
    if workspace is None or workspace.organization_id != context.organization_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found.")
    return workspace


def _writable(workspace: Workspace) -> None:
    if workspace.is_sample:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={
            "code": "SAMPLE_READ_ONLY", "message": "The sample company is read-only: explore it, but import and "
                                                   "decide in your own workspace."})


def _gstin(value: Optional[str]) -> Optional[str]:
    if value is None or value == "":
        return None
    found = gst_fields.gstin_of(value)
    if found is None:
        raise HTTPException(status_code=422, detail={"code": "GSTIN_INVALID", "message": "That is not a GSTIN."})
    return found


def _period(value: Optional[str]) -> Optional[str]:
    if value is None or value == "":
        return None
    if len(value) != 7 or value[4] != "-" or not (value[:4] + value[5:]).isdigit() or not 1 <= int(value[5:]) <= 12:
        raise HTTPException(status_code=422, detail={"code": "PERIOD_INVALID", "message": "The period is YYYY-MM."})
    return value


def _failure(error: Any) -> HTTPException:
    return HTTPException(status_code=422, detail={"code": error.code, "message": error.message})


# --------------------------------------------------------------------------------------------- imports


@router.post(P + "/returns")
def import_returns(workspace_id: uuid.UUID, file: UploadFile = File(...), db: Session = Depends(get_db),
                   context: TenantContext = Depends(RequireContributor)) -> dict[str, Any]:
    """Upload a GSTR-2B download (.json, or a .zip holding it): 25 MB, 50,000 records. Answers with the period, the
    counts and every problem in words. Available on every plan (the preview)."""
    workspace = _workspace(db, context, workspace_id)
    _writable(workspace)
    data = file.file.read(v.MAX_FILE_BYTES + 1)
    try:
        results = store.import_file(db, workspace=workspace, user_id=context.user_id,
                                    file_name=file.filename or "gstr2b.json", data=data)
    except parse.ReturnFileError as error:
        db.rollback()
        raise _failure(error) from error
    db.commit()
    return {"results": results, "imported": sum(1 for r in results if r["status"] in (store.IMPORTED, store.REPLACED)),
            "unchanged": sum(1 for r in results if r["status"] == store.UNCHANGED)}


@router.get(P + "/returns")
def list_returns(workspace_id: uuid.UUID, include_replaced: bool = Query(default=False), db: Session = Depends(get_db),
                 context: TenantContext = Depends(RequireViewer)) -> dict[str, Any]:
    _workspace(db, context, workspace_id)
    query = db.query(GstReturn).filter(GstReturn.workspace_id == workspace_id)
    if not include_replaced:
        query = query.filter(GstReturn.status == v.RETURN_ACTIVE)
    rows = query.order_by(GstReturn.gstin, GstReturn.period.desc(), GstReturn.imported_at.desc()).limit(500).all()
    return {"items": [{
        "id": str(r.id), "gstin": r.gstin, "period": r.period, "version": r.version, "status": r.status,
        "generated_on": r.generated_on.isoformat() if r.generated_on else None, "file_name": r.file_name,
        "record_count": r.record_count, "imported_at": r.imported_at.isoformat(), "problems": r.problems or [],
        "supersedes_id": str(r.supersedes_id) if r.supersedes_id else None,
    } for r in rows]}


# --------------------------------------------------------------------------------------------- reading


@router.get(P + "/summary")
def get_summary(workspace_id: uuid.UUID, gstin: Optional[str] = Query(default=None, max_length=20),
                period: Optional[str] = Query(default=None, max_length=7), db: Session = Depends(get_db),
                context: TenantContext = Depends(RequireViewer)) -> dict[str, Any]:
    """The six figures for a GSTIN and period (or all). On every plan; the lists are the paid part."""
    workspace = _workspace(db, context, workspace_id)
    wanted, month = _gstin(gstin), _period(period)
    if workspace.is_sample and not engine.active_gstins(db, workspace.id):
        # A sample company built before GST Credit existed gets its GSTR-2B the first time someone opens the page.
        from app.services.gst import sample as gst_sample

        gst_sample.build_returns(db, workspace, user_id=None)
        db.commit()
    full = gate.full_access(db, workspace)
    return {
        **summary.figures(db, workspace_ids=[workspace.id], gstin=wanted, period=month),
        **summary.returns_overview(db, workspace_ids=[workspace.id], gstin=wanted),
        "gstin": wanted, "period": month, "is_sample": bool(workspace.is_sample),
        "access": {"full": full, "preview": not full,
                   "locked": [] if full else ["suppliers", "invoices", "ims", "decisions", "export", "reminders"]},
        "tolerance_micros": engine.tolerance_micros(db, workspace.id),
        "law": {"itc": v.LAW_ITC_2B, "days_180": v.LAW_180_DAYS, "time_limit": v.LAW_TIME_LIMIT, "ims": v.LAW_IMS,
                "gstr2b": v.LAW_GSTR2B},
    }


@router.get(P + "/suppliers")
def get_suppliers(workspace_id: uuid.UUID, gstin: Optional[str] = Query(default=None, max_length=20),
                  period: Optional[str] = Query(default=None, max_length=7),
                  offset: int = Query(default=0, ge=0, le=MAX_OFFSET), limit: int = Query(default=50, ge=1, le=200),
                  db: Session = Depends(get_db), context: TenantContext = Depends(RequireViewer)) -> dict[str, Any]:
    workspace = _workspace(db, context, workspace_id)
    gate.require_full(db, workspace, context, "gst.suppliers")
    return summary.supplier_list(db, workspace_ids=[workspace.id], gstin=_gstin(gstin), period=_period(period),
                                 offset=offset, limit=limit)


@router.get(P + "/records")
def get_records(workspace_id: uuid.UUID, gstin: Optional[str] = Query(default=None, max_length=20),
                period: Optional[str] = Query(default=None, max_length=7),
                line_status: Optional[list[str]] = Query(default=None, alias="status"),
                supplier: Optional[str] = Query(default=None, max_length=100),
                ims: Optional[str] = Query(default=None, max_length=8), q: Optional[str] = Query(default=None, max_length=64),
                at_risk: Optional[bool] = Query(default=None),
                offset: int = Query(default=0, ge=0, le=MAX_OFFSET), limit: int = Query(default=50, ge=1, le=200),
                db: Session = Depends(get_db), context: TenantContext = Depends(RequireViewer)) -> dict[str, Any]:
    workspace = _workspace(db, context, workspace_id)
    gate.require_full(db, workspace, context, "gst.records")
    for value in line_status or ():
        if value not in v.STATUSES:
            raise HTTPException(status_code=422, detail={"code": "STATUS_UNKNOWN", "message": f"Unknown status {value}."})
    if ims and ims not in v.IMS_ACTIONS:
        raise HTTPException(status_code=422, detail={"code": "IMS_UNKNOWN", "message": "ims is ACCEPT, PENDING or REJECT."})
    return queries.list_lines(db, workspace_ids=[workspace.id], gstin=_gstin(gstin), period=_period(period),
                              statuses=line_status, supplier=supplier, ims_action=ims, q=q, at_risk=at_risk,
                              offset=offset, limit=limit)


@router.get(P + "/records/{line_id}")
def get_record(workspace_id: uuid.UUID, line_id: uuid.UUID, db: Session = Depends(get_db),
               context: TenantContext = Depends(RequireViewer)) -> dict[str, Any]:
    workspace = _workspace(db, context, workspace_id)
    gate.require_full(db, workspace, context, "gst.records")
    detail = queries.line_detail(db, workspace, line_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Line not found.")
    return detail


# --------------------------------------------------------------------------------------------- deciding


class DecisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: str = Field(..., max_length=10)
    work_item_id: Optional[uuid.UUID] = None
    note: Optional[str] = Field(default=None, max_length=500)


def _decision_error(error: queries.DecisionError) -> HTTPException:
    return HTTPException(status_code=error.status, detail={"code": error.code, "message": error.message})


@router.post(P + "/records/{record_id}/decision")
def post_decision(workspace_id: uuid.UUID, record_id: uuid.UUID, body: DecisionIn, db: Session = Depends(get_db),
                  context: TenantContext = Depends(RequireContributor)) -> dict[str, Any]:
    workspace = _workspace(db, context, workspace_id)
    _writable(workspace)
    gate.require_full(db, workspace, context, "gst.decide")
    try:
        result = queries.decide(db, workspace=workspace, user_id=context.user_id, record_id=record_id,
                                decision=body.decision, work_item_id=body.work_item_id, note=body.note)
    except queries.DecisionError as error:
        db.rollback()
        raise _decision_error(error) from error
    db.commit()
    return result


@router.delete(P + "/records/{record_id}/decision")
def delete_decision(workspace_id: uuid.UUID, record_id: uuid.UUID, db: Session = Depends(get_db),
                    context: TenantContext = Depends(RequireContributor)) -> dict[str, Any]:
    workspace = _workspace(db, context, workspace_id)
    _writable(workspace)
    gate.require_full(db, workspace, context, "gst.decide")
    try:
        result = queries.undo_decision(db, workspace=workspace, user_id=context.user_id, record_id=record_id)
    except queries.DecisionError as error:
        db.rollback()
        raise _decision_error(error) from error
    db.commit()
    return result


# --------------------------------------------------------------------------------------------- export, reminders


@router.get(P + "/export.xlsx")
def export_workbook(workspace_id: uuid.UUID, gstin: Optional[str] = Query(default=None, max_length=20),
                    period: Optional[str] = Query(default=None, max_length=7), db: Session = Depends(get_db),
                    context: TenantContext = Depends(RequireContributor)) -> Response:
    workspace = _workspace(db, context, workspace_id)
    gate.require_full(db, workspace, context, "gst.export")
    wanted, month = _gstin(gstin), _period(period)
    data = export.build(db, workspace_ids=[workspace.id], gstin=wanted, period=month)
    audit_service.record(db, organization_id=workspace.organization_id, workspace_id=workspace.id,
                         actor_id=context.user_id, resource_type=AuditResourceType.GST_MATCH, resource_id=None,
                         action=AuditAction.EXPORTED, details={"gstin": wanted, "period": month, "bytes": len(data)})
    db.commit()
    name = f"gst-credit-{wanted or 'all'}-{month or 'all'}-{date.today().isoformat()}.xlsx"
    return Response(content=data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"})


@router.get(P + "/suppliers/{supplier_gstin}/reminder")
def get_reminder(workspace_id: uuid.UUID, supplier_gstin: str, gstin: str = Query(..., max_length=20),
                 db: Session = Depends(get_db), context: TenantContext = Depends(RequireContributor)) -> dict[str, Any]:
    workspace = _workspace(db, context, workspace_id)
    gate.require_full(db, workspace, context, "gst.reminder")
    supplier, ours = _gstin(supplier_gstin), _gstin(gstin)
    return reminder.draft(db, workspace, ours or "", supplier or "")


@router.post(P + "/suppliers/{supplier_gstin}/reminder/send")
def send_reminder(workspace_id: uuid.UUID, supplier_gstin: str, gstin: str = Query(..., max_length=20),
                  db: Session = Depends(get_db), context: TenantContext = Depends(RequireContributor)) -> dict[str, Any]:
    workspace = _workspace(db, context, workspace_id)
    _writable(workspace)
    gate.require_full(db, workspace, context, "gst.reminder")
    supplier, ours = _gstin(supplier_gstin), _gstin(gstin)
    result = reminder.send(db, workspace, ours or "", supplier or "")
    if result.get("sent"):
        audit_service.record(db, organization_id=workspace.organization_id, workspace_id=workspace.id,
                             actor_id=context.user_id, resource_type=AuditResourceType.GST_MATCH, resource_id=None,
                             action=AuditAction.CREATED, details={"reminder_to_supplier": supplier, "gstin": ours,
                                                                  "invoices": len(result["lines"])})
    db.commit()
    result.pop("html", None)
    return result


# --------------------------------------------------------------------------------------------- settings


class SettingsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tolerance_rupees: Optional[float] = Field(default=None, ge=0, le=1000)
    #: Session J: after how many days a purchase invoice still missing from every GSTR-2B is announced to automation.
    waiting_notice_days: Optional[int] = Field(default=None, ge=1, le=365)

    @model_validator(mode="after")
    def _something_to_change(self) -> "SettingsIn":
        if self.tolerance_rupees is None and self.waiting_notice_days is None:
            raise ValueError("Send tolerance_rupees, waiting_notice_days or both.")
        return self


@router.get(P + "/settings")
def get_settings(workspace_id: uuid.UUID, db: Session = Depends(get_db),
                 context: TenantContext = Depends(RequireViewer)) -> dict[str, Any]:
    workspace = _workspace(db, context, workspace_id)
    row = db.get(GstSettings, workspace.id)
    return {"tolerance_micros": engine.tolerance_micros(db, workspace.id),
            "default_tolerance_micros": v.DEFAULT_TOLERANCE_MICROS,
            "waiting_notice_days": row.waiting_notice_days if row is not None else 30, "default_waiting_notice_days": 30}


@router.patch(P + "/settings")
def patch_settings(workspace_id: uuid.UUID, body: SettingsIn, db: Session = Depends(get_db),
                   context: TenantContext = Depends(RequireAdmin)) -> dict[str, Any]:
    workspace = _workspace(db, context, workspace_id)
    _writable(workspace)
    gate.require_full(db, workspace, context, "gst.settings")
    row = db.get(GstSettings, workspace.id)
    if row is None:
        row = GstSettings(workspace_id=workspace.id, organization_id=workspace.organization_id)
        db.add(row)
    if body.tolerance_rupees is not None:
        row.tolerance_micros = int(round(body.tolerance_rupees * 1_000_000))
    if body.waiting_notice_days is not None:
        row.waiting_notice_days = body.waiting_notice_days
    row.updated_by_user_id = context.user_id
    db.flush()
    audit_service.record(db, organization_id=workspace.organization_id, workspace_id=workspace.id,
                         actor_id=context.user_id, resource_type=AuditResourceType.GST_MATCH, resource_id=None,
                         action=AuditAction.UPDATED,
                         details={"tolerance_micros": row.tolerance_micros, "waiting_notice_days": row.waiting_notice_days})
    if body.tolerance_rupees is not None:
        engine.recompute(db, workspace)
    db.commit()
    return {"tolerance_micros": row.tolerance_micros, "waiting_notice_days": row.waiting_notice_days}


# --------------------------------------------------------------------------------------------- every workspace

O = "/organizations/{organization_id}/gst"
RequireOrgReader = RequireOrgRole([OrganizationRole.OWNER, OrganizationRole.ADMIN, OrganizationRole.BILLING])
LAW = {"itc": v.LAW_ITC_2B, "days_180": v.LAW_180_DAYS, "time_limit": v.LAW_TIME_LIMIT, "ims": v.LAW_IMS,
       "gstr2b": v.LAW_GSTR2B}


def _org_scope(db: Session, context: OrganizationContext, gstin: Optional[str], operation: str):
    """The plan's capability, the GSTIN (the one asked for, else the first imported) and the workspaces this person
    may read: owners and admins all of them, billing the ones it has grants on."""
    from app.services.helm import gate as helm_gate

    capability_gate.require_capability(db, context=context,
                                       capability_key=entitlements.GST_CREDIT_ALL_WORKSPACES_CAPABILITY,
                                       operation=operation)
    workspaces = gst_org.workspaces_of(db, context.organization_id)
    ids = [w.id for w in workspaces]
    available = gst_org.overview(db, ids)
    wanted = _gstin(gstin) or (available["gstins"][0] if available["gstins"] else None)
    result = gst_org.reconciliation(db, context.organization_id, wanted) if wanted else None
    readable = helm_gate.readable_workspaces(db, organization_id=context.organization_id, user_id=context.user_id,
                                             role=context.role) & set(ids)
    return workspaces, available, wanted, result, readable


@router.get(O + "/summary")
def get_org_summary(organization_id: uuid.UUID, gstin: Optional[str] = Query(default=None, max_length=20),
                    period: Optional[str] = Query(default=None, max_length=7), db: Session = Depends(get_db),
                    context: OrganizationContext = Depends(RequireOrgReader)) -> dict[str, Any]:
    """The six figures of one GSTIN across every workspace, and what each workspace contributes."""
    month = _period(period)
    workspaces, available, wanted, result, _readable = _org_scope(db, context, gstin, "gst.org.summary")
    lines = gst_org.scoped(result, period=month) if result else []
    return {
        **gst_org.figures(lines), **available, "gstin": wanted, "period": month,
        "workspaces": gst_org.by_workspace(result, lines) if result else [],
        "workspace_count": len(workspaces), "kept_for_seconds": gst_org.CACHE_SECONDS,
        "law": LAW,
        "note": "Computed when you open the page from the GSTR-2B returns imported in any workspace and the purchase "
                "invoices of every workspace that holds this GSTIN's purchases. The sample company is not included. "
                "Imports, decisions and exports are made in each workspace.",
    }


@router.get(O + "/suppliers")
def get_org_suppliers(organization_id: uuid.UUID, gstin: Optional[str] = Query(default=None, max_length=20),
                      period: Optional[str] = Query(default=None, max_length=7),
                      offset: int = Query(default=0, ge=0, le=MAX_OFFSET), limit: int = Query(default=50, ge=1, le=200),
                      db: Session = Depends(get_db),
                      context: OrganizationContext = Depends(RequireOrgReader)) -> dict[str, Any]:
    month = _period(period)
    _workspaces, _available, _wanted, result, readable = _org_scope(db, context, gstin, "gst.org.suppliers")
    lines = gst_org.scoped(result, period=month, workspace_ids=readable) if result else []
    return gst_org.suppliers(lines, offset=offset, limit=limit)


@router.get(O + "/records")
def get_org_records(organization_id: uuid.UUID, gstin: Optional[str] = Query(default=None, max_length=20),
                    period: Optional[str] = Query(default=None, max_length=7),
                    line_status: Optional[list[str]] = Query(default=None, alias="status"),
                    supplier: Optional[str] = Query(default=None, max_length=100),
                    ims: Optional[str] = Query(default=None, max_length=8),
                    q: Optional[str] = Query(default=None, max_length=64), at_risk: Optional[bool] = Query(default=None),
                    workspace_id: Optional[uuid.UUID] = Query(default=None),
                    offset: int = Query(default=0, ge=0, le=MAX_OFFSET), limit: int = Query(default=50, ge=1, le=200),
                    db: Session = Depends(get_db),
                    context: OrganizationContext = Depends(RequireOrgReader)) -> dict[str, Any]:
    month = _period(period)
    for value in line_status or ():
        if value not in v.STATUSES:
            raise HTTPException(status_code=422, detail={"code": "STATUS_UNKNOWN", "message": f"Unknown status {value}."})
    if ims and ims not in v.IMS_ACTIONS:
        raise HTTPException(status_code=422, detail={"code": "IMS_UNKNOWN", "message": "ims is ACCEPT, PENDING or REJECT."})
    workspaces, _available, _wanted, result, readable = _org_scope(db, context, gstin, "gst.org.records")
    lines = gst_org.scoped(result, period=month, workspace_ids=readable) if result else []
    return gst_org.page(lines, statuses=line_status, supplier=supplier, ims_action=ims, q=q, at_risk=at_risk,
                        workspace_id=workspace_id, offset=offset, limit=limit,
                        names={w.id: w.workspace_name for w in workspaces})
