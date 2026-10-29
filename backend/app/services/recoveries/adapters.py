"""One adapter per kind of money issue (Final session 2A, Phase 6; N-191). Read only.

Each adapter reads one engine's own tables and answers two questions for one workspace:

    observe(db, workspace, today)          -> the issues the engine reports now (Observation), with the engine's stored
                                              figure, its due date from the law or the terms, and its evidence
    judge(db, workspace, issues, today)    -> for issues already known, what the evidence now says (Verdict): verified
                                              (with the outcome it proves, if any), not money, closed, or reopened

Closure is only ever on evidence, one rule per kind (docs/product/RECOVERIES.md):

    GST_CREDIT            a later GSTR-2B carries the invoice (ITC_SECURED), or a credit note settles it in full
    DUPLICATE             the radar finding is confirmed and the duplicate is not paid (DUPLICATE_BLOCKED; Helm's rule)
    OVERCHARGE            a credit note against the invoice, or a re-read of the invoice at or below the order price
                          (OVERCHARGE_RECOVERED); a person accepting the price is "Not money"
    STATEMENT_DIFFERENCE  the supplier's next statement no longer shows it (never counted as money)
    PAYMENT_DEADLINE      paid on or before the deadline, with the payment evidenced (a fee stated in the terms: LATE_FEE_AVOIDED)

A new kind is one more adapter in ADAPTERS (Final session 2T added TRINETRA's "TDS not yet in the statement" this way).
    TDS_CREDIT          open cases with a gap; verified only by the accountant's confirmation; never an exposure in cash
No adapter moves money, approves, pays or releases a hold: they read.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Optional, Protocol, Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import entitlements
from app.models.gst import GstMatch
from app.models.helm import HelmBook, HelmPromise
from app.models.procurement import ProcurementCase, ProcurementCaseLine
from app.models.radar import AnomalyFinding, DocumentFingerprint
from app.models.recovery import RecoveryIssue
from app.models.work_item import WorkItem
from app.models.workspace import Workspace
from app.services.gst import vocabulary as gst_v
from app.services.gst.matching import section_16_4_deadline
from app.services.helm import money
from app.services.helm import vocabulary as helm_v
from app.services.procurement_matching import vocabulary as proc_v
from app.services.radar import vocabulary as radar_v
from app.services.recoveries import vocabulary as v

MATCHED_STATUSES = (gst_v.MATCHED, gst_v.MATCHED_WITH_DIFFERENCES)


@dataclass(frozen=True)
class Observation:
    kind: str
    subject_key: str
    work_item_id: Optional[uuid.UUID]
    title: str
    currency: Optional[str]
    exposure_micros: Optional[int]
    due_date: Optional[date] = None
    due_basis: Optional[str] = None
    #: The engine shows someone acting on it (a case disputed, a duplicate confirmed): Being fixed.
    in_progress: bool = False
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Outcome:
    category: str
    work_item_id: Optional[uuid.UUID]
    currency: str
    amount_micros: int
    occurred_on: date
    evidence: dict[str, Any]


@dataclass(frozen=True)
class Verdict:
    issue_id: uuid.UUID
    state: str                       # VERIFIED, NOT_MONEY, CLOSED, or BEING_FIXED (reopened: the evidence was undone)
    reason: str
    evidence: dict[str, Any] = field(default_factory=dict)
    outcome: Optional[Outcome] = None


class Adapter(Protocol):
    kind: str
    #: The plan capability the engine needs; None when the engine is open on every plan (GST Credit's figures).
    capability: Optional[str]
    #: Heavy adapters run in the hourly sweep and "Check now", not when the page opens.
    heavy: bool

    def observe(self, db: Session, workspace: Workspace, today: date) -> list[Observation]: ...

    def judge(self, db: Session, workspace: Workspace, issues: Sequence[RecoveryIssue], today: date) -> list[Verdict]: ...


# ------------------------------------------------------------------------------------------------------------ helpers


def _uuid(value: Any) -> Optional[uuid.UUID]:
    try:
        return uuid.UUID(str(value)) if value else None
    except ValueError:
        return None


def _date(value: Any) -> Optional[date]:
    if value is None or isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _payable_promises(db: Session, workspace_id: uuid.UUID, work_item_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, HelmPromise]:
    """Helm's payment promise for each invoice (what Helm knows of its payment and its credit notes)."""
    if not work_item_ids:
        return {}
    rows = db.execute(select(HelmPromise).where(
        HelmPromise.workspace_id == workspace_id, HelmPromise.kind == helm_v.KIND_PAYMENT_DUE,
        HelmPromise.direction == helm_v.DIRECTION_WE_OWE, HelmPromise.work_item_id.in_(list(work_item_ids)))).scalars()
    return {p.work_item_id: p for p in rows if p.work_item_id}


def _settlement(promise: Optional[HelmPromise]) -> dict[str, Any]:
    return dict(((promise.details or {}).get("settlement") or {})) if promise else {}


def _paid(promise: Optional[HelmPromise]) -> Optional[dict[str, Any]]:
    """The evidenced payment of an invoice: Helm's settlement says PAID, with a date and a source (a person's mark or a
    bank statement line). None when there is no such evidence."""
    settlement = _settlement(promise)
    if settlement.get("state") != helm_v.SETTLEMENT_PAID or not settlement.get("paid_on") or not settlement.get("source"):
        return None
    return {"paid_on": str(settlement["paid_on"])[:10], "source": settlement["source"]}


def _credited(promise: Optional[HelmPromise]) -> tuple[int, int, Optional[dict[str, Any]]]:
    """(credited, gross, the credit note's fulfilment) for an invoice, from Helm's ledger."""
    if promise is None:
        return 0, 0, None
    details = promise.details or {}
    credit = next((f for f in promise.fulfilments or [] if f.get("kind") == "CREDIT"), None)
    return int(details.get("credited_micros") or 0), int(details.get("gross_micros") or promise.amount_micros or 0), credit


def _names(db: Session, ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not ids:
        return {}
    return dict(db.execute(select(WorkItem.id, WorkItem.original_filename).where(WorkItem.id.in_(list(ids)))).all())


def _issue_work_item(issue: RecoveryIssue) -> Optional[uuid.UUID]:
    return issue.work_item_id or _uuid((issue.details or {}).get("work_item_id"))


# ------------------------------------------------------------------------------------------------------------ GST


class GstCredit:
    """An invoice in the books whose GST credit waits on the supplier (GST Credit's `WAITING_FOR_SUPPLIER`)."""

    kind = v.GST_CREDIT
    capability = None
    heavy = False

    def observe(self, db: Session, workspace: Workspace, today: date) -> list[Observation]:
        rows = db.execute(select(GstMatch).where(
            GstMatch.workspace_id == workspace.id, GstMatch.status == gst_v.WAITING_FOR_SUPPLIER,
            GstMatch.work_item_id.is_not(None), GstMatch.itc_micros > 0)).scalars().all()
        names = _names(db, [r.work_item_id for r in rows])
        out = []
        for row in rows:
            supplier = row.supplier_name or row.supplier_gstin or "a supplier"
            number = f" invoice {row.doc_number}" if row.doc_number else " an invoice"
            out.append(Observation(
                kind=self.kind, subject_key=str(row.work_item_id), work_item_id=row.work_item_id,
                title=f"GST credit waiting on {supplier} for{number}", currency="INR", exposure_micros=int(row.itc_micros),
                due_date=section_16_4_deadline(row.doc_date) if row.doc_date else None,
                due_basis="Section 16(4) time limit" if row.doc_date else None,
                details={"work_item_id": str(row.work_item_id), "document": names.get(row.work_item_id),
                         "supplier_gstin": row.supplier_gstin, "supplier_name": row.supplier_name,
                         "doc_number": row.doc_number, "doc_date": row.doc_date.isoformat() if row.doc_date else None,
                         "gstin": row.gstin}))
        return out

    def judge(self, db: Session, workspace: Workspace, issues: Sequence[RecoveryIssue], today: date) -> list[Verdict]:
        ids = [wid for wid in (_issue_work_item(i) for i in issues) if wid]
        matches: dict[uuid.UUID, list[GstMatch]] = {}
        for row in db.execute(select(GstMatch).where(GstMatch.workspace_id == workspace.id,
                                                     GstMatch.work_item_id.in_(ids))).scalars() if ids else ():
            matches.setdefault(row.work_item_id, []).append(row)
        promises = _payable_promises(db, workspace.id, ids)
        out: list[Verdict] = []
        for issue in issues:
            work_item_id = _issue_work_item(issue)
            rows = matches.get(work_item_id, []) if work_item_id else []
            reported = next((r for r in rows if r.status in MATCHED_STATUSES), None)
            credited, gross, credit = _credited(promises.get(work_item_id)) if work_item_id else (0, 0, None)
            if issue.state == v.VERIFIED:
                # Undone evidence: the return that carried it was removed and the invoice waits again.
                if any(r.status == gst_v.WAITING_FOR_SUPPLIER for r in rows) and not reported:
                    out.append(Verdict(issue.id, v.BEING_FIXED, "The GSTR-2B that carried this invoice is no longer imported."))
                continue
            if reported:
                amount = int(reported.itc_micros or 0)
                outcome = Outcome(v.ITC_SECURED, work_item_id, "INR", amount, today,
                                  {"gstr2b_period": reported.period_first_seen,
                                   "record_id": str(reported.record_id) if reported.record_id else None,
                                   "reported_late": bool(reported.reported_late), "status": reported.status}) if amount > 0 else None
                out.append(Verdict(issue.id, v.VERIFIED,
                                   f"The supplier reported it in the GSTR-2B for {reported.period_first_seen or 'a later period'}.",
                                   {"gstr2b_period": reported.period_first_seen,
                                    "record_id": str(reported.record_id) if reported.record_id else None},
                                   outcome))
            elif gross and credited >= gross:
                out.append(Verdict(issue.id, v.VERIFIED, "A credit note cancels the invoice: no credit is due on it.",
                                   {"credit_note": (credit or {}).get("document"), "credited_micros": credited}))
            elif not rows:
                out.append(Verdict(issue.id, v.CLOSED, "The invoice is no longer in the GST books."))
        return out


# ------------------------------------------------------------------------------------------------------------ duplicates


_FINDING_RANK = {radar_v.STATUS_CONFIRMED: 0, radar_v.STATUS_OPEN: 1, radar_v.STATUS_DISMISSED: 2}


def _one_per_invoice(findings):
    """The radar can find one invoice the duplicate of two others: one issue per invoice, read from its strongest finding
    (confirmed, then open, then dismissed)."""
    out: dict = {}
    for finding in findings:
        kept = out.get(finding.subject_work_item_id)
        if kept is None or _FINDING_RANK.get(finding.status, 3) < _FINDING_RANK.get(kept.status, 3):
            out[finding.subject_work_item_id] = finding
    return out


class Duplicate:
    """A probable duplicate invoice the radar found (`DUPLICATE_DOCUMENT`)."""

    kind = v.DUPLICATE
    capability = entitlements.ANOMALY_RADAR_CAPABILITY
    heavy = False

    def observe(self, db: Session, workspace: Workspace, today: date) -> list[Observation]:
        rows = db.execute(
            select(AnomalyFinding, DocumentFingerprint.total_micros, DocumentFingerprint.currency)
            .outerjoin(DocumentFingerprint, DocumentFingerprint.work_item_id == AnomalyFinding.subject_work_item_id)
            .where(AnomalyFinding.workspace_id == workspace.id, AnomalyFinding.kind == radar_v.KIND_DUPLICATE_DOCUMENT,
                   AnomalyFinding.status.in_((radar_v.STATUS_OPEN, radar_v.STATUS_CONFIRMED)))).all()
        strongest = _one_per_invoice(f for f, _, _ in rows)
        rows = [r for r in rows if strongest[r[0].subject_work_item_id] is r[0]]
        promises = _payable_promises(db, workspace.id, [f.subject_work_item_id for f, _, _ in rows])
        names = _names(db, [f.subject_work_item_id for f, _, _ in rows])
        out = []
        for finding, total, currency in rows:
            promise = promises.get(finding.subject_work_item_id)
            out.append(Observation(
                kind=self.kind, subject_key=str(finding.subject_work_item_id), work_item_id=finding.subject_work_item_id,
                title=f"Probable duplicate: {names.get(finding.subject_work_item_id) or 'an invoice'}",
                currency=currency if total else None, exposure_micros=int(total) if total else None,
                due_date=promise.due_date if promise else None, due_basis="Invoice due date" if promise and promise.due_date else None,
                in_progress=finding.status == radar_v.STATUS_CONFIRMED,
                details={"work_item_id": str(finding.subject_work_item_id), "finding_id": str(finding.id),
                         "counterpart_work_item_id": str(finding.counterpart_work_item_id) if finding.counterpart_work_item_id else None,
                         "document": names.get(finding.subject_work_item_id), "headline": finding.headline,
                         "needs_payment_record": promise is None}))
        return out

    def judge(self, db: Session, workspace: Workspace, issues: Sequence[RecoveryIssue], today: date) -> list[Verdict]:
        ids = [wid for wid in (_issue_work_item(i) for i in issues) if wid]
        findings = _one_per_invoice(db.execute(select(AnomalyFinding).where(
            AnomalyFinding.workspace_id == workspace.id, AnomalyFinding.kind == radar_v.KIND_DUPLICATE_DOCUMENT,
            AnomalyFinding.subject_work_item_id.in_(ids))).scalars()) if ids else {}
        promises = _payable_promises(db, workspace.id, ids)
        out: list[Verdict] = []
        for issue in issues:
            work_item_id = _issue_work_item(issue)
            finding = findings.get(work_item_id) if work_item_id else None
            promise = promises.get(work_item_id) if work_item_id else None
            paid = _paid(promise)
            if issue.state == v.VERIFIED:
                if paid:  # the evidence ("never paid") was undone
                    out.append(Verdict(issue.id, v.BEING_FIXED, f"The duplicate was paid on {paid['paid_on']}.",
                                       {"paid": paid}))
                continue
            if finding is None:
                out.append(Verdict(issue.id, v.CLOSED, "The radar no longer reports this duplicate."))
            elif finding.status == radar_v.STATUS_DISMISSED:
                note = (finding.resolution_note or "").strip()
                out.append(Verdict(issue.id, v.NOT_MONEY, f"Not a duplicate: {note}" if note else "Not a duplicate (dismissed in review)."))
            elif finding.status == radar_v.STATUS_CONFIRMED and promise is not None and not paid:
                amount = int((promise.details or {}).get("gross_micros") or promise.amount_micros or 0)
                outcome = Outcome(v.DUPLICATE_BLOCKED, work_item_id, promise.currency, amount, today,
                                  {"finding_id": str(finding.id), "confirmed": True,
                                   "settlement": _settlement(promise).get("state")}) if promise.currency and amount > 0 else None
                out.append(Verdict(issue.id, v.VERIFIED, "Confirmed as a duplicate and not paid.",
                                   {"finding_id": str(finding.id), "settlement": _settlement(promise).get("state")}, outcome))
        return out


# ------------------------------------------------------------------------------------------------------------ overcharges


class Overcharge:
    """An invoice priced above its purchase order (three-way matching's `PRICE_VARIANCE`), keyed by the invoice: a
    re-run of matching supersedes a case, the invoice stays."""

    kind = v.OVERCHARGE
    capability = entitlements.RECONCILIATION_CAPABILITY
    heavy = False

    def _live(self, db: Session, workspace_id: uuid.UUID, invoice_ids: Optional[Sequence[uuid.UUID]] = None):
        stmt = select(ProcurementCase).where(ProcurementCase.workspace_id == workspace_id,
                                             ProcurementCase.status != proc_v.CASE_STATUS_SUPERSEDED,
                                             ProcurementCase.invoice_work_item_id.is_not(None))
        if invoice_ids is not None:
            stmt = stmt.where(ProcurementCase.invoice_work_item_id.in_(list(invoice_ids)))
        cases = {c.invoice_work_item_id: c for c in db.execute(stmt.order_by(ProcurementCase.created_at)).scalars()}
        sums: dict[uuid.UUID, tuple[int, int]] = {}
        if cases:
            for case_id, over, invoiced in db.execute(
                    select(ProcurementCaseLine.case_id,
                           func.coalesce(func.sum(ProcurementCaseLine.price_delta_micros).filter(
                               ProcurementCaseLine.outcome == proc_v.OUTCOME_PRICE_VARIANCE,
                               ProcurementCaseLine.price_delta_micros > 0), 0),
                           func.coalesce(func.sum(ProcurementCaseLine.invoice_amount_micros), 0))
                    .where(ProcurementCaseLine.case_id.in_([c.id for c in cases.values()]))
                    .group_by(ProcurementCaseLine.case_id)).all():
                sums[case_id] = (int(over), int(invoiced))
        return cases, sums

    def observe(self, db: Session, workspace: Workspace, today: date) -> list[Observation]:
        cases, sums = self._live(db, workspace.id)
        live = {i: c for i, c in cases.items() if sums.get(c.id, (0, 0))[0] > 0
                and c.status not in (proc_v.CASE_STATUS_APPROVED,)}
        promises = _payable_promises(db, workspace.id, list(live))
        names = _names(db, list(live))
        out = []
        for invoice_id, case in live.items():
            over, invoiced = sums[case.id]
            promise = promises.get(invoice_id)
            out.append(Observation(
                kind=self.kind, subject_key=str(invoice_id), work_item_id=invoice_id,
                title=f"Priced above the purchase order: {names.get(invoice_id) or 'an invoice'}",
                currency=workspace.currency, exposure_micros=over,
                due_date=promise.due_date if promise else None, due_basis="Invoice due date" if promise and promise.due_date else None,
                in_progress=case.status == proc_v.CASE_STATUS_DISPUTED,
                details={"work_item_id": str(invoice_id), "case_id": str(case.id), "document": names.get(invoice_id),
                         "invoice_total_micros": invoiced, "case_status": case.status}))
        return out

    def judge(self, db: Session, workspace: Workspace, issues: Sequence[RecoveryIssue], today: date) -> list[Verdict]:
        ids = [wid for wid in (_issue_work_item(i) for i in issues) if wid]
        cases, sums = self._live(db, workspace.id, ids)
        promises = _payable_promises(db, workspace.id, ids)
        out: list[Verdict] = []
        for issue in issues:
            if issue.state == v.VERIFIED:
                continue  # a credit note or a corrected invoice is not undone by a later re-run
            work_item_id = _issue_work_item(issue)
            case = cases.get(work_item_id) if work_item_id else None
            found = int(issue.found_exposure_micros or issue.exposure_micros or 0)
            credited, _, credit = _credited(promises.get(work_item_id)) if work_item_id else (0, 0, None)
            currency = issue.currency or workspace.currency
            if credited > 0 and found > 0:
                amount = min(credited, found)
                out.append(Verdict(issue.id, v.VERIFIED, "A credit note against the invoice settles the overcharge.",
                                   {"credit_note": (credit or {}).get("document"), "credited_micros": credited},
                                   Outcome(v.OVERCHARGE_RECOVERED, work_item_id, currency, amount, _date((credit or {}).get("on")) or today,
                                           {"credit_note": (credit or {}).get("document"), "credited_micros": credited})))
                continue
            if case is None:
                out.append(Verdict(issue.id, v.CLOSED, "The invoice is no longer matched against an order."))
                continue
            over, invoiced = sums.get(case.id, (0, 0))
            if case.status == proc_v.CASE_STATUS_APPROVED and over > 0:
                reason = (case.resolution_reason or "").strip()
                out.append(Verdict(issue.id, v.NOT_MONEY, f"Price accepted: {reason}" if reason else "Price accepted in review."))
            elif over == 0:
                before = int((issue.details or {}).get("invoice_total_micros") or 0)
                drop = before - invoiced if before else 0
                if drop > 0 and found > 0:
                    amount = min(drop, found)
                    out.append(Verdict(issue.id, v.VERIFIED, "The invoice now bills at or below the order price.",
                                       {"case_id": str(case.id), "invoice_total_before": before, "invoice_total_now": invoiced},
                                       Outcome(v.OVERCHARGE_RECOVERED, work_item_id, currency, amount, today,
                                               {"corrected_invoice": True, "case_id": str(case.id)})))
                else:
                    out.append(Verdict(issue.id, v.CLOSED, "The order was changed: the invoice's price no longer exceeds it."))
        return out


# ------------------------------------------------------------------------------------------------------------ statements


def _books_for(db: Session, workspace: Workspace) -> list[HelmBook]:
    books = db.execute(select(HelmBook).where(
        HelmBook.organization_id == workspace.organization_id, HelmBook.status == helm_v.BOOK_ACTIVE)).scalars().all()
    if workspace.is_sample:
        return [b for b in books if b.kind == helm_v.BOOK_SAMPLE and b.workspace_id == workspace.id]
    return [b for b in books if b.kind != helm_v.BOOK_SAMPLE and (b.workspace_id in (None, workspace.id))]


class StatementDifference:
    """A supplier's statement that disagrees with the books (Helm's reconciliation, mandate 13), one issue per
    difference, keyed by the supplier, the kind of difference and the document or payment it names, so the supplier's
    next statement can show it gone. Needs a Helm book over the workspace."""

    kind = v.STATEMENT_DIFFERENCE
    capability = entitlements.HELM_CAPABILITY
    heavy = True

    def _latest(self, db: Session, workspace: Workspace, today: date):
        from app.services.helm import reconcile as rc
        from app.services.helm import snapshot_store

        books = _books_for(db, workspace)
        if not books:
            return None
        snapshot = snapshot_store.take(db, books[0], as_of=today)
        since = today - timedelta(days=v.STATEMENT_LOOKBACK_DAYS)
        latest: dict[str, Any] = {}
        for st in snapshot.supplier_statements:
            if st.workspace_id != str(workspace.id) or not st.counterparty_key:
                continue
            on = st.statement_date or st.received_on
            if on is None or on < since:
                continue
            kept = latest.get(st.counterparty_key)
            if kept is None or (kept.statement_date or kept.received_on) < on:
                latest[st.counterparty_key] = st
        return {key: rc.reconcile(st, snapshot.payables) for key, st in latest.items()}

    @staticmethod
    def _key(counterparty: str, difference: Any) -> str:
        ref = ""
        for item in difference.evidence or ():
            ref = str(item.get("number") or item.get("reference") or item.get("document") or "")
            if ref:
                break
        return f"{counterparty}|{difference.code}|{ref or difference.their_micros or difference.our_micros}"[:200]

    def _observations(self, recs: dict[str, Any]) -> list[Observation]:
        from app.services.helm import reconcile as rc

        out = []
        for counterparty, rec in (recs or {}).items():
            st = rec.statement
            for difference in rec.differences:
                if difference.code == rc.BALANCE_DIFFERS or not difference.effect_micros:
                    continue
                out.append(Observation(
                    kind=self.kind, subject_key=self._key(counterparty, difference), work_item_id=_uuid(st.work_item_id),
                    title=f"{st.counterparty_name or 'A supplier'}: {difference.summary}"[:500],
                    currency=rec.currency, exposure_micros=abs(int(difference.effect_micros)),
                    details={"work_item_id": st.work_item_id, "document": st.document, "code": difference.code,
                             "counterparty_key": counterparty, "counterparty_name": st.counterparty_name,
                             "statement_date": (st.statement_date or st.received_on).isoformat()
                             if (st.statement_date or st.received_on) else None,
                             "difference": difference.as_json()}))
        return out

    def observe(self, db: Session, workspace: Workspace, today: date) -> list[Observation]:
        return self._observations(self._latest(db, workspace, today) or {})

    def judge(self, db: Session, workspace: Workspace, issues: Sequence[RecoveryIssue], today: date) -> list[Verdict]:
        recs = self._latest(db, workspace, today)
        if recs is None:
            return []  # no Helm book: nothing can show the difference gone
        present = {o.subject_key for o in self._observations(recs)}
        out = []
        for issue in issues:
            if issue.state == v.VERIFIED:
                continue
            counterparty = (issue.details or {}).get("counterparty_key")
            rec = recs.get(counterparty) if counterparty else None
            if rec is None or issue.subject_key in present:
                continue
            on = rec.statement.statement_date or rec.statement.received_on
            seen = _date((issue.details or {}).get("statement_date"))
            if on and seen and on > seen:
                out.append(Verdict(issue.id, v.VERIFIED,
                                   f"{rec.statement.counterparty_name or 'The supplier'}'s statement of {on.isoformat()} no longer shows it.",
                                   {"statement_work_item_id": rec.statement.work_item_id, "statement_date": on.isoformat()}))
        return out


# ------------------------------------------------------------------------------------------------------------ deadlines


MSME_45, GST_180, LATE_FEE = "MSME_45", "GST_180", "LATE_FEE"
_SOURCE_WORDS = {helm_v.SOURCE_PERSON: "marked paid by a person", helm_v.SOURCE_STATEMENT: "a bank statement line",
                 helm_v.SOURCE_HELM: "paid through Helm"}
_RULE_WORDS = {MSME_45: "MSME 45-day limit (MSMED Act, section 15)", GST_180: "GST 180-day rule (section 16(2))",
               LATE_FEE: "Invoice terms (late fee)"}


class PaymentDeadline:
    """A payment deadline with money at stake, from Helm's Promise ledger: the MSME 45-day limit (the amount due), the GST
    180-day rule (the GST credit that would be reversed) and a late fee the terms state (the fee). Each becomes an issue
    from DEADLINE_LOOKAHEAD_DAYS before the deadline while the invoice is unpaid."""

    kind = v.PAYMENT_DEADLINE
    capability = entitlements.HELM_CAPABILITY
    heavy = False

    @staticmethod
    def _rules(promise: HelmPromise) -> list[tuple[str, date, int]]:
        details = promise.details or {}
        rules: list[tuple[str, date, int]] = []
        msme = _date(((details.get("msme_deadline") or {}).get("due")))
        if msme and promise.amount_micros:
            rules.append((MSME_45, msme, int(promise.amount_micros)))
        invoice_date = _date(details.get("invoice_date"))
        gst = int(details.get("gst_micros") or 0)
        if invoice_date and gst > 0:
            rules.append((GST_180, invoice_date + timedelta(days=180), gst))
        rate = (promise.terms or {}).get("late_fee_pct_per_month")
        if rate and promise.due_date and promise.amount_micros:
            rules.append((LATE_FEE, promise.due_date, money.pct_of(int(promise.amount_micros), Decimal(str(rate)))))
        return rules

    def observe(self, db: Session, workspace: Workspace, today: date) -> list[Observation]:
        rows = db.execute(select(HelmPromise).where(
            HelmPromise.workspace_id == workspace.id, HelmPromise.kind == helm_v.KIND_PAYMENT_DUE,
            HelmPromise.direction == helm_v.DIRECTION_WE_OWE,
            HelmPromise.status.in_((helm_v.STATUS_OPEN, helm_v.STATUS_PARTIAL, helm_v.STATUS_BROKEN)))).scalars().all()
        horizon = today + timedelta(days=v.DEADLINE_LOOKAHEAD_DAYS)
        out = []
        for promise in rows:
            if _paid(promise) or not promise.currency:
                continue
            for rule, deadline, at_stake in self._rules(promise):
                if deadline > horizon or at_stake <= 0:
                    continue
                state = _settlement(promise).get("state")
                out.append(Observation(
                    kind=self.kind, subject_key=f"{promise.work_item_id}|{rule}", work_item_id=promise.work_item_id,
                    title=f"{_RULE_WORDS[rule].split(' (')[0]}: {promise.title}"[:500], currency=promise.currency,
                    exposure_micros=at_stake, due_date=deadline, due_basis=_RULE_WORDS[rule],
                    in_progress=state in (helm_v.SETTLEMENT_SCHEDULED, helm_v.SETTLEMENT_APPROVED),
                    details={"work_item_id": str(promise.work_item_id), "rule": rule, "promise_id": str(promise.id),
                             "counterparty_name": promise.counterparty_name, "amount_due_micros": promise.amount_micros,
                             "settlement": state}))
        return out

    def judge(self, db: Session, workspace: Workspace, issues: Sequence[RecoveryIssue], today: date) -> list[Verdict]:
        ids = [wid for wid in (_issue_work_item(i) for i in issues) if wid]
        promises = _payable_promises(db, workspace.id, ids)
        out: list[Verdict] = []
        for issue in issues:
            work_item_id = _issue_work_item(issue)
            promise = promises.get(work_item_id) if work_item_id else None
            paid = _paid(promise)
            if issue.state == v.VERIFIED:
                if not paid:
                    out.append(Verdict(issue.id, v.BEING_FIXED, "The payment record was undone."))
                continue
            if promise is None:
                out.append(Verdict(issue.id, v.CLOSED, "The invoice is no longer in Helm's ledger."))
                continue
            if not paid:
                continue
            deadline = issue.due_date
            paid_on = _date(paid["paid_on"])
            if deadline and paid_on and paid_on > deadline:
                out.append(Verdict(issue.id, v.CLOSED, f"Paid on {paid_on.isoformat()}, after the deadline of {deadline.isoformat()}.",
                                   {"paid": paid}))
                continue
            rule = (issue.details or {}).get("rule")
            outcome = None
            if rule == LATE_FEE and issue.currency and int(issue.exposure_micros or 0) > 0:
                outcome = Outcome(v.LATE_FEE_AVOIDED, work_item_id, issue.currency, int(issue.exposure_micros),
                                  paid_on or today, {"paid_on": paid["paid_on"], "source": paid["source"],
                                                     "due_date": deadline.isoformat() if deadline else None})
            out.append(Verdict(issue.id, v.VERIFIED, f"Paid on {paid['paid_on']}, on time ({_SOURCE_WORDS.get(paid['source'], 'recorded')}).",
                               {"paid": paid}, outcome))
        return out


# ------------------------------------------------------------------------------------------------------------ TDS credit


class TdsCredit:
    """Tax a customer withheld that is not yet in the imported tax statement (TRINETRA; Final session 2T, Phase 7.10).

    One issue per open case with a known gap. The figure is a POSSIBLE CREDIT GAP, kept in `details` and the title: the issue has
    no exposure in cash, so it is in no "found" money, no "needs an owner" amount and no digest line, and a verified issue records
    no recovered outcome (it is evidence that a credit appears in the statement, not money). Closure is only on a person's
    review: the accountant confirmed the tax in the statement (verified), or the case was withdrawn, explained or left
    unresolved (closed, never counted). Live only while TRINETRA is live for the organization."""

    kind = v.TDS_CREDIT
    capability = entitlements.TRINETRA_CAPABILITY
    heavy = True

    @staticmethod
    def live(db: Session, organization_id: uuid.UUID) -> bool:
        from app.services.trinetra import mode

        return mode.live_for(db, organization_id)

    def observe(self, db: Session, workspace: Workspace, today: date) -> list[Observation]:
        from app.services.trinetra import service as trinetra
        from app.services.trinetra.notices import GAP_STATUSES, money

        if workspace.is_sample:
            return []
        out = []
        for item in trinetra.summary(db, workspace)["items"]:
            if item["review_state"] not in trinetra.OPEN_STATES or item["status"] not in GAP_STATUSES or not (item["gap_micros"] or 0) > 0:
                continue
            out.append(Observation(
                kind=self.kind, subject_key=item["id"], work_item_id=_uuid(item["work_item_id"]),
                title=f"TDS not yet in your statement: invoice {item['reference']} ({item['counterparty']}), {money(item['gap_micros'])}"[:500],
                currency="INR", exposure_micros=None,
                in_progress=item["review_state"] == "DISPUTED" or item["status"] == "DISPUTED",
                details={"case_id": item["id"], "work_item_id": item["work_item_id"], "gap_micros": int(item["gap_micros"]),
                         "expected_micros": int(item["expected_micros"] or 0), "currency": "INR", "year": item["year"],
                         "status": item["status"], "reference": item["reference"]}))
        return out

    def judge(self, db: Session, workspace: Workspace, issues: Sequence[RecoveryIssue], today: date) -> list[Verdict]:
        from app.models.trinetra import TrinetraCredit
        from app.services.trinetra import service as trinetra

        ids = [i for i in (_uuid(issue.subject_key) for issue in issues) if i]
        rows = {str(r.id): r for r in db.execute(select(TrinetraCredit).where(
            TrinetraCredit.workspace_id == workspace.id, TrinetraCredit.id.in_(ids))).scalars()} if ids else {}
        views = {item["id"]: item for item in trinetra.views(db, workspace, list(rows.values()))[0]} if rows else {}
        out: list[Verdict] = []
        for issue in issues:
            row, item = rows.get(issue.subject_key), views.get(issue.subject_key)
            if row is None or item is None:
                out.append(Verdict(issue.id, v.CLOSED, "The case no longer exists."))
                continue
            closed = row.state in trinetra.CLOSED_STATES
            confirmed = row.state == "CA_REVIEWED" and item["status"] in ("POSTED", "LATE_POSTING", "VERIFIED_CORRECTED")
            if issue.state == v.VERIFIED:
                if not confirmed:
                    out.append(Verdict(issue.id, v.BEING_FIXED, "The accountant's confirmation was reopened."))
                continue
            if confirmed:
                out.append(Verdict(issue.id, v.VERIFIED, "The accountant confirmed the tax is in the statement.",
                                   {"case_id": issue.subject_key, "statement_id": item["snapshot_id"]}))
            elif closed:
                out.append(Verdict(issue.id, v.CLOSED, f"The case was closed by a person ({row.state.replace('_', ' ').lower()})."))
        return out


ADAPTERS: tuple[Adapter, ...] = (GstCredit(), Duplicate(), Overcharge(), StatementDifference(), PaymentDeadline(), TdsCredit())
BY_KIND: dict[str, Adapter] = {a.kind: a for a in ADAPTERS}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


__all__ = ["ADAPTERS", "Adapter", "BY_KIND", "Observation", "Outcome", "Verdict"]
