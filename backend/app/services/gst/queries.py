"""Reading and deciding on the reconciled lines: the invoice list, one line side by side, a person's decision."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any, Optional, Sequence

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.models.audit_log import AuditAction, AuditResourceType
from app.models.document_role import DocumentRole
from app.models.gst import GstDecision, GstMatch, GstReturn, GstReturnRecord
from app.models.workspace import Workspace
from app.services import audit_service
from app.services.gst import books as books_module
from app.services.gst import engine, ims, summary
from app.services.gst import vocabulary as v
from app.services.helm import ledger, ledger_store

MAX_LIMIT = 200


class DecisionError(ValueError):
    """A decision that cannot be taken, in words; `status` is the HTTP status the API answers with."""

    def __init__(self, code: str, message: str, status: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def _risk_view(risk: Optional[dict[str, Any]], today: date) -> Optional[dict[str, Any]]:
    if not risk:
        return None
    age = ims.age_days(risk, today)
    deadline = date.fromisoformat(risk["deadline_16_4"]) if risk.get("deadline_16_4") else None
    return {**risk, "age_days": age, "at_risk": ims.at_risk(risk, today),
            "days_to_16_4": (deadline - today).days if deadline else None}


def serialise(match: GstMatch, today: date) -> dict[str, Any]:
    return {
        "id": str(match.id), "gstin": match.gstin, "record_id": str(match.record_id) if match.record_id else None,
        "work_item_id": str(match.work_item_id) if match.work_item_id else None,
        "status": match.status, "status_text": v.STATUS_EXPLANATIONS.get(match.status, ""), "method": match.method,
        "supplier_gstin": match.supplier_gstin, "supplier_name": match.supplier_name, "number": match.doc_number,
        "date": match.doc_date.isoformat() if match.doc_date else None, "value_micros": match.value_micros,
        "tax_micros": match.tax_micros, "itc_micros": match.itc_micros, "differences": match.differences or [],
        "notes": match.notes or [], "ims_action": match.ims_action, "ims_reason": match.ims_reason,
        "period_first_seen": match.period_first_seen, "reported_late": match.reported_late,
        "decision": match.decision, "risk": _risk_view(match.risk, today),
    }


def list_lines(db: Session, *, workspace_ids: Sequence[uuid.UUID], gstin: Optional[str] = None,
               period: Optional[str] = None, statuses: Optional[Sequence[str]] = None, supplier: Optional[str] = None,
               ims_action: Optional[str] = None, q: Optional[str] = None, at_risk: Optional[bool] = None,
               offset: int = 0, limit: int = 50, today: Optional[date] = None) -> dict[str, Any]:
    today = today or date.today()
    base = summary.scope(select(GstMatch), workspace_ids=workspace_ids, gstin=gstin, period=period)
    if statuses:
        base = base.where(GstMatch.status.in_(list(statuses)))
    if ims_action:
        base = base.where(GstMatch.ims_action == ims_action)
    if supplier:
        like = f"%{supplier.strip()}%"
        base = base.where(or_(GstMatch.supplier_gstin.ilike(like), GstMatch.supplier_name.ilike(like)))
    if q:
        base = base.where(GstMatch.doc_number.ilike(f"%{q.strip()}%"))
    if at_risk:
        base = base.where(summary._risk_filter(today))
    total = db.execute(select(func.count()).select_from(base.subquery())).scalar_one()
    rows = db.execute(base.order_by(GstMatch.doc_date.desc().nullslast(), GstMatch.id).offset(offset).limit(limit)).scalars()
    return {"total": int(total), "offset": offset, "limit": limit, "items": [serialise(m, today) for m in rows]}


def _book_side(db: Session, workspace: Workspace, work_item_id: uuid.UUID, gstin: str) -> Optional[dict[str, Any]]:
    facts = books_module.load_documents(db, workspace, ids=[work_item_id])
    if not facts:
        return None
    fact = facts[0]
    view = books_module.book_view(fact, identities=books_module.our_identities(db, workspace.id, gstin), gstin=gstin,
                                  cases={}, settlements={})
    return {
        "work_item_id": str(work_item_id), "filename": fact.filename, "role": fact.role,
        "number": view.number if view else fact.document_number, "date": (view.doc_date if view else fact.document_date),
        "supplier_name": view.supplier_name if view else None, "supplier_gstin": view.supplier_gstin if view else None,
        "taxable_micros": view.taxable_micros if view else None, "igst_micros": view.igst_micros if view else None,
        "cgst_micros": view.cgst_micros if view else None, "sgst_micros": view.sgst_micros if view else None,
        "cess_micros": view.cess_micros if view else None, "tax_micros": view.tax_micros if view else None,
        "total_micros": view.total_micros if view else fact.total_micros,
        "irn": view.irn if view else None,
    }


def line_detail(db: Session, workspace: Workspace, line_id: uuid.UUID, *, today: Optional[date] = None) -> Optional[dict[str, Any]]:
    """One line, both sides: the books and GSTR-2B (with its raw copy), the differences and the decision."""
    today = today or date.today()
    match = db.execute(select(GstMatch).where(
        GstMatch.workspace_id == workspace.id,
        or_(GstMatch.id == line_id, GstMatch.record_id == line_id, GstMatch.work_item_id == line_id)).limit(1)).scalar_one_or_none()
    if match is None:
        return None
    detail = serialise(match, today)
    record = db.get(GstReturnRecord, match.record_id) if match.record_id else None
    detail["gstr2b"] = None if record is None else {
        "section": record.section, "kind": record.kind, "period": record.period, "supplier_filed_on": (
            record.supplier_filed_on.isoformat() if record.supplier_filed_on else None),
        "number": record.doc_number, "date": record.doc_date.isoformat() if record.doc_date else None,
        "taxable_micros": record.taxable_micros, "igst_micros": record.igst_micros, "cgst_micros": record.cgst_micros,
        "sgst_micros": record.sgst_micros, "cess_micros": record.cess_micros, "value_micros": record.value_micros,
        "place_of_supply": record.place_of_supply, "reverse_charge": record.reverse_charge,
        "itc_available": record.itc_available, "reason": record.reason, "irn": record.irn,
        "original_number": record.original_number, "raw": record.raw,
    }
    book = _book_side(db, workspace, match.work_item_id, match.gstin) if match.work_item_id else None
    if book and isinstance(book.get("date"), date):
        book["date"] = book["date"].isoformat()
    detail["books"] = book
    return detail


# --------------------------------------------------------------------------------------------- decisions


def _book_document(db: Session, workspace: Workspace, work_item_id: uuid.UUID) -> bool:
    return db.execute(select(func.count()).select_from(DocumentRole).where(
        DocumentRole.workspace_id == workspace.id, DocumentRole.work_item_id == work_item_id,
        DocumentRole.role.in_((ledger.ROLE_INVOICE, ledger.ROLE_CREDIT_NOTE)))).scalar_one() > 0


def decide(db: Session, *, workspace: Workspace, user_id: Optional[uuid.UUID], record_id: uuid.UUID, decision: str,
           work_item_id: Optional[uuid.UUID] = None, note: Optional[str] = None) -> dict[str, Any]:
    """Confirm a suggested match, mark a record "not ours", or link it by hand. Recomputes the GSTIN."""
    record = db.execute(select(GstReturnRecord).join(GstReturn, GstReturn.id == GstReturnRecord.return_id).where(
        GstReturnRecord.id == record_id, GstReturnRecord.workspace_id == workspace.id,
        GstReturn.status == v.RETURN_ACTIVE)).scalar_one_or_none()
    if record is None:
        raise DecisionError("RECORD_NOT_FOUND", "That GSTR-2B record was not found.", 404)
    if record.section not in v.MATCHABLE_SECTIONS or not record.supplier_gstin or not record.doc_key:
        raise DecisionError("RECORD_NOT_DECIDABLE", "This record has no supplier GSTIN or number to decide on.", 422)
    if decision not in v.DECISIONS:
        raise DecisionError("DECISION_UNKNOWN", "The decision must be CONFIRM, NOT_OURS or LINK.", 422)
    if decision == v.DECISION_CONFIRM:
        current = db.execute(select(GstMatch).where(GstMatch.workspace_id == workspace.id,
                                                    GstMatch.record_id == record_id)).scalar_one_or_none()
        if current is None or current.status != v.SUGGESTED or current.work_item_id is None:
            raise DecisionError("NOTHING_TO_CONFIRM", "There is no suggested match to confirm on this record.")
        if work_item_id is not None and work_item_id != current.work_item_id:
            raise DecisionError("NOT_THE_SUGGESTION", "That is not the invoice Servabo suggested; use link by hand.")
        work_item_id = current.work_item_id
    elif decision == v.DECISION_LINK:
        if work_item_id is None:
            raise DecisionError("DOCUMENT_REQUIRED", "Say which of your documents this record is.", 422)
        if not _book_document(db, workspace, work_item_id):
            raise DecisionError("DOCUMENT_NOT_FOUND", "That document was not found among your purchase invoices.", 404)
        taken = db.execute(select(GstDecision).where(
            GstDecision.workspace_id == workspace.id, GstDecision.gstin == record.gstin,
            GstDecision.work_item_id == work_item_id, GstDecision.doc_key != record.doc_key)).first()
        if taken is not None:
            raise DecisionError("DOCUMENT_ALREADY_LINKED", "That document is already linked to another record.")
    else:
        work_item_id = None
    row = db.execute(select(GstDecision).where(
        GstDecision.workspace_id == workspace.id, GstDecision.gstin == record.gstin,
        GstDecision.supplier_gstin == record.supplier_gstin, GstDecision.doc_key == record.doc_key,
        GstDecision.kind == record.kind)).scalar_one_or_none()
    if row is None:
        row = GstDecision(organization_id=workspace.organization_id, workspace_id=workspace.id, gstin=record.gstin,
                          supplier_gstin=record.supplier_gstin, doc_key=record.doc_key, kind=record.kind,
                          decision=decision)
        db.add(row)
    row.decision, row.work_item_id, row.note = decision, work_item_id, (note or None)
    row.decided_by_user_id = user_id
    row.decided_at = func.now()
    db.flush()
    audit_service.record(
        db, organization_id=workspace.organization_id, workspace_id=workspace.id, actor_id=user_id,
        resource_type=AuditResourceType.GST_MATCH, resource_id=record.id, action=AuditAction.UPDATED,
        details={"decision": decision, "gstin": record.gstin, "supplier_gstin": record.supplier_gstin,
                 "number": record.doc_number, "work_item_id": str(work_item_id) if work_item_id else None})
    engine.recompute(db, workspace, record.gstin)
    return {"decision": decision, "record_id": str(record.id), "gstin": record.gstin}


def undo_decision(db: Session, *, workspace: Workspace, user_id: Optional[uuid.UUID], record_id: uuid.UUID) -> dict[str, Any]:
    record = db.get(GstReturnRecord, record_id)
    if record is None or record.workspace_id != workspace.id:
        raise DecisionError("RECORD_NOT_FOUND", "That GSTR-2B record was not found.", 404)
    row = db.execute(select(GstDecision).where(
        GstDecision.workspace_id == workspace.id, GstDecision.gstin == record.gstin,
        GstDecision.supplier_gstin == record.supplier_gstin, GstDecision.doc_key == record.doc_key,
        GstDecision.kind == record.kind)).scalar_one_or_none()
    if row is None:
        raise DecisionError("NO_DECISION", "Nobody has decided on this record.")
    db.delete(row)
    db.flush()
    audit_service.record(
        db, organization_id=workspace.organization_id, workspace_id=workspace.id, actor_id=user_id,
        resource_type=AuditResourceType.GST_MATCH, resource_id=record.id, action=AuditAction.DELETED,
        details={"decision": row.decision, "gstin": record.gstin, "number": record.doc_number})
    engine.recompute(db, workspace, record.gstin)
    return {"record_id": str(record.id), "gstin": record.gstin}


__all__ = ["DecisionError", "MAX_LIMIT", "decide", "line_detail", "list_lines", "serialise", "undo_decision"]
