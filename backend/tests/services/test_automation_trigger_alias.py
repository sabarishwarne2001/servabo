"""Final session 1 (1D, F-571): `{{trigger.local_date}}` reads the trigger's field exactly as `{{event.local_date}}` does.

A schedule's message used to accept only `{{event.local_date}}`; the natural `{{trigger.local_date}}` was refused with
"Unknown template variable(s)". `{{trigger.label}}` (the trigger's name) is a variable of its own and must not be hijacked.
"""

from __future__ import annotations

import pytest

from app.services.automation.actions import base

pytestmark = pytest.mark.no_db

EVENT_KEYS = {"event.local_date", "event.weekday"}


def test_trigger_dot_field_is_accepted_when_the_trigger_has_that_field():
    assert base.invalid_variables("Today is {{trigger.local_date}}", event_keys=EVENT_KEYS) == []
    assert base.invalid_variables("{{event.local_date}} {{trigger.weekday}}", event_keys=EVENT_KEYS) == []


def test_a_trigger_field_the_trigger_does_not_have_is_still_refused_by_name():
    assert base.invalid_variables("{{trigger.nonsense}}", event_keys=EVENT_KEYS) == ["trigger.nonsense"]


def test_trigger_label_is_still_the_triggers_name():
    assert base.invalid_variables("{{trigger.label}}", event_keys=EVENT_KEYS) == []
    values = base.PlainValues({"trigger.label": "Every Monday", "event.local_date": "2026-10-26"}, {})
    assert base.render("{{trigger.label}} on {{trigger.local_date}}", values) == "Every Monday on 2026-10-26"


def test_the_alias_renders_the_same_text_as_the_event_name():
    values = {"event.local_date": "2026-10-26"}
    assert base.render("{{trigger.local_date}}", values) == base.render("{{event.local_date}}", values) == "2026-10-26"
