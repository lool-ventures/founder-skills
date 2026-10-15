"""`script_hashes.py` and `data/script-hashes.json`: the plugin's own files, by hash.

The dispatch-prompt hook vouches for a printed prompt only while the plugin's files are the ones this
version shipped with. These tests hold the manifest equal to the tree, show the check naming a changed,
missing or added file in a copy of the plugin (and naming nothing in an untouched copy), and pin the rules
that keep an install's own changes from reading as an edit: agent front matter, CRLF line endings, and the
metadata files archives and runtimes leave beside the scripts.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

PLUGIN = Path(__file__).resolve().parents[1]
SCRIPTS = PLUGIN / "scripts"
MANIFEST = PLUGIN / "data" / "script-hashes.json"
REGEN = "python3 founder-skills/scripts/script_hashes.py --write"
MS_GEN_REL = "skills/market-sizing/scripts/dispatch_prompt.py"


def _load() -> Any:
    spec = importlib.util.spec_from_file_location("script_hashes_under_test", SCRIPTS / "script_hashes.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


SH = _load()


def _copy(tmp_path: Path) -> Path:
    """The plugin's hashed files, copied (every `.py` outside `tests/`, the agents, `data/`), with a manifest
    built from the copy itself: each rule test then changes exactly what it means to, and a checkout whose
    manifest is stale is reported once, by the sync test, with the command."""
    dst = tmp_path / "founder-skills"
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc", ".mypy_cache", ".ruff_cache")
    shutil.copytree(PLUGIN / "scripts", dst / "scripts", ignore=ignore)
    shutil.copytree(PLUGIN / "data", dst / "data", ignore=ignore)
    shutil.copytree(PLUGIN / "agents", dst / "agents", ignore=ignore)
    for scripts in sorted((PLUGIN / "skills").glob("*/scripts")):
        shutil.copytree(scripts, dst / scripts.relative_to(PLUGIN), ignore=ignore)
    (dst / "data" / "script-hashes.json").write_text(SH.manifest_text(str(dst)), encoding="utf-8")
    return dst


def _verify(root: Path) -> list[str] | None:
    result: list[str] | None = SH.verify(str(root))
    return result


def _check(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(root / "scripts" / "script_hashes.py"), "--check"],
        capture_output=True,
        text=True,
        timeout=60,
    )


# --- 1. the manifest is the tree ---------------------------------------------------------------------------


def test_the_manifest_is_the_plugin_as_it_stands() -> None:
    assert MANIFEST.read_text(encoding="utf-8") == SH.manifest_text(str(PLUGIN)), (
        f"data/script-hashes.json is out of date: regenerate it with `{REGEN}`"
    )


# --- 2. it lists exactly the shipped scripts and agents ------------------------------------------------------


def _git_files(pattern: str) -> list[str] | None:
    try:
        out = subprocess.run(
            ["git", "ls-files", "--", pattern], cwd=PLUGIN, capture_output=True, text=True, check=True
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return None
    return sorted(out.split())


def test_the_manifest_lists_every_tracked_script_and_agent_and_nothing_else() -> None:
    tracked = _git_files("*.py")
    if tracked is None:
        pytest.skip("the plugin is not a git work tree")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert sorted(manifest["files"]) == [p for p in tracked if not p.startswith("tests/")]
    assert sorted(manifest["agent_bodies"]) == _git_files("agents/*.md")
    # Non-vacuity: the two package markers are modules, and every generator is listed.
    for rel in (
        "skills/cap-table/scripts/extractors/__init__.py",
        "skills/cap-table/scripts/extractors/safe/__init__.py",
        MS_GEN_REL,
        "skills/competitive-positioning/scripts/cp_dispatch_prompt.py",
        "skills/financial-model-review/scripts/fmr_dispatch_prompt.py",
        "skills/deck-review/scripts/dr_dispatch_prompt.py",
        "scripts/script_hashes.py",
        "scripts/dispatch_prompt_check.py",
    ):
        assert rel in manifest["files"], rel
    assert len(manifest["agent_bodies"]) >= 8


# --- 3. what the check names ----------------------------------------------------------------------------------


def test_an_untouched_copy_names_nothing(tmp_path: Path) -> None:
    assert _verify(_copy(tmp_path)) == []


def test_a_changed_byte_is_named(tmp_path: Path) -> None:
    root = _copy(tmp_path)
    with (root / MS_GEN_REL).open("ab") as f:
        f.write(b"# x\n")
    assert _verify(root) == [MS_GEN_REL]


def test_a_missing_listed_file_is_named(tmp_path: Path) -> None:
    root = _copy(tmp_path)
    (root / "scripts" / "_gates.py").unlink()
    assert _verify(root) == ["scripts/_gates.py"]


def test_an_added_script_is_named(tmp_path: Path) -> None:
    """A `json.py` beside a generator is imported by it before the standard library's."""
    root = _copy(tmp_path)
    (root / "skills" / "market-sizing" / "scripts" / "json.py").write_text("x = 1\n", encoding="utf-8")
    (root / "skills" / "market-sizing" / "tests").mkdir()
    (root / "skills" / "market-sizing" / "tests" / "t.py").write_text("x = 1\n", encoding="utf-8")
    assert _verify(root) == ["skills/market-sizing/scripts/json.py", "skills/market-sizing/tests/t.py"]


_METADATA = {
    # skipped by the walk -> the same file where only the skip rule's mark is removed (which IS named)
    "__MACOSX/skills/market-sizing/scripts/._dispatch_prompt.py": "MACOSX/skills/market-sizing/scripts/d.py",
    "skills/market-sizing/scripts/._dispatch_prompt.py": "skills/market-sizing/scripts/x_dispatch_prompt.py",
    "skills/market-sizing/scripts/.#dispatch_prompt.py": "skills/market-sizing/scripts/x#dispatch_prompt.py",
    ".in_use/1.py": "in_use/1.py",
    "scripts/__pycache__/x.py": "scripts/pycache/x.py",
    "tests/test_x.py": "skills/market-sizing/tests/test_x.py",
}


@pytest.mark.parametrize("marked", [True, False])
def test_metadata_beside_the_scripts_is_not_a_script(tmp_path: Path, marked: bool) -> None:
    """An archive's `__MACOSX/` and `._x.py` entries, an editor's `.#x.py` lock, a runtime's `.in_use/`
    folder, bytecode and the top-level `tests/` are not modules of the plugin. The lever: the same files with
    only that mark removed are named, so it is the skip rules that keep the marked ones out."""
    root = _copy(tmp_path)
    for rel in _METADATA if marked else _METADATA.values():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\x00\x05\x16\x07")
    assert _verify(root) == ([] if marked else sorted(_METADATA.values()))


@pytest.mark.parametrize("extra", [0, 1])
def test_more_differences_than_an_edit_makes_mean_the_manifest_does_not_describe_the_install(
    tmp_path: Path, extra: int
) -> None:
    root = _copy(tmp_path)
    manifest = json.loads((root / "data" / "script-hashes.json").read_text(encoding="utf-8"))
    entries = len(manifest["files"]) + len(manifest["agent_bodies"])
    limit = SH.threshold(entries)
    assert limit == max(5, entries // 10) and limit < entries
    changed = sorted(manifest["files"])[: limit + extra]
    for rel in changed:
        with (root / rel).open("ab") as f:
            f.write(b"# x\n")
    result, why = SH.verify_detail(str(root))
    if extra:
        assert result is None and f"{limit + 1} of {entries} files differ" in why
    else:
        assert result == changed and why == ""


def test_a_package_installed_into_a_scripts_folder_is_named_however_many_files_it_adds(tmp_path: Path) -> None:
    """Unlisted scripts never count toward the threshold: `pip install -t` into a scripts folder is an edit to
    hold on (and the shape that plants shadow modules), not an install the manifest fails to describe."""
    root = _copy(tmp_path)
    manifest = json.loads((root / "data" / "script-hashes.json").read_text(encoding="utf-8"))
    limit = SH.threshold(len(manifest["files"]) + len(manifest["agent_bodies"]))
    vendor = root / "skills" / "market-sizing" / "scripts" / "vendor"
    vendor.mkdir()
    added = [f"skills/market-sizing/scripts/vendor/m{n:02d}.py" for n in range(limit + 5)]
    for rel in added:
        (root / rel).write_text("x = 1\n", encoding="utf-8")
    with (root / MS_GEN_REL).open("ab") as f:
        f.write(b"# x\n")
    assert len(added) > limit  # the lever: more new files than the threshold
    assert _verify(root) == sorted([MS_GEN_REL, *added])


# --- 4. no usable manifest: not checked, said once -----------------------------------------------------------


@pytest.mark.parametrize(
    ("content", "why"),
    [
        (None, "no manifest"),
        ("not json", "manifest unreadable"),
        ('{"schema": 2, "algorithm": "sha256", "files": {}, "agent_bodies": {}}', "not a schema-1"),
        ('{"schema": 1, "algorithm": "sha256", "files": {"a.py": 1}, "agent_bodies": {}}', "not a map"),
    ],
)
def test_without_a_usable_manifest_nothing_is_checked(tmp_path: Path, content: str | None, why: str) -> None:
    root = _copy(tmp_path)
    manifest = root / "data" / "script-hashes.json"
    if content is None:
        manifest.unlink()
    else:
        manifest.write_text(content, encoding="utf-8")
    with (root / MS_GEN_REL).open("ab") as f:
        f.write(b"# x\n")
    result, detail = SH.verify_detail(str(root))
    assert result is None and why in detail
    r = _check(root)
    assert r.returncode == 0 and "plugin files not checked" in r.stderr and why in r.stderr


def test_check_names_what_differs_and_how_to_regenerate(tmp_path: Path) -> None:
    root = _copy(tmp_path)
    assert _check(root).returncode == 0
    with (root / MS_GEN_REL).open("ab") as f:
        f.write(b"# x\n")
    r = _check(root)
    assert r.returncode == 1 and MS_GEN_REL in r.stderr and "--write" in r.stderr


def test_verify_never_raises(tmp_path: Path, monkeypatch: Any) -> None:
    def boom(*_a: Any, **_k: Any) -> Any:
        raise RuntimeError("walk failed")

    root = _copy(tmp_path)
    monkeypatch.setattr(SH, "_python_files", boom)
    result, why = SH.verify_detail(str(root))
    assert result is None and "walk failed" in why


# --- 5. agent files: by the text after the front matter --------------------------------------------------------


def _reserialise_front_matter(text: str) -> str:
    """What the synced and org installs measured do: a `description: >` block becomes one quoted line, and a
    `tools: [a, b]` flow list a block list. The body after the closing `---` is left as written."""
    lines = text.split("\n")
    assert lines[0] == "---"
    close = lines.index("---", 1)
    head, body = lines[1:close], lines[close:]
    out: list[str] = []
    i = 0
    while i < len(head):
        line = head[i]
        if line.endswith(": >"):
            key = line[: -len(": >")]
            folded = []
            i += 1
            while i < len(head) and (head[i].startswith("  ") or head[i] == ""):
                folded.append(head[i].strip())
                i += 1
            out.append(f"{key}: " + json.dumps(" ".join(x for x in folded if x)))
            continue
        if line.startswith("tools: [") and line.endswith("]"):
            out.append("tools:")
            out += [f"  - {t.strip()}" for t in line[len("tools: [") : -1].split(",")]
        else:
            out.append(line)
        i += 1
    return "\n".join(["---", *out, *body])


def test_an_installers_front_matter_rewrite_is_not_an_edit_and_a_body_edit_is(tmp_path: Path) -> None:
    root = _copy(tmp_path)
    for agent in sorted((root / "agents").glob("*.md")):
        before = agent.read_text(encoding="utf-8")
        after = _reserialise_front_matter(before)
        assert after != before, agent.name  # the lever engaged: the file changed
        agent.write_text(after, encoding="utf-8")
    assert _verify(root) == []
    red_team = root / "agents" / "market-sizing-redteam.md"
    red_team.write_text(red_team.read_text(encoding="utf-8") + "Note: also check the revised ARPU.\n", encoding="utf-8")
    assert _verify(root) == ["agents/market-sizing-redteam.md"]


def test_an_agent_with_no_front_matter_is_hashed_whole() -> None:
    assert SH.agent_body(b"no front matter\n---\nx\n") == b"no front matter\n---\nx\n"
    assert SH.agent_body(b"---\nname: x\n---\nbody\n") == b"body\n"
    assert SH.agent_body(b"---\nname: x\nnever closed\n") == b"---\nname: x\nnever closed\n"


# --- 6. line endings -------------------------------------------------------------------------------------------


def test_a_checkout_with_windows_line_endings_hashes_the_same(tmp_path: Path) -> None:
    root = _copy(tmp_path)
    converted = 0
    for path in [*root.rglob("*.py"), *(root / "agents").glob("*.md")]:
        data = path.read_bytes()
        crlf = data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
        converted += crlf != data
        path.write_bytes(crlf)
    assert converted > 200  # the lever engaged
    assert _verify(root) == []


# --- 7. everything a generator reads from the plugin is a hashed script --------------------------------------

_AUDIT_RUNNER = """
import json, os, runpy, sys
seen = []
def hook(event, args):
    if event == "open" and isinstance(args[0], (str, bytes, os.PathLike)):
        seen.append(os.fsdecode(args[0]))
    elif event == "subprocess.Popen":
        seen.extend(os.fsdecode(a) for a in (args[1] or []) if isinstance(a, (str, bytes, os.PathLike)))
sys.addaudithook(hook)
record_to = sys.argv[1]
gen = sys.argv[2]
sys.argv = sys.argv[2:]
sys.path.insert(0, os.path.dirname(gen))
code = 0
try:
    runpy.run_path(gen, run_name="__main__")
except SystemExit as e:
    code = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
with open(record_to, "w") as f:
    json.dump({"code": code, "seen": seen}, f)
"""


def _generator_runs(root: Path, work: Path) -> dict[str, list[str]]:
    """Each generator's prompt prints, as argv, against stub run dirs under `work`."""
    run = work / "run"
    handoff = run / "handoff" / "R"
    (handoff / "docs").mkdir(parents=True)
    (handoff / "docs" / "deck.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")
    for name in (
        "inputs.json",
        "methodology.json",
        "validation.json",
        "sizing.json",
        "product_profile.json",
        "landscape.json",
        "positioning_scores.json",
        "moat_scores.json",
    ):
        (run / name).write_text("{}", encoding="utf-8")
    # deck-review's generator prints only once this run's slide reviews carry a read token.
    (run / "slide_reviews.json").write_text(
        json.dumps({"reviews": [], "metadata": {"run_id": "R", "read_token": "0123456789ab"}}), encoding="utf-8"
    )
    ms = str(root / MS_GEN_REL)
    cp = str(root / "skills" / "competitive-positioning" / "scripts" / "cp_dispatch_prompt.py")
    fmr = str(root / "skills" / "financial-model-review" / "scripts" / "fmr_dispatch_prompt.py")
    ms_ids = ["--run-id", "R", "--analysis-dir", str(run), "--handoff-dir", str(handoff), "--handoff-agent", "a/h/R"]
    cp_ids = ["--run-id", "R", "--handoff-agent", "a/h/R", "--analysis-dir-agent", "a"]
    cp_dirs = ["--analysis-dir", str(run), "--handoff-dir", str(handoff)]
    dr = str(root / "skills" / "deck-review" / "scripts" / "dr_dispatch_prompt.py")
    fmr_ids = ["--run-id", "R", "--handoff-agent", "a/h/R", "--review-dir-agent", "a", "--review-dir", str(run)]
    runs = {f"ms {c}": [ms, c, *ms_ids] for c in ("red_team", "checklist", "top_down_methodology")}
    runs["ms bottom_up_methodology"] = [ms, "bottom_up_methodology", *ms_ids]
    runs.update({f"cp {c}": [cp, c, *cp_ids] for c in ("moat_scoring", "checklist", "startup_research")})
    runs["cp red_team"] = [cp, "red_team", *cp_ids, *cp_dirs]
    runs["fmr checklist"] = [fmr, "checklist", *fmr_ids]
    runs["dr checklist"] = [dr, "checklist", *fmr_ids]
    return runs


def _plugin_reads(root: Path, work: Path) -> dict[str, list[str]]:
    """Per generator run: every path under `root` it (or a process it started) opened or ran, relative."""
    runner = work / "audit_runner.py"
    runner.write_text(_AUDIT_RUNNER, encoding="utf-8")
    real_root = root.resolve()
    out: dict[str, list[str]] = {}
    for label, argv in _generator_runs(root, work).items():
        record = work / f"{label.replace(' ', '_')}.json"
        r = subprocess.run(
            [sys.executable, "-B", str(runner), str(record), *argv], capture_output=True, text=True, timeout=120
        )
        assert r.returncode == 0, (label, r.stderr)
        data = json.loads(record.read_text(encoding="utf-8"))
        assert data["code"] == 0, (label, r.stdout[-400:], r.stderr[-400:])
        rel = set()
        for seen in data["seen"]:
            path = Path(seen) if Path(seen).is_absolute() else Path(argv[0]).parent / seen
            try:
                rel.add(str(path.resolve().relative_to(real_root)))
            except ValueError:
                continue
        out[label] = sorted(rel)
    return out


def _not_hashed(reads: dict[str, list[str]]) -> dict[str, list[str]]:
    def hashed(rel: str) -> bool:
        return rel.endswith(".py") or (rel.endswith(".pyc") and "/__pycache__/" in f"/{rel}")

    return {
        label: [r for r in rels if not hashed(r)] for label, rels in reads.items() if any(not hashed(r) for r in rels)
    }


def test_every_plugin_file_a_generator_reads_is_a_hashed_script(tmp_path: Path) -> None:
    reads = _plugin_reads(PLUGIN, tmp_path)
    # Non-vacuity: every run was seen reading its own generator, the audit saw the gate modules the runs
    # import (as `.py`, or as cached `.pyc` when the source is not opened) and the probe one runs.
    gens = {
        "ms": MS_GEN_REL,
        "cp": "competitive-positioning/scripts/cp_dispatch_prompt.py",
        "fmr": "fmr_dispatch_prompt",
        "dr": "dr_dispatch_prompt",
    }
    assert len(reads) == 10 and all(any(gens[k.split()[0]].split("/")[-1] in r for r in v) for k, v in reads.items())
    seen = {Path(r).name.split(".")[0] for rels in reads.values() for r in rels}
    assert {
        "_ms_gates",
        "_sizing_redo",
        "_run_ref",
        "_cp_gates",
        "_cp_view",
        "pdf_probe",
        "_slide_reviews_file",
    } <= seen, seen
    assert _not_hashed(reads) == {}


def test_a_generator_reading_a_reference_file_is_caught(tmp_path: Path) -> None:
    """The lever: a copy whose generator reads a `references/` file at generation time is named."""
    root = _copy(tmp_path / "plugin")
    (root / "skills" / "market-sizing" / "references").mkdir(parents=True)
    (root / "skills" / "market-sizing" / "references" / "x.md").write_text("framing\n", encoding="utf-8")
    gen = root / MS_GEN_REL
    gen.write_text(
        gen.read_text(encoding="utf-8").replace(
            "\ndef main() -> None:\n",
            "\ndef main() -> None:\n    open(os.path.join(os.path.dirname(__file__), '..', 'references', 'x.md'))\n",
            1,
        ),
        encoding="utf-8",
    )
    work = tmp_path / "work"
    work.mkdir()
    assert _not_hashed(_plugin_reads(root, work)) == {
        label: ["skills/market-sizing/references/x.md"]
        for label in ("ms red_team", "ms checklist", "ms top_down_methodology", "ms bottom_up_methodology")
    }


# --- 8. a generator run from another installed copy is hashed where it ran -----------------------------------

_RAN_PRINTED = (
    "CONTEXT: RED_TEAM\nOUTPUT_PATH: /h/r1/redteam_output.json\nRUN_ID: R\n\nRead the documents.\n"
    "Do NOT write any file other than OUTPUT_PATH.\n"
)


def _dpc() -> Any:
    spec = importlib.util.spec_from_file_location("dpc_ran_path", SCRIPTS / "dispatch_prompt_check.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _ran_from(tmp_path: Path, generator: Path) -> Any:
    """The hook's decision on a RED_TEAM dispatch equal to what `generator`, run by its absolute path, printed."""
    rows: list[dict[str, Any]] = []
    for n, (tool, tool_input, result) in enumerate(
        [("Bash", {"command": f"python3 {generator} red_team --run-id R"}, _RAN_PRINTED)]
    ):
        use = {"type": "tool_use", "id": f"toolu_{n}", "name": tool, "input": tool_input}
        rows.append({"type": "assistant", "message": {"content": [use]}})
        rows.append({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": f"toolu_{n}",
                                                               "content": result}]}})  # fmt: skip
    transcript = tmp_path / "t.jsonl"
    transcript.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    tool_input = {"subagent_type": "founder-skills:market-sizing-redteam", "description": "d", "prompt": _RAN_PRINTED}
    return _dpc().decide(
        {
            "hook_event_name": "PreToolUse",
            "tool_name": "Agent",
            "transcript_path": str(transcript),
            "tool_input": tool_input,
        }
    )


@pytest.mark.usefixtures("plugin_hashes_current")
def test_a_generator_run_from_another_installed_copy_is_hashed_where_it_ran(tmp_path: Path) -> None:
    other = tmp_path / ".claude" / "plugins" / "x" / "founder-skills"
    generator = other / MS_GEN_REL
    generator.parent.mkdir(parents=True)
    shutil.copy2(PLUGIN / MS_GEN_REL, generator)
    # Control: the other copy's generator is the shipped one, so its print is compared (and matches).
    assert _ran_from(tmp_path, generator) is None
    with generator.open("ab") as f:
        f.write(b"# x\n")
    decision = _ran_from(tmp_path, generator)
    assert decision is not None, "a changed generator in another installed copy was compared"
    reason = decision["hookSpecificOutput"]["permissionDecisionReason"]
    assert f"The prompt generator that ran (`{generator}`) differs from the copy this version shipped with" in reason
    assert "after 2 holds" in reason and "$SCRIPTS" not in reason
    # The rule: a path the hook's host cannot open is never a mismatch (every Cowork-local VM path).
    generator.unlink()
    assert _ran_from(tmp_path, generator) is None


# --- 9. the hook loads this module the way the Python-3.9 floor test can see ------------------------------------


def test_the_hook_loads_the_module_where_the_floor_test_finds_it() -> None:
    """The floor test discovers a hook module only through the literal sibling-load spelling; a load spelled
    any other way would leave this module out of the 3.9 check, silently."""
    from test_hook_wrappers import _hook_files

    assert "scripts/script_hashes.py" in _hook_files(PLUGIN)


# --- the own-tree check is strict past the threshold -------------------------------------------------------


def test_check_on_its_own_tree_fails_when_many_files_differ_but_spares_another_root(tmp_path: Path) -> None:
    root = _copy(tmp_path)
    scripts = sorted(p for p in root.rglob("*.py") if "tests" not in p.relative_to(root).parts)
    threshold = SH.verify_detail(str(root), str(root / "data" / "script-hashes.json"))
    assert threshold[0] == [], "the copy must start clean"
    for path in scripts[:40]:
        path.write_text(path.read_text(encoding="utf-8") + "\n# edited\n", encoding="utf-8")
    assert SH.verify(str(root)) is None, "40 edits must exceed the threshold (lever engaged)"
    own = _check(root)
    assert own.returncode == 1, own.stderr
    assert "--write" in own.stderr
    other = subprocess.run(
        [sys.executable, str(SCRIPTS / "script_hashes.py"), "--check", "--root", str(root)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert other.returncode == 0, other.stderr
    assert "not checked" in other.stderr
