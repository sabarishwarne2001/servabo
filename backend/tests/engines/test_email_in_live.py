"""Final session 1 (2B): documents forwarded to a workspace's own address (Postmark inbound, stood in).

Every test posts what Postmark really posts (tests/fakes/fake_postmark_inbound.py) to the real public route, with the real
worker draining the jobs behind it. Proven: the credential, the address (and that a rotated one stops working), the sender
rules, a replay, the size limit, a PDF, a zip, a GSTR-2B JSON, a signature image, a message with nothing to read, the plan
and trial limits, approve and discard, and the chain: an emailed GST invoice appears in the GST books and Helm's ledger.
"""

from __future__ import annotations

import io
import json
import zipfile
from datetime import date

import pytest
from pydantic import SecretStr
from sqlalchemy import select

from app.core.config import settings
from app.models.inbound_email import InboundEmailSender, InboundMessage, WorkItemSource
from app.models.notification import Notification
from app.models.work_item import WorkItem
from app.services import plan_admission
from app.services.inbound_email import service
from tests.engines.conftest import Engines, drain, make_pdf
from tests.fakes import fake_postmark_inbound as pm

SENDER = "ap@supplier.example"

#: The collections this module proves isolated with its own assertions (tests/isolation/test_structural_invariants.py).
ISOLATION_PROVEN_HERE = ("inbound-email",)


def _pdf(number: str = "INV-5001") -> bytes:
    return make_pdf([[f"TAX INVOICE {number}", "Vendor: Sahyadri Packaging", "Total Amount Due: 1000.00 INR"]])


@pytest.fixture()
def mail(engines: Engines, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "POSTMARK_INBOUND_WEBHOOK_USER", pm.DEFAULT_USER)
    monkeypatch.setattr(settings, "POSTMARK_INBOUND_WEBHOOK_PASSWORD", SecretStr(pm.DEFAULT_PASSWORD))
    monkeypatch.setattr(settings, "POSTMARK_INBOUND_HASH", pm.DEFAULT_HASH)
    monkeypatch.setattr(settings, "INBOUND_EMAIL_DOMAIN", "")
    monkeypatch.setattr(settings, "POSTMARK_INBOUND_ALLOWED_IPS", "")
    first = engines.get("/inbound-email").json()
    assert first["enabled"] and first["address"].endswith("@inbound.postmarkapp.com")

    class Mail:
        e = engines
        address = first["address"]

        @staticmethod
        def allow(pattern: str = SENDER):
            response = engines.post("/inbound-email/senders", {"pattern": pattern})
            assert response.status_code == 201, response.text

        @staticmethod
        def send(*attachments, address: str | None = None, **kw):
            payload = pm.for_address(address or Mail.address, attachments=list(attachments), **kw)
            return pm.post(engines.client, payload)

        @staticmethod
        def view():
            return engines.get("/inbound-email").json()

    return Mail


def _messages(engines: Engines):
    engines.db.expire_all()
    return engines.db.execute(select(InboundMessage).where(InboundMessage.workspace_id == engines.ws)).scalars().all()


def _documents(engines: Engines):
    engines.db.expire_all()
    return engines.db.execute(select(WorkItem).where(WorkItem.workspace_id == engines.ws)).scalars().all()


# ------------------------------------------------------------------------------------------------ the door

def test_email_in_is_off_until_the_credential_is_set(engines: Engines, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "POSTMARK_INBOUND_WEBHOOK_USER", "")
    response = pm.post(engines.client, pm.message(to="x@inbound.postmarkapp.com"))
    assert response.status_code == 404
    view = engines.get("/inbound-email").json()
    assert view["enabled"] is False


@pytest.mark.parametrize(("user", "password"), [(None, ""), ("postmark-inbound", "wrong"), ("someone", pm.DEFAULT_PASSWORD), ("", "")])
def test_a_missing_or_wrong_credential_is_refused_without_saying_which_part(mail, user, password) -> None:
    payload = pm.for_address(mail.address, attachments=[pm.attachment("a.pdf", _pdf())])
    response = pm.post(mail.e.client, payload, user=user, password=password)
    assert response.status_code == 401
    assert "password" not in response.text.lower() and pm.DEFAULT_PASSWORD not in response.text


def test_an_unknown_address_is_a_403_so_postmark_stops_retrying(mail) -> None:
    response = mail.send(pm.attachment("a.pdf", _pdf()), address=f"{pm.DEFAULT_HASH}+{'0' * 32}@inbound.postmarkapp.com")
    assert response.status_code == 403
    assert _messages(mail.e) == []


def test_a_body_that_is_not_a_postmark_message_is_a_422_and_too_large_a_body_a_413(mail, monkeypatch: pytest.MonkeyPatch) -> None:
    assert pm.post(mail.e.client, {}, raw=b"not json").status_code == 422
    assert pm.post(mail.e.client, {"hello": "world"}).status_code == 422
    monkeypatch.setattr(settings, "INBOUND_EMAIL_MAX_BODY_MB", 0)
    assert mail.send(pm.attachment("a.pdf", _pdf())).status_code == 413


def test_an_ip_allowlist_when_set_refuses_other_addresses(mail, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "POSTMARK_INBOUND_ALLOWED_IPS", "203.0.113.0/24")
    assert mail.send(pm.attachment("a.pdf", _pdf())).status_code == 403


# ------------------------------------------------------------------------------------------------ addresses

def test_the_address_never_contains_the_workspace_name_or_slug(mail) -> None:
    local = mail.address.split("@", 1)[0]
    assert pm.DEFAULT_HASH in local
    token = local.split("+", 1)[1]
    assert len(token) == 32 and token.isalnum()
    for word in (mail.e.tenant.workspace.slug, mail.e.tenant.organization.slug, mail.e.tenant.workspace.workspace_name.lower()):
        assert word.lower() not in mail.address.lower()


def test_a_domain_address_routes_on_the_local_part_alone(mail, monkeypatch: pytest.MonkeyPatch) -> None:
    mail.allow()
    monkeypatch.setattr(settings, "INBOUND_EMAIL_DOMAIN", "in.servabo.example")
    address = mail.view()["address"]
    assert address.endswith("@in.servabo.example") and "+" not in address
    response = pm.post(mail.e.client, pm.message(to=address, mailbox_hash="", attachments=[pm.attachment("a.pdf", _pdf())]))
    assert response.status_code == 200 and response.json()["status"] == "accepted"


def test_a_rotated_address_stops_working_and_the_new_one_works(mail) -> None:
    mail.allow()
    old = mail.address
    assert mail.send(pm.attachment("a.pdf", _pdf())).status_code == 200
    rotated = mail.e.post("/inbound-email/rotate").json()
    assert rotated["address"] != old
    refused = mail.send(pm.attachment("b.pdf", _pdf("INV-5002")), address=old)
    assert refused.status_code == 403, "mail to the retired address is refused, so Postmark stops retrying"
    assert mail.send(pm.attachment("b.pdf", _pdf("INV-5002")), address=rotated["address"]).status_code == 200


# ------------------------------------------------------------------------------------------------ what arrives

def test_a_pdf_from_an_allowed_sender_becomes_a_document_that_says_how_it_arrived(mail) -> None:
    mail.allow()
    response = mail.send(pm.attachment("INV-5001.pdf", _pdf()), subject="Invoice INV-5001")
    assert response.status_code == 200 and response.json() == {"status": "accepted", "documents": 1, "hold": None}
    drain()
    [document] = _documents(mail.e)
    assert document.original_filename == "INV-5001.pdf" and document.created_by_user_id is None
    mail.e.db.expire_all()
    source = mail.e.db.get(WorkItemSource, document.id)
    assert source.kind == "EMAIL" and source.sender == SENDER and source.subject == "Invoice INV-5001"
    detail = mail.e.get(f"/work-items/{document.id}").json()
    assert detail["source"]["sender"] == SENDER and detail["source"]["subject"] == "Invoice INV-5001"
    [row] = _messages(mail.e)
    assert row.status == "ACCEPTED" and row.work_item_ids == [str(document.id)]
    assert [a["outcome"] for a in mail.view()["messages"][0]["attachments"]] == ["ADDED"]


def test_a_sender_on_an_allowed_domain_is_accepted_and_anyone_else_is_held_with_the_admin_told(mail) -> None:
    mail.allow("supplier.example")  # a domain
    assert mail.send(pm.attachment("a.pdf", _pdf())).json()["status"] == "accepted"
    held = mail.send(pm.attachment("b.pdf", _pdf("INV-5002")), sender="stranger@elsewhere.example")
    assert held.status_code == 200 and held.json() == {"status": "held", "documents": 0, "hold": "SENDER_NOT_ALLOWED"}
    drain()
    assert len(_documents(mail.e)) == 1, "nothing from the stranger was added"
    view = mail.view()
    assert view["held_count"] == 1
    waiting = next(m for m in view["messages"] if m["status"] == "HELD")
    assert waiting["can_approve"] and waiting["from_address"] == "stranger@elsewhere.example"
    notices = mail.e.db.execute(select(Notification).where(Notification.organization_id == mail.e.org)).scalars().all()
    assert any("waiting for approval" in n.title and "stranger@elsewhere.example" in n.message for n in notices)


def test_approving_a_held_message_adds_its_documents_and_discarding_throws_it_away(mail) -> None:
    mail.send(pm.attachment("b.pdf", _pdf("INV-5002")), sender="stranger@elsewhere.example")
    mail.send(pm.attachment("c.pdf", _pdf("INV-5003")), sender="other@elsewhere.example")
    held = [m for m in mail.view()["messages"] if m["status"] == "HELD"]
    assert len(held) == 2
    approved = mail.e.post(f"/inbound-email/messages/{held[0]['id']}/approve").json()
    assert approved["result"] == "accepted" and approved["documents"] == 1
    discarded = mail.e.post(f"/inbound-email/messages/{held[1]['id']}/discard").json()
    assert discarded["message"]["status"] == "DISCARDED"
    drain()
    assert len(_documents(mail.e)) == 1
    assert mail.e.post(f"/inbound-email/messages/{held[1]['id']}/approve").status_code == 409
    assert mail.view()["held_count"] == 0


def test_a_message_delivered_twice_is_counted_once(mail) -> None:
    mail.allow()
    payload = pm.for_address(mail.address, attachments=[pm.attachment("a.pdf", _pdf())], message_id="73e6d360-66eb-11e1-8e72-a8904824019b")
    first = pm.post(mail.e.client, payload)
    second = pm.post(mail.e.client, payload)
    assert first.json()["status"] == "accepted" and second.status_code == 200 and second.json()["status"] == "duplicate"
    drain()
    assert len(_documents(mail.e)) == 1 and len(_messages(mail.e)) == 1


def test_a_zip_attachment_goes_through_the_zip_path_and_a_gstr2b_json_is_set_aside(mail) -> None:
    mail.allow()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("one.pdf", _pdf("INV-6001"))
        zf.writestr("two.pdf", _pdf("INV-6002"))
    gstr2b = json.dumps({"data": {"gstin": "27AAACG1234F1Z5", "rtnprd": "092026", "docdata": {"b2b": []}}}).encode()
    response = mail.send(pm.attachment("batch.zip", buffer.getvalue(), "application/zip"),
                         pm.attachment("GSTR2B.json", gstr2b, "application/json"))
    assert response.json()["status"] == "accepted"
    drain()
    names = sorted(d.original_filename for d in _documents(mail.e))
    assert names == ["one.pdf", "two.pdf"]
    outcomes = {a["name"]: a for a in mail.view()["messages"][0]["attachments"]}
    assert outcomes["batch.zip"]["outcome"] == "ZIP_QUEUED" and "batch_id" in outcomes["batch.zip"]
    assert outcomes["GSTR2B.json"]["outcome"] == "SKIPPED_GSTR2B"
    assert "import it on the GST credit page" in outcomes["GSTR2B.json"]["note"]
    mail.e.db.expire_all()
    sources = mail.e.db.execute(select(WorkItemSource)).scalars().all()
    assert len(sources) == 2 and {s.sender for s in sources} == {SENDER}, "a zip's documents say how they arrived too"


def test_a_message_with_only_a_gstr2b_is_held_with_the_gst_page_words(mail) -> None:
    mail.allow()
    gstr2b = json.dumps({"data": {"gstin": "27AAACG1234F1Z5", "rtnprd": "092026", "docdata": {"b2b": []}}}).encode()
    held = mail.send(pm.attachment("GSTR2B.json", gstr2b, "application/json"))
    assert held.json()["hold"] == "GSTR2B_ONLY"
    [row] = _messages(mail.e)
    assert row.hold_message == "This looks like a GSTR-2B file: import it on the GST credit page."
    assert not mail.view()["messages"][0]["can_approve"]


def test_a_signature_image_is_ignored_and_a_message_with_nothing_readable_is_held(mail) -> None:
    mail.allow()
    logo = pm.attachment("logo.png", b"\x89PNG\r\n\x1a\n" + b"0" * 2000, "image/png", content_id="logo@01")
    held = mail.send(logo)
    assert held.json()["hold"] == "NO_ATTACHMENT"
    assert _messages(mail.e)[0].hold_message == "No attachment Servabo can read."
    none = mail.send()
    assert none.json()["hold"] == "NO_ATTACHMENT"
    # a real invoice beside the signature still arrives, and the signature is not made a document
    accepted = mail.send(logo, pm.attachment("INV.pdf", _pdf("INV-7001")))
    assert accepted.json() == {"status": "accepted", "documents": 1, "hold": None}
    drain()
    assert [d.original_filename for d in _documents(mail.e)] == ["INV.pdf"]


# ------------------------------------------------------------------------------------------------ plan and trial

def test_over_the_plan_limit_the_whole_message_is_held_and_nothing_is_half_added(mail, monkeypatch: pytest.MonkeyPatch) -> None:
    mail.allow()
    real = plan_admission.admit_document
    calls = {"n": 0}

    def limited(db, **kw):
        calls["n"] += 1
        if calls["n"] >= 2:
            raise plan_admission.PlanLimitExceededError("The monthly document limit is used up.", reason="DOCUMENTS",
                                                        limit_key="document.upload", limit=1, requested=2, plan="Developer")
        return real(db, **kw)

    monkeypatch.setattr(plan_admission, "admit_document", limited)
    held = mail.send(pm.attachment("a.pdf", _pdf("INV-8001")), pm.attachment("b.pdf", _pdf("INV-8002")))
    assert held.json() == {"status": "held", "documents": 0, "hold": "OVER_LIMIT"}
    assert _documents(mail.e) == [], "the first file was rolled back with the second"
    monkeypatch.setattr(plan_admission, "admit_document", real)
    row = mail.view()["messages"][0]
    assert row["can_approve"] and "monthly limit" in row["hold_message"]
    approved = mail.e.post(f"/inbound-email/messages/{row['id']}/approve").json()
    assert approved["result"] == "accepted" and approved["documents"] == 2


def test_in_the_read_only_state_after_the_trial_a_message_is_held_with_a_notice(mail, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import trial_service

    mail.allow()

    def ended(db, *, organization_id):
        raise trial_service.TrialEndedError("The free trial has ended.")

    monkeypatch.setattr(trial_service, "assert_trial_active", ended)
    held = mail.send(pm.attachment("a.pdf", _pdf()))
    assert held.json()["hold"] == "TRIAL_ENDED"
    assert _documents(mail.e) == []
    assert "free trial has ended" in mail.view()["messages"][0]["hold_message"]


# ------------------------------------------------------------------------------------------------ roles, scope, sweep

def test_only_workspace_admins_manage_email_in_and_a_message_is_scoped_to_its_workspace(mail) -> None:
    contributor = mail.e.tenant.contributor
    assert mail.e.get("/inbound-email", as_user=contributor).status_code == 403
    assert mail.e.post("/inbound-email/rotate", as_user=contributor).status_code == 403
    mail.send(pm.attachment("a.pdf", _pdf()), sender="stranger@elsewhere.example")
    message_id = mail.view()["messages"][0]["id"]
    foreign = mail.e.tenant.foreign_workspace
    other = mail.e.client.post(f"/api/v1/workspaces/{foreign.id}/inbound-email/messages/{message_id}/approve",
                               headers=mail.e.tenant.owner.headers)
    assert other.status_code in (403, 404)


def test_a_bad_sender_pattern_is_refused_and_a_duplicate_is_a_409(mail) -> None:
    assert mail.e.post("/inbound-email/senders", {"pattern": "not an address"}).status_code == 422
    mail.allow("Supplier.Example")
    assert mail.e.post("/inbound-email/senders", {"pattern": "supplier.example"}).status_code == 409
    [sender] = mail.view()["senders"]
    assert sender["pattern"] == "supplier.example"
    assert mail.e.delete(f"/inbound-email/senders/{sender['id']}").status_code == 204


def test_the_sweep_deletes_old_held_and_discarded_messages_and_their_stored_attachments(mail) -> None:
    from datetime import datetime, timedelta, timezone

    from app.core.storage import get_storage_driver

    mail.send(pm.attachment("a.pdf", _pdf()), sender="stranger@elsewhere.example")
    [row] = _messages(mail.e)
    key = row.attachments[0]["storage_key"]
    assert get_storage_driver().exists(key)
    assert service.sweep(mail.e.db, now=datetime.now(timezone.utc) + timedelta(days=5)) == 0, "not old enough"
    assert service.sweep(mail.e.db, now=datetime.now(timezone.utc) + timedelta(days=45)) == 1
    mail.e.db.commit()
    assert not get_storage_driver().exists(key) and _messages(mail.e) == []


def test_erasing_the_documents_deletes_the_arrival_records_too(mail) -> None:
    """The data map: a message that brought documents in is erased with them (sender address and subject are personal data)."""
    from app.services.compliance import document_content

    mail.allow()
    mail.send(pm.attachment("a.pdf", _pdf()))
    drain()
    [document] = _documents(mail.e)
    document_content.destroy_copies(mail.e.db, [document.id], mode="erase")
    mail.e.db.expire_all()
    assert _messages(mail.e) == []
    assert mail.e.db.get(WorkItemSource, document.id) is None


# ------------------------------------------------------------------------------------------------ the chain

def test_an_emailed_gst_invoice_appears_in_the_gst_books_and_in_helms_ledger(mail) -> None:
    """The point of email-in: a document that arrives this way feeds GST Credit and Helm with no extra work."""
    from app.models.gst import GstMatch
    from app.services.gst import builder as b
    from app.services.gst import vocabulary as gv
    from app.services.helm import snapshot_store
    from app.services.helm import vocabulary as hv
    from app.models.helm import HelmBook
    from tests.security.plans import put_on_plan
    from tests.services.gst.helpers import RECIPIENT, SUPPLIER_A, supplier_invoices

    e = mail.e
    put_on_plan(e.db, e.tenant.organization, "enterprise")
    e.db.commit()
    mail.allow()
    day = date.today().replace(day=1)
    period = f"{day.year:04d}-{day.month:02d}"
    statement = b.to_bytes(b.gstr2b(RECIPIENT, period, {"b2b": [supplier_invoices([b.document("MAIL-1", day, 100_000)])]}))
    sent = e.client.post(f"/api/v1/workspaces/{e.ws}/gst/returns", headers=e.tenant.contributor.headers,
                         files={"file": (f"{period}.json", statement)})
    assert sent.status_code == 200, sent.text

    line = b.item(100_000, 18)
    e.llm.record("MAIL-1", "Invoice", {
        "document_classification": "Invoice", "vendor_name": "Sahyadri Packaging", "invoice_number": "MAIL-1",
        "invoice_date": day.isoformat(), "bill_to": "Meridian Wholesale", "total_amount": f"{100_000 + line['cgst'] + line['sgst']:.2f}",
        "currency": "INR", "payment_terms": "Net 30", "vendor_gstin": SUPPLIER_A, "buyer_gstin": RECIPIENT,
        "subtotal": "100000.00", "cgst_amount": f"{line['cgst']:.2f}", "sgst_amount": f"{line['sgst']:.2f}",
        "tax_amount": f"{line['cgst'] + line['sgst']:.2f}", "supplier_gstin": SUPPLIER_A,
    })
    pdf = make_pdf([["TAX INVOICE MAIL-1", "Vendor: Sahyadri Packaging", "Invoice Number: MAIL-1"]])
    assert mail.send(pm.attachment("MAIL-1.pdf", pdf)).json()["status"] == "accepted"
    drain()

    e.db.expire_all()
    match = next(m for m in e.db.execute(select(GstMatch).where(GstMatch.workspace_id == e.ws)).scalars() if m.doc_number == "MAIL-1")
    assert match.work_item_id is not None and match.status == gv.MATCHED, "the emailed invoice is in the GST books, matched to GSTR-2B"

    book = e.post("/helm/books", {"workspace_id": str(e.ws)}, org=True).json()
    drain(only=[hv.JOB_LEDGER_BUILD])
    snapshot = snapshot_store.take(e.db, e.db.get(HelmBook, book["id"]))
    assert "MAIL-1" in {p.document_number for p in snapshot.payables}, "and in Helm's ledger"


def test_nothing_in_the_logs_names_the_sender_the_token_the_credential_or_the_attachment(mail, caplog: pytest.LogCaptureFixture) -> None:
    import logging

    mail.allow()
    token = mail.address.split("+", 1)[1].split("@", 1)[0]
    with caplog.at_level(logging.DEBUG):
        mail.send(pm.attachment("secret-invoice-name.pdf", _pdf()), subject="Private subject line")
        pm.post(mail.e.client, pm.for_address(mail.address), password="wrong-password-guess")
        pm.post(mail.e.client, pm.for_address(f"{pm.DEFAULT_HASH}+{'1' * 32}@inbound.postmarkapp.com"))
    text = " ".join(f"{r.getMessage()} {getattr(r, 'args', '')}" for r in caplog.records)
    extras = " ".join(str(v) for r in caplog.records for k, v in r.__dict__.items() if k not in {"msg", "args", "message"})
    for secret in (SENDER, token, pm.DEFAULT_PASSWORD, "wrong-password-guess", "secret-invoice-name", "Private subject line"):
        assert secret not in text and secret not in extras, f"{secret!r} reached a log line"


def test_a_workspace_sees_nothing_of_another_workspaces_email_in_not_in_its_organization_and_not_in_another_one(mail) -> None:
    """Workspace A has an address, an allowed sender and a held message. A second workspace of the same organization (B), and a workspace
    of another organization, see none of it, cannot act on it, and mail sent to B's own address lands in B alone."""
    import uuid

    mail.allow("allowed.example")
    mail.send(pm.attachment("a.pdf", _pdf()), sender="stranger@elsewhere.example")
    mine = mail.view()
    assert mine["senders"] and mine["messages"], "workspace A has something to protect"
    sender_id, message_id = mine["senders"][0]["id"], mine["messages"][0]["id"]
    owner = mail.e.tenant.owner.headers

    created = mail.e.post("/workspaces", {"workspace_name": f"Mail B {uuid.uuid4().hex[:6]}"}, org=True)
    assert created.status_code == 201, created.text
    b_id = created.json()["id"]
    b_base = f"/api/v1/workspaces/{b_id}/inbound-email"
    theirs = mail.e.client.get(b_base, headers=owner)
    assert theirs.status_code == 200, theirs.text
    body = theirs.json()
    assert body["address"] != mine["address"], "every workspace has its own address"
    assert body["senders"] == [] and body["messages"] == [], "B lists none of A's senders or messages"
    assert sender_id not in theirs.text and message_id not in theirs.text

    # A's objects through B's URLs, and through another organization's workspace: refused, and nothing changes.
    foreign_base = f"/api/v1/workspaces/{mail.e.tenant.foreign_workspace.id}/inbound-email"
    for base in (b_base, foreign_base):
        assert mail.e.client.post(f"{base}/messages/{message_id}/approve", headers=owner).status_code in (403, 404), base
        assert mail.e.client.post(f"{base}/messages/{message_id}/discard", headers=owner).status_code in (403, 404), base
        assert mail.e.client.delete(f"{base}/senders/{sender_id}", headers=owner).status_code in (403, 404), base
    assert mail.e.client.get(foreign_base, headers=owner).status_code in (403, 404), "another organization's workspace is not readable at all"
    after = mail.view()
    assert [m["id"] for m in after["messages"]] == [message_id] and [x["id"] for x in after["senders"]] == [sender_id]
    assert after["messages"][0]["status"] == mine["messages"][0]["status"], "the held message was neither approved nor discarded"

    # Mail to B's own address belongs to B alone.
    mail.allow(SENDER)  # A allows SENDER; B does not
    sent = mail.send(pm.attachment("b.pdf", _pdf("INV-B")), address=body["address"], sender=SENDER)
    assert sent.status_code == 200, sent.text
    b_after = mail.e.client.get(b_base, headers=owner).json()
    assert len(b_after["messages"]) == 1, "the message arrived in B"
    assert len(mail.view()["messages"]) == 1, "and A's list did not grow"
