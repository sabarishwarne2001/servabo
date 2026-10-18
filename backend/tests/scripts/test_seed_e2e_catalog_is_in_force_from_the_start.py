"""The browser suite's first catalog is in force before the seed ran (Session B, 4b).

On a freshly rebuilt local database the first browser run's `standIn("subscribe", ...)` failed with
`UnmappableTierError: No published quota tier '...' is in force`, and the next run passed. The seed
published the plans with `effective_from` = the instant it ran (to the microsecond), while a
subscription is pinned to the plan in force at its period start, which the stand-in's gateway states in
whole seconds or a moment earlier: within the second after the seed the plan "did not exist yet".
CI seeds a fresh database every run and never met it. The first catalog is now in force from the start
of the epoch the suite uses, so the order of seed and subscription no longer matters.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session

from app.services.billing.subscription_service import resolve_price_book, resolve_tier_version
from scripts import seed_e2e

PLANS = ("free", "developer", "business", "enterprise")


@pytest.mark.parametrize("ago", [timedelta(seconds=0), timedelta(seconds=1), timedelta(minutes=5), timedelta(days=30)])
def test_every_plan_is_in_force_at_any_recent_moment_after_the_first_seed(db_session: Session, ago: timedelta) -> None:
    seed_e2e.seed(db_session)
    moment = datetime.now(timezone.utc) - ago
    db_session.expire_all()
    for plan in PLANS:
        assert resolve_tier_version(db_session, tier_key=plan, at=moment).key == plan
    assert resolve_price_book(db_session, at=moment) is not None


def test_a_second_seed_does_not_move_the_start_of_the_catalog(db_session: Session) -> None:
    seed_e2e.seed(db_session)
    first = {plan: resolve_tier_version(db_session, tier_key=plan).effective_from for plan in PLANS}
    seed_e2e.seed(db_session)
    db_session.expire_all()
    assert {plan: resolve_tier_version(db_session, tier_key=plan).effective_from for plan in PLANS} == first
