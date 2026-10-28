"""Recoveries: money issues from Found to Being fixed to Verified (Final session 2A, Phase 6; N-191).

    sweep(db, workspace)              bring the issues up to date with the engines (observe, then judge); idempotent
    summary(db, workspace)            counts, what was found, what needs an owner, what was recovered and verified
    preview(db, workspace)            the same counts and "found" for a plan without Recoveries, written nowhere
    assign / set_due_date / close_not_money / reopen     a person's actions, each audited

The engines hold the facts; this module holds an issue's state (`recovery_issues`) and the outcomes evidence proved
(`ledger`). The workspace predicate is applied in `_issues`, once; every read goes through it.

Rules that are the feature:

* An issue is Verified only by evidence (`adapters`, one rule per kind). A person's click never verifies.
* "Not money: <reason>" is a person's decision (or the engine's own dismissal), recorded and never counted.
* "Found" and "Recovered, verified" are never added together; amounts in different currencies are never added.
* Nothing here moves money, approves, pays or releases a hold (Phase 3 invariant (a)): the next actions are the
  engines' own pages.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import entitlements
from app.models.audit_log import AuditAction, AuditOutcome, AuditResourceType
from app.models.recovery import RecoveryIssue
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.services import audit_service
from app.services.recoveries import ledger
from app.services.recoveries import vocabulary as v
from app.services.recoveries.adapters import ADAPTERS, Adapter, BY_KIND, Observation

#: Keys kept from when the issue was first found (a later sighting must not overwrite them).
_KEPT_DETAILS = ("invoice_total_micros",)
_PERSON_DUE = "Set by a person"


class RecoveryError(ValueError):
    """A person's action that cannot be done (the message is shown as is)."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def entitled(db: Session, organization_id: uuid.UUID) -> bool:
    from app.api import capability_gate

    return capability_gate.has_capability(db, organization_id=organization_id,
                                          capability_key=entitlements.RECOVERIES_CAPABILITY)


def _adapters(db: Session, organization_id: uuid.UUID, *, heavy: bool) -> list[Adapter]:
    from app.api import capability_gate

    out = []
    for adapter in ADAPTERS:
        if adapter.heavy and not heavy:
            continue
        if adapter.capability and not capability_gate.has_capability(db, organization_id=organization_id,
                                                                     capability_key=adapter.capability):
            continue
        live = getattr(adapter, "live", None)       # an engine that is also gated by a mode (TRINETRA: off, pilot, on)
        if live is not None and not live(db, organization_id):
            continue
        out.append(adapter)
    return out


def _issues(db: Session, workspace_id: uuid.UUID, *, kind: Optional[str] = None,
            states: Optional[Sequence[str]] = None) -> list[RecoveryIssue]:
    """THE workspace predicate: every read of `recovery_issues` in this module goes through here."""
    stmt = select(RecoveryIssue).where(RecoveryIssue.workspace_id == workspace_id)
    if kind:
        stmt = stmt.where(RecoveryIssue.kind == kind)
    if states:
        stmt = stmt.where(RecoveryIssue.state.in_(list(states)))
    return list(db.execute(stmt.order_by(RecoveryIssue.first_found_at, RecoveryIssue.id)).scalars())


def get(db: Session, workspace_id: uuid.UUID, issue_id: uuid.UUID) -> RecoveryIssue:
    issue = db.execute(select(RecoveryIssue).where(RecoveryIssue.workspace_id == workspace_id,
                                                   RecoveryIssue.id == issue_id)).scalar_one_or_none()
    if issue is None:
        raise LookupError("issue")
    return issue


# ---------------------------------------------------------------------------------------------------------- the sweep


def _open_state(issue: RecoveryIssue, in_progress: bool) -> str:
    return v.BEING_FIXED if (issue.owner_user_id or in_progress) else v.FOUND


def _apply_observation(db: Session, workspace: Workspace, found: dict[str, RecoveryIssue], ob: Observation,
                       now: datetime) -> int:
    issue = found.get(ob.subject_key)
    if issue is None:  # kept in `found`: a second observation of one subject updates it, never inserts twice
        issue = found[ob.subject_key] = RecoveryIssue(
            id=uuid.uuid4(), organization_id=workspace.organization_id, workspace_id=workspace.id, kind=ob.kind,
            subject_key=ob.subject_key, work_item_id=ob.work_item_id,
            state=v.BEING_FIXED if ob.in_progress else v.FOUND, title=ob.title, currency=ob.currency,
            exposure_micros=ob.exposure_micros, found_exposure_micros=ob.exposure_micros, due_date=ob.due_date,
            due_basis=ob.due_basis, details={**ob.details, "in_progress": ob.in_progress}, evidence={},
            first_found_at=now, last_seen_at=now)
        db.add(issue)
        return 1
    issue.last_seen_at = now
    if issue.state in v.OPEN_STATES or issue.state == v.CLOSED:
        kept = {k: (issue.details or {}).get(k) for k in _KEPT_DETAILS if (issue.details or {}).get(k) is not None}
        issue.title, issue.currency, issue.exposure_micros = ob.title, ob.currency, ob.exposure_micros
        issue.details = {**ob.details, **kept, "in_progress": ob.in_progress}
        if issue.found_exposure_micros is None:
            issue.found_exposure_micros = ob.exposure_micros
        if issue.due_basis != _PERSON_DUE or ob.due_date:
            issue.due_date, issue.due_basis = ob.due_date, ob.due_basis
        if issue.state == v.CLOSED:  # the engine reports it again
            issue.closed_at, issue.close_reason = None, None
        issue.state = _open_state(issue, ob.in_progress)
    return 0


def _apply_verdict(db: Session, issue: RecoveryIssue, verdict: Any, now: datetime) -> str:
    if verdict.state == v.BEING_FIXED:  # reopened: the evidence was undone
        ledger.withdraw(db, issue.id)
        issue.state = _open_state(issue, False)
        issue.verified_at = None
        issue.close_reason = None
        issue.evidence = {"reopened": verdict.reason, "reopened_at": now.isoformat(), **verdict.evidence}
        return "reopened"
    issue.state = verdict.state
    issue.close_reason = verdict.reason
    issue.evidence = dict(verdict.evidence)
    if verdict.state == v.VERIFIED:
        issue.verified_at = now
        if verdict.outcome is not None:
            counted_by = ledger.record(db, issue, verdict.outcome)
            issue.evidence = {**issue.evidence, "outcome": verdict.outcome.category,
                              "counted_by": counted_by or "RECOVERIES"}
        return "verified"
    issue.closed_at = now
    return verdict.state.lower()


def sweep(db: Session, workspace: Workspace, *, today: Optional[date] = None, heavy: bool = False) -> dict[str, int]:
    """Bring the workspace's issues up to date with the engines. Idempotent. Flushes; the caller commits."""
    now = _now()
    day = today or now.date()
    counts = {"found": 0, "verified": 0, "not_money": 0, "closed": 0, "reopened": 0}
    for adapter in _adapters(db, workspace.organization_id, heavy=heavy):
        known = {i.subject_key: i for i in _issues(db, workspace.id, kind=adapter.kind)}
        for ob in adapter.observe(db, workspace, day):
            counts["found"] += _apply_observation(db, workspace, known, ob, now)
        db.flush()
        judged = _issues(db, workspace.id, kind=adapter.kind, states=(*v.OPEN_STATES, v.VERIFIED))
        for verdict in adapter.judge(db, workspace, judged, day):
            issue = next(i for i in judged if i.id == verdict.issue_id)
            outcome = _apply_verdict(db, issue, verdict, now)
            counts[outcome] = counts.get(outcome, 0) + 1
        db.flush()
    return counts


# ---------------------------------------------------------------------------------------------------------- reading


def _sum(rows: Sequence[RecoveryIssue], attr: str = "exposure_micros") -> dict[str, int]:
    out: dict[str, int] = {}
    for issue in rows:
        amount = getattr(issue, attr)
        if issue.currency and amount:
            out[issue.currency] = out.get(issue.currency, 0) + int(amount)
    return out


def summary(db: Session, workspace: Workspace) -> dict[str, Any]:
    issues = _issues(db, workspace.id)
    open_issues = [i for i in issues if i.state in v.OPEN_STATES]
    needs_owner = [i for i in open_issues if i.owner_user_id is None]
    counted = ledger.rows(db, [workspace.id])
    return {
        "counts": {state: sum(1 for i in issues if i.state == state) for state in v.STATES},
        "found": _sum(open_issues),
        "needs_owner": {"count": len(needs_owner), "amounts": _sum(needs_owner)},
        "recovered_verified": ledger.totals(counted),
        "recovered_count": len(counted),
    }


def preview(db: Session, workspace: Workspace) -> dict[str, Any]:
    """For a plan without Recoveries: what the engines it has report now, as counts and "found". Written nowhere."""
    day = _now().date()
    found: list[Observation] = []
    for adapter in _adapters(db, workspace.organization_id, heavy=False):
        found += adapter.observe(db, workspace, day)
    amounts: dict[str, int] = {}
    for ob in found:
        if ob.currency and ob.exposure_micros:
            amounts[ob.currency] = amounts.get(ob.currency, 0) + int(ob.exposure_micros)
    counts = {state: 0 for state in v.STATES}
    counts[v.FOUND] = len(found)
    return {"counts": counts, "found": amounts, "needs_owner": {"count": len(found), "amounts": amounts},
            "recovered_verified": {}, "recovered_count": 0}


def list_issues(db: Session, workspace_id: uuid.UUID, *, state: Optional[str] = None,
                kind: Optional[str] = None) -> list[RecoveryIssue]:
    return _issues(db, workspace_id, kind=kind, states=(state,) if state else None)


def owners(db: Session, ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not ids:
        return {}
    return dict(db.execute(select(User.id, User.email).where(User.id.in_(list(set(ids))))).all())


# ---------------------------------------------------------------------------------------------------------- a person's actions


def _audit(db: Session, issue: RecoveryIssue, actor_id: uuid.UUID, change: str, **details: Any) -> None:
    audit_service.record(
        db, organization_id=issue.organization_id, workspace_id=issue.workspace_id, actor_id=actor_id,
        resource_type=AuditResourceType.REVIEW_ITEM, resource_id=issue.id, action=AuditAction.UPDATED,
        outcome=AuditOutcome.ALLOWED,
        details={"review_kind": "RECOVERY", "recovery_kind": issue.kind, "change": change, "state": issue.state,
                 **{k: (str(val) if isinstance(val, (uuid.UUID, date)) else val) for k, val in details.items()}})


def _check_version(issue: RecoveryIssue, version: Optional[int]) -> None:
    if version is not None and version != issue.version:
        raise RecoveryError("Someone else changed this issue. Reload it and try again.")


def _can_reach(db: Session, issue: RecoveryIssue, user_id: uuid.UUID) -> bool:
    """Whether the person can open this workspace: an explicit grant, or an organization owner or admin (a derived
    workspace admin, with no membership row; `workspace_permissions` is the single authority)."""
    from app.core.workspace_permissions import has_workspace_access
    from app.models.organization import MembershipStatus, OrganizationMember

    org_role = db.execute(select(OrganizationMember.role).where(
        OrganizationMember.organization_id == issue.organization_id, OrganizationMember.user_id == user_id,
        OrganizationMember.status == MembershipStatus.ACTIVE)).scalar_one_or_none()
    ws_role = db.execute(select(WorkspaceMember.role).where(WorkspaceMember.workspace_id == issue.workspace_id,
                                                            WorkspaceMember.user_id == user_id)).scalar_one_or_none()
    return has_workspace_access(org_role, ws_role)


def assign(db: Session, issue: RecoveryIssue, *, owner_user_id: Optional[uuid.UUID], actor_id: uuid.UUID,
           version: Optional[int] = None) -> RecoveryIssue:
    _check_version(issue, version)
    if issue.state not in v.OPEN_STATES:
        raise RecoveryError("Only an open issue can be given an owner.")
    if owner_user_id is not None and not _can_reach(db, issue, owner_user_id):
        raise RecoveryError("The owner must be a member of this workspace.")
    issue.owner_user_id = owner_user_id
    issue.assigned_at = _now() if owner_user_id else None
    if issue.state == v.FOUND and owner_user_id:
        issue.state = v.BEING_FIXED
    elif issue.state == v.BEING_FIXED and not owner_user_id and not (issue.details or {}).get("in_progress"):
        issue.state = v.FOUND
    issue.version += 1
    _audit(db, issue, actor_id, "owner", owner_user_id=owner_user_id)
    db.flush()
    return issue


def set_due_date(db: Session, issue: RecoveryIssue, *, due_date: Optional[date], actor_id: uuid.UUID,
                 version: Optional[int] = None) -> RecoveryIssue:
    """A person sets a due date only where the law and the terms give none (a statement difference, a duplicate with
    no payment term). A date from the law or the terms is never overwritten."""
    _check_version(issue, version)
    if issue.state not in v.OPEN_STATES:
        raise RecoveryError("Only an open issue can be given a due date.")
    if issue.due_date and issue.due_basis != _PERSON_DUE:
        raise RecoveryError(f"This issue's due date comes from the {issue.due_basis or 'terms'} and cannot be changed.")
    issue.due_date = due_date
    issue.due_basis = _PERSON_DUE if due_date else None
    issue.version += 1
    _audit(db, issue, actor_id, "due_date", due_date=due_date)
    db.flush()
    return issue


def close_not_money(db: Session, issue: RecoveryIssue, *, reason: str, actor_id: uuid.UUID,
                    version: Optional[int] = None) -> RecoveryIssue:
    """A person decides the issue is not money (for a statement difference: explained). Recorded; never counted."""
    _check_version(issue, version)
    reason = (reason or "").strip()
    if len(reason) < v.MIN_REASON:
        raise RecoveryError(f"Give a reason of at least {v.MIN_REASON} characters.")
    if issue.state not in v.OPEN_STATES:
        raise RecoveryError("Only an open issue can be closed.")
    word = "Explained" if issue.kind == v.STATEMENT_DIFFERENCE else "Not money"
    issue.state, issue.close_reason = v.NOT_MONEY, f"{word}: {reason}"
    issue.closed_at, issue.closed_by_user_id = _now(), actor_id
    issue.version += 1
    _audit(db, issue, actor_id, "not_money", reason=reason)
    db.flush()
    return issue


def reopen(db: Session, issue: RecoveryIssue, *, actor_id: uuid.UUID, version: Optional[int] = None) -> RecoveryIssue:
    """Undo a person's "Not money". Verified and closed issues follow the evidence, not a click."""
    _check_version(issue, version)
    if issue.state != v.NOT_MONEY:
        raise RecoveryError("Only an issue closed as not money can be reopened.")
    issue.closed_at, issue.closed_by_user_id, issue.close_reason = None, None, None
    issue.state = _open_state(issue, False)
    issue.version += 1
    _audit(db, issue, actor_id, "reopen")
    db.flush()
    return issue


def needs_owner(db: Session, organization_id: uuid.UUID) -> Optional[dict[str, Any]]:
    """For the GST digest (N-191): the open issues nobody owns across the organization's own workspaces, in rupees.
    {"count", "amount_micros", "workspace_slug"} (the workspace with the most), or None when there are none or the plan
    does not include Recoveries. Reads the issues the hourly sweep keeps; writes nothing."""
    from sqlalchemy import func

    from app.models.workspace import WorkspaceStatus

    if not entitled(db, organization_id):
        return None
    rows = db.execute(
        select(Workspace.slug, func.count(), func.coalesce(func.sum(RecoveryIssue.exposure_micros).filter(
            RecoveryIssue.currency == "INR"), 0))
        .join(Workspace, Workspace.id == RecoveryIssue.workspace_id)
        .where(RecoveryIssue.organization_id == organization_id, RecoveryIssue.state.in_(v.OPEN_STATES),
               RecoveryIssue.kind != v.TDS_CREDIT,       # a possible tax-statement gap is never one of the "money issues"
               RecoveryIssue.owner_user_id.is_(None), Workspace.is_sample.is_(False),
               Workspace.status == WorkspaceStatus.ACTIVE)
        .group_by(Workspace.slug).order_by(func.count().desc(), Workspace.slug)).all()
    if not rows:
        return None
    return {"count": sum(int(n) for _, n, _ in rows), "amount_micros": sum(int(a) for _, _, a in rows),
            "workspace_slug": rows[0][0]}


def adapter_for(kind: str) -> Adapter:
    return BY_KIND[kind]


__all__ = ["RecoveryError", "adapter_for", "assign", "close_not_money", "entitled", "get", "list_issues", "needs_owner", "owners",
           "preview", "reopen", "set_due_date", "summary", "sweep"]
