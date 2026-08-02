#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
Regression tests for competitive positioning HTML visualization script.

Run: pytest founder-skills/tests/test_visualize_competitive_positioning.py -v
All tests use subprocess to exercise the script exactly as the agent does.
"""

from __future__ import annotations

import contextlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import types
from collections.abc import Generator
from typing import Any

from conftest_competitive_positioning import (
    VALID_LANDSCAPE,
    VALID_MOAT_SCORES,
    VALID_POSITIONING,
    VALID_POSITIONING_SCORES,
    VALID_REPORT,
)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CP_SCRIPTS_DIR = os.path.join(os.path.dirname(SCRIPT_DIR), "skills", "competitive-positioning", "scripts")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def _make_artifact_dir(artifacts: dict[str, Any]) -> Generator[str, None, None]:
    """Create a temp dir with JSON artifacts. Yields dir path, cleans up on exit."""
    d = tempfile.mkdtemp(prefix="test-vis-cp-")
    try:
        for name, data in artifacts.items():
            path = os.path.join(d, name)
            if isinstance(data, str):
                with open(path, "w", encoding="utf-8") as f:
                    f.write(data)
            else:
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(data, f)
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)


def _all_artifacts() -> dict[str, Any]:
    """Return all artifacts for a complete visualization."""
    return {
        "landscape.json": VALID_LANDSCAPE,
        "positioning.json": VALID_POSITIONING,
        "positioning_scores.json": VALID_POSITIONING_SCORES,
        "moat_scores.json": VALID_MOAT_SCORES,
        "report.json": VALID_REPORT,
    }


def _run_visualize(
    artifact_dir: str,
    extra_args: list[str] | None = None,
) -> tuple[int, str, str]:
    """Run visualize.py and return (exit_code, stdout, stderr)."""
    cmd = [
        sys.executable,
        os.path.join(CP_SCRIPTS_DIR, "visualize.py"),
        "--dir",
        artifact_dir,
    ]
    if extra_args:
        cmd.extend(extra_args)
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode, result.stdout, result.stderr


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_generates_html() -> None:
    """Produces output containing <html> and </html>."""
    with _make_artifact_dir(_all_artifacts()) as d:
        rc, stdout, stderr = _run_visualize(d)
        assert rc == 0, f"exit {rc}, stderr={stderr}"
        assert "<html" in stdout
        assert "</html>" in stdout
        assert "<!DOCTYPE html>" in stdout


def test_positioning_map_svg() -> None:
    """HTML contains SVG with circle elements for competitors."""
    with _make_artifact_dir(_all_artifacts()) as d:
        rc, stdout, stderr = _run_visualize(d)
        assert rc == 0, f"exit {rc}, stderr={stderr}"
        assert "<svg" in stdout
        assert "<circle" in stdout
        # Each competitor + startup should have a circle
        assert stdout.count("<circle") >= 3  # at least startup + 2 competitors


def test_moat_radar_svg() -> None:
    """HTML contains SVG with polygon element for radar chart."""
    with _make_artifact_dir(_all_artifacts()) as d:
        rc, stdout, stderr = _run_visualize(d)
        assert rc == 0, f"exit {rc}, stderr={stderr}"
        assert "<polygon" in stdout
        # Should have at least 2 polygons: startup moat profile + competitor overlay
        assert stdout.count("<polygon") >= 2


def test_competitor_table() -> None:
    """HTML contains <table> with competitor names."""
    with _make_artifact_dir(_all_artifacts()) as d:
        rc, stdout, stderr = _run_visualize(d)
        assert rc == 0, f"exit {rc}, stderr={stderr}"
        assert "<table" in stdout
        assert "Salt Security" in stdout
        assert "Noname Security" in stdout
        assert "Wallarm" in stdout
        assert "Traceable AI" in stdout


def test_startup_highlighted() -> None:
    """_startup rendered with distinct styling and 'Your Company' label."""
    with _make_artifact_dir(_all_artifacts()) as d:
        rc, stdout, stderr = _run_visualize(d)
        assert rc == 0, f"exit {rc}, stderr={stderr}"
        # Should use the company name or "Your Company" for _startup
        assert "SecureFlow" in stdout or "Your Company" in stdout


def test_secondary_view() -> None:
    """If secondary view present, alternate positioning chart rendered."""
    with _make_artifact_dir(_all_artifacts()) as d:
        rc, stdout, stderr = _run_visualize(d)
        assert rc == 0, f"exit {rc}, stderr={stderr}"
        # Secondary view axes should appear
        assert "Latency Impact" in stdout
        assert "Protocol Coverage" in stdout
        # Should have at least 2 positioning map SVGs
        assert "Deployment Complexity" in stdout


def test_defensibility_timeline() -> None:
    """When trajectory data provided, timeline SVG elements present."""
    with _make_artifact_dir(_all_artifacts()) as d:
        rc, stdout, stderr = _run_visualize(d)
        assert rc == 0, f"exit {rc}, stderr={stderr}"
        # Trajectory data is present in moat_assessments (building, stable, eroding)
        # Should render timeline indicators
        assert "building" in stdout.lower() or "eroding" in stdout.lower() or "stable" in stdout.lower()


def test_defensibility_timeline_labels_fit_viewbox() -> None:
    """Trajectory labels (e.g. 'Building') must fit inside the timeline SVG viewBox.

    SVG clips content outside the viewBox by default, so a label placed too
    close to the right edge renders truncated ('Buildir').
    """
    import re

    with _make_artifact_dir(_all_artifacts()) as d:
        rc, stdout, stderr = _run_visualize(d)
        assert rc == 0, f"exit {rc}, stderr={stderr}"

        # Isolate the Defensibility Timeline SVG
        m = re.search(r"Defensibility Timeline</h2>(<svg.*?</svg>)", stdout, re.DOTALL)
        assert m, "Defensibility Timeline SVG not found"
        svg = m.group(1)

        vb = re.search(r'viewBox="0 0 (\d+) (\d+)"', svg)
        assert vb, "timeline SVG missing viewBox"
        svg_w = float(vb.group(1))

        # Every trajectory label text element must fit: x + estimated width <= svg_w.
        # ~0.62em average glyph width is a conservative estimate for the brand font.
        labels = re.findall(r'<text x="(\d+)" y="\d+" font-size="(\d+)" fill="#7D90A3">([^<]+)</text>', svg)
        assert labels, "no trajectory labels found in timeline SVG"
        for x, font_size, text in labels:
            est_width = len(text) * float(font_size) * 0.62
            assert float(x) + est_width <= svg_w, (
                f"trajectory label {text!r} at x={x} (est. width {est_width:.0f}) "
                f"overflows viewBox width {svg_w:.0f} and will be clipped"
            )


def test_handles_missing_optional() -> None:
    """Works without secondary view or trajectory data."""
    arts = _all_artifacts()
    # Remove secondary view
    pos = dict(arts["positioning.json"])
    pos["views"] = [v for v in pos["views"] if v["id"] == "primary"]
    arts["positioning.json"] = pos

    pos_scores = dict(arts["positioning_scores.json"])
    pos_scores["views"] = [v for v in pos_scores["views"] if v["view_id"] == "primary"]
    arts["positioning_scores.json"] = pos_scores

    # Remove trajectory data from moat assessments
    pos2 = dict(arts["positioning.json"])
    for slug in pos2["moat_assessments"]:
        for moat in pos2["moat_assessments"][slug]["moats"]:
            del moat["trajectory"]
    arts["positioning.json"] = pos2

    with _make_artifact_dir(arts) as d:
        rc, stdout, stderr = _run_visualize(d)
        assert rc == 0, f"exit {rc}, stderr={stderr}"
        assert "<html" in stdout
        assert "</html>" in stdout
        # Secondary view axes should NOT appear
        assert "Latency Impact" not in stdout


def test_output_flag() -> None:
    """-o writes HTML to file and emits JSON receipt to stdout."""
    with _make_artifact_dir(_all_artifacts()) as d:
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
            tmp = f.name
        try:
            rc, stdout, stderr = _run_visualize(d, extra_args=["-o", tmp])
            assert rc == 0, f"exit {rc}, stderr={stderr}"
            receipt = json.loads(stdout)
            assert receipt["ok"] is True
            with open(tmp, encoding="utf-8") as fh:
                content = fh.read()
            assert "<!DOCTYPE html>" in content
            assert "SecureFlow" in content
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)


def test_self_contained() -> None:
    """No external URLs in src/href attributes (except allowed)."""
    import re

    with _make_artifact_dir(_all_artifacts()) as d:
        rc, stdout, stderr = _run_visualize(d)
        assert rc == 0, f"exit {rc}, stderr={stderr}"
        allowed = {
            "https://github.com/lool-ventures/founder-skills",
            "https://github.com/lool-ventures/founder-skills/discussions/new?category=ideas-feedback",
            "https://lool.vc",
        }
        src_matches = re.findall(r'(?:src|href)\s*=\s*"([^"]*)"', stdout)
        for url in src_matches:
            if url in allowed:
                continue
            assert not url.startswith("http://"), f"External HTTP URL: {url}"
            assert not url.startswith("https://"), f"External HTTPS URL: {url}"


def test_vanity_flag_indicator() -> None:
    """Vanity-flagged axes get a visual indicator."""
    with _make_artifact_dir(_all_artifacts()) as d:
        rc, stdout, stderr = _run_visualize(d)
        assert rc == 0, f"exit {rc}, stderr={stderr}"
        # The secondary view has x_axis_vanity_flag=True for "Latency Impact"
        # Should have some visual indicator (dashed, warning, vanity)
        lower = stdout.lower()
        assert "vanity" in lower or "stroke-dasharray" in lower or "warning" in lower


def test_missing_report() -> None:
    """Works even without report.json."""
    arts = _all_artifacts()
    del arts["report.json"]
    with _make_artifact_dir(arts) as d:
        rc, stdout, stderr = _run_visualize(d)
        assert rc == 0, f"exit {rc}, stderr={stderr}"
        assert "<html" in stdout


def test_missing_positioning_scores() -> None:
    """Works with missing positioning_scores.json (shows placeholder)."""
    arts = _all_artifacts()
    del arts["positioning_scores.json"]
    with _make_artifact_dir(arts) as d:
        rc, stdout, stderr = _run_visualize(d)
        assert rc == 0, f"exit {rc}, stderr={stderr}"
        assert "<html" in stdout


def test_xss_safety() -> None:
    """Company name with script tag is escaped."""
    arts = _all_artifacts()
    report = dict(arts["report.json"])
    report["metadata"] = dict(report["metadata"])
    report["metadata"]["company_name"] = "<script>alert(1)</script>"
    arts["report.json"] = report
    with _make_artifact_dir(arts) as d:
        rc, stdout, stderr = _run_visualize(d)
        assert rc == 0, f"exit {rc}, stderr={stderr}"
        assert "<script>alert(1)</script>" not in stdout
        assert "&lt;script&gt;" in stdout


def test_competitor_table_sorted_by_defensibility() -> None:
    """Competitor table is sorted by overall_defensibility (high first)."""
    with _make_artifact_dir(_all_artifacts()) as d:
        rc, stdout, stderr = _run_visualize(d)
        assert rc == 0, f"exit {rc}, stderr={stderr}"
        # Salt Security has "high" defensibility, should appear before others
        salt_pos = stdout.find("Salt Security")
        noname_pos = stdout.find("Noname Security")
        manual_pos = stdout.find("Manual API monitoring")
        # Salt (high) should come before Noname (moderate) in table
        # Find them within a <table> context
        assert salt_pos < noname_pos or salt_pos < manual_pos, (
            "Salt Security (high defensibility) should appear before lower-ranked competitors in table"
        )


def test_deterministic_output() -> None:
    """Run twice -> identical HTML bytes."""
    with _make_artifact_dir(_all_artifacts()) as d:
        rc1, out1, _ = _run_visualize(d)
        rc2, out2, _ = _run_visualize(d)
        assert rc1 == 0
        assert rc2 == 0
        assert out1 == out2, "Output differs between runs"


def test_bubble_radius_by_defensibility() -> None:
    """Plotted circle radii reflect overall_defensibility from moat_scores."""
    import re

    arts = _all_artifacts()
    with _make_artifact_dir(arts) as d:
        rc, stdout, stderr = _run_visualize(d)
        assert rc == 0, f"exit {rc}, stderr={stderr}"
        svg_blocks = re.findall(r"<svg[^>]*>.*?</svg>", stdout, re.DOTALL)
        svg_content = "".join(svg_blocks)
        circles = re.findall(r"<circle[^>]*>", svg_content)
        high_circles = [c for c in circles if 'r="12"' in c]
        assert len(high_circles) >= 1, "high defensibility should produce r=12 circles in SVG"
        startup_circles = [c for c in circles if 'stroke="#fff"' in c]
        assert all('r="8"' in c for c in startup_circles), "_startup should have r=8"
        low_circles = [c for c in circles if 'r="5"' in c]
        assert len(low_circles) >= 1, "low defensibility should produce r=5 circles in SVG"


def test_bubble_color_by_category() -> None:
    """Plotted circle fill colors reflect competitor category."""
    import re

    arts = _all_artifacts()
    with _make_artifact_dir(arts) as d:
        rc, stdout, stderr = _run_visualize(d)
        assert rc == 0, f"exit {rc}, stderr={stderr}"
        svg_blocks = re.findall(r"<svg[^>]*>.*?</svg>", stdout, re.DOTALL)
        svg_content = "".join(svg_blocks)
        circles = re.findall(r"<circle[^>]*>", svg_content)
        startup_circles = [c for c in circles if 'stroke="#fff"' in c]
        assert all("#e11d48" in c for c in startup_circles), "_startup circles should be rose/red"
        assert any("#0D549D" in c for c in circles), "direct competitors should be dark blue"
        assert any("#A6AEB5" in c for c in circles), "do_nothing should be gray"


def test_startup_minimum_radius() -> None:
    """_startup radius is at least 8 even with low defensibility."""
    import re

    arts = _all_artifacts()
    moat = dict(arts["moat_scores.json"])
    moat["companies"] = dict(moat["companies"])
    moat["companies"]["_startup"] = dict(moat["companies"]["_startup"])
    moat["companies"]["_startup"]["overall_defensibility"] = "low"
    arts["moat_scores.json"] = moat
    with _make_artifact_dir(arts) as d:
        rc, stdout, stderr = _run_visualize(d)
        assert rc == 0, f"exit {rc}, stderr={stderr}"
        startup_circles = re.findall(r'<circle[^>]*stroke="#fff"[^>]*/>', stdout)
        assert len(startup_circles) >= 1, "Should find at least one startup circle"
        for circle in startup_circles:
            assert 'r="5"' not in circle, "_startup should never have r=5"


def test_size_legend_present() -> None:
    """HTML contains a size legend with low/moderate/high labels."""
    arts = _all_artifacts()
    with _make_artifact_dir(arts) as d:
        rc, stdout, stderr = _run_visualize(d)
        assert rc == 0, f"exit {rc}, stderr={stderr}"
        low = stdout.lower()
        assert "size-legend" in low or "size legend" in low, "Should contain size legend"


def test_color_legend_present() -> None:
    """HTML contains a color legend with category labels."""
    arts = _all_artifacts()
    with _make_artifact_dir(arts) as d:
        rc, stdout, stderr = _run_visualize(d)
        assert rc == 0, f"exit {rc}, stderr={stderr}"
        low = stdout.lower()
        assert "color-legend" in low or "color legend" in low, "Should contain color legend"


def test_graceful_no_moat_scores() -> None:
    """Without moat_scores.json, falls back to uniform radius (legacy behavior)."""
    import re

    arts = _all_artifacts()
    del arts["moat_scores.json"]
    with _make_artifact_dir(arts) as d:
        rc, stdout, stderr = _run_visualize(d)
        assert rc == 0, f"exit {rc}, stderr={stderr}"
        assert "<svg" in stdout, "Should still render SVG"
        svg_blocks = re.findall(r"<svg[^>]*>.*?</svg>", stdout, re.DOTALL)
        svg_content = "".join(svg_blocks)
        plotted_circles = re.findall(r'<circle[^>]*r="(\d+)"', svg_content)
        for r in plotted_circles:
            assert r in ("5", "8"), f"Without moat_scores, expected r=5 or r=8, got r={r}"


def test_graceful_no_landscape() -> None:
    """Without landscape.json, falls back to uniform color."""
    arts = _all_artifacts()
    del arts["landscape.json"]
    with _make_artifact_dir(arts) as d:
        rc, stdout, stderr = _run_visualize(d)
        assert rc == 0, f"exit {rc}, stderr={stderr}"
        assert "<svg" in stdout, "Should still render SVG"
        assert "#e11d48" in stdout, "_startup should still be rose/red"


def test_axis_rationale_displayed() -> None:
    """Axis rationale from positioning data appears in an axis-rationale block."""
    arts = _all_artifacts()
    with _make_artifact_dir(arts) as d:
        rc, stdout, stderr = _run_visualize(d)
        assert rc == 0, f"exit {rc}, stderr={stderr}"
        # Must have the rationale container
        assert 'class="axis-rationale"' in stdout, "Should contain axis-rationale block"
        # Check rationale text is inside the block (scoped check)
        import re

        rationale_blocks = re.findall(
            r'<div class="axis-rationale">(.*?)</div>\s*</div>',
            stdout,
            re.DOTALL,
        )
        assert len(rationale_blocks) >= 1, "Should have at least one rationale block"
        # The fixture has rationale text — check it appears in the block
        block_content = rationale_blocks[0]
        assert "Deployment Complexity" in block_content or "deployment" in block_content.lower()


def test_axis_rationale_omitted_when_missing() -> None:
    """No axis-rationale block when rationale is not in the data."""
    arts = _all_artifacts()
    # Strip rationale from views
    pos = dict(arts["positioning.json"])
    pos["views"] = []
    for v in arts["positioning.json"]["views"]:
        v2 = dict(v)
        v2["x_axis"] = {k: v for k, v in v2["x_axis"].items() if k != "rationale"}
        v2["y_axis"] = {k: v for k, v in v2["y_axis"].items() if k != "rationale"}
        pos["views"].append(v2)
    arts["positioning.json"] = pos
    with _make_artifact_dir(arts) as d:
        rc, stdout, stderr = _run_visualize(d)
        assert rc == 0, f"exit {rc}, stderr={stderr}"
        assert 'class="axis-rationale"' not in stdout, "Should not contain rationale block"


def test_axis_rationale_xss() -> None:
    """Malicious rationale text is HTML-escaped in the axis-rationale block."""
    import re

    arts = _all_artifacts()
    pos = dict(arts["positioning.json"])
    pos["views"] = []
    for v in arts["positioning.json"]["views"]:
        v2 = dict(v)
        v2["x_axis"] = dict(v2["x_axis"])
        v2["x_axis"]["rationale"] = '<script>alert("xss")</script>'
        pos["views"].append(v2)
    arts["positioning.json"] = pos
    with _make_artifact_dir(arts) as d:
        rc, stdout, stderr = _run_visualize(d)
        assert rc == 0, f"exit {rc}, stderr={stderr}"
        # Find the rationale block specifically
        rationale_blocks = re.findall(
            r'<div class="axis-rationale">(.*?)</div>\s*</div>',
            stdout,
            re.DOTALL,
        )
        assert len(rationale_blocks) >= 1
        block = rationale_blocks[0]
        assert "<script>" not in block, "Raw <script> should not appear in rationale block"
        assert "&lt;script&gt;" in block, "Script tag should be HTML-escaped"


# ---------------------------------------------------------------------------
# Audit regression test (a4: visualize.py)
# ---------------------------------------------------------------------------


def test_scoring_basis_not_declared_when_absent() -> None:
    """Absent scoring_basis must render as 'Not declared' next to the positioning
    map, never silently defaulted to 'shipped'."""
    with _make_artifact_dir(_all_artifacts()) as d:  # default positioning_scores has no scoring_basis key
        rc, stdout, stderr = _run_visualize(d)
        assert rc == 0, f"exit {rc}, stderr={stderr}"
        assert 'class="scoring-basis"' in stdout
        assert "Not declared" in stdout


def test_scoring_basis_shipped_label_rendered() -> None:
    arts = _all_artifacts()
    ps = dict(arts["positioning_scores.json"])
    ps["scoring_basis"] = "shipped"
    arts["positioning_scores.json"] = ps
    with _make_artifact_dir(arts) as d:
        rc, stdout, stderr = _run_visualize(d)
        assert rc == 0, f"exit {rc}, stderr={stderr}"
        assert "Shipped / verifiable surface" in stdout


def test_scoring_basis_roadmap_12mo_label_rendered() -> None:
    arts = _all_artifacts()
    ps = dict(arts["positioning_scores.json"])
    ps["scoring_basis"] = "roadmap_12mo"
    arts["positioning_scores.json"] = ps
    with _make_artifact_dir(arts) as d:
        rc, stdout, stderr = _run_visualize(d)
        assert rc == 0, f"exit {rc}, stderr={stderr}"
        assert "12-month roadmap" in stdout


def test_scoring_basis_mixed_label_rendered() -> None:
    arts = _all_artifacts()
    ps = dict(arts["positioning_scores.json"])
    ps["scoring_basis"] = "mixed"
    arts["positioning_scores.json"] = ps
    with _make_artifact_dir(arts) as d:
        rc, stdout, stderr = _run_visualize(d)
        assert rc == 0, f"exit {rc}, stderr={stderr}"
        assert 'class="scoring-basis"' in stdout
        assert "Mixed" in stdout


def test_non_dict_artifact_does_not_crash() -> None:
    """A top-level JSON array artifact must degrade to the placeholder/corrupt
    path, not crash visualize.py with AttributeError (audit cp-scripts-6)."""
    artifacts = _all_artifacts()
    artifacts["report.json"] = '["x"]'  # raw string → written verbatim
    with _make_artifact_dir(artifacts) as d:
        rc, stdout, stderr = _run_visualize(d)
        assert "Traceback" not in stderr
        assert rc == 0, f"exit {rc}, stderr={stderr}"
        assert "<html" in stdout.lower()


# ===========================================================================
# Key-coverage tests: producer output keys ⊆ renderer known sets
# ===========================================================================
#
# Invariant: when score_moats.py adds a new moat status, defensibility level,
# or trajectory value, the corresponding visualize.py maps must be updated.
# These tests pin the current complete sets so any new emitted key causes a
# loud failure with the offending name listed.
# ===========================================================================

_CP_VISUALIZE_SCRIPT = os.path.join(CP_SCRIPTS_DIR, "visualize.py")
_CP_EXPLORE_SCRIPT = os.path.join(CP_SCRIPTS_DIR, "explore.py")
_CP_SCORE_MOATS_SCRIPT = os.path.join(CP_SCRIPTS_DIR, "score_moats.py")
_CP_VALIDATE_LANDSCAPE_SCRIPT = os.path.join(CP_SCRIPTS_DIR, "validate_landscape.py")


def _load_cp_visualize() -> types.ModuleType:
    """Import competitive-positioning visualize.py with a unique sys.modules key.

    _theme is imported lazily inside a render function, so no stub is needed
    at module load time.
    """
    key = "_cp_keycov_visualize"
    if key in sys.modules:
        return sys.modules[key]  # type: ignore[return-value]
    spec = importlib.util.spec_from_file_location(key, _CP_VISUALIZE_SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = types.ModuleType(key)
    mod.__spec__ = spec  # type: ignore[assignment]
    mod.__file__ = _CP_VISUALIZE_SCRIPT  # type: ignore[assignment]
    sys.modules[key] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _load_cp_explore() -> types.ModuleType:
    """Import competitive-positioning explore.py with a unique sys.modules key."""
    key = "_cp_keycov_explore"
    if key in sys.modules:
        return sys.modules[key]  # type: ignore[return-value]
    spec = importlib.util.spec_from_file_location(key, _CP_EXPLORE_SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = types.ModuleType(key)
    mod.__spec__ = spec  # type: ignore[assignment]
    mod.__file__ = _CP_EXPLORE_SCRIPT  # type: ignore[assignment]
    sys.modules[key] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _load_cp_score_moats() -> types.ModuleType:
    """Import competitive-positioning score_moats.py with a unique sys.modules key."""
    key = "_cp_keycov_score_moats"
    if key in sys.modules:
        return sys.modules[key]  # type: ignore[return-value]
    spec = importlib.util.spec_from_file_location(key, _CP_SCORE_MOATS_SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = types.ModuleType(key)
    mod.__spec__ = spec  # type: ignore[assignment]
    mod.__file__ = _CP_SCORE_MOATS_SCRIPT  # type: ignore[assignment]
    sys.modules[key] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _load_cp_validate_landscape() -> types.ModuleType:
    """Import competitive-positioning validate_landscape.py with a unique sys.modules key."""
    key = "_cp_keycov_validate_landscape"
    if key in sys.modules:
        return sys.modules[key]  # type: ignore[return-value]
    spec = importlib.util.spec_from_file_location(key, _CP_VALIDATE_LANDSCAPE_SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = types.ModuleType(key)
    mod.__spec__ = spec  # type: ignore[assignment]
    mod.__file__ = _CP_VALIDATE_LANDSCAPE_SCRIPT  # type: ignore[assignment]
    sys.modules[key] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


# ---------------------------------------------------------------------------
# Test A: moat statuses → visualize._STATUS_SCORE coverage
# ---------------------------------------------------------------------------


class TestCpMoatStatusScoreCoverage:
    """Every moat status that score_moats.py can emit must appear in
    visualize.py's _STATUS_SCORE so the radar chart converts statuses to
    radial distances without silently treating unknown values as 0.

    Produced set is derived live from score_moats.VALID_STATUSES.
    """

    def test_all_moat_statuses_in_status_score(self) -> None:
        """Every moat status the producer emits must appear in _STATUS_SCORE."""
        produced = _load_cp_score_moats().VALID_STATUSES
        viz = _load_cp_visualize()
        score_keys: set[str] = set(viz._STATUS_SCORE.keys())

        missing = produced - score_keys
        assert not missing, (
            f"visualize._STATUS_SCORE is missing an entry for moat status(es) "
            f"emitted by score_moats.py: {sorted(missing)}. "
            f"Add entries to _STATUS_SCORE for each."
        )

    def test_producer_moat_statuses_min_count(self) -> None:
        """Guard against vacuous tests: VALID_STATUSES must have at least 5 statuses."""
        produced = _load_cp_score_moats().VALID_STATUSES
        assert len(produced) >= 5, (
            f"VALID_STATUSES expected >= 5 entries, got {len(produced)}. Check score_moats.VALID_STATUSES."
        )

    def test_status_score_min_count(self) -> None:
        """_STATUS_SCORE must cover at least the producer statuses."""
        produced = _load_cp_score_moats().VALID_STATUSES
        viz = _load_cp_visualize()
        assert len(viz._STATUS_SCORE) >= len(produced), (
            f"visualize._STATUS_SCORE has only {len(viz._STATUS_SCORE)} entries; expected >= {len(produced)}."
        )


# ---------------------------------------------------------------------------
# Test B: overall_defensibility levels → visualize._DEFENSIBILITY_COLORS coverage
# ---------------------------------------------------------------------------


class TestCpDefensibilityColorCoverage:
    """Every overall_defensibility level that score_moats.py can emit must
    appear in visualize.py's _DEFENSIBILITY_COLORS so the competitor table
    and timeline show the correct colour.

    Derived from: the 3 defensibility strings computed in
    score_moats._compute_aggregates(): "high", "moderate", "low".
    Pinned with a source-regex guard on each literal.
    """

    # Defensibility strings emitted by score_moats._compute_aggregates().
    PRODUCER_DEFENSIBILITY_LEVELS: set[str] = {
        "high",
        "moderate",
        "low",
    }

    def test_defensibility_literals_present_in_source(self) -> None:
        """Each level must appear as a string literal in score_moats.py."""
        with open(_CP_SCORE_MOATS_SCRIPT, encoding="utf-8") as fh:
            src = fh.read()
        for level in self.PRODUCER_DEFENSIBILITY_LEVELS:
            assert f'"{level}"' in src or f"'{level}'" in src, (
                f"Defensibility level {level!r} not found as a literal in score_moats.py. "
                f"Update PRODUCER_DEFENSIBILITY_LEVELS if _compute_aggregates() was changed."
            )

    def test_all_defensibility_levels_in_defensibility_colors(self) -> None:
        """Every defensibility level the producer emits must map to a colour."""
        viz = _load_cp_visualize()
        color_keys: set[str] = set(viz._DEFENSIBILITY_COLORS.keys())

        missing = self.PRODUCER_DEFENSIBILITY_LEVELS - color_keys
        assert not missing, (
            f"visualize._DEFENSIBILITY_COLORS is missing a colour entry for defensibility level(s) "
            f"emitted by score_moats.py: {sorted(missing)}. "
            f"Add entries to _DEFENSIBILITY_COLORS for each."
        )

    def test_producer_defensibility_levels_min_count(self) -> None:
        """Guard against vacuous tests: producer set must have exactly 3 levels."""
        assert len(self.PRODUCER_DEFENSIBILITY_LEVELS) == 3, (
            f"PRODUCER_DEFENSIBILITY_LEVELS expected 3 entries, got {len(self.PRODUCER_DEFENSIBILITY_LEVELS)}."
        )

    def test_defensibility_colors_min_count(self) -> None:
        """_DEFENSIBILITY_COLORS must cover at least the 3 producer levels."""
        viz = _load_cp_visualize()
        assert len(viz._DEFENSIBILITY_COLORS) >= 3, (
            f"visualize._DEFENSIBILITY_COLORS has only {len(viz._DEFENSIBILITY_COLORS)} entries; expected >= 3."
        )


# ---------------------------------------------------------------------------
# Test C: canonical moat dimensions → visualize._MOAT_DIM_LABELS coverage
# ---------------------------------------------------------------------------


class TestCpMoatDimLabelCoverage:
    """Every canonical moat dimension that score_moats.py evaluates must
    appear in visualize.py's _MOAT_DIM_LABELS so the radar axis shows a
    curated label instead of the mechanical fallback.

    Derived from: the 6 canonical moat dimension IDs used in SKILL.md and
    score_moats.py (_CANONICAL_MOAT_DIMS in visualize.py).
    """

    # The 6 canonical moat dimension IDs.
    PRODUCER_MOAT_DIMS: set[str] = {
        "network_effects",
        "data_advantages",
        "switching_costs",
        "regulatory_barriers",
        "cost_structure",
        "brand_reputation",
    }

    def test_all_moat_dims_in_moat_dim_labels(self) -> None:
        """Every canonical moat dimension must appear in _MOAT_DIM_LABELS."""
        viz = _load_cp_visualize()
        label_keys: set[str] = set(viz._MOAT_DIM_LABELS.keys())

        missing = self.PRODUCER_MOAT_DIMS - label_keys
        assert not missing, (
            f"visualize._MOAT_DIM_LABELS is missing a display label for moat dimension(s): "
            f"{sorted(missing)}. Add entries to _MOAT_DIM_LABELS for each."
        )

    def test_producer_moat_dims_min_count(self) -> None:
        """Guard against vacuous tests: producer set must have exactly 6 dimensions."""
        assert len(self.PRODUCER_MOAT_DIMS) == 6, (
            f"PRODUCER_MOAT_DIMS expected 6 entries, got {len(self.PRODUCER_MOAT_DIMS)}."
        )

    def test_moat_dim_labels_min_count(self) -> None:
        """_MOAT_DIM_LABELS must cover at least the 6 canonical dimensions."""
        viz = _load_cp_visualize()
        assert len(viz._MOAT_DIM_LABELS) >= 6, (
            f"visualize._MOAT_DIM_LABELS has only {len(viz._MOAT_DIM_LABELS)} entries; expected >= 6."
        )


# ---------------------------------------------------------------------------
# Test D: competitor category values → visualize._CATEGORY_COLORS coverage
# ---------------------------------------------------------------------------


class TestCpCategoryColorCoverage:
    """Every competitor category value that validate_landscape.py can emit
    must appear in visualize.py's _CATEGORY_COLORS so positioning-map bubbles
    receive the correct colour.

    validate_landscape.VALID_CATEGORIES is loaded live (covers "direct",
    "adjacent", "do_nothing", "emerging", "custom").  "_startup" is the
    renderer-internal sentinel slug — not present in VALID_CATEGORIES, but
    always rendered; it is pinned here with a documentary note.
    """

    # "_startup" is the renderer-internal sentinel, not a validate_landscape category.
    _RENDERER_INTERNAL: set[str] = {"_startup"}

    def _producer_categories(self) -> set[str]:
        """VALID_CATEGORIES (live) union renderer-internal sentinel."""
        return set[str](_load_cp_validate_landscape().VALID_CATEGORIES) | self._RENDERER_INTERNAL

    def test_all_producer_categories_in_category_colors(self) -> None:
        """Every competitor category the producer emits must map to a colour."""
        produced = self._producer_categories()
        viz = _load_cp_visualize()
        color_keys: set[str] = set(viz._CATEGORY_COLORS.keys())

        missing = produced - color_keys
        assert not missing, (
            f"visualize._CATEGORY_COLORS is missing a colour entry for competitor category(ies): "
            f"{sorted(missing)}. Add entries to _CATEGORY_COLORS for each."
        )

    def test_producer_categories_min_count(self) -> None:
        """Guard against vacuous tests: produced set must have at least 6 categories."""
        produced = self._producer_categories()
        assert len(produced) >= 6, f"VALID_CATEGORIES + _startup expected >= 6 entries, got {len(produced)}."

    def test_category_colors_min_count(self) -> None:
        """_CATEGORY_COLORS must cover at least the producer categories."""
        produced = self._producer_categories()
        viz = _load_cp_visualize()
        assert len(viz._CATEGORY_COLORS) >= len(produced), (
            f"visualize._CATEGORY_COLORS has only {len(viz._CATEGORY_COLORS)} entries; expected >= {len(produced)}."
        )


# ---------------------------------------------------------------------------
# Test E: trajectory maps → VALID_TRAJECTORIES coverage
# ---------------------------------------------------------------------------


class TestCpTrajectoryMapCoverage:
    """Both visualize.py's _TRAJECTORY_ARROWS and its trajectory_colors map
    must contain every trajectory value that score_moats.py can emit.

    Produced set is derived live from score_moats.VALID_TRAJECTORIES.

    trajectory_colors is a local dict defined inside the rendering function
    (_chart_moat_trajectory_bars), not a module-level constant.  We probe it
    by loading the module and inspecting the source for the literal keys, then
    cross-check against _TRAJECTORY_ARROWS (which IS module-level) to detect
    any divergence between the two maps.
    """

    _EXPECTED_TRAJECTORY_COLORS_KEYS: set[str] = {"building", "stable", "eroding"}

    def test_trajectory_arrows_covers_valid_trajectories(self) -> None:
        """Every VALID_TRAJECTORIES value must appear in _TRAJECTORY_ARROWS."""
        produced = _load_cp_score_moats().VALID_TRAJECTORIES
        viz = _load_cp_visualize()
        arrow_keys: set[str] = set(viz._TRAJECTORY_ARROWS.keys())

        missing = produced - arrow_keys
        assert not missing, (
            f"visualize._TRAJECTORY_ARROWS is missing an entry for trajectory(ies) "
            f"emitted by score_moats.py: {sorted(missing)}. "
            f"Add entries to _TRAJECTORY_ARROWS for each."
        )

    def test_trajectory_colors_keys_in_source(self) -> None:
        """Each expected trajectory_colors key must appear as a literal in visualize.py source."""
        with open(_CP_VISUALIZE_SCRIPT, encoding="utf-8") as fh:
            src = fh.read()
        for key in self._EXPECTED_TRAJECTORY_COLORS_KEYS:
            assert f'"{key}"' in src or f"'{key}'" in src, (
                f"trajectory_colors key {key!r} not found as a literal in visualize.py. "
                f"Update _EXPECTED_TRAJECTORY_COLORS_KEYS if the map was refactored."
            )

    def test_trajectory_arrows_and_colors_agree(self) -> None:
        """_TRAJECTORY_ARROWS key-set must match trajectory_colors key-set.

        Both maps process the same trajectory values; divergence means one will
        silently fall back to defaults for values the other knows about.
        """
        viz = _load_cp_visualize()
        arrow_keys = set(viz._TRAJECTORY_ARROWS.keys())
        assert arrow_keys == self._EXPECTED_TRAJECTORY_COLORS_KEYS, (
            f"_TRAJECTORY_ARROWS keys {sorted(arrow_keys)} do not match expected "
            f"trajectory_colors keys {sorted(self._EXPECTED_TRAJECTORY_COLORS_KEYS)}. "
            f"Keep both maps in sync when adding a new trajectory value."
        )

    def test_valid_trajectories_min_count(self) -> None:
        """Guard against vacuous tests: VALID_TRAJECTORIES must have at least 3 values."""
        produced = _load_cp_score_moats().VALID_TRAJECTORIES
        assert len(produced) >= 3, f"VALID_TRAJECTORIES expected >= 3 entries, got {len(produced)}."


# ---------------------------------------------------------------------------
# Test F: explore.py color maps → canonical sources coverage
# ---------------------------------------------------------------------------


class TestCpExploreColorCoverage:
    """explore.py defines its own _CATEGORY_COLORS (6) and _DEFENSIBILITY_COLORS (3)
    independently of visualize.py.  Both must cover the same canonical produced sets,
    and the same-concept hex values must agree between explore.py and visualize.py.

    Categories: validate_landscape.VALID_CATEGORIES + "_startup" sentinel.
    Defensibility: "high", "moderate", "low" (from _compute_aggregates).
    """

    # Defensibility levels — pinned with source-regex guards (same as TestCpDefensibilityColorCoverage).
    _DEFENSIBILITY_LEVELS: set[str] = {"high", "moderate", "low"}

    # "_startup" is the renderer-internal sentinel (not in VALID_CATEGORIES).
    _RENDERER_INTERNAL: set[str] = {"_startup"}

    def _producer_categories(self) -> set[str]:
        return set[str](_load_cp_validate_landscape().VALID_CATEGORIES) | self._RENDERER_INTERNAL

    def test_explore_category_colors_covers_producer_categories(self) -> None:
        """Every producer category must map to a colour in explore._CATEGORY_COLORS."""
        produced = self._producer_categories()
        exp = _load_cp_explore()
        color_keys: set[str] = set(exp._CATEGORY_COLORS.keys())

        missing = produced - color_keys
        assert not missing, (
            f"explore._CATEGORY_COLORS is missing a colour entry for competitor category(ies): "
            f"{sorted(missing)}. Add entries to explore._CATEGORY_COLORS."
        )

    def test_explore_category_colors_min_count(self) -> None:
        """Guard against vacuous tests: explore._CATEGORY_COLORS must have at least 6 entries."""
        exp = _load_cp_explore()
        assert len(exp._CATEGORY_COLORS) >= 6, (
            f"explore._CATEGORY_COLORS has only {len(exp._CATEGORY_COLORS)} entries; expected >= 6."
        )

    def test_explore_defensibility_colors_covers_all_levels(self) -> None:
        """Every defensibility level must map to a colour in explore._DEFENSIBILITY_COLORS."""
        exp = _load_cp_explore()
        color_keys: set[str] = set(exp._DEFENSIBILITY_COLORS.keys())

        missing = self._DEFENSIBILITY_LEVELS - color_keys
        assert not missing, (
            f"explore._DEFENSIBILITY_COLORS is missing a colour entry for defensibility level(s): "
            f"{sorted(missing)}. Add entries to explore._DEFENSIBILITY_COLORS."
        )

    def test_explore_defensibility_colors_min_count(self) -> None:
        """Guard against vacuous tests: explore._DEFENSIBILITY_COLORS must have exactly 3 entries."""
        exp = _load_cp_explore()
        assert len(exp._DEFENSIBILITY_COLORS) >= 3, (
            f"explore._DEFENSIBILITY_COLORS has only {len(exp._DEFENSIBILITY_COLORS)} entries; expected >= 3."
        )

    def test_defensibility_literals_present_in_source(self) -> None:
        """Each defensibility level must appear as a literal in score_moats.py source."""
        with open(_CP_SCORE_MOATS_SCRIPT, encoding="utf-8") as fh:
            src = fh.read()
        for level in self._DEFENSIBILITY_LEVELS:
            assert f'"{level}"' in src or f"'{level}'" in src, (
                f"Defensibility level {level!r} not found as a literal in score_moats.py. "
                f"Update _DEFENSIBILITY_LEVELS if _compute_aggregates() was changed."
            )

    def test_visualize_explore_category_colors_same_hex(self) -> None:
        """Same concept (category) must have the same hex in both visualize and explore."""
        produced = self._producer_categories()
        viz = _load_cp_visualize()
        exp = _load_cp_explore()
        for cat in produced:
            viz_color = viz._CATEGORY_COLORS.get(cat)
            exp_color = exp._CATEGORY_COLORS.get(cat)
            if viz_color is not None and exp_color is not None:
                assert viz_color == exp_color, (
                    f"Category {cat!r} has hex {viz_color!r} in visualize._CATEGORY_COLORS "
                    f"but {exp_color!r} in explore._CATEGORY_COLORS. Keep them in sync."
                )

    def test_visualize_explore_defensibility_colors_same_hex(self) -> None:
        """Same concept (defensibility level) must have the same hex in both visualize and explore."""
        viz = _load_cp_visualize()
        exp = _load_cp_explore()
        for level in self._DEFENSIBILITY_LEVELS:
            viz_color = viz._DEFENSIBILITY_COLORS.get(level)
            exp_color = exp._DEFENSIBILITY_COLORS.get(level)
            if viz_color is not None and exp_color is not None:
                assert viz_color == exp_color, (
                    f"Defensibility level {level!r} has hex {viz_color!r} in visualize._DEFENSIBILITY_COLORS "
                    f"but {exp_color!r} in explore._DEFENSIBILITY_COLORS. Keep them in sync."
                )
