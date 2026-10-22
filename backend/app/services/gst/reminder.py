"""The supplier reminder: a drafted email listing the supplier's invoices that are in our books but in no GSTR-2B.

Drafting never sends anything. Sending is a separate, explicit request, and goes only to a contact Helm already knows
for that supplier (Helm's counterparty contact), through the same mail path as Helm's supplier-statement emails; the
sample company never sends.
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.gst import GstMatch
from app.models.helm import HelmCounterparty
from app.models.workspace import Workspace
from app.services.gst import vocabulary as v
from app.services.helm import hands
from app.templates.emails import gst as templates

MAX_LINES = 100


def known_contact(db: Session, workspace: Workspace, supplier_gstin: str) -> Optional[str]:
    row = db.execute(select(HelmCounterparty.contact_email).where(
        HelmCounterparty.organization_id == workspace.organization_id,
        # By the tax id Helm's sync records, or by the `gstin:<GSTIN>` key a supplier keyed on its GSTIN carries.
        or_(HelmCounterparty.tax_id.ilike(f"%{supplier_gstin}%"), HelmCounterparty.key.ilike(f"%{supplier_gstin}")),
        HelmCounterparty.contact_email.isnot(None)).limit(1)).scalar_one_or_none()
    return row or None


def draft(db: Session, workspace: Workspace, gstin: str, supplier_gstin: str) -> dict[str, Any]:
    rows = list(db.execute(select(GstMatch).where(
        GstMatch.workspace_id == workspace.id, GstMatch.gstin == gstin, GstMatch.supplier_gstin == supplier_gstin,
        GstMatch.status == v.WAITING_FOR_SUPPLIER).order_by(GstMatch.doc_date).limit(MAX_LINES)).scalars())
    if not rows:
        return {"supplier_gstin": supplier_gstin, "lines": [], "subject": None, "text": None, "html": None, "to": None,
                "can_send": False, "note": "Nothing from this supplier is waiting."}
    name = next((r.supplier_name for r in rows if r.supplier_name), supplier_gstin)
    lines = [{"number": r.doc_number, "date": r.doc_date.isoformat() if r.doc_date else "",
              "amount_micros": r.value_micros or 0, "tax_micros": r.tax_micros or 0} for r in rows]
    first, last = rows[0].doc_date, rows[-1].doc_date
    period_text = (f"{first:%B %Y}" if first == last or (first and last and (first.year, first.month) == (last.year, last.month))
                   else f"{first:%B %Y} to {last:%B %Y}") if first and last else "the periods imported"
    subject, html, text = templates.render_missing_invoices(
        organization_name=hands._organization_name(db, workspace.organization_id), supplier_name=name,
        period_text=period_text, lines=lines)
    contact = known_contact(db, workspace, supplier_gstin)
    return {"supplier_gstin": supplier_gstin, "supplier_name": name, "lines": lines, "subject": subject, "text": text,
            "html": html, "to": contact, "can_send": bool(contact) and not workspace.is_sample,
            "note": (None if contact else "No email contact is known for this supplier; copy the draft into your own "
                     "email, or add the contact in Helm's settings.")}


def send(db: Session, workspace: Workspace, gstin: str, supplier_gstin: str) -> dict[str, Any]:
    prepared = draft(db, workspace, gstin, supplier_gstin)
    if not prepared["lines"]:
        return {**prepared, "sent": False}
    if workspace.is_sample:
        return {**prepared, "sent": False, "note": "The sample company never sends email."}
    if not prepared["to"]:
        return {**prepared, "sent": False}
    sent = hands.send_mail(db, organization_id=workspace.organization_id, workspace_id=workspace.id, to=prepared["to"],
                           subject=prepared["subject"], html_body=prepared["html"], text_body=prepared["text"])
    return {**prepared, "sent": True, "detail": sent}


__all__ = ["draft", "known_contact", "send"]
