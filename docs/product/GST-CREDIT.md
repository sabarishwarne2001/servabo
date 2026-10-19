# GST Credit

_Session F. Everything here is decision support, **not tax advice**: check with your chartered accountant._

## What it does, in plain words

Every month an Indian business can claim input tax credit (ITC) only on supplier invoices that the supplier has
reported and that show in the buyer's **GSTR-2B** statement on the GST portal. Finance teams compare GSTR-2B with
their purchase invoices by hand in Excel, chase suppliers who did not file, and lose credit when they miss
something. A second rule, the 180-day rule, makes credit reversible when an invoice stays unpaid too long.

Servabo already reads the purchase invoices (nobody types the purchase register). GST Credit adds:

1. **Import** a GSTR-2B download (JSON, or a zip holding it).
2. **Reconcile** it against the invoices Servabo has read: which are claimable, which differ, which the supplier
   has not reported, which the supplier reported that you do not have.
3. **Recommend** what to do in the portal's Invoice Management System (Accept, Pending or Reject), with the reason.
4. **Warn** about the 180-day rule on unpaid invoices, using Helm's payment records.
5. **Draft** a reminder email to a supplier listing the invoices missing from your GSTR-2B.
6. **Export** the reconciliation to Excel.

GST credit, the MSME 45-day law and the cash plan are one plan: Helm's mandates `gst_pay_within_180_days` and
`gst_hold_until_reported` (see `docs/helm/MANDATES.md`) use the same data.

## Where it is, and who gets what

Documents → **GST credit** (in the workspace sidebar under Enterprise processing, next to Three-way matching).

| | Every plan (the preview) | Business, Enterprise (`capability.gst_credit`) | Enterprise (`capability.gst_credit_all_workspaces`) |
|---|---|---|---|
| Import GSTR-2B files | yes | yes | yes |
| The six figures and their counts | yes | yes | yes |
| The sample company's full reconciliation | yes (read-only) | yes | yes |
| Supplier list, invoice list and side-by-side drawer | locked | yes | yes |
| IMS recommendations, decisions | locked | yes | yes |
| Excel export, supplier reminders | locked | yes | yes |
| One reconciliation per GSTIN across every workspace; `gst:read` API keys | | | yes |

Roles: viewers read; owners, admins and workspace contributors import, decide and export. A billing member with no
workspace grant has no workspace access (as everywhere); on Enterprise the organization page is open to owners,
admins and billing.

## The rules, and where they come from

Each statement in the product cites its source. **The official pages (cbic-gst.gov.in, tutorial.gst.gov.in) could not
be opened from the build sandbox** (the host did not resolve). The sections below were cross-checked through search
results that list the official CBIC documents and secondary commentary; the owner or the CA should read the linked
pages once. If a fact could not be confirmed, the product says less.

- **Credit needs GSTR-2B.** Section 16(2)(aa), CGST Act, 2017 (in force from 1 January 2022): credit only for
  invoices the supplier has furnished (GSTR-1 or IFF) and that are communicated to you, in practice shown in your
  GSTR-2B. [CGST Act, CBIC](https://cbic-gst.gov.in/pdf/CGST-Act-2017-amended-01012022.pdf).
  GSTR-2B is a monthly statement generated after the month ends (14th for monthly filers). Download path on the
  portal: Returns Dashboard → GSTR-2B → Download → JSON ([tutorials](https://tutorial.gst.gov.in)).
- **The 180-day rule.** Second proviso to Section 16(2) and Rule 37: if the value of the supply plus tax is not paid
  to the supplier within 180 days of the invoice date, the credit taken is added back to your output tax with
  interest (Section 50); it can be claimed again once paid. [Input tax credit, CBIC](https://cbic-gst.gov.in/input-tax-credit-rules.html).
  Servabo shows the amount at risk and says interest may apply. **It does not calculate interest.**
- **Time limit.** Section 16(4): credit for an invoice of a financial year cannot be claimed after 30 November of the
  following year, or the filing of the annual return if earlier. There are special rules for some years (the
  Finance (No. 2) Act, 2024 added exceptions): the product says "some cases have special rules".
- **Invoice Management System (IMS), from October 2024.** You can Accept, Reject or keep Pending each supplier record
  before you file GSTR-3B; no action means it is treated as accepted; GSTR-2B can be recomputed after changes.
  Pending has limits for some records (from the October 2025 period): **not confirmed here**, so the screen only
  says the portal may limit it. Servabo recommends; the person acts on the portal.

## How the reconciliation works

Inputs: the active GSTR-2B returns of one GSTIN (every imported period together) and the purchase invoices and
notes in the workspace. "The books" are documents Helm classifies as invoices or credit notes whose **buyer GSTIN is
the return's GSTIN**; with no buyer GSTIN, a document counts when its seller is not one of "our" identities (Helm's
identity rules plus the return's own GSTIN), so no new setting is needed. Documents in another currency, and those
that carry no GST, are not expected in GSTR-2B and are left out.

1. **Amendments** (`b2ba`, `cdnra`) replace their originals; the same supplier document reported in two periods is one
   document and the later copy is marked a duplicate.
2. **Exact match:** the same IRN, else the same supplier GSTIN and normalised document number
   (`normalize.document_number`, also ignoring a financial-year token such as `/25-26`) with dates in one financial year.
3. **Suggested match:** same supplier, dates within 3 days, value within the tolerance, similar numbers. **Never
   confirmed automatically**: it waits for a person.
4. **One to one:** a document matches at most one record and the other way round.
5. **Differences:** taxable value, each tax head and invoice value are compared; a difference beyond the tolerance
   (₹1 per head by default, set per workspace) makes the line `MATCHED_WITH_DIFFERENCES`. Date and number formatting
   differences are shown as notes. Only what both sides carry is compared.
6. **Across periods:** a book invoice is waiting until it appears in any imported period, and the period it first
   appeared in is recorded ("reported late, in October's GSTR-2B"). "Waiting" only applies to invoices dated inside
   the imported window (first imported month to last imported month).
7. **A person's decision** (confirm a suggestion, "not ours", link by hand) is applied first, kept across re-imports
   (it is keyed by supplier GSTIN, document number and kind), audited, and can be undone.

| Status | Meaning |
| --- | --- |
| `MATCHED` | Claimable |
| `MATCHED_WITH_DIFFERENCES` | Claim the lower figure; ask the supplier to amend |
| `SUGGESTED` | Waits for a person |
| `WAITING_FOR_SUPPLIER` | In the books, in no GSTR-2B: the credit is deferred, at risk as the Section 16(4) date nears |
| `NOT_IN_BOOKS` | The supplier reported it; Servabo has not seen it: upload it, or act in IMS |
| `NOT_ELIGIBLE` | GSTR-2B says the credit is not available (`itcavl = N`), with the reason code as given |
| `REVERSE_CHARGE` | You pay this tax yourself |
| `NOTE` | A credit note (lowers the credit) or debit note (adds to it) |

**The 180-day exposure** is read for each purchase invoice from Helm's settlement records: an invoice not recorded as
paid in Servabo that is 150 days old or more is shown as at risk. "Not recorded as paid" is what Servabo knows; a
payment made outside Servabo and its bank import is invisible to it.

**IMS recommendations** are in `NEEDS-OWNER.md` N-136. **Recompute:** on import, on a decision, after documents finish
processing (debounced to one job every ten seconds per workspace, through the worker) and nightly; a recompute is
idempotent.

## Enterprise: one reconciliation per GSTIN across every workspace

`capability.gst_credit_all_workspaces` (Enterprise), the same pattern as Helm's `helm_all_workspaces`. An organization
that books its purchases in several workspaces (a branch each, a client each) gets one answer per GSTIN: the GSTR-2B
returns imported **in any workspace**, matched with the purchase invoices of **every workspace** that holds that GSTIN's
purchases.

- **Where:** Organization → **GST credit, all workspaces** (`/organizations/{org}/gst`), for owners, admins and billing.
  Read-only: importing, deciding, exporting and reminders stay in each workspace's own page. Workspace members who are
  not owners, admins or billing never see the organization page; their own workspace's page is unchanged.
- **Which workspaces and documents:** active workspaces, never the sample company. A workspace with an active return
  of the GSTIN is a "home" workspace and its documents count as they do in its own reconciliation (buyer GSTIN, else
  "not ours"). Any other workspace contributes only documents that name the GSTIN as their buyer, so a workspace is
  never made to claim documents that belong to another GSTIN. Where the same period was imported in more than one
  workspace, the latest import is used. The tolerance is the strictest of the workspaces'; people's decisions are the
  union of the workspaces' (the latest wins).
- **How it is computed:** the stored rows cannot hold it (their composite keys tie a row to one workspace's
  documents, ARCH-41), so `services/gst/org.py` runs the same pure matching when the page is opened and keeps the
  answer for 60 seconds (an import or a decision shows at once; documents and payments within the minute). With one
  workspace, the organization's figures and list equal the workspace's own (a test compares them).
- **Roles:** the figures are the organization's. The supplier and invoice lists are cut to the workspaces the person may
  read: owners and admins all, billing the ones it has grants on.
- **API:** `GET /organizations/{id}/gst/summary | suppliers | records` (the workspace routes' filters, plus
  `workspace_id` on records). **API keys** with the scope `gst:read` read exactly these three, on a plan with the
  capability (402 otherwise); a key can import, decide or export nothing. The scope is in the same migration
  (`g1a1_gst_credit`) as the tables; Billing keys may hold it, Member keys may not.
- **Not stored:** nothing here is written, so nothing needs a recompute job; the cache is dropped on restart.

## The e-invoice QR code (stretch)

An Indian e-invoice carries a signed QR code (a JWT) holding the supplier and buyer GSTIN, the document number, type
and date, the invoice value, the item count, the main HSN code and the **IRN**. It is read in two steps, because
OpenCV lives only in the OCR image (the web image must not carry it): `einvoice_scan.py` finds the code in the pictures
at extraction (`document.extract`, the OCR worker) and keeps the token text in `extraction_metadata["qr_codes"]`;
`einvoice.py` reads and trusts the token at enrichment (`document.enrich`, for invoices and notes; never raises):

- **Finding it:** OpenCV decodes the code from the first three pages of a PDF (rendered with PDFium) or from an image:
  the WeChat detector first (contrib, no model file; the one that reads the dense codes an e-invoice has), then the
  Aruco-based and standard detectors (the standard one fails on dense codes, which the tests show).
- **Trust:** the signature is verified **only if `EINVOICE_QR_PUBLIC_KEY_PEM` (NIC's published key) is configured; none
  is shipped**. Without it the values say "signature not verified": they fill fields the model left empty, never replace
  what it read, and a difference is recorded as a conflict. With a key that verifies, the code's values **win**.
- **Where it shows:** each field it supplied or checked is listed in `extraction_metadata["einvoice_qr"]` ("from the
  e-invoice QR code": filled, confirmed, overridden, conflicts, whether the signature was verified).
- **Effect on GST Credit:** the IRN in the entities matches GSTR-2B exactly (method IRN), even when the model misread the
  number.
- **Unverified:** the payload layout follows the NIC e-invoice schema as publicly described; it was not tried on a real
  e-invoice. The tests use generated codes (`qrcode`, a dev-only dependency) and an invented RSA key. There is no screen
  for the provenance yet.

## API (workspace-scoped, `/api/v1/workspaces/{id}/gst`)

`POST /returns` (upload `.json` or `.zip`: 25 MB, 50,000 records, zip limits as for archives, JSON nested at most 12
deep), `GET /returns`, `GET /summary`, `GET /suppliers`, `GET /records` (filters, `offset`/`limit` bounded),
`GET /records/{id}`, `POST|DELETE /records/{id}/decision`, `GET /export.xlsx` (sheets: Summary, Matched, Differences,
Waiting, Not in books, IMS actions), `GET /suppliers/{gstin}/reminder` (a draft) and `POST …/reminder/send` (only to a
contact Helm already knows, only on request; never from the sample company), `GET|PATCH /settings` (the tolerance).
Importing is audited (`GST_RETURN`), decisions and exports too (`GST_MATCH`). Text from files and documents is
untrusted: the workbook writes anything that looks like a formula as text.

## GSTR-2B file format: what is assumed

Top level (optionally wrapped as `{status, data: {chksum, data: {…}}}` or `{data: {…}}`): `gstin`, `rtnprd` (MMYYYY),
`version`, `gendt` (dd-mm-yyyy), `itcsumm`, `docdata`. `docdata` sections: `b2b`, `b2ba`, `cdnr`, `cdnra`, `isd`,
`isda`, `impg`, `impgsez`, `ecom`, `ecoma`. A `b2b` supplier has `ctin`, `trdnm`, `supfildt`, `supprd`, `inv[]`; an
invoice has `inum`, `typ`, `dt`, `val`, `pos`, `rev`, `itcavl`, `rsn`, `diffprcnt`, `srctyp`, `irn`, `irngendate`,
`items[]` (`num`, `rt`, `txval`, `igst`, `cgst`, `sgst`, `cess`). `b2ba` adds `oinum`, `oidt`; `cdnr` notes are `nt[]`
with `ntnum`, `typ` (C/D), `dt`, `val` and the same tax fields. Only `b2b`, `b2ba`, `cdnr`, `cdnra`, `ecom`, `ecoma`
are matched against invoices; the rest are stored for the totals.

## What is unverified

- **The file format is unverified against a real portal download.** The fixtures are invented (GSTINs with valid check
  characters). Session D tries a real file (the owner's CA can supply one); anything unexpected is reported in words
  on import and never silently dropped.
- **The official pages were not opened** from the build sandbox; the law links point at the official documents but the
  wording of 16(2)(aa), 16(4), the second proviso, Rule 37 and the IMS tutorial should be read once against them.
- The IMS "Pending" limits from October 2025 are not stated (see above).
- The reason codes (`rsn`) are shown as given: no official source for their meanings was available.
- The 180-day figure depends on payments Servabo knows about (Helm's settlements and bank imports).
- The e-invoice QR payload layout and a real signed code (see above).
- A real model reading a real GST invoice through the new extraction schema (F-524, N-138) has not been run.
- Section 16(4) dates ignore the special cases noted above.

This is a recommendation, not tax advice. Check with your chartered accountant.
