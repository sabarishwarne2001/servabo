"""The Monday GST credit digest (Final session 1, 3A).

WHO. The owners, administrators and billing contacts of an organization with an imported GSTR-2B in one of its own workspaces, who
have not turned off the "GST credit" notification category. Never an archived, suspended or unpaid organization, never the sample.

WHEN. Monday from 09:00 in the zone of the organization's oldest workspace, through the end of that day (an hour a worker missed is
made up). The sweep runs hourly.

WHAT. The headline figures, in rupees with Indian grouping, as the monthly summary's block: a headline and up to three lines, each
linking to the GST Credit page. Where the plan opens the lists, the suppliers that owe the most; where it shows only the headline,
one line says what the lists would add and what they cost (taken from the add-on catalogue, never typed here).

ONCE, AND ONLY WHEN THERE IS SOMETHING TO SAY. `gst_notice_sends` (kind `digest`, key the ISO week) is claimed before anything is
built. A week with nothing to report is recorded with 0 recipients and not looked at again. If the relay accepted no email at all,
the claim is removed and the next hourly run tries again.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.gst import GstMatch, GstNoticeSend
from app.services.gst import notices
from app.services.gst import vocabulary as v

logger = logging.getLogger("app.services.gst.digest")

#: In this order, the figures that become lines (the first non-zero one that is not the headline fills three slots).
LINE_ORDER = ("waiting", "at_risk_180", "differences", "not_in_books")
LINE_WORDS = {
    "claimable_now": "Credit claimable now",
    "waiting": "Waiting for suppliers to report",
    "at_risk_180": "Near the 180-day limit",
    "differences": "Differences to settle",
    "not_in_books": "Reported to you but not in your books",
    "not_eligible": "Not eligible per GSTR-2B",
}


def due(db: Session, organization_id: uuid.UUID, now: datetime) -> Optional[str]:
    """The ISO week ("2026-W43") to send for now: a Monday, 09:00 or later in the organization's zone; else None."""
    local = now.astimezone(notices.zone_of(db, organization_id))
    if local.isoweekday() != 1 or local.hour < notices.DIGEST_HOUR:
        return None
    iso = local.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def unlock_line(db: Session, organization_id: uuid.UUID) -> Optional[str]:
    """What the lists would add and what it costs, for a plan that shows only the headline figures; None when the lists are open."""
    from app.core import entitlements
    from app.services.billing import entitlement_service

    if notices.full_access(db, organization_id):
        return None
    if entitlement_service.offered_on_plan(db, organization_id=organization_id, addon_key=entitlements.GST_CREDIT_ADDON):
        offer = entitlement_service.offer_for(entitlements.GST_CREDIT_ADDON)
        dollars = offer.monthly_price_micros // 1_000_000
        symbol = "$" if offer.currency == "USD" else f"{offer.currency} "
        return f"Unlock the lists: {offer.display_name} add-on, {symbol}{dollars} a month"
    names = entitlement_service.tiers_including(db, entitlements.GST_CREDIT_ADDON)
    return f"Unlock the lists: GST Credit comes with {' and '.join(names)}" if names else "Unlock the lists: see your plan options"


def build(db: Session, organization_id: uuid.UUID, *, today: Any = None) -> Optional[dict[str, Any]]:
    """{headline, lines: [(label, amount_text)]} or None when there is nothing to report."""
    figures = notices.figures_of(db, organization_id, today=today)
    if not figures:
        return None
    claimable = figures["claimable_now"]
    lines = []
    for key in LINE_ORDER:
        f = figures[key]
        if f["count"] or f["amount_micros"]:
            noun = "invoice" if f["count"] == 1 else "invoices"
            label = f"{LINE_WORDS[key]}: {f['count']} {noun}"
            if key == "waiting" and f.get("suppliers"):
                label += f" from {f['suppliers']} supplier{'s' if f['suppliers'] != 1 else ''}"
            lines.append((label, notices.money(f["amount_micros"])))
    if not lines and claimable["amount_micros"] <= 0:
        return None
    if claimable["amount_micros"] > 0:   # net of credit notes, so it can be negative: only a positive figure is good news
        headline = f"{notices.money(claimable['amount_micros'])} of GST credit is claimable now."
    else:
        headline = "GST credit needs your attention this week."
    return {"headline": headline, "lines": lines[:3]}


def top_waiting_suppliers(db: Session, organization_id: uuid.UUID, limit: int = 3) -> list[tuple[str, int]]:
    ids = notices.workspace_ids(db, organization_id)
    name = func.coalesce(GstMatch.supplier_name, GstMatch.supplier_gstin, "A supplier")
    return [(n, int(total or 0)) for n, total in db.execute(
        select(name, func.sum(GstMatch.itc_micros)).where(GstMatch.workspace_id.in_(ids), GstMatch.status == v.WAITING_FOR_SUPPLIER)
        .group_by(name).order_by(func.sum(GstMatch.itc_micros).desc().nullslast(), name).limit(limit)).all()]


def recipients(db: Session, organization_id: uuid.UUID) -> list[str]:
    from app.models.organization import MembershipStatus, OrganizationMember
    from app.models.user import User
    from app.services import notification_preferences_service as prefs

    rows = db.execute(
        select(OrganizationMember.user_id, User.email).join(User, User.id == OrganizationMember.user_id)
        .where(OrganizationMember.organization_id == organization_id, OrganizationMember.status == MembershipStatus.ACTIVE,
               OrganizationMember.role.in_(notices.GST_ROLES), User.is_active.is_(True)).order_by(User.email)).all()
    return [email for user_id, email in rows if prefs.email_enabled(db, user_id=user_id, category_key=prefs.GST_CREDIT)]


def send_for(db: Session, organization: Any, *, week: str) -> tuple[bool, int, int]:
    """Build and send one organization's digest. Returns (had something to say, people wanted, emails the relay accepted)."""
    from datetime import date

    from app.core.platform_email import PlatformEmailNotConfigured, send_platform_email
    from app.templates.emails.gst_digest import render_gst_digest
    from app.templates.emails.trial_notice import TrialFinding

    body = build(db, organization.id)
    wanted = recipients(db, organization.id) if body else []
    if body is None:
        return False, 0, 0
    if not wanted:
        return True, 0, 0
    base = settings.FRONTEND_URL.rstrip("/")
    gst_url = f"{base}/organizations/{organization.slug}/gst"
    findings = [TrialFinding(label=label, amount_text=amount, url=gst_url) for label, amount in body["lines"]]
    if notices.full_access(db, organization.id):
        # The lists are open: the digest names who owes the most instead of its third figure.
        top = top_waiting_suppliers(db, organization.id, limit=1)
        if top:
            findings = findings[:2] + [TrialFinding(label=f"Waiting on {top[0][0]}", amount_text=notices.money(top[0][1]), url=gst_url)]
    year, number = (int(part) for part in week.split("-W"))
    monday = date.fromisocalendar(year, number, 1)
    line = unlock_line(db, organization.id)
    subject, html_body, text_body = render_gst_digest(
        organization_name=organization.legal_name or organization.name,
        week_label=f"{monday.day} {notices.MONTH_NAMES[monday.month - 1]} {monday.year}", headline=body["headline"],
        findings=findings, gst_url=gst_url, preferences_url=f"{base}/settings?section=notifications",
        brand_name=settings.PROJECT_NAME, unlock_line=line, unlock_url=f"{base}/organizations/{organization.slug}/billing" if line else None)
    sent = 0
    for email in wanted:
        try:
            delivered, detail = send_platform_email(recipient=email, subject=subject, html_body=html_body, text_body=text_body)
        except PlatformEmailNotConfigured:
            logger.warning("gst_digest.unconfigured")
            break
        except Exception:  # noqa: BLE001 - one address failing must not stop the others
            logger.warning("gst_digest.send_failed", extra={"organization_id": str(organization.id)}, exc_info=True)
            continue
        if delivered:
            sent += 1
        else:
            logger.warning("gst_digest.not_delivered", extra={"detail": str(detail)})
    return True, len(wanted), sent


def run_sweep(db: Session, *, now: Optional[datetime] = None) -> dict[str, int]:
    """Send what is due. Commits per organization. Returns how many organizations were handled and emails sent."""
    from app.models.organization import Organization
    from app.workers.tenant_gate import inactive_reason, unpaid_reason

    moment = now or datetime.now(timezone.utc)
    handled = emails = 0
    for organization_id in notices.organizations_with_returns(db):
        if inactive_reason(db, organization_id=organization_id) or unpaid_reason(db, organization_id=organization_id):
            continue
        week = due(db, organization_id, moment)
        if week is None or db.get(GstNoticeSend, (organization_id, notices.KIND_DIGEST, week)) is not None:
            continue
        try:
            if not notices.claim(db, organization_id, notices.KIND_DIGEST, week):
                db.rollback()
                continue
            organization = db.get(Organization, organization_id)
            had_something, wanted, sent = send_for(db, organization, week=week)
            if wanted and not sent:
                db.rollback()          # the relay took nothing: the claim goes with it, so the next run tries again
                logger.warning("gst_digest.retry_later", extra={"organization_id": str(organization_id)})
                continue
            row = db.get(GstNoticeSend, (organization_id, notices.KIND_DIGEST, week))
            row.recipients = sent
            db.commit()
            handled += 1
            emails += sent
        except Exception:  # noqa: BLE001 - one organization failing must not stop the others
            db.rollback()
            logger.warning("gst_digest.organization_failed", extra={"organization_id": str(organization_id)}, exc_info=True)
    return {"organizations": handled, "emails": emails}


def handle_digest(payload: dict[str, Any]) -> dict[str, Any]:
    from app.db import session as session_module

    with session_module.SessionLocal() as db:
        return run_sweep(db, now=notices.payload_now(payload))


__all__ = ["build", "due", "handle_digest", "recipients", "run_sweep", "send_for", "unlock_line"]
