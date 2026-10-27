#!/usr/bin/env python3
"""How accurate Servabo is on real documents, measured (Final session 2A, Phase 5).

    python scripts/accuracy_report.py --workspace <workspace id> --truth truth.csv --out accuracy.md
    python scripts/accuracy_report.py --workspace <id> --truth truth.csv --tag pilot-oct --json   # machine-readable

The owner (or the customer) fills a **truth sheet**, one row per document, with what each document really says; the
template is `scripts/accuracy_truth_template.csv`. The `document` column is the document's file name as uploaded (or its id).
Leave a cell empty when the document does not carry that field. The script compares the truth with what Servabo extracted
and writes a report fit to show a customer: it names fields and counts, and never prints a document's content.

* **Field accuracy:** per field, the share of documents where the extracted value equals the truth after normalising:
  amounts to the paisa ("₹1,18,000.00" = "118000"), dates in any common form (05/09/2026 is 5 September, the Indian
  order), GSTINs without spaces and in capitals, text without case or extra spaces. HSN codes on lines are optional.
* **Document accuracy:** the share of documents whose key fields are all right.
* **Review catch rate:** of the wrong fields, how many Servabo sent to a person instead of passing them through (a
  verification that disagreed on that field, or held the whole document for review).
* **Misses:** every wrong field, with its document's name, so it can be looked at. Values are not printed.

Run it after processing and before anyone corrects the documents in review: it reads the current extraction.
Exit 0 always; the numbers are the result. Final session 2B runs it on the owner's real invoices.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

#: Truth-sheet column -> (the extraction field it is compared with, kind). Key fields decide "all key fields right".
FIELDS: dict[str, tuple[str, str]] = {
    "invoice_number": ("invoice_number", "text"),
    "invoice_date": ("invoice_date", "date"),
    "vendor_gstin": ("vendor_gstin", "gstin"),
    "buyer_gstin": ("buyer_gstin", "gstin"),
    "taxable_value": ("subtotal", "amount"),
    "cgst": ("cgst_amount", "amount"),
    "sgst": ("sgst_amount", "amount"),
    "igst": ("igst_amount", "amount"),
    "total": ("total_amount", "amount"),
    "place_of_supply": ("place_of_supply", "text"),
    "due_date": ("due_date", "date"),
    "hsn": ("line_items", "hsn"),
}
KEY_FIELDS = ("invoice_number", "invoice_date", "vendor_gstin", "taxable_value", "total")
TEMPLATE_COLUMNS = ("document", *FIELDS)


# ------------------------------------------------------------------------------------------------ normalising

def _amount(value: Any) -> Optional[str]:
    text = re.sub(r"[^\d.\-]", "", str(value).replace("₹", "").replace("INR", "").replace("Rs", ""))
    if not text or text in {"-", "."}:
        return None
    try:
        return str(Decimal(text).quantize(Decimal("0.01")))
    except InvalidOperation:
        return None


def _date(value: Any) -> Optional[str]:
    text = str(value).strip()
    if not text:
        return None
    if isinstance(value, (date, datetime)):
        return value.strftime("%Y-%m-%d")
    for pattern in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d %b %Y", "%d %B %Y", "%d-%b-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, pattern).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return text.lower()


def _hsn(value: Any) -> Optional[str]:
    """A set of HSN/SAC codes: from the truth ("8708; 4819") or from extracted line items."""
    codes: set[str] = set()
    if isinstance(value, list):
        for line in value:
            if isinstance(line, Mapping) and line.get("hsn_sac"):
                codes.add(re.sub(r"\s", "", str(line["hsn_sac"])))
    else:
        codes = {re.sub(r"\s", "", c) for c in re.split(r"[;,|]", str(value)) if c.strip()}
    return ";".join(sorted(codes)) or None


def normalise(kind: str, value: Any) -> Optional[str]:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if kind == "amount":
        return _amount(value)
    if kind == "date":
        return _date(value)
    if kind == "gstin":
        return re.sub(r"\s", "", str(value)).upper() or None
    if kind == "hsn":
        return _hsn(value)
    return re.sub(r"\s+", " ", str(value)).strip().lower() or None


# ------------------------------------------------------------------------------------------------ comparing

@dataclass
class FieldScore:
    field: str
    checked: int = 0
    right: int = 0

    @property
    def accuracy(self) -> Optional[float]:
        return self.right / self.checked if self.checked else None


@dataclass
class Miss:
    document: str
    field: str
    sent_to_review: bool
    missing: bool  # Servabo extracted nothing for a field the document carries


@dataclass
class Result:
    documents: int
    not_found: list[str]
    fields: dict[str, FieldScore]
    documents_all_key_right: int
    wrong_fields: int
    caught: int
    misses: list[Miss] = field(default_factory=list)

    @property
    def catch_rate(self) -> Optional[float]:
        return self.caught / self.wrong_fields if self.wrong_fields else None

    def as_json(self) -> dict[str, Any]:
        return {"documents": self.documents, "not_found": self.not_found,
                "fields": {k: {"checked": v.checked, "right": v.right, "accuracy": v.accuracy} for k, v in self.fields.items()},
                "documents_all_key_fields_right": self.documents_all_key_right, "wrong_fields": self.wrong_fields,
                "caught_by_review": self.caught, "catch_rate": self.catch_rate, "misses": [asdict(m) for m in self.misses]}


@dataclass(frozen=True)
class Extracted:
    """What Servabo holds for one document: its fields, and which of them it sent to a person."""
    entities: Mapping[str, Any]
    review_fields: frozenset[str] = frozenset()
    whole_document_reviewed: bool = False


def compare(truth: Iterable[Mapping[str, str]], extracted: Mapping[str, Extracted]) -> Result:
    """`truth`: truth-sheet rows. `extracted`: by the row's `document` value."""
    scores = {name: FieldScore(name) for name in FIELDS}
    rows = [r for r in truth if (r.get("document") or "").strip()]
    not_found: list[str] = []
    all_key_right = wrong = caught = 0
    misses: list[Miss] = []
    for row in rows:
        name = row["document"].strip()
        found = extracted.get(name)
        if found is None:
            not_found.append(name)
            continue
        key_right = True
        for column, (entity, kind) in FIELDS.items():
            expected = normalise(kind, row.get(column))
            if expected is None:
                continue  # the document does not carry this field
            got = normalise(kind, found.entities.get(entity))
            scores[column].checked += 1
            if got == expected:
                scores[column].right += 1
                continue
            if column in KEY_FIELDS:
                key_right = False
            reviewed = found.whole_document_reviewed or entity in found.review_fields
            wrong += 1
            caught += int(reviewed)
            misses.append(Miss(document=name, field=column, sent_to_review=reviewed, missing=got is None))
        all_key_right += int(key_right)
    return Result(documents=len(rows) - len(not_found), not_found=not_found, fields=scores,
                  documents_all_key_right=all_key_right, wrong_fields=wrong, caught=caught, misses=misses)


def _pct(value: Optional[float]) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


def render_markdown(result: Result, *, title: str = "Extraction accuracy", note: str = "") -> str:
    """A report fit to show a customer: field names and counts only, never a document's content."""
    lines = [f"# {title}", ""]
    if note:
        lines += [note, ""]
    lines += [f"Documents compared: **{result.documents}**"
              + (f" ({len(result.not_found)} in the truth sheet were not found in the workspace)" if result.not_found else ""),
              "",
              f"- **All key fields right** ({', '.join(KEY_FIELDS)}): {result.documents_all_key_right} of {result.documents} "
              f"documents ({_pct(result.documents_all_key_right / result.documents if result.documents else None)})",
              f"- **Wrong fields sent to a person for review** (not passed through): {result.caught} of {result.wrong_fields} "
              f"({_pct(result.catch_rate)})",
              "", "## Accuracy by field", "", "| Field | Documents checked | Right | Accuracy |", "|---|---|---|---|"]
    for name, score in result.fields.items():
        if score.checked:
            lines.append(f"| {name} | {score.checked} | {score.right} | {_pct(score.accuracy)} |")
    lines += ["", "Amounts are compared to the paisa, dates as dates, GSTINs without spaces and case, text without case.",
              "", "## Every miss", ""]
    if not result.misses:
        lines.append("None.")
    else:
        lines += ["| Document | Field | What happened |", "|---|---|---|"]
        for miss in result.misses:
            what = ("sent to review" if miss.sent_to_review else "passed through") + (", nothing extracted" if miss.missing else "")
            lines.append(f"| {miss.document} | {miss.field} | {what} |")
    if result.not_found:
        lines += ["", "## Not found in the workspace", ""] + [f"- {name}" for name in result.not_found]
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------------------------------------------ the database

def load_extracted(db: Any, *, workspace_id: str, names: Iterable[str], tag: Optional[str] = None) -> dict[str, Extracted]:
    """The workspace's documents by file name (and by id), with what verification sent to review."""
    import uuid

    from sqlalchemy import select

    from app.models.verification import DocumentVerification, VerificationStatus
    from app.models.work_item import WorkItem

    from app.models.ingestion import WorkItemTag

    wanted = {n.strip() for n in names if n and n.strip()}
    query = select(WorkItem).where(WorkItem.workspace_id == uuid.UUID(str(workspace_id)))
    if tag:
        query = query.where(WorkItem.id.in_(select(WorkItemTag.work_item_id).where(WorkItemTag.tag == tag)))
    out: dict[str, Extracted] = {}
    for item in db.execute(query).scalars():
        keys = {item.original_filename or "", str(item.id)} & wanted
        if not keys:
            continue
        verification = db.execute(select(DocumentVerification).where(DocumentVerification.work_item_id == item.id)
                                  .order_by(DocumentVerification.created_at.desc()).limit(1)).scalar_one_or_none()
        fields: set[str] = set()
        whole = False
        if verification is not None and verification.status == VerificationStatus.DISAGREED:
            details = verification.details or {}
            fields = set(details.get("disagreed_fields") or []) | set(details.get("unresolved_conflicts") or [])
            whole = any((details.get(k) or {}).get("review_all_fields") for k in ("calibration", "extraction_memory", "injection"))
        found = Extracted(entities=dict(item.extracted_entities or {}), review_fields=frozenset(fields),
                          whole_document_reviewed=whole)
        for key in keys:
            out[key] = found
    return out


def read_truth(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    unknown = set(rows[0].keys()) - set(TEMPLATE_COLUMNS) if rows else set()
    if unknown:
        raise SystemExit(f"Unknown columns in the truth sheet: {', '.join(sorted(unknown))}. "
                         f"The columns are: {', '.join(TEMPLATE_COLUMNS)}.")
    return rows


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--workspace", required=True, help="the workspace id the documents were processed in")
    parser.add_argument("--truth", required=True, type=Path, help="the filled truth sheet (CSV)")
    parser.add_argument("--tag", help="only documents with this tag")
    parser.add_argument("--out", type=Path, help="write the Markdown report here (default: print it)")
    parser.add_argument("--json", action="store_true", help="print the numbers as JSON instead")
    parser.add_argument("--title", default="Extraction accuracy")
    args = parser.parse_args(argv)

    from app.db.session import SessionLocal

    truth = read_truth(args.truth)
    with SessionLocal() as db:
        extracted = load_extracted(db, workspace_id=args.workspace, names=[r.get("document", "") for r in truth], tag=args.tag)
    result = compare(truth, extracted)
    if args.json:
        print(json.dumps(result.as_json(), indent=2))
        return 0
    report = render_markdown(result, title=args.title)
    if args.out:
        args.out.write_text(report, encoding="utf-8")
        print(f"wrote {args.out}")
    else:
        print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
