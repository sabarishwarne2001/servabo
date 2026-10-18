"""TruthMesh hardening: tenant isolation, roles, plans, concurrency and the audit trail, live.

    pytest tests/engines/test_truthmesh_hardening_live.py -q

`tests/engines/test_truthmesh_live.py` drives real PDFs through the pipeline into the mesh. These
tests need many meshes, two builds at once and two tenants, so they seed the documents the way
extraction leaves them (status COMPLETED, the recorded entities and text) and build with the same
service the rebuild job runs. The documents are the same purchase order, receipt, invoices, scan
and master agreement as the pipeline test, so the mesh holds the same links and conflicts.
"""

from __future__ import annotations

import threading
import uuid
from typing import Any

import pytest
from sqlalchemy import select

from app.models.truthmesh import MeshConflict, MeshLink, MeshNode, MeshState
from app.models.work_item import WorkItem
from tests.conftest import Fixture, TestSessionLocal
from tests.security.plans import put_on_plan

API = "/api/v1"
VENDOR = "Acme Industrial Supplies Ltd"
BUYER = "Caretakers Global Inc"


def _invoice(number: str, date: str, account: str) -> dict:
    return {"vendor_name": VENDOR, "customer_name": BUYER, "invoice_number": number, "po_number": "PO-TM-5001",
            "date": date, "currency": "USD", "subtotal": "1100.00", "tax_amount": "150.00",
            "total_amount": "1250.00", "payment_terms": "Net 30", "vendor_bank_account": account}


DOCUMENTS: list[tuple[str, str, str, list[str], dict]] = [
    ("contract-MSA-TM-2026.pdf", "MSA-TM-2026", "Contract",
     ["MASTER SERVICES AGREEMENT", "Agreement Number: MSA-TM-2026",
      f"Between {BUYER} (Customer) and {VENDOR} (Supplier)",
      "Effective Date: 2026-01-01. Renewal Date: 2026-12-31.",
      "1. Payment. Customer shall pay each undisputed invoice within 30 days of receipt.",
      "4. Termination. Either party may terminate with 60 days written notice before 2026-11-01."],
     {"party_names": [BUYER, VENDOR], "agreement_number": "MSA-TM-2026", "agreement_date": "2026-01-01",
      "termination_date": "2026-12-31", "governing_law": "England and Wales"}),
    ("purchase-order-PO-TM-5001.pdf", "PO-TM-5001", "Purchase Order",
     ["PURCHASE ORDER", f"Buyer: {BUYER}", f"Vendor: {VENDOR}", "PO Number: PO-TM-5001", "PO Total: 1100.00 USD"],
     {"vendor_name": VENDOR, "customer_name": BUYER, "po_number": "PO-TM-5001", "date": "2026-09-01",
      "currency": "USD", "total_amount": "1100.00"}),
    ("goods-receipt-GR-TM-7001.pdf", "GR-TM-7001", "Goods Receipt",
     ["GOODS RECEIPT NOTE", f"Vendor: {VENDOR}", "Receipt Number: GR-TM-7001", "PO Number: PO-TM-5001"],
     {"vendor_name": VENDOR, "customer_name": BUYER, "receipt_number": "GR-TM-7001", "po_number": "PO-TM-5001",
      "date": "2026-09-12"}),
    ("invoice-INV-TM-1001.pdf", "INV-TM-1001", "Invoice",
     ["INVOICE", f"Vendor: {VENDOR}", "Invoice Number: INV-TM-1001", "PO Number: PO-TM-5001"],
     _invoice("INV-TM-1001", "2026-09-15", "GB29 NWBK 6016 1331 9268 19")),
    ("invoice-INV-TM-1002.pdf", "INV-TM-1002", "Invoice",
     ["INVOICE", f"Vendor: {VENDOR}", "Invoice Number: INV-TM-1002", "PO Number: PO-TM-5001",
      "Note: our bank details have changed, please pay the new account."],
     _invoice("INV-TM-1002", "2026-09-20", "GB94 BARC 1020 1530 0934 59")),
    ("scan-of-INV-TM-1001.pdf", "SCAN-TM-1001", "Invoice",
     ["INVOICE (scanned copy)", "SCAN-TM-1001", f"Vendor: {VENDOR}", "Invoice Number: INV-TM-1001",
      "PO Number: PO-TM-5001"],
     _invoice("INV-TM-1001", "2026-09-15", "GB29 NWBK 6016 1331 9268 19")),
]


def seed_documents(db, workspace_id: uuid.UUID, user_id: uuid.UUID, *, tag: str = "") -> dict[str, uuid.UUID]:
    """The documents as extraction leaves them: COMPLETED, with their entities and text."""
    ids: dict[str, uuid.UUID] = {}
    for filename, marker, classification, lines, entities in DOCUMENTS:
        item = WorkItem(
            workspace_id=workspace_id, created_by_user_id=user_id, original_filename=f"{tag}{filename}",
            stored_filename=f"seed_{uuid.uuid4().hex}.pdf", file_type="application/pdf", file_size=1024,
            status="COMPLETED", summary="Seeded.", extracted_text="\n".join(lines),
            extracted_entities={"document_classification": classification, **entities}, extraction_metadata={},
        )
        db.add(item)
        db.flush()
        ids[marker] = item.id
    db.commit()
    return ids


def build(workspace_id: uuid.UUID, organization_id: uuid.UUID) -> None:
    from app.services.truthmesh import service

    with TestSessionLocal() as db:
        service.build_workspace(db, workspace_id=workspace_id, organization_id=organization_id)
        db.commit()


def url(workspace_id: uuid.UUID, path: str) -> str:
    return f"{API}/workspaces/{workspace_id}/truthmesh{path}"


@pytest.fixture()
def mesh(db_session, tenant: Fixture, test_sessions) -> dict[str, uuid.UUID]:
    """An Enterprise tenant whose workspace holds a built mesh."""
    put_on_plan(db_session, tenant.organization, "enterprise")
    ids = seed_documents(db_session, tenant.workspace.id, tenant.owner.user.id)
    build(tenant.workspace.id, tenant.organization.id)
    db_session.expire_all()
    return ids


def _conflicts(client, tenant: Fixture, **params: Any) -> list[dict]:
    response = client.get(url(tenant.workspace.id, "/conflicts"), params={"limit": 200, **params},
                          headers=tenant.owner.headers)
    assert response.status_code == 200, response.text
    return response.json()["items"]


def test_the_seeded_mesh_holds_the_pipeline_tests_conflicts(client, tenant: Fixture, mesh) -> None:
    found = {(c["kind"], c["severity"]) for c in _conflicts(client, tenant)}
    assert ("PAYEE_ACCOUNT_CHANGED", "CRITICAL") in found, found
    assert ("CUMULATIVE_OVERRUN", "CRITICAL") in found, found


# --------------------------------------------------------------------------- concurrency


def test_two_builds_of_one_workspace_at_once_both_succeed(db_session, tenant: Fixture, test_sessions,
                                                          monkeypatch: pytest.MonkeyPatch) -> None:
    """Two rebuild jobs (two clicks, or a rebuild while documents are indexed) overlap on one workspace.

    Each reads the mesh, finds no node for a document and inserts one: the second insert hits
    uq_mesh_nodes_work_item, the job fails, and the handler marks the mesh FAILED although the
    other build succeeded. Builds of one workspace must take turns.
    """
    from app.services.truthmesh import loader
    from app.workers.handlers.truthmesh import handle_rebuild_workspace

    put_on_plan(db_session, tenant.organization, "enterprise")
    seed_documents(db_session, tenant.workspace.id, tenant.owner.user.id)
    workspace_id = tenant.workspace.id

    # Both builds read the documents before either writes a node.
    gate = threading.Barrier(2, timeout=2)
    original = loader.sources

    def sources(*args: Any, **kwargs: Any):
        rows = original(*args, **kwargs)
        try:
            gate.wait()
        except threading.BrokenBarrierError:
            pass  # the other build is waiting its turn: this one goes on alone
        return rows

    monkeypatch.setattr(loader, "sources", sources)
    errors: list[BaseException] = []

    def run() -> None:
        try:
            handle_rebuild_workspace({"workspace_id": str(workspace_id)})
        except BaseException as exc:  # noqa: BLE001 - the test reports it
            errors.append(exc)

    threads = [threading.Thread(target=run) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    assert not errors, [f"{type(e).__name__}: {str(e)[:200]}" for e in errors]
    db_session.expire_all()
    state = db_session.get(MeshState, workspace_id)
    assert state is not None and state.status == "READY", (state.status if state else None, state and state.error)
    nodes = db_session.execute(select(MeshNode).where(MeshNode.workspace_id == workspace_id)).scalars().all()
    assert len(nodes) == len(DOCUMENTS)


# --------------------------------------------------------------------------- Session B
#
# Defects the audit after campaign session 4 reproduced and carried over; each test failed against
# the code as it was.

import time
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import text, update



def _all_conflicts(client, tenant: Fixture) -> dict[str, dict]:
    """Every conflict of the workspace by id, whatever its status."""
    out: dict[str, dict] = {}
    for status in ("OPEN", "ACKNOWLEDGED", "RESOLVED", "DISMISSED"):
        for item in _conflicts(client, tenant, status=status):
            out[item["id"]] = item
    return out


def _involving(client, tenant: Fixture, work_item_id: uuid.UUID) -> list[dict]:
    return [c for c in _all_conflicts(client, tenant).values() if str(work_item_id) in c["work_item_ids"]]


def _overview(client, tenant: Fixture) -> dict:
    response = client.get(url(tenant.workspace.id, "/overview"), headers=tenant.owner.headers)
    assert response.status_code == 200, response.text
    return response.json()


def _assert_resolved_because_deleted(client, tenant: Fixture, work_item_id: uuid.UUID) -> None:
    involved = _involving(client, tenant, work_item_id)
    assert involved, "the seeded mesh has conflicts on this document"
    still_open = [c["kind"] for c in involved if c["status"] in ("OPEN", "ACKNOWLEDGED")]
    assert not still_open, f"conflicts of a deleted document are still open: {still_open}"
    assert all(c["auto_resolved"] and "deleted" in (c["resolution_note"] or "").lower() for c in involved), involved
    overview = _overview(client, tenant)
    assert all(str(work_item_id) not in c["work_item_ids"] for c in overview["top_conflicts"])
    assert overview["documents"] == len(DOCUMENTS) - 1


def test_deleting_a_document_resolves_its_conflicts_at_once(client, tenant: Fixture, mesh) -> None:
    """The conflicts named the document by id with no foreign key, so they stayed OPEN, and in "money at
    risk", until somebody pressed Rebuild."""
    victim = mesh["INV-TM-1002"]
    response = client.delete(f"{API}/workspaces/{tenant.workspace.id}/work-items/{victim}",
                             headers=tenant.owner.headers)
    assert response.status_code == 204, response.text
    _assert_resolved_because_deleted(client, tenant, victim)


def test_a_bulk_delete_resolves_the_conflicts_of_every_deleted_document(client, tenant: Fixture, mesh) -> None:
    victims = [mesh["INV-TM-1002"], mesh["SCAN-TM-1001"]]
    response = client.post(f"{API}/workspaces/{tenant.workspace.id}/work-items/bulk",
                           json={"action": "delete", "ids": [str(i) for i in victims],
                                 "idempotency_key": uuid.uuid4().hex}, headers=tenant.owner.headers)
    assert response.status_code == 200 and response.json()["succeeded"] == 2, response.text
    for victim in victims:
        involved = _involving(client, tenant, victim)
        assert involved and not [c for c in involved if c["status"] in ("OPEN", "ACKNOWLEDGED")], (victim, involved)


def test_the_retention_purge_resolves_the_conflicts_of_the_documents_it_deletes(
    db_session, client, tenant: Fixture, mesh
) -> None:
    from datetime import datetime, timedelta, timezone

    from sqlalchemy.orm import sessionmaker

    from app.models.compliance import RetentionPolicy
    from scripts import sweep_compliance

    victim = mesh["INV-TM-1002"]
    db_session.add(RetentionPolicy(organization_id=tenant.organization.id, work_item_retention_days=90,
                                   auto_purge_enabled=True))
    db_session.execute(text("UPDATE work_items SET created_at = :old WHERE id = :id"),
                       {"old": datetime.now(timezone.utc) - timedelta(days=400), "id": victim})
    db_session.commit()

    deleted = sweep_compliance._purge_work_items(
        sessionmaker(bind=db_session.get_bind()), organization_id=tenant.organization.id, days=90, apply=True,
        batch_size=50)

    assert deleted == 1
    db_session.expire_all()
    involved = _involving(client, tenant, victim)
    assert involved and not [c for c in involved if c["status"] in ("OPEN", "ACKNOWLEDGED")], involved


# ----- a decision's reason

def test_the_reason_for_a_decision_is_in_the_audit_row_and_survives_reopening(
    client, db_session, tenant: Fixture, mesh
) -> None:
    from app.models.audit_log import AuditLog

    conflict = next(c for c in _conflicts(client, tenant) if c["kind"] == "PAYEE_ACCOUNT_CHANGED")
    reason = "The supplier confirmed the new account by phone on 2026-09-21."
    path = url(tenant.workspace.id, f"/conflicts/{conflict['id']}")
    done = client.patch(path, json={"status": "RESOLVED", "note": reason}, headers=tenant.owner.headers)
    assert done.status_code == 200, done.text

    db_session.expire_all()
    rows = db_session.execute(select(AuditLog).where(AuditLog.resource_id == uuid.UUID(conflict["id"]))
                              .order_by(AuditLog.created_at)).scalars().all()
    assert rows and rows[-1].details.get("note") == reason, [r.details for r in rows]

    reopened = client.patch(path, json={"status": "OPEN"}, headers=tenant.owner.headers)
    assert reopened.status_code == 200 and reopened.json()["status"] == "OPEN", reopened.text
    assert reopened.json()["resolution_note"] == reason, "reopening erased the reason it was resolved"
    db_session.expire_all()
    last = db_session.execute(select(AuditLog).where(AuditLog.resource_id == uuid.UUID(conflict["id"]))
                              .order_by(AuditLog.created_at.desc())).scalars().first()
    assert last.details["from"] == "RESOLVED" and last.details["to"] == "OPEN"


# ----- a rebuild while a document is reprocessing

def _link_between(db, a: uuid.UUID, b: uuid.UUID) -> MeshLink | None:
    db.expire_all()
    return db.execute(select(MeshLink).where(
        ((MeshLink.source_work_item_id == a) & (MeshLink.target_work_item_id == b))
        | ((MeshLink.source_work_item_id == b) & (MeshLink.target_work_item_id == a)))).scalar_one_or_none()


@pytest.mark.parametrize("decision", ["CONFIRMED", "REJECTED"])
def test_a_rebuild_while_a_document_reprocesses_keeps_the_decision_on_its_link(
    client, db_session, tenant: Fixture, mesh, decision: str
) -> None:
    """Reprocessing sets the document to PROCESSING, so a rebuild leaves it out and removed its node and
    every link of it, a person's too; the rejected link came back as automatic afterwards."""
    invoice, order = mesh["INV-TM-1002"], mesh["PO-TM-5001"]
    link = _link_between(db_session, invoice, order)
    assert link is not None and link.status == "AUTO"
    decided = client.post(url(tenant.workspace.id, f"/links/{link.id}/decision"), json={"decision": decision},
                          headers=tenant.owner.headers)
    assert decided.status_code == 200, decided.text

    db_session.execute(update(WorkItem).where(WorkItem.id == invoice).values(status="PROCESSING"))
    db_session.commit()
    build(tenant.workspace.id, tenant.organization.id)
    kept = _link_between(db_session, invoice, order)
    assert kept is not None and kept.status == decision, "the person's decision was deleted by the rebuild"

    db_session.execute(update(WorkItem).where(WorkItem.id == invoice).values(status="COMPLETED"))
    db_session.commit()
    build(tenant.workspace.id, tenant.organization.id)
    after = _link_between(db_session, invoice, order)
    assert after is not None and after.status == decision and after.id == link.id, (
        after.status if after else None)


def test_a_rebuild_while_a_document_is_failed_keeps_its_decided_links_and_drops_its_automatic_ones(
    client, db_session, tenant: Fixture, mesh
) -> None:
    invoice, order, receipt = mesh["INV-TM-1002"], mesh["PO-TM-5001"], mesh["GR-TM-7001"]
    confirm = _link_between(db_session, invoice, order)
    client.post(url(tenant.workspace.id, f"/links/{confirm.id}/decision"), json={"decision": "CONFIRMED"},
                headers=tenant.owner.headers)
    automatic = _link_between(db_session, invoice, receipt)
    db_session.execute(update(WorkItem).where(WorkItem.id == invoice).values(status="FAILED"))
    db_session.commit()
    build(tenant.workspace.id, tenant.organization.id)
    assert _link_between(db_session, invoice, order).status == "CONFIRMED"
    if automatic is not None:
        assert _link_between(db_session, invoice, receipt) is None, "an automatic link of a failed document stays"
    nodes = {n.work_item_id for n in db_session.execute(select(MeshNode).where(
        MeshNode.workspace_id == tenant.workspace.id)).scalars()}
    assert invoice not in nodes, "a failed document is not in the mesh"


# ----- a dismissal during a rebuild

def test_a_dismissal_made_during_a_rebuild_waits_for_it_and_is_not_overwritten(
    db_session, client, tenant: Fixture, mesh, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F-382: a build holds the workspace's mesh lock, so a person's decision waits for it instead of
    being overwritten by 'auto-resolved'. A document is changed so the build no longer detects the
    conflict, the build is held part-way, the dismissal is sent, and only then does the build go on."""
    from app.services.truthmesh import loader

    conflict = next(c for c in _conflicts(client, tenant) if c["kind"] == "PAYEE_ACCOUNT_CHANGED")
    changed = db_session.get(WorkItem, mesh["INV-TM-1002"])
    entities = dict(changed.extracted_entities)
    entities["vendor_bank_account"] = "GB29 NWBK 6016 1331 9268 19"  # now the same account as INV-TM-1001
    changed.extracted_entities = entities
    db_session.commit()

    held, release = threading.Event(), threading.Event()
    original = loader.sources

    def sources(*args: Any, **kwargs: Any):
        rows = original(*args, **kwargs)
        held.set()
        assert release.wait(timeout=30)
        return rows

    monkeypatch.setattr(loader, "sources", sources)
    decided_at: list[float] = []

    builder = threading.Thread(target=build, args=(tenant.workspace.id, tenant.organization.id))
    builder.start()
    assert held.wait(timeout=20), "the build did not start"

    # The decision, through the service the route uses, in its own session: it must wait for the lock.
    from app.services.truthmesh import service

    def decide() -> str:
        with TestSessionLocal() as session:
            service.lock_workspace(session, tenant.workspace.id, wait_seconds=service.DECISION_LOCK_WAIT_SECONDS)
            row = session.get(MeshConflict, uuid.UUID(conflict["id"]))
            service.decide_conflict(session, conflict=row, status="DISMISSED", note="It is the same account.",
                                    actor_id=tenant.owner.user.id)
            session.commit()
            decided_at.append(time.monotonic())
            return row.status

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(decide)
        time.sleep(1.5)
        assert not future.done(), "the dismissal ran while a build held the mesh"
        released_at = time.monotonic()
        release.set()
        assert future.result(timeout=60) == "DISMISSED"
    builder.join(timeout=60)
    assert decided_at[0] >= released_at, "the dismissal did not wait for the build"
    db_session.expire_all()
    final = db_session.get(MeshConflict, uuid.UUID(conflict["id"]))
    assert final.status == "DISMISSED" and not final.auto_resolved
    assert final.resolution_note == "It is the same account."


# ----- small things

def test_a_huge_offset_is_refused_not_a_server_error(client, tenant: Fixture, mesh) -> None:
    response = client.get(url(tenant.workspace.id, "/conflicts"), params={"offset": 10**30},
                          headers=tenant.owner.headers)
    assert response.status_code == 422, (response.status_code, response.text[:200])
    ok = client.get(url(tenant.workspace.id, "/conflicts"), params={"offset": 100_000}, headers=tenant.owner.headers)
    assert ok.status_code == 200 and ok.json()["items"] == []


def test_simulating_a_document_that_does_not_exist_answers_not_found(client, tenant: Fixture, mesh) -> None:
    body = {"scenario": "DELAY", "work_item_id": str(uuid.uuid4()), "days": 5}
    missing = client.post(url(tenant.workspace.id, "/simulations"), json=body, headers=tenant.owner.headers)
    assert missing.status_code == 404, (missing.status_code, missing.text[:200])


def test_rebuild_requests_are_coalesced_while_one_is_waiting(client, db_session, tenant: Fixture, mesh) -> None:
    from app.models.job import Job, JobStatus
    from app.services.truthmesh import vocabulary as v

    first = client.post(url(tenant.workspace.id, "/rebuild"), headers=tenant.owner.headers)
    second = client.post(url(tenant.workspace.id, "/rebuild"), headers=tenant.owner.headers)
    third = client.post(url(tenant.workspace.id, "/rebuild"), headers=tenant.owner.headers)
    assert [r.status_code for r in (first, second, third)] == [202, 202, 202]
    assert first.json()["job_id"] == second.json()["job_id"] == third.json()["job_id"]
    db_session.expire_all()
    waiting = db_session.execute(select(Job).where(Job.job_type == v.JOB_REBUILD_WORKSPACE,
                                                   Job.status == JobStatus.PENDING)).scalars().all()
    assert len(waiting) == 1


def test_the_read_models_do_not_load_every_nodes_embedding(client, db_session, tenant: Fixture, mesh) -> None:
    """Overview, graph, matrix and the CSV export loaded each node whole, its 384-number centroid too."""
    from sqlalchemy import event

    statements: list[str] = []

    def capture(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
        statements.append(statement)

    event.listen(db_session.get_bind(), "before_cursor_execute", capture)
    try:
        for path in ("/overview", "/graph", "/matrix", "/conflicts/export.csv"):
            assert client.get(url(tenant.workspace.id, path), headers=tenant.owner.headers).status_code == 200
    finally:
        event.remove(db_session.get_bind(), "before_cursor_execute", capture)
    selecting = [s for s in statements if "FROM mesh_nodes" in s and s.lstrip().upper().startswith("SELECT")]
    assert selecting
    heavy = [s[:160] for s in selecting if "mesh_nodes.centroid" in s]
    assert not heavy, heavy


def test_erasing_a_person_takes_their_documents_out_of_the_mesh(db_session, tenant: Fixture, test_sessions) -> None:
    """GDPR erasure emptied the person's documents but left their mesh nodes (title, facts, parties,
    counterparty), the conflicts quoting their values and the simulations that reached them."""
    from app.services.compliance import erasure_service

    put_on_plan(db_session, tenant.organization, "enterprise")
    ids = seed_documents(db_session, tenant.workspace.id, tenant.contributor.user.id)
    build(tenant.workspace.id, tenant.organization.id)
    db_session.expire_all()
    assert db_session.execute(select(MeshNode).where(MeshNode.workspace_id == tenant.workspace.id)).scalars().all()
    assert db_session.execute(select(MeshConflict).where(MeshConflict.workspace_id == tenant.workspace.id)
                              ).scalars().all()

    from app.models.truthmesh import MeshSimulation
    from app.services.truthmesh import service

    with TestSessionLocal() as session:
        service.simulate(session, workspace_id=tenant.workspace.id, organization_id=tenant.organization.id,
                         actor_id=tenant.owner.user.id, work_item_id=ids["PO-TM-5001"], scenario="DELAY",
                         parameters={"days": 5})
        session.commit()
    assert db_session.execute(select(MeshSimulation)).scalars().all()

    erasure_service.erase_subject(db_session, organization=tenant.organization,
                                  subject_user_id=tenant.contributor.user.id, erasure_ticket="DSR-TM-1",
                                  actor_user_id=tenant.owner.user.id)
    db_session.commit()
    db_session.expire_all()

    assert not db_session.execute(select(MeshNode).where(MeshNode.workspace_id == tenant.workspace.id)
                                  ).scalars().all(), "the erased person's documents are still in the mesh"
    assert not db_session.execute(select(MeshLink).where(MeshLink.workspace_id == tenant.workspace.id)
                                  ).scalars().all()
    left = db_session.execute(select(MeshConflict).where(MeshConflict.workspace_id == tenant.workspace.id)
                              ).scalars().all()
    assert not left, [c.title for c in left]
    assert not db_session.execute(select(MeshSimulation)).scalars().all(), "a simulation that reached them stays"
