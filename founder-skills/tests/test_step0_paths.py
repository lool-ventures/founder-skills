"""Step 0 finds the plugin's files on every lane, including when the skill text arrives unfilled.

The loader fills `${CLAUDE_PLUGIN_ROOT}` into a skill's text before the model sees it. On every lane
where it does, the filled value is right for the Read tool, so each Read, dispatch and generator
argument keeps the token in place. A skill typed as the FIRST message of a new conversation is the
exception: its text is expanded outside Claude Code, the token arrives literal, and every path built
from it points nowhere. Step 0 detects which of the two happened and, only when the text is literal,
finds the plugin on disk and prints `READ_ROOT=` for the model to write in the token's place.

These tests run the REAL Step 0 block, extracted from each SKILL.md, under `env -i sh` (dash on Linux
CI, bash-as-sh on macOS) against fake plugin trees. Only the filesystem roots are redirected into the
fake tree; the loader's textual substitution is applied the way the loader applies it, or left out.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PLUGIN = REPO_ROOT / "founder-skills"
SKILLS = sorted(p.parent.name for p in (PLUGIN / "skills").glob("*/SKILL.md"))
TOKEN = "${CLAUDE_PLUGIN_ROOT}"
VERSION = json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text())["version"]

# The fallback sentence every sub-agent prompt that carries a bundled reference path must hold.
SUBAGENT_FALLBACK = (
    "If a reference path below cannot be read (refused or not found), read the same file under the plugin folder "
    "your own instructions name."
)


def _step0_section(skill: str) -> str:
    text = (PLUGIN / "skills" / skill / "SKILL.md").read_text(encoding="utf-8")
    start = text.index("### Step 0")
    end = text.index("\n### ", start + 1)
    return text[start:end]


def _step0_fence(skill: str) -> str:
    section = _step0_section(skill)
    m = re.search(r"```bash\n(.*?)\n```", section, re.DOTALL)
    assert m, f"{skill}: no ```bash fence in Step 0"
    return m.group(1)


# Filesystem roots redirected into the fake tree. Each is anchored so that `find /` cannot match
# inside `find /sessions` (rewrite order then stops mattering), and a pattern ABSENT from a block is
# skipped rather than asserted here: that block must then fail on what it prints, not on this
# harness's bookkeeping. `test_every_redirect_matches_its_block_once` owns the count.
REDIRECTS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    ("find /sessions", re.compile(r"\bfind /sessions -type"), 'find "$FAKE/sessions" -type'),
    (
        "find /root/.claude/plugins",
        re.compile(r"\bfind /root/\.claude/plugins -type"),
        'find "$FAKE/root/.claude/plugins" -type',
    ),
    ("find /", re.compile(r"\bfind / -type"), 'find "$FAKE" -type'),
    ("/sessions/*) arm", re.compile(r"^(\s*)/sessions/\*\)", re.MULTILINE), r'\1"$FAKE"/sessions/*)'),
)


def _redirected(block: str) -> str:
    for _, pattern, repl in REDIRECTS:
        block = pattern.sub(repl, block)
    assert not re.search(r"\bfind /", block), "an unredirected find would walk the real filesystem"
    return block


def _plugin_copy(root: Path, *, name: str = "founder-skills", version: str = VERSION, manifest: bool = True) -> Path:
    (root / ".claude-plugin").mkdir(parents=True)
    if manifest:
        (root / ".claude-plugin" / "plugin.json").write_text(json.dumps({"name": name, "version": version}))
    (root / "scripts").mkdir()
    for f in (PLUGIN / "scripts").glob("*.py"):
        shutil.copy(f, root / "scripts" / f.name)
    for skill in SKILLS:
        (root / "skills" / skill / "scripts").mkdir(parents=True)
    return root


def _chat_mount(fake: Path) -> None:
    """claude.ai's flat skill mount: never `skills/<skill>/scripts`, and no plugin around it."""
    for skill in SKILLS:
        (fake / "mnt" / "skills" / "plugins" / f"founder-skills:{skill}" / "scripts").mkdir(parents=True)


def _run(
    skill: str,
    fake: Path,
    token: str | None,
    *,
    env: dict[str, str] | None = None,
    cwd: Path | None = None,
    mutate: Callable[[str], str] | None = None,
) -> tuple[dict[str, str], str, subprocess.CompletedProcess[str]]:
    block = _step0_fence(skill)
    if mutate:
        block = mutate(block)
    block = _redirected(block)
    if token is not None:
        block = block.replace(TOKEN, token)  # the loader's textual fill
    script = fake.parent / f"step0-{skill}.sh"
    script.write_text(block + "\n", encoding="utf-8")
    base = {
        "PATH": os.pathsep.join([os.path.dirname(sys.executable), "/usr/bin", "/bin"]),
        "HOME": str(fake.parent / "home"),
        "FAKE": str(fake),
        "COWORK_ARTIFACTS_ROOT": str(fake.parent / "artifacts"),
    }
    proc = subprocess.run(
        ["/usr/bin/env", "-i", *(f"{k}={v}" for k, v in {**base, **(env or {})}.items()), "sh", str(script)],
        capture_output=True,
        text=True,
        cwd=cwd or fake.parent,
        timeout=60,
    )
    values: dict[str, str] = {}
    for line in proc.stdout.splitlines():
        for key in ("PLUGIN_ROOT", "PATH_STATE", "READ_ROOT"):
            if line.startswith(key + "="):
                assert key not in values, f"{key} printed twice:\n{proc.stdout}"
                values[key] = line[len(key) + 1 :]
    return values, proc.stdout, proc


def _fake(tmp_path: Path) -> Path:
    fake = tmp_path / "fake"
    fake.mkdir()
    (tmp_path / "home").mkdir()
    return fake


def _synced(fake: Path) -> Path:
    return _plugin_copy(fake / "root" / ".claude" / "plugins" / "synced" / "o_a" / "founder-skills")


def _assert_filled(values: dict[str, str], out: str, state: str, plugin_root: Path | str) -> None:
    assert values.get("PATH_STATE") == state, f"expected PATH_STATE={state}:\n{out}"
    assert values.get("PLUGIN_ROOT") == str(plugin_root), out
    assert "READ_ROOT" not in values, f"READ_ROOT printed for filled text:\n{out}"
    assert "UNSUPPORTED_ENVIRONMENT" not in out


def _assert_literal(values: dict[str, str], out: str, plugin_root: Path) -> None:
    assert values.get("PATH_STATE") == "literal", f"expected PATH_STATE=literal:\n{out}"
    assert values.get("PLUGIN_ROOT") == str(plugin_root), out
    assert values.get("READ_ROOT") == str(plugin_root), out
    assert "UNSUPPORTED_ENVIRONMENT" not in out


# --- the lanes ---------------------------------------------------------------------------------


@pytest.mark.parametrize("skill", SKILLS)
@pytest.mark.parametrize("folder", ["install", "Application Support", "o'brien"])
def test_cli_text_filled_with_the_install_dir(skill: str, folder: str, tmp_path: Path) -> None:
    """The CLI (and the SDK lane): the filled path is right, nothing is searched for."""
    fake = _fake(tmp_path)
    root = _plugin_copy(fake / folder / "founder-skills")
    _plugin_copy(fake / "sessions" / "a" / "mnt" / ".local-plugins" / "founder-skills")  # found only by a search
    values, out, _ = _run(skill, fake, str(root))
    _assert_filled(values, out, "substituted", root)


@pytest.mark.parametrize("skill", SKILLS)
def test_cloud_text_filled_with_the_synced_dir(skill: str, tmp_path: Path) -> None:
    fake = _fake(tmp_path)
    root = _synced(fake)
    values, out, _ = _run(skill, fake, str(root))
    _assert_filled(values, out, "substituted", root)


@pytest.mark.parametrize("skill", SKILLS)
def test_hostloop_host_path_absent_from_the_shell(skill: str, tmp_path: Path) -> None:
    """Host-loop, untranslated: the shell finds the session mount; Reads keep the host path as shown."""
    fake = _fake(tmp_path)
    mount = _plugin_copy(fake / "sessions" / "x" / "mnt" / ".local-plugins" / "marketplaces" / "m" / "founder-skills")
    values, out, _ = _run(skill, fake, "/nonexistent-host/claude-hostloop-plugins/h1/plugin_1")
    _assert_filled(values, out, "local", mount)


@pytest.mark.parametrize("skill", SKILLS)
@pytest.mark.parametrize("mount", [".remote-plugins/plugin_1", ".local-plugins/marketplaces/m/founder-skills"])
def test_session_mount_path_in_the_text(skill: str, mount: str, tmp_path: Path) -> None:
    """Host-loop with the command rewritten to the session mount, and the VM loop: no search runs."""
    fake = _fake(tmp_path)
    _plugin_copy(fake / "sessions" / "a" / "mnt" / ".local-plugins" / "founder-skills")  # a search would find this
    root = _plugin_copy(fake / "sessions" / "x" / "mnt" / Path(mount))
    values, out, _ = _run(skill, fake, str(root))
    _assert_filled(values, out, "local", root)


@pytest.mark.parametrize("skill", SKILLS)
def test_windows_style_root_is_not_treated_as_unfilled(skill: str, tmp_path: Path) -> None:
    """A filled root that is not a POSIX path is still filled: Step 0 must not discard it and search."""
    fake = _fake(tmp_path)
    _synced(fake)  # a search would find this
    _plugin_copy(fake / "C:\\x")
    values, out, _ = _run(skill, fake, "C:\\x", cwd=fake)
    _assert_filled(values, out, "substituted", "C:\\x")


@pytest.mark.parametrize("skill", SKILLS)
@pytest.mark.parametrize("token", [None, ""], ids=["literal", "empty"])
def test_unfilled_text_finds_the_synced_plugin(skill: str, token: str | None, tmp_path: Path) -> None:
    """The fix: literal (or empty) text -> search, skip lookalikes, print READ_ROOT."""
    fake = _fake(tmp_path)
    root = _synced(fake)
    _chat_mount(fake)
    _plugin_copy(fake / "aa-other-plugin", name="other-plugin")
    values, out, _ = _run(skill, fake, token)
    _assert_literal(values, out, root)


@pytest.mark.parametrize("skill", SKILLS)
def test_unfilled_text_ignores_another_plugins_exported_root(skill: str, tmp_path: Path) -> None:
    """Literal text, but the shell exports a different plugin's root: the search still decides."""
    fake = _fake(tmp_path)
    root = _synced(fake)
    other = _plugin_copy(fake / "aa-other-plugin", name="other-plugin")
    values, out, _ = _run(skill, fake, None, env={"CLAUDE_PLUGIN_ROOT": str(other)})
    _assert_literal(values, out, root)


@pytest.mark.parametrize("skill", SKILLS)
def test_another_plugin_where_ours_is_expected_does_not_end_the_search(skill: str, tmp_path: Path) -> None:
    """Lookalikes are dropped BEFORE a search step is judged empty, so the next step still runs."""
    fake = _fake(tmp_path)
    _plugin_copy(fake / "root" / ".claude" / "plugins" / "synced" / "o_a" / "other-plugin", name="other-plugin")
    root = _plugin_copy(fake / "opt" / "founder-skills")
    values, out, _ = _run(skill, fake, None)
    _assert_literal(values, out, root)


@pytest.mark.parametrize("skill", SKILLS)
def test_an_older_copy_outside_the_plugins_folder_is_never_reached(skill: str, tmp_path: Path) -> None:
    """The plugins folder is searched before `/`. Which copy wins can depend on directory order, so the
    proof is that the selector never saw the older copy at all: it names every copy it rejects."""
    fake = _fake(tmp_path)
    _plugin_copy(fake / "aaa-old-founder-skills", version="0.0.1")
    root = _synced(fake)
    values, out, proc = _run(skill, fake, None)
    _assert_literal(values, out, root)
    assert "aaa-old" not in proc.stderr, f"the search reached past the plugins folder:\n{proc.stderr}"


@pytest.mark.parametrize("skill", SKILLS)
def test_another_plugin_in_the_session_mounts_does_not_end_the_search(skill: str, tmp_path: Path) -> None:
    """A lookalike under /sessions is dropped before that step is judged empty, so the plugins folder is
    still searched and the selector never sees the lookalike."""
    fake = _fake(tmp_path)
    _plugin_copy(fake / "sessions" / "x" / "mnt" / ".remote-plugins" / "plugin_9", name="other-plugin")
    root = _synced(fake)
    values, out, proc = _run(skill, fake, None)
    _assert_literal(values, out, root)
    assert "plugin_9" not in proc.stderr, proc.stderr


@pytest.mark.parametrize("skill", SKILLS)
def test_a_session_mount_without_a_manifest_is_kept(skill: str, tmp_path: Path) -> None:
    """Only a readable manifest naming ANOTHER plugin drops a candidate. A mount with no manifest is kept,
    as the selector keeps it: dropping it leaves a working mount unused and stops the run."""
    fake = _fake(tmp_path)
    mount = _plugin_copy(fake / "sessions" / "x" / "mnt" / ".remote-plugins" / "plugin_1", manifest=False)
    values, out, _ = _run(skill, fake, "/nonexistent-host/claude-hostloop-plugins/h1/plugin_1")
    _assert_filled(values, out, "local", mount)


@pytest.mark.parametrize("skill", SKILLS)
def test_unfilled_text_keeps_a_copy_without_a_manifest(skill: str, tmp_path: Path) -> None:
    fake = _fake(tmp_path)
    root = _plugin_copy(fake / "root" / ".claude" / "plugins" / "synced" / "o_a" / "founder-skills", manifest=False)
    _plugin_copy(fake / "aa-other-plugin", name="other-plugin")
    values, out, _ = _run(skill, fake, None)
    _assert_literal(values, out, root)


@pytest.mark.parametrize("skill", SKILLS)
def test_two_copies_in_the_plugins_folder_resolve_consistently(skill: str, tmp_path: Path) -> None:
    """Two copies side by side: the selector decides and names the other; READ_ROOT follows it."""
    fake = _fake(tmp_path)
    old = _plugin_copy(fake / "root" / ".claude" / "plugins" / "synced" / "aaa_old" / "founder-skills", version="0.0.1")
    new = _synced(fake)
    values, out, proc = _run(skill, fake, None)
    assert proc.returncode == 0, proc.stderr
    assert values.get("PATH_STATE") == "literal", out
    assert values.get("PLUGIN_ROOT") in {str(old), str(new)}, out
    assert values.get("READ_ROOT") == values.get("PLUGIN_ROOT"), out
    assert "rejected" in proc.stderr, f"the selector must name the copy it did not take:\n{proc.stderr}"
    values, out, _ = _run(skill, fake, None, env={"EXPECT_VERSION": VERSION})
    _assert_literal(values, out, new)


@pytest.mark.parametrize("skill", SKILLS)
def test_chat_runtime_stops_with_exactly_one_marker(skill: str, tmp_path: Path) -> None:
    """A surface with no plugin around the skill prints the stop marker once, and nothing else of ours."""
    fake = _fake(tmp_path)
    _chat_mount(fake)
    values, out, _ = _run(skill, fake, None)
    assert out.count("UNSUPPORTED_ENVIRONMENT") == 1, out
    assert "PATH_STATE" not in values and "READ_ROOT" not in values, out


@pytest.mark.parametrize("skill", SKILLS)
def test_control_without_the_unfilled_check_the_exported_root_wins(skill: str, tmp_path: Path) -> None:
    """Positive control: drop the line that discards an unfilled path and the wrong plugin is chosen."""
    fake = _fake(tmp_path)
    _synced(fake)
    other = _plugin_copy(fake / "aa-other-plugin", name="other-plugin")

    def drop_case_line(block: str) -> str:
        lines = [ln for ln in block.splitlines() if not ln.startswith('case "$TEXT_ROOT_RAW" in *')]
        assert len(lines) == len(block.splitlines()) - 1, "the unfilled-check line was not found"
        return "\n".join(lines)

    values, out, _ = _run(skill, fake, None, env={"CLAUDE_PLUGIN_ROOT": str(other)}, mutate=drop_case_line)
    assert values.get("PLUGIN_ROOT") == str(other), out


@pytest.mark.parametrize("skill", SKILLS)
def test_every_redirect_matches_its_block_once(skill: str) -> None:
    """The harness redirects every filesystem root the block touches, each exactly once."""
    block = _step0_fence(skill)
    counts = {label: len(pattern.findall(block)) for label, pattern, _ in REDIRECTS}
    assert counts == dict.fromkeys(counts, 1), f"{skill}: {counts}"


# --- the lines that must stay identical across the fleet ---------------------------------------

STEP0_LINES = (
    "IFS= read -r TEXT_ROOT_RAW <<'EOF'\n${CLAUDE_PLUGIN_ROOT}\nEOF\n",
    'SCRIPTS="${CLAUDE_PLUGIN_ROOT}/skills/{skill}/scripts"\n',
    """case "$TEXT_ROOT_RAW" in *'$'*|'') SCRIPTS="" ;; esac""",
    """  ours() { python3 -c 'import json, sys
for c in sys.stdin.read().splitlines():
    try: n = json.load(open(c.rsplit("/skills/", 1)[0] + "/.claude-plugin/plugin.json"))["name"]
    except Exception: n = "founder-skills"
    if n == "founder-skills": print(c)'; }""",
    "  CANDIDATES=\"$(find /sessions -type d -path '*/skills/{skill}/scripts' 2>/dev/null | ours)\"\n"
    '  [ -n "$CANDIDATES" ] || '
    "CANDIDATES=\"$(find /root/.claude/plugins -type d -path '*/skills/{skill}/scripts' 2>/dev/null | ours)\"\n"
    '  [ -n "$CANDIDATES" ] || CANDIDATES="$(find / -type d -path \'*/skills/{skill}/scripts\' 2>/dev/null | ours)"\n',
    'echo "PLUGIN_ROOT=$PLUGIN_ROOT"   # resolved ONCE, here — paste this literal into every later block; '
    "never re-run this resolution. PLUGIN_ROOT is the shell's path: never Read from it or put it in a "
    "sub-agent prompt. Exception: a READ_ROOT= printed below goes in Reads and prompts.\n",
    """[ -f "$SHARED_SCRIPTS/check_handoff.py" ] && case "$TEXT_ROOT_RAW" in
  *'$'*|'') echo "PATH_STATE=literal"; echo "READ_ROOT=$PLUGIN_ROOT" ;;
  /sessions/*) echo "PATH_STATE=local" ;;
  *) if [ -d "$TEXT_ROOT_RAW" ]; then echo "PATH_STATE=substituted"; else echo "PATH_STATE=local"; fi ;;
esac
""",
)

# The folder for Reads is named in prose, outside the fence, so the loader fills it on the lanes where it fills
# anything. The condition is Step 0's output, never the token: a token inside "if these still show ..." is
# filled too, which turns the condition into "if these still show /real/path" -- always true.
STEP0_READS_LINE = (
    "Plugin folder for Reads and prompts (as loaded): `${CLAUDE_PLUGIN_ROOT}` — this skill's references are in "
    "`${CLAUDE_PLUGIN_ROOT}/skills/{skill}/references/`. If Step 0 printed `READ_ROOT=`, use that value instead.\n\n"
)

# STEP0_READS_LINE is pinned to sit immediately before this paragraph.
STEP0_PROSE = (
    "**Plugin paths.** If Step 0 printed `READ_ROOT=`, this skill's text arrived without its plugin folder "
    "filled in. Use that value in place of `${CLAUDE_PLUGIN_ROOT}` in every Read and sub-agent prompt, "
    "including where a later step says to leave that path literal. If it did "
    "not print `READ_ROOT=`, use the paths as shown. The folder comes from Step 0's filesystem search, not from "
    'a skill file or the "Base directory" line, which can name a folder that does not exist. These are setup '
    "details: updates to the founder are about their company, not file locations, printed paths or plugin versions."
)

# Said before the fence: a block whose token was hand-filled before it ran cannot tell the two lanes apart.
STEP0_RUN_AS_SHOWN = "Run the block below with `${CLAUDE_PLUGIN_ROOT}` exactly as it appears.\n\n```bash\n"


@pytest.mark.parametrize("skill", SKILLS)
def test_step0_bootstrap_lines_are_fleet_identical(skill: str) -> None:
    fence = _step0_fence(skill)
    for line in STEP0_LINES:
        expected = line.replace("{skill}", skill)
        assert expected in fence, f"{skill}: Step 0 lost or changed:\n{expected}"
    section = _step0_section(skill)
    assert STEP0_PROSE in section, f"{skill}: Step 0 lost the plugin-paths paragraph"
    reads = STEP0_READS_LINE.replace("{skill}", skill)
    assert reads + STEP0_PROSE in section, f"{skill}: the folder-for-Reads line is not right before the paragraph"
    assert STEP0_RUN_AS_SHOWN in section, f"{skill}: Step 0 no longer says to run the block as it appears"
    assert "self-heal branch is normal" not in section, f"{skill}: the stale self-heal note is back"
    assert "Skip it if that path still begins with `$`." in section, f"{skill}: best-effort Read lacks its skip"


@pytest.mark.parametrize("skill", SKILLS)
def test_step0_never_keys_on_the_flat_skill_mount_or_reads_a_skill_file(skill: str) -> None:
    """The fallback is a filesystem search. `/mnt/skills` does not identify the chat surface."""
    fence = _step0_fence(skill)
    code = "\n".join(ln.split("#", 1)[0] for ln in fence.splitlines())
    assert "/mnt/skills" not in code, f"{skill}: Step 0 code tests a /mnt/skills path"
    assert "SKILL.md" not in code and "Base directory" not in code, f"{skill}: Step 0 reads the skill text"


MS_GEN = PLUGIN / "skills" / "market-sizing" / "scripts" / "dispatch_prompt.py"
CP_GEN = PLUGIN / "skills" / "competitive-positioning" / "scripts" / "cp_dispatch_prompt.py"
FMR_GEN = PLUGIN / "skills" / "financial-model-review" / "scripts" / "fmr_dispatch_prompt.py"


# --- every sub-agent prompt that carries a bundled reference path names the fallback -------------


def _load(path: Path):  # type: ignore[no-untyped-def]
    import importlib.util

    spec = importlib.util.spec_from_file_location(f"gen_{path.stem}", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _prompts_with_reference_paths() -> list[tuple[str, str, str]]:
    found: list[tuple[str, str, str]] = []
    for gen in (MS_GEN, CP_GEN, FMR_GEN):
        mod = _load(gen)
        for name, value in vars(mod).items():
            if isinstance(value, str) and "<PLUGIN_ROOT_AGENT>" in value:
                found.append((gen.name, name, value))
    for skill in SKILLS:
        text = (PLUGIN / "skills" / skill / "SKILL.md").read_text(encoding="utf-8")
        for i, block in enumerate(text.split("```")[1::2]):
            body = block.split("\n", 1)[-1]
            if body.lstrip().startswith("CONTEXT:") and f"{TOKEN}/" in body and "/references/" in body:
                found.append((skill, f"fence {i}", body))
    return found


# Hard-coded, never derived from the scan below: a scan that went blind would otherwise pass on nothing.
# The four generator templates, and the three prompts a SKILL.md still writes out in a fence.
EXPECTED_REFERENCE_PROMPTS = {
    ("dispatch_prompt.py", "CONTEXT: CHECKLIST"),
    ("cp_dispatch_prompt.py", "CONTEXT: MOAT_SCORING"),
    ("cp_dispatch_prompt.py", "CONTEXT: CHECKLIST"),
    ("fmr_dispatch_prompt.py", "CONTEXT: CHECKLIST"),
    ("deck-review", "CONTEXT: SLIDE_REVIEWS"),
    ("deck-review", "CONTEXT: CHECKLIST"),
    ("financial-model-review", "CONTEXT: INPUTS_REVIEW"),
}

# What a generated prompt says instead, on a /sessions tree, where it names no path at all.
SESSION_POINTER = (
    "Each reference file below is in your plugin folder: open it at the full path your own instructions give "
    "for it (below, each is named by how that path ends)."
)


def test_every_prompt_with_a_reference_path_names_the_fallback() -> None:
    prompts = _prompts_with_reference_paths()
    assert {(src, body.split("\n", 1)[0]) for src, _, body in prompts} == EXPECTED_REFERENCE_PROMPTS
    for src, name, body in prompts:
        assert SUBAGENT_FALLBACK in body, f"{src} {name} hands over a reference path with no fallback"
        first_path = min(i for i in (body.find("<PLUGIN_ROOT_AGENT>"), body.find(TOKEN)) if i >= 0)
        assert body.index(SUBAGENT_FALLBACK) < first_path, f"{src} {name}: the fallback must precede the paths"


def _session_renderings(tmp_path: Path) -> dict[str, str]:
    analysis = tmp_path / "a"
    analysis.mkdir()
    for f in ("inputs.json", "methodology.json", "validation.json", "sizing.json"):
        (analysis / f).write_text("{}")
    ms, cp = _load(MS_GEN), _load(CP_GEN)
    out = {"ms checklist": ms.checklist("R", str(analysis), str(tmp_path / "h"), "/h", "/a", session_tree=True)}
    for context in ("moat_scoring", "checklist"):
        out[f"cp {context}"] = cp.render(
            context, run_id="R", handoff_agent="/h", analysis_dir_agent="/a", session_tree=True
        )
    fmr = _load(FMR_GEN)
    out["fmr checklist"] = fmr.checklist(
        run_id="R", handoff_agent="/h", review_dir_agent="/a", has_model_data=True, session_tree=True
    )
    return out


def test_on_a_session_tree_a_generated_prompt_points_instead_of_naming_a_path(tmp_path: Path) -> None:
    for name, body in _session_renderings(tmp_path).items():
        assert SESSION_POINTER in body, name
        assert body.index(SESSION_POINTER) < body.index("the file ending skills/"), name
        assert SUBAGENT_FALLBACK not in body, name
        assert not re.search(r"/skills/[a-z-]+/references/", body), f"{name} names an absolute reference path"


@pytest.mark.parametrize("skill", SKILLS)
def test_reference_read_directives_name_an_absolute_path(skill: str) -> None:
    """A bare relative path is refused by the Read tool, and the "Base directory" line it would be resolved
    against can name a folder that does not exist. Every instruction to read a bundled reference names the
    file under the plugin token, which Step 0's READ_ROOT= replaces when the text arrived unfilled."""
    text = (PLUGIN / "skills" / skill / "SKILL.md").read_text(encoding="utf-8")
    bare = re.findall(r"(?i)\bread (?:it )?`references/[^`]*`", text)
    assert not bare, f"{skill}: a Read directive names a relative reference path: {bare}"


def test_known_reference_read_directives_use_the_token() -> None:
    """Positive control for the scan above: the directives it once caught now carry the token."""
    for skill, ref in (
        ("deck-review", "deck-best-practices.md"),
        ("deck-review", "schemas/reconciliation.schema.json"),
        ("market-sizing", "tam-sam-som-methodology.md"),
        ("cap-table", "inputs-skeleton.md"),
    ):
        text = (PLUGIN / "skills" / skill / "SKILL.md").read_text(encoding="utf-8")
        assert f"`{TOKEN}/skills/{skill}/references/{ref}`" in text, (skill, ref)


def test_cap_table_lane_references_are_read_by_an_absolute_path() -> None:
    """The lane table is a Read directive ("read the matching lane reference"). A bare relative path
    is refused by the Read tool, so each row names the file under the plugin token."""
    text = (PLUGIN / "skills" / "cap-table" / "SKILL.md").read_text(encoding="utf-8")
    assert "](references/lanes/" not in text, "a lane row still links a relative path"
    for lane in ("lane-1-pdf-docx", "lane-2-carta-pulley", "lane-3-freeform", "lane-4-structured"):
        assert f"`{TOKEN}/skills/cap-table/references/lanes/{lane}.md`" in text, lane


# --- nothing tells the model to Read through a value the shell printed ---------------------------
#
# The shell's paths are not the file tools' paths on a local session: the plugin folder the shell sees is
# a VM path, refused by the Read tool. So Step 0 defines no reference folder for the shell at all, and no
# instruction reads a reference through a shell value or through a bare relative path (which Read refuses,
# and which the "Base directory" line would resolve against a folder that may not exist).

SEM = PLUGIN / "references" / "skill-execution-model.md"

_READ_VERB = re.compile(r"\b(?:[Rr]ead|[Cc]onsult|[Ss]ee|[Oo]pen|[Ee]valuate|[Ff]ollow)\b")
# A bundled file named relative to the skill folder. `references/*.md` (a glob naming the class) is not a file.
_BARE_REFERENCE = re.compile(r"(?<![\w/}.$-])references/[\w./-]+\.(?:md|json)\b")
# A file path built on a value Step 0 or a later block printed for the shell.
_SHELL_VALUE_PATH = re.compile(
    r"(?:\$\{?(?:PLUGIN_ROOT|SCRIPTS|SHARED_SCRIPTS|REFS|SHARED_REFS)\}?|<printed PLUGIN_ROOT>)/[\w./-]*\.(?:md|json)\b"
)


def _prose_sentences(text: str) -> list[str]:
    """Every sentence outside a ```bash fence, whitespace squashed. Dispatch templates are kept: a sub-agent
    reads them, so a read directive there counts."""
    prose = re.sub(r"^```bash\n.*?^```", "", text, flags=re.MULTILINE | re.DOTALL)
    return re.split(r"(?<=[.!?])\s+", " ".join(prose.split()))


def reads_through_a_shell_value(text: str) -> list[str]:
    found: list[str] = []
    for sentence in _prose_sentences(text):
        if not _READ_VERB.search(sentence):
            continue
        hits = _BARE_REFERENCE.findall(sentence) + _SHELL_VALUE_PATH.findall(sentence)
        found.extend(f"{h}  <-  {sentence[:160]}" for h in hits)
    return found


@pytest.mark.parametrize("skill", SKILLS)
def test_no_dead_reference_root_in_step0(skill: str) -> None:
    """Step 0 prints nothing named for reading references. A shell-side reference folder was rebuilt into
    Read and `cat` calls from the printed root and refused; the folder for Reads is the loaded token."""
    text = (PLUGIN / "skills" / skill / "SKILL.md").read_text(encoding="utf-8")
    assert not re.search(r"^\s*(?:SHARED_)?REFS=", text, re.MULTILINE), f"{skill}: Step 0 defines a reference root"
    assert not re.search(r"\$\{?(?:SHARED_)?REFS\b", text), f"{skill}: the text names a shell reference root"


def test_execution_model_names_no_shell_reference_root() -> None:
    text = SEM.read_text(encoding="utf-8")
    assert not re.search(r"\$\{?(?:SHARED_)?REFS\b", text), "skill-execution-model.md names a shell reference root"


@pytest.mark.parametrize("skill", SKILLS)
def test_no_instruction_reads_through_a_printed_shell_value(skill: str) -> None:
    """No sentence that tells the model to read, consult, see or open a bundled file names it by a bare
    relative `references/` path or by a path built on a shell value (`$PLUGIN_ROOT`, `$SCRIPTS`, ...).

    The limit: this reads the text, not what the model does with it. A correct directive whose path the
    model rebuilds from the printed root anyway passes here, and only a live run shows that."""
    text = (PLUGIN / "skills" / skill / "SKILL.md").read_text(encoding="utf-8")
    found = reads_through_a_shell_value(text)
    assert not found, f"{skill}: a read directive names a path the Read tool is refused:\n" + "\n".join(found)


AGENTS = sorted(p.stem for p in (PLUGIN / "agents").glob("*.md"))


@pytest.mark.parametrize("agent", AGENTS)
def test_no_agent_instruction_reads_through_a_printed_shell_value(agent: str) -> None:
    """The same rule for the agent bodies: a sub-agent's Read tool is refused a bare relative path too."""
    text = (PLUGIN / "agents" / f"{agent}.md").read_text(encoding="utf-8")
    found = reads_through_a_shell_value(text)
    assert not found, f"agents/{agent}.md: a read directive names a path the Read tool is refused:\n" + "\n".join(found)


def test_the_read_directive_scan_catches_both_forms() -> None:
    """Positive control: one sentence of each shape is caught, and the token form is not."""
    assert reads_through_a_shell_value("For the schema, consult `references/artifact-schemas.md` first.")
    assert reads_through_a_shell_value("Read `$PLUGIN_ROOT/skills/x/references/a.md` before writing.")
    assert reads_through_a_shell_value("See `<printed PLUGIN_ROOT>/references/benchmarks.md` for targets.")
    assert reads_through_a_shell_value(
        "For CHECKLIST: evaluate all 35 criteria from `references/checklist-criteria.md`."
    )
    assert not reads_through_a_shell_value(f"Consult `{TOKEN}/skills/x/references/artifact-schemas.md` first.")
    assert not reads_through_a_shell_value("Bundled `references/*.md` are the one exception: read them by token.")


@pytest.mark.parametrize("skill", SKILLS)
def test_no_condition_is_keyed_on_the_token_showing(skill: str) -> None:
    """The loader fills every `${CLAUDE_PLUGIN_ROOT}`, including one inside "if this still shows ...", so
    such a condition reads as "if this still shows /real/path" and is always true. Conditions key on what
    Step 0 printed instead."""
    text = (PLUGIN / "skills" / skill / "SKILL.md").read_text(encoding="utf-8")
    bad = [
        ln for ln in text.splitlines() if re.search(r"(?i)\bif\b[^.\n]*\bshows?\b[^.\n]*\$\{CLAUDE_PLUGIN_ROOT\}", ln)
    ]
    assert not bad, f"{skill}: a condition is keyed on the token itself: {bad}"


# --- a deck rendered or copied for the Read tool lands where the Read tool reaches ---------------
#
# On a local session the Read tool reaches the outputs folder by its own (host) name and is refused both
# `$STAGING_DIR` (a /tmp path in the VM) and the uploads mount's shell path. So a PowerPoint deck is
# converted into this run's hand-off folder and the block prints the Read tool's path to it; a deck the
# Read tool cannot reach in place is copied there. The hand-off folder is working data, never delivered.

FAKE_SOFFICE = """#!/bin/sh
out=""; prev=""; for a in "$@"; do [ "$prev" = "--outdir" ] && out="$a"; prev="$a"; last="$a"; done
b="$(basename "$last")"; printf '%%PDF-1.4 fake' > "$out/${b%.*}.pdf"
"""


def _fence_with(skill: str, marker: str) -> str:
    text = (PLUGIN / "skills" / skill / "SKILL.md").read_text(encoding="utf-8")
    blocks: list[str] = [b for b in re.findall(r"^```bash\n(.*?)^```", text, re.MULTILINE | re.DOTALL) if marker in b]
    assert len(blocks) == 1, f"{skill}: expected one block containing {marker!r}, found {len(blocks)}"
    return blocks[0]


def _run_deck_block(skill: str, tmp_path: Path, deck_name: str, *, agent_differs: bool) -> tuple[str, Path, Path]:
    """Run the skill's conversion block with a stand-in converter. Returns (printed, hand-off, staging)."""
    marker = "DECK_READ=" if skill == "deck-review" else "--convert-to pdf"
    block = _fence_with(skill, marker)
    handoff, staging, uploads, bin_dir = (tmp_path / d for d in ("handoff", "staging", "uploads", "bin"))
    for d in (handoff, staging, uploads, bin_dir):
        d.mkdir()
    (uploads / deck_name).write_bytes(b"deck")
    soffice = bin_dir / "soffice"
    soffice.write_text(FAKE_SOFFICE)
    soffice.chmod(0o755)
    agent = "/Users/me/Library/outputs/artifacts/deck-review-acme/handoff/r1" if agent_differs else str(handoff)
    fills = {
        "<deck path>": str(uploads / deck_name),
        "<REVIEW_DIR>/handoff/<RUN_ID>": str(handoff),
        "<printed HANDOFF_DIR>": str(handoff),
        "<printed HANDOFF_AGENT>": agent,
    }
    for placeholder, value in fills.items():
        block = block.replace(placeholder, value)
    assert "<" not in re.sub(r"<<'?\w+'?|2>&1|</?\w+>", "", block.split("osascript")[0]), "an unfilled placeholder"
    script = tmp_path / "convert.sh"
    script.write_text(block + "\n", encoding="utf-8")
    proc = subprocess.run(
        ["/usr/bin/env", "-i", f"PATH={bin_dir}:/usr/bin:/bin", f"STAGING_DIR={staging}", "sh", str(script)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.strip().splitlines()[-1], handoff, staging


@pytest.mark.parametrize("skill", ["deck-review", "market-sizing"])
@pytest.mark.parametrize("agent_differs", [True, False], ids=["local-session", "shared-filesystem"])
def test_staged_pdf_is_read_from_a_readable_folder(skill: str, agent_differs: bool, tmp_path: Path) -> None:
    """A converted PowerPoint deck is written to the hand-off folder (never $STAGING_DIR), and what the
    block prints for the Read tool is that file under the hand-off folder's Read-tool name."""
    printed, handoff, staging = _run_deck_block(skill, tmp_path, "Acme Deck.pptx", agent_differs=agent_differs)
    assert (handoff / "Acme Deck.pdf").is_file(), f"{skill}: the PDF did not land in the hand-off folder"
    assert not list(staging.glob("*.pdf")), f"{skill}: a PDF landed in $STAGING_DIR, which Read cannot reach"
    agent = "/Users/me/Library/outputs/artifacts/deck-review-acme/handoff/r1" if agent_differs else str(handoff)
    assert printed == f"{agent}/Acme Deck.pdf", f"{skill}: printed {printed!r}, not the Read tool's path"
    text = (PLUGIN / "skills" / skill / "SKILL.md").read_text(encoding="utf-8")
    assert '-env:UserInstallation="file://$STAGING_DIR/.lo"' in text, f"{skill}: the profile left $STAGING_DIR"
    assert not re.search(r"(?i)\bread\b[^.\n]*from `\$STAGING_DIR`", text), f"{skill}: a Read from $STAGING_DIR"


def test_a_pdf_deck_the_read_tool_cannot_reach_is_copied_to_the_handoff_folder(tmp_path: Path) -> None:
    printed, handoff, _ = _run_deck_block("deck-review", tmp_path, "acme.pdf", agent_differs=True)
    assert (handoff / "acme.pdf").is_file()
    assert printed == "/Users/me/Library/outputs/artifacts/deck-review-acme/handoff/r1/acme.pdf"


def test_a_pdf_deck_on_a_shared_filesystem_is_read_in_place(tmp_path: Path) -> None:
    """CLI and cloud: the Read tool takes the shell's path, so nothing is copied."""
    printed, handoff, _ = _run_deck_block("deck-review", tmp_path, "acme.pdf", agent_differs=False)
    assert not (handoff / "acme.pdf").exists()
    assert printed == str(tmp_path / "uploads" / "acme.pdf")


def test_the_read_rule_names_the_plugin_folder_not_every_printed_path() -> None:
    """The shell prints paths that ARE for Reads (the hand-off folder's file-tool name, a deck's PDF), so the
    rule names what it forbids: the shell's path to the plugin folder."""
    for path in [*(PLUGIN / "skills").glob("*/SKILL.md"), SEM]:
        assert "path the shell printed" not in path.read_text(encoding="utf-8"), path.parent.name
