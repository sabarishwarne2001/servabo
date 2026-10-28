"""Join the shared document-change path; never block document processing."""

import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)


def document_changed(
    db, *, workspace_id, organization_id=None, reason="document_changed"
):
    from app.services.trinetra import mode

    if mode.deployment_mode() == mode.OFF or workspace_id is None:
        return
    try:
        from app.models.workspace import Workspace
        from app.services import job_service

        with db.begin_nested():
            workspace = db.get(Workspace, workspace_id)
            if not workspace or workspace.is_sample:
                return
            if not mode.live_for(db, workspace.organization_id):
                return
            # Something to compare: a case that is still open. Otherwise a changed document queues nothing.
            from app.services.trinetra.service import OPEN_STATES
            from app.models.trinetra import TrinetraCredit

            if (
                not db.query(TrinetraCredit.id)
                .filter(TrinetraCredit.workspace_id == workspace_id, TrinetraCredit.state.in_(OPEN_STATES))
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
