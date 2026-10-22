"""Final session 1 (2A): a zip of documents is read member by member, every limit refuses the whole zip, and what is
merely not a document is skipped and listed.

No database: `archive.py` is pure. The limits are the ones in ARCH-38; this file adds what the zip-upload feature needs
(skipped members, a GSTR-2B JSON, encrypted entries, symbolic links) and proves each limit once more, through
`expand_members`, because that is the door the feature uses.
"""

from __future__ import annotations

import io
import json
import struct
import zipfile

import pytest

from app.services.ingestion import archive

pytestmark = pytest.mark.no_db

PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
GSTR2B = json.dumps({"data": {"gstin": "27AAACG1234F1Z5", "rtnprd": "092026", "docdata": {"b2b": []}}}).encode()


def make_zip(entries: dict[str, bytes], *, deflate: bool = True) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED if deflate else zipfile.ZIP_STORED) as zf:
        for name, payload in entries.items():
            zf.writestr(name, payload)
    return buffer.getvalue()


def members(data: bytes):
    return list(archive.expand_members(data))


def test_documents_become_entries_in_order():
    out = members(make_zip({"a.pdf": PDF, "folder/b.PDF": PDF, "c.png": b"\x89PNG\r\n\x1a\n" + b"0" * 20}))
    assert [m.name for m in out] == ["a.pdf", "b.PDF", "c.png"]
    assert all(isinstance(m, archive.ArchiveEntry) for m in out)
    assert out[1].mime_type == "application/pdf"


def test_junk_a_computer_adds_is_skipped_without_a_word():
    out = members(make_zip({
        "a.pdf": PDF, ".DS_Store": b"\x00\x00\x00\x01Bud1", "__MACOSX/._a.pdf": b"x" * 10, "sub/Thumbs.db": b"x", "._b.pdf": b"x",
    }))
    assert [m.name for m in out] == ["a.pdf"], "nothing about the junk is yielded, not even as a skipped file"


def test_a_gstr2b_json_is_skipped_with_the_words_that_send_the_person_to_the_gst_page():
    out = members(make_zip({"a.pdf": PDF, "returns/gstr2b_092026.json": GSTR2B}))
    skipped = [m for m in out if isinstance(m, archive.SkippedEntry)]
    assert len(skipped) == 1
    assert skipped[0].name == "gstr2b_092026.json" and skipped[0].code == archive.SKIP_GSTR2B
    assert skipped[0].message == "This looks like a GSTR-2B file: import it on the GST credit page."


def test_other_files_are_skipped_as_not_a_supported_type_and_do_not_end_the_run():
    out = members(make_zip({"a.pdf": PDF, "notes.txt": b"hello", "sheet.xlsx": b"PK-not-really", "data.json": b'{"x": 1}', "b.pdf": PDF}))
    assert [m.name for m in out if isinstance(m, archive.ArchiveEntry)] == ["a.pdf", "b.pdf"]
    skipped = {m.name: m for m in out if isinstance(m, archive.SkippedEntry)}
    assert set(skipped) == {"notes.txt", "sheet.xlsx", "data.json"}
    assert all(m.code == archive.SKIP_UNSUPPORTED and "supported file type" in m.message for m in skipped.values())


def test_the_strict_expander_still_refuses_an_unsupported_member():
    with pytest.raises(archive.ArchiveRejected) as caught:
        list(archive.expand(make_zip({"notes.txt": b"hello"})))
    assert caught.value.code == "ARCHIVE_MEMBER_NOT_ALLOWED"


# ------------------------------------------------------------------------------------------------ every limit

def test_too_many_files(monkeypatch):
    monkeypatch.setattr(archive, "MAX_ENTRIES", 3)
    with pytest.raises(archive.ArchiveRejected) as caught:
        members(make_zip({f"{i}.pdf": PDF for i in range(4)}))
    assert caught.value.code == "ARCHIVE_TOO_MANY_ENTRIES"


def test_too_much_when_unpacked(monkeypatch):
    monkeypatch.setattr(archive, "MAX_TOTAL_EXPANDED_BYTES", 1000)
    monkeypatch.setattr(archive, "RATIO_FLOOR_BYTES", 10**9)
    with pytest.raises(archive.ArchiveRejected) as caught:
        members(make_zip({"a.pdf": PDF + b"A" * 600, "b.pdf": PDF + b"B" * 600}, deflate=False))
    assert caught.value.code == "ARCHIVE_TOO_LARGE"


def test_a_single_member_that_is_too_large(monkeypatch):
    monkeypatch.setattr(archive, "MAX_ENTRY_BYTES", 100)
    with pytest.raises(archive.ArchiveRejected) as caught:
        members(make_zip({"a.pdf": PDF + b"A" * 500}, deflate=False))
    assert caught.value.code == "ARCHIVE_ENTRY_TOO_LARGE"


def test_a_zip_inside_a_zip_is_refused_not_unpacked():
    inner = make_zip({"a.pdf": PDF})
    for name in ("inner.zip", "backup.tar.gz"):
        with pytest.raises(archive.ArchiveRejected) as caught:
            members(make_zip({"a.pdf": PDF, name: inner}))
        assert caught.value.code == "ARCHIVE_NESTED"
    with pytest.raises(archive.ArchiveRejected) as caught:  # an archive under another name
        members(make_zip({"looks-like.pdf": inner}))
    assert caught.value.code == "ARCHIVE_NESTED"


@pytest.mark.parametrize("name", ["../evil.pdf", "a/../../evil.pdf", "/etc/evil.pdf", "C:/evil.pdf", "..\\evil.pdf"])
def test_a_path_that_escapes_refuses_the_whole_zip(name):
    with pytest.raises(archive.ArchiveRejected) as caught:
        members(make_zip({"ok.pdf": PDF, name: PDF}))
    assert caught.value.code == "ARCHIVE_UNSAFE_PATH"


def test_a_compression_bomb_is_refused_before_anything_is_unpacked():
    bomb = make_zip({"a.pdf": PDF + b"\x00" * 5_000_000})
    assert len(bomb) < 20_000, "a few KB that expand to 5 MB"
    with pytest.raises(archive.ArchiveRejected) as caught:
        members(bomb)
    assert caught.value.code == "ARCHIVE_COMPRESSION_RATIO"


def test_a_symbolic_link_is_refused():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("a.pdf", PDF)
        link = zipfile.ZipInfo("secrets.pdf")
        link.create_system = 3
        link.external_attr = (0o120777 << 16)
        zf.writestr(link, "/etc/passwd")
    with pytest.raises(archive.ArchiveRejected) as caught:
        members(buffer.getvalue())
    assert caught.value.code == "ARCHIVE_SYMLINK"


def _mark_encrypted(data: bytes) -> bytes:
    """Set the 'encrypted' bit in every local and central header (what a password-protected zip carries)."""
    out = bytearray(data)
    for signature, offset in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):
        position = out.find(signature)
        while position != -1:
            flags = struct.unpack_from("<H", out, position + offset)[0] | 0x1
            struct.pack_into("<H", out, position + offset, flags)
            position = out.find(signature, position + 4)
    return bytes(out)


def test_a_password_protected_zip_is_refused_with_a_sentence():
    with pytest.raises(archive.ArchiveRejected) as caught:
        members(_mark_encrypted(make_zip({"a.pdf": PDF})))
    assert caught.value.code == "ARCHIVE_ENCRYPTED" and "password" in caught.value.message


def test_not_a_zip_and_an_empty_zip():
    with pytest.raises(archive.ArchiveRejected) as caught:
        members(b"this is not a zip at all")
    assert caught.value.code == "ARCHIVE_NOT_A_ZIP"
    with pytest.raises(archive.ArchiveRejected) as caught:
        members(make_zip({}))
    assert caught.value.code in {"ARCHIVE_EMPTY", "ARCHIVE_NOT_A_ZIP"}


def test_a_directory_that_lies_about_a_size_is_caught_when_read():
    data = bytearray(make_zip({"a.pdf": PDF + b"A" * 300}, deflate=False))
    # shrink the declared uncompressed size in the central directory (offset 24 of the central header)
    position = data.find(b"PK\x01\x02")
    struct.pack_into("<I", data, position + 24, 10)
    with pytest.raises((archive.ArchiveRejected, zipfile.BadZipFile)):
        members(bytes(data))
