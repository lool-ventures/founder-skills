"""`stop_handover_check.py`: the Stop hook that sends the model back once when its closing
message does not carry the printed hand-over. Exercised through the POSIX wrapper as the runtime
invokes it, with stdin payloads shaped like the CLI's (2.1.278) and transcripts shaped like the
session JSONL: real prompts are `type: user` without `isMeta`; skill attachments and hook feedback
are `isMeta: true`; tool results are user turns carrying `tool_result` blocks."""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
WRAPPER = SCRIPTS / "stop-handover-check.sh"

PRINTED = (
    "Here's your finished market sizing: [the written report](computer:///out/X.md) — it opens with the verdict.\n"
    "\n"
    "Your materials state TAM $80.0B; this analysis finds $7.0B (top-down) and $99.9B (bottom-up). "
    "Self-check: 100% (22/22 pass, 0 fail, 0 N/A)\n"
    "\n"
    "If you want to keep the working data behind this — say so and I'll send it as a single archive.\n"
)
OWN_VERDICT = (
    "Here's your finished market sizing: [the written report](computer:///out/X.md).\n\n"
    "1. Your $80B TAM is about 11x what the top-down build supports.\n"
    "2. Recommendation: revisit the deck's market slide.\n"
)
# The follow-up's lead, pinned as a literal rather than imported: it is the sentence a founder reads,
# so a reword must be a deliberate edit here. It states provenance and precedence, never error --
# the rule cannot tell a wrong figure from a correct paraphrase, and blocks both.
LEAD = (
    "For the record, this is the summary as the analysis produced it; "
    "if a figure in my message above differs from one here, use the one here:"
)


def _user(text: str, **extra: Any) -> dict[str, Any]:
    return {"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": text}]}, **extra}


def _tool_result() -> dict[str, Any]:
    return {"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "content": ""}]}}


def _assistant_text(text: str, **extra: Any) -> dict[str, Any]:
    return {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}, **extra}


def _assistant_call(name: str, command: str) -> dict[str, Any]:
    return {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [{"type": "tool_use", "name": name, "input": {"command": command}}],
        },
    }


CLOSING_CMD = (
    'python3 "$SCRIPTS/closing_message.py" --report "/sessions/x/mnt/outputs/artifacts/market-sizing-foo/report.json"'
)


def _run(tmp_path: Path, rows: list[dict[str, Any]] | None, payload_extra: dict[str, Any] | None = None) -> Any:
    transcript = tmp_path / "t.jsonl"
    if rows is not None:
        transcript.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    payload = {
        "session_id": "s",
        "transcript_path": str(transcript),
        "cwd": str(tmp_path / "outputs"),
        "hook_event_name": "Stop",
        "stop_hook_active": False,
        "last_assistant_message": rows[-1]["message"]["content"][0].get("text", "") if rows else "",
        **(payload_extra or {}),
    }
    return subprocess.run(["sh", str(WRAPPER)], input=json.dumps(payload), capture_output=True, text=True, timeout=30)


def _handover(tmp_path: Path, text: str = PRINTED, sub: str = "artifacts", run: str = "market-sizing-foo") -> Path:
    d = tmp_path / "outputs" / sub / run
    d.mkdir(parents=True, exist_ok=True)
    p = d / "handover.txt"
    p.write_text(text, encoding="utf-8")
    return p


def _rows_after_call(*after: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        _user("Use the market-sizing skill on this deck."),
        _user("Base directory for this skill: /x", isMeta=True),
        _assistant_call("Bash", "python3 market_sizing.py --stdin"),
        _tool_result(),
        _assistant_call("mcp__workspace__bash", CLOSING_CMD),
        _tool_result(),
        *after,
    ]


def test_verbatim_message_passes_silently(tmp_path: Path) -> None:
    _handover(tmp_path)
    r = _run(tmp_path, _rows_after_call(_assistant_text("Done!\n\n" + PRINTED)))
    assert r.returncode == 0 and r.stdout == "" and r.stderr == "", r


def test_own_verdict_is_blocked_with_a_correction(tmp_path: Path) -> None:
    _handover(tmp_path)
    r = _run(tmp_path, _rows_after_call(_assistant_text(OWN_VERDICT)))
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["decision"] == "block"
    assert LEAD in out["reason"]
    assert PRINTED.rstrip() in out["reason"]
    assert "not sent whole" in out["reason"]


def test_text_before_a_trailing_tool_call_is_judged_too(tmp_path: Path) -> None:
    """On real runs present_files and TaskUpdate sit between the closing call and the final text;
    a verdict emitted before them is on screen and invisible to last_assistant_message."""
    _handover(tmp_path)
    rows = _rows_after_call(
        _assistant_text(OWN_VERDICT),
        _assistant_call("mcp__cowork__present_files", "x"),
        _tool_result(),
        _assistant_text(PRINTED),
    )
    r = _run(tmp_path, rows, {"last_assistant_message": PRINTED})
    out = json.loads(r.stdout)
    assert out["decision"] == "block"
    # PRINTED is there whole, so this is the OTHER failure (a figure added around it) -- and it
    # gets the same lead: an addition can be wrong ("11x") or right, and the rule cannot tell.
    assert "was added around" in out["reason"]
    assert LEAD in out["reason"]


def test_second_stop_is_let_through(tmp_path: Path) -> None:
    """One rewrite is the budget: `stop_hook_active` true means the model already came back."""
    _handover(tmp_path)
    r = _run(tmp_path, _rows_after_call(_assistant_text(OWN_VERDICT)), {"stop_hook_active": True})
    assert r.stdout == ""


def test_the_correction_the_reason_asks_for_satisfies_the_rule(tmp_path: Path) -> None:
    """After a block, the judged text restarts at the feedback turn: the model's latest attempt is
    what is checked, and the correction the reason dictates must pass it."""
    _handover(tmp_path)
    r = _run(tmp_path, _rows_after_call(_assistant_text(OWN_VERDICT)))
    reason = json.loads(r.stdout)["reason"]
    correction = reason[reason.index(LEAD) :]
    rows = _rows_after_call(
        _assistant_text(OWN_VERDICT),
        {"type": "user", "isMeta": True, "message": {"role": "user", "content": "Stop hook feedback:\n" + reason}},
        _assistant_text(correction),
    )
    r2 = _run(tmp_path, rows)  # stop_hook_active deliberately False: the rule itself must pass
    assert r2.stdout == "", r2.stdout


def test_another_skills_stop_is_ignored(tmp_path: Path) -> None:
    _handover(tmp_path)
    rows = [
        _user("Review my deck."),
        _assistant_call("Bash", "python3 checklist.py"),
        _tool_result(),
        _assistant_text("Score: 71%."),
    ]
    r = _run(tmp_path, rows)
    assert r.returncode == 0 and r.stdout == "" and r.stderr == ""


def test_a_closing_call_from_an_earlier_prompt_does_not_trigger(tmp_path: Path) -> None:
    _handover(tmp_path)
    rows = _rows_after_call(_assistant_text(PRINTED)) + [
        _user("Thanks. What is 2+2?"),
        _assistant_text("4."),
    ]
    r = _run(tmp_path, rows)
    assert r.stdout == ""


def test_stop_feedback_turns_are_not_prompts(tmp_path: Path) -> None:
    """A hook's own feedback must not reset 'the current prompt', or the trigger call would fall
    before it and every later stop would read as another skill's."""
    _handover(tmp_path)
    rows = _rows_after_call(
        _assistant_text(OWN_VERDICT),
        {"type": "user", "isMeta": True, "message": {"role": "user", "content": "Stop hook feedback:\nx"}},
        _assistant_text(OWN_VERDICT),
    )
    r = _run(tmp_path, rows)
    assert json.loads(r.stdout)["decision"] == "block"


def test_other_events_are_ignored(tmp_path: Path) -> None:
    _handover(tmp_path)
    r = _run(tmp_path, _rows_after_call(_assistant_text(OWN_VERDICT)), {"hook_event_name": "SubagentStop"})
    assert r.stdout == ""


def test_missing_handover_fails_open_with_a_stderr_line(tmp_path: Path) -> None:
    r = _run(tmp_path, _rows_after_call(_assistant_text(OWN_VERDICT)))
    assert r.returncode == 0 and r.stdout == "" and "no handover.txt" in r.stderr


def test_vm_loop_cwd_layout_is_found(tmp_path: Path) -> None:
    _handover(tmp_path, sub="mnt/outputs/artifacts")
    r = _run(tmp_path, _rows_after_call(_assistant_text(OWN_VERDICT)))
    assert json.loads(r.stdout)["decision"] == "block"


def test_newest_handover_wins(tmp_path: Path) -> None:
    old = _handover(tmp_path, text="OLD RUN'S TEXT\n", run="market-sizing-old")
    os.utime(old, (time.time() - 3600, time.time() - 3600))
    _handover(tmp_path, run="market-sizing-new")
    r = _run(tmp_path, _rows_after_call(_assistant_text("Done!\n\n" + PRINTED)))
    assert r.stdout == "", r.stdout


def test_unreadable_transcript_falls_back_to_the_message_opener(tmp_path: Path) -> None:
    _handover(tmp_path)
    r = _run(tmp_path, None, {"last_assistant_message": OWN_VERDICT})
    assert json.loads(r.stdout)["decision"] == "block"
    r2 = _run(tmp_path, None, {"last_assistant_message": "Score: 71%."})
    assert r2.stdout == ""


@pytest.mark.parametrize("stdin", ["", "not json", "[1,2]"])
def test_garbage_stdin_exits_zero_silently_on_stdout(tmp_path: Path, stdin: str) -> None:
    r = subprocess.run(["sh", str(WRAPPER)], input=stdin, capture_output=True, text=True, timeout=30)
    assert r.returncode == 0 and r.stdout == ""


def test_wrapper_is_posix_sh() -> None:
    text = WRAPPER.read_text(encoding="utf-8")
    assert text.startswith("#!/bin/sh\n")
    for bashism in ("[[", "$(<", "<(", "function ", "local "):
        assert bashism not in text, bashism
    assert os.access(WRAPPER, os.X_OK)
