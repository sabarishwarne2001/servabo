# Checking Servabo against a real Dodo test account (on your own PC)

Everything Servabo does with Dodo Payments was written from Dodo's documentation and proven only
against a stand-in (`backend/tests/fakes/fake_dodo.py`). The cloud sandbox cannot reach Dodo, so the
real check has to run on your PC, in Dodo's **Test Mode** (no real money moves). This page is the whole
walk-through. It is written for you and for the Claude session that runs it with you ("Session D").

You will end with the results table at the bottom filled in: for each of the ten points in
[`DODO.md` §6](DODO.md), **Confirmed**, **Differs** or **Not checked**, with the date.

**Safety.** Test Mode only. Every script here refuses to run if `DODO_LIVEMODE=true`. Never paste a
Dodo key or webhook secret into a chat, a commit or a screenshot: they live in `backend/.env` only
(that file is not committed).

**What you need.** The PC where you run `start_dev.ps1` (Docker Desktop, Python 3.12, Node), a Dodo
account with **Test Mode** switched on (the toggle in Dodo's dashboard), and about an hour.

## 1. Test mode on

1. Sign in to Dodo's dashboard and switch **Test Mode** on. Everything below happens in that mode;
   Dodo shows a banner when it is on.
2. In `backend/.env` make sure these lines say:
   ```
   BILLING_GATEWAY=DODO
   DODO_LIVEMODE=false
   DODO_API_BASE=
   ```
   (`DODO_API_BASE` stays empty: it follows `DODO_LIVEMODE` and picks Dodo's test host.)

## 2. Keys into `backend/.env`

1. Dodo dashboard → **Developer → API keys** (Test Mode on) → create a key → copy it.
2. In `backend/.env` set `DODO_API_KEY=` to that key. (Do not set `DODO_WEBHOOK_SECRET` yet; step 5
   gives you it.)

## 3. Create and check the products

From PowerShell, in the repository folder:

```powershell
cd backend
.\.venv\Scripts\python.exe scripts\dodo_setup.py --create-test-products
```

It creates the five plan products and two add-ons in your **test** account and prints seven lines like
`GATEWAY_PRICE_ID_DEVELOPER=pdt_…`. Paste all seven lines into `backend/.env`. Then run the check until
every line says `OK`:

```powershell
.\.venv\Scripts\python.exe scripts\dodo_setup.py
```

If a line says `WRONG`, it tells you in words what to change in Dodo's dashboard (or delete the
product and run `--create-test-products` again with that line removed from `.env`).

## 4. Restart, so the plans pick up the product ids

```powershell
cd ..
.\start_dev.ps1 -Stop
.\start_dev.ps1
```

The plan seed (`seed_quota_tiers.py`) runs at start and reads the ids. If the plan cards on the
pricing page show no "Choose" button, the ids are missing from `backend/.env`.

## 5. Start the webhook relay

Dodo's servers cannot reach `localhost`, so something has to carry Dodo's events to your PC:

```powershell
.\start_dev.ps1 -Stop
.\start_dev.ps1 -DodoWebhooks
```

At the end of the start-up it prints, under **Dodo webhooks**, the exact steps for the tool it found:

- **Dodo's own CLI (first choice).** Install once with `npm install -g dodopayments-cli`, then run
  `dodo login` and choose Test Mode. The relay runs `dodo wh listen` for you. The first time it runs,
  the CLI creates an endpoint in Dodo's dashboard (**Developer → Webhooks**). Open it and reveal its
  **Signing secret** (starts with `whsec_`).
- **Cloudflare quick tunnel (fallback, needs no Dodo login).** Install once with
  `winget install --id Cloudflare.cloudflared`. The relay prints an address
  `https://….trycloudflare.com/api/v1/billing/webhooks/dodo`. In Dodo's dashboard (**Developer →
  Webhooks → Add endpoint**, Test Mode on) paste exactly that address, subscribe it to the
  `subscription.*`, `payment.*`, `refund.*` and `dispute.*` events, save, and reveal its **Signing
  secret**. The address changes every time the relay starts: edit the endpoint's URL each time.

Then put the secret in `backend/.env` as `DODO_WEBHOOK_SECRET=whsec_…` and restart once
(`.\start_dev.ps1 -Stop`, then `.\start_dev.ps1 -DodoWebhooks`). The relay's log is
`.dev\dodo-relay.log`. `.\start_dev.ps1 -Stop` stops the relay with everything else.

**Check it works** (before the journeys): in Dodo's dashboard open the endpoint and use its "send
test event" (if offered), or just do journey A. In Servabo, sign in as the admin the script printed,
go to the platform admin's inbound events or the API log (`.dev\logs\api.log`): a `POST
/api/v1/billing/webhooks/dodo` answered `200` means a signed event arrived and verified. A `401`
means the signing secret in `backend/.env` is not this endpoint's.

*Unverified (written from Dodo's documentation, not tried):* the exact words of Dodo's dashboard
labels, and whether `dodo wh listen` takes the address as an argument or as `--forward-to`. The
relay asks the CLI's own `--help` and uses whichever it accepts.

## 6. The journeys

Do these as a **new customer** (sign up in Servabo with a new e-mail, create an organization). Dodo's
Test Mode lists its test card numbers (in its documentation under test payments and on the checkout
page); use a card it lists as **successful** for the good journeys and one it lists as **declined**
for journey B. Any future expiry date and any three-digit security code work in test mode.

After each journey, run the probe (step 7) with the ids it produced, and fill the results table.

| # | Journey | What you do | What Servabo must show |
|---|---|---|---|
| A | **Checkout success** | Billing → choose **Developer**, 2 seats → pay with the successful test card on Dodo's page. | Back in Servabo: "Confirming your payment…", then "Payment confirmed" with the plan. Billing says "You're on Developer", 2 seats, and lists an invoice "Tax invoice issued by Dodo Payments (merchant of record)". **Download invoice** opens Dodo's PDF. *The address you land on must carry `subscription_id` and `status` (point 5): look at it in the browser bar.* |
| B | **Checkout decline** | Choose a plan again, pay with the declined test card. | "The payment did not go through. Your card was not charged and nothing has changed." The plan does not change. |
| C | **Upgrade, preview = charge** | Developer → **Business**. Before confirming, note the amount on the button (`Upgrade and pay …`). Confirm. | "You're on Business now." The amount charged in Dodo's dashboard (Payments, Test Mode) is **exactly** the amount on the button (point 3). The new invoice appears. |
| D | **Scheduled downgrade** | Business → **Developer**, choose "Schedule the change for …". | Billing says "Changing to Developer" on the renewal date; nothing is charged now. "Keep the current plan" cancels it. (This exercises `do_not_bill` and `on_payment_failure`, point 2.) |
| E | **Refund from Dodo** | In Dodo's dashboard open the payment of journey A → **Refund**. | Within a minute the invoice in Servabo says "Refunded" and the owner gets a notification (this reads `refunds[]`, point 1). |
| F | **Cancel from the customer portal** | Billing → **Manage payment method**: this must open **Dodo's** customer portal (the address is Dodo's, not Servabo's). Cancel the subscription there. | Back in Servabo, Billing says the plan "cancels at the end of the period". |
| G | **A dispute (if Dodo's test mode can simulate one)** | Look in Dodo's dashboard / documentation (Disputes) for a way to open a test dispute on a payment. | Servabo records a dispute (platform admin → Revenue → Disputes) and, if it is *lost*, the organization turns read-only until a later payment succeeds. If Test Mode cannot simulate one, write **Not checked** and move on: the stand-in covers the code path. |

One more check for point 4 (Dodo keeps the checkout's `metadata` after a plan change): after journey C, run
the probe on that subscription with `--after-plan-change` (step 7).

## 7. Run the probe with the ids from those journeys

The probe only reads (it sends GET requests and nothing else) and prints the **shape** of Dodo's
answers (field names and types), never e-mail addresses, ids or amounts, so its output can be pasted
into a chat. Get the ids from Dodo's dashboard (Test Mode → Subscriptions, Payments): `sub_…` and `pay_…`.

```powershell
cd backend
.\.venv\Scripts\python.exe scripts\dodo_probe.py
.\.venv\Scripts\python.exe scripts\dodo_probe.py --subscription-id sub_… --after-plan-change --payment-id pay_…
```

Run it once again with the id of the **refunded** payment (journey E) so the refund fields are read.
To check the webhook timestamp format and that no `livemode` flag is sent (point 9), save one webhook
body as JSON (Dodo's dashboard shows each delivery's body; copy it into a file such as
`C:\temp\webhook.json`) and add `--webhook-file C:\temp\webhook.json`.

For each of the ten points it prints one line: `matches`, `differs: …` (in words), or `not checked
(…)` with the reason. Exit status: 0 nothing differs; 1 something differs; 2 refused or unreachable.

## 8. Results (fill in)

Copy the probe's lines and your journey notes here. **Confirmed** = seen working against Dodo's test
account. **Differs** = write what Dodo did instead; Servabo then needs a fix (tell the next session).
**Not checked** = say why.

| # | Point (from [DODO.md §6](DODO.md)) | How to check | Result | Date | Notes |
|---|---|---|---|---|---|
| 1 | `GET /payments/{id}` has `subscription_id`, `refunds[]`, `disputes[]` as Servabo reads them | probe `--payment-id` (use the refunded payment) | | | |
| 2 | `change-plan` answers empty or with the subscription; `do_not_bill` and `on_payment_failure` are accepted | journeys C and D work end to end | | | |
| 3 | The preview's `total_amount` is the amount charged | journey C: button amount = Dodo's charge | | | |
| 4 | Dodo keeps the checkout's `metadata` after a plan change | probe `--after-plan-change` | | | |
| 5 | The return address carries `subscription_id` and `status` | journey A: read the address bar | | | |
| 6 | `GET /products` pages with `page_size` / `page_number`; `GET /products/{id}` has the full `price` | probe (no ids needed) and `dodo_setup.py` all `OK` | | | |
| 7 | A live key and a test key cannot be told apart from the key itself | cannot be probed; Servabo relies on `DODO_LIVEMODE` and the host | | | |
| 8 | Dodo's payment-retry window for an on-hold subscription | read Dodo's retry settings in the dashboard; Servabo's own grace is 13 days either way | | | |
| 9 | Webhook timestamp format; no `livemode` flag in the body | probe `--webhook-file` | | | |
| 10 | The fee figures (4% + $0.40, +1.5% international, +0.5% subscriptions, $30 chargeback) | compare with Dodo's pricing page and a payment's fee in the dashboard | | | |

When the table is filled in: update [`DODO.md` §6](DODO.md) (move every confirmed point out of "not yet
confirmed", and describe each difference), tell the next session which **Differs** need a code fix, and
tick step 9 of the owner launch checklist in `docs/hardening/HANDOFF.md`.

## If something goes wrong

| You see | It means | Do |
|---|---|---|
| `Refused: … TEST account only` | `DODO_LIVEMODE=true` or the live host | Set `DODO_LIVEMODE=false`, leave `DODO_API_BASE` empty |
| `Dodo refused the key (HTTP 401)` | the key is a live key, or mistyped | Create a key with Test Mode on and paste it again |
| The relay says `Not logged in` | Dodo's CLI needs `dodo login` | Run `dodo login` (Test Mode), start again |
| Webhooks arrive but Servabo answers `401` | `DODO_WEBHOOK_SECRET` is not this endpoint's secret | Copy the endpoint's signing secret again, restart |
| Journey A says the confirmation is late | the webhook is not arriving | Check the endpoint address (the tunnel's address changes on every start) and `.dev\dodo-relay.log` |
