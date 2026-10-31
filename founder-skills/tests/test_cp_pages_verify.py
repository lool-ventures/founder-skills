"""competitive-positioning's delivery gate over the fixture, composed and rendered: report.md and both pages.

The gate (`verify_positioning.py --gate 2`) fails on an internal file named in report.md. The Analysis Checklist
section shows the assessor's evidence, so a seeded filename there is the case that matters: `criterion_text`
drops its sentence, and the gate passes. The lever turns the drop off in a copy of the plugin and expects the
gate to fail naming the file, so a pass is not a gate that stopped looking.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
FIXTURE = HERE / "fixtures" / "competitive-positioning"
SEEDED = (
    "Graded with POS_05 in mind. The POSITIONING_SCORING step agrees. The research_depth was thin. "
    "The set is in landscape.json."
)


def _stage(work: Path, seed: bool) -> None:
    work.mkdir()
    for f in FIXTURE.iterdir():
        shutil.copy2(f, work / f.name)
    if seed:
        checklist = json.loads((work / "checklist.json").read_text(encoding="utf-8"))
        for item in checklist["items"]:
            item["evidence"] = SEEDED
        (work / "checklist.json").write_text(json.dumps(checklist, indent=2), encoding="utf-8")


def _run(scripts: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(scripts / args[0]), *args[1:]], capture_output=True, text=True)


def _deliver(plugin: Path, work: Path) -> dict[str, Any]:
    """Compose, render both pages, run the gate; return the gate's JSON (with its exit code)."""
    scripts = plugin / "skills" / "competitive-positioning" / "scripts"
    d = str(work)
    composed = _run(scripts, "compose_report.py", "--dir", d, "-o", f"{d}/report.json", "--write-md", f"{d}/report.md")
    assert composed.returncode == 0, composed.stderr
    for script, page in (("visualize.py", "report.html"), ("explore.py", "explore.html")):
        rendered = _run(scripts, script, "--dir", d, "-o", f"{d}/{page}")
        assert rendered.returncode == 0, rendered.stderr
    gate = _run(scripts, "verify_positioning.py", "--dir", d, "--gate", "2")
    out: dict[str, Any] = json.loads(gate.stdout)
    out["_rc"] = gate.returncode
    return out


def _messages(out: dict[str, Any], severity: str) -> list[str]:
    return [
        str(i.get("message"))
        for v in out.values()
        if isinstance(v, list)
        for i in v
        if isinstance(i, dict) and i.get("severity") == severity
    ]


def test_the_fixture_passes_the_delivery_gate(tmp_path: Path) -> None:
    work = tmp_path / "work"
    _stage(work, seed=False)
    out = _deliver(HERE.parent, work)
    assert out["_rc"] == 0, _messages(out, "error")


def test_seeded_evidence_passes_and_shows_none_of_its_tokens(tmp_path: Path) -> None:
    work = tmp_path / "work"
    _stage(work, seed=True)
    out = _deliver(HERE.parent, work)
    assert out["_rc"] == 0, _messages(out, "error")
    section = (work / "report.md").read_text(encoding="utf-8").split("## Analysis Checklist", 1)[1]
    for token in ("POS_05", "POSITIONING_SCORING", "research_depth", "landscape.json"):
        assert token not in section, token


def test_without_the_drop_step_the_gate_names_the_file(tmp_path: Path) -> None:
    """Lever: in a copy of the plugin whose `criterion_text` keeps every sentence, the gate fails on the file."""
    plugin = tmp_path / "founder-skills"
    shutil.copytree(HERE.parent, plugin, ignore=shutil.ignore_patterns("tests", "__pycache__"))
    view = plugin / "skills" / "competitive-positioning" / "scripts" / "_cp_view.py"
    src = view.read_text(encoding="utf-8")
    old = 'if policy.scan(policy.blank_kept_files(sentence, keep_files).casefold())["filenames"]:'
    assert src.count(old) == 1, "the lever's anchor moved"
    view.write_text(src.replace(old, "if False:"), encoding="utf-8")
    work = tmp_path / "work"
    _stage(work, seed=True)
    out = _deliver(plugin, work)
    assert out["_rc"] == 1
    assert any("landscape.json" in m for m in _messages(out, "error"))
