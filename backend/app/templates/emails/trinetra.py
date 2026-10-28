"""TRINETRA's email (Final 2T, Phase 6): one inquiry a person approved and sent to a customer, with a secure link for the
customer's Form 16A, withholding advice or correction response. Never sent on its own. It names the invoice, the amount the
business's records show was withheld and the period, never a PAN or a TAN, and never alleges missing filing or says what
credit the customer owes. Every value is escaped; each returns (subject, html_body, text_body)."""

from __future__ import annotations

from app.templates.emails.base import BASE_EMAIL_HTML_LAYOUT
from app.templates.emails.common import clip, esc, esc_attr, single_line


def _wrap(subject: str, brand_name: str, content_html: str, footer: str) -> str:
    return BASE_EMAIL_HTML_LAYOUT.format(title=esc(subject), brand_name=esc(brand_name), content_html=content_html,
                                         footer_text=esc(footer))


def render_inquiry(*, organization_name: str, customer_name: str, invoice_number: str, amount_text: str, period_label: str,
                   document_label: str, note: str, upload_url: str, valid_until: str) -> tuple[str, str, str]:
    customer_name, invoice_number = clip(customer_name), clip(invoice_number, 80)
    amount_text, period_label, document_label = clip(amount_text, 60), clip(period_label, 60), clip(document_label, 80)
    note = clip(note, 600)
    subject = single_line(f"Please help us match the tax deducted on invoice {invoice_number}")
    intro = (f"Our records for invoice {invoice_number} ({period_label}) show {amount_text} withheld as tax at source. "
             "We are matching our records with the tax statement we hold, and we would be grateful for a copy of the "
             f"{document_label} for this deduction, so that both sides agree. This is a request for a document; it does not "
             "suggest that anything was done wrongly.")
    text = (f"Dear {customer_name},\n\n{intro}\n\n" + (f"{note}\n\n" if note else "")
            + f"You can upload it with this secure link (it works once, until {valid_until}):\n{upload_url}\n\n"
            f"Thank you,\n{organization_name}\n")
    content = (f"<p>Dear {esc(customer_name)},</p><p>{esc(intro)}</p>" + (f"<p>{esc(note)}</p>" if note else "")
               + "<p>You can upload it with this secure link (it works once, until "
               f"<strong>{esc(valid_until)}</strong>):</p><div class=\"button-container\"><a href=\"{esc_attr(upload_url)}\" "
               "class=\"button\">Upload the document</a></div>"
               f"<p>Thank you,<br>{esc(organization_name)}</p>")
    return subject, _wrap(subject, organization_name, content,
                          f"Sent by {organization_name} about invoice {invoice_number}."), text
