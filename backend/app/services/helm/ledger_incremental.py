"""The Promise ledger, brought up to date without recomputing the workspace (Session B).

A document changes; the ledger re-projects that document and the others whose promises read it, and
leaves every other row alone. The result is exactly what a full rebuild would write, which is what a
property test and the nightly check hold it to. Three kinds of dependence have to be followed:

  1. by reference     a credit note names its invoice; a receipt, its purchase order; a procurement case,
                      its order, invoice and receipt; an obligation, its document. A changed (or deleted)
                      document re-projects what it pointed at and what pointed at it. What pointed at it
                      is found from the stored promises (their `fulfilments` name the documents that
                      fulfilled them); what it points at, from the document itself.
  2. by bank line     a statement line pays one invoice, the first (in the ledger's order) whose amount,
                      date and payee or number fit and that no earlier invoice has used. So whether an
                      invoice is paid depends on every invoice that could take the same line. The
                      invoices that can reach the same lines form a group; a change to one member
                      re-projects the group. Groups are found from the amounts alone, so a group is
                      never missed (it can be larger than needed, which costs time, not correctness).
  3. by number        a bank line that names another invoice pays that one: a new, changed or deleted
                      invoice number changes what the lines naming it mean to the invoices around them.

Everything is projected with `ledger.build` itself, on a smaller set of facts: the documents being
projected, the ones they reference, and the workspace-wide facts the build reads (every bank statement,
every credit note and receipt, the set of invoice numbers). Only the rows the changed documents own are
compared with the stored ones and written. When the change is too large for this to pay, or something
every promise depends on changed, `ledger_store.refresh_workspace` does the full rebuild instead.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any, Mapping, Optional

from sqlalchemy import or_, select

from app.models.document_role import DocumentRole
from app.models.helm import HelmPromise, HelmSettlement
from app.models.procurement import ProcurementCase
from app.models.work_item import WorkItem
from app.models.workspace import Workspace
from app.services.helm import ledger, ledger_store, money
from app.services.helm import vocabulary as v

logger = logging.getLogger("app.services.helm.ledger_incremental")

#: More marked documents than this in one update, or more documents to project: a full rebuild is
#: simpler and about as fast.
MAX_DIRTY = 200
MAX_PROJECTED = 600
#: A bank line is a candidate for an invoice when its amount is within this many cents of the claim
#: (the ledger looks two cents either side, then requires the amount to fit within one).
REACH_CENTS = 2
_CENT = money.MICROS // 100
#: Documents every projection reads in full: what invoices are paid by, reduced by, and received against.
REFERENCE_ROLES = (ledger.ROLE_CREDIT_NOTE, ledger.ROLE_GOODS_RECEIPT, ledger.ROLE_STATEMENT)


@dataclass
class Outcome:
    #: Set when the update cannot be done incrementally; the caller does a full rebuild.
    full_because: Optional[str] = None
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    deleted: int = 0
    projected: int = 0


def why_full(state: Optional[Mapping[str, Any]], as_of: date) -> Optional[str]:
    """Why the next update of this ledger must be a full rebuild, or None."""
    if state is None or state["built_at"] is None or state["as_of"] is None:
        return "the ledger has not been built"
    if state["full_requests"] > state["full_served"]:
        return "something every promise depends on changed"
    if state["as_of"] != as_of:
        return "the ledger was written for another day"
    return None


def _cents(micros: int) -> int:
    return round(micros / _CENT)


def _fulfilled_by(db: Any, workspace_id: uuid.UUID, ids: set[uuid.UUID]) -> tuple[set[uuid.UUID], set[uuid.UUID]]:
    """The documents and obligations whose stored promises were fulfilled by one of these documents (an
    invoice credited by a credit note, an order delivered by a receipt, a price line billed on an invoice,
    an invoice paid by a statement line)."""
    patterns: list[Any] = []
    for wid in sorted(ids, key=str):
        patterns.append([{"work_item_id": str(wid)}])
        patterns.append([{"statement": {"work_item_id": str(wid)}}])
    rows = db.execute(
        select(HelmPromise.work_item_id, HelmPromise.obligation_id)
        .where(HelmPromise.workspace_id == workspace_id, or_(*[HelmPromise.fulfilments.contains(p) for p in patterns]))
    ).all()
    return ({r.work_item_id for r in rows if r.work_item_id}, {r.obligation_id for r in rows if r.obligation_id})


def _stored_claims(db: Any, workspace_id: uuid.UUID, ids: set[uuid.UUID]) -> set[int]:
    """What the stored promises of these invoices said they could take a bank line for (the amount owed,
    the gross amount, what was paid): their claims before this update changes them."""
    out: set[int] = set()
    for amount, details, fulfilments in db.execute(
            select(HelmPromise.amount_micros, HelmPromise.details, HelmPromise.fulfilments)
            .where(HelmPromise.workspace_id == workspace_id, HelmPromise.work_item_id.in_(list(ids)),
                   HelmPromise.kind.in_((v.KIND_PAYMENT_DUE, v.KIND_PAYMENT_EXPECTED)))).all():
        out.add(amount or 0)
        out.add(int((details or {}).get("gross_micros") or 0))
        out |= {int(f.get("amount_micros") or 0) for f in fulfilments or [] if isinstance(f, dict)}
    out.discard(0)
    return out


def _cases_touching(db: Any, workspace_id: uuid.UUID, ids: set[uuid.UUID]) -> set[uuid.UUID]:
    """Every document of a live procurement case that names one of these as its order, invoice or receipt."""
    wanted = list(ids)
    rows = db.execute(
        select(ProcurementCase.po_work_item_id, ProcurementCase.invoice_work_item_id,
               ProcurementCase.receipt_work_item_id)
        .where(ProcurementCase.workspace_id == workspace_id, ProcurementCase.status != "SUPERSEDED",
               or_(ProcurementCase.po_work_item_id.in_(wanted), ProcurementCase.invoice_work_item_id.in_(wanted),
                   ProcurementCase.receipt_work_item_id.in_(wanted)))
    ).all()
    return {i for row in rows for i in row if i is not None}


def _documents_of_role(db: Any, workspace_id: uuid.UUID, role: str) -> list[Any]:
    return db.execute(
        select(DocumentRole.work_item_id, DocumentRole.document_number, DocumentRole.total_micros)
        .join(WorkItem, WorkItem.id == DocumentRole.work_item_id)
        .where(WorkItem.workspace_id == workspace_id, DocumentRole.workspace_id == workspace_id,
               DocumentRole.role == role, WorkItem.pipeline_stage != "FAILED")
    ).all()


def update(db: Any, *, workspace_id: uuid.UUID, as_of: date,
           dirty: Mapping[uuid.UUID, "ledger_store.Changed"]) -> Outcome:
    """Re-project what the marked documents changed, and write the difference. Flushes."""
    if len(dirty) > MAX_DIRTY:
        return Outcome(full_because=f"{len(dirty)} documents changed")
    workspace = db.get(Workspace, workspace_id)
    identities = ledger_store.identities_for_workspace(db, workspace_id)
    fmt = workspace.date_format
    ids = set(dirty)

    # ---- by reference ------------------------------------------------------------------------------
    pointed_at_by, obligations_pointed_at_by = _fulfilled_by(db, workspace_id, ids)
    facts: dict[uuid.UUID, ledger.DocumentFacts] = {
        d.work_item_id: d for d in ledger_store.document_facts(
            db, workspace, ids=ids | pointed_at_by, roles=REFERENCE_ROLES)}

    def load(wanted: set[uuid.UUID]) -> None:
        missing = [i for i in wanted if i not in facts]
        if missing:
            facts.update({d.work_item_id: d for d in ledger_store.document_facts(db, workspace, ids=missing)})

    invoices = {r.work_item_id: r for r in _documents_of_role(db, workspace_id, ledger.ROLE_INVOICE)}
    projected = set(ids | pointed_at_by | _cases_touching(db, workspace_id, ids))
    credit_targets = {ledger.credit_reference(facts[i]) for i in ids if i in facts} - {None}
    if credit_targets:  # a credit note now names an invoice
        projected |= {i for i, r in invoices.items() if r.document_number and ledger.nz_number(r.document_number)
                      in credit_targets}
    receipt_targets = {ledger.nz_number(facts[i].po_reference) for i in ids
                       if i in facts and facts[i].role == ledger.ROLE_GOODS_RECEIPT and facts[i].po_reference}
    if receipt_targets:  # a receipt now names a purchase order (a purchase order with no number of its own
        # is matched by the reference it prints, so it is always re-projected)
        projected |= {r.work_item_id for r in _documents_of_role(db, workspace_id, ledger.ROLE_PURCHASE_ORDER)
                      if not r.document_number or ledger.nz_number(r.document_number) in receipt_targets}

    # ---- by bank line and by number ------------------------------------------------------------------
    load(projected)
    credits = ledger.credit_index(d for d in facts.values() if d.role == ledger.ROLE_CREDIT_NOTE)
    credited_numbers = {number for _, number in credits}
    paid = {r.work_item_id: r.paid_amount_micros for r in db.execute(
        select(HelmSettlement.work_item_id, HelmSettlement.paid_amount_micros)
        .where(HelmSettlement.workspace_id == workspace_id, HelmSettlement.state == v.SETTLEMENT_PAID,
               HelmSettlement.paid_amount_micros.is_not(None))).all()}
    heavy = {i for i, r in invoices.items() if r.total_micros is None
             or (r.document_number and ledger.nz_number(r.document_number) in credited_numbers)}
    load(heavy | {i for i in projected if i in invoices})
    heavy_settlements = ledger_store.settlement_facts(db, workspace_id, ids=heavy | (projected & set(invoices)))
    claims: dict[uuid.UUID, set[int]] = {}
    for i, r in invoices.items():
        if i in heavy or i in projected:
            claims[i] = {_cents(m) for m in ledger.claim_micros(facts[i], heavy_settlements.get(i), credits)}
        else:
            claims[i] = {_cents(max(0, r.total_micros))} if r.total_micros else set()
            if paid.get(i):
                claims[i].add(_cents(paid[i]))

    bank_lines = [line for d in facts.values() if d.role == ledger.ROLE_STATEMENT
                  and ledger.statement_kind(d, identities) == ledger.STATEMENT_BANK
                  for line in ledger.statement_lines(d, fmt)]
    line_cents: dict[int, list[Any]] = {}
    for line in bank_lines:
        for value in (line.debit_micros, line.credit_micros):
            if value is not None:
                line_cents.setdefault(_cents(value), []).append(line)
    seeds: set[int] = {_cents(m) for change in dirty.values() for m in change.claims}
    for i in projected & set(invoices):
        seeds |= claims[i]
    # An invoice re-projected because of what it depends on (a credit note now reduces it) took lines
    # for a different amount before; the invoices that wanted those lines are affected too.
    seeds |= {_cents(m) for m in _stored_claims(db, workspace_id, projected & set(invoices))}
    for k, lines_at in line_cents.items():  # the lines of a statement that changed
        if any(line.statement_work_item_id in ids for line in lines_at):
            seeds.add(k)
    numbers = {ledger.joined_number(facts[i].document_number) for i in ids
               if i in facts and facts[i].role == ledger.ROLE_INVOICE and facts[i].document_number}
    numbers |= {ledger.joined_number(n) for change in dirty.values() for n in change.numbers}
    numbers.discard("")
    if numbers:  # the lines that name one of these invoice numbers now mean something else
        named = frozenset(numbers)
        for k, lines_at in line_cents.items():
            if any(ledger.numbers_named(f"{line.description} {line.reference}", named) for line in lines_at):
                seeds.add(k)

    by_cent: dict[int, set[uuid.UUID]] = {}
    for i, cs in claims.items():
        for c in cs:
            by_cent.setdefault(c, set()).add(i)
    group = set(projected & set(invoices))
    while True:
        touched = {k for s in seeds for k in range(s - REACH_CENTS, s + REACH_CENTS + 1) if k in line_cents}
        reach = {c for k in touched for c in range(k - REACH_CENTS, k + REACH_CENTS + 1)}
        joining = {i for c in reach for i in by_cent.get(c, ())} - group
        if not joining:
            break
        group |= joining
        for i in joining:
            seeds |= claims[i]
    projected |= group
    if len(projected) > MAX_PROJECTED:
        return Outcome(full_because=f"{len(projected)} documents depend on the change")

    # ---- what is projected, and what it reads ----------------------------------------------------------
    load(projected)
    match_lines = ledger_store.match_line_facts(db, workspace_id, documents=projected)
    for line in match_lines:
        load({i for i in (line.po_work_item_id, line.invoice_work_item_id, line.receipt_work_item_id) if i})
    obligations = ledger_store.obligation_facts(db, workspace_id, ids=ids | obligations_pointed_at_by,
                                                work_items=projected)
    present = set(facts) | {o.obligation_id for o in obligations}
    if any(o.kind == "EXPIRY" for o in obligations) or ids - present:
        # A certificate is kept by a newer one of the same supplier: the whole group is re-projected
        # (also when something vanished, which may have been one).
        known = {o.obligation_id for o in obligations}
        obligations += [o for o in ledger_store.obligation_facts(db, workspace_id, kind="EXPIRY")
                        if o.obligation_id not in known]
    load({o.work_item_id for o in obligations if o.work_item_id})
    # Invoices loaded only to find their claims are not projected (they would be re-projected for nothing).
    needed = projected | {o.work_item_id for o in obligations if o.work_item_id} | {
        i for line in match_lines for i in (line.po_work_item_id, line.invoice_work_item_id, line.receipt_work_item_id)
        if i}
    documents = [d for d in facts.values() if d.work_item_id in needed or d.role in REFERENCE_ROLES]
    settlements = ledger_store.settlement_facts(
        db, workspace_id, ids=[d.work_item_id for d in documents if d.role == ledger.ROLE_INVOICE])
    rows = ledger.build(ledger.LedgerInputs(
        as_of=as_of, documents=documents, match_lines=match_lines, obligations=obligations,
        settlements=settlements, identities=identities, date_format=fmt, workspace_currency=workspace.currency,
        organization_id=workspace.organization_id,
        known_invoice_numbers=frozenset(ledger.joined_number(r.document_number) for r in invoices.values()
                                        if r.document_number) - {""}))

    # ---- write only what the projected documents own ----------------------------------------------------
    scope_obligations = ids | obligations_pointed_at_by | {o.obligation_id for o in obligations}
    owned = [r for r in rows if (r.obligation_id is None and r.work_item_id in projected)
             or (r.obligation_id is not None and r.obligation_id in scope_obligations)]
    existing = {key: digest for key, digest in db.execute(
        select(HelmPromise.source_key, HelmPromise.content_hash).where(
            HelmPromise.workspace_id == workspace_id,
            or_(HelmPromise.work_item_id.in_(list(projected)), HelmPromise.obligation_id.in_(list(scope_obligations)))
        )).all()}
    inserted, updated, unchanged, deleted = ledger_store.write_rows(db, workspace_id, owned, existing)
    return Outcome(inserted=inserted, updated=updated, unchanged=unchanged, deleted=deleted,
                   projected=len(projected))
