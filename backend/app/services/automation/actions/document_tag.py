"""Session J action `document.tag` — add or remove tags on the document.

Tags are the product's own labels (`work_item_tags`: lowercase, up to 48 characters, at most MAX_TAGS_PER_ITEM per
document), the same ones people set from the document list. A tag is how a rule leaves a mark other rules and people can
read: "new supplier", "litigation", "needs GST follow-up".

LOOPS. A tag change is announced as `work_item.field_changed` (field `tags`), caused by the rule's own trigger event, so a
rule on "a document field changed" can react to a tag. That makes a loop possible (rule A tags, which fires rule B, which
tags, which fires rule A), and the engine's chain check ends it: the same rule never runs twice in one causal chain
(`SUPPRESSED_CYCLE`). A tag change that changes nothing (the tag is already there) announces nothing, so a rule that
re-applies its own tag stops by itself.
"""

from __future__ import annotations

from typing import Any

from pydantic import Field, field_validator, model_validator

from app.services.automation.actions.base import (
    ROLE_WORKSPACE_ADMIN,
    ActionConfig,
    ActionDefinition,
    ActionFailure,
    ActionOutcome,
    require_work_item,
)

ACTION_TYPE = "document.tag"
MAX_PER_ACTION = 10


def _normalise(tag: str) -> str:
    from app.services.ingestion.bulk_service import BulkError, normalise_tag

    try:
        return normalise_tag(tag)
    except BulkError as exc:
        raise ValueError(str(exc)) from exc


class DocumentTagConfig(ActionConfig):
    add: list[str] = Field(default_factory=list, max_length=MAX_PER_ACTION, description="Tags to put on the document.")
    remove: list[str] = Field(default_factory=list, max_length=MAX_PER_ACTION, description="Tags to take off it.")

    @field_validator("add", "remove")
    @classmethod
    def _tags(cls, value: list[str]) -> list[str]:
        cleaned = [_normalise(tag) for tag in value]
        return list(dict.fromkeys(cleaned))

    @model_validator(mode="after")
    def _something_to_do(self) -> "DocumentTagConfig":
        if not self.add and not self.remove:
            raise ValueError("Name a tag to add or a tag to remove.")
        both = sorted(set(self.add) & set(self.remove))
        if both:
            raise ValueError(f"A tag cannot be both added and removed: {', '.join(both)}.")
        return self


def perform(state: Any, spec: Any) -> ActionOutcome:
    from sqlalchemy import delete, select

    from app.models.ingestion import WorkItemTag
    from app.services import outbox_service
    from app.services.ingestion.bulk_service import MAX_TAGS_PER_ITEM

    config = DEFINITION.parse_spec(spec)
    assert isinstance(config, DocumentTagConfig)
    work_item = require_work_item(state, ACTION_TYPE)
    existing = set(state.db.execute(select(WorkItemTag.tag).where(WorkItemTag.work_item_id == work_item.id)).scalars())
    to_add = [tag for tag in config.add if tag not in existing]
    to_remove = [tag for tag in config.remove if tag in existing]
    if len(existing) - len(to_remove) + len(to_add) > MAX_TAGS_PER_ITEM:
        raise ActionFailure(f"A document may carry at most {MAX_TAGS_PER_ITEM} tags.", recoverable=False)
    for tag in to_add:
        state.db.add(WorkItemTag(work_item_id=work_item.id, workspace_id=work_item.workspace_id, tag=tag,
                                 created_by_user_id=None))
    if to_remove:
        state.db.execute(delete(WorkItemTag).where(WorkItemTag.work_item_id == work_item.id,
                                                   WorkItemTag.workspace_id == work_item.workspace_id,
                                                   WorkItemTag.tag.in_(to_remove)))
    state.db.flush()
    if not to_add and not to_remove:
        return ActionOutcome(summary="tags already as asked", details={"added": [], "removed": []})
    event = outbox_service.emit_trigger(
        state.db,
        organization_id=state.execution.organization_id,
        workspace_id=state.execution.workspace_id,
        event_type="work_item.field_changed",
        resource_id=work_item.id,
        payload={"work_item_id": str(work_item.id), "field": "tags", "rule_id": str(state.rule.id),
                 "execution_id": str(state.execution.id)},
        caused_by=state.trigger_event,
    )
    if event is not None:
        state.emitted_event_ids.append(str(event.id))
    parts = ([f"added {', '.join(to_add)}"] if to_add else []) + ([f"removed {', '.join(to_remove)}"] if to_remove else [])
    return ActionOutcome(
        summary="tags: " + "; ".join(parts),
        external_ref=str(event.id) if event is not None else None,
        details={"added": to_add, "removed": to_remove},
    )


DEFINITION = ActionDefinition(
    action_type=ACTION_TYPE,
    label="Tag the document",
    description="Add or remove tags on the document, so other rules and people can find it.",
    category="Documents",
    config_model=DocumentTagConfig,
    selector="automation.flow.document_tag",
    perform=perform,
    capability=None,
    minimum_role=ROLE_WORKSPACE_ADMIN,
    idempotent=True,
    icon="tag",
)
