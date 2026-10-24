"""Which tools each paid lane's session may use: the base list, plus WebFetch on the market-sizing smoke only.

The market-sizing lane opens the pages its sized figures rest on, so it needs WebFetch; the other lanes keep
the base list, so a tool added for one lane does not widen the rest. Free: it builds options and reads lane
source, and never starts a session.
"""

from __future__ import annotations

import ast
from pathlib import Path

import _e2e_harness
import pytest

_TESTS = Path(__file__).resolve().parent

pytest.importorskip("claude_agent_sdk")


def test_the_base_list_is_unchanged_without_extra_tools(tmp_path: Path) -> None:
    opts = _e2e_harness.build_options(tmp_path)
    assert list(opts.allowed_tools) == list(_e2e_harness.BASE_ALLOWED_TOOLS)
    assert "WebFetch" not in opts.allowed_tools


def test_extra_tools_are_added_to_the_base_list(tmp_path: Path) -> None:
    opts = _e2e_harness.build_options(tmp_path, None, ("WebFetch",))
    assert list(opts.allowed_tools) == [*_e2e_harness.BASE_ALLOWED_TOOLS, "WebFetch"]


def _extra_tools_by_caller() -> dict[str, list[str]]:
    """`extra_tools=` passed to `run_skill_capture`, per enclosing test function, across every lane file."""
    out: dict[str, list[str]] = {}
    for path in sorted(_TESTS.glob("test_e2e_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for fn in ast.walk(tree):
            if not isinstance(fn, ast.FunctionDef):
                continue
            for call in ast.walk(fn):
                if not (isinstance(call, ast.Call) and getattr(call.func, "id", None) == "run_skill_capture"):
                    continue
                for kw in call.keywords:
                    if kw.arg == "extra_tools":
                        out.setdefault(f"{path.name}::{fn.name}", []).extend(ast.literal_eval(kw.value))
    return out


def test_only_the_market_sizing_smoke_gets_webfetch() -> None:
    callers = _extra_tools_by_caller()
    assert list(callers.values()) == [["WebFetch"]], callers
    (caller,) = callers
    lane_file, function = caller.split("::")
    assert lane_file == "test_e2e_market_sizing.py" and function.endswith("_smoke"), caller
