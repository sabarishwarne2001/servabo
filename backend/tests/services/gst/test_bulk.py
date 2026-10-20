"""`bulk.insert_rows` writes exactly what `insert(Model)` writes (Session H: the speed fix must not change a value).

The rows carry the awkward text a supplier name or a note can hold: quotes, commas, new lines, a backslash, the
two characters `\\N`, an empty string, non-ASCII letters, nested JSON, `None` in a nullable column."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import insert, select

from app.models.gst import GstMatch
from app.models.work_item import WorkItem
from app.services.gst import bulk

NOW = datetime(2026, 10, 19, 9, 30, 15, 123456, tzinfo=timezone.utc)
NAMES = ['Sharma "Best" Traders, Pune', "Line one\nLine two", "back\\slash", "\\N", "", None, "Müller & Söhne – GmbH ₹",
         "tab\there", "'single' quotes"]


def _work_items(db, workspace, count):
    ids = [uuid.uuid4() for _ in range(count)]
    db.execute(insert(WorkItem), [{"id": i, "workspace_id": workspace.id, "original_filename": f"bulk-{n}.pdf",
                                   "stored_filename": f"bulk-{i.hex}.pdf", "file_type": "application/pdf",
                                   "file_size": 1, "status": "COMPLETED", "pipeline_stage": "COMPLETED",
                                   "extracted_entities": {}, "extracted_text": "", "extraction_metadata": {}}
                                  for n, i in enumerate(ids)])
    return ids


def _rows(tenant, work_item_ids):
    return [{
        "id": uuid.uuid4(), "organization_id": tenant.organization.id, "workspace_id": tenant.workspace.id,
        "gstin": "27AAACM1234F1Z5", "record_id": None, "work_item_id": wid, "status": "WAITING_FOR_SUPPLIER",
        "method": None if n % 2 else "NUMBER", "supplier_gstin": "29AABCS1000K1Z5", "supplier_name": name,
        "doc_number": name[:20] if name else None, "doc_date": date(2026, 9, 1 + n) if n % 3 else None,
        "value_micros": 10_000_000 * n, "tax_micros": -5 * n, "itc_micros": None,
        "differences": [{"field": "taxable", "label": 'Taxable "value"', "delta_micros": -500_000}] if n % 2 else [],
        "notes": [{"code": "NUMBER_FORMAT", "label": name or "", "books": "S01/25-26/1", "gstr2b": "S01-1"}],
        "ims_action": "PENDING" if n % 2 else None, "ims_reason": "Two lines\nof reason, with a comma" if n % 2 else None,
        "period_first_seen": "2026-09", "reported_late": bool(n % 2), "risk": {"days": n, "nested": {"a": [1, 2]}} if n % 2 else None,
        "decision": None, "computed_at": NOW,
    } for n, wid in zip(range(len(NAMES)), work_item_ids) for name in [NAMES[n]]]


def _stored(db, ids):
    rows = db.execute(select(GstMatch).where(GstMatch.work_item_id.in_(ids))).scalars().all()
    return [{c.name: getattr(r, c.name) for c in GstMatch.__table__.columns if c.name not in ("id", "work_item_id")}
            for r in sorted(rows, key=lambda r: r.value_micros)]


def test_a_copy_stores_the_same_values_as_an_insert(db_session, tenant):
    ids = _work_items(db_session, tenant.workspace, len(NAMES) * 2)
    by_insert, by_copy = ids[:len(NAMES)], ids[len(NAMES):]
    db_session.execute(insert(GstMatch), _rows(tenant, by_insert))
    bulk.insert_rows(db_session, GstMatch, _rows(tenant, by_copy))
    db_session.flush()
    assert _stored(db_session, by_copy) == _stored(db_session, by_insert)
    assert len(_stored(db_session, by_copy)) == len(NAMES)


def test_nothing_to_write_is_a_no_op(db_session):
    bulk.insert_rows(db_session, GstMatch, [])
