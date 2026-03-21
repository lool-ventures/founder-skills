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
import json
import os
import shutil
import subprocess
import sys
import tempfile
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
        allowed = {"https://github.com/lool-ventures/founder-skills", "https://lool.vc"}
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
        assert any("#1e40af" in c for c in circles), "direct competitors should be dark blue"
        assert any("#9ca3af" in c for c in circles), "do_nothing should be gray"


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
