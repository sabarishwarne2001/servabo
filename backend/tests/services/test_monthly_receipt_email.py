"""Who gets the monthly summary, when, and how often (Session H, Part 3).

The 1st of each month, from 09:00 in the organization's zone: last month's value receipt, to the owners of a PAYING
organization, only when it holds at least one finding, once per organization per month (recorded), and never to an
owner who turned "Monthly summary" off. Real Postgres; the platform mailer is captured."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.billing_account import BillingAccount
from app.models.notification_preference import MonthlyReceiptSend
from app.models.organization import MembershipStatus, OrganizationMember, OrganizationRole
from app.models.price_book import PriceBook
from app.models.subscription import Subscription, SubscriptionStatus
from app.services import monthly_receipt_email as monthly
from app.services import notification_preferences_service as prefs
from app.services import value_receipt
from tests.security.plans import put_on_plan
from tests.services.test_value_receipt import _bank_change

FIRST = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)
LAST_MONTH = datetime(2026, 9, 15, 10, 0, tzinfo=timezone.utc)


@pytest.fixture()
def outbox(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    from app.core import platform_email

    sent: list[dict] = []

    def capture(*, recipient, subject, html_body, text_body, reply_to=None, **_):
        sent.append({"to": recipient, "subject": subject, "text": text_body, "html": html_body})
        return True, "captured"

    monkeypatch.setattr(platform_email, "send_platform_email", capture)
    return sent


def _pay(db: Session, tenant, plan: str = "business", status=SubscriptionStatus.ACTIVE) -> None:
    tier = put_on_plan(db, tenant.organization, plan)
    account = BillingAccount(organization_id=tenant.organization.id, gateway="DODO", currency="USD",
                             billing_email="billing@acme.com", gateway_customer_id=f"cus_{uuid.uuid4().hex[:8]}")
    db.add(account)
    db.flush()
    sub = f"sub_{uuid.uuid4().hex[:8]}"
    db.add(Subscription(billing_account_id=account.id, gateway="DODO", gateway_subscription_id=sub, status=status,
                        quota_tier_key=plan, quota_tier_id=tier.id, price_book_id=db.query(PriceBook).first().id,
                        seats_purchased=5, current_period_start=FIRST - timedelta(days=20),
                        current_period_end=FIRST + timedelta(days=10)))
    db.flush()


def _found(db: Session, tenant, *, at: datetime = LAST_MONTH) -> None:
    tenant.workspace.timezone = "UTC"
    _bank_change(db, tenant, tenant.workspace, at=at)
    value_receipt.forget(tenant.organization.id)


def _sweep(db: Session, now: datetime = FIRST) -> dict:
    return monthly.run_sweep(db, now=now)


def test_a_paying_organization_with_findings_sends_one_email_per_owner_on_the_first(db_session, tenant, outbox):
    _pay(db_session, tenant)
    _found(db_session, tenant)
    db_session.commit()
    result = _sweep(db_session)
    assert result["organizations"] == 1 and result["emails"] == 1
    assert [m["to"] for m in outbox] == [tenant.owner.user.email]          # an admin is not an owner
    mail = outbox[0]
    assert mail["subject"].endswith("in September 2026") and "Last month" in mail["text"]
    assert "bank-account" in mail["text"].lower()
    assert f"/{tenant.organization.slug}/{tenant.workspace.slug}" in mail["text"]      # the Overview
    row = db_session.execute(select(MonthlyReceiptSend).where(
        MonthlyReceiptSend.organization_id == tenant.organization.id)).scalar_one()
    assert (row.period, row.recipients, row.findings) == ("2026-09", 1, 1)


def test_the_same_month_is_never_sent_twice_even_by_another_run(db_session, tenant, outbox):
    _pay(db_session, tenant)
    _found(db_session, tenant)
    db_session.commit()
    _sweep(db_session)
    again = _sweep(db_session, FIRST + timedelta(hours=3))
    assert again["emails"] == 0 and len(outbox) == 1
    next_month = _sweep(db_session, datetime(2026, 11, 1, 9, 0, tzinfo=timezone.utc))
    assert next_month["emails"] == 0          # October had no finding: nothing to say, and nothing sent
    assert len(outbox) == 1


def test_only_the_first_of_the_month_from_nine_in_the_organizations_own_zone(db_session, tenant, outbox):
    _pay(db_session, tenant)
    _found(db_session, tenant)
    tenant.workspace.timezone = "Asia/Kolkata"
    db_session.commit()
    assert _sweep(db_session, datetime(2026, 10, 1, 3, 0, tzinfo=timezone.utc))["emails"] == 0      # 08:30 in Kolkata
    assert _sweep(db_session, datetime(2026, 10, 2, 9, 0, tzinfo=timezone.utc))["emails"] == 0      # the 2nd
    assert _sweep(db_session, datetime(2026, 9, 30, 20, 0, tzinfo=timezone.utc))["emails"] == 0     # 01:30 on 1 Oct in Kolkata
    assert outbox == []
    assert _sweep(db_session, datetime(2026, 10, 1, 3, 30, tzinfo=timezone.utc))["emails"] == 1     # 09:00 on the 1st in Kolkata


def test_an_organization_that_does_not_pay_gets_nothing(db_session, tenant, outbox):
    put_on_plan(db_session, tenant.organization, "free")          # the trial: no subscription
    _found(db_session, tenant)
    db_session.commit()
    assert _sweep(db_session)["emails"] == 0 and outbox == []
    _pay(db_session, tenant)
    for sub in db_session.execute(select(Subscription)).scalars():       # the customer cancelled
        sub.status, sub.canceled_at = SubscriptionStatus.CANCELED, FIRST - timedelta(days=3)
    db_session.commit()
    assert _sweep(db_session)["emails"] == 0 and outbox == []


def test_a_month_with_no_finding_sends_nothing_and_is_not_asked_again_that_day(db_session, tenant, outbox):
    _pay(db_session, tenant)
    tenant.workspace.timezone = "UTC"
    db_session.commit()
    first = _sweep(db_session)
    assert first["emails"] == 0 and outbox == []
    row = db_session.execute(select(MonthlyReceiptSend).where(
        MonthlyReceiptSend.organization_id == tenant.organization.id)).scalar_one()
    assert (row.period, row.recipients, row.findings) == ("2026-09", 0, 0)          # recorded as looked at, nothing sent
    assert _sweep(db_session, FIRST + timedelta(hours=1))["organizations"] == 0


def test_an_owner_who_turned_monthly_summary_off_is_skipped(db_session, tenant, outbox):
    _pay(db_session, tenant)
    _found(db_session, tenant)
    second = OrganizationMember(organization_id=tenant.organization.id, user_id=tenant.non_member.user.id,
                                role=OrganizationRole.OWNER, status=MembershipStatus.ACTIVE)
    db_session.add(second)
    db_session.flush()
    prefs.set_email(db_session, user_id=tenant.owner.user.id, category_key=prefs.MONTHLY_SUMMARY, enabled=False)
    db_session.commit()
    _sweep(db_session)
    assert [m["to"] for m in outbox] == [tenant.non_member.user.email]
    assert prefs.email_enabled(db_session, user_id=tenant.owner.user.id, category_key=prefs.MONTHLY_SUMMARY) is False
    assert prefs.email_enabled(db_session, user_id=tenant.org_admin.user.id, category_key=prefs.MONTHLY_SUMMARY) is True  # on by default


def test_the_receipt_is_last_months_not_this_months(db_session, tenant, outbox):
    _pay(db_session, tenant)
    _found(db_session, tenant, at=datetime(2026, 10, 1, 8, 0, tzinfo=timezone.utc))      # this month: not last month's
    db_session.commit()
    assert _sweep(db_session)["emails"] == 0
    other = datetime(2026, 12, 1, 9, 0, tzinfo=timezone.utc)
    _found(db_session, tenant, at=datetime(2026, 11, 20, 8, 0, tzinfo=timezone.utc))
    db_session.commit()
    assert _sweep(db_session, other)["emails"] == 1 and outbox[0]["subject"].endswith("in November 2026")


def test_an_email_the_relay_did_not_take_is_tried_again_on_the_next_run(db_session, tenant, monkeypatch):
    from app.core import platform_email

    _pay(db_session, tenant)
    _found(db_session, tenant)
    db_session.commit()
    monkeypatch.setattr(platform_email, "send_platform_email", lambda **_: (False, "relay down"))
    assert _sweep(db_session)["emails"] == 0
    assert db_session.execute(select(MonthlyReceiptSend)).first() is None          # not recorded: it will be retried
    sent: list[str] = []
    monkeypatch.setattr(platform_email, "send_platform_email", lambda **k: (sent.append(k["recipient"]), (True, "ok"))[1])
    assert _sweep(db_session, FIRST + timedelta(hours=1))["emails"] == 1 and sent == [tenant.owner.user.email]


def test_the_category_is_a_switch_for_owners_only_and_is_not_essential(db_session, tenant):
    keys = lambda user: [c["key"] for c in prefs.list_for_user(db_session, user_id=user.user.id)]  # noqa: E731
    assert prefs.MONTHLY_SUMMARY == "monthly_summary" and not prefs.category(prefs.MONTHLY_SUMMARY).essential
    assert prefs.MONTHLY_SUMMARY in keys(tenant.owner)
    assert prefs.MONTHLY_SUMMARY not in keys(tenant.contributor)
