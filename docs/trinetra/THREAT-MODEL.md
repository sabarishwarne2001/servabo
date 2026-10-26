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
| File bombs or fake official formats | No new binary parser. Canonical intake validation/size/virus/decompression controls apply. Unverified official parsing is explicitly refused. |
| Prompt injection | Deterministic arithmetic; no LLM or autonomous action is invoked by this module. Existing extraction stays untrusted until review. |
| Resource exhaustion | Plan-version capacities and hard ceilings; bounded rows/allocations/history; batched summary reads; debounced shared jobs. |
| Unexpected communication/payment | Inquiry is a draft only. No tax-portal credentials, sending endpoint, payment operation or return submission. |
| Data left after erasure | Existing data-map purge/export/retention machinery follows canonical and supporting source links, including comparison baselines and copied review history. No separate blobs. Backups follow platform retention. |
| Old encryption key retired prematurely | Both PAN and identity salt participate in the platform rotation sweep; tests remove the old key and check decryption and identity stability. |
| Chasing confirmed withholding as customer cash | Explicit agreeing advice/accounting review; Helm displays a separate annotation and holds gross reminders, including when evidence is stale or the feature is disabled. No automatic settlement mutation. |
| Inflated outcome claims | Closure requires a later source increase, unchanged expectation and current accountant review; allocations of unchanged evidence count zero. Time is self-reported effort, not savings. |

Database/server administrators and encryption-key custodians are trusted. Reviewers
can intentionally enter an inaccurate transcription; the product labels it as such,
records who reviewed it, and never turns it into independently verified tax advice.
Independent tax review, real-source testing and a focused penetration test remain
launch gates. This document is not an independent security certification.
