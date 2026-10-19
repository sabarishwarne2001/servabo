"""GST Credit's job (LIGHT profile): `gst.recompute`.

{workspace_id, organization_id}  reconcile that workspace's imported GSTR-2B returns against its documents (idempotent;
                                 debounced by the enqueuer).
{}                               the nightly sweep over every workspace with an imported return, which also moves the
                                 180-day and Section 16(4) clocks forward.

Archived, suspended, unpaid and ended-trial organizations are skipped by `tenant_gate` before the handler for a job
that names one; the sweep filters them itself.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import select

logger = logging.getLogger("app.workers.handlers.gst")


def handle_recompute(payload: dict[str, Any]) -> dict[str, Any]:
    from app.db.session import SessionLocal
    from app.models.gst import GstReturn
    from app.models.workspace import Workspace
    from app.services.gst import engine
    from app.services.gst import vocabulary as v
    from app.workers.tenant_gate import inactive_reason, unpaid_reason

    with SessionLocal() as db:
        if payload.get("workspace_id"):
            ids = [uuid.UUID(str(payload["workspace_id"]))]
        else:
            ids = list(db.execute(select(GstReturn.workspace_id).where(GstReturn.status == v.RETURN_ACTIVE)
                                  .distinct()).scalars())
        done, failed, skipped = 0, 0, 0
        for workspace_id in ids:
            workspace = db.get(Workspace, workspace_id)
            if workspace is None or inactive_reason(db, workspace_id=workspace_id) is not None or \
                    unpaid_reason(db, organization_id=workspace.organization_id) is not None:
                skipped += 1
                continue
            try:
                engine.recompute(db, workspace)
                db.commit()
                done += 1
            except Exception:  # noqa: BLE001 - one workspace must not stop the sweep
                db.rollback()
                failed += 1
                logger.exception("gst.recompute_failed", extra={"workspace_id": str(workspace_id)})
        return {"reconciled": done, "failed": failed, "skipped": skipped}
