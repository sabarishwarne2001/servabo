# Webhook events for GST credit, workflow runs and TRINETRA

Written in Final session 1 (Phase 6). For people who build on Servabo: your own systems can be told, by a signed web request,
when one of these five things happens. Everything else about webhooks (signing with `X-Servabo-Signature`, retries, the delivery
log, rotating the secret) is the same as for every other event: see the Webhooks tab of the organization console.

TRINETRA adds the separately gated Enterprise event documented below.

## How they behave

| Rule | What it means for you |
|---|---|
| Subscribe | Tick the event on an endpoint in **Organization → Webhooks**, or send it in `event_types` when you create one through the API. Nothing is sent to an endpoint that did not ask. |
| Once per occurrence | Each event is sent once for the thing that happened. The same GSTR-2B file imported again, a sweep that runs every hour, and a retried delivery do not make a second event. (Your endpoint may still receive the same delivery twice when a retry follows a timeout: treat `X-Servabo-Delivery-Id` as the idempotency key, as for every event.) |
| Ids and figures only | A payload carries ids, GSTINs, amounts as whole numbers of micros (one rupee is 1,000,000) with their currency, ISO dates, counts and state names. It never carries a supplier's or customer's name, an invoice number, an error message or a rule's name. Read those from the API with a key that may see them. |
| Plan | Webhooks come with the plans that include them. These events need nothing more: a workspace's GST sweeps already follow GST credit, and the workflow events follow the Workflows page. |

## `gst.return.imported`

A GSTR-2B finished importing and was matched. Once per import (a replaced file is a new import; the same file again is not).

| Field | Meaning |
|---|---|
| `workspace_id` | The workspace that holds the books. |
| `return_id` | The imported return. |
| `gstin` | Your GSTIN the statement belongs to. |
| `period` | `YYYY-MM`. |
| `records` | How many records the file held. |
| `waiting_count`, `waiting_micros`, `currency` | Invoices in your books that no imported GSTR-2B shows (credit deferred), and their credit in micros. |
| `differences` | Invoices reported with a different amount. |
| `replaced` | `true` when the file replaced an earlier import of the same period. |

## `gst.invoice.at_risk`

An unpaid purchase invoice has reached 150 days: 30 days remain before the 180-day rule (Section 16(2), second proviso, CGST Act,
with Rule 37) would add the credit back to your output tax. Once per invoice.

| Field | Meaning |
|---|---|
| `workspace_id`, `work_item_id` | The workspace and the invoice document. |
| `gstin`, `supplier_gstin` | Yours and the supplier's. |
| `amount_micros`, `currency` | The tax at risk. |
| `age_days`, `days_left` | Days since the invoice date, and days left before the 180th. |
| `reversal_date` | The day the credit would have to be reversed (ISO date). |

## `gst.supplier.not_reported`

An invoice is in your books and in no GSTR-2B you imported, and it has waited longer than your waiting notice (30 days unless you
changed it in the workspace's GST settings). Once per invoice and threshold.

| Field | Meaning |
|---|---|
| `workspace_id`, `work_item_id` | The workspace and the invoice document. |
| `gstin`, `supplier_gstin` | Yours and the supplier's. |
| `amount_micros`, `currency` | The invoice's value. |
| `days_waiting`, `threshold_days` | How long it has waited, and the notice it crossed. |

## `automation.run.failed`

A workflow run ended `FAILED`, `TIMED_OUT` or `BUDGET_EXHAUSTED`: it did not finish what it set out to do. Once per run.
Read the explanation from Run history or the executions API; it is deliberately not in the payload.

## `automation.run.held`

A workflow run was recorded as held back and never ran: the workspace's automation is paused, the rule reached its hourly limit
(`SKIPPED_THROTTLED`), or it already ran for that document inside its cooldown (`SKIPPED_COOLDOWN`). Once per held run.

Both run events carry the same fields:

| Field | Meaning |
|---|---|
| `execution_id`, `rule_id`, `workspace_id` | The run, its workflow and its workspace. |
| `work_item_id` | The document the run was about, or `null` for a scheduled or manual run on no document. |
| `status` | The run's state, as Run history shows it (`FAILED`, `TIMED_OUT`, `BUDGET_EXHAUSTED`, `SKIPPED_THROTTLED`, `SKIPPED_COOLDOWN`, …). |
| `nodes_executed`, `actions_executed`, `depth` | How far the run got, and how deep in a chain of rules it sat. |

## For the person running Servabo

* The names are in `backend/app/core/webhook_events.py`; the browser's list in `frontend/src/types/webhook.ts` must match (a test keeps them equal).
* `automation.` is a reserved internal prefix; only the two `automation.run.*` names are public, listed one by one in
  `automation_events.PUBLIC_AUTOMATION_EVENTS`. Anything else under it is still refused at import time.
* Migration `k1a6_engine_webhook_events` widens the two database CHECKs that pin the vocabulary. Downgrading it deletes
  deliveries of these events and removes them from endpoints' subscriptions (an endpoint that listened to nothing else is deleted).
* Code: `backend/app/services/automation/public_events.py`; tests `backend/tests/engines/test_engine_public_webhooks_live.py`.

## `trinetra.case.reviewed`

Requires Enterprise's `capability.trinetra_all_workspaces`, enabled live processing
and an endpoint explicitly subscribed to this event. Sample evidence emits nothing.
The transactional outbox deduplicates each case/revision; delivery retains the
ordinary webhook retry/idempotency behavior above. It reports a recorded review,
not tax eligibility or money recovered.

| Field | Meaning |
| --- | --- |
| `workspace_id`, `case_id` | Opaque identifiers of the workspace and credit case. |
| `revision` | Integer revision saved by the reviewer. |
| `state` | Recorded review state, such as `OPEN`, `DISPUTED` or `CA_REVIEWED`. |

No PAN, TAN, invoice reference, amount, note or document content is included.
The `trinetra:read` scope grants only the authorized organization summary; it does
not grant case documents, decisions or exports. Migration `tr1a1_credit_assurance`
adds the database event vocabulary; its downgrade removes these subscriptions
and deliveries. See [TRINETRA architecture](../trinetra/ARCHITECTURE.md).

## `trinetra.case.gap_found` and `trinetra.case.closed`

Final session 2T. The same conditions as `trinetra.case.reviewed` (Enterprise `capability.trinetra_all_workspaces`, TRINETRA live
for the organization, an endpoint explicitly subscribed, no sample evidence). Each is sent once per case and revision.

* `gap_found`: after a statement import or a change in the evidence, the case's tax is not fully in the imported statement
  (`status` says how: `POSSIBLE_MISSING_POSTING`, `AMOUNT_MISMATCH`, `SUGGESTED`, `AMBIGUOUS`, `DUPLICATE_SUSPECTED`,
  `TAN_MISMATCH_SUSPECTED`). It is an item to check, never money, and not a statement that anyone failed to file or deposit.
* `closed`: a person closed the case (`state` is `CA_REVIEWED`, `EXPLAINED`, `WITHDRAWN` or `UNRESOLVED`).

| Field | Meaning |
| --- | --- |
| `workspace_id`, `case_id` | Opaque identifiers of the workspace and the case. |
| `revision`, `year` | The case revision the event is about, and its tax year (the year in which the tax year starts). |
| `state` | Review state: `OPEN`, `DISPUTED`, `EXPLAINED`, `WITHDRAWN`, `CA_REVIEWED` or `UNRESOLVED`. |
| `status` | The comparison status at that moment (see above). |
| `amount_micros`, `currency` | `gap_found`: the gap the statement does not show; `closed`: the withheld amount the case concerned. Integer millionths of a rupee, `INR`. Never added to cash. |

No PAN, TAN, invoice reference or customer name is included; read the case through the API (`trinetra:read`) for those you may see.
Migration `tr2t9_case_events` widens the three database CHECKs that pin the vocabulary; its downgrade removes the new names from
subscriptions, deliveries and the outbox. Code: `backend/app/services/trinetra/events.py`; tests
`backend/tests/trinetra/test_case_events.py`.
