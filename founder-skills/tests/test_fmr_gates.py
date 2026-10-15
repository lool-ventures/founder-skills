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


def test_the_closer_refuses_a_report_composed_for_another_run(tmp_path: Path) -> None:
    """Bound: the refusal prints nothing, writes no handover.txt and leaves the run status byte-identical (so a
    what-if after an earlier hand-over keeps that hand-over's stamp, and an unhanded run gains none)."""
    root, run_id, run_dir = _run(tmp_path)
    _settle_step1(root, run_id)
    _ok(_rec(root, run_id, "default", "--gate", "fmr_extracted_values", "--reason", "asked_not_to_be_asked"))
    _ok(_compose(run_dir))
    report = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
    assert report["run_id"] == run_id and report.get("verdict")  # the stamp is this run's; a verdict to print
    report["run_id"] = "20261001T090000Z-0f0f0f"
    (run_dir / "report.json").write_text(json.dumps(report), encoding="utf-8")
    before = h.status_path(root, run_id).read_bytes()
    proc = h.run(FMR / "fmr_closing_message.py", "--report", str(run_dir / "report.json"), "--link", "path")
    assert proc.returncode == 2 and proc.stdout == "" and "RUN_ID_MISMATCH" in proc.stderr, proc
    assert not (run_dir / "handover.txt").exists()
    assert h.status(root, run_id)["handed_over_at"] is None
    assert h.status_path(root, run_id).read_bytes() == before


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
    # Both calls were made before any delivery: a cash call is "after the review" only when it is the history
    # line the cash follow-up's recorded answer names, never by which paths it set.
    assert md.count(compose.CORRECTIONS_ORIGIN_TEXT["chat"]) == 2 and compose.CORRECTIONS_ORIGIN_TEXT["cash"] not in md
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
    # Compose records its own disclosed default while the run is running, under its own name: the recorder's
    # default on a delivered review is refused by that name, and compose refuses on a delivered review.
    assert led["fmr_cash_followup"]["history"][-1]["by"] == "compose_report.py"
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
        # A newer balance or date updates the review in place only as both cash paths and nothing else (the
        # same amount at a later date is accepted: test_a_later_balance_date_after_delivery_...).
        (("cash.balance_date=2026-06",), "new review"),
        (("cash.current_balance=1500000", "cash.balance_date=2026-06", "revenue.mrr=51000"), "new review"),
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
        if gd["reads_in"] and "financial-model-review" not in gd["reads_in"]:
            continue  # a shared gate only other skills read: this skill never opens it
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


# --- a newer cash balance or date after delivery ----------------------------------------------------------
#
# Built through the real chain: the checklist piped from a gated hand-off with `--inputs` (so its fingerprint
# is real), the commentary, and the coaching inserted by `md_to_commentary.py | insert_coaching.py`, so both
# verification gates are asserted whole rather than filtered for one message.

COMMENTARY = {
    "headline": "An invented headline for the test.",
    "lenses": {"runway": {"callout": "An invented callout."}, "unit_economics": {"callout": "Another one."}},
}


def _gate_file(path: Path, *flags: str) -> None:
    _ok(h.run(h.SHARED / "check_handoff.py", str(path), *flags))


def _handoff_dir(run_dir: Path, run_id: str, revision: int) -> Path:
    hd = run_dir / "handoff" / run_id
    if revision:
        hd = hd / f"r{revision}"
    hd.mkdir(parents=True, exist_ok=True)
    return hd


def _checklist(run_dir: Path, run_id: str, revision: int = 0) -> None:
    """Step 5: the sub-agent's hand-off (the fixture's grades), gated, piped with `--inputs`."""
    handoff = _handoff_dir(run_dir, run_id, revision) / "checklist_output.json"
    items = json.loads((FIXTURES / "checklist.json").read_text())["items"]
    keep = ("id", "status", "evidence", "notes")
    handoff.write_text(json.dumps({"items": [{k: i.get(k) for k in keep} for i in items]}))
    _gate_file(handoff)
    args = ("--run-id", run_id, "--inputs", str(run_dir / "inputs.json"), "-o", str(run_dir / "checklist.json"))
    _ok(h.run(FMR / "checklist.py", *args, stdin=handoff.read_text()))


def _coach(run_dir: Path, run_id: str, revision: int = 0) -> None:
    """Step 8c: the coaching hand-off, gated, wrapped and inserted by the shared scripts."""
    marker = json.loads((run_dir / "report.json").read_text())["coaching_payload"]["insertion_marker"]
    md = _handoff_dir(run_dir, run_id, revision) / "coaching.md"
    md.write_text("Invented coaching for this test.\n")
    _gate_file(md, "--format", "markdown", "--marker", marker)
    envelope = _ok(h.run(h.SHARED / "md_to_commentary.py", str(md))).stdout
    args = ["--report", str(run_dir / "report.md"), "--report-json", str(run_dir / "report.json"), "--marker", marker]
    for name in ("inputs.json", "checklist.json", "unit_economics.json", "runway.json"):
        args += ["--verify-artifact", str(run_dir / name)]
    _ok(h.run(h.SHARED / "insert_coaching.py", *args, stdin=envelope))


def _gates_clean(run_dir: Path) -> None:
    for gate in ("1", "2"):
        out = _verify(run_dir, gate)
        assert out["summary"]["errors"] == [], (gate, out["summary"])


def _build(root: Path, run_id: str, run_dir: Path, revision: int = 0, *, checklist: bool = True) -> None:
    """Steps 4, 5, 7, 7.5 and 8c for one revision."""
    _ok(_producer("unit_economics.py", run_dir, run_id))
    _ok(_producer("runway.py", run_dir, run_id))
    if checklist:
        _checklist(run_dir, run_id, revision)
    (run_dir / "commentary.json").write_text(json.dumps(COMMENTARY))
    _ok(_compose(run_dir))
    _coach(run_dir, run_id, revision)


def _close(run_dir: Path, *flags: str) -> str:
    argv = ("--report", str(run_dir / "report.json"), "--link", "path", "--deliverable", f"r={run_dir}/report.md")
    return _ok(h.run(FMR / "fmr_closing_message.py", *argv, *flags)).stdout


def _delivered_real(tmp: Path) -> tuple[Path, str, Path]:
    """A review built with the founder's Step 1 balance, delivered and handed over."""
    root, run_id, run_dir = _run(tmp)
    _settle_step1(root, run_id)
    _ok(_rec(root, run_id, "answer", "--gate", "fmr_extracted_values", "--answer-id", "values_ok"))
    _build(root, run_id, run_dir)
    _gates_clean(run_dir)
    st = h.status(root, run_id)
    assert (st["status"], st["revision"], st["coaching"]) == ("complete", 0, "inserted")
    _close(run_dir)
    return root, run_id, run_dir


# The founder's reply in the observed shape: the amount the review used, one month later.
CASH_REPLY = ("cash.current_balance=1500000", "cash.balance_date=2026-06")


def _cash_answer(root: Path, run_id: str, balance: str, date: str) -> subprocess.CompletedProcess[str]:
    """Step 12's record: the follow-up first, so its `reopens` effect re-opens the two basics it re-answers."""
    return _rec(
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
        balance,
        "--gate",
        "fmr_cash_basics.balance_date",
        "--answer-id",
        "stated",
        "--value",
        date,
    )


def _history(run_dir: Path) -> list[dict[str, Any]]:
    lines = (run_dir / "extraction_corrections.history.jsonl").read_text().splitlines()
    return [json.loads(x) for x in lines]


def test_a_later_balance_date_after_delivery_reopens_the_run_and_completes_it_again(tmp_path: Path) -> None:
    root, run_id, run_dir = _delivered_real(tmp_path)
    first_report = (run_dir / "report.md").read_text()
    time.sleep(0.002)
    _ok(_apply(run_dir, run_id, *CASH_REPLY))
    last = _history(run_dir)[-1]
    assert (last["changed_count"], last["origin"]) == (1, "chat")
    _ok(_cash_answer(root, run_id, "1500000", "2026-06"))
    shutil.copy(run_dir / "corrected_inputs.json", run_dir / "inputs.json")
    st = h.status(root, run_id)
    assert (st["status"], st["revision"], st["handed_over_at"], st["deliverables"]) == ("running", 1, None, None)
    assert st["invocations"][-1]["kind"] == "reopen"
    assert st["invocations"][-1]["resumed_from"]["gate"] == "fmr_cash_followup"
    led = h.ledger(root, run_id)["gates"]
    assert led["fmr_cash_followup"]["current"]["evidence"]["history_seq"] == last["seq"]
    assert led["fmr_cash_basics.balance_date"]["current"]["value"] == "2026-06"
    assert led["fmr_extracted_values"]["current"]["answer_id"] == "values_ok"

    _build(root, run_id, run_dir, revision=1)
    _gates_clean(run_dir)
    st = h.status(root, run_id)
    assert (st["status"], st["revision"]) == ("complete", 1)
    assert {d["revision"] for d in st["deliverables"].values()} == {1}
    report = (run_dir / "report.md").read_text()
    assert report != first_report and "The cash balance you gave after the review" in report
    assert "I've used the cash balance you gave me" in _close(run_dir, "--cash-update")
    assert h.status(root, run_id)["handed_over_at"] is not None

    # One update per review: a further balance is a new review, and nothing moves.
    before = _snapshot(run_dir, root, run_id)
    again = _apply(run_dir, run_id, "cash.current_balance=1462803", "cash.balance_date=2026-07")
    assert again.returncode == 1 and _out(again)["code"] == "RUN_FINISHED"
    assert _snapshot(run_dir, root, run_id) == before
    # And a recompose is refused without offering the update the review already took.
    proc = _compose(run_dir)
    assert proc.returncode == 1 and _out(proc)["code"] == "RUN_FINISHED", proc.stdout + proc.stderr
    assert "already taken" in _out(proc)["message"] and "Step 12" not in _out(proc)["message"]
    assert h.snapshot(root, run_id) == (before["status"], before["ledger"])


def _hand_edit(path: Path, fn: Any) -> None:
    data = json.loads(path.read_text())
    fn(data)
    path.write_text(json.dumps(data))


def test_an_unrecorded_cash_update_cannot_rebuild_the_delivered_review_in_place(tmp_path: Path) -> None:
    """The apply is allowed; skipping the record must not let compose replace the delivered review at the same
    revision with no reopen."""
    root, run_id, run_dir = _delivered_real(tmp_path)
    delivered = (run_dir / "report.md").read_bytes()
    time.sleep(0.002)
    _ok(_apply(run_dir, run_id, *CASH_REPLY))
    shutil.copy(run_dir / "corrected_inputs.json", run_dir / "inputs.json")
    _ok(_producer("unit_economics.py", run_dir, run_id))
    _ok(_producer("runway.py", run_dir, run_id))
    proc = _compose(run_dir)
    assert proc.returncode == 10 and _out(proc)["blocked_by_gate"] == "fmr_cash_followup", proc.stdout + proc.stderr
    assert "do not ask again" in proc.stderr
    assert (run_dir / "report.md").read_bytes() == delivered
    st = h.status(root, run_id)
    assert (st["status"], st["revision"]) == ("complete", 0)


def test_skipping_the_checklist_after_a_cash_update_fails_gate_1(tmp_path: Path) -> None:
    """Step 12's redo list includes Step 5: the checklist graded the inputs the cash update changed."""
    root, run_id, run_dir = _delivered_real(tmp_path)
    time.sleep(0.002)
    _ok(_apply(run_dir, run_id, *CASH_REPLY))
    _ok(_cash_answer(root, run_id, "1500000", "2026-06"))
    shutil.copy(run_dir / "corrected_inputs.json", run_dir / "inputs.json")
    _ok(_producer("unit_economics.py", run_dir, run_id))
    _ok(_producer("runway.py", run_dir, run_id))
    _ok(_compose(run_dir))
    errors = _verify(run_dir, "1")["summary"]["errors"]
    assert any("checklist" in e.lower() and "CHECKLIST" in e for e in errors), errors


def test_a_reopened_revision_needs_its_own_checklist_hand_off(tmp_path: Path) -> None:
    """Re-piping revision 0's hand-off into the new revision's checklist is named, not passed."""
    root, run_id, run_dir = _delivered_real(tmp_path)
    time.sleep(0.002)
    _ok(_apply(run_dir, run_id, *CASH_REPLY))
    _ok(_cash_answer(root, run_id, "1500000", "2026-06"))
    shutil.copy(run_dir / "corrected_inputs.json", run_dir / "inputs.json")
    _ok(_producer("unit_economics.py", run_dir, run_id))
    _ok(_producer("runway.py", run_dir, run_id))
    old = run_dir / "handoff" / run_id / "checklist_output.json"
    args = ("--run-id", run_id, "--inputs", str(run_dir / "inputs.json"), "-o", str(run_dir / "checklist.json"))
    _ok(h.run(FMR / "checklist.py", *args, stdin=old.read_text()))
    _ok(_compose(run_dir))
    codes = [w.get("code") for w in json.loads((run_dir / "report.json").read_text())["validation"]["warnings"]]
    assert "HANDOFF_BYPASSED" in codes
    _checklist(run_dir, run_id, revision=1)
    _ok(_compose(run_dir))
    codes = [w.get("code") for w in json.loads((run_dir / "report.json").read_text())["validation"]["warnings"]]
    assert "HANDOFF_BYPASSED" not in codes


def test_a_cash_call_made_before_delivery_does_not_reopen_the_review(tmp_path: Path) -> None:
    """Only a call made after the delivered report was listed is a reply to the delivered review."""
    root, run_id, run_dir = _run(tmp_path)
    _settle_step1(root, run_id)
    _opened(root, run_id)
    _corrections(run_dir, run_id, "chat", "cash.current_balance=1462803", "cash.balance_date=2026-05")
    _ok(_rec(root, run_id, "answer", "--gate", "fmr_extracted_values", "--answer-id", "corrections_applied"))
    _build(root, run_id, run_dir)
    assert h.status(root, run_id)["status"] == "complete"
    before = _snapshot(run_dir, root, run_id)
    proc = _cash_answer(root, run_id, "1462803", "2026-05")
    assert proc.returncode == 1 and _out(proc)["code"] == "GATE_NOT_OWED", proc.stdout + proc.stderr
    assert _snapshot(run_dir, root, run_id) == before


def test_a_cash_call_on_a_complete_run_with_no_delivery_time_is_undecidable(tmp_path: Path) -> None:
    root, run_id, run_dir = _delivered_real(tmp_path)
    time.sleep(0.002)
    _ok(_apply(run_dir, run_id, *CASH_REPLY))
    _hand_edit(h.status_path(root, run_id), lambda st: st["deliverables"].pop("report_md"))
    before = _snapshot(run_dir, root, run_id)
    proc = _cash_answer(root, run_id, "1500000", "2026-06")
    assert proc.returncode == 2 and _out(proc)["code"] == "GATE_UNDECIDABLE", proc.stdout + proc.stderr
    assert _snapshot(run_dir, root, run_id) == before


def test_a_run_whose_request_said_not_to_ask_keeps_its_delivered_review(tmp_path: Path) -> None:
    """Attended only: under FS_HOST_NO_ASK the follow-up cannot be answered, so the apply writes nothing."""
    root, run_id, run_dir = _delivered_real(tmp_path)
    _hand_edit(h.ledger_path(root, run_id), lambda led: led.update(no_ask={}))
    before = _snapshot(run_dir, root, run_id)
    proc = _apply(run_dir, run_id, *CASH_REPLY)
    assert proc.returncode == 1 and _out(proc)["code"] == "RUN_FINISHED", proc.stdout + proc.stderr
    assert _snapshot(run_dir, root, run_id) == before
    # A pin, not a lever: the no-ask check refuses the default before the finished-run check is reached, so
    # this passes with that check removed, by design.
    proc = _default(root, run_id)
    assert proc.returncode == 1 and _out(proc)["code"] == "NO_ASK_DEFAULT", proc.stdout + proc.stderr
    assert _snapshot(run_dir, root, run_id) == before


def test_a_refused_run_takes_no_cash_update(tmp_path: Path) -> None:
    root, run_id, run_dir = _delivered_real(tmp_path)
    _hand_edit(h.status_path(root, run_id), lambda st: st.update(status="refused"))
    before = _snapshot(run_dir, root, run_id)
    proc = _apply(run_dir, run_id, *CASH_REPLY)
    assert proc.returncode == 1 and _out(proc)["code"] == "RUN_FINISHED", proc.stdout + proc.stderr
    assert _snapshot(run_dir, root, run_id) == before


def test_an_archived_copy_takes_no_cash_update(tmp_path: Path) -> None:
    """Refused, not adopted: the update runs in the review's own folder."""
    root, run_id, run_dir = _delivered_real(tmp_path)
    copy = root / "archive" / run_dir.name
    shutil.copytree(run_dir, copy)
    time.sleep(0.002)
    proc = _apply(copy, run_id, *CASH_REPLY)
    assert proc.returncode == 1 and _out(proc)["code"] == "RUN_FINISHED", proc.stdout + proc.stderr
    assert not (copy / "corrected_inputs.json").exists()
    assert not (copy / "extraction_corrections.history.jsonl").exists()
    # The recorder, pointed at the copy, refuses even with the reply on record in the run's own folder.
    _ok(_apply(run_dir, run_id, *CASH_REPLY))
    before = h.snapshot(root, run_id)
    args = ("--run-id", run_id, "--run-dir", str(copy), "--gate", "fmr_cash_followup", "--answer-id", "provided")
    proc = h.run(h.RECORD, "answer", *args)
    assert proc.returncode == 1 and _out(proc)["code"] == "RUN_SUPERSEDED", proc.stdout + proc.stderr
    assert h.snapshot(root, run_id) == before
    # And so does a default pointed at the copy: the copy is refused before anything about the run is read.
    dargs = ("--run-id", run_id, "--run-dir", str(copy), "--gate", "fmr_cash_followup")
    proc = h.run(h.RECORD, "default", *dargs, "--reason", "producer_default_disclosed")
    assert proc.returncode == 1 and _out(proc)["code"] == "RUN_SUPERSEDED", proc.stdout + proc.stderr
    assert h.snapshot(root, run_id) == before


@pytest.mark.parametrize("marked", [True, False])
def test_a_cash_reply_recorded_after_a_later_run_took_the_folder_is_refused(tmp_path: Path, marked: bool) -> None:
    """The folder's refs decide who holds it; the status's `superseded_by` is only its mirror (a later bind's
    marking can time out), so the recorder refuses on either and never takes the folder back."""
    root, run_id, run_dir = _delivered_real(tmp_path)
    time.sleep(0.002)
    _ok(_apply(run_dir, run_id, *CASH_REPLY))
    later = "20261008T095000Z-ee0006"
    h.start_ok(root, "financial-model-review", f"FS_HOST_RUN_ID={later}\n")
    _ok(h.bind(root, later, run_dir, "example-co"))
    if not marked:
        _hand_edit(h.status_path(root, run_id), lambda st: st.update(superseded_by=None))
    before = (h.snapshot(root, run_id), h.snapshot(root, later))
    proc = _cash_answer(root, run_id, "1500000", "2026-06")
    assert proc.returncode == 1 and _out(proc)["code"] == "RUN_SUPERSEDED", proc.stdout + proc.stderr
    assert (h.snapshot(root, run_id), h.snapshot(root, later)) == before
    assert rs.folder_current_run(str(run_dir)) == later


def _default(
    root: Path, run_id: str, reason: str = "producer_default_disclosed", answer_id: str | None = None
) -> subprocess.CompletedProcess[str]:
    extra = ("--answer-id", answer_id) if answer_id else ()
    return _rec(root, run_id, "default", "--gate", "fmr_cash_followup", "--reason", reason, *extra)


@pytest.mark.parametrize(
    ("reason", "answer_id"), [("producer_default_disclosed", None), ("stated_in_request", "provided")]
)
def test_a_default_on_a_delivered_review_is_refused_and_the_reply_still_records(
    tmp_path: Path, reason: str, answer_id: str | None
) -> None:
    """Only the founder's recorded reply reopens a delivered review. With a post-delivery cash call on record,
    the recorder's default is refused `RUN_FINISHED` and writes nothing (it used to record, leaving a notice on
    a review in which nothing had changed), and the reply given after delivery is still accepted after it."""
    root, run_id, run_dir = _delivered_real(tmp_path)
    time.sleep(0.002)
    _ok(_apply(run_dir, run_id, *CASH_REPLY))
    before = _snapshot(run_dir, root, run_id)
    proc = _default(root, run_id, reason, answer_id)
    assert proc.returncode == 1 and _out(proc)["code"] == "RUN_FINISHED", proc.stdout + proc.stderr
    assert "record that answer" in _out(proc)["message"]
    assert _snapshot(run_dir, root, run_id) == before
    _ok(_cash_answer(root, run_id, "1500000", "2026-06"))
    st = h.status(root, run_id)
    assert (st["status"], st["revision"]) == ("running", 1)
    assert (
        h.ledger(root, run_id)["gates"]["fmr_cash_followup"]["current"]["evidence"]["history_seq"]
        == (_history(run_dir)[-1]["seq"])
    )


@pytest.mark.parametrize(
    ("reason", "answer_id"), [("producer_default_disclosed", None), ("stated_in_request", "provided")]
)
def test_a_recorder_default_keeps_its_old_code_where_nothing_was_reopenable(
    tmp_path: Path, reason: str, answer_id: str | None
) -> None:
    """The refusal above is placed after the owed and terminal-entry checks: with no post-delivery cash call
    the follow-up is not owed (`GATE_NOT_OWED`), and where it already holds compose's own default the
    recorder's default is `ANSWER_STANDS` (the founder's reply is recorded with `answer`)."""
    root, run_id, run_dir = _delivered_real(tmp_path)
    proc = _default(root, run_id, reason, answer_id)
    assert proc.returncode == 1 and _out(proc)["code"] == "GATE_NOT_OWED", proc.stdout + proc.stderr
    root, run_id, run_dir = _delivered_without_cash(tmp_path / "without")
    proc = _default(root, run_id, reason, answer_id)
    assert proc.returncode == 1 and _out(proc)["code"] == "ANSWER_STANDS", proc.stdout + proc.stderr


def test_the_post_delivery_cash_call_is_none_off_a_full_review(tmp_path: Path) -> None:
    """The follow-up is a full review's. The predicate the recorder, the allowance and compose read finds the
    call on a delivered full review and nothing once the run's mode is another. The transact writes nothing
    here: on a final status `settle_owed` returns at once."""
    root, run_id, run_dir = _delivered_real(tmp_path)
    time.sleep(0.002)
    _ok(_apply(run_dir, run_id, *CASH_REPLY))
    paths = rs.run_paths(str(root), run_id)
    assert g.transact(paths, lambda c, led, s: g.fmr_post_delivery_cash_call(c)) is not None  # the lever engaged
    _hand_edit(h.status_path(root, run_id), lambda st: st.update(mode="quick_check"))
    assert g.transact(paths, lambda c, led, s: g.fmr_post_delivery_cash_call(c)) is None


def test_a_default_on_a_delivered_review_another_run_replaced_is_refused(tmp_path: Path) -> None:
    root, run_id, run_dir = _delivered_real(tmp_path)
    time.sleep(0.002)
    _ok(_apply(run_dir, run_id, *CASH_REPLY))
    later = "20261008T095000Z-ee0007"
    h.start_ok(root, "financial-model-review", f"FS_HOST_RUN_ID={later}\n")
    _ok(h.bind(root, later, run_dir, "example-co"))
    before = (h.snapshot(root, run_id), h.snapshot(root, later))
    proc = _default(root, run_id)
    assert proc.returncode == 1 and _out(proc)["code"] == "RUN_SUPERSEDED", proc.stdout + proc.stderr
    assert (h.snapshot(root, run_id), h.snapshot(root, later)) == before
    assert rs.folder_current_run(str(run_dir)) == later


def test_a_repeated_coaching_insert_does_not_move_the_delivery(tmp_path: Path) -> None:
    """A retried Step 8c on the delivered report (`already_inserted`) changes nothing, so a reply given before
    it is still a reply to the delivered review, and compose still refuses to rebuild it unrecorded."""
    root, run_id, run_dir = _delivered_real(tmp_path)
    listed = h.status(root, run_id)["deliverables"]
    time.sleep(0.002)
    _ok(_apply(run_dir, run_id, *CASH_REPLY))
    time.sleep(0.002)
    _coach(run_dir, run_id)
    assert h.status(root, run_id)["deliverables"] == listed
    shutil.copy(run_dir / "corrected_inputs.json", run_dir / "inputs.json")
    _ok(_producer("runway.py", run_dir, run_id))
    assert _compose(run_dir).returncode == 10
    _ok(_cash_answer(root, run_id, "1500000", "2026-06"))
    assert h.status(root, run_id)["revision"] == 1


def test_a_finished_quick_check_takes_no_cash_update(tmp_path: Path) -> None:
    """The follow-up belongs to a full review; a complete run of any other mode writes nothing."""
    root, run_id, run_dir = _delivered_real(tmp_path)
    _hand_edit(h.status_path(root, run_id), lambda st: st.update(mode="quick_check"))
    before = _snapshot(run_dir, root, run_id)
    proc = _apply(run_dir, run_id, *CASH_REPLY)
    assert proc.returncode == 1 and _out(proc)["code"] == "RUN_FINISHED", proc.stdout + proc.stderr
    assert _snapshot(run_dir, root, run_id) == before


# --- a delivered review is never rebuilt in place --------------------------------------------------------------


@pytest.mark.parametrize(
    "sets",
    [
        ("cash.current_balance=", "cash.balance_date=2026-06"),
        ("cash.current_balance=null", "cash.balance_date=2026-06"),
        ("cash.current_balance=-", "cash.balance_date=2026-06"),
        ("cash.current_balance= ", "cash.balance_date=2026-06"),
        ("cash.current_balance=,", "cash.balance_date=2026-06"),
        ("cash.current_balance=true", "cash.balance_date=2026-06"),
        ("cash.current_balance=NaN", "cash.balance_date=2026-06"),
        ("cash.current_balance=1500000", "cash.balance_date="),
        ("cash.current_balance=1500000", "cash.balance_date=n/a"),
        ("cash.current_balance=1500000", "cash.balance_date=2026-6"),
        ("cash.current_balance=1500000", "cash.balance_date=2026-06-15"),
    ],
    ids=[
        "blank",
        "null",
        "dash",
        "space",
        "comma",
        "true",
        "nan",
        "date-blank",
        "date-n/a",
        "date-2026-6",
        "date-full-day",
    ],
)
def test_a_cash_update_that_removes_the_balance_is_refused(tmp_path: Path, sets: tuple[str, ...]) -> None:
    """The one update a delivered review takes gives a cash balance and its month. One that blanks either, or
    gives a value that is no balance (a bool, NaN) or no month, would reopen the review and rebuild it without
    its runway: refused before anything is written."""
    root, run_id, run_dir = _delivered_real(tmp_path)
    before = _snapshot(run_dir, root, run_id)
    time.sleep(0.002)
    proc = _apply(run_dir, run_id, *sets)
    assert proc.returncode == 1 and _out(proc)["code"] == "RUN_FINISHED", proc.stdout + proc.stderr
    assert "gives a cash balance and its month (YYYY-MM" in _out(proc)["message"]
    assert _snapshot(run_dir, root, run_id) == before
    assert not (run_dir / "corrected_inputs.json").exists()


def test_a_cash_update_that_gives_a_balance_and_its_month_is_still_taken(tmp_path: Path) -> None:
    """The control for the refusal above: the same review takes the founder's reply."""
    root, run_id, run_dir = _delivered_real(tmp_path)
    time.sleep(0.002)
    _ok(_apply(run_dir, run_id, *CASH_REPLY))
    assert (run_dir / "corrected_inputs.json").exists()


def test_compose_on_a_delivered_review_with_a_no_cash_runway_is_refused(tmp_path: Path) -> None:
    """A delivered review whose runway lost its balance is not rebuilt with compose's own default: the default is
    for a running review only, and the refusal is a JSON line, never a traceback."""
    root, run_id, run_dir = _delivered_real(tmp_path)
    _hand_edit(run_dir / "inputs.json", lambda d: d["cash"].update(current_balance=None))
    _ok(_producer("runway.py", run_dir, run_id))
    delivered = (run_dir / "report.md").read_bytes()
    before = h.snapshot(root, run_id)
    proc = _compose(run_dir)
    assert proc.returncode == 1 and _out(proc)["code"] == "RUN_FINISHED", proc.stdout + proc.stderr
    assert "Traceback" not in proc.stderr
    assert (run_dir / "report.md").read_bytes() == delivered
    assert h.snapshot(root, run_id) == before
    st = h.status(root, run_id)
    assert (st["status"], st["revision"], st.get("disclosures") or []) == ("complete", 0, [])


@pytest.mark.parametrize("delivered", ["real", "without_cash", "refused"])
def test_a_delivered_review_is_never_recomposed_in_place(tmp_path: Path, delivered: str) -> None:
    """Building the report again on a delivered review, with nothing changed, used to exit 0 and replace the
    delivered report at the same revision, dropping its coaching. It is refused, and nothing moves. A stopped
    (`refused`) review is refused the same way, with its own wording: it takes no cash update."""
    make = _delivered_without_cash if delivered == "without_cash" else _delivered_real
    root, run_id, run_dir = make(tmp_path)
    if delivered == "refused":
        _hand_edit(h.status_path(root, run_id), lambda st: st.update(status="refused"))
    report = (run_dir / "report.md").read_bytes()
    if delivered != "without_cash":
        assert b"## Coaching Commentary" in report  # the lever engaged: a rebuild would drop it
    before = h.snapshot(root, run_id)
    proc = _compose(run_dir)
    assert proc.returncode == 1 and _out(proc)["code"] == "RUN_FINISHED", proc.stdout + proc.stderr
    assert ("was stopped" in _out(proc)["message"]) == (delivered == "refused"), _out(proc)
    assert "Traceback" not in proc.stderr
    assert h.snapshot(root, run_id) == before
    assert (run_dir / "report.md").read_bytes() == report


def test_a_cash_update_is_always_revision_1() -> None:
    """Step 12 names the revision's hand-off folder `r1` literally. That holds because nothing else reopens a
    financial-model-review run: its only `reopens_complete` gate is the cash follow-up, whose one reply is the
    review's one update (an answered follow-up refuses another), and no FMR script reopens for a recompose. A
    change to any of these must revisit Step 12's `r1`."""
    fmr_reopening = [k for k, v in g.GATES.items() if v["skill"] == "financial-model-review" and v["reopens_complete"]]
    assert fmr_reopening == ["fmr_cash_followup"]
    for script in FMR.glob("*.py"):
        text = script.read_text(encoding="utf-8")
        assert "reopen_for_recompose" not in text and "reopen_if_complete" not in text, script.name
    assert '"$RUN_ID/r1"' in SKILL_MD.read_text(encoding="utf-8")


def test_a_cash_updates_redo_writes_its_hand_offs_to_the_revision_folder() -> None:
    """Step 12 sends the model back through Steps 5 and 8c, whose blocks set HANDOFF_AGENT from Step 0: both
    must say the revision's `r1` values win there, or the CHECKLIST overwrites the delivered review's hand-off."""
    text = SKILL_MD.read_text(encoding="utf-8")
    step5 = _section(text, "### Step 5:")
    line = next(x for x in step5.splitlines() if x.startswith("HANDOFF_AGENT="))
    assert "Step 12's r1 value" in line
    step12 = _section(text, "### Step 12:")
    update = step12[step12.index("**When the founder gives a cash balance or its date after delivery") :]
    assert "both replace Step 0's in every step" in update
    assert "(a new one starts a new review)" in update
