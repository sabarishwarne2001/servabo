"""The AIS "TDS/TCS information" CSV, TDS rows only (TCS stays out).

UNVERIFIED until Final session 2B proves it on the owner's own downloaded file. The portal's column headings could not be
read from the build environment (docs/trinetra/LEGAL-SOURCES.md), so this reader finds each column by what its heading
says, shows the reviewer the mapping (every column and what Servabo takes it to mean) and takes it only after the reviewer
confirms. It refuses a file where a needed column is missing or two columns could be the same thing, a row whose TAN
cannot be read, an amount that is not an amount, and a total row that disagrees with the rows above it. A row whose
information code names tax collected at source (TCS) is counted and left out."""

from __future__ import annotations

import re
from typing import Optional

from app.services.helm import bank_parse
from app.services.trinetra.statements.common import (
    MAX_BYTES, Check, Parsed, Row, StatementRefused, check_limits, find_tan, fingerprint, label_from_text, parse_amount,
    parse_date, parse_tan,
)

READER = "ais-csv-v1"
PARSER_VERSION = "ais-csv-v1"

#: What each column's heading may say. Order matters only for the preview; a heading matching two roles is ambiguous.
ROLES: dict[str, re.Pattern] = {
    "source": re.compile(r"(?i)\b(information source|deductor|collector|source of information|source)\b"),
    "tan": re.compile(r"(?i)\b(tan|deductor tan|tan of deductor)\b"),
    "code": re.compile(r"(?i)\b(information code|info code|code|section)\b"),
    "description": re.compile(r"(?i)\b(information description|description)\b"),
    "date": re.compile(r"(?i)\b(transaction date|date of (payment|credit|deduction)|date)\b"),
    "paid": re.compile(r"(?i)\b(amount paid|paid or credited|payment|amount credited)\b"),
    "deducted": re.compile(r"(?i)\b(tax deducted|tds deducted|tax deducted at source|tds amount|amount of tax|tax amount|tds)\b"),
    "status": re.compile(r"(?i)\b(status|status of booking)\b"),
}
_TCS = re.compile(r"(?i)\b(tcs|tax collected at source|206c)\b")
_TOTAL = re.compile(r"(?i)^\W*(grand\s+)?total\b")


def recognizes(rows: list[list[str]]) -> bool:
    head = " ".join(" ".join(r) for r in rows[:12]).lower()
    return ("information" in head and ("tds" in head or "tcs" in head)) and ("source" in head or "tan" in head)


def propose_mapping(columns: list[str]) -> dict[str, Optional[int]]:
    """Which column is which, by heading. A role two columns could claim is left None (ambiguous): the reviewer chooses."""
    found: dict[str, list[int]] = {role: [] for role in ROLES}
    for i, title in enumerate(columns):
        for role, pattern in ROLES.items():
            if pattern.search(title):
                found[role].append(i)
    # "TDS" alone is also in "TDS/TCS Information"; prefer the explicit amount headings.
    amount_like = [i for i in found["deducted"] if re.search(r"(?i)amount|value|deducted", columns[i])]
    if amount_like:
        found["deducted"] = amount_like
    mapping: dict[str, Optional[int]] = {}
    for role, indexes in found.items():
        mapping[role] = indexes[0] if len(indexes) == 1 else None
    return mapping


def read(filename: str, data: bytes, *, mapping: Optional[dict[str, Optional[int]]] = None) -> Parsed:
    if not data:
        raise StatementRefused("The file is empty.", code="TRINETRA_EMPTY_FILE")
    if len(data) > MAX_BYTES:
        raise StatementRefused(f"The file is larger than {MAX_BYTES // (1024 * 1024)} MB.", code="TRINETRA_FILE_TOO_LARGE")
    if data[:4] == b"%PDF":
        raise StatementRefused("This is a PDF. Download the AIS information as CSV and upload that; Servabo does not read "
                               "PDF statements.", code="TRINETRA_PDF_STATEMENT")
    try:
        rows = bank_parse._csv_rows(data)  # noqa: SLF001 - the shared, size-limited CSV reader
    except bank_parse.StatementError as exc:
        raise StatementRefused(exc.message, code="TRINETRA_UNREADABLE_FILE") from exc
    start = next((i for i, r in enumerate(rows) if sum(1 for c in r if c) >= 3 and any(re.search(r"(?i)tan|source|code", c) for c in r)), None)
    if start is None:
        raise StatementRefused("No header row with deductor and tax columns could be found.", code="TRINETRA_UNRECOGNIZED_LAYOUT")
    header = [c.strip() for c in rows[start]]
    while header and not header[-1]:
        header.pop()
    proposed = propose_mapping(header)
    chosen = dict(proposed)
    if mapping:
        for role, index in mapping.items():
            if role not in ROLES:
                raise StatementRefused(f"'{role}' is not something a column can mean here.", code="TRINETRA_BAD_MAPPING")
            if index is not None and not (0 <= index < len(header)):
                raise StatementRefused("The mapping points past the last column.", code="TRINETRA_BAD_MAPPING")
            chosen[role] = index
    if chosen["deducted"] is None:
        raise StatementRefused("Which column holds the tax amount could not be told" + (
            " (two columns could be it)" if any(ROLES["deducted"].search(h) for h in header) else "") +
            ". Choose it in the mapping.", code="TRINETRA_AMBIGUOUS_COLUMNS",
            columns={"proposed": proposed, "chosen": chosen, "columns": header})
    if chosen["tan"] is None and chosen["source"] is None:
        raise StatementRefused("No column holds the deductor's TAN or name and TAN. Choose it in the mapping.",
                               code="TRINETRA_AMBIGUOUS_COLUMNS", columns={"proposed": proposed, "chosen": chosen, "columns": header})
    claimed = [i for i in chosen.values() if i is not None]
    if len(claimed) != len(set(claimed)):
        raise StatementRefused("One column was chosen for two meanings. Choose each column once.", code="TRINETRA_BAD_MAPPING")

    def cell(row: list[str], role: str) -> str:
        i = chosen.get(role)
        return row[i].strip() if i is not None and i < len(row) else ""

    parsed: list[Row] = []
    tcs = 0
    declared_total: Optional[int] = None
    for number, raw in enumerate(rows[start + 1:], start=start + 2):
        if not any(c.strip() for c in raw):
            continue
        first = next((c for c in raw if c.strip()), "")
        if _TOTAL.match(first):
            amount_text = cell(raw, "deducted") or next((c for c in reversed(raw) if c.strip() and re.search(r"\d", c)), "")
            declared_total = parse_amount(amount_text, row=number)
            continue
        code, description = cell(raw, "code"), cell(raw, "description")
        if _TCS.search(f"{code} {description}"):
            tcs += 1
            continue
        try:
            tan_text = cell(raw, "tan") or ""
            tan = parse_tan(tan_text, row=number) if tan_text else (find_tan(cell(raw, "source")) or "")
            if not tan:
                raise StatementRefused("The deductor's TAN could not be read from this row.", code="TRINETRA_BAD_TAN", row=number)
            amount = parse_amount(cell(raw, "deducted"), row=number)
            if amount is None:
                raise StatementRefused("The tax amount is empty.", code="TRINETRA_BAD_AMOUNT", row=number)
            section = re.sub(r"(?i)^\s*(tds|tcs)\s*[-:/ ]*", "", code)[:60] or code[:60]
            parsed.append(Row(line_no=number, tan=tan, amount_micros=amount, deducted_micros=amount,
                              paid_micros=parse_amount(cell(raw, "paid"), row=number), section=section,
                              on=parse_date(cell(raw, "date"), row=number), status=cell(raw, "status")[:10].upper(),
                              remarks=description[:100], part="TDS", reference=f"row {number}"))
        except StatementRefused as exc:
            raise StatementRefused(f"Row {number}: {exc.message}", code=exc.code, row=number) from exc
    check_limits(parsed)
    checks = [Check("rows validated", True, f"{len(parsed)} TDS rows read; every row was checked and none was guessed")]
    if declared_total is not None:
        total = sum(r.amount_micros for r in parsed)
        ok = declared_total == total
        checks.append(Check("file total", ok, "agrees with the file's own total" if ok else
                            f"the file declares {declared_total / 1_000_000:,.2f} but its TDS rows add up to {total / 1_000_000:,.2f}"))
        if not ok:
            raise StatementRefused(f"The file's own total ({declared_total / 1_000_000:,.2f}) does not match the TDS rows read "
                                   f"({total / 1_000_000:,.2f}). Nothing was imported.", code="TRINETRA_TOTAL_MISMATCH")
    else:
        checks.append(Check("file total", True, "the file has no total row to check"))
    names = {role: header[i] for role, i in chosen.items() if i is not None}
    meaning = {"source": "deductor name (and TAN)", "tan": "deductor TAN", "code": "information code (section or table item)",
               "description": "description", "date": "transaction date", "paid": "amount paid or credited",
               "deducted": "tax amount (used for matching)", "status": "booking status"}
    label = label_from_text(" ".join(" ".join(r) for r in rows[:start]))
    return Parsed(
        reader=READER, parser_version=PARSER_VERSION, rows=parsed, label=label, checks=checks, sha256=fingerprint(data),
        ignored=[f"{tcs} tax-collected-at-source (TCS) row(s) left out"] if tcs else [],
        mapping=[(names[r], meaning[r]) for r in ROLES if r in names],
        columns_info={"proposed": proposed, "chosen": chosen, "columns": header},
    )
