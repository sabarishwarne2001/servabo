"""The monthly summary email (Session H, Part 3): last month's value receipt for an owner of a paying organization.

Rendered from the trial email's receipt block: a headline and up to three findings, each with a link to its evidence,
one button to the Overview, and a footer that says how to turn it off. HTML and plain text; text from documents escaped."""

from __future__ import annotations

import pytest

from app.templates.emails.monthly_receipt import render_monthly_receipt
from app.templates.emails.trial_notice import TrialFinding

OVERVIEW = "https://app.example.com/acme/main"
PREFS = "https://app.example.com/settings?section=notifications"
HEADLINE = "Last month Servabo read 212 documents and found ₹2,40,000 of GST credit waiting on 6 suppliers."
FINDINGS = [
    TrialFinding("GST credit waiting on 6 suppliers", "₹2,40,000", "https://app.example.com/acme/main/gst"),
    TrialFinding("GST credit you can claim now", "₹1,10,000", "https://app.example.com/acme/main/gst"),
    TrialFinding("2 supplier bank-account changes flagged before payment", None, "https://app.example.com/acme/main/radar"),
    TrialFinding("A fourth finding that must not be written", "₹1", "https://app.example.com/x"),
]


def render(headline: str = HEADLINE, findings=FINDINGS, organization: str = "Acme Traders"):
    return render_monthly_receipt(organization_name=organization, month_label="September 2026", headline=headline,
                                  findings=findings, overview_url=OVERVIEW, preferences_url=PREFS, brand_name="Servabo")


def test_it_names_the_month_the_organization_and_carries_the_headline_and_three_findings() -> None:
    subject, html, text = render()
    assert subject == "What Servabo found for Acme Traders in September 2026"
    assert HEADLINE in text and HEADLINE in html
    assert "GST credit waiting on 6 suppliers: ₹2,40,000 (https://app.example.com/acme/main/gst)" in text
    assert "A fourth finding" not in text and "A fourth finding" not in html
    assert html.count("See the evidence") == 3
    assert text.index(HEADLINE) < text.index(OVERVIEW)           # the figures come before the one button
    assert OVERVIEW in text and 'class="button"' in html and f'href="{OVERVIEW}"' in html


def test_it_says_how_to_stop_it_and_that_it_is_not_tax_advice() -> None:
    _, html, text = render()
    assert PREFS in text and PREFS in html
    assert "Monthly summary" in text
    assert "Not financial or tax advice" in text


def test_a_receipt_with_nothing_found_is_refused_because_an_empty_email_is_never_sent() -> None:
    with pytest.raises(ValueError, match="nothing to say"):
        render(headline="", findings=[])
    with pytest.raises(ValueError, match="nothing to say"):
        render(headline="Last month Servabo read 7 documents.", findings=[])


def test_text_from_documents_is_escaped_in_the_html() -> None:
    findings = [TrialFinding("<script>alert(1)</script> & co", "₹1", 'https://a.example/"><b>')]
    subject, html, _ = render("H", findings, organization="<b>Evil</b> Ltd")
    assert "<script>alert" not in html and "&lt;script&gt;" in html
    assert "<b>Evil</b>" not in html and "\n" not in subject
