#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
Generate an interactive HTML explorer for competitive positioning.

Outputs HTML (not JSON). Embeds Chart.js (vendored) for the interactive scatter
plot with view switching, bubble encoding controls, and company detail panels.

The 2D scatter, tables, and detail panels are fully self-contained (no network
access required). The OPTIONAL "3D View" tab is the one exception: it lazily
loads Plotly from a third-party CDN (cdn.plot.ly) on demand, so that single tab
requires network access. A graceful fallback card is shown if the CDN load
fails. Everything else works offline.

Usage:
    python explore.py --dir ./competitive-positioning-secureflow/
    python explore.py --dir ./competitive-positioning-secureflow/ -o explorer.html
"""

from __future__ import annotations

import argparse
import html
import json
import os
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, TypeGuard

# ---------------------------------------------------------------------------
# Artifact loading (same pattern as visualize.py, per PEP 723 convention)
# ---------------------------------------------------------------------------

_CORRUPT: dict[str, Any] = {"__corrupt__": True}

REQUIRED_ARTIFACTS = ["positioning.json", "landscape.json"]
OPTIONAL_ARTIFACTS = [
    "positioning_scores.json",
    "moat_scores.json",
    "product_profile.json",
    "report.json",
    "checklist.json",
]


# Optional artifacts another run wrote, in a folder that belongs to a run: read as absent (`main` sets this from
# `_run_ref.foreign_artifacts` when given --run-id; empty for a folder with no ref, and in-process callers).
_IGNORED_OTHER_RUN: set[str] = set()


def _load_artifact(dir_path: str, name: str) -> dict[str, Any] | None:
    if name in _IGNORED_OTHER_RUN:
        return None
    path = os.path.join(dir_path, name)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            loaded = json.load(f)
    except (json.JSONDecodeError, OSError):
        return _CORRUPT
    # Wrong-shape valid JSON (list/string/number) degrades to the corrupt path
    # rather than crashing downstream `.get()` access.
    if not isinstance(loaded, dict):
        return _CORRUPT
    return loaded


def _is_stub(data: dict[str, Any] | None) -> bool:
    return isinstance(data, dict) and data.get("skipped") is True


def _upload_names_for(dir_path: str, artifacts: dict[str, Any]) -> dict[str, str]:
    """{name as a cloud session stored an upload: the founder's name} for this page's run
    (`_cp_redteam_copy.upload_display`); empty when it cannot be told."""
    try:
        import _cp_redteam_copy

        run_id = _cp_redteam_copy.primary_run_id_in(dir_path, artifacts, REQUIRED_ARTIFACTS)
        return _cp_redteam_copy.upload_display(dir_path, run_id)
    except Exception:  # noqa: BLE001 - a display nicety must never stop the page
        return {}


def _humanized(data: Any, upload_names: dict[str, str]) -> Any:
    """`data` with the founder's file names as uploaded; a missing or corrupt artifact stays what it was."""
    if not upload_names or data is None or data is _CORRUPT:
        return data
    import _cp_redteam_copy

    return _cp_redteam_copy.humanize_tree(data, upload_names)


def _usable(data: dict[str, Any] | None) -> TypeGuard[dict[str, Any]]:
    return data is not None and data is not _CORRUPT and not _is_stub(data)


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _esc(text: Any) -> str:
    return html.escape(str(text), quote=True)


def _safe_json_embed(data: dict[str, Any]) -> str:
    """Serialize to JSON safe for embedding in <script> tags.

    Escapes </script>, </style>, and JS line separators to prevent
    premature tag closure or parse errors from untrusted strings.
    """
    raw = json.dumps(data, indent=2, default=str)
    # Prevent </script> or </style> inside string values from closing the tag
    raw = raw.replace("</", "<\\/")
    # Escape JS line separators that would break string literals
    raw = raw.replace("\u2028", "\\u2028")
    raw = raw.replace("\u2029", "\\u2029")
    return raw


# ---------------------------------------------------------------------------
# Data payload builder
# ---------------------------------------------------------------------------

_CATEGORY_COLORS: dict[str, str] = {
    "_startup": "#e11d48",
    "direct": "#0D549D",
    "adjacent": "#ea580c",
    "do_nothing": "#A6AEB5",
    "emerging": "#8b5cf6",
    "custom": "#14b8a6",
}

_DEFENSIBILITY_COLORS: dict[str, str] = {
    "high": "#2F8A56",
    "moderate": "#C9892B",
    "low": "#C0392B",
}


def _normalize_view_rationale(
    view: dict[str, Any], axis_compat: Any, scored_view: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Copy `view`, folding a resolved axis rationale back into the nested shape.

    The embedded JS reads view.x_axis.rationale / view.y_axis.rationale directly (no
    fallback logic client-side, by design). Some artifacts carry the rationale as a
    view-level sibling (x_axis_rationale) instead, because the dispatch templates used
    to instruct that shape. `axis_compat.axis_rationale()` resolves either shape server
    side; this folds the resolved value into the nested `rationale` key so the JS's
    single read path keeps working regardless of which shape the artifact used.

    `scored_view` (positioning_scores.json) WINS when it carries a rationale. `view` is the
    pre-scoring draft the main thread writes before the POSITIONING_SCORING dispatch runs, and its
    rationales are placeholders by design — reading it put `Placeholder — replaced by
    POSITIONING_SCORING dispatch` into founder-visible text. This mirrors the preference the
    `differentiation_claims` path in `_build_data_payload` already applies, for the same reason.
    Only the rationale is re-sourced: the draft remains authoritative for axis names and points,
    whose shapes differ between the two artifacts.
    """
    normalized = dict(view)
    for axis_key, axis_name in (("x_axis", "x"), ("y_axis", "y")):
        axis_val = normalized.get(axis_key)
        rationale = ""
        if isinstance(scored_view, dict):
            rationale = axis_compat.axis_rationale(scored_view, axis_name)
        if not rationale:
            if isinstance(axis_val, dict) and axis_val.get("rationale"):
                continue  # draft already nested and nothing scored to override it
            rationale = axis_compat.axis_rationale(view, axis_name)
        if not rationale:
            continue  # no shape on either artifact carries one — leave axis_val as-is
        axis_obj = dict(axis_val) if isinstance(axis_val, dict) else {}
        axis_obj["rationale"] = rationale
        normalized[axis_key] = axis_obj
    return normalized


def _build_data_payload(dir_path: str) -> dict[str, Any]:
    """Load all artifacts and assemble the explorer data payload."""
    scripts_dir = os.path.dirname(os.path.abspath(__file__))
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    import _axis_compat

    artifacts: dict[str, dict[str, Any] | None] = {}
    for name in REQUIRED_ARTIFACTS + OPTIONAL_ARTIFACTS:
        artifacts[name] = _load_artifact(dir_path, name)
    # Every string DATA carries, with the founder's file names as uploaded (`_upload_names_for`).
    upload_names = _upload_names_for(dir_path, artifacts)
    artifacts = {name: _humanized(data, upload_names) for name, data in artifacts.items()}

    positioning = artifacts["positioning.json"]
    landscape = artifacts["landscape.json"]
    moat_scores = artifacts.get("moat_scores.json")
    positioning_scores = artifacts.get("positioning_scores.json")
    product_profile = artifacts.get("product_profile.json")
    report = artifacts.get("report.json")

    # Company name
    company_name = "Unknown"
    if _usable(product_profile):
        company_name = str(product_profile.get("company_name", "Unknown"))
    elif _usable(report):
        md = _as_dict(report.get("metadata"))
        company_name = str(md.get("company_name", "Unknown"))

    # View scores keyed by view id. Built BEFORE the views themselves, because the scored view is the
    # authoritative source for a view's axis rationale — the draft carries a placeholder there.
    import _cp_view

    names = _cp_view.competitor_names(landscape if _usable(landscape) else None)
    view_scores_map: dict[str, dict[str, Any]] = {}
    if _usable(positioning_scores):
        for sv in _as_list(positioning_scores.get("views")):
            if isinstance(sv, dict):
                vid = str(sv.get("view_id", sv.get("id", "")))
                if vid:
                    # The same sentence report.md and report.html carry, computed here: the page
                    # shows it and does no geometry of its own. The score is not shown.
                    view_scores_map[vid] = {**sv, "where_you_stand": _cp_view.view_sentence(sv, names)}

    # Views with points
    views: list[dict[str, Any]] = []
    if _usable(positioning):
        for v in _as_list(positioning.get("views")):
            if isinstance(v, dict) and _as_list(v.get("points")):
                scored_v = view_scores_map.get(str(v.get("id", "")))
                views.append(_normalize_view_rationale(v, _axis_compat, scored_v))

    # Competitors from landscape
    competitors: list[dict[str, Any]] = []
    if _usable(landscape):
        competitors = [c for c in _as_list(landscape.get("competitors")) if isinstance(c, dict)]

    # Moat data per company
    company_moats: dict[str, dict[str, Any]] = {}
    if _usable(moat_scores):
        for slug, co_data in _as_dict(moat_scores.get("companies")).items():
            if isinstance(co_data, dict):
                company_moats[slug] = co_data

    # Differentiation claims — prefer the scored file, where the sub-agent's actual
    # stress-test verdicts land. positioning.json only carries the pre-scoring draft
    # (placeholder claims, written before POSITIONING_SCORING runs), so it's a fallback
    # for when the scored file is absent, unusable, or carries no claims.
    diff_claims: list[dict[str, Any]] = []
    if _usable(positioning_scores):
        diff_claims = [c for c in _as_list(positioning_scores.get("differentiation_claims")) if isinstance(c, dict)]
    if not diff_claims and _usable(positioning):
        diff_claims = [c for c in _as_list(positioning.get("differentiation_claims")) if isinstance(c, dict)]

    # Scoring basis — the declared convention for what the map coordinates represent
    # (shipped/verifiable surface vs. claimed/roadmap capability). Prefer the scored
    # file; fall back to positioning.json for the founder-override re-pipe path, which
    # writes positioning.json views back through the scorer and can carry it there too.
    # Absent must render as "not declared", never silently assumed to be "shipped" —
    # an artifact from before this convention existed has a genuinely undefined basis.
    scoring_basis: Any = None
    if _usable(positioning_scores) and "scoring_basis" in positioning_scores:
        scoring_basis = positioning_scores.get("scoring_basis")
    elif _usable(positioning) and "scoring_basis" in positioning:
        scoring_basis = positioning.get("scoring_basis")

    return {
        "company_name": company_name,
        # Competitor names from the landscape, so the page never labels a point by its slug.
        "display_names": names,
        "views": views,
        "view_scores": view_scores_map,
        "competitors": competitors,
        "company_moats": company_moats,
        "diff_claims": diff_claims,
        "scoring_basis": scoring_basis,
        "category_colors": _CATEGORY_COLORS,
        "defensibility_colors": _DEFENSIBILITY_COLORS,
    }


# ---------------------------------------------------------------------------
# HTML template
# ---------------------------------------------------------------------------

_VENDOR_DIR = Path(__file__).resolve().parent / "vendor"
_PLOTLY_CDN = "https://cdn.plot.ly/plotly-gl3d-2.35.2.min.js"


def _chartjs_source() -> str:
    """Return Chart.js source for inline embedding (no CDN)."""
    js_path = _VENDOR_DIR / "chart.min.js"
    return js_path.read_text(encoding="utf-8")


def _css() -> str:
    """The explorer's own styles, after the shared shell's (`_ui.UI_CSS` owns the body, the header card, sections,
    chips, pills and the checklist)."""
    return """
    [hidden] { display: none !important; }  /* the attribute wins over a class's display */
    .axes-bar { display: flex; flex-wrap: wrap; gap: 2rem; padding: 0.5rem 2rem; background: var(--lool-white);
                border-bottom: 1px solid var(--lool-line-2); font-size: 0.8rem; color: var(--lool-mute); }
    .cp-app { background: var(--lool-white); border: 1px solid var(--lool-line-2); margin-top: 1rem; }
    .toolbar { display: flex; flex-wrap: wrap; gap: 1rem; padding: 1rem 2rem;
               background: var(--lool-white); border-bottom: 1px solid var(--lool-line-2);
               align-items: center; }
    .toolbar label { font-size: 0.8rem; color: var(--lool-nav); font-weight: 500; max-width: 100%; min-width: 0; }
    .toolbar select { font-size: 0.8rem; padding: 4px 8px; border: 1px solid var(--lool-line-form);
                      border-radius: var(--r-input); background: var(--lool-white);
                      font-family: var(--font-body); color: var(--lool-ink); max-width: 100%; }
    .main { display: flex; gap: 0; height: max(520px, calc(100vh - 120px)); overflow: hidden; }
    .chart-area { flex: 1; padding: 1rem 1.5rem; min-width: 0; display: flex;
                  flex-direction: column; overflow-y: auto; }
    /* Chart.js sizes the canvas to this box; a canvas sized by flex instead drew stretched bubbles. */
    .chart-canvas { position: relative; flex: none; height: clamp(320px, 62vh, 600px); }
    .sidebar { width: 320px; border-left: 1px solid var(--lool-line-2); background: var(--lool-paper);
               overflow-y: auto; padding: 1rem; }
    .sidebar h3 { font-size: 0.85rem; font-weight: 500; color: var(--lool-royal);
                  margin-bottom: 0.5rem; padding-bottom: 0.25rem;
                  border-bottom: 1px solid var(--lool-line-2); }
    .company-item { padding: 0.5rem; border-radius: var(--r-input); cursor: pointer; font-size: 0.8rem;
                    display: flex; align-items: center; gap: 8px; transition: background 0.15s; }
    .company-item:hover { background: var(--lool-paper-2); }
    .company-item.dimmed { opacity: 0.4; }
    .company-item .dot { width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; }
    .company-item .name { font-weight: 500; }
    .company-item .cat { font-size: 0.7rem; color: var(--lool-faint); }
    .detail-panel { margin-top: 1rem; }
    .detail-panel h4 { font-size: 0.85rem; color: var(--lool-blue); margin-bottom: 0.5rem; }
    .detail-row { display: flex; justify-content: space-between; font-size: 0.75rem;
                  padding: 0.25rem 0; border-bottom: 1px solid var(--lool-line-2); }
    .detail-row .label { color: var(--lool-mute); }
    .detail-row .value { color: var(--lool-ink); font-weight: 500; }
    .badge { display: inline-block; padding: 2px 8px; border-radius: var(--r-pill);
             font-size: 0.7rem; font-weight: 600; color: #fff; }
    .legend-bar { display: flex; flex-wrap: wrap; gap: 1rem; padding: 0.75rem 2rem;
                  background: var(--lool-white); border-bottom: 1px solid var(--lool-line-2);
                  font-size: 0.75rem; }
    .legend-item { display: flex; align-items: center; gap: 4px; }
    .legend-dot { width: 10px; height: 10px; border-radius: 50%; }
    .placeholder { padding: 3rem; text-align: center; color: var(--lool-faint); font-size: 0.9rem; }
    .tab-bar { display: flex; flex-wrap: wrap; gap: 0; background: var(--lool-white);
               border-bottom: 1px solid var(--lool-line-2); }
    .tab-list { display: flex; }
    .cp-app a.tab { text-decoration: none; color: var(--lool-nav); }  /* reads as a tab, not a link */
    .cp-app a.tab:hover { color: var(--lool-blue); }
    .tab { padding: 0.5rem 1.5rem; font-size: 0.85rem; cursor: pointer; border: none;
           background: none; color: var(--lool-nav); border-bottom: 2px solid transparent;
           font-family: var(--font-body); }
    .tab:hover { color: var(--lool-blue); }
    .tab.active { color: var(--lool-blue); border-bottom-color: var(--lool-azure); font-weight: 600; }
    .tab:disabled { color: var(--lool-faint); cursor: not-allowed; }
    .tab-panel { display: none; }
    .tab-panel.active { display: block; }
    #chart-3d-container { width: 100%; height: calc(100vh - 100px); min-height: 400px; }
    .spinner { display: inline-block; width: 20px; height: 20px; border: 2px solid var(--lool-line-2);
               border-top-color: var(--lool-blue); border-radius: 50%;
               animation: spin 0.6s linear infinite; }
    @keyframes spin { to { transform: rotate(360deg); } }
    .not-scored { font-size: 0.7rem; color: var(--lool-faint); font-style: italic; }
    .axis-rationale {
        font-size: 0.75rem; color: var(--lool-mute); background: var(--lool-paper);
        border: 1px solid var(--lool-line-2);
        padding: 0.75rem; margin-top: 0.5rem; line-height: 1.5;
    }
    .axis-rationale strong { color: var(--lool-slate); }
    .view-score-panel {
        font-size: 0.75rem; color: var(--lool-mute); background: var(--lool-paper);
        border: 1px solid var(--lool-line-2);
        padding: 0.75rem; margin-top: 0.5rem; line-height: 1.6;
    }
    .view-score-panel strong { color: var(--lool-slate); }
    .view-score-panel .vanity-flag { color: var(--lool-warning); font-style: italic; margin-top: 2px; }
    .claim-card {
        background: var(--lool-paper); border: 1px solid var(--lool-line-2);
        border-radius: var(--r-input); padding: 0.6rem 0.75rem; margin-bottom: 0.5rem;
        font-size: 0.75rem; line-height: 1.5;
    }
    .claim-card .claim-text { font-weight: 500; color: var(--lool-ink); margin-bottom: 0.25rem; }
    .claim-card strong { color: var(--lool-slate); }
    .verdict-badge {
        display: inline-block; padding: 1px 8px; border-radius: var(--r-pill);
        font-size: 0.65rem; font-weight: 600; color: #fff;
    }
    .scoring-basis-caption { font-size: 0.75rem; color: var(--lool-mute);
        padding: 0.5rem 2rem; background: var(--lool-paper);
        border-bottom: 1px solid var(--lool-line-2); }
    .scoring-basis-caption strong { color: var(--lool-slate); }
    @media (max-width: 768px) {
      .main { flex-direction: column; height: auto; overflow: visible; }  /* the sidebar below, never cut off */
      .chart-canvas { height: 320px; }
      .sidebar { width: 100%; border-left: none; border-top: 1px solid var(--lool-line-2); }
      .toolbar { flex-direction: column; }
    }
    @media print {
      .toolbar, .tab-bar, .sidebar { display: none; }
      .main { display: block; }
    }
    """


# The header card and the checklist, as report.html builds them (the page-structure tests hold the two pages to
# the same ring and the same rows). Copied rather than imported: the test suite imports every skill's
# `visualize` into one process, so a second import by that name would be another skill's.
_BAND_TONE = {"strong": "pass", "solid": "pass", "needs_work": "warn", "major_revision": "fail"}
_DEFENSIBILITY_TONE = {"high": "pass", "moderate": "warn", "low": "fail"}
_CHECKLIST_SUMMARY = (
    "Score = (pass + half credit per warn) ÷ applicable. It measures how complete and well-evidenced this "
    "analysis is, not how strong the company's position is."
)


def _score_ring(checklist: dict[str, Any] | None, linked: bool = True) -> str:
    import _cp_view
    import _ui

    if not _usable(checklist):
        return ""
    summary = _as_dict(checklist.get("summary"))
    raw = summary.get("score_pct")
    if not isinstance(raw, (int, float)) or isinstance(raw, bool):
        return ""
    band = str(summary.get("overall_status") or "")
    band_text = band.replace("_", " ").title() if band in _BAND_TONE else ""
    shown = _cp_view.score_text(raw)
    return _ui.score_ring(
        float(raw),
        tone=_BAND_TONE.get(band, "neutral"),
        value_text=f"{shown}%",
        label="Analysis quality",
        caption=band_text,
        aria_label=f"Analysis quality {shown} percent" + (f", {band_text}" if band_text else ""),
        href="#checklist" if linked else None,
    )


def _header(
    report: dict[str, Any] | None,
    moat_scores: dict[str, Any] | None,
    checklist: dict[str, Any] | None,
    verdict_text: str | None,
    company_name: str,
) -> str:
    import _ui

    date = str(_as_dict(report.get("metadata")).get("analysis_date", "")) if _usable(report) else ""
    chips: list[str] = []
    if date:
        chips.append(f'<span class="ui-chip">{_esc(date)}</span>')
    if _usable(moat_scores):
        startup = _as_dict(_as_dict(moat_scores.get("companies")).get("_startup"))
        defensibility = str(startup.get("overall_defensibility", "")).lower()
        tone = _DEFENSIBILITY_TONE.get(defensibility)
        if tone:
            chips.append(
                f'<span class="ui-pill ui-pill--{tone}" data-tone="{tone}">'
                f"Defensibility: {_esc(defensibility.title())}</span>"
            )
    return _ui.header_card(
        eyebrow="Competitive explorer",
        title=company_name,
        meta_html=" ".join(chips),
        verdict_html=_esc(verdict_text) if verdict_text else "",
        ring_html=_score_ring(checklist, linked=bool(_checklist_section(checklist))),
    )


def _checklist_section(checklist: dict[str, Any] | None) -> str:
    """The analysis checklist, server-rendered outside the tab panels (visible with scripts off) and never in
    `DATA`: the same rows report.md and report.html show."""
    import _cp_view
    import _ui

    if not _usable(checklist):
        return ""
    groups = _cp_view.checklist_groups(checklist)
    if not groups:
        return ""
    return (
        '<section class="ui-section" id="checklist" aria-labelledby="checklist-h">'
        '<h2 id="checklist-h">Analysis Checklist</h2>'
        f"{_ui.checklist(groups, summary_html=_esc(_CHECKLIST_SUMMARY))}</section>"
    )


def compose_explorer(dir_path: str) -> str:
    """Build the full interactive explorer HTML."""
    scripts_dir = os.path.dirname(os.path.abspath(__file__))
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    import _theme

    brand_css = _theme.brand_css()
    import _ui

    payload = _build_data_payload(dir_path)
    data_json = _safe_json_embed(payload)
    company_name = _esc(payload["company_name"])
    # The report's own verdict paragraph, the same words report.md opens with. Rendered here, not
    # embedded in DATA: the page's script has no use for it.
    import _cp_view

    upload_names = _upload_names_for(
        dir_path, {name: _load_artifact(dir_path, name) for name in REQUIRED_ARTIFACTS + OPTIONAL_ARTIFACTS}
    )
    report = _humanized(_load_artifact(dir_path, "report.json"), upload_names)
    moat_scores = _humanized(_load_artifact(dir_path, "moat_scores.json"), upload_names)
    checklist = _humanized(_load_artifact(dir_path, "checklist.json"), upload_names)
    verdict_text = _cp_view.report_verdict(
        report, _humanized(_load_artifact(dir_path, "positioning_scores.json"), upload_names), moat_scores
    )
    header = _header(report, moat_scores, checklist, verdict_text, payload["company_name"])
    checklist_section = _checklist_section(checklist)
    checklist_tab = '  <a class="tab" href="#checklist">Checklist</a>\n' if checklist_section else ""

    # Build legend bar
    legend_parts: list[str] = []
    for label, color in [
        (company_name if payload["company_name"] != "Unknown" else "This company", _CATEGORY_COLORS["_startup"]),
        ("Direct", _CATEGORY_COLORS["direct"]),
        ("Adjacent", _CATEGORY_COLORS["adjacent"]),
        ("Do Nothing", _CATEGORY_COLORS["do_nothing"]),
        ("Emerging", _CATEGORY_COLORS["emerging"]),
        ("Custom", _CATEGORY_COLORS["custom"]),
    ]:
        legend_parts.append(
            f'<span class="legend-item"><span class="legend-dot" style="background:{color}"></span>{label}</span>'
        )
    legend_html = "\n".join(legend_parts)

    body = f"""{header}
<div class="cp-app">
<div class="tab-bar">
<div class="tab-list" role="tablist" aria-label="Views">
  <button class="tab active" role="tab" aria-selected="true" aria-controls="panel-2d" data-tab="2d"
    id="tab-2d" onclick="switchTab('2d')">2D Explorer</button>
  <button class="tab" role="tab" aria-selected="false" aria-controls="panel-3d" data-tab="3d" id="tab-3d"
    onclick="switchTab('3d')" title="Requires opening in a browser (Chrome, Firefox, Safari)">3D View &#127760;</button>
</div>
{checklist_tab}</div>

<div class="toolbar" id="toolbar-2d">
  <label>View:
    <select id="sel-view" onchange="onViewChange()"></select>
  </label>
  <label>Bubble Size:
    <select id="sel-size" onchange="onEncodingChange()">
      <option value="defensibility" selected>Defensibility</option>
      <option value="moat_count">Moat Count</option>
      <option value="uniform">Uniform</option>
    </select>
  </label>
  <label>Bubble Color:
    <select id="sel-color" onchange="onEncodingChange()">
      <option value="category" selected>Category</option>
      <option value="defensibility">Defensibility</option>
    </select>
  </label>
</div>

<div class="legend-bar" id="legend-bar">
{legend_html}
</div>

<div class="scoring-basis-caption" id="scoring-basis-caption"></div>

<div class="tab-panel active" id="panel-2d" role="tabpanel" aria-labelledby="tab-2d">
  <div class="main">
    <div class="chart-area">
      <div class="chart-canvas"><canvas id="chart-2d"></canvas></div>
      <div id="axis-rationale" class="axis-rationale" hidden></div>
      <div id="view-score-panel" class="view-score-panel" hidden></div>
    </div>
    <div class="sidebar" id="sidebar">
      <h3>Companies</h3>
      <div id="company-list"></div>
      <div class="detail-panel" id="detail-panel" hidden></div>
      <div class="detail-panel" id="diff-claims-panel">
        <h3>Differentiation Stress-Test</h3>
        <div id="diff-claims-list"></div>
      </div>
    </div>
  </div>
</div>

<div class="tab-panel" id="panel-3d" role="tabpanel" aria-labelledby="tab-3d">
  <div id="3d-axes-bar" class="axes-bar" hidden></div>
  <div id="chart-3d-container">
    <div class="placeholder" id="3d-placeholder">
      <span class="spinner"></span> Loading 3D view&hellip;
    </div>
    <div id="3d-fallback" hidden style="padding: 3rem 2rem; text-align: center;">
      <div style="max-width: 480px; margin: 0 auto; background: var(--lool-paper);
                  border: 1px solid var(--lool-line-2); padding: 2.5rem;">
        <div style="font-size: 2.5rem; margin-bottom: 1rem;">&#127760;</div>
        <h3 style="font-size: 1.1rem; color: var(--lool-ink); margin-bottom: 0.75rem;">
          3D View &mdash; Open in Browser</h3>
        <p style="font-size: 0.9rem; color: var(--lool-mute); line-height: 1.6; margin-bottom: 1.25rem;">
          The interactive 3D positioning map requires a full browser environment.
          It cannot load inside embedded viewers like Claude Cowork.</p>
        <p style="font-size: 0.85rem; color: var(--lool-mute); background: var(--lool-paper-2);
                  border-radius: var(--r-input); padding: 0.75rem 1rem; line-height: 1.5;">
          <strong>To use 3D:</strong> Open this file in Chrome, Safari or Firefox
          (from where you saved it), not inside the viewer.</p>
      </div>
    </div>
  </div>
</div>

</div>
{checklist_section}"""
    script = f"""<script>
/*DATA_START*/
const DATA = {data_json};
/*DATA_END*/
const CATEGORY_COLORS = DATA.category_colors;
const DEFENSIBILITY_COLORS = DATA.defensibility_colors;
const SCORING_BASIS_LABELS = {{
  shipped: 'Shipped / verifiable surface',
  roadmap_12mo: '12-month roadmap',
  mixed: 'Mixed'
}};
const DEFENSIBILITY_RADII = {{high: 12, moderate: 8, low: 5}};
const STARTUP_MIN_RADIUS = 8;
const VERDICT_COLORS = {{
  holds: 'var(--lool-success)',
  partially_holds: 'var(--lool-warning)',
  does_not_hold: 'var(--lool-danger)',
  unproven: 'var(--lool-mute)'
}};

// State
var currentView = null;
var chart2d = null;
var plotly3dInitialized = false;
var selectedCompany = null;

// ---- Helpers ----

function escHtml(s) {{
  var d = document.createElement('div');
  d.appendChild(document.createTextNode(s == null ? '' : String(s)));
  return d.innerHTML;
}}

function humanize(s) {{
  return escHtml((s || '').replace(/_/g, ' ').replace(/\b\\w/g, function(c) {{ return c.toUpperCase(); }}));
}}

function getCompanyStyle(slug) {{
  var isStartup = slug === '_startup';
  var cat = isStartup ? '_startup' : 'direct';
  var def = '';

  // Find category from competitors
  if (!isStartup) {{
    for (var i = 0; i < DATA.competitors.length; i++) {{
      if (DATA.competitors[i].slug === slug) {{
        cat = DATA.competitors[i].category || 'direct';
        break;
      }}
    }}
  }}

  // Find defensibility from moats
  if (DATA.company_moats[slug]) {{
    def = (DATA.company_moats[slug].overall_defensibility || '').toLowerCase();
  }}

  var sizeMode = document.getElementById('sel-size').value;
  var colorMode = document.getElementById('sel-color').value;

  // Radius
  var radius;
  if (sizeMode === 'defensibility') {{
    radius = DEFENSIBILITY_RADII[def] || 5;
    if (isStartup) radius = Math.max(radius, STARTUP_MIN_RADIUS);
  }} else if (sizeMode === 'moat_count') {{
    var mc = DATA.company_moats[slug] ? (DATA.company_moats[slug].moat_count || 0) : 0;
    radius = 4 + mc * 2;
    if (isStartup) radius = Math.max(radius, STARTUP_MIN_RADIUS);
  }} else {{
    radius = isStartup ? 8 : 5;
  }}

  // Color
  var color;
  if (colorMode === 'category') {{
    color = CATEGORY_COLORS[cat] || CATEGORY_COLORS['direct'];
  }} else {{
    color = DEFENSIBILITY_COLORS[def] || '#A6AEB5';
  }}

  return {{
    radius: radius,
    color: color,
    category: cat,
    defensibility: def,
    isStartup: isStartup,
    borderColor: isStartup ? '#ffffff' : 'transparent',
    borderWidth: isStartup ? 2 : 0
  }};
}}

// ---- Scoring Basis Caption ----

function renderScoringBasisCaption() {{
  // Absent/unrecognized always renders as "Not declared" — never silently
  // assumed to be "shipped" — so a reader never has to guess what the plotted
  // coordinates mean, and a pre-convention artifact isn't misrepresented.
  var label = SCORING_BASIS_LABELS[DATA.scoring_basis] || 'Not declared';
  var el = document.getElementById('scoring-basis-caption');
  el.innerHTML = '<strong>Scoring basis:</strong> ' + escHtml(label);
}}

// ---- View Selector ----

function populateViewSelector() {{
  var sel = document.getElementById('sel-view');
  sel.innerHTML = '';
  DATA.views.forEach(function(v, i) {{
    var opt = document.createElement('option');
    opt.value = i;
    var xName = (v.x_axis && v.x_axis.name) || 'X';
    var yName = (v.y_axis && v.y_axis.name) || 'Y';
    var viewLabel = v.label || humanize(v.id || 'view-' + i);
    opt.textContent = viewLabel + ': ' + xName + ' vs ' + yName;
    sel.appendChild(opt);
  }});
  if (DATA.views.length > 0) {{
    currentView = 0;
  }}
}}

// ---- Company List ----

function buildCompanyList() {{
  var list = document.getElementById('company-list');
  list.innerHTML = '';

  // _startup first
  var startupItem = makeCompanyItem('_startup', DATA.company_name, '_startup');
  list.appendChild(startupItem);

  // Then competitors
  DATA.competitors.forEach(function(c) {{
    var item = makeCompanyItem(c.slug, c.name, c.category);
    list.appendChild(item);
  }});
}}

function makeCompanyItem(slug, name, category) {{
  var div = document.createElement('div');
  div.className = 'company-item';
  div.setAttribute('data-slug', slug);
  div.onclick = function() {{ selectCompany(slug); }};

  var dot = document.createElement('span');
  dot.className = 'dot';
  dot.style.background = CATEGORY_COLORS[category] || CATEGORY_COLORS['direct'];
  div.appendChild(dot);

  var nameSpan = document.createElement('span');
  nameSpan.className = 'name';
  nameSpan.textContent = name;  // textContent is safe — no HTML injection
  div.appendChild(nameSpan);

  var catSpan = document.createElement('span');
  catSpan.className = 'cat';
  catSpan.textContent = humanize(category);
  div.appendChild(catSpan);

  return div;
}}

// ---- Detail Panel ----

function selectCompany(slug) {{
  selectedCompany = slug;

  // Highlight in list
  document.querySelectorAll('.company-item').forEach(function(el) {{
    el.style.background = el.getAttribute('data-slug') === slug ? 'var(--lool-line-2)' : '';
  }});

  // Show detail
  var panel = document.getElementById('detail-panel');
  var moatData = DATA.company_moats[slug];
  var comp = null;
  if (slug === '_startup') {{
    comp = {{ name: DATA.company_name, category: '_startup' }};
  }} else {{
    for (var i = 0; i < DATA.competitors.length; i++) {{
      if (DATA.competitors[i].slug === slug) {{ comp = DATA.competitors[i]; break; }}
    }}
  }}

  if (!comp) {{ panel.hidden = true; return; }}

  var h = '<h4>' + escHtml(comp.name || slug) + '</h4>';

  // Category & defensibility
  var def = moatData ? (moatData.overall_defensibility || 'unknown') : 'unknown';
  h += '<div class="detail-row"><span class="label">Category</span>' +
    '<span class="value">' + humanize(comp.category || '') + '</span></div>';
  h += '<div class="detail-row"><span class="label">Defensibility</span>' +
    '<span class="value">' + humanize(def) + '</span></div>';

  // Key differentiators
  if (comp.key_differentiators && comp.key_differentiators.length) {{
    h += '<div style="margin-top:0.5rem;font-size:0.75rem;color:var(--lool-slate);font-weight:500;">' +
      'Key Differentiators</div>';
    comp.key_differentiators.forEach(function(d) {{
      h += '<div style="font-size:0.75rem;color:var(--lool-mute);padding:2px 0;">&bull; ' + escHtml(d) + '</div>';
    }});
  }}

  // Moat summary
  if (moatData && moatData.moats) {{
    h += '<div style="margin-top:0.5rem;font-size:0.75rem;color:var(--lool-slate);font-weight:500;">Moats</div>';
    moatData.moats.forEach(function(m) {{
      if (m.status !== 'absent' && m.status !== 'not_applicable') {{
        h += '<div class="detail-row"><span class="label">' + humanize(m.id) + '</span>';
        h += '<span class="value">' + humanize(m.status) + ' (' + humanize(m.trajectory) + ')</span></div>';
      }}
    }});
  }}

  // Evidence for current view position
  if (currentView !== null && DATA.views[currentView]) {{
    var points = DATA.views[currentView].points || [];
    for (var i = 0; i < points.length; i++) {{
      if (points[i].competitor === slug) {{
        h += '<div style="margin-top:0.5rem;font-size:0.75rem;color:var(--lool-slate);font-weight:500;">' +
          'Position Evidence</div>';
        h += '<div style="font-size:0.7rem;color:var(--lool-mute);padding:2px 0;">' +
          '<b>X:</b> ' + escHtml(points[i].x_evidence || 'N/A') + '</div>';
        h += '<div style="font-size:0.7rem;color:var(--lool-mute);padding:2px 0;">' +
          '<b>Y:</b> ' + escHtml(points[i].y_evidence || 'N/A') + '</div>';
        break;
      }}
    }}
  }}

  panel.innerHTML = h;
  panel.hidden = false;
}}

// ---- 2D Chart ----

function render2D() {{
  if (currentView === null || !DATA.views[currentView]) return;
  var view = DATA.views[currentView];
  var points = view.points || [];
  var xName = (view.x_axis && view.x_axis.name) || 'X';
  var yName = (view.y_axis && view.y_axis.name) || 'Y';

  var datasets = [];
  var viewSlugs = new Set(points.map(function(p) {{ return p.competitor; }}));

  points.forEach(function(pt) {{
    var slug = pt.competitor;
    var style = getCompanyStyle(slug);
    var label = slug === '_startup' ? DATA.company_name
      : (DATA.display_names[slug] || humanize(slug.replace(/-/g, ' ')));

    datasets.push({{
      label: label,
      data: [{{ x: pt.x, y: pt.y }}],
      backgroundColor: style.color,
      borderColor: style.borderColor,
      borderWidth: style.borderWidth,
      pointRadius: style.radius,
      pointHoverRadius: style.radius + 2,
      pointStyle: style.isStartup ? 'rectRot' : 'circle',
      _slug: slug
    }});
  }});

  // Mark not-scored companies in sidebar
  document.querySelectorAll('.company-item').forEach(function(el) {{
    var slug = el.getAttribute('data-slug');
    var notScored = el.querySelector('.not-scored');
    if (!viewSlugs.has(slug) && slug !== '_startup') {{
      el.classList.add('dimmed');
      if (!notScored) {{
        var ns = document.createElement('span');
        ns.className = 'not-scored';
        ns.textContent = '(not scored)';
        el.appendChild(ns);
      }}
    }} else {{
      el.classList.remove('dimmed');
      if (notScored) notScored.remove();
    }}
  }});

  if (chart2d) chart2d.destroy();

  var ctx = document.getElementById('chart-2d').getContext('2d');
  chart2d = new Chart(ctx, {{
    type: 'scatter',
    data: {{ datasets: datasets }},
    options: {{
      responsive: true,
      maintainAspectRatio: false,
      scales: {{
        x: {{
          min: 0, max: 100,
          title: {{ display: true, text: xName, font: {{ size: 13 }} }}
        }},
        y: {{
          min: 0, max: 100,
          title: {{ display: true, text: yName, font: {{ size: 13 }} }}
        }}
      }},
      plugins: {{
        legend: {{ display: false }},
        tooltip: {{
          callbacks: {{
            label: function(ctx) {{
              var ds = ctx.dataset;
              return ds.label + ' (' + ctx.parsed.x + ', ' + ctx.parsed.y + ')';
            }}
          }}
        }}
      }},
      onClick: function(evt, elements) {{
        if (elements.length > 0) {{
          var idx = elements[0].datasetIndex;
          var slug = datasets[idx]._slug;
          selectCompany(slug);
        }}
      }}
    }}
  }});

  // Update legend bar
  updateLegend();

  // Update axis rationale
  var ratDiv = document.getElementById('axis-rationale');
  var xRat = (view.x_axis && view.x_axis.rationale) || '';
  var yRat = (view.y_axis && view.y_axis.rationale) || '';
  if (xRat || yRat) {{
    ratDiv.innerHTML =
      (xRat ? '<div><strong>X \u2014 ' + escHtml(xName) + ':</strong> ' + escHtml(xRat) + '</div>' : '') +
      (yRat ? '<div><strong>Y \u2014 ' + escHtml(yName) + ':</strong> ' + escHtml(yRat) + '</div>' : '');
    ratDiv.hidden = false;
  }} else {{
    ratDiv.hidden = true;
  }}

  // Update view score panel (differentiation score, per-axis rank, vanity flags).
  // Rank convention: "Rank N of M ranked", where M = competitor_count + 1 (the
  // startup counted among the ranked entities) \u2014 never "of M competitors".
  var scorePanel = document.getElementById('view-score-panel');
  var vs = DATA.view_scores[String(view.id || '')];
  if (vs) {{
    var totalRanked = (vs.competitor_count || 0) + 1;
    var lines = [];
    if (vs.where_you_stand) {{
      lines.push('<div><strong>Where you stand:</strong> ' + escHtml(vs.where_you_stand) + '</div>');
    }}
    // A tie is shown as a range: startup_*_rank counts only competitors strictly ahead.
    function placeText(rank, tied) {{
      var k = (tied && tied.length) ? tied.length : 0;
      return k ? (rank + '\u2013' + (rank + k) + ' of ' + totalRanked + ' ranked (tied)')
               : (rank + ' of ' + totalRanked + ' ranked');
    }}
    if (vs.startup_x_rank !== undefined && vs.startup_x_rank !== null) {{
      lines.push('<div><strong>' + escHtml(xName) + ' rank:</strong> Rank ' +
        placeText(vs.startup_x_rank, vs.startup_x_tied_with) + '</div>');
    }}
    if (vs.startup_y_rank !== undefined && vs.startup_y_rank !== null) {{
      lines.push('<div><strong>' + escHtml(yName) + ' rank:</strong> Rank ' +
        placeText(vs.startup_y_rank, vs.startup_y_tied_with) + '</div>');
    }}
    if (vs.x_axis_vanity_flag) {{
      lines.push('<div class="vanity-flag">Vanity axis warning: ' + escHtml(xName) + '</div>');
    }}
    if (vs.y_axis_vanity_flag) {{
      lines.push('<div class="vanity-flag">Vanity axis warning: ' + escHtml(yName) + '</div>');
    }}
    if (lines.length) {{
      scorePanel.innerHTML = lines.join('');
      scorePanel.hidden = false;
    }} else {{
      scorePanel.hidden = true;
    }}
  }} else {{
    scorePanel.hidden = true;
  }}
}}

// ---- Differentiation Claims ----

function renderDiffClaims() {{
  var list = document.getElementById('diff-claims-list');
  var claims = DATA.diff_claims || [];
  if (!claims.length) {{
    list.innerHTML = '<div style="font-size:0.75rem;color:var(--lool-faint);font-style:italic;padding:0.25rem 0;">' +
      'No differentiation claims tested.</div>';
    return;
  }}
  var html = '';
  claims.forEach(function(c) {{
    var verdict = c.verdict || 'untested';
    var color = VERDICT_COLORS[verdict] || 'var(--lool-faint)';
    html += '<div class="claim-card">';
    html += '<div class="claim-text">' + escHtml(c.claim || '') + '</div>';
    html += '<span class="verdict-badge" style="background:' + color + '">' + humanize(verdict) + '</span>';
    if (c.evidence) {{
      html += '<div style="margin-top:4px;"><strong>Evidence:</strong> ' + escHtml(c.evidence) + '</div>';
    }}
    if (c.challenge) {{
      html += '<div style="margin-top:2px;"><strong>Investor Challenge:</strong> ' + escHtml(c.challenge) + '</div>';
    }}
    html += '</div>';
  }});
  list.innerHTML = html;
}}

function updateLegend() {{
  var colorMode = document.getElementById('sel-color').value;
  var bar = document.getElementById('legend-bar');
  var items = [];

  if (colorMode === 'category') {{
    var startupLabel = DATA.company_name !== 'Unknown' ? DATA.company_name : 'This company';
    var cats = [[startupLabel,'_startup'],['Direct','direct'],['Adjacent','adjacent'],
                ['Do Nothing','do_nothing'],['Emerging','emerging'],['Custom','custom']];
    cats.forEach(function(c) {{
      items.push('<span class="legend-item"><span class="legend-dot" style="background:' +
        CATEGORY_COLORS[c[1]] + '"></span>' + escHtml(c[0]) + '</span>');
    }});
  }} else {{
    var defs = [['High','high'],['Moderate','moderate'],['Low','low']];
    defs.forEach(function(d) {{
      items.push('<span class="legend-item"><span class="legend-dot" style="background:' +
        DEFENSIBILITY_COLORS[d[1]] + '"></span>' + d[0] + '</span>');
    }});
  }}
  bar.innerHTML = items.join('\\n');
}}

// ---- Event Handlers ----

function onViewChange() {{
  currentView = parseInt(document.getElementById('sel-view').value, 10);
  render2D();
  if (plotly3dInitialized) render3D();
  if (selectedCompany) selectCompany(selectedCompany);
}}

function onEncodingChange() {{
  render2D();
  if (plotly3dInitialized) render3D();
}}

function switchTab(tab) {{
  document.querySelectorAll('.tab[data-tab]').forEach(function(el) {{
    var on = el.getAttribute('data-tab') === tab;
    el.classList.toggle('active', on);
    el.setAttribute('aria-selected', on ? 'true' : 'false');
  }});
  document.querySelectorAll('.tab-panel').forEach(function(el) {{
    el.classList.toggle('active', el.id === 'panel-' + tab);
  }});
  document.getElementById('toolbar-2d').hidden = tab !== '2d';
  document.getElementById('legend-bar').hidden = tab !== '2d';

  if (tab === '3d' && !plotly3dInitialized) {{
    load3D();
  }}
}}

// ---- 3D (Lazy Load) ----

function load3D() {{
  var placeholder = document.getElementById('3d-placeholder');
  var fallback = document.getElementById('3d-fallback');
  var container = document.getElementById('chart-3d-container');

  var script = document.createElement('script');
  script.src = '{_PLOTLY_CDN}';
  script.onload = function() {{
    try {{
      render3D();
      placeholder.hidden = true;
      plotly3dInitialized = true;
    }} catch(e) {{
      placeholder.hidden = true;
      fallback.hidden = false;
    }}
  }};
  script.onerror = function() {{
    placeholder.hidden = true;
    fallback.hidden = false;
  }};
  document.head.appendChild(script);
}}

function render3D() {{
  if (!DATA.views.length) return;
  var view = DATA.views[currentView || 0];
  var points = view.points || [];

  var x = [], y = [], z = [], text = [], colors = [], sizes = [];
  points.forEach(function(pt) {{
    var slug = pt.competitor;
    var style = getCompanyStyle(slug);
    var label = slug === '_startup' ? DATA.company_name
      : (DATA.display_names[slug] || humanize(slug.replace(/-/g, ' ')));
    var def = DATA.company_moats[slug] ? DATA.company_moats[slug].overall_defensibility : 'low';
    var zVal = def === 'high' ? 3 : def === 'moderate' ? 2 : 1;

    x.push(pt.x);
    y.push(pt.y);
    z.push(zVal);
    text.push(label);
    colors.push(style.color);
    sizes.push(style.isStartup ? 12 : 8);
  }});

  var xName = (view.x_axis && view.x_axis.name) || 'X';
  var yName = (view.y_axis && view.y_axis.name) || 'Y';

  // Show axis legend bar
  var axesBar = document.getElementById('3d-axes-bar');
  axesBar.innerHTML =
    '<span style="display:inline-flex;align-items:center;gap:6px;">' +
      '<span style="width:14px;height:3px;background:#0D549D;border-radius:2px;"></span>' +
      '<strong style="color:#0D549D;">X:</strong> ' + escHtml(xName) + '</span>' +
    '<span style="display:inline-flex;align-items:center;gap:6px;">' +
      '<span style="width:14px;height:3px;background:#ea580c;border-radius:2px;"></span>' +
      '<strong style="color:#ea580c;">Y:</strong> ' + escHtml(yName) + '</span>' +
    '<span style="display:inline-flex;align-items:center;gap:6px;">' +
      '<span style="width:14px;height:3px;background:#2F8A56;border-radius:2px;"></span>' +
      '<strong style="color:#2F8A56;">Z:</strong> Defensibility</span>';
  axesBar.hidden = false;

  // Build custom hover text with axis names and defensibility label
  var defLabels = {{1: 'Low', 2: 'Moderate', 3: 'High'}};
  var hoverText = text.map(function(name, i) {{
    return '<b>' + escHtml(name) + '</b><br>' +
      escHtml(xName) + ': ' + x[i] + '<br>' +
      escHtml(yName) + ': ' + y[i] + '<br>' +
      'Defensibility: ' + (defLabels[z[i]] || 'Unknown');
  }});

  Plotly.newPlot('chart-3d-container', [{{
    type: 'scatter3d',
    mode: 'markers+text',
    x: x, y: y, z: z,
    text: text,
    textposition: 'top center',
    textfont: {{ size: 10 }},
    hovertext: hoverText,
    hoverinfo: 'text',
    marker: {{
      size: sizes,
      color: colors,
      opacity: 0.9,
      line: {{ width: 1, color: '#ffffff' }}
    }}
  }}], {{
    scene: {{
      xaxis: {{ title: '', range: [0, 100],
               tickfont: {{ color: '#0D549D' }},
               gridcolor: 'rgba(13, 84, 157, 0.15)',
               linecolor: '#0D549D' }},
      yaxis: {{ title: '', range: [0, 100],
               tickfont: {{ color: '#ea580c' }},
               gridcolor: 'rgba(234, 88, 12, 0.15)',
               linecolor: '#ea580c' }},
      zaxis: {{ title: '', range: [0, 4],
               tickvals: [1, 2, 3], ticktext: ['Low', 'Moderate', 'High'],
               tickfont: {{ color: '#2F8A56' }},
               gridcolor: 'rgba(47, 138, 86, 0.15)',
               linecolor: '#2F8A56' }},
      camera: {{ eye: {{ x: 1.5, y: 1.5, z: 1.2 }} }},
      aspectmode: 'cube',
      annotations: []
    }},
    height: document.getElementById('chart-3d-container').clientHeight - 50 || 650,
    margin: {{ l: 20, r: 20, t: 20, b: 20 }},
    showlegend: false
  }}, {{ responsive: true }});
}}

// ---- Init ----

populateViewSelector();
buildCompanyList();
renderScoringBasisCaption();
renderDiffClaims();
if (DATA.views.length > 0) {{
  render2D();
}} else {{
  document.getElementById('chart-2d').parentElement.innerHTML =
    '<div class="placeholder">No positioning views available.</div>';
}}
</script>
"""
    return _ui.page_shell(
        title=f"Competitive Explorer: {payload['company_name']}",
        body_html=body,
        brand_css=brand_css,
        page_css=_css(),
        head_html=f"<script>{_chartjs_source()}</script>\n",
        skill_name="Competitive Positioning",
        scripts_html=script,
    )


# ---------------------------------------------------------------------------
# Output & CLI
# ---------------------------------------------------------------------------


def _write_output(data: str, output_path: str | None) -> None:
    if output_path:
        abs_path = os.path.abspath(output_path)
        parent = os.path.dirname(abs_path)
        if parent == "/":
            print(
                f"Error: output path resolves to root directory: {output_path}",
                file=sys.stderr,
            )
            sys.exit(1)
        os.makedirs(parent, exist_ok=True)
        with open(abs_path, "w", encoding="utf-8") as f:
            f.write(data)
        receipt: dict[str, Any] = {
            "ok": True,
            "path": abs_path,
            "bytes": len(data.encode("utf-8")),
        }
        sys.stdout.write(json.dumps(receipt, separators=(",", ":")) + "\n")
    else:
        sys.stdout.write(data)


def _run_ref_module() -> ModuleType:
    """The sibling `_run_ref`, loaded only when `--run-id` is given."""
    scripts_dir = os.path.dirname(os.path.abspath(__file__))
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    import _run_ref

    return _run_ref


def _own_run_id(dir_path: str) -> str | None:
    """This page's run id, as compose reads it."""
    _run_ref_module()
    import _cp_redteam_copy

    artifacts = {name: _load_artifact(dir_path, name) for name in REQUIRED_ARTIFACTS + OPTIONAL_ARTIFACTS}
    return _cp_redteam_copy.primary_run_id_in(dir_path, artifacts, REQUIRED_ARTIFACTS)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate interactive HTML explorer for competitive positioning")
    parser.add_argument("-d", "--dir", required=True, help="Artifact directory")
    parser.add_argument("-o", "--output", default=None, help="Write HTML to file")
    parser.add_argument(
        "--run-id",
        default=None,
        help="Stamp the page with this run id (it must be the run id its artifacts carry) and, when the run "
        "has a gate ledger, list the page among the run's deliverables",
    )
    parser.add_argument("--pretty", action="store_true", help="(no-op, HTML output)")
    args = parser.parse_args()
    # FIRST: an output naming one of this step's own input files is refused before anything is written.
    import _out_guard

    _out_guard.refuse_output_onto_input(
        [args.output],
        script="explore.py",
        extra=[
            os.path.join(args.dir, n)
            for n in (
                "checklist.json",
                "competitor_verification.json",
                "landscape.json",
                "landscape_draft.json",
                "moat_scores.json",
                "positioning.json",
                "positioning_scores.json",
                "product_profile.json",
                "red_team_skip.json",
                "redteam.json",
                "report.json",
                "startup_research.json",
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
                for n in (
                    "landscape.json",
                    "positioning.json",
                    "moat_scores.json",
                    "positioning_scores.json",
                    "checklist.json",
                )
            ],
            noun="analysis dir",
        )
        _IGNORED_OTHER_RUN.update(
            n
            for n, _r in _run_ref.foreign_artifacts(
                args.dir,
                args.run_id,
                [
                    os.path.join(args.dir, n)
                    for n in (
                        "product_profile.json",
                        "landscape_draft.json",
                        "competitor_verification.json",
                        "startup_research.json",
                        "redteam.json",
                        "red_team_skip.json",
                    )
                ],
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

    html_out = compose_explorer(args.dir)
    if args.run_id is not None:
        html_out = _run_ref_module().page_for_run(html_out, args.run_id, _own_run_id(args.dir))
    _write_output(html_out, args.output)
    if args.run_id is not None and args.output:
        _run_ref_module().list_page(args.dir, args.run_id, "explorer_html", args.output, "explore.py")


if __name__ == "__main__":
    main()
