"""Session J, Phase 4 — a rule's history: a snapshot at every save, a plain-words diff, and Restore.

A snapshot is the rule as a complete flow document (the same shape `flow_service.payload_from_rule` hands back for a
merge) plus the few settings that sit beside it. Restoring a version feeds the snapshot through the same validation as a
save, so a version that no longer passes (an action the plan dropped) says so instead of half-applying, and it writes a
NEW version: history only ever grows.
"""

from __future__ import annotations

import uuid
from typing import Any, Mapping, Optional

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core import finance_schema as fs
from app.models.automation import AutomationRuleVersion
from app.services.automation import document_fields as df
from app.services.automation import evaluator as ev
from app.services.automation import flow_service
from app.services.automation.triggers import EVENT_FIELD_PREFIX, TRIGGERS_BY_KEY

SETTINGS_KEYS = ("name", "priority", "is_active", "max_runs_per_hour", "cooldown_hours")
MAX_VERSIONS_LISTED = 100


def snapshot_of(rule: Any, event_types: list[str]) -> dict[str, Any]:
    body = flow_service.payload_from_rule(rule, event_types)
    # Saved as JSON: groups can be pydantic-free dicts already; settings sit beside them.
    snap: dict[str, Any] = {k: body[k] for k in body}
    for key in SETTINGS_KEYS:
        snap[key] = getattr(rule, key, None)
    return snap


def _next_version(db: Session, rule_id: uuid.UUID) -> int:
    db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": f"automation.versions:{rule_id}"})
    current = db.execute(
        select(func.max(AutomationRuleVersion.version)).where(AutomationRuleVersion.rule_id == rule_id)
    ).scalar_one()
    return int(current or 0) + 1


def latest(db: Session, rule_id: uuid.UUID) -> Optional[AutomationRuleVersion]:
    return db.execute(
        select(AutomationRuleVersion)
        .where(AutomationRuleVersion.rule_id == rule_id)
        .order_by(AutomationRuleVersion.version.desc())
        .limit(1)
    ).scalar_one_or_none()


def record(
    db: Session,
    *,
    rule: Any,
    event_types: list[str],
    user_id: Optional[uuid.UUID],
    note: Optional[str] = None,
    restored_from_version: Optional[int] = None,
) -> Optional[AutomationRuleVersion]:
    """Write the rule's current state as the next version. A save that changed nothing writes nothing."""
    snap = snapshot_of(rule, event_types)
    previous = latest(db, rule.id)
    if previous is not None and previous.snapshot == snap and restored_from_version is None:
        return None
    text_note = (note or "").strip()
    if not text_note:
        changes = describe_changes(previous.snapshot if previous else None, snap)
        text_note = changes[0] if changes else "Saved"
    row = AutomationRuleVersion(
        organization_id=_organization_id(db, rule),
        workspace_id=rule.workspace_id,
        rule_id=rule.id,
        version=_next_version(db, rule.id),
        snapshot=snap,
        note=text_note[:200],
        created_by_user_id=user_id,
        restored_from_version=restored_from_version,
    )
    db.add(row)
    db.flush([row])
    return row


def _organization_id(db: Session, rule: Any) -> uuid.UUID:
    from app.models.workspace import Workspace

    return db.execute(select(Workspace.organization_id).where(Workspace.id == rule.workspace_id)).scalar_one()


# ------------------------------------------------------------------------------------------------- plain words


def _field_label(path: str, triggers: list[str]) -> str:
    if path.startswith(EVENT_FIELD_PREFIX):
        key = path[len(EVENT_FIELD_PREFIX):]
        for trigger_key in triggers:
            spec = TRIGGERS_BY_KEY.get(trigger_key)
            for declared in (spec.fields if spec else ()):
                if declared.key == key:
                    return declared.label
        return ev.humanize(key)
    for derived in df.DERIVED_FIELDS:
        if derived["key"] == path:
            return str(derived["label"])
    declared = fs.BY_KEY.get(df.canonical_key(path))
    return declared.label if declared else ev.humanize(path)


def _value_text(value: Any, currency: Any = None) -> str:
    if isinstance(value, (list, tuple)):
        shown = ", ".join(str(v) for v in value)
    else:
        shown = str(value if value is not None else "")
    return f"{shown} {currency}".strip() if currency else shown


def condition_text(condition: Mapping[str, Any], triggers: list[str]) -> str:
    operator = str(condition.get("operator") or "").upper()
    phrase = ev.PHRASES.get(operator, (operator.lower().replace("_", " "), ""))[0]
    label = _field_label(str(condition.get("field") or ""), triggers)
    if operator in ("EXISTS", "IS_EMPTY", "IS_NOT_EMPTY"):
        return f"{label} {phrase}"
    value = _value_text(condition.get("value"), condition.get("currency"))
    if operator in ("WITHIN_NEXT_DAYS", "WITHIN_LAST_DAYS", "OLDER_THAN_DAYS"):
        value = f"{value} days"
    return f"{label} {phrase} {value}".strip()


def _conditions(snap: Mapping[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for group in snap.get("condition_groups") or []:
        out.extend(c for c in (group.get("conditions") or []) if isinstance(c, Mapping))
    if not snap.get("condition_groups"):
        out.extend(c for c in (snap.get("conditions") or []) if isinstance(c, Mapping))
    return out


def _action_label(entry: Mapping[str, Any]) -> str:
    from app.services.automation import actions as registry

    definition = registry.get(str(entry.get("action_type") or ""))
    return definition.label if definition is not None else str(entry.get("action_type") or "an action")


def _signature(item: Mapping[str, Any]) -> str:
    import json

    return json.dumps(item, sort_keys=True, default=str)


def _trigger_label(key: str) -> str:
    spec = TRIGGERS_BY_KEY.get(key)
    return spec.label if spec else ev.humanize(key)


def describe_changes(old: Optional[Mapping[str, Any]], new: Mapping[str, Any]) -> list[str]:
    """The difference between two snapshots as sentences. `old` None means the first version."""
    if old is None:
        return ["Created the rule"]
    out: list[str] = []
    triggers = list(new.get("triggers") or [])

    if old.get("name") != new.get("name"):
        out.append(f"Renamed the rule from “{old.get('name')}” to “{new.get('name')}”")
    if old.get("is_active") != new.get("is_active"):
        out.append("Switched the rule on" if new.get("is_active") else "Switched the rule off")
    if old.get("priority") != new.get("priority"):
        out.append(f"Changed the priority from {old.get('priority')} to {new.get('priority')}")

    old_triggers, new_triggers = list(old.get("triggers") or []), list(new.get("triggers") or [])
    for key in new_triggers:
        if key not in old_triggers:
            out.append(f"Added trigger: {_trigger_label(key)}")
    for key in old_triggers:
        if key not in new_triggers:
            out.append(f"Removed trigger: {_trigger_label(key)}")
    if old.get("event") != new.get("event") and not new_triggers and not old_triggers:
        out.append(f"Changed the trigger event from {old.get('event')} to {new.get('event')}")

    old_c, new_c = _conditions(old), _conditions(new)
    old_sigs = {_signature(c): c for c in old_c}
    new_sigs = {_signature(c): c for c in new_c}
    for sig, condition in new_sigs.items():
        if sig not in old_sigs:
            out.append(f"Added condition: {condition_text(condition, triggers)}")
    for sig, condition in old_sigs.items():
        if sig not in new_sigs:
            out.append(f"Removed condition: {condition_text(condition, triggers)}")
    if old.get("groups_operator") != new.get("groups_operator") and (old.get("groups_operator") and new.get("groups_operator")):
        out.append("Changed how the condition groups combine: "
                   + ("any group can match" if new.get("groups_operator") == "OR" else "every group must match"))

    for label, key in (("step", "actions"), ("“otherwise” step", "else_actions")):
        old_a = [a for a in (old.get(key) or []) if isinstance(a, Mapping)]
        new_a = [a for a in (new.get(key) or []) if isinstance(a, Mapping)]
        old_a_sigs = {_signature(a): a for a in old_a}
        new_a_sigs = {_signature(a): a for a in new_a}
        added = [a for s, a in new_a_sigs.items() if s not in old_a_sigs]
        removed = [a for s, a in old_a_sigs.items() if s not in new_a_sigs]
        # The same kind of step with different settings reads as a change, not a removal plus an addition.
        for a in list(added):
            match = next((r for r in removed if r.get("action_type") == a.get("action_type")), None)
            if match is not None:
                out.append(f"Changed the settings of the {label}: {_action_label(a)}")
                added.remove(a)
                removed.remove(match)
        out.extend(f"Added {label}: {_action_label(a)}" for a in added)
        out.extend(f"Removed {label}: {_action_label(a)}" for a in removed)

    if old.get("on_error") != new.get("on_error"):
        out.append("When a step fails, the rule now "
                   + ("carries on with the next step" if new.get("on_error") == "CONTINUE" else "stops"))

    if old.get("max_runs_per_hour") != new.get("max_runs_per_hour"):
        was, now = old.get("max_runs_per_hour"), new.get("max_runs_per_hour")
        if now is None:
            out.append("Went back to the workspace's default runs-per-hour limit")
        elif was is None:
            out.append(f"Set a limit of {now} runs an hour")
        else:
            out.append(f"{'Raised' if now > was else 'Lowered'} the limit from {was} to {now} runs an hour")
    if old.get("cooldown_hours") != new.get("cooldown_hours"):
        now = new.get("cooldown_hours")
        out.append("Removed the once-per-document cooldown" if now is None
                   else f"Set the rule to run at most once per document every {now} hour{'s' if now != 1 else ''}")
    return out


def view(row: AutomationRuleVersion, previous: Optional[AutomationRuleVersion], names: Mapping[uuid.UUID, str]) -> dict[str, Any]:
    return {
        "id": row.id,
        "version": row.version,
        "note": row.note,
        "created_at": row.created_at,
        "created_by_user_id": row.created_by_user_id,
        "created_by_name": names.get(row.created_by_user_id) if row.created_by_user_id else None,
        "restored_from_version": row.restored_from_version,
        "changes": describe_changes(previous.snapshot if previous else None, row.snapshot),
    }


def history(db: Session, *, rule_id: uuid.UUID, limit: int = 50, offset: int = 0) -> tuple[list[AutomationRuleVersion], int]:
    total = int(
        db.execute(select(func.count()).select_from(AutomationRuleVersion).where(AutomationRuleVersion.rule_id == rule_id)).scalar_one()
    )
    rows = list(
        db.execute(
            select(AutomationRuleVersion)
            .where(AutomationRuleVersion.rule_id == rule_id)
            .order_by(AutomationRuleVersion.version.desc())
            .limit(min(limit, MAX_VERSIONS_LISTED))
            .offset(offset)
        ).scalars()
    )
    return rows, total


def previous_of(db: Session, row: AutomationRuleVersion) -> Optional[AutomationRuleVersion]:
    return db.execute(
        select(AutomationRuleVersion)
        .where(AutomationRuleVersion.rule_id == row.rule_id, AutomationRuleVersion.version == row.version - 1)
    ).scalar_one_or_none()


__all__ = ["condition_text", "describe_changes", "history", "latest", "previous_of", "record", "snapshot_of", "view"]
