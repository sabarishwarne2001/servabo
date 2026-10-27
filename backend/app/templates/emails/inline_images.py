"""The Servabo logo as a picture inside the email (owner request, 2026-10-27; N-199).

Mail clients hold remote images until the reader allows them, and some emails must carry no web address at all (a
revocation notice, a completed transfer). So the logo travels inside the message: the HTML refers to `cid:<name>` and
`attach` adds the matching PNG as an inline part (multipart/related), which Gmail, Outlook and Apple Mail show at once.

The PNGs in `assets/` are the brand's own logo files (`brand/assets/servabo-logo-{light,dark}.svg`) at three times
email size, made by `brand/scripts/build_brand_assets.py`. Only what the HTML refers to is attached: mail sent under an
organization's own brand carries no Servabo picture.
"""

from __future__ import annotations

from email.message import EmailMessage
from functools import cache
from pathlib import Path

ASSETS = Path(__file__).parent / "assets"
LIGHT, DARK = "servabo-logo-light", "servabo-logo-dark"
#: The picture's size in the email, in CSS pixels: the logo 40 px tall (its shape is 125.74 x 32) with 4 px of panel
#: around it. The light picture's panel is white and opaque, so a client that darkens the card without reading the
#: stylesheet (Gmail's phone apps) still shows dark lettering on white; the dark picture's is transparent.
LOGO_PAD = 4
LOGO_HEIGHT = 48
LOGO_WIDTH = 165


@cache
def _png(name: str) -> bytes:
    return (ASSETS / f"{name}.png").read_bytes()


def attach(message: EmailMessage, html_body: str) -> None:
    """Add every logo picture `html_body` refers to as an inline part of `message`'s HTML alternative."""
    wanted = [name for name in (LIGHT, DARK) if f"cid:{name}" in html_body]
    if not wanted:
        return
    html_part = message.get_body(("html",))
    if html_part is None:
        return
    for name in wanted:
        html_part.add_related(_png(name), maintype="image", subtype="png", cid=f"<{name}>", filename=f"{name}.png",
                              disposition="inline")


__all__ = ["DARK", "LIGHT", "LOGO_HEIGHT", "LOGO_PAD", "LOGO_WIDTH", "attach"]
