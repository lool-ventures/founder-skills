"""The end-to-end lanes run with the account's claude.ai connectors switched off, and check it.

Free: nothing here calls the model. The SDK's `query` is replaced with a fake stream where a run is
needed, so the lanes' own post-run check is exercised without spending anything.

Why this exists: the SDK lane spawns the CLI as the signed-in user, and `setting_sources=[]` does not
stop that CLI from loading the account's claude.ai connectors (mail, drive, chat and the like). A
catch-all sub-agent in such a session can call them. The switch is the CLI's own
`ENABLE_CLAUDEAI_MCP_SERVERS`, read by a predicate that treats `0/false/no/off` as "disabled"; the lanes
also pass `--strict-mcp-config` with no servers, so no other MCP config is picked up either.

Each test asks what the code BUILDS or DOES, never whether a string appears in a file: a grep stays
green when the line that enforces it is deleted and a comment mentioning it survives.
"""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

TESTS = Path(__file__).resolve().parent
# What the bundled CLI's predicate accepts as "disabled" (lower-cased, trimmed).
_DISABLED_VALUES = {"0", "false", "no", "off"}
_SWITCH = "ENABLE_CLAUDEAI_MCP_SERVERS"


def _load(name: str) -> Any:
    spec = importlib.util.spec_from_file_location(f"_iso_{name}", TESTS / f"{name}.py")
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
    if str(TESTS) not in sys.path:
        sys.path.insert(0, str(TESTS))
    return _load("test_e2e_deck_review")


def _assert_isolated(options: Any) -> None:
    value = str(options.env.get(_SWITCH, "")).strip().lower()
    assert value in _DISABLED_VALUES, f"{_SWITCH}={options.env.get(_SWITCH)!r}: account connectors would load"
    assert options.strict_mcp_config is True, "strict MCP config is off: other MCP configs would load"
    assert options.mcp_servers in ({}, None), f"MCP servers configured: {options.mcp_servers!r}"


def test_shared_harness_options_switch_connectors_off(harness: Any, tmp_path: Path, monkeypatch: Any) -> None:
    # A caller environment that turns them ON must not win, nor may a lane's own extras.
    monkeypatch.setenv(_SWITCH, "true")
    _assert_isolated(harness.build_options(tmp_path))
    _assert_isolated(harness.build_options(tmp_path, {_SWITCH: "1"}))


def test_deck_review_lane_options_switch_connectors_off(deck_lane: Any, tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setenv(_SWITCH, "true")
    _assert_isolated(deck_lane._deck_review_options(tmp_path, TESTS.parents[1] / "founder-skills"))


def test_connector_check_flags_every_place_a_connector_can_show(harness: Any) -> None:
    check = harness.assert_no_account_connectors
    clean = ["Bash", "Read", "Task", "mcp__plugin_other__tool"]
    check(clean, ["Bash", "Read"], [])
    with pytest.raises(AssertionError, match="connector"):
        check([*clean, "mcp__claude_ai_Gmail__search_threads"], [], [])
    with pytest.raises(AssertionError, match="connector"):
        check(clean, ["mcp__claude_ai_Google_Drive__read_file_content"], [])
    with pytest.raises(AssertionError, match="connector"):
        check(clean, [], [{"name": "claude.ai Slack", "status": "connected"}])
    # No tool list recorded: the check cannot have looked, so it must not pass.
    with pytest.raises(AssertionError, match="tool list"):
        check(None, [], [])
    with pytest.raises(AssertionError, match="tool list"):
        check([], [], [])


def _fake_query(tools: list[str], servers: list[dict[str, str]]) -> Any:
    from claude_agent_sdk import SystemMessage

    async def fake(*, prompt: str, options: Any) -> AsyncIterator[Any]:
        yield SystemMessage(subtype="init", data={"tools": tools, "mcp_servers": servers})

    return fake


def test_shared_harness_run_fails_when_a_connector_loaded(harness: Any, tmp_path: Path, monkeypatch: Any) -> None:
    import claude_agent_sdk

    workdir = tmp_path / "workspace"
    workdir.mkdir()
    monkeypatch.setattr(claude_agent_sdk, "query", _fake_query(["Bash", "mcp__claude_ai_Gmail__send_message"], []))
    with pytest.raises(AssertionError, match="connector"):
        harness.run_skill_capture("probe", workdir, label="probe")
    # The clean stream passes the check (and returns the capture).
    monkeypatch.setattr(claude_agent_sdk, "query", _fake_query(["Bash", "Read"], []))
    cap = harness.run_skill_capture("probe", workdir, label="probe")
    assert cap.session_tools == ["Bash", "Read"]


def test_deck_review_lane_fails_when_a_connector_loaded(deck_lane: Any, tmp_path: Path, monkeypatch: Any) -> None:
    import claude_agent_sdk

    monkeypatch.setattr(
        claude_agent_sdk, "query", _fake_query(["Bash"], [{"name": "claude.ai Gmail", "status": "connected"}])
    )
    with pytest.raises(AssertionError, match="connector"):
        deck_lane._drive_deck_review_lane(
            tmp_path,
            deck_fixture=deck_lane.CONTRADICTION_DECK,
            golden_path=deck_lane.CONTRADICTION_GOLDEN,
            company="Probe Co",
            slug="probe-co",
        )
