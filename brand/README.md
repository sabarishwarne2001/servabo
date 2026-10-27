# Servabo brand

One place for what the app (`frontend/`) and the website (`website/`) share, so they look like one
company and cannot drift:

| File | What it is | Used by |
|---|---|---|
| `tokens.css` | The colour, surface and radius variables, light and dark (WCAG 2.1 AA) | `frontend/src/styles/index.css`, the website's global stylesheet |
| `tailwind-preset.js` | Tailwind's semantic colours, radii, type and elevation, reading `tokens.css` | `frontend/tailwind.config.js`, `website/tailwind.config.mjs` |
| `mark.ts` | The mark's and the wordmark's geometry (generated) | the app's `ServaboMark`, the website's logo |
| `tokens.json` | The name, its meaning, the positioning line and the brand colours as hex | the asset builder, the website |
| `assets/` | `servabo-mark.svg` (colour, on its tile), `servabo-mark-bare.svg` (colour, no tile, for a dark page), `servabo-mark-mono.svg` (one colour), `servabo-logo-{light,dark,mono}.svg`, `servabo-wordmark.svg` | press, documents, anyone who needs the logo |

**The mark.** A glossy ribbon "S" (cyan at the top, through brand blue, to violet) with a thin orbit
ring and a glowing dot, on a deep navy rounded tile. Servabo is Latin for "I will keep", from
*pacta sunt servanda*, agreements must be kept; the ring is the promise being kept in orbit around
your documents. Built on a 32-unit grid, it reads at 16 px. It carries its own colours and tile, so
it looks the same on a light or a dark page and under every tenant's colour scheme. In emails the
whole logo (mark and wordmark, light and dark) is a PNG carried inside the message
(`backend/app/templates/emails/assets/`, referred to as `cid:`), so mail clients show it without
loading anything from the web (N-199). **It is also the default workspace logo**: a workspace that has not uploaded a logo of
its own (every new workspace), or whose logo cannot be loaded, shows this mark, never initials.

**The wordmark.** Lowercase "servabo" in Inter (SIL Open Font License, the app's own typeface) at
weight 640, as outlines, so it looks the same everywhere without loading a font. The "o" carries a
small blue leaf. The tagline is "AUTOMATE • EXTRACT • ACCELERATE".

**Rebuilding.** The favicons, app icons and Open Graph cards in `frontend/public` and
`website/public`, and the email logo pictures, are generated, and committed so neither build needs these tools:

```bash
python -m venv /tmp/brand && /tmp/brand/bin/pip install fonttools brotli cairosvg pillow shapely svgpathtools
/tmp/brand/bin/python brand/scripts/build_brand_assets.py   # needs frontend/node_modules (Inter)
```
