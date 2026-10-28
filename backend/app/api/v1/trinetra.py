"""TRINETRA workspace API. Official imports and live access remain release gated."""

import uuid
from datetime import date
from typing import Literal, Annotated
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field, AfterValidator, BeforeValidator
from sqlalchemy.orm import Session
from app.api.deps import (
    RequireWorkspaceRole,
    TenantContext,
    get_db,
    OrganizationContext,
    RequireOrgRole,
)
from app.models.organization import OrganizationRole
from app.api import capability_gate
from app.core.config import settings
from app.models.workspace import Workspace, WorkspaceRole
from app.models.trinetra import (
    TrinetraProfile as Profile,
    TrinetraCredit as Credit,
    TrinetraDecision as Decision,
)
from app.services.trinetra import service as s, domain as d, mode
from app.services.trinetra.events import reviewed as announce_review
from app.services.trinetra.schemas import (
    AccessOut,
    SummaryOut,
    ProfilesOut,
    ProfileOut,
    StatementOut,
    CasesOut,
    CaseOut,
    DetailOut,
    DraftOut,
    PreviewOut,
    RunOut,
    RunStatusOut,
    OrganizationAccessOut,
    OrganizationSummaryOut,
)


def _money(value: str) -> str:
    d.money(value)
    return value


Money = Annotated[str, AfterValidator(_money)]


def _pan(value):
    """Upper case, no spaces or hyphens; anything else is left for the pattern to refuse (a 422)."""
    from app.services.trinetra.seller import normalize_pan

    return (normalize_pan(value) or value) if isinstance(value, str) else value


Pan = Annotated[str, BeforeValidator(_pan), Field(pattern=r"^[A-Z]{5}[0-9]{4}[A-Z]$", max_length=10)]


def no_cache(response: Response):
    response.headers["Cache-Control"] = "no-store"


router = APIRouter(tags=["TRINETRA"], dependencies=[Depends(no_cache)])
P = "/workspaces/{workspace_id}/trinetra"
Read = RequireWorkspaceRole(WorkspaceRole.VIEWER)
Write = RequireWorkspaceRole(WorkspaceRole.ADMIN)


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ProfileIn(Strict):
    name: str = Field(min_length=1, max_length=120)
    pan: Pan


class LineIn(Strict):
    tan: str = Field(pattern=r"^[A-Z]{4}[0-9]{5}[A-Z]$")
    amount: Money
    reference: str = Field(min_length=1, max_length=100)


class ImportIn(Strict):
    profile_id: uuid.UUID
    source_work_item_id: uuid.UUID
    source_version: str | None = Field(default=None, max_length=60)
    year: int = Field(ge=2000, le=2100)
    pan: Pan
    confirmed: bool
    rows: list[LineIn] = Field(min_length=1, max_length=500)


class CreditIn(Strict):
    profile_id: uuid.UUID
    work_item_id: uuid.UUID
    year: int = Field(ge=2000, le=2100)
    counterparty: str = Field(min_length=1, max_length=120)
    reference: str = Field(min_length=1, max_length=100)
    tan: str = Field(pattern=r"^[A-Z]{4}[0-9]{5}[A-Z]$")
    amount: Money
    source_confirmation: str = Field(min_length=10, max_length=1000)
    seller_name_confirmed: bool = False


class AllocationIn(Strict):
    snapshot_id: uuid.UUID
    line_id: str = Field(pattern=r"^\d{1,3}$")
    amount: Money


class DecisionIn(Strict):
    revision: int = Field(ge=1)
    action: Literal[
        "ALLOCATE", "DISPUTED", "EXPLAINED", "WITHDRAWN", "CA_REVIEWED", "REOPEN"
    ]
    reason: str = Field(min_length=10, max_length=1000)
    allocations: list[AllocationIn] = Field(default_factory=list, max_length=100)
    review_minutes: int = Field(default=0, ge=0, le=480, strict=True)


class ReconfirmIn(Strict):
    seller_name_confirmed: bool = False
    revision: int = Field(ge=1)
    amount: Money
    reason: str = Field(min_length=10, max_length=1000)


class EvidenceIn(Strict):
    work_item_id: uuid.UUID
    kind: Literal[
        "DEDUCTOR_ADVICE", "ACCOUNTING_RECORD", "CERTIFICATE", "CORRECTION_RESPONSE"
    ]
    amount: Money | None = None


class ReviewIn(Strict):
    revision: int = Field(ge=1)
    assign_to_me: bool = False
    priority: Literal["NORMAL", "HIGH", "URGENT"] = "NORMAL"
    due_on: date | None = None
    root_cause: str = Field(default="", max_length=300)
    reason: str = Field(min_length=10, max_length=1000)
    evidence: list[EvidenceIn] = Field(default_factory=list, max_length=20)
    confirm_receivable: bool = False


def require_source_validation(db, organization_id):
    """The launch gate: the deployment's mode (off, pilot, on) decides, through the one helper."""
    mode.require_mode(db, organization_id)


def workspace(db, context, wid, *, live=True):
    w = db.get(Workspace, wid)
    if (
        not w
        or context.workspace_id != wid
        or w.organization_id != context.organization_id
    ):
        raise HTTPException(404, "Workspace not found.")
    if live:
        from app.workers.tenant_gate import inactive_reason, unpaid_reason

        if inactive_reason(db, organization_id=w.organization_id, workspace_id=w.id):
            raise HTTPException(404, "Workspace not available.")
        if unpaid_reason(db, organization_id=w.organization_id):
            raise HTTPException(
                402, "An active subscription is required for live processing."
            )
        capability_gate.require_capability(
            db,
            context=context,
            capability_key="capability.trinetra",
            operation="trinetra",
        )
        if w.is_sample:
            raise HTTPException(409, "Synthetic examples are read-only.")
        require_source_validation(db, w.organization_id)
    return w


@router.get(P + "/access", response_model=AccessOut)
def access(
    workspace_id: uuid.UUID,
    db: Session = Depends(get_db),
    context: TenantContext = Depends(Read),
):
    workspace(db, context, workspace_id, live=False)
    live = mode.state(db, context.organization_id)
    return {
        "live_enabled": live.live,
        "mode": live.mode,
        "enrolled": live.enrolled,
        "enrolled_since": live.enrolled_since.isoformat() if live.enrolled_since else None,
        "entitled": live.entitled,
        "official_formats": [],
        "transcription_format": "human-transcription-v1",
        "tcs_supported": False,
    }


@router.get(P + "/sample", response_model=SummaryOut)
def sample(
    workspace_id: uuid.UUID,
    db: Session = Depends(get_db),
    context: TenantContext = Depends(Read),
):
    workspace(db, context, workspace_id, live=False)
    from app.services.trinetra.sample import cockpit

    return cockpit()


@router.post(P + "/profiles", response_model=ProfileOut)
def create_profile(
    workspace_id: uuid.UUID,
    body: ProfileIn,
    db: Session = Depends(get_db),
    context: TenantContext = Depends(Write),
):
    w = workspace(db, context, workspace_id)
    p = s.create_profile(db, w, body.name, body.pan)
    db.commit()
    return {"id": str(p.id), "name": p.name, "pan_masked": p.pan_masked}


@router.get(P + "/profiles", response_model=ProfilesOut)
def profiles(
    workspace_id: uuid.UUID,
    db: Session = Depends(get_db),
    context: TenantContext = Depends(Read),
):
    workspace(db, context, workspace_id)
    return {
        "items": [
            {"id": str(p.id), "name": p.name, "pan_masked": p.pan_masked}
            for p in db.query(Profile).filter_by(workspace_id=workspace_id).limit(20)
        ]
    }


@router.post(P + "/reviewed-statements", response_model=StatementOut)
def import_statement(
    workspace_id: uuid.UUID,
    body: ImportIn,
    db: Session = Depends(get_db),
    context: TenantContext = Depends(Write),
):
    w = workspace(db, context, workspace_id)
    p = s.profile(db, w, body.profile_id)
    if (
        body.source_version is not None
        and s.versions.one(db, w.id, s.document(db, w, body.source_work_item_id).id).statement
        != body.source_version
    ):
        raise HTTPException(
            409, "The source changed after preview. Preview and confirm it again."
        )
    r = s.import_reviewed(
        db,
        w,
        p,
        body.source_work_item_id,
        body.year,
        body.rows,
        body.pan,
        body.confirmed,
    )
    db.commit()
    return {
        "id": str(r.id),
        "revision": r.revision,
        "fingerprint": r.fingerprint,
        "source_kind": r.parser_version,
        "active": r.active,
    }


@router.post(P + "/reviewed-statements/preview", response_model=PreviewOut)
def preview_statement(
    workspace_id: uuid.UUID,
    body: ImportIn,
    db: Session = Depends(get_db),
    context: TenantContext = Depends(Write),
):
    w = workspace(db, context, workspace_id)
    p = s.profile(db, w, body.profile_id)
    source = s.document(db, w, body.source_work_item_id)
    if (
        s.identity(
            body.pan, "PAN", s.encryption.decrypt_secret(p.identity_salt_ciphertext)
        )
        != p.pan_fingerprint
    ):
        raise HTTPException(
            422, "The selected entity differs from the source confirmation."
        )
    return {
        "profile_id": str(p.id),
        "pan_masked": p.pan_masked,
        "period": d.tax_period(date(body.year, 4, 1))[1],
        "source_work_item_id": str(source.id),
        "source_version": s.versions.one(db, w.id, source.id).statement,
        "rows": len(body.rows),
        "total_micros": str(sum(d.money(r.amount) for r in body.rows)),
        "parser_version": "human-transcription-v1",
        "official_format_verified": False,
    }


@router.post(P + "/official-statements")
def unsupported_statement(
    workspace_id: uuid.UUID,
    db: Session = Depends(get_db),
    context: TenantContext = Depends(Write),
):
    workspace(db, context, workspace_id)
    raise HTTPException(
        422,
        {
            "code": "TRINETRA_UNSUPPORTED_FORMAT",
            "message": "No official file layout has passed source validation. Use Documents for evidence intake and explicitly reviewed transcription; no file was parsed.",
        },
    )


@router.post(P + "/credits", response_model=CaseOut)
def create_credit(
    workspace_id: uuid.UUID,
    body: CreditIn,
    db: Session = Depends(get_db),
    context: TenantContext = Depends(Write),
):
    w = workspace(db, context, workspace_id)
    p = s.profile(db, w, body.profile_id)
    source, fact, seller = s.receivable(
        db, w, p, body.work_item_id, seller_name_confirmed=body.seller_name_confirmed
    )
    s.invoice_period(fact, body.year)
    s.lock_capacity(db, w)
    old = (
        db.query(Credit)
        .filter_by(profile_id=p.id, work_item_id=body.work_item_id, year=body.year)
        .first()
    )
    deductor = s.identity(
        body.tan, "TAN", s.encryption.decrypt_secret(p.identity_salt_ciphertext)
    )
    amount = d.money(body.amount)
    if amount <= 0 or amount > fact.total_micros:
        raise HTTPException(
            422,
            "Expected withholding must be positive and cannot exceed the sourced gross invoice.",
        )
    if old:
        if (old.expected_micros, old.deductor_key, old.reference, old.counterparty) != (
            amount,
            deductor,
            body.reference,
            body.counterparty,
        ):
            raise HTTPException(
                409,
                "This source already has an expectation; use the versioned reconfirmation workflow.",
            )
        return s.view(db, w, old)
    if db.query(Credit).filter_by(
        organization_id=w.organization_id
    ).count() >= s.capacity(db, w, "cases"):
        raise HTTPException(409, "Live case limit reached.")
    r = Credit(
        organization_id=w.organization_id,
        workspace_id=w.id,
        profile_id=p.id,
        work_item_id=body.work_item_id,
        year=body.year,
        counterparty=body.counterparty,
        reference=body.reference,
        source_version=s.invoice_version(db, w, source.id),
        deductor_key=s.identity(
            body.tan, "TAN", s.encryption.decrypt_secret(p.identity_salt_ciphertext)
        ),
        expected_micros=d.money(body.amount),
    )
    db.add(r)
    db.flush()
    db.add(
        Decision(
            organization_id=w.organization_id,
            workspace_id=w.id,
            credit_id=r.id,
            actor_id=context.user_id,
            revision=1,
            action="EXPECTATION_CONFIRMED",
            reason=body.source_confirmation + s.SELLER_NAME_NOTE.get(seller.outcome, ""),
            allocations=[],
        )
    )
    db.commit()
    return s.view(db, w, r)


@router.get(P + "/credits", response_model=CasesOut)
def credits(
    workspace_id: uuid.UUID,
    response: Response,
    offset: int = Query(0, ge=0, le=10000),
    limit: int = Query(50, ge=1, le=100),
    year: int | None = Query(None, ge=2000, le=2100),
    db: Session = Depends(get_db),
    context: TenantContext = Depends(Read),
):
    w = workspace(db, context, workspace_id)
    q = db.query(Credit).filter_by(workspace_id=w.id)
    if year:
        q = q.filter_by(year=year)
    response.headers["Cache-Control"] = "no-store"
    page = q.order_by(Credit.created_at, Credit.id).offset(offset).limit(limit).all()
    return {"total": q.count(), "items": s.views(db, w, page)[0]}


@router.post(P + "/credits/{credit_id}/decisions", response_model=CaseOut)
def decision(
    workspace_id: uuid.UUID,
    credit_id: uuid.UUID,
    body: DecisionIn,
    db: Session = Depends(get_db),
    context: TenantContext = Depends(Write),
):
    w = workspace(db, context, workspace_id)
    r = db.query(Credit).filter_by(id=credit_id, workspace_id=w.id).first()
    if not r:
        raise HTTPException(404, "Case not found.")
    p = s.profile(db, w, r.profile_id)
    db.refresh(r)
    s.decide(
        db,
        w,
        r,
        p,
        context.user_id,
        body.revision,
        body.action,
        body.reason,
        body.allocations,
        body.review_minutes,
    )
    announce_review(db, w, r)
    db.commit()
    return s.view(db, w, r)


def locked_case(db, w, credit_id):
    row = db.query(Credit).filter_by(id=credit_id, workspace_id=w.id).first()
    if not row:
        raise HTTPException(404, "Case not found.")
    p = s.profile(db, w, row.profile_id)
    db.refresh(row)
    return row, p


@router.post(P + "/credits/{credit_id}/reconfirm", response_model=CaseOut)
def reconfirm(
    workspace_id: uuid.UUID,
    credit_id: uuid.UUID,
    body: ReconfirmIn,
    db: Session = Depends(get_db),
    context: TenantContext = Depends(Write),
):
    w = workspace(db, context, workspace_id)
    row, p = locked_case(db, w, credit_id)
    s.reconfirm(
        db,
        w,
        row,
        p,
        context.user_id,
        body.revision,
        body.amount,
        body.reason,
        body.seller_name_confirmed,
    )
    announce_review(db, w, row)
    db.commit()
    return s.view(db, w, row)


@router.post(P + "/credits/{credit_id}/review", response_model=CaseOut)
def update_review(
    workspace_id: uuid.UUID,
    credit_id: uuid.UUID,
    body: ReviewIn,
    db: Session = Depends(get_db),
    context: TenantContext = Depends(Write),
):
    from dataclasses import asdict
    import json

    w = workspace(db, context, workspace_id)
    row, p = locked_case(db, w, credit_id)
    if body.revision != row.revision:
        raise HTTPException(409, "This case changed. Reload before reviewing.")
    evidence = []
    if len({item.work_item_id for item in body.evidence}) != len(body.evidence):
        raise HTTPException(422, "Attach each evidence document only once.")
    for item in body.evidence:
        source = s.document(db, w, item.work_item_id)
        evidence.append(
            {
                "work_item_id": str(source.id),
                "kind": item.kind,
                "source_version": s.versions.one(db, w.id, source.id).evidence,
                "amount_micros": (
                    d.money(item.amount) if item.amount is not None else None
                ),
            }
        )
    prior = [
        asdict(a) for a in s.allocations(db, p, row.year) if a.credit == str(row.id)
    ]
    row.review = {
        "owner_id": (
            str(context.user_id)
            if body.assign_to_me
            else (row.review or {}).get("owner_id")
        ),
        "priority": body.priority,
        "due_on": body.due_on.isoformat() if body.due_on else None,
        "root_cause": body.root_cause,
        "evidence": evidence,
        "withholding_confirmed": body.confirm_receivable,
        "invoice_version": row.source_version,
    }
    row.evidence_work_item_ids = [e["work_item_id"] for e in evidence]
    if body.confirm_receivable:
        from app.services.trinetra.projection import reviewed_withholding

        if reviewed_withholding(row, s.view(db, w, row)) is None:
            raise HTTPException(
                422,
                "Confirm withholding only with current, agreeing customer advice and accounting evidence, within the supported expectation.",
            )
    if row.state == "CA_REVIEWED":
        row.state = "OPEN"
    row.revision += 1
    db.add(
        Decision(
            organization_id=w.organization_id,
            workspace_id=w.id,
            credit_id=row.id,
            actor_id=context.user_id,
            revision=row.revision,
            action="REVIEW_UPDATED",
            evidence_work_item_ids=s.decision_sources(db, row, p),
            reason=body.reason + "\n" + json.dumps(row.review, sort_keys=True),
            allocations=prior,
        )
    )
    db.flush()
    announce_review(db, w, row)
    db.commit()
    return s.view(db, w, row)


@router.get(P + "/summary", response_model=SummaryOut)
def summary(
    workspace_id: uuid.UUID,
    response: Response,
    db: Session = Depends(get_db),
    context: TenantContext = Depends(Read),
):
    w = workspace(db, context, workspace_id)
    response.headers["Cache-Control"] = "no-store"
    return s.summary(db, w)


@router.get(P + "/credits/{credit_id}", response_model=DetailOut)
def detail(
    workspace_id: uuid.UUID,
    credit_id: uuid.UUID,
    response: Response,
    db: Session = Depends(get_db),
    context: TenantContext = Depends(Read),
):
    w = workspace(db, context, workspace_id)
    row = db.query(Credit).filter_by(id=credit_id, workspace_id=w.id).first()
    if not row:
        raise HTTPException(404, "Case not found.")
    response.headers["Cache-Control"] = "no-store"
    p = s.profile(db, w, row.profile_id)
    snapshot = s.current(db, p, row.year)
    used = s.allocations(db, p, row.year)
    lines = [
        {
            "id": x.id,
            "snapshot_id": x.snapshot,
            "amount_micros": x.amount,
            "available_micros": x.amount
            - sum(
                a.amount
                for a in used
                if a.posting == x.id
                and a.snapshot == x.snapshot
                and a.credit != str(row.id)
            ),
        }
        for x in s.postings(snapshot, w, p)
        if x.deductor == row.deductor_key
    ]
    from app.services.trinetra.projection import receivable, reviewed_withholding

    value = s.view(db, w, row)
    bank = s.bank_evidence(db, w, row, context)
    cash = (
        sum(line["amount_micros"] for line in bank)
        if bank and all(line["amount_micros"] >= 0 for line in bank)
        else None
    )
    withholding = reviewed_withholding(row, value)
    from app.services.trinetra.fields import printed

    return {
        **value,
        "printed_evidence": printed(
            s.document(db, w, row.work_item_id).extracted_entities
        ),
        "cash_projection": receivable(value["gross_micros"], cash, withholding),
        "bank_evidence": bank,
        "statement_lines": lines,
        "events_total": db.query(Decision)
        .filter_by(credit_id=row.id, workspace_id=w.id)
        .count(),
        "events": [
            {
                "revision": x.revision,
                "action": x.action,
                "reason": x.reason,
                "at": x.created_at.isoformat(),
                "actor_id": str(x.actor_id) if x.actor_id else None,
                "review_minutes": x.review_minutes,
            }
            for x in db.query(Decision)
            .filter_by(credit_id=row.id, workspace_id=w.id)
            .order_by(Decision.revision.desc())
            .limit(200)
        ],
    }


@router.get(P + "/credits/{credit_id}/inquiry-draft", response_model=DraftOut)
def draft(
    workspace_id: uuid.UUID,
    credit_id: uuid.UUID,
    db: Session = Depends(get_db),
    context: TenantContext = Depends(Write),
):
    w = workspace(db, context, workspace_id)
    row = db.query(Credit).filter_by(id=credit_id, workspace_id=w.id).first()
    if not row:
        raise HTTPException(404, "Case not found.")
    return {
        "subject": "Please help clarify withholding evidence",
        "body": "Please share the deduction advice or certificate associated with "
        + row.reference
        + ". We are comparing our records with the statement supplied to us. This inquiry does not allege missing filing or establish tax-credit eligibility.",
        "sent": False,
        "requires_human_approval": True,
        "external_sending_enabled": False,
    }


@router.get(P + "/export.{format}")
def export_evidence(
    workspace_id: uuid.UUID,
    format: Literal["csv", "xlsx", "html"],
    db: Session = Depends(get_db),
    context: TenantContext = Depends(Write),
):
    from app.services.trinetra.export import build
    from app.services import audit_service
    from app.models.audit_log import AuditResourceType, AuditAction

    w = workspace(db, context, workspace_id)
    data, media_type = build(db, w, format)
    audit_service.record(
        db,
        organization_id=w.organization_id,
        workspace_id=w.id,
        actor_id=context.user_id,
        resource_type=AuditResourceType.WORKSPACE,
        resource_id=w.id,
        action=AuditAction.EXPORTED,
        details={
            "module": "trinetra",
            "format": format,
            "bytes": len(data),
            "rule_version": d.VERSION,
        },
    )
    db.commit()
    return Response(
        data,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="trinetra-evidence.{format}"',
            "Cache-Control": "no-store",
            "Content-Security-Policy": "default-src 'none'; sandbox",
        },
    )


@router.post(P + "/reconciliation", response_model=RunOut)
def recompute(
    workspace_id: uuid.UUID,
    db: Session = Depends(get_db),
    context: TenantContext = Depends(Write),
):
    from app.services import job_service
    import hashlib

    w = workspace(db, context, workspace_id)
    rows = (
        db.query(Credit)
        .filter_by(workspace_id=w.id)
        .order_by(Credit.id)
        .limit(5000)
        .all()
    )
    from app.models.trinetra import TrinetraStatement

    snapshots = (
        db.query(TrinetraStatement).filter_by(workspace_id=w.id, active=True).all()
    )
    digest = hashlib.sha256(
        repr(
            (
                [(str(x.id), x.revision) for x in rows],
                sorted(str(x.id) for x in snapshots),
            )
        ).encode()
    ).hexdigest()
    job = job_service.enqueue(
        db,
        job_type="trinetra.recompute",
        organization_id=w.organization_id,
        payload={"organization_id": str(w.organization_id), "workspace_id": str(w.id)},
        idempotency_key="trinetra:" + str(w.id) + ":" + digest,
    )
    db.commit()
    return {"job_id": str(job.id)}


@router.get(P + "/reconciliation/{job_id}", response_model=RunStatusOut)
def run_status(
    workspace_id: uuid.UUID,
    job_id: uuid.UUID,
    db: Session = Depends(get_db),
    context: TenantContext = Depends(Read),
):
    from app.models.job import Job

    w = workspace(db, context, workspace_id)
    job = (
        db.query(Job)
        .filter_by(
            id=job_id, organization_id=w.organization_id, job_type="trinetra.recompute"
        )
        .first()
    )
    if not job or job.payload.get("workspace_id") != str(w.id):
        raise HTTPException(404, "Run not found.")
    return {"job_id": str(job.id), "status": job.status.value, "result": job.result}


@router.get(
    "/organizations/{organization_id}/trinetra/access",
    response_model=OrganizationAccessOut,
)
def organization_access(
    organization_id: uuid.UUID,
    db: Session = Depends(get_db),
    context: OrganizationContext = Depends(
        RequireOrgRole(
            [OrganizationRole.OWNER, OrganizationRole.ADMIN, OrganizationRole.BILLING]
        )
    ),
):
    live = mode.state(db, organization_id)
    return {
        "live_enabled": live.live,
        "mode": live.mode,
        "enrolled": live.enrolled,
        "entitled": capability_gate.has_capability(
            db,
            organization_id=organization_id,
            capability_key="capability.trinetra_all_workspaces",
        ),
    }


@router.get(
    "/organizations/{organization_id}/trinetra/summary",
    response_model=OrganizationSummaryOut,
)
def organization_summary(
    organization_id: uuid.UUID,
    offset: int = Query(0, ge=0, le=10000),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
    context: OrganizationContext = Depends(
        RequireOrgRole(
            [OrganizationRole.OWNER, OrganizationRole.ADMIN, OrganizationRole.BILLING]
        )
    ),
):
    from app.services.helm.gate import readable_workspaces
    from app.workers.tenant_gate import inactive_reason, unpaid_reason

    capability_gate.require_capability(
        db,
        context=context,
        capability_key="capability.trinetra_all_workspaces",
        operation="trinetra.org.summary",
    )
    require_source_validation(db, organization_id)
    if inactive_reason(db, organization_id=organization_id) or unpaid_reason(
        db, organization_id=organization_id
    ):
        raise HTTPException(402, "An active organization subscription is required.")
    allowed = readable_workspaces(
        db, organization_id=organization_id, user_id=context.user_id, role=context.role
    )
    results = []
    for w in (
        db.query(Workspace)
        .filter(
            Workspace.organization_id == organization_id,
            Workspace.id.in_(allowed),
            Workspace.is_sample.is_(False),
        )
        .order_by(Workspace.id)
        .offset(offset)
        .limit(limit)
    ):
        if inactive_reason(db, organization_id=organization_id, workspace_id=w.id):
            continue
        result = s.summary(db, w)
        results.append(
            {
                "workspace_id": str(w.id),
                "name": w.workspace_name,
                **{
                    k: str(result[k]) if k.endswith("_micros") else result[k]
                    for k in (
                        "total",
                        "unresolved",
                        "expected_micros",
                        "posted_micros",
                        "gap_micros",
                        "as_of",
                    )
                },
            }
        )
    return {
        "workspaces": results,
        "scope": "Only workspaces readable by the current reviewer. Entities remain separate.",
        "is_sample": False,
    }
