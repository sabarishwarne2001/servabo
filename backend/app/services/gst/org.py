"""One GST reconciliation per GSTIN across every workspace of an organization (Enterprise,
`capability.gst_credit_all_workspaces`; docs/product/GST-CREDIT.md).

A workspace's own reconciliation (`engine.recompute`) matches its GSTR-2B returns with the invoices of that workspace.
An organization that books its purchases in several workspaces (a branch each, a client each) needs the one answer:
the returns of the GSTIN, wherever they were imported, against the purchase invoices of every workspace that holds
that GSTIN's purchases. The stored rows cannot hold that (their composite keys tie a row to one workspace's
documents), so this module computes it when the page is opened, with the same pure matching, and keeps the answer
for a minute. It is read-only: decisions, imports and exports stay in the workspaces.

Which workspaces count, and which documents:
  * active workspaces, never the sample company;
  * a workspace with an active return of the GSTIN is a "home" workspace: its documents count as they do in its own
    reconciliation (the buyer GSTIN, else "not ours");
  * any other workspace contributes only documents that name the GSTIN as their buyer.
Where the same period of the GSTIN was imported in more than one workspace, the latest import is the one used.
The tolerance is the strictest of the workspaces'; people's decisions are the union of the workspaces' (the latest
wins). Lists are cut to the workspaces the person may read; the figures are the organization's.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional, Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.gst import GstDecision, GstMatch, GstReturn, GstReturnRecord
from app.models.workspace import Workspace, WorkspaceStatus
from app.services.gst import books as books_module
from app.services.gst import engine, ims, queries
from app.services.gst import vocabulary as v
from app.services.gst.matching import DecisionView, period_window, reconcile
from app.services.gst.summary import CLAIMABLE_STATUSES, FIGURE_MEANING

CACHE_SECONDS = 60
CACHE_ENTRIES = 16


@dataclass(frozen=True)
class Result:
    """The organization's reconciliation of one GSTIN: transient rows (never saved) and what they came from."""

    gstin: str
    lines: tuple[GstMatch, ...]
    periods: tuple[str, ...]
    workspaces: tuple[tuple[uuid.UUID, str], ...]


def workspaces_of(db: Session, organization_id: uuid.UUID) -> list[Workspace]:
    """The workspaces an organization-wide reconciliation reads: active, and never the invented sample company."""
    return list(db.execute(select(Workspace).where(
        Workspace.organization_id == organization_id, Workspace.status == WorkspaceStatus.ACTIVE,
        Workspace.is_sample.is_(False)).order_by(Workspace.workspace_name, Workspace.id)).scalars())


def returns_in(db: Session, workspace_ids: Sequence[uuid.UUID], gstin: Optional[str] = None) -> list[GstReturn]:
    """The active returns, one per GSTIN and period: where a period was imported in several workspaces, the latest."""
    query = select(GstReturn).where(GstReturn.workspace_id.in_(list(workspace_ids)), GstReturn.status == v.RETURN_ACTIVE)
    if gstin:
        query = query.where(GstReturn.gstin == gstin)
    latest: dict[tuple[str, str], GstReturn] = {}
    for row in db.execute(query.order_by(GstReturn.imported_at, GstReturn.id)).scalars():
        latest[(row.gstin, row.period)] = row
    return sorted(latest.values(), key=lambda r: (r.gstin, r.period))


def overview(db: Session, workspace_ids: Sequence[uuid.UUID], gstin: Optional[str] = None) -> dict[str, Any]:
    """Which GSTINs and periods are imported, and the last import (the shape `summary.returns_overview` gives)."""
    rows = returns_in(db, workspace_ids, gstin)
    last = max(rows, key=lambda r: r.imported_at, default=None)
    return {
        "gstins": sorted({r.gstin for r in rows}),
        "periods": sorted({r.period for r in rows}, reverse=True),
        "last_import": None if last is None else {
            "imported_at": last.imported_at.isoformat(), "version": last.version, "period": last.period,
            "gstin": last.gstin, "generated_on": last.generated_on.isoformat() if last.generated_on else None,
        },
    }


# --------------------------------------------------------------------------------------------- computing


_cache: dict[tuple[uuid.UUID, str, date], tuple[float, str, Result]] = {}
_cache_lock = threading.Lock()


def _fingerprint(db: Session, returns: Sequence[GstReturn], workspace_ids: Sequence[uuid.UUID], gstin: str) -> str:
    """What changes when a person imports or decides: a new import changes the return ids, a decision the count and
    the latest time. (Documents and payments are read afresh once the minute is up.)"""
    decisions = db.execute(select(func.count(), func.max(GstDecision.decided_at)).where(
        GstDecision.workspace_id.in_(list(workspace_ids)), GstDecision.gstin == gstin)).one()
    return "|".join([",".join(sorted(str(r.id) for r in returns)), str(decisions[0]), str(decisions[1]),
                     ",".join(sorted(str(w) for w in workspace_ids))])


def reconciliation(db: Session, organization_id: uuid.UUID, gstin: str, *, today: Optional[date] = None) -> Result:
    today = today or date.today()
    workspaces = workspaces_of(db, organization_id)
    ids = [w.id for w in workspaces]
    returns = [r for r in returns_in(db, ids, gstin)]
    key = (organization_id, gstin, today)
    stamp = _fingerprint(db, returns, ids, gstin)
    with _cache_lock:
        hit = _cache.get(key)
    if hit is not None and hit[1] == stamp and time.monotonic() - hit[0] < CACHE_SECONDS:
        return hit[2]
    result = _compute(db, organization_id, workspaces, returns, gstin, today)
    with _cache_lock:
        if len(_cache) >= CACHE_ENTRIES:
            _cache.pop(min(_cache, key=lambda k: _cache[k][0]), None)
        _cache[key] = (time.monotonic(), stamp, result)
    return result


def forget() -> None:
    """Drop the kept answers (tests, and an import that must show at once)."""
    with _cache_lock:
        _cache.clear()


def _compute(db: Session, organization_id: uuid.UUID, workspaces: Sequence[Workspace],
             returns: Sequence[GstReturn], gstin: str, today: date) -> Result:
    if not returns:
        return Result(gstin, (), (), tuple((w.id, w.workspace_name) for w in workspaces))
    by_workspace = {w.id: w for w in workspaces}
    home = {r.workspace_id for r in returns}
    return_workspace = {r.id: r.workspace_id for r in returns}

    rows = db.execute(select(*engine._RECORD_COLUMNS, GstReturnRecord.return_id).where(
        GstReturnRecord.return_id.in_(list(return_workspace)))).all()
    records = engine.views_of(rows)
    record_workspace = {r.id: return_workspace[r.return_id] for r in rows}

    books = []
    book_workspace: dict[uuid.UUID, uuid.UUID] = {}
    for workspace in workspaces:
        for book in books_module.load_books(db, workspace, gstin, explicit_only=workspace.id not in home):
            books.append(book)
            book_workspace[book.work_item_id] = workspace.id

    decisions = [DecisionView(d.supplier_gstin, d.doc_key, d.kind, d.decision, d.work_item_id) for d in db.execute(
        select(GstDecision).where(GstDecision.workspace_id.in_(list(by_workspace)), GstDecision.gstin == gstin)
        .order_by(GstDecision.decided_at, GstDecision.id)).scalars()]
    tolerance = min(engine.tolerance_micros(db, w.id) for w in workspaces)
    periods = tuple(sorted({r.period for r in returns}))
    outputs = reconcile(records, books, tolerance_micros=tolerance, decisions=decisions,
                        window=period_window(list(periods)))
    now = datetime.now(timezone.utc)
    lines: list[GstMatch] = []
    for out in outputs:
        out.ims_action, out.ims_reason = ims.recommend(out)
        if out.book is not None:
            out.risk = ims.exposure(out.book, today)
        home_id = (book_workspace.get(out.book.work_item_id) if out.book is not None
                   else record_workspace.get(out.record.id) if out.record is not None else None)
        if home_id is None:
            continue
        lines.append(GstMatch(**engine.row_of(organization_id, home_id, gstin, out, now)))
    lines.sort(key=_order)
    return Result(gstin, tuple(lines), periods, tuple((w.id, w.workspace_name) for w in workspaces))


def _order(m: GstMatch) -> tuple[Any, ...]:
    """Newest first, then a fixed order, so a page is the same page on every request."""
    return (m.doc_date is None, -(m.doc_date.toordinal() if m.doc_date else 0), m.supplier_name or "",
            m.doc_number or "", str(m.record_id or m.work_item_id or ""))


# --------------------------------------------------------------------------------------------- reading


def _in_period(m: GstMatch, period: Optional[str]) -> bool:
    if not period:
        return True
    month = m.doc_date.strftime("%Y-%m") if m.doc_date else None
    return m.period_first_seen == period or (m.record_id is None and month == period)


def scoped(result: Result, *, period: Optional[str] = None, workspace_ids: Optional[set[uuid.UUID]] = None) -> list[GstMatch]:
    return [m for m in result.lines if _in_period(m, period) and (workspace_ids is None or m.workspace_id in workspace_ids)]


def _at_risk(m: GstMatch, today: date) -> bool:
    risk = m.risk
    if not risk or m.work_item_id is None or risk.get("paid") is not False or not risk.get("invoice_date"):
        return False
    return date.fromisoformat(risk["invoice_date"]) <= today - timedelta(days=v.RISK_NEAR_DAYS)


def _duplicate(m: GstMatch) -> bool:
    return any((n or {}).get("code") == "DUPLICATE_RECORD" for n in (m.notes or []))


def figures(lines: Sequence[GstMatch], *, today: Optional[date] = None) -> dict[str, Any]:
    """The six figures over rows: the same sums and counts `summary.figures` makes in SQL over stored rows."""
    today = today or date.today()

    def total(rows: Sequence[GstMatch], attr: str = "itc_micros") -> int:
        return int(sum(getattr(m, attr) or 0 for m in rows))

    by = lambda *statuses: [m for m in lines if m.status in statuses]  # noqa: E731
    waiting = by(v.WAITING_FOR_SUPPLIER)
    differing = by(v.MATCHED_WITH_DIFFERENCES)
    risky = [m for m in lines if _at_risk(m, today)]
    unseen = [m for m in by(v.NOT_IN_BOOKS) if not _duplicate(m) and m.decision != v.DECISION_NOT_OURS]
    ineligible = by(v.NOT_ELIGIBLE)
    values = {
        "claimable_now": {"amount_micros": total(by(*CLAIMABLE_STATUSES)),
                          "count": len(by(v.MATCHED, v.MATCHED_WITH_DIFFERENCES))},
        "waiting": {"amount_micros": total(waiting), "count": len(waiting),
                    "suppliers": len({m.supplier_gstin or m.supplier_name for m in waiting})},
        "differences": {"amount_micros": int(sum((m.tax_micros or 0) - (m.itc_micros or 0) for m in differing)),
                        "count": len(differing)},
        "at_risk_180": {"amount_micros": total(risky, "tax_micros"), "count": len(risky)},
        "not_in_books": {"amount_micros": total(unseen), "count": len(unseen)},
        "not_eligible": {"amount_micros": total(ineligible), "count": len(ineligible)},
    }
    out = [{"key": key, "title": title, "meaning": meaning, "law": law, **values[key]}
           for key, (title, meaning, law) in FIGURE_MEANING.items()]
    return {"figures": out, "suggested": len(by(v.SUGGESTED)), "reverse_charge": len(by(v.REVERSE_CHARGE)),
            "notes": len(by(v.NOTE)), "lines": len(lines), "currency": "INR", "disclaimer": v.NOT_ADVICE}


def by_workspace(result: Result, lines: Sequence[GstMatch]) -> list[dict[str, Any]]:
    """What each workspace contributes: its lines, the credit it can claim and the credit waiting on suppliers."""
    out = []
    for workspace_id, name in result.workspaces:
        own = [m for m in lines if m.workspace_id == workspace_id]
        if not own:
            continue
        claim = sum(m.itc_micros or 0 for m in own if m.status in CLAIMABLE_STATUSES)
        waiting = [m for m in own if m.status == v.WAITING_FOR_SUPPLIER]
        out.append({"workspace_id": str(workspace_id), "workspace_name": name, "lines": len(own),
                    "claimable_micros": int(claim), "waiting_micros": int(sum(m.itc_micros or 0 for m in waiting)),
                    "waiting_count": len(waiting)})
    return out


def suppliers(lines: Sequence[GstMatch], *, offset: int, limit: int) -> dict[str, Any]:
    """Who has not reported what, oldest first (`summary.supplier_list` over rows)."""
    groups: dict[tuple[Optional[str], str], list[GstMatch]] = {}
    for m in lines:
        groups.setdefault((m.supplier_gstin, m.supplier_gstin or m.supplier_name or ""), []).append(m)
    items = []
    for (gstin, _), rows in groups.items():
        waiting = [m for m in rows if m.status == v.WAITING_FOR_SUPPLIER]
        unseen = [m for m in rows if m.status == v.NOT_IN_BOOKS]
        differing = [m for m in rows if m.status == v.MATCHED_WITH_DIFFERENCES]
        suggested = [m for m in rows if m.status == v.SUGGESTED]
        if not (waiting or unseen or differing or suggested):
            continue
        dates = [m.doc_date for m in waiting if m.doc_date]
        names = [m.supplier_name for m in rows if m.supplier_name]
        items.append({
            "supplier_gstin": gstin, "supplier_name": max(names) if names else None, "waiting_count": len(waiting),
            "waiting_micros": int(sum(m.itc_micros or 0 for m in waiting)),
            "oldest_waiting": min(dates).isoformat() if dates else None, "not_in_books_count": len(unseen),
            "differences_count": len(differing), "suggested_count": len(suggested),
            "matched_count": len([m for m in rows if m.status in (v.MATCHED, v.MATCHED_WITH_DIFFERENCES)]),
        })
    items.sort(key=lambda s: (s["oldest_waiting"] is None, s["oldest_waiting"] or "", -s["waiting_micros"],
                              s["supplier_name"] or ""))
    return {"total": len(items), "items": items[offset:offset + limit], "offset": offset, "limit": limit}


def page(lines: Sequence[GstMatch], *, statuses: Optional[Sequence[str]] = None, supplier: Optional[str] = None,
         ims_action: Optional[str] = None, q: Optional[str] = None, at_risk: Optional[bool] = None,
         workspace_id: Optional[uuid.UUID] = None, offset: int = 0, limit: int = 50,
         names: Optional[dict[uuid.UUID, str]] = None, today: Optional[date] = None) -> dict[str, Any]:
    """The invoice list, filtered (`queries.list_lines` over rows). Each line also names its workspace."""
    today = today or date.today()
    rows = list(lines)
    if statuses:
        rows = [m for m in rows if m.status in statuses]
    if ims_action:
        rows = [m for m in rows if m.ims_action == ims_action]
    if supplier:
        needle = supplier.strip().lower()
        rows = [m for m in rows if needle in (m.supplier_gstin or "").lower() or needle in (m.supplier_name or "").lower()]
    if q:
        needle = q.strip().lower()
        rows = [m for m in rows if needle in (m.doc_number or "").lower()]
    if at_risk:
        rows = [m for m in rows if _at_risk(m, today)]
    if workspace_id:
        rows = [m for m in rows if m.workspace_id == workspace_id]
    names = names or {}
    items = []
    for m in rows[offset:offset + limit]:
        line = queries.serialise(m, today)
        line["workspace_id"] = str(m.workspace_id)
        line["workspace_name"] = names.get(m.workspace_id)
        items.append(line)
    return {"total": len(rows), "offset": offset, "limit": limit, "items": items}


__all__ = ["CACHE_SECONDS", "Result", "by_workspace", "figures", "forget", "overview", "page", "reconciliation",
           "returns_in", "scoped", "suppliers", "workspaces_of"]
