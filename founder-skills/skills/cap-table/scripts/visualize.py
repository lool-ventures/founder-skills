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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _labels  # noqa: E402
import _rules  # noqa: E402
from _rule_pack import RULE_PACK_VERSION  # noqa: E402


def _rule_html(rule_id: str, *, item_title: str | None = None, item_source_ids: list[str] | None = None) -> str:
    """Readable rule reference: title → primary source (new tab), summary as a
    tooltip, extra publishers as small 'also' links, raw rule_id as small-print."""
    ref = _rules.rule_ref(rule_id, item_title=item_title, item_source_ids=item_source_ids)
    title = html.escape(str(ref["title"]), quote=True)
    tip = html.escape(str(ref["summary"]), quote=True)
    links = ref["links"]
    if links:
        primary = html.escape(str(links[0][1]), quote=True)
        out = f'<a href="{primary}" target="_blank" rel="noopener noreferrer" class="term" title="{tip}">{title} ↗</a>'
        extras = links[1:]
        if extras:
            joined = " · ".join(
                f'<a href="{html.escape(str(u), quote=True)}" target="_blank" rel="noopener noreferrer">{html.escape(str(p), quote=True)} ↗</a>'
                for p, u in extras
            )
            out += f' <span class="rule-extra">· also {joined}</span>'
    else:
        out = f'<span class="term" title="{tip}">{title}</span>' if tip else title
    out += f' <code class="rule-code">{html.escape(str(rule_id), quote=True)}</code>'
    return out


# Color palette — see design §10
PALETTE = {
    "founders": "#0D549D",
    "preferred": "#365A8A",
    "option_pool": "#6CCDFF",
    "safe": "#21A2E3",
    "note": "#C9892B",
    "new_money": "#2F8A56",
    "warrants": "#48B4EA",
    "neutral": "#A6AEB5",
}

# Pre-AD / delta line-items that aggregate_ownership_by_class may carry. They
# are not ownership slices — render_donut/render_legend must exclude them so
# they neither draw a wedge nor double-encode the already-in-pp delta field.
EXCLUDED_OWNERSHIP_KEYS = {
    "founders_pct_pre_anti_dilution",
    "preferred_pct_pre_anti_dilution",
    "anti_dilution_delta_pct_points",
}


def _palette_color(cat: str) -> str:
    """Look up a slice color, tolerating the ``_pct`` suffix that
    aggregate_ownership_by_class keys carry (e.g. ``founders_pct``)."""
    return PALETTE.get(cat.removesuffix("_pct"), PALETTE["neutral"])


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

    slices = {k: v for k, v in breakdown.items() if k not in EXCLUDED_OWNERSHIP_KEYS}
    total = sum(slices.values())
    if total <= 0:
        return f'<svg width="{size}" height="{size}"><circle cx="{cx}" cy="{cy}" r="{r_outer}" fill="#F1F4F4"/></svg>'

    paths = []
    start_angle = -math.pi / 2  # 12 o'clock
    for cat, frac in slices.items():
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
        color = _palette_color(cat)
        d = (
            f"M {x1} {y1} A {r_outer} {r_outer} 0 {large_arc} 1 {x2} {y2} "
            f"L {x1i} {y1i} A {r_inner} {r_inner} 0 {large_arc} 0 {x2i} {y2i} Z"
        )
        paths.append(f'<path d="{d}" fill="{color}"/>')
        start_angle = end_angle

    label_svg = ""
    if label:
        label_svg = (
            f'<text x="{cx}" y="{cy + 5}" text-anchor="middle" font-size="12" fill="#374B65">{_esc(label)}</text>'
        )
    return f'<svg width="{size}" height="{size}">{"".join(paths)}{label_svg}</svg>'


def render_legend(breakdown: dict[str, float]) -> str:
    items = []
    for cat, frac in breakdown.items():
        # Skip the pre-AD / delta-pp fields here — they're rendered
        # separately by the scenario-card AD block (in render_report_html).
        # `_pct(frac)` multiplies by 100, which would double-encode the
        # already-in-pp anti_dilution_delta_pct_points field.
        if cat in EXCLUDED_OWNERSHIP_KEYS:
            continue
        color = _palette_color(cat)
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
            "warrants": cap_state["as_converted_totals"].get("warrants_underlying_total", 0) / fd,
        }
        if fd
        else {}
    )

    # Voting_pct per-holder table when dual-class (§6.5 HTML mirror).
    founders_list_v = cap_state.get("founders") or []
    common_batches_list_v = cap_state.get("common_batches") or []
    has_dual_class_v = any(float(f.get("voting_rights_multiple") or 1.0) != 1.0 for f in founders_list_v) or any(
        float(b.get("voting_rights_multiple") or 1.0) != 1.0 for b in common_batches_list_v
    )
    voting_pct_html = ""
    if has_dual_class_v:
        rows_v: list[tuple[str, str, int, float, float]] = []
        for f in founders_list_v:
            cls = f.get("common_class") or "class_a"
            vrm = float(f.get("voting_rights_multiple") or 1.0)
            shares = int(f.get("common_shares") or 0)
            rows_v.append((f.get("name", "Founder"), cls, shares, vrm, shares * vrm))
        for b in common_batches_list_v:
            cls = b.get("common_class") or "class_a"
            vrm = float(b.get("voting_rights_multiple") or 1.0)
            shares = int(b.get("shares") or 0)
            rows_v.append((f"Batch {b.get('batch_id') or b.get('holder_id', '?')}", cls, shares, vrm, shares * vrm))
        preferred_as_conv_v = int(cap_state["as_converted_totals"]["preferred_shares_as_converted"])
        if preferred_as_conv_v > 0:
            rows_v.append(
                ("Preferred (as-converted)", "preferred", preferred_as_conv_v, 1.0, float(preferred_as_conv_v))
            )
        total_voting_v = sum(r[4] for r in rows_v) or 1.0
        voting_rows_html = "".join(
            f"<tr><td>{_esc(n)}</td><td>{_esc(c)}</td><td class='num'>{s:,}</td>"
            f"<td class='num'>{vrm:g}× → {int(vu):,}</td>"
            f"<td class='num'>{_pct(vu / total_voting_v)}</td></tr>"
            for n, c, s, vrm, vu in rows_v
        )
        voting_pct_html = (
            "<h2>Voting power (dual-class)</h2>"
            "<p style='color:var(--muted);font-size:13px;'>Dual-class structure detected. Voting % = shares × voting_rights_multiple, normalized across all voting holders. "
            "Preferred treated as 1× per v0.5.0 simplification; see <code>dual_class.founder_super_voting</code> counsel item.</p>"
            "<table><thead><tr><th>Holder</th><th>Class</th><th>Shares</th><th>Voting units</th><th>Voting %</th></tr></thead>"
            f"<tbody>{voting_rows_html}</tbody></table>"
        )

    # AoA Findings section — rendered when aoa_findings has extracted data.
    aoa_v = cap_state.get("aoa_findings") or {}
    aoa_has_data_v = any(v is not None and v is not False for v in aoa_v.values())
    aoa_findings_html = ""
    if aoa_has_data_v:
        _aoa_v_map: list[tuple[str, str, str]] = [
            ("Pay-to-play detected", "pay_to_play_detected", "bool"),
            ("Drag-along threshold", "drag_along_threshold_pct", "pct"),
            ("§102 plan reference present", "section_102_plan_reference", "bool"),
            ("Ratchet anti-dilution detected", "ratchet_anti_dilution_detected", "bool"),
            ("Liquidation preference > 1x", "liquidation_preference_above_1x", "bool"),
            ("Participation present", "participation_present", "bool"),
            ("Dividend provisions present", "dividend_provisions_present", "bool"),
            ("Protective provisions below 75%", "protective_provisions_below_75_pct", "bool"),
            ("Bring-along threshold", "bring_along_threshold_pct", "pct"),
        ]
        aoa_rows_html = ""
        for label, key, fmt in _aoa_v_map:
            val = aoa_v.get(key)
            if val is None:
                rendered = "<em>Not extracted</em>"
            elif fmt == "bool":
                rendered = "Yes" if val else "No"
            elif fmt == "pct":
                rendered = f"{val}%"
            else:
                rendered = _esc(str(val))
            aoa_rows_html += f"<tr><td>{_esc(label)}</td><td>{rendered}</td></tr>"
        aoa_findings_html = (
            "<h2>Articles of Association — extracted findings</h2>"
            "<table><thead><tr><th>Finding</th><th>Value</th></tr></thead>"
            f"<tbody>{aoa_rows_html}</tbody></table>"
        )

    scenario_cards = []
    for s in scenarios:
        co = s["computed_outputs"]
        completeness = co.get("completeness", "structural_only")
        agg = co.get("aggregate_ownership_by_class") or {}
        if completeness in {"full", "mixed"} and agg:
            # agg contains a `founders_by_class` map sub-object; filter to
            # scalar pct values before passing to donut/legend so the SVG
            # math doesn't try to add a dict.
            agg_scalar = {k: v for k, v in agg.items() if isinstance(v, (int, float))}
            donut = render_donut(agg_scalar, size=180, label=_pct(agg.get("founders_pct", 0)))
            details = render_legend(agg_scalar)
            fi = co.get("founder_impact", {}) or {}
            impact_line = _esc(fi.get("plain_language", ""))
            # Render AD breakdown when present
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
                    '<p style="margin-top:8px;font-size:13px;color:var(--lool-slate);">'
                    + " | ".join(ad_summary_parts)
                    + "</p>"
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
                details += (
                    '<ul style="font-size:12px;color:var(--lool-mute);margin-top:6px;">'
                    + "".join(series_rows)
                    + "</ul>"
                )
        elif co.get("cap_implied_only") and co.get("per_safe"):
            # Cap-implied (pre-financing) — real per-SAFE ownership, NOT a blocked
            # scenario. Show the cap-implied table; ownership resolves at a priced round.
            donut = '<div style="width:180px;height:180px;display:flex;align-items:center;justify-content:center;background:var(--lool-paper-2);border-radius:50%;font-size:12px;color:var(--lool-mute);text-align:center;padding:0 10px;">Pre-round<br>snapshot</div>'
            rows = "".join(
                f'<tr><td>{_esc(sid)}</td><td class="num">{_pct(r.get("cap_implied_ownership", 0))}</td>'
                f'<td class="num">${float(r.get("safe_price") or 0):.4f}</td>'
                f'<td class="num">{int(r.get("cap_implied_shares") or 0):,}</td></tr>'
                for sid, r in co["per_safe"].items()
            )
            details = (
                f'<p style="font-size:13px;color:var(--lool-slate);">{_esc(_labels.CAP_IMPLIED_GLOSS)}</p>'
                '<table><thead><tr><th>SAFE</th><th class="num">Cap-implied %</th>'
                '<th class="num">Price</th><th class="num">Shares</th></tr></thead><tbody>' + rows + "</tbody></table>"
            )
            impact_line = ""
        else:
            donut = '<div style="width:180px;height:180px;display:flex;align-items:center;justify-content:center;background:var(--lool-paper-2);border-radius:50%;font-size:12px;color:var(--lool-mute);">Pending</div>'
            details = (
                "<em>No resolved ownership yet — see blockers below.</em>"
                if co.get("blockers")
                else "<em>No resolved ownership yet.</em>"
            )
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
      <p><strong>Type:</strong> {_labels.html_term("scenario_type", s["type"])} | <strong>Status:</strong> {_labels.html_term("completeness", completeness)}</p>
      {details}
      <p style="margin-top:10px;">{impact_line}</p>
      {blockers_html}
    </div>
  </div>
</div>
""")

    scripts_dir = os.path.dirname(os.path.abspath(__file__))
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    import _theme

    brand_css = _theme.brand_css()

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
                    f"<li><strong>{_rule_html(it['rule_id'], item_title=it.get('title'), item_source_ids=it.get('source_ids'))}</strong>"
                    f" — {_esc(it.get('counsel_question', ''))}</li>"
                )
            items_html.append("</ul>")
        counsel_html = "".join(items_html)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Cap Table — {company}</title>
<style>
{brand_css}
  :root {{
    --bg: var(--lool-white);
    --fg: var(--lool-ink);
    --muted: var(--lool-mute);
    --border: var(--lool-line-2);
    --accent: var(--lool-azure);
  }}
  body {{ font-family: var(--font-body);
         color: var(--fg); background: var(--bg); margin: 0; padding: 24px; line-height: 1.5;
         -webkit-font-smoothing: antialiased; -moz-osx-font-smoothing: grayscale; }}
  h1 {{ font-size: 32px; margin: 0 0 12px; font-weight: 400; color: var(--lool-blue); letter-spacing: -0.01em; }}
  h2 {{ font-size: 20px; margin: 32px 0 8px; font-weight: 500; color: var(--lool-royal);
        border-bottom: 1px solid var(--border); padding-bottom: 4px; }}
  h3 {{ font-size: 16px; margin: 16px 0 8px; font-weight: 500; color: var(--lool-royal); }}
  .header-row {{ display: flex; align-items: baseline; gap: 16px; flex-wrap: wrap; }}
  .meta {{ color: var(--muted); font-size: 14px; }}
  .card {{ border: 1px solid var(--lool-line-2); border-radius: 0; padding: 16px; margin: 12px 0;
           background: var(--lool-paper); }}
  .card-body {{ display: flex; gap: 20px; align-items: flex-start; }}
  code {{ background: var(--lool-paper-2); padding: 1px 4px; border-radius: var(--r-input);
          font-size: 0.9em; font-family: var(--font-mono); }}
  table {{ border-collapse: collapse; width: 100%; margin: 8px 0; font-size: 14px; }}
  th, td {{ border: 1px solid var(--lool-line-2); padding: 6px 10px; text-align: left; }}
  th {{ background: var(--lool-paper); }}
  .num {{ text-align: right; }}
  .term {{ border-bottom: 1px dotted var(--lool-line-2); cursor: help; }}
  .rule-code {{ font-size: 11px; color: var(--muted); }}
  .rule-extra {{ font-size: 11px; color: var(--muted); }}
  .footer {{ margin-top: 40px; font-size: 12px; color: var(--muted); border-top: 1px solid var(--lool-line-2); padding-top: 12px; }}
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
{voting_pct_html}
{aoa_findings_html}

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
            f"<tr><td>{_rule_html(w['rule_id'], item_title=w.get('title'))}</td><td>{_labels.html_term('scope', w.get('scope'))}</td>"
            f"<td>{_labels.html_term('status', w.get('current_status') or w.get('freshness_status'))}</td>"
            f"<td>{_esc(w.get('event_date_value') or '—')}</td></tr>"
            for w in rule_audit.get("date_sensitive_watchlist", [])
        )
    }
  </tbody>
</table>

<div class="footer">
  Report generated by cap-table skill. Rule pack v{RULE_PACK_VERSION}.
</div>
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
    print(
        json.dumps(
            {"ok": True, "path": out, "bytes": len(html_out.encode("utf-8"))},
            indent=2 if args.pretty else None,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
