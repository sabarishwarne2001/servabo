"""Library mandate 14 (India pack) — "Pay every GST invoice within 180 days of its date so the credit is kept".

Second proviso to Section 16(2) and Rule 37 of the CGST Act and Rules: if the value of the supply plus the tax is
not paid to the supplier within 180 days of the invoice date, the input tax credit taken is added back to your
output tax with interest (Section 50); it can be claimed again once paid. Helm's reading: every open invoice that
carries GST has a deadline of its invoice date plus 180 days (less an optional buffer), a hard constraint for the
payment plan like the MSMED Act's, and the earlier of the two wins. A payment after the deadline still goes ahead
(later is worse) but a person approves it knowing the consequence. Helm shows the credit at stake and says interest
may apply; it **does not calculate interest**. Recommendations, not legal or tax advice.

It also asks a supplier to report an invoice that is missing from your GSTR-2B (the "Request" action), once a month
and only for invoices in a month whose GSTR-2B was imported; it is sent only to a contact Helm knows, and only in Act
mode.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.services.gst import vocabulary as gv
from app.services.helm import money
from app.services.helm import vocabulary as v
from app.services.helm.mandates import base
from app.services.helm.mandates.spec import MandateSpec
from app.services.helm.snapshot import Payable, Snapshot

KEY = "gst_pay_within_180_days"
CONSEQUENCE = ("If the supplier is not paid within 180 days of the invoice date, the input tax credit taken has to be "
               "added back to your output tax, and interest may apply (Section 16(2) and Rule 37, CGST). It can be "
               "claimed again once paid.")
TOPIC = "GST_REPORTING"


class Params(BaseModel):
    model_config = ConfigDict(extra="forbid")

    buffer_days: int = Field(default=0, ge=0, le=60)
    ask_suppliers: bool = True


def deadline_of(payable: Payable, params: Params):
    if not payable.open or payable.gst_deadline is None:
        return None
    return payable.gst_deadline - timedelta(days=params.buffer_days)


def _explain(payable: Payable) -> str:
    return (f"180 days from the invoice date {money.day(payable.invoice_date)} is "
            f"{money.day(payable.gst_deadline)}, to keep the GST credit of "
            f"{money.say(payable.gst_micros or 0, payable.currency)} (Section 16(2), Rule 37)")


def _readback(spec: MandateSpec, params: Params) -> base.Readback:
    buffer = base.Chip("buffer_days", params.buffer_days,
                       "by the 180th day" if not params.buffer_days else f"{params.buffer_days} days before the 180th day",
                       "days")
    ask = base.Chip("ask_suppliers", params.ask_suppliers,
                    "ask suppliers to report invoices missing from my GSTR-2B" if params.ask_suppliers
                    else "do not ask suppliers to report missing invoices", "bool")
    return base.readback("Pay every invoice that carries GST ", buffer,
                         " from its date (Section 16(2) and Rule 37 of the CGST Act and Rules), so the input tax "
                         "credit is kept; ", ask, ".")


def _evaluate(snapshot: Snapshot, mandate: base.ActiveMandate, context: dict) -> base.Drift:
    params: Params = mandate.params
    schedule = context.get("schedule") or {}
    protected = [p for p in base.payables_in_scope(snapshot, mandate) if deadline_of(p, params)]
    if not protected:
        return base.Drift(base.HOLDING, "No GST invoices open", "No open invoice carries GST.", 0, [])
    held = (v.SETTLEMENT_HELD, v.SETTLEMENT_DISPUTED)
    late = [p for p in protected if p.gst_deadline < snapshot.as_of]
    at_risk = [p for p in protected if p not in late and p.settlement_state not in held and (
        (p.promise_id in schedule and (schedule[p.promise_id] is None or schedule[p.promise_id] > deadline_of(p, params)))
        or (schedule == {} and p.settlement_state == v.SETTLEMENT_UNPAID and deadline_of(p, params) <= snapshot.horizon_end))]
    items = [{"promise_id": p.promise_id, "document": p.document, "counterparty": p.counterparty_name,
              "currency": p.currency, "amount_micros": p.amount_micros, "gst_micros": p.gst_micros,
              "gst_deadline": p.gst_deadline.isoformat(), "explanation": _explain(p)} for p in protected]
    if late:
        total = sum(p.gst_micros or 0 for p in late)
        return base.Drift(base.BREACHED, f"{len(late)} past 180 days",
                          f"{money.say(total, late[0].currency)} of GST credit is on invoices unpaid after 180 days. "
                          + CONSEQUENCE, len(late), items)
    if at_risk:
        return base.Drift(base.DRIFTING, f"{len(at_risk)} at risk of passing 180 days",
                          "Some GST invoices are not planned inside 180 days. " + CONSEQUENCE, len(at_risk), items)
    nearest = min(p.gst_deadline for p in protected)
    return base.Drift(base.HOLDING, f"All {len(protected)} inside 180 days",
                      f"Every GST invoice is planned inside 180 days; the nearest last day is {money.day(nearest)}.",
                      len(protected), items)


def _optimizer(snapshot: Snapshot, mandate: base.ActiveMandate) -> base.OptimizerTerms:
    params: Params = mandate.params
    terms = base.OptimizerTerms()
    for payable in base.payables_in_scope(snapshot, mandate):
        due = deadline_of(payable, params)
        if due is None or not payable.schedulable:
            continue
        terms.deadlines[payable.promise_id] = (max(due, snapshot.as_of), "GST180", _explain(payable))
    return terms


def _guard(action: Any, snapshot: Snapshot, mandate: base.ActiveMandate, context: dict) -> list[base.Check]:
    if action.kind not in (v.ACTION_SCHEDULE_PAYMENT, v.ACTION_APPROVE_PAYMENT):
        return []
    payable = snapshot.payable(action.promise_id) if action.promise_id else None
    if payable is None or payable.gst_deadline is None or not base.in_scope(
            mandate, workspace_id=payable.workspace_id, counterparty_key=payable.counterparty_key,
            currency=payable.currency):
        return []
    run = action.run_date or snapshot.as_of
    inside = run <= payable.gst_deadline
    return [base.check(f"limit:{KEY}", "Inside the 180-day limit", inside, on_fail=v.CHECK_APPROVAL,
                       detail=(f"Paid on {money.day(run)}, by the 180th day ({money.day(payable.gst_deadline)})."
                               if inside else f"Paid on {money.day(run)}, after the 180th day "
                               f"({money.day(payable.gst_deadline)}). {CONSEQUENCE} A person approves it."),
                       evidence={"gst_deadline": payable.gst_deadline.isoformat(), "gst_micros": payable.gst_micros})]


def _propose(snapshot: Snapshot, mandate: base.ActiveMandate) -> list[base.Candidate]:
    """Ask a supplier to report what is missing from our GSTR-2B: one request a month for each supplier."""
    params: Params = mandate.params
    if not params.ask_suppliers:
        return []
    groups: dict[tuple[str, str], list[Payable]] = {}
    for payable in base.payables_in_scope(snapshot, mandate):
        if payable.gst_waiting and payable.gst_supplier_gstin and payable.gst_gstin and payable.currency == "INR":
            groups.setdefault((payable.workspace_id, payable.gst_supplier_gstin), []).append(payable)
    out: list[base.Candidate] = []
    for (workspace_id, supplier_gstin), items in sorted(groups.items()):
        items.sort(key=lambda p: (p.invoice_date or date.max, p.document_number or ""))
        first = items[0]
        total = sum(p.gst_micros or 0 for p in items)
        numbers = [p.document_number or p.document for p in items][:10]
        out.append(base.Candidate(
            kind=v.ACTION_REQUEST_DOCUMENT, mandate=mandate,
            title=f"Ask {first.counterparty_name or 'the supplier'} to report {len(items)} invoice"
                  f"{'s' if len(items) != 1 else ''} in GSTR-1"[:300],
            explanation=(f"{len(items)} invoice(s) from {first.counterparty_name or 'this supplier'} are in your books "
                         f"but in no GSTR-2B you imported ({', '.join(numbers)}), so the GST credit of "
                         f"{money.say(total, 'INR')} cannot be claimed yet (Section 16(2)(aa)). Helm drafts a note asking "
                         "the supplier to report them; it is sent only to a contact Helm knows, and only in Act mode."),
            key_parts=(workspace_id, supplier_gstin, "gst-request", snapshot.as_of.strftime("%Y-%m")),
            workspace_id=workspace_id, work_item_id=first.work_item_id, promise_id=first.promise_id,
            counterparty_key=first.counterparty_key,
            params={"topic": TOPIC, "supplier_gstin": supplier_gstin, "gstin": first.gst_gstin,
                    "invoices": numbers, "document_title": "GST reporting"}))
    return out


def _forecast(snapshot: Snapshot, mandate: base.ActiveMandate, sim) -> list[base.Risk]:
    params: Params = mandate.params
    out: list[base.Risk] = []
    for payable in base.payables_in_scope(snapshot, mandate):
        due = deadline_of(payable, params)
        if due is None or payable.settlement_state in (v.SETTLEMENT_SCHEDULED, v.SETTLEMENT_APPROVED):
            continue
        if 0 <= (due - snapshot.as_of).days <= 14:
            out.append(base.Risk(
                mandate=KEY, on=due, currency=payable.currency, amount_micros=payable.gst_micros,
                summary=(f"{payable.document} from {payable.counterparty_name or 'a supplier'} must be paid by "
                         f"{money.day(due)} to keep {money.say(payable.gst_micros or 0, payable.currency)} of GST "
                         "credit (180-day rule).")))
    return out


def _backtest(history, mandate: base.ActiveMandate) -> list[base.Finding]:
    out: list[base.Finding] = []
    for payable in base.payables_in_scope(history.snapshot, mandate):
        deadline = payable.gst_deadline
        if deadline is None or not history.within(deadline):
            continue
        if payable.paid_on is not None and payable.paid_on > deadline:
            honesty, what = v.HONESTY_CONFIRMED, f"was paid {(payable.paid_on - deadline).days} days after"
        elif payable.paid_on is None and payable.open and deadline < history.end:
            honesty, what = v.HONESTY_LIKELY, "is still unpaid after"
        else:
            continue
        out.append(base.Finding(
            mandate=KEY, on=deadline, action=v.ACTION_SCHEDULE_PAYMENT, honesty=honesty,
            category=base.CATEGORY_GST_180, currency=payable.currency, value_micros=0,
            summary=(f"{payable.document} from {payable.counterparty_name or 'a supplier'} "
                     f"({money.say(payable.amount_micros, payable.currency)}, GST "
                     f"{money.say(payable.gst_micros or 0, payable.currency)}) {what} its 180th day of "
                     f"{money.day(deadline)}. " + CONSEQUENCE),
            evidence=base.evidence_of(payable)))
    return out


TEMPLATE = base.Template(
    key=KEY, kind=v.MANDATE_KIND_LIMIT, title="Pay GST invoices within 180 days to keep the credit",
    group=base.GROUP_INDIA, order=14,
    summary="Section 16(2) and Rule 37: a hard deadline of 180 days from the invoice date.", Params=Params,
    readback=_readback, evaluate=_evaluate, propose=_propose, guard_checks=_guard, optimizer=_optimizer,
    forecast=_forecast, backtest=_backtest, law_links=gv.HELM_LAW_LINKS, disclaimer=gv.HELM_NOT_ADVICE,
    is_limit=True,
    keywords=("gst", "180 days", "input tax credit", "itc", "reversal", "rule 37", "section 16", "gstr-2b",
              "credit", "keep the credit"),
)
