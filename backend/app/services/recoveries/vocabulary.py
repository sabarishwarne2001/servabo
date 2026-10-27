"""Recoveries' fixed vocabulary (Final session 2A, Phase 6; N-191): the kinds, the states and the outcomes.

A money issue is Found (an engine raised it), Being fixed (a person owns it, or the engine shows someone acting) or
Verified (evidence closed it). A person may close it as Not money (with a reason; never counted), and an issue the engine
stops reporting without evidence of a fix is Closed (never counted).
"""

from __future__ import annotations

from typing import Final

GST_CREDIT: Final = "GST_CREDIT"                       # an invoice whose GST credit waits on the supplier's GSTR-1
DUPLICATE: Final = "DUPLICATE"                         # a probable duplicate invoice (the radar)
OVERCHARGE: Final = "OVERCHARGE"                       # an invoice priced above its purchase order
STATEMENT_DIFFERENCE: Final = "STATEMENT_DIFFERENCE"   # a supplier statement that disagrees with our books (Helm)
PAYMENT_DEADLINE: Final = "PAYMENT_DEADLINE"           # a legal or stated payment deadline (MSME 45 days, GST 180, a fee)
KINDS: Final = (GST_CREDIT, DUPLICATE, OVERCHARGE, STATEMENT_DIFFERENCE, PAYMENT_DEADLINE)

KIND_LABELS: Final = {
    GST_CREDIT: "GST credit waiting on a supplier",
    DUPLICATE: "Probable duplicate invoice",
    OVERCHARGE: "Price above the purchase order",
    STATEMENT_DIFFERENCE: "Supplier statement difference",
    PAYMENT_DEADLINE: "Payment deadline",
}

FOUND: Final = "FOUND"
BEING_FIXED: Final = "BEING_FIXED"
VERIFIED: Final = "VERIFIED"
NOT_MONEY: Final = "NOT_MONEY"
CLOSED: Final = "CLOSED"
STATES: Final = (FOUND, BEING_FIXED, VERIFIED, NOT_MONEY, CLOSED)
OPEN_STATES: Final = (FOUND, BEING_FIXED)
DONE_STATES: Final = (VERIFIED, NOT_MONEY, CLOSED)

ITC_SECURED: Final = "ITC_SECURED"
OVERCHARGE_RECOVERED: Final = "OVERCHARGE_RECOVERED"   # the same words as Helm's value ledger
DUPLICATE_BLOCKED: Final = "DUPLICATE_BLOCKED"
LATE_FEE_AVOIDED: Final = "LATE_FEE_AVOIDED"
CATEGORIES: Final = (ITC_SECURED, OVERCHARGE_RECOVERED, DUPLICATE_BLOCKED, LATE_FEE_AVOIDED)

#: A reason a person gives for "Not money" (or, for a statement difference, "Explained") is at least this long.
MIN_REASON: Final = 10
#: A payment deadline becomes an issue this many days before it (and stays one when it has passed unpaid).
DEADLINE_LOOKAHEAD_DAYS: Final = 30
#: Statements dated within this many days are reconciled (Helm's mandate uses the same window by default).
STATEMENT_LOOKBACK_DAYS: Final = 120
