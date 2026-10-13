"""A run owns its folder: in a run dir that carries a ref, nothing of another run's reaches its work.

The shape every row builds: run O started and bound into a folder, then run N started and bound into the same
folder (N is the folder's current run: the newest bind). The folder holds the skill's fixture files.

- A step named with O's id is refused `RUN_SUPERSEDED`; with an id bound nowhere here, `RUN_NOT_BOUND`. The
  lever: the same call named with N's id gets past the check.
- A step reading a run file stamped with O's id is refused `ARTIFACT_OTHER_RUN`, naming it. The lever: the same
  file restamped to N, the same call gets past the check.
Ids and figures are synthetic.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gate_run_helpers as h  # noqa: E402
import no_ledger_goldens as goldens  # noqa: E402

SKILLS = h.SKILLS
OWNERSHIP_CODES = {"RUN_ID_REQUIRED", "RUN_NOT_BOUND", "RUN_SUPERSEDED", "ARTIFACT_OTHER_RUN"}
STRANGER = "20260101T000000Z-5a5a5a"


@dataclass
class Folder:
    root: Path
    old: str
    new: str
    dir: Path


def two_runs(tmp: Path, skill: str, build: Callable[[Path], None]) -> Folder:
    """O bound, the fixture written, then N bound into the same folder; every run file restamped to N."""
    root, old, run_dir = h.start_bound(tmp, skill)
    # Built in a folder with no ref (the builders run producers under their own ids), then moved in.
    stage = tmp / "stage"
    stage.mkdir()
    build(stage)
    for p in stage.iterdir():
        if p.is_file():
            shutil.copy(p, run_dir / p.name)
    new = h.start_ok(root, skill)
    proc = h.bind(root, new, run_dir, "example-co")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    restamp_all(run_dir, new)
    return Folder(root, old, new, run_dir)


def restamp_all(run_dir: Path, run_id: str) -> None:
    for p in run_dir.glob("*.json"):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if isinstance(data, dict) and isinstance(data.get("metadata"), dict) and "run_id" in data["metadata"]:
            goldens._restamp(p, run_id)


def code_of(proc: subprocess.CompletedProcess[str]) -> str | None:
    for line in reversed(proc.stdout.strip().splitlines()):
        try:
            body = json.loads(line)
        except ValueError:
            continue
        if isinstance(body, dict):
            code = body.get("code")
            return code if isinstance(code, str) else None
    return None


def statuses(f: Folder) -> tuple[bytes, bytes]:
    return h.status_path(f.root, f.old).read_bytes(), h.status_path(f.root, f.new).read_bytes()


# --- producers: the run id must be the folder's current run ----------------------------------------------


@dataclass
class Producer:
    skill: str
    build: Callable[[Path], None]
    call: Callable[[Path, str], tuple[list[str], str | None, Path]]  # (argv, stdin, the -o it would write)


def _ms_checklist(d: Path, rid: str) -> tuple[list[str], str | None, Path]:
    items = json.loads((goldens.FIXTURES / "market-sizing" / "checklist.json").read_text(encoding="utf-8"))["items"]
    out = d / "checklist_out.json"
    argv = [str(goldens.MS_SCRIPTS / "checklist.py"), "--run-id", rid, "--sizing", str(d / "sizing.json")]
    return [*argv, "--inputs", str(d / "inputs.json"), "-o", str(out)], json.dumps({"items": items}), out


def _fmr_unit_economics(d: Path, rid: str) -> tuple[list[str], str | None, Path]:
    out = d / "ue_out.json"
    return [str(goldens.FMR_SCRIPTS / "unit_economics.py"), "--run-id", rid, "-o", str(out)], goldens._fmr_inputs(), out


def _cp_checklist(d: Path, rid: str) -> tuple[list[str], str | None, Path]:
    out = d / "checklist_out.json"
    items = {"items": goldens._cp_fixture("checklist.json")["items"]}
    argv = [str(goldens.CP_SCRIPTS / "checklist.py"), "--run-id", rid, "--input-mode", "deck"]
    return [*argv, "--positioning-scores", str(d / "positioning_scores.json"), "-o", str(out)], json.dumps(items), out


def _ic_fund_profile(d: Path, rid: str) -> tuple[list[str], str | None, Path]:
    body = json.loads((goldens.FIXTURES / "ic-sim" / "fund_profile.json").read_text(encoding="utf-8"))
    for key in ("validation", "metadata"):
        body.pop(key, None)
    out = d / "fund_profile_out.json"
    return [str(goldens.IC_SCRIPTS / "fund_profile.py"), "--run-id", rid, "-o", str(out)], json.dumps(body), out


def _ct_cap_state(d: Path, rid: str) -> tuple[list[str], str | None, Path]:
    out = d / "cap_state_out.json"
    argv = [str(SKILLS / "cap-table" / "scripts" / "cap_state.py"), "--inputs", str(d / "inputs.json")]
    return [*argv, "--instruments", str(d / "instruments.json"), "--run-id", rid, "-o", str(out)], None, out


PRODUCERS = {
    "market-sizing/checklist.py": Producer("market-sizing", goldens._ms_ref_dir, _ms_checklist),  # type: ignore[arg-type]
    "financial-model-review/unit_economics.py": Producer(
        "financial-model-review", goldens._fmr_review_dir, _fmr_unit_economics
    ),
    "competitive-positioning/checklist.py": Producer("competitive-positioning", goldens._cp_dir, _cp_checklist),
    "ic-sim/fund_profile.py": Producer("ic-sim", goldens._ic_dir, _ic_fund_profile),
    "cap-table/cap_state.py": Producer("cap-table", goldens.ct_dir, _ct_cap_state),
}


@pytest.mark.parametrize("name", sorted(PRODUCERS))
def test_a_producer_named_with_the_replaced_run_is_refused(name: str, tmp_path: Path) -> None:
    p = PRODUCERS[name]
    f = two_runs(tmp_path, p.skill, p.build)
    before = statuses(f)
    for rid, code in ((f.old, "RUN_SUPERSEDED"), (STRANGER, "RUN_NOT_BOUND")):
        argv, stdin, out = p.call(f.dir, rid)
        proc = h.run(*argv, stdin=stdin)  # type: ignore[arg-type]
        assert proc.returncode == 1 and code_of(proc) == code, (rid, proc.stdout, proc.stderr)
        assert not out.exists()
        assert statuses(f) == before


@pytest.mark.parametrize("name", sorted(PRODUCERS))
def test_the_same_producer_named_with_the_folders_run_gets_past_the_check(name: str, tmp_path: Path) -> None:
    """The lever: without it the refusal rows could green on an unrelated refusal."""
    p = PRODUCERS[name]
    f = two_runs(tmp_path, p.skill, p.build)
    argv, stdin, _out = p.call(f.dir, f.new)
    proc = h.run(*argv, stdin=stdin)  # type: ignore[arg-type]
    assert code_of(proc) not in OWNERSHIP_CODES, (proc.stdout, proc.stderr)
    assert proc.returncode in (0, 10), (proc.stdout, proc.stderr)


def test_supersede_names_the_run_that_holds_the_folder(tmp_path: Path) -> None:
    p = PRODUCERS["cap-table/cap_state.py"]
    f = two_runs(tmp_path, p.skill, p.build)
    argv, stdin, _out = p.call(f.dir, f.old)
    body = json.loads(h.run(*argv, stdin=stdin).stdout)  # type: ignore[arg-type]
    assert body["code"] == "RUN_SUPERSEDED" and body["current_run"] == f.new and f.new in body["message"]


# --- consumers: every run file a step reads must be this run's ----------------------------------------------


@dataclass
class Consumer:
    skill: str
    build: Callable[[Path], None]
    foreign: str  # the run file left stamped with the replaced run's id
    call: Callable[[Path, str], tuple[list[str], str | None, Path]]


def _dr_reconcile(d: Path, rid: str) -> tuple[list[str], str | None, Path]:
    out = d / "reconciliation_out.json"
    argv = [str(SKILLS / "deck-review" / "scripts" / "reconcile.py"), "--ledger", str(d / "ledger.json")]
    argv += ["--second-read", str(d / "second_read.json"), "--inventory", str(d / "deck_inventory.json")]
    return [*argv, "--run-id", rid, "-o", str(out)], json.dumps({"relations": []}), out


def _ic_discussion(d: Path, rid: str) -> tuple[list[str], str | None, Path]:
    out = d / "discussion_out.json"
    return (
        [str(goldens.IC_SCRIPTS / "compose_discussion.py"), "--dir", str(d), "--run-id", rid, "-o", str(out)],
        None,
        out,
    )


def _cp_positioning(d: Path, rid: str) -> tuple[list[str], str | None, Path]:
    out = d / "positioning_scores_out.json"
    argv = [str(goldens.CP_SCRIPTS / "score_positioning.py"), "--run-id", rid]
    argv += ["--product-profile", str(d / "product_profile.json"), "-o", str(out)]
    return argv, json.dumps(goldens._cp_fixture("positioning.json")), out


def _fmr_checklist(d: Path, rid: str) -> tuple[list[str], str | None, Path]:
    items = json.loads((goldens.FIXTURES / "financial-model-review" / "checklist.json").read_text(encoding="utf-8"))
    payload = {"items": items["items"], "company": json.loads((d / "inputs.json").read_text())["company"]}
    out = d / "checklist_out.json"
    argv = [str(goldens.FMR_SCRIPTS / "checklist.py"), "--inputs", str(d / "inputs.json"), "--run-id", rid]
    return [*argv, "-o", str(out)], json.dumps(payload), out


def _ct_rule_audit(d: Path, rid: str) -> tuple[list[str], str | None, Path]:
    out = d / "rule_audit_out.json"
    argv = [str(SKILLS / "cap-table" / "scripts" / "rule_audit.py"), "--phase=pre_math", "--inputs"]
    argv += [str(d / "inputs.json"), "--instruments", str(d / "instruments.json")]
    return [*argv, "--cap-state", str(d / "cap_state.json"), "--run-id", rid, "-o", str(out)], None, out


def _ct_with_cap_state(d: Path) -> None:
    goldens.ct_dir(d)
    i, n = str(d / "inputs.json"), str(d / "instruments.json")
    proc = goldens._ct(
        "cap_state.py", "--inputs", i, "--instruments", n, "--run-id", goldens.CT_RUN, "-o", str(d / "cap_state.json")
    )
    assert proc.returncode == 0, proc.stderr


CONSUMERS = {
    "deck-review/reconcile.py --ledger": Consumer("deck-review", goldens._dr_dir, "ledger.json", _dr_reconcile),
    "ic-sim/compose_discussion.py (a partner file)": Consumer(
        "ic-sim", goldens._ic_dir, "partner_assessment_visionary.json", _ic_discussion
    ),
    "competitive-positioning/score_positioning.py --product-profile": Consumer(
        "competitive-positioning", goldens._cp_dir, "product_profile.json", _cp_positioning
    ),
    "market-sizing/checklist.py --sizing": Consumer(
        "market-sizing",
        goldens._ms_ref_dir,  # type: ignore[arg-type]
        "sizing.json",
        _ms_checklist,
    ),
    "financial-model-review/checklist.py --inputs": Consumer(
        "financial-model-review", goldens._fmr_review_dir, "inputs.json", _fmr_checklist
    ),
    "cap-table/rule_audit.py --cap-state": Consumer("cap-table", _ct_with_cap_state, "cap_state.json", _ct_rule_audit),
}


@pytest.mark.parametrize("name", sorted(CONSUMERS))
def test_a_step_reading_another_runs_file_is_refused_naming_it(name: str, tmp_path: Path) -> None:
    c = CONSUMERS[name]
    f = two_runs(tmp_path, c.skill, c.build)
    goldens._restamp(f.dir / c.foreign, f.old)
    argv, stdin, out = c.call(f.dir, f.new)
    proc = h.run(*argv, stdin=stdin)  # type: ignore[arg-type]
    assert proc.returncode == 1 and code_of(proc) == "ARTIFACT_OTHER_RUN", (proc.stdout, proc.stderr)
    body = json.loads(proc.stdout.strip().splitlines()[-1])
    assert body["files"] == [{"file": c.foreign, "run_id": f.old}]
    assert "run the step that writes" in body["fix"]
    assert not out.exists()


@pytest.mark.parametrize("name", sorted(CONSUMERS))
def test_the_same_file_restamped_to_the_run_gets_past_the_check(name: str, tmp_path: Path) -> None:
    c = CONSUMERS[name]
    f = two_runs(tmp_path, c.skill, c.build)
    argv, stdin, _out = c.call(f.dir, f.new)
    proc = h.run(*argv, stdin=stdin)  # type: ignore[arg-type]
    assert code_of(proc) not in OWNERSHIP_CODES, (proc.stdout, proc.stderr)
    assert proc.returncode in (0, 10), (proc.stdout, proc.stderr)


def test_an_unbound_folder_loads_nothing_shared(tmp_path: Path) -> None:
    """No ref: the check returns before reading anything, and never loads the plugin's shared code."""
    ref = SKILLS / "market-sizing" / "scripts"
    goldens._ms_ref_dir(tmp_path)  # type: ignore[arg-type]
    goldens._restamp(tmp_path / "sizing.json", STRANGER)
    code = (
        "import sys; sys.path.insert(0, sys.argv[1]); import _run_ref; "
        "_run_ref.refuse_not_this_runs(sys.argv[2], 'whatever-id', [sys.argv[2] + '/sizing.json'], noun='x'); "
        "print('_run_status' in sys.modules)"
    )
    proc = h.run("-c", code, str(ref), str(tmp_path))  # type: ignore[arg-type]
    assert proc.returncode == 0 and proc.stdout.strip() == "False", proc.stderr
    assert proc.stderr == ""


# --- structural: every reader of run files with a --run-id checks them ------------------------------------

PLUGIN = h.REPO_ROOT / "founder-skills"
# (script, the input it does not compare) -> why. May only shrink.
EXEMPT_PARITY: dict[tuple[str, str], str] = {
    ("skills/cap-table/scripts/extract_instrument.py", "--instruments"): "its own append guard already refuses an "
    "earlier run's instruments store; its other inputs are the founder's documents",
    ("skills/cap-table/scripts/extract_cap_table.py", "--dir"): "lane 3 rewrites the dir's inputs.json in place for "
    "this run and the validate lane reads the founder's spreadsheet; its own gate checks bind a spreadsheet-built base",
    ("skills/cap-table/scripts/write_coverage_disclosure.py", "--input"): "its input is the model's staged payload "
    "(stdin or a scratch file), not a run file",
    ("skills/competitive-positioning/scripts/persist_agent_artifact.py", "--input"): "its input is a sub-agent's "
    "hand-off under handoff/<run_id>/, namespaced per run and gated by check_handoff.py",
    ("skills/market-sizing/scripts/red_team.py", "--uploads-dir"): "reads no run file: stdin and the founder's uploads",
    # Compose and the pages read their run files from --dir; they check them in their own commits.
    ("skills/cap-table/scripts/compose_report.py", "--dir"): "compose: its own required scan",
    ("skills/cap-table/scripts/visualize.py", "--dir"): "page: its own required scan",
    ("skills/cap-table/scripts/explore.py", "--dir"): "page: its own required scan",
    ("skills/competitive-positioning/scripts/visualize.py", "--dir"): "page: its own required scan",
    ("skills/competitive-positioning/scripts/explore.py", "--dir"): "page: its own required scan",
    ("skills/deck-review/scripts/visualize.py", "--dir"): "page: its own required scan",
    ("skills/financial-model-review/scripts/visualize.py", "--dir"): "page: its own required scan",
    ("skills/financial-model-review/scripts/explore.py", "--dir"): "page: its own required scan",
    ("skills/ic-sim/scripts/visualize.py", "--dir"): "page: its own required scan",
    ("skills/market-sizing/scripts/visualize.py", "--dir"): "page: its own required scan",
}


def _parity_findings() -> list[str]:
    import ast

    problems = []
    for path in sorted(PLUGIN.glob("skills/*/scripts/*.py")):
        rel = path.relative_to(PLUGIN).as_posix()
        src = path.read_text(encoding="utf-8")
        if '"--run-id"' not in src:
            continue
        tree = ast.parse(src)
        names = {
            (n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, "id", ""))
            for n in ast.walk(tree)
            if isinstance(n, ast.Call)
        }
        if "refuse_output_onto_input" not in names and not rel.endswith("dispatch_prompt.py"):
            continue
        calls = [
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "refuse_not_this_runs"
        ]
        with_inputs = [
            c
            for c in calls
            if (len(c.args) >= 3 and not (isinstance(c.args[2], ast.List) and not c.args[2].elts))
            or any(k.arg == "inputs" for k in c.keywords)
        ]
        if with_inputs or any(r == rel for r, _f in EXEMPT_PARITY):
            continue
        problems.append(f"{rel}: has --run-id and reads run files, but never checks they are this run's")
    return problems


def test_every_reader_with_a_run_id_checks_its_inputs_or_is_exempt() -> None:
    assert _parity_findings() == []


def test_every_parity_exemption_names_a_script_that_exists() -> None:
    assert [r for r, _f in EXEMPT_PARITY if not (PLUGIN / r).is_file()] == []
