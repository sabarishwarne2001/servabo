"""Migration k1a6's downgrade with webhook delivery rows present (Final session 2A, Phase 4).

k1a6 added five public events (GST and automation) to the webhook vocabularies. Its downgrade deletes the deliveries
that carry them, deletes an endpoint that listened to nothing else (an endpoint must listen to at least one event) and
narrows the other endpoints' lists. Until now it was only ever run on empty tables. Here, with real rows:

  * an endpoint listening only to `gst.return.imported`, with a delivery of that event (and an attempt) and a
    "Send test event" ping: the endpoint and both deliveries go (attempts cascade);
  * an endpoint listening to `document.completed` and `automation.run.failed`, with one delivery of each: it stays,
    keeps `document.completed` and its delivery, and loses the other;

then upgrade to head again, and the kept rows are still there.
"""

from __future__ import annotations

import uuid

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text

from tests.conftest import TEST_DB_URL

BEFORE_K1A6 = "k1a5_erp_oauth_states"


def _endpoint(db, org, events: list[str]) -> uuid.UUID:
    eid = uuid.uuid4()
    db.execute(text("""
        INSERT INTO webhook_endpoints (id, organization_id, url, event_types, status, secret_encrypted, created_at, updated_at)
        VALUES (:id, :org, 'https://hooks.example.com/x', CAST(:events AS varchar[]), 'ACTIVE', 'enc', now(), now())"""),
        {"id": eid, "org": org, "events": "{" + ",".join(events) + "}"})
    return eid


def _delivery(db, org, endpoint: uuid.UUID, event: str) -> uuid.UUID:
    did = uuid.uuid4()
    db.execute(text("""
        INSERT INTO webhook_deliveries (id, webhook_endpoint_id, organization_id, event_type, payload, status, created_at, updated_at)
        VALUES (:id, :ep, :org, :event, '{}'::jsonb, 'PENDING', now(), now())"""),
        {"id": did, "ep": endpoint, "org": org, "event": event})
    return did


def test_k1a6_downgrade_and_upgrade_with_deliveries_present(db_session, tenant) -> None:
    org = tenant.organization.id
    only_gst = _endpoint(db_session, org, ["gst.return.imported"])
    gst_delivery = _delivery(db_session, org, only_gst, "gst.return.imported")
    ping = _delivery(db_session, org, only_gst, "webhook.test")
    db_session.execute(text("""
        INSERT INTO webhook_delivery_attempts (id, webhook_delivery_id, organization_id, attempt_number, request_url,
                                               request_headers, disposition, duration_ms, response_status, created_at, updated_at)
        VALUES (:id, :d, :org, 1, 'https://hooks.example.com/x', '{}'::jsonb, 'RETRY', 120, 503, now(), now())"""),
        {"id": uuid.uuid4(), "d": gst_delivery, "org": org})
    mixed = _endpoint(db_session, org, ["document.completed", "automation.run.failed"])
    kept = _delivery(db_session, org, mixed, "document.completed")
    dropped = _delivery(db_session, org, mixed, "automation.run.failed")
    db_session.commit()
    db_session.close()

    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", TEST_DB_URL)
    command.downgrade(config, BEFORE_K1A6)

    def ids(table: str) -> set[uuid.UUID]:
        return set(db_session.execute(text(f"SELECT id FROM {table}")).scalars())

    try:
        assert only_gst not in ids("webhook_endpoints") and mixed in ids("webhook_endpoints")
        assert {gst_delivery, ping, dropped}.isdisjoint(ids("webhook_deliveries")) and kept in ids("webhook_deliveries")
        assert db_session.execute(text("SELECT count(*) FROM webhook_delivery_attempts WHERE webhook_delivery_id = :d"),
                                  {"d": gst_delivery}).scalar_one() == 0
        events = db_session.execute(text("SELECT event_types FROM webhook_endpoints WHERE id = :i"), {"i": mixed}).scalar_one()
        assert list(events) == ["document.completed"]
        db_session.rollback()
    finally:
        command.upgrade(config, "head")
    assert db_session.execute(text("SELECT version_num FROM alembic_version")).scalar() == \
        ScriptDirectory.from_config(config).get_current_head()
    assert mixed in ids("webhook_endpoints") and kept in ids("webhook_deliveries")
