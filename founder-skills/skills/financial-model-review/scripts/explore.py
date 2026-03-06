#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
Generate self-contained interactive HTML explorer for financial model review.

Outputs raw HTML (not JSON). Uses Chart.js for interactive charts and
a client-side projection engine for scenario modelling.

Usage:
    python explore.py --dir ./fmr-testco/
    python explore.py --dir ./fmr-testco/ -o explorer.html
    python explore.py --dir ./fmr-testco/ -o explorer.html --pretty
"""

from __future__ import annotations

import argparse
import html
import json
import os
import sys
from typing import Any, TypeGuard

# ---------------------------------------------------------------------------
# Import benchmark tables from unit_economics.py
# ---------------------------------------------------------------------------

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from unit_economics import CAC_PAYBACK_BY_ACV, STAGE_BENCHMARKS  # noqa: E402, I001

# ---------------------------------------------------------------------------
# Artifact loading infrastructure (duplicated per PEP 723 convention)
# ---------------------------------------------------------------------------

_CORRUPT: dict[str, Any] = {"__corrupt__": True}


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


def _stub_reason(data: dict[str, Any] | None) -> str | None:
    """Return the reason string from a stub artifact, or None."""
    if isinstance(data, dict) and data.get("skipped") is True:
        reason = data.get("reason")
        return str(reason) if reason else None
    return None


def _deep_get(data: dict[str, Any], *keys: str, default: Any = None) -> Any:
    """Safely traverse nested dicts."""
    current: Any = data
    for key in keys:
        if not isinstance(current, dict):
            return default
        current = current.get(key, default)
    return current


# ---------------------------------------------------------------------------
# HTML / safety helpers
# ---------------------------------------------------------------------------


def _esc(text: Any) -> str:
    """Escape text for HTML interpolation."""
    return html.escape(str(text), quote=True)


# ---------------------------------------------------------------------------
# Commentary loading
# ---------------------------------------------------------------------------


def _load_commentary(dir_path: str) -> dict[str, Any] | None:
    """Load commentary.json, validate it has headline field.

    Returns None + stderr warning if missing/malformed.
    """
    raw = _load_artifact(dir_path, "commentary.json")
    if raw is None:
        return None
    if raw is _CORRUPT:
        print("Warning: commentary.json is malformed, skipping", file=sys.stderr)
        return None
    if not isinstance(raw, dict) or "headline" not in raw:
        print("Warning: commentary.json missing headline field, skipping", file=sys.stderr)
        return None
    return raw


# ---------------------------------------------------------------------------
# Data payload builders
# ---------------------------------------------------------------------------


def _build_engine(inputs: dict[str, Any]) -> dict[str, Any]:
    """Extract engine inputs from inputs.json."""
    cash = _deep_get(inputs, "cash", default={})
    revenue = _deep_get(inputs, "revenue", default={})

    current_balance = _deep_get(cash, "current_balance", default=0) or 0
    debt = _deep_get(cash, "debt", default=0) or 0
    cash0 = current_balance - debt

    # revenue0: mrr > arr/12 > monthly_total > 0
    mrr_val = _deep_get(revenue, "mrr", "value", default=None)
    arr_val = _deep_get(revenue, "arr", "value", default=None)
    monthly_total = _deep_get(revenue, "monthly_total", default=None)
    if mrr_val is not None and mrr_val > 0:
        revenue0 = mrr_val
    elif arr_val is not None and arr_val > 0:
        revenue0 = arr_val / 12
    elif monthly_total is not None and monthly_total > 0:
        revenue0 = monthly_total
    else:
        revenue0 = 0

    # mrr is specifically the mrr.value field
    mrr = mrr_val if mrr_val is not None else 0

    # opex0 = revenue0 + monthly_net_burn (RAW signed burn, NOT abs())
    monthly_net_burn = _deep_get(cash, "monthly_net_burn", default=0) or 0
    opex0 = revenue0 + monthly_net_burn

    growth_rate = _deep_get(revenue, "growth_rate_monthly", default=0) or 0
    balance_date = _deep_get(cash, "balance_date", default=None)

    # Grant fields
    israel = _deep_get(inputs, "israel_specific", default={})
    grant_monthly = _deep_get(israel, "grant_monthly", default=0) or 0
    grant_start = _deep_get(israel, "grant_start", default=None)
    grant_end = _deep_get(israel, "grant_end", default=None)

    # ILS expense fraction: 0.5 when fx_rate is set, 0.0 otherwise
    fx_rate = _deep_get(israel, "fx_rate", default=None)
    ils_expense_fraction = 0.5 if fx_rate is not None else 0.0

    return {
        "cash0": cash0,
        "revenue0": revenue0,
        "mrr": mrr,
        "opex0": opex0,
        "growth_rate": growth_rate,
        "balance_date": balance_date,
        "grant_monthly": grant_monthly,
        "grant_start": grant_start,
        "grant_end": grant_end,
        "ils_expense_fraction": ils_expense_fraction,
        "fx_adjustment": 0.0,
        "max_months": 60,
        "growth_decay": 0.97,
    }


def _detect_burn_method(evidence: str | None) -> str:
    """Detect burn multiple method from evidence string."""
    if not evidence:
        return "growth_rate"
    ev = evidence.lower()
    if "ttm" in ev:
        return "ttm"
    if "yoy" in ev or "quarterly" in ev:
        return "quarterly"
    return "growth_rate"


def _build_metrics(inputs: dict[str, Any], ue_data: dict[str, Any]) -> list[dict[str, Any]]:
    """Build metrics array with per-metric formula inputs."""
    revenue = _deep_get(inputs, "revenue", default={})
    cash = _deep_get(inputs, "cash", default={})
    ue_input = _deep_get(inputs, "unit_economics", default={})

    raw_metrics = _deep_get(ue_data, "metrics", default=[])
    if not isinstance(raw_metrics, list):
        raw_metrics = []

    result: list[dict[str, Any]] = []
    for m in raw_metrics:
        if not isinstance(m, dict):
            continue
        name = m.get("name", "")
        metric: dict[str, Any] = {
            "id": name,
            "value": m.get("value"),
            "rating": m.get("rating"),
            "method": None,
            "benchmark": {
                "source": m.get("benchmark_source"),
                "as_of": m.get("benchmark_as_of"),
            },
            "inputs": {},
        }

        # Per-metric input sourcing
        if name == "burn_multiple":
            metric["method"] = _detect_burn_method(m.get("evidence"))
            metric["inputs"] = {
                "burn": _deep_get(cash, "monthly_net_burn", default=0),
                "revenue": _deep_get(revenue, "mrr", "value", default=0),
                "growth_rate": _deep_get(revenue, "growth_rate_monthly", default=0),
            }
        elif name in ("cac", "ltv", "ltv_cac_ratio", "cac_payback"):
            metric["inputs"] = {
                "cac": _deep_get(ue_input, "cac", "total", default=0),
                "arpu": _deep_get(ue_input, "ltv", "inputs", "arpu_monthly", default=0),
                "churn": _deep_get(revenue, "churn_monthly", default=0),
                "gross_margin": _deep_get(ue_input, "gross_margin", default=0),
            }
        elif name == "gross_margin":
            metric["inputs"] = {
                "gross_margin": _deep_get(ue_input, "gross_margin", default=0),
            }
        elif name == "rule_of_40":
            metric["inputs"] = {
                "growth_rate": _deep_get(revenue, "growth_rate_monthly", default=0),
                "burn": _deep_get(cash, "monthly_net_burn", default=0),
                "revenue": _deep_get(revenue, "mrr", "value", default=0),
            }
        else:
            metric["inputs"] = {}

        result.append(metric)

    return result


def _build_data_payload(
    inputs: dict[str, Any],
    runway: dict[str, Any] | None,
    ue: dict[str, Any] | None,
    checklist: dict[str, Any] | None,
    commentary: dict[str, Any] | None,
    *,
    stub_reasons: dict[str, str | None],
) -> dict[str, Any]:
    """Assemble the full DATA payload for the HTML explorer."""
    company_raw = _deep_get(inputs, "company", default={})
    stage = company_raw.get("stage", "seed")

    # Company
    company = {
        "name": company_raw.get("company_name", "Unknown"),
        "slug": company_raw.get("slug", "unknown"),
        "stage": stage,
        "sector": company_raw.get("sector", ""),
        "geography": company_raw.get("geography", ""),
        "model_type": company_raw.get("revenue_model_type", ""),
        "traits": company_raw.get("traits", []),
    }

    # Engine
    engine = _build_engine(inputs)

    # Scenarios from runway
    scenarios: list[dict[str, Any]] = []
    if _usable(runway):
        for s in _deep_get(runway, "scenarios", default=[]):
            if isinstance(s, dict):
                scenarios.append(s)

    # Metrics from unit economics
    metrics: list[dict[str, Any]] = []
    if _usable(ue):
        metrics = _build_metrics(inputs, ue)

    # Benchmarks
    stage_bench = STAGE_BENCHMARKS.get(stage, STAGE_BENCHMARKS.get("seed", {}))
    benchmarks: dict[str, Any] = dict(stage_bench)
    benchmarks["cac_payback_by_acv"] = dict(CAC_PAYBACK_BY_ACV)

    # Bridge
    bridge: dict[str, Any] = {
        "raise_amount": _deep_get(inputs, "cash", "fundraising", "target_raise", default=None),
        "runway_target": _deep_get(inputs, "bridge", "runway_target_months", default=None),
        "milestones": _deep_get(inputs, "bridge", "milestones", default=None),
    }

    # Checklist summary
    checklist_summary: dict[str, Any] | None = None
    if _usable(checklist):
        summary = _deep_get(checklist, "summary", default={})
        checklist_summary = {
            "score_pct": summary.get("score_pct"),
            "overall": summary.get("overall_status"),
            "fails": summary.get("failed_items", []),
            "warns": summary.get("warned_items", []),
        }

    return {
        "company": company,
        "engine": engine,
        "scenarios": scenarios,
        "metrics": metrics,
        "benchmarks": benchmarks,
        "bridge": bridge,
        "checklist": checklist_summary,
        "commentary": commentary,
        "_stub_reasons": stub_reasons,
    }


# ---------------------------------------------------------------------------
# Lens enablement
# ---------------------------------------------------------------------------

_LENSES = ["runway", "raise_planner", "unit_economics", "stress_test"]
_LENS_LABELS = {
    "runway": "Runway",
    "raise_planner": "Raise Plan",
    "unit_economics": "Unit Econ",
    "stress_test": "Stress Test",
}


def _compute_lens_status(data: dict[str, Any]) -> dict[str, bool]:
    """Determine which lenses are enabled."""
    has_runway = len(data.get("scenarios", [])) > 0
    has_ue = len(data.get("metrics", [])) > 0
    return {
        "runway": has_runway,
        "raise_planner": has_runway,
        "unit_economics": has_ue,
        "stress_test": has_runway,
    }


# ---------------------------------------------------------------------------
# HTML generation
# ---------------------------------------------------------------------------


def _generate_html(data: dict[str, Any]) -> str:
    """Generate the full HTML string from the data payload."""
    lens_status = _compute_lens_status(data)
    stub_reasons = data.get("_stub_reasons", {})

    # Remove internal field before embedding
    data_for_embed = {k: v for k, v in data.items() if not k.startswith("_")}
    data_json = json.dumps(data_for_embed, indent=2, default=str)

    company_name = _esc(data.get("company", {}).get("name", ""))
    stage = _esc(data.get("company", {}).get("stage", ""))
    sector = _esc(data.get("company", {}).get("sector", ""))
    headline = ""
    if data.get("commentary") and data["commentary"].get("headline"):
        headline = _esc(data["commentary"]["headline"])

    # Build tab bar
    tabs_html = ""
    for lens in _LENSES:
        label = _LENS_LABELS[lens]
        enabled = lens_status[lens]
        reason = stub_reasons.get(lens, "")
        if enabled:
            tabs_html += (
                f'  <button class="tab active-eligible"'
                f' data-lens="{lens}"'
                f" onclick=\"switchLens('{lens}')\">"
                f"{label}</button>\n"
            )
        else:
            ttl = f' title="{_esc(reason)}"' if reason else ""
            tabs_html += f'  <button class="tab disabled"{ttl} disabled>{label}</button>\n'

    # Build disabled lens reasons for content area
    disabled_reasons_html = ""
    for lens in _LENSES:
        if not lens_status[lens]:
            reason = stub_reasons.get(lens, "Data not available")
            lbl = _LENS_LABELS[lens]
            disabled_reasons_html += (
                f'<div class="stub-reason" data-lens="{lens}"><strong>{lbl}</strong>: {_esc(reason)}</div>\n'
            )

    enabled_count = sum(1 for v in lens_status.values() if v)
    disabled_names = [lens for lens in _LENSES if not lens_status[lens]]

    return _build_html_string(
        data_json=data_json,
        company_name=company_name,
        stage=stage,
        sector=sector,
        headline=headline,
        tabs_html=tabs_html,
        disabled_reasons_html=disabled_reasons_html,
        enabled_count=enabled_count,
        disabled_names=disabled_names,
    )


def _build_html_string(
    *,
    data_json: str,
    company_name: str,
    stage: str,
    sector: str,
    headline: str,
    tabs_html: str,
    disabled_reasons_html: str,
    enabled_count: int,
    disabled_names: list[str],
) -> str:
    """Build the full HTML document string."""
    # CSS built as list to keep lines under 120 chars
    css_lines = [
        "* { margin: 0; padding: 0; box-sizing: border-box; }",
        "body {",
        "  font-family: -apple-system, BlinkMacSystemFont,",
        "    'Segoe UI', Roboto, sans-serif;",
        "  background: #f5f5f7; color: #1d1d1f; padding: 1rem;",
        "}",
        ".header {",
        "  background: #fff; border-radius: 12px;",
        "  padding: 1.5rem; margin-bottom: 1rem;",
        "  box-shadow: 0 1px 3px rgba(0,0,0,0.1);",
        "}",
        ".header h1 { font-size: 1.5rem; margin-bottom: 0.25rem; }",
        ".header .meta { color: #86868b; font-size: 0.875rem; }",
        ".header .headline {",
        "  margin-top: 0.75rem; color: #1d1d1f;",
        "  font-size: 1rem; line-height: 1.5;",
        "}",
        ".tab-bar {",
        "  display: flex; gap: 0.5rem;",
        "  margin-bottom: 1rem; flex-wrap: wrap;",
        "}",
        ".tab {",
        "  padding: 0.5rem 1rem; border: 1px solid #d2d2d7;",
        "  border-radius: 8px; background: #fff;",
        "  cursor: pointer; font-size: 0.875rem;",
        "  transition: all 0.2s;",
        "}",
        ".tab:hover:not(.disabled) { background: #e8e8ed; }",
        ".tab.active {",
        "  background: #0071e3; color: #fff; border-color: #0071e3;",
        "}",
        ".tab.disabled {",
        "  opacity: 0.4; cursor: not-allowed; background: #f5f5f7;",
        "}",
        ".content {",
        "  background: #fff; border-radius: 12px;",
        "  padding: 1.5rem; min-height: 400px;",
        "  box-shadow: 0 1px 3px rgba(0,0,0,0.1);",
        "}",
        ".lens-panel { display: none; }",
        ".lens-panel.active { display: block; }",
        ".slider-group { margin: 1rem 0; }",
        ".slider-group label {",
        "  display: block; font-weight: 600; margin-bottom: 0.25rem;",
        "}",
        '.slider-group input[type="range"] { width: 100%; }',
        ".slider-value { font-size: 0.875rem; color: #86868b; }",
        ".badge {",
        "  display: inline-block; padding: 0.125rem 0.5rem;",
        "  border-radius: 4px; font-size: 0.75rem; font-weight: 600;",
        "}",
        ".badge.strong { background: #d1fae5; color: #065f46; }",
        ".badge.acceptable { background: #fef3c7; color: #92400e; }",
        ".badge.warning { background: #fed7aa; color: #9a3412; }",
        ".badge.fail { background: #fecaca; color: #991b1b; }",
        ".chart-container {",
        "  position: relative; height: 300px; margin: 1rem 0;",
        "}",
        ".commentary-box {",
        "  background: #f0f4ff; border-left: 4px solid #0071e3;",
        "  padding: 1rem; border-radius: 0 8px 8px 0; margin: 1rem 0;",
        "}",
        ".stub-reason {",
        "  background: #fef3c7; border-left: 4px solid #f59e0b;",
        "  padding: 0.75rem; border-radius: 0 8px 8px 0;",
        "  margin: 0.5rem 0; font-size: 0.875rem;",
        "}",
        ".reset-btn {",
        "  padding: 0.5rem 1rem; border: 1px solid #d2d2d7;",
        "  border-radius: 8px; background: #fff;",
        "  cursor: pointer; font-size: 0.875rem;",
        "}",
        ".reset-btn:hover { background: #e8e8ed; }",
    ]
    css = "\n".join(css_lines)

    hl_div = "<div class='headline'>" + headline + "</div>" if headline else ""

    # Lens panels — each on multiple lines for readability
    panels = []
    panel_defs = [
        ("runway", "Runway Projection", "chart-runway"),
        ("raise_planner", "Raise Planner", "chart-raise"),
        ("unit_economics", "Unit Economics", "chart-ue"),
        ("stress_test", "Stress Test", "chart-stress"),
    ]
    for pid, title, cid in panel_defs:
        panels.append(
            f'  <div class="lens-panel" id="lens-{pid}">'
            f"<h2>{title}</h2>"
            f'<div class="chart-container">'
            f'<canvas id="{cid}"></canvas>'
            f"</div></div>"
        )
    panels_html = "\n".join(panels)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>FMR Explorer — {company_name}</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4"></script>
<style>
{css}
</style>
</head>
<body>

<div class="header">
  <h1>{company_name}</h1>
  <div class="meta">{stage} &middot; {sector}</div>
  {hl_div}
</div>

<div class="tab-bar">
{tabs_html}  <button class="reset-btn" onclick="resetAll()">Reset</button>
</div>

<div class="content">
{disabled_reasons_html}
{panels_html}
</div>

<script>
const DATA = {data_json};

// ---------------------------------------------------------------------------
// Projection Engine (port of runway.py _project_scenario)
// ---------------------------------------------------------------------------

function projectScenario(params) {{
  var defaults = {{
    burnChange: 0, fxAdjustment: 0, grantMonthly: 0,
    grantStart: 1, grantEnd: 0, ilsFraction: 0,
    maxMonths: DATA.engine.max_months,
    growthDecay: DATA.engine.growth_decay
  }};
  var p = Object.assign({{}}, defaults, params);
  var cash0 = p.cash0, revenue0 = p.revenue0, opex0 = p.opex0;
  var growthRate = p.growthRate, burnChange = p.burnChange;
  var fxAdjustment = p.fxAdjustment, grantMonthly = p.grantMonthly;
  var grantStart = p.grantStart, grantEnd = p.grantEnd;
  var ilsFraction = p.ilsFraction;
  var maxMonths = p.maxMonths, growthDecay = p.growthDecay;

  var projections = [];
  var cash = cash0;
  var revenue = revenue0;
  var opex = opex0 * (1 + burnChange);
  var cashOutMonth = null;
  var defaultAlive = false;

  for (var t = 1; t <= maxMonths; t++) {{
    var effGrowth = growthRate * Math.pow(growthDecay, t - 1);
    revenue = revenue * (1 + effGrowth);

    var effOpex = opex;
    if (ilsFraction > 0 && fxAdjustment !== 0) {{
      effOpex = opex * (1 - ilsFraction) + opex * ilsFraction * (1 + fxAdjustment);
    }}

    var netBurn = effOpex - revenue;
    var grant = 0;
    if (grantMonthly > 0 && t >= grantStart && t <= grantEnd) {{
      grant = grantMonthly;
    }}

    cash = cash - netBurn + grant;
    projections.push({{
      month: t, cash_balance: cash, revenue: revenue,
      expenses: effOpex, net_burn: netBurn
    }});

    if (netBurn <= 0 && !defaultAlive) defaultAlive = true;
    if (cash <= 0 && cashOutMonth === null) {{
      cashOutMonth = t;
      break;
    }}
  }}
  if (cashOutMonth === null) defaultAlive = true;

  return {{
    runway_months: cashOutMonth,
    default_alive: defaultAlive,
    projections: projections,
    cash_out_month: cashOutMonth
  }};
}}

function findMinViableGrowth(params) {{
  var base = Object.assign({{}}, params);
  var lo = 0;
  var hi = Math.max(base.growthRate || 0, 0.01);
  var maxHi = 0.50;
  var precision = 0.001;

  while (hi < maxHi) {{
    var r = projectScenario(
      Object.assign({{}}, base, {{growthRate: hi, burnChange: 0}})
    );
    if (r.default_alive || (r.runway_months !== null && r.runway_months >= 18)) break;
    hi = Math.min(hi * 2, maxHi);
  }}

  for (var i = 0; i < 50; i++) {{
    var mid = (lo + hi) / 2;
    var r2 = projectScenario(
      Object.assign({{}}, base, {{growthRate: mid, burnChange: 0}})
    );
    if (r2.default_alive) {{ hi = mid; }} else {{ lo = mid; }}
    if (hi - lo < precision) break;
  }}
  return Math.round(hi * 1000) / 1000;
}}

// ---------------------------------------------------------------------------
// Number formatting
// ---------------------------------------------------------------------------

function fmtCurrency(v) {{
  if (v === null || v === undefined || isNaN(v)) return 'N/A';
  var neg = v < 0 ? '-' : '';
  var abs = Math.abs(v);
  if (abs >= 1e6) return neg + '$' + (abs / 1e6).toFixed(1) + 'M';
  if (abs >= 1e3) return neg + '$' + (abs / 1e3).toFixed(0) + 'K';
  return neg + '$' + Math.round(abs);
}}

function fmtPct(v, decimals) {{
  if (v === null || v === undefined || isNaN(v)) return 'N/A';
  return (v * 100).toFixed(decimals !== undefined ? decimals : 1) + '%';
}}

function fmtRatio(v) {{
  if (v === null || v === undefined || isNaN(v) || !isFinite(v)) return 'N/A';
  return v.toFixed(1) + 'x';
}}

function fmtMonths(v) {{
  if (v === null || v === undefined) return 'N/A';
  return Math.round(v) + ' months';
}}

// ---------------------------------------------------------------------------
// Unit economics formulas (Lens 3)
// ---------------------------------------------------------------------------

function calcBurnMultiple(inputs) {{
  var mrr = inputs.mrr, growth_rate = inputs.growth_rate;
  var monthly_burn = inputs.monthly_burn;
  if (!growth_rate || !mrr || monthly_burn <= 0) return null;
  var burn = Math.max(0, monthly_burn);
  return burn / (mrr * growth_rate);
}}

function calcLTV(inputs) {{
  var arpu = inputs.arpu, gross_margin = inputs.gross_margin;
  var churn = inputs.churn;
  if (!arpu || gross_margin === null || gross_margin === undefined) return null;
  if (churn > 0) return (arpu * gross_margin) / churn;
  return arpu * gross_margin * 60;
}}

function calcLTVCAC(inputs) {{
  var ltv = calcLTV(inputs);
  if (ltv === null || !inputs.cac || inputs.cac === 0) return null;
  return ltv / inputs.cac;
}}

function calcCACPayback(inputs) {{
  var arpu = inputs.arpu, gross_margin = inputs.gross_margin;
  var cac = inputs.cac;
  if (!arpu || !gross_margin || gross_margin === 0 || !cac) return null;
  return cac / (arpu * gross_margin);
}}

function calcR40(inputs) {{
  var mrr = inputs.mrr, growth_rate = inputs.growth_rate;
  var monthly_burn = inputs.monthly_burn, gross_margin = inputs.gross_margin;
  if (!growth_rate) return null;
  var annualGrowth = (Math.pow(1 + growth_rate, 12) - 1) * 100;
  var margin = null;
  if (mrr && mrr > 0 && monthly_burn !== null && monthly_burn !== undefined) {{
    var opMargin = -monthly_burn / mrr;
    if (opMargin <= 1.0) {{
      margin = opMargin;
    }} else if (gross_margin !== null && gross_margin !== undefined) {{
      margin = gross_margin;
    }}
  }} else if (gross_margin !== null && gross_margin !== undefined) {{
    margin = gross_margin;
  }}
  if (margin === null) return null;
  return annualGrowth + margin * 100;
}}

function safeMetric(val, benchTarget) {{
  if (val === null || val === undefined || !isFinite(val) || isNaN(val)) return null;
  if (benchTarget && Math.abs(val) > Math.abs(benchTarget) * 1000) return null;
  return val;
}}

var METRIC_FORMULAS = {{
  burn_multiple: calcBurnMultiple,
  ltv: calcLTV,
  ltv_cac_ratio: calcLTVCAC,
  cac_payback: calcCACPayback,
  rule_of_40: calcR40
}};

// ---------------------------------------------------------------------------
// Rating logic
// ---------------------------------------------------------------------------

function rateMetric(id, value, benchmarks) {{
  if (value === null) return 'not_rated';
  var b = benchmarks[id];
  if (!b) return 'not_rated';
  var lowerBetter = ['burn_multiple', 'cac_payback', 'cac'];
  if (lowerBetter.indexOf(id) >= 0) {{
    if (value <= b.strong) return 'strong';
    if (value <= b.acceptable) return 'acceptable';
    if (value <= b.warning) return 'warning';
    return 'fail';
  }}
  if (value >= b.strong) return 'strong';
  if (value >= b.acceptable) return 'acceptable';
  if (value >= b.warning) return 'warning';
  return 'fail';
}}

function ratingIcon(r) {{
  if (r === 'strong') return '\u2713';
  if (r === 'warning' || r === 'acceptable') return '\u26a0';
  if (r === 'fail') return '\u2717';
  return '';
}}

// ---------------------------------------------------------------------------
// UI controls (stubs — Tasks 6-7 will implement)
// ---------------------------------------------------------------------------

function switchLens(name) {{
  document.querySelectorAll('.lens-panel').forEach(function(el) {{
    el.classList.remove('active');
  }});
  var panel = document.getElementById('lens-' + name);
  if (panel) panel.classList.add('active');
  document.querySelectorAll('.tab.active').forEach(function(el) {{
    el.classList.remove('active');
  }});
  document.querySelectorAll('.tab[data-lens="' + name + '"]').forEach(function(el) {{
    el.classList.add('active');
  }});
}}

function resetAll() {{
  // Reset all sliders and UI state to defaults
}}

// Auto-activate first enabled lens
(function() {{
  var lenses = {json.dumps(_LENSES)};
  var status = {json.dumps({})};
  for (var i = 0; i < lenses.length; i++) {{
    var tab = document.querySelector('.tab[data-lens="' + lenses[i] + '"]:not(.disabled)');
    if (tab) {{
      switchLens(lenses[i]);
      break;
    }}
  }}
}})();
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------


def _write_output(data_str: str, output_path: str | None, *, summary: dict[str, Any] | None = None) -> None:
    """Write HTML string to file or stdout."""
    if output_path:
        abs_path = os.path.abspath(output_path)
        parent = os.path.dirname(abs_path)
        if parent == "/":
            print(f"Error: output path resolves to root directory: {output_path}", file=sys.stderr)
            sys.exit(1)
        os.makedirs(parent, exist_ok=True)
        with open(abs_path, "w", encoding="utf-8") as f:
            f.write(data_str)
        receipt: dict[str, Any] = {"ok": True, "path": abs_path, "bytes": len(data_str.encode("utf-8"))}
        if summary:
            receipt.update(summary)
        sys.stdout.write(json.dumps(receipt, separators=(",", ":")) + "\n")
    else:
        sys.stdout.write(data_str)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="FMR Interactive Explorer")
    parser.add_argument("--dir", required=True, help="Directory with FMR artifacts")
    parser.add_argument("-o", "--output", default=None, help="Write HTML to file")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON receipt")
    args = parser.parse_args()

    dir_path = args.dir

    # Load artifacts
    inputs = _load_artifact(dir_path, "inputs.json")
    if not _usable(inputs):
        print("Error: inputs.json is required but missing or corrupt", file=sys.stderr)
        sys.exit(1)

    assert inputs is not None  # for type checker

    runway = _load_artifact(dir_path, "runway.json")
    ue = _load_artifact(dir_path, "unit_economics.json")
    checklist = _load_artifact(dir_path, "checklist.json")
    commentary = _load_commentary(dir_path)

    # Collect stub reasons for disabled lenses
    stub_reasons: dict[str, str | None] = {}
    runway_reason = _stub_reason(runway)
    ue_reason = _stub_reason(ue)
    if not _usable(runway):
        reason = runway_reason or "runway.json not available"
        stub_reasons["runway"] = reason
        stub_reasons["raise_planner"] = reason
        stub_reasons["stress_test"] = reason
    if not _usable(ue):
        reason = ue_reason or "unit_economics.json not available"
        stub_reasons["unit_economics"] = reason

    # Build data payload
    data = _build_data_payload(
        inputs,
        runway if _usable(runway) else None,
        ue if _usable(ue) else None,
        checklist if _usable(checklist) else None,
        commentary,
        stub_reasons=stub_reasons,
    )

    # Generate HTML
    html_str = _generate_html(data)

    # Compute lens status for receipt
    lens_status = _compute_lens_status(data)
    enabled_count = sum(1 for v in lens_status.values() if v)
    disabled_names = [lens for lens in _LENSES if not lens_status[lens]]

    _write_output(
        html_str,
        args.output,
        summary={"lenses_enabled": enabled_count, "lenses_disabled": disabled_names},
    )


if __name__ == "__main__":
    main()
