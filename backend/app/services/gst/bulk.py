"""Writing many rows at once: one `COPY` instead of thousands of parameters.

GST Credit stores 10,000 records on an import and 10,000+ matches on every recompute. Through SQLAlchemy's
multi-row `INSERT` that was the largest single cost of a recompute on a busy CI machine (every value is adapted
one at a time in Python); a `COPY` of the same rows takes a sixth of the time and writes identical data.

The rows are plain dicts, exactly as they were given to `insert(Model)`. Every row must carry the same keys.
Columns that are left out take their database default (every table written here has a server default for the
columns the callers omit, such as `created_at`)."""

from __future__ import annotations

import csv
import io
import json
from typing import Any, Iterator, Mapping, Sequence, Type

from sqlalchemy import JSON
from sqlalchemy.orm import Session

#: rows written per `COPY`: keeps the in-memory text small on a very large return
CHUNK = 5000


def insert_rows(db: Session, model: Type[Any], rows: Sequence[Mapping[str, Any]]) -> None:
    """Insert `rows` into the table of `model`, inside the session's current transaction."""
    if not rows:
        return
    table = model.__table__
    names = list(rows[0].keys())
    json_at = [i for i, name in enumerate(names) if isinstance(table.c[name].type, JSON)]
    statement = "COPY {} ({}) FROM STDIN WITH (FORMAT csv)".format(
        table.name, ", ".join(f'"{name}"' for name in names))
    cursor = db.connection().connection.cursor()
    try:
        for start in range(0, len(rows), CHUNK):
            buffer = io.StringIO()
            # QUOTE_STRINGS (Python 3.12): every text value is quoted, so an empty string and the two characters
            # backslash-N stay text; a missing value is written bare, which COPY reads as NULL. The csv module does
            # the quoting in C; everything that is not text (numbers, dates, UUIDs, booleans) is written by `str`.
            csv.writer(buffer, quoting=csv.QUOTE_STRINGS, lineterminator="\n").writerows(
                _cells(rows[start:start + CHUNK], names, json_at))
            buffer.seek(0)
            cursor.copy_expert(statement, buffer)
    finally:
        cursor.close()


def _cells(rows: Sequence[Mapping[str, Any]], names: list[str], json_at: list[int]) -> Iterator[list[Any]]:
    for row in rows:
        values = [row[name] for name in names]
        for i in json_at:  # JSON columns go in as their text; None stays NULL
            if values[i] is not None:
                values[i] = json.dumps(values[i], default=str)
        yield values


__all__ = ["insert_rows"]
