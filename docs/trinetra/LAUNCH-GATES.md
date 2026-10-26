# TRINETRA launch gates

**Release status: gated implementation; not approved for live tax processing.**
`TRINETRA_LIVE_ENABLED=false` is the default in code, examples and production compose.
Do not enable it merely because synthetic tests pass.

## External evidence still required

- Authoritative commencement, transition and download guidance was reached and
  reviewed on 25 October 2026. See [LEGAL-SOURCES.md](LEGAL-SOURCES.md). This does
  not establish the structure or meaning of any particular exported file.
- Obtain authorized, legally usable historical/current statement exports. Validate
  every supported layout and ambiguous-column rule. No official parser is shipped
  as supported; human transcription must not be marketed as one.
- Have a tax adviser review transition/event dates, period labels, sample examples,
  section references and the wording of all financial conclusions. The current
  examples assert no rate or eligibility rule.
- Run an authorized customer pilot with reconciled invoice, bank, advice, accounting
  and statement evidence. Confirm data residency, retention and legal holds with the
  customer's owner and accountant. Do not use live data in this development environment.

## Product acceptance still open

These are limitations, not external verification already completed:

- Automatic ERP-derived expectations and verified official CSV/XLSX/TXT/PDF parsers.
- Full treatment of credit notes, reversals and advances; current unsupported signed
  amounts are refused for allocation and require accountant review.
- Pilot validation of the reviewed Helm annotation and reminder hold. Confirmed
  withholding is shown separately from cash; commercial totals are not silently
  netted and no bank settlement is rewritten. Unsupported signed adjustments stay gated.
- Production-ready multi-stage approval policy and an authorized inquiry-send path.
  Current drafts send nothing and consume no outbound-inquiry quota.
- Real-source validation of later gap-closure metrics and self-reported review time.
  Synthetic tests prove the comparison rules; no customer savings, recovery, refund
  or time-saving claim has been established.
- Pilot validation of document source comparison, source selection at scale, and
  the complete role/plan matrix in a browser.

## Deployment checklist after acceptance

1. Back up and restore-test the database; retain an evidence export for rollback.
2. Apply `alembic upgrade head`; confirm exactly one head and no new migration drift.
3. Publish additive tier versions through the existing publisher. Run the plan seed's
   dry-run/help first; inspect the generated delta. Existing subscriptions pin their
   versions: use the established reviewed carry-forward procedure. Do not rewrite
   subscription prices or invent payment product IDs.
4. Verify Business grants `capability.trinetra`, Enterprise also grants
   `capability.trinetra_all_workspaces`, and the agreed capacities are present.
5. Retain valid platform encryption keys and test rotation. JWT rotation is unrelated
   to the per-profile identity salt. Restart API and LIGHT workers on the same revision.
6. Keep `TRINETRA_LIVE_ENABLED=false` until the above evidence is approved, then enable
   only for the authorized deployment/pilot. Confirm sample workspaces remain immutable.
7. Review job failures in the existing jobs console and scoped run-status API. Check
   stale-source banners, export audit events and compliance export/erasure in staging.
8. Before rollback, export history; `tr1a2_review_outcomes` adds comparison/time/source
   links and `tr1a1_credit_assurance` adds the tables, key scope and webhook vocabulary.
   Downgrading both removes TRINETRA data and its key/webhook subscriptions. Disable
   the flag first. Existing recorded withholding continues to hold gross reminders
   while its rows remain, even after a flag disable or plan downgrade.

No production deployment, provider product creation, real email, government filing
or payment was performed during implementation. Validation evidence belongs in
[TEST-PLAN.md](TEST-PLAN.md), including failures and untested items.
