"""Reading a GSTR-2B download: every wrapping, a zip, the sections, and the limits of an untrusted file."""

from __future__ import annotations

import io
import json
import zipfile
from datetime import date

import pytest

from app.services.gst import builder as b
from app.services.gst import parse
from app.services.gst import vocabulary as v
from tests.services.gst.helpers import RECIPIENT, SUPPLIER_A, SUPPLIER_B, M, parsed_return, supplier_invoices

pytestmark = pytest.mark.no_db


def sections():
    return {
        "b2b": [supplier_invoices([
            b.document("INV/25-26/0045", date(2026, 9, 3), 1000, irn="a1" * 32),
            b.document("INV-0046", date(2026, 9, 4), 2000, interstate=True, itc_available="N", reason="P"),
        ])],
        "cdnr": [supplier_invoices([b.document("CN-7", date(2026, 9, 20), 500, note="C")], notes=True)],
    }


@pytest.mark.parametrize("wrap", ["status", "data", "bare"])
def test_every_documented_wrapping_reads_the_same(wrap):
    parsed = parse.parse_file("x.json", b.to_bytes(b.gstr2b(RECIPIENT, "2026-09", sections(), wrap=wrap)))[0]
    assert parsed.gstin == RECIPIENT and parsed.period == "2026-09" and parsed.rtnprd == "092026"
    assert parsed.generated_on == date(2026, 10, 14) and parsed.version == "1.0"
    assert [r.number for r in parsed.records] == ["INV/25-26/0045", "INV-0046", "CN-7"]
    assert parsed.counts() == {"b2b": 2, "cdnr": 1}


def test_amounts_are_micros_and_tax_heads_are_read_from_the_items():
    parsed = parsed_return(sections())
    first, second, note = parsed.records
    assert first.taxable_micros == 1000 * M and first.cgst_micros == 90 * M and first.sgst_micros == 90 * M
    assert first.igst_micros == 0 and first.value_micros == 1180 * M and first.tax_micros == 180 * M
    assert first.irn == "a1" * 32 and first.number_key == "INV-45"
    assert second.igst_micros == 360 * M and second.itc_available == "N" and second.reason == "P"
    assert note.kind == v.KIND_CREDIT_NOTE and note.number == "CN-7"


def test_amendments_carry_the_original_number_and_date():
    amended = {"b2ba": [supplier_invoices([b.document("INV-0050", date(2026, 9, 3), 900, original=("INV-0050 ", date(2026, 9, 3)))])]}
    record = parsed_return(amended).records[0]
    assert record.section == "b2ba" and record.original_key == "INV-50" and record.original_date == date(2026, 9, 3)


def test_goods_import_sections_are_kept_for_totals_not_matched():
    body = {"impg": [{"boenum": "7001", "boedt": "05-09-2026", "txval": 100, "igst": 18, "cess": 0}]}
    record = parsed_return(body).records[0]
    assert record.section == "impg" and record.kind == v.KIND_OTHER and record.igst_micros == 18 * M


def test_a_zip_holding_the_json_is_read_and_a_zip_of_several_months_gives_several_returns():
    first = b.to_bytes(b.gstr2b(RECIPIENT, "2026-08", sections()))
    second = b.to_bytes(b.gstr2b(RECIPIENT, "2026-09", sections()))
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("GSTR2B_082026.json", first)
        archive.writestr("GSTR2B_092026.json", second)
        archive.writestr("readme.txt", "ignored")
    returns = parse.parse_file("both.zip", buffer.getvalue())
    assert [r.period for r in returns] == ["2026-08", "2026-09"]
    assert returns[0].sha256 != returns[1].sha256


def test_a_zip_with_no_json_is_refused_in_words():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("notes.txt", "x")
    with pytest.raises(parse.ReturnFileError) as error:
        parse.parse_file("a.zip", buffer.getvalue())
    assert error.value.code == "ZIP_HAS_NO_JSON" and "JSON" in error.value.message


def test_a_compression_bomb_is_refused_before_it_is_read():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("bomb.json", " " * (24 * 1024 * 1024))
    with pytest.raises(parse.ReturnFileError) as error:
        parse.parse_file("bomb.zip", buffer.getvalue())
    assert error.value.code in ("ARCHIVE_COMPRESSION_RATIO", "ARCHIVE_TOO_LARGE")


@pytest.mark.parametrize("name,data,code", [
    ("a.json", b"", "FILE_EMPTY"),
    ("a.json", b"not json at all {", "NOT_JSON"),
    ("a.csv", b"a,b", "FILE_TYPE"),
    ("a.json", b'{"hello": 1}', "NOT_GSTR2B"),
])
def test_unreadable_files_get_a_sentence_and_a_code(name, data, code):
    with pytest.raises(parse.ReturnFileError) as error:
        parse.parse_file(name, data)
    assert error.value.code == code and error.value.message.endswith((".", "?"))


def test_a_gstin_with_a_wrong_check_character_is_refused():
    broken = b.gstr2b(RECIPIENT[:-1] + ("0" if RECIPIENT[-1] != "0" else "1"), "2026-09", {})
    with pytest.raises(parse.ReturnFileError) as error:
        parse.parse_file("a.json", b.to_bytes(broken))
    assert error.value.code == "GSTIN_INVALID"


def test_a_missing_or_malformed_period_is_refused():
    document = b.gstr2b(RECIPIENT, "2026-09", {}, wrap="bare")
    document["rtnprd"] = "2026-09"
    with pytest.raises(parse.ReturnFileError) as error:
        parse.parse_file("a.json", b.to_bytes(document))
    assert error.value.code == "PERIOD_INVALID"


def test_deeply_nested_json_is_refused():
    deep = current = {}
    for _ in range(40):
        current["x"] = {}
        current = current["x"]
    with pytest.raises(parse.ReturnFileError) as error:
        parse.parse_file("a.json", json.dumps({"gstin": RECIPIENT, "docdata": deep}).encode())
    assert error.value.code == "TOO_DEEP"


def test_the_record_limit_applies(monkeypatch):
    monkeypatch.setattr(v, "MAX_RECORDS", 2)
    with pytest.raises(parse.ReturnFileError) as error:
        parsed_return(sections())
    assert error.value.code == "TOO_MANY_RECORDS"


def test_the_size_limit_applies(monkeypatch):
    monkeypatch.setattr(v, "MAX_FILE_BYTES", 100)
    with pytest.raises(parse.ReturnFileError) as error:
        parse.parse_file("a.json", b"{" + b" " * 200 + b"}")
    assert error.value.code == "FILE_TOO_LARGE"


def test_problems_are_reported_in_words_not_dropped():
    bad_supplier = {"ctin": SUPPLIER_A[:-1] + ("1" if SUPPLIER_A[-1] != "1" else "2"), "trdnm": "Odd Co", "supfildt": "09-10-2026", "supprd": "092026",
                    "inv": [{"inum": "X-1", "dt": "not a date", "val": 10, "items": []}, {"dt": "01-09-2026", "val": 5}]}
    parsed = parsed_return({"b2b": [bad_supplier], "weird": [], "b2ba": "nope"})
    codes = {p.code for p in parsed.problems}
    assert {"SUPPLIER_GSTIN_INVALID", "RECORD_DATE_UNREADABLE", "RECORD_WITHOUT_NUMBER", "SECTION_UNKNOWN",
            "SECTION_SHAPE"} <= codes
    assert len(parsed.records) == 2


def test_the_raw_copy_is_bounded():
    huge = b.document("INV-1", date(2026, 9, 1), 100)
    huge["note"] = "x" * 50_000
    record = parsed_return({"b2b": [supplier_invoices([huge])]}).records[0]
    assert len(json.dumps(record.raw)) <= v.MAX_RAW_BYTES + 100 and record.raw.get("truncated") is True
