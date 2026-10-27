"""Warning emails after a workspace or organization is deleted (Final session 2A, Phase 4; closes the open part of N-164).

Deleting archives; `purge_service.sweep_archived` erases the content `ARCHIVED_PURGE_GRACE_DAYS` (30) days after the
archive and Restore works until then. The owners and admins of the organization are emailed twice:

  ARCHIVED     at the first hourly run after the deletion ("will be erased on <date>; restore until then");
  LAST_CHANCE  from 5 days before the erasure ("last chance to restore").

Each is sent once: the row in `deletion_notice_sends` (keyed by what was deleted, the warning and the archive moment) is
claimed before sending and kept only when the relay accepted at least one email, so a retried or doubled job never sends a
warning twice and a relay that took nothing is tried again next hour. A restore ends the warnings (only ARCHIVED things are
looked at); a later deletion has a new archive moment and is warned again. A workspace of an organization that is itself
deleted is covered by the organization's email. Nothing is sent once the erasure date has passed.

Runs hourly as the `compliance.deletion_notices` job (`DEFAULT_SCHEDULE`, LIGHT profile).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.audit_log import AuditResourceType
from app.models.deletion_notice_send import DeletionNoticeSend
from app.models.organization import MembershipStatus, Organization, OrganizationMember, OrganizationRole, OrganizationStatus
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceStatus
from app.services.compliance.purge_service import archived_at

logger = logging.getLogger("app.services.compliance.deletion_notices")

JOB_TYPE = "compliance.deletion_notices"
ARCHIVED, LAST_CHANCE = "ARCHIVED", "LAST_CHANCE"
LAST_CHANCE_BEFORE = timedelta(days=5)
AUDIENCE = (OrganizationRole.OWNER, OrganizationRole.ADMIN)
MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November",
          "December")


@dataclass(frozen=True)
class Due:
    scope_type: str                   # WORKSPACE or ORGANIZATION
    scope_id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    organization_name: str
    organization_slug: str
    archived: datetime
    erase_on: datetime
    kind: str


def _day(value: datetime) -> str:
    return f"{value.day} {MONTHS[value.month - 1]} {value.year}"


def _kind(archived: datetime, now: datetime, grace: timedelta) -> Optional[str]:
    erase_on = archived + grace
    if now >= erase_on:
        return None
    return LAST_CHANCE if now >= erase_on - LAST_CHANCE_BEFORE else ARCHIVED


def due(db: Session, *, now: Optional[datetime] = None) -> list[Due]:
    """Every warning that should be sent now and has not been. The ARCHIVED warning is skipped when the deletion is
    already inside the last five days (the LAST_CHANCE one says everything and arrives at once)."""
    moment = now or datetime.now(timezone.utc)
    grace = timedelta(days=settings.ARCHIVED_PURGE_GRACE_DAYS)
    found: list[Due] = []
    archived_orgs = {o.id: o for o in db.execute(sa.select(Organization).where(
        Organization.status == OrganizationStatus.ARCHIVED)).scalars()}
    for org in archived_orgs.values():
        when = archived_at(db, AuditResourceType.ORGANIZATION, org.id)
        kind = _kind(when, moment, grace) if when else None
        if kind:
            found.append(Due("ORGANIZATION", org.id, org.id, org.legal_name or org.name, org.legal_name or org.name,
                             org.slug, when, when + grace, kind))
    rows = db.execute(sa.select(Workspace, Organization).join(Organization, Organization.id == Workspace.organization_id)
                      .where(Workspace.status == WorkspaceStatus.ARCHIVED)).all()
    for workspace, org in rows:
        if org.id in archived_orgs:
            continue  # the organization's own warning covers it
        when = archived_at(db, AuditResourceType.WORKSPACE, workspace.id)
        kind = _kind(when, moment, grace) if when else None
        if kind:
            found.append(Due("WORKSPACE", workspace.id, org.id, workspace.workspace_name, org.legal_name or org.name, org.slug,
                             when, when + grace, kind))
    sent = {(r.scope_id, r.kind, r.archived_at) for r in db.execute(sa.select(DeletionNoticeSend)).scalars()}
    return [d for d in found if (d.scope_id, d.kind, d.archived) not in sent]


def recipients(db: Session, organization_id: uuid.UUID) -> list[str]:
    """The organization's active owners and admins. Not optional: a deletion warning cannot be turned off."""
    return list(db.execute(
        sa.select(User.email).join(OrganizationMember, OrganizationMember.user_id == User.id)
        .where(OrganizationMember.organization_id == organization_id, OrganizationMember.status == MembershipStatus.ACTIVE,
               OrganizationMember.role.in_(AUDIENCE), User.is_active.is_(True))
        .order_by(User.email)).scalars())


def _restore_url(item: Due) -> str:
    # The workspace picker lists a deleted organization, and a deleted workspace, each with its Restore button (F-131/F-132).
    return f"{settings.FRONTEND_URL.rstrip('/')}/workspaces"


def _send(db: Session, item: Due) -> tuple[int, int]:
    from app.core.platform_email import PlatformEmailNotConfigured, send_platform_email
    from app.templates.emails.deletion_notice import render_deletion_notice

    subject, html_body, text_body = render_deletion_notice(
        kind=item.kind, scope="workspace" if item.scope_type == "WORKSPACE" else "organization", name=item.name,
        organization_name=item.organization_name, erase_on=_day(item.erase_on), restore_url=_restore_url(item),
        brand_name=settings.PROJECT_NAME)
    wanted = recipients(db, item.organization_id)
    sent = 0
    for email in wanted:
        try:
            delivered, detail = send_platform_email(recipient=email, subject=subject, html_body=html_body, text_body=text_body)
        except PlatformEmailNotConfigured:
            logger.warning("deletion_notice.unconfigured")
            break
        except Exception:  # noqa: BLE001 - one address failing must not stop the others
            logger.warning("deletion_notice.send_failed", extra={"scope_id": str(item.scope_id)}, exc_info=True)
            continue
        if delivered:
            sent += 1
        else:
            logger.warning("deletion_notice.not_delivered", extra={"detail": str(detail)})
    return len(wanted), sent


def run(db: Session, *, now: Optional[datetime] = None) -> dict[str, int]:
    """Send every warning that is due. Commits per warning. Returns how many warnings went out and how many emails."""
    warnings = emails = 0
    for item in due(db, now=now):
        try:
            claimed = db.execute(pg_insert(DeletionNoticeSend).values(
                organization_id=item.organization_id, scope_id=item.scope_id, kind=item.kind, archived_at=item.archived,
                scope_type=item.scope_type).on_conflict_do_nothing().returning(DeletionNoticeSend.scope_id)).first()
            if claimed is None:
                db.rollback()
                continue
            wanted, sent = _send(db, item)
            if wanted and not sent:
                db.rollback()  # the relay took nothing: the claim goes with it, so the next run tries again
                continue
            db.execute(sa.update(DeletionNoticeSend).where(
                DeletionNoticeSend.scope_id == item.scope_id, DeletionNoticeSend.kind == item.kind,
                DeletionNoticeSend.archived_at == item.archived).values(recipients=sent))
            db.commit()
            warnings += 1
            emails += sent
        except Exception:  # noqa: BLE001 - one warning failing must not stop the others
            db.rollback()
            logger.warning("deletion_notice.failed", extra={"scope_id": str(item.scope_id)}, exc_info=True)
    return {"warnings": warnings, "emails": emails}


def handle(payload: dict[str, Any]) -> dict[str, Any]:
    from app.db.session import SessionLocal
    from app.services.gst.notices import payload_now

    # `now` in the payload (`e2e_stand_in.py run-job --now`) lets a rehearsal see the LAST_CHANCE email without waiting
    # 25 days; it is ignored in production.
    with SessionLocal() as db:
        return {"outcome": "COMPLETED", **run(db, now=payload_now(payload))}


__all__ = ["ARCHIVED", "JOB_TYPE", "LAST_CHANCE", "due", "handle", "recipients", "run"]
