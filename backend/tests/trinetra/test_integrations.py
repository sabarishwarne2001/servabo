"""TRINETRA woven into the rest of Servabo (Final 2T, Phase 7): Getting started, search, notifications, the digest, the value receipt,
automation, the public API, the warehouse, the organization view, Recoveries, Helm and the Enterprise controls."""

import uuid
from datetime import datetime, timezone

from app.core.config import settings

import pytest

from app.models.organization import OrganizationRole
from app.models.trinetra import TrinetraProfile, TrinetraStatement
from app.models.workspace import WorkspaceRole
from app.services import getting_started as gs
from tests.security.plans import put_on_plan
from tests.trinetra.test_api import world  # noqa: F401
from tests.trinetra.test_workflows import setup_case


def _view(db, tenant, *, ws_role=WorkspaceRole.ADMIN, org_role=OrganizationRole.OWNER):
    return gs.evaluate(db, organization=tenant.organization, workspace=tenant.workspace, workspace_role=ws_role, organization_role=org_role)


# --- 1. Getting started -----------------------------------------------------------------------------------------------------


def test_the_trinetra_step_ticks_only_when_a_statement_has_really_been_imported(client, tenant, world, db_session):
    assert gs.tick_trinetra(db_session, tenant.workspace.id) is False
    setup_case(client, tenant, world)
    profile = db_session.query(TrinetraProfile).one()
    assert gs.tick_trinetra(db_session, tenant.workspace.id) is False          # a profile and a case are not a statement
    db_session.add(TrinetraStatement(workspace_id=tenant.workspace.id, organization_id=tenant.organization.id, profile_id=profile.id,
                                     year=2025, source_sha256="0" * 64, rows=[], active=True, source_version="t", fingerprint="0" * 64,
                                     parser_version="t", revision=1))
    db_session.flush()
    assert gs.tick_trinetra(db_session, tenant.workspace.id) is True


def test_the_step_is_shown_to_workspace_admins_only_and_says_what_blocks_it(db_session, tenant, monkeypatch):
    from app.core.config import settings

    put_on_plan(db_session, tenant.organization, "business")
    monkeypatch.setattr(settings, "TRINETRA_MODE", "on")
    db_session.flush()
    step = next(s for s in _view(db_session, tenant)["steps"] if s["key"] == "trinetra")
    assert "TDS" in step["title"] and step["note"] is None and step["done"] is False
    assert "trinetra" not in [s["key"] for s in _view(db_session, tenant, ws_role=WorkspaceRole.CONTRIBUTOR)["steps"]]
    assert "trinetra" not in [s["key"] for s in _view(db_session, tenant, ws_role=WorkspaceRole.VIEWER, org_role=OrganizationRole.MEMBER)["steps"]]
    monkeypatch.setattr(settings, "TRINETRA_MODE", "pilot")                    # shipped state: not enrolled yet
    note = next(s for s in _view(db_session, tenant)["steps"] if s["key"] == "trinetra")["note"]
    assert note and "pilot" in note.lower()
    put_on_plan(db_session, tenant.organization, "developer")
    db_session.flush()
    monkeypatch.setattr(settings, "TRINETRA_MODE", "on")
    note = next(s for s in _view(db_session, tenant)["steps"] if s["key"] == "trinetra")["note"]
    assert note and "Business" in note and "Enterprise" in note


# --- 2. Global search -------------------------------------------------------------------------------------------------------


def _search(client, tenant, q, who="owner"):
    r = client.get(f"/api/v1/organizations/{tenant.organization.id}/search", params={"q": q}, headers=getattr(tenant, who).headers)
    assert r.status_code == 200, r.text
    return r.json()


def test_search_finds_a_case_by_invoice_reference_and_customer_name_but_never_by_pan_or_tan(client, tenant, world):
    setup_case(client, tenant, world, reference="TR-SEARCH-9")
    by_reference = _search(client, tenant, "tr-search")["tds_cases"]
    assert len(by_reference) == 1 and by_reference[0]["kind"] == "TDS_CASE" and by_reference[0]["title"] == "TR-SEARCH-9"
    assert "Synthetic deductor" in by_reference[0]["subtitle"] and by_reference[0]["workspace_slug"] == tenant.workspace.slug
    assert [h["title"] for h in _search(client, tenant, "synthetic ded")["tds_cases"]] == ["TR-SEARCH-9"]
    for identifier in ("ABCDE1234F", "ABCD12345E", "abcd1234"):
        assert _search(client, tenant, identifier)["tds_cases"] == []
    assert "ABCDE1234F" not in str(_search(client, tenant, "TR-SEARCH")) and "ABCD12345E" not in str(_search(client, tenant, "TR-SEARCH"))


def test_search_shows_nothing_where_the_page_itself_would_be_locked(client, tenant, world, db_session, monkeypatch):
    from app.core.config import settings

    setup_case(client, tenant, world, reference="TR-LOCK-1")
    assert len(_search(client, tenant, "TR-LOCK")["tds_cases"]) == 1
    monkeypatch.setattr(settings, "TRINETRA_LIVE_ENABLED", None)               # the old yes/no alias would otherwise win
    monkeypatch.setattr(settings, "TRINETRA_MODE", "pilot")                    # not enrolled: the page says so, search stays silent
    assert _search(client, tenant, "TR-LOCK")["tds_cases"] == []
    monkeypatch.setattr(settings, "TRINETRA_MODE", "on")
    put_on_plan(db_session, tenant.organization, "developer")
    db_session.commit()
    assert _search(client, tenant, "TR-LOCK")["tds_cases"] == []


def test_a_person_with_no_grant_on_the_workspace_and_another_organizations_member_find_nothing(client, tenant, world, db_session):
    from app.models.workspace import Workspace, WorkspaceStatus

    setup_case(client, tenant, world, reference="TR-GRANT-1")
    other = Workspace(organization_id=tenant.organization.id, slug="branch", workspace_name="Branch office", status=WorkspaceStatus.ACTIVE)
    db_session.add(other)
    db_session.commit()
    # The contributor holds a grant on "engineering" (where the case is) and may see it; remove that grant and nothing is found.
    assert len(_search(client, tenant, "TR-GRANT", who="contributor")["tds_cases"]) == 1
    from app.models.workspace import WorkspaceMember

    db_session.query(WorkspaceMember).filter_by(workspace_id=tenant.workspace.id, user_id=tenant.contributor.user.id).delete()
    db_session.commit()
    assert _search(client, tenant, "TR-GRANT", who="contributor")["tds_cases"] == []
    r = client.get(f"/api/v1/organizations/{tenant.organization.id}/search", params={"q": "TR-GRANT"}, headers=tenant.other_org_member.headers)
    assert r.status_code in (403, 404) and "TR-GRANT" not in r.text


# --- 5. The value receipt and the monthly summary ----------------------------------------------------------------------------

from tests.trinetra.test_money_model import allocate, decide, get, statement  # noqa: E402


def _receipt(db, tenant, period="month"):
    from app.services import value_receipt

    value_receipt.forget(tenant.organization.id)
    return value_receipt.receipt(db, tenant.organization.id, period)


def test_the_receipt_shows_tds_not_yet_in_the_statement_as_its_own_line_that_never_leads_or_adds(client, tenant, world, db_session):
    url, body, case = setup_case(client, tenant, world)
    assert [f for f in _receipt(db_session, tenant)["found"] if f["key"].startswith("tds_")] == []        # no statement, no figure
    statement(client, tenant, url, body, ["MUMB54321K,10.00,x0,194C,15-Jun-2025,F,FY 2025-26 / AY 2026-27"])
    receipt = _receipt(db_session, tenant)
    [gap] = [f for f in receipt["found"] if f["key"] == "tds_not_in_statement"]
    assert gap["amount_micros"] == 2_000_000_000 and gap["currency"] == "INR" and gap["count"] == 1
    assert "TDS not yet in your statement" in gap["label"] and gap["source"].endswith("/trinetra")
    assert gap["honesty"] == "potential"                         # a possible gap in a tax statement: never confirmed, never money
    assert "TDS" not in (receipt["headline"] or "")             # it never leads the sentence about what Servabo found
    assert not any(f["key"] not in ("tds_not_in_statement",) and f["amount_micros"] == gap["amount_micros"] and f["key"].startswith("gst")
                   for f in receipt["found"])                    # and is never folded into a GST or cash line


def test_tds_now_visible_comes_from_the_closure_ledger_and_is_labelled_as_not_cash(client, tenant, world, db_session):
    url, body, case = setup_case(client, tenant, world)
    statement(client, tenant, url, body, ["MUMB54321K,10.00,x0,194C,15-Jun-2025,F,FY 2025-26 / AY 2026-27"])
    second = statement(client, tenant, url, body, ["ABCD12345E,2000.00,y0,194C,15-Jun-2025,F,FY 2025-26 / AY 2026-27"])
    done = decide(client, tenant, url, get(client, tenant, url, case), "ALLOCATE", allocations=[allocate(second, 0, "2000")])
    decide(client, tenant, url, done.json(), "CA_REVIEWED", reason="Accountant confirmed it in the new statement.")
    receipt = _receipt(db_session, tenant)
    [visible] = [f for f in receipt["found"] if f["key"] == "tds_now_visible"]
    assert visible["amount_micros"] == 2_000_000_000 and "not cash" in visible["label"].lower() and visible["honesty"] == "confirmed"
    assert [f for f in receipt["found"] if f["key"] == "tds_not_in_statement"] == []      # nothing is left unposted
    assert "TDS" not in (receipt["headline"] or "")
    from app.services import getting_started

    assert getting_started.first_money(db_session, tenant.organization.id) is None        # TDS is never "first money found"


def test_the_receipt_has_no_tds_line_when_trinetra_is_not_live_for_the_organization(client, tenant, world, db_session, monkeypatch):
    url, body, case = setup_case(client, tenant, world)
    statement(client, tenant, url, body, ["MUMB54321K,10.00,x0,194C,15-Jun-2025,F,FY 2025-26 / AY 2026-27"])
    monkeypatch.setattr(settings, "TRINETRA_LIVE_ENABLED", None)
    monkeypatch.setattr(settings, "TRINETRA_MODE", "off")
    assert [f for f in _receipt(db_session, tenant)["found"] if f["key"].startswith("tds_")] == []


# --- 7. The public API (Enterprise) -----------------------------------------------------------------------------------------


def test_enterprise_keys_read_cases_and_nothing_else_with_amounts_as_strings_and_no_tax_identifier(client, tenant, world, db_session):
    from tests.security.test_non_human_principals_default_deny import _key
    from tests.trinetra.test_money_model import statement

    url, body, case = setup_case(client, tenant, world, reference="TR-API-1")
    statement(client, tenant, url, body, ["MUMB54321K,10.00,x0,194C,15-Jun-2025,F,FY 2025-26 / AY 2026-27"])
    path = f"/api/v1/organizations/{tenant.organization.id}/trinetra/cases"
    assert client.get(path, headers=tenant.owner.headers).status_code == 402                 # Business: an Enterprise capability
    headers = _key(db_session, tenant, ["trinetra:read"])
    result = client.get(path, headers=headers)
    assert result.status_code == 200, result.text
    data = result.json()
    assert data["total"] == 1 and data["is_sample"] is False
    [item] = data["items"]
    assert item["id"] == case["id"] and item["workspace_id"] == str(tenant.workspace.id) and item["reference"] == "TR-API-1"
    assert item["review_state"] == "OPEN" and item["status"] == "POSSIBLE_MISSING_POSTING" and item["revision"] == case["revision"]
    assert item["expected_micros"] == "2000000000" and item["posted_micros"] == "0" and item["gap_micros"] == "2000000000"
    assert item["currency"] == "INR"
    assert "ABCDE1234F" not in result.text and "ABCD12345E" not in result.text and "deductor_key" not in result.text
    assert client.get(path, params={"limit": 1, "offset": 1}, headers=headers).json()["items"] == []
    assert client.get(path, params={"workspace_id": str(uuid.uuid4())}, headers=headers).json()["total"] == 0
    # A key reads; it never writes, never reads another route, and a person's viewer role does not reach it.
    assert client.post(path, headers=headers, json={}).status_code in (403, 405)
    assert client.get(world[0] + "/credits", headers=headers).status_code == 403
    assert client.get(path, headers=tenant.viewer.headers).status_code == 403


# --- 9. The organization view: one legal entity, counted once ------------------------------------------------------------------


def test_the_organization_view_totals_each_legal_entity_once_and_names_no_pan(client, tenant, world, db_session):
    from tests.security.test_non_human_principals_default_deny import _key  # noqa: F401
    from tests.trinetra.test_money_model import statement

    url, body, case = setup_case(client, tenant, world, reference="TR-ORG-1")
    client.post(url + "/credits", headers=tenant.owner.headers, json={**body, "work_item_id": str(world[2].id), "reference": "TR-ORG-2"})
    statement(client, tenant, url, body, ["MUMB54321K,10.00,x0,194C,15-Jun-2025,F,FY 2025-26 / AY 2026-27"])
    put_on_plan(db_session, tenant.organization, "enterprise")
    db_session.commit()
    org = client.get(f"/api/v1/organizations/{tenant.organization.id}/trinetra/summary", headers=tenant.owner.headers)
    assert org.status_code == 200, org.text
    data = org.json()
    [entity] = data["entities"]
    assert entity["name"] == "Synthetic Ltd" and entity["total"] == 2 and entity["workspace_ids"] == [str(tenant.workspace.id)]
    assert entity["expected_micros"] == "4000000000" and entity["gap_micros"] == "4000000000" and entity["posted_micros"] == "0"
    assert data["totals"] == {k: entity[k] for k in ("total", "unresolved", "expected_micros", "posted_micros", "gap_micros")}
    assert data["totals"]["total"] == sum(w["total"] for w in data["workspaces"])
    assert "ABCDE1234F" not in org.text and "******" not in org.text and entity["entity_id"]


def test_a_legacy_duplicate_profile_for_one_pan_is_one_entity_in_the_organization_view(client, tenant, world, db_session):
    """Profiles made before the one-entity rule can hold the same PAN twice; the view must not count the entity twice."""
    from app.core import encryption
    from app.models.trinetra import TrinetraProfile
    from app.models.workspace import Workspace, WorkspaceStatus

    url, body, case = setup_case(client, tenant, world)
    first = db_session.query(TrinetraProfile).one()
    other = Workspace(organization_id=tenant.organization.id, slug="branch", workspace_name="Branch", status=WorkspaceStatus.ACTIVE)
    db_session.add(other)
    db_session.flush()
    first.org_pan_fingerprint = None                                  # a legacy row, as the migration left it
    db_session.add(TrinetraProfile(organization_id=tenant.organization.id, workspace_id=other.id, name="Synthetic Ltd (branch)",
                                   pan_ciphertext=first.pan_ciphertext, identity_salt_ciphertext=first.identity_salt_ciphertext,
                                   pan_fingerprint="legacy-" + "0" * 57, pan_masked=first.pan_masked, org_pan_fingerprint=None))
    put_on_plan(db_session, tenant.organization, "enterprise")
    db_session.commit()
    data = client.get(f"/api/v1/organizations/{tenant.organization.id}/trinetra/summary", headers=tenant.owner.headers).json()
    [entity] = data["entities"]                                       # one entity, however many profiles hold its PAN
    assert sorted(entity["workspace_ids"]) == sorted([str(tenant.workspace.id), str(other.id)])
    assert entity["total"] == 1 and data["totals"]["total"] == 1 and encryption is not None


# --- 12. Enterprise controls: legal holds and egress lockdown ------------------------------------------------------------------


def _url(tenant, item_id) -> str:
    return f"/api/v1/workspaces/{tenant.workspace.id}/work-items/{item_id}"


def test_a_legal_hold_keeps_the_invoice_and_so_the_case_and_its_history_until_it_is_released(client, tenant, world, db_session):
    from app.models.trinetra import TrinetraCredit, TrinetraDecision
    from app.services.ingestion import retention_service

    url, body, case = setup_case(client, tenant, world)
    invoice = world[1]
    hold = retention_service.place_hold(db_session, organization_id=tenant.organization.id, workspace_id=None, work_item_id=invoice.id,
                                        reason="Litigation hold - Acme v. Example", reference="CASE-1", user_id=tenant.owner.user.id)
    db_session.commit()
    refused = client.delete(_url(tenant, invoice.id), headers=tenant.owner.headers)
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "RETENTION_HOLD"
    assert db_session.query(TrinetraCredit).count() == 1 and db_session.query(TrinetraDecision).count() >= 1
    retention_service.release_hold(db_session, organization_id=tenant.organization.id, hold_id=hold.id, user_id=tenant.owner.user.id)
    db_session.commit()
    assert client.delete(_url(tenant, invoice.id), headers=tenant.owner.headers).status_code in (200, 204)
    db_session.expire_all()
    assert db_session.query(TrinetraCredit).count() == 0                  # without a hold the case goes with its document


def test_a_workspace_wide_hold_keeps_every_document_a_case_rests_on(client, tenant, world, db_session):
    from app.models.trinetra import TrinetraCredit
    from app.services.ingestion import retention_service

    setup_case(client, tenant, world)
    retention_service.place_hold(db_session, organization_id=tenant.organization.id, workspace_id=tenant.workspace.id, work_item_id=None,
                                 reason="Regulatory hold for the 2025-26 inspection", reference=None, user_id=tenant.owner.user.id)
    db_session.commit()
    for item in (world[1], world[2]):
        assert client.delete(_url(tenant, item.id), headers=tenant.owner.headers).status_code == 409
    assert db_session.query(TrinetraCredit).count() == 1


def test_an_inquiry_is_refused_in_words_when_the_organizations_egress_policy_blocks_its_mail_server(client, tenant, world, db_session,
                                                                                                    monkeypatch):
    from types import SimpleNamespace

    from app.core import egress
    from app.services.helm import hands
    from tests.trinetra.test_resolution import customer, draft, step

    url, body, case = setup_case(client, tenant, world)
    customer(db_session, tenant)
    made = draft(client, tenant, url, case).json()
    assert step(client, tenant, url, made, "approve").status_code == 200
    sent = []
    monkeypatch.setattr(hands, "_identity", lambda *a, **k: SimpleNamespace(
        transport_layer="TENANT", smtp=SimpleNamespace(smtp_host="mail.example.invalid", smtp_port=587), from_address="a@b.example",
        sender_name="Acme", reply_to=None))
    monkeypatch.setattr(egress, "decide", lambda *a, **k: SimpleNamespace(allowed=False, explanation="the organization's lockdown has no rule for it"))
    monkeypatch.setattr(hands, "send_mail", lambda *a, **k: sent.append(1))
    refused = step(client, tenant, url, made, "send")
    assert refused.status_code == 422 and "TRINETRA_DESTINATION_REFUSED" in refused.text and "lockdown" in refused.text
    assert sent == []                                                     # nothing left, and the draft stays approved for a retry
