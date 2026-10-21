"""Session J action `legal_hold.place` — place a legal hold on the document.

A hold stops the document being deleted, by anyone and by any retention schedule, until a person releases it. Only a
workspace administrator may put this action in a rule. A rule can place a hold; it can never RELEASE one: releasing is a
person's job, with the same audit trail as every hold (`retention_service.release_hold`).

Placing is idempotent for the document: a document the rule already holds (an active hold with the same reason) is not held
a second time, so a rule that runs twice leaves one hold. The hold announces itself like any other (the `legal_hold.placed`
trigger), so people and other rules hear of it.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import Field

from app.services.automation.actions.base import (
    ROLE_WORKSPACE_ADMIN,
    ActionConfig,
    ActionDefinition,
    ActionOutcome,
    plain_variables_for,
    render,
    require_work_item,
)

ACTION_TYPE = "legal_hold.place"


class LegalHoldPlaceConfig(ActionConfig):
    reason: str = Field(default="Placed by an automation rule.", min_length=1, max_length=255,
                        description="Why the document is held. Shown on the hold.")
    reference: Optional[str] = Field(default=None, max_length=128, description="A matter or case reference.")


def perform(state: Any, spec: Any) -> ActionOutcome:
    from sqlalchemy import select

    from app.models.ingestion import RetentionHold
    from app.services.ingestion import retention_service

    config = DEFINITION.parse_spec(spec)
    assert isinstance(config, LegalHoldPlaceConfig)
    work_item = require_work_item(state, ACTION_TYPE)
    values = plain_variables_for(state)
    reason = (render(config.reason, values).strip() or "Placed by an automation rule.")[:255]
    reference = (render(config.reference, values).strip() or None) if config.reference else None
    existing = state.db.execute(select(RetentionHold.id).where(
        RetentionHold.work_item_id == work_item.id, RetentionHold.released_at.is_(None),
        RetentionHold.reason == reason).limit(1)).scalar_one_or_none()
    if existing is not None:
        return ActionOutcome(summary="document already held", external_ref=str(existing), details={"reused": True})
    hold = retention_service.place_hold(
        state.db,
        organization_id=state.execution.organization_id,
        workspace_id=None,
        work_item_id=work_item.id,
        reason=reason,
        reference=reference,
        user_id=state.rule.created_by_user_id,
    )
    return ActionOutcome(summary="legal hold placed", external_ref=str(hold.id), details={"reference": reference})


DEFINITION = ActionDefinition(
    action_type=ACTION_TYPE,
    label="Place a legal hold",
    description="Stop the document being deleted until a person releases the hold. A rule can place a hold, never release one.",
    category="Compliance",
    config_model=LegalHoldPlaceConfig,
    selector="automation.flow.legal_hold_place",
    perform=perform,
    capability=None,
    minimum_role=ROLE_WORKSPACE_ADMIN,
    template_fields=("reason", "reference"),
    idempotent=True,
    icon="shield",
)
