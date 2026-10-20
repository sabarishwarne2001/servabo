"""Session I (F-532). Which pages of a PDF the e-invoice QR scan reads.

The scan rendered up to three pages of every PDF the OCR worker extracted and ran OpenCV's detectors over each. On a
page with no code the WeChat detector takes about 1.6 s at the render scale in use, so a one-page text invoice cost the
worker 1.6 s and a three-page contract 4.8 s, and the worker runs one job at a time. A page of nothing but text cannot
hold a QR code; a page with a picture, a drawing or a form still can. These tests pin both halves: text-only pages are
not rendered, and every other kind of page is still read (a code beside the text, a code drawn as vector shapes).
"""

from __future__ import annotations

import io

import pytest

qrcode = pytest.importorskip("qrcode")
pytest.importorskip("cv2")
pytest.importorskip("reportlab")

from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.lib.utils import ImageReader  # noqa: E402
from reportlab.pdfgen import canvas  # noqa: E402

from app.services.gst import einvoice_scan  # noqa: E402

# Three base64url-looking parts, 868 characters in all: as dense as a signed e-invoice token (QR version 20 and up).
TOKEN = ".".join(["eyJhbGciOiJSUzI1NiJ9" * 2, "Qx7" * 150, "s1G" * 126])


def _qr_matrix(text: str) -> list[list[bool]]:
    code = qrcode.QRCode(box_size=1, border=0)
    code.add_data(text)
    code.make(fit=True)
    return code.get_matrix()


def _qr_png(text: str) -> bytes:
    code = qrcode.QRCode(box_size=5, border=4)
    code.add_data(text)
    code.make(fit=True)
    out = io.BytesIO()
    code.make_image(fill_color="black", back_color="white").convert("L").save(out, format="PNG")
    return out.getvalue()


def _words(c: canvas.Canvas) -> None:
    """Thirty lines across the top of the page; the bottom right is left clear for a code and its white border."""
    for line in range(30):
        c.drawString(56, 800 - line * 16, f"Clause {line}: the supplier shall deliver the goods within thirty days of the order.")


def _pdf(*pages) -> bytes:
    out = io.BytesIO()
    c = canvas.Canvas(out, pagesize=A4)
    for draw in pages:
        draw(c)
        c.showPage()
    c.save()
    return out.getvalue()


def _text_only(c: canvas.Canvas) -> None:
    _words(c)


def _text_with_picture(c: canvas.Canvas) -> None:
    """A born-digital e-invoice: a text layer, and the QR code as a picture in a corner."""
    _words(c)
    c.drawImage(ImageReader(io.BytesIO(_qr_png(TOKEN))), 330, 40, 230, 230)


def _text_with_vector_code(c: canvas.Canvas) -> None:
    """The same code drawn as filled squares, as a PDF printed from a web page with an SVG code is."""
    _words(c)
    matrix = _qr_matrix(TOKEN)
    module = 2.0
    left, top = 330.0, 300.0
    for row, cells in enumerate(matrix):
        for column, dark in enumerate(cells):
            if dark:
                c.rect(left + column * module, top - (row + 1) * module, module, module, stroke=0, fill=1)


def test_a_page_of_nothing_but_text_is_not_rendered_for_reading():
    pdf = _pdf(_text_only, _text_only, _text_only)
    assert einvoice_scan.render_pdf(pdf) == []


def test_a_document_of_text_never_reaches_the_detectors(monkeypatch):
    calls: list[int] = []
    real = einvoice_scan.decode_images
    monkeypatch.setattr(einvoice_scan, "decode_images", lambda images: calls.append(len(list(images))) or real([]))
    assert einvoice_scan.token_texts(_pdf(_text_only, _text_only, _text_only), "application/pdf") == []
    assert calls in ([], [0])   # nothing was handed to OpenCV


def test_a_code_beside_the_text_is_still_read():
    pdf = _pdf(_text_with_picture)
    assert len(einvoice_scan.render_pdf(pdf)) == 1
    assert einvoice_scan.token_texts(pdf, "application/pdf") == [TOKEN]


def test_a_code_drawn_as_vector_shapes_is_still_read():
    pdf = _pdf(_text_with_vector_code)
    assert len(einvoice_scan.render_pdf(pdf)) == 1
    assert einvoice_scan.token_texts(pdf, "application/pdf") == [TOKEN]


def test_each_page_is_judged_on_its_own():
    pdf = _pdf(_text_only, _text_with_picture, _text_only)
    assert len(einvoice_scan.render_pdf(pdf)) == 1
    assert einvoice_scan.token_texts(pdf, "application/pdf") == [TOKEN]


def test_a_picture_only_page_such_as_a_scan_is_still_read():
    from PIL import Image

    page = Image.new("L", (1240, 1754), 255)
    page.paste(Image.open(io.BytesIO(_qr_png(TOKEN))), (80, 120))
    out = io.BytesIO()
    page.save(out, format="PDF", resolution=150)
    assert einvoice_scan.token_texts(out.getvalue(), "application/pdf") == [TOKEN]
