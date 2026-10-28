"""TRINETRA versions evidence by what it is, not by when its row was touched (Final 2T, Phase 1.2).

Credits, statements, supporting evidence and the comparison baselines stored `work_items.updated_at` stamps (or a hash
of them). This converts each to the content fingerprint of `app/services/trinetra/versions.py`:

- a stamp that was still current (its document unchanged since) becomes the document's fingerprint now;
- a stamp that was already stale stays stale (`v2:stale-before-migration`): a harmless touch cannot be told from a real
  change after the fact, so a person reconfirms, as they would have had to before.

The hashing below is a frozen copy of `versions.py` at the time of this migration (a migration does not import code that
may change later). Downgrade restores updated_at stamps for fingerprints that currently match and leaves the rest stale.
Static SQL plus Python over rows; no schema change.
"""

import hashlib
import json

from alembic import op
import sqlalchemy as sa

revision = "tr2t1_evidence_fingerprints"
down_revision = "s2a4_recoveries"
branch_labels = None
depends_on = None

SCHEME = "v2"
STALE = "v2:stale-before-migration"
LEGACY_STALE = "legacy-stale-after-downgrade"
FIELDS = tuple(sorted({
    "vendor_name", "supplier_name", "seller_name", "vendor", "supplier", "seller", "from", "billed_by", "company_name",
    "vendor_tax_id", "supplier_gstin", "seller_gstin", "vendor_gstin", "gstin", "gst_number", "vat_number", "vat_id",
    "tax_id", "ein", "tin", "supplier_vat",
    "bill_to", "billed_to", "buyer", "buyer_name", "customer", "customer_name", "sold_to", "invoice_to", "recipient",
    "client", "client_name",
    "buyer_gstin", "customer_gstin", "recipient_gstin", "bill_to_gstin", "buyer_tax_id", "customer_tax_id", "buyer_vat",
    "customer_vat",
    "vendor_pan", "seller_pan", "buyer_pan", "deductor_tan", "tds_amount", "tds_section", "tds_rate",
    "invoice_number", "invoice_date", "due_date", "total_amount", "subtotal", "tax_amount", "currency",
    "certificate_number", "challan_number", "amount", "date", "financial_year", "assessment_year", "tax_year",
}))


def _hash(*parts):
    return SCHEME + ":" + hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()[:48]


def _facts(row):
    file_part = _hash("sha256", row.checksum_sha256) if row.checksum_sha256 else _hash(
        "file", row.stored_filename, row.file_size, row.file_type)
    values = row.extracted_entities if isinstance(row.extracted_entities, dict) else {}
    fields = _hash("fields", {k: values.get(k) for k in FIELDS if values.get(k) is not None})
    role = _hash("role", None) if row.role is None else _hash(
        "role", row.role, row.total_micros, row.currency, row.document_date.isoformat() if row.document_date else None)
    return {
        "invoice": _hash("invoice", file_part, fields, role),
        "evidence": _hash("evidence", file_part, fields, role),
        "statement": _hash("statement", file_part),
    }


def _load(conn, ids):
    if not ids:
        return {}
    rows = conn.execute(sa.text(
        "SELECT w.id, w.stored_filename, w.file_size, w.file_type, w.extracted_entities, w.updated_at, "
        "u.checksum_sha256, r.role, r.total_micros, r.currency, r.document_date, r.updated_at AS role_updated_at "
        "FROM work_items w LEFT JOIN uploaded_files u ON u.id = w.uploaded_file_id "
        "LEFT JOIN document_roles r ON r.work_item_id = w.id WHERE w.id::text = ANY(:ids)"), {"ids": list(ids)}).all()
    return {str(r.id): r for r in rows}


def _legacy_invoice(row):
    parts = [row.updated_at.isoformat(), row.role_updated_at.isoformat() if row.role_updated_at else None]
    return hashlib.sha256(json.dumps(parts).encode()).hexdigest()


def convert(conn):
    """Legacy stamps to fingerprints. Returns the number of rows changed (for the test)."""
    changed = 0
    credits = conn.execute(sa.text(
        "SELECT id, work_item_id, source_version, review FROM trinetra_credits")).all()
    statements = conn.execute(sa.text(
        "SELECT id, source_work_item_id, source_version, comparison FROM trinetra_statements")).all()
    ids = {str(c.work_item_id) for c in credits} | {str(s.source_work_item_id) for s in statements}
    for c in credits:
        for e in (c.review or {}).get("evidence", []):
            ids.add(e["work_item_id"])
    docs = _load(conn, ids)
    mapping = {}
    for c in credits:
        if str(c.source_version).startswith(SCHEME + ":"):
            continue
        doc = docs.get(str(c.work_item_id))
        new = _facts(doc)["invoice"] if doc is not None and _legacy_invoice(doc) == c.source_version else STALE
        mapping[str(c.id)] = (c.source_version, new)
        review = dict(c.review or {})
        if review.get("invoice_version") == c.source_version:
            review["invoice_version"] = new
        evidence = []
        for e in review.get("evidence", []):
            item = docs.get(e["work_item_id"])
            current = item is not None and item.updated_at.isoformat() == e["source_version"]
            evidence.append({**e, "source_version": _facts(item)["evidence"] if current else STALE})
        if "evidence" in review:
            review["evidence"] = evidence
        conn.execute(sa.text("UPDATE trinetra_credits SET source_version = :v, review = CAST(:r AS jsonb) WHERE id = :i"),
                     {"v": new, "r": json.dumps(review), "i": c.id})
        changed += 1
    for s in statements:
        comparison = dict(s.comparison or {})
        touched = False
        for case_id, case in (comparison.get("cases") or {}).items():
            if case_id in mapping and case.get("source_version") == mapping[case_id][0]:
                case["source_version"] = mapping[case_id][1]
                touched = True
        if str(s.source_version).startswith(SCHEME + ":"):
            if touched:
                conn.execute(sa.text("UPDATE trinetra_statements SET comparison = CAST(:c AS jsonb) WHERE id = :i"),
                             {"c": json.dumps(comparison), "i": s.id})
            continue
        doc = docs.get(str(s.source_work_item_id))
        new = _facts(doc)["statement"] if doc is not None and doc.updated_at.isoformat() == s.source_version else STALE
        conn.execute(sa.text(
            "UPDATE trinetra_statements SET source_version = :v, comparison = CAST(:c AS jsonb) WHERE id = :i"),
            {"v": new, "c": json.dumps(comparison), "i": s.id})
        changed += 1
    return changed


def revert(conn):
    """Fingerprints back to updated_at stamps where they still match; everything else stays stale."""
    credits = conn.execute(sa.text("SELECT id, work_item_id, source_version, review FROM trinetra_credits")).all()
    statements = conn.execute(sa.text(
        "SELECT id, source_work_item_id, source_version FROM trinetra_statements")).all()
    ids = {str(c.work_item_id) for c in credits} | {str(s.source_work_item_id) for s in statements}
    for c in credits:
        for e in (c.review or {}).get("evidence", []):
            ids.add(e["work_item_id"])
    docs = _load(conn, ids)
    for c in credits:
        doc = docs.get(str(c.work_item_id))
        old = _legacy_invoice(doc) if doc is not None and c.source_version == _facts(doc)["invoice"] else LEGACY_STALE
        review = dict(c.review or {})
        if review.get("invoice_version") == c.source_version:
            review["invoice_version"] = old
        if "evidence" in review:
            review["evidence"] = [
                {**e, "source_version": (docs[e["work_item_id"]].updated_at.isoformat()
                                         if e["work_item_id"] in docs and e["source_version"] == _facts(docs[e["work_item_id"]])["evidence"]
                                         else LEGACY_STALE)}
                for e in review["evidence"]]
        conn.execute(sa.text("UPDATE trinetra_credits SET source_version = :v, review = CAST(:r AS jsonb) WHERE id = :i"),
                     {"v": old, "r": json.dumps(review), "i": c.id})
    for s in statements:
        doc = docs.get(str(s.source_work_item_id))
        old = doc.updated_at.isoformat() if doc is not None and s.source_version == _facts(doc)["statement"] else LEGACY_STALE
        conn.execute(sa.text("UPDATE trinetra_statements SET source_version = :v WHERE id = :i"), {"v": old, "i": s.id})


def upgrade():
    convert(op.get_bind())


def downgrade():
    revert(op.get_bind())
