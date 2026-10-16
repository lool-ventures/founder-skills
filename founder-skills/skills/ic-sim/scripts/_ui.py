"""Shared page components for the founder-facing HTML pages.

Four components, two text helpers and two constants:

- ``page_shell``: the document around a page (language, phone viewport, a light colour scheme,
  one ``<main>``, the brand and UI styles, the footer credit and ``UI_JS``);
- ``header_card``: the card a page opens with (eyebrow, title, meta line, verdict, a score);
- ``score_ring``: a score as an SVG ring, its tone chosen by the caller;
- ``checklist``: criteria grouped by category, with filter chips that work without scripts;
- ``founder_text``: assessor-written text through the fleet's founder-text policy, when reachable;
- ``stage_label``: a funding-stage token (``series_a``, ``pre-seed``) as the words a founder reads;
- ``UI_CSS`` / ``UI_JS``: the styles and the one small script every page on the shell carries.

Everything else a page shows -- tiles, cards, the section nav, tables, pills, callouts -- is a CSS
class with a markup convention, written by the page itself:

    <div class="ui-tiles"><div class="ui-tile ui-tile--pass" data-tile="..."><p class="ui-tile__label">
        <p class="ui-tile__value"><p class="ui-tile__sub"></div></div>
    <nav class="ui-nav" aria-label="Sections"><a href="#id">Name</a>...</nav>
    <section class="ui-section" id="id"><h2>...</h2>...</section>
    <div class="ui-findings"><div class="ui-finding-col"><h3>...</h3>
        <div class="ui-finding ui-finding--fail">...</div>
        <details class="ui-more"><summary>N more</summary>(more findings)</details></div></div>
    <div class="ui-table-wrap"><table class="ui-table">...</table></div>
    <span class="ui-pill ui-pill--warn">...</span>
    <p class="ui-callout ui-callout--warn">...</p>
    <div class="ui-scroll">(a chart wider than a phone)</div>

Rules this module keeps, so the pages' own tests stay meaningful:

- No component reads an artifact, decides wording or decides a threshold. Callers pass the strings
  (escaped here) and the tones; markup a caller already built is passed as a ``*_html`` argument.
- ``UI_JS`` never names the page's embedded payload; it only opens and closes ``<details>``.
- Nothing here is dark-mode aware yet: pages state ``color-scheme: light`` until their charts are.

The plugin-root ``scripts/`` holds the canonical copy and each skill that renders with it carries an
identical one in its own ``scripts/`` (skill scripts run by path and cannot import across skill
directories, and on some surfaces the plugin root is not mounted at all); a test holds the copies equal.
The module imports nothing outside the standard library, so a copy works wherever its skill runs.
"""

from __future__ import annotations

import html
import importlib.util
import os
import re
from collections.abc import Mapping, Sequence
from types import ModuleType
from typing import Any

# The tones a checklist item may carry, and the statuses a page gets chips for when it names none. `neutral`
# is a status that is neither a problem nor a pass (a moderate result); only a page that names it offers it.
TONES = ("fail", "warn", "pass", "na", "neutral")
DEFAULT_STATUSES = ("fail", "warn", "pass", "na")
_GLYPH = {"fail": "✕", "warn": "!", "pass": "✓", "na": "–", "neutral": "•"}
_DEFAULT_LABELS = {"fail": "Fail", "warn": "Warn", "pass": "Pass", "na": "Not applicable", "neutral": "Neutral"}
_RING_TONES = ("pass", "warn", "fail", "neutral")
_EMPTY_CHIP = ' class="is-empty"'


def _esc(text: Any) -> str:
    return html.escape(str(text), quote=True)


# --- text helpers -----------------------------------------------------------------------------------

# Where the policy module sits relative to a copy of this file: beside the canonical copy (the
# plugin-root `scripts/`), three levels up from a skill's copy (`skills/<skill>/scripts/`).
_POLICY_NAME = "_founder_text.py"
_policy_cache: list[ModuleType | None] = []


def _policy_paths() -> list[str]:
    here = os.path.dirname(os.path.abspath(__file__))
    return [
        os.path.join(here, _POLICY_NAME),
        os.path.normpath(os.path.join(here, "..", "..", "..", "scripts", _POLICY_NAME)),
    ]


def founder_text_policy() -> ModuleType | None:
    """The fleet's founder-text policy module (`founder-skills/scripts/_founder_text.py`), or None.

    Loaded by path, never through `sys.path`, so loading it changes nothing else a page imports. A
    surface that mounts the skill without the plugin root (the claude.ai flat mount) has no such file:
    the caller then shows the assessor's text as written and the page still renders.
    """
    if not _policy_cache:
        mod: ModuleType | None = None
        for path in _policy_paths():
            if not os.path.isfile(path):
                continue
            try:
                spec = importlib.util.spec_from_file_location("_ui_founder_text_policy", path)
                if spec is None or spec.loader is None:
                    continue
                candidate = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(candidate)
            except (ImportError, OSError, SyntaxError):
                continue
            mod = candidate
            break
        _policy_cache.append(mod)
    return _policy_cache[0]


def founder_text(text: str, extra_keep: frozenset[str] | None = None) -> str:
    """`text` with internal tokens (snake_case enums and field names) rewritten by the founder-text
    policy, or `text` unchanged when the policy is not reachable. For text an assessor wrote and only
    the page shows; clean text comes back byte-for-byte. `extra_keep` names tokens left as written (the
    keep-set the skill's report.md was substituted with), so the page and the report agree."""
    if not text:
        return text
    ft = founder_text_policy()
    if ft is None:
        return text
    try:
        if extra_keep:
            return str(ft.substitute(text, extra_keep=extra_keep))
        return str(ft.substitute(text))
    except Exception:  # noqa: BLE001 - a policy failure must never stop a page rendering
        return text


def score_text(pct: Any, decimals: int | None = None) -> str:
    """A score for a ring or its spoken label, printed the way the skill's own report.md prints it, so
    the two never disagree. By default one decimal at most and no trailing zero (68.2, 21, 95.6), as
    the market-sizing report prints its self-check; `decimals` fixes the places instead (0 gives "21"
    for 20.6, as the financial-model-review report prints its checklist score)."""
    if decimals is not None:
        return f"{float(pct):.{decimals}f}"
    return f"{round(float(pct), 1):g}"


# Stage tokens whose words are not the token title-cased. Written both ways the fleet writes them
# (`pre_seed` in deck-review, `pre-seed` in financial-model-review); anything else is title-cased word
# by word, and "series" keeps a following one-letter round upper-case ("series-c" -> "Series C").
_STAGE_WORDS = {"pre seed": "Pre-seed", "preseed": "Pre-seed", "seed": "Seed", "growth": "Growth"}


def stage_label(token: Any) -> str:
    """A funding-stage token as the words a founder reads: "series_a" -> "Series A", "pre-seed" ->
    "Pre-seed". Empty in, empty out. Display only: a gate or a benchmark keeps the token."""
    raw = str(token or "").strip()
    if not raw:
        return ""
    words = re.sub(r"[\s_-]+", " ", raw).strip().lower()
    if words in _STAGE_WORDS:
        return _STAGE_WORDS[words]
    parts = words.split(" ")
    out: list[str] = []
    for i, w in enumerate(parts):
        if len(w) == 1 and i > 0 and parts[i - 1] == "series":
            out.append(w.upper())
        else:
            out.append(w[:1].upper() + w[1:])
    return " ".join(out)


UI_CSS = """\
:root {
  --ui-bg: #F4F6F9;
  --ui-surface: #FFFFFF;
  --ui-surface-2: #F1F4F7;
  --ui-ink: var(--lool-ink);
  --ui-ink-2: #5E6A78;
  --ui-line: #E2E7EE;
  --ui-accent: var(--lool-blue);
  --ui-accent-2: var(--lool-royal);
  --ui-accent-tint: #E8F0FA;
  --ui-on-accent: #FFFFFF;
  --st-pass: var(--lool-success);
  --st-pass-tint: var(--lool-success-tint);
  --st-pass-ink: #27744A;
  --st-warn: #8F5E12;
  --st-warn-bar: var(--lool-warning);
  --st-warn-tint: var(--lool-warning-tint);
  --st-fail: var(--lool-danger);
  --st-fail-tint: var(--lool-danger-tint);
  --st-na: #5F6B79;
  --st-na-bar: #C7CED7;
  --st-na-tint: #EEF1F5;
  --st-neutral-bar: #8E9BAB;
  --ui-s1: 4px; --ui-s2: 8px; --ui-s3: 12px; --ui-s4: 16px; --ui-s5: 24px; --ui-s6: 32px;
  --ui-r1: 10px; --ui-r2: 14px;
  --ui-shadow: 0 1px 2px rgba(16, 32, 64, 0.04), 0 6px 20px rgba(16, 32, 64, 0.06);
}
html { color-scheme: light; -webkit-text-size-adjust: 100%; }
*, *::before, *::after { box-sizing: border-box; }
body.ui-body {
  margin: 0; background: var(--ui-bg); color: var(--ui-ink);
  font-family: var(--font-body); font-size: 15px; line-height: 1.55;
  -webkit-font-smoothing: antialiased; -moz-osx-font-smoothing: grayscale;
  /* Text a model wrote can carry one long unbroken token (a URL); it breaks rather than widening the page. */
  overflow-wrap: anywhere;
}
.ui-page { max-width: 1120px; margin: 0 auto; padding: var(--ui-s6) var(--ui-s5) var(--ui-s5); }
.ui-page a { color: var(--ui-accent-2); }
.ui-page a:hover { color: var(--lool-blue-deep); }
.ui-footer {
  max-width: 1120px; margin: 0 auto; padding: var(--ui-s4) var(--ui-s5) var(--ui-s6);
  display: flex; flex-wrap: wrap; align-items: center; justify-content: center; gap: var(--ui-s2) var(--ui-s3);
  color: var(--ui-ink-2); font-size: 0.82rem;
}
.ui-footer a { color: var(--ui-accent-2); }
.ui-footer a.ui-feedback {
  display: inline-block; padding: 6px 14px; border-radius: var(--r-pill); font-weight: 600;
  background: var(--ui-accent); color: var(--ui-on-accent); text-decoration: none;
}
.ui-footer a.ui-feedback:hover { background: var(--lool-blue-deep); color: var(--ui-on-accent); }
.ui-footer a.ui-feedback:focus-visible { outline: 2px solid var(--ui-accent); outline-offset: 3px; }
:focus-visible { outline: 2px solid var(--ui-accent); outline-offset: 2px; }
.ui-page h2 {
  font-size: 1.15rem; font-weight: 600; letter-spacing: -0.01em; color: var(--ui-ink); margin: 0 0 var(--ui-s4);
}
.ui-page h3 { font-size: 0.95rem; font-weight: 600; color: var(--ui-ink); margin: 0 0 var(--ui-s2); }
.ui-eyebrow {
  margin: 0; font-size: 0.72rem; font-weight: 600; letter-spacing: 0.09em;
  text-transform: uppercase; color: var(--ui-ink-2);
}

/* Header card */
.ui-hero {
  display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: var(--ui-s5); align-items: center;
  background: var(--ui-surface); border: 1px solid var(--ui-line); border-radius: var(--ui-r2);
  padding: var(--ui-s5) var(--ui-s6); box-shadow: var(--ui-shadow);
  border-top: 4px solid var(--ui-accent);
}
.ui-hero__text { min-width: 0; }
.ui-hero h1 {
  margin: 0.15rem 0 0.35rem; font-size: clamp(1.45rem, 3.2vw, 2.1rem); line-height: 1.2;
  font-weight: 600; letter-spacing: -0.02em; color: var(--ui-accent);
}
.ui-hero__meta { margin: 0; display: flex; flex-wrap: wrap; gap: 6px; align-items: center;
  color: var(--ui-ink-2); font-size: 0.85rem; }
.ui-hero__verdict { margin: var(--ui-s4) 0 0; font-size: 1.05rem; line-height: 1.55; max-width: 68ch; }
.ui-hero__body > * { margin-top: var(--ui-s3); }
.ui-chip {
  display: inline-block; padding: 2px 10px; border-radius: var(--r-pill); font-size: 0.78rem;
  font-weight: 500; background: var(--ui-accent-tint); color: var(--ui-accent-2);
}
.ui-points { margin-top: var(--ui-s4); border-top: 1px solid var(--ui-line); padding-top: var(--ui-s3); }
.ui-points > summary { cursor: pointer; font-weight: 600; font-size: 0.9rem; color: var(--ui-ink); }
.ui-points ul { margin: var(--ui-s2) 0 0; padding-left: 1.2rem; }
.ui-points li { margin: 0.3rem 0; max-width: 75ch; }

/* Score ring */
.ui-ring-link { display: block; text-decoration: none; color: inherit; border-radius: var(--ui-r1); }
.ui-ring-link:hover .ui-ring__track { stroke: var(--ui-surface-2); }
.ui-ring { margin: 0; width: 136px; text-align: center; }
.ui-ring__dial { position: relative; }
.ui-ring svg { display: block; width: 100%; height: auto; }
.ui-ring__track { fill: none; stroke: var(--ui-line); stroke-width: 10; }
.ui-ring__value { fill: none; stroke: var(--ring); stroke-width: 10; stroke-linecap: round; }
.ui-ring--pass { --ring: var(--st-pass); }
.ui-ring--warn { --ring: var(--st-warn-bar); }
.ui-ring--fail { --ring: var(--st-fail); }
.ui-ring--neutral { --ring: var(--ui-accent); }
.ui-ring__num {
  position: absolute; inset: 0; display: grid; place-content: center;
  font-size: 1.75rem; font-weight: 700; letter-spacing: -0.02em; color: var(--ui-ink);
}
.ui-ring figcaption { margin-top: 6px; font-size: 0.8rem; line-height: 1.35; color: var(--ui-ink-2); }
.ui-ring figcaption strong { display: block; color: var(--ui-ink); font-weight: 600; }

/* Section nav */
.ui-nav {
  position: sticky; top: 0; z-index: 5; display: flex; flex-wrap: wrap; gap: 6px;
  margin: var(--ui-s4) calc(-1 * var(--ui-s2)) 0; padding: var(--ui-s2);
  background: rgba(244, 246, 249, 0.92); -webkit-backdrop-filter: blur(6px); backdrop-filter: blur(6px);
}
.ui-nav a {
  flex: none; padding: 6px 14px; border-radius: var(--r-pill); font-size: 0.85rem; font-weight: 500;
  color: var(--ui-ink-2); text-decoration: none; background: var(--ui-surface); border: 1px solid var(--ui-line);
}
.ui-nav a:hover { color: var(--ui-accent); border-color: var(--ui-accent); }

/* Sections and cards */
.ui-section, .ui-card {
  background: var(--ui-surface); border: 1px solid var(--ui-line); border-radius: var(--ui-r2);
  padding: var(--ui-s5); margin-top: var(--ui-s4); box-shadow: var(--ui-shadow); scroll-margin-top: 64px;
}
.ui-section > h2 { padding-bottom: var(--ui-s3); border-bottom: 1px solid var(--ui-line); }

/* Tiles */
.ui-tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: var(--ui-s3); }
.ui-tile {
  background: var(--ui-surface-2); border-radius: var(--ui-r1); padding: var(--ui-s4);
  border-left: 4px solid var(--tile, var(--ui-accent));
}
.ui-tile--pass { --tile: var(--st-pass); }
.ui-tile--warn { --tile: var(--st-warn-bar); }
.ui-tile--fail { --tile: var(--st-fail); }
.ui-tile__label { margin: 0; font-size: 0.72rem; font-weight: 600; letter-spacing: 0.08em;
  text-transform: uppercase; color: var(--ui-ink-2); }
.ui-tile__value { margin: 0.2rem 0; font-size: 1.65rem; font-weight: 700; letter-spacing: -0.02em;
  line-height: 1.2; color: var(--ui-ink); font-variant-numeric: tabular-nums; }
.ui-tile--pass .ui-tile__value { color: var(--st-pass-ink); }
.ui-tile--warn .ui-tile__value { color: var(--st-warn); }
.ui-tile--fail .ui-tile__value { color: var(--st-fail); }
.ui-tile__sub { margin: 0; font-size: 0.85rem; color: var(--ui-ink-2); line-height: 1.4; }

/* Callouts and findings */
.ui-callout {
  margin: var(--ui-s3) 0 0; padding: var(--ui-s3) var(--ui-s4); border-radius: var(--ui-r1);
  background: var(--ui-accent-tint); border-left: 4px solid var(--lool-azure); font-size: 0.9rem;
}
.ui-callout--warn { background: var(--st-warn-tint); border-left-color: var(--st-warn-bar); }
.ui-callout--fail { background: var(--st-fail-tint); border-left-color: var(--st-fail); }
.ui-findings { display: grid; grid-auto-flow: column; grid-auto-columns: minmax(0, 1fr); gap: var(--ui-s4); }
@media (max-width: 900px) { .ui-findings { grid-auto-flow: row; } }
.ui-finding {
  padding: var(--ui-s3) var(--ui-s4); margin-bottom: var(--ui-s2); border-radius: var(--ui-r1);
  background: var(--ui-surface-2); border-left: 4px solid var(--finding, var(--ui-line)); font-size: 0.9rem;
}
.ui-finding--pass { --finding: var(--st-pass); }
.ui-finding--warn { --finding: var(--st-warn-bar); }
.ui-finding--fail { --finding: var(--st-fail); }
.ui-finding--action { --finding: var(--lool-azure); }
.ui-finding__eyebrow { margin: 0 0 2px; font-size: 0.7rem; font-weight: 600; letter-spacing: 0.08em;
  text-transform: uppercase; color: var(--ui-ink-2); }
.ui-finding__title { margin: 0; font-weight: 600; }
.ui-finding__body { margin: 4px 0 0; color: var(--ui-ink-2); }
.ui-more > summary {
  cursor: pointer; margin: 0 0 var(--ui-s2); font-size: 0.85rem; font-weight: 600; color: var(--ui-accent-2);
}

/* Tables, pills, wide figures */
.ui-table-wrap, .ui-scroll { max-width: 100%; overflow-x: auto; -webkit-overflow-scrolling: touch; }
/* A figure cut by a narrow screen shows a soft shadow on the side that scrolls, drawn by the background
   alone (no script): the two "local" covers move with the content and hide each shadow at its own end. */
.ui-table-wrap, .ui-scroll {
  background:
    linear-gradient(to right, var(--ui-surface) 30%, rgba(255, 255, 255, 0)) left center / 40px 100% no-repeat local,
    linear-gradient(to left, var(--ui-surface) 30%, rgba(255, 255, 255, 0)) right center / 40px 100% no-repeat local,
    radial-gradient(farthest-side at 0 50%, rgba(16, 32, 64, 0.22), transparent)
      left center / 10px 100% no-repeat scroll,
    radial-gradient(farthest-side at 100% 50%, rgba(16, 32, 64, 0.22), transparent)
      right center / 10px 100% no-repeat scroll;
}
.ui-scroll svg { max-width: 100%; height: auto; }
.ui-table { width: 100%; border-collapse: collapse; font-size: 0.88rem; }
.ui-table th, .ui-table td { padding: 8px 12px; text-align: left; border-bottom: 1px solid var(--ui-line); }
.ui-table th { font-size: 0.72rem; font-weight: 600; letter-spacing: 0.06em; text-transform: uppercase;
  color: var(--ui-ink-2); }
.ui-pill { display: inline-block; padding: 1px 9px; border-radius: var(--r-pill); font-size: 0.75rem;
  font-weight: 600; background: var(--st-na-tint); color: var(--st-na); }
.ui-pill--pass { background: var(--st-pass-tint); color: var(--st-pass-ink); }
.ui-pill--warn { background: var(--st-warn-tint); color: var(--st-warn); }
.ui-pill--fail { background: var(--st-fail-tint); color: var(--st-fail); }
.ui-pill--neutral { background: var(--ui-surface-2); color: var(--ui-ink-2); }

/* Checklist: the radios are siblings that precede the chips and the groups, so CSS alone filters. */
.ui-ck__sum { margin: 0 0 var(--ui-s3); color: var(--ui-ink-2); font-size: 0.9rem; }
.ui-ck__r { position: absolute; width: 1px; height: 1px; margin: -1px; padding: 0; border: 0;
  overflow: hidden; clip-path: inset(50%); white-space: nowrap; }
.ui-ck__chips { display: flex; flex-wrap: wrap; gap: 6px; margin: 0 0 var(--ui-s4); }
.ui-ck__chips label {
  display: inline-flex; align-items: center; gap: 6px; padding: 5px 12px; cursor: pointer;
  border: 1px solid var(--ui-line); border-radius: var(--r-pill); background: var(--ui-surface);
  font-size: 0.85rem; font-weight: 500; color: var(--ui-ink); user-select: none;
}
.ui-ck__chips label:hover { border-color: var(--ui-accent); }
.ui-ck__chips label b { font-weight: 600; font-variant-numeric: tabular-nums; color: var(--ui-ink-2); }
.ui-ck__chips label.is-empty { opacity: 0.55; }
#ck-f-all:checked ~ .ui-ck__chips [for="ck-f-all"],
#ck-f-attn:checked ~ .ui-ck__chips [for="ck-f-attn"],
#ck-f-fail:checked ~ .ui-ck__chips [for="ck-f-fail"],
#ck-f-warn:checked ~ .ui-ck__chips [for="ck-f-warn"],
#ck-f-pass:checked ~ .ui-ck__chips [for="ck-f-pass"],
#ck-f-na:checked ~ .ui-ck__chips [for="ck-f-na"],
#ck-f-neutral:checked ~ .ui-ck__chips [for="ck-f-neutral"] {
  background: var(--ui-accent); border-color: var(--ui-accent); color: var(--ui-on-accent);
}
#ck-f-all:checked ~ .ui-ck__chips [for="ck-f-all"] b, #ck-f-attn:checked ~ .ui-ck__chips [for="ck-f-attn"] b,
#ck-f-fail:checked ~ .ui-ck__chips [for="ck-f-fail"] b, #ck-f-warn:checked ~ .ui-ck__chips [for="ck-f-warn"] b,
#ck-f-pass:checked ~ .ui-ck__chips [for="ck-f-pass"] b, #ck-f-na:checked ~ .ui-ck__chips [for="ck-f-na"] b,
#ck-f-neutral:checked ~ .ui-ck__chips [for="ck-f-neutral"] b {
  color: var(--ui-on-accent);
}
#ck-f-all:focus-visible ~ .ui-ck__chips [for="ck-f-all"],
#ck-f-attn:focus-visible ~ .ui-ck__chips [for="ck-f-attn"],
#ck-f-fail:focus-visible ~ .ui-ck__chips [for="ck-f-fail"],
#ck-f-warn:focus-visible ~ .ui-ck__chips [for="ck-f-warn"],
#ck-f-pass:focus-visible ~ .ui-ck__chips [for="ck-f-pass"],
#ck-f-na:focus-visible ~ .ui-ck__chips [for="ck-f-na"],
#ck-f-neutral:focus-visible ~ .ui-ck__chips [for="ck-f-neutral"] {
  outline: 2px solid var(--ui-accent); outline-offset: 2px;
}
#ck-f-attn:checked ~ .ui-ck__groups .ui-ck__item:not([data-status="fail"]):not([data-status="warn"]),
#ck-f-fail:checked ~ .ui-ck__groups .ui-ck__item:not([data-status="fail"]),
#ck-f-warn:checked ~ .ui-ck__groups .ui-ck__item:not([data-status="warn"]),
#ck-f-pass:checked ~ .ui-ck__groups .ui-ck__item:not([data-status="pass"]),
#ck-f-na:checked ~ .ui-ck__groups .ui-ck__item:not([data-status="na"]),
#ck-f-neutral:checked ~ .ui-ck__groups .ui-ck__item:not([data-status="neutral"]),
#ck-f-attn:checked ~ .ui-ck__groups .ui-ck__grp:not([data-has~="fail"]):not([data-has~="warn"]),
#ck-f-fail:checked ~ .ui-ck__groups .ui-ck__grp:not([data-has~="fail"]),
#ck-f-warn:checked ~ .ui-ck__groups .ui-ck__grp:not([data-has~="warn"]),
#ck-f-pass:checked ~ .ui-ck__groups .ui-ck__grp:not([data-has~="pass"]),
#ck-f-na:checked ~ .ui-ck__groups .ui-ck__grp:not([data-has~="na"]),
#ck-f-neutral:checked ~ .ui-ck__groups .ui-ck__grp:not([data-has~="neutral"]),
.ui-ck__r:not(#ck-f-all):checked ~ .ui-ck__groups .ui-ck__item[data-weight="0"] { display: none; }
.ui-ck__grp {
  border: 1px solid var(--ui-line); border-radius: var(--ui-r1); margin: 0 0 var(--ui-s2);
  background: var(--ui-surface); overflow: hidden;
}
.ui-ck__grp > summary {
  display: grid; grid-template-columns: 1rem minmax(0, 1fr) 160px 6.5rem; gap: var(--ui-s3);
  align-items: center; padding: var(--ui-s3) var(--ui-s4); cursor: pointer; list-style: none;
}
.ui-ck__grp > summary::-webkit-details-marker { display: none; }
.ui-ck__grp > summary::before {
  content: ""; width: 7px; height: 7px; border-right: 2px solid var(--ui-ink-2);
  border-bottom: 2px solid var(--ui-ink-2); transform: rotate(-45deg); transition: transform 0.15s;
}
.ui-ck__grp[open] > summary::before { transform: rotate(45deg); }
.ui-ck__grp > summary:hover { background: var(--ui-surface-2); }
.ui-ck__name { font-weight: 600; }
.ui-ck__flags { display: inline-flex; gap: 4px; margin-left: 8px; vertical-align: 1px; }
.ui-ck__bar { display: flex; height: 8px; border-radius: 4px; overflow: hidden; background: var(--ui-surface-2); }
.ui-ck__bar i { flex: var(--n) 1 0; }
.ui-ck__bar .p { background: var(--st-pass); }
.ui-ck__bar .w { background: var(--st-warn-bar); }
.ui-ck__bar .f { background: var(--st-fail); }
.ui-ck__bar .n { background: var(--st-na-bar); }
.ui-ck__bar .u { background: var(--st-neutral-bar); }
.ui-ck__cnt {
  font-size: 0.85rem; color: var(--ui-ink-2); font-variant-numeric: tabular-nums;
  white-space: nowrap; text-align: right;
}
.ui-ck__list { list-style: none; margin: 0; padding: 0; }
.ui-ck__item {
  display: grid; grid-template-columns: 1.6rem minmax(0, 1fr); column-gap: var(--ui-s3);
  padding: 10px var(--ui-s4); border-top: 1px solid var(--ui-line);
}
.ui-ck__item[data-status="fail"] { background: linear-gradient(90deg, var(--st-fail-tint), transparent 40%); }
.ui-ck__item[data-status="warn"] { background: linear-gradient(90deg, var(--st-warn-tint), transparent 40%); }
.ui-ck__title { font-weight: 600; font-size: 0.92rem; line-height: 1.4; align-self: center; }
.ui-ck__item[data-status="pass"] .ui-ck__title, .ui-ck__item[data-status="na"] .ui-ck__title { font-weight: 500; }
.ui-ck__word { margin-left: 8px; font-size: 0.75rem; font-weight: 600; color: var(--ui-ink-2); white-space: nowrap; }
.ui-ck__item[data-weight="0"] { background: none; }
.ui-ck__item[data-weight="0"] .ui-ck__title { font-weight: 500; color: var(--ui-ink-2); }
.ui-ck__item[data-weight="0"] .ui-st { background: var(--st-na-tint); color: var(--st-na); }
.ui-ck__item[data-weight="0"] .ui-ck__ev { font-style: italic; }
.ui-ck__ev { grid-column: 2; margin: 0.25rem 0 0; font-size: 0.86rem; line-height: 1.5;
  color: var(--ui-ink-2); max-width: 80ch; }
.ui-st {
  display: inline-grid; place-content: center; width: 1.45rem; height: 1.45rem; border-radius: 50%;
  font-size: 0.75rem; font-weight: 700; line-height: 1; align-self: start; margin-top: 1px;
}
.ui-st--fail { background: var(--st-fail); color: #FFFFFF; }
.ui-st--warn { background: var(--st-warn); color: #FFFFFF; }
.ui-st--pass { background: var(--st-pass-tint); color: var(--st-pass-ink); }
.ui-st--na { background: var(--st-na-tint); color: var(--st-na); }
.ui-st--neutral { background: var(--ui-surface-2); color: var(--ui-ink-2); }

@media (max-width: 640px) {
  .ui-page { padding: var(--ui-s4) var(--ui-s4) var(--ui-s4); }
  .ui-hero { grid-template-columns: 1fr; padding: var(--ui-s5) var(--ui-s4); gap: var(--ui-s4); }
  .ui-hero .ui-ring-link, .ui-hero > .ui-ring { justify-self: start; }
  .ui-ring { width: auto; display: flex; align-items: center; gap: var(--ui-s3); text-align: left; }
  .ui-ring__dial { width: 76px; flex: none; }
  .ui-ring__num { font-size: 0.98rem; letter-spacing: -0.03em; }
  .ui-ring figcaption { margin-top: 0; }
  .ui-section, .ui-card { padding: var(--ui-s4); }
  .ui-nav { position: static; }
  .ui-ck__grp > summary { grid-template-columns: 1rem minmax(0, 1fr) auto; row-gap: 6px; }
  .ui-ck__cnt { grid-column: 3; grid-row: 1; }
  .ui-ck__bar { grid-column: 2 / -1; grid-row: 2; }
  .ui-ck__item { padding: var(--ui-s3); column-gap: var(--ui-s2); }
}
@media (prefers-reduced-motion: reduce) { * { transition: none !important; } }
@media print {
  body.ui-body { background: #fff; }
  .ui-page { max-width: none; padding: 0; }
  .ui-nav, .ui-ck__chips, .ui-ck__r { display: none; }
  .ui-section, .ui-card, .ui-hero { box-shadow: none; break-inside: avoid-page; }
  .ui-ck__item { break-inside: avoid; }
  .ui-ck__groups .ui-ck__grp { display: block !important; }
  .ui-ck__groups .ui-ck__item { display: grid !important; }
  * { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
}
"""

# Opens and closes <details> only. The groups are rendered open, so a reader with scripts off (or a
# printout) sees every criterion; with scripts on, the groups with nothing to fix close on load.
UI_JS = """\
(function () {
  function hasOf(g) { return (g.getAttribute('data-has') || '').split(' '); }
  function groups() { return document.querySelectorAll('.ui-ck__grp'); }
  var all = groups();
  for (var i = 0; i < all.length; i++) {
    var h = hasOf(all[i]);
    if (h.indexOf('fail') < 0 && h.indexOf('warn') < 0) all[i].open = false;
  }
  var radios = document.querySelectorAll('input.ui-ck__r');
  for (var r = 0; r < radios.length; r++) {
    radios[r].addEventListener('change', function () {
      var want = this.id.replace('ck-f-', '');
      if (want === 'all') return;
      var gs = groups();
      for (var j = 0; j < gs.length; j++) {
        var has = hasOf(gs[j]);
        var hit = want === 'attn' ? (has.indexOf('fail') >= 0 || has.indexOf('warn') >= 0) : has.indexOf(want) >= 0;
        if (hit) gs[j].open = true;
      }
    });
  }
  function openTarget(id) {
    var el = id ? document.getElementById(id) : null;
    if (el && el.tagName === 'DETAILS') el.open = true;
  }
  document.addEventListener('click', function (e) {
    var a = e.target && e.target.closest ? e.target.closest('a[href^="#"]') : null;
    if (a) openTarget(a.getAttribute('href').slice(1));
  });
  window.addEventListener('hashchange', function () { openTarget(location.hash.slice(1)); });
  openTarget(location.hash.slice(1));
  var reopened = [];
  window.addEventListener('beforeprint', function () {
    var closed = document.querySelectorAll('details:not([open])');
    for (var k = 0; k < closed.length; k++) { closed[k].open = true; reopened.push(closed[k]); }
  });
  window.addEventListener('afterprint', function () {
    while (reopened.length) reopened.pop().open = false;
  });
})();
"""


# The credit links and the feedback link, as every page's footer has always carried them (the feedback
# href is `_theme.FOOTER_CREDIT_HTML`'s; a test holds the two equal).
REPO_URL = "https://github.com/lool-ventures/founder-skills"
LOOL_URL = "https://lool.vc"
FEEDBACK_URL = "https://github.com/lool-ventures/founder-skills/discussions/new?category=ideas-feedback"


def footer(skill_name: str) -> str:
    """The one footer line: the skill, the credit, and "Share feedback" as a button."""
    skill = f'<span>{_esc(skill_name)}</span><span aria-hidden="true">·</span>' if skill_name else ""
    return (
        '<footer class="ui-footer">'
        f"{skill}"
        f'<span><a href="{REPO_URL}">founder skills</a> by <a href="{LOOL_URL}">lool ventures</a></span>'
        '<span aria-hidden="true">·</span>'
        f'<a class="ui-feedback" href="{_esc(FEEDBACK_URL)}">Share feedback</a>'
        "</footer>"
    )


def page_shell(
    *,
    title: str,
    body_html: str,
    brand_css: str,
    page_css: str = "",
    head_html: str = "",
    skill_name: str,
    after_main_html: str = "",
    scripts_html: str = "",
) -> str:
    """The whole document. `brand_css` is the skill's `_theme.brand_css()` (fonts and brand tokens);
    `page_css` is the page's own styles, after ours. `head_html` and `scripts_html` are trusted markup
    (vendored scripts, the page's own script). `skill_name` opens the one footer line every page carries
    ("<skill> · founder skills by lool ventures · Share feedback"); no page writes a footer of its own."""
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '<meta charset="UTF-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
        '<meta name="color-scheme" content="light">\n'
        f"<title>{_esc(title)}</title>\n"
        f"{head_html}"
        f"<style>\n{brand_css}\n{UI_CSS}\n{page_css}\n</style>\n"
        "</head>\n"
        '<body class="ui-body">\n'
        f'<main class="ui-page">\n{body_html}\n</main>\n'
        f"{after_main_html}"
        f"{footer(skill_name)}\n"
        f"{scripts_html}"
        f"<script>\n{UI_JS}</script>\n"
        "</body>\n"
        "</html>\n"
    )


def header_card(
    *,
    eyebrow: str,
    title: str,
    meta_html: str = "",
    verdict_html: str = "",
    body_html: str = "",
    ring_html: str = "",
) -> str:
    """The card every page opens with. `meta_html`, `verdict_html` and `body_html` are trusted markup the
    caller built (chips, a verdict sentence, notes, talking points); `ring_html` is a `score_ring`."""
    meta = f'<p class="ui-hero__meta">{meta_html}</p>' if meta_html else ""
    verdict = f'<p class="ui-hero__verdict" data-verdict>{verdict_html}</p>' if verdict_html else ""
    body = f'<div class="ui-hero__body">{body_html}</div>' if body_html else ""
    return (
        '<header class="ui-hero" aria-labelledby="ui-hero-title">'
        '<div class="ui-hero__text">'
        f'<p class="ui-eyebrow">{_esc(eyebrow)}</p>'
        f'<h1 id="ui-hero-title">{_esc(title)}</h1>'
        f"{meta}{verdict}{body}"
        "</div>"
        f"{ring_html}"
        "</header>"
    )


def score_ring(
    pct: float | None,
    *,
    tone: str,
    value_text: str,
    label: str,
    caption: str = "",
    aria_label: str,
    href: str | None = None,
) -> str:
    """A score as a ring. `pct` (0-100, clamped) sets the arc; None draws the empty track. The caller
    owns every word and the tone (its own thresholds): `value_text` is printed in the middle, `label`
    and `caption` below, `aria_label` is what a screen reader says."""
    if tone not in _RING_TONES:
        raise ValueError(f"unknown ring tone {tone!r}")
    arc = ""
    if pct is not None:
        p = max(0.0, min(100.0, float(pct)))
        arc = (
            '<circle class="ui-ring__value" cx="60" cy="60" r="50" pathLength="100" '
            f'stroke-dasharray="{p:g} 100" transform="rotate(-90 60 60)"/>'
        )
    cap = f"<span>{_esc(caption)}</span>" if caption else ""
    fig = (
        f'<figure class="ui-ring ui-ring--{tone}" role="img" aria-label="{_esc(aria_label)}">'
        '<div class="ui-ring__dial">'
        '<svg viewBox="0 0 120 120" aria-hidden="true">'
        '<circle class="ui-ring__track" cx="60" cy="60" r="50"/>'
        f"{arc}</svg>"
        f'<span class="ui-ring__num" aria-hidden="true">{_esc(value_text)}</span>'
        "</div>"
        f'<figcaption aria-hidden="true"><strong>{_esc(label)}</strong>{cap}</figcaption>'
        "</figure>"
    )
    if href:
        return f'<a class="ui-ring-link" href="{_esc(href)}">{fig}</a>'
    return fig


def checklist(
    groups: Sequence[Mapping[str, Any]],
    *,
    summary_html: str = "",
    labels: Mapping[str, str] | None = None,
    statuses: Sequence[str] = DEFAULT_STATUSES,
) -> str:
    """Criteria grouped by category, with CSS-only filter chips.

    Each group: ``{"name": str, "count_text": str, "items": [item, ...]}``. Each item:
    ``{"tone": "fail"|"warn"|"pass"|"na"|"neutral", "title": str, "criterion": str}`` plus either
    ``"evidence"`` (plain text) or ``"evidence_html"`` (trusted markup). An unknown tone raises: an
    item must never render blank. `labels` overrides the status names (chip and glyph labels). An item
    may carry ``"status_label"``, the skill's own word for its status (a tone groups several of a
    skill's statuses): it is what the glyph says and is shown after the title, and the row carries it as
    ``data-status-word``; ``data-status`` stays the tone.

    An item marked ``"weightless": True`` is a criterion whose result already counts under another
    one: it is listed (muted, ``data-weight="0"``), but no chip, group bar, pill or ``data-has``
    counts it, so one result is never counted twice and its group neither opens nor filters for it; a
    filter other than All hides it. So every chip's count is the rows it shows: All counts every listed
    row (weightless ones included, since All shows them), each other chip only the rows that count.

    `statuses` names the statuses the skill's checklist can carry (`DEFAULT_STATUSES` when it names
    none, so `neutral` is offered only by a page that asks for it); only those get a chip, and the
    "Needs attention" chip appears only when both fail and warn exist (with one, it would repeat it).

    Every group renders `open` and carries `data-has` (the tones it holds), so the chips hide a group
    with nothing to show without `:has()`, and with scripts off every criterion is visible and prints.
    """
    names = dict(_DEFAULT_LABELS)
    if labels:
        names.update(labels)
    for s in statuses:
        if s not in TONES:
            raise ValueError(f"unknown checklist status {s!r}")
    counts = {t: 0 for t in TONES}
    weightless_n = 0
    group_html: list[str] = []
    for g in groups:
        items = list(g.get("items") or [])
        if not items:
            continue
        gcounts = {t: 0 for t in TONES}
        rows: list[str] = []
        for it in items:
            tone = it.get("tone")
            if tone not in TONES:
                raise ValueError(f"unknown checklist tone {tone!r}")
            weightless = bool(it.get("weightless"))
            if weightless:
                weightless_n += 1
            else:
                gcounts[tone] += 1
                counts[tone] += 1
            ev_html = it.get("evidence_html")
            if ev_html is None:
                ev = str(it.get("evidence") or "").strip()
                ev_html = _esc(ev) if ev else ""
            ev_p = f'<p class="ui-ck__ev">{ev_html}</p>' if ev_html else ""
            crit = str(it.get("criterion") or "")
            crit_attr = f' data-criterion="{_esc(crit)}"' if crit else ""
            if weightless:
                crit_attr += ' data-weight="0"'
            word = str(it.get("status_label") or "")
            word_html = f'<span class="ui-ck__word">{_esc(word)}</span>' if word else ""
            if word:
                crit_attr += f' data-status-word="{_esc(word)}"'
            rows.append(
                f'<li class="ui-ck__item" data-status="{tone}"{crit_attr}>'
                f'<span class="ui-st ui-st--{tone}" role="img" aria-label="{_esc(word or names[tone])}">'
                f"{_GLYPH[tone]}</span>"
                f'<span class="ui-ck__title">{_esc(it.get("title") or "")}{word_html}</span>'
                f"{ev_p}</li>"
            )
        has = " ".join(t for t in TONES if gcounts[t])
        bar = "".join(
            f'<i class="{cls}" style="--n:{gcounts[t]}"></i>'
            for t, cls in (("pass", "p"), ("neutral", "u"), ("warn", "w"), ("fail", "f"), ("na", "n"))
            if gcounts[t]
        )
        flags = "".join(
            f'<span class="ui-pill ui-pill--{t}">{gcounts[t]} {_esc(names[t].lower())}</span>'
            for t in ("fail", "warn")
            if gcounts[t]
        )
        flags_html = f'<span class="ui-ck__flags">{flags}</span>' if flags else ""
        group_html.append(
            f'<details class="ui-ck__grp" data-has="{has}" open>'
            "<summary>"
            f'<span class="ui-ck__name">{_esc(g.get("name") or "")}{flags_html}</span>'
            f'<span class="ui-ck__bar" aria-hidden="true">{bar}</span>'
            f'<span class="ui-ck__cnt">{_esc(g.get("count_text") or "")}</span>'
            "</summary>"
            f'<ul class="ui-ck__list">{"".join(rows)}</ul>'
            "</details>"
        )
    # All shows every row, a weightless one included, so it counts every row.
    total = sum(counts.values()) + weightless_n
    chips = [
        ("all", "All", total),
        ("attn", "Needs attention", counts["fail"] + counts["warn"]),
        ("fail", names["fail"], counts["fail"]),
        ("warn", names["warn"], counts["warn"]),
        ("neutral", names["neutral"], counts["neutral"]),
        ("pass", names["pass"], counts["pass"]),
        ("na", names["na"], counts["na"]),
    ]
    offered = set(statuses) | {"all"}
    if "fail" in offered and "warn" in offered:
        offered.add("attn")
    chips = [c for c in chips if c[0] in offered]
    radios = "".join(
        f'<input type="radio" name="ck-f" id="ck-f-{key}" class="ui-ck__r"{" checked" if key == "all" else ""}>'
        for key, _label, _n in chips
    )
    chip_labels = "".join(
        f'<label for="ck-f-{key}"{_EMPTY_CHIP if n == 0 else ""}>{_esc(label)} <b>{n}</b></label>'
        for key, label, n in chips
    )
    summary = f'<p class="ui-ck__sum">{summary_html}</p>' if summary_html else ""
    return (
        '<div class="ui-ck">'
        f"{summary}{radios}"
        f'<div class="ui-ck__chips" role="group" aria-label="Filter criteria">{chip_labels}</div>'
        f'<div class="ui-ck__groups">{"".join(group_html)}</div>'
        "</div>"
    )
