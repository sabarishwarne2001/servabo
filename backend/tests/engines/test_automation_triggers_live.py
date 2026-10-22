"""Session J, Phase 2 — the engines are automation triggers, each firing exactly once per occurrence, live.

For every trigger: a rule on it (notify the admins) is saved, the thing happens through the real engine, the worker runs
the rule, and the rule's run history shows ONE run. The same occurrence again (a re-scan, the same file, the same sweep
next hour) adds none. A workspace with no rule on a trigger gets no event row at all.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, Optional

from sqlalchemy import func, select

from app.models.outbox_event import OutboxEvent
from app.services.automation import emitters, sweeps
from tests.engines.conftest import Engines, drain
from tests.engines.test_truthmesh_live import _load as load_mesh


def _rule(engines: Engines, trigger: str, name: str, *, conditions: Optional[list[dict[str, Any]]] = None,
          message: str = "{{trigger.label}}", expect: int = 201) -> dict[str, Any]:
    body = {
        "name": name, "triggers": [trigger], "groups_operator": "AND",
        "condition_groups": [{"logic_operator": "AND", "conditions": conditions}] if conditions else [],
        "actions": [{"action_type": "notify.role", "config": {"roles": ["ADMIN"], "title": f"{name} ran", "message": message}}],
    }
    response = engines.post("/automation/rules", body)
    assert response.status_code == expect, response.text
    return response.json()


def _runs(engines: Engines, rule_id: str) -> list[dict[str, Any]]:
    page = engines.get("/automation/executions", params={"rule_id": rule_id, "limit": 200}).json()
    return page["items"]


def _event_count(engines: Engines, event_type: str) -> int:
    engines.refresh()
    return int(engines.db.execute(select(func.count()).select_from(OutboxEvent).where(
        OutboxEvent.workspace_id == engines.ws, OutboxEvent.event_type == event_type)).scalar_one())


def _sweep(engines: Engines, at: datetime) -> dict[str, Any]:
    with engines.db.begin_nested():
        result = sweeps.run(engines.db, now=at)
    engines.db.commit()
    drain()
    return result


# ------------------------------------------------------------------------------------------------------ manual


def test_a_manual_run_runs_exactly_the_chosen_rule_on_the_chosen_document(engines: Engines) -> None:
    chosen = _rule(engines, "manual", "Hand rule A")
    other = _rule(engines, "manual", "Hand rule B")
    document = engines.process("hand.pdf", [["TAX INVOICE", "Invoice Number: INV-HAND-1"]], marker="INV-HAND-1",
                               classification="Invoice", entities={"invoice_number": "INV-HAND-1"})

    ran = engines.post(f"/automation/rules/{chosen['id']}/run", {"work_item_id": str(document)})
    assert ran.status_code == 202, ran.text
    drain()
    runs = _runs(engines, chosen["id"])
    assert len(runs) == 1 and str(runs[0]["work_item_id"]) == str(document) and runs[0]["status"] == "COMPLETED"
    assert _runs(engines, other["id"]) == [], "the other rule on the manual trigger must not run"

    assert engines.post(f"/automation/rules/{chosen['id']}/run", {"work_item_id": str(document)}).status_code == 202
    drain()
    assert len(_runs(engines, chosen["id"])) == 2, "every press is an occurrence of its own"


def test_a_manual_run_is_refused_in_words_audited_and_admin_only(engines: Engines) -> None:
    rule = _rule(engines, "manual", "Hand rule")
    plain = _rule(engines, "document.completed", "Not by hand", conditions=[
        {"field": "vendor_name", "operator": "EXISTS", "value": ""}])
    document = engines.process("hand2.pdf", [["TAX INVOICE", "Invoice Number: INV-HAND-2"]], marker="INV-HAND-2",
                               classification="Invoice", entities={"invoice_number": "INV-HAND-2"})
    body = {"work_item_id": str(document)}

    assert engines.post(f"/automation/rules/{rule['id']}/run", body, as_user=engines.tenant.contributor).status_code == 403
    assert engines.post(f"/automation/rules/{rule['id']}/run", body, as_user=engines.tenant.viewer).status_code == 403
    refused = engines.post(f"/automation/rules/{plain['id']}/run", body)
    assert refused.status_code == 409 and "Run by hand" in refused.text
    missing = engines.post(f"/automation/rules/{rule['id']}/run", {"work_item_id": str(uuid.uuid4())})
    assert missing.status_code == 404
    off = engines.patch(f"/automation/rules/{rule['id']}", {"is_active": False})
    assert off.status_code == 200
    assert "Switch the rule on" in engines.post(f"/automation/rules/{rule['id']}/run", body).text

    engines.patch(f"/automation/rules/{rule['id']}", {"is_active": True})
    assert engines.post(f"/automation/rules/{rule['id']}/run", body).status_code == 202
    audit = engines.get("/audit-logs", params={"resource_type": "AUTOMATION_RULE"}) if False else None
    from app.models.audit_log import AuditAction, AuditLog

    engines.refresh()
    rows = engines.db.execute(select(AuditLog).where(AuditLog.workspace_id == engines.ws,
                                                     AuditLog.action == AuditAction.EXECUTED)).scalars().all()
    assert rows and rows[0].details.get("manual_run") is True and audit is None


# ----------------------------------------------------------------------------------------------------- schedule


def test_schedules_fire_once_per_local_day_and_the_weekly_one_on_monday(engines: Engines) -> None:
    from app.models.workspace import Workspace

    daily = _rule(engines, "schedule.daily", "Morning digest")
    weekly = _rule(engines, "schedule.weekly", "Monday digest")
    engines.db.get(Workspace, engines.ws).timezone = "Asia/Kolkata"
    engines.db.commit()

    # Tuesday 2026-10-20: 02:00 UTC is 07:30 in Kolkata: not yet. 03:00 UTC is 08:30: the day is announced.
    assert _sweep(engines, datetime(2026, 10, 20, 2, 0, tzinfo=timezone.utc))["schedules"] == 0
    assert _runs(engines, daily["id"]) == []
    assert _sweep(engines, datetime(2026, 10, 20, 3, 0, tzinfo=timezone.utc))["schedules"] == 1
    assert len(_runs(engines, daily["id"])) == 1 and _runs(engines, weekly["id"]) == []
    # The next hour's sweep, and a re-run: the day is already announced.
    assert _sweep(engines, datetime(2026, 10, 20, 4, 0, tzinfo=timezone.utc))["schedules"] == 0
    assert len(_runs(engines, daily["id"])) == 1
    # A sweep that was down all morning still announces the day, once, when it comes back.
    assert _sweep(engines, datetime(2026, 10, 21, 14, 0, tzinfo=timezone.utc))["schedules"] == 1
    assert len(_runs(engines, daily["id"])) == 2
    # Monday 2026-10-26: both fire.
    assert _sweep(engines, datetime(2026, 10, 26, 3, 30, tzinfo=timezone.utc))["schedules"] == 2
    assert len(_runs(engines, weekly["id"])) == 1 and len(_runs(engines, daily["id"])) == 3
    # The trigger carries the date and the weekday, so a rule can say "only on Fridays".
    assert _event_count(engines, emitters.SCHEDULE_WEEKLY) == 1


def test_a_schedule_rule_can_be_limited_to_one_weekday(engines: Engines) -> None:
    fridays = _rule(engines, "schedule.daily", "Friday digest", conditions=[
        {"field": "event.weekday", "operator": "EQUALS", "value": "FRIDAY"}])
    _sweep(engines, datetime(2026, 10, 22, 9, 0, tzinfo=timezone.utc))  # a Thursday
    assert _runs(engines, fridays["id"]) == [] or all(r["actions_executed"] == 0 for r in _runs(engines, fridays["id"]))
    _sweep(engines, datetime(2026, 10, 23, 9, 0, tzinfo=timezone.utc))  # a Friday
    fired = [r for r in _runs(engines, fridays["id"]) if r["actions_executed"] == 1]
    assert len(fired) == 1


def test_nobody_listening_means_no_event_rows(engines: Engines) -> None:
    _sweep(engines, datetime(2026, 10, 20, 9, 0, tzinfo=timezone.utc))
    assert _event_count(engines, emitters.SCHEDULE_DAILY) == 0
    assert _event_count(engines, emitters.SCHEDULE_WEEKLY) == 0


# --------------------------------------------------------------------------------------------------- legal holds


def test_a_legal_hold_placed_and_released_fire_once_each(engines: Engines) -> None:
    placed_rule = _rule(engines, "legal_hold.placed", "Hold placed", message="{{event.reason}} / {{event.scope}}")
    released_rule = _rule(engines, "legal_hold.released", "Hold released")
    hold = engines.post("/work-items/retention-holds", {"reason": "Regulator inquiry", "reference": "CASE-9"})
    assert hold.status_code == 201, hold.text
    drain()
    assert len(_runs(engines, placed_rule["id"])) == 1 and _runs(engines, released_rule["id"]) == []

    freed = engines.delete(f"/work-items/retention-holds/{hold.json()['id']}")
    assert freed.status_code == 200
    assert engines.delete(f"/work-items/retention-holds/{hold.json()['id']}").status_code == 200  # releasing twice
    drain()
    assert len(_runs(engines, released_rule["id"])) == 1, "a hold is released once, however often release is pressed"
    assert len(_runs(engines, placed_rule["id"])) == 1


def test_a_document_hold_announces_its_document_without_being_held_back_by_a_review(engines: Engines) -> None:
    rule = _rule(engines, "legal_hold.placed", "Document hold", conditions=[
        {"field": "event.scope", "operator": "EQUALS", "value": "DOCUMENT"}])
    document = engines.process("held.pdf", [["TAX INVOICE", "Invoice Number: INV-HOLD-1"]], marker="INV-HOLD-1",
                               classification="Invoice", entities={"invoice_number": "INV-HOLD-1"})
    assert engines.post("/work-items/retention-holds", {"reason": "Litigation", "work_item_id": str(document)}).status_code == 201
    engines.post("/work-items/retention-holds", {"reason": "Whole workspace"})
    drain()
    fired = [r for r in _runs(engines, rule["id"]) if r["actions_executed"] == 1]
    assert len(fired) == 1, "only the document hold matches `scope is One document`"


# ------------------------------------------------------------------------------------------------- payment risk


def test_a_payment_risk_flag_fires_once_and_a_rescan_does_not_repeat_it(engines: Engines) -> None:
    engines.plan("business")
    bank = _rule(engines, "payment_risk.flagged", "Bank account changed", conditions=[
        {"field": "event.kind", "operator": "EQUALS", "value": "BANK_ACCOUNT_CHANGED"}])
    anything = _rule(engines, "payment_risk.flagged", "Any flag")
    for n, iban, total in ((1, "GB82 WEST 1234 5698 7654 32", "1234.56"), (2, "GB33 BUKB 2020 1555 5555 55", "50000.00")):
        number = f"INV-PRJ-{n}"
        engines.process(f"{number}.pdf", [["ACME SUPPLIES LTD", "TAX INVOICE", f"Invoice No: {number}"]], marker=number,
                        classification="Invoice", entities={"vendor_name": "Acme Supplies Ltd", "invoice_number": number,
                                                            "iban": iban, "total_amount": total, "currency": "GBP"})
    fired = [r for r in _runs(engines, bank["id"]) if r["actions_executed"] == 1]
    assert len(fired) == 1
    assert len([r for r in _runs(engines, anything["id"]) if r["actions_executed"] == 1]) == 2  # bank change + round amount
    assert _event_count(engines, emitters.PAYMENT_RISK) == 2

    # Scanning the same document again finds the same flags: the insert does nothing, so no new event.
    from app.models.work_item import WorkItem
    from app.services.radar import payment_risk

    engines.refresh()
    second = engines.db.execute(select(WorkItem).where(WorkItem.original_filename == "INV-PRJ-2.pdf")).scalar_one()
    assert payment_risk.scan(engines.db, work_item=second) == []
    engines.db.commit()
    drain()
    assert _event_count(engines, emitters.PAYMENT_RISK) == 2


# ----------------------------------------------------------------------------------------------------- TruthMesh


def test_truthmesh_conflicts_opening_and_being_decided_fire_once_each(engines: Engines) -> None:
    engines.plan("business")
    opened = _rule(engines, "truthmesh.conflict_opened", "Conflict opened", conditions=[
        {"field": "event.kind", "operator": "EQUALS", "value": "PAYEE_ACCOUNT_CHANGED"}])
    resolved = _rule(engines, "truthmesh.conflict_resolved", "Conflict resolved")
    load_mesh(engines)
    drain()
    fired = [r for r in _runs(engines, opened["id"]) if r["actions_executed"] == 1]
    assert len(fired) == 1, "one change of payee account is one conflict, announced once"
    before = _event_count(engines, emitters.CONFLICT_OPENED)
    assert before >= 4, "every conflict the mesh found was announced (a rule may filter by kind)"

    payee = next(c for c in engines.get("/truthmesh/conflicts", params={"limit": 200}).json()["items"]
                 if c["kind"] == "PAYEE_ACCOUNT_CHANGED")
    done = engines.patch(f"/truthmesh/conflicts/{payee['id']}", {"status": "RESOLVED", "note": "Confirmed by phone"})
    assert done.status_code == 200, done.text
    again = engines.patch(f"/truthmesh/conflicts/{payee['id']}", {"status": "RESOLVED", "note": "Confirmed by phone"})
    assert again.status_code == 200
    drain()
    assert len(_runs(engines, resolved["id"])) == 1, "deciding a conflict twice announces it once"
    assert _event_count(engines, emitters.CONFLICT_OPENED) == before


# ------------------------------------------------------------------------------------------------------ request link


def test_a_document_received_through_a_request_link_fires_once(engines: Engines) -> None:
    engines.plan("business")
    rule = _rule(engines, "document.received_by_link", "Received by link", message="{{event.document_type}} from {{event.recipient}}")
    template = engines.post("/case-templates", {"key": "intake", "name": "Intake", "rules": [],
                                                "required_documents": [{"doc_type": "invoice", "label": "Invoice"}]})
    assert template.status_code == 201, template.text
    assert engines.post(f"/case-templates/{template.json()['id']}/publish").status_code == 200
    case = engines.post("/cases", {"template_id": template.json()["id"], "title": "Supplier onboarding"}).json()["case"]
    created = engines.post(f"/cases/{case['id']}/requests", {"document_type": "invoice", "recipient_label": "Acme accounts"})
    assert created.status_code == 201, created.text
    token = created.json()["token"]
    from tests.engines.conftest import make_pdf

    sent = engines.client.post(f"/api/v1/public/document-requests/{token}",
                               files={"file": ("invoice.pdf", make_pdf([["TAX INVOICE", "Invoice Number: REQ-1"]]), "application/pdf")})
    assert sent.status_code == 200, sent.text
    drain()
    runs = _runs(engines, rule["id"])
    assert len(runs) == 1 and runs[0]["status"] == "COMPLETED" and runs[0]["work_item_id"]
    again = engines.client.post(f"/api/v1/public/document-requests/{token}",
                                files={"file": ("invoice.pdf", make_pdf([["x"]]), "application/pdf")})
    assert again.status_code in (404, 410)
    drain()
    assert len(_runs(engines, rule["id"])) == 1


# ------------------------------------------------------------------------------------------------------ GST Credit


def _gst_world(engines: Engines):
    from tests.services.gst.helpers import RECIPIENT, SUPPLIER_A, book_invoice

    engines.plan("business")
    return RECIPIENT, SUPPLIER_A, book_invoice


def _import(engines: Engines, gstin: str, period: str, documents) -> Any:
    from tests.services.gst.helpers import SUPPLIER_A, supplier_invoices
    from app.services.gst import builder as b

    statement = b.to_bytes(b.gstr2b(gstin, period, {"b2b": [supplier_invoices(documents, gstin=SUPPLIER_A)]}))
    return engines.client.post(f"/api/v1/workspaces/{engines.ws}/gst/returns", headers=engines.tenant.contributor.headers,
                               files={"file": (f"{period}.json", statement)})


def test_a_gstr_2b_import_fires_once_and_the_same_file_again_does_not(engines: Engines) -> None:
    from app.services.gst import builder as b

    recipient, supplier, book_invoice = _gst_world(engines)
    rule = _rule(engines, "gst.return_imported", "Return imported",
                 message="{{event.records}} records, {{event.waiting_count}} waiting ({{event.waiting}})")
    today = date.today()
    book_invoice(engines.db, engines.tenant, number="W-1", supplier="a", gstin=supplier, on=today - timedelta(days=3), taxable=200_000)
    engines.db.commit()
    period = f"{today.year:04d}-{today.month:02d}"
    documents = [b.document("ZZ-1", today - timedelta(days=2), 1_000)]
    first = _import(engines, recipient, period, documents)
    assert first.status_code == 200, first.text
    drain()
    runs = _runs(engines, rule["id"])
    assert len(runs) == 1 and runs[0]["status"] == "COMPLETED"
    again = _import(engines, recipient, period, documents)
    assert again.status_code == 200 and again.json()["results"][0]["status"] == "UNCHANGED"
    drain()
    assert len(_runs(engines, rule["id"])) == 1, "the same file again changes nothing, so it announces nothing"
    replaced = _import(engines, recipient, period, documents + [b.document("ZZ-2", today - timedelta(days=1), 2_000)])
    assert replaced.status_code == 200
    drain()
    assert len(_runs(engines, rule["id"])) == 2, "a replaced import is a new import"


def test_the_gst_clocks_announce_an_invoice_once_per_threshold(engines: Engines) -> None:
    from app.services.gst import builder as b

    recipient, supplier, book_invoice = _gst_world(engines)
    waiting = _rule(engines, "gst.waiting_for_supplier", "Waiting 30 days", conditions=[
        {"field": "event.amount", "operator": "GREATER_THAN", "value": "100000"}])
    risk = _rule(engines, "gst.reversal_risk", "Reversal risk")
    today = date.today()
    old_day, mid_day, fresh_day = today - timedelta(days=155), today - timedelta(days=40), today - timedelta(days=5)
    old = book_invoice(engines.db, engines.tenant, number="OLD-1", supplier="a", gstin=supplier, on=old_day, taxable=300_000)
    mid = book_invoice(engines.db, engines.tenant, number="MID-1", supplier="a", gstin=supplier, on=mid_day, taxable=400_000)
    fresh = book_invoice(engines.db, engines.tenant, number="NEW-1", supplier="a", gstin=supplier, on=fresh_day, taxable=500_000)
    for item, day in ((old, old_day), (mid, mid_day), (fresh, fresh_day)):
        # They entered the books on their own dates: an invoice entered late has not waited since its date.
        item.created_at = datetime(day.year, day.month, day.day, 6, 0, tzinfo=timezone.utc)
    engines.db.commit()
    for day in (old_day, mid_day, fresh_day):
        period = f"{day.year:04d}-{day.month:02d}"
        assert _import(engines, recipient, period, [b.document(f"ZZ-{period}", day, 1_000)]).status_code == 200
    drain()
    now = datetime.now(timezone.utc)

    first = _sweep(engines, now)["gst"]
    assert first["reversal"] == 1, first  # only the 155-day-old invoice reached 150 days
    assert first["waiting"] >= 2, first  # the 155-day and the 40-day invoice; not the 5-day one
    waiting_runs = _runs(engines, waiting["id"])
    assert len(waiting_runs) >= 2
    docs = {str(r["work_item_id"]) for r in waiting_runs}
    assert str(old.id) in docs and str(mid.id) in docs and str(fresh.id) not in docs
    assert len(_runs(engines, risk["id"])) == 1

    second = _sweep(engines, now + timedelta(hours=1))["gst"]
    assert second == {"waiting": 0, "reversal": 0}, "the next hour's sweep announces nothing it already announced"
    assert len(_runs(engines, risk["id"])) == 1

    # The workspace's threshold is its own: at 3 days the 5-day-old invoice is announced too, once.
    saved = engines.patch("/gst/settings", {"waiting_notice_days": 3})
    assert saved.status_code == 200 and saved.json()["waiting_notice_days"] == 3, saved.text
    third = _sweep(engines, now + timedelta(hours=2))["gst"]
    assert third["waiting"] >= 1


def test_the_gst_triggers_need_gst_credit_and_the_add_on_opens_them_on_developer(engines: Engines) -> None:
    engines.plan("developer")
    catalog = engines.get("/automation/catalog").json()
    gst = {t["key"]: t for t in catalog["triggers"] if t["key"].startswith("gst.")}
    assert gst and all(t["available"] is False and t["addon"] == "addon.gst_credit" for t in gst.values())
    refused = _rule(engines, "gst.return_imported", "GST", expect=422)
    assert "not included in your plan" in str(refused)
    engines.plan("business")
    assert all(t["available"] for t in {t["key"]: t for t in engines.get("/automation/catalog").json()["triggers"]
                                        if t["key"].startswith("gst.")}.values())


# --------------------------------------------------------------------------------------------------------- Helm


def test_helm_triggers_allow_only_actions_that_cannot_move_money(engines: Engines) -> None:
    engines.plan("business")
    for trigger in ("helm.mandate_breached", "helm.approval_needed"):
        for action_type, config in (("erp.post", {"target_id": str(uuid.uuid4()), "object_kind": "VENDOR_BILL"}),
                                    ("autonomy.decide", {}), ("work_item.mutate", {"target_field": "summary", "target_value": "x"}),
                                    ("redaction.start", {"profile_key": "financial"}),
                                    ("warehouse.export", {"destination_id": str(uuid.uuid4()), "dataset": "documents"})):
            body = {"name": f"{trigger} {action_type}", "triggers": [trigger], "condition_groups": [],
                    "actions": [{"action_type": action_type, "config": config}]}
            response = engines.post("/automation/rules", body)
            assert response.status_code == 422, (trigger, action_type, response.text)
        allowed = engines.post("/automation/rules", {"name": f"{trigger} ok", "triggers": [trigger], "condition_groups": [],
                                                      "actions": [{"action_type": "notify.role", "config": {"roles": ["ADMIN"]}}]})
        assert allowed.status_code == 201, allowed.text
    catalog = {t["key"]: t for t in engines.get("/automation/catalog").json()["triggers"]}
    assert "erp.post" in catalog["helm.approval_needed"]["excluded_actions"]
    assert "notify.role" not in catalog["helm.approval_needed"]["excluded_actions"]


def test_helm_announcements_fire_once_per_mandate_plan_and_action(engines: Engines) -> None:
    from app.models.helm import HelmBook
    from app.services.helm import plan_store
    from app.services.helm import vocabulary as v
    from app.services.helm.mandates import base

    engines.plan("business")
    breach = _rule(engines, "helm.mandate_breached", "Breach")
    approval = _rule(engines, "helm.approval_needed", "Approval")
    book = SimpleNamespace(id=uuid.uuid4(), organization_id=engines.org, workspace_id=engines.ws, kind="WORKSPACE")
    plan = SimpleNamespace(id=uuid.uuid4(), summary={"instruments": [
        {"mandate_id": "m-1", "template": "msme_45_day", "kind": "limit", "state": base.BREACHED, "items": [1, 2]},
        {"mandate_id": "m-2", "template": "other", "kind": "limit", "state": "OK", "items": []}]})
    action = SimpleNamespace(id=uuid.uuid4(), state=v.ACTION_PROPOSED, needs_approval=True, kind="pay_invoice",
                             amount_micros=118_000_000_000, currency="INR", run_date=date(2026, 10, 30))
    for _ in range(2):  # the same plan announced twice (a re-plan that changes nothing)
        plan_store._announce_to_automation(engines.db, book=book, plan=plan, previous={"m-1": "OK"}, actions=[action])
        engines.db.commit()
        drain()
    assert len(_runs(engines, breach["id"])) == 1 and len(_runs(engines, approval["id"])) == 1
    # Already breached on the plan before: not a new breach.
    fresh = SimpleNamespace(id=uuid.uuid4(), summary=plan.summary)
    plan_store._announce_to_automation(engines.db, book=book, plan=fresh, previous={"m-1": base.BREACHED}, actions=[])
    engines.db.commit()
    drain()
    assert len(_runs(engines, breach["id"])) == 1
    assert HelmBook is not None


def test_an_event_nobody_listens_to_writes_no_rows(engines: Engines) -> None:
    engines.db.commit()
    workspace = SimpleNamespace(id=engines.ws, organization_id=engines.org)
    assert emitters.schedule(engines.db, workspace=workspace, weekly=False, local_date=date(2026, 10, 21)) is None
    assert emitters.listening(engines.db, engines.ws, emitters.SCHEDULE_DAILY) is False
    assert _event_count(engines, emitters.SCHEDULE_DAILY) == 0
