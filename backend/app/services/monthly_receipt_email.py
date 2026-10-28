"""The monthly summary: last month's value receipt, emailed on the 1st (Session H, Part 3).

    run_sweep(db, now=None)      what the hourly `receipt.monthly` job does; returns {"organizations", "emails"}

WHO. The owners (active members with the OWNER role) of a PAYING organization: one with a live gateway subscription that
is entitled (active, trialing or past due) and not held for an overdue payment. Never the free trial (its two emails
are `trial.reminders`), an archived organization, or the sample company.

WHEN. The 1st of each month from 09:00 in the zone of the organization's oldest workspace (organizations have no clock
of their own, N-064; the same zone the receipt's month uses), through the end of that day, so an hour the worker missed
is made up. The sweep runs hourly.

WHAT. The receipt of the month before (`value_receipt.receipt(..., "month", previous=True)`): the headline and up to
three findings, each with a link to its evidence (`trial_notice.receipt_block`), one button to the Overview.
Nothing is sent when the month holds no finding: an email that says "nothing found" is never written.

ONCE. One `monthly_receipt_sends` row per organization and month is inserted before anything is built (an insert that
does nothing when it exists), so two workers or a retried job never send a month twice. A month with nothing to say is
recorded with 0 recipients and not looked at again. If the relay accepted no email at all, the row is removed and the
next run (still the 1st) tries again.

OPT-OUT. The "Monthly summary" notification category, on by default; an owner who turned it off is skipped.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.notification_preference import MonthlyReceiptSend

logger = logging.getLogger("app.services.monthly_receipt_email")

SEND_HOUR = 9
MONTH_NAMES = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
               "November", "December")


def _zone(db: Session, organization_id: Any) -> ZoneInfo:
    from app.services import value_receipt

    workspaces = value_receipt._workspaces(db, organization_id)  # noqa: SLF001 - the receipt's own zone rule
    return value_receipt._zone(workspaces[0].timezone if workspaces else "UTC")  # noqa: SLF001


def due_period(db: Session, organization_id: Any, now: datetime) -> Optional[tuple[str, str]]:
    """`("2026-09", "September 2026")` when it is the 1st, 09:00 or later, in the organization's zone; else None."""
    local = now.astimezone(_zone(db, organization_id))
    if local.day != 1 or local.hour < SEND_HOUR:
        return None
    year, month = (local.year, local.month - 1) if local.month > 1 else (local.year - 1, 12)
    return f"{year:04d}-{month:02d}", f"{MONTH_NAMES[month - 1]} {year}"


def paying_organizations(db: Session) -> list[Any]:
    """Active organizations with an entitled gateway subscription, oldest first."""
    from app.models.billing_account import BillingAccount
    from app.models.organization import Organization, OrganizationStatus
    from app.models.subscription import ENTITLED_SUBSCRIPTION_STATUSES, Subscription

    return list(db.execute(
        select(Organization).join(BillingAccount, BillingAccount.organization_id == Organization.id)
        .join(Subscription, Subscription.billing_account_id == BillingAccount.id)
        .where(Organization.status == OrganizationStatus.ACTIVE,
               Subscription.status.in_(ENTITLED_SUBSCRIPTION_STATUSES))
        .group_by(Organization.id).order_by(Organization.created_at, Organization.id)).scalars())


def owners_to_email(db: Session, organization_id: Any) -> list[tuple[Any, str]]:
    from app.models.organization import MembershipStatus, OrganizationMember, OrganizationRole
    from app.models.user import User
    from app.services import notification_preferences_service as prefs

    rows = db.execute(
        select(OrganizationMember.user_id, User.email).join(User, User.id == OrganizationMember.user_id)
        .where(OrganizationMember.organization_id == organization_id,
               OrganizationMember.status == MembershipStatus.ACTIVE,
               OrganizationMember.role == OrganizationRole.OWNER, User.is_active.is_(True))
        .order_by(User.email)).all()
    return [(user_id, email) for user_id, email in rows
            if prefs.email_enabled(db, user_id=user_id, category_key=prefs.MONTHLY_SUMMARY)]


def _claim(db: Session, organization_id: Any, period: str) -> bool:
    """True when this run is the one that gets to handle the month."""
    inserted = db.execute(
        pg_insert(MonthlyReceiptSend).values(organization_id=organization_id, period=period)
        .on_conflict_do_nothing(index_elements=["organization_id", "period"])
        .returning(MonthlyReceiptSend.period)).first()
    return inserted is not None


def _overview_url(organization: Any, workspaces: list[Any]) -> str:
    base = settings.FRONTEND_URL.rstrip("/")
    return f"{base}/{organization.slug}/{workspaces[0].slug}" if workspaces else f"{base}/{organization.slug}"


@dataclass(frozen=True)
class Outcome:
    """What one organization's month came to: findings read, owners who wanted it, emails the relay accepted."""

    findings: int
    wanted: int
    sent: int


def send_for(db: Session, organization: Any, *, period: str, label: str, now: datetime) -> Outcome:
    """Build and send one organization's month. Records the counts on the claimed row; commits nothing."""
    from app.core.platform_email import PlatformEmailNotConfigured, send_platform_email
    from app.services import value_receipt
    from app.templates.emails.monthly_receipt import render_monthly_receipt
    from app.templates.emails.trial_notice import MAX_FINDINGS, TrialFinding

    body = value_receipt.receipt(db, organization.id, value_receipt.MONTH, now=now, previous=True)
    found = list(body.get("found") or [])
    recipients = owners_to_email(db, organization.id) if found and body.get("headline") else []
    if not recipients:
        return Outcome(len(found), 0, 0)

    base = settings.FRONTEND_URL.rstrip("/")
    # Recoveries (N-191): what was recovered and verified always has its line beside what was found (never added).
    recovered = [f for f in found if f["key"].startswith("recovered_verified_")][:1]
    shown = [f for f in found if f not in recovered][:MAX_FINDINGS - len(recovered)] + recovered
    findings = [TrialFinding(label=f["label"], amount_text=f.get("amount_text"), url=f"{base}{f['source']}")
                for f in shown]
    workspaces = value_receipt._workspaces(db, organization.id)  # noqa: SLF001
    subject, html_body, text_body = render_monthly_receipt(
        organization_name=organization.name, month_label=label, headline=body["headline"], findings=findings,
        overview_url=_overview_url(organization, workspaces),
        preferences_url=f"{base}/settings?section=notifications", brand_name=settings.PROJECT_NAME)
    sent = 0
    for _user_id, email in recipients:
        try:
            delivered, detail = send_platform_email(recipient=email, subject=subject, html_body=html_body,
                                                    text_body=text_body)
        except PlatformEmailNotConfigured:
            logger.warning("monthly_receipt.unconfigured")
            break
        except Exception:  # noqa: BLE001 - one address failing must not stop the others
            logger.warning("monthly_receipt.send_failed", extra={"organization_id": str(organization.id)}, exc_info=True)
            continue
        if delivered:
            sent += 1
        else:
            logger.warning("monthly_receipt.not_delivered", extra={"detail": str(detail)})
    return Outcome(len(found), len(recipients), sent)


def run_sweep(db: Session, *, now: Optional[datetime] = None) -> dict[str, int]:
    """Send what is due. Commits per organization. Returns how many organizations were handled and emails sent."""
    from app.workers.tenant_gate import inactive_reason, unpaid_reason

    moment = now or datetime.now(timezone.utc)
    handled = emails = 0
    for organization in paying_organizations(db):
        if inactive_reason(db, organization_id=organization.id) or unpaid_reason(db, organization_id=organization.id):
            continue
        due = due_period(db, organization.id, moment)
        if due is None:
            continue
        period, label = due
        if db.get(MonthlyReceiptSend, (organization.id, period)) is not None:
            continue
        try:
            if not _claim(db, organization.id, period):
                db.rollback()
                continue
            outcome = send_for(db, organization, period=period, label=label, now=moment)
            if outcome.wanted and not outcome.sent:
                db.rollback()          # the relay took nothing: the claim goes with it, so the next run tries again
                logger.warning("monthly_receipt.retry_later", extra={"organization_id": str(organization.id)})
                continue
            row = db.get(MonthlyReceiptSend, (organization.id, period))
            row.recipients, row.findings = outcome.sent, outcome.findings if outcome.sent else 0
            db.commit()
            handled += 1
            emails += outcome.sent
        except Exception:  # noqa: BLE001 - one organization failing must not stop the others
            db.rollback()
            logger.warning("monthly_receipt.organization_failed", extra={"organization_id": str(organization.id)},
                           exc_info=True)
    return {"organizations": handled, "emails": emails}


def handle_monthly(payload: dict[str, Any]) -> dict[str, Any]:
    from app.db import session as session_module

    with session_module.SessionLocal() as db:
        result = run_sweep(db)
    if result["emails"]:
        logger.info("monthly_receipt.sent", extra=result)
    return result


__all__ = ["MONTH_NAMES", "due_period", "handle_monthly", "owners_to_email", "paying_organizations", "run_sweep",
           "send_for"]
