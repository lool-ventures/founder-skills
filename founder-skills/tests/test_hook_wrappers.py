"""The plugin's hook wrappers fail open when their Python body is missing.

A PreToolUse hook that exits 2 BLOCKS the tool call, and `exec python3 <missing file>` exits 2. So a
wrapper whose body is absent (a partial install, a stale cache) would hold every dispatch, which is the
opposite of the posture the wrappers state: the hooks enforce, the skills never depend on them. Each
wrapper is run on its own, with no Python body beside it, under `sh` and under `dash` (the Cowork VM's
shell), and must exit 0 with one stderr line and nothing on stdout (hook stdout is parsed).
"""

from __future__ import annotations

import json
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
