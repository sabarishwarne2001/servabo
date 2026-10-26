"""Bounded, read-only recompute against current snapshots; replay has no side effects."""

import uuid
from app.db.session import SessionLocal
from app.core.config import settings
from app.api.capability_gate import has_capability
from app.models.workspace import Workspace
from app.workers.tenant_gate import inactive_reason, unpaid_reason
from app.services.trinetra.service import summary


def handle_recompute(payload):
    organization_id = uuid.UUID(payload["organization_id"])
    workspace_id = uuid.UUID(payload["workspace_id"])
    with SessionLocal() as db:
        w = db.get(Workspace, workspace_id)
        if not w or w.organization_id != organization_id:
            return {"status": "unavailable"}
        if (
            not settings.TRINETRA_LIVE_ENABLED
            or inactive_reason(
                db, organization_id=organization_id, workspace_id=workspace_id
            )
            or unpaid_reason(db, organization_id=organization_id)
        ):
            return {"status": "blocked"}
        if w.is_sample or not has_capability(
            db, organization_id=organization_id, capability_key="capability.trinetra"
        ):
            return {"status": "blocked"}
        result = summary(db, w)
        return {
            "status": "complete",
            "cases": result["total"],
            "unresolved": result["unresolved"],
        }
