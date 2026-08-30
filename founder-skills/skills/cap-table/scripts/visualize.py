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
import _confidence  # noqa: E402
import _labels  # noqa: E402
import _palette  # noqa: E402
import _rules  # noqa: E402
from _rule_pack import RULE_PACK_VERSION  # noqa: E402

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
    title = _esc(_rules.founder_text(str(ref["title"])))
    # The counsel question is the rule's raw `summary`, mapped straight across by rule_audit and
    # rendered below as a text node. Neither hop applied the founder-text policy.
    question = _esc(_rules.founder_text(str(item.get("counsel_question", ""))))
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


def _floor_note(b: dict) -> str:
    """The charter-floor clause for one AD breakdown row, with the magnitude the founder needs.

    Kept in step with `compose_report`'s markdown line: both render the number the solver already
    computed (`ccp_unfloored`) instead of the bare fact that a clamp happened, so the founder learns
    how much protection the floor cost rather than only that it exists. The isinstance guard is
    load-bearing -- `ccp_unfloored` is not in scenarios.schema.json's `required` list.
    """
    if not b.get("floor_applied"):
        return ""
    unfloored = b.get("ccp_unfloored")
    if isinstance(unfloored, (int, float)):
        return _esc(
            f" — the adjustment would have taken it to ${float(unfloored):.4f}; the floor in the charter stopped it there"
        )
    return " (limited by the charter's floor)"


def _esc(s: Any) -> str:
    """HTML-escape per design doc §10."""
    return html.escape(str(s) if s is not None else "", quote=True)


def _strip_md_markers(s: str) -> str:
    """Strip leading markdown blockquote/bold/italic markers from a disclosure banner string.

    Handles the two banner forms emitted by build_disclosure_banner:
      `> ⚠️ **text**` and `> ⚠️ **text** rest`
    Strips `> ` prefix, `**` bold markers, and lone `_` italic markers so the
    result reads as plain prose ready for HTML rendering.
    """
    s = s.strip()
    if s.startswith("> "):
        s = s[2:]
    s = s.replace("**", "").replace("_", "")
    return s.strip()


def _pct(p: float) -> str:
    return f"{p * 100:.1f}%"


def _batch_label(b: dict[str, Any]) -> str:
    """Display label for a common batch. Prefer an explicit holder_name (common_batches has no name
    field like founders[].name); otherwise fall back to the 'Batch <id>' form."""
    name = b.get("holder_name")
    if isinstance(name, str) and name.strip():
        return name
    return f"Batch {b.get('batch_id') or b.get('holder_id', '?')}"


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
        + _row("Dilution vs. today", lambda c: f"{c['delta']:+.1f} pts" if c["delta"] is not None else "—")
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
    disclosure_banner: str = "",
) -> str:
    company = _esc(inputs.get("company_name", "Company"))
    scenarios = scenarios_doc.get("scenarios", [])

    # Step 1: founders-only pre_breakdown + other_common slice
    ats = cap_state["as_converted_totals"]
    fd = ats.get("fully_diluted_shares") or 0
    founder_shares = sum(int(f.get("common_shares", 0)) for f in cap_state.get("founders", []))
    batch_shares = sum(int(b.get("shares", 0)) for b in cap_state.get("common_batches", []))
    pre_breakdown = (
        {
            "founders": founder_shares / fd,
            "other_common": batch_shares / fd,
            "preferred": ats["preferred_shares_as_converted"] / fd,
            "option_pool": (ats["options_outstanding"] + ats["options_available"]) / fd,
            "warrants": ats.get("warrants_underlying_total", 0) / fd,
        }
        if fd
        else {}
    )
    today_founder_pct = founder_shares / fd if fd else 0.0
    fd_total_str = f"{int(fd):,}" if fd else "—"
    as_of = cap_state.get("as_of_date", "")

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
            rows_v.append((_batch_label(b), cls, shares, vrm, shares * vrm))
        preferred_as_conv_v = int(ats["preferred_shares_as_converted"])
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
            "<p class='section-note'>Dual-class structure detected. Voting % = shares × voting_rights_multiple, normalized across all voting holders. "
            "Preferred treated as 1× per v0.5.0 simplification; see <code>dual_class.founder_super_voting</code> counsel item.</p>"
            '<table class="data"><thead><tr><th>Holder</th><th>Class</th><th>Shares</th><th>Voting units</th><th>Voting %</th></tr></thead>'
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
            '<table class="data"><thead><tr><th>Finding</th><th>Value</th></tr></thead>'
            f"<tbody>{aoa_rows_html}</tbody></table>"
        )

    # Step 2: classify scenarios into ordered buckets
    rich: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]] = []
    cap_implied: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    for s in scenarios:
        co = s.get("computed_outputs", {}) or {}
        completeness = co.get("completeness", "structural_only")
        agg = co.get("aggregate_ownership_by_class") or {}
        agg_scalar = {k: v for k, v in agg.items() if isinstance(v, (int, float))}
        if completeness in {"full", "mixed"} and agg_scalar:
            rich.append((s, co, agg_scalar))
        elif co.get("cap_implied_only") and co.get("per_safe"):
            cap_implied.append(s)
        else:
            pending.append(s)
    comparison_html = render_comparison_table(rich, cap_state)

    # Step 3: build cards in bucket order (rich → cap-implied → pending)
    scenario_cards: list[str] = []
    for s, co, agg_scalar in rich:
        donut = render_donut(agg_scalar, size=128, center_value=_pct(agg_scalar.get("founders_pct", 0)))
        legend = render_legend(agg_scalar)
        after = agg_scalar.get("founders_pct")
        fi = co.get("founder_impact") or {}
        if fi.get("delta_pp") is not None:
            delta_pp = fi["delta_pp"]
        elif after is not None:
            delta_pp = (after - _scenario_before_pct(cap_state)) * 100
        else:
            delta_pp = None
        delta_txt = f"{delta_pp:+.1f} pts" if delta_pp is not None else "—"
        price = co.get("equity_financing_price")
        price_txt = f"${price:.2f}" if price is not None else "—"
        fd_after = co.get("post_round_fully_diluted_shares")
        fd_txt = f"{int(fd_after):,}" if fd_after is not None else "—"
        impact = (
            _esc(fi.get("plain_language", ""))
            if fi.get("plain_language")
            else (
                f"Founders held {_pct(_scenario_before_pct(cap_state))} before; after, "
                f"{_pct(after) if after is not None else '—'} — {delta_txt}."
            )
        )
        ad_html = ""
        ad_bd = co.get("anti_dilution_breakdown") or []
        if ad_bd:
            pre_ad = agg_scalar.get("founders_pct_pre_anti_dilution")
            d = agg_scalar.get("anti_dilution_delta_pct_points")
            parts = []
            if pre_ad is not None:
                parts.append(f"Pre-AD baseline {_pct(pre_ad)}")
            if d is not None:
                parts.append(f"AD impact {'−' if d < 0 else '+'}{abs(d):.2f} pp")
            series = "".join(
                f"<li>{_esc(b.get('series_id', '?'))} "
                f"({_esc(str(b.get('protection_type', '?')).replace('_', ' '))}): "
                f"CCP ${b.get('ccp_before', 0):.4f} → ${b.get('ccp_after', 0):.4f}"
                f"{_floor_note(b)}</li>"
                for b in ad_bd
            )
            ad_html = f'<p class="ad-summary">{" | ".join(parts)}</p><ul class="ad-series">{series}</ul>'
        scenario_cards.append(f"""
<div class="card avoid-break">
  <div class="card-head">
    <h3>{_esc(s.get("label", s["scenario_id"]))}</h3>
    <span class="pill pill-ok">Fully modeled</span>
  </div>
  <div class="card-body">
    {donut}
    <div class="card-main">
      <div class="metric-trio">
        <div><div class="metric-n metric-blue">{_pct(after) if after is not None else "—"}</div><div class="metric-l">founders after · <span class="delta">{delta_txt}</span></div></div>
        <div><div class="metric-n">{price_txt}</div><div class="metric-l">price per share</div></div>
        <div><div class="metric-n">{fd_txt}</div><div class="metric-l">shares after round</div></div>
      </div>
      {legend}
    </div>
  </div>
  {ad_html}
  <p class="impact">{impact}</p>
</div>""")

    for s in cap_implied:
        co = s["computed_outputs"]
        rows = "".join(
            f'<tr><td>{_esc(sid)}</td><td class="num">{_pct(r.get("cap_implied_ownership", 0))}</td>'
            f'<td class="num">${float(r.get("safe_price") or 0):.4f}</td>'
            f'<td class="num">{int(r.get("cap_implied_shares") or 0):,}</td></tr>'
            for sid, r in co["per_safe"].items()
        )
        scenario_cards.append(f"""
<div class="card card-dashed avoid-break">
  <div class="card-head">
    <h3>{_esc(s.get("label", s["scenario_id"]))}</h3>
    <span class="pill pill-warn">Structure only</span>
  </div>
  <p class="gloss">{_esc(_labels.CAP_IMPLIED_GLOSS)}</p>
  <table class="data"><thead><tr><th>SAFE</th><th class="num">Cap-implied %</th>
    <th class="num">Price</th><th class="num">Shares</th></tr></thead><tbody>{rows}</tbody></table>
</div>""")

    for s in pending:
        co = s.get("computed_outputs", {}) or {}
        if co.get("blockers"):
            body = (
                "<ul class='blockers'>"
                + "".join(f"<li><code>{_esc(b['code'])}</code>: {_esc(b['remedy'])}</li>" for b in co["blockers"])
                + "</ul>"
            )
        else:
            body = "<p class='gloss'>No resolved ownership yet.</p>"
        scenario_cards.append(f"""
<div class="card avoid-break">
  <div class="card-head">
    <h3>{_esc(s.get("label", s["scenario_id"]))}</h3>
    <span class="pill">{_esc(_labels.humanize("completeness", co.get("completeness", "structural_only")))}</span>
  </div>
  {body}
</div>""")

    # Disclosure/divergence banner — rendered at top of report body when non-empty.
    # Strips markdown markers (> , **, _) so it reads as plain HTML prose.
    banner_html = ""
    if disclosure_banner:
        banner_text = _esc(_strip_md_markers(disclosure_banner))
        banner_html = (
            '<div class="disclosure-banner" '
            'style="background:var(--lool-warning-tint);border-left:4px solid var(--lool-warning);'
            "padding:14px 18px;border-radius:4px;margin-bottom:24px;font-size:14px;"
            'line-height:1.55;color:var(--lool-ink);">'
            f"{banner_text}</div>"
        )

    # R-5: cap-base confidence-tier banner, sourced directly from cap_state.warnings (independent of the
    # narrower disclosure_banner mechanism above, which is about acquisition-coverage, not base confidence).
    conf_warnings = _confidence.confidence_warnings(cap_state.get("warnings") or [])
    conf_tier = _confidence.confidence_tier(cap_state.get("warnings") or [])
    confidence_banner_html = ""
    if conf_warnings:
        import _warning_callouts

        conf_lines = [
            _strip_md_markers(line) for line in _warning_callouts.render_warning_callouts(conf_warnings) if line.strip()
        ]
        conf_text = _esc(" ".join(conf_lines))
        tint_var = "--lool-danger-tint" if conf_tier == "vacuous" else "--lool-warning-tint"
        border_var = "--lool-danger" if conf_tier == "vacuous" else "--lool-warning"
        confidence_banner_html = (
            f'<div class="confidence-banner confidence-banner-{conf_tier}" '
            f'style="background:var({tint_var});border-left:4px solid var({border_var});'
            "padding:14px 18px;border-radius:4px;margin-bottom:16px;font-size:14px;"
            f'line-height:1.55;color:var(--lool-ink);">{conf_text}</div>'
        )

    # SOLVER warnings -- a SEPARATE block from the confidence banner above, deliberately. Those are
    # cap_state's base-confidence strings; these are the priced-round solver's dicts. Folding them
    # into one tinted banner would give a warning that QUALIFIES a number the same visual severity
    # as one that says the base itself is untrustworthy. Text comes from the shared plaintext helper,
    # never `_strip_md_markers`, which deletes the underscores in an instrument id.
    import _warning_callouts as _wc

    solver_banner_html = ""
    _solver_lines = _wc.solver_callouts_plaintext(scenarios_doc.get("scenarios") or [])
    if _solver_lines:
        _items = "".join(f"<li>{_esc(line)}</li>" for line in _solver_lines)
        solver_banner_html = (
            '<div class="solver-warnings" style="background:var(--lool-warning-tint);'
            "border-left:4px solid var(--lool-warning);padding:12px 16px;border-radius:4px;"
            'margin-bottom:16px;font-size:13px;line-height:1.5;color:var(--lool-ink);">'
            '<ul style="margin:0;padding-left:18px;">' + _items + "</ul></div>"
        )

    scripts_dir = os.path.dirname(os.path.abspath(__file__))
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    import _theme

    brand_css = _theme.brand_css()

    # Step 4: counsel grouped by domain via counsel_item_html; watchlist 4-col
    counsel_items = counsel_packet.get("items", [])
    counsel_html = ""
    if counsel_items:
        by_domain: dict[str, list[dict[str, Any]]] = {}
        for it in counsel_items:
            by_domain.setdefault(it.get("domain", "other"), []).append(it)
        blocks = []
        for domain in sorted(by_domain):
            items_html = "".join(counsel_item_html(it) for it in by_domain[domain])
            blocks.append(
                f'<div class="ci-group avoid-break"><div class="ci-domain">'
                f"{_esc(counsel_domain_label(domain))}</div>{items_html}</div>"
            )
        counsel_html = "".join(blocks)

    wl_groups = _rules.group_watchlist(rule_audit.get("date_sensitive_watchlist", []))
    if wl_groups:
        wl_rows = "".join(
            "<tr>"
            f"<td>{_esc(g['title'])}</td>"
            f"<td>{watchlist_status_pill(g['status'])}</td>"
            f'<td class="num">{_esc(watchlist_next_date(g["dates"], g["status"], as_of))}</td>'
            f'<td class="wl-do">{_esc(g["action"])}</td>'
            "</tr>"
            for g in wl_groups
        )
        watchlist_html = (
            "<h2>Date-sensitive watchlist</h2>"
            '<p class="section-note">Rules with a time window — one row each.</p>'
            '<div class="cmp-wrap avoid-break"><table class="data"><thead><tr>'
            "<th>Rule</th><th>Status</th><th>Next date</th><th>What to do</th>"
            f"</tr></thead><tbody>{wl_rows}</tbody></table></div>"
        )
    else:
        watchlist_html = "<h2>Date-sensitive watchlist</h2><p>No date-sensitive rules apply.</p>"

    counsel_count = len(counsel_items)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Cap Table — {company}</title>
<style>
{brand_css}
  @page {{ size: A4; margin: 18mm 16mm 20mm; }}
  body {{ font-family: var(--font-body); color: var(--lool-ink); background: var(--lool-paper);
         margin: 0; padding: 40px 24px; line-height: 1.5; font-size: 15px;
         -webkit-font-smoothing: antialiased; -moz-osx-font-smoothing: grayscale; }}
  .doc-sheet {{ max-width: 820px; margin: 0 auto; background: var(--lool-white);
         box-shadow: var(--shadow-soft); padding: 56px 64px 48px; }}
  .topbar {{ max-width: 820px; margin: 0 auto 16px; display: flex; justify-content: flex-end; }}
  .printbtn {{ display: inline-flex; align-items: center; gap: 7px; padding: 8px 14px;
         border: 1px solid var(--lool-blue); border-radius: 4px; background: var(--lool-blue);
         color: #fff; font: 600 13px var(--font-body); cursor: pointer; }}
  h1 {{ font-family: var(--font-body); font-size: 34px; font-weight: 400; margin: 0;
         color: var(--lool-blue); letter-spacing: -0.01em; }}
  h2 {{ font-family: var(--font-body); font-size: 20px; font-weight: 500; color: var(--lool-royal);
         margin: 34px 0 10px; }}
  h3 {{ font-family: var(--font-body); font-size: 18px; font-weight: 500; color: var(--lool-ink); margin: 0; }}
  .eyebrow {{ font-size: 12px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.10em;
         color: var(--lool-subtle); margin-bottom: 8px; }}
  .title-row {{ display: flex; justify-content: space-between; align-items: flex-end; gap: 24px;
         border-bottom: 2px solid var(--lool-blue); padding-bottom: 18px; }}
  .title-meta {{ text-align: right; font-size: 13px; color: var(--lool-mute); line-height: 1.5; }}
  .section-note {{ font-size: 14px; color: var(--lool-mute); margin: 0 0 14px; }}
  .panel {{ display: flex; gap: 32px; align-items: center; padding: 22px 24px;
         border: 1px solid var(--lool-line); border-radius: 8px; }}
  .legend {{ list-style: none; padding: 0; margin: 0; flex: 1; }}
  .lg-row {{ display: flex; align-items: center; gap: 11px; padding: 7px 0;
         border-bottom: 1px solid var(--lool-paper-2); font-size: 15px; }}
  .lg-sw {{ width: 13px; height: 13px; border-radius: 3px; flex: none; }}
  .lg-label {{ flex: 1; color: var(--lool-ink); }}
  .lg-pct {{ font-variant-numeric: tabular-nums; font-weight: 700; min-width: 60px; text-align: right; }}
  .lg-sh {{ font-variant-numeric: tabular-nums; color: var(--lool-faint); min-width: 96px;
         text-align: right; font-size: 14px; }}
  .card {{ border: 1px solid var(--lool-line); border-radius: 8px; padding: 22px 24px; margin: 16px 0; }}
  .card-dashed {{ border-style: dashed; border-color: var(--lool-line-form); }}
  .card-head {{ display: flex; justify-content: space-between; align-items: baseline;
         gap: 16px; flex-wrap: wrap; margin-bottom: 16px; }}
  .card-body {{ display: flex; gap: 28px; align-items: center; }}
  .card-main {{ flex: 1; min-width: 0; }}
  .metric-trio {{ display: flex; gap: 28px; flex-wrap: wrap; margin-bottom: 14px; }}
  .metric-n {{ font-size: 30px; font-weight: 700; font-variant-numeric: tabular-nums;
         line-height: 1; color: var(--lool-ink); }}
  .metric-blue {{ color: var(--lool-blue); }}
  .metric-l {{ font-size: 12px; color: var(--lool-mute); margin-top: 4px; }}
  .delta {{ color: var(--lool-danger); font-weight: 600; }}
  .impact {{ font-size: 14px; line-height: 1.55; color: var(--lool-slate);
         margin: 16px 0 0; padding-top: 14px; border-top: 1px solid var(--lool-paper-2); }}
  .gloss {{ font-size: 13px; color: var(--lool-mute); margin: 0 0 12px; }}
  .blockers {{ margin: 8px 0 0; padding-left: 18px; font-size: 13px; color: var(--lool-mute); }}
  .pill {{ font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em;
         padding: 3px 11px; border-radius: 50px; background: var(--lool-paper-2); color: var(--lool-subtle); }}
  .pill-ok {{ background: var(--lool-success-tint); color: var(--lool-success); }}
  .pill-warn {{ background: var(--lool-warning-tint); color: var(--lool-warning); }}
  .pill-danger {{ background: var(--lool-danger-tint); color: var(--lool-danger); }}
  .panel-badge {{ position: absolute; top: 14px; right: 16px; }}
  .panel-vacuous, .panel-unverified {{ position: relative; }}
  .panel-unverified {{ border-color: var(--lool-warning); border-style: dashed;
         background: var(--lool-warning-tint); }}
  .panel-vacuous {{ border-color: var(--lool-danger); border-style: dashed;
         background: var(--lool-danger-tint); }}
  .donut-dim {{ filter: grayscale(0.85) opacity(0.55); }}
  table.data, table.cmp {{ border-collapse: collapse; width: 100%; font-size: 14px; }}
  table.data th, table.data td, table.cmp th, table.cmp td {{ padding: 10px 14px; text-align: left;
         border-top: 1px solid var(--lool-line); }}
  table.cmp thead th, table.data thead th {{ background: var(--lool-paper-2); color: var(--lool-subtle);
         font-size: 11px; text-transform: uppercase; letter-spacing: 0.06em; border-top: none; }}
  .cmp-wrap {{ border: 1px solid var(--lool-line); border-radius: 8px; overflow: hidden; margin: 8px 0; }}
  .num {{ text-align: right; font-variant-numeric: tabular-nums; }}
  th.num {{ text-align: right; }}
  .cmp-best {{ display: block; font-size: 10px; font-weight: 600; text-transform: uppercase;
         letter-spacing: 0.05em; color: var(--lool-success); margin-top: 2px; }}
  .cmp-metric {{ text-align: left; color: var(--lool-mute); }}
  .cmp-best-col {{ background: var(--lool-success-tint); }}
  .ci-group {{ margin-bottom: 20px; }}
  .ci-domain {{ font-size: 12px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.06em;
         color: var(--lool-azure-deep); margin-bottom: 8px; }}
  .ci {{ padding: 12px 0; border-top: 1px solid var(--lool-paper-2); }}
  .ci-title {{ font-size: 15px; font-weight: 600; color: var(--lool-ink); margin-bottom: 4px; line-height: 1.35; }}
  .ci-q {{ font-size: 14px; line-height: 1.55; color: var(--lool-mute); margin-bottom: 6px; }}
  .ci-meta {{ display: flex; gap: 14px; align-items: center; flex-wrap: wrap; }}
  .ci-src {{ font-size: 13px; color: var(--lool-azure-deep); text-decoration: none; font-weight: 500; }}
  .ci-also {{ font-size: 12px; color: var(--lool-mute); }}
  .ci-code {{ font-family: var(--font-mono); font-size: 10px; color: var(--lool-faint); }}
  .ad-summary {{ font-size: 13px; color: var(--lool-slate); margin: 14px 0 4px; }}
  .ad-series {{ font-size: 12px; color: var(--lool-mute); margin: 0; }}
  .wl-do {{ color: var(--lool-slate); font-size: 13px; line-height: 1.45; }}
  .footer {{ margin-top: 36px; padding-top: 14px; border-top: 1px solid var(--lool-line);
         display: flex; justify-content: space-between; flex-wrap: wrap; gap: 10px;
         font-size: 12px; color: var(--lool-subtle); }}
  code {{ background: var(--lool-paper-2); padding: 1px 4px; border-radius: 3px;
          font-size: 0.9em; font-family: var(--font-mono); }}
  .term {{ border-bottom: 1px dotted var(--lool-line); cursor: help; }}
  .rule-code {{ font-size: 11px; color: var(--lool-mute); }}
  .rule-extra {{ font-size: 11px; color: var(--lool-mute); }}
  @media print {{
    body {{ background: #fff; padding: 0; }}
    .doc-sheet {{ box-shadow: none; margin: 0; max-width: none; }}
    .screen-only {{ display: none !important; }}
    .avoid-break {{ break-inside: avoid; }}
    .pg-break {{ break-before: page; }}
  }}
</style>
</head>
<body>
<div class="topbar screen-only">
  <button class="printbtn" onclick="window.print()">Print / Save PDF</button>
</div>
<div class="doc-sheet">
  {confidence_banner_html}{solver_banner_html}{banner_html}<div class="title-row">
    <div>
      <div class="eyebrow">Cap table report</div>
      <h1>{company}</h1>
    </div>
    <div class="title-meta">As of {_esc(as_of)}<br>{fd_total_str} FD shares today</div>
  </div>

  <h2>Ownership today (pre-financing)</h2>
  <div class="panel avoid-break {f"panel-{conf_tier}" if conf_tier != "ok" else ""}">
    {f'<span class="pill pill-{"danger" if conf_tier == "vacuous" else "warn"} panel-badge">{_esc(_confidence.TIER_BADGE_TEXT[conf_tier])}</span>' if conf_tier != "ok" else ""}
    <div class="{"donut-dim" if conf_tier == "vacuous" else ""}">
      {render_donut(pre_breakdown, size=150, center_value=_pct(today_founder_pct), center_label="founders")}
    </div>
    {render_legend(pre_breakdown, fd=fd)}
  </div>
  {voting_pct_html}

  {f"<h2>Comparing the priced rounds</h2>{comparison_html}" if comparison_html else ""}

  <h2>Each scenario in detail</h2>
  {"".join(scenario_cards)}
  {aoa_findings_html}

  <h2 class="pg-break">Questions for your lawyer <span class="section-note" style="display:inline;">· {counsel_count} items</span></h2>
  <p class="section-note">Not legal advice — a checklist to raise with qualified counsel. Each item links to its primary source.</p>
  {counsel_html or "<p>No counsel items.</p>"}

  {watchlist_html}

  <div class="footer">
    <span>{company} · cap table report · generated {_esc(as_of)} · rule pack v{RULE_PACK_VERSION}</span>
    <span>founder-skills by lool ventures</span>
  </div>
</div>
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

    # disclosure_banner is an optional field in report.json written by compose_report.py.
    # Defensive: missing file, missing key, or malformed JSON → no banner, no crash.
    disclosure_banner = ""
    _report_json_path = os.path.join(args.dir, "report.json")
    if os.path.exists(_report_json_path):
        try:
            with open(_report_json_path, encoding="utf-8") as _f:
                _rj: dict[str, Any] = json.load(_f)
            disclosure_banner = _rj.get("disclosure_banner", "") or ""
        except Exception:
            pass

    html_out = render_report_html(
        inputs=inputs,
        cap_state=cap_state,
        scenarios_doc=scenarios_doc,
        rule_audit=rule_audit,
        counsel_packet=counsel_packet,
        disclosure_banner=disclosure_banner,
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
