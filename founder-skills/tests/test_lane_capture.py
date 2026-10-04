"""The shared end-to-end harness: the options it builds and what it records from a run.

Free: nothing here calls the model. Where a run is needed, the SDK's `query` is replaced with a fake
stream of the SDK's own message objects, so the harness's real loop is exercised.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

TESTS = Path(__file__).resolve().parent


@pytest.fixture
def harness() -> Any:
    spec = importlib.util.spec_from_file_location("_capture_harness", TESTS / "_e2e_harness.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_shared_options_deny_the_catch_all_agent_under_both_tool_names(harness: Any, tmp_path: Path) -> None:
    options = harness.build_options(tmp_path)
    assert "Agent(claude)" in options.disallowed_tools
    assert "Task(claude)" in options.disallowed_tools
    # The deny list must not reach any tool the skills use.
    assert not set(options.disallowed_tools) & set(options.allowed_tools)


def test_the_sdk_passes_the_deny_list_to_the_cli(harness: Any, tmp_path: Path) -> None:
    from claude_agent_sdk._internal.transport.subprocess_cli import SubprocessCLITransport

    # Private SDK surface on purpose: a bump that stops passing the list fails here, for free.
    transport = SubprocessCLITransport(prompt="probe", options=harness.build_options(tmp_path))
    transport._cli_path = "claude"
    cmd = transport._build_command()
    flag = cmd.index("--disallowedTools")
    assert set(cmd[flag + 1].split(",")) == {"Agent(claude)", "Task(claude)"}


def _dispatch(tool_id: str, prompt: str) -> Any:
    from claude_agent_sdk import AssistantMessage, ToolUseBlock

    block = ToolUseBlock(id=tool_id, name="Agent", input={"prompt": prompt, "subagent_type": "probe"})
    return AssistantMessage(content=[block], model="probe-model")


def _block(call: str, **fields: Any) -> Any:
    from claude_agent_sdk import ToolResultBlock

    return ToolResultBlock(call, **fields)


def _user(blocks: list[Any], **fields: Any) -> Any:
    from claude_agent_sdk import UserMessage

    return UserMessage(blocks, **fields)


def _result(
    call: str, *, is_error: bool = False, structured: dict[str, Any] | None = None, content: Any = "text"
) -> Any:
    return _user([_block(call, content=content, is_error=is_error)], tool_use_result=structured)


def _init(version: Any = "2.1.286") -> Any:
    from claude_agent_sdk import SystemMessage

    data: dict[str, Any] = {"tools": ["Bash", "Agent"], "mcp_servers": [], "model": "probe-model"}
    if version is not None:
        data["claude_code_version"] = version
    return SystemMessage(subtype="init", data=data)


def _run(harness: Any, tmp_path: Path, monkeypatch: Any, stream: list[Any]) -> Any:
    import claude_agent_sdk

    async def fake(*, prompt: str, options: Any) -> Any:
        for msg in stream:
            yield msg

    monkeypatch.setattr(claude_agent_sdk, "query", fake)
    return harness.run_skill_capture("probe", tmp_path, label="probe")


PRINTED = "CONTEXT: PROBE\nOUTPUT_PATH: /x/out.json\nDo NOT write any file other than OUTPUT_PATH.\n"
OTHER_PATH = PRINTED.replace("/x/out.json", "/y/out.json")
HOLD = "[dispatch-check][/x/out.json] Held: the prompt differs. Send this as the prompt, unchanged:\n\n" + PRINTED


def _generator(call: str, stdout: str, *, script: str = "dispatch_prompt.py", is_error: bool = False) -> list[Any]:
    """A main-thread shell call to a prompt generator and its result."""
    from claude_agent_sdk import AssistantMessage, ToolUseBlock

    command = f'python3 "$SCRIPTS/{script}" probe --run-id "$RUN_ID"'
    use = AssistantMessage(content=[ToolUseBlock(id=call, name="Bash", input={"command": command})], model="m")
    return [use, _result(call, is_error=is_error, content=stdout)]


def _stream() -> list[Any]:
    from claude_agent_sdk import AssistantMessage, ToolUseBlock

    return [
        _init(),
        *_generator("gen", PRINTED),
        # Held by the hook: an error result carrying the hook's reason, no structured record.
        _dispatch("held", PRINTED + "Key things worth attacking: ...\n"),
        _result("held", is_error=True, content=HOLD),
        # Went through, with the CLI's record of what the sub-agent was sent.
        _dispatch("ok", PRINTED),
        _result("ok", structured={"status": "completed", "prompt": PRINTED}),
        # The sub-agent's own call and result: keyed by their own id, parented to the dispatch.
        AssistantMessage(
            content=[ToolUseBlock(id="sub-read", name="Read", input={"file_path": "/x"})],
            model="probe-model",
            parent_tool_use_id="ok",
        ),
        _user([_block("sub-read")], parent_tool_use_id="ok"),
        # Went through with no prompt in its record.
        _dispatch("bare", PRINTED),
        _result("bare", structured={"status": "completed"}),
        # An error that is not a hold: the sub-agent itself failed.
        _dispatch("broke", PRINTED),
        _result("broke", is_error=True, content="Agent stopped: API Error: overloaded"),
        # Two results in one message: the structured record belongs to neither for certain.
        _user([_block("a"), _block("b", is_error=True)], tool_use_result={"prompt": "?"}),
        # Sent, never answered.
        _dispatch("lost", PRINTED),
    ]


def test_the_capture_records_each_result_by_its_call(harness: Any, tmp_path: Path, monkeypatch: Any) -> None:
    cap = _run(harness, tmp_path, monkeypatch, _stream())
    assert cap.cli_version == "2.1.286"
    assert cap.model == "probe-model"
    assert cap.result("held")["is_error"] is True
    assert cap.result("held")["tool_use_result"] is None
    assert cap.result("ok")["is_error"] is False
    assert cap.result("ok")["tool_use_result"]["prompt"] == PRINTED
    assert cap.result("ok")["parent_tool_use_id"] is None
    assert cap.result("sub-read")["parent_tool_use_id"] == "ok"
    assert cap.result("lost") is None
    # A message-level record over two result blocks is kept, never attached to either.
    assert cap.result("a")["tool_use_result"] is None and cap.result("b")["tool_use_result"] is None
    assert cap.unattributed_results == [{"tool_use_ids": ["a", "b"], "tool_use_result": {"prompt": "?"}}]


@pytest.mark.parametrize(("version", "expected"), [({"VERSION": "2.1.290"}, "2.1.290"), (None, None)])
def test_the_cli_version_is_read_in_either_shape(
    harness: Any, tmp_path: Path, monkeypatch: Any, version: Any, expected: str | None
) -> None:
    assert _run(harness, tmp_path, monkeypatch, [_init(version)]).cli_version == expected


def _report(harness: Any, tmp_path: Path, monkeypatch: Any, stream: list[Any]) -> dict[str, Any]:
    cap = _run(harness, tmp_path, monkeypatch, stream)
    report: dict[str, Any] = harness.dispatch_report(
        cap, [t for t in cap.tool_uses if t["name"] == "Agent"], "dispatch_prompt.py"
    )
    return report


def _rows(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {r["id"]: r for r in report["dispatches"]}


def test_the_dispatch_report_tells_a_hold_from_a_failure(harness: Any, tmp_path: Path, monkeypatch: Any) -> None:
    report = _report(harness, tmp_path, monkeypatch, _stream())
    rows = _rows(report)
    assert (report["held"], report["failed"], report["succeeded"], report["no_result"]) == (1, 1, 2, 1)
    assert rows["held"]["status"] == "held" and rows["held"]["sent_matches"] is False
    assert rows["broke"]["status"] == "failed"
    assert rows["ok"]["sent_matches"] is True and rows["ok"]["received_matches"] is True
    assert rows["lost"]["status"] == "no_result"
    assert report["succeeded_without_received_prompt"] == ["bare"]
    assert report["rewrites"] == 0
    text = harness.format_dispatch_report("PROBE", report)
    assert "NO RECEIVED PROMPT" in text and "bare" in text
    assert "1 failed" in text
    assert "CLI `2.1.286`" in text and "model `probe-model`" in text


@pytest.mark.parametrize(
    "content",
    [
        "[dispatch-type][/x/out.json] Held: a CONTEXT: PROBE dispatch goes to its own agent",
        "[two-figures-check][TOP_DOWN] Before sizing, ask which figure to use",
        "PreToolUse:Agent hook error: the hook exited 2",
        [{"type": "text", "text": HOLD}],
    ],
)
def test_every_hook_hold_shape_reads_as_held(harness: Any, tmp_path: Path, monkeypatch: Any, content: Any) -> None:
    stream = [
        _init(),
        *_generator("gen", PRINTED),
        _dispatch("h", PRINTED + "x\n"),
        _result("h", is_error=True, content=content),
    ]
    assert _rows(_report(harness, tmp_path, monkeypatch, stream))["h"]["status"] == "held"


def test_the_printed_prompt_is_the_generator_calls_own_output(harness: Any, tmp_path: Path, monkeypatch: Any) -> None:
    corrected = PRINTED.replace("Do NOT", "Your previous receipt was wrong.\nDo NOT")
    stream = [
        _init(),
        # A compound block: another script's receipt is printed before the prompt.
        *_generator("g1", '{"ocr_available": false}\n' + PRINTED),
        # A later call for another hand-off path does not replace it.
        *_generator("g2", OTHER_PATH),
        # Nor does a failed call, nor another script's output.
        *_generator("g3", corrected, is_error=True),
        *_generator("g4", corrected, script="closing_message.py"),
        # A name that merely ends in the generator's is another generator.
        *_generator("g4b", corrected, script="fmr_dispatch_prompt.py"),
        _dispatch("d1", PRINTED),
        _result("d1", structured={"prompt": PRINTED}),
        # A redo: the latest successful call before the dispatch is what it is judged against.
        *_generator("g5", corrected),
        _dispatch("d2", corrected),
        _result("d2", structured={"prompt": corrected}),
        # A call after the dispatch is never used for it.
        _dispatch("d3", PRINTED.replace("/x/", "/z/")),
        _result("d3", structured={"prompt": "?"}),
        *_generator("g6", PRINTED.replace("/x/", "/z/")),
    ]
    rows = _rows(_report(harness, tmp_path, monkeypatch, stream))
    assert rows["d1"]["sent_matches"] is True
    assert rows["d2"]["sent_matches"] is True and rows["d2"]["received_matches"] is True
    assert rows["d3"]["sent_matches"] is None
    assert "/z/out.json" in rows["d3"]["regenerate_error"]


def test_the_structured_stdout_is_preferred_over_the_rendered_result(
    harness: Any, tmp_path: Path, monkeypatch: Any
) -> None:
    from claude_agent_sdk import AssistantMessage, ToolUseBlock

    command = 'python3 "$SCRIPTS/dispatch_prompt.py" red_team'
    stream = [
        _init(),
        AssistantMessage(content=[ToolUseBlock(id="g", name="Bash", input={"command": command})], model="m"),
        _result("g", content="(output persisted to a file)", structured={"stdout": PRINTED, "stderr": ""}),
        _dispatch("d", PRINTED),
        _result("d", structured={"prompt": PRINTED}),
    ]
    assert _rows(_report(harness, tmp_path, monkeypatch, stream))["d"]["sent_matches"] is True


def test_a_rewritten_dispatch_is_counted_as_one(harness: Any, tmp_path: Path, monkeypatch: Any) -> None:
    stream = [
        _init(),
        *_generator("gen", PRINTED),
        _dispatch("rw", PRINTED + "an added line\n"),
        _result("rw", structured={"prompt": PRINTED}),
    ]
    report = _report(harness, tmp_path, monkeypatch, stream)
    assert report["rewrites"] == 1
    assert report["dispatches"][0]["sent_matches"] is False
    assert report["dispatches"][0]["received_matches"] is True


def test_dispatch_outcomes_fail_on_a_failure_or_a_held_printed_prompt(
    harness: Any, tmp_path: Path, monkeypatch: Any
) -> None:
    clean = [
        _init(),
        *_generator("gen", PRINTED),
        _dispatch("h", PRINTED + "x\n"),
        _result("h", is_error=True, content=HOLD),
        _dispatch("ok", PRINTED),
        _result("ok", structured={"prompt": PRINTED}),
    ]
    harness.assert_dispatch_outcomes(_report(harness, tmp_path, monkeypatch, clean), "PROBE")

    # Held before any prompt was printed: a legitimate hold ("run the generator").
    early = [_init(), _dispatch("h", PRINTED), _result("h", is_error=True, content=HOLD)]
    harness.assert_dispatch_outcomes(_report(harness, tmp_path, monkeypatch, early), "PROBE")

    failed = [*clean, _dispatch("f", PRINTED), _result("f", is_error=True, content="API Error: overloaded")]
    with pytest.raises(AssertionError, match="failed"):
        harness.assert_dispatch_outcomes(_report(harness, tmp_path, monkeypatch, failed), "PROBE")

    false_hold = [*clean, _dispatch("fh", PRINTED), _result("fh", is_error=True, content=HOLD)]
    with pytest.raises(AssertionError, match="held a dispatch that sent the printed prompt"):
        harness.assert_dispatch_outcomes(_report(harness, tmp_path, monkeypatch, false_hold), "PROBE")


def test_prompts_compare_with_whitespace_squashed(harness: Any) -> None:
    assert harness.same_prompt("a  b\n", "a b")
    assert not harness.same_prompt("a b", "a b c")


def test_the_received_prompt_gate_ships_off(harness: Any) -> None:
    assert harness.RECEIVED_PROMPT_GATE_ENABLED is False


def test_the_gate_does_nothing_while_off(harness: Any, tmp_path: Path, monkeypatch: Any) -> None:
    report = _report(harness, tmp_path, monkeypatch, [_init(), _dispatch("x", "other"), _result("x", structured={})])
    harness.assert_received_prompt(report, "PROBE")
    harness.assert_received_prompt(report, "PROBE", enabled=False)


def test_the_gate_judges_what_was_received(harness: Any, tmp_path: Path, monkeypatch: Any) -> None:
    gen = [_init(), *_generator("gen", PRINTED)]

    rewritten = [*gen, _dispatch("rw", PRINTED + "added\n"), _result("rw", structured={"prompt": PRINTED})]
    harness.assert_received_prompt(_report(harness, tmp_path, monkeypatch, rewritten), "PROBE", enabled=True)

    altered = [*gen, _dispatch("al", PRINTED), _result("al", structured={"prompt": PRINTED + "added\n"})]
    with pytest.raises(AssertionError, match="did not receive the printed prompt"):
        harness.assert_received_prompt(_report(harness, tmp_path, monkeypatch, altered), "PROBE", enabled=True)

    unrecorded = [*gen, _dispatch("un", PRINTED), _result("un", structured={"status": "completed"})]
    with pytest.raises(AssertionError, match="no received prompt"):
        harness.assert_received_prompt(_report(harness, tmp_path, monkeypatch, unrecorded), "PROBE", enabled=True)

    held_only = [*gen, _dispatch("h", PRINTED), _result("h", is_error=True, content=HOLD)]
    with pytest.raises(AssertionError, match="went through"):
        harness.assert_received_prompt(_report(harness, tmp_path, monkeypatch, held_only), "PROBE", enabled=True)

    # No printed prompt to judge against: the failure names why.
    unprinted = [_init(), _dispatch("np", PRINTED), _result("np", structured={"prompt": PRINTED})]
    with pytest.raises(AssertionError, match="no successful dispatch_prompt.py call"):
        harness.assert_received_prompt(_report(harness, tmp_path, monkeypatch, unprinted), "PROBE", enabled=True)


# --- the Stop hook's blocks, counted two independent ways ---------------------------------------------


def test_shared_options_ask_the_cli_for_hook_events(harness: Any, tmp_path: Path) -> None:
    assert harness.build_options(tmp_path).include_hook_events is True


def _hook_event(phase: str, **fields: Any) -> Any:
    from claude_agent_sdk.types import HookEventMessage

    data: dict[str, Any] = {"type": "system", "subtype": phase, "hook_event": "Stop", **fields}
    return HookEventMessage(subtype=phase, hook_event_name="Stop", data=data)


def _stop_response(stdout: str, exit_code: int = 0) -> Any:
    outcome = "success" if exit_code == 0 else "error"
    return _hook_event("hook_response", stdout=stdout, output=stdout, exit_code=exit_code, outcome=outcome)


def _stop_started() -> Any:
    return _hook_event("hook_started")


BLOCK = '{"decision": "block", "reason": "Your last message did not carry the hand-over."}\n'


def test_hook_events_are_recorded(harness: Any, tmp_path: Path, monkeypatch: Any) -> None:
    cap = _run(harness, tmp_path, monkeypatch, [_init(), _stop_started(), _stop_response(BLOCK), _stop_response("")])
    assert [(e["event"], e["subtype"]) for e in cap.hook_events] == [
        ("Stop", "hook_started"),
        ("Stop", "hook_response"),
        ("Stop", "hook_response"),
    ]
    assert cap.stop_hook_blocks_from_events() == 1


@pytest.mark.parametrize(
    ("stream_tail", "agrees"),
    [
        # One block, its feedback turn, then a clean final Stop: both counts are 1.
        (["block", "feedback", "clean"], True),
        # No block at all: both 0.
        (["clean"], True),
        # A block exiting 2 instead of printing a decision counts as a block too.
        (["exit2", "feedback", "clean"], True),
        # The hook blocked but no feedback turn reached the stream: the stream count would read 0.
        (["block", "clean"], False),
        # A feedback-looking user turn with no block behind it.
        (["feedback", "clean"], False),
    ],
)
def test_the_stop_block_counts_must_agree(
    harness: Any, tmp_path: Path, monkeypatch: Any, stream_tail: list[str], agrees: bool
) -> None:
    from claude_agent_sdk import UserMessage

    parts = {
        "block": lambda: _stop_response(BLOCK),
        "exit2": lambda: _stop_response("", exit_code=2),
        "clean": lambda: _stop_response(""),
        "feedback": lambda: UserMessage("Stop hook feedback:\nreason"),
    }
    cap = _run(harness, tmp_path, monkeypatch, [_init(), *(parts[k]() for k in stream_tail)])
    if agrees:
        harness.assert_stop_block_evidence_agrees(cap)
    else:
        with pytest.raises(AssertionError, match="Stop hook"):
            harness.assert_stop_block_evidence_agrees(cap)


def test_no_stop_hook_event_means_the_count_was_not_checked(harness: Any, tmp_path: Path, monkeypatch: Any) -> None:
    cap = _run(harness, tmp_path, monkeypatch, [_init()])
    with pytest.raises(AssertionError, match="no Stop hook event"):
        harness.assert_stop_block_evidence_agrees(cap)


def test_the_deck_review_progress_line_names_a_dispatch_under_either_tool_name() -> None:
    from claude_agent_sdk import AssistantMessage, ToolUseBlock

    if str(TESTS) not in sys.path:
        sys.path.insert(0, str(TESTS))
    spec = importlib.util.spec_from_file_location("_capture_deck_lane", TESTS / "test_e2e_deck_review.py")
    assert spec and spec.loader
    lane = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lane)
    for name in ("Task", "Agent"):
        block = ToolUseBlock(id="d", name=name, input={"description": "score slides", "subagent_type": "probe"})
        line = lane._summarize_sdk_message(AssistantMessage(content=[block], model="m"))
        assert f"→ {name}[probe]: score slides" in line, line
