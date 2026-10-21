"""Session J action `obligation.create` — create a follow-up: something someone must do by a date.

An obligation (Obligations engine) with a fixed due date N days from today in the WORKSPACE's time zone, an owner, and a link
to the document when the run has one. It is made as the rule's author (every obligation records who created it), so a rule
whose author has left the organization cannot create them. A follow-up the rule already made for the same document and
title, still open, is not made again.

The owner is a named person who must be a member of the workspace, or the rule's author when none is named.
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import Field

from app.core.entitlements import OBLIGATIONS_CAPABILITY
from app.services.automation.actions.base import (
    ROLE_WORKSPACE_ADMIN,
    ActionConfig,
    ActionDefinition,
    ActionFailure,
    ActionOutcome,
    SaveContext,
    plain_variables_for,
    render,
)

ACTION_TYPE = "obligation.create"
KINDS = ("RENEWAL", "NOTICE", "PAYMENT", "DELIVERY", "EXPIRY", "REPORTING", "OTHER")


class ObligationCreateConfig(ActionConfig):
    title: str = Field(default="Follow up: {{document.filename}}", min_length=1, max_length=300)
    kind: Literal["RENEWAL", "NOTICE", "PAYMENT", "DELIVERY", "EXPIRY", "REPORTING", "OTHER"] = "OTHER"
    due_in_days: int = Field(default=7, ge=0, le=730, description="Due this many days from today, in the workspace's time zone.")
    owner_email: Optional[str] = Field(default=None, max_length=254, description="Who owns it. Default: the rule's author.")
    description: Optional[str] = Field(default=None, max_length=1000)


def _owner(db: Any, *, workspace_id: Any, email: Optional[str]) -> Optional[Any]:
    from sqlalchemy import select

    from app.models.user import User
    from app.services.obligations import service

    if not email:
        return None
    user = db.execute(select(User).where(User.email.ilike(email.strip()))).scalar_one_or_none()
    if user is None or not service._has_workspace_access(db, workspace_id, user.id):  # noqa: SLF001 - the engine's own rule
        return None
    return user


def _validate(ctx: SaveContext, config: ActionConfig) -> dict[str, str]:
    assert isinstance(config, ObligationCreateConfig)
    if config.owner_email and _owner(ctx.db, workspace_id=ctx.workspace_id, email=config.owner_email) is None:
        return {"owner_email": f"{config.owner_email} is not a member of this workspace."}
    return {}


def perform(state: Any, spec: Any) -> ActionOutcome:
    from datetime import timedelta

    from sqlalchemy import select

    from app.models.obligations import Obligation
    from app.services.obligations import service
    from app.services.obligations import vocabulary as v

    config = DEFINITION.parse_spec(spec)
    assert isinstance(config, ObligationCreateConfig)
    author = state.rule.created_by_user_id
    if author is None:
        raise ActionFailure("This rule has no author, and a follow-up is created as a person.", recoverable=False)
    owner = _owner(state.db, workspace_id=state.execution.workspace_id, email=config.owner_email)
    if config.owner_email and owner is None:
        raise ActionFailure(f"{config.owner_email} is not a member of this workspace.", recoverable=False)
    values = plain_variables_for(state)
    title = " ".join(render(config.title, values).split())[:v.MAX_TITLE] or state.rule.name[:v.MAX_TITLE]
    work_item = getattr(state, "work_item", None)
    existing = state.db.execute(select(Obligation.id).where(
        Obligation.workspace_id == state.execution.workspace_id, Obligation.title == title,
        Obligation.work_item_id == (work_item.id if work_item is not None else None),
        Obligation.state.not_in(v.CLOSED_STATES)).limit(1)).scalar_one_or_none()
    if existing is not None:
        return ActionOutcome(summary="follow-up already open", external_ref=str(existing), details={"reused": True})
    due = service.local_today(state.db, state.execution.workspace_id) + timedelta(days=config.due_in_days)
    try:
        created = service.create_manual(
            state.db,
            organization_id=state.execution.organization_id,
            workspace_id=state.execution.workspace_id,
            actor_user_id=author,
            kind=config.kind,
            title=title,
            rule={"kind": v.RULE_FIXED, "date": due.isoformat()},
            description=(render(config.description, values)[:1000] if config.description else None),
            owner_user_id=(owner.id if owner is not None else author),
            work_item_id=work_item.id if work_item is not None else None,
        )
    except service.ObligationError as exc:
        raise ActionFailure(str(exc), recoverable=False) from exc
    return ActionOutcome(summary=f"follow-up created, due {due.isoformat()}", external_ref=str(created.id),
                         details={"due_date": due.isoformat(), "kind": config.kind})


DEFINITION = ActionDefinition(
    action_type=ACTION_TYPE,
    label="Create a follow-up",
    description="Create an obligation due in N days, with an owner, linked to the document.",
    category="Obligations",
    config_model=ObligationCreateConfig,
    selector="automation.flow.obligation_create",
    perform=perform,
    capability=OBLIGATIONS_CAPABILITY,
    minimum_role=ROLE_WORKSPACE_ADMIN,
    template_fields=("title", "description"),
    validate_resources=_validate,
    idempotent=True,
    icon="calendar-check",
)
