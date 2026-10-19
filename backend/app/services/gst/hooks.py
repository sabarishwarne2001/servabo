"""Where the rest of the product tells GST Credit a document changed.

Called from the same places as Helm's `hooks.document_changed` (a document finished processing, was verified,
corrected or deleted). It asks for a debounced reconciliation of that workspace through the worker, and only when
some GSTR-2B is imported there. It never raises into the caller: a document path must not fail because GST Credit
could not be told; the nightly reconciliation catches anything missed.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import select

logger = logging.getLogger("app.services.gst.hooks")

JOB_RECOMPUTE = "gst.recompute"
DEBOUNCE_SECONDS = 10


def document_changed(db: Any, *, workspace_id: Optional[uuid.UUID], organization_id: Optional[uuid.UUID] = None,
                     reason: str = "document") -> bool:
    if workspace_id is None:
        return False
    try:
        from app.models.gst import GstReturn
        from app.models.workspace import Workspace
        from app.services import job_service
        from app.services.gst import vocabulary as v

        with db.begin_nested():
            if db.execute(select(GstReturn.id).where(GstReturn.workspace_id == workspace_id,
                                                     GstReturn.status == v.RETURN_ACTIVE).limit(1)).first() is None:
                return False
            if organization_id is None:
                workspace = db.get(Workspace, workspace_id)
                if workspace is None:
                    return False
                organization_id = workspace.organization_id
            bucket = int(datetime.now(timezone.utc).timestamp()) // DEBOUNCE_SECONDS
            job_service.enqueue(
                db, job_type=JOB_RECOMPUTE, organization_id=organization_id,
                payload={"workspace_id": str(workspace_id), "organization_id": str(organization_id), "reason": reason},
                idempotency_key=f"{JOB_RECOMPUTE}:{workspace_id}:{bucket}",
                available_at=datetime.fromtimestamp((bucket + 1) * DEBOUNCE_SECONDS, tz=timezone.utc) + timedelta(seconds=1),
            )
        return True
    except Exception:  # noqa: BLE001
        logger.exception("gst.hook_failed", extra={"workspace_id": str(workspace_id), "reason": reason})
        return False


__all__ = ["JOB_RECOMPUTE", "document_changed"]
