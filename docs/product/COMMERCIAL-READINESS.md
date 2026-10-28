# Can Servabo be sold, and make money? (Final session 2A, Phase 0A)

_Written 2026-10-26. An honest page for the owner to act on, not a sales page. Prices are the new ones (N-187, §4 below)._

**The short answer.** The engineering is far ahead of the proof. Servabo can be sold to its target customer at the new rupee prices
and keep a healthy margin, but **nothing yet shows a buyer that it works on their invoices or saves them money**: no measured accuracy on
real Indian invoices, no real integration tried, no customer. The next step is not more features. It is the proof kit (an accuracy report
on 30 to 50 real invoices, Final session 2B) and two or three paid 30-day pilots with distributors introduced by their CA
(`PILOT-PLAYBOOK.md`).

## 1. Who buys, and why

**The customer (N-186):** Indian **distributors, wholesalers and manufacturers** with roughly 50 to 2,000 supplier invoices a month,
an accounts team of one to five people and a CA firm that files their GST; and **the CA firms** that serve many such clients.

**The jobs they would pay to have done**, and where Servabo does each today:

| Job | Why it costs them money | Where Servabo does it today |
| --- | --- | --- |
| **Keep every rupee of GST input credit** | A supplier who does not report an invoice in GSTR-2B blocks the credit; after the Section 16(4) date it is lost | GST Credit (`/w/…/gst`): GSTR-2B import, matching, "waiting for supplier", the IMS action, supplier reminders, the Monday digest |
| **Stop paying more than agreed** (price or quantity above the order, duplicates) | Overcharges and duplicate invoices are paid because nobody checks every line | Three-way matching (`/w/…/procurement`), the forensic radar (`/w/…/radar`), Helm's hold |
| **Pay on time, not early, not late** (MSME 45 days, discounts, late fees) | A late MSME payment loses the expense deduction (43B(h)); a missed discount is lost cash | Helm (`/o/…/helm`): ledger, plan, the MSME rules, approvals |
| **Stop typing invoices** | Hours of data entry and errors every month | Extraction and review (`/w/…/documents`, the review hub), email-in, zip upload, the Tally Prime file, Zoho Books Connect |
| **(CA firms) Do the above for many clients** | Each client is a separate set of books | One organization per client or one workspace per client; Enterprise's views across workspaces |

## 2. Against whom

Prices are as published on the vendors' own pages **as quoted by web-search extracts on 2026-10-26**: the build sandbox could not open
the pages themselves (every direct fetch failed), so **check each figure in a browser before quoting it to anyone**. "GST extra" means
18% is added. Market-size figures are left out: none was found with a source good enough to cite.

| What they use or could buy | Price (as found) | Where Servabo is better | Where it is worse | What a buyer would say |
| --- | --- | --- | --- | --- |
| **TallyPrime** (tallysolutions.com/buy-tally/) | Silver ₹22,500 once (+ GST), or ₹750 a month rental; Gold ₹67,500 or ₹2,250 a month; renewal ₹4,500 / ₹13,500 a year. Has its own GSTR-2B reconciliation report (help.tallysolutions.com/gstr-2b-reconciliation/) | Reads the invoices (no typing), three-way matching, duplicates, supplier follow-up, MSME deadlines | Tally **is** their books; Servabo is another tool next to it. Tally's 2B report is already paid for | "Tally already does 2B. Why another login?" The answer must be the typing saved and the money found, measured |
| **Zoho Books India** (zoho.com/in/books/pricing/) | ₹749 to ₹7,999 an organization a month billed yearly (Standard to Ultimate), ₹899 to ₹9,599 monthly; extra users ₹150 a month; GST extra | Deeper GST matching and supplier follow-up, document reading, Helm | Zoho is a full ledger with bank feeds, at a lower price per organization (not per user) | "Zoho is cheaper and is my books." Servabo must sit on top of Zoho (Zoho Books Connect), not compete with it |
| **ClearTax / ClearMax ITC** (cleartax.in/s/max-itc) | No published price for ClearMax ITC (contact sales); a "GST Software for Professionals" listing at ₹11,999 (term and GST unclear) | Reads the invoices themselves; overcharges and duplicates; payment timing | Clear is the brand CAs know, files returns, and has an enterprise sales team | "We already use Clear for filing." Position next to filing, not against it |
| **GSTZen** (a low-cost reconciliation tool; gstzen.in/pricing-taxpayer-plans) | Per GSTIN per year, GST extra; third-party listings give Basic from about ₹7,650 a GSTIN a year (vendor figure not confirmed) | Everything beyond 2B matching | Cheaper for a business that only wants 2B matching | "₹7,650 a year does my 2B." Servabo must not be sold as a 2B tool alone |
| **Suvit / Vyapar TaxOne** (suvit.io/pricing) | One "Unlimited" plan at ₹10,000 a year (shown as 50% off ₹20,000), GST extra | Matching, duplicates, payment timing, GST follow-up | Built for CA firms' data entry into Tally, cheap, already known to CAs | "Suvit enters my clients' bills into Tally for ₹10,000 a year." Servabo's Starter is ₹14,990 a user a year |
| **Indian AP automation: Cflow** (cflowapps.com, help page) | $11 a user a month (minimum 10 users) and $16 (minimum 20), billed yearly. Cashflo and Peakflo publish no price (quote only) | GST-specific depth, no 10-user minimum, a rupee price | Approval workflows and ERP connectors proven at customers | "Cflow does approvals." Servabo wins only on GST and money found |
| **Global document AI: Rossum** (rossum.ai/pricing/) | Starter "from $18,000 a year", billed per page. Nanonets bills credits per processing step (third-party trackers: $0.02 to $0.30 a step). Docsumo quotes by volume | A tenth of the price; Indian GST knowledge built in; ready screens instead of a toolkit | Their accuracy is measured and published; ours is not | "Show me your accuracy on my invoices." **This is the gap the accuracy report closes** |
| **TDS / Form 26AS reconciliation** (for TRINETRA): ClearTDS Expert Pack (cleartax.in) | ₹25,000 a year renewal for 50 TANs (was ₹35,000; GST not stated). Gen TDS (SAG Infotech) ₹6,000 install + ₹3,500 a year; it downloads 26AS but is not documented as reconciling it. KDK Express RECO matches books to 26AS/AIS; no published price | TRINETRA joins the invoice, the bank receipt, the customer's advice and the statement, with reviewed decisions | It is switched off; its statement readers are unproven on real files; CAs already own TDS software | "My CA's software does 26AS." TRINETRA is for the business that wants its own receivable TDS chased, not for filing |

**What this says.** Servabo is not cheaper than any single tool above. It is sold as **one place that finds and recovers money across
GST credit, overcharges, duplicates and payment timing**, sitting on top of Tally or Zoho. That claim is believable only with numbers
from the buyer's own invoices.

## 3. What is proven and what is not

**Proven (in the build sandbox, by tests and CI):** the engineering. About 4,800 backend test functions and 119 browser spec files run on every change;
tenant isolation swept route by route; security reviews; GST matching, Helm and three-way matching tested against stand-ins and a sample
company; money in exact integer micros; CI green on `main` (run #482).

**Not proven, and what closes each:**

| Gap | Why it matters to a buyer | What closes it |
| --- | --- | --- |
| **Accuracy on real Indian invoices** (fields right, documents fully right, what the review queue catches) | The first question any buyer asks | `scripts/accuracy_report.py` (Phase 5) on 30 to 50 of the owner's real invoices with a filled truth sheet: Final session 2B |
| **Real OCR (PaddleOCR) on scans and phone photos** | Most supplier invoices arrive as scans | Final session 2B, Phase 3 |
| **Any real outside integration**: Dodo payments in rupees, Postmark email-in, Zoho Books, Tally import, a real GSTR-2B and e-invoice QR | A pilot needs at least the GSTR-2B and one of Tally or Zoho to work for real | Final session 2B (the hand-over table in HANDOFF) |
| **Any customer** | Nobody buys the first of anything without a reference | Two or three paid 30-day pilots (`PILOT-PLAYBOOK.md`) |
| **Time saved** | "Hours saved" sells AP tools | Measured in the pilot: invoice received → entered, before and after |
| **Rupees found, and rupees recovered** | The whole pitch | The value receipt shows found and, with Recoveries (built, `RECOVERIES.md`), "Recovered, verified" beside it, line by line on the Recoveries page; the pilot measures both |
| **Whether Dodo's invoice carries the buyer's GSTIN with CGST/SGST/IGST** | A business cannot claim the 18% GST on Servabo's own invoice without it | Final session 2B buys once in rupees with a GSTIN (Dodo's docs say the tax ID is printed on B2B invoices; the split is **not documented**) |
| **Production deployment and backups on a real server** | A customer's data must survive | The owner launch checklist, steps 6 to 10, and the rehearsal in Final session 2B |

## 4. The money model

**The prices (N-187; GST extra, charged by Dodo as merchant of record):**

| Per user | Free trial | Starter | Business | Enterprise |
| --- | --- | --- | --- | --- |
| India, monthly | ₹0 for 14 days | ₹1,499 | ₹4,999 | ₹14,999 |
| India, yearly | — | ₹14,990 | ₹49,990 | by agreement |
| International, monthly | $0 for 14 days | $49 | $299 | $799 |
| International, yearly | — | $490 | $2,990 | by agreement |
| GST Credit add-on (per organization) | — | ₹1,499 a month / ₹14,990 a year ($49 / $490) | included | included |

**What a typical customer pays in a year** (before GST):

| Customer | Plan | A year |
| --- | --- | --- |
| A small distributor, 2 users, monthly | Starter + GST Credit add-on | 2 × ₹1,499 × 12 + ₹1,499 × 12 = **₹53,964** |
| A distributor, 3 users, yearly | Business | 3 × ₹49,990 = **₹1,49,970** |
| A manufacturer, 5 users, monthly | Business | 5 × ₹4,999 × 12 = **₹2,99,940** |

**What it costs to serve them** (COSTS.md §5, `test_plan_unit_economics.py`): a Business user at a fifth of every allowance costs about
$3.60 a month in OCR, model tokens and storage (about ₹325), plus Dodo's fee (4.5% + 15 cents a payment). Even a user at every ceiling
leaves at least 57% of the lowest price (Business yearly in rupees). The server and the fixed services cost roughly **$30 to $120 a month**
before the first customer (COSTS.md §1 and §2), about ₹2,700 to ₹10,800.

**How many customers cover the fixed costs.** One 3-user Business customer on monthly billing (₹14,997 a month, about ₹13,000 after
model costs and Dodo's fee) covers the server and services. About **four** 2-user Starter customers do the same. To pay the owner
₹1 lakh a month on top, Servabo needs roughly **eight 3-user Business customers or about forty 2-user Starter ones**. These figures leave
out the owner's time, a lawyer, an accountant and marketing.

## 5. Three risks a careful investor would name

1. **"It has never been used by a customer."** No pilot, no measured accuracy, no reference. *What reduces it:* the accuracy report
   on real invoices (Final 2B), then two or three paid pilots introduced by CA firms, each ending with a one-page case study in rupees
   (`PILOT-PLAYBOOK.md`).
2. **"One founder, too many engines."** GST Credit, Helm, three-way matching, the radar, TruthMesh, obligations, clause assertions,
   TRINETRA and more, each needing support. *What reduces it:* the owner's decision N-186 (no new engines before the first pilots); sell
   one outcome (money leaking out of supplier invoices) and treat the rest as depth; the safety jobs that alert on their own (Phase 2);
   the prompt-injection map that answers the first security question (Phase 3).
3. **"Cheaper tools already do the Indian part."** Tally, Zoho, Clear and Suvit are known to every CA. *What reduces it:* do not compete
   with the books; sit on top of Tally and Zoho; sell the money found and recovered, measured on the buyer's own invoices; reach buyers
   through CA firms, for whom one tool across many clients is worth most.

## 6. Where TRINETRA fits

**Who would pay for it:** a distributor or manufacturer whose large customers withhold TDS when they pay (for example under section
194Q on purchases of goods), and who must check that each customer actually deposited it and that it shows in Form 26AS / AIS before the
credit is claimed. Today they do this in spreadsheets, or not at all.

**What it does today:** a reviewed, **transcribed** comparison: invoice → bank receipt → the customer's advice → the government statement
the user uploads and types in → a reasoned resolution, with an owner, a due date and an accountant's review. It is switched off
(`TRINETRA_LIVE_ENABLED=false`); customers see a synthetic preview.

**The order before it is sold:**
1. **Final session 2T** finishes it for Business and Enterprise (statement readers, the full money model, pilot mode, every integration).
2. **Final session 2B** proves the statement readers on the owner's own Form 26AS / AIS files.
3. **The owner's CA** reads the wording and the examples (about an hour).
4. The owner switches it on for Business and Enterprise.

It is included in Business and Enterprise at the new prices; it is not sold on its own.
