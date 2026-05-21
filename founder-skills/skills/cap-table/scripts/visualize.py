#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Generate self-contained report.html from cap-table artifacts.

Inline SVG donut + ownership bars + scenario comparison. Vanilla HTML +
CSS variables for theming. No network requests. HTML-escapes every
user-controlled string per design doc §10 security contract.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import sys
from typing import Any

# Color palette — see design §10
PALETTE = {
    "founders": "#2563EB",
    "preferred": "#7C3AED",
    "option_pool": "#0891B2",
    "safe": "#DC2626",
    "note": "#EA580C",
    "new_money": "#059669",
    "neutral": "#6B7280",
}


def _esc(s: Any) -> str:
    """HTML-escape per design doc §10."""
    return html.escape(str(s) if s is not None else "", quote=True)


def _pct(p: float) -> str:
    return f"{p * 100:.1f}%"


def _money(m: float | None) -> str:
    if m is None:
        return "—"
    if abs(m) >= 1_000_000_000:
        return f"${m / 1_000_000_000:.2f}B"
    if abs(m) >= 1_000_000:
        return f"${m / 1_000_000:.2f}M"
    if abs(m) >= 1_000:
        return f"${m / 1_000:,.0f}K"
    return f"${m:,.0f}"


def render_donut(
    breakdown: dict[str, float],
    *,
    size: int = 200,
    label: str = "",
) -> str:
    """Render an SVG donut. `breakdown` maps category → percentage (0-1)."""
    cx = cy = size // 2
    r_outer = size // 2 - 10
    r_inner = r_outer - 30
    import math

    total = sum(breakdown.values())
    if total <= 0:
        return f'<svg width="{size}" height="{size}"><circle cx="{cx}" cy="{cy}" r="{r_outer}" fill="#eee"/></svg>'

    paths = []
    start_angle = -math.pi / 2  # 12 o'clock
    for cat, frac in breakdown.items():
        if frac <= 0:
            continue
        end_angle = start_angle + (frac / total) * 2 * math.pi
        x1 = cx + r_outer * math.cos(start_angle)
        y1 = cy + r_outer * math.sin(start_angle)
        x2 = cx + r_outer * math.cos(end_angle)
        y2 = cy + r_outer * math.sin(end_angle)
        x1i = cx + r_inner * math.cos(end_angle)
        y1i = cy + r_inner * math.sin(end_angle)
        x2i = cx + r_inner * math.cos(start_angle)
        y2i = cy + r_inner * math.sin(start_angle)
        large_arc = 1 if (end_angle - start_angle) > math.pi else 0
        color = PALETTE.get(cat, PALETTE["neutral"])
        d = (
            f"M {x1} {y1} A {r_outer} {r_outer} 0 {large_arc} 1 {x2} {y2} "
            f"L {x1i} {y1i} A {r_inner} {r_inner} 0 {large_arc} 0 {x2i} {y2i} Z"
        )
        paths.append(f'<path d="{d}" fill="{color}"/>')
        start_angle = end_angle

    label_svg = ""
    if label:
        label_svg = f'<text x="{cx}" y="{cy + 5}" text-anchor="middle" font-size="12" fill="#111">{_esc(label)}</text>'
    return f'<svg width="{size}" height="{size}">{"".join(paths)}{label_svg}</svg>'


def render_legend(breakdown: dict[str, float]) -> str:
    items = []
    for cat, frac in breakdown.items():
        # v0.4.8: skip the new pre-AD / delta-pp fields here — they're rendered
        # separately by the scenario-card AD block (in render_report_html).
        # `_pct(frac)` multiplies by 100, which would double-encode the
        # already-in-pp anti_dilution_delta_pct_points field.
        if cat in {
            "founders_pct_pre_anti_dilution",
            "preferred_pct_pre_anti_dilution",
            "anti_dilution_delta_pct_points",
        }:
            continue
        color = PALETTE.get(cat, PALETTE["neutral"])
        items.append(
            f'<li style="display:flex;align-items:center;gap:6px;font-size:12px;">'
            f'<span style="width:12px;height:12px;background:{color};display:inline-block;"></span>'
            f"{_esc(cat.replace('_', ' '))}: {_pct(frac)}</li>"
        )
    return f'<ul style="list-style:none;padding:0;margin:0;">{"".join(items)}</ul>'


def render_report_html(
    *,
    inputs: dict[str, Any],
    cap_state: dict[str, Any],
    scenarios_doc: dict[str, Any],
    rule_audit: dict[str, Any],
    counsel_packet: dict[str, Any],
) -> str:
    company = _esc(inputs.get("company_name", "Company"))
    scenarios = scenarios_doc.get("scenarios", [])
    fd = cap_state["as_converted_totals"]["fully_diluted_shares"]
    pre_breakdown = (
        {
            "founders": cap_state["as_converted_totals"]["common_shares"] / fd,
            "preferred": cap_state["as_converted_totals"]["preferred_shares_as_converted"] / fd,
            "option_pool": (
                cap_state["as_converted_totals"]["options_outstanding"]
                + cap_state["as_converted_totals"]["options_available"]
            )
            / fd,
        }
        if fd
        else {}
    )

    scenario_cards = []
    for s in scenarios:
        co = s["computed_outputs"]
        completeness = co.get("completeness", "structural_only")
        agg = co.get("aggregate_ownership_by_class") or {}
        if completeness in {"full", "mixed"} and agg:
            donut = render_donut(agg, size=180, label=_pct(agg.get("founders_pct", 0)))
            details = render_legend(agg)
            fi = co.get("founder_impact", {}) or {}
            impact_line = _esc(fi.get("plain_language", ""))
            # v0.4.0: render AD breakdown when present
            ad_bd = co.get("anti_dilution_breakdown") or []
            if ad_bd:
                pre_ad = agg.get("founders_pct_pre_anti_dilution")
                delta = agg.get("anti_dilution_delta_pct_points")
                ad_summary_parts = []
                if pre_ad is not None:
                    ad_summary_parts.append(f"<strong>Pre-AD baseline:</strong> {_pct(pre_ad)}")
                if delta is not None:
                    sign = "−" if delta < 0 else "+"
                    ad_summary_parts.append(f"<strong>AD impact:</strong> {sign}{abs(delta):.2f} pp")
                details += (
                    '<p style="margin-top:8px;font-size:13px;color:#374151;">' + " | ".join(ad_summary_parts) + "</p>"
                )
                # Per-series AD rows
                series_rows = []
                for bd in ad_bd:
                    sid = _esc(bd.get("series_id", "?"))
                    ptype = _esc(bd.get("protection_type", "?").replace("_", " "))
                    cb = bd.get("ccp_before", 0)
                    ca = bd.get("ccp_after", 0)
                    floor_note = " <em>(floor clamped)</em>" if bd.get("floor_applied") else ""
                    series_rows.append(f"<li>{sid} ({ptype}): CCP ${cb:.4f} → ${ca:.4f}{floor_note}</li>")
                details += '<ul style="font-size:12px;color:#4b5563;margin-top:6px;">' + "".join(series_rows) + "</ul>"
        else:
            donut = '<div style="width:180px;height:180px;display:flex;align-items:center;justify-content:center;background:#f3f4f6;border-radius:50%;font-size:12px;color:#6b7280;">Pending</div>'
            details = "<em>No resolved ownership yet — see blockers.</em>"
            impact_line = ""
        blockers_html = ""
        if co.get("blockers"):
            blockers_html = (
                "<ul>"
                + "".join(f"<li><code>{_esc(b['code'])}</code>: {_esc(b['remedy'])}</li>" for b in co["blockers"])
                + "</ul>"
            )
        scenario_cards.append(f"""
<div class="card">
  <h3>{_esc(s.get("label", s["scenario_id"]))}</h3>
  <div class="card-body">
    {donut}
    <div>
      <p><strong>Type:</strong> {_esc(s["type"])} | <strong>Completeness:</strong> <code>{_esc(completeness)}</code></p>
      {details}
      <p style="margin-top:10px;">{impact_line}</p>
      {blockers_html}
    </div>
  </div>
</div>
""")

    counsel_html = ""
    if counsel_packet.get("items"):
        items_html = []
        by_domain: dict[str, list[dict[str, Any]]] = {}
        for it in counsel_packet["items"]:
            by_domain.setdefault(it.get("domain", "other"), []).append(it)
        for domain in sorted(by_domain.keys()):
            items_html.append(f"<h3>{_esc(domain.replace('_', ' ').title())}</h3>")
            items_html.append("<ul>")
            for it in by_domain[domain]:
                items_html.append(
                    f"<li><strong>{_esc(it['title'])}</strong> "
                    f"(<code>{_esc(it['rule_id'])}</code>) — {_esc(it.get('counsel_question', ''))}</li>"
                )
            items_html.append("</ul>")
        counsel_html = "".join(items_html)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Cap Table — {company}</title>
<style>
  :root {{
    --bg: #ffffff;
    --fg: #111111;
    --muted: #6b7280;
    --border: #e5e7eb;
    --accent: #2563EB;
  }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, system-ui, sans-serif;
         color: var(--fg); background: var(--bg); margin: 0; padding: 24px; line-height: 1.5; }}
  h1 {{ font-size: 32px; margin: 0 0 12px; }}
  h2 {{ font-size: 20px; margin: 32px 0 8px; border-bottom: 1px solid var(--border); padding-bottom: 4px; }}
  h3 {{ font-size: 16px; margin: 16px 0 8px; }}
  .header-row {{ display: flex; align-items: baseline; gap: 16px; flex-wrap: wrap; }}
  .meta {{ color: var(--muted); font-size: 14px; }}
  .card {{ border: 1px solid var(--border); border-radius: 8px; padding: 16px; margin: 12px 0; }}
  .card-body {{ display: flex; gap: 20px; align-items: flex-start; }}
  code {{ background: #f3f4f6; padding: 1px 4px; border-radius: 3px; font-size: 0.9em; }}
  table {{ border-collapse: collapse; width: 100%; margin: 8px 0; font-size: 14px; }}
  th, td {{ border: 1px solid var(--border); padding: 6px 10px; text-align: left; }}
  th {{ background: #f9fafb; }}
  .num {{ text-align: right; }}
  .footer {{ margin-top: 40px; font-size: 12px; color: var(--muted); border-top: 1px solid var(--border); padding-top: 12px; }}
</style>
</head>
<body>
<div class="header-row">
  <h1>Cap Table — {company}</h1>
  <span class="meta">As of {_esc(cap_state.get("as_of_date", ""))}</span>
</div>

<h2>Current cap state (pre-financing)</h2>
<div class="card-body">
  {render_donut(pre_breakdown, size=180, label="current")}
  {render_legend(pre_breakdown)}
</div>

<h2>Scenarios modeled</h2>
{"".join(scenario_cards)}

<h2>Counsel review required ({len(counsel_packet.get("items", []))} items)</h2>
{counsel_html or "<p>No counsel items.</p>"}

<h2>Date-sensitive watchlist</h2>
<table>
  <thead><tr><th>Rule</th><th>Scope</th><th>Status / Freshness</th><th>Date</th></tr></thead>
  <tbody>
    {
        "".join(
            f"<tr><td><code>{_esc(w['rule_id'])}</code></td><td>{_esc(w['scope'])}</td>"
            f"<td>{_esc(w.get('current_status') or w.get('freshness_status') or '—')}</td>"
            f"<td>{_esc(w.get('event_date_value') or '—')}</td></tr>"
            for w in rule_audit.get("date_sensitive_watchlist", [])
        )
    }
  </tbody>
</table>

<div class="footer">
  Report generated by cap-table skill. Rule pack v0.2.8.
</div>
</body>
</html>
"""


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dir", required=True)
    p.add_argument("-o", "--output", required=True)
    args = p.parse_args()

    def _read(name: str) -> dict[str, Any]:
        with open(os.path.join(args.dir, name), encoding="utf-8") as f:
            return json.load(f)  # type: ignore[no-any-return]

    inputs = _read("inputs.json")
    cap_state = _read("cap_state.json")
    scenarios_doc = _read("scenarios.json")
    rule_audit = _read("rule_audit.json")
    counsel_packet = _read("counsel_packet.json")

    html_out = render_report_html(
        inputs=inputs,
        cap_state=cap_state,
        scenarios_doc=scenarios_doc,
        rule_audit=rule_audit,
        counsel_packet=counsel_packet,
    )

    out = os.path.abspath(args.output)
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(html_out)
    print(json.dumps({"ok": True, "path": out, "bytes": len(html_out.encode("utf-8"))}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
