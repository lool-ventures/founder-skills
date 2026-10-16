"""The SessionStart hook's compaction note: after a compaction, a run in progress is told to re-read its SKILL.md.

`session-setup.sh` tests the payload's `source` in the shell and launches `compaction_reread.py` only on a
compaction; the module speaks only when the session started a founder-skills skill on the main thread and the
latest run status the transcript names is `running` or `waiting` for that skill. Everything else is silence,
and every path exits 0.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gate_run_helpers as h  # noqa: E402

SCRIPTS = h.SHARED
WRAPPER = SCRIPTS / "session-setup.sh"
SHELLS = ["sh", "dash"]


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("compaction_reread_under_test", SCRIPTS / "compaction_reread.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


cr = _load()


def _skill_call(skill: str = "founder-skills:market-sizing", **extra: Any) -> dict[str, Any]:
    use = {"type": "tool_use", "id": "toolu_s", "name": "Skill", "input": {"skill": skill}}
    return {"type": "assistant", "message": {"role": "assistant", "content": [use]}, **extra}


def _user(text: str, **extra: Any) -> dict[str, Any]:
    return {"type": "user", "message": {"role": "user", "content": text}, **extra}


def _result(printed: Any, **extra: Any) -> dict[str, Any]:
    text = printed if isinstance(printed, str) else json.dumps(printed)
    block = {"type": "tool_result", "tool_use_id": "s1", "content": text}
    return {"type": "user", "message": {"role": "user", "content": [block]}, **extra}


def _start_result(root: Path, run_id: str) -> dict[str, Any]:
    return _result({"run_id": run_id, "status": "running", "status_path": str(h.status_path(root, run_id))})


def _transcript(tmp: Path, rows: list[dict[str, Any]]) -> str:
    path = tmp / "t.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return str(path)


def _payload(transcript: str, source: str = "compact") -> dict[str, Any]:
    return {"session_id": "s", "transcript_path": transcript, "hook_event_name": "SessionStart", "source": source}


def _set_status(root: Path, run_id: str, **fields: Any) -> None:
    path = h.status_path(root, run_id)
    status = json.loads(path.read_text(encoding="utf-8"))
    status.update(fields)
    path.write_text(json.dumps(status), encoding="utf-8")


def _run(tmp: Path) -> tuple[Path, str, list[dict[str, Any]]]:
    root, run_id, _run_dir = h.start_bound(tmp, "market-sizing")
    return root, run_id, [_user("Size this market."), _skill_call(), _start_result(root, run_id)]


def _text(out: dict[str, Any] | None) -> str:
    assert out is not None
    spec = out["hookSpecificOutput"]
    assert spec["hookEventName"] == "SessionStart"
    text: str = spec["additionalContext"]
    return text


# --- the module --------------------------------------------------------------------------------------


def test_a_compaction_during_a_running_run_names_the_skill_its_file_and_the_shell_paths(tmp_path: Path) -> None:
    root, run_id, rows = _run(tmp_path)
    status = h.status(root, run_id)
    assert status["status"] == "running"
    text = _text(cr.decide(_payload(_transcript(tmp_path, rows))))
    assert text.startswith(f"If you are the main thread running the founder-skills market-sizing run {run_id}")
    assert "(status running)" in text
    assert text.endswith("If you are a sub-agent, ignore this.")
    assert "/skills/market-sizing/SKILL.md`" in text
    assert "### Step" in text and "READ_ROOT=" in text
    assert "it does not re-run it" in text
    # The shell's own paths, as `start` and `bind` recorded them.
    assert status["scripts_dir_shell"] and status["shared_scripts_dir_shell"]
    assert f"`{status['scripts_dir_shell']}`" in text
    assert f"`{status['shared_scripts_dir_shell']}`" in text


def test_the_read_path_is_under_the_hooks_own_plugin_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _root, _rid, rows = _run(tmp_path)
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", "/plugins/founder-skills/9.9.9")
    text = _text(cr.decide(_payload(_transcript(tmp_path, rows))))
    assert "`/plugins/founder-skills/9.9.9/skills/market-sizing/SKILL.md`" in text
    monkeypatch.delenv("CLAUDE_PLUGIN_ROOT")
    text = _text(cr.decide(_payload(_transcript(tmp_path, rows))))
    assert f"`{SCRIPTS.parent / 'skills' / 'market-sizing' / 'SKILL.md'}`" in text


def test_a_waiting_run_is_named_too(tmp_path: Path) -> None:
    root, run_id, rows = _run(tmp_path)
    _set_status(root, run_id, status="waiting")
    assert "(status waiting)" in _text(cr.decide(_payload(_transcript(tmp_path, rows))))


@pytest.mark.parametrize("state", ["complete", "refused"])
def test_a_finished_run_is_not_told_it_is_open(tmp_path: Path, state: str) -> None:
    root, run_id, rows = _run(tmp_path)
    _set_status(root, run_id, status=state)
    assert cr.decide(_payload(_transcript(tmp_path, rows))) is None


def test_a_missing_or_unreadable_status_is_silent(tmp_path: Path) -> None:
    root, run_id, rows = _run(tmp_path)
    path = h.status_path(root, run_id)
    path.write_text("{not json", encoding="utf-8")
    out = subprocess.run(
        [sys.executable, str(SCRIPTS / "compaction_reread.py")],
        input=json.dumps(_payload(_transcript(tmp_path, rows))),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert out.returncode == 0 and out.stdout == "" and len(out.stderr.strip().splitlines()) == 1
    path.unlink()
    assert cr.decide(_payload(_transcript(tmp_path, rows))) is None
    # No `start` result at all: nothing names a run.
    assert cr.decide(_payload(_transcript(tmp_path, rows[:2]))) is None


@pytest.mark.parametrize("source", ["startup", "resume", "clear", "fork"])
def test_other_session_starts_are_silent(tmp_path: Path, source: str) -> None:
    _root, _rid, rows = _run(tmp_path)
    assert cr.decide(_payload(_transcript(tmp_path, rows), source)) is None


def test_no_transcript_or_an_unreadable_one_is_silent(tmp_path: Path) -> None:
    assert cr.decide(_payload(str(tmp_path / "absent.jsonl"))) is None
    assert cr.decide({"hook_event_name": "SessionStart", "source": "compact"}) is None


def test_another_plugins_skill_is_not_ours(tmp_path: Path) -> None:
    root, run_id, _rows = _run(tmp_path)
    rows = [_user("Go."), _skill_call("other:market-sizing"), _start_result(root, run_id)]
    assert cr.decide(_payload(_transcript(tmp_path, rows))) is None


def test_a_skill_name_a_tool_returned_does_not_count_and_a_slash_command_does(tmp_path: Path) -> None:
    root, run_id, _rows = _run(tmp_path)
    returned = _result("<command-name>/founder-skills:market-sizing</command-name>")
    rows = [_user("Read the old run."), returned, _start_result(root, run_id)]
    assert cr.decide(_payload(_transcript(tmp_path, rows))) is None
    typed = _user("<command-name>/founder-skills:market-sizing</command-name>")
    assert cr.decide(_payload(_transcript(tmp_path, [typed, _start_result(root, run_id)]))) is not None


def test_a_sub_agents_skill_call_does_not_count(tmp_path: Path) -> None:
    root, run_id, _rows = _run(tmp_path)
    rows = [_user("Go."), _skill_call(isSidechain=True), _start_result(root, run_id)]
    assert cr.decide(_payload(_transcript(tmp_path, rows))) is None


def test_the_open_run_must_be_one_of_the_skills_this_session_started(tmp_path: Path) -> None:
    root, run_id, _rows = _run(tmp_path)
    rows = [_user("Go."), _skill_call("founder-skills:deck-review"), _start_result(root, run_id)]
    assert cr.decide(_payload(_transcript(tmp_path, rows))) is None


def test_the_latest_start_result_decides(tmp_path: Path) -> None:
    root, first, rows = _run(tmp_path)
    _set_status(root, first, status="complete")
    second_root, second, _r = h.start_bound(tmp_path / "b", "market-sizing")
    later = [*rows, _user("Another one."), _skill_call(), _start_result(second_root, second)]
    assert f"run {second} " in _text(cr.decide(_payload(_transcript(tmp_path, later))))
    _set_status(second_root, second, status="complete")
    assert cr.decide(_payload(_transcript(tmp_path, later))) is None


def test_a_status_with_no_shell_paths_leaves_that_clause_out(tmp_path: Path) -> None:
    root, run_id, rows = _run(tmp_path)
    _set_status(root, run_id, scripts_dir_shell=None, shared_scripts_dir_shell=None)
    text = _text(cr.decide(_payload(_transcript(tmp_path, rows))))
    assert "In the shell" not in text
    _set_status(root, run_id, shared_scripts_dir_shell="/vm/plugin/scripts")
    assert "In the shell, the shared scripts are in `/vm/plugin/scripts`." in _text(
        cr.decide(_payload(_transcript(tmp_path, rows)))
    )


# --- the wrapper -------------------------------------------------------------------------------------


def _shell(name: str) -> str:
    exe = shutil.which(name)
    if exe is None:
        pytest.skip(f"{name} not available")
    return exe


def _wrap(
    shell: str, wrapper: Path, payload: dict[str, Any] | str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    base = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE_ENV_FILE", "CLAUDE_PLUGIN_ROOT"))}
    base.update(env or {})
    text = payload if isinstance(payload, str) else json.dumps(payload, separators=(",", ":"))
    return subprocess.run([shell, str(wrapper)], input=text, capture_output=True, text=True, env=base, timeout=30)


@pytest.mark.parametrize("shell", SHELLS)
def test_through_the_wrapper_a_compaction_prints_valid_session_start_json(tmp_path: Path, shell: str) -> None:
    exe = _shell(shell)
    _root, run_id, rows = _run(tmp_path)
    r = _wrap(exe, WRAPPER, _payload(_transcript(tmp_path, rows)))
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert f"run {run_id} " in _text(out)
    # The runtime writes compact JSON; a startup payload prints nothing.
    r = _wrap(exe, WRAPPER, _payload(_transcript(tmp_path, rows), "startup"))
    assert r.returncode == 0 and r.stdout == ""


def _stub_beside(tmp: Path) -> tuple[Path, Path]:
    """A copy of the wrapper whose body only records that it was launched."""
    folder = tmp / "w"
    folder.mkdir()
    wrapper = folder / "session-setup.sh"
    shutil.copy(WRAPPER, wrapper)
    flag = tmp / "launched"
    (folder / "compaction_reread.py").write_text(
        f"import pathlib\npathlib.Path({str(flag)!r}).write_text('x')\n", encoding="utf-8"
    )
    return wrapper, flag


@pytest.mark.parametrize("shell", SHELLS)
@pytest.mark.parametrize("source", ["startup", "resume", "clear", "fork"])
def test_the_wrapper_launches_no_interpreter_for_another_session_start(tmp_path: Path, shell: str, source: str) -> None:
    exe = _shell(shell)
    wrapper, flag = _stub_beside(tmp_path)
    r = _wrap(exe, wrapper, {"hook_event_name": "SessionStart", "source": source})
    assert r.returncode == 0 and r.stdout == "" and r.stderr == ""
    assert not flag.exists()
    r = _wrap(exe, wrapper, {"hook_event_name": "SessionStart", "source": "compact"})
    assert r.returncode == 0
    assert flag.exists(), "the compact payload must reach the body (the case match is what gates it)"


@pytest.mark.parametrize("shell", SHELLS)
def test_the_wrapper_fails_open_with_its_body_missing_and_still_writes_the_env_file(tmp_path: Path, shell: str) -> None:
    """`test_hook_wrappers.py`'s fail-open test admits only `exec python3` wrappers; this one launches its body
    only on a compaction, so it is checked here, on the payload that reaches the body."""
    exe = _shell(shell)
    if shutil.which("python3") is None:
        pytest.skip("python3 not available, so the wrapper exits before reaching its body")
    folder = tmp_path / "w"
    folder.mkdir()
    wrapper = folder / "session-setup.sh"
    shutil.copy(WRAPPER, wrapper)
    assert not any(p.suffix == ".py" for p in folder.iterdir())
    env_file = tmp_path / "env"
    env = {"CLAUDE_PLUGIN_ROOT": "/plugins/founder-skills", "CLAUDE_ENV_FILE": str(env_file)}
    r = _wrap(exe, wrapper, {"hook_event_name": "SessionStart", "source": "compact"}, env)
    assert r.returncode == 0, r.stderr
    assert r.stdout == ""
    assert len(r.stderr.strip().splitlines()) == 1, r.stderr
    assert env_file.read_text(encoding="utf-8") == "export CLAUDE_PLUGIN_ROOT='/plugins/founder-skills'\n"
    # A body that crashes fails open as well.
    (folder / "compaction_reread.py").write_text("raise SystemExit(3)\n", encoding="utf-8")
    r = _wrap(exe, wrapper, {"hook_event_name": "SessionStart", "source": "compact"}, env)
    assert r.returncode == 0 and r.stdout == ""


@pytest.mark.parametrize("shell", SHELLS)
def test_the_env_file_reads_back_the_same_root_when_sourced(tmp_path: Path, shell: str) -> None:
    exe = _shell(shell)
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash not available")
    env_file = tmp_path / "env"
    env_file.write_text("export OTHER=1\nexport CLAUDE_PLUGIN_ROOT=/old\n", encoding="utf-8")
    root = "/tmp/it's a $path with `quotes` and \\ back"
    r = _wrap(exe, WRAPPER, "{}", {"CLAUDE_PLUGIN_ROOT": root, "CLAUDE_ENV_FILE": str(env_file)})
    assert r.returncode == 0 and r.stdout == "" and r.stderr == ""
    lines = env_file.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "export OTHER=1" and len(lines) == 2
    back = subprocess.run(
        [bash, "-c", f'. "{env_file}"; printf %s "$CLAUDE_PLUGIN_ROOT"'], capture_output=True, text=True, timeout=30
    )
    assert back.stdout == root
