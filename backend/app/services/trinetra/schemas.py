"""Public evidence contracts. Micros travel as decimal strings to preserve JS precision."""

from typing import Any, Annotated
from pydantic import BaseModel, Field, PlainSerializer

Micros = Annotated[int, PlainSerializer(str, return_type=str, when_used="json")]


class Wire(BaseModel):
    pass


class CaseOut(Wire):
    id: str
    profile_id: str | None = None
    counterparty: str
    reference: str
    year: int
    period: str
    revision: int
    review_state: str
    review: dict[str, Any] = Field(default_factory=dict)
    status: str
    expected_micros: Micros | None
    posted_micros: Micros
    gap_micros: Micros | None
    gross_micros: Micros | None
    bank_micros: Micros | None
    booked_micros: Micros | None
    advice_micros: Micros | None
    candidate_ids: list[str]
    rule_version: str
    note: str
    work_item_id: str | None = None
    statement_work_item_id: str | None = None
    statement_reader: dict | None = None
    snapshot_id: str | None = None
    source_current: bool = True
    created_at: str
    age_days: int = 0
    as_of: str | None


class CasesOut(Wire):
    items: list[CaseOut]
    total: int


class OutcomesOut(Wire):
    confirmed_gap_closure_micros: Micros = 0
    confirmed_cases: int = 0
    review_minutes: int = 0
    note: str = "No measured outcomes for synthetic examples."


class SummaryOut(CasesOut):
    outcomes: OutcomesOut = Field(default_factory=OutcomesOut)
    is_sample: bool
    as_of: str | None
    expected_micros: Micros
    posted_micros: Micros
    gap_micros: Micros
    unresolved: int
    note: str


class ProfileOut(BaseModel):
    id: str
    name: str
    pan_masked: str


class ProfilesOut(BaseModel):
    items: list[ProfileOut]


class StatementOut(BaseModel):
    id: str
    revision: int
    fingerprint: str
    source_kind: str
    active: bool


class PostingOut(Wire):
    id: str
    snapshot_id: str
    amount_micros: Micros
    available_micros: Micros


class BankOut(Wire):
    id: str
    amount_micros: Micros
    on: str


class EventOut(BaseModel):
    review_minutes: int = 0
    revision: int
    action: str
    reason: str
    at: str
    actor_id: str | None


class ProjectionOut(Wire):
    gross_micros: Micros | None
    cash_received_micros: Micros | None
    reviewed_withholding_micros: Micros | None
    unexplained_micros: Micros | None
    overexplained_micros: Micros | None
    status: str
    note: str


class PrintedEvidenceOut(Wire):
    amount_micros: Micros | None
    deductor_tan_masked: str | None
    section_label: str | None
    note: str


class DetailOut(CaseOut):
    printed_evidence: PrintedEvidenceOut
    statement_lines: list[PostingOut]
    bank_evidence: list[BankOut]
    events: list[EventOut]
    events_total: int
    cash_projection: ProjectionOut


class AccessOut(BaseModel):
    live_enabled: bool
    mode: str
    enrolled: bool
    enrolled_since: str | None = None
    entitled: bool
    official_formats: list[str]
    statement_readers: list[dict] = []
    transcription_format: str
    tcs_supported: bool


class DraftOut(BaseModel):
    subject: str
    body: str
    sent: bool
    requires_human_approval: bool
    external_sending_enabled: bool


class PreviewOut(Wire):
    profile_id: str
    pan_masked: str
    period: str
    source_work_item_id: str
    source_version: str
    rows: int
    total_micros: Micros
    parser_version: str
    official_format_verified: bool


class FilePreviewOut(Wire):
    """What a statement file would import, for the reviewer to confirm before anything is saved."""

    reader: str
    reader_label: str
    official: bool
    verified: bool
    parser_version: str
    sha256: str
    tax_year_label: str | None = None
    tax_year_kind: str | None = None
    year: int
    year_matches: bool
    file_pan_matches: bool | None = None
    rows: int
    total_micros: Micros
    deductors: list[dict]
    mapping: list[dict]
    columns: dict | None = None
    checks: list[dict]
    ignored: list[str]
    sample: list[dict]
    notice: str


class RunOut(BaseModel):
    job_id: str


class RunStatusOut(RunOut):
    status: str
    result: dict[str, Any] | None


class OrganizationAccessOut(BaseModel):
    live_enabled: bool
    mode: str
    enrolled: bool
    entitled: bool


class WorkspaceSummaryOut(Wire):
    workspace_id: str
    name: str
    total: int
    unresolved: int
    expected_micros: Micros
    posted_micros: Micros
    gap_micros: Micros
    as_of: str | None


class OrganizationSummaryOut(BaseModel):
    workspaces: list[WorkspaceSummaryOut]
    scope: str
    is_sample: bool
