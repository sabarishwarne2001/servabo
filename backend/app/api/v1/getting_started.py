"""The first-run checklist (Final session 1, 2C).

    GET /workspaces/{wid}/getting-started      the steps this person can do, each ticked from real data     [VIEWER]

Every tick rule is in `app/services/getting_started.py`. Reads only; a viewer gets the steps a viewer can do.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import RequireWorkspaceViewer, TenantContext, get_read_db
from app.services import getting_started

router = APIRouter(tags=["Getting started"])


@router.get("/workspaces/{workspace_id}/getting-started", summary="The first-run checklist, ticked from real data")
def get_getting_started(
    workspace_id: uuid.UUID,
    db: Session = Depends(get_read_db),
    context: TenantContext = Depends(RequireWorkspaceViewer),
) -> dict[str, Any]:
    if context.workspace_id != workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace not found.")
    return getting_started.evaluate(
        db, organization=context.organization, workspace=context.workspace,
        workspace_role=context.effective_workspace_role, organization_role=context.organization_role,
    )
