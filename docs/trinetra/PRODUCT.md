# TRINETRA: credit assurance

TRINETRA compares evidence about business TDS receivables. It does not calculate a
legal entitlement, recommend a rate, file a return, move money or promise recovery.
Live processing defaults off. Read [LAUNCH-GATES.md](LAUNCH-GATES.md) before a pilot.

## Reviewer workflow

1. Open TRINETRA in an authorized workspace. The initial view is a transient,
   read-only synthetic example; it creates no customer documents or tax records.
2. With live access enabled and a current Business/Enterprise entitlement, a
   workspace administrator creates a legal-entity profile. PAN is encrypted and
   displayed masked. Do not enter tax-portal credentials.
3. Upload evidence through Documents, using its existing validation, quotas,
   extraction, review and retention controls. Select an INR invoice whose seller
   matches the profile. Confirm the explicitly supported withholding expectation
   and give a reason. A bank shortfall alone is insufficient.
4. Transcribe a legally obtained statement into the reviewed rows form, check the
   source entity and April–March period, preview the scope, then import. This is
   **human transcription**, not a verified Form 26AS parser. Unverified official
   file layouts are refused. References are preserved; TAN is keyed, not displayed.
5. Inspect suggestions and source links. Allocate exact amounts to one or more
   postings with a reason. Several invoices can share a posting, but its total
   cannot be used twice. Suggestions never count as posted credit.
6. Record disputed, explained, withdrawn or accountant-reviewed outcomes. Assign
   the case to yourself, record priority, follow-up date and root cause, and attach
   advice/accounting/certificate/correction documents from the same workspace.
7. A later snapshot supersedes the selected view. Historical snapshots and review
   decisions remain. New evidence requires new allocations; old ones do not carry
   forward automatically. A changed invoice requires reconfirmation, which clears
   current allocations and records a revision. A changed statement is unavailable
   until a fresh transcription is confirmed.
8. Prepare a plain-text inquiry draft, or export CSV, XLSX and an HTML evidence
   dossier. Nothing sends an inquiry automatically. Use the existing document's
   discussion and secure-request workflow for collaboration.
9. Open **Compare source documents** for side-by-side canonical sources and review
   controls. Search or page through source documents when attaching evidence. Attach
   advice and accounting records separately, then explicitly confirm withholding for
   the receivable projection. Helm shows that amount separately and holds gross cash
   reminders. Changed evidence requires review; confirmation never marks an invoice paid.

## Meaning of the figures

| Figure | Meaning |
| --- | --- |
| Supported expected withholding | Current reviewed expectations, excluding withdrawn cases. Not a tax asset. |
| Allocated uploaded postings | Reviewed allocations in the current, unchanged uploaded statement. Not independently verified government data. |
| Possible credit gap | Positive expected-minus-allocated amount where current statement evidence exists, excluding explained/withdrawn cases. Unknowns are excluded, not zero-filled. |
| Unresolved cases | Cases without a fully allocated posting or an explicit explained/withdrawn outcome. |
| Deductor advice / accounting record | Separate amounts explicitly attached by a reviewer; neither becomes a posted statement amount. |
| Bank receipt | Canonical Helm matched receipt, available only under the viewer's Helm/book/workspace permissions. It never creates a TDS expectation. |
| Confirmed later gap closure | Current CA-reviewed closure against the immediately preceding import, with the same invoice version/expectation, capped by the increase in that deductor's uploaded postings. Not cumulative recovery. |
| Recorded review minutes | Optional whole minutes entered on each decision, summed as effort. Not measured time saved. |

Totals can cover several periods. The case filter narrows the queue; headline
figures retain the workspace scope. The import timestamp is an **evidence as-of**
timestamp, not a government filing timestamp. Case age is days since creation;
it does not assert a statutory deadline. Reviewer-time savings, tax refunds and
cash recovery are not measured or claimed.

## Synthetic walkthrough

The nine arithmetic scenarios use FY 2025–26 / AY 2026–27 and a 31 March 2026
statement timestamp: exact posted ₹2,000; partial posting ₹1,500 against ₹3,000;
disputed ₹1,800; no uploaded posting ₹2,400; a later ₹1,200 posting; suspected
deductor mismatch ₹900; ₹4,000 allocated from a shared ₹6,000 quarterly posting;
an unsupported source with an unknown gap; and a credit note requiring review.
The partial-remittance case shows ₹50,000 bank cash separately from withholding.
Sample case ages are measured at that fixed statement date, with matching creation
dates; they do not keep aging against the real calendar.
No section, tax rate or taxable basis is asserted. The examples still require
tax-adviser review before being described as law-reviewed.

## Permissions and packaging

Viewers read; workspace administrators write and export. API keys can read only
the scoped organization summary with `trinetra:read` and the Enterprise capability.
Free/Starter (the `developer` plan, N-187) get synthetic examples only. Business caps are 2 profiles, 12
retained snapshots and 500 retained cases per organization. Enterprise defaults
are 10/60/5,000. Published subscription versions supply the limits, with finite
platform ceilings. No prices, provider products or billing intervals change.
The proposed 50 outbound inquiries/month is not charged or consumed: outbound
TRINETRA sending is disabled. Canonical document processing still consumes its
existing document/OCR/storage allowances.

## Boundaries still requiring work

See [LAUNCH-GATES.md](LAUNCH-GATES.md). Official formats, TCS, automatic ERP
expectation derivation, signed/advance workflows and externally validated outcomes
remain gated. The present
surface is a gated reviewed-evidence workflow, not completion of all original
production acceptance criteria.
