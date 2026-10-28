# TRINETRA: credit assurance

TRINETRA compares evidence about business TDS receivables: **did the tax a customer withheld reach the business's tax statement?**
It does not calculate a legal entitlement, recommend a rate or a section, file a return, move money or promise recovery. It is
on **Business and Enterprise**, and ships in **pilot** mode: an organization is live only after a platform administrator enrolls
it. Read [LAUNCH-GATES.md](LAUNCH-GATES.md) before opening it to anyone. The person-facing guide is [USER-GUIDE.md](USER-GUIDE.md).

_Finished in Final session 2T (2026-10-28). The official statement readers are written but unverified until Final session 2B reads
a real file; everything else here is tested on synthetic data._

## Reviewer workflow

1. **See the examples.** Every plan can open TRINETRA to a transient, read-only synthetic example (nine scenarios, labelled). It
   creates no records. A Starter organization is told that live TDS credit comes with Business and Enterprise; a Business or
   Enterprise organization that is not yet enrolled is told it is in a pilot.
2. **Set up the legal entity.** A workspace administrator creates a profile: name and PAN (encrypted, shown masked). One legal entity has
   one profile per organization, even across workspaces (a clear message names the workspace that already holds it).
3. **Say where the customer's withholding comes from.** Three ways, none automatic: a figure printed on an invoice (a suggestion
   a person accepts), the *expected-TDS template* (for businesses whose books are in Tally: an accountant fills in invoice
   reference, customer TAN and amount), or a read-only look at Zoho Books. A person accepts each suggestion with a reason; if the
   seller's name on the invoice is spelled differently from the profile, the person must say they checked. A customer's TAN is
   mapped to the customer once, in the *deductor directory*, by a person. A bank shortfall alone never creates an expectation.
4. **Bring in the tax statement.** The Servabo template (CSV or Excel, typed from a statement the business holds), an AIS CSV (the
   person confirms which column means what), or the text download of Form 26AS or Form 168 (unverified readers until 2B). Every file
   is previewed first: rows read, total, the file's own tax-year label, checks against the file's own totals, each TAN masked. Nothing
   is saved until the person confirms the entity, year and amounts. PDF is not read. An unrecognised or ambiguous file is refused
   in words, naming the row or heading and never the content.
5. **Review each case.** Allocate exact amounts from statement rows to the case with a reason (several invoices may share a row;
   a row can't be used twice). Pair a reversal with the row it reverses. Record that the case is explained, disputed, withdrawn,
   reviewed by the accountant, or **closed without resolution**. Annotate or reject a suggested match. The drawer shows *why* each
   match was made: which keys agreed, which reader, which rule version.
6. **Ask the customer for the document.** Prepare a draft, edit it, approve it, and press **Send**. It goes only to a contact a
   person confirmed in Helm, once per case per week unless the person gives a reason, within the plan's monthly allowance. A reply
   attaches to the case as evidence and changes nothing else.
7. **Close with a second person (Enterprise).** An organization policy (amount, kinds of closure, approver role) makes a closure wait
   for a different person in that role. An approval is tied to the case revision it was asked for and goes stale if the case moves.
8. **Later statements.** A newer statement supersedes the active one; history and earlier decisions stay. New evidence needs new
   allocations. A changed invoice needs reconfirmation; a *touch* (a rename) is not a change, a replaced file is.
9. **Export.** CSV, XLSX and an HTML evidence dossier, with masked identifiers, snapshots, rule versions, history and a disclaimer.

## Meaning of the figures

| Figure | Meaning |
| --- | --- |
| Supported expected withholding | Current reviewed expectations, excluding withdrawn cases. Not a tax asset. |
| Allocated uploaded postings | Reviewed allocations in the current, unchanged statement. Not independently verified government data. |
| Possible credit gap | Expected minus allocated where current statement evidence exists, excluding explained, withdrawn and closed cases. Unknowns are excluded, not zero-filled. An **investigation item**, never a refund or an asset. |
| Unresolved cases | Cases without a fully allocated posting or an explicit closed outcome. |
| Deductor advice / accounting record | Separate amounts a reviewer attached; neither becomes a posted statement amount. |
| Bank receipt | The matched Helm receipt, under the viewer's own Helm permissions. Never creates an expectation. |
| TDS now visible in your statement | The closure ledger: one row per case and confirming statement, written when a case that was a gap is later confirmed against a statement that shows the tax. **Evidence the credit appears. Never cash, never a refund, never added to GST or cash figures.** |
| Recorded review minutes | Whole minutes a person entered on a decision, summed as effort. Not measured time saved. |

Totals can cover several tax years. The import timestamp is an **evidence as-of** date, not a filing date. Case age is days since
creation; no statutory deadline is asserted. "Due" in a notice means the case has been open for 30 days (a Servabo setting, not a legal date).

## Where it shows up (as with GST Credit and Helm)

Getting started (a step for workspace administrators), global search (by customer and invoice, never by PAN or TAN), notification
preferences ("TDS credit", on by default for owners and admins), the Monday line, the value receipt ("found" and "now visible", never
added), rule triggers and recipes (Business: *a gap is found*, *evidence went stale*, *a case closed*; the actions notify, assign, tag
or post to chat, **never send an inquiry**), Recoveries (kind *TDS credit*, outside every "found money" total), Helm (confirmed
withholding shown beside the commercial balance; gross reminders held), and for Enterprise the public events and read API, the
warehouse dataset, and the organization view per legal entity (each entity counted once).

## Permissions and packaging

| | Viewer / member | Workspace admin | Organization owner / admin |
|---|---|---|---|
| Read cases, statements, evidence | yes | yes | yes |
| Write (profiles, expectations, imports, decisions, inquiries) | no | yes | yes (if also a workspace admin) |
| Closure policy (Enterprise) | no | no | yes |
| Approve a closure (Enterprise) | no | no | the named role, never the requester |
| Pilot enrolment | no | no | no (platform administrator only) |

Starter (the `developer` plan, N-187) and trial organizations: synthetic examples only. **Business:** 2 profiles, 12 snapshots, 500
open cases, 50 inquiries a month. **Enterprise:** 10 profiles, 60 snapshots, 5,000 open cases, every Business feature plus the
organization view, approval chains, the closure ledger across workspaces, the read API and webhooks, the warehouse dataset.
Capacities count working figures (superseded snapshots and closed cases are kept, within a retention ceiling, but do not use up the
plan). No price, provider product or billing interval changed: `capability.trinetra` is bundled, not sold.

## What it will not do

No tax-portal login, scraping or CAPTCHA bypass; no filing; no autonomous sending; no advice on rates, sections or which credit to
claim; no TCS; no payroll TDS (Form 16); no statements from PDF; no promise of a refund or a guaranteed credit. A chartered accountant
decides what a business may claim. Product decisions made along the way are N-190 to N-209 in `docs/hardening/NEEDS-OWNER.md`.
