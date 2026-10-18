"""Where the Promise ledger learns that something it reads has changed (Session B).

The ledger no longer recomputes a workspace when one document changes: it re-projects the documents
marked here, and what depends on them. So the marking has to be complete, and the most reliable place
to do it is where the data is written, not in each of the many callers: the mapper events below fire
on every ORM write to a table the ledger reads, in the same transaction as the write (a rolled-back
change leaves no mark; a committed change always has one).

  mark(ids)            "this document (or this obligation, or this payment's invoice) changed"
  request_full(...)    "something every promise depends on changed (who we are, the workspace's date
                       format and currency, the price tolerance, which books read the workspace)":
                       the next update is a full rebuild

Both do nothing unless some active Helm book reads the workspace, so a tenant without Helm pays one
cheap `EXISTS` per write and keeps no marks. Writes that bypass the ORM (a bulk `UPDATE`) are not seen;
the nightly full rebuild catches them and says so (`ledger_store.verify_workspace`).
"""

from __future__ import annotations

import uuid
from typing import Iterable, Optional, Sequence

from sqlalchemy import event, text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import attributes

from app.models.document_role import DocumentRole
from app.models.helm import HelmBook, HelmSettings, HelmSettlement
from app.models.obligations import Obligation
from app.models.procurement import ProcurementCase, ProcurementCaseLine, ProcurementTolerancePolicy
from app.models.verification import DocumentVerification
from app.models.work_item import WorkItem
from app.models.work_item_field_correction import WorkItemFieldCorrection
from app.models.workspace import Workspace

#: Some active book reads the workspace: its own, or an organization's (which reads them all).
_READ_BY_A_BOOK = (
    "EXISTS (SELECT 1 FROM helm_books b WHERE b.organization_id = w.organization_id AND b.status = 'ACTIVE' "
    "AND (b.workspace_id = w.id OR b.workspace_id IS NULL))"
)

#: What a document's stored promises said before the change: the amounts an invoice could have taken a
#: bank line for (what was owed, what was paid), and its invoice number. Read when the first change is
#: marked, while the promises still exist (a deleted document takes them along).
_OLD_STATE = """
    ARRAY(SELECT DISTINCT m FROM (
        SELECT p.amount_micros AS m FROM helm_promises p
         WHERE p.work_item_id = subject AND p.workspace_id = w.id AND p.kind IN ('PAYMENT_DUE', 'PAYMENT_EXPECTED')
        UNION SELECT (p.details ->> 'gross_micros')::bigint FROM helm_promises p
         WHERE p.work_item_id = subject AND p.workspace_id = w.id AND p.kind IN ('PAYMENT_DUE', 'PAYMENT_EXPECTED')
        UNION SELECT (f ->> 'amount_micros')::bigint FROM helm_promises p, jsonb_array_elements(p.fulfilments) f
         WHERE p.work_item_id = subject AND p.workspace_id = w.id AND p.kind IN ('PAYMENT_DUE', 'PAYMENT_EXPECTED')
    ) x WHERE m IS NOT NULL AND m > 0),
    ARRAY(SELECT DISTINCT p.details ->> 'document_number' FROM helm_promises p
           WHERE p.work_item_id = subject AND p.workspace_id = w.id AND p.kind IN ('PAYMENT_DUE', 'PAYMENT_EXPECTED')
             AND p.details ->> 'document_number' IS NOT NULL)
"""

_MERGE = """
    ON CONFLICT (workspace_id, work_item_id) DO UPDATE SET
        marks = helm_ledger_dirty.marks + 1, reason = EXCLUDED.reason, marked_at = now(),
        claims = ARRAY(SELECT DISTINCT unnest(helm_ledger_dirty.claims || EXCLUDED.claims)),
        numbers = ARRAY(SELECT DISTINCT unnest(helm_ledger_dirty.numbers || EXCLUDED.numbers))
"""

_MARK = text(
    f"""
    INSERT INTO helm_ledger_dirty (workspace_id, organization_id, work_item_id, reason, claims, numbers)
    SELECT DISTINCT w.id, w.organization_id, subject, :reason, {_OLD_STATE}
    FROM workspaces w, unnest(CAST(:ids AS uuid[])) AS subject
    WHERE w.id = :workspace_id AND {_READ_BY_A_BOOK}
    {_MERGE}
    """
)

_REQUEST_FULL = (
    "INSERT INTO helm_ledger_state (workspace_id, organization_id, full_requests) "
    "SELECT w.id, w.organization_id, 1 FROM workspaces w WHERE {where} AND " + _READ_BY_A_BOOK + " "
    "ON CONFLICT (workspace_id) DO UPDATE SET full_requests = helm_ledger_state.full_requests + 1, updated_at = now()"
)
_REQUEST_FULL_WORKSPACE = text(_REQUEST_FULL.format(where="w.id = :scope"))
_REQUEST_FULL_ORGANIZATION = text(_REQUEST_FULL.format(where="w.organization_id = :scope"))

#: The obligations of a document about to be deleted: they outlive it (the link is cleared), and their
#: promises, which named the document, go with it. Marked by their own ids, so they are re-projected.
_MARK_OBLIGATIONS_OF = text(
    f"""
    INSERT INTO helm_ledger_dirty (workspace_id, organization_id, work_item_id, reason)
    SELECT w.id, w.organization_id, o.id, :reason
    FROM obligations o JOIN workspaces w ON w.id = o.workspace_id
    WHERE o.work_item_id = ANY(CAST(:ids AS uuid[])) AND {_READ_BY_A_BOOK}
    {_MERGE.replace('helm_ledger_dirty.claims || EXCLUDED.claims', "helm_ledger_dirty.claims || '{}'::bigint[]")
           .replace('helm_ledger_dirty.numbers || EXCLUDED.numbers', "helm_ledger_dirty.numbers || '{}'::text[]")}
    """
)

#: The other documents of the procurement cases that name a document about to be deleted: the cases go with
#: it (a foreign key), and what they said about the others (a receipt's date, a price) goes too.
_MARK_CASES_OF = text(
    f"""
    INSERT INTO helm_ledger_dirty (workspace_id, organization_id, work_item_id, reason)
    SELECT DISTINCT w.id, w.organization_id, subject, :reason
    FROM procurement_cases c
    JOIN workspaces w ON w.id = c.workspace_id,
         unnest(ARRAY[c.po_work_item_id, c.invoice_work_item_id, c.receipt_work_item_id]) AS subject
    WHERE c.workspace_id = :workspace_id AND c.status <> 'SUPERSEDED' AND subject IS NOT NULL
      AND :work_item_id IN (c.po_work_item_id, c.invoice_work_item_id, c.receipt_work_item_id) AND {_READ_BY_A_BOOK}
    {_MERGE.replace('helm_ledger_dirty.claims || EXCLUDED.claims', "helm_ledger_dirty.claims || '{}'::bigint[]")
           .replace('helm_ledger_dirty.numbers || EXCLUDED.numbers', "helm_ledger_dirty.numbers || '{}'::text[]")}
    """
)

#: A case's three documents, marked from the case row (a line knows only its case).
_MARK_CASE = text(
    f"""
    INSERT INTO helm_ledger_dirty (workspace_id, organization_id, work_item_id, reason, claims, numbers)
    SELECT DISTINCT w.id, w.organization_id, subject, :reason, {_OLD_STATE}
    FROM procurement_cases c
    JOIN workspaces w ON w.id = c.workspace_id,
         unnest(ARRAY[c.po_work_item_id, c.invoice_work_item_id, c.receipt_work_item_id]) AS subject
    WHERE c.id = :case_id AND subject IS NOT NULL AND {_READ_BY_A_BOOK}
    {_MERGE}
    """
)

_PRESENT = False


def _ready(connection: Connection) -> bool:
    """The two tables exist (they do not while migrations older than h1a5 run). Checked until it is true."""
    global _PRESENT
    if not _PRESENT:
        _PRESENT = bool(connection.execute(text("SELECT to_regclass('helm_ledger_dirty') IS NOT NULL "
                                                "AND to_regclass('helm_ledger_state') IS NOT NULL")).scalar())
    return _PRESENT


def mark(connection: Connection, workspace_id: Optional[uuid.UUID], subjects: Iterable[Optional[uuid.UUID]],
         reason: str) -> None:
    ids = sorted({str(s) for s in subjects if s is not None})
    if workspace_id is None or not ids or not _ready(connection):
        return
    connection.execute(_MARK, {"workspace_id": workspace_id, "ids": ids, "reason": reason[:60]})


def mark_obligations_of(connection: Connection, work_item_ids: Iterable[uuid.UUID], reason: str) -> None:
    """Mark the obligations of these documents (for a caller about to change them without the ORM)."""
    ids = sorted({str(i) for i in work_item_ids})
    if ids and _ready(connection):
        connection.execute(_MARK_OBLIGATIONS_OF, {"ids": ids, "reason": reason[:60]})


def request_full(connection: Connection, *, workspace_id: Optional[uuid.UUID] = None,
                 organization_id: Optional[uuid.UUID] = None) -> None:
    if not _ready(connection):
        return
    if workspace_id is not None:
        connection.execute(_REQUEST_FULL_WORKSPACE, {"scope": workspace_id})
    elif organization_id is not None:
        connection.execute(_REQUEST_FULL_ORGANIZATION, {"scope": organization_id})


def _changed(target: object, *names: str) -> bool:
    return any(attributes.get_history(target, name).has_changes() for name in names)


# ---- what is marked, per table ----------------------------------------------------------------------


def _document_row(_mapper: object, connection: Connection, target: object) -> None:
    mark(connection, target.workspace_id, [target.work_item_id], f"{target.__tablename__} changed")


def _obligation(_mapper: object, connection: Connection, target: Obligation) -> None:
    # By its own id: it may belong to no document. The ledger re-reads the document's other promises
    # only when the document itself changes.
    mark(connection, target.workspace_id, [target.id], "obligation changed")


def _work_item_changed(_mapper: object, connection: Connection, target: WorkItem) -> None:
    if _changed(target, "extracted_entities", "pipeline_stage", "extracted_text", "original_filename"):
        mark(connection, target.workspace_id, [target.id], "document changed")


def _work_item_deleting(_mapper: object, connection: Connection, target: WorkItem) -> None:
    # Before the delete: the document's promises (and what they said) go with it, and are read now.
    mark(connection, target.workspace_id, [target.id], "document deleted")
    if _ready(connection):
        mark_obligations_of(connection, [target.id], "document deleted")
        connection.execute(_MARK_CASES_OF, {"workspace_id": target.workspace_id, "work_item_id": target.id,
                                            "reason": "document deleted"})


def _case(_mapper: object, connection: Connection, target: ProcurementCase) -> None:
    mark(connection, target.workspace_id,
         [target.po_work_item_id, target.invoice_work_item_id, target.receipt_work_item_id], "match changed")


def _case_line(_mapper: object, connection: Connection, target: ProcurementCaseLine) -> None:
    if _ready(connection):
        connection.execute(_MARK_CASE, {"case_id": target.case_id, "reason": "match line changed"})


def _workspace_changed(_mapper: object, connection: Connection, target: Workspace) -> None:
    if _changed(target, "date_format", "currency"):
        request_full(connection, workspace_id=target.id)


def _tolerance(_mapper: object, connection: Connection, target: ProcurementTolerancePolicy) -> None:
    request_full(connection, workspace_id=target.workspace_id)


def _organization_wide(_mapper: object, connection: Connection, target: object) -> None:
    request_full(connection, organization_id=target.organization_id)


def _register() -> None:
    for model in (DocumentRole, DocumentVerification, WorkItemFieldCorrection, HelmSettlement):
        for name in ("after_insert", "after_update", "after_delete"):
            event.listen(model, name, _document_row)
    for name in ("after_insert", "after_update", "after_delete"):
        event.listen(Obligation, name, _obligation)
        event.listen(ProcurementCase, name, _case)
        event.listen(ProcurementCaseLine, name, _case_line)
        event.listen(ProcurementTolerancePolicy, name, _tolerance)
        event.listen(HelmSettings, name, _organization_wide)
        event.listen(HelmBook, name, _organization_wide)
    event.listen(WorkItem, "after_update", _work_item_changed)
    event.listen(WorkItem, "before_delete", _work_item_deleting)
    event.listen(Workspace, "after_update", _workspace_changed)


_register()

__all__: Sequence[str] = ("mark", "mark_obligations_of", "request_full")
