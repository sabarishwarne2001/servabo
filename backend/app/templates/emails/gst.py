"""The GST Credit email to a supplier: invoices of theirs we cannot see in our GSTR-2B. Same layout and
escaping as Helm's emails; returns (subject, html_body, text_body)."""

from __future__ import annotations

from typing import Sequence

from app.services.helm import money
from app.templates.emails.base import BASE_EMAIL_HTML_LAYOUT
from app.templates.emails.common import esc, single_line


def render_missing_invoices(*, organization_name: str, supplier_name: str, period_text: str,
                            lines: Sequence[dict]) -> tuple[str, str, str]:
    """`lines`: [{"number", "date", "amount_micros", "tax_micros"}] in rupees."""
    subject = single_line(f"Please report {len(lines)} invoice(s) in GSTR-1: not in our GSTR-2B")
    rows_text = []
    rows_html = []
    for line in lines:
        amount = money.say(int(line.get("amount_micros") or 0), "INR")
        tax = money.say(int(line.get("tax_micros") or 0), "INR")
        rows_text.append(f"- {single_line(str(line.get('number') or ''))}, dated {line.get('date') or ''}: "
                         f"{amount} (GST {tax})")
        rows_html.append(f"<li>{esc(str(line.get('number') or ''))}, dated {esc(str(line.get('date') or ''))}: "
                         f"{esc(amount)} (GST {esc(tax)})</li>")
    text = (f"Dear {supplier_name},\n\nWe cannot find these invoices of yours in our GSTR-2B for {period_text}:\n"
            + "\n".join(rows_text) + "\n\nIf they have not been reported yet, please report them in your GSTR-1 (or "
            "IFF) so that we can claim the input tax credit. If you have already reported them, please tell us the "
            f"filing date.\n\nRegards,\n{organization_name}\n")
    content = (f"<p>Dear {esc(supplier_name)},</p><p>We cannot find these invoices of yours in our GSTR-2B for "
               f"{esc(period_text)}:</p><ul>{''.join(rows_html)}</ul><p>If they have not been reported yet, please "
               "report them in your GSTR-1 (or IFF) so that we can claim the input tax credit. If you have already "
               "reported them, please tell us the filing date.</p>"
               f"<p>Regards,<br>{esc(organization_name)}</p>")
    html = BASE_EMAIL_HTML_LAYOUT.format(title=esc(subject), brand_name=esc(organization_name), content_html=content,
                                         footer_text=esc(f"Sent by {organization_name} about its GST input tax credit."))
    return subject, html, text
