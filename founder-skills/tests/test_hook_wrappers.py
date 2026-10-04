"""The plugin's hook wrappers fail open when their Python body is missing.

A PreToolUse hook that exits 2 BLOCKS the tool call, and `exec python3 <missing file>` exits 2. So a
wrapper whose body is absent (a partial install, a stale cache) would hold every dispatch, which is the
opposite of the posture the wrappers state: the hooks enforce, the skills never depend on them. Each
wrapper is run on its own, with no Python body beside it, under `sh` and under `dash` (the Cowork VM's
shell), and must exit 0 with one stderr line and nothing on stdout (hook stdout is parsed).
"""

from __future__ import annotations

import ast
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parents[1]
SCRIPTS = PLUGIN / "scripts"


def _hook_wrappers() -> list[str]:
    """Every hook command in plugin.json that is a shell wrapper exec'ing a Python body."""
    manifest = json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    names: set[str] = set()
    for entries in manifest["hooks"].values():
        for entry in entries:
            for hook in entry["hooks"]:
                name = hook["command"].rsplit("/", 1)[-1]
                if name.endswith(".sh") and "exec python3" in (SCRIPTS / name).read_text(encoding="utf-8"):
                    names.add(name)
    return sorted(names)


WRAPPERS = _hook_wrappers()
SHELLS = ["sh", "dash"]


def test_the_wrapper_list_is_not_empty() -> None:
    assert {"pretooluse-dispatch.sh", "stop-handover-check.sh"} <= set(WRAPPERS), WRAPPERS


@pytest.mark.parametrize("shell", SHELLS)
@pytest.mark.parametrize("wrapper", WRAPPERS)
def test_a_wrapper_with_no_body_fails_open(wrapper: str, shell: str, tmp_path: Path) -> None:
    exe = shutil.which(shell)
    if exe is None:
        pytest.skip(f"{shell} not available")
    if shutil.which("python3") is None:
        pytest.skip("python3 not available, so the wrapper exits before reaching its body")
    copy = tmp_path / wrapper
    shutil.copy(SCRIPTS / wrapper, copy)
    assert not any(p.suffix == ".py" for p in tmp_path.iterdir()), "the body must be absent for this test"
    r = subprocess.run([exe, str(copy)], input="{}", capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, (
        f"{wrapper} under {shell} exited {r.returncode} with its body missing; a PreToolUse hook that "
        f"exits 2 blocks the tool call. stderr: {r.stderr!r}"
    )
    assert r.stdout == "", f"hook stdout is parsed; a missing body must print nothing there: {r.stdout!r}"
    assert len(r.stderr.strip().splitlines()) == 1, f"expected one stderr line, got {r.stderr!r}"


# --- every hook ships with the Python it runs ---------------------------------------------------------
# Failing open covers a body missing from an install; it does not make a missing body acceptable in the
# plugin we ship. The wrappers name their body by a path relative to themselves, and the bodies load their
# helpers the same way, so nothing imports them and a body or helper left untracked would pass every test
# that imports it from the working tree.

_BODY = re.compile(r'f="\$\(dirname "\$0"\)/([A-Za-z0-9_]+\.py)"')
_SIBLING = re.compile(r'os\.path\.join\(os\.path\.dirname\(os\.path\.abspath\(__file__\)\),\s*"([A-Za-z0-9_]+\.py)"\)')
_SIBLING_BY_NAME = re.compile(
    r'os\.path\.join\(os\.path\.dirname\(os\.path\.abspath\(__file__\)\),\s*f"\{name\}\.py"\)'
)


def _names_assigned(source: str, var: str) -> list[str]:
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == var for t in node.targets):
            value = ast.literal_eval(node.value)
            return [str(v) for v in value]
    return []


def _hook_files(plugin: Path) -> list[str]:
    """Every file a plugin.json hook runs: the command, its Python body, and the helpers the body loads
    by path (transitively). Plugin-relative paths."""
    manifest = json.loads((plugin / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    todo: list[str] = []
    for entries in manifest["hooks"].values():
        for entry in entries:
            for hook in entry["hooks"]:
                todo.append(hook["command"].replace("${CLAUDE_PLUGIN_ROOT}/", ""))
    seen: list[str] = []
    while todo:
        rel = todo.pop()
        if rel in seen:
            continue
        seen.append(rel)
        path = plugin / rel
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        folder = str(Path(rel).parent)
        found = _BODY.findall(text) + _SIBLING.findall(text)
        if _SIBLING_BY_NAME.search(text):
            found += [f"{n}.py" for n in _names_assigned(text, "CHECKS")]
        todo.extend(f"{folder}/{name}" for name in found)
    return sorted(seen)


def _shipped(plugin: Path) -> set[str]:
    out = subprocess.run(["git", "ls-files", "--", "."], cwd=plugin, capture_output=True, text=True, check=True).stdout
    return set(out.split())


def test_every_hook_and_the_python_it_runs_ships_in_the_plugin() -> None:
    files = _hook_files(PLUGIN)
    # Non-vacuity: the three wrappers, both bodies, and the helpers each body loads.
    for expected in (
        "scripts/stop-handover-check.sh",
        "scripts/stop_handover_check.py",
        "scripts/_delivery_check.py",
        "scripts/_handover_check.py",
        "scripts/pretooluse-dispatch.sh",
        "scripts/pretooluse_dispatch.py",
        "scripts/dispatch_prompt_check.py",
        "scripts/dispatch_type_check.py",
        "scripts/two_figures_check.py",
        "scripts/session-setup.sh",
    ):
        assert expected in files, (expected, files)
    missing = [f for f in files if f not in _shipped(PLUGIN)]
    assert not missing, f"hook files not tracked in the plugin tree: {missing}"


def test_a_hook_body_missing_from_the_tree_is_reported(tmp_path: Path) -> None:
    """Seeded: a manifest whose wrapper names a body that is not there."""
    (tmp_path / ".claude-plugin").mkdir()
    (tmp_path / "scripts").mkdir()
    (tmp_path / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"hooks": {"Stop": [{"hooks": [{"command": "${CLAUDE_PLUGIN_ROOT}/scripts/w.sh"}]}]}}),
        encoding="utf-8",
    )
    (tmp_path / "scripts" / "w.sh").write_text('f="$(dirname "$0")/body.py"\nexec python3 "$f"\n', encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    files = _hook_files(tmp_path)
    assert files == ["scripts/body.py", "scripts/w.sh"]
    assert [f for f in files if f not in _shipped(tmp_path)] == ["scripts/body.py"]
