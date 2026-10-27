# The final sessions: what they are, and how to run them

_Written 2026-10-22 for the owner; updated 2026-10-23 when the upgrade session (2A) was added, and 2026-10-26 after TRINETRA.
Plain language, no prior DevOps knowledge assumed._

## 1. Where things stand (2026-10-23)

- **Sessions A to J are merged, and so is Final session 1** (PR #37). Every item on its checklist is done; its CI run (#462)
  and the run on `main` after the merge (#464) were green on every job, the advisory `pip-audit` included.
- **What Final session 1 left open is listed honestly** in `docs/hardening/HANDOFF.md`, "Final session 1 → Final session 2":
  - nothing that talks to an outside service has been tried against the real service;
  - a few small things were not reached, for example the warning emails after a customer deletes a workspace.
- **You then asked four commercial questions before the live tests:**
  - Are the prices right for India?
  - Why does the custom-domain price contradict itself?
  - What if the server's scheduled jobs stop?
  - Can a malicious invoice steer the AI?

  You also proposed an "Evidence-to-Resolution" idea, to be built only if it is truly needed and truly earns money.
  **Session 2A answers these before the live tests.**
- **Since then (2026-10-23 to 26) two more changes were merged:**
  - **PR #39** redesigned the Documents and AI Assistant screens;
  - **PR #40, TRINETRA**, checks that the TDS your customers withhold from your invoices really shows up in your tax
    statement. It is merged and its checks passed, but it is **switched off for customers** until real statement files, a tax
    adviser and a pilot customer have confirmed it. Today customers see a synthetic preview only.
- **A review of TRINETRA (2026-10-26) found real gaps,** and its original brief is only partly built. You want it on Business
  and Enterprise, working like every other feature. So it now has **its own session, 2T, right after 2A**, which fixes the
  gaps and finishes it. The most important gaps:
  - a confirmed TDS deduction made Helm stop reminding the customer about the whole invoice, even the cash still owed;
  - renaming a document made its tax evidence count as "changed";
  - the check that the invoice is really yours ignored the GSTIN;
  - a Business customer would be stopped for good after 12 statement uploads or 500 cases;
  - there was no way to switch TRINETRA on for **one** pilot customer only.

  HANDOFF "TRINETRA review and the revised session 2A" lists everything; "Plan change: Final session 2T…" says what 2T builds.

## 2. The sessions, in order

| | **Final session 1** (done) | **2A: upgrade** (next) | **2T: TRINETRA** | **2B: live** |
| --- | --- | --- | --- | --- |
| **What** | Study the whole project, bring it up to date, build the money features (email-in, zip upload, GST digest, Zoho/Tally, Sentry, `preflight.py`, …) | Prices for India in rupees; the custom-domain fix; safety jobs that cannot stop silently; a prompt-injection map and tests; Final 1's leftovers; an accuracy report and a pilot playbook; assess Evidence-to-Resolution and build a thin version only if it passes the test; **rewrite the live prompt to match reality** | **TRINETRA finished for Business and Enterprise:** every line of its original brief, every integration other features have, the review's gaps fixed; statement readers instead of typing; sending inquiries; approval chains; a switch for one pilot customer, then for everyone | Test **everything for real** on your PC: real AI and OCR, your real invoices (with the accuracy report), real GST files, **TRINETRA with your own Form 26AS / AIS**, Dodo test payments in rupees and dollars, real emails, Slack, Zoho Books, Tally, Sentry, a production rehearsal |
| **Where** | Claude Code on the web | Claude Code **on the web** | Claude Code **on the web** | Claude Code **in VS Code on your PC** |
| **Model** | Opus 5.5, High | **Opus 5.5, High** | **Opus 5.5, High** | Sonnet 5.5, High (Opus 5.5 for a stubborn defect) |
| **You** | — | Mostly away; type `continue` after a usage reset; merge at the end | The same | **Present**: about 1 hour at the start, then short moments over the day |
| **Prompt** | [`FINAL-1-UPGRADE.md`](sessions/FINAL-1-UPGRADE.md) | [`FINAL-2-UPGRADE.md`](sessions/FINAL-2-UPGRADE.md) | [`FINAL-2T-TRINETRA.md`](sessions/FINAL-2T-TRINETRA.md) | [`FINAL-2-LIVE.md`](sessions/FINAL-2-LIVE.md) (2A and 2T rewrite it before you run it) |
| **Cost** | Zero | Zero | Zero | Zero (free plans; Dodo **Test Mode**, no real money) |

**Run them in this order:** 2A, then 2T, then 2B. 2B tests what 2A and 2T change, and both update 2B's prompt and the
preparation list below.
Wherever older documents say "Final session 2", they mean 2B, the live session.

### The decisions you delegated, now written down (N-186 and N-187)

- **No new engines.** Servabo already has more engines than one person can sell. 2A makes the existing product cheaper to
  buy, safer to run and provable.
- **The focus:** Indian distributors, wholesalers and manufacturers, and the CA firms that serve them. Servabo finds money
  leaking out of supplier invoices (GST credit at risk, overcharges, duplicates, missed deadlines), helps get each one fixed,
  and shows the rupees it can prove.
- **Prices in India, per user per month, GST extra:**
  - Starter (today's "Developer") ₹1,499;
  - Business ₹4,999;
  - Enterprise ₹14,999;
  - yearly is ten months' price;
  - the GST Credit add-on for Starter is ₹1,499 a month or ₹14,990 a year;
  - the dollar prices stay as they are.
- **The free trial becomes 14 days** with 100 documents, so one monthly GSTR-2B fits inside it.
- **Custom domains** are included on Business and Enterprise and no longer sold separately (the $199 price is retired).
- **The Tally Prime file** comes to Starter.
- **TRINETRA was your one exception to "no new engines"** (N-188). Nothing else new starts before the first pilots (N-189).
- **TRINETRA goes to Business and Enterprise** (N-190):
  - 2T finishes it, and ships it in "pilot" mode (live only for organizations you enrol);
  - 2B proves its statement readers on your own files;
  - your CA reads its wording (about an hour);
  - you switch it "on" for everyone on Business and Enterprise.
  - TCS, payroll TDS, filing and tax advice stay out on purpose.

## 2b. What Final session 2A did, in plain words (2026-10-27)

- **Prices in rupees.** Starter ₹1,499, Business ₹4,999, Enterprise ₹14,999 per user a month (GST extra), and yearly
  prices. Indian businesses pay in rupees by UPI or card with their GSTIN; dollars stay for everyone else. The trial is now
  14 days, and "Developer" is called **Starter**.
- **The server's scheduled jobs can no longer stop silently.** If cron stops, you get an email the next day and the admin
  page turns red. One command installs them: `servabo-install-host-jobs` (RUNBOOK 9.6).
- **A malicious invoice cannot make Servabo pay or email anyone.** An email address read from an invoice is never used
  until you confirm it; Helm never takes a payment decision on its own; documents are fenced as data in every AI prompt.
  `docs/hardening/PROMPT-INJECTION.md` has the full map. **One thing for you:** Helm, Settings, Suppliers and customers:
  confirm each supplier's email address once ("Use this address").
- **A way to prove accuracy:** `backend/scripts/accuracy_report.py` with the truth sheet
  `backend/scripts/accuracy_truth_template.csv`. And `docs/product/PILOT-PLAYBOOK.md` for your first paid pilot.
- **Not built:** the "Recoveries" page (decided, deferred to after the first pilots).
- **Decisions waiting for you:** N-193 (the GSTIN on Dodo's invoice, checked in 2B), N-197 (ERP auto-post and outside
  uploads), N-198 (your pilot price). All in `docs/hardening/NEEDS-OWNER.md`, each with a recommendation.

## 3. How to run Final session 2A (the upgrade)

1. **Merge the pull request that added this guide's update,** once its CI is green.
2. **Check that `main` is green:** on GitHub, open **Actions**, then the latest run on `main`. Every job needs a green tick.
3. Open **claude.ai/code** and start a new session on the `servabo` repository. Choose **Opus 5.5** and **High** effort.
4. Paste this one sentence:

   > Read `docs/sessions/FINAL-2-UPGRADE.md` on `main` and carry it out from section 0. Never stop to ask me.

5. **Leave it running.** If it says your usage limit is reached, come back after the reset and type `continue`.
6. **At the end** it marks its pull request "ready". Then:
   - read the description (it is written for you);
   - wait until every CI job is green;
   - press **Merge**.

   **Never merge while a CI job other than `pip-audit (advisory)` is red.**
7. **Read the two short pages it writes for you:**
   - `docs/product/COMMERCIAL-READINESS.md`: can this be sold, to whom, against whom;
   - `docs/product/PILOT-PLAYBOOK.md`: how to run your first paid pilot.

   Then re-read §4 below: 2A may have added something to prepare.

## 3b. How to run Final session 2T (TRINETRA)

The same way as 2A, once 2A is merged and `main` is green. Choose **Opus 5.5**, **High**, and paste:

> Read `docs/sessions/FINAL-2T-TRINETRA.md` on `main` and carry it out from section 0. Never stop to ask me.

It is a big session. Type `continue` after each usage reset; it has no cut line, because its goal is that nothing is left behind.
At the end, read `docs/trinetra/COMPLETION.md`: every line of your original TRINETRA brief, with what was done and where. Merge
only when every check is green.

## 4. Before Final session 2B (live): what to prepare (about 1 to 2 hours, all free)

Do this before you start Final session 2B. Anything you cannot get is simply skipped and marked "Not checked". **Nothing
blocks the session.**

**Golden rule.** Keys and passwords go **only** into `backend\.env` (or `frontend\.env` where noted), typed by you. **Never paste
them into the chat.** If you do by accident, rotate that key afterwards.

### 4.1 Your PC

- **Docker Desktop** running, **Python 3.12**, **Node 22 or newer**, **Git**, and VS Code with the **Claude Code** extension.
- **At least 40 GB of free disk** (the production rehearsal builds about 10 GB of images) and, ideally, 16 GB of memory.
- **Optional:** WSL 2 with Ubuntu (it lets the full browser test suite run on your PC). Docker Desktop usually installs WSL 2
  already.
- Then:
  - in your `servabo` folder, run `git checkout main` and `git pull`;
  - run `.\start_dev.ps1` once, to check that it still starts;
  - run `.\start_dev.ps1 -Stop`.

### 4.2 Free accounts (only the names of the settings are shown; the values are yours)

| Account | What to do | Into `backend\.env` |
| --- | --- | --- |
| **Groq** | You have it. If the key was ever pasted into a chat, make a new one at console.groq.com/keys and delete the old one. | `GROQ_API_KEY` |
| **Google AI Studio** (Gemini) | aistudio.google.com → **Get API key**. Free plan: Google may use what you send to improve its products, so use it only with your own or invented documents. | Typed into Servabo's **BYOK settings** during the session; nothing in `.env` |
| **Dodo Payments** | You have it. **Test Mode** on; keep the test API key ready. | `DODO_API_KEY`, `DODO_LIVEMODE=false` (the rest during the session) |
| **Gmail (sending email)** | Google Account → Security → turn on **2-Step Verification** → **App passwords** → create "Servabo" → copy the 16-letter password. (If "App passwords" is missing, use **Brevo**'s free plan and its SMTP key instead.) | `PLATFORM_SMTP_HOST=smtp.gmail.com`, `PLATFORM_SMTP_PORT=587`, `PLATFORM_SMTP_ENCRYPTION=TLS`, `PLATFORM_SMTP_USERNAME` = your Gmail, `PLATFORM_SMTP_PASSWORD` = the app password, `PLATFORM_SMTP_FROM_EMAIL` = your Gmail |
| **Postmark** (email-in) | postmarkapp.com → sign up (free developer plan) → create a server "Servabo local" → open its **Inbound** stream → copy the inbound address (`…@inbound.postmarkapp.com`). The webhook is set during the session. | The names Final 1 documents (the HANDOFF section "Final session 1 → Final session 2") |
| **Sentry** (error tracking) | sentry.io → sign up, and choose the **EU** data region when you create the organization (it cannot be changed later) → create a **Python/FastAPI** project and a **React** project → copy both DSNs. | `SENTRY_DSN`; the React one goes into `frontend\.env` as `VITE_SENTRY_DSN` |
| **Slack** | Create a free workspace → api.slack.com/apps → **Create App** → **Incoming Webhooks** → turn on → **Add New Webhook to Workspace** → pick a channel → copy the URL. | Typed into Servabo's **Webhooks** page during the session |
| **Zoho Books** (India) | zoho.com/in/books → sign up for the **Free** plan → create an organization (test details are fine). Then api-console.zoho.in → **Add Client** → **Server-based Applications** → use the redirect address Final 1 documents → copy the client id and secret. | `ZOHO_CLIENT_ID`, `ZOHO_CLIENT_SECRET`, `ZOHO_REDIRECT_URI` (check the exact names in the HANDOFF section) |
| *Optional:* **Tally Prime** | Download TallyPrime from tallysolutions.com, install, choose **Educational mode**, create a test company. | Nothing |
| *Optional:* **Microsoft Teams** | In a channel: **Workflows** → "Post to a channel when a webhook request is received" → copy the URL. | Typed into Servabo's Webhooks page |
| *Optional:* **Okta** or **Entra ID** | An Okta Integrator (free) or an Entra ID test tenant, for one enterprise sign-in test. | Typed into Servabo during the session |

### 4.2b New since Final session 2A

- **The GSTIN you will buy with** (yours, or a friendly business's with permission): 2B buys Servabo once in rupees in Dodo's
  test mode and checks what Dodo's invoice shows (N-193).
- **A Dodo test-mode UPI ID or Indian test card**, if Dodo's test-mode documentation offers one (2B looks it up with you).
- **A long random secret for the server's safety jobs:** 2B generates it with you
  (`python -c "import secrets; print(secrets.token_urlsafe(32))"`); it goes in `.env.production` and
  `/etc/servabo/sweepers.env` as `SAFETY_JOB_REPORT_TOKEN`. Never paste it into a chat.

### 4.3 Real files, in `C:\servabo-live\` (never inside the `servabo` folder)

- **Five to ten real GST tax invoices** (PDF or scans). Your own online-shopping tax invoices (Amazon, Flipkart and the like)
  are real GST invoices and are fine. A friendly distributor's invoices are fine **with their permission**.
- **If you can, 30 to 50 real purchase invoices with their truth sheet** (the template is
  `backend/scripts/accuracy_truth_template.csv`: one row per invoice, the correct invoice number, date, GSTINs, tax amounts
  and total; dates as on the invoice, for example 05/09/2026). 2B turns them into a **measured accuracy
  figure** you can show customers. It is the single most convincing number for a first sale.
- **One printed page photographed at a slight angle**, and **one handwritten bill** (photos from your phone).
- **One zip** of 20 or more invoices (copies are fine).
- **Optional, from your CA** (worth asking for; it turns "unverified" into "confirmed"):
  - **one real GSTR-2B JSON** (GST portal → Returns dashboard → GSTR-2B → **Download JSON**; any month, any client);
  - **one real e-invoice PDF** (an invoice with an IRN and a signed QR code, usually from a large supplier);
  - **NIC's public key** for checking the QR signature, if the CA knows where to get it.
- **For TRINETRA** (2B proves its statement readers with these; never committed, never pasted into a chat):
  - **your own Form 26AS:** income tax e-filing portal → e-File → Income Tax Returns → View Form 26AS → TRACES → download it as
    **Text** (menu names may have changed since Form 168 replaced the name; 2B guides you). Any PAN holder can download his
    own; the layout is what matters, not the amounts;
  - **your own AIS:** e-filing portal → AIS → the TDS/TCS information → download **CSV**;
  - if possible, one sales invoice on which a customer deducted TDS, and that customer's TDS certificate (Form 16A).

## 5. How to run Final session 2B (live)

1. Make sure Final session 2A is **merged** and `main` is green. Then run `git pull` on your PC.
2. Start Docker Desktop.
3. Open VS Code in your `servabo` folder, then the **Claude Code** panel. Choose **Sonnet 5.5**, **High**.
4. Paste:

   > Read `docs/sessions/FINAL-2-LIVE.md` and carry it out from section 0, on this PC, with me.

5. **Claude asks before each command.** Read the request and allow it. Say **no** to anything that deletes things (Docker
   volumes, `reset_dev.ps1`, `git reset --hard`) unless it has told you why and you agree.
6. **It tells you, phase by phase, what it needs from you:** a click in Dodo's test checkout, a photo, a key typed into
   `.env`, reading an email on your phone. Everything else it does itself.
7. **Whenever it starts something that keeps running** (the app, a tunnel), it also stops it. If you must leave, say so; it
   stops what is running.
8. **At the end** it gives you a pull request and a ten-line summary. Wait for CI to be green, then merge.

**What you get:**

- `docs/hardening/LIVE-VERIFICATION.md`: every feature marked **Confirmed**, **Differs → fixed**, **Differs → open** or **Not
  checked (why)**;
- every real-world difference fixed, with a test;
- a ten-minute **live smoke suite** (`frontend/e2e-live/`) to repeat before every release;
- a rehearsal of the production start-up, backup and restore on your PC.

## 6. After the sessions: launch

Open `docs/hardening/HANDOFF.md`, **"Owner launch checklist"**. Final session 2B will have ticked what your PC could prove
(Dodo test mode, the real-model checks, the production rehearsal). What remains needs money or a public address, so only you
can do it:

1. rotate old keys;
2. the domain on Cloudflare;
3. the website online;
4. Dodo's business verification;
5. Postmark with your domain;
6. the Hetzner server;
7. the install;
8. and the following steps, then live mode;
9. **TRINETRA:** after 2B marks its readers verified, your CA reads `/trinetra` and the in-app wording; then set its mode to "on".

`preflight.py --online` on the server tells you what is still missing.

## 7. If something goes wrong

- **"Usage limit reached":** come back after the reset and type `continue` in the same session. Do not start a new session for
  the same work.
- **CI is red on a pull request:** do not merge. Start a small new session, paste the link to the failed run, and ask it to
  find the cause and fix it test-first.
- **You pasted a secret into a chat:** create a new key in that provider's dashboard, delete the old one, and put the new one
  in `.env`.
- **The PC cannot start the stack:** in Final session 2B, tell Claude what you see. It reads `.dev\logs` and fixes or explains.

## 8. One safety reminder

**The `servabo` repository on GitHub is public.** Anyone can read the code, though not your `.env` files, which are never
committed. Before the first customer, consider making it private: GitHub → the repository → **Settings** → **General** →
**Danger Zone** → **Change visibility**. Check what that does to your GitHub plan's CI minutes first: private repositories
use the free plan's monthly minutes, while public ones do not.
