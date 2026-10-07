"""A plugin folder never reaches a sub-agent prompt through a shell command.

Recent Claude Desktop versions rewrite the plugin's (and a skill's) folder inside a shell command to its
path inside the VM before the command runs; other paths are left alone. A generator that took the
folder as a command-line argument printed that VM path into the CHECKLIST / MOAT_SCORING reference
lines, and a sub-agent's file tools are refused a VM path on a local session.

So the prompt generators do not take the folder from the shell. Each one decides from where it
runs: off a `/sessions` tree (CLI, cloud) it prints the absolute reference paths from its own location,
the same text as before; on a `/sessions` tree (local Desktop) it points the sub-agent at the full path
its own instructions give, naming only how that path ends. The agent body carries that full path,
filled in by the loader.

The simulation below is the one place these tests run the command lines a model copies out of SKILL.md.
It checks two things, because the old flag is now accepted and ignored: no plugin folder crosses the
shell at all (a token put back into a fence fails here), and no absolute reference path is printed on a
`/sessions` tree (a generator that renders its own folder there fails here -- that folder is a VM path).
"""

from __future__ import annotations

import difflib
import importlib.util
import re
import shlex
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

PLUGIN = Path(__file__).resolve().parents[1]
# `feedback` is a user-invoked skill that runs no shell and dispatches nothing, so it has no Step 0,
# hand-offs or report pipeline for these contracts to check.
SKILLS = sorted(p.parent.name for p in (PLUGIN / "skills").glob("*/SKILL.md") if p.parent.name != "feedback")
TOKEN = "${CLAUDE_PLUGIN_ROOT}"
MS_GEN = PLUGIN / "skills" / "market-sizing" / "scripts" / "dispatch_prompt.py"
CP_GEN = PLUGIN / "skills" / "competitive-positioning" / "scripts" / "cp_dispatch_prompt.py"
FMR_GEN = PLUGIN / "skills" / "financial-model-review" / "scripts" / "fmr_dispatch_prompt.py"
RESOLVER = PLUGIN / "scripts" / "resolve_artifacts_root.py"
# Off a /sessions tree each reference-naming prompt is pinned as readable text, one file per prompt, with the
# generator's plugin folder written as @PLUGIN_ROOT@. The files began as the previous generator's output when
# handed that folder; the one deliberate change since is competitive positioning's CHECKLIST naming its
# NARR_03 guide skill-qualified. A prompt change is a deliberate re-copy, and the failure shows the diff.
GOLDEN_DIR = PLUGIN / "tests" / "fixtures" / "dispatch_prompts"
ROOT_MARK = "@PLUGIN_ROOT@"
# A second off-session folder: rendering under it may change only the places the root placeholder sits.
OTHER_ROOT = "/opt/elsewhere/founder-skills"
HOOK = PLUGIN / "scripts" / "dispatch_prompt_check.py"

# The loader's value for the plugin folder on a local session (a host path), and the same folder as the
# VM shell sees it after the rewrite.
HOST_ROOT = "/private/var/folders/xx/T/claude-hostloop-plugins/abc/plugin_x"
SESSION_ROOT = "/sessions/quiet-bold-otter/mnt/.remote-plugins/plugin_x"

# An absolute path ending in a bundled reference, whatever its root: the VM path, the host path, or the
# folder the script runs from. A pointer names the tail with no leading slash and passes.
_ABS_REF = re.compile(r"(?<![\w.~-])/(?:[^\s`'\"()]*/)?skills/[a-z-]+/references/[\w./-]+")
_TAIL = re.compile(r"<PLUGIN_ROOT_AGENT>/(skills/[a-z-]+/references/[\w./-]+?\.md)")


def _load(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def rewrite(command: str) -> str:
    """What Desktop does to a shell command on a local session: the plugin folder becomes its VM path.
    Data and project paths are left alone. One function, so a wider rewrite is modelled in one place."""
    return command.replace(HOST_ROOT, SESSION_ROOT)


# --- the command lines the model copies -----------------------------------------------------------


def _fences(text: str) -> list[str]:
    return re.findall(r"^```bash\n(.*?)^```", text, re.MULTILINE | re.DOTALL)


def generator_commands() -> list[tuple[str, str, str]]:
    """(skill, context, command) for every generator call in a SKILL.md bash fence, continuations joined."""
    found: list[tuple[str, str, str]] = []
    for skill in SKILLS:
        text = (PLUGIN / "skills" / skill / "SKILL.md").read_text(encoding="utf-8")
        for fence in _fences(text):
            lines = fence.splitlines()
            i = 0
            while i < len(lines):
                line = lines[i]
                if re.match(r'^python3 "\$SCRIPTS/(cp_|fmr_)?dispatch_prompt\.py" ', line):
                    cmd = line
                    while cmd.endswith("\\"):
                        i += 1
                        cmd = cmd[:-1] + " " + lines[i].strip()
                    cmd = cmd.split("   #", 1)[0].strip()
                    found.append((skill, shlex.split(cmd)[2], cmd))
                i += 1
    return found


# Derived by hand, never from the scan: a scan that went blind would otherwise pass on nothing.
EXPECTED_COMMANDS = {
    ("market-sizing", "checklist"),
    ("market-sizing", "red_team"),
    # The sizing prompts: SKILL.md runs the top-down call in a fence and names the bottom-up one beside it.
    ("market-sizing", "top_down_methodology"),
    ("competitive-positioning", "startup_research"),
    ("competitive-positioning", "moat_scoring"),
    ("competitive-positioning", "positioning_scoring"),
    ("competitive-positioning", "checklist"),
    ("competitive-positioning", "red_team"),
    ("financial-model-review", "checklist"),
}
# The prompts that name a bundled reference, and the references each names.
EXPECTED_TAILS = {
    ("market-sizing", "checklist"): {
        "skills/market-sizing/references/pitfalls-checklist.md",
        "skills/market-sizing/references/artifact-schemas.md",
    },
    ("competitive-positioning", "moat_scoring"): {"skills/competitive-positioning/references/moat-definitions.md"},
    ("competitive-positioning", "checklist"): {"skills/competitive-positioning/references/checklist-criteria.md"},
    ("financial-model-review", "checklist"): {"skills/financial-model-review/references/checklist-criteria.md"},
}


def test_the_command_scan_finds_every_generator_call() -> None:
    assert {(s, c) for s, c, _ in generator_commands()} == EXPECTED_COMMANDS


def _workspace(tmp_path: Path) -> dict[str, str]:
    analysis = tmp_path / "analysis"
    handoff = analysis / "handoff" / "R"
    (handoff / "docs").mkdir(parents=True, exist_ok=True)
    for name in ("inputs", "methodology", "validation", "sizing"):
        (analysis / f"{name}.json").write_text("{}", encoding="utf-8")
    for name in ("product_profile", "landscape", "positioning_scores", "moat_scores"):
        (analysis / f"{name}.json").write_text("{}", encoding="utf-8")
    (handoff / "docs" / "deck.md").write_text("deck", encoding="utf-8")
    # financial-model-review's review folder: inputs.json and no model_data.json, the golden text's arm.
    review = tmp_path / "review"
    review.mkdir(exist_ok=True)
    (review / "inputs.json").write_text("{}", encoding="utf-8")
    return {
        "RUN_ID": "R",
        "ANALYSIS_DIR": str(analysis),
        "HANDOFF_DIR": str(handoff),
        "ANALYSIS_DIR_AGENT": "/agent/analysis",
        "HANDOFF_AGENT": "/agent/handoff/R",
        "REVIEW_DIR": str(review),
        "REVIEW_DIR_AGENT": "/agent/review",
    }


def _argv(skill: str, command: str, env: dict[str, str], plugin_value: str, *, lane_rewrite: bool) -> list[str]:
    """The command as the generator receives it: loader fills the token, Desktop may rewrite, the shell
    expands variables (a SKILL.md placeholder such as `<HANDOFF_AGENT>` stands for the same value)."""
    cmd = command.replace(TOKEN, plugin_value)
    if lane_rewrite:
        cmd = rewrite(cmd)
    values = {**env, "SCRIPTS": str(PLUGIN / "skills" / skill / "scripts")}
    cmd = re.sub(r"\$\{?([A-Z_]+)\}?", lambda m: values[m.group(1)], cmd)
    for key in ("ANALYSIS_DIR_AGENT", "HANDOFF_AGENT"):
        cmd = cmd.replace(f"<{key}>", values[key])
    return shlex.split(cmd)


def _run(
    argv: list[str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: Any,
    patches: dict[str, Any],
    *,
    cwd: str | None = None,
) -> tuple[int, str]:
    """Run a generator's main(). `cwd` is the working directory as the generator reads it (os.getcwd)."""
    script = Path(argv[1])
    mod = _load(script, f"sim_{script.stem}")
    for name, value in patches.items():
        monkeypatch.setattr(mod, name, value, raising=False)
    if cwd is not None:
        monkeypatch.setattr(mod.os, "getcwd", lambda: cwd)
    monkeypatch.setattr(sys, "argv", [str(script), *argv[2:]])
    code = 0
    try:
        mod.main()
    except SystemExit as e:
        code = int(e.code or 0)
    out = capsys.readouterr().out
    return code, out


def violations(argv: list[str], stdout: str) -> list[str]:
    found = [f"a plugin folder crossed the shell: {a}" for a in argv if SESSION_ROOT in a or HOST_ROOT in a]
    found += [f"absolute reference path printed: {m}" for m in _ABS_REF.findall(stdout)]
    if "/sessions/" in stdout:
        found.append("a /sessions path was printed")
    if TOKEN in stdout:
        found.append("an unfilled plugin token was printed")
    return found


def _on_a_session_tree() -> dict[str, Any]:
    """Installed under /sessions/<slug>/mnt/.remote-plugins/plugin_x/, as the VM shell runs it."""
    return {"_plugin_root": lambda: SESSION_ROOT}


# How a local session can show itself to a generator: (plugin folder it runs from, cwd it reads).
# None keeps the real value (this checkout; a temp dir). Either half on a /sessions tree selects the pointer.
SESSION_LANES = {
    "folder-under-mnt": (SESSION_ROOT, None),
    "cwd-on-sessions": (None, "/sessions/quiet-bold-otter"),
    "folder-outside-mnt": ("/sessions/s/plugins/founder-skills", "/tmp"),
}


@pytest.mark.parametrize("lane", sorted(SESSION_LANES))
@pytest.mark.parametrize("skill,context,command", generator_commands(), ids=lambda v: str(v)[:24])
def test_rewrite_simulation_prints_no_absolute_reference_path(
    skill: str, context: str, command: str, lane: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    folder, cwd = SESSION_LANES[lane]
    monkeypatch.chdir(tmp_path)
    argv = _argv(skill, command, _workspace(tmp_path), HOST_ROOT, lane_rewrite=True)
    patches = {"_plugin_root": lambda: folder} if folder is not None else {}
    code, out = _run(argv, monkeypatch, capsys, patches, cwd=cwd)
    assert code == 0, f"{skill} {context} exited {code}"
    assert out.startswith("CONTEXT: "), out[:200]
    assert violations(argv, out) == [], f"{skill} {context} ({lane})"
    for tail in EXPECTED_TAILS.get((skill, context), set()):
        assert f"ending {tail}" in out, f"{skill} {context} ({lane}): the pointer does not name {tail}"


def test_control_a_token_put_back_into_a_fence_is_caught(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    skill, context, command = next(c for c in generator_commands() if c[:2] == ("market-sizing", "checklist"))
    mutant = command + f' --plugin-root-agent "{TOKEN}"'
    monkeypatch.chdir(tmp_path)
    argv = _argv(skill, mutant, _workspace(tmp_path), HOST_ROOT, lane_rewrite=True)
    code, out = _run(argv, monkeypatch, capsys, _on_a_session_tree())
    assert code == 0
    assert any("crossed the shell" in v for v in violations(argv, out))


@pytest.mark.parametrize("pair", sorted(EXPECTED_TAILS))
def test_control_the_own_folder_default_on_a_session_tree_is_caught(
    pair: tuple[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    """A generator that renders the folder it runs from, whatever the lane, prints a VM path here."""
    skill, context, command = next(c for c in generator_commands() if c[:2] == pair)
    monkeypatch.chdir(tmp_path)
    argv = _argv(skill, command, _workspace(tmp_path), HOST_ROOT, lane_rewrite=True)
    code, out = _run(argv, monkeypatch, capsys, {**_on_a_session_tree(), "_on_session_lane": lambda: False})
    assert code == 0
    assert any(v.startswith("absolute reference path printed: /sessions/") for v in violations(argv, out)), out


# --- off a /sessions tree: the same text as before -----------------------------------------------


def _hook_squash() -> Any:
    """The dispatch hook's own whitespace normaliser, loaded from the hook, so the two cannot drift."""
    return _load(HOOK, "hook_dispatch_prompt_check")._squash


def text_mismatch(label: str, expected: str, actual: str) -> str:
    """'' when equal; otherwise a unified diff, and a whitespace-only change named as one."""
    if expected == actual:
        return ""
    diff = difflib.unified_diff(
        expected.splitlines(keepends=True), actual.splitlines(keepends=True), "golden", "printed", n=1
    )
    msg = f"{label}: the printed prompt is not the golden text.\n" + "".join(diff)
    if _hook_squash()(expected) == _hook_squash()(actual):
        changed = [ln for ln in difflib.ndiff(expected.splitlines(), actual.splitlines()) if ln[:2] in ("- ", "+ ")]
        msg += (
            "\nWHITESPACE ONLY. The dispatch hook squashes whitespace, so it would accept either prompt; this "
            "test still fails, because the printed text changed. If the change is intended, copy the new "
            "output into the golden file. Changed lines, exactly:\n" + "\n".join(repr(ln) for ln in changed)
        )
    return msg


def _template(skill: str, context: str) -> str:
    gen = {"market-sizing": MS_GEN, "competitive-positioning": CP_GEN, "financial-model-review": FMR_GEN}[skill]
    mod = _load(gen, f"tpl_{gen.stem}")
    return str(mod._TEMPLATES[context] if skill == "competitive-positioning" else mod._CHECKLIST_TEMPLATE)


@pytest.mark.parametrize("pair", sorted(EXPECTED_TAILS))
def test_off_a_session_tree_the_prompt_is_the_golden_text(
    pair: tuple[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    """CLI and cloud: the golden text with the root placeholder set to the generator's own folder, and
    nothing else in it depends on the root. The loader value is set to a different folder, so a path that
    came through the shell would show."""
    skill, context, command = next(c for c in generator_commands() if c[:2] == pair)
    golden = (GOLDEN_DIR / f"{skill}.{context}.txt").read_text(encoding="utf-8")
    # The root sits exactly where the template puts its placeholder, no more, no fewer.
    assert golden.count(ROOT_MARK) == _template(skill, context).count("<PLUGIN_ROOT_AGENT>") > 0
    monkeypatch.chdir(tmp_path)
    argv = _argv(skill, command, _workspace(tmp_path), HOST_ROOT, lane_rewrite=False)
    code, out = _run(argv, monkeypatch, capsys, {})
    assert code == 0
    assert HOST_ROOT not in out
    assert not (m := text_mismatch(f"{skill} {context}", golden.replace(ROOT_MARK, str(PLUGIN)), out)), m
    # Root independence: under another off-session folder only the placeholder sites change.
    code, out = _run(argv, monkeypatch, capsys, {"_plugin_root": lambda: OTHER_ROOT})
    assert code == 0
    assert not (m := text_mismatch(f"{skill} {context} at {OTHER_ROOT}", golden.replace(ROOT_MARK, OTHER_ROOT), out)), m


def test_the_mismatch_message_shows_a_diff_and_names_a_whitespace_only_change() -> None:
    golden = (GOLDEN_DIR / "market-sizing.checklist.txt").read_text(encoding="utf-8")
    assert "not `fail`. There was nothing" in golden
    spaced = golden.replace("not `fail`. There was nothing", "not `fail`.  There was nothing")
    msg = text_mismatch("ms", golden, spaced)
    assert "+not `fail`.  There was nothing" in msg and "WHITESPACE ONLY" in msg
    worded = golden.replace("not `fail`. There was nothing", "not `fail`. There is nothing")
    msg = text_mismatch("ms", golden, worded)
    assert "+not `fail`. There is nothing" in msg and "WHITESPACE ONLY" not in msg
    assert text_mismatch("ms", golden, golden) == ""


# --- the old flag: accepted, ignored, unlisted ---------------------------------------------------


# financial-model-review's generator is not here: it never took the folder flag, so it has no older
# command line to stay compatible with.
_CLI_CASES = [
    (MS_GEN, "checklist"),
    (CP_GEN, "moat_scoring"),
    (CP_GEN, "positioning_scoring"),
    (CP_GEN, "checklist"),
    (CP_GEN, "startup_research"),
    (CP_GEN, "red_team"),
]


def _cli(gen: Path, context: str, tmp_path: Path, extra: list[str]) -> subprocess.CompletedProcess[str]:
    env = _workspace(tmp_path)
    args = [context, "--run-id", "R", "--handoff-agent", env["HANDOFF_AGENT"]]
    args += ["--analysis-dir-agent", env["ANALYSIS_DIR_AGENT"], "--analysis-dir", env["ANALYSIS_DIR"]]
    args += ["--handoff-dir", env["HANDOFF_DIR"]]
    return subprocess.run(
        [sys.executable, str(gen), *args, *extra], capture_output=True, text=True, timeout=60, cwd=tmp_path
    )


@pytest.mark.parametrize("gen,context", _CLI_CASES, ids=lambda v: getattr(v, "stem", v))
def test_the_old_flag_changes_nothing(gen: Path, context: str, tmp_path: Path) -> None:
    """A model copying an older command line gets the same prompt, never an exit 2 -- including the
    values the previous generator refused (a pasted token on a first-message session, a relative path)."""
    plain = _cli(gen, context, tmp_path / "plain", [])
    assert plain.returncode == 0 and plain.stderr == "", plain.stderr
    for value in ("/p", TOKEN, "rel/path", "", SESSION_ROOT):
        r = _cli(gen, context, tmp_path / "plain", ["--plugin-root-agent", value])
        assert (r.returncode, r.stdout, r.stderr) == (0, plain.stdout, ""), (value, r.stderr)


@pytest.mark.parametrize("gen", [MS_GEN, CP_GEN, FMR_GEN], ids=lambda p: p.stem)
def test_help_does_not_offer_the_old_flag(gen: Path) -> None:
    r = subprocess.run([sys.executable, str(gen), "--help"], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0
    assert "plugin-root" not in r.stdout + r.stderr


# --- lane detection is the resolver's ----------------------------------------------------------


@pytest.mark.parametrize("gen", [MS_GEN, CP_GEN, FMR_GEN], ids=lambda p: p.stem)
def test_lane_detection_is_a_copy_of_the_resolvers(gen: Path) -> None:
    mod = _load(gen, f"lane_{gen.stem}")
    res = _load(RESOLVER, "lane_resolver")
    assert mod._SESSION_TREE.pattern == res._SESSION_TREE.pattern
    assert mod._SESSION_ROOT.pattern == res._SESSION_ROOT.pattern
    for path in (
        SESSION_ROOT,
        "/sessions/x",
        "/sessions/x/mnt",
        "/sessions/x/mnt/outputs",
        "/sessions/x/other",
        "/home/u/sessions/x/mnt/y",
        "/root/.claude/plugins/synced/o_a/founder-skills",
        "/home/claude",
        HOST_ROOT,
    ):
        assert mod.on_session_tree(path) == res.on_session_tree(path), path


@pytest.mark.parametrize("gen", [MS_GEN, CP_GEN, FMR_GEN], ids=lambda p: p.stem)
def test_the_lane_is_read_from_the_folder_and_the_cwd(
    gen: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mod = _load(gen, f"lane2_{gen.stem}")
    monkeypatch.chdir(tmp_path)
    assert mod._on_session_lane() is False  # this checkout, run from a temp dir
    monkeypatch.setattr(mod, "_plugin_root", lambda: SESSION_ROOT)
    assert mod._on_session_lane() is True
    monkeypatch.setattr(mod, "_plugin_root", lambda: "/sessions/s/plugins/founder-skills")
    assert mod._on_session_lane() is True  # any plugin folder under /sessions, not only under mnt/
    monkeypatch.setattr(mod, "_plugin_root", lambda: "/root/.claude/plugins/synced/o_a/founder-skills")
    assert mod._on_session_lane() is False
    monkeypatch.setattr(mod.os, "getcwd", lambda: "/sessions/quiet-bold-otter")
    assert mod._on_session_lane() is True


# --- the shell never carries the plugin folder outside Step 0 ------------------------------------


_SCRIPT_PATH = re.compile(r'python3?\s+"?\$\{CLAUDE_PLUGIN_ROOT\}/[^\s"]*\.py"?')


def token_sites(text: str, *, skip_step0: bool) -> list[str]:
    """Lines in a bash fence that hand the plugin token to a program as anything but the script to run."""
    if skip_step0:
        start = text.find("### Step 0")
        if start >= 0:
            nxt = re.search(r"\n#{2,3} ", text[start + 1 :])
            end = start + 1 + nxt.start() if nxt else len(text)
            text = text[:start] + text[end:]
    sites: list[str] = []
    for fence in _fences(text):
        for line in fence.splitlines():
            if TOKEN in _SCRIPT_PATH.sub("", line):
                sites.append(line.strip())
    return sites


def _guarded_files() -> list[tuple[Path, bool]]:
    files = [(PLUGIN / "skills" / s / "SKILL.md", True) for s in SKILLS]
    files += [(p, False) for p in sorted((PLUGIN / "skills").glob("*/references/**/*.md"))]
    files += [(p, False) for p in sorted((PLUGIN / "references").glob("**/*.md"))]
    return files


def test_no_bash_fence_passes_the_plugin_token_outside_step_0() -> None:
    found = {
        str(path.relative_to(PLUGIN)): sites
        for path, skip in _guarded_files()
        if (sites := token_sites(path.read_text(encoding="utf-8"), skip_step0=skip))
    }
    assert found == {}, found


def test_the_token_guard_sees_an_argument_and_spares_a_script_path() -> None:
    doc = (
        '### Step 0\n```bash\nSCRIPTS="${CLAUDE_PLUGIN_ROOT}/skills/x/scripts"\n```\n### Step 1\n'
        '```bash\npython3 "${CLAUDE_PLUGIN_ROOT}/skills/x/scripts/y.py" --a b\n'
        'python3 "$SCRIPTS/g.py" checklist \\\n  --plugin-root-agent "${CLAUDE_PLUGIN_ROOT}"\n```\n'
    )
    assert token_sites(doc, skip_step0=True) == ['--plugin-root-agent "${CLAUDE_PLUGIN_ROOT}"']
    assert len(token_sites(doc, skip_step0=False)) == 2
    assert len(_guarded_files()) > len(SKILLS)  # the reference fences are in scope


# --- the agent bodies carry the full paths the pointer sends the sub-agent to -------------------


_GEN_AGENT = {MS_GEN: "market-sizing", CP_GEN: "competitive-positioning", FMR_GEN: "financial-model-review"}


def _template_tails() -> dict[tuple[str, str], set[str]]:
    """(agent, CONTEXT) -> reference tails, parsed from each generator module's templates."""
    out: dict[tuple[str, str], set[str]] = {}
    for gen, agent in _GEN_AGENT.items():
        for value in vars(_load(gen, f"tails_{gen.stem}")).values():
            if isinstance(value, str) and value.startswith("CONTEXT: ") and _TAIL.search(value):
                context = value.split("\n", 1)[0].removeprefix("CONTEXT: ")
                out.setdefault((agent, context), set()).update(_TAIL.findall(value))
    return out


def _subtype_section(agent: str, context: str) -> str:
    text = (PLUGIN / "agents" / f"{agent}.md").read_text(encoding="utf-8")
    start = text.index(f"#### {context} subtype")
    nxt = re.search(r"\n#{2,4} ", text[start + 1 :])
    return text[start : start + 1 + nxt.start()] if nxt else text[start:]


def test_template_tails_match_the_expected_references() -> None:
    expected = {
        ("market-sizing", "CHECKLIST"): EXPECTED_TAILS[("market-sizing", "checklist")],
        ("competitive-positioning", "MOAT_SCORING"): EXPECTED_TAILS[("competitive-positioning", "moat_scoring")],
        ("competitive-positioning", "CHECKLIST"): EXPECTED_TAILS[("competitive-positioning", "checklist")],
        ("financial-model-review", "CHECKLIST"): EXPECTED_TAILS[("financial-model-review", "checklist")],
    }
    assert _template_tails() == expected


@pytest.mark.parametrize("agent,context", sorted(_template_tails()))
def test_each_pointed_reference_has_its_full_path_in_that_subtype(agent: str, context: str) -> None:
    section = _subtype_section(agent, context)
    for tail in _template_tails()[(agent, context)]:
        assert f"`{TOKEN}/{tail}`" in section, f"agents/{agent}.md {context}: no full path for {tail}"


MAIN_AGENTS = (
    "cap-table",
    "competitive-positioning",
    "deck-review",
    "financial-model-review",
    "ic-sim",
    "market-sizing",
)
PLUGIN_FOLDER_LINE = (
    f"Your plugin folder is `{TOKEN}`. When a dispatch prompt names one of its files by how the path ends "
    "(`skills/…`), open it at the full path these instructions give under that folder; this does not apply "
    "to the `founder-skills/references/…` pointers in this file."
)


@pytest.mark.parametrize("agent", MAIN_AGENTS)
def test_every_main_agent_states_its_plugin_folder(agent: str) -> None:
    text = (PLUGIN / "agents" / f"{agent}.md").read_text(encoding="utf-8")
    assert PLUGIN_FOLDER_LINE in text, agent
    assert text.index(PLUGIN_FOLDER_LINE) < text.index("## Dispatch Contexts"), agent


def test_market_sizing_checklist_may_open_the_full_paths_it_is_given() -> None:
    section = _subtype_section("market-sizing", "CHECKLIST")
    assert "Read the files your prompt names, and only those: the checklist reference, the schema's" not in section
    assert "open them at the full paths above" in section
