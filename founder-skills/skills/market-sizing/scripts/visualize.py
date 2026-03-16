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
from typing import Any, TypeGuard

# ---------------------------------------------------------------------------
# Artifact loading infrastructure (duplicated from compose_report.py per PEP 723)
# ---------------------------------------------------------------------------

_CORRUPT: dict[str, Any] = {"__corrupt__": True}

REQUIRED_ARTIFACTS = [
    "inputs.json",
    "methodology.json",
    "validation.json",
    "sizing.json",
    "checklist.json",
]
OPTIONAL_ARTIFACTS = ["sensitivity.json"]

# Canonical category order for assumption confidence donut
_CONFIDENCE_CATEGORIES: list[str] = ["sourced", "derived", "agent_estimate"]

# Quantitative params that participate in provenance classification
QUANTITATIVE_PARAMS = {
    "customer_count",
    "arpu",
    "serviceable_pct",
    "target_pct",
    "industry_total",
    "segment_pct",
    "share_pct",
}


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


def _fmt_usd(value: float | int) -> str:
    """Format a number as compact USD currency string."""
    if value >= 1_000_000_000:
        return f"${value / 1_000_000_000:,.1f}B"
    if value >= 1_000_000:
        return f"${value / 1_000_000:,.1f}M"
    if value >= 1_000:
        return f"${value / 1_000:,.1f}K"
    return f"${value:,.2f}"


def _compute_delta(calculated: float, deck_claim: Any) -> float | None:
    """Returns signed percentage delta, or None if claim is invalid."""
    try:
        claim = float(deck_claim)
    except (TypeError, ValueError):
        return None
    if claim <= 0:
        return None
    return round((calculated - claim) / claim * 100, 1)


def _compute_provenance(
    sizing: dict[str, Any],
    validation: dict[str, Any] | None,
    inputs: dict[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    """Compute provenance classification for each TAM/SAM/SOM figure."""
    assumption_map: dict[str, str] = {}
    if validation is not None and not _is_stub(validation):
        for assumption in _as_list(validation.get("assumptions")):
            if isinstance(assumption, dict):
                name = assumption.get("name", "")
                cat = assumption.get("category", "")
                if name and cat:
                    assumption_map[name] = cat

    existing_claims: dict[str, Any] = {}
    if inputs is not None and not _is_stub(inputs):
        existing_claims = _as_dict(inputs.get("existing_claims"))

    provenance: dict[str, dict[str, Any]] = {}
    for approach_key in ("top_down", "bottom_up"):
        approach_data = sizing.get(approach_key)
        if approach_data is None:
            continue
        approach_prov: dict[str, Any] = {}
        for metric in ("tam", "sam", "som"):
            m = _as_dict(approach_data.get(metric))
            figure_inputs = _as_dict(m.get("inputs"))
            relevant_inputs = {k: v for k, v in figure_inputs.items() if k in QUANTITATIVE_PARAMS}

            input_provenances: dict[str, str] = {}
            for param_name in relevant_inputs:
                if param_name in assumption_map:
                    input_provenances[param_name] = assumption_map[param_name]

            if not input_provenances:
                classification = "unknown"
            else:
                categories = set(input_provenances.values())
                if "agent_estimate" in categories:
                    classification = "agent_estimate"
                elif categories == {"sourced"}:
                    classification = "sourced"
                else:
                    classification = "derived"

            breakdown: dict[str, int] = {"sourced": 0, "derived": 0, "agent_estimate": 0}
            for cat in input_provenances.values():
                if cat in breakdown:
                    breakdown[cat] += 1

            deck_claim = existing_claims.get(metric)
            value = m.get("value", 0)
            delta = _compute_delta(float(value), deck_claim) if deck_claim is not None else None

            approach_prov[metric] = {
                "classification": classification,
                "confidence_breakdown": breakdown,
                "deck_claim": deck_claim,
                "delta_vs_deck_pct": delta,
                "input_provenances": input_provenances,
            }
        provenance[approach_key] = approach_prov
    return provenance


# ---------------------------------------------------------------------------
# Color scheme
# ---------------------------------------------------------------------------

_TORNADO_LABEL_FONT = 8

# Dash patterns — each must be unique to enable targeted test assertions
_DASH_LEADER_LINE = "2,2"  # leader lines from labels to small circles
_DASH_CLAMPED_CIRCLE = "3,2"  # floor-clamped circles ("not to scale")
# Existing: tornado baseline uses "4,3" (already hardcoded in _chart_tornado)

_SAM_LABEL_FONT = 10  # px, SAM label font size in funnel chart

_CLR_PRIMARY = "#0d549d"
_CLR_ACCENT = "#21a2e3"
_CLR_PASS = "#10b981"
_CLR_WARN = "#f59e0b"
_CLR_FAIL = "#ef4444"
_CLR_NA = "#9ca3af"

_CONFIDENCE_COLORS: dict[str, str] = {
    "sourced": _CLR_PASS,
    "derived": _CLR_WARN,
    "agent_estimate": _CLR_FAIL,
}

_CHECKLIST_COLORS: dict[str, str] = {
    "pass": _CLR_PASS,
    "fail": _CLR_FAIL,
    "not_applicable": _CLR_NA,
}


# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------


def _css() -> str:
    """Return inline CSS for the report."""
    return f"""
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
                         Helvetica, Arial, sans-serif;
            line-height: 1.6;
            color: #1f2937;
            background: #f9fafb;
            padding: 2rem;
            max-width: 960px;
            margin: 0 auto;
        }}
        header {{
            border-bottom: 3px solid {_CLR_PRIMARY};
            padding-bottom: 1rem;
            margin-bottom: 2rem;
        }}
        header h1 {{
            color: {_CLR_PRIMARY};
            font-size: 1.75rem;
        }}
        header p {{
            color: #6b7280;
            font-size: 0.875rem;
        }}
        main section {{
            background: #ffffff;
            border: 1px solid #e5e7eb;
            border-radius: 0.5rem;
            padding: 1.5rem;
            margin-bottom: 1.5rem;
        }}
        main section h2 {{
            color: {_CLR_PRIMARY};
            font-size: 1.25rem;
            margin-bottom: 1rem;
            border-bottom: 1px solid #e5e7eb;
            padding-bottom: 0.5rem;
        }}
        .chart-container {{
            display: flex;
            justify-content: center;
            align-items: center;
            flex-wrap: wrap;
            gap: 2rem;
        }}
        .placeholder {{
            text-align: center;
            color: #9ca3af;
            font-style: italic;
            padding: 2rem;
            background: #f3f4f6;
            border-radius: 0.25rem;
        }}
        .legend {{
            display: flex;
            justify-content: center;
            gap: 1.5rem;
            flex-wrap: wrap;
            margin-top: 1rem;
            font-size: 0.85rem;
        }}
        .legend-item {{
            display: flex;
            align-items: center;
            gap: 0.35rem;
        }}
        .legend-swatch {{
            width: 14px;
            height: 14px;
            border-radius: 3px;
            display: inline-block;
        }}
        footer {{
            text-align: center;
            color: #9ca3af;
            font-size: 0.75rem;
            padding-top: 1rem;
            border-top: 1px solid #e5e7eb;
        }}
        footer a, header a {{ color: {_CLR_ACCENT}; text-decoration: none; }}
        footer a:hover, header a:hover {{ text-decoration: underline; }}
        .collapsible-toggle {{
            cursor: pointer;
            user-select: none;
            display: flex;
            align-items: center;
            gap: 0.5rem;
            padding: 0.5rem 0;
        }}
        .collapsible-toggle:hover {{ background: #f3f4f6; border-radius: 0.25rem; }}
        .chevron {{
            display: inline-block;
            transition: transform 0.2s;
            font-size: 0.75rem;
            color: #9ca3af;
        }}
        .collapsible-content {{ padding-left: 1.5rem; }}
        .finding-item {{
            padding: 0.75rem;
            border-left: 3px solid #e5e7eb;
            margin-bottom: 0.5rem;
            border-radius: 0 0.25rem 0.25rem 0;
        }}
        .finding-strong {{ border-left-color: {_CLR_PASS}; }}
        .finding-attention {{ border-left-color: {_CLR_FAIL}; }}
        .finding-action {{ border-left-color: {_CLR_ACCENT}; }}
        .findings-subsection {{ margin-bottom: 1rem; }}
        .findings-subsection h3 {{
            font-size: 0.9rem;
            color: #374151;
            margin-bottom: 0.5rem;
        }}
        .confidence-badge {{
            display: inline-block;
            padding: 0.1rem 0.4rem;
            border-radius: 0.25rem;
            font-size: 0.65rem;
            font-weight: 600;
            color: #fff;
            margin-left: 0.25rem;
            vertical-align: middle;
        }}
        @media print {{
            body {{ background: #fff; padding: 0; }}
            main section {{ break-inside: avoid; border: 1px solid #ccc; }}
            header {{ border-bottom-color: #000; }}
            header h1 {{ color: #000; }}
            .collapsible-content {{ display: block !important; }}
            .collapsible-toggle .chevron {{ display: none; }}
            [data-tooltip] {{ cursor: default; }}
        }}
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
        "    tip.style.cssText = 'position:fixed;padding:8px 12px;background:#1f2937;color:#fff;'\n"
        "        + 'border-radius:6px;font-size:12px;max-width:300px;pointer-events:none;'\n"
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


def _collapsible_js() -> str:
    """Return inline JS for collapsible sections."""
    return (
        "<script>\n"
        "document.addEventListener('DOMContentLoaded', function() {\n"
        "    document.querySelectorAll('.collapsible-toggle').forEach(function(btn) {\n"
        "        btn.addEventListener('click', function() {\n"
        "            var content = this.nextElementSibling;\n"
        "            var chevron = this.querySelector('.chevron');\n"
        "            if (content.style.display === 'none') {\n"
        "                content.style.display = 'block';\n"
        "                if (chevron) chevron.style.transform = 'rotate(90deg)';\n"
        "            } else {\n"
        "                content.style.display = 'none';\n"
        "                if (chevron) chevron.style.transform = 'rotate(0deg)';\n"
        "            }\n"
        "        });\n"
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
        return '<text x="100" y="100" text-anchor="middle" fill="#9ca3af">No data</text>'

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
        f'fill="#1f2937">{_esc(str(total_int))}</text>'
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

_FUNNEL_COLORS = {
    "tam": "#0d549d",
    "sam": "#1b5fb2",
    "som": "#48b2e8",
}


def _chart_funnel_single(
    approach_data: dict[str, Any],
    label: str,
    cx: float,
    cy: float,
    max_r: float,
    label_side: str | None = None,
) -> str:
    """Render a single concentric-circle funnel centered at (cx, cy).

    label_side: "left" or "right" to place TAM/SAM/SOM labels externally
    with horizontal leader lines. None = centered labels (single-approach).
    """
    tam_val = _num(_as_dict(approach_data.get("tam")).get("value", 0))
    sam_val = _num(_as_dict(approach_data.get("sam")).get("value", 0))
    som_val = _num(_as_dict(approach_data.get("som")).get("value", 0))

    # Radii proportional to value, with TAM as outermost
    if tam_val <= 0:
        return f'<text x="{cx:.2f}" y="{cy:.2f}" text-anchor="middle" fill="#9ca3af" font-size="12">No TAM data</text>'

    r_tam = _num(max_r)
    r_sam_proportional = _num(max_r * math.sqrt(max(sam_val, 0) / tam_val)) if tam_val > 0 else 0.0
    r_som_proportional = _num(max_r * math.sqrt(max(som_val, 0) / tam_val)) if tam_val > 0 else 0.0

    # Apply minimum floors for visibility and track clamping
    r_sam = max(_num(r_sam_proportional), 15.0)
    r_som = max(_num(r_som_proportional), 8.0)
    sam_clamped = r_sam_proportional < 15.0
    som_clamped = r_som_proportional < 8.0

    # Dashed stroke for floor-clamped circles to signal "not to scale"
    sam_dash = f' stroke-dasharray="{_DASH_CLAMPED_CIRCLE}"' if sam_clamped else ""
    som_dash = f' stroke-dasharray="{_DASH_CLAMPED_CIRCLE}"' if som_clamped else ""

    parts: list[str] = []

    # TAM circle (outermost)
    parts.append(f'<circle cx="{cx:.2f}" cy="{cy:.2f}" r="{r_tam:.2f}" fill="{_FUNNEL_COLORS["tam"]}" opacity="0.3" />')
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
                f'dominant-baseline="central" font-size="10" fill="#1f2937" font-weight="bold">'
                f"{metric_label}: {_esc(_fmt_usd(metric_val))}</text>"
            )
            # Leader line from label to circle edge
            line_end_x = _num(cx + sign * radius)
            # Line starts near the text (with a small gap)
            line_start_x = _num(label_x + (8 if label_side == "left" else -8))
            parts.append(
                f'<line x1="{line_start_x:.2f}" y1="{y_pos:.2f}" '
                f'x2="{line_end_x:.2f}" y2="{y_pos:.2f}" '
                f'stroke="#9ca3af" stroke-width="1" stroke-dasharray="{_DASH_LEADER_LINE}" />'
            )
    else:
        # Centered labels (single-approach mode)
        label_y_tam = _num(cy - r_tam - 8)
        parts.append(
            f'<text x="{cx:.2f}" y="{label_y_tam:.2f}" text-anchor="middle" '
            f'font-size="11" fill="#1f2937" font-weight="bold">'
            f"TAM: {_esc(_fmt_usd(tam_val))}</text>"
        )

        # SAM label — move outside circle with leader line when too small to fit
        if r_sam < _SAM_LABEL_FONT * 3.5:
            label_y_sam = _num(cy - r_tam - 22)
            line_y_start = _num(label_y_sam + 4)
            line_y_end = _num(cy - r_sam)
            parts.append(
                f'<line x1="{cx:.2f}" y1="{line_y_start:.2f}" '
                f'x2="{cx:.2f}" y2="{line_y_end:.2f}" '
                f'stroke="#9ca3af" stroke-width="1" stroke-dasharray="{_DASH_LEADER_LINE}" />'
            )
        else:
            label_y_sam = _num(cy - r_sam + 14)
        parts.append(
            f'<text x="{cx:.2f}" y="{label_y_sam:.2f}" text-anchor="middle" '
            f'font-size="{_SAM_LABEL_FONT}" fill="#1f2937">'
            f"SAM: {_esc(_fmt_usd(sam_val))}</text>"
        )
        parts.append(
            f'<text x="{cx:.2f}" y="{cy:.2f}" text-anchor="middle" '
            f'dominant-baseline="central" font-size="10" fill="#1f2937" font-weight="bold">'
            f"SOM: {_esc(_fmt_usd(som_val))}</text>"
        )

    # Approach label below
    label_y_bot = _num(cy + r_tam + 18)
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
        parts = [
            f'<svg width="{svg_w}" height="{svg_h}" xmlns="http://www.w3.org/2000/svg">',
            _chart_funnel_single(td_d, "Top-Down", 230.0, 130.0, max_r, label_side="left"),
            _chart_funnel_single(bu_d, "Bottom-Up", 470.0, 130.0, max_r, label_side="right"),
            "</svg>",
        ]
    elif has_td:
        svg_w = 300
        svg_h = 280
        max_r = 100.0
        parts = [
            f'<svg width="{svg_w}" height="{svg_h}" xmlns="http://www.w3.org/2000/svg">',
            _chart_funnel_single(td_d, "Top-Down", 150.0, 130.0, max_r),
            "</svg>",
        ]
    else:
        svg_w = 300
        svg_h = 280
        max_r = 100.0
        parts = [
            f'<svg width="{svg_w}" height="{svg_h}" xmlns="http://www.w3.org/2000/svg">',
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

    parts: list[str] = [f'<svg width="{svg_w}" height="{svg_h}" xmlns="http://www.w3.org/2000/svg">']

    # Base SOM center line
    base_x = x_pos(base_som)
    parts.append(
        f'<line x1="{base_x:.2f}" y1="0" x2="{base_x:.2f}" y2="{_num(svg_h - 20):.2f}" '
        f'stroke="#6b7280" stroke-width="1" stroke-dasharray="4,3" />'
    )
    parts.append(
        f'<text x="{base_x:.2f}" y="{_num(svg_h - 5):.2f}" text-anchor="middle" '
        f'font-size="9" fill="#6b7280">Base: {_esc(_fmt_usd(base_som))}</text>'
    )

    for i, (param, low_som, _b_som, high_som) in enumerate(bar_data):
        y = _num(i * (bar_height + bar_gap) + 15)
        # Label
        display_param = _esc(param.replace("_", " ").title())
        parts.append(
            f'<text x="{_num(label_width - 5):.2f}" y="{_num(y + bar_height / 2):.2f}" '
            f'text-anchor="end" dominant-baseline="central" font-size="11" '
            f'fill="#1f2937">{display_param}</text>'
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
            f'fill="#6b7280">{_esc(_fmt_usd(low_som))}</text>'
        )
        parts.append(
            f'<text x="{high_label_x:.2f}" y="{_num(y - 2):.2f}" '
            f'text-anchor="middle" font-size="{_TORNADO_LABEL_FONT}" '
            f'fill="#6b7280">{_esc(_fmt_usd(high_som))}</text>'
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
                # Scenarios without a recognized approach_used are silently skipped
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


# ---------------------------------------------------------------------------
# Chart 3: Cross-validation Comparison (grouped bars)
# ---------------------------------------------------------------------------


def _chart_cross_validation(sizing: dict[str, Any] | None) -> str:
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
        return '<div class="placeholder">Cross-validation requires both approaches</div>'

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

    parts: list[str] = [f'<svg width="{svg_w}" height="{svg_h}" xmlns="http://www.w3.org/2000/svg">']

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
            f'stroke="#e5e7eb" stroke-width="1" />'
        )
        parts.append(
            f'<text x="{gx:.2f}" y="10.00" '
            f'text-anchor="middle" font-size="7" fill="#9ca3af">'
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
            f'text-anchor="middle" font-size="8" fill="#1f2937">'
            f"{_esc(_fmt_usd(td_v))}</text>"
        )

        # BU bar
        bu_x = _num(gx + bar_gap / 2)
        bu_y = _num(margin_top + chart_height - bu_h)
        parts.append(
            f'<rect x="{bu_x:.2f}" y="{bu_y:.2f}" '
            f'width="{_num(bar_width):.2f}" height="{_num(bu_h):.2f}" '
            f'fill="#48b2e8" rx="3" />'
        )
        # BU value label
        parts.append(
            f'<text x="{_num(bu_x + bar_width / 2):.2f}" y="{_num(bu_y - 5):.2f}" '
            f'text-anchor="middle" font-size="8" fill="#1f2937">'
            f"{_esc(_fmt_usd(bu_v))}</text>"
        )

        # Metric label
        label_y = _num(margin_top + chart_height + 15)
        parts.append(
            f'<text x="{gx:.2f}" y="{label_y:.2f}" '
            f'text-anchor="middle" font-size="12" fill="#1f2937" '
            f'font-weight="bold">{_esc(metric.upper())}</text>'
        )

    parts.append("</svg>")

    legend = (
        '<div class="legend">'
        '<span class="legend-item">'
        f'<span class="legend-swatch" style="background:{_CLR_PRIMARY}"></span>'
        " Top-Down</span>"
        '<span class="legend-item">'
        '<span class="legend-swatch" style="background:#48b2e8"></span>'
        " Bottom-Up</span>"
        "</div>"
    )

    return '<div class="chart-container">' + "\n".join(parts) + "</div>" + legend


# ---------------------------------------------------------------------------
# Chart 4: Assumption Confidence Donut
# ---------------------------------------------------------------------------


def _chart_confidence_donut(validation: dict[str, Any] | None) -> str:
    """Chart 4: Donut chart of assumption confidence categories."""
    if validation is None:
        return '<div class="placeholder">No data available</div>'
    if validation is _CORRUPT:
        return '<div class="placeholder">Data unavailable</div>'
    if _is_stub(validation):
        reason = _esc(validation.get("reason", "Skipped"))
        return f'<div class="placeholder">{reason}</div>'

    assumptions = _as_list(validation.get("assumptions"))
    if not assumptions:
        return '<div class="placeholder">No assumptions recorded</div>'

    # Count by category in canonical order
    counts: dict[str, int] = {}
    for a in assumptions:
        if not isinstance(a, dict):
            continue
        cat = str(a.get("category", "unknown"))
        counts[cat] = counts.get(cat, 0) + 1

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

    return '<div class="chart-container">' + svg + "</div>" + legend


# ---------------------------------------------------------------------------
# Chart 5: Checklist Status Donut
# ---------------------------------------------------------------------------


def _chart_checklist_donut(checklist: dict[str, Any] | None) -> str:
    """Chart 5: Donut chart of checklist pass/fail/NA."""
    if checklist is None:
        return '<div class="placeholder">No data available</div>'
    if checklist is _CORRUPT:
        return '<div class="placeholder">Data unavailable</div>'
    if _is_stub(checklist):
        reason = _esc(checklist.get("reason", "Skipped"))
        return f'<div class="placeholder">{reason}</div>'

    summary = _as_dict(checklist.get("summary"))
    pass_ct = _num(summary.get("pass", 0))
    fail_ct = _num(summary.get("fail", 0))
    na_ct = _num(summary.get("not_applicable", 0))

    if pass_ct + fail_ct + na_ct <= 0:
        return '<div class="placeholder">No checklist data</div>'

    # Canonical order: pass, fail, not_applicable
    segments: list[tuple[str, float, str]] = [
        ("pass", pass_ct, _CHECKLIST_COLORS["pass"]),
        ("fail", fail_ct, _CHECKLIST_COLORS["fail"]),
        ("not_applicable", na_ct, _CHECKLIST_COLORS["not_applicable"]),
    ]
    # Filter out zero segments
    segments = [(s, v, c) for s, v, c in segments if v > 0]

    svg = _svg_donut(segments)

    status_labels = {"pass": "Pass", "fail": "Fail", "not_applicable": "N/A"}
    legend_items: list[str] = []
    for cat, val, color in segments:
        label = _esc(status_labels.get(cat, cat))
        legend_items.append(
            f'<span class="legend-item">'
            f'<span class="legend-swatch" style="background:{_esc(color)}"></span>'
            f" {label}: {int(val)}</span>"
        )
    legend = '<div class="legend">' + "".join(legend_items) + "</div>"

    return '<div class="chart-container">' + svg + "</div>" + legend


def _chart_provenance_summary(
    provenance: dict[str, dict[str, Any]] | None,
    sizing: dict[str, Any] | None = None,
) -> str:
    """Render provenance summary HTML table below funnels."""
    if not provenance:
        return ""

    rows: list[str] = []
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
                "sourced": "#10b981",
                "derived": "#f59e0b",
                "agent_estimate": "#ef4444",
                "unknown": "#9ca3af",
            }
            badge_labels = {
                "sourced": "Sourced",
                "derived": "Derived",
                "agent_estimate": "Agent Estimate",
                "unknown": "Unknown",
            }
            color = badge_colors.get(classification, "#9ca3af")
            label = badge_labels.get(classification, classification)

            deck_str = _esc(_fmt_usd(float(deck_claim))) if deck_claim is not None else "\u2014"
            delta_str = _esc(f"{delta:+.1f}%") if delta is not None else "\u2014"

            # Look up the agent's calculated estimate from sizing data
            estimate_str = "\u2014"  # em dash fallback
            if sizing is not None:
                approach_sizing = _as_dict(sizing.get(approach_key))
                metric_data = _as_dict(approach_sizing.get(metric))
                estimate_val = metric_data.get("value")
                if estimate_val is not None:
                    estimate_str = _esc(_fmt_usd(float(estimate_val)))

            rows.append(
                f"<tr>"
                f"<td>{_esc(metric.upper())} ({_esc(method)})</td>"
                f'<td style="color:{_esc(color)}">{_esc(label)}</td>'
                f"<td>{estimate_str}</td>"
                f"<td>{deck_str}</td>"
                f"<td>{delta_str}</td>"
                f"</tr>"
            )

    if not rows:
        return ""

    return (
        '<div style="margin-top:1rem;font-size:0.85rem;">'
        '<table style="width:100%;border-collapse:collapse;">'
        "<tr>"
        '<th style="text-align:left;padding:0.4rem;border-bottom:1px solid #e5e7eb;color:#6b7280;">Metric</th>'
        '<th style="text-align:left;padding:0.4rem;border-bottom:1px solid #e5e7eb;color:#6b7280;">Classification</th>'
        '<th style="text-align:left;padding:0.4rem;border-bottom:1px solid #e5e7eb;color:#6b7280;">Our Estimate</th>'
        '<th style="text-align:left;padding:0.4rem;border-bottom:1px solid #e5e7eb;color:#6b7280;">Deck Claim</th>'
        '<th style="text-align:left;padding:0.4rem;border-bottom:1px solid #e5e7eb;color:#6b7280;">Delta</th>'
        "</tr>" + "".join(rows) + "</table></div>"
    )


def _chart_key_findings(
    checklist: dict[str, Any] | None,
    validation: dict[str, Any] | None,
    provenance: dict[str, dict[str, Any]] | None,
) -> str:
    """Render Key Findings section with strong/attention/actions subsections."""
    strong: list[str] = []
    attention: list[str] = []
    actions: list[str] = []

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
                notes = str(item.get("notes", ""))
                text = f"{label}: {notes}" if notes else label
                attention.append(text)
                actions.append(f"Address: {label}")

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
                notes = str(fig.get("notes", ""))
                prefix = "Refuted" if status == "refuted" else "Unsupported"
                text = f"{prefix}: {figure_name}" + (f" — {notes}" if notes else "")
                attention.append(text)
                actions.append(f"Find independent source for {figure_name}")
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
                if delta is not None:
                    if abs(delta) <= 20:
                        strong.append(f"{metric.upper()} ({method}) within 20% of deck claim")
                    elif abs(delta) > 50:
                        attention.append(f"{metric.upper()} ({method}): {delta:+.1f}% vs deck claim")

    if not strong and not attention and not actions:
        return ""

    def _render_items(items: list[str], css_class: str, max_items: int = 3) -> str:
        return "".join(f'<div class="finding-item {css_class}">{_esc(item)}</div>' for item in items[:max_items])

    parts: list[str] = []
    if strong:
        parts.append(
            f'<div class="findings-subsection"><h3>What\'s strong</h3>{_render_items(strong, "finding-strong")}</div>'
        )
    if attention:
        parts.append(
            '<div class="findings-subsection">'
            "<h3>What needs attention</h3>"
            f"{_render_items(attention, 'finding-attention')}"
            "</div>"
        )
    if actions:
        parts.append(
            f'<div class="findings-subsection"><h3>Top actions</h3>{_render_items(actions, "finding-action")}</div>'
        )

    return (
        '<section><h2 style="color:#0d549d;font-size:1.25rem;margin-bottom:1rem;'
        'border-bottom:1px solid #e5e7eb;padding-bottom:0.5rem;">Key Findings</h2>'
        '<div style="font-size:0.9rem;">' + "".join(parts) + "</div></section>"
    )


# ---------------------------------------------------------------------------
# Main HTML composition
# ---------------------------------------------------------------------------


def compose_html(dir_path: str) -> str:
    """Load artifacts and compose full HTML report."""
    all_names = REQUIRED_ARTIFACTS + OPTIONAL_ARTIFACTS
    artifacts: dict[str, dict[str, Any] | None] = {}
    for name in all_names:
        artifacts[name] = _load_artifact(dir_path, name)

    inputs = artifacts.get("inputs.json")
    sizing = artifacts.get("sizing.json")
    sensitivity = artifacts.get("sensitivity.json")
    validation = artifacts.get("validation.json")
    checklist = artifacts.get("checklist.json")

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
        provenance_data = _compute_provenance(sizing, validation, inputs)

    # Build sections
    funnel_html = _chart_funnel(sizing)
    provenance_summary_html = _chart_provenance_summary(provenance_data, sizing)
    key_findings_html = _chart_key_findings(checklist, validation, provenance_data)
    tornado_html = _chart_tornado(sensitivity)
    cross_val_html = _chart_cross_validation(sizing)
    confidence_html = _chart_confidence_donut(validation)
    checklist_html = _chart_checklist_donut(checklist)

    date_line = ""
    if analysis_date:
        date_line = f"<p>Analysis date: {_esc(analysis_date)}</p>"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Market Sizing: {_esc(company_name)}</title>
    <style>{_css()}</style>
</head>
<body>
    <header>
        <h1>Market Sizing: {_esc(company_name)}</h1>
        {date_line}
        <p>Generated by <a href="https://github.com/lool-ventures/founder-skills">founder skills</a>
        by <a href="https://lool.vc">lool ventures</a> — Market Sizing Agent</p>
    </header>
    <main>
        <section>
            <h2>TAM / SAM / SOM</h2>
            {funnel_html}
            {provenance_summary_html}
        </section>
        {key_findings_html}
        <section>
            <h2>Sensitivity Analysis</h2>
            <p style="color:#6b7280;font-size:0.85rem;margin-bottom:1rem;">
            Wider bars = higher sensitivity. Parameters are ranked by
            impact on SOM. Focus on sourcing or validating the top
            parameters first.</p>
            {tornado_html}
        </section>
        <section>
            <h2>Cross-Validation Comparison</h2>
            {cross_val_html}
        </section>
        <section>
            <h2>Assumption Confidence</h2>
            {confidence_html}
        </section>
        <section>
            <h2>Checklist Status</h2>
            {checklist_html}
        </section>
    </main>
    <footer>
        Generated by <a href="https://github.com/lool-ventures/founder-skills">founder skills</a>
        by <a href="https://lool.vc">lool ventures</a> — Market Sizing Agent
    </footer>
    {_tooltip_js()}
    {_collapsible_js()}
</body>
</html>
"""


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    p = argparse.ArgumentParser(description="Generate HTML visualization from market sizing artifacts")
    p.add_argument("-d", "--dir", required=True, help="Directory containing JSON artifacts")
    p.add_argument("--pretty", action="store_true", help="Accepted for compatibility (no-op)")
    p.add_argument("-o", "--output", help="Write HTML to file instead of stdout")
    return p.parse_args()


def main() -> None:
    """Entry point."""
    args = parse_args()

    if not os.path.isdir(args.dir):
        print(f"Error: directory not found: {args.dir}", file=sys.stderr)
        sys.exit(1)

    html_output = compose_html(args.dir)
    _write_output(html_output, args.output)


if __name__ == "__main__":
    main()
