# TRINETRA launch gates

**Release status: gated implementation; not approved for live tax processing.**
`TRINETRA_LIVE_ENABLED=false` is the default in code, examples and production compose.
Do not enable it merely because synthetic tests pass.

## External evidence still required

- Reach and archive current authoritative ITD/CBDT/TRACES guidance, with access dates.
  Managed network requests returned CONNECT 403; the saved network draft is not an
  applied runtime policy. See [LEGAL-SOURCES.md](LEGAL-SOURCES.md).
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
- Reviewed net-of-TDS integration with Helm receivable projections. Existing cash and
  settlement semantics are unchanged; no claim is made that Helm now nets withholding.
- Production-ready multi-stage approval policy and an authorized inquiry-send path.
  Current drafts send nothing and consume no outbound-inquiry quota.
- Verified later credit-gap closure and measured reviewer-time outcomes. Headline
  exposure is not savings, recovery, a refund or an automatically bookable asset.
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
8. Before rollback, export history; downgrade drops the new evidence tables and removes
   `trinetra:read` from keys. Disabling the flag is the first rollback step.

No production deployment, provider product creation, real email, government filing
or payment was performed during implementation. Validation evidence belongs in
[TEST-PLAN.md](TEST-PLAN.md), including failures and untested items.
