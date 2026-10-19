# Changelog

_FlowPilot AI was renamed Servabo on 2026-10-16. Entries below that date keep the old name._

All notable changes to this project will be documented here.

## [Unreleased]

### Added — A green main, the GST Credit add-on, the monthly summary (Session H, 2026-10-19)

- **GST Credit add-on**: a Developer organization can buy the GST Credit lists (suppliers, invoices with IMS recommendations,
  decisions, export, reminders) for $49 a month for the whole organization, as the third add-on. Business and Enterprise
  include it through their plan. When it ends the page returns to the preview and every import, match and decision is kept.
  Offered on the GST page (and both ways on the trial), listed on Billing → Add-ons, named in the value receipt, and on the
  website's pricing page (a new Add-ons section) and `/gst-credit`. One migration (`h1a6_gst_credit_addon`); the Dodo setup
  now creates eight products.
- **Monthly summary email**: on the 1st of each month the owners of a paying organization get last month's value receipt,
  only when it found something, once per organization per month, with a "Monthly summary" switch (on by default). One
  migration (`h1a7_monthly_receipt_sends`), one worker job (`receipt.monthly`).

### Changed

- **GST matching is faster** (storing results with one `COPY`, suggestion lookups by supplier and day): matching 10,000 records
  against 10,000 invoices went from about 4.2 s to about 2.9 s on the build machine, because it took 11.48 s on CI and failed
  `main`. The budget did not move.
- **CI**: the frontend audit blocks on what ships (`npm audit --omit=dev`) and only reports build tools; every job runs on
  `ubuntu-24.04`; `checkout`, `setup-node`, `setup-python` on v7 and `upload-artifact` on v6 (Node.js 24).

### Fixed

- An add-on's checkout returned the customer to an empty address (F-530).

### Added — The value receipt (Session G, 2026-10-19)

- **Value receipt**: real figures from a customer's own documents, in rupees, shown where a purchase is decided and every
  month after: GST credit waiting on suppliers (and at risk under the 180-day rule, and claimable now), the Time machine's
  latest replay (confirmed, likely and potential kept apart), probable duplicate invoices, supplier bank-account changes,
  overcharges against purchase orders, and Helm's value held. Nothing is estimated, currencies and honesty classes are never
  added, zero is left out, and the sample company is never counted.
- **Where**: the trial banner's last three days (the headline), the "Your free trial has ended" dialog (a receipt card with
  links to the evidence), the plan page ("Your trial so far"), the Documents Overview ("Found this month", every plan), a
  one-page PDF ("Download as PDF"), and both trial emails. For owners, admins and the billing role; members see today's text.
- **API**: `GET /organizations/{org}/value-receipt?period=trial|month` and `.pdf`, kept ten minutes in Redis. No migration.

### Added — GST Credit (Session F, 2026-10-19)

- **GST credit**: import a GSTR-2B and see which input tax credit you can claim, which suppliers have not reported your
  invoices, what differs, and what to do in the GST portal's Invoice Management System; the 180-day exposure; an Excel
  export and a supplier reminder. Documents → GST credit. Every plan can import and see the six figures; Business and
  Enterprise get the lists, decisions, export and reminders. Recommendations, not tax advice.
- **Enterprise**: GST credit across every workspace (Organization → GST credit, all workspaces) and the `gst:read` API
  key scope. Migration `g1a1_gst_credit` adds five tables and the key scope.
- **Helm**: mandates "Pay within 180 days of the invoice date" (recommended, on in the sample company) and "Hold payment
  until the supplier has reported the invoice in GSTR-2B" (off by default); neither can make a payment late under the MSMED
  Act or the 180-day rule. A Guard check "GST credit secured" and a drafted request to suppliers who have not reported.
- **Reading**: the extraction prompt now asks a model for every field the product reads (F-524); the e-invoice QR code
  (IRN) is read during processing.
- **Website**: a `/gst-credit` page.

### Changed — FlowPilot AI is now Servabo (2026-10-16)

There are no customers yet, so every protocol identifier that carried the old name changes once,
now. Anything built against the old names (a webhook receiver, a script that holds an API key, a
DNS record) must use the new ones:

| What | Before | After |
|---|---|---|
| Outgoing webhook signature header | `X-FlowPilot-Signature` | `X-Servabo-Signature` |
| Outgoing webhook delivery headers | `X-FlowPilot-Delivery-Id`, `X-FlowPilot-Event-Type`, `X-FlowPilot-Attempt` | `X-Servabo-Delivery-Id`, `X-Servabo-Event-Type`, `X-Servabo-Attempt` |
| Outgoing User-Agent strings | `FlowPilot-Webhooks/1.0`, `FlowPilot-ERP/1`, `FlowPilot-ARCH26/1.0` | `Servabo-Webhooks/1.0`, `Servabo-ERP/1`, `Servabo-ARCH26/1.0` |
| Public API version header | `X-FlowPilot-API-Version` | `X-Servabo-API-Version` |
| Spend-limit and export response headers | `X-FlowPilot-Spend-Limit`, `-Spend-Period`, `-Spend-Resets-At`, `X-FlowPilot-Export-Truncated` | `X-Servabo-Spend-Limit`, `-Spend-Period`, `-Spend-Resets-At`, `X-Servabo-Export-Truncated` |
| Domain-verification TXT record value | `flowpilot-site-verification=…` | `servabo-site-verification=…` |
| Domain-verification TXT record name (subdomain form) | `_flowpilot.<domain>` | `_servabo.<domain>` |
| Custom-domain challenge record | `_flowpilot-challenge.<host>` | `_servabo-challenge.<host>` |
| Live-review WebSocket subprotocol | `flowpilot.review.v1` | `servabo.review.v1` |
| Refresh cookie | `flowpilot_refresh` | `servabo_refresh` (everyone signs in again once) |
| API key prefixes | `fp_live_…` / `fp_test_…` | `svb_live_…` / `svb_test_…` (re-create local keys) |
| Browser storage keys | `flowpilot_auth_session`, `flowpilot_ui_preferences`, `flowpilot_tenant_selection` | `servabo_auth_session`, `servabo_ui_preferences`, `servabo_tenant_selection` (theme and last workspace reset once) |
| Sovereign licence format | `flowpilot-licence/1` | `servabo-licence/1` |

### Removed — the old name is no longer read (Session B, 2026-10-18)

There are no installations from before the rename, so the one-release compatibility is gone.
**Operators must use the `SERVABO_*` setting names: the old `FLOWPILOT_*` names are no longer read**
(by the API, the worker, the scripts in `backend/scripts/` and `backend/deploy/bin/`). Also gone:

- API keys starting `fp_live_` / `fp_test_` (only `svb_live_` / `svb_test_` are keys);
- backups and local backup folders written under the old name (`flowpilot-<stamp>.fpbk`, `.flowpilot_*`);
- `--loop stripe` and the `worker-stripe` service role (use `--loop billing` and `worker-billing`);
- old display values rewritten to Servabo (`PROJECT_NAME=FlowPilot AI` now shows as written);
- the launchers' shim for Docker volumes named `flowpilot_*`.

The values that were once published as defaults (`flowpilot_default_*` peppers) stay refused by the
production guard for good.

### Changed — the local databases are published on this computer only (Session B, 2026-10-18)

`backend/docker-compose.yml` publishes Postgres (5432), Redis (6379) and MinIO (9000, console 9001)
on `127.0.0.1` instead of every network interface.

### Changed — Helm's Promise ledger updates incrementally (Session B, 2026-10-18)

A document change used to recompute the whole workspace's ledger (4.07 s at 10,000 documents, budget 1 s).
It now re-projects that document and what depends on it (0.70 s), and gives exactly what a full rebuild
gives. The nightly rebuild checks that, repairs a difference and raises an operator alert of the new kind
`HELM_LEDGER_DRIFT`. Migration `h1a5_helm_ledger_incremental` adds two bookkeeping tables
(`helm_ledger_state`, `helm_ledger_dirty`) and an index on `helm_promises.fulfilments`; a migration
`b1a1_pan_card_phrase` lets the Aadhaar / PAN card document pack recognise a real PAN card.

### Fixed — carried-over defects (Session B, 2026-10-18)

Batch operations (two dispatches or adds at once, archived batches, totals over every batch, packages of
erased documents, extra files in a package), TruthMesh (a deleted or erased document leaves the mesh and
its conflicts at once, a rebuild keeps people's decisions on links, the reason is audited, lighter read
models), document packs (whole-word phrases, one answer on a tie, a real audit trail), conversation
retention counted from the last message, a refused tenant refreshes the app, and every list endpoint
refuses an `offset` above 2,147,483,647 (422) instead of failing with a 500. FINDINGS.md F-469 to F-499.

### Planned

- Backend foundation
- Frontend foundation
- PostgreSQL integration
- Authentication
- Work Item processing
- AI pipeline
- Automation Engine
