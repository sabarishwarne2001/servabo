"""Session J — how a rule reads a document's fields.

Three things a condition needs that the raw `extracted_entities` dictionary does not give it:

1. A CANONICAL ALIAS MAP. A model returns `supplier_gstin` or `gstin` where the prompt asked for `vendor_gstin`,
   and a condition on `vendor_gstin` used to read None, so it silently never matched. Every field in
   `app/core/finance_schema.py` is read under all the names the product already knows for it. The lists are not
   copied here: they are the batch canonical layer's (`batches/canonical.py`), the GST Credit engine's
   (`gst/fields.py`) and Helm's (`helm/ledger.py`, `helm/identity.py`, `helm/counterparties.py`), merged.
2. DERIVED FIELDS, computed when the rule runs and never stored: `document.age_days`, `document.has_irn` and
   `document.days_until_due`.
3. THE FIELD CATALOG the builder offers (the finance schema, with labels, types and examples), instead of the stale
   six-field list the catalog used to carry.

A human correction of a field is what a rule reads: corrections are written into `extracted_entities` by
`field_correction`, so every read here sees the corrected value (proven in test_automation_document_fields.py).
"""

from __future__ import annotations

import functools
from datetime import date, datetime
from typing import Any, Mapping, Optional

from app.core import finance_schema as fs

DERIVED_PREFIX = "document."
AGE_DAYS = "document.age_days"
HAS_IRN = "document.has_irn"
DAYS_UNTIL_DUE = "document.days_until_due"
TAGS = "document.tags"

#: Date fields in the order "the document's own date" is looked for.
OWN_DATE_ORDER = ("invoice_date", "po_date", "receipt_date", "agreement_date")


def normalize_key(key: str) -> str:
    from app.services.batches.canonical import normalize_key as _normalize

    return _normalize(key)


@functools.lru_cache(maxsize=1)
def alias_map() -> dict[str, tuple[str, ...]]:
    """canonical key -> every other name a model may use for it, in priority order."""
    from app.services.batches import canonical as cn
    from app.services.gst import fields as gf
    from app.services.helm import counterparties as hc
    from app.services.helm import identity as hi
    from app.services.helm import ledger as hl

    concept: dict[str, tuple[str, ...]] = {
        "invoice_number": gf.INVOICE_NUMBER_KEYS,
        "invoice_date": gf.INVOICE_DATE_KEYS,
        "due_date": hl.DUE_DATE_KEYS,
        "payment_terms": hl.TERMS_KEYS,
        "delivery_date": hl.DELIVERY_KEYS,
        "vendor_name": gf.SELLER_NAME_KEYS + hi.SELLER_NAME_KEYS,
        "vendor_gstin": gf.SELLER_GSTIN_KEYS,
        "buyer_gstin": gf.BUYER_GSTIN_KEYS,
        "customer_name": hi.BUYER_NAME_KEYS,
        "vendor_email": hc.EMAIL_KEYS,
        "subtotal": gf.TAXABLE_VALUE_KEYS,
        "cgst_amount": gf.CGST_KEYS,
        "sgst_amount": gf.SGST_KEYS,
        "igst_amount": gf.IGST_KEYS,
        "cess_amount": gf.CESS_KEYS,
        "tax_amount": gf.TAX_TOTAL_KEYS,
        "total_amount": gf.TOTAL_KEYS + hl.TOTAL_KEYS,
        "place_of_supply": gf.PLACE_OF_SUPPLY_KEYS,
        "reverse_charge": gf.REVERSE_CHARGE_KEYS,
        "irn": gf.IRN_KEYS,
        "note_type": gf.NOTE_TYPE_KEYS,
        "credit_note_number": gf.NOTE_NUMBER_KEYS,
        "original_invoice_number": gf.ORIGINAL_INVOICE_NUMBER_KEYS + hl.CREDIT_REFERENCE_KEYS,
        "original_invoice_date": gf.ORIGINAL_INVOICE_DATE_KEYS,
    }
    # The batch canonical layer keeps its aliases per field; its "date" is this prompt's invoice date.
    canonical_names = {"invoice_date": "date"}
    builtin: dict[str, tuple[str, ...]] = {}
    for schema in cn.BUILTIN.values():
        for spec in schema.fields:
            builtin.setdefault(spec.name, spec.aliases)

    keys = {field.key for field in fs.ALL_FIELDS}
    claimed: set[str] = set()
    out: dict[str, tuple[str, ...]] = {}
    for field in fs.ALL_FIELDS:
        names: list[str] = []
        for name in (*concept.get(field.key, ()), *builtin.get(canonical_names.get(field.key, field.key), ())):
            norm = normalize_key(name)
            if norm == field.key or norm in keys or norm in claimed or norm in names:
                continue
            names.append(norm)
        # Two fields never share an alias: the first (most specific) claims it.
        claimed.update(names)
        out[field.key] = tuple(names)
    # `date` is the old prompt's name for the invoice date; a rule written against it keeps reading it.
    if "date" not in out["invoice_date"]:
        out["invoice_date"] = (*out["invoice_date"], "date")
    return out


@functools.lru_cache(maxsize=1)
def _canonical_of() -> dict[str, str]:
    mapping: dict[str, str] = {}
    for key, names in alias_map().items():
        for name in names:
            mapping.setdefault(name, key)
    return mapping


def canonical_key(path: str) -> str:
    """`supplier_gstin` -> `vendor_gstin`; a name the schema does not know comes back normalised-as-given."""
    if "." in path:
        return path
    norm = normalize_key(path)
    if norm in fs.BY_KEY:
        return norm
    return _canonical_of().get(norm, path)


def _empty(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip()) or (isinstance(value, (list, dict, tuple, set)) and not value)


def read_by_alias(entities: Mapping[str, Any], path: str) -> Any:
    """The first non-empty value under the field's canonical name or any alias; None if there is none."""
    if not isinstance(entities, Mapping) or "." in path:
        return None
    canonical = canonical_key(path)
    if canonical not in fs.BY_KEY:
        return None
    folded: dict[str, Any] = {}
    for raw_key, value in entities.items():
        if isinstance(raw_key, str):
            folded.setdefault(normalize_key(raw_key), value)
    for name in (canonical, *alias_map().get(canonical, ())):
        value = folded.get(name)
        if not _empty(value):
            return value
    return None


# ------------------------------------------------------------------------------------------------ derived fields


def is_derived(path: str) -> bool:
    return path in (AGE_DAYS, HAS_IRN, DAYS_UNTIL_DUE, TAGS)


def _entities(work_item: Any) -> Mapping[str, Any]:
    value = getattr(work_item, "extracted_entities", None)
    return value if isinstance(value, Mapping) else {}


def _as_date(raw: Any, ctx: Any) -> Optional[date]:
    from app.services.automation import evaluator

    parsed = evaluator.parse_date(raw, ctx)
    return parsed.value


def own_date(work_item: Any, ctx: Any) -> Optional[date]:
    entities = _entities(work_item)
    for key in OWN_DATE_ORDER:
        raw = read_by_alias(entities, key)
        if not _empty(raw):
            found = _as_date(raw, ctx)
            if found is not None:
                return found
    return None


def derived_value(work_item: Any, path: str, ctx: Any) -> Any:
    """The value of `document.age_days`, `document.has_irn` or `document.days_until_due`; None when it cannot be known."""
    if work_item is None:
        return None
    entities = _entities(work_item)
    if path == TAGS:
        held = getattr(work_item, "tags", None)
        if isinstance(held, (list, tuple, set)):
            return sorted(str(t) for t in held)
        from sqlalchemy import select
        from sqlalchemy.orm import object_session

        session = object_session(work_item)
        if session is None:
            return []
        from app.models.ingestion import WorkItemTag

        return sorted(session.execute(select(WorkItemTag.tag).where(WorkItemTag.work_item_id == work_item.id)).scalars())
    if path == HAS_IRN:
        return not _empty(read_by_alias(entities, "irn"))
    if path == DAYS_UNTIL_DUE:
        due = read_by_alias(entities, "due_date")
        found = _as_date(due, ctx) if not _empty(due) else None
        return None if found is None else (found - ctx.today).days
    if path == AGE_DAYS:
        start = own_date(work_item, ctx)
        if start is None:
            created = getattr(work_item, "created_at", None)
            if isinstance(created, datetime):
                start = ctx.local_date(created)
        return None if start is None else (ctx.today - start).days
    return None


# ------------------------------------------------------------------------------------------ the builder's catalog

DERIVED_FIELDS: tuple[dict[str, Any], ...] = (
    {"key": AGE_DAYS, "label": "Document age (days)", "type": "number", "example": "42", "unit": None,
     "description": "Days since the date printed on the document (the invoice date, or the document's own date); "
                    "since it was uploaded when no date was read. Worked out when the rule runs, never stored."},
    {"key": HAS_IRN, "label": "Has an e-invoice IRN", "type": "boolean", "example": "true", "unit": None,
     "description": "Whether an e-invoice IRN was read on the document."},
    {"key": DAYS_UNTIL_DUE, "label": "Days until due", "type": "number", "example": "12", "unit": None,
     "description": "Days from today (in the workspace's time zone) to the due date; negative when it has passed."},
    {"key": TAGS, "label": "Tags", "type": "array", "example": "litigation, new-supplier", "unit": None,
     "description": "The tags on the document right now."},
)


def catalog_fields() -> list[dict[str, Any]]:
    """The finance schema as the builder's `document_fields`, grouped by the document type each belongs to."""
    out: list[dict[str, Any]] = []
    for field in fs.ALL_FIELDS:
        if field.key == "line_items":
            continue
        entry: dict[str, Any] = {
            "key": field.key,
            "label": field.label,
            "type": field.type,
            "example": field.example,
            "description": f"Read from {field.group.lower()}s.",
            "source": "document",
            "group": field.group,
            "aliases": list(alias_map().get(field.key, ())),
        }
        if field.options:
            entry["options"] = [{"value": value, "label": label} for value, label in field.options]
        out.append(entry)
    out.append({
        "key": fs.CLASSIFICATION_PATH, "label": "Document type", "type": "string", "example": "Invoice",
        "description": "What the classifier decided the document is.", "source": "document",
        "group": "Any document", "aliases": [],
        "options": [{"value": value, "label": label} for value, label in fs.CLASSIFICATIONS],
    })
    for derived in DERIVED_FIELDS:
        out.append({**derived, "source": "derived", "group": "Worked out when the rule runs", "aliases": []})
    return out


__all__ = [
    "AGE_DAYS",
    "DAYS_UNTIL_DUE",
    "HAS_IRN",
    "TAGS",
    "alias_map",
    "canonical_key",
    "catalog_fields",
    "derived_value",
    "is_derived",
    "normalize_key",
    "own_date",
    "read_by_alias",
]
