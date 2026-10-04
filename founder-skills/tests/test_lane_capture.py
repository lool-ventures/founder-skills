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


def _result(call: str, *, is_error: bool = False, structured: dict[str, Any] | None = None) -> Any:
    return _user([_block(call, content="text", is_error=is_error)], tool_use_result=structured)


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


def _stream() -> list[Any]:
    from claude_agent_sdk import AssistantMessage, ToolUseBlock

    return [
        _init(),
        # Held by the hook: an error result, no structured record.
        _dispatch("held", PRINTED + "Key things worth attacking: ...\n"),
        _result("held", is_error=True),
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


def test_the_dispatch_report_sorts_held_from_succeeded(harness: Any, tmp_path: Path, monkeypatch: Any) -> None:
    cap = _run(harness, tmp_path, monkeypatch, _stream())
    dispatches = [t for t in cap.tool_uses if t["name"] == "Agent"]
    report = harness.dispatch_report(cap, dispatches, lambda sent: PRINTED)
    by_id = {r["id"]: r for r in report["dispatches"]}
    assert (report["held"], report["succeeded"], report["no_result"]) == (1, 2, 1)
    assert by_id["held"]["status"] == "held" and by_id["held"]["sent_matches"] is False
    assert by_id["ok"]["sent_matches"] is True and by_id["ok"]["received_matches"] is True
    assert by_id["lost"]["status"] == "no_result"
    assert report["succeeded_without_received_prompt"] == ["bare"]
    assert report["rewrites"] == 0
    text = harness.format_dispatch_report("PROBE", report)
    assert "NO RECEIVED PROMPT" in text and "bare" in text
    assert "CLI `2.1.286`" in text and "model `probe-model`" in text


def test_a_rewritten_dispatch_is_counted_as_one(harness: Any, tmp_path: Path, monkeypatch: Any) -> None:
    stream = [
        _init(),
        _dispatch("rw", PRINTED + "an added line\n"),
        _result("rw", structured={"prompt": PRINTED}),
    ]
    cap = _run(harness, tmp_path, monkeypatch, stream)
    report = harness.dispatch_report(cap, cap.tool_uses, lambda sent: PRINTED)
    assert report["rewrites"] == 1
    assert report["dispatches"][0]["sent_matches"] is False
    assert report["dispatches"][0]["received_matches"] is True


def test_a_failed_regeneration_is_reported_not_raised(harness: Any, tmp_path: Path, monkeypatch: Any) -> None:
    cap = _run(harness, tmp_path, monkeypatch, _stream())

    def broken(sent: str) -> str:
        raise ValueError("no RUN_ID line")

    report = harness.dispatch_report(cap, [t for t in cap.tool_uses if t["name"] == "Agent"], broken)
    assert all("no RUN_ID line" in r["regenerate_error"] for r in report["dispatches"])
    assert all(r["sent_matches"] is None for r in report["dispatches"])
    assert "regeneration failed" in harness.format_dispatch_report("PROBE", report)


def test_prompts_compare_with_whitespace_squashed(harness: Any) -> None:
    assert harness.same_prompt("a  b\n", "a b")
    assert not harness.same_prompt("a b", "a b c")
