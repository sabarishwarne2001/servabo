# TRINETRA threat model

## Assets and boundaries

Confidential assets: PAN/TAN, source tax documents, customer invoices, bank evidence,
allocations and human review history. Boundaries: browser → authenticated workspace
API; API → scoped PostgreSQL; existing document intake → canonical evidence; queue →
worker; reviewer → export; optional canonical document discussion/request service.
Tax portals and customer email destinations are outside TRINETRA's processing path.

| Threat | Control and residual limitation |
| --- | --- |
| Guessed tenant/workspace/entity IDs | Standard context/role dependencies, scoped source lookups and composite FKs. Organization reporting filters readable workspaces before computation. |
| Viewer/API key privilege escalation | Workspace writes/exports require ADMIN; keys only reach the explicit Enterprise summary scope. |
| Processing after downgrade/archive | Request capability and subscription checks plus independent worker gates. Synthetic examples remain read-only. |
| Mixing entity/year/TAN | Explicit profile/year on evidence; keyed TAN equality; profile identity confirmation; allocation scope equality. Names alone never confirm a posting. |
| Duplicate tax credit | Profile locks, revision conflicts and conserved many-to-many allocation amounts. |
| Stale approved evidence | Canonical source fingerprints, immutable snapshot revisions and explicit reconfirmation. Source edits cannot silently retain a current credit figure. |
| PAN/TAN leakage | Platform encryption, random encrypted identity salt, HMAC fingerprints, masked profile responses, no identifiers in URLs or telemetry. User-written review notes are confidential content. |
| Formula or HTML injection | GST's spreadsheet neutralization, HTML escaping, attachment downloads and a sandboxed no-script export CSP. React renders source text as text. |
| File bombs, hostile spreadsheets or fake official formats | Statement readers are the Servabo template (CSV/XLSX) and the AIS CSV: size and row ceilings before parsing, an XLSX is read cell by cell without formulas or macros, a formula-looking cell is kept as text, and every refusal names the row or heading, never the content. A hostile corpus (oversized, zip-bomb shaped, BOM and delimiter tricks, NUL bytes, formula cells, a thousand columns, mixed encodings) is run through every reader and template in `tests/trinetra/test_hostile_files.py`. The official Form 26AS / Form 168 readers are registered as **unverified** and refuse every upload until a real file is read in Final 2B. No PDF is read as a statement. The platform has no malware scanner (N-017); these checks are not an antivirus guarantee. |
| Prompt injection | Arithmetic is deterministic. A TDS amount, TAN or section printed on a document is only a labelled, masked hint (invariant (f), `docs/hardening/PROMPT-INJECTION.md`); no worker, rule, agent or Helm path writes a TRINETRA row, and every writing route needs a named person. Text from a statement, a document or a reply is rendered as text, never as an instruction, and a reply that says "mark confirmed" attaches as evidence only. Tests: `tests/security/test_prompt_injection_tds_hints.py`, `test_prompt_injection_trinetra_paths.py`. |
| Resource exhaustion | Plan-version capacities and hard ceilings; bounded rows/allocations/history; batched summary reads; debounced shared jobs. |
| Unexpected communication/payment | An inquiry to a deductor is a draft until **a person presses Send**: a draft needs a person's approval, the recipient is a confirmed contact (never a guess), there is one per case per week unless a person records a reason, and a plan allowance caps the month. A failed mail is a failed inquiry with its upload link revoked. Nothing is sent by a job, rule or webhook. No tax-portal credential, scraping, payment operation or return submission exists. |
| Data left after erasure | Existing data-map purge/export/retention machinery follows canonical and supporting source links, including comparison baselines and copied review history. No separate blobs. Backups follow platform retention. |
| Old encryption key retired prematurely | Both PAN and identity salt participate in the platform rotation sweep; tests remove the old key and check decryption and identity stability. |
| Chasing confirmed withholding as customer cash | Explicit agreeing advice/accounting review; Helm displays a separate annotation and holds gross reminders, including when evidence is stale or the feature is disabled. No automatic settlement mutation. |
| Inflated outcome claims | Closure requires a later source increase, unchanged expectation and current accountant review; allocations of unchanged evidence count zero. Time is self-reported effort, not savings. |
| Approvals bypassed or self-approved (Enterprise) | An organization policy (threshold, actions, approver role) turns a decision into a pending request; the requester cannot approve their own request; an approval is tied to the case revision and amount it was asked for and goes stale if either changes; approving needs the named role. Tests: `tests/trinetra/test_resolution.py`, isolation sweep. |
| Cross-organization reads through the new routes | Every workspace and organization route is swept with real ids by a stranger, a user with no organization and another organization's own ids (`tests/trinetra/test_isolation_sweep.py`); the sweep reads the routes from OpenAPI, so a new route fails the build until covered. Platform-admin routes refuse even an organization owner. |
| Integrations leaking PAN/TAN or counterparties | Notices, the Monday line, rule triggers, Enterprise webhooks, Recoveries, value receipt, search and the warehouse dataset carry masked identifiers and case references only; one journey is run with every log record captured and every place searched for the unmasked identifiers (`tests/trinetra/test_privacy.py`). The error tracker scrubs TAN patterns as well as PAN. |
| Noisy or repeated notices | A claim ledger (`trinetra_notice_sends`) allows one notice per organization, kind and key; a bundle replaces many; nothing is sent when nothing is open. |
| Treating "TDS now visible" as money | The closure ledger and value receipt say "visible in the statement", never cash or refund; a gap is an investigation item, not an asset (bounded claims on the website and in the app). |
| Slow or exhausted summaries | Measured budgets at the 5,000-case limit and 100 workspaces (`docs/hardening/PERFORMANCE.md`); indexes in memory, not a scan per case. |

Database/server administrators and encryption-key custodians are trusted. Reviewers
can intentionally enter an inaccurate transcription; the product labels it as such,
records who reviewed it, and never turns it into independently verified tax advice.
Independent tax review, real-source testing and a focused penetration test remain
launch gates. This document is not an independent security certification.
