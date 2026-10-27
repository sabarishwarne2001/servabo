"""Owners are told before and when a plan limit runs out (campaign session 3, N-062).

Before: the allowance screen showed "NEAR" and "REACHED", but only to someone looking at it.
An owner learned that documents were being refused when a colleague complained. Now the hourly
`usage.limit_alerts` sweep tells the organization's owners (the people who can change the plan)
once at 80% of a monthly limit (a Usage warning, which a person may turn off) and once when it
is reached (Billing: always emailed), once per meter, limit and month, however often it runs.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.notification import Notification
from app.models.notification_delivery import NotificationDelivery
from app.models.notification import NotificationChannel
from app.services import notification_preferences_service as preferences
from app.services import usage_service
from app.workers.handlers.usage_alerts import run_limit_alerts, run_seat_alerts
from tests.conftest import Fixture
from tests.security.plans import put_on_plan


@pytest.fixture()
def free(db_session: Session, tenant: Fixture) -> Fixture:
    put_on_plan(db_session, tenant.organization, "free")  # 100 document uploads a month (N-187; 25 before)
    db_session.commit()
    return tenant


def _use(db: Session, organization_id: uuid.UUID, quantity: int) -> None:
    usage_service.record_usage(
        db, organization_id=organization_id, event_type="document.upload", quantity=quantity,
        cost_micros=0, provider="internal",
    )
    db.commit()


def _notices(db: Session, organization_id: uuid.UUID) -> list[tuple[str, uuid.UUID]]:
    return [
        (row.title, row.user_id)
        for row in db.execute(
            select(Notification).where(Notification.organization_id == organization_id).order_by(Notification.created_at)
        ).scalars()
    ]


def _emailed(db: Session, organization_id: uuid.UUID) -> list[tuple[str, str]]:
    return [
        (row.payload["title"], row.target)
        for row in db.execute(
            select(NotificationDelivery).where(
                NotificationDelivery.organization_id == organization_id,
                NotificationDelivery.channel == NotificationChannel.EMAIL,
            ).order_by(NotificationDelivery.created_at)
        ).scalars()
    ]


def test_owners_are_warned_once_at_80_percent(db_session: Session, free: Fixture) -> None:
    _use(db_session, free.organization.id, 79)
    run_limit_alerts(db_session)
    assert _notices(db_session, free.organization.id) == [], "79% is not a warning"

    _use(db_session, free.organization.id, 1)  # 80 of 100
    assert run_limit_alerts(db_session)["sent"] == 1
    notices = _notices(db_session, free.organization.id)
    assert notices == [("You have used 80% of this month's document uploads", free.owner.user.id)]
    assert _emailed(db_session, free.organization.id) == [
        ("You have used 80% of this month's document uploads", free.owner.user.email)
    ]
    # The hourly sweep runs again (and on other workers): nothing more is sent.
    assert run_limit_alerts(db_session)["sent"] == 0
    assert len(_notices(db_session, free.organization.id)) == 1


def test_reaching_the_limit_is_always_emailed(db_session: Session, free: Fixture) -> None:
    preferences.set_email(db_session, user_id=free.owner.user.id, category_key=preferences.USAGE, enabled=False)
    db_session.commit()
    _use(db_session, free.organization.id, 84)
    run_limit_alerts(db_session)
    assert _emailed(db_session, free.organization.id) == [], "the owner turned usage warnings off"
    assert len(_notices(db_session, free.organization.id)) == 1, "the in-app notice still appears"

    _use(db_session, free.organization.id, 16)  # 100 of 100
    run_limit_alerts(db_session)
    title = "You have reached this month's document upload limit"
    assert (title, free.owner.user.email) in _emailed(db_session, free.organization.id)
    message = db_session.execute(select(Notification.message).where(Notification.title == title)).scalar_one()
    assert "100 of 100" in message and "Acme Inc." in message
    assert run_limit_alerts(db_session)["sent"] == 0


def test_members_who_cannot_change_the_plan_are_not_emailed(db_session: Session, free: Fixture) -> None:
    _use(db_session, free.organization.id, 100)
    run_limit_alerts(db_session)
    recipients = {user_id for _, user_id in _notices(db_session, free.organization.id)}
    assert recipients == {free.owner.user.id}


def test_an_unused_organization_is_not_looked_at(db_session: Session, free: Fixture) -> None:
    assert run_limit_alerts(db_session) == {"organizations": 0, "sent": 0}


def test_the_sweep_is_scheduled_and_runs_on_a_worker() -> None:
    from app.workers import handlers, profiles, scheduler

    assert "usage.limit_alerts" in handlers._HANDLERS  # noqa: SLF001
    assert any(job.job_type == "usage.limit_alerts" for job in scheduler.DEFAULT_SCHEDULE)
    assert any(
        profile.job_types is not None and "usage.limit_alerts" in profile.job_types
        for profile in profiles.PROFILES.values()
    )


# ---------------------------------------------------------------------- Final session 1 (3B): one click to the place that fixes it


def _action(db: Session, organization_id: uuid.UUID, title: str) -> tuple[str, str, str]:
    row = db.execute(
        select(NotificationDelivery).where(
            NotificationDelivery.organization_id == organization_id,
            NotificationDelivery.channel == NotificationChannel.EMAIL,
        )
    ).scalars().all()
    hit = next(r for r in row if r.payload["title"] == title)
    return hit.payload["action_path"], hit.payload["action_label"], hit.target


def test_the_80_percent_email_goes_to_the_plan_picker_not_the_top_of_billing(db_session: Session, free: Fixture) -> None:
    _use(db_session, free.organization.id, 80)
    run_limit_alerts(db_session)
    path, label, _to = _action(db_session, free.organization.id, "You have used 80% of this month's document uploads")
    assert path == f"/organizations/{free.organization.slug}/billing#plans" and label == "Choose a plan"


def _pay(db: Session, tenant: Fixture, seats: int, plan: str = "business") -> None:
    from datetime import datetime, timedelta, timezone

    from app.models.billing_account import BillingAccount
    from app.models.price_book import PriceBook
    from app.models.subscription import Subscription, SubscriptionStatus

    tier = put_on_plan(db, tenant.organization, plan)
    account = BillingAccount(organization_id=tenant.organization.id, gateway="DODO", currency="USD",
                             billing_email="billing@acme.com", gateway_customer_id=f"cus_{uuid.uuid4().hex[:8]}")
    db.add(account)
    db.flush()
    now = datetime.now(timezone.utc)
    db.add(Subscription(billing_account_id=account.id, gateway="DODO", gateway_subscription_id=f"sub_{uuid.uuid4().hex[:8]}",
                        status=SubscriptionStatus.ACTIVE, quota_tier_key=plan, quota_tier_id=tier.id,
                        price_book_id=db.query(PriceBook).first().id, seats_purchased=seats,
                        current_period_start=now - timedelta(days=5), current_period_end=now + timedelta(days=25)))
    db.commit()


def test_a_team_at_four_of_five_seats_is_told_to_add_seats_by_the_people_who_can(db_session: Session, tenant: Fixture) -> None:
    # The fixture organization holds five seats (owner, administrator and three members).
    _pay(db_session, tenant, seats=6)
    run_seat_alerts(db_session)
    title = "You have used 5 of your 6 seats"
    who = {user_id for t, user_id in _notices(db_session, tenant.organization.id) if t == title}
    assert who == {tenant.owner.user.id, tenant.org_admin.user.id}, "owners and administrators buy seats; members cannot"
    path, label, _to = _action(db_session, tenant.organization.id, title)
    assert path == f"/organizations/{tenant.organization.slug}/billing#seats" and label == "Add seats"
    assert run_seat_alerts(db_session) == 0, "once per capacity and month"


def test_every_seat_taken_is_a_billing_notice_and_buying_a_seat_re_arms_it(db_session: Session, tenant: Fixture) -> None:
    _pay(db_session, tenant, seats=5)
    run_seat_alerts(db_session)
    assert any(t == "Every seat is taken" for t, _u in _notices(db_session, tenant.organization.id))
    from app.models.subscription import Subscription

    db_session.query(Subscription).update({"seats_purchased": 6})
    db_session.commit()
    run_seat_alerts(db_session)
    assert any(t == "You have used 5 of your 6 seats" for t, _u in _notices(db_session, tenant.organization.id))


def test_a_plan_that_cannot_buy_seats_sends_the_owner_to_the_plans_instead(db_session: Session, tenant: Fixture) -> None:
    from app.models.organization import Organization

    put_on_plan(db_session, tenant.organization, "free")
    db_session.query(Organization).filter(Organization.id == tenant.organization.id).update({"seat_limit": 5})
    db_session.commit()
    run_seat_alerts(db_session)
    who = {user_id for t, user_id in _notices(db_session, tenant.organization.id) if t == "Every seat is taken"}
    assert who == {tenant.owner.user.id}
    path, label, _to = _action(db_session, tenant.organization.id, "Every seat is taken")
    assert path.endswith("/billing#plans") and label == "Choose a plan"


def test_a_sole_owner_on_a_one_seat_plan_is_never_told_every_seat_is_taken(db_session: Session) -> None:
    from app.workers.handlers.usage_alerts import _seat_state

    class Cap:
        capacity, used, members, can_purchase = 1, 1, 1, True

    assert _seat_state(Cap()) is None
