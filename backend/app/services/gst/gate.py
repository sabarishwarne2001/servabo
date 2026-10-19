"""What a plan lets a workspace do with GST Credit.

  * every plan (the GST Credit preview): import GSTR-2B files, see the six headline figures and counts, and see the
    full reconciliation of the sample company;
  * `capability.gst_credit` (Business, Enterprise): the supplier list, the invoice list with IMS recommendations,
    decisions, the export and supplier reminders;
  * the `addon.gst_credit` add-on (Developer, $49 a month for the organization, Session H): the same, for as long as
    the add-on is active or in its grace period. When it ends the page returns to the preview and nothing is deleted.

The sample company is a workspace flagged `is_sample`; it is read-only (nothing is imported into it or decided on it).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.api import addon_gate, capability_gate
from app.core import entitlements
from app.models.workspace import Workspace
from app.services.billing import entitlement_service


def _addon_grants(db: Session, organization_id: Any) -> bool:
    """An active or in-grace GST Credit add-on (the check custom domains and warehouse sync use)."""
    return entitlement_service.addon_access(
        db, organization_id=organization_id, addon_key=entitlements.GST_CREDIT_ADDON).can_maintain


def full_access(db: Session, workspace: Workspace) -> bool:
    if workspace.is_sample:
        return True
    if capability_gate.has_capability(db, organization_id=workspace.organization_id,
                                      capability_key=entitlements.GST_CREDIT_CAPABILITY):
        return True
    return _addon_grants(db, workspace.organization_id)


def require_full(db: Session, workspace: Workspace, context: Any, operation: str) -> None:
    """Raise a 402 that names the remedy when the organization has neither the plan's capability nor the add-on.

    On Developer the remedy is the add-on (`AddonRequiredError`, which also says a higher plan includes it); on any
    other plan the only route is a plan change (`CapabilityRequiredError`, remedy PLAN_UPGRADE). The sample company
    is exempt."""
    if workspace.is_sample or full_access(db, workspace):
        return
    if entitlement_service.offered_on_plan(db, organization_id=workspace.organization_id,
                                           addon_key=entitlements.GST_CREDIT_ADDON):
        addon_gate.require_addon(db, context=context, addon_key=entitlements.GST_CREDIT_ADDON, operation=operation,
                                 allow_grace=True)
    capability_gate.require_capability(db, context=context, capability_key=entitlements.GST_CREDIT_CAPABILITY,
                                       operation=operation)


__all__ = ["full_access", "require_full"]
