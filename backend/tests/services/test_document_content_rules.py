"""Final session 1 (1A): erasing a person's documents, and purging them, leave no copy of their content behind.

Each test plants a copy of an invoice's content in ONE store that the study (UPGRADE-AUDIT F-546, F-547) found
unprotected, runs the real erasure or the real purge, and looks at the store. Every one of these failed before
`document_content.py` and the data map existed.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import select, text

from app.models.automation import AutomationRule
from app.models.automation_execution import (
    AutomationExecution,
    AutomationExecutionStatus,
    AutomationNodeRun,
    AutomationNodeRunStatus,
)
from app.models.gst import GstDecision, GstMatch, GstReturn, GstReturnRecord
from app.models.helm import HelmAction, HelmBook, HelmSettlement, HelmTask, HelmValueEvent
from app.models.notification import Notification
from app.models.outbox_event import OutboxEvent
from app.models.webhook_delivery import WebhookDelivery
from app.models.webhook_delivery_attempt import AttemptDisposition, WebhookDeliveryAttempt
from app.models.webhook_endpoint import WebhookEndpoint
from app.models.work_item import WorkItem
from app.services.compliance import document_content, erasure_service

SECRET = "Sahyadri Packaging"        # a supplier name that came from the erased invoice
AMOUNT = "INR 1,48,000.00"            # a value a condition read


def _invoice(db, tenant, subject) -> WorkItem:
    item = WorkItem(
        workspace_id=tenant.workspace.id, created_by_user_id=subject.id, original_filename="inv-2048.pdf",
        stored_filename=f"stored-{uuid.uuid4().hex}", file_type="application/pdf", file_size=1024, status="COMPLETED",
        extracted_text=f"{SECRET} invoice INV-2048 total {AMOUNT}", extracted_entities={"vendor_name": SECRET},
    )
    db.add(item)
    db.flush()
    return item


@pytest.fixture()
def planted(db_session, tenant):
    """An invoice by the contributor, with a copy of its content in every newer store."""
    db, org, ws = db_session, tenant.organization, tenant.workspace
    subject = tenant.contributor.user
    item = _invoice(db, tenant, subject)
    other = _invoice(db, tenant, tenant.owner.user)  # someone else's document: must be untouched

    rows: dict[str, object] = {}
    rule = AutomationRule(name="r", event="DOCUMENT_UPLOADED", workspace_id=ws.id)
    db.add(rule)
    db.flush()

    def execution(work_item):
        ex = AutomationExecution(
            organization_id=org.id, workspace_id=ws.id, rule_id=rule.id, work_item_id=work_item.id,
            correlation_id=uuid.uuid4(), status=AutomationExecutionStatus.COMPLETED, budget_cost_micros=0,
            started_at=datetime.now(timezone.utc), completed_at=datetime.now(timezone.utc),
            details={"trace": [{"field": "total", "read": AMOUNT}]}, error=f"could not read {SECRET}",
        )
        db.add(ex)
        db.flush()
        run = AutomationNodeRun(execution_id=ex.id, node_key="n1", node_type="CONDITION", sequence=1,
                                status=AutomationNodeRunStatus.COMPLETED, started_at=datetime.now(timezone.utc), completed_at=datetime.now(timezone.utc), details={"read": AMOUNT}, error=SECRET)
        db.add(run)
        db.flush()
        return ex, run

    rows["execution"], rows["node_run"] = execution(item)
    rows["other_execution"], _ = execution(other)

    rows["notification"] = Notification(title="Invoice", message=f"{SECRET} sent INV-2048", user_id=tenant.owner.user.id,
                                        organization_id=org.id, workspace_id=ws.id, work_item_id=item.id)
    db.add(rows["notification"])
    other_note = Notification(title="Invoice", message="Another invoice", user_id=tenant.owner.user.id,
                              organization_id=org.id, workspace_id=ws.id, work_item_id=other.id)
    db.add(other_note)

    payload = {"work_item_id": str(item.id), "supplier_name": SECRET, "amount": AMOUNT}
    rows["outbox"] = OutboxEvent(organization_id=org.id, workspace_id=ws.id, event_type="document.completed",
                                 resource_id=item.id, payload=payload)
    db.add(rows["outbox"])
    rows["other_outbox"] = OutboxEvent(organization_id=org.id, workspace_id=ws.id, event_type="document.completed",
                                       resource_id=other.id, payload={"work_item_id": str(other.id), "supplier_name": "Other"})
    db.add(rows["other_outbox"])
    db.flush()
    endpoint = WebhookEndpoint(organization_id=org.id, url="https://example.com/hook", event_types=["document.completed"],
                               secret_encrypted="x")
    db.add(endpoint)
    db.flush()
    rows["delivery"] = WebhookDelivery(webhook_endpoint_id=endpoint.id, organization_id=org.id, outbox_event_id=rows["outbox"].id,
                                       event_type="document.completed", payload=payload)
    db.add(rows["delivery"])
    db.flush()
    rows["attempt"] = WebhookDeliveryAttempt(webhook_delivery_id=rows["delivery"].id, organization_id=org.id, attempt_number=1,
                                             request_url="https://example.com/hook", disposition=AttemptDisposition.DELIVERED,
                                             duration_ms=5, response_status=200, response_body_excerpt=f"got {SECRET}")
    db.add(rows["attempt"])

    ret = GstReturn(organization_id=org.id, workspace_id=ws.id, gstin="27AAAAA0000A1Z5", period="2026-09", rtnprd="092026",
                    file_sha256="0" * 64, file_name="r.json")
    db.add(ret)
    db.flush()
    record = GstReturnRecord(organization_id=org.id, workspace_id=ws.id, return_id=ret.id, gstin="27AAAAA0000A1Z5", period="2026-09",
                           section="b2b", kind="INVOICE", supplier_gstin="29BBBBB1111B1Z6", supplier_name=SECRET, doc_number="INV-2048")
    db.add(record)
    db.flush()
    rows["match"] = GstMatch(organization_id=org.id, workspace_id=ws.id, gstin="27AAAAA0000A1Z5", status="MATCHED_WITH_DIFFERENCES",
                             record_id=record.id, work_item_id=item.id, supplier_gstin="29BBBBB1111B1Z6", supplier_name=SECRET, doc_number="INV-2048",
                             doc_date=date(2026, 9, 12), value_micros=148_000_000_000, tax_micros=22_576_271_186,
                             itc_micros=22_576_271_186, differences=[{"code": "TAX", "books": AMOUNT}],
                             notes=[{"code": "NUMBER_FORMAT", "books": "INV-2048"}], ims_reason=f"{SECRET} mismatch")
    db.add(rows["match"])
    rows["decision"] = GstDecision(organization_id=org.id, workspace_id=ws.id, gstin="27AAAAA0000A1Z5", supplier_gstin="29BBBBB1111B1Z6",
                                   doc_key="INV2048", kind="IMS", decision="CONFIRM", work_item_id=item.id, note=f"{SECRET} confirmed by phone")
    db.add(rows["decision"])

    book = HelmBook(organization_id=org.id, kind="ORGANIZATION", name="Helm")
    db.add(book)
    db.flush()
    rows["settlement"] = HelmSettlement(organization_id=org.id, workspace_id=ws.id, work_item_id=item.id, state="PAID",
                                        paid_on=date(2026, 10, 1), paid_amount_micros=148_000_000_000, source="PERSON",
                                        paid_reference=f"UTR for {SECRET}", hold_reason=None, evidence={"quote": SECRET})
    db.add(rows["settlement"])
    rows["action"] = HelmAction(organization_id=org.id, book_id=book.id, workspace_id=ws.id, work_item_id=item.id, kind="schedule_payment",
                                idempotency_key=uuid.uuid4().hex, state="EXECUTED", autonomy="propose", title=f"Pay {SECRET}",
                                explanation=f"{SECRET} due 12 Oct", amount_micros=148_000_000_000, params={"supplier": SECRET},
                                result={"ok": True, "supplier": SECRET})
    db.add(rows["action"])
    rows["task"] = HelmTask(organization_id=org.id, workspace_id=ws.id, book_id=book.id, kind="VERIFY_BANK_ACCOUNT", work_item_id=item.id,
                            title=f"Check {SECRET}", body=f"{SECRET} bank account changed", severity="LOW")
    db.add(rows["task"])
    rows["value"] = HelmValueEvent(organization_id=org.id, book_id=book.id, workspace_id=ws.id, work_item_id=item.id,
                                   category="DISCOUNT_CAPTURED", dedupe_key=uuid.uuid4().hex, currency="INR",
                                   amount_micros=2_000_000_000, occurred_on=date(2026, 10, 1), month=date(2026, 10, 1),
                                   evidence={"supplier": SECRET})
    db.add(rows["value"])
    db.flush()
    rows["item"], rows["other"] = item, other
    return rows


def _ids(planted):
    """The ids, read while the rows still exist (a deleted row cannot be refreshed)."""
    return {k: v.id for k, v in planted.items() if hasattr(v, "id")}


# ---------------------------------------------------------------------------------------------- erasure

def _erase(db, tenant):
    return erasure_service.erase_subject(
        db, organization=tenant.organization, subject_user_id=tenant.contributor.user.id,
        erasure_ticket="T-1", actor_user_id=tenant.owner.user.id,
    )


def test_erasure_clears_the_values_an_automation_trace_read(db_session, tenant, planted):
    ids = _ids(planted)
    _erase(db_session, tenant)
    db_session.expire_all()
    ex = db_session.get(AutomationExecution, ids["execution"])
    assert ex is not None and ex.status == AutomationExecutionStatus.COMPLETED  # the audit of what ran stays
    assert AMOUNT not in str(ex.details) and SECRET not in (ex.error or "")
    run = db_session.get(AutomationNodeRun, ids["node_run"])
    assert AMOUNT not in str(run.details) and SECRET not in (run.error or "")
    untouched = db_session.get(AutomationExecution, ids["other_execution"])
    assert AMOUNT in str(untouched.details), "someone else's document is not touched"


def test_erasure_deletes_notices_that_quote_the_document(db_session, tenant, planted):
    ids = _ids(planted)
    _erase(db_session, tenant)
    db_session.expire_all()
    assert db_session.get(Notification, ids["notification"]) is None
    assert db_session.execute(select(Notification).where(Notification.work_item_id == ids["other"])).scalars().all()


def test_erasure_deletes_event_payloads_and_their_deliveries(db_session, tenant, planted):
    ids = _ids(planted)
    _erase(db_session, tenant)
    db_session.expire_all()
    assert db_session.get(OutboxEvent, ids["outbox"]) is None
    assert db_session.get(WebhookDelivery, ids["delivery"]) is None
    assert db_session.get(WebhookDeliveryAttempt, ids["attempt"]) is None
    assert db_session.get(OutboxEvent, ids["other_outbox"]) is not None


def test_erasure_keeps_a_gst_match_but_loses_the_names_and_the_documents_own_values(db_session, tenant, planted):
    ids = _ids(planted)
    _erase(db_session, tenant)
    db_session.expire_all()
    m = db_session.get(GstMatch, ids["match"])
    assert m is not None, "a GST match is a money record: it stays"
    assert m.value_micros == 148_000_000_000 and m.itc_micros == 22_576_271_186 and m.status == "MATCHED_WITH_DIFFERENCES"
    assert m.supplier_gstin == "29BBBBB1111B1Z6", "the books need the GSTIN (N-163)"
    assert m.supplier_name is None and m.notes == [] and m.differences == [] and m.ims_reason is None
    d = db_session.get(GstDecision, ids["decision"])
    assert d.decision == "CONFIRM" and d.note is None


def test_erasure_keeps_helm_money_and_clears_its_free_text(db_session, tenant, planted):
    ids = _ids(planted)
    _erase(db_session, tenant)
    db_session.expire_all()
    s = db_session.get(HelmSettlement, ids["settlement"])
    assert s.state == "PAID" and s.paid_amount_micros == 148_000_000_000 and s.paid_on == date(2026, 10, 1)
    assert s.paid_reference is None and s.evidence == {}
    a = db_session.get(HelmAction, ids["action"])
    assert a.amount_micros == 148_000_000_000 and SECRET not in (a.title + (a.explanation or "") + str(a.params) + str(a.result))
    assert SECRET not in db_session.get(HelmTask, ids["task"]).body
    value = db_session.get(HelmValueEvent, ids["value"])
    assert value.amount_micros == 2_000_000_000 and value.evidence == {}


def test_erasure_leaves_the_books_themselves_alone(db_session, tenant, planted):
    """The GSTR-2B rows come from the government portal, not from the erased invoice (N-163)."""
    _erase(db_session, tenant)
    db_session.expire_all()
    book = db_session.execute(select(GstReturnRecord).where(GstReturnRecord.organization_id == tenant.organization.id)).scalar_one()
    assert book.supplier_name == SECRET and book.supplier_gstin == "29BBBBB1111B1Z6" and book.doc_number == "INV-2048"


# --------------------------------------------------------------------------------------------- the sweep

def test_the_sweep_keeps_money_records_and_lets_go_of_their_document(db_session, tenant, planted):
    ids = _ids(planted)
    counts = document_content.destroy_copies(db_session, [ids["item"]], mode="purge")
    db_session.execute(text("DELETE FROM work_items WHERE id = :i"), {"i": ids["item"]})
    db_session.expire_all()
    # money records survive the document's deletion, detached from it
    m = db_session.get(GstMatch, ids["match"])
    assert m is not None and m.work_item_id is None and m.supplier_name is None and m.itc_micros == 22_576_271_186
    s = db_session.get(HelmSettlement, ids["settlement"])
    assert s is not None and s.work_item_id is None and s.paid_amount_micros == 148_000_000_000
    assert db_session.get(GstDecision, ids["decision"]) is None, "a confirm is about one document: it goes with it"
    assert db_session.get(HelmAction, ids["action"]).amount_micros == 148_000_000_000
    assert db_session.get(HelmAction, ids["action"]).work_item_id is None
    assert db_session.get(HelmValueEvent, ids["value"]).amount_micros == 2_000_000_000
    # copies without a foreign key are gone, and the trace no longer holds the values
    assert db_session.get(OutboxEvent, ids["outbox"]) is None
    assert db_session.get(WebhookDelivery, ids["delivery"]) is None
    ex = db_session.get(AutomationExecution, ids["execution"])
    assert ex is not None and ex.work_item_id is None and AMOUNT not in str(ex.details)
    assert counts["outbox_events"] == 1


def test_a_match_with_no_book_record_has_nothing_left_to_keep(db_session, tenant, planted):
    """The invoice was missing from GSTR-2B: the match is only about the document, so it goes with it."""
    ids = _ids(planted)
    db_session.execute(text("UPDATE gst_matches SET record_id = NULL WHERE id = :m"), {"m": ids["match"]})
    document_content.destroy_copies(db_session, [ids["item"]], mode="purge")
    db_session.execute(text("DELETE FROM work_items WHERE id = :i"), {"i": ids["item"]})
    db_session.expire_all()
    assert db_session.get(GstMatch, ids["match"]) is None


def test_the_engine_does_nothing_for_no_documents(db_session):
    assert document_content.destroy_copies(db_session, [], mode="erase") == {}
