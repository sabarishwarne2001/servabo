"""GST Credit re-reconciles when documents change: a debounced `gst.recompute` job, and the nightly sweep (real Postgres,
the real job runner). A recompute is idempotent."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import select

from app.models.gst import GstMatch
from app.services.gst import engine, hooks
from app.services.gst import vocabulary as v
from tests.engines.conftest import drain
from tests.security.plans import put_on_plan
from tests.services.gst.helpers import RECIPIENT, SUPPLIER_A, SUPPLIER_B, book_invoice, statement

API = "/api/v1"

#: Workspace isolation of the GST Credit routes is proved below (and through the role matrix in tests/api/test_gst_api.py).
ISOLATION_PROVEN_HERE = ("gst",)


@pytest.fixture()
def imported(client, db_session, tenant, test_sessions):
    put_on_plan(db_session, tenant.organization, "business")
    book_invoice(db_session, tenant, number="INV-1001", supplier="a", gstin=SUPPLIER_A, on=date(2026, 9, 5), taxable=1000)
    db_session.commit()
    response = client.post(f"{API}/workspaces/{tenant.workspace.id}/gst/returns", headers=tenant.contributor.headers,
                           files={"file": ("gstr2b.json", statement())})
    assert response.status_code == 200, response.text
    return tenant


def shape(db, workspace_id):
    rows = db.execute(select(GstMatch).where(GstMatch.workspace_id == workspace_id)).scalars().all()
    return sorted((m.doc_number or "", m.status, m.method or "", m.itc_micros or 0, m.ims_action or "") for m in rows)


def test_a_document_that_arrives_later_settles_the_line_through_the_worker(db_session, imported):
    tenant = imported
    x7 = next(m for m in db_session.execute(select(GstMatch).where(GstMatch.workspace_id == tenant.workspace.id)).scalars()
              if m.doc_number == "X-7")
    assert x7.status == v.NOT_IN_BOOKS
    book_invoice(db_session, tenant, number="X-7", supplier="b", gstin=SUPPLIER_B, on=date(2026, 9, 16), taxable=700,
                 name="Deccan Plastics")
    assert hooks.document_changed(db_session, workspace_id=tenant.workspace.id, reason="test") is True
    db_session.commit()
    drain(only=[hooks.JOB_RECOMPUTE])
    db_session.expire_all()
    after = next(m for m in db_session.execute(select(GstMatch).where(GstMatch.workspace_id == tenant.workspace.id)).scalars()
                 if m.doc_number == "X-7")
    assert after.status == v.MATCHED and after.work_item_id is not None


def test_changes_in_one_burst_ask_for_one_job(db_session, imported):
    from app.models.job import Job

    for _ in range(5):
        hooks.document_changed(db_session, workspace_id=imported.workspace.id, reason="burst")
    db_session.commit()
    jobs = db_session.execute(select(Job).where(Job.job_type == hooks.JOB_RECOMPUTE)).scalars().all()
    assert len(jobs) == 1


def test_a_workspace_with_no_return_asks_for_nothing(db_session, tenant, test_sessions):
    assert hooks.document_changed(db_session, workspace_id=tenant.workspace.id, reason="none") is False


def test_a_recompute_is_idempotent(db_session, imported):
    workspace = imported.workspace
    before = shape(db_session, workspace.id)
    engine.recompute(db_session, workspace)
    engine.recompute(db_session, workspace)
    db_session.commit()
    assert shape(db_session, workspace.id) == before and len(before) == 6


def test_the_nightly_sweep_reconciles_every_workspace_with_a_return(db_session, imported):
    from app.workers.handlers import gst as handler

    db_session.execute(GstMatch.__table__.delete().where(GstMatch.workspace_id == imported.workspace.id))
    db_session.commit()
    result = handler.handle_recompute({})
    assert result["reconciled"] >= 1 and result["failed"] == 0
    db_session.expire_all()
    assert len(shape(db_session, imported.workspace.id)) == 6


def test_a_second_workspace_sees_nothing_of_the_first(client, db_session, imported):
    """Every list route of another organization's workspace is empty, and ours answers 404/403 to its people."""
    tenant = imported
    mine = client.get(f"{API}/workspaces/{tenant.workspace.id}/gst/records", headers=tenant.viewer.headers).json()
    assert mine["total"] == 6
    foreign = tenant.foreign_workspace
    for tail in ("/records", "/suppliers"):
        response = client.get(f"{API}/workspaces/{foreign.id}/gst{tail}", headers=tenant.other_org_member.headers)
        assert response.status_code in (200, 402), response.text
        if response.status_code == 200:
            assert response.json()["total"] == 0
    summary = client.get(f"{API}/workspaces/{foreign.id}/gst/summary", headers=tenant.other_org_member.headers).json()
    assert summary["gstins"] == [] and summary["lines"] == 0
    for item in mine["items"]:
        assert client.get(f"{API}/workspaces/{foreign.id}/gst/records/{item['id']}",
                          headers=tenant.other_org_member.headers).status_code in (402, 404)
        assert client.get(f"{API}/workspaces/{tenant.workspace.id}/gst/records/{item['id']}",
                          headers=tenant.other_org_member.headers).status_code in (403, 404)
