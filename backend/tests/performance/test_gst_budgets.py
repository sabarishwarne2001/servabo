"""GST Credit's performance budget (Session F, brief §5): importing 10,000 GSTR-2B records and matching them against
10,000 book documents must each take under 5 s on the sandbox.

A workspace is seeded with N purchase invoices from 40 suppliers (bulk inserts, as the pipeline leaves them), and a
GSTR-2B of N records is built from them: 70% reported exactly, 10% with an amount off, 5% with a different number
format, and the rest unmatched on either side. Then the two steps are timed on real Postgres:

  import      parse the file, store the return and its records            <= 5 s at 10,000 records
  matching    read the books, reconcile, store the result (`recompute`)     <= 5 s at 10,000 books and 10,000 records

`GST_PERF_RECORDS` sets N (10,000 by default). `PERF_BUDGET_MULTIPLIER` (default 2) gives a shared CI machine slack; on
the sandbox the budget is 5 s as it stands (set it to 1 to hold the sandbox to it). Measured figures are printed (pytest -s) for docs/hardening/PERFORMANCE.md.
"""

from __future__ import annotations

import os
import random
import time
import uuid
from datetime import date, timedelta

from sqlalchemy import func, insert, select

from app.core import normalize as nz
from app.models.document_role import DocumentRole
from app.models.gst import GstMatch, GstReturnRecord
from app.models.work_item import WorkItem
from app.services.gst import builder as b
from app.services.gst import engine, store
from app.services.helm import money
from tests.security.plans import put_on_plan

N = int(os.getenv("GST_PERF_RECORDS", "10000"))
MULTIPLIER = float(os.getenv("PERF_BUDGET_MULTIPLIER", "2.0"))
BUDGET_SECONDS = 5.0
RECIPIENT = b.make_gstin("27", "AAACM1234F")
SUPPLIERS = 40


def _suppliers():
    return [(b.make_gstin("27" if i % 2 else "29", f"AAB{chr(65 + i % 26)}S{1000 + i}K"), f"Supplier {i:02d} Trading Pvt Ltd")
            for i in range(SUPPLIERS)]


def test_import_and_matching_stay_inside_their_budgets(db_session, tenant):
    put_on_plan(db_session, tenant.organization, "business")
    rng = random.Random(20261019)
    suppliers = _suppliers()
    workspace = tenant.workspace
    items, roles, documents = [], [], []
    for n in range(N):
        gstin, name = suppliers[n % SUPPLIERS]
        on = date(2026, 9, 1) + timedelta(days=rng.randint(0, 29))
        taxable = rng.randint(10, 900) * 100
        number = f"S{n % SUPPLIERS:02d}/25-26/{10000 + n}"
        line = b.item(taxable, 18)
        tax = line["cgst"] + line["sgst"]
        item_id = uuid.uuid4()
        entities = {"document_classification": "Invoice", "vendor_name": name, "vendor_gstin": gstin,
                    "buyer_gstin": RECIPIENT, "invoice_number": number, "invoice_date": on.isoformat(),
                    "subtotal": f"{taxable:.2f}", "cgst_amount": f"{line['cgst']:.2f}",
                    "sgst_amount": f"{line['sgst']:.2f}", "tax_amount": f"{tax:.2f}",
                    "total_amount": f"{taxable + tax:.2f}", "currency": "INR"}
        items.append({"id": item_id, "workspace_id": workspace.id, "original_filename": f"inv-{n}.pdf",
                      "stored_filename": f"gst-perf-{item_id.hex}.pdf", "file_type": "application/pdf", "file_size": 2048,
                      "status": "COMPLETED", "pipeline_stage": "COMPLETED", "extracted_entities": entities,
                      "extracted_text": "", "extraction_metadata": {}})
        roles.append({"organization_id": tenant.organization.id, "workspace_id": workspace.id, "work_item_id": item_id,
                      "role": "INVOICE", "role_source": "CLASSIFIER", "role_confidence": 0.9,
                      "vendor_key": nz.vendor_key(name, gstin), "document_number": number, "document_date": on,
                      "currency": "INR", "total_micros": money.to_micros(taxable + tax)})
        documents.append((gstin, name, number, on, taxable))
    for start in range(0, N, 2000):
        db_session.execute(insert(WorkItem), items[start:start + 2000])
        db_session.execute(insert(DocumentRole), roles[start:start + 2000])
    db_session.commit()

    by_supplier: dict[str, list[dict]] = {}
    for n, (gstin, name, number, on, taxable) in enumerate(documents):
        roll = rng.random()
        if roll < 0.15:
            continue  # the supplier never reported it: the books are ahead
        if roll < 0.25:
            taxable += 500  # an amount off
        shown = number.replace("/25-26/", "-") if roll > 0.9 else number
        by_supplier.setdefault(gstin, []).append(b.document(shown, on, taxable))
    extra = N - sum(len(v) for v in by_supplier.values())
    for k in range(extra):  # the supplier reported what Servabo has not seen
        gstin, name = suppliers[k % SUPPLIERS]
        by_supplier.setdefault(gstin, []).append(b.document(f"UNSEEN-{k}", date(2026, 9, 1) + timedelta(days=k % 30), 1000))
    names = dict(suppliers)
    names_by_gstin = {g: n for g, n in suppliers}
    body = {"b2b": [b.supplier(g, names_by_gstin[g], docs, filed_on=date(2026, 10, 9), period="092026")
                    for g, docs in by_supplier.items()]}
    data = b.to_bytes(b.gstr2b(RECIPIENT, "2026-09", body, wrap="status"))

    real_recompute = engine.recompute
    engine.recompute = lambda *a, **k: {}  # time the import on its own
    try:
        started = time.perf_counter()
        result = store.import_file(db_session, workspace=workspace, user_id=tenant.owner.user.id,
                                   file_name="gstr2b.json", data=data)
        db_session.commit()
        import_seconds = time.perf_counter() - started
    finally:
        engine.recompute = real_recompute
    assert result[0]["record_count"] == N

    started = time.perf_counter()
    engine.recompute(db_session, workspace, RECIPIENT)
    db_session.commit()
    matching_seconds = time.perf_counter() - started

    statuses = dict(db_session.execute(select(GstMatch.status, func.count()).where(GstMatch.workspace_id == workspace.id)
                                       .group_by(GstMatch.status)).all())
    print(f"\nGST perf at {N} records / {N} books: import {import_seconds:.2f}s, matching {matching_seconds:.2f}s, "
          f"statuses {statuses}")
    assert db_session.execute(select(func.count()).select_from(GstReturnRecord)).scalar_one() == N
    assert statuses.get("MATCHED", 0) > N * 0.5 and statuses.get("WAITING_FOR_SUPPLIER", 0) > 0
    assert statuses.get("MATCHED_WITH_DIFFERENCES", 0) > 0 and statuses.get("NOT_IN_BOOKS", 0) > 0
    assert import_seconds <= BUDGET_SECONDS * MULTIPLIER, f"import took {import_seconds:.2f}s"
    assert matching_seconds <= BUDGET_SECONDS * MULTIPLIER, f"matching took {matching_seconds:.2f}s"
