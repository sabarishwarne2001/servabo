"""TRINETRA's case events as automation triggers and Enterprise webhooks (Final 2T, Phase 7.6 and 7.7): once per case revision, only
when someone listens, no PAN or TAN anywhere, and a rule on them can never send an inquiry."""

import uuid
from contextlib import contextmanager

import pytest

from app.models.automation import AutomationRule
from app.models.automation_trigger import AutomationRuleTrigger
from app.models.outbox_event import OutboxEvent
from app.models.webhook_endpoint import WebhookEndpoint
from app.services.automation import triggers
from app.workers.handlers import trinetra as handler
from tests.security.plans import put_on_plan
from tests.trinetra.test_api import really_change, world  # noqa: F401
from tests.trinetra.test_money_model import allocate, decide, get, statement
from tests.trinetra.test_workflows import setup_case

GAP = "trinetra.case.gap_found"
STALE = "trinetra.case.evidence_stale"
CLOSED = "trinetra.case.closed"
OTHER = "ZZZZ99999Z,5000.00,x1,194C,15-Jun-2025,F,FY 2025-26 / AY 2026-27"


def listen(db, tenant, *events):
    rule = AutomationRule(name="TDS rule", event="DOCUMENT_UPLOADED", workspace_id=tenant.workspace.id)
    db.add(rule)
    db.flush()
    for event in events:
        db.add(AutomationRuleTrigger(rule_id=rule.id, event_type=f"trigger.{event}", workspace_id=tenant.workspace.id))
    db.commit()


def subscribe(db, tenant, *events):
    db.add(WebhookEndpoint(organization_id=tenant.organization.id, url="https://example.invalid/synthetic-test",
                           event_types=list(events), secret_encrypted="synthetic-unused"))
    db.commit()


def outbox(db, tenant, name):
    return db.query(OutboxEvent).filter(OutboxEvent.organization_id == tenant.organization.id, OutboxEvent.event_type == name).all()


@pytest.fixture()
def recompute(db_session, tenant, monkeypatch):
    @contextmanager
    def session():
        yield db_session

    monkeypatch.setattr(handler, "SessionLocal", session)
    payload = {"organization_id": str(tenant.organization.id), "workspace_id": str(tenant.workspace.id)}
    return lambda: handler.handle_recompute(payload)


def test_a_gap_is_announced_to_a_listening_rule_once_with_no_tax_identifier(client, tenant, world, db_session, recompute):
    url, body, case = setup_case(client, tenant, world, reference="TR-EVT-1")
    statement(client, tenant, url, body, [OTHER])
    recompute()
    assert outbox(db_session, tenant, f"trigger.{GAP}") == []                      # nobody listens: no event, no cost
    listen(db_session, tenant, GAP)
    for _ in range(3):
        recompute()
    [event] = outbox(db_session, tenant, f"trigger.{GAP}")
    payload = event.payload
    assert payload["case_id"] == case["id"] and payload["work_item_id"] == str(world[1].id) and payload["amount_micros"] == 2_000_000_000
    assert payload["reference"] == "TR-EVT-1" and payload["currency"] == "INR" and payload["status"] == "POSSIBLE_MISSING_POSTING"
    assert "ABCDE1234F" not in str(payload) and "ABCD12345E" not in str(payload)


def test_a_confirmation_that_lost_its_evidence_is_announced_once_per_revision(client, tenant, world, db_session, recompute):
    url, body, case = setup_case(client, tenant, world, reference="TR-EVT-2")
    listen(db_session, tenant, STALE)
    recompute()
    assert outbox(db_session, tenant, f"trigger.{STALE}") == []
    really_change(db_session, world[1])
    recompute()
    recompute()
    [event] = outbox(db_session, tenant, f"trigger.{STALE}")
    assert event.payload["amount_micros"] == 2_000_000_000 and event.payload["revision"] == case["revision"]


def test_a_closure_is_announced_when_a_person_closes_the_case(client, tenant, world, db_session):
    url, body, case = setup_case(client, tenant, world, reference="TR-EVT-3")
    listen(db_session, tenant, CLOSED)
    assert decide(client, tenant, url, case, "WITHDRAWN", reason="This invoice was cancelled by the customer.").status_code == 200
    [event] = outbox(db_session, tenant, f"trigger.{CLOSED}")
    assert event.payload["state"] == "WITHDRAWN" and event.payload["reference"] == "TR-EVT-3" and event.payload["days_open"] == 0


def test_a_decision_that_does_not_close_the_case_announces_no_closure(client, tenant, world, db_session):
    url, body, case = setup_case(client, tenant, world, reference="TR-EVT-4")
    listen(db_session, tenant, CLOSED)
    noted = decide(client, tenant, url, case, "ANNOTATE", reason="A note for the file.", note="Called the customer's accounts team.",
                   snapshot_id=None, line_id=None)
    assert noted.status_code in (200, 422)
    assert outbox(db_session, tenant, f"trigger.{CLOSED}") == []


def test_public_webhooks_are_enterprise_only_and_carry_no_name_reference_or_identifier(client, tenant, world, db_session, recompute):
    url, body, case = setup_case(client, tenant, world, reference="TR-EVT-5")
    subscribe(db_session, tenant, GAP, CLOSED)
    statement(client, tenant, url, body, [OTHER])
    recompute()
    assert outbox(db_session, tenant, GAP) == []                                    # Business: the webhook is an Enterprise feature
    put_on_plan(db_session, tenant.organization, "enterprise")
    db_session.commit()
    recompute()
    recompute()
    [event] = outbox(db_session, tenant, GAP)
    assert event.payload == {"workspace_id": str(tenant.workspace.id), "case_id": case["id"], "revision": case["revision"], "year": 2025,
                             "state": "OPEN", "status": "POSSIBLE_MISSING_POSTING", "amount_micros": 2_000_000_000, "currency": "INR"}
    assert "TR-EVT-5" not in str(event.payload) and "Synthetic" not in str(event.payload)
    decide(client, tenant, url, get(client, tenant, url, case), "UNRESOLVED", reason="The customer never answered after two requests.")
    [closed] = outbox(db_session, tenant, CLOSED)
    assert closed.payload["state"] == "UNRESOLVED" and "reference" not in closed.payload and "customer" not in closed.payload


def test_a_rule_on_a_tds_event_can_never_send_an_inquiry_an_email_or_a_webhook():
    for key in (GAP, STALE, CLOSED):
        allowed = triggers.allowed_actions_for([key])
        assert allowed == {"notify.role", "chat.post", "review.assign", "document.tag"}, (key, allowed)
        assert "email.send" not in allowed and "webhook.send" not in allowed and "supplier.request_document" not in allowed


def test_the_events_are_in_the_catalogue_with_a_recipe_each_and_the_vocabularies_agree():
    from app.core.automation_events import INTERNAL_EVENT_TYPES
    from app.core.webhook_events import WEBHOOK_EVENT_TYPES
    from app.services.automation import recipes

    for key in (GAP, STALE, CLOSED):
        assert key in triggers.TRIGGERS_BY_KEY and f"trigger.{key}" in INTERNAL_EVENT_TYPES
    assert {GAP, CLOSED, "trinetra.case.reviewed"} <= WEBHOOK_EVENT_TYPES and STALE not in WEBHOOK_EVENT_TYPES
    assert {"tds-gap-assign", "tds-evidence-tell"} <= {r["id"] for r in recipes.RECIPES}
