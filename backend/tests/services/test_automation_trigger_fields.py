"""Session J — trigger fields: their choices equal their engines' vocabularies, money is in units, templates read amounts.

`triggers.py` imports no engine, so the fixed values of a trigger field are written there. This test fails when one of them
drifts from the vocabulary of the engine that emits the event, or when a money field points at a payload key nothing sends.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.automation import triggers as t
from app.services.automation.actions import base

pytestmark = pytest.mark.no_db


def _values(options: tuple[tuple[str, str], ...]) -> tuple[str, ...]:
    return tuple(v for v, _ in options)


def test_the_choices_equal_the_engines_vocabularies() -> None:
    from app.services.assertions import vocabulary as assertions
    from app.services.erp import vocabulary as erp
    from app.services.obligations import vocabulary as obligations
    from app.services.procurement_matching import vocabulary as procurement
    from app.services.process_intel import vocabulary as process
    from app.services.radar import vocabulary as radar
    from app.services.review import vocabulary as review

    assert _values(t.OPTIONS_SEVERITY) == radar.SEVERITIES
    assert _values(t.OPTIONS_ANOMALY_KIND) == radar.KINDS
    assert _values(t.OPTIONS_CASE_STATUS) == procurement.CASE_STATUSES
    assert _values(t.OPTIONS_ASSERTION_VERDICT) == assertions.VERDICTS
    assert _values(t.OPTIONS_REVIEW_SEVERITY) == review.SEVERITIES
    assert set(_values(t.OPTIONS_REVIEW_KIND)) == {getattr(review, n) for n in dir(review) if n.startswith("KIND_")}
    assert _values(t.OPTIONS_OBLIGATION_KIND) == obligations.KINDS
    assert _values(t.OPTIONS_POSTING_STATE) == erp.EXCEPTION_STATES
    assert _values(t.OPTIONS_POSTING_OBJECT) == erp.OBJECT_KINDS
    assert _values(t.OPTIONS_PROCESS_OBJECT) == process.OBJECT_TYPES

    from app.models import payment_risk
    from app.services.truthmesh import vocabulary as truthmesh

    assert dict(t.OPTIONS_CONFLICT_KIND) == dict(truthmesh.CONFLICT_LABELS)
    assert _values(t.OPTIONS_PAYMENT_RISK) == tuple(payment_risk.KINDS)
    assert t.OPTIONS_WEEKDAY[0][0] == "MONDAY" and len(t.OPTIONS_WEEKDAY) == 7


def test_every_option_has_a_plain_label_and_no_raw_code_is_shown() -> None:
    for spec in t.TRIGGERS:
        for field in spec.fields:
            for value, label in field.options:
                assert label and label[0].isupper(), (spec.key, field.key, value)
                assert "_" not in label, f"{spec.key}.{field.key}: {label!r} is a raw code"


def test_money_fields_name_their_stored_key_and_unit() -> None:
    for spec in t.TRIGGERS:
        for field in spec.fields:
            if field.type == "money":
                assert field.source_key, f"{spec.key}.{field.key} is money but names no payload key"
            if field.unit:
                assert field.unit == "micros" and field.type == "money"


def test_the_old_micros_fields_are_kept_for_stored_rules_and_hidden_from_new_ones() -> None:
    for key in ("procurement.completed", "procurement.approved", "procurement.disputed"):
        fields = {f.key: f for f in t.TRIGGERS_BY_KEY[key].fields}
        assert fields["variance_micros"].legacy and fields["variance_micros"].type == "number"
        assert fields["variance"].type == "money" and fields["variance"].source_key == "variance_micros"
    posting = {f.key: f for f in t.TRIGGERS_BY_KEY["posting.failed"].fields}
    assert posting["amount"].legacy and posting["amount_value"].currency_key == "currency"


def test_no_payload_key_is_listed_twice_for_one_field() -> None:
    for spec in t.TRIGGERS:
        keys = [f.key for f in spec.fields]
        assert len(keys) == len(set(keys)), spec.key


def test_a_template_reads_a_money_field_in_units_with_its_currency() -> None:
    event = SimpleNamespace(event_type="trigger.procurement.completed", payload={"variance_micros": 12_500_000})
    values = base.variables_for(SimpleNamespace(trigger_event=event, work_item=None, rule=None, db=None, execution=None))
    assert values["event.variance"] == "12.50"
    posting = SimpleNamespace(event_type="trigger.posting.failed", payload={"amount": "118000.00", "currency": "inr"})
    values = base.variables_for(SimpleNamespace(trigger_event=posting, work_item=None, rule=None, db=None, execution=None))
    assert values["event.amount_value"] == "INR 118,000.00" and values["event.amount"] == "118000.00"


def test_the_webhook_payload_keeps_its_old_keys_and_adds_no_duplicates() -> None:
    from app.services.automation.actions import webhook_send

    event = SimpleNamespace(id="e", event_type="trigger.procurement.completed",
                            payload={"variance_micros": 12_500_000, "status": "NEEDS_REVIEW", "exception_count": 2})
    state = SimpleNamespace(trigger_event=event, work_item=None, rule=SimpleNamespace(id="r", name="n"),
                            execution=SimpleNamespace(id="x", workspace_id="w"))
    body = webhook_send.build_payload(state, SimpleNamespace(include_fields=[]))
    assert body["event"]["variance_micros"] == 12_500_000 and "variance" not in body["event"]
