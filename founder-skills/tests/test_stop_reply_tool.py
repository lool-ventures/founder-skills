"""The Stop hook on a host whose founder reads replies through a tool (`FS_HOST_REPLY_TOOL`).

On such a host the plain text after the closing step is unseen and is often just "Done."; the founder's message
is what the tool sent. The request names the tool (`FS_HOST_REPLY_TOOL <tool_name> <input_key>`), and the hook
reads that line from a founder's own message only -- any prompt, last line wins, never the run's ledger (the
model types the ledger's lines). When the turn sent through the tool after the closer, the sends alone are
judged. Without the line, everything is judged as before.

Exercised through the POSIX wrapper on transcripts shaped like the session JSONL (helpers from
`test_stop_handover_hook.py`). Every tool name is synthetic. Each test that flips on a lever asserts the lever
in a parametrized sibling (`lever-…`), so the red half is shown, not described.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gate_run_helpers as h  # noqa: E402
import test_stop_handover_hook as base  # noqa: E402

PRINTED = base.PRINTED
OWN_VERDICT = base.OWN_VERDICT
LEAD = base.LEAD
_run = base._run
_user = base._user
_handover = base._handover
_assistant_text = base._assistant_text
_assistant_call = base._assistant_call
_result_for = base._result_for
_call_with_id = base._call_with_id

REPLY_NAME = "mcp__hostchat__reply"
REPLY_LINE = f"FS_HOST_REPLY_TOOL {REPLY_NAME} text"
DONE = "Done."
NOT_WHOLE = "not sent whole"


def _assistant_send(name: str, call_id: str, **tool_input: Any) -> dict[str, Any]:
    return {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [{"type": "tool_use", "id": call_id, "name": name, "input": tool_input}],
        },
    }


def _sent(call_id: str, *, is_error: bool = False) -> dict[str, Any]:
    return _result_for(call_id, "sent", is_error=is_error)


def _feedback(reason: str = "x") -> dict[str, Any]:
    return {"type": "user", "isMeta": True, "message": {"role": "user", "content": "Stop hook feedback:\n" + reason}}


def _reply_rows(*after: dict[str, Any], line: str | None = REPLY_LINE) -> list[dict[str, Any]]:
    """A market-sizing prompt whose founder's message carries `line` (when given), then the closer, then `after`."""
    rows = base._rows_after_call(*after)
    rows[0] = _user("Use the market-sizing skill on this deck." + (f"\n{line}" if line else ""))
    return rows


def _whole_send(line: str | None = REPLY_LINE) -> list[dict[str, Any]]:
    """Closer, a file sent, the hand-over sent whole through the reply tool, then "Done." in plain text."""
    return _reply_rows(
        _assistant_call("mcp__hostchat__send_file", "x"),
        base._tool_result(),
        _assistant_send(REPLY_NAME, "toolu_r1", text=PRINTED),
        _sent("toolu_r1"),
        _assistant_text(DONE),
        line=line,
    )


def _with(rows: list[dict[str, Any]], at: int, row: dict[str, Any]) -> list[dict[str, Any]]:
    return [*rows[:at], row, *rows[at:]]


def _blocks(r: Any, part: str = NOT_WHOLE) -> bool:
    return bool(r.stdout) and part in json.loads(r.stdout)["reason"]


# --- R: red before the fix, green after -------------------------------------------------------------------


@pytest.mark.parametrize("named", [True, False], ids=["line", "lever-no-line"])
def test_a_hand_over_sent_whole_through_the_named_reply_tool_passes(tmp_path: Path, named: bool) -> None:
    """R1. Lever: without the line the plain text is the message, and "Done." does not carry the hand-over."""
    _handover(tmp_path)
    r = _run(tmp_path, _whole_send(REPLY_LINE if named else None))
    if named:
        assert r.returncode == 0 and r.stdout == "" and r.stderr == "", r
    else:
        assert _blocks(r)


def _ledger_rows(tmp_path: Path, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """`rows` with a `start` result naming a ledger that records the reply tool, as `run_status.py` would."""
    ledger = tmp_path / "gates.json"
    ledger.write_text(json.dumps({"reply_tool": {"name": REPLY_NAME, "key": "text", "raw": REPLY_LINE}}))
    start = _result_for("toolu_start", json.dumps({"ledger_path_shell": str(ledger), "status": "running"}))
    return [rows[0], _call_with_id("Bash", "run_status.py start", "toolu_start"), start, *rows[1:]]


@pytest.mark.parametrize(
    "where",
    [
        "ledger",
        "assistant_text",
        "tool_input",
        "tool_result",
        "is_meta",
        "sidechain",
        "compact_summary",
        "agent_result",
        "lever-founder-row",
    ],
)
def test_the_reply_line_counts_only_in_a_founders_own_message(tmp_path: Path, where: str) -> None:
    """R2'. The ledger's lines are typed by the model (they reach `run_status.py start` through a heredoc the
    model writes), so a ledger route would let the model name any tool (a file writer, say) as the founder's
    message, removing the hold by writing it. Only a founder's own row counts; every other place the line can
    appear is ignored, as the no-ask line is. Lever: the same line in the founder's message passes."""
    _handover(tmp_path)
    plain = _whole_send(line=None)
    rows = {
        "ledger": lambda: _ledger_rows(tmp_path, plain),
        "assistant_text": lambda: _with(plain, 1, _assistant_text(REPLY_LINE)),
        "tool_input": lambda: _with(plain, 1, _assistant_call("Bash", f"echo '{REPLY_LINE}'")),
        "tool_result": lambda: _with(plain, 1, _result_for("toolu_x", REPLY_LINE)),
        "is_meta": lambda: _with(plain, 1, _user(REPLY_LINE, isMeta=True)),
        "sidechain": lambda: _with(plain, 1, _user(REPLY_LINE, isSidechain=True)),
        "compact_summary": lambda: _with(plain, 1, _user(REPLY_LINE, isCompactSummary=True)),
        "agent_result": lambda: _with(plain, 1, _user(REPLY_LINE, origin={"kind": "task-notification"})),
        "lever-founder-row": lambda: _whole_send(),
    }[where]()
    r = _run(tmp_path, rows)
    if where == "lever-founder-row":
        assert r.stdout == "", r.stdout
    else:
        assert _blocks(r), where


@pytest.mark.parametrize("wrapped", [False, True], ids=["plain", "command-args"])
def test_the_reply_line_in_an_earlier_prompt_counts_for_a_later_closer(tmp_path: Path, wrapped: bool) -> None:
    """R2''. Which tool reaches the founder is the host's, not the prompt's: a line in the first prompt (also as
    a slash command's arguments) still names the tool when the closer runs in a later prompt. Lever: drop the
    first prompt's line and the later closer is judged on its plain text."""
    _handover(tmp_path)
    first = f"<command-args>{REPLY_LINE}</command-args>" if wrapped else f"Size this market.\n{REPLY_LINE}"
    later = _whole_send(line=None)
    later[0] = _user("Top-down, please.")
    rows = [_user(first), _assistant_text("Which approach should I take?"), *later]
    assert _run(tmp_path, rows).stdout == ""
    rows[0] = _user("Size this market.")
    assert _blocks(_run(tmp_path, rows))


def test_the_last_reply_line_wins(tmp_path: Path) -> None:
    _handover(tmp_path)
    assert _run(tmp_path, _whole_send(line=f"FS_HOST_REPLY_TOOL mcp__other__tool text\n{REPLY_LINE}")).stdout == ""
    assert _blocks(_run(tmp_path, _whole_send(line=f"{REPLY_LINE}\nFS_HOST_REPLY_TOOL mcp__other__tool text")))


@pytest.mark.parametrize("send", [True, False], ids=["send", "lever-no-send"])
def test_unseen_text_with_a_figure_beside_a_whole_send_passes(tmp_path: Path, send: bool) -> None:
    """R3. The plain text is unseen on this host, so a figure in it is not added to the founder's message (the
    hook's docstring says so: the hand-over sent, then contradicted in plain text, passes). Lever: with no send,
    the plain text is judged and its figure blocks."""
    _handover(tmp_path)
    after: list[dict[str, Any]] = [_assistant_text(PRINTED + "\nAlso, the TAM is about 11x the top-down build.")]
    if send:
        after += [_assistant_send(REPLY_NAME, "toolu_r1", text=PRINTED), _sent("toolu_r1")]
    after.append(_assistant_text(DONE))
    r = _run(tmp_path, _reply_rows(*after))
    if send:
        assert r.stdout == "", r.stdout
    else:
        assert _blocks(r, "was added around")


@pytest.mark.parametrize("named", [True, False], ids=["line", "lever-no-line"])
def test_a_turn_ending_on_a_send_ignores_the_payloads_last_text(tmp_path: Path, named: bool) -> None:
    """R4. The transcript ends on the send's result and the payload's `last_assistant_message` is an earlier
    narration with a figure. With a send, the payload's text is never appended. Lever: no line, and the
    lagging-transcript path judges the payload's text."""
    _handover(tmp_path)
    narration = "Working through 3 steps now."
    rows = _reply_rows(
        _assistant_text(narration),
        _assistant_send(REPLY_NAME, "toolu_r1", text=PRINTED),
        _sent("toolu_r1"),
        line=REPLY_LINE if named else None,
    )
    r = _run(tmp_path, rows, {"last_assistant_message": narration})
    if named:
        assert r.stdout == "", r.stdout
    else:
        assert json.loads(r.stdout)["decision"] == "block"


CLAUSE = f"with {REPLY_NAME}, the tool your last message went through, not as plain text"


@pytest.mark.parametrize("send", [True, False], ids=["send", "lever-no-send"])
def test_a_rewritten_send_is_blocked_and_told_to_use_the_same_tool(tmp_path: Path, send: bool) -> None:
    """R5. The reason's lead asks for the follow-up through the same tool, before the correction lead -- which
    is resent to the founder, so the clause never sits inside or after it. Lever: no send, no clause."""
    _handover(tmp_path)
    after: list[dict[str, Any]] = []
    if send:
        after += [_assistant_send(REPLY_NAME, "toolu_r1", text=OWN_VERDICT), _sent("toolu_r1")]
    else:
        after.append(_assistant_text(OWN_VERDICT))
    after.append(_assistant_text(DONE))
    reason = json.loads(_run(tmp_path, _reply_rows(*after)).stdout)["reason"]
    if send:
        assert CLAUSE in reason and reason.index(CLAUSE) < reason.index(LEAD)
        assert REPLY_NAME not in reason[reason.index(LEAD) :]
    else:
        assert CLAUSE not in reason and REPLY_NAME not in reason


def test_a_refused_closer_asks_for_its_follow_up_through_the_tool(tmp_path: Path) -> None:
    """The refused-closer reason asks for a follow-up too; with a send in the turn it names the tool."""
    _handover(tmp_path)
    rows = base._rows_with_result(
        _result_for("toolu_close", base.REFUSED, is_error=True, as_string=True),
        _assistant_send(REPLY_NAME, "toolu_r1", text=base.COULD_NOT_FINISH),
        _sent("toolu_r1"),
        _assistant_text(DONE),
    )
    rows[0] = _user(f"Use the market-sizing skill on this deck.\n{REPLY_LINE}")
    reason = json.loads(_run(tmp_path, rows).stdout)["reason"]
    assert "compose the report again for this run" in reason and CLAUSE in reason
    rows[0] = _user("Use the market-sizing skill on this deck.")  # the lever: no line, no clause
    assert CLAUSE not in json.loads(_run(tmp_path, rows).stdout)["reason"]


def test_the_correction_sent_through_the_tool_satisfies_the_rule(tmp_path: Path) -> None:
    """The correction the reason dictates, sent through the tool after the feedback turn, passes."""
    _handover(tmp_path)
    first = [_assistant_send(REPLY_NAME, "toolu_r1", text=OWN_VERDICT), _sent("toolu_r1"), _assistant_text(DONE)]
    reason = json.loads(_run(tmp_path, _reply_rows(*first)).stdout)["reason"]
    rows = _reply_rows(
        *first,
        _feedback(reason),
        _assistant_send(REPLY_NAME, "toolu_r2", text=reason[reason.index(LEAD) :]),
        _sent("toolu_r2"),
        _assistant_text(DONE),
    )
    assert _run(tmp_path, rows).stdout == ""


@pytest.mark.parametrize(
    ("case", "want"),
    [
        ("text-passed", "second stop: hand-over passed"),
        ("text-failed", "second stop: hand-over failed: the printed hand-over was not sent whole"),
        ("send-passed", "second stop: hand-over passed"),
        ("send-failed", "second stop: hand-over failed: the printed hand-over was not sent whole"),
    ],
)
def test_second_stop_logs_whether_the_hand_over_passed(tmp_path: Path, case: str, want: str) -> None:
    """R6. On `stop_hook_active` the hook never blocks again, but it judges the follow-up and writes one stderr
    line, so the closing-rewrite rate is measured. With the tool named, the follow-up sent through it is what is
    judged (judging the plain "Done." would log `failed` on every correction)."""
    _handover(tmp_path)
    good = LEAD + "\n\n" + PRINTED
    follow = {
        "text-passed": [_assistant_text(good)],
        "text-failed": [_assistant_text(OWN_VERDICT)],
        "send-passed": [_assistant_send(REPLY_NAME, "toolu_r2", text=good), _sent("toolu_r2"), _assistant_text(DONE)],
        "send-failed": [
            _assistant_send(REPLY_NAME, "toolu_r2", text=OWN_VERDICT),
            _sent("toolu_r2"),
            _assistant_text(DONE),
        ],
    }[case]
    rows = _reply_rows(_assistant_text(OWN_VERDICT), _feedback(), *follow)
    r = _run(tmp_path, rows, {"stop_hook_active": True})
    assert r.returncode == 0 and r.stdout == ""
    assert r.stderr.strip() == f"stop_handover_check: {want}", r.stderr


def test_a_second_stop_with_no_closing_call_writes_nothing(tmp_path: Path) -> None:
    r = _run(tmp_path, [_user("Review my deck."), _assistant_text("Score: 71%.")], {"stop_hook_active": True})
    assert r.stdout == "" and r.stderr == ""


# --- P: pins (they block today too; their red half is the lever) --------------------------------------------


@pytest.mark.parametrize("digit", [True, False], ids=["figure", "lever-no-figure"])
def test_a_figure_added_in_a_send_beside_the_hand_over_is_blocked(tmp_path: Path, digit: bool) -> None:
    """P1. The remainder rule applies to the sends. Lever: the same addition with no digit passes."""
    _handover(tmp_path)
    extra = "The TAM is about 11x the top-down build." if digit else "Happy to go deeper on any part."
    rows = _reply_rows(
        _assistant_send(REPLY_NAME, "toolu_r1", text=PRINTED),
        _sent("toolu_r1"),
        _assistant_send(REPLY_NAME, "toolu_r2", text=extra),
        _sent("toolu_r2"),
        _assistant_text(DONE),
    )
    r = _run(tmp_path, rows)
    if digit:
        assert json.loads(r.stdout)["reason"].startswith(
            "Your last message did not deliver the printed hand-over as written (text with a figure was added"
        )
    else:
        assert r.stdout == "", r.stdout


@pytest.mark.parametrize("errored", [True, False], ids=["is_error", "lever-ok"])
def test_a_send_that_errored_does_not_count(tmp_path: Path, errored: bool) -> None:
    """P2. A send whose result is `is_error: true` never reached the founder. Lever: the same send succeeding."""
    _handover(tmp_path)
    rows = _reply_rows(
        _assistant_send(REPLY_NAME, "toolu_r1", text=PRINTED),
        _sent("toolu_r1", is_error=errored),
        _assistant_text(DONE),
    )
    r = _run(tmp_path, rows)
    if errored:
        assert _blocks(r)
    else:
        assert r.stdout == "", r.stdout


def test_a_send_with_no_result_row_yet_counts(tmp_path: Path) -> None:
    """The tool_use row lands before its result; a send not yet answered still went out."""
    _handover(tmp_path)
    rows = _reply_rows(_assistant_send(REPLY_NAME, "toolu_r1", text=PRINTED))
    assert _run(tmp_path, rows, {"last_assistant_message": ""}).stdout == ""


@pytest.mark.parametrize(
    ("name", "key", "sidechain"),
    [
        ("mcp__hostchat__repl", "text", False),
        ("mcp__hostchat__reply_all", "text", False),
        ("MCP__HOSTCHAT__REPLY", "text", False),
        ("x" + REPLY_NAME, "text", False),
        (REPLY_NAME, "text", True),
        (REPLY_NAME, "body", False),
        (REPLY_NAME, "text", None),
    ],
    ids=["prefix", "suffix", "case", "leading", "sidechain", "wrong-key", "lever-exact"],
)
def test_only_the_exact_name_and_key_count_as_a_send(tmp_path: Path, name: str, key: str, sidechain: Any) -> None:
    """P3. Exact equality, never substring, prefix or case-fold; a sub-agent's call is not the founder's message;
    the right name with another input key is not a send (the text path judges it). Lever: the exact name and
    key on the main thread pass."""
    _handover(tmp_path)
    send = _assistant_send(name, "toolu_r1", **{key: PRINTED})
    if sidechain:
        send["isSidechain"] = True
    r = _run(tmp_path, _reply_rows(send, _sent("toolu_r1"), _assistant_text(DONE)))
    if sidechain is None:
        assert r.stdout == "", r.stdout
    else:
        assert _blocks(r)


@pytest.mark.parametrize("before", [True, False], ids=["before-closer", "lever-after-closer"])
def test_a_send_before_the_closing_call_does_not_count(tmp_path: Path, before: bool) -> None:
    """P4. A send of the hand-over before the closer ran is not a send after it."""
    _handover(tmp_path)
    send = [_assistant_send(REPLY_NAME, "toolu_r1", text=PRINTED), _sent("toolu_r1")]
    if before:
        rows = _reply_rows(_assistant_text(DONE))
        rows = [rows[0], *send, *rows[1:]]
    else:
        rows = _reply_rows(*send, _assistant_text(DONE))
    r = _run(tmp_path, rows)
    assert _blocks(r) if before else r.stdout == ""


@pytest.mark.parametrize("feedback", [True, False], ids=["feedback", "lever-no-feedback"])
def test_a_send_before_stop_feedback_is_dropped(tmp_path: Path, feedback: bool) -> None:
    """P4. After a feedback turn the latest attempt is judged: an earlier whole send does not carry it."""
    _handover(tmp_path)
    rows = _reply_rows(
        _assistant_send(REPLY_NAME, "toolu_r1", text=PRINTED),
        _sent("toolu_r1"),
        *([_feedback()] if feedback else []),
        _assistant_send(REPLY_NAME, "toolu_r2", text="Anything else?"),
        _sent("toolu_r2"),
        _assistant_text(DONE),
    )
    r = _run(tmp_path, rows)
    assert _blocks(r) if feedback else r.stdout == ""


@pytest.mark.parametrize("whole", [True, False], ids=["whole", "lever-rewritten"])
def test_a_quiet_run_judges_the_send(tmp_path: Path, whole: bool) -> None:
    """P5. Under FS_HOST_NO_ASK the hand-over is still judged, on the send."""
    _handover(tmp_path)
    rows = _reply_rows(
        _assistant_send(REPLY_NAME, "toolu_r1", text=PRINTED if whole else OWN_VERDICT),
        _sent("toolu_r1"),
        _assistant_text(DONE),
        line=f"FS_HOST_RUN_ID=20261016T100000Z-0a0b0c\nFS_HOST_NO_ASK\n{REPLY_LINE}",
    )
    r = _run(tmp_path, rows)
    assert r.stdout == "" if whole else _blocks(r)


@pytest.mark.parametrize(
    "line",
    [
        f"FS_HOST_REPLY_TOOL {REPLY_NAME}",
        f"FS_HOST_REPLY_TOOL {REPLY_NAME} text extra",
        "FS_HOST_REPLY_TOOL mcp__host.chat__reply text",
        f"FS_HOST_REPLY_TOOL {REPLY_NAME} 1text",
        "FS_HOST_REPLY_TOOL Bash command",
        "FS_HOST_REPLY_TOOL SendMessage message",
        "FS_HOST_REPLY_TOOL mcp__cowork__present_files files",
        "FS_HOST_REPLY_TOOL SendUserFile message",
    ],
    ids=["one-token", "three-tokens", "bad-name", "bad-key", "shell", "agent-message", "delivery", "send-file"],
)
def test_an_invalid_reply_line_is_ignored_with_a_stderr_line(tmp_path: Path, line: str) -> None:
    """P6. A line the hook's copy of the shape rejects is ignored (today's behaviour), with one stderr line.
    The send uses the line's own name and carries the hand-over under every key it names, so only the
    rejection can make it block."""
    _handover(tmp_path)
    parts = line.split()
    name = parts[1] if len(parts) > 1 else REPLY_NAME
    rows = _reply_rows(
        _assistant_send(name, "toolu_r1", text=PRINTED, command=PRINTED, message=PRINTED, files=PRINTED),
        _sent("toolu_r1"),
        _assistant_text(DONE),
        line=line,
    )
    r = _run(tmp_path, rows)
    assert _blocks(r)
    assert "reply tool line ignored" in r.stderr


@pytest.mark.parametrize("link_in", ["send", "control-text"])
def test_a_send_carrying_a_link_does_not_change_the_delivery_check(tmp_path: Path, link_in: str) -> None:
    """D1 (a decision pin). The delivery half reads plain text and the host's own delivery tools only: a reply
    send carrying a `computer://` link, with `SendUserFile` offered, is not asked to attach. Control: the same
    link in plain text is asked, so the delivery check is live in this transcript."""
    _handover(tmp_path)
    link = "\n[the written report](computer:///out/X.md)"
    send_text = PRINTED + (link if link_in == "send" else "")
    rows = [
        base._snapshot("mcp__workspace__bash", "SendUserFile"),
        _user(f"Size this market.\n{REPLY_LINE}"),
        _call_with_id("mcp__workspace__bash", base.CLOSING_CMD, "toolu_close"),
        _result_for("toolu_close", PRINTED),
        _assistant_send(REPLY_NAME, "toolu_r1", text=send_text),
        _sent("toolu_r1"),
        _assistant_text(DONE + (link if link_in != "send" else "")),
    ]
    r = _run(tmp_path, rows)
    if link_in == "send":
        assert r.stdout == "", r.stdout
    else:
        assert _blocks(r, "attach")


# --- the hook's copy of the line's rules ----------------------------------------------------------------------


def _load(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_hooks_reply_line_rules_are_the_registrys() -> None:
    """The hook cannot load `_gates.py`, so it carries its own copy of the line's shape and refused names."""
    hook = base._load_hook()
    if str(base.SCRIPTS) not in sys.path:
        sys.path.append(str(base.SCRIPTS))
    gates = sys.modules.get("_gates") or _load("_gates", base.SCRIPTS / "_gates.py")
    delivery = hook._load_delivery()
    assert hook.REPLY_TOOL_NAME_RE.pattern == gates.REPLY_TOOL_NAME_RE.pattern
    assert hook.REPLY_TOOL_KEY_RE.pattern == gates.REPLY_TOOL_KEY_RE.pattern
    assert hook.REPLY_TOOL_REFUSED == gates.REPLY_TOOL_REFUSED
    assert set(delivery.SHELL_TOOLS) <= set(gates.REPLY_TOOL_REFUSED)
    assert set(gates.REPLY_TOOL_SKILLS) == {row[0] for row in hook.SKILLS}
    for name in ("mcp__cowork__present_files", "SendUserFile", "mcp__x__present_files_now", REPLY_NAME, "Write"):
        assert (gates.reply_tool_name_problem(name) is None) == (hook.reply_tool_name_problem(name) is None), name
        refused = name in gates.REPLY_TOOL_REFUSED or delivery.is_delivery_tool(name)
        assert (gates.reply_tool_name_problem(name) is not None) == refused, name


# --- the contract side: parse, record, check, notices -----------------------------------------------------------


def _gates() -> Any:
    if str(h.SHARED) not in sys.path:
        sys.path.append(str(h.SHARED))
    return sys.modules.get("_gates") or _load("_gates", h.SHARED / "_gates.py")


RID = "20261016T120000Z-0d0e0f"


def test_the_line_is_a_request_token_in_the_contract() -> None:
    g = _gates()
    assert g.REQUEST_TOKENS["reply_tool"] == "FS_HOST_REPLY_TOOL <tool_name> <input_key>"
    contract = json.loads((h.SHARED.parent / "data" / "host-contract.json").read_text(encoding="utf-8"))
    assert contract["request_tokens"]["reply_tool"] == g.REQUEST_TOKENS["reply_tool"]
    note = next(n for n in contract["notes"] if n.startswith("`FS_HOST_REPLY_TOOL"))
    assert "before 0.22 refuse the line" in note and "`run_status.py check`" in note
    assert "never from the run's records" in note


def test_the_line_parses_and_the_last_one_wins() -> None:
    g = _gates()
    text = f"FS_HOST_REPLY_TOOL mcp__other__tool text\n{REPLY_LINE}\n"
    _rid, _pre, bad, flags = g.parse_request(text, "market-sizing")
    assert bad == []
    assert flags["reply_tool"] == {"name": REPLY_NAME, "key": "text", "raw": REPLY_LINE}
    assert g.parse_request("FS_HOST_RUN_ID=x1\n", "market-sizing")[3]["reply_tool"] is None


@pytest.mark.parametrize(
    "line",
    [
        "FS_HOST_REPLY_TOOL",
        f"FS_HOST_REPLY_TOOL {REPLY_NAME}",
        f"FS_HOST_REPLY_TOOL {REPLY_NAME} text extra",
        f"FS_HOST_REPLY_TOOL={REPLY_NAME} text",
        "FS_HOST_REPLY_TOOL mcp__host.chat__reply text",
        "FS_HOST_REPLY_TOOL " + "x" * 129 + " text",
        f"FS_HOST_REPLY_TOOL {REPLY_NAME} 1text",
        f"FS_HOST_REPLY_TOOL {REPLY_NAME} te-xt",
        "FS_HOST_REPLY_TOOL Bash command",
        "FS_HOST_REPLY_TOOL mcp__workspace__bash command",
        "FS_HOST_REPLY_TOOL Agent prompt",
        "FS_HOST_REPLY_TOOL Task prompt",
        "FS_HOST_REPLY_TOOL AskUserQuestion questions",
        "FS_HOST_REPLY_TOOL SendMessage message",
        "FS_HOST_REPLY_TOOL SendUserFile files",
        "FS_HOST_REPLY_TOOL mcp__cowork__present_files files",
    ],
)
def test_every_bad_shape_or_refused_name_is_invalid(line: str) -> None:
    _rid, _pre, bad, flags = _gates().parse_request(line + "\n", "market-sizing")
    assert [b["line"] for b in bad] == [line] and flags["reply_tool"] is None


def test_start_records_the_line_and_a_later_line_replaces_it(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    lines = f"FS_HOST_RUN_ID={RID}\n{REPLY_LINE}\n"
    assert h.start_ok(root, "market-sizing", lines) == RID
    rec = h.ledger(root, RID)["reply_tool"]
    assert (rec["name"], rec["key"], rec["raw"], rec["by"]) == (REPLY_NAME, "text", REPLY_LINE, "run_status.py")
    assert "not_used_by_skill" not in rec
    # Open a question so the run waits: its resume repeats the recorded line, and a later line replaces it.
    opened = h.record(root, RID, "open", "--gate", "ms_methodology")
    assert h.status(root, RID)["status"] == "waiting", opened.stdout + opened.stderr
    assert REPLY_LINE in h.status(root, RID)["resume_prompt"]
    newer = "FS_HOST_REPLY_TOOL mcp__hostchat__post body"
    proc = h.start(root, "market-sizing", f"FS_HOST_RUN_ID={RID}\n{newer}\n")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert h.ledger(root, RID)["reply_tool"]["raw"] == newer


def test_start_refuses_a_bad_line(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    proc = h.start(root, "market-sizing", f"FS_HOST_RUN_ID={RID}\nFS_HOST_REPLY_TOOL Bash command\n")
    assert proc.returncode == 1 and json.loads(proc.stdout)["code"] == "PRE_ANSWER_INVALID"


@pytest.mark.parametrize(
    ("skill", "verdict", "code"),
    [
        ("market-sizing", "applies", 0),
        ("competitive-positioning", "applies", 0),
        ("financial-model-review", "applies", 0),
        ("deck-review", "not_used_by_skill", 0),
        ("ic-sim", "not_used_by_skill", 0),
        ("cap-table", "not_used_by_skill", 0),
    ],
)
def test_check_reads_the_line_per_skill(skill: str, verdict: str, code: int) -> None:
    proc = h.run(h.RUN_STATUS, "check", "--skill", skill, stdin=f"{REPLY_LINE}\n")
    assert proc.returncode == code, proc.stdout + proc.stderr
    rows = [v for v in json.loads(proc.stdout)["values"] if v.get("line") == REPLY_LINE]
    assert rows == [{"gate": None, "line": REPLY_LINE, "verdict": verdict}]


def test_check_exits_1_on_a_bad_line() -> None:
    proc = h.run(h.RUN_STATUS, "check", "--skill", "market-sizing", stdin="FS_HOST_REPLY_TOOL SendMessage message\n")
    assert proc.returncode == 1 and json.loads(proc.stdout)["invalid"][0]["line"].startswith("FS_HOST_REPLY_TOOL")


@pytest.mark.parametrize(("skill", "listed"), [("deck-review", True), ("market-sizing", False)])
def test_a_skill_with_no_judged_closer_lists_the_line_not_used(tmp_path: Path, skill: str, listed: bool) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    assert h.start_ok(root, skill, f"FS_HOST_RUN_ID={RID}\n{REPLY_LINE}\n") == RID
    done = h.run(h.RUN_STATUS, "fail", "--run-id", RID, "--artifacts-root", str(root), "--code",
                 "PRODUCER_FAILED", "--reason", "x")  # fmt: skip
    assert done.returncode == 0, done.stdout + done.stderr
    notices = [n for n in h.status(root, RID)["notices"] if n.get("lines") == [REPLY_LINE]]
    want = [{"code": "PRE_ANSWER_IGNORED", "gate": None, "lines": [REPLY_LINE], "reason": "not_used_by_skill"}]
    assert notices == (want if listed else [])
