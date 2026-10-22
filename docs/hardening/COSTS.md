# What Servabo costs to run (campaign session 4, §C.9)

Plain numbers for the first customers. Prices of other companies change: the ones marked
*approximate* were not checked live from this sandbox, so look them up before you buy. Everything
else comes from this repository (the price book, the plan limits, the compose file) or was measured
in campaign session 4.

## 1. The smallest server

Servabo runs as one Docker Compose stack on one server (RUNBOOK §9): the web API, seven worker
processes, PostgreSQL with pgvector, Redis, the reranker and Caddy. OCR (PaddleOCR) and the
embedding model (SentenceTransformers) run **on the server**, so no per-page OCR bill arrives from
anyone; they cost CPU time and memory instead.

| Measured (session 4, local stack, idle after the browser suite) | Memory |
|---|---|
| Web API (`uvicorn`) | 0.7 GB |
| One worker running every queue (`--loop all --profile all`) | 1.0 GB |
| PostgreSQL with the suite's data (32 MB database) | well under 0.5 GB |
| Redis | under 0.1 GB |

The compose file caps each service (`deploy.resources.limits.memory` in
`backend/docker-compose.prod.yml`): the caps add up to about 20 GB, but they are ceilings, not what
the services use. The OCR worker (cap 4 GB) and the enrichment worker (cap 3 GB) are the ones that
grow while documents are processed; the reranker loads its model once (cap 2 GB).

**Recommendation for the first customers: 4 vCPU, 16 GB RAM, 160 GB SSD.** 8 GB is the floor and
is tight: a batch of scanned uploads would push the OCR worker and the database into swap.
Approximate prices for that size: Hetzner Cloud about €25–35 a month, DigitalOcean or Linode about
$80–100 a month. Add the provider's snapshot or backup option (about 20% of the server price) as a
second copy next to Servabo's own encrypted backups (RUNBOOK §9.4).

**When to grow:** when uploads queue for more than a few minutes in Platform admin → Background
jobs, give the OCR worker more CPU first (OCR is the slowest step: about 1–3 seconds a page on one
vCPU), then move PostgreSQL to a managed database.

## 2. Monthly fixed costs besides the server

| Item | What for | Approximate cost |
|---|---|---|
| Domain name | `servabo.app` (N-028) | $15–80 a year, depending on the extension |
| Postmark | verification, invitation, trial, billing and alert emails (N-027) | free test tier; about $15 a month for 10,000 emails |
| Object storage (Cloudflare R2, Backblaze B2 or S3) | uploaded documents, and an off-server copy of backups | R2: about $0.015 per GB-month, the first 10 GB free; a few dollars a month at first |
| Healthchecks.io | heartbeats and the alert email when a job or the site stops (RUNBOOK §9.6) | free for up to 20 checks |
| Groq | the platform's AI model (section 3) | pay as you go, no minimum |
| Stripe | payments | no monthly fee; about 2.9% + $0.30 per card payment in the US (other countries differ) |

**Total before the first customer: roughly $30–120 a month**, almost all of it the server.

## 3. What one document costs

The plans include the two models Servabo serves on its own Groq key (N-054). The price book
(`backend/scripts/seed_price_book.py`) holds the supplier's list prices (checked 2026-10-11):

| Model (Groq) | Input, per million tokens | Output, per million tokens |
|---|---|---|
| GPT-OSS 120B (the default) | $0.15 | $0.60 |
| GPT-OSS 20B | $0.075 | $0.30 |

A typical two-page invoice is read by OCR on the server, then the model extracts its fields and a
second pass checks them. **Estimate: about 4,000 input and 1,000 output tokens a document**, which
is **about $0.0012 a document on GPT-OSS 120B** (a tenth of a cent): 4,000 × $0.15 / 1,000,000 +
1,000 × $0.60 / 1,000,000. A 20-page contract might use five times that, still under a cent.
Assistant messages cost about the same as a document each. This is an estimate from the prompt
sizes, not a measurement on real customer documents (the browser suite uses a stand-in model): after
the first real week, read the true figure in Platform admin → Usage (tokens by model) and divide by
the documents processed.

OCR pages, embeddings and storage cost the server's CPU and disk, not a per-unit bill. The price
book still charges them on paid plans' overage at several times that cost.

Customers on Gemini or Qwen models use **their own provider key** (BYOK): they pay the provider, and
Servabo pays nothing for those tokens (N-048, N-054).

## 4. The worst case for one Free user

A Free account gets the **one-week trial** (N-052, TENANCY-AND-PLANS §4.3) and Free's monthly
allowances, which are **shared by every Free organization the same person owns**
(`quota_service.usage_pool`), so making more organizations does not multiply them. After the week,
the organization is read-only: nothing more is processed until it subscribes.

| Free allowance (per month, refused at the limit) | Worst-case cost to Servabo |
|---|---|
| 300,000 input tokens on GPT-OSS 120B | $0.045 |
| 60,000 output tokens on GPT-OSS 120B | $0.036 |
| 50 OCR pages, 25 documents | server CPU: about 2–3 minutes of one vCPU |
| 0.25 GB storage | under $0.01 a month |
| A handful of emails (verify, trial reminders) | under $0.01 |
| Usage cost ceiling (the platform's safety net) | refuses at $1.00 |

**Worst case: about $0.10 per Free sign-up**, and never more than the $1.00 usage ceiling, because
the token allowances stop it first. The real risk is not one Free user but many fake ones: each
verified email address gets its own trial. Sign-up requires a verified email and is rate-limited
per address (`POLICY_PUBLIC_READ`); if you ever see a wave of sign-ups, Platform admin → Usage shows
it, and the trial can be shortened with one setting (`FREE_TRIAL_DAYS` in `.env.production`).

## 5. What a paying seat leaves

| Plan | Price per seat per month | Model cost at the seat's full token allowance, GPT-OSS 120B | Notes |
|---|---|---|---|
| Developer | $49 | 15M input + 2M output = $2.25 + $1.20 = **$3.45** | refused above; the usage ceiling is $25 a seat |
| Business | $299 | 100M input + 20M output = $15 + $12 = **$27** | input overage billed above |
| Enterprise | $799 | 300M input + 75M output = $45 + $45 = **$90** | overage billed above |

So even a seat that uses every token keeps more than 85% of its price before the server, the
payment provider's fee and support. Most seats use a small part of their allowance.

### After Dodo Payments' fees (website and payments session, C12)

Dodo Payments keeps 4% + 40 cents of each payment, plus 1.5% for an international card and 0.5% for
a subscription (`backend/app/core/payment_fees.py`; Dodo's pricing page, read 2026-10-16). The
figures below take the dearest usual case, an international subscription of one seat, and every
cost at its ceiling (OCR pages, tokens on the default model, storage, embeddings;
`tests/scripts/test_plan_unit_economics.py`, which fails if these rows go stale). Typical use is a
fifth of each allowance.

| Plan | Price per seat | Dodo fee | Cost at the ceilings | Margin at the ceilings | Margin at typical use |
|---|---|---|---|---|---|
| Developer | $49 | $3.34 | $14.05 | 65% | 87% |
| Business | $299 | $18.34 | $112.95 | 56% | 86% |
| Enterprise | $799 | $48.34 | $303.48 | 56% | 86% |

The rule: every paid plan keeps **at least 55%** at its ceilings after the fee. Enterprise kept 54.7%
with 100,000 OCR pages a seat, so its allowance became 95,000 pages a seat (the price did not move;
NEEDS-OWNER, C12). A chargeback costs a further $30.

## 6. Keep these numbers true

- When Groq changes a price, change it first in `backend/tests/scripts/test_price_book_matches_supplier_rates.py`,
  then in `seed_price_book.py`, then re-run `seed_price_book.py --version auto` on the server
  (RUNBOOK §9.3).
- After the first month, replace the estimate in section 3 with the measured figure and note the
  server's peak memory (`docker stats --no-stream`).

## 7. Error tracking (Final session 1, 4A)

**Sentry's free "Developer" plan:** one user and **5,000 errors a month** (secondary sources, a search on 2026-10-22; Sentry's own pricing page
could not be opened from the build sandbox, so confirm it on the day you sign up). The Team plan, from about $26 a month billed annually, includes
50,000 errors. Choose the **EU data region when you create the organization** (it cannot be moved afterwards); I could not confirm from here that the
free plan offers it, so check before you rely on it. Cost today: **$0**. At the settings used here (5xx and unhandled exceptions only, no traces, no
replays, no breadcrumbs) a healthy product sends a handful a day; 5,000 a month is a loud outage, and past it Sentry drops the extra rather than bill you.

**Sentry or GlitchTip, in plain words.** Both receive errors through the same address (`SENTRY_DSN`), so you can switch by changing that one setting.
Sentry's own service (EU region): nothing to run, a good screen, free up to the limit above, a US company holding data in the EU. GlitchTip, self-hosted:
free whatever the volume and the data never leaves your server, but it is another thing to run, update and back up, and it has a plainer screen. Start with
Sentry's free plan; move to GlitchTip only if you hit the limit or a customer's contract forbids a third party seeing even scrubbed errors.

## 8. What Final session 1 added to the bill (2026-10-22)

None of these was measured against the real service; each says where the number would come from.

| Item | Adds to the monthly bill | Notes |
|---|---|---|
| **Email-in** | **About $0 extra** | Postmark's inbound is part of the account that already sends the platform's mail; check that your Postmark plan's monthly message count covers inbound too (inbound messages count towards it on some plans; look at the plan page on the day you set it up). Each forwarded attachment costs what an upload costs (OCR and reading on your own server, plus the model call). |
| **The GST Monday email** | **A few cents** | One message per organization per week, only when there is something to say, through the same relay. |
| **Error tracking** | **$0** | Section 7. |
| **Zoho Books Connect** | **$0** | A free developer application in Zoho's API console; the customer's own Zoho Books pays for itself. |
| **Tally file** | **$0** | A file the customer imports. |
| **Public webhook events** | **A little compute** | One small signed request per occurrence to the customer's address, only when they subscribed. |
| **Warehouse datasets** | **Storage and egress, small** | Two more Parquet files per scheduled sync for an Enterprise customer (identifiers and figures only, so small); the customer's bucket pays for what it stores. |
| **Document packs: added checks** | **Model tokens, per document** | Twelve of the fourteen shipped checks are read by an AI model (N-181). Each one a customer adds costs one short model call per document processed, billed to the customer as assistant usage at the usual markup. A customer who adds five has five calls on every document. |
| **The new logo, resizable sidebars, search, screens** | **$0** | Nothing runs on a server for them. |
| **WhatsApp-in** (not built) | A monthly line from Meta (and possibly a solution provider) | PRODUCT-NEXT 2.2 says what it takes; read Meta's price list before deciding. |
