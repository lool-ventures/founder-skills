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


def _sweep_payload(sweep: dict[str, Any] | None) -> dict[str, Any] | None:
    """Normalize sweep.json frames to the compact shape the slider JS consumes."""
    if not sweep or not sweep.get("frames"):
        return None

    # Only the per-instrument fields the detail tables show — keeps payload small.
    _safe_keys = ("branch", "conversion_shares", "conversion_price", "cap_implied_shares", "safe_price")
    _note_keys = ("branch", "conversion_shares", "cash_repayment")

    def _trim(d: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
        return {sid: {k: r.get(k) for k in keys if k in r} for sid, r in (d or {}).items()}

    frames = []
    for fr in sweep["frames"]:
        o = fr.get("outputs") or {}
        frames.append(
            {
                "pre_money": fr.get("pre_money"),
                "valid": bool(fr.get("valid")),
                "aggregate": _filter_agg(o.get("aggregate_ownership_by_class") or {}),
                "equity_financing_price": o.get("equity_financing_price"),
                "post_round_fd": o.get("post_round_fully_diluted_shares"),
                "shares_breakdown": o.get("shares_breakdown") or {},
                "impact_text": (o.get("founder_impact") or {}).get("plain_language"),
                "per_safe": _trim(o.get("per_safe") or {}, _safe_keys),
                "per_note": _trim(o.get("per_note") or {}, _note_keys),
            }
        )
    return {
        "axis": sweep.get("axis", "pre_money"),
        "base_scenario_id": sweep.get("base_scenario_id"),
        "frames": frames,
    }


def render_explorer_html(
    *,
    inputs: dict[str, Any],
    cap_state: dict[str, Any],
    scenarios_doc: dict[str, Any],
    counsel_packet: dict[str, Any],
    sweep: dict[str, Any] | None = None,
) -> str:
    scripts_dir = os.path.dirname(os.path.abspath(__file__))
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    import _labels
    import _rules
    import _theme

    brand_css = _theme.brand_css()
    labels_json = _embed_json(_labels.MAPS)
    cap_implied_gloss = _esc(_labels.CAP_IMPLIED_GLOSS)

    def _enrich_counsel(it: dict[str, Any]) -> dict[str, Any]:
        # Resolve the rule's plain-English summary + primary-source links so the
        # counsel rail can show a linked, readable reference.
        ref = _rules.rule_ref(it.get("rule_id", ""), item_source_ids=it.get("source_ids"))
        return {**it, "_summary": ref["summary"], "_links": ref["links"]}

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
        "counsel_items": [_enrich_counsel(it) for it in counsel_packet.get("items", [])],
        "sweep": _sweep_payload(sweep),
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
  .term {{ border-bottom: 1px dotted var(--border); cursor: help; }}
  .controls {{ display: flex; gap: 8px; align-items: center; }}
  .btn {{ padding: 6px 12px; border: 1px solid var(--border); border-radius: var(--r-input);
          background: var(--bg); color: var(--fg); font-size: 13px; cursor: pointer;
          font-family: var(--font-body);
          transition: all 0.15s; }}
  .btn:hover {{ border-color: var(--lool-azure); }}
  .btn.primary {{ background: var(--lool-blue); color: white; border-color: var(--lool-blue); }}
  .btn.primary:hover {{ background: var(--lool-blue-deep); }}
  .layout {{ display: grid; grid-template-columns: 236px minmax(0, 1fr) 312px;
             min-height: calc(100vh - 65px); }}
  /* Counsel rail stacks below content on small laptops/tablets; everything
     stacks single-column on phones. The header counsel cue keeps the rail
     reachable when it's pushed out of sight. */
  @media (max-width: 1180px) {{
    .layout {{ grid-template-columns: 220px minmax(0, 1fr); }}
    .right-rail {{ grid-column: 1 / -1; border-left: none; border-top: 1px solid var(--border);
                    max-height: none; }}
  }}
  @media (max-width: 760px) {{
    .layout {{ grid-template-columns: 1fr; }}
    aside {{ grid-column: 1 / -1; border-right: none; border-bottom: 1px solid var(--border); }}
    .metric-row {{ grid-template-columns: 1fr !important; }}
    .graphics-row {{ grid-template-columns: 1fr !important; }}
    .compare-grid {{ grid-template-columns: 1fr !important; }}
  }}
  aside {{ padding: 16px; border-right: 1px solid var(--border); background: var(--surface); }}
  .section-label {{ font-size: 11px; color: var(--label); margin-bottom: 8px;
                     text-transform: uppercase; letter-spacing: 0.06em; font-weight: 600; }}
  .scenario-pill {{ display: block; width: 100%; text-align: left;
                     padding: 10px 12px; margin-bottom: 6px; border: 1px solid var(--border);
                     border-radius: var(--r-input); background: var(--bg); color: var(--fg); cursor: pointer;
                     font-size: 14px; font-family: var(--font-body); transition: all .12s ease; }}
  .scenario-pill:hover {{ border-color: var(--lool-azure); }}
  .scenario-pill.active {{ border-color: var(--lool-blue); background: var(--accent-bg); font-weight: 600; }}
  main {{ padding: 24px; overflow-y: auto; }}
  .right-rail {{ padding: 16px; border-left: 1px solid var(--border); background: var(--surface);
                  overflow-y: auto; max-height: calc(100vh - 65px); }}
  .donut-canvas {{ position: relative; height: 200px; width: 200px; max-width: 100%; }}
  .legend {{ list-style: none; padding: 0; margin: 0; font-size: 13px; }}
  .legend li {{ display: flex; align-items: center; gap: 8px; padding: 4px 0; }}
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
  .blocker-code {{ margin-top: 6px; font-family: var(--font-mono); font-size: 11px;
                    color: var(--lool-mute); opacity: 0.85; }}
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
  .metric-row {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr));
                  gap: 14px; margin: 16px 0; }}
  .metric {{ padding: 14px 18px; background: var(--surface); border-radius: 6px;
              border: 1px solid var(--border); transition: background .15s, border-color .15s; }}
  .number-display {{ font-size: clamp(24px, 2.6vw, 36px); }}
  /* Modeled what-if: tint the slider panel + metric cards so a slider-driven
     number never reads as the agreed round. */
  .metric-row.modeled .metric {{ background: var(--lool-warning-tint); border-color: var(--lool-warning); }}
  #sweep-wrap {{ margin: 16px 0; padding: 12px 16px; background: var(--surface);
                  border: 1px solid var(--border); }}
  #sweep-wrap label {{ display: block; font-size: 11px; text-transform: uppercase;
                        letter-spacing: 0.06em; color: var(--label); font-weight: 600; margin-bottom: 8px; }}
  #sweep-slider {{ width: 100%; accent-color: var(--lool-blue); }}
  .sweep-readout {{ font-size: 13px; color: var(--muted); margin-top: 8px;
                     font-variant-numeric: tabular-nums; }}
  .compare-banner {{ background: var(--lool-warning-tint); color: var(--lool-ink); padding: 10px 16px;
                      border-radius: 0; border-left: 3px solid var(--lool-warning);
                      margin: 12px 0; font-size: 13px;
                      display: flex; justify-content: space-between; align-items: center; }}
  .compare-banner button {{ background: transparent; border: 1px solid var(--lool-warning);
                              color: var(--lool-warning); padding: 4px 8px; border-radius: var(--r-input);
                              font-family: var(--font-body); cursor: pointer; }}
  .walkthrough-toast {{ position: fixed; bottom: 24px; left: 50%; transform: translateX(-50%);
                          background: var(--fg); color: var(--bg); padding: 12px 16px;
                          border-radius: var(--r-input); font-size: 14px; max-width: 640px; z-index: 1000;
                          box-shadow: var(--shadow-soft); opacity: 0; pointer-events: none;
                          display: flex; align-items: center; gap: 10px;
                          transition: opacity 0.3s, transform 0.3s; }}
  .walkthrough-toast.visible {{ opacity: 1; pointer-events: auto; transform: translateX(-50%) translateY(-4px); }}
  .wt-ctl {{ flex: none; width: 26px; height: 26px; padding: 0; display: inline-flex;
              align-items: center; justify-content: center; background: transparent;
              border: 1px solid rgba(255,255,255,0.35); border-radius: var(--r-input);
              color: var(--bg); font-size: 15px; line-height: 1; cursor: pointer; font-family: var(--font-body); }}
  .wt-ctl .ico {{ width: 13px; height: 13px; }}
  #wt-msg {{ flex: 1; min-width: 0; }}
  .sankey-container {{ margin: 24px 0; border: 1px solid var(--border); border-radius: 0;
                        padding: 16px; background: var(--surface); }}
  .sankey-container h3 {{ margin: 0 0 12px; font-size: 14px; color: var(--label);
                            text-transform: uppercase; letter-spacing: 0.06em; }}
  .sankey-path {{ transition: opacity 0.2s; }}
  .sankey-path:hover {{ opacity: 0.7; cursor: pointer; }}
  .sankey-label {{ font-size: 11px; fill: var(--fg); font-family: var(--font-body); }}
  .sankey-block {{ stroke: var(--bg); stroke-width: 1; }}

  /* ---- PR1 usability: icons, counsel cue, print, slider panel, graphics ---- */
  .btn {{ display: inline-flex; align-items: center; gap: 7px; }}
  .ico {{ width: 16px; height: 16px; stroke: currentColor; fill: none; stroke-width: 1.7;
          flex: none; }}
  .btn.cue {{ border-color: var(--lool-warning); background: var(--lool-warning-tint);
              color: var(--lool-warning); font-weight: 600; }}
  .btn.cue:hover {{ border-color: var(--lool-warning); }}
  /* Slider panel (what-if): primary control at top; folds in the modeled state. */
  #sweep-wrap {{ border-radius: 8px; }}
  #sweep-wrap.modeled {{ background: var(--lool-warning-tint); border-color: var(--lool-warning); }}
  .sweep-head {{ display: flex; justify-content: space-between; align-items: center;
                  gap: 16px; min-height: 28px; }}
  .sweep-title {{ display: flex; align-items: center; gap: 9px; font-size: 12px;
                   text-transform: uppercase; letter-spacing: 0.06em; font-weight: 600;
                   color: var(--label); }}
  #sweep-wrap.modeled .sweep-title {{ color: var(--lool-warning); }}
  .sweep-pre {{ font-size: 16px; font-weight: 700; font-variant-numeric: tabular-nums;
                 color: var(--heading); white-space: nowrap; }}
  .sweep-reset {{ padding: 4px 11px; border: 1px solid var(--lool-warning); border-radius: var(--r-input);
                   background: var(--bg); color: var(--lool-warning); font-size: 12px; font-weight: 600;
                   font-family: var(--font-body); cursor: pointer; }}
  /* Donut + flow side by side; shared legend below. */
  .graphics-row {{ display: grid; grid-template-columns: 230px minmax(0, 1fr); gap: 14px;
                    margin: 16px 0; align-items: stretch; }}
  .graphics-card {{ border: 1px solid var(--border); border-radius: 8px; padding: 18px;
                     background: var(--surface); min-width: 0; }}
  .legend-summary {{ border: 1px solid var(--border); border-radius: 8px; padding: 16px 20px;
                      background: var(--surface-2); margin: 4px 0 20px; }}
  .legend-summary .legend {{ display: flex; flex-wrap: wrap; gap: 8px 22px; }}
  .legend-summary .legend li {{ gap: 9px; }}
  .donut-summary {{ font-size: 12px; color: var(--label); margin: 12px 0 0; line-height: 1.55; }}
  /* Counsel relevance tiers + flow caption */
  .rel-badge {{ display: inline-block; font-size: 9px; font-weight: 700; text-transform: uppercase;
                 letter-spacing: 0.05em; padding: 2px 7px; border-radius: var(--r-pill); }}
  .rel-applies {{ background: var(--lool-warning-tint); color: var(--lool-warning); }}
  .rel-likely {{ background: var(--accent-bg); color: var(--heading-2); }}
  .rel-general {{ background: var(--surface-2); color: var(--lool-slate); }}
  .flow-cap {{ font-size: 13px; fill: var(--label); font-style: italic; }}
  .counsel-item {{ padding: 13px 0; border-top: 1px solid var(--border); }}
  .counsel-item .ci-head {{ display: flex; align-items: center; gap: 8px; margin-bottom: 5px; }}
  .counsel-item .ci-domain {{ font-size: 10px; text-transform: uppercase; letter-spacing: 0.04em;
                               color: var(--label); }}
  .counsel-item .ci-title {{ font-size: 13px; font-weight: 600; color: var(--fg); line-height: 1.35;
                              margin-bottom: 4px; }}
  .counsel-item .ci-q {{ font-size: 12px; line-height: 1.5; color: var(--muted); }}
  .counsel-code {{ display: none; margin-top: 6px; font-family: var(--font-mono); font-size: 10px;
                    color: var(--label); }}
  #counsel-list.codes-shown .counsel-code {{ display: block; }}
  .codes-toggle {{ margin-top: 14px; width: 100%; padding: 7px; border: 1px dashed var(--border);
                    border-radius: var(--r-input); background: transparent; color: var(--label);
                    font-size: 11px; font-family: var(--font-mono); cursor: pointer; }}
  @media (max-width: 760px) {{ .graphics-row {{ grid-template-columns: 1fr; }} }}
  /* Two-up side-by-side scenario compare */
  .compare-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 18px; margin: 12px 0; }}
  @media (max-width: 760px) {{ .compare-grid {{ grid-template-columns: 1fr; }} }}
  .compare-card {{ border: 1px solid var(--border); border-radius: 8px; padding: 20px 22px;
                    background: var(--surface); }}
  .compare-card .cmp-slot {{ display: inline-block; font-size: 11px; font-weight: 700; color: #fff;
                              border-radius: var(--r-input); padding: 2px 8px; margin-right: 8px; }}
  .compare-card .cmp-canvas {{ position: relative; width: 120px; height: 120px; flex: none; }}
  .compare-card table {{ margin: 0; }}
  .compare-card td {{ border: none; padding: 3px 0; }}
  /* The scenario whose founders keep more reads greener. */
  .compare-card.better {{ border-color: var(--lool-success); background: var(--lool-success-tint); }}
  .cmp-canvas {{ position: relative; }}
  .cmp-center {{ position: absolute; inset: 0; display: flex; align-items: center;
                  justify-content: center; font-size: 17px; font-weight: 700; color: var(--heading); }}
  /* Donut hole overlay: the headline founder share + label. */
  .donut-center {{ position: absolute; inset: 0; display: flex; flex-direction: column;
                    align-items: center; justify-content: center; pointer-events: none; }}
  .donut-center-val {{ font-size: 24px; font-weight: 700; color: var(--heading); line-height: 1; }}
  .donut-center-label {{ font-size: 10px; text-transform: uppercase; letter-spacing: 0.05em;
                          color: var(--muted); margin-top: 3px; }}
  .metric-sub {{ margin-top: 4px; }}
  .nowrap {{ white-space: nowrap; }}
  .sweep-ends {{ display: flex; justify-content: space-between; font-size: 11px;
                  color: var(--label); margin-top: 2px; font-variant-numeric: tabular-nums; }}
  /* In a modeled what-if the whole slider panel reads as a warning, icon included. */
  #sweep-wrap.modeled .sweep-title svg {{ stroke: var(--lool-warning); }}
  .sweep-reset.invisible {{ visibility: hidden; pointer-events: none; }}
  #compare-hint {{ margin-top: 12px; padding: 10px 12px; background: var(--accent-bg);
                    border-radius: var(--r-input); font-size: 12px; line-height: 1.5; color: var(--lool-slate); }}
  /* Scenario pills: a status dot + status line, and a "B" tag on the compare target. */
  .scenario-pill {{ position: relative; }}
  .pill-row {{ display: flex; justify-content: space-between; align-items: center; gap: 8px; }}
  .pill-status {{ display: flex; align-items: center; gap: 6px; margin-top: 6px;
                   font-size: 11px; color: var(--muted); }}
  .pill-dot {{ width: 7px; height: 7px; border-radius: 50%; flex: none; }}
  .b-badge {{ display: none; font-size: 10px; font-weight: 700; text-transform: uppercase;
              letter-spacing: 0.05em; color: var(--lool-azure); }}
  .scenario-pill.pinned .b-badge {{ display: inline; }}
  .cta-card {{ padding: 22px 24px; border: 1px dashed var(--border); border-radius: 8px;
               background: var(--surface); margin: 12px 0; }}
  .cta-title {{ font-size: 15px; font-weight: 600; color: var(--heading-2); margin-bottom: 6px; }}
  @media print {{
    .no-print {{ display: none !important; }}
    body {{ background: #fff; color: #111; }}
    .layout {{ display: block; }}
    aside, .right-rail {{ border: none; }}
    .metric, .graphics-card, .legend-summary {{ break-inside: avoid; }}
    [hidden] {{ display: none !important; }}
  }}
</style>
</head>
<body>
<header>
  <div class="title-block">
    <h1>Cap Table Explorer — {company}</h1>
    <span class="meta">As of <span id="as-of">{_esc(cap_state.get("as_of_date", ""))}</span></span>
  </div>
  <div class="controls no-print">
    <button class="btn cue" id="counsel-cue" hidden title="Jump to questions for your lawyer">
      <svg class="ico" viewBox="0 0 24 24" style="stroke:var(--lool-warning);"><path d="M12 3v18M5 7h14M7 7l-3 7h6l-3-7zM17 7l-3 7h6l-3-7z"/></svg><span id="counsel-cue-label"></span></button>
    <button class="btn" id="compare-toggle" title="Compare two scenarios side by side">
      <svg class="ico" viewBox="0 0 24 24"><rect x="3" y="4" width="7" height="16" rx="1"/><rect x="14" y="4" width="7" height="16" rx="1"/></svg><span id="compare-label">Compare</span></button>
    <button class="btn" id="theme-toggle" title="Toggle light/dark" aria-label="Toggle light/dark theme">
      <svg class="ico" id="theme-ico" viewBox="0 0 24 24"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg></button>
    <button class="btn" id="print-btn" title="Print or save as PDF">
      <svg class="ico" viewBox="0 0 24 24"><path d="M6 9V3h12v6"/><rect x="6" y="13" width="12" height="8"/><path d="M6 17H3v-5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v5h-3"/></svg>Export PDF</button>
    <button class="btn primary" id="walkthrough-btn">
      <svg class="ico" id="walkthrough-ico" viewBox="0 0 24 24" style="fill:currentColor;stroke:none;"><path d="M8 5v14l11-7z"/></svg><span id="walkthrough-label">Walkthrough</span></button>
  </div>
</header>
<div class="layout">
  <aside>
    <div class="section-label">Scenarios</div>
    <div id="scenario-list"></div>
    <div id="compare-hint" hidden>Pick a second scenario above to set it as <strong>B</strong> and compare side by side.</div>
    <div style="margin-top: 24px;">
      <div class="section-label">Compare</div>
      <button class="btn" id="pin-btn" style="width:100%;">
        <svg class="ico" viewBox="0 0 24 24"><path d="M9 4h6l-1 7 3 3v2H7v-2l3-3-1-7zM12 16v4"/></svg><span id="pin-label">Pin current as baseline</span></button>
    </div>
    <div id="founders-block" style="margin-top:24px;" hidden>
      <div class="section-label">Founders today</div>
      <div id="founders-list"></div>
    </div>
  </aside>
  <main>
    <div id="compare-banner" style="display:none;"></div>
    <div id="scenario-view">
      <div id="scenario-head"></div>
      <div id="scenario-blockers"></div>
      <div id="sweep-wrap" class="no-print" hidden>
        <div class="sweep-head">
          <div class="sweep-title">
            <svg class="ico" viewBox="0 0 24 24" style="width:18px;height:18px;"><path d="M4 8h8M16 8h4M4 16h4M12 16h8"/><circle cx="14" cy="8" r="2"/><circle cx="10" cy="16" r="2"/></svg>
            <span id="sweep-title-text">Model the round — drag to explore a valuation</span>
          </div>
          <div style="display:flex;align-items:center;gap:14px;">
            <span class="sweep-pre"><span id="sweep-pre-val">—</span> <span style="font-size:11px;font-weight:500;color:var(--muted);">pre-money</span></span>
            <button class="sweep-reset invisible" id="sweep-reset">Reset to scenario</button>
          </div>
        </div>
        <input type="range" id="sweep-slider" min="0" max="0" value="0" step="1" style="width:100%;margin-top:12px;accent-color:var(--lool-blue);" aria-label="Pre-money valuation">
        <div class="sweep-ends"><span id="sweep-end-lo"></span><span id="sweep-end-hi"></span></div>
        <div class="sweep-readout" id="sweep-readout"></div>
      </div>
      <div class="metric-row" id="metric-row" hidden>
        <div class="metric" id="metric-founder"><div class="number-display" id="founder-pct">—</div><div class="number-label">Founder ownership</div><div class="number-label metric-sub" id="founder-delta" style="color:var(--lool-danger);"></div></div>
        <div class="metric" id="metric-price"><div class="number-display" id="price-psh">—</div><div class="number-label">Price per share</div><div class="number-label metric-sub">what new investors pay</div></div>
        <div class="metric" id="metric-fd"><div class="number-display nowrap" id="post-fd">—</div><div class="number-label"><span class="term" title="Fully-diluted shares — the total if every option and convertible converts to stock">Shares after round</span></div><div class="number-label metric-sub">fully diluted total</div></div>
      </div>
      <div class="graphics-row" id="graphics-row" hidden>
        <div class="graphics-card" style="display:flex;flex-direction:column;align-items:center;">
          <div class="section-label" style="align-self:flex-start;">Ownership after this round</div>
          <div class="donut-canvas"><canvas id="donut-chart"></canvas>
            <div class="donut-center"><div class="donut-center-val" id="donut-center-val">—</div><div class="donut-center-label">founders</div></div>
          </div>
        </div>
        <div class="graphics-card" id="sankey-container">
          <div class="section-label">Where your ownership went</div>
          <p class="donut-summary" id="flow-intro" style="margin:0 0 8px;">Founders &amp; the option pool carry straight across. New investors and converting SAFEs are issued this round, so the same founder shares become a smaller slice of a bigger total.</p>
          <div id="sankey"></div>
        </div>
      </div>
      <div class="legend-summary" id="legend-summary" hidden>
        <ul class="legend" id="legend"></ul>
        <p class="donut-summary" id="donut-summary"></p>
      </div>
      <div class="impact-callout" id="impact-callout" hidden></div>
      <div id="scenario-variable"></div>
    </div>
    <div id="compare-view" hidden>
      <h2 style="margin-top:0;">Side by side</h2>
      <p class="meta" style="margin-top:0;">Which round leaves founders better off? The greener column keeps more.</p>
      <div class="compare-grid" id="compare-grid"></div>
      <div class="impact-callout" id="compare-verdict" hidden></div>
    </div>
  </main>
  <div class="right-rail" id="counsel-rail">
    <div class="section-label">Questions for your lawyer</div>
    <div id="counsel-list"></div>
  </div>
</div>
<div class="walkthrough-toast no-print" id="toast">
  <button class="wt-ctl" id="wt-prev" title="Previous" aria-label="Previous step">‹</button>
  <button class="wt-ctl" id="wt-playpause" title="Pause" aria-label="Pause">
    <svg class="ico" id="wt-pp-ico" viewBox="0 0 24 24" style="fill:currentColor;stroke:none;"><rect x="6" y="5" width="4" height="14"/><rect x="14" y="5" width="4" height="14"/></svg></button>
  <button class="wt-ctl" id="wt-next" title="Next" aria-label="Next step">›</button>
  <span id="wt-msg"></span>
  <button class="wt-ctl" id="wt-close" title="End walkthrough" aria-label="End walkthrough">×</button>
</div>

<script>
{chart_js}
</script>

<script>
const DATA = {data_json};
const LABELS = {labels_json};
const CAP_IMPLIED_GLOSS = "{cap_implied_gloss}";

// Plain-language label for an internal enum; raw code stays as a hover tooltip.
function humanize(cat, val) {{
  if (val === null || val === undefined || val === "") return "—";
  const m = LABELS[cat] || {{}};
  return m[val] || String(val).replace(/_/g, " ");
}}
function term(cat, val) {{
  if (val === null || val === undefined || val === "") return humanize(cat, val);
  return `<span class="term" title="${{escape(val)}}">${{escape(humanize(cat, val))}}</span>`;
}}

const PALETTE = {{
  founders: "#0D549D",
  preferred: "#365A8A",
  option_pool: "#6CCDFF",
  safe: "#21A2E3",
  note: "#C9892B",
  new_money: "#2F8A56",
  warrants: "#48B4EA",
}};
const NEUTRAL = "#A6AEB5";

// aggregate_ownership_by_class keys carry a `_pct` suffix (founders_pct, …),
// but PALETTE keys do not. Strip the suffix before color/label lookup, or every
// wedge falls back to NEUTRAL and labels read "founders pct". Mirrors
// visualize.py's _palette_color (color); also drops `_pct` from the label.
function sliceColor(cat) {{ return PALETTE[cat.replace(/_pct$/, "")] || NEUTRAL; }}
function sliceLabel(cat) {{ return cat.replace(/_pct$/, "").replace(/_/g, " "); }}

// Chart registry keyed by canvas id: the single-view donut ("donut-chart") and
// the two compare donuts ("cmp-donut-a"/"cmp-donut-b") must all be live at once,
// so a single shared instance won't do. Every donut site looks up / tears down
// its chart by canvas id.
const _charts = {{}};
function _destroyChart(id) {{ if (_charts[id]) {{ _charts[id].destroy(); delete _charts[id]; }} }}
let _pinnedScenarioIdx = null;
let _activeIdx = 0;
let _compareMode = false;
let _walkthroughTimer = null;

// P0 number-ticker state. `_prevMetrics` caches the last *displayed* value per
// metric (so a full→cap-implied→full sequence still tweens from the real prior
// value); `_metricAnimGen` invalidates superseded tweens; `_metricsIntroDone`
// gates the capture-mode intro tick to the first full/mixed metric render.
let _prevMetrics = {{ founders_pct: null, price: null, post_fd: null }};
let _metricAnimGen = 0;
let _metricsIntroDone = false;
let _hasSweep = false;
const _REDUCED_MOTION = !!(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
const _CAPTURE = new URLSearchParams(location.search).get("capture") === "1";
if (_CAPTURE) document.body.dataset.capture = "1";

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

// countUp animation utility — animates from `from` to `to` over `duration` ms.
// Seeds the start value synchronously so the eye never sees the pre-rendered
// final value flash for one frame before the tween starts. `gen` lets a newer
// animation supersede an in-flight one (rapid scenario switches / arrow-nav).
function countUp(el, from, to, duration, formatter, gen) {{
  formatter = formatter || (v => v.toFixed(1) + "%");
  el.textContent = formatter(from);
  const start = performance.now();
  function tick(now) {{
    if (gen !== undefined && gen !== _metricAnimGen) return;
    const elapsed = now - start;
    const t = Math.min(1, elapsed / duration);
    const eased = 1 - Math.pow(1 - t, 3);  // ease-out cubic
    const v = from + (to - from) * eased;
    el.textContent = formatter(v);
    if (t < 1) requestAnimationFrame(tick);
  }}
  requestAnimationFrame(tick);
}}

// animateMetric — tween one metric node from its previous value to the new one.
// Direct-sets (no tween) under prefers-reduced-motion or when there is no prior
// value (first appearance). 600ms ease-out per design §10.
function animateMetric(id, from, to, formatter, gen) {{
  const el = document.getElementById(id);
  if (!el || to == null) return;
  if (_REDUCED_MOTION || from == null) {{ el.textContent = formatter(to); return; }}
  countUp(el, from, to, 600, formatter, gen);
}}

// ---------------------------------------------------------------------------
// Sankey-style dilution flow renderer (~150 lines)
// Source pools → Target pools, path widths proportional to share counts.
// ---------------------------------------------------------------------------

// Swap the Sankey content with a fade transition (P2 / design §10-C "Sankey
// transition") so a scenario switch reads as a transition, not a snap. The
// #sankey node persists (P0a); a pending swap is cancelled so rapid switches
// don't stack. Reduced-motion sets directly.
function setSankeyHTML(container, html, instant) {{
  // `instant` (slider scrub) skips the fade so rapid updates don't strobe.
  if (_REDUCED_MOTION || instant) {{
    if (container._sankeyTimer) {{ clearTimeout(container._sankeyTimer); container._sankeyTimer = null; }}
    container.style.opacity = "1";
    container.innerHTML = html;
    return;
  }}
  if (container._sankeyTimer) clearTimeout(container._sankeyTimer);
  container.style.transition = "opacity 0.15s";
  container.style.opacity = "0";
  container._sankeyTimer = setTimeout(() => {{
    container.innerHTML = html;
    container.style.opacity = "1";
    container._sankeyTimer = null;
  }}, 150);
}}

// Ownership flow — a plain-language "before → after" story for founders.
// Carried classes (founders, preferred, pool) flow straight across;
// new issuance (converting SAFEs/notes + new investors) rises in FROM BELOW the
// "after" column, so the same founder shares visibly become a smaller slice of
// a bigger total. Keeps setSankeyHTML + .sankey-path/.sankey-block for the
// transition + headless tests.
// A fixed shares→pixels reference (the largest post-round total across every
// scenario and what-if frame) so the "Before" stack stays the same physical
// height everywhere — only the "After" column grows as more shares are issued.
const _FLOW_REF = (() => {{
  let m = 0;
  for (const s of DATA.scenarios) if (s.post_round_fd) m = Math.max(m, s.post_round_fd);
  if (DATA.sweep && DATA.sweep.frames) for (const f of DATA.sweep.frames) if (f.post_round_fd) m = Math.max(m, f.post_round_fd);
  const pre = DATA.pre_financing || {{}};
  return m || (pre.fully_diluted ? pre.fully_diluted * 1.5 : 1);
}})();

function renderSankey(container, scenarioData, instant) {{
  const pre = DATA.pre_financing;
  const breakdown = scenarioData.shares_breakdown || {{}};
  const postFd = scenarioData.post_round_fd || pre.fully_diluted;

  if (!breakdown.pre_round_fully_diluted) {{
    setSankeyHTML(container, '<p style="color:var(--muted);font-size:13px;">No dilution flow — scenario is pending.</p>', instant);
    return;
  }}

  const common = pre.common || 0;
  const preferred = pre.preferred_as_converted || 0;
  const poolBase = (pre.options_outstanding || 0) + (pre.options_available || 0);
  const poolTopup = breakdown.pool_topup || 0;
  const safeNote = (breakdown.safe_converted || 0) + (breakdown.note_converted || 0);
  const newMoney = breakdown.new_money || 0;

  const before = [
    {{ key: "common", label: "Founders & common", v: common, c: PALETTE.founders }},
    {{ key: "preferred", label: "Preferred", v: preferred, c: PALETTE.preferred }},
    {{ key: "pool", label: "Option pool", v: poolBase, c: PALETTE.option_pool }},
  ].filter(s => s.v > 0);
  const after = [
    {{ key: "common", label: "Founders & common", v: common, c: PALETTE.founders }},
    {{ key: "preferred", label: "Preferred", v: preferred, c: PALETTE.preferred }},
    {{ key: "pool", label: "Option pool", v: poolBase + poolTopup, c: PALETTE.option_pool }},
    {{ key: "safe", label: "SAFEs converted", v: safeNote, c: PALETTE.safe }},
    {{ key: "new", label: "New investors", v: newMoney, c: PALETTE.new_money }},
  ].filter(s => s.v > 0);

  const W = 760, H = 320, BW = 15, TOP = 34;
  const LG = 168, RG = 150;
  const innerH = H - TOP - 26;
  const scale = innerH / _FLOW_REF;  // fixed reference: Before stays put, After grows with issuance

  const preTotal = before.reduce((a, s) => a + s.v, 0) || 1;
  let y = TOP + (innerH - preTotal * scale) / 2;
  const lB = before.map(s => {{ const h = Math.max(2, s.v * scale); const b = {{ ...s, y, h }}; y += h; return b; }});
  y = TOP + (innerH - postFd * scale) / 2;
  const rB = after.map(s => {{ const h = Math.max(2, s.v * scale); const b = {{ ...s, y, h }}; y += h; return b; }});

  const xL = LG, xR = W - RG - BW;
  const x1 = xL + BW, x2 = xR;
  const lByKey = {{}}; lB.forEach(b => {{ lByKey[b.key] = b; }});

  let paths = "";
  rB.forEach(rb => {{
    const lb = lByKey[rb.key];
    if (!lb) return;  // new issuance handled below
    const sy = lb.y + lb.h / 2, dy = rb.y + rb.h / 2;
    const cx1 = x1 + (x2 - x1) * 0.5, cx2 = x2 - (x2 - x1) * 0.5;
    paths += `<path class="sankey-path" d="M ${{x1}},${{sy}} C ${{cx1}},${{sy}} ${{cx2}},${{dy}} ${{x2}},${{dy}}" stroke="${{lb.c}}" stroke-width="${{Math.max(2, rb.h)}}" fill="none" opacity="0.42"/>`;
  }});
  rB.filter(b => b.key === "safe" || b.key === "new").forEach((rb, i) => {{
    const dy = rb.y + rb.h / 2;
    const sx = x2 - (x2 - x1) * (0.30 - i * 0.12);
    paths += `<path class="sankey-path" d="M ${{sx}},${{H}} C ${{sx}},${{dy + 46}} ${{x2 - 24}},${{dy}} ${{x2}},${{dy}}" stroke="${{rb.c}}" stroke-width="${{Math.max(2, rb.h)}}" fill="none" opacity="0.42"/>`;
  }});

  const rect = (b, x) => `<rect class="sankey-block" x="${{x}}" y="${{b.y}}" width="${{BW}}" height="${{b.h}}" rx="1" fill="${{b.c}}"/>`;
  const lLabels = lB.map(b => `<text class="sankey-label" x="${{xL - 6}}" y="${{b.y + b.h/2 + 4}}" text-anchor="end">${{escape(b.label)}} · ${{Math.round(b.v / preTotal * 100)}}%</text>`).join("");
  const rLabels = rB.map(b => `<text class="sankey-label" x="${{xR + BW + 6}}" y="${{b.y + b.h/2 + 4}}" text-anchor="start">${{escape(b.label)}} · ${{Math.round(b.v / postFd * 100)}}%</text>`).join("");

  const svg = `<svg viewBox="0 0 ${{W}} ${{H}}" style="width:100%;height:auto;max-height:340px;display:block;">
    <text class="sankey-label" x="${{xL}}" y="18" style="font-weight:600;fill:var(--label);">Before · ${{fmtShares(preTotal)}} sh</text>
    <text class="sankey-label" x="${{xR + BW}}" y="18" text-anchor="end" style="font-weight:600;fill:var(--label);">After · ${{fmtShares(postFd)}} sh</text>
    ${{paths}}
    ${{lB.map(b => rect(b, xL)).join("")}}
    ${{rB.map(b => rect(b, xR)).join("")}}
    ${{lLabels}}
    ${{rLabels}}
    <text class="flow-cap" x="${{x2 - (x2 - x1) * 0.22}}" y="${{H - 3}}" text-anchor="middle">↑ new shares issued this round</text>
  </svg>`;
  setSankeyHTML(container, svg, instant);
}}

// ---------------------------------------------------------------------------
// Chart.js donut + ownership table
// ---------------------------------------------------------------------------

// Fixed wedge order (P1). Building over a stable key set with 0 for absent
// categories keeps Chart.js dataset indices stable across scenarios, so
// `.update()` tweens wedges (0→value to appear, value→0 to disappear) instead
// of a fresh grow-in. Keys carry the `_pct` suffix; there is no warrants_pct.
const DONUT_ORDER = ["founders_pct", "preferred_pct", "option_pool_pct", "safe_pct", "note_pct", "new_money_pct"];

// Accessibility: a non-color channel for the wedges (hatch/dot patterns) so the
// near-identical blues are still distinguishable for color-blind and low-vision
// readers. Guarded: when the canvas API is unavailable (e.g. a server-side or
// test renderer with no document.createElement), fall back to the solid color.
const PATTERN_KIND = {{
  founders_pct: "solid", preferred_pct: "diag", option_pool_pct: "dot",
  safe_pct: "cross", note_pct: "solid", new_money_pct: "solid",
}};
function _wedgePattern(color, kind) {{
  if (typeof document.createElement !== "function") return color;
  let cv;
  try {{ cv = document.createElement("canvas"); }} catch (e) {{ return color; }}
  if (!cv || typeof cv.getContext !== "function") return color;
  const S = 10; cv.width = S; cv.height = S;
  const ctx = cv.getContext("2d");
  if (!ctx) return color;
  ctx.fillStyle = color; ctx.fillRect(0, 0, S, S);
  ctx.strokeStyle = "rgba(255,255,255,0.55)"; ctx.lineWidth = 2;
  if (kind === "diag" || kind === "cross") {{
    ctx.beginPath(); ctx.moveTo(0, S); ctx.lineTo(S, 0); ctx.stroke();
    if (kind === "cross") {{ ctx.beginPath(); ctx.moveTo(0, 0); ctx.lineTo(S, S); ctx.stroke(); }}
  }} else if (kind === "dot") {{
    ctx.fillStyle = "rgba(255,255,255,0.6)";
    ctx.beginPath(); ctx.arc(S / 2, S / 2, 1.7, 0, Math.PI * 2); ctx.fill();
  }}
  const p = ctx.createPattern(cv, "repeat");
  return p || color;
}}
function _wedgeFill(cat) {{
  const color = sliceColor(cat);
  const kind = PATTERN_KIND[cat] || "solid";
  return kind === "solid" ? color : _wedgePattern(color, kind);
}}

function renderDonut(canvasEl, breakdown, animate) {{
  // `animate` defaults true. The slider passes false to SNAP wedges (no
  // fabricated in-between geometry mid-drag); under capture it passes true.
  if (animate === undefined) animate = true;
  const doAnim = animate && !_REDUCED_MOTION;
  const labels = DONUT_ORDER.map(sliceLabel);
  const data = DONUT_ORDER.map(k => (breakdown[k] || 0) * 100);
  const colors = DONUT_ORDER.map(_wedgeFill);
  const borderColor = getComputedStyle(document.body).getPropertyValue("--bg");

  // Morph in place when a chart is already bound to this (persistent) canvas.
  const cid = canvasEl.id;
  const existing = _charts[cid];
  if (existing && existing.canvas === canvasEl) {{
    existing.data.labels = labels;
    existing.data.datasets[0].data = data;
    existing.data.datasets[0].backgroundColor = colors;
    existing.data.datasets[0].borderColor = borderColor;
    if (doAnim) {{ existing.update(); }} else {{ existing.update("none"); }}
    return;
  }}
  _destroyChart(cid);
  _charts[cid] = new Chart(canvasEl, {{
    type: "doughnut",
    data: {{ labels, datasets: [{{ data, backgroundColor: colors, borderWidth: 2, borderColor }}] }},
    options: {{
      responsive: true, maintainAspectRatio: false,
      plugins: {{
        legend: {{ display: false }},
        // Hide the zero-area wedges the fixed order introduces from the tooltip.
        tooltip: {{ filter: item => item.parsed > 0, callbacks: {{ label: ctx => `${{ctx.label}}: ${{ctx.parsed.toFixed(1)}}%` }} }},
      }},
      animation: doAnim ? {{ duration: 750, easing: "easeInOutCubic" }} : false,
    }},
  }});
}}

// Index of the first fully/partly-modeled scenario — the default landing view.
// A structure-only "cap-implied today" scenario hides all three hero metrics by
// design, so landing there would show a founder a first screen with no numbers.
function firstModeledIdx() {{
  const i = DATA.scenarios.findIndex(s => s.completeness === "full" || s.completeness === "mixed");
  return i === -1 ? 0 : i;
}}

// A colored dot + one-line status for a scenario pill, keyed on completeness.
function _scenarioStatus(s) {{
  if (s.completeness === "full") return {{ dot: "var(--lool-success)", text: "Fully modeled" }};
  if (s.completeness === "mixed") return {{ dot: "var(--lool-success)", text: "Partially modeled" }};
  if (s.cap_implied_only) return {{ dot: "var(--lool-warning)", text: "Structure only — no priced round" }};
  return {{ dot: "var(--lool-slate)", text: humanize("completeness", s.completeness) }};
}}

function renderScenarioList() {{
  const list = document.getElementById("scenario-list");
  list.innerHTML = DATA.scenarios.map((s, i) => {{
    const st = _scenarioStatus(s);
    return `<button class="scenario-pill" data-idx="${{i}}">`
      + `<div class="pill-row"><span>${{escape(s.label)}}</span><span class="b-badge">B</span></div>`
      + `<div class="pill-status"><span class="pill-dot" style="background:${{st.dot}};"></span>${{escape(st.text)}}</div>`
      + `</button>`;
  }}).join("");
  list.querySelectorAll(".scenario-pill").forEach(b => {{
    b.addEventListener("click", () => selectScenario(parseInt(b.dataset.idx)));
  }});
  if (DATA.scenarios.length > 0) selectScenario(firstModeledIdx());
}}

// "Founders today" rail block — orientation: who holds what right now.
function renderFoundersBlock() {{
  const founders = DATA.founders || [];
  if (!founders.length) return;
  const list = document.getElementById("founders-list");
  if (!list) return;
  list.innerHTML = founders.map(f =>
    `<div style="display:flex;justify-content:space-between;font-size:13px;padding:4px 0;">`
    + `<span>${{escape(f.name)}}</span>`
    + `<span class="num" style="color:var(--muted);">${{fmtShares(f.common_shares)}}</span></div>`
  ).join("");
  show("founders-block", true);
}}

// Ownership legend (the per-class % next to the donut). Iterates DONUT_ORDER
// so swatch order matches the donut arcs. Shared by selectScenario + the slider.
function renderLegend(agg, fd) {{
  agg = agg || {{}};
  let legend = "";
  for (const cat of DONUT_ORDER) {{
    const frac = agg[cat] || 0;
    if (frac <= 0) continue;
    const shares = fd ? ` <span style="color:var(--label);">· ${{fmtShares(frac * fd)}}</span>` : "";
    legend += `<li><span class="swatch" style="background:${{sliceColor(cat)}};"></span>${{escape(sliceLabel(cat))}} <strong>${{pct(frac)}}</strong>${{shares}}</li>`;
  }}
  const el = document.getElementById("legend");
  if (el) el.innerHTML = legend;
}}

// The founder share shown in the donut hole. Kept in sync with the metric card.
function _setDonutCenter(foundersFrac) {{
  const el = document.getElementById("donut-center-val");
  if (el) el.textContent = foundersFrac == null ? "—" : pct(foundersFrac);
}}

// Founder-Impact callout. Persists across renders, so it's cleared+hidden when
// absent. Shared by selectScenario (animate) + the slider (snap). `text` is the
// plain-language impact sentence (or falsy to hide).
function renderImpact(text, animate) {{
  const impact = document.getElementById("impact-callout");
  if (!impact) return;
  if (text) {{
    impact.innerHTML = `<strong>Founder Impact:</strong> ${{escape(text)}}`;
    impact.hidden = false;
    if (animate) slideIn(impact);
  }} else {{
    impact.innerHTML = "";
    impact.hidden = true;
  }}
}}

// The slider's frames model the base scenario's pre-money axis; it is only
// meaningful on that scenario. Other scenarios hide the slider so its readout
// never describes a different round than the cards show.
function _isSweepBase(idx) {{
  if (!_hasSweep || !DATA.sweep) return false;
  const s = DATA.scenarios[idx];
  return !!s && s.scenario_id === DATA.sweep.base_scenario_id;
}}

// Modeled-state: a slider drag opts into a hypothetical. We tint the slider
// panel + metric cards and reveal Reset so a modeled number never reads as the
// agreed round. Sticky until reset or a scenario switch.
let _modeled = false;
function enterModeled() {{
  if (_modeled) return;
  _modeled = true;
  const sw = document.getElementById("sweep-wrap"); if (sw) sw.classList.add("modeled");
  const mr = document.getElementById("metric-row"); if (mr) mr.classList.add("modeled");
  const t = document.getElementById("sweep-title-text"); if (t) t.textContent = "Modeled what-if — not the agreed round";
  // Toggle visibility (not display) so the panel height never shifts.
  const rb = document.getElementById("sweep-reset"); if (rb) rb.classList.remove("invisible");
}}
function exitModeled() {{
  _modeled = false;
  const sw = document.getElementById("sweep-wrap"); if (sw) sw.classList.remove("modeled");
  const mr = document.getElementById("metric-row"); if (mr) mr.classList.remove("modeled");
  const t = document.getElementById("sweep-title-text"); if (t) t.textContent = "Model the round — drag to explore a valuation";
  const rb = document.getElementById("sweep-reset"); if (rb) rb.classList.add("invisible");
}}

// Plain-language ownership summary under the shared legend (founder-facing
// alternative to reading the donut + the chart's text alternative for a11y).
function renderDonutSummary(agg, fd) {{
  const el = document.getElementById("donut-summary");
  if (!el) return;
  const parts = [];
  for (const cat of DONUT_ORDER) {{
    const frac = agg[cat] || 0;
    if (frac > 0) parts.push(`${{sliceLabel(cat)}} ${{pct(frac)}}`);
  }}
  const tail = fd ? ` — of ${{fmtShares(fd)}} fully-diluted shares` : "";
  el.textContent = parts.join(", ") + tail + ".";
  const canvas = document.getElementById("donut-chart");
  if (canvas) canvas.setAttribute("aria-label", "Ownership after this round: " + el.textContent);
}}

// Founders' fully-diluted ownership BEFORE this round (pre-financing): the sum
// of founder common over the pre-financing fully-diluted total. The baseline
// the per-scenario delta is measured against.
function _preFounderFrac() {{
  const pre = DATA.pre_financing || {{}};
  const fd = pre.fully_diluted || 0;
  if (!fd) return null;
  const common = (DATA.founders || []).reduce((a, f) => a + (f.common_shares || 0), 0);
  return common / fd;
}}

// Founder-ownership delta vs today (pre-financing), shown under the founder
// card. Computed from the displayed founders fraction so it stays correct for
// both a saved scenario and a slider-modeled what-if.
function renderFounderDelta(foundersFrac) {{
  const el = document.getElementById("founder-delta");
  if (!el) return;
  const base = _preFounderFrac();
  if (foundersFrac == null || base == null) {{ el.textContent = ""; return; }}
  const d = (foundersFrac - base) * 100;
  const sign = d > 0 ? "+" : "";
  el.textContent = `${{sign}}${{d.toFixed(1)}} pts vs. today`;
}}

// Per-SAFE / per-note conversion detail tables (the <details> in the variable
// region). These depend on the round price, so they change with pre-money —
// shared by selectScenario + the slider so a drag keeps them in sync.
function instrumentDetailsHTML(perSafe, perNote) {{
  let out = "";
  if (perSafe && Object.keys(perSafe).length > 0) {{
    out += "<details><summary>Per-SAFE detail</summary><table><thead><tr><th>SAFE</th><th><span class='term' title='Which conversion rule applied — e.g. valuation cap, discount, or most-favored-nation'>How it converts</span></th><th class='num'>Shares</th><th class='num'>Price</th></tr></thead><tbody>";
    for (const [sid, r] of Object.entries(perSafe)) {{
      const shares = r.conversion_shares || r.cap_implied_shares || 0;
      const price = r.conversion_price || r.safe_price || 0;
      out += `<tr><td>${{escape(sid)}}</td><td>${{escape(r.branch)}}</td><td class="num">${{fmtShares(shares)}}</td><td class="num">$${{price.toFixed(4)}}</td></tr>`;
    }}
    out += "</tbody></table></details>";
  }}
  if (perNote && Object.keys(perNote).length > 0) {{
    out += "<details><summary>Per-note detail</summary><table><thead><tr><th>Note</th><th><span class='term' title='Which conversion rule applied — e.g. valuation cap, discount, or cash repayment at maturity'>How it converts</span></th><th class='num'>Shares / Cash</th></tr></thead><tbody>";
    for (const [nid, r] of Object.entries(perNote)) {{
      const val = r.conversion_shares !== undefined
        ? fmtShares(r.conversion_shares) + " shares"
        : (r.cash_repayment !== undefined ? fmtMoney(r.cash_repayment) : "—");
      out += `<tr><td>${{escape(nid)}}</td><td>${{escape(r.branch)}}</td><td class="num">${{val}}</td></tr>`;
    }}
    out += "</tbody></table></details>";
  }}
  return out;
}}

function show(id, on) {{ const el = document.getElementById(id); if (el) el.hidden = !on; }}

// Card mount animation (P3 / design §10-D): 200ms fade + 8px translate-Y.
// Reduced-motion and environments without the Web Animations API skip it.
function slideIn(el) {{
  if (_REDUCED_MOTION || !el || !el.animate) return;
  el.animate([{{ opacity: 0, transform: "translateY(8px)" }}, {{ opacity: 1, transform: "none" }}], {{ duration: 200, easing: "ease" }});
}}

function selectScenario(idx) {{
  _activeIdx = idx;
  document.querySelectorAll(".scenario-pill").forEach((b, i) => {{
    b.classList.toggle("active", i === idx);
    b.classList.toggle("pinned", i === _pinnedScenarioIdx);
  }});
  const s = DATA.scenarios[idx];
  const isFull = (s.completeness === "full" || s.completeness === "mixed");

  // Variable region (rebuilt each switch): heading + badge + type + blockers.
  let head = `<h2 style="margin-top:0;">${{escape(s.label)}} <span class="badge ${{s.completeness}}" title="${{escape(s.completeness)}}">${{escape(humanize("completeness", s.completeness))}}</span></h2>`;
  if (s.cap_implied_only) head += `<p class="meta">Pre-round snapshot — ${{CAP_IMPLIED_GLOSS}}</p>`;
  head += `<p class="meta">Type: ${{term("scenario_type", s.type)}}</p>`;
  document.getElementById("scenario-head").innerHTML = head;

  let blockers = "";
  if (s.blockers && s.blockers.length > 0) {{
    blockers = "<h3>What's blocking this scenario</h3>";
    for (const b of s.blockers) {{
      // Lead with the plain-language remedy a founder can act on; keep the raw
      // rule code + instance on a muted secondary line for counsel to cite.
      const where = b.instance_id ? " on " + escape(b.instance_id) : "";
      blockers += `<div class="blocker">${{escape(b.remedy)}}`
        + `<div class="blocker-code">${{escape(b.code)}}${{where}}</div></div>`;
    }}
  }}
  document.getElementById("scenario-blockers").innerHTML = blockers;

  // Persistent widgets (P0a): show + update in place for full/mixed, hide +
  // tear down otherwise. The canvas/sankey nodes survive the switch so P1/P2
  // can morph them in place; the metric nodes survive so the tickers tick in
  // place rather than against a freshly-rebuilt node.
  // The what-if slider only shows when this scenario IS the sweep base — its
  // frames model that scenario's pre-money axis; showing it on any other
  // scenario would describe a different round than the metric cards show.
  const sweepHere = isFull && _hasSweep && _isSweepBase(idx);
  exitModeled();  // a scenario switch always clears any modeled what-if state
  show("metric-row", isFull);
  show("sweep-wrap", sweepHere);
  if (sweepHere) resetSweepSlider();  // keep thumb in sync with the scenario
  show("graphics-row", isFull);
  show("legend-summary", isFull);
  if (isFull) {{
    const agg = s.aggregate || {{}};
    show("metric-price", !!s.equity_financing_price);
    show("metric-fd", !!s.post_round_fd);

    renderLegend(agg, s.post_round_fd);
    renderDonutSummary(agg, s.post_round_fd);
    renderFounderDelta(agg.founders_pct);
    _setDonutCenter(agg.founders_pct);

    // Impact callout persists, so it must be cleared+hidden when absent or a
    // stale "Founder Impact" from the prior scenario lingers.
    renderImpact(s.founder_impact && s.founder_impact.plain_language, true);

    // graphics-row is now visible — Chart.js needs the canvas sized before init.
    renderDonut(document.getElementById("donut-chart"), agg);
    renderSankey(document.getElementById("sankey"), s);
  }} else {{
    // No donut here — destroy the chart so it does not retain a hidden, stale
    // canvas, and hide the persistent impact callout.
    _destroyChart("donut-chart");
    document.getElementById("impact-callout").hidden = true;
  }}

  // Variable region: cap-implied table / pending notice / per-instrument details.
  let variable = "";
  // Structure-only scenarios show no priced-round metrics — offer a clear way
  // to jump to a modeled round when one exists.
  const _hasModeled = DATA.scenarios.some(x => x.completeness === "full" || x.completeness === "mixed");
  if (!isFull && _hasModeled) {{
    variable += `<div class="cta-card">`
      + `<div class="cta-title">No priced round yet</div>`
      + `<p class="meta" style="margin:0 0 12px;max-width:64ch;">This view shows only what each SAFE locks in from its valuation cap — there's no share price until a priced round sets one. Open a modeled round to see ownership, price, and dilution.</p>`
      + `<button class="btn primary" id="go-modeled">View a modeled round →</button></div>`;
  }}
  if (!isFull && s.cap_implied_only && Object.keys(s.per_safe || {{}}).length > 0) {{
    variable += `<h3>Pre-round ownership snapshot</h3><p class="meta">${{CAP_IMPLIED_GLOSS}}</p>`;
    variable += `<table><thead><tr><th>SAFE</th><th class="num"><span class="term" title="Ownership this SAFE locks in from its valuation cap, before a priced round sets a share price">Cap-implied %</span></th><th class="num"><span class="term" title="Effective price per share implied by the SAFE's valuation cap">Cap price</span></th><th class="num">Shares</th></tr></thead><tbody>`;
    for (const [sid, r] of Object.entries(s.per_safe)) {{
      variable += `<tr><td>${{escape(sid)}}</td><td class="num">${{pct(r.cap_implied_ownership || 0)}}</td><td class="num">$${{(r.safe_price || 0).toFixed(4)}}</td><td class="num">${{fmtShares(r.cap_implied_shares || 0)}}</td></tr>`;
    }}
    variable += `</tbody></table>`;
  }} else if (!isFull) {{
    variable += `<p class="meta"><em>This scenario is pending — see blockers above.</em></p>`;
  }}

  if (isFull) variable += instrumentDetailsHTML(s.per_safe, s.per_note);
  document.getElementById("scenario-variable").innerHTML = variable;
  const _gm = document.getElementById("go-modeled");
  if (_gm) _gm.addEventListener("click", () => selectScenario(firstModeledIdx()));

  // Animate the three hero metric numbers (P0 / design §10 number tickers).
  // Read `s.aggregate` directly — `agg` is block-scoped to the full/mixed
  // branch above and is out of scope here. Bump the generation first so any
  // in-flight tween from a prior scenario bails.
  _metricAnimGen++;
  const gen = _metricAnimGen;
  if (s.completeness === "full" || s.completeness === "mixed") {{
    const fp = (s.aggregate && s.aggregate.founders_pct) || 0;
    const introCapture = _CAPTURE && !_metricsIntroDone;
    animateMetric("founder-pct", introCapture ? 1.0 : _prevMetrics.founders_pct, fp, v => pct(v), gen);
    _prevMetrics.founders_pct = fp;
    // Gate price/shares on the same truthiness the metric-row template uses, so
    // the card and its animation appear together.
    if (s.equity_financing_price) {{
      animateMetric("price-psh", introCapture ? 0 : _prevMetrics.price, s.equity_financing_price, v => "$" + v.toFixed(4), gen);
      _prevMetrics.price = s.equity_financing_price;
    }}
    if (s.post_round_fd) {{
      animateMetric("post-fd", introCapture ? 0 : _prevMetrics.post_fd, s.post_round_fd, v => fmtShares(v), gen);
      _prevMetrics.post_fd = s.post_round_fd;
    }}
    _metricsIntroDone = true;
  }}

  // Compare banner + (if active) the two-up compare view
  updateCompareBanner();
  if (_compareMode) renderCompare();
}}

// ---------------------------------------------------------------------------
// True side-by-side compare — both donuts, both metric sets, and a verdict line.
// Uses the chart registry (separate canvas ids) so two donuts can be live together.
// ---------------------------------------------------------------------------
function _compareTargetIdx() {{
  // Prefer the pinned baseline (B); else the first modeled scenario != active.
  const modeled = i => {{ const s = DATA.scenarios[i]; return s && (s.completeness === "full" || s.completeness === "mixed"); }};
  if (_pinnedScenarioIdx !== null && _pinnedScenarioIdx !== _activeIdx && modeled(_pinnedScenarioIdx)) return _pinnedScenarioIdx;
  for (let i = 0; i < DATA.scenarios.length; i++) if (i !== _activeIdx && modeled(i)) return i;
  return -1;
}}

function _cmpRow(label, val) {{
  return `<tr><td style="color:var(--muted);">${{label}}</td><td class="num">${{val}}</td></tr>`;
}}

function renderCompare() {{
  const grid = document.getElementById("compare-grid");
  const verdict = document.getElementById("compare-verdict");
  const aIdx = _activeIdx, bIdx = _compareTargetIdx();
  if (bIdx === -1) {{
    grid.innerHTML = "<p class='meta'>Pick or pin a second fully-modeled scenario in the left rail to compare.</p>";
    verdict.hidden = true;
    return;
  }}
  const A = DATA.scenarios[aIdx], B = DATA.scenarios[bIdx];
  const fa = (A.aggregate && A.aggregate.founders_pct) || 0;
  const fb = (B.aggregate && B.aggregate.founders_pct) || 0;
  const base = _preFounderFrac();
  const cols = [
    {{ s: A, fp: fa, slot: "A", tag: "var(--lool-blue)", canvas: "cmp-donut-a", better: fa >= fb }},
    {{ s: B, fp: fb, slot: "B", tag: "var(--lool-azure)", canvas: "cmp-donut-b", better: fb > fa }},
  ];
  grid.innerHTML = cols.map(c => {{
    const s = c.s, fp = c.fp;
    const price = s.equity_financing_price != null ? "$" + s.equity_financing_price.toFixed(4) : "—";
    const fd = s.post_round_fd != null ? fmtShares(s.post_round_fd) : "—";
    const dil = base == null ? "—" : ((fp - base) * 100).toFixed(1) + " pts";
    return `<div class="compare-card${{c.better ? " better" : ""}}">
      <div style="margin-bottom:14px;"><span class="cmp-slot" style="background:${{c.tag}};">${{escape(c.slot)}}</span><strong>${{escape(s.label)}}</strong></div>
      <div style="display:flex;gap:18px;align-items:center;">
        <div class="cmp-canvas" style="width:120px;height:120px;flex:none;"><canvas id="${{c.canvas}}"></canvas><div class="cmp-center">${{pct(fp)}}</div></div>
        <table style="flex:1;"><tbody>
          ${{_cmpRow("Founders", "<strong>" + pct(fp) + "</strong>")}}
          ${{_cmpRow("Price/share", price)}}
          ${{_cmpRow("Shares after", fd)}}
          ${{_cmpRow("Dilution", `<span style="color:var(--lool-danger);">${{dil}}</span>`)}}
        </tbody></table>
      </div>
    </div>`;
  }}).join("");
  renderDonut(document.getElementById("cmp-donut-a"), A.aggregate || {{}}, false);
  renderDonut(document.getElementById("cmp-donut-b"), B.aggregate || {{}}, false);

  const better = fa >= fb ? A : B;
  const diff = Math.abs(fa - fb) * 100;
  verdict.innerHTML = `<strong>${{escape(better.label)}}</strong> keeps founders ${{diff.toFixed(1)}} points higher — ${{pct(Math.max(fa, fb))}} vs ${{pct(Math.min(fa, fb))}} fully diluted.`;
  verdict.hidden = false;
}}

function toggleCompare() {{
  _compareMode = !_compareMode;
  const lbl = document.getElementById("compare-label");
  if (lbl) lbl.textContent = _compareMode ? "Exit compare" : "Compare";
  document.getElementById("compare-toggle").classList.toggle("primary", _compareMode);
  show("scenario-view", !_compareMode);
  show("compare-view", _compareMode);
  show("compare-hint", _compareMode);
  if (_compareMode) {{
    renderCompare();
  }} else {{
    _destroyChart("cmp-donut-a");
    _destroyChart("cmp-donut-b");
  }}
}}

function updateCompareBanner() {{
  const banner = document.getElementById("compare-banner");
  if (_pinnedScenarioIdx === null || _pinnedScenarioIdx === _activeIdx) {{
    banner.style.display = "none";
    return;
  }}
  const pinned = DATA.scenarios[_pinnedScenarioIdx];
  const active = DATA.scenarios[_activeIdx];
  // Only meaningful when both scenarios have a real founder %; a cap-implied /
  // pending scenario has an empty aggregate, so comparing against 0% is noise.
  const pinnedHas = pinned.aggregate && pinned.aggregate.founders_pct;
  const activeHas = active.aggregate && active.aggregate.founders_pct;
  if (!pinnedHas || !activeHas) {{
    banner.style.display = "none";
    return;
  }}
  const pinnedF = pinned.aggregate.founders_pct * 100;
  const activeF = active.aggregate.founders_pct * 100;
  const rawDelta = activeF - pinnedF;
  const delta = rawDelta.toFixed(1);
  const sign = rawDelta >= 0 ? "+" : "";
  banner.style.display = "flex";
  banner.className = "compare-banner";
  slideIn(banner);
  banner.innerHTML = `<div>Compared to <strong>${{escape(pinned.label)}}</strong> (baseline): founder ownership is <strong>${{sign}}${{delta}} <span class="term" title="percentage points">pts</span></strong></div><button id="unpin-btn">Unpin baseline</button>`;
  document.getElementById("unpin-btn").addEventListener("click", () => {{
    _pinnedScenarioIdx = null;
    updateCompareBanner();
    document.querySelectorAll(".scenario-pill").forEach(p => p.classList.remove("pinned"));
  }});
}}

// Relevance tier for a counsel item, taken from the producer-supplied
// `relevance_tier`. Defaults to "general" when the producer hasn't scoped it —
// the client never invents a relevance it can't back.
const _TIER_ORDER = {{ applies: 0, likely: 1, general: 2 }};
const _TIER_META = {{
  applies: {{ cls: "rel-applies", label: "Applies here" }},
  likely:  {{ cls: "rel-likely",  label: "Likely relevant" }},
  general: {{ cls: "rel-general", label: "General" }},
}};
function _counselTier(it) {{
  const t = it.relevance_tier;
  return (t === "applies" || t === "likely") ? t : "general";
}}

function renderCounsel() {{
  const list = document.getElementById("counsel-list");
  if (!DATA.counsel_items || DATA.counsel_items.length === 0) {{
    list.innerHTML = "<p class='meta'><em>No counsel items.</em></p>";
    renderCounselCue(0);
    return;
  }}
  const items = DATA.counsel_items
    .map(it => ({{ ...it, _tier: _counselTier(it) }}))
    .sort((a, b) => _TIER_ORDER[a._tier] - _TIER_ORDER[b._tier]);
  const _n = items.length;
  // Items are sorted by relevance to this cap table, most relevant first. The
  // tiers reflect the instruments present, not the active scenario, so we keep
  // the framing cap-table-level rather than naming one scenario.
  let html = "<p style='font-size:12px;color:var(--muted);margin:0 0 12px;line-height:1.5;'>"
    + "Not legal advice. Showing the items most relevant to your cap table first — "
    + _n + (_n === 1 ? " question" : " questions") + " in all.</p>";
  for (const it of items) {{
    const meta = _TIER_META[it._tier];
    const links = it._links || [];
    html += `<div class="counsel-item">`;
    html += `<div class="ci-head"><span class="rel-badge ${{meta.cls}}">${{escape(meta.label)}}</span>`;
    if (it.applies_to) html += `<span class="ci-domain">${{escape(it.applies_to)}}</span>`;
    html += `</div>`;
    html += `<div class="ci-title">${{escape(it.title)}}</div>`;
    const q = it.counsel_question || it._summary;
    if (q) html += `<div class="ci-q">${{escape(q)}}</div>`;
    if (links.length) {{
      html += `<div class="ci-q" style="margin-top:6px;">Source: `
        + links.map(l => `<a href="${{escape(l[1])}}" target="_blank" rel="noopener noreferrer">${{escape(l[0])}}</a>`).join(" · ")
        + `</div>`;
    }}
    html += `<div class="counsel-code">${{escape(it.rule_id)}}</div>`;
    html += `</div>`;
  }}
  // Rule codes are hidden by default behind one rail-level toggle so the founder
  // view stays clean while counsel can still reveal and cite them.
  html += `<button class="codes-toggle no-print" id="codes-toggle">Show rule codes (for counsel)</button>`;
  list.innerHTML = html;
  document.getElementById("codes-toggle").addEventListener("click", () => {{
    const shown = list.classList.toggle("codes-shown");
    document.getElementById("codes-toggle").textContent =
      shown ? "Hide rule codes" : "Show rule codes (for counsel)";
  }});

  const appliesN = items.filter(it => it._tier === "applies").length;
  renderCounselCue(appliesN || _n);
}}

// Header "N for your lawyer" cue — counts items that apply to this cap table
// (falls back to the total count when no item is tagged as applying here).
function renderCounselCue(n) {{
  const cue = document.getElementById("counsel-cue");
  const label = document.getElementById("counsel-cue-label");
  if (!cue || !label) return;
  if (!n) {{ cue.hidden = true; return; }}
  label.textContent = n + " for your lawyer";
  cue.hidden = false;
}}

// ---------------------------------------------------------------------------
// Theme toggle
// ---------------------------------------------------------------------------
function toggleTheme() {{
  const current = document.body.dataset.theme || "light";
  const next = current === "light" ? "dark" : "light";
  document.body.dataset.theme = next;
  // Swap the SVG icon (sun ↔ moon) — no emoji in product chrome.
  const ico = document.getElementById("theme-ico");
  if (ico) {{
    ico.innerHTML = next === "dark"
      ? '<path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/>'
      : '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>';
  }}
  // Re-tint every live donut's border to the new --bg without re-animating.
  const bg = getComputedStyle(document.body).getPropertyValue("--bg");
  for (const id in _charts) {{
    _charts[id].data.datasets[0].borderColor = bg;
    _charts[id].update("none");
  }}
}}

// ---------------------------------------------------------------------------
// Walkthrough demo mode
// ---------------------------------------------------------------------------

function showToast(msg) {{
  const m = document.getElementById("wt-msg");
  if (m) m.textContent = msg;
  document.getElementById("toast").classList.add("visible");
}}

function hideToast() {{
  document.getElementById("toast").classList.remove("visible");
}}

// Controllable walkthrough — prev / play-pause / next over a three-state
// machine (idle | playing | paused) so a founder can read at their own pace.
let _wtState = "idle";
let _wtFrame = 0;
let _wtFrames = [];
const _WT_DURATION = 4500;

function _wtBuildFrames() {{
  const nCounsel = DATA.counsel_items.length;
  const counselMsg = nCounsel === 0
    ? "No counsel-review items were flagged for this cap table — still, run any financing past your lawyer."
    : `${{nCounsel}} counsel-review item${{nCounsel === 1 ? "" : "s"}} in the right rail — ${{nCounsel === 1 ? "a question" : "questions"}} for your lawyer, not legal advice.`;
  const start = firstModeledIdx();
  return [
    {{ msg: "Welcome — this is your cap-table explorer. The left rail shows the scenarios we modeled.", action: () => selectScenario(start) }},
    {{ msg: `${{DATA.scenarios[start]?.label || "Your round"}} — watch the donut and the before→after flow on the right.`, action: null }},
    ...DATA.scenarios.map((s, i) => ({{ msg: `Now: ${{s.label}} — see how ownership shifts.`, action: () => selectScenario(i) }})),
    {{ msg: counselMsg, action: null }},
    {{ msg: "Walkthrough complete. Click any scenario, or replay.", action: null }},
  ];
}}

function _wtRender() {{
  const f = _wtFrames[_wtFrame];
  if (!f) return;
  if (f.action) f.action();
  showToast(f.msg);
}}

function _wtClearTimer() {{
  if (_walkthroughTimer) {{ clearTimeout(_walkthroughTimer); _walkthroughTimer = null; }}
}}

function _wtSchedule() {{
  _wtClearTimer();
  if (_wtState !== "playing") return;
  _walkthroughTimer = setTimeout(() => {{
    if (_wtFrame < _wtFrames.length - 1) {{ _wtFrame++; _wtRender(); _wtSchedule(); }}
    else stopWalkthrough();
  }}, _WT_DURATION);
}}

function _wtSetPlayIcon(playing) {{
  const ico = document.getElementById("wt-pp-ico");
  const btn = document.getElementById("wt-playpause");
  if (ico) ico.innerHTML = playing
    ? '<rect x="6" y="5" width="4" height="14"/><rect x="14" y="5" width="4" height="14"/>'
    : '<path d="M8 5v14l11-7z"/>';
  if (btn) btn.setAttribute("title", playing ? "Pause" : "Play");
}}

function _wtSetWalkButton(active) {{
  const lbl = document.getElementById("walkthrough-label");
  if (lbl) lbl.textContent = active ? "Stop" : "Walkthrough";
  const ico = document.getElementById("walkthrough-ico");
  if (ico) ico.innerHTML = active ? '<rect x="6" y="6" width="12" height="12"/>' : '<path d="M8 5v14l11-7z"/>';
}}

function startWalkthrough() {{
  if (_wtState !== "idle") {{ stopWalkthrough(); return; }}
  _wtFrames = _wtBuildFrames();
  _wtFrame = 0;
  _wtState = "playing";
  _wtSetWalkButton(true);
  _wtSetPlayIcon(true);
  _wtRender();
  _wtSchedule();
}}

function stopWalkthrough() {{
  _wtClearTimer();
  _wtState = "idle";
  _wtSetWalkButton(false);
  hideToast();
}}

function _wtPlayPause() {{
  if (_wtState === "playing") {{ _wtState = "paused"; _wtClearTimer(); _wtSetPlayIcon(false); }}
  else if (_wtState === "paused") {{ _wtState = "playing"; _wtSetPlayIcon(true); _wtSchedule(); }}
}}

function _wtStep(delta) {{
  if (_wtState === "idle") return;
  _wtFrame = Math.max(0, Math.min(_wtFrames.length - 1, _wtFrame + delta));
  _wtRender();
  if (_wtState === "playing") _wtSchedule();  // restart the dwell timer
}}

// ---------------------------------------------------------------------------
// Pre-money sweep slider (P4)
// ---------------------------------------------------------------------------
// Scrubs precomputed real solver frames. The slider snaps to discrete frames,
// so every value it ever shows — number AND donut geometry — is real solver
// output. By default the donut SNAPS too (no fabricated in-between geometry);
// only under capture mode does the geometry tween.
function applySweepFrame(idx) {{
  const fr = DATA.sweep.frames[idx];
  const readout = document.getElementById("sweep-readout");
  if (!fr) return;
  enterModeled();  // a drag opts into the hypothetical — mark cards as modeled
  const preM = "$" + (fr.pre_money / 1e6).toFixed(1) + "M";
  const preEl = document.getElementById("sweep-pre-val");
  if (preEl) preEl.textContent = preM;
  if (!fr.valid) {{
    // Never show a stale (real-but-wrong) number for a non-converging frame.
    ["founder-pct", "price-psh", "post-fd"].forEach(id => {{
      const el = document.getElementById(id);
      if (el) el.textContent = "—";
    }});
    readout.textContent = "Pre-money " + preM + " — doesn't converge (frame skipped).";
    return;
  }}
  // Cancel any in-flight metric tween so the snapped value sticks.
  _metricAnimGen++;
  const agg = fr.aggregate || {{}};
  const fp = agg.founders_pct || 0;
  const fpEl = document.getElementById("founder-pct");
  if (fpEl) fpEl.textContent = pct(fp);
  const priceEl = document.getElementById("price-psh");
  if (priceEl && fr.equity_financing_price != null) priceEl.textContent = "$" + fr.equity_financing_price.toFixed(4);
  const fdEl = document.getElementById("post-fd");
  if (fdEl && fr.post_round_fd != null) fdEl.textContent = fmtShares(fr.post_round_fd);
  const canvas = document.getElementById("donut-chart");
  if (canvas) renderDonut(canvas, agg, _CAPTURE);  // snap unless capture
  renderLegend(agg, fr.post_round_fd);  // the per-class % + shares next to the pie
  renderDonutSummary(agg, fr.post_round_fd);  // keep the summary + donut aria fresh during a what-if
  renderFounderDelta(fp);  // delta vs today must track the modeled founders %
  _setDonutCenter(fp);  // donut-hole headline tracks the modeled founders %
  renderImpact(fr.impact_text, false);  // the Founder-Impact narrative for this frame
  const sankeyDiv = document.getElementById("sankey");
  if (sankeyDiv) {{
    // The dilution flow for this frame; snap (no fade) so a drag doesn't strobe.
    renderSankey(sankeyDiv, {{ shares_breakdown: fr.shares_breakdown, post_round_fd: fr.post_round_fd }}, true);
  }}
  // Per-SAFE/per-note conversion detail tables also move with the round price.
  document.getElementById("scenario-variable").innerHTML = instrumentDetailsHTML(fr.per_safe, fr.per_note);
  readout.textContent = "Pre-money " + preM + " → founders " + pct(fp);
}}

function _sweepAria(idx) {{
  const slider = document.getElementById("sweep-slider");
  const fr = DATA.sweep.frames[idx];
  if (!fr) return;
  const txt = "Pre-money $" + (fr.pre_money / 1e6).toFixed(1) + "M, founders "
    + (fr.valid && fr.aggregate ? pct(fr.aggregate.founders_pct || 0) : "not available");
  slider.setAttribute("aria-valuetext", txt);
}}

// Update only the slider's own readout/aria (NOT the metric cards), so the
// selected scenario's real numbers stay authoritative until the user drags.
function _sweepReadout(idx) {{
  const fr = DATA.sweep.frames[idx];
  const readout = document.getElementById("sweep-readout");
  if (!fr || !readout) return;
  const preM = "$" + (fr.pre_money / 1e6).toFixed(1) + "M";
  readout.textContent = fr.valid
    ? ("Drag to model — at " + preM + ", founders " + pct(fr.aggregate.founders_pct || 0))
    : ("Drag to model — " + preM + " doesn't converge");
}}

// Return the slider thumb to the middle frame and refresh its readout/aria.
// Called on every scenario change so the thumb never drifts out of sync with
// the displayed scenario.
function resetSweepSlider() {{
  if (!_hasSweep) return;
  const slider = document.getElementById("sweep-slider");
  const mid = Math.floor((DATA.sweep.frames.length - 1) / 2);
  slider.value = String(mid);
  const fr = DATA.sweep.frames[mid];
  const preEl = document.getElementById("sweep-pre-val");
  if (preEl && fr) preEl.textContent = "$" + (fr.pre_money / 1e6).toFixed(1) + "M";
  _sweepReadout(mid);
  _sweepAria(mid);
}}

function initSweep() {{
  const sw = DATA.sweep;
  if (!sw || !sw.frames || !sw.frames.some(f => f.valid)) return;
  _hasSweep = true;
  const slider = document.getElementById("sweep-slider");
  slider.max = String(sw.frames.length - 1);
  // Anchor the track ends with the min/max pre-money the frames span.
  const fmtM = v => "$" + (v / 1e6).toFixed(0) + "M";
  const lo = document.getElementById("sweep-end-lo");
  const hi = document.getElementById("sweep-end-hi");
  if (lo) lo.textContent = fmtM(sw.frames[0].pre_money);
  if (hi) hi.textContent = fmtM(sw.frames[sw.frames.length - 1].pre_money);
  slider.addEventListener("input", () => {{
    const idx = parseInt(slider.value);
    applySweepFrame(idx);  // drag = opt into the what-if; updates the cards
    _sweepAria(idx);
  }});
  // The initial scenario selection (called by renderScenarioList, after this)
  // sets the initial thumb + readout via resetSweepSlider.
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

// Export to PDF via the browser's print dialog.
document.getElementById("print-btn").addEventListener("click", () => window.print());

// Two-up side-by-side scenario compare.
document.getElementById("compare-toggle").addEventListener("click", toggleCompare);

// Walkthrough controls: prev / play-pause / next / end.
document.getElementById("wt-prev").addEventListener("click", () => _wtStep(-1));
document.getElementById("wt-next").addEventListener("click", () => _wtStep(1));
document.getElementById("wt-playpause").addEventListener("click", _wtPlayPause);
document.getElementById("wt-close").addEventListener("click", stopWalkthrough);

// Reset a modeled what-if back to the saved scenario.
document.getElementById("sweep-reset").addEventListener("click", () => selectScenario(_activeIdx));

// Header counsel cue: jump to the rail + brief highlight (keeps the rail
// reachable once it stacks below content on narrow screens).
document.getElementById("counsel-cue").addEventListener("click", () => {{
  const el = document.getElementById("counsel-rail");
  if (!el) return;
  const y = el.getBoundingClientRect().top + window.scrollY - 12;
  window.scrollTo({{ top: y, behavior: "smooth" }});
  if (el.animate) el.animate(
    [{{ boxShadow: "0 0 0 3px var(--lool-warning)" }}, {{ boxShadow: "0 0 0 0 transparent" }}],
    {{ duration: 1100, easing: "ease-out" }});
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

initSweep();
renderFoundersBlock();
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

    # sweep.json is optional — present only when a pre-money sweep was generated.
    sweep: dict[str, Any] | None = None
    sweep_path = os.path.join(args.dir, "sweep.json")
    if os.path.exists(sweep_path):
        with open(sweep_path, encoding="utf-8") as f:
            sweep = json.load(f)

    html_out = render_explorer_html(
        inputs=inputs,
        cap_state=cap_state,
        scenarios_doc=scenarios_doc,
        counsel_packet=counsel_packet,
        sweep=sweep,
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
