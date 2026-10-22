"""The e-invoice QR code (stretch goal of Session F; docs/product/GST-CREDIT.md).

An Indian e-invoice carries a QR code whose content is a signed token (a JWT, `header.payload.signature`, each part
base64url). The payload's `data` holds the supplier and buyer GSTIN, the document number, type and date, the invoice
value, the item count, the main HSN code and the **IRN**. An IRN read from the code matches GSTR-2B exactly.

* **Reading.** The code is found in the page images with OpenCV (`einvoice_scan.py`): the WeChat detector (contrib; no
  model file needed, and the one that reads the dense codes an e-invoice has), then the Aruco-based and the standard
  detectors. That runs in the **OCR worker** (`document.extract`), the only image that carries OpenCV, and keeps the
  decoded token texts in `extraction_metadata["qr_codes"]`. Reading the token (this module: base64, JSON, RSA) is plain
  Python and happens in the enrich worker.
* **Trust.** (Three states are shown on the document: signature not checked, checked, does not match.) The signature is **verified only when a public key is configured** (`EINVOICE_QR_PUBLIC_KEY_PEM`, NIC's
  published key; none is shipped). Otherwise the values are marked "signature not verified" and are used as a person
  would use a scribble that agrees: they fill what the model left empty and never replace what it read; a difference
  is recorded for a person to see. Values from a **verified** code win over the model's reading.
* **Provenance.** Each field it supplied or checked is listed in `extraction_metadata["einvoice_qr"]` ("from the
  e-invoice QR code"), with whether the signature was verified.

The layout of the payload follows the NIC e-invoice schema as described in public documentation; it is unverified
against a real e-invoice QR code (the tests use generated codes).
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from app.services.gst import fields as f

logger = logging.getLogger("app.services.gst.einvoice")

SOURCE = "from the e-invoice QR code"
SIGNATURE_NOT_CHECKED = "not_checked"
SIGNATURE_CHECKED = "checked"
SIGNATURE_DOES_NOT_MATCH = "does_not_match"
MAX_PAGES = 3
RENDER_SCALE = 2.5
MAX_TOKEN_CHARS = 20_000
_IRN = re.compile(r"^[0-9a-f]{64}$")
_DOC_TYPES = {"INV": "INVOICE", "CRN": "CREDIT_NOTE", "DBN": "DEBIT_NOTE"}


@dataclass(frozen=True)
class EInvoiceQr:
    seller_gstin: str
    buyer_gstin: Optional[str]
    doc_number: str
    doc_type: str
    doc_date: Optional[date]
    total_value: Optional[Decimal]
    irn: str
    item_count: Optional[int] = None
    main_hsn: Optional[str] = None
    irn_date: Optional[str] = None
    issuer: Optional[str] = None
    signature_verified: bool = False
    #: Final session 1 (3D). "not_checked" (no NIC key is configured), "checked" (the signature verifies with it) or
    #: "does_not_match" (a key is configured and the signature fails: the code may be forged or damaged).
    signature_state: str = SIGNATURE_NOT_CHECKED


# --------------------------------------------------------------------------------------------- the payload


def _b64(segment: str) -> bytes:
    return base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))


def _date(raw: Any) -> Optional[date]:
    text = str(raw or "").strip()[:10]
    for pattern in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    return None


def _amount(raw: Any) -> Optional[Decimal]:
    if raw is None or raw == "":
        return None
    try:
        value = Decimal(str(raw).replace(",", ""))
    except InvalidOperation:
        return None
    return value if value.is_finite() and value >= 0 else None


def parse_token(token: str, *, public_key_pem: Optional[str] = None) -> Optional[EInvoiceQr]:
    """The e-invoice fields in a QR code's text, or None when it is not an e-invoice QR code (or is unreadable).
    `public_key_pem`: verify the RS256 signature with it; without a key `signature_verified` is False."""
    text = (token or "").strip()
    if not text or len(text) > MAX_TOKEN_CHARS or text.count(".") != 2:
        return None
    header_part, payload_part, _signature = text.split(".")
    try:
        payload = json.loads(_b64(payload_part))
        data = payload.get("data") if isinstance(payload, dict) else None
        if isinstance(data, str):
            data = json.loads(data)
    except (ValueError, binascii.Error, UnicodeDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    seller = f.gstin_of(data.get("SellerGstin"))
    irn = str(data.get("Irn") or "").strip().lower()
    number = str(data.get("DocNo") or "").strip()[:64]
    # A real code has a valid supplier GSTIN, a 64-hex IRN and a number; anything less is not trusted as an e-invoice.
    if seller is None or not _IRN.match(irn) or not number:
        return None
    verified = bool(public_key_pem) and verify_signature(text, public_key_pem or "")
    state = (SIGNATURE_CHECKED if verified else SIGNATURE_DOES_NOT_MATCH) if public_key_pem else SIGNATURE_NOT_CHECKED
    item_count = data.get("ItemCnt")
    return EInvoiceQr(
        seller_gstin=seller, buyer_gstin=f.gstin_of(data.get("BuyerGstin")), doc_number=number,
        doc_type=_DOC_TYPES.get(str(data.get("DocTyp") or "INV").upper(), "INVOICE"), doc_date=_date(data.get("DocDt")),
        total_value=_amount(data.get("TotInvVal")), irn=irn,
        item_count=int(item_count) if str(item_count or "").isdigit() else None,
        main_hsn=str(data["MainHsnCode"]).strip()[:8] if data.get("MainHsnCode") else None,
        irn_date=str(data["IrnDt"]) if data.get("IrnDt") else None,
        issuer=str(payload.get("iss")) if isinstance(payload, dict) and payload.get("iss") else None,
        signature_verified=verified, signature_state=state)


def verify_signature(token: str, public_key_pem: str) -> bool:
    """RS256: the signature over `header.payload` checks with `public_key_pem`. Any failure is False."""
    try:
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding
        from cryptography.hazmat.primitives.serialization import load_pem_public_key

        header, payload, signature = token.split(".")
        if json.loads(_b64(header)).get("alg") != "RS256":
            return False
        key = load_pem_public_key(public_key_pem.encode("utf-8"))
        key.verify(_b64(signature), f"{header}.{payload}".encode("ascii"), padding.PKCS1v15(), hashes.SHA256())  # type: ignore[union-attr,call-arg]
        return True
    except Exception:  # noqa: BLE001 - a key or token that does not verify is simply "not verified"
        return False


# --------------------------------------------------------------------------------------------- the entities


def _same(key: str, model: Any, qr: Any) -> bool:
    if key in ("vendor_gstin", "buyer_gstin"):
        return f.gstin_of(model) == qr
    if key == "irn":
        return str(model).strip().lower() == qr
    if key == "invoice_date":
        return _date(model) == _date(qr)
    if key == "total_amount":
        value = _amount(model)
        return value is not None and abs(value - Decimal(str(qr))) <= Decimal("1")
    return re.sub(r"[^A-Za-z0-9]", "", str(model)).lower() == re.sub(r"[^A-Za-z0-9]", "", str(qr)).lower()


def fields_of(qr: EInvoiceQr) -> dict[str, Any]:
    """What the code says, under the extraction prompt's field names."""
    note = qr.doc_type != "INVOICE"
    out: dict[str, Any] = {"irn": qr.irn, "vendor_gstin": qr.seller_gstin,
                           "credit_note_number" if note else "invoice_number": qr.doc_number}
    if qr.buyer_gstin:
        out["buyer_gstin"] = qr.buyer_gstin
    if qr.doc_date:
        out["invoice_date"] = qr.doc_date.isoformat()
    if qr.total_value is not None:
        out["total_amount"] = f"{qr.total_value:.2f}"
    if note:
        out["note_type"] = "debit" if qr.doc_type == "DEBIT_NOTE" else "credit"
    return out


def apply(entities: dict[str, Any], qr: EInvoiceQr) -> dict[str, Any]:
    """Merge the code's values into `entities` (in place) and say what happened, for `extraction_metadata`:

    * a field the model left empty is **filled**;
    * a field that agrees is **confirmed** (nothing changes);
    * a field that differs is **overridden** by a verified code, and only recorded as a **conflict** by an unverified
      one (the model's value stays; a person decides).
    """
    filled: list[str] = []
    confirmed: list[str] = []
    overridden: list[str] = []
    conflicts: list[dict[str, Any]] = []
    for key, value in fields_of(qr).items():
        model = entities.get(key)
        if model in (None, "", []):
            entities[key] = value
            filled.append(key)
        elif _same(key, model, value):
            confirmed.append(key)
        elif qr.signature_verified:
            entities[key] = value
            overridden.append(key)
            conflicts.append({"field": key, "model": model, "qr": value, "used": "qr"})
        else:
            conflicts.append({"field": key, "model": model, "qr": value, "used": "model"})
    notes = {
        SIGNATURE_CHECKED: "The signature was verified with the configured public key.",
        SIGNATURE_DOES_NOT_MATCH: "The signature was not verified: it does not match the configured public key, so these values do not "
                                  "replace what was read from the page. The code may be damaged or not genuine.",
        SIGNATURE_NOT_CHECKED: "The signature was not verified (no public key is configured), so these values do not replace what was "
                               "read from the page.",
    }
    return {"source": SOURCE, "signature_verified": qr.signature_verified, "signature": qr.signature_state, "issuer": qr.issuer,
            "irn": qr.irn, "filled": filled, "confirmed": confirmed, "overridden": overridden, "conflicts": conflicts,
            "note": notes[qr.signature_state]}


def provenance(record: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """What the document page shows of the stored record: the same, with `signature` filled in for records stored before the three
    states existed."""
    if not isinstance(record, dict):
        return None
    out = dict(record)
    out.setdefault("signature", SIGNATURE_CHECKED if record.get("signature_verified") else SIGNATURE_NOT_CHECKED)
    return out


def enrich_work_item(entities: dict[str, Any], work_item: Any) -> Optional[dict[str, Any]]:
    """The enrich step: the QR token texts the OCR worker found (`extraction_metadata["qr_codes"]`) merged into the
    entities; the provenance record, or None. Never raises."""
    try:
        from app.core.config import settings

        texts = (getattr(work_item, "extraction_metadata", None) or {}).get("qr_codes") or []
        for text in texts if isinstance(texts, list) else []:
            qr = parse_token(str(text), public_key_pem=settings.EINVOICE_QR_PUBLIC_KEY_PEM)
            if qr is not None:
                return apply(entities, qr)
    except Exception:  # noqa: BLE001 - a QR code is a bonus: the document must go on without it
        logger.warning("einvoice.enrich_failed", exc_info=True)
    return None


__all__ = ["EInvoiceQr", "SIGNATURE_CHECKED", "SIGNATURE_DOES_NOT_MATCH", "SIGNATURE_NOT_CHECKED", "SOURCE", "apply", "provenance", "enrich_work_item", "fields_of", "parse_token", "verify_signature"]
