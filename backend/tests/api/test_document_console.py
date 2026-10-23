"""Document console filters/counts share the authenticated workspace boundary."""
from datetime import datetime, timezone

import pytest


def test_counts_are_workspace_scoped_and_independent_of_filters(client, tenant, db_session, work_item_factory):
    for state in ("QUEUED", "PROCESSING", "COMPLETED", "FAILED"):
        item = work_item_factory(original_filename=f"{state}.pdf")
        item.status = state
    other = work_item_factory(workspace_id=tenant.foreign_workspace.id)
    other.status = "FAILED"
    db_session.commit()
    url = f"/api/v1/workspaces/{tenant.workspace.id}/work-items/counts"
    response = client.get(url, headers=tenant.owner.headers)
    assert response.status_code == 200, response.text
    assert response.json() == dict(total=4, queued=1, processing=1, completed=1, failed=1)
    assert client.get(url, headers=tenant.viewer.headers).json() == response.json()
    assert client.get(url).status_code == 401
    assert client.get(url, headers=tenant.other_org_member.headers).status_code == 404


def test_format_and_inclusive_upload_dates_apply_to_rows_and_total(client, tenant, db_session, work_item_factory):
    for name, mime, instant in (
        ("a.pdf", "application/pdf", "2026-10-01T00:00:00+00:00"),
        ("b.pdf", "application/pdf", "2026-10-01T23:59:59+00:00"),
        ("c.pdf", "application/pdf", "2026-10-02T00:00:00+00:00"),
        ("d.csv", "text/csv", "2026-10-01T12:00:00+00:00"),
    ):
        item = work_item_factory(original_filename=name, file_type=mime)
        item.status = "COMPLETED"
        item.created_at = datetime.fromisoformat(instant)
    other = work_item_factory(workspace_id=tenant.foreign_workspace.id)
    other.status = "COMPLETED"
    other.created_at = datetime(2026, 10, 1, tzinfo=timezone.utc)
    db_session.commit()
    url = f"/api/v1/workspaces/{tenant.workspace.id}/work-items"
    params = dict(file_format="pdf", uploaded_from="2026-10-01", uploaded_to="2026-10-01", limit=1, sort_by="original_filename", sort_order="asc")
    first = client.get(url, params=params, headers=tenant.owner.headers).json()
    second = client.get(url, params={**params, "skip": 1}, headers=tenant.owner.headers).json()
    assert first["totalItems"] == second["totalItems"] == 2
    assert first["totalPages"] == 2
    assert first["items"][0]["original_filename"] == "a.pdf"
    assert second["items"][0]["original_filename"] == "b.pdf"


@pytest.mark.parametrize("params", [
    {"file_format": "exe"}, {"uploaded_from": "invalid"},
    {"uploaded_from": "2026-10-02", "uploaded_to": "2026-10-01"},
    {"uploaded_to": "9999-12-31"}, {"search": "x" * 101},
])
def test_invalid_console_filters_are_rejected(client, tenant, params):
    response = client.get(f"/api/v1/workspaces/{tenant.workspace.id}/work-items", params=params, headers=tenant.owner.headers)
    assert response.status_code == 422
