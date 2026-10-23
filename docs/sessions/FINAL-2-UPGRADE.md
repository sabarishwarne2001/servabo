# Final session 2A (FINAL-2-UPGRADE): make Servabo sellable in India, safe to run, and provable

| | |
| --- | --- |
| **Where** | Claude Code on the web (the cloud), repository `servabo` |
| **Model / effort** | **Opus 5.5, High** |
| **Before you start** | PR #37 (Final session 1) is merged and the PR that added this file is merged; **CI is green on `main`** |
| **After it** | Final session 2B, on your own PC: `docs/sessions/FINAL-2-LIVE.md`. **This session rewrites that prompt** so it matches what is really there. |
| **External cost** | Zero. Every outside service is played by a stand-in here. Final session 2B connects the real accounts. |
| **If usage runs out** | Type `continue` in the same session after the reset. Each phase is finished, tested and pushed before the next one starts. |

**How to start.** Open a new Claude Code session on the web for `servabo`, choose Opus 5.5 with High effort, and paste either
everything below the line or this one sentence:

> Read `docs/sessions/FINAL-2-UPGRADE.md` on `main` and carry it out from section 0. Never stop to ask me.

---

# Final session 2A: sellable in India, safe to run, provable

## 0. Why this session exists

Servabo is a multi-tenant B2B SaaS for document intelligence and finance automation, built by a solo founder in India who is
new to SaaS. Explain everything you report in plain language, with no jargon left unexplained.

**Final session 1 is complete.** All of its checklist is ticked:

- PR #37's CI run (#462) was green on every job, and so was the run on `main` after the merge (#464);
- even the advisory `pip-audit` job is green now;
- its hand-over is in `docs/hardening/HANDOFF.md`, "Final session 1 → Final session 2".

Before trying everything for real, the owner asked for one more session, with these goals:

1. **A commercial reality check.** Can Servabo, as it is today, be sold to its target customer and make money? What stands in
   the way? The owner's own words: sophisticated architecture is not the same as a competitive product with paying customers,
   proven accuracy, reliable deployments and repeatable sales.
2. **Four issues the owner found:**
   - the custom-domain price contradicts itself;
   - safety jobs depend on host cron;
   - document text could steer automations or agents (prompt injection);
   - **prices are too high for Indian customers.**
3. **An idea to assess, not to build blindly: "Evidence-to-Resolution".** Detect an issue → establish the evidence →
   coordinate the fix → **verify** that it was fixed → measure the money. The owner wants it built only if the product does not
   already do it, and only if it would really earn money.
4. **Final session 1's small leftovers.**
5. **Make the live session's prompt match reality.** This session ends by rewriting `docs/sessions/FINAL-2-LIVE.md`.

**The direction (decided by the owner, N-186): no new engines.** Servabo already has more engines than one founder can sell.
This session makes the existing product cheaper to buy, safer to run, provable, and focused on one customer and one outcome:

> **For Indian distributors, wholesalers and manufacturers, and the CA firms that serve them:** Servabo finds the money leaking
> out of supplier invoices (GST credit at risk, overcharges, duplicates, missed payment deadlines). It helps the team get each
> one fixed, and shows the rupees it can **prove** were saved.

### What a read of the code found on 2026-10-23 (verify every point before you rely on it)

| Area | What was found | Where |
| --- | --- | --- |
| Custom domains | The add-on catalogue prices **Custom domains at $199 a month**, but the plan seed bundles `addon.custom_domain` into **every paid plan** (it is in `DEVELOPER_FEATURES`). So nobody can buy it (`sold_on` is empty in the website's `pricing.json`). Even so, RUNBOOK §9 says "add-ons: custom domains $199", and `dodo_setup.py` creates a Dodo product nobody can buy. The generated tenancy doc says "included" on Developer and above. **The code is consistent; the docs and the Dodo product list are not, and the decision itself was never made on purpose.** | `backend/app/services/billing/entitlement_service.py` (`ADDON_CATALOG`), `backend/scripts/seed_quota_tiers.py`, `docs/RUNBOOK.md` (about line 410), `docs/hardening/TENANCY-AND-PLANS.md`, `website/src/data/pricing.json`, `backend/scripts/dodo_setup.py` |
| Prices | Every price is in USD, **per seat per month**: Developer $49, Business $299, Enterprise $799. Yearly is $490 and $2,990. The GST Credit add-on is $49 a month and warehouse sync $300. At about ₹88 to the dollar, Business is about ₹26,000 **per user** a month. | `seed_quota_tiers.py` (`COMMERCIALS`, `YEARLY_COMMERCIALS`), `entitlement_service.py` |
| Multi-currency | Plan prices already support several currencies and intervals through published price books (ARCH-50; the billing page has a Currency dropdown). But the Dodo product ids are one environment variable per plan and interval (`GATEWAY_PRICE_ID_DEVELOPER`, …), with no currency in the name. Add-ons have **one** USD monthly price each. | `backend/app/services/revops/price_books*`, `backend/app/api/v1/billing.py`, `backend/app/core/config.py` |
| Unit economics | `tests/scripts/test_plan_unit_economics.py` requires **60% gross margin at every paid plan's ceilings** (50% on the dearest model), and requires Free to cost under $0.25 a month. It checks the **USD** price only. The ceilings are **per seat**. The OCR cost basis is **$0.002 a page, ESTIMATED**, and it dominates them: Developer's 5,000 pages is $10 of its $14.05. | `backend/tests/scripts/test_plan_unit_economics.py`, `backend/scripts/seed_price_book.py`, `docs/hardening/COSTS.md` |
| Trial | Free is a **7-day** trial (`FREE_TRIAL_DAYS=7`) with 25 documents. GSTR-2B arrives once a month (on the 14th), so a 7-day trial often contains no GSTR-2B. | `backend/app/core/config.py`, `trial_service.py` |
| Dodo and India (read on 2026-10-23; **check again**) | A product can be priced **natively in INR**. The domestic India fee is **4% + 15¢**, plus 0.5% for subscriptions. Adaptive currency (showing USD prices in rupees) adds 2 to 4%. UPI, RuPay and Indian cards support subscriptions. Indian card mandates default to a **₹15,000 floor**: above it the mandate is fixed at the exact amount, and "an upgrade above the existing mandate limit fails" until the customer authorizes again. Checkout can collect a business **Tax ID**; **whether Dodo's invoice shows the buyer's GSTIN, so the buyer can claim the 18% GST as input credit, is not documented.** | dodopayments.com/pricing; docs.dodopayments.com: features/payment-methods/india, features/adaptive-currency, features/b2b-payments |
| Host cron | About 17 sweeps (retention and compliance purge, identity, invitations, ERP retries, obligations, …), the backups, the weekly restore drill and the uptime heartbeat all run from **host** cron. The watchdog that notices a stale sweep **also runs from cron**. The in-app scheduler (`worker-scheduler`, 36 jobs) records nothing about the host jobs. **If cron is missing, nothing inside the app notices**, and only an outside Healthchecks.io check would, if the owner set it up. | `backend/deploy/cron.d/`, `backend/deploy/bin/servabo-sweep-watchdog`, `backend/app/workers/scheduler.py`, RUNBOOK §9.6 |
| Prompt injection | There are good pieces, but no single map: the corpus flags injection text before a model sees it; supplier emails go only to a supplier's **known** contact; the ERP target comes from the rule's configuration; `work_item.mutate` has an allowlist; `autonomy.decide` uses the calibrated model, not text. **Nothing enumerates every path from document text to an action**, and no test fails when a new path appears. Open questions include where a supplier's "known contact" comes from (could a document teach it?), and what email-in subjects, filenames, QR payloads and GSTR-2B trade names can reach. | `backend/tests/fixtures/corpus/`, `backend/tests/engines/test_corpus_live.py`, `backend/app/services/automation/actions/`, `backend/app/services/tools/`, `backend/app/services/helm/` |
| Evidence-to-Resolution | **Most of the pieces exist, in separate engines.** *Detect:* three-way matching (procurement cases), the radar's duplicates and anomalies, payment-risk flags, TruthMesh conflicts, GST matches (waiting for supplier, not in books, the 180-day risk), Helm's supplier statement reconciliation (`helm/reconcile.py`), MSME 45-day terms, obligations, clause assertions. *Evidence:* document evidence and provenance, case documents, Helm certificates. *Coordinate:* the review hub (assignment, but only three sources: verification disagreements, automation triage, anomalies), automation (assign, notify, remind supplier, request a document), Helm tasks, approvals and the Guard, collaborative threads. *Verify closure:* only **Helm's value ledger** counts an outcome on evidence (a confirmed duplicate never paid, an overcharge credited or corrected, a discount captured, a late fee avoided, each once). GST closes itself when a later GSTR-2B shows the invoice, but nothing counts that as money secured. *Measure:* the value receipt counts what was **found** this month, with strict honesty rules; it has no "verified recovered" line apart from Helm's. **What no engine has:** one list of money issues across engines, each with its rupee exposure, an owner, a due date and the next action; closure that only evidence can grant; and one outcome ledger counted once. | `backend/app/services/review/`, `helm/value.py`, `helm/reconcile.py`, `value_receipt.py`, `gst/`, `procurement_matching/`, `radar/`, `truthmesh/`, `payment_risk*` |
| Final 1 leftovers | (a) No warning emails on day 1 and day 25 after a customer deletes a workspace or organization. (b) The global upload tray does not accept a zip; the Documents page does. (c) Migration `k1a6`'s downgrade was proven only on an empty database. (d) PRODUCT-NEXT 2.3: a yearly and a rupee price for the GST add-on. | HANDOFF "Final session 1 → Final session 2" §3 |
| Owner questions still open | N-174 (should the Tally file come to Developer?), N-180 (warehouse datasets for Business?), N-181 (the cost of AI-read pack checks). N-187 below answers N-174 and N-181. | `docs/hardening/NEEDS-OWNER.md` |
| The owner's own commit | `e51f736` ("package_update") on `main` removed two optional peer entries (`ajv`, `fast-uri`) from `frontend/package-lock.json`. Harmless, but check that `npm ci` and the frontend job are still green. | `git show e51f736` |
| **`main` went red on a speed test** | `main`'s CI run #465 (on `e51f736`, which changed only the frontend lockfile) failed one job: `pytest (shard 1/4)`, `tests/performance/test_gst_budgets.py::test_import_and_matching_stay_inside_their_budgets`, with "matching took 10.23s" against a 10 s budget (5 s × `PERF_BUDGET_MULTIPLIER` 2). Session H made matching 2.0 to 2.4 s on the build machine. Either the shared CI machine was slow that day, or Final session 1 added work to the GST recompute (notices, webhook events, the data map). **Find out which; do not move the budget.** | `docs/hardening/PERFORMANCE.md` ("the matching step on a shared CI machine"), `backend/app/services/gst/` |

## 1. Authority and rules

- **The owner has delegated full product and pricing authority for this session.**
  - **The prices and packaging in N-187 (§4) are the owner's decisions;** implement them. You may change **allowances**
    (documents, pages, tokens per seat) to keep the margin rules, but **not the prices**. If a price truly cannot hold, use
    the band in §4. Record every number you change and why.
  - Every other decision: decide like a careful senior engineer at a top SaaS company, build it, and record it in
    `docs/hardening/NEEDS-OWNER.md` as `DECIDED (Final 2A)`.
  - Never stop to ask. The next free numbers are decisions from **N-188** (N-186 and N-187 are this plan's own), findings from
    **F-619**, and browser specs from **135**. Check `STATE.md`.
- **Evidence rule (CLAUDE.md):** a bug is fixed only when a test failed first, the fix is applied, that test passes and the
  rest of the suite still passes. Anything not proven is reported as "unverified".
- **CLAUDE.md hard rules hold:**
  - no secrets, `.env` files or binaries in git;
  - never weaken, skip or delete a test. **When a product decision changes what is right** (a price, a plan name, an
    allowance), updating a test's expected value is not weakening it. Say so in the commit message, with the N-number.
  - never push to `main`;
  - exactly one Alembic head, with up, down and up;
  - leave `archive/` and the historical scripts alone;
  - test-mode credentials only.
- **Never contact a live outside service from a test.** Use the existing stand-ins (`backend/tests/fakes/fake_dodo.py`, the
  Postmark, Zoho and SMTP stand-ins). Read providers' documentation with WebSearch and WebFetch, and cite page and date in a
  code comment wherever you rely on documented behaviour.
- **The old product name must not come back** outside the allowlist in `backend/tests/core/test_the_old_name_is_gone.py`.
- **Every new route, setting and migration is accounted for**, as in Final session 1:
  - coverage-ledger rows, with `campaign_slices.py --check all` exiting 0;
  - `config.py`, `docs/CONFIGURATION.md` (`config_reference.py`), `.env.example` and the production template;
  - the generated API types;
  - `TENANCY-AND-PLANS.md` (`generate_tenancy_doc.py`; `test_tenancy_doc_is_current.py`);
  - the website's `pricing.json` (`export_public_pricing.py`).
- **Branch and PR.**
  - Use the session's assigned branch.
  - Open a **draft** PR at the start and push after every finished phase.
  - One logical change per commit; each message says what and why.
  - Mark the PR ready only at the end.
- **Never merge, and never call the work finished, while CI is red** (Session I's rule).
- **If cut off,** continue from the first unticked box in `STATE.md`. Never restart a phase that is ticked.
- **Usage discipline.**
  - At most two helper agents at a time, each with a narrow brief and a clear "done when".
  - Run long suites in the background. Keep command output short.
  - The full backend and browser suites run once at the end, or on the ready PR's CI.
- **The cut line.** Phases 1 to 3 and Phase 8 are the must-haves. If usage gets tight after Phase 5, skip the build part of
  Phase 6 (keep its assessment), go to Phase 8, write the hand-over and stop cleanly.

## 2. Start-up

1. **Read:**
   - `CLAUDE.md`;
   - `docs/hardening/STATE.md` (the top sections);
   - `docs/hardening/HANDOFF.md`: "Plan change: the upgrade session before the live session", "Final session 1 → Final
     session 2", and the "Owner launch checklist";
   - `docs/hardening/UPGRADE-AUDIT.md`;
   - `docs/PRODUCT-NEXT.md`;
   - `docs/hardening/NEEDS-OWNER.md`: N-118, N-145, N-160 to N-187 in full;
   - `docs/hardening/COSTS.md`, `docs/billing/DODO.md`, `docs/billing/DODO-LOCAL-TEST.md`;
   - `docs/RUNBOOK.md` §9;
   - `docs/sessions/FINAL-2-LIVE.md`;
   - `docs/FINAL-SESSIONS.md`.
2. **Read the code** behind every row of the §0 table.
3. **Stand up the stack** as STATE.md's environment notes describe (Postgres 16 with pgvector 0.8, Redis, Python 3.12 venv,
   `npm ci`, `frontend/e2e/scripts/start-stack.sh`). Keep the environment block in the scratchpad, outside the repo.
4. **Open the draft PR.** Write this session's checklist at the top of `STATE.md`: a section "Current phase — Final session 2A
   (FINAL-2-UPGRADE)", one box per phase item below, and the next free numbers.
5. **Look at `main`'s latest CI run.** If it is still red (§0, the speed test), do Phase 4 item 0 before Phase 1.

## 3. Phase 0: the commercial reality check and the resolution assessment (written first, at most one tenth of the session)

### 0A. `docs/product/COMMERCIAL-READINESS.md`

An honest page the owner can act on. It does not sell Servabo to the owner. It has five parts:

1. **Who buys, and why.** The target customer above, and the three or four jobs they would pay to have done. Tie each job to
   the screens that do it today.
2. **Against whom.** A table of what these customers use or could buy instead, with **today's** prices from the vendors' own
   pages (cite each, with the date). At least:
   - Tally Prime (its own GSTR-2B reconciliation);
   - Zoho Books;
   - ClearTax / Clear GST;
   - one low-cost GST reconciliation tool;
   - Suvit (Vyapar TaxOne);
   - one Indian AP-automation vendor;
   - one global document-AI vendor (Nanonets, Docsumo or Rossum).

   For each: where Servabo is better, where it is worse, and what a buyer would say.
3. **What is proven and what is not.**
   - Proven: the engineering (tests, security, CI).
   - Not proven: accuracy on real Indian invoices; any real outside integration; any customer; the time a customer saves; the
     rupees found or recovered.
   - Name each gap, and the session or step that closes it. Final 2B and the pilot (Phase 5) close most of them.
4. **The money model.** The new price list (§4), what a typical customer pays per year, the cost to serve them (from COSTS.md
   and the unit-economics test), and how many customers cover the fixed costs.
5. **Three risks a careful investor would name,** and what reduces each.

Keep it to what the evidence supports. No market-size figures without a cited source.

### 0B. `docs/product/RESOLUTION-ASSESSMENT.md`: does Servabo already do Evidence-to-Resolution?

Trace these **six money issues** through today's product, end to end, as a finance person would. Use the browser stack and the
sample company; take screenshots for yourself, but do not commit large images.

1. An invoice above its purchase order: price or quantity, through three-way matching.
2. A supplier statement that disagrees with our books (`helm/reconcile.py`).
3. A payment deadline approaching: MSME 45 days, the GST 180-day rule, an obligation.
4. GST credit at risk: a supplier not reported in GSTR-2B.
5. A duplicate invoice (the radar).
6. A changed supplier bank account (payment risk).

For each, write down:

- which engine detects it;
- where the evidence is shown;
- how a person is assigned and what they can do next;
- what marks it "done", **and whether that mark is a click or evidence**;
- whether its money is counted, where, and whether it could be counted twice;
- **how many screens and clicks** it takes.

Then decide, using these rules, and record the decision as an N-number. **Build Phase 6** only if all four hold:

- **(a)** at least three of the six issues have no evidence-based closure, or no single place with an owner and a due date;
- **(b)** the build reuses existing detection and stores: a read model plus closure rules plus one outcome ledger, **no new
  detection engine and no new AI**;
- **(c)** it fits in about 35% of this session;
- **(d)** it produces a number the value receipt can show as **"Recovered, verified"**, separate from "Found", that a customer
  could check line by line.

If the decision is "do not build", write what to build instead, or nothing, and why. **The prediction from the code read is
"build a thin layer". Prove or disprove it; do not assume it.**

## 4. Phase 1 (P0): prices and packaging for India (N-187)

**Why it earns money:** today a three-person Business team in India would pay about ₹78,000 a month. Indian AP-automation
platforms cost ₹3 to ₹5 lakh a year (about ₹25,000 to ₹42,000 a month), GST reconciliation tools ₹500 to ₹1,500 a month, and
Zoho Books ₹749 to ₹2,999 a month. At current prices almost no Indian SMB will start. Servabo's cost to serve is tiny: about
₹0.10 of model tokens per document, plus a share of one server.

### 1A. The decisions (N-187; the owner's)

**India, in rupees.** GST (18%) is charged on top by Dodo as merchant of record.

| | Free trial | **Starter** (key stays `developer`) | Business | Enterprise |
| --- | --- | --- | --- | --- |
| Per user, per month | ₹0, **14 days** | **₹1,499** | **₹4,999** | **₹14,999** |
| Per user, per year (two months free) | — | **₹14,990** | **₹49,990** | by agreement (as today) |
| GST Credit | preview | add-on **₹1,499 a month or ₹14,990 a year** per organization | included | included |
| Custom domains | — | **not included** | included | included |
| Tally Prime import file (download) | — | **included** (closes N-174) | included | included |
| Zoho Books Connect and every automatic ERP posting | — | — | included | included |
| Warehouse sync | — | not sold in rupees | included | included |

**International, in dollars.** The per-user prices **do not change**: $49, $299 and $799, and $490 and $2,990 a year. The GST
Credit add-on gains a yearly price: **$490 a year**, beside $49 a month. Custom domains, the Tally file and the Starter name
follow the table above in every currency. Warehouse sync stays a $300-a-month add-on for Starter in dollars only.

**Rules that come with the prices:**

1. **One set of allowances for every currency, sized for the rupee prices.** A plan means the same thing everywhere; only the
   price differs, which is ordinary regional pricing.
2. **The margin rule is checked against the lowest price of every plan, in every currency.**
   - Convert at a **conservative fixed rate** (₹90 to $1; record the day's real rate beside it).
   - Use Dodo's **India** fee (4% + 15¢, plus 0.5% for subscriptions).
   - Paid plans keep at least **60%** at their ceilings, and 50% on the dearest model, as today.
   - To get there, **lower the allowances, not the prices.** Starting points from the code read, which you must recompute:
     - Starter: about 300 documents, 1,500 OCR pages and 6M input / 1M output tokens a user;
     - Business: about 1,500 documents, 6,000 pages and 25M / 5M;
     - Enterprise: about 4,000 documents, 20,000 pages and 60M / 15M.
     - Keep `test_plan_ladder_is_monotonic.py` green.
   - If even reasonable allowances (a Starter user under 200 documents a month) cannot meet the rule, raise the rupee price,
     **at most 20%**, and record it.
3. **The OCR cost basis stays $0.002 a page (ESTIMATED)** until Final session 2B measures it (its Phase 17). Write in COSTS.md
   that allowances can rise once a lower real cost is measured. Never lower a cost basis without a measurement.
4. **The trial becomes 14 days, with 100 documents and 200 OCR pages,** so that one monthly GSTR-2B cycle fits inside it.
   - Free's acquisition-cost ceiling in the unit-economics test rises from $0.25 to **$1.00 per trial account**. This is
     intended, so record it.
   - The platform's existing $1.00 usage ceiling still backs it.
   - Every email and banner that says "7 days" or counts the trial's days follows the setting.
5. **"Developer" is shown as "Starter"** everywhere a customer sees a plan name: the app, the website, emails, Dodo product
   names and docs for customers.
   - The key `developer` and every code identifier stay as they are.
   - "Developer API", the "developer portal" and similar feature names are **not** plan names, and stay.
6. **Custom domains move to Business and Enterprise** (white-label is worth most to larger customers and to CA firms
   reselling Servabo).
   - Starter loses it, and **the $199 add-on and its Dodo product are retired**. Keep the catalogue entry only if code needs
     it for old rows; there are none in production.
   - RUNBOOK, the tenancy doc, the website and `dodo_setup.py` then all say the same thing.
7. **Currency follows the customer.**
   - An organization whose billing country is India, or whose oldest workspace is in `Asia/Kolkata` when no billing country is
     known, sees rupees by default; anyone can switch.
   - The website shows **₹ by default** (the target market), with a $ switch. It is a static site, so no geolocation.
8. **Indian payment rules, checked against Dodo's docs today:**
   - Rupee checkouts set `billing_currency: INR` and billing country `IN`, so UPI and RuPay are offered.
   - **The ₹15,000 mandate floor:** when a monthly total including GST would exceed ₹15,000, the billing page says in one line
     that Indian banks ask the customer to approve each automatic payment above ₹15,000, and offers yearly (one approval a
     year).
   - When adding seats would exceed the existing mandate, the app says what will happen **before** the change, and handles
     Dodo's failure as a plain "approve the new amount" step with a link, never as a silent dunning email. Read Dodo's
     `mandate_min_amount_inr_paise` and decide whether to raise the floor at checkout; record the decision.
9. **The buyer's GSTIN on Dodo's invoice.** A business buying in rupees should get a tax invoice carrying its GSTIN, so it can
   claim the 18% GST as input credit.
   - Pass Dodo's business purchase with the Tax ID, using `require_tax_id` for Indian business checkouts, pre-filled from the
     organization's GSTIN where Servabo knows it.
   - Whether Dodo's invoice then prints the GSTIN and splits CGST, SGST and IGST **cannot be proven here**. It becomes a
     Final 2B check.
   - If Dodo's documentation says it cannot, record `OPEN` with the options (ask Dodo; issue Servabo's own GST invoice; an
     Indian gateway for rupee sales). Do not build any of them now.

### 1B. Build it

- **The catalogue:**
  - `COMMERCIALS` and `YEARLY_COMMERCIALS`, or a successor that holds prices per **currency and interval**;
  - the add-on catalogue gains prices per currency and interval (`AddonOffer` holds one USD monthly price today);
  - the price books publish a USD book and an INR book, monthly and yearly;
  - the seed stays idempotent.
- **Dodo products,** one per plan, currency and interval, plus the add-on's:
  - choose clear setting names, for example `GATEWAY_PRICE_ID_BUSINESS_INR`, `GATEWAY_PRICE_ID_BUSINESS_YEARLY_INR`,
    `DODO_ADDON_PRODUCT_GST_CREDIT_INR`, `DODO_ADDON_PRODUCT_GST_CREDIT_YEARLY`, `DODO_ADDON_PRODUCT_GST_CREDIT_YEARLY_INR`;
  - `dodo_setup.py --create-test-products` creates them all, prints the lines, and checks each product's amount, currency and
    interval;
  - the custom-domain product is gone;
  - **write down the final product count** everywhere the docs say "eight".
- **Checkout, the billing page, upgrade moments, the GST page's add-on offer, the value receipt's lines, and every email that
  names a price or a plan.** Grep for `$49`, `$299`, `$799`, `$199`, `$300`, `49_000_000`, `"Developer"` and "per seat" in
  `backend/app`, `frontend/src`, `website/src`, the email templates and the docs. **No price is hard-coded in a sentence;**
  sentences read the catalogue.
- **Unit economics:** extend `test_plan_unit_economics.py` so it checks every published price in every currency (the rupee
  ones with the fixed rate and the India fee). Then resize the allowances until it passes; the ladder test stays green.
- **The website:**
  - the pricing page in ₹ by default, with a $ switch;
  - "per user per month, GST extra" in plain words;
  - the yearly switch;
  - the add-on in both currencies;
  - the refund page and the FAQ in step with the 14-day trial;
  - `pricing.json` regenerated.
- **Docs:**
  - COSTS.md (§5 in both currencies, with the India fee);
  - RUNBOOK §9 (the product list and the setting names);
  - the owner launch checklist steps 8, 9 and 11 (the product counts);
  - `DODO.md` and `DODO-LOCAL-TEST.md` (the journeys now include a rupee checkout);
  - `TENANCY-AND-PLANS.md` (regenerated);
  - `PRODUCT-NEXT.md` (2.3 done).
- **Tests:**
  - the catalogue per currency;
  - the price-book publish;
  - the checkout parameters for rupees (currency, country, tax id);
  - the mandate notice;
  - the trial length;
  - the custom-domain gate on Starter (refused with an upgrade moment naming Business);
  - the Tally file on Starter;
  - the plan names;
  - unit economics and the ladder;
  - browser specs: a rupee checkout through the stand-in Dodo, the billing page's currency default, and the website's pricing
    page in both currencies.

## 5. Phase 2 (P0): safety jobs that cannot stop silently

**Why it earns money:** a retention purge or backup that silently stops is how a small SaaS loses a customer's trust, or their
data. The owner must hear about it the same day, without depending on an outside service he may not have set up.

1. **Every safety job reports its runs into the app.**
   - The safety jobs are: each sweep in `deploy/cron.d/servabo-sweepers`, the backup, the restore drill, the PITR drill where
     used, and the uptime heartbeat.
   - Each reports its start, success or failure, and a short detail to one small table (or an existing store, if one fits):
     job name, last success, last failure, last detail. It goes through a tiny authenticated internal path, or straight to
     the database from the host scripts; choose the simplest safe one and record why.
   - Reporting must never make a job fail.
2. **The in-app scheduler watches them.** Every hour it compares each job's last success with its deadline (each job's own,
   from its schedule). **"Never ran" counts as stale once the app has been up for a day.** A stale job:
   - sends one operator alert (`OPERATOR_ALERT_EMAILS`, and `ALERT_WEBHOOK` when set), at most once a day per job;
   - shows red on the platform admin's health page with the job, the last success and what to run;
   - adds `safety_jobs: degraded` to the readiness answer **without** failing readiness. A stale sweep must not take the app
     down.
3. **Consider moving the sweeps into the in-app scheduler** (`backend/app/workers/scheduler.py`), so only the backup, the
   restore drill and the heartbeat need host cron.
   - Do it if each sweep is idempotent, can take the scheduler's lock, and its runtime fits the worker.
   - Remove the moved cron lines in the same change (never run a job twice), and keep `test_host_cron_lines.py` truthful.
   - Record the decision either way.
4. **Install and prove the host part on day one.** Write `backend/deploy/bin/servabo-install-host-jobs`, which:
   - checks that `cron` is installed and running;
   - installs the cron files;
   - runs each host job once, in its safe or dry mode;
   - prints what reported back.
5. **`preflight.py`** gains a check that every safety job has reported a success within its deadline, and says which one to run
   if not.
6. **Docs and checklist:**
   - RUNBOOK §9.6 (what reports, what alerts, how to read the health page);
   - owner launch checklist step 10: install the host jobs with the script, see every job report, and **stop cron once on
     purpose and see the alert arrive the next day**. The rehearsal in Final 2B does this on the owner's PC.
7. **Tests:**
   - the report path;
   - stale and never-ran detection with a controlled clock;
   - one alert a day;
   - readiness stays up;
   - the preflight line;
   - if moved, each sweep in the scheduler, and that no cron line still names it.

## 6. Phase 3 (P0): prompt injection, mapped and tested

**Why it earns money:** a finance customer's first security question is "can a malicious invoice make your AI pay someone or
email our data out?" The answer must be "no, and here is the test that proves it".

1. **Write `docs/hardening/PROMPT-INJECTION.md`: the map.**
   - **Every way outside text enters:**
     - document text and tables;
     - file names;
     - email-in subjects, bodies and sender names;
     - QR payloads;
     - GSTR-2B trade names;
     - supplier uploads through request links;
     - extraction memory;
     - assistant questions.
   - **Every model call that reads it.**
   - **Every way a model's output can cause an effect:**
     - fields used by automation conditions;
     - automation actions;
     - assistant tools (`services/tools/` selectors);
     - Helm drafts and the Guard;
     - calibrated autonomy;
     - the process agent;
     - email, chat and webhook content;
     - ERP postings.
   - For each path: what stops a document from steering it, and the test that proves it.
2. **Invariants, each with a test that walks the registry, so a new path fails the build:**
   - **(a)** No automation action, assistant tool, agent or Helm action can approve a payment, pay, release a hold on a
     payment, change a supplier's bank details, or mark an invoice paid on its own. A person always does. Enumerate every
     registered action and tool and assert its class.
   - **(b)** Every outbound message goes to a recipient from configuration or from a contact **a person confirmed**, never to
     an address read from a document. Find where Helm's "known contact" for a supplier comes from. If a document can teach
     it, a learned contact needs a person's confirmation before it is used for an outbound email; build that, test-first.
   - **(c)** Text from a document is always data in a prompt: fenced (`fenced_context.py`), never instructions. Prove it for
     every model call that reads document text.
   - **(d)** Calibrated autonomy's decision cannot be moved by text in the document.
   - **(e)** Every outbound template escapes and truncates every value taken from a document. Extend
     `test_email_templates_escape_every_value.py` to every template added since: the GST digest, notices, email-in replies and
     supplier reminders.
3. **Extend the red-team corpus** (`tests/fixtures/corpus/`) with:
   - hidden white-on-white text;
   - injection in a table cell;
   - in a file name;
   - in an email-in subject and body;
   - in a QR payload;
   - in a GSTR-2B trade name;
   - in Hindi;
   - in a supplier's upload through a request link.

   For each, the test asserts that **nothing changed state beyond the ordinary processing of that document**, and that the
   injection was flagged where the product flags it.
4. **Fix every gap test-first,** and record the findings.

## 7. Phase 4 (P1): Final session 1's leftovers

0. **Do this first, before Phase 1: `main`'s red speed test** (§0).
   - Measure the GST recompute step by step, as Session H did: read, reconcile, write, and whatever Final session 1 added after it.
   - If Final 1 made it slower, make it fast again, test-first, and keep `test_matching_equivalence.py` green.
   - If it is only the CI machine, show that with timings from at least three CI runs, record it in PERFORMANCE.md, and make the
     test report its step timings when it fails, so the next red run explains itself. The budget does not move.
   - `main` must be green before this session's PR is ready.
1. **Warning emails after deletion** (N-164). After a customer deletes a workspace or organization:
   - one email at once ("will be erased on <date>; restore until then");
   - one 5 days before the purge ("last chance to restore").

   The audience is owners and admins. The emails are sent once, through the existing job and email patterns. Test it with a
   controlled clock.
2. **The global upload tray accepts a zip,** through the same path as the Documents page (spec 118's rules).
3. **Migration `k1a6`'s downgrade** with delivery rows present: prove it, or make it safe, test-first.
4. **The owner's lockfile commit:** confirm `npm ci` from the committed lockfile and the frontend job are green.

## 8. Phase 5 (P1): the proof kit (accuracy and the first pilots)

**Why it earns money:** "92% match confidence" on a screen sells nothing by itself. "**98% of fields right on 120 real Indian
GST invoices, measured**" and "**₹3.2 lakh of GST credit protected in 30 days for <customer>**" do.

1. **`backend/scripts/accuracy_report.py`:** measured accuracy on real documents.
   - **Input:**
     - a folder of documents already processed in a workspace (by id or tag);
     - a **truth sheet** (CSV) the owner fills in: one row per document, one column per field.
   - Ship a template with the finance-schema fields Helm and GST read: invoice number and date, vendor and buyer GSTIN,
     taxable value, CGST, SGST, IGST, total, place of supply, due date, and HSN on lines (optional).
   - **Output:**
     - field-level accuracy (exact after normalisation: amounts to the paisa, dates, GSTIN case and spacing);
     - document-level "all key fields right";
     - the review queue's catch rate (how many wrong fields were sent to review rather than passed through);
     - a list of every miss with its document.
   - Write a Markdown report fit to show a customer, with no document content beyond the field names and counts.
   - **Tests:** with the stand-in and an invented truth sheet.
   - **Final 2B runs it on the owner's real invoices.**
2. **`docs/product/PILOT-PLAYBOOK.md`:** how to run a 30-day paid pilot with a distributor, ideally introduced by their CA:
   - the offer (for example the first month at a pilot price, recorded as an owner decision);
   - what to collect on day 1 (one month of purchase invoices, the GSTR-2B, the supplier list, the Tally or Zoho export);
   - what to measure (accuracy, the time from invoice received to entered, rupees found, rupees **verified** recovered if
     Phase 6 is built, the review queue's size);
   - the weekly check-in;
   - what "success" means in numbers;
   - the case-study template.

   Plain words, a few pages.

## 9. Phase 6 (P1, only if Phase 0B said "build"): the Resolution layer

Build it **thin**, on top of what exists. Name it in plain words: for example a "Recoveries" page with **Found → Being fixed →
Verified** columns. Record the final name.

1. **One read model, not a new source of truth.** It covers the issue kinds 0B proved worth it (expected: GST credit at risk,
   duplicate, price or quantity above the order, supplier statement difference, payment deadline). Follow the review hub's
   pattern (`services/review/projection.py`: a projection over the engines' own tables), with the workspace predicate in one
   place.
2. **Each issue shows:**
   - its **rupee exposure, read from the engine's stored figure** (never estimated; none for kinds without a supportable
     figure, such as a changed bank account);
   - the evidence (documents, lines, the engine's page);
   - an **owner** (assign);
   - a **due date** from the law or the terms (the 180-day rule, MSME 45 days, the supplier's terms);
   - the **next actions**, which are the existing ones: request a document, remind the supplier, Helm's drafted email, hold
     via the Guard, open a dispute.

   **No new action may move money (Phase 3's invariant).**
3. **Closure only on evidence,** one rule per kind:
   - **GST:** the invoice appears in a later GSTR-2B, or a credit note settles it;
   - **duplicate:** confirmed and never paid (Helm's existing rule);
   - **overcharge:** a credit note, or a re-read at or below the order price;
   - **statement difference:** explained, or zero after a new statement or a ledger entry;
   - **deadline:** paid on time, with evidence (a payment mark or a bank line).

   A person may close an issue as **"Not money: <reason>"**. That is recorded, and **never counted as recovered**.
4. **One outcome ledger, counted once.** Extend Helm's value-held ledger idea (`helm/value.py`: dedupe keys, evidence,
   withdrawal when the evidence is undone) to the new kinds, for example `ITC_SECURED`. **Do not double count:** an outcome
   Helm already records is the same row, not a second one. Write a test for every pair of engines that could both claim one
   outcome.
5. **Where it shows:**
   - the value receipt and the monthly summary gain **"Recovered, verified"** beside **"Found"** (never added together;
     Session G's honesty rules);
   - the GST digest gains one line: "3 issues worth ₹2.4 lakh need an owner";
   - Getting started's money step links here.
6. **Plans:** Business and Enterprise. Starter sees the counts and the total found as a preview, with the upgrade moment.
7. **Tests:**
   - each closure rule (a click alone never closes as money);
   - the double count;
   - isolation through a second workspace (the route sweeps);
   - the plan gate;
   - one browser spec walking an issue from found to verified on the sample company, with axe in light and dark.

If 0B said "do not build", write instead what Final 2B should measure about today's flow during the pilot, and stop.

## 10. Phase 7: records and the docs that customers see

- **Update:**
  - `PRODUCT-NEXT.md` (what this session did; the next list after the first pilots);
  - `COSTS.md`, `RUNBOOK.md`, `CONFIGURATION.md`, the env templates;
  - `DODO.md`, `DODO-LOCAL-TEST.md` (a rupee journey, the mandate notice, the GSTIN check);
  - the website (pricing, the product pages' honest lines for the Resolution layer if built, the trial length);
  - `CHANGELOG.md`, `FINDINGS.md`, `COVERAGE.csv`, `NEEDS-OWNER.md`.
- **`docs/FINAL-SESSIONS.md`** (the owner's guide): what 2A did, in plain words, and anything new the owner must prepare for
  2B. For example: a Dodo test-mode UPI or Indian test card if Dodo offers one, 30 to 50 real invoices **with their truth
  sheet filled in**, and the GSTIN he will use to buy.

## 11. Phase 8 (must): rewrite the live session's prompt to match reality

`docs/sessions/FINAL-2-LIVE.md` was written before Final session 1 and this session. Rewrite the parts that changed, keeping its
rules, its structure and everything still true. **Remove the "Do not run this yet" note at its top** once the rewrite is done:

1. **Its §0 and start-up:** what exists now (Final 1 and 2A), and the hand-over it must read first (step 2 below).
2. **Dodo (its Phase 8):**
   - the full product list, in both currencies;
   - a **rupee journey** (UPI or an Indian card in test mode, if Dodo offers one);
   - the ₹15,000 mandate notice;
   - **the buyer's GSTIN and the CGST, SGST or IGST lines on Dodo's invoice**;
   - the yearly add-on;
   - the custom domain refused on Starter.
3. **Documents (its Phase 3):** run `accuracy_report.py` on 30 to 50 of the owner's real invoices with the truth sheet, and
   publish the result in `LIVE-VERIFICATION.md` and `COMMERCIAL-READINESS.md`.
4. **The production rehearsal (its Phase 15):**
   - install the host jobs with `servabo-install-host-jobs`;
   - see every safety job report;
   - **stop cron and see the stale alert** (with a shortened deadline for the rehearsal only);
   - restore.
5. **Prompt injection:** the red-team documents of Phase 3, uploaded through the real models. Nothing may change beyond
   ordinary processing.
6. **The Resolution layer** (if built): walk one real issue from found to verified on the owner's own data, or on the sample
   company if none occurs.
7. **The deletion warning emails** in a real inbox.
8. **Every "Not checked" reason** that this session removed or added.

Also write a section **"Final session 2A → Final session 2B"** in `docs/hardening/HANDOFF.md`, in the shape of Final 1's hand-over:

- a table of what 2B must try for real (feature, settings, how to turn it on, the stand-in that proved it, what real success
  looks like);
- the commands 2B can use;
- what was not reached;
- what is unverified, in plain words.

## 12. Finish line

- **Phases 1, 2, 3 and 8 are done and tested.** Phases 4 to 7 as far as usage allowed, each item either done with tests or
  listed as not reached. Phase 6 is built or explicitly declined, with the reason.
- **These pass,** locally or on the ready PR's CI:
  - `pytest -q`;
  - the frontend's typecheck, lint, `check:self`, `test:unit` and build;
  - the website's checks;
  - the full browser suite.
- `campaign_slices.py --check all` exits 0. There is one Alembic head, with up, down and up.
- **Records:**
  - `COMMERCIAL-READINESS.md`, `RESOLUTION-ASSESSMENT.md`, `PROMPT-INJECTION.md`, `PILOT-PLAYBOOK.md`;
  - `FINDINGS.md`, `COVERAGE.csv`, `STATE.md` (next action: Final session 2B), `HANDOFF.md`, `NEEDS-OWNER.md`, `CHANGELOG.md`;
  - the rewritten `FINAL-2-LIVE.md`, and `FINAL-SESSIONS.md`.
- **Mark the PR ready.** The description explains, for a non-engineer:
  - the new prices and why;
  - what keeps the safety jobs honest;
  - what stops a malicious invoice;
  - whether the Resolution layer was built and why;
  - what Final 2B will now check.
- **CI is green before the owner merges.** Then stop, and tell the owner in eight lines or fewer:
  - the prices;
  - what was fixed;
  - the Resolution decision;
  - what is still unproven;
  - that Final 2B is next.
