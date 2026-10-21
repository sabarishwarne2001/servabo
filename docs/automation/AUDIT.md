# Automation audit (Session J, 2026-10-21)

This is the map for Session J. It lists what Automation (Workflows) can do today, what it cannot, and every native
browser pop-up in the app. Statuses: **confirmed** (read in the code on `main` `c872828`), **proven** (a test failed
first; the test name is given), **unverified** (not yet proven). The ticks in STATE.md say which are fixed.

## 1. Triggers (23)

Every trigger below has an emitter (the code that writes its event). The test `tests/services/test_automation_trigger_emitters.py`
(new in Session J) fails when a trigger's event has none, so it also guards every trigger added later.

| Key | Event | Plan capability | Has a document |
| --- | --- | --- | --- |
| `document.created` | `trigger.work_item.created` | none | yes |
| `document.ready` | `work_item.enriched`, `work_item.verification_completed` | none | yes |
| `document.completed` | `trigger.document.completed` (twin) | none | yes |
| `document.failed` | `trigger.document.failed` (twin) | none | yes |
| `document.reprocessed` | `trigger.work_item.reprocessed` | none | yes |
| `document.field_changed` | `work_item.field_changed` | none | yes |
| `procurement.completed` / `.approved` / `.disputed` | `trigger.procurement.*` (twins) | reconciliation | yes |
| `anomaly.detected` | `trigger.anomaly.detected` (twin) | anomaly radar | yes |
| `assertion.held` | `trigger.assertion.held` | semantic assertions | yes |
| `redaction.completed` | `trigger.redaction.completed` | redaction | yes |
| `batch.completed` | `trigger.batch.completed` | none | no |
| `review.cleared` | `trigger.review.cleared` | none | yes |
| `packet.split` | `trigger.packet.split` | case intelligence | yes |
| `case.completed` / `case.inconsistent` | `trigger.case.*` | case intelligence | no |
| `table.flagged` | `trigger.table.flagged` | table intelligence | yes |
| `corroboration.discrepancies` | `trigger.corroboration.discrepancies` | universal corroborator | no |
| `obligation.due_soon` / `obligation.overdue` | `trigger.obligation.*` | obligations | no |
| `posting.failed` | `trigger.posting.failed` | ERP posting | no |
| `process.sla_at_risk` | `trigger.process.sla_at_risk` | process intelligence | no |

**Engine events with no trigger (confirmed):** TruthMesh conflicts, GST Credit (return imported, invoice waiting for
its supplier, 180-day risk), payment-risk flags, legal holds, Helm (`helm.plan.ready`, `helm.action.executed`,
`helm.mandate.breached` exist only as public webhook events), documents received through a request link, schedules, and
running a rule by hand.

## 2. Condition fields and operators

Operators by field type (`OPERATORS_BY_TYPE`): string (11), number (12), boolean (3), array (9), date (6: equals, not equals,
starts with, exists, is empty, is not empty). The evaluator is `automation_service._evaluate_condition`.

| Defect | Where | Status |
| --- | --- | --- |
| Numbers compared with `float(actual)`: `"1,18,000.00"`, `"₹ 1,18,000"`, `"INR 118,000.00"`, `"(1,200.00)"` never match "greater than"; the comparison silently returns False | `automation_service.py:114` | proven (Phase 1 table, F-535) |
| No date comparison (before, after, within, older than); workspace date format and time zone ignored | `triggers.py` `OPERATORS_BY_TYPE["date"]` | proven (Phase 1 table, F-536) |
| Trigger money is in micros and typed as `12500000` (`variance_micros`) | `triggers.py` | confirmed; fixed by field type `money` |
| Fixed-value fields (object, kind, severity, state) are free text | `triggers.py` | confirmed; fixed by `TriggerField.options` |
| `IN`/`NOT_IN`/`BETWEEN`/array operators split on commas, so "Acme, Inc" breaks | `_evaluate_condition` | proven (F-537) |
| `STANDARD_FIELDS` lists the old six-field prompt (`date`, no GSTINs, no tax heads, no due date, no IRN) | `catalog_service.py:37` | confirmed; fixed by one shared schema |
| Document fields read raw: `supplier_gstin` does not match a condition on `vendor_gstin` | `resolve_field` | proven (F-538) |
| A run's trace holds only `matched: true/false` and a digest of the conditions, not the values | `executor._execute_node` | confirmed (F-539) |

## 3. Actions (9)

`webhook.send`, `redaction.start`, `review.escalate`, `warehouse.export`, `notify.role`, `autonomy.decide`, `email.send`,
`work_item.mutate`, `erp.post`. Not available: tag a document, assign a review to a person, place a legal hold, create a
follow-up (obligation), ask a supplier for a document, send a GST supplier reminder, post to Slack or Microsoft Teams.

## 4. Safety (confirmed)

- No per-rule throttle or cooldown: a batch of 500 uploads with an "email on upload" rule sends 500 emails.
- No rule version history, no restore.
- No preview of what a rule would have done on recent data (the existing test runs on one document).
- No retry of a failed run from the run history.
- No way to answer "why didn't my rule run?".

## 5. The builder (confirmed, with the owner's screenshots)

One long modal; 23 trigger cards with long paragraphs and no search; the summary reads "When (pick when it runs): (add
what it does)."; raw codes as values (`POSTING`); "Another document field…" means typing a path; no recipes. The frontend
has no unit-test runner, only `check:self`.

## 6. Native browser dialogs in `frontend/src` (13 calls, 12 files; confirmed by search on 2026-10-21)

| File | Line | Call | What it protects | Replacement |
| --- | --- | --- | --- | --- |
| `pages/Automation/FlowBuilder.tsx` | 159 | `confirm` | Discard unsaved rule | `ConfirmDialog`, "Discard changes" / "Keep editing" |
| `components/obligations/HolidayCalendars.tsx` | 131 | `confirm` | Delete a holiday calendar | danger, "Delete calendar" |
| `components/obligations/CalendarFeeds.tsx` | 133 | `confirm` | Revoke a calendar feed | danger, "Revoke feed" |
| `components/erp/MappingEditor.tsx` | 128 | `confirm` | Replace the mapping with the default | primary, "Restore default" |
| `components/erp/LookupTables.tsx` | 76 | `confirm` | Delete a lookup table | danger, "Delete table" |
| `pages/admin/AdminMarginsHub.tsx` | 504 | `globalThis.prompt` | The required note when accepting a variance | `input`; Confirm disabled while the note is empty |
| `pages/corroboration/CorroborationRun.tsx` | 289 | `confirm` | Delete a comparison and its decisions | danger, "Delete comparison" |
| `pages/entities/Entity360.tsx` | 198 | `confirm` | Erase a record (documents kept) | danger, "Erase record" |
| `pages/organization/OrganizationAnalytics.tsx` | 341 | `confirm` | Delete a warehouse destination | danger, "Delete destination" |
| `pages/obligations/ObligationDetail.tsx` | 198 | `confirm` | Delete an obligation | danger, "Delete obligation" |
| `pages/erp/ErpTargetDetail.tsx` | 75 | `confirm` | Changing the sign-in method removes the stored credential (inside the save flow) | "Change and remove credential" |
| `pages/erp/ErpTargetDetail.tsx` | 217 | `confirm` | Delete an ERP target | danger, "Delete target" |
| `pages/erp/ErpPostingDetail.tsx` | 186 | `confirm` | The CANCEL decision ("will not be sent") | danger, "Do not send" |

`src/utils/security.ts:66` matches the pattern only inside a comment (`javascript:alert(1)`); the guard skips comments.
No bare `alert(` or `prompt(` call and no `window.alert` exists. The `beforeunload` handler in `FlowBuilder` is native by
design and stays (only while the draft is dirty).

**Browser specs that answer a native dialog (confirmed):** 86 (`:165`), 90 (`:331`, `:341`), 96 (`:709`, `:713`, `:719`),
98 (`:759`, `:768`), 26 (`:105`, counts dialogs as a guard). No other spec under `e2e/tests` listens for `dialog`.

## 7. Confirmed defects (findings)

See FINDINGS.md F-535 onward. Each is "unverified" here until its test is written and fails first.
