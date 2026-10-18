"""Batch operations hardening, live: verification of uploaded packages, concurrency and tenancy.

    pytest tests/engines/test_batch_hardening_live.py -q

`test_batch_engine_live.py` proves the engine's main path (a batch processed, healed, dispatched,
exported and verified). This module covers what a production workspace meets that the main path
does not: packages uploaded for verification that are damaged, malformed or hostile; people
acting on the same batch at the same moment; and documents whose files were released.
"""

from __future__ import annotations

import gc
import hashlib
import io
import json
import tracemalloc
import uuid
import zipfile

from tests.engines.conftest import Engines

FORMAT = "servabo-export-package/1"


def _verify_raw(engines: Engines, data: bytes, *, as_user=None):
    return engines.client.post(
        engines.url("/export-packages/verify"),
        files={"file": ("package.zip", data, "application/zip")},
        headers=(as_user or engines.tenant.owner).headers,
    )


def _zip(entries: dict[str, bytes]) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as target:
        for name, body in entries.items():
            target.writestr(name, body)
    return out.getvalue()


def _synthetic(manifest: bytes, *, root: str = "Pkg-20260101-0000aaaa") -> bytes:
    """A package-shaped zip around `manifest`, whose SHA256SUMS matches its files."""
    files = {f"{root}/manifest.json": manifest, f"{root}/README.txt": b"SERVABO AI EXPORT PACKAGE\n"}
    sums = "".join(f"{hashlib.sha256(body).hexdigest()}  {name[len(root) + 1:]}\n" for name, body in files.items())
    files[f"{root}/SHA256SUMS"] = sums.encode()
    return _zip(files)


# ------------------------------------------------------------------ verification: hostile uploads


def test_a_huge_manifest_is_refused_without_reading_it_into_memory(engines: Engines) -> None:
    """A zip bomb in manifest.json: ~40 KB uploaded, 40 MB inflated. A viewer may verify, so the
    smallest role could otherwise make the API hold gigabytes (the archive limit is 4 GB)."""
    head = json.dumps({"format": FORMAT, "package_id": str(uuid.uuid4()), "name": "bomb",
                       "created_at": "2026-01-01T00:00:00+00:00", "files": []}).encode()
    bomb = _synthetic(head + b" " * (40 * 1024 * 1024))
    assert len(bomb) < 1024 * 1024
    gc.collect()

    tracemalloc.start()
    try:
        response = _verify_raw(engines, bomb, as_user=engines.tenant.viewer)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert response.status_code == 200, response.text
    result = response.json()
    assert result["verdict"] == "INVALID", result
    assert "too large" in result["message"], result["message"]
    assert peak < 16 * 1024 * 1024, f"verifying held {peak // (1024 * 1024)} MB in memory"


def _with_data_file(root: str = "Pkg-20260101-0000bbbb") -> tuple[bytes, str]:
    """A package-shaped zip with one data file listed in its manifest and SHA256SUMS."""
    data = b"invoice,total\nINV-1,10.00\n"
    manifest = json.dumps({"format": FORMAT, "package_id": str(uuid.uuid4()), "name": "pkg",
                           "created_at": "2026-01-01T00:00:00+00:00",
                           "files": [{"path": "data/extractions.csv",
                                      "sha256": hashlib.sha256(data).hexdigest()}]}).encode()
    files = {f"{root}/manifest.json": manifest, f"{root}/data/extractions.csv": data}
    sums = "".join(f"{hashlib.sha256(body).hexdigest()}  {name[len(root) + 1:]}\n" for name, body in files.items())
    files[f"{root}/SHA256SUMS"] = sums.encode()
    return _zip(files), f"{root}/data/extractions.csv"


def _patch_entry_header(archive: bytes, name: str, *, method: int | None = None, flags: int | None = None) -> bytes:
    """Rewrite one entry's compression method or flag bits in both its local and central headers,
    as one flipped byte in transit would."""
    raw = bytearray(archive)
    encoded = name.encode()
    for signature, flag_at, method_at, name_at in ((b"PK\x03\x04", 6, 8, 30), (b"PK\x01\x02", 8, 10, 46)):
        start = 0
        while (start := raw.find(signature, start)) != -1:
            if raw[start + name_at:start + name_at + len(encoded)] == encoded:
                if method is not None:
                    raw[start + method_at:start + method_at + 2] = method.to_bytes(2, "little")
                if flags is not None:
                    raw[start + flag_at:start + flag_at + 2] = flags.to_bytes(2, "little")
            start += 4
    return bytes(raw)


def test_a_flipped_header_byte_is_a_verdict_not_a_server_error(engines: Engines) -> None:
    """One byte that turns an entry's compression method into an unknown one, or marks it
    encrypted, made zipfile raise NotImplementedError / RuntimeError, which verify did not catch:
    the person holding a damaged package got a 500 instead of "changed after it was issued"."""
    archive, data_name = _with_data_file()
    assert _verify_raw(engines, archive).json()["verdict"] == "UNRECOGNISED"
    for damaged in (_patch_entry_header(archive, data_name, method=99),
                    _patch_entry_header(archive, data_name, flags=0x1)):
        response = _verify_raw(engines, damaged, as_user=engines.tenant.viewer)
        assert response.status_code == 200, response.text[:300]
        result = response.json()
        assert result["verdict"] == "TAMPERED", result
        assert any(f["path"] == "data/extractions.csv" and f["status"] == "MODIFIED"
                   for f in result["problems"]), result


def test_a_manifest_of_the_wrong_shape_is_not_a_package(engines: Engines) -> None:
    """Valid JSON of the wrong shape (a list, `files` as a number, a path or digest that is not a
    string, a name that is an object) crashed verify with a 500."""
    base = {"format": FORMAT, "package_id": str(uuid.uuid4()), "name": "pkg",
            "created_at": "2026-01-01T00:00:00+00:00", "files": []}
    shapes = [
        [base],
        {**base, "files": 7},
        {**base, "files": [{"path": ["data/x.csv"], "sha256": "0" * 64}]},
        {**base, "files": [{"path": "data/x.csv", "sha256": {"hex": "0"}}]},
        {**base, "name": {"text": "pkg"}},
        {**base, "created_at": 20260101},
        {**base, "package_id": ["not", "an", "id"]},
    ]
    for shape in shapes:
        response = _verify_raw(engines, _synthetic(json.dumps(shape).encode()), as_user=engines.tenant.viewer)
        assert response.status_code == 200, f"{shape!r}: {response.status_code} {response.text[:200]}"
        assert response.json()["verdict"] in {"INVALID", "TAMPERED"}, (shape, response.json())


# ------------------------------------------------------------------ Session B: races, erasure, strictness
#
# The audit that followed campaign session 4 reproduced these and carried them over unproven; each test
# below failed against the code as it was.

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import func, select, update

from app.models.batches import ExportPackage, ProcessingBatch, ProcessingBatchItem
from app.models.ingestion import WorkItemTag
from app.models.uploaded_file import UploadedFile
from app.services.batches import dispatch as dispatch_module
from app.services.batches import service as batch_service
from app.services.batches import vocabulary as batch_vocabulary
from tests.engines.conftest import drain, make_pdf
from tests.engines.test_concurrent_requests_do_not_freeze_the_api_live import live_server  # noqa: F401
from tests.engines.test_helm_concurrency_live import Meet, race

API = "/api/v1"


def _completed(engines: Engines, name: str, **entities) -> uuid.UUID:
    """A document as extraction leaves it: uploaded for real, COMPLETED, with a few fields."""
    work_item_id = engines.upload(name, make_pdf([[name, "Total: 10.00"]]))
    item = engines.item(work_item_id)
    item.status = "COMPLETED"
    item.extracted_entities = {"document_classification": "Invoice", "vendor_name": "Acme Ltd",
                               "invoice_number": name, **entities}
    engines.refresh()
    return work_item_id


def _batch(engines: Engines, ids: list[uuid.UUID], name: str = "Session B batch") -> str:
    response = engines.post("/processing-batches", {"name": name, "work_item_ids": [str(i) for i in ids]})
    assert response.status_code == 201, response.text
    return response.json()["id"]


class _Live:
    """Real requests to the live server as the workspace owner, each with an HTTP client of its own."""

    def __init__(self, base: str, engines: Engines) -> None:
        from app.main import app

        # The TestClient fixture hands every request the test's own session; the live server must open
        # a session per request, as in production, or the "race" is one session talking to itself.
        engines.db.commit()
        app.dependency_overrides.clear()
        self.base = base
        self.headers = engines.tenant.owner.headers
        self.root = f"{base}{API}/workspaces/{engines.ws}"

    def call(self, method: str, path: str, body=None) -> httpx.Response:
        with httpx.Client(timeout=60) as http:
            return http.request(method, f"{self.root}{path}", json=body, headers=self.headers)


def _lane_tags(engines: Engines) -> list[tuple[uuid.UUID, str]]:
    engines.refresh()
    return list(engines.db.execute(
        select(WorkItemTag.work_item_id, WorkItemTag.tag).where(WorkItemTag.tag.like("dispatch-%"))
    ).all())


# 1. Two dispatches at once --------------------------------------------------------------------


def test_two_dispatches_of_one_batch_at_once_both_answer_and_tag_once(
    engines: Engines, live_server, monkeypatch: pytest.MonkeyPatch  # noqa: F811
) -> None:
    """Both dispatches delete the old lane tags, find none, and insert the same tags: the slower one
    hit the unique key on (document, tag) and the person got an error ("changed by another request")
    for a click that was fine."""
    ids = [_completed(engines, f"RACE-{i}.pdf") for i in range(3)]
    batch_id = _batch(engines, ids)
    engines.db.commit()
    meet = Meet(2)
    monkeypatch.setattr(dispatch_module, "tag_documents", meet.after(dispatch_module.tag_documents))
    live = _Live(live_server, engines)

    responses = race(*[lambda: live.call("POST", f"/processing-batches/{batch_id}/dispatch")] * 2)

    assert [r.status_code for r in responses] == [200, 200], [(r.status_code, r.text[:200]) for r in responses]
    tags = _lane_tags(engines)
    assert sorted(t[0] for t in tags) == sorted(ids), "exactly one lane tag per document"


def test_two_batches_sharing_a_document_dispatched_at_once_both_answer(
    engines: Engines, live_server, monkeypatch: pytest.MonkeyPatch  # noqa: F811
) -> None:
    shared = _completed(engines, "SHARED.pdf")
    first = _batch(engines, [shared, _completed(engines, "ONLY-A.pdf")], "A")
    second = _batch(engines, [shared, _completed(engines, "ONLY-B.pdf")], "B")
    engines.db.commit()
    meet = Meet(2)
    monkeypatch.setattr(dispatch_module, "tag_documents", meet.after(dispatch_module.tag_documents))
    live = _Live(live_server, engines)

    responses = race(lambda: live.call("POST", f"/processing-batches/{first}/dispatch"),
                     lambda: live.call("POST", f"/processing-batches/{second}/dispatch"))

    assert [r.status_code for r in responses] == [200, 200], [(r.status_code, r.text[:200]) for r in responses]
    assert len([t for t in _lane_tags(engines) if t[0] == shared]) == 1, "the shared document has one lane tag"


# 2. Adding documents at once ------------------------------------------------------------------


def test_adding_the_same_document_twice_at_once_adds_it_once(
    engines: Engines, live_server, monkeypatch: pytest.MonkeyPatch  # noqa: F811
) -> None:
    """Two tabs add the same document: both read an empty membership and both inserted it, so the
    second hit the primary key (a 500)."""
    base = _completed(engines, "BASE.pdf")
    extra = _completed(engines, "EXTRA.pdf")
    batch_id = _batch(engines, [base])
    engines.db.commit()
    meet = Meet(2)
    monkeypatch.setattr(batch_service, "_workspace_ids", meet.after(batch_service._workspace_ids))
    live = _Live(live_server, engines)

    responses = race(*[lambda: live.call("POST", f"/processing-batches/{batch_id}/documents",
                                         {"work_item_ids": [str(extra)]})] * 2)

    assert sorted(r.status_code for r in responses) == [200, 200], [(r.status_code, r.text[:200]) for r in responses]
    engines.refresh()
    count = engines.db.execute(select(func.count()).select_from(ProcessingBatchItem)
                               .where(ProcessingBatchItem.batch_id == uuid.UUID(batch_id))).scalar_one()
    assert count == 2


def test_simultaneous_adds_cannot_pass_the_document_limit(
    engines: Engines, live_server, monkeypatch: pytest.MonkeyPatch  # noqa: F811
) -> None:
    """Each add counted the documents already there, not the other add's: 1,999 plus two single adds
    read as 2,000 twice, and the batch ended at 2,001."""
    monkeypatch.setattr(batch_vocabulary, "MAX_BATCH_DOCUMENTS", 3)
    ids = [_completed(engines, f"LIM-{i}.pdf") for i in range(4)]
    batch_id = _batch(engines, ids[:2])
    engines.db.commit()
    meet = Meet(2)
    monkeypatch.setattr(batch_service, "_workspace_ids", meet.after(batch_service._workspace_ids))
    live = _Live(live_server, engines)

    responses = race(lambda: live.call("POST", f"/processing-batches/{batch_id}/documents",
                                       {"work_item_ids": [str(ids[2])]}),
                     lambda: live.call("POST", f"/processing-batches/{batch_id}/documents",
                                       {"work_item_ids": [str(ids[3])]}))

    assert sorted(r.status_code for r in responses) == [200, 422], [(r.status_code, r.text[:200]) for r in responses]
    engines.refresh()
    count = engines.db.execute(select(func.count()).select_from(ProcessingBatchItem)
                               .where(ProcessingBatchItem.batch_id == uuid.UUID(batch_id))).scalar_one()
    assert count == 3


# 3. A batch with erased documents --------------------------------------------------------------


def _erase_upload(engines: Engines, work_item_id: uuid.UUID, *, delete_object: bool) -> None:
    """What GDPR erasure leaves: the upload marked deleted, the document's content gone; the stored
    object is deleted too, unless the storage delete failed (`delete_object=False`)."""
    from app.core.storage import get_storage_driver

    item = engines.item(work_item_id)
    upload = engines.db.get(UploadedFile, item.uploaded_file_id)
    upload.deleted_at = datetime.now(timezone.utc)
    upload.original_filename = "[erased]"
    item.extracted_text = item.summary = item.extracted_entities = item.extraction_metadata = None
    item.original_filename = "[erased]"
    key = item.stored_filename
    engines.refresh()
    if delete_object:
        get_storage_driver().delete(key)


def _build(engines: Engines, batch_id: str, *, originals: bool = True) -> dict:
    response = engines.post("/export-packages", {"batch_id": batch_id, "name": "Erasure check",
                                                  "include_originals": originals})
    assert response.status_code == 202, response.text
    drain()
    return engines.get(f"/export-packages/{response.json()['id']}").json()


def _names(engines: Engines, package: dict) -> list[str]:
    body = engines.get(f"/export-packages/{package['id']}/download").content
    return zipfile.ZipFile(io.BytesIO(body)).namelist()


def test_a_package_of_a_batch_with_an_erased_document_is_built_without_its_original(engines: Engines) -> None:
    kept = _completed(engines, "KEPT.pdf")
    erased = _completed(engines, "ERASED.pdf")
    batch_id = _batch(engines, [kept, erased])
    _erase_upload(engines, erased, delete_object=True)

    package = _build(engines, batch_id)

    assert package["status"] == "READY", package
    originals = [n for n in _names(engines, package) if "/files/" in n]
    assert len(originals) == 1 and originals[0].endswith("KEPT.pdf"), originals


def test_an_original_whose_deletion_failed_is_not_put_in_the_package(engines: Engines) -> None:
    """The upload is marked deleted but its stored object is still there (the storage delete failed
    after the database change): erasure promised the file was gone, so a package must not carry it."""
    kept = _completed(engines, "KEPT-2.pdf")
    erased = _completed(engines, "ERASED-2.pdf")
    batch_id = _batch(engines, [kept, erased])
    _erase_upload(engines, erased, delete_object=False)

    package = _build(engines, batch_id)

    assert package["status"] == "READY", package
    originals = [n for n in _names(engines, package) if "/files/" in n]
    assert len(originals) == 1 and originals[0].endswith("KEPT-2.pdf"), originals


# 4. Extra files in a package (N-076) -------------------------------------------------------------


def _tampered(result: dict, path: str) -> bool:
    return result["verdict"] == "TAMPERED" and any(p["path"] == path and p["status"] == "UNEXPECTED"
                                                   for p in result["problems"])


def _add_entries(archive: bytes, extra: list[tuple[str, bytes]]) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(archive)) as source, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as target:
        for info in source.infolist():
            target.writestr(info, source.read(info.filename))
        for name, body in extra:
            target.writestr(name, body)
    return out.getvalue()


def test_a_file_outside_the_package_folder_is_tampering(engines: Engines) -> None:
    archive, _ = _with_data_file()
    assert _verify_raw(engines, archive).json()["verdict"] == "UNRECOGNISED"
    result = _verify_raw(engines, _add_entries(archive, [("notes-from-someone.txt", b"added later")])).json()
    assert _tampered(result, "notes-from-someone.txt"), result


def test_a_file_inside_the_folder_that_the_sums_do_not_list_is_tampering(engines: Engines) -> None:
    archive, _ = _with_data_file()
    result = _verify_raw(engines, _add_entries(archive, [("Pkg-20260101-0000bbbb/data/extra.csv", b"x")])).json()
    assert _tampered(result, "data/extra.csv"), result


def test_two_entries_under_one_name_are_tampering(engines: Engines) -> None:
    """zipfile reads the last of two same-named entries, and a `set` of names hid the first: a package
    could carry the checked body last and a different one first, which another unzip tool extracts."""
    archive, data_name = _with_data_file()
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(archive)) as source, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as target:
        target.writestr(data_name, b"invoice,total\nINV-1,99999.00\n")  # the body a reader would extract first
        for info in source.infolist():
            target.writestr(info, source.read(info.filename))
    result = _verify_raw(engines, out.getvalue()).json()
    assert result["verdict"] == "TAMPERED", result
    assert any(p["path"].endswith("data/extractions.csv") and p["status"] == "UNEXPECTED"
               for p in result["problems"]), result


def test_what_macos_adds_when_a_folder_is_re_zipped_is_ignored(engines: Engines) -> None:
    archive, _ = _with_data_file()
    root = "Pkg-20260101-0000bbbb"
    repacked = _add_entries(archive, [
        ("__MACOSX/Pkg-20260101-0000bbbb/._manifest.json", b"\x00\x05\x16\x07"),
        (".DS_Store", b"\x00\x00\x00\x01Bud1"),
        (f"{root}/.DS_Store", b"\x00\x00\x00\x01Bud1"),
        (f"{root}/data/.DS_Store", b"\x00\x00\x00\x01Bud1"),
    ])
    result = _verify_raw(engines, repacked).json()
    assert result["verdict"] == "UNRECOGNISED" and not result["problems"], result


# 5. The list, archived batches and an expired download -------------------------------------------


def test_the_batch_list_reads_only_this_workspaces_verifications(engines: Engines) -> None:
    """The latest-verification subquery had no workspace bound: it ranked every organization's
    verifications before joining to this page's batches."""
    from sqlalchemy import event

    batch_id = _batch(engines, [_completed(engines, "SCOPE.pdf")])
    statements: list[str] = []

    def capture(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
        statements.append(statement)

    event.listen(engines.db.get_bind(), "before_cursor_execute", capture)
    try:
        assert engines.get("/processing-batches").status_code == 200
    finally:
        event.remove(engines.db.get_bind(), "before_cursor_execute", capture)
    reading = [s for s in statements if "FROM document_verifications" in s]
    assert reading, "the list reads verifications for the mean confidence"
    assert all("document_verifications.workspace_id" in s for s in reading), reading[0][:400]
    assert batch_id


@pytest.mark.parametrize("act", ["dispatch", "heal", "retry-failed", "add", "remove", "rename"])
def test_an_archived_batch_cannot_be_acted_on(engines: Engines, act: str) -> None:
    first, second = _completed(engines, "ARCH-1.pdf"), _completed(engines, "ARCH-2.pdf")
    batch_id = _batch(engines, [first])
    assert engines.patch(f"/processing-batches/{batch_id}", {"status": "ARCHIVED"}).status_code == 200
    base = f"/processing-batches/{batch_id}"
    attempts = {
        "dispatch": lambda: engines.post(f"{base}/dispatch"),
        "heal": lambda: engines.post(f"{base}/heal", {}),
        "retry-failed": lambda: engines.post(f"{base}/retry-failed"),
        "add": lambda: engines.post(f"{base}/documents", {"work_item_ids": [str(second)]}),
        "remove": lambda: engines.delete(f"{base}/documents/{first}"),
        "rename": lambda: engines.patch(base, {"name": "A new name"}),
    }
    response = attempts[act]()
    assert response.status_code == 409, (act, response.status_code, response.text[:200])
    assert response.json()["detail"]["code"] == "BATCH_ARCHIVED"
    # Nothing changed, and it can still be restored, read and deleted.
    assert engines.get(base).status_code == 200
    assert engines.patch(base, {"status": "ACTIVE"}).status_code == 200
    assert engines.post(f"{base}/dispatch").status_code == 200


def test_downloading_an_expired_package_expires_that_package_only(engines: Engines) -> None:
    """The route ran the global expiry sweep (every workspace's packages) inside the download request."""
    ids = [_completed(engines, "EXP-1.pdf")]
    batch_id = _batch(engines, ids)
    first, second = _build(engines, batch_id), _build(engines, batch_id)
    assert first["status"] == second["status"] == "READY"
    engines.db.execute(update(ExportPackage).values(expires_at=datetime.now(timezone.utc) - timedelta(days=1)))
    engines.refresh()

    response = engines.get(f"/export-packages/{first['id']}/download")

    assert response.status_code == 409 and response.json()["detail"]["code"] == "PACKAGE_EXPIRED", response.text
    engines.refresh()
    states = dict(engines.db.execute(select(ExportPackage.id, ExportPackage.status)).all())
    assert states[uuid.UUID(first["id"])] == "EXPIRED"
    assert states[uuid.UUID(second["id"])] == "READY", "the other package is left to the hourly sweep"


def test_the_list_totals_cover_every_batch_not_just_the_page(engines: Engines) -> None:
    """The page's tiles summed the batches on the page (50 at most). The list now carries totals over
    every batch of the tab, so a workspace with 60 batches does not show 50 documents' worth."""
    first = _batch(engines, [_completed(engines, "T-1.pdf"), _completed(engines, "T-2.pdf")], "one")
    _batch(engines, [_completed(engines, "T-3.pdf")], "two")
    archived = _batch(engines, [_completed(engines, "T-4.pdf")], "three")
    assert engines.post(f"/processing-batches/{first}/dispatch").status_code == 200
    assert engines.patch(f"/processing-batches/{archived}", {"status": "ARCHIVED"}).status_code == 200

    page = engines.get("/processing-batches", params={"status": "ACTIVE", "limit": 1}).json()
    assert len(page["items"]) == 1 and page["total"] == 2
    assert page["totals"] == {"batches": 2, "documents": 3, "in_flight": 0, "failed": 0, "straight_through": 0,
                              "review": 2, "exception": 0, "dispatched": 2, "mean_confidence": None}, page["totals"]

    gone = engines.get("/processing-batches", params={"status": "ARCHIVED"}).json()
    assert gone["total"] == 1 and gone["totals"]["batches"] == 1 and gone["totals"]["documents"] == 1
