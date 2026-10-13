"""`_out_guard.refuse_output_onto_input`: no step writes its output over one of the files it reads.

The helper's rule, unit by unit, each with the positive control that keeps it from passing by refusing
everything. The per-script wiring is held by `test_out_guard_wiring.py`.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
GUARD = REPO_ROOT / "founder-skills" / "scripts" / "_out_guard.py"


def _guard() -> ModuleType:
    spec = importlib.util.spec_from_file_location("_out_guard_under_test", GUARD)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


g = _guard()


def _refused(capsys: pytest.CaptureFixture[str], outputs: list[str | None], **kw: object) -> dict[str, object]:
    with pytest.raises(SystemExit) as exc:
        g.refuse_output_onto_input(outputs, script="probe.py", **kw)
    assert exc.value.code == 1
    out, err = capsys.readouterr()
    body: dict[str, object] = json.loads(out)
    assert body["status"] == "rejected" and body["code"] == "OUTPUT_IS_INPUT"
    assert err.startswith("Error: probe.py: ") and err.endswith("nothing was written\n")
    return body


def _passes(capsys: pytest.CaptureFixture[str], outputs: list[str | None], **kw: object) -> None:
    g.refuse_output_onto_input(outputs, script="probe.py", **kw)
    assert capsys.readouterr() == ("", ""), "the pass path prints nothing (no-ledger goldens hash both streams)"


@pytest.fixture
def inp(tmp_path: Path) -> Path:
    p = tmp_path / "inputs.json"
    p.write_text('{"metadata": {"run_id": "r1"}}', encoding="utf-8")
    return p


def test_an_output_equal_to_an_input_is_refused(tmp_path: Path, inp: Path, capsys: pytest.CaptureFixture[str]) -> None:
    body = _refused(capsys, [str(inp)], argv=["--inputs", str(inp), "-o", str(inp)])
    assert body["input"] == str(inp) and body["output"] == str(inp)


def test_the_outputs_own_occurrence_is_not_an_input(inp: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Positive control: an existing output (a re-run) named once is not its own input."""
    _passes(capsys, [str(inp)], argv=["-o", str(inp)])


def test_a_fresh_output_passes(tmp_path: Path, inp: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _passes(capsys, [str(tmp_path / "out.json")], argv=["--inputs", str(inp), "-o", str(tmp_path / "out.json")])


def test_relative_and_absolute_spellings_match(
    tmp_path: Path, inp: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    _refused(capsys, ["inputs.json"], argv=["--inputs", str(inp), "-o", "inputs.json"])


def test_a_symlink_to_an_input_is_refused(tmp_path: Path, inp: Path, capsys: pytest.CaptureFixture[str]) -> None:
    link = tmp_path / "link.json"
    link.symlink_to(inp)
    _refused(capsys, [str(link)], argv=["--inputs", str(inp), "-o", str(link)])


def test_a_hard_link_to_an_input_is_refused(tmp_path: Path, inp: Path, capsys: pytest.CaptureFixture[str]) -> None:
    hard = tmp_path / "hard.json"
    os.link(inp, hard)
    assert os.path.realpath(hard) != os.path.realpath(inp), "the lever: realpath alone cannot see a hard link"
    _refused(capsys, [str(hard)], argv=["--inputs", str(inp), "-o", str(hard)])


def test_a_case_variant_on_a_case_folding_volume(tmp_path: Path, inp: Path, capsys: pytest.CaptureFixture[str]) -> None:
    variant = tmp_path / "INPUTS.json"
    if not variant.exists():
        pytest.skip("this volume is case-sensitive: a case variant is a different file here")
    _refused(capsys, [str(variant)], argv=["--inputs", str(inp), "-o", str(variant)])


def test_the_flag_equals_value_form(tmp_path: Path, inp: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _refused(capsys, [str(inp)], argv=[f"--inputs={inp}", f"--output={inp}"])
    _passes(capsys, [str(inp)], argv=[f"--output={inp}"])


def test_two_outputs_naming_one_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = str(tmp_path / "report.json")
    _refused(capsys, [out, out], argv=["-o", out, "--write-md", out])


def test_a_directory_never_counts(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    d = tmp_path / "dir"
    d.mkdir()
    _passes(capsys, [str(d)], argv=["--dir", str(d), "-o", str(d)])


def test_stdin_never_counts(tmp_path: Path, inp: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """`validate_inputs.py --fix < inputs.json -o inputs.json`: stdin is not on argv, so it is not an input."""
    _passes(capsys, [str(inp)], argv=["--fix", "-o", str(inp)])


def test_extra_names_inputs_the_command_line_does_not(
    tmp_path: Path, inp: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _refused(capsys, [str(inp)], argv=["--dir", str(tmp_path), "-o", str(inp)], extra=[str(inp)])
    _passes(capsys, [str(tmp_path / "report.json")], argv=["--dir", str(tmp_path)], extra=[str(inp)])


def test_none_outputs_are_skipped(inp: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _passes(capsys, [None], argv=["--inputs", str(inp)])


def test_protect_refuses_an_existing_run_artifact(
    tmp_path: Path, inp: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    body = _refused(capsys, [str(inp)], argv=["-o", str(inp)], protect=[])
    assert body["output"] == str(inp)


def test_protect_refuses_a_canonical_name(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    store = tmp_path / "scenarios.json"
    store.write_text("[]", encoding="utf-8")
    _refused(capsys, [str(store)], argv=["-o", str(store)], protect=[str(store)])


def test_protect_passes_an_earlier_receipt(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """The documented reuse: one receipt path for every document (a top-level run_id, no metadata)."""
    receipt = tmp_path / "extraction_audit.json"
    receipt.write_text(json.dumps({"ok": True, "run_id": "r1", "path": "x"}), encoding="utf-8")
    _passes(capsys, [str(receipt)], argv=["-o", str(receipt)], protect=[str(tmp_path / "scenarios.json")])
    _passes(capsys, [str(tmp_path / "new.json")], argv=["-o", str(tmp_path / "new.json")], protect=[])


def test_without_protect_an_existing_artifact_output_passes(inp: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Only the receipt writers opt in: every compose rewrites its report on a re-run."""
    _passes(capsys, [str(inp)], argv=["-o", str(inp)])


def test_the_argv_default_is_the_processes_own(
    tmp_path: Path, inp: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "argv", ["probe.py", "--inputs", str(inp), "-o", str(inp)])
    _refused(capsys, [str(inp)])


def test_in_place_allows_only_the_named_input(tmp_path: Path, inp: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """`market_sizing.py --replay sizing.json -o sizing.json`: the replayed file may be rewritten, nothing else."""
    sizing = tmp_path / "sizing.json"
    sizing.write_text("{}", encoding="utf-8")
    argv = ["--replay", str(sizing), "--inputs", str(inp), "-o", str(sizing)]
    _passes(capsys, [str(sizing)], argv=argv, in_place=[str(sizing)])
    _refused(capsys, [str(sizing)], argv=argv)  # the lever: without in_place the same call is refused
    _refused(
        capsys, [str(inp)], argv=["--replay", str(sizing), "--inputs", str(inp), "-o", str(inp)], in_place=[str(sizing)]
    )
