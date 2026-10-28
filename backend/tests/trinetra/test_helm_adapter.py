"""Withholding explains a commercial receivable, never a cash settlement."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import uuid

import pytest

from tests.trinetra.test_api import world  # noqa: F401
from tests.trinetra.test_workflows import setup_case
from app.models.trinetra import TrinetraCredit
from app.services.helm import hands


def confirmed_case(client, tenant, world):
    url, _, case = setup_case(client, tenant, world)
    body = {
        "revision": case["revision"],
        "confirm_receivable": True,
        "reason": "Reviewed separate customer advice and accounting entry.",
        "evidence": [
            {
                "work_item_id": str(world[1].id),
                "kind": "ACCOUNTING_RECORD",
                "amount": "2000",
            },
            {
                "work_item_id": str(world[2].id),
                "kind": "DEDUCTOR_ADVICE",
                "amount": "2000",
            },
        ],
    }
    path = url + "/credits/" + case["id"]
    response = client.post(path + "/review", headers=tenant.owner.headers, json=body)
    assert response.status_code == 200, response.text
    return path, response.json(), body


def test_confirmed_withholding_does_not_require_government_posting(
    client, tenant, world, db_session
):
    path, case, body = confirmed_case(client, tenant, world)
    detail = client.get(path, headers=tenant.owner.headers).json()
    assert detail["status"] == "PENDING_REPORT"
    assert detail["cash_projection"]["reviewed_withholding_micros"] == "2000000000"
    assert detail["cash_projection"]["cash_received_micros"] is None
    assert detail["cash_projection"]["unexplained_micros"] is None
    # Freshness failure must not make a stale deduction look verified.
    world[2].updated_at = datetime.now(timezone.utc) + timedelta(seconds=1)
    db_session.commit()
    detail = client.get(path, headers=tenant.owner.headers).json()
    assert detail["cash_projection"]["reviewed_withholding_micros"] is None


def test_projection_refuses_conflicting_or_missing_evidence(client, tenant, world):
    path, case, body = confirmed_case(client, tenant, world)
    body["revision"] = case["revision"]
    body["evidence"][0]["amount"] = "1999"
    assert (
        client.post(
            path + "/review", headers=tenant.owner.headers, json=body
        ).status_code
        == 422
    )
    body["evidence"] = body["evidence"][1:]
    assert (
        client.post(
            path + "/review", headers=tenant.owner.headers, json=body
        ).status_code
        == 422
    )


def test_helm_never_sends_gross_reminder_for_reviewed_withholding(
    client, tenant, world, db_session, monkeypatch
):
    _, case, _ = confirmed_case(client, tenant, world)
    sent = []
    monkeypatch.setattr(hands, "send_mail", lambda *a, **k: sent.append(k))
    action = SimpleNamespace(
        organization_id=tenant.organization.id,
        workspace_id=tenant.workspace.id,
        work_item_id=world[1].id,
        counterparty_key=None,
        currency="INR",
        amount_micros=118000000000,
        params={"to": "synthetic@example.invalid"},
    )
    with pytest.raises(hands.HandError, match="withholding"):
        hands.send_reminder(
            db_session, action=action, book=SimpleNamespace(kind="WORKSPACE")
        )
    assert sent == []
    # A stale confirmation also requires review, rather than silently resuming gross chasing.
    world[2].updated_at = datetime.now(timezone.utc) + timedelta(seconds=1)
    db_session.commit()
    with pytest.raises(hands.HandError, match="withholding"):
        hands.send_reminder(
            db_session, action=action, book=SimpleNamespace(kind="WORKSPACE")
        )
    assert sent == []
    # Explicit withdrawal releases the hold, never a mutation of Helm settlement state.
    row = db_session.get(TrinetraCredit, uuid.UUID(case["id"]))
    row.state = "WITHDRAWN"
    db_session.flush()
    hands.send_reminder(
        db_session, action=action, book=SimpleNamespace(kind="WORKSPACE")
    )
    assert len(sent) == 1


def test_helm_projection_is_scoped_and_keeps_commercial_amount(
    client, tenant, world, db_session
):
    from app.services.trinetra.helm_adapter import annotate
    from app.services.helm.service import Viewer

    _, case, _ = confirmed_case(client, tenant, world)
    who = Viewer(
        tenant.organization.id,
        tenant.owner.user.id,
        "OWNER",
        frozenset([tenant.workspace.id]),
    )
    original = {
        "readable": True,
        "work_item_id": str(world[1].id),
        "workspace_id": str(tenant.workspace.id),
        "kind": "PAYMENT_EXPECTED",
        "currency": "INR",
        "amount_micros": 118000000000,
    }
    result = annotate(db_session, who, [dict(original)])[0]
    assert result["amount_micros"] == original["amount_micros"]
    assert result["withholding_review"]["reviewed_micros"] == "2000000000"
    assert result["withholding_review"]["case_id"] == case["id"]
    hidden = Viewer(who.organization_id, who.user_id, "OWNER", frozenset())
    assert "withholding_review" not in annotate(db_session, hidden, [dict(original)])[0]
    outsider = Viewer(uuid.uuid4(), who.user_id, "OWNER", who.readable)
    assert (
        "withholding_review" not in annotate(db_session, outsider, [dict(original)])[0]
    )


# --- Final 2T, Phase 1.1: Helm chases the cash still owed, never the tax the customer withheld -------------


def test_the_snapshot_learns_the_reviewed_withholding_even_when_trinetra_is_off(
    client, tenant, world, db_session, monkeypatch
):
    from app.core.config import settings
    from app.services.trinetra.helm_adapter import withholding_for

    _, case, _ = confirmed_case(client, tenant, world)
    ids = [world[1].id]
    found = withholding_for(db_session, tenant.organization.id, ids)[world[1].id]
    assert (found.case_id, found.reviewed_micros) == (case["id"], 2_000_000_000)
    # The safety property does not depend on the mode or the plan: switched off, the same figure still stands.
    monkeypatch.setattr(settings, "TRINETRA_LIVE_ENABLED", False)
    assert withholding_for(db_session, tenant.organization.id, ids)[world[1].id].reviewed_micros == 2_000_000_000
    # Stale evidence keeps the hold but the amount becomes unknown (never "nothing withheld").
    world[2].updated_at = datetime.now(timezone.utc) + timedelta(seconds=1)
    db_session.commit()
    stale = withholding_for(db_session, tenant.organization.id, ids)[world[1].id]
    assert stale.case_id == case["id"] and stale.reviewed_micros is None
    # Withdrawing releases it.
    db_session.get(TrinetraCredit, uuid.UUID(case["id"])).state = "WITHDRAWN"
    db_session.flush()
    assert withholding_for(db_session, tenant.organization.id, ids) == {}


def test_the_reminder_hand_allows_the_net_cash_and_refuses_the_withheld_tax(
    client, tenant, world, db_session, monkeypatch
):
    _, case, _ = confirmed_case(client, tenant, world)
    sent = []
    monkeypatch.setattr(hands, "send_mail", lambda *a, **k: sent.append(k) or True)

    def action(amount):
        return SimpleNamespace(
            organization_id=tenant.organization.id,
            workspace_id=tenant.workspace.id,
            work_item_id=world[1].id,
            counterparty_key=None,
            currency="INR",
            amount_micros=amount,
            params={"to": "synthetic@example.invalid"},
        )

    book = SimpleNamespace(kind="WORKSPACE")
    # The invoice is for 1,18,000 with 2,000 withheld: asking for the 1,16,000 still owed is fine.
    hands.send_reminder(db_session, action=action(116_000_000_000), book=book)
    assert len(sent) == 1
    # Asking for the gross, which includes the withheld tax, is refused.
    with pytest.raises(hands.HandError, match="withholding"):
        hands.send_reminder(db_session, action=action(118_000_000_000), book=book)
    assert len(sent) == 1


def test_the_snapshot_marks_the_receivable_and_a_stale_confirmation_holds_the_reminder(
    client, tenant, world, db_session
):
    from types import SimpleNamespace as NS

    from app.services.helm import snapshot as snap
    from app.services.helm import snapshot_store

    _, case, _ = confirmed_case(client, tenant, world)

    def receivable(work_item):
        return snap.Receivable(
            promise_id="p1", work_item_id=str(work_item.id), workspace_id=str(tenant.workspace.id),
            document="inv.pdf", document_number="TR-1", counterparty_key=None, counterparty_name="Customer",
            currency="INR", amount_micros=118_000_000_000, invoice_date=None, due_date=None, status="OPEN",
            paid_on=None, confidence="VERIFIED")

    book = NS(organization_id=tenant.organization.id)
    [marked] = snapshot_store._with_withholding(db_session, book, [receivable(world[1])])
    assert (marked.withheld_micros, marked.withholding_case_id, marked.withholding_hold) == (
        2_000_000_000, case["id"], None)
    assert marked.cash_due_micros == 116_000_000_000 and not marked.reminder_held
    # An invoice with no withholding is untouched.
    [plain] = snapshot_store._with_withholding(db_session, book, [receivable(world[2])])
    assert plain.withholding_case_id is None and plain.withheld_micros == 0
    # Stale evidence: the amount is not known, so the reminder is held, not sent for the gross.
    world[2].updated_at = datetime.now(timezone.utc) + timedelta(seconds=1)
    db_session.commit()
    [stale] = snapshot_store._with_withholding(db_session, book, [receivable(world[1])])
    assert stale.withholding_hold == "UNKNOWN_AMOUNT" and stale.reminder_held
