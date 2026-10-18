"""TruthMesh's read models at 5,000 documents (Session B).

Overview, graph, matrix and the CSV export used to load every node whole, its 384-number centroid
(and its facts) included, only to read a title and a risk score. A workspace is seeded with N nodes
(`TRUTHMESH_PERF_DOCUMENTS`, 1,000 in the suite, 5,000 for the recorded run), about 1.5 links per
node and a conflict for one node in ten; each read model is timed on real Postgres. The measured
figures are printed (pytest -s) for docs/hardening/PERFORMANCE.md.
"""

from __future__ import annotations

import os
import random
import time
import uuid
from datetime import date

import numpy as np
from sqlalchemy import insert

from app.models.truthmesh import MESH_EMBEDDING_DIMENSION, MeshConflict, MeshLink, MeshNode
from app.models.work_item import WorkItem
from app.services.truthmesh import service
from tests.conftest import Fixture
from tests.security.plans import put_on_plan

DOCUMENTS = int(os.getenv("TRUTHMESH_PERF_DOCUMENTS", "1000"))
MULTIPLIER = float(os.getenv("PERF_BUDGET_MULTIPLIER", "3.0"))
MEASURED: dict[str, float] = {}


def _seed(db, tenant: Fixture) -> None:
    rng = random.Random(20261018)
    workspace, organization = tenant.workspace.id, tenant.organization.id
    ids = [uuid.uuid4() for _ in range(DOCUMENTS)]
    db.execute(insert(WorkItem), [dict(
        id=i, workspace_id=workspace, created_by_user_id=tenant.owner.user.id, original_filename=f"doc-{n}.pdf",
        stored_filename=f"seed_{i.hex}.pdf", file_type="application/pdf", file_size=1024, status="COMPLETED",
        extracted_entities={}) for n, i in enumerate(ids)])
    facts = [{"concept": f"field_{k}", "value": f"value {k} " * 6, "display": f"value {k}"} for k in range(30)]
    db.execute(insert(MeshNode), [dict(
        id=uuid.uuid4(), organization_id=organization, workspace_id=workspace, work_item_id=i,
        kind="INVOICE", kind_label="Invoice", rank=4, title=f"Invoice INV-{n:05d}", document_number=f"INV-{n:05d}",
        counterparty=f"Supplier {n % 40:02d}", currency="USD", amount_micros=rng.randint(1, 9) * 100_000_000,
        document_date=date(2026, 1, 1), facts=[{"concept": "_twin", "filename": f"doc-{n}.pdf"}, *facts],
        terms={"payment": "Net 30"}, identifiers=[f"INV-{n:05d}"], referenced_identifiers=[], parties=[],
        centroid=np.random.default_rng(n).random(MESH_EMBEDDING_DIMENSION).astype(float).tolist(),
        risk_score=rng.choice([0, 0, 0, 10, 40, 75]), degree=3, fingerprint=f"{n:064d}")
        for n, i in enumerate(ids)])
    pairs = set()
    for n in range(int(DOCUMENTS * 1.5)):
        a, b = ids[n % DOCUMENTS], ids[(n * 7 + 1) % DOCUMENTS]
        if a != b:
            pairs.add((min(a, b), max(a, b)))
    db.execute(insert(MeshLink), [dict(
        id=uuid.uuid4(), organization_id=organization, workspace_id=workspace, source_work_item_id=a,
        target_work_item_id=b, relation="RELATES_TO", directed=False, strength=0.8, method="IDENTIFIER",
        signals=[], status="AUTO") for a, b in sorted(pairs)])
    db.execute(insert(MeshConflict), [dict(
        id=uuid.uuid4(), organization_id=organization, workspace_id=workspace, fingerprint=f"{n:064d}",
        kind="DUPLICATE_BILLING", concept="amount", severity=rng.choice(["CRITICAL", "HIGH", "MEDIUM", "LOW"]),
        status="OPEN", title=f"Conflict {n}", summary="Two documents state different amounts.", relation="RELATES_TO",
        work_item_ids=[ids[n], ids[(n + 1) % DOCUMENTS]], document_values=[], details={},
        exposure_micros=1_000_000, currency="USD") for n in range(0, DOCUMENTS, 10)])
    db.commit()


def test_the_read_models_at_scale(db_session, tenant: Fixture) -> None:
    put_on_plan(db_session, tenant.organization, "enterprise")
    _seed(db_session, tenant)
    workspace = tenant.workspace.id
    for name, call in (
        ("overview", lambda: service.overview(db_session, workspace)),
        ("graph", lambda: service.graph(db_session, workspace)),
        ("matrix", lambda: service.matrix(db_session, workspace)),
        ("export", lambda: service.export_csv(db_session, workspace)),
    ):
        db_session.expire_all()
        started = time.perf_counter()
        call()
        MEASURED[name] = time.perf_counter() - started
        print(f"truthmesh {name} at {DOCUMENTS} documents: {MEASURED[name] * 1000:.0f} ms")
    # A person waits for each: two seconds at 5,000 documents, with the shared machine's slack.
    for name, seconds in MEASURED.items():
        assert seconds <= 2.0 * MULTIPLIER * max(1.0, DOCUMENTS / 5_000), (name, seconds)
