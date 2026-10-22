"""Final session 1 (2C): every step of "first money found" ticks from real data, and a person sees only the steps they can do.

One test per tick rule, so a rule that quietly changes fails by name. Nothing here ticks from a click.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest

from app.models.automation import AutomationRule
from app.models.gst import GstReturn
from app.models.helm import HelmBook
from app.models.organization import OrganizationMember, OrganizationRole, MembershipStatus
from app.models.work_item import WorkItem
from app.models.workspace import WorkspaceRole
from app.services import getting_started as gs
from tests.security.plans import put_on_plan
from tests.services.gst.helpers import book_invoice


def _keys(view):
    return [s["key"] for s in view["steps"]]


def _step(view, key):
    return next(s for s in view["steps"] if s["key"] == key)


def _view(db, tenant, *, ws_role=WorkspaceRole.ADMIN, org_role=OrganizationRole.OWNER):
    return gs.evaluate(db, organization=tenant.organization, workspace=tenant.workspace, workspace_role=ws_role, organization_role=org_role)


# ------------------------------------------------------------------------------------------------ the tick rules

def test_documents_ticks_when_a_document_exists_and_not_before(db_session, tenant):
    assert gs.tick_documents(db_session, tenant.workspace.id) is False
    db_session.add(WorkItem(workspace_id=tenant.workspace.id, original_filename="a.pdf", stored_filename="s", file_type="application/pdf",
                            file_size=1, status="QUEUED"))
    db_session.flush()
    assert gs.tick_documents(db_session, tenant.workspace.id) is True


def test_read_ticks_only_for_a_document_that_finished_reading(db_session, tenant):
    item = WorkItem(workspace_id=tenant.workspace.id, original_filename="a.pdf", stored_filename="s", file_type="application/pdf", file_size=1,
                    status="QUEUED")
    db_session.add(item)
    db_session.flush()
    assert gs.tick_read(db_session, tenant.workspace.id) is False
    item.status = "COMPLETED"
    db_session.flush()
    assert gs.tick_read(db_session, tenant.workspace.id) is True


def test_gst_ticks_when_a_gstr2b_was_imported_in_this_workspace(db_session, tenant):
    assert gs.tick_gst(db_session, tenant.workspace.id) is False
    db_session.add(GstReturn(organization_id=tenant.organization.id, workspace_id=tenant.workspace.id, gstin="27AAACG1234F1Z5", period="2026-09",
                             rtnprd="092026", file_sha256="0" * 64, file_name="r.json"))
    db_session.flush()
    assert gs.tick_gst(db_session, tenant.workspace.id) is True


def test_helm_ticks_when_the_organization_has_a_helm_book_even_the_sample_company(db_session, tenant):
    assert gs.tick_helm(db_session, tenant.organization.id) is False
    db_session.add(HelmBook(organization_id=tenant.organization.id, kind="SAMPLE", name="Sample company", workspace_id=tenant.workspace.id))
    db_session.flush()
    assert gs.tick_helm(db_session, tenant.organization.id) is True


def test_recipe_ticks_when_a_rule_exists_and_not_for_a_deleted_one(db_session, tenant):
    from datetime import datetime, timezone

    assert gs.tick_recipe(db_session, tenant.workspace.id) is False
    rule = AutomationRule(name="r", event="DOCUMENT_UPLOADED", workspace_id=tenant.workspace.id)
    db_session.add(rule)
    db_session.flush()
    assert gs.tick_recipe(db_session, tenant.workspace.id) is True
    rule.deleted_at = datetime.now(timezone.utc)
    db_session.flush()
    assert gs.tick_recipe(db_session, tenant.workspace.id) is False


def test_invite_ticks_when_there_is_a_second_member_active_or_invited(db_session, tenant):
    # the fixture seats four people: remove all but one to start from "only me"
    db_session.query(OrganizationMember).filter(OrganizationMember.organization_id == tenant.organization.id,
                                                OrganizationMember.user_id != tenant.owner.user.id).delete()
    db_session.flush()
    assert gs.tick_invite(db_session, tenant.organization.id) is False
    from tests.conftest import _make_user

    other = _make_user(db_session, f"invited-{uuid.uuid4().hex[:6]}@acme.com")
    db_session.add(OrganizationMember(organization_id=tenant.organization.id, user_id=other.user.id, role=OrganizationRole.MEMBER,
                                      status=MembershipStatus.INVITED))
    db_session.flush()
    assert gs.tick_invite(db_session, tenant.organization.id) is True


# ------------------------------------------------------------------------------------------------ who sees what

def test_an_owner_who_is_a_workspace_admin_sees_all_six_steps_in_order(db_session, tenant):
    assert _keys(_view(db_session, tenant)) == list(gs.STEP_KEYS)


def test_a_viewer_sees_only_what_a_viewer_can_do(db_session, tenant):
    view = _view(db_session, tenant, ws_role=WorkspaceRole.VIEWER, org_role=OrganizationRole.MEMBER)
    assert _keys(view) == ["read"] and view["money"] is None


def test_a_contributor_member_adds_documents_and_imports_but_does_not_configure_or_invite(db_session, tenant):
    view = _view(db_session, tenant, ws_role=WorkspaceRole.CONTRIBUTOR, org_role=OrganizationRole.MEMBER)
    assert _keys(view) == ["documents", "read", "gst"]


def test_billing_role_sees_helm_but_cannot_invite(db_session, tenant):
    view = _view(db_session, tenant, ws_role=WorkspaceRole.VIEWER, org_role=OrganizationRole.BILLING)
    assert _keys(view) == ["read", "helm"]


def test_a_plan_where_gst_credit_is_a_preview_says_what_unlocks_the_lists(db_session, tenant):
    put_on_plan(db_session, tenant.organization, "developer")
    db_session.flush()
    note = _step(_view(db_session, tenant), "gst")["note"]
    assert note and "Business" in note and "GST Credit add-on" in note


def test_a_plan_with_gst_credit_has_no_preview_note_and_a_plan_without_helm_names_the_sample_company(db_session, tenant):
    put_on_plan(db_session, tenant.organization, "business")
    db_session.flush()
    assert _step(_view(db_session, tenant), "gst")["note"] is None
    put_on_plan(db_session, tenant.organization, "developer")
    db_session.flush()
    assert "sample company" in _step(_view(db_session, tenant), "helm")["note"]


# ------------------------------------------------------------------------------------------------ the money line

def test_the_money_line_appears_with_the_first_confirmed_figure_and_never_before(db_session, tenant, monkeypatch):
    from app.services import value_receipt

    assert _view(db_session, tenant)["money"] is None
    receipt = {"found": [
        {"key": "payment_risk", "label": "a likely thing", "honesty": "likely", "amount_micros": 5_000_000, "amount_text": "₹5"},
        {"key": "gst", "label": "ITC at risk", "honesty": "confirmed", "amount_micros": 240_000_000_000, "amount_text": "₹2,40,000"},
    ]}
    monkeypatch.setattr(value_receipt, "cached", lambda db, org, period: receipt)
    money = _view(db_session, tenant)["money"]
    assert money["amount_text"] == "₹2,40,000" and "₹2,40,000" in money["text"], "the likely figure is never the headline"
    assert _view(db_session, tenant, org_role=OrganizationRole.MEMBER)["money"] is None, "a member does not read the receipt"
    monkeypatch.setattr(value_receipt, "cached", lambda db, org, period: {"found": [{"honesty": "likely", "amount_micros": 1, "amount_text": "₹1"}]})
    assert _view(db_session, tenant)["money"] is None


def test_a_receipt_that_cannot_be_built_never_breaks_the_checklist(db_session, tenant, monkeypatch):
    from app.services import value_receipt

    def boom(db, org, period):
        raise RuntimeError("redis is down")

    monkeypatch.setattr(value_receipt, "cached", boom)
    assert _view(db_session, tenant)["money"] is None
