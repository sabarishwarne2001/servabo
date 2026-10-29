"""TRINETRA's performance budgets (Final 2T, Phase 9): the summary at 5,000 cases, an import of a full annual statement
(5,000 rows, over a workspace that already holds 5,000 cases and an earlier snapshot, so the baseline comparison is included),
and the organization view over 100 workspaces. Each must take under 5 s on the sandbox.

Bulk inserts leave the data as the pipeline would; the code under test is unchanged. `TRINETRA_PERF_CASES` sets the case
count (5,000 by default; the product's working-set limit). `PERF_BUDGET_MULTIPLIER` (default 2) gives a shared CI machine slack;
set it to 1 to hold the sandbox to 5 s. Measured figures print with `pytest -s` for docs/hardening/PERFORMANCE.md.
"""

from __future__ import annotations

import csv
import hashlib
import io
import os
import time
import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy import insert, update

from app.models.document_role import DocumentRole
from app.models.trinetra import TrinetraCredit, TrinetraStatement
from app.models.work_item import WorkItem
from app.models.workspace import Workspace, WorkspaceStatus
from app.services.helm import money
from app.services.trinetra import service, versions
from app.services.trinetra.statements import detect, template
from tests.security.plans import put_on_plan

CASES = int(os.getenv("TRINETRA_PERF_CASES", "5000"))
MULTIPLIER = float(os.getenv("PERF_BUDGET_MULTIPLIER", "2.0"))
BUDGET_SECONDS = 5.0
CUSTOMERS = 200
PAN = "ABCDE1234F"


def _tan(n: int) -> str:
    return f"{chr(65 + n // 676 % 26)}{chr(65 + n // 26 % 26)}{chr(65 + n % 26)}Z{10000 + n}K"


def _profile(db, workspace, name="Perf Ltd", pan=PAN):
    p = service.create_profile(db, workspace, name, pan)
    db.commit()
    return p


def _direct_profile(db, tenant, workspace, n):
    """A profile written directly (the plan allows ten entities; the organization view is measured over a hundred)."""
    import secrets

    from app.models.trinetra import TrinetraProfile

    pan = f"{chr(65 + n // 26 % 26)}{chr(65 + n % 26)}CDE{1000 + n}F"
    salt = secrets.token_hex(32)
    row = TrinetraProfile(
        organization_id=tenant.organization.id, workspace_id=workspace.id, name=f"Entity {n:03d}",
        identity_salt_ciphertext=service.encryption.encrypt_secret(salt), pan_ciphertext=service.encryption.encrypt_secret(pan),
        pan_fingerprint=service.identity(pan, "PAN", salt), pan_masked="******" + pan[-4:], org_pan_fingerprint=f"perf-{n:03d}" + "0" * 50)
    db.add(row)
    db.commit()
    return row


def _seed_cases(db, tenant, workspace, profile, count, *, snapshot_rows=None):
    """`count` confirmed cases (each on its own invoice) and, when asked, an active snapshot holding `snapshot_rows` rows."""
    salt = service.encryption.decrypt_secret(profile.identity_salt_ciphertext)
    keys = [service.identity(_tan(n), "TAN", salt) for n in range(CUSTOMERS)]
    items, roles, credits = [], [], []
    for n in range(count):
        item_id = uuid.uuid4()
        on = date(2025, 6, 1) + timedelta(days=n % 200)
        total = 100_000 + n
        items.append({"id": item_id, "workspace_id": workspace.id, "original_filename": f"inv-{n}.pdf",
                      "stored_filename": f"trinetra-perf-{item_id.hex}.pdf", "file_type": "application/pdf", "file_size": 2048,
                      "status": "COMPLETED", "pipeline_stage": "COMPLETED", "extracted_text": "", "extraction_metadata": {},
                      "extracted_entities": {"document_classification": "Invoice", "vendor_pan": PAN, "invoice_number": f"INV-{n}",
                                             "invoice_date": on.isoformat(), "total_amount": f"{total}.00", "currency": "INR"}})
        roles.append({"organization_id": tenant.organization.id, "workspace_id": workspace.id, "work_item_id": item_id,
                      "role": "INVOICE", "role_source": "CLASSIFIER", "role_confidence": 0.9, "vendor_key": f"v{n % CUSTOMERS}",
                      "document_number": f"INV-{n}", "document_date": on, "currency": "INR", "total_micros": money.to_micros(total)})
        credits.append({"organization_id": tenant.organization.id, "workspace_id": workspace.id, "profile_id": profile.id,
                        "work_item_id": item_id, "year": 2025, "counterparty": f"Customer {n % CUSTOMERS:03d}",
                        "deductor_key": keys[n % CUSTOMERS], "expected_micros": 2_000_000_000, "reference": f"INV-{n}",
                        "source_version": "pending", "revision": 1, "state": "OPEN", "review": {"origin": "perf"},
                        "evidence_work_item_ids": []})
    for start in range(0, count, 2000):
        db.execute(insert(WorkItem), items[start:start + 2000])
        db.execute(insert(DocumentRole), roles[start:start + 2000])
    db.commit()
    facts = versions.load(db, workspace.id, [i["id"] for i in items])          # the invoices' real fingerprints, so cases are current
    for credit in credits:
        credit["source_version"] = facts[credit["work_item_id"]].invoice
    for start in range(0, count, 2000):
        db.execute(insert(TrinetraCredit), credits[start:start + 2000])
    if snapshot_rows:
        rows = [{"deductor_key": keys[n % CUSTOMERS], "amount_micros": 2_000_000_000 if n % 3 else 1_000_000_000,
                 "reference": f"Q{n}", "section": "194C", "on": "2025-07-15", "status": "F", "booked_on": None, "remarks": "",
                 "paid_micros": None, "deducted_micros": None, "line_no": n + 1} for n in range(snapshot_rows)]
        db.execute(insert(TrinetraStatement).values(
            organization_id=tenant.organization.id, workspace_id=workspace.id, profile_id=profile.id, source_sha256="0" * 64,
            source_meta={"reader": "servabo-template-v1", "reader_label": "Servabo template"}, source_version="v2:perf",
            year=2025, fingerprint=hashlib.sha256(b"perf").hexdigest(), parser_version="servabo-template-v1", rows=rows, active=True,
            revision=1, comparison={}, evidence_work_item_ids=[]))
    db.commit()
    return keys


def _report(label, seconds):
    print(f"\nTRINETRA {label}: {seconds:.2f}s (budget {BUDGET_SECONDS * MULTIPLIER:.1f}s)")


def test_the_summary_at_5000_cases_and_an_annual_statement_import_stay_inside_their_budgets(db_session, tenant, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "TRINETRA_LIVE_ENABLED", True)
    put_on_plan(db_session, tenant.organization, "enterprise")
    workspace = tenant.workspace
    profile = _profile(db_session, workspace)
    _seed_cases(db_session, tenant, workspace, profile, CASES, snapshot_rows=CASES)

    started = time.perf_counter()
    result = service.summary(db_session, workspace)
    summary_seconds = time.perf_counter() - started
    _report(f"summary at {CASES} cases", summary_seconds)
    assert result["total"] == CASES and result["unresolved"] > 0
    assert summary_seconds <= BUDGET_SECONDS * MULTIPLIER, f"summary took {summary_seconds:.2f}s"

    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(template.COLUMNS)
    for n in range(CASES):
        writer.writerow([_tan(n % CUSTOMERS), "2000.00", f"Row {n}", "194C", "15-Jul-2025", "F", "", "", "", "FY 2025-26 / AY 2026-27"])
    data = out.getvalue().encode("utf-8")
    started = time.perf_counter()
    parsed = detect.read("annual.csv", data)
    read_seconds = time.perf_counter() - started
    started = time.perf_counter()
    snapshot = service.import_parsed(db_session, workspace, profile, 2025, parsed, PAN, True, parsed.sha256)
    db_session.commit()
    import_seconds = time.perf_counter() - started
    _report(f"read a {CASES}-row annual statement", read_seconds)
    _report(f"import it (with the baseline comparison over {CASES} cases)", import_seconds)
    assert len(snapshot.rows) == CASES and snapshot.revision == 2 and snapshot.comparison["cases"]
    assert read_seconds + import_seconds <= BUDGET_SECONDS * MULTIPLIER, (
        f"read {read_seconds:.2f}s + import {import_seconds:.2f}s")


def test_the_organization_view_over_100_workspaces_stays_inside_its_budget(client, db_session, tenant, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "TRINETRA_LIVE_ENABLED", True)
    put_on_plan(db_session, tenant.organization, "enterprise")
    per_workspace = max(1, CASES // 250)                                   # 20 cases each: 2,000 over the 100 workspaces
    for n in range(100):
        workspace = tenant.workspace if n == 0 else Workspace(
            organization_id=tenant.organization.id, slug=f"perf-{n:03d}", workspace_name=f"Perf {n:03d}", status=WorkspaceStatus.ACTIVE)
        if n:
            db_session.add(workspace)
            db_session.flush()
        profile = _direct_profile(db_session, tenant, workspace, n)
        _seed_cases(db_session, tenant, workspace, profile, per_workspace)
    path = f"/api/v1/organizations/{tenant.organization.id}/trinetra/summary"
    started = time.perf_counter()
    response = client.get(path, params={"limit": 100}, headers=tenant.owner.headers)
    seconds = time.perf_counter() - started
    _report("organization view over 100 workspaces", seconds)
    assert response.status_code == 200, response.text
    data = response.json()
    assert len(data["workspaces"]) == 100 and len(data["entities"]) == 100
    assert data["totals"]["total"] == per_workspace * 100
    assert seconds <= BUDGET_SECONDS * MULTIPLIER, f"organization view took {seconds:.2f}s"
