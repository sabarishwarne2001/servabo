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

A Free account gets the **14-day trial** (N-052; 14 days since Final session 2A, N-187, so that one monthly GSTR-2B
fits inside it; TENANCY-AND-PLANS §4.3) and Free's allowances, which are **shared by every Free organization the same
person owns** (`quota_service.usage_pool`), so making more organizations does not multiply them. After the trial, the
organization is read-only: nothing more is processed until it subscribes.

| Free allowance (refused at the limit) | Worst-case cost to Servabo |
|---|---|
| 1,000,000 input tokens on GPT-OSS 120B | $0.15 |
| 200,000 output tokens on GPT-OSS 120B | $0.12 |
| 200 OCR pages, 100 documents | $0.40 at the OCR cost basis (server CPU: about 10 minutes of one vCPU) |
| 0.25 GB storage | under $0.01 a month |
| A handful of emails (verify, trial reminders) | under $0.01 |
| Usage cost ceiling (the platform's safety net) | refuses at $1.00 |

**Worst case: about $0.68 per Free sign-up**, and never more than the $1.00 usage ceiling. The real risk is not one Free
user but many fake ones: each verified email address gets its own trial. Sign-up requires a verified email and is
rate-limited per address (`POLICY_PUBLIC_READ`); if you ever see a wave of sign-ups, Platform admin → Usage shows it, and
the trial can be shortened with one setting (`FREE_TRIAL_DAYS` in `.env.production`).

## 5. What a paying seat leaves

_Rewritten in Final session 2A (2026-10-26, N-187): every plan is now sold in dollars and in rupees, monthly and yearly, with
one set of allowances sized for the **lowest** of those prices._

| Plan | Allowance per seat per month | Model cost at the seat's full token allowance, GPT-OSS 120B | Notes |
|---|---|---|---|
| Starter (`developer`) | 300 documents, 1,500 OCR pages, 10 GB | 6M input + 1M output = $0.90 + $0.60 = **$1.50** | refused above; the usage ceiling is $8 a seat |
| Business | 1,500 documents, 6,000 OCR pages, 25 GB | 20M input + 4M output = $3 + $2.40 = **$5.40** | input overage billed above where the gateway bills usage |
| Enterprise | 4,000 documents, 20,000 OCR pages, 100 GB | 60M input + 15M output = $9 + $9 = **$18** | overage billed above where the gateway bills usage |

The allowances were cut (Starter from 500 documents and 5,000 pages, Business from 5,000 and 40,000, Enterprise from 10,000 and
95,000), **not the prices**: the rupee prices are about a third of the dollar ones, and one plan must mean the same thing in every
currency. The OCR cost basis, which dominates every row ($0.002 a page), is still an **estimate**; once Final session 2B measures
PaddleOCR on the production server, the page allowances can rise in step with a lower measured cost (never lower a cost basis without
a measurement).

### After Dodo Payments' fees (C12; every currency since Final session 2A)

Dodo keeps 4% + 40 cents of each dollar payment, plus 1.5% for an international card and 0.5% for a subscription; on a **domestic
Indian** payment (an Indian customer paying in rupees) it keeps 4% + 15 cents, plus 0.5% for a subscription
(`backend/app/core/payment_fees.py`; Dodo's pricing page as quoted by search extracts on 2026-10-23 and 2026-10-26, the page itself
could not be opened from the build sandbox). Rupees are converted at a fixed, conservative **₹90 to the dollar** (the market rate on
2026-10-26 was about ₹88). A yearly price is shown per month (divided by twelve), with its one yearly fee spread over the months. Every
cost is at its ceiling (OCR pages, tokens on the default model, storage, embeddings; `tests/scripts/test_plan_unit_economics.py`, which
fails if these rows go stale). Typical use is a fifth of each allowance.

| Plan | Price | Per seat per month, in dollars | Dodo fee | Cost at the ceilings | Margin at the ceilings | Margin at typical use |
|---|---|---|---|---|---|---|
| Starter | $49 a month | $49.00 | $3.34 | $4.74 | 84% | 91% |
| Starter | $490 a year | $40.83 | $2.48 | $4.74 | 82% | 92% |
| Starter | ₹1,499 a month | $16.66 | $0.90 | $4.74 | 66% | 89% |
| Starter | ₹14,990 a year | $13.88 | $0.64 | $4.74 | 61% | 89% |
| Business | $299 a month | $299.00 | $18.34 | $18.00 | 88% | 93% |
| Business | $2,990 a year | $249.17 | $14.98 | $18.00 | 87% | 93% |
| Business | ₹4,999 a month | $55.54 | $2.65 | $18.00 | 63% | 89% |
| Business | ₹49,990 a year | $46.29 | $2.10 | $18.00 | 57% | 88% |
| Enterprise | $799 a month | $799.00 | $48.34 | $60.40 | 86% | 92% |
| Enterprise | ₹14,999 a month | $166.66 | $7.65 | $60.40 | 59% | 88% |

The rules, checked against **every** row: at least **60%** at the ceilings before the fee, **50%** if every token went to the dearest
model the platform serves, and **55%** after the fee. The binding row is Business at ₹49,990 a year (57% after the fee). If Dodo turns
out to add its 1.5% international surcharge to Indian cards too, that row still keeps 55.1%. Before Final session 2A the test checked
only the dollar monthly prices, and Business at $2,990 a year kept 54.6% at the old allowances (F-626). A chargeback costs a further $30.

**The trial** (Free, 14 days, 100 documents, 200 OCR pages): about **$0.68** per trial account at its ceilings, against an acquisition
ceiling of $1.00 (raised from $0.25 with the longer trial, N-187), backed by the platform's $1.00 usage ceiling on Free.

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
