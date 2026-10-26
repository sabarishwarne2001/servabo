# Final session 2T (FINAL-2T-TRINETRA): TRINETRA, finished, on Business and Enterprise

| | |
| --- | --- |
| **Where** | Claude Code on the web (the cloud), repository `servabo` |
| **Model / effort** | **Opus 5.5, High** |
| **Before you start** | Final session 2A (`docs/sessions/FINAL-2-UPGRADE.md`) is merged and **CI is green on `main`** |
| **After it** | Final session 2B, on your own PC (`docs/sessions/FINAL-2-LIVE.md`). It proves TRINETRA's statement readers, the Zoho TDS read and the inquiry emails against real files and real inboxes. **This session writes TRINETRA's part of that prompt.** |
| **External cost** | Zero. Every outside service is played by a stand-in here. |
| **If usage runs out** | Type `continue` in the same session after the reset. Each phase is finished, tested and pushed before the next one starts. **This session has no cut line: its goal is that nothing is left behind.** |

**How to start.** Open a new Claude Code session on the web for `servabo`, choose Opus 5.5 with High effort, and paste either
everything below the line or this one sentence:

> Read `docs/sessions/FINAL-2T-TRINETRA.md` on `main` and carry it out from section 0. Never stop to ask me.

---

# Final session 2T: TRINETRA, finished, on Business and Enterprise

## 0. Why this session exists

Servabo is a multi-tenant B2B SaaS for document intelligence and finance automation, built by a solo founder in India who is
new to SaaS. Explain everything you report in plain language.

**TRINETRA** (PR #40, decision N-188, `docs/trinetra/`) answers one question for a business: **"Did the TDS my customer withheld
from my invoice really reach my tax statement?"** It compares five kinds of evidence, each kept as a separate fact:

- the invoice;
- the reviewed accounting expectation;
- the bank receipt;
- the customer's advice or certificate;
- the uploaded government statement.

It then helps a reviewer resolve each difference, with evidence.

**What exists today.** A careful, honestly documented and well-tested foundation:

- four tables (head `tr1a2_review_outcomes`) and 20 routes;
- exact money in integer micros;
- versioned human decisions;
- many-to-many allocation that cannot spend a posting twice within a profile;
- an encrypted PAN;
- a cockpit, a case drawer, side-by-side source review and CSV/XLSX/HTML exports;
- a Helm annotation and a website page;
- CI run 40282980125 and `main` run #478 green.

**It is switched off for customers** (`TRINETRA_LIVE_ENABLED=false`); they see a synthetic preview.

**The owner's goal, in his words:** TRINETRA "available to Business and Enterprise tiers", working "like other features in
Servabo", like Helm, three-way matching and GST Credit, with "nothing left behind".

### What "finished" means here, honestly

TRINETRA is finished when all three of these are true. Never claim "100%" before all three.

1. **This session (2T): complete in code and tests.**
   - Every requirement of the owner's original brief (`docs/trinetra/ORIGINAL-BRIEF.md`) for **business TDS receivables** is
     built and tested.
   - So is every integration the other Servabo features have (§0, "Like every other feature").
   - Every bug the review found is fixed test-first.
2. **Final session 2B (the owner's PC): proven against the real world.**
   - The statement readers on real, legally obtained files: the owner's own Form 26AS / Form 168 text download and AIS CSV,
     which any PAN holder can download for himself.
   - The Zoho Books TDS read on a real organization.
   - The inquiry email in a real inbox.
   - Each reader is marked **verified** only there.
3. **The owner switches it on.**
   - His CA reads TRINETRA's wording and examples (about an hour; recommended by its launch gates).
   - He then sets one setting to "on", and every Business and Enterprise organization gets live TRINETRA.

**Out of scope on purpose,** as the original brief allows. Say so plainly in the product and the docs:

- **TCS** stays isolated and switched off: its rules and statements differ, and the brief says to gate it until it is
  trustworthy;
- payroll TDS (Form 16, employer returns);
- filing anything;
- logging in to any tax portal;
- advice on rates, sections or which credit to claim.

### What the code read found on 2026-10-26 (verify each point; prove each defect with a failing test first, or record "not a defect")

**Defects and gaps in what exists** (HANDOFF "TRINETRA review and the revised session 2A"):

| Area | What was found | Where |
| --- | --- | --- |
| **The Helm reminder hold** | Once a withholding is confirmed on an invoice, `helm/hands.py` refuses **every** cash reminder for that invoice (`HELM_WITHHOLDING_REVIEW`). That includes the case where the customer still owes most of the invoice in cash, for example ₹1,16,000 of ₹1,18,000 with ₹2,000 withheld. The refusal lands at send time as a **FAILED** action, not as a Guard block, so the planner may propose it again, and the person sees "failed". The hold also survives the flag being switched off and a plan downgrade, by design, so a stale confirmation can stop collections indefinitely. | `backend/app/services/trinetra/helm_adapter.py`, `backend/app/services/helm/hands.py`, `helm/executor.py` |
| **"Changed" means any touch** | A case's invoice, its supporting evidence and the active statement are "current" only while each document's `work_items.updated_at` is unchanged. That column moves on **any** update to the row (`onupdate=func.now()`): a rename or summary set by an automation (`work_item.mutate`), batch healing, or a reprocess that yields the same fields. Such a touch makes the expectation stale, so reconfirming clears its allocations, and it makes a whole statement snapshot unusable until it is re-imported. | `backend/app/services/trinetra/service.py`, `backend/app/db/base.py` |
| **The seller check** | `receivable()` compares the extracted `vendor_pan` to the profile's PAN **as printed**: no upper-casing, no removal of spaces. It never derives the PAN from `vendor_gstin`, although an Indian B2B invoice prints the GSTIN and the PAN is characters 3 to 12 of it. Without a PAN it falls back to matching on the **name** only. `hmac.compare_digest` raises a `TypeError` (a 500 error) on non-ASCII text. | `service.py` (`receivable`), `backend/app/services/helm/identity.py` |
| **Capacities that never free up** | The plan capacities count **every** snapshot and every case the organization ever created, superseded and withdrawn included, and nothing can archive them. A Business organization therefore stops for good after its 12th statement import or its 500th case. | `service.py` (`capacity`, `import_reviewed`), `api/v1/trinetra.py` (`create_credit`) |
| **One PAN, two workspaces** | Duplicate PANs are refused only **within** a workspace. The same legal entity can have a profile in two workspaces of one organization, and the same government posting can then be allocated once in each: credit counted twice. | `service.py` (`create_profile`) |
| **No way to run a pilot, and no way to launch** | `TRINETRA_LIVE_ENABLED` is one switch for the whole deployment, with no mode for one enrolled organization. Every gate reads it separately. | `core/config.py`; `api/v1/trinetra.py`, `workers/handlers/trinetra.py`, `trinetra/hooks.py`, `events.py`, `helm_adapter.py` |
| **A job that does nothing** | `trinetra.recompute` is queued on every document change in a workspace that has a profile. It computes the summary and throws it away: no notice, no event, no stored figure. | `workers/handlers/trinetra.py`, `trinetra/hooks.py` |
| Smaller points | The case list builds each row with separate queries. The page shows write forms only when `workspace.role === "ADMIN"`; check what an organization owner sees. TRINETRA rows are deleted on erasure while GST rows are kept (N-163): pick one deliberate rule. | `api/v1/trinetra.py` (`credits`), `pages/trinetra/Trinetra.tsx`, `services/compliance/data_map.py` |

**Unfinished against the original brief** (`docs/trinetra/LAUNCH-GATES.md`, "Product acceptance still open", and DELIVERY):

| Brief | Missing today |
| --- | --- |
| §3A Import | Official statement files are refused. Rows are **typed by hand**, up to 500. There is no mapping preview for a file, and no reader for the Form 26AS / Form 168 text download or the AIS CSV. |
| §3A / §3B Records | No expectation is derived from accounting records. Printed TDS hints (`tds_amount`, `deductor_tan`, `tds_section`) are shown, but they never become suggestions. Zoho Books' customer payments carry the TDS withheld (`tax_amount_withheld` in its API), and nothing reads it. |
| §3B Money model | Credit notes, reversals, advances and earlier triggering events are refused. There are no statuses for a duplicate or late posting, "verified corrected" or "unresolved". There is no way to reject or annotate a suggestion. |
| §3C Resolution | The inquiry is a draft only: no authorized send, no record of who sent it, no reply path, no quota. There are no configurable approval chains for Enterprise. Outcomes compare only with the previous import; there is no cumulative closure ledger and no measured cycle time. |
| §3D Dashboard | There is no filter by customer or workspace, no amount waterfall in the drawer, no first-run tutorial, and no KPIs by source confidence. |
| §4 Platform | Notifications, metering of inquiries, and platform administration (pilot enrolment) are missing. |
| §6 Packaging | Live access is gated for everyone. Business and Enterprise do not actually get it. |

**Like every other feature.** Compare TRINETRA with how GST Credit, Helm and three-way matching are woven into Servabo. Today
TRINETRA is missing from:

- Getting started;
- global search;
- the notification preferences and the weekly digest;
- the value receipt and the monthly summary;
- automation triggers;
- the warehouse datasets;
- the public read API beyond one organization summary;
- the Resolution layer (if 2A built it);
- a user guide like `docs/automation/README.md`;
- a performance budget test like `tests/performance/test_gst_budgets.py`;
- `preflight.py`;
- an explicit TAN pattern in the error-tracking scrubber (`app/core/error_tracking.py`; it is caught today only by the generic
  reference pattern).

## 1. Authority and rules

- **Full founder authority for this session.** The owner decided that TRINETRA goes to Business and Enterprise (N-190).
  - Every other decision: decide like a careful senior engineer at a top SaaS company, build it, and record it in
    `docs/hardening/NEEDS-OWNER.md` as `DECIDED (Final 2T)`.
  - Never stop to ask. Take the next free N-, F- and spec numbers from the top of `STATE.md`. Final 2A used some.
- **Tax and data rules from the original brief stand:**
  - no tax-portal credentials, scraping, CAPTCHA bypass or invented government API;
  - no autonomous sending (every inquiry is sent by a person who pressed Send);
  - no rate, section or eligibility advice;
  - no TCS;
  - PAN and TAN never in logs, URLs, telemetry, screenshots or emails;
  - a gap is an investigation item, never a refund, an asset or proof of wrongdoing.
- **Evidence rule (CLAUDE.md):** every defect is proven by a failing test before it is fixed. Anything not proven is reported as
  "unverified".
- **CLAUDE.md hard rules hold:**
  - no secrets, `.env` files, binaries or **real tax files** in git (fixtures are synthetic, with the real shape and invented
    values);
  - never weaken, skip or delete a test;
  - never push to `main`;
  - exactly one Alembic head, with up, down and up, **with populated TRINETRA rows**;
  - test-mode credentials only.
- **Never contact a live outside service from a test.** Use the stand-ins: SMTP, Zoho (extend it with customer payments) and
  Dodo. Read official documentation with WebSearch and WebFetch, and cite page and date wherever a reader relies on a layout.
- **Every new route, setting, migration and job is accounted for:**
  - coverage-ledger rows, with `campaign_slices.py --check all` exiting 0;
  - `config.py`, `CONFIGURATION.md`, the env templates;
  - the generated API types;
  - `TENANCY-AND-PLANS.md`;
  - `pricing.json`;
  - the data map (`data_map.py` and its completeness test);
  - the route isolation sweeps.
- **Branch and PR:**
  - use the assigned branch;
  - open a draft PR at the start, push after each phase, mark it ready at the end;
  - one logical change per commit.
- **Never call the work finished while CI is red.**
- **If cut off,** continue from the first unticked box in `STATE.md`.
- **Usage discipline:**
  - at most two helper agents at a time, each with a narrow brief;
  - long suites in the background;
  - full suites once at the end, or on the ready PR's CI.

## 2. Start-up

1. **Read:**
   - `CLAUDE.md`;
   - `docs/hardening/STATE.md` (top sections);
   - `docs/trinetra/ORIGINAL-BRIEF.md` (the owner's brief, every line);
   - all of `docs/trinetra/`;
   - HANDOFF: "TRINETRA review and the revised session 2A", "Final session 2A → Final session 2B", "Owner launch checklist";
   - NEEDS-OWNER N-160 to the latest;
   - `docs/product/GST-CREDIT.md`, `docs/helm/ARCHITECTURE.md`, `docs/automation/README.md`;
   - `docs/RUNBOOK.md` §9;
   - `docs/sessions/FINAL-2-LIVE.md`.
2. **Read the code:**
   - `backend/app/services/trinetra/`, `backend/app/api/v1/trinetra.py`, `backend/app/models/trinetra.py`, the two migrations,
     `frontend/src/pages/trinetra/`;
   - and the code that every row of §0 names;
   - and how GST Credit is wired into search, notifications, the digest, the value receipt, automation triggers, webhooks,
     warehouse datasets, Getting started, upgrade moments and the website. **Copy those patterns; do not invent new ones.**
3. **Stand up the stack** (STATE.md environment notes), including the browser stack with TRINETRA live (CI's separate TRINETRA
   phase shows how).
4. **Open the draft PR.** Write this session's checklist at the top of `STATE.md`: one box per phase item, and the next free
   numbers.

## 3. Phase 0: the completion matrix (first, and kept up to date to the end)

Write **`docs/trinetra/COMPLETION.md`**: one row for every requirement in `ORIGINAL-BRIEF.md` (§0 to §9, sentence by sentence
where a sentence asks for something), plus one row for every item of "Like every other feature" (§0). Columns:

- the requirement;
- **status**: Done before 2T / Built in 2T / Verified in 2B / Owner's step / Out of scope;
- the evidence (file, test, spec);
- for "Out of scope", the reason.

**No row may stay "missing".** Out of scope is only TCS, payroll TDS, filing, portal access, tax advice and reading statements
from PDF (TRACES protects them with a password, and the text and CSV downloads carry the same data), unless you record a new
reason the owner would accept. Update the matrix at the end of every phase. At the finish it is the proof that nothing was
left behind.

## 4. Phase 1 (P0): what exists, made correct and safe

Each item: a failing test first, then the fix.

1. **The Helm reminder hold.**
   - A confirmed withholding must stop Helm from chasing the **withheld tax** as cash. It must not stop Helm from chasing the
     **cash** the customer still owes.
   - Recommended: the reminder states the cash still due (gross, less reviewed withholding, less matched receipts) when that is
     positive, says in one line that ₹X was withheld as TDS, and is held only when nothing is left to chase in cash.
   - A hold is a **Guard block with a plain reason**, not a FAILED action. The planner knows about it and does not propose it
     again. The person sees "held for withholding review" and a link to the case. Helm lists "reminders held for withholding
     review" with the way to release each.
   - The safety property holds when TRINETRA is off, a plan lapses or evidence goes stale: never chase withheld tax as cash.
   - **Tests:**
     - cash owed → a reminder for the net amount;
     - fully explained → a Guard block;
     - withdrawn → released;
     - mode off → still never chases the tax;
     - no repeated proposals;
     - the sample company untouched;
     - Helm's existing suites green.
2. **"Changed" means the evidence changed.**
   - Version an invoice, a piece of evidence or a statement by a fingerprint of what it **is**:
     - the stored file;
     - the extracted fields TRINETRA reads;
     - the `DocumentRole` facts (role, total, currency, date);
     - for a statement, the stored file.
   - A rename, a summary, a tag, a reprocess with the same fields, or a no-op healing leaves it current. A field correction, a
     different file or a changed total makes it stale.
   - Migrate existing rows in a tested way.
3. **The seller check.**
   - Normalize every PAN.
   - Derive the PAN from a validated `vendor_gstin` (characters 3 to 12; use the repository's GSTIN helper).
   - Compare every identity the invoice offers, and name the field that disagrees.
   - A name-only match needs the reviewer's explicit confirmation, recorded in the case history.
   - Odd input gives a 422, never a 500.
4. **One legal entity, one profile, per organization.**
   - Refuse a second profile for the same PAN in another workspace of the organization, naming the workspace that holds it.
   - Compare with an organization-level keyed fingerprint, never by decrypting across workspaces.
   - Record "a shared profile across workspaces" as the later option. Isolation sweeps stay green.
5. **The case list in batches.** Use the summary's batched path, and add a query-count test.
6. **Who sees the write forms.** An organization owner and a workspace administrator see them; a viewer and a member do not.
   Match the server exactly, with a browser assertion.
7. **One data-lifecycle rule for tax evidence.**
   - Decide whether TRINETRA's reviewed figures are records the business must keep (like GST's books, N-163), or content that
     goes with the documents.
   - Apply it in `data_map.py`, test it, and record the legal basis, marked for the owner's lawyer.

## 5. Phase 2 (P0): available on Business and Enterprise, the safe way

1. **Three modes**, replacing the single boolean:
   - **off:** nobody has live access.
   - **pilot:** live only for organizations a platform administrator enrolled. Enrolment is audited, carries a reason, and is
     shown on the platform admin's organization page.
   - **on:** every organization whose plan includes `capability.trinetra`, that is Business and Enterprise.

   Rules:
   - **One helper decides "is TRINETRA live for this organization"**, and every gate uses it: the routes, the worker, the
     hooks, the event, the Helm annotation, `/access`, the frontend, the website copy where it applies.
   - Keep `TRINETRA_LIVE_ENABLED` as a backward-compatible alias (true = on), or replace it everywhere; record which.
   - **This session ships with the default "pilot".** The owner turns it to "on" after Final 2B and his CA's read
     (launch-checklist step).
   - **Tests:** each gate, in each mode.
2. **Plans.**
   - Business and Enterprise carry `capability.trinetra`; Enterprise also carries `capability.trinetra_all_workspaces`.
   - Starter and the trial keep the synthetic preview, with the upgrade moment naming Business.
   - Keep N-188's capacities, but **decide what they count** so that a real year never hits a permanent wall. Recommended:
     - profiles as today;
     - **active** snapshots (one per profile and year);
     - **open** cases.

     Superseded snapshots and closed cases go against a much higher retention ceiling and age out under the retention policy.
   - **The inquiry allowance:** 50 sent inquiries a month on Business (the brief's figure) and a higher Enterprise figure. Count
     them through the existing metering and limits, never a new counter system; a refusal names the plan that raises it.
   - Update the tier seed, `plan_limits`, the tenancy doc, `pricing.json`, the in-app plan features and the upgrade moments.
   - **Tests:**
     - the 13th quarterly import and the 501st case over time succeed on Business;
     - the open-case cap refuses;
     - the inquiry allowance refuses at 51;
     - Starter is refused with the right plan named.
3. **`preflight.py`** reports the mode, how many organizations are enrolled, and warns when the mode is "on" while a statement
   reader is still unverified.

## 6. Phase 3 (P0/P1): statements in without typing

**Why it earns money:** a distributor's annual statement has hundreds of rows. Typing them is the reason nobody would use it.

1. **A Servabo template** (CSV and XLSX):
   - it carries the statement's columns as Servabo names them;
   - it goes through **the same** preview, confirm and import path as typed rows;
   - every row is validated, and a bad row is refused with its row number, never guessed;
   - it is labelled "your transcription", never an official format;
   - hostile input is tested (formulas, oversize, bad money, bad TAN, duplicate rows).
2. **Readers for the official downloads,** built from official documentation (cite each page and its date) and synthetic
   fixtures:
   - the **Form 26AS / Form 168 text download** from TRACES;
   - the **AIS** "TDS/TCS information" **CSV**. Read its TDS rows only; TCS stays out.

   Each reader:
   - checks the file's own structure and **its own totals** (per deductor, per section or table) against what it read;
   - refuses on any mismatch, unknown section, unknown column or ambiguous layout, with a plain sentence;
   - shows a **mapping preview** (each column → its meaning, rows read, totals per deductor) that the reviewer confirms;
   - records the parser version and the file's fingerprint;
   - keeps the tax year's label exactly as the file states it: historical FY/AY or the new Tax Year, never mixed;
   - keeps each row's section or table item exactly as printed: an old-Act section (for example 194Q) or a new-Act Section 393
     table item. It never converts one into the other, and matching uses it, with the transaction date, when present;
   - **is marked "unverified" in a reader registry** until Final 2B proves it against a real file and records the date. An
     unverified reader works in pilot mode with a visible "unverified reader" label on the snapshot; mode "on" warns in
     `preflight.py` while any reader is unverified.
   - **A password-protected PDF statement** is refused with the instruction to use the text or CSV download. No password
     handling, no PDF parsing of statements.
3. **Limits:** file size, rows (raise the 500-row bound if a real annual statement needs it, with a performance test), zip
   bombs and encodings, all with tests. Everything goes through the existing intake protections.

## 7. Phase 4 (P1): expectations from the records the business already has

Every suggestion here becomes an expectation **only when a person confirms it**, with a reason, as today.

1. **Printed hints → suggestions.** A sales invoice that prints a TDS amount, section and the customer's TAN proposes a
   suggested expectation. It is never confirmed automatically.
2. **An expectations template** (CSV and XLSX: invoice reference, customer TAN, expected TDS, optional section text), matched to
   canonical invoices, with a preview and a refusal per bad row. It is the bridge for Tally users: their accountant exports the
   receipts with TDS and fills the template.
3. **Zoho Books, through the existing Connect** (Final session 1):
   - read customer payments' TDS withheld (Zoho's `tax_amount_withheld` and its TDS fields) for invoices Servabo knows;
   - add the read scope Zoho requires, with the reconnect flow;
   - show the result as **accounting evidence** and as a suggested expectation;
   - extend the Zoho stand-in, and record the field names with Zoho's documentation page and date. **Unverified until 2B.**

4. **A deductor directory.** Each customer's TAN is mapped to the customer (the counterparty) once, reviewed by a person, and
   then used for suggestions and display, with the TAN masked. A TAN seen under two customers is flagged for review, never
   merged automatically.

## 8. Phase 5 (P1): the whole money model

1. **Credit notes.** A credit note linked to an invoice reduces what can be expected for it, conserving every amount, with
   evidence.
2. **Reversals and corrections in a statement.** Negative or corrected rows are netted per deductor and reference **only after
   a person reviews the pairing**; an unpaired one stays an exception.
3. **Advances and earlier triggering events.** A reviewer may place an expectation in the period of its triggering event (an
   advance received in an earlier year), with a reason and evidence. Never inferred.
4. **A taxable basis only when sourced.** When an invoice or the accounting record prints the amount the TDS was computed on,
   keep it as its own dimension, with its source. **Never compute one**, from the bank gap or from the GST value.
5. **Several remittances and split payments** through Helm's matched bank lines. The bank figure is the sum of current matched
   lines, with unknown when Helm cannot say.
6. **Statuses the brief names:**
   - duplicate posting suspected;
   - late posting (first seen in a later snapshot than the period it belongs to);
   - verified corrected (a correction response, then a later snapshot shows the posting);
   - unresolved (closed without resolution, with a reason);
   - plus today's statuses.

   Each has a sentence a person understands.
7. **Reject and annotate.** A reviewer can reject a suggestion (it is not offered again for that snapshot) or annotate a match,
   with a reason, a revision check and history.
8. **Tests:** conservation in every case; no statement amount used twice; cross-year contamination refused; every new status
   reachable and leaving correctly.

## 9. Phase 6 (P1): resolution, end to end

1. **Authorized inquiries.**
   - A workspace administrator presses **Send** on an approved draft.
   - It goes through the existing email path and templates (escaped, rate-limited) to the customer's **confirmed** contact,
     never an address read from a document.
   - It carries a **secure document-request link** (the existing `cases/requests` and `public_document_requests`; no second
     portal) for the customer's Form 16A, advice or correction response.
   - A reply uploaded through the link is attached to the case as evidence of the right kind, and the case history records it.
   - The case shows who approved, who sent, when, the delivery state and the reply.
   - At most one inquiry per case per seven days unless a person overrides with a reason.
   - Counted against the plan's inquiry allowance (Phase 2).
   - **Never automatic.**
   - **Tests:** a revoked or expired link is refused; a reply from the wrong case cannot attach; the template escapes every
     value.
2. **Approval chains (Enterprise).**
   - A configurable policy, following Helm's approval pattern (`helm/approvals.py`), for example: closing a case above ₹X as
     posted, explained or unresolved needs the approval of a named role, by a different person.
   - Business keeps today's simple rule.
   - **Tests:** amounts, roles, the same person refused, a revision moved underneath.
3. **A closure ledger that adds up over time.**
   - Today's comparison with the previous import stays.
   - Add an outcome row each time a closure is confirmed, with a dedupe key (case, the snapshot that confirmed it), so that
     monthly and yearly figures add up without counting anything twice and survive later imports.
   - **"TDS now visible in your statement" is never cash recovered,** and is labelled so everywhere.
4. **Measured time.** Cycle time from case opened to closed, computed from the history. The self-reported minutes stay; both
   are labelled for what they are.
5. **The inquiry draft and the dossier** include the new evidence kinds and statuses.

## 10. Phase 7 (P1): woven in like every other feature

Follow GST Credit's patterns for each:

1. **Getting started:** a TRINETRA step on Business and Enterprise ("check that your customers' TDS reached your statement"),
   ticked from real data.
2. **Global search:** cases by invoice reference and customer name; never by PAN or TAN. Scoped and plan-gated, with the
   second-workspace refusal.
3. **Notifications:** a "TDS credit" category (owners and admins, on by default, optional). Make `trinetra.recompute` do real
   work: compare with each case's last known state and send **one** notice per case revision when a confirmed withholding loses
   its evidence, an import turns a case into "possible missing posting", or a case passes its due date. Otherwise it is not
   queued.
4. **The weekly digest:** one TRINETRA line ("₹X of TDS across N invoices is not yet in your statement"), or its own Monday
   section, following the GST digest's rules (only when there is something to say; preview wording on Starter).
5. **The value receipt and the monthly summary:**
   - "TDS not yet in your statement" (found) and "TDS now visible in your statement" (from the closure ledger);
   - both separate, never added to cash or to GST figures, under Session G's honesty rules.
6. **Automation triggers:** `trinetra.case.gap_found`, `trinetra.case.evidence_stale`, `trinetra.case.closed`. They are
   announced once (Session J's `emit_once`), have catalogue entries and recipes (for example "assign TDS gaps above ₹50,000 to
   the accountant"). Allowed steps are notify, assign, tag and chat; **never sending an inquiry**.
7. **Public webhooks and API (Enterprise):**
   - events for gap found and case closed, alongside `trinetra.case.reviewed`;
   - read routes for cases and summaries under `trinetra:read`;
   - documented in the developer docs;
   - payloads carry ids, states and amounts as decimal strings, never PAN or TAN.
8. **Warehouse dataset (Enterprise):** TRINETRA cases with masked identifiers, following the dataset contract and its tests.
9. **The organization view (Enterprise):** totals per legal entity across the readable workspaces, never double counting one
   entity.
10. **The Resolution layer** (if Final 2A built it): TRINETRA's cases join as their own kind through the live helper. Their figure
    is a possible credit gap, never cash.
11. **Helm:** the planner reads the net-of-TDS cash due (Phase 1), and the ledger shows the withheld amount beside the
    commercial balance.
12. **Enterprise controls:**
    - TRINETRA's exports obey the organization's existing egress lockdown and export policies (`capability.egress_lockdown`), as
      every other export does;
    - legal holds stop TRINETRA's evidence from being purged, as they do for documents.

## 11. Phase 8 (P1): the screens the brief describes

Follow the brief's §5 with Servabo's existing shell, tokens, light and dark, accessibility and phone layout:

- a legal-entity (profile) selector and filters by tax year, customer, workspace, exception type and status;
- KPIs with source and as-of tooltips, and by source confidence (typed, template, verified reader, unverified reader);
- the case drawer with an **amount waterfall** (gross → bank → withheld → posted → gap), a field-by-field explanation of each
  match (which keys agreed, the reader or template that supplied them, the rule version), clickable sources, ambiguity flags, an
  evidence checklist and the audit timeline;
- a **first-run tutorial** for a live organization, and the evidence-freshness banner;
- import screens for the template and the readers, with the mapping preview;
- inquiry screens (draft, approve, send, reply);
- approval screens (Enterprise);
- the Helm list of held reminders;
- every state: loading, empty, error, upgrade, pilot ("not enrolled"), unverified reader;
- a **user guide**, `docs/trinetra/USER-GUIDE.md`, in the style of `docs/automation/README.md`;
- **browser specs** for each journey, by role (owner, admin, viewer) and plan (Starter preview, Business, Enterprise), with axe
  in light and dark and at 390 px.

## 12. Phase 9 (P1): quality gates

1. **Performance:** a budget test like `test_gst_budgets.py`, run with `PERF_BUDGET_MULTIPLIER`:
   - the summary at 5,000 cases;
   - an import of a full annual statement;
   - the organization view over 100 workspaces.

   Record the figures in `PERFORMANCE.md`.
2. **Hostile files** for every reader and template (the corpus patterns). **Isolation sweeps** over every new route.
3. **Prompt injection:** add TRINETRA's new paths (statement files, templates, inquiry replies, Zoho data) to
   `docs/hardening/PROMPT-INJECTION.md` (Final 2A), each with its test. Nothing in a document or file may confirm, allocate,
   close or send.
4. **Privacy:** an explicit TAN pattern in the error-tracking scrubber, and a test that no PAN or TAN reaches a log, a URL, an
   event payload, an email or an export unmasked.
5. **The threat model** (`docs/trinetra/THREAT-MODEL.md`) updated for readers, sending, approvals and the new integrations.

## 13. Phase 10 (must): records, the live prompt and the launch step

1. **`docs/trinetra/`:** COMPLETION (every row final), PRODUCT (metric definitions and the sample walkthrough), ARCHITECTURE,
   EXISTING-CAPABILITY-MAP, LEGAL-SOURCES (each reader's documentation page and date), LAUNCH-GATES (the modes, the reader
   registry, the owner's steps), TEST-PLAN, DELIVERY, THREAT-MODEL and USER-GUIDE, all saying what is true after this session.
2. **Campaign records:**
   - `STATE.md` (next action: Final session 2B);
   - HANDOFF "Final session 2T → Final session 2B" (what 2B must try for real; the commands; what is unverified);
   - `FINDINGS.md`, `NEEDS-OWNER.md`, `COVERAGE.csv`, `CHANGELOG.md`, `RUNBOOK.md`, `CONFIGURATION.md`, `PRODUCT-NEXT.md`.
3. **The website:**
   - `/trinetra` and the pricing page say "Business and Enterprise".
   - Choose how the page says "rolling out" until the owner switches the mode on, for example a build setting, and record it.
   - Keep the bounded claims: no refunds, no guaranteed credit, no government connection.
4. **The owner launch checklist** gains a TRINETRA step. In plain words:
   - after Final 2B marks the readers verified, your CA reads `/trinetra`, the in-app wording and the sample (about an hour);
   - then set the mode to "on" and restart;
   - `preflight.py` confirms it.
5. **`docs/sessions/FINAL-2-LIVE.md`:** add (or replace) its TRINETRA phase, and remove the "Do not run this yet" note at its
   top:
   - pilot mode, with the owner's own organization enrolled;
   - his own **Form 26AS / Form 168 text download** and **AIS CSV**, downloaded by himself, kept outside the repo and never
     pasted into the chat: each reader read, its totals self-check passed, the reader marked verified with the date (a
     synthetic fixture of the real shape committed; the real file never);
   - one real or realistic case end to end: expectation (typed, template or Zoho), import, allocation, the advice and the
     accounting record, confirmation, the Helm reminder for the **net** cash, an inquiry sent to his own second address with
     the secure link, a reply uploaded through it, closure, the exports;
   - Zoho Books' TDS withheld read from a real free organization;
   - the "TDS credit" notice and the digest line in a real inbox;
   - each TRINETRA row of `COMPLETION.md` marked "Verified in 2B" or "Differs" with the fix.
6. **`docs/FINAL-SESSIONS.md`:** what 2T did, and what the owner prepares for TRINETRA in 2B:
   - his own Form 26AS text download and AIS CSV (any PAN holder can download his own);
   - if possible, one sales invoice on which a customer deducted TDS.

## 14. Finish line

- **`docs/trinetra/COMPLETION.md` has no row left "missing".** Every row is Done, Built in 2T with its test, waiting for 2B
  with what 2B must do, an owner's step, or out of scope with its reason.
- **These pass,** locally or on the ready PR's CI:
  - `pytest -q`;
  - the frontend's typecheck, lint, `check:self`, `test:unit` and build;
  - the website's checks;
  - the full browser suite, including the TRINETRA phases.
- `campaign_slices.py --check all` exits 0. There is one Alembic head, with up, down and up, populated.
- **Mark the PR ready.** The description explains, for a non-engineer:
  - what TRINETRA does now;
  - who gets it;
  - what 2B will prove;
  - the one setting the owner changes to launch it;
  - what is out of scope and why.
- **CI is green before the owner merges.** Then stop, and tell the owner in eight lines or fewer:
  - what was built;
  - what was fixed;
  - what 2B must prove;
  - the launch step.
