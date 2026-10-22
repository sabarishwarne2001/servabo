"""Tally Prime, guided (Final session 1, 3C): four answers instead of a mapping editor.

A customer who keeps books in Tally Prime does not want to learn mappings. They tell us the company as it is spelled in Tally and the
names of five ledgers they already have (the purchase ledger and Input CGST, SGST, IGST and a plain input-tax ledger). We make a DOWNLOAD
target in Tally's own format with the shipped mapping, and write those five names into the target's `accounts` table. Each bill then
becomes one balanced Purchase voucher: the supplier credited with the total, the purchase ledger debited, and the tax debited to
Input CGST and Input SGST (same state) or Input IGST (another state). The customer downloads the file and imports it in Tally Prime.

The target is an ordinary one: every setting the guided form fills can be changed afterwards on the ERP targets page.
"""

from __future__ import annotations

import uuid
from typing import Any, Mapping, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.erp import ErpLookupTable, ErpTarget
from app.services.erp import presets as PR
from app.services.erp import service
from app.services.erp import vocabulary as v

LEDGERS = (("default", "purchases", "Purchase Accounts"), ("CGST", "cgst", "Input CGST"), ("SGST", "sgst", "Input SGST"),
           ("IGST", "igst", "Input IGST"), ("TAX", "tax", "Input Tax"))


def setup(db: Session, *, organization_id: uuid.UUID, workspace_id: uuid.UUID, actor_user_id: uuid.UUID, company: str,
          ledgers: Optional[Mapping[str, str]] = None, name: str = "Tally Prime") -> ErpTarget:
    company = " ".join(str(company or "").split())
    if not company:
        raise service.ErpError("INVALID", "Tell us the company exactly as it is spelled in Tally Prime.")
    given = {k: " ".join(str(val or "").split()) for k, val in (ledgers or {}).items()}
    entries = {key: given.get(field) or fallback for key, field, fallback in LEDGERS}
    too_long = [field for _key, field, _fb in LEDGERS if len(given.get(field, "")) > 100]
    if too_long:
        raise service.ErpError("INVALID", f"ledger names are at most 100 characters ({', '.join(too_long)})")
    target = service.create_target(
        db, organization_id=organization_id, workspace_id=workspace_id, actor_user_id=actor_user_id, name=name,
        format=v.FORMAT_TALLY, transport=v.TRANSPORT_DOWNLOAD, preset=v.PRESET_NONE, ack_mode=v.ACK_MANUAL, auth_mode=v.AUTH_NONE,
        config={"tally": {"company": company}, "guided": "tally"}, check_network=False)
    table = db.execute(select(ErpLookupTable).where(
        ErpLookupTable.workspace_id == workspace_id, ErpLookupTable.name == PR.table_names(target.config["lookup_prefix"])["accounts"])
    ).scalar_one()
    service.update_lookup(db, table=table, actor_user_id=actor_user_id, entries=entries)
    return target


def guide(target: ErpTarget) -> dict[str, Any]:
    return {"company": ((target.config or {}).get("tally") or {}).get("company")}


__all__ = ["LEDGERS", "setup"]
