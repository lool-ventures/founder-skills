"""A request that says not to ask (`FS_HOST_NO_ASK`): nothing is put, defaults are taken by the scripts, every
other question leaves the run `waiting` (exit 12), and the model cannot answer for anyone.

Exercised through the real scripts on throwaway artifacts roots: the run status script, the recorder, the
company-context script, and each priority skill's own enforcers (deck review's stage gate, market sizing's
revision writer, financial model review's producers and corrections, IC simulation's compose). The hook half
(`no_ask_check.py`, the Stop hook) is exercised on transcripts shaped like the session JSONL. All figures and
names are invented.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gate_run_helpers as h  # noqa: E402
import no_ledger_goldens as goldens  # noqa: E402


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

RID = "20261008T100000Z-0a0b0c"
NO_ASK = f"FS_HOST_RUN_ID={RID}\nFS_HOST_NO_ASK\n"
FMR = h.SKILLS / "financial-model-review" / "scripts"
IC = h.SKILLS / "ic-sim" / "scripts"
MS = h.SKILLS / "market-sizing" / "scripts"
DR = h.SKILLS / "deck-review" / "scripts"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
CASH = (
    "FS_HOST_VALUE fmr_cash_basics.current_balance=stated | 1200000\n"
    "FS_HOST_VALUE fmr_cash_basics.balance_date=stated | 2026-09\n"
    "FS_HOST_VALUE fmr_cash_basics.monthly_burn=stated | 85000\n"
)


def _out(proc: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    text = proc.stdout.strip()
    try:
        whole: dict[str, Any] = json.loads(text or "{}")
        return whole
    except ValueError:
        data: dict[str, Any] = json.loads(text.splitlines()[-1])
        return data


def _ok(proc: subprocess.CompletedProcess[str]) -> subprocess.CompletedProcess[str]:
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return proc


def _rec(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return h.record(root, RID, *args)


def _open(root: Path, *gates: str) -> subprocess.CompletedProcess[str]:
    return _rec(root, "open", *[a for gate in gates for a in ("--gate", gate)])


def _entry(root: Path, key: str) -> dict[str, Any]:
    entry: dict[str, Any] = h.ledger(root, RID)["gates"][key]
    return entry


def _bound(tmp: Path, skill: str, lines: str = "") -> tuple[Path, str, Path]:
    root, run_id, run_dir = h.start_bound(tmp, skill, lines=NO_ASK + lines)
    assert run_id == RID
    return root, run_id, run_dir


def _resume(root: Path, skill: str, extra: str = "") -> dict[str, Any]:
    prompt = str(h.status(root, RID)["resume_prompt"])
    data: dict[str, Any] = json.loads(_ok(h.start(root, skill, prompt + extra)).stdout)
    return data


def _stops(proc: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    """A no-ask stop: exit 12, a waiting payload with nothing to ask from, and the stop line on stderr."""
    assert proc.returncode == 12, proc.stdout + proc.stderr
    out = _out(proc)
    assert out["status"] == "waiting" and out["no_ask"] is True and out["stop"] == g.NO_ASK_STOP
    assert "needs_input" not in out and "answer_command" not in json.dumps(out)
    assert proc.stderr.startswith("Waiting (the request said not to ask):")
    return out


# --- the request lines -------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("lines", "reason"),
    [
        ("FS_HOST_NO_ASK\n", "needs FS_HOST_RUN_ID"),
        (f"FS_HOST_RUN_ID={RID}\nFS_HOST_NO_ASK=1\n", "takes nothing after it"),
        (f"FS_HOST_RUN_ID={RID}\nFS_HOST_WAIT ic_mode\n", "needs FS_HOST_NO_ASK"),
        (f"FS_HOST_RUN_ID={RID}\nFS_HOST_DERIVE ctx_basics.sector\n", "needs FS_HOST_NO_ASK"),
        (NO_ASK + "FS_HOST_DERIVE ctx_basics.stage\n", "cannot name a stage"),
        (NO_ASK + "FS_HOST_DERIVE ic_mode\n", "does not cover"),
        (NO_ASK + "FS_HOST_ANSWER ctx_basics.sector=use_derived\n", "takes a value"),
    ],
)
def test_a_line_the_run_cannot_use_refuses_it(tmp_path: Path, lines: str, reason: str) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    proc = h.start(root, "ic-sim", lines)
    assert proc.returncode == 1 and _out(proc)["code"] == "PRE_ANSWER_INVALID", proc.stdout
    assert reason in proc.stderr + proc.stdout


def test_wait_is_refused_on_a_question_asked_once_per_item_found_at_run_time(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    proc = h.start(root, "market-sizing", NO_ASK + "FS_HOST_WAIT ms_input_period\n")
    assert proc.returncode == 1 and "found at run time" in proc.stderr
    proc = h.start(root, "deck-review", NO_ASK + "FS_HOST_WAIT stage_confirmation\n")
    assert proc.returncode == 1 and "its own script records it" in proc.stderr


@pytest.mark.parametrize(
    "text",
    [
        f"<command-args>FS_HOST_RUN_ID={RID}\nFS_HOST_NO_ASK</command-args>",
        f"<command-args>FS_HOST_NO_ASK\r\nFS_HOST_RUN_ID={RID}</command-args>",
        f"Review it.\nFS_HOST_RUN_ID={RID}\nFS_HOST_NO_ASK\n",
    ],
)
def test_the_line_counts_first_middle_or_last_in_a_slash_commands_arguments(tmp_path: Path, text: str) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    out = json.loads(_ok(h.start(root, "ic-sim", text)).stdout)
    assert out["run_id"] == RID and out["no_ask"] == 1 and out["rule"] == g.NO_ASK_RULE


def test_start_prints_the_rule_and_the_flag_is_sticky_and_resent(tmp_path: Path) -> None:
    root, _rid, _rd = _bound(tmp_path, "ic-sim", "FS_HOST_WAIT ic_mode\nFS_HOST_DERIVE ctx_basics.sector\n")
    assert h.status(root, RID)["no_ask"] is True
    _stops(_open(root, "ic_mode"))
    prompt = h.status(root, RID)["resume_prompt"]
    assert prompt.splitlines()[1:5] == [
        f"FS_HOST_RUN_ID={RID}",
        "FS_HOST_NO_ASK",
        "FS_HOST_WAIT ic_mode",
        "FS_HOST_DERIVE ctx_basics.sector",
    ]
    # A resume that leaves the lines out is still a run that asks nothing.
    out = json.loads(_ok(h.start(root, "ic-sim", f"FS_HOST_RUN_ID={RID}\n")).stdout)
    assert out["no_ask"] == 1 and g.no_ask(h.ledger(root, RID))


def test_an_attended_run_has_no_flag(tmp_path: Path) -> None:
    root, run_id, _rd = h.start_bound(tmp_path, "ic-sim")
    st = h.status(root, run_id)
    assert st["no_ask"] is False and "no_ask" not in h.ledger(root, run_id)
    out = _out(_ok(h.record(root, run_id, "open", "--gate", "ic_mode")))
    assert out["needs_input"] and "applied" not in out


# --- open ----------------------------------------------------------------------------------------------------


def test_a_question_with_a_default_takes_it_and_says_so(tmp_path: Path) -> None:
    root, _rid, _rd = _bound(tmp_path, "ic-sim")
    out = _out(_ok(_open(root, "ic_mode", "ic_fund_mode")))
    assert out["applied"] == "pre_answer" and out["applied_by"] == {
        "ic_mode": "no_ask_default",
        "ic_fund_mode": "no_ask_default",
    }
    assert out["applied_answers"]["ic_mode"]["answer_id"] == "auto_pilot"
    cur = _entry(root, "ic_mode")["current"]
    assert (cur["resolution"], cur["default_reason"], cur["resolution_basis"]) == (
        "default_taken",
        "asked_not_to_be_asked",
        "host_no_ask",
    )
    st = h.status(root, RID)
    assert "DEFAULT_TAKEN:ic_mode" in st["disclosures"] and st["status"] == "running"


def test_a_question_with_no_default_stops_the_run_waiting(tmp_path: Path) -> None:
    root, _rid, _rd = _bound(tmp_path, "ic-sim")
    out = _stops(_open(root, "ctx_basics.company_name", "ic_mode"))
    assert [w["gate"] for w in out["waiting"]] == ["ctx_basics.company_name"]
    st = h.status(root, RID)
    assert (st["status"], st["code"], st["waiting_on"]) == ("waiting", "GATE_WAITING", "ctx_basics.company_name")
    assert h.ledger(root, RID)["form_batches"] == []


def test_wait_stops_at_a_question_that_has_a_default_and_an_answer_line_wins(tmp_path: Path) -> None:
    root, _rid, _rd = _bound(tmp_path, "ic-sim", "FS_HOST_WAIT ic_mode\n")
    _stops(_open(root, "ic_mode"))
    root2, _r2, _d2 = _bound(tmp_path / "b", "ic-sim", "FS_HOST_WAIT ic_mode\nFS_HOST_ANSWER ic_mode=interactive\n")
    out = _out(_ok(_open(root2, "ic_mode")))
    assert out["applied_by"] == {"ic_mode": "request"}


def test_a_request_answer_that_cannot_apply_waits_and_never_falls_to_the_default(tmp_path: Path) -> None:
    root, _rid, run_dir = _bound(
        tmp_path, "financial-model-review", "FS_HOST_ANSWER fmr_extracted_values=corrections_applied\n"
    )
    _stops(_open(root, "fmr_extracted_values"))
    entry = _entry(root, "fmr_extracted_values")
    assert entry["current"] is None and "pre_answer_unlisted" in entry["flags"]
    assert h.status(root, RID)["code"] == "PRE_ANSWER_UNLISTED"


def test_a_question_asking_for_a_file_waits_with_a_code_naming_the_input(tmp_path: Path) -> None:
    root, _rid, _rd = _bound(tmp_path, "deck-review")
    _stops(_open(root, "dr_input_request.copy_failed"))
    st = h.status(root, RID)
    assert (st["code"], st["waiting_on"]) == ("INPUT_NEEDED", "dr_input_request.copy_failed")


def test_an_attended_question_asking_for_a_file_keeps_the_plain_code(tmp_path: Path) -> None:
    root, run_id, _rd = h.start_bound(tmp_path, "deck-review")
    _ok(h.record(root, run_id, "open", "--gate", "dr_input_request.copy_failed"))
    assert h.status(root, run_id)["code"] == "GATE_WAITING"


# --- the model cannot answer ---------------------------------------------------------------------------------


def test_an_answer_typed_by_the_model_is_refused_and_writes_nothing(tmp_path: Path) -> None:
    root, _rid, _rd = _bound(tmp_path, "ic-sim")
    _stops(_open(root, "ctx_basics.stage"))
    before = h.snapshot(root, RID)
    proc = _rec(root, "answer", "--gate", "ctx_basics.stage", "--answer-id", "seed")
    assert proc.returncode == 1 and _out(proc)["code"] == "NO_ASK_ANSWER"
    assert "the run waits for a request line" in proc.stdout
    assert h.snapshot(root, RID) == before


@pytest.mark.parametrize(
    ("gate", "reason", "extra", "ok"),
    [
        ("ctx_basics.stage", "no_signal_marked_to_confirm", ("--answer-id", "seed"), False),
        ("ctx_basics.sector", "stated_in_request", ("--answer-id", "use_derived", "--value", "fintech"), False),
        ("ctx_basics.sector", "derived_from_materials", ("--answer-id", "use_derived", "--value", "fintech"), False),
        ("ctx_basics.sector", "no_signal_marked_to_confirm", ("--answer-id", "not_sure"), True),
        ("ctx_basics.company_name", "no_signal_marked_to_confirm", ("--answer-id", "working_title"), True),
        ("ctx_basics.geography", "no_signal_marked_to_confirm", ("--answer-id", "different"), False),
        ("ic_mode", "asked_not_to_be_asked", (), True),
        ("ic_mode", "stated_in_request", ("--answer-id", "interactive"), False),
    ],
)
def test_the_model_may_only_mark_a_value_unknown(
    tmp_path: Path, gate: str, reason: str, extra: tuple[str, ...], ok: bool
) -> None:
    root, _rid, _rd = _bound(tmp_path, "ic-sim")
    before = h.snapshot(root, RID)
    proc = _rec(root, "default", "--gate", gate, "--reason", reason, *extra)
    if ok:
        _ok(proc)
        basis = _entry(root, gate)["current"]["resolution_basis"]
        assert basis == ("host_no_ask" if reason == "asked_not_to_be_asked" else "model_no_ask")
    else:
        assert proc.returncode == 1 and _out(proc)["code"] == "NO_ASK_DEFAULT", proc.stdout + proc.stderr
        assert h.snapshot(root, RID) == before


def test_a_default_on_a_question_the_request_asked_to_wait_on_is_refused(tmp_path: Path) -> None:
    root, _rid, _rd = _bound(tmp_path, "ic-sim", "FS_HOST_WAIT ic_mode\n")
    proc = _rec(root, "default", "--gate", "ic_mode", "--reason", "asked_not_to_be_asked")
    assert proc.returncode == 1 and _out(proc)["code"] == "NO_ASK_DEFAULT"


def test_a_script_records_its_own_default_unhindered(tmp_path: Path) -> None:
    """The whitelist lives in the recorder's `default` command only; a producer's own default goes through."""
    root, _rid, _rd = _bound(tmp_path, "financial-model-review")
    paths = rs.run_paths(str(root), RID)

    def fn(ctx: Any, led: dict[str, Any], st: dict[str, Any]) -> Any:
        return g.record(
            ctx,
            led,
            "fmr_extracted_values",
            resolution="default_taken",
            default_reason="asked_not_to_be_asked",
            by="compose_report.py",
        )

    g.transact(paths, fn)
    assert _entry(root, "fmr_extracted_values")["state"] == "answered"


# --- deriving from the materials ------------------------------------------------------------------------------


def test_a_derive_line_lets_the_run_take_the_answer_with_its_source(tmp_path: Path) -> None:
    root, _rid, _rd = _bound(tmp_path, "ic-sim", "FS_HOST_DERIVE ctx_basics.sector\n")
    out = _out(_ok(_open(root, "ctx_basics.sector")))
    assert [d["gate"] for d in out["derive"]] == ["ctx_basics.sector"] and "waiting" not in out
    proc = _rec(
        root, "derive", "--gate", "ctx_basics.geography", "--answer-id", "use_derived", "--value", "US", "--source", "x"
    )
    assert proc.returncode == 1 and _out(proc)["code"] == "DERIVE_NOT_AUTHORIZED"
    _ok(
        _rec(
            root,
            "derive",
            "--gate",
            "ctx_basics.sector",
            "--answer-id",
            "use_derived",
            "--value",
            "Warehouse robotics",
            "--source",
            "the deck's title slide",
        )
    )
    cur = _entry(root, "ctx_basics.sector")["current"]
    assert (cur["value"], cur["source"], cur["resolution_basis"]) == (
        "Warehouse robotics",
        "the deck's title slide",
        "host_authorized",
    )
    st = h.status(root, RID)
    assert "DERIVED:ctx_basics.sector" in st["disclosures"]
    assert "DEFAULT_TAKEN:ctx_basics.sector" not in st["disclosures"]


def test_a_derived_answer_is_corrected_by_a_later_line_until_the_context_is_written(tmp_path: Path) -> None:
    root, _rid, run_dir = _bound(tmp_path, "ic-sim", "FS_HOST_DERIVE ctx_basics.sector\n")
    _ok(_open(root, "ctx_basics.sector"))
    _ok(
        _rec(
            root,
            "derive",
            "--gate",
            "ctx_basics.sector",
            "--answer-id",
            "use_derived",
            "--value",
            "Robotics",
            "--source",
            "slide 1",
        )
    )
    _stops(_open(root, "ctx_basics.stage"))
    _resume(root, "ic-sim", "FS_HOST_VALUE ctx_basics.sector=different | Logistics\n")
    _ok(h.bind(root, RID, run_dir, "example-co"))
    out = _out(_ok(_open(root, "ctx_basics.sector")))
    assert out["applied_by"] == {"ctx_basics.sector": "request"}
    assert _entry(root, "ctx_basics.sector")["current"]["value"] == "Logistics"
    assert "PRE_ANSWERED:ctx_basics.sector" in h.status(root, RID)["disclosures"]


def test_an_answer_line_wins_over_a_derive_line(tmp_path: Path) -> None:
    root, _rid, _rd = _bound(
        tmp_path, "ic-sim", "FS_HOST_DERIVE ctx_basics.sector\nFS_HOST_VALUE ctx_basics.sector=different | Fintech\n"
    )
    out = _out(_ok(_open(root, "ctx_basics.sector")))
    assert out["applied_by"] == {"ctx_basics.sector": "request"} and "derive" not in out


# --- a request that asks to stop, and an input that fails again ------------------------------------------------


def test_a_stop_the_request_sent_ends_the_run_at_once(tmp_path: Path) -> None:
    root, _rid, _rd = _bound(tmp_path, "deck-review", "FS_HOST_ANSWER dr_input_request.copy_failed=stop\n")
    proc = _open(root, "dr_input_request.copy_failed")
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert _out(proc) == {
        "status": "refused",
        "code": "REQUEST_DECLINED",
        "gate": "dr_input_request.copy_failed",
        "message": "dr_input_request.copy_failed: the request asked to stop",
    }
    assert "stop here and produce nothing" in proc.stderr
    st = h.status(root, RID)
    assert (st["status"], st["code"]) == ("refused", "REQUEST_DECLINED")


def test_an_attended_stop_through_open_also_ends_the_run(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    lines = f"FS_HOST_RUN_ID={RID}\nFS_HOST_ANSWER dr_input_request.copy_failed=stop\n"
    run_id = h.start_ok(root, "deck-review", lines)
    _ok(h.bind(root, run_id, root / "deck-review-example-co", "example-co"))
    proc = h.record(root, run_id, "open", "--gate", "dr_input_request.copy_failed")
    assert proc.returncode == 1 and _out(proc)["code"] == "REQUEST_DECLINED"
    assert h.status(root, run_id)["status"] == "refused"


def test_the_same_input_failing_again_after_the_request_supplied_it_ends_the_run(tmp_path: Path) -> None:
    lines = "FS_HOST_VALUE dr_input_request.copy_failed=provide | /tmp/example-deck.pdf\n"
    root, _rid, _rd = _bound(tmp_path, "deck-review", lines)
    out = _out(_ok(_open(root, "dr_input_request.copy_failed")))
    assert out["applied_answers"]["dr_input_request.copy_failed"]["value"] == "/tmp/example-deck.pdf"
    proc = _open(root, "dr_input_request.copy_failed")
    assert proc.returncode == 1 and _out(proc)["code"] == "INPUT_UNREADABLE"
    assert h.status(root, RID)["code"] == "INPUT_UNREADABLE"


# --- fail ----------------------------------------------------------------------------------------------------


def test_fail_never_ends_a_run_that_waits_and_ends_one_that_failed(tmp_path: Path) -> None:
    root, _rid, _rd = _bound(tmp_path, "ic-sim")
    _stops(_open(root, "ctx_basics.stage"))
    before = h.snapshot(root, RID)
    args = ("fail", "--run-id", RID, "--artifacts-root", str(root), "--code", "HANDOFF_FAILED", "--reason", "x")
    proc = h.run(h.RUN_STATUS, *args)
    assert proc.returncode == 1 and _out(proc)["code"] == "RUN_WAITING"
    assert h.snapshot(root, RID) == before
    root2, _r2, _d2 = _bound(tmp_path / "b", "ic-sim")
    bad = h.run(
        h.RUN_STATUS, "fail", "--run-id", RID, "--artifacts-root", str(root2), "--code", "NOPE", "--reason", "x"
    )
    assert bad.returncode == 2
    _ok(
        h.run(
            h.RUN_STATUS,
            "fail",
            "--run-id",
            RID,
            "--artifacts-root",
            str(root2),
            "--code",
            "HANDOFF_FAILED",
            "--reason",
            "the checklist hand-off never arrived after two tries",
        )
    )
    st = h.status(root2, RID)
    assert (st["status"], st["code"], st["failure"]["code"]) == ("refused", "HANDOFF_FAILED", "HANDOFF_FAILED")


# --- request lines the run never used -------------------------------------------------------------------------


def test_lines_the_run_never_used_are_listed_when_it_ends_and_leave_no_null_gate(tmp_path: Path) -> None:
    lines = (
        "FS_HOST_ANSWER ic_decline_confirmation=finish\nFS_HOST_WAIT ic_fund_mode\n"
        "FS_HOST_DERIVE ctx_basics.geography\n"
    )
    root, _rid, _rd = _bound(tmp_path, "ic-sim", lines)
    assert all(e.get("state") is not None for e in h.ledger(root, RID)["gates"].values())
    assert "ic_decline_confirmation" not in h.ledger(root, RID)["gates"]
    _ok(
        h.run(
            h.RUN_STATUS,
            "fail",
            "--run-id",
            RID,
            "--artifacts-root",
            str(root),
            "--code",
            "PRODUCER_FAILED",
            "--reason",
            "x",
        )
    )
    notices = {(n["gate"], n["reason"]) for n in h.status(root, RID)["notices"]}
    assert {
        ("ic_decline_confirmation", "not_reached"),
        ("ic_fund_mode", "wait_not_reached"),
        ("ctx_basics.geography", "derive_not_used"),
    } <= notices


# --- the company context ------------------------------------------------------------------------------------


@pytest.mark.parametrize("typed", ["Not sure", "not_sure", "", "NOT SURE"])
def test_not_sure_is_accepted_however_it_is_typed_and_stored_empty(tmp_path: Path, typed: str) -> None:
    root, run_id, _rd = h.start_bound(tmp_path, "ic-sim")
    for gate, option, value in (
        ("ctx_basics.company_name", "different", "Example Co"),
        ("ctx_basics.stage", "seed", None),
        ("ctx_basics.sector", "different", "Fintech"),
        ("ctx_basics.geography", "not_sure", None),
    ):
        _ok(h.record(root, run_id, "open", "--gate", gate))
        extra = ("--value", value) if value else ()
        _ok(h.record(root, run_id, "answer", "--gate", gate, "--answer-id", option, *extra))
    proc = h.run(
        h.SHARED / "founder_context.py",
        "init",
        "--company-name",
        "Example Co",
        "--stage",
        "seed",
        "--sector",
        "Fintech",
        "--geography",
        typed,
        "--artifacts-root",
        str(root),
        "--run-id",
        run_id,
        "--skill",
        "ic-sim",
    )
    _ok(proc)
    ctx = json.loads(proc.stdout)
    assert ctx["geography"] == ""


def test_founder_context_init_stops_with_nothing_to_ask_under_the_token(tmp_path: Path) -> None:
    root, _rid, _rd = _bound(tmp_path, "ic-sim", "FS_HOST_VALUE ctx_basics.company_name=different | Example Co\n")
    proc = h.run(
        h.SHARED / "founder_context.py",
        "init",
        "--company-name",
        "Example Co",
        "--stage",
        "seed",
        "--sector",
        "x",
        "--geography",
        "US",
        "--artifacts-root",
        str(root),
        "--run-id",
        RID,
        "--skill",
        "ic-sim",
    )
    out = _stops(proc)
    assert out["blocked_by_gate"] == "ctx_basics.stage"
    assert h.status(root, RID)["status"] == "waiting"


# --- financial model review ------------------------------------------------------------------------------------


def _fmr(tmp: Path, lines: str = "") -> tuple[Path, Path]:
    root, _rid, run_dir = _bound(tmp, "financial-model-review", lines)
    for f in (FIXTURES / "financial-model-review").iterdir():
        data = json.loads(f.read_text(encoding="utf-8"))
        data.setdefault("metadata", {})["run_id"] = RID
        (run_dir / f.name).write_text(json.dumps(data), encoding="utf-8")
    return root, run_dir


def _producer(script: str, run_dir: Path) -> subprocess.CompletedProcess[str]:
    out = run_dir / script.replace(".py", ".json")
    return h.run(
        FMR / script,
        "--pretty",
        "-o",
        str(out),
        "--run-id",
        RID,
        stdin=(run_dir / "inputs.json").read_text(encoding="utf-8"),
    )


def _fmr_compose(run_dir: Path) -> subprocess.CompletedProcess[str]:
    return h.run(
        FMR / "compose_report.py",
        "--dir",
        str(run_dir),
        "--today",
        "2026-10-07",
        "-o",
        str(run_dir / "report.json"),
        "--write-md",
        str(run_dir / "report.md"),
    )


def test_fmr_no_ask_takes_its_defaults_and_composes_without_a_question(tmp_path: Path) -> None:
    root, run_dir = _fmr(tmp_path, CASH)
    cash = [f"fmr_cash_basics.{k}" for k in ("current_balance", "balance_date", "monthly_burn")]
    out = _out(_ok(_open(root, *cash)))
    assert set(out["applied_by"].values()) == {"request"}
    out = _out(_ok(_open(root, "fmr_extracted_values")))
    assert out["applied_by"] == {"fmr_extracted_values": "no_ask_default"}
    _ok(_producer("unit_economics.py", run_dir))
    _ok(_producer("runway.py", run_dir))
    _ok(_fmr_compose(run_dir))
    st = h.status(root, RID)
    assert "DEFAULT_TAKEN:fmr_extracted_values" in st["disclosures"] and "EXTRACTION_UNREVIEWED" in st["disclosures"]


def test_fmr_values_check_waits_then_the_hosts_corrections_resume_it(tmp_path: Path) -> None:
    root, run_dir = _fmr(tmp_path, CASH + "FS_HOST_WAIT fmr_extracted_values\n")
    _stops(_open(root, "fmr_extracted_values"))
    _stops(_producer("unit_economics.py", run_dir))
    assert h.status(root, RID)["waiting_on"] == "fmr_extracted_values"
    time.sleep(0.002)
    _ok(
        h.run(
            FMR / "apply_corrections.py",
            "--set",
            "revenue.mrr=45000",
            "--original",
            str(run_dir / "inputs.json"),
            "--output-dir",
            str(run_dir),
            "--run-id",
            RID,
            "--origin",
            "external",
        )
    )
    resumed = _resume(root, "financial-model-review", "FS_HOST_ANSWER fmr_extracted_values=corrections_applied\n")
    assert resumed["resume"] == 1 and h.status(root, RID)["status"] == "running"
    _ok(h.bind(root, RID, run_dir, "example-co"))
    shutil.copy(run_dir / "corrected_inputs.json", run_dir / "inputs.json")
    history = [json.loads(x) for x in (run_dir / "extraction_corrections.history.jsonl").read_text().splitlines()]
    assert (
        history[-1]["corrected_sha256"]
        == __import__("hashlib").sha256((run_dir / "inputs.json").read_bytes()).hexdigest()
    )
    out = _out(_ok(_open(root, "fmr_extracted_values")))
    assert out["applied_by"] == {"fmr_extracted_values": "request"}
    cur = _entry(root, "fmr_extracted_values")["current"]
    assert (cur["answer_id"], cur["evidence"]["origin"]) == ("corrections_applied", "external")
    st = h.status(root, RID)
    assert {"CORRECTIONS_SOURCE:external", "PRE_ANSWERED:fmr_extracted_values"} <= set(st["disclosures"])
    _ok(_producer("unit_economics.py", run_dir))


def test_fmr_cash_default_is_replaced_by_a_line_a_resume_sends(tmp_path: Path) -> None:
    root, _run_dir = _fmr(tmp_path)
    _ok(_open(root, "fmr_cash_basics.current_balance"))
    assert _entry(root, "fmr_cash_basics.current_balance")["current"]["answer_id"] == "not_stated"
    _stops(_open(root, "ctx_basics.stage"))
    _resume(root, "financial-model-review", "FS_HOST_VALUE fmr_cash_basics.current_balance=stated | 1200000\n")
    out = _out(_ok(_open(root, "fmr_cash_basics.current_balance")))
    assert out["applied_by"] == {"fmr_cash_basics.current_balance": "request"}
    st = h.status(root, RID)
    assert "PRE_ANSWERED:fmr_cash_basics.current_balance" in st["disclosures"]
    assert "DEFAULT_TAKEN:fmr_cash_basics.current_balance" not in st["disclosures"]


def test_a_request_answer_superseded_by_a_changed_input_is_applied_again_on_a_resume(tmp_path: Path) -> None:
    root, run_dir = _fmr(tmp_path, CASH + "FS_HOST_ANSWER fmr_extracted_values=values_ok\n")
    _ok(_open(root, "fmr_cash_basics.current_balance", "fmr_cash_basics.balance_date", "fmr_cash_basics.monthly_burn"))
    _ok(_open(root, "fmr_extracted_values"))
    inputs = json.loads((run_dir / "inputs.json").read_text())
    inputs["revenue"]["mrr"] = 51000
    (run_dir / "inputs.json").write_text(json.dumps(inputs))
    _stops(_producer("unit_economics.py", run_dir))
    assert h.status(root, RID)["waiting_on"] == "fmr_extracted_values"
    _resume(root, "financial-model-review")
    _ok(h.bind(root, RID, run_dir, "example-co"))
    _ok(_producer("unit_economics.py", run_dir))
    assert _entry(root, "fmr_extracted_values")["current"]["answer_id"] == "values_ok"


# --- IC simulation ----------------------------------------------------------------------------------------------


def _ic(tmp: Path, lines: str = "") -> tuple[Path, Path]:
    root, _rid, run_dir = _bound(tmp, "ic-sim", lines)
    for f in (FIXTURES / "ic-sim").iterdir():
        data = json.loads(f.read_text(encoding="utf-8"))
        data["metadata"] = {**(data.get("metadata") or {}), "run_id": RID}
        (run_dir / f.name).write_text(json.dumps(data), encoding="utf-8")
    scores = json.loads((run_dir / "score_dimensions.json").read_text(encoding="utf-8"))
    scores["summary"]["verdict"] = "pass"
    (run_dir / "score_dimensions.json").write_text(json.dumps(scores), encoding="utf-8")
    return root, run_dir


def _ic_compose(run_dir: Path) -> subprocess.CompletedProcess[str]:
    return h.run(
        IC / "compose_report.py",
        "--dir",
        str(run_dir),
        "-o",
        str(run_dir / "report.json"),
        "--write-md",
        str(run_dir / "report.md"),
    )


def test_ic_a_decline_takes_finish_and_composes_without_a_question(tmp_path: Path) -> None:
    root, run_dir = _ic(tmp_path)
    _ok(_ic_compose(run_dir))
    st = h.status(root, RID)
    assert "DEFAULT_TAKEN:ic_decline_confirmation" in st["disclosures"] and st["coaching"] == "pending"


def test_ic_a_decline_the_request_asked_to_wait_on_waits_then_resumes(tmp_path: Path) -> None:
    root, run_dir = _ic(tmp_path, "FS_HOST_WAIT ic_decline_confirmation\n")
    _stops(_open(root, "ic_decline_confirmation"))
    proc = _ic_compose(run_dir)
    _stops(proc)
    assert not (run_dir / "report.md").exists()
    st = h.status(root, RID)
    assert (st["status"], st["waiting_on"]) == ("waiting", "ic_decline_confirmation")
    _resume(root, "ic-sim", "FS_HOST_ANSWER ic_decline_confirmation=finish\n")
    _ok(h.bind(root, RID, run_dir, "example-co"))
    assert _out(_ok(_open(root, "ic_decline_confirmation")))["applied_by"] == {"ic_decline_confirmation": "request"}
    _ok(_ic_compose(run_dir))
    assert "PRE_ANSWERED:ic_decline_confirmation" in h.status(root, RID)["disclosures"]


def test_compose_with_a_question_still_open_leaves_the_run_waiting_not_running(tmp_path: Path) -> None:
    root, run_dir = _ic(tmp_path, "FS_HOST_ANSWER ic_decline_confirmation=finish\n")
    _stops(_open(root, "ctx_basics.stage"))
    _stops(_ic_compose(run_dir))
    st = h.status(root, RID)
    assert (st["status"], st["last_error_code"]) == ("waiting", None)
    assert _resume(root, "ic-sim")["resume"] == 1


# --- market sizing ----------------------------------------------------------------------------------------------


def test_ms_the_revision_question_takes_deliver_and_writes_its_record(tmp_path: Path) -> None:
    root, _rid, run_dir = _bound(tmp_path, "market-sizing")
    (run_dir / "redteam.json").write_text(json.dumps({**goldens.REDTEAM, "metadata": {"run_id": RID}}))
    (run_dir / "handoff" / RID).mkdir(parents=True, exist_ok=True)
    out = _out(_ok(h.run(MS / "record_revision_answer.py", "--dir", str(run_dir), "--from-pre-answer")))
    assert out["applied"] is True and out["answer"] == "deliver"
    mirror = json.loads((run_dir / "handoff" / RID / "revision_answer.json").read_text())
    assert (mirror["answer"], mirror["source"]) == ("deliver", "no_questions")
    cur = _entry(root, "ms_revision")["current"]
    assert (cur["resolution"], cur["resolution_basis"]) == ("default_taken", "host_no_ask")
    # The prose route's own call records the same default: unchanged, never refused.
    _ok(
        h.run(
            MS / "record_revision_answer.py", "--dir", str(run_dir), "--answer", "deliver", "--source", "no_questions"
        )
    )
    founder = h.run(
        MS / "record_revision_answer.py", "--dir", str(run_dir), "--answer", "revise", "--source", "founder"
    )
    assert founder.returncode == 1 and _out(founder)["code"] == "NO_ASK_ANSWER"


def test_ms_the_approach_takes_its_default(tmp_path: Path) -> None:
    root, _rid, _rd = _bound(tmp_path, "market-sizing")
    out = _out(_ok(_open(root, "ms_methodology")))
    assert out["applied_by"] == {"ms_methodology": "no_ask_default"}


# --- deck review ---------------------------------------------------------------------------------------------


def _emit(run_dir: Path, stage: str = "seed") -> subprocess.CompletedProcess[str]:
    return h.run(
        DR / "gate_state.py",
        "emit",
        "--run-id",
        RID,
        "--stage",
        stage,
        "-o",
        str(run_dir / "gate_state.json"),
        stdin=json.dumps(goldens.STAGE_BODY),
    )


def test_dr_the_stage_check_is_auto_satisfied_from_the_requests_stage(tmp_path: Path) -> None:
    root, _rid, run_dir = _bound(tmp_path, "deck-review", "FS_HOST_ANSWER ctx_basics.stage=seed\n")
    _ok(_open(root, "ctx_basics.stage"))
    proc = _ok(_emit(run_dir))
    assert _out(proc)["answered"]["answer_source"] == "auto_satisfied"
    cur = _entry(root, "stage_confirmation")["current"]
    assert (cur["resolution"], cur["default_reason"]) == ("default_taken", "stage_stated_and_detected_agree")


def test_dr_the_stage_check_waits_without_the_requests_stage(tmp_path: Path) -> None:
    root, _rid, run_dir = _bound(tmp_path, "deck-review")
    out = _stops(_emit(run_dir))
    assert out["blocked_by_gate"] == "stage_confirmation" and (run_dir / "gate_state.json").exists()
    assert h.status(root, RID)["waiting_on"] == "stage_confirmation"
    answer = h.run(
        DR / "gate_state.py",
        "answer",
        "--file",
        str(run_dir / "gate_state.json"),
        "--answer",
        "Looks right",
        "--source",
        "founder",
    )
    assert answer.returncode != 0 and "NO_ASK_ANSWER" in answer.stdout + answer.stderr


def test_dr_a_mismatched_stage_is_not_auto_satisfied(tmp_path: Path) -> None:
    root, _rid, run_dir = _bound(tmp_path, "deck-review", "FS_HOST_ANSWER ctx_basics.stage=series_a\n")
    _ok(_open(root, "ctx_basics.stage"))
    _stops(_emit(run_dir, "seed"))


def test_dr_compose_records_that_the_deck_was_read_as_text(tmp_path: Path) -> None:
    dr_compose = _load("dr_compose_report", DR / "compose_report.py")
    (tmp_path / "deck_inventory.json").write_text(json.dumps({"input_format": "text"}))
    assert dr_compose._deck_read_as_text(str(tmp_path)) is True
    (tmp_path / "deck_inventory.json").write_text(json.dumps({"input_format": "pdf"}))
    assert dr_compose._deck_read_as_text(str(tmp_path)) is False


# --- no exit 10 outside the helper --------------------------------------------------------------------------------


# The functions allowed to name the attended waiting code: the shared helpers, and attended-only paths each of
# which returns or exits under the token above that line (asserted by the per-skill no-ask tests).
WAITING_CODE_SITES = {
    ("founder-skills/scripts/_gates.py", "print_waiting_and_exit"),
    ("founder-skills/scripts/_gates.py", "waiting_exit"),
    ("founder-skills/scripts/run_status.py", "_blocked"),
    ("founder-skills/scripts/founder_context.py", "_check_gate_records"),
    ("founder-skills/scripts/founder_context.py", "_read_with_ledger"),
    ("founder-skills/skills/cap-table/scripts/_ct_gates.py", "refuse_open_gates"),
    ("founder-skills/skills/competitive-positioning/scripts/_cp_gates.py", "refuse_open_gates"),
    ("founder-skills/skills/deck-review/scripts/compose_report.py", "_record_refusal"),
    ("founder-skills/skills/deck-review/scripts/compose_report.py", "_refuse_open_gates"),
    ("founder-skills/skills/financial-model-review/scripts/_fmr_gates.py", "refuse_open_gates"),
    ("founder-skills/skills/financial-model-review/scripts/_fmr_gates.py", "settle_cash_followup"),
    ("founder-skills/skills/ic-sim/scripts/_ic_gates.py", "refuse_open_gates"),
    ("founder-skills/skills/market-sizing/scripts/_ms_gates.py", "period_question"),
    ("founder-skills/skills/market-sizing/scripts/_ms_gates.py", "revision_owed"),
    ("founder-skills/skills/market-sizing/scripts/_ms_gates.py", "refuse_open_gates"),
}
_EXITS = ("exit", "_exit", "_init_refusal")


def _waiting_exit_sites(path: Path) -> list[str]:
    """Every way a script could exit 10 bypassing the shared helper: a literal 10 (directly, or through a name
    or constant bound to 10), and the attended code `EXIT_CODES["waiting"]` named outside the allowed sites."""
    rel = str(path.relative_to(h.REPO_ROOT)) if path.is_relative_to(h.REPO_ROOT) else path.name
    tree = ast.parse(path.read_text(encoding="utf-8"))
    ten_names = {
        t.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and node.value.value == 10
        for t in node.targets
        if isinstance(t, ast.Name)
    }

    def is_ten(node: ast.AST) -> bool:
        if isinstance(node, ast.Constant) and node.value == 10:
            return True
        return isinstance(node, ast.Name) and node.id in ten_names

    hits: list[str] = []

    def visit(node: ast.AST, func: str) -> None:
        for child in ast.iter_child_nodes(node):
            name = child.name if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) else func
            called = getattr(child.func, "attr", getattr(child.func, "id", "")) if isinstance(child, ast.Call) else ""
            if isinstance(child, ast.Call) and called in _EXITS and child.args and is_ten(child.args[0]):
                hits.append(f"{rel}:{child.lineno} exit 10")
            if isinstance(child, ast.Return) and child.value is not None and is_ten(child.value):
                hits.append(f"{rel}:{child.lineno} return 10")
            if (
                isinstance(child, ast.Subscript)
                and getattr(child.value, "attr", getattr(child.value, "id", "")) == "EXIT_CODES"
                and isinstance(child.slice, ast.Constant)
                and child.slice.value == "waiting"
                and (rel, name) not in WAITING_CODE_SITES
            ):
                hits.append(f"{rel}:{child.lineno} EXIT_CODES['waiting'] in {name}")
            visit(child, name)

    visit(tree, "<module>")
    return hits


def test_no_script_exits_10_except_through_the_shared_waiting_exit() -> None:
    """Every stop on an unanswered question goes through `_gates.waiting_exit` (or names the attended code
    `EXIT_CODES["waiting"]` in a listed attended-only path, which the no-ask branch above it has already left),
    so a run whose request said not to ask always exits 12 there. Anything else is a stop that would bypass it."""
    files = sorted(h.SHARED.glob("*.py")) + sorted(h.SKILLS.glob("*/scripts/*.py"))
    found = [hit for p in files for hit in _waiting_exit_sites(p)]
    assert found == []


def test_the_exit_10_scan_sees_a_name_a_constant_and_an_unlisted_waiting_code(tmp_path: Path) -> None:
    """The scan itself: each bypass shape is found (a scan that finds nothing proves nothing)."""
    probe = tmp_path / "probe_exit_scan.py"
    probe.write_text(
        "import sys\nWAIT = 10\nEXIT_CODES = {'waiting': 10}\n\n\ndef a():\n    sys.exit(10)\n\n\n"
        "def b():\n    sys.exit(WAIT)\n\n\ndef c():\n    return 10\n\n\ndef d():\n"
        "    sys.exit(EXIT_CODES['waiting'])\n",
        encoding="utf-8",
    )
    hits = _waiting_exit_sites(probe)
    assert len(hits) == 4, hits


# --- the hooks ------------------------------------------------------------------------------------------------


def _user(text: str, **extra: Any) -> dict[str, Any]:
    return {"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": text}]}, **extra}


def _transcript(tmp: Path, rows: list[dict[str, Any]]) -> str:
    path = tmp / "t.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return str(path)


def _ask(tmp: Path, rows: list[dict[str, Any]]) -> Any:
    check = _load("no_ask_check_under_test", h.SHARED / "no_ask_check.py")
    payload = {
        "hook_event_name": "PreToolUse",
        "tool_name": "AskUserQuestion",
        "tool_input": {"questions": []},
        "transcript_path": _transcript(tmp, rows),
    }
    return check.decide(payload)


@pytest.mark.parametrize(
    ("rows", "denied"),
    [
        ([_user(f"Review it.\nFS_HOST_RUN_ID={RID}\nFS_HOST_NO_ASK")], True),
        ([_user("<command-args>Review it.\nFS_HOST_NO_ASK</command-args>")], True),
        ([_user("Review it.")], False),
        ([_user("FS_HOST_NO_ASK", isMeta=True)], False),
        (
            [
                _user("Review it."),
                {
                    "type": "user",
                    "message": {
                        "role": "user",
                        "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "FS_HOST_NO_ASK"}],
                    },
                },
            ],
            False,
        ),
        ([_user("FS_HOST_NO_ASK", isCompactSummary=True)], False),
    ],
)
def test_the_question_tool_is_denied_only_in_a_request_that_said_not_to_ask(
    tmp_path: Path, rows: list[dict[str, Any]], denied: bool
) -> None:
    out = _ask(tmp_path, rows)
    assert (out is not None) is denied
    if denied:
        reason = out["hookSpecificOutput"]["permissionDecisionReason"]
        assert reason.startswith("[no-ask-check]") and "in chat" in reason


def test_a_resume_that_left_the_line_out_is_covered_by_the_runs_ledger(tmp_path: Path) -> None:
    root, _rid, _rd = _bound(tmp_path, "ic-sim")
    ledger = h.ledger_path(root, RID)
    start_result = {
        "type": "user",
        "message": {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "s1", "content": json.dumps({"ledger_path_shell": str(ledger)})}
            ],
        },
    }
    assert _ask(tmp_path, [_user(f"Resume.\nFS_HOST_RUN_ID={RID}"), start_result]) is not None
    attended_root, attended_id, _r = h.start_bound(tmp_path / "b", "ic-sim")
    other = {
        "type": "user",
        "message": {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "s1",
                    "content": json.dumps({"ledger_path_shell": str(h.ledger_path(attended_root, attended_id))}),
                }
            ],
        },
    }
    assert _ask(tmp_path, [_user("Resume."), other]) is None


def test_the_check_runs_before_the_review_page_check() -> None:
    dispatch = _load("pretooluse_dispatch_under_test", h.SHARED / "pretooluse_dispatch.py")
    assert dispatch.CHECKS == (
        "dispatch_type_check",
        "asked_gate_check",
        "two_figures_check",
        "dispatch_prompt_check",
        "no_ask_check",
        "review_page_check",
    )


def test_the_stop_hook_asks_once_when_a_no_ask_run_is_left_running(tmp_path: Path) -> None:
    stop = _load("stop_handover_check_under_test", h.SHARED / "stop_handover_check.py")
    status = tmp_path / "run_status.json"
    status.write_text(json.dumps({"status": "running", "no_ask": True}))
    start = {
        "type": "user",
        "message": {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "s1", "content": json.dumps({"status_path": str(status)})}
            ],
        },
    }
    req = _user(f"Review it.\nFS_HOST_RUN_ID={RID}\nFS_HOST_NO_ASK")
    payload = {"hook_event_name": "Stop", "transcript_path": _transcript(tmp_path, [req, start])}
    block = stop.decide(payload)
    assert block is not None and block["reason"].startswith(stop.NO_ASK_END_MARKER)
    # Once: the block's own feedback in the prompt stops a second.
    feedback = _user(f"Stop hook feedback: {block['reason']}", isMeta=True)
    payload["transcript_path"] = _transcript(tmp_path, [req, start, feedback])
    assert stop.decide(payload) is None
    for state in ("waiting", "complete"):
        status.write_text(json.dumps({"status": state, "no_ask": True}))
        payload["transcript_path"] = _transcript(tmp_path, [req, start])
        assert stop.decide(payload) is None
    # An attended run never fires it; a refused start (no status path) never fires it.
    status.write_text(json.dumps({"status": "running", "no_ask": False}))
    assert (
        stop.decide({"hook_event_name": "Stop", "transcript_path": _transcript(tmp_path, [_user("Review it."), start])})
        is None
    )
    refused = {
        "type": "user",
        "message": {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": "s1", "content": json.dumps({"code": "RUN_ID_IN_USE"})}],
        },
    }
    assert stop.decide({"hook_event_name": "Stop", "transcript_path": _transcript(tmp_path, [req, refused])}) is None


# --- the skills' text --------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "skill",
    ["deck-review", "market-sizing", "financial-model-review", "ic-sim", "competitive-positioning", "cap-table"],
)
def test_each_skills_start_paragraph_routes_exit_12_to_a_stop(skill: str) -> None:
    text = (h.SKILLS / skill / "SKILL.md").read_text(encoding="utf-8")
    start = text.index("**Then start the run's record, once**")
    paragraph = text[start : text.index("\n\n", start)]
    assert "Exit 12 from any script: ask nothing; say what the run is waiting for, and stop." in paragraph


def test_the_shared_reference_states_the_rule() -> None:
    text = (h.REPO_ROOT / "founder-skills" / "references" / "skill-execution-model.md").read_text(encoding="utf-8")
    section = text[text.index("## Gates and run status") : text.index("## Per-Symptom Triage")]
    for phrase in ("FS_HOST_NO_ASK", "exit 12", "record nothing yourself", "run_status.py fail", "FS_HOST_DERIVE"):
        assert phrase in section, phrase
    for phrase in ("stated_in_request` / `derived_from_materials", "record what the request"):
        assert phrase not in section


def test_an_attended_unresolved_question_stays_running_as_the_contract_says(tmp_path: Path) -> None:
    """Compose's `GATE_UNRESOLVED` leaves an attended run `running`; a later read-only transaction does not turn
    it into `waiting` (only a no-ask run is re-derived there)."""
    root, run_id, run_dir = h.start_bound(tmp_path, "ic-sim", lines="FS_HOST_ANSWER ic_decline_confirmation=finish\n")
    for f in (FIXTURES / "ic-sim").iterdir():
        data = json.loads(f.read_text(encoding="utf-8"))
        data["metadata"] = {**(data.get("metadata") or {}), "run_id": run_id}
        (run_dir / f.name).write_text(json.dumps(data), encoding="utf-8")
    _ok(h.record(root, run_id, "open", "--gate", "ctx_basics.stage"))
    proc = _ic_compose(run_dir)
    assert proc.returncode == 10, proc.stdout + proc.stderr
    st = h.status(root, run_id)
    assert (st["status"], st["last_error_code"]) == ("running", "GATE_UNRESOLVED")
    g.transact(rs.run_paths(str(root), run_id), lambda ctx, led, s: None)
    st = h.status(root, run_id)
    assert (st["status"], st["last_error_code"]) == ("running", "GATE_UNRESOLVED")


def test_a_derived_answer_needs_a_stated_source(tmp_path: Path) -> None:
    root, _rid, _rd = _bound(tmp_path, "ic-sim", "FS_HOST_DERIVE ctx_basics.sector\n")
    proc = _rec(
        root,
        "derive",
        "--gate",
        "ctx_basics.sector",
        "--answer-id",
        "use_derived",
        "--value",
        "Robotics",
        "--source",
        " ",
    )
    assert proc.returncode == 1 and _out(proc)["code"] == "VALUE_REQUIRED"


def test_an_attended_run_left_running_with_an_error_keeps_what_it_wrote(tmp_path: Path) -> None:
    """The status re-derivation is for a plain `running` (or a no-ask run): an attended run a script left
    `running` with an error code beside an open question is not turned into `waiting`."""
    root, run_id, _rd = h.start_bound(tmp_path, "ic-sim")
    _ok(h.record(root, run_id, "open", "--gate", "ctx_basics.stage"))
    paths = rs.run_paths(str(root), run_id)

    def broken(st: dict[str, Any]) -> None:
        rs.set_state(st, "running", "RUNNING")
        st["last_error_code"] = "GATE_INVALID"

    rs.update(paths, broken)
    before = h.status_path(root, run_id).read_bytes()
    g.transact(paths, lambda ctx, led, s: None)
    assert h.status_path(root, run_id).read_bytes() == before


def test_a_request_stop_still_pending_at_compose_exits_cleanly(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A stop the request sent on a resume, for a question nobody opened again, is applied when compose settles
    the open questions: exit 1 with `REQUEST_DECLINED` on stdout, never a traceback."""
    root, _rid, _rd = _bound(tmp_path, "deck-review")
    _stops(_open(root, "dr_input_request.copy_failed"))
    _resume(root, "deck-review", "FS_HOST_ANSWER dr_input_request.copy_failed=stop\n")
    dr_compose = _load("dr_compose_for_stop", DR / "compose_report.py")
    sys.path.insert(0, str(DR))
    with pytest.raises(SystemExit) as ended:
        dr_compose._refuse_open_gates((g, rs.run_paths(str(root), RID)))
    assert ended.value.code == 1
    out = capsys.readouterr()
    assert json.loads(out.out.strip().splitlines()[-1])["code"] == "REQUEST_DECLINED"
    assert "Traceback" not in out.err
    assert h.status(root, RID)["code"] == "REQUEST_DECLINED"


def test_a_founder_fact_asked_again_is_asked_not_refused_as_an_unreadable_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only a question asking for a file or path ends the run when it comes back after the request answered it;
    a cap-table fact asked again simply waits for a new line."""
    root, _rid, _rd = _bound(tmp_path, "cap-table", "FS_HOST_VALUE ct_founder_fact.inputs.example=stated | 5\n")
    monkeypatch.setattr(g, "owed", lambda ctx, gdef, inst: True)
    paths = rs.run_paths(str(root), RID)
    key = "ct_founder_fact.inputs.example"
    first = g.transact(paths, lambda ctx, led, st: g.open_gates(ctx, led, [key]))
    assert first["applied_by"] == {key: "request"}
    second = g.transact(paths, lambda ctx, led, st: g.open_gates(ctx, led, [key]))
    assert [w["gate"] for w in second["waiting"]] == [key]
    assert h.status(root, RID)["status"] == "waiting"
