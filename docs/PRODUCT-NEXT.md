# What to build next

_Rewritten at the end of Final session 1 (2026-10-22), when most of the first list had been built. It is true today: every old item has a status, and
the ranked list after it is for after the first paying customers._

Billing is Dodo Payments (it was Stripe once; where an old note says Stripe, it means Dodo). Build cost is in focused engineering days for one person who
knows the code: an estimate, not a promise. Running cost is what the idea adds to the monthly bill (`docs/hardening/COSTS.md` has the baseline).

**TRINETRA update (2026-10-26):** the current request adds a gated business-TDS
review workflow, without changing the separate Final 2A pricing plan. Its implemented
surfaces, test evidence and remaining official-format, adviser, pilot and product
acceptance work are tracked in [trinetra/DELIVERY.md](trinetra/DELIVERY.md) and
[trinetra/LAUNCH-GATES.md](trinetra/LAUNCH-GATES.md). It is not approved for live tax processing.

## 1. What happened to the first list

| # | Idea | Status |
| --- | --- | --- |
| 1 | Email-in: forward invoices to a workspace address | **Done** (Final session 1). Postmark inbound; listed senders are read at once, anyone else's mail is held for an administrator. Not yet tried with a real Postmark server (HANDOFF) |
| 2 | Final overage invoice on cancellation | **Not applicable** while Dodo bills hard limits (N-118): there is no overage to collect |
| 3 | Yearly billing switch | **Done.** The owner creates the yearly prices in Dodo and sets their ids (RUNBOOK 9.3) |
| 4 | Error tracking the owner can read | **Done** (Final session 1). Sentry (EU region) or GlitchTip; off until the DSN is set; scrubbed before sending. Not yet receiving from the real service (HANDOFF) |
| 5 | Accounting-system connections | **Done for India** (Final session 1): Zoho Books "Connect" and a guided Tally Prime file. **Xero and QuickBooks Online later, for other markets** (QuickBooks left India in 2023). Zoho is untried against real Zoho; Tally untried in real Tally (HANDOFF) |
| 6 | Archive (zip) upload | **Done** (Final session 1). One zip becomes its documents, through the ordinary intake path |
| 7 | Premium models as credits | **Not started** (see 2.4) |
| 8 | Industry benchmarks | **Not started** (see 2.6; needs many customers) |
| 9 | Correct a field beside the page | **Done** earlier (`f53ccc8`: `field_correction_service.py`, `PATCH …/work-items/{id}/fields`, `ExtractedFieldsPanel.tsx`) |
| 10 | Packs that do everything they recommend | **Done** (Final session 1, F-408): enabling a pack proposes its checks under Clause assertions, one click to add each; the Redact menu offers the pack's profile first. Twelve of the fourteen shipped checks are read by an AI model and billed as assistant usage (N-181) |

Also done in Final session 1, from the same ambition: the data lifecycle (what erasure, retention, deletion and the export do with every table), refreshed
AI model lists and libraries, the GST Monday email and notices, upgrade moments that name the right plan, the e-invoice QR badge, `preflight.py`, public webhook
events for GST and workflow runs (docs/product/WEBHOOK-EVENTS.md), warehouse datasets for GST matches and the Helm ledger (Enterprise), global search for GST and
workflows, resizable sidebars, the new logo, and a sweep of every organization console tab.

## 1b. What Final session 2A did (2026-10-27)

- **Sellable in India** (N-187): prices in rupees and yearly for every plan, rupee checkout with GSTIN, the ₹15,000 mandate
  notice, a 14-day trial, "Developer" renamed Starter, custom domains in Business and Enterprise, the Tally Prime file on
  Starter. Margins checked in every currency (COSTS.md §4).
- **Safety jobs report and alert** (N-194): every cron job on the server reports its runs; a stopped one is emailed once a day.
- **Prompt injection mapped and tested** (docs/hardening/PROMPT-INJECTION.md): six fixes, six invariants walked in the code.
- **Leftovers:** deletion warning emails, a zip on a conversation's upload tray, the GST speed test's step timings.
- **The proof kit:** `scripts/accuracy_report.py` and `docs/product/PILOT-PLAYBOOK.md`.
- **Recoveries** (N-191, `docs/product/RECOVERIES.md`): money issues from Found to Being fixed to Verified, closed only on
  evidence, counted once beside what was found. Built in 2A at the owner's request (2026-10-27), with N-197 (ERP auto-post
  waits for a person on an outside upload) and N-198 (the pilot price) decided.
- **The email logo** (N-199) and a person's re-plan that waits for a running plan (F-637).

## 2. A new list, for after the first paying customers

### 2.0 Recoveries, next kinds (N-191 built the first five)

Built: GST credit waiting, duplicates, prices above the order, supplier statement differences, payment deadlines. Next, in
the order the pilots' numbers suggest: TRINETRA's "TDS not yet in the statement" (Final session 2T adds it through one
adapter), then quantity differences against the goods receipt, then an assignee's email when an issue is given to them.
About a day each. No running cost.


Best first. "Earns money" says how the idea turns into revenue or protects it. Nothing here changes a price, a plan or a trial until the owner decides it.

### 2.1 Chartered accountants as a channel (CA firms)

**What:** one chartered accountant files GST for 20 to 200 small clients. Give them one screen that shows the GST position of **every client** (claimable now,
waiting for suppliers, near the 180 days) and let each client be an organization under the accountant. Servabo already has the tenancy for it: the partner
portal and reseller tenancy (ARCH-27) read across a book of organizations, and the GST pages already total across workspaces.

**Earns money:** one relationship brings many organizations. A CA who sees 40 clients' GST credit in one place has a reason to put all 40 on Servabo, and to
recommend it to the next firm. It is the only idea here that sells to many customers at once.

**Build:** about 10 days (a multi-client GST summary in the partner portal, an invitation flow for a client to join a CA's book, plan and billing per client).
**Run:** nothing beyond compute. **Decide first (the owner):** the reseller margin or referral fee; nothing about it is in the product.

### 2.2 WhatsApp-in: invoices sent on WhatsApp

**What:** Indian suppliers send invoices as photos and PDFs on WhatsApp. A workspace would get a WhatsApp number to forward to, as it has an email address.

**What it takes** (written down so the owner can decide; check Meta's pages for today's rules and prices before committing):
1. A **Meta Business account, verified** (company documents; days to weeks).
2. A **phone number dedicated to the WhatsApp Business Platform** (not one already used in the ordinary WhatsApp app).
3. A **Cloud API app**, a webhook that checks Meta's signature (`X-Hub-Signature-256`), and a token to download each attachment.
4. A **list of allowed senders per workspace**, as email-in has: only a listed phone number is read at once; anyone else's message is held for an administrator.
5. **Privacy:** a short notice to the sender that the message is processed, and a retention rule for the held messages (the DPDP Act applies).
6. **Cost:** Meta prices messages by kind (the rules for a reply and for a message Servabo starts, such as "we could not read your photo", differ, and change), and a
   solution provider, if used, adds a fee. Read Meta's current price list before deciding; expect a small monthly line, not a per-document line.

**Earns money:** it removes the last manual step for the customers whose suppliers will never email. **Build:** about 8 days, most of it reusing email-in's intake,
hold queue and tests. **Run:** the message fees above. **Do it after** customers ask; it is the largest outside dependency on this list.

### 2.3 An annual price and a rupee price for the GST Credit add-on

**Done in Final session 2A (2026-10-26, N-187):** $49 or $490 a year, ₹1,499 or ₹14,990 a year, each its own Dodo product; every plan has rupee prices too. What follows is the original note.

**Status (2026-10-23):** decided (N-187: ₹1,499 a month or ₹14,990 a year; $490 a year beside $49 a month) and scheduled
in Final session 2A (`docs/sessions/FINAL-2-UPGRADE.md`), together with rupee prices for every plan.

**What:** the add-on is a monthly dollar price today (Session H). Offer a yearly price (about two months free, as the plans have) and a price in rupees.

**Earns money:** yearly payers pay up front and leave far less; an Indian owner-manager weighing a $49 line against a rupee bill often stops at the dollar sign.
It is the cheapest experiment on the list.

**Build:** about 1 day in the code (the price book already carries an interval; the add-on catalogue gains the two prices) plus the Dodo products. **Check first:**
whether Dodo collects rupees by UPI and cards for your account, and what it charges for it. **Run:** none. **Decide first (the owner):** the two prices.

### 2.4 Premium models inside the plans, counted as credits (old #7)

**What:** let plans include the dearer models by counting one of their tokens as several of the default model's (N-054, "reversible later").

**Earns money:** a customer who wants the strongest model today must bring their own key. Credits let a Business customer use it without a second vendor account and
let you price the dearer tokens at twice cost or more. **Build:** about 5 days (a credit unit, every usage screen and limit email in credits, migration of the
allowances). **Run:** the dearer model's tokens. Do it after the model lists settle (they were just refreshed, F-564 to F-566).

### 2.5 The automation Wait step (N-154)

**What:** a step that pauses a run for some hours or days, or until a date, and then continues: "remind the supplier at day 7, and again at day 14 if nothing came".

**Earns money:** it turns the GST reminder from one message into a follow-up that really recovers credit, and it is the first thing a power user of automation asks for.
**Build:** about 6 days (a stored, resumable run state, a scheduled resume job, the run history showing "waiting until"). **Run:** none.

### 2.6 Industry benchmarks (old #8)

**What:** "your supplier prices rose 8% this year; similar companies saw 3%", from anonymized, aggregated data of organizations that opt in.

**Earns money:** a differentiator nobody with a single customer's data can copy. **Build:** about 15 days, most of it privacy work (opt-in, aggregation thresholds so no
customer can be singled out, the owner's legal review). **Run:** a small nightly job. **Only worth doing** once there are enough customers for the numbers to mean something.

### 2.7 Tailwind 4 (removes N-119)

**What:** the styling tool is a major version behind (N-119 records why it stayed: the audit advisories sit in its build tooling, not in what ships).

**Earns money:** indirectly. It clears the build-tool advisories that make the front-end security job noisy, so a real advisory is easier to see. **Build:** about 3 days
(the class names are mostly unchanged; the work is the configuration and a visual pass). **Run:** none.

### 2.8 Smaller things worth doing when there is a quiet week

- **Xero and QuickBooks Online** connections, for a customer outside India (about 10 days for both; QuickBooks is not sold in India).
- **Tally for Developer** (N-174, OPEN): it is a file, needs no live connection, and is what many small Indian businesses use. A plan decision.
- **The GST and Helm warehouse datasets for Business** (N-180, OPEN): a plan decision.
- **Day-1 and day-25 emails after a customer deletes a workspace** ("it will be erased on…", "last chance to restore"): the data is purged by the sweep, but nothing warns the customer.
- **The global upload tray accepts a zip** (the Documents page does; the tray in the corner of every page does not take one yet).
- **A shared "could not be loaded, try again" block** for the nine organization console pages (80 files in the app repeat it; it is consistent and tested, so it is polish).
- **The failed-run webhook says why** (N-179, OPEN): today it carries ids and a state, not the error text, which can hold document content.

---

**Recommendation (2026-10-22, after launch):** do **2.3 first** (about a day, only the catalogue and two Dodo products, and it answers the objection Indian buyers raise most), then
**2.1** (the only item that sells to many organizations through one relationship). Keep **2.2** until customers ask for it, because it is the biggest dependency on someone else's
platform, and leave 2.4 to 2.7 until usage tells you which of them hurts.
