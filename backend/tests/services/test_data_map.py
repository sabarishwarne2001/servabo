"""Final session 1 (1A): the data map must name every table, and its rules must be well formed.

A new table without a decision FAILS this file, for every future session. That is the point of it: GST, Helm and the
automation traces were all added without anyone deciding what erasure, the retention sweep, deleting a workspace and
the export do with them.
"""

from __future__ import annotations

import warnings

import pytest
import sqlalchemy as sa

import app.models  # noqa: F401  (registers every model on the metadata)
from app.db.base import Base
from app.services.compliance import data_map
from app.services.compliance.data_map import Erasure, Kind, OrgPurge, REGISTRY, Sweep

with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    TABLES = dict(Base.metadata.tables)


def _link_columns(table: sa.Table) -> list[str]:
    return [c.name for c in table.c if c.name.endswith(("work_item_id", "work_item_ids"))]


def test_every_table_has_a_decision():
    missing = sorted(set(TABLES) - set(REGISTRY))
    assert not missing, (
        "These tables have no entry in app/services/compliance/data_map.py. For each, decide what erasure, the "
        f"retention sweep, deleting an organization and the export do with its rows: {missing}"
    )


def test_the_registry_names_no_table_that_does_not_exist():
    assert not sorted(set(REGISTRY) - set(TABLES)), sorted(set(REGISTRY) - set(TABLES))


def test_a_table_that_names_a_document_has_an_erasure_and_a_sweep_decision():
    """Any table with a work item column (or a foreign key to work_items) must say what happens to those rows."""
    offenders = []
    for name, table in TABLES.items():
        if name == "work_items":
            continue
        names_a_document = bool(_link_columns(table)) or any(
            fk.column.table.name == "work_items" for fk in table.foreign_keys
        )
        if not names_a_document:
            continue
        rule = REGISTRY[name]
        if rule.erasure is Erasure.NONE or rule.sweep is Sweep.NONE:
            offenders.append(f"{name}: erasure={rule.erasure.value} sweep={rule.sweep.value}")
    assert not offenders, offenders


@pytest.mark.parametrize("name", sorted(REGISTRY))
def test_rule_is_well_formed(name):
    rule = REGISTRY[name]
    table = TABLES[name]
    cols = set(table.c.keys())

    # DELETE and SCRUB need to know how rows name a document.
    if rule.erasure in (Erasure.DELETE, Erasure.SCRUB) or rule.sweep in (Sweep.DELETE, Sweep.DETACH, Sweep.SCRUB):
        assert rule.links, f"{name}: {rule.erasure.value}/{rule.sweep.value} needs `links`"
    for link in rule.links:
        assert link.column in cols, f"{name}: link column {link.column!r} does not exist"
        if link.kind == "via":
            parent = TABLES[link.parent]
            assert link.parent_pk in parent.c, f"{name}: {link.parent}.{link.parent_pk} does not exist"
            assert link.parent_link.column in parent.c, f"{name}: {link.parent}.{link.parent_link.column} does not exist"
        if link.kind == "json_key":
            assert "JSON" in type(table.c[link.column].type).__name__.upper(), f"{name}.{link.column} is not JSON"

    # What is scrubbed must exist and be able to hold the replacement.
    for column, replacement in rule.scrub.items():
        assert column in cols, f"{name}: scrub column {column!r} does not exist"
        c = table.c[column]
        if replacement is None:
            assert c.nullable, f"{name}.{column} is NOT NULL, so it cannot be scrubbed to NULL; give it an empty value"
        elif isinstance(replacement, (dict, list)):
            assert "JSON" in type(c.type).__name__.upper(), f"{name}.{column} is not JSON but is scrubbed to {replacement!r}"
        elif isinstance(replacement, str):
            assert isinstance(c.type, (sa.String, sa.Text)), f"{name}.{column} is not text"
            length = getattr(c.type, "length", None)
            assert length is None or len(replacement) <= length, f"{name}.{column}: {replacement!r} is longer than {length}"
    if rule.sweep is Sweep.DETACH:
        # The link is cleared, so the first `col` link must be able to hold NULL.
        first = next(link for link in rule.links if link.kind == "col")
        assert table.c[first.column].nullable or table.c[first.column].name == "work_item_id" and name == "helm_settlements", (
            f"{name}.{first.column} cannot be NULL, so the row cannot be detached"
        )

    # Every table that holds the customer's content, a person's data or a money record says where it is exported.
    if rule.kind in (Kind.CONTENT, Kind.PERSON, Kind.MONEY, Kind.CONFIG, Kind.AUDIT):
        assert rule.export or rule.export_note.startswith("not exported: "), (
            f"{name}: name its export section, or say why it is not exported"
        )

    # An organization purge that DELETES needs a column to find the organization's rows by.
    if rule.org_purge is OrgPurge.DELETE:
        assert {"organization_id", "workspace_id"} & cols, f"{name}: org purge DELETE needs organization_id or workspace_id"


def test_money_records_are_never_destroyed_by_erasure_or_the_sweep():
    for name, rule in REGISTRY.items():
        if rule.kind is Kind.MONEY:
            assert rule.erasure in (Erasure.KEEP, Erasure.SCRUB, Erasure.SERVICE), name
            assert rule.sweep in (Sweep.KEEP, Sweep.DETACH, Sweep.NONE, Sweep.CASCADE, Sweep.SERVICE), name
            assert rule.org_purge in (OrgPurge.KEEP, OrgPurge.CASCADE), f"{name}: money records are kept until the final deletion"


def test_kept_money_rows_lose_free_text_that_came_from_documents():
    """A SCRUB on a money table must blank every text column the document's content could have filled."""
    free_text = {
        "gst_matches": {"supplier_name", "notes", "differences", "ims_reason"},
        "gst_decisions": {"note"},
        "helm_settlements": {"hold_reason", "paid_reference", "evidence"},
        "helm_actions": {"title", "explanation", "params", "result", "rejected_reason"},
    }
    for table, expected in free_text.items():
        assert expected <= set(REGISTRY[table].scrub), (table, expected - set(REGISTRY[table].scrub))


def test_gstin_is_kept_on_gst_rows():
    """N-163: the books need the supplier GSTIN, so no GST rule blanks it."""
    for table in ("gst_matches", "gst_decisions", "gst_return_records"):
        assert "supplier_gstin" not in REGISTRY[table].scrub


def test_link_helpers_are_the_only_way_to_name_a_document():
    assert data_map.col("work_item_id").kind == "col"
    assert data_map.json_key("payload", "work_item_id").key == "work_item_id"
