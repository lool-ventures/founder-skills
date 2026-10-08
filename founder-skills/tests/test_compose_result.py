"""compose_result.json: compose's own record of its last exit, written beside the report in a run dir.

The record replaces the reason to save compose's streams to a file of one's own. Its promises, each pinned
here: written only where the dir carries a run's ref (any `handoff/*/run_ref.json`), so a dir with none is
untouched; never stale (the earlier record is removed before compose runs); never changes compose's argv
handling, streams or exit code; the run id is the skill's own derivation, top level, never
`metadata.run_id`. The six skills carry identical copies of the module.
"""

from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import compose_invocations as ci  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILLS = REPO_ROOT / "founder-skills" / "skills"
FIXTURES = REPO_ROOT / "founder-skills" / "tests" / "fixtures"
SKILL_NAMES = (
    "cap-table",
    "competitive-positioning",
    "deck-review",
    "financial-model-review",
    "ic-sim",
    "market-sizing",
)
# The run id each skill's compose derives for its fixture set: the id the fixtures carry, except cap-table,
# whose derivation is its own required `--run-id` (the harness passes `test-run`).
FIXTURE_RUN_ID = {
    "cap-table": "test-run",
    "competitive-positioning": "fixture-competitive-positioning-001",
    "deck-review": "fixture-deck-review-001",
    "financial-model-review": "fixture-run",
    "ic-sim": "fixture-ic-sim-001",
    "market-sizing": "fixture-market-sizing-001",
}
NAME = "compose_result.json"


def _load(skill: str = "market-sizing") -> ModuleType:
    path = SKILLS / skill / "scripts" / "_compose_result.py"
    spec = importlib.util.spec_from_file_location(f"_compose_result_{skill.replace('-', '_')}", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


cr = _load()


# --- the copies --------------------------------------------------------------------------------------


def test_the_six_copies_are_identical() -> None:
    digests = {
        s: hashlib.sha256((SKILLS / s / "scripts" / "_compose_result.py").read_bytes()).hexdigest() for s in SKILL_NAMES
    }
    assert len(set(digests.values())) == 1, digests


@pytest.mark.parametrize("skill", SKILL_NAMES)
def test_every_compose_runs_inside_the_recorder(skill: str) -> None:
    text = (SKILLS / skill / "scripts" / "compose_report.py").read_text(encoding="utf-8")
    main_block = text[text.index('if __name__ == "__main__":') :]
    assert "_compose_result.recording(" in main_block and f'skill="{skill}"' in main_block, main_block


# --- in process -----------------------------------------------------------------------------------------


def _ref(run_dir: Path, run_id: str = "R1") -> None:
    ref = run_dir / "handoff" / run_id / "run_ref.json"
    ref.parent.mkdir(parents=True, exist_ok=True)
    ref.write_text("{}", encoding="utf-8")


@contextlib.contextmanager
def _argv(*args: str) -> Iterator[None]:
    saved = sys.argv
    sys.argv = ["compose_report.py", *args]
    try:
        yield
    finally:
        sys.argv = saved


def _run(run_dir: Path, body: Any, *extra: str, run_id: str | None = "R1", flag: bool = False) -> BaseException | None:
    """Run `body` inside the recorder; return what escaped it."""
    out = run_dir / "report.json"
    with _argv("--dir", str(run_dir), "-o", str(out), *extra):
        try:
            with cr.recording(skill="market-sizing", run_id_of=lambda d: run_id, run_id_flag=flag):
                body(out)
        except BaseException as e:  # noqa: BLE001
            return e
    return None


def _record(run_dir: Path) -> dict[str, Any]:
    rec: dict[str, Any] = json.loads((run_dir / NAME).read_text(encoding="utf-8"))
    return rec


def test_a_clean_return_is_recorded_with_the_report_it_wrote(tmp_path: Path) -> None:
    _ref(tmp_path)

    def body(out: Path) -> None:
        out.write_text(
            json.dumps(
                {
                    "validation": {
                        "status": "warnings",
                        "warnings": [{"code": "X", "severity": "medium", "message": "m"}],
                    }
                }
            )
        )
        print('{"ok": true}')

    assert _run(tmp_path, body) is None
    rec = _record(tmp_path)
    assert (rec["exit_code"], rec["run_id"], rec["validation_status"]) == (0, "R1", "warnings")
    assert rec["warnings"] == [{"code": "X", "severity": "medium"}]
    assert rec["outputs"]["report_json"] == {"path": "report.json", "exists": True, "written": True}
    assert rec["printed"] == {"ok": True} and "metadata" not in rec


def test_an_exit_from_anywhere_passes_through_and_is_recorded(tmp_path: Path) -> None:
    _ref(tmp_path)

    def body(out: Path) -> None:
        print(json.dumps({"status": "waiting", "blocked_by_gate": "g"}))
        sys.exit(10)

    exc = _run(tmp_path, body)
    assert isinstance(exc, SystemExit) and exc.code == 10
    rec = _record(tmp_path)
    assert (rec["exit_code"], rec["status"], rec["blocked_by_gate"]) == (10, "waiting", "g")
    assert rec["outputs"]["report_json"]["written"] is False


def test_a_message_exit_and_an_error_keep_their_own_exit(tmp_path: Path) -> None:
    _ref(tmp_path)
    exc = _run(tmp_path, lambda out: sys.exit("boom"))
    assert isinstance(exc, SystemExit) and exc.code == "boom"
    assert _record(tmp_path)["exit_code"] == 1 and _record(tmp_path)["stderr"].endswith("boom\n")
    err = ValueError("x")

    def raises(out: Path) -> None:
        raise err

    assert _run(tmp_path, raises) is err, "the very exception compose raised must propagate"
    assert _record(tmp_path)["exit_code"] == 1 and "ValueError: x" in _record(tmp_path)["stderr"]


def test_an_interrupt_is_recorded_as_the_shell_reports_it(tmp_path: Path) -> None:
    _ref(tmp_path)

    def body(out: Path) -> None:
        raise KeyboardInterrupt

    assert isinstance(_run(tmp_path, body), KeyboardInterrupt)
    assert _record(tmp_path)["exit_code"] == 130


def test_a_dir_with_no_ref_gets_nothing_and_the_streams_are_restored(tmp_path: Path) -> None:
    stdout, stderr = sys.stdout, sys.stderr
    assert _run(tmp_path, lambda out: print("x")) is None
    assert not (tmp_path / NAME).exists()
    assert sys.stdout is stdout and sys.stderr is stderr


def test_any_runs_ref_is_ledger_mode_even_when_the_run_id_cannot_be_derived(tmp_path: Path) -> None:
    _ref(tmp_path, "another-run")
    assert _run(tmp_path, lambda out: None, run_id=None) is None
    assert _record(tmp_path)["run_id"] is None


def test_the_record_is_never_an_earlier_exits(tmp_path: Path) -> None:
    """A run killed before it records, or whose write fails, leaves no record rather than an old one."""
    _ref(tmp_path)
    (tmp_path / NAME).write_text('{"exit_code": 2}', encoding="utf-8")
    seen: list[bool] = []
    _run(tmp_path, lambda out: seen.append((tmp_path / NAME).exists()))
    assert seen == [False], "the earlier record must be gone before compose runs"
    (tmp_path / NAME).write_text('{"exit_code": 2}', encoding="utf-8")
    real = cr._write  # type: ignore[attr-defined]

    def fail(path: str, body: dict[str, Any]) -> None:
        raise OSError("disk full")

    cr._write = fail  # type: ignore[attr-defined]
    try:
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            assert _run(tmp_path, lambda out: None) is None
    finally:
        cr._write = real  # type: ignore[attr-defined]
    assert not (tmp_path / NAME).exists()
    assert buf.getvalue() == f"warning: {NAME} was not written: disk full\n"


def test_what_compose_prints_passes_through_unchanged(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _ref(tmp_path)

    def body(out: Path) -> None:
        sys.stdout.write("a\n")
        print("b", file=sys.stderr)
        sys.stdout.write("c")

    _run(tmp_path, body)
    got = capsys.readouterr()
    assert (got.out, got.err) == ("a\nc", "b\n")
    assert (_record(tmp_path)["stdout"], _record(tmp_path)["stderr"]) == ("a\nc", "b\n")


def test_a_large_stdout_is_kept_from_its_end_and_not_parsed(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _ref(tmp_path)
    big = "x" * (cr.STREAM_CAP * 3) + "END"
    _run(tmp_path, lambda out: sys.stdout.write(big))
    capsys.readouterr()
    rec = _record(tmp_path)
    assert rec["stdout_truncated"] and rec["printed"] is None
    assert len(rec["stdout"]) == cr.STREAM_CAP and rec["stdout"].endswith("END")
    assert (tmp_path / NAME).stat().st_size < 48 * 1024, "the record must stay under a recording's 64 KiB body cap"


def test_a_refusal_leaves_the_earlier_report_unwritten(tmp_path: Path) -> None:
    _ref(tmp_path)
    (tmp_path / "report.json").write_text('{"sentinel": true}', encoding="utf-8")
    _run(tmp_path, lambda out: sys.exit(1))
    assert _record(tmp_path)["outputs"]["report_json"] == {"path": "report.json", "exists": True, "written": False}
    assert not list(tmp_path.glob(f"{NAME}.tmp-*"))


def test_cap_tables_run_id_is_its_own_flag_and_no_other_skill_reads_one(tmp_path: Path) -> None:
    _ref(tmp_path)
    _run(tmp_path, lambda out: None, "--run-id", "FLAG", run_id="DERIVED")
    assert _record(tmp_path)["run_id"] == "DERIVED", "a stray --run-id must not override the skill's derivation"
    _run(tmp_path, lambda out: None, "--run-id", "FLAG", run_id="DERIVED", flag=True)
    assert _record(tmp_path)["run_id"] == "FLAG"


@pytest.mark.parametrize("argv", [["--dir"], ["--run-id"], ["-o"], ["--bogus", "--dir"]])
def test_reading_the_flags_prints_nothing_and_never_exits(argv: list[str], capsys: pytest.CaptureFixture[str]) -> None:
    assert cr._paths(argv) is None
    got = capsys.readouterr()
    assert (got.out, got.err) == ("", "")


def test_the_temp_file_is_left_out_of_resume_evidence_and_the_record_is_not() -> None:
    rs_path = REPO_ROOT / "founder-skills" / "scripts" / "_run_status.py"
    spec = importlib.util.spec_from_file_location("_run_status_for_cr", rs_path)
    assert spec and spec.loader
    rs = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("_run_status_for_cr", rs)
    spec.loader.exec_module(rs)
    assert rs._MANIFEST_EXCLUDED_RE.fullmatch(f"{NAME}.tmp-123")
    assert not rs._MANIFEST_EXCLUDED_RE.fullmatch(NAME), "a rewritten record is a write the evidence must show"


# --- through each real compose -------------------------------------------------------------------------


def _stage(skill: str, work: Path) -> None:
    ci._ensure_registered(skill)
    ci._stage_fixtures(FIXTURES / skill, work)


def _compose(skill: str, work: Path) -> subprocess.CompletedProcess[str]:
    return ci._run_compose_subprocess(skill, work, ci._ensure_registered(skill))


@pytest.mark.parametrize("skill", SKILL_NAMES)
def test_a_dir_with_no_ref_is_left_as_before(skill: str, tmp_path: Path) -> None:
    """The no-ledger goldens rely on this: a compose in a dir with no ref writes no record."""
    _stage(skill, tmp_path)
    proc = _compose(skill, tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert not (tmp_path / NAME).exists()


@pytest.mark.parametrize("skill", SKILL_NAMES)
def test_a_refusal_from_a_sibling_module_is_recorded_with_the_skills_run_id(skill: str, tmp_path: Path) -> None:
    """A ref naming this run with no ledger behind it: compose exits 2 from its gates module."""
    _stage(skill, tmp_path)
    _ref(tmp_path, FIXTURE_RUN_ID[skill])
    proc = _compose(skill, tmp_path)
    assert proc.returncode == 2, (proc.stdout, proc.stderr)
    rec = _record(tmp_path)
    assert (rec["skill"], rec["run_id"], rec["exit_code"]) == (skill, FIXTURE_RUN_ID[skill], 2)
    assert rec["stdout"] == proc.stdout and rec["stderr"] == proc.stderr
    assert rec["code"] == json.loads(proc.stdout.strip().splitlines()[-1])["code"]
    assert rec["outputs"]["report_json"]["written"] is False and not (tmp_path / "report.json").exists()


@pytest.mark.parametrize("skill", SKILL_NAMES)
def test_another_runs_ref_records_a_composed_report(skill: str, tmp_path: Path) -> None:
    _stage(skill, tmp_path)
    _ref(tmp_path, "another-run")
    proc = _compose(skill, tmp_path)
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    rec = _record(tmp_path)
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert rec["exit_code"] == 0 and rec["run_id"] == FIXTURE_RUN_ID[skill]
    found = (report.get("validation") or report)["warnings"]
    assert rec["warnings"] == [{"code": w["code"], "severity": w["severity"]} for w in found]
    assert rec["outputs"]["report_md"]["written"] is True


@pytest.mark.parametrize("skill", SKILL_NAMES)
def test_a_malformed_call_prints_what_compose_alone_prints(skill: str, tmp_path: Path) -> None:
    """The recorder reads its flags without printing or exiting, so compose's own usage error is unchanged."""
    script = SKILLS / skill / "scripts" / "compose_report.py"
    plain = tmp_path / "compose_report.py"
    text = script.read_text(encoding="utf-8")
    head = text[: text.index('if __name__ == "__main__":')]
    plain.write_text(head + 'if __name__ == "__main__":\n    sys.exit(main())\n', encoding="utf-8")
    env = {**os.environ, "PYTHONPATH": str(script.parent)}
    for argv in (["--dir"], ["--run-id"], ["--bogus"]):
        a = subprocess.run([sys.executable, str(script), *argv], capture_output=True, text=True, cwd=tmp_path)
        b = subprocess.run([sys.executable, str(plain), *argv], capture_output=True, text=True, cwd=tmp_path, env=env)
        assert (a.returncode, a.stdout, a.stderr) == (
            b.returncode,
            b.stdout,
            b.stderr,
        ), argv


def test_a_resumed_run_is_never_offered_the_record_to_reuse(tmp_path: Path) -> None:
    rs_path = REPO_ROOT / "founder-skills" / "scripts" / "_run_status.py"
    spec = importlib.util.spec_from_file_location("_run_status_reuse", rs_path)
    assert spec and spec.loader
    rs = importlib.util.module_from_spec(spec)
    sys.modules["_run_status_reuse"] = rs
    spec.loader.exec_module(rs)
    (tmp_path / NAME).write_text(json.dumps({"run_id": "R1", "exit_code": 0}), encoding="utf-8")
    (tmp_path / "inputs.json").write_text(json.dumps({"metadata": {"run_id": "R1"}}), encoding="utf-8")
    assert rs.reuse_names({"run_dir_shell": str(tmp_path), "run_id": "R1"}) == ["inputs.json"]


@pytest.mark.parametrize("skill", SKILL_NAMES)
@pytest.mark.parametrize("tail", [["--write-md"], ["-o"]])
def test_a_call_the_parser_refuses_still_replaces_the_record(skill: str, tail: list[str], tmp_path: Path) -> None:
    """A flag missing its value exits 2 before compose runs; the previous call's record must not survive it."""
    _stage(skill, tmp_path)
    _ref(tmp_path, "another-run")
    assert _compose(skill, tmp_path).returncode == 0
    assert _record(tmp_path)["exit_code"] == 0
    script = SKILLS / skill / "scripts" / "compose_report.py"
    proc = subprocess.run(
        [sys.executable, str(script), "--dir", str(tmp_path), *tail], capture_output=True, text=True, cwd=tmp_path
    )
    assert proc.returncode == 2
    rec = _record(tmp_path)
    assert rec["exit_code"] == 2 and rec["stderr"] == proc.stderr


@pytest.mark.parametrize(
    "argv, expected",
    [
        (["--dir", "D", "--write-md"], "D"),
        (["--dir=D", "-o"], "D"),
        (["-dD", "-o"], "D"),
        (["-d", "D"], "D"),
        (["--write-md"], None),
        (["--dir"], None),
    ],
)
def test_the_dir_is_read_by_hand_when_the_parser_refuses(argv: list[str], expected: str | None) -> None:
    assert cr._dir_by_hand(argv) == expected  # type: ignore[attr-defined]
