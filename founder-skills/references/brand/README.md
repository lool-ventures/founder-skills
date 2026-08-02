# Brand assets

Design tokens and webfont used by the HTML artifacts the skills generate
(`report.html`, `explorer.html`, `review.html`).

## Fonts

- `fonts/Sora-variable.woff2` — Sora variable font (`wght` 100–800), latin
  subset, from Google Fonts. Licensed under the
  [SIL Open Font License 1.1](fonts/OFL.txt) — the license text and copyright notice ship
  alongside the font in `fonts/OFL.txt`, as OFL 1.1 §2 requires of any redistribution.
  Generator scripts embed it base64-inline so artifacts stay self-contained
  (no CDN); when the file is absent, artifacts fall back to the system font
  stack.

## Tokens

The CSS custom properties (palette, type scale, radii, shadows) live in each
skill's `scripts/_theme.py`. Generated artifacts are white-surface, blue-accent
(`#0D549D` primary, `#21A2E3` azure), charcoal body text, square-cornered
blocks with hairline rules, and muted semantic status colors.
