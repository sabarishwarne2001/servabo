"""Session J action `gst.remind_supplier` — remind a supplier about invoices that are in your books but in no GSTR-2B.

This is the GST page's supplier reminder (`gst.reminder`), run by a rule:

  * WHO. The supplier is read from the trigger when it names one (the GST triggers carry `supplier_gstin` and your
    `gstin`), else from the document's own `vendor_gstin` and `buyer_gstin`.
  * ONLY TO A KNOWN CONTACT, exactly as on the GST page: the email contact Helm already knows for that supplier. With no
    known contact nothing is sent; the run says so, in words, and carries on (a later step can tell your finance team).
  * NEVER THE SAMPLE COMPANY.
  * NOT TWICE IN A ROW. A supplier is reminded at most once every `at_most_every_days` days by rules (7 by default), so a
    rule that fires for each of a supplier's invoices sends one email, not nine.

The email lists every invoice of that supplier still waiting, as the GST page's draft does.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import Field

from app.core.entitlements import GST_CREDIT_ADDON, GST_CREDIT_CAPABILITY
from app.services.automation.actions.base import (
    ROLE_WORKSPACE_ADMIN,
    ActionConfig,
    ActionDefinition,
    ActionFailure,
    ActionOutcome,
)

ACTION_TYPE = "gst.remind_supplier"


class GstRemindSupplierConfig(ActionConfig):
    at_most_every_days: int = Field(default=7, ge=1, le=90, description="The least time between two reminders to one supplier.")


def _who(state: Any) -> tuple[Optional[str], Optional[str]]:
    """(your GSTIN, the supplier's GSTIN): from the trigger first, then the document."""
    from app.services.automation import document_fields as df
    from app.services.gst import fields as gf

    payload = dict(getattr(getattr(state, "trigger_event", None), "payload", None) or {})
    supplier = gf.gstin_of(payload.get("supplier_gstin"))
    own = gf.gstin_of(payload.get("gstin"))
    work_item = getattr(state, "work_item", None)
    if work_item is not None:
        entities = getattr(work_item, "extracted_entities", None) or {}
        supplier = supplier or gf.gstin_of(df.read_by_alias(entities, "vendor_gstin"))
        own = own or gf.gstin_of(df.read_by_alias(entities, "buyer_gstin"))
    return own, supplier


def perform(state: Any, spec: Any) -> ActionOutcome:
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from app.models.automation_trigger import AutomationEventMark
    from app.models.workspace import Workspace
    from app.services.gst import engine, gate, reminder

    config = DEFINITION.parse_spec(spec)
    assert isinstance(config, GstRemindSupplierConfig)
    workspace = state.db.get(Workspace, state.execution.workspace_id)
    if workspace is None or workspace.is_sample:
        return ActionOutcome(summary="not sent: the sample company never sends email", details={"sent": False})
    if not gate.full_access(state.db, workspace):
        raise ActionFailure("GST Credit is not included in your plan, so supplier reminders are not available.", recoverable=False)
    own, supplier = _who(state)
    if supplier is None:
        raise ActionFailure("This run names no supplier GSTIN (the trigger or the document must carry one).", recoverable=False)
    if own is None:
        mine = engine.active_gstins(state.db, workspace.id)
        own = mine[0] if len(mine) == 1 else None
    if own is None:
        raise ActionFailure("Your own GSTIN could not be told from the run; import a GSTR-2B for it first.", recoverable=False)
    draft = reminder.draft(state.db, workspace, own, supplier)
    if not draft["lines"]:
        return ActionOutcome(summary="not sent: nothing from this supplier is waiting", details={"sent": False})
    if not draft["to"]:
        return ActionOutcome(
            summary="not sent: no email contact is known for this supplier",
            details={"sent": False, "supplier_gstin": supplier},
        )
    bucket = datetime.now(timezone.utc).date().toordinal() // config.at_most_every_days
    inserted = state.db.execute(
        pg_insert(AutomationEventMark)
        .values(workspace_id=workspace.id, mark_key=f"gst.reminded:{own}:{supplier}:{config.at_most_every_days}:{bucket}",
                event_type="action.gst.remind_supplier")
        .on_conflict_do_nothing(index_elements=["workspace_id", "mark_key"]).returning(AutomationEventMark.workspace_id)
    ).first()
    if inserted is None:
        return ActionOutcome(summary=f"not sent: reminded within the last {config.at_most_every_days} days",
                             details={"sent": False})
    result = reminder.send(state.db, workspace, own, supplier)
    if not result.get("sent"):
        raise ActionFailure(str(result.get("note") or "The reminder could not be sent."), recoverable=True)
    return ActionOutcome(summary=f"reminder sent to the supplier's known contact ({len(draft['lines'])} invoices)",
                         details={"sent": True, "invoices": len(draft["lines"]), "supplier_gstin": supplier})


DEFINITION = ActionDefinition(
    action_type=ACTION_TYPE,
    label="Remind a GST supplier",
    description="Email a supplier's known contact the invoices of theirs that are in your books but in no GSTR-2B.",
    category="GST Credit",
    config_model=GstRemindSupplierConfig,
    selector="automation.flow.gst_remind_supplier",
    perform=perform,
    capability=GST_CREDIT_CAPABILITY,
    addon=GST_CREDIT_ADDON,
    either=True,
    minimum_role=ROLE_WORKSPACE_ADMIN,
    idempotent=False,
    icon="mail",
)
