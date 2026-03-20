#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
Generate self-contained HTML visualization from competitive positioning artifacts.

Outputs HTML (not JSON). See compose_report.py for JSON output.

Usage:
    python visualize.py --dir ./competitive-positioning-secureflow/
    python visualize.py --dir ./competitive-positioning-secureflow/ -o report.html

Output: Raw HTML to stdout (or file with -o).
"""

from __future__ import annotations

import argparse
import html
import json
import math
import os
import sys
from typing import Any, TypeGuard

# ---------------------------------------------------------------------------
# Artifact loading infrastructure
# ---------------------------------------------------------------------------

_CORRUPT: dict[str, Any] = {"__corrupt__": True}

REQUIRED_ARTIFACTS = [
    "landscape.json",
    "positioning.json",
    "moat_scores.json",
    "positioning_scores.json",
]

OPTIONAL_ARTIFACTS = [
    "report.json",
]


def _load_artifact(dir_path: str, name: str) -> dict[str, Any] | None:
    """Load a JSON artifact. Returns None if missing, _CORRUPT if unparseable."""
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


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_CANONICAL_MOAT_DIMS = [
    "network_effects",
    "data_advantages",
    "switching_costs",
    "regulatory_barriers",
    "cost_structure",
    "brand_reputation",
]

_MOAT_DIM_LABELS: dict[str, str] = {
    "network_effects": "Network Effects",
    "data_advantages": "Data Advantages",
    "switching_costs": "Switching Costs",
    "regulatory_barriers": "Regulatory Barriers",
    "cost_structure": "Cost Structure",
    "brand_reputation": "Brand Reputation",
}


def _humanize(value: str) -> str:
    """Convert machine IDs to human-readable labels."""
    _LABELS: dict[str, str] = {
        # research_depth
        "full": "Full",
        "partial": "Partial",
        "founder_provided": "Founder Provided",
        # evidence_source
        "researched": "Researched",
        "agent_estimate": "Agent Estimate",
        "founder_override": "Founder Override",
        # categories
        "direct": "Direct",
        "adjacent": "Adjacent",
        "do_nothing": "Do Nothing",
        "emerging": "Emerging",
        "custom": "Custom",
        # trajectories
        "building": "Building",
        "stable": "Stable",
        "eroding": "Eroding",
        # statuses
        "strong": "Strong",
        "moderate": "Moderate",
        "weak": "Weak",
        "absent": "Absent",
        "not_applicable": "N/A",
        # defensibility
        "high": "High",
        "low": "Low",
    }
    return _LABELS.get(value, value.replace("_", " ").title() if value else "?")


_STATUS_SCORE: dict[str, float] = {
    "strong": 1.0,
    "moderate": 0.66,
    "weak": 0.33,
    "absent": 0.0,
    "not_applicable": 0.0,
}

_DEFENSIBILITY_COLORS: dict[str, str] = {
    "high": "#10b981",
    "moderate": "#f59e0b",
    "low": "#ef4444",
}

_TRAJECTORY_ARROWS: dict[str, str] = {
    "building": "\u2191",  # up arrow
    "stable": "\u2192",  # right arrow
    "eroding": "\u2193",  # down arrow
}

_CLR_PRIMARY = "#0d549d"
_CLR_ACCENT = "#21a2e3"
_CLR_STARTUP = "#e11d48"  # distinct rose/red for startup


# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------


def _css() -> str:
    """Return the full CSS block for the report."""
    return """
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
                         "Helvetica Neue", Arial, sans-serif;
            background: #f9fafb; color: #1f2937; line-height: 1.6;
            padding: 2rem; max-width: 1100px; margin: 0 auto;
        }
        h1 { color: #0d549d; font-size: 1.8rem; margin-bottom: 0.25rem; }
        h2 {
            color: #0d549d; font-size: 1.2rem; margin: 2rem 0 1rem;
            border-bottom: 1px solid #e5e7eb; padding-bottom: 0.5rem;
        }
        .subtitle { color: #6b7280; font-size: 0.9rem; margin-bottom: 0.5rem; }
        .chart-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 1.5rem; margin-bottom: 1.5rem; }
        .chart-box {
            background: #ffffff; border-radius: 12px; padding: 1.5rem;
            border: 1px solid #e5e7eb;
        }
        .chart-box.full { grid-column: 1 / -1; }
        .chart-box h2 { border-bottom-color: #334155; margin-top: 0; }
        .badge {
            display: inline-block; padding: 0.25rem 0.75rem; border-radius: 9999px;
            font-size: 0.8rem; font-weight: 600; color: #fff;
        }
        .comp-table { width: 100%; border-collapse: collapse; margin-top: 1rem; font-size: 0.85rem; }
        .comp-table th { text-align: left; color: #6b7280; padding: 0.5rem; border-bottom: 2px solid #e5e7eb; }
        .comp-table td { padding: 0.5rem; border-bottom: 1px solid #f3f4f6; }
        .placeholder { color: #6b7280; font-style: italic; padding: 2rem; text-align: center; }
        .score-bar {
            display: inline-block; height: 8px; border-radius: 4px;
            background: #e5e7eb; width: 80px; vertical-align: middle;
        }
        .score-fill { display: block; height: 100%; border-radius: 4px; }
        .legend { display: flex; gap: 1rem; flex-wrap: wrap; margin-top: 0.75rem; font-size: 0.8rem; color: #6b7280; }
        .legend-item { display: flex; align-items: center; gap: 0.25rem; }
        .legend-dot { width: 10px; height: 10px; border-radius: 50%; }
        .footer {
            margin-top: 3rem; padding-top: 1rem;
            border-top: 1px solid #e5e7eb; color: #9ca3af;
            font-size: 0.75rem; text-align: center;
        }
        .footer a { color: #21a2e3; text-decoration: none; }
        .vanity-warning {
            color: #f59e0b; font-size: 0.75rem; font-style: italic;
            margin-top: 0.25rem;
        }
        svg { max-width: 100%; height: auto; }
        @media (max-width: 768px) {
            body { padding: 1rem; }
            .chart-grid { grid-template-columns: 1fr; }
        }
        @media print {
            body { background: #fff; padding: 0; }
            .chart-box { break-inside: avoid; border: 1px solid #d1d5db; }
        }
    </style>
"""


# ---------------------------------------------------------------------------
# Placeholder helper
# ---------------------------------------------------------------------------


def _placeholder(message: str) -> str:
    """Render a placeholder div for missing/corrupt/stub data."""
    return f'<div class="placeholder">{_esc(message)}</div>'


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
# Header section
# ---------------------------------------------------------------------------


def _section_header(
    report: dict[str, Any] | None,
    positioning_scores: dict[str, Any] | None,
    moat_scores: dict[str, Any] | None,
) -> str:
    """Render the header with title, date, and score summary."""
    company = "Unknown"
    date = ""
    if _usable(report):
        meta = _as_dict(report.get("metadata"))
        company = str(meta.get("company_name", "Unknown"))
        date = str(meta.get("analysis_date", ""))

    title_html = f'<h1>Competitive Positioning: {_esc(company)}</h1><div class="subtitle">{_esc(date)}</div>'

    # Score summary badges
    badges: list[str] = []

    if _usable(report):
        scoring = _as_dict(report.get("scoring_summary"))
        checklist_pct = _num(scoring.get("checklist_score_pct"), -1)
        if checklist_pct >= 0:
            badges.append(f'<span class="badge" style="background:#6b7280;">Checklist: {checklist_pct:.0f}%</span>')

    if _usable(positioning_scores):
        diff = _num(positioning_scores.get("overall_differentiation"), -1)
        if diff >= 0:
            badges.append(f'<span class="badge" style="background:{_CLR_ACCENT};">Differentiation: {diff:.0f}%</span>')

    if _usable(moat_scores):
        startup_data = _as_dict(_as_dict(moat_scores.get("companies")).get("_startup"))
        defensibility = str(startup_data.get("overall_defensibility", "")).lower()
        color = _DEFENSIBILITY_COLORS.get(defensibility, "#9ca3af")
        if defensibility:
            badges.append(
                f'<span class="badge" style="background:{_esc(color)};">'
                f"Defensibility: {_esc(defensibility.title())}</span>"
            )

    badge_html = ""
    if badges:
        badge_html = (
            '<div style="display:flex;gap:0.5rem;flex-wrap:wrap;margin-bottom:1.5rem;">' + "".join(badges) + "</div>"
        )

    attribution = (
        '<div class="subtitle">Generated by '
        '<a href="https://github.com/lool-ventures/founder-skills">founder skills</a>'
        ' by <a href="https://lool.vc">lool ventures</a>'
        " — Competitive Positioning Coach</div>"
    )

    return f"{title_html}{attribution}{badge_html}"


# ---------------------------------------------------------------------------
# Chart: Positioning Map (2D scatter plot)
# ---------------------------------------------------------------------------


def _chart_positioning_map(
    view: dict[str, Any],
    view_scores: dict[str, Any] | None,
    company_name: str,
) -> str:
    """Render a 2D SVG scatter plot for one positioning view."""
    view_id = str(view.get("id", "primary"))
    x_axis = _as_dict(view.get("x_axis"))
    y_axis = _as_dict(view.get("y_axis"))
    x_name = str(x_axis.get("name", "X"))
    y_name = str(y_axis.get("name", "Y"))
    points = _as_list(view.get("points"))

    # Check vanity flags from scores
    x_vanity = False
    y_vanity = False
    if view_scores is not None:
        x_vanity = bool(view_scores.get("x_axis_vanity_flag", False))
        y_vanity = bool(view_scores.get("y_axis_vanity_flag", False))

    # SVG dimensions
    pad_left = 60.0
    pad_bottom = 50.0
    pad_top = 30.0
    pad_right = 30.0
    plot_w = 400.0
    plot_h = 300.0
    svg_w = pad_left + plot_w + pad_right
    svg_h = pad_top + plot_h + pad_bottom

    svg: list[str] = [f'<svg viewBox="0 0 {svg_w:.0f} {svg_h:.0f}" xmlns="http://www.w3.org/2000/svg">']

    # Grid lines
    for i in range(5):
        frac = i / 4
        gx = pad_left + frac * plot_w
        gy = pad_top + (1.0 - frac) * plot_h
        svg.append(
            f'<line x1="{pad_left:.0f}" y1="{gy:.1f}" x2="{pad_left + plot_w:.0f}" y2="{gy:.1f}" '
            f'stroke="#e5e7eb" stroke-width="0.5"/>'
        )
        svg.append(
            f'<line x1="{gx:.1f}" y1="{pad_top:.0f}" x2="{gx:.1f}" y2="{pad_top + plot_h:.0f}" '
            f'stroke="#e5e7eb" stroke-width="0.5"/>'
        )

    # Axes
    svg.append(
        f'<line x1="{pad_left:.0f}" y1="{pad_top + plot_h:.0f}" '
        f'x2="{pad_left + plot_w:.0f}" y2="{pad_top + plot_h:.0f}" '
        f'stroke="#374151" stroke-width="1.5"/>'
    )
    svg.append(
        f'<line x1="{pad_left:.0f}" y1="{pad_top:.0f}" '
        f'x2="{pad_left:.0f}" y2="{pad_top + plot_h:.0f}" '
        f'stroke="#374151" stroke-width="1.5"/>'
    )

    # Vanity indicators — dashed overlay on axis
    if x_vanity:
        svg.append(
            f'<line x1="{pad_left:.0f}" y1="{pad_top + plot_h + 2:.0f}" '
            f'x2="{pad_left + plot_w:.0f}" y2="{pad_top + plot_h + 2:.0f}" '
            f'stroke="#f59e0b" stroke-width="2" stroke-dasharray="6,4"/>'
        )
    if y_vanity:
        svg.append(
            f'<line x1="{pad_left - 2:.0f}" y1="{pad_top:.0f}" '
            f'x2="{pad_left - 2:.0f}" y2="{pad_top + plot_h:.0f}" '
            f'stroke="#f59e0b" stroke-width="2" stroke-dasharray="6,4"/>'
        )

    # Axis labels
    x_label = _esc(x_name)
    y_label = _esc(y_name)
    if x_vanity:
        x_label += ' <tspan fill="#f59e0b" font-size="9">(vanity warning)</tspan>'
    if y_vanity:
        y_label += ' <tspan fill="#f59e0b" font-size="9">(vanity warning)</tspan>'

    svg.append(
        f'<text x="{pad_left + plot_w / 2:.0f}" y="{svg_h - 5:.0f}" '
        f'text-anchor="middle" font-size="11" fill="#374151">{x_label}</text>'
    )
    svg.append(
        f'<text x="14" y="{pad_top + plot_h / 2:.0f}" '
        f'text-anchor="middle" font-size="11" fill="#374151" '
        f'transform="rotate(-90, 14, {pad_top + plot_h / 2:.0f})">{y_label}</text>'
    )

    # Plot points
    startup_label = _esc(company_name) if company_name != "Unknown" else "Your Company"
    for pt in points:
        if not isinstance(pt, dict):
            continue
        slug = str(pt.get("competitor", ""))
        px = _num(pt.get("x"), 50)
        py = _num(pt.get("y"), 50)

        # Map 0-100 to plot coordinates
        cx = pad_left + (px / 100.0) * plot_w
        cy = pad_top + (1.0 - py / 100.0) * plot_h

        is_startup = slug == "_startup"
        radius = 8 if is_startup else 5
        fill = _CLR_STARTUP if is_startup else _CLR_ACCENT
        stroke = "#fff" if is_startup else "none"
        stroke_w = "2" if is_startup else "0"

        svg.append(
            f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{radius}" '
            f'fill="{fill}" stroke="{stroke}" stroke-width="{stroke_w}"/>'
        )

        # Label
        label = startup_label if is_startup else _esc(slug.replace("-", " ").title())
        font_weight = "bold" if is_startup else "normal"
        label_y = cy - radius - 4
        svg.append(
            f'<text x="{cx:.1f}" y="{label_y:.1f}" text-anchor="middle" '
            f'font-size="9" font-weight="{font_weight}" fill="#374151">{label}</text>'
        )

    svg.append("</svg>")

    title = f"Positioning Map: {_esc(view_id.title())}"
    vanity_note = ""
    if x_vanity or y_vanity:
        flagged = []
        if x_vanity:
            flagged.append(_esc(x_name))
        if y_vanity:
            flagged.append(_esc(y_name))
        vanity_note = (
            f'<div class="vanity-warning">Vanity axis warning: '
            f"{', '.join(flagged)} — competitors cluster tightly, "
            f"differentiation may be overstated</div>"
        )

    return f'<div class="chart-box full"><h2>{title}</h2>{"".join(svg)}{vanity_note}</div>'


# ---------------------------------------------------------------------------
# Chart: Moat Radar (hexagonal spider)
# ---------------------------------------------------------------------------


def _moat_score_value(moats: list[Any], dim_id: str) -> float:
    """Get numeric score (0-1) for a moat dimension from moats list."""
    for m in moats:
        if isinstance(m, dict) and str(m.get("id", "")) == dim_id:
            status = str(m.get("status", "absent")).lower()
            return _STATUS_SCORE.get(status, 0.0)
    return 0.0


def _find_strongest_competitor(
    moat_scores: dict[str, Any],
) -> tuple[str, list[Any]]:
    """Find the competitor with highest overall defensibility for radar overlay."""
    companies = _as_dict(moat_scores.get("companies"))
    best_slug = ""
    best_score = -1.0
    best_moats: list[Any] = []
    for slug, data in companies.items():
        if slug == "_startup":
            continue
        if not isinstance(data, dict):
            continue
        defensibility = str(data.get("overall_defensibility", "")).lower()
        score_map = {"high": 3, "moderate": 2, "low": 1}
        s = score_map.get(defensibility, 0)
        if s > best_score:
            best_score = s
            best_slug = slug
            best_moats = _as_list(data.get("moats"))
    return best_slug, best_moats


def _chart_moat_radar(moat_scores: dict[str, Any] | None) -> str:
    """Render hexagonal radar chart for moat dimensions."""
    ph = _artifact_placeholder(moat_scores, "Moat scores")
    if ph is not None:
        return f'<div class="chart-box"><h2>Moat Radar</h2>{ph}</div>'

    ms = _as_dict(moat_scores)
    companies = _as_dict(ms.get("companies"))
    startup_data = _as_dict(companies.get("_startup"))
    startup_moats = _as_list(startup_data.get("moats"))

    if not startup_moats:
        return f'<div class="chart-box"><h2>Moat Radar</h2>{_placeholder("No moat data for startup")}</div>'

    # Find strongest competitor for overlay
    comp_slug, comp_moats = _find_strongest_competitor(ms)

    dims = list(_CANONICAL_MOAT_DIMS)
    n = len(dims)

    # SVG parameters
    cx, cy = 200.0, 170.0
    max_r = 110.0

    svg: list[str] = ['<svg viewBox="0 0 400 360" xmlns="http://www.w3.org/2000/svg">']

    def _angle(i: int) -> float:
        return 2 * math.pi * i / n - math.pi / 2

    # Grid rings at 33%, 66%, 100%
    for pct in [0.33, 0.66, 1.0]:
        ring_r = max_r * pct
        ring_pts: list[str] = []
        for i in range(n):
            a = _angle(i)
            px = cx + ring_r * math.cos(a)
            py = cy + ring_r * math.sin(a)
            ring_pts.append(f"{px:.2f},{py:.2f}")
        svg.append(f'<polygon points="{" ".join(ring_pts)}" fill="none" stroke="#d1d5db" stroke-width="0.5"/>')

    # Axis spokes
    for i in range(n):
        a = _angle(i)
        ex = cx + max_r * math.cos(a)
        ey = cy + max_r * math.sin(a)
        svg.append(
            f'<line x1="{cx:.2f}" y1="{cy:.2f}" x2="{ex:.2f}" y2="{ey:.2f}" stroke="#d1d5db" stroke-width="0.5"/>'
        )

    # Competitor overlay polygon (if available)
    if comp_slug and comp_moats:
        comp_pts: list[str] = []
        for i in range(n):
            a = _angle(i)
            frac = max(0.05, _moat_score_value(comp_moats, dims[i]))
            px = cx + max_r * frac * math.cos(a)
            py = cy + max_r * frac * math.sin(a)
            comp_pts.append(f"{px:.2f},{py:.2f}")
        svg.append(
            f'<polygon points="{" ".join(comp_pts)}" '
            f'fill="{_CLR_ACCENT}" fill-opacity="0.1" '
            f'stroke="{_CLR_ACCENT}" stroke-width="1.5" stroke-dasharray="4,3"/>'
        )

    # Startup polygon
    startup_pts: list[str] = []
    for i in range(n):
        a = _angle(i)
        frac = max(0.05, _moat_score_value(startup_moats, dims[i]))
        px = cx + max_r * frac * math.cos(a)
        py = cy + max_r * frac * math.sin(a)
        startup_pts.append(f"{px:.2f},{py:.2f}")
    svg.append(
        f'<polygon points="{" ".join(startup_pts)}" '
        f'fill="{_CLR_STARTUP}" fill-opacity="0.15" '
        f'stroke="{_CLR_STARTUP}" stroke-width="2"/>'
    )

    # Axis labels
    for i in range(n):
        a = _angle(i)
        label_r = max_r + 22
        lx = cx + label_r * math.cos(a)
        ly = cy + label_r * math.sin(a)
        anchor = "middle"
        if math.cos(a) > 0.3:
            anchor = "start"
        elif math.cos(a) < -0.3:
            anchor = "end"
        label = _MOAT_DIM_LABELS.get(dims[i], dims[i].replace("_", " ").title())
        svg.append(
            f'<text x="{lx:.2f}" y="{ly:.2f}" text-anchor="{anchor}" font-size="10" fill="#6b7280">{_esc(label)}</text>'
        )

    svg.append("</svg>")

    # Legend
    legend_parts = [
        '<div class="legend">',
        f'<div class="legend-item"><div class="legend-dot" style="background:{_CLR_STARTUP};"></div>Your Company</div>',
    ]
    if comp_slug:
        comp_label = _esc(comp_slug.replace("-", " ").title())
        legend_parts.append(
            f'<div class="legend-item">'
            f'<div class="legend-dot" style="background:{_CLR_ACCENT};"></div>'
            f"{comp_label} (strongest)</div>"
        )
    legend_parts.append("</div>")

    return f'<div class="chart-box"><h2>Moat Radar</h2>{"".join(svg)}{"".join(legend_parts)}</div>'


# ---------------------------------------------------------------------------
# Competitor Table
# ---------------------------------------------------------------------------


def _section_competitor_table(
    landscape: dict[str, Any] | None,
    moat_scores: dict[str, Any] | None,
) -> str:
    """Render competitor comparison table sorted by defensibility."""
    ph = _artifact_placeholder(landscape, "Landscape")
    if ph is not None:
        return f'<div class="chart-box full"><h2>Competitor Comparison</h2>{ph}</div>'

    land = _as_dict(landscape)
    competitors = _as_list(land.get("competitors"))
    companies = _as_dict(_as_dict(moat_scores).get("companies")) if _usable(moat_scores) else {}

    # Build rows with defensibility for sorting
    rows: list[tuple[int, str, str]] = []
    order = {"high": 0, "moderate": 1, "low": 2}

    for comp in competitors:
        if not isinstance(comp, dict):
            continue
        name = _esc(str(comp.get("name", "?")))
        slug = str(comp.get("slug", ""))
        category = _esc(_humanize(str(comp.get("category", "?"))))
        research = _esc(_humanize(str(comp.get("research_depth", "?"))))

        comp_data = _as_dict(companies.get(slug))
        defensibility = str(comp_data.get("overall_defensibility", "unknown")).lower()
        def_color = _DEFENSIBILITY_COLORS.get(defensibility, "#9ca3af")
        def_label = _esc(defensibility.title())

        sort_key = order.get(defensibility, 3)

        row = (
            f"<tr>"
            f"<td><strong>{name}</strong></td>"
            f"<td>{category}</td>"
            f'<td style="color:{_esc(def_color)};font-weight:600;">{def_label}</td>'
            f"<td>{research}</td>"
            f"</tr>"
        )
        rows.append((sort_key, slug, row))

    rows.sort(key=lambda r: (r[0], r[1]))

    table = (
        '<table class="comp-table">'
        "<tr><th>Name</th><th>Category</th><th>Defensibility</th><th>Research Depth</th></tr>"
        + "".join(r[2] for r in rows)
        + "</table>"
    )

    return f'<div class="chart-box full"><h2>Competitor Comparison</h2>{table}</div>'


# ---------------------------------------------------------------------------
# Defensibility Timeline
# ---------------------------------------------------------------------------


def _section_defensibility_timeline(
    positioning: dict[str, Any] | None,
    moat_scores: dict[str, Any] | None,
) -> str:
    """Render moat trajectory timeline if trajectory data is available."""
    if not _usable(positioning):
        return ""

    # Check if any moat has trajectory data
    moat_assessments = _as_dict(positioning.get("moat_assessments"))
    startup_assessment = _as_dict(moat_assessments.get("_startup"))
    startup_moats = _as_list(startup_assessment.get("moats"))

    has_trajectory = False
    for m in startup_moats:
        if isinstance(m, dict) and "trajectory" in m:
            has_trajectory = True
            break

    if not has_trajectory:
        return ""

    # Build timeline rows
    svg_row_h = 32.0
    label_w = 140.0
    bar_w = 200.0
    svg_w = label_w + bar_w + 60
    n_rows = len(_CANONICAL_MOAT_DIMS)
    svg_h = n_rows * svg_row_h + 30

    svg: list[str] = [f'<svg viewBox="0 0 {svg_w:.0f} {svg_h:.0f}" xmlns="http://www.w3.org/2000/svg">']

    trajectory_colors = {
        "building": "#10b981",
        "stable": "#6b7280",
        "eroding": "#ef4444",
    }

    for i, dim_id in enumerate(_CANONICAL_MOAT_DIMS):
        y = i * svg_row_h + 15
        label = _MOAT_DIM_LABELS.get(dim_id, dim_id.replace("_", " ").title())

        # Find trajectory for this dim
        trajectory = "stable"
        status = "absent"
        for m in startup_moats:
            if isinstance(m, dict) and str(m.get("id", "")) == dim_id:
                trajectory = str(m.get("trajectory", "stable")).lower()
                status = str(m.get("status", "absent")).lower()
                break

        arrow = _TRAJECTORY_ARROWS.get(trajectory, "\u2192")
        color = trajectory_colors.get(trajectory, "#6b7280")
        score = _STATUS_SCORE.get(status, 0.0)

        # Label
        svg.append(
            f'<text x="{label_w - 8:.0f}" y="{y + 4:.0f}" text-anchor="end" '
            f'font-size="10" fill="#374151">{_esc(label)}</text>'
        )

        # Bar background
        svg.append(f'<rect x="{label_w:.0f}" y="{y - 6:.0f}" width="{bar_w:.0f}" height="12" rx="6" fill="#e5e7eb"/>')

        # Bar fill
        fill_w = max(4, score * bar_w)
        svg.append(
            f'<rect x="{label_w:.0f}" y="{y - 6:.0f}" width="{fill_w:.1f}" height="12" rx="6" fill="{_esc(color)}"/>'
        )

        # Trajectory arrow
        svg.append(
            f'<text x="{label_w + bar_w + 12:.0f}" y="{y + 4:.0f}" font-size="14" fill="{_esc(color)}">{arrow}</text>'
        )

        # Trajectory label
        svg.append(
            f'<text x="{label_w + bar_w + 30:.0f}" y="{y + 3:.0f}" '
            f'font-size="9" fill="#6b7280">{_esc(_humanize(trajectory))}</text>'
        )

    svg.append("</svg>")

    return f'<div class="chart-box full"><h2>Defensibility Timeline</h2>{"".join(svg)}</div>'


# ---------------------------------------------------------------------------
# Full HTML composition
# ---------------------------------------------------------------------------


def compose_html(dir_path: str) -> str:
    """Load artifacts and compose the full HTML document."""
    all_names = REQUIRED_ARTIFACTS + OPTIONAL_ARTIFACTS
    artifacts: dict[str, dict[str, Any] | None] = {}
    for name in all_names:
        artifacts[name] = _load_artifact(dir_path, name)

    landscape = artifacts.get("landscape.json")
    positioning = artifacts.get("positioning.json")
    positioning_scores = artifacts.get("positioning_scores.json")
    moat_scores = artifacts.get("moat_scores.json")
    report = artifacts.get("report.json")

    # Resolve company name
    company_name = "Unknown"
    if _usable(report):
        meta = _as_dict(report.get("metadata"))
        company_name = str(meta.get("company_name", "Unknown"))

    # Header
    header = _section_header(report, positioning_scores, moat_scores)

    # Positioning maps
    positioning_maps: list[str] = []
    if _usable(positioning):
        views = _as_list(positioning.get("views"))
        scores_by_id: dict[str, dict[str, Any]] = {}
        if _usable(positioning_scores):
            for sv in _as_list(positioning_scores.get("views")):
                if isinstance(sv, dict):
                    scores_by_id[str(sv.get("view_id", ""))] = sv

        for view in views:
            if not isinstance(view, dict):
                continue
            view_id = str(view.get("id", ""))
            view_score = scores_by_id.get(view_id)
            positioning_maps.append(_chart_positioning_map(view, view_score, company_name))

    if not positioning_maps:
        positioning_maps.append(
            f'<div class="chart-box full"><h2>Positioning Map</h2>'
            f"{_placeholder('Positioning data not available')}</div>"
        )

    # Moat radar
    moat_radar = _chart_moat_radar(moat_scores)

    # Competitor table
    comp_table = _section_competitor_table(landscape, moat_scores)

    # Defensibility timeline
    timeline = _section_defensibility_timeline(positioning, moat_scores)

    # Page title
    page_title = f"Competitive Positioning: {_esc(company_name)}"

    maps_html = "\n".join(positioning_maps)

    body = f"""
{header}
{maps_html}
<div class="chart-grid">
{moat_radar}
</div>
{comp_table}
{timeline}
<div class="footer">
  Generated by <a href="https://github.com/lool-ventures/founder-skills">founder skills</a>
  by <a href="https://lool.vc">lool ventures</a> — Competitive Positioning Coach
</div>
"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>{page_title}</title>
{_css()}
</head>
<body>
{body}
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------


def _write_output(data: str, output_path: str | None) -> None:
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
        receipt: dict[str, Any] = {
            "ok": True,
            "path": abs_path,
            "bytes": len(data.encode("utf-8")),
        }
        sys.stdout.write(json.dumps(receipt, separators=(",", ":")) + "\n")
    else:
        sys.stdout.write(data)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    p = argparse.ArgumentParser(description="Generate HTML visualization from competitive positioning artifacts")
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
    return p.parse_args()


def main() -> None:
    """Entry point."""
    args = parse_args()

    if not os.path.isdir(args.dir):
        print(f"Error: directory not found: {args.dir}", file=sys.stderr)
        sys.exit(1)

    html_out = compose_html(args.dir)
    _write_output(html_out, args.output)


if __name__ == "__main__":
    main()
