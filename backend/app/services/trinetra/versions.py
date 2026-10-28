"""What a document IS, for TRINETRA: a fingerprint of the evidence, not of the row (Final 2T, Phase 1.2).

`work_items.updated_at` moves on any update (a rename, a summary set by an automation, batch healing, a reprocess that
yields the same fields). Using it as the "version" made harmless touches stale a confirmed expectation and made a whole
statement snapshot unusable. A document's version is now a hash of:

- the stored file (the upload's checksum when there is one, else the stored name, size and type);
- the extracted fields TRINETRA reads (`FIELDS`), not the whole extraction;
- for an invoice or a piece of evidence, the DocumentRole facts: role, total, currency and date.

A statement is versioned by its stored file alone. A correction to a field, a different file or a changed total
changes the fingerprint; nothing else does. The `v2:` prefix tells it from the legacy updated_at stamps."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from typing import Iterable, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.document_role import DocumentRole
from app.models.uploaded_file import UploadedFile
from app.models.work_item import WorkItem
from app.services.helm import identity as ident

SCHEME = "v2"
#: A legacy stamp that was already stale when the data was migrated: it never matches, so a person reconfirms.
STALE = "v2:stale-before-migration"

#: The extracted fields TRINETRA reads from an invoice or a piece of evidence (seller and buyer identity, PAN, TAN,
#: printed TDS hints and the amounts and dates a reviewer compares).
FIELDS: tuple[str, ...] = tuple(sorted({
    *ident.SELLER_NAME_KEYS, *ident.SELLER_TAX_KEYS, *ident.BUYER_NAME_KEYS, *ident.BUYER_TAX_KEYS,
    "vendor_pan", "seller_pan", "buyer_pan", "deductor_tan", "tds_amount", "tds_section", "tds_rate",
    "invoice_number", "invoice_date", "due_date", "total_amount", "subtotal", "tax_amount", "currency",
    "certificate_number", "challan_number", "amount", "date", "financial_year", "assessment_year", "tax_year",
}))


def _hash(*parts) -> str:
    # 48 hex characters (192 bits) keep "v2:" plus the digest inside the 64-character version columns.
    return SCHEME + ":" + hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()[:48]


@dataclass(frozen=True)
class Facts:
    """The three parts of a document's identity, each already hashed; a version combines the parts it needs."""

    file: str
    fields: str
    role: str

    @property
    def invoice(self) -> str:
        return _hash("invoice", self.file, self.fields, self.role)

    @property
    def evidence(self) -> str:
        return _hash("evidence", self.file, self.fields, self.role)

    @property
    def statement(self) -> str:
        return _hash("statement", self.file)


def _file_part(item_row, checksum: Optional[str]) -> str:
    if checksum:
        return _hash("sha256", checksum)
    return _hash("file", item_row.stored_filename, item_row.file_size, item_row.file_type)


def _fields_part(entities) -> str:
    values = entities if isinstance(entities, dict) else {}
    return _hash("fields", {k: values.get(k) for k in FIELDS if values.get(k) is not None})


def _role_part(role) -> str:
    if role is None:
        return _hash("role", None)
    return _hash("role", role.role, role.total_micros, role.currency,
                 role.document_date.isoformat() if role.document_date else None)


def load(db: Session, workspace_ids, ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, Facts]:
    """One batched read for any number of documents of these workspaces: id -> Facts (a missing id is absent)."""
    ids = list(set(ids))
    if not ids:
        return {}
    if isinstance(workspace_ids, uuid.UUID):
        workspace_ids = [workspace_ids]
    rows = db.execute(
        select(WorkItem.id, WorkItem.stored_filename, WorkItem.file_size, WorkItem.file_type,
               WorkItem.extracted_entities, UploadedFile.checksum_sha256)
        .outerjoin(UploadedFile, UploadedFile.id == WorkItem.uploaded_file_id)
        .where(WorkItem.id.in_(ids), WorkItem.workspace_id.in_(list(workspace_ids)))
    ).all()
    roles = {r.work_item_id: r for r in db.execute(
        select(DocumentRole).where(DocumentRole.work_item_id.in_([r.id for r in rows]),
                                   DocumentRole.workspace_id.in_(list(workspace_ids)))).scalars()}
    return {r.id: Facts(_file_part(r, r.checksum_sha256), _fields_part(r.extracted_entities), _role_part(roles.get(r.id)))
            for r in rows}


def one(db: Session, workspace_id: uuid.UUID, item_id: uuid.UUID) -> Optional[Facts]:
    return load(db, workspace_id, [item_id]).get(item_id)
