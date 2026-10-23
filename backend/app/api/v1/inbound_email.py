"""Email-in's settings API (Final session 1, 2B). Workspace-scoped, workspace admins only.

    GET    /workspaces/{wid}/inbound-email                         the address, the allowed senders, the recent arrivals
    POST   /workspaces/{wid}/inbound-email/rotate                  a new address; the old one is refused from then on
    POST   /workspaces/{wid}/inbound-email/senders                 allow a sender (an address or a domain)
    DELETE /workspaces/{wid}/inbound-email/senders/{sender_id}     stop allowing it
    POST   /workspaces/{wid}/inbound-email/messages/{id}/approve   add a held message's documents (the plan still applies)
    POST   /workspaces/{wid}/inbound-email/messages/{id}/discard   throw a held message away

Postmark's webhook itself is `public_inbound_email.py`. The address is never built from the workspace's name or slug.
"""

from __future__ import annotations

import uuid
from typing import Any

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import RequireWorkspaceRole, TenantContext, get_db
from app.models.audit_log import AuditAction, AuditResourceType
from app.models.inbound_email import InboundEmailSender, InboundMessage
from app.models.workspace import WorkspaceRole
from app.services import audit_service
from app.services.inbound_email import service

router = APIRouter(tags=["Email-in"])
RequireAdmin = RequireWorkspaceRole(WorkspaceRole.ADMIN)
P = "/workspaces/{workspace_id}/inbound-email"
RECENT = 50


class SenderRequest(BaseModel):
    pattern: str = Field(min_length=1, max_length=255)


def _own(context: TenantContext, workspace_id: uuid.UUID) -> None:
    if context.workspace_id != workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace not found.")


def _message_view(row: InboundMessage) -> dict[str, Any]:
    return {
        "id": str(row.id), "from_address": row.from_address, "from_name": row.from_name, "subject": row.subject,
        "received_at": row.received_at.isoformat() if row.received_at else None, "status": row.status,
        "hold_code": row.hold_code, "hold_message": row.hold_message,
        "can_approve": row.status == "HELD" and row.hold_code in service.APPROVABLE,
        "documents": len(row.work_item_ids or []),
        # What happened to each attachment, never its bytes or its storage key.
        "attachments": [
            {k: v for k, v in entry.items() if k in {"name", "size", "outcome", "note", "work_item_id", "batch_id"}}
            for entry in (row.attachments or [])
        ],
    }


def _view(db: Session, context: TenantContext) -> dict[str, Any]:
    address = service.active_address(db, organization_id=context.organization_id, workspace_id=context.workspace_id)
    rendered = service.address_for(address.token)
    senders = db.execute(
        sa.select(InboundEmailSender).where(InboundEmailSender.workspace_id == context.workspace_id).order_by(InboundEmailSender.pattern)
    ).scalars().all()
    messages = db.execute(
        sa.select(InboundMessage).where(InboundMessage.workspace_id == context.workspace_id)
        .order_by(InboundMessage.received_at.desc()).limit(RECENT)
    ).scalars().all()
    held = db.execute(
        sa.select(sa.func.count()).select_from(InboundMessage)
        .where(InboundMessage.workspace_id == context.workspace_id, InboundMessage.status == "HELD")
    ).scalar_one()
    return {
        # Switched on = the webhook credential is set AND an address form is configured.
        "enabled": service.is_enabled() and rendered is not None,
        "address": rendered,
        "form": "domain" if rendered and "@inbound.postmarkapp.com" not in rendered else ("postmark" if rendered else None),
        "senders": [{"id": str(s.id), "pattern": s.pattern, "created_at": s.created_at.isoformat()} for s in senders],
        "messages": [_message_view(m) for m in messages],
        "held_count": int(held),
    }


@router.get(P)
def get_inbound_email(workspace_id: uuid.UUID, db: Session = Depends(get_db), context: TenantContext = Depends(RequireAdmin)) -> dict[str, Any]:
    _own(context, workspace_id)
    view = _view(db, context)
    db.commit()  # the first read creates the workspace's address
    return view


@router.post(P + "/rotate")
def rotate_address(workspace_id: uuid.UUID, db: Session = Depends(get_db), context: TenantContext = Depends(RequireAdmin)) -> dict[str, Any]:
    _own(context, workspace_id)
    service.active_address(db, organization_id=context.organization_id, workspace_id=context.workspace_id)
    service.rotate(db, organization_id=context.organization_id, workspace_id=context.workspace_id, user_id=context.user_id)
    audit_service.record(db, organization_id=context.organization_id, workspace_id=context.workspace_id, actor_id=context.user_id,
                         resource_type=AuditResourceType.WORKSPACE, resource_id=context.workspace_id, action=AuditAction.UPDATED,
                         details={"email_in": "address_rotated"})
    view = _view(db, context)
    db.commit()
    return view


@router.post(P + "/senders", status_code=status.HTTP_201_CREATED)
def add_sender(workspace_id: uuid.UUID, payload: SenderRequest, db: Session = Depends(get_db),
               context: TenantContext = Depends(RequireAdmin)) -> dict[str, Any]:
    _own(context, workspace_id)
    try:
        pattern = service.normalise_pattern(payload.pattern)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    try:
        with db.begin_nested():
            db.add(InboundEmailSender(organization_id=context.organization_id, workspace_id=context.workspace_id, pattern=pattern,
                                      created_by_user_id=context.user_id))
    except IntegrityError:
        raise HTTPException(status.HTTP_409_CONFLICT, f"{pattern} is already allowed.")
    audit_service.record(db, organization_id=context.organization_id, workspace_id=context.workspace_id, actor_id=context.user_id,
                         resource_type=AuditResourceType.WORKSPACE, resource_id=context.workspace_id, action=AuditAction.UPDATED,
                         details={"email_in": "sender_allowed"})
    view = _view(db, context)
    db.commit()
    return view


@router.delete(P + "/senders/{sender_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def remove_sender(workspace_id: uuid.UUID, sender_id: uuid.UUID, db: Session = Depends(get_db),
                  context: TenantContext = Depends(RequireAdmin)) -> Response:
    _own(context, workspace_id)
    row = db.execute(sa.select(InboundEmailSender).where(InboundEmailSender.id == sender_id,
                                                         InboundEmailSender.workspace_id == context.workspace_id)).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Sender not found.")
    db.delete(row)
    audit_service.record(db, organization_id=context.organization_id, workspace_id=context.workspace_id, actor_id=context.user_id,
                         resource_type=AuditResourceType.WORKSPACE, resource_id=context.workspace_id, action=AuditAction.UPDATED,
                         details={"email_in": "sender_removed"})
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _message(db: Session, context: TenantContext, message_id: uuid.UUID) -> InboundMessage:
    row = db.execute(sa.select(InboundMessage).where(InboundMessage.id == message_id,
                                                     InboundMessage.workspace_id == context.workspace_id)).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Message not found.")
    return row


@router.post(P + "/messages/{message_id}/approve")
def approve_message(workspace_id: uuid.UUID, message_id: uuid.UUID, db: Session = Depends(get_db),
                    context: TenantContext = Depends(RequireAdmin)) -> dict[str, Any]:
    _own(context, workspace_id)
    row = _message(db, context, message_id)
    try:
        outcome = service.approve(db, message=row, user_id=context.user_id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    audit_service.record(db, organization_id=context.organization_id, workspace_id=context.workspace_id, actor_id=context.user_id,
                         resource_type=AuditResourceType.WORKSPACE, resource_id=context.workspace_id, action=AuditAction.UPDATED,
                         details={"email_in": "message_approved", "result": outcome.status})
    db.commit()
    db.refresh(row)
    return {"result": outcome.status, "documents": outcome.documents, "message": _message_view(row)}


@router.post(P + "/messages/{message_id}/discard")
def discard_message(workspace_id: uuid.UUID, message_id: uuid.UUID, db: Session = Depends(get_db),
                    context: TenantContext = Depends(RequireAdmin)) -> dict[str, Any]:
    _own(context, workspace_id)
    row = _message(db, context, message_id)
    try:
        service.discard(db, message=row, user_id=context.user_id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    audit_service.record(db, organization_id=context.organization_id, workspace_id=context.workspace_id, actor_id=context.user_id,
                         resource_type=AuditResourceType.WORKSPACE, resource_id=context.workspace_id, action=AuditAction.UPDATED,
                         details={"email_in": "message_discarded"})
    db.commit()
    db.refresh(row)
    return {"message": _message_view(row)}
