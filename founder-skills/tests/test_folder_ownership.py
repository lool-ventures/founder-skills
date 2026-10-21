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

import hashlib
import json
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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


_DR_DECK = b"%PDF synthetic"


def _dr_ocr_build(d: Path) -> None:
    """Step 3.95's inputs: a deck, a ledger and a reconciliation with no relation (so nothing needs reading)."""
    (d / "deck.pdf").write_bytes(_DR_DECK)
    (d / "ledger.json").write_text(json.dumps({"figures": [], "metadata": {"run_id": "builder"}}), encoding="utf-8")
    recon = {"status": "checked", "relations": [], "metadata": {"run_id": "builder"}}
    (d / "reconciliation.json").write_text(json.dumps(recon), encoding="utf-8")


def _dr_deck_text(d: Path, rid: str) -> Path:
    sha = hashlib.sha256(_DR_DECK).hexdigest()
    path = d / "deck_text.md"
    path.write_text(
        f"---\nrun_id: {rid}\nsource: inventory\npages_source: {{1: inventory}}\ndeck_sha256: {sha}\n---\n"
        "## Slide 1\n\nText\n",
        encoding="utf-8",
    )
    return path


def _dr_deck_ocr(d: Path, rid: str) -> tuple[list[str], str | None, Path]:
    out = d / "handoff" / "ocr-check-run" / "ocr"
    argv = [str(SKILLS / "deck-review" / "scripts" / "deck_ocr.py"), "--deck", str(d / "deck.pdf")]
    argv += ["--ledger", str(d / "ledger.json"), "--reconciliation", str(d / "reconciliation.json")]
    return [*argv, "--deck-text", str(_dr_deck_text(d, rid)), "--run-id", rid, "-o", str(out)], None, out


def _dr_ocr_check(d: Path, rid: str) -> tuple[list[str], str | None, Path]:
    ocr = d / "handoff" / "ocr-check-run" / "ocr"
    ocr.mkdir(parents=True, exist_ok=True)
    receipt = {"run_id": rid, "complete": True, "status": "no_figures", "reason": "no_figures"}
    receipt["deck_sha256"] = hashlib.sha256(_DR_DECK).hexdigest()
    (ocr / "receipt.json").write_text(json.dumps(receipt), encoding="utf-8")
    out = d / "ocr_check_out.json"
    argv = [str(SKILLS / "deck-review" / "scripts" / "ocr_check.py"), "--ledger", str(d / "ledger.json")]
    argv += ["--reconciliation", str(d / "reconciliation.json"), "--deck-text", str(_dr_deck_text(d, rid))]
    return [*argv, "--ocr-dir", str(ocr), "--run-id", rid, "-o", str(out)], None, out


PRODUCERS = {
    "market-sizing/checklist.py": Producer("market-sizing", goldens._ms_ref_dir, _ms_checklist),  # type: ignore[arg-type]
    "financial-model-review/unit_economics.py": Producer(
        "financial-model-review", goldens._fmr_review_dir, _fmr_unit_economics
    ),
    "competitive-positioning/checklist.py": Producer("competitive-positioning", goldens._cp_dir, _cp_checklist),
    "ic-sim/fund_profile.py": Producer("ic-sim", goldens._ic_dir, _ic_fund_profile),
    "cap-table/cap_state.py": Producer("cap-table", goldens.ct_dir, _ct_cap_state),
    "deck-review/deck_ocr.py": Producer("deck-review", _dr_ocr_build, _dr_deck_ocr),
    "deck-review/ocr_check.py": Producer("deck-review", _dr_ocr_build, _dr_ocr_check),
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
    ("skills/cap-table/scripts/compose_extraction_report.py", "--review-dir"): "the folder it writes the terms-only "
    "report into; the run files it reads come through --inputs, --instruments and --audit, which are checked",
    (
        "skills/competitive-positioning/scripts/cp_red_team.py",
        "--uploads-dir",
    ): "the founder's documents, not run files",
    ("skills/cap-table/scripts/write_coverage_disclosure.py", "--input"): "its input is the model's staged payload "
    "(stdin or a scratch file), not a run file",
    ("skills/competitive-positioning/scripts/persist_agent_artifact.py", "--input"): "its input is a sub-agent's "
    "hand-off under handoff/<run_id>/, namespaced per run and gated by check_handoff.py",
    ("skills/market-sizing/scripts/red_team.py", "--uploads-dir"): "reads no run file: stdin and the founder's uploads",
}
# Each skill's `_compose_result.py` reads compose's own argv to record what compose wrote; compose checks its files.
for _skill in (
    "cap-table",
    "competitive-positioning",
    "deck-review",
    "financial-model-review",
    "ic-sim",
    "market-sizing",
):
    EXEMPT_PARITY[(f"skills/{_skill}/scripts/_compose_result.py", "--dir")] = (
        "compose's wrapper: reads compose's argv to file its record; compose itself checks the run's files"
    )


RUN_FILE_FLAGS = frozenset(
    {
        "--inputs",
        "--instruments",
        "--cap-state",
        "--scenarios",
        "--rule-audit",
        "--audit",
        "--sizing",
        "--validation",
        "--replay",
        "--inventory",
        "--reconciliation",
        "--slide-reviews",
        "--deck-text",
        "--ledger",
        "--second-read",
        "--downgrades",
        "--positioning-scores",
        "--product-profile",
        "--carry-deferred",
        "--landscape",
        "--blind-set",
        "--scores",
        "--draft",
        "--original",
        "--input",
        "--dir",
        "--review-dir",
        "--analysis-dir",
        "--uploads-dir",
        "--profile",
    }
)


def _flag_dests(tree: Any) -> dict[str, str]:
    """{flag: dest} for every RUN_FILE_FLAGS flag the script registers."""
    import ast

    out: dict[str, str] = {}
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "add_argument":
            flags = [a.value for a in n.args if isinstance(a, ast.Constant) and isinstance(a.value, str)]
            dest = next(
                (k.value.value for k in n.keywords if k.arg == "dest" and isinstance(k.value, ast.Constant)), None
            )
            longs = [f for f in flags if f.startswith("--")]
            for f in flags:
                if f in RUN_FILE_FLAGS:
                    out[f] = str(dest or longs[0][2:].replace("-", "_"))
    return out


def _parity_findings() -> list[str]:
    """Every run-file flag of every skill script that takes a --run-id (an output flag or not) reaches a
    `refuse_not_this_runs` / `compose_run_or_exit` call, or is exempt as (script, flag) with a reason. A script's
    exemption covers only the flag it names."""
    import ast

    problems = []
    for path in sorted(PLUGIN.glob("skills/*/scripts/*.py")):
        rel = path.relative_to(PLUGIN).as_posix()
        src = path.read_text(encoding="utf-8")
        if '"--run-id"' not in src:
            continue
        tree = ast.parse(src)
        flags = _flag_dests(tree)
        if not flags:
            continue
        checked: set[str] = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.Call) and getattr(n.func, "attr", "") in (
                "refuse_not_this_runs",
                "compose_run_or_exit",
            ):
                checked |= {s.attr for s in ast.walk(n) if isinstance(s, ast.Attribute)}
                checked |= {s.id for s in ast.walk(n) if isinstance(s, ast.Name)}
        for flag, dest in sorted(flags.items()):
            if (rel, flag) in EXEMPT_PARITY or dest in checked:
                continue
            problems.append(f"{rel}: {flag} (args.{dest}) reads run files and never reaches the ownership check")
    return problems


# Readers of run files that take no --run-id, so they have nothing to compare against: why each is left out.
NO_RUN_ID_READERS: dict[str, str] = {
    "skills/competitive-positioning/scripts/gate3_triggers.py": "reads the positioning scores the same step pair "
    "just wrote and prints which Gate 3 triggers fire; its output is read once in the main thread, never a run "
    "artifact another step consumes, so giving it a --run-id would add a flag with nothing behind it",
}


def test_every_reader_with_a_run_id_checks_its_inputs_or_is_exempt() -> None:
    assert _parity_findings() == []


def test_the_readers_with_no_run_id_still_have_none() -> None:
    """If one gains a --run-id, it moves into the scan above and this entry goes."""
    for rel in NO_RUN_ID_READERS:
        assert '"--run-id"' not in (PLUGIN / rel).read_text(encoding="utf-8"), rel


def test_an_exemption_covers_only_its_own_flag() -> None:
    """The scan is per flag: exempting one flag of a script leaves its other run-file flags checked."""
    assert all(isinstance(k, tuple) and k[1] in RUN_FILE_FLAGS for k in EXEMPT_PARITY), sorted(EXEMPT_PARITY)
    # extract_cap_table.py's lanes 2 and 3 merge into the run's store: both flags are checked, neither exempt.
    rel = "skills/cap-table/scripts/extract_cap_table.py"
    assert (rel, "--instruments") not in EXEMPT_PARITY and (rel, "--dir") not in EXEMPT_PARITY
    assert not [p for p in _parity_findings() if p.startswith(rel)]


def test_every_parity_exemption_names_a_script_that_exists() -> None:
    assert [r for r, _f in EXEMPT_PARITY if not (PLUGIN / r).is_file()] == []


# --- compose: built only from the folder's current run ----------------------------------------------------


def _ct_compose_for(rid: str) -> Callable[[Path], subprocess.CompletedProcess[str]]:
    def run(d: Path) -> subprocess.CompletedProcess[str]:
        argv = ["compose_report.py", "--dir", str(d), "--run-id", rid]
        return goldens._ct(*argv, "-o", str(d / "report.json"), "--write-md", str(d / "report.md"))

    return run


@dataclass
class Compose:
    skill: str
    build: Callable[[Path], None]
    run: Callable[[Folder], subprocess.CompletedProcess[str]]
    required: tuple[str, ...]


def _required(skill: str) -> tuple[str, ...]:
    import ast

    tree = ast.parse((SKILLS / skill / "scripts" / "compose_report.py").read_text(encoding="utf-8"))
    names: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") in (
            "REQUIRED_ARTIFACTS",
            "RUN_ALWAYS_WRITES",
        ):
            names += list(ast.literal_eval(node.value))
    return tuple(names)


COMPOSES = {
    "market-sizing": Compose(
        "market-sizing",
        lambda r: goldens._ms_variant(r, "plain"),
        lambda f: goldens._ms_compose(f.dir),
        _required("market-sizing"),
    ),
    "financial-model-review": Compose(
        "financial-model-review",
        goldens._fmr_review_dir,
        lambda f: goldens._fmr_compose(f.dir),
        _required("financial-model-review"),
    ),
    "ic-sim": Compose("ic-sim", goldens._ic_dir, lambda f: goldens._ic_compose(f.dir), _required("ic-sim")),
    "competitive-positioning": Compose(
        "competitive-positioning",
        goldens._cp_dir,
        lambda f: goldens._cp_compose(f.dir),
        _required("competitive-positioning"),
    ),
    "deck-review": Compose(
        "deck-review", goldens._dr_dir, lambda f: goldens._dr_compose(f.dir), _required("deck-review")
    ),
    "cap-table": Compose(
        "cap-table", goldens._ct_full, lambda f: _ct_compose_for(f.new)(f.dir), _required("cap-table")
    ),
}


def _outputs_and_statuses(f: Folder) -> tuple[bool, bool, tuple[bytes, bytes]]:
    return (f.dir / "report.json").exists(), (f.dir / "report.md").exists(), statuses(f)


@pytest.mark.parametrize("skill", sorted(COMPOSES))
def test_compose_over_a_wholly_earlier_set_refuses_every_required_file(skill: str, tmp_path: Path) -> None:
    c = COMPOSES[skill]
    f = two_runs(tmp_path, c.skill, c.build)
    restamp_all(f.dir, f.old)
    before = statuses(f)
    proc = c.run(f)
    assert proc.returncode == 1 and code_of(proc) == "ARTIFACT_OTHER_RUN", (proc.stdout, proc.stderr)
    named = {x["file"] for x in json.loads(proc.stdout.strip().splitlines()[-1])["files"]}
    stamped = {n for n in c.required if json.loads((f.dir / n).read_text()).get("metadata", {}).get("run_id")}
    assert named == stamped and stamped
    assert _outputs_and_statuses(f) == (False, False, before)


@pytest.mark.parametrize("skill", sorted(COMPOSES))
def test_compose_names_exactly_the_one_required_file_left_from_the_earlier_run(skill: str, tmp_path: Path) -> None:
    c = COMPOSES[skill]
    f = two_runs(tmp_path, c.skill, c.build)
    left = c.required[-1]
    goldens._restamp(f.dir / left, f.old)
    proc = c.run(f)
    assert proc.returncode == 1 and code_of(proc) == "ARTIFACT_OTHER_RUN", (proc.stdout, proc.stderr)
    assert json.loads(proc.stdout.strip().splitlines()[-1])["files"] == [{"file": left, "run_id": f.old}]
    assert not (f.dir / "report.json").exists()


@pytest.mark.parametrize("skill", sorted(COMPOSES))
def test_compose_over_the_folders_own_files_gets_past_ownership(skill: str, tmp_path: Path) -> None:
    """The lever for the two rows above: the same set restamped to the folder's run passes the check (and then
    stops wherever the run's own gates stop it)."""
    c = COMPOSES[skill]
    f = two_runs(tmp_path, c.skill, c.build)
    proc = c.run(f)
    assert code_of(proc) not in OWNERSHIP_CODES, (proc.stdout, proc.stderr)


@pytest.mark.parametrize("skill", ["market-sizing", "financial-model-review"])
def test_inputs_carrying_another_runs_id_is_refused(skill: str, tmp_path: Path) -> None:
    """Their composes used to derive the run from inputs.json alone: a well-formed other id there composed with
    no ledger and every gate skipped. Now the folder's run is read from its refs and inputs.json is named."""
    c = COMPOSES[skill]
    f = two_runs(tmp_path, c.skill, c.build)
    goldens._restamp(f.dir / "inputs.json", STRANGER)
    proc = c.run(f)
    assert proc.returncode == 1 and code_of(proc) == "ARTIFACT_OTHER_RUN", (proc.stdout, proc.stderr)
    assert json.loads(proc.stdout.strip().splitlines()[-1])["files"] == [{"file": "inputs.json", "run_id": STRANGER}]


def test_another_runs_pruned_ledger_does_not_lock_the_folder(tmp_path: Path) -> None:
    c = COMPOSES["competitive-positioning"]
    f = two_runs(tmp_path, c.skill, c.build)
    shutil.rmtree(f.root / "runs" / f.old)
    proc = c.run(f)
    assert code_of(proc) not in OWNERSHIP_CODES, (proc.stdout, proc.stderr)


def _complete(f: Folder, run_id: str) -> None:
    (f.dir / "report.md").write_text("# Example Co\n", encoding="utf-8")
    rs = _load_shared("_run_status")
    rs.complete_after_coaching(rs.run_paths(str(f.root), run_id), str(f.dir / "report.md"), None)


def _load_shared(name: str) -> Any:
    import importlib.util

    spec = importlib.util.spec_from_file_location(f"{name}_fo", h.SHARED / f"{name}.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[f"{name}_fo"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_a_what_if_on_a_replaced_complete_review_never_takes_the_folder_back(tmp_path: Path) -> None:
    """cap-table compose under the earlier run's id, the earlier run complete: refused before the reopen, so its
    revision does not move and the later run is not marked superseded."""
    c = COMPOSES["cap-table"]
    f = two_runs(tmp_path, c.skill, c.build)
    _complete(f, f.old)
    assert h.status(f.root, f.old)["status"] == "complete"
    restamp_all(f.dir, f.old)
    before = statuses(f)
    proc = _ct_compose_for(f.old)(f.dir)
    assert proc.returncode == 1 and code_of(proc) == "RUN_SUPERSEDED", (proc.stdout, proc.stderr)
    assert statuses(f) == before
    assert h.status(f.root, f.old)["revision"] == 0 and h.status(f.root, f.new)["superseded_by"] is None


# --- an optional file of another run is read as absent ----------------------------------------------------

SENTINEL = "Quillfeather Zentrovane"


def _cp_composed(tmp: Path, stamp_other: bool) -> tuple[subprocess.CompletedProcess[str], Path]:
    import test_cp_gates as cpg

    root, rid, rd = cpg._fixture_run(tmp)
    cpg._answer_all(root, rid, rd)
    profile = json.loads((rd / "product_profile.json").read_text(encoding="utf-8"))
    profile["product_description"] = f"{SENTINEL} for small firms."
    profile["metadata"]["run_id"] = STRANGER if stamp_other else rid
    (rd / "product_profile.json").write_text(json.dumps(profile), encoding="utf-8")
    return cpg._compose(rd), rd


def _dr_composed(tmp: Path, stamp_other: bool) -> tuple[subprocess.CompletedProcess[str], Path]:
    import test_deck_review_gates as drg

    root, rd = drg._run(tmp)
    drg._settle(rd, "stage_confirmation", "seed", "Looks right")
    ledger = json.loads((rd / "ledger.json").read_text(encoding="utf-8"))
    ledger["figures"][0]["label"] = SENTINEL
    ledger["figures"][0]["quote"] = f"{SENTINEL} of $493K in 2024"
    if stamp_other:
        ledger["metadata"]["run_id"] = STRANGER
    (rd / "ledger.json").write_text(json.dumps(ledger), encoding="utf-8")
    return drg._compose(rd), rd


OPTIONAL = {"competitive-positioning product_profile.json": _cp_composed}


def _delivered_text(rd: Path) -> str:
    return (rd / "report.md").read_text(encoding="utf-8") + (rd / "report.json").read_text(encoding="utf-8")


@pytest.mark.parametrize("name", sorted(OPTIONAL))
def test_another_runs_optional_file_is_left_out_of_the_report(name: str, tmp_path: Path) -> None:
    proc, rd = OPTIONAL[name](tmp_path, True)
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    assert SENTINEL not in _delivered_text(rd)
    receipt = json.loads(proc.stdout.strip().splitlines()[0])
    assert receipt["ignored_other_run"] == [name.split()[-1]]
    assert "left out" in proc.stderr


@pytest.mark.parametrize("name", sorted(OPTIONAL))
def test_the_same_optional_file_of_this_run_reaches_the_report(name: str, tmp_path: Path) -> None:
    """The lever: restamped to the run, the sentinel is in what the founder gets."""
    proc, rd = OPTIONAL[name](tmp_path, False)
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    assert SENTINEL in _delivered_text(rd)
    assert "ignored_other_run" not in json.loads(proc.stdout.strip().splitlines()[0])


# --- ic-sim: another run's partner file is refused by name, never as a stale profile ---------------------------


@pytest.mark.parametrize("same_profile", [True, False])
def test_another_runs_partner_file_is_named_not_reported_as_stale(same_profile: bool, tmp_path: Path) -> None:
    import test_ic_gates as icg

    root, rid, rd = icg._sim(tmp_path, "invest")
    target = rd / "partner_assessment_visionary.json"
    doc = json.loads(target.read_text(encoding="utf-8"))
    doc["metadata"]["run_id"] = STRANGER
    if not same_profile:
        doc["metadata"]["fund_profile_sha256"] = "0" * 64
        doc["metadata"]["fund_profile"] = {"sha256": "0" * 64}
    target.write_text(json.dumps(doc), encoding="utf-8")
    proc = icg._compose(rd)
    assert proc.returncode == 1 and code_of(proc) == "ARTIFACT_OTHER_RUN", (proc.stdout, proc.stderr)
    files = json.loads(proc.stdout.strip().splitlines()[-1])["files"]
    assert files == [{"file": "partner_assessment_visionary.json", "run_id": STRANGER}]
    assert "PARTNER_ARTIFACTS_STALE" not in proc.stdout


def test_deck_reviews_ledger_of_another_run_is_left_out_not_warned_about(tmp_path: Path) -> None:
    """deck-review's optional ledger joins the run-id parity loop when read; another run's is now left out, so the
    report carries no stale-file row for it (its content is checked, not rendered, so the observable is the row)."""
    proc, rd = _dr_composed(tmp_path, True)
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    assert json.loads(proc.stdout.strip().splitlines()[0])["ignored_other_run"] == ["ledger.json"]
    warnings = json.loads((rd / "report.json").read_text(encoding="utf-8"))["validation"]["warnings"]
    assert [w for w in warnings if w["code"] == "STALE_ARTIFACT"] == []
    same, rd2 = _dr_composed(tmp_path / "same", False)
    assert same.returncode == 0 and "ignored_other_run" not in json.loads(same.stdout.strip().splitlines()[0])


def test_a_host_resume_of_the_earlier_run_takes_the_folder_back_and_refuses_the_later_files(tmp_path: Path) -> None:
    """O bound, N bound later, then O re-bound (its resume runs the slug block again): O holds the folder, its
    compose names N's leftovers (saying to re-run them even on a resume), and N's id is now RUN_SUPERSEDED."""
    c = COMPOSES["competitive-positioning"]
    f = two_runs(tmp_path, c.skill, c.build)  # every file is N's
    assert h.bind(f.root, f.old, f.dir, "example-co").returncode == 0
    proc = c.run(f)
    assert proc.returncode == 1 and code_of(proc) == "ARTIFACT_OTHER_RUN", (proc.stdout, proc.stderr)
    body = json.loads(proc.stdout.strip().splitlines()[-1])
    assert {x["run_id"] for x in body["files"]} == {f.new}
    assert "another run bound to this folder" in body["message"] and "even on a resume" in body["fix"]
    p = PRODUCERS["competitive-positioning/checklist.py"]
    argv, stdin, _out = p.call(f.dir, f.new)
    assert code_of(h.run(*argv, stdin=stdin)) == "RUN_SUPERSEDED"  # type: ignore[arg-type]


def test_ic_sims_always_written_files_are_the_partner_files() -> None:
    """compose's RUN_ALWAYS_WRITES is fund_profile.PARTNER_FILES, the six files every run writes."""
    import ast

    tree = ast.parse((SKILLS / "ic-sim" / "scripts" / "compose_report.py").read_text(encoding="utf-8"))
    always = next(
        ast.literal_eval(n.value)
        for n in tree.body
        if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "RUN_ALWAYS_WRITES"
    )
    code = "import sys; sys.path.insert(0, sys.argv[1]); import fund_profile; print(list(fund_profile.PARTNER_FILES))"
    proc = h.run("-c", code, str(SKILLS / "ic-sim" / "scripts"))  # type: ignore[arg-type]
    assert sorted(always) == sorted(json.loads(proc.stdout.replace("'", '"'))), proc.stderr


# --- pages, closers and the insert --------------------------------------------------------------------------


def _ct_page(f: Folder, rid: str, script: str = "visualize.py") -> tuple[subprocess.CompletedProcess[str], Path]:
    page = f.dir / f"page_{script}.html"
    return goldens._ct(script, "--dir", str(f.dir), "--run-id", rid, "-o", str(page)), page


@pytest.mark.parametrize("script", ["visualize.py", "explore.py"])
def test_a_page_for_the_replaced_run_is_refused(script: str, tmp_path: Path) -> None:
    c = COMPOSES["cap-table"]
    f = two_runs(tmp_path, c.skill, c.build)
    proc, page = _ct_page(f, f.old, script)
    assert proc.returncode == 1 and code_of(proc) == "RUN_SUPERSEDED", (proc.stdout, proc.stderr)
    assert not page.exists()
    lever, page = _ct_page(f, f.new, script)
    assert code_of(lever) not in OWNERSHIP_CODES and page.exists(), (lever.stdout, lever.stderr)


def test_the_page_and_compose_give_the_same_code_for_a_resumed_runs_folder(tmp_path: Path) -> None:
    """O re-bound over N's files: compose and the page both name N's files (ARTIFACT_OTHER_RUN), so a host reads
    one answer from either surface; RUN_ID_MISMATCH keeps its unbound meaning."""
    c = COMPOSES["competitive-positioning"]
    f = two_runs(tmp_path, c.skill, c.build)
    assert h.bind(f.root, f.old, f.dir, "example-co").returncode == 0
    compose = c.run(f)
    page = goldens.run(
        [str(goldens.CP_SCRIPTS / "visualize.py"), "--dir", str(f.dir), "--run-id", f.old, "-o", str(f.dir / "r.html")]
    )
    assert code_of(compose) == code_of(page) == "ARTIFACT_OTHER_RUN", (compose.stdout, page.stdout)
    assert not (f.dir / "r.html").exists()


def _cp_page(rd: Path, rid: str) -> tuple[subprocess.CompletedProcess[str], Path]:
    page = rd / "report.html"
    argv = [str(goldens.CP_SCRIPTS / "visualize.py"), "--dir", str(rd), "--run-id", rid, "-o", str(page)]
    return goldens.run(argv), page


@pytest.mark.parametrize("stamp_other", [True, False])
def test_a_page_leaves_out_another_runs_optional_file(stamp_other: bool, tmp_path: Path) -> None:
    """The page names what it left out, as compose does; the lever is the parameter (this run's file: no note)."""
    proc, rd = _cp_composed(tmp_path, False)
    assert proc.returncode == 0, proc.stderr
    rid = json.loads((rd / "report.json").read_text(encoding="utf-8"))["run_id"]
    skip = json.loads((rd / "red_team_skip.json").read_text(encoding="utf-8"))
    skip["metadata"]["run_id"] = STRANGER if stamp_other else rid
    (rd / "red_team_skip.json").write_text(json.dumps(skip), encoding="utf-8")
    page_proc, page = _cp_page(rd, rid)
    assert page_proc.returncode == 0, (page_proc.stdout, page_proc.stderr)
    assert ("left out red_team_skip.json" in page_proc.stderr) is stamp_other


def test_a_pages_loader_reads_a_left_out_file_as_missing(tmp_path: Path) -> None:
    import importlib.util

    scripts = SKILLS / "competitive-positioning" / "scripts"
    sys.path.insert(0, str(scripts))
    spec = importlib.util.spec_from_file_location("cp_visualize_fo", scripts / "visualize.py")
    assert spec and spec.loader
    viz = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(viz)
    goldens._cp_dir(tmp_path)
    assert viz._load_artifact(str(tmp_path), "product_profile.json") is not None
    viz._IGNORED_OTHER_RUN.add("product_profile.json")
    assert viz._load_artifact(str(tmp_path), "product_profile.json") is None


def _cp_composed_then_replaced(tmp: Path) -> tuple[Path, str, str, Path]:
    """A composed report for run O, then a later run N bound into the same folder before N wrote anything."""
    proc, rd = _cp_composed(tmp, False)
    assert proc.returncode == 0, proc.stderr
    root = rd.parent
    old = json.loads((rd / "report.json").read_text(encoding="utf-8"))["run_id"]
    new = h.start_ok(root, "competitive-positioning")
    assert h.bind(root, new, rd, "example-co").returncode == 0
    return root, old, new, rd


def test_the_closer_refuses_a_report_of_the_run_the_folder_no_longer_belongs_to(tmp_path: Path) -> None:
    root, old, new, rd = _cp_composed_then_replaced(tmp_path)
    before = h.status_path(root, old).read_bytes()
    argv = [str(goldens.CP_SCRIPTS / "cp_closing_message.py"), "--report", str(rd / "report.json"), "--link", "path"]
    proc = goldens.run(argv)
    assert proc.returncode == 2 and proc.stdout == "" and "RUN_SUPERSEDED" in proc.stderr and new in proc.stderr
    assert not (rd / "handover.txt").exists()
    assert h.status_path(root, old).read_bytes() == before


def test_the_closer_prints_for_the_folders_own_run(tmp_path: Path) -> None:
    """The lever: the same report, the folder not taken by a later run, prints its hand-over."""
    proc, rd = _cp_composed(tmp_path, False)
    argv = [str(goldens.CP_SCRIPTS / "cp_closing_message.py"), "--report", str(rd / "report.json"), "--link", "path"]
    out = goldens.run(argv)
    # The fixture report has no verdict, so the hand-over itself is refused for that reason, after the check.
    assert "RUN_SUPERSEDED" not in out.stderr and "RUN_NOT_BOUND" not in out.stderr, out.stderr
    assert "carries no verdict" in out.stderr


def test_the_insert_refuses_coaching_for_the_run_the_folder_no_longer_belongs_to(tmp_path: Path) -> None:
    import test_report_run_id as rr

    root, run_dir, extra, stdin = rr._bound_for_insert("competitive-positioning", tmp_path)
    newer = h.start_ok(root, "competitive-positioning")
    assert h.bind(root, newer, run_dir, "example-co").returncode == 0
    before = (run_dir / "report.md").read_bytes(), h.status_path(root, rr.BOUND_RUN).read_bytes()
    proc = rr._insert_as_documented("competitive-positioning", run_dir, extra, stdin)
    assert proc.returncode == 1 and json.loads(proc.stdout)["code"] == "RUN_SUPERSEDED", proc.stdout
    assert ((run_dir / "report.md").read_bytes(), h.status_path(root, rr.BOUND_RUN).read_bytes()) == before
    lever_root, lever_dir, lever_extra, lever_stdin = rr._bound_for_insert("competitive-positioning", tmp_path / "x")
    lever = rr._insert_as_documented("competitive-positioning", lever_dir, lever_extra, lever_stdin)
    assert lever.returncode == 0, lever.stdout


# --- an archived review: a what-if there never marks the fresh run in the original folder ----------------


def test_a_what_if_in_an_archived_copy_leaves_the_fresh_run_alone(tmp_path: Path) -> None:
    root, old, run_dir = h.start_bound(tmp_path, "cap-table")
    stage = tmp_path / "stage"
    stage.mkdir()
    goldens._ct_full(stage)
    for p in stage.iterdir():
        if p.is_file():
            shutil.copy(p, run_dir / p.name)
    restamp_all(run_dir, old)
    (run_dir / "report.md").write_text("# Example Co\n", encoding="utf-8")
    rs = _load_shared("_run_status")
    rs.add_deliverable(rs.run_paths(str(root), old), "report_md", str(run_dir / "report.md"), "0" * 64, "test")
    rs.complete_after_coaching(rs.run_paths(str(root), old), str(run_dir / "report.md"), None)
    archive = root / "_archive" / run_dir.name
    archive.parent.mkdir()
    shutil.move(str(run_dir), str(archive))
    new = h.start_ok(root, "cap-table")
    assert h.bind(root, new, run_dir, "example-co").returncode == 0
    assert h.status(root, old)["superseded_by"] == new  # the archived run claims the original folder: expected
    before = h.status_path(root, new).read_bytes()
    proc = goldens._ct(
        "compose_report.py",
        "--dir",
        str(archive),
        "--run-id",
        old,
        "-o",
        str(archive / "report.json"),
        "--write-md",
        str(archive / "report.md"),
    )
    assert code_of(proc) not in OWNERSHIP_CODES, (proc.stdout, proc.stderr)
    assert h.status(root, old)["revision"] == 1, proc.stderr  # the what-if reopened the archived review
    assert h.status_path(root, new).read_bytes() == before, "the fresh run was marked replaced by the archive"
    # The archived review is being revised, not replaced: its folder is now the archive, and its mirror is clear.
    st = h.status(root, old)
    assert st["superseded_by"] is None and st["run_dir_shell"] == str(archive)


# --- cap-table lanes 2 and 3 merge into the run's store: never into an earlier review's ------------------------

CARTA = h.REPO_ROOT / "founder-skills" / "tests" / "fixtures" / "cap-table-corpus" / "synthetic_carta.xlsx"


def _ct_bound(tmp: Path) -> tuple[Path, str, Path]:
    import test_ct_gates as ctg

    root, rid, rd = ctg.bound(tmp)
    return root, rid, rd


def _carta(rd: Path, rid: str, out: Path | None = None) -> subprocess.CompletedProcess[str]:
    argv = [str(SKILLS / "cap-table" / "scripts" / "extract_cap_table.py"), "--mode=carta", "--xlsx", str(CARTA)]
    argv += ["--instruments", str(rd / "instruments.json"), "--run-id", rid]
    return goldens.run([*argv, "-o", str(out or rd / "extraction_audit.json")])


def _count(path: Path) -> int:
    d = json.loads(path.read_text(encoding="utf-8"))
    return sum(len(d.get(k) or []) for k in ("safes", "convertible_notes", "warrants", "preferred_series"))


@pytest.mark.parametrize("store", ["foreign", "this_run", "absent"])
def test_lane_2_merges_only_into_this_runs_store(store: str, tmp_path: Path) -> None:
    root, rid, rd = _ct_bound(tmp_path)
    inst = rd / "instruments.json"
    if store == "absent":
        inst.unlink(missing_ok=True)
    else:
        doc = json.loads(inst.read_text(encoding="utf-8"))
        doc["metadata"]["run_id"] = STRANGER if store == "foreign" else rid
        inst.write_text(json.dumps(doc), encoding="utf-8")
    before = inst.read_bytes() if inst.exists() else None
    proc = _carta(rd, rid)
    if store == "foreign":
        assert proc.returncode == 1 and code_of(proc) == "ARTIFACT_OTHER_RUN", (proc.stdout, proc.stderr)
        assert json.loads(proc.stdout.strip().splitlines()[-1])["files"] == [
            {"file": "instruments.json", "run_id": STRANGER}
        ]
        assert inst.read_bytes() == before and not (rd / "extraction_audit.json").exists()
    else:  # the lever: the first document (no store yet) and the run's own store still merge
        assert code_of(proc) not in OWNERSHIP_CODES and proc.returncode == 0, (proc.stdout, proc.stderr)
        assert _count(inst) > 0 and json.loads(inst.read_text())["metadata"]["run_id"] == rid


def test_lane_2_refuses_its_audit_written_onto_the_store(tmp_path: Path) -> None:
    root, rid, rd = _ct_bound(tmp_path)
    (rd / "instruments.json").unlink()
    proc = _carta(rd, rid, out=rd / "instruments.json")
    assert proc.returncode == 1 and code_of(proc) == "OUTPUT_IS_INPUT", (proc.stdout, proc.stderr)
    assert not (rd / "instruments.json").exists()


@pytest.mark.parametrize("foreign", [True, False])
def test_lane_3_merges_only_into_this_runs_base(foreign: bool, tmp_path: Path) -> None:
    root, rid, rd = _ct_bound(tmp_path)
    xlsx = goldens.ct_workbook(rd)
    inputs: dict[str, Any] = json.loads(json.dumps(goldens.CT_INPUTS))
    inputs["metadata"] = {"run_id": STRANGER if foreign else rid}
    (rd / "inputs.json").write_text(json.dumps(inputs), encoding="utf-8")
    (rd / "instruments.json").unlink(missing_ok=True)
    before = (rd / "inputs.json").read_bytes()
    argv = [str(SKILLS / "cap-table" / "scripts" / "extract_cap_table.py"), "--mode=freeform-emit", "--xlsx", str(xlsx)]
    argv += ["--dir", str(rd), "--run-id", rid, "--answer", "0.interest_rate_type=fixed_numeric_simple"]
    proc = goldens.run(argv, stdin=json.dumps(goldens.CT_NOTE_BLOCKS))
    if foreign:
        assert proc.returncode == 1 and code_of(proc) == "ARTIFACT_OTHER_RUN", (proc.stdout, proc.stderr)
        assert (rd / "inputs.json").read_bytes() == before and not (rd / "instruments.json").exists()
    else:
        assert code_of(proc) not in OWNERSHIP_CODES, (proc.stdout, proc.stderr)
        assert (rd / "inputs.json").read_bytes() != before  # the in-place merge still happens


@pytest.mark.parametrize("foreign", [True, False])
def test_the_aoa_merge_and_the_terms_report_read_only_this_runs_files(foreign: bool, tmp_path: Path) -> None:
    """extract_aoa.py writes its terms back into --inputs; compose_extraction_report.py renders from --inputs and
    --instruments. Neither takes another run's file (the lever: the same files stamped with this run's id)."""
    root, rid, rd = _ct_bound(tmp_path)
    for name in ("inputs.json", "instruments.json"):
        doc = json.loads((rd / name).read_text(encoding="utf-8"))
        doc["metadata"]["run_id"] = STRANGER if foreign else rid
        (rd / name).write_text(json.dumps(doc), encoding="utf-8")
    before = (rd / "inputs.json").read_bytes()
    aoa = goldens._ct("extract_aoa.py", "--inputs", str(rd / "inputs.json"), "--run-id", rid, stdin="{}")
    report = goldens._ct(
        "compose_extraction_report.py",
        "--inputs",
        str(rd / "inputs.json"),
        "--instruments",
        str(rd / "instruments.json"),
        "--review-dir",
        str(rd),
        "--run-id",
        rid,
    )
    if foreign:
        for proc in (aoa, report):
            assert proc.returncode == 1 and code_of(proc) == "ARTIFACT_OTHER_RUN", (proc.stdout, proc.stderr)
        assert (rd / "inputs.json").read_bytes() == before
    else:
        for proc in (aoa, report):
            assert code_of(proc) not in OWNERSHIP_CODES, (proc.stdout, proc.stderr)


# --- 8.6-3: market sizing's and financial model review's optional files of another run --------------------------


def test_market_sizings_review_of_another_run_reads_as_no_review(tmp_path: Path) -> None:
    """Another run's redteam.json is left out, so compose takes its absence path (no review and no recorded skip:
    refused), never treating the earlier review as this run's. The lever: the run's own review composes."""
    import test_ms_gates as msg

    root, rid, rd = msg._run_dir(tmp_path)
    msg._artifacts(rd, rid, redteam=msg._redteam(rid))
    msg._ok(msg._answer(root, rid, "ms_methodology", "looks_good"))
    assert msg._compose(rd).returncode == 10
    revision = h.run(
        msg.MS / "record_revision_answer.py", "--dir", str(rd), "--answer", "deliver", "--source", "founder"
    )
    msg._ok(revision)
    own = msg._compose(rd)
    assert own.returncode == 0, (own.stdout, own.stderr)
    assert "ignored_other_run" not in json.loads(own.stdout.strip().splitlines()[0])
    goldens._restamp(rd / "redteam.json", STRANGER)
    before = (rd / "report.json").read_bytes()
    proc = msg._compose(rd)
    assert proc.returncode != 0 and code_of(proc) not in OWNERSHIP_CODES, (proc.stdout, proc.stderr)
    assert "left out redteam.json" in proc.stderr
    assert (rd / "report.json").read_bytes() == before
    # Read as absent, exactly: the same compose with the file gone answers the same.
    (rd / "redteam.json").rename(tmp_path / "set_aside.json")
    absent = msg._compose(rd)
    assert (absent.returncode, absent.stdout) == (proc.returncode, proc.stdout)


def test_financial_model_reviews_corrections_of_another_run_are_left_out(tmp_path: Path) -> None:
    import test_fmr_gates as fg

    root, rid, rd = fg._delivered_without_cash(tmp_path)
    fg._ok(fg._apply(rd, rid, "cash.current_balance=900000", "cash.balance_date=2026-09"))
    # The reply is recorded first: a delivered review is never recomposed in place, so these composes run on the
    # reopened review.
    fg._ok(fg._cash_answer(root, rid, "900000", "2026-09"))
    ec = rd / "extraction_corrections.json"
    assert ec.is_file()
    own = fg._compose(rd)
    assert code_of(own) not in OWNERSHIP_CODES, (own.stdout, own.stderr)
    assert "extraction_corrections.json" not in own.stderr
    goldens._restamp(ec, STRANGER)
    proc = fg._compose(rd)
    assert code_of(proc) not in OWNERSHIP_CODES, (proc.stdout, proc.stderr)
    assert proc.returncode == own.returncode, (proc.stdout, proc.stderr)
    assert "left out extraction_corrections.json" in proc.stderr
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    assert json.loads(proc.stdout.strip().splitlines()[0])["ignored_other_run"] == ["extraction_corrections.json"]
    with_foreign = _report_text(rd)
    # Read as absent, exactly: the same compose with the file gone renders the same report.
    ec.rename(tmp_path / "set_aside.json")
    fg._ok(fg._compose(rd))
    assert _report_text(rd) == with_foreign


def _report_text(rd: Path) -> str:
    import re

    text = (rd / "report.md").read_text(encoding="utf-8")
    return re.sub(r"COACHING_INSERTION_POINT_[0-9a-f]+", "M", text)


# --- the resumed older run: one folder state, each surface's code pinned ------------------------------------------


def test_the_resumed_older_runs_folder_state_is_pinned_on_every_surface(tmp_path: Path) -> None:
    """O re-bound over N's composed files: compose and the page name N's artifacts (ARTIFACT_OTHER_RUN); the closer,
    given N's report, says the folder belongs to O now (RUN_SUPERSEDED). Both true; pinned so neither drifts."""
    proc, rd = _cp_composed(tmp_path, False)
    assert proc.returncode == 0, proc.stderr
    root = rd.parent
    n_run = json.loads((rd / "report.json").read_text(encoding="utf-8"))["run_id"]
    older = h.start_ok(root, "competitive-positioning")
    assert h.bind(root, older, rd, "example-co").returncode == 0  # O, "resumed": newest bind
    f = Folder(root, older, n_run, rd)
    compose = goldens._cp_compose(rd)
    page = goldens.run(
        [str(goldens.CP_SCRIPTS / "visualize.py"), "--dir", str(rd), "--run-id", older, "-o", str(rd / "o.html")]
    )
    closer = goldens.run(
        [str(goldens.CP_SCRIPTS / "cp_closing_message.py"), "--report", str(rd / "report.json"), "--link", "path"]
    )
    assert code_of(compose) == code_of(page) == "ARTIFACT_OTHER_RUN", (compose.stdout, page.stdout)
    assert closer.returncode == 2 and "RUN_SUPERSEDED" in closer.stderr and older in closer.stderr
    assert not (rd / "o.html").exists() and not (rd / "handover.txt").exists()
    assert f.new == n_run
