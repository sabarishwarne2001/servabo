"""Indian GST in the books (Final session 1, 3C): what a purchase bill carries into Zoho Books India and into Tally Prime.

Pure rendering, no database: a canonical bill with its GST block is rendered through the shipped default mappings.

  * Zoho Books: the vendor's GSTIN, the GST treatment, the two states as Zoho writes them, and on every line the HSN or SAC code and
    the tax code looked up in the `taxes` table; no separate tax line (the books add the tax from the code, so one would count it
    twice); a tax code the table does not know stops the posting and names the code.
  * Tally Prime: a balanced voucher. CGST and SGST (two ledgers, half each) for a purchase inside the buyer's state, IGST (one
    ledger) from another state; the party ledger is credited with the total and every entry sums to zero.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from app.services.erp import canonical as C
from app.services.erp import gst_fields as G
from app.services.erp import presets as PR
from app.services.erp import render as R
from app.services.erp import vocabulary as v
from app.services.erp.formats import xmlsafe
from app.services.gst import builder as b

BUYER = b.make_gstin("27", "AAACM1234F")            # Maharashtra
VENDOR_SAME_STATE = b.make_gstin("27", "AABCS5555K")
VENDOR_OTHER_STATE = b.make_gstin("29", "AAGCD7777P")  # Karnataka
D = Decimal


def bill(vendor_gstin: str, *, intra: bool) -> C.PostingObject:
    obj = C.PostingObject(kind=v.OBJECT_VENDOR_BILL, currency="INR", document_number="INV-2048", document_date=date(2026, 9, 12),
                          due_date=date(2026, 10, 12), posting_date=date(2026, 10, 1), subtotal=D("2000.00"), tax_total=D("360.00"),
                          total=D("2360.00"), vendor=C.Party(name="Sahyadri Packaging", entity_id="vend-1", tax_id=vendor_gstin),
                          buyer=C.Party(name="Meridian Wholesale", tax_id=BUYER), source={"kind": "PROCUREMENT_CASE", "label": "Case 7"})
    obj.lines = [C.Line(number=1, description="Corrugated boxes", code="4819", quantity=D(100), unit_price=D("10"), amount=D("1000.00"),
                        tax_amount=D("180.00"), hsn="4819"),
                 C.Line(number=2, description="Tape", code="3919", quantity=D(50), unit_price=D("20"), amount=D("1000.00"),
                        tax_amount=D("180.00"), hsn="3919")]
    heads = dict(cgst=D("180.00"), sgst=D("180.00"), igst=D("0.00")) if intra else dict(cgst=None, sgst=None, igst=D("360.00"))
    obj.gst = G.describe(vendor_gstin=vendor_gstin, buyer_gstin=BUYER, place_of_supply=None, cess=None, **heads)
    for line in obj.lines:
        line.gst_tax_key = G.line_key(obj.gst, line_amount=line.amount, line_tax=line.tax_amount, subtotal=obj.subtotal, tax_total=obj.tax_total)
    return obj


def render(target_format: str, preset: str, obj: C.PostingObject, lookups: dict, config: dict | None = None) -> R.Rendered:
    spec = PR.default_mapping(target_format, preset, obj.kind)
    return R.render(R.TargetView(target_format, preset, config or {}), obj, spec, lookups=lookups,
                    extra={"id": "p1", "idempotency_key": "k", "date": date(2026, 10, 1), "bill_external_id": None},
                    posting_id="00000000-0000-0000-0000-000000000001", remote_id="FP-k", at=datetime(2026, 10, 1, tzinfo=timezone.utc))


# ------------------------------------------------------------------------------------------ the pieces

def test_a_gstin_gives_its_state_and_two_letters_for_zoho():
    assert G.state_of(VENDOR_SAME_STATE) == "27" and G.STATE_LETTERS["27"] == "MH" and G.STATE_LETTERS["29"] == "KA"
    assert G.state_of("27-Maharashtra") == "27" and G.state_of("Maharashtra") is None


def test_the_tax_code_is_the_slab_nearest_the_lines_own_rate_and_says_which_kind():
    assert G.tax_key(True, D("18.004")) == "GST18" and G.tax_key(False, D("17.98")) == "IGST18"
    assert G.tax_key(True, D("5")) == "GST5" and G.tax_key(True, D("0")) == "GST0"
    assert G.tax_key(True, D("14.2")) is None, "a rate on no slab is not guessed"


def test_a_document_without_any_sign_of_gst_has_no_gst_block():
    assert G.describe(vendor_gstin="VAT123", buyer_gstin=None, place_of_supply=None, cgst=None, sgst=None, igst=None, cess=None) == {}


def test_the_states_decide_when_the_heads_are_not_printed():
    info = G.describe(vendor_gstin=VENDOR_SAME_STATE, buyer_gstin=BUYER, place_of_supply=None, cgst=None, sgst=None, igst=None, cess=None)
    assert info["intra_state"] is True and info["treatment"] == "business_gst"
    info = G.describe(vendor_gstin=VENDOR_OTHER_STATE, buyer_gstin=None, place_of_supply="27-Maharashtra", cgst=None, sgst=None, igst=None, cess=None)
    assert info["intra_state"] is False and info["destination_state_code"] == "MH" and info["vendor_state_code"] == "KA"


# ------------------------------------------------------------------------------------------ Zoho Books

ZOHO_TABLES = {"vendors": {"vend-1": "zoho-vendor-1"}, "accounts": {"default": "acc-expense"},
               "taxes": {"GST18": "tax-gst18", "IGST18": "tax-igst18"}, "items": {}, "settings": {}}


def test_a_same_state_bill_carries_the_gst_fields_and_no_separate_tax_line():
    out = render(v.FORMAT_JSON, v.PRESET_ZOHO, bill(VENDOR_SAME_STATE, intra=True), ZOHO_TABLES, {"zoho": {"organization_id": "1"}})
    body = out.body
    assert body["gst_treatment"] == "business_gst" and body["gst_no"] == VENDOR_SAME_STATE
    assert body["source_of_supply"] == "MH" and body["destination_of_supply"] == "MH"
    assert [(ln["hsn_or_sac"], ln["tax_id"]) for ln in body["line_items"]] == [("4819", "tax-gst18"), ("3919", "tax-gst18")]
    assert len(body["line_items"]) == 2, "the books add the tax from the code; a tax line would count it twice"


def test_an_other_state_bill_uses_the_igst_code_and_the_vendors_state():
    out = render(v.FORMAT_JSON, v.PRESET_ZOHO, bill(VENDOR_OTHER_STATE, intra=False), ZOHO_TABLES, {"zoho": {"organization_id": "1"}})
    assert out.body["source_of_supply"] == "KA" and out.body["destination_of_supply"] == "MH"
    assert {ln["tax_id"] for ln in out.body["line_items"]} == {"tax-igst18"}


def test_a_tax_code_the_books_do_not_know_stops_the_posting_and_names_it():
    tables = {**ZOHO_TABLES, "taxes": {}}
    with pytest.raises(R.RenderError) as raised:
        render(v.FORMAT_JSON, v.PRESET_ZOHO, bill(VENDOR_SAME_STATE, intra=True), tables, {"zoho": {"organization_id": "1"}})
    assert "GST18" in " ".join(raised.value.problems)


def test_a_bill_without_gst_still_posts_with_its_tax_as_a_line():
    obj = bill(VENDOR_SAME_STATE, intra=True)
    obj.gst = {}
    for line in obj.lines:
        line.gst_tax_key = None
        line.hsn = None
    tables = {**ZOHO_TABLES, "accounts": {"default": "acc-expense", "TAX": "acc-tax"}}
    out = render(v.FORMAT_JSON, v.PRESET_ZOHO, obj, tables, {"zoho": {"organization_id": "1"}})
    assert len(out.body["line_items"]) == 3 and "gst_no" not in out.body and "tax_id" not in out.body["line_items"][0]


# ------------------------------------------------------------------------------------------ Tally Prime

TALLY_TABLES = {"vendors": {}, "accounts": {"default": "Packaging Purchases", "CGST": "Input CGST 9%", "SGST": "Input SGST 9%",
                                             "IGST": "Input IGST 18%"}, "items": {}, "settings": {}, "taxes": {}}


def entries(xml: bytes) -> list[tuple[str, Decimal]]:
    root = xmlsafe.parse(xml)
    return [(le.findtext("LEDGERNAME"), Decimal(le.findtext("AMOUNT"))) for le in root.iter("ALLLEDGERENTRIES.LIST")]


def test_a_same_state_purchase_books_cgst_and_sgst_to_their_own_ledgers_and_balances():
    out = render(v.FORMAT_TALLY, v.PRESET_NONE, bill(VENDOR_SAME_STATE, intra=True), TALLY_TABLES, {"tally": {"company": "Meridian"}})
    rows = entries(out.data)
    assert ("Sahyadri Packaging", D("2360.00")) in rows
    assert ("Input CGST 9%", D("-180.00")) in rows and ("Input SGST 9%", D("-180.00")) in rows
    assert not any(name == "Input IGST 18%" for name, _a in rows)
    assert sum(a for _n, a in rows) == 0


def test_an_other_state_purchase_books_igst_to_one_ledger_and_balances():
    out = render(v.FORMAT_TALLY, v.PRESET_NONE, bill(VENDOR_OTHER_STATE, intra=False), TALLY_TABLES, {"tally": {"company": "Meridian"}})
    rows = entries(out.data)
    assert ("Input IGST 18%", D("-360.00")) in rows
    assert not any(name in ("Input CGST 9%", "Input SGST 9%") for name, _a in rows)
    assert sum(a for _n, a in rows) == 0


def test_a_bill_whose_heads_do_not_add_up_is_refused_rather_than_posted_unbalanced():
    obj = bill(VENDOR_SAME_STATE, intra=True)
    obj.gst["sgst"] = "100.00"
    with pytest.raises(R.RenderError, match="does not balance"):
        render(v.FORMAT_TALLY, v.PRESET_NONE, obj, TALLY_TABLES, {"tally": {"company": "Meridian"}})


def test_a_bill_without_heads_keeps_the_single_tax_ledger():
    obj = bill(VENDOR_SAME_STATE, intra=True)
    obj.gst = {}
    out = render(v.FORMAT_TALLY, v.PRESET_NONE, obj, {**TALLY_TABLES, "accounts": {**TALLY_TABLES["accounts"], "TAX": "Input Tax"}},
                 {"tally": {"company": "Meridian"}})
    rows = entries(out.data)
    assert ("Input Tax", D("-360.00")) in rows and sum(a for _n, a in rows) == 0
