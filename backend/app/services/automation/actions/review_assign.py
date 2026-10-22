"""Session J action `review.assign` — send the document to the review hub, assigned to a person or a role, with a due time.

It is `review.escalate` (the document is held for a reviewer; later rules on it wait for the decision) followed by an
assignment in the review hub:

  * `assignee_email`: one named person, who must be able to work review items in this workspace (a contributor or an
    administrator, by effective access);
  * `assignee_role`: whoever holds that organization role and can work review items here, the one with the fewest open
    assignments (ties go to the lowest user id, so the choice is stable).

`due_in_hours` sets when the review is due; the hub shows it beside the assignee. `review.escalate` itself is unchanged.
A person who cannot hold review items is refused at save time, and again when the rule runs (a member can leave).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Literal, Optional

from pydantic import Field, model_validator

from app.services.automation.actions import review_escalate
from app.services.automation.actions.base import (
    ROLE_WORKSPACE_ADMIN,
    ActionConfig,
    ActionDefinition,
    ActionFailure,
    ActionOutcome,
    SaveContext,
    require_work_item,
)

ACTION_TYPE = "review.assign"
ROLES = ("OWNER", "ADMIN", "BILLING", "MEMBER")


class ReviewAssignConfig(ActionConfig):
    assignee_email: Optional[str] = Field(default=None, max_length=254, description="The person who works the review.")
    assignee_role: Optional[Literal["OWNER", "ADMIN", "BILLING", "MEMBER"]] = Field(
        default=None, description="Or whoever holds this role and can work reviews (the least busy)."
    )
    reason: str = Field(default="Sent to review by an automation rule.", min_length=1, max_length=240)
    due_in_hours: int = Field(default=48, ge=1, le=720, description="When the review is due, in hours from now.")

    @model_validator(mode="after")
    def _one_assignee(self) -> "ReviewAssignConfig":
        if bool(self.assignee_email) == bool(self.assignee_role):
            raise ValueError("Choose a person or a role to assign the review to, not both and not neither.")
        if self.assignee_email and "@" not in self.assignee_email:
            raise ValueError("That does not look like an email address.")
        return self


def _holders(db: Any, *, workspace_id: uuid.UUID, organization_id: uuid.UUID) -> list[Any]:
    """Active organization members who can work review items in the workspace, with their organization role."""
    from sqlalchemy import select

    from app.models.organization import MembershipStatus, OrganizationMember
    from app.models.user import User
    from app.services.review import resolution

    rows = db.execute(
        select(User, OrganizationMember.role)
        .join(OrganizationMember, OrganizationMember.user_id == User.id)
        .where(OrganizationMember.organization_id == organization_id, OrganizationMember.status == MembershipStatus.ACTIVE)
        .order_by(User.id)
    ).all()
    return [(user, role) for user, role in rows
            if resolution.can_hold_review_items(db, workspace_id=workspace_id, user_id=user.id)]


def resolve_assignee(db: Any, *, workspace_id: uuid.UUID, organization_id: uuid.UUID, config: ReviewAssignConfig) -> Any:
    """The user the review goes to, or an ActionFailure that says why not."""
    from sqlalchemy import func, select

    from app.models.review import ReviewAssignment

    holders = _holders(db, workspace_id=workspace_id, organization_id=organization_id)
    if config.assignee_email:
        wanted = config.assignee_email.strip().lower()
        for user, _role in holders:
            if (user.email or "").strip().lower() == wanted:
                return user
        raise ActionFailure(
            f"{config.assignee_email} is not a member of this workspace who can work reviews, so the review was not assigned.",
            recoverable=False,
        )
    role = str(config.assignee_role)
    candidates = [user for user, member_role in holders if getattr(member_role, "value", member_role) == role]
    if not candidates:
        raise ActionFailure(f"Nobody holding the {role.title()} role can work reviews in this workspace.", recoverable=True)
    loads = dict(db.execute(
        select(ReviewAssignment.assignee_user_id, func.count()).where(
            ReviewAssignment.workspace_id == workspace_id,
            ReviewAssignment.assignee_user_id.in_([u.id for u in candidates]))
        .group_by(ReviewAssignment.assignee_user_id)).all())
    return sorted(candidates, key=lambda u: (loads.get(u.id, 0), str(u.id)))[0]


def _validate(ctx: SaveContext, config: ActionConfig) -> dict[str, str]:
    assert isinstance(config, ReviewAssignConfig)
    try:
        resolve_assignee(ctx.db, workspace_id=ctx.workspace_id, organization_id=ctx.organization_id, config=config)
    except ActionFailure as exc:
        return {"assignee_email" if config.assignee_email else "assignee_role": str(exc)}
    return {}


def perform(state: Any, spec: Any) -> ActionOutcome:
    from sqlalchemy import select

    from app.models.review import REVIEW_KIND_EXTRACTION, ReviewAssignment
    from app.services.review import resolution

    config = DEFINITION.parse_spec(spec)
    assert isinstance(config, ReviewAssignConfig)
    require_work_item(state, ACTION_TYPE)
    escalated = review_escalate.escalate(state, reason=config.reason, source=ACTION_TYPE)
    verification_id = escalated.external_ref
    if verification_id is None:
        raise ActionFailure("The review could not be opened.", recoverable=True)
    assignee = resolve_assignee(state.db, workspace_id=state.execution.workspace_id,
                                organization_id=state.execution.organization_id, config=config)
    item_id = uuid.UUID(str(verification_id))
    resolution.assign(state.db, workspace_id=state.execution.workspace_id, kind=REVIEW_KIND_EXTRACTION, item_id=item_id,
                      assignee_user_id=assignee.id, assigned_by_user_id=state.rule.created_by_user_id)
    due = datetime.now(timezone.utc) + timedelta(hours=config.due_in_hours)
    row = state.db.execute(select(ReviewAssignment).where(
        ReviewAssignment.kind == REVIEW_KIND_EXTRACTION, ReviewAssignment.item_id == item_id)).scalar_one()
    row.due_at = due
    state.db.flush()
    return ActionOutcome(
        summary=f"sent to review, assigned, due in {config.due_in_hours} hours",
        external_ref=str(verification_id),
        details={"assigned_to_role": config.assignee_role, "due_at": due.isoformat(), "reused": bool(
            (escalated.details or {}).get("reused"))},
    )


DEFINITION = ActionDefinition(
    action_type=ACTION_TYPE,
    label="Send to review, assigned",
    description="Hold the document for review and give it to a person, or to whoever holds a role, with a due time.",
    category="Human review",
    config_model=ReviewAssignConfig,
    selector="automation.flow.review_assign",
    perform=perform,
    capability=None,
    minimum_role=ROLE_WORKSPACE_ADMIN,
    validate_resources=_validate,
    idempotent=True,
    icon="user-check",
)
