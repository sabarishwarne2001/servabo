"""Field by field: why a statement row is, or is not, the case's match (Final 2T, Phase 8). Pure, plus the case detail's answer."""

from datetime import date

from app.services.trinetra import domain as d
from tests.trinetra.test_api import world  # noqa: F401
from tests.trinetra.test_money_model import allocate, decide, get, statement  # noqa: F401
from tests.trinetra.test_workflows import setup_case

SCOPE = d.Scope("o", "w", "e", 2025)
M = 1_000_000


def credit(**more):
    base = dict(id="c", scope=SCOPE, deductor="k", expected=2000 * M, source="invoice", reference="INV-1", section="194C")
    return d.Credit(**{**base, **more})


def posting(**more):
    base = dict(id="0", scope=SCOPE, deductor="k", amount=2000 * M, snapshot="s", reference="Q1", section="194C", on=date(2025, 6, 15))
    return d.Posting(**{**base, **more})


def by_key(checks):
    return {c["key"]: c for c in checks}


def test_every_key_that_agreed_says_so_with_the_values_as_printed():
    checks = by_key(d.explain(credit(), posting(reference="inv-1"), expected=2000 * M, available=2000 * M))
    assert [c["agrees"] for c in checks.values()] == [True] * len(checks)
    assert checks["section"]["case_value"] == "194C" and checks["section"]["statement_value"] == "194C"
    assert checks["amount"]["case_value"] == str(2000 * M) and checks["amount"]["statement_value"] == str(2000 * M)
    assert set(checks) == {"deductor", "entity_and_year", "section", "amount", "reference"}


def test_a_difference_names_the_key_and_a_missing_print_is_not_called_a_difference():
    checks = by_key(d.explain(credit(), posting(section="393 (1) table", on=date(2026, 6, 1), amount=1500 * M, deductor="other"),
                              expected=2000 * M, available=1500 * M))
    assert checks["deductor"]["agrees"] is False
    assert checks["section"]["agrees"] is False and "never converts" in checks["section"]["note"].lower()
    assert checks["entity_and_year"]["agrees"] is False and checks["amount"]["agrees"] is False
    quiet = by_key(d.explain(credit(section=None), posting(section=None), expected=2000 * M, available=2000 * M))
    assert quiet["section"]["agrees"] is None and "not printed" in quiet["section"]["note"].lower()


def test_the_case_detail_explains_each_candidate_and_allocated_row(client, tenant, world, db_session):
    url, body, case = setup_case(client, tenant, world)
    snap = statement(client, tenant, url, body, ["ABCD12345E,2000.00,Q4,194C,15-Jun-2025,F,FY 2025-26 / AY 2026-27"])
    detail = get(client, tenant, url, case)
    [one] = detail["match_explanations"]
    assert one["role"] == "candidate" and one["snapshot_id"] == snap and one["line_id"] == "0" and one["reader"]
    assert {c["key"] for c in one["checks"]} == {"deductor", "entity_and_year", "section", "amount", "reference"}
    assert all(c["agrees"] is not False for c in one["checks"] if c["key"] != "reference")     # a typed reference may differ
    done = decide(client, tenant, url, detail, "ALLOCATE", allocations=[allocate(snap, 0, "2000")])
    assert done.status_code == 200
    [after] = get(client, tenant, url, case)["match_explanations"]
    assert after["role"] == "allocated" and after["allocated_micros"] == "2000000000"
