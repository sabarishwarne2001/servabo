"""Session G — the value receipt: what Servabo found in the organization's own documents, in its own money.

    GET /organizations/{oid}/value-receipt?period=trial|month      [owner, admin, billing]
    GET /organizations/{oid}/value-receipt.pdf?period=trial|month  the same receipt as a one-page PDF

Reads only. The receipt is kept in Redis for ten minutes per organization and period
(`app.services.value_receipt.cached`). It is not a list, so the offset rule does not apply. Members and
viewers get a 403: the figures are the organization's money, like the usage page.
"""

from __future__ import annotations

import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.api.deps import OrganizationContext, RequireOrgUsageReader, get_read_db
from app.services import value_receipt, value_receipt_pdf

router = APIRouter(tags=["Value receipt"])


@router.get("/organizations/{organization_id}/value-receipt", summary="What Servabo found, in your own money")
def get_value_receipt(
    organization_id: uuid.UUID,
    period: Literal["trial", "month"] = Query("trial", description="trial: the organization's trial window; month: this calendar month."),
    db: Session = Depends(get_read_db),
    context: OrganizationContext = Depends(RequireOrgUsageReader),
) -> dict[str, Any]:
    return value_receipt.cached(db, context.organization_id, period)


@router.get("/organizations/{organization_id}/value-receipt.pdf", summary="The value receipt as a one-page PDF")
def get_value_receipt_pdf(
    organization_id: uuid.UUID,
    period: Literal["trial", "month"] = Query("trial"),
    db: Session = Depends(get_read_db),
    context: OrganizationContext = Depends(RequireOrgUsageReader),
) -> Response:
    """The same figures as the screen (the kept copy, so the page and the PDF agree), for the same roles."""
    receipt = value_receipt.cached(db, context.organization_id, period)
    return Response(
        content=value_receipt_pdf.to_pdf(receipt), media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{value_receipt_pdf.filename(receipt, context.organization.slug)}"',
                 "Cache-Control": "private, no-store"})
