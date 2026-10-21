"""Session J action `chat.post` — post a message to Slack or Microsoft Teams.

The channel is one of the organization's registered chat endpoints (`webhook_endpoints` with kind SLACK or TEAMS), so
there is no URL in the rule (the same guardrail as `webhook.send`: a free URL in a tenant-written rule is a request
forgery primitive). The endpoint's incoming-webhook URL is a secret and is stored encrypted; it is never shown back in full.

DELIVERY is the webhook registry's own: one `webhook_deliveries` row, sent by the delivery loop through the egress gate
(an organization's network rules can refuse the host), retried with backoff, every attempt logged. The message is formatted
as each platform expects (Slack text with `&` `<` `>` escaped so a document's text can never ping the channel; a Teams
Adaptive Card). Values from the document are plain text and truncated.
"""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import Field

from app.core.entitlements import OUTGOING_WEBHOOKS_CAPABILITY
from app.services.automation.actions.base import (
    ROLE_ORGANIZATION_ADMIN,
    ActionConfig,
    ActionDefinition,
    ActionFailure,
    ActionOutcome,
    SaveContext,
    plain_variables_for,
    render,
)
from app.services.automation.actions.webhook_send import load_endpoint

ACTION_TYPE = "chat.post"
MAX_MESSAGE = 1500


class ChatPostConfig(ActionConfig):
    endpoint_id: uuid.UUID = Field(description="A registered Slack or Microsoft Teams channel.")
    title: str = Field(default="{{rule.name}}", max_length=150)
    message: str = Field(default="{{trigger.label}}: {{document.filename}}", min_length=1, max_length=MAX_MESSAGE)


def _validate(ctx: SaveContext, config: ActionConfig) -> dict[str, str]:
    assert isinstance(config, ChatPostConfig)
    endpoint, reason = load_endpoint(ctx.db, endpoint_id=config.endpoint_id, organization_id=ctx.organization_id,
                                     workspace_id=ctx.workspace_id, chat=True)
    if endpoint is None:
        return {"endpoint_id": reason or "Chat channel not found."}
    from app.core import egress
    from app.services.webhook_service import InvalidURLError  # noqa: F401  (the registry's own refusal type)

    try:
        egress.guard(egress.WEBHOOK, _host_of(endpoint), 443, organization_id=ctx.organization_id, db=ctx.db, record=False)
    except egress.EgressDenied:
        return {"endpoint_id": "Your organization's network rules do not allow posting to this chat service."}
    return {}


def _host_of(endpoint: Any) -> str:
    from urllib.parse import urlsplit

    return urlsplit(endpoint.delivery_url).hostname or ""


def perform(state: Any, spec: Any) -> ActionOutcome:
    from app.models.webhook_delivery import WebhookDelivery, WebhookDeliveryStatus
    from app.services import webhook_service

    config = DEFINITION.parse_spec(spec)
    assert isinstance(config, ChatPostConfig)
    endpoint, reason = load_endpoint(state.db, endpoint_id=config.endpoint_id,
                                     organization_id=state.execution.organization_id,
                                     workspace_id=state.execution.workspace_id, chat=True)
    if endpoint is None:
        raise ActionFailure(reason or "Chat channel unavailable.", recoverable=False)
    values = plain_variables_for(state)
    title = render(config.title, values).strip()[:150]
    message = render(config.message, values).strip()[:MAX_MESSAGE] or title or state.rule.name
    body = webhook_service.chat_body(endpoint.kind, title=title, message=message)
    delivery = WebhookDelivery(
        webhook_endpoint_id=endpoint.id,
        outbox_event_id=None,
        organization_id=state.execution.organization_id,
        event_type=webhook_service.CHAT_EVENT_TYPE,
        payload={"chat": body, "rule_id": str(state.rule.id), "execution_id": str(state.execution.id)},
        status=WebhookDeliveryStatus.PENDING,
    )
    state.db.add(delivery)
    state.db.flush([delivery])
    return ActionOutcome(
        summary=f"message queued for {webhook_service.CHAT_LABELS.get(endpoint.kind, endpoint.kind)}",
        external_ref=str(delivery.id),
        details={"endpoint_id": str(endpoint.id), "kind": endpoint.kind},
    )


DEFINITION = ActionDefinition(
    action_type=ACTION_TYPE,
    label="Post a message to chat",
    description="Post to a Slack or Microsoft Teams channel you registered. Only plain text from the rule and the document is sent.",
    category="Integrations",
    config_model=ChatPostConfig,
    selector="automation.flow.chat_post",
    perform=perform,
    capability=OUTGOING_WEBHOOKS_CAPABILITY,
    minimum_role=ROLE_ORGANIZATION_ADMIN,
    template_fields=("title", "message"),
    validate_resources=_validate,
    idempotent=False,
    icon="message-square",
)
