"""Postmark's inbound webhook (Final session 1, 2B). No account: the credential is HTTP basic auth, the way Postmark documents.

    POST /api/v1/public/inbound/postmark

Registered in `app/core/public_route_registry.PUBLIC_ROUTES`. Everything the service decides is in
`app/services/inbound_email/service.py` (the answers and why are listed at the top of that file). This module only
authenticates, bounds the body and turns the service's decision into a status code. It never echoes the credential and
never logs a body, an attachment, an address's token or a sender.
"""

from __future__ import annotations

import base64
import json
import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.api.deps import get_db
from app.core.client_ip import client_ip
from app.core.config import settings
from app.services.inbound_email import service

logger = logging.getLogger("app.api.v1.public_inbound_email")

router = APIRouter(tags=["Email-in (public)"])


def _basic_credentials(header: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    if not header or not header.lower().startswith("basic "):
        return None, None
    try:
        decoded = base64.b64decode(header[6:].strip(), validate=True).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return None, None
    user, _, password = decoded.partition(":")
    return user, password


def _process(db: Session, parsed: service.Parsed) -> dict[str, Any]:
    address = service.resolve_token(db, parsed.token_candidates)
    # Unknown, rotated and archived are one answer: Postmark stops retrying a dead address and learns nothing more.
    if address is None or address.retired_at is not None or not service.workspace_is_live(db, address.workspace_id):
        logger.info("inbound_email.refused_address", extra={"known": address is not None})
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No such address.")
    try:
        outcome = service.receive(db, address=address, parsed=parsed)
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.exception("inbound_email.failed", extra={"workspace_id": str(address.workspace_id)})
        from app.core import error_tracking

        error_tracking.capture(exc, area="email_in", workspace_id=address.workspace_id, status_code=500)   # opaque ids only
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Could not process the message; Postmark will retry.")
    logger.info(
        "inbound_email.received",
        extra={"workspace_id": str(address.workspace_id), "status": outcome.status, "documents": outcome.documents,
               "sender": service.fingerprint(parsed.sender), "hold": outcome.hold_code},
    )
    return {"status": outcome.status, "documents": outcome.documents, "hold": outcome.hold_code}


@router.post("/public/inbound/postmark")
async def postmark_inbound(request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    if not service.is_enabled():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found.")
    user, password = _basic_credentials(request.headers.get("authorization"))
    if not service.credentials_match(user, password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unauthorized.", headers={"WWW-Authenticate": 'Basic realm="inbound"'})
    if not service.ip_allowed(client_ip(request)):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Forbidden.")

    limit = int(settings.INBOUND_EMAIL_MAX_BODY_MB) * 1024 * 1024
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > limit:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "The message is too large.")
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > limit:
            raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "The message is too large.")
        chunks.append(chunk)
    try:
        payload = json.loads(b"".join(chunks))
        parsed = service.parse(payload)
    except (ValueError, RecursionError):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Not a Postmark inbound message.")
    except service.InboundRefused as exc:
        raise HTTPException(exc.status, exc.reason)
    return await run_in_threadpool(_process, db, parsed)
