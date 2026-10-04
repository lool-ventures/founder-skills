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
