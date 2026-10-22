#!/usr/bin/env python3
"""Build Servabo's brand assets: the mark, the wordmark, favicons, app icons and Open Graph cards.

    python -m venv /tmp/brand && /tmp/brand/bin/pip install fonttools brotli cairosvg pillow
    /tmp/brand/bin/python brand/scripts/build_brand_assets.py

The outputs are committed (brand/assets/, frontend/public/, website/public/), so neither the app
nor the website needs these tools to build. Re-run after changing the mark or the colours.

The mark: a glossy ribbon "S" (cyan at the top, through blue, to violet) with a thin orbit ring and
a glowing dot, on a deep navy rounded tile. It is drawn on a 32-unit grid so it stays legible at
16 px. The wordmark is lowercase "servabo" in Inter (SIL Open Font License, bundled with the app as
@fontsource-variable/inter) at weight 640, converted to outlines so it renders identically
everywhere, with no font to load; the "o" carries a small blue leaf. The tagline is
"AUTOMATE \u2022 EXTRACT \u2022 ACCELERATE".
"""

from __future__ import annotations

import io
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BRAND = ROOT / "brand"
ASSETS = BRAND / "assets"
TOKENS = json.loads((BRAND / "tokens.json").read_text(encoding="utf-8"))
INTER = ROOT / "frontend/node_modules/@fontsource-variable/inter/files/inter-latin-wght-normal.woff2"

BLUE = TOKENS["brandHex"]["primary"]          # the app's --primary (light), as hex
INK = TOKENS["brandHex"]["ink"]               # the app's --foreground (light)
PAPER = TOKENS["brandHex"]["paper"]           # the app's --foreground (dark)
NIGHT = TOKENS["brandHex"]["night"]           # the app's --background (dark)

# ---------------------------------------------------------------------------------------------
# The mark (32 x 32)
# ---------------------------------------------------------------------------------------------

#: The tile the mark sits on: a rounded square in deep navy (the mark is drawn for a dark ground).
TILE = "M8 0H24a8 8 0 0 1 8 8V24a8 8 0 0 1-8 8H8a8 8 0 0 1-8-8V8a8 8 0 0 1 8-8Z"
TILE_TOP, TILE_BOTTOM = "#0e2149", "#050c20"
#: The ribbon "S", one stroke with round ends.
S_STROKE = (
    "M21.6 10.6C20.3 9 18.4 8.2 16.1 8.2C12.7 8.2 10.4 9.9 10.4 12.6"
    "C10.4 15.5 13.2 16.2 16.1 16.8C19 17.4 21.8 18.3 21.8 21.2C21.8 23.8 19.4 25.6 16 25.6"
    "C13.5 25.6 11.5 24.6 10.2 22.9"
)
S_WIDTH = 4.4
#: Cyan at the top, through brand blue, to violet at the bottom.
RIBBON = (("0", "#2ee6f2"), ("0.5", "#3b82f6"), ("1", "#8b5cf6"))
#: The thin orbit ring around the S (centre, radii, tilt in degrees) and the glowing dot on it.
ORBIT = {"cx": 16.0, "cy": 16.6, "rx": 14.6, "ry": 5.6, "rot": -32.0}
ORBIT_WIDTH = 0.7
DOT_ANGLE = -35.0
DOT_R = 1.45


def dot_position() -> tuple[float, float]:
    """The glowing dot's place on the ring."""
    import math

    t, rot = math.radians(DOT_ANGLE), math.radians(ORBIT["rot"])
    x, y = ORBIT["rx"] * math.cos(t), ORBIT["ry"] * math.sin(t)
    return (ORBIT["cx"] + x * math.cos(rot) - y * math.sin(rot),
            ORBIT["cy"] + x * math.sin(rot) + y * math.cos(rot))


def s_outline() -> str:
    """The "S" stroke as a filled outline (round ends), for the one-colour mark.

    A mask would do the same in a browser, but mail clients, some favicon renderers and
    rasterisers ignore masks; a filled outline works everywhere.
    """
    from shapely.geometry import LineString
    from svgpathtools import parse_path

    path = parse_path(S_STROKE)
    points = [path.point(t / 400) for t in range(401)]
    line = LineString([(p.real, p.imag) for p in points])
    shape = line.buffer(S_WIDTH / 2, quad_segs=16, cap_style="round", join_style="round").simplify(0.01)
    coords = list(shape.exterior.coords)
    return "M" + "L".join(f"{x:.2f} {y:.2f}" for x, y in coords) + "Z"


def _ribbon_stops() -> str:
    return "".join(f'<stop offset="{o}" stop-color="{c}"/>' for o, c in RIBBON)


def mark_inner(uid: str = "sv", *, tile: bool = True) -> str:
    """The mark's drawing: tile (optional), ribbon S with a gloss line, orbit ring, glowing dot."""
    dx, dy = dot_position()
    o = ORBIT
    parts = [
        f'<defs><linearGradient id="{uid}-r" gradientUnits="userSpaceOnUse" x1="11" y1="8" x2="22" y2="26">'
        f"{_ribbon_stops()}</linearGradient>"
        f'<linearGradient id="{uid}-o" gradientUnits="userSpaceOnUse" x1="2" y1="22" x2="30" y2="10">'
        '<stop offset="0" stop-color="#8b5cf6" stop-opacity="0.15"/><stop offset="0.55" stop-color="#3b82f6"/>'
        '<stop offset="1" stop-color="#2ee6f2"/></linearGradient>'
        f'<linearGradient id="{uid}-t" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{TILE_TOP}"/>'
        f'<stop offset="1" stop-color="{TILE_BOTTOM}"/></linearGradient>'
        f'<radialGradient id="{uid}-g"><stop offset="0" stop-color="#7df3ff" stop-opacity="0.95"/>'
        '<stop offset="1" stop-color="#2ee6f2" stop-opacity="0"/></radialGradient></defs>'
    ]
    if tile:
        parts.append(f'<path d="{TILE}" fill="url(#{uid}-t)"/>')
    ring = (f'<ellipse cx="{o["cx"]}" cy="{o["cy"]}" rx="{o["rx"]}" ry="{o["ry"]}" '
            f'transform="rotate({o["rot"]} {o["cx"]} {o["cy"]})" fill="none" stroke="url(#{uid}-o)" '
            f'stroke-width="{ORBIT_WIDTH}"/>')
    parts.append(ring)
    parts.append(f'<path d="{S_STROKE}" fill="none" stroke="url(#{uid}-r)" stroke-width="{S_WIDTH}" '
                 'stroke-linecap="round" stroke-linejoin="round"/>')
    parts.append(f'<path d="{S_STROKE}" fill="none" stroke="#fff" stroke-opacity="0.38" stroke-width="0.9" '
                 'stroke-linecap="round" stroke-linejoin="round" transform="translate(-0.8 -0.9)"/>')
    parts.append(f'<circle cx="{dx:.2f}" cy="{dy:.2f}" r="{DOT_R * 2.3:.2f}" fill="url(#{uid}-g)"/>'
                 f'<circle cx="{dx:.2f}" cy="{dy:.2f}" r="{DOT_R}" fill="#fff"/>')
    return "".join(parts)


def mark_svg(*, tile: bool = True, title: str = "Servabo", uid: str = "sv") -> str:
    """The full-colour mark, on its navy tile (or bare, for use on a dark page)."""
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" role="img" '
        f'aria-label="{title}"><title>{title}</title>{mark_inner(uid, tile=tile)}</svg>\n'
    )


def mark_mono_svg(title: str = "Servabo") -> str:
    """One colour (currentColor): the S and the ring, no tile, no gradients."""
    o = ORBIT
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" role="img" '
        f'aria-label="{title}"><title>{title}</title>'
        f'<ellipse cx="{o["cx"]}" cy="{o["cy"]}" rx="{o["rx"]}" ry="{o["ry"]}" '
        f'transform="rotate({o["rot"]} {o["cx"]} {o["cy"]})" fill="none" stroke="currentColor" '
        f'stroke-width="{ORBIT_WIDTH}"/><path d="{s_outline()}" fill="currentColor"/></svg>\n'
    )


# ---------------------------------------------------------------------------------------------
# The wordmark: lowercase "servabo", the "o" carrying a small leaf
# ---------------------------------------------------------------------------------------------

WORD = "servabo"
TAGLINE = "AUTOMATE \u2022 EXTRACT \u2022 ACCELERATE"


def wordmark_paths(text: str = WORD, weight: float = 640, tracking_em: float = -0.012):
    return text_paths(text, weight=weight, tracking_em=tracking_em)


def text_paths(text: str, *, weight: float, tracking_em: float):
    """(svg path data in font units, advance width, units per em, cap height) for `text`."""
    d, width, upm, cap, _ = _text_layout(text, weight=weight, tracking_em=tracking_em)
    return d, width, upm, cap


def _text_layout(text: str, *, weight: float, tracking_em: float):
    from fontTools.pens.boundsPen import BoundsPen
    from fontTools.pens.svgPathPen import SVGPathPen
    from fontTools.pens.transformPen import TransformPen
    from fontTools.ttLib import TTFont
    from fontTools.varLib.instancer import instantiateVariableFont

    font = TTFont(io.BytesIO(INTER.read_bytes()))
    font = instantiateVariableFont(font, {"wght": weight}, inplace=False)
    upm = font["head"].unitsPerEm
    cmap = font.getBestCmap()
    glyphs = font.getGlyphSet()
    hmtx = font["hmtx"]
    x = 0.0
    parts = []
    boxes = []
    for ch in text:
        name = cmap[ord(ch)]
        pen = SVGPathPen(glyphs)
        glyphs[name].draw(TransformPen(pen, (1, 0, 0, -1, x, 0)))
        parts.append(pen.getCommands())
        bounds = BoundsPen(glyphs)
        glyphs[name].draw(bounds)
        b = bounds.bounds
        boxes.append((ch, x, b))
        x += hmtx[name][0] + tracking_em * upm
    width = x - tracking_em * upm
    return " ".join(parts), width, upm, font["OS/2"].sCapHeight, boxes


def wordmark_leaf() -> str:
    """The small leaf on the "o" (font units, y down, baseline at 0): a pointed oval leaning up-right."""
    d, width, upm, cap, boxes = _text_layout(WORD, weight=640, tracking_em=-0.012)
    ch, x0, (xmin, ymin, xmax, ymax) = boxes[-1]
    assert ch == "o"
    cx = x0 + xmax - (xmax - xmin) * 0.20
    cy = -ymax - 70
    length, half = 300, 80
    # A leaf: two arcs meeting at points, long axis rotated 40 degrees from horizontal.
    import math

    a = math.radians(-40)
    ux, uy = math.cos(a), math.sin(a)
    vx, vy = -uy, ux
    p0 = (cx - ux * length / 2, cy - uy * length / 2)
    p1 = (cx + ux * length / 2, cy + uy * length / 2)
    c1 = (cx + vx * half * 1.6, cy + vy * half * 1.6)
    c2 = (cx - vx * half * 1.6, cy - vy * half * 1.6)
    return (f"M{p0[0]:.0f} {p0[1]:.0f}Q{c1[0]:.0f} {c1[1]:.0f} {p1[0]:.0f} {p1[1]:.0f}"
            f"Q{c2[0]:.0f} {c2[1]:.0f} {p0[0]:.0f} {p0[1]:.0f}Z")


def logo_svg(*, text: str, title: str = "Servabo", uid: str = "sv") -> str:
    """Mark + wordmark on one line. Height 32 units; the wordmark's x-height sits on the S's baseline."""
    d, width, upm, cap = wordmark_paths()
    scale = 15.6 / cap
    gap = 9.0
    baseline = 24.6
    total = 32 + gap + width * scale + 1.5      # room for the leaf, which overhangs the last letter
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {total:.2f} 32" role="img" '
        f'aria-label="{title}"><title>{title}</title>{mark_inner(uid)}'
        f'<g transform="translate({32 + gap:.2f} {baseline}) scale({scale:.6f})">'
        f'<path fill="{text}" d="{d}"/><path fill="#2f8cff" d="{wordmark_leaf()}"/></g></svg>\n'
    )


def wordmark_only_svg(*, text: str, title: str = "Servabo") -> str:
    d, width, upm, cap = wordmark_paths()
    scale = 15.6 / cap
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 -17 {width * scale + 1.5:.2f} 22" role="img" '
        f'aria-label="{title}"><title>{title}</title><g transform="scale({scale:.6f})">'
        f'<path fill="{text}" d="{d}"/><path fill="#2f8cff" d="{wordmark_leaf()}"/></g></svg>\n'
    )


# ---------------------------------------------------------------------------------------------
# Raster outputs
# ---------------------------------------------------------------------------------------------


def png(svg: str, size: int, path: Path, *, width: int | None = None, height: int | None = None) -> None:
    import cairosvg

    path.parent.mkdir(parents=True, exist_ok=True)
    cairosvg.svg2png(bytestring=svg.encode(), write_to=str(path),
                     output_width=width or size, output_height=height or size)


def og_card(path: Path, *, dark: bool, headline: str, sub: str) -> None:
    """A 1200 x 630 Open Graph card: the logo, one headline and one line under it."""
    d, width, upm, cap = wordmark_paths()
    bg, fg, muted = (NIGHT, PAPER, "#a1a1aa") if dark else ("#f4f4f5", INK, "#52525b")
    scale = 44 / cap
    lines = _wrap(headline, 34)
    head = ""
    for i, line in enumerate(lines):
        ld, _, lupm, _ = text_paths(line, weight=700, tracking_em=-0.022)
        head += (f'<path transform="translate(96 {318 + i * 74}) scale({62 / lupm:.6f})" fill="{fg}" '
                 f'd="{ld}"/>')
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="630" viewBox="0 0 1200 630">'
        f'<rect width="1200" height="630" fill="{bg}"/>'
        f'<rect x="0" y="0" width="1200" height="8" fill="{BLUE}"/>'
        f'<g transform="translate(96 96) scale(2.6)">{mark_inner("og")}</g>'
        f'<g transform="translate({96 + 32 * 2.6 + 26} {96 + 24.6 * 2.6}) scale({scale:.6f})">'
        f'<path fill="{fg}" d="{d}"/><path fill="#2f8cff" d="{wordmark_leaf()}"/></g>'
        f"{head}"
        f'<path transform="translate(96 {318 + len(lines) * 74 + 40}) scale({30 / upm:.6f})" fill="{muted}" '
        f'd="{text_paths(sub, weight=450, tracking_em=0)[0]}"/>'
        "</svg>"
    )
    png(svg, 0, path, width=1200, height=630)


def _wrap(text: str, width: int) -> list[str]:
    words, lines, line = text.split(), [], ""
    for word in words:
        if len(line) + len(word) + 1 > width and line:
            lines.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    return lines + [line]


def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    print("wrote", path.relative_to(ROOT))


def main() -> None:
    mark = mark_svg()
    write(ASSETS / "servabo-mark.svg", mark)
    write(ASSETS / "servabo-mark-bare.svg", mark_svg(tile=False))
    write(ASSETS / "servabo-mark-mono.svg", mark_mono_svg())
    write(ASSETS / "servabo-logo-light.svg", logo_svg(text=INK))
    write(ASSETS / "servabo-logo-dark.svg", logo_svg(text=PAPER))
    write(ASSETS / "servabo-logo-mono.svg", logo_svg(text="currentColor"))
    write(ASSETS / "servabo-wordmark.svg", wordmark_only_svg(text="currentColor"))
    d, width, upm, cap = wordmark_paths()

    write(BRAND / "mark.ts", (
        "// Generated by brand/scripts/build_brand_assets.py: the Servabo mark and wordmark geometry.\n"
        "// Shared by the app (components/branding/ServaboMark.tsx) and the website. Do not edit.\n\n"
        "/** The navy tile the mark sits on (32 x 32 grid) and its two gradient colours. */\n"
        f"export const TILE = {json.dumps(TILE)};\n"
        f"export const TILE_COLOURS = {json.dumps([TILE_TOP, TILE_BOTTOM])} as const;\n"
        f"/** The ribbon S as one stroke, drawn {S_WIDTH} units wide with round ends. */\n"
        f"export const S_STROKE = {json.dumps(S_STROKE)};\n"
        f"export const S_WIDTH = {S_WIDTH};\n"
        "/** The ribbon's gradient stops (cyan, blue, violet), top to bottom. */\n"
        f"export const RIBBON_STOPS = {json.dumps([list(x) for x in RIBBON])} as const;\n"
        "/** The thin orbit ring: centre, radii, tilt in degrees, line width. */\n"
        f"export const ORBIT = {json.dumps({**ORBIT, 'width': ORBIT_WIDTH})};\n"
        "/** The glowing dot on the ring. */\n"
        f"export const DOT = {json.dumps({'x': round(dot_position()[0], 2), 'y': round(dot_position()[1], 2), 'r': DOT_R})};\n"
        "/** The S as a filled outline, for the one-colour mark. */\n"
        f"export const S_OUTLINE = {json.dumps(s_outline())};\n"
        f"/** \"servabo\" in Inter 640 as outlines: font units, baseline at y=0, cap height {cap}; LEAF is the small leaf on the o. */\n"
        f"export const WORDMARK = {{ d: {json.dumps(d)}, leaf: {json.dumps(wordmark_leaf())}, width: {width:.1f}, capHeight: {cap} }};\n"
        f"export const TAGLINE = {json.dumps(TAGLINE, ensure_ascii=False)};\n"
    ))
    for public in (ROOT / "frontend/public", ROOT / "website/public"):
        write(public / "favicon.svg", mark)
        png(mark, 32, public / "favicon-32.png")
        png(mark, 16, public / "favicon-16.png")
        png(mark, 180, public / "apple-touch-icon.png")
        png(mark, 192, public / "icon-192.png")
        png(mark, 512, public / "icon-512.png")

    # The browser tests upload a real PNG as a sample image document and as an organization logo.
    png(mark, 256, ROOT / "frontend/e2e/support/servabo-mark.png")

    headline = TOKENS["positioning"]
    for dark in (False, True):
        suffix = "dark" if dark else "light"
        og_card(ROOT / f"website/public/og/servabo-{suffix}.png", dark=dark, headline=headline,
                sub="Online software, available immediately after sign-up")
    og_card(ROOT / "frontend/public/og-servabo.png", dark=False, headline=headline, sub="app.servabo.app")


if __name__ == "__main__":
    main()
