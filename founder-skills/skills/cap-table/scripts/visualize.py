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
import datetime
import html
import json
import os
import re
import sys
from collections.abc import Callable
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _labels  # noqa: E402
import _palette  # noqa: E402
import _rules  # noqa: E402
from _rule_pack import RULE_PACK_VERSION  # noqa: E402


def _rule_html(
    rule_id: str,
    *,
    item_title: str | None = None,
    item_source_ids: list[str] | None = None,
    compact: bool = False,
) -> str:
    """Readable rule reference: title → primary source (new tab), summary as a
    tooltip. Full form adds extra 'also' source links + the raw rule_id as
    small-print; `compact=True` (for dense tables) keeps just the linked title
    and folds the rule_id into the tooltip."""
    ref = _rules.rule_ref(rule_id, item_title=item_title, item_source_ids=item_source_ids)
    title = html.escape(str(ref["title"]), quote=True)
    summary = str(ref["summary"])
    tip = html.escape((f"{summary} · " if summary else "") + rule_id if compact else summary, quote=True)
    links = ref["links"]
    if links:
        primary = html.escape(str(links[0][1]), quote=True)
        out = f'<a href="{primary}" target="_blank" rel="noopener noreferrer" class="term" title="{tip}">{title} ↗</a>'
        if not compact and links[1:]:
            joined = " · ".join(
                f'<a href="{html.escape(str(u), quote=True)}" target="_blank" rel="noopener noreferrer">{html.escape(str(p), quote=True)} ↗</a>'
                for p, u in links[1:]
            )
            out += f' <span class="rule-extra">· also {joined}</span>'
    else:
        out = f'<span class="term" title="{tip}">{title}</span>' if tip else title
    if not compact:
        out += f' <code class="rule-code">{html.escape(str(rule_id), quote=True)}</code>'
    return out


_COUNSEL_DOMAIN_LABELS = {
    "safe": "SAFEs & Israeli tax",
    "israel_equity_tax": "Section 102 & equity tax",
    "israeli_ltd": "Israeli company administration",
    "israeli_aoa": "Articles of Association",
    "delaware_cross_border": "Cross-border structure",
    "delaware_flip": "Delaware flip",
    "convertible_notes": "Convertible notes",
    "anti_dilution": "Anti-dilution",
    "dual_class": "Dual-class shares",
    "option_pool": "Option pool",
    "warrants": "Warrants",
    "founder_benchmarks": "Founder benchmarks",
    "cap_table": "Cap table",
}


def counsel_domain_label(slug: str) -> str:
    return _COUNSEL_DOMAIN_LABELS.get(slug, slug.replace("_", " ").title())


# status value → (pill text, tint key). Covers every value _rules._wl_status
# can surface: current_status (legal/tax) AND freshness_status (benchmarks).
_STATUS_PILL = {
    "in_window": ("Active now", "success"),
    "pre_effective": ("Opens soon", "warning"),
    "missing_event_date": ("Needs a date", "warning"),
    "date_tracking_only": ("Tracking", "neutral"),
    "expired": ("Window passed", "faint"),
    "not_date_sensitive": ("—", "neutral"),
    "stale": ("Refresh data", "warning"),
    "fresh": ("Current", "neutral"),
    "unknown": ("Set a date", "warning"),
}
_PILL_TINT = {
    "success": ("var(--lool-success-tint)", "var(--lool-success)"),
    "warning": ("var(--lool-warning-tint)", "var(--lool-warning)"),
    "neutral": ("var(--lool-paper-2)", "var(--lool-subtle)"),
    "faint": ("var(--lool-paper-2)", "var(--lool-faint)"),
}


def watchlist_status_pill(status: str | None) -> str:
    text, tint = _STATUS_PILL.get(status or "", ((status or "").replace("_", " ") or "—", "neutral"))
    bg, fg = _PILL_TINT[tint]
    return f'<span class="pill" style="background:{bg};color:{fg};">{_esc(text)}</span>'


def _parse_iso(d: Any) -> datetime.date | None:
    try:
        return datetime.date.fromisoformat(str(d))
    except (ValueError, TypeError):
        return None


def watchlist_next_date(dates: list[str], status: str | None, as_of: str) -> str:
    """Single neutral date cell. The status pill carries Active/Opens/Passed;
    this just shows the relevant event date (no Opens/Until/Ended verbs, since
    the watchlist only carries trigger dates, not window boundaries)."""
    parsed = [p for p in (_parse_iso(d) for d in (dates or [])) if p is not None]
    if not parsed:
        return _rules.format_dates(dates) if dates else "—"
    ref = _parse_iso(as_of)
    if ref is None:
        return min(parsed).isoformat()
    future = [p for p in parsed if p >= ref]
    return (min(future) if future else max(parsed)).isoformat()


def counsel_item_html(item: dict[str, Any]) -> str:
    """Structured counsel block (mock layout): bold title, question, primary
    source link + secondary 'also' links, and the rule code as muted mono
    small-print. Reuses _rules.rule_ref for title/links."""
    ref = _rules.rule_ref(item["rule_id"], item_title=item.get("title"), item_source_ids=item.get("source_ids"))
    title = _esc(str(ref["title"]))
    question = _esc(item.get("counsel_question", ""))
    links = ref["links"]
    src_html = ""
    if links:
        primary_pub, primary_url = links[0]
        src_html = (
            f'<a href="{_esc(primary_url)}" target="_blank" rel="noopener noreferrer" '
            f'class="ci-src">{_esc(primary_pub)} ↗</a>'
        )
        if links[1:]:
            also = " · ".join(
                f'<a href="{_esc(u)}" target="_blank" rel="noopener noreferrer">{_esc(p)} ↗</a>' for p, u in links[1:]
            )
            src_html += f'<span class="ci-also">· also {also}</span>'
    code_html = f'<span class="ci-code">{_esc(item["rule_id"])}</span>'
    return (
        '<div class="ci">'
        f'<div class="ci-title">{title}</div>'
        f'<div class="ci-q">{question}</div>'
        f'<div class="ci-meta">{src_html}{code_html}</div>'
        "</div>"
    )


# Ownership-class colors live in the shared _palette module so the report and
# the explorer can't drift (design E3). Re-exported here because existing tests
# read visualize.PALETTE.
PALETTE = _palette.PALETTE

# Pre-AD / delta line-items that aggregate_ownership_by_class may carry. They
# are not ownership slices — render_donut/render_legend must exclude them so
# they neither draw a wedge nor double-encode the already-in-pp delta field.
EXCLUDED_OWNERSHIP_KEYS = {
    "founders_pct_pre_anti_dilution",
    "preferred_pct_pre_anti_dilution",
    "anti_dilution_delta_pct_points",
}


def _palette_color(cat: str) -> str:
    return _palette.slice_color(cat)


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


def _money_compact(m: float | None) -> str:
    """`_money` with a trailing `.00` stripped (so $18.00M → $18M) but real
    decimals kept ($18.50M stays). Used for comparison column labels."""
    return re.sub(r"\.00(?=[BMK]?$)", "", _money(m))


def _ordered_items(breakdown: dict[str, float], order: list[str]) -> list[tuple[str, float]]:
    """Walk `order` (bare class names) and emit (key, value) for each class
    present in `breakdown`, matching either the bare key or its `_pct` form.
    Keys absent from `order` are dropped (order lists every renderable class)."""
    items: list[tuple[str, float]] = []
    for name in order:
        if name in breakdown:
            items.append((name, breakdown[name]))
        elif f"{name}_pct" in breakdown:
            items.append((f"{name}_pct", breakdown[f"{name}_pct"]))
    return items


def render_donut(
    breakdown: dict[str, float],
    *,
    size: int = 200,
    center_value: str = "",
    center_label: str = "",
) -> str:
    """Inline SVG donut. `breakdown` maps class → fraction (0-1), keyed either
    bare (``founders``) or `_pct`-suffixed (``founders_pct``). Wedges are drawn
    at raw `frac × 360°` (no renormalization) so a wedge, its legend %, and the
    headline founder % are the same number; classes below EPS or in
    EXCLUDED_OWNERSHIP_KEYS are dropped. `center_value`/`center_label` print in
    the hole."""
    import math

    cx = cy = size / 2
    r_outer = size / 2 - 6
    r_inner = r_outer * 0.62

    slices = [
        (cat, frac)
        for cat, frac in _ordered_items(breakdown, _palette.ORDER_DONUT)
        if cat not in EXCLUDED_OWNERSHIP_KEYS and frac >= _palette.EPS
    ]

    paths: list[str] = []
    if not slices or sum(f for _, f in slices) <= 0:
        paths.append(f'<circle cx="{cx}" cy="{cy}" r="{r_outer}" fill="var(--lool-paper-2)"/>')
    else:
        start = -math.pi / 2  # 12 o'clock
        for cat, frac in slices:
            end = start + frac * 2 * math.pi  # raw frac, denominator 1.0
            x1, y1 = cx + r_outer * math.cos(start), cy + r_outer * math.sin(start)
            x2, y2 = cx + r_outer * math.cos(end), cy + r_outer * math.sin(end)
            large = 1 if (end - start) > math.pi else 0
            paths.append(
                f'<path d="M {cx} {cy} L {x1:.2f} {y1:.2f} '
                f'A {r_outer:.2f} {r_outer:.2f} 0 {large} 1 {x2:.2f} {y2:.2f} Z" '
                f'fill="{_palette.slice_color(cat)}"/>'
            )
            start = end

    # Hole (turns the pie into a donut)
    paths.append(f'<circle cx="{cx}" cy="{cy}" r="{r_inner:.2f}" fill="var(--lool-white)"/>')

    center = ""
    if center_value:
        center = (
            f'<text x="{cx}" y="{cy - 2:.2f}" text-anchor="middle" '
            f'font-size="{size * 0.16:.0f}" font-weight="700" '
            f'fill="var(--lool-blue)">{_esc(center_value)}</text>'
        )
        if center_label:
            center += (
                f'<text x="{cx}" y="{cy + size * 0.12:.2f}" text-anchor="middle" '
                f'font-size="{max(9, size * 0.07):.0f}" fill="var(--lool-mute)">'
                f"{_esc(center_label)}</text>"
            )
    return f'<svg width="{size}" height="{size}" viewBox="0 0 {size} {size}">{"".join(paths)}{center}</svg>'


def render_legend(breakdown: dict[str, float], *, fd: float | None = None) -> str:
    """Legend rows `swatch · Label · pct` (+ ` · N sh` when `fd` given). Plain
    class labels via _palette; classes below EPS or excluded are skipped; rows
    follow ORDER_LEGEND."""
    rows: list[str] = []
    for cat, frac in _ordered_items(breakdown, _palette.ORDER_LEGEND):
        if cat in EXCLUDED_OWNERSHIP_KEYS or frac < _palette.EPS:
            continue
        color = _palette.slice_color(cat)
        label = _esc(_palette.slice_label(cat))
        shares = ""
        if fd:
            shares = f'<span class="lg-sh">{int(round(frac * fd)):,} sh</span>'
        rows.append(
            '<li class="lg-row">'
            f'<span class="lg-sw" style="background:{color};"></span>'
            f'<span class="lg-label">{label}</span>'
            f'<span class="lg-pct">{_pct(frac)}</span>'
            f"{shares}</li>"
        )
    return f'<ul class="legend">{"".join(rows)}</ul>'


def _scenario_before_pct(cap_state: dict[str, Any]) -> float:
    """Founders-only 'today' fraction — same basis as _compute_founder_impact
    and the producer's founders_pct (excludes common_batches)."""
    ats = cap_state["as_converted_totals"]
    fd = ats.get("fully_diluted_shares") or 0
    f_shares = sum(int(f.get("common_shares", 0)) for f in cap_state.get("founders", []))
    return f_shares / fd if fd else 0.0


def _col_label(s: dict[str, Any]) -> str:
    p = s.get("parameters") or {}
    pre = p.get("pre_money", p.get("priced_round_pre_money"))
    raise_ = p.get("new_money", p.get("priced_round_new_money"))
    if pre is not None and raise_ is not None:
        return f"{_money_compact(pre)} pre · {_money_compact(raise_)}"
    return _esc(str(s.get("label", s.get("scenario_id", "Scenario"))))


def render_comparison_table(
    full_scenarios: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]],
    cap_state: dict[str, Any],
) -> str:
    """Comparison across ≥2 fully-modeled scenarios. Returns "" when <2.
    Columns = scenarios; rows = founders after / dilution vs today / price /
    shares. Missing fields render '—'; the max-founders_pct column is flagged
    'least dilutive'."""
    if len(full_scenarios) < 2:
        return ""

    before = _scenario_before_pct(cap_state)
    cols: list[dict[str, Any]] = []
    for s, co, agg in full_scenarios:
        after = agg.get("founders_pct")
        fi = co.get("founder_impact")
        if fi and fi.get("delta_pp") is not None:
            delta = fi["delta_pp"]
        elif after is not None:
            delta = (after - before) * 100
        else:
            delta = None
        cols.append(
            {
                "label": _col_label(s),
                "after": after,
                "delta": delta,
                "price": co.get("equity_financing_price"),
                "fd": co.get("post_round_fully_diluted_shares"),
            }
        )

    afters = [c["after"] for c in cols if c["after"] is not None]
    best_after = max(afters) if afters else None

    def _cell(v: str, *, best: bool) -> str:
        bg = ' style="background:rgba(47,138,86,0.07);"' if best else ""
        return f'<td class="num"{bg}>{v}</td>'

    head = '<th class="cmp-metric">Metric</th>'
    for c in cols:
        is_best = best_after is not None and c["after"] == best_after
        tag = '<span class="cmp-best">least dilutive</span>' if is_best else ""
        cls = " cmp-best-col" if is_best else ""
        head += f'<th class="num{cls}">{c["label"]}{tag}</th>'

    def _row(label: str, fmt: Callable[[dict[str, Any]], str]) -> str:
        cells = ""
        for c in cols:
            is_best = best_after is not None and c["after"] == best_after
            cells += _cell(fmt(c), best=is_best)
        return f'<tr><td class="cmp-metric">{label}</td>{cells}</tr>'

    rows = (
        _row("Founders after round", lambda c: _pct(c["after"]) if c["after"] is not None else "—")
        + _row("Dilution vs. today", lambda c: f"{c['delta']:.1f} pts" if c["delta"] is not None else "—")
        + _row("Price per share", lambda c: f"${c['price']:.2f}" if c["price"] is not None else "—")
        + _row("Shares after round", lambda c: f"{int(c['fd']):,}" if c["fd"] is not None else "—")
    )
    return f'<div class="cmp-wrap"><table class="cmp"><thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table></div>'


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
            donut = render_donut(agg_scalar, size=180)
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

    # Date-sensitive watchlist — deduped to one row per rule, slim columns.
    wl_groups = _rules.group_watchlist(rule_audit.get("date_sensitive_watchlist", []))
    if wl_groups:
        wl_row_list = []
        for g in wl_groups:
            count_badge = f' <span class="rule-extra">· {g["count"]}×</span>' if g["count"] > 1 else ""
            wl_row_list.append(
                "<tr>"
                f"<td>{_rule_html(g['rule_id'], item_title=g['title'], compact=True)}</td>"
                f"<td>{_labels.html_term('status', g['status'])}{count_badge}</td>"
                f'<td class="num">{_esc(_rules.format_dates(g["dates"]))}</td>'
                f"<td>{_esc(g['action'])}</td>"
                "</tr>"
            )
        watchlist_html = (
            "<h2>Date-sensitive watchlist</h2>"
            "<table><thead><tr><th>Rule</th><th>Status</th><th>When</th><th>Action</th></tr></thead>"
            f"<tbody>{''.join(wl_row_list)}</tbody></table>"
        )
    else:
        watchlist_html = "<h2>Date-sensitive watchlist</h2><p>No date-sensitive rules apply.</p>"

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
  {render_donut(pre_breakdown, size=180)}
  {render_legend(pre_breakdown)}
</div>
{voting_pct_html}
{aoa_findings_html}

<h2>Scenarios modeled</h2>
{"".join(scenario_cards)}

<h2>Counsel review required ({len(counsel_packet.get("items", []))} items)</h2>
{counsel_html or "<p>No counsel items.</p>"}

{watchlist_html}

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
