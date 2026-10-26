"""The warning emails after a workspace or organization is deleted (Final session 2A, Phase 4; N-164).

Deleting a workspace or an organization archives it; its documents, conversations and files are erased
`ARCHIVED_PURGE_GRACE_DAYS` (30) days later, and until then it can be restored. Its owners and admins get two emails:

  ARCHIVED     at once: "will be erased on <date>; restore it until then"
  LAST_CHANCE  5 days before the erasure: "last chance to restore"

The names are what people typed (a workspace, an organization), so everything is escaped here and the subject is kept to
one line. Pure function: no Session, no model import, no clock. See common.py.
"""

from __future__ import annotations

from typing import Literal

from app.templates.emails.base import BASE_EMAIL_HTML_LAYOUT
from app.templates.emails.common import esc, esc_attr, single_line


def render_deletion_notice(
    *,
    kind: Literal["ARCHIVED", "LAST_CHANCE"],
    scope: Literal["workspace", "organization"],
    name: str,
    organization_name: str,
    erase_on: str,
    restore_url: str,
    brand_name: str,
) -> tuple[str, str, str]:
    """Render `(subject, html, text)` for one warning to one owner or admin."""
    what = single_line(name, max_length=120)
    organization = single_line(organization_name, max_length=120)
    label = f"the {scope} {what}" if scope == "workspace" else f"the organization {what}"
    if kind == "LAST_CHANCE":
        subject = single_line(f"Last chance: {what} will be erased on {erase_on}")
        lead = (f"In 5 days, on {erase_on}, {brand_name} erases {label} for good: its documents, conversations and "
                f"stored files. This is the last reminder.")
    else:
        subject = single_line(f"{what} was deleted and will be erased on {erase_on}")
        lead = (f"{label[0].upper()}{label[1:]} was deleted. On {erase_on} {brand_name} erases its documents, "
                f"conversations and stored files for good.")
    keep = ("Until then, an owner can restore it and everything comes back as it was. Invoices, the money records the law "
            "asks us to keep and the audit trail stay after the erasure.")
    about = f"Organization: {organization}." if scope == "workspace" else None
    why = f"You get this because you are an owner or admin of {organization} on {brand_name}. It cannot be turned off."

    text_parts = ["Hello,", lead, keep] + ([about] if about else []) + [f"Restore it: {restore_url}", why]
    text_body = "\n\n".join(text_parts) + "\n"

    about_html = f"\n            <p>{esc(about)}</p>" if about else ""
    content_html = f"""<p>Hello,</p>
            <p>{esc(lead)}</p>
            <p>{esc(keep)}</p>{about_html}
            <div class="button-container">
                <a class="button" href="{esc_attr(restore_url)}">Restore it</a>
            </div>
            <p style="font-size:12px;color:#6b7280">{esc(why)}</p>"""
    html_body = BASE_EMAIL_HTML_LAYOUT.format(
        title=esc(subject),
        brand_name=esc(brand_name),
        content_html=content_html,
        footer_text=esc(f"{brand_name} sent this notice about data it will erase."),
    )
    return subject, html_body, text_body
