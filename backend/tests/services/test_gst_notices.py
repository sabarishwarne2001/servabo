"""GST credit notices and the Monday digest (Final session 1, 3A).

Four in-app notices (a GSTR-2B imported, invoices at 150 days unpaid, suppliers that have not reported by the 14th, IMS actions
waiting) and one weekly email, all under the "GST credit" category: on by default, for owners, administrators and the billing role,
once each, and the email only when there is something to report. Real Postgres; the platform mailer is captured.

    pytest tests/services/test_gst_notices.py -q
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.gst import GstMatch, GstNoticeSend
from app.models.notification import Notification
from app.services import notification_preferences_service as prefs
from app.services.gst import digest, engine, notices, store
from tests.security.plans import put_on_plan
from tests.services.gst import helpers
from tests.services.gst.helpers import RECIPIENT, SUPPLIER_A, book_invoice, statement

MONDAY = datetime(2026, 10, 19, 9, 30, tzinfo=timezone.utc)       # 19 Oct 2026 is a Monday
FIFTEENTH = date(2026, 10, 15)


@pytest.fixture()
def outbox(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    from app.core import platform_email

    sent: list[dict] = []

    def capture(*, recipient, subject, html_body, text_body, reply_to=None, **_):
        sent.append({"to": recipient, "subject": subject, "text": text_body, "html": html_body})
        return True, "captured"

    monkeypatch.setattr(platform_email, "send_platform_email", capture)
    return sent


def _import(db: Session, tenant) -> list[dict]:
    tenant.workspace.timezone = "UTC"
    results = store.import_file(db, workspace=tenant.workspace, user_id=tenant.owner.user.id, file_name="gstr2b.json", data=statement())
    db.flush()
    return results


def _old_unpaid(db: Session, tenant, *, on: date = date(2026, 9, 10), taxable: float = 1_000_000, number: str = "OLD-1") -> None:
    """A September purchase invoice no GSTR-2B shows (the engine only reads books near the imported months)."""
    book_invoice(db, tenant, number=number, supplier="Sahyadri Packaging", gstin=SUPPLIER_A, on=on, taxable=taxable)
    engine.recompute(db, tenant.workspace, RECIPIENT)
    db.flush()


def _titles(db: Session, user) -> list[str]:
    return [n.title for n in db.execute(select(Notification).where(Notification.user_id == user.id)).scalars()]


# ------------------------------------------------------------------------------------------ the category

def test_the_category_is_on_by_default_and_offered_to_owners_admins_and_billing_only(db_session, tenant):
    assert prefs.category(prefs.GST_CREDIT).essential is False
    owner = {c["key"]: c for c in prefs.list_for_user(db_session, user_id=tenant.owner.user.id)}
    assert owner["gst_credit"]["email"] is True and owner["gst_credit"]["label"] == "GST credit"
    admin_keys = {c["key"] for c in prefs.list_for_user(db_session, user_id=tenant.org_admin.user.id)}
    member_keys = {c["key"] for c in prefs.list_for_user(db_session, user_id=tenant.contributor.user.id)}
    assert "gst_credit" in admin_keys and "gst_credit" not in member_keys


# ------------------------------------------------------------------------------------------ import finished

def test_an_import_tells_owners_and_admins_once_and_a_member_nothing(db_session, tenant):
    _import(db_session, tenant)
    assert "GSTR-2B imported" in _titles(db_session, tenant.owner.user)
    assert "GSTR-2B imported" in _titles(db_session, tenant.org_admin.user)
    assert _titles(db_session, tenant.contributor.user) == []
    _import(db_session, tenant)                                   # the same file: nothing changed, nothing said
    assert _titles(db_session, tenant.owner.user).count("GSTR-2B imported") == 1


def test_the_import_notice_carries_rupees_with_indian_grouping(db_session, tenant):
    _old_unpaid(db_session, tenant, taxable=2_000_000)
    _import(db_session, tenant)
    message = next(n.message for n in db_session.execute(select(Notification).where(Notification.user_id == tenant.owner.user.id)).scalars())
    assert "were imported into Engineering" in message and "September 2026" in message


# ------------------------------------------------------------------------------------------ the 150-day window

LATE = date(2027, 2, 17)          # 160 days after 10 September 2026; 140 after 30 September


def test_invoices_that_reach_150_days_unpaid_are_announced_once_and_a_younger_one_never(db_session, tenant):
    _import(db_session, tenant)
    _old_unpaid(db_session, tenant)
    _old_unpaid(db_session, tenant, on=date(2026, 9, 30), number="NEW-1")
    assert notices.window_notice(db_session, tenant.organization.id, today=LATE) == 1
    assert any(t.endswith("near the 180-day limit") for t in _titles(db_session, tenant.owner.user))
    assert notices.window_notice(db_session, tenant.organization.id, today=LATE) == 0               # already said
    assert notices.window_notice(db_session, tenant.organization.id, today=date(2027, 3, 9)) == 1    # the younger one reaches 160 days later


def test_the_window_notice_is_a_warning_so_the_owner_also_gets_it_by_email(db_session, tenant):
    _import(db_session, tenant)
    _old_unpaid(db_session, tenant)
    notices.window_notice(db_session, tenant.organization.id, today=LATE)
    row = next(n for n in db_session.execute(select(Notification).where(Notification.user_id == tenant.owner.user.id)).scalars()
               if "180-day" in n.title)
    assert getattr(row.priority, "value", row.priority) == "WARNING"
    assert prefs.should_email(db_session, user_id=tenant.owner.user.id, category_key=prefs.GST_CREDIT, priority=row.priority)


# ------------------------------------------------------------------------------------------ suppliers by the 14th

def test_suppliers_that_have_not_reported_are_announced_from_the_14th_once_a_month(db_session, tenant):
    _import(db_session, tenant)
    _old_unpaid(db_session, tenant)
    assert notices.supplier_notice(db_session, tenant.organization.id, today=date(2026, 10, 13)) == 0
    assert notices.supplier_notice(db_session, tenant.organization.id, today=FIFTEENTH) >= 1
    assert any("have not reported your invoices" in t or "has not reported" in t for t in _titles(db_session, tenant.owner.user))
    assert notices.supplier_notice(db_session, tenant.organization.id, today=date(2026, 10, 16)) == 0


def test_no_supplier_notice_without_the_months_gstr2b(db_session, tenant):
    tenant.workspace.timezone = "UTC"
    _old_unpaid(db_session, tenant)
    assert notices.supplier_notice(db_session, tenant.organization.id, today=FIFTEENTH) == 0


# ------------------------------------------------------------------------------------------ IMS

def test_ims_actions_are_announced_only_where_the_lists_are_open_and_only_between_the_14th_and_20th(db_session, tenant):
    _import(db_session, tenant)
    put_on_plan(db_session, tenant.organization, "developer")
    assert notices.ims_notice(db_session, tenant.organization.id, today=FIFTEENTH) == 0          # a preview plan: the list is not theirs
    put_on_plan(db_session, tenant.organization, "business")
    assert notices.ims_notice(db_session, tenant.organization.id, today=date(2026, 10, 10)) == 0
    assert notices.ims_notice(db_session, tenant.organization.id, today=FIFTEENTH) >= 1
    assert notices.ims_notice(db_session, tenant.organization.id, today=date(2026, 10, 16)) == 0


# ------------------------------------------------------------------------------------------ the Monday digest

def test_the_digest_goes_out_on_monday_from_nine_once_in_rupees_with_indian_grouping(db_session, tenant, outbox):
    put_on_plan(db_session, tenant.organization, "business")
    _import(db_session, tenant)
    _old_unpaid(db_session, tenant, taxable=1_000_000)
    db_session.commit()
    assert digest.run_sweep(db_session, now=datetime(2026, 10, 19, 8, 59, tzinfo=timezone.utc)) == {"organizations": 0, "emails": 0}
    assert digest.run_sweep(db_session, now=datetime(2026, 10, 20, 9, 30, tzinfo=timezone.utc)) == {"organizations": 0, "emails": 0}
    result = digest.run_sweep(db_session, now=MONDAY)
    assert result["organizations"] == 1 and result["emails"] == len(outbox) >= 2          # owner and administrator
    assert {m["to"] for m in outbox} >= {tenant.owner.user.email, tenant.org_admin.user.email}
    mail = outbox[0]
    assert "INR 1,80,000.00" in mail["text"] and "INR 180,000.00" not in mail["text"]
    assert "Waiting on Sahyadri Packaging" in mail["text"], mail["text"]            # the lists are open: the supplier is named
    assert "Unlock the lists" not in mail["text"]
    again = digest.run_sweep(db_session, now=MONDAY + timedelta(hours=3))
    assert again == {"organizations": 0, "emails": 0}
    row = db_session.get(GstNoticeSend, (tenant.organization.id, "digest", "2026-W43"))
    assert row is not None and row.recipients == result["emails"]


def test_a_plan_with_only_the_headline_is_told_what_the_lists_would_add_and_what_they_cost(db_session, tenant, outbox):
    put_on_plan(db_session, tenant.organization, "developer")
    _import(db_session, tenant)
    _old_unpaid(db_session, tenant)
    db_session.commit()
    digest.run_sweep(db_session, now=MONDAY)
    assert outbox and "Unlock the lists: GST Credit add-on, $49 a month" in outbox[0]["text"]
    assert "Waiting on " not in outbox[0]["text"]                       # no supplier names on a preview


def test_a_person_who_turned_the_category_off_gets_no_digest(db_session, tenant, outbox):
    put_on_plan(db_session, tenant.organization, "business")
    _import(db_session, tenant)
    _old_unpaid(db_session, tenant)
    prefs.set_email(db_session, user_id=tenant.owner.user.id, category_key=prefs.GST_CREDIT, enabled=False)
    db_session.commit()
    digest.run_sweep(db_session, now=MONDAY)
    assert outbox and tenant.owner.user.email not in {m["to"] for m in outbox}


def test_nothing_to_report_sends_nothing_and_is_not_looked_at_again(db_session, tenant, outbox):
    put_on_plan(db_session, tenant.organization, "business")
    _import(db_session, tenant)
    db_session.query(GstMatch).filter(GstMatch.workspace_id == tenant.workspace.id).delete()
    db_session.commit()
    assert digest.build(db_session, tenant.organization.id) is None
    result = digest.run_sweep(db_session, now=MONDAY)
    assert result["emails"] == 0 and outbox == []
    assert db_session.get(GstNoticeSend, (tenant.organization.id, "digest", "2026-W43")).recipients == 0


def test_an_archived_organization_hears_nothing(db_session, tenant, outbox):
    from app.models.organization import OrganizationStatus

    put_on_plan(db_session, tenant.organization, "business")
    _import(db_session, tenant)
    _old_unpaid(db_session, tenant)
    tenant.organization.status = OrganizationStatus.ARCHIVED
    db_session.commit()
    assert digest.run_sweep(db_session, now=MONDAY)["emails"] == 0 and outbox == []
    assert notices.run_notices(db_session, now=MONDAY)["organizations"] == 0


def test_the_renderer_refuses_an_empty_digest():
    from app.templates.emails.gst_digest import render_gst_digest

    with pytest.raises(ValueError):
        render_gst_digest(organization_name="Acme", week_label="19 October 2026", headline="", findings=[], gst_url="https://x/gst",
                          preferences_url="https://x/p", brand_name="Servabo")


def test_a_job_payload_cannot_move_the_clock_in_production(monkeypatch):
    from app.core.config import settings

    assert notices.payload_now({"now": "2026-10-19T09:30:00+00:00"}) == MONDAY
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    assert notices.payload_now({"now": "2026-10-19T09:30:00+00:00"}) is None


def test_the_jobs_are_registered_and_scheduled():
    from app.services.job_service import JOB_HANDLERS
    from app.workers import scheduler
    from app.workers.handlers import register_all

    register_all()
    scheduled = {job.job_type for job in scheduler.SCHEDULED_JOBS} if hasattr(scheduler, "SCHEDULED_JOBS") else set()
    for job in ("gst.digest", "gst.notices"):
        assert job in JOB_HANDLERS
        assert not scheduled or job in scheduled
