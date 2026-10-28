"""Existing TRINETRA rows move from updated_at stamps to content fingerprints, and back (Final 2T, Phase 1.2)."""

import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tests.trinetra.test_api import world  # noqa: F401
from tests.trinetra.test_helm_adapter import confirmed_case
from tests.trinetra.test_workflows import import_and_allocate
from app.models.trinetra import TrinetraCredit, TrinetraStatement
from app.services.trinetra import versions


def migration():
    path = Path(__file__).parents[2] / "alembic" / "versions" / "tr2t1_evidence_fingerprints.py"
    spec = importlib.util.spec_from_file_location("tr2t1", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def legacy(db, credit, statement, docs):
    """Rewrite the rows as the code before Final 2T stored them."""
    mod = migration()
    db.flush()
    rows = mod._load(db.connection(), {str(i.id) for i in docs})
    credit.source_version = mod._legacy_invoice(rows[str(credit.work_item_id)])
    review = dict(credit.review or {})
    review["invoice_version"] = credit.source_version
    review["evidence"] = [
        {**e, "source_version": rows[e["work_item_id"]].updated_at.isoformat()} for e in review.get("evidence", [])
    ]
    credit.review = review
    statement.source_version = rows[str(statement.source_work_item_id)].updated_at.isoformat()
    db.commit()


def test_current_stamps_become_fingerprints_and_stale_ones_stay_stale(client, tenant, world, db_session):
    import_and_allocate(client, tenant, world)
    credit = db_session.query(TrinetraCredit).one()
    statement = db_session.query(TrinetraStatement).one()
    legacy(db_session, credit, statement, [world[1], world[2]])
    assert not credit.source_version.startswith("v2:")
    mod = migration()
    assert mod.convert(db_session.connection()) == 2
    db_session.expire_all()
    credit, statement = db_session.query(TrinetraCredit).one(), db_session.query(TrinetraStatement).one()
    assert credit.source_version == versions.one(db_session, tenant.workspace.id, world[1].id).invoice
    assert statement.source_version == versions.one(db_session, tenant.workspace.id, world[2].id).statement
    assert credit.review["invoice_version"] == credit.source_version
    # Run again: nothing left to convert.
    assert mod.convert(db_session.connection()) == 0

    # A stamp that was already stale before the migration stays stale; it is never silently blessed.
    legacy(db_session, credit, statement, [world[1], world[2]])
    world[1].updated_at = datetime.now(timezone.utc) + timedelta(seconds=30)
    db_session.commit()
    mod.convert(db_session.connection())
    db_session.expire_all()
    assert db_session.query(TrinetraCredit).one().source_version == versions.STALE
    assert db_session.query(TrinetraStatement).one().source_version.startswith("v2:")


def test_evidence_stamps_and_the_downgrade_round_trip(client, tenant, world, db_session):
    confirmed_case(client, tenant, world)
    credit = db_session.query(TrinetraCredit).one()
    # `confirmed_case` has no statement; give the downgrade something to do on a statement too.
    mod = migration()
    kept = json.loads(json.dumps(credit.review))
    assert all(e["source_version"].startswith("v2:") for e in kept["evidence"])
    mod.revert(db_session.connection())
    db_session.expire_all()
    credit = db_session.query(TrinetraCredit).one()
    assert not credit.source_version.startswith("v2:")
    assert all(not e["source_version"].startswith("v2:") for e in credit.review["evidence"])
    mod.convert(db_session.connection())
    db_session.expire_all()
    credit = db_session.query(TrinetraCredit).one()
    assert credit.review["evidence"] == kept["evidence"] and credit.review["invoice_version"] == credit.source_version
