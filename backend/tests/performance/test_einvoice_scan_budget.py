"""Session I (F-532). The e-invoice QR scan's cost on a document that has no QR code.

The OCR worker runs one job at a time, and the scan ran over every PDF it extracted: about 1.6 s for a one-page text
invoice and about 4.8 s for three pages, on a document that could not hold a code. The browser suite's documents are such
PDFs, and each one made every job queued behind it wait longer.

Budget (sandbox, `PERF_BUDGET_MULTIPLIER=1`): a three-page PDF of text is passed in under 0.25 s. Before the change the
same call took 4.5 s to 5 s. `PERF_BUDGET_MULTIPLIER` (default 3, as the other performance tests) gives a shared CI
machine its slack. Measured figures are printed (pytest -s) for docs/hardening/PERFORMANCE.md.
"""

from __future__ import annotations

import io
import os
import time

import pytest

pytest.importorskip("cv2")
pytest.importorskip("reportlab")

from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.pdfgen import canvas  # noqa: E402

from app.services.gst import einvoice_scan  # noqa: E402

MULTIPLIER = float(os.getenv("PERF_BUDGET_MULTIPLIER", "3.0"))
BUDGET_SECONDS = 0.25


def _text_pdf(pages: int) -> bytes:
    out = io.BytesIO()
    c = canvas.Canvas(out, pagesize=A4)
    for page in range(pages):
        for line in range(45):
            c.drawString(56, 800 - line * 16, f"Page {page + 1}, line {line}: invoice INV-2026-0042, total 118000.00 INR.")
        c.showPage()
    c.save()
    return out.getvalue()


def test_a_three_page_document_of_text_is_scanned_in_a_fraction_of_a_second():
    pdf = _text_pdf(3)
    einvoice_scan.token_texts(pdf, "application/pdf")   # load OpenCV and PDFium once; the worker does that at start
    samples = []
    for _ in range(3):
        started = time.perf_counter()
        assert einvoice_scan.token_texts(pdf, "application/pdf") == []
        samples.append(time.perf_counter() - started)
    best = min(samples)
    print(f"\ne-invoice scan, 3 pages of text: best of 3 = {best * 1000:.0f} ms (budget {BUDGET_SECONDS * MULTIPLIER * 1000:.0f} ms)")
    assert best <= BUDGET_SECONDS * MULTIPLIER
