"""Hostile files for every reader and both templates (Final 2T, Phase 9). A corpus of the shapes a bad or malicious file takes,
pushed through each reader under every file name that could route to it. The contract for every pair:

  * the answer is a `StatementRefused` (a sentence a person understands) or rows that obey the reader's own rules;
  * never any other exception, never a hang (each read is bounded), never more than MAX_ROWS rows;
  * a parsed row has a well-formed TAN, an integer amount inside the bound and short text: nothing a file said can widen a field;
  * nothing is imported by reading: these functions never touch the database.
"""

import io
import time
import zipfile

import pytest

from app.services.trinetra.domain import MAX_MICROS
from app.services.trinetra.statements import ais, detect, expectations, form26as, template
from app.services.trinetra.statements.common import MAX_ROWS, Parsed, StatementRefused

TAN = "ABCD12345E"
AIS_HEAD = ('"Sr. No.","Information Source","Information Code","Information Description","Transaction Date",'
            '"Amount Paid or Credited","Tax Deducted","Status"\n')
LONG = "A" * 100_000
RTL = "‮"


def _xlsx_bomb() -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("xl/worksheets/sheet1.xml", b"0" * (40 * 1024 * 1024))
    return out.getvalue()


def _xlsx_without_sheets() -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
    return out.getvalue()


CORPUS: dict[str, bytes] = {
    "empty": b"",
    "whitespace": b" \n\t\r\n  \n",
    "nul bytes": b"\x00" * 4096,
    "binary garbage": bytes(range(256)) * 64,
    "latin-1 bytes": "Deductor TAN,Tax credited (INR)\n".encode() + "Müller,10\n".encode("latin-1"),
    "utf-16": "Deductor TAN,Tax credited (INR)\nABCD12345E,10\n".encode("utf-16"),
    "pdf header": b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n" + b"0" * 1000,
    "zip header": b"PK\x03\x04" + b"\x00" * 200,
    "json": b'{"rows": [{"tan": "ABCD12345E", "amount": 10}]}',
    "html": b"<html><script>alert(1)</script><table><tr><td>ABCD12345E</td></tr></table></html>",
    "one giant line": LONG.encode() * 20,
    "ten thousand rows": (template.csv_bytes() + b"".join(f"{TAN},1.00,r{i}\n".encode() for i in range(MAX_ROWS + 5))),
    "formula cells": template.csv_bytes() + f'{TAN},100.00,=cmd|"/c calc"!A1,194C,,,,,,\n'.encode(),
    "formula in tan": template.csv_bytes() + b'=HYPERLINK("http://x"),100.00,r1\n',
    "formula amount": template.csv_bytes() + f"{TAN},=1+1,r1\n".encode(),
    "script in text": template.csv_bytes() + f"{TAN},100.00,<script>alert(1)</script>,\"<img src=x onerror=alert(1)>\"\n".encode(),
    "rtl and zero width": template.csv_bytes() + f"{TAN},100.00,r{RTL}1​,194C\n".encode(),
    "huge amount": template.csv_bytes() + f"{TAN},{'9' * 400},r1\n".encode(),
    "scientific amount": template.csv_bytes() + f"{TAN},1e308,r1\n".encode(),
    "negative infinity": template.csv_bytes() + f"{TAN},-Infinity,r1\n".encode(),
    "nan": template.csv_bytes() + f"{TAN},NaN,r1\n".encode(),
    "currency symbols": template.csv_bytes() + f"{TAN},₹ 1,00,000.50,r1\n".encode(),
    "lowercase tan": template.csv_bytes() + b"abcd12345e,100.00,r1\n",
    "lookalike tan": template.csv_bytes() + "ABCD12345Е,100.00,r1\n".encode(),            # a Cyrillic E
    "tan too long": template.csv_bytes() + b"ABCD12345EE,100.00,r1\n",
    "duplicate rows": template.csv_bytes() + f"{TAN},1.00,r1\n{TAN},1.00,r1\n".encode(),
    "unknown column": template.csv_bytes().replace(b"Remarks", b"Password") + f"{TAN},1.00,r1\n".encode(),
    "mixed delimiters": f"Deductor TAN;Tax credited (INR)\n{TAN};10\n".encode(),
    "only a header": template.csv_bytes(),
    "ais with tcs only": (AIS_HEAD + '1,"X (TAN: ABCD12345E)","TCS-206C","Sale of scrap","15/06/2025","1,000.00","10.00","F"\n').encode(),
    "ais two tax columns": (AIS_HEAD.replace("Tax Deducted", "Tax Deducted at Source\",\"TDS Amount") + "1,x,y,z,a,b,c,d,e\n").encode(),
    "ais mapping bomb": (AIS_HEAD + "\n".join(f'{i},"Acme (TAN: {TAN})","TDS-194C","x","15/06/2025","1.00","1.00","F"'
                                               for i in range(MAX_ROWS + 5))).encode(),
    "26as with two pans": (b"^Permanent Account Number (PAN)^ABCDE1234F^\n^Permanent Account Number (PAN)^ZZZZZ9999Z^\n"),
    "26as no sections": b"^Name of Deductor^TAN of Deductor^Total Amount Paid^Total Tax Deducted^Total TDS Deposited^\n",
    "26as huge field": b"^Name of Deductor^" + LONG.encode() + b"^TAN of Deductor^" + TAN.encode() + b"^\n",
    "xlsx zip bomb": _xlsx_bomb(),
    "xlsx without sheets": _xlsx_without_sheets(),
    "xlsx truncated": b"PK\x03\x04\x14\x00\x00\x00\x08\x00" + b"\x00" * 40,
}
# The same names, as every file name that could route to a reader.
NAMES = ("statement.csv", "statement.txt", "statement.xlsx", "AS.TXT", "no-extension", "x" * 300 + ".csv")
READERS = (None, form26as.READER, ais.READER, template.READER if hasattr(template, "READER") else None)


def _check(parsed: Parsed) -> None:
    assert len(parsed.rows) <= MAX_ROWS
    for row in parsed.rows:
        assert len(row.tan) == 10 and row.tan.isascii() and row.tan[:4].isalpha() and row.tan[4:9].isdigit() and row.tan[9].isalpha()
        assert isinstance(row.amount_micros, int) and abs(row.amount_micros) <= MAX_MICROS
        for text in (row.section, row.reference, row.remarks, row.status):
            assert text is None or len(text) <= 200


@pytest.mark.no_db
@pytest.mark.parametrize("kind", sorted(CORPUS))
@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize("reader", READERS)
def test_every_reader_refuses_or_reads_cleanly_whatever_the_file_says(kind, name, reader):
    started = time.perf_counter()
    try:
        parsed = detect.read(name, CORPUS[kind], reader=reader)
    except StatementRefused as exc:
        assert exc.message and exc.code.startswith("TRINETRA_")
    else:
        _check(parsed)
    assert time.perf_counter() - started < 5, f"{kind} / {name} / {reader} was slow"


@pytest.mark.no_db
@pytest.mark.parametrize("kind", sorted(CORPUS))
@pytest.mark.parametrize("name", ("t.csv", "t.xlsx", "t.txt"))
def test_the_expectations_template_refuses_or_reads_cleanly_whatever_the_file_says(kind, name):
    started = time.perf_counter()
    try:
        lines = expectations.read(name, CORPUS[kind])
    except StatementRefused as exc:
        assert exc.message and exc.code.startswith("TRINETRA_")
    else:
        assert len(lines) <= MAX_ROWS
        for line in lines:
            assert len(line.tan) == 10 and isinstance(line.amount_micros, int) and abs(line.amount_micros) <= MAX_MICROS
            assert len(line.reference) <= 200 and len(line.section) <= 200
    assert time.perf_counter() - started < 5, f"{kind} / {name} was slow"
