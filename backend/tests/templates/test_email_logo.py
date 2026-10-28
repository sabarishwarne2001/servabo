"""The real Servabo logo in every email Servabo sends (owner request, 2026-10-27; N-199).

    pytest tests/templates/test_email_logo.py -q

Mail sent as Servabo showed a stand-in drawn in HTML (a navy tile with a plain "S"). It now carries the logo itself
(the ribbon mark and the "servabo" wordmark) as a picture inside the message (an inline attachment referenced as
`cid:`), so Gmail, Outlook and Apple Mail show it without asking to load remote images, and an email that must carry
no web address still carries none. A light and a dark version: dark-mode clients that read the stylesheet swap them.
Mail sent under an organization's own brand carries neither.
"""

from __future__ import annotations

import re
import struct
from email.message import EmailMessage
from pathlib import Path

import pytest

from app.core.smtp import SMTPConfig
from app.models.email_settings import EmailEncryption
from app.services.email_service import email_service
from app.templates.emails import inline_images
from tests.templates.test_emails_render_in_mail_clients import EMAILS

ASSETS = Path(inline_images.__file__).parent / "assets"


def _verify_html() -> str:
    return EMAILS["verify"]()[1]


def _png_size(data: bytes) -> tuple[int, int]:
    assert data[:8] == b"\x89PNG\r\n\x1a\n", "not a PNG"
    return struct.unpack(">II", data[16:24])


def test_servabo_mail_shows_the_logo_as_an_embedded_picture() -> None:
    header = _verify_html().split('<div class="content"', 1)[0]
    light = re.search(r'<img [^>]*src="cid:servabo-logo-light"[^>]*>', header)
    assert light, "the light logo is not in the header"
    assert 'alt="Servabo"' in light.group(0) and 'width="' in light.group(0) and 'height="' in light.group(0)
    assert re.search(r'<img [^>]*src="cid:servabo-logo-dark"[^>]*display:none', header), "no hidden dark logo"
    assert ">S</span>" not in header, "the old stand-in tile is still drawn"
    assert not re.search(r'<img [^>]*src="https?:', header), "no remote image: some emails must carry no address"


def test_dark_mode_swaps_the_logo() -> None:
    style = _verify_html().split("</style>", 1)[0]
    dark = style.split("prefers-color-scheme: dark", 1)[1]
    assert ".logo-light" in dark and ".logo-dark" in dark


def test_white_label_mail_carries_no_servabo_logo() -> None:
    _, html, _ = EMAILS["helm-briefing"]()  # sent under the organization's own brand
    assert "cid:servabo-logo" not in html


@pytest.mark.parametrize("name", ["servabo-logo-light", "servabo-logo-dark"])
def test_the_logo_pictures_are_the_brand_logo_at_three_times_email_size(name: str) -> None:
    data = (ASSETS / f"{name}.png").read_bytes()
    width, height = _png_size(data)
    assert height == inline_images.LOGO_HEIGHT * 3 and inline_images.LOGO_WIDTH == round(width / 3)
    svg = (Path(__file__).resolve().parents[3] / "brand/assets" / f"{name}.svg").read_text()
    view_w, view_h = (float(v) for v in re.search(r'viewBox="0 0 ([\d.]+) ([\d.]+)"', svg).groups())
    pad = inline_images.LOGO_PAD * 3   # the panel around the logo, on each side
    assert abs((width - 2 * pad) / (height - 2 * pad) - view_w / view_h) < 0.02, "the picture is not the brand logo's shape"


def test_the_light_logo_carries_its_own_white_panel_and_the_dark_one_none() -> None:
    """Gmail's phone apps darken the card in dark mode but ignore the stylesheet that swaps the pictures: the light
    logo's dark lettering stays readable on its own white panel (N-199)."""
    from PIL import Image

    light = Image.open(ASSETS / "servabo-logo-light.png").convert("RGBA")
    dark = Image.open(ASSETS / "servabo-logo-dark.png").convert("RGBA")
    edge = (3, light.height // 2)                       # inside the panel's padding, beside the mark
    assert light.getpixel(edge) == (255, 255, 255, 255)
    assert dark.getpixel(edge)[3] == 0
    assert light.getpixel((0, 0))[3] < 255               # rounded corners


def _send(html: str) -> EmailMessage:
    sent: list[EmailMessage] = []
    config = SMTPConfig(smtp_host="relay.example.com", smtp_port=587, smtp_username="u", smtp_password="p",
                        sender_name="Servabo", encryption=EmailEncryption.TLS, from_email="no-reply@example.com")
    original = email_service._send_message
    email_service._send_message = lambda cfg, message: sent.append(message) or (True, "ok")  # type: ignore[method-assign]
    try:
        email_service.send_html_email(settings=config, recipient="owner@example.com", subject="S", html_body=html,
                                      text_body="plain")
    finally:
        email_service._send_message = original  # type: ignore[method-assign]
    return sent[0]


def test_the_sent_message_carries_both_pictures_inline_with_their_content_ids() -> None:
    message = _send(_verify_html())
    html_part = message.get_body(("html",))
    assert html_part is not None and "cid:servabo-logo-light" in html_part.get_content()
    images = {part["Content-ID"]: part for part in message.walk() if part.get_content_type() == "image/png"}
    assert set(images) == {"<servabo-logo-light>", "<servabo-logo-dark>"}
    for cid, part in images.items():
        assert part.get_content_disposition() == "inline"
        assert part.get_content() == (ASSETS / f"{cid.strip('<>')}.png").read_bytes()
    assert message.get_body(("plain",)).get_content().strip() == "plain"


def test_a_message_without_the_logo_gets_no_attachment() -> None:
    _, html, _ = EMAILS["helm-briefing"]()
    message = _send(html)
    assert not [part for part in message.walk() if part.get_content_maintype() == "image"]

