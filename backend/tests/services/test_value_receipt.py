"""The value receipt (Session G): what Servabo found in a customer's own documents, in their own money.

Real Postgres. Every engine's rows are planted the way the engines leave them, then the receipt is read:

  * the exact figures, their order and the headline sentence;
  * the sample company is never counted (its workspace, its Helm book, its usage);
  * another organization sees nothing of it;
  * rupees and dollars are two findings, and confirmed / likely / potential are three, never added;
  * a figure of zero is left out;
  * an engine the plan does not include produces nothing, and the receipt names what Business adds;
  * the trial window and the calendar month, in the zone of the organization's oldest workspace.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest

from app.core import entitlements
from app.models.gst import GstMatch
from app.models.helm import HelmBacktest, HelmBook, HelmValueEvent
from app.models.payment_risk import PaymentRiskFlag
from app.models.procurement import ProcurementCase, ProcurementCaseLine
from app.models.radar import AnomalyFinding, DocumentFingerprint
from app.models.usage_event import UsageEvent
from app.models.workspace import Workspace, WorkspaceStatus
from app.services import value_receipt as vr
from app.services.helm import vocabulary as hv
from app.services.radar import vocabulary as radar_v
from tests.security.plans import put_on_plan
from tests.services.gst.helpers import RECIPIENT, SUPPLIER_A, book_invoice
from tests.services.helm import factories

M = 1_000_000
NOW = datetime.now(timezone.utc).replace(microsecond=0)
DAY = timedelta(days=1)


def _usage(db, org_id, workspace_id, event_type, quantity, at):
    db.add(UsageEvent(organization_id=org_id, workspace_id=workspace_id, event_type=event_type, unit="request",
                      quantity=quantity, occurred_at=at))


def _book(db, org_id, workspace, kind=hv.BOOK_WORKSPACE, name="Book"):
    book = HelmBook(organization_id=org_id, workspace_id=workspace.id if workspace else None, kind=kind, name=name,
                    status=hv.BOOK_ACTIVE)
    db.add(book)
    db.flush()
    return book


def _backtest(db, book, totals, *, finished=NOW - DAY):
    row = HelmBacktest(organization_id=book.organization_id, book_id=book.id, status=hv.BACKTEST_DONE, months=3,
                       period_start=(finished - 90 * DAY).date(), period_end=finished.date(), mandates=[],
                       result={"totals": totals}, finished_at=finished, created_at=finished)
    db.add(row)
    db.flush()
    return row


def _gst_book(db, tenant, workspace, number, taxable, status, *, risk=None):
    """A purchase invoice and its reconciliation row. `taxable` x 18% is the credit."""
    item = book_invoice(db, tenant, number=number, supplier="a", gstin=SUPPLIER_A, on=date.today() - 10 * DAY,
                        taxable=taxable, workspace=workspace)
    credit = int(taxable * 0.18 * M)
    db.add(GstMatch(organization_id=tenant.organization.id, workspace_id=workspace.id, gstin=RECIPIENT,
                    work_item_id=item.id, status=status, supplier_gstin=SUPPLIER_A, supplier_name="Sahyadri",
                    doc_number=number, doc_date=date.today() - 10 * DAY, value_micros=credit * 6,
                    tax_micros=credit, itc_micros=credit, risk=risk))
    db.flush()
    return item


def _duplicate(db, tenant, workspace, number, total, currency, *, status="OPEN", at=NOW - DAY):
    first = factories.invoice(db, workspace=workspace, organization_id=tenant.organization.id, number=number,
                              supplier="Nilgiri", amount=total or 1, on=date.today() - 5 * DAY)
    second = factories.invoice(db, workspace=workspace, organization_id=tenant.organization.id, number=number,
                               supplier="Nilgiri", amount=total or 1, on=date.today() - 5 * DAY)
    db.add(DocumentFingerprint(
        work_item_id=second.id, organization_id=tenant.organization.id, workspace_id=workspace.id,
        content_sha256="a" * 64, minhash=[1] * radar_v.MINHASH_PERMUTATIONS, shingle_count=3, embedding_model="stub",
        total_micros=int(total * M) if total else None, currency=currency if total else None, engine_version="t",
        embedding=[0.0] * radar_v.EMBEDDING_DIMENSION))
    db.add(AnomalyFinding(
        organization_id=tenant.organization.id, workspace_id=workspace.id, kind=radar_v.KIND_DUPLICATE_DOCUMENT,
        layer="L1", severity="HIGH", subject_work_item_id=second.id, counterpart_work_item_id=first.id, score=1,
        headline="Same supplier and number", metrics={}, evidence=[{"kind": "identifiers", "number": number}], status=status, dedupe_key=uuid.uuid4().hex * 2,
        input_digest="e" * 64, engine_version="t", created_at=at, updated_at=at,
        resolved_by_user_id=None if status == "OPEN" else tenant.owner.user.id,
        resolved_at=None if status == "OPEN" else at, resolution_note=None if status == "OPEN" else "reviewed"))
    db.flush()


def _bank_change(db, tenant, workspace, *, status="OPEN", at=NOW - DAY):
    item = factories.invoice(db, workspace=workspace, organization_id=tenant.organization.id,
                             number=f"B-{uuid.uuid4().hex[:6]}", supplier="Deccan", amount=100,
                             on=date.today() - 3 * DAY)
    db.add(PaymentRiskFlag(organization_id=tenant.organization.id, workspace_id=workspace.id, work_item_id=item.id,
                           kind="BANK_ACCOUNT_CHANGED", severity="HIGH", status=status, summary="Account changed",
                           details={}, created_at=at))
    db.flush()


def _overcharge(db, tenant, workspace, delta, *, outcome="PRICE_VARIANCE", status="NEEDS_REVIEW", at=NOW - DAY):
    order = factories.document(db, workspace=workspace, organization_id=tenant.organization.id, role="PURCHASE_ORDER",
                               entities={}, number=f"PO-{uuid.uuid4().hex[:5]}")
    invoice = factories.invoice(db, workspace=workspace, organization_id=tenant.organization.id,
                                number=f"I-{uuid.uuid4().hex[:5]}", supplier="Steel", amount=100, on=date.today())
    case = ProcurementCase(organization_id=tenant.organization.id, workspace_id=workspace.id,
                           po_work_item_id=order.id, invoice_work_item_id=invoice.id, status=status,
                           input_digest=uuid.uuid4().hex + uuid.uuid4().hex, policy_version="1", header_findings=[],
                           line_count=1, exception_count=1, variance_micros=delta * M, created_at=at, updated_at=at)
    db.add(case)
    db.flush()
    db.add(ProcurementCaseLine(organization_id=tenant.organization.id, workspace_id=workspace.id, case_id=case.id,
                               line_number=1, outcome=outcome, po_line_index=0, invoice_line_index=0,
                               price_delta_micros=delta * M, findings=[], evidence={}))
    db.flush()


def _value_event(db, book, workspace, currency, amount, *, on=None, category=hv.VALUE_DUPLICATE_BLOCKED):
    on = on or (NOW - DAY).date()
    db.add(HelmValueEvent(organization_id=book.organization_id, book_id=book.id,
                          workspace_id=workspace.id if workspace else None, category=category,
                          dedupe_key=uuid.uuid4().hex + uuid.uuid4().hex, currency=currency, amount_micros=amount * M,
                          occurred_on=on, month=on.replace(day=1)))
    db.flush()


@pytest.fixture()
def world(db_session, tenant):
    """A Business organization two days from the end of its trial, with every engine's rows planted, and a sample
    company next to it holding rows that must never be counted."""
    org = tenant.organization
    put_on_plan(db_session, org, "business")
    org.trial_ends_at = NOW + 2 * DAY
    ws = tenant.workspace
    ws.timezone = "UTC"
    ws.currency = "INR"
    sample = Workspace(organization_id=org.id, slug="sample", workspace_name="Sample company",
                       status=WorkspaceStatus.ACTIVE, is_sample=True)
    db_session.add(sample)
    db_session.flush()

    # What was read: 5 documents, 12 pages, 3 answers in the trial; older and sample events do not count.
    for _ in range(5):
        _usage(db_session, org.id, ws.id, "document.upload", 1, NOW - DAY)
    _usage(db_session, org.id, ws.id, "ocr.page", 12, NOW - DAY)
    _usage(db_session, org.id, ws.id, "assistant.message", 3, NOW - 2 * DAY)
    _usage(db_session, org.id, ws.id, "document.upload", 40, NOW - 20 * DAY)          # before the trial
    _usage(db_session, org.id, sample.id, "document.upload", 99, NOW - DAY)           # the sample company

    # GST: 2 invoices waiting on one supplier (1000 + 3000 taxable -> 180 + 540), 1 claimable (500 -> 90),
    # 1 at risk under the 180-day rule (2000 -> 360 of tax), and rows in the sample company.
    _gst_book(db_session, tenant, ws, "W-1", 1000, "WAITING_FOR_SUPPLIER")
    _gst_book(db_session, tenant, ws, "W-2", 3000, "WAITING_FOR_SUPPLIER")
    _gst_book(db_session, tenant, ws, "C-1", 500, "MATCHED")
    _gst_book(db_session, tenant, ws, "R-1", 2000, "MATCHED",
              risk={"paid": False, "invoice_date": (date.today() - 170 * DAY).isoformat()})
    _gst_book(db_session, tenant, sample, "S-1", 900000, "WAITING_FOR_SUPPLIER")

    book = _book(db_session, org.id, ws)
    sample_book = _book(db_session, org.id, sample, kind=hv.BOOK_SAMPLE, name="Sample")
    _backtest(db_session, book, {"confirmed": {"INR": 50_000 * M}, "likely": {"INR": 20_000 * M},
                                 "potential": {"INR": 7_000 * M}})
    _backtest(db_session, sample_book, {"confirmed": {"INR": 999_999 * M}}, finished=NOW - DAY / 2)  # newer, sample

    _duplicate(db_session, tenant, ws, "D-1", 8_000, "INR")
    _duplicate(db_session, tenant, ws, "D-2", 2_000, "INR", status="CONFIRMED")
    _duplicate(db_session, tenant, ws, "D-3", 0, "INR")                                    # amount not read
    _duplicate(db_session, tenant, ws, "D-4", 5_000, "INR", status="DISMISSED")           # a person said no
    _duplicate(db_session, tenant, sample, "D-5", 777_000, "INR")
    _bank_change(db_session, tenant, ws)
    _bank_change(db_session, tenant, ws, status="CONFIRMED")
    _bank_change(db_session, tenant, ws, status="DISMISSED")
    _bank_change(db_session, tenant, sample)
    _overcharge(db_session, tenant, ws, 1_200)
    _overcharge(db_session, tenant, ws, 300)
    _overcharge(db_session, tenant, ws, 50_000, status="SUPERSEDED")                       # replaced by a newer case
    _overcharge(db_session, tenant, ws, 60_000, outcome="QUANTITY_VARIANCE")
    _overcharge(db_session, tenant, sample, 888_000)
    _value_event(db_session, book, ws, "INR", 4_000)
    _value_event(db_session, sample_book, sample, "INR", 555_000)
    db_session.commit()
    vr.forget(org.id)
    return tenant


def found(body):
    return {f["key"]: f for f in body["found"]}


def test_the_figures_come_in_the_stated_order(db_session, world):
    body = vr.receipt(db_session, world.organization.id, "trial", now=NOW)

    assert body["work"] == {"documents": 5, "pages": 12, "assistant_answers": 3}
    assert [f["key"] for f in body["found"]] == [
        "gst_waiting", "gst_at_risk_180", "gst_claimable",
        "time_machine_confirmed_INR", "time_machine_likely_INR", "time_machine_potential_INR",
        "duplicate_payments_INR", "duplicate_payments_unpriced", "bank_account_changes",
        "overcharges_INR", "helm_value_held_INR",
    ]
    f = found(body)
    assert (f["gst_waiting"]["amount_micros"], f["gst_waiting"]["count"], f["gst_waiting"]["suppliers"]) == (
        (180 + 540) * M, 2, 1)
    assert f["gst_waiting"]["amount_text"] == "₹720" and f["gst_waiting"]["currency"] == "INR"
    assert f["gst_waiting"]["label"] == "GST credit waiting on 1 supplier"
    assert (f["gst_at_risk_180"]["amount_micros"], f["gst_at_risk_180"]["count"]) == (360 * M, 1)
    assert (f["gst_claimable"]["amount_micros"], f["gst_claimable"]["count"]) == ((90 + 360) * M, 2)
    assert f["time_machine_confirmed_INR"]["amount_micros"] == 50_000 * M
    assert f["time_machine_confirmed_INR"]["amount_text"] == "₹50,000"
    assert f["duplicate_payments_INR"]["amount_micros"] == 10_000 * M and f["duplicate_payments_INR"]["count"] == 2
    assert f["duplicate_payments_unpriced"]["count"] == 1 and f["duplicate_payments_unpriced"]["amount_micros"] is None
    assert f["bank_account_changes"]["count"] == 2
    assert (f["overcharges_INR"]["amount_micros"], f["overcharges_INR"]["count"]) == (1_500 * M, 2)
    assert (f["helm_value_held_INR"]["amount_micros"], f["helm_value_held_INR"]["honesty"]) == (4_000 * M, "confirmed")
    assert body["headline"] == "In your trial Servabo read 5 documents and found ₹720 of GST credit waiting on 1 supplier."
    assert body["also_on_business"] == []


def test_every_money_figure_links_to_the_page_that_holds_its_evidence(db_session, world):
    org, ws = world.organization.slug, world.workspace.slug
    f = found(vr.receipt(db_session, world.organization.id, "trial", now=NOW))
    assert f["gst_waiting"]["source"] == f"/{org}/{ws}/gst" == f["gst_claimable"]["source"]
    assert f["time_machine_likely_INR"]["source"] == f"/{org}/helm/time-machine"
    assert f["duplicate_payments_INR"]["source"] == f"/{org}/{ws}/radar" == f["bank_account_changes"]["source"]
    assert f["overcharges_INR"]["source"] == f"/{org}/{ws}/procurement"
    assert f["helm_value_held_INR"]["source"] == f"/{org}/helm"
    assert all(item["source"].startswith("/") for item in vr.receipt(db_session, world.organization.id, "trial",
                                                                      now=NOW)["found"])


def test_the_sample_company_is_never_counted(db_session, world):
    body = vr.receipt(db_session, world.organization.id, "trial", now=NOW)
    text = repr(body)
    for planted in ("99", "900000", "999999", "777000", "888000", "555000"):
        assert str(int(planted) * M) not in text, planted
    assert body["work"]["documents"] == 5
    assert found(body)["time_machine_confirmed_INR"]["amount_micros"] == 50_000 * M   # not the newer sample replay


def test_a_workspace_that_is_only_the_sample_company_has_nothing_to_show(db_session, tenant):
    sample = tenant.workspace
    sample.is_sample = True
    _usage(db_session, tenant.organization.id, sample.id, "document.upload", 4, NOW - DAY)
    db_session.commit()
    body = vr.receipt(db_session, tenant.organization.id, "month", now=NOW)
    assert body["work"]["documents"] == 0 and body["found"] == [] and body["headline"] is None


def test_another_organization_sees_nothing_of_it(db_session, world):
    other = world.foreign_workspace.organization_id
    body = vr.receipt(db_session, other, "trial", now=NOW)
    assert body["found"] == [] and body["work"] == {"documents": 0, "pages": 0, "assistant_answers": 0}
    assert body["headline"] is None


def test_rupees_and_dollars_are_two_findings_and_never_added(db_session, world):
    book = db_session.query(HelmBook).filter_by(kind=hv.BOOK_WORKSPACE).one()
    _value_event(db_session, book, world.workspace, "USD", 300)
    _backtest(db_session, book, {"confirmed": {"INR": 10 * M, "USD": 25 * M}, "likely": {}, "potential": {}},
              finished=NOW - DAY / 4)
    db_session.commit()
    f = found(vr.receipt(db_session, world.organization.id, "trial", now=NOW))
    assert f["helm_value_held_INR"]["amount_micros"] == 4_000 * M
    assert f["helm_value_held_USD"]["amount_micros"] == 300 * M and f["helm_value_held_USD"]["amount_text"] == "$300"
    assert f["time_machine_confirmed_INR"]["amount_micros"] == 10 * M
    assert f["time_machine_confirmed_USD"]["amount_micros"] == 25 * M


def test_confirmed_likely_and_potential_stay_three_findings(db_session, world):
    f = found(vr.receipt(db_session, world.organization.id, "trial", now=NOW))
    classes = {f[k]["honesty"]: f[k]["amount_micros"] for k in f if k.startswith("time_machine_")}
    assert classes == {"confirmed": 50_000 * M, "likely": 20_000 * M, "potential": 7_000 * M}
    assert not any(item["amount_micros"] == 77_000 * M for item in f.values())


def test_a_headline_only_rests_on_a_confirmed_figure_or_one_without_a_class(db_session, tenant):
    org = tenant.organization
    put_on_plan(db_session, org, "free")
    org.trial_ends_at = NOW + DAY
    book = _book(db_session, org.id, tenant.workspace)
    _backtest(db_session, book, {"confirmed": {}, "likely": {"INR": 20_000 * M}, "potential": {"INR": 1 * M}})
    _usage(db_session, org.id, tenant.workspace.id, "document.upload", 7, NOW - DAY)
    db_session.commit()
    body = vr.receipt(db_session, org.id, "trial", now=NOW)
    assert [x["key"] for x in body["found"]] == ["time_machine_likely_INR", "time_machine_potential_INR"]
    assert body["headline"] == "In your trial Servabo read 7 documents."


def test_zero_is_left_out(db_session, tenant):
    org = tenant.organization
    put_on_plan(db_session, org, "business")
    org.trial_ends_at = NOW + DAY
    _gst_book(db_session, tenant, tenant.workspace, "W-1", 1000, "WAITING_FOR_SUPPLIER")
    book = _book(db_session, org.id, tenant.workspace)
    _backtest(db_session, book, {"confirmed": {"INR": 0}, "likely": {}, "potential": {"USD": 0}})
    db_session.commit()
    keys = [x["key"] for x in vr.receipt(db_session, org.id, "trial", now=NOW)["found"]]
    assert keys == ["gst_waiting"]          # no at-risk, no claimable, no zero replay, no duplicates, no overcharges


def test_a_plan_without_an_engine_gets_nothing_from_it_and_is_told_what_business_adds(db_session, world):
    put_on_plan(db_session, world.organization, "free")
    vr.forget(world.organization.id)
    body = vr.receipt(db_session, world.organization.id, "trial", now=NOW)
    keys = [x["key"] for x in body["found"]]
    assert keys == ["gst_waiting", "gst_at_risk_180", "gst_claimable", "time_machine_confirmed_INR",
                    "time_machine_likely_INR", "time_machine_potential_INR"]          # radar, matching, Helm: locked
    assert body["also_on_business"] == ["Payment risks", "Prices checked against purchase orders",
                                        "Helm's full planning", "GST's supplier list"]
    assert not any(ch.isdigit() for name in body["also_on_business"] for ch in name)   # names only, never numbers


def test_business_is_not_told_what_business_adds(db_session, world):
    assert vr.receipt(db_session, world.organization.id, "trial", now=NOW)["also_on_business"] == []


def test_the_trial_window_ends_at_the_trials_end_and_starts_fourteen_days_before(db_session, world):
    org = world.organization
    ends = NOW + 2 * DAY
    body = vr.receipt(db_session, org.id, "trial", now=NOW)
    assert datetime.fromisoformat(body["period_start"]) == ends - 14 * DAY  # N-187: a 14-day trial (was 7)
    assert datetime.fromisoformat(body["period_end"]) == NOW
    after = vr.receipt(db_session, org.id, "trial", now=NOW + 5 * DAY)           # the trial is over: the window is fixed
    assert datetime.fromisoformat(after["period_end"]) == ends
    assert after["work"]["documents"] == 5


def test_the_month_is_the_calendar_month_in_the_zone_of_the_oldest_workspace(db_session, tenant):
    org = tenant.organization
    tenant.workspace.timezone = "Asia/Kolkata"
    db_session.commit()
    # 31 Oct 2026 20:00 IST is still October; 18:30 UTC on 31 Oct is 00:00 on 1 Nov in Kolkata.
    now = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)
    start, end, zone = vr.window(org, [tenant.workspace], "month", now)
    assert zone == "Asia/Kolkata"
    assert start == datetime(2026, 9, 30, 18, 30, tzinfo=timezone.utc)      # 1 Oct 00:00 IST
    assert end == datetime(2026, 10, 31, 18, 30, tzinfo=timezone.utc)       # 1 Nov 00:00 IST

    _usage(db_session, org.id, tenant.workspace.id, "document.upload", 1, datetime(2026, 9, 30, 18, 29, tzinfo=timezone.utc))
    _usage(db_session, org.id, tenant.workspace.id, "document.upload", 2, datetime(2026, 9, 30, 18, 31, tzinfo=timezone.utc))
    _usage(db_session, org.id, tenant.workspace.id, "document.upload", 4, datetime(2026, 10, 31, 18, 29, tzinfo=timezone.utc))
    _usage(db_session, org.id, tenant.workspace.id, "document.upload", 8, datetime(2026, 10, 31, 18, 31, tzinfo=timezone.utc))
    db_session.commit()
    assert vr.receipt(db_session, org.id, "month", now=now)["work"]["documents"] == 2 + 4


def test_month_and_trial_read_different_windows(db_session, world):
    org = world.organization
    _usage(db_session, org.id, world.workspace.id, "document.upload", 100, NOW - 3 * DAY)
    db_session.commit()
    assert vr.receipt(db_session, org.id, "trial", now=NOW)["work"]["documents"] == 105
    # a month that began a day ago holds none of the trial's earlier days
    now = NOW.replace(day=1, hour=12) + DAY
    month = vr.receipt(db_session, org.id, "month", now=now)
    assert datetime.fromisoformat(month["period_start"]).day == 1 and month["period"] == "month"
    assert month["headline"] is None or month["headline"].startswith("This month Servabo")


def test_an_unknown_period_is_refused(db_session, world):
    with pytest.raises(vr.ReceiptError):
        vr.receipt(db_session, world.organization.id, "year", now=NOW)


@pytest.mark.parametrize("micros,currency,said", [
    (240_000 * M, "INR", "₹2,40,000"), (12_34_567 * M, "INR", "₹12,34,567"), (3 * 10**13, "INR", "₹3,00,00,000"),
    (1_234 * M, "USD", "$1,234"), (5_000 * M, "AED", "AED 5,000"), (250_000, "INR", "₹0.25"), (0, "INR", "₹0.00"),
])
def test_amounts_are_said_in_indian_grouping_for_rupees(micros, currency, said):
    assert vr.say_amount(micros, currency) == said


def test_the_receipt_reads_and_never_writes(db_session, world):
    before = {t: db_session.execute(__import__("sqlalchemy").text(f"select count(*) from {t}")).scalar_one()
              for t in ("usage_events", "gst_matches", "helm_backtests", "audit_logs", "jobs")}
    vr.receipt(db_session, world.organization.id, "trial", now=NOW)
    after = {t: db_session.execute(__import__("sqlalchemy").text(f"select count(*) from {t}")).scalar_one()
             for t in before}
    assert before == after


def test_an_indian_starter_organization_is_offered_the_add_on_in_rupees(db_session, world):
    """N-187: an organization whose oldest workspace is in India sees the add-on's rupee prices."""
    put_on_plan(db_session, world.organization, "developer")
    for workspace in db_session.query(Workspace).filter(Workspace.organization_id == world.organization.id):
        workspace.timezone = "Asia/Kolkata"
    db_session.flush()
    vr.forget(world.organization.id)
    body = vr.receipt(db_session, world.organization.id, "trial", now=NOW)
    assert body["gst_add_on_line"] == "GST Credit add-on (₹1,499 a month or ₹14,990 a year) or Business: GST's supplier list"


def test_a_developer_organization_is_offered_the_gst_credit_add_on_or_business(db_session, world):
    """Session H: on Developer the GST list is not only a Business feature, it is also a $49 add-on, and the receipt says so."""
    from app.services.billing import addon_service

    put_on_plan(db_session, world.organization, "developer")
    vr.forget(world.organization.id)
    body = vr.receipt(db_session, world.organization.id, "trial", now=NOW)
    # N-187: the catalogue's prices, monthly and yearly, in the organization's currency (dollars here).
    assert body["gst_add_on_line"] == "GST Credit add-on ($49 a month or $490 a year) or Business: GST's supplier list"
    assert "GST's supplier list" not in body["also_on_business"]          # said once, in the add-on's own line
    assert "Helm's full planning" in body["also_on_business"]

    addon_service.record_purchase_state(db_session, organization_id=world.organization.id,
                                        addon_key=entitlements.GST_CREDIT_ADDON, gateway="DODO",
                                        gateway_subscription_id="sub_receipt", gateway_status="active", state_version=1)
    vr.forget(world.organization.id)
    bought = vr.receipt(db_session, world.organization.id, "trial", now=NOW)
    assert bought["gst_add_on_line"] is None and "GST's supplier list" not in bought["also_on_business"]

    put_on_plan(db_session, world.organization, "free")
    vr.forget(world.organization.id)
    free = vr.receipt(db_session, world.organization.id, "trial", now=NOW)
    assert free["gst_add_on_line"] is None and "GST's supplier list" in free["also_on_business"]
