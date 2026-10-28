"""TDS-credit notices and the Monday line (Final 2T, Phase 7.3 and 7.4).

The owner should hear about a TDS case without opening the page, but only about what changed. Three things are worth a notice, each
in the "TDS credit" category (on by default; organization owners and administrators):

  stale     a confirmed withholding lost its evidence (the invoice or a piece of evidence really changed)       {WARNING}
  missing   an import turned a case into a "possible missing posting"                                           {WARNING}
  due       a case is still open, with the tax not matched in the statement, after DUE_AFTER_DAYS days          {WARNING}

ONE NOTICE PER CASE REVISION. `trinetra_notice_sends` holds a row per (organization, kind, "<case>:<revision>"); the insert is the
claim, so a replayed job, two workers or an hourly sweep never say a thing twice, and a new revision of a case can speak again. A
closed case never speaks. When more than BUNDLE_AFTER cases are fresh at once (a first import into a large book), they are one notice
that counts them; each case is still claimed.

NOTHING THAT IS A CONCLUSION. A notice names the invoice, the customer and the amount the business's own records show was withheld.
It never names a PAN or a TAN, never says a customer failed to file or deposit, and never calls the gap money. It is a thing to check.

THE MONDAY LINE. "₹X of TDS across N invoices is not yet in your statement", with what is now visible and the cases whose evidence
needs a look: once per ISO week, only when there is something to say, to owners and administrators who have not switched the
category off. The figure is a possible gap in the tax statement, NEVER cash and never added to a GST or cash figure.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.display_format import format_amount_micros
from app.models.notification import NotificationPriority, NotificationType
from app.models.organization import MembershipStatus, Organization, OrganizationMember, OrganizationRole, OrganizationStatus
from app.models.trinetra import TrinetraCredit, TrinetraNoticeSend
from app.models.workspace import Workspace
from app.services.trinetra import mode
from app.services.trinetra.service import OPEN_STATES, RESOLVED_STATUSES

logger = logging.getLogger("app.services.trinetra.notices")

KIND_STALE, KIND_MISSING, KIND_DUE, KIND_DIGEST, KIND_BUNDLE = "stale", "missing", "due", "digest", "bundle"
#: Who hears: the people who act on a case.
ROLES: tuple[OrganizationRole, ...] = (OrganizationRole.OWNER, OrganizationRole.ADMIN)
#: A case with the tax still not matched this many days after it was opened is past its due date (N-209).
DUE_AFTER_DAYS = 30
#: More fresh cases than this at once are told as one notice.
BUNDLE_AFTER = 5
DIGEST_HOUR = 9
#: Statuses that mean "the tax is not yet in the statement and the amount is known".
GAP_STATUSES = ("POSSIBLE_MISSING_POSTING", "AMOUNT_MISMATCH", "SUGGESTED", "AMBIGUOUS", "DUPLICATE_SUSPECTED", "TAN_MISMATCH_SUSPECTED")

_TITLES = {
    KIND_STALE: "The evidence behind a TDS confirmation changed",
    KIND_MISSING: "A TDS credit may be missing from your statement",
    KIND_DUE: "A TDS case is past its due date",
}


def claim(db: Session, organization_id: uuid.UUID, kind: str, key: str) -> bool:
    """True when this call is the one that gets to say it (the insert found no row)."""
    inserted = db.execute(
        pg_insert(TrinetraNoticeSend).values(organization_id=organization_id, kind=kind, key=key)
        .on_conflict_do_nothing(index_elements=["organization_id", "kind", "key"]).returning(TrinetraNoticeSend.key)).first()
    return inserted is not None


def money(micros: Optional[int]) -> str:
    return format_amount_micros(int(micros or 0), "INR")


def _evidence_lost(item: dict) -> bool:
    """A confirmed withholding whose evidence is no longer the evidence it was confirmed on."""
    if not item.get("source_current", True):
        return True
    return any(e.get("current") is False for e in (item.get("review") or {}).get("evidence", []))


def events(items: Iterable[dict]) -> list[dict[str, Any]]:
    """The things worth saying about these case views: [{kind, case_id, revision, reference, customer}]. Closed cases are skipped."""
    found: list[dict[str, Any]] = []
    for item in items:
        if item["review_state"] not in OPEN_STATES:
            continue
        base = {"case_id": item["id"], "revision": item["revision"], "reference": item["reference"], "customer": item["counterparty"],
                "days": item["age_days"]}
        if _evidence_lost(item):
            found.append({**base, "kind": KIND_STALE})
        elif item["status"] == "POSSIBLE_MISSING_POSTING":
            found.append({**base, "kind": KIND_MISSING})
        if item["status"] not in RESOLVED_STATUSES and item["age_days"] > DUE_AFTER_DAYS:
            found.append({**base, "kind": KIND_DUE})
    return found


def _sentence(event: dict, amount: str) -> str:
    who = f"invoice {event['reference']} ({event['customer']}, {amount})"
    if event["kind"] == KIND_STALE:
        return (f"The evidence behind the TDS withheld on {who} changed after it was confirmed, so the confirmation no longer counts. "
                "Open the case, look at the new evidence and confirm again.")
    if event["kind"] == KIND_MISSING:
        return (f"The latest statement import has no posting that matches the TDS withheld on {who}. This is a possible missing "
                "posting to check with your customer or accountant. It is not a conclusion.")
    return (f"The case for {who} has been open for {event['days']} days and the tax is still not matched in your statement. "
            "Decide what to do next: ask the customer for the document, add evidence, or close it with a reason.")


def _tell(db: Session, organization_id: uuid.UUID, *, title: str, message: str) -> int:
    from app.services import notification_preferences_service as prefs
    from app.services import organization_notification_service as notices

    return notices.emit_to_roles(
        db, organization_id=organization_id, roles=ROLES, title=title, message=message, notification_type=NotificationType.SYSTEM,
        priority=NotificationPriority.WARNING, category=prefs.TDS_CREDIT, action="trinetra")


def announce(db: Session, workspace: Workspace, items: list[dict]) -> dict[str, int]:
    """Say what is new about these cases, once. Never raises into the job that calls it. Returns {kind: how many cases}."""
    told: dict[str, int] = {}
    if workspace.is_sample or not mode.live_for(db, workspace.organization_id):
        return told
    try:
        with db.begin_nested():
            fresh = [e for e in events(items) if claim(db, workspace.organization_id, e["kind"], f"{e['case_id']}:{e['revision']}")]
            if not fresh:
                return told
            amounts = {str(r.id): r.expected_micros for r in db.execute(
                select(TrinetraCredit.id, TrinetraCredit.expected_micros).where(
                    TrinetraCredit.workspace_id == workspace.id, TrinetraCredit.id.in_([uuid.UUID(e["case_id"]) for e in fresh]))).all()}
            for e in fresh:
                told[e["kind"]] = told.get(e["kind"], 0) + 1
            if len(fresh) > BUNDLE_AFTER:
                parts = ", ".join(f"{n} {_PHRASE[k]}" for k, n in told.items())
                people = _tell(db, workspace.organization_id, title=f"{len(fresh)} TDS cases need a look",
                               message=f"In {workspace.workspace_name}: {parts}. Open TDS credit to see which, with the reason for each.")
                db.execute(pg_insert(TrinetraNoticeSend).values(
                    organization_id=workspace.organization_id, kind=KIND_BUNDLE, key=uuid.uuid4().hex, recipients=people))
            else:
                for e in fresh:
                    _tell(db, workspace.organization_id, title=_TITLES[e["kind"]], message=_sentence(e, money(amounts.get(e["case_id"]))))
            _announce_elsewhere(db, workspace, fresh, amounts)
    except Exception:  # noqa: BLE001 - a notice must never fail the job that found the change
        logger.warning("trinetra.notice_failed", exc_info=True)
        return {}
    return told


_PHRASE = {KIND_STALE: "with changed evidence", KIND_MISSING: "with a possible missing posting", KIND_DUE: "past their due date"}


def _announce_elsewhere(db: Session, workspace: Workspace, fresh: list[dict], amounts: dict) -> None:
    """Hook for the automation triggers and webhooks of the same moments (added with Phase 7.6 and 7.7)."""
    return None


# ------------------------------------------------------------------------------------------------ the sweep and the Monday line


def organizations_with_open_cases(db: Session) -> list[uuid.UUID]:
    return list(db.execute(
        select(Organization.id).join(TrinetraCredit, TrinetraCredit.organization_id == Organization.id)
        .join(Workspace, Workspace.id == TrinetraCredit.workspace_id)
        .where(Organization.status == OrganizationStatus.ACTIVE, TrinetraCredit.state.in_(OPEN_STATES), Workspace.is_sample.is_(False))
        .group_by(Organization.id, Organization.created_at).order_by(Organization.created_at, Organization.id)).scalars())


def digest_week(db: Session, organization_id: uuid.UUID, now: datetime) -> Optional[str]:
    """The ISO week ("2026-W43") to send for now: a Monday, 09:00 or later in the organization's zone; else None."""
    from app.services.gst import notices as gst_notices

    local = now.astimezone(gst_notices.zone_of(db, organization_id))
    if local.isoweekday() != 1 or local.hour < DIGEST_HOUR:
        return None
    iso = local.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def figures(db: Session, organization_id: uuid.UUID) -> dict[str, Any]:
    """What the Monday line can say: {gap_micros, gap_cases, stale, due, now_visible_micros}, summed over the organization's own
    workspaces. A legal entity has one profile in one workspace (one PAN, one profile per organization), so nothing is counted twice."""
    from app.services.trinetra import outcomes, service

    total = {"gap_micros": 0, "gap_cases": 0, "stale": 0, "due": 0, "missing": 0, "now_visible_micros": 0}
    for workspace in db.execute(select(Workspace).where(Workspace.organization_id == organization_id, Workspace.is_sample.is_(False))
                                .order_by(Workspace.created_at)).scalars():
        result = service.summary(db, workspace)
        for item in result["items"]:
            if item["review_state"] not in OPEN_STATES:
                continue
            if item["status"] in GAP_STATUSES and (item["gap_micros"] or 0) > 0:
                total["gap_micros"] += item["gap_micros"]
                total["gap_cases"] += 1
            if _evidence_lost(item):
                total["stale"] += 1
            if item["status"] == "POSSIBLE_MISSING_POSTING":
                total["missing"] += 1
            if item["status"] not in RESOLVED_STATUSES and item["age_days"] > DUE_AFTER_DAYS:
                total["due"] += 1
        total["now_visible_micros"] += outcomes.ledger(db, workspace)["now_visible_this_month_micros"]
    return total


def digest_body(db: Session, organization_id: uuid.UUID) -> Optional[dict[str, Any]]:
    """{headline, lines} or None when there is nothing to report."""
    f = figures(db, organization_id)
    lines: list[str] = []
    if f["missing"]:
        lines.append(f"{f['missing']} possible missing posting{'s' if f['missing'] != 1 else ''} to check with the customer")
    if f["stale"]:
        lines.append(f"{f['stale']} case{'s' if f['stale'] != 1 else ''} whose evidence changed and needs a look")
    if f["due"]:
        lines.append(f"{f['due']} case{'s' if f['due'] != 1 else ''} past the due date")
    if f["now_visible_micros"]:
        lines.append(f"{money(f['now_visible_micros'])} of TDS now visible in your statement this month (evidence, not cash)")
    if f["gap_cases"]:
        word = "invoice" if f["gap_cases"] == 1 else "invoices"
        headline = f"{money(f['gap_micros'])} of TDS across {f['gap_cases']} {word} is not yet in your statement."
    elif lines:
        headline = "A few TDS cases need your attention this week."
    else:
        return None
    return {"headline": headline, "lines": lines[:3]}


def recipients(db: Session, organization_id: uuid.UUID) -> list[str]:
    from app.models.user import User
    from app.services import notification_preferences_service as prefs

    rows = db.execute(
        select(OrganizationMember.user_id, User.email).join(User, User.id == OrganizationMember.user_id)
        .where(OrganizationMember.organization_id == organization_id, OrganizationMember.status == MembershipStatus.ACTIVE,
               OrganizationMember.role.in_(ROLES), User.is_active.is_(True)).order_by(User.email)).all()
    return [email for user_id, email in rows if prefs.email_enabled(db, user_id=user_id, category_key=prefs.TDS_CREDIT)]


def send_digest(db: Session, organization: Organization, *, week: str) -> tuple[bool, int, int]:
    """Build and send one organization's Monday line. Returns (had something to say, people wanted, emails the relay accepted)."""
    from datetime import date

    from app.core.platform_email import PlatformEmailNotConfigured, send_platform_email
    from app.services.gst.notices import MONTH_NAMES
    from app.templates.emails.trinetra import render_trinetra_digest

    body = digest_body(db, organization.id)
    if body is None:
        return False, 0, 0
    wanted = recipients(db, organization.id)
    if not wanted:
        return True, 0, 0
    base = settings.FRONTEND_URL.rstrip("/")
    year, number = (int(part) for part in week.split("-W"))
    monday = date.fromisocalendar(year, number, 1)
    subject, html_body, text_body = render_trinetra_digest(
        organization_name=organization.legal_name or organization.name,
        week_label=f"{monday.day} {MONTH_NAMES[monday.month - 1]} {monday.year}", headline=body["headline"], lines=body["lines"],
        trinetra_url=f"{base}/organizations/{organization.slug}/trinetra", preferences_url=f"{base}/settings?section=notifications",
        brand_name=settings.PROJECT_NAME)
    sent = 0
    for email in wanted:
        try:
            delivered, detail = send_platform_email(recipient=email, subject=subject, html_body=html_body, text_body=text_body)
        except PlatformEmailNotConfigured:
            logger.warning("trinetra_digest.unconfigured")
            break
        except Exception:  # noqa: BLE001 - one address failing must not stop the others
            logger.warning("trinetra_digest.send_failed", extra={"organization_id": str(organization.id)}, exc_info=True)
            continue
        if delivered:
            sent += 1
        else:
            logger.warning("trinetra_digest.not_delivered", extra={"detail": str(detail)})
    return True, len(wanted), sent


def _old_open_cases_unclaimed(db: Session, organization_id: uuid.UUID, now: datetime) -> bool:
    """Cheap pre-check for the sweep: is there an open case past its due date that has not been told yet?"""
    from datetime import timedelta

    cutoff = now - timedelta(days=DUE_AFTER_DAYS)
    rows = db.execute(select(TrinetraCredit.id, TrinetraCredit.revision).where(
        TrinetraCredit.organization_id == organization_id, TrinetraCredit.state.in_(OPEN_STATES), TrinetraCredit.created_at < cutoff)
        .limit(500)).all()
    if not rows:
        return False
    told = set(db.execute(select(TrinetraNoticeSend.key).where(
        TrinetraNoticeSend.organization_id == organization_id, TrinetraNoticeSend.kind == KIND_DUE,
        TrinetraNoticeSend.key.in_([f"{i}:{r}" for i, r in rows]))).scalars())
    return any(f"{i}:{r}" not in told for i, r in rows)


def run_sweep(db: Session, *, now: Optional[datetime] = None) -> dict[str, int]:
    """The hourly sweep: the due-date notices (once each) and, on Monday from 09:00, the digest. Commits per organization."""
    from app.services.trinetra import service
    from app.workers.tenant_gate import inactive_reason, unpaid_reason

    moment = now or datetime.now(timezone.utc)
    totals = {"organizations": 0, "due": 0, "digests": 0, "emails": 0}
    for organization_id in organizations_with_open_cases(db):
        if inactive_reason(db, organization_id=organization_id) or unpaid_reason(db, organization_id=organization_id):
            continue
        if not mode.live_for(db, organization_id):
            continue
        try:
            if _old_open_cases_unclaimed(db, organization_id, moment):
                for workspace in db.execute(select(Workspace).where(
                        Workspace.organization_id == organization_id, Workspace.is_sample.is_(False)).order_by(Workspace.created_at)).scalars():
                    told = announce(db, workspace, service.summary(db, workspace)["items"])
                    totals["due"] += told.get(KIND_DUE, 0)
            week = digest_week(db, organization_id, moment)
            if week is not None and db.get(TrinetraNoticeSend, (organization_id, KIND_DIGEST, week)) is None:
                if claim(db, organization_id, KIND_DIGEST, week):
                    organization = db.get(Organization, organization_id)
                    _had, wanted, sent = send_digest(db, organization, week=week)
                    if wanted and not sent:
                        db.rollback()      # the relay took nothing: the claim goes with it, so the next hourly run tries again
                        logger.warning("trinetra_digest.retry_later", extra={"organization_id": str(organization_id)})
                        continue
                    db.get(TrinetraNoticeSend, (organization_id, KIND_DIGEST, week)).recipients = sent
                    totals["digests"] += 1
                    totals["emails"] += sent
            db.commit()
            totals["organizations"] += 1
        except Exception:  # noqa: BLE001 - one organization failing must not stop the others
            db.rollback()
            logger.warning("trinetra.sweep_failed", extra={"organization_id": str(organization_id)}, exc_info=True)
    return totals


def handle_sweep(payload: dict[str, Any]) -> dict[str, int]:
    from app.db import session as session_module
    from app.services.gst.notices import payload_now

    with session_module.SessionLocal() as db:
        return run_sweep(db, now=payload_now(payload))


__all__ = ["announce", "claim", "digest_body", "events", "figures", "handle_sweep", "run_sweep"]
