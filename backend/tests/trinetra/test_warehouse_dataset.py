"""The Enterprise warehouse dataset TRINETRA_CASES (Final 2T, Phase 7.8): the dataset contract (a versioned spec, no forbidden column,
rows whose keys are exactly the spec's columns, a Parquet file that reads back, the organization's own rows only, the sample
company left out) plus masked identifiers: no PAN, no TAN, no deductor key, no customer or invoice name, no document text."""

import io
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.models.workspace import Workspace, WorkspaceStatus
from app.services.analytics import export_engine
from tests.security.plans import put_on_plan
from tests.trinetra.test_api import world  # noqa: F401
from tests.trinetra.test_money_model import statement
from tests.trinetra.test_workflows import setup_case

WINDOW_START = datetime(2000, 1, 1, tzinfo=timezone.utc)
WINDOW_END = datetime.now(timezone.utc) + timedelta(days=1)
NAMES_AND_TEXT = {"counterparty", "customer", "customer_name", "reference", "invoice_number", "review", "original_filename", "pan", "tan",
                  "deductor_key", "note", "reason"}


def _extract(db, organization_id):
    return export_engine.extract_dataset(db, "TRINETRA_CASES", organization_id=organization_id, window_start=WINDOW_START,
                                         window_end=WINDOW_END)


def test_the_dataset_has_a_versioned_spec_no_forbidden_column_and_no_names_or_identifiers():
    spec = export_engine.DATASET_SPECS["TRINETRA_CASES"]
    assert spec.version == export_engine.DATASET_SCHEMA_VERSIONS["TRINETRA_CASES"] == 1
    assert "TRINETRA_CASES" in export_engine.EXTRACTORS
    assert not set(spec.column_names) & export_engine.FORBIDDEN_COLUMN_NAMES
    assert not set(spec.column_names) & NAMES_AND_TEXT
    assert export_engine.DATASET_CAPABILITY["TRINETRA_CASES"] == "capability.trinetra_all_workspaces"
    from app.models.warehouse_sync import EXPORT_DATASET_VALUES

    assert "TRINETRA_CASES" in EXPORT_DATASET_VALUES


def test_rows_have_exactly_the_specs_columns_ids_states_and_figures_and_no_name_or_tax_identifier(client, tenant, world, db_session):
    url, body, case = setup_case(client, tenant, world, reference="TR-WH-1")
    statement(client, tenant, url, body, ["MUMB54321K,10.00,x0,194C,15-Jun-2025,F,FY 2025-26 / AY 2026-27"])
    put_on_plan(db_session, tenant.organization, "enterprise")
    db_session.commit()
    [row] = _extract(db_session, tenant.organization.id)
    assert tuple(row) == export_engine.DATASET_SPECS["TRINETRA_CASES"].column_names
    assert row["case_id"] == case["id"] and row["workspace_id"] == str(tenant.workspace.id) and row["organization_id"] == str(tenant.organization.id)
    assert row["status"] == "POSSIBLE_MISSING_POSTING" and row["review_state"] == "OPEN" and row["year"] == 2025
    assert row["expected_micros"] == 2_000_000_000 and row["posted_micros"] == 0 and row["gap_micros"] == 2_000_000_000
    assert row["currency"] == "INR" and row["source_current"] is True and row["customer_key"]
    text = repr(row)
    for secret in ("ABCDE1234F", "ABCD12345E", "TR-WH-1", "Synthetic"):
        assert secret not in text, secret


def test_another_organization_and_the_sample_company_never_leave_and_the_window_is_honoured(client, tenant, world, db_session):
    setup_case(client, tenant, world)
    put_on_plan(db_session, tenant.organization, "enterprise")
    sample = Workspace(organization_id=tenant.organization.id, slug="sample", workspace_name="Sample", status=WorkspaceStatus.ACTIVE,
                       is_sample=True)
    db_session.add(sample)
    db_session.commit()
    mine = _extract(db_session, tenant.organization.id)
    assert {r["workspace_id"] for r in mine} == {str(tenant.workspace.id)}
    assert _extract(db_session, tenant.foreign_workspace.organization_id) == []
    assert export_engine.extract_dataset(db_session, "TRINETRA_CASES", organization_id=tenant.organization.id, window_start=WINDOW_START,
                                         window_end=datetime(2001, 1, 1, tzinfo=timezone.utc)) == []


def test_a_decision_brings_the_case_back_into_a_later_window_and_closed_history_stays(client, tenant, world, db_session):
    from tests.trinetra.test_money_model import decide

    url, body, case = setup_case(client, tenant, world)
    put_on_plan(db_session, tenant.organization, "enterprise")
    db_session.commit()
    assert decide(client, tenant, url, case, "WITHDRAWN", reason="This invoice was cancelled by the customer.").status_code == 200
    [row] = _extract(db_session, tenant.organization.id)
    assert row["review_state"] == "WITHDRAWN" and row["revision"] == case["revision"] + 1
    assert row["updated_at"] >= row["created_at"]


def test_the_dataset_is_empty_when_trinetra_is_not_live_and_round_trips_through_parquet(client, tenant, world, db_session, monkeypatch):
    from app.core.config import settings

    pq = pytest.importorskip("pyarrow.parquet")
    setup_case(client, tenant, world)
    put_on_plan(db_session, tenant.organization, "enterprise")
    db_session.commit()
    rows = _extract(db_session, tenant.organization.id)
    spec = export_engine.DATASET_SPECS["TRINETRA_CASES"]
    table = pq.read_table(io.BytesIO(export_engine.write_parquet(rows, spec)))
    assert table.column_names == list(spec.column_names) and table.num_rows == len(rows) == 1
    monkeypatch.setattr(settings, "TRINETRA_LIVE_ENABLED", None)
    monkeypatch.setattr(settings, "TRINETRA_MODE", "off")
    assert _extract(db_session, tenant.organization.id) == []


def test_business_is_refused_the_dataset_in_words(client, tenant, db_session):
    from tests.api.test_arch26_endpoints import base  # noqa: F401

    from app.services.analytics import sync_service

    put_on_plan(db_session, tenant.organization, "business")
    db_session.commit()
    assert sync_service.datasets_not_held(db_session, organization_id=tenant.organization.id, datasets=["TRINETRA_CASES", "USAGE_ROLLUPS"]) == [
        "TRINETRA_CASES"]
