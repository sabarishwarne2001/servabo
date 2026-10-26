# TRINETRA validation

This file distinguishes implemented tests from their executed results. Final run
results will be recorded after the remaining validation completes; intermediate
green runs are not production or legal approval.

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

## Executed validation, 26 October 2026

| Check | Observed result |
| --- | --- |
| TRINETRA plus compliance data-map registry | 326 passed; includes supporting-source erasure/retention and populated downgrade/upgrade. |
| TRINETRA, structural/locking/key-rotation/extraction checks and two engine suites | 153 passed; two engine sweeps stopped at an unconfigured local SMTP relay. Both were rerun with the declared test relay below. |
| Those engine suites plus existing Helm service regressions | 402 passed. |
| Image dependency contracts and extraction contracts after security upgrades | 56 passed; `pip check` found no broken requirements. |
| Existing document console counts/filter contracts | 7 passed. |
| Frontend units | 291 passed in 19 files. |
| Frontend build, lint, self-check, generated API contracts | Passed; 12 API contracts agree with the running server. |
| Live synthetic browser workflow, CSP and axe | 1 passed: actual intake, profile, expectation, preview/import, allocation, accountant review, multiple advice/accounting attachments, withholding projection, shared worker, export and side-by-side sources. |
| Existing review hub and procurement browser suites (92/96) | 30 passed locally. Both suites had a failing test in the first PR CI run; a complete new CI run is still required. |
| Migration drift | No new drift; 282 existing baseline operations. One head `tr1a2_review_outcomes`. |
| Python dependency audit | Initially reported three filelock advisories and one setuptools advisory. Updated pins to 4.2.1 and 84.1.0; the same audit now reports no known vulnerabilities. |

The first PR CI run, `40213665041` on `5581d0bf`, passed frontend, website,
encoding and migration jobs but failed backend integration checks and two browser
tests. It exposed missing encryption-rotation registration, unsafe/unrecognized
organization locks, a missing extraction-reader contract, missing structural
isolation registration, and the launch gate's 503 conflicting with route sweeps.
Those findings were reproduced/fixed without removing assertions. The deliberate
launch gate now returns a structured 409; disabled-feature tests still assert refusal.
All engine assertions remain intact. The final full-suite CI result is pending.

Earlier local full-suite attempts were interrupted by environment resets or invalid
test storage/concurrent database setup. They are not passes. An earlier local website
Lighthouse run missed the home/pricing performance budget under concurrent load;
the first PR's website CI job subsequently passed. No performance threshold changed.

Reproduce browser 135 with the default-disabled API; browser 136 requires an isolated
synthetic API with `TRINETRA_LIVE_ENABLED=true` and runner `E2E_TRINETRA_LIVE=1`.
CI runs these in separate stack phases. Local Chromium is `/usr/bin/chromium` via
`E2E_CHROMIUM_PATH`. No real provider, tax portal, customer data or recipient was used.
