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
import re
import sys
from typing import Any, TypeGuard

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _redteam_copy  # noqa: E402
import _upload_names  # noqa: E402
from _redteam_text import humanize_claim as _humanize_claim  # noqa: E402
from _redteam_text import humanize_param as _humanize_param  # noqa: E402

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
    "sensitivity.json",
]
OPTIONAL_ARTIFACTS: list[str] = ["redteam.json"]

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


# Process-wide currency label, set once per run from the artifacts. See the
# matching note in compose_report.py — a bare "$" on a non-USD analysis puts a
# wrong unit on the headline chart labels.
_CURRENCY: str = "USD"


def _resolve_currency(*artifacts: dict[str, Any] | None) -> str:
    """Return the analysis currency code from the first artifact carrying one."""
    for artifact in artifacts:
        if isinstance(artifact, dict):
            currency = artifact.get("currency")
            if isinstance(currency, str) and currency.strip():
                return currency.strip().upper()
    return "USD"


def _set_currency(code: str) -> None:
    """Set the process-wide default currency label for _fmt_usd."""
    global _CURRENCY
    _CURRENCY = code.strip().upper() if isinstance(code, str) and code.strip() else "USD"


# Human-readable labels for the declared sizing_basis convention — see
# references/tam-sam-som-methodology.md §5. Mirrors compose_report.py's copy
# (standalone scripts can't import across skills).
_SIZING_BASIS_LABELS: dict[str, str] = {
    "current_year": "Current-year market size",
    "forecast_year": "Forecast-year market size",
    "mixed": "Mixed (current- and forecast-year figures)",
}


def _sizing_basis_label(value: Any) -> str:
    """Human-readable label for sizing_basis — absence renders "Not declared",
    never a silent default to "current_year" (see compose_report.py's copy for
    the full rationale)."""
    if isinstance(value, str) and value in _SIZING_BASIS_LABELS:
        return _SIZING_BASIS_LABELS[value]
    return "Not declared"


def _resolve_sizing_basis(
    sizing: dict[str, Any] | None,
    inputs: dict[str, Any] | None,
) -> str | None:
    """Resolve the raw sizing_basis token — sizing.json first, inputs.json fallback."""
    if _usable(sizing):
        val = sizing.get("sizing_basis")
        if isinstance(val, str) and val:
            return val
    if _usable(inputs):
        val = inputs.get("sizing_basis")
        if isinstance(val, str) and val:
            return val
    return None


def _fmt_usd(value: float | int, currency_code: str | None = None) -> str:
    """Format a number as a compact currency string, scaled with K/M/B suffixes.

    Defaults to the process-wide currency (``_set_currency``). "USD" renders a
    bare "$" prefix; any other ISO code is tagged as a suffix (e.g. "1.5M ILS").
    """
    code = _CURRENCY if currency_code is None else (currency_code or "USD")
    if value < 0:
        return "-" + _fmt_usd(-value, code)
    prefix = "$" if code == "USD" else ""
    suffix = "" if code == "USD" else f" {code}"
    if value >= 1_000_000_000:
        return f"{prefix}{value / 1_000_000_000:,.1f}B{suffix}"
    if value >= 1_000_000:
        return f"{prefix}{value / 1_000_000:,.1f}M{suffix}"
    if value >= 1_000:
        return f"{prefix}{value / 1_000:,.1f}K{suffix}"
    return f"{prefix}{value:,.2f}{suffix}"


def _try_float(value: Any) -> float | None:
    """Coerce to float, returning None on non-numeric input.

    Mirrors the _compute_delta tolerance: a non-numeric deck claim (e.g. "$5B"
    or "TBD") must be skipped, not crash the whole HTML render.
    """
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# Below this |delta| vs a founder-stated figure, agreement carries no evidentiary weight:
# it can mean both analyses read the same source, or that our input came from their materials.
# compose_report.py uses the same constant; keep them in step.
CLOSE_AGREEMENT_PCT = 25.0

# Mirrors compose_report.DECK_MISMATCH_PCT. Both surfaces must speak at the same threshold.
DECK_MISMATCH_PCT = 50.0


def _compute_delta(calculated: float, deck_claim: Any) -> float | None:
    """Returns signed percentage delta, or None if claim is invalid."""
    try:
        claim = float(deck_claim)
    except (TypeError, ValueError):
        return None
    if claim <= 0:
        return None
    return round((calculated - claim) / claim * 100, 1)


def _comparable_claim(
    claim: Any, sizing: dict[str, Any] | None, inputs: dict[str, Any] | None
) -> tuple[float | None, bool]:
    """Express a deck claim in the analysis currency. Returns (value, blocked).

    Mirrors compose_report._comparable_claim. An earlier version tested only for an UNDECLARED
    claim currency, which left the declared-and-convertible case comparing a RAW claim in the table
    against a CONVERTED one in the warnings -- measured at 83 percentage points apart on one figure.
    A declared currency with no matching recorded pair is blocked too: converting it would need a
    rate nobody supplied, and inverting another pair is exactly what this skill refuses to do.
    """
    if not isinstance(claim, (int, float)) or isinstance(claim, bool):
        return None, False
    fx = sizing.get("fx") if isinstance(sizing, dict) else None
    conversions = fx.get("conversions") if isinstance(fx, dict) else None
    if not (isinstance(conversions, list) and conversions):
        return float(claim), False
    declared = (inputs or {}).get("existing_claims_currency")
    if not (isinstance(declared, str) and declared.strip()):
        return None, True
    target = (sizing or {}).get("currency")
    if declared.strip().upper() == str(target).strip().upper():
        return float(claim), False
    for c in conversions:
        if not isinstance(c, dict):
            continue
        rate = c.get("rate")
        if (
            str(c.get("from", "")).upper() == declared.strip().upper()
            and str(c.get("to", "")).upper() == str(target).upper()
            and isinstance(rate, (int, float))
            and not isinstance(rate, bool)
            and rate > 0
        ):
            return float(claim) * float(rate), False
    return None, True


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
            value_num = _try_float(m.get("value", 0))
            comparable, blocked = _comparable_claim(deck_claim, sizing, inputs)
            # Mirrors compose_report.py: a blocked comparison yields NO delta. See the note there.
            delta = (
                _compute_delta(value_num, comparable)
                if value_num is not None and deck_claim is not None and comparable is not None
                else None
            )

            # A converted money input with no declared claim currency makes the delta carry the
            # exchange rate's magnitude on a perfectly correct analysis. compose_report.py refuses
            # the comparison in that case; the renderers must not assert closeness there either.
            # Mirrors compose_report.py: a horizon mismatch kills the delta exactly as a blocked
            # currency comparison does, so this renderer cannot assert closeness across it either.
            horizon = _horizon_mismatch(inputs, metric)
            if horizon is not None:
                delta = None
                comparable = None

            approach_prov[metric] = {
                "classification": classification,
                "confidence_breakdown": breakdown,
                "deck_claim": deck_claim,
                "delta_vs_deck_pct": delta,
                "deck_claim_comparable": comparable,
                "comparison_blocked": blocked,
                "horizon_mismatch": ({"claim_months": horizon[0], "ours_months": horizon[1]} if horizon else None),
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
    return """
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: var(--font-body);
            line-height: 1.6;
            color: var(--lool-ink);
            background: var(--lool-white);
            padding: 2rem;
            max-width: 960px;
            margin: 0 auto;
            -webkit-font-smoothing: antialiased;
            -moz-osx-font-smoothing: grayscale;
        }
        header {
            border-bottom: 3px solid var(--lool-blue);
            padding-bottom: 1rem;
            margin-bottom: 2rem;
        }
        header h1 {
            color: var(--lool-blue);
            font-size: 1.75rem;
            font-weight: 400;
            letter-spacing: -0.01em;
        }
        header p {
            color: var(--lool-mute);
            font-size: 0.875rem;
        }
        main section {
            background: var(--lool-paper);
            border: 1px solid var(--lool-line-2);
            padding: 1.5rem;
            margin-bottom: 1.5rem;
        }
        main section h2 {
            color: var(--lool-royal);
            font-size: 1.25rem;
            font-weight: 500;
            margin-bottom: 1rem;
            border-bottom: 1px solid var(--lool-line-2);
            padding-bottom: 0.5rem;
        }
        .chart-container {
            display: flex;
            justify-content: center;
            align-items: center;
            flex-wrap: wrap;
            gap: 2rem;
        }
        .placeholder {
            text-align: center;
            color: var(--lool-faint);
            font-style: italic;
            padding: 2rem;
            background: var(--lool-paper-2);
        }
        .legend {
            display: flex;
            justify-content: center;
            gap: 1.5rem;
            flex-wrap: wrap;
            margin-top: 1rem;
            font-size: 0.85rem;
        }
        .legend-item {
            display: flex;
            align-items: center;
            gap: 0.35rem;
        }
        .legend-swatch {
            width: 14px;
            height: 14px;
            display: inline-block;
        }
        footer {
            text-align: center;
            color: var(--lool-faint);
            font-size: 0.75rem;
            padding-top: 1rem;
            border-top: 1px solid var(--lool-line-2);
        }
        footer a, header a { color: var(--lool-azure); text-decoration: none; }
        footer a:hover, header a:hover {
            color: var(--lool-azure-deep);
            text-decoration: underline;
        }
        .collapsible-toggle {
            cursor: pointer;
            user-select: none;
            display: flex;
            align-items: center;
            gap: 0.5rem;
            padding: 0.5rem 0;
        }
        .collapsible-toggle:hover { background: var(--lool-paper-2); }
        .chevron {
            display: inline-block;
            transition: transform 0.2s;
            font-size: 0.75rem;
            color: var(--lool-faint);
        }
        .collapsible-content { padding-left: 1.5rem; }
        .finding-item {
            padding: 0.75rem;
            border-left: 3px solid var(--lool-line-2);
            margin-bottom: 0.5rem;
        }
        .finding-strong { border-left-color: var(--lool-success); }
        .finding-attention { border-left-color: var(--lool-danger); }
        .finding-action { border-left-color: var(--lool-azure); }
        .findings-subsection { margin-bottom: 1rem; }
        .findings-subsection h3 {
            font-size: 0.9rem;
            font-weight: 500;
            color: var(--lool-slate);
            margin-bottom: 0.5rem;
        }
        .confidence-badge {
            display: inline-block;
            padding: 0.1rem 0.4rem;
            border-radius: var(--r-input);
            font-size: 0.65rem;
            font-weight: 600;
            color: var(--lool-white);
            margin-left: 0.25rem;
            vertical-align: middle;
        }
        @media print {
            body { background: #fff; padding: 0; }
            main section { break-inside: avoid; border: 1px solid #ccc; }
            header { border-bottom-color: #000; }
            header h1 { color: #000; }
            .collapsible-content { display: block !important; }
            .collapsible-toggle .chevron { display: none; }
            [data-tooltip] { cursor: default; }
        }
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
        return (
            f'<text x="{cx:.2f}" y="{cy:.2f}" text-anchor="middle" '
            f'fill="{_SVG_TEXT_FAINT}" font-size="12">No TAM data</text>'
        )

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
        label_y_tam = _num(cy - r_tam - 8)
        parts.append(
            f'<text x="{cx:.2f}" y="{label_y_tam:.2f}" text-anchor="middle" '
            f'font-size="11" fill="{_SVG_TEXT_DARK}" font-weight="bold">'
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


# --- COPIES of compose_report.py, kept byte-identical -----------------------
def _horizon_mismatch(inputs: dict[str, Any] | None, metric: str) -> tuple[int, int] | None:
    """(claim_months, ours_months) when both are stated for SOM and differ; else None.

    SOM ONLY, and the scoping is load-bearing. `capture_horizon_months` describes the period
    `share_pct` / `target_pct` represent, which is a SOM concept. Read for TAM or SAM it would let
    an analyst who records a stated SAM horizon blank the SAM comparison -- which on the run that
    motivated this check is the one deck finding that is real.
    """
    if metric != "som" or not isinstance(inputs, dict):
        return None
    claim = _as_dict(inputs.get("existing_claims_horizon_months")).get(metric)
    ours = inputs.get("capture_horizon_months")
    if not isinstance(claim, int) or isinstance(claim, bool):
        return None
    if not isinstance(ours, int) or isinstance(ours, bool):
        return None
    return (claim, ours) if claim != ours else None


# The shared-input detector and its helpers exist here and in compose_report.py.
# test_visualize_market_sizing.py parses both files and compares the bodies, so a drift reds rather
# than shipping two surfaces that disagree about what the founder is told. The label helpers
# (PARAM_LABELS, _humanize_param, _humanize_claim) come from _redteam_text, one source for both.


def _as_number(value: Any) -> float | None:
    """The value as a float when it is a real number, else None.

    `bool` is excluded deliberately: it is an int subclass, so a stray `True` would compare equal
    to 1 and could manufacture an identity out of nothing.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


_PAIRED_SLOTS: tuple[tuple[str, str, str, str], ...] = (
    # metric, top-down input key, bottom-up input key, sizing block carrying them
    ("sam", "segment_pct", "serviceable_pct", "sam"),
    ("som", "share_pct", "target_pct", "som"),
)


def _factor_chain(assumption: dict[str, Any]) -> list[dict[str, Any]] | None:
    """The assumption's `factors` list if it is well-formed and has TWO OR MORE entries, else None.

    Well-formed: a list of objects each carrying a str `factor_id`, a finite numeric `value` (bool
    excluded, as everywhere else here), a str `source_id`, and an optional `role`. Anything else
    is "no chain" -- a malformed chain must read as UNSTRUCTURED, never crash compose, and never
    be graded as reconciling, because a chain we cannot parse is exactly as uncheckable as one
    that is absent.

    Two or more. A one-element list is the value under another name: on a live run that is exactly
    what arrived (`segment_pct` <- one factor of 0.3732), it reconciled trivially, and the report
    called the figure itemized.

    `role` defaults to `"multiplicand"`; the only other accepted value is `"divisor"`, which lets
    a derived figure be itemized as a RATIO (numerator multiplicands over denominator divisors --
    e.g. 15,000,000 / 64,200,000) rather than only as a chain of narrowing multiplicands. An
    additive decomposition was mis-encoded here once and caught only by the product check; an
    unrecognized `role` string is malformed the same way a missing `factor_id` is.
    """
    raw = assumption.get("factors")
    if not isinstance(raw, list) or len(raw) < 2:
        return None
    out: list[dict[str, Any]] = []
    for f in raw:
        if not isinstance(f, dict):
            return None
        fid, src = f.get("factor_id"), f.get("source_id")
        if not isinstance(fid, str) or not isinstance(src, str):
            return None
        val = _as_number(f.get("value"))
        if val is None or not math.isfinite(val):
            return None
        role = f.get("role", "multiplicand")
        if role not in ("multiplicand", "divisor"):
            return None
        out.append({"factor_id": fid, "value": val, "source_id": src, "role": role})
    return out


def _shared_input_values(
    sizing: dict[str, Any] | None, validation: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    """Inputs the two builds share BY VALUE. Empty unless both approaches are present.

    Each item carries a founder-facing `detail` sentence and NO raw field name: these items reach
    `coaching_payload`, and a raw id in that payload is a defect the fleet has already fixed once.

    Tolerance is 1e-6 relative. This is an IDENTITY check, not a closeness one: an honest
    near-agreement of even 0.5% must not trip it -- that case is what the comparison caveat is for.
    """
    if not isinstance(sizing, dict):
        return []
    td = _as_dict(sizing.get("top_down"))
    bu = _as_dict(sizing.get("bottom_up"))
    if not td or not bu:
        return []
    found: list[dict[str, Any]] = []

    it = _as_number(_as_dict(_as_dict(td.get("tam")).get("inputs")).get("industry_total"))
    bu_tam_in = _as_dict(_as_dict(bu.get("tam")).get("inputs"))
    cc = _as_number(bu_tam_in.get("customer_count"))
    arpu = _as_number(bu_tam_in.get("arpu"))
    if it and cc is not None and arpu is not None and math.isclose(it, cc * arpu, rel_tol=1e-6):
        found.append(
            {
                "metric": "tam",
                "kind": "identity",
                "code": "SHARED_TAM_IDENTITY",
                "detail": (
                    f"Your {_humanize_param('industry_total')} equals "
                    f"{_humanize_param('customer_count')} \u00d7 {_humanize_param('arpu')} exactly, "
                    "so the two TAM figures are one computation, shown two ways."
                ),
            }
        )

    for metric, td_key, bu_key, block in _PAIRED_SLOTS:
        a = _as_number(_as_dict(_as_dict(td.get(block)).get("inputs")).get(td_key))
        b = _as_number(_as_dict(_as_dict(bu.get(block)).get("inputs")).get(bu_key))
        if a and b is not None and math.isclose(a, b, rel_tol=1e-6):
            found.append(
                {
                    "metric": metric,
                    "kind": "equal_value",
                    "code": "PAIRED_SLOT_SAME_VALUE",
                    "detail": (
                        f"{_humanize_param(td_key)} and {_humanize_param(bu_key)} carry the same "
                        f"value ({a:g}), so the two {metric.upper()} figures narrow by one "
                        "number, not two."
                    ),
                }
            )

    # Factor-level overlap. Value identity on the slot (above) could not see the motivating run:
    # 10.0 and 9.1 are different numbers whose chains share three of four factors. A factor counts
    # as shared when its `factor_id` matches, OR its (source_id, value) pair matches -- the same
    # figure under two names is still the same figure, while two coincidentally-equal fractions
    # from different sources are not. Reported as a list, never a threshold: one shared factor is
    # one shared factor, and the reader decides what it means.
    if isinstance(validation, dict):
        by_name = {a2.get("name"): a2 for a2 in _as_list(validation.get("assumptions")) if isinstance(a2, dict)}
        for metric, td_key, bu_key, _block in _PAIRED_SLOTS:
            td_chain = _factor_chain(by_name.get(td_key) or {})
            bu_chain = _factor_chain(by_name.get(bu_key) or {})
            if not td_chain or not bu_chain:
                continue
            bu_ids = {f["factor_id"] for f in bu_chain}
            bu_pairs = {(f["source_id"], round(f["value"], 6)) for f in bu_chain}
            shared_ids = [
                f["factor_id"]
                for f in td_chain
                if f["factor_id"] in bu_ids or (f["source_id"], round(f["value"], 6)) in bu_pairs
            ]
            if not shared_ids:
                continue
            mass = 1.0
            for f in td_chain:
                if f["factor_id"] in shared_ids:
                    mass *= f["value"]
            found.append(
                {
                    "metric": metric,
                    "kind": "shared_factor",
                    "code": "SHARED_FACTOR_OVERLAP",
                    "shared": shared_ids,
                    "shared_mass": round(mass, 6),
                    "detail": (
                        f"The two {metric.upper()} builds share {len(shared_ids)} of the "
                        f"{len(td_chain)} figures they narrow by "
                        f"({', '.join(sid.replace('_', ' ') for sid in shared_ids)}), so they "
                        "differ only where the remaining figures do."
                    ),
                }
            )
    return found


# ---------------------------------------------------------------------------
# Chart 3: Top-down vs bottom-up comparison (grouped bars).
# NOT "cross-validation" -- that word asserts the comparison validates something. The pipeline
# cannot tell whether the two builds rest on the same underlying figures, so closeness is not
# confirmation. compose_report.py carries the same wording; the two surfaces ship together.
# ---------------------------------------------------------------------------


def _chart_cross_validation(sizing: dict[str, Any] | None, validation: dict[str, Any] | None = None) -> str:
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
            text = str(comparison.get(warn_key) or comparison.get(note_key) or "").strip()
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
        if text.strip():
            note_html = (
                '<p class="chart-note" style="color:var(--lool-mute);font-size:0.8rem;'
                'margin-top:0.5rem;">' + _esc(text) + "</p>"
            )

    return '<div class="chart-container">' + "\n".join(parts) + "</div>" + legend + note_html


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


def _contested_rows(
    sizing: dict[str, Any] | None, inputs: dict[str, Any] | None, redteam: dict[str, Any] | None
) -> set[tuple[str, str]]:
    """(approach, metric) pairs built on a founder-stated input that a HIGH red-team finding names.

    A mark, not a re-basing: the red team may not propose a replacement figure, and the live
    finding that motivated this quoted a monthly rate against an annual ARPU -- a number field
    would have laundered that unit mismatch into a warning. What the founder needs is to see which
    rows rest on the contested figure. A metric consumes a parameter if that parameter appears in
    its own `inputs` or in any block above it in the same approach (SAM is built on TAM).
    """
    if not isinstance(sizing, dict) or not _usable(redteam):
        return set()
    stated = _as_dict(_as_dict(inputs).get("founder_stated_inputs"))
    contested = {
        str(f.get("parameter"))
        for f in _as_list(_as_dict(redteam).get("findings"))
        if isinstance(f, dict) and f.get("severity") == "high" and isinstance(f.get("parameter"), str)
    }
    contested &= set(stated.keys())
    if not contested:
        return set()
    rows: set[tuple[str, str]] = set()
    for approach in ("top_down", "bottom_up"):
        consumed: set[str] = set()
        for metric in ("tam", "sam", "som"):
            block = _as_dict(_as_dict(sizing.get(approach)).get(metric))
            consumed |= set(_as_dict(block.get("inputs")).keys())
            if consumed & contested:
                rows.add((approach, metric))
    return rows


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
            color = badge_colors.get(classification, _CLR_NA)
            label = badge_labels.get(classification, classification)

            # The CONVERTED claim, matching report.md. Rendering the raw one made the two
            # deliverables print different numbers for the same field, and `_fmt_usd` suffixes the
            # ANALYSIS currency -- so a raw EUR figure came out tagged ILS.
            # `is not None`, not `or`: a legitimate comparable of 0.0 is falsy.
            _comparable = prov.get("deck_claim_comparable")
            _shown_claim = deck_claim if _comparable is None else _comparable
            deck_claim_num = _try_float(_shown_claim) if _shown_claim is not None else None
            deck_str = _esc(_fmt_usd(deck_claim_num)) if deck_claim_num is not None else "\u2014"
            # An em-dash reads as missing data; a horizon mismatch is two figures for different
            # periods. Mirrors report.md.
            _hm_prov = _as_dict(prov.get("horizon_mismatch"))
            if _hm_prov:
                delta_str = _esc(
                    f"different horizon ({_hm_prov.get('claim_months')} vs {_hm_prov.get('ours_months')} mo)"
                )
            elif delta is not None:
                delta_str = _esc(f"{delta:+.1f}%")
            else:
                delta_str = "\u2014"
            if delta is not None and abs(delta) <= CLOSE_AGREEMENT_PCT and not prov.get("comparison_blocked"):
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
                f'<td style="color:{_esc(color)}">{_esc(label)}</td>'
                f"<td>{estimate_str}</td>"
                f"<td>{deck_str}</td>"
                f"<td>{delta_str}</td>"
                f"</tr>"
            )

    if not rows:
        return ""

    th_style = "text-align:left;padding:0.4rem;border-bottom:1px solid var(--lool-line-2);color:var(--lool-subtle);"
    headers = "".join(
        f'<th style="{th_style}">{label}</th>'
        for label in ("Metric", "Classification", "Our Estimate", "Deck Claim", "Delta")
    )
    footnote = ""
    if identity_metrics:
        footnote += (
            '<p style="color:var(--lool-mute);font-size:0.8rem;margin-top:0.5rem;">&dagger; '
            + _esc(" ".join(str(x["detail"]) for x in shared if x["kind"] == "identity"))
            + " Agreement on these rows is arithmetic, not corroboration.</p>"
        )
    if shared_metrics:
        footnote += (
            '<p style="color:var(--lool-mute);font-size:0.8rem;margin-top:0.5rem;">&Dagger; Both builds '
            "narrow this figure by the same number(s), so their agreement on it is not a cross-check: "
            + _esc(" ".join(str(x["detail"]) for x in shared if x["kind"] in ("equal_value", "shared_factor")))
            + "</p>"
        )
    if contested_rows:
        footnote += (
            '<p style="color:var(--lool-mute);font-size:0.8rem;margin-top:0.5rem;">&sect; Built on a '
            "figure you stated that a cited source contradicts; see Adversarial Findings.</p>"
        )
    if close_agreement:
        footnote += (
            '<p style="color:var(--lool-mute);font-size:0.8rem;margin-top:0.5rem;">'
            f"* Within {CLOSE_AGREEMENT_PCT:.0f}% of the figure in your materials. "
            "Agreement on a number is not independent confirmation &mdash; it can mean both "
            "analyses drew on the same source, or that our input came from your materials. "
            "To get a real check, size it again from an independently chosen value.</p>"
        )
    return (
        '<div style="margin-top:1rem;font-size:0.85rem;">'
        '<table style="width:100%;border-collapse:collapse;">'
        "<tr>" + headers + "</tr>" + "".join(rows) + "</table>" + footnote + "</div>"
    )


# Mirrors red_team.py's INTERNAL_PROVENANCE: a finding grounded in this run's own output.
_INTERNAL_PROVENANCE = "internal:analysis"

_SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}


# Copies of compose_report.py's verdict helpers (skill scripts cannot import each other); kept in
# step by test_visualize_market_sizing.py's helper-sync test.
_SOURCE_CLASS_LABEL = {
    "published": "from published sources",
    "internal": "from this analysis's own output",
    "document": "from your own documents",
}

_RED_TEAM_SKIP_REASONS: dict[str, str] = {
    "founder_declined": (
        "No adversarial review ran, because you asked us not to run one. Nothing in this report "
        "has been checked against an outside source that was trying to contradict it."
    ),
    "dispatch_failed": (
        "An adversarial review was attempted and did not complete, so nothing in this report has "
        "been checked against an outside source. This is a gap in the process, not a finding "
        "about your figures — it is worth re-running."
    ),
    "no_network_available": (
        "No adversarial review ran, because this run had no access to outside sources. Nothing "
        "here has been checked against published figures that might contradict it."
    ),
    "no_subagent_dispatch": (
        "No adversarial review ran, because this environment runs the whole analysis as a single "
        "agent and cannot dispatch a separate reviewer. Nothing here has been checked against an "
        "outside source that was trying to contradict it — running the same analysis in Claude "
        "Cowork or Claude Code can do that."
    ),
}


def _source_class(url: str) -> str:
    """Where a red-team finding's sentence came from: `published` (a web address), `internal`
    (`internal:analysis`) or `document` (the founder's own page). The validator accepts exactly
    these three forms, so the counts always sum to the findings."""
    u = url.strip()
    if u == _INTERNAL_PROVENANCE:
        return "internal"
    if u.startswith("document:"):
        return "document"
    return "published"


def _adversarial_outcome(redteam: dict[str, Any] | None, skip_reason: str | None) -> str:
    """The ONE sentence for what the outside review found, said the same way everywhere it appears.

    By state, then by source class. It used to say "found N published sources" for every accepted
    finding; on a live run both findings were the analysis's own output, the sentence was false at
    the top of the report, and the model's chat paragraph partly consisted of correcting it.
    """
    if not _usable(redteam):
        if isinstance(skip_reason, str) and skip_reason in _RED_TEAM_SKIP_REASONS:
            return _RED_TEAM_SKIP_REASONS[skip_reason]
        return "No outside review ran; the report says why."
    findings = [f for f in _as_list(redteam.get("findings")) if isinstance(f, dict)]
    rejected = int(_as_dict(redteam.get("summary")).get("rejected") or 0)
    if not findings:
        if rejected:
            noun = "challenge" if rejected == 1 else "challenges"
            text = f"An outside review raised {rejected} {noun} but could evidence none of them."
        else:
            text = "An outside review ran against this analysis and found nothing it could evidence."
    else:
        counts: dict[str, int] = {}
        for f in findings:
            cls = _source_class(str(f.get("source_url") or ""))
            counts[cls] = counts.get(cls, 0) + 1
        n = len(findings)
        noun = "challenge" if n == 1 else "challenges"
        parts = [
            f"{counts[c]} {_SOURCE_CLASS_LABEL[c]}" for c in ("published", "internal", "document") if counts.get(c)
        ]
        text = f"An outside review raised {n} {noun}: {', '.join(parts)}."
    unread = [str(x) for x in _as_list(redteam.get("sources_unread")) if str(x).strip()]
    if unread:
        text += f" It did not open {', '.join(unread)}."
    return text


def _top_challenge(redteam: dict[str, Any] | None) -> str:
    """The most serious accepted finding, as one sentence with its provenance class."""
    if not _usable(redteam):
        return ""
    findings = [f for f in _as_list(redteam.get("findings")) if isinstance(f, dict)]
    for sev in ("high", "medium"):
        for f in findings:
            if f.get("severity") != sev:
                continue
            truth = str(f.get("what_is_true") or "").strip()
            first = truth.split(". ")[0].rstrip(".") if truth else ""
            url = str(f.get("source_url") or "")
            cls = _source_class(url)
            where = _document_cite(url) if cls == "document" else _SOURCE_CLASS_LABEL[cls]
            where = f"from {where}" if cls == "document" else where
            claim = _humanize_claim(str(f.get("claim_attacked") or "").strip())
            return f"The most serious: {claim} — {first} ({where})."
    return ""


def _summary_verdict(
    sizing: dict[str, Any],
    provenance: dict[str, dict[str, Any]] | None,
    checklist: dict[str, Any] | None,
    redteam: dict[str, Any] | None,
    skip_reason: str | None,
    marks: dict[tuple[str, str], str],
    inputs: dict[str, Any] | None,
) -> tuple[str, set[str]]:
    """The paragraph a reader wants first, from fields only. Returns (text, metrics it stated).

    Measured on 2 of 2 hostloop runs: the model wrote this paragraph in chat -- what the deck
    claims against what each build found, how far the builds disagree, the sharpest challenge --
    with ratios it rounded itself. Nothing on the page carried it, so it had to. Every figure
    here is the table's figure with the table's mark; every delta is the producer's.
    """
    sentences: list[str] = []
    stated: set[str] = set()
    approaches = [a for a in ("top_down", "bottom_up") if _as_dict(sizing.get(a))]
    label = {"top_down": "top-down", "bottom_up": "bottom-up"}
    claim_ccy = _as_dict(inputs).get("existing_claims_currency") if isinstance(inputs, dict) else None
    for metric in ("tam", "sam", "som"):
        claim_text = None
        for a in approaches:
            prov = _as_dict(_as_dict(_as_dict(provenance).get(a)).get(metric))
            raw = prov.get("deck_claim")
            comparable = prov.get("deck_claim_comparable")
            if raw is None:
                continue
            if _as_dict(prov.get("horizon_mismatch")):
                claim_text = (
                    f"Your materials state {metric.upper()} {_fmt_usd(float(raw))} for a different period than "
                    f"this analysis covers, so the two are not compared."
                )
                stated.add(metric)
                break
            comp = _as_number(comparable)
            raw_n = _as_number(raw)
            if comp is None or comp <= 0 or raw_n is None:
                break  # blocked (currency not stated) or not a comparable figure: the table says so
            shown = _fmt_usd(comp)
            if comp != raw_n and isinstance(claim_ccy, str) and claim_ccy:
                shown += f" (converted from {raw_n:,.0f} {claim_ccy})"
            values = [(x, _as_number(_as_dict(_as_dict(sizing.get(x)).get(metric)).get("value"))) for x in approaches]
            found = " and ".join(
                f"{_fmt_usd(v)}{marks.get((x, metric), '')} ({label[x]})" for x, v in values if v is not None
            )
            if not found:
                break
            claim_text = f"Your materials state {metric.upper()} {shown}; this analysis finds {found}."
            stated.add(metric)
            break
        if claim_text:
            sentences.append(claim_text)
    comparison = _as_dict(sizing.get("comparison"))
    if len(approaches) == 2 and comparison:
        gaps = []
        for metric in ("tam", "sam", "som"):
            delta = _as_number(comparison.get(f"{metric}_delta_pct"))
            if delta is not None and delta > 30:
                gaps.append(f"{delta:g}% on {metric.upper()}")
        if gaps:
            sentences.append(f"The two builds differ by {' and '.join(gaps)} — one approach likely has a flawed input.")
    sentences.append(_adversarial_outcome(redteam, skip_reason))
    top = _top_challenge(redteam)
    if top:
        sentences.append(top)
    if _usable(checklist):
        sentences.append(_self_check_line(checklist))
    return " ".join(sentences), stated


def _self_check_line(checklist: dict[str, Any]) -> str:
    """The one line a founder reads for the score, rendered ONCE and copied everywhere else.

    "<score>% (<pass>/<applicable> pass, ...)" -- NOT a bare "pass/total" fraction (e.g. "100/22"),
    which reads as a malformed ratio rather than 100% across 22 items. The closing message copies
    this string rather than re-deriving it, so the chat and the report cannot disagree.
    """
    summary = _as_dict(checklist.get("summary"))
    pass_ct = summary.get("pass", 0)
    fail_ct = summary.get("fail", 0)
    na_ct = summary.get("not_applicable", 0)
    total_ct = summary.get("total", pass_ct + fail_ct + na_ct)
    applicable_ct = total_ct - na_ct
    score_pct = summary.get("score_pct")
    if isinstance(score_pct, (int, float)):
        score_str = f"{int(score_pct)}" if float(score_pct) == int(score_pct) else f"{score_pct:.1f}"
        return f"Self-check: {score_str}% ({pass_ct}/{applicable_ct} pass, {fail_ct} fail, {na_ct} N/A)"
    return f"Self-check: {pass_ct} pass, {fail_ct} fail, {na_ct} N/A"


def _document_cite(url: str) -> str:
    """`document:<file>#page=<n>` -> "<file>, page <n>"; `document:<file>` -> "<file>"."""
    m = re.match(r"^document:([^#]+)(?:#page=(\d+))?$", url)
    if not m:
        return url[len("document:") :]
    return f"{m.group(1)}, page {m.group(2)}" if m.group(2) else m.group(1)


def _chart_adversarial(
    redteam: dict[str, Any] | None, names: dict[str, str] | None = None, revision_note: str | None = None
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

    outcome = _esc(_named(_adversarial_outcome(redteam, None)))
    parts: list[str] = []
    if revision_note:
        parts.append(f"<p><em>{_esc(revision_note)}</em></p>")
    if not findings:
        parts.append(f"<p>{outcome} That is a result, not an absence of one.</p>")
    else:
        parts.append(f"<p>{outcome} Each quotes the sentence it relies on.</p>")
        for f in sorted(findings, key=lambda x: _SEVERITY_ORDER.get(str(x.get("severity")), 3)):
            claim = _esc(_named(_humanize_claim(str(f.get("claim_attacked") or "").strip())))
            truth = _esc(_named(str(f.get("what_is_true") or "").strip()))
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
            parts.append(
                f'<div style="margin-bottom:1rem;"><strong>{claim}</strong>'
                f"<p>{truth}</p>"
                + (
                    f'<blockquote style="border-left:3px solid var(--lool-mute);margin:0;'
                    f'padding-left:0.75rem;color:var(--lool-mute);">{quote}</blockquote>'
                    if quote
                    else ""
                )
                + (f'<p style="font-size:0.85rem;">&mdash; {cite}</p>' if cite else "")
                + "</div>"
            )

    if unchecked:
        items = "".join(f"<li>{_esc(_named(str(u).strip()))}</li>" for u in unchecked)
        parts.append(f"<p><strong>Not checked</strong></p><ul>{items}</ul>")

    if dropped:
        noun = "challenge" if dropped == 1 else "challenges"
        them = "it" if dropped == 1 else "them"
        parts.append(
            f'<p style="color:var(--lool-mute);font-size:0.85rem;">{dropped} further {noun} '
            f"could not be shown here because no source was given for {them}.</p>"
        )

    return "".join(parts)


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
                raw_notes = item.get("notes")
                notes = str(raw_notes) if raw_notes is not None else ""
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
                raw_notes = fig.get("notes")
                notes = str(raw_notes) if raw_notes is not None else ""
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
                if delta is not None:
                    if abs(delta) <= CLOSE_AGREEMENT_PCT:
                        # NOT a strength. Landing on the founder's own number is the cheapest
                        # possible outcome — it happens when both analyses read the same source,
                        # or when our input came from their materials. Measured across a 3-deck
                        # corpus, every close agreement was the top-down TAM, and on one deck this
                        # line was the ONLY "what's strong" item in the report.
                        attention.append(
                            f"{metric.upper()} ({method}) is within {abs(delta):.1f}% of your own "
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
        '<section><h2 style="color:var(--lool-royal);font-size:1.25rem;margin-bottom:1rem;'
        'border-bottom:1px solid var(--lool-line-2);padding-bottom:0.5rem;">Key Findings</h2>'
        '<div style="font-size:0.9rem;">' + "".join(parts) + "</div></section>"
    )


# ---------------------------------------------------------------------------
# Main HTML composition
# ---------------------------------------------------------------------------


def compose_html(dir_path: str) -> str:
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

    # The same review report.md shows: its append-only copy, never `redteam.json` as it now stands.
    _rt_shown, _rt_codes, _rt_facts = _redteam_copy.resolve(
        dir_path,
        _redteam_copy.primary_run_id(artifacts.get(n) for n in REQUIRED_ARTIFACTS),
        artifacts.get("redteam.json"),
        artifacts.get("methodology.json"),
    )
    if _rt_facts["rounds"]:
        artifacts["redteam.json"] = _rt_shown

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
        provenance_data = _compute_provenance(sizing, validation, inputs)

    # Build sections
    funnel_html = _chart_funnel(sizing)
    provenance_summary_html = _chart_provenance_summary(
        provenance_data, sizing, validation, inputs, _as_dict(artifacts.get("redteam.json")) or None
    )
    key_findings_html = _chart_key_findings(checklist, validation, provenance_data)
    tornado_html = _chart_tornado(sensitivity)
    cross_val_html = _chart_cross_validation(sizing, _as_dict(validation) or None)
    confidence_html = _chart_confidence_donut(validation)
    checklist_html = _chart_checklist_donut(checklist)
    _upload_display = _upload_names.for_redteam(artifacts.get("redteam.json"))
    adversarial_html = _chart_adversarial(
        artifacts.get("redteam.json"), _upload_display, _redteam_copy.revision_note(_rt_facts)
    )
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
        verdict_html = f'<p class="verdict">{_esc(_upload_names.humanize(_verdict_text, _upload_display))}</p>'
    else:
        _outcome = _esc(_upload_names.humanize(_adversarial_outcome(_rt_for_verdict, _skip), _upload_display))
        verdict_html = f'<p class="verdict">No sizing was produced; see Warnings. {_outcome}</p>'

    date_line = ""
    if analysis_date:
        date_line = f"<p>Analysis date: {_esc(analysis_date)}</p>"

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

    brand_css = _theme.brand_css()

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Market Sizing: {_esc(company_name)}</title>
    <style>{brand_css}{_css()}</style>
</head>
<body>
    <header>
        <h1>Market Sizing: {_esc(company_name)}</h1>
        {date_line}
        {sizing_basis_line}
        {fx_line}
        <p>Generated by <a href="https://github.com/lool-ventures/founder-skills">founder skills</a>
        by <a href="https://lool.vc">lool ventures</a> — Market Sizing Agent</p>
        {verdict_html}
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
            <p style="color:var(--lool-mute);font-size:0.85rem;margin-bottom:1rem;">
            Wider bars = a wider stress range, which follows from how confident
            we are in each input &mdash; not from how much the answer depends on it.
            Focus on sourcing or validating the widest-stressed parameters first.</p>
            {tornado_html}
        </section>
        <section>
            <h2>Top-down vs Bottom-up</h2>
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
        <section>
            <h2>Adversarial Findings</h2>
            {adversarial_html}
        </section>
    </main>
    <footer>
        Generated by <a href="https://github.com/lool-ventures/founder-skills">founder skills</a>
        by <a href="https://lool.vc">lool ventures</a> — Market Sizing Agent
    </footer>
    {_theme.FOOTER_CREDIT_HTML}
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
