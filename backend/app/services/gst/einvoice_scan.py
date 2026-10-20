"""Finding the e-invoice QR code in a document's pages (OpenCV; runs in the OCR worker only).

`document.extract` runs in the OCR image, the one image that carries OpenCV (requirements-ocr.txt); the web image
must not (tests/infra/test_image_requirements.py). So the pictures are read here, at extraction, and only the decoded
token texts are kept (`extraction_metadata["qr_codes"]`). Reading and trusting them is `einvoice.py`, plain Python,
in the enrich worker. Imports of cv2, numpy and PDFium are inside the functions on purpose: nothing but the OCR
worker ever calls them.
"""

from __future__ import annotations

import logging
from typing import Any, Iterable

logger = logging.getLogger("app.services.gst.einvoice_scan")

MAX_PAGES = 3
RENDER_SCALE = 2.5
MAX_TOKEN_CHARS = 20_000
MAX_CODES = 3


def decode_images(images: Iterable[Any]) -> list[str]:
    """The texts of every QR code found in the images (numpy arrays: grey or BGR). Never raises."""
    import cv2

    found: list[str] = []
    detectors = []
    if hasattr(cv2, "wechat_qrcode_WeChatQRCode"):
        detectors.append(("wechat", cv2.wechat_qrcode_WeChatQRCode()))
    if hasattr(cv2, "QRCodeDetectorAruco"):
        detectors.append(("aruco", cv2.QRCodeDetectorAruco()))
    detectors.append(("standard", cv2.QRCodeDetector()))
    for image in images:
        for name, detector in detectors:
            try:
                if name == "wechat":
                    texts, _points = detector.detectAndDecode(image)
                    texts = [t for t in texts if t]
                else:
                    ok, texts, _points, _straight = detector.detectAndDecodeMulti(image)
                    texts = [t for t in texts if ok and t]
            except Exception:  # noqa: BLE001 - one detector failing must not hide what another reads
                logger.debug("einvoice.detector_failed", extra={"detector": name}, exc_info=True)
                continue
            for text in texts:
                if text not in found:
                    found.append(text)
            if found:
                break
    return found


def page_may_hold_a_code(page: Any) -> bool:
    """False for a page of nothing but text, which cannot hold a QR code (Session I, F-532).

    A code is a picture, shapes drawn on the page, or a form that holds either: any object that is not text. A page
    with none of them is not rendered or read; the WeChat detector takes about 1.6 s on a page with no code, and the
    worker runs one job at a time. A scan is a picture and a web page printed to PDF has its code as shapes, so both
    are still read. (A code set in a font of squares would not be; none is known.)"""
    import pypdfium2.raw as raw

    count = raw.FPDFPage_CountObjects(page.raw)
    return any(
        raw.FPDFPageObj_GetType(raw.FPDFPage_GetObject(page.raw, index)) != raw.FPDF_PAGEOBJ_TEXT
        for index in range(max(count, 0))
    )


def render_pdf(pdf_bytes: bytes, *, max_pages: int = MAX_PAGES, scale: float = RENDER_SCALE) -> list[Any]:
    """The first pages of a PDF that can hold a code, as grey numpy arrays."""
    import numpy as np
    import pypdfium2 as pdfium

    from app.core.pdfium_lock import PDFIUM_LOCK, pdfium_page

    images: list[Any] = []
    with PDFIUM_LOCK:
        document = pdfium.PdfDocument(pdf_bytes)
        try:
            for index in range(min(len(document), max_pages)):
                with pdfium_page(document, index) as page:
                    if not page_may_hold_a_code(page):
                        continue
                    bitmap = page.render(scale=scale, grayscale=True)
                    images.append(np.array(bitmap.to_numpy(), copy=True))
        finally:
            document.close()
    return images


def read_images_of(data: bytes, mime: str) -> list[Any]:
    mime = (mime or "").split(";")[0].strip().lower()
    if mime == "application/pdf":
        return render_pdf(data)
    if mime.startswith("image/"):
        import cv2
        import numpy as np

        image = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
        return [] if image is None else [image]
    return []


def token_texts(data: bytes, mime: str) -> list[str]:
    """The texts of the QR codes of a document that look like a signed token (`a.b.c`, base64url parts): at most
    three, none longer than 20,000 characters. Never raises: a document that cannot be opened has no QR code for us."""
    try:
        found = [t for t in decode_images(read_images_of(data, mime)) if t.count(".") == 2 and len(t) <= MAX_TOKEN_CHARS]
        return found[:MAX_CODES]
    except Exception:  # noqa: BLE001
        logger.warning("einvoice.scan_failed", exc_info=True)
        return []


def scan_work_item(work_item: Any) -> list[str]:
    """Token texts from the stored file of a work item (PDF or image); the OCR worker keeps them in the metadata."""
    mime = (getattr(work_item, "file_type", None) or "").split(";")[0].strip().lower()
    if not getattr(work_item, "stored_filename", None) or not (mime == "application/pdf" or mime.startswith("image/")):
        return []
    try:
        from app.core.storage import get_storage_driver

        return token_texts(get_storage_driver().get(work_item.stored_filename), mime)
    except Exception:  # noqa: BLE001
        logger.warning("einvoice.scan_unavailable", exc_info=True)
        return []


__all__ = ["decode_images", "page_may_hold_a_code", "render_pdf", "scan_work_item", "token_texts"]
