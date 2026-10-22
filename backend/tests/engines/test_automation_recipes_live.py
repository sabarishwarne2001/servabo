"""Session J, Phase 5 — the recipe library. Every recipe saves, on a tenant that holds what it needs."""

from __future__ import annotations

from typing import Any

import pytest

from app.services.automation import recipes
from tests.engines.conftest import Engines

SLACK = "https://slack-in.acme.example.com/services/T000/B000/SECRETTOKEN123"


@pytest.fixture(autouse=True)
def chat_hosts(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "CHAT_WEBHOOK_EXTRA_HOSTS", "slack-in.acme.example.com")


def _answers(engines: Engines) -> dict[str, Any]:
    chat = engines.post("/webhooks/endpoints", {"kind": "SLACK", "url": SLACK}, org=True)
    assert chat.status_code == 201, chat.text
    return {"chat_endpoint": chat.json()["endpoint"]["id"], "member_email": engines.tenant.org_admin.user.email,
            "email": "ap@acme.example.com"}


def test_the_library_has_a_dozen_or_more_recipes_in_plain_words(engines: Engines) -> None:
    body = engines.get("/automation/recipes").json()
    assert len(body["recipes"]) >= 12
    ids = [r["id"] for r in body["recipes"]]
    assert len(ids) == len(set(ids)) and set(r["category"] for r in body["recipes"]) <= set(body["categories"])
    for recipe in body["recipes"]:
        assert recipe["title"] and recipe["summary"] and recipe["trigger_labels"]
        assert "{{" not in recipe["title"] and "micros" not in recipe["summary"].lower()
    assert engines.get("/automation/recipes", as_user=engines.tenant.viewer).status_code in (200, 403)


def test_every_recipe_saves_with_its_fill_ins_answered(engines: Engines) -> None:
    answers = _answers(engines)
    listed = engines.get("/automation/recipes").json()["recipes"]
    assert all(r["available"] for r in listed), [r["id"] for r in listed if not r["available"]]
    saved_names = set()
    for recipe in listed:
        filled = {fill["path"]: answers[fill["kind"]] for fill in recipe["fill_ins"]}
        rule = recipes.fill(recipe["id"], filled)
        response = engines.post("/automation/rules", rule)
        assert response.status_code == 201, f"{recipe['id']}: {response.text}"
        saved_names.add(response.json()["name"])
    assert len(saved_names) == len(listed), "every recipe has its own rule name"


def test_a_recipe_with_a_fill_in_left_blank_is_refused_in_words_not_saved_half_done(engines: Engines) -> None:
    for recipe in engines.get("/automation/recipes").json()["recipes"]:
        if recipe["fill_ins"]:
            refused = engines.post("/automation/rules", recipes.fill(recipe["id"], {}))
            assert refused.status_code == 422, recipe["id"]


def test_recipes_follow_the_plan_the_triggers_and_actions_need(engines: Engines) -> None:
    engines.plan("developer")
    listed = {r["id"]: r for r in engines.get("/automation/recipes").json()["recipes"]}
    assert listed["hold-big-invoices"]["available"] is True
    gst = listed["gst-chase-supplier"]
    assert gst["available"] is False and "GST Credit" in gst["unavailable_reason"]


def test_no_recipe_can_move_money() -> None:
    forbidden = {"payment.approve", "payment.schedule", "helm.approve", "erp.post"}
    for recipe in recipes.RECIPES:
        for step in [*recipe["rule"]["actions"], *recipe["rule"]["else_actions"]]:
            assert step["action_type"] not in forbidden
