"""Every composed report.json names the run it was composed for, and the insert and the closers refuse another's.

A report left on disk by an earlier run looks finished: the coaching insert would add this run's commentary to
it, and a closer would hand its figures over as this run's. So each compose stamps a top-level `run_id` (the
skill's own derivation, the one its closer and `compose_result.json` already use), last, `null` when it cannot
tell. The insert compares it with the run its `--verify-artifact` files agree on; a closer with its folder's run
id. A missing id on either side is not compared: a report from before the stamp still goes through.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import compose_invocations as ci  # noqa: E402
import gate_run_helpers as h  # noqa: E402
import no_ledger_goldens as goldens  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
PLUGIN = REPO_ROOT / "founder-skills"
SKILLS = PLUGIN / "skills"
FIXTURES = PLUGIN / "tests" / "fixtures"
INSERT = PLUGIN / "scripts" / "insert_coaching.py"
SKILL_NAMES = (
    "cap-table",
    "competitive-positioning",
    "deck-review",
    "financial-model-review",
    "ic-sim",
    "market-sizing",
)
# How each skill derives its run id from a run dir: the function compose hands `_compose_result.recording`.
# cap-table takes `--run-id`, which the shared drive passes as `test-run`.
_DERIVE = {
    "deck-review": "import compose_report as m; print(m._artifacts_run_id(d) or '')",
    "market-sizing": "import _ms_gates as m; print(m.run_id_of(d) or '')",
    "ic-sim": "import _ic_gates as m; print(m.run_id_of(d) or '')",
    "financial-model-review": "import _fmr_gates as m; print(m.run_id_of(d) or '')",
    "competitive-positioning": "import _cp_gates as m; print(m.run_id_of(d) or '')",
}


def _derived(skill: str, run_dir: Path) -> str | None:
    if skill == "cap-table":
        return "test-run"
    scripts = SKILLS / skill / "scripts"
    code = f"import sys; sys.path.insert(0, {str(scripts)!r}); d = {str(run_dir)!r}; {_DERIVE[skill]}"
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.strip() or None


def _report(run_dir: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
    return data


# --- compose stamps the run ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("skill", SKILL_NAMES)
def test_every_report_json_carries_the_runs_id_last(skill: str, tmp_path: Path) -> None:
    ci.drive_compose(skill, FIXTURES / skill, tmp_path)
    report = _report(tmp_path)
    assert report["run_id"] == _derived(skill, tmp_path) and report["run_id"], report.get("run_id")
    assert list(report)[-1] == "run_id"


def test_a_run_dir_with_no_run_id_stamps_null(tmp_path: Path) -> None:
    """market-sizing reads its run from inputs.json; with none there the report says it could not tell."""
    fixture = tmp_path / "fixture"
    shutil.copytree(FIXTURES / "market-sizing", fixture)
    inputs = json.loads((fixture / "inputs.json").read_text(encoding="utf-8"))
    inputs.get("metadata", {}).pop("run_id", None)
    (fixture / "inputs.json").write_text(json.dumps(inputs), encoding="utf-8")
    work = tmp_path / "work"
    work.mkdir()
    proc = ci.run_compose_capturing("market-sizing", fixture, work)
    assert (work / "report.json").is_file(), proc.stderr
    report = _report(work)
    assert "run_id" in report and report["run_id"] is None


@pytest.mark.parametrize("skill", SKILL_NAMES)
def test_compose_receipt_names_its_run_and_dir(skill: str, tmp_path: Path) -> None:
    proc = ci.run_compose_capturing(skill, FIXTURES / skill, tmp_path)
    assert (tmp_path / "report.json").is_file(), proc.stderr
    receipt = json.loads(proc.stdout.strip().splitlines()[0])
    assert receipt["run_id"] == _report(tmp_path)["run_id"]
    assert receipt["dir"] == str(tmp_path.resolve()) or receipt["dir"] == str(tmp_path)


# --- the insert, run exactly as each SKILL.md gives it, agrees with the stamp ---------------------------------------


def _insert_block(skill: str) -> list[str]:
    """The `--verify-artifact` file names of the SKILL.md's insert command, bounded by the command's own end (the
    first line that does not continue), never by a character window."""
    lines = (SKILLS / skill / "SKILL.md").read_text(encoding="utf-8").splitlines()
    start = next(i for i, ln in enumerate(lines) if 'insert_coaching.py" \\' in ln)
    block: list[str] = []
    for ln in lines[start:]:
        block.append(ln)
        if not ln.rstrip().endswith("\\"):
            break
    names = re.findall(r'--verify-artifact "\$\w+/([^"]+)"', "\n".join(block))
    assert len(names) >= 4, (skill, block)
    return names


def _composed_for_insert(skill: str, root: Path, cap_run_id: str = "fixture-run") -> tuple[Path, list[str], str | None]:
    """(run dir, extra insert args, stdin) for a composed fixture ready for the SKILL.md's insert. cap-table's
    fixture is restamped to `cap_run_id` first when that is not its own."""
    run_dir = root / "run"
    run_dir.mkdir()
    if skill != "cap-table":
        ci.drive_compose(skill, FIXTURES / skill, run_dir)
        return run_dir, [], goldens.COACH_STDIN
    # cap-table: compose for the fixture's own run (the shared drive passes `test-run`, which the fixture's
    # artifacts do not carry, so the insert would rightly refuse), then the check and its release, without which
    # the report's check-record declaration refuses before the run is compared.
    for f in (FIXTURES / "cap-table").iterdir():
        if f.is_file():
            shutil.copy(f, run_dir / f.name)
            if cap_run_id != "fixture-run" and f.suffix == ".json":
                doc = json.loads(f.read_text(encoding="utf-8"))
                assert doc["metadata"]["run_id"] == "fixture-run"  # replaced, never added
                doc["metadata"]["run_id"] = cap_run_id
                (run_dir / f.name).write_text(json.dumps(doc), encoding="utf-8")
    scripts = SKILLS / "cap-table" / "scripts"
    run = [sys.executable, str(scripts / "compose_report.py"), "--dir", str(run_dir)]
    run += ["-o", str(run_dir / "report.json"), "--write-md", str(run_dir / "report.md"), "--run-id", cap_run_id]
    proc = subprocess.run(run, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    (run_dir / "coaching.md").write_text("Lead with the round's size; the rest follows from it.\n", encoding="utf-8")
    check = [sys.executable, str(scripts / "pool_claims_check.py"), str(run_dir / "coaching.md")]
    check += ["--scenarios", str(run_dir / "scenarios.json"), "-o", str(run_dir / "coaching.checked.json")]
    proc = subprocess.run(check, capture_output=True, text=True)
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    release = [sys.executable, str(scripts / "pool_check_release.py"), str(run_dir / "coaching.md")]
    release += ["--checked", str(run_dir / "coaching.checked.json"), "--scenarios", str(run_dir / "scenarios.json")]
    release += ["-o", str(run_dir / "released.json")]
    proc = subprocess.run(release, capture_output=True, text=True)
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    return run_dir, ["--commentary-file", str(run_dir / "released.json")], None


def _insert_as_documented(
    skill: str, run_dir: Path, extra: list[str], stdin: str | None
) -> subprocess.CompletedProcess[str]:
    argv = [sys.executable, str(INSERT), "--report", str(run_dir / "report.md")]
    argv += ["--report-json", str(run_dir / "report.json")]
    argv += ["--marker", _report(run_dir)["coaching_payload"]["insertion_marker"], *extra]
    for name in _insert_block(skill):
        argv += ["--verify-artifact", str(run_dir / name)]
    return subprocess.run(argv, input=stdin, capture_output=True, text=True)


@pytest.mark.parametrize("skill", SKILL_NAMES)
def test_the_insert_commands_artifacts_agree_with_the_stamp(skill: str, tmp_path: Path) -> None:
    run_dir, extra, stdin = _composed_for_insert(skill, tmp_path)
    proc = _insert_as_documented(skill, run_dir, extra, stdin)
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    assert json.loads(proc.stdout)["run_id"] == _report(run_dir)["run_id"]


@pytest.mark.parametrize("skill", SKILL_NAMES)
def test_a_report_json_stamped_for_another_run_is_refused(skill: str, tmp_path: Path) -> None:
    """The in-test negative row: the same documented command, the stamp changed by one character."""
    run_dir, extra, stdin = _composed_for_insert(skill, tmp_path)
    report = _report(run_dir)
    report["run_id"] = f"{report['run_id']}x"
    (run_dir / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    before = {n: (run_dir / n).read_bytes() for n in ("report.json", "report.md")}
    proc = _insert_as_documented(skill, run_dir, extra, stdin)
    assert proc.returncode == 1, (proc.stdout, proc.stderr)
    assert json.loads(proc.stdout)["code"] == "RUN_ID_MISMATCH"
    assert {n: (run_dir / n).read_bytes() for n in before} == before


# --- the same insert, in a bound dir ----------------------------------------------------------------------------------
# The insert's run checks are skill-agnostic, but what each SKILL.md passes is not: the artifact names, whether a real
# compose stamps `metadata.run_id` on each of them, and (cap-table) the check-record declaration. Composed unbound
# (a bound compose would wait on each skill's questions, which the per-skill gate files answer), then bound.

BOUND_RUN = "20261011T120000Z-c0ffee"
OTHER_RUN = "20261011T000000Z-aaaaaa"


def _bound_for_insert(skill: str, tmp: Path) -> tuple[Path, Path, list[str], str | None]:
    """(artifacts root, run dir, extra insert args, stdin): composed for BOUND_RUN and bound to it."""
    root = tmp / "artifacts"
    root.mkdir(parents=True)
    run_dir, extra, stdin = _composed_for_insert(skill, root, cap_run_id=BOUND_RUN)
    if skill != "cap-table":
        for name in _insert_block(skill):
            doc = json.loads((run_dir / name).read_text(encoding="utf-8"))
            meta = doc.get("metadata")
            assert isinstance(meta, dict) and meta.get("run_id"), (skill, name, "compose left no run id")
            meta["run_id"] = BOUND_RUN  # replaced, never added
            (run_dir / name).write_text(json.dumps(doc), encoding="utf-8")
        report = _report(run_dir)
        report["run_id"] = BOUND_RUN
        (run_dir / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    assert _report(run_dir)["run_id"] == BOUND_RUN
    assert h.start_ok(root, skill, f"FS_HOST_RUN_ID={BOUND_RUN}\n") == BOUND_RUN
    proc = h.bind(root, BOUND_RUN, run_dir, "example-co")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    # Lever: the dir is bound, and the run is not complete before the insert.
    assert (run_dir / "handoff" / BOUND_RUN / "run_ref.json").is_file()
    assert h.status(root, BOUND_RUN)["status"] == "running"
    return root, run_dir, extra, stdin


def _untouched(root: Path, run_dir: Path) -> tuple[bytes, ...]:
    return tuple(
        p.read_bytes() for p in (run_dir / "report.md", run_dir / "report.json", h.status_path(root, BOUND_RUN))
    )


@pytest.mark.parametrize("skill", SKILL_NAMES)
def test_the_documented_insert_in_a_bound_dir(skill: str, tmp_path: Path) -> None:
    root, run_dir, extra, stdin = _bound_for_insert(skill, tmp_path / "ok")
    proc = _insert_as_documented(skill, run_dir, extra, stdin)
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    assert json.loads(proc.stdout)["run_id"] == BOUND_RUN
    st = h.status(root, BOUND_RUN)
    assert (st["status"], st["coaching"]) == ("complete", "inserted")  # only the bound path writes this

    # Every listed file restamped to one other well-formed id: that run is not bound here.
    root, run_dir, extra, stdin = _bound_for_insert(skill, tmp_path / "not-bound")
    for name in _insert_block(skill):
        doc = json.loads((run_dir / name).read_text(encoding="utf-8"))
        doc["metadata"]["run_id"] = OTHER_RUN
        (run_dir / name).write_text(json.dumps(doc), encoding="utf-8")
    before = _untouched(root, run_dir)
    proc = _insert_as_documented(skill, run_dir, extra, stdin)
    assert proc.returncode == 1 and json.loads(proc.stdout)["code"] == "RUN_NOT_BOUND", proc.stdout
    assert _untouched(root, run_dir) == before

    # The documented command with every --verify-artifact removed.
    root, run_dir, extra, stdin = _bound_for_insert(skill, tmp_path / "no-verify")
    before = _untouched(root, run_dir)
    argv = [sys.executable, str(INSERT), "--report", str(run_dir / "report.md")]
    argv += ["--report-json", str(run_dir / "report.json")]
    argv += ["--marker", _report(run_dir)["coaching_payload"]["insertion_marker"], *extra]
    proc = subprocess.run(argv, input=stdin, capture_output=True, text=True)
    assert proc.returncode == 1 and json.loads(proc.stdout)["code"] == "RUN_ID_REQUIRED", proc.stdout
    assert _untouched(root, run_dir) == before

    # report.json's stamp changed by one character: blocked, with the bound-only status write. For cap-table this
    # is also the proof that the run check precedes the check-record declaration in a bound dir.
    root, run_dir, extra, stdin = _bound_for_insert(skill, tmp_path / "mismatch")
    report = _report(run_dir)
    report["run_id"] = f"{BOUND_RUN}x"
    (run_dir / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    md_before = (run_dir / "report.md").read_bytes()
    proc = _insert_as_documented(skill, run_dir, extra, stdin)
    assert proc.returncode == 1 and json.loads(proc.stdout)["code"] == "RUN_ID_MISMATCH", proc.stdout
    assert (run_dir / "report.md").read_bytes() == md_before
    st = h.status(root, BOUND_RUN)
    assert (st["status"], st["last_error_code"]) == ("running", "COACHING_BLOCKED")


# --- the closers ------------------------------------------------------------------------------------------------------

_CLOSERS: dict[str, tuple[str, Callable[[Path], Any], Callable[[Path], Any]]] = {
    "market-sizing": ("closing_message.py", lambda r: goldens._ms_variant(r, "plain"), goldens._ms_compose),
    "competitive-positioning": ("cp_closing_message.py", goldens._cp_dir, goldens._cp_compose),
    "financial-model-review": (
        "fmr_closing_message.py",
        lambda r: goldens._fmr_review_dir(r, cash=True),
        goldens._fmr_compose,
    ),
}


def _closer_dir(skill: str, root: Path) -> tuple[Path, list[str]]:
    script, make, compose = _CLOSERS[skill]
    make(root)
    compose(root)
    report = _report(root)
    report.setdefault("verdict", "Example Co's figures hold on the evidence given.")
    if not report["verdict"]:
        report["verdict"] = "Example Co's figures hold on the evidence given."
    (root / "report.json").write_text(json.dumps(report), encoding="utf-8")
    argv = [sys.executable, str(SKILLS / skill / "scripts" / script), "--report", str(root / "report.json")]
    return root, [*argv, "--link", "path", "--deliverable", f"the written report={root}/report.md"]


@pytest.mark.parametrize("skill", sorted(_CLOSERS))
def test_closers_refuse_another_runs_report(skill: str) -> None:
    with tempfile.TemporaryDirectory() as td:
        root, argv = _closer_dir(skill, Path(td))
        report = _report(root)
        assert report["run_id"], "the fixture must carry a run id for the comparison to run"
        report["run_id"] = "20261011T000000Z-other"
        (root / "report.json").write_text(json.dumps(report), encoding="utf-8")
        stale = root / "handover.txt"
        stale.write_text("an earlier run's hand-over\n", encoding="utf-8")
        proc = subprocess.run(argv, capture_output=True, text=True)
        assert proc.returncode == 2 and proc.stdout == "", (proc.returncode, proc.stdout)
        assert "RUN_ID_MISMATCH" in proc.stderr and "Compose the report again" in proc.stderr
        assert stale.read_text(encoding="utf-8") == "an earlier run's hand-over\n"


@pytest.mark.parametrize("skill", sorted(_CLOSERS))
def test_closers_print_when_either_side_has_no_run_id(skill: str) -> None:
    with tempfile.TemporaryDirectory() as td:
        root, argv = _closer_dir(skill, Path(td))
        assert subprocess.run(argv, capture_output=True, text=True).returncode == 0  # same id: prints
        report = _report(root)
        report.pop("run_id")  # a report from before the stamp
        (root / "report.json").write_text(json.dumps(report), encoding="utf-8")
        proc = subprocess.run(argv, capture_output=True, text=True)
        assert proc.returncode == 0 and proc.stdout.startswith("Here's your finished"), proc.stderr
