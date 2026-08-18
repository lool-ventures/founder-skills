"""No internal token may appear in founder-visible text in any generated HTML page.

The compose-time scan covers `report.md`. The HTML generators are a separate delivery surface reading
the same artifacts, and nothing checked them: an enum or field name our producers write into an
evidence string reaches `report.html` exactly as it reaches the markdown.

SCOPE, stated so a green is not over-read:

  * Only TEXT NODES are scanned. Attribute values and script/style bodies are excluded — an
    `<option value="moat_count">` whose label reads "Moat Count" is not a leak, and JS identifiers are
    not founder-facing prose.
  * THE EXPLORERS ARE BARELY COVERED, and pretending otherwise would be worse than not scanning them.
    Measured text-node share of each page: visualize 1.4-4.4%, explore 0.1-0.2% (255-793 B of static
    text in a 300 KB page). Their founder-visible content is rendered by JavaScript from the embedded
    payload at runtime and never exists as a static text node, so this scan cannot see it. A
    display-string scan of the payload was tried and abandoned: it cannot distinguish a display field
    from a provenance map keyed by field name (`evidence_source.description == "agent_estimate"` is
    not a label), and produced a false positive on the first page it examined. What covers that
    surface today is the Cowork UI gate, i.e. a human reading the rendered page.
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
    # The extracted-values review page — a page the founder opens and reads, and the 10th HTML
    # generator in the fleet. It was missing from this list while every other one was covered.
    ("financial-model-review", "review_inputs.py"),
]

# Static-text floor per generator. NOT one number: a 300 KB explorer legitimately yields ~250 B of
# text nodes, so a single floor either passes vacuously for explorers or fails honestly-thin pages.
_TEXT_FLOOR = {"visualize.py": 700, "explore.py": 200, "review_inputs.py": 200}


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
        if generator == "review_inputs.py":
            # Different CLI: positional inputs path, and --static is the Cowork branch (the
            # --workspace branch backgrounds an HTTP server that never exits). --static takes the
            # OUTPUT path, it is not a bare flag.
            argv = [str(script), str(work / "inputs.json"), "--static", str(out)]
        else:
            argv = [str(script), "--dir", str(work), "-o", str(out)]
            # deck-review's visualize.py sits behind the same authorization boundary as its
            # compose (see G2). These fixtures carry no gate, which is the legitimate ungated
            # path -- it just has to be stated rather than spelled as a missing flag.
            if skill == "deck-review" and generator == "visualize.py":
                argv.append("--ungated")
        result = subprocess.run([sys.executable, *argv], capture_output=True, text=True)
        assert result.returncode == 0, f"{skill}/{generator} failed: {result.stderr[-400:]}"
        html = out.read_text(encoding="utf-8")

    # Non-vacuity: a trivially small page would pass without proving anything.
    assert len(html) > 2000, f"{skill}/{generator} produced only {len(html)}B"
    text = _text_nodes(html)
    floor = _TEXT_FLOOR[generator]
    assert len(text) > floor, (
        f"{skill}/{generator} yielded {len(text)}B of text nodes, below its {floor}B floor — either the "
        f"stripper broke or the page stopped rendering static text"
    )

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
