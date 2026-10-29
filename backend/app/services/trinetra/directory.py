"""The deductor directory (Final 2T, Phase 4): a customer's TAN mapped to the customer, once, reviewed by a person.

Only the TAN's keyed fingerprint and its masked form are stored. A mapping starts PROPOSED (seen on a document), becomes
CONFIRMED when a person confirms it, and goes FLAGGED when the same TAN is seen under a different customer: it is never merged
automatically, and a suggestion for a flagged TAN cannot be accepted until a person resolves it."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException

from app.models.trinetra import TrinetraDeductor as Deductor
from app.services.helm import identity as ident

SEEN_LIMIT = 10


def name_key(name: str) -> str:
    return ident.key_for(name) or f"name:{(name or '').strip().casefold()}"


def lookup(db, p, deductor_key):
    return db.query(Deductor).filter_by(profile_id=p.id, deductor_key=deductor_key).first()


def by_customer(db, p, name):
    """The CONFIRMED mapping whose customer is this name (name-normalized), or None."""
    if not name:
        return None
    return (
        db.query(Deductor)
        .filter_by(profile_id=p.id, counterparty_key=name_key(name), status="CONFIRMED")
        .first()
    )


def observe(db, workspace, p, deductor_key, tan_masked, name):
    """A TAN was seen under this customer name. Create the mapping, leave it be, or flag a second customer."""
    if not deductor_key or not name:
        return None
    key = name_key(name)
    row = lookup(db, p, deductor_key)
    if row is None:
        row = Deductor(
            organization_id=workspace.organization_id,
            workspace_id=workspace.id,
            profile_id=p.id,
            deductor_key=deductor_key,
            tan_masked=tan_masked,
            counterparty_key=key,
            counterparty_name=name[:120],
            status="PROPOSED",
        )
        db.add(row)
        db.flush()
        return row
    if row.counterparty_key != key:
        seen = list(row.seen_as or [])
        if name[:120] not in seen and len(seen) < SEEN_LIMIT:
            seen.append(name[:120])
        row.seen_as = seen
        row.status = "FLAGGED"
        row.updated_at = datetime.now(timezone.utc)
        db.flush()
    return row


def confirm(db, workspace, p, user_id, deductor_key, tan_masked, name, reason):
    """A person says which customer this TAN belongs to. Resolves a flag; the other names seen are kept in the history."""
    row = lookup(db, p, deductor_key)
    if row is None:
        row = Deductor(
            organization_id=workspace.organization_id,
            workspace_id=workspace.id,
            profile_id=p.id,
            deductor_key=deductor_key,
            tan_masked=tan_masked,
            counterparty_key=name_key(name),
            counterparty_name=name[:120],
        )
        db.add(row)
    row.counterparty_key, row.counterparty_name = name_key(name), name[:120]
    row.status, row.seen_as = "CONFIRMED", []
    row.reviewed_by, row.review_reason = user_id, reason
    row.updated_at = datetime.now(timezone.utc)
    db.flush()
    return row


def require_unflagged(row):
    if row is not None and row.status == "FLAGGED":
        raise HTTPException(
            409,
            {
                "code": "TRINETRA_DEDUCTOR_FLAGGED",
                "message": "This TAN has been seen under more than one customer name "
                f"({row.counterparty_name} and {', '.join(row.seen_as or [])}). Servabo never merges them on its own: "
                "confirm which customer the TAN belongs to in the deductor directory, then accept the suggestion.",
            },
        )


def view(row):
    return {
        "id": str(row.id),
        "profile_id": str(row.profile_id),
        "tan_masked": row.tan_masked,
        "counterparty": row.counterparty_name,
        "status": row.status,
        "seen_as": list(row.seen_as or []),
        "review_reason": row.review_reason,
        "updated_at": row.updated_at.isoformat(),
    }
