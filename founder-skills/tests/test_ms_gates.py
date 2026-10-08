"""market-sizing's recorded gates, through the real scripts.

The sizing prompts are printed by `dispatch_prompt.py`, which refuses (exit 10) until the approach
(`ms_methodology`) and, for each input the founder's materials state two figures for, the choice
(`ms_two_figures.<input>`) are recorded; `market_sizing.py` and compose refuse the same way with a ledger. The
approach answer is bound to `approach_chosen` alone; `Change methodology` and `Correct or add data` ask the
question again; a follow-up the parent no longer owes is closed; the revision question becomes a question
compose asks for instead of a disclosure; the report says which questions were not put to the founder.
Every company name and figure here is invented.
"""

from __future__ import annotations

import copy
import importlib.util
import inspect
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gate_run_helpers as h  # noqa: E402
from test_market_sizing import (  # noqa: E402
    _VALID_CHECKLIST,
    _VALID_INPUTS,
    _VALID_METHODOLOGY,
    _VALID_SENSITIVITY,
    _VALID_SIZING,
    _VALID_VALIDATION,
)


def _load(name: str, path: Path | None = None) -> ModuleType:
    if path is None and name in sys.modules:
        return sys.modules[name]
    if str(h.SHARED) not in sys.path:
        sys.path.append(str(h.SHARED))
    spec = importlib.util.spec_from_file_location(name, path or h.SHARED / f"{name}.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    if path is None:
        sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


rs = _load("_run_status")
g = _load("_gates")

MS = h.SKILLS / "market-sizing" / "scripts"
GEN = MS / "dispatch_prompt.py"
SKILL_MD = h.SKILLS / "market-sizing" / "SKILL.md"
ALT = {"arpu": [{"value": 140, "period": "month", "source": "chat", "label": "the blended rate"}]}
HIGH = {
    "claim_attacked": "The employer share the sizing uses",
    "parameter": "segment_pct",
    "what_is_true": "The published share is lower than the analysis uses.",
    "evidence_quote": "A lower share of employers offered the benefit.",
    "source_url": "https://example.org/benefits",
    "source_title": "Benefits Survey",
    "severity": "high",
}


def _out(proc: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    line = proc.stdout.strip().splitlines()[0] if proc.stdout.strip() else "{}"
    data: dict[str, Any] = json.loads(line)
    return data


def _ok(proc: subprocess.CompletedProcess[str]) -> subprocess.CompletedProcess[str]:
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return proc


def _write(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


def _run_dir(tmp_path: Path, *, alternatives: bool = False, lines: str = "") -> tuple[Path, str, Path]:
    """A started, bound full run with inputs.json and methodology.json written (Steps 2-3)."""
    root, run_id, run_dir = h.start_bound(tmp_path, "market-sizing", lines=lines)
    inputs = {**copy.deepcopy(_VALID_INPUTS), "metadata": {"run_id": run_id}}
    if alternatives:
        inputs["founder_stated_inputs"] = {"arpu": 120}
        inputs["founder_stated_inputs_period"] = {"arpu": "month"}
        inputs["founder_stated_alternatives"] = copy.deepcopy(ALT)
    _write(run_dir / "inputs.json", inputs)
    _write(run_dir / "methodology.json", {"approach_chosen": "both", "rationale": "x", "metadata": {"run_id": run_id}})
    _write(run_dir / "validation.json", {**copy.deepcopy(_VALID_VALIDATION), "metadata": {"run_id": run_id}})
    return root, run_id, run_dir


def _gen(run_dir: Path, run_id: str, context: str = "top_down_methodology") -> subprocess.CompletedProcess[str]:
    hand = run_dir / "handoff" / run_id
    return h.run(
        GEN,
        context,
        "--run-id",
        run_id,
        "--analysis-dir",
        str(run_dir),
        "--handoff-dir",
        str(hand),
        "--handoff-agent",
        str(hand),
    )


def _answer(root: Path, run_id: str, gate: str, option: str, *extra: str) -> subprocess.CompletedProcess[str]:
    return h.record(root, run_id, "answer", "--gate", gate, "--answer-id", option, *extra)


def _open(root: Path, run_id: str, *gates: str) -> subprocess.CompletedProcess[str]:
    args = [a for gate in gates for a in ("--gate", gate)]
    return h.record(root, run_id, "open", *args)


def _entry(root: Path, run_id: str, key: str) -> dict[str, Any]:
    entry: dict[str, Any] = h.ledger(root, run_id)["gates"][key]
    return entry


# --- the sizing prompts wait for their questions ----------------------------------------------------------


def test_with_no_ledger_the_sizing_prompts_print_at_once(tmp_path: Path) -> None:
    d = tmp_path / "plain"
    (d / "h").mkdir(parents=True)
    for name in ("inputs.json", "methodology.json", "validation.json"):
        _write(d / name, {})
    for context in ("top_down_methodology", "bottom_up_methodology"):
        proc = _ok(
            h.run(
                GEN,
                context,
                "--run-id",
                "R",
                "--analysis-dir",
                str(d),
                "--handoff-dir",
                str(d / "h"),
                "--handoff-agent",
                "A",
            )
        )
        assert proc.stdout.startswith(f"CONTEXT: {context.upper()}\n")
        assert proc.stdout.endswith("Do NOT write any file other than OUTPUT_PATH.\n")


def test_the_generator_waits_for_the_figures_then_the_approach(tmp_path: Path) -> None:
    root, run_id, run_dir = _run_dir(tmp_path, alternatives=True)
    proc = _gen(run_dir, run_id)
    assert proc.returncode == 10 and "CONTEXT:" not in proc.stdout
    out = _out(proc)
    assert out["blocked_by_gate"] == "ms_two_figures.arpu"
    opts = out["needs_input"][0]["options"]
    assert [o["id"] for o in opts] == ["typed", "alt_140_month"]
    # The typed option shows its figure, so a question asked from it offers every figure.
    assert "120" in opts[0]["label"] and "140" in opts[1]["label"]
    _ok(_answer(root, run_id, "ms_two_figures.arpu", "typed"))
    assert _out(_gen(run_dir, run_id))["blocked_by_gate"] == "ms_methodology"
    _ok(_answer(root, run_id, "ms_methodology", "looks_good"))
    for context in ("top_down_methodology", "bottom_up_methodology"):
        assert _ok(_gen(run_dir, run_id, context)).stdout.startswith(f"CONTEXT: {context.upper()}\n")


def test_a_missing_methodology_file_is_refused_before_a_request_answer_is_applied(tmp_path: Path) -> None:
    root, run_id, run_dir = _run_dir(tmp_path, lines="FS_HOST_ANSWER ms_methodology=looks_good")
    (run_dir / "methodology.json").unlink()
    before = h.snapshot(root, run_id)
    assert _gen(run_dir, run_id).returncode == 2
    assert h.snapshot(root, run_id) == before


def test_a_request_answer_is_applied_and_the_prompt_prints(tmp_path: Path) -> None:
    root, run_id, run_dir = _run_dir(tmp_path, lines="FS_HOST_ANSWER ms_methodology=looks_good")
    _ok(_gen(run_dir, run_id))
    assert _entry(root, run_id, "ms_methodology")["current"]["asked_evidence"] == "host_line"


def test_an_open_follow_up_holds_the_prompt(tmp_path: Path) -> None:
    root, run_id, run_dir = _run_dir(tmp_path)
    _ok(_answer(root, run_id, "ms_methodology", "looks_good"))
    _ok(_open(root, run_id, "ms_fx_rate"))
    proc = _gen(run_dir, run_id)
    assert proc.returncode == 10 and _out(proc)["blocked_by_gate"] == "ms_fx_rate"


# --- the binder: the approach, nothing else -------------------------------------------------------------


def test_later_writes_to_the_methodology_file_do_not_reopen_the_approach(tmp_path: Path) -> None:
    root, run_id, run_dir = _run_dir(tmp_path)
    _ok(_answer(root, run_id, "ms_methodology", "looks_good"))
    later = {
        "approach_chosen": "both",
        "rationale": "scope now names two verticals",
        "red_team_skipped": "founder_declined",
        "red_team_skipped_run_id": run_id,
        "red_team_revision": {"changes": [{"field": "arpu", "reason": "x"}]},
        "founder_notes": ["a note"],
        "accepted_warnings": [],
        "metadata": {"run_id": run_id},
    }
    _write(run_dir / "methodology.json", later)
    _ok(_gen(run_dir, run_id))
    _write(run_dir / "methodology.json", {**later, "approach_chosen": "top_down"})
    proc = _gen(run_dir, run_id)
    assert proc.returncode == 10 and _out(proc)["blocked_by_gate"] == "ms_methodology"
    assert "changed since" in proc.stderr


# --- asked again: a change or a correction, twice; and the follow-up the parent no longer owes ----------


def test_a_second_change_of_approach_is_recorded(tmp_path: Path) -> None:
    root, run_id, _rd = _run_dir(tmp_path)
    _ok(_answer(root, run_id, "ms_methodology", "change_methodology"))
    _ok(_answer(root, run_id, "ms_methodology_change", "top_down"))
    _ok(_answer(root, run_id, "ms_methodology", "change_methodology"))
    assert _entry(root, run_id, "ms_methodology_change")["state"] == "open"
    _ok(_answer(root, run_id, "ms_methodology_change", "bottom_up"))
    child = _entry(root, run_id, "ms_methodology_change")
    assert child["current"]["answer_id"] == "bottom_up" and child["supersessions"] == 1


def test_a_second_correction_of_the_same_field_is_recorded(tmp_path: Path) -> None:
    root, run_id, _rd = _run_dir(tmp_path)
    key = "ms_correct_data.existing_claims.tam"
    _ok(_answer(root, run_id, "ms_methodology", "correct_data"))
    _ok(_open(root, run_id, key))
    _ok(_answer(root, run_id, key, "set", "--value", "9"))
    _ok(_answer(root, run_id, "ms_methodology", "correct_data"))
    _ok(_open(root, run_id, key))
    _ok(_answer(root, run_id, key, "set", "--value", "10"))
    entry = _entry(root, run_id, key)
    assert entry["current"]["value"] == "10" and "superseded" in [e["event"] for e in entry["history"]]
    # Asked again after the correction, the approach can now be confirmed.
    _ok(_answer(root, run_id, "ms_methodology", "looks_good"))


def test_a_follow_up_the_parent_no_longer_owes_is_closed(tmp_path: Path) -> None:
    """`Change methodology`, then `Looks good` before the new approach was chosen: the follow-up could never
    be answered (not owed) and would hold the run open. It is closed by script."""
    root, run_id, run_dir = _run_dir(tmp_path)
    _ok(_answer(root, run_id, "ms_methodology", "change_methodology"))
    _ok(_answer(root, run_id, "ms_methodology", "looks_good"))
    child = _entry(root, run_id, "ms_methodology_change")
    assert child["state"] == "not_owed" and child["current"]["resolution_basis"] == "script"
    assert h.status(root, run_id)["status"] == "running"
    _ok(_gen(run_dir, run_id))


# --- two figures: ids keyed on the figure; the bare request line ---------------------------------------


def test_an_answer_stands_for_its_figure_after_the_list_is_rewritten(tmp_path: Path) -> None:
    root, run_id, run_dir = _run_dir(tmp_path, alternatives=True)
    _ok(_answer(root, run_id, "ms_two_figures.arpu", "alt_140_month"))
    inputs = json.loads((run_dir / "inputs.json").read_text(encoding="utf-8"))
    inputs["founder_stated_inputs"] = {"arpu": 140}
    inputs["founder_stated_alternatives"] = {"arpu": [{"value": 120, "period": "month", "source": "chat"}]}
    _write(run_dir / "inputs.json", inputs)
    _ok(_answer(root, run_id, "ms_methodology", "looks_good"))
    _ok(_gen(run_dir, run_id))
    assert _entry(root, run_id, "ms_two_figures.arpu")["current"]["answer_id"] == "alt_140_month"


def test_the_bare_two_figures_line_is_accepted_and_answers_every_input(tmp_path: Path) -> None:
    """`FS_HOST_ANSWER ms_two_figures=typed` was the contract before the gate had instances, and the hook
    accepts it: `start` accepts it too, and `open` applies it to each input."""
    root, run_id, run_dir = _run_dir(tmp_path, alternatives=True, lines="FS_HOST_ANSWER ms_two_figures=typed")
    out = _out(_ok(_open(root, run_id, "ms_two_figures.arpu")))
    assert out.get("applied") == "pre_answer"
    assert _entry(root, run_id, "ms_two_figures.arpu")["current"]["answer_id"] == "typed"
    assert "PRE_ANSWERED:ms_two_figures.arpu" in h.status(root, run_id)["disclosures"]
    # The line is listed once in a resume request, as it was sent, not once per input it answered.
    assert g.resume_prompt(h.ledger(root, run_id)).count("FS_HOST_ANSWER ms_two_figures") == 1


def test_the_hook_and_start_read_the_bare_line_the_same_way(tmp_path: Path) -> None:
    """Pinned together: the figures check lets a sizing dispatch through on the bare line, and `start`
    stores it rather than refusing the run."""
    tf = _load("two_figures_check_pin", h.SHARED / "two_figures_check.py")
    row = {
        "type": "user",
        "message": {"role": "user", "content": [{"type": "text", "text": "FS_HOST_ANSWER ms_two_figures=typed"}]},
    }
    assert tf.host_line_in([row], 0, "ms_two_figures", ("ANSWER", "VALUE"), lambda r: True)
    assert tf.host_line_in([row], 0, "ms_two_figures", ("ANSWER",), lambda r: True)
    root = tmp_path / "a"
    root.mkdir()
    proc = h.start(root, "market-sizing", "FS_HOST_ANSWER ms_two_figures=typed")
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_revise_cannot_be_answered_ahead(tmp_path: Path) -> None:
    root = tmp_path / "a"
    root.mkdir()
    proc = h.start(root, "market-sizing", "FS_HOST_ANSWER ms_revision=revise")
    assert proc.returncode == 1 and _out(proc)["code"] == "PRE_ANSWER_INVALID"


def test_none_of_these_is_answered_alone(tmp_path: Path) -> None:
    root, run_id, run_dir = _run_dir(tmp_path)
    _write(run_dir / "redteam.json", {"metadata": {"run_id": run_id}, "findings": [HIGH]})
    ctx_ledger = h.ledger(root, run_id)
    assert "ms_revision_changes" not in ctx_ledger.get("gates", {})
    paths = rs.run_paths(str(root), run_id)
    g.record_from_writer(paths, "ms_revision", "revise", "record_revision_answer.py", by_model=True)
    proc = _answer(root, run_id, "ms_revision_changes", "none_of_these,segment_pct")
    assert proc.returncode == 1 and _out(proc)["code"] == "OPTION_UNLISTED"
    _ok(_answer(root, run_id, "ms_revision_changes", "segment_pct"))


# --- market_sizing.py, the backstop ---------------------------------------------------------------------

_NUMERIC = {
    "approach": "bottom_up",
    "customer_count": 42000,
    "arpu": 1260,
    "serviceable_pct": 30,
    "target_pct": 4,
}


def _size(run_dir: Path, run_id: str | None, *extra: str, stdin: dict[str, Any] = _NUMERIC) -> Any:
    args = ["--stdin", "-o", str(run_dir / "sizing.json"), *extra]
    if run_id:
        args += ["--run-id", run_id]
    return h.run(MS / "market_sizing.py", *args, stdin=json.dumps(stdin))


def test_the_sizing_waits_for_the_approach_and_writes_nothing(tmp_path: Path) -> None:
    root, run_id, run_dir = _run_dir(tmp_path)
    proc = _size(run_dir, run_id)
    assert proc.returncode == 10 and _out(proc)["blocked_by_gate"] == "ms_methodology"
    assert not (run_dir / "sizing.json").exists()
    _ok(_answer(root, run_id, "ms_methodology", "looks_good"))
    _ok(_size(run_dir, run_id))


def test_a_quick_check_owes_no_approach(tmp_path: Path) -> None:
    root, run_id, run_dir = h.start_bound(tmp_path, "market-sizing", suffix="-quickcheck")
    _ok(_size(run_dir, run_id))


def test_a_call_into_a_bound_dir_must_name_its_run(tmp_path: Path) -> None:
    _root, _run_id, run_dir = _run_dir(tmp_path)
    for script, stdin in (
        ("market_sizing.py", _NUMERIC),
        ("checklist.py", {"items": []}),
        ("sensitivity.py", {"approach": "bottom_up", "base": {}, "ranges": {}}),
    ):
        proc = h.run(
            MS / script,
            "-o",
            str(run_dir / "x.json"),
            *(["--stdin"] if script == "market_sizing.py" else []),
            stdin=json.dumps(stdin),
        )
        assert proc.returncode == 1 and _out(proc)["code"] == "RUN_ID_REQUIRED", script
        assert not (run_dir / "x.json").exists()


def _period_case(tmp_path: Path) -> tuple[Path, str, Path, dict[str, Any], dict[str, Any]]:
    root, run_id, run_dir = _run_dir(tmp_path)
    _ok(_answer(root, run_id, "ms_methodology", "looks_good"))
    validation = {
        "sources": [{"title": "Example Report", "url": "https://example.org/r"}],
        "assumptions": [
            {
                "name": "accounts",
                "value": 42000,
                "unit": "count",
                "category": "sourced",
                "source_title": "Example Report",
                "source_url": "https://example.org/r",
            },
            {"name": "reachable", "value": 30, "unit": "percent_points", "category": "derived"},
            {"name": "capture", "value": 4, "unit": "percent_points", "category": "agent_estimate"},
        ],
        "metadata": {"run_id": run_id},
    }
    _write(run_dir / "validation.json", validation)
    inputs = json.loads((run_dir / "inputs.json").read_text(encoding="utf-8"))
    inputs["founder_stated_inputs"] = {"arpu": 90}
    inputs.pop("founder_stated_inputs_period", None)
    _write(run_dir / "inputs.json", inputs)
    refs = {
        "approach": "bottom_up",
        "customer_count": {"assumption": "accounts"},
        "serviceable_pct": {"assumption": "reachable"},
        "arpu": {"founder_stated": "arpu"},
        "target_pct": {"assumption": "capture"},
    }
    return root, run_id, run_dir, refs, inputs


def test_a_period_only_the_founder_knows_is_asked_then_never_asked_again(tmp_path: Path) -> None:
    root, run_id, run_dir, refs, inputs = _period_case(tmp_path)
    extra = ("--validation", str(run_dir / "validation.json"), "--inputs", str(run_dir / "inputs.json"))
    proc = _size(run_dir, run_id, *extra, stdin=refs)
    assert proc.returncode == 10 and _out(proc)["blocked_by_gate"] == "ms_input_period.arpu"
    _ok(_answer(root, run_id, "ms_input_period.arpu", "per_month"))
    # Recorded but not written where the sizing reads it: asking again would loop, so it names the field.
    proc = _size(run_dir, run_id, *extra, stdin=refs)
    assert proc.returncode == 1 and _out(proc)["code"] == "PERIOD_NOT_WRITTEN" and '"month"' in _out(proc)["message"]
    inputs["founder_stated_inputs_period"] = {"arpu": "month"}
    _write(run_dir / "inputs.json", inputs)
    _ok(_size(run_dir, run_id, *extra, stdin=refs))


# --- finished runs: nothing moves -----------------------------------------------------------------------


def test_a_finished_run_whose_approach_changed_is_refused_and_nothing_moves(tmp_path: Path) -> None:
    root, run_id, run_dir = _run_dir(tmp_path)
    _ok(_answer(root, run_id, "ms_methodology", "looks_good"))
    rs.update(rs.run_paths(str(root), run_id), lambda s: (s.update(coaching="inserted"), rs.mark_complete(s)))
    _write(run_dir / "methodology.json", {"approach_chosen": "top_down", "metadata": {"run_id": run_id}})
    before = h.snapshot(root, run_id)
    for proc in (_gen(run_dir, run_id), _size(run_dir, run_id), _compose(run_dir)):
        assert proc.returncode == 1 and _out(proc)["code"] == "RUN_FINISHED", proc.stdout + proc.stderr
        assert "starts a new analysis" in _out(proc)["message"], "the founder-facing reason, not the raw rejection"
        assert h.snapshot(root, run_id) == before


# --- compose ---------------------------------------------------------------------------------------------


def _artifacts(run_dir: Path, run_id: str, *, redteam: dict[str, Any] | None = None) -> None:
    methodology = {k: v for k, v in _VALID_METHODOLOGY.items() if k != "red_team_skipped" or redteam is None}
    if redteam is None:
        methodology["red_team_skipped_run_id"] = run_id
    arts: dict[str, Any] = {
        "inputs.json": _VALID_INPUTS,
        "methodology.json": methodology,
        "validation.json": _VALID_VALIDATION,
        "sizing.json": _VALID_SIZING,
        "checklist.json": _VALID_CHECKLIST,
        "sensitivity.json": _VALID_SENSITIVITY,
    }
    if redteam is not None:
        arts["redteam.json"] = redteam
    for name, data in arts.items():
        data = copy.deepcopy(data)
        data["metadata"] = {"run_id": run_id}
        _write(run_dir / name, data)


def _compose(run_dir: Path) -> subprocess.CompletedProcess[str]:
    return h.run(
        MS / "compose_report.py",
        "--dir",
        str(run_dir),
        "-o",
        str(run_dir / "report.json"),
        "--write-md",
        str(run_dir / "report.md"),
    )


def _redteam(run_id: str) -> dict[str, Any]:
    return {
        "metadata": {"run_id": run_id},
        "findings": [HIGH],
        "rejected": [],
        "could_not_check": [],
        "summary": {"accepted": 1, "rejected": 0, "unchecked": 0, "by_severity": {"low": 0, "medium": 0, "high": 1}},
        "validation": {"status": "valid", "errors": []},
    }


def test_compose_waits_for_the_approach_and_writes_nothing(tmp_path: Path) -> None:
    root, run_id, run_dir = _run_dir(tmp_path)
    _artifacts(run_dir, run_id)
    proc = _compose(run_dir)
    assert proc.returncode == 10 and _out(proc)["blocked_by_gate"] == "ms_methodology"
    assert not (run_dir / "report.md").exists()


def test_compose_asks_for_the_revision_answer_only_when_the_review_raises_the_question(tmp_path: Path) -> None:
    root, run_id, run_dir = _run_dir(tmp_path)
    _artifacts(run_dir, run_id)
    _ok(_answer(root, run_id, "ms_methodology", "looks_good"))
    _ok(_compose(run_dir))  # no review finding: no question
    _artifacts(run_dir, run_id, redteam=_redteam(run_id))
    proc = _compose(run_dir)
    assert proc.returncode == 10 and _out(proc)["blocked_by_gate"] == "ms_revision"
    assert "record_revision_answer.py" in proc.stderr
    _ok(h.run(MS / "record_revision_answer.py", "--dir", str(run_dir), "--answer", "deliver", "--source", "founder"))
    _ok(_compose(run_dir))
    report = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
    assert "REVISION_NOT_OFFERED" not in [w["code"] for w in report["validation"]["warnings"]]


def test_compose_refuses_a_question_opened_and_never_recorded(tmp_path: Path) -> None:
    root, run_id, run_dir = _run_dir(tmp_path)
    _artifacts(run_dir, run_id)
    _ok(_answer(root, run_id, "ms_methodology", "looks_good"))
    _ok(_open(root, run_id, "ms_upload_path"))
    proc = _compose(run_dir)
    assert proc.returncode == 10 and _out(proc)["code"] == "GATE_UNRESOLVED"
    assert h.status(root, run_id)["last_error_code"] == "GATE_UNRESOLVED"


def test_the_report_says_the_request_answered_and_what_was_not_asked_on_every_surface(tmp_path: Path) -> None:
    root, run_id, run_dir = _run_dir(tmp_path, lines="FS_HOST_ANSWER ms_methodology=looks_good")
    _artifacts(run_dir, run_id)
    _ok(_open(root, run_id, "ms_methodology"))
    sizing = json.loads((run_dir / "sizing.json").read_text(encoding="utf-8"))
    sizing.setdefault("validation", {}).setdefault("warnings", []).append(
        {"field": "target_pct", "code": "IMPLAUSIBLE_PCT_SCALE", "message": "x"}
    )
    _write(run_dir / "sizing.json", sizing)
    proc = h.record(root, run_id, "default", "--gate", "ms_pct_scale.target_pct", "--reason", "asked_not_to_be_asked")
    _ok(proc)
    _ok(_compose(run_dir))
    md = (run_dir / "report.md").read_text(encoding="utf-8")
    page = _ok(
        h.run(MS / "visualize.py", "--dir", str(run_dir), "--run-id", run_id, "-o", str(run_dir / "report.html"))
    )
    html = (run_dir / "report.html").read_text(encoding="utf-8")
    del page
    for text in (md, html):
        assert "not put to you as a question" in text
        assert "No question was asked for these; the default was taken: whether a share was meant as a percent" in text
        assert "you confirmed" not in text.lower()
    report = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
    assert "PRE_ANSWERED:ms_methodology" in report["disclosures"]
    assert h.status(root, run_id)["coaching"] == "pending"


def test_an_inputs_edit_after_the_checklist_names_it_stale(tmp_path: Path) -> None:
    root, run_id, run_dir = _run_dir(tmp_path)
    _artifacts(run_dir, run_id)
    items = copy.deepcopy(_VALID_CHECKLIST)["items"]
    _ok(
        h.run(
            MS / "checklist.py",
            "--run-id",
            run_id,
            "--inputs",
            str(run_dir / "inputs.json"),
            "-o",
            str(run_dir / "checklist.json"),
            stdin=json.dumps({"items": items}),
        )
    )
    checklist = json.loads((run_dir / "checklist.json").read_text(encoding="utf-8"))
    assert set(checklist["graded_against"]) == {"inputs.json"}
    _ok(_answer(root, run_id, "ms_methodology", "looks_good"))

    def codes() -> list[str]:
        report = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
        return [w["code"] for w in report["validation"]["warnings"]]

    _ok(_compose(run_dir))
    assert "CHECKLIST_STALE" not in codes()
    inputs = json.loads((run_dir / "inputs.json").read_text(encoding="utf-8"))
    inputs["competitive_landscape_notes"] = "A later note from the deck."
    _write(run_dir / "inputs.json", inputs)
    _ok(_compose(run_dir))
    assert "CHECKLIST_STALE" in codes()


# --- the revision question's writer ----------------------------------------------------------------------


def test_from_pre_answer_touches_nothing_when_no_question_is_owed(tmp_path: Path) -> None:
    root, run_id, run_dir = _run_dir(tmp_path, lines="FS_HOST_ANSWER ms_revision=deliver")
    _write(run_dir / "redteam.json", {"metadata": {"run_id": run_id}, "findings": []})
    before = h.snapshot(root, run_id)
    out = _out(_ok(h.run(MS / "record_revision_answer.py", "--dir", str(run_dir), "--from-pre-answer")))
    assert out == {"applied": False, "owed": False}
    assert h.snapshot(root, run_id) == before


def test_from_pre_answer_applies_the_requests_answer(tmp_path: Path) -> None:
    root, run_id, run_dir = _run_dir(tmp_path, lines="FS_HOST_ANSWER ms_revision=deliver")
    _write(run_dir / "redteam.json", _redteam(run_id))
    out = _out(_ok(h.run(MS / "record_revision_answer.py", "--dir", str(run_dir), "--from-pre-answer")))
    assert out["applied"] is True and out["answer"] == "deliver"
    mirror = json.loads((run_dir / "handoff" / run_id / "revision_answer.json").read_text(encoding="utf-8"))
    assert mirror["source"] == "host" and mirror["answer"] == "deliver"
    assert _entry(root, run_id, "ms_revision")["current"]["answer_id"] == "deliver"


def test_from_pre_answer_without_a_request_answer_opens_the_question(tmp_path: Path) -> None:
    root, run_id, run_dir = _run_dir(tmp_path)
    _write(run_dir / "redteam.json", _redteam(run_id))
    out = _out(_ok(h.run(MS / "record_revision_answer.py", "--dir", str(run_dir), "--from-pre-answer")))
    assert out["applied"] is False and out["owed"] is True
    assert _entry(root, run_id, "ms_revision")["state"] == "open"


# --- the closer --------------------------------------------------------------------------------------------


def test_the_closer_stamps_the_hand_over_and_prints_the_same(tmp_path: Path) -> None:
    root, run_id, run_dir = _run_dir(tmp_path)
    _artifacts(run_dir, run_id)
    _ok(_answer(root, run_id, "ms_methodology", "looks_good"))
    _ok(_compose(run_dir))
    argv = [
        "--report",
        str(run_dir / "report.json"),
        "--link",
        "path",
        "--deliverable",
        f"the written report={run_dir}/report.md",
    ]
    first = _ok(h.run(MS / "closing_message.py", *argv))
    assert h.status(root, run_id)["handed_over_at"]
    # With the status unwritable the hand-over is printed all the same.
    status = h.status_path(root, run_id)
    status.chmod(0o444)
    status.parent.chmod(0o555)
    try:
        again = h.run(MS / "closing_message.py", *argv)
    finally:
        status.parent.chmod(0o755)
        status.chmod(0o644)
    assert again.returncode == 0 and again.stdout == first.stdout


# --- skill-local copies -------------------------------------------------------------------------------------


def test_the_run_id_guard_is_financial_model_reviews_word_for_word() -> None:
    ms = _load("_ms_gates_pin", MS / "_ms_gates.py")
    fmr = _load("_fmr_gates_pin", h.SKILLS / "financial-model-review" / "scripts" / "_fmr_gates.py")
    a = inspect.getsource(ms.refuse_without_run_id).replace("analysis dir", "review dir")
    assert a == inspect.getsource(fmr.refuse_without_run_id)


def test_the_generators_template_is_the_one_skill_md_had() -> None:
    """The sizing prompts moved out of SKILL.md word for word, except the closing: they end with the line
    the dispatch hook requires last."""
    dp = _load("ms_dp_pin", GEN)
    lines = dp._SIZING_LINES["top_down_methodology"]
    assert lines[0] == "CONTEXT: TOP_DOWN_METHODOLOGY"
    assert "35%, not 0.35). segment_pct narrows TAM to SAM; share_pct narrows SAM to SOM — do not swap them. A" in lines
    assert "full dispatch prompt template" not in SKILL_MD.read_text(encoding="utf-8").lower()


@pytest.mark.parametrize("gate", ["ms_methodology", "ms_two_figures", "ms_revision"])
def test_market_sizing_gates_are_wired(gate: str) -> None:
    assert not [k for k, v in g.unimplemented().items() if any(x.startswith("ms_") for x in v)], gate


def test_a_figure_question_the_materials_no_longer_raise_never_strands_the_run(tmp_path: Path) -> None:
    """Opened while the materials stated two figures, then the second figure was dropped: the generator,
    which only reads, must not wait on it forever, and compose must not refuse it as unresolved."""
    root, run_id, run_dir = _run_dir(tmp_path, alternatives=True)
    _ok(_open(root, run_id, "ms_two_figures.arpu"))
    _ok(_answer(root, run_id, "ms_methodology", "looks_good"))
    _artifacts(run_dir, run_id)  # the inputs now state one figure; no write follows before the generator
    _ok(_gen(run_dir, run_id))
    assert _entry(root, run_id, "ms_two_figures.arpu")["state"] == "not_owed"
    _ok(_compose(run_dir))


def test_the_figure_question_offers_at_most_four_options(tmp_path: Path) -> None:
    """The question tool shows four options: the typed figure and the first three alternatives."""
    root, run_id, run_dir = _run_dir(tmp_path, alternatives=True)
    inputs = json.loads((run_dir / "inputs.json").read_text(encoding="utf-8"))
    inputs["founder_stated_alternatives"] = {
        "arpu": [{"value": v, "period": "month", "source": "chat"} for v in (130, 140, 150, 160)]
    }
    _write(run_dir / "inputs.json", inputs)
    opts = _out(_open(root, run_id, "ms_two_figures.arpu"))["needs_input"][0]["options"]
    assert [o["id"] for o in opts] == ["typed", "alt_130_month", "alt_140_month", "alt_150_month"]


def test_the_resume_and_quick_check_sentences_stand() -> None:
    text = SKILL_MD.read_text(encoding="utf-8")
    assert "then continues at the question `waiting_on` names" in text
    assert "For `ms_methodology` that is the Gate after Steps 2-3: do not redo Steps 2-3" in text
    quick = text[text.index("#### Step 5-quick") :]
    assert quick.index("Run it after the slug block below has created `ANALYSIS_DIR` and bound the run.") < quick.index(
        "market_sizing.py"
    )
