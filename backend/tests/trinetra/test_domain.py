from datetime import date

import pytest

from app.services.trinetra.domain import (
    Allocation,
    Credit,
    Posting,
    Scope,
    allocate,
    money,
    reconcile,
    tax_period,
)

pytestmark = pytest.mark.no_db
S = Scope("org", "workspace", "entity", 2025)


def credit(id="invoice", amount=2000000000, **kwargs):
    return Credit(id, S, "deductor", amount, "source", **kwargs)


def posting(id="line", amount=2000000000, **kwargs):
    return Posting(id, S, "deductor", amount, "snapshot", **kwargs)


def test_year_boundary_and_historical_labels():
    assert tax_period(date(2026, 3, 31)) == (2025, "FY 2025–26 / AY 2026–27")
    assert tax_period(date(2026, 4, 1)) == (2026, "Tax year 2026–27")


@pytest.mark.parametrize(
    "raw", ["NaN", "Infinity", "1e9", "1,23", "-1", "0.001", 1.2, True]
)
def test_invalid_money_is_never_guessed(raw):
    with pytest.raises(ValueError):
        money(raw)


def test_money_preserves_paise_without_float():
    assert money("123456.78") == 123456780000


def test_no_statement_or_expectation_is_unknown_not_missing_credit():
    assert (
        reconcile(credit(), [], [], statement_available=False)["status"]
        == "PENDING_REPORT"
    )
    assert (
        reconcile(credit(amount=None), [], [], statement_available=True)["gap_micros"]
        is None
    )


def test_exact_candidate_requires_review():
    r = reconcile(credit(), [posting()], [], statement_available=True)
    assert r["status"] == "SUGGESTED"
    assert r["posted_micros"] == 0


def test_grouped_and_split_allocations_conserve_statement_value():
    a, b = credit("a", 100), credit("b", 200)
    p, q = posting("p", 200), posting("q", 100)
    allocations = allocate(a, p, 100, [])
    allocations = allocate(b, p, 100, allocations)
    allocations = allocate(b, q, 100, allocations)
    assert (
        reconcile(b, [p, q], allocations, statement_available=True)["status"]
        == "POSTED"
    )
    with pytest.raises(ValueError, match="available"):
        allocate(credit("c", 1), p, 1, allocations)


@pytest.mark.parametrize(
    "scope",
    [
        Scope("other", "workspace", "entity", 2025),
        Scope("org", "other", "entity", 2025),
        Scope("org", "workspace", "other", 2025),
        Scope("org", "workspace", "entity", 2026),
    ],
)
def test_scope_cannot_be_crossed(scope):
    with pytest.raises(ValueError, match="scope"):
        allocate(credit(), Posting("p", scope, "deductor", 10, "snapshot"), 10, [])


def test_deductor_mismatch_and_disputed_credits_cannot_be_confirmed():
    with pytest.raises(ValueError):
        allocate(credit(), Posting("p", S, "other", 10, "snapshot"), 10, [])
    with pytest.raises(ValueError):
        allocate(credit(disputed=True), posting(), 10, [])


def test_superseded_snapshot_does_not_carry_old_allocations_forward():
    a = Allocation("invoice", "old", 100, "old-snapshot")
    r = reconcile(
        credit(amount=100), [posting("new", 100)], [a], statement_available=True
    )
    assert r["posted_micros"] == 0
    assert r["status"] == "SUGGESTED"


def test_duplicate_and_ambiguous_candidates_are_never_added():
    r = reconcile(credit(), [posting("a"), posting("b")], [], statement_available=True)
    assert r["status"] == "AMBIGUOUS"
    assert r["posted_micros"] == 0


def test_signed_reversals_require_explicit_review():
    with pytest.raises(ValueError):
        allocate(credit(), posting(amount=-100), 100, [])
    with pytest.raises(ValueError):
        allocate(credit(), posting(), -1, [])


def test_bank_shortfall_does_not_create_a_tax_basis():
    r = reconcile(
        credit(amount=None, gross_micros=118000000000, bank_micros=116000000000),
        [],
        [],
        statement_available=True,
    )
    assert r["expected_micros"] is None
    assert r["gap_micros"] is None
    assert r["status"] == "EVIDENCE_NEEDED"
def test_sample_aging_uses_its_displayed_evidence_date():
    from datetime import date, datetime
    from app.services.trinetra.sample import cockpit

    sample = cockpit()
    as_of = date.fromisoformat(sample["as_of"])
    for item in sample["items"]:
        created = datetime.fromisoformat(item["created_at"]).date()
        assert item["age_days"] == (as_of - created).days


# --- Final 2T, Phase 3: matching uses the section or table item as printed, and the transaction date, when present -------


def test_a_section_printed_on_both_sides_must_agree_as_printed():
    c = credit(section="194C")
    same = posting("a", section="194C ")
    other = posting("b", section="194Q")
    assert reconcile(c, [same], [], statement_available=True)["candidate_ids"] == ["a"]
    out = reconcile(c, [other], [], statement_available=True)
    assert out["candidate_ids"] == [] and out["status"] != "SUGGESTED"
    with pytest.raises(ValueError, match="section"):
        allocate(c, other, 2000000000, [])


def test_an_old_act_section_is_never_converted_into_a_new_act_table_item():
    c = credit(section="194Q")
    new_act = posting("n", section="393(1) [Sl. No. 8(ii)]")
    assert reconcile(c, [new_act], [], statement_available=True)["candidate_ids"] == []
    with pytest.raises(ValueError, match="never converts"):
        allocate(c, new_act, 2000000000, [])


def test_a_missing_section_on_either_side_does_not_block_a_match():
    assert reconcile(credit(), [posting("a", section="194C")], [], statement_available=True)["candidate_ids"] == ["a"]
    assert reconcile(credit(section="194C"), [posting("a")], [], statement_available=True)["candidate_ids"] == ["a"]


def test_a_posting_dated_in_another_tax_year_is_never_matched():
    inside = posting("in", on=date(2026, 3, 31))      # FY 2025-26: the credit's year (2025)
    outside = posting("out", on=date(2026, 4, 1))     # Tax Year 2026-27: another year
    out = reconcile(credit(), [outside], [], statement_available=True)
    assert out["candidate_ids"] == [] and out["status"] in ("POSSIBLE_MISSING_POSTING", "AMOUNT_MISMATCH")
    assert reconcile(credit(), [inside], [], statement_available=True)["candidate_ids"] == ["in"]
    with pytest.raises(ValueError, match="tax year"):
        allocate(credit(), outside, 2000000000, [])


# --- Final 2T, Phase 5: the statuses the brief names, and reject ------------------------------------------------------


def test_identical_candidate_rows_are_a_suspected_duplicate_not_just_ambiguous():
    twin = dict(section="194C", on=date(2025, 6, 15), booked_on=date(2025, 7, 30))
    out = reconcile(credit(), [posting("a", **twin), posting("b", **twin)], [], statement_available=True)
    assert out["status"] == "DUPLICATE_SUSPECTED" and sorted(out["candidate_ids"]) == ["a", "b"]
    # Rows that differ in what they print are merely ambiguous: a person chooses.
    other = reconcile(credit(), [posting("a", section="194C"), posting("b", section="194J")], [], statement_available=True)
    assert other["status"] == "AMBIGUOUS"


def test_a_posting_booked_after_its_year_is_a_late_posting():
    late = posting("late", on=date(2026, 2, 10), booked_on=date(2026, 5, 20))      # transaction in FY 2025-26, booked in Tax Year 2026-27
    on_time = posting("ok", on=date(2026, 2, 10), booked_on=date(2026, 3, 20))
    amount = 2000000000
    for line, status in ((late, "LATE_POSTING"), (on_time, "POSTED")):
        c = credit()
        allocation = [Allocation(c.id, line.id, amount, line.snapshot)]
        assert reconcile(c, [line], allocation, statement_available=True)["status"] == status


def test_a_correction_response_followed_by_a_later_posting_is_verified_corrected():
    c = credit(corrected=True)
    line = posting("p", on=date(2026, 2, 10), booked_on=date(2026, 3, 20))
    out = reconcile(c, [line], [Allocation(c.id, "p", 2000000000, "snapshot")], statement_available=True)
    assert out["status"] == "VERIFIED_CORRECTED"
    # Without a posting it is still a gap, whatever correction was requested.
    assert reconcile(credit(corrected=True), [], [], statement_available=True)["status"] == "POSSIBLE_MISSING_POSTING"


def test_a_rejected_candidate_is_not_offered_again_for_that_snapshot():
    out = reconcile(credit(rejected=frozenset({("snapshot", "a")})), [posting("a")], [], statement_available=True)
    assert out["candidate_ids"] == [] and out["status"] != "SUGGESTED"
    again = reconcile(credit(rejected=frozenset({("older-snapshot", "a")})), [posting("a")], [], statement_available=True)
    assert again["candidate_ids"] == ["a"]       # a rejection is for that snapshot only


def test_a_credit_note_that_drops_the_gross_below_the_expectation_makes_the_expectation_unsupported():
    c = credit(gross_micros=118_000_000_000, credit_notes_micros=117_999_000_000)       # gross left: 1,000,000 micros
    out = reconcile(c, [posting()], [], statement_available=True)
    assert out["status"] == "EVIDENCE_NEEDED" and out["adjusted_gross_micros"] == 1_000_000
    fine = reconcile(credit(gross_micros=118_000_000_000, credit_notes_micros=10_000_000_000), [posting()], [], statement_available=True)
    assert fine["adjusted_gross_micros"] == 108_000_000_000 and fine["status"] == "SUGGESTED"


def test_the_taxable_basis_is_a_dimension_only_when_sourced_and_is_never_computed():
    assert reconcile(credit(), [posting()], [], statement_available=True)["basis_micros"] is None
    sourced = reconcile(credit(basis_micros=100_000_000_000, basis_source="ACCOUNTING_RECORD"), [posting()], [], statement_available=True)
    assert sourced["basis_micros"] == 100_000_000_000 and sourced["basis_source"] == "ACCOUNTING_RECORD"
    # A bank shortfall or GST value never produces one.
    gap = reconcile(credit(gross_micros=118_000_000_000, bank_micros=116_000_000_000), [posting()], [], statement_available=True)
    assert gap["basis_micros"] is None
