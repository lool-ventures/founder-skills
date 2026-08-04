"""No internal token may appear in founder-visible text in any generated HTML page.

The compose-time scan covers `report.md`. The HTML generators are a separate delivery surface reading
the same artifacts, and nothing checked them: an enum or field name our producers write into an
evidence string reaches `report.html` exactly as it reaches the markdown.

SCOPE, stated so a green is not over-read:

  * Only TEXT NODES are scanned. Attribute values and script/style bodies are excluded — an
    `<option value="moat_count">` whose label reads "Moat Count" is not a leak, and JS identifiers are
    not founder-facing prose.
  * Unlike `report.md`, HTML output is not run through `substitute()`. This asserts that our PRODUCERS
    emit no internal token; it cannot rewrite one a sub-agent authors into free text.
"""

from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

import pytest
from compose_invocations import drive_compose

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "founder-skills" / "tests" / "fixtures"

# (skill, generator) for every HTML generator in the fleet.
GENERATORS = [
    ("competitive-positioning", "visualize.py"),
    ("competitive-positioning", "explore.py"),
    ("financial-model-review", "visualize.py"),
    ("financial-model-review", "explore.py"),
    ("cap-table", "visualize.py"),
    ("cap-table", "explore.py"),
    ("ic-sim", "visualize.py"),
    ("market-sizing", "visualize.py"),
    ("deck-review", "visualize.py"),
]


def _founder_text():  # type: ignore[no-untyped-def]
    path = REPO_ROOT / "founder-skills" / "scripts" / "_founder_text.py"
    spec = importlib.util.spec_from_file_location("_founder_text", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _text_nodes(html: str) -> str:
    """Founder-visible text only: no script/style bodies, no attribute values."""
    html = re.sub(r"<script.*?</script>", " ", html, flags=re.S)
    html = re.sub(r"<style.*?</style>", " ", html, flags=re.S)
    return re.sub(r"<[^>]+>", " ", html)


def _cap_table_keep() -> frozenset[str]:
    path = REPO_ROOT / "founder-skills" / "skills" / "cap-table" / "scripts" / "_labels.py"
    spec = importlib.util.spec_from_file_location("_labels", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return frozenset(k for m in mod.MAPS.values() for k in m)


@pytest.mark.parametrize(("skill", "generator"), GENERATORS)
def test_generated_html_carries_no_internal_tokens(skill: str, generator: str) -> None:
    ft = _founder_text()
    script = REPO_ROOT / "founder-skills" / "skills" / skill / "scripts" / generator
    if not script.exists():
        pytest.skip(f"{skill} has no {generator}")

    with tempfile.TemporaryDirectory() as td:
        work = Path(td)
        drive_compose(skill, FIXTURES / skill, work)
        out = work / "page.html"
        result = subprocess.run(
            [sys.executable, str(script), "--dir", str(work), "-o", str(out)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"{skill}/{generator} failed: {result.stderr[-400:]}"
        html = out.read_text(encoding="utf-8")

    # Non-vacuity: a trivially small page would pass without proving anything.
    assert len(html) > 2000, f"{skill}/{generator} produced only {len(html)}B"
    text = _text_nodes(html)
    assert len(text) > 200, f"{skill}/{generator} yielded almost no text nodes — the stripper broke"

    keep = _cap_table_keep() if skill == "cap-table" else None
    found = ft.scan(text, extra_keep=keep)
    assert found["enums"] == [], (
        f"{skill}/{generator} shows internal token(s) in founder-visible text: {found['enums']}. "
        f"Render them through the shared founder-text policy, or stop writing them into the artifact."
    )


def test_the_scanner_would_catch_a_token_in_a_text_node() -> None:
    """Guard the stripper: if it over-stripped, every page above would pass vacuously."""
    ft = _founder_text()
    html = "<div><p>status is switching_costs</p><option value='moat_count'>Moat Count</option></div>"
    found = ft.scan(_text_nodes(html))
    assert found["enums"] == ["switching_costs"], found
    assert "moat_count" not in found["enums"], "an attribute value is not founder-visible text"


_ = Callable  # re-exported type import kept for parametrize signature clarity
