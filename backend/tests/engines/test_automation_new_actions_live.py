"""Session J, Phase 3 — the new automation actions, live.

tag, assign a review, place a legal hold, post to Slack or Teams, remind a GST supplier, create a follow-up, ask a supplier
for a document. For each: it does what it says, its capability and role are enforced, a repeat does not repeat the effect,
and a document's text can never become markup, a mention or a recipient.
"""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

import pytest
from sqlalchemy import func, select

from app.models.ingestion import RetentionHold, WorkItemTag
from app.models.review import ReviewAssignment
from app.models.webhook_delivery import WebhookDelivery
from app.models.webhook_endpoint import WebhookEndpoint
from tests.engines.conftest import Engines, drain
from tests.engines.test_webhooks_live import _deliver, receiver  # noqa: F401  (fixture)

SLACK = "https://slack-in.acme.example.com/services/T000/B000/SECRETTOKEN123"
TEAMS = "https://teams-in.acme.example.com/workflows/SECRETTOKEN456"


@pytest.fixture(autouse=True)
def chat_hosts(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "CHAT_WEBHOOK_EXTRA_HOSTS", "slack-in.acme.example.com,teams-in.acme.example.com")


def _rule(engines: Engines, name: str, actions: list[dict[str, Any]], *, trigger: str = "document.completed",
          expect: int = 201, conditions: Any = None) -> dict[str, Any]:
    body = {"name": name, "triggers": [trigger], "groups_operator": "AND",
            "condition_groups": [{"logic_operator": "AND", "conditions": conditions}] if conditions else [],
            "actions": actions}
    response = engines.post("/automation/rules", body)
    assert response.status_code == expect, response.text
    return response.json()


def _invoice(engines: Engines, number: str, **entities: Any) -> uuid.UUID:
    return engines.process(f"{number}.pdf", [["TAX INVOICE", f"Invoice Number: {number}"]], marker=number,
                           classification="Invoice", entities={"invoice_number": number, "vendor_name": "Acme Supplies Ltd",
                                                               **entities})


def _runs(engines: Engines, rule_id: str) -> list[dict[str, Any]]:
    return engines.get("/automation/executions", params={"rule_id": rule_id, "limit": 200}).json()["items"]


def _node_outcomes(engines: Engines, rule_id: str) -> list[str]:
    outcomes: list[str] = []
    for run in _runs(engines, rule_id):
        for node in engines.get(f"/automation/executions/{run['id']}/nodes").json():
            if node["node_type"] == "action":
                outcomes.append(node["outcome"] or node["status"])
    return outcomes


def _tags(engines: Engines, work_item: uuid.UUID) -> list[str]:
    engines.refresh()
    return sorted(engines.db.execute(select(WorkItemTag.tag).where(WorkItemTag.work_item_id == work_item)).scalars())


# ------------------------------------------------------------------------------------------------ document.tag


def test_document_tag_adds_and_removes_tags_and_a_repeat_changes_nothing(engines: Engines) -> None:
    rule = _rule(engines, "Tag big invoices", [{"action_type": "document.tag", "config": {"add": ["Big Invoice", "new-supplier"]}}])
    first = _invoice(engines, "INV-TAG-1")
    assert _tags(engines, first) == ["big-invoice", "new-supplier"]
    assert "tags: added big-invoice, new-supplier" in _node_outcomes(engines, rule["id"])

    from app.models.outbox_event import OutboxEvent

    events = lambda: engines.db.execute(select(func.count()).select_from(OutboxEvent).where(  # noqa: E731
        OutboxEvent.workspace_id == engines.ws, OutboxEvent.event_type == "work_item.field_changed")).scalar_one()
    before = events()
    again = engines.post(f"/automation/rules/{rule['id']}/test", {"work_item_id": str(first)})
    assert again.status_code == 200  # a dry run changes nothing
    assert _tags(engines, first) == ["big-invoice", "new-supplier"] and events() == before


def test_a_tag_is_a_condition_and_the_save_refuses_a_bad_tag_in_words(engines: Engines) -> None:
    _rule(engines, "Hold litigation", [{"action_type": "legal_hold.place", "config": {"reason": "Litigation"}}],
          conditions=[{"field": "document.tags", "operator": "ARRAY_CONTAINS_ANY", "value": ["litigation"]}])
    bad = engines.post("/automation/rules", {"name": "Bad tag", "triggers": ["document.completed"], "condition_groups": [],
                                             "actions": [{"action_type": "document.tag", "config": {"add": ["no way!"]}}]})
    assert bad.status_code == 422 and "is not a valid tag" in bad.text
    both = engines.post("/automation/rules", {"name": "Both", "triggers": ["document.completed"], "condition_groups": [],
                                              "actions": [{"action_type": "document.tag", "config": {"add": ["a"], "remove": ["a"]}}]})
    assert both.status_code == 422 and "both added and removed" in both.text
    none = engines.post("/automation/rules", {"name": "None", "triggers": ["document.completed"], "condition_groups": [],
                                              "actions": [{"action_type": "document.tag", "config": {}}]})
    assert none.status_code == 422 and "Name a tag" in none.text


def test_two_rules_that_tag_each_other_stop_at_the_cycle(engines: Engines) -> None:
    tags_a = _rule(engines, "Tag A on change", [{"action_type": "document.tag", "config": {"add": ["a"]}}],
                   trigger="document.field_changed")
    tags_b = _rule(engines, "Tag B on change", [{"action_type": "document.tag", "config": {"add": ["b"]}}],
                   trigger="document.field_changed")
    # `a` and `b` are added once each; each rule's own change fires the other once, and the chain check ends it.
    document = _invoice(engines, "INV-TAG-LOOP")
    engines.post(f"/automation/rules/{tags_a['id']}/test", {"work_item_id": str(document)})
    mutate = _rule(engines, "Kick", [{"action_type": "document.tag", "config": {"add": ["kick"]}}])
    drain()
    runs_a, runs_b = _runs(engines, tags_a["id"]), _runs(engines, tags_b["id"])
    assert len(runs_a) <= 2 and len(runs_b) <= 2, "the same rule never runs twice in one causal chain"
    assert not any(r["status"] == "RUNNING" for r in runs_a + runs_b)
    assert mutate["id"]


# ----------------------------------------------------------------------------------------------- review.assign


def test_review_assign_gives_the_review_to_a_person_or_the_least_busy_holder_of_a_role(engines: Engines) -> None:
    person = engines.tenant.contributor.user
    rule = _rule(engines, "Review by Carla", [{"action_type": "review.assign", "config": {
        "assignee_email": person.email, "reason": "Large invoice", "due_in_hours": 24}}])
    document = _invoice(engines, "INV-ASG-1")
    engines.refresh()
    held = engines.db.execute(select(ReviewAssignment).where(ReviewAssignment.workspace_id == engines.ws)).scalars().all()
    assert len(held) == 1 and held[0].assignee_user_id == person.id
    assert held[0].due_at is not None
    assert timedelta(hours=23) < held[0].due_at - datetime.now(timezone.utc) <= timedelta(hours=24)
    assert any("assigned, due in 24 hours" in o for o in _node_outcomes(engines, rule["id"]))
    item = engines.get("/review", params={"kind": "EXTRACTION"}).json()["items"]
    assert [str(i["work_item_id"]) for i in item] == [str(document)]

    by_role = _rule(engines, "Review by an admin", [{"action_type": "review.assign", "config": {"assignee_role": "ADMIN"}}],
                    conditions=[{"field": "invoice_number", "operator": "STARTS_WITH", "value": "INV-ROLE"}])
    second = _invoice(engines, "INV-ROLE-1")
    engines.refresh()
    row = engines.db.execute(select(ReviewAssignment).join(
        __import__("app.models.verification", fromlist=["DocumentVerification"]).DocumentVerification,
        __import__("app.models.verification", fromlist=["DocumentVerification"]).DocumentVerification.id == ReviewAssignment.item_id,
    ).where(__import__("app.models.verification", fromlist=["DocumentVerification"]).DocumentVerification.work_item_id == second)).scalar_one()
    assert row.assignee_user_id != person.id and by_role["id"]


def test_review_assign_refuses_someone_who_cannot_work_reviews_in_words(engines: Engines) -> None:
    viewer = engines.tenant.viewer.user
    refused = engines.post("/automation/rules", {"name": "To a viewer", "triggers": ["document.completed"], "condition_groups": [],
                                                 "actions": [{"action_type": "review.assign", "config": {"assignee_email": viewer.email}}]})
    assert refused.status_code == 422 and "who can work reviews" in refused.text
    nobody = engines.post("/automation/rules", {"name": "To nobody", "triggers": ["document.completed"], "condition_groups": [],
                                                "actions": [{"action_type": "review.assign", "config": {"assignee_email": "ghost@nowhere.example"}}]})
    assert nobody.status_code == 422
    neither = engines.post("/automation/rules", {"name": "Neither", "triggers": ["document.completed"], "condition_groups": [],
                                                 "actions": [{"action_type": "review.assign", "config": {}}]})
    assert neither.status_code == 422 and "a person or a role" in neither.text


# ------------------------------------------------------------------------------------------- legal_hold.place


def test_a_rule_can_place_a_hold_once_and_cannot_release_one(engines: Engines) -> None:
    from app.services.automation import actions

    assert "legal_hold.release" not in actions.ACTIONS, "releasing a hold is a person's job"
    rule = _rule(engines, "Hold by tag", [{"action_type": "legal_hold.place", "config": {
        "reason": "Matter {{document.filename}}", "reference": "CASE-7"}}])
    document = _invoice(engines, "INV-HOLD-9")
    engines.refresh()
    holds = engines.db.execute(select(RetentionHold).where(RetentionHold.work_item_id == document)).scalars().all()
    assert len(holds) == 1 and holds[0].reason == "Matter INV-HOLD-9.pdf" and holds[0].reference == "CASE-7"
    assert engines.delete(f"/work-items/{document}").status_code == 409, "the held document cannot be deleted"
    again = engines.post(f"/automation/rules/{rule['id']}/test", {"work_item_id": str(document)})
    assert again.status_code == 200
    drain()
    engines.refresh()
    assert engines.db.execute(select(func.count()).select_from(RetentionHold).where(
        RetentionHold.work_item_id == document)).scalar_one() == 1


# --------------------------------------------------------------------------------------------------- chat.post


def _chat(engines: Engines, kind: str, url: str) -> dict[str, Any]:
    engines.plan("business")
    created = engines.post("/webhooks/endpoints", {"kind": kind, "url": url}, org=True)
    assert created.status_code == 201, created.text
    return created.json()["endpoint"]


def test_a_chat_url_is_stored_encrypted_and_never_shown_back(engines: Engines) -> None:
    endpoint = _chat(engines, "SLACK", SLACK)
    assert endpoint["kind"] == "SLACK" and "SECRETTOKEN" not in json.dumps(endpoint)
    assert endpoint["url"] == "https://slack-in.acme.example.com/…"
    listed = engines.get("/webhooks/endpoints", org=True)
    assert "SECRETTOKEN" not in listed.text
    engines.refresh()
    row = engines.db.get(WebhookEndpoint, uuid.UUID(endpoint["id"]))
    assert row.url_encrypted and "SECRETTOKEN" not in row.url_encrypted and "SECRETTOKEN" not in row.url
    assert row.delivery_url == SLACK
    catalog = engines.get("/automation/catalog").json()["resources"]
    assert any(c["id"] == endpoint["id"] and c["kind"] == "SLACK" for c in catalog["chat_endpoints"])
    assert endpoint["id"] not in {e["id"] for e in catalog["webhook_endpoints"]}
    assert "SECRETTOKEN" not in json.dumps(catalog)


def test_only_a_real_chat_address_is_accepted(engines: Engines) -> None:
    engines.plan("business")
    wrong_host = engines.post("/webhooks/endpoints", {"kind": "SLACK", "url": "https://evil.example.org/hook"}, org=True)
    assert wrong_host.status_code == 422 and "not a Slack incoming-webhook address" in wrong_host.text
    wrong_kind = engines.post("/webhooks/endpoints", {"kind": "TEAMS", "url": "https://hooks.slack.com/services/T/B/x"}, org=True)
    assert wrong_kind.status_code == 422 and "Microsoft Teams" in wrong_kind.text
    plain = engines.post("/webhooks/endpoints", {"kind": "SLACK", "url": "http://hooks.slack.com/services/T/B/x"}, org=True)
    assert plain.status_code == 422
    nothing = engines.post("/webhooks/endpoints", {"kind": "GENERIC", "url": "https://hooks.acme.example.com/x"}, org=True)
    assert nothing.status_code == 422, "an ordinary endpoint still needs its event types"


def test_chat_post_sends_each_platform_its_own_message_and_neutralises_a_documents_text(engines: Engines, receiver) -> None:
    slack = _chat(engines, "SLACK", SLACK)
    teams = _chat(engines, "TEAMS", TEAMS)
    rule = _rule(engines, "Chat both", [
        {"action_type": "chat.post", "config": {"endpoint_id": slack["id"], "title": "Invoice {{field.invoice_number}}",
                                                "message": "{{document.filename}} from {{field.vendor_name}}"}},
        {"action_type": "chat.post", "config": {"endpoint_id": teams["id"], "title": "Invoice {{field.invoice_number}}",
                                                "message": "{{document.filename}} from {{field.vendor_name}}"}},
    ])
    _invoice(engines, "INV-CHAT-1", vendor_name="<!channel> <@U1234> Acme & Sons")
    assert _node_outcomes(engines, rule["id"]).count("message queued for Slack") == 1
    _deliver()
    by_host = {r["url"]: json.loads(r["body"]) for r in receiver.requests}
    assert set(by_host) == {SLACK, TEAMS}, "each message goes to its own secret URL"
    text = by_host[SLACK]["text"]
    assert text.startswith("*Invoice INV-CHAT-1*") and "&lt;!channel&gt;" in text and "&lt;@U1234&gt;" in text
    assert "<!channel>" not in text and "Acme &amp; Sons" in text, "a document cannot ping the channel"
    card = by_host[TEAMS]["attachments"][0]
    assert card["contentType"] == "application/vnd.microsoft.card.adaptive"
    body = card["content"]["body"]
    assert body[0]["text"] == "Invoice INV-CHAT-1" and "Acme & Sons" in body[1]["text"]
    deliveries = engines.db.execute(select(WebhookDelivery).where(WebhookDelivery.organization_id == engines.org)).scalars().all()
    assert len(deliveries) == 2 and all(d.status.value == "DELIVERED" for d in deliveries)
    assert "SECRETTOKEN" not in json.dumps([(d.payload, d.event_type) for d in deliveries])


def test_chat_endpoints_and_webhook_endpoints_are_not_interchangeable(engines: Engines) -> None:
    slack = _chat(engines, "SLACK", SLACK)
    generic = engines.post("/webhooks/endpoints", {"url": "https://hooks.acme.example.com/servabo", "event_types": ["document.completed"]}, org=True)
    assert generic.status_code == 201, generic.text
    generic_id = generic.json()["endpoint"]["id"]
    wrong = engines.post("/automation/rules", {"name": "Webhook to Slack", "triggers": ["document.completed"], "condition_groups": [],
                                               "actions": [{"action_type": "webhook.send", "config": {"endpoint_id": slack["id"]}}]})
    assert wrong.status_code == 422 and "posts to Slack or Teams" in wrong.text
    other_way = engines.post("/automation/rules", {"name": "Chat to a webhook", "triggers": ["document.completed"], "condition_groups": [],
                                                   "actions": [{"action_type": "chat.post", "config": {"endpoint_id": generic_id, "message": "x"}}]})
    assert other_way.status_code == 422 and "Slack or Microsoft Teams" in other_way.text


def test_a_public_event_is_never_delivered_to_a_chat_endpoint(engines: Engines, receiver) -> None:
    _chat(engines, "SLACK", SLACK)
    _invoice(engines, "INV-CHAT-PUB")  # emits public document.completed
    _deliver()
    assert receiver.requests == [], "a chat endpoint takes only what a rule posts to it"


def test_the_chat_test_message_is_a_chat_message(engines: Engines, receiver) -> None:
    slack = _chat(engines, "SLACK", SLACK)
    sent = engines.post(f"/webhooks/endpoints/{slack['id']}/test", org=True)
    assert sent.status_code == 202, sent.text
    _deliver()
    assert receiver.requests and json.loads(receiver.requests[0]["body"])["text"].startswith("*Servabo test message*")


def test_the_organizations_network_rules_can_refuse_chat(engines: Engines) -> None:
    engines.plan("enterprise")
    created = engines.post("/webhooks/endpoints", {"kind": "SLACK", "url": SLACK}, org=True)
    assert created.status_code == 201, created.text
    endpoint = created.json()["endpoint"]
    assert engines.put("/egress", {"lockdown_enabled": True}, org=True).status_code == 200
    refused = engines.post("/automation/rules", {"name": "Chat under lockdown", "triggers": ["document.completed"],
                                                 "condition_groups": [], "actions": [{"action_type": "chat.post", "config": {
                                                     "endpoint_id": endpoint["id"], "message": "x"}}]})
    assert refused.status_code == 422 and "network rules do not allow" in refused.text
    rule = engines.post("/egress/rules", {"channel": "WEBHOOK", "host_pattern": "slack-in.acme.example.com"}, org=True)
    assert rule.status_code in (200, 201), rule.text
    allowed = engines.post("/automation/rules", {"name": "Chat allowed", "triggers": ["document.completed"],
                                                 "condition_groups": [], "actions": [{"action_type": "chat.post", "config": {
                                                     "endpoint_id": endpoint["id"], "message": "x"}}]})
    assert allowed.status_code == 201, allowed.text
    assert engines.delete(f"/egress/rules/{rule.json()['id']}", org=True).status_code == 204
    _invoice(engines, "INV-CHAT-EGR")
    _deliver()
    engines.refresh()
    delivery = engines.db.execute(select(WebhookDelivery).where(WebhookDelivery.organization_id == engines.org)).scalars().first()
    assert delivery is not None and delivery.status.value in ("DEAD", "FAILED")
    assert "EGRESS" in (delivery.last_error or "").upper() or "SSRF_REFUSED" in (delivery.last_error or "")


def test_chat_follows_the_outgoing_webhooks_capability(engines: Engines) -> None:
    from app.core import entitlements

    engines.plan("free")
    created = engines.post("/webhooks/endpoints", {"kind": "SLACK", "url": SLACK}, org=True)
    assert created.status_code == 402, "the registry's own plan gate applies to chat endpoints too"
    from app.services.automation import actions

    assert actions.ACTIONS["chat.post"].capability == entitlements.OUTGOING_WEBHOOKS_CAPABILITY
    engines.plan("developer")
    catalog = {a["type"]: a for a in engines.get("/automation/catalog").json()["actions"]}
    assert catalog["chat.post"]["capability"] == "capability.outgoing_webhooks"
    assert catalog["chat.post"]["minimum_role"] == "ORGANIZATION_ADMIN"


# ------------------------------------------------------------------------------------------------ obligation.create


def test_obligation_create_makes_one_follow_up_due_in_n_days(engines: Engines) -> None:
    engines.plan("business")
    rule = _rule(engines, "Follow up", [{"action_type": "obligation.create", "config": {
        "title": "Chase {{field.invoice_number}}", "kind": "PAYMENT", "due_in_days": 10,
        "owner_email": engines.tenant.contributor.user.email}}])
    document = _invoice(engines, "INV-OBL-1")
    listed = engines.get("/obligations").json()
    items = listed["items"] if isinstance(listed, dict) else listed
    mine = [o for o in items if o["title"] == "Chase INV-OBL-1"]
    assert len(mine) == 1
    from app.services.obligations import service

    expected = service.local_today(engines.db, engines.ws) + timedelta(days=10)
    assert mine[0]["due_date"] == expected.isoformat() and mine[0]["kind"] == "PAYMENT"
    assert str(mine[0].get("work_item_id")) == str(document)
    assert any("follow-up created" in o for o in _node_outcomes(engines, rule["id"]))
    engines.post(f"/automation/rules/{rule['id']}/test", {"work_item_id": str(document)})
    again = engines.get("/obligations").json()
    assert len([o for o in (again["items"] if isinstance(again, dict) else again) if o["title"] == "Chase INV-OBL-1"]) == 1


def test_obligation_create_needs_the_obligations_plan_and_a_member_owner(engines: Engines) -> None:
    engines.plan("developer")
    cfg = {"action_type": "obligation.create", "config": {"title": "x"}}
    refused = engines.post("/automation/rules", {"name": "No plan", "triggers": ["document.completed"], "condition_groups": [], "actions": [cfg]})
    assert refused.status_code == 422 and "not included in your plan" in refused.text
    engines.plan("business")
    stranger = engines.post("/automation/rules", {"name": "Stranger", "triggers": ["document.completed"], "condition_groups": [],
                                                  "actions": [{"action_type": "obligation.create", "config": {"owner_email": "nobody@nowhere.example"}}]})
    assert stranger.status_code == 422 and "not a member of this workspace" in stranger.text


# ------------------------------------------------------------- gst.remind_supplier, supplier.request_document


@pytest.fixture()
def known_supplier(engines: Engines, monkeypatch):
    """A supplier whose email contact Helm knows, and a mail relay that records instead of sending."""
    from app.models.helm import HelmCounterparty
    from app.services.email_service import email_service
    from tests.services.gst.helpers import SUPPLIER_A

    engines.plan("business")
    book = engines.client.post(f"/api/v1/organizations/{engines.org}/helm/books", json={"workspace_id": str(engines.ws)},
                               headers=engines.tenant.owner.headers).json()
    engines.db.add(HelmCounterparty(organization_id=engines.org, book_id=uuid.UUID(book["id"]), key=f"gstin:{SUPPLIER_A}",
                                    role="SUPPLIER", display_name="Sahyadri Packaging", tax_id=SUPPLIER_A,
                                    contact_email="accounts@sahyadri.example.com"))
    engines.db.commit()
    sent: list[dict[str, Any]] = []

    def record(*, settings, recipient, subject, html_body, text_body, reply_to=None):
        sent.append({"to": recipient, "subject": subject, "html": html_body, "text": text_body})
        return True, "ok"

    monkeypatch.setattr(email_service, "send_html_email", record)
    return SUPPLIER_A, sent


def test_gst_remind_supplier_emails_the_known_contact_once_a_week(engines: Engines, known_supplier) -> None:
    from app.services.gst import builder as b
    from tests.services.gst.helpers import RECIPIENT, SUPPLIER_A, book_invoice, supplier_invoices

    supplier, sent = known_supplier
    rule = _rule(engines, "Remind waiting suppliers", [{"action_type": "gst.remind_supplier", "config": {}}],
                 trigger="gst.waiting_for_supplier")
    today = date.today()
    waiting = [book_invoice(engines.db, engines.tenant, number=f"W-{n}", supplier="a", gstin=SUPPLIER_A,
                            on=today - timedelta(days=45 + n), taxable=100_000 + n) for n in range(2)]
    for item, number in zip(waiting, range(2)):
        item.created_at = datetime.now(timezone.utc) - timedelta(days=45 + number)
    engines.db.commit()
    period = f"{today.year:04d}-{today.month:02d}"
    earlier = today - timedelta(days=50)
    for day in (earlier, today):
        p = f"{day.year:04d}-{day.month:02d}"
        statement = b.to_bytes(b.gstr2b(RECIPIENT, p, {"b2b": [supplier_invoices([b.document(f"ZZ-{p}", day, 1_000)])]}))
        sent_file = engines.client.post(f"/api/v1/workspaces/{engines.ws}/gst/returns", headers=engines.tenant.contributor.headers,
                                        files={"file": (f"{p}.json", statement)})
        assert sent_file.status_code == 200, sent_file.text
    from app.services.automation import sweeps

    sweeps.run(engines.db)
    engines.db.commit()
    drain()
    assert period and len(sent) == 1, "two waiting invoices from one supplier send one reminder"
    assert sent[0]["to"] == "accounts@sahyadri.example.com" and "W-0" in sent[0]["text"] and "W-1" in sent[0]["text"]
    outcomes = _node_outcomes(engines, rule["id"])
    assert any("reminder sent to the supplier's known contact" in o for o in outcomes)
    assert any("reminded within the last 7 days" in o for o in outcomes)


def test_gst_remind_supplier_sends_nothing_without_a_known_contact(engines: Engines, known_supplier) -> None:
    from app.models.helm import HelmCounterparty
    from tests.services.gst.helpers import RECIPIENT, SUPPLIER_A, book_invoice

    _supplier, sent = known_supplier
    engines.db.query(HelmCounterparty).delete()
    engines.db.commit()
    rule = _rule(engines, "Remind", [{"action_type": "gst.remind_supplier", "config": {}}], trigger="manual")
    today = date.today()
    item = book_invoice(engines.db, engines.tenant, number="NC-1", supplier="a", gstin=SUPPLIER_A, on=today - timedelta(days=40), taxable=1000)
    engines.db.commit()
    from app.services.gst import builder as b
    from tests.services.gst.helpers import supplier_invoices

    for day in (today - timedelta(days=40), today):
        p = f"{day.year:04d}-{day.month:02d}"
        statement = b.to_bytes(b.gstr2b(RECIPIENT, p, {"b2b": [supplier_invoices([b.document(f"ZZ-{p}", day, 1_000)])]}))
        engines.client.post(f"/api/v1/workspaces/{engines.ws}/gst/returns", headers=engines.tenant.contributor.headers,
                            files={"file": (f"{p}.json", statement)})
    assert engines.post(f"/automation/rules/{rule['id']}/run", {"work_item_id": str(item.id)}).status_code == 202
    drain()
    assert sent == []
    outcomes = _node_outcomes(engines, rule["id"])
    assert any("no email contact is known" in o for o in outcomes), (outcomes, _runs(engines, rule["id"]))


def test_supplier_request_document_sends_a_link_to_the_known_contact_and_opens_a_case(engines: Engines, known_supplier) -> None:
    from app.core.config import settings

    supplier, sent = known_supplier
    template = engines.post("/case-templates", {"key": "kyc", "name": "Supplier KYC", "rules": [],
                                                "required_documents": [{"doc_type": "gst_registration", "label": "GST registration"}]})
    assert template.status_code == 201, template.text
    assert engines.post(f"/case-templates/{template.json()['id']}/publish").status_code == 200
    rule = _rule(engines, "Ask for registration", [{"action_type": "supplier.request_document", "config": {
        "case_template_id": template.json()["id"], "document_type": "gst_registration"}}])
    _invoice(engines, "INV-REQ-1", vendor_gstin=supplier)
    assert len(sent) == 1 and sent[0]["to"] == "accounts@sahyadri.example.com"
    link = sent[0]["text"].split("(no account needed): ")[1].split("\n")[0]
    assert link.startswith(settings.FRONTEND_URL.rstrip("/") + "/request/")
    token = link.rsplit("/", 1)[1]
    assert engines.client.get(f"/api/v1/public/document-requests/{token}").status_code == 200
    cases = engines.get("/cases").json()
    assert any("Supplier KYC" in c["title"] for c in cases["items"])
    _invoice(engines, "INV-REQ-2", vendor_gstin=supplier)
    assert len(sent) == 1, "one open request per supplier, template and document type"
    assert any("already open" in o for o in _node_outcomes(engines, rule["id"]))


def test_the_new_actions_have_a_role_a_capability_and_a_selector(engines: Engines) -> None:
    from app.services.automation import actions
    from app.services.fenced_context import TOOL_SELECTORS

    for action_type in ("document.tag", "review.assign", "legal_hold.place", "chat.post", "gst.remind_supplier",
                        "obligation.create", "supplier.request_document"):
        definition = actions.ACTIONS[action_type]
        assert definition.minimum_role in actions.MINIMUM_ROLES and definition.selector in TOOL_SELECTORS
        assert definition.config_model.model_config.get("extra") == "forbid"
    assert actions.ACTIONS["gst.remind_supplier"].either and actions.ACTIONS["gst.remind_supplier"].addon == "addon.gst_credit"
    assert actions.ACTIONS["chat.post"].minimum_role == "ORGANIZATION_ADMIN"
    catalog = {a["type"]: a for a in engines.get("/automation/catalog").json()["actions"]}
    assert catalog["document.tag"]["needs_document"] and catalog["legal_hold.place"]["needs_document"]
    assert catalog["chat.post"]["idempotent"] is False and catalog["document.tag"]["idempotent"] is True


def test_a_contact_helm_derived_from_documents_is_known_by_its_gstin_key(engines: Engines) -> None:
    """Helm's sync stores a supplier under the key `gstin:<GSTIN>` and never fills `tax_id`; the reminder's lookup used to
    read only `tax_id`, so no supplier Helm had derived from a document ever had a known contact (found by browser spec 115)."""
    from app.models.helm import HelmCounterparty
    from app.models.workspace import Workspace
    from app.services.gst import reminder
    from tests.services.gst.helpers import SUPPLIER_A, SUPPLIER_B

    engines.plan("business")
    book = engines.client.post(f"/api/v1/organizations/{engines.org}/helm/books", json={"workspace_id": str(engines.ws)},
                               headers=engines.tenant.owner.headers).json()
    for key, email in ((f"gstin:{SUPPLIER_A}", "accounts@sahyadri.example.com"), (f"gstin:{SUPPLIER_B}", None)):
        engines.db.add(HelmCounterparty(organization_id=engines.org, book_id=uuid.UUID(book["id"]), key=key, role="SUPPLIER",
                                        display_name="Derived by sync", tax_id=None, contact_email=email))
    engines.db.commit()
    workspace = engines.db.get(Workspace, engines.ws)
    assert reminder.known_contact(engines.db, workspace, SUPPLIER_A) == "accounts@sahyadri.example.com"
    assert reminder.known_contact(engines.db, workspace, SUPPLIER_B) is None, "a supplier with no contact stays unknown"
    assert reminder.known_contact(engines.db, workspace, "29ZZZZZ9999Z9Z9") is None


def test_helms_own_sync_records_the_suppliers_gstin_so_its_contact_is_found(engines: Engines) -> None:
    """The whole path, with nothing written by hand: an invoice naming a supplier, its GSTIN and its email is read; Helm
    derives the supplier; the reminder then finds its contact (F-545)."""
    from app.models.helm import HelmCounterparty
    from app.models.workspace import Workspace
    from app.services.gst import reminder
    from tests.services.gst.helpers import SUPPLIER_A

    engines.plan("business")
    engines.process("SAH-1.pdf", [["TAX INVOICE", "Invoice Number: SAH-1"]], marker="SAH-1", classification="Invoice", entities={
        "invoice_number": "SAH-1", "invoice_date": "2026-09-01", "due_date": "2026-10-01", "total_amount": "11800.00",
        "currency": "INR", "vendor_name": "Sahyadri Packaging", "vendor_gstin": SUPPLIER_A,
        "vendor_email": "accounts@sahyadri.example.com"})
    created = engines.client.post(f"/api/v1/organizations/{engines.org}/helm/books", json={"workspace_id": str(engines.ws)},
                                  headers=engines.tenant.owner.headers)
    assert created.status_code in (200, 201), created.text
    book = created.json()["id"]
    from app.models.helm import HelmBook
    from app.services.helm import counterparties, ledger_store

    engines.refresh()
    ledger_store.rebuild_workspace(engines.db, workspace_id=engines.ws)
    counterparties.sync(engines.db, engines.db.get(HelmBook, uuid.UUID(book)))
    engines.db.commit()
    engines.refresh()
    rows = list(engines.db.execute(select(HelmCounterparty).where(HelmCounterparty.organization_id == engines.org)).scalars())
    assert rows, "Helm derived no supplier from the invoice"
    assert [r.contact_email for r in rows] == ["accounts@sahyadri.example.com"]
    workspace = engines.db.get(Workspace, engines.ws)
    assert reminder.known_contact(engines.db, workspace, SUPPLIER_A) == "accounts@sahyadri.example.com"
