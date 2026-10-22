"""Taking a zip into the product (Final session 1, 2A).

A customer with a backlog drops one archive on day one. This module is the single door for it, used by the upload route and
by email-in (a zip attached to a forwarded message): it refuses what can never work *now*, with a sentence, stores the zip
for the worker, opens a batch whose only item is the archive, and queues `batch.expand_archive`. The worker unpacks it and
ingests every document through the ordinary intake path, so plan limits, file checks, processing, GST, Helm and the value
receipt all apply unchanged.

What is refused here, before anything is stored (the same limits the worker enforces again against what it really reads):
a trial that has ended, an allowance already used up, a zip that is not a zip, password-protected, nested, too many files,
too large when unpacked, a compression bomb, a path that escapes (`../`, absolute), a symbolic link.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.storage import StorageNamespace, get_storage_driver, tenant_key
from app.models.audit_log import AuditAction, AuditOutcome, AuditResourceType
from app.models.ingestion import IngestionBatch
from app.services import audit_service, job_service, plan_admission, trial_service
from app.services.ingestion import archive, batch_service

logger = logging.getLogger("app.services.ingestion.archive_intake")

JOB_TYPE = "batch.expand_archive"


class ArchiveNotAccepted(Exception):
    """The zip was refused before anything was stored. `code` is one of `archive.REJECTION_CODES` or ZIP_TOO_BIG."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def max_upload_bytes() -> int:
    return int(settings.ZIP_UPLOAD_MAX_MB) * 1024 * 1024


def is_zip(filename: Optional[str], head: bytes) -> bool:
    return bool(head[:4] in (b"PK\x03\x04", b"PK\x05\x06")) or (filename or "").lower().endswith(".zip")


def accept_archive(
    db: Session,
    *,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
    user_id: Optional[uuid.UUID],
    filename: str,
    data: bytes,
    source: Optional[dict[str, Any]] = None,
) -> IngestionBatch:
    """Refuse or accept one zip. On acceptance the batch exists and the worker will unpack it; nothing is half-added."""
    if len(data) > max_upload_bytes():
        raise ArchiveNotAccepted(
            "ZIP_TOO_BIG",
            f"The zip is larger than {settings.ZIP_UPLOAD_MAX_MB} MB. Split it into smaller zips.",
        )
    # An ended trial or a used-up allowance is a refusal now, not a surprise after the unpacking.
    trial_service.assert_trial_active(db, organization_id=organization_id)
    plan_admission.precheck_document(db, organization_id=organization_id, size_bytes=1, page_count=None)
    try:
        archive.inspect(data, depth=1)
    except archive.ArchiveRejected as exc:
        raise ArchiveNotAccepted(exc.code, exc.message) from exc

    name = (filename or "archive.zip").strip()[:255] or "archive.zip"
    digest = hashlib.sha256(data).hexdigest()
    batch = batch_service.create_batch(
        db,
        workspace_id=workspace_id,
        user_id=user_id,
        source="ARCHIVE",
        files=[{"client_key": f"archive:{uuid.uuid4().hex}", "filename": name, "size_bytes": len(data), "sha256": digest}],
    )
    item = batch_service.list_items(db, workspace_id=workspace_id, batch_id=batch.id)[0]

    driver = get_storage_driver()
    key = tenant_key(organization_id=organization_id, namespace=StorageNamespace.DERIVED, file_id=uuid.uuid4(), suffix="zip")
    driver.put(key, data, "application/zip")
    try:
        batch_service.mark_item_uploaded(db, item=item, upload_session_id=None, sha256=digest)
        batch.status = "PROCESSING"
        job_service.enqueue(
            db,
            job_type=JOB_TYPE,
            payload={
                "batch_id": str(batch.id),
                "item_id": str(item.id),
                "workspace_id": str(workspace_id),
                "organization_id": str(organization_id),
                "storage_key": key,
                "uploader_id": str(user_id) if user_id else None,
                "source": source,
            },
            organization_id=organization_id,
            idempotency_key=f"{JOB_TYPE}:{item.id}",
        )
        audit_service.record(
            db,
            organization_id=organization_id,
            workspace_id=workspace_id,
            resource_type=AuditResourceType.INGESTION_BATCH,
            resource_id=batch.id,
            action=AuditAction.CREATED,
            outcome=AuditOutcome.ALLOWED,
            details={"source": "ARCHIVE", "size_bytes": len(data), "by": (source or {}).get("kind", "upload")},
        )
    except Exception:
        driver.delete(key)
        raise
    # Not a column: lets a caller that rolls the batch back (email-in holding a whole message) delete the stored zip too.
    batch.archive_storage_key = key  # type: ignore[attr-defined]
    return batch


__all__ = ["ArchiveNotAccepted", "JOB_TYPE", "accept_archive", "is_zip", "max_upload_bytes"]
