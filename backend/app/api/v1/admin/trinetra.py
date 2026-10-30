"""The operator's TRINETRA pilot console (platform superadmins only; Final 2T, N-201).

    GET  /admin/trinetra/pilot                          the mode and every enrolled organization (with the reason)
    PUT  /admin/trinetra/pilot/{organization_id}        enrol an organization (a reason is required; audited)
    POST /admin/trinetra/pilot/{organization_id}/withdraw   take it out again (a reason is required; audited)

`require_superadmin` on the router (404 for anyone else). Both changes are audited on the customer organization
(ORGANIZATION / UPDATED with an `operation`) and shown on that organization's own TRINETRA page. Only mode "pilot"
reads the enrolments; in "on" every entitled organization is live and in "off" none is.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_superadmin
from app.models.organization import Organization
from app.models.trinetra import TrinetraPilot
from app.models.user import User
from app.services.trinetra import mode

router = APIRouter(prefix="/admin/trinetra", tags=["TRINETRA pilot"], dependencies=[Depends(require_superadmin)])


class ReasonIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    reason: str = Field(min_length=10, max_length=500)


def _entry(db: Session, row: TrinetraPilot) -> dict:
    """One enrolled organization. The slug tells two of the same name apart; `entitled` says whether its plan includes TRINETRA
    (an enrolled Starter organization stays on the examples)."""
    organization = db.get(Organization, row.organization_id)
    return {"organization_id": str(row.organization_id), "name": organization.name if organization else None,
            "slug": organization.slug if organization else None,
            "entitled": mode.state(db, row.organization_id).entitled,
            "reason": row.reason, "enrolled_by": str(row.enrolled_by) if row.enrolled_by else None,
            "enrolled_at": row.created_at.isoformat()}


@router.get("/pilot")
def pilot(db: Session = Depends(get_db)) -> dict:
    rows = db.query(TrinetraPilot).order_by(TrinetraPilot.created_at).limit(500).all()
    return {"mode": mode.deployment_mode(), "items": [_entry(db, r) for r in rows]}


@router.put("/pilot/{organization_id}")
def enrol(organization_id: uuid.UUID, body: ReasonIn, db: Session = Depends(get_db),
          admin: User = Depends(require_superadmin)) -> dict:
    if db.get(Organization, organization_id) is None:
        raise HTTPException(404, "Organization not found.")
    row = mode.enrol(db, organization_id=organization_id, actor_id=admin.id, reason=body.reason)
    db.commit()
    return _entry(db, row)


@router.post("/pilot/{organization_id}/withdraw")
def withdraw(organization_id: uuid.UUID, body: ReasonIn, db: Session = Depends(get_db),
             admin: User = Depends(require_superadmin)) -> dict:
    removed = mode.withdraw(db, organization_id=organization_id, actor_id=admin.id, reason=body.reason)
    db.commit()
    return {"organization_id": str(organization_id), "withdrawn": removed}
