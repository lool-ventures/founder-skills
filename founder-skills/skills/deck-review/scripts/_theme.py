"""Brand theme for generated HTML artifacts.

Provides the design-token CSS (palette, type, radii) and an offline
``@font-face`` rule with the Sora variable webfont embedded as base64, so
generated HTML stays self-contained (no CDN). The font file lives in
``references/brand/fonts/`` at the plugin root; when absent, artifacts
fall back to the system font stack.
"""

from __future__ import annotations

import base64
import os

_BRAND_FONT_PATH = os.path.normpath(
    os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..",
        "..",
        "..",
        "references",
        "brand",
        "fonts",
        "Sora-variable.woff2",
    )
)

# Palette and primitives: white surfaces, blue accents, charcoal text,
# square-cornered blocks with hairline rules, muted semantic status colors.
TOKENS_CSS = """\
:root {
  --lool-blue: #0D549D;
  --lool-blue-deep: #093F78;
  --lool-royal: #1B5FB2;
  --lool-azure: #21A2E3;
  --lool-azure-deep: #1488C8;
  --lool-sky: #48B4EA;
  --lool-slate: #374B65;
  --lool-slate-blue: #365A8A;

  --lool-white: #FFFFFF;
  --lool-paper: #FAFAFA;
  --lool-paper-2: #F1F4F4;
  --lool-line: #D7DBE0;
  --lool-line-2: #E5EEF8;
  --lool-line-form: #C0CFDD;

  --lool-ink: #333333;
  --lool-nav: #414042;
  --lool-mute: #777777;
  --lool-subtle: #7D90A3;
  --lool-faint: #A6AEB5;

  --lool-success: #2F8A56;
  --lool-success-tint: #EAF4EE;
  --lool-warning: #C9892B;
  --lool-warning-tint: #FAF3E5;
  --lool-danger: #C0392B;
  --lool-danger-tint: #FAECEA;

  --font-body: 'Sora', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto,
    Helvetica, Arial, sans-serif;
  --font-mono: 'SF Mono', 'Fira Code', 'Cascadia Code', ui-monospace, Menlo,
    monospace;

  --r-input: 4px;
  --r-pill: 50px;
  --shadow-soft: 0 8px 30px rgba(16, 32, 64, 0.08);
}
"""

# Subtle provenance line rendered at the bottom of each artifact.
FOOTER_CREDIT_HTML = (
    '<div class="footer-credit">founder-skills by lool ventures'
    ' &middot; <a href="https://github.com/lool-ventures/founder-skills/discussions/new?category=ideas-feedback"'
    ' style="color:inherit">Share feedback</a></div>'
)

FOOTER_CREDIT_CSS = """\
.footer-credit {
  font-size: 0.75rem; color: var(--lool-subtle);
  padding: 24px 32px 8px; letter-spacing: 0.02em;
}
"""


def font_face_css() -> str:
    """``@font-face`` rule with Sora embedded base64-inline.

    Returns an empty string when the font file is missing so the artifact
    degrades to the system stack instead of failing to generate.
    """
    if not os.path.isfile(_BRAND_FONT_PATH):
        return ""
    with open(_BRAND_FONT_PATH, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")
    return (
        "@font-face { font-family: 'Sora'; font-style: normal; "
        "font-weight: 100 800; font-display: swap; "
        f"src: url(data:font/woff2;base64,{b64}) format('woff2'); }}"
    )


def brand_css() -> str:
    """Font-face + token CSS, ready to inject at the top of a <style> block."""
    parts = [font_face_css(), TOKENS_CSS, FOOTER_CREDIT_CSS]
    return "\n".join(p for p in parts if p)
