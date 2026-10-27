"""Final session 2A (Phase 6; N-191) — Recoveries: money issues from Found to Being fixed to Verified.

    GET  /workspaces/{wid}/recoveries                          [VIEWER]       the issues, counts, found, recovered (a preview
                                                                              of counts and found on a plan without it)
    GET  /workspaces/{wid}/recoveries/{issue_id}               [VIEWER]       one issue with its evidence and outcomes
    POST /workspaces/{wid}/recoveries/check                    [CONTRIBUTOR]  re-read every engine now (statements too)
    PUT  /workspaces/{wid}/recoveries/{issue_id}/owner         [CONTRIBUTOR]  set or clear the owner (a workspace member)
    PUT  /workspaces/{wid}/recoveries/{issue_id}/due-date      [CONTRIBUTOR]  only where the law and the terms give none
    POST /workspaces/{wid}/recoveries/{issue_id}/not-money     [CONTRIBUTOR]  close as "Not money: <reason>" (never counted)
    POST /workspaces/{wid}/recoveries/{issue_id}/reopen        [CONTRIBUTOR]  undo a "Not money"

Opening the list brings the issues up to date with the engines that are cheap to read (`service.sweep`); the supplier
statements are re-read by the hourly `recoveries.sweep` job and by "Check now". No route here moves money, approves,
pays or releases a hold: an issue's next actions are links to the engines' own pages.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api import capability_gate
from app.api.deps import RequireWorkspaceRole, TenantContext, get_db
from app.core import entitlements
from app.models.recovery import RecoveryIssue
from app.models.workspace import Workspace, WorkspaceRole
from app.services.recoveries import ledger, service
from app.services.recoveries import vocabulary as v

router = APIRouter(tags=["Recoveries"])

RequireViewer = RequireWorkspaceRole(WorkspaceRole.VIEWER)
RequireContributor = RequireWorkspaceRole(WorkspaceRole.CONTRIBUTOR)

StateName = Literal["FOUND", "BEING_FIXED", "VERIFIED", "NOT_MONEY", "CLOSED"]
KindName = Literal["GST_CREDIT", "DUPLICATE", "OVERCHARGE", "STATEMENT_DIFFERENCE", "PAYMENT_DEADLINE"]


class RecoveryNextAction(BaseModel):
    key: str
    label: str
    #: "workspace": a path under the workspace (/{org}/{workspace}/<path>); "helm": under Helm (/{org}/helm/<path>).
    scope: Literal["workspace", "helm"]
    path: str


class RecoveryOutcomeOut(BaseModel):
    category: str
    currency: str
    amount_micros: int
    occurred_on: date
    counted_by: Literal["HELM", "RECOVERIES"]


class RecoveryIssueOut(BaseModel):
    id: uuid.UUID
    kind: KindName
    kind_label: str
    state: StateName
    title: str
    work_item_id: Optional[uuid.UUID] = None
    document: Optional[str] = None
    currency: Optional[str] = None
    exposure_micros: Optional[int] = None
    found_exposure_micros: Optional[int] = None
    due_date: Optional[date] = None
    due_basis: Optional[str] = None
    due_set_by_person: bool = False
    owner_user_id: Optional[uuid.UUID] = None
    owner_email: Optional[str] = None
    close_reason: Optional[str] = None
    first_found_at: datetime
    verified_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None
    version: int
    details: dict[str, Any]
    evidence: dict[str, Any]
    next_actions: list[RecoveryNextAction]
    outcomes: list[RecoveryOutcomeOut] = Field(default_factory=list)


class RecoveryAmount(BaseModel):
    currency: str
    amount_micros: int


class RecoveryNeedsOwner(BaseModel):
    count: int
    amounts: list[RecoveryAmount]


class RecoveriesSummary(BaseModel):
    counts: dict[str, int]
    found: list[RecoveryAmount]
    needs_owner: RecoveryNeedsOwner
    recovered_verified: list[RecoveryAmount]
    recovered_count: int


class RecoveriesOut(BaseModel):
    #: False on a plan without Recoveries: `summary` is then a preview (counts and found only) and `items` is empty.
    included: bool
    summary: RecoveriesSummary
    items: list[RecoveryIssueOut]
    kind_labels: dict[str, str]


class RecoveryOwnerRequest(BaseModel):
    owner_user_id: Optional[uuid.UUID] = None
    version: Optional[int] = None


class RecoveryDueDateRequest(BaseModel):
    due_date: Optional[date] = None
    version: Optional[int] = None


class RecoveryNotMoneyRequest(BaseModel):
    reason: str = Field(min_length=v.MIN_REASON, max_length=2000)
    version: Optional[int] = None


class RecoveryVersionRequest(BaseModel):
    version: Optional[int] = None


class RecoveryCheckOut(BaseModel):
    found: int
    verified: int
    not_money: int
    closed: int
    reopened: int


def _amounts(by_currency: dict[str, int]) -> list[RecoveryAmount]:
    return [RecoveryAmount(currency=c, amount_micros=int(a)) for c, a in sorted(by_currency.items()) if a]


def _summary(raw: dict[str, Any]) -> RecoveriesSummary:
    return RecoveriesSummary(
        counts=raw["counts"], found=_amounts(raw["found"]),
        needs_owner=RecoveryNeedsOwner(count=raw["needs_owner"]["count"], amounts=_amounts(raw["needs_owner"]["amounts"])),
        recovered_verified=_amounts(raw["recovered_verified"]), recovered_count=raw["recovered_count"])


def _workspace(db: Session, context: TenantContext, workspace_id: uuid.UUID) -> Workspace:
    if context.workspace_id != workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace not found.")
    workspace = db.get(Workspace, workspace_id)
    if workspace is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace not found.")
    return workspace


def _require(db: Session, context: TenantContext, operation: str) -> None:
    capability_gate.require_capability(db, context=context, capability_key=entitlements.RECOVERIES_CAPABILITY,
                                       operation=operation)


def _next_actions(issue: RecoveryIssue) -> list[RecoveryNextAction]:
    details = issue.details or {}
    document = details.get("work_item_id")
    out: list[RecoveryNextAction] = []
    if issue.kind == v.GST_CREDIT:
        out.append(RecoveryNextAction(key="gst", label="Remind the supplier on the GST page", scope="workspace", path="gst"))
    elif issue.kind == v.DUPLICATE:
        out.append(RecoveryNextAction(key="radar", label="Confirm or dismiss on the radar", scope="workspace", path="radar"))
        out.append(RecoveryNextAction(key="helm_plan", label="Hold the payment in Helm (a person decides)", scope="helm", path="plan"))
    elif issue.kind == v.OVERCHARGE:
        if details.get("case_id"):
            out.append(RecoveryNextAction(key="case", label="Open the order match and dispute it", scope="workspace",
                                  path=f"procurement/{details['case_id']}"))
        out.append(RecoveryNextAction(key="helm_plan", label="Hold the payment in Helm (a person decides)", scope="helm", path="plan"))
    elif issue.kind == v.STATEMENT_DIFFERENCE:
        out.append(RecoveryNextAction(key="helm_plan", label="Review Helm's drafted email to the supplier", scope="helm", path="plan"))
    elif issue.kind == v.PAYMENT_DEADLINE:
        out.append(RecoveryNextAction(key="helm_plan", label="Plan the payment in Helm (a person approves)", scope="helm", path="plan"))
    if document:
        out.append(RecoveryNextAction(key="document", label="Open the document", scope="workspace", path=f"work-items/{document}"))
    return out


def _out(db: Session, issue: RecoveryIssue, emails: dict[uuid.UUID, str], *, outcomes: bool = False) -> RecoveryIssueOut:
    details = dict(issue.details or {})
    return RecoveryIssueOut(
        id=issue.id, kind=issue.kind, kind_label=v.KIND_LABELS[issue.kind], state=issue.state, title=issue.title,
        work_item_id=issue.work_item_id, document=details.get("document"), currency=issue.currency,
        exposure_micros=issue.exposure_micros, found_exposure_micros=issue.found_exposure_micros,
        due_date=issue.due_date, due_basis=issue.due_basis, due_set_by_person=issue.due_basis == "Set by a person",
        owner_user_id=issue.owner_user_id, owner_email=emails.get(issue.owner_user_id) if issue.owner_user_id else None,
        close_reason=issue.close_reason, first_found_at=issue.first_found_at, verified_at=issue.verified_at,
        closed_at=issue.closed_at, version=issue.version, details=details, evidence=dict(issue.evidence or {}),
        next_actions=_next_actions(issue),
        outcomes=[RecoveryOutcomeOut(category=r.category, currency=r.currency, amount_micros=r.amount_micros,
                             occurred_on=r.occurred_on, counted_by=r.source)
                  for r in ledger.for_issue(db, issue)] if outcomes else [])


def _load(db: Session, workspace_id: uuid.UUID, issue_id: uuid.UUID) -> RecoveryIssue:
    try:
        return service.get(db, workspace_id, issue_id)
    except LookupError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Issue not found.") from None


def _one(db: Session, issue: RecoveryIssue) -> RecoveryIssueOut:
    return _out(db, issue, service.owners(db, [issue.owner_user_id] if issue.owner_user_id else []), outcomes=True)


@router.get("/workspaces/{workspace_id}/recoveries", response_model=RecoveriesOut,
            summary="Money issues from found to verified, with what was recovered")
def list_recoveries(
    workspace_id: uuid.UUID,
    state: Optional[StateName] = Query(None),
    kind: Optional[KindName] = Query(None),
    db: Session = Depends(get_db),
    context: TenantContext = Depends(RequireViewer),
) -> RecoveriesOut:
    workspace = _workspace(db, context, workspace_id)
    if not service.entitled(db, workspace.organization_id):
        return RecoveriesOut(included=False, summary=_summary(service.preview(db, workspace)), items=[],
                             kind_labels=dict(v.KIND_LABELS))
    service.sweep(db, workspace)
    db.commit()
    items = service.list_issues(db, workspace.id, state=state, kind=kind)
    emails = service.owners(db, [i.owner_user_id for i in items if i.owner_user_id])
    return RecoveriesOut(included=True, summary=_summary(service.summary(db, workspace)),
                         items=[_out(db, i, emails) for i in items], kind_labels=dict(v.KIND_LABELS))


@router.post("/workspaces/{workspace_id}/recoveries/check", response_model=RecoveryCheckOut,
             summary="Re-read every engine now, supplier statements included")
def check_recoveries(
    workspace_id: uuid.UUID,
    db: Session = Depends(get_db),
    context: TenantContext = Depends(RequireContributor),
) -> RecoveryCheckOut:
    workspace = _workspace(db, context, workspace_id)
    _require(db, context, "recoveries.check")
    counts = service.sweep(db, workspace, heavy=True)
    db.commit()
    return RecoveryCheckOut(**{k: counts.get(k, 0) for k in ("found", "verified", "not_money", "closed", "reopened")})


@router.get("/workspaces/{workspace_id}/recoveries/{issue_id}", response_model=RecoveryIssueOut)
def get_recovery(
    workspace_id: uuid.UUID,
    issue_id: uuid.UUID,
    db: Session = Depends(get_db),
    context: TenantContext = Depends(RequireViewer),
) -> RecoveryIssueOut:
    _workspace(db, context, workspace_id)
    _require(db, context, "recoveries.get")
    return _one(db, _load(db, workspace_id, issue_id))


def _act(db: Session, context: TenantContext, workspace_id: uuid.UUID, issue_id: uuid.UUID, operation: str, fn) -> RecoveryIssueOut:
    _workspace(db, context, workspace_id)
    _require(db, context, operation)
    issue = _load(db, workspace_id, issue_id)
    try:
        fn(issue)
    except service.RecoveryError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    db.commit()
    db.refresh(issue)
    return _one(db, issue)


@router.put("/workspaces/{workspace_id}/recoveries/{issue_id}/owner", response_model=RecoveryIssueOut)
def set_recovery_owner(
    workspace_id: uuid.UUID, issue_id: uuid.UUID, body: RecoveryOwnerRequest,
    db: Session = Depends(get_db), context: TenantContext = Depends(RequireContributor),
) -> RecoveryIssueOut:
    return _act(db, context, workspace_id, issue_id, "recoveries.owner",
                lambda issue: service.assign(db, issue, owner_user_id=body.owner_user_id, actor_id=context.user_id,
                                             version=body.version))


@router.put("/workspaces/{workspace_id}/recoveries/{issue_id}/due-date", response_model=RecoveryIssueOut)
def set_recovery_due_date(
    workspace_id: uuid.UUID, issue_id: uuid.UUID, body: RecoveryDueDateRequest,
    db: Session = Depends(get_db), context: TenantContext = Depends(RequireContributor),
) -> RecoveryIssueOut:
    return _act(db, context, workspace_id, issue_id, "recoveries.due_date",
                lambda issue: service.set_due_date(db, issue, due_date=body.due_date, actor_id=context.user_id,
                                                   version=body.version))


@router.post("/workspaces/{workspace_id}/recoveries/{issue_id}/not-money", response_model=RecoveryIssueOut)
def close_recovery_not_money(
    workspace_id: uuid.UUID, issue_id: uuid.UUID, body: RecoveryNotMoneyRequest,
    db: Session = Depends(get_db), context: TenantContext = Depends(RequireContributor),
) -> RecoveryIssueOut:
    return _act(db, context, workspace_id, issue_id, "recoveries.not_money",
                lambda issue: service.close_not_money(db, issue, reason=body.reason, actor_id=context.user_id,
                                                      version=body.version))


@router.post("/workspaces/{workspace_id}/recoveries/{issue_id}/reopen", response_model=RecoveryIssueOut)
def reopen_recovery(
    workspace_id: uuid.UUID, issue_id: uuid.UUID, body: RecoveryVersionRequest,
    db: Session = Depends(get_db), context: TenantContext = Depends(RequireContributor),
) -> RecoveryIssueOut:
    return _act(db, context, workspace_id, issue_id, "recoveries.reopen",
                lambda issue: service.reopen(db, issue, actor_id=context.user_id, version=body.version))
