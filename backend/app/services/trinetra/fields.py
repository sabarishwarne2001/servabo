"""Read printed extraction fields as unapproved hints, never inferred tax rules."""

import re
from app.services.trinetra.domain import money

AMOUNT_KEYS = ("tds_amount",)
TAN_KEYS = ("deductor_tan",)
SECTION_KEYS = ("tds_section",)


def printed(entities):
    values = entities if isinstance(entities, dict) else {}
    raw = next((values[k] for k in AMOUNT_KEYS if values.get(k) is not None), None)
    amount = None
    if isinstance(raw, (str, int)) and not isinstance(raw, bool):
        try:
            amount = money(str(raw))
        except ValueError:
            pass
    tan = next((values[k] for k in TAN_KEYS if isinstance(values.get(k), str)), "")
    section = next(
        (values[k] for k in SECTION_KEYS if isinstance(values.get(k), str)), ""
    )
    return {
        "amount_micros": amount,
        "deductor_tan_masked": (
            "******" + tan[-4:] if re.fullmatch(r"[A-Z]{4}[0-9]{5}[A-Z]", tan) else None
        ),
        "section_label": section[:100] or None,
        "note": "Unapproved fields read from the invoice. Check the source; a printed section is not a recommendation under current law.",
    }


def hints(entities):
    """The printed hints, raw, for the suggestion scan only (Final 2T, Phase 4): the amount in micros, the validated
    deductor TAN and the section text exactly as printed. These never become a case without a person accepting them."""
    values = entities if isinstance(entities, dict) else {}
    amount = None
    raw = next((values[k] for k in AMOUNT_KEYS if values.get(k) is not None), None)
    if isinstance(raw, (str, int)) and not isinstance(raw, bool):
        try:
            amount = money(str(raw))
        except ValueError:
            pass
    tan = next((values[k] for k in TAN_KEYS if isinstance(values.get(k), str)), "")
    tan = re.sub(r"[\s\-]", "", tan).upper()
    section = next((values[k] for k in SECTION_KEYS if isinstance(values.get(k), str)), "")
    return {
        "amount_micros": amount,
        "tan": tan if re.fullmatch(r"[A-Z]{4}[0-9]{5}[A-Z]", tan) else None,
        "section_text": (section.strip()[:100] or None),
    }


def has_hint_clause(column):
    """A SQL condition for documents that print a TDS amount (the scan's cheap first filter)."""
    from sqlalchemy import cast, or_
    from sqlalchemy.dialects.postgresql import JSONB

    return or_(*[cast(column, JSONB).has_key(k) for k in AMOUNT_KEYS])
