# TRINETRA validation

This file distinguishes implemented tests from their executed results. The PR's
checks report the final head; green automated runs are not production or legal approval.

## Automated coverage

- `backend/tests/trinetra/test_domain.py`: exact paise, signed/unsupported values,
  old/new period boundary labels, scope/TAN isolation, many-to-many conservation,
  ambiguous suggestions, unknown evidence and superseded allocations.
- `test_api.py`: encrypted/masked profiles, sample isolation, plan/launch gates,
  duplicate imports, stale decisions, superseding snapshots and JWT-key rotation.
- `test_workflows.py`: source correction/reconfirmation, stale statement handling,
  source identity/currency/gross guards, hostile exports, distinct advice/book amounts,
  case ownership, pinned caps, tenant IDOR, worker status and source erasure.
- `test_controls.py`: independent-session concurrent allocations, worker replay,
  summary query bound, canonical role invalidation, API-key restrictions and a
  populated downgrade/upgrade preserving canonical workspaces.
- Frontend exact-money tests cover values beyond JavaScript's safe integer range.
  The route is registered in the existing accessibility/phone sweep catalogue.
- `frontend/e2e/tests/135-trinetra.spec.ts`: real API sample flows for Developer,
  Business, Enterprise and viewer; search/selection; direct write denial; keyboard,
  light/dark axe and 390/768/1440 widths under the production CSP.
- **Final session 2T** (`backend/tests/trinetra/` unless a path is given; every failing test was written before its fix):
  - `test_modes.py` (off / pilot / on, the old alias, enrolment audit), `test_capacities.py` (working-set counts, retention ceiling,
    inquiry allowance), `test_one_entity_one_profile.py`, `test_seller_check.py`, `test_write_forms_match_the_server.py`,
    `test_lifecycle_rule.py`, `test_versions.py` and `test_evidence_lifecycle.py` ("changed" means the evidence changed),
    `test_version_migration.py` (populated up/down/up of the fingerprint conversion).
  - `test_statement_readers.py`, `test_statement_files.py` (template, AIS with the mapping choice, Form 26AS/168, every refusal),
    `test_hostile_files.py` (a corpus of hostile files run through every reader and template: oversized, zip-bomb shaped,
    NULs, formula cells, a thousand columns, mixed encodings), fixtures in `backend/tests/fixtures/trinetra/` (synthetic).
  - `test_suggestions.py`, `test_zoho_tds.py` (expectations accepted only by a person; read-only Zoho), `test_money_model.py`
    (credit notes, reversals and pairings, advances, triggering events, late and duplicate postings, UNRESOLVED),
    `test_explain.py`, `test_resolution.py` (authorized inquiries, approval chains, closure ledger, measured time),
    `test_outcomes.py`, `test_helm_adapter.py`.
  - `test_notices.py`, `test_case_events.py`, `test_integrations.py`, `test_warehouse_dataset.py`, `test_tds_recoveries.py`
    (Getting started, search, notices and the Monday line, value receipt, rules and webhooks, organization view, holds and egress).
  - `test_case_list_batches.py` (queries do not grow with cases; the batched list equals the one-case path),
    `test_privacy.py` (one whole journey with every log captured: no PAN or TAN anywhere), `test_isolation_sweep.py` (every
    TRINETRA route, read from OpenAPI, by a stranger, a user with no organization and another organization's own ids; the
    sweep fails if a new route is not covered).
  - `backend/tests/performance/test_trinetra_budgets.py` (5,000 cases, a 5,000-row import, 100 workspaces; 5 s each),
    `backend/tests/security/test_prompt_injection_tds_hints.py` and `test_prompt_injection_trinetra_paths.py` (invariant (f) and the
    new paths in `docs/hardening/PROMPT-INJECTION.md`), `backend/tests/infra/test_error_tracking.py` (TAN pattern),
    `backend/tests/services/helm/test_withholding_hold.py`.
  - Browser specs from 141 (`frontend/e2e/tests/`): **141** access by plan and by pilot enrolment (Starter, a Business
    organization before and after enrolment, the operator-only console); **142** owner, workspace administrator and viewer on
    Enterprise and the owner on Business, with the server asked too; **143** statement import (template, AIS mapping, official readers
    shown unverified), suggestions from a filled template accepted by a person, an inquiry draft that cannot be sent without a
    confirmed contact; **144** the Enterprise approval chain, the organization view per legal entity, axe in light and dark on every
    tab and at 390 px. Spec 136 now enrols its own organization in the pilot.

## Required execution

Use the existing PostgreSQL/Redis fixtures. Only one pytest process may use the
same test database; the fixture recreates it. Run from `backend/`, so local `.env`
configuration resolves. Never point this fixture at customer data.

```sh
pytest tests/trinetra -q
pytest -q
alembic heads
python scripts/check_migration_drift.py
```

Frontend: `npm run test:unit`, `npm run lint`, `npm run check:self`, `npm run build`,
contract verification and Playwright. Website: typecheck/build, links, HTML, axe,
and shipped-dependency audit. Preserve logs outside tracked source and report exact
counts/failures. Browser runs use synthetic data and local integration stand-ins;
they do not validate real OCR/model quality, real tax exports or payment providers.

## Executed validation, 26 October 2026 (PR #40; history)

| Check | Observed result |
| --- | --- |
| TRINETRA plus compliance data-map registry | 326 passed; includes supporting-source erasure/retention and populated downgrade/upgrade. |
| Final TRINETRA plus all-route isolation rerun | 77 passed in 104.29 s. Organization disabled-gate regression failed first (503), then passed with the shared structured 409 prerequisite response. |
| Synthetic date consistency and API regressions | 31 passed in 23.91 s after reproducing and correcting creation-date/sample-age disagreement. Amounts and period labels are unchanged. |
| TRINETRA, structural/locking/key-rotation/extraction checks and two engine suites | 153 passed; two engine sweeps stopped at an unconfigured local SMTP relay. Both were rerun with the declared test relay below. |
| Those engine suites plus existing Helm service regressions | 402 passed. |
| Image dependency contracts and extraction contracts after security upgrades | 56 passed; `pip check` found no broken requirements. |
| Existing document console counts/filter contracts | 7 passed. |
| Frontend units | 291 passed in 19 files. |
| Frontend build, lint, self-check, generated API contracts | Passed; 12 API contracts agree with the running server. |
| Sample browser workflow, plan matrix, responsiveness, light/dark axe | 6 passed under production CSP (36.4 s). |
| Live synthetic browser workflow, CSP and axe | 1 passed: actual intake, profile, expectation, preview/import, allocation, accountant review, multiple advice/accounting attachments, withholding projection, shared worker, export and side-by-side sources. |
| Existing review hub and procurement browser suites (92/96) | 30 passed locally; neither failed the second full CI browser run. |
| Autonomy settings browser regression (129) | CI exposed a loading race; delayed real API response reproduced it. Polling assertion passed both scenarios three times (6 passed, 1.2 min). |
| Migration drift | No new drift; 282 existing baseline operations. One head `tr1a2_review_outcomes`. |
| Python dependency audit | Initially reported three filelock advisories and one setuptools advisory. Updated pins to 4.2.1 and 84.1.0; the same audit now reports no known vulnerabilities. |

The first PR CI run, `40213665041` on `5581d0bf`, passed frontend, website,
encoding and migration jobs but failed backend integration checks and two browser
tests. It exposed missing encryption-rotation registration, unsafe/unrecognized
organization locks, a missing extraction-reader contract, missing structural
isolation registration, and the launch gate's 503 conflicting with route sweeps.
Those findings were reproduced/fixed without removing assertions. The deliberate
launch gate now returns a structured 409; disabled-feature tests still assert refusal.
All engine assertions remain intact.

The second full CI run, `40254658271` on `bcec7de9`, passed **all four backend
shards**, frontend, website, encoding, migration head/drift and Python audit. This
includes existing Helm, GST, TruthMesh and collaboration regressions. The browser
job failed only spec 129's count-before-load assertion (F-623); it was reproduced
and corrected as above. Its Stripe and gated live-TRINETRA steps were consequently
not reached. Final-head browser CI remains pending in this committed report; see
PR #40's checks and review description for the subsequent result. No failed or
skipped phase is counted as passing here.

Earlier local full-suite attempts were interrupted by environment resets or invalid
test storage/concurrent database setup. They are not passes. An earlier local website
Lighthouse run missed the home/pricing performance budget under concurrent load;
both PR website CI jobs subsequently passed, including all-category Lighthouse
scores of at least 95 on home, pricing, Helm, GST and TRINETRA. No threshold changed.

Reproduce the browser specs against the shipped default (`TRINETRA_MODE=pilot`): 135 expects an organization nobody enrolled; 136 and
141 to 144 enrol their own fresh organizations through the platform operator API, so they need no special setting. CI still runs 136
once more in a stack with the old `TRINETRA_LIVE_ENABLED=true` alias. Local Chromium is `/usr/bin/chromium` via
`E2E_CHROMIUM_PATH`. No real provider, tax portal, customer data or recipient was used.
