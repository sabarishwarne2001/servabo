"""Writing many rows at once: one `COPY` instead of thousands of parameters.

GST Credit stores 10,000 records on an import and 10,000+ matches on every recompute. Through SQLAlchemy's
multi-row `INSERT` that was the largest single cost of a recompute on a busy CI machine (every value is adapted
one at a time in Python); a `COPY` of the same rows takes a sixth of the time and writes identical data.

The rows are plain dicts, exactly as they were given to `insert(Model)`. Every row must carry the same keys.
Columns that are left out take their database default (every table written here has a server default for the
columns the callers omit, such as `created_at`)."""

from __future__ import annotations

import io
import json
from typing import Any, Callable, Mapping, Sequence, Type

from sqlalchemy import JSON
from sqlalchemy.orm import Session

#: rows written per `COPY`: keeps the in-memory text small on a very large return
CHUNK = 5000
NULL = "\\N"


def insert_rows(db: Session, model: Type[Any], rows: Sequence[Mapping[str, Any]]) -> None:
    """Insert `rows` into the table of `model`, inside the session's current transaction."""
    if not rows:
        return
    table = model.__table__
    names = list(rows[0].keys())
    is_json = [isinstance(table.c[name].type, JSON) for name in names]
    statement = "COPY {} ({}) FROM STDIN WITH (FORMAT csv, NULL '\\N')".format(
        table.name, ", ".join(f'"{name}"' for name in names))
    cursor = db.connection().connection.cursor()
    try:
        for start in range(0, len(rows), CHUNK):
            lines = [",".join([_cell(row[name], as_json) for name, as_json in zip(names, is_json)])
                     for row in rows[start:start + CHUNK]]
            lines.append("")
            cursor.copy_expert(statement, io.StringIO("\n".join(lines)))
    finally:
        cursor.close()


def _quoted(text: str) -> str:
    return '"' + text.replace('"', '""') + '"'


#: how each plain Python type is written; text is always quoted, so only a missing value is the bare `\N` that COPY
#: reads as NULL (a name that is literally backslash-N stays text)
_WRITERS: dict[type, Callable[[Any], str]] = {
    str: _quoted, int: str, bool: lambda value: "t" if value else "f", float: repr,
}


def _cell(value: Any, as_json: bool) -> str:
    """One value as a CSV field."""
    if value is None:
        return NULL
    if as_json:
        return _quoted(json.dumps(value, default=str))
    writer = _WRITERS.get(type(value))
    return writer(value) if writer is not None else _quoted(str(value))


__all__ = ["insert_rows"]
