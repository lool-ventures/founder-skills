"""Each paid lane writes its SDK stream to its run folder, whether the lane passes or fails.

Free: `claude_agent_sdk.query` is replaced with a fake async generator, so nothing calls the model. A lane
that fails leaves nothing but its assertion text, and the runner's workspace is destroyed with the job; the
stream file beside `workspace/` is collected by the workflow's `pytest/**/artifacts/**` upload.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

TESTS = Path(__file__).resolve().parent

pytest.importorskip("claude_agent_sdk")


def _load(name: str) -> Any:
    if str(TESTS) not in sys.path:
        sys.path.insert(0, str(TESTS))
    spec = importlib.util.spec_from_file_location(f"_stream_{name}", TESTS / f"{name}.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def harness() -> Any:
    return _load("_e2e_harness")


@pytest.fixture
def deck_lane() -> Any:
    return _load("test_e2e_deck_review")


def _workspace(tmp_path: Path) -> Path:
    workdir = tmp_path / "workspace"
    workdir.mkdir()
    return workdir


def _lines(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _fake(messages: list[Any], then_raise: Exception | None = None) -> Any:
    async def fake(*, prompt: str, options: Any) -> AsyncIterator[Any]:
        for m in messages:
            yield m
        if then_raise is not None:
            raise then_raise

    return fake


def _assistant(text: str) -> Any:
    from claude_agent_sdk import AssistantMessage, TextBlock

    return AssistantMessage(content=[TextBlock(text=text)], model="m")


def test_path_is_beside_the_workspace_not_in_the_skills_artifacts_root(harness: Any, tmp_path: Path) -> None:
    workdir = _workspace(tmp_path)
    path = harness.sdk_stream_path(workdir, "lane")
    assert path == tmp_path / "artifacts" / "sdk-stream-lane.jsonl"
    assert workdir / "artifacts" not in path.parents


def test_a_failing_lane_still_leaves_the_stream(harness: Any, tmp_path: Path, monkeypatch: Any) -> None:
    import claude_agent_sdk

    workdir = _workspace(tmp_path)
    msgs = [_assistant("one"), _assistant("two"), _assistant("three")]
    monkeypatch.setattr(claude_agent_sdk, "query", _fake(msgs))
    # No init message, so the connector check has no tool list and the lane fails.
    with pytest.raises(AssertionError, match="tool list"):
        harness.run_skill_capture("probe", workdir, label="probe")
    rows = _lines(harness.sdk_stream_path(workdir, "probe"))
    assert [r["n"] for r in rows] == [1, 2, 3]
    assert all(r["type"] == "AssistantMessage" for r in rows)
    assert "one" in rows[0]["text"]


def test_a_stream_that_raises_midway_keeps_what_was_written_and_an_error_line(
    harness: Any, tmp_path: Path, monkeypatch: Any
) -> None:
    import claude_agent_sdk

    workdir = _workspace(tmp_path)
    monkeypatch.setattr(claude_agent_sdk, "query", _fake([_assistant("a"), _assistant("b")], RuntimeError("boom")))
    with pytest.raises(RuntimeError, match="boom"):
        harness.run_skill_capture("probe", workdir, label="probe")
    rows = _lines(harness.sdk_stream_path(workdir, "probe"))
    assert [r.get("n") for r in rows[:2]] == [1, 2]
    assert rows[-1]["error"] == "RuntimeError: boom"
    assert rows[-1]["after_messages"] == 2
    assert len(rows) == 3


def test_credentials_are_replaced_by_name_pattern(harness: Any, tmp_path: Path, monkeypatch: Any) -> None:
    import claude_agent_sdk

    secrets = {
        "ANTHROPIC_API_KEY": "sk-ant-fake-aaaaaaaaaaaaaaaa",
        "CLAUDE_CODE_OAUTH_TOKEN": "oat-fake-bbbbbbbbbbbbbbbb",
        "SOME_SERVICE_PASSWORD": "pw-fake-cccccccccccccccc",
        "MY_CLIENT_SECRET": "cs-fake-dddddddddddddddd",
        "PROXY_AUTH": "auth-fake-eeeeeeeeeeeeeeee",
    }
    for k, v in secrets.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("HARMLESS_NAME", "plain-value-that-stays-visible")
    workdir = _workspace(tmp_path)
    body = " | ".join([*secrets.values(), "plain-value-that-stays-visible"])
    monkeypatch.setattr(claude_agent_sdk, "query", _fake([_assistant(body)], RuntimeError(secrets["PROXY_AUTH"])))
    with pytest.raises(RuntimeError):
        harness.run_skill_capture("probe", workdir, label="probe")
    raw = harness.sdk_stream_path(workdir, "probe").read_text(encoding="utf-8")
    for v in secrets.values():
        assert v not in raw
    assert raw.count("[REDACTED]") >= len(secrets) + 1
    assert "plain-value-that-stays-visible" in raw


def test_the_deck_review_lane_leaves_the_stream_when_it_fails_at_no_artifacts(
    deck_lane: Any, tmp_path: Path, monkeypatch: Any
) -> None:
    import claude_agent_sdk
    from claude_agent_sdk import SystemMessage

    init = SystemMessage(subtype="init", data={"tools": ["Bash", "Read"], "mcp_servers": []})
    monkeypatch.setattr(claude_agent_sdk, "query", _fake([init, _assistant("hello")]))
    with pytest.raises(AssertionError, match="no artifacts"):
        deck_lane._drive_deck_review_lane(
            tmp_path,
            deck_fixture=deck_lane.CONTRADICTION_DECK,
            golden_path=deck_lane.CONTRADICTION_GOLDEN,
            company="Probe Co",
            slug="probe-co",
            lane="probe-lane",
        )
    rows = _lines(tmp_path / "artifacts" / "sdk-stream-probe-lane.jsonl")
    assert [r["type"] for r in rows] == ["SystemMessage", "AssistantMessage"]
