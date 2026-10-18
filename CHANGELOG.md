# Changelog

_FlowPilot AI was renamed Servabo on 2026-10-16. Entries below that date keep the old name._

All notable changes to this project will be documented here.

## [Unreleased]

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
