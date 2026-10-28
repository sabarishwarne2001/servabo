"""No PAN or TAN reaches a log, a URL, an event, an email, a notice or an export unmasked (Final 2T, Phase 9). One whole journey is
run (profile, case, statement, allocation, review, inquiry, closure, notices, the Monday line, rules and webhooks, Recoveries, the
warehouse dataset, every export), with every log record captured and every place a value can go searched for the two identifiers.
The identifiers are typed by the person in request bodies, which is the only place they may appear."""

import io
import json
import logging
import zipfile
from datetime import datetime, timedelta, timezone

from app.models.automation import AutomationRule
from app.models.automation_trigger import AutomationRuleTrigger
from app.models.notification import Notification
from app.models.outbox_event import OutboxEvent
from app.models.webhook_endpoint import WebhookEndpoint
from tests.security.plans import put_on_plan
from tests.trinetra.test_api import world  # noqa: F401
from tests.trinetra.test_money_model import allocate, decide, get, statement
from tests.trinetra.test_resolution import customer, draft, mailbox, step  # noqa: F401
from tests.trinetra.test_workflows import setup_case

PAN, TAN = "ABCDE1234F", "ABCD12345E"
OTHER = "MUMB54321K"


def clean(label, text):
    for secret in (PAN, TAN):
        assert secret not in text, f"{secret} reached {label}"


def test_no_pan_or_tan_reaches_a_log_a_url_an_event_an_email_a_notice_or_an_export(client, tenant, world, db_session, mailbox, caplog):
    from app.services import notification_preferences_service as prefs
    from app.services.analytics import export_engine
    from app.services.recoveries import service as recoveries
    from app.services.trinetra import notices

    caplog.set_level(logging.DEBUG)
    put_on_plan(db_session, tenant.organization, "enterprise")
    db_session.add(WebhookEndpoint(organization_id=tenant.organization.id, url="https://example.invalid/hook", secret_encrypted="x",
                                   event_types=["trinetra.case.gap_found", "trinetra.case.closed", "trinetra.case.reviewed"]))
    rule = AutomationRule(name="TDS", event="DOCUMENT_UPLOADED", workspace_id=tenant.workspace.id)
    db_session.add(rule)
    db_session.flush()
    for event in ("trinetra.case.gap_found", "trinetra.case.closed"):
        db_session.add(AutomationRuleTrigger(rule_id=rule.id, event_type=f"trigger.{event}", workspace_id=tenant.workspace.id))
    db_session.commit()
    visible = []                                                                   # every response body a person could read

    url, body, case = setup_case(client, tenant, world, reference="TR-PRIV-1")
    customer(db_session, tenant)
    snap = statement(client, tenant, url, body, [f"{OTHER},10.00,x0,194C,15-Jun-2025,F,FY 2025-26 / AY 2026-27"])   # a gap
    from app.services.trinetra import notices as n

    n.announce(db_session, tenant.workspace, __import__("app.services.trinetra.service", fromlist=["x"]).summary(db_session, tenant.workspace)["items"])
    db_session.commit()                                                           # as the recompute job commits what it announced
    notices.run_sweep(db_session, now=datetime(2026, 10, 19, 9, 30, tzinfo=timezone.utc))
    recoveries.sweep(db_session, tenant.workspace, heavy=True)
    db_session.commit()

    made = draft(client, tenant, url, case, document_kind="CERTIFICATE").json()
    step(client, tenant, url, made, "approve")
    step(client, tenant, url, made, "send")
    second = statement(client, tenant, url, body, [f"{TAN},2000.00,y0,194C,15-Jun-2025,F,FY 2025-26 / AY 2026-27"])
    done = decide(client, tenant, url, get(client, tenant, url, case), "ALLOCATE", allocations=[allocate(second, 0, "2000")])
    decide(client, tenant, url, done.json(), "CA_REVIEWED", reason="Accountant confirmed it in the new statement.")

    for path in ("", "/summary", "/credits", f"/credits/{case['id']}", "/suggestions", "/deductors", "/exceptions", "/outcomes", "/policy",
                 "/approvals", "/access", "/profiles", f"/credits/{case['id']}/inquiries", "/inquiry-draft".join(["/credits/" + case["id"], ""])):
        r = client.get(url + path, headers=tenant.owner.headers)
        if r.status_code == 200:
            visible.append((path, r.text))
    org = f"/api/v1/organizations/{tenant.organization.id}"
    for path in ("/trinetra/summary", "/trinetra/cases", "/trinetra/access", "/search?q=TR-PRIV"):
        r = client.get(org + path, headers=tenant.owner.headers)
        if r.status_code == 200:
            visible.append((path, r.text))
    for fmt in ("csv", "xlsx", "html"):
        exported = client.get(url + f"/export.{fmt}", headers=tenant.owner.headers)
        assert exported.status_code == 200
        text = exported.content.decode("utf-8", "ignore") if fmt != "xlsx" else "".join(
            zipfile.ZipFile(io.BytesIO(exported.content)).read(name).decode("utf-8", "ignore")
            for name in zipfile.ZipFile(io.BytesIO(exported.content)).namelist())
        visible.append((f"export.{fmt}", text))
    for fmt in ("csv", "xlsx"):
        for template in ("statement-template", "suggestion-template"):
            assert client.get(url + f"/{template}.{fmt}", headers=tenant.owner.headers).status_code == 200
    rows = export_engine.extract_dataset(db_session, "TRINETRA_CASES", organization_id=tenant.organization.id,
                                         window_start=datetime(2000, 1, 1, tzinfo=timezone.utc), window_end=datetime.now(timezone.utc) + timedelta(days=1))
    visible.append(("warehouse dataset", json.dumps(rows, default=str)))

    for label, text in visible:
        clean(label, text.replace(f"******{PAN[-4:]}", "").replace(f"******{TAN[-4:]}", ""))
    for event in db_session.query(OutboxEvent).filter_by(organization_id=tenant.organization.id):
        clean(f"event {event.event_type}", json.dumps(event.payload, default=str))
    for notice in db_session.query(Notification):
        clean("a notification", f"{notice.title} {notice.message}")
    for mail in mailbox:
        clean("an email", mail["subject"] + mail["text"] + mail["html"])
    clean("a log", caplog.text)
    assert prefs.TDS_CREDIT == "tds_credit" and visible and mailbox
    kinds = sorted({e.event_type for e in db_session.query(OutboxEvent).filter_by(organization_id=tenant.organization.id)})
    assert "trinetra.case.gap_found" in kinds and "trigger.trinetra.case.gap_found" in kinds, kinds
