"""The compaction lane's observables and its completion check, against hand-built streams and artifacts.

Free: no model is called here. The billed compaction lane in the market-sizing e2e file (opt-in) forces a
mid-run compaction and reports C (the run compacted on the main thread), R (the main thread
re-read its SKILL.md after it), F (argparse usage errors after it) and S (the run still completed). Each is
settled here before anyone pays: the SDK's `query` is replaced with a fake stream of the SDK's own message
objects, so the harness's real loop records what the observables read.

Not named `test_e2e_*`: the lane count is pinned, and this file runs in the default suite.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

TESTS = Path(__file__).resolve().parent
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))
import _e2e_harness as harness  # noqa: E402

SKILL_MD = str(TESTS.parent / "skills" / "market-sizing" / "SKILL.md")
NOTE = "If you are the main thread running the founder-skills market-sizing run r1 (status running), ..."


@pytest.fixture(scope="module")
def lane() -> Any:
    spec = importlib.util.spec_from_file_location("_cmp_test_e2e_ms", TESTS / "test_e2e_market_sizing.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _init() -> Any:
    from claude_agent_sdk import SystemMessage

    data = {"tools": ["Bash", "Read"], "mcp_servers": [], "model": "probe-model", "session_id": "sess-1"}
    data["claude_code_version"] = "2.1.286"
    return SystemMessage(subtype="init", data=data)


def _call(call: str, name: str, inp: dict[str, Any], output: str, *, parent: str | None = None) -> list[Any]:
    from claude_agent_sdk import AssistantMessage, ToolResultBlock, ToolUseBlock, UserMessage

    use = AssistantMessage(content=[ToolUseBlock(id=call, name=name, input=inp)], model="m", parent_tool_use_id=parent)
    result = UserMessage([ToolResultBlock(call, content=output, is_error=False)], parent_tool_use_id=parent)
    return [use, result]


def _session_start(stdout: str = "") -> Any:
    from claude_agent_sdk import HookEventMessage

    data = {"hook_event": "SessionStart", "stdout": stdout, "type": "system", "subtype": "hook_response"}
    return HookEventMessage(subtype="hook_response", hook_event_name="SessionStart", data=data, session_id="sess-1")


def _boundary() -> Any:
    from claude_agent_sdk import SystemMessage

    return SystemMessage(subtype="compact_boundary", data={"compact_metadata": {"trigger": "auto"}})


_SEEN: dict[str, Any] = {}  # the options the fake query was called with


def _capture(tmp_path: Path, monkeypatch: Any, stream: list[Any], **kw: Any) -> Any:
    import claude_agent_sdk

    async def fake(*, prompt: str, options: Any) -> Any:
        _SEEN["options"] = options
        for msg in stream:
            yield msg

    monkeypatch.setattr(claude_agent_sdk, "query", fake)
    return harness.run_skill_capture("probe", tmp_path, label="probe", **kw)


START = 'python3 "/p/scripts/run_status.py" start --skill market-sizing --artifacts-root /a'
BARE_FINISH = 'python3 "/p/scripts/run_status.py" finish --run-id r1 --artifacts-root /a'
USAGE = "usage: run_status.py finish ...\nrun_status.py finish: error: the following arguments are required: --mode"


def _stream(*, compacted: bool = True) -> list[Any]:
    before = [
        _init(),
        _session_start(),  # the startup SessionStart: before the first tool call, not a compaction
        *_call("s1", "Bash", {"command": START}, '{"run_id": "r1"}'),
        # Before the compaction: neither counted.
        *_call("r0", "Read", {"file_path": SKILL_MD}, "body"),
        *_call("u0", "Bash", {"command": BARE_FINISH}, USAGE),
    ]
    if not compacted:
        return before
    return [
        *before,
        _boundary(),
        _session_start(json.dumps({"hookSpecificOutput": {"additionalContext": NOTE}})),
        *_call("r1", "Read", {"file_path": SKILL_MD}, "body"),
        *_call("r2", "Bash", {"command": 'sed -n "200,260p" "$PLUGIN_ROOT/skills/market-sizing/SKILL.md"'}, "x"),
        *_call("u1", "Bash", {"command": BARE_FINISH}, USAGE),
        # A non-argparse refusal that exits 2 is not F; a sub-agent's read is not R.
        *_call("c1", "Bash", {"command": 'python3 "$S/closing_message.py" --report r.json'}, "RUN_ID_MISMATCH"),
        *_call("sub", "Read", {"file_path": SKILL_MD}, "body", parent="d1"),
        *_call("s2", "Bash", {"command": START}, '{"run_id": "r1"}'),
    ]


def test_the_capture_records_the_session_the_boundary_and_where_hooks_landed(tmp_path: Path, monkeypatch: Any) -> None:
    cap = _capture(tmp_path, monkeypatch, _stream())
    assert cap.session_id == "sess-1"
    assert cap.cli_version == "2.1.286"
    assert len(cap.compactions) == 1
    assert [ev["at"] for ev in cap.hook_events] == sorted(ev["at"] for ev in cap.hook_events)
    assert len(harness.mid_run_session_starts(cap)) == 1


def test_the_window_reaches_the_cli_environment(tmp_path: Path, monkeypatch: Any) -> None:
    _capture(tmp_path, monkeypatch, [_init()], env_extra={harness.COMPACT_WINDOW_ENV: "100000"})
    assert _SEEN["options"].env[harness.COMPACT_WINDOW_ENV] == "100000"


def test_the_observables_are_keyed_on_the_first_compaction(tmp_path: Path, monkeypatch: Any) -> None:
    cap = _capture(tmp_path, monkeypatch, _stream())
    report = harness.compaction_report(cap, "market-sizing", config_dir=tmp_path / "none")
    assert report["compaction_at"] is not None
    assert report["main_thread_confirmed"] is True  # the stream's own boundary
    assert report["reread_note_emitted"] is True
    assert report["rereads"] == ["r1", "r2"]
    assert len(report["argparse_failures"]) == 1 and "arguments are required" in report["argparse_failures"][0]
    assert report["run_starts"] == 2
    assert "R: 2 main-thread read(s)" in harness.format_compaction_report(report)


def test_a_run_that_never_compacted_measures_nothing(tmp_path: Path, monkeypatch: Any) -> None:
    cap = _capture(tmp_path, monkeypatch, _stream(compacted=False))
    report = harness.compaction_report(cap, "market-sizing", config_dir=tmp_path / "none")
    assert report["compaction_at"] is None and report["main_thread_confirmed"] is False
    assert report["rereads"] == [] and report["argparse_failures"] == []


def test_a_mid_run_session_start_alone_is_c_but_not_confirmed_main_thread(tmp_path: Path, monkeypatch: Any) -> None:
    stream = [s for s in _stream() if getattr(s, "subtype", None) != "compact_boundary"]
    cap = _capture(tmp_path, monkeypatch, stream)
    report = harness.compaction_report(cap, "market-sizing", config_dir=tmp_path / "none")
    assert report["compaction_at"] is not None
    assert report["main_thread_confirmed"] is False  # a sub-agent's compaction fires the same hook


def _transcript(config: Path, rows: list[dict[str, Any]]) -> None:
    folder = config / "projects" / "-tmp-workspace"
    folder.mkdir(parents=True)
    (folder / "sess-1.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def test_the_transcript_confirms_the_boundary_and_reports_the_summary_and_the_note(
    tmp_path: Path, monkeypatch: Any
) -> None:
    stream = [s for s in _stream() if getattr(s, "subtype", None) != "compact_boundary"]
    cap = _capture(tmp_path, monkeypatch, stream)
    config = tmp_path / "config"
    _transcript(
        config,
        [
            {"type": "system", "subtype": "compact_boundary", "isSidechain": True},
            {"type": "user", "message": {"content": "x"}},
            {"type": "system", "subtype": "compact_boundary", "isSidechain": False},
            {"type": "user", "isCompactSummary": True, "message": {"content": "The SKILL.md has been loaded."}},
            {"type": "user", "isMeta": True, "message": {"content": f"SessionStart hook additional context: {NOTE}"}},
        ],
    )
    report = harness.compaction_report(cap, "market-sizing", config_dir=config)
    assert report["transcript_boundaries"] == 1
    assert report["main_thread_confirmed"] is True
    assert report["summaries_say_loaded"] is True
    assert report["note_after_boundary"] is True


def _review_dir(tmp_path: Path, run_id: str, *, redteam: Any = "own", coaching: bool = True) -> Path:
    review = tmp_path / "market-sizing-example"
    review.mkdir()
    if redteam == "own":
        (review / "redteam.json").write_text(json.dumps({"metadata": {"run_id": run_id}}), encoding="utf-8")
    elif redteam == "skip":
        skip = {"red_team_skipped": "no_subagent_dispatch", "red_team_skipped_run_id": run_id}
        (review / "methodology.json").write_text(json.dumps(skip), encoding="utf-8")
    elif redteam == "other":
        (review / "redteam.json").write_text(json.dumps({"metadata": {"run_id": "other"}}), encoding="utf-8")
    body = "# Report\n\n## Coaching Commentary\n\nText.\n" if coaching else "# Report\n"
    (review / "report.md").write_text(body, encoding="utf-8")
    (review / "report.json").write_text("{}", encoding="utf-8")
    return review


def _complete(review: Path, run_id: str) -> dict[str, Any]:
    sha = harness._sha256
    return {
        "status": "complete",
        "run_id": run_id,
        "skill": "market-sizing",
        "gates": [],
        "deliverables_status": "final",
        "deliverables": {
            "report_md": {"sha256": sha(review / "report.md")},
            "report_json": {"sha256": sha(review / "report.json")},
        },
    }


@pytest.mark.parametrize("redteam", ["own", "skip"])
def test_a_completed_compacted_run_passes(lane: Any, tmp_path: Path, redteam: str) -> None:
    review = _review_dir(tmp_path, "r1", redteam=redteam)
    assert lane.compaction_completion_problems(review, "r1", _complete(review, "r1"), {"run_starts": 1}) == []


def test_each_way_a_compacted_run_falls_short_is_named(lane: Any, tmp_path: Path) -> None:
    review = _review_dir(tmp_path, "r1", redteam="other", coaching=False)
    status = {**_complete(review, "r1"), "status": "running"}
    problems = lane.compaction_completion_problems(review, "r1", status, {"run_starts": 2})
    text = "\n".join(problems)
    assert "status 'running'" in text
    assert "redteam names 'other'" in text
    assert "no coaching commentary" in text
    assert "started 2 times" in text


def test_the_lane_is_wired_to_its_own_opt_in(lane: Any, monkeypatch: Any) -> None:
    assert lane.COMPACTION_OPT_IN_ENV == "RUN_PAID_E2E_MS_COMPACTION"
    assert lane.COMPACTION_WINDOW == "100000"
    monkeypatch.delenv(lane.COMPACTION_OPT_IN_ENV, raising=False)
    assert lane._compaction_lane_authorized() is False
    monkeypatch.setenv(lane.COMPACTION_OPT_IN_ENV, "1")
    assert lane._compaction_lane_authorized() is True


def _result_message(cost: float, subtype: str = "success") -> Any:
    from claude_agent_sdk import ResultMessage

    return ResultMessage(
        subtype=subtype,
        duration_ms=1,
        duration_api_ms=1,
        is_error=subtype != "success",
        num_turns=1,
        session_id="sess-1",
        total_cost_usd=cost,
        result="done",
    )


def test_the_budget_cap_reaches_the_options_and_the_cost_is_reported(tmp_path: Path, monkeypatch: Any) -> None:
    cap = _capture(tmp_path, monkeypatch, [_init(), _result_message(12.5, "error_max_budget_usd")], max_budget_usd=22.0)
    assert _SEEN["options"].max_budget_usd == 22.0
    report = harness.compaction_report(cap, "market-sizing", config_dir=tmp_path / "none")
    assert report["cost_usd"] == 12.5 and report["result_subtype"] == "error_max_budget_usd"
    assert "cost $12.5" in harness.format_compaction_report(report)
    _capture(tmp_path, monkeypatch, [_init()])
    assert _SEEN["options"].max_budget_usd is None


def test_the_lane_budget_defaults_and_takes_the_environment(lane: Any, monkeypatch: Any) -> None:
    monkeypatch.delenv(lane.COMPACTION_BUDGET_ENV, raising=False)
    assert lane.compaction_budget() == 25.0
    monkeypatch.setenv(lane.COMPACTION_BUDGET_ENV, "22")
    assert lane.compaction_budget() == 22.0
