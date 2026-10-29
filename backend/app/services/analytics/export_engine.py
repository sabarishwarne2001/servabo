"""ARCH-26 §1, §2 — versioned export datasets and signed Parquet bundles.

WHAT THIS MODULE REFUSES TO EXPORT, AND WHY
===========================================

Invariant I1, COGS confidentiality. `usage_rollups` carries two money columns
that look interchangeable and are not:

    cost_micros        what we invoiced the tenant.  EXPORTED.
    cost_basis_micros  what the supplier charged us. NEVER EXPORTED.

The second is our cost of goods. A tenant who can read it can compute our
margin on their own account and negotiate against it at renewal, and once it
is sitting in their Snowflake there is no mechanism by which we take it back.

This is not enforced by remembering. `FORBIDDEN_COLUMN_NAMES` below is checked
at runtime against every column of every dataset spec at import time, and
`verify_arch26.py` G5 walks this module's AST for any attribute access named
`cost_basis_micros`, `cost_basis_source`, `cost_basis_source_mix` or
`unknown_cost_basis_event_count`. Both have to be defeated for a leak to ship,
and the second one cannot be defeated by aliasing, because the gate resolves
the attribute name rather than the local it lands in.

WHY ASSISTANT TURNS EXPORT WITHOUT `content`
============================================

`conversation_messages.content` is the tenant's own text, so exporting it is
not a confidentiality problem in the COGS sense. It is a *residency* problem.

ARCH-20 lets a tenant pin their data to a region and set a retention window on
it. A warehouse push moves message bodies into infrastructure we do not
operate, outside the residency boundary they configured, with a retention
policy that is now theirs and not ours — and it does so on a cron, silently,
after a one-time click. Message metadata (who, when, how many tokens, did it
finish) answers every analytical question the tranche exists to serve without
that happening.

A tenant who genuinely wants conversation bodies in their warehouse has
ARCH-20's compliance export, which is a deliberate, audited, human-initiated
act. That is the right shape for that operation.

WHY PARQUET AND NOT CSV
=======================

Every one of the four destinations ingests Parquet with types intact.
CSV re-introduces type ambiguity at exactly the boundary where we stop being
able to correct it: a `quantity` column that arrives as text in a tenant's
warehouse gets cast by whoever models it downstream, and the cast they choose
is the cast we live with.

WHY pyarrow IS IMPORTED INSIDE THE FUNCTION
===========================================

ARCH-26 audit decision B2-a. pyarrow is ~50MB of extension modules. Every
FastAPI worker imports this module transitively through `sync_service`, and
none of them writes a bundle — that happens on the LIGHT worker. A module-level
`import pyarrow` costs every API process its import time and resident memory
for a code path it never executes.
"""

from __future__ import annotations

import hashlib
import io
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.assistant import Conversation, ConversationMessage
from app.models.automation_execution import AutomationExecution
from app.models.uploaded_file import UploadedFile
from app.models.usage_rollup import UsageRollup
from app.models.workspace import Workspace

logger = logging.getLogger("app.services.analytics.export_engine")


class ExportEngineError(RuntimeError):
    """A bundle could not be produced."""


class ForbiddenColumnError(ExportEngineError):
    """A dataset spec named a column that must never leave the platform."""


class ParquetUnavailableError(ExportEngineError):
    """pyarrow is not installed in this image."""


#: Columns that may never appear in a tenant-facing export, in any dataset,
#: under any name. Checked at import time against every spec below, and again
#: inside `write_parquet` against the actual row keys — because a spec can be
#: correct while an extractor adds a key the spec never declared.
#:
#: `cost_micros` is deliberately NOT here. That is the invoiced price, which
#: the tenant already sees on their invoice, and withholding it would make the
#: export useless for the reconciliation it exists to support.
FORBIDDEN_COLUMN_NAMES: frozenset[str] = frozenset(
    {
        "cost_basis_micros",
        "cost_basis_source",
        "cost_basis_source_mix",
        "unknown_cost_basis_event_count",
        "known_cost_basis_event_count",
        "margin_micros",
        "supplier_cost_micros",
    }
)

#: Bump when a dataset's column set changes. The version travels in the
#: manifest and in the Parquet key name, so a tenant's dbt model can pin to a
#: version and fail loudly rather than silently reading a renamed column.
DATASET_SCHEMA_VERSIONS: dict[str, int] = {
    "USAGE_ROLLUPS": 1,
    "DOCUMENT_METADATA": 1,
    "ASSISTANT_TURNS": 1,
    "AUTOMATION_RUNS": 1,
    # Final session 1 (Phase 6): Enterprise datasets, see DATASET_CAPABILITY.
    "GST_MATCHES": 1,
    "HELM_LEDGER": 1,
    # Final session 2T (Phase 7.8): TRINETRA's cases, masked. Enterprise.
    "TRINETRA_CASES": 1,
}

#: Hard ceiling on rows pulled per dataset per run. A tenant with a 90-day
#: lookback over hourly rollups can ask for several million rows, and the
#: worker holds the whole part in memory to digest it. Exceeding this marks
#: the run PARTIAL rather than failing it: delivering 500k rows and saying so
#: beats delivering nothing.
MAX_ROWS_PER_DATASET: int = 500_000


@dataclass(frozen=True)
class ColumnSpec:
    name: str
    #: One of: string, int64, double, timestamp, bool. Mapped to pyarrow types
    #: inside `write_parquet`. Kept as strings here so this module is
    #: importable and testable without pyarrow present.
    arrow_type: str
    description: str


@dataclass(frozen=True)
class DatasetSpec:
    dataset: str
    version: int
    description: str
    columns: tuple[ColumnSpec, ...]

    @property
    def column_names(self) -> tuple[str, ...]:
        return tuple(column.name for column in self.columns)

    def as_descriptor(self) -> dict[str, Any]:
        return {
            "dataset": self.dataset,
            "version": self.version,
            "description": self.description,
            "columns": [
                {
                    "name": column.name,
                    "type": column.arrow_type,
                    "description": column.description,
                }
                for column in self.columns
            ],
        }


# ---------------------------------------------------------------------------
# Dataset specifications
# ---------------------------------------------------------------------------

USAGE_ROLLUPS_SPEC = DatasetSpec(
    dataset="USAGE_ROLLUPS",
    version=DATASET_SCHEMA_VERSIONS["USAGE_ROLLUPS"],
    description=(
        "Aggregated consumption per event type, provider and model. Carries "
        "quantities and the price we invoiced. Supplier cost is not included "
        "and will not be added."
    ),
    columns=(
        ColumnSpec("rollup_id", "string", "Stable identifier for this bucket."),
        ColumnSpec("organization_id", "string", "Owning tenant."),
        ColumnSpec("workspace_id", "string", "NULL for organization totals."),
        ColumnSpec("grain", "string", "DETAIL or ORG_TOTAL."),
        ColumnSpec("granularity", "string", "HOUR, DAY or MONTH."),
        ColumnSpec("event_type", "string", "Metered event type; '*' on totals."),
        ColumnSpec("provider", "string", "Serving provider, NULL on totals."),
        ColumnSpec("model", "string", "Model identifier, NULL on totals."),
        ColumnSpec("bucket_start", "timestamp", "Inclusive window start, UTC."),
        ColumnSpec("bucket_end", "timestamp", "Exclusive window end, UTC."),
        ColumnSpec("quantity", "double", "Total metered quantity."),
        ColumnSpec(
            "estimated_quantity",
            "double",
            "Portion of quantity that is estimated rather than measured.",
        ),
        ColumnSpec(
            "billed_micros",
            "int64",
            "What we invoiced for this bucket, in micros. This is price, not "
            "cost. Sourced from usage_rollups.cost_micros.",
        ),
        ColumnSpec("event_count", "int64", "Events folded into this bucket."),
        ColumnSpec(
            "late_event_count",
            "int64",
            "Events that arrived after the bucket first closed.",
        ),
        ColumnSpec(
            "is_sealed",
            "bool",
            "True once the window is immutable. An unsealed bucket may still "
            "move; a dbt model should filter on this before reporting.",
        ),
    ),
)

DOCUMENT_METADATA_SPEC = DatasetSpec(
    dataset="DOCUMENT_METADATA",
    version=DATASET_SCHEMA_VERSIONS["DOCUMENT_METADATA"],
    description=(
        "One row per uploaded document. Metadata only: no file bytes, no "
        "extracted text."
    ),
    columns=(
        ColumnSpec("file_id", "string", "Document identifier."),
        ColumnSpec("organization_id", "string", "Owning tenant."),
        ColumnSpec("workspace_id", "string", "Owning workspace."),
        ColumnSpec("original_filename", "string", "As uploaded."),
        ColumnSpec("mime_type", "string", "Detected content type."),
        ColumnSpec("file_size_bytes", "int64", "Stored object size."),
        ColumnSpec(
            "checksum_sha256",
            "string",
            "Content digest. Lets a tenant reconcile against their own copy.",
        ),
        ColumnSpec("uploaded_at", "timestamp", "Creation time, UTC."),
        ColumnSpec(
            "deleted_at",
            "timestamp",
            "NULL while live. Present so a warehouse model can see removals "
            "rather than inferring them from a row disappearing.",
        ),
    ),
)

ASSISTANT_TURNS_SPEC = DatasetSpec(
    dataset="ASSISTANT_TURNS",
    version=DATASET_SCHEMA_VERSIONS["ASSISTANT_TURNS"],
    description=(
        "One row per assistant message. Metadata only — message bodies are "
        "excluded so that a scheduled push cannot move conversation text "
        "outside the ARCH-20 residency boundary the tenant configured."
    ),
    columns=(
        ColumnSpec("message_id", "string", "Message identifier."),
        ColumnSpec("conversation_id", "string", "Owning conversation."),
        ColumnSpec("organization_id", "string", "Owning tenant."),
        ColumnSpec("workspace_id", "string", "Owning workspace."),
        ColumnSpec("role", "string", "user or assistant."),
        ColumnSpec("created_at", "timestamp", "Message time, UTC."),
        ColumnSpec(
            "prompt_tokens",
            "int64",
            "NULL when the provider did not report usage. Not 0.",
        ),
        ColumnSpec("completion_tokens", "int64", "NULL when unreported."),
        ColumnSpec("total_tokens", "int64", "NULL when unreported."),
        ColumnSpec(
            "usage_estimated",
            "bool",
            "True when token counts were estimated locally rather than "
            "returned by the provider.",
        ),
        ColumnSpec("finish_reason", "string", "Provider stop reason."),
        ColumnSpec("truncated", "bool", "Whether the turn hit a length cap."),
        ColumnSpec(
            "source_count",
            "int64",
            "Retrieved citations attached to this turn.",
        ),
    ),
)

AUTOMATION_RUNS_SPEC = DatasetSpec(
    dataset="AUTOMATION_RUNS",
    version=DATASET_SCHEMA_VERSIONS["AUTOMATION_RUNS"],
    description="One row per automation execution, with node-level counters.",
    columns=(
        ColumnSpec("execution_id", "string", "Execution identifier."),
        ColumnSpec("organization_id", "string", "Owning tenant."),
        ColumnSpec("workspace_id", "string", "Owning workspace."),
        ColumnSpec("rule_id", "string", "Automation rule that fired."),
        ColumnSpec("work_item_id", "string", "Subject work item, if any."),
        ColumnSpec("correlation_id", "string", "Chain identifier."),
        ColumnSpec("status", "string", "Terminal or in-flight status."),
        ColumnSpec("depth", "int64", "Cascade depth at which this ran."),
        ColumnSpec("started_at", "timestamp", "NULL if never started."),
        ColumnSpec("completed_at", "timestamp", "NULL while running."),
        ColumnSpec("node_count", "int64", "Nodes in the graph."),
        ColumnSpec("nodes_executed", "int64", "Nodes actually run."),
        ColumnSpec("actions_executed", "int64", "Side-effecting actions run."),
        ColumnSpec(
            "budget_cost_micros",
            "int64",
            "Ceiling granted to this execution, in micros of invoiced price.",
        ),
        ColumnSpec(
            "spent_cost_micros",
            "int64",
            "Invoiced price consumed by this execution, in micros.",
        ),
        ColumnSpec("has_error", "bool", "Whether the run recorded an error."),
    ),
)

GST_MATCHES_SPEC = DatasetSpec(
    dataset="GST_MATCHES",
    version=DATASET_SCHEMA_VERSIONS["GST_MATCHES"],
    description=(
        "One row per reconciled GST record or purchase invoice, across every workspace: how a supplier's GSTR-2B "
        "record matched the invoice the books hold, and what the credit is worth. Identifiers and figures only: no "
        "supplier names, no document text. Rows the engine recomputed in the window; the engine rebuilds a workspace's "
        "matches when a return is imported, so each import writes its rows again. Enterprise."
    ),
    columns=(
        ColumnSpec("match_id", "string", "Stable identifier for this match row."),
        ColumnSpec("organization_id", "string", "Owning tenant."),
        ColumnSpec("workspace_id", "string", "Owning workspace."),
        ColumnSpec("gstin", "string", "The buyer's GSTIN the return belongs to."),
        ColumnSpec("supplier_gstin", "string", "The supplier's GSTIN, NULL when the document names none."),
        ColumnSpec("record_id", "string", "The GSTR-2B record, NULL when the supplier reported nothing."),
        ColumnSpec("work_item_id", "string", "The purchase invoice document, NULL when the books hold none."),
        ColumnSpec(
            "status", "string",
            "MATCHED, MATCHED_WITH_DIFFERENCES, WAITING_FOR_SUPPLIER, NOT_IN_BOOKS, NOT_ELIGIBLE and the others the "
            "GST Credit page shows.",
        ),
        ColumnSpec("method", "string", "How it was matched (IRN, GSTIN and number, ...), NULL when unmatched."),
        ColumnSpec("document_number", "string", "The invoice or note number as printed."),
        ColumnSpec("document_date", "timestamp", "The document date, midnight UTC; NULL when unknown."),
        ColumnSpec("value_micros", "int64", "Invoice value in INR micros."),
        ColumnSpec("tax_micros", "int64", "Tax on the invoice in INR micros."),
        ColumnSpec("claimable_micros", "int64", "Input credit the supplier reported as available, INR micros."),
        ColumnSpec("difference_count", "int64", "How many amounts differ between record and books."),
        ColumnSpec("ims_action", "string", "ACCEPT, PENDING or REJECT when an IMS action is recorded."),
        ColumnSpec("decision", "string", "A person's decision (CONFIRM, NOT_OURS, LINK), NULL when none."),
        ColumnSpec("reported_late", "bool", "Whether the supplier reported it after the period it belongs to."),
        ColumnSpec("period_first_seen", "string", "YYYY-MM of the first statement that carried it."),
        ColumnSpec("days_unpaid", "int64", "Days since the invoice date of an unpaid invoice, as of the end of the window; NULL when paid or not tracked."),
        ColumnSpec("computed_at", "timestamp", "When the engine last computed this row, UTC."),
    ),
)

HELM_LEDGER_SPEC = DatasetSpec(
    dataset="HELM_LEDGER",
    version=DATASET_SCHEMA_VERSIONS["HELM_LEDGER"],
    description=(
        "Helm's Promise ledger across every workspace: one row per promise found in the documents (a payment due, "
        "a delivery, a price held) and whether it was kept. Identifiers, states and figures only: no counterparty "
        "names, titles or evidence quotes. Rows updated in the window. The invented sample company is never exported. "
        "Enterprise."
    ),
    columns=(
        ColumnSpec("promise_id", "string", "Stable identifier for this promise."),
        ColumnSpec("organization_id", "string", "Owning tenant."),
        ColumnSpec("workspace_id", "string", "Owning workspace."),
        ColumnSpec("work_item_id", "string", "The document the promise was found in, NULL when it has none."),
        ColumnSpec("obligation_id", "string", "The obligation it belongs to, NULL when none."),
        ColumnSpec("kind", "string", "The kind of promise, as the Promise ledger names it."),
        ColumnSpec("direction", "string", "Whether it is owed to the company or by it."),
        ColumnSpec("counterparty_key", "string", "A stable key for the other party; join to your own master data."),
        ColumnSpec("currency", "string", "ISO currency, NULL when the promise has no amount."),
        ColumnSpec("amount_micros", "int64", "Promised amount in micros of the currency, NULL when none."),
        ColumnSpec("due_date", "timestamp", "When it falls due, midnight UTC; NULL when open-ended."),
        ColumnSpec("window_end", "timestamp", "End of the window it may be kept in, midnight UTC; NULL when none."),
        ColumnSpec("status", "string", "Open, kept, broken or the other states the ledger shows."),
        ColumnSpec("confidence", "string", "How sure the reading is."),
        ColumnSpec("fulfilment_count", "int64", "How many payments or events were matched against it."),
        ColumnSpec("engine_version", "string", "The ledger engine that wrote the row."),
        ColumnSpec("created_at", "timestamp", "When Helm first found it, UTC."),
        ColumnSpec("updated_at", "timestamp", "When it last changed, UTC."),
    ),
)

TRINETRA_CASES_SPEC = DatasetSpec(
    dataset="TRINETRA_CASES",
    version=DATASET_SCHEMA_VERSIONS["TRINETRA_CASES"],
    description=(
        "TRINETRA's cases across every workspace: one row per case that was opened, or decided on, in the window. A case is the "
        "tax a customer withheld from one invoice and where it stands in your imported tax statement. Identifiers, states and "
        "figures only: no PAN, no TAN, no customer or invoice name, no note or document text. The customer is a stable key you can "
        "join to your own master data. A gap is an item to check, never money. The invented sample company is never exported. "
        "Enterprise."
    ),
    columns=(
        ColumnSpec("case_id", "string", "Stable identifier for this case."),
        ColumnSpec("organization_id", "string", "Owning tenant."),
        ColumnSpec("workspace_id", "string", "Owning workspace."),
        ColumnSpec("profile_id", "string", "The legal-entity profile the case belongs to (an opaque id; the PAN is never exported)."),
        ColumnSpec("work_item_id", "string", "The invoice document the withholding was confirmed on."),
        ColumnSpec("customer_key", "string", "A stable key for the customer; join to your own master data. Not the customer's name."),
        ColumnSpec("year", "int64", "The tax year, as the year in which it starts (2025 is 2025-26)."),
        ColumnSpec("revision", "int64", "The case revision this row describes."),
        ColumnSpec("review_state", "string", "OPEN, DISPUTED, EXPLAINED, WITHDRAWN, CA_REVIEWED or UNRESOLVED."),
        ColumnSpec("status", "string", "The comparison status: POSTED, LATE_POSTING, VERIFIED_CORRECTED, AMOUNT_MISMATCH, "
                                       "DUPLICATE_SUSPECTED, AMBIGUOUS, SUGGESTED, TAN_MISMATCH_SUSPECTED, POSSIBLE_MISSING_POSTING, "
                                       "EVIDENCE_NEEDED, PENDING_REPORT, DISPUTED, WITHDRAWN, CLOSED_WITH_EXCEPTION or UNRESOLVED."),
        ColumnSpec("currency", "string", "Always INR."),
        ColumnSpec("expected_micros", "int64", "The withheld amount the case rests on, INR micros; NULL when the evidence is stale."),
        ColumnSpec("posted_micros", "int64", "What the active statement shows for this case, INR micros."),
        ColumnSpec("gap_micros", "int64", "expected less posted when both are known, INR micros; NULL when unknown. Never money."),
        ColumnSpec("source_current", "bool", "Whether the invoice is still the one the withholding was confirmed on."),
        ColumnSpec("age_days", "int64", "Days since the case was opened, as of the extraction."),
        ColumnSpec("created_at", "timestamp", "When the case was opened, UTC."),
        ColumnSpec("updated_at", "timestamp", "When it last changed (its latest decision), UTC."),
    ),
)

DATASET_SPECS: dict[str, DatasetSpec] = {
    spec.dataset: spec
    for spec in (
        USAGE_ROLLUPS_SPEC,
        DOCUMENT_METADATA_SPEC,
        ASSISTANT_TURNS_SPEC,
        AUTOMATION_RUNS_SPEC,
        GST_MATCHES_SPEC,
        HELM_LEDGER_SPEC,
        TRINETRA_CASES_SPEC,
    )
}

#: Datasets that need a capability the organization's plan must hold (Final session 1, Phase 6). Both span every
#: workspace of the organization, which is what the "all workspaces" capabilities sell (Enterprise). The other datasets
#: need nothing beyond the warehouse add-on every export already needs.
DATASET_CAPABILITY: dict[str, str] = {
    "GST_MATCHES": "capability.gst_credit_all_workspaces",
    "HELM_LEDGER": "capability.helm_all_workspaces",
    "TRINETRA_CASES": "capability.trinetra_all_workspaces",
}


def _assert_specs_are_clean() -> None:
    """Import-time guard.

    Runs once, at import, so a spec that names a forbidden column cannot be
    deployed at all — not merely fail a test somebody might skip.
    """
    for spec in DATASET_SPECS.values():
        offending = sorted(
            set(spec.column_names) & FORBIDDEN_COLUMN_NAMES
        )
        if offending:
            raise ForbiddenColumnError(
                f"Dataset {spec.dataset} declares forbidden column(s) "
                f"{offending}. Supplier cost never leaves the platform "
                "(ARCH-26 invariant I1)."
            )


_assert_specs_are_clean()


# ---------------------------------------------------------------------------
# Extraction
#
# Every extractor takes organization_id and filters on it. There is no
# code path in this module that reads a row without a tenant predicate;
# verify_arch26.py G6 asserts that by AST over each function body.
# ---------------------------------------------------------------------------


def _iso(value: Optional[datetime]) -> Optional[datetime]:
    """Normalise to timezone-aware UTC, or None.

    A naive datetime written into Parquet is a timestamp whose meaning depends
    on the reader's locale. Every timestamp leaving here is UTC-aware.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _s(value: Any) -> Optional[str]:
    return None if value is None else str(value)


def _token(usage: Optional[dict[str, Any]], key: str) -> Optional[int]:
    """Pull one token count, preserving 'unreported' as NULL.

    `(usage or {}).get(key, 0)` is the tempting one-liner and it is the same
    mistake as `COALESCE(cost_basis_micros, 0)`: it turns "the provider did
    not tell us" into "there were none", and a warehouse model summing that
    column reports a token spend lower than the invoice.
    """
    if not usage:
        return None
    raw = usage.get(key)
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def extract_usage_rollups(
    db: Session,
    *,
    organization_id: uuid.UUID,
    window_start: datetime,
    window_end: datetime,
    limit: int = MAX_ROWS_PER_DATASET,
) -> list[dict[str, Any]]:
    stmt = (
        select(UsageRollup)
        .where(UsageRollup.organization_id == organization_id)
        .where(UsageRollup.bucket_start >= window_start)
        .where(UsageRollup.bucket_start < window_end)
        .order_by(UsageRollup.bucket_start.asc(), UsageRollup.id.asc())
        .limit(limit)
    )
    rows: list[dict[str, Any]] = []
    for rollup in db.execute(stmt).scalars():
        rows.append(
            {
                "rollup_id": str(rollup.id),
                "organization_id": str(rollup.organization_id),
                "workspace_id": _s(rollup.workspace_id),
                "grain": rollup.grain,
                "granularity": rollup.granularity,
                "event_type": rollup.event_type,
                "provider": rollup.provider,
                "model": rollup.model,
                "bucket_start": _iso(rollup.bucket_start),
                "bucket_end": _iso(rollup.bucket_end),
                "quantity": float(Decimal(rollup.quantity or 0)),
                "estimated_quantity": float(
                    Decimal(rollup.estimated_quantity or 0)
                ),
                # cost_micros is the INVOICED price. The supplier-side column
                # on this same row is never read here.
                "billed_micros": int(rollup.cost_micros or 0),
                "event_count": int(rollup.event_count or 0),
                "late_event_count": int(rollup.late_event_count or 0),
                "is_sealed": rollup.sealed_at is not None,
            }
        )
    return rows


def extract_document_metadata(
    db: Session,
    *,
    organization_id: uuid.UUID,
    window_start: datetime,
    window_end: datetime,
    limit: int = MAX_ROWS_PER_DATASET,
) -> list[dict[str, Any]]:
    stmt = (
        select(UploadedFile)
        .where(UploadedFile.organization_id == organization_id)
        .where(UploadedFile.created_at >= window_start)
        .where(UploadedFile.created_at < window_end)
        .order_by(UploadedFile.created_at.asc(), UploadedFile.id.asc())
        .limit(limit)
    )
    rows: list[dict[str, Any]] = []
    for record in db.execute(stmt).scalars():
        rows.append(
            {
                "file_id": str(record.id),
                "organization_id": str(record.organization_id),
                "workspace_id": _s(record.workspace_id),
                "original_filename": record.original_filename,
                "mime_type": record.mime_type,
                "file_size_bytes": int(record.file_size or 0),
                "checksum_sha256": record.checksum_sha256,
                "uploaded_at": _iso(record.created_at),
                "deleted_at": _iso(record.deleted_at),
            }
        )
    return rows


def extract_assistant_turns(
    db: Session,
    *,
    organization_id: uuid.UUID,
    window_start: datetime,
    window_end: datetime,
    limit: int = MAX_ROWS_PER_DATASET,
) -> list[dict[str, Any]]:
    """Message metadata, scoped through conversation -> workspace -> org.

    `conversation_messages` carries no organization_id of its own, so the
    tenant predicate has to come from the join. Writing this as a query over
    messages with a filter applied afterwards in Python is how a cross-tenant
    read gets shipped; the predicate is in the SQL.
    """
    stmt = (
        select(ConversationMessage, Conversation.workspace_id)
        .join(
            Conversation,
            Conversation.id == ConversationMessage.conversation_id,
        )
        .join(Workspace, Workspace.id == Conversation.workspace_id)
        .where(Workspace.organization_id == organization_id)
        .where(ConversationMessage.created_at >= window_start)
        .where(ConversationMessage.created_at < window_end)
        .order_by(
            ConversationMessage.created_at.asc(), ConversationMessage.id.asc()
        )
        .limit(limit)
    )
    rows: list[dict[str, Any]] = []
    for message, workspace_id in db.execute(stmt).all():
        usage = message.token_usage or {}
        sources = message.sources or []
        rows.append(
            {
                "message_id": str(message.id),
                "conversation_id": str(message.conversation_id),
                "organization_id": str(organization_id),
                "workspace_id": _s(workspace_id),
                "role": str(getattr(message.role, "value", message.role)),
                "created_at": _iso(message.created_at),
                "prompt_tokens": _token(usage, "prompt_tokens"),
                "completion_tokens": _token(usage, "completion_tokens"),
                "total_tokens": _token(usage, "total_tokens"),
                "usage_estimated": bool(message.usage_estimated),
                "finish_reason": message.finish_reason,
                "truncated": bool(message.truncated),
                "source_count": len(sources) if isinstance(sources, list) else 0,
                # message.content is deliberately absent. See module docstring.
            }
        )
    return rows


def extract_automation_runs(
    db: Session,
    *,
    organization_id: uuid.UUID,
    window_start: datetime,
    window_end: datetime,
    limit: int = MAX_ROWS_PER_DATASET,
) -> list[dict[str, Any]]:
    stmt = (
        select(AutomationExecution)
        .where(AutomationExecution.organization_id == organization_id)
        .where(AutomationExecution.created_at >= window_start)
        .where(AutomationExecution.created_at < window_end)
        .order_by(
            AutomationExecution.created_at.asc(), AutomationExecution.id.asc()
        )
        .limit(limit)
    )
    rows: list[dict[str, Any]] = []
    for run in db.execute(stmt).scalars():
        rows.append(
            {
                "execution_id": str(run.id),
                "organization_id": str(run.organization_id),
                "workspace_id": _s(run.workspace_id),
                "rule_id": _s(run.rule_id),
                "work_item_id": _s(run.work_item_id),
                "correlation_id": _s(run.correlation_id),
                "status": str(getattr(run.status, "value", run.status)),
                "depth": int(run.depth or 0),
                "started_at": _iso(run.started_at),
                "completed_at": _iso(run.completed_at),
                "node_count": int(run.node_count or 0),
                "nodes_executed": int(run.nodes_executed or 0),
                "actions_executed": int(run.actions_executed or 0),
                "budget_cost_micros": int(run.budget_cost_micros or 0),
                "spent_cost_micros": int(run.spent_cost_micros or 0),
                "has_error": run.error is not None,
            }
        )
    return rows


def _day(value: Any) -> Optional[datetime]:
    """A date as midnight UTC, the only way a DATE reaches a Parquet timestamp without a locale."""
    if value is None:
        return None
    return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)


def extract_gst_matches(
    db: Session,
    *,
    organization_id: uuid.UUID,
    window_start: datetime,
    window_end: datetime,
    limit: int = MAX_ROWS_PER_DATASET,
) -> list[dict[str, Any]]:
    from app.models.gst import GstMatch
    from app.services.gst import ims

    stmt = (
        select(GstMatch)
        .join(Workspace, Workspace.id == GstMatch.workspace_id)
        .where(GstMatch.organization_id == organization_id)
        .where(Workspace.is_sample.is_(False))
        .where(GstMatch.computed_at >= window_start)
        .where(GstMatch.computed_at < window_end)
        .order_by(GstMatch.computed_at.asc(), GstMatch.id.asc())
        .limit(limit)
    )
    rows: list[dict[str, Any]] = []
    for match in db.execute(stmt).scalars():
        risk = match.risk if isinstance(match.risk, dict) else {}
        # Unpaid age as of the end of the window, so a re-run of the same window writes the same figure.
        age = None if risk.get("paid") else ims.age_days(risk, window_end.astimezone(timezone.utc).date())
        rows.append(
            {
                "match_id": str(match.id),
                "organization_id": str(match.organization_id),
                "workspace_id": _s(match.workspace_id),
                "gstin": match.gstin,
                "supplier_gstin": match.supplier_gstin,
                "record_id": _s(match.record_id),
                "work_item_id": _s(match.work_item_id),
                "status": match.status,
                "method": match.method,
                "document_number": match.doc_number,
                "document_date": _day(match.doc_date),
                "value_micros": match.value_micros,
                "tax_micros": match.tax_micros,
                "claimable_micros": match.itc_micros,
                "difference_count": len(match.differences or []),
                "ims_action": match.ims_action,
                "decision": match.decision,
                "reported_late": bool(match.reported_late),
                "period_first_seen": match.period_first_seen,
                "days_unpaid": age,
                "computed_at": _iso(match.computed_at),
                # supplier_name, ims_reason, differences and notes are deliberately absent. See the spec.
            }
        )
    return rows


def extract_helm_ledger(
    db: Session,
    *,
    organization_id: uuid.UUID,
    window_start: datetime,
    window_end: datetime,
    limit: int = MAX_ROWS_PER_DATASET,
) -> list[dict[str, Any]]:
    from app.models.helm import HelmPromise

    stmt = (
        select(HelmPromise)
        .join(Workspace, Workspace.id == HelmPromise.workspace_id)
        .where(HelmPromise.organization_id == organization_id)
        .where(Workspace.is_sample.is_(False))
        .where(HelmPromise.updated_at >= window_start)
        .where(HelmPromise.updated_at < window_end)
        .order_by(HelmPromise.updated_at.asc(), HelmPromise.id.asc())
        .limit(limit)
    )
    rows: list[dict[str, Any]] = []
    for promise in db.execute(stmt).scalars():
        rows.append(
            {
                "promise_id": str(promise.id),
                "organization_id": str(promise.organization_id),
                "workspace_id": _s(promise.workspace_id),
                "work_item_id": _s(promise.work_item_id),
                "obligation_id": _s(promise.obligation_id),
                "kind": promise.kind,
                "direction": promise.direction,
                "counterparty_key": promise.counterparty_key,
                "currency": promise.currency,
                "amount_micros": promise.amount_micros,
                "due_date": _day(promise.due_date),
                "window_end": _day(promise.window_end),
                "status": promise.status,
                "confidence": promise.confidence,
                "fulfilment_count": len(promise.fulfilments or []),
                "engine_version": promise.engine_version,
                "created_at": _iso(promise.created_at),
                "updated_at": _iso(promise.updated_at),
                # counterparty_name, title, terms, evidence and details are deliberately absent. See the spec.
            }
        )
    return rows


def extract_trinetra_cases(
    db: Session,
    *,
    organization_id: uuid.UUID,
    window_start: datetime,
    window_end: datetime,
    limit: int = MAX_ROWS_PER_DATASET,
) -> list[dict[str, Any]]:
    """Cases opened or decided on in the window, across the organization's own workspaces. Nothing unless TRINETRA is live for the
    organization (the same `live_for` as every gate). Statuses are computed through the service's batched case views."""
    from sqlalchemy import func

    from app.models.trinetra import TrinetraCredit, TrinetraDecision
    from app.services.trinetra import directory, mode, service

    if not mode.live_for(db, organization_id):
        return []
    latest = (
        select(TrinetraDecision.credit_id.label("credit_id"), func.max(TrinetraDecision.created_at).label("at"))
        .where(TrinetraDecision.organization_id == organization_id)
        .group_by(TrinetraDecision.credit_id)
        .subquery()
    )
    changed = func.greatest(TrinetraCredit.created_at, func.coalesce(latest.c.at, TrinetraCredit.created_at))
    stmt = (
        select(TrinetraCredit, changed.label("changed"))
        .join(Workspace, Workspace.id == TrinetraCredit.workspace_id)
        .outerjoin(latest, latest.c.credit_id == TrinetraCredit.id)
        .where(TrinetraCredit.organization_id == organization_id)
        .where(Workspace.is_sample.is_(False))
        .where(changed >= window_start)
        .where(changed < window_end)
        .order_by(changed.asc(), TrinetraCredit.id.asc())
        .limit(limit)
    )
    found = db.execute(stmt).all()
    by_workspace: dict[uuid.UUID, list[Any]] = {}
    for credit, _changed in found:
        by_workspace.setdefault(credit.workspace_id, []).append(credit)
    views: dict[str, dict[str, Any]] = {}
    for workspace_id, credits in by_workspace.items():
        workspace = db.get(Workspace, workspace_id)
        for chunk in range(0, len(credits), 500):
            for item in service.views(db, workspace, credits[chunk : chunk + 500])[0]:
                views[item["id"]] = item
    rows: list[dict[str, Any]] = []
    for credit, at in found:
        item = views[str(credit.id)]
        rows.append(
            {
                "case_id": str(credit.id),
                "organization_id": str(credit.organization_id),
                "workspace_id": _s(credit.workspace_id),
                "profile_id": _s(credit.profile_id),
                "work_item_id": _s(credit.work_item_id),
                "customer_key": directory.name_key(credit.counterparty),
                "year": credit.year,
                "revision": credit.revision,
                "review_state": credit.state,
                "status": item["status"],
                "currency": "INR",
                "expected_micros": item["expected_micros"],
                "posted_micros": item["posted_micros"],
                "gap_micros": item["gap_micros"],
                "source_current": bool(item["source_current"]),
                "age_days": item["age_days"],
                "created_at": _iso(credit.created_at),
                "updated_at": _iso(at),
                # counterparty, reference, deductor_key, review (notes) and every PAN or TAN are deliberately absent. See the spec.
            }
        )
    return rows


EXTRACTORS: dict[str, Callable[..., list[dict[str, Any]]]] = {
    "USAGE_ROLLUPS": extract_usage_rollups,
    "DOCUMENT_METADATA": extract_document_metadata,
    "ASSISTANT_TURNS": extract_assistant_turns,
    "AUTOMATION_RUNS": extract_automation_runs,
    "GST_MATCHES": extract_gst_matches,
    "HELM_LEDGER": extract_helm_ledger,
    "TRINETRA_CASES": extract_trinetra_cases,
}


def extract_dataset(
    db: Session,
    dataset: str,
    *,
    organization_id: uuid.UUID,
    window_start: datetime,
    window_end: datetime,
    limit: int = MAX_ROWS_PER_DATASET,
) -> list[dict[str, Any]]:
    try:
        extractor = EXTRACTORS[dataset]
    except KeyError as exc:
        raise ExportEngineError(
            f"Unknown dataset {dataset!r}. Known: {sorted(EXTRACTORS)}."
        ) from exc
    return extractor(
        db,
        organization_id=organization_id,
        window_start=window_start,
        window_end=window_end,
        limit=limit,
    )


# ---------------------------------------------------------------------------
# Parquet
# ---------------------------------------------------------------------------


def _arrow_schema(spec: DatasetSpec) -> Any:
    """Build the pyarrow schema for one spec.

    Imports pyarrow. Callers that only want the column list use
    `spec.column_names` instead and stay pyarrow-free.
    """
    try:
        import pyarrow as pa
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise ParquetUnavailableError(
            "pyarrow is not installed. ARCH-26 pins it in "
            "backend/requirements.txt; this image predates that pin or was "
            "built without it."
        ) from exc

    mapping = {
        "string": pa.string(),
        "int64": pa.int64(),
        "double": pa.float64(),
        "bool": pa.bool_(),
        "timestamp": pa.timestamp("us", tz="UTC"),
    }
    fields = []
    for column in spec.columns:
        try:
            arrow_type = mapping[column.arrow_type]
        except KeyError as exc:
            raise ExportEngineError(
                f"Column {spec.dataset}.{column.name} declares unknown arrow "
                f"type {column.arrow_type!r}."
            ) from exc
        # Every field is nullable. A NOT NULL Parquet column forces the writer
        # to invent a value where the source had none, which is invariant 6
        # violated at the file format layer.
        fields.append(pa.field(column.name, arrow_type, nullable=True))
    return pa.schema(fields)


def write_parquet(rows: Sequence[dict[str, Any]], spec: DatasetSpec) -> bytes:
    """Serialise rows to a Parquet file in memory.

    Returns the bytes rather than a path: the caller digests them and uploads
    them, and a temporary file between those two steps is one more place the
    bytes can differ from the bytes we hashed.
    """
    forbidden: set[str] = set()
    for row in rows:
        forbidden |= set(row) & FORBIDDEN_COLUMN_NAMES
    if forbidden:
        raise ForbiddenColumnError(
            f"Refusing to write {spec.dataset}: rows carry forbidden "
            f"column(s) {sorted(forbidden)}. Supplier cost never leaves the "
            "platform (ARCH-26 invariant I1)."
        )

    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise ParquetUnavailableError(
            "pyarrow is not installed. ARCH-26 pins it in "
            "backend/requirements.txt."
        ) from exc

    schema = _arrow_schema(spec)
    columns: dict[str, list[Any]] = {name: [] for name in spec.column_names}
    for row in rows:
        for name in spec.column_names:
            columns[name].append(row.get(name))

    table = pa.Table.from_pydict(
        {name: columns[name] for name in spec.column_names}, schema=schema
    )

    sink = io.BytesIO()
    # Deterministic settings. `store_schema=False` would shrink the file and
    # break the digest's reproducibility across pyarrow versions; snappy is
    # the one codec all four destinations read without configuration.
    pq.write_table(
        table,
        sink,
        compression="snappy",
        version="2.6",
        write_statistics=True,
    )
    return sink.getvalue()


def digest_bytes(payload: bytes) -> str:
    """SHA-256, lowercase hex. The same primitive ARCH-15 uses on invoices."""
    return hashlib.sha256(payload).hexdigest()


def bundle_digest(part_digests: Sequence[str]) -> str:
    """One digest over a set of parts, order-independent.

    Sorted before hashing so that two runs producing the same parts in a
    different order produce the same bundle digest. An order-dependent digest
    would make the receipt depend on dictionary iteration order, which is a
    property of the Python build and not of the data.
    """
    joined = "\n".join(sorted(part_digests)).encode("utf-8")
    return hashlib.sha256(joined).hexdigest()


@dataclass(frozen=True)
class ExportPart:
    dataset: str
    version: int
    row_count: int
    byte_count: int
    sha256: str
    storage_key: str
    truncated: bool


def build_manifest(
    *,
    run_id: uuid.UUID,
    organization_id: uuid.UUID,
    window_start: datetime,
    window_end: datetime,
    parts: Sequence[ExportPart],
    generated_at: Optional[datetime] = None,
) -> dict[str, Any]:
    """The JSON document that ties a bundle together.

    Mirrors ARCH-15's invoice manifest discipline: the digest of every part,
    plus a digest over the digests, so a tenant can verify the bundle they
    downloaded is the bundle we recorded having sent.
    """
    stamp = generated_at or datetime.now(timezone.utc)
    return {
        "manifest_version": 1,
        "run_id": str(run_id),
        "organization_id": str(organization_id),
        "generated_at": stamp.astimezone(timezone.utc).isoformat(),
        "window_start": _iso(window_start).isoformat(),  # type: ignore[union-attr]
        "window_end": _iso(window_end).isoformat(),  # type: ignore[union-attr]
        "digest_algorithm": "sha256",
        "bundle_digest": bundle_digest([part.sha256 for part in parts]),
        "parts": [
            {
                "dataset": part.dataset,
                "schema_version": part.version,
                "storage_key": part.storage_key,
                "row_count": part.row_count,
                "byte_count": part.byte_count,
                "sha256": part.sha256,
                "truncated": part.truncated,
            }
            for part in sorted(parts, key=lambda p: p.dataset)
        ],
        "excluded_columns": sorted(FORBIDDEN_COLUMN_NAMES),
        "exclusion_reason": (
            "Supplier cost basis is withheld from tenant-facing exports "
            "(ARCH-26 invariant I1)."
        ),
    }


def dataset_descriptors() -> list[dict[str, Any]]:
    """Every dataset's column list, for the docs endpoint."""
    return [
        DATASET_SPECS[name].as_descriptor() for name in sorted(DATASET_SPECS)
    ]


__all__ = [
    "ASSISTANT_TURNS_SPEC",
    "AUTOMATION_RUNS_SPEC",
    "ColumnSpec",
    "DATASET_SCHEMA_VERSIONS",
    "DATASET_SPECS",
    "DOCUMENT_METADATA_SPEC",
    "DatasetSpec",
    "DATASET_CAPABILITY",
    "EXTRACTORS",
    "ExportEngineError",
    "ExportPart",
    "FORBIDDEN_COLUMN_NAMES",
    "ForbiddenColumnError",
    "GST_MATCHES_SPEC",
    "HELM_LEDGER_SPEC",
    "MAX_ROWS_PER_DATASET",
    "ParquetUnavailableError",
    "USAGE_ROLLUPS_SPEC",
    "build_manifest",
    "bundle_digest",
    "dataset_descriptors",
    "digest_bytes",
    "extract_assistant_turns",
    "extract_automation_runs",
    "extract_dataset",
    "extract_document_metadata",
    "extract_gst_matches",
    "extract_helm_ledger",
    "extract_trinetra_cases",
    "extract_usage_rollups",
    "write_parquet",
]
