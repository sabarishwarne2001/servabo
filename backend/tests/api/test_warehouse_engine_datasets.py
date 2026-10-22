"""The Enterprise warehouse datasets: GST_MATCHES and HELM_LEDGER (Final session 1, Phase 6).

Each follows the dataset contract the others do: a versioned spec, no forbidden column, rows whose keys are exactly the
spec's columns, a Parquet file that reads back, the organization's own rows only. Beyond it: identifiers and figures only
(no supplier or counterparty names, no document text), the invented sample company left out, and a plan that does not
include the across-every-workspace capabilities refused in words with a 402.
"""

from __future__ import annotations

import io
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

import pytest

from app.models.helm import HelmPromise
from app.models.workspace import Workspace, WorkspaceStatus
from app.services.analytics import export_engine, sync_service
from app.services.gst import builder as b
from app.services.gst import store
from app.services.helm import vocabulary as hv
from tests.api.test_arch26_endpoints import (  # noqa: F401  (fixtures and helpers)
    _warehouse_sync_plan, base, destination, s3_payload, stub_s3_connector,
)
from tests.security.plans import put_on_plan
from tests.services.gst.helpers import RECIPIENT, SUPPLIER_A, statement, supplier_invoices

WINDOW_START = datetime(2000, 1, 1, tzinfo=timezone.utc)
WINDOW_END = datetime.now(timezone.utc) + timedelta(days=1)
NAMES_AND_TEXT = {"supplier_name", "counterparty_name", "title", "terms", "evidence", "details", "notes", "ims_reason",
                  "differences", "original_filename"}


def _extract(db, dataset: str, organization_id: uuid.UUID) -> list[dict[str, Any]]:
    return export_engine.extract_dataset(db, dataset, organization_id=organization_id, window_start=WINDOW_START,
                                         window_end=WINDOW_END)


@pytest.fixture()
def gst_books(db_session, tenant):
    put_on_plan(db_session, tenant.organization, "enterprise")
    tenant.workspace.timezone = "UTC"
    store.import_file(db_session, workspace=tenant.workspace, user_id=tenant.owner.user.id, file_name="gstr2b.json",
                      data=statement())
    db_session.commit()
    return tenant


def _own_statement(number: str, taxable: int) -> bytes:
    """A GSTR-2B with a single supplier invoice."""
    return b.to_bytes(b.gstr2b(RECIPIENT, "2026-09", {"b2b": [supplier_invoices([b.document(number, date(2026, 9, 5), taxable)])]}))


def _promise(organization_id: uuid.UUID, workspace_id: uuid.UUID, key: str, **extra: Any) -> HelmPromise:
    fields: dict[str, Any] = dict(
        organization_id=organization_id, workspace_id=workspace_id, source_key=key, kind=hv.PROMISE_KINDS[0],
        direction=hv.DIRECTIONS[0], counterparty_key="sahyadri-packaging", counterparty_name="Sahyadri Packaging Pvt Ltd",
        currency="INR", amount_micros=125_000_000, due_date=date(2026, 11, 5), status=hv.STATUS_OPEN,
        confidence=hv.CONFIDENCES[0], title="Pay Sahyadri 1.25 lakh by 5 Nov", engine_version="1",
        content_hash="0" * 64, evidence=[{"quote": "payable within 30 days"}], fulfilments=[])
    fields.update(extra)
    return HelmPromise(**fields)


# ------------------------------------------------------------------------------------------------- the contract


@pytest.mark.parametrize("dataset", ["GST_MATCHES", "HELM_LEDGER"])
def test_each_dataset_has_a_versioned_spec_no_forbidden_column_and_no_names_or_text(dataset: str) -> None:
    spec = export_engine.DATASET_SPECS[dataset]
    assert spec.version == export_engine.DATASET_SCHEMA_VERSIONS[dataset] == 1
    assert dataset in export_engine.EXTRACTORS
    assert not set(spec.column_names) & export_engine.FORBIDDEN_COLUMN_NAMES
    assert not set(spec.column_names) & NAMES_AND_TEXT
    assert dataset in export_engine.DATASET_CAPABILITY


# ------------------------------------------------------------------------------------------------ GST matches


def test_gst_matches_carry_figures_and_ids_in_exactly_the_specs_columns(db_session, gst_books) -> None:
    rows = _extract(db_session, "GST_MATCHES", gst_books.organization.id)
    assert rows, "the imported statement produced matches"
    spec = export_engine.GST_MATCHES_SPEC
    for row in rows:
        assert tuple(row) == spec.column_names
        assert row["organization_id"] == str(gst_books.organization.id)
        assert row["workspace_id"] == str(gst_books.workspace.id)
    assert SUPPLIER_A in {row["supplier_gstin"] for row in rows}
    assert any(row["value_micros"] for row in rows)
    assert "Sahyadri" not in repr(rows), "no supplier name leaves"


def test_gst_matches_leave_out_another_organization_and_the_sample_company(db_session, gst_books) -> None:
    sample = Workspace(organization_id=gst_books.organization.id, slug="sample", workspace_name="Sample company",
                       status=WorkspaceStatus.ACTIVE, is_sample=True)
    db_session.add(sample)
    db_session.flush()
    store.import_file(db_session, workspace=sample, user_id=gst_books.owner.user.id, file_name="s.json",
                      data=_own_statement("S-1", 9999))
    store.import_file(db_session, workspace=gst_books.foreign_workspace, user_id=None, file_name="f.json",
                      data=_own_statement("F-1", 7777))
    db_session.commit()

    mine = _extract(db_session, "GST_MATCHES", gst_books.organization.id)
    assert {row["workspace_id"] for row in mine} == {str(gst_books.workspace.id)}
    assert "S-1" not in {row["document_number"] for row in mine}
    theirs = _extract(db_session, "GST_MATCHES", gst_books.foreign_workspace.organization_id)
    assert theirs and {row["workspace_id"] for row in theirs} == {str(gst_books.foreign_workspace.id)}


def test_gst_matches_follow_the_window(db_session, gst_books) -> None:
    long_ago = export_engine.extract_dataset(
        db_session, "GST_MATCHES", organization_id=gst_books.organization.id,
        window_start=WINDOW_START, window_end=datetime(2001, 1, 1, tzinfo=timezone.utc))
    assert long_ago == []


# ----------------------------------------------------------------------------------------------- Helm ledger


def test_helm_ledger_rows_have_ids_states_and_figures_and_never_names_or_evidence(db_session, tenant) -> None:
    put_on_plan(db_session, tenant.organization, "enterprise")
    db_session.add(_promise(tenant.organization.id, tenant.workspace.id, "k-1"))
    db_session.commit()

    rows = _extract(db_session, "HELM_LEDGER", tenant.organization.id)
    assert len(rows) == 1
    row = rows[0]
    assert tuple(row) == export_engine.HELM_LEDGER_SPEC.column_names
    assert row["amount_micros"] == 125_000_000 and row["currency"] == "INR" and row["status"] == hv.STATUS_OPEN
    assert row["due_date"] == datetime(2026, 11, 5, tzinfo=timezone.utc)
    assert row["fulfilment_count"] == 0 and row["counterparty_key"] == "sahyadri-packaging"
    text = repr(row)
    assert "Sahyadri Packaging" not in text and "payable within 30 days" not in text and "Pay Sahyadri" not in text


def test_helm_ledger_leaves_out_another_organization_and_the_sample_company(db_session, tenant) -> None:
    put_on_plan(db_session, tenant.organization, "enterprise")
    sample = Workspace(organization_id=tenant.organization.id, slug="sample", workspace_name="Sample company",
                       status=WorkspaceStatus.ACTIVE, is_sample=True)
    db_session.add(sample)
    db_session.flush()
    foreign = tenant.foreign_workspace
    db_session.add_all([
        _promise(tenant.organization.id, tenant.workspace.id, "mine"),
        _promise(tenant.organization.id, sample.id, "sample"),
        _promise(foreign.organization_id, foreign.id, "theirs"),
    ])
    db_session.commit()

    mine = _extract(db_session, "HELM_LEDGER", tenant.organization.id)
    assert [row["workspace_id"] for row in mine] == [str(tenant.workspace.id)]
    theirs = _extract(db_session, "HELM_LEDGER", foreign.organization_id)
    assert [row["workspace_id"] for row in theirs] == [str(foreign.id)]


# ------------------------------------------------------------------------------------------------ Parquet


def test_both_datasets_round_trip_through_parquet(db_session, gst_books) -> None:
    pq = pytest.importorskip("pyarrow.parquet")
    db_session.add(_promise(gst_books.organization.id, gst_books.workspace.id, "rt"))
    db_session.commit()
    for dataset in ("GST_MATCHES", "HELM_LEDGER"):
        rows = _extract(db_session, dataset, gst_books.organization.id)
        spec = export_engine.DATASET_SPECS[dataset]
        table = pq.read_table(io.BytesIO(export_engine.write_parquet(rows, spec)))
        assert table.column_names == list(spec.column_names)
        assert table.num_rows == len(rows) > 0


# ------------------------------------------------------------------------------------------------ the plan


def test_the_datasets_endpoint_lists_both(client, tenant) -> None:
    response = client.get(base(tenant.organization.id) + "/datasets", headers=tenant.org_admin.headers)
    assert response.status_code == 200
    listed = {item["dataset"] for item in response.json()}
    assert {"GST_MATCHES", "HELM_LEDGER"} <= listed


@pytest.mark.parametrize("dataset", ["GST_MATCHES", "HELM_LEDGER"])
def test_business_is_refused_an_enterprise_dataset_in_words(client, db_session, tenant, destination, dataset) -> None:
    schedule = {"destination_id": destination["id"], "datasets": ["USAGE_ROLLUPS", dataset], "cadence": "DAILY",
                "hour_utc": 2, "lookback_days": 1}
    refused = client.post(base(tenant.organization.id) + "/schedules", json=schedule, headers=tenant.owner.headers)
    assert refused.status_code == 402, refused.text
    body = refused.json()
    assert body["code"] == "CAPABILITY_REQUIRED" and "across every workspace" in body["message"]
    assert "capability." not in body["message"], "a plan name, never a key"

    manual = client.post(base(tenant.organization.id) + "/sync", headers=tenant.owner.headers,
                         json={"destination_id": destination["id"], "datasets": [dataset], "lookback_days": 1})
    assert manual.status_code == 402, manual.text
    # nothing else about the request changed: the usage dataset alone is still accepted
    ok = client.post(base(tenant.organization.id) + "/schedules", headers=tenant.owner.headers,
                     json={**schedule, "datasets": ["USAGE_ROLLUPS"]})
    assert ok.status_code == 201, ok.text


def test_enterprise_may_schedule_and_trigger_both(client, db_session, tenant, destination) -> None:
    put_on_plan(db_session, tenant.organization, "enterprise")
    db_session.commit()
    created = client.post(base(tenant.organization.id) + "/schedules", headers=tenant.owner.headers,
                          json={"destination_id": destination["id"], "datasets": ["GST_MATCHES", "HELM_LEDGER"],
                                "cadence": "DAILY", "hour_utc": 2, "lookback_days": 1})
    assert created.status_code == 201, created.text
    assert created.json()["datasets"] == ["GST_MATCHES", "HELM_LEDGER"]
    manual = client.post(base(tenant.organization.id) + "/sync", headers=tenant.owner.headers,
                         json={"destination_id": destination["id"], "datasets": ["GST_MATCHES"], "lookback_days": 1})
    assert manual.status_code == 202, manual.text


def test_a_downgraded_plan_leaves_the_engine_datasets_out_of_a_scheduled_run_and_says_so(
        db_session, tenant, destination) -> None:
    put_on_plan(db_session, tenant.organization, "business")
    db_session.commit()
    assert sync_service.datasets_not_held(
        db_session, organization_id=tenant.organization.id,
        datasets=["USAGE_ROLLUPS", "GST_MATCHES", "HELM_LEDGER"]) == ["GST_MATCHES", "HELM_LEDGER"]
    with pytest.raises(sync_service.SyncServiceError, match="no longer includes GST_MATCHES, HELM_LEDGER"):
        sync_service.execute_sync(
            db_session, organization_id=tenant.organization.id, destination_id=uuid.UUID(destination["id"]),
            datasets=["GST_MATCHES", "HELM_LEDGER"], lookback_days=1, trigger="SCHEDULED")
