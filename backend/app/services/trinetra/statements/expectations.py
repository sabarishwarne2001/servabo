"""The expectations template (CSV and Excel): the bridge for Tally users (Final 2T, Phase 4).

Their accountant exports the receipts with TDS and fills this in: invoice reference, customer TAN, expected TDS, an optional
section text. Each row is matched to a canonical invoice; a bad row is refused with its row number and reason, never guessed.
A matched row only becomes a SUGGESTION: a person still accepts it."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from typing import Optional

from app.services.helm import bank_parse
from app.services.trinetra.statements.common import (
    MAX_BYTES, MAX_ROWS, StatementRefused, parse_amount, parse_tan,
)

COLUMNS = ("Invoice reference", "Customer TAN", "Expected TDS (INR)", "Section text (optional)")
GUIDE = ("One row per invoice. Invoice reference is the number printed on the sales invoice. Customer TAN is your customer's "
         "TAN. Expected TDS is the amount your customer withheld or will withhold, from your records. Copy the section text "
         "as your records print it. Servabo only suggests: you accept each one yourself.")


@dataclass
class Line:
    row: int
    reference: str
    tan: str
    amount_micros: int
    section: str


def csv_bytes() -> bytes:
    out = io.StringIO()
    csv.writer(out, lineterminator="\n").writerow(COLUMNS)
    return ("﻿" + out.getvalue()).encode("utf-8")


def xlsx_bytes() -> bytes:
    from openpyxl import Workbook

    book = Workbook()
    book.active.title = "Expected TDS"
    book.active.append(list(COLUMNS))
    book.create_sheet("How to fill this in").append([GUIDE])
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


def read(filename: str, data: bytes) -> list[Line]:
    if not data:
        raise StatementRefused("The file is empty.", code="TRINETRA_EMPTY_FILE")
    if len(data) > MAX_BYTES:
        raise StatementRefused(f"The file is larger than {MAX_BYTES // (1024 * 1024)} MB.", code="TRINETRA_FILE_TOO_LARGE")
    name = (filename or "").lower()
    try:
        rows = bank_parse._xlsx_rows(data) if name.endswith(".xlsx") or data[:2] == b"PK" else bank_parse._csv_rows(data)  # noqa: SLF001
    except bank_parse.StatementError as exc:
        raise StatementRefused(exc.message, code="TRINETRA_UNREADABLE_FILE") from exc
    start = next((i for i, r in enumerate(rows) if any(c for c in r)), None)
    if start is None:
        raise StatementRefused("The file has no rows.", code="TRINETRA_NO_ROWS")
    header = [c.strip() for c in rows[start]]
    while header and not header[-1]:
        header.pop()
    known = {c.lower(): c for c in COLUMNS}
    unknown = [c for c in header if c.lower() not in known]
    if unknown:
        raise StatementRefused(f"The column '{unknown[0][:40]}' is not in the expectations template. Download the template "
                               "again and fill it in without adding or renaming columns.", code="TRINETRA_UNKNOWN_COLUMN")
    pos = {known[c.lower()]: i for i, c in enumerate(header)}
    missing = [c for c in COLUMNS[:3] if c not in pos]
    if missing or len(pos) != len(header):
        raise StatementRefused(f"The required column '{missing[0]}' is missing or repeated." if missing else
                               "A column appears twice.", code="TRINETRA_MISSING_COLUMN")

    def cell(raw, name):
        i = pos.get(name)
        return raw[i].strip() if i is not None and i < len(raw) else ""

    out: list[Line] = []
    seen: set[str] = set()
    for number, raw in enumerate(rows[start + 1:], start=start + 2):
        if not any(c.strip() for c in raw):
            continue
        try:
            reference = cell(raw, "Invoice reference")
            if not reference:
                raise StatementRefused("The invoice reference is empty.", code="TRINETRA_BAD_REFERENCE", row=number)
            amount = parse_amount(cell(raw, "Expected TDS (INR)"), row=number)
            if not amount or amount <= 0:
                raise StatementRefused("The expected TDS must be a positive amount.", code="TRINETRA_BAD_AMOUNT", row=number)
            key = reference.casefold()
            if key in seen:
                raise StatementRefused("This invoice reference repeats an earlier row.", code="TRINETRA_DUPLICATE_ROW", row=number)
            seen.add(key)
            out.append(Line(number, reference[:100], parse_tan(cell(raw, "Customer TAN"), row=number), amount,
                            cell(raw, "Section text (optional)")[:100]))
        except StatementRefused as exc:
            raise StatementRefused(f"Row {number}: {exc.message}", code=exc.code, row=number) from exc
        if len(out) > MAX_ROWS:
            raise StatementRefused(f"The template has more than {MAX_ROWS:,} rows.", code="TRINETRA_TOO_MANY_ROWS")
    if not out:
        raise StatementRefused("The template has no rows to read.", code="TRINETRA_NO_ROWS")
    return out
