# Does Servabo already do "Evidence-to-Resolution"? (Final session 2A, Phase 0B)

_Written 2026-10-26 from a read of the code on `main` at `5600d9d`. Decision: **N-191** (`docs/hardening/NEEDS-OWNER.md`)._

**The idea (the owner's):** detect a money issue → establish the evidence → get someone to fix it → **verify** that it was fixed →
count the rupees once. The question is whether the product already does this, and if not, whether a thin layer on top of the existing
engines would earn money.

**How this was traced.** Each issue was followed through the code a finance person's click would run: the engine that raises it, the
table it is stored in, the screen that shows it (`frontend/src/App.tsx` routes), what a person can do next, what closes it, and whether
any figure counts its rupees. The click counts are read from the screens' code, not timed in a browser; Final session 2B and the first
pilot measure them for real (`PILOT-PLAYBOOK.md`).

## The seven issues, one by one

### 1. An invoice above its purchase order (price or quantity)

| Question | Today |
| --- | --- |
| Who detects it | Three-way matching (`procurement_matching/matcher.py`): a **procurement case** with line outcome `PRICE_VARIANCE` or a quantity outcome (Business). |
| Where the evidence is | The case page (`…/procurement/cases/:id`): PO, goods receipt and invoice lines side by side, the tolerance policy that fired. Good evidence. |
| Who owns it, what next | **No owner and no due date.** Cases are not in the review hub (`models/review.py` `REVIEW_KINDS` has no procurement kind). A person can approve, dispute or re-run; Helm can *hold* the invoice if a Helm mandate covers it. |
| What marks it done | A **click**: `APPROVED` or `DISPUTED` (`CASE_STATUS_*`). Nothing waits for a credit note. |
| Is the money counted | The value receipt counts the overcharge as **found** (`value_receipt._overcharges`). Helm's ledger counts `OVERCHARGE_RECOVERED` **only if Helm held the invoice** and a credit note or a re-read at or below the price followed (`helm/value.py`). A disputed case nobody followed up counts as found forever and recovered never. |
| Screens and clicks | Case list → case → approve/dispute: 2 screens, about 3 clicks. Following the supplier up is outside the product (email by hand) unless Helm is set up. |

### 2. A supplier statement that disagrees with our books

| Question | Today |
| --- | --- |
| Who detects it | Helm's library mandate 13 (`helm/mandates/library/supplier_statements.py`) runs `helm/reconcile.py` on each supplier statement document (Business, Helm set up). |
| Where the evidence is | The differences are explained line by line **inside the drafted email** (Helm's plan → the action). They are **not stored** as issues: re-running the reconciliation recomputes them. |
| Who owns it, what next | No owner, no due date. The next action is Helm's drafted reconciliation email, sent only in Act mode to a known contact. |
| What marks it done | **Nothing.** The next month's statement either agrees or produces a new draft. |
| Is the money counted | No. Not found, not recovered. |
| Screens and clicks | Helm → Plan → the action → approve the draft: 3 screens, about 4 clicks; then nothing to close. |

### 3. A payment deadline approaching (MSME 45 days, the GST 180-day rule, an obligation)

| Question | Today |
| --- | --- |
| Who detects it | Helm's ledger with the India pack (`helm/msme.py`; mandate `gst_180`), and the obligations engine (`services/obligations`, Business). |
| Where the evidence is | Helm's ledger (the promise and its due date, with the source line); an obligation's detail page with its clause. |
| Who owns it, what next | Obligations **have** an owner and a due date and are in the review hub (`REVIEW_KIND_OBLIGATION`). Helm's deadlines are planned payments (schedule, approve in Helm). |
| What marks it done | An obligation: a click ("fulfilled"). Helm: the payment record (a person's mark or a matched bank line), which is **evidence**. |
| Is the money counted | Helm's `LATE_FEE_AVOIDED` and `DISCOUNT_CAPTURED` count on the payment evidence, once, and are withdrawn when the payment record is undone. The 43B(h) deduction kept by paying an MSME on time is **not** counted (no supportable rupee figure without the tax rate). |
| Screens and clicks | Helm → Ledger or Plan → approve: 2 screens, about 3 clicks. The best of the seven. |

### 4. GST credit at risk: a supplier has not reported the invoice in GSTR-2B

| Question | Today |
| --- | --- |
| Who detects it | GST Credit (`gst/matching.py`): `WAITING_FOR_SUPPLIER`, with `itc_micros` (the credit at risk) and a `risk` block for the Section 16(4) time limit. |
| Where the evidence is | The GST page's invoice list: our invoice, the GSTR-2B periods searched, the supplier's filing pattern. Good evidence. |
| Who owns it, what next | **No owner and no due date per invoice** (the 16(4) date is shown as a risk, not as a task). Next actions exist: remind the supplier (`gst/reminder.py`), the IMS action, the Excel export, the Monday digest. |
| What marks it done | **Evidence, automatically**: a later GSTR-2B carrying the invoice turns it `MATCHED` and sets `reported_late = true`. This is the right rule, already built. |
| Is the money counted | Found: the digest and the value receipt show credit at risk. **Secured: nowhere.** When a late report rescues ₹40,000 of credit, no figure says so. |
| Screens and clicks | GST → invoices → filter "waiting" → remind: 2 screens, about 4 clicks per supplier. |

### 5. A duplicate invoice

| Question | Today |
| --- | --- |
| Who detects it | The forensic radar (`radar/`, `DUPLICATE_DOCUMENT` findings, Business). |
| Where the evidence is | The radar page and the review hub: both documents, the fingerprint layers that matched. Good evidence. |
| Who owns it, what next | **Yes**: anomalies are in the review hub with assignment (`REVIEW_KIND_ANOMALY`). Confirm or dismiss; Helm can hold the payment. |
| What marks it done | A **click** (confirm/dismiss). Helm's `DUPLICATE_BLOCKED` adds evidence: confirmed **and never paid**, only for invoices Helm held. |
| Is the money counted | Found: the value receipt (`_duplicates`). Recovered: only through Helm's ledger. A duplicate confirmed outside Helm and then not paid is never counted as saved. |
| Screens and clicks | Review hub → item → confirm: 2 screens, about 3 clicks. |

### 6. A changed supplier bank account

| Question | Today |
| --- | --- |
| Who detects it | Payment risk (`radar/payment_risk.py`, `PaymentRiskFlag` kind `BANK_ACCOUNT_CHANGED`); Helm opens a `VERIFY_BANK_ACCOUNT` task. |
| Where the evidence is | The flag (old and new account, masked, the document that changed it) and Helm's task. |
| Who owns it, what next | Helm tasks are in the review hub (`REVIEW_KIND_HELM`) with assignment; the flag itself is confirm/dismiss. |
| What marks it done | A **click**, which is right here: the evidence is a phone call to a known number, which the product cannot see. |
| Is the money counted | No, and it should not be: there is no supportable rupee figure for a fraud that did not happen. The value receipt lists it as a count. |
| Screens and clicks | Review hub → task → verified: 2 screens, about 3 clicks. |

### 7. TDS a customer withheld that the uploaded statement does not show (TRINETRA, the reference design)

TRINETRA (`services/trinetra/`, flag on in the test stack only) already has the pattern for one kind of money: each **case** has an
owner, a priority, a due date and a root cause (the `review` block of `trinetra_credits`); evidence is attached by id
(`evidence_work_item_ids`); every decision is **reasoned and versioned** (`trinetra_decisions`: action, reason, revision, allocations,
review minutes); an independent accountant's review exists; and a gap is "closed later" **only on new statement evidence**.

**What the other six would need to work the same way:** an owner and a due date on every issue; closure that only evidence can grant,
with a recorded "not money: reason" for the rest; one place that counts the outcome once.

**What should not be copied:**
- **Its own copy of the facts.** TRINETRA keeps its own tables because there was no engine for TDS. For the other six the engines
  already hold the facts; a second store would drift (the reason the review hub is a view, `review/projection.py`).
- **"Current" by a row's `updated_at`** (the 2026-10-26 review, finding 2): closure must key on the evidence itself.
- **Capacities that count every case ever made** (finding 4): a resolution list must not run out.
- **Per-invoice reasoned decisions for every issue.** Right for tax evidence an accountant signs; too heavy for a duplicate or a GST
  late report, where the evidence closes the issue by itself.

## The decision against the four tests

| Test | Result |
| --- | --- |
| **(a)** At least three of the first six have no evidence-based closure, or no single place with an owner and a due date | **Holds.** Issues 1 (click closure, no owner), 2 (nothing stored, nothing closes) and 4 (evidence closure exists but no owner, no due date and no "secured" count) fail outright; 5 counts recovered money only through Helm. Only 3 and 6 are in reasonable shape. |
| **(b)** The build reuses existing detection and stores: a read model, closure rules and one outcome ledger; no new detection engine, no new AI | **Holds.** Every kind's detection and its rupee figure are already stored: `gst_matches.itc_micros` and `reported_late`, procurement case lines' variance, radar findings, Helm's value events. A projection over them (the review hub's pattern), an assignment row and an outcome ledger extending Helm's `helm_value_events` idea are enough. Issue 2 is the exception: its differences are not stored, so it joins only when Helm stores them (not in this build). |
| **(c)** It fits in about 35% of this session | **Holds for a thin first cut, after the must-haves.** Read model over three kinds (GST credit at risk, duplicate, price above the order) plus Helm's existing outcomes; owner and due date; closure rules; the outcome ledger; one page; the receipt line. The session's cut line (Phases 1 to 3 and 8 first) still governs: if usage is tight, the build waits and this assessment stands. |
| **(d)** It produces a "Recovered, verified" number a customer can check line by line | **Holds.** `ITC_SECURED` (an invoice that was waiting turns up in a later GSTR-2B: the credit amount, the GSTR-2B period as evidence), Helm's `OVERCHARGE_RECOVERED` and `DUPLICATE_BLOCKED`. Each line names its document and its evidence. |

**Decision (N-191): build a thin layer**, named **"Recoveries"** (Found → Being fixed → Verified), as Phase 6, after Phases 1 to 3.
The prediction from the code read ("build a thin layer") is **confirmed**, with two corrections:

1. **Supplier statement differences are left out of the first cut.** They are not stored anywhere today; storing them is Helm work,
   not a read model. They are listed as the next kind.
2. **Changed bank accounts are left out on purpose.** They are not money that can be counted, and their closure is rightly a person's
   call after a phone check. They stay in the review hub.

**What it must never do:** move money, approve, pay or release a hold (Phase 3 invariant (a)); count a "not money" close as recovered;
add "Found" and "Recovered, verified" together; count an outcome Helm already records a second time.

**If it is not reached in this session**, Final session 2B measures, during the first pilot, how many issues of kinds 1, 4 and 5 were
followed up, by whom, and how many were provably closed (`PILOT-PLAYBOOK.md`, "What to measure").

## Status at the end of Final session 2A: decided, not built yet

The decision (N-191) stands: build the thin **Recoveries** layer. It was **not built in this session.** The session prompt's
cut line put Phases 1, 2, 3 and 8 first and allowed Phase 6 to be skipped if usage was tight after Phase 5; it was (the
session hit its usage limit once), and the security fixes of Phase 3 took priority. Nothing of it is half-built in the code.

**The build, when it comes** (unchanged from the prompt's Phase 6): one read model over the engines' own tables, like the
review hub; Found → Being fixed → Verified; each issue with its stored rupee figure, evidence, owner, due date and the
existing next actions; closure only on evidence, one rule per kind, and "Not money: <reason>" never counted; one outcome
ledger extending Helm's value ledger, with a test for every pair of engines that could claim the same outcome; Business and
Enterprise; TRINETRA's cases joining through one adapter in 2T.

**What Final session 2B (and the first pilots) should measure about today's flow meanwhile**, so the build starts from
real numbers:

- **GST credit at risk:** how many invoices are on the list at day 7 and still on it at day 30, and how many the customer
  chased (a reminder sent, a supplier call). The gap between "found" and "chased" is what an owner and a due date would close.
- **Prices above the order:** how many procurement cases opened, how many a person disputed, and how many ended with a
  credit note. Today a dispute is a click with no evidence of the outcome.
- **Duplicates:** how many Helm held, and how many were confirmed and never paid (Helm already counts these).
- **Who looked:** for each kind, whether anyone opened the engine's page in the month (the audit trail shows it). If nobody
  did, the layer's first job is to put the issue in front of a person.

These go in the pilot notes (docs/product/PILOT-PLAYBOOK.md, the weekly check-in) and in 2B's LIVE-VERIFICATION.md.

