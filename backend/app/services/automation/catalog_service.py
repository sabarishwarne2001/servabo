"""ARCH-37 — `GET /workspaces/{id}/automation/catalog`.

Everything the step builder may offer, for this tenant, in one response:
triggers and actions with availability, operators per field type, template
variables, the workspace's observed document fields, and the resources an
action can point at (endpoints, destinations, profiles, roles, datasets).

Observed fields come from the most recent documents' extracted entities, so a
healthcare workspace sees `patient_name` and an AP workspace sees
`total_amount` without anyone maintaining a list.
"""

from __future__ import annotations

import uuid
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.entitlements import ERP_POSTING_CAPABILITY, GST_CREDIT_ADDON, WAREHOUSE_SYNC_ADDON  # ARCH47-S1:catalog-capability
from app.services.automation import actions as action_registry
from app.services.automation import triggers as catalog
from app.services.automation import document_fields
from app.services.automation.actions.base import STATIC_VARIABLES
from app.services.automation import flow_service
from app.services.automation.flow_service import Authoring

OBSERVED_SAMPLE = 200
MAX_OBSERVED_FIELDS = 120
SKIPPED_ENTITY_KEYS = frozenset({"verification", "_meta"})

def authoring_for(db: Session, *, context: Any) -> Authoring:
    from app.api import capability_gate
    from app.services.billing import entitlement_service

    granted = frozenset(
        capability_gate.granted_capabilities(db, organization_id=context.organization_id)
    )
    addons: set[str] = set()
    try:
        if entitlement_service.addon_access(
            db, organization_id=context.organization_id, addon_key=WAREHOUSE_SYNC_ADDON
        ).can_maintain:
            addons.add(WAREHOUSE_SYNC_ADDON)
    except Exception:  # noqa: BLE001 - an unreadable ledger is "no add-on"
        pass
    try:
        # Session J: the GST Credit add-on opens the GST triggers on Developer, as it opens the GST page.
        if entitlement_service.addon_access(
            db, organization_id=context.organization_id, addon_key=GST_CREDIT_ADDON
        ).can_maintain:
            addons.add(GST_CREDIT_ADDON)
    except Exception:  # noqa: BLE001
        pass
    role = getattr(getattr(context, "organization_membership", None), "role", None)
    return Authoring(
        db=db,
        organization_id=context.organization_id,
        workspace_id=context.workspace_id,
        organization_role=str(getattr(role, "value", role) or ""),
        granted_capabilities=granted,
        addons=frozenset(addons),
    )


def _type_of(value: Any) -> str | None:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, (list, tuple)):
        return "array"
    if isinstance(value, str):
        stripped = value.strip()
        if len(stripped) == 10 and stripped[4:5] == "-" and stripped[7:8] == "-":
            return "date"
        try:
            float(stripped.replace(",", ""))
            return "number" if stripped else "string"
        except ValueError:
            return "string"
    return None


def observed_fields(db: Session, *, workspace_id: uuid.UUID) -> list[dict[str, Any]]:
    from app.models.work_item import WorkItem

    rows = db.execute(
        select(WorkItem.extracted_entities)
        .where(WorkItem.workspace_id == workspace_id, WorkItem.extracted_entities.is_not(None))
        .order_by(WorkItem.created_at.desc())
        .limit(OBSERVED_SAMPLE)
    ).scalars().all()

    seen: dict[str, dict[str, Any]] = {}

    def note(path: str, value: Any) -> None:
        kind = _type_of(value)
        if kind is None:
            return
        entry = seen.setdefault(path, {"key": path, "type": kind, "count": 0, "example": ""})
        entry["count"] += 1
        if entry["type"] != kind and {entry["type"], kind} == {"number", "string"}:
            entry["type"] = "string"
        if not entry["example"] and value not in (None, "", []):
            entry["example"] = str(value if not isinstance(value, list) else (value[0] if value else ""))[:60]

    for entities in rows:
        if not isinstance(entities, dict):
            continue
        for key, value in entities.items():
            if key in SKIPPED_ENTITY_KEYS or not isinstance(key, str):
                continue
            if isinstance(value, dict):
                for sub, sub_value in value.items():
                    if isinstance(sub, str):
                        note(f"{key}.{sub}", sub_value)
            else:
                note(key, value)

    from app.core import finance_schema as fs

    # Session J: the finance schema (one table, shared with the extraction prompt) comes first, grouped by the
    # document type each field belongs to. A field a model returned under another name is counted against the
    # schema field it is an alias of; only fields the schema does not know are listed as "seen in your documents".
    counted: dict[str, int] = {}
    unknown: list[dict[str, Any]] = []
    for entry in seen.values():
        canonical = document_fields.canonical_key(entry["key"])
        if canonical in fs.BY_KEY or entry["key"] == fs.CLASSIFICATION_PATH:
            key = canonical if canonical in fs.BY_KEY else entry["key"]
            counted[key] = counted.get(key, 0) + entry["count"]
        else:
            unknown.append(entry)

    out: list[dict[str, Any]] = []
    for entry in document_fields.catalog_fields():
        seen_count = counted.get(entry["key"], 0)
        if seen_count:
            entry = {**entry, "description": f"Seen on {seen_count} recent document(s)."}
        out.append(entry)

    def _label(key: str) -> str:
        return key.replace("classification_details.", "").replace("_", " ").replace(".", " › ").capitalize()

    for entry in sorted(unknown, key=lambda e: (-e["count"], e["key"])):
        if len(out) >= MAX_OBSERVED_FIELDS + len(document_fields.catalog_fields()):
            break
        out.append({
            "key": entry["key"],
            "label": _label(entry["key"]),
            "type": entry["type"],
            "example": entry["example"],
            "description": f"Seen on {entry['count']} recent document(s).",
            "source": "document",
            "group": "Seen in your documents",
            "aliases": [],
        })
    return out


def _endpoints(db: Session, *, organization_id: uuid.UUID, workspace_id: uuid.UUID) -> list[dict[str, Any]]:
    from app.models.webhook_endpoint import WebhookEndpoint, WebhookEndpointStatus

    rows = db.execute(
        select(WebhookEndpoint)
        .where(
            WebhookEndpoint.organization_id == organization_id,
            WebhookEndpoint.status == WebhookEndpointStatus.ACTIVE,
            WebhookEndpoint.kind == "GENERIC",
            (WebhookEndpoint.workspace_id.is_(None)) | (WebhookEndpoint.workspace_id == workspace_id),
        )
        .order_by(WebhookEndpoint.created_at.asc())
    ).scalars().all()
    return [
        {
            "id": str(row.id),
            # The host only. Paths often carry tokens.
            "label": (row.description or urlparse(row.url).hostname or "endpoint")[:120],
            "host": urlparse(row.url).hostname or "",
        }
        for row in rows
    ]


def _chat_endpoints(db: Session, *, organization_id: uuid.UUID, workspace_id: uuid.UUID) -> list[dict[str, Any]]:
    """Session J: the Slack and Teams channels `chat.post` may name. Never the URL, which is a secret."""
    from app.models.webhook_endpoint import WebhookEndpoint, WebhookEndpointStatus

    rows = db.execute(
        select(WebhookEndpoint)
        .where(
            WebhookEndpoint.organization_id == organization_id,
            WebhookEndpoint.status == WebhookEndpointStatus.ACTIVE,
            WebhookEndpoint.kind != "GENERIC",
            (WebhookEndpoint.workspace_id.is_(None)) | (WebhookEndpoint.workspace_id == workspace_id),
        )
        .order_by(WebhookEndpoint.created_at.asc())
    ).scalars().all()
    return [{"id": str(row.id), "label": (row.description or row.kind)[:120], "kind": row.kind} for row in rows]


def _case_templates(db: Session, *, workspace_id: uuid.UUID) -> list[dict[str, Any]]:
    from app.models.cases import CaseTemplate
    from app.services.cases import vocabulary as cv

    rows = db.execute(select(CaseTemplate).where(CaseTemplate.workspace_id == workspace_id,
                                                  CaseTemplate.status == cv.TEMPLATE_PUBLISHED)
                      .order_by(CaseTemplate.name)).scalars().all()
    return [{"id": str(row.id), "label": row.name} for row in rows]


def _members(db: Session, *, workspace_id: uuid.UUID, organization_id: uuid.UUID) -> list[dict[str, Any]]:
    """People a rule may assign a review or a follow-up to: those who can work review items here."""
    from app.services.automation.actions import review_assign

    return [{"email": user.email, "name": (getattr(user, "full_name", None) or user.email)}
            for user, _role in review_assign._holders(db, workspace_id=workspace_id, organization_id=organization_id)]  # noqa: SLF001


def _destinations(db: Session, *, organization_id: uuid.UUID) -> list[dict[str, Any]]:
    from app.services.analytics import sync_service

    return [
        {"id": str(row.id), "label": row.label, "kind": row.kind}
        for row in sync_service.list_destinations(db, organization_id=organization_id)
        if row.is_active
    ]


def _erp_targets(db: Session, *, workspace_id: uuid.UUID) -> list[dict[str, Any]]:
    """ARCH47-S1:catalog-erp-targets. Active ERP targets the erp.post action can name."""
    from app.models.erp import ErpTarget
    from app.services.erp import presets as PR
    from app.services.erp import vocabulary as ev

    rows = db.execute(select(ErpTarget).where(ErpTarget.workspace_id == workspace_id,
                                              ErpTarget.status == ev.TARGET_ACTIVE)
                      .order_by(ErpTarget.name)).scalars().all()
    return [{"id": str(t.id), "label": t.name, "format": t.format, "preset": t.preset,
             "objects": list(PR.supported_objects(t.format, t.preset))} for t in rows]


def _workspace_settings(db: Session, workspace_id: uuid.UUID) -> dict[str, Any]:
    """What the builder needs to show amounts and dates the way this workspace reads them."""
    from app.models.workspace import Workspace

    workspace = db.get(Workspace, workspace_id)
    return {
        "currency": (getattr(workspace, "currency", None) or "USD"),
        "date_format": (getattr(workspace, "date_format", None) or "YYYY-MM-DD"),
        "timezone": (getattr(workspace, "timezone", None) or "UTC"),
    }


def build(db: Session, *, context: Any) -> dict[str, Any]:
    from app.models.warehouse_sync import EXPORT_DATASET_VALUES
    from app.services.automation.actions.notify_role import ROLE_VALUES
    from app.services.automation.actions.work_item_mutate import MUTABLE_COLUMNS
    from app.services.redaction.vocabulary import PROFILE_KEYS

    authoring = authoring_for(db, context=context)
    triggers = []
    for entry in catalog.catalog_triggers():
        spec = catalog.TRIGGERS_BY_KEY[entry["key"]]
        entry["available"] = catalog.available_for(
            spec, capabilities=authoring.granted_capabilities, addons=authoring.addons)
        # Session J: what the trigger forbids, complete (a Helm trigger allows only a few actions).
        if spec.allowed_actions is not None:
            entry["excluded_actions"] = sorted(set(action_registry.ACTIONS) - set(spec.allowed_actions))
        entry["unavailable_reason"] = None if entry["available"] else (
            "Needs the GST Credit add-on or a plan that includes GST Credit."
            if spec.addon is not None else "Not included in your plan.")
        triggers.append(entry)

    actions = []
    for action_type, definition in action_registry.ACTIONS.items():
        reason = None
        if not flow_service.action_available(
                definition, capabilities=authoring.granted_capabilities, addons=authoring.addons):
            if definition.either:
                reason = "Needs GST Credit, or the GST Credit add-on."
            elif definition.capability and definition.capability not in authoring.granted_capabilities:
                reason = "Not included in your plan."
            else:
                reason = "Needs the warehouse sync add-on."
        elif definition.minimum_role == "ORGANIZATION_ADMIN" and authoring.organization_role not in ("OWNER", "ADMIN"):
            reason = "Only organization owners and admins can add this."
        actions.append(
            {
                "type": action_type,
                "label": definition.label,
                "description": definition.description,
                "category": definition.category,
                "capability": definition.capability,
                "addon": definition.addon,
                "minimum_role": definition.minimum_role,
                "available": reason is None,
                "unavailable_reason": reason,
                "commercial": action_type in action_registry.COMMERCIAL_ACTION_TYPES,
                "needs_document": action_type in flow_service.DOCUMENT_ACTIONS,
                "idempotent": definition.idempotent,
                "icon": definition.icon,
                "either": definition.either,
                "template_fields": list(definition.template_fields),
                # Legacy stored names (e.g. the ARCH-13 console's email type),
                # so the builder can open an old rule without a vocabulary.
                "aliases": list(definition.aliases),
                "config_schema": definition.schema(),
            }
        )

    resources: dict[str, Any] = {
        "webhook_endpoints": _endpoints(
            db, organization_id=authoring.organization_id, workspace_id=authoring.workspace_id
        ),
        "warehouse_destinations": (
            _destinations(db, organization_id=authoring.organization_id)
            if WAREHOUSE_SYNC_ADDON in authoring.addons
            else []
        ),
        "redaction_profiles": list(PROFILE_KEYS),
        "organization_roles": list(ROLE_VALUES),
        "export_datasets": list(EXPORT_DATASET_VALUES),
        "mutable_fields": list(MUTABLE_COLUMNS),
        # Session J
        "chat_endpoints": _chat_endpoints(
            db, organization_id=authoring.organization_id, workspace_id=authoring.workspace_id),
        "case_templates": _case_templates(db, workspace_id=authoring.workspace_id),
        "members": _members(db, workspace_id=authoring.workspace_id, organization_id=authoring.organization_id),
        "obligation_kinds": list(__import__("app.services.automation.actions.obligation_create", fromlist=["KINDS"]).KINDS),
        # ARCH47-S1:catalog-erp-resources
        "erp_targets": (
            _erp_targets(db, workspace_id=authoring.workspace_id)
            if ERP_POSTING_CAPABILITY in authoring.granted_capabilities
            else []
        ),
        "erp_object_kinds": ["VENDOR_BILL", "PURCHASE_ORDER", "GOODS_RECEIPT", "JOURNAL_ENTRY", "PAYMENT_REFERENCE"],
    }
    return {
        "triggers": triggers,
        "actions": actions,
        "operators": {k: list(v) for k, v in catalog.OPERATORS_BY_TYPE.items()},
        "valueless_operators": sorted(catalog.VALUELESS_OPERATORS),
        # Session J: how the builder shapes a value.
        "day_count_operators": sorted(catalog.DAY_COUNT_OPERATORS),
        "list_value_operators": sorted(catalog.LIST_VALUE_OPERATORS),
        "workspace": _workspace_settings(db, authoring.workspace_id),
        "template_variables": list(STATIC_VARIABLES),
        "document_fields": observed_fields(db, workspace_id=authoring.workspace_id),
        "resources": resources,
        "limits": {"triggers": 4, "groups": 10, "conditions_per_group": 20, "actions_per_branch": 10},
    }


__all__ = ["authoring_for", "build", "observed_fields"]
