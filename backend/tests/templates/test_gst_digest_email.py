"""The Monday GST credit digest email (Final session 1, 3A): a headline and up to three lines, one button, how to turn it off,
and (on a plan that shows only the headline) one line saying what the lists add and what they cost."""

from __future__ import annotations

import pytest

from app.templates.emails.gst_digest import render_gst_digest
from app.templates.emails.trial_notice import TrialFinding

GST = "https://app.example.com/organizations/acme/gst"
PREFS = "https://app.example.com/settings?section=notifications"
HEADLINE = "INR 2,25,000.00 of GST credit is claimable now."
FINDINGS = [
    TrialFinding("Waiting for suppliers to report: 3 invoices from 2 suppliers", "INR 1,80,000.00", GST),
    TrialFinding("Near the 180-day limit: 1 invoice", "INR 9,000.00", GST),
    TrialFinding("Differences to settle: 2 invoices", "INR 450.00", GST),
    TrialFinding("A fourth line that must not be written", "INR 1.00", GST),
]


def render(headline: str = HEADLINE, findings=FINDINGS, **extra):
    return render_gst_digest(organization_name="Acme Traders", week_label="19 October 2026", headline=headline, findings=findings,
                             gst_url=GST, preferences_url=PREFS, brand_name="Servabo", **extra)


def test_it_carries_the_headline_three_lines_and_one_button_in_indian_grouping() -> None:
    subject, html, text = render()
    assert subject == "Your GST credit this week: Acme Traders"
    assert HEADLINE in text and HEADLINE in html and "INR 1,80,000.00" in text
    assert "A fourth line" not in text and "A fourth line" not in html
    assert text.index(HEADLINE) < text.index("Open GST Credit:")
    assert html.count('class="button"') == 1 and f'href="{GST}"' in html


def test_it_says_how_to_stop_it_and_that_it_is_not_tax_advice() -> None:
    _, html, text = render()
    assert PREFS in text and PREFS in html and '"GST credit"' in text
    assert "not tax advice" in text


def test_the_unlock_line_appears_only_when_given() -> None:
    _, html, text = render(unlock_line="Unlock the lists: GST Credit add-on, $49 a month", unlock_url=GST)
    assert "Unlock the lists: GST Credit add-on, $49 a month" in text and "Unlock the lists" in html
    _, html, text = render()
    assert "Unlock" not in text and "Unlock" not in html


def test_nothing_to_say_is_refused() -> None:
    with pytest.raises(ValueError, match="nothing to say"):
        render(headline="", findings=[])
    with pytest.raises(ValueError, match="nothing to say"):
        render(findings=[])


def test_text_from_documents_is_escaped() -> None:
    _, html, _ = render(findings=[TrialFinding("<script>x</script> & co", "INR 1.00", GST)])
    assert "<script>x" not in html and "&lt;script&gt;" in html
