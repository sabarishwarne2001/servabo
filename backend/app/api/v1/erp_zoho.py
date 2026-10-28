"""Zoho Books "Connect" (Final session 1, 3C). The sign-in itself is `app/services/erp/zoho.py`; this module only authenticates,
gates on the ERP posting capability, and turns the service's answers into status codes.

    GET  /workspaces/{wid}/erp/zoho                                      what can be connected, and what is        [VIEWER]
    POST /workspaces/{wid}/erp/zoho/connect                               the address of Zoho's consent screen     [ADMIN]
    GET  /erp/zoho/callback                                        Zoho sends the browser back here          [signed state]
    GET  /workspaces/{wid}/erp/targets/{tid}/zoho/organizations           the Zoho organizations to choose from    [ADMIN]
    POST /workspaces/{wid}/erp/targets/{tid}/zoho/organization            choose one                               [ADMIN]
    POST /workspaces/{wid}/erp/targets/{tid}/zoho/check                   does the saved sign-in still work?       [ADMIN]
    POST /workspaces/{wid}/erp/targets/{tid}/zoho/disconnect              revoke at Zoho and forget it             [ADMIN]

No route returns a token. A Zoho error reaches the page as a short code and a sentence, never as Zoho's raw body.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Optional
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api import capability_gate
from app.api.deps import RequireWorkspaceRole, TenantContext, get_db
from app.core import entitlements
from app.core.config import settings
from app.models.erp import ErpTarget
from app.models.organization import Organization
from app.models.workspace import Workspace, WorkspaceRole
from app.services.erp import vocabulary as v
from app.services.erp import zoho

logger = logging.getLogger("app.api.v1.erp_zoho")

router = APIRouter(tags=["ERP posting"])
RequireViewer = RequireWorkspaceRole(WorkspaceRole.VIEWER)
RequireAdmin = RequireWorkspaceRole(WorkspaceRole.ADMIN)

_STATUS = {"NOT_CONFIGURED": 503, "BAD_STATE": 400, "EXPIRED": 400, "USED": 400, "UNKNOWN_DATA_CENTRE": 422, "NOT_CONNECTED": 409,
           "RECONNECT": 409, "UNKNOWN_ORGANIZATION": 422, "UNREACHABLE": 502, "EXCHANGE_FAILED": 400, "WRONG_DATA_CENTRE": 400}


def _raise(exc: zoho.ZohoError) -> HTTPException:
    return HTTPException(_STATUS.get(exc.code, 400), detail={"code": exc.code, "message": str(exc)})


def _gate(db: Session, context: TenantContext, operation: str) -> None:
    capability_gate.require_capability(db, context=context, capability_key=entitlements.ERP_POSTING_CAPABILITY, operation=operation)


def _ws(context: TenantContext, workspace_id: uuid.UUID) -> None:
    if context.workspace_id != workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace not found.")


def _zoho_target(db: Session, workspace_id: uuid.UUID, target_id: uuid.UUID) -> ErpTarget:
    target = db.get(ErpTarget, target_id)
    if target is None or target.workspace_id != workspace_id or target.preset != v.PRESET_ZOHO:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Zoho Books connection not found.")
    return target


class ConnectIn(BaseModel):
    data_centre: str = Field(default=zoho.DEFAULT_DATA_CENTRE, max_length=4)
    #: Set to reconnect an existing connection instead of making a new one.
    target_id: Optional[uuid.UUID] = None


class OrganizationIn(BaseModel):
    organization_id: str = Field(min_length=1, max_length=64)


@router.get("/workspaces/{workspace_id}/erp/zoho")
def get_zoho(workspace_id: uuid.UUID, db: Session = Depends(get_db), context: TenantContext = Depends(RequireViewer)) -> dict[str, Any]:
    _ws(context, workspace_id)
    _gate(db, context, "erp.zoho.get")
    targets = db.execute(select(ErpTarget).where(ErpTarget.workspace_id == workspace_id, ErpTarget.preset == v.PRESET_ZOHO)
                         .order_by(ErpTarget.created_at)).scalars().all()
    return {
        "configured": zoho.configured(), "default_data_centre": zoho.DEFAULT_DATA_CENTRE,
        "data_centres": [{"key": d.key, "label": d.label} for d in zoho.DATA_CENTRES.values()],
        "connections": [{"target_id": str(t.id), "name": t.name, "status": t.status, **zoho.connection_view(t)} for t in targets],
    }


@router.post("/workspaces/{workspace_id}/erp/zoho/connect")
def connect(workspace_id: uuid.UUID, body: ConnectIn, db: Session = Depends(get_db),
            context: TenantContext = Depends(RequireAdmin)) -> dict[str, str]:
    _ws(context, workspace_id)
    _gate(db, context, "erp.zoho.connect")
    if body.target_id is not None:
        _zoho_target(db, workspace_id, body.target_id)
    try:
        url = zoho.start(db, organization_id=context.organization_id, workspace_id=workspace_id, user_id=context.user_id,
                         dc=body.data_centre, target_id=body.target_id)
    except zoho.ZohoError as exc:
        raise _raise(exc) from exc
    db.commit()
    return {"authorize_url": url}


def _back(db: Session, workspace_id: Optional[uuid.UUID], **params: str) -> RedirectResponse:
    base = settings.FRONTEND_URL.rstrip("/")
    path = ""
    if workspace_id is not None:
        row = db.execute(select(Organization.slug, Workspace.slug).join(Workspace, Workspace.organization_id == Organization.id)
                         .where(Workspace.id == workspace_id)).first()
        if row is not None:
            path = f"/{row[0]}/{row[1]}/erp"
    return RedirectResponse(f"{base}{path or '/'}?{urlencode({k: val for k, val in params.items() if val})}", status_code=302)


@router.get("/erp/zoho/callback", include_in_schema=False)
def callback(code: Optional[str] = Query(default=None, max_length=2000), state: Optional[str] = Query(default=None, max_length=4000),
             location: Optional[str] = Query(default=None, max_length=16), error: Optional[str] = Query(default=None, max_length=100),
             db: Session = Depends(get_db)) -> RedirectResponse:
    """Zoho sends the browser here. Whatever happens, the person lands back on the ERP page with a short reason."""
    workspace_id: Optional[uuid.UUID] = None
    try:
        if state:
            try:
                workspace_id = uuid.UUID(str(zoho._unsign(state).get("w")))  # noqa: SLF001 - the state names the workspace to return to
            except (ValueError, zoho.ZohoError):
                workspace_id = None
        if error or not code or not state:
            return _back(db, workspace_id, zoho="error", reason="DENIED" if error == "access_denied" else "INCOMPLETE")
        done = zoho.complete(db, code=code, state=state, location=location)
        from app.api import capability_gate as gate

        if not gate.has_capability(db, organization_id=done.organization_id, capability_key=entitlements.ERP_POSTING_CAPABILITY):
            db.rollback()
            return _back(db, workspace_id, zoho="error", reason="PLAN")
        db.commit()
        return _back(db, done.workspace_id, zoho="connected" if done.state == "CONNECTED" else "choose", target=str(done.target.id))
    except zoho.ZohoError as exc:
        db.rollback()
        logger.info("erp.zoho.callback_refused", extra={"code": exc.code})
        return _back(db, workspace_id, zoho="error", reason=exc.code)


@router.get("/workspaces/{workspace_id}/erp/targets/{target_id}/zoho/organizations")
def list_organizations(workspace_id: uuid.UUID, target_id: uuid.UUID, db: Session = Depends(get_db),
                       context: TenantContext = Depends(RequireAdmin)) -> dict[str, Any]:
    _ws(context, workspace_id)
    _gate(db, context, "erp.zoho.organizations")
    target = _zoho_target(db, workspace_id, target_id)
    try:
        items = zoho.organizations(db, target)
    except zoho.ZohoError as exc:
        db.commit()   # a refused sign-in is recorded on the target
        raise _raise(exc) from exc
    return {"items": items}


@router.post("/workspaces/{workspace_id}/erp/targets/{target_id}/zoho/organization")
def choose_organization(workspace_id: uuid.UUID, target_id: uuid.UUID, body: OrganizationIn, db: Session = Depends(get_db),
                        context: TenantContext = Depends(RequireAdmin)) -> dict[str, Any]:
    _ws(context, workspace_id)
    _gate(db, context, "erp.zoho.organization")
    target = _zoho_target(db, workspace_id, target_id)
    try:
        zoho.choose_organization(db, target, body.organization_id, actor_user_id=context.user_id)
    except zoho.ZohoError as exc:
        db.commit()
        raise _raise(exc) from exc
    db.commit()
    return {"target_id": str(target.id), **zoho.connection_view(target)}


@router.post("/workspaces/{workspace_id}/erp/targets/{target_id}/zoho/check")
def check(workspace_id: uuid.UUID, target_id: uuid.UUID, db: Session = Depends(get_db),
          context: TenantContext = Depends(RequireAdmin)) -> dict[str, Any]:
    _ws(context, workspace_id)
    _gate(db, context, "erp.zoho.check")
    target = _zoho_target(db, workspace_id, target_id)
    try:
        view = zoho.check(db, target)
    except zoho.ZohoError as exc:
        db.commit()
        raise _raise(exc) from exc
    db.commit()
    return {"target_id": str(target.id), **view}


@router.post("/workspaces/{workspace_id}/erp/targets/{target_id}/zoho/disconnect")
def disconnect(workspace_id: uuid.UUID, target_id: uuid.UUID, db: Session = Depends(get_db),
               context: TenantContext = Depends(RequireAdmin)) -> dict[str, Any]:
    _ws(context, workspace_id)
    _gate(db, context, "erp.zoho.disconnect")
    target = _zoho_target(db, workspace_id, target_id)
    revoked = zoho.disconnect(db, target, actor_user_id=context.user_id)
    db.commit()
    return {"target_id": str(target.id), "revoked_at_zoho": revoked, **zoho.connection_view(target)}


class TallySetupIn(BaseModel):
    company: str = Field(min_length=1, max_length=200)
    name: str = Field(default="Tally Prime", min_length=1, max_length=120)
    purchases: str = Field(default="", max_length=100)
    cgst: str = Field(default="", max_length=100)
    sgst: str = Field(default="", max_length=100)
    igst: str = Field(default="", max_length=100)
    tax: str = Field(default="", max_length=100)


@router.post("/workspaces/{workspace_id}/erp/tally/setup", status_code=201)
def tally_setup(workspace_id: uuid.UUID, body: TallySetupIn, db: Session = Depends(get_db),
                context: TenantContext = Depends(RequireAdmin)) -> dict[str, Any]:
    """Tally Prime, guided: a download target with the shipped mapping and the customer's own ledger names (3C)."""
    _ws(context, workspace_id)
    # N-187 (closes N-174): the Tally Prime file is on Starter too, without ERP posting.
    if not capability_gate.has_capability(db, organization_id=context.organization_id,
                                          capability_key=entitlements.TALLY_FILE_CAPABILITY):
        _gate(db, context, "erp.tally.setup")
    from app.services.erp import service, tally_setup as guided

    try:
        target = guided.setup(db, organization_id=context.organization_id, workspace_id=workspace_id, actor_user_id=context.user_id,
                              company=body.company, name=body.name,
                              ledgers={"purchases": body.purchases, "cgst": body.cgst, "sgst": body.sgst, "igst": body.igst,
                                       "tax": body.tax})
    except service.ErpError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT if exc.code == "NAME_TAKEN" else status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail={"code": exc.code, "message": str(exc)}) from exc
    db.commit()
    return {"target_id": str(target.id), "name": target.name, "company": guided.guide(target)["company"]}


__all__ = ["router"]
