#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""SessionStart hook body, `source: "compact"` only: tell a run in progress to re-read its SKILL.md.

WHY. After a compaction the runtime re-attaches a skill's instructions cut to a fixed window, and for the
analysis skills that window ends inside Step 0: the steps the run is on are gone, while what survives (Step
0's flags, a quick check's commands) reads like a whole manual. A run that carries on from that copy guesses
flags and skips steps. This adds one note after the cut copy, last in context, naming the file to read.

WHEN. Only when the session started a founder-skills analysis skill on the main thread (a `Skill` call or a
slash command; a skill name a tool returned does not count) AND the latest run status the transcript names is
`running` or `waiting`, for one of those skills. Otherwise it prints nothing: a session whose run finished is
not told a run is open.

WHO. The runtime fires this for a sub-agent's compaction too, with the same payload, so the note says whom it
is for and tells a sub-agent to ignore it. Whatever goes wrong, it prints nothing on stdout and exits 0.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import sys
from typing import Any

OPEN = ("running", "waiting")
_STATUS_PATH = re.compile(r'"status_path"\s*:\s*"([^"]+)"')


def _log(msg: str) -> None:
    print(f"compaction_reread: {msg}", file=sys.stderr)


def _type_check() -> Any:
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dispatch_type_check.py")
    spec = importlib.util.spec_from_file_location("dispatch_type_check", path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _plugin_root() -> str:
    root = os.environ.get("CLAUDE_PLUGIN_ROOT", "").strip()
    return root or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def latest_status_path(rows: list[dict[str, Any]], strings: Any) -> str | None:
    """The `status_path` the latest main-thread `run_status.py start` result printed, or None."""
    found = None
    for row in rows:
        if row.get("type") != "user" or row.get("isSidechain"):
            continue
        for piece in strings((row.get("message") or {}).get("content")):
            for m in _STATUS_PATH.finditer(piece):
                found = m.group(1)
    return found


def note(skill: str, run_id: str, state: str, status: dict[str, Any]) -> str:
    skill_md = os.path.join(_plugin_root(), "skills", skill, "SKILL.md")
    parts = [
        f"If you are the main thread running the founder-skills {skill} run {run_id} (status {state}), its "
        "instructions were re-attached cut inside Step 0 by this compaction. Before your next command, Read "
        f"`{skill_md}` from the `### Step` you are on (if Step 0 printed `READ_ROOT=`, use that value as the "
        "root)."
    ]
    # The shell's own paths, recorded at `start` / `bind`: they outlive a summary that dropped Step 0's printout.
    own, shared = status.get("scripts_dir_shell"), status.get("shared_scripts_dir_shell")
    if isinstance(own, str) and isinstance(shared, str):
        parts.append(
            f"In the shell, the scripts are in `{own}` and `{shared}`; "
            "the SKILL.md is in the parent folder of the first."
        )
    elif isinstance(own, str):
        parts.append(f"In the shell, the scripts are in `{own}`; the SKILL.md is in its parent folder.")
    elif isinstance(shared, str):
        parts.append(f"In the shell, the shared scripts are in `{shared}`.")
    parts.append("This continues the run; it does not re-run it. If you are a sub-agent, ignore this.")
    return " ".join(parts)


def decide(payload: dict[str, Any]) -> dict[str, Any] | None:
    if payload.get("hook_event_name") not in (None, "SessionStart") or payload.get("source") != "compact":
        return None
    transcript = payload.get("transcript_path")
    if not isinstance(transcript, str) or not os.path.isfile(transcript):
        return None
    dtc = _type_check()
    rows = dtc._transcript_tools().read_transcript(transcript)
    started = {skill for _i, skill in dtc.invocations(rows)}
    if not started:
        return None
    path = latest_status_path(rows, dtc.strings)
    if not path or not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as fh:
        status = json.load(fh)
    if not isinstance(status, dict):
        return None
    state, skill, run_id = status.get("status"), status.get("skill"), status.get("run_id")
    if state not in OPEN or skill not in started or not isinstance(run_id, str):
        return None
    return {
        "hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": note(skill, run_id, state, status)}
    }


def main() -> None:
    try:
        payload = json.load(sys.stdin)
        if isinstance(payload, dict):
            out = decide(payload)
            if out is not None:
                sys.stdout.write(json.dumps(out))
    except Exception as e:  # noqa: BLE001 - a hook that crashes helps nobody; print nothing on stdout
        _log(f"{type(e).__name__}: {e}")
    sys.exit(0)


if __name__ == "__main__":
    main()
