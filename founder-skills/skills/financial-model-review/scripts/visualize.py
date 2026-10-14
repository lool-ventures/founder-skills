#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
Generate self-contained HTML visualization from financial model review JSON artifacts.

Outputs raw HTML (not JSON). See compose_report.py for JSON report output.

Usage:
    python visualize.py --dir ./fmr-testco/
    python visualize.py --dir ./fmr-testco/ -o report.html
"""

from __future__ import annotations

import argparse
import html
import json
import math
import os
import sys
from types import ModuleType

# Sibling helper: see compose_report.py. Shared so this page cannot drift from report.md.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from typing import Any, TypeGuard

import _checklist_view  # noqa: E402
import _evidence_multiple  # noqa: E402
import _ui  # noqa: E402

# ---------------------------------------------------------------------------
# Artifact loading infrastructure (duplicated from compose_report.py per PEP 723)
# ---------------------------------------------------------------------------

_CORRUPT: dict[str, Any] = {"__corrupt__": True}

REQUIRED_ARTIFACTS = [
    "inputs.json",
    "checklist.json",
    "unit_economics.json",
    "runway.json",
]
OPTIONAL_ARTIFACTS: list[str] = []


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


def _fmt_usd(value: float | int, currency_code: str = "USD") -> str:
    """Format a number as a compact currency string, scaled with K/M/B suffixes.

    `currency_code` defaults to "USD" (the back-compat behavior for absent/
    "USD" models), using a bare "$" prefix. Any other ISO code is tagged as a
    suffix instead (e.g. "1.5M INR") — a bare "$" would misrepresent a
    non-USD-denominated model.
    """
    if value < 0:
        return "-" + _fmt_usd(-value, currency_code)
    prefix = "$" if currency_code == "USD" else ""
    suffix = "" if currency_code == "USD" else f" {currency_code}"
    if value >= 1_000_000_000:
        return f"{prefix}{value / 1_000_000_000:,.1f}B{suffix}"
    if value >= 1_000_000:
        return f"{prefix}{value / 1_000_000:,.1f}M{suffix}"
    if value >= 1_000:
        return f"{prefix}{value / 1_000:,.1f}K{suffix}"
    return f"{prefix}{value:,.2f}{suffix}"


def _resolve_currency(*artifacts: dict[str, Any] | None) -> str:
    """Return the model's native currency code from the first artifact carrying one.

    Checked in the order passed by the caller; falls back to "USD" (the
    back-compat default) when none carry a currency field.
    """
    for artifact in artifacts:
        if isinstance(artifact, dict):
            currency = artifact.get("currency")
            if isinstance(currency, str) and currency.strip():
                return currency.strip().upper()
    return "USD"


def _fmt_pct(value: float | int) -> str:
    """Format a fraction (0.75, or 1.05 for retention above 100%) as a percentage string."""
    return f"{value * 100:.0f}%"


_RISK_LEVEL_PREFIXES: tuple[tuple[str, str], ...] = (
    ("low risk", "low"),
    ("moderate risk", "moderate"),
    ("elevated risk", "elevated"),
    ("critical risk", "critical"),
)


def _risk_level(risk_assessment: str | None) -> str:
    """Classify runway.py's `risk_assessment` prose into a coarse severity bucket.

    `_assess_risk` in runway.py always opens with one of "Low risk:", "Moderate
    risk:", "Elevated risk:", "Critical risk:", or a no-data fallback. Parsing
    that prefix is how this rendering layer stays in sync with the producer's
    own verdict instead of re-deriving one from `default_alive` alone — which
    is exactly the mismatch behind finding 19: a flat-burn projection that
    never depletes cash was being shown as unconditionally "strong" even when
    runway.py itself rated the same scenario "Moderate risk".
    """
    if not risk_assessment:
        return "unknown"
    lowered = risk_assessment.lower()
    for phrase, level in _RISK_LEVEL_PREFIXES:
        if lowered.startswith(phrase):
            return level
    return "unknown"


# ---------------------------------------------------------------------------
# Color scheme
# ---------------------------------------------------------------------------

_CLR_PRIMARY = "#0D549D"
_CLR_ACCENT = "#21A2E3"
_CLR_PASS = "#2F8A56"
_CLR_WARN = "#C9892B"
_CLR_FAIL = "#C0392B"
_CLR_NA = "#A6AEB5"

_RATING_COLORS: dict[str, str] = {
    "strong": _CLR_PASS,
    "acceptable": "#21A2E3",
    "warning": _CLR_WARN,
    "fail": _CLR_FAIL,
}

_SCENARIO_COLORS: dict[str, str] = {
    "base": "#0D549D",
    "slow": "#C9892B",
    "crisis": "#C0392B",
    "threshold": "#8b5cf6",
}

_SCENARIO_LABELS: dict[str, str] = {
    "base": "Base",
    "slow": "Slow Growth",
    "crisis": "Crisis",
    "threshold": "Break-even",
}


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
# CSS
# ---------------------------------------------------------------------------


def _css() -> str:
    """This page's own styles, after `_ui.UI_CSS` (the shell, cards, tiles, ring and checklist)."""
    return """
        .chart-container {
            display: flex; justify-content: center; align-items: center; flex-wrap: wrap; gap: 2rem;
        }
        .placeholder {
            text-align: center; color: var(--ui-ink-2); font-style: italic;
            padding: 2rem; background: var(--ui-surface-2); border-radius: var(--ui-r1);
        }
        .legend {
            display: flex; justify-content: center; gap: 0.5rem 1.5rem; flex-wrap: wrap;
            margin-top: 1rem; font-size: 0.85rem; color: var(--ui-ink-2);
        }
        .legend-item { display: flex; align-items: center; gap: 0.35rem; }
        .legend-swatch { width: 12px; height: 12px; border-radius: 3px; display: inline-block; }
        .ue-row { padding: 0.6rem 0; border-bottom: 1px solid var(--ui-line); }
        .ue-row:last-of-type { border-bottom: 0; }
        .ue-row__main {
            display: grid; grid-template-columns: 170px minmax(120px, 260px) minmax(0, 1fr);
            gap: 0.4rem 1rem; align-items: center;
        }
        .ue-name { font-size: 0.9rem; font-weight: 600; }
        .ue-bar { display: block; width: 100%; height: 16px; }
        .ue-val { font-size: 0.85rem; font-weight: 500; }
        .ue-reason { font-size: 0.8rem; color: var(--ui-ink-2); margin: 0.2rem 0 0 calc(170px + 1rem); }
        .fmr-subhead { margin: var(--ui-s5) 0 var(--ui-s2); }
        .fmr-runway-summary { margin: 0 0 var(--ui-s4); font-size: 0.95rem; line-height: 1.55; max-width: 72ch; }
        .fmr-runway-chart { margin: 0 0 var(--ui-s4); }
        .fmr-runway-chart figcaption { margin-top: 4px; font-size: 0.8rem; color: var(--ui-ink-2); }
        .fmr-runway-table caption { text-align: left; font-size: 0.8rem; color: var(--ui-ink-2); padding-bottom: 6px; }
        .fmr-runway-table th[scope="row"] {
            font-weight: 600; vertical-align: top; text-transform: none; letter-spacing: normal;
            font-size: 0.88rem; color: var(--ui-ink);
        }
        .fmr-runway-table .ui-pill { white-space: nowrap; }
        .fmr-runway-table td { vertical-align: top; }
        .fmr-runway-table .fmr-num { text-align: right; }
        .fmr-scn { display: inline-flex; align-items: center; gap: 8px; }
        .fmr-swatch { display: inline-block; width: 10px; height: 10px; border-radius: 3px; flex: none; }
        .fmr-swatch--dash { height: 0; border-radius: 0; border-top: 2px dashed; }
        .fmr-assume { display: block; margin-top: 2px; font-size: 0.78rem; font-weight: 400; color: var(--ui-ink-2); }
        .fmr-runway-table th[scope="row"] .fmr-assume { margin-left: 18px; }
        @media (max-width: 640px) {
            /* On a phone each scenario is a two-line entry: name and runway, then cash-out and raise-by. */
            .fmr-runway-table thead { display: none; }
            .fmr-runway-table tr {
                display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 2px 12px;
                padding: 10px 0; border-bottom: 1px solid var(--ui-line);
            }
            .fmr-runway-table th, .fmr-runway-table td { padding: 0; border: 0; }
            .fmr-runway-table td:not(.fmr-num) { font-size: 0.8rem; color: var(--ui-ink-2); text-align: left; }
            .fmr-runway-table td[data-label="Raise by"], .fmr-runway-table td.fmr-raise { text-align: right; }
            .fmr-runway-table td[data-label]::before { content: attr(data-label) " "; }
        }
        #revenue .ui-tiles { grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); }
        .fmr-trend { min-width: 480px; }
        .fmr-runway-chart .chart-container { min-width: 520px; }
        [data-tooltip] { cursor: help; }
        @media (max-width: 640px) {
            .ue-row__main { grid-template-columns: minmax(0, 1fr) auto; }
            .ue-bar { grid-column: 1 / -1; grid-row: 2; }
            .ue-reason { margin-left: 0; }
        }
        @media print { [data-tooltip] { cursor: default; } }
    """


# ---------------------------------------------------------------------------
# Chart 1: Checklist, grouped by category
# ---------------------------------------------------------------------------


def _chart_checklist_heatmap(checklist: dict[str, Any] | None) -> str:
    """Every criterion grouped by category (`_checklist_view`, shared with the explorer), with the
    filter chips and per-group status bars of `_ui.checklist`. Problem groups stay open; all-pass
    groups close on load, and every group is open with scripts off or in print."""
    if checklist is None:
        return '<div class="placeholder">No data available</div>'
    if checklist is _CORRUPT:
        return '<div class="placeholder">Data unavailable</div>'
    if _is_stub(checklist):
        reason = _esc(checklist.get("reason", "Skipped"))
        return f'<div class="placeholder">{reason}</div>'

    items = _as_list(checklist.get("items"))
    if not items:
        return '<div class="placeholder">No checklist items</div>'

    groups = _checklist_view.groups(items)
    if not groups:
        return '<div class="placeholder">No checklist categories</div>'
    return _ui.checklist(groups)


# ---------------------------------------------------------------------------
# Chart 2: Unit Economics Dashboard (horizontal bars)
# ---------------------------------------------------------------------------

# Display labels for metric names
_METRIC_LABELS: dict[str, str] = {
    "cac": "CAC",
    "ltv": "LTV",
    "ltv_cac_ratio": "LTV/CAC Ratio",
    "cac_payback": "CAC Payback (mo)",
    "gross_margin": "Gross Margin",
    "burn_multiple": "Burn Multiple",
    "magic_number": "Magic Number",
    "rule_of_40": "Rule of 40",
    "nrr": "Net Revenue Retention",
    "grr": "Gross Revenue Retention",
    "arr_per_fte": "ARR per Employee",
    "customer_concentration": "Customer Concentration",
    "logo_churn": "Logo Churn",
    "revenue_churn": "Revenue Churn",
    "months_of_runway": "Months of Runway",
}

_RATING_LABELS: dict[str, str] = {
    "strong": "Strong",
    "acceptable": "Acceptable",
    "warning": "Needs improvement",
    "fail": "Below target",
    "not_rated": "No benchmark available",
    "not_applicable": "Not applicable",
}


def _format_metric_value(name: str, value: float, currency_code: str = "USD") -> str:
    """Format a metric value appropriately based on its type."""
    pct_metrics = {"gross_margin", "nrr", "grr"}
    if name in pct_metrics:
        return _fmt_pct(value)
    if name == "cac_payback":
        return f"{value:,.0f} mo"
    if value >= 1_000:
        return _fmt_usd(value, currency_code)
    return f"{value:,.1f}"


# Ratings that carry no grade, so the reason has to be printed beside them.
# `not_rated` is left out: its evidence is usually the value restated ("Fully loaded CAC of $1,500"),
# which the row already shows.
_UNGRADED_RATINGS = frozenset({"contextual", "not_applicable"})


def _chart_unit_economics(unit_economics: dict[str, Any] | None) -> str:
    """Bullet charts showing unit economics metrics with per-metric scaling."""
    if unit_economics is None:
        return '<div class="placeholder">No data available</div>'
    if unit_economics is _CORRUPT:
        return '<div class="placeholder">Data unavailable</div>'
    if _is_stub(unit_economics):
        reason = _esc(unit_economics.get("reason", "Skipped"))
        return f'<div class="placeholder">{reason}</div>'

    metrics = _as_list(unit_economics.get("metrics"))
    if not metrics:
        return '<div class="placeholder">No unit economics metrics</div>'

    valid_metrics: list[dict[str, Any]] = [m for m in metrics if isinstance(m, dict)]
    if not valid_metrics:
        return '<div class="placeholder">No valid metrics</div>'

    currency_code = _resolve_currency(unit_economics)
    bar_width = 220
    bar_height = 16
    parts: list[str] = []

    for m in valid_metrics:
        name = str(m.get("name", ""))
        # A figure the review could not compute has no value: it printed as "0.0" with a value bar.
        has_value = m.get("value") is not None
        value = _num(m.get("value", 0))
        rating = str(m.get("rating", ""))
        benchmark = _as_dict(m.get("benchmark"))
        display_name = _METRIC_LABELS.get(name, name.replace("_", " ").title())

        # A non-USD metric is rated `contextual` because the USD-calibrated benchmark
        # set was not established against local-currency-market companies — but the
        # dimensionless comparison DID run, and its grade is preserved here. Show it,
        # marked as a reference, so a non-USD review is not a page of ungraded numbers.
        # See the matching note in compose_report.py's unit-economics section.
        reference_rating = str(m.get("benchmark_reference_rating") or "")
        if reference_rating:
            color = _RATING_COLORS.get(reference_rating, _CLR_PRIMARY)
            rating_label = f"{_RATING_LABELS.get(reference_rating, reference_rating.title())} (ref)"
        else:
            color = _RATING_COLORS.get(rating, _CLR_PRIMARY)
            rating_label = _RATING_LABELS.get(rating, rating.title())
        val_str = _format_metric_value(name, value, currency_code) if has_value else ""

        # Determine scale for this metric's bullet chart
        target = _num(benchmark.get("target", 0))
        scale_max = max(abs(value) * 1.5, abs(target) * 1.5, 1.0)

        # Build tooltip text
        tip_parts: list[str] = [f"{display_name}: {val_str}" if has_value else f"{display_name}: {rating_label}"]
        if target:
            tip_parts.append(f"Target: {_format_metric_value(name, target, currency_code)}")
        source = benchmark.get("source", "")
        if source:
            tip_parts.append(f"Source: {source}")
        if reference_rating:
            tip_parts.append(
                f"Reference grade only ({reference_rating}) — dimensionless benchmark, "
                "no FX conversion; withheld from the rating because the benchmark set is "
                "calibrated on USD-market companies"
            )
            ref_source = str(m.get("benchmark_reference_source") or "")
            if ref_source:
                tip_parts.append(f"Reference source: {ref_source}")
        tooltip = "\n".join(tip_parts)

        # Build inline SVG bullet chart
        svg = (
            f'<svg class="ue-bar" width="{bar_width}" height="{bar_height}" '
            f'viewBox="0 0 {bar_width} {bar_height}" preserveAspectRatio="none" data-tooltip="{_esc(tooltip)}">'
        )
        # Background track
        svg += f'<rect x="0" y="0" width="{bar_width}" height="{bar_height}" fill="#F1F4F4" rx="3" />'
        # Benchmark target zone (if available)
        if target > 0:
            target_x = min(target / scale_max * bar_width, bar_width)
            svg += f'<rect x="0" y="2" width="{target_x:.1f}" height="{bar_height - 4}" fill="#D7DBE0" rx="2" />'
        # Value bar
        if has_value:
            bar_w = max(min(abs(value) / scale_max * bar_width, bar_width), 2.0)
            svg += f'<rect x="0" y="3" width="{bar_w:.1f}" height="{bar_height - 6}" fill="{_esc(color)}" rx="2" />'
        # Target marker line
        if target > 0:
            marker_x = min(target / scale_max * bar_width, bar_width - 1)
            svg += (
                f'<line x1="{marker_x:.1f}" y1="0" x2="{marker_x:.1f}" y2="{bar_height}" '
                f'stroke="#374B65" stroke-width="2" />'
            )
        svg += "</svg>"

        # A metric with no grade said only "Contextual" / "Not rated" / "Not applicable" here, while
        # report.md and the explorer print WHY (e.g. no gross-margin benchmark covers the stated
        # revenue model). Print the producer's reason under it. A graded metric's bar and benchmark
        # band already explain it. Contextual evidence leads with the figure ("Gross margin of 55%;
        # <reason>"), which the row already shows, so keep only the reason -- as the explorer does.
        reason = ""
        if rating in _UNGRADED_RATINGS and not reference_rating:
            ev = str(m.get("evidence") or "").strip()
            reason = ev.split("; ", 1)[1] if rating == "contextual" and "; " in ev else ev
            reason = reason[:1].upper() + reason[1:]
        parts.append(
            f'<div class="ue-row" data-metric="{_esc(name)}">'
            f'<div class="ue-row__main">'
            f'<span class="ue-name">{_esc(display_name)}</span>'
            f"{svg}"
            f'<span class="ue-val" style="color:{_esc(color)};">'
            f"{_esc(f'{val_str} — {rating_label}' if has_value else rating_label)}</span>"
            f"</div>" + (f'<div class="ue-reason">{_esc(reason)}</div>' if reason else "") + "</div>"
        )

    # Legend
    legend_items: list[str] = []
    for rating, color in [
        ("Strong", _CLR_PASS),
        ("Acceptable", "#21A2E3"),
        ("Needs improvement", _CLR_WARN),
        ("Below target", _CLR_FAIL),
    ]:
        legend_items.append(
            f'<span class="legend-item">'
            f'<span class="legend-swatch" style="background:{_esc(color)}"></span>'
            f" {_esc(rating)}</span>"
        )
    legend = '<div class="legend">' + "".join(legend_items) + "</div>"

    return "".join(parts) + legend


# ---------------------------------------------------------------------------
# Chart 3: Runway Scenarios Timeline (multi-line)
# ---------------------------------------------------------------------------


def _chart_runway(runway: dict[str, Any] | None) -> str:
    """Multi-line SVG chart of cash balance over time per scenario."""
    if runway is None:
        return '<div class="placeholder">No data available</div>'
    if runway is _CORRUPT:
        return '<div class="placeholder">Data unavailable</div>'
    if _is_stub(runway):
        reason = _esc(runway.get("reason", "Skipped"))
        return f'<div class="placeholder">{reason}</div>'

    scenarios = _as_list(runway.get("scenarios"))
    if not scenarios:
        return '<div class="placeholder">No runway scenarios</div>'

    currency_code = _resolve_currency(runway)

    # Collect all data points per scenario
    scenario_data: list[tuple[str, list[tuple[int, float]]]] = []
    for s in scenarios:
        if not isinstance(s, dict):
            continue
        name = str(s.get("name", "unknown"))
        projections = _as_list(s.get("monthly_projections"))
        points: list[tuple[int, float]] = []
        for p in projections:
            if not isinstance(p, dict):
                continue
            month = int(_num(p.get("month", 0)))
            cash = _num(p.get("cash_balance", 0))
            points.append((month, cash))
        if points:
            scenario_data.append((name, points))

    if not scenario_data:
        return '<div class="placeholder">No projection data</div>'

    # SVG dimensions
    margin_left = 80
    margin_right = 56
    margin_top = 30
    margin_bottom = 40
    chart_width = 500
    chart_height = 250
    svg_w = margin_left + chart_width + margin_right
    svg_h = margin_top + chart_height + margin_bottom

    # Determine a sensible time horizon for the chart.  If any scenario
    # runs out of cash, show up to 2x that horizon (min 12, max 36).
    # This keeps shorter scenarios visible instead of being dwarfed by
    # exponential growth in longer ones.
    shortest_end = min(len(pts) for _, pts in scenario_data)
    longest_end = max(len(pts) for _, pts in scenario_data)
    chart_horizon = max(min(shortest_end * 3, 36), 12) if shortest_end < longest_end else min(longest_end, 36)

    capped_data: list[tuple[str, list[tuple[int, float]]]] = []
    for name, points in scenario_data:
        capped_data.append((name, [(m, c) for m, c in points if m <= chart_horizon]))
    scenario_data = [(n, pts) for n, pts in capped_data if pts]

    if not scenario_data:
        return '<div class="placeholder">No projection data</div>'

    # Find global min/max
    all_months: list[int] = []
    all_cash: list[float] = []
    for _name, points in scenario_data:
        for month, cash in points:
            all_months.append(month)
            all_cash.append(cash)

    min_month = min(all_months) if all_months else 0
    max_month = max(all_months) if all_months else 1
    if min_month == max_month:
        max_month = min_month + 1
    min_cash = min(min(all_cash), 0)  # Include zero line
    max_cash = max(all_cash) if all_cash else 1
    if min_cash == max_cash:
        max_cash = min_cash + 1

    def x_pos(month: int) -> float:
        return _num(margin_left + (month - min_month) / (max_month - min_month) * chart_width)

    def y_pos(cash: float) -> float:
        return _num(margin_top + (1 - (cash - min_cash) / (max_cash - min_cash)) * chart_height)

    parts: list[str] = [
        f'<svg width="{_num(svg_w):.0f}" height="{_num(svg_h):.0f}" '
        f'viewBox="0 0 {_num(svg_w):.0f} {_num(svg_h):.0f}" xmlns="http://www.w3.org/2000/svg">'
    ]

    # Y-axis labels
    for i in range(5):
        frac = i / 4
        cash_val = min_cash + frac * (max_cash - min_cash)
        y = _num(margin_top + (1 - frac) * chart_height)
        parts.append(
            f'<text x="{_num(margin_left - 8):.2f}" y="{y:.2f}" '
            f'text-anchor="end" dominant-baseline="central" '
            f'font-size="11" fill="#5E6A78">{_esc(_fmt_usd(cash_val, currency_code))}</text>'
        )
        # Grid line
        parts.append(
            f'<line x1="{_num(margin_left):.2f}" y1="{y:.2f}" '
            f'x2="{_num(margin_left + chart_width):.2f}" y2="{y:.2f}" '
            f'stroke="#D7DBE0" stroke-width="1" />'
        )

    # Zero line (if visible)
    if min_cash < 0 < max_cash:
        zero_y = y_pos(0)
        parts.append(
            f'<line x1="{_num(margin_left):.2f}" y1="{zero_y:.2f}" '
            f'x2="{_num(margin_left + chart_width):.2f}" y2="{zero_y:.2f}" '
            f'stroke="{_CLR_FAIL}" stroke-width="1.5" stroke-dasharray="4,3" />'
        )
        zero_label = "$0" if currency_code == "USD" else f"0 {currency_code}"
        parts.append(
            f'<text x="{_num(margin_left + chart_width + 5):.2f}" y="{zero_y:.2f}" '
            f'dominant-baseline="central" font-size="9" fill="{_CLR_FAIL}">{_esc(zero_label)}</text>'
        )

    # X-axis label
    parts.append(
        f'<text x="{_num(margin_left + chart_width / 2):.2f}" '
        f'y="{_num(svg_h - 5):.2f}" text-anchor="middle" '
        f'font-size="10" fill="#7D90A3">Months</text>'
    )

    # Plot each scenario as a polyline. Each line is named where it ends, or at the point it reaches
    # $0 when it runs out (with a dot there), so the chart needs no separate legend.
    labels: list[tuple[float, float, str, str, bool]] = []  # (x, y, text, color, at_zero)
    for name, points in scenario_data:
        color = _SCENARIO_COLORS.get(name, _CLR_PRIMARY)
        display = _SCENARIO_LABELS.get(name, name.title())
        sorted_points = sorted(points, key=lambda p: p[0])
        point_strs = [f"{x_pos(m):.2f},{y_pos(c):.2f}" for m, c in sorted_points]
        if not point_strs:
            continue
        dash = ' stroke-dasharray="6,3"' if name == "threshold" else ""
        pts = " ".join(point_strs)
        parts.append(f'<polyline points="{pts}" fill="none" stroke="{_esc(color)}" stroke-width="2.5"{dash} />')
        zero_month: int | None = None
        for j in range(1, len(sorted_points)):
            if sorted_points[j - 1][1] > 0 >= sorted_points[j][1]:
                zero_month = sorted_points[j][0]
                break
        if zero_month is not None:
            cx, cy = x_pos(zero_month), y_pos(0)
            parts.append(
                f'<circle cx="{cx:.2f}" cy="{cy:.2f}" r="4.5" fill="{_esc(color)}" stroke="#fff" '
                f'stroke-width="1.5" data-zero="{_esc(name)}" />'
            )
            labels.append((cx, cy, f"{display} · M{zero_month}", color, True))
        else:
            labels.append((x_pos(sorted_points[-1][0]), y_pos(sorted_points[-1][1]), display, color, False))

    # A label at $0 sits above its dot; labels that would touch are stacked upwards. A label at a line's
    # end sits to its right, nudged down when another end label is too close.
    placed: list[tuple[float, float]] = []
    for lx, ly, text, color, at_zero in sorted(labels, key=lambda el: (el[0], el[1])):
        width = 6.2 * len(text)
        if at_zero:
            x, y, anchor = lx, ly - 10, "middle"
            while any(abs(x - px) < (width + 8) and abs(y - py) < 13 for px, py in placed):
                y -= 14
        else:
            x, y, anchor = lx + 6, ly, "start"
            while any(abs(x - px) < 40 and abs(y - py) < 13 for px, py in placed):
                y += 14
        placed.append((x, y))
        parts.append(
            f'<text x="{_num(x):.2f}" y="{_num(y):.2f}" text-anchor="{anchor}" dominant-baseline="central" '
            f'font-size="11" font-weight="600" fill="{_esc(color)}" stroke="#FFFFFF" stroke-width="3" '
            f'paint-order="stroke">{_esc(text)}</text>'
        )

    parts.append("</svg>")
    return (
        '<figure class="fmr-runway-chart"><div class="ui-scroll"><div class="chart-container">'
        + "\n".join(parts)
        + "</div></div><figcaption>Cash balance under each scenario. A dot marks the month cash reaches zero."
        "</figcaption></figure>"
    )


# ---------------------------------------------------------------------------
# Runway scenarios: summary sentence and scenario table
# ---------------------------------------------------------------------------

_MONTH_NAMES = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _month_text(value: Any) -> str:
    """A "YYYY-MM" month as "Mon YYYY"; anything else as written."""
    text = str(value or "").strip()
    parts = text.split("-")
    if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit() and 1 <= int(parts[1]) <= 12:
        return f"{_MONTH_NAMES[int(parts[1]) - 1]} {parts[0]}"
    return text


def _scenario_assumption(s: dict[str, Any]) -> str:
    """The scenario's own stated parameters, worded as report.md's scenarios table words them, after the
    scenario's label when runway.json gives one. "" when it states none."""
    bits: list[str] = []
    growth_rate = s.get("growth_rate")
    if isinstance(growth_rate, (int, float)) and not isinstance(growth_rate, bool):
        bits.append(f"growth {growth_rate * 100:.0f}%/mo")
    burn_change = s.get("burn_change")
    if isinstance(burn_change, (int, float)) and not isinstance(burn_change, bool):
        bits.append(f"burn {'+' if burn_change >= 0 else ''}{burn_change * 100:.0f}%")
    fx = s.get("fx_adjustment")
    if isinstance(fx, (int, float)) and not isinstance(fx, bool) and fx != 0:
        bits.append(f"fx {'+' if fx >= 0 else ''}{fx * 100:.0f}%")
    label = str(s.get("label") or "").strip()
    text = ", ".join(bits)
    return " · ".join(t for t in (label, text) if t)


def _runway_rows(runway: dict[str, Any]) -> list[dict[str, Any]]:
    """One row per scenario, earliest deadline first; a scenario that never runs out comes last."""
    risk_level = _risk_level(str(runway.get("risk_assessment") or ""))
    rows: list[dict[str, Any]] = []
    for order, s in enumerate(_as_list(runway.get("scenarios"))):
        if not isinstance(s, dict):
            continue
        name = str(s.get("name", ""))
        months = s.get("runway_months")
        months_n = _num(months) if isinstance(months, (int, float)) and not isinstance(months, bool) else None
        alive = bool(s.get("default_alive")) or (months_n is None and bool(s.get("became_profitable")))
        caveat = ""
        if months_n is not None:
            # runway.py's own lines: a raise starts 12 months before cash-out (its decision point),
            # and 18 months is its target runway (`target_runway`). Literals there, so restated here.
            tone = "fail" if months_n < 12 else "warn" if months_n <= 18 else "neutral"
            pill = f"{months_n:g} mo"
        elif alive:
            tone, pill = "pass", "Default alive"
            if name == "base" and risk_level in ("moderate", "elevated", "critical"):
                # runway.py rates this scenario moderate-or-worse risk (finding 19): never an
                # unqualified green, and the today's-burn floor travels with it.
                tone = "warn"
                static = s.get("static_runway_months")
                caveat = f"rated {risk_level} risk" + (
                    f" · {static:g} mo at today's burn" if isinstance(static, (int, float)) else ""
                )
        else:
            tone, pill = "neutral", "—"
        rows.append(
            {
                "name": name,
                "label": _SCENARIO_LABELS.get(name, name.title()),
                "color": _SCENARIO_COLORS.get(name, _CLR_PRIMARY),
                "dashed": name == "threshold",
                "assumption": _scenario_assumption(s),
                "months": months_n,
                "alive": alive,
                "profitable": bool(s.get("became_profitable")),
                "tone": tone,
                "pill": pill,
                "caveat": caveat,
                "cash_out": s.get("cash_out_date"),
                "decision": s.get("decision_point"),
                "order": order,
            }
        )
    rows.sort(key=lambda r: (r["months"] is None, r["months"] if r["months"] is not None else 0, r["order"]))
    return rows


def _runway_summary(rows: list[dict[str, Any]]) -> str:
    """One sentence from the data: what the base case does, then the earliest deadline."""
    base = next((r for r in rows if r["name"] == "base"), None)
    parts: list[str] = []
    if base is not None:
        if base["alive"] and base["tone"] == "pass" and base["profitable"]:
            parts.append("In the base case the company becomes profitable before cash runs out.")
        elif base["alive"] and base["tone"] == "pass":
            parts.append("In the base case cash does not run out within the projection.")
        elif base["alive"]:
            parts.append(f"In the base case cash does not run out within the projection, but it is {base['caveat']}.")
        elif base["months"] is not None:
            parts.append(f"In the base case cash runs out in {base['months']:g} months.")
    others = [r for r in rows if r["months"] is not None and r["name"] != "base"]
    if others:
        first = others[0]
        lead = "In the other scenarios" if base is not None else "Across the scenarios"
        parts.append(
            f"{lead} the earliest deadline is <strong>{first['months']:g} months</strong> away "
            f"({_esc(first['label'])})."
        )
    return " ".join(parts)


def _runway_table(rows: list[dict[str, Any]], runway: dict[str, Any]) -> str:
    """The scenarios as a table, earliest deadline first. A column shows only when runway.json carries
    its field; on a phone each row becomes a two-line entry (name and runway, then the two dates)."""
    scenarios = [x for x in _as_list(runway.get("scenarios")) if isinstance(x, dict)]
    has_cash_out = any("cash_out_date" in x for x in scenarios)
    has_decision = any("decision_point" in x for x in scenarios)
    head = '<th scope="col">Scenario</th><th scope="col" class="fmr-num">Runway</th>'
    if has_cash_out:
        head += '<th scope="col">Cash runs out</th>'
    if has_decision:
        head += '<th scope="col">Start raising by</th>'
    body: list[str] = []
    for r in rows:
        swatch = (
            f'<span class="fmr-swatch fmr-swatch--dash" style="border-top-color:{_esc(r["color"])}" aria-hidden="true">'
            "</span>"
            if r["dashed"]
            else f'<span class="fmr-swatch" style="background:{_esc(r["color"])}" aria-hidden="true"></span>'
        )
        assumption = f'<span class="fmr-assume">{_esc(r["assumption"])}</span>' if r["assumption"] else ""
        caveat = f'<span class="fmr-assume">{_esc(r["caveat"])}</span>' if r["caveat"] else ""
        # A neutral runway (over eighteen months) is the plain pill; the others take their status ink.
        pill_cls = "ui-pill" if r["tone"] == "neutral" else f"ui-pill ui-pill--{r['tone']}"
        cells = (
            f'<th scope="row"><span class="fmr-scn">{swatch}{_esc(r["label"])}</span>{assumption}</th>'
            f'<td class="fmr-num" data-runway-tone="{r["tone"]}"><span class="{pill_cls}">'
            f"{_esc(r['pill'])}</span>{caveat}</td>"
        )
        if has_cash_out:
            if r["cash_out"] or not r["alive"]:
                out = _month_text(r["cash_out"]) if r["cash_out"] else "—"
                cells += f'<td data-label="Out">{_esc(out)}</td>'
            else:
                cells += "<td>Does not run out</td>"
        if has_decision:
            if r["decision"] or not r["alive"]:
                raise_by = _month_text(r["decision"]) if r["decision"] else "—"
                cells += f'<td data-label="Raise by">{_esc(raise_by)}</td>'
            else:
                cells += '<td class="fmr-raise">Raise optional</td>'
        body.append(f'<tr data-scenario="{_esc(r["name"])}">{cells}</tr>')
    return (
        '<div class="ui-table-wrap"><table class="ui-table fmr-runway-table">'
        "<caption>Ordered from the earliest deadline</caption>"
        f"<thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table></div>"
    )


def _runway_section(runway: dict[str, Any] | None) -> str:
    """Runway Scenarios: a one-sentence summary, the chart, and the scenario table."""
    chart = _chart_runway(runway)
    if not _usable(runway):
        return chart
    rows = _runway_rows(runway)
    if not rows:
        return chart
    summary = _runway_summary(rows)
    lead = f'<p class="fmr-runway-summary" data-runway-summary>{summary}</p>' if summary else ""
    return lead + chart + _runway_table(rows, runway)


# ---------------------------------------------------------------------------
# Chart 4: Revenue overview (tiles from inputs.revenue, and the monthly trend)
# ---------------------------------------------------------------------------


def _fmt_rate(value: float) -> str:
    """A monthly rate as a percentage with at most one decimal (0.035 -> "3.5%"), never rounded to a
    whole number that would state a different rate."""
    return f"{round(value * 100, 1):g}%"


def _stated(value: Any) -> float | None:
    """`value` as a number when the inputs state one, else None (a missing figure is never shown as 0)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    v = float(value)
    return v if math.isfinite(v) else None


def _revenue_tiles(inputs: dict[str, Any]) -> str:
    """The revenue figures the inputs state, one tile each: ARR and MRR (with their as-of month),
    monthly growth, monthly churn and customers. A figure the inputs do not state gets no tile."""
    revenue = _as_dict(inputs.get("revenue"))
    currency_code = _resolve_currency(inputs)
    tiles: list[str] = []
    for key, label in (("arr", "ARR"), ("mrr", "MRR")):
        snap = _as_dict(revenue.get(key))
        value = _stated(snap.get("value"))
        if value is None:
            continue
        as_of = str(snap.get("as_of") or "").strip()
        tiles.append(
            _tile(
                f"revenue-{key}",
                label,
                _fmt_usd(value, currency_code),
                [f"as of {_month_text(as_of)}" if as_of else ""],
            )
        )
    growth = _stated(revenue.get("growth_rate_monthly"))
    if growth is not None:
        tiles.append(_tile("revenue-growth", "Monthly growth", _fmt_rate(growth), []))
    churn = _stated(revenue.get("churn_monthly"))
    if churn is not None:
        tiles.append(_tile("revenue-churn", "Monthly churn", _fmt_rate(churn), []))
    customers = _stated(revenue.get("customers"))
    if customers is not None:
        tiles.append(_tile("revenue-customers", "Customers", f"{customers:,.0f}", []))
    return '<div class="ui-tiles">' + "".join(tiles) + "</div>" if tiles else ""


def _revenue_months(inputs: dict[str, Any]) -> list[tuple[str, float, bool]]:
    """(month, total, actual) for every `revenue.monthly[]` entry that states both a month and a total,
    in month order."""
    rows: list[tuple[str, float, bool]] = []
    for entry in _as_list(_as_dict(inputs.get("revenue")).get("monthly")):
        if not isinstance(entry, dict):
            continue
        month = str(entry.get("month") or "").strip()
        total = _stated(entry.get("total"))
        if not month or total is None:
            continue
        rows.append((month, total, entry.get("actual") is not False))
    return sorted(rows, key=lambda r: r[0])


def _nice_ceiling(value: float) -> float:
    """The smallest 1 / 2 / 2.5 / 5 x 10^n at or above `value`, so the axis ticks read cleanly."""
    if value <= 0:
        return 1.0
    exp = math.floor(math.log10(value))
    for step in (1.0, 2.0, 2.5, 5.0, 10.0):
        top = step * 10.0**exp
        if top >= value:
            return top
    return 10.0 ** (exp + 1)


def _chart_revenue_trend(inputs: dict[str, Any]) -> str:
    """Monthly revenue as a line over a value axis, from `revenue.monthly[]`; "" with fewer than two
    months (a single point is not a trend). Projected months are drawn dashed with open dots."""
    rows = _revenue_months(inputs)
    if len(rows) < 2:
        return ""
    currency_code = _resolve_currency(inputs)
    w, h = 860, 280
    left, right, top, bottom = 72, 44, 24, 44
    plot_w, plot_h = w - left - right, h - top - bottom
    lo = min(0.0, min(t for _, t, _ in rows))
    hi = _nice_ceiling(max(t for _, t, _ in rows))
    span = hi - lo or 1.0
    n = len(rows)

    def x(i: int) -> float:
        return _num(left + (plot_w * i / (n - 1)))

    def y(v: float) -> float:
        return _num(top + plot_h * (1 - (v - lo) / span))

    parts: list[str] = [
        f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" xmlns="http://www.w3.org/2000/svg" role="img" '
        f'aria-label="{_esc(f"Monthly revenue, {_month_text(rows[0][0])} to {_month_text(rows[-1][0])}")}">'
    ]
    for k in range(5):
        v = lo + span * k / 4
        gy = y(v)
        parts.append(
            f'<line x1="{left}" y1="{gy:.2f}" x2="{w - right}" y2="{gy:.2f}" stroke="#E2E7EE" stroke-width="1" />'
        )
        parts.append(
            f'<text x="{left - 8}" y="{gy + 4:.2f}" text-anchor="end" font-size="11" fill="#5E6A78">'
            f"{_esc(_fmt_usd(v, currency_code) if v else ('$0' if currency_code == 'USD' else f'0 {currency_code}'))}"
            "</text>"
        )
    # Month labels: every month up to twelve, then every other one (or sparser) so they never collide.
    every = max(1, math.ceil(n / 12))
    for i, (month, _t, _a) in enumerate(rows):
        if i % every == 0 or i == n - 1:
            parts.append(
                f'<text x="{x(i):.2f}" y="{h - bottom + 18}" text-anchor="middle" font-size="11" '
                f'fill="#5E6A78">{_esc(_month_text(month))}</text>'
            )
    for i in range(1, n):
        dashed = not rows[i][2]
        dash = ' stroke-dasharray="5,4"' if dashed else ""
        parts.append(
            f'<line x1="{x(i - 1):.2f}" y1="{y(rows[i - 1][1]):.2f}" x2="{x(i):.2f}" y2="{y(rows[i][1]):.2f}" '
            f'stroke="{_CLR_PRIMARY}" stroke-width="2.5"{dash} />'
        )
    for i, (_m, total, actual) in enumerate(rows):
        fill = _CLR_PRIMARY if actual else "#FFFFFF"
        parts.append(
            f'<circle cx="{x(i):.2f}" cy="{y(total):.2f}" r="4" fill="{fill}" stroke="{_CLR_PRIMARY}" '
            f'stroke-width="2" />'
        )
    last_m, last_t, _ = rows[-1]
    parts.append(
        f'<text x="{x(n - 1):.2f}" y="{y(last_t) - 10:.2f}" text-anchor="end" font-size="12" font-weight="600" '
        f'fill="#374B65">{_esc(_fmt_usd(last_t, currency_code))}</text>'
    )
    parts.append("</svg>")
    legend = ""
    if any(not a for _, _, a in rows):
        legend = (
            '<div class="legend">'
            f'<span class="legend-item"><span class="legend-swatch" style="background:{_CLR_PRIMARY}"></span>'
            " Actual</span>"
            '<span class="legend-item"><span class="legend-swatch" style="background:#FFFFFF;'
            f'border:2px solid {_CLR_PRIMARY}"></span> Projected</span>'
            "</div>"
        )
    return (
        '<div class="ui-scroll" data-chart="revenue-trend"><div class="chart-container fmr-trend">'
        + "\n".join(parts)
        + "</div></div>"
        + legend
    )


def _revenue_overview(inputs: dict[str, Any] | None) -> str:
    """The Revenue Overview section's body: the stated revenue figures as tiles and, with two or more
    months of `revenue.monthly[]`, the monthly trend under them. "" when the inputs state none of it."""
    if not _usable(inputs):
        return ""
    tiles = _revenue_tiles(inputs)
    trend = _chart_revenue_trend(inputs)
    if trend:
        trend = f'<h3 class="fmr-subhead">Monthly revenue</h3>{trend}'
    return tiles + trend


# ---------------------------------------------------------------------------
# Executive Summary
# ---------------------------------------------------------------------------


def _score_coverage_note(summary: dict[str, Any]) -> str:
    """Disclose that the score was computed over fewer criteria than the company warrants.

    The percentage is a fraction, and both of these shrink its DENOMINATOR without moving the
    number: criteria the assessment self-excluded, and criteria dropped because a profile field
    could not be matched. `report.md` has said so since the warnings were added; this surface
    showed a bare percentage, so an unmatched geography read as a clean, complete score --
    measured at 91.2% "strong" on a run where four Israel-specific checks were never assessed.
    """
    self_gated = [str(i) for i in _as_list(summary.get("self_gated_items"))]
    unresolved: list[str] = []
    for _field, ids in sorted(_as_dict(summary.get("unresolved_profile_exclusions")).items()):
        unresolved.extend(str(i) for i in _as_list(ids))
    missing = len(self_gated) + len(unresolved)
    if not missing:
        return ""
    total = summary.get("total")
    over = f" of {int(_num(total))}" if total is not None else ""
    return (
        '<p class="ui-callout ui-callout--warn" data-note="score-coverage">'
        f"{missing}{over} checks were not assessed — scored over the rest"
        "</p>"
    )


def _score_ring(checklist: dict[str, Any] | None) -> tuple[str, str]:
    """(the header card's score ring, the note under it that the score left criteria out).

    A deck-only review (no spreadsheet) is scored on Business Quality, said under the ring; any other
    review on the checklist score, its status beneath. The 80 / 60 bands are the page's own.
    """
    if not _usable(checklist):
        return "", ""
    summary = _as_dict(checklist.get("summary"))
    score_pct = summary.get("score_pct")
    overall = str(summary.get("overall_status") or "")
    overall_text = overall.replace("_", " ").title()
    biz_pct = summary.get("business_quality_pct")
    mat_pct = summary.get("model_maturity_pct")
    if biz_pct is not None and mat_pct is None:
        pct = _num(biz_pct)
        shown = _ui.score_text(pct, decimals=_checklist_view.SCORE_DECIMALS)  # as report.md prints it
        ring = _ui.score_ring(
            pct,
            tone=_checklist_view.score_tone(pct),
            value_text=f"{shown}%",
            label="Business Quality",
            caption="Based on pitch deck (no spreadsheet provided)",
            aria_label=f"Business quality {shown} percent, based on pitch deck",
            href="#checklist",
        )
        return ring, ""
    if score_pct is None:
        return "", ""
    pct = _num(score_pct)
    shown = _ui.score_text(pct, decimals=_checklist_view.SCORE_DECIMALS)  # as report.md prints it
    ring = _ui.score_ring(
        pct,
        tone=_checklist_view.score_tone(pct),
        value_text=f"{shown}%",
        label="Checklist Score",
        caption=overall_text,
        aria_label=f"Checklist score {shown} percent" + (f", {overall_text}" if overall_text else ""),
        href="#checklist",
    )
    return ring, _score_coverage_note(summary)


def _tile(key: str, label: str, value: str, subs: list[str], tone: str = "", attrs: str = "") -> str:
    """One headline figure as a `ui-tile` (label, value, the lines under it). Plain text in."""
    tone_cls = f" ui-tile--{tone}" if tone else ""
    sub_html = "".join(f'<p class="ui-tile__sub">{html.escape(t, quote=False)}</p>' for t in subs if t)
    return (
        f'<div class="ui-tile{tone_cls}" data-tile="{_esc(key)}"{attrs}>'
        f'<p class="ui-tile__label">{_esc(label)}</p>'
        f'<p class="ui-tile__value" data-tile-value>{_esc(value)}</p>'
        f"{sub_html}</div>"
    )


def _executive_summary(
    inputs: dict[str, Any] | None,
    checklist: dict[str, Any] | None,
    unit_economics: dict[str, Any] | None,
    runway: dict[str, Any] | None,
) -> str:
    """Build an executive summary section with key numbers."""
    cards: list[str] = []

    # Unit economics summary
    if _usable(unit_economics):
        # The count is over GRADED figures only. A figure shown without a grade (contextual, not rated,
        # or not applicable with a value) is stated apart: a business no bar fits has nothing graded by
        # design, and "0/6" read as a failing score.
        ue_summary = _as_dict(unit_economics.get("summary"))
        strong = int(_num(ue_summary.get("strong", 0)))
        graded_n = strong + sum(int(_num(ue_summary.get(k, 0))) for k in ("acceptable", "warning", "fail"))
        # `computed` counts every figure with a value; a graded figure always has one.
        ungraded_n = max(int(_num(ue_summary.get("computed", 0))) - graded_n, 0)
        ungraded_label = f"{ungraded_n} shown without a grade"
        if graded_n:
            # List strong metric names if 3 or fewer
            strong_names: list[str] = []
            for m in _as_list(unit_economics.get("metrics")):
                if isinstance(m, dict) and m.get("rating") == "strong":
                    name = str(m.get("name", ""))
                    strong_names.append(_METRIC_LABELS.get(name, name.replace("_", " ").title()))
            if 0 < len(strong_names) <= 3:
                ue_label = ", ".join(strong_names) + " rated strong"
            else:
                ue_label = f"{strong} strong metrics"
            cards.append(
                _tile(
                    "unit-economics",
                    "Unit Economics",
                    f"{strong}/{graded_n}",
                    [ue_label, ungraded_label if ungraded_n else ""],
                )
            )
        elif ungraded_n:
            shown = f"{ungraded_n} figure{'s' if ungraded_n != 1 else ''} shown; none graded for this business"
            cards.append(_tile("unit-economics", "Unit Economics", "—", [shown]))

    # Runway (base case)
    if _usable(runway):
        scenarios = _as_list(runway.get("scenarios"))
        risk_assessment = str(runway.get("risk_assessment") or "")
        risk_level = _risk_level(risk_assessment)
        for s in scenarios:
            if isinstance(s, dict) and s.get("name") == "base":
                raw_months = s.get("runway_months")
                alive = s.get("default_alive", False)
                profitable = s.get("became_profitable", False)
                static_months = s.get("static_runway_months")
                runway_display = "∞" if raw_months is None else f"{int(_num(raw_months))} mo"
                tooltip_attr = ""
                if alive and risk_level in ("moderate", "elevated", "critical"):
                    # runway.py's own risk_assessment disagrees with a bare "cash never runs
                    # out" read (finding 19): the flat-burn projection never depletes, but the
                    # producer itself rates this scenario moderate-or-worse risk — never render
                    # it as the unqualified "strong" green a plain default_alive check would.
                    alive_tone = "warn"
                    alive_label = f"Default alive, but rated {risk_level} risk"
                    if static_months is not None:
                        alive_label += f" — {static_months:g} mo at today's burn"
                    if risk_assessment:
                        tooltip_attr = f' data-tooltip="{_esc(risk_assessment)}"'
                elif alive:
                    alive_tone = "pass"
                    alive_label = "On track to profitability" if profitable else "Default alive (cash never runs out)"
                else:
                    alive_tone = "fail"
                    alive_label = "Cash runs out before profitability"
                cards.append(
                    _tile("base-runway", "Base Runway", runway_display, [alive_label], alive_tone, tooltip_attr)
                )
                break

    # ARR from inputs
    if _usable(inputs):
        revenue = _as_dict(inputs.get("revenue"))
        arr_data = _as_dict(revenue.get("arr"))
        arr_val = _num(arr_data.get("value", 0))
        if arr_val > 0:
            currency_code = _resolve_currency(inputs)
            cards.append(_tile("arr", "ARR", _fmt_usd(arr_val, currency_code), ["current"]))

    if not cards:
        return ""

    return '<div class="ui-tiles">' + "".join(cards) + "</div>"


# ---------------------------------------------------------------------------
# Key Findings
# ---------------------------------------------------------------------------


def _key_findings(
    checklist: dict[str, Any] | None,
    unit_economics: dict[str, Any] | None,
    runway: dict[str, Any] | None,
) -> str:
    """Build an actionable Key Findings section from artifact data."""
    strong: list[str] = []
    # A checklist card is (criterion id, category, label, evidence); every other card is one sentence.
    attention: list[str | tuple[str, str, str, str]] = []
    actions: list[str] = []

    # --- Checklist findings ---
    if _usable(checklist):
        items = _as_list(checklist.get("items"))
        pass_count = sum(1 for i in items if isinstance(i, dict) and i.get("status") == "pass")
        fail_items = [i for i in items if isinstance(i, dict) and i.get("status") == "fail"]
        warn_items = [i for i in items if isinstance(i, dict) and i.get("status") == "warn"]
        total_applicable = sum(1 for i in items if isinstance(i, dict) and i.get("status") != "not_applicable")
        if total_applicable > 0 and pass_count / total_applicable >= 0.7:
            strong.append(f"Checklist: {pass_count} of {total_applicable} criteria pass")
        for item in [*fail_items[:3], *warn_items[:2]]:
            item_id = str(item.get("id") or "")
            cat = str(item.get("category", ""))
            title = (
                str(item.get("label") or "").strip() or _checklist_view.FALLBACK_LABELS.get(item_id) or "Checklist item"
            )
            raw = _checklist_view.founder_text(str(item.get("notes") or item.get("evidence") or ""))
            attention.append((item_id, cat, title, _evidence_multiple.caveat(raw)))

    # --- Unit economics findings ---
    if _usable(unit_economics):
        metrics = _as_list(unit_economics.get("metrics"))
        for m in metrics:
            if not isinstance(m, dict):
                continue
            name = str(m.get("name", ""))
            rating = str(m.get("rating", ""))
            display_name = _METRIC_LABELS.get(name, name.replace("_", " ").title())
            value = m.get("value", 0)
            if rating == "strong":
                strong.append(f"{display_name} rated strong")
            elif rating == "fail":
                val_str = f"{_num(value):,.1f}"
                attention.append(f"{display_name} below target ({val_str})")
                benchmark = _as_dict(m.get("benchmark"))
                target = benchmark.get("target")
                if target is not None:
                    actions.append(f"Improve {display_name} (currently {val_str}, target: {target})")

    # --- Runway findings ---
    if _usable(runway):
        scenarios = _as_list(runway.get("scenarios"))
        risk_assessment = str(runway.get("risk_assessment") or "")
        risk_level = _risk_level(risk_assessment)
        for s in scenarios:
            if not isinstance(s, dict):
                continue
            if s.get("name") == "base":
                if s.get("default_alive"):
                    if risk_level == "low":
                        if s.get("became_profitable"):
                            strong.append("On track to profitability (base case)")
                        else:
                            strong.append("Default alive — cash never runs out (base case)")
                    else:
                        # runway.py's own risk_assessment rates this scenario
                        # moderate-or-worse (finding 19): a flat-burn projection that never
                        # depletes cash is not the same as a safe cash position, so it must
                        # not be filed under "What's strong".
                        static_months = s.get("static_runway_months")
                        attention.append(risk_assessment or f"Default alive but rated {risk_level} risk (base case)")
                        if static_months is not None:
                            actions.append(
                                f"Treat the {static_months:g}-month static runway (today's burn, no growth) as "
                                "the planning number, not the flat-burn projection"
                            )
                else:
                    months = s.get("runway_months")
                    if months is not None:
                        attention.append(f"Cash runs out in {int(_num(months))} months (base case)")
                        actions.append("Extend runway: cut burn or accelerate revenue")

    # --- Build HTML ---
    if not strong and not attention and not actions:
        return ""

    parts: list[str] = []

    def _card(item: str | tuple[str, str, str, str], tone: str) -> str:
        if isinstance(item, str):
            return f'<div class="ui-finding ui-finding--{tone}">{_esc(item)}</div>'
        item_id, cat, title, body = item
        eyebrow = f'<p class="ui-finding__eyebrow">{_esc(cat)}</p>' if cat else ""
        body_html = f'<p class="ui-finding__body">{_esc(body)}</p>' if body else ""
        return (
            f'<div class="ui-finding ui-finding--{tone}" data-finding="{_esc(item_id)}">'
            f'{eyebrow}<p class="ui-finding__title">{_esc(title)}</p>{body_html}</div>'
        )

    def _column(
        key: str, heading: str, items: list[str] | list[str | tuple[str, str, str, str]], tone: str, max_items: int = 3
    ) -> str:
        cards = "".join(_card(item, tone) for item in items[:max_items])
        return f'<div class="ui-finding-col" data-findings="{key}"><h3>{heading}</h3>{cards}</div>'

    if strong:
        parts.append(_column("strong", "What's strong", strong, "pass"))
    if attention:
        parts.append(_column("attention", "What needs attention", attention, "fail"))
    if actions:
        parts.append(_column("actions", "Top actions", actions, "action"))

    return '<div class="ui-findings">' + "".join(parts) + "</div>"


# ---------------------------------------------------------------------------
# Main HTML composition
# ---------------------------------------------------------------------------


# The values-check notes, compose_report.py's text word for word (a test holds them equal); shown only on a
# run whose ledger records the values went on unreviewed, or were taken as checked without asking.
EXTRACTION_UNREVIEWED_NOTE = (
    "The figures this review used were not checked with you before the analysis ran, so check them against "
    "your model before relying on these numbers."
)
VALUES_BY_REQUEST_NOTE = (
    "The extracted values were not put to you as a question: the request that started this review said they "
    "had been checked."
)


def _headline(dir_path: str) -> str:
    """The coaching commentary's headline, the verdict the explorer opens with; "" without one.

    Read the way explore.py reads it: commentary.json must be an object with a `headline`.
    """
    raw = _load_artifact(dir_path, "commentary.json")
    if not isinstance(raw, dict) or raw is _CORRUPT:
        return ""
    return str(raw.get("headline") or "").strip()


def compose_html(dir_path: str, review_note: str = "") -> str:
    """Load artifacts and compose full HTML report."""
    scripts_dir = os.path.dirname(os.path.abspath(__file__))
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    import _growth_rate
    import _theme

    all_names = REQUIRED_ARTIFACTS + OPTIONAL_ARTIFACTS
    artifacts: dict[str, dict[str, Any] | None] = {}
    for name in all_names:
        artifacts[name] = _load_artifact(dir_path, name)

    inputs = artifacts.get("inputs.json")
    checklist = artifacts.get("checklist.json")
    unit_economics = artifacts.get("unit_economics.json")
    runway = artifacts.get("runway.json")

    # Company name from inputs
    company_name = "Financial Model Review"
    if _usable(inputs):
        company = _as_dict(inputs.get("company"))
        company_name = str(company.get("company_name", "Financial Model Review"))

    # Build sections
    summary_html = _executive_summary(inputs, checklist, unit_economics, runway)
    # A growth rate computed from the monthly series, not stated: the same sentence report.md carries.
    growth_note = _growth_rate.disclosure(inputs) if _usable(inputs) else None
    if growth_note is not None:
        summary_html += f'<p class="ui-callout growth-note" data-note="growth">{_esc(growth_note)}</p>'
    findings_html = _key_findings(checklist, unit_economics, runway)
    checklist_html = _chart_checklist_heatmap(checklist)
    unit_econ_html = _chart_unit_economics(unit_economics)
    runway_html = _runway_section(runway)
    # The revenue the inputs state, as tiles, and the monthly trend when there are two or more months.
    revenue_html = _revenue_overview(inputs)

    ring_html, coverage_html = _score_ring(checklist)
    note_html = (
        f'<p class="ui-callout review-note" data-note="review"><em>{_esc(review_note)}</em></p>' if review_note else ""
    )
    header = _ui.header_card(
        eyebrow="Financial Model Review",
        title=company_name,
        verdict_html=_esc(_headline(dir_path)),
        body_html=note_html + coverage_html,
        ring_html=ring_html,
    )

    # (section id, heading, body). Optional sections drop out when empty.
    sections: list[tuple[str, str, str]] = [("summary", "Executive Summary", summary_html)]
    if findings_html:
        sections.append(("findings", "Key Findings", findings_html))
    sections += [
        ("checklist", "Checklist", checklist_html),
        ("unit-economics", "Unit Economics Dashboard", unit_econ_html),
        ("runway", "Runway Scenarios", runway_html),
    ]
    if revenue_html:
        sections.append(("revenue", "Revenue Overview", revenue_html))

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
        title=f"Financial Model Review: {company_name}",
        body_html=body,
        brand_css=_theme.brand_css(),
        page_css=_css(),
        skill_name="Financial Model Review",
        scripts_html=_tooltip_js() + "\n",
    )


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


def _review_note(dir_path: str) -> str:
    """The values-check note for a run with a gate ledger; empty with none (nothing shared is loaded)."""
    scripts_dir = os.path.dirname(os.path.abspath(__file__))
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    import _fmr_gates

    rec = _fmr_gates.values_record(dir_path)
    if rec is None:
        return ""
    if rec.get("answer_id") == "proceed_unreviewed":
        return EXTRACTION_UNREVIEWED_NOTE
    if rec.get("answer_id") == "values_ok" and (rec.get("by_request") or rec.get("resolution") == "default_taken"):
        return VALUES_BY_REQUEST_NOTE
    return ""


def _own_run_id(dir_path: str) -> str | None:
    """This page's run id: inputs.json's."""
    rid: str | None = _run_ref_module().json_run_id(os.path.join(dir_path, "inputs.json"))
    return rid


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    p = argparse.ArgumentParser(description="Generate HTML visualization from financial model review artifacts")
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
                "checklist.json",
                "unit_economics.json",
                "runway.json",
                "model_data.json",
                "extraction_corrections.json",
                "commentary.json",
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
                for n in ("inputs.json", "checklist.json", "unit_economics.json", "runway.json")
            ],
            noun="review dir",
        )
        _IGNORED_OTHER_RUN.update(
            n
            for n, _r in _run_ref.foreign_artifacts(
                args.dir, args.run_id, [os.path.join(args.dir, n) for n in ("extraction_corrections.json",)]
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

    html_output = compose_html(args.dir, _review_note(args.dir))
    if args.run_id is not None:
        html_output = _run_ref_module().page_for_run(html_output, args.run_id, _own_run_id(args.dir))
    _write_output(html_output, args.output)
    if args.run_id is not None and args.output:
        _run_ref_module().list_page(args.dir, args.run_id, "report_html", args.output, "visualize.py")


if __name__ == "__main__":
    main()
