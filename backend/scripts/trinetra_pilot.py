#!/usr/bin/env python3
"""TRINETRA pilot enrolment, from the server (Final session 2T, N-201).

    python scripts/trinetra_pilot.py list
    python scripts/trinetra_pilot.py enrol --organization <id or slug> --reason "Pilot with the owner's own Zoho; CA has read the wording"
    python scripts/trinetra_pilot.py withdraw --organization <id or slug> --reason "Pilot over; customer asked to stop"

The same thing the platform operator's console does (`/api/v1/admin/trinetra/pilot`), for the owner who is on the server and
has no API token at hand. In `TRINETRA_MODE=pilot` only an enrolled organization is live (and only if its plan includes
TRINETRA); in `on` every Business and Enterprise organization is live and enrolment changes nothing. Each change is audited on the
organization (ORGANIZATION / UPDATED `trinetra.pilot_enrolled` or `trinetra.pilot_withdrawn`, with the reason). Prints no secret and
makes no network call.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path
from typing import Any

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


def resolve_organization(db: Any, ref: str) -> uuid.UUID:
    from sqlalchemy import text

    try:
        return uuid.UUID(str(ref))
    except ValueError:
        row = db.execute(text("SELECT id FROM organizations WHERE slug = :s"), {"s": str(ref)}).first()
        if row is None:
            raise SystemExit(f"no organization with slug {ref!r}")
        return row[0]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="the mode and every enrolled organization")
    for name, help_text in (("enrol", "enrol an organization in the pilot"), ("withdraw", "take an organization out of the pilot")):
        step = sub.add_parser(name, help=help_text)
        step.add_argument("--organization", required=True)
        step.add_argument("--reason", required=True, help="at least 10 characters; kept in the audit log")
    args = parser.parse_args(argv)

    from app.db.session import SessionLocal
    from app.models.organization import Organization
    from app.models.trinetra import TrinetraPilot
    from app.services.trinetra import mode

    with SessionLocal() as db:
        if args.command == "list":
            rows = db.query(TrinetraPilot).order_by(TrinetraPilot.created_at).all()
            items = [{"organization_id": str(r.organization_id), "name": getattr(db.get(Organization, r.organization_id), "name", None),
                      "reason": r.reason, "enrolled_at": r.created_at.isoformat()} for r in rows]
            print(json.dumps({"mode": mode.deployment_mode(), "items": items}, indent=2))
            return 0
        reason = args.reason.strip()
        if len(reason) < 10:
            raise SystemExit("the reason must be at least 10 characters")
        organization_id = resolve_organization(db, args.organization)
        if db.get(Organization, organization_id) is None:
            raise SystemExit("organization not found")
        if args.command == "enrol":
            mode.enrol(db, organization_id=organization_id, actor_id=None, reason=reason)
            print(json.dumps({"organization_id": str(organization_id), "enrolled": True, "mode": mode.deployment_mode()}))
        else:
            removed = mode.withdraw(db, organization_id=organization_id, actor_id=None, reason=reason)
            print(json.dumps({"organization_id": str(organization_id), "withdrawn": removed}))
        db.commit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
