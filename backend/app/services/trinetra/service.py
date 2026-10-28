"""Transactional reviewed evidence adapter. Locks serialize profile revisions/allocations."""

import hashlib
import hmac
import json
import re
import uuid
import secrets
from dataclasses import asdict
from fastapi import HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import select
from app.core import encryption
from app.models.organization import Organization
from app.models.work_item import WorkItem
from app.models.document_role import DocumentRole
from app.models.trinetra import (
    TrinetraProfile as Profile,
    TrinetraStatement as Statement,
    TrinetraCredit as CreditRow,
    TrinetraDecision as Decision,
)
from app.services.trinetra import domain as d
from app.services.trinetra import versions


#: Recorded in the case history when the seller was matched by name alone and a reviewer confirmed it.
SELLER_NAME_NOTE = {
    "NAME_ONLY": " Seller matched by name only (no PAN or valid GSTIN printed); confirmed by the reviewer."
}


def capacity(db, workspace, kind):
    """Pinned published plan, with a finite platform ceiling even for legacy tiers."""
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


def create_profile(db, workspace, name, pan):
    lock_capacity(db, workspace)
    identity(pan, "PAN", "validation-only")
    for old in db.query(Profile).filter_by(workspace_id=workspace.id).all():
        if hmac.compare_digest(encryption.decrypt_secret(old.pan_ciphertext), pan):
            return old
    salt = secrets.token_hex(32)
    key = identity(pan, "PAN", salt)
    if db.query(Profile).filter_by(
        organization_id=workspace.organization_id
    ).count() >= capacity(db, workspace, "profiles"):
        raise HTTPException(
            409, "Legal-entity profile limit reached for this plan version."
        )
    row = Profile(
        organization_id=workspace.organization_id,
        workspace_id=workspace.id,
        name=name,
        identity_salt_ciphertext=encryption.encrypt_secret(salt),
        pan_ciphertext=encryption.encrypt_secret(pan),
        pan_fingerprint=key,
        pan_masked="******" + pan[-4:],
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
    )


def current(db, p, year):
    snapshot = (
        db.query(Statement)
        .filter_by(profile_id=p.id, workspace_id=p.workspace_id, year=year, active=True)
        .first()
    )
    if snapshot:
        facts = versions.one(db, p.workspace_id, snapshot.source_work_item_id)
        if facts is None or facts.statement != snapshot.source_version:
            return None
    return snapshot


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


def decision_sources(db, row, p):
    snapshot = current(db, p, row.year)
    return sorted(
        {
            str(row.work_item_id),
            *(row.evidence_work_item_ids or []),
            *([str(snapshot.source_work_item_id)] if snapshot else []),
        }
    )


def postings(snapshot, workspace, p):
    if not snapshot:
        return []
    return [
        d.Posting(
            str(i),
            scope(workspace, p, snapshot.year),
            r["deductor_key"],
            r["amount_micros"],
            str(snapshot.id),
            r["reference"],
        )
        for i, r in enumerate(snapshot.rows)
    ]


def view(db, workspace, row, bundle=None, facts=None, roles=None):
    if bundle is None:
        p = db.get(Profile, row.profile_id)
        snapshot = current(db, p, row.year)
        bundle = (
            p,
            snapshot,
            postings(snapshot, workspace, p),
            allocations(db, p, row.year),
        )
    p, snapshot, posting_rows, allocated = bundle
    if facts is None:
        facts = versions.load(
            db,
            workspace.id,
            [row.work_item_id]
            + [uuid.UUID(e["work_item_id"]) for e in (row.review or {}).get("evidence", [])],
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
        evidence = facts.get(uuid.UUID(item["work_item_id"]))
        reviewed["evidence"].append(
            {
                **item,
                "current": bool(evidence and evidence.evidence == item["source_version"]),
            }
        )
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
    if row.state in ("WITHDRAWN", "EXPLAINED"):
        value["status"] = (
            "WITHDRAWN" if row.state == "WITHDRAWN" else "CLOSED_WITH_EXCEPTION"
        )
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
        statement_work_item_id=str(snapshot.source_work_item_id) if snapshot else None,
        created_at=row.created_at.isoformat(),
        snapshot_id=str(snapshot.id) if snapshot else None,
        as_of=snapshot.created_at.isoformat() if snapshot else None,
        **value,
    )


def import_reviewed(db, workspace, p, source, year, rows, pan, confirmed):
    if not confirmed:
        raise HTTPException(
            422, "Confirm the entity, year and transcription against the source."
        )
    if (
        identity(pan, "PAN", encryption.decrypt_secret(p.identity_salt_ciphertext))
        != p.pan_fingerprint
    ):
        raise HTTPException(422, "Entity does not match the source confirmation.")
    source_document = document(db, workspace, source)
    lock_capacity(db, workspace)
    # Stable content hash, excluding file names and upload time. Identical input is idempotent.
    normalized = [
        dict(
            deductor_key=identity(
                r.tan, "TAN", encryption.decrypt_secret(p.identity_salt_ciphertext)
            ),
            amount_micros=d.money(r.amount),
            reference=r.reference,
        )
        for r in rows
    ]
    keys = {(r["deductor_key"], r["amount_micros"], r["reference"]) for r in normalized}
    if len(keys) != len(normalized):
        raise HTTPException(
            422, "Duplicate posting rows require distinct source-row references."
        )
    source_version = versions.one(db, workspace.id, source_document.id).statement
    fp = hashlib.sha256(
        json.dumps(
            [str(source), source_version, year, normalized], sort_keys=True
        ).encode()
    ).hexdigest()
    old = (
        db.query(Statement)
        .filter_by(profile_id=p.id, year=year, fingerprint=fp)
        .first()
    )
    if old:
        return old
    if db.query(Statement).filter_by(
        organization_id=workspace.organization_id
    ).count() >= capacity(db, workspace, "snapshots"):
        raise HTTPException(409, "Snapshot limit reached; contact your administrator.")
    previous = (
        db.query(Statement).filter_by(profile_id=p.id, year=year, active=True).first()
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
        source_work_item_id=source,
        source_version=source_version,
        year=year,
        fingerprint=fp,
        parser_version="human-transcription-v1",
        rows=normalized,
        active=True,
        revision=(previous.revision + 1 if previous else 1),
        comparison=comparison,
        evidence_work_item_ids=(
            [str(previous.source_work_item_id)] + [str(c.work_item_id) for c in cases]
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
):
    if action != "WITHDRAWN" and (
        invoice_version(db, workspace, row.work_item_id) != row.source_version
    ):
        raise HTTPException(
            409,
            "The source document changed. Reconfirm the expectation before deciding.",
        )
    if revision != row.revision:
        raise HTTPException(409, "This case changed. Reload before deciding.")
    snapshot = current(db, p, row.year)
    existing = allocations(db, p, row.year)
    retained = [a for a in existing if a.credit != str(row.id)]
    chosen = []
    if action == "ALLOCATE":
        if not snapshot:
            raise HTTPException(409, "Import a statement first.")
        if not requested:
            raise HTTPException(422, "Choose at least one supported posting amount.")
        ps = {x.id: x for x in postings(snapshot, workspace, p)}
        for item in requested:
            if item.snapshot_id != snapshot.id or item.line_id not in ps:
                raise HTTPException(
                    409, "Statement changed; review the active version."
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
    if action == "CA_REVIEWED":
        result = view(db, workspace, row)
        if result["status"] != "POSTED":
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
    row.revision += 1
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


def reconfirm(db, workspace, row, p, user_id, revision, amount, reason, seller_name_confirmed=False):
    if revision != row.revision:
        raise HTTPException(409, "This case changed. Reload before confirming.")
    source, fact, seller = receivable(
        db, workspace, p, row.work_item_id, seller_name_confirmed=seller_name_confirmed
    )
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


def summary(db, workspace):
    rows = (
        db.query(CreditRow)
        .filter_by(workspace_id=workspace.id)
        .order_by(CreditRow.created_at, CreditRow.id)
        .limit(5001)
        .all()
    )
    if len(rows) > 5000:
        raise HTTPException(
            409,
            "Workspace exceeds the supported report size; archive evidence under the retention policy.",
        )
    profiles = {p.id: p for p in db.query(Profile).filter_by(workspace_id=workspace.id)}
    snapshots = list(
        db.query(Statement).filter_by(workspace_id=workspace.id, active=True)
    )
    ids = {row.work_item_id for row in rows} | {
        snap.source_work_item_id for snap in snapshots
    }
    ids.update(
        uuid.UUID(e["work_item_id"])
        for row in rows
        for e in (row.review or {}).get("evidence", [])
    )
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
        if snap.source_work_item_id in facts
        and facts[snap.source_work_item_id].statement == snap.source_version
    }
    latest = (
        db.query(Decision, CreditRow.profile_id, CreditRow.year)
        .join(
            CreditRow,
            (Decision.credit_id == CreditRow.id)
            & (Decision.revision == CreditRow.revision),
        )
        .filter(CreditRow.workspace_id == workspace.id)
        .all()
    )
    by_group = {}
    for decision, profile_id, year in latest:
        by_group.setdefault((profile_id, year), []).extend(
            d.Allocation(**a) for a in decision.allocations
        )
    bundles = {}
    for row in rows:
        key = (row.profile_id, row.year)
        if key not in bundles:
            p = profiles[row.profile_id]
            snapshot = active.get(key)
            bundles[key] = (
                p,
                snapshot,
                postings(snapshot, workspace, p),
                by_group.get(key, []),
            )
    items = [
        view(db, workspace, r, bundles[(r.profile_id, r.year)], facts, roles)
        for r in rows
    ]
    from app.services.trinetra.outcomes import measure

    return dict(
        is_sample=False,
        items=items,
        total=len(items),
        outcomes=measure(db, workspace, items, rows, list(active.values())),
        as_of=max((r["as_of"] for r in items if r["as_of"]), default=None),
        expected_micros=sum(
            r["expected_micros"] or 0 for r in items if r["review_state"] != "WITHDRAWN"
        ),
        posted_micros=sum(
            r["posted_micros"] for r in items if r["review_state"] != "WITHDRAWN"
        ),
        gap_micros=sum(
            r["gap_micros"] or 0
            for r in items
            if r["review_state"] not in ("WITHDRAWN", "EXPLAINED")
        ),
        unresolved=sum(
            r["status"] not in ("POSTED", "WITHDRAWN", "CLOSED_WITH_EXCEPTION")
            for r in items
        ),
        note="Human-confirmed transcription; not a verified official-format import. Unknown gaps excluded.",
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
                currency="INR",
            )
            .limit(101)
            .all()
        )
        if len(candidates) > 100:
            return []  # Unknown is safer than a silently truncated cash total.
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
