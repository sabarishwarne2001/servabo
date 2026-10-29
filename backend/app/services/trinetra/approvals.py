"""Approval chains for closing cases (Final 2T, Phase 6; N-207), Enterprise.

Helm's approval pattern: a policy says what needs a second person. Here: closing a case worth at least the threshold, in one of
the listed ways (posted and accountant-reviewed, explained, unresolved), needs the approval of a named role, by a DIFFERENT
person than the one who asked. The approval is valid only for the revision it was asked on: if the case moved underneath, it
goes STALE and is asked again. Business has no policy and keeps the simple rule. A pending request changes nothing by itself."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException

from app.api.capability_gate import has_capability
from app.models.organization import OrganizationMember, OrganizationRole
from app.models.trinetra import TrinetraApproval as Approval
from app.models.trinetra import TrinetraPolicy as Policy

CLOSING = ("CA_REVIEWED", "EXPLAINED", "UNRESOLVED")
ROLE_RANK = {"ADMIN": 1, "OWNER": 2}


def policy_for(db, organization_id):
    """The organization's policy, only where the plan has approval chains (Enterprise)."""
    if not has_capability(db, organization_id=organization_id, capability_key="capability.trinetra_all_workspaces"):
        return None
    return db.get(Policy, organization_id)


def save_policy(db, organization_id, user_id, *, threshold_micros, actions, approver_role):
    if not has_capability(db, organization_id=organization_id, capability_key="capability.trinetra_all_workspaces"):
        raise HTTPException(402, "Approval chains are part of the Enterprise plan.")
    bad = [a for a in actions if a not in CLOSING]
    if bad or not actions:
        raise HTTPException(422, "Choose which closures need approval: " + ", ".join(CLOSING) + ".")
    row = db.get(Policy, organization_id)
    if row is None:
        row = Policy(organization_id=organization_id)
        db.add(row)
    row.threshold_micros, row.actions, row.approver_role = threshold_micros, sorted(set(actions)), approver_role
    row.updated_by, row.updated_at = user_id, datetime.now(timezone.utc)
    db.flush()
    return row


def view_policy(row):
    return None if row is None else {
        "threshold_micros": str(row.threshold_micros), "actions": list(row.actions or []), "approver_role": row.approver_role,
        "updated_at": row.updated_at.isoformat(),
        "note": "Closing a case worth at least the threshold, in these ways, needs the named role's approval by a different person.",
    }


def required(db, workspace, case, action):
    """The policy that applies to this closure, or None (the simple rule)."""
    if action not in CLOSING:
        return None
    policy = policy_for(db, workspace.organization_id)
    if policy is None or action not in (policy.actions or []):
        return None
    if (case.expected_micros or 0) < policy.threshold_micros:
        return None
    return policy


class ApprovalNeeded(Exception):
    """The closure needs a second person's approval under the organization's policy; carries that policy."""

    def __init__(self, policy):
        super().__init__("approval required")
        self.policy = policy


def request(db, workspace, case, user_id, action, reason, policy):
    """Ask for the approval. It is recorded in the case history on a new revision, and is valid for exactly that revision."""
    from app.models.trinetra import TrinetraDecision as Decision
    from app.services.trinetra import service

    pending = db.query(Approval).filter_by(credit_id=case.id, status="PENDING").first()
    if pending is not None:
        raise HTTPException(409, "An approval is already waiting for this case.")
    case.revision += 1
    db.add(Decision(
        organization_id=workspace.organization_id, workspace_id=workspace.id, credit_id=case.id, actor_id=user_id,
        revision=case.revision, action="APPROVAL_REQUESTED",
        reason=f"Approval asked for closing as {action}: {reason}", allocations=service.carry(db, case),
        evidence_work_item_ids=case.evidence_work_item_ids or [],
    ))
    row = Approval(
        organization_id=workspace.organization_id, workspace_id=workspace.id, credit_id=case.id, action=action,
        reason=reason, amount_micros=case.expected_micros or 0, case_revision=case.revision,
        approver_role=policy.approver_role, requested_by=user_id, status="PENDING",
    )
    db.add(row)
    db.flush()
    return row


def view(row):
    return {
        "id": str(row.id), "credit_id": str(row.credit_id), "action": row.action, "reason": row.reason,
        "amount_micros": str(row.amount_micros), "case_revision": row.case_revision, "approver_role": row.approver_role,
        "requested_by": str(row.requested_by) if row.requested_by else None, "status": row.status,
        "decided_by": str(row.decided_by) if row.decided_by else None, "decided_reason": row.decided_reason,
        "decided_at": row.decided_at.isoformat() if row.decided_at else None, "created_at": row.created_at.isoformat(),
    }


def holds_role(db, organization_id, user_id, needed):
    """Does this person hold the named role in the organization? OWNER needs the owner; ADMIN accepts an admin or the owner."""
    member = db.query(OrganizationMember).filter_by(organization_id=organization_id, user_id=user_id).first()
    if member is None:
        return False
    rank = {OrganizationRole.OWNER: 2, OrganizationRole.ADMIN: 1}.get(member.role, 0)
    return rank >= ROLE_RANK[needed]


def check_can_decide(db, workspace, row, user_id):
    if row.status != "PENDING":
        raise HTTPException(409, "This approval was already decided.")
    if row.requested_by == user_id:
        raise HTTPException(409, "A different person must decide: the one who asked cannot approve their own closure.")
    if not holds_role(db, workspace.organization_id, user_id, row.approver_role):
        raise HTTPException(403, f"Only an organization {row.approver_role.lower()} can decide this approval.")


def mark_stale(row, reason="The case changed after this approval was asked for."):
    row.status, row.decided_reason, row.decided_at = "STALE", reason, datetime.now(timezone.utc)
