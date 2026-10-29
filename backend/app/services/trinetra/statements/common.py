"""What every statement reader produces, and the checks they share (Final 2T, Phase 3).

A reader turns a file into a `Parsed`: rows read exactly as printed, the tax-year label exactly as the file states it, the
file's own declared totals and the checks against them. It never guesses: a layout it does not recognise, an unknown column,
a total that disagrees with the rows it read, or an ambiguous mapping is a `StatementRefused` with a plain sentence.
Nothing here touches the database; the same `Parsed` goes through the same preview, confirm and import path as typed rows."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Optional

from app.services.trinetra.domain import MAX_MICROS

#: One statement carries at most this many rows (an annual statement of a distributor is a few hundred to a few thousand).
MAX_ROWS = 5_000
#: The largest statement file accepted (the bank-statement reader's bound, which also bounds the zip checks).
MAX_BYTES = 5 * 1024 * 1024
TAN = re.compile(r"[A-Z]{4}[0-9]{5}[A-Z]")
_TAN_IN_TEXT = re.compile(r"(?<![A-Z0-9])([A-Z]{4}[0-9]{5}[A-Z])(?![A-Z0-9])")


class StatementRefused(ValueError):
    """The file is refused, in a sentence a person understands. Nothing was read into a statement."""

    def __init__(self, message: str, *, code: str = "TRINETRA_STATEMENT_REFUSED", row: Optional[int] = None,
                 columns: Optional[dict] = None) -> None:
        super().__init__(message)
        self.message, self.code, self.row = message, code, row
        #: For a refusal the reviewer can fix by choosing columns: the headings and what was proposed (never a data row).
        self.columns = columns


@dataclass
class Row:
    """One statement row as printed. Money is in millionths; a negative amount is kept (a reversal or correction)."""

    line_no: int
    tan: str
    #: The tax credited to the entity: TDS deposited when printed, else tax deducted.
    amount_micros: int
    deducted_micros: Optional[int] = None
    paid_micros: Optional[int] = None
    section: str = ""
    on: Optional[date] = None
    status: str = ""
    booked_on: Optional[date] = None
    remarks: str = ""
    part: str = ""
    #: The row's own reference: a typed reference, or "row N" of the file. Distinct per row.
    reference: str = ""


@dataclass
class Label:
    """The tax-year label as the file states it. `kind` is never converted: FY/AY years stay FY/AY, Tax Years stay Tax Years."""

    kind: str  # "FY_AY" (a financial year and its assessment year) or "TAX_YEAR" (Income-tax Act 2025)
    text: str
    #: The year the label starts in: FY 2025-26 / AY 2026-27 is 2025; Tax Year 2026-27 is 2026.
    year: int


@dataclass
class Check:
    name: str
    ok: bool
    detail: str


@dataclass
class Parsed:
    reader: str
    parser_version: str
    rows: list[Row]
    label: Optional[Label] = None
    #: The PAN printed in the file, normalized (never stored or logged); compared with the entity's PAN.
    file_pan: Optional[str] = None
    checks: list[Check] = field(default_factory=list)
    #: What was deliberately not read, in words ("12 TCS rows", "Part C").
    ignored: list[str] = field(default_factory=list)
    #: (column as in the file, what TRINETRA takes it to mean) for the mapping preview.
    mapping: list[tuple[str, str]] = field(default_factory=list)
    #: For a reader that finds its columns by heading: the columns, what was proposed and what was chosen (indexes).
    columns_info: Optional[dict] = None
    sha256: str = ""

    @property
    def total_micros(self) -> int:
        return sum(r.amount_micros for r in self.rows)


def fingerprint(data: bytes) -> str:
    return hashlib.sha256(data or b"").hexdigest()


_MONEY = re.compile(r"^[-+]?\d+(?:\.\d+)?$")


def parse_amount(text: str, *, row: Optional[int] = None) -> Optional[int]:
    """'1,00,000.50', 'Rs. 500', '(500.00)' or '-500' in millionths, or None for an empty or dash cell. Never a float."""
    raw = (text or "").replace(" ", " ").strip()
    if raw in ("", "-", "--", "—", "NA", "N/A", "nil", "Nil", "NIL"):
        return None
    negative = raw.startswith("(") and raw.endswith(")")
    cleaned = re.sub(r"(?i)^(rs\.?|inr|₹)\s*", "", raw.strip("()")).replace(",", "").replace(" ", "")
    if not _MONEY.match(cleaned):
        raise StatementRefused(f"'{raw[:30]}' is not an amount.", code="TRINETRA_BAD_AMOUNT", row=row)
    try:
        value = Decimal(cleaned)
    except InvalidOperation as exc:  # pragma: no cover - the pattern already ensures it parses
        raise StatementRefused(f"'{raw[:30]}' is not an amount.", code="TRINETRA_BAD_AMOUNT", row=row) from exc
    if value.as_tuple().exponent < -2:
        raise StatementRefused(f"'{raw[:30]}' has more than two decimal places; rupees and paise only.",
                               code="TRINETRA_BAD_AMOUNT", row=row)
    micros = int(value * 1_000_000)
    if negative:
        micros = -micros
    if abs(micros) > MAX_MICROS:
        raise StatementRefused("An amount is larger than the supported bound.", code="TRINETRA_BAD_AMOUNT", row=row)
    return micros


_MONTHS = {m: i + 1 for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"))}


def parse_date(text: str, *, row: Optional[int] = None) -> Optional[date]:
    """'15-Jun-2025', '15/06/2025' or '2025-06-15' (day first when numeric: Indian statements) or None for empty."""
    raw = (text or "").strip()
    if raw in ("", "-", "--", "—", "NA", "N/A"):
        return None
    for pattern, build in (
        (r"^(\d{1,2})[-/ ]([A-Za-z]{3})[a-z]*[-/ ,]+(\d{4})$", lambda m: (int(m[3]), _MONTHS.get(m[2].lower()), int(m[1]))),
        (r"^(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})$", lambda m: (int(m[3]), int(m[2]), int(m[1]))),
        (r"^(\d{4})-(\d{2})-(\d{2})(?:[ T].*)?$", lambda m: (int(m[1]), int(m[2]), int(m[3]))),
    ):
        match = re.match(pattern, raw)
        if match:
            y, mth, d = build(match)
            try:
                return date(y, mth, d)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                break
    raise StatementRefused(f"'{raw[:30]}' is not a date the reader can be sure of.", code="TRINETRA_BAD_DATE", row=row)


def parse_tan(text: str, *, row: Optional[int] = None) -> str:
    value = re.sub(r"[\s\-]", "", (text or "")).upper()
    if not value.isascii() or not TAN.fullmatch(value):
        raise StatementRefused("A deductor TAN is not in the TAN format (four letters, five digits, one letter).",
                               code="TRINETRA_BAD_TAN", row=row)
    return value


def find_tan(text: str) -> Optional[str]:
    """The one TAN inside a cell such as 'ACME LTD (DELA12345E)', or None when there is none or more than one."""
    found = {m.group(1) for m in _TAN_IN_TEXT.finditer((text or "").upper())}
    return next(iter(found)) if len(found) == 1 else None


def label_from_text(text: str) -> Optional[Label]:
    """The tax-year label as printed: 'Tax Year 2026-27', or 'Financial Year 2025-26' (with its Assessment Year). Never
    converted into the other. None when the text states none."""
    flat = re.sub(r"\s+", " ", text or "")
    new = re.search(r"(?i)\btax year\D{0,12}((?:20)\d\d)\s*[-–/]\s*(\d\d)\b", flat)
    if new:
        return Label("TAX_YEAR", f"Tax Year {new.group(1)}-{new.group(2)}", int(new.group(1)))
    old = re.search(r"(?i)\b(?:financial year|fy)\D{0,12}((?:20)\d\d)\s*[-–/]\s*(\d\d)\b", flat)
    if old:
        year = int(old.group(1))
        assessment = re.search(r"(?i)\b(?:assessment year|ay)\D{0,12}((?:20)\d\d)\s*[-–/]\s*(\d\d)\b", flat)
        text_ = f"FY {old.group(1)}-{old.group(2)}" + (f" / AY {assessment.group(1)}-{assessment.group(2)}" if assessment else "")
        return Label("FY_AY", text_, year)
    return None


def mask_tan(tan: str) -> str:
    return "******" + tan[-4:]


def normalize_pan(raw) -> Optional[str]:
    from app.services.trinetra.seller import normalize_pan as _normalize

    return _normalize(raw)


def check_limits(parsed_rows: list[Row]) -> None:
    if not parsed_rows:
        raise StatementRefused("No statement rows could be read from the file.", code="TRINETRA_NO_ROWS")
    if len(parsed_rows) > MAX_ROWS:
        raise StatementRefused(f"The statement has more than {MAX_ROWS:,} rows. Split it by quarter or by deductor.",
                               code="TRINETRA_TOO_MANY_ROWS")
