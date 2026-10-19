"""Library mandate 15 (India pack) — "Hold payment of an invoice until the supplier has reported it in GSTR-2B".

You can claim input tax credit only on an invoice the supplier has reported (Section 16(2)(aa), CGST Act), so
paying a supplier who has not reported it leaves you paying tax you cannot yet claim. This mandate holds the
payment of such an invoice, optionally only above an amount, until it appears in an imported GSTR-2B.

**It never makes a payment late under the MSMED Act or the 180-day rule.** When the earlier of those deadlines is
within the safety days (10 by default), Helm releases the hold, pays on time and lists the GST follow-up instead:
the supplier still has to report the invoice before the credit can be claimed, and paying inside 180 days keeps
the credit you have taken safe. It applies only where a GSTR-2B for the invoice's own month has been imported.
Propose mode by default; it is off until someone turns it on. Recommendations, not legal or tax advice.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from app.services.gst import vocabulary as gv
from app.services.helm import money
from app.services.helm import vocabulary as v
from app.services.helm.mandates import base
from app.services.helm.mandates.spec import MandateSpec, Money
from app.services.helm.snapshot import Payable, Snapshot

KEY = "gst_hold_until_reported"
CODE = "GST_NOT_REPORTED"
ON_TIME = ("Helm pays it on time because the MSMED Act or the 180-day rule leaves no more room, and lists the GST "
           "follow-up: the supplier must still report the invoice before the credit can be claimed.")


class Params(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: Hold only invoices at or above this amount; None: every invoice that is waiting.
    threshold: Optional[Money] = None
    #: Release the hold this many days before the earlier legal deadline, so the next payment run can pay it.
    safety_days: int = Field(default=10, ge=3, le=30)


def law_deadline(payable: Payable) -> Optional[date]:
    """The earlier of the MSMED Act deadline and the 180th day: the last day a payment may be made."""
    dates = [d for d in (payable.msme_deadline, payable.gst_deadline) if d is not None]
    return min(dates) if dates else None


def has_room(payable: Payable, params: Params, as_of: date) -> bool:
    """Is the earlier legal deadline further off than the safety days? (No deadline: yes.)"""
    deadline = law_deadline(payable)
    return deadline is None or deadline - timedelta(days=params.safety_days) > as_of


def above_threshold(payable: Payable, params: Params) -> bool:
    if params.threshold is None:
        return True
    return payable.currency == params.threshold.currency and payable.amount_micros >= params.threshold.amount_micros


def waiting(payable: Payable, params: Params) -> bool:
    return payable.open and payable.gst_waiting and above_threshold(payable, params)


def holdable(payable: Payable, params: Params, as_of: date) -> bool:
    return waiting(payable, params) and has_room(payable, params, as_of)


def _still_holds(snapshot: Snapshot, payable: Payable, mandate: base.ActiveMandate) -> bool:
    return holdable(payable, mandate.params, snapshot.as_of)


def _readback(spec: MandateSpec, params: Params) -> base.Readback:
    above = (base.Chip("threshold", params.threshold.model_dump(),
                       f"of {money.say(params.threshold.amount_micros, params.threshold.currency)} or more",
                       "money") if params.threshold else base.Chip("threshold", None, "of any amount", "money"))
    safety = base.Chip("safety_days", params.safety_days, f"{params.safety_days} days", "days")
    return base.readback("Hold the payment of an invoice ", above, " until the supplier has reported it in my GSTR-2B "
                         "(Section 16(2)(aa)), but never past the earlier of the MSMED Act deadline and the 180th day: "
                         "release it ", safety, " before, pay on time and list the follow-up.")


def _evaluate(snapshot: Snapshot, mandate: base.ActiveMandate, context: dict) -> base.Drift:
    params: Params = mandate.params
    waiters = [p for p in base.payables_in_scope(snapshot, mandate) if waiting(p, params)]
    if not waiters:
        return base.Drift(base.HOLDING, "Nothing waiting",
                          "Every invoice in a month whose GSTR-2B was imported has been reported by its supplier "
                          "(or none was imported).", 0, [])
    held_states = (v.SETTLEMENT_HELD, v.SETTLEMENT_DISPUTED)
    safe = [p for p in waiters if has_room(p, params, snapshot.as_of)]
    follow_up = [p for p in waiters if p not in safe]
    exposed = [p for p in safe if p.settlement_state not in held_states]
    items = [{"promise_id": p.promise_id, "document": p.document, "counterparty": p.counterparty_name,
              "currency": p.currency, "amount_micros": p.amount_micros, "gst_micros": p.gst_micros,
              "law_deadline": law_deadline(p).isoformat() if law_deadline(p) else None,
              "follow_up": p in follow_up} for p in waiters]
    held_total = sum(p.amount_micros for p in safe if p.settlement_state in held_states)
    tail = (f" {len(follow_up)} will be paid on time instead and need a GST follow-up. " + ON_TIME) if follow_up else ""
    if exposed:
        return base.Drift(base.DRIFTING, f"{len(exposed)} not held yet",
                          f"{len(exposed)} invoice(s) the supplier has not reported are not held yet." + tail,
                          len(exposed), items)
    return base.Drift(base.HOLDING,
                      f"{money.say(held_total, 'INR')} held" if held_total else f"{len(follow_up)} to follow up",
                      f"{len(safe)} invoice(s) are held until the supplier reports them." + tail, len(waiters), items)


def _propose(snapshot: Snapshot, mandate: base.ActiveMandate) -> list[base.Candidate]:
    params: Params = mandate.params
    out: list[base.Candidate] = []
    for payable in base.payables_in_scope(snapshot, mandate):
        if not holdable(payable, params, snapshot.as_of) or payable.settlement_state in (
                v.SETTLEMENT_HELD, v.SETTLEMENT_DISPUTED, v.SETTLEMENT_SCHEDULED, v.SETTLEMENT_APPROVED):
            continue
        deadline = law_deadline(payable)
        out.append(base.Candidate(
            kind=v.ACTION_HOLD_PAYMENT, mandate=mandate,
            title=f"Hold {payable.document_number or payable.document}: not in GSTR-2B",
            explanation=(f"{payable.counterparty_name or 'The supplier'} has not reported {payable.document} in a GSTR-2B "
                         f"you imported, so its GST credit of {money.say(payable.gst_micros or 0, payable.currency)} "
                         "cannot be claimed (Section 16(2)(aa)). Helm holds the payment until it appears"
                         + (f", and releases it {params.safety_days} days before {money.day(deadline)}, the earlier "
                            "legal deadline, so it is never paid late." if deadline else ".")),
            key_parts=(payable.promise_id, "gst-hold", payable.settlement_version),
            workspace_id=payable.workspace_id, work_item_id=payable.work_item_id, promise_id=payable.promise_id,
            counterparty_key=payable.counterparty_key, amount_micros=payable.amount_micros, currency=payable.currency,
            params={"reason": CODE, "document_number": payable.document_number}))
    return out


def _optimizer(snapshot: Snapshot, mandate: base.ActiveMandate) -> base.OptimizerTerms:
    terms = base.OptimizerTerms()
    for payable in base.payables_in_scope(snapshot, mandate):
        if holdable(payable, mandate.params, snapshot.as_of):
            terms.exclude[payable.promise_id] = "the supplier has not reported it in GSTR-2B"
    return terms


def _forecast(snapshot: Snapshot, mandate: base.ActiveMandate, sim) -> list[base.Risk]:
    """Invoices Helm will pay on time although the supplier has not reported them: said in words, with the follow-up."""
    params: Params = mandate.params
    out: list[base.Risk] = []
    for payable in base.payables_in_scope(snapshot, mandate):
        if waiting(payable, params) and not has_room(payable, params, snapshot.as_of):
            deadline = law_deadline(payable)
            out.append(base.Risk(
                mandate=KEY, on=deadline, currency=payable.currency, amount_micros=payable.gst_micros,
                summary=(f"{payable.document} from {payable.counterparty_name or 'a supplier'} is not in your GSTR-2B "
                         f"but must be paid by {money.day(deadline)} (the MSMED Act deadline or the 180th day), so "
                         "Helm pays it on time instead of holding it. Ask the supplier to report it in GSTR-1; "
                         f"{money.say(payable.gst_micros or 0, payable.currency)} of credit waits for that.")))
    return out


TEMPLATE = base.Template(
    key=KEY, kind=v.MANDATE_KIND_LIMIT, title="Hold payment until the supplier has reported the invoice in GSTR-2B",
    group=base.GROUP_INDIA, order=15,
    summary="Section 16(2)(aa): credit only on reported invoices, never at the cost of paying late in law.",
    Params=Params, readback=_readback, evaluate=_evaluate, propose=_propose, optimizer=_optimizer, forecast=_forecast,
    law_links=gv.HELM_LAW_LINKS, disclaimer=gv.HELM_NOT_ADVICE, hold_code=CODE, still_holds=_still_holds,
    recommend=False,
    keywords=("gstr-2b", "gstr2b", "reported", "hold until", "supplier has not filed", "gst credit",
              "input tax credit", "itc", "not filed", "gstr-1"),
)
