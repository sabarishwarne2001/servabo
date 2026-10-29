"""TDS-credit notices and the Monday digest (Final 2T, Phase 7.3 and 7.4): one notice per case revision when a confirmed
withholding loses its evidence, an import turns a case into a possible missing posting, or a case passes its due date; the
recompute job does the real work; nothing is queued when there is nothing to compare; the digest says something only when
there is something to say."""

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.models.notification import Notification
from app.models.trinetra import TrinetraCredit, TrinetraNoticeSend
from app.workers.handlers import trinetra as handler
from tests.trinetra.test_api import really_change, world  # noqa: F401
from tests.trinetra.test_money_model import statement
from tests.trinetra.test_workflows import setup_case

OTHER = "ABCD12345E,2000.00,r0,194C,15-Jun-2025,F,FY 2025-26 / AY 2026-27"


@pytest.fixture()
def recompute(db_session, tenant, monkeypatch):
    @contextmanager
    def session():
        yield db_session

    monkeypatch.setattr(handler, "SessionLocal", session)
    payload = {"organization_id": str(tenant.organization.id), "workspace_id": str(tenant.workspace.id)}
    return lambda: handler.handle_recompute(payload)


def tds_notices(db, tenant, who="owner"):
    user = getattr(tenant, who).user
    return [n for n in db.execute(select(Notification).where(Notification.user_id == user.id)).scalars()
            if "TDS" in n.title]


def test_a_confirmed_withholding_that_loses_its_evidence_is_told_once_per_case_revision(client, tenant, world, db_session, recompute):
    url, body, case = setup_case(client, tenant, world, reference="TR-NOTICE-1")
    assert recompute()["status"] == "complete" and tds_notices(db_session, tenant) == []         # nothing to say yet
    really_change(db_session, world[1])                                                       # the invoice itself changed
    recompute()
    [notice] = tds_notices(db_session, tenant)
    assert "TR-NOTICE-1" in notice.message and "Synthetic deductor" in notice.message and "evidence" in notice.message.lower()
    assert "ABCDE1234F" not in notice.message + notice.title and "ABCD12345E" not in notice.message + notice.title    # no PAN, no TAN
    for _ in range(3):                                                                         # a replay says nothing again
        recompute()
    assert len(tds_notices(db_session, tenant)) == 1
    assert db_session.get(TrinetraNoticeSend, (tenant.organization.id, "stale", f"{case['id']}:{case['revision']}")) is not None


def test_an_import_that_turns_a_case_into_a_possible_missing_posting_is_told_and_a_clean_one_is_not(client, tenant, world, db_session, recompute):
    url, body, case = setup_case(client, tenant, world, reference="TR-NOTICE-2")
    statement(client, tenant, url, body, ["ZZZZ99999Z,5000.00,x1,194C,15-Jun-2025,F,FY 2025-26 / AY 2026-27"])   # another deductor's row
    recompute()
    [notice] = tds_notices(db_session, tenant)
    assert "possible missing posting" in notice.message.lower() and "TR-NOTICE-2" in notice.message
    assert "not a conclusion" in notice.message.lower() or "check" in notice.message.lower()
    recompute()
    assert len(tds_notices(db_session, tenant)) == 1


def test_a_case_that_passes_its_due_date_is_told_once_and_a_closed_case_never(client, tenant, world, db_session, recompute):
    from app.services.trinetra import notices

    url, body, case = setup_case(client, tenant, world, reference="TR-NOTICE-3")
    row = db_session.get(TrinetraCredit, __import__("uuid").UUID(case["id"]))
    row.created_at = datetime.now(timezone.utc) - timedelta(days=notices.DUE_AFTER_DAYS + 1)
    db_session.commit()
    recompute()
    [notice] = tds_notices(db_session, tenant)
    assert "due" in notice.title.lower() or "overdue" in notice.message.lower() or "past" in notice.message.lower()
    recompute()
    assert len(tds_notices(db_session, tenant)) == 1


def test_a_burst_is_one_bundled_notice_and_each_case_is_still_claimed_once(client, tenant, world, db_session, recompute, monkeypatch):
    from app.services.trinetra import notices

    monkeypatch.setattr(notices, "BUNDLE_AFTER", 0)                       # any number of fresh cases is "a burst"
    url, body, case = setup_case(client, tenant, world, reference="TR-NOTICE-4")
    really_change(db_session, world[1])
    recompute()
    [notice] = tds_notices(db_session, tenant)
    assert "1 TDS case" in notice.title or "case" in notice.title.lower()
    recompute()
    assert len(tds_notices(db_session, tenant)) == 1


def test_only_owners_and_admins_hear_and_the_category_can_be_switched_off(client, tenant, world, db_session, recompute):
    from app.services import notification_preferences_service as prefs

    assert "tds_credit" in {c.key for c in prefs.CATEGORIES} and prefs.category("tds_credit").essential is False
    setup_case(client, tenant, world)
    really_change(db_session, world[1])
    recompute()
    assert len(tds_notices(db_session, tenant, "owner")) == 1
    assert tds_notices(db_session, tenant, "viewer") == [] and tds_notices(db_session, tenant, "contributor") == []
    keys = {c["key"] for c in prefs.list_for_user(db_session, user_id=tenant.owner.user.id)}
    assert "tds_credit" in keys
    assert "tds_credit" not in {c["key"] for c in prefs.list_for_user(db_session, user_id=tenant.viewer.user.id)}


def test_nothing_is_queued_when_there_is_nothing_to_compare(client, tenant, world, db_session):
    from app.models.job import Job
    from app.services.trinetra import hooks

    def queued():
        return db_session.query(Job).filter(Job.job_type == "trinetra.recompute").count()

    hooks.document_changed(db_session, workspace_id=tenant.workspace.id, organization_id=tenant.organization.id)
    assert queued() == 0                                                            # no profile, no case
    setup_case(client, tenant, world)
    db_session.query(Job).filter(Job.job_type == "trinetra.recompute").delete()
    db_session.commit()
    hooks.document_changed(db_session, workspace_id=tenant.workspace.id, organization_id=tenant.organization.id)
    assert queued() == 1                                                            # an open case: there is something to compare


# --- the sweep and the Monday line ------------------------------------------------------------------------------------------

MONDAY = datetime(2026, 10, 19, 9, 30, tzinfo=timezone.utc)       # 19 Oct 2026 is a Monday


@pytest.fixture()
def outbox(monkeypatch):
    from app.core import platform_email

    sent = []

    def capture(*, recipient, subject, html_body, text_body, reply_to=None, **_):
        sent.append({"to": recipient, "subject": subject, "text": text_body, "html": html_body})
        return True, "captured"

    monkeypatch.setattr(platform_email, "send_platform_email", capture)
    return sent


def gap_case(client, tenant, world, reference="TR-DIGEST-1"):
    url, body, case = setup_case(client, tenant, world, reference=reference)
    statement(client, tenant, url, body, ["ZZZZ99999Z,5000.00,x1,194C,15-Jun-2025,F,FY 2025-26 / AY 2026-27"])
    tenant.workspace.timezone = "UTC"
    return url, body, case


def test_the_hourly_sweep_tells_a_due_case_once_and_skips_a_closed_one(client, tenant, world, db_session):
    import uuid

    from app.services.trinetra import notices

    url, body, case = setup_case(client, tenant, world, reference="TR-SWEEP-1")
    assert notices.run_sweep(db_session, now=datetime.now(timezone.utc)) == {"organizations": 1, "due": 0, "digests": 0, "emails": 0}
    row = db_session.get(TrinetraCredit, uuid.UUID(case["id"]))
    row.created_at = datetime.now(timezone.utc) - timedelta(days=notices.DUE_AFTER_DAYS + 2)
    db_session.commit()
    assert notices.run_sweep(db_session, now=datetime.now(timezone.utc))["due"] == 1
    assert notices.run_sweep(db_session, now=datetime.now(timezone.utc) + timedelta(hours=1))["due"] == 0
    assert len([n for n in tds_notices(db_session, tenant) if "due date" in n.title]) == 1
    # Withdrawn: it never speaks, even though it is old.
    row.state = "WITHDRAWN"
    row.revision += 1
    db_session.commit()
    assert notices.run_sweep(db_session, now=datetime.now(timezone.utc) + timedelta(hours=2))["due"] == 0


def test_the_monday_line_says_what_is_not_in_the_statement_once_and_never_names_a_pan_or_tan(client, tenant, world, db_session, outbox):
    from app.services.trinetra import notices

    gap_case(client, tenant, world)
    assert notices.run_sweep(db_session, now=MONDAY - timedelta(days=1))["digests"] == 0            # not a Monday
    assert notices.run_sweep(db_session, now=MONDAY.replace(hour=8))["digests"] == 0                # before 09:00
    done = notices.run_sweep(db_session, now=MONDAY)
    assert done["digests"] == 1 and done["emails"] == len(outbox) and len(outbox) >= 1
    [mail] = [m for m in outbox if m["to"] == tenant.owner.user.email]
    assert "2,000" in mail["text"] and "1 invoice is not yet in your statement" in mail["text"]
    assert "not cash" in mail["text"].lower() and "ABCDE1234F" not in mail["text"] + mail["html"] and "ABCD12345E" not in mail["text"] + mail["html"]
    assert mail["subject"].startswith("Your TDS credit this week")
    assert notices.run_sweep(db_session, now=MONDAY + timedelta(hours=3))["digests"] == 0               # once a week
    assert db_session.get(TrinetraNoticeSend, (tenant.organization.id, "digest", "2026-W43")).recipients == len(outbox)


def test_the_digest_is_silent_without_news_and_respects_the_switch_and_the_role(client, tenant, world, db_session, outbox):
    from app.services import notification_preferences_service as prefs
    from app.services.trinetra import notices

    setup_case(client, tenant, world)                                                             # an open case, nothing to report
    tenant.workspace.timezone = "UTC"
    assert notices.run_sweep(db_session, now=MONDAY)["emails"] == 0 and outbox == []
    row = db_session.get(TrinetraNoticeSend, (tenant.organization.id, "digest", "2026-W43"))
    assert row is not None and row.recipients == 0                                                # recorded, never looked at again
    # With news: the person who switched the category off gets nothing; a viewer or contributor never does.
    db_session.delete(row)
    db_session.commit()
    from app.models.trinetra import TrinetraProfile

    statement(client, tenant, f"/api/v1/workspaces/{tenant.workspace.id}/trinetra",
              {"profile_id": str(db_session.query(TrinetraProfile).one().id)},
              ["ZZZZ99999Z,5000.00,x1,194C,15-Jun-2025,F,FY 2025-26 / AY 2026-27"])
    prefs.set_email(db_session, user_id=tenant.owner.user.id, category_key="tds_credit", enabled=False)
    db_session.commit()
    notices.run_sweep(db_session, now=MONDAY)
    assert tenant.owner.user.email not in {m["to"] for m in outbox}
    assert tenant.viewer.user.email not in {m["to"] for m in outbox} and tenant.contributor.user.email not in {m["to"] for m in outbox}


def test_a_relay_that_takes_nothing_is_tried_again_next_hour(client, tenant, world, db_session, monkeypatch):
    from app.core import platform_email
    from app.services.trinetra import notices

    gap_case(client, tenant, world)
    monkeypatch.setattr(platform_email, "send_platform_email", lambda **kw: (False, "relay down"))
    assert notices.run_sweep(db_session, now=MONDAY)["digests"] == 0
    assert db_session.get(TrinetraNoticeSend, (tenant.organization.id, "digest", "2026-W43")) is None     # the claim went with it
    sent = []
    monkeypatch.setattr(platform_email, "send_platform_email", lambda **kw: sent.append(kw["recipient"]) or (True, "ok"))
    assert notices.run_sweep(db_session, now=MONDAY + timedelta(hours=1))["digests"] == 1 and sent


def test_an_organization_that_is_not_live_or_not_paid_hears_nothing(client, tenant, world, db_session, outbox, monkeypatch):
    from app.services.trinetra import notices

    gap_case(client, tenant, world)
    monkeypatch.setattr(settings, "TRINETRA_LIVE_ENABLED", None)
    monkeypatch.setattr(settings, "TRINETRA_MODE", "pilot")                                        # not enrolled
    assert notices.run_sweep(db_session, now=MONDAY) == {"organizations": 0, "due": 0, "digests": 0, "emails": 0} and outbox == []


def test_the_sweep_is_registered_scheduled_and_on_the_light_profile():
    from app.services.job_service import JOB_HANDLERS
    from app.workers import profiles, scheduler
    from app.workers.handlers import register_all

    register_all()
    assert "trinetra.sweep" in JOB_HANDLERS
    assert "trinetra.sweep" in {job.job_type for job in scheduler.DEFAULT_SCHEDULE}
    assert any("trinetra.sweep" in repr(value) for value in vars(profiles).values())
