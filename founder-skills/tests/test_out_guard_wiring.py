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
    out_flag: str = "-o"


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


ROWS: dict[str, Callable[[Path], Call]] = {
    "cap-table/extract_instrument.py --instruments": _ct_extract,
    "competitive-positioning/record_deferred_recall.py --draft": _cp_deferred,
    "cap-table/_emit (pool_clause.py --doc)": _ct_emit,
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
    proc = _run(call, fresh)
    assert "OUTPUT_IS_INPUT" not in proc.stdout
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    assert fresh.is_file()


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
