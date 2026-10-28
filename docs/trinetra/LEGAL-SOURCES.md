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

## Statement readers: what each was written from (Final session 2T, accessed 2026-10-28)

**The official TRACES and e-filing hosts could not be reached from the build environment** this time (outside the session's
allowed network; the three pages above were reachable on 25 October only). So no official reader was written from, or checked
against, an official document or a real file. Each one is registered in `app/services/trinetra/readers.py` as **official and
unverified** (`verified_on` empty) and the screens label it "(unverified)".

| Reader | Written from | Status |
|---|---|---|
| `form26as-text-v1` (Form 26AS text download, FY/AY) | Secondary sources found by web search on 2026-10-28: a KDK Software support article on importing the Form 26AS text download, taxheal.com's text-to-Excel guide, tdsman.com's 2014 conversion guide. Checked only against **synthetic** fixtures of the same shape (`backend/tests/fixtures/trinetra/form26as_sample.txt`). | Unverified. Final 2B compares it with the owner's own download. |
| `form168-text-v1` (Form 168 text download, Tax Year) | The same sources, plus the assumption that Form 168's text follows Form 26AS's layout. The reader refuses any difference rather than guess. | Unverified. Same. |
| `ais-csv-v1` (AIS TDS/TCS information CSV) | Only the on-screen field names (information code, description, value, source), confirmed by web search; the AIS user guide and FAQ on incometax.gov.in could not be reached. Columns are found by **heading** and confirmed by the person in a mapping preview, so a different heading is a question, not a guess. TDS rows only (TCS rows are left out and counted). | Unverified. Same. |
| `servabo-template-v1` | Servabo's own template; not an official format. | Not official; no verification needed. |
| `human-transcription-v1` | Rows typed by a person from a statement they hold. | Not official. |

What the readers do not do: read PDF (TRACES password-protects it; the text and CSV downloads carry the same data), convert an old
section into a Section 393 table item or the reverse (each row keeps the label the file printed), mix a financial year with a tax
year (the file's own label is shown back and must match the year the person chose), or compute any rate, base or eligibility.

## Formats and remaining validation

`human-transcription-v1` and the Servabo template record an authorized person's review of a statement they hold; they are not a Form
26AS parser or a statement that Servabo fetched anything from government. The official readers above are unverified:
representative, legally usable historical and current exports have not been supplied, and a download-help page alone cannot validate
their structure. All evidence intake uses the existing Documents service or the file limits (5 MB, 5,000 rows); an ambiguous or
unrecognised file is refused in words.

Before live release for any customer, Final session 2B reads the owner's own Form 26AS / Form 168 text and AIS CSV on the owner's PC
(never in the repository or in a chat), records "Verified in 2B" or "Differs" for each COMPLETION row, and the owner's chartered
accountant approves event dates, labels, the examples and the wording of every financial conclusion. `TRINETRA_MODE` stays
`pilot` (enrolled organizations only) until then and the website says "rolling out".
Never collect portal passwords, defeat CAPTCHA, scrape authenticated portals, invent a government API, file returns or recommend
which credit to claim.
