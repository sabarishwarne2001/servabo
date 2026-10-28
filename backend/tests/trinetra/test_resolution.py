"""Resolution end to end (Final 2T, Phase 6; N-206 to N-208): authorized inquiries, approval chains, the closure ledger and the
measured cycle. A person presses Send; nothing is sent on its own; a reply attaches only to the case it answers."""

import hashlib
import io
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.core.config import settings
from app.models.helm import HelmBook, HelmCounterparty
from app.models.trinetra import TrinetraApproval, TrinetraCredit, TrinetraInquiry, TrinetraOutcome
from app.services.helm import hands
from app.services.helm import vocabulary as hv
from app.services.trinetra import directory, inquiries
from tests.engines.conftest import make_pdf
from tests.security.plans import put_on_plan
from tests.trinetra.test_api import world  # noqa: F401
from tests.trinetra.test_money_model import HEAD, allocate, decide, get, statement
from tests.trinetra.test_workflows import setup_case

ADDRESS = "accounts@customer.example"


@pytest.fixture()
def mailbox(monkeypatch):
    sent = []

    def fake_send(db, *, organization_id, workspace_id, to, subject, html_body, text_body):
        sent.append({"to": to, "subject": subject, "html": html_body, "text": text_body})
        return {"sent_to": to}

    monkeypatch.setattr(hands, "send_mail", fake_send)
    monkeypatch.setattr(hands, "email_destination", lambda db, **kw: (True, "Email."))
    return sent


def customer(db, tenant, name="Synthetic deductor", source=hv.CONTACT_SOURCE_PERSON, email=ADDRESS):
    book = db.query(HelmBook).filter_by(workspace_id=tenant.workspace.id).first()
    if book is None:
        book = HelmBook(organization_id=tenant.organization.id, workspace_id=tenant.workspace.id, kind=hv.BOOK_WORKSPACE,
                        name="Engineering", status=hv.BOOK_ACTIVE)
        db.add(book)
        db.flush()
    row = HelmCounterparty(organization_id=tenant.organization.id, book_id=book.id, key=directory.name_key(name), role="CUSTOMER",
                           display_name=name, contact_email=email, contact_source=source)
    db.add(row)
    db.commit()
    return row


def draft(client, tenant, url, case, **more):
    return client.post(url + f"/credits/{case['id']}/inquiries", headers=tenant.owner.headers, json={"document_kind": "CERTIFICATE", **more})


def step(client, tenant, url, inquiry, what, **body):
    return client.post(url + f"/inquiries/{inquiry['id']}/{what}", headers=tenant.owner.headers, json=body)


# --- authorized inquiries ---------------------------------------------------------------------------------------------------


def test_only_a_confirmed_contact_is_ever_a_recipient(client, tenant, world, db_session, mailbox):
    url, body, case = setup_case(client, tenant, world)
    made = draft(client, tenant, url, case)
    assert made.status_code == 200 and made.json()["status"] == "DRAFT"
    none = step(client, tenant, url, made.json(), "approve")
    assert none.status_code == 422 and "TRINETRA_NO_CONFIRMED_CONTACT" in none.text
    customer(db_session, tenant, source=hv.CONTACT_SOURCE_DOCUMENT)                # read from a document, not confirmed
    learned = step(client, tenant, url, made.json(), "approve")
    assert learned.status_code == 422 and mailbox == []


def test_a_person_approves_then_presses_send_and_the_email_carries_a_secure_link(client, tenant, world, db_session, mailbox):
    url, body, case = setup_case(client, tenant, world)
    customer(db_session, tenant)
    made = draft(client, tenant, url, case, subject="Please help us match invoice TR-1", body="We are matching our records.").json()
    # Nothing leaves by itself, a viewer cannot, and an unapproved draft cannot be sent.
    assert client.post(url + f"/inquiries/{made['id']}/send", headers=tenant.viewer.headers, json={}).status_code == 403
    assert step(client, tenant, url, made, "send").status_code == 409 and mailbox == []
    approved = step(client, tenant, url, made, "approve")
    assert approved.status_code == 200 and approved.json()["status"] == "APPROVED" and approved.json()["recipient_masked"] == "a***@customer.example"
    assert approved.json()["approved_by"] == str(tenant.owner.user.id) and mailbox == []
    sent = step(client, tenant, url, made, "send")
    assert sent.status_code == 200, sent.text
    out = sent.json()
    assert out["status"] == "SENT" and out["sent_by"] == str(tenant.owner.user.id) and out["delivery_state"] == "SENT"
    [mail] = mailbox
    assert mail["to"] == ADDRESS and "TR-1" in mail["subject"]
    link = next(line for line in mail["text"].splitlines() if "/request/" in line)
    assert link.startswith(settings.FRONTEND_URL.rstrip("/") + "/request/")
    assert "ABCDE1234F" not in mail["text"] + mail["html"] and "ABCD12345E" not in mail["text"] + mail["html"]   # no PAN, no TAN
    assert "2,000" in mail["text"] and "does not suggest that anything was done wrongly" in mail["text"]
    again = step(client, tenant, url, made, "send")
    assert again.status_code == 409 and len(mailbox) == 1
    actions = [e["action"] for e in get(client, tenant, url, case)["events"]]
    assert "INQUIRY_SENT" in actions
    assert ADDRESS not in str(get(client, tenant, url, case)) and ADDRESS not in out.get("body", "")           # the address is not stored


def test_one_inquiry_per_case_per_week_unless_a_person_overrides_with_a_reason(client, tenant, world, db_session, mailbox):
    url, body, case = setup_case(client, tenant, world)
    customer(db_session, tenant)
    first = draft(client, tenant, url, case).json()
    step(client, tenant, url, first, "approve")
    assert step(client, tenant, url, first, "send").status_code == 200
    second = draft(client, tenant, url, case).json()
    step(client, tenant, url, second, "approve")
    soon = step(client, tenant, url, second, "send")
    assert soon.status_code == 409 and "TRINETRA_INQUIRY_TOO_SOON" in soon.text and len(mailbox) == 1
    ok = step(client, tenant, url, second, "send", override_reason="The first email bounced; the contact was corrected.")
    assert ok.status_code == 200 and ok.json()["override_reason"].startswith("The first email bounced") and len(mailbox) == 2


def test_the_monthly_allowance_refuses_the_next_send_and_names_the_plan_that_raises_it(client, tenant, world, db_session, mailbox):
    url, body, case = setup_case(client, tenant, world)
    customer(db_session, tenant)
    row = db_session.query(TrinetraCredit).one()
    now = datetime.now(timezone.utc)
    for n in range(50):                                               # the Business allowance is 50 a month
        db_session.add(TrinetraInquiry(organization_id=tenant.organization.id, workspace_id=tenant.workspace.id, credit_id=row.id,
                                       document_kind="CERTIFICATE", subject="s", body="b", status="SENT", sent_at=now - timedelta(days=8)))
    db_session.commit()
    allowance = client.get(url + "/inquiries/allowance", headers=tenant.viewer.headers).json()
    assert allowance == {**allowance, "used": 50, "limit": 50}
    made = draft(client, tenant, url, case).json()
    step(client, tenant, url, made, "approve")
    refused = step(client, tenant, url, made, "send")
    assert refused.status_code == 409 and "TRINETRA_INQUIRY_ALLOWANCE" in refused.text and "Enterprise" in refused.text and mailbox == []


def test_a_failed_mail_is_a_failed_inquiry_with_its_link_revoked_and_it_can_be_retried(client, tenant, world, db_session, monkeypatch):
    url, body, case = setup_case(client, tenant, world)
    customer(db_session, tenant)
    monkeypatch.setattr(hands, "email_destination", lambda db, **kw: (True, "ok"))

    def broken(db, **kw):
        raise hands.HandError("HELM_MAIL_FAILED", "The mail server did not accept the message: refused")

    monkeypatch.setattr(hands, "send_mail", broken)
    made = draft(client, tenant, url, case).json()
    step(client, tenant, url, made, "approve")
    failed = step(client, tenant, url, made, "send")
    assert failed.status_code == 200 and failed.json()["status"] == "FAILED" and "refused" in failed.json()["delivery_detail"]
    monkeypatch.setattr(hands, "send_mail", lambda db, **kw: {"sent_to": "x"})
    retried = step(client, tenant, url, made, "send")
    assert retried.status_code == 200 and retried.json()["status"] == "SENT"


def test_a_reply_through_the_link_attaches_to_that_case_only_and_a_revoked_link_is_refused(client, tenant, world, db_session, mailbox):
    url, body, case = setup_case(client, tenant, world)
    customer(db_session, tenant)
    made = draft(client, tenant, url, case, document_kind="DEDUCTOR_ADVICE").json()
    step(client, tenant, url, made, "approve")
    step(client, tenant, url, made, "send")
    link = next(line for line in mailbox[0]["text"].splitlines() if "/request/" in line)
    token = link.rsplit("/", 1)[1]
    public = f"/api/v1/public/document-requests/{token}"
    assert client.get(public).status_code == 200
    pdf = make_pdf([["Withholding advice for invoice TR-1"]])
    uploaded = client.post(public, files={"file": ("advice.pdf", pdf, "application/pdf")})
    assert uploaded.status_code == 200, uploaded.text
    detail = get(client, tenant, url, case)
    evidence = [e for e in detail["review"]["evidence"] if e.get("from_inquiry") == made["id"]]
    assert len(evidence) == 1 and evidence[0]["kind"] == "DEDUCTOR_ADVICE" and evidence[0]["amount_micros"] is None
    assert "INQUIRY_REPLY" in [e["action"] for e in detail["events"]]
    row = db_session.get(TrinetraInquiry, uuid.UUID(made["id"]))
    db_session.refresh(row)
    assert row.status == "REPLIED" and str(row.reply_work_item_id) == evidence[0]["work_item_id"]
    assert client.post(public, files={"file": ("again.pdf", pdf, "application/pdf")}).status_code == 410       # single use
    # A second case: its own link, its own reply; another case's evidence is untouched.
    other_invoice = world[2]
    other = client.post(url + "/credits", headers=tenant.owner.headers,
                        json={**body, "work_item_id": str(other_invoice.id), "reference": "TR-2"}).json()
    again = draft(client, tenant, url, other).json()
    step(client, tenant, url, again, "approve")
    step(client, tenant, url, again, "send")
    revoked_token = next(line for line in mailbox[1]["text"].splitlines() if "/request/" in line).rsplit("/", 1)[1]
    assert step(client, tenant, url, again, "withdraw").status_code == 200
    assert client.post(f"/api/v1/public/document-requests/{revoked_token}", files={"file": ("x.pdf", pdf, "application/pdf")}).status_code == 410
    assert get(client, tenant, url, other)["review"]["evidence"] == []


def test_a_hostile_customer_name_is_escaped_in_the_email(client, tenant, world, db_session, mailbox):
    url, body, case = setup_case(client, tenant, world)
    row = db_session.query(TrinetraCredit).one()
    row.counterparty = '<script>alert(1)</script> Ltd'
    db_session.commit()
    customer(db_session, tenant, name=row.counterparty)
    made = draft(client, tenant, url, {"id": str(row.id)}).json()
    step(client, tenant, url, made, "approve")
    assert step(client, tenant, url, made, "send").status_code == 200
    assert "<script>" not in mailbox[0]["html"] and "&lt;script&gt;" in mailbox[0]["html"]


# --- approval chains (Enterprise) -----------------------------------------------------------------------------------------


def posted_case(client, tenant, world):
    url, body, case = setup_case(client, tenant, world)
    snap = statement(client, tenant, url, body, ["ABCD12345E,2000.00,r0,194C,15-Jun-2025,F,FY 2025-26 / AY 2026-27"])
    done = decide(client, tenant, url, case, "ALLOCATE", allocations=[allocate(snap, 0, "2000")])
    assert done.status_code == 200
    return url, body, done.json(), snap


def set_policy(client, tenant, **more):
    return client.put(f"/api/v1/organizations/{tenant.organization.id}/trinetra/policy", headers=tenant.owner.headers,
                      json={"threshold": "1000", "actions": ["CA_REVIEWED"], "approver_role": "OWNER", **more})


def test_business_has_no_chain_and_closes_simply(client, tenant, world, db_session):
    url, body, case, snap = posted_case(client, tenant, world)
    assert set_policy(client, tenant).status_code == 402                     # approval chains are Enterprise
    ca = decide(client, tenant, url, case, "CA_REVIEWED", reason="Accountant reviewed the posting.")
    assert ca.status_code == 200 and ca.json()["review_state"] == "CA_REVIEWED"


def test_an_enterprise_closure_above_the_threshold_needs_a_named_role_and_a_different_person(client, tenant, world, db_session):
    put_on_plan(db_session, tenant.organization, "enterprise")
    url, body, case, snap = posted_case(client, tenant, world)
    assert set_policy(client, tenant, threshold="1000", approver_role="OWNER").status_code == 200
    asked = decide(client, tenant, url, case, "CA_REVIEWED", reason="Accountant reviewed the posting.")
    assert asked.status_code == 202 and asked.json()["approval_required"] is True
    approval = asked.json()["approval"]
    assert approval["status"] == "PENDING" and approval["approver_role"] == "OWNER"
    assert db_session.query(TrinetraCredit).one().state == "OPEN"             # nothing closed yet
    url_a = url + f"/approvals/{approval['id']}"
    # The one who asked cannot approve their own closure; a workspace admin who is not the owner cannot either.
    assert client.post(url_a + "/approve", headers=tenant.owner.headers, json={"reason": "I approve my own request."}).status_code == 409
    assert client.post(url_a + "/approve", headers=tenant.ws_admin.headers, json={"reason": "Reviewed and approved it."}).status_code == 403
    assert client.post(url_a + "/approve", headers=tenant.viewer.headers, json={"reason": "Reviewed and approved it."}).status_code == 403
    # An organization admin is not the named role (OWNER) either.
    assert client.post(url_a + "/approve", headers=tenant.org_admin.headers, json={"reason": "Reviewed and approved it."}).status_code == 403
    # A different OWNER approves: it closes, with the approval in the history.
    from app.models.organization import OrganizationMember, OrganizationRole

    tenant.org_admin  # the second owner
    member = db_session.query(OrganizationMember).filter_by(organization_id=tenant.organization.id, user_id=tenant.org_admin.user.id).one()
    member.role = OrganizationRole.OWNER
    db_session.commit()
    ok = client.post(url_a + "/approve", headers=tenant.org_admin.headers, json={"reason": "Reviewed and approved it."})
    assert ok.status_code == 200, ok.text
    assert ok.json()["review_state"] == "CA_REVIEWED"
    events = [e["action"] for e in get(client, tenant, url, case)["events"]]
    assert events[:2] == ["CA_REVIEWED", "APPROVAL_REQUESTED"]
    done = client.get(url + "/approvals?status=APPROVED", headers=tenant.viewer.headers).json()["items"]
    assert [a["id"] for a in done] == [approval["id"]]


def test_below_the_threshold_or_for_another_action_the_simple_rule_applies(client, tenant, world, db_session):
    put_on_plan(db_session, tenant.organization, "enterprise")
    url, body, case, snap = posted_case(client, tenant, world)
    assert set_policy(client, tenant, threshold="5000").status_code == 200                      # 2,000 is below 5,000
    assert decide(client, tenant, url, case, "CA_REVIEWED", reason="Accountant reviewed the posting.").status_code in (200, 409)
    explained = decide(client, tenant, url, case, "EXPLAINED", reason="Explained: the customer deducted on a later invoice.")
    assert explained.status_code == 200                                                       # EXPLAINED is not in this policy


def test_a_case_that_moved_after_the_request_makes_the_approval_stale(client, tenant, world, db_session):
    put_on_plan(db_session, tenant.organization, "enterprise")
    url, body, case, snap = posted_case(client, tenant, world)
    set_policy(client, tenant, threshold="1000", approver_role="ADMIN")
    asked = decide(client, tenant, url, case, "CA_REVIEWED", reason="Accountant reviewed the posting.").json()["approval"]
    # Someone annotates the case: it moves on to a new revision underneath the pending approval.
    moved = decide(client, tenant, url, get(client, tenant, url, case), "ANNOTATE", note="The advice arrived.", reason="Added a note for the file.")
    assert moved.status_code == 200
    stale = client.post(url + f"/approvals/{asked['id']}/approve", headers=tenant.org_admin.headers, json={"reason": "Reviewed and approved it."})
    assert stale.status_code == 409 and "changed" in stale.text
    assert db_session.query(TrinetraApproval).one().status == "STALE"
    assert db_session.query(TrinetraCredit).one().state == "OPEN"


def test_a_rejected_approval_closes_nothing(client, tenant, world, db_session):
    put_on_plan(db_session, tenant.organization, "enterprise")
    url, body, case, snap = posted_case(client, tenant, world)
    set_policy(client, tenant, threshold="1000", approver_role="ADMIN")
    asked = decide(client, tenant, url, case, "CA_REVIEWED", reason="Accountant reviewed the posting.").json()["approval"]
    no = client.post(url + f"/approvals/{asked['id']}/reject", headers=tenant.org_admin.headers, json={"reason": "The advice does not match yet."})
    assert no.status_code == 200 and no.json()["status"] == "REJECTED"
    assert db_session.query(TrinetraCredit).one().state == "OPEN"


# --- the closure ledger and the measured cycle -----------------------------------------------------------------------------


def test_the_closure_ledger_adds_up_over_time_without_double_counting_and_is_never_cash(client, tenant, world, db_session):
    url, body, case = setup_case(client, tenant, world)
    first = statement(client, tenant, url, body, ["MUMB54321K,10.00,x0,194C,15-Jun-2025,F,FY 2025-26 / AY 2026-27"])   # the TDS is not there yet
    gap = get(client, tenant, url, case)
    assert gap["status"] == "POSSIBLE_MISSING_POSTING" and first
    second = statement(client, tenant, url, body, ["ABCD12345E,2000.00,y0,194C,15-Jun-2025,F,FY 2025-26 / AY 2026-27"])
    # The first import had a gap for this case; the second shows the posting.
    done = decide(client, tenant, url, get(client, tenant, url, case), "ALLOCATE", allocations=[allocate(second, 0, "2000")])
    assert done.status_code == 200
    ca = decide(client, tenant, url, done.json(), "CA_REVIEWED", reason="Accountant confirmed it in the new statement.")
    assert ca.status_code == 200
    summary = client.get(url + "/summary", headers=tenant.owner.headers).json()["outcomes"]
    assert summary["now_visible_total_micros"] == "2000000000" and summary["now_visible_cases"] == 1
    assert summary["now_visible_this_month_micros"] == "2000000000" and "NOT cash" in summary["ledger_note"]
    # Closing again on the same snapshot adds nothing (the dedupe key); a later import does not remove it either.
    reopened = decide(client, tenant, url, ca.json(), "REOPEN", reason="Reopened to check the amount again.")
    again = decide(client, tenant, url, reopened.json(), "CA_REVIEWED", reason="Accountant confirmed it again.")
    assert again.status_code == 200 and db_session.query(TrinetraOutcome).count() == 1
    later = statement(client, tenant, url, body, ["ABCD12345E,2000.00,z0,194C,15-Jun-2025,F,FY 2025-26 / AY 2026-27",
                                                  "MUMB54321K,5.00,z1,194C,15-Jun-2025,F,FY 2025-26 / AY 2026-27"])
    assert later
    ledger = client.get(url + "/outcomes", headers=tenant.owner.headers).json()
    assert ledger["now_visible_total_micros"] == "2000000000" and ledger["months"][0]["amount_micros"] == "2000000000"
    assert "NOT cash" in ledger["ledger_note"]


def test_a_posting_that_was_never_a_gap_is_recorded_but_not_counted_as_now_visible(client, tenant, world, db_session):
    url, body, case, snap = posted_case(client, tenant, world)
    decide(client, tenant, url, case, "CA_REVIEWED", reason="Accountant reviewed the posting.")
    row = db_session.query(TrinetraOutcome).one()
    assert row.was_gap is False and row.amount_micros == 2_000_000_000
    assert client.get(url + "/summary", headers=tenant.owner.headers).json()["outcomes"]["now_visible_total_micros"] == "0"


def test_the_cycle_time_is_measured_from_the_history_and_kept_apart_from_typed_minutes(client, tenant, world, db_session):
    url, body, case, snap = posted_case(client, tenant, world)
    decide(client, tenant, url, case, "CA_REVIEWED", reason="Accountant reviewed the posting.", review_minutes=30)
    from app.models.trinetra import TrinetraDecision

    first = db_session.query(TrinetraDecision).filter_by(revision=1).one()
    first.created_at = datetime.now(timezone.utc) - timedelta(days=10)
    db_session.commit()
    out = client.get(url + "/summary", headers=tenant.owner.headers).json()["outcomes"]
    assert out["measured_cycle_cases"] == 1 and 9.9 <= out["measured_cycle_days_median"] <= 10.1
    assert out["review_minutes"] == 30 and "typed in" in out["cycle_note"]
