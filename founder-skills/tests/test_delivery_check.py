"""Unit tests for the runtime delivery-completeness checker.

The branch that matters most here — `[incomplete]`, i.e. SOME files delivered
but not all — is the one with **no real-evidence validation available**. A live
Cowork probe measured a four-file skill presenting three, but that was observed
in the Desktop UI, which a harness run dir does not record; no run directory on
this machine exhibits the partial signature (every one is either complete or
zero-delivery). So the partial case is exercised synthetically below, and the
limitation is stated rather than papered over.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "delivery_check",
    pathlib.Path(__file__).resolve().parents[2] / "cowork-tests" / "delivery_check.py",
)
assert _SPEC and _SPEC.loader
dc = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(dc)


# ---------------------------------------------------------------- check()


def test_complete_delivery_passes() -> None:
    problems, outcome = dc.check({"A.md", "A.html"}, {"A.md", "A.html"}, calls=1)
    assert outcome == "PASS"
    assert problems == []


def test_partial_delivery_fails_and_names_the_missing_file() -> None:
    """THE defect this checker exists for, and the one `present_files_called`
    cannot see: it asserts at-least-one, so it is green on this input."""
    problems, outcome = dc.check(
        {"A_Cap_Table.md", "A_Cap_Table.html", "A_Cap_Table_Explorer.html", "A_Counsel_Packet.md"},
        {"A_Cap_Table.md", "A_Cap_Table_Explorer.html", "A_Counsel_Packet.md"},
        calls=1,
    )
    assert outcome == "FAIL"
    assert any("incomplete" in p for p in problems)
    # The missing file must be NAMED — "something is missing" is not actionable.
    assert any("A_Cap_Table.html" in p for p in problems)


def test_zero_delivery_is_reported_separately_from_partial() -> None:
    """Distinct problem classes: nothing handed over vs a subset handed over.
    They have different causes and the report should not conflate them."""
    problems, outcome = dc.check({"A.md"}, set(), calls=0)
    assert outcome == "FAIL"
    assert any("undelivered" in p for p in problems)


def test_nothing_produced_and_nothing_delivered_is_not_exercised() -> None:
    """A gated stop or a rule-lookup. Never a pass — exit 2, not 0."""
    problems, outcome = dc.check(set(), set(), calls=0)
    assert outcome == "NOT-EXERCISED"
    assert problems == []


def test_remote_lane_zero_calls_is_not_a_failure_but_is_not_a_pass_either() -> None:
    """On lane: remote the delivery tool is not served at all, so silence is the
    tool's absence, not the agent's failure. Scoring it FAIL would manufacture a
    defect on the lane Cowork makes DEFAULT for new sessions; scoring it PASS
    would hide a real one."""
    problems, outcome = dc.check({"A.md"}, set(), calls=0, lane="remote")
    assert outcome == "NOT-EXERCISED"
    assert any("not-observable" in p for p in problems)
    assert any("A.md" in p for p in problems)


def test_extra_presented_file_is_not_a_failure() -> None:
    """Presenting something that is not at the outputs root is not this
    checker's business — over-delivery is not the defect under test."""
    _, outcome = dc.check({"A.md"}, {"A.md", "some_other.md"}, calls=1)
    assert outcome == "PASS"


def test_require_flags_a_file_that_was_never_produced() -> None:
    """The root scan cannot see a file that does not exist; --require can."""
    problems, outcome = dc.check(
        {"Acme_Cap_Table.md"},
        {"Acme_Cap_Table.md"},
        calls=1,
        require=dc.REQUIRED_SUFFIXES["cap-table"],
    )
    assert outcome == "FAIL"
    assert any("_Counsel_Packet.md" in p and "missing-required" in p for p in problems)


def test_require_is_suffix_matched_so_the_company_prefix_is_irrelevant() -> None:
    produced = presented = {
        "Ridgeline_Cap_Table.md",
        "Ridgeline_Cap_Table.html",
        "Ridgeline_Cap_Table_Explorer.html",
        "Ridgeline_Counsel_Packet.md",
    }
    _, outcome = dc.check(produced, presented, calls=1, require=dc.REQUIRED_SUFFIXES["cap-table"])
    assert outcome == "PASS"


# ------------------------------------------------- transcript parsing


def _write_run(tmp_path: pathlib.Path, tool_uses: list[dict], root_files: list[str]) -> pathlib.Path:
    """Build a minimal run dir: an events.jsonl plus an mnt/outputs tree."""
    run = tmp_path / "run"
    (run / "work" / "session" / "mnt" / "outputs" / "artifacts").mkdir(parents=True)
    out = run / "work" / "session" / "mnt" / "outputs"
    for name in root_files:
        (out / name).write_text("x", encoding="utf-8")
    # Working state below the root must be ignored, per the skills' own contract.
    (out / "artifacts" / "report.json").write_text("{}", encoding="utf-8")
    lines = [json.dumps({"message": {"role": "assistant", "content": [tu]}}) for tu in tool_uses]
    (run / "events.jsonl").write_text("\n".join(lines), encoding="utf-8")
    return run


def _present(files: list[str], name: str = "mcp__cowork__present_files") -> dict:
    return {
        "type": "tool_use",
        "name": name,
        "input": {"files": [{"file_path": f"/mnt/outputs/{f}"} for f in files]},
    }


def test_end_to_end_complete(tmp_path: pathlib.Path) -> None:
    run = _write_run(tmp_path, [_present(["A.md", "A.html"])], ["A.md", "A.html"])
    presented, calls, _err = dc.collect_presented(run)
    produced, root, _fr = dc.collect_produced(run)
    assert calls == 1
    assert presented == {"A.md", "A.html"}
    assert produced == {"A.md", "A.html"}
    assert root is not None
    assert dc.check(produced, presented, calls)[1] == "PASS"


def test_artifacts_subdir_is_working_state_not_a_deliverable(tmp_path: pathlib.Path) -> None:
    """ic-sim's Deliver step: the root is "the level the founder sees as
    deliverable cards; artifacts/ below it is working state". If the scan
    descended, every run would FAIL on unpresented intermediates."""
    run = _write_run(tmp_path, [_present(["A.md"])], ["A.md"])
    produced, _, _fr = dc.collect_produced(run)
    assert produced == {"A.md"}
    assert "report.json" not in produced


def test_the_agent_native_tool_name_is_also_recognized(tmp_path: pathlib.Path) -> None:
    """Desktop-local serves mcp__cowork__present_files; remote/cloud serves the
    agent-native SendUserFile. A checker that knew only one would report a
    total delivery failure on the other surface."""
    run = _write_run(tmp_path, [_present(["A.md"], name="SendUserFile")], ["A.md"])
    presented, calls, _err = dc.collect_presented(run)
    assert calls == 1 and presented == {"A.md"}


def test_delivery_across_multiple_calls_is_unioned(tmp_path: pathlib.Path) -> None:
    """Delivering in two batches is still a complete delivery."""
    run = _write_run(tmp_path, [_present(["A.md"]), _present(["A.html"])], ["A.md", "A.html"])
    presented, calls, _err = dc.collect_presented(run)
    produced, _, _fr = dc.collect_produced(run)
    assert calls == 2
    assert dc.check(produced, presented, calls)[1] == "PASS"


def test_partial_delivery_end_to_end_is_the_r3_signature(tmp_path: pathlib.Path) -> None:
    """Partial delivery, reproduced end to end: four produced, three handed over.

    Synthetic by necessity — no run directory exhibits this, because the live
    observation of it came from the Desktop UI, not from harness evidence.
    """
    files = ["C_Cap_Table.md", "C_Cap_Table.html", "C_Cap_Table_Explorer.html", "C_Counsel_Packet.md"]
    run = _write_run(tmp_path, [_present([f for f in files if f != "C_Cap_Table.html"])], files)
    presented, calls, _err = dc.collect_presented(run)
    produced, _, _fr = dc.collect_produced(run)
    problems, outcome = dc.check(produced, presented, calls)
    assert outcome == "FAIL"
    assert any("C_Cap_Table.html" in p for p in problems)


def test_missing_outputs_dir_is_evidence_unavailable(tmp_path: pathlib.Path) -> None:
    run = tmp_path / "bare"
    run.mkdir()
    (run / "events.jsonl").write_text("", encoding="utf-8")
    produced, root, _fr = dc.collect_produced(run)
    assert root is None and produced == set()


def test_malformed_transcript_lines_are_skipped_not_fatal(tmp_path: pathlib.Path) -> None:
    """The transcript envelope has changed shape across harness versions; a
    reader that dies on one bad line reports a total delivery failure."""
    run = _write_run(tmp_path, [_present(["A.md"])], ["A.md"])
    p = run / "events.jsonl"
    p.write_text("mcp__cowork__present_files {not json\n" + p.read_text(encoding="utf-8"), encoding="utf-8")
    presented, calls, _err = dc.collect_presented(run)
    assert calls == 1 and presented == {"A.md"}


# ------------------------------------------------------------- regression


def test_against_the_real_run_that_motivated_this_checker() -> None:
    """The ic-sim-contested run: 2 produced at the outputs root, 2 presented.

    Scored by hand before the script existed; this pins that the script agrees.
    Skips where the run dir is absent — it is local evidence, not a fixture.
    """
    run = pathlib.Path.home() / ".cowork-harness" / "runs" / "ic-sim-contested" / "local_l5c2x1rb7g"
    if not run.exists():
        pytest.skip("local run directory not present")
    presented, calls, _err = dc.collect_presented(run)
    produced, _, _fr = dc.collect_produced(run)
    assert calls == 1
    assert produced == {"Ridgeline_IC_Simulation.md", "Ridgeline_IC_Simulation.html"}
    assert dc.check(produced, presented, calls)[1] == "PASS"


# ------------------------------- the no-root-copy shape (financial-model-review)


def _write_nested_run(tmp_path: pathlib.Path, tool_uses: list[dict], nested: list[str]) -> pathlib.Path:
    """A run whose deliverables live UNDER the outputs root, never copied up.

    This is financial-model-review's real shape: no workspace-root copy, the
    three files presented by path from the review dir.
    """
    run = tmp_path / "run"
    review = run / "work" / "session" / "mnt" / "outputs" / "artifacts" / "financial-model-review-acme"
    review.mkdir(parents=True)
    for name in nested:
        (review / name).write_text("x", encoding="utf-8")
    lines = [json.dumps({"message": {"role": "assistant", "content": [tu]}}) for tu in tool_uses]
    (run / "events.jsonl").write_text("\n".join(lines), encoding="utf-8")
    return run


def test_no_root_copy_deliverables_are_found_below_the_root(tmp_path: pathlib.Path) -> None:
    """A root-only scan reports nothing produced for this shape, which makes a
    PARTIAL delivery score PASS — blind to the defect, on one sixth of the fleet.
    """
    files = ["report.md", "report.html", "explore.html"]
    run = _write_nested_run(tmp_path, [_present(files)], files)
    produced, _, from_root = dc.collect_produced(run)
    assert produced == set(files)
    assert from_root is False


def test_partial_delivery_is_caught_for_a_no_root_copy_skill(tmp_path: pathlib.Path) -> None:
    """The regression that motivated the nested scan: 3 produced, 2 handed over."""
    files = ["report.md", "report.html", "explore.html"]
    run = _write_nested_run(tmp_path, [_present(["report.md", "report.html"])], files)
    presented, calls, err = dc.collect_presented(run)
    produced, _, _ = dc.collect_produced(run)
    problems, outcome = dc.check(produced, presented, calls, errored=err)
    assert outcome == "FAIL"
    assert any("explore.html" in p for p in problems)


def test_root_copy_run_ignores_its_own_working_state(tmp_path: pathlib.Path) -> None:
    """The nested scan must NOT engage when the root holds deliverables, or every
    root-copy run fails on the intermediates its copy was made from."""
    run = _write_run(tmp_path, [_present(["A_Cap_Table.md"])], ["A_Cap_Table.md"])
    review = run / "work" / "session" / "mnt" / "outputs" / "artifacts" / "cap-table-acme"
    review.mkdir(parents=True)
    (review / "report.md").write_text("x", encoding="utf-8")
    produced, _, from_root = dc.collect_produced(run)
    assert produced == {"A_Cap_Table.md"}
    assert from_root is True


def test_fmr_require_row_passes_a_conforming_run(tmp_path: pathlib.Path) -> None:
    """--require financial-model-review must not fail the shape it describes."""
    files = ["report.md", "report.html", "explore.html"]
    run = _write_nested_run(tmp_path, [_present(files)], files)
    presented, calls, err = dc.collect_presented(run)
    produced, _, _ = dc.collect_produced(run)
    _, outcome = dc.check(
        produced, presented, calls, require=dc.REQUIRED_SUFFIXES["financial-model-review"], errored=err
    )
    assert outcome == "PASS"


# ---------------------------------------------------- errored deliveries


def test_an_errored_delivery_call_does_not_credit_its_files(tmp_path: pathlib.Path) -> None:
    """A hallucinated path or a permission failure must not score PASS. The
    tool_use alone says what was ATTEMPTED, not what the founder received."""
    run = tmp_path / "run"
    out = run / "work" / "session" / "mnt" / "outputs"
    out.mkdir(parents=True)
    (out / "A.md").write_text("x", encoding="utf-8")
    call = _present(["A.md"])
    call["id"] = "tu_1"
    lines = [
        json.dumps({"message": {"role": "assistant", "content": [call]}}),
        json.dumps(
            {"message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "tu_1", "is_error": True}]}}
        ),
    ]
    (run / "events.jsonl").write_text("\n".join(lines), encoding="utf-8")

    presented, calls, errored = dc.collect_presented(run)
    assert presented == set()
    assert errored == 1
    produced, _, _ = dc.collect_produced(run)
    problems, outcome = dc.check(produced, presented, calls, errored=errored)
    assert outcome == "FAIL"
    assert any("errored-delivery" in p for p in problems)


def test_a_successful_delivery_still_counts_when_another_errored(tmp_path: pathlib.Path) -> None:
    run = tmp_path / "run"
    out = run / "work" / "session" / "mnt" / "outputs"
    out.mkdir(parents=True)
    (out / "A.md").write_text("x", encoding="utf-8")
    ok, bad = _present(["A.md"]), _present(["ghost.md"])
    ok["id"], bad["id"] = "tu_ok", "tu_bad"
    lines = [
        json.dumps({"message": {"role": "assistant", "content": [ok, bad]}}),
        json.dumps(
            {
                "message": {
                    "role": "user",
                    "content": [{"type": "tool_result", "tool_use_id": "tu_bad", "is_error": True}],
                }
            }
        ),
    ]
    (run / "events.jsonl").write_text("\n".join(lines), encoding="utf-8")
    presented, _, errored = dc.collect_presented(run)
    assert presented == {"A.md"} and errored == 1


# ------------------------------------------------------- lane detection


def test_lane_is_read_from_the_run_not_trusted_from_a_flag(tmp_path: pathlib.Path) -> None:
    """An operator who forgets --lane remote gets a false FAIL; one who passes it
    on a local run launders a real failure. The run records the answer."""
    run = _write_run(tmp_path, [], ["A.md"])
    turn = run / "turns" / "1"
    turn.mkdir(parents=True)
    (turn / "result.json").write_text(json.dumps({"lane": "remote"}), encoding="utf-8")
    assert dc.detect_lane(run) == "remote"


def test_lane_detection_returns_none_when_unrecorded(tmp_path: pathlib.Path) -> None:
    run = _write_run(tmp_path, [], ["A.md"])
    assert dc.detect_lane(run) is None


# ------------------------------------------- the CLI exit-code contract


def _run_cli(args: list[str]) -> int:
    import subprocess

    script = pathlib.Path(__file__).resolve().parents[2] / "cowork-tests" / "delivery_check.py"
    return subprocess.run([__import__("sys").executable, str(script), *args], capture_output=True, text=True).returncode


def test_cli_exit_codes(tmp_path: pathlib.Path) -> None:
    """The 0/1/2 contract is what any caller gates on, and it had no coverage —
    `return 1` could have been `return 0` and every other test stayed green."""
    ok = _write_run(tmp_path / "ok", [_present(["A.md"])], ["A.md"])
    assert _run_cli([str(ok)]) == 0

    bad = _write_run(tmp_path / "bad", [_present(["A.md"])], ["A.md", "B.html"])
    assert _run_cli([str(bad)]) == 1

    empty = _write_run(tmp_path / "empty", [], [])
    assert _run_cli([str(empty)]) == 2

    assert _run_cli([str(tmp_path / "nope")]) == 2


def test_lane_detection_survives_a_scenario_that_is_a_bare_string(tmp_path: pathlib.Path) -> None:
    """Real result.json files carry `scenario` as a NAME string, not an object.
    Indexing it blind crashed the CLI on a real run dir — fixtures never showed
    it because fixtures were written from the shape the code assumed."""
    run = _write_run(tmp_path, [], ["A.md"])
    turn = run / "turns" / "1"
    turn.mkdir(parents=True)
    (turn / "result.json").write_text(json.dumps({"scenario": "market-sizing-smoke"}), encoding="utf-8")
    assert dc.detect_lane(run) is None


# ------------------------------------------------- cassette-file mode (CI has no run dir)


def _write_cassette(
    tmp_path: pathlib.Path,
    tool_uses: list[dict],
    artifact_paths: list[str],
    *,
    lane: str | None = None,
    name: str = "cassette",
) -> pathlib.Path:
    """A minimal committed-cassette shape: `events` (JSON-line strings, exactly
    what a live run writes to events.jsonl) + `artifacts[].path` (root-relative
    to `outputs/`, not `mnt/outputs/...` — see the module's cassette docstrings
    for why the prefix differs from a run dir)."""
    events = [json.dumps({"message": {"role": "assistant", "content": [tu]}}) for tu in tool_uses]
    doc = {
        "scenario": {"lane": lane} if lane is not None else {},
        "artifacts": [{"path": p} for p in artifact_paths],
        "events": events,
    }
    cassette = tmp_path / f"{name}.cassette.json"
    cassette.write_text(json.dumps(doc), encoding="utf-8")
    return cassette


def test_cassette_mode_complete_delivery(tmp_path: pathlib.Path) -> None:
    cassette = _write_cassette(
        tmp_path,
        [_present(["A.md", "A.html"])],
        ["outputs/A.md", "outputs/A.html"],
    )
    presented, calls, _err = dc.collect_presented(cassette)
    produced, root, from_root = dc.collect_produced(cassette)
    assert calls == 1
    assert presented == {"A.md", "A.html"}
    assert produced == {"A.md", "A.html"}
    assert root is not None
    assert from_root is True
    assert dc.check(produced, presented, calls)[1] == "PASS"


def test_cassette_mode_partial_delivery_is_caught(tmp_path: pathlib.Path) -> None:
    """The exact defect class this checker exists for, reproduced from a cassette
    rather than a live run dir — this is the CI-reachable evidence path."""
    cassette = _write_cassette(
        tmp_path,
        [_present(["A_Cap_Table.md"])],
        ["outputs/A_Cap_Table.md", "outputs/A_Cap_Table.html"],
    )
    produced, _, _ = dc.collect_produced(cassette)
    presented, calls, _ = dc.collect_presented(cassette)
    problems, outcome = dc.check(produced, presented, calls)
    assert outcome == "FAIL"
    assert any("A_Cap_Table.html" in p for p in problems)


def test_cassette_mode_nested_no_root_copy_deliverable(tmp_path: pathlib.Path) -> None:
    """financial-model-review has no root copy — its cassette's artifacts sit
    below `outputs/`, e.g. `outputs/artifacts/<dir>/report.md`."""
    cassette = _write_cassette(
        tmp_path,
        [],
        ["outputs/artifacts/financial-model-review-cadence/report.md", "outputs/artifacts/.../model_data.json"],
    )
    produced, root, from_root = dc.collect_produced(cassette)
    assert produced == {"report.md"}
    assert from_root is False
    assert root is not None


def test_cassette_mode_lane_is_read_from_scenario_lane(tmp_path: pathlib.Path) -> None:
    cassette = _write_cassette(tmp_path, [], ["outputs/A.md"], lane="remote")
    assert dc.detect_lane(cassette) == "remote"


def test_cassette_mode_lane_absent_returns_none(tmp_path: pathlib.Path) -> None:
    cassette = _write_cassette(tmp_path, [], ["outputs/A.md"])
    assert dc.detect_lane(cassette) is None


def test_cassette_mode_cli_exit_codes(tmp_path: pathlib.Path) -> None:
    ok = _write_cassette(tmp_path, [_present(["A.md"])], ["outputs/A.md"], name="ok")
    assert _run_cli([str(ok)]) == 0

    bad = _write_cassette(tmp_path, [_present(["A.md"])], ["outputs/A.md", "outputs/B.html"], name="bad")
    assert _run_cli([str(bad)]) == 1

    empty = _write_cassette(tmp_path, [], [], name="empty")
    assert _run_cli([str(empty)]) == 2
