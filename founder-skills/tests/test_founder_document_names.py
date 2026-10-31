"""A founder's own `.md` / `.json` document is not one of our files.

The founder-text policy calls every `.json` and `.md` name ours (`_founder_text._is_internal_file`). A founder
who uploaded `notes.md` or `customer_list.json` and saw it named back was therefore told the report leaked an
internal file: competitive-positioning's delivery gate failed, and both skills' composes warned. Each caller now
passes this run's document names (`keep_files`), and the scan blanks them at filename boundaries only, never a
name the scan would report as one of ours.

Each integration test has a lever: a copy of the plugin in which the run's document names come back empty, where
the old behaviour must return, so a pass is not a check that stopped looking.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

HERE = Path(__file__).resolve().parent
PLUGIN = HERE.parent
SKILLS = PLUGIN / "skills"


def _load(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


FT = _load("_founder_text_keep_files_test", PLUGIN / "scripts" / "_founder_text.py")

KEEP = (
    "notes.md",
    "scores.json",
    "text.md",
    "a1b2c3d4-notes.md",
    "q3-notes.md",
    "Customer List.json",
    "customer_list.json",
    "my-report.md",
    "My Report.md",
    "report.md",
    "landscape.json",
)


@pytest.mark.parametrize(
    "text, reported",
    [
        ("Read notes.md first.", []),  # a kept name before a full stop
        ("Read notes.md.", []),
        ("Read xnotes.md.", ["xnotes.md"]),  # never part of a longer name
        ("Graded in moat_scores.json.", ["moat_scores.json"]),  # kept `scores.json` never hides ours
        ("Taken from deck_text.md.", ["deck_text.md"]),  # kept `text.md` never hides ours
        ("Read a1b2c3d4-notes.md and q3-notes.md.", []),
        ("Read customer_list.json.", []),
        ("Read my-report.md beside report.md.", ["report.md"]),  # an upload named like ours is never kept
        ("The set is in landscape.json.", ["landscape.json"]),
        ("Read notes.md.first.json.", ["first.json", "notes.md"]),  # never the stem of a longer name
    ],
)
def test_kept_names_are_blanked_at_filename_boundaries_only(text: str, reported: list[str]) -> None:
    assert FT.scan(text, keep_files=KEEP)["filenames"] == reported


@pytest.mark.parametrize(
    "kept, text, ours",
    [
        ("report", "see report.md", "report.md"),
        ("landscape", "in landscape.json", "landscape.json"),
        ("deck_text", "from deck_text.md", "deck_text.md"),
    ],
)
def test_a_name_with_no_extension_never_hides_ours(kept: str, text: str, ours: str) -> None:
    """A name the scan reports nothing for has nothing to keep; kept, it would blank the stem of ours."""
    assert FT.scan(text, keep_files=[kept])["filenames"] == [ours]


def test_without_keep_files_every_name_is_reported_as_before() -> None:
    """Lever for the rows above: with nothing kept, the founder's names are reported."""
    assert FT.scan("Read notes.md and customer_list.json.")["filenames"] == ["customer_list.json", "notes.md"]


def test_a_casefolding_caller_blanks_as_written_then_folds() -> None:
    sentence = "Customer List.json lists six buyers."
    assert FT.scan(sentence.casefold())["filenames"] == ["list.json"]
    assert FT.scan(FT.blank_kept_files(sentence, KEEP).casefold())["filenames"] == []
    assert FT.scan(FT.blank_kept_files("My Report.md says so.", KEEP).casefold())["filenames"] == ["report.md"]


def test_a_name_of_ours_is_never_kept() -> None:
    kept = FT._kept_file_names(KEEP)
    for ours in ("report.md", "My Report.md", "my-report.md", "landscape.json"):
        assert ours not in kept
    for theirs in ("notes.md", "q3-notes.md", "Customer List.json", "scores.json", "text.md"):
        assert theirs in kept
    for pattern_named in ("checklist_output.json", "landscape.json.gate.json", "redteam.r2.json", "x.first.json"):
        assert FT.is_our_output_name(pattern_named)


# ---------------------------------------------------------------------------
# OUR_OUTPUT_NAMES covers every artifact constant the skills declare
# ---------------------------------------------------------------------------

_CONSTANTS = {
    "competitive-positioning/scripts/compose_report.py": ("REQUIRED_ARTIFACTS", "OPTIONAL_ARTIFACTS"),
    "competitive-positioning/scripts/verify_positioning.py": ("_ALWAYS_REQUIRED", "_GATE2_REQUIRED", "_OPTIONAL"),
    "market-sizing/scripts/compose_report.py": ("REQUIRED_ARTIFACTS", "OPTIONAL_ARTIFACTS"),
    "deck-review/scripts/compose_report.py": ("REQUIRED_ARTIFACTS", "OPTIONAL_ARTIFACTS"),
    "financial-model-review/scripts/compose_report.py": ("REQUIRED_ARTIFACTS", "OPTIONAL_ARTIFACTS"),
    "financial-model-review/scripts/verify_review.py": ("_ALWAYS_REQUIRED", "_OPTIONAL"),
    "ic-sim/scripts/compose_report.py": ("REQUIRED_ARTIFACTS", "OPTIONAL_ARTIFACTS"),
    "cap-table/scripts/compose_report.py": ("REQUIRED_ARTIFACTS",),
    "competitive-positioning/scripts/_cp_redteam_text.py": ("INTERNAL_FILE_PHRASES",),
    "market-sizing/scripts/_redteam_text.py": ("INTERNAL_FILE_PHRASES",),
}


def _literal_names(path: Path, names: tuple[str, ...]) -> set[str]:
    """The file names a module-level list or dict literal holds, read from the source (no import side effects)."""
    found: dict[str, set[str]] = {}
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        target, value = None, None
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            target, value = node.targets[0].id, node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            target, value = node.target.id, node.value
        if target in names and value is not None:
            lit = ast.literal_eval(value)
            found[target] = set(lit.keys() if isinstance(lit, dict) else lit)
    assert set(found) == set(names), f"{path}: constants not found: {set(names) - set(found)}"
    return set().union(*found.values())


def test_our_output_names_cover_every_declared_artifact() -> None:
    expected: set[str] = set()
    for rel, names in _CONSTANTS.items():
        expected |= _literal_names(SKILLS / rel, names)
    expected = {n for n in expected if n.endswith((".json", ".md", ".html"))}
    assert len(expected) > 40, "the derivation read too little to mean anything"
    missing = sorted(n for n in expected if not FT.is_our_output_name(n))
    assert not missing, f"add these to OUR_OUTPUT_NAMES in _founder_text.py: {missing}"


# ---------------------------------------------------------------------------
# competitive-positioning: compose, both pages and the delivery gate
# ---------------------------------------------------------------------------

CP_FIXTURE = HERE / "fixtures" / "competitive-positioning"
CP_RUN = "fixture-competitive-positioning-001"
KEPT_SENTENCE = "Pricing comes from notes.md and customer_list.json."
EVIDENCE = f"{KEPT_SENTENCE} The set is in landscape.json."


def _stub_names(plugin: Path, rel: str) -> None:
    """Lever: this copy's `founder_document_names` returns nothing."""
    path = plugin / "skills" / rel
    src = path.read_text(encoding="utf-8")
    assert src.count("def founder_document_names(") == 1, "the lever's anchor moved"
    src = src.replace("def founder_document_names(", "def _unstubbed_founder_document_names(")
    path.write_text(src + "\n\ndef founder_document_names(*_a, **_k):\n    return frozenset()\n", encoding="utf-8")


def _copy_plugin(tmp_path: Path) -> Path:
    plugin = tmp_path / "founder-skills"
    shutil.copytree(PLUGIN, plugin, ignore=shutil.ignore_patterns("tests", "__pycache__"))
    return plugin


def _run(scripts: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(scripts / args[0]), *args[1:]], capture_output=True, text=True)


def _stage_cp(work: Path) -> None:
    work.mkdir()
    for f in CP_FIXTURE.iterdir():
        shutil.copy2(f, work / f.name)
    checklist = json.loads((work / "checklist.json").read_text(encoding="utf-8"))
    checklist["items"][0]["evidence"] = EVIDENCE
    (work / "checklist.json").write_text(json.dumps(checklist, indent=2), encoding="utf-8")
    profile = json.loads((work / "product_profile.json").read_text(encoding="utf-8"))
    profile["product_description"] = str(profile.get("product_description") or "") + " Details are in notes.md."
    (work / "product_profile.json").write_text(json.dumps(profile, indent=2), encoding="utf-8")
    # The founder's documents as the review step mirrors them, one of them named like a file of ours.
    docs = work / "handoff" / CP_RUN / "docs"
    docs.mkdir(parents=True)
    for name in ("notes.md", "customer_list.json", "landscape.json"):
        (docs / name).write_text("synthetic\n", encoding="utf-8")


def _deliver_cp(plugin: Path, work: Path) -> dict[str, Any]:
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
    report = json.loads((work / "report.json").read_text(encoding="utf-8"))
    out["_compose_files"] = [w["message"] for w in report.get("warnings", []) if w.get("code") == "FOUNDER_TEXT_TOKEN"]
    return out


def _gate_messages(out: dict[str, Any]) -> tuple[list[str], list[str]]:
    return out["summary"]["errors"], out["summary"]["warnings"]


def test_cp_a_founders_own_documents_pass_the_delivery_gate(tmp_path: Path) -> None:
    work = tmp_path / "work"
    _stage_cp(work)
    out = _deliver_cp(PLUGIN, work)
    errors, warnings = _gate_messages(out)
    assert out["_rc"] == 0, errors
    md = (work / "report.md").read_text(encoding="utf-8")
    assert "Details are in notes.md." in md  # the precondition: the name reaches report.md
    for name in ("notes.md", "customer_list.json"):
        assert not [m for m in errors + warnings + out["_compose_files"] if f"'{name}'" in m], name
    # An upload named like one of our files exempts nothing: the evidence citing ours is still flagged.
    assert any("'landscape.json'" in w for w in warnings)
    # The checklist keeps the sentence naming only the founder's files, drops ours, on all three surfaces.
    section = md.split("## Analysis Checklist", 1)[1]
    assert KEPT_SENTENCE in section and "landscape.json" not in section
    for page in ("report.html", "explore.html"):
        html = (work / page).read_text(encoding="utf-8")
        assert KEPT_SENTENCE in html, page


def test_cp_without_the_names_the_old_flags_return(tmp_path: Path) -> None:
    plugin = _copy_plugin(tmp_path)
    _stub_names(plugin, "competitive-positioning/scripts/_cp_redteam_copy.py")
    work = tmp_path / "work"
    _stage_cp(work)
    out = _deliver_cp(plugin, work)
    errors, _warnings = _gate_messages(out)
    assert out["_rc"] == 1
    assert any("'notes.md'" in e for e in errors)
    assert any("'notes.md'" in m for m in out["_compose_files"])
    md = (work / "report.md").read_text(encoding="utf-8")
    assert KEPT_SENTENCE not in md.split("## Analysis Checklist", 1)[1]
    for page in ("report.html", "explore.html"):
        assert KEPT_SENTENCE not in (work / page).read_text(encoding="utf-8"), page


# ---------------------------------------------------------------------------
# market-sizing: compose's warning
# ---------------------------------------------------------------------------

MS_FIXTURE = HERE / "fixtures" / "market-sizing"
MS_RUN = "fixture-market-sizing-001"


def _compose_ms(plugin: Path, tmp_path: Path) -> tuple[str, list[str]]:
    work = tmp_path / "ms"
    work.mkdir()
    for f in MS_FIXTURE.glob("*.json"):
        shutil.copy2(f, work / f.name)
    checklist = json.loads((work / "checklist.json").read_text(encoding="utf-8"))
    checklist["items"][0]["notes"] = "Read from notes.md and customer_list.json, and checked against sizing.json."
    (work / "checklist.json").write_text(json.dumps(checklist, indent=2), encoding="utf-8")
    docs = work / "handoff" / MS_RUN / "docs"
    docs.mkdir(parents=True)
    for name in ("notes.md", "customer_list.json", "sizing.json"):
        (docs / name).write_text("synthetic\n", encoding="utf-8")
    scripts = plugin / "skills" / "market-sizing" / "scripts"
    d = str(work)
    composed = _run(scripts, "compose_report.py", "--dir", d, "-o", f"{d}/report.json", "--write-md", f"{d}/report.md")
    assert composed.returncode == 0, composed.stderr
    report = json.loads((work / "report.json").read_text(encoding="utf-8"))
    warnings = report.get("validation", {}).get("warnings", [])
    files = [w["message"] for w in warnings if w.get("code") == "FOUNDER_TEXT_TOKEN"]
    return (work / "report.md").read_text(encoding="utf-8"), files


def test_ms_compose_does_not_warn_on_a_founders_own_documents(tmp_path: Path) -> None:
    md, files = _compose_ms(PLUGIN, tmp_path)
    assert "notes.md" in md and "customer_list.json" in md  # the precondition
    assert not [m for m in files if "'notes.md'" in m or "'customer_list.json'" in m], files
    assert any("'sizing.json'" in m for m in files)  # an upload named like ours exempts nothing


def test_ms_without_the_names_the_warning_returns(tmp_path: Path) -> None:
    plugin = _copy_plugin(tmp_path)
    _stub_names(plugin, "market-sizing/scripts/_redteam_copy.py")
    _md, files = _compose_ms(plugin, tmp_path)
    assert any("'notes.md'" in m for m in files)
    assert any("'customer_list.json'" in m for m in files)
