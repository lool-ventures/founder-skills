"""Tests for competitive positioning explore.py (interactive HTML explorer)."""

from __future__ import annotations

import copy
import json
import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Generator
from contextlib import contextmanager
from html.parser import HTMLParser
from typing import Any

# Shared fixtures — imported from conftest (populated in Task 6 setup step)
from conftest_competitive_positioning import (
    VALID_LANDSCAPE,
    VALID_MOAT_SCORES,
    VALID_POSITIONING,
    VALID_POSITIONING_SCORES,
    VALID_REPORT,
)

SCRIPT = os.path.join(
    os.path.dirname(__file__),
    "..",
    "skills",
    "competitive-positioning",
    "scripts",
    "explore.py",
)


@contextmanager
def _make_artifact_dir(artifacts: dict[str, Any]) -> Generator[str, None, None]:
    with tempfile.TemporaryDirectory() as d:
        for name, data in artifacts.items():
            with open(os.path.join(d, name), "w") as f:
                json.dump(data, f)
        yield d


def _all_artifacts() -> dict[str, Any]:
    return {
        "positioning.json": VALID_POSITIONING,
        "landscape.json": VALID_LANDSCAPE,
        "moat_scores.json": VALID_MOAT_SCORES,
        "positioning_scores.json": VALID_POSITIONING_SCORES,
        "product_profile.json": {
            "company_name": "SecureFlow",
            "slug": "secureflow",
            "product_description": "API security platform",
            "target_customers": ["Mid-market SaaS"],
            "value_propositions": ["Fast detection"],
            "differentiation_claims": ["ML model"],
            "stage": "seed",
            "sector": "Cybersecurity",
            "business_model": "SaaS",
            "input_mode": "conversation",
            "source_materials": ["conversation"],
            "metadata": {"run_id": "20260319T143045Z"},
        },
        "report.json": VALID_REPORT,
    }


def _run_explore(artifact_dir: str, extra_args: list[str] | None = None) -> tuple[int, str, str]:
    cmd = [sys.executable, SCRIPT, "--dir", artifact_dir]
    if extra_args:
        cmd.extend(extra_args)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    return result.returncode, result.stdout, result.stderr


# ---------------------------------------------------------------------------
# Self-contained contract checker
# ---------------------------------------------------------------------------


class _ExternalResourceChecker(HTMLParser):
    """Find top-level <script src> and <link rel=stylesheet href> with external URLs."""

    def __init__(self) -> None:
        super().__init__()
        self.external_scripts: list[str] = []
        self.external_stylesheets: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_dict = dict(attrs)
        if tag == "script" and attr_dict.get("src"):
            src = attr_dict["src"]
            if src and (src.startswith("http://") or src.startswith("https://")):
                self.external_scripts.append(src)
        if tag == "link" and attr_dict.get("rel") == "stylesheet" and attr_dict.get("href"):
            href = attr_dict["href"]
            if href and (href.startswith("http://") or href.startswith("https://")):
                self.external_stylesheets.append(href)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_generates_html() -> None:
    """Outputs valid HTML document."""
    arts = _all_artifacts()
    with _make_artifact_dir(arts) as d:
        rc, stdout, stderr = _run_explore(d)
        assert rc == 0, f"exit {rc}, stderr={stderr}"
        assert "<!DOCTYPE html>" in stdout
        assert "</html>" in stdout


def test_3d_tab_degrades_gracefully_in_cowork() -> None:
    """The optional 3D tab lazy-loads Plotly from a CDN (deliberately not
    inlined — ~3 MB). In Cowork (embedded viewer, no CDN egress) that load
    fails. This must degrade to a clear, Cowork-named fallback card, NOT a
    silent blank tab. Regression guard: a refactor must not drop the
    `#3d-fallback` card or the `onerror`/`catch` handlers that reveal it.

    (The 2D map is vendored/offline and unaffected; only the 3D tab depends on
    the CDN. See 2026-06-16-skills-live-test-findings.md Finding 1.)
    """
    arts = _all_artifacts()
    with _make_artifact_dir(arts) as d:
        rc, stdout, stderr = _run_explore(d)
        assert rc == 0, f"exit {rc}, stderr={stderr}"
        # The fallback card element must exist...
        assert 'id="3d-fallback"' in stdout, "missing #3d-fallback degradation card"
        # ...both failure paths (CDN load error AND render error) must reveal it...
        assert "script.onerror" in stdout, "missing CDN-load-failure (onerror) handler"
        assert stdout.count("fallback.style.display = 'block'") >= 2, (
            "both the onerror and the render-catch handlers must reveal the fallback card"
        )
        # ...and it must name Cowork so the user knows why and what to do.
        assert "Cowork" in stdout, "fallback card must name Cowork (the embedded-viewer case)"


def test_chartjs_loaded() -> None:
    """Chart.js must be inlined — the vendored source must appear in HTML."""
    arts = _all_artifacts()
    with _make_artifact_dir(arts) as d:
        rc, stdout, stderr = _run_explore(d)
        assert rc == 0, f"exit {rc}, stderr={stderr}"
        assert "new Chart(" in stdout, "Explorer must use Chart.js (new Chart(...))"
        assert "Chart.js v" in stdout, "Chart.js source must be inlined (vendored)"


def test_no_external_stylesheets() -> None:
    """No external stylesheet links — CSS must be inlined."""
    arts = _all_artifacts()
    with _make_artifact_dir(arts) as d:
        rc, stdout, stderr = _run_explore(d)
        assert rc == 0, f"exit {rc}, stderr={stderr}"
        checker = _ExternalResourceChecker()
        checker.feed(stdout)
        assert len(checker.external_stylesheets) == 0, f"External stylesheets found: {checker.external_stylesheets}"


def test_data_embedding() -> None:
    """const DATA = ... is present and contains valid JSON with expected keys."""

    arts = _all_artifacts()
    with _make_artifact_dir(arts) as d:
        rc, stdout, stderr = _run_explore(d)
        assert rc == 0, f"exit {rc}, stderr={stderr}"
        assert "const DATA = " in stdout

        # Extract JSON between sentinel comments emitted by compose_explorer
        match = re.search(r"/\*DATA_START\*/\s*const DATA = (.*?);\s*/\*DATA_END\*/", stdout, re.DOTALL)
        assert match is not None, "DATA sentinel comments not found"
        data_str = match.group(1)
        data = json.loads(data_str)
        assert "company_name" in data
        assert "views" in data
        assert "competitors" in data
        assert "company_moats" in data
        assert data["company_name"] == "SecureFlow"


def test_view_selector_has_both_views() -> None:
    """View selector should contain options for primary and secondary views."""
    arts = _all_artifacts()
    with _make_artifact_dir(arts) as d:
        rc, stdout, stderr = _run_explore(d)
        assert rc == 0, f"exit {rc}, stderr={stderr}"
        # The view labels include axis names from our fixture
        assert "Deployment Complexity" in stdout
        assert "Latency Impact" in stdout


def test_output_flag() -> None:
    """The -o flag writes to file and emits a JSON receipt."""
    arts = _all_artifacts()
    with _make_artifact_dir(arts) as d:
        out_path = os.path.join(d, "explorer.html")
        rc, stdout, stderr = _run_explore(d, ["-o", out_path])
        assert rc == 0, f"exit {rc}, stderr={stderr}"
        assert os.path.exists(out_path)
        receipt = json.loads(stdout.strip())
        assert receipt["ok"] is True
        assert receipt["bytes"] > 0


def test_missing_moat_scores() -> None:
    """Works without moat_scores.json — no crash."""
    arts = _all_artifacts()
    del arts["moat_scores.json"]
    with _make_artifact_dir(arts) as d:
        rc, stdout, stderr = _run_explore(d)
        assert rc == 0, f"exit {rc}, stderr={stderr}"
        assert "</html>" in stdout


def test_missing_report() -> None:
    """Works without report.json — no crash."""
    arts = _all_artifacts()
    del arts["report.json"]
    with _make_artifact_dir(arts) as d:
        rc, stdout, stderr = _run_explore(d)
        assert rc == 0, f"exit {rc}, stderr={stderr}"
        assert "</html>" in stdout


def test_xss_safety() -> None:
    """Malicious company name is escaped in embedded JSON."""
    arts = _all_artifacts()
    arts["product_profile.json"] = dict(arts["product_profile.json"])
    arts["product_profile.json"]["company_name"] = "</script><script>alert(1)</script>"
    with _make_artifact_dir(arts) as d:
        rc, stdout, stderr = _run_explore(d)
        assert rc == 0, f"exit {rc}, stderr={stderr}"
        # The raw </script> should be escaped as <\/script>
        assert "</script><script>alert(1)</script>" not in stdout
        assert "<\\/script>" in stdout


def test_plotly_url_not_top_level_script() -> None:
    """Plotly CDN URL exists in HTML but not as a top-level <script src>."""
    arts = _all_artifacts()
    with _make_artifact_dir(arts) as d:
        rc, stdout, stderr = _run_explore(d)
        assert rc == 0, f"exit {rc}, stderr={stderr}"
        # The URL should be somewhere in the HTML (in the lazy loader JS)
        assert "plotly" in stdout.lower()
        # But NOT as a top-level script tag
        checker = _ExternalResourceChecker()
        checker.feed(stdout)
        plotly_scripts = [s for s in checker.external_scripts if "plotly" in s.lower()]
        assert len(plotly_scripts) == 0, "Plotly should not be a top-level <script src>"


def test_3d_fallback_message() -> None:
    """HTML contains a 3D fallback message element."""
    arts = _all_artifacts()
    with _make_artifact_dir(arts) as d:
        rc, stdout, stderr = _run_explore(d)
        assert rc == 0, f"exit {rc}, stderr={stderr}"
        assert "3d-fallback" in stdout
        assert "open in browser" in stdout.lower() or "browser environment" in stdout.lower()


def test_axis_rationale_container_exists() -> None:
    """Explorer HTML contains the axis-rationale container element."""
    arts = _all_artifacts()
    with _make_artifact_dir(arts) as d:
        rc, stdout, stderr = _run_explore(d)
        assert rc == 0, f"exit {rc}, stderr={stderr}"
        assert 'id="axis-rationale"' in stdout, "Should contain axis-rationale container"


def test_axis_rationale_render_uses_escaping() -> None:
    """The JS render path for axis rationale uses escHtml for safety."""
    arts = _all_artifacts()
    with _make_artifact_dir(arts) as d:
        rc, stdout, stderr = _run_explore(d)
        assert rc == 0, f"exit {rc}, stderr={stderr}"
        # Structural check: the JS near 'axis-rationale' uses escHtml
        import re

        # Find the JS block that populates the rationale div
        rationale_js = re.search(
            r"axis-rationale.*?escHtml\(.*?rationale",
            stdout,
            re.DOTALL | re.IGNORECASE,
        )
        assert rationale_js is not None, "JS code populating axis-rationale should use escHtml on rationale values"


def test_axis_rationale_in_embedded_data() -> None:
    """Rationale text from fixtures is present in the embedded DATA payload."""

    arts = _all_artifacts()
    with _make_artifact_dir(arts) as d:
        rc, stdout, stderr = _run_explore(d)
        assert rc == 0, f"exit {rc}, stderr={stderr}"
        # Extract the DATA JSON
        match = re.search(
            r"/\*DATA_START\*/\s*const DATA = (.*?);\s*/\*DATA_END\*/",
            stdout,
            re.DOTALL,
        )
        assert match is not None
        import json

        data = json.loads(match.group(1))
        # Check rationale exists in views
        assert len(data["views"]) >= 1
        v = data["views"][0]
        assert v.get("x_axis", {}).get("rationale"), "View should have x_axis rationale in DATA"


# ---------------------------------------------------------------------------
# Audit regression tests (a4: explore.py)
# ---------------------------------------------------------------------------


def test_non_dict_artifact_does_not_crash() -> None:
    """A top-level JSON array artifact must degrade to the corrupt path, not
    crash explore.py with AttributeError (audit cp-scripts-6)."""
    with _make_artifact_dir(_all_artifacts()) as d:
        with open(os.path.join(d, "report.json"), "w") as f:
            f.write('["x"]')
        rc, stdout, stderr = _run_explore(d)
        assert "Traceback" not in stderr
        assert rc == 0, f"exit {rc}, stderr={stderr}"
        assert "<html" in stdout.lower()


def test_3d_axes_bar_initially_hidden() -> None:
    """The #3d-axes-bar div must not carry a live 'display: flex' in its static
    style — the dead duplicate that overrode the intended display:none is removed
    (audit cp-scripts-8). render3D sets display='flex' at runtime instead."""
    with _make_artifact_dir(_all_artifacts()) as d:
        rc, stdout, _stderr = _run_explore(d)
        assert rc == 0
        # Isolate the axes-bar div's opening tag.
        idx = stdout.find('id="3d-axes-bar"')
        assert idx != -1
        tag = stdout[idx : stdout.find(">", idx)]
        assert "display:none" in tag
        # The static style must not also declare display:flex (that masked the hide).
        assert "display: flex" not in tag and "display:flex" not in tag


def _extract_data_payload(stdout: str) -> dict[str, Any]:
    """Extract and parse the embedded `const DATA = ...` JSON payload."""

    match = re.search(r"/\*DATA_START\*/\s*const DATA = (.*?);\s*/\*DATA_END\*/", stdout, re.DOTALL)
    assert match is not None, "DATA sentinel comments not found"
    payload = json.loads(match.group(1))
    assert isinstance(payload, dict)
    return payload


def test_prefers_scored_differentiation_claims_over_draft_placeholder() -> None:
    """positioning.json carries a DRAFT placeholder claim (written before
    POSITIONING_SCORING runs); positioning_scores.json carries the real scored
    claim with a verdict. The explorer must surface the scored claim and must
    NOT carry the placeholder text — the placeholder was never meant to reach
    the founder."""
    arts = _all_artifacts()

    pos = dict(arts["positioning.json"])
    pos["differentiation_claims"] = [{"claim": "DRAFT — stress-tested in positioning_scores.json"}]
    arts["positioning.json"] = pos

    ps = dict(arts["positioning_scores.json"])
    ps["differentiation_claims"] = [
        {
            "claim": "Sub-5ms latency vs. competitors' 50-200ms",
            "verifiable": True,
            "evidence": "SDK-based approach avoids network hop",
            "challenge": "No independent benchmark found",
            "verdict": "holds",
        }
    ]
    arts["positioning_scores.json"] = ps

    with _make_artifact_dir(arts) as d:
        rc, stdout, stderr = _run_explore(d)
        assert rc == 0, f"exit {rc}, stderr={stderr}"
        data = _extract_data_payload(stdout)
        claims = data["diff_claims"]
        assert any(c.get("claim") == "Sub-5ms latency vs. competitors' 50-200ms" for c in claims), (
            f"scored claim missing from diff_claims: {claims}"
        )
        assert not any("DRAFT" in c.get("claim", "") for c in claims), (
            f"draft placeholder claim leaked into diff_claims: {claims}"
        )
        assert "DRAFT — stress-tested in positioning_scores.json" not in stdout


def test_falls_back_to_positioning_claims_when_scores_have_none() -> None:
    """When positioning_scores.json carries no differentiation_claims, the
    explorer must still fall back to positioning.json's claims rather than
    shipping an empty stress-test section."""
    arts = _all_artifacts()
    ps = dict(arts["positioning_scores.json"])
    ps["differentiation_claims"] = []
    arts["positioning_scores.json"] = ps

    with _make_artifact_dir(arts) as d:
        rc, stdout, stderr = _run_explore(d)
        assert rc == 0, f"exit {rc}, stderr={stderr}"
        data = _extract_data_payload(stdout)
        claims = data["diff_claims"]
        assert len(claims) >= 1, "fallback to positioning.json claims must not yield an empty section"
        # VALID_POSITIONING's differentiation_claims (conftest fixture) includes this claim text.
        assert any("2B+ API calls" in c.get("claim", "") for c in claims)


def test_scoring_basis_absent_is_null_in_data_payload() -> None:
    """Absent scoring_basis must be carried through as null/absent in DATA, not
    silently defaulted — the JS caption renders 'Not declared' for exactly this
    payload shape."""
    arts = _all_artifacts()
    with _make_artifact_dir(arts) as d:
        rc, stdout, stderr = _run_explore(d)
        assert rc == 0, f"exit {rc}, stderr={stderr}"
        data = _extract_data_payload(stdout)
        assert data.get("scoring_basis") is None
        assert 'id="scoring-basis-caption"' in stdout


def test_scoring_basis_declared_value_carried_into_data_payload() -> None:
    """A declared scoring_basis (from positioning_scores.json) must be carried
    verbatim into the DATA payload so the JS caption can label it."""
    arts = _all_artifacts()
    ps = dict(arts["positioning_scores.json"])
    ps["scoring_basis"] = "roadmap_12mo"
    arts["positioning_scores.json"] = ps
    with _make_artifact_dir(arts) as d:
        rc, stdout, stderr = _run_explore(d)
        assert rc == 0, f"exit {rc}, stderr={stderr}"
        data = _extract_data_payload(stdout)
        assert data.get("scoring_basis") == "roadmap_12mo"


def test_docstring_discloses_plotly_cdn() -> None:
    """The explore.py module docstring must disclose the Plotly CDN dependency
    for the 3D tab rather than claim blanket 'self-contained' (audit cp-scripts-4)."""
    with open(SCRIPT, encoding="utf-8") as f:
        src = f.read()
    doc_end = src.index('"""', src.index('"""') + 3)
    docstring = src[:doc_end]
    assert "3D" in docstring or "Plotly" in docstring
    assert "CDN" in docstring


# ---------------------------------------------------------------------------
# Sibling-shaped axis rationale (Task 1), scored-layer rendering (Task 3),
# and optional view label (Task 4)
# ---------------------------------------------------------------------------


def test_sibling_shaped_rationale_normalized_into_embedded_data() -> None:
    """Regression guard for the silently-lost axis rationale defect: a view
    carrying the axis rationale as a view-level sibling (x_axis_rationale /
    y_axis_rationale — the shape the dispatch templates used to instruct)
    must be normalized server-side into the nested view.x_axis.rationale
    shape the embedded JS reads (render2D reads view.x_axis.rationale
    directly — that read path is deliberately untouched by this fix)."""
    arts = _all_artifacts()
    pos = dict(arts["positioning.json"])
    new_views = []
    for v in pos["views"]:
        v2 = dict(v)
        x_rationale = v2["x_axis"].get("rationale", "")
        y_rationale = v2["y_axis"].get("rationale", "")
        v2["x_axis"] = {k: val for k, val in v2["x_axis"].items() if k != "rationale"}
        v2["y_axis"] = {k: val for k, val in v2["y_axis"].items() if k != "rationale"}
        v2["x_axis_rationale"] = x_rationale
        v2["y_axis_rationale"] = y_rationale
        new_views.append(v2)
    pos["views"] = new_views
    arts["positioning.json"] = pos

    with _make_artifact_dir(arts) as d:
        rc, stdout, stderr = _run_explore(d)
        assert rc == 0, f"exit {rc}, stderr={stderr}"
        data = _extract_data_payload(stdout)
        v = data["views"][0]
        assert v.get("x_axis", {}).get("rationale"), (
            "sibling-shaped rationale must be folded into the nested x_axis.rationale the JS reads"
        )
        assert "key differentiator" in v["x_axis"]["rationale"].lower()


def test_sibling_shaped_rationale_nested_wins_when_both_present() -> None:
    """When a view carries both shapes and they differ, the nested (canonical)
    value must win — the normalization must not overwrite an already-nested
    rationale with the sibling's.

    Exercised on `positioning_scores.json`, which is where the rationale is now sourced from. The
    precedence rule is unchanged and still lives in `_axis_compat`; only the artifact it applies to
    moved. Asserting it on the draft would no longer reach the renderer at all.
    """
    arts = copy.deepcopy(_all_artifacts())
    sv = arts["positioning_scores.json"]["views"][0]
    sv["x_axis"] = {"name": "X", "rationale": "Nested wins this one"}
    sv["x_axis_rationale"] = "Sibling loses this one"

    with _make_artifact_dir(arts) as d:
        rc, stdout, stderr = _run_explore(d)
        assert rc == 0, f"exit {rc}, stderr={stderr}"
        data = _extract_data_payload(stdout)
        assert data["views"][0]["x_axis"]["rationale"] == "Nested wins this one"


def test_view_score_panel_container_exists() -> None:
    """Explorer HTML contains the view-score-panel container element (Task 3:
    the scored layer — differentiation score, rank, vanity flags — must
    render, not just sit unused in DATA.view_scores)."""
    arts = _all_artifacts()
    with _make_artifact_dir(arts) as d:
        rc, stdout, stderr = _run_explore(d)
        assert rc == 0, f"exit {rc}, stderr={stderr}"
        assert 'id="view-score-panel"' in stdout


def test_view_score_panel_renders_differentiation_score_and_rank() -> None:
    """The JS must read DATA.view_scores and render a differentiation score
    and a rank string following the 'Rank N of M ranked' convention — M is
    competitor_count + 1 (the startup counted among the ranked entities),
    never 'of M competitors'."""
    arts = _all_artifacts()
    with _make_artifact_dir(arts) as d:
        rc, stdout, stderr = _run_explore(d)
        assert rc == 0, f"exit {rc}, stderr={stderr}"
        assert "DATA.view_scores" in stdout
        assert "Differentiation score" in stdout
        assert "totalRanked = (vs.competitor_count || 0) + 1" in stdout
        assert "totalRanked + ' ranked" in stdout
        assert "competitors</div>" not in stdout, "must never render 'of M competitors'"


def test_view_score_panel_renders_vanity_flags() -> None:
    """A vanity-flagged axis (the fixture's secondary view has
    x_axis_vanity_flag=True) must be capable of rendering a vanity warning in
    the score panel."""
    arts = _all_artifacts()
    with _make_artifact_dir(arts) as d:
        rc, stdout, stderr = _run_explore(d)
        assert rc == 0, f"exit {rc}, stderr={stderr}"
        assert "x_axis_vanity_flag" in stdout
        assert "y_axis_vanity_flag" in stdout
        assert "vanity-flag" in stdout
        assert "Vanity axis warning" in stdout


def test_diff_claims_panel_renders_humanized_verdict() -> None:
    """Task 3: DATA.diff_claims must actually be rendered — a claim card with
    the claim text and a humanized verdict badge, not just embedded and
    ignored. The fixture's differentiation_claims include a
    'partially_holds' verdict, which humanize() must convert away from the
    raw snake_case token."""
    arts = _all_artifacts()
    with _make_artifact_dir(arts) as d:
        rc, stdout, stderr = _run_explore(d)
        assert rc == 0, f"exit {rc}, stderr={stderr}"
        assert 'id="diff-claims-panel"' in stdout
        assert 'id="diff-claims-list"' in stdout
        assert "renderDiffClaims" in stdout
        assert "DATA.diff_claims" in stdout
        assert "humanize(verdict)" in stdout
        assert "verdict-badge" in stdout
        data = _extract_data_payload(stdout)
        assert any(c.get("verdict") == "partially_holds" for c in data["diff_claims"]), (
            "fixture must actually carry a snake_case verdict for this test to be meaningful"
        )


def test_diff_claims_panel_placeholder_when_no_claims() -> None:
    """No differentiation claims (neither scored nor draft) must render a
    clear empty-state message, not a blank panel."""
    arts = _all_artifacts()
    ps = dict(arts["positioning_scores.json"])
    ps["differentiation_claims"] = []
    arts["positioning_scores.json"] = ps
    pos = dict(arts["positioning.json"])
    pos["differentiation_claims"] = []
    arts["positioning.json"] = pos

    with _make_artifact_dir(arts) as d:
        rc, stdout, stderr = _run_explore(d)
        assert rc == 0, f"exit {rc}, stderr={stderr}"
        assert "No differentiation claims tested" in stdout


def test_view_label_preferred_in_selector_option() -> None:
    """Task 4: an optional views[].label, when present, is used verbatim for
    the view-selector option text instead of the title-cased `id`."""
    arts = _all_artifacts()
    pos = dict(arts["positioning.json"])
    pos["views"] = [dict(pos["views"][0])]
    pos["views"][0]["label"] = "Speed vs. Privacy"
    arts["positioning.json"] = pos
    with _make_artifact_dir(arts) as d:
        rc, stdout, stderr = _run_explore(d)
        assert rc == 0, f"exit {rc}, stderr={stderr}"
        assert "v.label ||" in stdout
        data = _extract_data_payload(stdout)
        assert data["views"][0]["label"] == "Speed vs. Privacy"


def test_explorer_stays_self_contained_with_new_panels() -> None:
    """The new view-score and differentiation-claims panels must not
    introduce any new external network requests — the explorer stays
    self-contained apart from the pre-existing, deliberately-lazy 3D Plotly
    CDN load (which is injected at runtime, not a static tag, and so never
    shows up here either)."""
    arts = _all_artifacts()
    with _make_artifact_dir(arts) as d:
        rc, stdout, stderr = _run_explore(d)
        assert rc == 0, f"exit {rc}, stderr={stderr}"
        checker = _ExternalResourceChecker()
        checker.feed(stdout)
        assert len(checker.external_stylesheets) == 0
        assert len(checker.external_scripts) == 0, f"top-level external scripts found: {checker.external_scripts}"


# ---------------------------------------------------------------------------
# Dead-payload coverage lives in test_dead_payload.py, which scans every embedder in one place
# and distinguishes 'unread' from 'unverifiable' (this file's earlier scan matched dotted access
# only, so a computed-name read read as a dead key).


def test_axis_rationale_comes_from_the_scored_artifact_not_the_draft() -> None:
    """Same defect as the static report: the explorer read its axis rationale from the pre-scoring
    draft, whose rationales are placeholders by design, so an internal ALLCAPS dispatch name reached
    founder-visible text.

    `explore.py` already prefers the scored file for `differentiation_claims` twenty-five lines below
    the axis path, with a comment explaining exactly why — the fix existed in the same function and had
    not been applied here.

    The two fixtures carry the same rationale text, so the placeholder is injected to tell the sources
    apart; asserting against them unmodified would prove nothing.
    """
    artifacts = copy.deepcopy(_all_artifacts())
    placeholder = "Placeholder — replaced by POSITIONING_SCORING dispatch"
    for view in artifacts["positioning.json"]["views"]:
        for axis in ("x_axis", "y_axis"):
            if isinstance(view.get(axis), dict):
                view[axis]["rationale"] = placeholder
    scored = artifacts["positioning_scores.json"]["views"][0]["x_axis_rationale"]

    with _make_artifact_dir(artifacts) as d:
        rc, stdout, stderr = _run_explore(d)
        assert rc == 0, f"exit {rc}, stderr={stderr}"
        assert "POSITIONING_SCORING" not in stdout, (
            "an internal dispatch name reached founder-visible explorer HTML — the axis rationale is "
            "being read from the pre-scoring draft"
        )
        assert scored in stdout, f"the scored rationale never reached the explorer; expected {scored!r}"
