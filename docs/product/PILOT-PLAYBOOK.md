# Pilot playbook: a 30-day paid pilot with a distributor

**Who this is for:** you (the owner), running Servabo's first paid pilots. **The aim:** at the end of 30 days, two
numbers the customer agrees with: how accurate Servabo was on their own invoices, and how many rupees of GST credit it
protected. Those two numbers are the case study that sells the next ten customers.

The best pilot customer is a **distributor or trader with 200 to 2,000 purchase invoices a month**, introduced by their
**chartered accountant (CA)**. The CA trusts you, sees the GST results first-hand, and has other clients.

## 1. The offer

- **One month on Business, up to 3 seats, for ₹9,999 plus GST** (decision N-198; the list price for 3 seats is ₹14,997),
  paid in advance through the ordinary checkout and **credited in full against the first yearly plan** if they continue
  within 30 days. A paid pilot, even a small one, gets attention a free trial does not.
- **What they get:** their invoices read, GST credit checked against their GSTR-2B every month, Helm's payment plan and
  reminders, and a written result at day 30.
- **What you promise:** a measured accuracy figure on their own documents, and every rupee of credit at risk named with
  the invoice and the supplier. You do not promise a number in advance.
- **What they give:** the documents listed below, one person who answers questions, and 30 minutes a week.

## 2. Day 1: what to collect

| What | Why | How |
|---|---|---|
| One month of purchase invoices (PDF, scans or photos) | The accuracy test and the GST check | Upload a zip on the Documents page, or forward them to the workspace's email-in address |
| The GSTR-2B for the same month (JSON from the GST portal) | Credit at risk: what the books have and the portal does not | GST Credit page, Import |
| The supplier list with GSTINs | Contacts and reminders | Helm, Settings, Suppliers and customers. **Confirm each supplier's email address there**: Servabo never emails an address it only read from a document |
| The Tally or Zoho Books export for the month | To check Servabo's totals against their books | Keep it beside you; compare totals |
| A truth sheet for 30 to 50 invoices | The accuracy figure | `backend/scripts/accuracy_truth_template.csv`: one row per invoice, what it really says |

Fill the truth sheet **with** the customer's accountant: it takes about an hour for 50 invoices and it is the evidence.

## 3. What to measure

| Measure | How | When |
|---|---|---|
| **Accuracy** | `python scripts/accuracy_report.py --workspace <id> --truth truth.csv --out accuracy.md`, run after processing and **before** anyone corrects fields | Day 3 |
| **Time from invoice received to entered** | Their old way (ask them) against the time on Servabo's document list | Day 7 and day 30 |
| **Rupees found** | GST Credit: credit at risk (not in GSTR-2B, amount differences, the 180-day rule), with each invoice | Day 7 and day 30 |
| **Rupees recovered, verified** | The Recoveries page (Documents → Recoveries): each issue closed by evidence, with what it proved; "Found" beside it, never added | Day 7 and day 30 |
| **The review queue** | How many documents waited for a person, and why | Weekly |

## 4. The weekly check-in (30 minutes)

1. What Servabo found this week: the GST credit at risk and the suppliers to chase.
2. What went wrong: every document in review and every field someone corrected. Fix the cause the same week.
3. One question for them: what did they do with what Servabo found?
4. Write three lines in a shared note: found, fixed, next.

## 5. What success means, in numbers

The pilot is a success when, at day 30, all of these are true:

- **At least 95% of key fields right** on their truth sheet (invoice number, date, supplier GSTIN, taxable value, total),
  and at least 80% of the wrong fields were sent to review rather than passed through.
- **Credit at risk named** with invoice and supplier for every rupee, and the customer agrees with the list.
- **Time to enter an invoice** at least halved.
- **They want to continue at the list price** (₹4,999 per seat a month for Business, or yearly).

If accuracy is below 95%, say so plainly, show the misses from the report, and say what will change. Never round up.

## 6. The case study (one page)

Ask permission first, in writing. Then:

- **The customer:** what they distribute, how many invoices a month, who introduced them.
- **Before:** how invoices were entered and how GST credit was checked.
- **The numbers:** "98% of fields right on 120 real invoices, measured", "₹3.2 lakh of GST credit protected in 30 days",
  "invoice entry from 2 days to 2 hours". Only numbers from the report and the GST page.
- **A quote** from the owner or their CA.
- **How it was measured:** the truth sheet, the report, the dates.

## 7. After the pilot

- **They continue:** offer the yearly plan. A monthly charge above ₹15,000 (with GST) needs the payer's approval every
  month under the RBI's e-mandate rule; a yearly plan is one payment a year, approved once.
- **They stop:** ask why, write it in the pilot notes, and fix what you can before the next pilot.
- **Either way:** ask the CA for two more introductions. A CA who introduces a pilot gets a free Starter seat for as long as
  the customer stays, never a fee (N-198).
