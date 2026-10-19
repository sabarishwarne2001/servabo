"""The e-invoice QR code (stretch): a generated, signed token in a QR image is found in a PDF and in a PNG, read into
the invoice's fields (IRN, GSTINs, number, date, value), trusted only as far as its signature is verified, and the IRN
then matches GSTR-2B exactly. The codes are generated here with an invented key; no real e-invoice is involved."""

from __future__ import annotations

import base64
import io
import json
import uuid
from datetime import date

import pytest

pytestmark = pytest.mark.no_db

qrcode = pytest.importorskip("qrcode")
cv2 = pytest.importorskip("cv2")

from cryptography.hazmat.primitives import hashes, serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import padding, rsa  # noqa: E402
from PIL import Image  # noqa: E402

from app.services.gst import books, einvoice  # noqa: E402
from app.services.gst import builder as b  # noqa: E402
from app.services.gst.matching import reconcile  # noqa: E402
from tests.services.gst.helpers import RECIPIENT, SUPPLIER_A, parsed_return, rec_views  # noqa: E402

IRN = "9f1c" * 16


def b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def pem(private) -> str:
    return private.public_key().public_bytes(serialization.Encoding.PEM,
                                              serialization.PublicFormat.SubjectPublicKeyInfo).decode()


def token(private, **overrides) -> str:
    data = {"SellerGstin": SUPPLIER_A, "BuyerGstin": RECIPIENT, "DocNo": "INV/25-26/0042", "DocTyp": "INV",
            "DocDt": "05/09/2026", "TotInvVal": 118000.0, "ItemCnt": 3, "MainHsnCode": "8708", "Irn": IRN,
            "IrnDt": "2026-09-05 10:15:00", **overrides}
    header = b64(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
    payload = b64(json.dumps({"data": json.dumps(data), "iss": "NIC"}).encode())
    signature = private.sign(f"{header}.{payload}".encode(), padding.PKCS1v15(), hashes.SHA256())
    return f"{header}.{payload}.{b64(signature)}"


def qr_png(text: str, box: int = 4) -> bytes:
    code = qrcode.QRCode(box_size=box, border=4)
    code.add_data(text)
    code.make(fit=True)
    out = io.BytesIO()
    code.make_image(fill_color="black", back_color="white").convert("L").save(out, format="PNG")
    return out.getvalue()


def pdf_with(png: bytes) -> bytes:
    page = Image.new("L", (1240, 1754), 255)
    qr = Image.open(io.BytesIO(png))
    page.paste(qr, (80, 120))
    out = io.BytesIO()
    page.save(out, format="PDF", resolution=150)
    return out.getvalue()


def test_the_payload_is_read_and_the_signature_only_when_a_key_is_given():
    private = key()
    text = token(private)
    unverified = einvoice.parse_token(text)
    assert unverified is not None and unverified.signature_verified is False
    assert (unverified.seller_gstin, unverified.buyer_gstin, unverified.doc_number, unverified.irn) == (
        SUPPLIER_A, RECIPIENT, "INV/25-26/0042", IRN)
    assert unverified.doc_date == date(2026, 9, 5) and str(unverified.total_value) == "118000.0"
    assert (unverified.item_count, unverified.main_hsn, unverified.issuer) == (3, "8708", "NIC")
    assert einvoice.parse_token(text, public_key_pem=pem(private)).signature_verified is True
    assert einvoice.parse_token(text, public_key_pem=pem(key())).signature_verified is False
    # a signature that was tampered with after signing
    head, payload, signature = text.split(".")
    forged = b64(json.dumps({"data": json.dumps({"SellerGstin": SUPPLIER_A, "DocNo": "X", "Irn": IRN}), "iss": "NIC"}).encode())
    assert einvoice.parse_token(f"{head}.{forged}.{signature}", public_key_pem=pem(private)).signature_verified is False


@pytest.mark.parametrize("bad", ["", "not a token", "a.b.c", "x" * 30_000, "eyJhIjoxfQ.eyJhIjoxfQ.sig"])
def test_text_that_is_not_an_e_invoice_is_not_read(bad):
    assert einvoice.parse_token(bad) is None


def test_a_token_without_a_valid_supplier_or_irn_is_refused():
    private = key()
    assert einvoice.parse_token(token(private, SellerGstin="27AAAAA0000A1Z")) is None   # not a GSTIN
    assert einvoice.parse_token(token(private, Irn="short")) is None
    assert einvoice.parse_token(token(private, DocNo="")) is None


@pytest.mark.parametrize("box", [3, 6])
def test_a_dense_qr_code_is_found_in_a_png_and_in_a_pdf(box):
    private = key()
    text = token(private)
    assert len(text) > 700   # a real e-invoice token is this dense (QR version 20 and up)
    png = qr_png(text, box)
    from_png = einvoice.read_bytes(png, "image/png")
    assert from_png is not None and from_png.irn == IRN
    from_pdf = einvoice.read_bytes(pdf_with(qr_png(text, 5)), "application/pdf", public_key_pem=pem(private))
    assert from_pdf is not None and from_pdf.irn == IRN and from_pdf.signature_verified is True
    assert einvoice.read_bytes(b"not an image", "image/png") is None
    assert einvoice.read_bytes(pdf_with(qr_png("just some text", 5)), "application/pdf") is None


def test_values_fill_what_the_model_left_empty_and_never_replace_what_it_read_unless_verified():
    private = key()
    qr = einvoice.parse_token(token(private))
    entities = {"invoice_number": "INV/25-26/0042", "vendor_gstin": SUPPLIER_A, "total_amount": "99999.00",
                "invoice_date": "2026-09-05"}
    record = einvoice.apply(entities, qr)
    assert entities["irn"] == IRN and entities["buyer_gstin"] == RECIPIENT           # filled
    assert entities["total_amount"] == "99999.00"                                     # the model's value stays
    assert record["filled"] == ["irn", "buyer_gstin"] and set(record["confirmed"]) == {"vendor_gstin", "invoice_number", "invoice_date"}
    assert record["conflicts"] == [{"field": "total_amount", "model": "99999.00", "qr": "118000.00", "used": "model"}]
    assert record["source"] == "from the e-invoice QR code" and record["signature_verified"] is False
    assert "not verified" in record["note"]

    verified = einvoice.parse_token(token(private), public_key_pem=pem(private))
    won = {"invoice_number": "INV-42", "total_amount": "99999.00"}
    record = einvoice.apply(won, verified)
    assert won["total_amount"] == "118000.00" and won["invoice_number"] == "INV/25-26/0042"
    assert set(record["overridden"]) == {"invoice_number", "total_amount"} and record["signature_verified"] is True


def test_a_credit_note_is_read_as_a_note():
    qr = einvoice.parse_token(token(key(), DocTyp="CRN", DocNo="CN-7"))
    fields = einvoice.fields_of(qr)
    assert fields["credit_note_number"] == "CN-7" and fields["note_type"] == "credit" and "invoice_number" not in fields


def test_the_irn_then_matches_gstr_2b_exactly_even_when_the_model_misread_the_number():
    qr = einvoice.parse_token(token(key()))
    entities = {"invoice_number": "INV/25-26/OO42", "vendor_gstin": SUPPLIER_A, "buyer_gstin": RECIPIENT,
                "invoice_date": "2026-09-05", "subtotal": "100000.00", "cgst_amount": "9000.00", "sgst_amount": "9000.00",
                "tax_amount": "18000.00", "total_amount": "118000.00"}
    einvoice.apply(entities, qr)
    assert entities["invoice_number"] == "INV/25-26/OO42" and entities["irn"] == IRN
    fact = books.BookDocument(uuid.uuid4(), "i.pdf", "INVOICE", entities, "INV/25-26/OO42", date(2026, 9, 5), "INR", 118_000_000_000)
    from app.services.helm import identity as ident

    view = books.book_view(fact, identities=ident.Identities(frozenset(), frozenset()), gstin=RECIPIENT, cases={}, settlements={})
    assert view is not None and view.irn == IRN
    parsed = parsed_return({"b2b": [b.supplier(SUPPLIER_A, "Sahyadri Packaging", [
        b.document("INV/25-26/0042", date(2026, 9, 5), 100000, irn=IRN)], filed_on=date(2026, 10, 9), period="09-2026")]})
    out = reconcile(rec_views(parsed), [view], tolerance_micros=1_000_000, decisions=[], window=None)
    matched = [o for o in out if o.book is not None]
    assert len(matched) == 1 and matched[0].status == "MATCHED" and matched[0].method == "IRN"


def test_the_processing_step_reads_the_stored_file_and_never_breaks_a_document(monkeypatch):
    from types import SimpleNamespace

    private = key()
    pdf = pdf_with(qr_png(token(private), 5))
    storage = SimpleNamespace(get=lambda name: pdf if name == "stored.pdf" else (_ for _ in ()).throw(OSError("gone")))
    monkeypatch.setattr("app.core.storage.get_storage_driver", lambda: storage)
    entities = {"classification_details": {"document_classification": "Invoice"}, "invoice_number": "INV/25-26/0042"}
    record = einvoice.enrich_work_item(entities, SimpleNamespace(file_type="application/pdf", stored_filename="stored.pdf"))
    assert record is not None and entities["irn"] == IRN and record["signature_verified"] is False
    # a missing file, or a type with no picture in it, is just "no QR code"
    assert einvoice.enrich_work_item({}, SimpleNamespace(file_type="application/pdf", stored_filename="missing.pdf")) is None
    assert einvoice.enrich_work_item({}, SimpleNamespace(file_type="text/plain", stored_filename="stored.pdf")) is None
