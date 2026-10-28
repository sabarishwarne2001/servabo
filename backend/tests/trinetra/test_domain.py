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
