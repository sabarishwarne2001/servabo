"""The Monday GST credit digest (Final session 1, 3A): where the organization's GST credit stands, once a week.

Sent by `app.services.gst.digest` only when there is something to report; this renderer refuses an empty one. It reuses the monthly
summary's block (`trial_notice.receipt_block`): the headline and up to three lines, each with a link. Where the plan shows only the
headline figures, one extra line says what the lists would add and what it costs. Pure function: no Session, no model import, no clock.
"""

from __future__ import annotations

from typing import Optional, Sequence

from app.templates.emails.base import BASE_EMAIL_HTML_LAYOUT
from app.templates.emails.common import clip, esc, esc_attr, single_line
from app.templates.emails.trial_notice import TrialFinding, receipt_block

NOT_ADVICE = "Figures come from your own documents and imported GSTR-2B in Servabo. A recommendation, not tax advice."


def render_gst_digest(
    *,
    organization_name: str,
    week_label: str,
    headline: str,
    findings: Sequence[TrialFinding],
    gst_url: str,
    preferences_url: str,
    brand_name: str,
    unlock_line: Optional[str] = None,
    unlock_url: Optional[str] = None,
) -> tuple[str, str, str]:
    """Render `(subject, html, text)`. `ValueError` when there is nothing to say."""
    if not single_line(headline or "") or not list(findings):
        raise ValueError("a GST digest with nothing to say is never sent")
    # Final session 2A (invariant (e)): finding lines name suppliers (GSTR-2B trade names); bounded as well as escaped.
    import dataclasses

    headline = clip(headline)
    findings = [dataclasses.replace(f, label=clip(f.label), amount_text=clip(f.amount_text, 60) if f.amount_text else f.amount_text)
                for f in findings]
    unlock_line = clip(unlock_line) if unlock_line else unlock_line
    organization = single_line(organization_name)
    subject = single_line(f"Your GST credit this week: {organization}")
    lead = f"Here is where GST credit stands for {organization} in the week of {single_line(week_label)}."
    found_text, found_html = receipt_block(headline, findings)
    button = "Open GST Credit"
    footer = (
        f"{brand_name} sends this on Mondays to owners, administrators and billing contacts, and only when there is something to report. "
        'Turn it off under "GST credit" in your notification settings.'
    )
    unlock_text = f"{single_line(unlock_line)}: {unlock_url}\n\n" if unlock_line and unlock_url else ""
    unlock_html = (f'<p><a href="{esc_attr(unlock_url)}">{esc(unlock_line)}</a></p>' if unlock_line and unlock_url else "")

    text_body = (
        f"Hello,\n\n{lead}\n\n{found_text}{unlock_text}{NOT_ADVICE}\n\n{button}: {gst_url}\n\n"
        f"{footer}\nNotification settings: {preferences_url}\n"
    )
    content_html = f"""<p>Hello,</p>
            <p>{esc(lead)}</p>
            {found_html}
            {unlock_html}
            <p>{esc(NOT_ADVICE)}</p>
            <div class="button-container">
                <a class="button" href="{esc_attr(gst_url)}">{esc(button)}</a>
            </div>
            <p><a href="{esc_attr(preferences_url)}">Notification settings</a></p>"""
    html_body = BASE_EMAIL_HTML_LAYOUT.format(
        title=esc(subject), brand_name=esc(brand_name), content_html=content_html, footer_text=esc(footer))
    return subject, html_body, text_body


__all__ = ["render_gst_digest"]
