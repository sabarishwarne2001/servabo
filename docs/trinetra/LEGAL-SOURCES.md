# Tax-source verification record

## Official sources accessed on 25 October 2026

The initial attempt on 24 October returned managed-proxy CONNECT 403. After the
cloud network configuration took effect, all three official pages below returned
HTTP 200. Their HTML and extracted text were inspected locally. The earlier
network blocker is resolved; source-layout and professional validation remain open.

| Source | Verified content and implementation boundary |
|---|---|
| [CBDT commencement announcement](https://www.incometaxindia.gov.in/w/income-tax-act-2025-comes-into-force-from-1st-april-2026) | Announcement dated 1 April 2026: the Income-tax Act, 2025 comes into force on that date. |
| [e-Filing TDS compliance FAQs](https://www.incometax.gov.in/iec/foportal/help/all-topics/e-filing-services/tds-compliance) | Questions 1–6 distinguish the earlier credit/payment event, including March credits paid in April and March advances booked in April. Question 2 gives historical 194C / new 393(1), Table 6(i), as an example; question 18 identifies TCS section 394. Questions 22–25 distinguish AY 2026–27 for FY 2025–26 from Tax Year 2026–27, including AIS/Form 168. These are source references, not a rate or eligibility engine. |
| [CBDT annual statement download instructions](https://www.incometaxindia.gov.in/tax-services/process-annual-tax-statement-traces-form-26as-form-168) | Separate instructions for historical assessment-year selection and tax-year selection from 2026–27; PDF, Excel and text downloads are listed. The page does not specify the column layouts, row semantics or reversal rules needed for a reliable parser. |

The calendar-label helper distinguishes historical FY/AY from Tax Year 2026–27.
It does not determine the applicable Act from invoice or deposit date. The initial
reviewed-invoice workflow requires the selected period to contain the source invoice
date and refuses earlier-advance/other-trigger cases; that is a supported-workflow
restriction, not a statement that invoice date legally determines withholding.
No statutory rate, taxable basis, automatic section translation, payroll, TCS or
claim eligibility is computed. No absent row is called evasion.

## Formats and remaining validation

`human-transcription-v1` records an authorized person's review of a canonical
uploaded document. It is not a Form 26AS parser or a statement that Servabo fetched
records from government. Official CSV/XLSX/TXT/PDF layouts remain unsupported:
representative, legally usable historical/current exports have not been supplied.
A download-help page alone cannot validate their structure. All evidence intake
uses the existing Documents service; ambiguous official files are explicitly refused.

Before live release, obtain authorized representative exports for each claimed
layout/year, add provenance-backed parser fixtures, and obtain tax-adviser approval
of event dates, labels, synthetic examples and outcome wording. `TRINETRA_LIVE_ENABLED`
remains false until those gates and the authorized pilot are completed.
Never collect portal passwords, defeat CAPTCHA, scrape authenticated portals,
invent a government API, file returns or recommend which credit to claim.
