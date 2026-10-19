"""The value receipt (Session G): what Servabo found in a customer's own documents, in their own money.

    receipt(db, organization_id, period)     reads only, never writes
    cached(db, organization_id, period)      the same, kept in Redis for ten minutes per organization and period
    forget(organization_id)                  drops the kept copies (tests, and a new import is allowed to show at once)

`period` is "trial" (the organization's trial window: the seven days that end at `organizations.trial_ends_at`)
or "month" (the current calendar month in the time zone of the organization's oldest workspace; organizations
have no time zone of their own, N-141).

The honesty rules are the feature:

1. Every figure is read from stored rows. No estimate, no "hours saved", no projection.
2. Amounts in different currencies are never added, and neither are the Time machine's honesty classes
   (confirmed, likely, potential): each is its own finding.
3. A figure of zero, or one that was not computed, is left out.
4. The sample company's workspace (`workspaces.is_sample`) and its Helm book are never counted.
5. Every money figure carries `source`, the app path of the page that holds its evidence.

An engine the organization's plan does not include produces nothing, even if old rows exist (a plan that was
downgraded). GST Credit's figures and the Time machine's preview are open on every plan, so they are read on every plan.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core import entitlements
from app.core.config import settings
from app.models.gst import GstMatch
from app.models.helm import HelmBacktest, HelmBook, HelmValueEvent
from app.models.organization import Organization
from app.models.payment_risk import KIND_BANK_ACCOUNT_CHANGED, PaymentRiskFlag
from app.models.procurement import ProcurementCase, ProcurementCaseLine
from app.models.radar import AnomalyFinding, DocumentFingerprint
from app.models.usage_event import UsageEvent
from app.models.workspace import Workspace, WorkspaceStatus
from app.services.gst import summary as gst_summary
from app.services.helm import vocabulary as helm_v
from app.services.procurement_matching.vocabulary import CASE_STATUS_SUPERSEDED, OUTCOME_PRICE_VARIANCE
from app.services.radar import vocabulary as radar_v

logger = logging.getLogger("app.services.value_receipt")

TRIAL = "trial"
MONTH = "month"
PERIODS = (TRIAL, MONTH)

CACHE_SECONDS = 600
MICROS = 1_000_000

DOCUMENT_UPLOAD = "document.upload"
OCR_PAGE = "ocr.page"
ASSISTANT_MESSAGE = "assistant.message"

#: What Business adds that the receipt can name (the capability catalogue's keys), in the words a customer uses.
BUSINESS_ADDS = (
    (entitlements.ANOMALY_RADAR_CAPABILITY, "Payment risks"),
    (entitlements.RECONCILIATION_CAPABILITY, "Prices checked against purchase orders"),
    (entitlements.HELM_CAPABILITY, "Helm's full planning"),
    (entitlements.GST_CREDIT_CAPABILITY, "GST's supplier list"),
)

_SYMBOLS = {"INR": "₹", "USD": "$", "EUR": "€", "GBP": "£"}


class ReceiptError(ValueError):
    pass


# ------------------------------------------------------------------------------------------------ words and money


def _indian(digits: str) -> str:
    """Indian grouping: 1234567 -> 12,34,567."""
    if len(digits) <= 3:
        return digits
    head, tail = digits[:-3], digits[-3:]
    groups: list[str] = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return ",".join(groups + [tail])


def say_amount(micros: int, currency: str) -> str:
    """Whole units, rupees in Indian grouping (N-112, N-137): ₹2,40,000, $1,234, AED 5,000. Under one unit it keeps
    its two decimals so a real figure is never shown as zero."""
    value = Decimal(int(micros)) / MICROS
    sign = "-" if value < 0 else ""
    value = abs(value)
    whole = value.quantize(Decimal(1), rounding=ROUND_HALF_UP)
    if whole == 0:
        shown = f"{value:.2f}"
    else:
        digits = f"{int(whole)}"
        shown = _indian(digits) if currency == "INR" else f"{int(whole):,}"
    symbol = _SYMBOLS.get(currency)
    return f"{sign}{symbol}{shown}" if symbol else f"{sign}{currency} {shown}"


def _plural(n: int, one: str, many: Optional[str] = None) -> str:
    return f"{n:,} {one if n == 1 else (many or one + 's')}"


# ------------------------------------------------------------------------------------------------ the window


def _workspaces(db: Session, organization_id: uuid.UUID) -> list[Workspace]:
    """The customer's own active workspaces, oldest first. The sample company is never one of them."""
    return list(db.execute(
        select(Workspace).where(Workspace.organization_id == organization_id,
                                Workspace.status == WorkspaceStatus.ACTIVE, Workspace.is_sample.is_(False))
        .order_by(Workspace.created_at, Workspace.id)).scalars())


def _sample_ids(db: Session, organization_id: uuid.UUID) -> list[uuid.UUID]:
    return list(db.execute(select(Workspace.id).where(Workspace.organization_id == organization_id,
                                                      Workspace.is_sample.is_(True))).scalars())


def _zone(name: Optional[str]) -> ZoneInfo:
    try:
        return ZoneInfo(name or "UTC")
    except Exception:  # noqa: BLE001 - a zone that cannot be read falls back to UTC, never an error on a card
        return ZoneInfo("UTC")


def window(organization: Organization, workspaces: list[Workspace], period: str,
           now: datetime) -> tuple[datetime, datetime, str]:
    """`[start, end)` in UTC and the zone name. The trial window is the seven days ending at the trial's end
    (clipped to now); the month is the calendar month in the zone of the oldest workspace."""
    if period not in PERIODS:
        raise ReceiptError("period must be trial or month")
    zone_name = workspaces[0].timezone if workspaces else "UTC"
    zone = _zone(zone_name)
    if period == TRIAL:
        ends = organization.trial_ends_at
        if ends is None:
            return organization.created_at, now, zone.key
        if ends.tzinfo is None:
            ends = ends.replace(tzinfo=timezone.utc)
        length = timedelta(days=max(0, int(settings.FREE_TRIAL_DAYS)))
        return ends - length, min(ends, now), zone.key
    local = now.astimezone(zone)
    first = local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    following = (first + timedelta(days=32)).replace(day=1)
    return first.astimezone(timezone.utc), following.astimezone(timezone.utc), zone.key


# ------------------------------------------------------------------------------------------------ the findings


def _finding(key: str, label: str, *, source: str, count: Optional[int] = None, amount_micros: Optional[int] = None,
             currency: Optional[str] = None, honesty: Optional[str] = None, suppliers: Optional[int] = None,
             ) -> Optional[dict[str, Any]]:
    """None when the figure is zero or was not computed (rule 3)."""
    has_amount = amount_micros is not None and currency is not None
    if has_amount and amount_micros <= 0:  # type: ignore[operator]
        return None
    if not has_amount and not count:
        return None
    out: dict[str, Any] = {"key": key, "label": label, "count": count, "source": source, "honesty": honesty,
                           "amount_micros": amount_micros if has_amount else None,
                           "currency": currency if has_amount else None,
                           "amount_text": say_amount(amount_micros, currency) if has_amount else None}  # type: ignore[arg-type]
    if suppliers is not None:
        out["suppliers"] = suppliers
    return out


def _work(db: Session, organization_id: uuid.UUID, sample_ids: list[uuid.UUID], start: datetime,
          end: datetime) -> dict[str, int]:
    """Documents read, pages read and assistant answers, as the Usage page and the plan meters count them: the
    usage ledger's `document.upload`, `ocr.page` and `assistant.message`. The sample company's events are left out."""
    rows = db.execute(
        select(UsageEvent.event_type, func.coalesce(func.sum(UsageEvent.quantity), 0))
        .where(UsageEvent.organization_id == organization_id,
               UsageEvent.event_type.in_((DOCUMENT_UPLOAD, OCR_PAGE, ASSISTANT_MESSAGE)),
               UsageEvent.occurred_at >= start, UsageEvent.occurred_at < end,
               or_(UsageEvent.workspace_id.is_(None), UsageEvent.workspace_id.notin_(sample_ids)))
        .group_by(UsageEvent.event_type)).all()
    by_type = {event_type: int(total) for event_type, total in rows}
    return {"documents": by_type.get(DOCUMENT_UPLOAD, 0), "pages": by_type.get(OCR_PAGE, 0),
            "assistant_answers": by_type.get(ASSISTANT_MESSAGE, 0)}


def _paths(organization: Organization, workspaces: list[Workspace]):
    org = organization.slug
    by_id = {w.id: w for w in workspaces}

    def workspace_page(workspace_id: Optional[uuid.UUID], tail: str) -> str:
        workspace = by_id.get(workspace_id) if workspace_id else None
        return f"/{org}/{(workspace or workspaces[0]).slug}/{tail}"

    return workspace_page, f"/{org}/helm/time-machine", f"/{org}/helm"


def _gst(db: Session, workspaces: list[Workspace], page, today: date) -> list[dict[str, Any]]:
    """The GST figures stand as of today (a waiting credit is waiting until the supplier reports it), read from the
    stored reconciliation of each workspace that has one. INR only: GSTR-2B carries no other currency."""
    ids = [w.id for w in workspaces]
    holding = list(db.execute(select(GstMatch.workspace_id).where(GstMatch.workspace_id.in_(ids))
                              .group_by(GstMatch.workspace_id)).scalars())
    waiting = at_risk = claim = suppliers = 0
    waiting_n = risk_n = claim_n = 0
    lead: Optional[uuid.UUID] = None
    biggest = -1
    for workspace_id in holding:
        figures = {f["key"]: f for f in gst_summary.figures(db, workspace_ids=[workspace_id], today=today)["figures"]}
        w, r, c = figures["waiting"], figures["at_risk_180"], figures["claimable_now"]
        waiting += w["amount_micros"]
        waiting_n += w["count"]
        suppliers += w.get("suppliers", 0)
        at_risk += r["amount_micros"]
        risk_n += r["count"]
        claim += c["amount_micros"]
        claim_n += c["count"]
        if w["amount_micros"] + c["amount_micros"] > biggest:
            biggest, lead = w["amount_micros"] + c["amount_micros"], workspace_id
    source = page(lead, "gst")
    return [f for f in (
        _finding("gst_waiting", f"GST credit waiting on {_plural(suppliers, 'supplier')}", source=source,
                 count=waiting_n, amount_micros=waiting, currency="INR", suppliers=suppliers),
        _finding("gst_at_risk_180", "GST credit at risk under the 180-day rule", source=source, count=risk_n,
                 amount_micros=at_risk, currency="INR"),
        _finding("gst_claimable", "GST credit you can claim now", source=source, count=claim_n,
                 amount_micros=claim, currency="INR"),
    ) if f]


def _time_machine(db: Session, organization_id: uuid.UUID, start: datetime, end: datetime,
                  path: str) -> list[dict[str, Any]]:
    """The latest finished replay of the organization's own documents in the period. One finding per honesty class
    and currency: confirmed, likely and potential are never added together."""
    latest = db.execute(
        select(HelmBacktest).join(HelmBook, HelmBook.id == HelmBacktest.book_id)
        .where(HelmBacktest.organization_id == organization_id, HelmBacktest.status == helm_v.BACKTEST_DONE,
               HelmBook.kind != helm_v.BOOK_SAMPLE, HelmBacktest.finished_at >= start, HelmBacktest.finished_at < end)
        .order_by(HelmBacktest.finished_at.desc()).limit(1)).scalar_one_or_none()
    if latest is None:
        return []
    totals = (latest.result or {}).get("totals") or {}
    words = {helm_v.HONESTY_CONFIRMED: "what Helm would have held or saved, with evidence",
             helm_v.HONESTY_LIKELY: "what Helm would likely have held or saved",
             helm_v.HONESTY_POTENTIAL: "what Helm might have held or saved, if the missing facts hold"}
    out = []
    for honesty in helm_v.HONESTY_CLASSES:
        for currency, micros in sorted((totals.get(honesty) or {}).items()):
            found = _finding(f"time_machine_{honesty}_{currency}", f"Time machine replay, {honesty}: {words[honesty]}",
                             source=path, amount_micros=int(micros), currency=currency, honesty=honesty)
            if found:
                out.append(found)
    return out


def _duplicates(db: Session, ids: list[uuid.UUID], start: datetime, end: datetime, page) -> list[dict[str, Any]]:
    """Open or confirmed probable duplicates. The amount is the repeated document's total where it was read."""
    rows = db.execute(
        select(AnomalyFinding.workspace_id, DocumentFingerprint.currency,
               func.count(), func.coalesce(func.sum(DocumentFingerprint.total_micros), 0),
               func.count(DocumentFingerprint.total_micros))
        .outerjoin(DocumentFingerprint, DocumentFingerprint.work_item_id == AnomalyFinding.subject_work_item_id)
        .where(AnomalyFinding.workspace_id.in_(ids), AnomalyFinding.kind == radar_v.KIND_DUPLICATE_DOCUMENT,
               AnomalyFinding.status.in_((radar_v.STATUS_OPEN, radar_v.STATUS_CONFIRMED)),
               AnomalyFinding.created_at >= start, AnomalyFinding.created_at < end)
        .group_by(AnomalyFinding.workspace_id, DocumentFingerprint.currency)).all()
    priced: dict[str, list[int]] = {}
    lead: dict[str, tuple[int, uuid.UUID]] = {}
    unpriced = 0
    unpriced_lead: Optional[uuid.UUID] = None
    for workspace_id, currency, found, total, with_total in rows:
        if currency and with_total:
            entry = priced.setdefault(currency, [0, 0])
            entry[0] += int(with_total)
            entry[1] += int(total)
            if int(total) > lead.get(currency, (-1, workspace_id))[0]:
                lead[currency] = (int(total), workspace_id)
            unpriced += int(found) - int(with_total)
        else:
            unpriced += int(found)
        unpriced_lead = unpriced_lead or workspace_id
    out = []
    for currency in sorted(priced):
        count, total = priced[currency]
        found = _finding(f"duplicate_payments_{currency}",
                         f"{_plural(count, 'probable duplicate invoice')} that could have been paid twice",
                         source=page(lead[currency][1], "radar"), count=count, amount_micros=total, currency=currency)
        if found:
            out.append(found)
    left = _finding("duplicate_payments_unpriced",
                    f"{_plural(unpriced, 'more probable duplicate invoice')} (amount not read)",
                    source=page(unpriced_lead, "radar"), count=unpriced)
    if left:
        out.append(left)
    return out


def _bank_changes(db: Session, ids: list[uuid.UUID], start: datetime, end: datetime, page) -> list[dict[str, Any]]:
    rows = db.execute(
        select(PaymentRiskFlag.workspace_id, func.count()).where(
            PaymentRiskFlag.workspace_id.in_(ids), PaymentRiskFlag.kind == KIND_BANK_ACCOUNT_CHANGED,
            PaymentRiskFlag.status.in_(("OPEN", "CONFIRMED")),
            PaymentRiskFlag.created_at >= start, PaymentRiskFlag.created_at < end)
        .group_by(PaymentRiskFlag.workspace_id).order_by(func.count().desc())).all()
    if not rows:
        return []
    found = _finding("bank_account_changes", f"{_plural(sum(n for _, n in rows), 'supplier bank-account change')} flagged "
                     "before payment", source=page(rows[0][0], "radar"), count=sum(n for _, n in rows))
    return [found] if found else []


def _overcharges(db: Session, ids: list[uuid.UUID], start: datetime, end: datetime, page) -> list[dict[str, Any]]:
    """Invoice lines priced above the purchase order, in live cases: the amount is the sum of the positive price
    differences. Their currency is the workspace's (the matching compares documents of one currency)."""
    rows = db.execute(
        select(ProcurementCase.workspace_id, Workspace.currency,
               func.count(func.distinct(ProcurementCase.id)), func.coalesce(func.sum(ProcurementCaseLine.price_delta_micros), 0))
        .join(ProcurementCaseLine, ProcurementCaseLine.case_id == ProcurementCase.id)
        .join(Workspace, Workspace.id == ProcurementCase.workspace_id)
        .where(ProcurementCase.workspace_id.in_(ids), ProcurementCase.status != CASE_STATUS_SUPERSEDED,
               ProcurementCaseLine.outcome == OUTCOME_PRICE_VARIANCE, ProcurementCaseLine.price_delta_micros > 0,
               ProcurementCase.created_at >= start, ProcurementCase.created_at < end)
        .group_by(ProcurementCase.workspace_id, Workspace.currency)).all()
    sums: dict[str, list[int]] = {}
    lead: dict[str, tuple[int, uuid.UUID]] = {}
    for workspace_id, currency, cases, total in rows:
        entry = sums.setdefault(currency, [0, 0])
        entry[0] += int(cases)
        entry[1] += int(total)
        if int(total) > lead.get(currency, (-1, workspace_id))[0]:
            lead[currency] = (int(total), workspace_id)
    out = []
    for currency in sorted(sums):
        cases, total = sums[currency]
        found = _finding(f"overcharges_{currency}",
                         f"Overcharges against purchase orders on {_plural(cases, 'invoice')}",
                         source=page(lead[currency][1], "procurement"), count=cases, amount_micros=total,
                         currency=currency)
        if found:
            out.append(found)
    return out


def _helm_value(db: Session, organization_id: uuid.UUID, sample_ids: list[uuid.UUID], start: datetime, end: datetime,
                zone: ZoneInfo, path: str) -> list[dict[str, Any]]:
    first = start.astimezone(zone).date()
    last = (end - timedelta(microseconds=1)).astimezone(zone).date()
    rows = db.execute(
        select(HelmValueEvent.currency, func.count(), func.coalesce(func.sum(HelmValueEvent.amount_micros), 0))
        .join(HelmBook, HelmBook.id == HelmValueEvent.book_id)
        .where(HelmValueEvent.organization_id == organization_id, HelmBook.kind != helm_v.BOOK_SAMPLE,
               HelmValueEvent.occurred_on >= first, HelmValueEvent.occurred_on <= last,
               or_(HelmValueEvent.workspace_id.is_(None), HelmValueEvent.workspace_id.notin_(sample_ids)))
        .group_by(HelmValueEvent.currency)).all()
    out = []
    for currency, count, total in sorted(rows):
        found = _finding(f"helm_value_held_{currency}", f"Value Helm held, with evidence ({_plural(int(count), 'outcome')})",
                         source=path, count=int(count), amount_micros=int(total), currency=currency,
                         honesty=helm_v.HONESTY_CONFIRMED)
        if found:
            out.append(found)
    return out


# ------------------------------------------------------------------------------------------------ the sentence


def _phrase(finding: dict[str, Any]) -> str:
    key, amount, count = finding["key"], finding["amount_text"], finding["count"] or 0
    if key == "gst_waiting":
        return f"found {amount} of GST credit waiting on {_plural(finding.get('suppliers') or 0, 'supplier')}"
    if key == "gst_at_risk_180":
        return f"found {amount} of GST credit at risk under the 180-day rule"
    if key == "gst_claimable":
        return f"found {amount} of GST credit you can claim now"
    if key.startswith("time_machine_"):
        return f"found {amount} that Helm would have held or saved, with evidence"
    if key.startswith("duplicate_payments_unpriced"):
        return f"found {_plural(count, 'probable duplicate invoice')}"
    if key.startswith("duplicate_payments_"):
        return f"found {_plural(count, 'probable duplicate invoice')}, {amount} in all"
    if key == "bank_account_changes":
        return f"flagged {_plural(count, 'supplier bank-account change')} before payment"
    if key.startswith("overcharges_"):
        return f"found {amount} of overcharges against purchase orders"
    return f"held {amount} with evidence"


def headline(period: str, work: dict[str, int], found: list[dict[str, Any]]) -> Optional[str]:
    """One sentence from the work counts and the first finding that is confirmed or has no honesty class."""
    lead = next((f for f in found if f["honesty"] in (None, helm_v.HONESTY_CONFIRMED)), None)
    opening = "In your trial" if period == TRIAL else "This month"
    docs = work["documents"]
    if docs and lead:
        return f"{opening} Servabo read {_plural(docs, 'document')} and {_phrase(lead)}."
    if docs:
        return f"{opening} Servabo read {_plural(docs, 'document')}."
    if lead:
        return f"{opening} Servabo {_phrase(lead)}."
    return None


def _also_on_business(db: Session, organization_id: uuid.UUID, now: datetime) -> list[str]:
    """The names of the checks Business adds that this organization does not have. Names only, never numbers."""
    from app.api import capability_gate
    from app.services import quota_service

    tier = quota_service.resolve_tier(db, organization_id=organization_id)
    if tier is None or tier.key not in (quota_service.FREE_TIER_KEY, "developer"):
        return []
    business = next((t for t in quota_service._tiers(db) if t.key == "business" and t.covers(now)), None)
    if business is None:
        return []
    granted = {entry.limit_key for entry in business.entries}
    return [name for key, name in BUSINESS_ADDS
            if key in granted and not capability_gate.has_capability(db, organization_id=organization_id,
                                                                     capability_key=key)]


# ------------------------------------------------------------------------------------------------ the receipt


def receipt(db: Session, organization_id: uuid.UUID, period: str, *, now: Optional[datetime] = None) -> dict[str, Any]:
    """The whole receipt for one organization and period. Reads only."""
    from app.api import capability_gate
    from app.services.helm import gate as helm_gate

    if period not in PERIODS:
        raise ReceiptError("period must be trial or month")
    organization = db.get(Organization, organization_id)
    if organization is None:
        raise ReceiptError("organization not found")
    moment = now or datetime.now(timezone.utc)
    workspaces = _workspaces(db, organization_id)
    start, end, zone_name = window(organization, workspaces, period, moment)
    zone = _zone(zone_name)
    sample_ids = _sample_ids(db, organization_id)
    work = _work(db, organization_id, sample_ids, start, end)

    found: list[dict[str, Any]] = []
    if workspaces:
        ids = [w.id for w in workspaces]
        page, time_machine_path, helm_path = _paths(organization, workspaces)
        has = lambda key: capability_gate.has_capability(db, organization_id=organization_id, capability_key=key)  # noqa: E731
        found += _gst(db, workspaces, page, moment.astimezone(zone).date())
        found += _time_machine(db, organization_id, start, end, time_machine_path)
        radar = has(entitlements.ANOMALY_RADAR_CAPABILITY)
        if radar:
            found += _duplicates(db, ids, start, end, page)
            found += _bank_changes(db, ids, start, end, page)
        if has(entitlements.RECONCILIATION_CAPABILITY):
            found += _overcharges(db, ids, start, end, page)
        if helm_gate.helm_held(db, organization_id):
            found += _helm_value(db, organization_id, sample_ids, start, end, zone, helm_path)

    return {
        "organization_id": str(organization_id), "period": period,
        "period_start": start.isoformat(), "period_end": end.isoformat(), "timezone": zone_name,
        "work": work, "found": found, "headline": headline(period, work, found),
        "also_on_business": _also_on_business(db, organization_id, moment),
        "organization_name": organization.name,
        "note": "Figures come from your own documents in Servabo. Not financial or tax advice.",
    }


# ------------------------------------------------------------------------------------------------ the kept copy


def _cache_key(organization_id: uuid.UUID, period: str) -> str:
    return f"value-receipt:v1:{organization_id}:{period}"


def cached(db: Session, organization_id: uuid.UUID, period: str) -> dict[str, Any]:
    """`receipt`, kept in Redis for ten minutes per organization and period. Without Redis it is computed each time."""
    from app.core.redis_client import get_redis_client

    client = get_redis_client()
    key = _cache_key(organization_id, period)
    if client is not None:
        try:
            kept = client.get(key)
            if kept:
                return json.loads(kept)
        except Exception:  # noqa: BLE001 - a cache that is down is a slower page, never an error
            logger.warning("value_receipt.cache_read_failed", exc_info=True)
    fresh = receipt(db, organization_id, period)
    if client is not None:
        try:
            client.setex(key, CACHE_SECONDS, json.dumps(fresh))
        except Exception:  # noqa: BLE001
            logger.warning("value_receipt.cache_write_failed", exc_info=True)
    return fresh


def forget(organization_id: uuid.UUID) -> None:
    from app.core.redis_client import get_redis_client

    client = get_redis_client()
    if client is None:
        return
    try:
        client.delete(*(_cache_key(organization_id, p) for p in PERIODS))
    except Exception:  # noqa: BLE001
        logger.warning("value_receipt.cache_forget_failed", exc_info=True)


__all__ = ["CACHE_SECONDS", "MONTH", "PERIODS", "ReceiptError", "TRIAL", "cached", "forget", "headline", "receipt",
           "say_amount", "window"]
