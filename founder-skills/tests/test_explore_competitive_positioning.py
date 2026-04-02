"""Tests for competitive positioning explore.py (interactive HTML explorer)."""

from __future__ import annotations

import json
import os
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
    import re

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
    import re

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
