"""The two free-trial emails (owner decision N-052): two days before the end, and when it ends.

Sent to each owner ACCOUNT once (the trial belongs to the account), naming the
organizations still on the trial, by `app.workers.handlers.trial` (`trial.reminders`).

Both carry one link, to the plan page of the first organization, where an owner
subscribes. Neither says the data is at risk: nothing is deleted when a trial ends.

Session G: an account whose first organization has something to show gets the value receipt's headline and up to
three findings (what Servabo found in its own documents, each with a link to the evidence) between the lead and the
rest. Without figures the email is exactly what it was. The figures arrive as plain data (`headline` and
`findings`), computed by the caller from `app.services.value_receipt`; this module stays pure.

Pure function: no Session, no model import, no clock. See common.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Sequence

from app.templates.emails.base import BASE_EMAIL_HTML_LAYOUT
from app.templates.emails.common import esc, esc_attr, format_timestamp, single_line


def _organization_list(names: Sequence[str]) -> str:
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + f" and {names[-1]}"


MAX_FINDINGS = 3


@dataclass(frozen=True)
class TrialFinding:
    """One line of the value receipt: what was found, the amount as the server writes it, and the evidence link."""

    label: str
    amount_text: Optional[str] = None
    url: Optional[str] = None


def _finding_line(item: TrialFinding) -> str:
    label = single_line(item.label or "", max_length=200)
    return f"{label}: {single_line(item.amount_text, max_length=40)}" if item.amount_text else label


def _finding_text(item: TrialFinding) -> str:
    url = single_line(item.url, max_length=500) if item.url else ""
    return f"{_finding_line(item)} ({url})" if url else _finding_line(item)


def _finding_html(item: TrialFinding) -> str:
    link = f' <a href="{esc_attr(item.url)}">See the evidence</a>' if item.url else ""
    return f"{esc(_finding_line(item))}{link}"


def render_receipt_block(headline: str, findings: Sequence[TrialFinding]) -> tuple[str, str]:
    """The value receipt as it sits inside an email: `(text, html)` — the headline and at most three findings, each
    with a link to its evidence. Empty strings without a headline (the email carries no figures then). The monthly
    summary reuses this block (Session H)."""
    said = single_line(headline or "", max_length=300)
    if not said:
        return "", ""
    shown = list(findings)[:MAX_FINDINGS]
    text = f"{said}\n" + "".join(f"  - {_finding_text(item)}\n" for item in shown) + "\n"
    html = f"""<p><strong>{esc(said)}</strong></p>""" + (
        "<ul>" + "".join(f"<li>{_finding_html(item)}</li>" for item in shown) + "</ul>" if shown else "")
    return text, html


def render_trial_notice(
    *,
    kind: str,
    organization_names: Sequence[str],
    ends_at: datetime,
    plans_link: str,
    brand_name: str,
    headline: str = "",
    findings: Sequence[TrialFinding] = (),
) -> tuple[str, str, str]:
    """Render `(subject, html, text)`. `kind` is "ENDING" (two days before) or "ENDED".

    `headline` and `findings` are the value receipt's: at most three findings are written. Without a headline the
    email carries no figures."""
    if kind not in ("ENDING", "ENDED"):
        raise ValueError(f"unknown trial notice {kind!r}")
    organizations = _organization_list([single_line(name) for name in organization_names])
    when = format_timestamp(ends_at)

    if kind == "ENDING":
        subject = single_line(f"Your {brand_name} trial ends on {when}")
        lead = (
            f"Your free trial of {brand_name} for {organizations} ends on {when}. "
            "Choose a plan before then to keep uploading documents, asking the assistant "
            "and running automations without a pause."
        )
        after = (
            "If you do not subscribe, nothing is deleted: everyone can still sign in, read, "
            "search and export, and subscribing later turns everything back on at once."
        )
        button = "Choose a plan"
    else:
        subject = single_line(f"Your {brand_name} trial has ended")
        lead = (
            f"Your free trial of {brand_name} for {organizations} ended on {when}. "
            "New uploads, the assistant and automations are paused until you choose a plan."
        )
        after = (
            "Nothing has been deleted. Everyone can still sign in, read, search and export, "
            "and subscribing turns everything back on at once."
        )
        button = "Subscribe"

    found_text, found_html = render_receipt_block(headline, findings)

    text_body = f"Hello,\n\n{lead}\n\n{found_text}{after}\n\n{button}: {plans_link}\n"
    content_html = f"""<p>Hello,</p>
            <p>{esc(lead)}</p>
            {found_html}
            <p>{esc(after)}</p>
            <div class="button-container">
                <a class="button" href="{esc_attr(plans_link)}">{esc(button)}</a>
            </div>"""
    footer_text = (
        f"{brand_name} sent this because you own an organization on the free trial."
    )
    html_body = BASE_EMAIL_HTML_LAYOUT.format(
        title=esc(subject),
        brand_name=esc(brand_name),
        content_html=content_html,
        footer_text=esc(footer_text),
    )
    return subject, html_body, text_body


__all__ = ["MAX_FINDINGS", "TrialFinding", "render_receipt_block", "render_trial_notice"]
