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

    _raw_growth = _deep_get(revenue, "growth_rate_monthly", default=None)
    growth_rate_missing = _raw_growth is None
    growth_rate = _raw_growth or 0
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
        "growth_rate_missing": growth_rate_missing,
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
                "monthly_burn": _deep_get(cash, "monthly_net_burn", default=0),
                "mrr": _deep_get(revenue, "mrr", "value", default=0),
                "growth_rate": _deep_get(revenue, "growth_rate_monthly", default=0),
            }
        elif name in ("cac", "ltv", "ltv_cac_ratio", "cac_payback"):
            # ARPU: ltv.inputs.arpu_monthly > ltv.inputs.arpu > mrr/customers
            arpu = _deep_get(ue_input, "ltv", "inputs", "arpu_monthly") or _deep_get(
                ue_input, "ltv", "inputs", "arpu", default=0
            )
            if not arpu:
                mrr_val = _deep_get(revenue, "mrr", "value", default=0) or 0
                customers = _deep_get(revenue, "customers", default=0) or 0
                arpu = round(mrr_val / customers, 2) if customers > 0 else 0
            # Churn: revenue.churn_monthly > revenue.churn
            churn = _deep_get(revenue, "churn_monthly") or _deep_get(revenue, "churn", default=0)
            metric["inputs"] = {
                "cac": _deep_get(ue_input, "cac", "total", default=0),
                "arpu": arpu,
                "churn": churn or 0,
                "gross_margin": _deep_get(ue_input, "gross_margin", default=0),
            }
        elif name == "gross_margin":
            metric["inputs"] = {
                "gross_margin": _deep_get(ue_input, "gross_margin", default=0),
            }
        elif name == "rule_of_40":
            metric["inputs"] = {
                "growth_rate": _deep_get(revenue, "growth_rate_monthly", default=0),
                "monthly_burn": _deep_get(cash, "monthly_net_burn", default=0),
                "mrr": _deep_get(revenue, "mrr", "value", default=0),
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
        ".metrics-strip {",
        "  display: flex; align-items: center; gap: 0.5rem;",
        "  flex-wrap: wrap; margin: 0.75rem 0;",
        "}",
        ".metrics-table th, .metrics-table td {",
        "  text-align: left; padding: 0.5rem 0.75rem;",
        "  border-bottom: 1px solid #e8e8ed;",
        "}",
        ".metrics-table th { font-weight: 600; color: #86868b; }",
        ".scenario-table th, .scenario-table td {",
        "  text-align: left; padding: 0.5rem 0.75rem;",
        "  border-bottom: 1px solid #e8e8ed;",
        "}",
        ".scenario-table th { font-weight: 600; color: #86868b; }",
        ".clickable:hover { background: #f5f5f7; }",
        ".clickable.active { background: #e8f0fe; }",
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

function findMinViableGrowth(params, targetRunway) {{
  targetRunway = targetRunway || 18;
  var base = Object.assign({{}}, params);
  var lo = 0;
  var hi = Math.max(base.growthRate || 0, 0.01);
  var maxHi = 0.50;
  var precision = 0.001;

  while (hi < maxHi) {{
    var r = projectScenario(
      Object.assign({{}}, base, {{growthRate: hi, burnChange: 0}})
    );
    if (r.default_alive || (r.runway_months !== null && r.runway_months >= targetRunway)) break;
    hi = Math.min(hi * 2, maxHi);
  }}

  for (var i = 0; i < 50; i++) {{
    var mid = (lo + hi) / 2;
    var r2 = projectScenario(
      Object.assign({{}}, base, {{growthRate: mid, burnChange: 0}})
    );
    if (r2.default_alive || (r2.runway_months !== null && r2.runway_months >= targetRunway)) {{  // noqa: E501
      hi = mid;
    }} else {{ lo = mid; }}
    if (hi - lo < precision) break;
  }}
  // Check if even maxHi isn't viable
  var check = projectScenario(
    Object.assign({{}}, base, {{growthRate: hi, burnChange: 0}})
  );
  if (!check.default_alive && (check.runway_months === null || check.runway_months < targetRunway)) {{
    return null;
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
  rule_of_40: calcR40,
  gross_margin: function(s) {{ return s.gross_margin; }}
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
// UI State
// ---------------------------------------------------------------------------

var state = {{
  growthRate: DATA.engine.growth_rate,
  opex0: DATA.engine.opex0,
  cash0: DATA.engine.cash0,
  fxAdjustment: DATA.engine.fx_adjustment,
  grantMonthly: DATA.engine.grant_monthly,
  grantStart: DATA.engine.grant_start || 1,
  grantEnd: DATA.engine.grant_end || 0,
  ilsFraction: DATA.engine.ils_expense_fraction,
  targetRunway: (DATA.bridge && DATA.bridge.runway_target) || 24,
  burnChange: 0,
  stressGrowth: DATA.engine.growth_rate
}};

var charts = {{}};
var currentLens = null;

// ---------------------------------------------------------------------------
// Tab switching
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
  currentLens = name;
  if (name === 'runway') renderRunway();
  else if (name === 'raise_planner') renderRaisePlanner();
  else if (name === 'unit_economics') renderUnitEconomics();
  else if (name === 'stress_test') renderStressTest();
}}

function resetAll() {{
  state.growthRate = DATA.engine.growth_rate;
  state.opex0 = DATA.engine.opex0;
  state.cash0 = DATA.engine.cash0;
  state.fxAdjustment = DATA.engine.fx_adjustment;
  state.grantMonthly = DATA.engine.grant_monthly;
  state.grantStart = DATA.engine.grant_start || 1;
  state.grantEnd = DATA.engine.grant_end || 0;
  state.burnChange = 0;
  state.targetRunway = (DATA.bridge && DATA.bridge.runway_target) || 24;
  state.stressGrowth = DATA.engine.growth_rate;
  state.advRunwayOpen = false;
  state.advRaiseOpen = false;
  if (currentLens) switchLens(currentLens);
}}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function getProjectionParams() {{
  return {{
    cash0: state.cash0,
    revenue0: DATA.engine.revenue0,
    opex0: state.opex0,
    growthRate: state.growthRate,
    burnChange: state.burnChange,
    fxAdjustment: state.fxAdjustment,
    grantMonthly: state.grantMonthly,
    grantStart: state.grantStart,
    grantEnd: state.grantEnd,
    ilsFraction: state.ilsFraction
  }};
}}

function getStressParams() {{
  return {{
    cash0: DATA.engine.cash0,
    revenue0: DATA.engine.revenue0,
    opex0: DATA.engine.opex0,
    growthRate: state.stressGrowth,
    burnChange: 0,
    fxAdjustment: DATA.engine.fx_adjustment,
    grantMonthly: DATA.engine.grant_monthly,
    grantStart: DATA.engine.grant_start,
    grantEnd: DATA.engine.grant_end,
    ilsFraction: DATA.engine.ils_expense_fraction
  }};
}}

function makeSlider(opts) {{
  var id = opts.id, label = opts.label, min = opts.min, max = opts.max;
  var step = opts.step, value = opts.value, fmt = opts.fmt || String;
  var onChange = opts.onChange;
  var div = document.createElement('div');
  div.className = 'slider-group';
  var lbl = document.createElement('label');
  lbl.setAttribute('for', id);
  lbl.textContent = label + ': ';
  var valSpan = document.createElement('span');
  valSpan.className = 'slider-value';
  valSpan.id = 'val-' + id;
  valSpan.textContent = fmt(value);
  lbl.appendChild(valSpan);
  div.appendChild(lbl);
  var input = document.createElement('input');
  input.type = 'range';
  input.id = id;
  input.min = String(min);
  input.max = String(max);
  input.step = String(step);
  input.value = String(value);
  input.setAttribute('aria-label', label);
  div.appendChild(input);
  input.addEventListener('input', function() {{
    var v = parseFloat(this.value);
    valSpan.textContent = fmt(v);
    if (onChange) onChange(v);
  }});
  return div;
}}

function commentaryBox(lensKey) {{
  if (!DATA.commentary || !DATA.commentary.lenses) return '';
  var c = DATA.commentary.lenses[lensKey];
  if (!c) return '';
  var parts = [];
  if (c.callout) parts.push('<div class="commentary-box">' + c.callout + '</div>');
  if (c.highlight) parts.push('<div class="commentary-box"'
    + ' style="border-color:#86868b;background:#f9f9fb">' + c.highlight + '</div>');
  if (c.watch_out) parts.push('<div class="commentary-box"'
    + ' style="border-color:#f59e0b;background:#fffbeb">' + c.watch_out + '</div>');
  return parts.join('');
}}

// ---------------------------------------------------------------------------
// Safe DOM helpers — build content via DOM API, not innerHTML
// ---------------------------------------------------------------------------

function setContent(el, htmlStr) {{
  // Uses createContextualFragment for safe insertion of
  // internally-constructed markup (no external/user input).
  while (el.firstChild) el.removeChild(el.firstChild);
  var range = document.createRange();
  range.selectNode(document.body);
  el.appendChild(range.createContextualFragment(htmlStr));
}}

// ---------------------------------------------------------------------------
// Lens 1: Runway & Default-Alive
// ---------------------------------------------------------------------------

function renderRunway() {{
  var panel = document.getElementById('lens-runway');
  if (!panel) return;

  var p = getProjectionParams();
  var result = projectScenario(p);
  var mvg = findMinViableGrowth(p, state.targetRunway);

  var alive = result.default_alive;
  var months = result.runway_months || DATA.engine.max_months + '+';
  var badge = alive
    ? '<span class="badge strong">SELF-SUSTAINING</span>'
    : '<span class="badge fail">NEEDS FUNDING</span>';

  var burn = state.opex0 - DATA.engine.revenue0;
  var burnLabel = burn >= 0 ? 'Monthly burn' : 'Monthly expenses';
  var burnAbs = Math.abs(burn);
  var burnMax = Math.max(DATA.engine.opex0, DATA.engine.revenue0) * 3;
  var burnStep = Math.max(1000, Math.round(burnAbs / 20 / 1000) * 1000) || 5000;

  var markup = '<h2>Runway &amp; Default-Alive</h2>';
  var mvgSpan = mvg !== null
    ? ' <span style="margin-left:12px">Min viable growth: <strong>' + fmtPct(mvg, 1) + ' MoM</strong></span>'
    : '';
  markup += '<div class="metrics-strip">' + badge +
    ' <span style="margin-left:12px">Runway: <strong>' + months + ' months</strong></span>' +
    mvgSpan + '</div>';
  if (DATA.engine.growth_rate_missing) {{
    markup += '<div style="background:#fef3c7;color:#92400e;padding:8px 12px;'
      + 'border-radius:6px;font-size:0.85rem;margin:8px 0">'
      + 'Growth rate not provided \u2014 adjust the slider to explore scenarios.</div>';
  }}
  markup += commentaryBox('runway');
  markup += '<div class="chart-container"><canvas id="chart-runway"></canvas></div>';
  markup += '<div id="sliders-runway"></div>';
  setContent(panel, markup);

  // Sliders
  var sliderDiv = document.getElementById('sliders-runway');
  sliderDiv.appendChild(makeSlider({{
    id: 'growth', label: 'Growth rate', min: 0, max: 0.30, step: 0.005,
    value: state.growthRate, fmt: function(v) {{ return fmtPct(v, 1); }},
    onChange: function(v) {{ state.growthRate = v; renderRunway(); }}
  }}));
  sliderDiv.appendChild(makeSlider({{
    id: 'opex', label: burnLabel, min: 0, max: burnMax, step: burnStep,
    value: state.opex0, fmt: fmtCurrency,
    onChange: function(v) {{ state.opex0 = v; renderRunway(); }}
  }}));

  // Advanced toggle
  var advBtn = document.createElement('button');
  advBtn.className = 'tab';
  advBtn.style.cssText = 'font-size:0.8rem;padding:4px 8px;margin-top:8px';
  advBtn.textContent = 'Advanced...';
  var advPanel = document.createElement('div');
  advPanel.style.display = state.advRunwayOpen ? 'block' : 'none';
  advBtn.onclick = function() {{
    state.advRunwayOpen = !state.advRunwayOpen;
    advPanel.style.display = state.advRunwayOpen ? 'block' : 'none';
  }};
  sliderDiv.appendChild(advBtn);

  advPanel.appendChild(makeSlider({{
    id: 'cash0', label: 'Starting cash', min: 0,
    max: DATA.engine.cash0 * 3 || 1000000, step: Math.max(10000, Math.round(DATA.engine.cash0 / 20)),
    value: state.cash0, fmt: fmtCurrency,
    onChange: function(v) {{ state.cash0 = v; renderRunway(); }}
  }}));

  if (state.ilsFraction > 0) {{
    advPanel.appendChild(makeSlider({{
      id: 'fx', label: 'FX adjustment', min: -0.15, max: 0.15, step: 0.01,
      value: state.fxAdjustment, fmt: function(v) {{ return fmtPct(v, 0); }},
      onChange: function(v) {{ state.fxAdjustment = v; renderRunway(); }}
    }}));
  }}

  if (DATA.engine.grant_monthly > 0) {{
    advPanel.appendChild(makeSlider({{
      id: 'grant', label: 'IIA grant/month', min: 0,
      max: DATA.engine.grant_monthly * 5, step: Math.max(10000, Math.round(DATA.engine.grant_monthly / 10)),
      value: state.grantMonthly, fmt: fmtCurrency,
      onChange: function(v) {{ state.grantMonthly = v; renderRunway(); }}
    }}));
  }}

  sliderDiv.appendChild(advPanel);

  // Chart
  renderRunwayChart(result);
}}

function renderRunwayChart(result) {{
  var ctx = document.getElementById('chart-runway');
  if (!ctx) return;
  if (charts.runway) charts.runway.destroy();

  var labels = result.projections.map(function(p) {{ return 'M' + p.month; }});
  var cashData = result.projections.map(function(p) {{ return Math.round(p.cash_balance); }});
  var revData = result.projections.map(function(p) {{ return Math.round(p.revenue); }});

  charts.runway = new Chart(ctx, {{
    type: 'line',
    data: {{
      labels: labels,
      datasets: [
        {{
          label: 'Cash Balance',
          data: cashData,
          borderColor: '#0071e3',
          backgroundColor: 'rgba(0,113,227,0.1)',
          fill: true,
          tension: 0.2
        }},
        {{
          label: 'Revenue',
          data: revData,
          borderColor: '#34c759',
          borderDash: [5, 5],
          fill: false,
          tension: 0.2
        }}
      ]
    }},
    options: {{
      responsive: true,
      maintainAspectRatio: false,
      plugins: {{
        legend: {{ position: 'top' }},
        tooltip: {{
          callbacks: {{
            label: function(ctx) {{ return ctx.dataset.label + ': ' + fmtCurrency(ctx.raw); }}
          }}
        }}
      }},
      scales: {{
        y: {{
          ticks: {{
            callback: function(v) {{ return fmtCurrency(v); }}
          }}
        }}
      }}
    }}
  }});
}}

// ---------------------------------------------------------------------------
// Lens 2: Raise Planner
// ---------------------------------------------------------------------------

function renderRaisePlanner() {{
  var panel = document.getElementById('lens-raise_planner');
  if (!panel) return;

  var targetRaise = (DATA.bridge && DATA.bridge.raise_amount) || 3000000;
  var maxRaise = Math.max(targetRaise * 2, 6000000);

  var target = state.targetRunway;
  var markup = '<h2>Raise Planner</h2>';
  markup += '<div id="raise-summary" style="background:#f0f7ff;border-left:4px solid #2563eb;'
    + 'padding:12px 16px;border-radius:4px;margin-bottom:16px;">'
    + '<div id="raise-headline" style="font-size:0.95rem;font-weight:600;color:#1e40af;"></div>'
    + '<div id="raise-detail" style="font-size:0.8rem;color:#3b82f6;margin-top:4px;"></div>'
    + '</div>';
  markup += commentaryBox('raise_planner');
  markup += '<div class="chart-container"><canvas id="chart-raise"></canvas></div>';
  markup += '<div id="sliders-raise"></div>';
  setContent(panel, markup);

  var sliderDiv = document.getElementById('sliders-raise');
  sliderDiv.appendChild(makeSlider({{
    id: 'target-runway', label: 'Target runway', min: 12, max: 36, step: 1,
    value: target, fmt: function(v) {{ return v + ' months'; }},
    onChange: function(v) {{ state.targetRunway = v; updateRaisePlannerChart(); }}
  }}));
  sliderDiv.appendChild(makeSlider({{
    id: 'growth-rp', label: 'Growth rate', min: 0, max: 0.30, step: 0.005,
    value: state.growthRate, fmt: function(v) {{ return fmtPct(v, 1); }},
    onChange: function(v) {{ state.growthRate = v; updateRaisePlannerChart(); }}
  }}));

  // Advanced
  var advBtn = document.createElement('button');
  advBtn.className = 'tab';
  advBtn.style.cssText = 'font-size:0.8rem;padding:4px 8px;margin-top:8px';
  advBtn.textContent = 'Advanced...';
  var advPanel = document.createElement('div');
  advPanel.style.display = state.advRaiseOpen ? 'block' : 'none';
  advBtn.onclick = function() {{
    state.advRaiseOpen = !state.advRaiseOpen;
    advPanel.style.display = state.advRaiseOpen ? 'block' : 'none';
  }};
  sliderDiv.appendChild(advBtn);
  advPanel.appendChild(makeSlider({{
    id: 'burn-change', label: 'Burn increase after raise', min: 0, max: 0.50, step: 0.05,
    value: state.burnChange, fmt: function(v) {{ return '+' + fmtPct(v, 0); }},
    onChange: function(v) {{ state.burnChange = v; updateRaisePlannerChart(); }}
  }}));
  sliderDiv.appendChild(advPanel);

  // Build line chart
  var ctx = document.getElementById('chart-raise');
  if (charts.raise) charts.raise.destroy();
  charts.raise = new Chart(ctx, {{
    type: 'line',
    data: {{
      datasets: [
        {{
          label: 'Runway (months)',
          data: [],
          borderColor: '#16a34a',
          backgroundColor: 'rgba(22, 163, 106, 0.08)',
          fill: true,
          tension: 0.3,
          pointRadius: 0,
          pointHoverRadius: 5,
          borderWidth: 2.5
        }},
        {{
          label: 'Target',
          data: [],
          borderColor: '#2563eb',
          borderDash: [6, 3],
          borderWidth: 1.5,
          pointRadius: 0,
          fill: false
        }}
      ]
    }},
    options: {{
      responsive: true,
      maintainAspectRatio: false,
      interaction: {{
        mode: 'index',
        intersect: false
      }},
      plugins: {{
        legend: {{ display: false }},
        tooltip: {{
          callbacks: {{
            title: function(items) {{
              return '$' + (items[0].parsed.x / 1e6).toFixed(1) + 'M raise';
            }},
            label: function(item) {{
              if (item.datasetIndex === 1) return 'Target: ' + item.parsed.y + ' months';
              var v = item.parsed.y;
              return 'Runway: ' + (v >= DATA.engine.max_months ? DATA.engine.max_months + '+' : v) + ' months';
            }}
          }}
        }}
      }},
      scales: {{
        x: {{
          type: 'linear',
          title: {{ display: true, text: 'Raise Amount', font: {{ size: 12, weight: '600' }}, color: '#6b7280' }},
          ticks: {{
            callback: function(v) {{ return '$' + (v / 1e6).toFixed(0) + 'M'; }},
            stepSize: 2000000,
            color: '#9ca3af'
          }},
          grid: {{ color: '#f3f4f6' }},
          min: 0,
          max: maxRaise
        }},
        y: {{
          title: {{ display: true, text: 'Runway (months)', font: {{ size: 12, weight: '600' }}, color: '#6b7280' }},
          ticks: {{ color: '#9ca3af' }},
          grid: {{ color: '#f3f4f6' }},
          min: 0,
          max: 65
        }}
      }}
    }}
  }});

  // Store maxRaise for updates
  charts.raiseMaxAmount = maxRaise;

  // Initial data population
  updateRaisePlannerChart();
}}

function updateRaisePlannerChart() {{
  if (!charts.raise) return;
  var maxRaise = charts.raiseMaxAmount || 6000000;
  var target = state.targetRunway;

  // Compute runway for $0 to maxRaise in $500K steps
  var points = [];
  var targetLine = [];
  var minViable = null;

  for (var amt = 0; amt <= maxRaise; amt += 500000) {{
    var p = getProjectionParams();
    p.cash0 = state.cash0 + amt;
    p.burnChange = state.burnChange;
    var r = projectScenario(p);
    var runway = r.runway_months || DATA.engine.max_months;
    points.push({{ x: amt, y: runway }});
    targetLine.push({{ x: amt, y: target }});

    if (runway >= target && minViable === null && amt > 0) {{
      minViable = amt;
    }}
  }}

  // Pre-raise runway (amt = 0)
  var preRaise = points[0].y;

  // Update dynamic summary
  var headline = document.getElementById('raise-headline');
  var detail = document.getElementById('raise-detail');
  var summaryBox = document.getElementById('raise-summary');

  if (headline && detail && summaryBox) {{
    if (preRaise >= DATA.engine.max_months || (points[0] && projectScenario(getProjectionParams()).default_alive)) {{
      headline.textContent = 'Already self-sustaining at ' + fmtPct(state.growthRate, 1) + ' MoM growth';
      detail.textContent = 'Pre-raise runway exceeds ' + DATA.engine.max_months + ' months. '
        + 'Try lowering the growth rate to see when a raise becomes necessary.';
      summaryBox.style.borderColor = '#16a34a';
      summaryBox.style.background = '#f0fdf4';
    }} else if (minViable !== null) {{
      headline.textContent = 'Minimum viable raise: $'
        + (minViable / 1e6).toFixed(1) + 'M (reaches ' + target + '-month target)';
      detail.textContent = 'Pre-raise runway: ' + preRaise
        + ' months at ' + fmtPct(state.growthRate, 1) + ' MoM growth.';
      summaryBox.style.borderColor = '#2563eb';
      summaryBox.style.background = '#f0f7ff';
    }} else {{
      headline.textContent = 'No raise amount in range reaches ' + target + '-month target';
      detail.textContent = 'Pre-raise runway: ' + preRaise + ' months. Consider reducing burn or increasing growth.';
      summaryBox.style.borderColor = '#dc2626';
      summaryBox.style.background = '#fef2f2';
    }}
  }}

  // Update chart data
  charts.raise.data.datasets[0].data = points;
  charts.raise.data.datasets[1].data = targetLine;

  // Segment coloring: red below target, green above
  charts.raise.data.datasets[0].segment = {{
    borderColor: function(ctx2) {{
      var y = ctx2.p1.parsed.y;
      return y >= target ? '#16a34a' : '#dc2626';
    }}
  }};

  charts.raise.update('none');
}}

// ---------------------------------------------------------------------------
// Lens 3: Unit Economics
// ---------------------------------------------------------------------------

var ueState = {{}};
var metricLabels = {{
  cac: 'CAC', ltv: 'LTV', ltv_cac_ratio: 'LTV/CAC',
  cac_payback: 'CAC Payback', gross_margin: 'Gross Margin',
  burn_multiple: 'Burn Multiple', rule_of_40: 'Rule of 40',
  magic_number: 'Magic Number', nrr: 'NRR', grr: 'GRR',
  arr_per_fte: 'ARR per FTE'
}};
var metricFmt = {{
  cac: fmtCurrency, ltv: fmtCurrency, ltv_cac_ratio: fmtRatio,
  cac_payback: fmtMonths, gross_margin: function(v) {{ return fmtPct(v, 0); }},
  burn_multiple: fmtRatio, rule_of_40: function(v) {{ return v !== null ? v.toFixed(0) : 'N/A'; }},
  magic_number: fmtRatio, nrr: fmtRatio,
  grr: function(v) {{ return fmtPct(v, 0); }}, arr_per_fte: fmtCurrency
}};

function renderUnitEconomics() {{
  var panel = document.getElementById('lens-unit_economics');
  if (!panel) return;

  var markup = '<h2>Unit Economics</h2>';
  markup += commentaryBox('unit_economics');

  // Metrics table
  var explorable = {{}};
  DATA.metrics.forEach(function(m) {{
    explorable[m.id] = !!METRIC_FORMULAS[m.id];
  }});

  markup += '<p style="font-size:0.8rem;color:#86868b;margin-bottom:0.5rem">'
    + 'Click a metric with \u25b6 to explore what-if scenarios</p>';
  markup += '<table class="metrics-table" style="width:100%;border-collapse:collapse;font-size:0.875rem">';
  markup += '<tr><th></th><th>Metric</th><th>Value</th><th>Rating</th><th>Benchmark</th></tr>';

  var worstGap = null, worstMetric = null;

  DATA.metrics.forEach(function(m) {{
    var label = metricLabels[m.id] || m.id;
    var fmt = metricFmt[m.id] || String;
    var val = m.value;
    var rating = m.rating || 'not_rated';
    var icon = ratingIcon(rating);
    var bench = DATA.benchmarks[m.id];
    var benchStr = bench ? fmt(bench.strong) : '-';
    var canExplore = explorable[m.id];

    // Track worst gap for default selection (only explorable metrics)
    if (canExplore && bench && val !== null && val !== undefined) {{
      var gap;
      var lowerBetter = ['burn_multiple', 'cac_payback', 'cac'];
      if (lowerBetter.indexOf(m.id) >= 0) {{
        gap = val - bench.strong;
      }} else {{
        gap = bench.strong - val;
      }}
      if (gap > 0 && (worstGap === null || gap > worstGap)) {{
        worstGap = gap;
        worstMetric = m.id;
      }}
    }}

    var ratingCell = rating === 'not_rated'
      ? '<td style="color:#86868b">\u2014</td>'
      : '<td><span class="badge ' + rating + '">' + icon + ' ' + rating + '</span></td>';
    var arrow = canExplore ? '<td style="color:#0071e3;font-size:0.7rem">\u25b6</td>' : '<td></td>';
    var trAttr = canExplore
      ? ' id="ue-row-' + m.id + '" class="clickable"'
        + ' onclick="selectMetric(\\x27' + m.id + '\\x27)" style="cursor:pointer"'
      : '';
    markup += '<tr' + trAttr + '>' +
      arrow +
      '<td>' + label + '</td>' +
      '<td>' + fmt(val) + '</td>' +
      ratingCell +
      '<td>' + benchStr + '</td></tr>';
  }});
  markup += '</table>';

  markup += '<div id="fix-metric" style="margin-top:1.5rem"></div>';
  setContent(panel, markup);

  // Auto-select worst explorable metric
  if (worstMetric) {{
    selectMetric(worstMetric);
  }} else {{
    var first = null;
    DATA.metrics.forEach(function(m) {{ if (!first && explorable[m.id]) first = m.id; }});
    if (first) selectMetric(first);
  }}
}}

function selectMetric(metricId) {{
  var m = null;
  DATA.metrics.forEach(function(metric) {{
    if (metric.id === metricId) m = metric;
  }});
  if (!m) return;

  // Highlight active row
  document.querySelectorAll('.clickable.active').forEach(function(el) {{
    el.classList.remove('active');
  }});
  var row = document.getElementById('ue-row-' + metricId);
  if (row) row.classList.add('active');

  var div = document.getElementById('fix-metric');
  if (!div) return;

  var label = metricLabels[m.id] || m.id;

  // TTM burn multiple: read-only
  if (m.id === 'burn_multiple' && m.method && m.method !== 'growth_rate') {{
    setContent(div, '<h3>Explore: ' + label + '</h3>' +
      '<p><em>Actual (trailing 12 months)</em> — this reflects historical data and cannot be adjusted.</p>' +
      '<p>Current value: <strong>' + fmtRatio(m.value) + '</strong></p>');
    return;
  }}

  // Build sliders for this metric's formula inputs
  var fixMarkup = '<h3>Explore: ' + label + '</h3>';
  var inputs = Object.assign({{}}, m.inputs || {{}});
  ueState = Object.assign({{}}, inputs);

  var formula = METRIC_FORMULAS[m.id];
  if (!formula) {{
    setContent(div, fixMarkup + '<p>This metric is calculated from your model data.</p>');
    return;
  }}

  fixMarkup += '<div id="ue-result"></div>';
  fixMarkup += '<div id="ue-sliders"></div>';
  setContent(div, fixMarkup);

  var slidersDiv = document.getElementById('ue-sliders');

  var baselineInputs = JSON.stringify(m.inputs || {{}});
  function updateUE() {{
    var newVal = formula(ueState);
    newVal = safeMetric(newVal, DATA.benchmarks[m.id] ? DATA.benchmarks[m.id].strong : null);
    var atBaseline = JSON.stringify(ueState) === baselineInputs;
    var rating = atBaseline ? (m.rating || 'not_rated') : rateMetric(m.id, newVal, DATA.benchmarks);
    var fmt = metricFmt[m.id] || String;
    var icon = ratingIcon(rating);
    var valStr = newVal !== null ? fmt(newVal) : 'N/A';
    var badgeHtml = rating === 'not_rated'
      ? '<span style="color:#86868b;font-size:0.85rem;margin-left:8px">no benchmark</span>'
      : ' <span class="badge ' + rating + '">' + icon + ' ' + rating + '</span>';
    var ueEl = document.getElementById('ue-result');
    if (ueEl) setContent(ueEl,
      '<div style="font-size:1.5rem;margin:0.5rem 0">' + valStr + badgeHtml + '</div>');
  }}

  // Add sliders based on metric type
  if (m.id === 'burn_multiple') {{
    slidersDiv.appendChild(makeSlider({{
      id: 'ue-growth', label: 'Growth rate', min: 0.001, max: 0.30, step: 0.005,
      value: ueState.growth_rate || 0.05,
      fmt: function(v) {{ return fmtPct(v, 1); }},
      onChange: function(v) {{ ueState.growth_rate = v; updateUE(); }}
    }}));
    slidersDiv.appendChild(makeSlider({{
      id: 'ue-burn', label: 'Monthly burn', min: 0, max: (ueState.monthly_burn || 50000) * 3,
      step: Math.max(1000, Math.round((ueState.monthly_burn || 50000) / 20)),
      value: ueState.monthly_burn || 0, fmt: fmtCurrency,
      onChange: function(v) {{ ueState.monthly_burn = v; updateUE(); }}
    }}));
  }} else if (m.id === 'rule_of_40') {{
    slidersDiv.appendChild(makeSlider({{
      id: 'ue-growth', label: 'Growth rate', min: 0, max: 0.30, step: 0.005,
      value: ueState.growth_rate || 0.05,
      fmt: function(v) {{ return fmtPct(v, 1); }},
      onChange: function(v) {{ ueState.growth_rate = v; updateUE(); }}
    }}));
  }} else if (['cac', 'ltv', 'ltv_cac_ratio', 'cac_payback'].indexOf(m.id) >= 0) {{
    if (ueState.arpu !== undefined) {{
      slidersDiv.appendChild(makeSlider({{
        id: 'ue-arpu', label: 'ARPU/month', min: Math.max(1, (ueState.arpu || 100) * 0.5),
        max: (ueState.arpu || 100) * 3, step: Math.max(1, Math.round((ueState.arpu || 100) / 20)),
        value: ueState.arpu || 100, fmt: fmtCurrency,
        onChange: function(v) {{ ueState.arpu = v; updateUE(); }}
      }}));
    }}
    if (ueState.churn !== undefined) {{
      slidersDiv.appendChild(makeSlider({{
        id: 'ue-churn', label: 'Monthly churn', min: 0, max: 0.15, step: 0.005,
        value: ueState.churn || 0.03,
        fmt: function(v) {{ return fmtPct(v, 1); }},
        onChange: function(v) {{ ueState.churn = v; updateUE(); }}
      }}));
    }}
    if (ueState.cac !== undefined) {{
      slidersDiv.appendChild(makeSlider({{
        id: 'ue-cac', label: 'CAC', min: Math.max(1, (ueState.cac || 500) * 0.5),
        max: (ueState.cac || 500) * 3, step: Math.max(1, Math.round((ueState.cac || 500) / 20)),
        value: ueState.cac || 500, fmt: fmtCurrency,
        onChange: function(v) {{ ueState.cac = v; updateUE(); }}
      }}));
    }}
    if (ueState.gross_margin !== undefined) {{
      slidersDiv.appendChild(makeSlider({{
        id: 'ue-gm', label: 'Gross margin', min: 0, max: 0.95, step: 0.01,
        value: ueState.gross_margin || 0.7,
        fmt: function(v) {{ return fmtPct(v, 0); }},
        onChange: function(v) {{ ueState.gross_margin = v; updateUE(); }}
      }}));
    }}
  }} else if (m.id === 'gross_margin') {{
    slidersDiv.appendChild(makeSlider({{
      id: 'ue-gm', label: 'Gross margin', min: 0, max: 0.95, step: 0.01,
      value: ueState.gross_margin || 0.7,
      fmt: function(v) {{ return fmtPct(v, 0); }},
      onChange: function(v) {{ ueState.gross_margin = v; updateUE(); }}
    }}));
  }}

  updateUE();
}}

// ---------------------------------------------------------------------------
// Lens 4: Stress Test
// ---------------------------------------------------------------------------

var SCENARIO_LABELS = {{
  base: 'Base case', slow: 'Slow growth',
  crisis: 'Crisis', threshold: 'Minimum viable growth'
}};

function renderStressTest() {{
  var panel = document.getElementById('lens-stress_test');
  if (!panel) return;

  var p = getStressParams();
  var result = projectScenario(p);

  // Status badge from live projection
  var alive = result.default_alive;
  var months = alive ? null : (result.runway_months || DATA.engine.max_months);
  var badge = alive
    ? '<span class="badge strong">SELF-SUSTAINING</span>'
    : '<span class="badge fail">' + months + ' MONTHS</span>';

  // Min viable growth from threshold scenario (authoritative)
  var threshold = null;
  DATA.scenarios.forEach(function(s) {{ if (s.name === 'threshold') threshold = s; }});
  var mvgText = '';
  if (threshold) {{
    if (threshold.growth_rate !== null && threshold.growth_rate !== undefined) {{
      mvgText = 'Min viable growth: <strong>'
        + fmtPct(threshold.growth_rate, 1) + ' MoM</strong>';
    }} else if (threshold.note) {{
      mvgText = '<em>' + threshold.note + '</em>';
    }}
  }}

  var markup = '<h2>Stress Test</h2>';
  markup += commentaryBox('stress_test');

  // Summary strip
  markup += '<div class="metrics-strip">' + badge;
  if (mvgText) markup += ' <span style="margin-left:12px">' + mvgText + '</span>';
  markup += '</div>';
  if (DATA.engine.growth_rate_missing) {{
    markup += '<div style="background:#fef3c7;color:#92400e;padding:8px 12px;'
      + 'border-radius:6px;font-size:0.85rem;margin:8px 0">'
      + 'Growth rate not provided \u2014 adjust the slider to explore scenarios.</div>';
  }}

  // Chart
  markup += '<div class="chart-container"><canvas id="chart-stress"></canvas></div>';

  // Disclaimer
  markup += '<p style="font-size:0.75rem;color:#86868b;margin:4px 0 12px">'
    + 'Interactive projection is approximate &mdash; '
    + 'scenario table below reflects the full review</p>';

  // Growth slider
  markup += '<div id="sliders-stress"></div>';

  // Scenario reference table
  if (DATA.scenarios.length > 0) {{
    markup += '<h3 style="margin-top:1.5rem">Review Scenarios</h3>';
    markup += '<table style="width:100%;border-collapse:collapse;'
      + 'font-size:0.875rem;margin-top:0.5rem">';
    markup += '<tr><th style="text-align:left">Scenario</th>'
      + '<th>Growth</th><th>Runway</th><th>Status</th></tr>';
    DATA.scenarios.forEach(function(s) {{
      var label = s.label || SCENARIO_LABELS[s.name]
        || (s.name.charAt(0).toUpperCase() + s.name.slice(1));
      var gr = s.growth_rate !== null && s.growth_rate !== undefined
        ? fmtPct(s.growth_rate, 1) : 'N/A';
      var status = s.default_alive
        ? '<span class="badge strong">Self-sustaining</span>'
        : '<span class="badge fail">'
          + (s.runway_months || '?') + ' months</span>';
      markup += '<tr><td>' + label + '</td><td>' + gr
        + '</td><td>' + (s.runway_months || 'N/A')
        + '</td><td>' + status + '</td></tr>';
    }});
    markup += '</table>';
  }}

  setContent(panel, markup);

  // Slider
  var sliderMax = Math.max(DATA.engine.growth_rate, 0.30);
  var sliderDiv = document.getElementById('sliders-stress');
  sliderDiv.appendChild(makeSlider({{
    id: 'stress-growth', label: 'Growth rate',
    min: 0, max: sliderMax, step: 0.005,
    value: state.stressGrowth,
    fmt: function(v) {{ return fmtPct(v, 1); }},
    onChange: function(v) {{ state.stressGrowth = v; renderStressTest(); }}
  }}));

  // Chart
  renderStressChart(result);
}}

function renderStressChart(result) {{
  var ctx = document.getElementById('chart-stress');
  if (!ctx) return;
  if (charts.stress) charts.stress.destroy();

  var projections = result.projections || [];
  var labels = projections.map(function(p) {{ return 'M' + p.month; }});
  var cashData = projections.map(function(p) {{ return Math.round(p.cash_balance); }});
  var zeroLine = projections.map(function() {{ return 0; }});

  charts.stress = new Chart(ctx, {{
    type: 'line',
    data: {{
      labels: labels,
      datasets: [
        {{
          label: 'Cash balance',
          data: cashData,
          borderColor: '#0071e3',
          backgroundColor: 'rgba(0, 113, 227, 0.1)',
          fill: true,
          tension: 0.2
        }},
        {{
          label: '$0',
          data: zeroLine,
          borderColor: '#86868b',
          borderDash: [5, 5],
          pointRadius: 0,
          fill: false
        }}
      ]
    }},
    options: {{
      responsive: true,
      maintainAspectRatio: false,
      plugins: {{
        legend: {{ display: false }},
        tooltip: {{
          callbacks: {{
            label: function(c) {{ return c.dataset.label + ': ' + fmtCurrency(c.raw); }}
          }}
        }}
      }},
      scales: {{
        y: {{
          suggestedMin: -Math.abs(cashData[0] || 100000) * 0.1,
          ticks: {{
            callback: function(v) {{ return fmtCurrency(v); }}
          }}
        }}
      }}
    }}
  }});
}}

// ---------------------------------------------------------------------------
// Initialize
// ---------------------------------------------------------------------------

(function() {{
  var lenses = {json.dumps(_LENSES)};
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
