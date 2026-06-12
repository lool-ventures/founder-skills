#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Generate self-contained explorer.html — polished interactive scenario tool.

Per design doc §10: polished demo/video-friendly interactive explorer for
the cap-table skill's distinctive output. Features:

  * Vanilla JS + vendored Chart.js (no CDN; runs offline)
  * CSS variables + light/dark theme toggle
  * Scenario picker (left rail) with active highlighting
  * Donut chart (Chart.js, animated) + ownership table
  * Custom Sankey SVG dilution flow (~200 lines)
  * Counsel-review sticky callout (right rail)
  * Number-ticker animation on scenario switch (countUp utility)
  * Walkthrough demo mode (`▶ Walkthrough` button) — scripted frame sequence
  * Side-by-side compare mode (pin a scenario as baseline)

Per design §10 security contract: all user-controlled strings HTML-escaped;
inline JSON `</` escaped to `<\\/` to prevent `</script>` breakout.

Output: HTML to --output path, JSON receipt to stdout.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import sys
from pathlib import Path
from typing import Any

_VENDOR_DIR = Path(__file__).resolve().parent / "vendor"

# Pre-AD / delta narrative fields that aggregate_ownership_by_class carries.
# They are not ownership wedges — the donut and legend must exclude them.
# Mirrors visualize.py EXCLUDED_OWNERSHIP_KEYS.
_EXCLUDED_OWNERSHIP_KEYS: frozenset[str] = frozenset(
    {
        "founders_pct_pre_anti_dilution",
        "preferred_pct_pre_anti_dilution",
        "anti_dilution_delta_pct_points",
    }
)


def _filter_agg(agg: dict[str, Any]) -> dict[str, float]:
    """Return only numeric ownership slices — exclude AD meta keys and dicts."""
    return {k: v for k, v in agg.items() if k not in _EXCLUDED_OWNERSHIP_KEYS and isinstance(v, (int, float))}


def _esc(s: Any) -> str:
    return html.escape(str(s) if s is not None else "", quote=True)


def _embed_json(data: Any) -> str:
    """JSON-encode + escape `</` to prevent </script> breakout (design §10)."""
    return json.dumps(data, default=str).replace("</", "<\\/")


def _chartjs_source() -> str:
    js_path = _VENDOR_DIR / "chart.min.js"
    return js_path.read_text(encoding="utf-8")


def render_explorer_html(
    *,
    inputs: dict[str, Any],
    cap_state: dict[str, Any],
    scenarios_doc: dict[str, Any],
    counsel_packet: dict[str, Any],
) -> str:
    scripts_dir = os.path.dirname(os.path.abspath(__file__))
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    import _theme

    brand_css = _theme.brand_css()

    company = _esc(inputs.get("company_name", "Company"))

    # Build data payload for client-side JS. Includes pre-financing baseline
    # for the Sankey source pools.
    payload = {
        "company_name": inputs.get("company_name", ""),
        "as_of_date": cap_state.get("as_of_date", ""),
        "mode": inputs.get("mode", "standard"),
        "pre_financing": {
            "common": cap_state["as_converted_totals"]["common_shares"],
            "preferred_as_converted": cap_state["as_converted_totals"]["preferred_shares_as_converted"],
            "options_outstanding": cap_state["as_converted_totals"]["options_outstanding"],
            "options_available": cap_state["as_converted_totals"]["options_available"],
            "fully_diluted": cap_state["as_converted_totals"]["fully_diluted_shares"],
        },
        "founders": [
            {"name": f["name"], "founder_id": f["founder_id"], "common_shares": f["common_shares"]}
            for f in cap_state.get("founders", [])
        ],
        "scenarios": [
            {
                "scenario_id": s["scenario_id"],
                "label": s.get("label", s["scenario_id"]),
                "type": s["type"],
                "completeness": s["computed_outputs"].get("completeness", "structural_only"),
                "cap_implied_only": s["computed_outputs"].get("cap_implied_only", False),
                "blockers": s["computed_outputs"].get("blockers", []),
                "aggregate": _filter_agg(s["computed_outputs"].get("aggregate_ownership_by_class") or {}),
                "equity_financing_price": s["computed_outputs"].get("equity_financing_price"),
                "shares_breakdown": s["computed_outputs"].get("shares_breakdown", {}),
                "post_round_fd": s["computed_outputs"].get("post_round_fully_diluted_shares"),
                "founder_impact": s["computed_outputs"].get("founder_impact"),
                "per_safe": s["computed_outputs"].get("per_safe", {}),
                "per_note": s["computed_outputs"].get("per_note", {}),
                "parameters": s.get("parameters", {}),
            }
            for s in scenarios_doc.get("scenarios", [])
        ],
        "counsel_items": counsel_packet.get("items", []),
    }
    data_json = _embed_json(payload)
    chart_js = _chartjs_source()

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Cap Table Explorer — {company}</title>
<style>
{brand_css}
  :root {{
    --bg: var(--lool-white); --fg: var(--lool-ink); --muted: var(--lool-mute);
    --border: var(--lool-line-2);
    --surface: var(--lool-paper); --surface-2: var(--lool-paper-2);
    --accent-bg: var(--lool-line-2);
    --heading: var(--lool-blue); --heading-2: var(--lool-royal);
    --label: var(--lool-subtle);
    --founders: #0D549D; --preferred: #365A8A; --pool: #6CCDFF;
    --safe: #21A2E3; --note: #C9892B; --new-money: #2F8A56;
  }}
  [data-theme="dark"] {{
    --bg: #0E1B2C; --fg: #F1F4F4; --muted: #A6AEB5; --border: #2A3B52;
    --surface: #16263B; --surface-2: #1E3048; --accent-bg: #173A5E;
    --heading: #6CCDFF; --heading-2: #48B4EA;
    --label: #A6AEB5;
  }}
  * {{ box-sizing: border-box; }}
  body {{ font-family: var(--font-body); margin: 0;
         background: var(--bg); color: var(--fg);
         -webkit-font-smoothing: antialiased; -moz-osx-font-smoothing: grayscale;
         transition: background 0.2s, color 0.2s; }}
  header {{ display: flex; justify-content: space-between; align-items: center;
             padding: 16px 24px; border-bottom: 1px solid var(--border); }}
  .title-block {{ display: flex; flex-direction: column; gap: 4px; }}
  h1 {{ font-size: 22px; margin: 0; font-weight: 400; color: var(--heading);
        letter-spacing: -0.01em; }}
  h2, h3 {{ font-weight: 500; color: var(--heading-2); }}
  .meta {{ color: var(--muted); font-size: 13px; }}
  .controls {{ display: flex; gap: 8px; align-items: center; }}
  .btn {{ padding: 6px 12px; border: 1px solid var(--border); border-radius: var(--r-input);
          background: var(--bg); color: var(--fg); font-size: 13px; cursor: pointer;
          font-family: var(--font-body);
          transition: all 0.15s; }}
  .btn:hover {{ border-color: var(--lool-azure); }}
  .btn.primary {{ background: var(--lool-blue); color: white; border-color: var(--lool-blue); }}
  .btn.primary:hover {{ background: var(--lool-blue-deep); }}
  .layout {{ display: grid; grid-template-columns: 240px 1fr 280px;
             min-height: calc(100vh - 65px); }}
  aside {{ padding: 16px; border-right: 1px solid var(--border); background: var(--surface); }}
  .section-label {{ font-size: 11px; color: var(--label); margin-bottom: 8px;
                     text-transform: uppercase; letter-spacing: 0.06em; font-weight: 600; }}
  .scenario-pill {{ display: block; width: 100%; text-align: left;
                     padding: 10px 12px; margin-bottom: 6px; border: 1px solid var(--border);
                     border-radius: var(--r-input); background: var(--bg); color: var(--fg); cursor: pointer;
                     font-size: 14px; font-family: var(--font-body); transition: all .12s ease; }}
  .scenario-pill:hover {{ border-color: var(--lool-azure); }}
  .scenario-pill.active {{ border-color: var(--lool-blue); background: var(--accent-bg); font-weight: 600; }}
  .scenario-pill.pinned::after {{ content: "📌"; margin-left: 6px; font-size: 11px; }}
  main {{ padding: 24px; overflow-y: auto; }}
  .right-rail {{ padding: 16px; border-left: 1px solid var(--border); background: var(--surface);
                  overflow-y: auto; max-height: calc(100vh - 65px); }}
  .donut-wrap {{ display: grid; grid-template-columns: 200px 1fr; gap: 24px;
                  align-items: center; margin: 16px 0; }}
  .donut-canvas {{ position: relative; height: 200px; width: 200px; }}
  .legend {{ list-style: none; padding: 0; margin: 0; font-size: 13px; }}
  .legend li {{ display: flex; align-items: center; gap: 8px; padding: 4px 0;
                 transition: opacity 0.2s; }}
  .legend li.dimmed {{ opacity: 0.35; }}
  .swatch {{ width: 14px; height: 14px; border-radius: 0; flex-shrink: 0; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 13px; margin: 12px 0; }}
  th, td {{ border: 1px solid var(--border); padding: 6px 10px; text-align: left; }}
  th {{ background: var(--surface); font-weight: 600; }}
  .num {{ text-align: right; font-variant-numeric: tabular-nums; }}
  .badge {{ display: inline-block; padding: 2px 8px; border-radius: var(--r-pill); font-size: 11px;
            font-weight: 600; text-transform: uppercase; letter-spacing: 0.06em; }}
  .badge.full {{ background: var(--lool-success-tint); color: var(--lool-success); }}
  .badge.structural_only {{ background: var(--lool-warning-tint); color: var(--lool-warning); }}
  .badge.repay_only {{ background: var(--lool-paper-2); color: var(--lool-slate); }}
  .badge.mixed {{ background: var(--lool-line-2); color: var(--lool-royal); }}
  .blocker {{ background: var(--lool-danger-tint); border-left: 3px solid var(--lool-danger); padding: 8px 12px;
              margin: 8px 0; border-radius: 0; font-size: 13px; color: var(--lool-danger); }}
  .blocker code {{ font-weight: 600; }}
  code {{ background: var(--surface-2); padding: 1px 4px; border-radius: var(--r-input);
          font-size: 0.9em; font-family: var(--font-mono); }}
  details {{ margin: 8px 0; background: var(--bg); border: 1px solid var(--border);
              border-radius: 0; padding: 8px 12px; }}
  summary {{ cursor: pointer; font-weight: 600; padding: 4px 0; user-select: none; }}
  .impact-callout {{ background: var(--accent-bg); border-radius: 0; padding: 16px;
                      margin: 16px 0; border-left: 4px solid var(--lool-blue);
                      font-size: 14px; line-height: 1.5; }}
  .number-display {{ font-size: 28px; font-weight: 700; font-variant-numeric: tabular-nums;
                      color: var(--heading); }}
  .number-label {{ font-size: 12px; color: var(--muted); text-transform: uppercase;
                    letter-spacing: 0.06em; margin-top: 2px; }}
  .metric-row {{ display: flex; gap: 24px; margin: 16px 0; }}
  .metric {{ flex: 1; padding: 12px 16px; background: var(--surface); border-radius: 0;
              border: 1px solid var(--border); }}
  .compare-banner {{ background: var(--lool-warning-tint); color: var(--lool-ink); padding: 10px 16px;
                      border-radius: 0; border-left: 3px solid var(--lool-warning);
                      margin: 12px 0; font-size: 13px;
                      display: flex; justify-content: space-between; align-items: center; }}
  .compare-banner button {{ background: transparent; border: 1px solid var(--lool-warning);
                              color: var(--lool-warning); padding: 4px 8px; border-radius: var(--r-input);
                              font-family: var(--font-body); cursor: pointer; }}
  .walkthrough-toast {{ position: fixed; bottom: 24px; left: 50%; transform: translateX(-50%);
                          background: var(--fg); color: var(--bg); padding: 14px 20px;
                          border-radius: var(--r-input); font-size: 14px; max-width: 600px; z-index: 1000;
                          box-shadow: var(--shadow-soft); opacity: 0;
                          transition: opacity 0.3s, transform 0.3s; }}
  .walkthrough-toast.visible {{ opacity: 1; transform: translateX(-50%) translateY(-4px); }}
  .sankey-container {{ margin: 24px 0; border: 1px solid var(--border); border-radius: 0;
                        padding: 16px; background: var(--surface); }}
  .sankey-container h3 {{ margin: 0 0 12px; font-size: 14px; color: var(--label);
                            text-transform: uppercase; letter-spacing: 0.06em; }}
  .sankey-path {{ transition: opacity 0.2s; }}
  .sankey-path:hover {{ opacity: 0.7; cursor: pointer; }}
  .sankey-label {{ font-size: 11px; fill: var(--fg); font-family: var(--font-body); }}
  .sankey-block {{ stroke: var(--bg); stroke-width: 1; }}
</style>
</head>
<body>
<header>
  <div class="title-block">
    <h1>Cap Table Explorer — {company}</h1>
    <span class="meta">As of <span id="as-of">{_esc(cap_state.get("as_of_date", ""))}</span></span>
  </div>
  <div class="controls">
    <button class="btn" id="theme-toggle" title="Toggle light/dark">☀️</button>
    <button class="btn primary" id="walkthrough-btn">▶ Walkthrough</button>
  </div>
</header>
<div class="layout">
  <aside>
    <div class="section-label">Scenarios</div>
    <div id="scenario-list"></div>
    <div style="margin-top: 24px;">
      <div class="section-label">Compare</div>
      <button class="btn" id="pin-btn" style="width:100%;">📌 Pin current as baseline</button>
    </div>
  </aside>
  <main>
    <div id="compare-banner" style="display:none;"></div>
    <div id="scenario-view"></div>
  </main>
  <div class="right-rail">
    <div class="section-label">Counsel Review</div>
    <div id="counsel-list"></div>
  </div>
</div>
<div class="walkthrough-toast" id="toast"></div>

<script>
{chart_js}
</script>

<script>
const DATA = {data_json};

const PALETTE = {{
  founders: "#0D549D",
  preferred: "#365A8A",
  option_pool: "#6CCDFF",
  safe: "#21A2E3",
  note: "#C9892B",
  new_money: "#2F8A56",
  warrants: "#48B4EA",
}};

let _chartInstance = null;
let _pinnedScenarioIdx = null;
let _activeIdx = 0;
let _walkthroughTimer = null;

function escape(s) {{
  if (s === null || s === undefined) return "";
  return String(s).replace(/[&<>"']/g, c =>
    ({{"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#x27;"}})[c]);
}}

function pct(n) {{ return (n * 100).toFixed(1) + "%"; }}
function fmtMoney(n) {{
  if (n === null || n === undefined) return "—";
  if (Math.abs(n) >= 1e9) return "$" + (n/1e9).toFixed(2) + "B";
  if (Math.abs(n) >= 1e6) return "$" + (n/1e6).toFixed(2) + "M";
  if (Math.abs(n) >= 1e3) return "$" + (n/1e3).toFixed(0) + "K";
  return "$" + Math.round(n).toLocaleString();
}}
function fmtShares(n) {{
  if (n === null || n === undefined) return "—";
  return Math.round(n).toLocaleString();
}}

// countUp animation utility — animates from `from` to `to` over `duration` ms
function countUp(el, from, to, duration, formatter) {{
  formatter = formatter || (v => v.toFixed(1) + "%");
  const start = performance.now();
  function tick(now) {{
    const elapsed = now - start;
    const t = Math.min(1, elapsed / duration);
    const eased = 1 - Math.pow(1 - t, 3);  // ease-out cubic
    const v = from + (to - from) * eased;
    el.textContent = formatter(v);
    if (t < 1) requestAnimationFrame(tick);
  }}
  requestAnimationFrame(tick);
}}

// ---------------------------------------------------------------------------
// Sankey-style dilution flow renderer (~150 lines)
// Source pools → Target pools, path widths proportional to share counts.
// ---------------------------------------------------------------------------

function renderSankey(container, scenarioData) {{
  container.innerHTML = "";
  const pre = DATA.pre_financing;
  const breakdown = scenarioData.shares_breakdown || {{}};
  const postFd = scenarioData.post_round_fd || pre.fully_diluted;

  if (!breakdown.pre_round_fully_diluted) {{
    container.innerHTML = '<p style="color:var(--muted);font-size:13px;">No dilution flow — scenario is pending.</p>';
    return;
  }}

  // Sources (pre-financing pools)
  const sources = [
    {{ label: "Common", value: pre.common, color: PALETTE.founders }},
    {{ label: "Preferred", value: pre.preferred_as_converted, color: PALETTE.preferred }},
    {{ label: "Option Pool", value: pre.options_outstanding + pre.options_available, color: PALETTE.option_pool }},
  ].filter(s => s.value > 0);

  // Sinks (post-financing pools)
  const sinks = [
    {{ label: "Founders & Common", value: pre.common, color: PALETTE.founders }},
    {{ label: "Preferred", value: pre.preferred_as_converted, color: PALETTE.preferred }},
    {{ label: "Option Pool + Top-up", value: (pre.options_outstanding + pre.options_available + (breakdown.pool_topup || 0)), color: PALETTE.option_pool }},
    {{ label: "SAFE/Note Converted", value: (breakdown.safe_converted || 0) + (breakdown.note_converted || 0), color: PALETTE.safe }},
    {{ label: "New Money", value: breakdown.new_money || 0, color: PALETTE.new_money }},
  ].filter(s => s.value > 0);

  const W = 720, H = 360;
  const PAD = 20, BLOCK_W = 14;
  const innerH = H - 2 * PAD;

  // Stack sources on left
  let yCursor = PAD;
  const sourceBlocks = sources.map(s => {{
    const h = (s.value / postFd) * innerH;
    const block = {{ ...s, y: yCursor, h }};
    yCursor += h;
    return block;
  }});

  // Stack sinks on right
  yCursor = PAD;
  const sinkBlocks = sinks.map(s => {{
    const h = (s.value / postFd) * innerH;
    const block = {{ ...s, y: yCursor, h }};
    yCursor += h;
    return block;
  }});

  // Build flow paths: each source → corresponding sink (by label match for the common/preferred/pool flows;
  // SAFE/Note + New Money come from synthetic "issuance" sources).
  const flows = [];
  const matchByLabel = {{
    "Common": "Founders & Common",
    "Preferred": "Preferred",
    "Option Pool": "Option Pool + Top-up",
  }};

  sourceBlocks.forEach(src => {{
    const sinkLabel = matchByLabel[src.label];
    const dst = sinkBlocks.find(s => s.label === sinkLabel);
    if (dst) flows.push({{ src, dst, color: src.color, opacity: 0.55 }});
  }});
  // Synthetic flows from outside (right edge of source area) for new issuances
  const safeNoteAmount = (breakdown.safe_converted || 0) + (breakdown.note_converted || 0);
  const newMoneyAmount = breakdown.new_money || 0;
  if (safeNoteAmount > 0) {{
    const dst = sinkBlocks.find(s => s.label === "SAFE/Note Converted");
    if (dst) flows.push({{ src: {{ x: PAD, y: H/2 - 20, h: (safeNoteAmount / postFd) * innerH, label: "New issuance" }}, dst, color: PALETTE.safe, opacity: 0.55, isSynthetic: true }});
  }}
  if (newMoneyAmount > 0) {{
    const dst = sinkBlocks.find(s => s.label === "New Money");
    if (dst) flows.push({{ src: {{ x: PAD, y: H/2 + 20, h: (newMoneyAmount / postFd) * innerH, label: "Investor cash" }}, dst, color: PALETTE.new_money, opacity: 0.55, isSynthetic: true }});
  }}

  // Render SVG
  const svg = `<svg viewBox="0 0 ${{W}} ${{H}}" style="width:100%;height:auto;max-height:400px;">
    ${{flows.map(f => {{
      const x1 = PAD + BLOCK_W;
      const x2 = W - PAD - BLOCK_W;
      const y1 = (f.src.y || PAD) + (f.src.h / 2);
      const y2 = f.dst.y + (f.dst.h / 2);
      const cx1 = x1 + (x2 - x1) * 0.5;
      const cx2 = x2 - (x2 - x1) * 0.5;
      const strokeW = Math.max(2, f.dst.h);
      return `<path class="sankey-path" d="M ${{x1}},${{y1}} C ${{cx1}},${{y1}} ${{cx2}},${{y2}} ${{x2}},${{y2}}" stroke="${{f.color}}" stroke-width="${{strokeW}}" fill="none" opacity="${{f.opacity}}"/>`;
    }}).join("")}}
    ${{sourceBlocks.map(b => `
      <rect class="sankey-block" x="${{PAD}}" y="${{b.y}}" width="${{BLOCK_W}}" height="${{b.h}}" fill="${{b.color}}"/>
      <text class="sankey-label" x="${{PAD - 4}}" y="${{b.y + b.h/2 + 4}}" text-anchor="end">${{escape(b.label)}}</text>
    `).join("")}}
    ${{sinkBlocks.map(b => `
      <rect class="sankey-block" x="${{W - PAD - BLOCK_W}}" y="${{b.y}}" width="${{BLOCK_W}}" height="${{b.h}}" fill="${{b.color}}"/>
      <text class="sankey-label" x="${{W - PAD + 4}}" y="${{b.y + b.h/2 + 4}}" text-anchor="start">${{escape(b.label)}} (${{pct(b.value/postFd)}})</text>
    `).join("")}}
  </svg>`;
  container.innerHTML = svg;
}}

// ---------------------------------------------------------------------------
// Chart.js donut + ownership table
// ---------------------------------------------------------------------------

function renderDonut(canvasEl, breakdown) {{
  if (_chartInstance) _chartInstance.destroy();
  const labels = [];
  const data = [];
  const colors = [];
  for (const [cat, frac] of Object.entries(breakdown)) {{
    if (frac <= 0) continue;
    labels.push(cat.replace(/_/g, " "));
    data.push(frac * 100);
    colors.push(PALETTE[cat] || "#A6AEB5");
  }}
  _chartInstance = new Chart(canvasEl, {{
    type: "doughnut",
    data: {{ labels, datasets: [{{ data, backgroundColor: colors, borderWidth: 2,
                                    borderColor: getComputedStyle(document.body).getPropertyValue("--bg") }}] }},
    options: {{
      responsive: true, maintainAspectRatio: false,
      plugins: {{
        legend: {{ display: false }},
        tooltip: {{ callbacks: {{ label: ctx => `${{ctx.label}}: ${{ctx.parsed.toFixed(1)}}%` }} }},
      }},
      animation: {{ duration: 750, easing: "easeInOutCubic" }},
    }},
  }});
}}

function renderScenarioList() {{
  const list = document.getElementById("scenario-list");
  list.innerHTML = DATA.scenarios.map((s, i) =>
    `<button class="scenario-pill" data-idx="${{i}}">${{escape(s.label)}}</button>`
  ).join("");
  list.querySelectorAll(".scenario-pill").forEach(b => {{
    b.addEventListener("click", () => selectScenario(parseInt(b.dataset.idx)));
  }});
  if (DATA.scenarios.length > 0) selectScenario(0);
}}

function selectScenario(idx) {{
  _activeIdx = idx;
  document.querySelectorAll(".scenario-pill").forEach((b, i) => {{
    b.classList.toggle("active", i === idx);
    b.classList.toggle("pinned", i === _pinnedScenarioIdx);
  }});
  const s = DATA.scenarios[idx];
  const view = document.getElementById("scenario-view");

  let body = `<h2 style="margin-top:0;">${{escape(s.label)}} <span class="badge ${{s.completeness}}">${{s.completeness}}</span></h2>`;
  if (s.cap_implied_only) body += `<p class="meta">Cap-implied output set only (pre-financing snapshot)</p>`;
  body += `<p class="meta">Type: <code>${{escape(s.type)}}</code></p>`;

  if (s.blockers && s.blockers.length > 0) {{
    body += "<h3>Blockers</h3>";
    for (const b of s.blockers) {{
      body += `<div class="blocker"><code>${{escape(b.code)}}</code> ${{b.instance_id ? "on " + escape(b.instance_id) : ""}}: ${{escape(b.remedy)}}</div>`;
    }}
  }}

  if (s.completeness === "full" || s.completeness === "mixed") {{
    const agg = s.aggregate;
    // Metric row
    const founderImpact = s.founder_impact || {{}};
    body += `<div class="metric-row">
      <div class="metric"><div class="number-display" id="founder-pct">${{pct(agg.founders_pct || 0)}}</div><div class="number-label">Founder ownership</div></div>
      ${{s.equity_financing_price ? `<div class="metric"><div class="number-display" id="price-psh">$${{s.equity_financing_price.toFixed(4)}}</div><div class="number-label">Price per share</div></div>` : ""}}
      ${{s.post_round_fd ? `<div class="metric"><div class="number-display" id="post-fd">${{fmtShares(s.post_round_fd)}}</div><div class="number-label">Post-round FD shares</div></div>` : ""}}
    </div>`;

    body += `<div class="donut-wrap"><div class="donut-canvas"><canvas id="donut-chart"></canvas></div>`;
    body += `<ul class="legend">`;
    for (const [cat, frac] of Object.entries(agg)) {{
      if (frac <= 0) continue;
      const c = PALETTE[cat] || "#A6AEB5";
      body += `<li><span class="swatch" style="background:${{c}};"></span>${{escape(cat.replace(/_/g, ' '))}}: <strong style="margin-left:auto;">${{pct(frac)}}</strong></li>`;
    }}
    body += `</ul></div>`;

    if (s.founder_impact) {{
      body += `<div class="impact-callout"><strong>Founder Impact:</strong> ${{escape(s.founder_impact.plain_language)}}</div>`;
    }}

    // Sankey dilution flow
    body += `<div class="sankey-container"><h3>Dilution flow</h3><div id="sankey"></div></div>`;
  }} else if (s.cap_implied_only && Object.keys(s.per_safe).length > 0) {{
    // Cap-implied per-SAFE summary
    body += `<h3>Cap-implied ownership (pre-financing)</h3>`;
    body += `<table><thead><tr><th>SAFE</th><th class="num">Cap-implied %</th><th class="num">Safe price</th><th class="num">Shares</th></tr></thead><tbody>`;
    for (const [sid, r] of Object.entries(s.per_safe)) {{
      body += `<tr><td>${{escape(sid)}}</td><td class="num">${{pct(r.cap_implied_ownership || 0)}}</td><td class="num">$${{(r.safe_price || 0).toFixed(4)}}</td><td class="num">${{fmtShares(r.cap_implied_shares || 0)}}</td></tr>`;
    }}
    body += `</tbody></table>`;
  }} else {{
    body += `<p class="meta"><em>This scenario is pending — see blockers above.</em></p>`;
  }}

  // Per-SAFE / per-note details
  if (Object.keys(s.per_safe || {{}}).length > 0 && !s.cap_implied_only) {{
    body += "<details><summary>Per-SAFE detail</summary><table><thead><tr><th>SAFE</th><th>Branch</th><th class='num'>Shares</th><th class='num'>Price</th></tr></thead><tbody>";
    for (const [sid, r] of Object.entries(s.per_safe)) {{
      const shares = r.conversion_shares || r.cap_implied_shares || 0;
      const price = r.conversion_price || r.safe_price || 0;
      body += `<tr><td>${{escape(sid)}}</td><td>${{escape(r.branch)}}</td><td class="num">${{fmtShares(shares)}}</td><td class="num">$${{price.toFixed(4)}}</td></tr>`;
    }}
    body += "</tbody></table></details>";
  }}
  if (Object.keys(s.per_note || {{}}).length > 0) {{
    body += "<details><summary>Per-note detail</summary><table><thead><tr><th>Note</th><th>Branch</th><th class='num'>Shares / Cash</th></tr></thead><tbody>";
    for (const [nid, r] of Object.entries(s.per_note)) {{
      const val = r.conversion_shares !== undefined
        ? fmtShares(r.conversion_shares) + " shares"
        : (r.cash_repayment !== undefined ? fmtMoney(r.cash_repayment) : "—");
      body += `<tr><td>${{escape(nid)}}</td><td>${{escape(r.branch)}}</td><td class="num">${{val}}</td></tr>`;
    }}
    body += "</tbody></table></details>";
  }}

  view.innerHTML = body;

  // Render Chart.js donut + Sankey after DOM update
  const canvas = document.getElementById("donut-chart");
  if (canvas && (s.completeness === "full" || s.completeness === "mixed")) {{
    renderDonut(canvas, s.aggregate);
  }}
  const sankeyDiv = document.getElementById("sankey");
  if (sankeyDiv) renderSankey(sankeyDiv, s);

  // Compare banner
  updateCompareBanner();
}}

function updateCompareBanner() {{
  const banner = document.getElementById("compare-banner");
  if (_pinnedScenarioIdx === null || _pinnedScenarioIdx === _activeIdx) {{
    banner.style.display = "none";
    return;
  }}
  const pinned = DATA.scenarios[_pinnedScenarioIdx];
  const active = DATA.scenarios[_activeIdx];
  const pinnedF = (pinned.aggregate.founders_pct || 0) * 100;
  const activeF = (active.aggregate.founders_pct || 0) * 100;
  const delta = (activeF - pinnedF).toFixed(1);
  const sign = delta >= 0 ? "+" : "";
  banner.style.display = "flex";
  banner.className = "compare-banner";
  banner.innerHTML = `<div>Compared to <strong>${{escape(pinned.label)}}</strong> (baseline): founder ownership is <strong>${{sign}}${{delta}}pp</strong></div><button id="unpin-btn">Unpin baseline</button>`;
  document.getElementById("unpin-btn").addEventListener("click", () => {{
    _pinnedScenarioIdx = null;
    updateCompareBanner();
    document.querySelectorAll(".scenario-pill").forEach(p => p.classList.remove("pinned"));
  }});
}}

function renderCounsel() {{
  const list = document.getElementById("counsel-list");
  if (!DATA.counsel_items || DATA.counsel_items.length === 0) {{
    list.innerHTML = "<p class='meta'><em>No counsel items.</em></p>";
    return;
  }}
  let html = "<p style='font-size:13px;color:var(--muted);'>" + DATA.counsel_items.length + " item(s) for your lawyer.</p>";
  for (const it of DATA.counsel_items) {{
    html += `<details><summary>${{escape(it.title)}}</summary>`;
    html += `<p style='font-size:12px;margin:8px 0 0;color:var(--muted);'><code>${{escape(it.rule_id)}}</code></p>`;
    if (it.counsel_question) html += `<p style='font-size:13px;margin:8px 0;'>${{escape(it.counsel_question)}}</p>`;
    html += `</details>`;
  }}
  list.innerHTML = html;
}}

// ---------------------------------------------------------------------------
// Theme toggle
// ---------------------------------------------------------------------------
function toggleTheme() {{
  const current = document.body.dataset.theme || "light";
  const next = current === "light" ? "dark" : "light";
  document.body.dataset.theme = next;
  document.getElementById("theme-toggle").textContent = next === "dark" ? "🌙" : "☀️";
  // Re-render donut to pick up new border color
  if (_chartInstance && _activeIdx !== null) {{
    const canvas = document.getElementById("donut-chart");
    if (canvas) renderDonut(canvas, DATA.scenarios[_activeIdx].aggregate);
  }}
}}

// ---------------------------------------------------------------------------
// Walkthrough demo mode
// ---------------------------------------------------------------------------

function showToast(msg, duration) {{
  const toast = document.getElementById("toast");
  toast.textContent = msg;
  toast.classList.add("visible");
  if (duration) setTimeout(() => toast.classList.remove("visible"), duration);
}}

function hideToast() {{
  document.getElementById("toast").classList.remove("visible");
}}

function startWalkthrough() {{
  if (_walkthroughTimer) {{
    clearTimeout(_walkthroughTimer);
    _walkthroughTimer = null;
    hideToast();
    document.getElementById("walkthrough-btn").textContent = "▶ Walkthrough";
    return;
  }}
  document.getElementById("walkthrough-btn").textContent = "■ Stop";

  const frames = [
    {{ msg: "Welcome — this is your cap-table explorer. The left rail shows the scenarios we modeled.", duration: 4500, action: () => selectScenario(0) }},
    {{ msg: `Scenario 1: ${{DATA.scenarios[0]?.label || "baseline"}}. Watch the donut + Sankey on the right.`, duration: 4500 }},
    ...DATA.scenarios.slice(1).map((s, i) => ({{ msg: `Now: ${{s.label}} — see how ownership shifts.`, duration: 4500, action: () => selectScenario(i + 1) }})),
    {{ msg: `${{DATA.counsel_items.length}} counsel-review items in the right rail — these are questions for your lawyer, not legal advice.`, duration: 5000 }},
    {{ msg: "Walkthrough complete. Click any scenario to explore further.", duration: 4000 }},
  ];

  let i = 0;
  function nextFrame() {{
    if (i >= frames.length) {{
      hideToast();
      document.getElementById("walkthrough-btn").textContent = "▶ Walkthrough";
      _walkthroughTimer = null;
      return;
    }}
    const f = frames[i++];
    if (f.action) f.action();
    showToast(f.msg);
    _walkthroughTimer = setTimeout(nextFrame, f.duration);
  }}
  nextFrame();
}}

// ---------------------------------------------------------------------------
// Wire up event handlers
// ---------------------------------------------------------------------------
document.getElementById("theme-toggle").addEventListener("click", toggleTheme);
document.getElementById("walkthrough-btn").addEventListener("click", startWalkthrough);
document.getElementById("pin-btn").addEventListener("click", () => {{
  _pinnedScenarioIdx = (_pinnedScenarioIdx === _activeIdx) ? null : _activeIdx;
  document.querySelectorAll(".scenario-pill").forEach((p, i) => p.classList.toggle("pinned", i === _pinnedScenarioIdx));
  updateCompareBanner();
}});

// Keyboard navigation: arrow keys to switch scenarios
document.addEventListener("keydown", e => {{
  if (e.key === "ArrowDown" || e.key === "ArrowRight") {{
    e.preventDefault();
    selectScenario(Math.min(_activeIdx + 1, DATA.scenarios.length - 1));
  }} else if (e.key === "ArrowUp" || e.key === "ArrowLeft") {{
    e.preventDefault();
    selectScenario(Math.max(_activeIdx - 1, 0));
  }}
}});

renderScenarioList();
renderCounsel();
</script>
{_theme.FOOTER_CREDIT_HTML}
</body>
</html>
"""


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dir", required=True)
    p.add_argument("-o", "--output", required=True)
    p.add_argument("--pretty", action="store_true", help="Indent the JSON receipt printed to stdout")
    args = p.parse_args()

    def _read(name: str) -> dict[str, Any]:
        with open(os.path.join(args.dir, name), encoding="utf-8") as f:
            return json.load(f)  # type: ignore[no-any-return]

    inputs = _read("inputs.json")
    cap_state = _read("cap_state.json")
    scenarios_doc = _read("scenarios.json")
    counsel_packet = _read("counsel_packet.json")

    html_out = render_explorer_html(
        inputs=inputs,
        cap_state=cap_state,
        scenarios_doc=scenarios_doc,
        counsel_packet=counsel_packet,
    )
    out = os.path.abspath(args.output)
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(html_out)
    print(
        json.dumps(
            {"ok": True, "path": out, "bytes": len(html_out.encode("utf-8"))},
            indent=2 if args.pretty else None,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
