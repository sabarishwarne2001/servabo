"""The Promise ledger's database side: read the facts, write the diff.

`load_inputs` reads exactly what `ledger.build` needs, scoped by `workspace_id` in every query.
Writing is always a diff (insert new source keys, update changed hashes, delete source keys no longer
produced). There are two ways to produce what is compared with the stored rows:

  rebuild_workspace   recompute the whole workspace: the first build, the nightly one, a change of
                      "who we are", a new day (statuses depend on today)
  refresh_workspace   what a document change runs (Session B): re-project the documents marked dirty
                      (`app/models/helm_dirty.py`) and what depends on them (`ledger_incremental`),
                      at a cost that depends on the change, not on the size of the workspace

Both call `ledger.build`, so they cannot disagree about what a promise is; a property test compares
them row for row, and the nightly run (`verify_workspace`) checks the stored ledger against a full
recomputation and says so when they differ.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Collection, Optional

from sqlalchemy import delete, func, or_, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.document_role import DocumentRole
from app.models import helm_dirty
from app.models.helm import HelmBook, HelmLedgerDirty, HelmLedgerState, HelmPromise, HelmSettings, HelmSettlement
from app.models.obligations import Obligation
from app.models.procurement import ProcurementCase, ProcurementCaseLine, ProcurementTolerancePolicy
from app.models.verification import DocumentVerification
from app.models.work_item import WorkItem
from app.models.work_item_field_correction import WorkItemFieldCorrection
from app.models.workspace import Workspace
from app.services.helm import identity as ident
from app.services.helm import ledger
from app.services.helm import vocabulary as v

logger = logging.getLogger("app.services.helm.ledger_store")

TEXT_HEAD_CHARS = 4000


@dataclass(frozen=True)
class RebuildResult:
    workspace_id: uuid.UUID
    inserted: int
    updated: int
    deleted: int
    unchanged: int
    ms: int
    #: "full" (the whole workspace was recomputed), "incremental" (the changed documents and what depends
    #: on them) or "none" (nothing had changed).
    mode: str = "full"
    #: Documents re-projected by an incremental update.
    projected: int = 0

    @property
    def changed(self) -> bool:
        return bool(self.inserted or self.updated or self.deleted)

    def as_dict(self) -> dict[str, Any]:
        return {"workspace_id": str(self.workspace_id), "inserted": self.inserted, "updated": self.updated,
                "deleted": self.deleted, "unchanged": self.unchanged, "ms": self.ms, "mode": self.mode,
                "projected": self.projected}


def identities_for_workspace(db: Session, workspace_id: uuid.UUID) -> ident.Identities:
    """Our identities for one workspace's ledger: its own book's, else the all-workspaces book's."""
    workspace = db.get(Workspace, workspace_id)
    if workspace is None:
        return ident.Identities(frozenset(), frozenset())
    books = db.execute(
        select(HelmBook.id, HelmBook.kind).where(
            HelmBook.organization_id == workspace.organization_id,
            HelmBook.status == v.BOOK_ACTIVE,
            ((HelmBook.workspace_id == workspace_id) | (HelmBook.kind == v.BOOK_ORGANIZATION)),
        )
    ).all()
    ordered = sorted(books, key=lambda b: 0 if b.kind != v.BOOK_ORGANIZATION else 1)
    for book in ordered:
        settings = db.get(HelmSettings, book.id)
        if settings is not None and settings.identities:
            return ident.Identities.of(settings.identities)
    return ident.Identities(frozenset(), frozenset())


def _confidence(status: Optional[str], corrected: bool) -> str:
    if corrected or status == "REVIEWED":
        return v.CONFIDENCE_VERIFIED
    if status in ("AGREED", "AUTO_APPROVED"):
        return v.CONFIDENCE_CALIBRATED
    return v.CONFIDENCE_EXTRACTED


def document_facts(db: Session, workspace: Workspace, *, ids: Optional[Collection[uuid.UUID]] = None,
                   roles: Optional[Collection[str]] = None) -> list[ledger.DocumentFacts]:
    """The workspace's documents as the ledger reads them. With `ids` and/or `roles`, only those (a
    document that matches either); with neither, all of them."""
    workspace_id = workspace.id
    query = (
        select(
            WorkItem.id, WorkItem.original_filename, WorkItem.created_at, WorkItem.extracted_entities,
            func.substring(WorkItem.extracted_text, 1, TEXT_HEAD_CHARS).label("text_head"),
            DocumentRole.role, DocumentRole.vendor_key, DocumentRole.document_number, DocumentRole.document_date,
            DocumentRole.currency, DocumentRole.total_micros, DocumentRole.role_source,
        )
        .join(DocumentRole, DocumentRole.work_item_id == WorkItem.id)
        .where(WorkItem.workspace_id == workspace_id, DocumentRole.workspace_id == workspace_id)
        .where(WorkItem.pipeline_stage != "FAILED")
    )
    if ids is not None or roles is not None:
        wanted = []
        if ids:
            wanted.append(WorkItem.id.in_(list(ids)))
        if roles:
            wanted.append(DocumentRole.role.in_(list(roles)))
        if not wanted:
            return []
        query = query.where(or_(*wanted))
    rows = db.execute(query).all()
    loaded = [row.id for row in rows]
    verification_query = select(DocumentVerification.work_item_id, DocumentVerification.status).where(
        DocumentVerification.workspace_id == workspace_id)
    corrected_query = (select(WorkItemFieldCorrection.work_item_id)
                       .join(WorkItem, WorkItem.id == WorkItemFieldCorrection.work_item_id)
                       .where(WorkItem.workspace_id == workspace_id).distinct())
    if ids is not None or roles is not None:
        verification_query = verification_query.where(DocumentVerification.work_item_id.in_(loaded))
        corrected_query = corrected_query.where(WorkItemFieldCorrection.work_item_id.in_(loaded))
    verification = {wid: getattr(status, "value", status) for wid, status in db.execute(verification_query)}
    corrected = set(db.execute(corrected_query).scalars())

    from app.services.procurement_matching.line_extraction import po_reference_of

    documents: list[ledger.DocumentFacts] = []
    for row in rows:
        entities = row.extracted_entities if isinstance(row.extracted_entities, dict) else {}
        classification = entities.get("document_classification") or entities.get("document_type")
        documents.append(ledger.DocumentFacts(
            work_item_id=row.id, workspace_id=workspace_id, organization_id=workspace.organization_id,
            filename=row.original_filename, role=row.role,
            received_on=(row.created_at or datetime.now(timezone.utc)).date(), entities=entities,
            vendor_key=row.vendor_key, document_number=row.document_number, document_date=row.document_date,
            currency=row.currency, total_micros=row.total_micros, po_reference=po_reference_of(entities),
            confidence=_confidence(verification.get(row.id), row.id in corrected),
            text_head=row.text_head or "", classification=str(classification) if classification else None,
        ))
    return documents


def match_line_facts(db: Session, workspace_id: uuid.UUID, *,
                     documents: Optional[Collection[uuid.UUID]] = None) -> list[ledger.MatchLineFacts]:
    """The live procurement case lines; with `documents`, only those of a case that names one of them
    as its purchase order, invoice or receipt."""
    policy = db.execute(
        select(ProcurementTolerancePolicy.price_tolerance_bps)
        .where(ProcurementTolerancePolicy.workspace_id == workspace_id,
               ProcurementTolerancePolicy.status == "PUBLISHED")
        .order_by(ProcurementTolerancePolicy.version.desc()).limit(1)
    ).scalar_one_or_none()
    query = (
        select(ProcurementCaseLine, ProcurementCase)
        .join(ProcurementCase, ProcurementCase.id == ProcurementCaseLine.case_id)
        .where(ProcurementCase.workspace_id == workspace_id, ProcurementCaseLine.workspace_id == workspace_id,
               ProcurementCase.status != "SUPERSEDED")
    )
    if documents is not None:
        ids = list(documents)
        query = query.where(or_(ProcurementCase.po_work_item_id.in_(ids), ProcurementCase.invoice_work_item_id.in_(ids),
                                ProcurementCase.receipt_work_item_id.in_(ids)))
    return [
        ledger.MatchLineFacts(
            case_id=line.case_id, workspace_id=workspace_id, po_work_item_id=case.po_work_item_id,
            invoice_work_item_id=case.invoice_work_item_id, receipt_work_item_id=case.receipt_work_item_id,
            line_number=line.line_number, description=line.description, po_line_index=line.po_line_index,
            po_unit_price_micros=line.po_unit_price_micros, invoice_unit_price_micros=line.invoice_unit_price_micros,
            po_quantity=line.po_quantity, receipt_quantity=line.receipt_quantity,
            invoice_quantity=line.invoice_quantity, outcome=line.outcome, tolerance_bps=int(policy or 0),
            case_created_at=case.created_at,
        )
        for line, case in db.execute(query).all()
    ]


def obligation_facts(db: Session, workspace_id: uuid.UUID, *, ids: Optional[Collection[uuid.UUID]] = None,
                     work_items: Optional[Collection[uuid.UUID]] = None,
                     kind: Optional[str] = None) -> list[ledger.ObligationFacts]:
    """The live obligations; with any of `ids`, `work_items` (obligations of those documents) or `kind`,
    only those that match one of them."""
    query = select(Obligation).where(Obligation.workspace_id == workspace_id, Obligation.superseded_at.is_(None),
                                     Obligation.review != "REJECTED")
    if ids is not None or work_items is not None or kind is not None:
        wanted = []
        if ids:
            wanted.append(Obligation.id.in_(list(ids)))
        if work_items:
            wanted.append(Obligation.work_item_id.in_(list(work_items)))
        if kind:
            wanted.append(Obligation.kind == kind)
        if not wanted:
            return []
        query = query.where(or_(*wanted))
    out = []
    for ob in db.execute(query).scalars():
        detail = ob.detail if isinstance(ob.detail, dict) else {}
        out.append(ledger.ObligationFacts(
            obligation_id=ob.id, workspace_id=workspace_id, work_item_id=ob.work_item_id, kind=ob.kind,
            title=ob.title, state=ob.state, due_date=ob.due_date, done_on=ob.done_at.date() if ob.done_at else None,
            counterparty_name=ob.counterparty_name,
            amount_micros=int(ob.amount * 1_000_000) if ob.amount is not None else None, currency=ob.currency,
            quote=ob.quote,
            confidence=(v.CONFIDENCE_VERIFIED if ob.review == "CONFIRMED" else
                        v.CONFIDENCE_CALIBRATED if ob.review == "AUTO" else v.CONFIDENCE_EXTRACTED),
            decision=(detail.get("helm_decision") or {}).get("decision") if isinstance(detail.get("helm_decision"),
                                                                                         dict) else None,
        ))
    return out


def settlement_facts(db: Session, workspace_id: uuid.UUID, *,
                     ids: Optional[Collection[uuid.UUID]] = None) -> dict[uuid.UUID, ledger.SettlementFacts]:
    query = select(HelmSettlement).where(HelmSettlement.workspace_id == workspace_id)
    if ids is not None:
        query = query.where(HelmSettlement.work_item_id.in_(list(ids)))
    return {
        s.work_item_id: ledger.SettlementFacts(
            work_item_id=s.work_item_id, state=s.state, source=s.source, run_date=s.run_date, paid_on=s.paid_on,
            paid_amount_micros=s.paid_amount_micros, paid_reference=s.paid_reference, hold_reason=s.hold_reason,
            hold_code=(s.evidence or {}).get("reason") if s.state in (v.SETTLEMENT_HELD, v.SETTLEMENT_DISPUTED)
            else None, waived=tuple(sorted((s.evidence or {}).get("waived") or ())), version=s.version)
        for s in db.execute(query).scalars()
    }


def load_inputs(db: Session, *, workspace_id: uuid.UUID, as_of: date,
                identities: Optional[ident.Identities] = None) -> ledger.LedgerInputs:
    workspace = db.get(Workspace, workspace_id)
    if workspace is None:
        raise ValueError("workspace not found")
    identities = identities if identities is not None else identities_for_workspace(db, workspace_id)
    return ledger.LedgerInputs(
        as_of=as_of, documents=document_facts(db, workspace), match_lines=match_line_facts(db, workspace_id),
        obligations=obligation_facts(db, workspace_id), settlements=settlement_facts(db, workspace_id),
        identities=identities, date_format=workspace.date_format, workspace_currency=workspace.currency,
    )


# ---------------------------------------------------------------------------
# What changed, and what the ledger is up to date with
# ---------------------------------------------------------------------------


def lock_workspace(db: Session, workspace_id: uuid.UUID) -> None:
    """Serialise ledger jobs for one workspace (a transaction-scoped advisory lock): two never interleave
    their diffs. Held until the caller commits."""
    db.execute(select(func.pg_advisory_xact_lock(func.hashtextextended(f"helm-ledger:{workspace_id}", 0))))


def mark_dirty(db: Session, *, workspace_id: uuid.UUID, work_item_ids: Collection[uuid.UUID], reason: str) -> None:
    """Say these documents changed (for a caller that writes without the ORM, where the marks cannot be
    made for it). Part of the caller's transaction."""
    helm_dirty.mark(db.connection(), workspace_id, work_item_ids, reason)


def request_full(db: Session, *, workspace_id: uuid.UUID) -> None:
    """Say the next update of this workspace's ledger must be a full rebuild."""
    helm_dirty.request_full(db.connection(), workspace_id=workspace_id)


def _state(db: Session, workspace_id: uuid.UUID) -> Optional[dict[str, Any]]:
    row = db.execute(
        select(HelmLedgerState.as_of, HelmLedgerState.built_at, HelmLedgerState.full_requests,
               HelmLedgerState.full_served, HelmLedgerState.incremental_runs)
        .where(HelmLedgerState.workspace_id == workspace_id)
    ).one_or_none()
    return dict(row._mapping) if row is not None else None


@dataclass(frozen=True)
class Changed:
    """One marked document: how many changes were marked, and what its stored promises said before."""

    marks: int
    claims: tuple[int, ...] = ()
    numbers: tuple[str, ...] = ()


def _claim_dirty(db: Session, workspace_id: uuid.UUID) -> dict[uuid.UUID, Changed]:
    """The documents marked changed since the ledger was last written."""
    return {
        wid: Changed(marks, tuple(claims or ()), tuple(numbers or ()))
        for wid, marks, claims, numbers in db.execute(
            select(HelmLedgerDirty.work_item_id, HelmLedgerDirty.marks, HelmLedgerDirty.claims,
                   HelmLedgerDirty.numbers).where(HelmLedgerDirty.workspace_id == workspace_id)).all()
    }


def _release_dirty(db: Session, workspace_id: uuid.UUID, claimed: dict[uuid.UUID, Changed]) -> None:
    """Clear the marks this update saw. A document marked again since (a change committed while this ran)
    keeps its mark, and one a writer holds locked right now is left for the next update rather than waited
    for (waiting could deadlock with that writer's own marks)."""
    if not claimed:
        return
    ids = sorted(claimed, key=str)
    db.execute(
        text("""
            DELETE FROM helm_ledger_dirty d USING (
                SELECT x.workspace_id, x.work_item_id FROM helm_ledger_dirty x
                JOIN unnest(CAST(:ids AS uuid[]), CAST(:marks AS integer[])) AS seen(work_item_id, marks)
                  ON seen.work_item_id = x.work_item_id AND seen.marks = x.marks
                WHERE x.workspace_id = :workspace_id
                ORDER BY x.work_item_id FOR UPDATE OF x SKIP LOCKED
            ) gone WHERE d.workspace_id = gone.workspace_id AND d.work_item_id = gone.work_item_id
        """),
        {"workspace_id": workspace_id, "ids": [str(i) for i in ids], "marks": [claimed[i].marks for i in ids]},
    )


def _record_build(db: Session, workspace: Workspace, *, as_of: date, full: bool, served: Optional[int]) -> None:
    """Remember what the stored promises are up to date with. `served` is the number of full-rebuild
    requests the build saw when it began (a request that arrived while it ran stays pending)."""
    values = {"workspace_id": workspace.id, "organization_id": workspace.organization_id, "as_of": as_of,
              "built_at": func.now(), "incremental_runs": 0 if full else 1}
    statement = pg_insert(HelmLedgerState).values(**values, **({"full_served": served} if full else {}))
    update = {"as_of": as_of, "built_at": func.now(), "updated_at": func.now(),
              "incremental_runs": 0 if full else HelmLedgerState.incremental_runs + 1}
    if full:
        update["full_served"] = served
    db.execute(statement.on_conflict_do_update(index_elements=["workspace_id"], set_=update))


def write_rows(db: Session, workspace_id: uuid.UUID, rows: list[ledger.PromiseRow],
               existing: dict[str, str]) -> tuple[int, int, int, int]:
    """Write the difference between `rows` and the stored promises (`existing`: source key to content
    hash). Returns inserted, updated, unchanged and deleted. Keys in `existing` that `rows` does not
    produce are deleted."""
    wanted = {row.source_key: row for row in rows}
    inserted = updated = unchanged = 0
    for key, row in wanted.items():
        values = row.as_values()
        if key not in existing:
            inserted += 1
        elif existing[key] != values["content_hash"]:
            updated += 1
        else:
            unchanged += 1
            continue
        statement = pg_insert(HelmPromise).values(**values)
        update_values = {k: statement.excluded[k] for k in values if k not in ("source_key",)}
        update_values["updated_at"] = func.now()
        db.execute(statement.on_conflict_do_update(constraint="uq_helm_promises_source_key", set_=update_values))
    stale = [key for key in existing if key not in wanted]
    if stale:
        db.execute(delete(HelmPromise).where(HelmPromise.workspace_id == workspace_id,
                                             HelmPromise.source_key.in_(stale)))
    return inserted, updated, unchanged, len(stale)


def _stored(db: Session, workspace_id: uuid.UUID) -> dict[str, str]:
    return {key: digest for key, digest in db.execute(
        select(HelmPromise.source_key, HelmPromise.content_hash).where(HelmPromise.workspace_id == workspace_id)
    ).all()}


def rebuild_workspace(db: Session, *, workspace_id: uuid.UUID, as_of: Optional[date] = None) -> RebuildResult:
    """Recompute the whole workspace's promises and write the difference. Flushes; the caller commits.

    Serialised per workspace (a transaction-scoped advisory lock), so two ledger jobs for the same
    workspace never interleave their diffs. Everything marked changed before it began is now included,
    so those marks are cleared."""
    started = time.monotonic()
    as_of = as_of or datetime.now(timezone.utc).date()
    lock_workspace(db, workspace_id)
    state = _state(db, workspace_id)
    served = state["full_requests"] if state else 0
    claimed = _claim_dirty(db, workspace_id)
    workspace = db.get(Workspace, workspace_id)
    inputs = load_inputs(db, workspace_id=workspace_id, as_of=as_of)
    rows = ledger.build(inputs)
    inserted, updated, unchanged, deleted = write_rows(db, workspace_id, rows, _stored(db, workspace_id))
    _record_build(db, workspace, as_of=as_of, full=True, served=served)
    _release_dirty(db, workspace_id, claimed)
    db.flush()
    result = RebuildResult(workspace_id=workspace_id, inserted=inserted, updated=updated, deleted=deleted,
                           unchanged=unchanged, ms=int((time.monotonic() - started) * 1000))
    logger.info("helm.ledger_rebuilt", extra=result.as_dict())
    return result


def refresh_workspace(db: Session, *, workspace_id: uuid.UUID, as_of: Optional[date] = None) -> RebuildResult:
    """Bring the stored promises up to date with what changed since they were last written.

    Re-projects the documents marked changed and what depends on them, when it can; a full rebuild when
    it cannot: the ledger was never built, it was built for another day (statuses such as "broken"
    depend on today), something every promise depends on changed, or the change is too large for the
    shortcut to pay. The result is the same either way."""
    from app.services.helm import ledger_incremental

    started = time.monotonic()
    as_of = as_of or datetime.now(timezone.utc).date()
    lock_workspace(db, workspace_id)
    state = _state(db, workspace_id)
    why_full = ledger_incremental.why_full(state, as_of)
    if why_full is None:
        claimed = _claim_dirty(db, workspace_id)
        if not claimed:
            return RebuildResult(workspace_id=workspace_id, inserted=0, updated=0, deleted=0, unchanged=0,
                                 ms=int((time.monotonic() - started) * 1000), mode="none")
        outcome = ledger_incremental.update(db, workspace_id=workspace_id, as_of=as_of, dirty=claimed)
        if outcome.full_because is None:
            workspace = db.get(Workspace, workspace_id)
            _record_build(db, workspace, as_of=as_of, full=False, served=None)
            _release_dirty(db, workspace_id, claimed)
            db.flush()
            result = RebuildResult(workspace_id=workspace_id, inserted=outcome.inserted, updated=outcome.updated,
                                   deleted=outcome.deleted, unchanged=outcome.unchanged,
                                   ms=int((time.monotonic() - started) * 1000), mode="incremental",
                                   projected=outcome.projected)
            logger.info("helm.ledger_refreshed", extra=result.as_dict())
            return result
        why_full = outcome.full_because
    logger.info("helm.ledger_full_because", extra={"workspace_id": str(workspace_id), "why": why_full})
    return rebuild_workspace(db, workspace_id=workspace_id, as_of=as_of)


@dataclass(frozen=True)
class Verification:
    """The nightly check: the stored ledger against a full recomputation of the same day."""

    workspace_id: uuid.UUID
    checked: int
    mismatched: int
    #: A few source keys that differed, for the operator's alert.
    examples: tuple[str, ...]
    result: RebuildResult


def verify_workspace(db: Session, *, workspace_id: uuid.UUID, as_of: Optional[date] = None) -> Verification:
    """The nightly rebuild, with a check. Brings the stored promises up to date with what is marked
    changed, recomputes the whole workspace as of the day they were written for, and compares: a row that
    differs means an incremental update missed something (a write that bypassed the ORM, a dependency not
    followed). Then rebuilds for today, which repairs whatever differed. Flushes; the caller commits."""
    from app.services.helm import ledger_incremental

    as_of = as_of or datetime.now(timezone.utc).date()
    lock_workspace(db, workspace_id)
    state = _state(db, workspace_id)
    checked = mismatched = 0
    examples: tuple[str, ...] = ()
    if state is not None and state["as_of"] is not None and state["built_at"] is not None \
            and state["full_requests"] <= state["full_served"]:
        stored_day = state["as_of"]
        refresh_workspace(db, workspace_id=workspace_id, as_of=stored_day)  # pending changes, as of that day
        inputs = load_inputs(db, workspace_id=workspace_id, as_of=stored_day)
        wanted = {row.source_key: row.as_values()["content_hash"] for row in ledger.build(inputs)}
        stored = _stored(db, workspace_id)
        differing = sorted(key for key in set(wanted) | set(stored) if wanted.get(key) != stored.get(key))
        checked, mismatched, examples = len(wanted), len(differing), tuple(differing[:5])
    result = rebuild_workspace(db, workspace_id=workspace_id, as_of=as_of)
    db.execute(
        text("UPDATE helm_ledger_state SET checked_at = now(), check_mismatches = check_mismatches + :n "
             "WHERE workspace_id = :workspace_id"),
        {"n": mismatched, "workspace_id": workspace_id})
    if mismatched:
        logger.error("helm.ledger_drift", extra={"workspace_id": str(workspace_id), "mismatched": mismatched,
                                                 "checked": checked, "examples": list(examples)})
    return Verification(workspace_id=workspace_id, checked=checked, mismatched=mismatched, examples=examples,
                        result=result)


def workspace_ids_with_books(db: Session, organization_id: Optional[uuid.UUID] = None) -> list[uuid.UUID]:
    """Every workspace some active book reads (a WORKSPACE or SAMPLE book, or an ORGANIZATION book's)."""
    query = select(HelmBook.organization_id, HelmBook.workspace_id, HelmBook.kind).where(
        HelmBook.status == v.BOOK_ACTIVE)
    if organization_id is not None:
        query = query.where(HelmBook.organization_id == organization_id)
    out: set[uuid.UUID] = set()
    for org_id, workspace_id, kind in db.execute(query).all():
        if workspace_id is not None:
            out.add(workspace_id)
        else:
            out.update(db.execute(select(Workspace.id).where(Workspace.organization_id == org_id,
                                                             Workspace.is_sample.is_(False))).scalars())
    return sorted(out, key=str)


def book_workspace_ids(db: Session, book: HelmBook) -> list[uuid.UUID]:
    if book.workspace_id is not None:
        return [book.workspace_id]
    from app.models.workspace import WorkspaceStatus

    return sorted(db.execute(
        select(Workspace.id).where(Workspace.organization_id == book.organization_id,
                                   Workspace.is_sample.is_(False), Workspace.status == WorkspaceStatus.ACTIVE)
    ).scalars(), key=str)


def enqueue_rebuild(db: Session, *, workspace_id: uuid.UUID, organization_id: uuid.UUID, reason: str,
                    work_item_ids: Optional[Collection[uuid.UUID]] = None, full: bool = False) -> bool:
    """Ask for this workspace's ledger to be brought up to date soon (debounced). Only workspaces some Helm
    book reads are updated; returns False (nothing enqueued) for the rest. Never raises into the caller's
    document path.

    `work_item_ids` are documents the caller changed without the ORM noticing; `full` asks for a full
    rebuild (a change that every promise depends on)."""
    try:
        if work_item_ids:
            mark_dirty(db, workspace_id=workspace_id, work_item_ids=work_item_ids, reason=reason)
        if full:
            request_full(db, workspace_id=workspace_id)
        if workspace_id not in set(workspace_ids_with_books(db, organization_id)):
            return False
        from datetime import timedelta

        from app.services import job_service

        now = datetime.now(timezone.utc)
        bucket = int(now.timestamp()) // 10
        job_service.enqueue(
            db,
            job_type=v.JOB_LEDGER_BUILD,
            organization_id=organization_id,
            payload={"workspace_id": str(workspace_id), "organization_id": str(organization_id), "reason": reason},
            idempotency_key=f"{v.JOB_LEDGER_BUILD}:{workspace_id}:{bucket}",
            available_at=datetime.fromtimestamp((bucket + 1) * 10, tz=timezone.utc) + timedelta(seconds=1),
        )
        return True
    except Exception:  # noqa: BLE001 - the ledger catches up in the nightly rebuild
        logger.exception("helm.ledger_enqueue_failed", extra={"workspace_id": str(workspace_id)})
        return False


__all__ = ["RebuildResult", "Verification", "book_workspace_ids", "document_facts", "enqueue_rebuild",
           "identities_for_workspace", "load_inputs", "lock_workspace", "mark_dirty", "match_line_facts",
           "obligation_facts", "rebuild_workspace", "refresh_workspace", "request_full", "settlement_facts",
           "verify_workspace", "workspace_ids_with_books", "write_rows"]
