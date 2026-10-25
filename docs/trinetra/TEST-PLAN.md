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

## Intermediate observations

The initial 45 TRINETRA tests passed and 286 frontend unit tests passed. Follow-up
tests found an expired fixture reference in the populated migration test and a
workspace display-name attribute error in organization reporting; fixes are under
rerun. A frontend equality lint error was also corrected. The website typecheck
passes with telemetry disabled and a writable configuration directory. Final
regression, browser and deployment evidence is still being assembled.
