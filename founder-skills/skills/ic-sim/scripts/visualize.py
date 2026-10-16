#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
Generate the self-contained IC simulation report page from the simulation's JSON artifacts.

The page is built on the shared page components (`_ui.py`): a header card with the committee's verdict and
conviction score, the key findings, the context supplied with the request (when there is any), the debate,
all 28 dimensions grouped by category with filters, the category radar, the fund profile the partners argued
from and the conflict check. The verdict and score wording is `_ic_view`'s and the fund lines are
`fund_profile.founder_lines`, so the page and report.md state them the same way.

Outputs HTML (not JSON). See compose_report.py for JSON output.

Usage:
    python visualize.py --dir ./ic-sim-acme-corp/
    python visualize.py --dir ./ic-sim-acme-corp/ -o report.html

Output: Raw HTML to stdout (or file with -o).
"""

from __future__ import annotations

import argparse
import html
import json
import math
import os
import sys
from types import ModuleType
from typing import Any, TypeGuard

# The shared page components and the IC wording owner, same-dir imports (each skill carries its own copy).
if os.path.dirname(os.path.abspath(__file__)) not in sys.path:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ic_view  # noqa: E402
import _ui  # noqa: E402

# ---------------------------------------------------------------------------
# Artifact loading infrastructure
# ---------------------------------------------------------------------------

_CORRUPT: dict[str, Any] = {"__corrupt__": True}

REQUIRED_ARTIFACTS = [
    "startup_profile.json",
    "fund_profile.json",
    "conflict_check.json",
    "discussion.json",
    "score_dimensions.json",
]

OPTIONAL_ARTIFACTS = [
    "prior_artifacts.json",
    "partner_assessment_visionary.json",
    "partner_assessment_operator.json",
    "partner_assessment_analyst.json",
]


# Optional artifacts another run wrote, in a folder that belongs to a run: read as absent (`main` sets this from
# `_run_ref.foreign_artifacts` when given --run-id; empty for a folder with no ref, and in-process callers).
_IGNORED_OTHER_RUN: set[str] = set()


def _load_artifact(dir_path: str, name: str) -> dict[str, Any] | None:
    """Load a JSON artifact. Returns None if missing, _CORRUPT if unparseable."""
    if name in _IGNORED_OTHER_RUN:
        return None
    path = os.path.join(dir_path, name)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)  # type: ignore[no-any-return]
    except (json.JSONDecodeError, OSError):
        return _CORRUPT


def _is_stub(data: dict[str, Any] | None) -> bool:
    """Check if artifact is a stub (intentionally skipped)."""
    return isinstance(data, dict) and data.get("skipped") is True


def _usable(data: dict[str, Any] | None) -> TypeGuard[dict[str, Any]]:
    """Check if artifact is loaded, not corrupt, and not a stub."""
    return data is not None and data is not _CORRUPT and not _is_stub(data)


def _as_list(value: Any) -> list[Any]:
    """Coerce to list -- returns [] if not a list."""
    return value if isinstance(value, list) else []


def _as_dict(value: Any) -> dict[str, Any]:
    """Coerce to dict -- returns {} if not a dict."""
    return value if isinstance(value, dict) else {}


# ---------------------------------------------------------------------------
# HTML safety helpers
# ---------------------------------------------------------------------------


def _esc(text: Any) -> str:
    """HTML-escape any value, safe for both text content and attributes."""
    return html.escape(str(text), quote=True)


def _num(value: Any, default: float = 0.0) -> float:
    """Coerce to finite float, returning default for non-numeric / non-finite."""
    try:
        result = float(value)
        if not math.isfinite(result):
            return default
        return result
    except (TypeError, ValueError):
        return default


class _Text:
    """The one rule for every string this page builds from an artifact: the founder-text policy first (with
    the keep-set report.md was substituted with), then HTML escaping. Escaping first would turn an `&` into
    `&amp;` before the policy reads it."""

    def __init__(self, keep: frozenset[str]) -> None:
        self.keep = keep

    def plain(self, text: Any) -> str:
        """The policy's words, not escaped (for a component that escapes its own strings)."""
        return _ui.founder_text(str(text), self.keep or None)

    def __call__(self, text: Any) -> str:
        return _esc(self.plain(text))


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_CANONICAL_CATEGORIES = [
    "Team",
    "Market",
    "Product",
    "Business Model",
    "Financials",
    "Risk",
    "Fund Fit",
]

_CANONICAL_PARTNERS = ["visionary", "operator", "analyst"]

# A dimension's status as a checklist tone and as the word the row shows. A tone groups statuses (both
# "to confirm" and "not applicable" are not scored), so the word is what tells them apart.
_STATUS_TONE: dict[str, str] = {
    "strong_conviction": "pass",
    "moderate_conviction": "neutral",
    "concern": "warn",
    "dealbreaker": "fail",
    "to_confirm": "na",
    "not_applicable": "na",
}
_STATUS_WORD: dict[str, str] = {
    "strong_conviction": "Strong",
    "moderate_conviction": "Moderate",
    "concern": "Concern",
    "dealbreaker": "Dealbreaker",
    "to_confirm": "To confirm",
    "not_applicable": "Not applicable",
}
_CHECKLIST_STATUSES = ("fail", "warn", "neutral", "pass", "na")
_CHIP_LABELS = {"fail": "Dealbreaker", "warn": "Concern", "neutral": "Moderate", "pass": "Strong", "na": "Not scored"}

# A partner's verdict as a pill tone (the word is `_ic_view.VERDICT_WORD`'s).
_VERDICT_TONE: dict[str, str] = {"invest": "pass", "more_diligence": "warn", "pass": "fail", "hard_pass": "fail"}

# A portfolio conflict's severity as a word and a pill tone: never colour alone.
_SEVERITY_WORD: dict[str, str] = {"clear": "Clear", "manageable": "Manageable", "blocking": "Blocking"}
_SEVERITY_TONE: dict[str, str] = {"clear": "pass", "manageable": "warn", "blocking": "fail"}


def _norm(value: Any) -> str:
    return str(value or "").strip().lower()


def _severity_word(severity: Any, text: _Text) -> str:
    key = _norm(severity)
    return _SEVERITY_WORD.get(key) or text.plain(str(severity or "?").strip()).title()


def _pill(tone: str, label_html: str, attrs: str = "") -> str:
    """A pill this page builds; its tone rides `data-tone` as well as the class, so it is read by meaning."""
    if tone in ("pass", "warn", "fail", "neutral"):
        return f'<span class="ui-pill ui-pill--{tone}" data-tone="{tone}"{attrs}>{label_html}</span>'
    return f'<span class="ui-pill"{attrs}>{label_html}</span>'


# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------


def _css() -> str:
    """This page's own styles, after `_ui.UI_CSS` (the shell, cards, ring and checklist)."""
    return """
        svg text { font-family: var(--font-body); }
        .ic-placeholder {
            text-align: center; color: var(--ui-ink-2); font-style: italic; margin: 0;
            padding: 2rem; background: var(--ui-surface-2); border-radius: var(--ui-r1);
        }
        .ic-oneliner { margin: var(--ui-s3) 0 0; color: var(--ui-ink-2); max-width: 68ch; }
        .ic-partners { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; margin: var(--ui-s3) 0 0; }
        .ic-partners .ui-pill { font-size: 0.8rem; padding: 3px 10px; }
        .ic-note { margin: var(--ui-s3) 0 0; font-size: 0.82rem; font-style: italic; color: var(--ui-ink-2); }
        .ic-debate { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: var(--ui-s3); }
        .ic-debate > .ui-card { margin-top: 0; box-shadow: none; padding: var(--ui-s4); }
        .ic-debate h3 { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; justify-content: space-between; }
        .ic-rationale { margin: var(--ui-s2) 0 0; font-size: 0.9rem; color: var(--ui-ink-2); }
        @media (max-width: 719px) { .ic-debate { grid-template-columns: 1fr; } }
        .ic-radar { margin: 0; }
        /* The radar fits its card at any width: its viewBox is drawn tight around the labels, so on a phone the
           whole chart shows, scaled, with nothing cut and nothing to scroll. */
        .ic-radar svg { display: block; width: 100%; max-width: 520px; height: auto; margin: 0 auto; }
        .ic-radar figcaption {
            margin-top: var(--ui-s2); font-size: 0.78rem; color: var(--ui-ink-2); text-align: center;
        }
        .ic-fund-line { margin: var(--ui-s2) 0 0; max-width: 75ch; }
        .ic-fund-name { margin: 0; font-weight: 600; font-size: 1rem; }
        .ic-context ul { margin: var(--ui-s3) 0 0; padding-left: 1.2rem; }
        .ic-context li { margin: 0.3rem 0; max-width: 75ch; }
        .ic-context p { margin: var(--ui-s2) 0 0; max-width: 75ch; }
        .ic-table-gap { margin-top: var(--ui-s4); }
    """


# ---------------------------------------------------------------------------
# Placeholder helper
# ---------------------------------------------------------------------------


def _placeholder(message: str) -> str:
    """Render a placeholder for missing/corrupt/stub data (`message` is plain text)."""
    return f'<p class="ic-placeholder">{_esc(message)}</p>'


def _artifact_placeholder(
    data: dict[str, Any] | None,
    artifact_name: str,
) -> str | None:
    """Return placeholder HTML if artifact is not usable, else None."""
    if data is None:
        return _placeholder(f"{artifact_name} not available")
    if data is _CORRUPT:
        return _placeholder("Data unavailable")
    if _is_stub(data):
        reason = data.get("reason", "Skipped")
        return _placeholder(f"{artifact_name} skipped: {reason}")
    return None


# ---------------------------------------------------------------------------
# Dealbreaker provenance
# ---------------------------------------------------------------------------


def _dealbreaker_provenance(discussion: dict[str, Any] | None) -> dict[str, list[str]] | None:
    """Map dimension id -> the archetypes that raised it as a dealbreaker in
    the debate. Returns None when discussion.json carries no id-level
    channel at all — that is NOT the same as "nothing was debated" and must
    not be rendered as such. Mirrors compose_report.py's
    _dealbreaker_provenance so the HTML and Markdown reports agree."""
    if not _usable(discussion):
        return None
    debated = discussion.get("debated_dealbreakers")
    if not isinstance(debated, list):
        return None
    out: dict[str, list[str]] = {}
    for entry in debated:
        if not isinstance(entry, dict):
            continue
        dimension = entry.get("dimension")
        if isinstance(dimension, str) and dimension:
            out[dimension] = [a for a in _as_list(entry.get("raised_by")) if isinstance(a, str)]
    return out


def _dealbreaker_provenance_suffix(db_id: str, provenance: dict[str, list[str]] | None) -> str:
    """Short founder-facing suffix distinguishing a dealbreaker two partners
    argued in the debate from one the scoring pass produced alone, or from
    the case where provenance can't be traced at all — the three cases
    compose_report.py's Markdown draws, condensed for a Key Findings bullet."""
    if provenance is None:
        return " (debate provenance unavailable)"
    if db_id in provenance:
        raised_by = provenance[db_id] or []
        who = ", ".join(a.title() for a in raised_by) if raised_by else "the debate"
        return f" (raised in debate by {who})"
    return " (scoring pass only — not raised in debate)"


# ---------------------------------------------------------------------------
# Key Findings
# ---------------------------------------------------------------------------

# (text, tone): a finding is one sentence, coloured by what it says.
_Finding = tuple[str, str]


def _key_findings(
    score_dims: dict[str, Any] | None,
    discussion: dict[str, Any] | None,
    conflict: dict[str, Any] | None,
    text: _Text,
) -> str:
    """The findings: what's strong, what needs attention, the top actions."""
    strong: list[_Finding] = []
    attention: list[_Finding] = []
    actions: list[_Finding] = []

    if _usable(score_dims):
        summary = _as_dict(score_dims.get("summary"))
        by_cat = _as_dict(summary.get("by_category"))

        # Strong categories: positive (>=1 strong) with no concerns/dealbreakers.
        # Only claim "all strong conviction" when no moderate convictions exist
        # either — otherwise the category is strong-leaning but mixed.
        for cat in _CANONICAL_CATEGORIES:
            counts = _as_dict(by_cat.get(cat))
            s = int(_num(counts.get("strong_conviction"), 0))
            m = int(_num(counts.get("moderate_conviction"), 0))
            c = int(_num(counts.get("concern"), 0))
            d = int(_num(counts.get("dealbreaker"), 0))
            if s > 0 and c == 0 and d == 0:
                if m == 0:
                    strong.append((f"{cat} scores all strong conviction", "pass"))
                else:
                    strong.append((f"{cat} leans strong with no concerns", "pass"))

        # Dealbreakers — labelled with debate provenance so a partner-argued
        # dealbreaker isn't presented identically to a scoring-pass-only one.
        provenance = _dealbreaker_provenance(discussion)
        for db in _as_list(summary.get("dealbreakers")):
            if isinstance(db, dict):
                label = str(db.get("label", db.get("id", "?")))
                cat = str(db.get("category", ""))
                db_id = str(db.get("id", ""))
                suffix = _dealbreaker_provenance_suffix(db_id, provenance)
                attention.append((f"Dealbreaker in {cat}: {label}{suffix}", "fail"))

        # Top concerns
        for tc in _as_list(summary.get("top_concerns")):
            if isinstance(tc, dict):
                label = str(tc.get("label", tc.get("id", "?")))
                cat = str(tc.get("category", ""))
                attention.append((f"Concern in {cat}: {label}", "warn"))

    if _usable(conflict):
        conf_summary = _as_dict(conflict.get("summary"))
        severity = _norm(conf_summary.get("overall_severity"))
        if severity == "clear":
            strong.append(("No portfolio conflicts found", "pass"))
        elif severity in ("manageable", "blocking"):
            count = int(_num(conf_summary.get("conflict_count"), 0))
            attention.append(
                (f"{count} portfolio conflict(s) — severity: {severity}", _SEVERITY_TONE.get(severity, "warn"))
            )

    if _usable(discussion):
        for req in _as_list(discussion.get("diligence_requirements")):
            if isinstance(req, str) and req.strip():
                actions.append((req.strip(), "action"))
        if not actions:
            for kc in _as_list(discussion.get("key_concerns")):
                if isinstance(kc, str) and kc.strip():
                    actions.append((kc.strip(), "action"))

    if not strong and not attention and not actions:
        return ""

    def _cards(items: list[_Finding]) -> str:
        return "".join(f'<div class="ui-finding ui-finding--{tone}">{text(s)}</div>' for s, tone in items)

    def _column(key: str, heading: str, items: list[_Finding]) -> str:
        # Show five; the rest behind a disclosure, so nothing report.md carries is dropped.
        head, tail = items[:5], items[5:]
        more = f'<details class="ui-more"><summary>{len(tail)} more</summary>{_cards(tail)}</details>' if tail else ""
        return f'<div class="ui-finding-col" data-findings="{key}"><h3>{heading}</h3>{_cards(head)}{more}</div>'

    parts: list[str] = []
    if strong:
        parts.append(_column("strong", "What's strong", strong))
    if attention:
        parts.append(_column("attention", "What needs attention", attention))
    if actions:
        parts.append(_column("actions", "Top actions", actions))
    return '<div class="ui-findings">' + "".join(parts) + "</div>"


# ---------------------------------------------------------------------------
# Header card
# ---------------------------------------------------------------------------


def _partner_verdicts(discussion: dict[str, Any] | None) -> list[tuple[str, dict[str, Any]]]:
    """(role, verdict entry) in the canonical order, then any other role alphabetically; an entry with no role is
    skipped. Roles are matched case-insensitively."""
    if not _usable(discussion):
        return []
    by_partner: dict[str, dict[str, Any]] = {}
    for pv in _as_list(discussion.get("partner_verdicts")):
        if isinstance(pv, dict):
            role = _norm(pv.get("partner"))
            if role:
                by_partner[role] = pv
    ordered = [p for p in _CANONICAL_PARTNERS if p in by_partner]
    ordered += sorted(set(by_partner) - set(_CANONICAL_PARTNERS))
    return [(p, by_partner[p]) for p in ordered]


def _partners_row(discussion: dict[str, Any] | None, text: _Text) -> str:
    """One pill per partner, "<Role>: <decision word>", as report.md's Partner Split states it."""
    pills = []
    for role, pv in _partner_verdicts(discussion):
        verdict = pv.get("verdict")
        word = text(_ic_view.verdict_word(verdict))
        pills.append(
            _pill(
                _VERDICT_TONE.get(_norm(verdict), "neutral"),
                f"{text(role.title())}: {word}",
                f' data-partner="{_esc(role)}"',
            )
        )
    if not pills:
        return ""
    return f'<p class="ic-partners" data-partners><span class="ui-eyebrow">Partners</span>{"".join(pills)}</p>'


def _score_ring(score_dims: dict[str, Any] | None, text: _Text) -> str:
    if not _usable(score_dims):
        return ""
    summary = _as_dict(score_dims.get("summary"))
    score = _ic_view.score_text(summary)
    word = text.plain(_ic_view.verdict_word(summary.get("verdict")))
    return _ui.score_ring(
        _num(summary.get("conviction_score"), 0.0),
        tone=_ic_view.ring_tone(summary),
        value_text=f"{score}%",
        label="Conviction score",
        aria_label=f"Conviction score {score} percent, {word}",
        href="#checklist",
    )


def _header(
    startup: dict[str, Any] | None,
    score_dims: dict[str, Any] | None,
    discussion: dict[str, Any] | None,
    text: _Text,
) -> str:
    company = str(startup.get("company_name", "Unknown")) if _usable(startup) else "IC Simulation Report"
    chips: list[str] = []
    body: list[str] = []
    if _usable(startup):
        chips += [
            _ui.stage_label(startup.get("stage")),
            str(startup.get("sector") or ""),
            str(startup.get("simulation_date") or ""),
        ]
        one_liner = str(startup.get("one_liner") or "")
        if one_liner:
            body.append(f'<p class="ic-oneliner">{text(one_liner)}</p>')
    meta_html = "".join(f'<span class="ui-chip">{text(c)}</span>' for c in chips if c)
    verdict_html = ""
    if _usable(score_dims):
        summary = _as_dict(score_dims.get("summary"))
        verdict_html = text(_ic_view.verdict_line(summary))
        note = _ic_view.thin_basis_note(summary)
        if note is not None:
            body.append(f'<p class="ui-callout ui-callout--warn" data-note="basis">{text(note)}</p>')
    else:
        body.append(_artifact_placeholder(score_dims, "Score dimensions") or "")
    body.append(_partners_row(discussion, text))
    body.append(
        '<p class="ic-note">AI-generated assessment: an AI simulation of a committee, not actual VC feedback.</p>'
    )
    return _ui.header_card(
        eyebrow="IC Simulation",
        title=company,
        meta_html=meta_html,
        verdict_html=verdict_html,
        body_html="".join(body),
        ring_html=_score_ring(score_dims, text),
    )


# ---------------------------------------------------------------------------
# The debate
# ---------------------------------------------------------------------------


def _debate(discussion: dict[str, Any] | None, text: _Text) -> str:
    ph = _artifact_placeholder(discussion, "Discussion")
    if ph is not None:
        return ph
    present = dict(_partner_verdicts(discussion))
    roles = list(_CANONICAL_PARTNERS) + sorted(set(present) - set(_CANONICAL_PARTNERS))
    cards: list[str] = []
    for role in roles:
        pv = present.get(role)
        if pv is None:
            cards.append(
                f'<article class="ui-card" data-partner="{_esc(role)}"><h3>{text(role.title())}'
                f"{_pill('neutral', 'No verdict')}</h3></article>"
            )
            continue
        verdict = pv.get("verdict")
        word = text(_ic_view.verdict_word(verdict))
        # Whole, as report.md shows it (the page breaks a long token rather than widening).
        rationale = str(pv.get("rationale") or "")
        rationale_html = f'<p class="ic-rationale">{text(rationale)}</p>' if rationale else ""
        cards.append(
            f'<article class="ui-card" data-partner="{_esc(role)}"><h3>{text(role.title())}'
            f"{_pill(_VERDICT_TONE.get(_norm(verdict), 'neutral'), word)}</h3>{rationale_html}</article>"
        )
    return (
        '<p class="ic-note">AI-simulated partner perspectives — not actual investor views</p>'
        f'<div class="ic-debate">{"".join(cards)}</div>'
    )


# ---------------------------------------------------------------------------
# Dimensions
# ---------------------------------------------------------------------------


def _dimensions(score_dims: dict[str, Any] | None, text: _Text) -> str:
    ph = _artifact_placeholder(score_dims, "Score dimensions")
    if ph is not None:
        return ph
    items = [i for i in _as_list(score_dims.get("items")) if isinstance(i, dict)]  # type: ignore[union-attr]
    by_cat: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        by_cat.setdefault(str(item.get("category") or "Other"), []).append(item)
    order = [c for c in _CANONICAL_CATEGORIES if c in by_cat] + sorted(set(by_cat) - set(_CANONICAL_CATEGORIES))
    groups: list[dict[str, Any]] = []
    for cat in order:
        rows = []
        for item in by_cat[cat]:
            status = _norm(item.get("status"))
            # The word is the closed set's, never model text: an unknown status is not scored (tone `na`).
            word = _STATUS_WORD.get(status, "Not scored")
            rows.append(
                {
                    "tone": _STATUS_TONE.get(status, "na"),
                    "status_label": word,
                    "title": text.plain(str(item.get("label") or item.get("id") or "?")),
                    "criterion": str(item.get("id") or ""),
                    "evidence": text.plain(str(item.get("evidence") or "")),
                }
            )
        n = len(rows)
        groups.append({"name": cat, "count_text": f"{n} dimension{'s' if n != 1 else ''}", "items": rows})
    return _ui.checklist(
        groups,
        summary_html="Dimensions are scored once by the committee as a whole, not per partner.",
        labels=_CHIP_LABELS,
        statuses=_CHECKLIST_STATUSES,
    )


# ---------------------------------------------------------------------------
# Category radar (7-point spider)
# ---------------------------------------------------------------------------


def _category_weighted_score(by_cat: dict[str, Any], cat: str) -> float:
    """Compute weighted score for a category: strong=1.0, moderate=0.5, others=0."""
    counts = _as_dict(by_cat.get(cat))
    strong = _num(counts.get("strong_conviction"), 0.0)
    moderate = _num(counts.get("moderate_conviction"), 0.0)
    concern = _num(counts.get("concern"), 0.0)
    db = _num(counts.get("dealbreaker"), 0.0)
    applicable = strong + moderate + concern + db
    if applicable <= 0:
        return 0.0
    weighted = strong * 1.0 + moderate * 0.5
    return round(weighted / applicable * 100.0, 2)


def _chart_category_radar(score_dims: dict[str, Any] | None) -> str:
    """The 7-point radar as a figure (the categories' strong-and-moderate share, 0-100)."""
    ph = _artifact_placeholder(score_dims, "Score dimensions")
    if ph is not None:
        return ph

    summary = _as_dict(score_dims.get("summary"))  # type: ignore[union-attr]
    by_cat = _as_dict(summary.get("by_category"))

    # Ordered categories with their scores; any unknown category appended alphabetically.
    categories = list(_CANONICAL_CATEGORIES)
    extra = sorted(set(by_cat.keys()) - set(categories))
    categories.extend(extra)

    scores = [_category_weighted_score(by_cat, cat) for cat in categories]
    n = len(categories)

    # SVG parameters: the viewBox is drawn tight around the longest labels ("Business Model", "Fund Fit"), so
    # the chart scales to a phone's width with its labels still about 10 px tall.
    view_w, view_h = 380, 262
    cx, cy = view_w / 2, 130.0
    max_r = 100.0

    svg_lines: list[str] = [
        f'<svg viewBox="0 0 {view_w} {view_h}" xmlns="http://www.w3.org/2000/svg" role="img" '
        'aria-label="Category radar: each category\'s share of strong and moderate conviction">'
    ]

    # Angle offset: start from top (-90 degrees)
    def _angle(i: int) -> float:
        return 2 * math.pi * i / n - math.pi / 2

    # Draw grid rings at 25%, 50%, 75%, 100%
    for pct in [0.25, 0.5, 0.75, 1.0]:
        ring_r = max_r * pct
        points = []
        for i in range(n):
            a = _angle(i)
            px = cx + ring_r * math.cos(a)
            py = cy + ring_r * math.sin(a)
            points.append(f"{px:.2f},{py:.2f}")
        svg_lines.append(f'<polygon points="{" ".join(points)}" fill="none" stroke="#D7DBE0" stroke-width="0.5"/>')

    # Draw axis lines
    for i in range(n):
        a = _angle(i)
        ex = cx + max_r * math.cos(a)
        ey = cy + max_r * math.sin(a)
        svg_lines.append(
            f'<line x1="{cx:.2f}" y1="{cy:.2f}" x2="{ex:.2f}" y2="{ey:.2f}" stroke="#D7DBE0" stroke-width="0.5"/>'
        )

    # Data polygon
    data_points: list[str] = []
    point_coords: list[tuple[float, float, float]] = []  # (px, py, score)
    for i in range(n):
        a = _angle(i)
        frac = _num(scores[i], 0.0) / 100.0
        frac = max(0.05, min(1.0, frac))  # 5% floor prevents center collapse
        px = cx + max_r * frac * math.cos(a)
        py = cy + max_r * frac * math.sin(a)
        data_points.append(f"{px:.2f},{py:.2f}")
        point_coords.append((px, py, scores[i]))

    svg_lines.append(
        f'<polygon points="{" ".join(data_points)}"'
        f' fill="#21A2E3" fill-opacity="0.2" stroke="#21A2E3" stroke-width="2"/>'
    )

    # Data points (dots)
    for i in range(n):
        px, py, _score_val = point_coords[i]
        svg_lines.append(f'<circle cx="{px:.2f}" cy="{py:.2f}" r="3" fill="#21A2E3"/>')

    # Labels
    for i in range(n):
        a = _angle(i)
        label_r = max_r + 12
        lx = cx + label_r * math.cos(a)
        ly = cy + label_r * math.sin(a)
        anchor = "middle"
        if math.cos(a) > 0.3:
            anchor = "start"
        elif math.cos(a) < -0.3:
            anchor = "end"
        score_str = f"{scores[i]:.0f}%"
        svg_lines.append(
            f'<text x="{lx:.2f}" y="{ly:.2f}" text-anchor="{anchor}"'
            f' font-size="12" fill="#5E6A78">'
            f"{_esc(categories[i])}</text>"
        )
        svg_lines.append(
            f'<text x="{lx:.2f}" y="{ly + 13:.2f}" text-anchor="{anchor}"'
            f' font-size="11" fill="#5E6A78">{_esc(score_str)}</text>'
        )

    svg_lines.append("</svg>")
    svg = "\n".join(svg_lines)
    return (
        f'<figure class="ic-radar" data-chart="radar">{svg}'
        "<figcaption>Each category's strong and moderate dimensions as a share of the scored ones. "
        "Values below 5% are drawn at 5% for readability.</figcaption></figure>"
    )


# ---------------------------------------------------------------------------
# Fund profile
# ---------------------------------------------------------------------------


def _fund(fund: dict[str, Any] | None, text: _Text) -> str:
    """The fund the partners argued from: its name, then `fund_profile.founder_lines` verbatim (the kind line
    first), the generic fund's note, and a table of thesis, check size and the partners' roles. From an
    archetype only its role's label and its focus areas are read, never anything that could name a person."""
    if fund is None or fund is _CORRUPT or _is_stub(fund):
        return _artifact_placeholder(fund, "Fund profile") or ""
    fp = _fund_profile_module()
    parts = [f'<p class="ic-fund-name">{text(fund.get("fund_name", "?"))}</p>']
    parts += [f'<p class="ic-fund-line" data-fund-line>{_esc(line)}</p>' for line in fp.founder_lines(fund)]
    note = fp.illustrative_note(fund)
    if note is not None:
        parts.append(
            f'<p class="ui-callout" data-note="illustrative"><strong>{_esc(note[0])}</strong> {_esc(note[1])}</p>'
        )
    rows: list[tuple[str, str]] = []
    thesis = [str(t) for t in _as_list(fund.get("thesis_areas"))]
    if thesis:
        rows.append(("Thesis areas", text(", ".join(thesis))))
    check = _ic_view.check_size_text(fund)
    if check is not None:
        rows.append(("Check size", text(check)))
    if rows:
        parts.append(
            '<div class="ui-table-wrap ic-table-gap"><table class="ui-table"><tbody>'
            + "".join(f'<tr><th scope="row">{k}</th><td>{v}</td></tr>' for k, v in rows)
            + "</tbody></table></div>"
        )
    partner_rows: list[str] = []
    for arch in _as_list(fund.get("archetypes")):
        if not isinstance(arch, dict):
            continue
        label = fp.ROLE_LABELS.get(str(arch.get("role", "")))
        if label is None:
            continue
        focus = ", ".join(str(a) for a in _as_list(arch.get("focus_areas")))
        partner_rows.append(f"<tr><td>{_esc(label)}</td><td>{text(focus)}</td></tr>")
    if partner_rows:
        parts.append(
            '<div class="ui-table-wrap ic-table-gap"><table class="ui-table">'
            '<thead><tr><th scope="col">Partner</th><th scope="col">Focus areas</th></tr></thead>'
            f"<tbody>{''.join(partner_rows)}</tbody></table></div>"
        )
    return "".join(parts)


# ---------------------------------------------------------------------------
# Conflicts
# ---------------------------------------------------------------------------


def _conflicts(conflict: dict[str, Any] | None, text: _Text) -> str:
    ph = _artifact_placeholder(conflict, "Conflict check")
    if ph is not None:
        return ph
    summary = _as_dict(conflict.get("summary"))  # type: ignore[union-attr]
    severity = summary.get("overall_severity", "unknown")
    overall = _pill(_SEVERITY_TONE.get(_norm(severity), "neutral"), _esc(_severity_word(severity, text)))
    facts = [f"Overall severity: {overall}"]
    if summary.get("total_checked") is not None:
        facts.append(f"{text(summary.get('total_checked'))} portfolio companies checked")
    if summary.get("conflict_count") is not None:
        facts.append(f"{text(summary.get('conflict_count'))} conflicts found")
    parts = [f'<p class="ic-oneliner" data-conflict-summary>{" · ".join(facts)}</p>']
    rows: list[str] = []
    for c in _as_list(conflict.get("conflicts")):  # type: ignore[union-attr]
        if not isinstance(c, dict):
            continue
        sev = c.get("severity", "?")
        sev_pill = _pill(_SEVERITY_TONE.get(_norm(sev), "neutral"), _esc(_severity_word(sev, text)), " data-severity")
        rows.append(
            f"<tr><td>{text(c.get('company', '?'))}</td><td>{text(str(c.get('type', '?')))}</td>"
            f"<td>{sev_pill}</td>"
            f"<td>{text(c.get('rationale') or c.get('detail') or '')}</td></tr>"
        )
    if rows:
        parts.append(
            '<div class="ui-table-wrap ic-table-gap"><table class="ui-table">'
            '<thead><tr><th scope="col">Company</th><th scope="col">Type</th><th scope="col">Severity</th>'
            '<th scope="col">Why</th></tr></thead>'
            f"<tbody>{''.join(rows)}</tbody></table></div>"
        )
    return "".join(parts)


# ---------------------------------------------------------------------------
# Context supplied with the request
# ---------------------------------------------------------------------------


def _host_context(startup: dict[str, Any] | None) -> str:
    """The context supplied with the request, verbatim (escaped, never reworded), in `host_context`'s words."""
    parts = _host_context_module().host_context_parts(startup if _usable(startup) else None)
    if parts is None:
        return ""
    intro, items, closing = parts
    out = [f'<p data-context-line="intro">{_esc(intro)}</p>']
    if items:
        out.append("<ul>" + "".join(f"<li data-context-item>{_esc(i)}</li>" for i in items) + "</ul>")
    out += [f'<p data-context-line="closing">{_esc(c)}</p>' for c in closing]
    return f'<div class="ic-context">{"".join(out)}</div>'


# ---------------------------------------------------------------------------
# Full HTML composition
# ---------------------------------------------------------------------------


def compose_html(dir_path: str) -> str:
    """Load artifacts and compose the full HTML document."""
    import _theme

    artifacts: dict[str, dict[str, Any] | None] = {}
    for name in REQUIRED_ARTIFACTS + OPTIONAL_ARTIFACTS:
        artifacts[name] = _load_artifact(dir_path, name)

    startup = artifacts.get("startup_profile.json")
    score_dims = artifacts.get("score_dimensions.json")
    discussion = artifacts.get("discussion.json")
    conflict = artifacts.get("conflict_check.json")
    fund = artifacts.get("fund_profile.json")

    # The keep-set report.md was substituted with (the tokens in the context supplied with the request), from
    # the same function, so the page leaves the same tokens alone.
    policy = _ui.founder_text_policy()
    keep = _host_context_module().keep_set(startup if _usable(startup) else None, policy.scan if policy else None)
    text = _Text(keep)

    header = _header(startup, score_dims, discussion, text)

    # (section id, heading, body, in the nav)
    sections: list[tuple[str, str, str, bool]] = []
    findings = _key_findings(score_dims, discussion, conflict, text)
    if findings:
        sections.append(("findings", "Key Findings", findings, False))
    context = _host_context(startup)
    if context:
        sections.append(("context", "Context Supplied With This Request", context, True))
    sections += [
        ("debate", "The Debate", _debate(discussion, text), True),
        ("checklist", "Dimensions", _dimensions(score_dims, text), True),
        ("radar", "Category Radar", f'<div class="ui-scroll">{_chart_category_radar(score_dims)}</div>', False),
        ("fund", "Fund Profile", _fund(fund, text), True),
        ("conflicts", "Conflict Check", _conflicts(conflict, text), True),
    ]
    nav_names = {
        "debate": "Debate",
        "checklist": "Dimensions",
        "fund": "Fund profile",
        "conflicts": "Conflicts",
        "context": "Context",
    }
    nav = (
        '<nav class="ui-nav" aria-label="Sections">'
        + "".join(f'<a href="#{sid}">{nav_names[sid]}</a>' for sid, _t, _b, in_nav in sections if in_nav)
        + "</nav>"
    )
    body = (
        header
        + nav
        + "".join(
            f'<section class="ui-section" id="{sid}" aria-labelledby="{sid}-h"><h2 id="{sid}-h">{_esc(title)}</h2>'
            f"{content}</section>"
            for sid, title, content, _nav in sections
        )
    )
    company = str(startup.get("company_name", "Report")) if _usable(startup) else ""
    return _ui.page_shell(
        title=f"IC Simulation: {company}" if company else "IC Simulation Report",
        body_html=body,
        brand_css=_theme.brand_css(),
        page_css=_css(),
        skill_name="IC Simulation",
    )


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------


def _write_output(data: str, output_path: str | None, *, summary: dict[str, Any] | None = None) -> None:
    """Write HTML string to file or stdout."""
    if output_path:
        abs_path = os.path.abspath(output_path)
        parent = os.path.dirname(abs_path)
        if parent == "/":
            print(
                f"Error: output path resolves to root directory: {output_path}",
                file=sys.stderr,
            )
            sys.exit(1)
        os.makedirs(parent, exist_ok=True)
        with open(abs_path, "w", encoding="utf-8") as f:
            f.write(data)
        receipt: dict[str, Any] = {"ok": True, "path": abs_path, "bytes": len(data.encode("utf-8"))}
        if summary:
            receipt.update(summary)
        sys.stdout.write(json.dumps(receipt, separators=(",", ":")) + "\n")
    else:
        sys.stdout.write(data)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _run_ref_module() -> ModuleType:
    """The sibling `_run_ref`, loaded only when `--run-id` is given."""
    scripts_dir = os.path.dirname(os.path.abspath(__file__))
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    import _run_ref

    return _run_ref


def _fund_profile_module() -> ModuleType:
    """The sibling `fund_profile`: its check of a profile that names people, and the fund lines it owns."""
    scripts_dir = os.path.dirname(os.path.abspath(__file__))
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    import fund_profile

    return fund_profile


def _host_context_module() -> ModuleType:
    """The sibling `host_context`, the one owner of the supplied context's wording and keep-set."""
    scripts_dir = os.path.dirname(os.path.abspath(__file__))
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    import host_context

    return host_context


def _own_run_id(dir_path: str) -> str | None:
    """This page's run id: the one the simulation's files agree on, read as compose reads it
    (`_ic_gates.run_id_of`), so a model-written profile alone never decides it."""
    _run_ref_module()
    import _ic_gates

    rid: str | None = _ic_gates.run_id_of(dir_path)
    return rid


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    p = argparse.ArgumentParser(description="Generate HTML visualization from IC simulation artifacts")
    p.add_argument(
        "-d",
        "--dir",
        required=True,
        help="Directory containing JSON artifacts",
    )
    p.add_argument(
        "--pretty",
        action="store_true",
        help="Accepted for compatibility (no-op)",
    )
    p.add_argument(
        "-o",
        "--output",
        help="Write HTML to file instead of stdout",
    )
    p.add_argument(
        "--run-id",
        default=None,
        help="Stamp the page with this run id (it must be the run id its artifacts carry) and, when the run "
        "has a gate ledger, list the page among the run's deliverables",
    )
    return p.parse_args()


def main() -> None:
    """Entry point."""
    args = parse_args()
    # FIRST: an output naming one of this step's own input files is refused before anything is written.
    import _out_guard

    _out_guard.refuse_output_onto_input(
        [args.output],
        script="visualize.py",
        extra=[
            os.path.join(args.dir, n)
            for n in (
                "startup_profile.json",
                "fund_profile.json",
                "conflict_check.json",
                "discussion.json",
                "score_dimensions.json",
                "prior_artifacts.json",
                "partner_assessment_visionary.json",
                "partner_assessment_operator.json",
                "partner_assessment_analyst.json",
            )
        ],
    )
    # In a folder that belongs to a run: only the folder's current run, and only its files on the page (the same
    # code compose gives for the same folder).
    if args.run_id:
        import _run_ref

        _run_ref.refuse_not_this_runs(
            args.dir,
            args.run_id,
            [
                os.path.join(args.dir, n)
                for n in (
                    "startup_profile.json",
                    "fund_profile.json",
                    "conflict_check.json",
                    "discussion.json",
                    "score_dimensions.json",
                    "partner_assessment_visionary.json",
                    "partner_assessment_operator.json",
                    "partner_assessment_analyst.json",
                )
            ],
            noun="simulation dir",
        )
        _IGNORED_OTHER_RUN.update(
            n
            for n, _r in _run_ref.foreign_artifacts(
                args.dir, args.run_id, [os.path.join(args.dir, n) for n in ("prior_artifacts.json",)]
            )
        )
        if _IGNORED_OTHER_RUN:
            print(
                f"Note: left out {', '.join(sorted(_IGNORED_OTHER_RUN))}: another run's file, not this run's",
                file=sys.stderr,
            )

    if not os.path.isdir(args.dir):
        print(f"Error: directory not found: {args.dir}", file=sys.stderr)
        sys.exit(1)

    # A profile that names people means the partner prose this page renders was written by sub-agents that saw
    # them: refuse before writing (this page has no run gate, so it also runs on a finished old folder).
    _fund_profile_module().refuse_profile_naming_people(args.dir, by="visualize.py")

    html_out = compose_html(args.dir)
    if args.run_id is not None:
        html_out = _run_ref_module().page_for_run(html_out, args.run_id, _own_run_id(args.dir))
    _write_output(html_out, args.output)
    if args.run_id is not None and args.output:
        _run_ref_module().list_page(args.dir, args.run_id, "report_html", args.output, "visualize.py")


if __name__ == "__main__":
    main()
