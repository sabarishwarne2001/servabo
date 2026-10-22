"""The builder can configure every action the server can run (Session J).

`ACTION_FORMS` in `frontend/src/components/automation/flow/ActionConfigForm.tsx` lists, per action type, the config keys
its form shows. An action the server registers but the console cannot configure, or a config key the form never shows,
would leave a rule that cannot be completed in the builder. The older check lived in a script that is now archived, so
this test is the guard.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.services.automation import actions as registry

pytestmark = pytest.mark.no_db

FORM = Path(__file__).resolve().parents[3] / "frontend" / "src" / "components" / "automation" / "flow" / "ActionConfigForm.tsx"
#: Config keys the legacy/alias actions carry that the form deliberately does not show.
NOT_SHOWN: dict[str, set[str]] = {}


def _forms() -> dict[str, set[str]]:
    text = FORM.read_text(encoding="utf-8")
    block = text[text.index("export const ACTION_FORMS"): text.index("};", text.index("export const ACTION_FORMS"))]
    return {
        match.group(1): set(re.findall(r'"([a-z_]+)"', match.group(2)))
        for match in re.finditer(r'"([a-z_.]+)":\s*\[([^\]]*)\]', block)
    }


def test_every_registered_action_has_a_form() -> None:
    forms = _forms()
    missing = sorted(set(registry.ACTIONS) - set(forms))
    assert not missing, f"actions the server runs but the builder has no form for: {missing}"


def test_every_config_key_of_every_action_is_shown_in_its_form() -> None:
    forms = _forms()
    gaps = {}
    for action_type, definition in registry.ACTIONS.items():
        properties = set((definition.schema().get("properties") or {}).keys())
        hidden = properties - forms.get(action_type, set()) - NOT_SHOWN.get(action_type, set())
        if hidden:
            gaps[action_type] = sorted(hidden)
    assert not gaps, f"config keys an action takes that its builder form never shows: {gaps}"


def test_no_form_names_an_action_or_key_the_server_does_not_have() -> None:
    forms = _forms()
    unknown = sorted(set(forms) - set(registry.ACTIONS))
    assert not unknown, f"the builder has a form for actions the server does not register: {unknown}"
    stale = {}
    for action_type, keys in forms.items():
        definition = registry.ACTIONS.get(action_type)
        if definition is None:
            continue
        extra = keys - set((definition.schema().get("properties") or {}).keys())
        if extra:
            stale[action_type] = sorted(extra)
    assert not stale, f"form keys the action's schema does not have: {stale}"
