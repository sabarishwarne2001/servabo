"""
Automation Rules API router endpoints for Servabo.
"""

import asyncio
import logging
import uuid
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status, Query, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import crud
from app.core.pagination import MAX_OFFSET
from app.api import deps
# L-1. The /logs query joins these two. Neither was imported —
# the module only ever needed AutomationExecution before.
from app.models.automation import AutomationRule
from app.models.work_item import WorkItem
from app.models.automation_execution import (
    AutomationExecution,
    AutomationExecutionStatus,
    SKIPPED_STATUSES,
    SUPPRESSED_STATUSES,
)
from app.services.automation.volume import RETRYABLE_STATUSES
from app.services.automation_service import automation_service
from app.schemas.automation import (
    AutomationRuleCreate,
    AutomationRuleUpdate,
    AutomationRuleResponse,
    AutomationLogResponse,
    AutomationRuleTestRequest,
    AutomationRuleTestResponse,
)


router = APIRouter(tags=["Automation"])


def _require_automations(db: Session, context: deps.TenantContext, operation: str) -> None:
    """N-049 (campaign session 1). Building, changing, testing or running a rule needs the
    plan's automations; seeing, switching off and deleting one never does (N-003)."""
    from app.api import capability_gate
    from app.core import entitlements

    capability_gate.require_capability(
        db, context=context, capability_key=entitlements.AUTOMATIONS_CAPABILITY, operation=operation
    )


logger = logging.getLogger("app.api.v1.automation")


# ==========================================================================
# ARCH-13 execution traces
# ==========================================================================


class AutomationNodeRunResponse(BaseModel):
    """One node inside an execution."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    node_key: Optional[str] = None
    node_type: Optional[str] = None
    sequence: int = 0
    status: str
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    attempt: int = 0
    error: Optional[str] = None
    # ARCH37-S1:node-run-response
    action_type: Optional[str] = None
    external_ref: Optional[str] = None
    duration_ms: Optional[int] = None
    outcome: Optional[str] = None
    # Session J: what each condition read, wanted and decided, in words (identifiers masked).
    conditions: list[dict[str, Any]] = Field(default_factory=list)
    matched: Optional[bool] = None


# ==========================================================================
# ARCH-37 flow builder
# ==========================================================================


def _flow_issues(exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=list(getattr(exc, "issues", [])) or [
            {"loc": ["body"], "msg": str(exc), "type": "value_error"}
        ],
    )


def _audit_rule(
    db: Session,
    *,
    context: Any,
    rule: AutomationRule,
    action: Any,
    details: dict[str, Any],
) -> None:
    from app.models.audit_log import AuditOutcome, AuditResourceType
    from app.services import audit_service

    audit_service.record(
        db,
        organization_id=context.organization_id,
        workspace_id=context.workspace_id,
        actor_id=context.user_id,
        resource_type=AuditResourceType.AUTOMATION_RULE,
        resource_id=rule.id,
        action=action,
        outcome=AuditOutcome.ALLOWED,
        details={"rule_name": rule.name, **details},
    )


def _workspace_paused(db: Session, workspace_id: uuid.UUID) -> bool:
    from app.models.workspace import Workspace
    from app.services.automation import volume

    return volume.is_paused(db.get(Workspace, workspace_id))


def _latest_versions(db: Session, rule_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    from sqlalchemy import func

    from app.models.automation import AutomationRuleVersion

    if not rule_ids:
        return {}
    rows = db.execute(
        select(AutomationRuleVersion.rule_id, func.max(AutomationRuleVersion.version))
        .where(AutomationRuleVersion.rule_id.in_(rule_ids))
        .group_by(AutomationRuleVersion.rule_id)
    ).all()
    return {rule_id: int(version) for rule_id, version in rows}


def _view(db: Session, rule: AutomationRule) -> dict[str, Any]:
    from app.services.automation import flow_service, rule_triggers

    events = rule_triggers.event_types_of(db, rule_ids=[rule.id]).get(rule.id, [])
    return flow_service.rule_view(
        rule, events,
        paused=_workspace_paused(db, rule.workspace_id),
        version=_latest_versions(db, [rule.id]).get(rule.id, 0),
    )


@router.get(
    "/catalog",
    summary="Flow builder catalog",
    response_description=(
        "Triggers, actions, operators, template variables, observed document "
        "fields and the resources actions may reference. The console renders "
        "this and holds no trigger or action list of its own."
    ),
)
def get_catalog(
    db: Session = Depends(deps.get_db),
    context: deps.TenantContext = Depends(deps.RequireWorkspaceContributor),
) -> dict[str, Any]:
    from app.services.automation import catalog_service

    return catalog_service.build(db, context=context)


@router.get(
    "/executions/{execution_id}/nodes",
    response_model=list[AutomationNodeRunResponse],
    summary="Node runs of one execution",
)
def list_execution_nodes(
    execution_id: uuid.UUID,
    db: Session = Depends(deps.get_db),
    context: deps.TenantContext = Depends(deps.RequireWorkspaceContributor),
) -> list[AutomationNodeRunResponse]:
    from app.models.automation_execution import AutomationNodeRun

    owned = db.execute(
        select(AutomationExecution.id).where(
            AutomationExecution.id == execution_id,
            AutomationExecution.workspace_id == context.workspace_id,
        )
    ).scalar_one_or_none()
    if owned is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Execution not found.")
    rows = db.execute(
        select(AutomationNodeRun)
        .where(AutomationNodeRun.execution_id == execution_id)
        .order_by(AutomationNodeRun.sequence.asc())
    ).scalars().all()
    return [
        AutomationNodeRunResponse(
            id=row.id,
            node_key=row.node_key,
            node_type=row.node_type,
            sequence=row.sequence,
            status=getattr(row.status, "value", getattr(row.status, "value", row.status)),
            started_at=row.started_at,
            completed_at=row.completed_at,
            error=row.error,
            action_type=row.action_type,
            external_ref=row.external_ref,
            duration_ms=row.duration_ms,
            outcome=(row.details or {}).get("outcome") if isinstance(row.details, dict) else None,
            conditions=list((row.details or {}).get("conditions") or []) if isinstance(row.details, dict) else [],
            matched=(row.details or {}).get("matched") if isinstance(row.details, dict) else None,
        )
        for row in rows
    ]


class AutomationExecutionResponse(BaseModel):
    """One execution, with the fields a causal timeline needs."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    workspace_id: uuid.UUID
    rule_id: uuid.UUID
    rule_name: Optional[str] = None
    work_item_id: Optional[uuid.UUID] = None
    outbox_event_id: Optional[uuid.UUID] = None

    correlation_id: uuid.UUID
    depth: int
    status: str

    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    deadline_at: Optional[datetime] = None
    created_at: datetime

    budget_cost_micros: int
    spent_cost_micros: int

    node_count: int
    nodes_executed: int
    actions_executed: int

    emitted_event_ids: list[str] = Field(default_factory=list)
    error: Optional[str] = None
    details: dict[str, Any] = Field(default_factory=dict)
    is_suppressed: bool = False
    duration_ms: Optional[int] = None
    #: Session J. Held back on purpose (paused, throttled, cooldown): `error` says why, in words.
    is_skipped: bool = False
    #: Session J. This run is a retry of that one.
    retry_of_id: Optional[uuid.UUID] = None
    #: Session J. The run broke part way, so "Retry" is offered (the retry route checks the rest).
    retryable: bool = False


class AutomationExecutionPage(BaseModel):
    """A page of executions, newest first."""

    items: list[AutomationExecutionResponse]
    limit: int
    has_more: bool
    next_offset: Optional[int] = None


def _rule_names(db: Session, rule_ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    """F-140. One query for a page's rule names: the execution model has no `rule` relationship,
    so reading one always gave None and Run history could only say "Rule 1f3a9c0e"."""
    if not rule_ids:
        return {}
    # F-150: a deleted rule's runs stay in the history, named and marked as deleted.
    return {
        rule_id: f"{name} (deleted)" if deleted_at is not None else name
        for rule_id, name, deleted_at in db.execute(
            select(AutomationRule.id, AutomationRule.name, AutomationRule.deleted_at).where(
                AutomationRule.id.in_(rule_ids)
            )
        ).all()
    }


def _execution_view(
    row: AutomationExecution, rule_name: Optional[str] = None
) -> AutomationExecutionResponse:
    duration_ms: Optional[int] = None
    if row.started_at is not None and row.completed_at is not None:
        delta = row.completed_at - row.started_at
        duration_ms = max(int(delta.total_seconds() * 1000), 0)

    status_value = (
        row.status.value if hasattr(row.status, "value") else getattr(row.status, "value", row.status)
    )

    return AutomationExecutionResponse(
        id=row.id,
        organization_id=row.organization_id,
        workspace_id=row.workspace_id,
        rule_id=row.rule_id,
        rule_name=rule_name,
        work_item_id=row.work_item_id,
        outbox_event_id=row.outbox_event_id,
        correlation_id=row.correlation_id,
        depth=row.depth,
        status=status_value,
        started_at=row.started_at,
        completed_at=row.completed_at,
        deadline_at=row.deadline_at,
        created_at=row.created_at,
        budget_cost_micros=row.budget_cost_micros,
        spent_cost_micros=row.spent_cost_micros,
        node_count=row.node_count,
        nodes_executed=row.nodes_executed,
        actions_executed=row.actions_executed,
        emitted_event_ids=list(row.emitted_event_ids or []),
        error=row.error,
        details=dict(row.details or {}),
        is_suppressed=status_value
        in {s.value for s in SUPPRESSED_STATUSES},
        duration_ms=duration_ms,
        is_skipped=row.status in SKIPPED_STATUSES,
        retry_of_id=row.retry_of_id,
        retryable=row.status in RETRYABLE_STATUSES,
    )


@router.get(
    "/executions",
    response_model=AutomationExecutionPage,
    summary="List Automation Executions (causal traces)",
    response_description=(
        "Executions newest first, including SUPPRESSED_CYCLE and "
        "SUPPRESSED_DEPTH refusals that never appear in /logs."
    ),
)
def list_executions(
    db: Session = Depends(deps.get_db),
    context: deps.TenantContext = Depends(deps.RequireWorkspaceContributor),
    correlation_id: Optional[uuid.UUID] = Query(
        None,
        description=(
            "Return one causal chain. This is the filter that makes a cycle "
            "visible: a loop is a property of a chain, not of a rule."
        ),
    ),
    rule_id: Optional[uuid.UUID] = Query(
        None, description="Return executions of one rule."
    ),
    work_item_id: Optional[uuid.UUID] = Query(
        None, description="Return executions triggered by one document."
    ),
    execution_status: Optional[AutomationExecutionStatus] = Query(
        None, alias="status", description="Filter by execution status."
    ),
    suppressed_only: bool = Query(
        False,
        description=(
            "Only refusals — SUPPRESSED_CYCLE and SUPPRESSED_DEPTH. The "
            "'what is silently not running' view."
        ),
    ),
    offset: int = Query(0, ge=0, le=MAX_OFFSET),
    limit: int = Query(100, ge=1, le=200),
) -> AutomationExecutionPage:
    stmt = select(AutomationExecution).where(
        AutomationExecution.workspace_id == context.workspace_id,
    )

    if correlation_id is not None:
        stmt = stmt.where(AutomationExecution.correlation_id == correlation_id)
    if rule_id is not None:
        stmt = stmt.where(AutomationExecution.rule_id == rule_id)
    if work_item_id is not None:
        stmt = stmt.where(AutomationExecution.work_item_id == work_item_id)
    if execution_status is not None:
        stmt = stmt.where(AutomationExecution.status == execution_status)
    if suppressed_only:
        stmt = stmt.where(AutomationExecution.status.in_(SUPPRESSED_STATUSES))

    if correlation_id is not None:
        stmt = stmt.order_by(
            AutomationExecution.depth.asc(),
            AutomationExecution.created_at.asc(),
            AutomationExecution.id.asc(),
        )
    else:
        stmt = stmt.order_by(
            AutomationExecution.created_at.desc(),
            AutomationExecution.id.desc(),
        )

    rows = db.execute(stmt.offset(offset).limit(limit + 1)).scalars().all()

    has_more = len(rows) > limit
    page = rows[:limit]

    names = _rule_names(db, {row.rule_id for row in page})
    return AutomationExecutionPage(
        items=[_execution_view(row, names.get(row.rule_id)) for row in page],
        limit=limit,
        has_more=has_more,
        next_offset=(offset + limit) if has_more else None,
    )


@router.get(
    "/executions/{execution_id}",
    response_model=AutomationExecutionResponse,
    summary="Get one Automation Execution",
    response_description="A single execution including its suppression detail.",
)
def get_execution(
    execution_id: uuid.UUID,
    db: Session = Depends(deps.get_db),
    context: deps.TenantContext = Depends(deps.RequireWorkspaceContributor),
) -> Any:
    row = db.execute(
        select(AutomationExecution).where(
            AutomationExecution.id == execution_id,
            AutomationExecution.workspace_id == context.workspace_id,
        )
    ).scalar_one_or_none()

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Execution not found or you do not have permission to access it.",
        )

    return _execution_view(row, _rule_names(db, {row.rule_id}).get(row.rule_id))


@router.post(
    "/rules", 
    response_model=AutomationRuleResponse, 
    status_code=status.HTTP_201_CREATED,
    summary="Create a new Automation Rule",
    response_description="The registered Automation Rule with generated UUID."
)
def create_rule(
    rule_in: AutomationRuleCreate,
    db: Session = Depends(deps.get_db),
    context: deps.TenantContext = Depends(deps.RequireWorkspaceAdmin)
) -> Any:
    # ARCH37-S1:flow-create. Validated as a whole rule, stored with its
    # trigger rows, audited, committed once.
    from app.models.audit_log import AuditAction
    from app.services.automation import catalog_service, flow_service, rule_triggers, versions

    _require_automations(db, context, "automation.rule.create")
    authoring = catalog_service.authoring_for(db, context=context)
    try:
        normalised = flow_service.normalise(rule_in.model_dump(mode="json"), authoring)
    except flow_service.FlowValidationError as exc:
        raise _flow_issues(exc) from exc

    rule = AutomationRule(
        name=rule_in.name,
        priority=rule_in.priority,
        event=normalised.event,
        conditions=normalised.conditions,
        logic_operator=normalised.logic_operator,
        actions=normalised.actions,
        is_active=rule_in.is_active,
        on_error=normalised.on_error,
        flow_spec=normalised.flow_spec,
        max_runs_per_hour=rule_in.max_runs_per_hour,
        cooldown_hours=rule_in.cooldown_hours,
        workspace_id=context.workspace_id,
        created_by_user_id=context.user_id,
    )
    db.add(rule)
    db.flush([rule])
    rule_triggers.set_event_types(db, rule=rule, event_types=normalised.event_types)
    versions.record(db, rule=rule, event_types=list(normalised.event_types), user_id=context.user_id,
                    note=rule_in.note or "Created the rule")
    _audit_rule(
        db, context=context, rule=rule, action=AuditAction.CREATED,
        details={"triggers": normalised.trigger_keys, "actions": [a["action_type"] for a in normalised.actions]},
    )
    db.commit()
    db.refresh(rule)
    logger.info(f"User {context.user_id} created Automation Rule '{rule.name}' [ID: {rule.id}] in workspace {context.workspace_id}")
    return _view(db, rule)


@router.get(
    "/rules", 
    response_model=list[AutomationRuleResponse],
    summary="List all Automation Rules",
    response_description="A paginated list of active and inactive Automation Rules."
)
def list_rules(
    db: Session = Depends(deps.get_db),
    context: deps.TenantContext = Depends(deps.RequireWorkspaceContributor),
    skip: int = Query(0, ge=0, description="The number of rules to skip for pagination."),
    limit: int = Query(100, ge=1, le=100, description="The maximum number of rules to return.")
) -> Any:
    from app.services.automation import flow_service, rule_triggers

    rules = crud.list_automation_rules(db, workspace_id=context.workspace_id, skip=skip, limit=limit)
    events = rule_triggers.event_types_of(db, rule_ids=[r.id for r in rules])
    paused = _workspace_paused(db, context.workspace_id)
    versions = _latest_versions(db, [r.id for r in rules])
    return [
        flow_service.rule_view(r, events.get(r.id, []), paused=paused, version=versions.get(r.id, 0)) for r in rules
    ]


# ---------------------------------------------------------------------------
# L-1 helpers. Mapping an ARCH-13 DAG execution onto the V1 log shape the
# frontend still consumes.
# ---------------------------------------------------------------------------

#: Only SUCCEEDED is a success. BUDGET_EXHAUSTED and TIMED_OUT are failures
#: from the operator's point of view even though the engine handled them
#: cleanly, and the suppressed states mean the work never ran.
_SUCCESS_STATUSES = frozenset({AutomationExecutionStatus.COMPLETED})


def _legacy_status(status: AutomationExecutionStatus) -> str:
    """Collapse seven execution statuses into the frontend's two-value union.

    types/automation.ts declares status as "SUCCESS" | "FAILED". Emitting a
    raw AutomationExecutionStatus would put values into that field the union
    does not admit. The unmapped value travels in execution_status instead.
    """
    if status in SKIPPED_STATUSES:
        return "SKIPPED"
    return "SUCCESS" if status in _SUCCESS_STATUSES else "FAILED"


def _duration_ms(execution: AutomationExecution) -> Optional[int]:
    """Wall clock, or None while the execution is still open.

    Returns None rather than 0 for an unfinished execution: zero would render
    as an instantaneous run, which is a different and wrong claim.
    """
    if execution.started_at is None or execution.completed_at is None:
        return None
    delta = execution.completed_at - execution.started_at
    return max(0, int(delta.total_seconds() * 1000))


def _action_summary(execution: AutomationExecution) -> str:
    """What this execution did, for the V1 action_type column.

    A V1 rule had exactly one action, so action_type was a single verb. A DAG
    has many. Reporting the first node's type would misdescribe a fifteen-node
    workflow as if it did one thing, so this reports the count instead and
    leaves the per-node breakdown to the Execution Timeline.
    """
    actions = int(execution.actions_executed or 0)
    if actions == 0:
        return "no actions"
    if actions == 1:
        return "1 action"
    return f"{actions} actions"


@router.get(
    "/logs",
    response_model=list[AutomationLogResponse],
    summary="List Automation Execution Logs",
    response_description="Execution history for all automation rules.",
)
def list_rule_logs(
    db: Session = Depends(deps.get_db),
    context: deps.TenantContext = Depends(deps.RequireWorkspaceContributor),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=100),
) -> list[AutomationLogResponse]:
    # L-1. Reads automation_executions, not automation_logs.
    #
    # automation_logs is written ONLY by automation_service.py, the V1 rule
    # engine. The live path is handlers/automation.py -> executor.run_execution,
    # which writes automation_executions and has never touched the log table.
    # That is why a working automation that delivers email left this panel
    # showing zero.
    #
    # Filtered to executions that have a work item: this panel is a document
    # audit trail, and the frontend type declares work_item_id and
    # document_name non-null. Manual and system executions surface in the
    # Execution Timeline, which has its own endpoint and its own type.
    rows = db.execute(
        select(AutomationExecution, AutomationRule.name, WorkItem.original_filename)
        .join(AutomationRule, AutomationExecution.rule_id == AutomationRule.id)
        .join(WorkItem, AutomationExecution.work_item_id == WorkItem.id)
        .where(AutomationExecution.workspace_id == context.workspace_id)
        .order_by(AutomationExecution.created_at.desc(), AutomationExecution.id.desc())
        .offset(skip)
        .limit(limit)
    ).all()

    response: list[AutomationLogResponse] = []

    for execution, rule_name, filename in rows:
        response.append(
            AutomationLogResponse(
                id=execution.id,
                rule_id=execution.rule_id,
                work_item_id=execution.work_item_id,
                rule_name=rule_name,
                document_name=filename,
                action_type=_action_summary(execution),
                status=_legacy_status(execution.status),
                log_message=execution.error,
                execution_status=execution.status.value,
                execution_time_ms=_duration_ms(execution),
                spent_cost_micros=execution.spent_cost_micros,
                nodes_executed=execution.nodes_executed,
                actions_executed=execution.actions_executed,
                created_at=execution.created_at,
                updated_at=execution.updated_at,
            )
        )

    logger.info(
        "Returned %d automation logs for workspace %s.",
        len(response),
        context.workspace_id,
    )

    return response


@router.get(
    "/rules/{rule_id}", 
    response_model=AutomationRuleResponse,
    summary="Get an Automation Rule by ID",
    response_description="The details of the requested Automation Rule."
)
def get_rule(
    rule_id: uuid.UUID,
    db: Session = Depends(deps.get_db),
    context: deps.TenantContext = Depends(deps.RequireWorkspaceContributor)
) -> Any:
    rule = crud.get_rule_by_id(db, workspace_id=context.workspace_id, rule_id=rule_id)
    if rule is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Automation rule not found or you do not have permission to access it."
        )
    return _view(db, rule)


@router.patch(
    "/rules/{rule_id}", 
    response_model=AutomationRuleResponse,
    summary="Update an Automation Rule",
    response_description="The updated Automation Rule."
)
def update_rule(
    rule_id: uuid.UUID,
    rule_in: AutomationRuleUpdate,
    db: Session = Depends(deps.get_db),
    context: deps.TenantContext = Depends(deps.RequireWorkspaceAdmin)
) -> Any:
    rule = crud.get_rule_by_id(db, workspace_id=context.workspace_id, rule_id=rule_id)
    if rule is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Automation rule not found or you do not have permission to access it."
        )
    
    # ARCH37-S1:flow-update. A partial update is merged into the stored rule
    # and the WHOLE result is validated, so a toggle cannot re-enable a rule
    # whose actions the tenant's plan no longer includes... except that a
    # pure enable/disable/rename is always allowed: turning a rule OFF must
    # never be refused.
    from app.models.audit_log import AuditAction
    from app.services.automation import catalog_service, flow_service, rule_triggers, versions

    changes = rule_in.model_dump(exclude_unset=True, mode="json")
    if changes != {"is_active": False}:
        _require_automations(db, context, "automation.rule.update")
    structural = set(changes) - {"is_active", "name", "priority", "max_runs_per_hour", "cooldown_hours", "note"}
    enabling = changes.get("is_active") is True and not rule.is_active

    if structural or enabling:
        events = rule_triggers.event_types_of(db, rule_ids=[rule.id]).get(rule.id, [])
        merged = flow_service.payload_from_rule(rule, events)
        flow_keys = {"triggers", "condition_groups", "groups_operator", "else_actions"}
        if flow_keys & set(changes) and "triggers" not in merged:
            # Upgrading an ARCH-13 rule to the flow shape.
            merged = {
                "triggers": changes.get("triggers") or [],
                "condition_groups": [
                    {"logic_operator": rule.logic_operator, "conditions": list(rule.conditions or [])}
                ],
                "actions": list(rule.actions or []),
                "on_error": rule.on_error,
            }
        for key in ("event", "conditions", "logic_operator", "actions", "on_error", *flow_keys):
            if key in changes and changes[key] is not None:
                merged[key] = changes[key]
        try:
            normalised = flow_service.normalise(
                merged, catalog_service.authoring_for(db, context=context), check_options=bool(structural)
            )
        except flow_service.FlowValidationError as exc:
            raise _flow_issues(exc) from exc
        if structural:
            rule.event = normalised.event
            rule.conditions = normalised.conditions
            rule.logic_operator = normalised.logic_operator
            rule.actions = normalised.actions
            rule.on_error = normalised.on_error
            rule.flow_spec = normalised.flow_spec
            rule_triggers.set_event_types(db, rule=rule, event_types=normalised.event_types)

    for key in ("name", "priority", "is_active"):
        if key in changes and changes[key] is not None:
            setattr(rule, key, changes[key])
    # Session J: a limit can be cleared (back to the default / off) by sending null.
    for key in ("max_runs_per_hour", "cooldown_hours"):
        if key in changes:
            setattr(rule, key, changes[key])
            if key == "max_runs_per_hour":
                rule.throttle_notified_at = None
    db.flush([rule])
    versions.record(
        db, rule=rule,
        event_types=rule_triggers.event_types_of(db, rule_ids=[rule.id]).get(rule.id, []),
        user_id=context.user_id, note=rule_in.note,
    )

    action = AuditAction.UPDATED
    if set(changes) == {"is_active"}:
        action = AuditAction.ENABLED if changes["is_active"] else AuditAction.DISABLED
    _audit_rule(db, context=context, rule=rule, action=action, details={"fields": sorted(changes)})
    db.commit()
    db.refresh(rule)
    logger.info(f"User {context.user_id} updated Automation Rule [ID: {rule_id}] inside workspace {context.workspace_id}")
    return _view(db, rule)


@router.delete(
    "/rules/{rule_id}", 
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an Automation Rule",
    response_description="Empty response indicating successful deletion."
)
def delete_rule(
    rule_id: uuid.UUID,
    db: Session = Depends(deps.get_db),
    context: deps.TenantContext = Depends(deps.RequireWorkspaceAdmin)
) -> Response:
    rule = crud.get_rule_by_id(db, workspace_id=context.workspace_id, rule_id=rule_id)
    if rule is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Automation rule not found or you do not have permission to access it."
        )
    
    from app.models.audit_log import AuditAction

    _audit_rule(db, context=context, rule=rule, action=AuditAction.DELETED, details={})
    crud.delete_automation_rule(db, db_obj=rule)
    logger.info(f"User {context.user_id} deleted Automation Rule [ID: {rule_id}] in workspace {context.workspace_id}")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/rules/{rule_id}/test",
    response_model=AutomationRuleTestResponse,
    summary="Test an Automation Rule against a Work Item",
    response_description="Detailed results of the test match evaluation."
)
def test_rule(
    rule_id: uuid.UUID,
    payload: AutomationRuleTestRequest,
    db: Session = Depends(deps.get_db),
    context: deps.TenantContext = Depends(deps.RequireWorkspaceAdmin)
) -> Any:
    rule = crud.get_rule_by_id(db, workspace_id=context.workspace_id, rule_id=rule_id)
    if rule is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Automation rule not found or you do not have permission to access it."
        )
    _require_automations(db, context, "automation.rule.test")

    work_item = crud.get_work_item(
        db,
        workspace_id=context.workspace_id,
        work_item_id=payload.work_item_id,
    )
    
    if work_item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Work item not found or you do not have permission to access it."
        )

    # F-218. A plain `def`, so the lookups, the dry run and the email settings
    # (all blocking database work) run in the threadpool, not on the event loop.
    # The test itself is a coroutine (it may send a labelled test email, through
    # a provider that already sends from a thread); it runs to completion on
    # this worker thread's own loop.
    return asyncio.run(
        automation_service.test_rule_for_work_item(db, rule=rule, work_item=work_item)
    )

# ==========================================================================
# Session J — run a rule by hand on one document
# ==========================================================================


class ManualRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    work_item_id: uuid.UUID


@router.post(
    "/rules/{rule_id}/run",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Run a rule by hand on one document",
    response_description="The run is queued; it appears in Run history within seconds.",
)
def run_rule_by_hand(
    rule_id: uuid.UUID,
    payload: ManualRunRequest,
    db: Session = Depends(deps.get_db),
    context: deps.TenantContext = Depends(deps.RequireWorkspaceAdmin),
) -> dict[str, Any]:
    """The manual trigger. A workspace admin presses "Run a rule on this document"; the rule runs on that document as if
    its trigger had just fired. The rule must have the "Run by hand" trigger and be switched on. Audited."""
    from app.models.audit_log import AuditAction
    from app.models.workspace import Workspace
    from app.services.automation import emitters, rule_triggers

    _require_automations(db, context, "automation.rule.run")
    rule = crud.get_rule_by_id(db, workspace_id=context.workspace_id, rule_id=rule_id)
    if rule is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Automation rule not found or you do not have permission to access it.")
    if emitters.MANUAL not in rule_triggers.event_types_of(db, rule_ids=[rule.id]).get(rule.id, []):
        raise HTTPException(status.HTTP_409_CONFLICT, "This rule is not set to run by hand. Give it the 'Run by hand on one document' trigger.")
    if not rule.is_active:
        raise HTTPException(status.HTTP_409_CONFLICT, "Switch the rule on before running it.")
    work_item = crud.get_work_item(db, workspace_id=context.workspace_id, work_item_id=payload.work_item_id)
    if work_item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Work item not found or you do not have permission to access it.")
    workspace = db.get(Workspace, context.workspace_id)
    event = emitters.manual(db, workspace=workspace, work_item_id=work_item.id, rule_id=rule.id)
    if event is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "The run could not be queued. Check that the rule is on and try again.")
    _audit_rule(db, context=context, rule=rule, action=AuditAction.EXECUTED,
                details={"manual_run": True, "work_item_id": str(work_item.id)})
    db.commit()
    return {"queued": True, "event_id": str(event.id), "rule_id": str(rule.id), "work_item_id": str(work_item.id)}


# ==========================================================================
# Session J, Phase 4 — safe at volume: pause, retry, versions
# ==========================================================================


class PauseRequest(BaseModel):
    paused: bool


@router.get(
    "/pause",
    summary="Are this workspace's automations paused?",
)
def get_pause(
    db: Session = Depends(deps.get_db),
    context: deps.TenantContext = Depends(deps.RequireWorkspaceContributor),
) -> dict[str, Any]:
    from app.models.workspace import Workspace

    workspace = db.get(Workspace, context.workspace_id)
    paused_at = getattr(workspace, "automations_paused_at", None)
    return {
        "paused": paused_at is not None,
        "paused_at": paused_at,
        "paused_by_user_id": getattr(workspace, "automations_paused_by_user_id", None),
    }


@router.put(
    "/pause",
    summary="Pause or resume every automation in this workspace",
    response_description="The new state. Runs that arrive while paused are listed in Run history as Skipped.",
)
def set_pause(
    body: PauseRequest,
    db: Session = Depends(deps.get_db),
    context: deps.TenantContext = Depends(deps.RequireWorkspaceAdmin),
) -> dict[str, Any]:
    """The big red switch. Pausing never needs the plan's automations (turning things off is always allowed)."""
    from datetime import timezone

    from app.models.audit_log import AuditAction, AuditOutcome, AuditResourceType
    from app.models.workspace import Workspace
    from app.services import audit_service

    workspace = db.get(Workspace, context.workspace_id)
    if workspace is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace not found.")
    already = workspace.automations_paused_at is not None
    if body.paused != already:
        workspace.automations_paused_at = datetime.now(timezone.utc) if body.paused else None
        workspace.automations_paused_by_user_id = context.user_id if body.paused else None
        audit_service.record(
            db,
            organization_id=context.organization_id,
            workspace_id=context.workspace_id,
            actor_id=context.user_id,
            resource_type=AuditResourceType.WORKSPACE,
            resource_id=context.workspace_id,
            action=AuditAction.DISABLED if body.paused else AuditAction.ENABLED,
            outcome=AuditOutcome.ALLOWED,
            details={"automations": "paused" if body.paused else "resumed"},
        )
        db.commit()
        db.refresh(workspace)
    return {
        "paused": workspace.automations_paused_at is not None,
        "paused_at": workspace.automations_paused_at,
        "paused_by_user_id": workspace.automations_paused_by_user_id,
    }


class RetryRequest(BaseModel):
    #: The person has read "This may send the message again" and still wants the retry.
    acknowledge_repeat: bool = False


@router.post(
    "/executions/{execution_id}/retry",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Run a failed run again",
    response_description="A new run is queued; the failed one stays in Run history as it was.",
)
def retry_execution(
    execution_id: uuid.UUID,
    body: RetryRequest,
    db: Session = Depends(deps.get_db),
    context: deps.TenantContext = Depends(deps.RequireWorkspaceAdmin),
) -> dict[str, Any]:
    """Runs the whole rule again from the start, on the same document. When a step would repeat something a person
    notices (an email, a chat message) the first call is refused with 409 and the steps named; the same call with
    `acknowledge_repeat` true goes ahead. Audited."""
    from app.models.audit_log import AuditAction
    from app.services import job_service, outbox_service
    from app.services.automation import executor, volume

    _require_automations(db, context, "automation.execution.retry")
    execution = db.execute(
        select(AutomationExecution).where(
            AutomationExecution.id == execution_id, AutomationExecution.workspace_id == context.workspace_id
        )
    ).scalar_one_or_none()
    if execution is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run not found or you do not have permission to access it.")
    rule = crud.get_rule_by_id(db, workspace_id=context.workspace_id, rule_id=execution.rule_id)
    blocker = volume.retry_blocker(db, execution, rule)
    if blocker:
        raise HTTPException(status.HTTP_409_CONFLICT, blocker)
    if _workspace_paused(db, context.workspace_id):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This workspace's automations are paused. Resume them before retrying a run.",
        )
    repeats = volume.repeatable_actions(rule)
    if repeats and not body.acknowledge_repeat:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={
                "code": "may_repeat",
                "message": "This may send the message again: " + ", ".join(repeats)
                + ". Retry only if you are sure it did not go out the first time.",
                "actions": repeats,
            },
        )

    retry, _ = executor.create_execution(
        db,
        rule=rule,
        organization_id=context.organization_id,
        workspace_id=context.workspace_id,
        work_item_id=execution.work_item_id,
        retry_of_id=execution.id,
    )
    outbox_service._ensure_automation_handler()
    job_service.enqueue(
        db,
        job_type=outbox_service.AUTOMATION_JOB_TYPE,
        organization_id=context.organization_id,
        payload={"retry_execution_id": str(retry.id)},
        idempotency_key=f"automation:retry:{retry.id}",
    )
    _audit_rule(db, context=context, rule=rule, action=AuditAction.EXECUTED,
                details={"retry_of": str(execution.id), "execution_id": str(retry.id)})
    db.commit()
    return {"queued": True, "execution_id": str(retry.id), "retry_of": str(execution.id), "rule_id": str(rule.id)}


def _user_names(db: Session, user_ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    from app.models.user import User

    if not user_ids:
        return {}
    rows = db.execute(select(User.id, User.display_name, User.email).where(User.id.in_(user_ids))).all()
    return {row.id: (row.display_name or row.email) for row in rows}


@router.get(
    "/rules/{rule_id}/versions",
    summary="A rule's history, newest first, with what changed in plain words",
)
def list_rule_versions(
    rule_id: uuid.UUID,
    db: Session = Depends(deps.get_db),
    context: deps.TenantContext = Depends(deps.RequireWorkspaceContributor),
    skip: int = Query(0, ge=0, le=MAX_OFFSET),
    limit: int = Query(50, ge=1, le=100),
) -> dict[str, Any]:
    from app.services.automation import versions

    rule = crud.get_rule_by_id(db, workspace_id=context.workspace_id, rule_id=rule_id)
    if rule is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Automation rule not found or you do not have permission to access it.")
    rows, total = versions.history(db, rule_id=rule.id, limit=limit, offset=skip)
    names = _user_names(db, {r.created_by_user_id for r in rows if r.created_by_user_id})
    return {
        "total": total,
        "items": [versions.view(r, versions.previous_of(db, r), names) for r in rows],
    }


@router.post(
    "/rules/{rule_id}/versions/{version}/restore",
    summary="Restore an earlier version of a rule (as a new version)",
)
def restore_rule_version(
    rule_id: uuid.UUID,
    version: int,
    db: Session = Depends(deps.get_db),
    context: deps.TenantContext = Depends(deps.RequireWorkspaceAdmin),
) -> dict[str, Any]:
    """Puts the rule back as it was in `version`. The old version is validated like any save (a step the plan no
    longer includes is refused with the usual 422). History is never rewritten: the restore is a new version."""
    from app.models.audit_log import AuditAction
    from app.models.automation import AutomationRuleVersion
    from app.services.automation import catalog_service, flow_service, rule_triggers, versions

    _require_automations(db, context, "automation.rule.restore")
    rule = crud.get_rule_by_id(db, workspace_id=context.workspace_id, rule_id=rule_id)
    if rule is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Automation rule not found or you do not have permission to access it.")
    row = db.execute(
        select(AutomationRuleVersion).where(
            AutomationRuleVersion.rule_id == rule.id, AutomationRuleVersion.version == version
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That version of the rule does not exist.")
    snap = dict(row.snapshot)
    payload = {k: v for k, v in snap.items() if k not in versions.SETTINGS_KEYS}
    try:
        normalised = flow_service.normalise(
            payload, catalog_service.authoring_for(db, context=context), check_options=False
        )
    except flow_service.FlowValidationError as exc:
        raise _flow_issues(exc) from exc
    rule.event = normalised.event
    rule.conditions = normalised.conditions
    rule.logic_operator = normalised.logic_operator
    rule.actions = normalised.actions
    rule.on_error = normalised.on_error
    rule.flow_spec = normalised.flow_spec
    rule_triggers.set_event_types(db, rule=rule, event_types=normalised.event_types)
    for key in ("name", "priority", "max_runs_per_hour", "cooldown_hours"):
        if key in snap:
            setattr(rule, key, snap[key])
    # A restore never switches a rule on by itself: the person decides that.
    db.flush([rule])
    created = versions.record(
        db, rule=rule, event_types=list(normalised.event_types), user_id=context.user_id,
        note=f"Restored version {version}", restored_from_version=version,
    )
    _audit_rule(db, context=context, rule=rule, action=AuditAction.RESTORED,
                details={"restored_version": version, "new_version": created.version if created else None})
    db.commit()
    db.refresh(rule)
    return _view(db, rule)


# ==========================================================================
# Session J, Phase 4 — preview on the last 30 days, and "why didn't my rule run?"
# ==========================================================================


@router.post(
    "/preview",
    summary="What would this rule have done on the last 30 days? (nothing is written or sent)",
)
def preview_draft(
    rule_in: AutomationRuleCreate,
    db: Session = Depends(deps.get_db),
    context: deps.TenantContext = Depends(deps.RequireWorkspaceAdmin),
) -> dict[str, Any]:
    """Replays the stored events and recent documents of the last 30 days through a rule that is not saved yet. The rule
    is validated like a save, so the same plain-words errors come back. Read-only: no run, notification or outbox row."""
    from app.services.automation import catalog_service, flow_service, preview

    _require_automations(db, context, "automation.rule.preview")
    try:
        normalised = flow_service.normalise(rule_in.model_dump(mode="json"), catalog_service.authoring_for(db, context=context))
    except flow_service.FlowValidationError as exc:
        raise _flow_issues(exc) from exc
    draft = preview.draft_rule(normalised, max_runs_per_hour=rule_in.max_runs_per_hour)
    return preview.preview(db, rule=draft, event_types=list(normalised.event_types), workspace_id=context.workspace_id)


@router.post(
    "/rules/{rule_id}/preview",
    summary="What would this saved rule have done on the last 30 days?",
)
def preview_rule(
    rule_id: uuid.UUID,
    db: Session = Depends(deps.get_db),
    context: deps.TenantContext = Depends(deps.RequireWorkspaceAdmin),
) -> dict[str, Any]:
    from app.services.automation import preview, rule_triggers

    _require_automations(db, context, "automation.rule.preview")
    rule = crud.get_rule_by_id(db, workspace_id=context.workspace_id, rule_id=rule_id)
    if rule is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Automation rule not found or you do not have permission to access it.")
    events = rule_triggers.event_types_of(db, rule_ids=[rule.id]).get(rule.id, [])
    return preview.preview(db, rule=rule, event_types=events, workspace_id=context.workspace_id)


@router.get(
    "/documents/{work_item_id}/explain",
    summary="Why did (or didn't) each rule run on this document?",
)
def explain_document(
    work_item_id: uuid.UUID,
    db: Session = Depends(deps.get_db),
    context: deps.TenantContext = Depends(deps.RequireWorkspaceContributor),
) -> dict[str, Any]:
    """Read-only. For each rule: whether its trigger fired for this document, which condition failed with what value, or
    why the run was held back. It uses the same evaluator the engine runs."""
    from app.services.automation import preview

    work_item = crud.get_work_item(db, workspace_id=context.workspace_id, work_item_id=work_item_id)
    if work_item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Work item not found or you do not have permission to access it.")
    return {
        "work_item_id": work_item_id,
        "rules": preview.explain_document(db, workspace_id=context.workspace_id, work_item=work_item),
    }
