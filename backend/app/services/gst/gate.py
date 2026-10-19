"""What a plan lets a workspace do with GST Credit.

  * every plan (the GST Credit preview): import GSTR-2B files, see the six headline figures and counts, and see the
    full reconciliation of the sample company;
  * `capability.gst_credit` (Business, Enterprise): the supplier list, the invoice list with IMS recommendations,
    decisions, the export and supplier reminders.

The sample company is a workspace flagged `is_sample`; it is read-only (nothing is imported into it or decided on it).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.api import capability_gate
from app.core import entitlements
from app.models.workspace import Workspace


def full_access(db: Session, workspace: Workspace) -> bool:
    if workspace.is_sample:
        return True
    return capability_gate.has_capability(db, organization_id=workspace.organization_id,
                                          capability_key=entitlements.GST_CREDIT_CAPABILITY)


def require_full(db: Session, workspace: Workspace, context: Any, operation: str) -> None:
    """Raise `CapabilityRequiredError` (402, remedy PLAN_UPGRADE) on a plan without GST Credit; the sample is exempt."""
    if workspace.is_sample:
        return
    capability_gate.require_capability(db, context=context, capability_key=entitlements.GST_CREDIT_CAPABILITY,
                                       operation=operation)


__all__ = ["full_access", "require_full"]
