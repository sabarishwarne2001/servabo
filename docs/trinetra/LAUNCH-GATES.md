# TRINETRA launch gates

_Updated in Final session 2T (2026-10-28). The order is fixed: **2T** finished the product in code and tests; **2B** proves what only a
real file or service can prove; then the owner's chartered accountant reads the wording; then the owner sets the mode to "on"._

**Release status: finished in code and tests, in pilot mode; not approved for open release.**
`TRINETRA_MODE=pilot` is the default in code, the examples and the production compose: an organization is live only when a platform
administrator enrolls it (`/admin/trinetra/pilot`, with a reason, audited). Do not set `on` merely because the tests pass.
`TRINETRA_LIVE_ENABLED` is the old on/off setting, kept as an alias that wins when it is set; leave it unset.

## What is proven, and what only a real file or service can prove

| Claim | Proven by | Still needed |
|---|---|---|
| Arithmetic, scoping, versions, approvals, notices, isolation, privacy, limits | Backend tests, synthetic data (`TEST-PLAN.md`) | Nothing, except the finish-line runs |
| The template and AIS readers read what a person typed or exported | Synthetic fixtures; the AIS columns are confirmed by the person in a mapping preview | 2B: the owner's own AIS CSV |
| **The Form 26AS and Form 168 readers read a real download** | **Nothing.** Written from secondary sources (the official hosts were unreachable); registered unverified | **2B: the owner's own Form 26AS / Form 168 text**, never put in the repository or a chat |
| The Zoho Books read finds invoices with TDS | A mocked Zoho (`test_zoho_tds.py`) | 2B: the owner's real Zoho Books organization, read-only |
| An inquiry reaches a real inbox and the secure link works | Tests with a mail catcher | 2B: one real send to the owner's own address |
| A real case end to end (invoice, bank, advice, statement, review) | Synthetic browser specs 136 and 141 to 144 | 2B: the owner's own data, in pilot mode |
| The wording is acceptable to a tax professional | Not claimed | The owner's chartered accountant reads `/trinetra` and the in-app text for about an hour |

## The owner's gates

1. **Final session 2B** (`docs/sessions/FINAL-2-LIVE.md`, TRINETRA phase) marks each COMPLETION row "Verified in 2B" or "Differs"
   and fixes or records every difference. A reader that differs stays `unverified` (and refusing) until it is fixed.
2. **The accountant's read.** Give the accountant the website's `/trinetra` page, `docs/trinetra/USER-GUIDE.md` and a login to a
   pilot organization. They check the words "possible gap", "TDS now visible in your statement", "expected deduction", the examples,
   the disclaimer on every export, and that nothing reads as advice on a rate, a section or a claim. Wording changes are code changes
   in `frontend/src/pages/trinetra/model.ts` and the website; a session makes them.
3. **Open the pilot to a named customer.** `PUT /admin/trinetra/pilot/{organization_id}` with a reason (the exact command is in RUNBOOK, "TRINETRA";
   `scripts/preflight.py` shows how many are enrolled). Confirm data residency and retention with that customer's owner.
4. **Open it to every Business and Enterprise organization.** Set `TRINETRA_MODE=on`, restart the API and the workers, run
   `preflight.py` (it must say the mode is on and name the readers still unverified, if any), and set the website's
   `PUBLIC_TRINETRA_STATUS=available` and rebuild. Until then the website says "rolling out". This is HANDOFF's launch checklist, step 13.
5. **Rolling back:** set `TRINETRA_MODE=pilot` (or `off`) and restart. Recorded withholding keeps holding Helm's reminders in every
   mode, so a customer is never chased for tax a customer already withheld; export dossiers first if a migration is to be reversed.

## Bounded claims (the website, the app and the sales conversation)

Servabo may say: it **checks whether the tax your customers withheld reached your tax statement**, shows what is missing as
**things to investigate**, keeps the evidence and the history, and shows "TDS now visible in your statement" when a later statement
contains a credit that was missing. Servabo must not say: that it recovers or refunds money, that a credit is guaranteed or allowed,
that it is connected to the government, TRACES or the e-filing portal, that it files anything, that it gives tax advice, or that a
gap means anyone did something wrong. A chartered accountant decides what a business may claim.

## Deployment checklist

1. Back up and restore-test the database; retain an evidence export for rollback.
2. Apply `alembic upgrade head`; confirm exactly one head (`tr2t10_recoveries_tds_kind` at the end of 2T) and no migration drift.
3. Publish the additive tier versions through the existing publisher (dry run first; existing subscriptions keep their pins and
   the reviewed carry-forward applies). Business grants `capability.trinetra`; Enterprise also `capability.trinetra_all_workspaces`;
   the capacities are Business 2 profiles, 12 snapshots, 500 cases, 50 inquiries a month and Enterprise 10, 60, 5,000.
   `docs/hardening/TENANCY-AND-PLANS.md` and the website's `pricing.json` are generated from the same seed.
4. Retain valid platform encryption keys and test rotation (both PAN and identity-salt columns, and the per-organization salt, are in
   the sweep). Restart the API and the workers on the same revision; `trinetra.sweep` runs hourly and says each thing once.
5. Keep `TRINETRA_MODE=pilot`. Enrol the first organization only after gates 1 and 2.
6. Check the jobs console for `trinetra.recompute` and `trinetra.sweep`, the stale-source banner, export audit events, and the
   compliance export and erasure in staging.
7. Before rollback, export dossiers. `tr2t4` deletes file-sourced snapshots on downgrade, `tr2t6` the pairings and closes UNRESOLVED
   cases as EXPLAINED, `tr2t7` the inquiries, policies, approvals and closure ledger, `tr2t10` the Recoveries issues of kind TDS credit.
   `tr1a1` and `tr1a2` remove the original tables. Each migration's docstring says what is lost.

No production deployment, provider product creation, real email, government filing or payment was performed during implementation.
Validation evidence belongs in [TEST-PLAN.md](TEST-PLAN.md), including failures and untested items.
