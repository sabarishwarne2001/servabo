"""Join the shared document-change path; never block document processing."""

import logging
from datetime import datetime, timezone, timedelta
from app.core.config import settings

logger = logging.getLogger(__name__)


def document_changed(
    db, *, workspace_id, organization_id=None, reason="document_changed"
):
    if not settings.TRINETRA_LIVE_ENABLED or workspace_id is None:
        return
    try:
        from app.models.workspace import Workspace
        from app.models.trinetra import TrinetraProfile
        from app.services import job_service

        with db.begin_nested():
            workspace = db.get(Workspace, workspace_id)
            if not workspace or workspace.is_sample:
                return
            if (
                not db.query(TrinetraProfile.id)
                .filter_by(workspace_id=workspace_id)
                .first()
            ):
                return
            # The handler repeats subscription/status checks before accessing evidence.
            now = datetime.now(timezone.utc)
            bucket = int(now.timestamp()) // 30
            job_service.enqueue(
                db,
                job_type="trinetra.recompute",
                organization_id=workspace.organization_id,
                payload={
                    "workspace_id": str(workspace.id),
                    "organization_id": str(workspace.organization_id),
                },
                idempotency_key=f"trinetra:changed:{workspace.id}:{bucket}",
                available_at=now + timedelta(seconds=31),
            )
    except Exception:
        # No source contents, identifiers or caller-provided reason in logs.
        logger.warning("trinetra.document_change_enqueue_failed")
