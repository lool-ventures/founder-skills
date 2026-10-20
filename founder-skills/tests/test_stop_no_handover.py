"""The Stop hook under `FS_HOST_NO_HANDOVER`. The hook never reads the ledger's flag: it keys on (a) a real closer
run whose result is the host line, and (b) the line in a founder's own message of this prompt. (a) and (b): the
final message is not judged (it is the host's own text). (a) alone: the host line is the comparand. (b) alone: the
founder hand-over is judged as before. Transcripts are synthetic, shaped like the session JSONL.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_stop_handover_hook as base  # noqa: E402

F = "The analysis is complete. The host delivers its output."
MEMO = "Investment memo for Example Co: ARR $4.2M, burn $310K a month, 19 months of runway.\n"
TASK_ROW = "[SCHEDULED TASK - weekly-memo]\nReview the attached materials.\n\nFS_HOST_NO_ASK\nFS_HOST_NO_HANDOVER\n"
CLOSER = 'python3 "$SCRIPTS/closing_message.py" --report "/w/artifacts/market-sizing-foo/report.json" --link none'

_run = base._run
_user = base._user
_assistant_text = base._assistant_text
_call_with_id = base._call_with_id
_result_for = base._result_for


def _hook() -> Any:
    path = base.SCRIPTS / "stop_handover_check.py"
    spec = importlib.util.spec_from_file_location("stop_handover_check_nh", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _rows(
    prompt: Any, result: str, *after: dict[str, Any], cmd: str = CLOSER, tool: str = "mcp__workspace__bash"
) -> list[dict[str, Any]]:
    head = [prompt] if isinstance(prompt, dict) else [_user(prompt)]
    return [*head, _call_with_id(tool, cmd, "toolu_close"), _result_for("toolu_close", result), *after]


def _decision(tmp_path: Path, rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    proc = _run(tmp_path, rows)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout) if proc.stdout else None


def test_a_and_b_leave_the_hosts_memo_unjudged(tmp_path: Path) -> None:
    rows = _rows(TASK_ROW, F + "\n", _assistant_text(MEMO))
    # Both halves engaged, so the pass below is the host rule's, not a hook that found nothing to judge.
    hook = _hook()
    found = hook.closing_window(rows, None)
    assert found is not None and found[2] == F + "\n"
    assert hook._load_figures().no_handover_in(rows, hook._current_prompt_start(rows), hook._is_real_user_prompt)
    assert _decision(tmp_path, rows) is None


def test_a_alone_makes_the_host_line_the_comparand(tmp_path: Path) -> None:
    block = _decision(tmp_path, _rows("Size this market.", F + "\n", _assistant_text(MEMO)))
    assert block is not None and block["decision"] == "block"
    reason = block["reason"]
    hook = _hook()
    assert hook.HOST_LINE_LEAD in reason and reason.rstrip().endswith(F)
    assert base.LEAD not in reason and "founder" not in reason
    assert _decision(tmp_path, _rows("Size this market.", F + "\n", _assistant_text(F))) is None


def test_b_alone_judges_the_founder_hand_over_as_before(tmp_path: Path) -> None:
    block = _decision(tmp_path, _rows(TASK_ROW, base.PRINTED, _assistant_text(base.OWN_VERDICT)))
    assert block is not None and base.LEAD in block["reason"]


@pytest.mark.parametrize(
    "row",
    [
        _user(TASK_ROW, isMeta=True),
        _user(TASK_ROW, isCompactSummary=True),
        _user(TASK_ROW, origin={"kind": "task-notification"}),
        _user(TASK_ROW, origin={"kind": "peer"}, isMeta=True),
        _user("<task-notification>\n" + TASK_ROW),
    ],
    ids=["skill-text", "compaction-summary", "task-notification", "peer", "notification-tag"],
)
def test_the_line_outside_a_founders_own_message_is_not_b(tmp_path: Path, row: dict[str, Any]) -> None:
    rows = [_user("Size this market."), row] + _rows(_user("x"), F + "\n", _assistant_text(MEMO))[1:]
    block = _decision(tmp_path, rows)
    assert block is not None and _hook().HOST_LINE_LEAD in block["reason"]


def test_the_line_in_a_tool_result_is_not_b(tmp_path: Path) -> None:
    rows = [
        _user("Size this market."),
        _call_with_id("mcp__workspace__bash", "cat request.txt", "toolu_cat"),
        _result_for("toolu_cat", TASK_ROW),
        *_rows(_user("x"), F + "\n", _assistant_text(MEMO))[1:],
    ]
    block = _decision(tmp_path, rows)
    assert block is not None and _hook().HOST_LINE_LEAD in block["reason"]


def test_the_line_in_command_args_counts(tmp_path: Path) -> None:
    prompt = (
        "<command-name>/founder-skills:market-sizing</command-name>\n<command-args>FS_HOST_NO_HANDOVER</command-args>"
    )
    assert _decision(tmp_path, _rows(prompt, F + "\n", _assistant_text(MEMO))) is None


def test_the_line_only_in_skill_args_is_not_b(tmp_path: Path) -> None:
    skill_call = {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [
                {"type": "tool_use", "id": "toolu_skill", "name": "Skill", "input": {"skill": "x", "args": TASK_ROW}}
            ],
        },
    }
    rows = [_user("Run the chain."), skill_call, _result_for("toolu_skill", "ok")]
    rows += _rows(_user("x"), F + "\n", _assistant_text(MEMO))[1:]
    block = _decision(tmp_path, rows)
    assert block is not None and _hook().HOST_LINE_LEAD in block["reason"]


def test_a_compaction_between_the_task_row_and_the_closer_keeps_b(tmp_path: Path) -> None:
    boundary = {"type": "system", "subtype": "compact_boundary", "isSidechain": False, "content": "compacted"}
    summary = _user("Summary of the conversation so far.", isCompactSummary=True)
    rows = [_user(TASK_ROW), boundary, summary] + _rows(_user("x"), F + "\n", _assistant_text(MEMO))[1:]
    assert _decision(tmp_path, rows) is None


def test_a_human_row_mid_run_starts_a_new_prompt_and_b_no_longer_holds(tmp_path: Path) -> None:
    rows = [_user(TASK_ROW), _user("Also, keep it short.")] + _rows(_user("x"), F + "\n", _assistant_text(MEMO))[1:]
    block = _decision(tmp_path, rows)
    assert block is not None and _hook().HOST_LINE_LEAD in block["reason"]


def test_a_compound_block_still_yields_the_host_line(tmp_path: Path) -> None:
    cmd = f"cp a b && ls out && {CLOSER}"
    assert (
        _decision(tmp_path, _rows("Size it.", "copied\nreport.json\n" + F + "\n", _assistant_text(F), cmd=cmd)) is None
    )
    block = _decision(tmp_path, _rows("Size it.", "copied\n" + F + "\n", _assistant_text(MEMO), cmd=cmd))
    assert block is not None and _hook().HOST_LINE_LEAD in block["reason"]


def test_the_host_loops_exit_lead_is_dropped(tmp_path: Path) -> None:
    assert _decision(tmp_path, _rows(TASK_ROW, "[exit 0]\n" + F + "\r\n", _assistant_text(MEMO))) is None


def test_a_real_hand_over_beside_an_echoed_host_line_is_judged_as_the_hand_over(tmp_path: Path) -> None:
    result = base.PRINTED + F + "\n"
    block = _decision(tmp_path, _rows(TASK_ROW, result, _assistant_text(F)))
    assert block is not None and base.LEAD in block["reason"] and base.PRINTED.rstrip() in block["reason"]


@pytest.mark.parametrize(
    ("tool", "cmd"),
    [
        ("mcp__workspace__bash", f"echo '{F}' # closing_message.py"),
        ("Read", "/w/scripts/closing_message.py"),
        ("mcp__workspace__bash", "grep -n verdict closing_message.py"),
    ],
    ids=["echo", "read", "grep"],
)
def test_only_a_closer_run_through_python_prints_the_host_line(tool: str, cmd: str) -> None:
    rows = _rows(TASK_ROW, F + "\n", _assistant_text(MEMO), cmd=cmd, tool=tool)
    found = _hook().closing_window(rows, None)
    assert found is not None and found[2] is None


def test_a_newer_handover_file_of_another_folder_is_not_the_comparand(tmp_path: Path) -> None:
    base._handover(tmp_path, base.PRINTED, run="market-sizing-other")
    assert _decision(tmp_path, _rows("Size it.", F + "\n", _assistant_text(F))) is None


def test_the_follow_up_to_a_host_line_block_is_measured(tmp_path: Path) -> None:
    hook = _hook()
    rows = _rows("Size it.", F + "\n", _assistant_text(MEMO))
    block = _decision(tmp_path, rows)
    assert block is not None
    rows += [_user(f"Stop hook feedback: {block['reason']}", isMeta=True), _assistant_text(F)]
    proc = _run(tmp_path, rows, {"stop_hook_active": True})
    assert proc.stdout == "" and "second stop: hand-over passed" in proc.stderr
    assert hook._last_feedback_asked_for_the_hand_over(rows, 1)


def test_under_the_host_line_a_linked_unattached_file_is_still_asked_for(tmp_path: Path) -> None:
    linked = "Done: [the report](computer:///sessions/x/mnt/outputs/artifacts/market-sizing-foo/report.md)\n"
    rows = [base._snapshot("mcp__workspace__bash", "mcp__cowork__present_files"), _user("Size it.")]
    rows += [
        _call_with_id("mcp__workspace__bash", base.COMPOSE_CMD, "toolu_compose"),
        _result_for("toolu_compose", '{"ok": true}'),
    ]
    rows += _rows(_user("x"), F + "\n", _assistant_text(linked))[1:]
    block = _decision(tmp_path, rows)
    assert block is not None and "present_files" in block["reason"]
    # (a) and (b): nothing about the final message is judged, the delivery ask included.
    rows[1] = _user(TASK_ROW)
    assert _decision(tmp_path, rows) is None


def test_a_refused_closer_under_the_line_never_says_founder(tmp_path: Path) -> None:
    rows = [_user(TASK_ROW), _call_with_id("mcp__workspace__bash", CLOSER, "toolu_close")]
    rows += [_result_for("toolu_close", "Error: RUN_ID_MISMATCH: nothing was printed.", is_error=True)]
    rows += [_assistant_text("The closing step failed.")]
    block = _decision(tmp_path, rows)
    assert block is not None and "RUN_ID_MISMATCH" in block["reason"] and "founder" not in block["reason"]


def test_a_and_b_under_no_ask_with_the_run_left_running_still_ask_once(tmp_path: Path) -> None:
    hook = _hook()
    status = tmp_path / "run_status.json"
    status.write_text(json.dumps({"status": "running", "no_ask": True}))
    start = _result_for("s1", json.dumps({"status_path": str(status)}))
    rows = [_user(TASK_ROW + "FS_HOST_RUN_ID=20261020T090000Z-1a2b3c\n"), start]
    rows += _rows(_user("x"), F + "\n", _assistant_text(MEMO))[1:]
    transcript = tmp_path / "t2.jsonl"
    transcript.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    block = hook.decide({"hook_event_name": "Stop", "transcript_path": str(transcript)})
    assert block is not None and block["reason"].startswith(hook.NO_ASK_END_MARKER)


@pytest.mark.parametrize(
    ("cmd", "is_f_call"),
    [
        ('python3 "$SCRIPTS/closing_message.py" --link none --report "/w/x/report.json"', True),
        ('python3 \\\n  "$SCRIPTS/fmr_closing_message.py" --report r.json', True),
        ("python3 -c 'print(1)' # closing_message.py", False),
        ("python3 other.py closing_message.py", False),
    ],
    ids=["skill-md-form", "continued-line", "python-c", "closer-as-argument"],
)
def test_the_closer_must_be_pythons_script_argument(cmd: str, is_f_call: bool) -> None:
    found = _hook().closing_window(_rows(TASK_ROW, F + "\n", _assistant_text(MEMO), cmd=cmd), None)
    assert found is not None and (found[2] == F + "\n") is is_f_call


def test_a_host_line_in_a_call_that_does_not_run_the_closer_cannot_hide_a_refusal(tmp_path: Path) -> None:
    cmd = f"{CLOSER}; echo '{F}'"
    rows = [_user(TASK_ROW), _call_with_id("Read", cmd, "toolu_close")]
    rows += [_result_for("toolu_close", "Error: RUN_ID_MISMATCH\n" + F, is_error=True), _assistant_text(MEMO)]
    block = _decision(tmp_path, rows)
    assert block is not None and "RUN_ID_MISMATCH" in block["reason"]


def test_a_reply_tool_line_from_an_earlier_prompt_is_not_read_under_the_host_line(tmp_path: Path) -> None:
    rows = [_user("FS_HOST_REPLY_TOOL mcp__hostchat__reply text"), _assistant_text("ok")]
    rows += _rows("Size it.", F + "\n", _assistant_text(MEMO))
    block = _decision(tmp_path, rows)
    assert block is not None and "mcp__hostchat__reply" not in block["reason"]
    assert _hook().HOST_LINE_LEAD in block["reason"]


def test_a_review_page_left_unsent_is_not_asked_for_under_a_and_b(tmp_path: Path) -> None:
    page = [
        base._snapshot("mcp__workspace__bash", "mcp__cowork__present_files"),
        _user(TASK_ROW),
        _call_with_id("mcp__workspace__bash", base.REVIEW_CMD, "toolu_review"),
        _result_for("toolu_review", '{"ok": true, "mode": "static"}'),
    ]
    rows = page + _rows(_user("x"), F + "\n", _assistant_text(MEMO))[1:]
    assert _decision(tmp_path, rows) is None


def test_a_resume_message_without_the_line_meets_the_host_line_rule(tmp_path: Path) -> None:
    """A host resuming a waiting run must put the line in its resume message itself: it is never repeated."""
    rows = [_user(TASK_ROW), _assistant_text("Waiting on the approach question.")]
    rows += _rows("FS_HOST_RUN_ID=20261020T090000Z-1a2b3c\nFS_HOST_ANSWER ms_methodology=looks_good", F + "\n",
                  _assistant_text(MEMO))  # fmt: skip
    block = _decision(tmp_path, rows)
    assert block is not None and _hook().HOST_LINE_LEAD in block["reason"]


def test_the_scheduled_task_shape_with_the_line_after_script_output(tmp_path: Path) -> None:
    row = "[SCHEDULED TASK - memo]\nScript output:\n  rows: 12\nFS_HOST_NO_HANDOVER\nThen write the memo.\n"
    assert _decision(tmp_path, _rows(row, F + "\n", _assistant_text(MEMO))) is None


def test_a_forged_ledger_flag_with_a_normal_closer_result_is_judged_as_before(tmp_path: Path) -> None:
    """The hook never reads the flag: a ledger that says no-handover changes nothing about a real hand-over."""
    ledger = tmp_path / "gates.json"
    ledger.write_text(json.dumps({"no_handover": {"raw": "FS_HOST_NO_HANDOVER"}}))
    start = _result_for("s1", json.dumps({"ledger_path": str(ledger), "status_path": str(tmp_path / "s.json")}))
    rows = [_user("Size it."), start] + _rows(_user("x"), base.PRINTED, _assistant_text(base.OWN_VERDICT))[1:]
    block = _decision(tmp_path, rows)
    assert block is not None and base.LEAD in block["reason"]


def test_the_transcripts_real_hand_over_beats_a_host_line_handover_file(tmp_path: Path) -> None:
    base._handover(tmp_path, F + "\n")
    block = _decision(tmp_path, _rows("Size it.", base.PRINTED, _assistant_text(MEMO)))
    assert block is not None and base.PRINTED.rstrip() in block["reason"]


def test_the_delivery_only_ask_under_the_host_line_never_says_founder(tmp_path: Path) -> None:
    linked = F + "\n[the report](computer:///sessions/x/mnt/outputs/artifacts/market-sizing-foo/report.md)\n"
    rows = [base._snapshot("mcp__workspace__bash", "mcp__cowork__present_files"), _user("Size it.")]
    rows += [
        _call_with_id("mcp__workspace__bash", base.COMPOSE_CMD, "toolu_compose"),
        _result_for("toolu_compose", '{"ok": true}'),
    ]
    rows += _rows(_user("x"), F + "\n", _assistant_text(linked))[1:]
    block = _decision(tmp_path, rows)
    assert block is not None and "present_files" in block["reason"] and "founder" not in block["reason"]
