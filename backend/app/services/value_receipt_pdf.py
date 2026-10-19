"""The value receipt as a one-page PDF, to justify the purchase (Session G, P2).

The same data as the screen (`app.services.value_receipt`), laid out with the Time machine report's page writer
(Helvetica, nothing embedded; the rupee sign is written "INR " because the font cannot draw it). Each finding is
written with its plain meaning and the app path of the page that holds its evidence. The creation date is the
moment the receipt was made, so the same receipt at the same moment gives the same bytes.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from app.services.helm.backtest_report import ACCENT, BODY_W, INK, MARGIN, MUTED, _Writer, wrap  # noqa: PLC2701
from app.services.helm.backtest_report import clean

FOOTER = "Figures come from your own documents in Servabo. Not financial or tax advice."

#: What each finding means, in words a finance manager can repeat. Keyed by the finding's key (or its prefix).
MEANING = (
    ("gst_waiting", "Purchase invoices in your books that no imported GSTR-2B shows yet. The input tax credit is "
                    "deferred until the supplier reports them."),
    ("gst_at_risk_180", "Invoices not recorded as paid in Servabo that are 150 days old or more. If the supplier is "
                        "not paid within 180 days of the invoice date, credit taken may have to be reversed, and "
                        "interest may apply."),
    ("gst_claimable", "Credit on invoices the supplier has reported and that agree with your books (net of credit "
                      "and debit notes)."),
    ("time_machine_confirmed", "What Helm would have held or saved over the replayed period, where the evidence "
                               "shows it happened (a credit note, a reviewer's confirmation, a payment date)."),
    ("time_machine_likely", "What Helm would likely have held or saved: the rule fired and the facts are there, but "
                            "nothing confirms the loss. Not counted as value held."),
    ("time_machine_potential", "What Helm might have held or saved if missing facts hold. Not counted as value held."),
    ("duplicate_payments", "Invoices that look like repeats of an invoice you already have, so paying both would "
                           "pay twice. Open or confirmed by a reviewer."),
    ("bank_account_changes", "Suppliers whose bank account on a new invoice differs from the one on earlier "
                             "invoices, flagged before payment."),
    ("overcharges", "Invoice lines priced above the agreed purchase order price, summed over the live matching "
                    "cases."),
    ("helm_value_held", "Outcomes Helm held and can prove: a confirmed duplicate never paid, an overcharge later "
                        "credited, an early-payment discount captured, a late fee avoided."),
)


def meaning(key: str) -> str:
    return next((words for prefix, words in MEANING if key.startswith(prefix)), "")


def _day(iso: str, zone_name: str) -> str:
    from zoneinfo import ZoneInfo

    try:
        moment = datetime.fromisoformat(iso).astimezone(ZoneInfo(zone_name))
    except Exception:  # noqa: BLE001
        moment = datetime.fromisoformat(iso)
    return f"{moment.day} {moment.strftime('%b %Y')}"


def filename(receipt: dict[str, Any], slug: Optional[str] = None) -> str:
    return f"servabo-value-receipt-{slug + '-' if slug else ''}{receipt['period']}.pdf"


def to_pdf(receipt: dict[str, Any], *, created: Optional[datetime] = None) -> bytes:
    """`receipt` is the dict `value_receipt.receipt` returns."""
    created = created or datetime.now(timezone.utc)
    zone = receipt.get("timezone") or "UTC"
    period_words = "Free trial" if receipt["period"] == "trial" else "This month"
    span = f"{_day(receipt['period_start'], zone)} to {_day(receipt['period_end'], zone)}"

    w = _Writer()
    w.para("SERVABO  -  VALUE RECEIPT", size=8, bold=True, rgb=ACCENT, gap=4)
    w.para(receipt.get("organization_name") or "Your organization", size=18, bold=True, gap=2)
    w.para(f"{period_words}: {span}", size=9.5, rgb=MUTED, gap=8)
    if receipt.get("headline"):
        w.para(receipt["headline"], size=11, bold=True, gap=8)

    work = receipt["work"]
    w.heading("What Servabo read", size=11)
    w.row([("Documents", 0, 120, True), (f"{work['documents']:,}", 120, 80, False)], size=9)
    w.row([("Pages", 0, 120, True), (f"{work['pages']:,}", 120, 80, False)], size=9)
    w.row([("Assistant answers", 0, 120, True), (f"{work['assistant_answers']:,}", 120, 80, False)], size=9)

    w.heading("What Servabo found", size=11)
    if not receipt["found"]:
        w.para("Nothing to report for this period.", size=9, rgb=MUTED)
    for finding in receipt["found"]:
        label_w = BODY_W - 120
        w.need(44)
        w.row([(finding["label"], 0, label_w, True), (finding.get("amount_text") or "", label_w, 120, True)], size=9.2, gap=1)
        if finding.get("honesty"):
            w.para(f"Confidence: {finding['honesty']} (the three levels are never added together).", size=8, rgb=MUTED, gap=1)
        words = meaning(finding["key"])
        if words:
            w.para(words, size=8.4, indent=0, gap=1)
        w.para(f"Evidence: {finding['source']}", size=7.8, rgb=MUTED, gap=6)

    if receipt.get("also_on_business"):
        w.heading("Business also checks", size=11)
        w.para(", ".join(receipt["also_on_business"]) + ".", size=9)
    if receipt.get("gst_add_on_line"):
        w.para(receipt["gst_add_on_line"] + ".", size=9)

    return w.finish(title=f"Servabo value receipt - {receipt.get('organization_name') or ''}",
                    subject="What Servabo found in the organization's own documents", created=created,
                    footer=[FOOTER], author="Servabo", creator="Servabo value receipt")


__all__ = ["FOOTER", "filename", "meaning", "to_pdf"]
