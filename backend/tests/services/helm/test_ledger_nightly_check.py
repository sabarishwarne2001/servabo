"""The nightly rebuild is also the check on the incremental updates (Session B).

    pytest tests/services/helm/test_ledger_nightly_check.py -q

An incremental update trusts the marks that say which documents changed. A write that bypasses them (a
bulk database statement, a path nobody has marked) leaves a stored promise that a full recomputation
would not produce. The nightly job recomputes every workspace's ledger from scratch; this holds it to
doing so as a check, not only as a rebuild:

  * stored promises that differ from the recomputation (as of the day they were written for) are
    counted, repaired by the rebuild that follows, and reported to the operator through the existing
    operator alert, so someone looks for the path that missed the change
  * a ledger that is merely a day old (statuses move on without any document changing), or that is
    waiting for a full rebuild it was already asked for, is not reported: nothing was missed
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import delete, select, update

from app.models.document_role import DocumentRole
from app.models.helm import HelmBook, HelmLedgerState, HelmPromise, HelmSettings
from app.models.operator_alert import OperatorAlert
from app.models.work_item import WorkItem
from app.services.helm import ledger_store
from app.services.helm import vocabulary as v
from tests.engines.conftest import test_sessions  # noqa: F401  (fixture: the job opens its own sessions)
from tests.security.plans import put_on_plan
from tests.services.helm import factories
from tests.services.helm.test_ledger_incremental_equivalence import US, US_TAX, assert_equivalent, stored, recomputed

TODAY = date.today()


def _forget_alerts(db) -> None:
    """Operator alerts belong to no tenant, so the per-test clean-up does not remove them."""
    db.execute(delete(OperatorAlert).where(OperatorAlert.kind == "HELM_LEDGER_DRIFT"))
    db.commit()


@pytest.fixture()
def book(db_session, tenant, test_sessions):
    from app.workers.handlers import register_all

    _forget_alerts(db_session)

    register_all(replace=True)  # the nightly job queues a re-plan for each book
    put_on_plan(db_session, tenant.organization, "business")
    row = HelmBook(organization_id=tenant.organization.id, workspace_id=tenant.workspace.id, kind=v.BOOK_WORKSPACE,
                   name="Nightly", status=v.BOOK_ACTIVE)
    db_session.add(row)
    db_session.flush()
    db_session.add(HelmSettings(book_id=row.id, organization_id=tenant.organization.id,
                                identities=[{"name": US, "tax_id": US_TAX}], run_weekdays=[2, 5], horizon_days=30,
                                cost_of_capital_bps=1200, default_autonomy=v.AUTONOMY_PROPOSE, briefing_enabled=False,
                                first_run_step=4, preferences={}))
    db_session.flush()
    yield row
    db_session.rollback()
    _forget_alerts(db_session)


def _invoices(db, tenant, count: int = 4) -> list[WorkItem]:
    return [factories.invoice(db, workspace=tenant.workspace, organization_id=tenant.organization.id,
                              number=f"INV-{n:03d}", supplier=f"Supplier {n} Trading", amount=10_000 + n * 500,
                              buyer=US, on=TODAY - timedelta(days=10 + n)) for n in range(count)]


class _Nightly:
    def __init__(self, db, tenant) -> None:
        self.db, self.workspace_id = db, tenant.workspace.id

    def run(self) -> dict:
        from app.workers.handlers.helm import handle_ledger_build

        self.db.commit()
        result = handle_ledger_build({"full": True})
        self.db.expire_all()
        return result

    def alerts(self) -> list[OperatorAlert]:
        return list(self.db.execute(select(OperatorAlert).where(OperatorAlert.kind == "HELM_LEDGER_DRIFT")).scalars())

    def state(self) -> HelmLedgerState:
        return self.db.execute(select(HelmLedgerState).where(HelmLedgerState.workspace_id == self.workspace_id)
                               ).scalar_one()


def test_a_write_that_bypassed_the_marks_is_repaired_and_reported(db_session, tenant, book) -> None:
    db = db_session
    items = _invoices(db, tenant)
    ledger_store.rebuild_workspace(db, workspace_id=tenant.workspace.id, as_of=TODAY)
    db.commit()
    # A bulk statement: the ORM's events (and so the marks) never see it.
    changed = items[1]
    db.execute(update(DocumentRole).where(DocumentRole.work_item_id == changed.id).values(total_micros=99_000 * 10**6))
    db.commit()
    assert not ledger_store._claim_dirty(db, tenant.workspace.id)
    before = stored(db, tenant.workspace.id)

    nightly = _Nightly(db, tenant)
    assert nightly.run() == {"rebuilt": 1}

    # Repaired: the stored ledger is what a full recomputation says.
    assert stored(db, tenant.workspace.id) == recomputed(db, tenant.workspace.id, TODAY)
    assert stored(db, tenant.workspace.id) != before
    # Reported: through the operator alert, naming the workspace and how much differed.
    (alert,) = nightly.alerts()
    assert str(tenant.workspace.id) in alert.dedupe_key and str(tenant.workspace.id) in alert.subject
    assert "1 of 4" in alert.body and "rebuilt" in alert.body
    state = nightly.state()
    assert state.check_mismatches == 1 and state.checked_at is not None


def test_changes_the_marks_saw_are_not_drift(db_session, tenant, book) -> None:
    db = db_session
    items = _invoices(db, tenant)
    ledger_store.rebuild_workspace(db, workspace_id=tenant.workspace.id, as_of=TODAY)
    db.commit()
    # Through the ORM: marked, and not yet brought in by an update when the nightly job runs.
    role = db.execute(select(DocumentRole).where(DocumentRole.work_item_id == items[2].id)).scalar_one()
    role.total_micros = 77_000 * 10**6
    db.flush()
    assert ledger_store._claim_dirty(db, tenant.workspace.id)

    nightly = _Nightly(db, tenant)
    assert nightly.run() == {"rebuilt": 1}
    assert nightly.alerts() == []
    assert nightly.state().check_mismatches == 0 and nightly.state().checked_at is not None
    assert stored(db, tenant.workspace.id) == recomputed(db, tenant.workspace.id, TODAY)
    assert not ledger_store._claim_dirty(db, tenant.workspace.id)  # the rebuild included it


def test_a_ledger_that_is_a_day_old_is_not_drift(db_session, tenant, book) -> None:
    """Statuses move on with the calendar ("open" becomes "broken") without any document changing."""
    db = db_session
    _invoices(db, tenant)
    yesterday = TODAY - timedelta(days=1)
    ledger_store.rebuild_workspace(db, workspace_id=tenant.workspace.id, as_of=yesterday)
    # An invoice that fell due today is open in what was written yesterday and broken in tonight's.
    db.commit()
    nightly = _Nightly(db, tenant)
    assert nightly.run() == {"rebuilt": 1}
    assert nightly.alerts() == []
    assert nightly.state().as_of == TODAY
    assert stored(db, tenant.workspace.id) == recomputed(db, tenant.workspace.id, TODAY)


def test_a_ledger_already_waiting_for_a_full_rebuild_is_not_drift(db_session, tenant, book) -> None:
    db = db_session
    items = _invoices(db, tenant)
    ledger_store.rebuild_workspace(db, workspace_id=tenant.workspace.id, as_of=TODAY)
    ledger_store.request_full(db, workspace_id=tenant.workspace.id)  # "who we are" changed, say
    db.execute(update(DocumentRole).where(DocumentRole.work_item_id == items[0].id).values(total_micros=5_000 * 10**6))
    db.commit()
    nightly = _Nightly(db, tenant)
    assert nightly.run() == {"rebuilt": 1}
    assert nightly.alerts() == []  # stale on purpose: nothing was missed
    state = nightly.state()
    assert state.full_requests <= state.full_served
    assert stored(db, tenant.workspace.id) == recomputed(db, tenant.workspace.id, TODAY)


def test_the_first_nightly_build_has_nothing_to_compare_with(db_session, tenant, book) -> None:
    db = db_session
    _invoices(db, tenant)
    db.commit()
    nightly = _Nightly(db, tenant)
    assert nightly.run() == {"rebuilt": 1}
    assert nightly.alerts() == []
    assert db.execute(select(HelmPromise).where(HelmPromise.workspace_id == tenant.workspace.id)).first() is not None
