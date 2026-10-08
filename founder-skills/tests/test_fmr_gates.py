"""financial-model-review's recorded gates, through the real scripts.

The values check (`fmr_extracted_values`), the cash questions (`fmr_cash_basics`) and the cash follow-up
(`fmr_cash_followup`): the binder that ties the values answer to `inputs.json` minus the cash paths, the
`requires` readers over the corrections history, the enforcers (`unit_economics.py`, `runway.py`, compose,
`verify_review.py`), the report's and the hand-over's disclosure, and the cash cycle that reopens a complete
run. Every company name and figure here is invented.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gate_run_helpers as h  # noqa: E402


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

FMR = h.SKILLS / "financial-model-review" / "scripts"
FIXTURES = h.REPO_ROOT / "founder-skills" / "tests" / "fixtures" / "financial-model-review"
SKILL_MD = h.SKILLS / "financial-model-review" / "SKILL.md"


def _out(proc: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    line = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else "{}"
    data: dict[str, Any] = json.loads(line)
    return data


def _ok(proc: subprocess.CompletedProcess[str]) -> subprocess.CompletedProcess[str]:
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return proc


def _run(tmp: Path, *, lines: str = "", suffix: str = "") -> tuple[Path, str, Path]:
    """A started, bound run whose dir holds the fixture's four producer artifacts, carrying this run's id."""
    root, run_id, run_dir = h.start_bound(tmp, "financial-model-review", lines=lines, suffix=suffix)
    for f in FIXTURES.iterdir():
        data = json.loads(f.read_text(encoding="utf-8"))
        data.setdefault("metadata", {})["run_id"] = run_id
        (run_dir / f.name).write_text(json.dumps(data), encoding="utf-8")
    return root, run_id, run_dir


def _rec(root: Path, run_id: str, *args: str) -> subprocess.CompletedProcess[str]:
    return h.record(root, run_id, *args)


def _settle_step1(root: Path, run_id: str) -> None:
    _ok(
        _rec(
            root,
            run_id,
            "open",
            *[a for k in g.GATES["fmr_cash_basics"]["instances"]["static"] for a in ("--gate", f"fmr_cash_basics.{k}")],
        )
    )
    _ok(
        _rec(
            root,
            run_id,
            "answer",
            "--gate",
            "fmr_cash_basics.current_balance",
            "--answer-id",
            "stated",
            "--value",
            "1500000",
            "--gate",
            "fmr_cash_basics.balance_date",
            "--answer-id",
            "stated",
            "--value",
            "2026-05",
            "--gate",
            "fmr_cash_basics.monthly_burn",
            "--answer-id",
            "stated",
            "--value",
            "120000",
        )
    )


def _corrections(run_dir: Path, run_id: str | None, origin: str | None, *sets: str) -> None:
    args = [a for s in sets for a in ("--set", s)]
    args += ["--original", str(run_dir / "inputs.json"), "--output-dir", str(run_dir)]
    if run_id is not None:
        args += ["--run-id", run_id, "--origin", str(origin)]
    _ok(h.run(FMR / "apply_corrections.py", *args))
    shutil.copy(run_dir / "corrected_inputs.json", run_dir / "inputs.json")


def _producer(
    script: str, run_dir: Path, run_id: str | None, *, out: str | None = None
) -> subprocess.CompletedProcess[str]:
    args = ["--pretty", "-o", str(run_dir / (out or script.replace(".py", ".json")))]
    if run_id is not None:
        args += ["--run-id", run_id]
    return h.run(FMR / script, *args, stdin=(run_dir / "inputs.json").read_text(encoding="utf-8"))


def _compose(run_dir: Path) -> subprocess.CompletedProcess[str]:
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


def _snapshot(run_dir: Path, root: Path, run_id: str) -> dict[str, bytes]:
    files = {p.name: p.read_bytes() for p in run_dir.iterdir() if p.is_file()}
    files["status"], files["ledger"] = h.snapshot(root, run_id)
    return files


# --- the binder -------------------------------------------------------------------------------------------


def _fp(root: Path, run_id: str) -> str:
    paths = rs.run_paths(str(root), run_id)
    out: str = g.transact(paths, lambda c, led, s: g.binding(c, "fmr_inputs_minus_cash"))["fingerprint"]
    return out


def test_the_binder_survives_a_cash_only_call_and_sees_any_other_change(tmp_path: Path) -> None:
    root, run_id, run_dir = _run(tmp_path)
    inputs = json.loads((run_dir / "inputs.json").read_text())
    # A document apply_corrections would re-canonicalise: string numbers, an unsorted series with row ids.
    inputs["revenue"]["mrr"] = "40,000"
    inputs["revenue"]["monthly"] = [
        {"month": "2026-03", "value": 3, "_row_id": "b"},
        {"month": "2026-01", "value": 1, "_row_id": "a"},
    ]
    (run_dir / "inputs.json").write_text(json.dumps(inputs))
    raw = _fp(root, run_id)
    _corrections(run_dir, run_id, "chat", "cash.current_balance=250000", "cash.balance_date=2026-09")
    assert _fp(root, run_id) == raw, "a cash-only call (which re-canonicalises the rest) must not move the binding"
    _corrections(run_dir, run_id, "chat", "revenue.mrr=45000")
    assert _fp(root, run_id) != raw


def test_the_binder_puts_sys_path_and_the_sibling_ref_back(tmp_path: Path) -> None:
    """Loading apply_corrections.py for its pipeline must not leave financial-model-review's scripts dir first
    on sys.path, or its `_run_ref` cached, in another skill's process."""
    sys.modules.pop("_fmr_apply_corrections", None)
    before_path, before_ref = list(sys.path), sys.modules.get("_run_ref")
    root, run_id, _rd = _run(tmp_path)
    _fp(root, run_id)
    assert sys.path == before_path
    assert sys.modules.get("_run_ref") is before_ref


# --- requires -----------------------------------------------------------------------------------------------


def _opened(root: Path, run_id: str) -> None:
    _ok(_rec(root, run_id, "open", "--gate", "fmr_extracted_values"))
    time.sleep(0.002)


def test_corrections_applied_needs_this_runs_founder_or_host_call_after_the_question(tmp_path: Path) -> None:
    root, run_id, run_dir = _run(tmp_path)
    # Before the question, by the inputs review, or with no run id: none of these count.
    _corrections(run_dir, run_id, "chat", "revenue.mrr=41000")
    _opened(root, run_id)
    _corrections(run_dir, None, None, "revenue.mrr=43000")
    refused = _rec(root, run_id, "answer", "--gate", "fmr_extracted_values", "--answer-id", "corrections_applied")
    assert refused.returncode == 1 and _out(refused)["code"] == "REQUIRES_UNMET"
    _corrections(run_dir, run_id, "chat", "revenue.mrr=44000")
    _ok(_rec(root, run_id, "answer", "--gate", "fmr_extracted_values", "--answer-id", "corrections_applied"))
    cur = h.ledger(root, run_id)["gates"]["fmr_extracted_values"]["current"]
    assert cur["evidence"]["origin"] == "chat"
    assert "CORRECTIONS_SOURCE:chat" in h.status(root, run_id)["disclosures"]


def test_an_inputs_review_call_or_an_unchanged_call_never_satisfies_it(tmp_path: Path) -> None:
    root, run_id, run_dir = _run(tmp_path)
    _opened(root, run_id)
    corrected = json.loads((run_dir / "inputs.json").read_text())
    corrected["cash"]["monthly_net_burn"] = 100000
    change = {"path": "cash.monthly_net_burn", "old": 120000, "new": 100000, "reason": "scale"}
    payload = {"corrected": corrected, "corrections": [change]}
    (run_dir / "ir.json").write_text(json.dumps(payload))
    _ok(
        h.run(
            FMR / "apply_corrections.py",
            str(run_dir / "ir.json"),
            "--original",
            str(run_dir / "inputs.json"),
            "--output-dir",
            str(run_dir),
            "--run-id",
            run_id,
            "--origin",
            "inputs_review",
        )
    )
    burn = json.loads((run_dir / "inputs.json").read_text())["cash"]["monthly_net_burn"]
    _corrections(run_dir, run_id, "chat", f"cash.monthly_net_burn={burn}")  # was == now: changed_count 0
    refused = _rec(root, run_id, "answer", "--gate", "fmr_extracted_values", "--answer-id", "corrections_applied")
    assert _out(refused)["code"] == "REQUIRES_UNMET"


def test_a_torn_history_line_is_skipped_never_refused(tmp_path: Path) -> None:
    root, run_id, run_dir = _run(tmp_path)
    _opened(root, run_id)
    _corrections(run_dir, run_id, "chat", "revenue.mrr=45000")
    with open(run_dir / g.FMR_HISTORY, "a", encoding="utf-8") as f:
        f.write('{"seq": 9, "run_id": "torn')
    _ok(_rec(root, run_id, "answer", "--gate", "fmr_extracted_values", "--answer-id", "corrections_applied"))


def test_a_request_line_whose_corrections_are_not_on_record_leaves_the_question_open(tmp_path: Path) -> None:
    """A host that applied corrections without --run-id: the line cannot be applied, the run waits, and the
    founder is asked. Opening twice notes it once."""
    lines = "FS_HOST_ANSWER fmr_extracted_values=corrections_applied\n"
    root, run_id, _rd = _run(tmp_path, lines=lines)
    for _ in range(2):
        out = _out(_ok(_rec(root, run_id, "open", "--gate", "fmr_extracted_values")))
        assert out.get("applied") is None and out["needs_input"]
    st = h.status(root, run_id)
    assert (st["status"], st["code"]) == ("waiting", "PRE_ANSWER_UNLISTED")
    assert [n["code"] for n in st["notices"]].count("PRE_ANSWER_NOT_APPLIED") == 1


def test_a_request_line_with_the_hosts_corrections_on_record_is_applied(tmp_path: Path) -> None:
    lines = "FS_HOST_ANSWER fmr_extracted_values=corrections_applied\n"
    root, run_id, run_dir = _run(tmp_path, lines=lines)
    _opened_raw = _rec(root, run_id, "open", "--gate", "fmr_extracted_values")
    assert _opened_raw.returncode == 0
    time.sleep(0.002)
    _corrections(run_dir, run_id, "external", "revenue.mrr=41250")
    out = _out(_ok(_rec(root, run_id, "open", "--gate", "fmr_extracted_values")))
    assert out["applied"] == "pre_answer"
    st = h.status(root, run_id)
    assert (
        "CORRECTIONS_SOURCE:external" in st["disclosures"] and "PRE_ANSWERED:fmr_extracted_values" in st["disclosures"]
    )


def test_disclosures_are_listed_once_however_often_the_status_is_derived(tmp_path: Path) -> None:
    root, run_id, _rd = _run(tmp_path)
    _ok(_rec(root, run_id, "default", "--gate", "fmr_extracted_values", "--reason", "asked_not_to_be_asked"))
    # Each recorded answer re-derives the status from the ledger.
    for key, value in (("current_balance", "1"), ("balance_date", "2026-01"), ("monthly_burn", "2")):
        _ok(_rec(root, run_id, "answer", "--gate", f"fmr_cash_basics.{key}", "--answer-id", "stated", "--value", value))
    st = h.status(root, run_id)
    assert st["disclosures"].count("EXTRACTION_UNREVIEWED") == 1


# --- bind and the quick check --------------------------------------------------------------------------------


def test_a_quick_check_bound_after_its_cash_questions_were_opened_finishes(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    run_id = h.start_ok(root, "financial-model-review", "FS_HOST_VALUE fmr_cash_basics.monthly_burn=stated | 9000\n")
    _ok(
        _rec(
            root, run_id, "open", "--gate", "fmr_cash_basics.current_balance", "--gate", "fmr_cash_basics.balance_date"
        )
    )
    run_dir = root / "financial-model-review-example-co-quickcheck"
    _ok(h.bind(root, run_id, run_dir, "example-co"))
    st = h.status(root, run_id)
    assert st["mode"] == "quick_check" and st["status"] == "running"
    proc = h.run(
        FMR / "runway.py",
        "--pretty",
        "--run-id",
        run_id,
        "-o",
        str(run_dir / "runway.json"),
        stdin='{"cash": {"current_balance": 400000, "monthly_net_burn": 60000}}',
    )
    _ok(proc)
    _ok(
        h.run(
            h.RUN_STATUS,
            "finish",
            "--mode",
            "quick_check",
            "--run-id",
            run_id,
            "--artifacts-root",
            str(root),
            "--output",
            str(run_dir / "runway.json"),
        )
    )
    assert h.status(root, run_id)["status"] == "complete"


# --- the producers --------------------------------------------------------------------------------------------


def test_the_producers_refuse_until_the_values_check_is_recorded(tmp_path: Path) -> None:
    root, run_id, run_dir = _run(tmp_path)
    _settle_step1(root, run_id)
    before = (run_dir / "runway.json").read_bytes()
    for script in ("unit_economics.py", "runway.py"):
        proc = _producer(script, run_dir, run_id)
        assert proc.returncode == 10, proc.stderr
        assert _out(proc)["blocked_by_gate"] == "fmr_extracted_values"
    assert (run_dir / "runway.json").read_bytes() == before, "-o is left as it was"
    assert h.status(root, run_id)["status"] == "waiting"
    _ok(
        _rec(
            root,
            run_id,
            "answer",
            "--gate",
            "fmr_extracted_values",
            "--answer-id",
            "has_corrections",
            "--value",
            "in chat",
        )
    )
    assert _producer("runway.py", run_dir, run_id).returncode == 10, "an intermediate answer is not a review"
    _corrections(run_dir, run_id, "chat", "revenue.mrr=45000")
    _ok(_rec(root, run_id, "answer", "--gate", "fmr_extracted_values", "--answer-id", "corrections_applied"))
    _ok(_producer("unit_economics.py", run_dir, run_id))
    _ok(_producer("runway.py", run_dir, run_id))


def test_runway_waits_for_an_unrecorded_cash_question(tmp_path: Path) -> None:
    root, run_id, run_dir = _run(tmp_path)
    _ok(_rec(root, run_id, "answer", "--gate", "fmr_extracted_values", "--answer-id", "values_ok"))
    _ok(_producer("unit_economics.py", run_dir, run_id))
    proc = _producer("runway.py", run_dir, run_id)
    assert proc.returncode == 10 and _out(proc)["blocked_by_gate"].startswith("fmr_cash_basics.")


def test_a_changed_figure_after_the_values_answer_asks_again(tmp_path: Path) -> None:
    root, run_id, run_dir = _run(tmp_path)
    _settle_step1(root, run_id)
    _ok(_rec(root, run_id, "answer", "--gate", "fmr_extracted_values", "--answer-id", "values_ok"))
    _ok(_producer("runway.py", run_dir, run_id))
    _corrections(run_dir, None, None, "revenue.mrr=47000")
    proc = _producer("runway.py", run_dir, run_id)
    assert proc.returncode == 10 and _out(proc)["blocked_by_gate"] == "fmr_extracted_values"


def test_a_finished_run_whose_figures_changed_is_refused_and_nothing_moves(tmp_path: Path) -> None:
    root, run_id, run_dir = _run(tmp_path)
    _settle_step1(root, run_id)
    _ok(_rec(root, run_id, "answer", "--gate", "fmr_extracted_values", "--answer-id", "values_ok"))
    rs.update(rs.run_paths(str(root), run_id), lambda s: (s.update(coaching="inserted"), rs.mark_complete(s)))
    # Edited by hand: the corrections script itself refuses a finished run (the test below).
    inputs = json.loads((run_dir / "inputs.json").read_text())
    inputs["revenue"]["mrr"]["value"] = 48000
    (run_dir / "inputs.json").write_text(json.dumps(inputs))
    before = _snapshot(run_dir, root, run_id)
    proc = _producer("runway.py", run_dir, run_id)
    assert proc.returncode == 1 and _out(proc)["code"] == "RUN_FINISHED"
    assert "new review" in proc.stdout
    assert _snapshot(run_dir, root, run_id) == before


def test_a_call_with_no_run_id_into_a_bound_dir_is_refused(tmp_path: Path) -> None:
    _root, _run_id, run_dir = _run(tmp_path)
    inputs = json.loads((run_dir / "inputs.json").read_text())
    inputs.pop("metadata")
    proc = h.run(FMR / "runway.py", "-o", str(run_dir / "runway.json"), stdin=json.dumps(inputs))
    assert proc.returncode == 1 and _out(proc)["code"] == "RUN_ID_REQUIRED"


# --- compose, the report and the hand-over --------------------------------------------------------------------


def test_compose_refuses_before_writing_until_the_values_check_is_recorded(tmp_path: Path) -> None:
    root, run_id, run_dir = _run(tmp_path)
    _settle_step1(root, run_id)
    proc = _compose(run_dir)
    assert proc.returncode == 10 and _out(proc)["blocked_by_gate"] == "fmr_extracted_values"
    assert not (run_dir / "report.json").exists() and not (run_dir / "report.md").exists()


def test_unreviewed_values_are_disclosed_in_the_report_the_json_the_status_and_the_hand_over(tmp_path: Path) -> None:
    closer = _load("fmr_closer_t", FMR / "fmr_closing_message.py")
    compose = _load("fmr_compose_t", FMR / "compose_report.py")
    root, run_id, run_dir = _run(tmp_path)
    _settle_step1(root, run_id)
    _ok(_rec(root, run_id, "default", "--gate", "fmr_extracted_values", "--reason", "asked_not_to_be_asked"))
    _ok(_compose(run_dir))
    md = (run_dir / "report.md").read_text()
    report = json.loads((run_dir / "report.json").read_text())
    assert compose.EXTRACTION_UNREVIEWED_TEXT in md
    assert report["disclosures"] == ["EXTRACTION_UNREVIEWED"]
    assert "EXTRACTION_UNREVIEWED" in h.status(root, run_id)["disclosures"]
    assert closer.EXTRACTION_UNREVIEWED == compose.EXTRACTION_UNREVIEWED_TEXT
    text = _ok(
        h.run(
            FMR / "fmr_closing_message.py",
            "--report",
            str(run_dir / "report.json"),
            "--link",
            "path",
            "--deliverable",
            f"the written report={run_dir}/report.md",
        )
    ).stdout
    assert text.index(report["verdict"]) < text.index(closer.EXTRACTION_UNREVIEWED) < text.index("If you want to keep")
    assert h.status(root, run_id)["handed_over_at"] is not None


def test_values_taken_as_checked_without_asking_are_the_requests_word(tmp_path: Path) -> None:
    compose = _load("fmr_compose_t2", FMR / "compose_report.py")
    root, run_id, run_dir = _run(tmp_path, lines="FS_HOST_ANSWER fmr_extracted_values=values_ok\n")
    _settle_step1(root, run_id)
    _ok(_rec(root, run_id, "open", "--gate", "fmr_extracted_values"))
    _ok(_compose(run_dir))
    md = (run_dir / "report.md").read_text()
    assert compose.VALUES_BY_REQUEST_TEXT in md and compose.EXTRACTION_UNREVIEWED_TEXT not in md
    html = _ok(
        h.run(FMR / "visualize.py", "--dir", str(run_dir), "-o", str(run_dir / "report.html"), "--run-id", run_id)
    )
    assert html.returncode == 0 and compose.VALUES_BY_REQUEST_TEXT in (run_dir / "report.html").read_text()


def test_the_page_says_the_values_were_not_reviewed(tmp_path: Path) -> None:
    viz = _load("fmr_viz_t", FMR / "visualize.py")
    compose = _load("fmr_compose_t3", FMR / "compose_report.py")
    assert viz.EXTRACTION_UNREVIEWED_NOTE == compose.EXTRACTION_UNREVIEWED_TEXT
    assert viz.VALUES_BY_REQUEST_NOTE == compose.VALUES_BY_REQUEST_TEXT
    root, run_id, run_dir = _run(tmp_path)
    _ok(_rec(root, run_id, "default", "--gate", "fmr_extracted_values", "--reason", "asked_not_to_be_asked"))
    _ok(h.run(FMR / "visualize.py", "--dir", str(run_dir), "-o", str(run_dir / "report.html"), "--run-id", run_id))
    assert viz.EXTRACTION_UNREVIEWED_NOTE in (run_dir / "report.html").read_text()


def test_every_corrections_call_has_its_block_and_its_source(tmp_path: Path) -> None:
    compose = _load("fmr_compose_t4", FMR / "compose_report.py")
    root, run_id, run_dir = _run(tmp_path)
    _settle_step1(root, run_id)
    _opened(root, run_id)
    _corrections(run_dir, run_id, "chat", "revenue.mrr=45000")
    _ok(_rec(root, run_id, "answer", "--gate", "fmr_extracted_values", "--answer-id", "corrections_applied"))
    _corrections(run_dir, run_id, "chat", "cash.current_balance=900000", "cash.balance_date=2026-09")
    _ok(_compose(run_dir))
    md = (run_dir / "report.md").read_text()
    assert md.count("## Corrections Applied") == 1
    assert compose.CORRECTIONS_ORIGIN_TEXT["chat"] in md and compose.CORRECTIONS_ORIGIN_TEXT["cash"] in md
    assert "revenue.mrr" in md, "the cash call must not replace the earlier corrections"
    assert json.loads((run_dir / "report.json").read_text())["disclosures"] == ["CORRECTIONS_SOURCE:chat"]


def test_no_ledger_report_json_carries_no_disclosures_key(tmp_path: Path) -> None:
    for f in FIXTURES.iterdir():
        shutil.copy(f, tmp_path / f.name)
    _ok(_compose(tmp_path))
    assert "disclosures" not in json.loads((tmp_path / "report.json").read_text())


def test_an_open_question_refuses_compose_unresolved(tmp_path: Path) -> None:
    root, run_id, run_dir = _run(tmp_path)
    _settle_step1(root, run_id)
    _ok(_rec(root, run_id, "answer", "--gate", "fmr_extracted_values", "--answer-id", "values_ok"))
    _ok(_rec(root, run_id, "open", "--gate", "ctx_stage_detail"))
    proc = _compose(run_dir)
    assert proc.returncode == 10 and _out(proc)["code"] == "GATE_UNRESOLVED"
    assert not (run_dir / "report.md").exists()


def test_the_values_check_is_a_gate_error_in_verify_and_verify_writes_nothing(tmp_path: Path) -> None:
    root, run_id, run_dir = _run(tmp_path)
    before = h.snapshot(root, run_id)
    proc = h.run(FMR / "verify_review.py", "--dir", str(run_dir), "--gate", "1")
    assert proc.returncode == 1 and "Step 3.6" in proc.stdout
    assert h.snapshot(root, run_id) == before


def test_the_no_cash_runway_test_is_composes(tmp_path: Path) -> None:
    compose = _load("fmr_compose_t5", FMR / "compose_report.py")
    shapes = [
        None,
        {"skipped": True},
        {"insufficient_data": True},
        {"insufficient_data": True, "baseline": {"net_cash": None, "monthly_burn": 9000}},
        {"insufficient_data": True, "baseline": {"net_cash": None, "monthly_burn": None}},
        {"insufficient_data": True, "baseline": {"net_cash": 5, "monthly_burn": 9000}},
        {"insufficient_data": False, "baseline": {"net_cash": None, "monthly_burn": 9000}},
    ]
    for shape in shapes:
        assert g.fmr_runway_has_no_cash(shape) == (compose._runway_status(shape) == "no_cash_balance"), shape


# --- the cash follow-up cycle ----------------------------------------------------------------------------------


def _complete(root: Path, run_id: str, run_dir: Path) -> dict[str, Any]:
    st: dict[str, Any] = rs.complete_after_coaching(
        rs.run_paths(str(root), run_id), str(run_dir / "report.md"), str(run_dir / "report.json")
    )
    return st


def _verify(run_dir: Path, gate: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(h.run(FMR / "verify_review.py", "--dir", str(run_dir), "--gate", gate).stdout)
    return data


def _delivered_without_cash(tmp_path: Path) -> tuple[Path, str, Path]:
    """A delivered review built without a cash balance: its hand-over asked for one (the follow-up waits)."""
    root, run_id, run_dir = _run(tmp_path)
    inputs = json.loads((run_dir / "inputs.json").read_text())
    for k in ("current_balance", "balance_date"):
        inputs["cash"].pop(k)
    (run_dir / "inputs.json").write_text(json.dumps(inputs))
    _ok(
        _rec(
            root,
            run_id,
            "open",
            *[
                a
                for k in ("current_balance", "balance_date", "monthly_burn")
                for a in ("--gate", f"fmr_cash_basics.{k}")
            ],
        )
    )
    _ok(
        _rec(
            root,
            run_id,
            "answer",
            "--gate",
            "fmr_cash_basics.current_balance",
            "--answer-id",
            "not_stated",
            "--gate",
            "fmr_cash_basics.balance_date",
            "--answer-id",
            "not_stated",
            "--gate",
            "fmr_cash_basics.monthly_burn",
            "--answer-id",
            "stated",
            "--value",
            "120000",
        )
    )
    _opened(root, run_id)
    _corrections(run_dir, run_id, "chat", "revenue.mrr=45000")
    _ok(_rec(root, run_id, "answer", "--gate", "fmr_extracted_values", "--answer-id", "corrections_applied"))
    _ok(_producer("unit_economics.py", run_dir, run_id))
    _ok(_producer("runway.py", run_dir, run_id))
    _ok(_compose(run_dir))
    assert json.loads((run_dir / "report.json").read_text())["runway_status"] == "no_cash_balance"
    led = h.ledger(root, run_id)["gates"]
    assert led["fmr_cash_followup"]["current"]["default_reason"] == "producer_default_disclosed"
    gate1 = _verify(run_dir, "1")
    assert not any("Step 3.6" in e for e in gate1["summary"]["errors"]), gate1
    st = _complete(root, run_id, run_dir)
    assert (st["status"], st["revision"]) == ("complete", 0)
    _ok(
        h.run(
            FMR / "fmr_closing_message.py",
            "--report",
            str(run_dir / "report.json"),
            "--link",
            "path",
            "--deliverable",
            f"the written report={run_dir}/report.md",
        )
    )
    assert h.status(root, run_id)["handed_over_at"] is not None
    return root, run_id, run_dir


def test_the_cash_reply_reopens_the_run_and_completes_it_again(tmp_path: Path) -> None:
    root, run_id, run_dir = _delivered_without_cash(tmp_path)

    # The founder replies with the balance (a new prompt): the three SKILL.md Step 12 calls.
    time.sleep(0.002)
    _corrections(run_dir, run_id, "chat", "cash.current_balance=900000", "cash.balance_date=2026-09")
    # Re-composing before the reply is recorded is refused, and the founder is not asked again.
    _ok(_producer("runway.py", run_dir, run_id))
    refused = _compose(run_dir)
    assert refused.returncode == 10 and "do not ask again" in refused.stderr
    _ok(
        _rec(
            root,
            run_id,
            "answer",
            "--gate",
            "fmr_cash_followup",
            "--answer-id",
            "provided",
            "--gate",
            "fmr_cash_basics.current_balance",
            "--answer-id",
            "stated",
            "--value",
            "900000",
            "--gate",
            "fmr_cash_basics.balance_date",
            "--answer-id",
            "stated",
            "--value",
            "2026-09",
        )
    )
    st = h.status(root, run_id)
    assert (st["status"], st["revision"], st["handed_over_at"]) == ("running", 1, None)
    assert not any(d.startswith("DEFAULT_TAKEN:fmr_cash_basics.current_balance") for d in st["disclosures"])
    assert h.ledger(root, run_id)["gates"]["fmr_extracted_values"]["current"]["answer_id"] == "corrections_applied"
    _ok(_producer("runway.py", run_dir, run_id))
    _ok(_compose(run_dir))
    assert "runway_status" not in json.loads((run_dir / "report.json").read_text())
    for gate in ("1", "2"):
        assert not any("Step 3.6" in e for e in _verify(run_dir, gate)["summary"]["errors"])
    st = _complete(root, run_id, run_dir)
    assert (st["status"], st["revision"]) == ("complete", 1)
    _ok(
        h.run(
            FMR / "fmr_closing_message.py",
            "--report",
            str(run_dir / "report.json"),
            "--link",
            "path",
            "--cash-update",
            "--deliverable",
            f"the written report={run_dir}/report.md",
        )
    )
    assert h.status(root, run_id)["handed_over_at"] is not None
    # The follow-up is answered: a further balance after this delivery is a new review, and nothing moves.
    before = _snapshot(run_dir, root, run_id)
    again = _apply(run_dir, run_id, "cash.current_balance=850000", "cash.balance_date=2026-10")
    assert again.returncode == 1 and _out(again)["code"] == "RUN_FINISHED"
    assert _snapshot(run_dir, root, run_id) == before


def _delivered_with_cash(tmp: Path) -> tuple[Path, str, Path]:
    """A complete run whose review was built with the cash balance the founder gave at Step 1."""
    root, run_id, run_dir = _run(tmp)
    _settle_step1(root, run_id)
    _ok(_rec(root, run_id, "answer", "--gate", "fmr_extracted_values", "--answer-id", "values_ok"))
    _ok(_producer("unit_economics.py", run_dir, run_id))
    _ok(_producer("runway.py", run_dir, run_id))
    _ok(_compose(run_dir))
    assert _complete(root, run_id, run_dir)["status"] == "complete"
    return root, run_id, run_dir


def _apply(run_dir: Path, run_id: str | None, *sets: str) -> subprocess.CompletedProcess[str]:
    """`--set` each `PATH=VALUE`; anything else passes through as a flag."""
    args = [a for s in sets for a in (("--set", s) if "=" in s else (s,))]
    args += ["--original", str(run_dir / "inputs.json"), "--output-dir", str(run_dir)]
    if run_id is not None:
        args += ["--run-id", run_id, "--origin", "chat"]
    return h.run(FMR / "apply_corrections.py", *args)


@pytest.mark.parametrize(
    "sets",
    [("revenue.mrr=43217",), ("cash.current_balance=900000",), ("cash.balance_date=2026-09",)],
)
def test_the_waiting_follow_up_takes_both_cash_paths_and_nothing_else(tmp_path: Path, sets: tuple[str, ...]) -> None:
    """The follow-up's answer needs a call setting both cash paths; any other call is refused before it writes."""
    root, run_id, run_dir = _delivered_without_cash(tmp_path)
    before = _snapshot(run_dir, root, run_id)
    proc = _apply(run_dir, run_id, *sets)
    assert proc.returncode == 1 and _out(proc)["code"] == "RUN_FINISHED", proc.stdout + proc.stderr
    assert _snapshot(run_dir, root, run_id) == before


def test_a_call_naming_no_run_into_a_delivered_review_is_refused(tmp_path: Path) -> None:
    root, run_id, run_dir = _delivered_with_cash(tmp_path)
    original = json.loads((run_dir / "inputs.json").read_text())
    original.pop("metadata", None)
    elsewhere = tmp_path / "copy.json"
    elsewhere.write_text(json.dumps(original))
    before = _snapshot(run_dir, root, run_id)
    args = ["--set", "revenue.mrr=43217", "--original", str(elsewhere), "--output-dir", str(run_dir)]
    proc = h.run(FMR / "apply_corrections.py", *args)
    assert proc.returncode == 1 and _out(proc)["code"] == "RUN_ID_REQUIRED", proc.stdout + proc.stderr
    assert _snapshot(run_dir, root, run_id) == before


@pytest.mark.parametrize(
    ("sets", "words"),
    [
        # The balance the review already used, restated: nothing to apply, no rerun.
        (("cash.current_balance=1500000", "cash.balance_date=2026-05"), "already uses"),
        # Same amount, a later date: a changed confirmed figure after delivery is a new review.
        (("cash.current_balance=1500000", "cash.balance_date=2026-06"), "new review"),
        (("revenue.mrr=51000",), "new review"),
    ],
)
@pytest.mark.parametrize("with_run_id", [True, False])
def test_corrections_on_a_delivered_review_with_its_balance_are_refused_and_nothing_moves(
    tmp_path: Path, sets: tuple[str, ...], words: str, with_run_id: bool
) -> None:
    root, run_id, run_dir = _delivered_with_cash(tmp_path)
    before = _snapshot(run_dir, root, run_id)
    status_out = tmp_path / "apply_status.json"
    proc = _apply(run_dir, run_id if with_run_id else None, *sets, "-o", str(status_out))
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert not status_out.exists()
    assert _out(proc)["code"] == "RUN_FINISHED" and words in proc.stdout
    assert "nothing was written" in proc.stderr
    assert _snapshot(run_dir, root, run_id) == before


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores file modes")
def test_a_status_write_failure_never_changes_the_hand_over(tmp_path: Path) -> None:
    root, run_id, run_dir = _run(tmp_path)
    _ok(_rec(root, run_id, "answer", "--gate", "fmr_extracted_values", "--answer-id", "values_ok"))
    _settle_step1(root, run_id)
    _ok(_compose(run_dir))
    argv = ("--report", str(run_dir / "report.json"), "--link", "path", "--deliverable", f"r={run_dir}/report.md")
    plain = _ok(h.run(FMR / "fmr_closing_message.py", *argv)).stdout
    status = h.status_path(root, run_id)
    lock_dir = status.parent
    mode = lock_dir.stat().st_mode
    os.chmod(lock_dir, stat.S_IRUSR | stat.S_IXUSR)
    try:
        proc = h.run(FMR / "fmr_closing_message.py", *argv)
    finally:
        os.chmod(lock_dir, mode)
    assert proc.returncode == 0 and proc.stdout == plain


# --- SKILL.md ------------------------------------------------------------------------------------------------


def _section(text: str, head: str) -> str:
    start = text.index(head)
    nxt = text.find("\n### ", start + 1)
    return text[start : nxt if nxt != -1 else len(text)]


def test_step_36_opens_before_the_page_and_asks_one_question_in_the_registry_labels() -> None:
    text = SKILL_MD.read_text(encoding="utf-8")
    step = _section(text, "### Step 3.6:")
    open_at = step.index('record_gate_answer.py" open')
    assert "--gate fmr_extracted_values" in step[open_at : open_at + 200]
    assert open_at < step.index("--static") < step.index("**Path B")
    assert open_at < step.index('"applied": "pre_answer"') < step.index("**Path A")
    opts = [line for line in step.splitlines() if line.startswith("Options:")]
    shown = [o["label"] for o in g.GATES["fmr_extracted_values"]["options"] if o["shown"]]
    assert opts == ["Options: " + " / ".join(f"`{label}`" for label in shown)]
    assert f'"{g.GATES["fmr_extracted_values"]["question"]}"' in step
    assert step.count("then ask") == 2 and step.count("`AskUserQuestion`") >= 2


def test_step_1_opens_its_questions_before_it_asks() -> None:
    step = _section(SKILL_MD.read_text(encoding="utf-8"), "### Step 1:")
    first_ask = (
        step.index("use `AskUserQuestion`") if "use `AskUserQuestion`" in step else step.index("Use `AskUserQuestion`")
    )
    assert step.index("Open the questions (the block below) first.") < first_ask
    assert step.count("Open the questions (the block below) first.") == 2
    assert "**Exit 1 (not found: no `code`, or `CONTEXT_NOT_FOUND`)" in step
    assert "Exit 1 with another `code`: report it and stop." in step
    assert '--run-id "$RUN_ID" --skill financial-model-review' in step


def test_the_gate_sites_are_the_registrys_both_ways() -> None:
    import re

    text = SKILL_MD.read_text(encoding="utf-8")
    sites = set(re.findall(r"--gate ([a-z][a-z0-9_]*(?:\.[a-z_]+)?)", text))
    sites |= set(re.findall(r"<!-- gate: ([a-z][a-z0-9_]*(?:\.[A-Za-z0-9_.+-]+)?) -->", text))
    sites.discard("fmr_cash_basics")  # the `--gate <gate>` placeholder sentence names none
    registry = set()
    for gid, gd in g.GATES.items():
        if gd["skill"] not in ("financial-model-review", "shared"):
            continue
        inst = gd["instances"]
        registry |= {f"{gid}.{i}" for i in inst["static"]} if inst else {gid}
    assert sites == registry


def test_the_pages_the_exits_and_the_delivery_close_carry_the_run() -> None:
    text = SKILL_MD.read_text(encoding="utf-8")
    assert 'report.html" --run-id "$RUN_ID"' in text and 'explore.html" --run-id "$RUN_ID"' in text
    assert "never re-run compose without the answer" in _section(text, "### Step 7:")
    assert "Exit 10 from either is a question" in _section(text, "### Step 4:")
    step12 = _section(text, "### Step 12:")
    assert step12.index("--final || :") < step12.index("fmr_closing_message.py")
    for origin in ("inputs_review", "upload", "chat"):
        assert f'--run-id "$RUN_ID" --origin {origin}' in text
    quick = _section(text, "#### Step 5-quick")
    assert quick.index("bound the run") < quick.index("runway.py")
    assert "finish --mode quick_check" in quick


def test_the_catalog_sections_are_gone_and_the_shared_references_stay_on_one_line() -> None:
    text = SKILL_MD.read_text(encoding="utf-8")
    for heading in ("## Skill Metadata", "## Available Scripts", "## Available References"):
        assert heading not in text
    line = next(ln for ln in text.splitlines() if "${CLAUDE_PLUGIN_ROOT}/references/` (shared)" in ln)
    for name in (
        "stage-expectations.md",
        "benchmarks.md",
        "israel-guidance.md",
        "revenue-model-types.md",
        "common-mistakes.md",
    ):
        assert name in line


# --- the --after-hold hint, the ignored request line, the follow-up's runway -----------------------------------


def test_a_held_gates_standing_answer_names_after_hold_unless_the_request_gave_it(tmp_path: Path) -> None:
    root, run_id, _rd = _run(tmp_path / "model")
    _ok(_rec(root, run_id, "answer", "--gate", "fmr_extracted_values", "--answer-id", "values_ok"))
    refused = _rec(root, run_id, "answer", "--gate", "fmr_extracted_values", "--answer-id", "proceed_unreviewed")
    assert _out(refused)["code"] == "ANSWER_STANDS" and "--after-hold" in _out(refused)["message"]

    root, run_id, _rd = _run(tmp_path / "host", lines="FS_HOST_ANSWER fmr_extracted_values=values_ok\n")
    assert _out(_ok(_rec(root, run_id, "open", "--gate", "fmr_extracted_values")))["applied"] == "pre_answer"
    refused = _rec(root, run_id, "answer", "--gate", "fmr_extracted_values", "--answer-id", "proceed_unreviewed")
    assert _out(refused)["code"] == "ANSWER_STANDS" and "--after-hold" not in _out(refused)["message"]


def test_bind_lists_a_request_line_for_a_gate_its_mode_closed_as_ignored(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    run_id = h.start_ok(
        root, "financial-model-review", "FS_HOST_VALUE fmr_cash_basics.current_balance=stated | 400000\n"
    )
    # Opened before the mode was known; the request line is still pending (`open` applies it only once asked).
    led = h.ledger(root, run_id)
    paths = rs.run_paths(str(root), run_id)
    g.transact(paths, lambda c, ledger, s: g._open_entry(ledger, "fmr_cash_basics.current_balance", "test"))
    assert led["pre_answers"]["fmr_cash_basics.current_balance"]["applied_at"] is None
    _ok(h.bind(root, run_id, root / "financial-model-review-example-co-quickcheck", "example-co"))
    notices = [n for n in h.status(root, run_id)["notices"] if n["code"] == "PRE_ANSWER_IGNORED"]
    assert [n["gate"] for n in notices] == ["fmr_cash_basics.current_balance"]
    assert h.ledger(root, run_id)["gates"]["fmr_cash_basics.current_balance"]["state"] == "not_owed"


def test_the_cash_follow_up_reads_only_this_runs_runway(tmp_path: Path) -> None:
    root, run_id, run_dir = _run(tmp_path)
    no_cash = {"insufficient_data": True, "baseline": {"net_cash": None, "monthly_burn": 9000}}
    (run_dir / "runway.json").write_text(json.dumps({**no_cash, "metadata": {"run_id": "20260101T000000Z-aaaaaa"}}))
    assert _rec(root, run_id, "require", "--gate", "fmr_cash_followup").returncode == 11
    (run_dir / "runway.json").write_text(json.dumps({**no_cash, "metadata": {"run_id": run_id}}))
    assert _rec(root, run_id, "require", "--gate", "fmr_cash_followup").returncode == 10
