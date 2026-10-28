"""Replay, concurrent reviews, bounded reads and reversible-schema checks."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import date
import uuid
from types import SimpleNamespace
import pytest
from fastapi import HTTPException
from sqlalchemy import event, text
from tests.trinetra.test_api import world  # noqa: F401
from tests.trinetra.test_workflows import setup_case, import_and_allocate
from tests.conftest import TestSessionLocal, TEST_DB_URL
from app.core.config import settings
from app.models.workspace import Workspace
from app.models.trinetra import TrinetraCredit, TrinetraProfile, TrinetraStatement
from app.services.trinetra import service


def test_concurrent_reviewers_cannot_double_allocate(client, tenant, world, db_session):
    url, body, credit = setup_case(client, tenant, world)
    imported = client.post(
        url + "/reviewed-statements",
        headers=tenant.owner.headers,
        json={
            "profile_id": body["profile_id"],
            "source_work_item_id": str(world[2].id),
            "year": 2025,
            "pan": "ABCDE1234F",
            "confirmed": True,
            "rows": [{"tan": "ABCD12345E", "amount": "2000", "reference": "Q4"}],
        },
    )
    assert imported.status_code == 200, imported.text
    workspace_id = tenant.workspace.id
    user_id = tenant.owner.user.id
    db_session.commit()

    def decide():
        with TestSessionLocal() as db:
            w = db.get(Workspace, workspace_id)
            p = service.profile(db, w, uuid.UUID(body["profile_id"]))
            row = db.get(TrinetraCredit, uuid.UUID(credit["id"]))
            try:
                service.decide(
                    db,
                    w,
                    row,
                    p,
                    user_id,
                    1,
                    "ALLOCATE",
                    "Concurrent allocation reviewed against evidence.",
                    [
                        SimpleNamespace(
                            snapshot_id=uuid.UUID(imported.json()["id"]),
                            line_id="0",
                            amount="2000",
                        )
                    ],
                )
                db.commit()
                return 200
            except HTTPException as exc:
                db.rollback()
                return exc.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: decide(), range(2))) == [200, 409]


def test_worker_replay_and_status_gates(client, tenant, world, db_session, monkeypatch):
    from app.workers.handlers import trinetra
    from app.models.organization import OrganizationStatus

    setup_case(client, tenant, world)

    @contextmanager
    def session():
        yield db_session

    monkeypatch.setattr(trinetra, "SessionLocal", session)
    payload = {
        "organization_id": str(tenant.organization.id),
        "workspace_id": str(tenant.workspace.id),
    }
    assert (
        trinetra.handle_recompute(payload)
        == trinetra.handle_recompute(payload)
        == {"status": "complete", "cases": 1, "unresolved": 1}
    )
    assert (
        trinetra.handle_recompute({**payload, "organization_id": str(uuid.uuid4())})[
            "status"
        ]
        == "unavailable"
    )
    monkeypatch.setattr(settings, "TRINETRA_LIVE_ENABLED", False)
    assert trinetra.handle_recompute(payload)["status"] == "blocked"


def test_enterprise_api_key_scope_is_read_only_and_plan_enforced(
    client, tenant, world, db_session
):
    from tests.security.test_non_human_principals_default_deny import _key
    from tests.security.plans import put_on_plan

    setup_case(client, tenant, world)
    url = f"/api/v1/organizations/{tenant.organization.id}/trinetra/summary"
    assert client.get(url, headers=tenant.owner.headers).status_code == 402
    headers = _key(db_session, tenant, ["trinetra:read"])
    result = client.get(url, headers=headers)
    assert result.status_code == 200, result.text
    assert [r["workspace_id"] for r in result.json()["workspaces"]] == [
        str(tenant.workspace.id)
    ]
    assert client.get(world[0] + "/credits", headers=headers).status_code == 403
    assert (
        client.post(
            world[0] + "/profiles",
            headers=headers,
            json={"name": "Denied", "pan": "ABCDE1234F"},
        ).status_code
        == 403
    )
    put_on_plan(db_session, tenant.organization, "business")
    db_session.commit()
    assert client.get(url, headers=headers).status_code == 402


def test_summary_uses_bounded_database_queries(client, tenant, world, db_session):
    from tests.services.gst.helpers import book_invoice, SUPPLIER_A
    from app.models.document_role import DocumentRole

    _, body, _ = setup_case(client, tenant, world)
    profile = db_session.get(TrinetraProfile, uuid.UUID(body["profile_id"]))
    for i in range(99):
        invoice = book_invoice(
            db_session,
            tenant,
            number=f"BOUND-{i}",
            supplier="a",
            gstin=SUPPLIER_A,
            on=date(2026, 3, 1),
            taxable=100000,
            extra={"vendor_pan": "ABCDE1234F"},
        )
        db_session.add(
            TrinetraCredit(
                organization_id=tenant.organization.id,
                workspace_id=tenant.workspace.id,
                profile_id=profile.id,
                work_item_id=invoice.id,
                year=2025,
                counterparty="Synthetic",
                deductor_key="opaque",
                expected_micros=2000000000,
                reference=f"BOUND-{i}",
                source_version=service.invoice_version(db_session, tenant.workspace, invoice.id),
            )
        )
    db_session.commit()
    count = []

    def query(*args):
        count.append(1)

    connection = db_session.connection()
    event.listen(connection, "before_cursor_execute", query)
    try:
        result = service.summary(db_session, tenant.workspace)
    finally:
        event.remove(connection, "before_cursor_execute", query)
    assert result["total"] == 100 and result["expected_micros"] == 200000000000
    assert (
        len(count) <= 9
    ), f"{len(count)} queries for 100 cases; per-case database queries are not allowed"


def test_canonical_role_change_invalidates_expectation(
    client, tenant, world, db_session
):
    from app.models.document_role import DocumentRole

    url, _, credit = setup_case(client, tenant, world)
    role = db_session.query(DocumentRole).filter_by(work_item_id=world[1].id).one()
    role.currency = "USD"
    db_session.commit()
    result = client.get(
        url + "/credits/" + credit["id"], headers=tenant.owner.headers
    ).json()
    assert result["status"] == "EVIDENCE_NEEDED" and result["expected_micros"] is None


def test_migration_down_up_with_populated_trinetra_rows(
    client, tenant, world, db_session
):
    from alembic import command
    from alembic.config import Config

    import_and_allocate(client, tenant, world)
    workspace_id = tenant.workspace.id
    db_session.commit()
    db_session.close()
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", TEST_DB_URL)
    command.downgrade(config, "k1a7_pack_check_dismissals")
    command.upgrade(config, "head")
    from alembic.script import ScriptDirectory

    # Back at the single head (named by Alembic, so a later migration does not break this test).
    assert (
        db_session.execute(text("select version_num from alembic_version")).scalar()
        == ScriptDirectory.from_config(config).get_current_head()
    )
    assert db_session.query(TrinetraCredit).count() == 0
    assert db_session.get(Workspace, workspace_id) is not None


def test_platform_rotation_preserves_profile_and_identity(
    client, tenant, world, db_session, monkeypatch
):
    from cryptography.fernet import Fernet
    from app.core import encryption
    from app.core.config import settings
    from app.services import encryption_rotation_service

    old, new = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    monkeypatch.setattr(settings, "_encryption_key_list", [old], raising=False)
    encryption.reset_encryption()
    try:
        _, body, _ = setup_case(client, tenant, world)
        p = db_session.get(TrinetraProfile, uuid.UUID(body["profile_id"]))
        original = p.pan_fingerprint
        salt = encryption.decrypt_secret(p.identity_salt_ciphertext)
        monkeypatch.setattr(settings, "_encryption_key_list", [new, old])
        encryption.reset_encryption()
        reports = encryption_rotation_service.reencrypt_all_smtp_passwords(
            db_session, dry_run=False
        )
        assert not any(r.failed for r in reports)
        db_session.expire_all()
        monkeypatch.setattr(settings, "_encryption_key_list", [new])
        encryption.reset_encryption()
        assert encryption.decrypt_secret(p.pan_ciphertext) == "ABCDE1234F"
        assert encryption.decrypt_secret(p.identity_salt_ciphertext) == salt
        assert p.pan_fingerprint == original
    finally:
        encryption.reset_encryption()
