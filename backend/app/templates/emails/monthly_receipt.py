"""The monthly summary (Session H, Part 3): last month's value receipt, for an owner of a paying organization.

Sent on the 1st of each month by `app.services.monthly_receipt_email` (`monthly_receipt.send`), only when the receipt
holds at least one finding; this renderer refuses an empty one rather than write an email that says "nothing found".
It reuses the trial email's receipt block (`trial_notice.receipt_block`): the headline and up to three
findings, each with a link to its evidence. One button, to the Overview. The footer names the switch that turns it off
("Monthly summary" in the person's notification settings).

Pure function: no Session, no model import, no clock. See common.py.
"""

from __future__ import annotations

from typing import Sequence

from app.templates.emails.base import BASE_EMAIL_HTML_LAYOUT
from app.templates.emails.common import esc, esc_attr, single_line
from app.templates.emails.trial_notice import TrialFinding, receipt_block

NOT_ADVICE = "Figures come from your own documents in Servabo. Not financial or tax advice."


def render_monthly_receipt(
    *,
    organization_name: str,
    month_label: str,
    headline: str,
    findings: Sequence[TrialFinding],
    overview_url: str,
    preferences_url: str,
    brand_name: str,
) -> tuple[str, str, str]:
    """Render `(subject, html, text)`. `ValueError` when there is nothing to say (no headline, or no finding)."""
    if not single_line(headline or "") or not list(findings):
        raise ValueError("a monthly summary with nothing to say is never sent")
    organization = single_line(organization_name)
    month = single_line(month_label)
    subject = single_line(f"What {brand_name} found for {organization} in {month}")
    lead = f"Here is what {brand_name} found for {organization} in {month}."
    found_text, found_html = receipt_block(headline, findings)
    button = "Open the Overview"
    footer = (
        f"{brand_name} sends this on the 1st of each month to the owners of a paying organization. "
        'Turn it off under "Monthly summary" in your notification settings.'
    )

    text_body = (
        f"Hello,\n\n{lead}\n\n{found_text}{NOT_ADVICE}\n\n{button}: {overview_url}\n\n"
        f"{footer}\nNotification settings: {preferences_url}\n"
    )
    content_html = f"""<p>Hello,</p>
            <p>{esc(lead)}</p>
            {found_html}
            <p>{esc(NOT_ADVICE)}</p>
            <div class="button-container">
                <a class="button" href="{esc_attr(overview_url)}">{esc(button)}</a>
            </div>
            <p><a href="{esc_attr(preferences_url)}">Notification settings</a></p>"""
    html_body = BASE_EMAIL_HTML_LAYOUT.format(
        title=esc(subject),
        brand_name=esc(brand_name),
        content_html=content_html,
        footer_text=esc(footer),
    )
    return subject, html_body, text_body


__all__ = ["render_monthly_receipt"]
