"""Which reader reads this file. Never a guess: an unrecognised file is refused with the three accepted shapes named."""

from __future__ import annotations

from typing import Optional

from app.services.helm import bank_parse
from app.services.trinetra.statements import ais, form26as, template
from app.services.trinetra.statements.common import MAX_BYTES, Parsed, StatementRefused

ACCEPTED = ("the Servabo template (CSV or Excel)", "the Form 26AS / Form 168 text download (.txt)", "the AIS TDS/TCS CSV")


def read(filename: str, data: bytes, *, reader: Optional[str] = None, mapping: Optional[dict] = None) -> Parsed:
    """Read a statement file with the reader that recognises it (or the one the person named)."""
    if not data:
        raise StatementRefused("The file is empty.", code="TRINETRA_EMPTY_FILE")
    if len(data) > MAX_BYTES:
        raise StatementRefused(f"The file is larger than {MAX_BYTES // (1024 * 1024)} MB.", code="TRINETRA_FILE_TOO_LARGE")
    if data[:4] == b"%PDF":
        raise StatementRefused(
            "This is a PDF. TRACES protects its PDF statements with a password and Servabo does not open them. Use the "
            "text download of Form 26AS / Form 168, or the AIS CSV, instead.", code="TRINETRA_PDF_STATEMENT")
    name = (filename or "").lower()
    if name.endswith(".zip"):
        raise StatementRefused("This is a zip file. Extract the .txt file from it yourself (TRACES' zip needs your date of "
                               "birth as the password, which Servabo never handles) and upload the text file.",
                               code="TRINETRA_ZIP_STATEMENT")
    if reader in (None, form26as.READER) and name.endswith((".txt", ".text")) or (reader == form26as.READER):
        return form26as.read(filename, data)
    if data[:2] == b"PK" or name.endswith((".xlsx",)):
        return template.read(filename, data)
    if form26as.recognizes(data):
        return form26as.read(filename, data)
    try:
        rows = bank_parse._csv_rows(data)  # noqa: SLF001
    except bank_parse.StatementError as exc:
        raise StatementRefused(exc.message, code="TRINETRA_UNREADABLE_FILE") from exc
    if reader == ais.READER or (reader is None and ais.recognizes(rows)):
        return ais.read(filename, data, mapping=mapping)
    if template.recognizes(rows):
        return template.read(filename, data, rows=rows)
    raise StatementRefused("Servabo could not tell what kind of statement this is. It reads " + ", ".join(ACCEPTED[:-1]) +
                           " and " + ACCEPTED[-1] + ". Nothing was read.", code="TRINETRA_UNRECOGNIZED_LAYOUT")
