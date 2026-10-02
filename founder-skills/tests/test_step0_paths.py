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
    "If a reference path below is refused, read the same file under the plugin folder your own instructions name."
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


def _plugin_copy(root: Path, *, name: str = "founder-skills", version: str = VERSION) -> Path:
    (root / ".claude-plugin").mkdir(parents=True)
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
    fake = _fake(tmp_path)
    _plugin_copy(fake / "aaa-old-founder-skills", version="0.0.1")
    root = _synced(fake)
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
    except Exception: n = ""
    if n == "founder-skills": print(c)'; }""",
    "  CANDIDATES=\"$(find /sessions -type d -path '*/skills/{skill}/scripts' 2>/dev/null | ours)\"\n"
    '  [ -n "$CANDIDATES" ] || '
    "CANDIDATES=\"$(find /root/.claude/plugins -type d -path '*/skills/{skill}/scripts' 2>/dev/null | ours)\"\n"
    '  [ -n "$CANDIDATES" ] || CANDIDATES="$(find / -type d -path \'*/skills/{skill}/scripts\' 2>/dev/null | ours)"\n',
    """[ -f "$SHARED_SCRIPTS/check_handoff.py" ] && case "$TEXT_ROOT_RAW" in
  *'$'*|'') echo "PATH_STATE=literal"; echo "READ_ROOT=$PLUGIN_ROOT" ;;
  /sessions/*) echo "PATH_STATE=local" ;;
  *) if [ -d "$TEXT_ROOT_RAW" ]; then echo "PATH_STATE=substituted"; else echo "PATH_STATE=local"; fi ;;
esac
""",
)

STEP0_PROSE = (
    "**Plugin paths.** If this run's Step 0 printed `READ_ROOT=`, this skill's text arrived with its "
    "plugin folder unfilled: write that printed value wherever this skill shows `${CLAUDE_PLUGIN_ROOT}` "
    "in a Read, a sub-agent prompt or a `--plugin-root-agent` argument, including where a later step "
    "says to leave that path literal. Otherwise use those paths exactly as shown. Step 0 finds the "
    "folder by searching the filesystem only; never recover it by reading a SKILL.md or the "
    '"Base directory" line. **Say nothing about this step to the founder, including the version you '
    "read and the paths it printed.**"
)


@pytest.mark.parametrize("skill", SKILLS)
def test_step0_bootstrap_lines_are_fleet_identical(skill: str) -> None:
    fence = _step0_fence(skill)
    for line in STEP0_LINES:
        expected = line.replace("{skill}", skill)
        assert expected in fence, f"{skill}: Step 0 lost or changed:\n{expected}"
    section = _step0_section(skill)
    assert STEP0_PROSE in section, f"{skill}: Step 0 lost the plugin-paths paragraph"
    assert "self-heal branch is normal" not in section, f"{skill}: the stale self-heal note is back"
    assert "Skip it if that path still begins with `$`." in section, f"{skill}: best-effort Read lacks its skip"


@pytest.mark.parametrize("skill", SKILLS)
def test_step0_never_keys_on_the_flat_skill_mount_or_reads_a_skill_file(skill: str) -> None:
    """The fallback is a filesystem search. `/mnt/skills` does not identify the chat surface."""
    fence = _step0_fence(skill)
    code = "\n".join(ln.split("#", 1)[0] for ln in fence.splitlines())
    assert "/mnt/skills" not in code, f"{skill}: Step 0 code tests a /mnt/skills path"
    assert "SKILL.md" not in code and "Base directory" not in code, f"{skill}: Step 0 reads the skill text"


# --- generators refuse a root a sub-agent cannot use --------------------------------------------

MS_GEN = PLUGIN / "skills" / "market-sizing" / "scripts" / "dispatch_prompt.py"
CP_GEN = PLUGIN / "skills" / "competitive-positioning" / "scripts" / "cp_dispatch_prompt.py"


def _ms_checklist(tmp_path: Path, root: str) -> subprocess.CompletedProcess[str]:
    analysis = tmp_path / "analysis"
    analysis.mkdir(exist_ok=True)
    for f in ("inputs.json", "methodology.json", "validation.json", "sizing.json"):
        (analysis / f).write_text("{}")
    args = ["checklist", "--run-id", "R", "--analysis-dir", str(analysis), "--handoff-dir", str(tmp_path / "h")]
    args += ["--handoff-agent", "/agent/h", "--plugin-root-agent", root]
    return subprocess.run([sys.executable, str(MS_GEN), *args], capture_output=True, text=True)


def _cp_moat(tmp_path: Path, root: str) -> subprocess.CompletedProcess[str]:
    args = ["moat_scoring", "--run-id", "R", "--handoff-agent", "/agent/h", "--analysis-dir-agent", "/agent/a"]
    return subprocess.run(
        [sys.executable, str(CP_GEN), *args, "--plugin-root-agent", root], capture_output=True, text=True
    )


def _bad_roots(tmp_path: Path) -> list[str]:
    other = tmp_path / "other"
    (other / ".claude-plugin").mkdir(parents=True)
    (other / ".claude-plugin" / "plugin.json").write_text('{"name": "other-plugin"}')
    return ["", TOKEN, "rel/path", str(other)]


@pytest.mark.parametrize("gen", [_ms_checklist, _cp_moat], ids=["market-sizing", "competitive-positioning"])
def test_generators_refuse_a_root_a_sub_agent_cannot_read(gen: Callable, tmp_path: Path) -> None:
    for root in _bad_roots(tmp_path):
        proc = gen(tmp_path, root)
        assert proc.returncode == 2 and proc.stdout == "", f"{root!r} accepted:\n{proc.stdout}{proc.stderr}"
        assert "--plugin-root-agent" in proc.stderr and len(proc.stderr.strip().splitlines()) == 1, proc.stderr
    ours = _plugin_copy(tmp_path / "ours")
    for root in ("/p", str(ours)):
        proc = gen(tmp_path, root)
        assert proc.returncode == 0, f"{root!r} refused:\n{proc.stderr}"


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
    for gen in (MS_GEN, CP_GEN):
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


def test_every_prompt_with_a_reference_path_names_the_fallback() -> None:
    prompts = _prompts_with_reference_paths()
    names = {(src, name) for src, name, _ in prompts}
    assert len(prompts) >= 6, f"the prompt scan went blind: {sorted(names)}"
    for src, name, body in prompts:
        assert SUBAGENT_FALLBACK in body, f"{src} {name} hands over a reference path with no fallback"
        first_path = min(i for i in (body.find("<PLUGIN_ROOT_AGENT>"), body.find(TOKEN)) if i >= 0)
        assert body.index(SUBAGENT_FALLBACK) < first_path, f"{src} {name}: the fallback must precede the paths"


def test_cap_table_lane_references_are_read_by_an_absolute_path() -> None:
    """The lane table is a Read directive ("read the matching lane reference"). A bare relative path
    is refused by the Read tool, so each row names the file under the plugin token."""
    text = (PLUGIN / "skills" / "cap-table" / "SKILL.md").read_text(encoding="utf-8")
    assert "](references/lanes/" not in text, "a lane row still links a relative path"
    for lane in ("lane-1-pdf-docx", "lane-2-carta-pulley", "lane-3-freeform", "lane-4-structured"):
        assert f"`{TOKEN}/skills/cap-table/references/lanes/{lane}.md`" in text, lane
