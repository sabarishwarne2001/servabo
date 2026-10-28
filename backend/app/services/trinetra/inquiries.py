"""Authorized inquiries (Final 2T, Phase 6; N-206): a person drafts, a person approves, a person presses Send.

It goes through the existing email path and templates (escaped, bounded) to the customer's CONFIRMED contact in Helm (never an
address read from a document), carrying a secure document-request link from the existing cases/requests (no second portal) for
the customer's Form 16A, advice or correction response. A reply uploaded through the link is attached to the case as evidence of
the right kind and the case history records it. At most one inquiry per case per seven days unless a person overrides it with
a reason; sent inquiries are counted against the plan's monthly allowance. Never automatic: nothing here is reachable from a
worker, an automation or a document."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import func, select

from app.core.config import settings
from app.models.trinetra import TrinetraCredit as CreditRow
from app.models.trinetra import TrinetraDecision as Decision
from app.models.trinetra import TrinetraInquiry as Inquiry
from app.services.trinetra import directory, domain as d, service

KIND_LABEL = {
    "CERTIFICATE": "TDS certificate (Form 16A)",
    "DEDUCTOR_ADVICE": "withholding advice",
    "CORRECTION_RESPONSE": "correction response",
}
COOLDOWN = timedelta(days=7)
LINK_HOURS = 720
TEMPLATE_KEY = "trinetra-tds-inquiry"
OPEN_STATES = ("OPEN", "DISPUTED")


def mask_email(address: str) -> str:
    local, _, domain = (address or "").partition("@")
    return (local[:1] + "***@" + domain)[:120] if domain else "***"


def confirmed_contact(db, organization_id, counterparty: str):
    """The customer's email as a PERSON confirmed it in Helm, or None. A learned address (N-195) is never a recipient."""
    from app.models.helm import HelmCounterparty
    from app.services.helm import vocabulary as hv

    key = directory.name_key(counterparty)
    row = db.execute(
        select(HelmCounterparty).where(
            HelmCounterparty.organization_id == organization_id,
            HelmCounterparty.key == key,
            HelmCounterparty.contact_source == hv.CONTACT_SOURCE_PERSON,
            HelmCounterparty.contact_email.isnot(None),
        ).limit(1)
    ).scalar_one_or_none()
    return row.contact_email if row else None


def _month_start(now):
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def sent_this_month(db, organization_id, now=None) -> int:
    now = now or datetime.now(timezone.utc)
    return (
        db.query(func.count(Inquiry.id))
        .filter(Inquiry.organization_id == organization_id, Inquiry.sent_at >= _month_start(now),
                Inquiry.status.in_(("SENT", "REPLIED")))
        .scalar()
        or 0
    )


def allowance(db, workspace) -> int:
    from app.services.quota_service import plan_limit

    value = plan_limit(db, organization_id=workspace.organization_id, limit_key="limit.trinetra_inquiries_per_month")
    return min(value if value is not None else 50, 5000)


def view(row):
    return {
        "id": str(row.id), "credit_id": str(row.credit_id), "status": row.status, "document_kind": row.document_kind,
        "subject": row.subject, "body": row.body, "recipient_label": row.recipient_label,
        "recipient_masked": row.recipient_masked,
        "created_by": str(row.created_by) if row.created_by else None,
        "approved_by": str(row.approved_by) if row.approved_by else None,
        "approved_at": row.approved_at.isoformat() if row.approved_at else None,
        "sent_by": str(row.sent_by) if row.sent_by else None,
        "sent_at": row.sent_at.isoformat() if row.sent_at else None,
        "delivery_state": row.delivery_state, "delivery_detail": row.delivery_detail,
        "override_reason": row.override_reason,
        "replied_at": row.replied_at.isoformat() if row.replied_at else None,
        "reply_work_item_id": str(row.reply_work_item_id) if row.reply_work_item_id else None,
        "created_at": row.created_at.isoformat(),
        "note": "Sent only by a person who pressed Send, to the customer's confirmed contact. It requests a document and "
                "alleges nothing.",
    }


def _default_text(case) -> tuple[str, str]:
    return (
        "Please help us match the tax deducted on invoice " + case.reference,
        "We are comparing our records with the statement supplied to us for this period. This is a request for a "
        "document; it does not allege missing filing or establish tax-credit eligibility.",
    )


def create_draft(db, workspace, case, user_id, *, document_kind, subject=None, body=None):
    if case.state not in OPEN_STATES:
        raise HTTPException(409, "Only an open case can be the subject of an inquiry.")
    default_subject, default_body = _default_text(case)
    row = Inquiry(
        organization_id=workspace.organization_id, workspace_id=workspace.id, credit_id=case.id,
        document_kind=document_kind, subject=(subject or default_subject)[:200], body=(body or default_body)[:2000],
        status="DRAFT", recipient_label=case.counterparty[:200], created_by=user_id,
    )
    db.add(row)
    db.flush()
    return row


def edit_draft(db, row, user_id, *, subject=None, body=None):
    if row.status not in ("DRAFT",):
        raise HTTPException(409, "Only a draft can be edited. Withdraw this inquiry and write a new one.")
    if subject is not None:
        row.subject = subject[:200]
    if body is not None:
        row.body = body[:2000]
    row.updated_at = datetime.now(timezone.utc)
    db.flush()
    return row


def require_contact(db, workspace, row):
    address = confirmed_contact(db, workspace.organization_id, row.recipient_label)
    if address is None:
        raise HTTPException(
            422,
            {"code": "TRINETRA_NO_CONFIRMED_CONTACT",
             "message": f"There is no confirmed email contact for {row.recipient_label}. Confirm the customer's email in "
                        "Helm's counterparties first; Servabo never writes to an address it only read from a document."},
        )
    return address


def approve(db, workspace, row, user_id):
    if row.status != "DRAFT":
        raise HTTPException(409, "Only a draft can be approved.")
    address = require_contact(db, workspace, row)
    row.status, row.approved_by, row.approved_at = "APPROVED", user_id, datetime.now(timezone.utc)
    row.recipient_masked = mask_email(address)
    db.flush()
    return row


def _template(db, workspace):
    from app.models.cases import CaseTemplate
    from app.services.cases import templates
    from app.services.cases import vocabulary as cv

    found = db.execute(select(CaseTemplate).where(
        CaseTemplate.workspace_id == workspace.id, CaseTemplate.key == TEMPLATE_KEY,
        CaseTemplate.status == cv.TEMPLATE_PUBLISHED)).scalar_one_or_none()
    if found is not None:
        return found
    draft = templates.create(db, organization_id=workspace.organization_id, workspace_id=workspace.id, actor_user_id=None,
                             payload={"key": TEMPLATE_KEY, "name": "TDS inquiry (TRINETRA)",
                                      "description": "A customer's Form 16A, withholding advice or correction response, "
                                                     "asked for by a person from TRINETRA.",
                                      "assembly_key": cv.ASSEMBLY_MANUAL,
                                      "required_documents": [{"doc_type": "tds_document", "label": "TDS document"}],
                                      "request_ttl_hours": LINK_HOURS})
    return templates.publish(db, template=draft)


def send(db, workspace, case, row, user_id, *, override_reason=None):
    """Press Send. Refused unless approved, the contact is still confirmed, the week's one inquiry is free (or a person
    overrides with a reason) and the plan's monthly allowance has room."""
    from app.services.cases import assembly, requests
    from app.services.cases import vocabulary as cv
    from app.services.helm import hands, money
    from app.templates.emails import trinetra as mail

    if row.status not in ("APPROVED", "FAILED"):
        raise HTTPException(409, "Approve the draft before sending it." if row.status == "DRAFT" else "This inquiry was already sent or withdrawn.")
    if case.state not in OPEN_STATES:
        raise HTTPException(409, "Only an open case can be the subject of an inquiry.")
    address = require_contact(db, workspace, row)
    now = datetime.now(timezone.utc)
    recent = db.query(Inquiry.id).filter(
        Inquiry.credit_id == case.id, Inquiry.id != row.id, Inquiry.status.in_(("SENT", "REPLIED")),
        Inquiry.sent_at >= now - COOLDOWN).first()
    if recent is not None:
        if not override_reason or len(override_reason.strip()) < 10:
            raise HTTPException(
                409,
                {"code": "TRINETRA_INQUIRY_TOO_SOON",
                 "message": "An inquiry about this case went out in the last 7 days. Wait, or send again with a reason."})
        row.override_reason = override_reason.strip()[:500]
    limit = allowance(db, workspace)
    if sent_this_month(db, workspace.organization_id, now) >= limit:
        raise HTTPException(
            409,
            {"code": "TRINETRA_INQUIRY_ALLOWANCE",
             "message": f"Your plan allows {limit} sent TRINETRA inquiries a month and this month's are used. "
                        + service.raise_hint(db, workspace)})
    ok, detail = hands.email_destination(db, organization_id=workspace.organization_id, workspace_id=workspace.id, to=address)
    if not ok:
        raise HTTPException(422, {"code": "TRINETRA_DESTINATION_REFUSED", "message": detail})
    assembled = assembly.open_case(db, _template(db, workspace), anchor_kind=cv.ASSEMBLY_MANUAL,
                                   title=f"TDS inquiry: {case.counterparty} {case.reference}"[:200])
    request, token = requests.create(db, case=assembled, document_type="tds_document", recipient_label=row.recipient_label,
                                     actor_user_id=user_id, ttl_hours=LINK_HOURS)
    url = f"{settings.FRONTEND_URL.rstrip('/')}/request/{token}"
    amount_text = money.say(case.expected_micros, "INR")
    subject, html_body, text_body = mail.render_inquiry(
        organization_name=hands._organization_name(db, workspace.organization_id),  # noqa: SLF001
        customer_name=row.recipient_label, invoice_number=case.reference, amount_text=amount_text,
        period_label=d.tax_period(date(case.year, 4, 1))[1],
        document_label=KIND_LABEL[row.document_kind], note=row.body, upload_url=url,
        valid_until=money.day(request.expires_at.date()))
    row.subject = subject[:200]
    row.request_id = request.id
    row.sent_by = user_id
    try:
        hands.send_mail(db, organization_id=workspace.organization_id, workspace_id=workspace.id, to=address,
                        subject=subject, html_body=html_body, text_body=text_body)
    except hands.HandError as exc:
        requests.revoke(db, request=request)
        row.status, row.delivery_state, row.delivery_detail = "FAILED", "FAILED", exc.message[:300]
        db.flush()
        return row
    row.status, row.sent_at, row.delivery_state, row.delivery_detail = "SENT", now, "SENT", "Accepted by the mail server."
    row.recipient_masked = mask_email(address)
    case.revision += 1
    db.add(Decision(
        organization_id=workspace.organization_id, workspace_id=workspace.id, credit_id=case.id, actor_id=user_id,
        revision=case.revision, action="INQUIRY_SENT",
        reason=f"Inquiry sent to {row.recipient_masked} for a {KIND_LABEL[row.document_kind]}; approved by "
               f"{row.approved_by}, sent by {user_id}." + (f" Override: {row.override_reason}" if row.override_reason else ""),
        allocations=service.carry(db, case),
        evidence_work_item_ids=case.evidence_work_item_ids or [],
    ))
    db.flush()
    return row


def withdraw(db, row, user_id):
    from app.models.cases import DocumentRequest
    from app.services.cases import requests

    if row.status not in ("DRAFT", "APPROVED", "SENT", "FAILED"):
        raise HTTPException(409, "This inquiry is already closed.")
    if row.request_id:
        request = db.get(DocumentRequest, row.request_id)
        if request is not None and request.status == "OPEN":
            requests.revoke(db, request=request)
    row.status, row.updated_at = "WITHDRAWN", datetime.now(timezone.utc)
    db.flush()
    return row


def reply_received(db, request, work_item):
    """The customer uploaded through the inquiry's link: attach it to THAT case as evidence of the kind asked for, and record
    it in the case history. Only the inquiry that made this request is touched, so a reply can attach to no other case."""
    row = db.execute(select(Inquiry).where(Inquiry.request_id == request.id).with_for_update()).scalar_one_or_none()
    if row is None or row.status not in ("SENT", "FAILED"):
        return None
    case = db.execute(select(CreditRow).where(CreditRow.id == row.credit_id, CreditRow.workspace_id == row.workspace_id)
                      .with_for_update()).scalar_one()
    from app.services.trinetra import versions

    facts = versions.one(db, case.workspace_id, work_item.id)
    now = datetime.now(timezone.utc)
    review = dict(case.review or {})
    review["evidence"] = list(review.get("evidence", [])) + [{
        "work_item_id": str(work_item.id), "kind": row.document_kind, "source_version": facts.evidence if facts else "",
        "amount_micros": None, "added_at": now.isoformat(), "from_inquiry": str(row.id)}]
    case.review = review
    case.evidence_work_item_ids = list(case.evidence_work_item_ids or []) + [str(work_item.id)]
    case.revision += 1
    row.status, row.reply_work_item_id, row.replied_at = "REPLIED", work_item.id, now
    db.add(Decision(
        organization_id=case.organization_id, workspace_id=case.workspace_id, credit_id=case.id, actor_id=None,
        revision=case.revision, action="INQUIRY_REPLY",
        reason=f"The customer replied through the secure link with a {KIND_LABEL[row.document_kind]}; attached as evidence. "
               "Check the amount and enter it on the case.",
        allocations=service.carry(db, case), evidence_work_item_ids=case.evidence_work_item_ids))
    db.flush()
    return row
