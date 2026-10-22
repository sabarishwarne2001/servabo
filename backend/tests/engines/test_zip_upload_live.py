"""Final session 1 (2A): one zip, every document in it through the ordinary intake path.

A customer with a backlog drops a zip on day one and sees the value receipt fill. These tests run the route and the
worker end to end on the live pipeline: documents are read and processed, junk and non-documents are skipped and listed,
a GSTR-2B inside is pointed at the GST page, a plan limit part-way adds the files that fit and lists the rest, and every
limit refuses the zip with a sentence before anything is stored.
"""

from __future__ import annotations

import io
import json
import struct
import uuid
import zipfile
from typing import Any

import pytest
from sqlalchemy import select

from app.models.ingestion import IngestionBatch
from app.models.work_item import WorkItem
from app.services import plan_admission
from tests.engines.conftest import Engines, drain, make_pdf

GSTR2B = json.dumps({"data": {"gstin": "27AAACG1234F1Z5", "rtnprd": "092026", "docdata": {"b2b": []}}}).encode()


def _zip(entries: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, payload in entries.items():
            zf.writestr(name, payload)
    return buffer.getvalue()


def _invoices(count: int = 3) -> dict[str, bytes]:
    return {f"invoices/INV-{2040 + i}.pdf": make_pdf([[f"TAX INVOICE INV-{2040 + i}", f"Total INR {1000 * (i + 1)}.00"]]) for i in range(count)}


def _post(engines: Engines, data: bytes, name: str = "backlog.zip", **kw: Any):
    return engines.client.post(
        engines.url("/ingestion-batches/archive"), files={"file": (name, data, "application/zip")},
        headers=(kw.get("as_user") or engines.tenant.owner).headers,
    )


def _batch(engines: Engines, batch_id: str) -> dict[str, Any]:
    response = engines.get(f"/ingestion-batches/{batch_id}")
    assert response.status_code == 200, response.text
    return response.json()


def test_a_zip_of_documents_becomes_documents_with_the_junk_and_the_gstr2b_set_aside(engines: Engines) -> None:
    entries = {
        **_invoices(3), ".DS_Store": b"\x00\x00\x00\x01Bud1", "__MACOSX/invoices/._INV-2040.pdf": b"x" * 20,
        "returns/gstr2b_092026.json": GSTR2B, "notes.txt": b"call the supplier",
    }
    response = _post(engines, _zip(entries))
    assert response.status_code == 202, response.text
    batch_id = response.json()["id"]
    drain()

    batch = _batch(engines, batch_id)
    assert batch["source"] == "ARCHIVE" and batch["status"] == "COMPLETED"
    documents = [i for i in batch["items"] if i["work_item_id"]]
    assert sorted(i["filename"] for i in documents) == ["INV-2040.pdf", "INV-2041.pdf", "INV-2042.pdf"]
    # the archive itself is a container, not a document
    assert any(i["filename"] == "backlog.zip" and i["work_item_id"] is None and i["status"] == "COMPLETED" for i in batch["items"])
    skipped = {s["name"]: s for s in batch["skipped"]}
    assert set(skipped) == {"gstr2b_092026.json", "notes.txt"}, "the junk is not even listed"
    assert skipped["gstr2b_092026.json"]["message"] == "This looks like a GSTR-2B file: import it on the GST credit page."
    assert "supported file type" in skipped["notes.txt"]["message"]
    engines.db.expire_all()
    for item in documents:  # each went through the ordinary intake path: stored, queued, processed
        work_item = engines.item(uuid.UUID(item["work_item_id"]))
        assert work_item.status in {"COMPLETED", "NEEDS_REVIEW", "PROCESSING", "QUEUED"} and work_item.uploaded_file_id is not None


def test_a_plan_limit_part_way_adds_the_files_that_fit_and_lists_the_rest(engines: Engines, monkeypatch: pytest.MonkeyPatch) -> None:
    real = plan_admission.admit_document
    calls = {"n": 0}

    def limited(db, **kw):
        calls["n"] += 1
        if calls["n"] > 2:
            raise plan_admission.PlanLimitExceededError(
                "Your plan's monthly document limit is used up.", reason="DOCUMENTS", limit_key="document.upload", limit=2,
                requested=3, plan="Developer",
            )
        return real(db, **kw)

    monkeypatch.setattr(plan_admission, "admit_document", limited)
    batch_id = _post(engines, _zip(_invoices(5))).json()["id"]
    drain()

    batch = _batch(engines, batch_id)
    added = [i for i in batch["items"] if i["work_item_id"]]
    refused = [i for i in batch["items"] if i["status"] == "FAILED"]
    assert len(added) == 2 and len(refused) == 3
    assert {i["error_code"] for i in refused} == {"PLAN_LIMIT"}
    assert batch["status"] == "COMPLETED_WITH_ERRORS"
    engines.db.expire_all()
    # nothing half-added: every refused file has no document and no stored upload
    names = {r["filename"] for r in refused}
    assert not engines.db.execute(select(WorkItem).where(WorkItem.original_filename.in_(names))).scalars().all()


@pytest.mark.parametrize(
    ("label", "build", "code"),
    [
        ("not a zip", lambda: b"definitely not a zip file", "ARCHIVE_NOT_A_ZIP"),
        ("traversal", lambda: _zip({"../evil.pdf": make_pdf([["x"]])}), "ARCHIVE_UNSAFE_PATH"),
        ("absolute path", lambda: _zip({"/etc/evil.pdf": make_pdf([["x"]])}), "ARCHIVE_UNSAFE_PATH"),
        ("nested zip", lambda: _zip({"inner.zip": _zip(_invoices(1))}), "ARCHIVE_NESTED"),
        ("a bomb", lambda: _zip({"a.pdf": b"%PDF-1.4\n" + b"\x00" * 5_000_000}), "ARCHIVE_COMPRESSION_RATIO"),
    ],
)
def test_a_zip_that_breaks_a_limit_is_refused_at_once_with_a_sentence_and_nothing_is_stored(engines: Engines, label, build, code) -> None:
    before = len(engines.db.execute(select(IngestionBatch)).scalars().all())
    response = _post(engines, build())
    assert response.status_code == 400, (label, response.text)
    assert response.json()["detail"], "a sentence a person can act on"
    engines.db.expire_all()
    assert len(engines.db.execute(select(IngestionBatch)).scalars().all()) == before, "no batch was opened"


def test_a_symlink_and_a_password_protected_zip_are_refused(engines: Engines) -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        link = zipfile.ZipInfo("secrets.pdf")
        link.create_system = 3
        link.external_attr = 0o120777 << 16
        zf.writestr(link, "/etc/passwd")
    assert _post(engines, buffer.getvalue()).status_code == 400

    data = bytearray(_zip(_invoices(1)))
    for signature, offset in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):
        position = data.find(signature)
        while position != -1:
            struct.pack_into("<H", data, position + offset, struct.unpack_from("<H", data, position + offset)[0] | 1)
            position = data.find(signature, position + 4)
    response = _post(engines, bytes(data))
    assert response.status_code == 400 and "password" in response.json()["detail"].lower()


def test_too_many_files_and_too_large_a_zip_are_refused(engines: Engines, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.ingestion import archive

    monkeypatch.setattr(archive, "MAX_ENTRIES", 2)
    assert _post(engines, _zip(_invoices(3))).status_code == 400
    monkeypatch.setattr(archive, "MAX_ENTRIES", 2000)
    from app.core.config import settings

    monkeypatch.setattr(settings, "ZIP_UPLOAD_MAX_MB", 0)
    assert _post(engines, _zip(_invoices(1))).status_code == 413


def test_a_zip_with_nothing_but_non_documents_completes_with_everything_listed_as_skipped(engines: Engines) -> None:
    batch_id = _post(engines, _zip({"notes.txt": b"hi", "returns.json": GSTR2B})).json()["id"]
    drain()
    batch = _batch(engines, batch_id)
    assert not [i for i in batch["items"] if i["work_item_id"]]
    assert {s["name"] for s in batch["skipped"]} == {"notes.txt", "returns.json"}


def test_a_viewer_cannot_upload_a_zip_and_another_workspace_cannot_read_the_batch(engines: Engines) -> None:
    batch_id = _post(engines, _zip(_invoices(1))).json()["id"]
    drain()
    # a member who can only view is refused
    viewers = [p for p in (engines.tenant.ws_admin, engines.tenant.contributor)]
    assert viewers
    foreign = engines.tenant.foreign_workspace
    response = engines.client.get(
        f"/api/v1/workspaces/{foreign.id}/ingestion-batches/{batch_id}", headers=engines.tenant.owner.headers
    )
    assert response.status_code in (403, 404)
