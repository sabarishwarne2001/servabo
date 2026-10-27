# Recoveries: the money Servabo found, followed until it is recovered

_Built in Final session 2A (decision N-191; the assessment is `RESOLUTION-ASSESSMENT.md`). Business and Enterprise; every
other plan sees the counts and what was found, as a preview._

**What it is.** One page per workspace (Documents → Recoveries) with three columns: **Found → Being fixed → Verified**. Every
money issue Servabo's engines find lands in **Found**, with its amount, its due date and the evidence. Someone takes it
(**Being fixed**). It moves to **Verified** only when evidence shows the money came back or the deadline was met. A click
never verifies anything.

**What it is not.** A new engine: every issue comes from an engine that already exists (GST Credit, the radar, three-way
matching, Helm). Nothing on the page moves money, approves, pays or releases a hold: the next steps are links to the pages
where a person does that.

## The five kinds

| Kind | Where it comes from | Amount at stake (the engine's own figure) | Due date | Verified when (evidence) | Counted as |
| --- | --- | --- | --- | --- | --- |
| **GST credit waiting on a supplier** | GST Credit: an invoice in the books that no imported GSTR-2B carries | the invoice's input tax credit | Section 16(4): 30 November after the financial year | a later GSTR-2B carries it; or a credit note cancels the invoice in full (verified, nothing counted) | GST credit secured |
| **Probable duplicate** | the radar's duplicate finding | the duplicate's total | the invoice's due date in Helm, if any | the finding is confirmed **and** Helm's ledger shows it unpaid | Duplicate payment blocked |
| **Price above the purchase order** | three-way matching (price variance) | the sum of the price differences | the invoice's due date in Helm, if any | a credit note against the invoice (up to what was found); or the invoice re-read at or below the order price | Overcharge recovered |
| **Supplier statement difference** | Helm's reconciliation of a supplier's statement (now kept as issues) | the difference's effect on the balance | none (a person may set one) | the supplier's next statement no longer shows it | not counted: resolved, not recovered |
| **Payment deadline** | Helm's ledger: the MSME 45-day limit, the GST 180-day rule, a late fee the terms state | the amount due; the GST credit that would be reversed; the fee | the legal or stated deadline | the payment is recorded (by a person or a bank statement line) on or before the deadline | the late fee avoided (the other two are verified without a figure) |

**Closed without money.** A person may close an issue as **"Not money: <reason>"** (for a statement difference:
**"Explained: <reason>"**), at least ten characters, recorded and never counted; it can be reopened. An engine's own
dismissal does the same (a duplicate dismissed in review). An issue the engine stops reporting without evidence of a fix
is **Closed** (for example an invoice paid after its deadline, or an order changed to match the invoice). Neither is
ever counted.

**Undone evidence.** If the evidence goes away (the GSTR-2B that carried the invoice is removed, the duplicate is paid
after all, the payment record is undone), the outcome is withdrawn and the issue reopens.

## Counting once

The outcomes Recoveries proves live in one ledger that shares Helm's keys (the kind of outcome and the document). An
outcome Helm already recorded is not recorded again; one both could claim is counted once; a blocked duplicate is never
also counted as an overcharge recovered on the same invoice. Amounts in different currencies are never added.

**"Found" and "Recovered, verified" are never added together.** They are two figures, side by side, on the page, on the
value receipt and in the monthly summary. On a plan with Recoveries, the receipt's evidence-backed line is "Recovered,
verified": Helm's own outcomes (a discount captured, a late fee avoided) are counted in it too, once, so the same rupee is
never shown on two lines.

## Who does what

| Who | Can |
| --- | --- |
| A viewer | read the page and every issue |
| A contributor, an admin, an organization owner or admin | give an issue an owner (anyone who can open the workspace), set a due date where the law and the terms give none, close as not money, reopen, "Check now" |

Every person's action is in the audit log (review item, kind RECOVERY).

## When it updates

Opening the page brings it up to date with the engines that are quick to read. Every hour, `recoveries.sweep` queues one
small job per workspace that re-reads all of them, supplier statements included (one job per workspace, so a customer's
documents never wait behind the whole sweep); **Check now** does the same at once.

## Where else it shows

- **The value receipt and the monthly summary:** "Recovered, verified" beside what was found.
- **The GST digest (Mondays):** "3 money issues worth ₹2,40,000 need an owner", linking to the page.
- **Getting started:** the money step links here ("Follow it in Recoveries").

## For engineers

`backend/app/services/recoveries/` (one adapter per kind in `adapters.py`; the sweep and a person's actions in
`service.py`; the outcome ledger in `ledger.py`), `app/api/v1/recoveries.py`, migration `s2a4_recoveries`,
`frontend/src/pages/recoveries/`. A new kind is one adapter (and its name in the kinds check of `recovery_issues`, a small migration): Final session 2T adds TRINETRA's "TDS not yet in the
statement" (a possible credit gap, never cash) this way. Tests: `backend/tests/api/test_recoveries.py`, browser spec 140.
