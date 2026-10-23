# Servabo

Multi-tenant B2B document intelligence and workflow automation. Customers
upload documents (PDFs, scans, images). Servabo extracts the text and
fields, lets people review and correct them, answers questions about them
with an AI assistant, and runs automations on the results.

| Part | Technology |
|---|---|
| API | FastAPI, SQLAlchemy 2, Alembic (`backend/app`) |
| Workers | `python -m app.worker` (job queue in Postgres) |
| Data | PostgreSQL 16 + pgvector, Redis 7, MinIO / S3 |
| AI | PaddleOCR, SentenceTransformers, Groq / Gemini |
| Web app | React 19, TypeScript, Vite, TanStack Query, Tailwind (`frontend/`) |
| Billing | Stripe and Dodo Payments |

## Quick start (development)

You need Docker, Python 3.12, Node.js 22 and about 15 GB of disk.

```bash
git clone https://github.com/sabarishwarne2001/servabo.git servabo
cd servabo
./start_dev.sh          # Windows: .\start_dev.ps1
```

Open <http://localhost:5173> and sign in as `admin@servabo.app` with the
password the launcher prints (development default `Servabo!Dev123`).
The public website (`website/`, the pages at <https://servabo.app>) runs too with
`./start_dev.sh --website` (Windows: `.\start_dev.ps1 -Website`) at
<http://localhost:4321>; the app's Pricing, Terms and Privacy links go there.
API health: <http://localhost:8000/api/v1/health>. API schema (development
only; production and staging do not serve it):
<http://localhost:8000/api/v1/openapi.json>.

No internet access to the model hosts? Put `ML_STUBS=true` in `backend/.env`
to use labelled test stubs in place of OCR and embeddings (never in
production).

### Before the rename

The product was called FlowPilot AI until 2026-10-16. [CHANGELOG.md](CHANGELOG.md) lists every identifier that was renamed.

**Full instructions, manual steps, test commands and troubleshooting:
[docs/RUNBOOK.md](docs/RUNBOOK.md).**

## Project status

**Release-ready.** The hardening campaign is complete; its records are in
[`docs/hardening/`](docs/hardening/):

- [`05-release-readiness.md`](docs/hardening/05-release-readiness.md): the final release
  certification (OWASP ASVS L2 and Twelve-Factor audit, test results, GO / NO-GO)
- [`STATE.md`](docs/hardening/STATE.md): where things stand and what to do next
- [`FINDINGS.md`](docs/hardening/FINDINGS.md): every defect found, with its fix and evidence
- [`NEEDS-OWNER.md`](docs/hardening/NEEDS-OWNER.md): the product decisions taken

**What comes next:** Final session 2A (the upgrade, in the cloud), then 2B (everything for real, on the owner's PC),
explained for the owner in [`docs/FINAL-SESSIONS.md`](docs/FINAL-SESSIONS.md) (prompts in [`docs/sessions/`](docs/sessions/)).

Deploying to production (a Linux server with Docker Compose): [`docs/RUNBOOK.md`](docs/RUNBOOK.md)
section 9.

## Repository layout

```
backend/            FastAPI app, workers, Alembic migrations, tests, scripts
  app/              application code
  alembic/          database migrations (exactly one head)
  tests/            pytest suite (security, isolation, engines, API, infra)
  scripts/          seeding, sweepers (cron), backups, maintenance tools
  deploy/           Caddyfile, cron files and deployment helpers
  docker-compose.yml       local development services
  docker-compose.prod.yml  production stack
frontend/           React web app; e2e/ holds the Playwright browser suite
website/            the public website (Astro, static): pricing, legal pages, product tour
brand/              the Servabo mark, colours and fonts shared by the app and the website
docs/               RUNBOOK, configuration reference, hardening campaign records
archive/            historical development records (not used to run anything)
start_dev.sh/.ps1   one-command local development launchers
```

The `apply_*`, `verify_*`, `run_arch*` scripts and phase certification reports of earlier
development phases are in [`archive/`](archive/README.md), unchanged.

## License

Proprietary. All rights reserved. This is closed-source commercial software;
no licence to use, copy, modify or distribute it is granted.
