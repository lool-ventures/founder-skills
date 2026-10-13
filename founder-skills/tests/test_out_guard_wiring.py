"""Each wired writer refuses an output onto one of its own input files, and runs as before otherwise.

A behavioural registry (`ROWS`): each row builds a minimal input set in a temp dir and names the file an output
would collide with. The collision is refused (exit 1, `OUTPUT_IS_INPUT`, a stderr line, the file's bytes
unchanged, nothing new in the dir). The lever, per row, is the same call with the output pointed at a fresh
file: it must exit 0 and write that file, or the row would green on an unrelated refusal and guard nothing.

Kept small on purpose: the receipt writers, the math producers' one choke point, the six composes, one
producer per skill and the two documented in-place controls. The static half (`test_out_guard_coverage.py`)
holds that every other writer calls the guard.
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import no_ledger_goldens as goldens  # noqa: E402

SKILLS = goldens.SKILLS


@dataclass
class Call:
    script: Path
    argv: list[str]  # "{out}" is replaced by the output path
    target: Path  # the input file an output onto it collides with
    stdin: str | None = None
    # False where the mode writes no -o receipt (lane 3's freeform emit writes its two files in place through
    # --dir): the control then asserts that in-place write still happened.
    writes_out: bool = True


def _run(call: Call, out: Path) -> subprocess.CompletedProcess[str]:
    argv = [a.replace("{out}", str(out)) for a in call.argv]
    return goldens.run([str(call.script), *argv], stdin=call.stdin)


def _snapshot(root: Path) -> dict[str, bytes]:
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


# --- rows ------------------------------------------------------------------------------------------


def _ct_extract(root: Path) -> Call:
    goldens.ct_dir(root)
    doc = root / "safe.txt"
    doc.write_text(goldens.CT_DOC, encoding="utf-8")
    return Call(
        SKILLS / "cap-table" / "scripts" / "extract_instrument.py",
        ["--instruments", str(root / "instruments.json"), "--run-id", goldens.CT_RUN, "--source-doc", str(doc)]
        + ["-o", "{out}"],
        root / "instruments.json",
        stdin=json.dumps(goldens.CT_SAFE_EXTRACTION),
    )


def _cp_deferred(root: Path) -> Call:
    goldens._cp_dir(root)
    entry = {
        "name": "Example Newco",
        "slug": "example-newco",
        "why_considered": "same buyer",
        "sources": ["https://example.org/a"],
    }
    return Call(
        SKILLS / "competitive-positioning" / "scripts" / "record_deferred_recall.py",
        ["--draft", str(root / "landscape_draft.json"), "-o", "{out}"],
        root / "landscape_draft.json",
        stdin=json.dumps([entry]),
    )


def _ct_emit(root: Path) -> Call:
    doc = root / "plan.txt"
    doc.write_text("The pool is 10% of the post-money capitalization. Nothing else.", encoding="utf-8")
    return Call(
        SKILLS / "cap-table" / "scripts" / "pool_clause.py",
        ["--doc", str(doc), "--quote", "The pool is 10% of the post-money capitalization.", "-o", "{out}"],
        doc,
    )


# --- one producer per skill -------------------------------------------------------------------------


def _ms_checklist(root: Path) -> Call:
    goldens._ms_ref_dir(root)
    items = json.loads((goldens.FIXTURES / "market-sizing" / "checklist.json").read_text(encoding="utf-8"))["items"]
    return Call(
        goldens.MS_SCRIPTS / "checklist.py",
        ["--run-id", goldens.GATE_RUN, "--sizing", str(root / "sizing.json"), "-o", "{out}"],
        root / "sizing.json",
        stdin=json.dumps({"items": items}),
    )


def _fmr_review_page(root: Path) -> Call:
    goldens._fmr_review_dir(root)
    return Call(
        goldens.FMR_SCRIPTS / "review_inputs.py", [str(root / "inputs.json"), "--static", "{out}"], root / "inputs.json"
    )


def _dr_ledger(root: Path) -> Call:
    goldens._dr_dir(root)
    return Call(
        SKILLS / "deck-review" / "scripts" / "ledger.py",
        ["--inventory", str(root / "deck_inventory.json"), "--run-id", goldens.DR_FIXTURE_RUN, "-o", "{out}"],
        root / "deck_inventory.json",
        stdin=(root / "ledger.json").read_text(encoding="utf-8"),
    )


def _cp_landscape(root: Path) -> Call:
    goldens._cp_dir(root)
    body = goldens._cp_fixture("landscape.json")
    for key in ("metadata", "_produced_by", "warnings"):
        body.pop(key, None)
    return Call(
        goldens.CP_SCRIPTS / "validate_landscape.py",
        ["--run-id", goldens.CP_RUN, "--carry-deferred", str(root / "landscape_draft.json"), "-o", "{out}"],
        root / "landscape_draft.json",
        stdin=json.dumps(body),
    )


def _ic_page(root: Path) -> Call:
    goldens._ic_dir(root)
    return Call(goldens.IC_SCRIPTS / "visualize.py", ["--dir", str(root), "-o", "{out}"], root / "discussion.json")


def _ct_cap_state(root: Path) -> Call:
    goldens.ct_dir(root)
    i, n = str(root / "inputs.json"), str(root / "instruments.json")
    return Call(
        SKILLS / "cap-table" / "scripts" / "cap_state.py",
        ["--inputs", i, "--instruments", n, "--run-id", goldens.CT_RUN, "-o", "{out}"],
        root / "instruments.json",
    )


# --- the six composes: -o onto an artifact compose reads from --dir (not on its command line) ---------


def _compose(build: Callable[[Path], None], script: Path, target: str, *extra: str) -> Callable[[Path], Call]:
    def make(root: Path) -> Call:
        build(root)
        argv = ["--dir", str(root), *extra, "-o", "{out}", "--write-md", str(root / "report.md")]
        return Call(script, argv, root / target)

    return make


COMPOSES: dict[str, Callable[[Path], Call]] = {
    "market-sizing/compose": _compose(
        lambda r: goldens._ms_variant(r, "plain"), goldens.MS_SCRIPTS / "compose_report.py", "inputs.json"
    ),
    "financial-model-review/compose": _compose(
        goldens._fmr_review_dir,
        goldens.FMR_SCRIPTS / "compose_report.py",
        "inputs.json",
        "--today",
        goldens.FMR_TODAY,
    ),
    "ic-sim/compose": _compose(goldens._ic_dir, goldens.IC_SCRIPTS / "compose_report.py", "discussion.json"),
    "competitive-positioning/compose": _compose(
        goldens._cp_dir, goldens.CP_SCRIPTS / "compose_report.py", "checklist.json"
    ),
    "deck-review/compose": _compose(
        goldens._dr_dir, SKILLS / "deck-review" / "scripts" / "compose_report.py", "ledger.json", "--ungated"
    ),
    "cap-table/compose": _compose(
        goldens._ct_full,
        SKILLS / "cap-table" / "scripts" / "compose_report.py",
        "scenarios.json",
        "--run-id",
        goldens.CT_RUN,
    ),
}


def _ct_freeform(root: Path) -> Call:
    """Lane 3 rewrites inputs.json in place through --dir, by design; its -o is a receipt."""
    xlsx = goldens.ct_workbook(root)
    (root / "inputs.json").write_text(json.dumps(goldens.CT_INPUTS), encoding="utf-8")
    argv = ["--mode=freeform-emit", "--xlsx", str(xlsx), "--dir", str(root), "--run-id", goldens.GATE_RUN]
    argv += ["--answer", "0.interest_rate_type=fixed_numeric_simple", "-o", "{out}"]
    return Call(
        SKILLS / "cap-table" / "scripts" / "extract_cap_table.py",
        argv,
        root / "inputs.json",
        stdin=json.dumps(goldens.CT_NOTE_BLOCKS),
        writes_out=False,
    )


ROWS: dict[str, Callable[[Path], Call]] = {
    "cap-table/extract_instrument.py --instruments": _ct_extract,
    "competitive-positioning/record_deferred_recall.py --draft": _cp_deferred,
    "cap-table/_emit (pool_clause.py --doc)": _ct_emit,
    "market-sizing/checklist.py --sizing": _ms_checklist,
    "financial-model-review/review_inputs.py --static onto its inputs": _fmr_review_page,
    "deck-review/ledger.py --inventory": _dr_ledger,
    "competitive-positioning/validate_landscape.py --carry-deferred": _cp_landscape,
    "ic-sim/visualize.py -o onto a dir artifact": _ic_page,
    "cap-table/cap_state.py --instruments": _ct_cap_state,
    "cap-table/extract_cap_table.py freeform -o onto the dir's inputs.json": _ct_freeform,
    **COMPOSES,
}


@pytest.mark.parametrize("row", sorted(ROWS))
def test_an_output_onto_an_input_is_refused(row: str, tmp_path: Path) -> None:
    call = ROWS[row](tmp_path)
    call.target.write_bytes(call.target.read_bytes() + b"\n")  # a sentinel byte nothing would write
    before = _snapshot(tmp_path)
    proc = _run(call, call.target)
    assert proc.returncode == 1, (proc.stdout, proc.stderr)
    body = json.loads(proc.stdout.strip().splitlines()[-1])
    assert body["code"] == "OUTPUT_IS_INPUT", body
    assert proc.stderr.strip()
    assert _snapshot(tmp_path) == before, "the refusal wrote something"


@pytest.mark.parametrize("row", sorted(ROWS))
def test_the_same_call_with_a_fresh_output_runs(row: str, tmp_path: Path) -> None:
    """The lever: without it a row greens on an unrelated refusal (a waiting gate, a bad stdin)."""
    call = ROWS[row](tmp_path)
    fresh = tmp_path / "fresh_out.json"
    before = call.target.read_bytes()
    proc = _run(call, fresh)
    assert "OUTPUT_IS_INPUT" not in proc.stdout
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    if call.writes_out:
        assert fresh.is_file()
    else:
        assert call.target.read_bytes() != before, "the in-place write through --dir no longer happens"


# --- the receipt writers' existing -o ----------------------------------------------------------------


def test_extract_instrument_refuses_an_existing_analysis_file_as_its_receipt(tmp_path: Path) -> None:
    call = _ct_extract(tmp_path)
    scenarios = tmp_path / "scenarios.json"
    scenarios.write_text('{"scenarios": []}', encoding="utf-8")
    before = _snapshot(tmp_path)
    proc = _run(call, scenarios)
    assert proc.returncode == 1 and json.loads(proc.stdout)["code"] == "OUTPUT_IS_INPUT"
    assert _snapshot(tmp_path) == before


def test_extract_instrument_refuses_any_file_carrying_a_run_id_as_its_receipt(tmp_path: Path) -> None:
    call = _ct_extract(tmp_path)
    other = tmp_path / "some_analysis.json"
    other.write_text('{"metadata": {"run_id": "20260901T080000Z-0e1d2c"}}', encoding="utf-8")
    proc = _run(call, other)
    assert proc.returncode == 1 and json.loads(proc.stdout)["code"] == "OUTPUT_IS_INPUT"


def test_extract_instrument_reuses_its_receipt_path_for_the_next_document(tmp_path: Path) -> None:
    """The documented path: one `-o` for every document of a review (the control for the two rows above)."""
    call = _ct_extract(tmp_path)
    receipt = tmp_path / "extraction_audit.json"
    first = _run(call, receipt)
    assert first.returncode == 0, first.stderr
    second = goldens.run(
        [str(call.script), *[a.replace("{out}", str(receipt)) for a in call.argv], "--replace"], stdin=call.stdin
    )
    assert second.returncode == 0, (second.stdout, second.stderr)


def test_the_r_class_names_track_their_composes() -> None:
    """The receipt writers' protected names are their skill compose's REQUIRED_ARTIFACTS plus its two outputs."""
    import ast

    def required(skill: str) -> list[str]:
        tree = ast.parse((SKILLS / skill / "scripts" / "compose_report.py").read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "REQUIRED_ARTIFACTS":
                return list(ast.literal_eval(node.value))
        raise AssertionError(skill)

    def canonical(path: Path) -> list[str]:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "CANONICAL_ARTIFACTS":
                return list(ast.literal_eval(node.value))
        raise AssertionError(path)

    ct = canonical(SKILLS / "cap-table" / "scripts" / "extract_instrument.py")
    assert ct == [*required("cap-table"), "report.json", "report.md"]
    cp = canonical(SKILLS / "competitive-positioning" / "scripts" / "record_deferred_recall.py")
    assert cp == [*required("competitive-positioning"), "report.json", "report.md"]


def test_a_compose_refuses_write_md_onto_an_artifact(tmp_path: Path) -> None:
    call = COMPOSES["market-sizing/compose"](tmp_path)
    argv = [a.replace("{out}", str(tmp_path / "report.json")) for a in call.argv]
    argv[argv.index("--write-md") + 1] = str(tmp_path / "checklist.json")
    before = _snapshot(tmp_path)
    proc = goldens.run([str(call.script), *argv])
    assert proc.returncode == 1 and json.loads(proc.stdout)["code"] == "OUTPUT_IS_INPUT"
    after = _snapshot(tmp_path)
    after.pop("compose_result.json", None)  # compose's wrapper records every exit, never in an unbound dir
    assert after == before


def test_the_stdin_in_place_fix_stays_legal(tmp_path: Path) -> None:
    """The guard's one documented in-place call: `validate_inputs.py --fix < inputs.json -o inputs.json`."""
    goldens._fmr_review_dir(tmp_path)
    target = tmp_path / "inputs.json"
    proc = goldens.run(
        [str(goldens.FMR_SCRIPTS / "validate_inputs.py"), "--fix", "-o", str(target)],
        stdin=target.read_text(encoding="utf-8"),
    )
    assert "OUTPUT_IS_INPUT" not in proc.stdout
    assert proc.returncode in (0, 1), proc.stderr  # validation's own verdict; the file is rewritten either way
    assert json.loads(target.read_text(encoding="utf-8"))


def test_the_documented_replay_in_place_stays_legal(tmp_path: Path) -> None:
    """market-sizing Step 6d: `market_sizing.py --replay sizing.json ... -o sizing.json` rewrites the sizing."""
    goldens._ms_ref_dir(tmp_path)
    s, v, i = (str(tmp_path / n) for n in ("sizing.json", "validation.json", "inputs.json"))
    replay = [str(goldens.MS_SCRIPTS / "market_sizing.py"), "--replay", s, "--validation", v, "--inputs", i]
    proc = goldens.run([*replay, "-o", s])
    assert "OUTPUT_IS_INPUT" not in proc.stdout
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    onto_inputs = goldens.run([*replay, "-o", i])
    assert onto_inputs.returncode == 1 and json.loads(onto_inputs.stdout)["code"] == "OUTPUT_IS_INPUT"
