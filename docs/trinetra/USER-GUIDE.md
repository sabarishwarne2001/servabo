# TRINETRA (TDS credit) — user guide

_Written in Final session 2T (2026-10-28). For the owner, the accountant and anyone who works the cases. No programming is needed._

When a customer pays you, they may keep back part of the money as **tax deducted at source (TDS)** and pay that tax to the
government for you. You are meant to find it in your tax statement (Form 26AS, or Form 168 under the Income-tax Act 2025, or the
AIS). TRINETRA checks, invoice by invoice, **whether the tax your customer says it withheld is in your statement**, and shows you
where it is not. A missing line is a **thing to check**. It is never a refund, never money you are owed, and never a statement that
anyone did something wrong.

Open it from the workspace menu: **TDS credit** (the page is titled *Credit assurance*). It is on **Business** and **Enterprise**.
While Servabo is still checking the official statement layouts with a tax adviser, it is in a **pilot**: your organization must be
enrolled by Servabo first. Until then you see the synthetic examples and the sentence *"TRINETRA is in a pilot and your
organization is not enrolled yet"*. Nothing about your own data changes.

## What it will never do

- It never asks for, stores or uses your tax-portal login, and never signs in to the portal for you.
- It never sends a message to a customer on its own. A person presses **Send**.
- It never tells you a rate, a section or whether a credit is allowed. It shows what **your documents say** next to what **your
  statement says**.
- It never shows a full PAN or TAN on a screen, in an email, in a link or in a log. PANs are stored encrypted; TANs are kept only
  as masked keys (`******234F`).
- It does not read statements from PDF. Use the template, the text download or the AIS CSV.
- It does not handle tax collected at source (TCS), payroll TDS or filing.

## Who sees what

| | Viewer / member | Workspace admin | Organization owner / admin |
|---|---|---|---|
| Cases, statements' effect, suggestions, closure ledger | read | read and write | read and write |
| Import a statement, accept a suggestion, record a decision, ask a customer | no | **yes** | yes |
| Approve a closure (Enterprise) | no | no | **yes, if it is not the person who asked** |
| Set the approval policy (Enterprise) | no | no | **yes** |
| Across-workspaces page | no | no | Enterprise only |

The write buttons are simply not shown to a role that cannot use them.

## Try it in two minutes (examples)

1. Open **TDS credit**. The page opens on **Illustrative synthetic data**: thirteen made-up cases that show every status.
2. Search for *Exact posted*, choose the case and read **Case insight**: how the amounts add up, which evidence is on the table and
   how the match was made.
3. Nothing here is sent anywhere and no real document is needed.

When your organization is live and has a legal entity, the page opens on **your workspace** instead. **Explore examples** switches
back.

## Set it up (live)

The first-run guide at the top ticks itself as you go: **1.** a legal entity, **2.** one confirmed invoice, **3.** a statement,
**4.** one decision.

### 1. The legal entity

Under **Cases**, open **Add reviewed evidence** and choose **Legal entity profile**: a name and the **PAN**. An organization keeps
**one profile per legal entity** (the same PAN cannot be a profile in two workspaces), so the same tax credit is never counted
twice. If it already exists in another workspace, the message names that workspace.

### 2. An invoice where a customer withheld tax

You can get there three ways. Each one only ever creates a **suggestion**; a person accepts it:

- **Printed on the invoice.** *Suggestions* → **Look for TDS printed on invoices**. Servabo suggests an expectation for each
  invoice that prints a TDS amount. A printed figure is not a rate or a section recommendation.
- **Your own list.** *Suggestions* → **Fill in an expected-TDS template**: download the CSV or Excel file, fill in the invoice
  reference, TAN, amount and (optionally) section, upload it, and read the row-by-row check before adding.
- **Zoho Books.** *Suggestions* → **Read Zoho Books** reads the "tax amount withheld" on your customer payments, read only. This
  reader is **unverified** until it has been checked on a real Zoho Books organization.

Press **Accept as a case** and write what you checked. If the invoice does not show the TAN, enter the customer's TAN as on their
advice. If the seller's name on the invoice is a different spelling of your legal entity, tick the box that says you checked it is
the same. A TAN that appears under two customers is **flagged** until you confirm who it is (*Customers and their TANs*).

You can also confirm a case by hand from **Add reviewed evidence** → *Confirmed withholding expectation*.

### 3. Your tax statement

**Statements** → **Import your tax statement**. Three ways, and always **preview first**:

| Source | What to upload | Label you will see |
|---|---|---|
| **Servabo template** | The CSV or Excel template you filled in from your statement | *Your transcription* |
| **Form 26AS or Form 168** | The **text** download (not the PDF) | *Official download, unverified reader* |
| **AIS** | The AIS TDS/TCS information as **CSV** | *Official download, unverified reader* |

The preview shows the reader, the **tax-year label exactly as the file states it** (financial year / assessment year, or tax year;
Servabo never converts one into the other), the rows grouped by customer with masked TANs, every check against the file's own
totals, and what was left out (for example TCS rows). For an AIS file it also shows **which column means what**; change a column
that is wrong and preview again. If the file's total disagrees with its rows, or the PAN in the file is not your entity's, nothing
can be imported. Tick the confirmation and press **Import this statement**. A statement is saved as a snapshot that never changes;
the next import is a new snapshot.

> **Unverified readers.** The two official readers were built from descriptions of the layouts and tested on made-up files that
> have the same shape. Servabo will mark each one **verified** only after it has been proved on a real downloaded statement.
> Until then, check the rows against your own statement before you confirm.

If you would rather type: **Add reviewed evidence** → *Reviewed statement transcription* (one row per line: TAN, amount, reference).

### 4. Reviewing a case

Choose a case in **Cases**. **Case insight** shows:

- **How the amounts add up** — invoice gross, cash received, tax withheld (confirmed), posted in the statement, what is left to
  check. An unknown figure says *Not known*; it is never guessed.
- **Evidence on the table** — invoice, bank receipt, the customer's advice, an accounting record, credit notes, the statement.
  *Changed since it was confirmed* means the evidence really changed (a rename or a re-read does not count).
- **Why this match** — for each statement row: the deductor, the entity and tax year, the section or table item **as printed**, the
  amount, the reference; whether each agrees, differs, or is not printed on one side. Servabo never converts an old-Act section into
  a new-Act table item.

Under that, **Review decision**:

| Decision | Use it when |
|---|---|
| Allocate a statement posting | You verified a row and want to count an amount of it for this case |
| Mark as disputed | The customer or you disagree about the amount |
| Close with an explanation | The difference is understood (write why) |
| Withdraw the case | It should not have been a case |
| Confirmed by the accountant | A fully allocated, current posting is in the statement and an accountant has reviewed it (Enterprise: a different person from the one who allocated) |
| Leave unresolved | You tried and the customer never answered |
| This statement row is not the match | Servabo suggested a row and it is wrong; it is not offered again for that statement |
| Add a note | Anything the next reviewer should know |
| Reopen | New evidence |

Every decision needs a reason of at least ten characters and creates a new **revision**; nothing is ever overwritten.

**Reversals.** A reversal or correction in a statement is never netted on its own. **Reversals** lists each one with the rows it
could reverse; you pair them with a reason, and you can unpair them.

**More evidence.** *Ownership and supporting evidence* attaches the customer's advice, an accounting record, a credit note
(which lowers the invoice amount the tax can rest on), a correction response or a triggering event, and can state **the amount the
tax was computed on** — only when a document states it; Servabo never works it out. *Correct or reconfirm expectation* creates a new
revision when the invoice changed.

### What the statuses mean

| Status | In plain words |
|---|---|
| Posted in your statement / Posted late / Posted after a correction | The amount is in the statement (late: booked in a later tax year) |
| Possible missing posting | A statement is imported and has nothing for this customer and amount |
| Amount differs | A posting exists with a different amount |
| A match to confirm | One row fits; a person must allocate it |
| More than one possible match / Possible duplicate rows | Several rows fit; Servabo will not guess |
| Same invoice under another TAN | Another deductor's row carries this invoice reference |
| Evidence needed | The expectation is not supported (for example the invoice changed) |
| Waiting for a statement | No statement is imported yet. This says nothing about missing credit |
| Disputed / Withdrawn / Closed with an explanation / Left unresolved | A person decided |

## Ask the customer for the document

In a case, **Ask the customer for the document**: choose what to ask for (a Form 16A certificate, a withholding advice, or the
response to a correction), **Prepare a draft**, edit it, **Approve the draft**, then **Press Send**. The rules:

- It goes only to the customer's **confirmed contact** in Helm (an address a person confirmed, not one read from a document).
- Nothing is sent by itself, not even by an automation. The approval and the send are recorded with who did them.
- One inquiry per case per week, unless a person writes a reason to send another.
- Your plan has a monthly allowance (Business 50, Enterprise 500).
- The email carries a one-time secure link to upload the document. It asks for a document and **alleges nothing**. It never contains
  a PAN or TAN. When the customer uploads, the reply appears on the case.
- If your organization's network policy (egress lockdown) does not allow the mail server, the send is refused in words.

## Closing, approvals and the closure ledger

On **Enterprise**, an organization owner or admin can set a rule under **Approvals**: *closing a case worth at least ₹X, in these
ways, needs an admin or owner other than the person who asked*. The request is recorded and nothing is closed until it is approved;
an approval is good only for the case revision it was asked on. Approvers see **Closures waiting for approval**.

**Closures** shows **TDS now visible in your statement**: the tax of cases that **had a gap in an earlier import** and that an
accountant later confirmed as posted. It is evidence that a credit appears in your statement. It is **not cash, not a refund and
not money saved**, and it is never added to GST or cash figures. The same page shows how long cases take to close, measured from the
case history.

## Where else it shows up

- **Getting started** on the dashboard has a TDS step that ticks when you import a statement.
- **Search** (Ctrl/⌘ K) finds a case by **invoice reference** or **customer name**, never by PAN or TAN.
- **Notifications**: a *TDS credit* category (owners and administrators, on by default). One notice per case revision when a
  confirmed withholding **loses its evidence**, an import leaves a **possible missing posting**, or a case is still open **30 days**
  after it was opened. Many at once are one notice. **Monday**, 09:00 in your workspace's zone, one short email says how much TDS
  across how many invoices is not yet in your statement — only when there is something to say. Turn it off in *Notification
  settings*.
- **Value receipt and monthly summary** show two lines of their own: *TDS not yet in your statement* and *TDS now visible in your
  statement*. Neither is the headline, neither is "money found", and neither is added to anything else.
- **Helm**: when a customer withheld tax, the reminder asks only for the **net cash** still due. When nothing is left to chase, the
  reminder is **held** (a Guard block, with the case that releases it) and listed on the Helm cockpit under *Reminders held for
  withholding review*. The ledger shows the withheld amount beside the commercial balance.
- **Recoveries** lists *TDS not yet in your statement* as its own kind. Its figure is a possible gap, never an amount in the
  "found" totals, and verifying it records no recovered money.
- **Automation** (Workflows → *TDS credit*): triggers **TDS credit gap found**, **TDS confirmation lost its evidence** and **TDS
  case closed**, and two recipes (assign large gaps to your accountant; tell admins when evidence goes stale). A rule on these
  can **notify, assign a reviewer, tag the invoice and post to chat**. It can never send an inquiry, an email or a webhook.
- **Across workspaces** (Enterprise): organization page → *Credit assurance across workspaces*. Each legal entity is counted once.
- **Enterprise integrations**: webhook events `trinetra.case.gap_found`, `trinetra.case.closed` and `trinetra.case.reviewed` (ids,
  states and amounts only, never a PAN, a TAN, an invoice number or a name); a read-only API key scope `trinetra:read` for
  `/organizations/{id}/trinetra/summary` and `/cases`; and the `TRINETRA_CASES` warehouse dataset with masked identifiers. See
  `docs/product/WEBHOOK-EVENTS.md`.

## Limits and your data

| | Business | Enterprise |
|---|---|---|
| Legal-entity profiles | 2 | 10 |
| Active statement snapshots | 12 | 60 |
| Open cases | 500 | 5,000 |
| Customer inquiries sent per month | 50 | 500 |

A closed case or a replaced snapshot frees its place. Files are limited in size and rows, and a malformed file is refused with a
sentence, not a crash.

TRINETRA's cases, decisions and snapshots are **working papers**: they are erased with the invoice, advice or statement document
they were built from, and the compliance export hands you the whole dossier first. A legal hold on a document stops it being
deleted, and so keeps the case. A statement imported from a file has no document attached, so it is not aged out by a retention
sweep.

## When something looks wrong

| You see | What to do |
|---|---|
| *TRINETRA is in a pilot and your organization is not enrolled yet* | Ask Servabo to enrol you, or explore the examples |
| *This legal entity already has a TRINETRA profile in the workspace …* | Use that workspace, or remove the profile there first |
| The preview says the tax-year label does not match | You chose a different year; fix the year, never convert it |
| *The file's own total does not match the rows* | The file was cut or edited; download it again |
| A case says *Evidence needed* after the invoice was re-read | Open **Correct or reconfirm expectation** |
| A reminder in Helm is *held for withholding review* | Review or withdraw the case; Helm re-plans on its own |
| You cannot send an inquiry | The customer needs a confirmed contact in Helm, or the weekly or monthly limit was reached |

## For the person running Servabo

Mode, enrolment, plan figures, the unverified readers and the official sources are in `docs/trinetra/LAUNCH-GATES.md`,
`docs/trinetra/LEGAL-SOURCES.md`; the owner's launch checklist (step 13) is in `docs/hardening/HANDOFF.md`, and the exact commands
(`python scripts/trinetra_pilot.py enrol …`, `preflight.py`) are in `docs/RUNBOOK.md`, "TRINETRA deployment supplement".
