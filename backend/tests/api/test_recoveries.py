"""Recoveries (Final session 2A, Phase 6; N-191): money issues from Found to Being fixed to Verified.

Real Postgres. The engines' rows are planted the way the engines leave them (the same helpers as the value receipt's
tests), then the issues are swept and the routes called:

* each kind's closure rule, and that a click alone never closes an issue as money;
* "Not money" is recorded and never counted;
* the outcome ledger counts every outcome once, for every pair of engines that could both claim it;
* an outcome whose evidence is undone is withdrawn and the issue reopened;
* the plan gate (Starter sees a preview) and isolation through a second workspace and another organization.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import delete, select

from app.models.gst import GstMatch
from app.models.helm import HelmPromise, HelmValueEvent
from app.models.procurement import ProcurementCase, ProcurementCaseLine
from app.models.radar import AnomalyFinding
from app.models.recovery import RecoveryIssue, RecoveryOutcome
from app.services.helm import value as helm_value
from app.services.helm import vocabulary as hv
from app.services.recoveries import adapters, ledger, service
from app.services.recoveries import vocabulary as v
from tests.security.plans import put_on_plan
from tests.services.test_value_receipt import _book, _duplicate, _gst_book, _overcharge

API = "/api/v1"
M = 1_000_000
TODAY = date.today()


def _promise(db, tenant, work_item_id, *, amount=10_000, currency="INR", due=None, settlement=None, credited=0,
             credit=None, details=None, terms=None, status=hv.STATUS_OPEN):
    workspace = tenant.workspace
    row = HelmPromise(
        organization_id=tenant.organization.id, workspace_id=workspace.id, work_item_id=work_item_id,
        source_key=f"t-{uuid.uuid4().hex}", kind=hv.KIND_PAYMENT_DUE, direction=hv.DIRECTION_WE_OWE,
        counterparty_name="Nilgiri", currency=currency, amount_micros=amount * M, due_date=due or TODAY + timedelta(days=20),
        status=status, confidence=hv.CONFIDENCE_EXTRACTED, title=f"Pay {amount} to Nilgiri", terms=terms or {},
        evidence=[], fulfilments=[credit] if credit else [],
        details={"gross_micros": amount * M, "credited_micros": credited * M,
                 "settlement": settlement or {"state": hv.SETTLEMENT_UNPAID}, **(details or {})},
        engine_version="t", content_hash=uuid.uuid4().hex)
    db.add(row)
    db.flush()
    return row


def _business(db_session, tenant):
    put_on_plan(db_session, tenant.organization, "business")
    tenant.workspace.currency = "INR"
    db_session.flush()


def _sweep(db, tenant, **kw):
    counts = service.sweep(db, tenant.workspace, **kw)
    db.flush()
    return counts


def _issue(db, tenant, kind, work_item_id=None) -> RecoveryIssue:
    stmt = select(RecoveryIssue).where(RecoveryIssue.workspace_id == tenant.workspace.id, RecoveryIssue.kind == kind)
    if work_item_id:
        stmt = stmt.where(RecoveryIssue.work_item_id == work_item_id)
    return db.execute(stmt).scalar_one()


def _counted(db, tenant):
    return ledger.totals(ledger.rows(db, [tenant.workspace.id]))


def _waiting_to_matched(db, tenant, work_item_id, *, status="MATCHED", period="2026-11"):
    row = db.execute(select(GstMatch).where(GstMatch.work_item_id == work_item_id)).scalar_one()
    data = {c.name: getattr(row, c.name) for c in GstMatch.__table__.columns if c.name not in ("id", "computed_at")}
    db.execute(delete(GstMatch).where(GstMatch.id == row.id))   # the engine rebuilds its rows
    db.add(GstMatch(**{**data, "status": status, "period_first_seen": period, "reported_late": True}))
    db.flush()


# ------------------------------------------------------------------------------------------------------------ GST


def test_gst_credit_is_verified_only_when_a_later_gstr2b_carries_the_invoice(db_session, tenant):
    _business(db_session, tenant)
    item = _gst_book(db_session, tenant, tenant.workspace, "W-1", 1000, "WAITING_FOR_SUPPLIER")
    assert _sweep(db_session, tenant)["found"] == 1
    issue = _issue(db_session, tenant, v.GST_CREDIT)
    assert issue.state == v.FOUND and issue.exposure_micros == 180 * M and issue.currency == "INR"
    assert issue.due_basis == "Section 16(4) time limit" and issue.due_date.month == 11 and issue.due_date.day == 30

    # A click never verifies: an owner makes it Being fixed, and nothing is counted.
    service.assign(db_session, issue, owner_user_id=tenant.owner.user.id, actor_id=tenant.owner.user.id)
    _sweep(db_session, tenant)
    assert issue.state == v.BEING_FIXED and _counted(db_session, tenant) == {}

    _waiting_to_matched(db_session, tenant, item.id)
    counts = _sweep(db_session, tenant)
    assert counts["verified"] == 1 and issue.state == v.VERIFIED
    assert "GSTR-2B for 2026-11" in issue.close_reason
    assert _counted(db_session, tenant) == {"INR": 180 * M}
    assert _sweep(db_session, tenant)["verified"] == 0 and _counted(db_session, tenant) == {"INR": 180 * M}  # once


def test_gst_outcome_is_withdrawn_when_the_return_that_carried_it_goes(db_session, tenant):
    _business(db_session, tenant)
    item = _gst_book(db_session, tenant, tenant.workspace, "W-2", 2000, "WAITING_FOR_SUPPLIER")
    _sweep(db_session, tenant)
    _waiting_to_matched(db_session, tenant, item.id)
    _sweep(db_session, tenant)
    _waiting_to_matched(db_session, tenant, item.id, status="WAITING_FOR_SUPPLIER", period=None)
    counts = _sweep(db_session, tenant)
    issue = _issue(db_session, tenant, v.GST_CREDIT)
    assert counts["reopened"] == 1 and issue.state == v.FOUND and _counted(db_session, tenant) == {}
    assert db_session.execute(select(RecoveryOutcome.withdrawn_at)).scalar_one() is not None


def test_a_gst_invoice_cancelled_by_a_credit_note_is_verified_without_money(db_session, tenant):
    _business(db_session, tenant)
    item = _gst_book(db_session, tenant, tenant.workspace, "W-3", 1000, "WAITING_FOR_SUPPLIER")
    _sweep(db_session, tenant)
    _promise(db_session, tenant, item.id, amount=1180, credited=1180,
             credit={"kind": "CREDIT", "document": "CN-1", "on": TODAY.isoformat()})
    _sweep(db_session, tenant)
    issue = _issue(db_session, tenant, v.GST_CREDIT)
    assert issue.state == v.VERIFIED and "credit note" in issue.close_reason and _counted(db_session, tenant) == {}


# ------------------------------------------------------------------------------------------------------------ duplicates


def _dup_item(db, tenant, number, total=5_000, status="OPEN"):
    _duplicate(db, tenant, tenant.workspace, number, total, "INR", status=status)
    return db.execute(select(AnomalyFinding).where(AnomalyFinding.workspace_id == tenant.workspace.id)
                      .order_by(AnomalyFinding.created_at.desc())).scalars().first().subject_work_item_id


def test_a_duplicate_is_verified_when_confirmed_and_not_paid(db_session, tenant):
    _business(db_session, tenant)
    work_item_id = _dup_item(db_session, tenant, "D-1")
    _sweep(db_session, tenant)
    issue = _issue(db_session, tenant, v.DUPLICATE)
    assert issue.state == v.FOUND and issue.exposure_micros == 5_000 * M

    finding = db_session.execute(select(AnomalyFinding).where(AnomalyFinding.subject_work_item_id == work_item_id)).scalar_one()
    finding.status, finding.resolved_by_user_id = "CONFIRMED", tenant.owner.user.id
    finding.resolved_at = datetime.now(timezone.utc)
    db_session.flush()
    _sweep(db_session, tenant)
    assert issue.state == v.BEING_FIXED and issue.details["needs_payment_record"] is True  # no payment record yet

    _promise(db_session, tenant, work_item_id, amount=5_000)
    _sweep(db_session, tenant)
    assert issue.state == v.VERIFIED and _counted(db_session, tenant) == {"INR": 5_000 * M}

    promise = db_session.execute(select(HelmPromise).where(HelmPromise.work_item_id == work_item_id)).scalar_one()
    promise.details = {**promise.details, "settlement": {"state": hv.SETTLEMENT_PAID, "paid_on": TODAY.isoformat(),
                                                          "source": hv.SOURCE_PERSON}}
    db_session.flush()
    assert _sweep(db_session, tenant)["reopened"] == 1
    assert issue.state == v.FOUND and _counted(db_session, tenant) == {}


def test_a_dismissed_duplicate_is_not_money_with_the_reviewers_note(db_session, tenant):
    _business(db_session, tenant)
    work_item_id = _dup_item(db_session, tenant, "D-2")
    _sweep(db_session, tenant)
    finding = db_session.execute(select(AnomalyFinding).where(AnomalyFinding.subject_work_item_id == work_item_id)).scalar_one()
    finding.status, finding.resolution_note = "DISMISSED", "A second delivery, rightly billed"
    finding.resolved_by_user_id, finding.resolved_at = tenant.owner.user.id, datetime.now(timezone.utc)
    db_session.flush()
    _sweep(db_session, tenant)
    issue = _issue(db_session, tenant, v.DUPLICATE)
    assert issue.state == v.NOT_MONEY and issue.close_reason == "Not a duplicate: A second delivery, rightly billed"
    assert _counted(db_session, tenant) == {}


# ------------------------------------------------------------------------------------------------------------ overcharges


def _over(db, tenant, delta=1_200, status="NEEDS_REVIEW"):
    before = set(db.execute(select(ProcurementCase.id).where(ProcurementCase.workspace_id == tenant.workspace.id)).scalars())
    _overcharge(db, tenant, tenant.workspace, delta, status=status)
    case = db.execute(select(ProcurementCase).where(ProcurementCase.workspace_id == tenant.workspace.id,
                                                    ProcurementCase.id.notin_(before) if before else True)).scalar_one()
    for line in case.lines:
        line.invoice_amount_micros = 10_000 * M
    db.flush()
    return case


def test_an_overcharge_is_verified_by_a_credit_note_up_to_what_was_found(db_session, tenant):
    _business(db_session, tenant)
    case = _over(db_session, tenant)
    _sweep(db_session, tenant)
    issue = _issue(db_session, tenant, v.OVERCHARGE)
    assert issue.exposure_micros == 1_200 * M and issue.details["invoice_total_micros"] == 10_000 * M
    _resolve(case, tenant, "DISPUTED", "Asked the supplier for a credit note")
    db_session.flush()
    _sweep(db_session, tenant)
    assert issue.state == v.BEING_FIXED                       # a dispute is progress, never a closure

    _promise(db_session, tenant, case.invoice_work_item_id, credited=2_000,
             credit={"kind": "CREDIT", "document": "CN-77", "on": TODAY.isoformat()})
    _sweep(db_session, tenant)
    assert issue.state == v.VERIFIED and _counted(db_session, tenant) == {"INR": 1_200 * M}   # never more than found


def _resolve(case, tenant, status, reason):
    case.status, case.resolution_reason = status, reason
    case.resolved_by_user_id, case.resolved_at = tenant.owner.user.id, datetime.now(timezone.utc)


def _rerun(db, tenant, case, *, delta, invoiced):
    case.status = "SUPERSEDED"
    db.flush()   # one live case per invoice: the old one is superseded first, as the matcher does
    fresh = ProcurementCase(organization_id=case.organization_id, workspace_id=case.workspace_id,
                            po_work_item_id=case.po_work_item_id, invoice_work_item_id=case.invoice_work_item_id,
                            status="MATCHED", input_digest=uuid.uuid4().hex * 2, policy_version="1", header_findings=[],
                            line_count=1, exception_count=0, variance_micros=0,
                            created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc))
    db.add(fresh)
    db.flush()
    db.add(ProcurementCaseLine(organization_id=case.organization_id, workspace_id=case.workspace_id, case_id=fresh.id,
                               line_number=1, outcome="MATCHED" if not delta else "PRICE_VARIANCE", po_line_index=0,
                               invoice_line_index=0, price_delta_micros=delta * M, invoice_amount_micros=invoiced * M,
                               findings=[], evidence={}))
    db.flush()


def test_an_overcharge_corrected_by_a_reread_counts_and_an_amended_order_does_not(db_session, tenant):
    _business(db_session, tenant)
    corrected, amended = _over(db_session, tenant), _over(db_session, tenant, delta=500)
    _sweep(db_session, tenant)
    _rerun(db_session, tenant, corrected, delta=0, invoiced=8_800)     # the supplier re-issued at the order price
    _rerun(db_session, tenant, amended, delta=0, invoiced=10_000)      # the order was raised to the invoice's price
    _sweep(db_session, tenant)
    assert _issue(db_session, tenant, v.OVERCHARGE, corrected.invoice_work_item_id).state == v.VERIFIED
    closed = _issue(db_session, tenant, v.OVERCHARGE, amended.invoice_work_item_id)
    assert closed.state == v.CLOSED and "order was changed" in closed.close_reason
    assert _counted(db_session, tenant) == {"INR": 1_200 * M}


def test_an_overcharge_whose_price_a_person_accepted_is_not_money(db_session, tenant):
    _business(db_session, tenant)
    case = _over(db_session, tenant)
    _sweep(db_session, tenant)
    _resolve(case, tenant, "APPROVED", "Agreed surcharge for express delivery")
    db_session.flush()
    _sweep(db_session, tenant)
    issue = _issue(db_session, tenant, v.OVERCHARGE)
    assert issue.state == v.NOT_MONEY and "express delivery" in issue.close_reason and _counted(db_session, tenant) == {}


# ------------------------------------------------------------------------------------------------------------ deadlines


def test_a_deadline_is_verified_only_by_an_evidenced_payment_on_time(db_session, tenant):
    _business(db_session, tenant)
    from tests.services.helm import factories

    on_time = factories.invoice(db_session, workspace=tenant.workspace, organization_id=tenant.organization.id,
                                number="M-1", supplier="Udyam", amount=50_000, on=TODAY - timedelta(days=30))
    late = factories.invoice(db_session, workspace=tenant.workspace, organization_id=tenant.organization.id,
                             number="M-2", supplier="Udyam", amount=20_000, on=TODAY - timedelta(days=40))
    deadline = TODAY + timedelta(days=10)
    for item, amount in ((on_time, 50_000), (late, 20_000)):
        _promise(db_session, tenant, item.id, amount=amount, details={"msme_deadline": {"due": deadline.isoformat()}})
    fee = factories.invoice(db_session, workspace=tenant.workspace, organization_id=tenant.organization.id,
                            number="F-1", supplier="Steel", amount=10_000, on=TODAY - timedelta(days=20))
    _promise(db_session, tenant, fee.id, amount=10_000, due=TODAY + timedelta(days=5), terms={"late_fee_pct_per_month": "2"})
    _sweep(db_session, tenant)
    msme = _issue(db_session, tenant, v.PAYMENT_DEADLINE, on_time.id)
    assert msme.due_date == deadline and msme.exposure_micros == 50_000 * M and "MSME" in msme.due_basis
    fee_issue = _issue(db_session, tenant, v.PAYMENT_DEADLINE, fee.id)
    assert fee_issue.exposure_micros == 200 * M

    def pay(item, on):
        p = db_session.execute(select(HelmPromise).where(HelmPromise.work_item_id == item.id)).scalar_one()
        p.status = hv.STATUS_KEPT
        p.details = {**p.details, "settlement": {"state": hv.SETTLEMENT_PAID, "paid_on": on.isoformat(),
                                                 "source": hv.SOURCE_STATEMENT}}
    pay(on_time, TODAY)
    pay(late, deadline + timedelta(days=1))
    pay(fee, TODAY)
    db_session.flush()
    _sweep(db_session, tenant)
    assert msme.state == v.VERIFIED and "bank statement line" in msme.close_reason
    late_issue = _issue(db_session, tenant, v.PAYMENT_DEADLINE, late.id)
    assert late_issue.state == v.CLOSED and "after the deadline" in late_issue.close_reason
    assert fee_issue.state == v.VERIFIED
    # Paying on time keeps the MSME deadline; only the stated fee is money avoided.
    assert _counted(db_session, tenant) == {"INR": 200 * M}


# ------------------------------------------------------------------------------------------------------------ statements


def test_a_statement_difference_is_verified_when_the_next_statement_drops_it(db_session, tenant, monkeypatch):
    from app.services.helm import reconcile as rc
    from app.services.helm.snapshot import SupplierStatement

    from tests.services.helm import factories

    _business(db_session, tenant)
    soa = factories.document(db_session, workspace=tenant.workspace, organization_id=tenant.organization.id,
                             role="STATEMENT", entities={}, number="SOA-1")

    def rec(on, differences):
        st = SupplierStatement(work_item_id=str(soa.id), workspace_id=str(tenant.workspace.id), document="soa.pdf",
                               counterparty_key="nilgiri", counterparty_name="Nilgiri", currency="INR",
                               statement_date=on, period_start=None, opening_balance_micros=0,
                               closing_balance_micros=0, entries=(), confidence="EXTRACTED")
        return {"nilgiri": rc.Reconciliation(statement=st, currency="INR", their_balance_micros=0, our_balance_micros=0,
                                              differences=tuple(differences), agreed_lines=0, period_start=None,
                                              period_end=None)}
    unapplied = rc.Difference(code=rc.PAYMENT_NOT_APPLIED, summary="We paid KP-1182; their statement shows no payment",
                              effect_micros=50_000 * M, our_micros=50_000 * M, evidence=({"number": "KP-1182"},))
    state = {"recs": rec(TODAY - timedelta(days=30), [unapplied])}
    monkeypatch.setattr(adapters.StatementDifference, "_latest", lambda self, db, ws, today: state["recs"])

    assert _sweep(db_session, tenant)["found"] == 0                 # statements are read by the hourly sweep only
    _sweep(db_session, tenant, heavy=True)
    issue = _issue(db_session, tenant, v.STATEMENT_DIFFERENCE)
    assert issue.state == v.FOUND and issue.exposure_micros == 50_000 * M and issue.due_date is None
    service.set_due_date(db_session, issue, due_date=TODAY + timedelta(days=7), actor_id=tenant.owner.user.id)
    assert issue.due_basis == "Set by a person"

    state["recs"] = rec(TODAY, [])                                  # the next statement applies our payment
    _sweep(db_session, tenant, heavy=True)
    assert issue.state == v.VERIFIED and "no longer shows it" in issue.close_reason
    assert _counted(db_session, tenant) == {}                       # resolved, but not money recovered


# ------------------------------------------------------------------------------------------------------------ the ledger


def test_every_pair_of_engines_counts_one_outcome_once(db_session, tenant):
    """Helm and Recoveries can both claim a blocked duplicate, a recovered overcharge and an avoided fee; a duplicate
    that was blocked is not also an overcharge recovered on the same invoice."""
    _business(db_session, tenant)
    book = _book(db_session, tenant.organization.id, tenant.workspace)
    issue = RecoveryIssue(organization_id=tenant.organization.id, workspace_id=tenant.workspace.id, kind=v.DUPLICATE,
                          subject_key="x", title="t", state=v.VERIFIED)
    db_session.add(issue)
    db_session.flush()
    for category, amount in ((v.DUPLICATE_BLOCKED, 5_000), (v.OVERCHARGE_RECOVERED, 700), (v.LATE_FEE_AVOIDED, 90)):
        work_item_id = uuid.uuid4()
        outcome = adapters.Outcome(category, work_item_id, "INR", amount * M, TODAY, {})
        # Recoveries first, Helm second: one row each in the two ledgers, counted once.
        assert ledger.record(db_session, issue, outcome) == "RECOVERIES"
        db_session.add(HelmValueEvent(organization_id=book.organization_id, book_id=book.id, workspace_id=tenant.workspace.id,
                                      category=category, dedupe_key=helm_value.dedupe_key(category, work_item_id),
                                      currency="INR", amount_micros=amount * M, occurred_on=TODAY, month=TODAY.replace(day=1)))
        db_session.flush()
        # Helm first: Recoveries does not write a second row.
        other = uuid.uuid4()
        db_session.add(HelmValueEvent(organization_id=book.organization_id, book_id=book.id, workspace_id=tenant.workspace.id,
                                      category=category, dedupe_key=helm_value.dedupe_key(category, other),
                                      currency="INR", amount_micros=amount * M, occurred_on=TODAY, month=TODAY.replace(day=1)))
        db_session.flush()
        assert ledger.record(db_session, issue, adapters.Outcome(category, other, "INR", amount * M, TODAY, {})) == "HELM"
    assert _counted(db_session, tenant) == {"INR": 2 * (5_000 + 700 + 90) * M}

    both = uuid.uuid4()   # a blocked duplicate that was also billed above its order
    ledger.record(db_session, issue, adapters.Outcome(v.DUPLICATE_BLOCKED, both, "INR", 9_000 * M, TODAY, {}))
    ledger.record(db_session, issue, adapters.Outcome(v.OVERCHARGE_RECOVERED, both, "INR", 1_000 * M, TODAY, {}))
    assert _counted(db_session, tenant) == {"INR": (2 * (5_000 + 700 + 90) + 9_000) * M}


def test_a_gst_secured_credit_is_one_row_however_often_it_is_proved(db_session, tenant):
    _business(db_session, tenant)
    item = _gst_book(db_session, tenant, tenant.workspace, "W-9", 1000, "WAITING_FOR_SUPPLIER")
    _sweep(db_session, tenant)
    _waiting_to_matched(db_session, tenant, item.id)
    for _ in range(3):
        _sweep(db_session, tenant)
    assert db_session.execute(select(RecoveryOutcome)).scalars().all().__len__() == 1


# ------------------------------------------------------------------------------------------------------------ the routes


def url(tenant, tail="", workspace=None) -> str:
    return f"{API}/workspaces/{(workspace or tenant.workspace).id}/recoveries{tail}"


@pytest.fixture()
def business(db_session, tenant):
    _business(db_session, tenant)
    _gst_book(db_session, tenant, tenant.workspace, "W-1", 1000, "WAITING_FOR_SUPPLIER")
    _gst_book(db_session, tenant, tenant.workspace, "W-2", 3000, "WAITING_FOR_SUPPLIER")
    db_session.commit()
    return tenant


def test_the_list_shows_found_being_fixed_and_verified_with_next_actions(client, business):
    t = business
    body = client.get(url(t), headers=t.viewer.headers).json()
    assert body["included"] is True
    assert body["summary"]["counts"]["FOUND"] == 2 and body["summary"]["found"] == [{"currency": "INR", "amount_micros": 720 * M}]
    assert body["summary"]["needs_owner"]["count"] == 2 and body["summary"]["recovered_verified"] == []
    first = body["items"][0]
    assert first["kind"] == "GST_CREDIT" and first["kind_label"] == "GST credit waiting on a supplier"
    assert {a["key"] for a in first["next_actions"]} == {"gst", "document"}

    response = client.put(url(t, f"/{first['id']}/owner"), headers=t.contributor.headers,
                          json={"owner_user_id": str(t.contributor.user.id), "version": first["version"]})
    assert response.status_code == 200, response.text
    assert response.json()["state"] == "BEING_FIXED" and response.json()["owner_email"] == t.contributor.user.email
    stale = client.put(url(t, f"/{first['id']}/owner"), headers=t.contributor.headers,
                       json={"owner_user_id": None, "version": first["version"]})
    assert stale.status_code == 409 and "Someone else changed" in stale.json()["detail"]
    stranger = client.put(url(t, f"/{first['id']}/owner"), headers=t.contributor.headers,
                          json={"owner_user_id": str(t.other_org_member.user.id)})
    assert stranger.status_code == 409 and "member of this workspace" in stranger.json()["detail"]
    due = client.put(url(t, f"/{first['id']}/due-date"), headers=t.contributor.headers, json={"due_date": "2030-01-01"})
    assert due.status_code == 409 and "Section 16(4)" in due.json()["detail"]


def test_not_money_needs_a_reason_is_never_counted_and_can_be_reopened(client, business):
    t = business
    item = client.get(url(t), headers=t.viewer.headers).json()["items"][0]
    short = client.post(url(t, f"/{item['id']}/not-money"), headers=t.contributor.headers, json={"reason": "no"})
    assert short.status_code == 422
    closed = client.post(url(t, f"/{item['id']}/not-money"), headers=t.contributor.headers,
                         json={"reason": "Booked twice by mistake; the second entry was removed"})
    assert closed.status_code == 200 and closed.json()["state"] == "NOT_MONEY"
    assert closed.json()["close_reason"].startswith("Not money: Booked twice")
    body = client.get(url(t), headers=t.viewer.headers).json()
    assert body["summary"]["counts"]["NOT_MONEY"] == 1 and body["summary"]["recovered_verified"] == []
    left = 720 * M - item["exposure_micros"]                                           # what is left open
    assert body["summary"]["found"] == [{"currency": "INR", "amount_micros": left}]
    reopened = client.post(url(t, f"/{item['id']}/reopen"), headers=t.contributor.headers, json={})
    assert reopened.status_code == 200 and reopened.json()["state"] == "FOUND"


def test_viewers_read_and_cannot_act(client, business):
    t = business
    item = client.get(url(t), headers=t.viewer.headers).json()["items"][0]
    assert client.get(url(t, f"/{item['id']}"), headers=t.viewer.headers).status_code == 200
    for method, tail, body in (("put", "/owner", {"owner_user_id": None}), ("post", "/not-money", {"reason": "x" * 20}),
                               ("post", "/reopen", {})):
        response = getattr(client, method)(url(t, f"/{item['id']}{tail}"), headers=t.viewer.headers, json=body)
        assert response.status_code == 403, tail
    assert client.post(url(t, "/check"), headers=t.viewer.headers).status_code == 403
    assert client.post(url(t, "/check"), headers=t.contributor.headers).status_code == 200


def test_another_workspace_and_another_organization_see_nothing(client, business, db_session):
    from app.models.organization import Organization

    t = business
    # The other organization is on Business too, so only the workspace predicate stands between them.
    put_on_plan(db_session, db_session.get(Organization, t.foreign_workspace.organization_id), "business")
    db_session.commit()
    item = client.get(url(t), headers=t.viewer.headers).json()["items"][0]
    # The foreign workspace's member asks for this workspace's issue through their own workspace: not found.
    response = client.get(url(t, f"/{item['id']}", workspace=t.foreign_workspace), headers=t.other_org_member.headers)
    assert response.status_code == 404
    assert client.get(url(t), headers=t.other_org_member.headers).status_code in (403, 404)
    assert client.get(url(t), headers=t.non_member.headers).status_code in (403, 404)


def test_starter_sees_a_preview_of_counts_and_found_and_cannot_act(client, db_session, tenant):
    put_on_plan(db_session, tenant.organization, "developer")
    _gst_book(db_session, tenant, tenant.workspace, "W-1", 1000, "WAITING_FOR_SUPPLIER")
    db_session.commit()
    body = client.get(url(tenant), headers=tenant.viewer.headers).json()
    assert body["included"] is False and body["items"] == []
    assert body["summary"]["counts"]["FOUND"] == 1 and body["summary"]["found"] == [{"currency": "INR", "amount_micros": 180 * M}]
    assert db_session.execute(select(RecoveryIssue)).first() is None        # a preview writes nothing
    assert client.post(url(tenant, "/check"), headers=tenant.contributor.headers).status_code in (402, 403)


# ------------------------------------------------------------------------------------------------------------ where it shows


def test_the_receipt_shows_recovered_verified_beside_found_counted_once(db_session, tenant):
    from app.services import value_receipt as vr

    _business(db_session, tenant)
    tenant.workspace.timezone = "UTC"
    book = _book(db_session, tenant.organization.id, tenant.workspace)
    item = _gst_book(db_session, tenant, tenant.workspace, "W-1", 1000, "WAITING_FOR_SUPPLIER")
    _gst_book(db_session, tenant, tenant.workspace, "W-2", 3000, "WAITING_FOR_SUPPLIER")
    work_item_id = _dup_item(db_session, tenant, "D-9", total=5_000, status="CONFIRMED")
    _promise(db_session, tenant, work_item_id, amount=5_000)
    _sweep(db_session, tenant)
    _waiting_to_matched(db_session, tenant, item.id)
    _sweep(db_session, tenant)
    # Helm also proved the same blocked duplicate: one outcome, Helm's row.
    db_session.add(HelmValueEvent(organization_id=book.organization_id, book_id=book.id, workspace_id=tenant.workspace.id,
                                  category=v.DUPLICATE_BLOCKED, dedupe_key=helm_value.dedupe_key(v.DUPLICATE_BLOCKED, work_item_id),
                                  currency="INR", amount_micros=5_000 * M, occurred_on=TODAY, month=TODAY.replace(day=1)))
    db_session.commit()
    vr.forget(tenant.organization.id)
    found = {f["key"]: f for f in vr.receipt(db_session, tenant.organization.id, "month")["found"]}
    recovered = found["recovered_verified_INR"]
    assert recovered["amount_micros"] == (5_000 + 180) * M and recovered["count"] == 2
    assert recovered["source"].endswith(f"/{tenant.workspace.slug}/recoveries") and recovered["honesty"] == "confirmed"
    assert found["gst_waiting"]["amount_micros"] == 540 * M              # found, its own line, never added to it
    assert "helm_value_held_INR" not in found                           # the same rupees are not shown twice


def test_the_monthly_summary_keeps_a_line_for_recovered_verified(db_session, tenant, monkeypatch):
    from app.services import monthly_receipt_email as monthly
    from app.services import value_receipt as vr

    found = [{"key": k, "label": k, "amount_text": "₹1", "source": "/x"} for k in
             ("gst_waiting", "gst_at_risk_180", "gst_claimable", "duplicate_payments_INR", "recovered_verified_INR")]
    monkeypatch.setattr(vr, "receipt", lambda *a, **k: {"found": found, "headline": "This month Servabo found ₹1."})
    monkeypatch.setattr(monthly, "owners_to_email", lambda db, org_id: [(uuid.uuid4(), "owner@example.com")])
    sent = []
    monkeypatch.setattr("app.core.platform_email.send_platform_email",
                        lambda **kw: sent.append(kw["text_body"]) or (True, "ok"))
    monthly.send_for(db_session, tenant.organization, period="2026-09", label="September 2026", now=datetime.now(timezone.utc))
    assert "recovered_verified_INR" in sent[0] and "gst_waiting" in sent[0] and "duplicate_payments_INR" not in sent[0]


def test_the_gst_digest_says_how_many_issues_need_an_owner(db_session, tenant):
    from app.services.gst import digest

    _business(db_session, tenant)
    _gst_book(db_session, tenant, tenant.workspace, "W-1", 1000, "WAITING_FOR_SUPPLIER")
    _gst_book(db_session, tenant, tenant.workspace, "W-2", 3000, "WAITING_FOR_SUPPLIER")
    _sweep(db_session, tenant)
    line = digest.needs_owner_finding(db_session, tenant.organization)
    assert line.label == "2 money issues worth ₹720 need an owner"
    assert line.url.endswith(f"/{tenant.organization.slug}/{tenant.workspace.slug}/recoveries")
    for issue in service.list_issues(db_session, tenant.workspace.id):
        service.assign(db_session, issue, owner_user_id=tenant.owner.user.id, actor_id=tenant.owner.user.id)
    assert digest.needs_owner_finding(db_session, tenant.organization) is None


def test_getting_started_money_step_follows_up_in_recoveries(db_session, tenant, monkeypatch):
    from app.models.organization import OrganizationRole
    from app.models.workspace import WorkspaceRole
    from app.services import getting_started as gs

    monkeypatch.setattr(gs, "first_money", lambda db, org_id: {"text": "Found ₹720", "amount_text": "₹720", "period": "month"})
    view = lambda: gs.evaluate(db_session, organization=tenant.organization, workspace=tenant.workspace,  # noqa: E731
                               workspace_role=WorkspaceRole.ADMIN, organization_role=OrganizationRole.OWNER)
    put_on_plan(db_session, tenant.organization, "developer")
    assert view()["money"]["follow_up"] is None
    put_on_plan(db_session, tenant.organization, "business")
    assert view()["money"]["follow_up"] == "recoveries"


def test_an_organization_owner_without_a_workspace_grant_can_own_an_issue(client, business, db_session):
    """Owners and admins reach every workspace as a derived admin, with no membership row (the sample company is one
    such workspace): they must be able to take an issue, and someone with no access must not."""
    from app.models.workspace import WorkspaceMember

    t = business
    item = client.get(url(t), headers=t.viewer.headers).json()["items"][0]
    granted = db_session.execute(select(WorkspaceMember).where(WorkspaceMember.workspace_id == t.workspace.id,
                                                               WorkspaceMember.user_id == t.owner.user.id)).scalar_one_or_none()
    if granted is not None:
        db_session.delete(granted)
        db_session.commit()
    response = client.put(url(t, f"/{item['id']}/owner"), headers=t.contributor.headers,
                          json={"owner_user_id": str(t.owner.user.id)})
    assert response.status_code == 200, response.text
    assert response.json()["owner_email"] == t.owner.user.email
    nobody = client.put(url(t, f"/{item['id']}/owner"), headers=t.contributor.headers,
                        json={"owner_user_id": str(t.non_member.user.id)})
    assert nobody.status_code == 409


def test_two_radar_findings_on_one_invoice_are_one_issue(db_session, tenant):
    """The radar can find one invoice the duplicate of two others (CI, test_process_intel_live): one issue, not a crash."""
    _business(db_session, tenant)
    work_item_id = _dup_item(db_session, tenant, "D-7", total=3_000)
    first = db_session.execute(select(AnomalyFinding).where(AnomalyFinding.subject_work_item_id == work_item_id)).scalar_one()
    from tests.services.helm import factories

    third = factories.invoice(db_session, workspace=tenant.workspace, organization_id=tenant.organization.id, number="D-7",
                              supplier="Nilgiri", amount=3_000, on=TODAY - timedelta(days=5))
    db_session.add(AnomalyFinding(
        organization_id=first.organization_id, workspace_id=first.workspace_id, kind=first.kind, layer="L2",
        severity="MEDIUM", subject_work_item_id=work_item_id, counterpart_work_item_id=third.id, score=1,
        headline="Near-identical text", metrics={}, evidence=[{"kind": "text", "similarity": 0.97}], status="OPEN", dedupe_key=uuid.uuid4().hex * 2,
        input_digest="f" * 64, engine_version="t"))
    db_session.flush()
    assert _sweep(db_session, tenant)["found"] == 1
    assert len(service.list_issues(db_session, tenant.workspace.id, kind=v.DUPLICATE)) == 1


def test_the_hourly_job_queues_one_sweep_per_workspace_and_sweeps_none_itself(db_session, tenant):
    """CI runs 510 and 511: one hourly job sweeping every workspace in turn held the worker's queue for minutes, and the
    browser tests waiting on other jobs timed out. It now queues one small job per entitled workspace."""
    from app.models.job import Job, JobStatus
    from app.workers.handlers import recoveries as job

    def queued():
        return [j for j in db_session.execute(select(Job).where(Job.job_type == "recoveries.sweep")).scalars()
                if (j.payload or {}).get("workspace_id") == str(tenant.workspace.id)]

    put_on_plan(db_session, tenant.organization, "developer")
    db_session.flush()
    job.fan_out(db_session)
    assert queued() == []  # a plan without Recoveries gets none
    _business(db_session, tenant)
    _dup_item(db_session, tenant, "D-9", total=3_000)
    assert job.fan_out(db_session) >= 1
    job.fan_out(db_session)  # its sweep is still waiting: not queued twice
    assert len(queued()) == 1
    assert queued()[0].organization_id == tenant.organization.id
    assert service.list_issues(db_session, tenant.workspace.id) == []  # the fan-out sweeps nothing itself
    assert job._sweep_one(db_session, tenant.workspace.id)["found"] == 1  # each queued job sweeps its workspace
    assert len(service.list_issues(db_session, tenant.workspace.id, kind=v.DUPLICATE)) == 1
    done = queued()[0]
    done.status, done.succeeded_at = JobStatus.SUCCEEDED, datetime.now(timezone.utc)
    db_session.flush()
    job.fan_out(db_session)  # the next hour, after it ran: queued again
    assert len(queued()) == 2
