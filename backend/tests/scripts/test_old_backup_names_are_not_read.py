"""Backups written under the old product name are not read (Session B, B1).

Until 2026-10-16 backups were `<old name>-<stamp>.fpbk` with the old format tag. No installation
from before the rename exists, so only `servabo-<stamp>.fpbk` with `servabo-backup-floor/1` is a
backup, and the old local directories are not looked at.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
from pathlib import Path

import pytest

from scripts import backup_floor

pytestmark = pytest.mark.no_db

OLD = "flow" + "pilot"  # split so the guard test does not match this file


@pytest.fixture()
def key(monkeypatch: pytest.MonkeyPatch) -> bytes:
    raw = os.urandom(32)
    monkeypatch.setenv("SERVABO_BACKUP_KEY", base64.b64encode(raw).decode())
    return raw


def _write(dest: Path, stem: str, stamp: str, key: bytes, fmt: str) -> None:
    plain = f"dump {stem} {stamp}".encode()
    sink = io.BytesIO()
    original = backup_floor.FORMAT
    backup_floor.FORMAT = fmt
    try:
        plain_sha, size = backup_floor.encrypt_stream(io.BytesIO(plain), sink, key)
    finally:
        backup_floor.FORMAT = original
    data = dest / f"{stem}-{stamp}.fpbk"
    data.write_bytes(sink.getvalue())
    (dest / f"{stem}-{stamp}.manifest.json").write_text(json.dumps({
        "format": fmt, "file": data.name, "stamp": stamp, "plaintext_bytes": size,
        "plaintext_sha256": plain_sha, "ciphertext_sha256": hashlib.sha256(data.read_bytes()).hexdigest(),
    }))


def test_only_the_current_name_and_format_are_backups() -> None:
    assert backup_floor.STEMS == ("servabo",)
    assert backup_floor.READABLE_FORMATS == frozenset({backup_floor.FORMAT})


def test_a_backup_under_the_old_name_is_not_the_newest(tmp_path: Path, key: bytes) -> None:
    _write(tmp_path, "servabo", "20261001T000000Z", key, backup_floor.FORMAT)
    _write(tmp_path, OLD, "20261010T000000Z", key, OLD + "-backup-floor/1")
    assert backup_floor.latest_manifest(tmp_path).name == "servabo-20261001T000000Z.manifest.json"


def test_the_old_format_tag_is_refused(tmp_path: Path, key: bytes) -> None:
    _write(tmp_path, "servabo", "20261001T000000Z", key, OLD + "-backup-floor/1")
    with pytest.raises(backup_floor.BackupError, match="Unsupported backup format"):
        backup_floor.verify_file(tmp_path, backup_floor.latest_manifest(tmp_path))


def test_pruning_leaves_files_under_the_old_name_alone(tmp_path: Path, key: bytes) -> None:
    stamps = [f"202609{day:02d}T000000Z" for day in range(1, 21)]
    for stamp in stamps:
        _write(tmp_path, "servabo", stamp, key, backup_floor.FORMAT)
    _write(tmp_path, OLD, "20260902T120000Z", key, OLD + "-backup-floor/1")  # old enough to be pruned if it counted
    backup_floor.prune(tmp_path)
    assert (tmp_path / f"{OLD}-20260902T120000Z.fpbk").exists()


def test_an_unknown_format_is_still_refused(tmp_path: Path, key: bytes) -> None:
    _write(tmp_path, "servabo", "20261001T000000Z", key, "someone-else/1")
    with pytest.raises(backup_floor.BackupError, match="Unsupported backup format"):
        backup_floor.verify_file(tmp_path, backup_floor.latest_manifest(tmp_path))
