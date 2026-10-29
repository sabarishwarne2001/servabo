"""Transactional reviewed evidence adapter. Locks serialize profile revisions/allocations."""

import hashlib
import hmac
import json
import re
import uuid
import secrets
from datetime import date, datetime, timezone
from dataclasses import asdict
from fastapi import HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import select
from app.core import encryption
from app.models.organization import Organization
from app.models.workspace import Workspace
from app.models.work_item import WorkItem
from app.models.document_role import DocumentRole
from app.models.trinetra import (
    TrinetraProfile as Profile,
    TrinetraStatement as Statement,
    TrinetraCredit as CreditRow,
    TrinetraDecision as Decision,
    TrinetraOrgKey as OrgKey,
    TrinetraPairing as Pairing,
    TrinetraOutcome as Outcome,
)
from app.services.trinetra import domain as d
from app.services.trinetra import approvals, versions


def evidence_ids(review):
    """The documents a case's evidence points at (a record read from an accounting system points at none)."""
    return [uuid.UUID(e["work_item_id"]) for e in (review or {}).get("evidence", []) if e.get("work_item_id")]


def evidence_current(item, facts):
    """Is this piece of evidence what the reviewer saw? A document: its fingerprint is unchanged. A record read from an
    accounting system is immutable once attached, so it stays current (its source_version is its own content hash)."""
    if not item.get("work_item_id"):
        return bool(item.get("source_version"))
    doc = facts.get(uuid.UUID(item["work_item_id"]))
    return bool(doc and doc.evidence == item["source_version"])


#: Parts of a case's review record that a review update must carry over: where the expectation came from, its printed
#: section, and the reviewer's rejections and annotations of statement matches (Phase 5).
KEPT_REVIEW_KEYS = ("origin", "origin_evidence", "section_text", "rejected_candidates", "annotations", "basis", "triggering_event")


#: Recorded in the case history when the seller was matched by name alone and a reviewer confirmed it.
SELLER_NAME_NOTE = {
    "NAME_ONLY": " Seller matched by name only (no PAN or valid GSTIN printed); confirmed by the reviewer."
}


#: A superseded snapshot or a closed case is not working capacity, but it is kept (and counted) until the retention
#: policy erases the documents it was built from. The ceiling is a multiple of the plan's working figure (N-202).
RETENTION_MULTIPLIER = {"snapshots": 20, "cases": 40}
#: The most cases one workspace's cockpit reads at once: open cases plus recently closed ones. Older closed cases stay
#: in the database (and in the dossier, by year) but out of the working set, so a real year never hits a wall.
WORKING_SET_LIMIT = 5000
OPEN_STATES = ("OPEN", "DISPUTED")
#: Statuses that need no more work from a reviewer: the credit is in the statement, or the case is closed.
RESOLVED_STATUSES = ("POSTED", "LATE_POSTING", "VERIFIED_CORRECTED", "WITHDRAWN", "CLOSED_WITH_EXCEPTION", "UNRESOLVED")
CLOSED_STATES = ("EXPLAINED", "WITHDRAWN", "CA_REVIEWED", "UNRESOLVED")
#: A closed case this many tax years old (or older) leaves the working set.
CLOSED_RETENTION_YEARS = 3


def capacity(db, workspace, kind):
    """The plan's WORKING capacity: profiles; ACTIVE snapshots (one per profile and tax year); OPEN cases.

    Pinned published plan, with a finite platform ceiling even for legacy tiers."""
    from app.services.quota_service import plan_limit

    baseline, ceiling = {
        "profiles": (2, 10),
        "snapshots": (12, 60),
        "cases": (500, 5000),
    }[kind]
    value = plan_limit(
        db,
        organization_id=workspace.organization_id,
        limit_key="limit.trinetra_" + kind,
    )
    return min(value if value is not None else baseline, ceiling)


def raise_hint(db, workspace) -> str:
    """The plan that raises a limit, in words (a refusal names it)."""
    from app.api.capability_gate import has_capability

    if has_capability(
        db,
        organization_id=workspace.organization_id,
        capability_key="capability.trinetra_all_workspaces",
    ):
        return "Ask Servabo to raise the limit for your Enterprise plan."
    return "Enterprise raises it."


def working_set(query, today=None):
    """Narrow a CreditRow query to the working set: every open case, and closed cases of recent tax years."""
    from datetime import date

    cutoff = d.tax_period(today or date.today())[0] - CLOSED_RETENTION_YEARS
    return query.filter(
        CreditRow.state.in_(OPEN_STATES) | (CreditRow.year >= cutoff)
    )


def check_case_capacity(db, workspace):
    """Admit one more OPEN case: under the plan's open-case figure, and under the retention ceiling for all cases."""
    working = capacity(db, workspace, "cases")
    base = db.query(CreditRow).filter_by(organization_id=workspace.organization_id)
    if base.filter(CreditRow.state.in_(OPEN_STATES)).count() >= working:
        raise HTTPException(
            409,
            f"Your plan allows {working} open TRINETRA cases. Close or withdraw finished cases to free room. "
            + raise_hint(db, workspace),
        )
    if base.count() >= working * RETENTION_MULTIPLIER["cases"]:
        raise HTTPException(
            409,
            "The retention ceiling for TRINETRA cases is reached. Closed cases age out with the documents they were "
            "built from under your retention policy. " + raise_hint(db, workspace),
        )


def lock_capacity(db, workspace):
    # Serialize admission without blocking FK KEY SHARE checks from child inserts.
    db.execute(
        select(Organization)
        .where(Organization.id == workspace.organization_id)
        .with_for_update(key_share=True)
    ).scalar_one()


def identity(raw: str, kind: str, salt: str) -> str:
    pattern = r"[A-Z]{5}[0-9]{4}[A-Z]" if kind == "PAN" else r"[A-Z]{4}[0-9]{5}[A-Z]"
    if not re.fullmatch(pattern, raw):
        raise HTTPException(422, f"Invalid {kind} format.")
    return hmac.new(salt.encode(), raw.encode(), hashlib.sha256).hexdigest()


def document(db, workspace, id):
    row = db.query(WorkItem).filter_by(id=id, workspace_id=workspace.id).first()
    if row is None:
        raise HTTPException(404, "Evidence document not found.")
    return row


def invoice_version(db, workspace, item_id):
    """The invoice's fingerprint now (what it is, not when its row was last touched); None when it is gone."""
    facts = versions.one(db, workspace.id, item_id)
    return facts.invoice if facts else None


def receivable(db, workspace, p, source_id, *, seller_name_confirmed=False):
    """Use canonical document facts and Helm's identity rules, without changing its ledger.

    Returns (source, fact, seller). `seller.outcome` is MATCH, or NAME_ONLY when a reviewer confirmed the seller by name
    because the invoice prints no PAN and no valid GSTIN (the caller records that in the case history)."""
    from app.services.helm import ledger_store
    from app.services.trinetra import seller as sellers

    source = document(db, workspace, source_id)
    facts = ledger_store.document_facts(db, workspace, ids=[source_id])
    if (
        not facts
        or facts[0].role != "INVOICE"
        or facts[0].currency != "INR"
        or not facts[0].total_micros
        or facts[0].total_micros <= 0
    ):
        raise HTTPException(
            422,
            "Choose a classified INR invoice with a positive source amount. Reversals require accountant review.",
        )
    fact = facts[0]
    verdict = sellers.check(fact.entities, encryption.decrypt_secret(p.pan_ciphertext), p.name)
    if verdict.outcome == sellers.MISMATCH:
        raise HTTPException(422, verdict.message())
    if verdict.outcome == sellers.NAME_ONLY and not seller_name_confirmed:
        raise HTTPException(
            422,
            {
                "code": "TRINETRA_SELLER_NAME_ONLY",
                "message": "The invoice prints no PAN and no valid GSTIN for the seller, so it can only be matched to this entity by name. Check the invoice and confirm the seller by name to continue.",
            },
        )
    return source, fact, verdict


def check_triggering_event(db, workspace, fact, year, event):
    """A person places the expectation in the tax year of an EARLIER triggering event (an advance received before the invoice),
    with a reason and the document that shows it. Never inferred from dates or amounts."""
    if fact.document_date is None:
        raise HTTPException(422, "The invoice has no date, so an earlier period cannot be compared.")
    invoice_year = d.tax_period(fact.document_date)[0]
    if not 2000 <= int(year) < invoice_year:
        raise HTTPException(
            422,
            "A triggering event must fall in a tax year before the invoice's. For the invoice's own year, leave it out.",
        )
    reason = (event.get("reason") or "").strip()
    if len(reason) < 20:
        raise HTTPException(422, "Say why this period applies (at least 20 characters).")
    evidence_id = event.get("evidence_work_item_id")
    if not evidence_id:
        raise HTTPException(422, "Attach the document that shows the earlier event, such as the advance receipt.")
    document(db, workspace, uuid.UUID(str(evidence_id)))
    return {"year": int(year), "reason": reason[:500], "evidence_work_item_id": str(evidence_id)}


def invoice_period(fact, year):
    # This reviewed-invoice workflow excludes earlier advances/trigger events.
    # It does not determine the legally applicable withholding period.
    if fact.document_date is None or d.tax_period(fact.document_date)[0] != year:
        raise HTTPException(
            422,
            "The selected period must contain the sourced invoice date. Earlier advances or other triggering events require a separately validated workflow.",
        )


def profile(db, workspace, id):
    row = db.execute(
        select(Profile)
        .filter_by(
            id=id, workspace_id=workspace.id, organization_id=workspace.organization_id
        )
        .with_for_update()
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Tax profile not found.")
    return row


def org_salt(db, organization_id) -> str:
    """The organization's random PAN-fingerprint salt, created on first use (call under `lock_capacity`)."""
    row = db.get(OrgKey, organization_id)
    if row is None:
        row = OrgKey(
            organization_id=organization_id,
            salt_ciphertext=encryption.encrypt_secret(secrets.token_hex(32)),
        )
        db.add(row)
        db.flush()
    return encryption.decrypt_secret(row.salt_ciphertext)


def org_fingerprint(salt: str, pan: str) -> str:
    return hmac.new(salt.encode(), b"trinetra-org-pan:" + pan.encode("ascii"), hashlib.sha256).hexdigest()


def create_profile(db, workspace, name, pan):
    lock_capacity(db, workspace)
    identity(pan, "PAN", "validation-only")
    salt = org_salt(db, workspace.organization_id)
    fingerprint = org_fingerprint(salt, pan)
    # A profile made before the organization fingerprint existed: fill it in now (under the organization lock).
    for legacy in db.query(Profile).filter_by(
        organization_id=workspace.organization_id, org_pan_fingerprint=None
    ):
        key = org_fingerprint(salt, encryption.decrypt_secret(legacy.pan_ciphertext))
        if not db.query(Profile.id).filter_by(
            organization_id=workspace.organization_id, org_pan_fingerprint=key
        ).first():
            legacy.org_pan_fingerprint = key
    db.flush()
    held = (
        db.query(Profile)
        .filter_by(organization_id=workspace.organization_id, org_pan_fingerprint=fingerprint)
        .first()
    )
    if held is not None:
        if held.workspace_id == workspace.id:
            return held
        where = db.get(Workspace, held.workspace_id)
        raise HTTPException(
            409,
            {
                "code": "TRINETRA_ENTITY_HAS_PROFILE",
                "message": "This legal entity already has a TRINETRA profile in the workspace "
                f"\"{where.workspace_name if where else 'another workspace'}\". An organization keeps one profile "
                "per legal entity, so the same tax credit is never counted twice. Use that workspace, or ask an "
                "administrator to remove its profile first.",
            },
        )
    salt_profile = secrets.token_hex(32)
    key = identity(pan, "PAN", salt_profile)
    if db.query(Profile).filter_by(
        organization_id=workspace.organization_id
    ).count() >= capacity(db, workspace, "profiles"):
        raise HTTPException(
            409,
            "Legal-entity profile limit reached for this plan version. " + raise_hint(db, workspace),
        )
    row = Profile(
        organization_id=workspace.organization_id,
        workspace_id=workspace.id,
        name=name,
        identity_salt_ciphertext=encryption.encrypt_secret(salt_profile),
        pan_ciphertext=encryption.encrypt_secret(pan),
        pan_fingerprint=key,
        pan_masked="******" + pan[-4:],
        org_pan_fingerprint=fingerprint,
    )
    db.add(row)
    db.flush()
    return row


def scope(workspace, p, year):
    return d.Scope(str(workspace.organization_id), str(workspace.id), str(p.id), year)


def credit(row, workspace):
    return d.Credit(
        str(row.id),
        d.Scope(
            str(row.organization_id), str(workspace.id), str(row.profile_id), row.year
        ),
        row.deductor_key,
        row.expected_micros,
        str(row.work_item_id),
        disputed=row.state == "DISPUTED",
        reference=row.reference,
        section=(row.review or {}).get("section_text") or None,
    )


def current(db, p, year):
    snapshot = (
        db.query(Statement)
        .filter_by(profile_id=p.id, workspace_id=p.workspace_id, year=year, active=True)
        .first()
    )
    if snapshot and snapshot.source_work_item_id is not None:
        facts = versions.one(db, p.workspace_id, snapshot.source_work_item_id)
        if facts is None or facts.statement != snapshot.source_version:
            return None
    return snapshot  # a file-sourced snapshot is identified by its file's SHA-256 and cannot go stale


def allocations(db, p, year):
    decisions = (
        db.query(Decision)
        .join(
            CreditRow,
            (Decision.credit_id == CreditRow.id)
            & (Decision.revision == CreditRow.revision),
        )
        .filter(
            CreditRow.profile_id == p.id,
            CreditRow.year == year,
            CreditRow.workspace_id == p.workspace_id,
        )
        .all()
    )
    return [d.Allocation(**a) for dec in decisions for a in dec.allocations]


def carry(db, row):
    """The case's current allocations, to be written onto a new revision that is not an allocation decision (an inquiry sent,
    a reply received): only the current decision's allocations count, so they must be carried forward."""
    p = db.get(Profile, row.profile_id)
    return [asdict(a) for a in allocations(db, p, row.year) if a.credit == str(row.id)]


def decision_sources(db, row, p):
    snapshot = current(db, p, row.year)
    return sorted(
        {
            str(row.work_item_id),
            *(row.evidence_work_item_ids or []),
            *([str(snapshot.source_work_item_id)] if snapshot and snapshot.source_work_item_id else []),
        }
    )


def active_pairings(db, snapshot_ids):
    """The reviewed reversal pairings of these snapshots: {snapshot id: [pairing, ...]}."""
    if not snapshot_ids:
        return {}
    out = {}
    for row in db.query(Pairing).filter(
        Pairing.statement_id.in_(list(snapshot_ids)), Pairing.active.is_(True)
    ):
        out.setdefault(row.statement_id, []).append(row)
    return out


def net_amounts(rows, pairings):
    """Each row's amount after the reversals a person paired with it. A paired reversal nets out to zero; an unpaired one
    keeps its negative amount (an exception no allocation can use)."""
    net = [r["amount_micros"] for r in rows]
    for pair in pairings:
        net[pair.positive_line] += net[pair.negative_line]
        net[pair.negative_line] = 0
    return net


def postings(snapshot, workspace, p, pairings=()):
    if not snapshot:
        return []
    net = net_amounts(snapshot.rows, pairings)
    return [
        d.Posting(
            str(i),
            scope(workspace, p, snapshot.year),
            r["deductor_key"],
            net[i],
            str(snapshot.id),
            r["reference"],
            r.get("section") or None,
            date.fromisoformat(r["on"]) if r.get("on") else None,
            date.fromisoformat(r["booked_on"]) if r.get("booked_on") else None,
        )
        for i, r in enumerate(snapshot.rows)
    ]


def _reader_of(snapshot):
    """How the active statement was read, for the case: the reader, the file's own tax-year label and whether the reader
    is verified (an unverified reader is labelled as such on the snapshot)."""
    if snapshot is None:
        return None
    meta = snapshot.source_meta or {}
    return dict(
        key=meta.get("reader") or snapshot.parser_version,
        label=meta.get("reader_label") or "Rows typed by hand",
        official=bool(meta.get("official", False)),
        verified=bool(meta.get("verified", True)),
        tax_year_label=meta.get("label"),
    )


def view(db, workspace, row, bundle=None, facts=None, roles=None):
    if bundle is None:
        p = db.get(Profile, row.profile_id)
        snapshot = current(db, p, row.year)
        bundle = (
            p,
            snapshot,
            postings(
                snapshot,
                workspace,
                p,
                active_pairings(db, [snapshot.id] if snapshot else []).get(snapshot.id, ()) if snapshot else (),
            ),
            allocations(db, p, row.year),
        )
    p, snapshot, posting_rows, allocated = bundle
    if facts is None:
        facts = versions.load(
            db,
            workspace.id,
            [row.work_item_id]
            + evidence_ids(row.review),
        )
    source = facts.get(row.work_item_id)
    role = (
        roles.get(row.work_item_id)
        if roles is not None
        else db.query(DocumentRole)
        .filter_by(work_item_id=row.work_item_id, workspace_id=workspace.id)
        .first()
    )
    source_current = source is not None and source.invoice == row.source_version
    expectation = credit(row, workspace)
    reviewed = dict(row.review or {})
    reviewed["evidence"] = []
    for item in (row.review or {}).get("evidence", []):
        reviewed["evidence"].append({**item, "current": evidence_current(item, facts)})
    from dataclasses import replace

    for kind, field in [
        ("DEDUCTOR_ADVICE", "advice_micros"),
        ("ACCOUNTING_RECORD", "booked_micros"),
    ]:
        values = [
            item["amount_micros"]
            for item in reviewed["evidence"]
            if item["current"]
            and item["kind"] == kind
            and item["amount_micros"] is not None
        ]
        if values:
            expectation = replace(expectation, **{field: sum(values)})
    credit_notes = sum(
        item["amount_micros"] or 0
        for item in reviewed["evidence"]
        if item["current"] and item["kind"] == "CREDIT_NOTE"
    )
    basis = (row.review or {}).get("basis") or {}
    sourced_basis = bool(basis) and any(
        e["current"] and (e.get("work_item_id") or "") == (basis.get("evidence_work_item_id") or "")
        for e in reviewed["evidence"]
    )
    corrected = bool(snapshot) and any(
        item["current"]
        and item["kind"] == "CORRECTION_RESPONSE"
        and (item.get("added_at") or "9999") < snapshot.created_at.isoformat()
        for item in reviewed["evidence"]
    )
    rejected = frozenset(
        (r["snapshot_id"], r["line_id"])
        for r in (row.review or {}).get("rejected_candidates", [])
    )
    expectation = replace(
        expectation,
        credit_notes_micros=credit_notes,
        basis_micros=basis.get("micros") if sourced_basis else None,
        basis_source=basis.get("source") if sourced_basis else None,
        corrected=corrected,
        rejected=rejected,
    )
    if source_current:
        if role:
            expectation = replace(expectation, gross_micros=role.total_micros)
    if not source_current:
        from dataclasses import replace

        expectation = replace(expectation, expected=None, source="")
        # Old allocations remain in the immutable audit trail, not current exposure.
        allocated = [a for a in allocated if a.credit != str(row.id)]
    value = d.reconcile(
        expectation, posting_rows, allocated, statement_available=snapshot is not None
    )
    value["source_current"] = source_current
    if row.state in ("WITHDRAWN", "EXPLAINED", "UNRESOLVED"):
        value["status"] = {
            "WITHDRAWN": "WITHDRAWN",
            "EXPLAINED": "CLOSED_WITH_EXCEPTION",
            "UNRESOLVED": "UNRESOLVED",
        }[row.state]
    from datetime import date, datetime, timezone

    age = max(0, (datetime.now(timezone.utc) - row.created_at).days)
    return dict(
        id=str(row.id),
        profile_id=str(p.id),
        counterparty=row.counterparty,
        reference=row.reference,
        work_item_id=str(row.work_item_id),
        year=row.year,
        revision=row.revision,
        review_state=row.state,
        period=d.tax_period(date(row.year, 4, 1))[1],
        age_days=age,
        review=reviewed,
        statement_work_item_id=(
            str(snapshot.source_work_item_id) if snapshot and snapshot.source_work_item_id else None
        ),
        statement_reader=_reader_of(snapshot),
        created_at=row.created_at.isoformat(),
        snapshot_id=str(snapshot.id) if snapshot else None,
        as_of=snapshot.created_at.isoformat() if snapshot else None,
        **value,
    )


def check_entity(p, pan):
    if (
        identity(pan, "PAN", encryption.decrypt_secret(p.identity_salt_ciphertext))
        != p.pan_fingerprint
    ):
        raise HTTPException(422, "Entity does not match the source confirmation.")


def import_reviewed(db, workspace, p, source, year, rows, pan, confirmed):
    """Typed rows read from a document the person points at (the original path)."""
    if not confirmed:
        raise HTTPException(
            422, "Confirm the entity, year and transcription against the source."
        )
    check_entity(p, pan)
    source_document = document(db, workspace, source)
    lock_capacity(db, workspace)
    salt = encryption.decrypt_secret(p.identity_salt_ciphertext)
    # Stable content hash, excluding file names and upload time. Identical input is idempotent.
    normalized = [
        dict(
            deductor_key=identity(r.tan, "TAN", salt),
            amount_micros=d.money(r.amount),
            reference=r.reference,
        )
        for r in rows
    ]
    return store_snapshot(
        db,
        workspace,
        p,
        year,
        normalized,
        source_work_item_id=source,
        source_version=versions.one(db, workspace.id, source_document.id).statement,
        parser_version="human-transcription-v1",
    )


def import_parsed(db, workspace, p, year, parsed, pan, confirmed, expected_sha256):
    """Rows read from an uploaded statement file by a reader (template, Form 26AS / 168 text, AIS CSV): the same preview,
    confirm and import path as typed rows. The reviewer confirmed the file's fingerprint, the entity and the year."""
    from app.services.trinetra import readers

    if not confirmed or parsed.sha256 != expected_sha256:
        raise HTTPException(
            422,
            "Confirm the entity, year and the file shown in the preview. This file is not the one that was previewed.",
        )
    check_entity(p, pan)
    entity_pan = encryption.decrypt_secret(p.pan_ciphertext)
    if parsed.file_pan and not hmac.compare_digest(
        parsed.file_pan.encode("ascii"), entity_pan.encode("ascii")
    ):
        raise HTTPException(
            422,
            {
                "code": "TRINETRA_FILE_PAN_DIFFERS",
                "message": "The PAN printed in the file is not this entity's PAN. Nothing was imported.",
            },
        )
    if parsed.label is not None and parsed.label.year != year:
        raise HTTPException(
            422,
            {
                "code": "TRINETRA_FILE_YEAR_DIFFERS",
                "message": f"The file states {parsed.label.text}, which is not the year you chose "
                f"({d.tax_period(date(year, 4, 1))[1]}). Years are never mixed or converted; choose the file's own year.",
            },
        )
    lock_capacity(db, workspace)
    salt = encryption.decrypt_secret(p.identity_salt_ciphertext)
    normalized = [
        dict(
            deductor_key=identity(r.tan, "TAN", salt),
            amount_micros=r.amount_micros,
            reference=r.reference or f"row {r.line_no}",
            section=r.section,
            on=r.on.isoformat() if r.on else None,
            status=r.status,
            booked_on=r.booked_on.isoformat() if r.booked_on else None,
            remarks=r.remarks,
            paid_micros=r.paid_micros,
            deducted_micros=r.deducted_micros,
            line_no=r.line_no,
        )
        for r in parsed.rows
    ]
    reader = readers.get(parsed.reader)
    meta = dict(
        reader=parsed.reader,
        reader_label=reader.label if reader else parsed.reader,
        official=bool(reader and reader.official),
        verified=bool(reader and reader.verified),
        label=parsed.label.text if parsed.label else None,
        label_kind=parsed.label.kind if parsed.label else None,
        checks=[dict(name=c.name, ok=c.ok, detail=c.detail) for c in parsed.checks],
        ignored=parsed.ignored,
        rows_read=len(parsed.rows),
    )
    return store_snapshot(
        db,
        workspace,
        p,
        year,
        normalized,
        source_work_item_id=None,
        source_version=versions.file_statement_version(parsed.sha256),
        parser_version=parsed.parser_version,
        source_sha256=parsed.sha256,
        source_meta=meta,
    )


def store_snapshot(
    db,
    workspace,
    p,
    year,
    normalized,
    *,
    source_work_item_id,
    source_version,
    parser_version,
    source_sha256=None,
    source_meta=None,
):
    keys = {(r["deductor_key"], r["amount_micros"], r["reference"]) for r in normalized}
    if len(keys) != len(normalized):
        raise HTTPException(
            422, "Duplicate posting rows require distinct source-row references."
        )
    fp = hashlib.sha256(
        json.dumps(
            [str(source_work_item_id or source_sha256), source_version, year, normalized],
            sort_keys=True,
        ).encode()
    ).hexdigest()
    old = (
        db.query(Statement)
        .filter_by(profile_id=p.id, year=year, fingerprint=fp)
        .first()
    )
    if old:
        return old
    previous = (
        db.query(Statement).filter_by(profile_id=p.id, year=year, active=True).first()
    )
    snapshots = db.query(Statement).filter_by(organization_id=workspace.organization_id)
    working = capacity(db, workspace, "snapshots")
    # A new import supersedes the active snapshot of its profile and year: only a NEW profile-year adds an active one.
    if previous is None and snapshots.filter_by(active=True).count() >= working:
        raise HTTPException(
            409,
            f"Your plan allows {working} active statement snapshots (one for each legal entity and tax year). "
            + raise_hint(db, workspace),
        )
    if snapshots.count() >= working * RETENTION_MULTIPLIER["snapshots"]:
        raise HTTPException(
            409,
            "The retention ceiling for TRINETRA statement snapshots is reached. Superseded snapshots age out with "
            "their documents under your retention policy. " + raise_hint(db, workspace),
        )
    from app.services.trinetra.outcomes import baseline

    comparison = {}
    if previous:
        cases = (
            db.query(CreditRow)
            .filter_by(profile_id=p.id, workspace_id=workspace.id, year=year)
            .limit(5001)
            .all()
        )
        if len(cases) > 5000:
            raise HTTPException(409, "The comparison exceeds the supported case limit.")
        comparison = baseline(previous, summary(db, workspace)["items"], cases)
    if previous:
        previous.active = False
        db.flush()
    row = Statement(
        organization_id=workspace.organization_id,
        workspace_id=workspace.id,
        profile_id=p.id,
        source_work_item_id=source_work_item_id,
        source_sha256=source_sha256,
        source_meta=source_meta or {},
        source_version=source_version,
        year=year,
        fingerprint=fp,
        parser_version=parser_version,
        rows=normalized,
        active=True,
        revision=(previous.revision + 1 if previous else 1),
        comparison=comparison,
        evidence_work_item_ids=(
            (
                ([str(previous.source_work_item_id)] if previous.source_work_item_id else [])
                + [str(c.work_item_id) for c in cases]
            )
            if previous
            else []
        ),
    )
    db.add(row)
    db.flush()
    return row


def decide(
    db,
    workspace,
    row,
    p,
    user_id,
    revision,
    action,
    reason,
    requested,
    review_minutes=0,
    extra=None,
    approval=None,
):
    # Closing out, withdrawing and annotating never wait for a changed invoice to be reconfirmed.
    if action not in ("WITHDRAWN", "UNRESOLVED", "ANNOTATE") and (
        invoice_version(db, workspace, row.work_item_id) != row.source_version
    ):
        raise HTTPException(
            409,
            "The source document changed. Reconfirm the expectation before deciding.",
        )
    if revision != row.revision:
        raise HTTPException(409, "This case changed. Reload before deciding.")
    if approval is None and action in approvals.CLOSING:
        policy = approvals.required(db, workspace, row, action)
        if policy is not None:
            raise approvals.ApprovalNeeded(policy)       # Enterprise: a second person approves this closure
    snapshot = current(db, p, row.year)
    existing = allocations(db, p, row.year)
    retained = [a for a in existing if a.credit != str(row.id)]
    chosen = []
    if action == "ALLOCATE":
        if not snapshot:
            raise HTTPException(409, "Import a statement first.")
        if not requested:
            raise HTTPException(422, "Choose at least one supported posting amount.")
        ps = {
            x.id: x
            for x in postings(
                snapshot, workspace, p, active_pairings(db, [snapshot.id]).get(snapshot.id, ())
            )
        }
        for item in requested:
            if item.snapshot_id != snapshot.id or item.line_id not in ps:
                raise HTTPException(
                    409, "Statement changed; review the active version."
                )
            booking = (snapshot.rows[int(item.line_id)].get("status") or "").upper()
            if booking not in ("", "F"):
                raise HTTPException(
                    422,
                    f"This statement row's booking status is '{booking}', not final ('F'), exactly as the statement prints "
                    "it. Wait for the final booking in a later statement, or record an explanation instead.",
                )
            try:
                retained = d.allocate(
                    credit(row, workspace),
                    ps[item.line_id],
                    d.money(item.amount),
                    retained,
                )
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
        chosen = [asdict(a) for a in retained if a.credit == str(row.id)]
    elif requested:
        raise HTTPException(422, "Only allocation decisions may carry allocations.")
    elif action == "WITHDRAWN":
        chosen = []
    else:
        chosen = [asdict(a) for a in existing if a.credit == str(row.id)]
    if action in ("REJECT_MATCH", "ANNOTATE"):
        extra = extra or {}
        review = dict(row.review or {})
        now = datetime.now(timezone.utc).isoformat()
        if action == "REJECT_MATCH":
            if snapshot is None or str(extra.get("snapshot_id")) != str(snapshot.id):
                raise HTTPException(409, "Statement changed; review the active version.")
            line = extra.get("line_id")
            if line is None or not str(line).isdigit() or int(line) >= len(snapshot.rows):
                raise HTTPException(422, "Choose the statement row to reject.")
            rejected = list(review.get("rejected_candidates", []))
            if not any(r["snapshot_id"] == str(snapshot.id) and r["line_id"] == str(line) for r in rejected):
                rejected.append({"snapshot_id": str(snapshot.id), "line_id": str(line), "by": str(user_id), "at": now,
                                 "reason": reason[:300]})
            review["rejected_candidates"] = rejected[-200:]
        else:
            note = (extra.get("note") or "").strip()
            if not note:
                raise HTTPException(422, "Write the annotation.")
            review["annotations"] = (list(review.get("annotations", [])) + [
                {"text": note[:500], "by": str(user_id), "at": now, "reason": reason[:300],
                 "line_id": extra.get("line_id"), "snapshot_id": str(snapshot.id) if snapshot else None}])[-200:]
        row.review = review
    if action == "CA_REVIEWED":
        result = view(db, workspace, row)
        if result["status"] not in ("POSTED", "LATE_POSTING", "VERIFIED_CORRECTED"):
            raise HTTPException(
                409, "A fully allocated active posting is required before CA review."
            )
        from app.api.capability_gate import has_capability

        if has_capability(
            db,
            organization_id=workspace.organization_id,
            capability_key="capability.trinetra_all_workspaces",
        ):
            previous = (
                db.query(Decision)
                .filter_by(credit_id=row.id)
                .order_by(Decision.revision.desc())
                .first()
            )
            allocator = (
                db.query(Decision)
                .filter_by(credit_id=row.id, action="ALLOCATE")
                .order_by(Decision.revision.desc())
                .first()
            )
            if any(
                event and event.actor_id == user_id for event in (previous, allocator)
            ):
                raise HTTPException(
                    409,
                    "Enterprise accountant review requires a different reviewer from the allocator and most recent decision author.",
                )
    if action == "CA_REVIEWED":
        record_outcome(db, workspace, row, p, user_id, snapshot, result)
    row.revision += 1
    if action not in ("REJECT_MATCH", "ANNOTATE"):      # these keep the case where it is
        row.state = "OPEN" if action in ("ALLOCATE", "REOPEN") else action
    db.add(
        Decision(
            organization_id=workspace.organization_id,
            workspace_id=workspace.id,
            credit_id=row.id,
            actor_id=user_id,
            revision=row.revision,
            action=action,
            reason=reason,
            allocations=chosen,
            review_minutes=review_minutes,
            evidence_work_item_ids=decision_sources(db, row, p),
        )
    )
    db.flush()


def record_outcome(db, workspace, row, p, user_id, snapshot, result):
    """The closure ledger: one row each time a closure is confirmed, deduplicated by (case, the snapshot that confirmed it), so
    monthly and yearly figures add up without counting anything twice and survive later imports. Only a case that HAD a gap in
    an earlier import counts as "now visible in your statement"; it is never cash recovered."""
    if snapshot is None:
        return None
    if db.query(Outcome.id).filter_by(credit_id=row.id, snapshot_id=snapshot.id).first():
        return None
    before = ((snapshot.comparison or {}).get("cases") or {}).get(str(row.id))
    db.add(
        Outcome(
            organization_id=workspace.organization_id,
            workspace_id=workspace.id,
            credit_id=row.id,
            snapshot_id=snapshot.id,
            year=row.year,
            amount_micros=int(result["posted_micros"]),
            was_gap=bool(before and int(before.get("gap_micros") or 0) > 0),
            confirmed_by=user_id,
        )
    )
    db.flush()


def pair_reversal(db, workspace, p, user_id, snapshot_id, positive_line, negative_line, reason):
    """A person pairs a reversal (a negative row) with the row it reverses. Netting happens only through this. Refused unless
    both rows are the same deductor's, one positive and one negative, the reversal does not exceed the row, and the net
    still covers what is already allocated: amounts are conserved, a statement amount is never spent twice."""
    lock_capacity(db, workspace)
    snapshot = db.query(Statement).filter_by(id=snapshot_id, profile_id=p.id, workspace_id=workspace.id).first()
    if snapshot is None or not snapshot.active:
        raise HTTPException(409, "Pair rows of the active statement only.")
    rows = snapshot.rows
    if not (0 <= positive_line < len(rows) and 0 <= negative_line < len(rows)):
        raise HTTPException(422, "That statement row does not exist.")
    plus, minus = rows[positive_line], rows[negative_line]
    if plus["deductor_key"] != minus["deductor_key"]:
        raise HTTPException(422, "A reversal is paired with a row of the same deductor only.")
    if plus["amount_micros"] <= 0 or minus["amount_micros"] >= 0:
        raise HTTPException(422, "Pair one positive row with one negative row (the reversal).")
    existing = active_pairings(db, [snapshot.id]).get(snapshot.id, [])
    if any(x.negative_line == negative_line for x in existing):
        raise HTTPException(409, "This reversal is already paired.")
    net = net_amounts(rows, existing)
    if net[positive_line] + minus["amount_micros"] < 0:
        raise HTTPException(422, "The reversal is larger than the row it is paired with.")
    allocated = sum(
        a.amount
        for a in allocations(db, p, snapshot.year)
        if a.posting == str(positive_line) and a.snapshot == str(snapshot.id)
    )
    if net[positive_line] + minus["amount_micros"] < allocated:
        raise HTTPException(
            409,
            "That row is already allocated to cases for more than it would be worth after the reversal. Reallocate those "
            "cases first.",
        )
    row = Pairing(
        organization_id=workspace.organization_id, workspace_id=workspace.id, profile_id=p.id, statement_id=snapshot.id,
        positive_line=positive_line, negative_line=negative_line, reason=reason, created_by=user_id,
    )
    db.add(row)
    db.flush()
    return row


def unpair_reversal(db, workspace, p, user_id, pairing_id, reason):
    row = db.query(Pairing).filter_by(id=pairing_id, profile_id=p.id, workspace_id=workspace.id, active=True).first()
    if row is None:
        raise HTTPException(404, "Pairing not found.")
    snapshot = db.get(Statement, row.statement_id)
    others = [x for x in active_pairings(db, [snapshot.id]).get(snapshot.id, []) if x.id != row.id]
    # Un-netting only ever raises a row, but a row that had absorbed this reversal must still cover its allocations.
    net = net_amounts(snapshot.rows, others)
    for line in {row.positive_line}:
        used = sum(
            a.amount
            for a in allocations(db, p, snapshot.year)
            if a.posting == str(line) and a.snapshot == str(snapshot.id)
        )
        if used > net[line]:
            raise HTTPException(409, "Cases are allocated against this row; reallocate them first.")
    row.active, row.withdrawn_reason = False, reason
    db.flush()
    return row


def unpaired_reversals(snapshot, pairings):
    """Negative rows of the active statement nobody paired: exceptions, never netted on their own."""
    paired = {x.negative_line for x in pairings}
    return [i for i, r in enumerate(snapshot.rows) if r["amount_micros"] < 0 and i not in paired] if snapshot else []


def reconfirm(db, workspace, row, p, user_id, revision, amount, reason, seller_name_confirmed=False):
    if revision != row.revision:
        raise HTTPException(409, "This case changed. Reload before confirming.")
    source, fact, seller = receivable(
        db, workspace, p, row.work_item_id, seller_name_confirmed=seller_name_confirmed
    )
    if not (row.review or {}).get("triggering_event"):
        invoice_period(fact, row.year)
    value = d.money(amount)
    if value <= 0 or value > fact.total_micros:
        raise HTTPException(
            422,
            "Expected withholding must be positive and cannot exceed the sourced gross invoice. Withdraw the expectation when no withholding remains.",
        )
    previous = row.expected_micros
    row.expected_micros = value
    row.source_version = invoice_version(db, workspace, source.id)
    row.state = "OPEN"
    row.revision += 1
    db.add(
        Decision(
            organization_id=workspace.organization_id,
            workspace_id=workspace.id,
            credit_id=row.id,
            actor_id=user_id,
            revision=row.revision,
            action="EXPECTATION_RECONFIRMED",
            evidence_work_item_ids=decision_sources(db, row, p),
            reason=f"Previous expected micros: {previous}. Reconfirmed micros: {value}. "
            + reason
            + SELLER_NAME_NOTE.get(seller.outcome, ""),
            allocations=[],
        )
    )
    db.flush()


def views(db, workspace, rows):
    """The case views for these rows, read in batches (profiles, statements, documents, decisions): the number of
    queries does not grow with the number of cases. Returns (items, active snapshots by (profile, year))."""
    profile_ids = {r.profile_id for r in rows}
    profiles = {
        p.id: p
        for p in db.query(Profile).filter(
            Profile.workspace_id == workspace.id, Profile.id.in_(profile_ids)
        )
    }
    snapshots = (
        list(
            db.query(Statement).filter(
                Statement.workspace_id == workspace.id,
                Statement.active.is_(True),
                Statement.profile_id.in_(profile_ids),
            )
        )
        if profile_ids
        else []
    )
    ids = {row.work_item_id for row in rows} | {
        snap.source_work_item_id for snap in snapshots if snap.source_work_item_id
    }
    for row in rows:
        ids.update(evidence_ids(row.review))
    facts = versions.load(db, workspace.id, ids)
    roles = {
        x.work_item_id: x
        for x in db.query(DocumentRole).filter(
            DocumentRole.workspace_id == workspace.id,
            DocumentRole.work_item_id.in_(ids),
        )
    }
    active = {
        (snap.profile_id, snap.year): snap
        for snap in snapshots
        if snap.source_work_item_id is None
        or (
            snap.source_work_item_id in facts
            and facts[snap.source_work_item_id].statement == snap.source_version
        )
    }
    latest = (
        db.query(Decision, CreditRow.profile_id, CreditRow.year)
        .join(
            CreditRow,
            (Decision.credit_id == CreditRow.id)
            & (Decision.revision == CreditRow.revision),
        )
        .filter(
            CreditRow.workspace_id == workspace.id,
            CreditRow.profile_id.in_(profile_ids),
        )
        .all()
        if profile_ids
        else []
    )
    by_group = {}
    for decision, profile_id, year in latest:
        by_group.setdefault((profile_id, year), []).extend(
            d.Allocation(**a) for a in decision.allocations
        )
    pairings = active_pairings(db, [snap.id for snap in active.values()])
    bundles = {}
    for row in rows:
        key = (row.profile_id, row.year)
        if key not in bundles:
            p = profiles[row.profile_id]
            snapshot = active.get(key)
            bundles[key] = (
                p,
                snapshot,
                _PostingIndex(postings(snapshot, workspace, p, pairings.get(snapshot.id, ()) if snapshot else ())),
                _AllocationIndex(by_group.get(key, [])),
            )
    out = []
    for r in rows:
        p, snapshot, posting_index, allocation_index = bundles[(r.profile_id, r.year)]
        narrowed = posting_index.for_case(r.deductor_key, r.reference)
        out.append(
            view(
                db,
                workspace,
                r,
                (p, snapshot, narrowed, allocation_index.for_case(str(r.id), narrowed)),
                facts,
                roles,
            )
        )
    return out, active


class _PostingIndex:
    """The statement's postings by deductor and by reference, so a case compares itself with the rows that can matter
    (its own deductor's, and any other deductor's row that prints the same reference) and not with every row of the
    statement: the cost of a case no longer grows with the size of the statement."""

    def __init__(self, rows):
        self.by_deductor = {}
        self.by_reference = {}
        for row in rows:
            self.by_deductor.setdefault(row.deductor, []).append(row)
            if row.reference:
                self.by_reference.setdefault(row.reference.casefold().strip(), []).append(row)

    def for_case(self, deductor, reference):
        found = list(self.by_deductor.get(deductor, []))
        if reference:
            found += [
                r for r in self.by_reference.get(reference.casefold().strip(), []) if r.deductor != deductor
            ]
        return found


class _AllocationIndex:
    """The reviewed allocations by case and by statement row: a case needs its own and those on the rows it may use."""

    def __init__(self, allocations):
        self.by_credit = {}
        self.by_posting = {}
        for a in allocations:
            self.by_credit.setdefault(a.credit, []).append(a)
            self.by_posting.setdefault((a.snapshot, a.posting), []).append(a)

    def for_case(self, credit_id, postings):
        found = {id(a): a for a in self.by_credit.get(credit_id, [])}
        for posting in postings:
            for a in self.by_posting.get((posting.snapshot, posting.id), []):
                found[id(a)] = a
        return list(found.values())


def create_case(
    db,
    workspace,
    p,
    user_id,
    *,
    work_item_id,
    year,
    counterparty,
    reference,
    tan,
    amount,
    source_confirmation,
    seller_name_confirmed=False,
    origin="TYPED",
    section_text=None,
    evidence=None,
    deductor_key=None,
    triggering_event=None,
):
    """Confirm one expected withholding on an invoice. Every way in (typed, an accepted suggestion) ends here, so every case
    has the same checks: the invoice is a classified INR invoice of this entity, the period contains its date, the amount is
    positive and within the gross, and the plan has room. `origin` records where the expectation came from; it is a person's
    confirmation either way (`source_confirmation` is their reason)."""
    source, fact, seller = receivable(
        db, workspace, p, work_item_id, seller_name_confirmed=seller_name_confirmed
    )
    event = None
    if triggering_event:
        event = check_triggering_event(db, workspace, fact, year, triggering_event)
    else:
        invoice_period(fact, year)
    lock_capacity(db, workspace)
    old = (
        db.query(CreditRow)
        .filter_by(profile_id=p.id, work_item_id=work_item_id, year=year)
        .first()
    )
    deductor = deductor_key or identity(
        tan, "TAN", encryption.decrypt_secret(p.identity_salt_ciphertext)
    )
    value = d.money(amount) if isinstance(amount, str) else int(amount)
    if value <= 0 or value > fact.total_micros:
        raise HTTPException(
            422,
            "Expected withholding must be positive and cannot exceed the sourced gross invoice.",
        )
    if old:
        if (old.expected_micros, old.deductor_key, old.reference, old.counterparty) != (
            value,
            deductor,
            reference,
            counterparty,
        ):
            raise HTTPException(
                409,
                "This source already has an expectation; use the versioned reconfirmation workflow.",
            )
        return old
    check_case_capacity(db, workspace)
    review = {"origin": origin}
    if section_text:
        review["section_text"] = section_text[:100]
    if event:
        # An advance or earlier triggering event: placed in its own period by a person, with a reason and evidence. Never inferred.
        review["triggering_event"] = event
        review["evidence"] = [
            {
                "work_item_id": event["evidence_work_item_id"],
                "kind": "TRIGGERING_EVENT",
                "source_version": versions.one(db, workspace.id, uuid.UUID(event["evidence_work_item_id"])).evidence,
                "amount_micros": None,
                "added_at": datetime.now(timezone.utc).isoformat(),
            }
        ]
    if evidence:
        review["origin_evidence"] = evidence
        if evidence.get("accounting_record") and evidence.get("withheld_micros"):
            # A record read from the accounting system (Zoho Books): evidence of the booked withholding, not a document.
            review["evidence"] = review.get("evidence", []) + [
                {
                    "work_item_id": None,
                    "kind": "ACCOUNTING_RECORD",
                    "source": "ZOHO",
                    "external_ref": ",".join(p_["id"] for p_ in (evidence.get("zoho") or {}).get("payments", []))[:200],
                    "source_version": hashlib.sha256(json.dumps(evidence, sort_keys=True, default=str).encode()).hexdigest()[:48],
                    "amount_micros": int(evidence["withheld_micros"]),
                }
            ]
    r = CreditRow(
        organization_id=workspace.organization_id,
        workspace_id=workspace.id,
        profile_id=p.id,
        work_item_id=work_item_id,
        year=year,
        counterparty=counterparty,
        reference=reference,
        source_version=invoice_version(db, workspace, source.id),
        deductor_key=deductor,
        expected_micros=value,
        review=review,
    )
    db.add(r)
    db.flush()
    db.add(
        Decision(
            organization_id=workspace.organization_id,
            workspace_id=workspace.id,
            credit_id=r.id,
            actor_id=user_id,
            revision=1,
            action="EXPECTATION_CONFIRMED",
            reason=source_confirmation + SELLER_NAME_NOTE.get(seller.outcome, ""),
            allocations=[],
        )
    )
    db.flush()
    return r


def totals_of(items):
    """The headline figures of these case views: one rule for a workspace, a legal entity and an organization."""
    return dict(
        total=len(items),
        unresolved=sum(r["status"] not in RESOLVED_STATUSES for r in items),
        expected_micros=sum(
            r["expected_micros"] or 0 for r in items if r["review_state"] != "WITHDRAWN"
        ),
        posted_micros=sum(
            r["posted_micros"] for r in items if r["review_state"] != "WITHDRAWN"
        ),
        gap_micros=sum(
            r["gap_micros"] or 0
            for r in items
            if r["review_state"] not in ("WITHDRAWN", "EXPLAINED", "UNRESOLVED")
        ),
    )


def entities(db, organization_id, workspace_ids, profile_items):
    """The legal entities behind these workspaces, each counted once. A profile made before the one-entity rule can hold the
    same PAN as another: those are grouped by the PAN (compared in memory, never stored or shown). `profile_items` maps a
    profile id (as text) to its case views."""
    profiles = (
        db.query(Profile)
        .filter(Profile.organization_id == organization_id, Profile.workspace_id.in_(workspace_ids))
        .order_by(Profile.id)
        .all()
        if workspace_ids
        else []
    )
    groups = {}
    for p in profiles:
        key = p.org_pan_fingerprint or "legacy:" + hashlib.sha256(
            encryption.decrypt_secret(p.pan_ciphertext).encode("ascii")
        ).hexdigest()
        groups.setdefault(key, []).append(p)
    out = []
    for members in groups.values():
        items = [i for p in members for i in profile_items.get(str(p.id), [])]
        out.append(
            dict(
                entity_id=str(members[0].id),
                name=members[0].name,
                workspace_ids=sorted({str(p.workspace_id) for p in members}),
                **totals_of(items),
            )
        )
    return sorted(out, key=lambda e: (e["name"].casefold(), e["entity_id"]))


def entity_totals(entities_):
    return dict(
        total=sum(e["total"] for e in entities_),
        unresolved=sum(e["unresolved"] for e in entities_),
        expected_micros=sum(e["expected_micros"] for e in entities_),
        posted_micros=sum(e["posted_micros"] for e in entities_),
        gap_micros=sum(e["gap_micros"] for e in entities_),
    )


def summary(db, workspace):
    rows = (
        working_set(db.query(CreditRow).filter_by(workspace_id=workspace.id))
        .order_by(CreditRow.created_at, CreditRow.id)
        .limit(WORKING_SET_LIMIT + 1)
        .all()
    )
    if len(rows) > WORKING_SET_LIMIT:
        raise HTTPException(
            409,
            "Workspace exceeds the supported report size; archive evidence under the retention policy.",
        )
    items, active = views(db, workspace, rows)
    from app.services.trinetra.outcomes import measure

    return dict(
        is_sample=False,
        items=items,
        outcomes=measure(db, workspace, items, rows, list(active.values())),
        as_of=max((r["as_of"] for r in items if r["as_of"]), default=None),
        note="Human-confirmed transcription; not a verified official-format import. Unknown gaps excluded.",
        **totals_of(items),
    )


def bank_evidence(db, workspace, row, context):
    """Read through Helm's role, book and restricted-workspace checks; never settle."""
    from app.models.helm import HelmBankLine
    from app.services.helm import service, bank
    from app.services.helm.errors import HelmError

    try:
        who = service.viewer(
            db,
            organization_id=workspace.organization_id,
            user_id=context.user_id,
            role=context.organization_role,
        )
        evidence = []
        candidates = (
            db.query(HelmBankLine)
            .filter_by(
                organization_id=workspace.organization_id,
                workspace_id=workspace.id,
                work_item_id=row.work_item_id,
                status="MATCHED",
            )
            .limit(101)
            .all()
        )
        if len(candidates) > 100:
            return []  # Unknown is safer than a silently truncated cash total.
        if any(c.currency != "INR" for c in candidates):
            return []  # A receipt in another currency would be silently left out of the total: unknown instead.
        for candidate in candidates:
            line, _ = bank._line(db, who, candidate.id)
            bank._require_line(who, line)
            evidence.append(
                {
                    "id": str(line.id),
                    "amount_micros": line.amount_micros,
                    "on": line.on_date.isoformat(),
                }
            )
        return evidence
    except HelmError:
        return []
