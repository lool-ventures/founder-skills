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
from typing import Any, TypeGuard

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


def _fmt_pct(value: float | int) -> str:
    """Format a value as a percentage string."""
    if isinstance(value, float) and value <= 1.0:
        return f"{value * 100:.0f}%"
    return f"{value:.0f}%"


# ---------------------------------------------------------------------------
# Color scheme
# ---------------------------------------------------------------------------

_CLR_PRIMARY = "#0d549d"
_CLR_ACCENT = "#21a2e3"
_CLR_PASS = "#10b981"
_CLR_WARN = "#f59e0b"
_CLR_FAIL = "#ef4444"
_CLR_NA = "#9ca3af"

_STATUS_COLORS: dict[str, str] = {
    "pass": _CLR_PASS,
    "fail": _CLR_FAIL,
    "warn": _CLR_WARN,
    "not_applicable": _CLR_NA,
}

_CHECKLIST_LABELS: dict[str, str] = {
    "STRUCT_01": "Assumptions on dedicated tab",
    "STRUCT_02": "Tab structure is navigable",
    "STRUCT_03": "Actuals vs. projections separated",
    "STRUCT_04": "Scenario toggles (base/up/down)",
    "STRUCT_05": "Model matches pitch deck",
    "STRUCT_06": "Version/date included",
    "STRUCT_07": "Monthly granularity appropriate",
    "STRUCT_08": "No structural errors",
    "STRUCT_09": "Professional formatting",
    "UNIT_10": "Revenue is bottom-up",
    "UNIT_11": "Churn modeled explicitly",
    "UNIT_12": "Pricing logic explicit",
    "UNIT_13": "Expansion revenue modeled",
    "UNIT_14": "COGS/margin matches model type",
    "UNIT_15": "CAC fully loaded",
    "UNIT_16": "CAC payback computed",
    "UNIT_17": "LTV/CAC shown",
    "UNIT_18": "Sales capacity constrains revenue",
    "UNIT_19": "Conversion rates grounded",
    "CASH_20": "Headcount plan drives expenses",
    "CASH_21": "Benefits/tax burden included",
    "CASH_22": "Working capital modeled",
    "CASH_23": "Cash runway computed correctly",
    "CASH_24": "Runway length adequate",
    "CASH_25": "Cash-out date explicit",
    "CASH_26": "Step costs captured",
    "CASH_27": "OpEx scales with revenue",
    "CASH_28": "FX sensitivity modeled",
    "CASH_29": "Entity-level cash solvent",
    "CASH_30": "Israel statutory costs itemized",
    "CASH_31": "Government grants modeled",
    "CASH_32": "VAT/indirect tax cash timing",
    "METRIC_33": "KPI summary visible",
    "METRIC_34": "Burn multiple tracked",
    "METRIC_35": "Benchmark awareness",
    "BRIDGE_36": "Raise-runway-milestones linked",
    "BRIDGE_37": "Next-round milestones identified",
    "BRIDGE_38": "Dilution/ownership shown",
    "SECTOR_39": "Marketplace: two-sided mechanics",
    "SECTOR_40": "AI: inference costs modeled",
    "SECTOR_41": "Hardware: milestones + capex",
    "SECTOR_42": "Usage-based: margin at scale",
    "SECTOR_43": "Consumer: retention curves",
    "SECTOR_44": "Deferred revenue handled",
    "OVERALL_45": "5-minute audit possible",
    "OVERALL_46": "Country-level metrics tracked",
}

_STATUS_ICONS: dict[str, str] = {
    "pass": "\u2713",  # checkmark
    "fail": "\u2717",  # X
    "warn": "\u26a0",  # warning triangle
    "not_applicable": "\u2014",  # em dash
}

_RATING_COLORS: dict[str, str] = {
    "strong": _CLR_PASS,
    "acceptable": "#3b82f6",
    "warning": _CLR_WARN,
    "fail": _CLR_FAIL,
}

_SCENARIO_COLORS: dict[str, str] = {
    "base": "#3b82f6",
    "slow": "#f59e0b",
    "crisis": "#ef4444",
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
        .summary-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 1rem;
            margin-bottom: 1.5rem;
        }}
        .summary-card {{
            background: #f9fafb;
            border: 1px solid #e5e7eb;
            border-radius: 0.5rem;
            padding: 1rem;
            text-align: center;
        }}
        .summary-card .label {{
            font-size: 0.75rem;
            color: #6b7280;
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }}
        .summary-card .value {{
            font-size: 1.5rem;
            font-weight: bold;
            color: #1f2937;
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
# Chart 1: Checklist Heatmap
# ---------------------------------------------------------------------------


def _chart_checklist_heatmap(checklist: dict[str, Any] | None) -> str:
    """Categorized status list with compact color bars and expandable item details."""
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

    # Group items by category, preserving order
    categories: list[str] = []
    cat_items: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        cat = str(item.get("category", "Other"))
        if cat not in cat_items:
            categories.append(cat)
            cat_items[cat] = []
        cat_items[cat].append(item)

    if not categories:
        return '<div class="placeholder">No checklist categories</div>'

    parts: list[str] = []
    for cat in categories:
        cat_list = cat_items[cat]
        # Count statuses
        counts: dict[str, int] = {"pass": 0, "fail": 0, "warn": 0, "not_applicable": 0}
        for item in cat_list:
            status = str(item.get("status", "not_applicable"))
            counts[status] = counts.get(status, 0) + 1
        applicable = len(cat_list) - counts["not_applicable"]
        pass_pct = f"{counts['pass'] / applicable * 100:.0f}%" if applicable > 0 else "N/A"

        # Compact color bar (inline SVG)
        bar_w = 200
        bar_h = 8
        bar_svg = f'<svg width="{bar_w}" height="{bar_h}" style="vertical-align:middle;">'
        x_offset = 0.0
        for status in ("pass", "fail", "warn", "not_applicable"):
            if counts[status] > 0:
                seg_w = counts[status] / len(cat_list) * bar_w
                color = _STATUS_COLORS.get(status, _CLR_NA)
                bar_svg += (
                    f'<rect x="{x_offset:.1f}" y="0" width="{seg_w:.1f}" height="{bar_h}" fill="{_esc(color)}" />'
                )
                x_offset += seg_w
        bar_svg += "</svg>"

        # Category header (collapsible toggle)
        header_text = f"{_esc(cat)} — {counts['pass']}/{applicable} ({pass_pct})"
        parts.append(
            f'<div style="margin-bottom:0.75rem;">'
            f'<div class="collapsible-toggle">'
            f'<span class="chevron">\u25b6</span>'
            f'<span style="font-weight:600;font-size:0.9rem;">{header_text}</span>'
            f'<span style="margin-left:0.5rem;">{bar_svg}</span>'
            f"</div>"
        )

        # Collapsible item list (hidden by default)
        parts.append('<div class="collapsible-content" style="display:none;">')
        for item in cat_list:
            item_id = str(item.get("id", ""))
            status = str(item.get("status", "not_applicable"))
            icon = _STATUS_ICONS.get(status, "\u2014")
            color = _STATUS_COLORS.get(status, _CLR_NA)
            label = _CHECKLIST_LABELS.get(item_id, item_id)
            evidence = str(item.get("evidence") or item.get("notes") or "")
            parts.append(
                f'<div style="display:flex;align-items:flex-start;gap:0.5rem;'
                f'padding:0.35rem 0;border-bottom:1px solid #f3f4f6;">'
                f'<span style="color:{_esc(color)};font-weight:bold;min-width:1.2rem;">'
                f"{_esc(icon)}</span>"
                f"<div>"
                f'<span style="font-size:0.85rem;">{_esc(label)}</span>'
            )
            if evidence:
                parts.append(f'<div style="font-size:0.75rem;color:#6b7280;margin-top:0.15rem;">{_esc(evidence)}</div>')
            parts.append("</div></div>")
        parts.append("</div></div>")

    # Legend
    legend_items: list[str] = []
    for status, color in [("pass", _CLR_PASS), ("fail", _CLR_FAIL), ("warn", _CLR_WARN), ("n/a", _CLR_NA)]:
        legend_items.append(
            f'<span class="legend-item">'
            f'<span class="legend-swatch" style="background:{_esc(color)}"></span>'
            f" {_esc(status.title())}</span>"
        )
    legend = '<div class="legend">' + "".join(legend_items) + "</div>"

    return "".join(parts) + legend


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
}


def _format_metric_value(name: str, value: float) -> str:
    """Format a metric value appropriately based on its type."""
    pct_metrics = {"gross_margin", "nrr", "grr"}
    if name in pct_metrics and 0 < value <= 2.0:
        return _fmt_pct(value)
    if name == "cac_payback":
        return f"{value:,.0f} mo"
    if value >= 1_000:
        return _fmt_usd(value)
    return f"{value:,.1f}"


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

    bar_width = 220
    bar_height = 16
    parts: list[str] = []

    for m in valid_metrics:
        name = str(m.get("name", ""))
        value = _num(m.get("value", 0))
        rating = str(m.get("rating", ""))
        benchmark = _as_dict(m.get("benchmark"))
        color = _RATING_COLORS.get(rating, _CLR_PRIMARY)
        display_name = _METRIC_LABELS.get(name, name.replace("_", " ").title())
        rating_label = _RATING_LABELS.get(rating, rating.title())
        val_str = _format_metric_value(name, value)

        # Determine scale for this metric's bullet chart
        target = _num(benchmark.get("target", 0))
        scale_max = max(abs(value) * 1.5, abs(target) * 1.5, 1.0)

        # Build tooltip text
        tip_parts: list[str] = [f"{display_name}: {val_str}"]
        if target:
            tip_parts.append(f"Target: {_format_metric_value(name, target)}")
        source = benchmark.get("source", "")
        if source:
            tip_parts.append(f"Source: {source}")
        tooltip = "\n".join(tip_parts)

        # Build inline SVG bullet chart
        svg = (
            f'<svg width="{bar_width}" height="{bar_height}" '
            f'style="vertical-align:middle;" data-tooltip="{_esc(tooltip)}">'
        )
        # Background track
        svg += f'<rect x="0" y="0" width="{bar_width}" height="{bar_height}" fill="#f3f4f6" rx="3" />'
        # Benchmark target zone (if available)
        if target > 0:
            target_x = min(target / scale_max * bar_width, bar_width)
            svg += f'<rect x="0" y="2" width="{target_x:.1f}" height="{bar_height - 4}" fill="#e5e7eb" rx="2" />'
        # Value bar
        bar_w = max(min(abs(value) / scale_max * bar_width, bar_width), 2.0)
        svg += f'<rect x="0" y="3" width="{bar_w:.1f}" height="{bar_height - 6}" fill="{_esc(color)}" rx="2" />'
        # Target marker line
        if target > 0:
            marker_x = min(target / scale_max * bar_width, bar_width - 1)
            svg += (
                f'<line x1="{marker_x:.1f}" y1="0" x2="{marker_x:.1f}" y2="{bar_height}" '
                f'stroke="#374151" stroke-width="2" />'
            )
        svg += "</svg>"

        parts.append(
            f'<div style="display:flex;align-items:center;gap:0.75rem;'
            f'padding:0.4rem 0;border-bottom:1px solid #f3f4f6;">'
            f'<span style="min-width:140px;font-size:0.85rem;font-weight:600;'
            f'color:#1f2937;">{_esc(display_name)}</span>'
            f"{svg}"
            f'<span style="min-width:120px;font-size:0.8rem;color:{_esc(color)};">'
            f"{_esc(val_str)} — {_esc(rating_label)}</span>"
            f"</div>"
        )

    # Legend
    legend_items: list[str] = []
    for rating, color in [
        ("Strong", _CLR_PASS),
        ("Acceptable", "#3b82f6"),
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
    margin_right = 30
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
        f'<svg width="{_num(svg_w):.0f}" height="{_num(svg_h):.0f}" xmlns="http://www.w3.org/2000/svg">'
    ]

    # Y-axis labels
    for i in range(5):
        frac = i / 4
        cash_val = min_cash + frac * (max_cash - min_cash)
        y = _num(margin_top + (1 - frac) * chart_height)
        parts.append(
            f'<text x="{_num(margin_left - 8):.2f}" y="{y:.2f}" '
            f'text-anchor="end" dominant-baseline="central" '
            f'font-size="9" fill="#9ca3af">{_esc(_fmt_usd(cash_val))}</text>'
        )
        # Grid line
        parts.append(
            f'<line x1="{_num(margin_left):.2f}" y1="{y:.2f}" '
            f'x2="{_num(margin_left + chart_width):.2f}" y2="{y:.2f}" '
            f'stroke="#e5e7eb" stroke-width="1" />'
        )

    # Zero line (if visible)
    if min_cash < 0 < max_cash:
        zero_y = y_pos(0)
        parts.append(
            f'<line x1="{_num(margin_left):.2f}" y1="{zero_y:.2f}" '
            f'x2="{_num(margin_left + chart_width):.2f}" y2="{zero_y:.2f}" '
            f'stroke="#ef4444" stroke-width="1.5" stroke-dasharray="4,3" />'
        )
        parts.append(
            f'<text x="{_num(margin_left + chart_width + 5):.2f}" y="{zero_y:.2f}" '
            f'dominant-baseline="central" font-size="9" fill="#ef4444">$0</text>'
        )

    # X-axis label
    parts.append(
        f'<text x="{_num(margin_left + chart_width / 2):.2f}" '
        f'y="{_num(svg_h - 5):.2f}" text-anchor="middle" '
        f'font-size="10" fill="#6b7280">Months</text>'
    )

    # Plot each scenario as a polyline
    end_labels: list[tuple[float, float, str, str]] = []  # (x, y, name, color)
    for name, points in scenario_data:
        color = _SCENARIO_COLORS.get(name, _CLR_PRIMARY)
        sorted_points = sorted(points, key=lambda p: p[0])
        point_strs = [f"{x_pos(m):.2f},{y_pos(c):.2f}" for m, c in sorted_points]
        if point_strs:
            dash = ' stroke-dasharray="6,3"' if name == "threshold" else ""
            pts = " ".join(point_strs)
            parts.append(f'<polyline points="{pts}" fill="none" stroke="{_esc(color)}" stroke-width="2.5"{dash} />')
            last_x = x_pos(sorted_points[-1][0])
            last_y = y_pos(sorted_points[-1][1])
            display = _SCENARIO_LABELS.get(name, name.title())
            end_labels.append((last_x, last_y, display, color))

            # Cash-out marker: dot where line crosses zero
            for j in range(1, len(sorted_points)):
                prev_cash = sorted_points[j - 1][1]
                curr_cash = sorted_points[j][1]
                if prev_cash > 0 >= curr_cash:
                    cx = x_pos(sorted_points[j][0])
                    cy = y_pos(0)
                    parts.append(
                        f'<circle cx="{cx:.2f}" cy="{cy:.2f}" r="4" '
                        f'fill="{_esc(color)}" stroke="#fff" stroke-width="1.5" '
                        f'data-tooltip="Month {sorted_points[j][0]}: cash runs out ({_esc(name)})" />'
                    )
                    break

    # Label collision avoidance: offset labels that are within 15px vertically
    end_labels.sort(key=lambda el: el[1])
    for i in range(1, len(end_labels)):
        if abs(end_labels[i][1] - end_labels[i - 1][1]) < 15:
            x, y, n, c = end_labels[i]
            end_labels[i] = (x, end_labels[i - 1][1] + 15, n, c)

    for lx, ly, lname, lcolor in end_labels:
        parts.append(
            f'<text x="{_num(lx + 5):.2f}" y="{ly:.2f}" '
            f'dominant-baseline="central" font-size="9" '
            f'fill="{_esc(lcolor)}" font-weight="bold">{_esc(lname)}</text>'
        )

    # Decision point markers from scenario data
    for s in scenarios:
        if not isinstance(s, dict):
            continue
        dp_list = _as_list(s.get("decision_points"))
        dp_single = _as_dict(s.get("decision_point"))
        if dp_single and dp_single.get("month"):
            dp_list = [dp_single] + dp_list
        for dp in dp_list:
            if not isinstance(dp, dict):
                continue
            dp_month = int(_num(dp.get("month", 0)))
            dp_action = str(dp.get("action", ""))
            if dp_month > 0 and min_month <= dp_month <= max_month:
                dpx = x_pos(dp_month)
                parts.append(
                    f'<line x1="{dpx:.2f}" y1="{_num(margin_top):.2f}" '
                    f'x2="{dpx:.2f}" y2="{_num(margin_top + chart_height):.2f}" '
                    f'stroke="{_CLR_ACCENT}" stroke-width="1.5" stroke-dasharray="4,3" />'
                )
                if dp_action:
                    parts.append(
                        f'<text x="{dpx:.2f}" y="{_num(margin_top - 5):.2f}" '
                        f'text-anchor="middle" font-size="8" fill="{_CLR_ACCENT}">'
                        f"{_esc(dp_action[:30])}</text>"
                    )

    parts.append("</svg>")

    # Legend
    legend_items: list[str] = []
    for name, _points in scenario_data:
        color = _SCENARIO_COLORS.get(name, _CLR_PRIMARY)
        legend_items.append(
            f'<span class="legend-item">'
            f'<span class="legend-swatch" style="background:{_esc(color)}"></span>'
            f" {_esc(_SCENARIO_LABELS.get(name, name.title()))}</span>"
        )
    legend = '<div class="legend">' + "".join(legend_items) + "</div>"

    # Annotation box summarizing key runway numbers
    annotations: list[str] = []
    for s in scenarios:
        if not isinstance(s, dict):
            continue
        sname = str(s.get("name", ""))
        slabel = _SCENARIO_LABELS.get(sname, sname.title())
        months = s.get("runway_months")
        if months is not None:
            annotations.append(f"{slabel}: {int(_num(months))} months runway")
        elif s.get("default_alive"):
            annotations.append(f"{slabel}: on track to profitability")
    annotation_html = ""
    if annotations:
        items_html = "".join(
            f'<div class="finding-item" style="border-left-color:{_CLR_ACCENT};">{_esc(a)}</div>'
            for a in annotations[:4]
        )
        annotation_html = f'<div style="margin-top:1rem;">{items_html}</div>'

    return '<div class="chart-container">' + "\n".join(parts) + "</div>" + legend + annotation_html


# ---------------------------------------------------------------------------
# Chart 4: Revenue Waterfall (optional ARR bar)
# ---------------------------------------------------------------------------


def _chart_revenue_waterfall(inputs: dict[str, Any] | None) -> str:
    """Simple bar chart showing ARR value if available."""
    if inputs is None:
        return '<div class="placeholder">No data available</div>'
    if inputs is _CORRUPT:
        return '<div class="placeholder">Data unavailable</div>'
    if _is_stub(inputs):
        reason = _esc(inputs.get("reason", "Skipped"))
        return f'<div class="placeholder">{reason}</div>'

    revenue = _as_dict(inputs.get("revenue"))
    arr_data = _as_dict(revenue.get("arr"))
    arr_value = _num(arr_data.get("value", 0))
    arr_as_of = str(arr_data.get("as_of", ""))

    if arr_value <= 0:
        return '<div class="placeholder">No ARR data available</div>'

    # Simple single-bar chart
    svg_w = 300
    svg_h = 200
    margin_top = 30
    margin_bottom = 40
    bar_x = 100
    bar_width = 100
    chart_height = svg_h - margin_top - margin_bottom
    bar_h = _num(chart_height * 0.8)

    parts: list[str] = [f'<svg width="{svg_w}" height="{svg_h}" xmlns="http://www.w3.org/2000/svg">']

    bar_y = _num(margin_top + chart_height - bar_h)
    parts.append(
        f'<rect x="{_num(bar_x):.2f}" y="{bar_y:.2f}" '
        f'width="{_num(bar_width):.2f}" height="{bar_h:.2f}" '
        f'fill="{_CLR_PRIMARY}" opacity="0.8" rx="4" />'
    )

    # Value label above bar
    parts.append(
        f'<text x="{_num(bar_x + bar_width / 2):.2f}" y="{_num(bar_y - 8):.2f}" '
        f'text-anchor="middle" font-size="14" fill="#1f2937" font-weight="bold">'
        f"{_esc(_fmt_usd(arr_value))}</text>"
    )

    # Label below bar
    label = "ARR"
    if arr_as_of:
        label = f"ARR (as of {arr_as_of})"
    parts.append(
        f'<text x="{_num(bar_x + bar_width / 2):.2f}" y="{_num(margin_top + chart_height + 18):.2f}" '
        f'text-anchor="middle" font-size="11" fill="#6b7280">{_esc(label)}</text>'
    )

    parts.append("</svg>")

    return '<div class="chart-container">' + "\n".join(parts) + "</div>"


# ---------------------------------------------------------------------------
# Executive Summary
# ---------------------------------------------------------------------------


def _executive_summary(
    inputs: dict[str, Any] | None,
    checklist: dict[str, Any] | None,
    unit_economics: dict[str, Any] | None,
    runway: dict[str, Any] | None,
) -> str:
    """Build an executive summary section with key numbers."""
    cards: list[str] = []

    # Checklist score
    if _usable(checklist):
        summary = _as_dict(checklist.get("summary"))
        score_pct = summary.get("score_pct")
        overall = summary.get("overall_status", "")
        biz_pct = summary.get("business_quality_pct")
        mat_pct = summary.get("model_maturity_pct")

        if biz_pct is not None and mat_pct is None:
            # Deck-only review: show Business Quality
            color = _CLR_PASS if _num(biz_pct) >= 80 else (_CLR_WARN if _num(biz_pct) >= 60 else _CLR_FAIL)
            cards.append(
                f'<div class="summary-card">'
                f'<div class="label">Business Quality</div>'
                f'<div class="value" style="color:{_esc(color)}">{_esc(f"{_num(biz_pct):.0f}%")}</div>'
                f'<div class="label">Based on pitch deck (no spreadsheet provided)</div>'
                f"</div>"
            )
        elif score_pct is not None:
            # Normal: show Checklist Score
            color = _CLR_PASS if _num(score_pct) >= 80 else (_CLR_WARN if _num(score_pct) >= 60 else _CLR_FAIL)
            cards.append(
                f'<div class="summary-card">'
                f'<div class="label">Checklist Score</div>'
                f'<div class="value" style="color:{_esc(color)}">{_esc(f"{_num(score_pct):.0f}%")}</div>'
                f'<div class="label">{_esc(overall)}</div>'
                f"</div>"
            )

    # Unit economics summary
    if _usable(unit_economics):
        ue_summary = _as_dict(unit_economics.get("summary"))
        strong = int(_num(ue_summary.get("strong", 0)))
        computed = int(_num(ue_summary.get("computed", 0)))
        if computed > 0:
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
                f'<div class="summary-card">'
                f'<div class="label">Unit Economics</div>'
                f'<div class="value" style="color:{_CLR_PRIMARY}">{_esc(str(strong))}/{_esc(str(computed))}</div>'
                f'<div class="label">{_esc(ue_label)}</div>'
                f"</div>"
            )

    # Runway (base case)
    if _usable(runway):
        scenarios = _as_list(runway.get("scenarios"))
        for s in scenarios:
            if isinstance(s, dict) and s.get("name") == "base":
                raw_months = s.get("runway_months")
                alive = s.get("default_alive", False)
                alive_color = _CLR_PASS if alive else _CLR_FAIL
                runway_display = "∞" if raw_months is None else f"{int(_num(raw_months))} mo"
                cards.append(
                    f'<div class="summary-card">'
                    f'<div class="label">Base Runway</div>'
                    f'<div class="value" style="color:{_esc(alive_color)}">{runway_display}</div>'
                    f'<div class="label">'
                    f"{'On track to profitability' if alive else 'Cash runs out before profitability'}"
                    f"</div>"
                    f"</div>"
                )
                break

    # ARR from inputs
    if _usable(inputs):
        revenue = _as_dict(inputs.get("revenue"))
        arr_data = _as_dict(revenue.get("arr"))
        arr_val = _num(arr_data.get("value", 0))
        if arr_val > 0:
            cards.append(
                f'<div class="summary-card">'
                f'<div class="label">ARR</div>'
                f'<div class="value" style="color:{_CLR_PRIMARY}">{_esc(_fmt_usd(arr_val))}</div>'
                f'<div class="label">current</div>'
                f"</div>"
            )

    if not cards:
        return ""

    return '<div class="summary-grid">' + "".join(cards) + "</div>"


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
    attention: list[str] = []
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
        for item in fail_items[:3]:
            cat = str(item.get("category", ""))
            notes = str(item.get("notes") or item.get("evidence") or "")
            label = f"{cat}: {notes}" if notes else cat
            attention.append(label)
        for item in warn_items[:2]:
            cat = str(item.get("category", ""))
            notes = str(item.get("notes") or item.get("evidence") or "")
            label = f"{cat}: {notes}" if notes else cat
            attention.append(label)

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
        for s in scenarios:
            if not isinstance(s, dict):
                continue
            if s.get("name") == "base":
                if s.get("default_alive"):
                    strong.append("On track to profitability (base case)")
                else:
                    months = s.get("runway_months")
                    if months is not None:
                        attention.append(f"Cash runs out in {int(_num(months))} months (base case)")
                        actions.append("Extend runway: cut burn or accelerate revenue")

    # --- Build HTML ---
    if not strong and not attention and not actions:
        return ""

    parts: list[str] = []

    def _render_items(items: list[str], css_class: str, max_items: int = 3) -> str:
        html_parts: list[str] = []
        for item in items[:max_items]:
            html_parts.append(f'<div class="finding-item {css_class}">{_esc(item)}</div>')
        return "".join(html_parts)

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

    return "".join(parts)


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
    findings_html = _key_findings(checklist, unit_economics, runway)
    checklist_html = _chart_checklist_heatmap(checklist)
    unit_econ_html = _chart_unit_economics(unit_economics)
    runway_html = _chart_runway(runway)
    # Revenue section only if MRR time-series data exists
    has_mrr_series = False
    if _usable(inputs):
        revenue = _as_dict(inputs.get("revenue"))
        has_mrr_series = len(_as_list(revenue.get("mrr_history"))) > 1
    revenue_html = _chart_revenue_waterfall(inputs) if has_mrr_series else ""

    # Key Findings section (only if there are findings)
    findings_section = ""
    if findings_html:
        findings_section = f"""
        <section>
            <h2>Key Findings</h2>
            {findings_html}
        </section>"""

    # Revenue section (only if MRR time-series available)
    revenue_section = ""
    if revenue_html:
        revenue_section = f"""
        <section>
            <h2>Revenue Overview</h2>
            {revenue_html}
        </section>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Financial Model Review: {_esc(company_name)}</title>
    <style>{_css()}</style>
</head>
<body>
    <header>
        <h1>Financial Model Review: {_esc(company_name)}</h1>
        <p>Generated by <a href="https://github.com/lool-ventures/founder-skills">founder skills</a>
        by <a href="https://lool.vc">lool ventures</a> — Financial Model Review Agent</p>
    </header>
    <main>
        <section>
            <h2>Executive Summary</h2>
            {summary_html}
        </section>{findings_section}
        <section>
            <h2>Checklist</h2>
            {checklist_html}
        </section>
        <section>
            <h2>Unit Economics Dashboard</h2>
            {unit_econ_html}
        </section>
        <section>
            <h2>Runway Scenarios</h2>
            {runway_html}
        </section>{revenue_section}
    </main>
    <footer>
        Generated by <a href="https://github.com/lool-ventures/founder-skills">founder skills</a>
        by <a href="https://lool.vc">lool ventures</a> — Financial Model Review Agent
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
    p = argparse.ArgumentParser(description="Generate HTML visualization from financial model review artifacts")
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
