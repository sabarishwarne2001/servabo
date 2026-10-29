"""The Servabo statement template (CSV and XLSX): the customer's own transcription, never an official format.

Columns are fixed and named as Servabo names them. Every row is validated and a bad row is refused with its row number, never
guessed. It goes through the same preview, confirm and import path as typed rows."""

from __future__ import annotations

import csv
import io
from typing import Optional

from app.services.helm import bank_parse
from app.services.trinetra.statements.common import (
    MAX_BYTES, Check, Label, Parsed, Row, StatementRefused, check_limits, fingerprint, label_from_text, parse_amount,
    parse_date, parse_tan,
)

READER = "servabo-template-v1"
PARSER_VERSION = "servabo-template-v1"
COLUMNS = (
    "Deductor TAN",
    "Tax credited (INR)",
    "Row reference",
    "Section or table item (as printed)",
    "Transaction date",
    "Booking status",
    "Amount paid or credited (INR)",
    "Tax deducted (INR)",
    "Remarks",
    "Tax year label (as printed)",
)
REQUIRED = COLUMNS[:2]
GUIDE = (
    "This is your own transcription of a statement you hold. Servabo reads it as typed by you; it is not an official "
    "format. One row per statement line. Deductor TAN and Tax credited are required. Copy the section or table item "
    "exactly as the statement prints it (an old-Act section such as 194Q, or a new-Act Section 393 table item); Servabo "
    "never converts one into the other."
)


def csv_bytes() -> bytes:
    out = io.StringIO()
    csv.writer(out, lineterminator="\n").writerow(COLUMNS)
    return ("﻿" + out.getvalue()).encode("utf-8")


def xlsx_bytes() -> bytes:
    from openpyxl import Workbook

    book = Workbook()
    sheet = book.active
    sheet.title = "Statement rows"
    sheet.append(list(COLUMNS))
    guide = book.create_sheet("How to fill this in")
    guide.append([GUIDE])
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


def _raw_rows(filename: str, data: bytes) -> list[list[str]]:
    if not data:
        raise StatementRefused("The file is empty.", code="TRINETRA_EMPTY_FILE")
    if len(data) > MAX_BYTES:
        raise StatementRefused(f"The file is larger than {MAX_BYTES // (1024 * 1024)} MB.", code="TRINETRA_FILE_TOO_LARGE")
    name = (filename or "").lower()
    try:
        if name.endswith(".xlsx") or data[:2] == b"PK":
            return bank_parse._xlsx_rows(data)  # noqa: SLF001 - the shared, zip-bomb-checked reader
        return bank_parse._csv_rows(data)  # noqa: SLF001
    except bank_parse.StatementError as exc:
        raise StatementRefused(exc.message, code="TRINETRA_UNREADABLE_FILE") from exc


def recognizes(rows: list[list[str]]) -> bool:
    first = next((r for r in rows if any(c for c in r)), [])
    return bool(first) and [c.strip().lower() for c in first[:2]] == [c.lower() for c in COLUMNS[:2]]


def read(filename: str, data: bytes, *, rows: Optional[list[list[str]]] = None) -> Parsed:
    rows = rows if rows is not None else _raw_rows(filename, data)
    start = next((i for i, r in enumerate(rows) if any(c for c in r)), None)
    if start is None:
        raise StatementRefused("The file has no rows.", code="TRINETRA_NO_ROWS")
    header = [c.strip() for c in rows[start]]
    while header and not header[-1]:
        header.pop()
    known = {c.lower(): c for c in COLUMNS}
    unknown = [c for c in header if c.lower() not in known]
    if unknown:
        raise StatementRefused(
            f"The column '{unknown[0][:40]}' is not in the Servabo template. Download the template again and fill it in "
            "without adding or renaming columns.", code="TRINETRA_UNKNOWN_COLUMN")
    positions = {known[c.lower()]: i for i, c in enumerate(header)}
    if len(positions) != len(header):
        raise StatementRefused("A column of the template appears twice.", code="TRINETRA_DUPLICATE_COLUMN")
    missing = [c for c in REQUIRED if c not in positions]
    if missing:
        raise StatementRefused(f"The required column '{missing[0]}' is missing.", code="TRINETRA_MISSING_COLUMN")

    def cell(row: list[str], name: str) -> str:
        i = positions.get(name)
        return row[i].strip() if i is not None and i < len(row) else ""

    parsed_rows: list[Row] = []
    seen: set[tuple] = set()
    labels: set[str] = set()
    for offset, raw in enumerate(rows[start + 1:], start=start + 2):
        if not any(c.strip() for c in raw):
            continue
        if len(raw) > len(header) and any(c.strip() for c in raw[len(header):]):
            raise StatementRefused(f"Row {offset} has more cells than the template has columns.", code="TRINETRA_WIDE_ROW", row=offset)
        try:
            tan = parse_tan(cell(raw, "Deductor TAN"), row=offset)
            credited = parse_amount(cell(raw, "Tax credited (INR)"), row=offset)
            if credited is None:
                raise StatementRefused("The tax credited is empty.", code="TRINETRA_BAD_AMOUNT", row=offset)
            reference = cell(raw, "Row reference")
            row = Row(
                line_no=offset, tan=tan, amount_micros=credited,
                deducted_micros=parse_amount(cell(raw, "Tax deducted (INR)"), row=offset),
                paid_micros=parse_amount(cell(raw, "Amount paid or credited (INR)"), row=offset),
                section=cell(raw, "Section or table item (as printed)")[:60],
                on=parse_date(cell(raw, "Transaction date"), row=offset),
                status=cell(raw, "Booking status")[:10].upper(),
                remarks=cell(raw, "Remarks")[:100],
            )
        except StatementRefused as exc:
            raise StatementRefused(f"Row {offset}: {exc.message}", code=exc.code, row=offset) from exc
        key = (tan, credited, reference or f"row {offset}")
        if reference and key in seen:
            raise StatementRefused(f"Row {offset} repeats an earlier row (same TAN, amount and reference).",
                                   code="TRINETRA_DUPLICATE_ROW", row=offset)
        seen.add(key)
        row.reference = reference or f"row {offset}"
        parsed_rows.append(row)
        text = cell(raw, "Tax year label (as printed)")
        if text:
            labels.add(text)
    check_limits(parsed_rows)
    label: Optional[Label] = None
    if len(labels) > 1:
        raise StatementRefused("The tax year label differs between rows. One file holds one tax year.", code="TRINETRA_MIXED_YEARS")
    if labels:
        label = label_from_text(next(iter(labels)))
        if label is None:
            raise StatementRefused("The tax year label must read like 'FY 2025-26 / AY 2026-27' or 'Tax Year 2026-27'.",
                                   code="TRINETRA_BAD_LABEL")
    return Parsed(
        reader=READER, parser_version=PARSER_VERSION, rows=parsed_rows, label=label, sha256=fingerprint(data),
        mapping=[(c, c) for c in header],
        checks=[Check("rows validated", True, f"{len(parsed_rows)} rows read; every row was checked and none was guessed")],
    )
