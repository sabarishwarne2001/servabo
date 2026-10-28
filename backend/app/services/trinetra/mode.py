"""Is TRINETRA live for this organization? One helper, used by every gate (Final 2T, Phase 2.1; N-201).

    off    nobody has live TRINETRA; everyone sees the synthetic preview.
    pilot  only organizations a platform administrator enrolled (a reason, audited).
    on     every organization whose plan includes capability.trinetra (Business and Enterprise).

`TRINETRA_LIVE_ENABLED` is kept as an alias (true is "on", false is "off") so an old deployment file means what it said.
The safety hold on Helm's reminders deliberately does not use this: a recorded confirmation keeps holding in every mode."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.trinetra import TrinetraPilot

OFF, PILOT, ON = "off", "pilot", "on"
CAPABILITY = "capability.trinetra"


def deployment_mode() -> str:
    """The deployment's mode: the old boolean alias wins when it is set."""
    alias = settings.TRINETRA_LIVE_ENABLED
    if alias is not None:
        return ON if alias else OFF
    return settings.TRINETRA_MODE


@dataclass(frozen=True)
class LiveState:
    mode: str
    enrolled: bool
    enrolled_since: Optional[datetime]
    entitled: bool
    live: bool
    #: Why it is not live ("off", "not_enrolled", "not_entitled"), or None when it is.
    reason: Optional[str]


def enrolment(db: Session, organization_id: uuid.UUID) -> Optional[TrinetraPilot]:
    return db.get(TrinetraPilot, organization_id)


def state(db: Session, organization_id: uuid.UUID) -> LiveState:
    from app.api.capability_gate import has_capability

    deployment = deployment_mode()
    row = enrolment(db, organization_id)
    entitled = has_capability(db, organization_id=organization_id, capability_key=CAPABILITY)
    if deployment == OFF:
        reason = "off"
    elif deployment == PILOT and row is None:
        reason = "not_enrolled"
    elif not entitled:
        reason = "not_entitled"
    else:
        reason = None
    return LiveState(deployment, row is not None, row.created_at if row else None, entitled, reason is None, reason)


def live_for(db: Session, organization_id: uuid.UUID) -> bool:
    """True when live TRINETRA may process this organization's evidence now (mode and plan both allow it)."""
    return state(db, organization_id).live


def require_mode(db: Session, organization_id: uuid.UUID) -> None:
    """The route gate, after the plan check: refuse with a plain, specific reason when the mode does not allow it."""
    deployment = deployment_mode()
    if deployment == ON:
        return
    if deployment == PILOT and enrolment(db, organization_id) is not None:
        return
    if deployment == PILOT:
        raise HTTPException(409, {
            "code": "TRINETRA_NOT_ENROLLED",
            "message": "TRINETRA is in a pilot and your organization is not enrolled yet. Explore the synthetic "
                       "examples; Servabo will open it for Business and Enterprise organizations when the pilot ends."})
    raise HTTPException(409, {
        "code": "TRINETRA_SOURCE_REVIEW_REQUIRED",
        "message": "Live access awaits official-source and tax-adviser validation. Explore the synthetic examples."})


def enrol(db: Session, *, organization_id: uuid.UUID, actor_id: Optional[uuid.UUID], reason: str) -> TrinetraPilot:
    row = enrolment(db, organization_id)
    if row is None:
        row = TrinetraPilot(organization_id=organization_id, enrolled_by=actor_id, reason=reason)
        db.add(row)
    else:
        row.reason, row.enrolled_by = reason, actor_id
    db.flush()
    _audit(db, organization_id, actor_id, "trinetra.pilot_enrolled", reason)
    return row


def withdraw(db: Session, *, organization_id: uuid.UUID, actor_id: Optional[uuid.UUID], reason: str) -> bool:
    row = enrolment(db, organization_id)
    if row is None:
        return False
    db.delete(row)
    db.flush()
    _audit(db, organization_id, actor_id, "trinetra.pilot_withdrawn", reason)
    return True


def _audit(db: Session, organization_id, actor_id, operation: str, reason: str) -> None:
    from app.models.audit_log import AuditAction, AuditOutcome, AuditResourceType
    from app.services import audit_service

    audit_service.record(db, organization_id=organization_id, actor_id=actor_id,
                         resource_type=AuditResourceType.ORGANIZATION, resource_id=organization_id,
                         action=AuditAction.UPDATED, outcome=AuditOutcome.ALLOWED,
                         details={"operation": operation, "reason": reason[:500]})


def enrolled_count(db: Session) -> int:
    return db.query(TrinetraPilot).count()
