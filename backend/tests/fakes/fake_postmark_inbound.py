"""A stand-in for Postmark's inbound webhook (Final session 1, 2B): the JSON Postmark POSTs, in the shape its documentation shows
(postmarkapp.com/developer/webhooks/inbound-webhook, read 2026-10-22), and the HTTP basic auth it sends with it.

Nothing here talks to Postmark. `message()` builds one delivery; `post()` sends it to a TestClient or, for the browser tests
(`scripts/e2e_stand_in.py inbound-email`), to a running API over HTTP.
"""

from __future__ import annotations

import base64
import json
import uuid
from datetime import datetime, timezone
from email.utils import format_datetime
from typing import Any, Mapping, Optional, Sequence

DEFAULT_USER = "postmark-inbound"
DEFAULT_PASSWORD = "e2e-inbound-password-0123456789abcdef"
DEFAULT_HASH = "e2einboundhash0123456789abcdef"
PATH = "/api/v1/inbound/postmark"


def attachment(name: str, data: bytes, content_type: str = "application/pdf", *, content_id: str = "") -> dict[str, Any]:
    return {
        "Name": name, "Content": base64.b64encode(data).decode(), "ContentType": content_type,
        "ContentLength": len(data), "ContentID": content_id,
    }


def message(
    *,
    to: str,
    mailbox_hash: Optional[str] = None,
    sender: str = "ap@supplier.example",
    sender_name: str = "Supplier Accounts",
    subject: str = "Invoice INV-2048",
    message_id: Optional[str] = None,
    attachments: Sequence[Mapping[str, Any]] = (),
    when: Optional[datetime] = None,
) -> dict[str, Any]:
    """One inbound delivery. `to` is the full address the message was sent to; `mailbox_hash` is what Postmark extracted
    after the `+` (empty for a custom-domain address, where the whole local part is the key)."""
    when = when or datetime.now(timezone.utc)
    return {
        "FromName": sender_name,
        "MessageStream": "inbound",
        "From": sender,
        "FromFull": {"Email": sender, "Name": sender_name, "MailboxHash": ""},
        "To": to,
        "ToFull": [{"Email": to, "Name": "", "MailboxHash": mailbox_hash or ""}],
        "Cc": "", "CcFull": [], "Bcc": "", "BccFull": [],
        "OriginalRecipient": to,
        "Subject": subject,
        "MessageID": message_id or str(uuid.uuid4()),
        "ReplyTo": "",
        "MailboxHash": mailbox_hash or "",
        "Date": format_datetime(when),
        "TextBody": "Please find the invoice attached.",
        "HtmlBody": "<p>Please find the invoice attached.</p>",
        "StrippedTextReply": "",
        "Tag": "",
        "Headers": [{"Name": "X-Spam-Status", "Value": "No"}],
        "Attachments": list(attachments),
    }


def for_address(address: str, **kwargs: Any) -> dict[str, Any]:
    """A delivery to `address` as Servabo shows it: `<hash>+<token>@inbound.postmarkapp.com` or `<token>@<domain>`."""
    local = address.split("@", 1)[0]
    mailbox_hash = local.split("+", 1)[1] if "+" in local else ""
    return message(to=address, mailbox_hash=mailbox_hash, **kwargs)


def auth_header(user: str = DEFAULT_USER, password: str = DEFAULT_PASSWORD) -> dict[str, str]:
    return {"Authorization": "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()}


def post(client: Any, payload: Mapping[str, Any], *, user: Optional[str] = DEFAULT_USER, password: str = DEFAULT_PASSWORD,
         path: str = PATH, raw: Optional[bytes] = None):
    """POST to a Starlette TestClient (or anything with `.post(path, content=, headers=)`)."""
    headers = {"Content-Type": "application/json", **(auth_header(user, password) if user is not None else {})}
    body = raw if raw is not None else json.dumps(payload).encode()
    return client.post(path, content=body, headers=headers)
