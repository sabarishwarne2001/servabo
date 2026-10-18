"""An incremental update of the Promise ledger writes exactly what a full rebuild writes (Session B).

    pytest tests/services/helm/test_ledger_incremental_equivalence.py -q

The ledger is no longer recomputed whenever one document changes: `ledger_store.refresh_workspace`
re-projects the documents that changed and what depends on them. That is only safe if the result is the
same as recomputing everything, so this test holds it to that on real Postgres, row for row (every
column, through the content hash), after every update, across thousands of random changes:

  * invoices created, edited (amount, number, date, supplier, direction) and deleted
  * credit notes, purchase orders, goods receipts, bank statements (created, edited, deleted)
  * payments recorded, held, waived and undone (what a bank import does to an invoice)
  * obligations (a certificate kept by a newer one, a notice) created, completed, waived, deleted
  * procurement cases that price a purchase order's lines against its invoices

The invoices are made to compete: a few suppliers whose names share words, amounts drawn from a handful
of values a cent or two apart, and bank statement lines that name the supplier, the invoice number, both
or neither. That is where a bank line goes to the first invoice that fits and a change to one invoice
changes the others. Each run is seeded; a failure names the seed, the step and what was done.
"""

from __future__ import annotations

import os
import random
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Optional

import pytest
from sqlalchemy import select

from app.models.document_role import DocumentRole
from app.models.helm import HelmBook, HelmLedgerDirty, HelmLedgerState, HelmPromise, HelmSettings
from app.models.procurement import ProcurementCase, ProcurementCaseLine
from app.services.helm import ledger, ledger_incremental, ledger_store, settlements
from app.services.helm import vocabulary as v
from app.services.obligations import service as obligations
from tests.engines.conftest import test_sessions  # noqa: F401  (fixture: threads open their own sessions)
from tests.security.plans import put_on_plan
from tests.services.helm import factories

US = "Meridian Wholesale Pvt Ltd"
US_TAX = "27AAACM1234F1Z5"
SUPPLIERS = ["Shree Balaji Traders", "Shree Ganesh Steel Traders", "Konkan Packaging Pvt Ltd",
             "Konkan Packaging Industries"]
#: A few rupees apart and a few a cent apart, so invoices compete for the same statement lines.
AMOUNTS = [40_000.00, 40_000.00, 40_000.01, 40_001.00, 55_500.00, 55_500.00, 12_250.50]
TODAY = date.today()
#: The suite runs a few seeds; a wider search is `HELM_EQUIVALENCE_SEEDS=200 pytest ...` (about a second each).
SEEDS = range(int(os.getenv("HELM_EQUIVALENCE_SEEDS", "8")))
STEPS = int(os.getenv("HELM_EQUIVALENCE_STEPS", "28"))


class World:
    """One workspace being changed at random, and everything the test needs to change it."""

    def __init__(self, db, tenant, seed: int) -> None:
        self.db, self.tenant, self.rng = db, tenant, random.Random(seed)
        self.seed, self.log = seed, []
        self.ws, self.org = tenant.workspace, tenant.organization.id
        self.numbers = 0
        self.docs: dict[str, list[Any]] = {"INVOICE": [], "CREDIT_NOTE": [], "PURCHASE_ORDER": [],
                                           "GOODS_RECEIPT": [], "STATEMENT": []}
        self.obligations: list[Any] = []
        self.cases: list[Any] = []

    # -- helpers -------------------------------------------------------------------------------------
    def number(self, prefix: str) -> str:
        self.numbers += 1
        return f"{prefix}-{self.numbers:04d}"

    def day(self, back: int = 75) -> date:
        return TODAY - timedelta(days=self.rng.randint(0, back))

    def received(self) -> datetime:
        return datetime.now(timezone.utc) - timedelta(days=self.rng.randint(0, 70), minutes=self.rng.randint(0, 900))

    def say(self, what: str) -> None:
        self.log.append(what)

    def pick(self, role: str) -> Optional[Any]:
        return self.rng.choice(self.docs[role]) if self.docs[role] else None

    # -- the changes ---------------------------------------------------------------------------------
    def create_invoice(self) -> None:
        supplier, amount = self.rng.choice(SUPPLIERS), self.rng.choice(AMOUNTS)
        number, on = self.number("INV"), self.day()
        receivable = self.rng.random() < 0.12
        extra: dict[str, Any] = {}
        if self.rng.random() < 0.5:
            extra["po_number"] = f"PO-{self.rng.randint(1, 6):04d}"
        item = factories.invoice(self.db, workspace=self.ws, organization_id=self.org, number=number,
                                 supplier=US if receivable else supplier, buyer=supplier if receivable else US,
                                 amount=amount, on=on, terms=self.rng.choice(["Net 30", "Net 15", None]),
                                 extra=extra, text=f"TAX INVOICE {number}")
        item.created_at = self.received()
        self.db.flush()
        self.docs["INVOICE"].append(item)
        self.say(f"create invoice {number} {supplier} {amount}")

    def edit_invoice(self) -> None:
        item = self.pick("INVOICE")
        if item is None:
            return
        entities = dict(item.extracted_entities)
        role = self.db.execute(select(DocumentRole).where(DocumentRole.work_item_id == item.id)).scalar_one()
        change = self.rng.choice(["amount", "number", "date", "supplier", "terms"])
        if change == "amount":
            amount = self.rng.choice(AMOUNTS)
            entities["total_amount"] = f"{amount:.2f}"
            role.total_micros = int(Decimal(str(amount)) * 1_000_000)
        elif change == "number":
            role.document_number = entities["invoice_number"] = self.number("INV")
        elif change == "date":
            role.document_date = self.day()
            entities["invoice_date"] = role.document_date.isoformat()
        elif change == "supplier":
            entities["vendor_name"] = self.rng.choice(SUPPLIERS)
        else:
            entities["payment_terms"] = self.rng.choice(["Net 30", "Net 45", "Net 7"])
        item.extracted_entities = entities
        self.db.flush()
        self.say(f"edit invoice {role.document_number} ({change})")

    def delete(self, role: str) -> None:
        item = self.pick(role)
        if item is None:
            return
        self.docs[role].remove(item)
        self.say(f"delete {role.lower()} {item.original_filename}")
        from app.crud import work_item as crud

        crud.delete_work_item(self.db, db_obj=item)
        self.db.flush()
        self.db.expire_all()

    def create_credit_note(self) -> None:
        target = self.pick("INVOICE")
        if target is None:
            return
        number, amount = self.number("CN"), self.rng.choice([500.0, 1250.0, 10_000.0])
        item = factories.document(
            self.db, workspace=self.ws, organization_id=self.org, role="CREDIT_NOTE", number=number,
            on=self.day(), total=amount, vendor=self.rng.choice(SUPPLIERS),
            entities={"document_classification": "Credit Note", "credit_note_number": number,
                      "invoice_reference": target.extracted_entities["invoice_number"],
                      "total_amount": f"{amount:.2f}", "currency": "INR"})
        self.docs["CREDIT_NOTE"].append(item)
        self.say(f"create credit note {number} against {target.extracted_entities['invoice_number']}")

    def retarget_credit_note(self) -> None:
        note, target = self.pick("CREDIT_NOTE"), self.pick("INVOICE")
        if note is None or target is None:
            return
        entities = dict(note.extracted_entities)
        entities["invoice_reference"] = target.extracted_entities["invoice_number"]
        note.extracted_entities = entities
        self.db.flush()
        self.say(f"credit note {entities['credit_note_number']} now against {entities['invoice_reference']}")

    def create_purchase_order(self) -> None:
        number = f"PO-{self.rng.randint(1, 6):04d}"
        item = factories.document(
            self.db, workspace=self.ws, organization_id=self.org, role="PURCHASE_ORDER", number=number,
            on=self.day(), total=10_000, vendor=self.rng.choice(SUPPLIERS),
            entities={"document_classification": "Purchase Order", "po_number": number,
                      "vendor_name": self.rng.choice(SUPPLIERS), "order_date": self.day().isoformat(),
                      "delivery_date": (TODAY + timedelta(days=self.rng.randint(-20, 20))).isoformat(),
                      "total_amount": "10000.00"})
        self.docs["PURCHASE_ORDER"].append(item)
        self.say(f"create purchase order {number}")

    def create_goods_receipt(self) -> None:
        order = self.pick("PURCHASE_ORDER")
        reference = order.extracted_entities["po_number"] if order is not None else f"PO-{self.rng.randint(1, 6):04d}"
        number = self.number("GRN")
        item = factories.document(
            self.db, workspace=self.ws, organization_id=self.org, role="GOODS_RECEIPT", number=number,
            on=self.day(30), vendor=self.rng.choice(SUPPLIERS),
            entities={"document_classification": "Goods Receipt", "grn_number": number, "po_number": reference,
                      "date": self.day(30).isoformat()})
        self.docs["GOODS_RECEIPT"].append(item)
        self.say(f"create goods receipt {number} for {reference}")

    def _statement_lines(self) -> list[dict[str, str]]:
        lines = []
        for _ in range(self.rng.randint(1, 6)):
            invoice = self.pick("INVOICE")
            supplier = (invoice.extracted_entities.get("vendor_name") if invoice is not None
                        else self.rng.choice(SUPPLIERS))
            amount = self.rng.choice(AMOUNTS)
            naming = self.rng.choice(["payee", "number", "both", "neither"])
            text = {"payee": f"NEFT {supplier.upper()}",
                    "number": f"NEFT {invoice.extracted_entities['invoice_number']}" if invoice is not None else "NEFT",
                    "both": (f"NEFT {supplier.upper()} {invoice.extracted_entities['invoice_number']}"
                             if invoice is not None else f"NEFT {supplier.upper()}"),
                    "neither": "NEFT PAYMENT"}[naming]
            lines.append({"date": self.day(60).isoformat(), "description": text, "debit": f"{amount:.2f}",
                          "credit": ""})
        return lines

    def create_bank_statement(self) -> None:
        number = self.number("HDFC")
        item = factories.document(
            self.db, workspace=self.ws, organization_id=self.org, role="STATEMENT", number=number,
            on=self.day(30), vendor=None, text="HDFC BANK - CURRENT ACCOUNT STATEMENT",
            entities={"document_classification": "Bank Statement", "currency": "INR",
                      "statement_date": TODAY.isoformat(), "closing_balance": "2500000.00",
                      "transactions": self._statement_lines()})
        item.created_at = self.received()
        self.db.flush()
        self.docs["STATEMENT"].append(item)
        self.say(f"create bank statement {number}")

    def edit_bank_statement(self) -> None:
        item = self.pick("STATEMENT")
        if item is None:
            return
        entities = dict(item.extracted_entities)
        entities["transactions"] = self._statement_lines()
        item.extracted_entities = entities
        self.db.flush()
        self.say(f"edit bank statement {item.original_filename}")

    def settle(self) -> None:
        item = self.pick("INVOICE")
        if item is None:
            return
        state = self.rng.choice([v.SETTLEMENT_PAID, v.SETTLEMENT_PAID, v.SETTLEMENT_HELD, v.SETTLEMENT_UNPAID,
                                 v.SETTLEMENT_SCHEDULED])
        paid_amount = self.rng.choice([None, None, int(Decimal(str(self.rng.choice(AMOUNTS))) * 1_000_000)])
        settlements.set_state(
            self.db, organization_id=self.org, workspace_id=self.ws.id, work_item_id=item.id, state=state,
            source=self.rng.choice([v.SOURCE_PERSON, v.SOURCE_STATEMENT]), paid_on=self.day(40),
            paid_amount_micros=paid_amount, run_date=TODAY + timedelta(days=3),
            hold_reason="Held for a check" if state == v.SETTLEMENT_HELD else None)
        self.say(f"settle {item.extracted_entities['invoice_number']} as {state} ({paid_amount})")

    def undo_settlement(self) -> None:
        item = self.pick("INVOICE")
        if item is None:
            return
        settlements.restore(self.db, organization_id=self.org, workspace_id=self.ws.id, work_item_id=item.id,
                            previous={"exists": False}, actor_user_id=None, action_id=None)
        self.say(f"undo the settlement of {item.extracted_entities['invoice_number']}")

    def waive(self) -> None:
        item = self.pick("INVOICE")
        if item is None:
            return
        settlements.waive(self.db, organization_id=self.org, workspace_id=self.ws.id, work_item_id=item.id,
                          code="NO_MATCHED_PO", actor_user_id=None)
        self.say(f"waive NO_MATCHED_PO on {item.extracted_entities['invoice_number']}")

    def create_obligation(self) -> None:
        kind = self.rng.choice(["EXPIRY", "EXPIRY", "NOTICE", "DELIVERY"])
        title = {"EXPIRY": "Fire insurance policy", "NOTICE": "Rate contract renewal",
                 "DELIVERY": "Deliver the steel"}[kind]
        supplier = self.rng.choice(SUPPLIERS[:2])
        document = self.pick("PURCHASE_ORDER") if self.rng.random() < 0.4 else None
        ob = obligations.create_manual(
            self.db, organization_id=self.org, workspace_id=self.ws.id, actor_user_id=self.tenant.owner.user.id,
            kind=kind, title=title, rule={"kind": "FIXED", "date": (TODAY + timedelta(days=self.rng.randint(-40, 90))).isoformat()},
            work_item_id=document.id if document is not None else None, counterparty_name=supplier)
        self.obligations.append(ob)
        self.say(f"create obligation {kind} for {supplier}")

    def move_obligation(self) -> None:
        if not self.obligations:
            return
        ob = self.rng.choice(self.obligations)
        action = self.rng.choice(["complete", "waive", "delete"])
        actor = self.tenant.owner.user.id
        try:
            if action == "complete":
                obligations.complete(self.db, ob=ob, actor_user_id=actor)
            elif action == "waive":
                obligations.waive(self.db, ob=ob, actor_user_id=actor, reason="not needed")
            else:
                self.obligations.remove(ob)
                obligations.delete_obligation(self.db, ob=ob, actor_user_id=actor)
        except obligations.ObligationError:
            return
        self.db.flush()
        self.say(f"{action} an obligation")

    def create_case(self) -> None:
        order, invoice = self.pick("PURCHASE_ORDER"), self.pick("INVOICE")
        if order is None or invoice is None:
            return
        receipt = self.pick("GOODS_RECEIPT")
        if self.db.execute(select(ProcurementCase.id).where(
                ProcurementCase.invoice_work_item_id == invoice.id, ProcurementCase.status != "SUPERSEDED")).first():
            return  # one live case per invoice
        case = ProcurementCase(
            organization_id=self.org, workspace_id=self.ws.id, po_work_item_id=order.id,
            receipt_work_item_id=receipt.id if receipt is not None and self.rng.random() < 0.6 else None,
            invoice_work_item_id=invoice.id, status="MATCHED", input_digest=uuid.uuid4().hex + uuid.uuid4().hex, policy_version=1,
            vendor_key=None, header_findings=[], line_count=2, exception_count=0, variance_micros=0)
        self.db.add(case)
        self.db.flush()
        for index in range(2):
            agreed = (100 + 20 * ((order.id.int + index) % 2)) * 1_000_000  # the order's price: one per line, whatever the case
            self.db.add(ProcurementCaseLine(
                organization_id=self.org, workspace_id=self.ws.id, case_id=case.id, line_number=index + 1,
                outcome="MATCHED", description=f"Steel {index}", po_line_index=index, po_quantity=Decimal(10),
                po_unit_price_micros=agreed, po_amount_micros=agreed * 10, receipt_line_index=index, invoice_line_index=index,
                receipt_quantity=Decimal(10),
                invoice_quantity=Decimal(10), invoice_unit_price_micros=agreed + self.rng.choice([0, 0, 5_000_000]),
                invoice_amount_micros=agreed * 10, pair_cost=0, price_delta_micros=0, quantity_delta=0,
                findings=[], evidence={}))
        self.db.flush()
        self.cases.append(case.id)
        self.say("create a procurement case")

    def retire_case(self) -> None:
        if not self.cases:
            return
        case = self.rng.choice(self.cases)
        self.cases.remove(case)
        live = self.db.execute(select(ProcurementCase).where(ProcurementCase.id == case)).scalar_one_or_none()
        if live is None:  # its purchase order was deleted, and the case with it
            return
        live.status = "SUPERSEDED"
        self.db.flush()
        self.say("supersede a procurement case")

    def step(self) -> None:
        moves = [self.create_invoice] * 5 + [self.edit_invoice] * 4 + [lambda: self.delete("INVOICE")] * 2 + [
            self.create_credit_note, self.retarget_credit_note, lambda: self.delete("CREDIT_NOTE"),
            self.create_purchase_order, lambda: self.delete("PURCHASE_ORDER"), self.create_goods_receipt,
            lambda: self.delete("GOODS_RECEIPT"), self.create_bank_statement, self.create_bank_statement,
            self.edit_bank_statement, lambda: self.delete("STATEMENT"), self.settle, self.settle,
            self.undo_settlement, self.waive, self.create_obligation, self.move_obligation, self.create_case,
            self.retire_case]
        for _ in range(self.rng.choice([1, 1, 1, 2, 3])):  # now and then several changes before one update
            self.rng.choice(moves)()


def _book(db, tenant) -> None:
    put_on_plan(db, tenant.organization, "business")
    book = HelmBook(organization_id=tenant.organization.id, workspace_id=tenant.workspace.id,
                    kind=v.BOOK_WORKSPACE, name="Equivalence", status=v.BOOK_ACTIVE)
    db.add(book)
    db.flush()
    db.add(HelmSettings(book_id=book.id, organization_id=tenant.organization.id,
                        identities=[{"name": US, "tax_id": US_TAX}], run_weekdays=[2, 5], horizon_days=30,
                        cost_of_capital_bps=1200, default_autonomy=v.AUTONOMY_PROPOSE, briefing_enabled=False,
                        first_run_step=4, preferences={}))
    db.flush()


def stored(db, workspace_id) -> dict[str, tuple[str, str, str, Optional[int]]]:
    return {p.source_key: (p.content_hash, p.kind, p.status, p.amount_micros) for p in db.execute(
        select(HelmPromise).where(HelmPromise.workspace_id == workspace_id)).scalars()}


def recomputed(db, workspace_id, as_of) -> dict[str, tuple[str, str, str, Optional[int]]]:
    inputs = ledger_store.load_inputs(db, workspace_id=workspace_id, as_of=as_of)
    return {r.source_key: (r.content_hash, r.kind, r.status, r.amount_micros) for r in ledger.build(inputs)}


def _what_differs(db, workspace_id, as_of, key: str) -> str:
    """Which columns of one promise differ, for the failure message."""
    row = db.execute(select(HelmPromise).where(HelmPromise.source_key == key)).scalar_one_or_none()
    wanted = next((r for r in ledger.build(ledger_store.load_inputs(db, workspace_id=workspace_id, as_of=as_of))
                   if r.source_key == key), None)
    if row is None or wanted is None:
        return f"{key[:12]} {'is missing' if row is None else 'should not exist'}"
    values = wanted.as_values()
    return f"{key[:12]}: " + ", ".join(
        f"{c} stored={getattr(row, c)!r} rebuilt={values[c]!r}" for c in values
        if c not in ("content_hash",) and ledger.canonical(getattr(row, c)) != ledger.canonical(values[c]))


def assert_equivalent(db, workspace_id, as_of, world: World, step: int) -> None:
    db.flush()
    db.expire_all()
    have, want = stored(db, workspace_id), recomputed(db, workspace_id, as_of)
    differing = sorted(k for k in set(have) | set(want) if have.get(k) != want.get(k))
    if differing:
        world.log.append("differences: " + "; ".join(_what_differs(db, workspace_id, as_of, k) for k in differing[:2]))
    assert not differing, (
        f"seed {world.seed}, step {step}: {len(differing)} of {len(want)} promises differ from a full rebuild; "
        f"e.g. {[(k[:48], have.get(k), want.get(k)) for k in differing[:3]]}\n  what was done: {world.log[-6:]}")


@pytest.fixture(autouse=True)
def _jobs():
    from app.workers.handlers import register_all

    register_all(replace=True)  # an update is requested through a job, as in production


@pytest.mark.parametrize("seed", SEEDS)
def test_incremental_updates_equal_a_full_rebuild(db_session, tenant, seed: int) -> None:
    db = db_session
    _book(db, tenant)
    world = World(db, tenant, seed)
    for _ in range(6):  # something to start from
        world.create_invoice()
    world.create_bank_statement()
    world.create_purchase_order()
    ledger_store.rebuild_workspace(db, workspace_id=tenant.workspace.id, as_of=TODAY)
    assert_equivalent(db, tenant.workspace.id, TODAY, world, 0)
    modes: list[str] = []
    for step in range(1, STEPS + 1):
        world.step()
        result = ledger_store.refresh_workspace(db, workspace_id=tenant.workspace.id, as_of=TODAY)
        modes.append(result.mode)
        assert_equivalent(db, tenant.workspace.id, TODAY, world, step)
    # The marks are all cleared, and the update really was incremental (not a rebuild every time).
    assert db.execute(select(HelmLedgerDirty).where(HelmLedgerDirty.workspace_id == tenant.workspace.id)).first() is None
    assert modes.count("incremental") >= STEPS // 2, modes
    assert "full" not in modes, modes


def test_a_new_day_and_a_change_of_identity_are_full_rebuilds(db_session, tenant) -> None:
    db = db_session
    _book(db, tenant)
    world = World(db, tenant, 99)
    for _ in range(4):
        world.create_invoice()
    wid = tenant.workspace.id
    assert ledger_store.refresh_workspace(db, workspace_id=wid, as_of=TODAY).mode == "full"  # never built
    assert ledger_store.refresh_workspace(db, workspace_id=wid, as_of=TODAY).mode == "none"  # nothing changed
    world.create_invoice()
    assert ledger_store.refresh_workspace(db, workspace_id=wid, as_of=TODAY).mode == "incremental"
    tomorrow = TODAY + timedelta(days=1)  # statuses depend on today
    assert ledger_store.refresh_workspace(db, workspace_id=wid, as_of=tomorrow).mode == "full"
    assert_equivalent(db, wid, tomorrow, world, 0)
    # "Who we are" changed: every promise's direction may flip, so the next update is a full rebuild.
    settings = db.execute(select(HelmSettings)).scalars().first()
    settings.identities = [{"name": "Somebody Else Ltd", "tax_id": "27AAACS9999F1Z5"}]
    db.flush()
    world.create_invoice()
    assert ledger_store.refresh_workspace(db, workspace_id=wid, as_of=tomorrow).mode == "full"
    assert_equivalent(db, wid, tomorrow, world, 1)
    state = db.execute(select(HelmLedgerState).where(HelmLedgerState.workspace_id == wid)).scalar_one()
    assert state.full_requests <= state.full_served  # the request was served, not left pending


def test_a_change_that_arrives_while_an_update_runs_is_not_lost(db_session, tenant) -> None:
    """The marks an update saw are cleared; one made after it looked stays for the next update."""
    db = db_session
    _book(db, tenant)
    world = World(db, tenant, 7)
    for _ in range(3):
        world.create_invoice()
    wid = tenant.workspace.id
    ledger_store.rebuild_workspace(db, workspace_id=wid, as_of=TODAY)
    world.create_invoice()
    claimed = ledger_store._claim_dirty(db, wid)  # what an update starting now would see
    assert len(claimed) == 1
    ledger_incremental.update(db, workspace_id=wid, as_of=TODAY, dirty=claimed)  # ... and does with it
    world.edit_invoice()  # committed after the update looked: marked again
    ledger_store._release_dirty(db, wid, claimed)  # the update finishes
    left = ledger_store._claim_dirty(db, wid)
    assert left, "the later change was cleared with the earlier one"
    ledger_store.refresh_workspace(db, workspace_id=wid, as_of=TODAY)
    assert_equivalent(db, wid, TODAY, world, 0)
    assert not ledger_store._claim_dirty(db, wid)


def test_a_full_rebuild_requested_while_one_runs_stays_pending(db_session, tenant, monkeypatch) -> None:
    """The build records the request counter it read before it began: a request that arrives while it
    runs is still pending afterwards (and is not lost to the build finishing)."""
    db = db_session
    _book(db, tenant)
    world = World(db, tenant, 3)
    for _ in range(3):
        world.create_invoice()
    wid = tenant.workspace.id
    real_load = ledger_store.load_inputs

    def load_then_a_request_arrives(*args, **kwargs):
        inputs = real_load(*args, **kwargs)
        ledger_store.request_full(db, workspace_id=wid)  # committed by somebody else, after the build began
        return inputs

    monkeypatch.setattr(ledger_store, "load_inputs", load_then_a_request_arrives)
    ledger_store.rebuild_workspace(db, workspace_id=wid, as_of=TODAY)
    monkeypatch.setattr(ledger_store, "load_inputs", real_load)
    state = db.execute(select(HelmLedgerState).where(HelmLedgerState.workspace_id == wid)).scalar_one()
    assert state.full_requests > state.full_served, "a request made during the build was treated as served"
    world.create_invoice()
    assert ledger_store.refresh_workspace(db, workspace_id=wid, as_of=TODAY).mode == "full"
    assert ledger_store.refresh_workspace(db, workspace_id=wid, as_of=TODAY).mode == "none"


def test_changes_and_updates_running_at_once_converge(db_session, tenant, test_sessions) -> None:
    """Four people (threads, each with their own database session) change documents and ask for updates at
    the same moment. Updates take turns (one lock per workspace), a change that commits while an update
    runs keeps its mark, and nothing deadlocks or fails; when they are done, one more update leaves the
    stored ledger equal to a full rebuild."""
    import threading
    from types import SimpleNamespace

    db = db_session
    _book(db, tenant)
    wid, org = tenant.workspace.id, tenant.organization.id
    owner = tenant.owner.user.id
    db.commit()
    shared = SimpleNamespace(workspace=SimpleNamespace(id=wid), organization=SimpleNamespace(id=org),
                             owner=SimpleNamespace(user=SimpleNamespace(id=owner)))
    seed_world = World(db, shared, 1)
    for _ in range(5):
        seed_world.create_invoice()
    ledger_store.rebuild_workspace(db, workspace_id=wid, as_of=TODAY)
    db.commit()

    errors: list[BaseException] = []
    modes: list[str] = []

    def person(index: int) -> None:
        try:
            with test_sessions() as session:
                mine = World(session, shared, 100 + index)
                for _ in range(6):
                    mine.step()
                    session.commit()
                    result = ledger_store.refresh_workspace(session, workspace_id=wid, as_of=TODAY)
                    session.commit()
                    modes.append(result.mode)
        except BaseException as error:  # noqa: BLE001 - reported on the main thread
            errors.append(error)

    threads = [threading.Thread(target=person, args=(n,)) for n in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=240)
    assert not any(thread.is_alive() for thread in threads), "an update never finished (a deadlock)"
    assert not errors, errors[0]

    db.rollback()
    ledger_store.refresh_workspace(db, workspace_id=wid, as_of=TODAY)
    db.commit()
    assert_equivalent(db, wid, TODAY, seed_world, 0)
    assert "incremental" in modes, modes


def test_the_retention_purge_is_followed_by_the_ledger(db_session, tenant) -> None:
    """The nightly retention purge deletes documents with raw SQL, which the ORM's events never see: it
    marks them itself, with their obligations and procurement cases, so the next update re-projects what
    pointed at them (the invoice a deleted credit note reduced, the order whose receipt went)."""
    from datetime import timezone
    from sqlalchemy import text
    from sqlalchemy.orm import sessionmaker

    from app.models.compliance import RetentionPolicy
    from scripts import sweep_compliance

    db = db_session
    _book(db, tenant)
    world = World(db, tenant, 11)
    for _ in range(4):
        world.create_invoice()
    world.create_credit_note()
    world.create_purchase_order()
    world.create_goods_receipt()
    world.create_case()
    world.create_obligation()
    wid = tenant.workspace.id
    ledger_store.rebuild_workspace(db, workspace_id=wid, as_of=TODAY)
    old = datetime.now(timezone.utc) - timedelta(days=400)
    victims = [world.docs["CREDIT_NOTE"][0].id, world.docs["GOODS_RECEIPT"][0].id, world.docs["INVOICE"][1].id]
    db.add(RetentionPolicy(organization_id=tenant.organization.id, work_item_retention_days=90,
                           auto_purge_enabled=True))
    db.execute(text("UPDATE work_items SET created_at = :old WHERE id = ANY(:ids)"), {"old": old, "ids": victims})
    db.commit()
    assert not ledger_store._claim_dirty(db, wid)

    deleted = sweep_compliance._purge_work_items(
        sessionmaker(bind=db.get_bind()), organization_id=tenant.organization.id, days=90, apply=True, batch_size=50)

    assert deleted == len(victims)
    db.expire_all()
    assert set(victims) <= set(ledger_store._claim_dirty(db, wid)), "the purge did not mark what it deleted"
    result = ledger_store.refresh_workspace(db, workspace_id=wid, as_of=TODAY)
    assert result.mode == "incremental"
    assert_equivalent(db, wid, TODAY, world, 0)
