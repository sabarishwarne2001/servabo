"""The outcome ledger: "Recovered, verified", counted once (Final session 2A, Phase 6; N-191).

Recoveries writes an outcome only when evidence closed an issue (`adapters.Verdict.outcome`). Its `dedupe_key` is Helm's
own (`helm/value.dedupe_key`: the category and the document), so:

* an outcome Helm already recorded is not written again (`record` sees Helm's row and stops);
* an outcome Helm records later is still counted once: `rows` reads both ledgers and keeps Helm's row for a key both hold;
* a duplicate that was blocked is not also an overcharge recovered: the whole invoice was not paid, so the overcharge on
  it is part of what the duplicate's figure already counts (`rows` drops the overcharge for that document).

An outcome whose evidence is undone (the duplicate was paid after all, the payment record was undone, the GSTR-2B that
carried the invoice was removed) is withdrawn (`withdraw`), never deleted, so the audit trail keeps what was claimed.
Amounts in different currencies are never added.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Iterable, Optional

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.helm import HelmBook, HelmValueEvent
from app.models.recovery import RecoveryIssue, RecoveryOutcome
from app.services.helm import value as helm_value
from app.services.helm import vocabulary as helm_v
from app.services.recoveries import vocabulary as v
from app.services.recoveries.adapters import Outcome


def dedupe_key(category: str, work_item_id: Any, issue_id: Any) -> str:
    """Helm's key when the outcome is about a document (so the two ledgers agree); the issue's own otherwise."""
    return helm_value.dedupe_key(category, work_item_id if work_item_id else f"issue:{issue_id}")


def record(db: Session, issue: RecoveryIssue, outcome: Outcome) -> Optional[str]:
    """Write the outcome once. Returns "HELM" when Helm already holds it, "RECOVERIES" when written, None when it was
    already written (and is restored if it had been withdrawn). Flushes."""
    key = dedupe_key(outcome.category, outcome.work_item_id, issue.id)
    if db.execute(select(HelmValueEvent.id).where(HelmValueEvent.dedupe_key == key)).first():
        return "HELM"
    result = db.execute(pg_insert(RecoveryOutcome).values(
        id=uuid.uuid4(), organization_id=issue.organization_id, workspace_id=issue.workspace_id, issue_id=issue.id,
        work_item_id=outcome.work_item_id, category=outcome.category, dedupe_key=key, currency=outcome.currency,
        amount_micros=int(outcome.amount_micros), occurred_on=outcome.occurred_on, evidence=outcome.evidence,
    ).on_conflict_do_nothing(constraint="uq_recovery_outcomes_dedupe_key"))
    if result.rowcount:
        db.flush()
        return "RECOVERIES"
    db.execute(update(RecoveryOutcome).where(RecoveryOutcome.dedupe_key == key, RecoveryOutcome.withdrawn_at.is_not(None))
               .values(withdrawn_at=None))
    db.flush()
    return None


def withdraw(db: Session, issue_id: uuid.UUID) -> int:
    """Take the issue's outcomes off the count (their evidence was undone). Returns how many. Flushes."""
    result = db.execute(update(RecoveryOutcome).where(RecoveryOutcome.issue_id == issue_id,
                                                      RecoveryOutcome.withdrawn_at.is_(None))
                        .values(withdrawn_at=datetime.now(timezone.utc)))
    db.flush()
    return int(result.rowcount or 0)


@dataclass(frozen=True)
class Row:
    dedupe_key: str
    category: str
    workspace_id: Optional[uuid.UUID]
    work_item_id: Optional[uuid.UUID]
    currency: str
    amount_micros: int
    occurred_on: date
    source: str          # HELM or RECOVERIES
    issue_id: Optional[uuid.UUID] = None


def rows(db: Session, workspace_ids: Iterable[uuid.UUID], *, first: Optional[date] = None,
         last: Optional[date] = None) -> list[Row]:
    """Every outcome of Recoveries' categories in these workspaces, each counted once (see the module's rules)."""
    ids = list(workspace_ids)
    if not ids:
        return []
    helm_q = (select(HelmValueEvent).join(HelmBook, HelmBook.id == HelmValueEvent.book_id)
              .where(HelmValueEvent.workspace_id.in_(ids), HelmValueEvent.category.in_(v.CATEGORIES),
                     HelmBook.kind != helm_v.BOOK_SAMPLE))
    own_q = select(RecoveryOutcome).where(RecoveryOutcome.workspace_id.in_(ids), RecoveryOutcome.withdrawn_at.is_(None))
    if first:
        helm_q = helm_q.where(HelmValueEvent.occurred_on >= first)
        own_q = own_q.where(RecoveryOutcome.occurred_on >= first)
    if last:
        helm_q = helm_q.where(HelmValueEvent.occurred_on <= last)
        own_q = own_q.where(RecoveryOutcome.occurred_on <= last)
    kept: dict[str, Row] = {}
    for e in db.execute(helm_q).scalars():
        kept[e.dedupe_key] = Row(e.dedupe_key, e.category, e.workspace_id, e.work_item_id, e.currency,
                                 int(e.amount_micros), e.occurred_on, "HELM")
    for o in db.execute(own_q).scalars():
        kept.setdefault(o.dedupe_key, Row(o.dedupe_key, o.category, o.workspace_id, o.work_item_id, o.currency,
                                          int(o.amount_micros), o.occurred_on, "RECOVERIES", o.issue_id))
    blocked = {r.work_item_id for r in kept.values() if r.category == v.DUPLICATE_BLOCKED and r.work_item_id}
    return [r for r in kept.values()
            if not (r.category == v.OVERCHARGE_RECOVERED and r.work_item_id in blocked)]


def totals(found: Iterable[Row]) -> dict[str, int]:
    out: dict[str, int] = {}
    for r in found:
        out[r.currency] = out.get(r.currency, 0) + r.amount_micros
    return out


def for_issue(db: Session, issue: RecoveryIssue) -> list[Row]:
    """The counted outcomes that closed this issue (its own, or Helm's for the same document)."""
    if issue.work_item_id is None:
        return [r for r in rows(db, [issue.workspace_id]) if r.issue_id == issue.id]
    return [r for r in rows(db, [issue.workspace_id])
            if r.issue_id == issue.id or (r.work_item_id == issue.work_item_id and r.source == "HELM"
                                          and r.category in CATEGORY_OF_KIND.get(issue.kind, ()))]


CATEGORY_OF_KIND: dict[str, tuple[str, ...]] = {
    v.GST_CREDIT: (v.ITC_SECURED,),
    v.DUPLICATE: (v.DUPLICATE_BLOCKED,),
    v.OVERCHARGE: (v.OVERCHARGE_RECOVERED,),
    v.PAYMENT_DEADLINE: (v.LATE_FEE_AVOIDED,),
    v.STATEMENT_DIFFERENCE: (),
}

__all__ = ["CATEGORY_OF_KIND", "Row", "dedupe_key", "for_issue", "record", "rows", "totals", "withdraw"]
