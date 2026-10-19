"""The trial emails with and without the value receipt (Session G): a headline and up to three findings, in HTML and
plain text, each with a link to its evidence; without figures the email is exactly what it was."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.templates.emails.trial_notice import TrialFinding, render_trial_notice

NOW = datetime(2026, 10, 14, 9, 0, tzinfo=timezone.utc)
PLANS = "https://app.example.com/organizations/acme/billing"
HEADLINE = "In your trial Servabo read 132 documents and found ₹2,40,000 of GST credit waiting on 6 suppliers."
FINDINGS = [
    TrialFinding("GST credit waiting on 6 suppliers", "₹2,40,000", "https://app.example.com/acme/main/gst"),
    TrialFinding("GST credit you can claim now", "₹1,10,000", "https://app.example.com/acme/main/gst"),
    TrialFinding("2 supplier bank-account changes flagged before payment", None, "https://app.example.com/acme/main/radar"),
    TrialFinding("A fourth finding that must not be written", "₹1", "https://app.example.com/x"),
]


def render(kind: str, headline: str = "", findings=()):
    return render_trial_notice(kind=kind, organization_names=["Acme"], ends_at=NOW + timedelta(days=2), plans_link=PLANS,
                               brand_name="Servabo", headline=headline, findings=findings)


@pytest.mark.parametrize("kind", ["ENDING", "ENDED"])
def test_both_emails_carry_the_headline_and_three_findings(kind: str) -> None:
    subject, html, text = render(kind, HEADLINE, FINDINGS)
    assert HEADLINE in text and HEADLINE.replace("&", "&amp;") in html
    assert "GST credit waiting on 6 suppliers: ₹2,40,000 (https://app.example.com/acme/main/gst)" in text
    assert "2 supplier bank-account changes flagged before payment (https://app.example.com/acme/main/radar)" in text
    assert "A fourth finding" not in text and "A fourth finding" not in html
    assert html.count("See the evidence") == 3
    assert 'href="https://app.example.com/acme/main/gst"' in html
    assert text.index(HEADLINE) < text.index(PLANS)          # the figures come before the one button
    assert PLANS in text and 'class="button"' in html                  # and the button is still there


@pytest.mark.parametrize("kind", ["ENDING", "ENDED"])
def test_without_figures_the_email_is_exactly_what_it_was(kind: str) -> None:
    plain = render(kind)
    assert render(kind, "", FINDINGS) == plain       # no headline: no figures
    assert render(kind, "", []) == plain
    assert "See the evidence" not in plain[1] and "GST" not in plain[2]


def test_a_headline_with_no_findings_is_just_the_headline() -> None:
    subject, html, text = render("ENDED", "In your trial Servabo read 7 documents.", [])
    assert "In your trial Servabo read 7 documents." in text and "<ul>" not in html


def test_text_from_documents_is_escaped_in_the_html() -> None:
    findings = [TrialFinding("<script>alert(1)</script> & co", "₹1", 'https://a.example/"><b>')]
    html = render("ENDING", "H", findings)[1]
    assert "<script>alert" not in html and "&lt;script&gt;" in html
    assert 'href="https://a.example/"><b>"' not in html
