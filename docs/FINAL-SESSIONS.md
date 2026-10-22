# The two final sessions: what they are, and how to run them

_Written 2026-10-22 for the owner. Plain language, no prior DevOps knowledge assumed._

## 1. Where things stand

- **Session J (Automation) is complete.** Every box in its checklist is ticked. Its pull request (#35) passed every CI job
  (run #415), and the run on `main` after the merge (#417) passed too.
  - The only red mark is the **advisory** `pip-audit` job. It warns about the image library Pillow, and it never blocks a
    merge (N-159).
  - Two things were honestly left open: a message to a **real** Slack or Teams channel (N-158), and the optional "Wait" step
    (N-154, decided "not now").
- **Sessions A to J are merged.** The product has Helm, GST Credit, the value receipt, the monthly summary, the GST Credit
  add-on and the rebuilt Automation.
- **What has never happened:**
  - one session that goes back over the **whole** product to bring the older parts up to date;
  - the product being tried **for real**: with real Dodo test payments, real AI and OCR, real GST files and real emails in a
    real inbox.

The two final sessions do exactly those two things.

## 2. The plan changed: two final sessions replace Sessions D and E

| | **Final session 1** | **Final session 2** |
| --- | --- | --- |
| **What** | Study the whole project; bring outdated parts up to date (backend and frontend); build the PRODUCT-NEXT items that earn money | Test **everything for real** on your PC: real AI and OCR, real GST files, real Dodo test payments, real emails, real Slack, Zoho Books, Tally, Sentry, a production rehearsal |
| **Where** | Claude Code **on the web** (the cloud) | Claude Code **in VS Code on your PC** |
| **Model** | Opus 5.5, High | Sonnet 5.5, High (Opus 5.5 for a stubborn defect) |
| **You** | Mostly away; check in, type `continue` after a usage reset, merge at the end | **Present**: about 1 hour at the start, then short moments over the day |
| **Prompt** | [`docs/sessions/FINAL-1-UPGRADE.md`](sessions/FINAL-1-UPGRADE.md) | [`docs/sessions/FINAL-2-LIVE.md`](sessions/FINAL-2-LIVE.md) |
| **Replaces** | Old Session E (error tracking, zip upload, email-in), now with much more | Old Session D (real Dodo, GST files, AI and OCR), now for the whole product |
| **Cost** | Zero | Zero (free plans; Dodo **Test Mode**, no real money) |

**Run them in this order:** Final 1 first. Final 2 tests what Final 1 builds.

### What Final session 1 builds, and why each part earns money

- **Email-in.** Each workspace gets an email address; forwarded invoices become documents. This is what turns a trial into
  daily use.
- **Zip upload.** A customer with a backlog uploads one file on day one.
- **"First money found" in Getting started.** It leads a new customer to the first rupee Servabo finds in their documents.
- **A GST weekly digest email** and GST notifications. They keep the GST Credit add-on, and its $49 a month, in front of the
  owner every week.
- **Upgrade moments.** Every locked feature names the right plan or add-on and opens the right checkout.
- **"Connect Zoho Books" and a guided Tally Prime file.** "Invoice received → bill in my books" is the strongest reason to buy
  Business.
- **Error tracking (Sentry, EU region).** You see *which line failed, for whom* before the customer finishes typing.
- **`preflight.py`.** One command that tells you whether a setup is ready to launch.
- **Bringing things up to date:**
  - what happens to data when it is erased, swept or exported (DPDP Act questions in enterprise deals);
  - outdated AI model lists (some suggested Gemini models were retired by Google);
  - libraries;
  - Session J's small leftovers;
  - accessibility and phone layouts on every page;
  - search for GST.
- **`docs/PRODUCT-NEXT.md` rewritten,** so it tells the truth and ranks what comes after launch.

It will **not** change any price, plan or trial length. Ideas that need a price decision are written down for you.

## 3. How to run Final session 1

1. **Check that `main` is green:** open the repository on GitHub, then **Actions**, then the latest run on `main`. Every job
   must have a green tick; `pip-audit (advisory)` may be red, and that is fine.
2. Open **claude.ai/code** and start a new session on the `servabo` repository.
3. Choose **Opus 5.5** and **High** effort.
4. Paste this one sentence:

   > Read `docs/sessions/FINAL-1-UPGRADE.md` on `main` and carry it out from section 0. Never stop to ask me.

   Or paste everything below the line in that file. Both work.
5. **Leave it running.** Check in every few hours. If it says your usage limit is reached, come back after the reset and type
   `continue`. It picks up where it stopped.
6. **At the end** it marks its pull request "ready". Then:
   - read the PR description (it is written for you);
   - wait until every CI job is green;
   - press **Merge**.

   **Never merge while a CI job other than `pip-audit (advisory)` is red.** Ask a new session to fix it first, and give it the
   link to the failed run.

**Tip:** Final 1 is large. Start it at the beginning of your weekly usage cycle.

## 4. Before Final session 2: what to prepare (about 1 to 2 hours, all free)

Do this before you start Final session 2. Anything you cannot get is simply skipped and marked "Not checked". **Nothing
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

### 4.3 Real files, in `C:\servabo-live\` (never inside the `servabo` folder)

- **Five to ten real GST tax invoices** (PDF or scans). Your own online-shopping tax invoices (Amazon, Flipkart and the like)
  are real GST invoices and are fine. A friendly distributor's invoices are fine **with their permission**.
- **One printed page photographed at a slight angle**, and **one handwritten bill** (photos from your phone).
- **One zip** of 20 or more invoices (copies are fine).
- **Optional, from your CA** (worth asking for; it turns "unverified" into "confirmed"):
  - **one real GSTR-2B JSON** (GST portal → Returns dashboard → GSTR-2B → **Download JSON**; any month, any client);
  - **one real e-invoice PDF** (an invoice with an IRN and a signed QR code, usually from a large supplier);
  - **NIC's public key** for checking the QR signature, if the CA knows where to get it.

## 5. How to run Final session 2

1. Make sure Final session 1 is **merged** and `main` is green. Then run `git pull` on your PC.
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

## 6. After both sessions: launch

Open `docs/hardening/HANDOFF.md`, **"Owner launch checklist"**. Final session 2 will have ticked what your PC could prove
(Dodo test mode, the real-model checks, the production rehearsal). What remains needs money or a public address, so only you
can do it:

1. rotate old keys;
2. the domain on Cloudflare;
3. the website online;
4. Dodo's business verification;
5. Postmark with your domain;
6. the Hetzner server;
7. the install;
8. and the following steps, then live mode.

`preflight.py --online` on the server tells you what is still missing.

## 7. If something goes wrong

- **"Usage limit reached":** come back after the reset and type `continue` in the same session. Do not start a new session for
  the same work.
- **CI is red on a pull request:** do not merge. Start a small new session, paste the link to the failed run, and ask it to
  find the cause and fix it test-first.
- **You pasted a secret into a chat:** create a new key in that provider's dashboard, delete the old one, and put the new one
  in `.env`.
- **The PC cannot start the stack:** in Final session 2, tell Claude what you see. It reads `.dev\logs` and fixes or explains.

## 8. One safety reminder

**The `servabo` repository on GitHub is public.** Anyone can read the code, though not your `.env` files, which are never
committed. Before the first customer, consider making it private: GitHub → the repository → **Settings** → **General** →
**Danger Zone** → **Change visibility**. Check what that does to your GitHub plan's CI minutes first: private repositories
use the free plan's monthly minutes, while public ones do not.
