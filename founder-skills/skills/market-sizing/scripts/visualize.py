#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
Generate self-contained HTML visualization from market sizing JSON artifacts.

Outputs raw HTML (not JSON). See compose_report.py for JSON report output.

Usage:
    python visualize.py --dir ./market-sizing-acme-corp/
    python visualize.py --dir ./market-sizing-acme-corp/ -o report.html
"""

from __future__ import annotations

import argparse
import html
import json
import math
import os
import sys
from types import ModuleType
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _params  # noqa: E402
import _redteam_copy  # noqa: E402
import _thresholds  # noqa: E402
import _ui  # noqa: E402
import _upload_names  # noqa: E402
import _view  # noqa: E402
from _redteam_text import humanize_claim as _humanize_claim  # noqa: E402
from _view import (  # noqa: E402
    _CORRUPT,
    _INTERNAL_PROVENANCE,
    CLOSE_AGREEMENT_PCT,
    DECK_MISMATCH_PCT,
    _adversarial_outcome,
    _as_dict,
    _as_list,
    _compute_provenance,
    _contested_rows,
    _document_cite,
    _fmt_usd,
    _is_stub,
    _resolve_currency,
    _resolve_sizing_basis,
    _set_currency,
    _shared_input_values,
    _sizing_basis_label,
    _summary_verdict,
    _usable,
)

# ---------------------------------------------------------------------------
# Artifact loading infrastructure (duplicated from compose_report.py per PEP 723)
# ---------------------------------------------------------------------------


REQUIRED_ARTIFACTS = [
    "inputs.json",
    "methodology.json",
    "validation.json",
    "sizing.json",
    "checklist.json",
    "sensitivity.json",
]
OPTIONAL_ARTIFACTS: list[str] = ["redteam.json"]

# Canonical category order for assumption confidence donut
_CONFIDENCE_CATEGORIES: list[str] = ["sourced", "derived", "agent_estimate"]


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


def _write_output(data: str, output_path: str | None, *, summary: dict[str, Any] | None = None) -> None:
    """Write HTML string to file or stdout."""
    if output_path:
        abs_path = os.path.abspath(output_path)
        parent = os.path.dirname(abs_path)
        if parent == "/":
            print(f"Error: output path resolves to root directory: {output_path}", file=sys.stderr)
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
# HTML / SVG safety helpers
# ---------------------------------------------------------------------------


def _esc(text: Any) -> str:
    """Escape text for HTML/SVG interpolation."""
    return html.escape(str(text), quote=True)


def _num(value: Any, default: float = 0.0) -> float:
    """Safe numeric coercion for SVG coordinates."""
    try:
        result = float(value)
        if not math.isfinite(result):
            return default
        return result
    except (TypeError, ValueError):
        return default


def _try_float(value: Any) -> float | None:
    """Coerce to float, returning None on non-numeric input.

    Mirrors the _compute_delta tolerance: a non-numeric deck claim (e.g. "$5B"
    or "TBD") must be skipped, not crash the whole HTML render.
    """
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Color scheme
# ---------------------------------------------------------------------------

_TORNADO_LABEL_FONT = 8

# Dash patterns — each must be unique to enable targeted test assertions
_DASH_LEADER_LINE = "2,2"  # leader lines from labels to small circles
_DASH_CLAMPED_CIRCLE = "3,2"  # floor-clamped circles ("not to scale")
# Existing: tornado baseline uses "4,3" (already hardcoded in _chart_tornado)

_SAM_LABEL_FONT = 10  # px, SAM label font size in funnel chart

_CLR_PRIMARY = "#0D549D"
_CLR_ACCENT = "#21A2E3"
_CLR_PASS = "#2F8A56"
_CLR_WARN = "#C9892B"
_CLR_FAIL = "#C0392B"
_CLR_NA = "#A6AEB5"

# SVG chrome greys (literal hex -- var(--x) does not resolve in SVG
# presentation attributes)
_SVG_TEXT_DARK = "#374B65"
_SVG_TEXT_MUTE = "#7D90A3"
_SVG_TEXT_FAINT = "#A6AEB5"
_SVG_GRIDLINE = "#D7DBE0"

_CONFIDENCE_COLORS: dict[str, str] = {
    "sourced": _CLR_PASS,
    "derived": _CLR_WARN,
    "agent_estimate": _CLR_FAIL,
}


# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------


def _css() -> str:
    """This page's own styles, after `_ui.UI_CSS` (the shell, cards, ring and checklist)."""
    return """
        .chart-container {
            display: flex; justify-content: center; align-items: center; flex-wrap: wrap; gap: 2rem;
        }
        .chart-container svg { max-width: 100%; height: auto; }
        svg text { font-family: var(--font-body); }
        .placeholder {
            text-align: center; color: var(--ui-ink-2); font-style: italic;
            padding: 2rem; background: var(--ui-surface-2); border-radius: var(--ui-r1); margin: 0;
        }
        .legend {
            display: flex; justify-content: center; gap: 0.5rem 1.5rem; flex-wrap: wrap;
            margin-top: 1rem; font-size: 0.85rem; color: var(--ui-ink-2);
        }
        .legend-item { display: flex; align-items: center; gap: 0.35rem; }
        .legend-swatch { width: 12px; height: 12px; border-radius: 3px; display: inline-block; }
        .chart-note, .ms-foot { margin: 0.6rem 0 0; font-size: 0.82rem; color: var(--ui-ink-2); }
        .ms-foot--warn { color: var(--st-warn); font-size: 0.86rem; }
        .estimate-note { margin: 0.5rem 0 0; font-size: 0.86rem; }
        .ms-lead { margin: 0 0 var(--ui-s4); font-size: 0.86rem; color: var(--ui-ink-2); }
        .ms-meta { margin: var(--ui-s3) 0 0; font-size: 0.82rem; color: var(--ui-ink-2); }
        .ms-meta p { margin: 2px 0 0; }
        .ms-prov { margin-top: var(--ui-s4); }
        /* The funnel and the tornado scale with the page but stop where their labels stay legible; on a
           phone the rest scrolls inside the card, never the page. */
        .ms-wide { min-width: 460px; }
        .ms-prov td:first-child { white-space: nowrap; }
        .ms-grade { font-weight: 600; }
        .ms-grade--sourced { color: var(--st-pass-ink); }
        .ms-grade--derived { color: var(--st-warn); }
        .ms-grade--agent_estimate { color: var(--st-fail); }
        .ms-grade--unknown { color: var(--st-na); }
        .ms-challenge__truth { margin: 4px 0 0; }
        .ms-quote {
            margin: var(--ui-s2) 0 0; padding-left: 0.75rem; border-left: 3px solid var(--ui-line);
            color: var(--ui-ink-2);
        }
        .ms-cite { margin: 4px 0 0; font-size: 0.82rem; color: var(--ui-ink-2); }
        #sensitivity h3 { margin-top: var(--ui-s4); }
        [data-tooltip] { cursor: help; }
        @media print { [data-tooltip] { cursor: default; } }
    """


# ---------------------------------------------------------------------------
# Inline JS
# ---------------------------------------------------------------------------


def _tooltip_js() -> str:
    """Return inline JS for hover tooltips on elements with data-tooltip attribute."""
    return (
        "<script>\n"
        "document.addEventListener('DOMContentLoaded', function() {\n"
        "    var tip = document.createElement('div');\n"
        "    tip.style.cssText = 'position:fixed;padding:8px 12px;background:#374B65;color:#fff;'\n"
        "        + 'border-radius:4px;font-size:12px;max-width:300px;pointer-events:none;'\n"
        "        + 'z-index:1000;display:none;line-height:1.4;white-space:pre-line;'\n"
        "        + 'box-shadow:0 2px 8px rgba(0,0,0,0.15)';\n"
        "    document.body.appendChild(tip);\n"
        "    document.addEventListener('mouseover', function(e) {\n"
        "        var el = e.target.closest('[data-tooltip]');\n"
        "        if (el) {\n"
        "            tip.textContent = el.getAttribute('data-tooltip');\n"
        "            tip.style.display = 'block';\n"
        "        }\n"
        "    });\n"
        "    document.addEventListener('mousemove', function(e) {\n"
        "        if (tip.style.display === 'block') {\n"
        "            tip.style.left = Math.min(e.clientX + 12, window.innerWidth - 320) + 'px';\n"
        "            tip.style.top = (e.clientY + 16) + 'px';\n"
        "        }\n"
        "    });\n"
        "    document.addEventListener('mouseout', function(e) {\n"
        "        if (e.target.closest('[data-tooltip]')) tip.style.display = 'none';\n"
        "    });\n"
        "});\n"
        "</script>"
    )


# ---------------------------------------------------------------------------
# SVG helper: donut chart
# ---------------------------------------------------------------------------


def _svg_donut(
    segments: list[tuple[str, float, str]],
    width: int = 200,
    height: int = 200,
    inner_radius: float = 50.0,
    outer_radius: float = 90.0,
) -> str:
    """Render a donut chart as SVG.

    segments: list of (label, value, color).
    """
    total = sum(v for _, v, _ in segments)
    if total <= 0:
        return f'<text x="100" y="100" text-anchor="middle" fill="{_SVG_TEXT_FAINT}">No data</text>'

    total_int = int(total)

    or_val = _num(outer_radius)
    vb_size = _num(or_val * 2 + 20)
    return (
        f'<svg width="{_num(width):.0f}" height="{_num(height):.0f}" '
        f'viewBox="{_num(-or_val - 10):.2f} {_num(-or_val - 10):.2f} '
        f'{vb_size:.2f} {vb_size:.2f}" '
        f'xmlns="http://www.w3.org/2000/svg">\n'
        + "\n".join(p for p in _render_donut_paths_centered(segments, total, outer_radius, inner_radius))
        + f'\n<text x="0" y="0" text-anchor="middle" '
        f'dominant-baseline="central" font-size="24" font-weight="bold" '
        f'fill="{_SVG_TEXT_DARK}">{_esc(str(total_int))}</text>'
        "\n</svg>"
    )


def _render_donut_paths_centered(
    segments: list[tuple[str, float, str]],
    total: float,
    outer_radius: float,
    inner_radius: float,
) -> list[str]:
    """Render donut path elements centered at origin."""
    paths: list[str] = []
    angle = -90.0

    for _label, value, color in segments:
        if value <= 0:
            continue
        sweep = _num(value / total * 360.0)
        if sweep >= 360.0:
            sweep = 359.999

        start_rad = math.radians(angle)
        end_rad = math.radians(angle + sweep)

        x1o = _num(outer_radius * math.cos(start_rad))
        y1o = _num(outer_radius * math.sin(start_rad))
        x2o = _num(outer_radius * math.cos(end_rad))
        y2o = _num(outer_radius * math.sin(end_rad))

        x1i = _num(inner_radius * math.cos(end_rad))
        y1i = _num(inner_radius * math.sin(end_rad))
        x2i = _num(inner_radius * math.cos(start_rad))
        y2i = _num(inner_radius * math.sin(start_rad))

        large_arc = 1 if sweep > 180 else 0

        d = (
            f"M {x1o:.2f} {y1o:.2f} "
            f"A {outer_radius:.2f} {outer_radius:.2f} 0 {large_arc} 1 {x2o:.2f} {y2o:.2f} "
            f"L {x1i:.2f} {y1i:.2f} "
            f"A {inner_radius:.2f} {inner_radius:.2f} 0 {large_arc} 0 {x2i:.2f} {y2i:.2f} Z"
        )
        paths.append(f'<path d="{d}" fill="{_esc(color)}" />')
        angle += sweep

    return paths


# ---------------------------------------------------------------------------
# Chart 1: TAM/SAM/SOM Funnel (concentric circles)
# ---------------------------------------------------------------------------

# The smallest TAM circle drawn, in px of a 100 px scale: below it the circle is a dot nobody can read.
_MIN_TAM_R = 20.0

_FUNNEL_COLORS = {
    "tam": "#0D549D",
    "sam": "#1B5FB2",
    "som": "#48B4EA",
}


def _chart_funnel_single(
    approach_data: dict[str, Any],
    label: str,
    cx: float,
    cy: float,
    max_r: float,
    label_side: str | None = None,
    scale_value: float | None = None,
) -> str:
    """Render a single concentric-circle funnel centered at (cx, cy).

    label_side: "left" or "right" to place TAM/SAM/SOM labels externally
    with horizontal leader lines. None = centered labels (single-approach).

    scale_value: the value a circle of radius `max_r` stands for. Two builds drawn side by side pass the
    larger of their two TAMs, so both diagrams share ONE scale: every circle's AREA is proportional to
    its value, and a build whose TAM is a quarter of the other's is drawn at half the radius. A circle
    too small to see keeps a minimum radius (dashed, "not to scale"); its label always prints the exact
    figure. None = this build's own TAM (a lone diagram fills its space).
    """
    tam_val = _num(_as_dict(approach_data.get("tam")).get("value", 0))
    sam_val = _num(_as_dict(approach_data.get("sam")).get("value", 0))
    som_val = _num(_as_dict(approach_data.get("som")).get("value", 0))

    # Radii proportional to value, with TAM as outermost
    if tam_val <= 0:
        return (
            f'<text x="{cx:.2f}" y="{cy:.2f}" text-anchor="middle" '
            f'fill="{_SVG_TEXT_FAINT}" font-size="12">No TAM data</text>'
        )

    ref = scale_value if scale_value is not None and scale_value >= tam_val else tam_val

    def _radius(value: float) -> float:
        return _num(max_r * math.sqrt(max(value, 0) / ref)) if ref > 0 else 0.0

    r_tam_proportional = _radius(tam_val)
    r_sam_proportional = _radius(sam_val)
    r_som_proportional = _radius(som_val)

    # Apply minimum floors for visibility and track clamping
    r_tam = max(_num(r_tam_proportional), _MIN_TAM_R)
    tam_clamped = r_tam_proportional < _MIN_TAM_R
    r_sam = max(_num(r_sam_proportional), 15.0)
    r_som = max(_num(r_som_proportional), 8.0)
    sam_clamped = r_sam_proportional < 15.0
    som_clamped = r_som_proportional < 8.0

    # Dashed stroke for floor-clamped circles to signal "not to scale"
    tam_dash = f' stroke="#ffffff" stroke-width="2" stroke-dasharray="{_DASH_CLAMPED_CIRCLE}"' if tam_clamped else ""
    sam_dash = f' stroke-dasharray="{_DASH_CLAMPED_CIRCLE}"' if sam_clamped else ""
    som_dash = f' stroke-dasharray="{_DASH_CLAMPED_CIRCLE}"' if som_clamped else ""

    parts: list[str] = []

    # TAM circle (outermost)
    parts.append(
        f'<circle cx="{cx:.2f}" cy="{cy:.2f}" r="{r_tam:.2f}" fill="{_FUNNEL_COLORS["tam"]}" opacity="0.3"{tam_dash} />'
    )
    # SAM circle — white stroke to separate from TAM
    parts.append(
        f'<circle cx="{cx:.2f}" cy="{cy:.2f}" r="{r_sam:.2f}" fill="{_FUNNEL_COLORS["sam"]}" opacity="0.5"'
        f' stroke="#ffffff" stroke-width="2"{sam_dash} />'
    )
    # SOM circle (innermost) — white stroke to separate from SAM
    parts.append(
        f'<circle cx="{cx:.2f}" cy="{cy:.2f}" r="{r_som:.2f}" fill="{_FUNNEL_COLORS["som"]}" opacity="0.7"'
        f' stroke="#ffffff" stroke-width="2"{som_dash} />'
    )

    # --- Labels ---
    if label_side in ("left", "right"):
        # External labels with horizontal leader lines to circle edges.
        # Stack TAM/SAM/SOM vertically with 22px spacing, centered on cy.
        label_y_tam = _num(cy - 22)
        label_y_sam = _num(cy)
        label_y_som = _num(cy + 22)

        if label_side == "left":
            anchor = "end"
            label_x = _num(cx - max_r - 40)  # text position
            sign = -1.0
        else:
            anchor = "start"
            label_x = _num(cx + max_r + 40)
            sign = 1.0

        # Each label: text + horizontal leader line to circle edge
        for metric_label, metric_val, radius, y_pos in [
            ("TAM", tam_val, r_tam, label_y_tam),
            ("SAM", sam_val, r_sam, label_y_sam),
            ("SOM", som_val, r_som, label_y_som),
        ]:
            # Text
            parts.append(
                f'<text x="{label_x:.2f}" y="{y_pos:.2f}" text-anchor="{anchor}" '
                f'dominant-baseline="central" font-size="10" fill="{_SVG_TEXT_DARK}" font-weight="bold">'
                f"{metric_label}: {_esc(_fmt_usd(metric_val))}</text>"
            )
            # Leader line from label to circle edge
            line_end_x = _num(cx + sign * radius)
            # Line starts near the text (with a small gap)
            line_start_x = _num(label_x + (8 if label_side == "left" else -8))
            parts.append(
                f'<line x1="{line_start_x:.2f}" y1="{y_pos:.2f}" '
                f'x2="{line_end_x:.2f}" y2="{y_pos:.2f}" '
                f'stroke="{_SVG_TEXT_FAINT}" stroke-width="1" stroke-dasharray="{_DASH_LEADER_LINE}" />'
            )
    else:
        # Centered labels (single-approach mode)
        label_y_tam = _num(cy - max_r - 8)
        parts.append(
            f'<text x="{cx:.2f}" y="{label_y_tam:.2f}" text-anchor="middle" '
            f'font-size="11" fill="{_SVG_TEXT_DARK}" font-weight="bold">'
            f"TAM: {_esc(_fmt_usd(tam_val))}</text>"
        )

        # SAM label — move outside circle with leader line when too small to fit
        if r_sam < _SAM_LABEL_FONT * 3.5:
            label_y_sam = _num(cy - max_r - 22)
            line_y_start = _num(label_y_sam + 4)
            line_y_end = _num(cy - r_sam)
            parts.append(
                f'<line x1="{cx:.2f}" y1="{line_y_start:.2f}" '
                f'x2="{cx:.2f}" y2="{line_y_end:.2f}" '
                f'stroke="{_SVG_TEXT_FAINT}" stroke-width="1" stroke-dasharray="{_DASH_LEADER_LINE}" />'
            )
        else:
            label_y_sam = _num(cy - r_sam + 14)
        parts.append(
            f'<text x="{cx:.2f}" y="{label_y_sam:.2f}" text-anchor="middle" '
            f'font-size="{_SAM_LABEL_FONT}" fill="{_SVG_TEXT_DARK}">'
            f"SAM: {_esc(_fmt_usd(sam_val))}</text>"
        )
        parts.append(
            f'<text x="{cx:.2f}" y="{cy:.2f}" text-anchor="middle" '
            f'dominant-baseline="central" font-size="10" fill="{_SVG_TEXT_DARK}" font-weight="bold">'
            f"SOM: {_esc(_fmt_usd(som_val))}</text>"
        )

    # Approach label below
    label_y_bot = _num(cy + max_r + 18)
    parts.append(
        f'<text x="{cx:.2f}" y="{label_y_bot:.2f}" text-anchor="middle" '
        f'font-size="12" fill="{_CLR_PRIMARY}" font-weight="bold">{_esc(label)}</text>'
    )

    return "\n".join(parts)


def _chart_funnel(sizing: dict[str, Any] | None) -> str:
    """Chart 1: TAM/SAM/SOM concentric circles funnel."""
    if sizing is None:
        return '<div class="placeholder">No data available</div>'
    if sizing is _CORRUPT:
        return '<div class="placeholder">Data unavailable</div>'
    if _is_stub(sizing):
        reason = _esc(sizing.get("reason", "Skipped"))
        return f'<div class="placeholder">{reason}</div>'

    td = sizing.get("top_down")
    bu = sizing.get("bottom_up")
    has_td = isinstance(td, dict)
    has_bu = isinstance(bu, dict)

    if not has_td and not has_bu:
        return '<div class="placeholder">No sizing approaches found</div>'

    td_d = _as_dict(td)
    bu_d = _as_dict(bu)

    if has_td and has_bu:
        # Side by side with external labels on outer edges
        svg_w = 700
        svg_h = 280
        max_r = 100.0
        # ONE scale for both diagrams: the larger TAM fills the radius, the other is drawn to it.
        shared = max(_num(_as_dict(td_d.get("tam")).get("value", 0)), _num(_as_dict(bu_d.get("tam")).get("value", 0)))
        parts = [
            f'<svg width="{svg_w}" height="{svg_h}" viewBox="0 0 {svg_w} {svg_h}" xmlns="http://www.w3.org/2000/svg">',
            _chart_funnel_single(td_d, "Top-Down", 230.0, 130.0, max_r, label_side="left", scale_value=shared),
            _chart_funnel_single(bu_d, "Bottom-Up", 470.0, 130.0, max_r, label_side="right", scale_value=shared),
            "</svg>",
        ]
    elif has_td:
        svg_w = 300
        svg_h = 280
        max_r = 100.0
        parts = [
            f'<svg width="{svg_w}" height="{svg_h}" viewBox="0 0 {svg_w} {svg_h}" xmlns="http://www.w3.org/2000/svg">',
            _chart_funnel_single(td_d, "Top-Down", 150.0, 130.0, max_r),
            "</svg>",
        ]
    else:
        svg_w = 300
        svg_h = 280
        max_r = 100.0
        parts = [
            f'<svg width="{svg_w}" height="{svg_h}" viewBox="0 0 {svg_w} {svg_h}" xmlns="http://www.w3.org/2000/svg">',
            _chart_funnel_single(bu_d, "Bottom-Up", 150.0, 130.0, max_r),
            "</svg>",
        ]

    return '<div class="chart-container">' + "\n".join(parts) + "</div>"


# ---------------------------------------------------------------------------
# Chart 2: Sensitivity Tornado Chart
# ---------------------------------------------------------------------------


def _render_tornado_svg(
    bar_data: list[tuple[str, float, float, float]],
    base_som: float,
) -> str:
    """Render a single tornado SVG chart for the given bars and baseline.

    Each entry in *bar_data* is ``(param_name, low_som, base_som, high_som)``.
    Returns an SVG string wrapped in a ``<div class="chart-container">``.
    """
    # SVG dimensions
    bar_height = 28
    bar_gap = 18
    label_width = 180
    chart_width = 350
    margin_right = 70
    svg_w = label_width + chart_width + margin_right
    svg_h = len(bar_data) * (bar_height + bar_gap) + 50

    # Find min/max for scale (independent per sub-chart)
    all_vals = [v for _, lo, _, hi in bar_data for v in (lo, hi)]
    if base_som > 0:
        all_vals.append(base_som)
    global_min = min(all_vals) if all_vals else 0
    global_max = max(all_vals) if all_vals else 1
    if global_min == global_max:
        global_max = global_min + 1

    def x_pos(val: float) -> float:
        span = global_max - global_min
        if span <= 0:
            return _num(label_width)
        return _num(label_width + (val - global_min) / span * chart_width)

    parts: list[str] = [
        f'<svg width="{svg_w}" height="{svg_h}" viewBox="0 0 {svg_w} {svg_h}" xmlns="http://www.w3.org/2000/svg">'
    ]

    # Base SOM center line
    base_x = x_pos(base_som)
    parts.append(
        f'<line x1="{base_x:.2f}" y1="0" x2="{base_x:.2f}" y2="{_num(svg_h - 20):.2f}" '
        f'stroke="{_SVG_TEXT_MUTE}" stroke-width="1" stroke-dasharray="4,3" />'
    )
    parts.append(
        f'<text x="{base_x:.2f}" y="{_num(svg_h - 5):.2f}" text-anchor="middle" '
        f'font-size="9" fill="{_SVG_TEXT_MUTE}">Base: {_esc(_fmt_usd(base_som))}</text>'
    )

    for i, (param, low_som, _b_som, high_som) in enumerate(bar_data):
        y = _num(i * (bar_height + bar_gap) + 15)
        # Label
        display_param = _esc(param.replace("_", " ").title())
        parts.append(
            f'<text x="{_num(label_width - 5):.2f}" y="{_num(y + bar_height / 2):.2f}" '
            f'text-anchor="end" dominant-baseline="central" font-size="11" '
            f'fill="{_SVG_TEXT_DARK}">{display_param}</text>'
        )

        # Bar from low to high
        x_low = x_pos(low_som)
        x_high = x_pos(high_som)
        bar_x = min(x_low, x_high)
        bar_w = max(abs(x_high - x_low), 1.0)

        tooltip_text = (
            f"{param.replace('_', ' ').title()}\n"
            f"Low: {_fmt_usd(low_som)}\n"
            f"Base: {_fmt_usd(_b_som)}\n"
            f"High: {_fmt_usd(high_som)}"
        )
        parts.append(
            f'<rect x="{_num(bar_x):.2f}" y="{y:.2f}" '
            f'width="{_num(bar_w):.2f}" height="{_num(bar_height):.2f}" '
            f'fill="{_CLR_PRIMARY}" opacity="0.6" rx="3" '
            f'data-tooltip="{_esc(tooltip_text)}" />'
        )

        # Low/high value labels — enforce minimum gap to prevent overlap.
        # Each USD label at font_size 8 is roughly 7-8 chars -> ~8 * char_width.
        # Approximate char_width ~ font_size * 0.6 for sans-serif.
        # So each label occupies ~font_size * 0.6 * 8 ~ font_size * 5 px.
        # Two labels with text-anchor="middle" overlap when their centers are
        # closer than one label width.  Use font_size * 5 as the minimum gap.
        label_font_size = _TORNADO_LABEL_FONT  # 8px
        min_label_gap = label_font_size * 5  # ~40px — one label width apart
        low_label_x = _num(bar_x)
        high_label_x = _num(bar_x + bar_w)

        if high_label_x - low_label_x < min_label_gap:
            high_label_x = low_label_x + min_label_gap

        # Clamp to SVG right edge to prevent clipping
        max_label_x = svg_w - label_font_size * 2  # leave room for text
        high_label_x = min(high_label_x, max_label_x)

        parts.append(
            f'<text x="{low_label_x:.2f}" y="{_num(y - 2):.2f}" '
            f'text-anchor="middle" font-size="{_TORNADO_LABEL_FONT}" '
            f'fill="{_SVG_TEXT_MUTE}">{_esc(_fmt_usd(low_som))}</text>'
        )
        parts.append(
            f'<text x="{high_label_x:.2f}" y="{_num(y - 2):.2f}" '
            f'text-anchor="middle" font-size="{_TORNADO_LABEL_FONT}" '
            f'fill="{_SVG_TEXT_MUTE}">{_esc(_fmt_usd(high_som))}</text>'
        )

    parts.append("</svg>")

    return '<div class="chart-container">' + "\n".join(parts) + "</div>"


def _build_bar_data(
    ordered_params: list[str],
    scenario_map: dict[str, dict[str, Any]],
    base_som: float,
) -> list[tuple[str, float, float, float]]:
    """Collect (param, low, base, high) SOM tuples for tornado bars."""
    bar_data: list[tuple[str, float, float, float]] = []
    for param in ordered_params:
        s = scenario_map[param]
        low_som = _num(_as_dict(s.get("low")).get("som", 0))
        b_som = _num(_as_dict(s.get("base")).get("som", 0))
        high_som = _num(_as_dict(s.get("high")).get("som", 0))
        if b_som == 0:
            b_som = base_som
        bar_data.append((param, low_som, b_som, high_som))
    return bar_data


def _order_params(
    ranked_params: list[str],
    scenario_map: dict[str, dict[str, Any]],
) -> list[str]:
    """Return deduplicated, ordered parameter list: ranking first, then remaining sorted."""
    seen: set[str] = set()
    ordered: list[str] = []
    for p in ranked_params:
        if p not in seen:
            ordered.append(p)
            seen.add(p)
    remaining = sorted(set(scenario_map.keys()) - seen)
    ordered.extend(remaining)
    # Filter to only those with scenario data
    return [p for p in ordered if p in scenario_map]


def _chart_tornado(sensitivity: dict[str, Any] | None) -> str:
    """Chart 2: Horizontal tornado bars centered on base SOM.

    In "both" mode (base_result contains top_down/bottom_up keys and scenarios
    carry ``approach_used``), renders two sub-charts with independent baselines
    and scales.  Single-approach mode is unchanged.
    """
    if sensitivity is None:
        return '<div class="placeholder">No data available</div>'
    if sensitivity is _CORRUPT:
        return '<div class="placeholder">Data unavailable</div>'
    if _is_stub(sensitivity):
        reason = _esc(sensitivity.get("reason", "Skipped"))
        return f'<div class="placeholder">{reason}</div>'

    ranking = _as_list(sensitivity.get("sensitivity_ranking"))
    scenarios = _as_list(sensitivity.get("scenarios"))

    if not scenarios:
        return '<div class="placeholder">No sensitivity scenarios</div>'

    # Build ordered parameter list from sensitivity_ranking
    ranked_params: list[str] = [str(r.get("parameter", "")) for r in ranking if isinstance(r, dict)]

    # Build scenario lookup
    scenario_map: dict[str, dict[str, Any]] = {}
    for s in scenarios:
        if not isinstance(s, dict):
            continue
        param = str(s.get("parameter", ""))
        scenario_map[param] = s

    ordered_params = _order_params(ranked_params, scenario_map)

    if not ordered_params:
        return '<div class="placeholder">No sensitivity data to display</div>'

    # Determine base SOM and detect "both" mode
    base_result = _as_dict(sensitivity.get("base_result"))
    is_both = "top_down" in base_result or "bottom_up" in base_result

    if is_both:
        # --- "both" mode: partition scenarios by approach_used ---
        approach_groups: dict[str, dict[str, dict[str, Any]]] = {
            "top_down": {},
            "bottom_up": {},
        }
        for s in scenarios:
            if not isinstance(s, dict):
                continue
            approach = s.get("approach_used", "")
            param = str(s.get("parameter", ""))
            if approach in approach_groups:
                approach_groups[approach][param] = s
            else:
                # Scenarios without a recognized approach_used are skipped with a stderr warning
                print(
                    f"Warning: scenario '{param}' has unrecognized approach_used '{approach}', skipping",
                    file=sys.stderr,
                )

        html_parts: list[str] = []
        display_names = {"top_down": "Top-Down", "bottom_up": "Bottom-Up"}
        for approach_key in ("top_down", "bottom_up"):
            group_map = approach_groups[approach_key]
            if not group_map:
                continue
            group_base_som = _num(_as_dict(base_result.get(approach_key)).get("som", 0))
            group_ordered = _order_params(ranked_params, group_map)
            if not group_ordered:
                continue
            bar_data = _build_bar_data(group_ordered, group_map, group_base_som)
            heading = display_names[approach_key]
            html_parts.append(f"<h3>{heading}</h3>")
            html_parts.append(_render_tornado_svg(bar_data, group_base_som))

        if not html_parts:
            return '<div class="placeholder">No sensitivity data to display</div>'
        return "\n".join(html_parts)

    # --- Single-approach mode (backward compatible) ---
    base_som = _num(base_result.get("som", 0))
    bar_data = _build_bar_data(ordered_params, scenario_map, base_som)
    return _render_tornado_svg(bar_data, base_som)


# The shared-input detector and its helpers exist here and in compose_report.py.
# test_visualize_market_sizing.py parses both files and compares the bodies, so a drift reds rather
# than shipping two surfaces that disagree about what the founder is told. The label helpers
# (PARAM_LABELS, _humanize_param, _humanize_claim) come from _redteam_text, one source for both.


# ---------------------------------------------------------------------------
# Chart 3: Top-down vs bottom-up comparison (grouped bars).
# NOT "cross-validation" -- that word asserts the comparison validates something. The pipeline
# cannot tell whether the two builds rest on the same underlying figures, so closeness is not
# confirmation. compose_report.py carries the same wording; the two surfaces ship together.
# ---------------------------------------------------------------------------


def _chart_cross_validation(
    sizing: dict[str, Any] | None,
    validation: dict[str, Any] | None = None,
    redo: str | None = None,
    scope: str | None = None,
) -> str:
    """Chart 3: Grouped bars comparing TD vs BU for TAM/SAM/SOM."""
    if sizing is None:
        return '<div class="placeholder">No data available</div>'
    if sizing is _CORRUPT:
        return '<div class="placeholder">Data unavailable</div>'
    if _is_stub(sizing):
        reason = _esc(sizing.get("reason", "Skipped"))
        return f'<div class="placeholder">{reason}</div>'

    td = sizing.get("top_down")
    bu = sizing.get("bottom_up")

    if not isinstance(td, dict) or not isinstance(bu, dict):
        return '<div class="placeholder">Comparing the two approaches requires both</div>'

    metrics = ["tam", "sam", "som"]
    td_vals = [_num(_as_dict(td.get(m)).get("value", 0)) for m in metrics]
    bu_vals = [_num(_as_dict(bu.get(m)).get("value", 0)) for m in metrics]

    # Check that at least one metric group has a positive value
    any_positive = any(max(td_vals[i], bu_vals[i]) > 0 for i in range(len(metrics)))
    if not any_positive:
        return '<div class="placeholder">No positive values to compare</div>'

    # SVG dimensions
    group_width = 120
    bar_width = 40
    bar_gap = 10
    chart_height = 200
    margin_top = 45  # room for max-scale label + tallest bar's value label
    margin_bottom = 40
    svg_w = len(metrics) * group_width + 60
    svg_h = chart_height + margin_top + margin_bottom

    parts: list[str] = [
        f'<svg width="{svg_w}" height="{svg_h}" viewBox="0 0 {svg_w} {svg_h}" xmlns="http://www.w3.org/2000/svg">'
    ]

    for i, metric in enumerate(metrics):
        gx = _num(30 + i * group_width + group_width / 2)
        td_v = td_vals[i]
        bu_v = bu_vals[i]

        # Per-metric group scaling: each TAM/SAM/SOM pair scales independently
        group_max = max(td_v, bu_v)
        if group_max <= 0:
            group_max = 1

        td_h = _num(td_v / group_max * chart_height)
        bu_h = _num(bu_v / group_max * chart_height)

        # Scale ceiling line + max label for this group
        # The ceiling line sits at margin_top where the tallest bar's top is.
        # Place the max label well above it (y=10) so it doesn't collide
        # with the tallest bar's value label (which sits at bar_top - 5).
        ceiling_y = _num(margin_top)
        group_left = _num(gx - bar_width - bar_gap)
        group_right = _num(gx + bar_width + bar_gap)
        parts.append(
            f'<line x1="{group_left:.2f}" y1="{ceiling_y:.2f}" '
            f'x2="{group_right:.2f}" y2="{ceiling_y:.2f}" '
            f'stroke="{_SVG_GRIDLINE}" stroke-width="1" />'
        )
        parts.append(
            f'<text x="{gx:.2f}" y="10.00" '
            f'text-anchor="middle" font-size="7" fill="{_SVG_TEXT_FAINT}">'
            f"max: {_esc(_fmt_usd(group_max))}</text>"
        )

        # TD bar
        td_x = _num(gx - bar_width - bar_gap / 2)
        td_y = _num(margin_top + chart_height - td_h)
        parts.append(
            f'<rect x="{td_x:.2f}" y="{td_y:.2f}" '
            f'width="{_num(bar_width):.2f}" height="{_num(td_h):.2f}" '
            f'fill="{_CLR_PRIMARY}" rx="3" />'
        )
        # TD value label
        parts.append(
            f'<text x="{_num(td_x + bar_width / 2):.2f}" y="{_num(td_y - 5):.2f}" '
            f'text-anchor="middle" font-size="8" fill="{_SVG_TEXT_DARK}">'
            f"{_esc(_fmt_usd(td_v))}</text>"
        )

        # BU bar
        bu_x = _num(gx + bar_gap / 2)
        bu_y = _num(margin_top + chart_height - bu_h)
        parts.append(
            f'<rect x="{bu_x:.2f}" y="{bu_y:.2f}" '
            f'width="{_num(bar_width):.2f}" height="{_num(bu_h):.2f}" '
            f'fill="#48B4EA" rx="3" />'
        )
        # BU value label
        parts.append(
            f'<text x="{_num(bu_x + bar_width / 2):.2f}" y="{_num(bu_y - 5):.2f}" '
            f'text-anchor="middle" font-size="8" fill="{_SVG_TEXT_DARK}">'
            f"{_esc(_fmt_usd(bu_v))}</text>"
        )

        # Metric label
        label_y = _num(margin_top + chart_height + 15)
        parts.append(
            f'<text x="{gx:.2f}" y="{label_y:.2f}" '
            f'text-anchor="middle" font-size="12" fill="{_SVG_TEXT_DARK}" '
            f'font-weight="bold">{_esc(metric.upper())}</text>'
        )

    parts.append("</svg>")

    legend = (
        '<div class="legend">'
        '<span class="legend-item">'
        f'<span class="legend-swatch" style="background:{_CLR_PRIMARY}"></span>'
        " Top-Down</span>"
        '<span class="legend-item">'
        '<span class="legend-swatch" style="background:#48B4EA"></span>'
        " Bottom-Up</span>"
        "</div>"
    )

    # The same sentence group per metric that report.md prints under its sizing table.
    # compose_report.py owns the wording (`_comparison_sentences`); this is a copy because skill
    # scripts are standalone and cannot import across files. Keep the two in step -- the producer
    # computed sam_note/som_note for a long time with NO consumer on either surface, which is the
    # defect this renders away.
    comparison = _as_dict(sizing.get("comparison"))
    note_html = ""
    if comparison:
        leads: list[str] = []
        rest: list[str] = []
        for delta_key, note_key, warn_key in (
            ("tam_delta_pct", "note", "warning"),
            ("sam_delta_pct", "sam_note", "sam_warning"),
            ("som_delta_pct", "som_note", "som_warning"),
        ):
            if delta_key not in comparison:
                continue
            text = _view.legacy_gap_tail(str(comparison.get(warn_key) or comparison.get(note_key) or "").strip())
            if not text:
                continue
            for i, raw in enumerate([s.strip() for s in text.split(". ") if s.strip()]):
                sentence = raw if raw.endswith(".") else raw + "."
                target = leads if i == 0 else rest
                if sentence not in leads and sentence not in rest:
                    target.append(sentence)
        # The same shared-input sentences report.md appends to its comparison paragraph -- and the
        # same caveat swap (compose_report.py `_comparison_paragraph`): once a shared figure has
        # been SEEN, "the pipeline cannot tell" is contradicted by the next sentence.
        text = " ".join(leads + rest)
        shared_details = [str(_shared["detail"]) for _shared in _shared_input_values(sizing, validation)]
        if shared_details:
            producer_caveat = (
                "Closeness is not confirmation: the pipeline cannot tell whether the two builds rest on "
                "the same underlying figures. Check whether they do."
            )
            seen_caveat = (
                "Closeness is not confirmation \u2014 and where the inputs are itemized, the pipeline "
                "can see what the two builds share:"
            )
            text = (
                (text.replace(producer_caveat, seen_caveat) if producer_caveat in text else text)
                + " "
                + " ".join(shared_details)
            )
        if redo:
            # The comparison redo's sentence, from the one owner report.md prints it from (_view.redo_sentence).
            text = f"{text} {redo}" if text.strip() else redo
        if scope:
            # What each build's TAM is built from, from the one owner report.md prints it from (_view.scope_sentence).
            text = f"{text} {scope}" if text.strip() else scope
        if text.strip():
            note_html = '<p class="chart-note">' + _esc(text) + "</p>"

    return '<div class="chart-container">' + "\n".join(parts) + "</div>" + legend + note_html


# ---------------------------------------------------------------------------
# Chart 4: Assumption Confidence Donut
# ---------------------------------------------------------------------------


def _chart_confidence_donut(validation: dict[str, Any] | None, sizing: dict[str, Any] | None = None) -> str:
    """Chart 4: Donut chart of the grades the research and the sizing's estimates EARNED.

    Counts `_view.assumption_rows`, the same rows report.md's Assumptions section lists, so the two
    pages cannot grade one figure two ways. Each estimate the sizing used is listed under the chart
    with its reason and the research it departed from.
    """
    if validation is None:
        return '<div class="placeholder">No data available</div>'
    if validation is _CORRUPT:
        return '<div class="placeholder">Data unavailable</div>'
    if _is_stub(validation):
        reason = _esc(validation.get("reason", "Skipped"))
        return f'<div class="placeholder">{reason}</div>'

    rows = _view.assumption_rows(validation, sizing)
    if not rows:
        return '<div class="placeholder">No assumptions recorded</div>'

    # Count by grade in canonical order
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["grade"]] = counts.get(row["grade"], 0) + 1

    # Build segments in canonical order, then unknown categories alphabetically
    segments: list[tuple[str, float, str]] = []
    for cat in _CONFIDENCE_CATEGORIES:
        if cat in counts:
            color = _CONFIDENCE_COLORS.get(cat, _CLR_NA)
            segments.append((cat, float(counts[cat]), color))

    unknown_cats = sorted(set(counts.keys()) - set(_CONFIDENCE_CATEGORIES))
    for cat in unknown_cats:
        segments.append((cat, float(counts[cat]), _CLR_NA))

    if not segments:
        return '<div class="placeholder">No assumptions recorded</div>'

    svg = _svg_donut(segments)

    cat_labels = {"sourced": "Sourced", "derived": "Derived", "agent_estimate": "Agent Estimate"}
    legend_items: list[str] = []
    for cat, val, color in segments:
        label = _esc(cat_labels.get(cat, cat.replace("_", " ").title()))
        legend_items.append(
            f'<span class="legend-item">'
            f'<span class="legend-swatch" style="background:{_esc(color)}"></span>'
            f" {label}: {int(val)}</span>"
        )
    legend = '<div class="legend">' + "".join(legend_items) + "</div>"

    notes = "".join(
        f'<p class="estimate-note"><strong>{_esc(r["label"])}</strong> = {_esc(r["shown"])} (estimate) '
        f"— {_esc(r['note'])}</p>"
        for r in rows
        if r["kind"] == "estimate"
    )

    # How many sourced figures the sizing uses carry a recorded passage: report.md's Sources Used sentence,
    # from its one owner. "uses" is what separates it from the legend above, which counts unused research too.
    quoted = _view.quote_sentence(validation, sizing)
    if quoted:
        notes += f'<p class="estimate-note">{_esc(quoted)}</p>'

    return '<div class="chart-container">' + svg + "</div>" + legend + notes


# ---------------------------------------------------------------------------
# Chart 5: Checklist Status Donut
# ---------------------------------------------------------------------------


def _checklist_section(checklist: dict[str, Any] | None) -> str:
    """Every self-check criterion, grouped by category in the order `checklist.py` lists them.

    market-sizing grades pass / fail / not applicable only, so the filters offer no Warn chip. Each
    item's `notes` is the text shown under it, through the same founder-text pass report.md's rows take
    (`_view._founder_prose`).
    """
    if checklist is None:
        return '<div class="placeholder">No data available</div>'
    if checklist is _CORRUPT:
        return '<div class="placeholder">Data unavailable</div>'
    if _is_stub(checklist):
        reason = _esc(checklist.get("reason", "Skipped"))
        return f'<div class="placeholder">{reason}</div>'
    items = [i for i in _as_list(checklist.get("items")) if isinstance(i, dict)]
    if not items:
        return '<div class="placeholder">No checklist data</div>'

    order: list[str] = []
    by_cat: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        cat = str(item.get("category") or "Other")
        if cat not in by_cat:
            order.append(cat)
            by_cat[cat] = []
        by_cat[cat].append(item)

    groups: list[dict[str, Any]] = []
    for cat in order:
        rows: list[dict[str, Any]] = []
        passed = applicable = 0
        for item in by_cat[cat]:
            tone = _CHECKLIST_TONE.get(str(item.get("status")), "na")
            if tone != "na":
                applicable += 1
                passed += tone == "pass"
            notes = item.get("notes")
            rows.append(
                {
                    "tone": tone,
                    "title": str(item.get("label") or "").strip() or "Checklist item",
                    "criterion": str(item.get("id") or ""),
                    "evidence": _view._founder_prose(str(notes).strip()) if notes is not None else "",
                }
            )
        count = f"{passed}/{applicable} pass" if applicable else "Not applicable"
        groups.append({"name": cat, "count_text": count, "items": rows})
    return _ui.checklist(groups, statuses=("fail", "pass", "na"))


# The self-check's statuses onto the page's tones (market-sizing has no warn).
_CHECKLIST_TONE = {"pass": "pass", "fail": "fail", "not_applicable": "na"}

# The ring's colour per band: the two upper bands read as pass, the lower two as warn and fail.
_BAND_TONE = {"strong": "pass", "solid": "pass", "needs_work": "warn", "major_revision": "fail"}


def _score_ring(checklist: dict[str, Any] | None) -> str:
    """The header's ring: the self-check score report.md's summary states, linking to the checklist.

    The band is the one `checklist.py` wrote; one this page does not know is banded from the score by
    the same module that scored it.
    """
    if not _usable(checklist):
        return ""
    summary = _as_dict(checklist.get("summary"))
    raw = summary.get("score_pct")
    if not isinstance(raw, (int, float)) or isinstance(raw, bool):
        return ""
    pct = max(0.0, min(100.0, float(raw)))
    band = str(summary.get("overall_status") or "")
    if band not in _BAND_TONE:
        band = _thresholds.band_for(pct)
    band_text = band.replace("_", " ").title()
    return _ui.score_ring(
        pct,
        tone=_BAND_TONE.get(band, "neutral"),
        value_text=f"{_ui.score_text(pct)}%",
        label="Self-check",
        caption=band_text,
        aria_label=f"Self-check {_ui.score_text(pct)} percent, {band_text}",
        href="#checklist",
    )


def _chart_provenance_summary(
    provenance: dict[str, dict[str, Any]] | None,
    sizing: dict[str, Any] | None = None,
    validation: dict[str, Any] | None = None,
    inputs: dict[str, Any] | None = None,
    redteam: dict[str, Any] | None = None,
) -> str:
    """Render provenance summary HTML table below funnels."""
    if not provenance:
        return ""

    rows: list[str] = []
    close_agreement = False
    # The same marks report.md's summary table carries, from the same detector: a dagger for two
    # builds that are ONE computation, a double dagger for two builds narrowing by the SAME number.
    # From `_shared_input_values`, never from the warning list -- acceptance must not remove them.
    shared = _shared_input_values(_as_dict(sizing), validation)
    identity_metrics = {str(x["metric"]) for x in shared if x["kind"] == "identity"}
    shared_metrics = {str(x["metric"]) for x in shared if x["kind"] in ("equal_value", "shared_factor")}
    contested_rows = _contested_rows(sizing, inputs, redteam)
    for approach_key in ("top_down", "bottom_up"):
        if approach_key not in provenance:
            continue
        method = "Top-down" if approach_key == "top_down" else "Bottom-up"
        for metric in ("tam", "sam", "som"):
            prov = _as_dict(provenance[approach_key].get(metric))
            classification = prov.get("classification", "")
            deck_claim = prov.get("deck_claim")
            delta = prov.get("delta_vs_deck_pct")
            if not classification:
                continue

            badge_colors = {
                "sourced": _CLR_PASS,
                "derived": _CLR_WARN,
                "agent_estimate": _CLR_FAIL,
                "unknown": _CLR_NA,
            }
            badge_labels = {
                "sourced": "Sourced",
                "derived": "Derived",
                "agent_estimate": "Agent Estimate",
                "unknown": "Unknown",
            }
            grade_key = classification if classification in badge_colors else "unknown"
            label = badge_labels.get(classification, classification)

            # The CONVERTED claim, matching report.md. Rendering the raw one made the two
            # deliverables print different numbers for the same field, and `_fmt_usd` suffixes the
            # ANALYSIS currency -- so a raw EUR figure came out tagged ILS.
            # `is not None`, not `or`: a legitimate comparable of 0.0 is falsy.
            _comparable = prov.get("deck_claim_comparable")
            _shown_claim = deck_claim if _comparable is None else _comparable
            deck_claim_num = _try_float(_shown_claim) if _shown_claim is not None else None
            _high_num = _try_float(prov.get("deck_claim_high_comparable"))
            deck_str = _esc(_view.claim_display(deck_claim_num, _high_num)) if deck_claim_num is not None else "\u2014"
            # An em-dash reads as missing data; a horizon mismatch is two figures for different
            # periods. Mirrors report.md.
            _hm_prov = _as_dict(prov.get("horizon_mismatch"))
            if _hm_prov:
                delta_str = _esc(
                    f"different horizon ({_hm_prov.get('claim_months')} vs {_hm_prov.get('ours_months')} mo)"
                )
            elif prov.get("within_claim_range"):
                delta_str = "within your range"
            elif delta is not None:
                delta_str = _esc(_params.fmt_delta(delta, signed=True))
            else:
                delta_str = "\u2014"
            if (
                delta is not None
                and abs(delta) <= CLOSE_AGREEMENT_PCT
                and not prov.get("comparison_blocked")
                and not prov.get("within_claim_range")
            ):
                delta_str += " *"
                close_agreement = True

            # Look up the agent's calculated estimate from sizing data
            estimate_str = "\u2014"  # em dash fallback
            if sizing is not None:
                approach_sizing = _as_dict(sizing.get(approach_key))
                metric_data = _as_dict(approach_sizing.get(metric))
                estimate_num = _try_float(metric_data.get("value"))
                if estimate_num is not None:
                    estimate_str = _esc(_fmt_usd(estimate_num))

            mark = (
                ("\u2020" if metric in identity_metrics else "")
                + ("\u2021" if metric in shared_metrics else "")
                + ("\u00a7" if (approach_key, metric) in contested_rows else "")
            )
            rows.append(
                f"<tr>"
                f"<td>{_esc(metric.upper())} ({_esc(method)}){(' ' + mark) if mark else ''}</td>"
                f'<td class="ms-grade ms-grade--{_esc(grade_key)}">{_esc(label)}</td>'
                f"<td>{estimate_str}</td>"
                f"<td>{deck_str}</td>"
                f"<td>{delta_str}</td>"
                f"</tr>"
            )

    if not rows:
        return ""

    headers = "".join(
        f"<th>{label}</th>" for label in ("Metric", "Classification", "Our Estimate", "Your Figure", "Delta")
    )
    footnote = ""
    if identity_metrics:
        footnote += (
            '<p class="ms-foot">&dagger; '
            + _esc(" ".join(str(x["detail"]) for x in shared if x["kind"] == "identity"))
            + " Agreement on these rows is arithmetic, not corroboration.</p>"
        )
    if shared_metrics:
        footnote += (
            '<p class="ms-foot">&Dagger; Both builds '
            "narrow this figure by the same number(s), so on it they are not independent checks of each other: "
            + _esc(" ".join(str(x["detail"]) for x in shared if x["kind"] in ("equal_value", "shared_factor")))
            + "</p>"
        )
    if contested_rows:
        footnote += (
            '<p class="ms-foot">&sect; Built on a '
            "figure you stated that a cited source contradicts; see Adversarial Findings.</p>"
        )
    for _item in _view.claim_disagreements(inputs):
        # The same sentence report.md's warning carries, from the same owner.
        footnote += '<p class="ms-foot ms-foot--warn">' + _esc(_view.disagreement_sentence(_item)) + "</p>"
    if close_agreement:
        footnote += (
            '<p class="ms-foot">'
            f"* Within {CLOSE_AGREEMENT_PCT:.0f}% of the figure you gave. "
            "Agreement on a number is not independent confirmation &mdash; it can mean both "
            "analyses drew on the same source, or that our input came from a figure you gave. "
            "To get a real check, size it again from an independently chosen value.</p>"
        )
    return (
        '<div class="ms-prov"><div class="ui-table-wrap"><table class="ui-table">'
        "<tr>" + headers + "</tr>" + "".join(rows) + "</table></div>" + footnote + "</div>"
    )


_SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}


def _chart_adversarial(
    redteam: dict[str, Any] | None,
    names: dict[str, str] | None = None,
    review_note: str | None = None,
    review_changes: list[str] | None = None,
    sizing: Any = None,
    inputs: Any = None,
    later: list[tuple[int, dict[str, Any]]] | None = None,
) -> str:
    """Mirror of compose_report.py's Adversarial Findings section.

    Three states that must read DIFFERENTLY -- never ran, ran and found nothing, ran and found
    something. Collapsing the first two lets a founder read a clean report as a checked one.
    """
    if redteam is None:
        return (
            '<p class="placeholder">No adversarial review ran. Nothing in this report has been '
            "checked against an outside source that was trying to contradict it.</p>"
        )
    if redteam is _CORRUPT or _is_stub(redteam):
        return '<p class="placeholder">The adversarial review did not produce a readable result.</p>'

    findings = [f for f in _as_list(redteam.get("findings")) if isinstance(f, dict)]
    summary = _as_dict(redteam.get("summary"))
    dropped = int(summary.get("rejected") or 0)
    unchecked = _as_list(redteam.get("could_not_check"))

    def _named(text: str) -> str:
        # The founder's filenames as uploaded (see _upload_names). BEFORE _esc: an escaped
        # apostrophe or ampersand in a filename would no longer match the name it replaces.
        return _upload_names.humanize(text, names or {})

    def _finding_html(f: dict[str, Any]) -> str:
        claim = _esc(_named(_humanize_claim(str(f.get("claim_attacked") or "").strip())))
        truth = _esc(_named(_view.checked_multiples(str(f.get("what_is_true") or "").strip(), sizing, inputs)))
        quote = _esc(str(f.get("evidence_quote") or "").strip())
        title = _esc(str(f.get("source_title") or "").strip())
        url = _esc(str(f.get("source_url") or "").strip())
        if url == _INTERNAL_PROVENANCE:
            # Labelled, never linked -- see compose_report.py for why the two kinds of
            # evidence must stay distinguishable.
            cite = "from this analysis&rsquo; own output, not an outside source"
        elif url.startswith("document:"):
            # The founder's own page -- named, never linked; same wording as report.md.
            cite = _esc(_named(_document_cite(str(f.get("source_url") or "").strip())))
            verified = f.get("quote_verified")
            if verified is False:
                cite += " (this sentence was not found on that page)"
            elif verified is not True:
                cite += " (quoted from a page that could not be machine-read)"
        else:
            cite = f'<a href="{url}">{title or url}</a>' if url else ""
        tone = {"high": " ui-finding--fail", "medium": " ui-finding--warn"}.get(str(f.get("severity")), "")
        return (
            f'<div class="ui-finding{tone}" data-challenge><p class="ui-finding__title">{claim}</p>'
            f'<p class="ms-challenge__truth">{truth}</p>'
            + (f'<blockquote class="ms-quote">{quote}</blockquote>' if quote else "")
            + (f'<p class="ms-cite">&mdash; {cite}</p>' if cite else "")
            + "</div>"
        )

    outcome = _esc(_named(_adversarial_outcome(redteam, None)))
    parts: list[str] = []
    if review_note:
        parts.append(f"<p><em>{_esc(review_note)}</em></p>")
        if review_changes:
            items = "".join(f"<li>{_esc(c)}</li>" for c in review_changes)
            parts.append(f"<p>What changed:</p><ul>{items}</ul>")
    if not findings:
        parts.append(f"<p>{outcome} That is a result, not an absence of one.</p>")
    else:
        parts.append(f"<p>{outcome} Each quotes the sentence it relies on.</p>")
        for f in sorted(findings, key=lambda x: _SEVERITY_ORDER.get(str(x.get("severity")), 3)):
            parts.append(_finding_html(f))

    for n, doc in later or []:
        extra = [f for f in _as_list(_as_dict(doc).get("findings")) if isinstance(f, dict)]
        parts.append(f"<h3>A later review of the same analysis (review {n})</h3>")
        if not extra:
            parts.append("<p>It raised no challenges.</p>")
        for f in sorted(extra, key=lambda x: _SEVERITY_ORDER.get(str(x.get("severity")), 3)):
            parts.append(_finding_html(f))

    if unchecked:
        items = "".join(f"<li>{_esc(_named(str(u).strip()))}</li>" for u in unchecked)
        parts.append(f"<p><strong>Not checked</strong></p><ul>{items}</ul>")

    if dropped:
        noun = "challenge" if dropped == 1 else "challenges"
        was = "it was" if dropped == 1 else "they were"
        its = "its" if dropped == 1 else "their"
        parts.append(
            f'<p class="ms-foot">{dropped} further {noun} '
            f"could not be shown here because {was} incomplete or did not cite {its} evidence "
            "in a form that can be checked.</p>"
        )

    return "".join(parts)


# A card is either one sentence, or (criterion id, eyebrow, title, body): a failed criterion's label as
# its title, its category above it and its notes below, so nothing on the card repeats.
_Card = str | tuple[str, str, str, str]


def _chart_key_findings(
    checklist: dict[str, Any] | None,
    validation: dict[str, Any] | None,
    provenance: dict[str, dict[str, Any]] | None,
) -> str:
    """Key Findings: what's strong and what needs attention, as cards. No "Top actions" column: each action
    only restated an attention card ("Address: <the failed criterion>").

    A failed criterion's card is its label as the title, its category above and its notes below, so
    nothing repeats; every other finding is one sentence. Each column shows its first three and puts the
    rest behind "N more", so nothing is dropped from the page.
    """
    strong: list[_Card] = []
    attention: list[_Card] = []

    # --- Checklist findings ---
    if _usable(checklist):
        items = _as_list(checklist.get("items"))
        pass_count = sum(1 for i in items if isinstance(i, dict) and i.get("status") == "pass")
        total = sum(1 for i in items if isinstance(i, dict) and i.get("status") != "not_applicable")
        if total > 0 and pass_count / total >= 0.7:
            strong.append(f"Checklist: {pass_count} of {total} criteria pass")
        for item in items:
            if not isinstance(item, dict):
                continue
            if item.get("status") == "fail":
                label = str(item.get("label", item.get("id", "Unknown")))
                raw_notes = item.get("notes")
                notes = _view._founder_prose(str(raw_notes)) if raw_notes is not None else ""
                attention.append((str(item.get("id") or ""), str(item.get("category") or ""), label, notes))

    # --- Validation findings ---
    if _usable(validation):
        confirmed = 0
        total_figs = 0
        for fig in _as_list(validation.get("figure_validations")):
            if not isinstance(fig, dict):
                continue
            total_figs += 1
            status = fig.get("status", "")
            if status == "validated":
                confirmed += 1
            elif status in ("refuted", "unsupported"):
                figure_name = str(fig.get("figure", "Unknown"))
                raw_notes = fig.get("notes")
                notes = str(raw_notes) if raw_notes is not None else ""
                prefix = "Refuted" if status == "refuted" else "Unsupported"
                text = f"{prefix}: {figure_name}" + (f" — {notes}" if notes else "")
                attention.append(text)
        if total_figs > 0 and confirmed / total_figs >= 0.7:
            strong.append(f"{confirmed} of {total_figs} figures independently validated")

    # --- Provenance / delta findings ---
    if provenance:
        for approach_key in ("top_down", "bottom_up"):
            if approach_key not in provenance:
                continue
            method = "Top-down" if approach_key == "top_down" else "Bottom-up"
            for metric in ("tam", "sam", "som"):
                prov = _as_dict(provenance[approach_key].get(metric))
                delta = prov.get("delta_vs_deck_pct")
                # REPLACED, not suppressed. The delta is now None whenever the comparison was
                # refused, so neither arm below can speak across currencies -- but dropping the
                # item silently would leave the founder nothing, which is what the previous
                # comment here objected to. Say what could not be checked and what would fix it.
                if delta is None and prov.get("comparison_blocked") and prov.get("deck_claim") is not None:
                    attention.append(
                        f"{metric.upper()} ({method}): could not be checked against your own "
                        f"figure — no currency was stated for it, so we could not tell whether the "
                        f"two are comparable"
                    )
                if delta is not None and prov.get("within_claim_range"):
                    attention.append(
                        f"{metric.upper()} ({method}) is within the range you stated — "
                        f"agreement is not independent confirmation"
                    )
                elif delta is not None:
                    if abs(delta) <= CLOSE_AGREEMENT_PCT:
                        # NOT a strength. Landing on the founder's own number is the cheapest
                        # possible outcome — it happens when both analyses read the same source,
                        # or when our input came from their materials. Measured across a 3-deck
                        # corpus, every close agreement was the top-down TAM, and on one deck this
                        # line was the ONLY "what's strong" item in the report.
                        attention.append(
                            f"{metric.upper()} ({method}) is within {_params.fmt_delta(abs(delta))} of your own "
                            f"figure — agreement is not independent confirmation"
                        )
                    elif abs(delta) > DECK_MISMATCH_PCT:
                        # Same threshold compose_report.py uses for DECK_CLAIM_MISMATCH. Until
                        # today this arm read `> CLOSE_AGREEMENT_PCT`, so report.html flagged a
                        # divergence at >25% while report.md warned only above >50% -- two
                        # thresholds for one relationship across two surfaces the founder reads
                        # side by side. (The condition was also tautological after the `<=` arm.)
                        # The (25, 50] band is a known gap, documented at DECK_MISMATCH_PCT; it is
                        # closed in both surfaces at once or in neither.
                        attention.append(
                            f"{metric.upper()} ({method}): {_params.fmt_delta(delta, signed=True)} vs your figure"
                        )

    if not strong and not attention:
        return ""

    def _card(item: _Card, tone: str) -> str:
        if isinstance(item, str):
            return f'<div class="ui-finding ui-finding--{tone}">{_esc(item)}</div>'
        item_id, eyebrow, title, body = item
        eyebrow_html = f'<p class="ui-finding__eyebrow">{_esc(eyebrow)}</p>' if eyebrow else ""
        body_html = f'<p class="ui-finding__body">{_esc(body)}</p>' if body else ""
        return (
            f'<div class="ui-finding ui-finding--{tone}" data-finding="{_esc(item_id)}">'
            f'{eyebrow_html}<p class="ui-finding__title">{_esc(title)}</p>{body_html}</div>'
        )

    def _column(key: str, heading: str, items: list[_Card], tone: str, shown: int = 3) -> str:
        # The first three, then the rest behind a disclosure: a finding the page used to drop
        # silently past the third is now one click away, never gone.
        head, tail = items[:shown], items[shown:]
        more = (
            f'<details class="ui-more"><summary>{len(tail)} more</summary>'
            + "".join(_card(i, tone) for i in tail)
            + "</details>"
            if tail
            else ""
        )
        return (
            f'<div class="ui-finding-col" data-findings="{key}"><h3>{heading}</h3>'
            + "".join(_card(i, tone) for i in head)
            + more
            + "</div>"
        )

    parts: list[str] = []
    if strong:
        parts.append(_column("strong", "What's strong", strong, "pass"))
    if attention:
        parts.append(_column("attention", "What needs attention", attention, "fail"))

    return '<div class="ui-findings">' + "".join(parts) + "</div>"


# ---------------------------------------------------------------------------
# Main HTML composition
# ---------------------------------------------------------------------------


def compose_html(dir_path: str) -> str:
    """Render inside one currency scope: the default is back to USD when this returns or raises."""
    with _view.render_scope():
        return _compose_html(dir_path)


def _compose_html(dir_path: str) -> str:
    """Load artifacts and compose the HTML report.

    THIS IS A CHART DECK, NOT A SECOND RENDERING OF report.md, and the difference is deliberate.
    Measured 2026-09-21 on a replayed real run: report.md carries 40,516 characters across 12
    sections; this carries 5,190 across 6, and they are mostly DIFFERENT sections rather than a
    subset. Absent here by design: Methodology (and so its rationale), Definitions, Deck Claims
    (Narrative), Sources Used, and most warning prose.

    Do not read that as the two-renderer rule being broken. That rule exists because three
    August reviews in a row caught a FIX landing on one surface only, leaving a founder reading
    the HTML something the markdown had already corrected. It is about shared content staying in
    AGREEMENT, not about content parity -- and it is honoured: the TAM-identity caveat, the
    comparison caveat and the Adversarial Findings section all render here.

    So a field that lives only in report.md is not automatically a defect. Before adding one
    here, ask whether it is a CORRECTION to something both surfaces already say (it belongs
    here) or a section this deck never carried (it probably does not). The methodology rationale
    is the second kind, and there is a second reason to leave it out: it is model-written free
    text, which is the channel that produced this skill's 2026-09-21 defects. A field whose
    companions -- sources, definitions, validation prose -- are equally absent does not become
    consistent by adding it alone.

    The open question this does NOT settle, recorded so it is not mistaken for settled: whether a
    5,190-character deck with no sources and no validation is the right second deliverable at
    all. That is a product decision, not a rendering one.
    """
    scripts_dir = os.path.dirname(os.path.abspath(__file__))
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    import _theme

    all_names = REQUIRED_ARTIFACTS + OPTIONAL_ARTIFACTS
    artifacts: dict[str, dict[str, Any] | None] = {}
    for name in all_names:
        artifacts[name] = _load_artifact(dir_path, name)

    # This run's id, as compose_report.py reads it (stubs carry no analysis, so they do not vote).
    _rt_run_id = _redteam_copy.primary_run_id_in(dir_path, artifacts, REQUIRED_ARTIFACTS)
    # The same review report.md shows: its append-only copy, never `redteam.json` as it now stands.
    _rt_shown, _rt_codes, _rt_facts = _redteam_copy.resolve(
        dir_path,
        _rt_run_id,
        artifacts.get("redteam.json"),
        artifacts.get("methodology.json"),
        same_as_now=_view.review_matcher(
            artifacts.get("sizing.json") if isinstance(artifacts.get("sizing.json"), dict) else {},
            artifacts.get("validation.json"),
            artifacts.get("inputs.json"),
        ),
    )
    if _rt_facts["rounds"]:
        artifacts["redteam.json"] = _rt_shown

    # The same re-checked sizing report.md renders: an edited one is replaced by its recomputation.
    _sz_render, _ = _view.sizing_integrity(
        dir_path,
        _rt_run_id,
        artifacts.get("sizing.json"),
        artifacts.get("validation.json"),
        artifacts.get("inputs.json"),
        reviewed=bool(_rt_facts["rounds"]),
        review_facts=_rt_facts,
        methodology=artifacts.get("methodology.json"),
    )
    if _sz_render is not None:
        artifacts["sizing.json"] = _sz_render

    inputs = artifacts.get("inputs.json")
    sizing = artifacts.get("sizing.json")
    sensitivity = artifacts.get("sensitivity.json")
    validation = artifacts.get("validation.json")
    checklist = artifacts.get("checklist.json")

    # Resolve the analysis currency before rendering any money label.
    _set_currency(_resolve_currency(inputs, sizing))

    # Company name from inputs
    company_name = "Market Sizing Report"
    if _usable(inputs):
        company_name = str(inputs.get("company_name", "Market Sizing Report"))

    analysis_date = ""
    if _usable(inputs):
        analysis_date = str(inputs.get("analysis_date", ""))

    # Compute provenance
    provenance_data: dict[str, dict[str, Any]] | None = None
    if _usable(sizing) and (_usable(validation) or _usable(inputs)):
        provenance_data, _ = _compute_provenance(sizing, validation, inputs)

    # Build sections
    funnel_html = _chart_funnel(sizing)
    provenance_summary_html = _chart_provenance_summary(
        provenance_data, sizing, validation, inputs, _as_dict(artifacts.get("redteam.json")) or None
    )
    key_findings_html = _chart_key_findings(checklist, validation, provenance_data)
    tornado_html = _chart_tornado(sensitivity)
    cross_val_html = _chart_cross_validation(
        sizing,
        _as_dict(validation) or None,
        _view.redo_sentence(_view.redo_record(dir_path, _rt_run_id), validation),
        _view.scope_sentence(sizing, validation),
    )
    confidence_html = _chart_confidence_donut(validation, sizing)
    checklist_html = _checklist_section(checklist)
    _upload_display = _upload_names.for_redteam(artifacts.get("redteam.json"))
    adversarial_html = _chart_adversarial(
        artifacts.get("redteam.json"),
        _upload_display,
        _view.review_note(_rt_facts),
        _view.review_changes(_rt_facts, artifacts.get("validation.json"), _view._CURRENCY),
        sizing,
        inputs,
        _rt_facts.get("later"),
    )
    _answers = _view._your_answers_lines(artifacts.get("methodology.json"), inputs, dir_path, _gate_view(dir_path))
    answers_html = "<ul>" + "".join(f"<li>{_esc(line)}</li>" for line in _answers) + "</ul>" if _answers else ""
    # The same verdict paragraph report.md opens with -- the second renderer is where this class of
    # defect survives. Marks recomputed from the same detectors the provenance table uses.
    verdict_html = ""
    _rt_art = artifacts.get("redteam.json")
    _rt_for_verdict = _rt_art if _usable(_rt_art) else None
    _meth = artifacts.get("methodology.json")
    _skip = _as_dict(_meth).get("red_team_skipped") if _usable(_meth) else None
    if _usable(sizing) and not _is_stub(sizing):
        _shared_v = _shared_input_values(sizing, validation)
        _identity_v = {str(x["metric"]) for x in _shared_v if x["kind"] == "identity"}
        _shared_m = {str(x["metric"]) for x in _shared_v if x["kind"] in ("equal_value", "shared_factor")}
        _contested_v = _contested_rows(sizing, inputs, _rt_for_verdict)
        _marks = {
            (a, m): (
                (" \u2020" if m in _identity_v else "")
                + (" \u2021" if m in _shared_m else "")
                + (" \u00a7" if (a, m) in _contested_v else "")
            )
            for a in ("top_down", "bottom_up")
            for m in ("tam", "sam", "som")
        }
        _verdict_text, _ = _summary_verdict(
            sizing, provenance_data, checklist if _usable(checklist) else None, _rt_for_verdict, _skip, _marks, inputs
        )
        verdict_html = _esc(_upload_names.humanize(_verdict_text, _upload_display))
    else:
        _outcome = _esc(_upload_names.humanize(_adversarial_outcome(_rt_for_verdict, _skip), _upload_display))
        verdict_html = f"No sizing was produced; see Warnings. {_outcome}"

    basis_label = _sizing_basis_label(_resolve_sizing_basis(sizing, inputs))
    sizing_basis_line = f"<p>Sizing basis: {_esc(basis_label)}</p>"

    # FX disclosure. The HTML is a founder deliverable in its own right — someone reads it
    # without the markdown beside it — so a converted figure has to carry its rate HERE too,
    # not only in report.md. Empty string when nothing was converted, which is the norm.
    fx_line = ""
    _fx = sizing.get("fx") if isinstance(sizing, dict) else None
    _fx_conversions = _fx.get("conversions") if isinstance(_fx, dict) else None
    if isinstance(_fx_conversions, list) and _fx_conversions:
        _parts = []
        _target = "the analysis currency"
        for _c in _fx_conversions:
            if not isinstance(_c, dict):
                continue
            _parts.append(f"1 {_c.get('from')} = {_c.get('rate')} {_c.get('to')}")
            _target = str(_c.get("to") or _target)
        _fx_meta: dict[str, Any] = _fx if isinstance(_fx, dict) else {}
        _asof = _fx_meta.get("as_of") or "date not stated"
        _src = _fx_meta.get("source") or "source not stated"
        if _parts:
            fx_line = (
                f"<p>Converted into {_esc(_target)} at {_esc('; '.join(_parts))} "
                f"(as of {_esc(str(_asof))}, {_esc(str(_src))})</p>"
            )

    # The header card: the analysis date as a chip, the verdict paragraph report.md opens with, the
    # sizing basis and any conversion beneath it, and the self-check score as a ring.
    meta_html = f'<span class="ui-chip">{_esc(analysis_date)}</span>' if analysis_date else ""
    header = _ui.header_card(
        eyebrow="Market Sizing",
        title=company_name,
        meta_html=meta_html,
        verdict_html=verdict_html,
        body_html=f'<div class="ms-meta">{sizing_basis_line}{fx_line}</div>',
        ring_html=_score_ring(checklist),
    )

    sensitivity_lead = (
        '<p class="ms-lead">Wider bars = a wider stress range, which follows from how confident we are in '
        "each input &mdash; not from how much the answer depends on it. Focus on sourcing or validating the "
        "widest-stressed parameters first.</p>"
    )
    # (section id, heading, body). Optional sections drop out when empty.
    sections: list[tuple[str, str, str]] = [
        (
            "sizing",
            "TAM / SAM / SOM",
            f'<div class="ui-scroll"><div class="ms-wide">{funnel_html}</div></div>{provenance_summary_html}',
        ),
    ]
    if key_findings_html:
        sections.append(("findings", "Key Findings", key_findings_html))
    sections += [
        (
            "sensitivity",
            "Sensitivity Analysis",
            sensitivity_lead + f'<div class="ui-scroll"><div class="ms-wide">{tornado_html}</div></div>',
        ),
        ("comparison", "Top-down vs Bottom-up", cross_val_html),
        ("confidence", "Assumption Confidence", confidence_html),
        ("checklist", "Analysis Checklist", checklist_html),
        ("adversarial", "Adversarial Findings", adversarial_html),
    ]
    if answers_html:
        sections.append(("answers", "Your Answers", answers_html))

    nav = (
        '<nav class="ui-nav" aria-label="Sections">'
        + "".join(f'<a href="#{sid}">{_esc(title)}</a>' for sid, title, _ in sections)
        + "</nav>"
    )
    body = (
        header
        + nav
        + "".join(
            f'<section class="ui-section" id="{sid}" aria-labelledby="{sid}-h"><h2 id="{sid}-h">{_esc(title)}</h2>'
            f"{content}</section>"
            for sid, title, content in sections
        )
    )

    return _ui.page_shell(
        title=f"Market Sizing: {company_name}",
        body_html=body,
        brand_css=_theme.brand_css(),
        page_css=_css(),
        skill_name="Market Sizing",
        # The tornado bars' hover text (`data-tooltip`) is the one live tooltip in the fleet.
        scripts_html=_tooltip_js() + "\n",
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _gate_view(dir_path: str) -> dict[str, Any] | None:
    """The run ledger's answers, as compose reads them for "Your Answers"; None for a run without one."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import _ms_gates

    return _ms_gates.answers_view(dir_path)


def _run_ref_module() -> ModuleType:
    """The sibling `_run_ref`, loaded only when `--run-id` is given."""
    scripts_dir = os.path.dirname(os.path.abspath(__file__))
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    import _run_ref

    return _run_ref


def _own_run_id(dir_path: str) -> str | None:
    """This page's run id, as compose reads it."""
    artifacts = {name: _load_artifact(dir_path, name) for name in REQUIRED_ARTIFACTS + OPTIONAL_ARTIFACTS}
    return _redteam_copy.primary_run_id_in(dir_path, artifacts, REQUIRED_ARTIFACTS)


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    p = argparse.ArgumentParser(description="Generate HTML visualization from market sizing artifacts")
    p.add_argument("-d", "--dir", required=True, help="Directory containing JSON artifacts")
    p.add_argument("--pretty", action="store_true", help="Accepted for compatibility (no-op)")
    p.add_argument("-o", "--output", help="Write HTML to file instead of stdout")
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
                "inputs.json",
                "methodology.json",
                "validation.json",
                "sizing.json",
                "checklist.json",
                "sensitivity.json",
                "redteam.json",
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
                    "inputs.json",
                    "methodology.json",
                    "validation.json",
                    "sizing.json",
                    "checklist.json",
                    "sensitivity.json",
                )
            ],
            noun="analysis dir",
        )
        _IGNORED_OTHER_RUN.update(
            n
            for n, _r in _run_ref.foreign_artifacts(
                args.dir, args.run_id, [os.path.join(args.dir, n) for n in ("redteam.json",)]
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

    html_output = compose_html(args.dir)
    if args.run_id is not None:
        html_output = _run_ref_module().page_for_run(html_output, args.run_id, _own_run_id(args.dir))
    _write_output(html_output, args.output)
    if args.run_id is not None and args.output:
        _run_ref_module().list_page(args.dir, args.run_id, "report_html", args.output, "visualize.py")


if __name__ == "__main__":
    main()
