# Automation (Workflows) — user guide

_Written in Session J (2026-10-21). For the founder and for anyone who builds rules. No programming is needed._

A **rule** watches for something that happens in Servabo (**When**), checks your conditions (**Only if**), and then does
things (**Then**), or other things when the checks are not met (**Otherwise**). Example: *"When an invoice is processed and its
total is over ₹10,00,000, send it to review and notify Finance admins."*

Open it from the workspace menu: **Workflows**. Plans: automations are on Developer and up. A workspace on a lower plan can
still see its rules, switch them off and delete them.

## Try it in two minutes

1. Open **Workflows**, press **Start from a recipe**, choose **Hold invoices above ₹10 lakh for review**, press **Use this recipe**.
2. The builder opens with the rule filled in. Read the sentence at the top. Press **Test & preview** to see what the rule
   would have done on the last 30 days, or pick a recent document and press **Try it**.
3. Press **Create rule**. It is switched on.
4. Upload an invoice. In **Run history** you will see the run, with the reason for each check in words.

## The builder

A full-page editor. The rule is drawn as boxes: **When → Only if → Yes / No → Then and Otherwise**. Choose a box and its form
opens on the right (three tabs: **Configuration**, **Input / output**, **Advanced**). The bar at the bottom says how many
steps you have, and whether anything still blocks saving.

- **Keys:** `Ctrl/⌘ S` or `Ctrl/⌘ Enter` save; `Esc` closes. Closing with unsaved edits asks first.
- **Test & preview:** *Try it on a document* shows which way the checks go for one of your documents, why, and the exact
  message each step would send, with that document's values filled in. *The last 30 days* counts how often the rule would
  have run, on what, and warns when it would be noisy. **Neither sends or changes anything.**

### When — what starts a rule (37 triggers)

Search the list by a word (invoice, GST, hold, schedule…). Each one shows a short line; **Details** shows the long text. One rule
can listen to up to four.

| About | Triggers |
|---|---|
| Documents | uploaded; processed (AI fields ready); pipeline completed; failed; sent for reprocessing; field changed by a rule; batch finished; scanned packet split; table does not reconcile; documents disagree; **run by hand on one document** |
| Procurement | three-way match finished, approved, disputed |
| Forensic audit | anomaly or duplicate detected; payment-risk flag raised (for example a changed bank account) |
| GST Credit | GSTR-2B imported; an invoice still waiting for its supplier; GST credit at risk of reversal (the 180-day clock) |
| Compliance | legal hold placed; legal hold released |
| TruthMesh | a conflict opened; a conflict resolved |
| Schedule | every day (08:00 in the workspace's time zone); every week (Monday) |
| Helm | a mandate breached; an action waiting for approval (these can only tell, mail, post, call out, review or tag: **never move money**) |
| Cases, obligations, clauses, redaction, ERP, process intelligence, review | as before |

A trigger your plan does not include is shown locked, with the reason and an **Upgrade** button.

### Only if — the checks

Every check is a field, a comparison and a value. The value box fits the field:

- **Amounts:** a number and a currency ("greater than 10,00,000 **INR**"). Never typed in millionths. A document in another
  currency does not match, and the reason says so: Servabo never converts.
- **Dates:** a date picker, or "within the next N days", "within the last N days", "older than N days". Dates are read in the
  workspace's date format and time zone.
- **Fixed values** (a severity, a state, a document type): a dropdown of plain names, never a code to type.
- **"Is one of":** a list; a value may hold a comma ("Acme, Inc").
- **"Between":** a low and a high.

Fields come from the trigger and from the document: the finance fields (invoice number and date, supplier, GSTINs, tax heads,
totals, due date, IRN…), the document type, and three that are worked out when the rule runs: **document age (days)**, **has an
e-invoice IRN**, **days until due**. A search box narrows the list. A field is found by any name a model may have given it
(`supplier_gstin` is read as `vendor_gstin`), and a person's correction on a document is what the next check reads.

With no checks the rule runs every time its trigger fires.

### Then and Otherwise — what a rule can do (16 steps)

Steps run in order. A failed step stops the ones after it (or the rule keeps going, if you chose "Keep going").

| Step | What it does |
|---|---|
| Send to review / Send to review, assigned | Hold the document for a person, or a role, with a due time |
| Notify a role / Send email | Tell people |
| **Post a message to chat** | Slack or Microsoft Teams, through a channel's incoming-webhook address (stored encrypted, never shown back) |
| Tag the document | Add or take off tags (a tag change can start another rule; a rule cannot start itself) |
| Place a legal hold | Hold a document with a reason. Releasing stays a person's job |
| Create a follow-up | An obligation due in N days, with an owner |
| Remind a GST supplier / Ask a supplier for a document | Only to a contact Servabo already knows |
| Set a document field, Redact PII, Decide with calibrated autonomy, Send to webhook, Export to warehouse, Post to ERP | As before |

**Automation never approves, pays or schedules a payment.**

## Recipes

Sixteen ready-made rules, India first, in plain words (Invoices, Compliance, GST, Follow-ups, Team). A recipe can need a plan or
the GST Credit add-on: a locked one offers **Upgrade**. Two or three need one answer from you (a Slack channel, a reviewer,
an email address), asked before the builder opens. The list lives in `backend/app/services/automation/recipes.py`; a test saves
every recipe, so a stale one fails the build.

## Safe at volume

- **Hourly limit:** a rule may run 200 times an hour unless you set another number (Advanced tab). Runs over the limit are not
  lost: they are listed in Run history as **Skipped — over the limit**, and the rule's author gets one notice a day.
- **Cooldown:** "at most once per document every X hours" (off until set).
- **Pause all automations:** one switch for the workspace (administrators; audited). While paused nothing runs, not even by
  hand; runs that arrive are listed as **Skipped — paused**, rule cards show **Paused**.
- **Retry:** a run that failed can be retried from Run history. If a step could send a message twice, Servabo asks first.
- **Versions:** every save keeps a version with a plain list of what changed ("Added condition: Total amount is greater than
  1000000 INR"). **History** on a rule lists them; **Restore** puts one back as a new version (nothing is lost).
- **"Why didn't my rule run?":** on a document, the **Automation** tab says, for each rule, whether it ran, was held back, or
  which check was not met and with what value. From there an administrator can also **run a rule on this document** (a rule
  with the "Run by hand" trigger).

## Run history

Everything a rule did, grouped by what set it off. Filter by outcome (all, failed, skipped), rule and date. Open a run for its
steps, and for each check the reason in words. **Retry this run**, and **Open the document**, are there too.

## Telling your own systems (webhook events)

A rule reacts *inside* Servabo. Your own systems can also subscribe, under Organization → Webhooks, to five things the engines notice (docs/product/WEBHOOK-EVENTS.md):
`gst.return.imported`, `gst.invoice.at_risk`, `gst.supplier.not_reported`, `automation.run.failed` and `automation.run.held`. They are separate from the 37 triggers (a rule never
hears them and a webhook never starts a rule), they carry ids and figures only, and each is sent once. `automation.run.failed` and `automation.run.held` are the two public names under the
reserved internal `automation.` prefix; everything else under it stays internal.

## For administrators of the deployment

- `AUTOMATION_DEFAULT_RUNS_PER_HOUR` (default 200; 0 = no default limit) and `CHAT_WEBHOOK_EXTRA_HOSTS`: see `docs/CONFIGURATION.md`.
- The hourly job `automation.sweep` announces the schedules and the GST clocks; the worker's light profile runs it.
- Decisions behind all this: `docs/hardening/NEEDS-OWNER.md`, N-149 to N-159. Defects found: F-535 to F-545. The starting
  inventory: `docs/automation/AUDIT.md`.
