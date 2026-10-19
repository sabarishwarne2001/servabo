"""The extraction prompt asks for every field the rest of the product reads (Session F, Phase 1).

Helm's ledger, three-way matching, duplicate checks, the bank-account check, ERP posting and GST Credit
all read fields of an invoice, purchase order or receipt: invoice number, due date, GSTINs, the bank
account and more. Those readers accept several spellings of each field, but the model only writes the
fields the production prompt (`llm_service.ENTITY_EXTRACTION_PROMPT_TEMPLATE`) asks for. Until Session F
the prompt asked for six, while the browser suite's model stand-in answered with the rest, so every test
passed and a real model would have left Helm half-blind.

Two guards:

1. Every concept a reader looks for is asked for under a name that reader accepts. The accepted names are
   taken from the readers' own key lists, not copied here, so a new reader alias or a renamed prompt key
   cannot drift apart silently.
2. Every key the browser suite's stand-in (`frontend/e2e/support/llm-mock.mjs`) returns for a document
   type is a key the production prompt asks for. The stand-in may not know more than the prompt says.
"""

from __future__ import annotations

import json
import re
import shutil
import socket
import subprocess
import time
import urllib.request
from pathlib import Path
from typing import Iterable

import pytest

from app.services import llm_service
from app.services.batches import canonical
from app.services.corroboration import fields as corroboration_fields
from app.services.erp import sources as erp_sources
from app.services.gst import fields as gst_fields
from app.services.helm import counterparties, identity, ledger, msme
from app.services.obligations import extract as obligations_extract
from app.services.procurement_matching import line_extraction as lines
from app.services.truthmesh import facts as truthmesh_facts

pytestmark = pytest.mark.no_db

REPO = Path(__file__).resolve().parents[3]
MOCK = REPO / "frontend" / "e2e" / "support" / "llm-mock.mjs"

INVOICE_SECTION = "Invoice / Receipt / Purchase Order"
_BULLET = re.compile(r"^(\s*)-\s+([a-z][a-z0-9_]*)\b")


# --------------------------------------------------------------------------- the prompt's keys


SECTION_TITLES = (INVOICE_SECTION, "Resume", "Contract", "Other")


def _sections() -> dict[str, list[tuple[int, str]]]:
    """Section title -> [(indent, key)] for every `- key` bullet the prompt lists under that title."""
    template = llm_service.ENTITY_EXTRACTION_PROMPT_TEMPLATE
    body = template.split("Rules:", 1)[1].split("Return ONLY valid JSON.", 1)[0]
    out: dict[str, list[tuple[int, str]]] = {}
    title: str | None = None
    for raw in body.splitlines():
        if raw.strip() in SECTION_TITLES and not raw.startswith((" ", "-")):
            title = raw.strip()
            out[title] = []
            continue
        match = _BULLET.match(raw)
        if match:
            assert title is not None, f"a field listed before any section title: {raw!r}"
            out[title].append((len(match.group(1)), match.group(2)))
    return out


def asked_keys(section: str = INVOICE_SECTION) -> set[str]:
    """Top-level keys the prompt asks for in a section (line item sub-keys are `asked_line_keys`)."""
    return {key for indent, key in _sections()[section] if indent == 0}


def asked_line_keys(section: str = INVOICE_SECTION) -> set[str]:
    return {key for indent, key in _sections()[section] if indent > 0}


def _union(*lists: Iterable[str]) -> set[str]:
    return {key for keys in lists for key in keys}


# --------------------------------------------------------------------------- the readers' key lists

#: concept -> every spelling any reader of that concept accepts (taken from the readers themselves).
CONCEPTS: dict[str, set[str]] = {
    "invoice number": _union(
        erp_sources._KEYS["invoice_number"], lines.ROLE_NUMBER_KEYS["INVOICE"],
        truthmesh_facts.OWN_NUMBER_KEYS["INVOICE"], gst_fields.INVOICE_NUMBER_KEYS,
    ),
    "invoice date": _union(
        erp_sources._KEYS["invoice_date"], lines._DATE_KEYS, truthmesh_facts.DATE_SELF_KEYS,
        obligations_extract.INVOICE_DATE_KEYS, gst_fields.INVOICE_DATE_KEYS,
    ),
    "due date": _union(ledger.DUE_DATE_KEYS, erp_sources._KEYS["due_date"]),
    "payment terms": _union(
        ledger.TERMS_KEYS, erp_sources._KEYS["payment_terms"], obligations_extract.TERMS_KEYS,
        corroboration_fields.CONCEPTS["payment_terms"][2],
    ),
    "PO number": _union(
        erp_sources._KEYS["po_reference"], lines._PO_REFERENCE_KEYS, corroboration_fields.CONCEPTS["po_reference"][2],
    ),
    "seller GSTIN": _union(
        identity.SELLER_TAX_KEYS, erp_sources._KEYS["vendor_tax_id"], lines._VENDOR_TAX_KEYS,
        gst_fields.SELLER_GSTIN_KEYS,
    ),
    "buyer GSTIN": _union(identity.BUYER_TAX_KEYS, erp_sources._KEYS["buyer_tax_id"], gst_fields.BUYER_GSTIN_KEYS),
    "seller name": _union(identity.SELLER_NAME_KEYS, erp_sources._KEYS["vendor"], lines._VENDOR_NAME_KEYS),
    "buyer name": _union(identity.BUYER_NAME_KEYS, erp_sources._KEYS["buyer"]),
    "seller email": _union(counterparties.EMAIL_KEYS),
    "seller bank account": _union(truthmesh_facts.PAYEE_KEYS),
    "subtotal (taxable value)": _union(
        erp_sources._KEYS["subtotal"], corroboration_fields.CONCEPTS["subtotal"][2], gst_fields.TAXABLE_VALUE_KEYS,
    ),
    "CGST": _union(gst_fields.CGST_KEYS),
    "SGST": _union(gst_fields.SGST_KEYS),
    "IGST": _union(gst_fields.IGST_KEYS),
    "cess": _union(gst_fields.CESS_KEYS),
    "total tax": _union(
        erp_sources._KEYS["tax"], corroboration_fields.CONCEPTS["tax"][2], gst_fields.TAX_TOTAL_KEYS,
    ),
    "total": _union(
        ledger.TOTAL_KEYS, lines._TOTAL_KEYS, erp_sources._KEYS["total"], corroboration_fields.CONCEPTS["total"][2],
        gst_fields.TOTAL_KEYS,
    ),
    "currency": _union(lines._CURRENCY_KEYS, erp_sources._KEYS["currency"]),
    "place of supply": _union(gst_fields.PLACE_OF_SUPPLY_KEYS),
    "reverse charge": _union(gst_fields.REVERSE_CHARGE_KEYS),
    "IRN": _union(gst_fields.IRN_KEYS),
    "credit note: original invoice number": _union(ledger.CREDIT_REFERENCE_KEYS,
                                                   gst_fields.ORIGINAL_INVOICE_NUMBER_KEYS),
    "credit note: its own number": _union(lines.ROLE_NUMBER_KEYS["CREDIT_NOTE"],
                                          truthmesh_facts.OWN_NUMBER_KEYS["CREDIT_NOTE"]),
    "credit note: type": _union(gst_fields.NOTE_TYPE_KEYS),
    "receipt number": _union(
        erp_sources._KEYS["receipt_number"], lines.ROLE_NUMBER_KEYS["GOODS_RECEIPT"],
        truthmesh_facts.OWN_NUMBER_KEYS["GOODS_RECEIPT"],
    ),
}

#: Line items, by concept: keys inside one entry of `line_items`.
LINE_CONCEPTS: dict[str, set[str]] = {
    "line: description": _union(lines._DESCRIPTION_KEYS),
    "line: HSN/SAC": _union(gst_fields.LINE_HSN_KEYS),
    "line: quantity": _union(lines._QUANTITY_KEYS),
    "line: unit price": _union(lines._UNIT_PRICE_KEYS),
    "line: taxable value": _union(gst_fields.LINE_TAXABLE_VALUE_KEYS, lines._AMOUNT_KEYS),
    "line: tax rate": _union(gst_fields.LINE_TAX_RATE_KEYS),
    "line: amount": _union(lines._AMOUNT_KEYS),
    "line: received quantity": _union(lines._QUANTITY_KEYS),
}


@pytest.mark.parametrize("concept", sorted(CONCEPTS))
def test_the_prompt_asks_for_a_name_every_reader_accepts(concept: str) -> None:
    accepted = CONCEPTS[concept]
    assert accepted, f"no reader declares what it accepts for {concept!r}"
    asked = asked_keys()
    assert asked & accepted, (
        f"the extraction prompt never asks for {concept}: readers accept {sorted(accepted)}, "
        f"the prompt asks for {sorted(asked)}"
    )


@pytest.mark.parametrize("concept", sorted(LINE_CONCEPTS))
def test_the_prompt_asks_for_each_line_item_field_readers_use(concept: str) -> None:
    accepted = LINE_CONCEPTS[concept]
    asked = asked_line_keys()
    assert asked & accepted, f"the prompt's line_items never ask for {concept}: readers accept {sorted(accepted)}"


def test_a_udyam_number_is_asked_for_and_read_back_by_helm() -> None:
    """Helm finds a Udyam number by its shape in any field, so the check is end to end: the key the prompt
    asks for, filled in with a Udyam number, is found."""
    keys = [key for key in asked_keys() if "udyam" in key]
    assert keys, "the extraction prompt never asks for the supplier's Udyam number"
    for key in keys:
        assert msme.find_udyam({key: "UDYAM-MH-12-0001234"}, None) == "UDYAM-MH-12-0001234"


def test_the_prompt_asks_for_no_key_twice_and_nothing_unreadable() -> None:
    """A key nobody reads is noise the model has to produce and a person has to review."""
    keys = [key for indent, key in _sections()[INVOICE_SECTION] if indent == 0]
    assert len(keys) == len(set(keys)), "a key is listed twice in the invoice section"
    readable = _union(*CONCEPTS.values(), {"line_items", "vendor_address", "vendor_pan", "vendor_ifsc", "udyam_number"})
    unread = sorted(set(keys) - readable)
    assert not unread, f"the prompt asks for keys no reader declares: {unread}"


def test_the_instructions_around_the_fields_are_kept() -> None:
    template = llm_service.ENTITY_EXTRACTION_PROMPT_TEMPLATE
    assert "Return ONLY valid JSON." in template, "preset_context is inserted before this line"
    assert template.rstrip().endswith("{text}")
    assert "{document_classification}" in template
    assert re.search(r"null.*(absent|missing|not (stated|present))", template, re.I | re.S), (
        "the prompt must say: null when a field is absent, never a guess"
    )
    assert re.search(r"data", template, re.I), "the document is data, not instructions"
    for other_type in ("Resume", "Contract", "Other"):
        assert other_type in _sections(), f"the {other_type} rules were dropped"
    assert {"candidate_name", "email", "phone_number", "core_skills", "degree_education",
            "years_of_experience"} <= asked_keys("Resume")
    assert {"agreement_date", "termination_date", "party_names", "governing_law", "value_amount"} <= asked_keys(
        "Contract")
    assert {"key_metadata_tags", "core_entities_mentioned"} <= asked_keys("Other")


# --------------------------------------------------------------------------- the model stand-in

#: A document that carries every label the stand-in knows, one per type. Labels are what the sample
#: documents print ("Key: Value"); the stand-in is not a language model.
RICH = {
    "Invoice": "\n".join([
        "TAX INVOICE", "Vendor: Sahyadri Packaging Industries Pvt Ltd", "Vendor GSTIN: 27AAAAA0000A1Z5",
        "Vendor PAN: AAAAA0000A", "Vendor Address: 12 Mill Road, Pune", "Vendor Email: accounts@sahyadri.example",
        "Vendor Bank Account: 000123456789", "Vendor IFSC: HDFC0000123", "Udyam Number: UDYAM-MH-12-0001234",
        "Bill To: Meridian Wholesale Distributors Pvt Ltd", "Buyer GSTIN: 27BBBBB1111B1Z5",
        "Place of Supply: Maharashtra (27)", "Invoice Number: INV-2026-001", "Invoice Date: 2026-04-05",
        "Due Date: 2026-05-05", "Payment Terms: Net 30", "PO Number: PO-2026-007", "Currency: INR",
        "Taxable value: 1000.00", "CGST: 90.00", "SGST: 90.00", "IGST: 0.00", "Cess: 0.00", "Tax Amount: 180.00",
        "Reverse Charge: No", "IRN: " + "a1" * 32, "Total Amount Due: INR 1,180.00",
        "Original Invoice Number: INV-2026-000", "Original Invoice Date: 2026-03-01", "Note Type: Credit",
        "Credit Note Number: CN-2026-001",
        "#   Description   Qty   Unit Price   Amount", "1 Industrial safety gloves 100 5.00 500.00",
    ]),
    "Receipt": "\n".join([
        "GOODS RECEIPT NOTE", "Vendor: Sahyadri Packaging Industries Pvt Ltd", "Receipt Number: GRN-2026-003",
        "PO Number: PO-2026-007", "Received Date: 2026-04-02", "#   Description   Qty received",
        "1 Industrial safety gloves 100",
    ]),
    "Purchase Order": "\n".join([
        "PURCHASE ORDER", "Supplier: Sahyadri Packaging Industries Pvt Ltd", "PO Number: PO-2026-007",
        "PO Date: 2026-03-20", "Buyer: Meridian Wholesale Distributors Pvt Ltd", "Currency: INR", "PO Total: 5,000.00",
        "Payment Terms: Net 30", "#   Description   Qty   Unit Price   Amount", "1 Industrial safety gloves 100 5.00 500.00",
    ]),
    "Contract": "\n".join([
        "MASTER SERVICES AGREEMENT", "Agreement Number: MSA-2026-14",
        "Between Acme Ltd (the Customer) and Beta LLC (the Supplier)",
        "Effective Date: 2026-01-01", "Renewal Date: 2027-01-01", "This agreement is governed by the laws of India.",
        "Fees are USD 12,000.",
    ]),
    "Other": "\n".join(["Site visit note", "Reviewed by: Priya"]),
}
SECTION_OF = {"Invoice": INVOICE_SECTION, "Receipt": INVOICE_SECTION, "Purchase Order": INVOICE_SECTION,
              "Contract": "Contract", "Other": "Other"}


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.fixture(scope="module")
def stand_in():
    """The real stand-in, on a free port; ask it with the real prompt."""
    node = shutil.which("node")
    assert node, "node is needed to run the browser suite's model stand-in (frontend/e2e/support/llm-mock.mjs)"
    port = _free_port()
    process = subprocess.Popen(
        [node, str(MOCK)], env={"E2E_LLM_PORT": str(port), "PATH": "/usr/bin:/bin"},
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        for _ in range(100):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/v1/models", timeout=0.5).read()
                break
            except Exception:
                time.sleep(0.1)
        else:
            raise AssertionError("the model stand-in did not start")

        def ask(document_type: str) -> dict:
            prompt = llm_service.LLMService()._build_entity_prompt(
                text=RICH[document_type], document_classification=document_type)
            request = urllib.request.Request(
                f"http://127.0.0.1:{port}/v1/chat/completions",
                data=json.dumps({"model": "m", "messages": [{"role": "user", "content": prompt}]}).encode(),
                headers={"Content-Type": "application/json"},
            )
            reply = json.loads(urllib.request.urlopen(request, timeout=10).read())
            return json.loads(reply["choices"][0]["message"]["content"])

        yield ask
    finally:
        process.terminate()
        process.wait(timeout=5)


@pytest.mark.parametrize("document_type", sorted(RICH))
def test_the_stand_in_returns_only_keys_the_prompt_asks_for(stand_in, document_type: str) -> None:
    answer = stand_in(document_type)
    assert answer, f"the stand-in read nothing from the {document_type} fixture"
    section = SECTION_OF[document_type]
    unasked = sorted(set(answer) - asked_keys(section))
    assert not unasked, f"the stand-in knows keys the {document_type} prompt never asks for: {unasked}"
    for entry in answer.get("line_items") or []:
        unasked_line = sorted(set(entry) - asked_line_keys(section))
        assert not unasked_line, f"the stand-in's line items carry keys the prompt never asks for: {unasked_line}"


def test_the_stand_in_fixture_exercises_every_key_the_stand_in_can_return(stand_in) -> None:
    """The test above is only as strong as its documents: every `out.<key> =` in the stand-in's
    extraction must show up in at least one answer, or the fixture has gone stale."""
    source = MOCK.read_text(encoding="utf-8")
    body = source.split("function extractEntities", 1)[1].split("/** Verification agents", 1)[0]
    assigned = set(re.findall(r"\bout\.([a-z_]+)\s*=", body)) | set(re.findall(r'\bout\["([a-z_]+)"\]\s*=', body))
    returned: set[str] = set()
    for document_type in RICH:
        returned |= set(stand_in(document_type))
    assert assigned, "could not read the stand-in's extraction keys"
    assert assigned <= returned, f"fixture documents never trigger: {sorted(assigned - returned)}"
