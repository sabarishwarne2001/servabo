"""Recomputes the GST reconciliation of one workspace and GSTIN, and stores it.

`recompute` reads the active returns' records, the books, the people's decisions and the workspace tolerance,
runs the pure matching (`matching.reconcile`), adds the IMS recommendation and the 180-day picture to each
row and replaces the stored `gst_matches` of that GSTIN in one transaction under a per-workspace advisory lock.
It is idempotent: the same inputs give the same rows. It runs on import, on a decision, after documents finish
processing (debounced through the worker, like Helm's ledger update) and nightly.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timezone
from typing import Any, Optional

from sqlalchemy import delete, func, insert, select, text
from sqlalchemy.orm import Session

from app.models.gst import GstDecision, GstMatch, GstReturn, GstReturnRecord, GstSettings
from app.models.workspace import Workspace
from app.services.gst import books as books_module
from app.services.gst import ims
from app.services.gst import vocabulary as v
from app.services.gst.matching import DecisionView, MatchOut, RecView, period_window, reconcile
from app.services.helm import identity as ident

logger = logging.getLogger("app.services.gst.engine")


def tolerance_micros(db: Session, workspace_id: uuid.UUID) -> int:
    settings = db.get(GstSettings, workspace_id)
    return settings.tolerance_micros if settings is not None else v.DEFAULT_TOLERANCE_MICROS


def active_gstins(db: Session, workspace_id: uuid.UUID) -> list[str]:
    return list(db.execute(select(GstReturn.gstin).where(
        GstReturn.workspace_id == workspace_id, GstReturn.status == v.RETURN_ACTIVE).distinct()
        .order_by(GstReturn.gstin)).scalars())


def active_periods(db: Session, workspace_id: uuid.UUID, gstin: str) -> list[str]:
    return list(db.execute(select(GstReturn.period).where(
        GstReturn.workspace_id == workspace_id, GstReturn.gstin == gstin,
        GstReturn.status == v.RETURN_ACTIVE).order_by(GstReturn.period)).scalars())


_RECORD_COLUMNS = (
    GstReturnRecord.id, GstReturnRecord.section, GstReturnRecord.kind, GstReturnRecord.period,
    GstReturnRecord.supplier_gstin, GstReturnRecord.supplier_name, GstReturnRecord.doc_number, GstReturnRecord.doc_key,
    GstReturnRecord.doc_date, GstReturnRecord.value_micros, GstReturnRecord.taxable_micros, GstReturnRecord.igst_micros,
    GstReturnRecord.cgst_micros, GstReturnRecord.sgst_micros, GstReturnRecord.cess_micros,
    GstReturnRecord.reverse_charge, GstReturnRecord.itc_available, GstReturnRecord.reason, GstReturnRecord.irn,
    GstReturnRecord.original_key, GstReturnRecord.supplier_period,
)


def record_views(db: Session, workspace_id: uuid.UUID, gstin: str) -> list[RecView]:
    """The active returns' records, as plain views. Only the columns matching needs: the raw copy stays in the table."""
    rows = db.execute(
        select(*_RECORD_COLUMNS).join(GstReturn, GstReturn.id == GstReturnRecord.return_id)
        .where(GstReturn.workspace_id == workspace_id, GstReturn.gstin == gstin, GstReturn.status == v.RETURN_ACTIVE)
    ).all()
    name_keys: dict[str, Optional[str]] = {}

    def name_key(name: Optional[str]) -> Optional[str]:
        if not name:
            return None
        if name not in name_keys:
            name_keys[name] = ident.key_for(name)
        return name_keys[name]

    return [
        RecView(
            id=r.id, section=r.section, kind=r.kind, period=r.period, supplier_gstin=r.supplier_gstin,
            supplier_name=r.supplier_name, supplier_name_key=name_key(r.supplier_name), number=r.doc_number,
            doc_key=r.doc_key, doc_date=r.doc_date, value_micros=r.value_micros, taxable_micros=r.taxable_micros,
            igst_micros=r.igst_micros, cgst_micros=r.cgst_micros, sgst_micros=r.sgst_micros, cess_micros=r.cess_micros,
            reverse_charge=r.reverse_charge, itc_available=r.itc_available, reason=r.reason,
            irn=r.irn.strip().lower() if r.irn else None, original_key=r.original_key,
            supplier_period=r.supplier_period,
        )
        for r in rows
    ]


def decision_views(db: Session, workspace_id: uuid.UUID, gstin: str) -> list[DecisionView]:
    return [DecisionView(d.supplier_gstin, d.doc_key, d.kind, d.decision, d.work_item_id) for d in db.execute(
        select(GstDecision).where(GstDecision.workspace_id == workspace_id, GstDecision.gstin == gstin)).scalars()]


def _row(workspace: Workspace, gstin: str, out: MatchOut, now: datetime) -> dict[str, Any]:
    rec, book = out.record, out.book
    return {
        "id": uuid.uuid4(), "organization_id": workspace.organization_id, "workspace_id": workspace.id, "gstin": gstin,
        "record_id": rec.id if rec is not None else None,
        "work_item_id": book.work_item_id if book is not None else None,
        "status": out.status, "method": out.method,
        "supplier_gstin": (rec.supplier_gstin if rec is not None else None) or (book.supplier_gstin if book else None),
        "supplier_name": ((rec.supplier_name if rec is not None else None) or (book.supplier_name if book else None)),
        "doc_number": ((rec.number if rec is not None else None) or (book.number if book else None)),
        "doc_date": ((rec.doc_date if rec is not None else None) or (book.doc_date if book else None)),
        "value_micros": rec.value_micros if rec is not None else (book.total_micros if book else None),
        "tax_micros": rec.tax_micros if rec is not None else (book.tax_micros if book else None),
        "itc_micros": out.itc_micros, "differences": out.differences, "notes": out.notes,
        "ims_action": out.ims_action, "ims_reason": out.ims_reason, "period_first_seen": out.period_first_seen,
        "reported_late": out.reported_late, "risk": out.risk, "decision": out.decision, "computed_at": now,
    }


def recompute(db: Session, workspace: Workspace, gstin: Optional[str] = None, *,
              today: Optional[date] = None) -> dict[str, int]:
    """Rebuild the stored matches for one GSTIN of the workspace (or each GSTIN with an active return)."""
    today = today or date.today()
    summary: dict[str, int] = {}
    db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"gst:{workspace.id}"})
    targets = [gstin] if gstin else active_gstins(db, workspace.id)
    for target in targets:
        periods = active_periods(db, workspace.id, target)
        if not periods:
            db.execute(delete(GstMatch).where(GstMatch.workspace_id == workspace.id, GstMatch.gstin == target))
            summary[target] = 0
            continue
        records = record_views(db, workspace.id, target)
        books = books_module.load_books(db, workspace, target)
        outputs = reconcile(records, books, tolerance_micros=tolerance_micros(db, workspace.id),
                            decisions=decision_views(db, workspace.id, target), window=period_window(periods))
        for out in outputs:
            out.ims_action, out.ims_reason = ims.recommend(out)
            if out.book is not None:
                out.risk = ims.exposure(out.book, today)
        now = datetime.now(timezone.utc)
        db.execute(delete(GstMatch).where(GstMatch.workspace_id == workspace.id, GstMatch.gstin == target))
        rows = [_row(workspace, target, out, now) for out in outputs]
        for start in range(0, len(rows), 2000):
            db.execute(GstMatch.__table__.insert(), rows[start:start + 2000])
        summary[target] = len(rows)
    db.flush()
    from app.services.gst import hooks

    hooks.replan(db, workspace)
    return summary


def count_records(db: Session, workspace_id: uuid.UUID) -> int:
    return int(db.execute(select(func.count()).select_from(GstReturnRecord)
                          .where(GstReturnRecord.workspace_id == workspace_id)).scalar_one())


__all__ = ["active_gstins", "active_periods", "recompute", "tolerance_micros"]
