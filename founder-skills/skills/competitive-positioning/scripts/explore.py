#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
Generate self-contained interactive HTML explorer for competitive positioning.

Outputs HTML (not JSON). Uses Chart.js for interactive scatter plot with
view switching, bubble encoding controls, and company detail panels.

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
]


def _load_artifact(dir_path: str, name: str) -> dict[str, Any] | None:
    path = os.path.join(dir_path, name)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)  # type: ignore[no-any-return]
    except (json.JSONDecodeError, OSError):
        return _CORRUPT


def _is_stub(data: dict[str, Any] | None) -> bool:
    return isinstance(data, dict) and data.get("skipped") is True


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
    "direct": "#1e40af",
    "adjacent": "#ea580c",
    "do_nothing": "#9ca3af",
    "emerging": "#8b5cf6",
    "custom": "#14b8a6",
}

_DEFENSIBILITY_COLORS: dict[str, str] = {
    "high": "#10b981",
    "moderate": "#f59e0b",
    "low": "#ef4444",
}


def _build_data_payload(dir_path: str) -> dict[str, Any]:
    """Load all artifacts and assemble the explorer data payload."""
    artifacts: dict[str, dict[str, Any] | None] = {}
    for name in REQUIRED_ARTIFACTS + OPTIONAL_ARTIFACTS:
        artifacts[name] = _load_artifact(dir_path, name)

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

    # Views with points
    views: list[dict[str, Any]] = []
    if _usable(positioning):
        for v in _as_list(positioning.get("views")):
            if isinstance(v, dict) and _as_list(v.get("points")):
                views.append(v)

    # View scores keyed by view id
    view_scores_map: dict[str, dict[str, Any]] = {}
    if _usable(positioning_scores):
        for sv in _as_list(positioning_scores.get("views")):
            if isinstance(sv, dict):
                vid = str(sv.get("view_id", sv.get("id", "")))
                if vid:
                    view_scores_map[vid] = sv

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

    # Differentiation claims
    diff_claims: list[dict[str, Any]] = []
    if _usable(positioning):
        diff_claims = [c for c in _as_list(positioning.get("differentiation_claims")) if isinstance(c, dict)]

    return {
        "company_name": company_name,
        "views": views,
        "view_scores": view_scores_map,
        "competitors": competitors,
        "company_moats": company_moats,
        "diff_claims": diff_claims,
        "category_colors": _CATEGORY_COLORS,
        "defensibility_colors": _DEFENSIBILITY_COLORS,
    }


# ---------------------------------------------------------------------------
# HTML template
# ---------------------------------------------------------------------------

# Chart.js loaded via CDN for MVP. Inlining deferred to follow-up task.
_CHARTJS_CDN = "https://cdn.jsdelivr.net/npm/chart.js@4.4"
_PLOTLY_CDN = "https://cdn.plot.ly/plotly-gl3d-2.35.2.min.js"


def _css() -> str:
    """Return embedded CSS for the explorer."""
    return """
    <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
           background: #f8fafc; color: #1e293b; line-height: 1.5; }
    .header { padding: 1.5rem 2rem; background: #fff; border-bottom: 1px solid #e2e8f0; }
    .header h1 { font-size: 1.5rem; color: #0d549d; }
    .header .subtitle { font-size: 0.875rem; color: #64748b; }
    .toolbar { display: flex; flex-wrap: wrap; gap: 1rem; padding: 1rem 2rem;
               background: #fff; border-bottom: 1px solid #e2e8f0; align-items: center; }
    .toolbar label { font-size: 0.8rem; color: #475569; font-weight: 500; }
    .toolbar select { font-size: 0.8rem; padding: 4px 8px; border: 1px solid #cbd5e1;
                      border-radius: 4px; background: #fff; }
    .main { display: flex; gap: 0; min-height: calc(100vh - 140px); }
    .chart-area { flex: 1; padding: 1.5rem; min-width: 0; }
    .sidebar { width: 320px; border-left: 1px solid #e2e8f0; background: #fff;
               overflow-y: auto; padding: 1rem; }
    .sidebar h3 { font-size: 0.85rem; color: #374151; margin-bottom: 0.5rem; padding-bottom: 0.25rem;
                  border-bottom: 1px solid #e5e7eb; }
    .company-item { padding: 0.5rem; border-radius: 6px; cursor: pointer; font-size: 0.8rem;
                    display: flex; align-items: center; gap: 8px; transition: background 0.15s; }
    .company-item:hover { background: #f1f5f9; }
    .company-item.dimmed { opacity: 0.4; }
    .company-item .dot { width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; }
    .company-item .name { font-weight: 500; }
    .company-item .cat { font-size: 0.7rem; color: #94a3b8; }
    .detail-panel { margin-top: 1rem; }
    .detail-panel h4 { font-size: 0.85rem; color: #0d549d; margin-bottom: 0.5rem; }
    .detail-row { display: flex; justify-content: space-between; font-size: 0.75rem;
                  padding: 0.25rem 0; border-bottom: 1px solid #f1f5f9; }
    .detail-row .label { color: #64748b; }
    .detail-row .value { color: #1e293b; font-weight: 500; }
    .badge { display: inline-block; padding: 2px 8px; border-radius: 10px;
             font-size: 0.7rem; font-weight: 600; color: #fff; }
    .legend-bar { display: flex; flex-wrap: wrap; gap: 1rem; padding: 0.75rem 2rem;
                  background: #fff; border-bottom: 1px solid #e2e8f0; font-size: 0.75rem; }
    .legend-item { display: flex; align-items: center; gap: 4px; }
    .legend-dot { width: 10px; height: 10px; border-radius: 50%; }
    .placeholder { padding: 3rem; text-align: center; color: #94a3b8; font-size: 0.9rem; }
    .tab-bar { display: flex; gap: 0; background: #fff; border-bottom: 1px solid #e2e8f0; }
    .tab { padding: 0.5rem 1.5rem; font-size: 0.85rem; cursor: pointer; border: none;
           background: none; color: #64748b; border-bottom: 2px solid transparent; }
    .tab.active { color: #0d549d; border-bottom-color: #0d549d; font-weight: 600; }
    .tab:disabled { color: #cbd5e1; cursor: not-allowed; }
    .tab-panel { display: none; }
    .tab-panel.active { display: block; }
    #chart-3d-container { width: 100%; height: calc(100vh - 100px); min-height: 400px; }
    .spinner { display: inline-block; width: 20px; height: 20px; border: 2px solid #e2e8f0;
               border-top-color: #0d549d; border-radius: 50%; animation: spin 0.6s linear infinite; }
    @keyframes spin { to { transform: rotate(360deg); } }
    .not-scored { font-size: 0.7rem; color: #94a3b8; font-style: italic; }
    @media (max-width: 768px) {
      .main { flex-direction: column; }
      .sidebar { width: 100%; border-left: none; border-top: 1px solid #e2e8f0; }
      .toolbar { flex-direction: column; }
    }
    @media print {
      .toolbar, .tab-bar, .sidebar { display: none; }
      .main { display: block; }
    }
    </style>
    """


def compose_explorer(dir_path: str) -> str:
    """Build the full interactive explorer HTML."""
    payload = _build_data_payload(dir_path)
    data_json = _safe_json_embed(payload)
    company_name = _esc(payload["company_name"])

    # Build legend bar
    legend_parts: list[str] = []
    for label, color in [
        ("Your Company", _CATEGORY_COLORS["_startup"]),
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

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>Competitive Explorer: {company_name}</title>
<script src="{_CHARTJS_CDN}"></script>
{_css()}
</head>
<body>
<div class="header">
  <h1>Competitive Explorer: {company_name}</h1>
  <div class="subtitle">Interactive positioning analysis &mdash;
    <a href="https://github.com/lool-ventures/founder-skills">founder skills</a>
    by <a href="https://lool.vc">lool ventures</a></div>
</div>

<div class="tab-bar">
  <button class="tab active" data-tab="2d" onclick="switchTab('2d')">2D Explorer</button>
  <button class="tab" data-tab="3d" id="tab-3d" onclick="switchTab('3d')">3D View</button>
</div>

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

<div class="tab-panel active" id="panel-2d">
  <div class="main">
    <div class="chart-area">
      <canvas id="chart-2d"></canvas>
    </div>
    <div class="sidebar" id="sidebar">
      <h3>Companies</h3>
      <div id="company-list"></div>
      <div class="detail-panel" id="detail-panel" style="display:none;"></div>
    </div>
  </div>
</div>

<div class="tab-panel" id="panel-3d">
  <div id="chart-3d-container">
    <div class="placeholder" id="3d-placeholder">
      <span class="spinner"></span> Loading 3D view&hellip;
    </div>
    <div class="placeholder" id="3d-fallback" style="display:none;">
      3D view requires network access and WebGL support.
    </div>
  </div>
</div>

<script>
/*DATA_START*/
const DATA = {data_json};
/*DATA_END*/
const CATEGORY_COLORS = DATA.category_colors;
const DEFENSIBILITY_COLORS = DATA.defensibility_colors;
const DEFENSIBILITY_RADII = {{high: 12, moderate: 8, low: 5}};
const STARTUP_MIN_RADIUS = 8;

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
    color = DEFENSIBILITY_COLORS[def] || '#9ca3af';
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

// ---- View Selector ----

function populateViewSelector() {{
  var sel = document.getElementById('sel-view');
  sel.innerHTML = '';
  DATA.views.forEach(function(v, i) {{
    var opt = document.createElement('option');
    opt.value = i;
    var xName = (v.x_axis && v.x_axis.name) || 'X';
    var yName = (v.y_axis && v.y_axis.name) || 'Y';
    opt.textContent = humanize(v.id || 'view-' + i) + ': ' + xName + ' vs ' + yName;
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
    el.style.background = el.getAttribute('data-slug') === slug ? '#eff6ff' : '';
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

  if (!comp) {{ panel.style.display = 'none'; return; }}

  var h = '<h4>' + escHtml(comp.name || slug) + '</h4>';

  // Category & defensibility
  var def = moatData ? (moatData.overall_defensibility || 'unknown') : 'unknown';
  h += '<div class="detail-row"><span class="label">Category</span>' +
    '<span class="value">' + humanize(comp.category || '') + '</span></div>';
  h += '<div class="detail-row"><span class="label">Defensibility</span>' +
    '<span class="value">' + humanize(def) + '</span></div>';

  // Key differentiators
  if (comp.key_differentiators && comp.key_differentiators.length) {{
    h += '<div style="margin-top:0.5rem;font-size:0.75rem;color:#475569;font-weight:500;">Key Differentiators</div>';
    comp.key_differentiators.forEach(function(d) {{
      h += '<div style="font-size:0.75rem;color:#64748b;padding:2px 0;">&bull; ' + escHtml(d) + '</div>';
    }});
  }}

  // Moat summary
  if (moatData && moatData.moats) {{
    h += '<div style="margin-top:0.5rem;font-size:0.75rem;color:#475569;font-weight:500;">Moats</div>';
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
        h += '<div style="margin-top:0.5rem;font-size:0.75rem;color:#475569;font-weight:500;">Position Evidence</div>';
        h += '<div style="font-size:0.7rem;color:#64748b;padding:2px 0;">' +
          '<b>X:</b> ' + escHtml(points[i].x_evidence || 'N/A') + '</div>';
        h += '<div style="font-size:0.7rem;color:#64748b;padding:2px 0;">' +
          '<b>Y:</b> ' + escHtml(points[i].y_evidence || 'N/A') + '</div>';
        break;
      }}
    }}
  }}

  panel.innerHTML = h;
  panel.style.display = 'block';
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
    var label = slug === '_startup' ? DATA.company_name : humanize(slug.replace(/-/g, ' '));

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
      maintainAspectRatio: true,
      aspectRatio: 1.33,
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
}}

function updateLegend() {{
  var colorMode = document.getElementById('sel-color').value;
  var bar = document.getElementById('legend-bar');
  var items = [];

  if (colorMode === 'category') {{
    var cats = [['Your Company','_startup'],['Direct','direct'],['Adjacent','adjacent'],
                ['Do Nothing','do_nothing'],['Emerging','emerging'],['Custom','custom']];
    cats.forEach(function(c) {{
      items.push('<span class="legend-item"><span class="legend-dot" style="background:' +
        CATEGORY_COLORS[c[1]] + '"></span>' + c[0] + '</span>');
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
  document.querySelectorAll('.tab').forEach(function(el) {{
    el.classList.toggle('active', el.getAttribute('data-tab') === tab);
  }});
  document.querySelectorAll('.tab-panel').forEach(function(el) {{
    el.classList.toggle('active', el.id === 'panel-' + tab);
  }});
  document.getElementById('toolbar-2d').style.display = tab === '2d' ? 'flex' : 'none';
  document.getElementById('legend-bar').style.display = tab === '2d' ? 'flex' : 'none';

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
      placeholder.style.display = 'none';
      plotly3dInitialized = true;
    }} catch(e) {{
      placeholder.style.display = 'none';
      fallback.style.display = 'block';
    }}
  }};
  script.onerror = function() {{
    placeholder.style.display = 'none';
    fallback.style.display = 'block';
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
    var label = slug === '_startup' ? DATA.company_name : humanize(slug.replace(/-/g, ' '));
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

  // Build custom hover text with axis names and defensibility label
  var defLabels = {{1: 'Low', 2: 'Moderate', 3: 'High'}};
  var hoverText = text.map(function(name, i) {{
    return '<b>' + name + '</b><br>' +
      xName + ': ' + x[i] + '<br>' +
      yName + ': ' + y[i] + '<br>' +
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
      xaxis: {{ title: xName, range: [0, 100] }},
      yaxis: {{ title: yName, range: [0, 100] }},
      zaxis: {{ title: 'Defensibility', range: [0, 4],
               tickvals: [1, 2, 3], ticktext: ['Low', 'Moderate', 'High'] }},
      camera: {{ eye: {{ x: 1.5, y: 1.5, z: 1.2 }} }}
    }},
    margin: {{ l: 0, r: 0, t: 30, b: 0 }},
    showlegend: false
  }}, {{ responsive: true }});
}}

// ---- Init ----

populateViewSelector();
buildCompanyList();
if (DATA.views.length > 0) {{
  render2D();
}} else {{
  document.getElementById('chart-2d').parentElement.innerHTML =
    '<div class="placeholder">No positioning views available.</div>';
}}
</script>
</body>
</html>"""


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


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate interactive HTML explorer for competitive positioning")
    parser.add_argument("-d", "--dir", required=True, help="Artifact directory")
    parser.add_argument("-o", "--output", default=None, help="Write HTML to file")
    parser.add_argument("--pretty", action="store_true", help="(no-op, HTML output)")
    args = parser.parse_args()

    if not os.path.isdir(args.dir):
        print(f"Error: directory not found: {args.dir}", file=sys.stderr)
        sys.exit(1)

    html_out = compose_explorer(args.dir)
    _write_output(html_out, args.output)


if __name__ == "__main__":
    main()
