"""Document-number keys for GST matching: `normalize.document_number`, also ignoring the financial-year
token many Indian suppliers print inside a number ("INV/25-26/0045" and "INV-0045" are one invoice)."""

from __future__ import annotations

import re
from datetime import date
from typing import Optional

from app.core import normalize as nz

#: A financial-year token between separators or at an end: "2025-2026", "2025-26", "25-26" (the second year
#: follows the first). Longest form first, so "45/2025-2026" loses "2025-2026" and not "45/20".
_FY_PATTERNS = (
    (re.compile(r"(?<![0-9])(20\d{2})\s*[-/]\s*(20\d{2})(?![0-9])"), 4),
    (re.compile(r"(?<![0-9])(20\d{2})\s*[-/]\s*(\d{2})(?![0-9])"), 2),
    (re.compile(r"(?<![0-9])(\d{2})\s*[-/]\s*(\d{2})(?![0-9])"), 0),
)


def _strip_fy(raw: str) -> str:
    for pattern, width in _FY_PATTERNS:
        position = 0
        while True:
            match = pattern.search(raw, position)
            if match is None:
                break
            first, second = int(match.group(1)), int(match.group(2))
            follows = second == first + 1 if width == 4 else second == (first + 1) % 100
            if follows:
                raw = raw[:match.start()] + raw[match.end():]
                position = match.start()
            else:
                position = match.start() + 1  # "12/24-25": the token may start inside this match
    return raw


def number_key(raw: Optional[str]) -> Optional[str]:
    """The comparison key of an invoice/note number, or None when there is nothing to compare."""
    if not raw or not str(raw).strip():
        return None
    text = _strip_fy(str(raw))
    text = re.sub(r"[-/\s]{2,}", "-", text).strip("-/ ")
    try:
        return nz.document_number(text or str(raw))[:64]
    except nz.NormalizationError:
        return None


def financial_year(day: date) -> int:
    """The year a financial year starts in (April to March): 2026-02-10 is FY 2025, 2026-04-01 is FY 2026."""
    return day.year if day.month >= 4 else day.year - 1


def period_of(day: date) -> str:
    return f"{day.year:04d}-{day.month:02d}"


__all__ = ["financial_year", "number_key", "period_of"]
