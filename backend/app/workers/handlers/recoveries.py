"""`recoveries.sweep` (hourly, LIGHT): bring every entitled workspace's Recoveries up to date (Final session 2A, N-191).

Each workspace of an organization whose plan includes Recoveries is swept with every adapter, the supplier statements
included (`service.sweep(heavy=True)`), and committed on its own: one workspace failing never stops the others. A
payload with `workspace_id` sweeps that workspace only. Reads the engines' tables; writes only `recovery_issues` and
`recovery_outcomes`.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import select

logger = logging.getLogger("app.workers.handlers.recoveries")


def handle(payload: dict[str, Any]) -> dict[str, Any]:
    from app.db.session import SessionLocal
    from app.models.workspace import Workspace, WorkspaceStatus
    from app.services.recoveries import service

    totals = {"workspaces": 0, "found": 0, "verified": 0, "not_money": 0, "closed": 0, "reopened": 0, "failed": 0}
    with SessionLocal() as db:
        stmt = select(Workspace.id, Workspace.organization_id).where(Workspace.status == WorkspaceStatus.ACTIVE)
        if payload.get("workspace_id"):
            stmt = stmt.where(Workspace.id == uuid.UUID(str(payload["workspace_id"])))
        targets = db.execute(stmt.order_by(Workspace.id)).all()
        entitled: dict[uuid.UUID, bool] = {}
        for workspace_id, organization_id in targets:
            if organization_id not in entitled:
                entitled[organization_id] = service.entitled(db, organization_id)
            if not entitled[organization_id]:
                continue
            try:
                workspace = db.get(Workspace, workspace_id)
                counts = service.sweep(db, workspace, heavy=True)
                db.commit()
                totals["workspaces"] += 1
                for key, value in counts.items():
                    totals[key] = totals.get(key, 0) + value
            except Exception:  # noqa: BLE001 - one workspace failing must not stop the others
                db.rollback()
                totals["failed"] += 1
                logger.warning("recoveries.sweep_failed", extra={"workspace_id": str(workspace_id)}, exc_info=True)
    return {"outcome": "COMPLETED", **totals}


__all__ = ["handle"]
