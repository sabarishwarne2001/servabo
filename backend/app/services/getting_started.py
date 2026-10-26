"""Getting started: "first money found" (Final session 1, 2C).

The checklist a new customer sees is a short path to the first finding. Every step ticks itself from REAL data, never from a click,
and each is a small function here so a test can prove its rule:

  documents  any document in the workspace (an upload, a zip, or an email)         (workspace contributors and above)
  read       any document Servabo has finished reading                              (everyone)
  gst        a GSTR-2B has been imported in the workspace                           (workspace contributors and above)
  helm       the organization has a Helm book (the sample company counts)           (organization owners, admins, billing)
  recipe     a rule exists in the workspace (turning on a recipe creates one)       (workspace administrators)
  invite     the organization has a second member (invited or active)               (organization owners and admins)

A person is only shown the steps they can do. Where a step's feature is a preview on the plan (GST Credit without the add-on), the
step says what the add-on or plan unlocks. When the value receipt has its first non-zero figure the checklist says so in one line with
the amount, using the receipt's own honesty rules (a confirmed figure, or one without an honesty class), for the roles that may read it.
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.models.automation import AutomationRule
from app.models.gst import GstReturn
from app.models.helm import HelmBook
from app.models.organization import Organization, OrganizationMember, OrganizationRole
from app.models.work_item import WorkItem
from app.models.workspace import Workspace, WorkspaceRole

__all__ = ["STEP_KEYS", "evaluate", "first_money", "tick_documents", "tick_gst", "tick_helm", "tick_invite", "tick_read", "tick_recipe"]

STEP_KEYS: tuple[str, ...] = ("documents", "read", "gst", "helm", "recipe", "invite")

_ORDER = {WorkspaceRole.VIEWER: 0, WorkspaceRole.CONTRIBUTOR: 1, WorkspaceRole.ADMIN: 2}
HELM_ROLES = frozenset({OrganizationRole.OWNER, OrganizationRole.ADMIN, OrganizationRole.BILLING})
INVITE_ROLES = frozenset({OrganizationRole.OWNER, OrganizationRole.ADMIN})


def _at_least(role: Any, minimum: WorkspaceRole) -> bool:
    return _ORDER.get(role, -1) >= _ORDER[minimum]


# ------------------------------------------------------------------------------------------------ the tick rules

def tick_documents(db: Session, workspace_id: uuid.UUID) -> bool:
    return db.execute(sa.select(sa.func.count()).select_from(WorkItem).where(WorkItem.workspace_id == workspace_id)).scalar_one() > 0


def tick_read(db: Session, workspace_id: uuid.UUID) -> bool:
    return db.execute(
        sa.select(sa.func.count()).select_from(WorkItem).where(WorkItem.workspace_id == workspace_id, WorkItem.status == "COMPLETED")
    ).scalar_one() > 0


def tick_gst(db: Session, workspace_id: uuid.UUID) -> bool:
    return db.execute(sa.select(sa.func.count()).select_from(GstReturn).where(GstReturn.workspace_id == workspace_id)).scalar_one() > 0


def tick_helm(db: Session, organization_id: uuid.UUID) -> bool:
    return db.execute(sa.select(sa.func.count()).select_from(HelmBook).where(HelmBook.organization_id == organization_id)).scalar_one() > 0


def tick_recipe(db: Session, workspace_id: uuid.UUID) -> bool:
    return db.execute(
        sa.select(sa.func.count()).select_from(AutomationRule).where(AutomationRule.workspace_id == workspace_id, AutomationRule.deleted_at.is_(None))
    ).scalar_one() > 0


def tick_invite(db: Session, organization_id: uuid.UUID) -> bool:
    return db.execute(
        sa.select(sa.func.count()).select_from(OrganizationMember).where(
            OrganizationMember.organization_id == organization_id, OrganizationMember.status.in_(("ACTIVE", "INVITED"))
        )
    ).scalar_one() > 1


# ------------------------------------------------------------------------------------------------ the money line

def first_money(db: Session, organization_id: uuid.UUID) -> Optional[dict[str, Any]]:
    """The receipt's first confirmed figure with an amount, as one line: {"text", "amount_text"}; None when there is none.
    Same honesty rule as the receipt's own headline: a figure that is confirmed or carries no honesty class (never a "likely" or
    "potential" one), and zero is never shown."""
    from app.services import value_receipt
    from app.services.helm import vocabulary as helm_v

    for period in (value_receipt.TRIAL, value_receipt.MONTH):
        try:
            receipt = value_receipt.cached(db, organization_id, period)
        except Exception:  # noqa: BLE001 - a receipt that cannot be built must never break the checklist
            continue
        lead = next(
            (f for f in receipt.get("found", []) if f.get("honesty") in (None, helm_v.HONESTY_CONFIRMED) and f.get("amount_micros")),
            None,
        )
        if lead:
            return {"text": f"Servabo has found {lead['amount_text']} in your own documents: {lead['label']}.", "amount_text": lead["amount_text"],
                    "period": period}
    return None


# ------------------------------------------------------------------------------------------------ the checklist

def evaluate(
    db: Session,
    *,
    organization: Organization,
    workspace: Workspace,
    workspace_role: Any,
    organization_role: Any,
) -> dict[str, Any]:
    """The steps this person can do, each with `done` computed from real data, and the money line when they may read it."""
    from app.api import capability_gate
    from app.core import entitlements
    from app.services.gst import gate as gst_gate
    from app.services.helm import gate as helm_gate

    steps: list[dict[str, Any]] = []

    def add(key: str, title: str, done: bool, note: Optional[str] = None) -> None:
        steps.append({"key": key, "title": title, "done": bool(done), "note": note})

    if _at_least(workspace_role, WorkspaceRole.CONTRIBUTOR):
        add("documents", "Add your documents: upload, a zip, or forward them by email", tick_documents(db, workspace.id))
    add("read", "See what Servabo read from them", tick_read(db, workspace.id))
    if _at_least(workspace_role, WorkspaceRole.CONTRIBUTOR):
        note = None
        if not gst_gate.full_access(db, workspace):
            from app.core import entitlements as _entitlements
            from app.services.billing import entitlement_service as _addons

            # N-187: the plan that sells the add-on by its customer-facing name ("Starter"), from the published plans.
            sold_on = " or ".join(_addons.sold_on(db, _entitlements.GST_CREDIT_ADDON)) or "Starter"
            note = ("Your plan shows the headline figures from a GSTR-2B. The supplier and invoice lists, the portal recommendations and the "
                    f"export come with Business, or with the GST Credit add-on on {sold_on}.")
        add("gst", "Import a GSTR-2B and see which suppliers have not reported your invoices", tick_gst(db, workspace.id), note)
    if organization_role in HELM_ROLES:
        note = None
        if not helm_gate.helm_held(db, organization.id):
            note = "Open Helm with its sample company to see how payments are planned. Your own invoices need Business or Enterprise."
        add("helm", "Open Helm and see your payments planned", tick_helm(db, organization.id), note)
    if _at_least(workspace_role, WorkspaceRole.ADMIN):
        note = None
        if not capability_gate.has_capability(db, organization_id=organization.id, capability_key=entitlements.AUTOMATIONS_CAPABILITY):
            note = "Automations, and so recipes, are not included in your plan."
        add("recipe", "Turn on one recipe", tick_recipe(db, workspace.id), note)
    if organization_role in INVITE_ROLES:
        add("invite", "Invite a teammate", tick_invite(db, organization.id))

    money = None
    if organization_role in HELM_ROLES:  # the roles that may read the value receipt (owner, admin, billing)
        money = first_money(db, organization.id)
    return {"steps": steps, "done": sum(1 for s in steps if s["done"]), "total": len(steps), "money": money}
