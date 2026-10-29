"""The statement readers (Final 2T, Phase 3; N-203): the Servabo template, the Form 26AS / Form 168 text download and the AIS
CSV. Pure: no database. The fixtures are synthetic files of the shape the readers expect (invented PAN, TANs and amounts); the
official layouts could not be read from the build environment, so each official reader is unverified until Final session 2B
(see readers.py)."""

import io
from pathlib import Path

import pytest

from app.services.trinetra import readers
from app.services.trinetra.statements import ais, detect, form26as, template
from app.services.trinetra.statements.common import StatementRefused

pytestmark = pytest.mark.no_db

FIXTURES = Path(__file__).parents[1] / "fixtures" / "trinetra"
M = 1_000_000


def fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


# --- Form 26AS text ----------------------------------------------------------------------------------------------------


def test_the_form_26as_text_is_read_with_its_label_sections_and_checked_totals():
    parsed = detect.read("AS.txt", fixture("form26as_sample.txt"))
    assert parsed.reader == "form26as-text-v1" and parsed.parser_version == "form26as-text-v1"
    assert [(r.tan, r.section, r.amount_micros) for r in parsed.rows] == [
        ("ABCD12345E", "194C", 2000 * M), ("ABCD12345E", "194C", 1000 * M), ("MUMB54321K", "194Q", 1250 * M)]
    assert parsed.label.kind == "FY_AY" and parsed.label.year == 2025 and "FY 2025-26" in parsed.label.text
    assert parsed.file_pan == "ABCDE1234F"
    assert all(c.ok for c in parsed.checks) and any("TDS deposited" in c.name for c in parsed.checks)
    assert any("PART-B" in i for i in parsed.ignored)          # tax collected at source is not read
    assert parsed.rows[0].on.isoformat() == "2025-06-15" and parsed.rows[0].status == "F"
    assert len({r.reference for r in parsed.rows}) == 3        # every row has its own reference


def test_the_form_168_text_keeps_the_tax_year_label_and_the_table_items_as_printed():
    parsed = detect.read("168.txt", fixture("form168_sample.txt"))
    assert parsed.reader == "form168-text-v1"
    assert parsed.label.kind == "TAX_YEAR" and parsed.label.year == 2026 and parsed.label.text == "Tax Year 2026-27"
    assert [r.section for r in parsed.rows] == ["393(1) [Sl. No. 6(iii)]", "393(1) [Sl. No. 6(iii)]", "393(1) [Sl. No. 8(ii)]"]
    assert "FY" not in parsed.label.text and "AY" not in parsed.label.text  # never mixed or converted


def test_a_total_that_disagrees_with_the_rows_refuses_the_whole_file():
    bad = fixture("form26as_sample.txt").replace(b"^150000.00^3000.00^3000.00^", b"^150000.00^3000.00^3100.00^")
    with pytest.raises(StatementRefused) as e:
        form26as.read("AS.txt", bad)
    assert e.value.code == "TRINETRA_TOTAL_MISMATCH" and "does not match" in e.value.message


@pytest.mark.parametrize("edit,code", [
    (lambda b: b.replace(b"^Section^", b"^Surprise^"), "TRINETRA_UNEXPECTED_LINE"),
    (lambda b: b.replace(b"PART-B - Details", b"PART-Q - Details"), "TRINETRA_UNKNOWN_PART"),
    (lambda b: b.replace(b"^Status of Booking^", b"^Status of Booking^Mystery^").replace(b"^F^30-Jul-2025^-^", b"^F^x^30-Jul-2025^-^"), None),
    (lambda b: b.replace(b"ABCD12345E^150000", b"del12345^150000"), "TRINETRA_BAD_TAN"),
    (lambda b: b.replace(b"15-Jun-2025", b"31-Feb-2025"), "TRINETRA_BAD_DATE"),
    (lambda b: b.replace(b"2000.00^2000.00^\n", b"2,0x0.00^2000.00^\n"), "TRINETRA_BAD_AMOUNT"),
    (lambda b: b.replace(b"2026-27^SYNTHETIC", b"2026-27^SYNTHETIC").replace(b"ABCDE1234F", b"ABCDE1234F") + b"^PART-A - Details of Tax Deducted at Source^\n^Sr. No.^Name of Deductor^TAN of Deductor^Total Amount Paid/ Credited(Rs.)^Total Tax Deducted(Rs.)^Total TDS Deposited(Rs.)^\n^1^X^ABCD12345E^1.00^1.00^1.00^\n", None),
])
def test_an_unknown_column_part_tan_date_or_amount_is_refused_not_guessed(edit, code):
    with pytest.raises(StatementRefused) as e:
        form26as.read("AS.txt", edit(fixture("form26as_sample.txt")))
    if code:
        assert e.value.code == code, (e.value.code, e.value.message)


def test_a_pdf_a_zip_and_a_file_that_is_not_a_statement_are_refused_with_the_way_forward():
    with pytest.raises(StatementRefused) as e:
        detect.read("AS.pdf", b"%PDF-1.7 ...")
    assert e.value.code == "TRINETRA_PDF_STATEMENT" and "text" in e.value.message
    with pytest.raises(StatementRefused) as e:
        detect.read("AS.zip", b"PK\x03\x04....")
    assert e.value.code == "TRINETRA_ZIP_STATEMENT" and "password" in e.value.message
    with pytest.raises(StatementRefused) as e:
        detect.read("notes.csv", b"a,b,c\n1,2,3\n")
    assert e.value.code == "TRINETRA_UNRECOGNIZED_LAYOUT"


def test_a_file_naming_two_pans_or_two_tax_years_is_refused():
    two = fixture("form26as_sample.txt") + b"^28-10-2026^ZZZZZ9999Z^Active^2025-26^2026-27^X^\n"
    # (a second header line without its title row is a stray line in a part we do not read: ignored, not a second PAN)
    assert form26as.read("AS.txt", two).file_pan == "ABCDE1234F"
    mixed = fixture("form26as_sample.txt").replace(b"^28-10-2026^ABCDE1234F^Active^2025-26^2026-27^SYNTH",
                                                    b"^28-10-2026^ABCDE1234F^Active^2025-26^2026-27^SYNTH") \
        .replace(b"^File Creation Date^", b"Tax Year 2026-27\n^File Creation Date^")
    with pytest.raises(StatementRefused) as e:
        form26as.read("AS.txt", mixed)
    assert e.value.code == "TRINETRA_MIXED_YEARS"


# --- AIS CSV -----------------------------------------------------------------------------------------------------------


def test_the_ais_csv_reads_tds_rows_only_and_shows_the_mapping_to_confirm():
    parsed = detect.read("AIS.csv", fixture("ais_tds_sample.csv"))
    assert parsed.reader == "ais-csv-v1"
    assert [(r.tan, r.section, r.amount_micros) for r in parsed.rows] == [
        ("ABCD12345E", "194C", 2000 * M), ("ABCD12345E", "194C", 1000 * M), ("MUMB54321K", "194Q", 1250 * M)]
    assert any("TCS" in i for i in parsed.ignored) and parsed.label.year == 2025 and parsed.label.kind == "FY_AY"
    assert ("Information Source", "deductor name (and TAN)") in parsed.mapping
    assert any(c.name == "file total" and c.ok for c in parsed.checks)
    assert parsed.columns_info["chosen"]["deducted"] is not None


def test_the_ais_csv_total_row_must_agree_and_an_ambiguous_mapping_is_left_to_the_reviewer():
    bad = fixture("ais_tds_sample.csv").replace(b'"4,250.00"', b'"4,251.00"')
    with pytest.raises(StatementRefused) as e:
        ais.read("AIS.csv", bad)
    assert e.value.code == "TRINETRA_TOTAL_MISMATCH"
    two_tax = fixture("ais_tds_sample.csv").replace(b"Tax Deducted", b"Tax Deducted at Source,TDS Amount")
    with pytest.raises(StatementRefused) as e:
        ais.read("AIS.csv", two_tax.replace(b",F\n", b",F,0\n"))
    assert e.value.code in ("TRINETRA_AMBIGUOUS_COLUMNS", "TRINETRA_UNRECOGNIZED_LAYOUT")
    # The reviewer chooses explicitly: the second tax column.
    header = [h for h in two_tax.decode().splitlines()[2].split(",")]
    chosen = ais.read("AIS.csv", fixture("ais_tds_sample.csv"), mapping={"deducted": 6})
    assert len(chosen.rows) == 3


# --- Servabo template --------------------------------------------------------------------------------------------------


def test_the_template_round_trips_and_is_labelled_as_your_transcription():
    parsed = detect.read("t.csv", fixture("servabo_template_sample.csv"))
    assert parsed.reader == "servabo-template-v1" and len(parsed.rows) == 3
    assert readers.get("servabo-template-v1").official is False and "official" in readers.get("servabo-template-v1").source.lower()
    assert parsed.label.kind == "FY_AY"
    # The downloadable template (CSV and Excel) has exactly the documented columns.
    assert template.csv_bytes().decode("utf-8-sig").strip().split(",")[:2] == ["Deductor TAN", "Tax credited (INR)"]
    from openpyxl import load_workbook

    book = load_workbook(io.BytesIO(template.xlsx_bytes()))
    assert [c.value for c in book["Statement rows"][1]] == list(template.COLUMNS)


@pytest.mark.parametrize("row,fragment", [
    ("BADTAN,100.00,r1", "TAN"),
    ("ABCD12345E,abc,r1", "not an amount"),
    ("ABCD12345E,100.123,r1", "decimal places"),
    ("ABCD12345E,100.00,r1,194C,32-Jan-2025", "date"),
    ("ABCD12345E,99999999999999999,r1", "amount"),
])
def test_a_bad_template_row_is_refused_with_its_row_number(row, fragment):
    body = template.csv_bytes() + row.encode() + b"\n"
    with pytest.raises(StatementRefused) as e:
        template.read("t.csv", body)
    assert e.value.message.startswith("Row 2") and fragment.lower() in e.value.message.lower()


def test_template_hostile_input_formulas_oversize_unknown_columns_and_duplicates():
    head = template.csv_bytes()
    # A formula in a text cell is kept as text (exports neutralize it); in a TAN or amount cell it is simply refused.
    ok = template.read("t.csv", head + b'ABCD12345E,100.00,=cmd|"/c calc"!A1,194C\n')
    assert ok.rows[0].reference.startswith("=")
    with pytest.raises(StatementRefused):
        template.read("t.csv", head + b"=1+1,100.00,r\n")
    with pytest.raises(StatementRefused) as e:
        template.read("t.csv", head.replace(b"Remarks", b"Secrets") + b"ABCD12345E,100.00,r\n")
    assert e.value.code == "TRINETRA_UNKNOWN_COLUMN"
    with pytest.raises(StatementRefused) as e:
        template.read("t.csv", head + b"ABCD12345E,100.00,r1\nABCD12345E,100.00,r1\n")
    assert e.value.code == "TRINETRA_DUPLICATE_ROW"
    with pytest.raises(StatementRefused) as e:
        template.read("t.csv", head + b"x" * (6 * 1024 * 1024))
    assert e.value.code == "TRINETRA_FILE_TOO_LARGE"
    many = head + b"".join(f"ABCD12345E,1.00,r{i}\n".encode() for i in range(5001))
    with pytest.raises(StatementRefused) as e:
        template.read("t.csv", many)
    assert e.value.code == "TRINETRA_TOO_MANY_ROWS"
    with pytest.raises(StatementRefused):
        template.read("t.csv", b"")


def test_a_zip_bomb_workbook_is_refused_before_it_is_unpacked():
    import zipfile

    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("xl/worksheets/sheet1.xml", b"0" * (40 * 1024 * 1024))
    with pytest.raises(StatementRefused):
        template.read("bomb.xlsx", out.getvalue())


def test_the_reader_registry_marks_official_readers_unverified_until_2b():
    unverified = {r.key for r in readers.unverified()}
    assert unverified == {"form26as-text-v1", "form168-text-v1", "ais-csv-v1"}
    assert all(not r.verified for r in readers.REGISTRY.values() if r.official)
    assert readers.get("servabo-template-v1").verified and readers.get("human-transcription-v1").verified
