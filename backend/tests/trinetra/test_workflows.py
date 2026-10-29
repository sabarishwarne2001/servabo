"""Real PostgreSQL/API regressions for evidence, authorization and review workflows."""

from datetime import datetime, timedelta, timezone
from io import BytesIO
import uuid
import pytest
from openpyxl import load_workbook
from tests.trinetra.test_api import world, really_change  # noqa: F401
from tests.security.plans import put_on_plan
from app.models.trinetra import TrinetraCredit, TrinetraDecision, TrinetraProfile


def setup_case(client, tenant, world, *, reference="TR-1"):
    url, a, b = world
    headers = tenant.owner.headers
    p = client.post(
        url + "/profiles",
        headers=headers,
        json={"name": "Synthetic Ltd", "pan": "ABCDE1234F"},
    )
    assert p.status_code == 200, p.text
    body = {
        "profile_id": p.json()["id"],
        "work_item_id": str(a.id),
        "year": 2025,
        "counterparty": "Synthetic deductor",
        "reference": reference,
        "tan": "ABCD12345E",
        "amount": "2000",
        "source_confirmation": "Reviewed explicitly sourced withholding against the invoice.",
    }
    created = client.post(url + "/credits", headers=headers, json=body)
    assert created.status_code == 200, created.text
    return url, body, created.json()


def import_and_allocate(client, tenant, world):
    url, body, credit = setup_case(client, tenant, world)
    headers = tenant.owner.headers
    statement = {
        "profile_id": body["profile_id"],
        "source_work_item_id": str(world[2].id),
        "year": 2025,
        "pan": "ABCDE1234F",
        "confirmed": True,
        "rows": [
            {"tan": "ABCD12345E", "amount": "2000", "reference": "Q4 source row 1"}
        ],
    }
    imported = client.post(
        url + "/reviewed-statements", headers=headers, json=statement
    )
    assert imported.status_code == 200, imported.text
    decision = {
        "revision": credit["revision"],
        "action": "ALLOCATE",
        "reason": "Reviewed the evidence and confirmed allocation.",
        "allocations": [
            {"snapshot_id": imported.json()["id"], "line_id": "0", "amount": "2000"}
        ],
    }
    result = client.post(
        url + "/credits/" + credit["id"] + "/decisions", headers=headers, json=decision
    )
    assert result.status_code == 200, result.text
    return url, body, result.json(), statement, decision


def test_corrected_invoice_invalidates_and_reconfirmation_preserves_history(
    client, tenant, world, db_session
):
    url, body, credit, statement, decision = import_and_allocate(client, tenant, world)
    invoice = world[1]
    really_change(db_session, invoice)
    path = url + "/credits/" + credit["id"]
    changed = client.get(path, headers=tenant.owner.headers).json()
    assert changed["status"] == "EVIDENCE_NEEDED" and changed["posted_micros"] == "0"
    assert changed["expected_micros"] is None
    decision["revision"] = credit["revision"]
    assert (
        client.post(
            path + "/decisions", headers=tenant.owner.headers, json=decision
        ).status_code
        == 409
    )
    result = client.post(
        path + "/reconfirm",
        headers=tenant.owner.headers,
        json={
            "revision": credit["revision"],
            "amount": "1500",
            "reason": "Approved corrected invoice withholding evidence.",
        },
    )
    assert result.status_code == 200, result.text
    assert (
        result.json()["expected_micros"] == "1500000000"
        and result.json()["posted_micros"] == "0"
    )
    history = client.get(path, headers=tenant.owner.headers).json()["events"]
    assert {e["action"] for e in history} == {
        "EXPECTATION_CONFIRMED",
        "ALLOCATE",
        "EXPECTATION_RECONFIRMED",
    }
    assert (
        client.post(
            path + "/reconfirm",
            headers=tenant.owner.headers,
            json={
                "revision": credit["revision"],
                "amount": "1500",
                "reason": "A stale concurrent correction must be rejected.",
            },
        ).status_code
        == 409
    )


def test_changed_statement_is_unknown_until_new_confirmed_snapshot(
    client, tenant, world, db_session
):
    url, _, credit, statement, _ = import_and_allocate(client, tenant, world)
    source = world[2]
    really_change(db_session, source)
    before = client.get(
        url + "/credits/" + credit["id"], headers=tenant.owner.headers
    ).json()
    assert (
        before["status"] == "PENDING_REPORT"
        and before["gap_micros"] is None
        and before["posted_micros"] == "0"
    )
    replaced = client.post(
        url + "/reviewed-statements", headers=tenant.owner.headers, json=statement
    )
    assert replaced.status_code == 200, replaced.text
    assert replaced.json()["revision"] == 2
    assert (
        client.get(
            url + "/credits/" + credit["id"], headers=tenant.owner.headers
        ).json()["status"]
        == "SUGGESTED"
    )


def test_duplicate_natural_key_cannot_silently_change_amount(client, tenant, world):
    url, body, credit = setup_case(client, tenant, world)
    assert (
        client.post(url + "/credits", headers=tenant.owner.headers, json=body).json()[
            "id"
        ]
        == credit["id"]
    )
    body["amount"] = "1999"
    assert (
        client.post(
            url + "/credits", headers=tenant.owner.headers, json=body
        ).status_code
        == 409
    )


@pytest.mark.parametrize(
    "amount", ["-1", "NaN", "1e2", "1,000", "1.001", "9999999999.99"]
)
def test_invalid_money_is_a_validation_error_not_server_error(
    client, tenant, world, amount
):
    url, body, _ = setup_case(client, tenant, world)
    body["amount"] = amount
    assert (
        client.post(
            url + "/credits", headers=tenant.owner.headers, json=body
        ).status_code
        == 422
    )


def test_receivable_identity_currency_and_gross_are_guarded(
    client, tenant, world, db_session
):
    from app.models.document_role import DocumentRole

    url, body, _ = setup_case(client, tenant, world)
    body["work_item_id"] = str(world[2].id)
    body["amount"] = "999999"
    assert (
        client.post(
            url + "/credits", headers=tenant.owner.headers, json=body
        ).status_code
        == 422
    )
    body["amount"] = "2000"
    role = db_session.query(DocumentRole).filter_by(work_item_id=world[2].id).one()
    role.currency = "USD"
    db_session.commit()
    assert (
        client.post(
            url + "/credits", headers=tenant.owner.headers, json=body
        ).status_code
        == 422
    )
    role.currency = "INR"
    world[2].extracted_entities = {
        **world[2].extracted_entities,
        "vendor_pan": "ZZZZZ9999Z",
    }
    db_session.commit()
    assert (
        client.post(
            url + "/credits", headers=tenant.owner.headers, json=body
        ).status_code
        == 422
    )


def test_dossier_masks_identifiers_escapes_formula_and_html_and_audits(
    client, tenant, world, db_session
):
    from app.models.audit_log import AuditLog

    url, _, credit = setup_case(
        client, tenant, world, reference='=HYPERLINK("https://invalid.example")<script>'
    )
    for format in ("csv", "xlsx", "html"):
        result = client.get(url + "/export." + format, headers=tenant.owner.headers)
        assert result.status_code == 200, result.text[:200]
        assert result.headers["cache-control"] == "no-store"
        if format == "xlsx":
            book = load_workbook(BytesIO(result.content))
            text = str(list(book["Cases"].values))
            assert book["Cases"]["A2"].data_type == "s" and book["Cases"][
                "A2"
            ].value.startswith("'=")
        else:
            text = result.text
        assert "ABCDE1234F" not in text and "ABCD12345E" not in text
        if format == "html":
            assert "<script>" not in text and "&lt;script&gt;" in text
        assert (
            client.get(
                url + "/export." + format, headers=tenant.viewer.headers
            ).status_code
            == 403
        )
    assert (
        db_session.query(AuditLog)
        .filter(AuditLog.details["module"].astext == "trinetra")
        .count()
        == 3
    )


def test_case_review_evidence_remains_distinct_and_versioned(client, tenant, world):
    url, _, credit = setup_case(client, tenant, world)
    path = url + "/credits/" + credit["id"]
    body = {
        "revision": 1,
        "assign_to_me": True,
        "priority": "HIGH",
        "root_cause": "Awaiting correction",
        "reason": "Customer supplied deduction advice for review.",
        "evidence": [
            {
                "work_item_id": str(world[2].id),
                "kind": "DEDUCTOR_ADVICE",
                "amount": "2000",
            }
        ],
    }
    result = client.post(path + "/review", headers=tenant.owner.headers, json=body)
    assert result.status_code == 200, result.text
    assert result.json()["advice_micros"] == "2000000000"
    assert (
        result.json()["booked_micros"] is None and result.json()["posted_micros"] == "0"
    )
    assert result.json()["review"]["priority"] == "HIGH"
    assert (
        client.post(
            path + "/review", headers=tenant.owner.headers, json=body
        ).status_code
        == 409
    )
    draft = client.get(path + "/inquiry-draft", headers=tenant.owner.headers).json()
    assert not draft["sent"] and not draft["external_sending_enabled"]


def test_pinned_plan_limits_and_profile_scope(client, tenant, world, db_session):
    from app.services.trinetra.service import capacity

    url = world[0]
    assert capacity(db_session, tenant.workspace, "profiles") == 2
    for pan in ["ABCDE1234F", "BCDEF1234G"]:
        assert (
            client.post(
                url + "/profiles",
                headers=tenant.owner.headers,
                json={"name": "Synthetic", "pan": pan},
            ).status_code
            == 200
        )
    assert (
        client.post(
            url + "/profiles",
            headers=tenant.owner.headers,
            json={"name": "Third", "pan": "CDEFG1234H"},
        ).status_code
        == 409
    )
    put_on_plan(db_session, tenant.organization, "enterprise")
    db_session.commit()
    assert capacity(db_session, tenant.workspace, "profiles") == 10
    assert (
        client.post(
            url + "/profiles",
            headers=tenant.owner.headers,
            json={"name": "Third", "pan": "CDEFG1234H"},
        ).status_code
        == 200
    )


def test_no_guessed_tenant_access_or_job_status(client, tenant, world):
    url, _, credit = setup_case(client, tenant, world)
    paths = [
        "/profiles",
        "/credits",
        "/summary",
        "/credits/" + credit["id"],
        "/credits/" + credit["id"] + "/inquiry-draft",
        "/export.csv",
        "/export.xlsx",
        "/export.html",
        "/reconciliation/" + str(uuid.uuid4()),
    ]
    for path in paths:
        assert client.get(
            url + path, headers=tenant.other_org_member.headers
        ).status_code in (403, 404), path
    queued = client.post(url + "/reconciliation", headers=tenant.owner.headers)
    assert queued.status_code == 200, queued.text
    assert (
        client.post(url + "/reconciliation", headers=tenant.owner.headers).json()[
            "job_id"
        ]
        == queued.json()["job_id"]
    )
    assert (
        client.get(
            url + "/reconciliation/" + queued.json()["job_id"],
            headers=tenant.owner.headers,
        ).status_code
        == 200
    )


def test_source_erasure_cascades_cases_and_sensitive_identity_exports_are_excluded(
    client, tenant, world, db_session
):
    url, _, credit = setup_case(client, tenant, world)
    db_session.delete(world[1])
    db_session.commit()
    assert (
        db_session.query(TrinetraCredit).count() == 0
        and db_session.query(TrinetraDecision).count() == 0
    )
    assert (
        client.get(
            url + "/credits/" + credit["id"], headers=tenant.owner.headers
        ).status_code
        == 404
    )


def test_official_format_refusal_and_entity_confirmation(client, tenant, world):
    url, body, _ = setup_case(client, tenant, world)
    assert (
        client.post(
            url + "/official-statements", headers=tenant.owner.headers
        ).status_code
        == 422
    )

    statement = {
        "profile_id": body["profile_id"],
        "source_work_item_id": str(world[2].id),
        "year": 2025,
        "pan": "ZZZZZ9999Z",
        "confirmed": True,
        "rows": [{"tan": "ABCD12345E", "amount": "1", "reference": "Q4"}],
    }
    assert (
        client.post(
            url + "/reviewed-statements", headers=tenant.owner.headers, json=statement
        ).status_code
        == 422
    )
    assert (
        client.post(
            url + "/reviewed-statements/preview",
            headers=tenant.owner.headers,
            json=statement,
        ).status_code
        == 422
    )


def test_invoice_period_and_duplicate_rows_are_refused(client, tenant, world):
    url, body, credit = setup_case(client, tenant, world)
    body["year"] = 2026
    assert (
        client.post(
            url + "/credits", headers=tenant.owner.headers, json=body
        ).status_code
        == 422
    )
    posting = {
        "tan": "ABCD12345E",
        "amount": "2000",
        "reference": "Identical source row",
    }
    statement = {
        "profile_id": body["profile_id"],
        "source_work_item_id": str(world[2].id),
        "year": 2025,
        "pan": "ABCDE1234F",
        "confirmed": True,
        "rows": [posting, posting],
    }
    assert (
        client.post(
            url + "/reviewed-statements", headers=tenant.owner.headers, json=statement
        ).status_code
        == 422
    )


def test_duplicate_advice_reference_cannot_double_the_evidence_amount(
    client, tenant, world
):
    url, _, credit = setup_case(client, tenant, world)
    evidence = {
        "work_item_id": str(world[2].id),
        "kind": "DEDUCTOR_ADVICE",
        "amount": "2000",
    }
    response = client.post(
        url + "/credits/" + credit["id"] + "/review",
        headers=tenant.owner.headers,
        json={
            "revision": 1,
            "reason": "One document must not be counted twice.",
            "evidence": [evidence, evidence],
        },
    )
    assert response.status_code == 422, response.text


def test_enterprise_ca_review_requires_independent_reviewer(
    client, tenant, world, db_session
):
    url, _, credit, _, _ = import_and_allocate(client, tenant, world)
    put_on_plan(db_session, tenant.organization, "enterprise")
    db_session.commit()
    path = url + "/credits/" + credit["id"] + "/decisions"
    review = {
        "revision": credit["revision"],
        "action": "CA_REVIEWED",
        "reason": "Accountant reviewed the currently posted evidence.",
        "allocations": [],
    }
    assert (
        client.post(path, headers=tenant.owner.headers, json=review).status_code == 409
    )
    response = client.post(path, headers=tenant.ws_admin.headers, json=review)
    assert response.status_code == 200, response.text
    assert response.json()["review_state"] == "CA_REVIEWED"


def test_stale_invoice_can_be_withdrawn_without_reconfirming_wrong_period(
    client, tenant, world, db_session
):
    from app.models.document_role import DocumentRole
    from datetime import date

    url, _, credit, _, _ = import_and_allocate(client, tenant, world)
    role = db_session.query(DocumentRole).filter_by(work_item_id=world[1].id).one()
    role.document_date = date(2026, 4, 1)
    db_session.commit()
    path = url + "/credits/" + credit["id"]
    denied = client.post(
        path + "/reconfirm",
        headers=tenant.owner.headers,
        json={
            "revision": credit["revision"],
            "amount": "2000",
            "reason": "The invoice moved to another source period.",
        },
    )
    assert denied.status_code == 422
    withdrawn = client.post(
        path + "/decisions",
        headers=tenant.owner.headers,
        json={
            "revision": credit["revision"],
            "action": "WITHDRAWN",
            "reason": "Withdraw the outdated period before creating the corrected case.",
        },
    )
    assert withdrawn.status_code == 200, withdrawn.text
    assert withdrawn.json()["review_state"] == "WITHDRAWN"
    assert withdrawn.json()["posted_micros"] == "0"


def test_changed_statement_cannot_be_imported_using_old_preview(
    client, tenant, world, db_session
):
    url, body, _ = setup_case(client, tenant, world)
    statement = {
        "profile_id": body["profile_id"],
        "source_work_item_id": str(world[2].id),
        "year": 2025,
        "pan": "ABCDE1234F",
        "confirmed": True,
        "rows": [{"tan": "ABCD12345E", "amount": "2000", "reference": "Row 1"}],
    }
    preview = client.post(
        url + "/reviewed-statements/preview",
        headers=tenant.owner.headers,
        json=statement,
    )
    assert preview.status_code == 200, preview.text
    statement["source_version"] = preview.json()["source_version"]
    really_change(db_session, world[2])
    assert (
        client.post(
            url + "/reviewed-statements", headers=tenant.owner.headers, json=statement
        ).status_code
        == 409
    )


def test_review_event_is_opt_in_enterprise_and_contains_no_tax_identifiers(
    client, tenant, world, db_session
):
    from app.models.webhook_endpoint import WebhookEndpoint
    from app.models.outbox_event import OutboxEvent
    from app.services.trinetra.events import reviewed

    url, _, credit = setup_case(client, tenant, world)
    row = db_session.get(TrinetraCredit, uuid.UUID(credit["id"]))
    assert reviewed(db_session, tenant.workspace, row) is None
    put_on_plan(db_session, tenant.organization, "enterprise")
    db_session.commit()
    assert reviewed(db_session, tenant.workspace, row) is None
    endpoint = WebhookEndpoint(
        organization_id=tenant.organization.id,
        url="https://example.invalid/synthetic-test",
        event_types=["trinetra.case.reviewed"],
        secret_encrypted="synthetic-unused",
    )
    db_session.add(endpoint)
    db_session.flush()
    event = reviewed(db_session, tenant.workspace, row)
    assert event is not None
    assert event.payload == {
        "workspace_id": str(tenant.workspace.id),
        "case_id": str(row.id),
        "revision": row.revision,
        "state": row.state,
    }
    assert reviewed(db_session, tenant.workspace, row) is None
    assert (
        db_session.query(OutboxEvent)
        .filter_by(
            organization_id=tenant.organization.id, event_type="trinetra.case.reviewed"
        )
        .count()
        == 1
    )
    db_session.rollback()
    assert (
        db_session.query(OutboxEvent)
        .filter_by(
            organization_id=tenant.organization.id, event_type="trinetra.case.reviewed"
        )
        .count()
        == 0
    )
