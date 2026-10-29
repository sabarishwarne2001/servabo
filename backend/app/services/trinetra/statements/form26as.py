"""The Form 26AS / Form 168 text download from TRACES (caret-delimited text), TDS part only.

UNVERIFIED until Final session 2B proves it on the owner's own downloaded file (registry: `readers.py`). The layout below was
written from secondary sources (see docs/trinetra/LEGAL-SOURCES.md): the official TRACES pages could not be reached from the
build environment. So this reader is strict instead of clever. It finds each block by the column titles it prints, never by
fixed positions; it checks its own structure (every deductor's declared totals against the rows read under it); and it refuses
a column it does not know, a Part heading it does not know, a total that disagrees, a second PAN or a mixed tax-year label.

What it reads: the file header (PAN, financial and assessment year, or a Tax Year), then in the TDS part each deductor line
(name, TAN, declared totals) and the transaction lines under it (section or table item, transaction date, booking status,
booking date, remarks, amount paid or credited, tax deducted, TDS deposited). The section or table item is kept exactly as
printed. Tax collected at source and the other parts are not read. A password-protected zip or PDF is refused: use the text
download itself."""

from __future__ import annotations

import re
from typing import Optional

from app.services.trinetra.statements.common import (
    MAX_BYTES, TAN, Check, Parsed, Row, StatementRefused, check_limits, fingerprint, label_from_text, mask_tan, normalize_pan,
    parse_amount, parse_date, parse_tan,
)

READER = "form26as-text-v1"
PARSER_VERSION = "form26as-text-v1"

DEDUCTOR_COLUMNS = {
    "sr no": "n", "name of deductor": "name", "tan of deductor": "tan", "total amount paid credited": "paid",
    "total tax deducted": "deducted", "total tds deposited": "deposited", "total tax deposited": "deposited",
}
TRANSACTION_COLUMNS = {
    "sr no": "n", "section": "section", "transaction date": "on", "status of booking": "status",
    "date of booking": "booked_on", "remarks": "remarks", "amount paid credited": "paid", "tax deducted": "deducted",
    "tds deposited": "deposited", "tax deposited": "deposited",
}
HEADER_COLUMNS = {
    "file creation date", "permanent account number pan", "current status of pan", "financial year", "assessment year",
    "tax year", "name of assessee", "address line1", "address line2", "address line3", "address line4", "address line5",
    "statecode", "pincode", "state", "pin code",
}
#: Part headings: TDS (read) and the parts that are recognised but deliberately not read.
_PART = re.compile(r"(?i)^part[\s\-]*([a-z]\d?|[ivx]+)\b")
READ_PARTS = {"a", "i"}
KNOWN_PARTS = {"a", "a1", "a2", "b", "c", "d", "e", "f", "g", "i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x"}


def _norm(title: str) -> str:
    text = re.sub(r"(?i)\(\s*rs\.?\s*\)", " ", title)
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", text.lower())).strip()


def _decode(data: bytes) -> str:
    if data[:4] == b"%PDF":
        raise StatementRefused(
            "This is a PDF. TRACES protects its PDF statements with a password and Servabo does not open them. Download "
            "the statement as a text file (or the AIS as CSV) instead and upload that.", code="TRINETRA_PDF_STATEMENT")
    if data[:2] == b"PK":
        raise StatementRefused(
            "This is a zip file. TRACES protects its text download's zip with a password (your date of birth) and Servabo "
            "never handles passwords. Extract the .txt file from it yourself and upload the text file.",
            code="TRINETRA_ZIP_STATEMENT")
    if b"\x00" in data:
        raise StatementRefused("This file is not a text file.", code="TRINETRA_NOT_TEXT")
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise StatementRefused("This file is not readable text.", code="TRINETRA_NOT_TEXT")


def _cells(line: str) -> list[str]:
    cells = [c.strip() for c in line.rstrip("\r\n").split("^")]
    while cells and not cells[0]:
        cells.pop(0)
    while cells and not cells[-1]:
        cells.pop()
    return cells


def recognizes(data: bytes) -> bool:
    head = data[:8000].decode("utf-8", "ignore").lower()
    return head.count("^") >= 3 and ("tan of deductor" in head or "form 26as" in head or "form 168" in head
                                      or "annual tax statement" in head)


def read(filename: str, data: bytes) -> Parsed:
    if not data:
        raise StatementRefused("The file is empty.", code="TRINETRA_EMPTY_FILE")
    text = _decode(data)  # refuses PDF and zip first, whatever the size
    if len(data) > MAX_BYTES:
        raise StatementRefused(f"The file is larger than {MAX_BYTES // (1024 * 1024)} MB.", code="TRINETRA_FILE_TOO_LARGE")
    lines = text.splitlines()
    if len(lines) > 200_000:
        raise StatementRefused("The file has far more lines than a statement holds.", code="TRINETRA_TOO_MANY_ROWS")

    label_text: list[str] = []
    file_pans: set[str] = set()
    rows: list[Row] = []
    ignored: dict[str, int] = {}
    deductors: list[dict] = []
    current: Optional[dict] = None
    mode: Optional[str] = None            # "header", "deductor", "transaction"
    columns: dict[int, str] = {}
    deductor_columns: dict[int, str] = {}
    deductor_width = 0
    header_titles: list[str] = []
    reading = False                      # inside a TDS part we read
    part_name = ""
    seen_headings: list[str] = []

    for number, line in enumerate(lines, start=1):
        cells = _cells(line)
        if not cells:
            continue
        titles = [_norm(c) for c in cells]
        # A part heading: one cell, "PART-A - Details of Tax Deducted at Source".
        if len(cells) == 1 and _PART.match(cells[0]):
            key = _PART.match(cells[0]).group(1).lower()
            if key not in KNOWN_PARTS:
                raise StatementRefused(f"Line {number}: the part '{cells[0][:40]}' is not one this reader knows. Nothing was read.",
                                       code="TRINETRA_UNKNOWN_PART", row=number)
            reading = key in READ_PARTS
            part_name = cells[0][:60]
            seen_headings.append(part_name)
            mode, current = None, None
            if not reading:
                ignored.setdefault(part_name, 0)
            continue
        # The file header block (before any part).
        if not seen_headings and sum(1 for t in titles if t in HEADER_COLUMNS) >= 3:
            mode, header_titles = "header", titles
            continue
        if mode == "header" and not seen_headings:
            values = dict(zip(header_titles, cells))
            pan = normalize_pan(values.get("permanent account number pan", ""))
            if pan:
                file_pans.add(pan)
            label_text.append(" ".join(f"{k} {v}" for k, v in values.items() if k in ("financial year", "assessment year", "tax year")))
            mode = None
            continue
        if not seen_headings:
            label_text.append(" ".join(cells))     # a title line such as "Form 168 ... Tax Year 2026-27"
            continue
        # Column header lines.
        if sum(1 for t in titles if t in DEDUCTOR_COLUMNS) >= 4 and "tan of deductor" in titles:
            unknown = [c for c, t in zip(cells, titles) if t not in DEDUCTOR_COLUMNS]
            if unknown and reading:
                raise StatementRefused(f"Line {number}: the column '{unknown[0][:40]}' is not one this reader knows.",
                                       code="TRINETRA_UNKNOWN_COLUMN", row=number)
            mode, columns = "deductor", {i: DEDUCTOR_COLUMNS[t] for i, t in enumerate(titles) if t in DEDUCTOR_COLUMNS}
            deductor_columns, deductor_width = dict(columns), len(titles)
            continue
        if sum(1 for t in titles if t in TRANSACTION_COLUMNS) >= 5 and "section" in titles:
            unknown = [c for c, t in zip(cells, titles) if t not in TRANSACTION_COLUMNS]
            if unknown and reading:
                raise StatementRefused(f"Line {number}: the column '{unknown[0][:40]}' is not one this reader knows.",
                                       code="TRINETRA_UNKNOWN_COLUMN", row=number)
            mode, columns = "transaction", {i: TRANSACTION_COLUMNS[t] for i, t in enumerate(titles) if t in TRANSACTION_COLUMNS}
            continue
        if not reading:
            ignored[part_name] = ignored.get(part_name, 0) + 1
            continue
        # Data lines of a part we read. A deductor line may follow transaction lines without its header repeated: it has the
        # deductor header's width and a TAN where that header has one.
        if mode == "transaction" and deductor_columns and len(cells) == deductor_width:
            tan_at = next(i for i, name in deductor_columns.items() if name == "tan")
            if TAN.fullmatch(cells[tan_at].upper()):
                mode = "deductor"
        if mode == "deductor":
            columns = deductor_columns
            values = {columns[i]: c for i, c in enumerate(cells) if i in columns}
            if not re.fullmatch(r"\d+", values.get("n", "")):
                raise StatementRefused(f"Line {number}: a deductor line was expected here.", code="TRINETRA_UNEXPECTED_LINE", row=number)
            try:
                current = {
                    "tan": parse_tan(values.get("tan", ""), row=number),
                    "paid": parse_amount(values.get("paid", ""), row=number),
                    "deducted": parse_amount(values.get("deducted", ""), row=number),
                    "deposited": parse_amount(values.get("deposited", ""), row=number),
                    "line": number, "rows": [],
                }
            except StatementRefused as exc:
                raise StatementRefused(f"Line {number}: {exc.message}", code=exc.code, row=number) from exc
            deductors.append(current)
        elif mode == "transaction":
            if current is None:
                raise StatementRefused(f"Line {number}: transaction lines come before any deductor line.", code="TRINETRA_UNEXPECTED_LINE", row=number)
            values = {columns[i]: c for i, c in enumerate(cells) if i in columns}
            if not re.fullmatch(r"\d+", values.get("n", "")):
                raise StatementRefused(f"Line {number}: a transaction line was expected here.", code="TRINETRA_UNEXPECTED_LINE", row=number)
            try:
                deducted = parse_amount(values.get("deducted", ""), row=number)
                deposited = parse_amount(values.get("deposited", ""), row=number)
                credit = deposited if deposited is not None else deducted
                if credit is None:
                    raise StatementRefused("The tax deducted and the TDS deposited are both empty.", code="TRINETRA_BAD_AMOUNT", row=number)
                row = Row(line_no=number, tan=current["tan"], amount_micros=credit, deducted_micros=deducted,
                          paid_micros=parse_amount(values.get("paid", ""), row=number),
                          section=values.get("section", "")[:60], on=parse_date(values.get("on", ""), row=number),
                          status=values.get("status", "")[:10].upper(), booked_on=parse_date(values.get("booked_on", ""), row=number),
                          remarks=values.get("remarks", "")[:100], part=part_name, reference=f"line {number}")
            except StatementRefused as exc:
                raise StatementRefused(f"Line {number}: {exc.message}", code=exc.code, row=number) from exc
            current["rows"].append(row)
            rows.append(row)
        else:
            raise StatementRefused(f"Line {number}: a line this reader cannot place.", code="TRINETRA_UNEXPECTED_LINE", row=number)

    if not seen_headings:
        raise StatementRefused("No part of the statement could be recognised. This does not look like a Form 26AS or Form 168 "
                               "text download; nothing was read.", code="TRINETRA_UNRECOGNIZED_LAYOUT")
    if len(file_pans) > 1:
        raise StatementRefused("The file names more than one PAN. Nothing was read.", code="TRINETRA_MIXED_PAN")
    labels = {l.text for l in (label_from_text(t) for t in label_text) if l}
    if len(labels) > 1:
        raise StatementRefused("The file states more than one tax year. Nothing was read.", code="TRINETRA_MIXED_YEARS")
    label = label_from_text(" ".join(label_text)) if labels else None
    check_limits(rows)

    checks: list[Check] = []
    for d in deductors:
        subtotal = {k: sum((r.__dict__[f] or 0) for r in d["rows"]) for k, f in (("paid", "paid_micros"), ("deducted", "deducted_micros"))}
        deposited = sum((r.amount_micros) for r in d["rows"])
        for name, declared, computed in (("amount paid or credited", d["paid"], subtotal["paid"]),
                                         ("tax deducted", d["deducted"], subtotal["deducted"]),
                                         ("TDS deposited", d["deposited"], deposited)):
            if declared is None:
                continue
            ok = declared == computed
            checks.append(Check(f"{mask_tan(d['tan'])}: {name}", ok, "agrees with the file's own total" if ok else
                                f"the file declares {declared / 1_000_000:,.2f} but its rows add up to {computed / 1_000_000:,.2f}"))
            if not ok:
                raise StatementRefused(
                    f"The file's own total for {mask_tan(d['tan'])} ({name}: {declared / 1_000_000:,.2f}) does not match the "
                    f"rows read under it ({computed / 1_000_000:,.2f}). The layout may differ from what this reader expects, "
                    "so nothing was imported.", code="TRINETRA_TOTAL_MISMATCH", row=d["line"])
    if not checks:
        checks.append(Check("file totals", True, "the file declared no totals to check"))
    return Parsed(
        # A Tax Year (Income-tax Act 2025) file is Form 168's; a financial / assessment year file is Form 26AS's.
        reader="form168-text-v1" if label is not None and label.kind == "TAX_YEAR" else READER,
        parser_version=PARSER_VERSION, rows=rows, label=label, file_pan=next(iter(file_pans), None),
        checks=checks, sha256=fingerprint(data),
        ignored=[f"{name}: not read" for name in ignored],
        mapping=[("TAN of Deductor", "deductor TAN"), ("Section", "section or table item, as printed"),
                 ("Transaction Date", "transaction date"), ("Status of Booking", "booking status"),
                 ("Tax Deducted", "tax deducted"), ("TDS Deposited", "tax credited (used for matching)")],
    )
