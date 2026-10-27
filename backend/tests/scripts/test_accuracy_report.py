"""`scripts/accuracy_report.py` measures extraction accuracy against a truth sheet (Final session 2A, Phase 5).

An invented truth sheet for four documents and what the stand-in "extracted": one perfect, one with the total wrong and
sent to review, one with the GSTIN wrong and passed through, one missing a date. The numbers, the catch rate, the misses
and the Markdown (field names and counts only, never a value) are checked; then the same through the database.
"""

from __future__ import annotations

import csv
from decimal import Decimal
from pathlib import Path

import pytest

from scripts import accuracy_report as ar

TRUTH = [
    {"document": "A.pdf", "invoice_number": "INV-1", "invoice_date": "05/09/2026", "vendor_gstin": "27AAAAA0000A1Z5",
     "taxable_value": "1,00,000.00", "total": "₹1,18,000", "hsn": "8708; 4819"},
    {"document": "B.pdf", "invoice_number": "INV-2", "invoice_date": "2026-09-06", "vendor_gstin": "27AAAAA0000A1Z5",
     "taxable_value": "500", "total": "590.00"},
    {"document": "C.pdf", "invoice_number": "INV-3", "invoice_date": "07/09/2026", "vendor_gstin": "27AAAAA0000A1Z5",
     "taxable_value": "200", "total": "236"},
    {"document": "D.pdf", "invoice_number": "INV-4", "invoice_date": "08/09/2026", "vendor_gstin": "29BBBBB1111B1Z6",
     "taxable_value": "300", "total": "354"},
    {"document": "E.pdf", "invoice_number": "INV-5"},
]
EXTRACTED = {
    "A.pdf": ar.Extracted({"invoice_number": "inv-1", "invoice_date": "2026-09-05", "vendor_gstin": "27aaaaa 0000a1z5",
                           "subtotal": "100000", "total_amount": "118000.00",
                           "line_items": [{"hsn_sac": "4819"}, {"hsn_sac": "8708"}]}),
    "B.pdf": ar.Extracted({"invoice_number": "INV-2", "invoice_date": "2026-09-06", "vendor_gstin": "27AAAAA0000A1Z5",
                           "subtotal": "500", "total_amount": "950.00"}, review_fields=frozenset({"total_amount"})),
    "C.pdf": ar.Extracted({"invoice_number": "INV-3", "invoice_date": "2026-09-07", "vendor_gstin": "27AAAAA0000A1Z6",
                           "subtotal": "200", "total_amount": "236"}),
    "D.pdf": ar.Extracted({"invoice_number": "INV-4", "vendor_gstin": "29BBBBB1111B1Z6", "subtotal": "300",
                           "total_amount": "354"}, whole_document_reviewed=True),
}


def test_the_numbers() -> None:
    result = ar.compare(TRUTH, EXTRACTED)
    assert result.documents == 4 and result.not_found == ["E.pdf"]
    assert (result.fields["total"].checked, result.fields["total"].right) == (4, 3)
    assert (result.fields["vendor_gstin"].checked, result.fields["vendor_gstin"].right) == (4, 3)
    assert (result.fields["invoice_date"].checked, result.fields["invoice_date"].right) == (4, 3)
    assert result.fields["hsn"].accuracy == 1.0
    assert result.documents_all_key_right == 1
    assert (result.wrong_fields, result.caught) == (3, 2), "B's total and D's date were sent to review; C's GSTIN was not"
    assert {(m.document, m.field, m.sent_to_review, m.missing) for m in result.misses} == {
        ("B.pdf", "total", True, False), ("C.pdf", "vendor_gstin", False, False), ("D.pdf", "invoice_date", True, True)}


def test_normalising() -> None:
    assert ar.normalise("amount", "₹1,18,000") == ar.normalise("amount", "118000.00") == "118000.00"
    assert ar.normalise("amount", Decimal("0.5")) == "0.50"
    assert ar.normalise("date", "05/09/2026") == "2026-09-05", "the Indian order: day first"
    assert ar.normalise("gstin", " 27aaaaa0000a1z5 ") == "27AAAAA0000A1Z5"
    assert ar.normalise("text", "  Maharashtra ") == "maharashtra"


def test_the_report_names_fields_and_counts_and_no_value() -> None:
    report = ar.render_markdown(ar.compare(TRUTH, EXTRACTED), title="Pilot accuracy")
    assert "# Pilot accuracy" in report and "| total | 4 | 3 | 75.0% |" in report
    assert "Wrong fields sent to a person for review** (not passed through): 2 of 3 (66.7%)" in report
    assert "| C.pdf | vendor_gstin | passed through |" in report
    for value in ("27AAAAA0000A1Z6", "950", "INV-3", "1,18,000"):
        assert value not in report, f"the report shows a document value: {value}"


def test_the_template_has_every_column(tmp_path: Path) -> None:
    template = Path(ar.__file__).with_name("accuracy_truth_template.csv")
    with template.open(encoding="utf-8") as handle:
        header = next(csv.reader(handle))
    assert tuple(header) == ar.TEMPLATE_COLUMNS
    bad = tmp_path / "bad.csv"
    bad.write_text("document,totl\nA.pdf,1\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="Unknown columns"):
        ar.read_truth(bad)


def test_through_the_database(db_session, tenant, work_item_factory) -> None:
    from app.models.verification import DocumentVerification, VerificationStatus

    good = work_item_factory(original_filename="A.pdf", extracted_entities=dict(EXTRACTED["A.pdf"].entities))
    held = work_item_factory(original_filename="B.pdf", extracted_entities=dict(EXTRACTED["B.pdf"].entities))
    db_session.add(DocumentVerification(work_item_id=held.id, workspace_id=tenant.workspace.id,
                                        organization_id=tenant.organization.id, status=VerificationStatus.DISAGREED,
                                        agent_count=2, agreement_score=Decimal("0.5"), confidence=Decimal("0.5"),
                                        details={"disagreed_fields": ["total_amount"]}))
    db_session.commit()
    found = ar.load_extracted(db_session, workspace_id=str(tenant.workspace.id), names=["A.pdf", "B.pdf", "Z.pdf"])
    assert set(found) == {"A.pdf", "B.pdf"} and found["B.pdf"].review_fields == {"total_amount"}
    result = ar.compare(TRUTH[:2], found)
    assert result.documents_all_key_right == 1 and result.caught == 1
    assert good.id
