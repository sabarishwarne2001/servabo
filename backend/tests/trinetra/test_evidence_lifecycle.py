"""Derived copies must follow erasure/retention of every supporting source."""

import pytest
from tests.trinetra.test_api import world  # noqa: F401
from tests.trinetra.test_helm_adapter import confirmed_case
from tests.trinetra.test_outcomes import run_comparison
from app.services.compliance.document_content import destroy_copies
from app.models.trinetra import TrinetraCredit, TrinetraDecision, TrinetraStatement


@pytest.mark.parametrize("mode", ["erase", "purge"])
def test_supporting_document_removes_case_and_copied_review_history(
    client, tenant, world, db_session, mode
):
    confirmed_case(client, tenant, world)
    destroy_copies(db_session, [world[2].id], mode=mode)
    db_session.flush()
    assert db_session.query(TrinetraCredit).count() == 0
    assert db_session.query(TrinetraDecision).count() == 0


@pytest.mark.parametrize("mode", ["erase", "purge"])
def test_comparison_baseline_does_not_outlive_its_invoice(
    client, tenant, world, db_session, mode
):
    run_comparison(client, tenant, world, before="1000", after="2000")
    destroy_copies(db_session, [world[1].id], mode=mode)
    db_session.flush()
    # The original independent statement can remain; its derived comparison cannot.
    assert not any(s.comparison for s in db_session.query(TrinetraStatement))
