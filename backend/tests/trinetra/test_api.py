from datetime import date
import uuid
import pytest
from app.core.config import settings
from app.models.trinetra import TrinetraDecision, TrinetraStatement
from tests.security.plans import put_on_plan
from tests.services.gst.helpers import book_invoice
from app.services.gst import builder as gst_builder

#: The seller's GSTIN carries the seller's PAN (characters 3 to 12), as a real one does.
SUPPLIER_A = gst_builder.make_gstin("27", "ABCDE1234F")


def really_change(db, item):
    """A real change to a document: its stored file is replaced. (Since Final 2T a touch of the row, such as a rename or
    a bumped updated_at, is not a change; see tests/trinetra/test_versions.py.)"""
    item.stored_filename = item.stored_filename + ".replaced"
    db.commit()


@pytest.fixture()
def world(client, db_session, tenant, monkeypatch):
    put_on_plan(db_session, tenant.organization, "business")
    monkeypatch.setattr(settings, "TRINETRA_LIVE_ENABLED", True)
    a = book_invoice(
        db_session,
        tenant,
        number="TR-1",
        supplier="a",
        gstin=SUPPLIER_A,
        on=date(2026, 3, 1),
        taxable=100000,
        extra={"vendor_pan": "ABCDE1234F"},
    )
    b = book_invoice(
        db_session,
        tenant,
        number="TR-2",
        supplier="a",
        gstin=SUPPLIER_A,
        on=date(2026, 3, 2),
        taxable=100000,
        extra={"vendor_pan": "ABCDE1234F"},
    )
    db_session.commit()
    return f"/api/v1/workspaces/{tenant.workspace.id}/trinetra", a, b


def test_sample_has_consistent_totals_and_no_live_write(client, tenant):
    url = f"/api/v1/workspaces/{tenant.workspace.id}/trinetra/sample"
    r = client.get(url, headers=tenant.viewer.headers)
    assert r.status_code == 200, r.text
    data = r.json()
    assert len(data["items"]) == 13            # nine from M0-M6, four more for the whole money model (Final 2T)
    assert int(data["expected_micros"]) == sum(
        int(i["expected_micros"] or 0) for i in data["items"]
    )
    assert all("Tax year 2026" not in i["period"] for i in data["items"])
    assert client.get(url, headers=tenant.other_org_member.headers).status_code in (
        403,
        404,
    )


def test_profile_is_encrypted_and_role_scoped(world, client, tenant, db_session):
    from app.models.trinetra import TrinetraProfile

    url, _, _ = world
    body = {"name": "Synthetic Ltd", "pan": "ABCDE1234F"}
    assert (
        client.post(
            url + "/profiles", headers=tenant.viewer.headers, json=body
        ).status_code
        == 403
    )
    r = client.post(url + "/profiles", headers=tenant.owner.headers, json=body)
    assert r.status_code == 200, r.text
    assert body["pan"] not in r.text
    profile = db_session.get(TrinetraProfile, uuid.UUID(r.json()["id"]))
    assert profile.pan_ciphertext != body["pan"]
    assert (
        client.post(url + "/profiles", headers=tenant.owner.headers, json=body).json()[
            "id"
        ]
        == r.json()["id"]
    )


def test_snapshot_reimport_allocations_and_stale_decisions(
    world, client, tenant, db_session
):
    url, a, b = world
    headers = tenant.owner.headers
    p = client.post(
        url + "/profiles",
        headers=headers,
        json={"name": "Synthetic", "pan": "ABCDE1234F"},
    ).json()["id"]

    def new_credit(doc):
        r = client.post(
            url + "/credits",
            headers=headers,
            json={
                "profile_id": p,
                "work_item_id": str(doc.id),
                "year": 2025,
                "counterparty": "Synthetic deductor",
                "reference": str(doc.id),
                "tan": "ABCD12345E",
                "amount": "2000",
                "source_confirmation": "Reviewed against the approved invoice and deduction advice.",
            },
        )
        assert r.status_code == 200, r.text
        return r.json()

    c1, c2 = new_credit(a), new_credit(b)
    body = {
        "profile_id": p,
        "source_work_item_id": str(a.id),
        "year": 2025,
        "pan": "ABCDE1234F",
        "confirmed": True,
        "rows": [{"tan": "ABCD12345E", "amount": "2000", "reference": "Q4"}],
    }
    r = client.post(url + "/reviewed-statements", headers=headers, json=body)
    assert r.status_code == 200, r.text
    sid = r.json()["id"]
    assert (
        client.post(url + "/reviewed-statements", headers=headers, json=body).json()[
            "id"
        ]
        == sid
    )
    alloc = {
        "revision": 1,
        "action": "ALLOCATE",
        "reason": "Reviewed the source and confirmed this allocation.",
        "allocations": [{"snapshot_id": sid, "line_id": "0", "amount": "2000"}],
    }
    endpoint = url + "/credits/" + c1["id"] + "/decisions"
    r = client.post(endpoint, headers=headers, json=alloc)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "POSTED"
    assert client.post(endpoint, headers=headers, json=alloc).status_code == 409
    assert (
        client.post(
            url + "/credits/" + c2["id"] + "/decisions", headers=headers, json=alloc
        ).status_code
        == 422
    )
    body["rows"][0]["amount"] = "2100"
    assert (
        client.post(
            url + "/reviewed-statements", headers=headers, json=body
        ).status_code
        == 200
    )
    data = client.get(url + "/credits", headers=headers).json()
    assert all(c["posted_micros"] == "0" for c in data["items"])
    assert db_session.query(TrinetraDecision).count() == 3
    assert db_session.query(TrinetraStatement).count() == 2


@pytest.mark.parametrize("plan", ["free", "developer"])
def test_live_read_and_write_require_capability(
    world, client, tenant, db_session, plan
):
    url, _, _ = world
    put_on_plan(db_session, tenant.organization, plan)
    db_session.commit()
    assert client.get(url + "/credits", headers=tenant.owner.headers).status_code == 402
    assert (
        client.post(
            url + "/profiles",
            headers=tenant.owner.headers,
            json={"name": "Synthetic", "pan": "ABCDE1234F"},
        ).status_code
        == 402
    )


def test_launch_gate_remains_closed(world, client, tenant, monkeypatch):
    url, _, _ = world
    monkeypatch.setattr(settings, "TRINETRA_LIVE_ENABLED", False)
    assert client.get(url + "/credits", headers=tenant.owner.headers).status_code == 409
    assert client.get(url + "/sample", headers=tenant.owner.headers).status_code == 200


def test_organization_launch_gate_reports_a_prerequisite_not_an_outage(
    world, client, tenant, monkeypatch, db_session
):
    put_on_plan(db_session, tenant.organization, "enterprise")
    db_session.commit()
    monkeypatch.setattr(settings, "TRINETRA_LIVE_ENABLED", False)
    result = client.get(
        f"/api/v1/organizations/{tenant.organization.id}/trinetra/summary",
        headers=tenant.owner.headers,
    )
    assert result.status_code == 409, result.text
    assert result.json()["detail"]["code"] == "TRINETRA_SOURCE_REVIEW_REQUIRED"
    assert "workspaces" not in result.json()


def test_jwt_rotation_does_not_duplicate_tax_entity(
    world, client, tenant, monkeypatch, db_session
):
    url, _, _ = world
    body = {"name": "Synthetic", "pan": "ABCDE1234F"}
    first = client.post(url + "/profiles", headers=tenant.owner.headers, json=body)
    assert first.status_code == 200
    # Service-level test: the authenticated request does not depend on an old JWT.
    from app.services.trinetra import service
    from app.core.config import settings
    from pydantic import SecretStr

    original = settings.JWT_SECRET_KEY
    monkeypatch.setattr(
        settings,
        "JWT_SECRET_KEY",
        (
            SecretStr("different-key-for-rotation-test")
            if hasattr(original, "get_secret_value")
            else "different-key-for-rotation-test"
        ),
    )
    same = service.create_profile(
        db_session, tenant.workspace, body["name"], body["pan"]
    )
    assert str(same.id) == first.json()["id"]
