"""Recoveries, live (Final session 2A, N-191): an issue the real engines raise, and its isolation.

The same invoice arrives twice through the real pipeline; the radar finds the duplicate; Recoveries lists it as an issue
with the duplicate's amount, Found. A second workspace's routes never show it and cannot reach it
(`assert_workspace_isolated`): the workspace predicate in `services/recoveries/service._issues`.
"""

from __future__ import annotations

from sqlalchemy import text

from tests.engines.conftest import Engines
from tests.engines.isolation import assert_workspace_isolated


def _invoice(engines: Engines, copy: int) -> str:
    lines = ["NILGIRI TRADERS", "TAX INVOICE", "Invoice No: NT-4410", "Date: 2026-09-12", "Total: 48,500.00 INR"]
    return str(engines.process(f"NT-4410-copy{copy}.pdf", [lines], marker=f"NT-4410-{copy}", classification="Invoice",
                               entities={"vendor_name": "Nilgiri Traders", "invoice_number": "NT-4410",
                                         "invoice_date": "2026-09-12", "total_amount": "48500.00", "currency": "INR"}))


def test_a_duplicate_the_radar_finds_is_a_recoveries_issue_no_other_workspace_sees(engines: Engines) -> None:
    engines.plan("business")
    _invoice(engines, 1)
    _invoice(engines, 2)

    listed = engines.get("/recoveries", as_user=engines.tenant.viewer)
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert body["included"] is True
    duplicates = [i for i in body["items"] if i["kind"] == "DUPLICATE"]
    assert len(duplicates) == 1, body["items"]
    assert duplicates[0]["state"] == "FOUND" and duplicates[0]["title"].startswith("Probable duplicate")
    # The amount is the radar's own stored figure (its fingerprint's total), or none when it read none: never estimated.
    fingerprint = engines.db.execute(text("SELECT total_micros FROM document_fingerprints WHERE work_item_id = :w"),
                                     {"w": duplicates[0]["work_item_id"]}).scalar()
    assert duplicates[0]["exposure_micros"] == fingerprint

    assert_workspace_isolated(engines, collections=("recoveries",))
