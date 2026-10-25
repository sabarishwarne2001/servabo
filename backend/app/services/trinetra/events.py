"""Opt-in Enterprise event through the existing transactional public outbox."""

from app.api.capability_gate import has_capability
from app.core.config import settings
from app.services.automation.public_events import emit_once


def reviewed(db, workspace, row):
    if not settings.TRINETRA_LIVE_ENABLED or workspace.is_sample:
        return None
    if not has_capability(
        db,
        organization_id=workspace.organization_id,
        capability_key="capability.trinetra_all_workspaces",
    ):
        return None
    return emit_once(
        db,
        organization_id=workspace.organization_id,
        workspace_id=workspace.id,
        event_type="trinetra.case.reviewed",
        mark_key=f"trinetra:{row.id}:{row.revision}",
        resource_id=row.id,
        payload={
            "workspace_id": str(workspace.id),
            "case_id": str(row.id),
            "revision": row.revision,
            "state": row.state,
        },
    )
