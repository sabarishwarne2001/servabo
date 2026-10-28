"""The case list reads its page in batches, not one case at a time (Final 2T, Phase 1.5)."""

import uuid
from datetime import date

from sqlalchemy import event

from app.models.trinetra import TrinetraCredit, TrinetraProfile
from tests.services.gst.helpers import book_invoice
from tests.trinetra.test_api import world, SUPPLIER_A  # noqa: F401
from tests.trinetra.test_workflows import setup_case
from app.services.trinetra import service


def add_cases(db, tenant, profile, n, prefix):
    for i in range(n):
        invoice = book_invoice(db, tenant, number=f"{prefix}-{i}", supplier="a", gstin=SUPPLIER_A, on=date(2026, 3, 1),
                               taxable=100000, extra={"vendor_pan": "ABCDE1234F"})
        db.add(TrinetraCredit(
            organization_id=tenant.organization.id, workspace_id=tenant.workspace.id, profile_id=profile.id,
            work_item_id=invoice.id, year=2025, counterparty="Synthetic", deductor_key="opaque",
            expected_micros=2_000_000_000, reference=f"{prefix}-{i}",
            source_version=service.invoice_version(db, tenant.workspace, invoice.id)))
    db.commit()


def queries_for_list(client, tenant, db, url, limit):
    count = []
    connection = db.connection()
    listener = lambda *a: count.append(1)  # noqa: E731
    event.listen(connection, "before_cursor_execute", listener)
    try:
        r = client.get(url + f"/credits?limit={limit}", headers=tenant.owner.headers)
    finally:
        event.remove(connection, "before_cursor_execute", listener)
    assert r.status_code == 200, r.text
    return len(count), len(r.json()["items"])


def test_the_number_of_queries_does_not_grow_with_the_page(client, tenant, world, db_session):
    url, body, _ = setup_case(client, tenant, world)
    profile = db_session.get(TrinetraProfile, uuid.UUID(body["profile_id"]))
    small, n_small = queries_for_list(client, tenant, db_session, url, 100)
    add_cases(db_session, tenant, profile, 40, "BATCH")
    large, n_large = queries_for_list(client, tenant, db_session, url, 100)
    assert n_small == 1 and n_large == 41
    assert large <= small + 2, f"{small} queries for 1 case, {large} for 41: the list is not batched"
    assert large <= 40, f"{large} queries for 41 cases"
