"""Apply the data map's rules to the copies of a document's content (Final session 1, 1A).

Two callers, one engine:

* `mode="erase"` — a person's documents are erased. The document row is KEPT (blanked), so no foreign key acts and
  every copy of the content needs a rule: rows are deleted (`Erasure.DELETE`) or have their free text blanked and
  stay (`Erasure.SCRUB`). Stores that already have a service eraser (`Erasure.SERVICE`) are left to it.
* `mode="purge"` — the retention sweep (or an organization purge) is about to DELETE the document rows. Rows that a
  foreign key will remove (`Sweep.CASCADE`) are left to it. Rows without a foreign key are deleted here
  (`Sweep.DELETE`). Money records are DETACHED: the link to the document is cleared and the free text blanked, so
  the foreign key finds nothing to cascade (`Sweep.DETACH`).

The rules themselves are in `data_map.REGISTRY`; this module reads them and does nothing else. Table and column names
come from the registry and are checked against the models' metadata by `tests/services/test_data_map.py`, never from
user input.
"""

from __future__ import annotations

import uuid
import warnings
from typing import Iterable, Literal, Optional

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

import app.models  # noqa: F401  (registers every model on the metadata)
from app.db.base import Base
from app.services.compliance.data_map import REGISTRY, Erasure, Link, Sweep, TableRule

__all__ = ["destroy_copies"]

Mode = Literal["erase", "purge"]

with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    _TABLES = dict(Base.metadata.tables)


def _clause(table: sa.Table, link: Link, ids: list[uuid.UUID]) -> sa.ColumnElement[bool]:
    column = table.c[link.column]
    if link.kind == "col":
        return column.in_(ids)
    texts = [str(i) for i in ids]
    if link.kind == "json_key":
        return column[link.key].as_string().in_(texts)
    if link.kind == "json_array":
        if isinstance(column.type, postgresql.ARRAY):
            return column.overlap(ids)
        return sa.cast(column, postgresql.JSONB).has_any(sa.cast(texts, postgresql.ARRAY(sa.Text)))
    if link.kind == "via":
        parent = _TABLES[link.parent]
        inner = sa.select(parent.c[link.parent_pk]).where(_clause(parent, link.parent_link, ids))
        return column.in_(inner)
    raise ValueError(f"unknown link kind {link.kind!r}")


def _where(table: sa.Table, rule: TableRule, ids: list[uuid.UUID]) -> sa.ColumnElement[bool]:
    return sa.or_(*[_clause(table, link, ids) for link in rule.links])


def _parents(rule: TableRule) -> set[str]:
    found: set[str] = set()

    def walk(link: Link) -> None:
        if link.kind == "via":
            found.add(link.parent)
            walk(link.parent_link)

    for link in rule.links:
        walk(link)
    return found


def _acts(rule: TableRule, mode: Mode) -> Optional[str]:
    """DELETE, SCRUB or DETACH, or None when this mode leaves the table to someone else."""
    if mode == "erase":
        return {Erasure.DELETE: "DELETE", Erasure.SCRUB: "SCRUB"}.get(rule.erasure)
    return {Sweep.DELETE: "DELETE", Sweep.SCRUB: "SCRUB", Sweep.DETACH: "DETACH"}.get(rule.sweep)


def _order(names: Iterable[str]) -> list[str]:
    """Children before the tables they point through (attempts, deliveries, outbox)."""
    names = list(names)
    rank: dict[str, int] = {}

    def rank_of(name: str, trail: tuple[str, ...] = ()) -> int:
        if name in rank:
            return rank[name]
        parents = [p for p in _parents(REGISTRY[name]) if p in names and p not in trail]
        rank[name] = 0 if not parents else 1 + max(rank_of(p, trail + (name,)) for p in parents)
        return rank[name]

    for name in names:
        rank_of(name)
    return sorted(names, key=lambda n: (-rank[n], n))


def destroy_copies(db: Session, work_item_ids: Iterable[uuid.UUID], *, mode: Mode) -> dict[str, int]:
    """Apply the registry's rules to every store holding a copy of these documents' content.

    Returns the number of rows touched per table (zero counts left out). Does not commit.
    """
    ids = list(dict.fromkeys(work_item_ids))
    if not ids:
        return {}
    actions = {name: act for name, rule in REGISTRY.items() if (act := _acts(rule, mode))}
    counts: dict[str, int] = {}
    for name in _order(actions):
        rule, act, table = REGISTRY[name], actions[name], _TABLES[name]
        where = _where(table, rule, ids)
        if act == "DELETE":
            result = db.execute(sa.delete(table).where(where))
        else:
            values = dict(rule.scrub)
            if act == "DETACH":
                if rule.detach_needs:
                    lost = db.execute(sa.delete(table).where(where, sa.or_(*[table.c[c].is_(None) for c in rule.detach_needs])))
                    if lost.rowcount:
                        counts[name] = int(lost.rowcount)
                for link in rule.links:
                    if link.kind == "col":
                        values[link.column] = None
            if not values:
                continue
            result = db.execute(sa.update(table).where(where).values(**values))
        if result.rowcount:
            counts[name] = counts.get(name, 0) + int(result.rowcount)
    return counts
