#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Did a recorded run's final message carry the printed hand-over whole, with the Stop hook actually checking it?

WHY A REPO-SIDE CHECK. `hook_event_fired: Stop` passed on a committed recording whose final message was the
model's own rewrite of the hand-over, made while the Stop hook failed open with "no handover.txt" on its
stderr. No harness assertion can see either fact: `transcript_*` matches literals over assistant text and
cannot compare against the run's own printed text, and `hook_event_*` see a hook's frame and exit code, not
its stderr. The recorded `hook_response` frame does carry `stderr`, and the events carry the closing call,
its printed result and the final text -- so this reads them.

ONE OWNER. The judgement is the Stop hook's own: this loads `founder-skills/scripts/stop_handover_check.py`
by path and runs its `closing_call` (which closing script ran, the text after it restarting after a hook's
feedback turn, and the printed hand-over sliced from the call's result) and its containment rule. Only the
row shape is adapted here: a recording's stream-json events become the transcript rows the hook reads (a
sub-agent's event, `parent_tool_use_id` set, is a sidechain row; a "Stop hook feedback:" turn is a meta row).

Outcomes: PASS (exit 0), FAIL (exit 1), NOT-EXERCISED (exit 2: no closing call -- a gated stop, or a skill
with no printed hand-over). Prints one JSON object. Usage:
    handover_check_cassette.py <cassette.json> [--pretty]
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

_HOOK = Path(__file__).resolve().parents[1] / "founder-skills" / "scripts" / "stop_handover_check.py"
FAILED_OPEN = "no handover.txt"


def _hook() -> Any:
    spec = importlib.util.spec_from_file_location("stop_handover_check_for_cassettes", _HOOK)
    if spec is None or spec.loader is None:
        raise ImportError(str(_HOOK))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@dataclass
class Result:
    outcome: str
    skill: str | None = None
    problems: list[str] = field(default_factory=list)


def _decode(event: Any) -> dict[str, Any] | None:
    if isinstance(event, str):
        try:
            event = json.loads(event)
        except ValueError:
            return None
    return event if isinstance(event, dict) else None


def rows_from_events(events: list[Any], feedback_prefix: str) -> list[dict[str, Any]]:
    """The recording's user/assistant events as the transcript rows the Stop hook reads."""
    rows: list[dict[str, Any]] = []
    for raw in events:
        ev = _decode(raw)
        if ev is None or ev.get("type") not in ("user", "assistant"):
            continue
        message = ev.get("message") if isinstance(ev.get("message"), dict) else {}
        row: dict[str, Any] = {
            "type": ev["type"],
            "message": message,
            "isSidechain": bool(ev.get("parent_tool_use_id")),
        }
        content = message.get("content")
        text = content if isinstance(content, str) else ""
        if isinstance(content, list):
            text = "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
        if ev["type"] == "user" and text.startswith(feedback_prefix):
            row["isMeta"] = True
        rows.append(row)
    return rows


def _stop_stderr(events: list[Any]) -> list[str]:
    out: list[str] = []
    for raw in events:
        ev = _decode(raw)
        if ev and ev.get("subtype") == "hook_response" and ev.get("hook_event") == "Stop":
            out.append(str(ev.get("stderr") or ""))
    return out


def check_events(events: list[Any]) -> Result:
    hook = _hook()
    rows = rows_from_events(events, hook.STOP_FEEDBACK_PREFIX)
    found = hook.closing_call(rows)
    if found is None:
        return Result("NOT-EXERCISED")
    skill, final, printed = found
    problems: list[str] = []
    if printed is None:
        problems.append("the closing call's result holds no whole printed hand-over")
    else:
        ok, why = hook._load_contained()(printed, final)
        if not ok:
            problems.append(f"the final message: {why}")
    for stderr in _stop_stderr(events):
        if FAILED_OPEN in stderr:
            problems.append(f"the Stop hook checked nothing (it failed open): {stderr.strip()[:200]}")
    return Result("FAIL" if problems else "PASS", skill, problems)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cassette", type=Path)
    ap.add_argument("--pretty", action="store_true")
    a = ap.parse_args()
    try:
        events = json.loads(a.cassette.read_text(encoding="utf-8"))["events"]
    except (OSError, ValueError, KeyError, TypeError) as e:
        print(f"handover_check_cassette: cannot read events from {a.cassette}: {e}", file=sys.stderr)
        return 1
    r = check_events(events if isinstance(events, list) else [])
    print(json.dumps(asdict(r), indent=2 if a.pretty else None))
    return {"PASS": 0, "FAIL": 1}.get(r.outcome, 2)


if __name__ == "__main__":
    sys.exit(main())
