"""Document packs do what they promise (Final session 1, Phase 6, F-408), live.

* Enabling a pack PROPOSES its suggested checks in Clause assertions; accepting one is one click that creates a real,
  active clause check; a check the administrator turns down is not proposed again; disabling the pack withdraws them.
* A check the engine reads with an AI model says so, and cannot be added without the person confirming it.
* A plan without Clause assertions is offered nothing; a contributor cannot accept; another workspace is untouched.
* Starting a redaction of a document the pack recognises suggests the pack's redaction profile.
"""

from __future__ import annotations

import uuid

import pytest

from tests.engines.conftest import Engines
from tests.engines.test_batch_ingestion_live import platform_presets  # noqa: F401  (fixture)
from tests.engines.test_document_packs_live import DOCUMENTS, _pack, _read, _switch

pytestmark = pytest.mark.usefixtures("platform_presets")

MSA_TYPED = "A limitation of liability is present."
MSA_PAYMENT = "Payment terms are no longer than 60 days."
NDA_AI = "A governing law is named."


def _url(engines: Engines, path: str = "", workspace_id: uuid.UUID | None = None) -> str:
    return f"/api/v1/workspaces/{workspace_id or engines.ws}/document-presets{path}"


def _proposals(engines: Engines, *, as_user=None) -> dict:
    persona = as_user or engines.tenant.owner
    response = engines.client.get(_url(engines, "/check-proposals"), headers=persona.headers)
    assert response.status_code == 200, response.text
    return response.json()


def _sentences(engines: Engines) -> list[str]:
    return [p["sentence"] for p in _proposals(engines)["proposals"]]


def _accept(engines: Engines, sentence: str, *, acknowledge: bool = False, as_user=None):
    persona = as_user or engines.tenant.owner
    key = next(p["key"] for p in _proposals(engines)["proposals"] if p["sentence"] == sentence)
    return engines.client.post(_url(engines, "/check-proposals/accept"), json={"key": key, "acknowledge_llm": acknowledge},
                               headers=persona.headers)


def _clause_checks(engines: Engines) -> list[dict]:
    response = engines.client.get(f"/api/v1/workspaces/{engines.ws}/assertions/clause-checks",
                                  headers=engines.tenant.owner.headers)
    assert response.status_code == 200, response.text
    return response.json()


def test_enabling_a_pack_proposes_its_checks_and_disabling_withdraws_them(engines: Engines) -> None:
    engines.plan("enterprise")
    msa = _pack(engines, "msa")
    assert _proposals(engines) == {"available": True, "proposals": []}, "nothing is proposed before a pack is enabled"
    _switch(engines, msa, True)
    body = _proposals(engines)
    assert body["available"] is True
    assert sorted(p["sentence"] for p in body["proposals"]) == sorted([MSA_PAYMENT, MSA_TYPED])
    typed = next(p for p in body["proposals"] if p["sentence"] == MSA_PAYMENT)
    assert typed["requires_acknowledgement"] is False and typed["preset_label"] == msa["label"]
    assert typed["understood_as"], "the engine says in words what it will check"
    assert _clause_checks(engines) == [], "enabling the pack adds nothing behind anyone's back"
    _switch(engines, _pack(engines, "msa"), False)
    assert _proposals(engines)["proposals"] == []


def test_accepting_a_check_creates_an_active_clause_check_once(engines: Engines) -> None:
    engines.plan("enterprise")
    _switch(engines, _pack(engines, "msa"), True)
    accepted = _accept(engines, MSA_TYPED)
    assert accepted.status_code == 201, accepted.text
    rule_id = accepted.json()["rule_id"]
    assert accepted.json()["is_active"] is True
    checks = _clause_checks(engines)
    assert [c["rule_id"] for c in checks] == [rule_id] and checks[0]["is_active"] is True
    assert checks[0]["definition"]["sentence"].rstrip(".") == MSA_TYPED.rstrip(".")
    assert checks[0]["definition"]["family"] != "llm"
    assert MSA_TYPED not in _sentences(engines), "an added check is not proposed again"
    assert MSA_PAYMENT in _sentences(engines)


def test_severity_sets_the_confidence_the_check_is_saved_with(engines: Engines) -> None:
    engines.plan("enterprise")
    _switch(engines, _pack(engines, "msa"), True)
    proposal = next(p for p in _proposals(engines)["proposals"] if p["sentence"] == MSA_TYPED)
    assert proposal["threshold"] == {"HIGH": "0.97", "MEDIUM": "0.95", "LOW": "0.90"}[proposal["severity"]]
    assert _accept(engines, MSA_TYPED).status_code == 201
    saved = _clause_checks(engines)[0]["definition"]
    assert saved["threshold"].startswith(proposal["threshold"])


def test_a_check_read_by_an_ai_model_says_so_and_needs_the_person_to_confirm(engines: Engines) -> None:
    engines.plan("enterprise")
    _switch(engines, _pack(engines, "nda"), True)
    ai = next(p for p in _proposals(engines)["proposals"] if p["sentence"] == NDA_AI)
    assert ai["requires_acknowledgement"] is True
    refused = _accept(engines, NDA_AI)
    assert refused.status_code == 409 and "AI model" in refused.json()["detail"], refused.text
    assert _clause_checks(engines) == []
    accepted = _accept(engines, NDA_AI, acknowledge=True)
    assert accepted.status_code == 201, accepted.text
    check = _clause_checks(engines)[0]
    assert check["definition"]["family"] == "llm" and check["definition"]["llm_acknowledged_by"]


def test_a_check_turned_down_is_not_proposed_again_and_the_server_refuses_a_second_accept(engines: Engines) -> None:
    engines.plan("enterprise")
    msa = _pack(engines, "msa")
    _switch(engines, msa, True)
    key = next(p["key"] for p in _proposals(engines)["proposals"] if p["sentence"] == MSA_PAYMENT)
    done = engines.client.post(_url(engines, "/check-proposals/dismiss"), json={"key": key}, headers=engines.tenant.owner.headers)
    assert done.status_code == 204, done.text
    assert MSA_PAYMENT not in _sentences(engines)
    _switch(engines, _pack(engines, "msa"), False)
    _switch(engines, _pack(engines, "msa"), True)
    assert MSA_PAYMENT not in _sentences(engines), "turning the pack off and on does not bring a declined check back"
    again = engines.client.post(_url(engines, "/check-proposals/accept"), json={"key": key}, headers=engines.tenant.owner.headers)
    assert again.status_code == 409
    nothing = engines.client.post(_url(engines, "/check-proposals/dismiss"), json={"key": "0" * 24}, headers=engines.tenant.owner.headers)
    assert nothing.status_code == 409


def test_a_plan_without_clause_assertions_is_offered_nothing_and_cannot_add(engines: Engines) -> None:
    engines.plan("business")
    msa = _pack(engines, "msa")
    _switch(engines, msa, True)
    assert _proposals(engines) == {"available": False, "proposals": []}
    refused = engines.client.post(_url(engines, "/check-proposals/accept"), json={"key": "a" * 24},
                                  headers=engines.tenant.owner.headers)
    assert refused.status_code == 402, refused.text


def test_only_an_administrator_manages_proposals(engines: Engines) -> None:
    engines.plan("enterprise")
    _switch(engines, _pack(engines, "msa"), True)
    contributor = engines.tenant.contributor
    assert engines.client.get(_url(engines, "/check-proposals"), headers=contributor.headers).status_code == 403
    key = _proposals(engines)["proposals"][0]["key"]
    assert engines.client.post(_url(engines, "/check-proposals/accept"), json={"key": key},
                               headers=contributor.headers).status_code == 403
    assert engines.client.post(_url(engines, "/check-proposals/dismiss"), json={"key": key},
                               headers=contributor.headers).status_code == 403
    assert _clause_checks(engines) == []


def test_another_workspace_sees_none_of_it(engines: Engines) -> None:
    engines.plan("enterprise")
    _switch(engines, _pack(engines, "msa"), True)
    other = engines.post("/workspaces", {"workspace_name": f"Packs C {uuid.uuid4().hex[:6]}"}, org=True)
    assert other.status_code in (200, 201), other.text
    other_id = uuid.UUID(other.json()["id"])
    seen = engines.client.get(_url(engines, "/check-proposals", other_id), headers=engines.tenant.owner.headers)
    assert seen.status_code == 200 and seen.json()["proposals"] == []
    key = _proposals(engines)["proposals"][0]["key"]
    cross = engines.client.post(_url(engines, "/check-proposals/accept", other_id), json={"key": key},
                                headers=engines.tenant.owner.headers)
    assert cross.status_code == 409, "a key from one workspace's packs is not honoured in another"


# ------------------------------------------------------------------------------------- the redaction profile


def _suggestion(engines: Engines, item_id: uuid.UUID, *, as_user=None, workspace_id=None):
    persona = as_user or engines.tenant.owner
    return engines.client.get(_url(engines, f"/redaction-suggestion?work_item_id={item_id}", workspace_id), headers=persona.headers)


def test_a_document_the_pack_recognises_gets_the_packs_redaction_profile_suggested(engines: Engines) -> None:
    engines.plan("enterprise")
    nda = _pack(engines, "nda")
    item, _ = _read(engines, DOCUMENTS[("nda", "mutual")], "NDA-PACK-1")
    quiet = _suggestion(engines, item)
    assert quiet.status_code == 200 and quiet.json() is None, "no pack enabled, nothing suggested"

    _switch(engines, nda, True)
    suggested = _suggestion(engines, item)
    assert suggested.status_code == 200, suggested.text
    assert suggested.json() == {"profile": nda["redaction_profile"], "preset_label": nda["label"], "document_type": "nda"}

    unrelated, _ = _read(engines, ["Weekly stand-up notes", "Nothing about agreements here"], "PLAIN-NOTE-1")
    assert _suggestion(engines, unrelated).json() is None, "a document the pack does not recognise gets no suggestion"

    _switch(engines, _pack(engines, "nda"), False)
    assert _suggestion(engines, item).json() is None


def test_the_suggestion_is_scoped_to_the_workspace_and_open_to_a_contributor(engines: Engines) -> None:
    engines.plan("enterprise")
    _switch(engines, _pack(engines, "nda"), True)
    item, _ = _read(engines, DOCUMENTS[("nda", "mutual")], "NDA-PACK-2")
    assert _suggestion(engines, item, as_user=engines.tenant.contributor).status_code == 200
    assert _suggestion(engines, item, as_user=engines.tenant.viewer).status_code == 403
    assert _suggestion(engines, uuid.uuid4()).status_code == 404
    other = engines.post("/workspaces", {"workspace_name": f"Packs D {uuid.uuid4().hex[:6]}"}, org=True)
    other_id = uuid.UUID(other.json()["id"])
    assert _suggestion(engines, item, workspace_id=other_id).status_code == 404, "a document of another workspace is not found"
