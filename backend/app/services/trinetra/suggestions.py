"""Suggested expectations (Final 2T, Phase 4): printed on an invoice, typed in the expectations template, or read from Zoho
Books. A suggestion is only ever a suggestion: it becomes a case when a person accepts it, with a reason, through the same
`create_case` as a typed expectation. Nothing here confirms, allocates or sends; a document or a file can only propose."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select

from app.models.document_role import DocumentRole
from app.models.trinetra import TrinetraCredit as CreditRow
from app.models.trinetra import TrinetraSuggestion as Suggestion
from app.models.work_item import WorkItem
from app.services.helm import identity as ident
from app.services.trinetra import directory, domain as d, fields, seller as sellers, service, versions

SCAN_LIMIT = 500
SOURCES = ("PRINTED_HINT", "TEMPLATE", "ZOHO")


def content_hash(amount_micros, deductor_key, section, evidence) -> str:
    return hashlib.sha256(
        json.dumps([amount_micros, deductor_key, section, evidence], sort_keys=True, default=str).encode()
    ).hexdigest()


def upsert(db, workspace, p, *, work_item_id, year, source, amount_micros, tan, section_text, counterparty, reference,
           source_version, evidence, deductor_key=None, tan_masked=None):
    """Create or refresh one suggestion. A dismissed suggestion stays dismissed while its content is unchanged; changed
    evidence reopens it (it is a different suggestion now). An accepted one is left alone (its case exists)."""
    salt = service.encryption.decrypt_secret(p.identity_salt_ciphertext)
    if tan:
        deductor_key, tan_masked = service.identity(tan, "TAN", salt), "******" + tan[-4:]
    digest = content_hash(amount_micros, deductor_key, section_text, evidence)
    row = (
        db.query(Suggestion)
        .filter_by(profile_id=p.id, work_item_id=work_item_id, year=year, source=source)
        .first()
    )
    if row is None:
        row = Suggestion(
            organization_id=workspace.organization_id, workspace_id=workspace.id, profile_id=p.id,
            work_item_id=work_item_id, year=year, source=source, amount_micros=amount_micros,
            deductor_key=deductor_key, tan_masked=tan_masked, section_text=section_text,
            counterparty=counterparty[:120], reference=reference[:100], source_version=source_version,
            content_hash=digest, evidence=evidence, status="OPEN",
        )
        db.add(row)
        db.flush()
        outcome = "created"
    elif row.content_hash == digest and row.source_version == source_version:
        return row, "unchanged"
    elif row.status == "ACCEPTED":
        return row, "unchanged"
    else:
        row.amount_micros, row.deductor_key, row.tan_masked = amount_micros, deductor_key, tan_masked
        row.section_text, row.counterparty, row.reference = section_text, counterparty[:120], reference[:100]
        row.source_version, row.content_hash, row.evidence = source_version, digest, evidence
        row.status, row.decided_by, row.decided_reason = "OPEN", None, None
        row.updated_at = datetime.now(timezone.utc)
        db.flush()
        outcome = "refreshed"
    if deductor_key and tan_masked:
        directory.observe(db, workspace, p, deductor_key, tan_masked, counterparty)
    return row, outcome


def scan_hints(db, workspace, p):
    """Invoices of this entity that print a TDS amount become suggestions. Bounded, and a document is read only for the
    hints it prints: nothing printed is believed beyond proposing."""
    from app.services.helm import ledger_store

    ids = [
        r.id
        for r in db.execute(
            select(WorkItem.id)
            .join(DocumentRole, DocumentRole.work_item_id == WorkItem.id)
            .where(
                WorkItem.workspace_id == workspace.id,
                DocumentRole.workspace_id == workspace.id,
                DocumentRole.role == "INVOICE",
                DocumentRole.currency == "INR",
                fields.has_hint_clause(WorkItem.extracted_entities),
            )
            .order_by(WorkItem.created_at.desc())
            .limit(SCAN_LIMIT)
        )
    ]
    counts = {"created": 0, "refreshed": 0, "unchanged": 0, "skipped": 0}
    if not ids:
        return counts
    entity_pan = service.encryption.decrypt_secret(p.pan_ciphertext)
    taken = {
        (c.work_item_id, c.year)
        for c in db.query(CreditRow.work_item_id, CreditRow.year).filter_by(profile_id=p.id)
    }
    facts_by_id = versions.load(db, workspace.id, ids)
    for fact in ledger_store.document_facts(db, workspace, ids=ids):
        if fact.role != "INVOICE" or not fact.total_micros or fact.total_micros <= 0 or fact.document_date is None:
            counts["skipped"] += 1
            continue
        year = d.tax_period(fact.document_date)[0]
        hint = fields.hints(fact.entities)
        verdict = sellers.check(fact.entities, entity_pan, p.name)
        if (
            verdict.outcome == sellers.MISMATCH
            or hint["amount_micros"] is None
            or not 0 < hint["amount_micros"] <= fact.total_micros
            or (fact.work_item_id, year) in taken
        ):
            counts["skipped"] += 1
            continue
        buyer = ident.buyer(fact.entities).name or "Customer"
        _, outcome = upsert(
            db, workspace, p, work_item_id=fact.work_item_id, year=year, source="PRINTED_HINT",
            amount_micros=hint["amount_micros"], tan=hint["tan"], section_text=hint["section_text"],
            counterparty=buyer, reference=fact.document_number or fact.filename[:100],
            source_version=facts_by_id[fact.work_item_id].invoice,
            evidence={"printed_on_invoice": True, "seller_match": verdict.outcome},
        )
        counts[outcome] += 1
    return counts


def view(row):
    return {
        "id": str(row.id), "profile_id": str(row.profile_id), "work_item_id": str(row.work_item_id), "year": row.year,
        "source": row.source, "amount_micros": str(row.amount_micros), "tan_masked": row.tan_masked,
        "needs_tan": row.deductor_key is None, "section_text": row.section_text, "counterparty": row.counterparty,
        "reference": row.reference, "status": row.status, "evidence": row.evidence or {},
        "decided_reason": row.decided_reason, "credit_id": str(row.credit_id) if row.credit_id else None,
        "created_at": row.created_at.isoformat(), "updated_at": row.updated_at.isoformat(),
        "note": "A suggestion only: nothing is confirmed until a person accepts it with a reason. A printed or "
                "imported figure is not a rate or section recommendation.",
    }


def listing(db, workspace, *, profile_id=None, year=None, status=None, limit=100, offset=0):
    query = db.query(Suggestion).filter_by(workspace_id=workspace.id)
    for column, value in ((Suggestion.profile_id, profile_id), (Suggestion.year, year), (Suggestion.status, status)):
        if value is not None:
            query = query.filter(column == value)
    total = query.count()
    rows = query.order_by(Suggestion.created_at, Suggestion.id).offset(offset).limit(limit).all()
    return {"total": total, "items": [view(r) for r in rows]}


def locked(db, workspace, suggestion_id):
    row = db.execute(
        select(Suggestion).filter_by(id=suggestion_id, workspace_id=workspace.id).with_for_update()
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Suggestion not found.")
    return row


def accept(db, workspace, p, user_id, row, *, source_confirmation, tan=None, amount=None, seller_name_confirmed=False):
    if row.status != "OPEN":
        raise HTTPException(409, "This suggestion was already decided.")
    facts = versions.one(db, workspace.id, row.work_item_id)
    if facts is None or facts.invoice != row.source_version:
        raise HTTPException(409, "The invoice changed since this was suggested. Scan again to see the current suggestion.")
    salt = service.encryption.decrypt_secret(p.identity_salt_ciphertext)
    key = row.deductor_key
    if tan:
        given = service.identity(tan, "TAN", salt)
        if key and given != key:
            raise HTTPException(422, "The TAN you entered is not the one this suggestion names.")
        key = given
    if not key:
        raise HTTPException(
            422,
            {"code": "TRINETRA_TAN_NEEDED",
             "message": "This suggestion does not carry the customer's TAN. Enter it from the customer's advice or your records."})
    mask = row.tan_masked or ("******" + tan[-4:] if tan else "")
    directory.require_unflagged(directory.lookup(db, p, key))
    case = service.create_case(
        db, workspace, p, user_id, work_item_id=row.work_item_id, year=row.year, counterparty=row.counterparty,
        reference=row.reference, tan=None, deductor_key=key,
        amount=(amount if amount is not None else row.amount_micros), source_confirmation=source_confirmation,
        seller_name_confirmed=seller_name_confirmed, origin=f"suggestion:{row.source}", section_text=row.section_text,
        evidence=row.evidence,
    )
    directory.observe(db, workspace, p, key, mask, row.counterparty)
    row.status, row.decided_by, row.decided_reason, row.credit_id = "ACCEPTED", user_id, source_confirmation, case.id
    row.updated_at = datetime.now(timezone.utc)
    db.flush()
    return case


def dismiss(db, row, user_id, reason):
    if row.status != "OPEN":
        raise HTTPException(409, "This suggestion was already decided.")
    row.status, row.decided_by, row.decided_reason = "DISMISSED", user_id, reason
    row.updated_at = datetime.now(timezone.utc)
    db.flush()
    return row


def match_template(db, workspace, p, lines):
    """Match each expectations-template row to a canonical invoice. Per row: OK, or the reason it is refused."""
    from sqlalchemy import func

    from app.services.helm import ledger_store

    entity_pan = service.encryption.decrypt_secret(p.pan_ciphertext)
    taken = {
        (c.work_item_id, c.year)
        for c in db.query(CreditRow.work_item_id, CreditRow.year).filter_by(profile_id=p.id)
    }
    found = {}
    for line in lines:
        found[line.row] = [
            r.work_item_id
            for r in db.execute(
                select(DocumentRole.work_item_id).where(
                    DocumentRole.workspace_id == workspace.id,
                    DocumentRole.role == "INVOICE",
                    func.lower(func.trim(DocumentRole.document_number)) == line.reference.strip().casefold(),
                ).limit(3)
            )
        ]
    ids = {i for v in found.values() if len(v) == 1 for i in v}
    facts = {f.work_item_id: f for f in ledger_store.document_facts(db, workspace, ids=ids)} if ids else {}
    versions_by_id = versions.load(db, workspace.id, ids)
    out = []
    for line in lines:
        base = {"row": line.row, "reference": line.reference, "tan_masked": "******" + line.tan[-4:],
                "amount_micros": str(line.amount_micros), "section_text": line.section or None}
        candidates = found[line.row]
        if not candidates:
            out.append({**base, "status": "NOT_FOUND", "reason": "No sales invoice in this workspace has this reference."})
            continue
        if len(candidates) > 1:
            out.append({**base, "status": "AMBIGUOUS", "reason": "More than one invoice has this reference; Servabo will not guess."})
            continue
        fact = facts.get(candidates[0])
        if fact is None or fact.currency != "INR" or not fact.total_micros or fact.total_micros <= 0 or fact.document_date is None:
            out.append({**base, "status": "NOT_USABLE", "reason": "The invoice is not a classified INR invoice with an amount and a date."})
            continue
        verdict = sellers.check(fact.entities, entity_pan, p.name)
        year = d.tax_period(fact.document_date)[0]
        if verdict.outcome == sellers.MISMATCH:
            out.append({**base, "status": "SELLER_MISMATCH", "reason": verdict.message()})
        elif line.amount_micros > fact.total_micros:
            out.append({**base, "status": "TDS_EXCEEDS_GROSS", "reason": "The expected TDS is more than the invoice's gross amount."})
        elif (fact.work_item_id, year) in taken:
            out.append({**base, "status": "ALREADY_A_CASE", "reason": "This invoice already has an expectation."})
        else:
            out.append({**base, "status": "OK", "reason": "", "work_item_id": str(fact.work_item_id), "year": year,
                        "customer": ident.buyer(fact.entities).name or "Customer",
                        "invoice_gross_micros": str(fact.total_micros), "invoice_date": fact.document_date.isoformat(),
                        "seller_match": verdict.outcome,
                        "_source_version": versions_by_id[fact.work_item_id].invoice})
    return out


def import_template(db, workspace, p, lines, results, *, skip_refused):
    refused = [r for r in results if r["status"] != "OK"]
    if refused and not skip_refused:
        raise HTTPException(
            422,
            {"code": "TRINETRA_TEMPLATE_ROWS_REFUSED",
             "message": f"{len(refused)} row(s) cannot be matched (see the preview). Fix them, or import the rest and skip these.",
             "rows": [{"row": r["row"], "status": r["status"], "reason": r["reason"]} for r in refused[:50]]},
        )
    by_row = {l.row: l for l in lines}
    created = refreshed = 0
    for r in results:
        if r["status"] != "OK":
            continue
        line = by_row[r["row"]]
        _, outcome = upsert(
            db, workspace, p, work_item_id=uuid.UUID(r["work_item_id"]), year=r["year"], source="TEMPLATE",
            amount_micros=line.amount_micros, tan=line.tan, section_text=line.section or None,
            counterparty=r["customer"], reference=line.reference, source_version=r["_source_version"],
            evidence={"template_row": line.row, "seller_match": r["seller_match"]},
        )
        created += outcome == "created"
        refreshed += outcome == "refreshed"
    return {"created": created, "refreshed": refreshed, "skipped": len(refused)}


def scan_zoho(db, workspace, p, *, year=None):
    """Read the TDS customers withheld from Zoho Books customer payments (read only) and suggest an expectation for each invoice
    Servabo knows. The result is also accounting evidence for the case; a person accepts it. UNVERIFIED until Final session 2B."""
    from datetime import date

    from sqlalchemy import func

    from app.models.erp import ErpTarget
    from app.services.erp import vocabulary as ev
    from app.services.erp import zoho
    from app.services.helm import ledger_store

    target = db.execute(
        select(ErpTarget).where(
            ErpTarget.workspace_id == workspace.id, ErpTarget.preset == ev.PRESET_ZOHO, ErpTarget.status == ev.TARGET_ACTIVE
        ).order_by(ErpTarget.created_at)
    ).scalars().first()
    if target is None:
        raise HTTPException(409, {"code": "TRINETRA_ZOHO_NOT_CONNECTED",
                                  "message": "Connect Zoho Books for this workspace first (Settings, ERP)."})
    this = d.tax_period(date.today())[0]
    first = year if year is not None else this - 1
    try:
        payments = zoho.customer_payments(db, target, date_start=f"{first}-04-01",
                                          date_end=f"{(year + 1) if year is not None else this + 1}-03-31")
    except zoho.ZohoError as exc:
        code = {"SCOPE": "TRINETRA_ZOHO_RECONNECT", "RECONNECT": "TRINETRA_ZOHO_RECONNECT",
                "NOT_CONNECTED": "TRINETRA_ZOHO_NOT_CONNECTED"}.get(exc.code, "TRINETRA_ZOHO_UNAVAILABLE")
        raise HTTPException(409 if code != "TRINETRA_ZOHO_UNAVAILABLE" else 502, {"code": code, "message": str(exc)}) from exc
    grouped: dict[str, dict] = {}
    for item in payments:
        entry = grouped.setdefault(item["invoice_number"].strip().casefold(),
                                   {"number": item["invoice_number"], "customer": item["customer"], "total": 0, "payments": []})
        entry["total"] += item["withheld_micros"]
        entry["payments"].append({"id": item["payment_id"], "date": item["date"]})
    counts = {"created": 0, "refreshed": 0, "unchanged": 0, "skipped": 0, "unknown_invoices": 0}
    if not grouped:
        return counts
    by_number: dict[str, list] = {}
    for r in db.execute(
        select(DocumentRole.work_item_id, func.lower(func.trim(DocumentRole.document_number))).where(
            DocumentRole.workspace_id == workspace.id, DocumentRole.role == "INVOICE",
            func.lower(func.trim(DocumentRole.document_number)).in_(list(grouped)))
    ):
        by_number.setdefault(r[1], []).append(r[0])
    ids = {v[0] for v in by_number.values() if len(v) == 1}
    facts = {f.work_item_id: f for f in ledger_store.document_facts(db, workspace, ids=ids)} if ids else {}
    version = versions.load(db, workspace.id, ids)
    entity_pan = service.encryption.decrypt_secret(p.pan_ciphertext)
    taken = {
        (c.work_item_id, c.year)
        for c in db.query(CreditRow.work_item_id, CreditRow.year).filter_by(profile_id=p.id)
    }
    for number, entry in grouped.items():
        candidates = by_number.get(number, [])
        if len(candidates) != 1:
            counts["unknown_invoices"] += 1
            continue
        fact = facts.get(candidates[0])
        if fact is None or fact.currency != "INR" or not fact.total_micros or fact.document_date is None:
            counts["skipped"] += 1
            continue
        verdict = sellers.check(fact.entities, entity_pan, p.name)
        invoice_year = d.tax_period(fact.document_date)[0]
        if verdict.outcome == sellers.MISMATCH or not 0 < entry["total"] <= fact.total_micros or (fact.work_item_id, invoice_year) in taken:
            counts["skipped"] += 1
            continue
        known = directory.by_customer(db, p, entry["customer"] or ident.buyer(fact.entities).name or "")
        evidence = {"accounting_record": True, "withheld_micros": entry["total"], "seller_match": verdict.outcome,
                    "zoho": {"customer": entry["customer"], "payments": entry["payments"][:20]}}
        _, outcome = upsert(
            db, workspace, p, work_item_id=fact.work_item_id, year=invoice_year, source="ZOHO", amount_micros=entry["total"],
            tan=None, section_text=None, counterparty=entry["customer"] or ident.buyer(fact.entities).name or "Customer",
            reference=fact.document_number or entry["number"], source_version=version[fact.work_item_id].invoice,
            evidence=evidence, deductor_key=known.deductor_key if known and known.status == "CONFIRMED" else None,
            tan_masked=known.tan_masked if known and known.status == "CONFIRMED" else None,
        )
        counts[outcome] += 1
    return counts
