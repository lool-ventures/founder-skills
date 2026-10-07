"""What today's writers produce on a run with no gate ledger, captured as normalised hashes.

A run without `handoff/<run_id>/run_ref.json` must behave exactly as it did before the gate registry
existed: same stdout, same exit code, same bytes on disk. "Compare against a run of the same code
without the flag" cannot show that, because both arms run the edited code. So each scenario here was
run against the scripts as they stood before the registry was added, and its result is committed in
`fixtures/no_ledger_goldens.json`. The tests compare against that file, never against a fresh run of
some other arm.

Normalisation replaces only what legitimately varies between runs: the temp dir's path, timestamps,
random uuids and the per-run coaching marker suffix. Everything else is hashed as written.

The committed file was captured from a checkout of the commit before the registry, by pointing this
helper at that checkout's plugin (`NO_LEDGER_GOLDENS_PLUGIN`). Regenerate ONLY when a writer's no-ledger
behaviour is meant to change, the same way:
    git worktree add <dir> <commit-before-the-change>
    NO_LEDGER_GOLDENS_PLUGIN=<dir>/founder-skills python founder-skills/tests/no_ledger_goldens.py --write
    git worktree remove <dir>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
# The plugin whose scripts run. Fixtures and the goldens file are always this tree's.
PLUGIN = Path(os.environ.get("NO_LEDGER_GOLDENS_PLUGIN") or REPO_ROOT / "founder-skills")
SKILLS = PLUGIN / "skills"
SHARED = PLUGIN / "scripts"
FIXTURES = REPO_ROOT / "founder-skills" / "tests" / "fixtures"
GOLDEN_PATH = FIXTURES / "no_ledger_goldens.json"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from compose_invocations import drive_compose  # noqa: E402

# (skill, script, deliverable key) for the nine deliverable HTML writers.
HTML_WRITERS: tuple[tuple[str, str, str], ...] = (
    ("deck-review", "visualize.py", "report_html"),
    ("market-sizing", "visualize.py", "report_html"),
    ("ic-sim", "visualize.py", "report_html"),
    ("financial-model-review", "visualize.py", "report_html"),
    ("competitive-positioning", "visualize.py", "report_html"),
    ("cap-table", "visualize.py", "report_html"),
    ("financial-model-review", "explore.py", "explorer_html"),
    ("competitive-positioning", "explore.py", "explorer_html"),
    ("cap-table", "explore.py", "explorer_html"),
)

_TS = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?")
_COMPACT_TS = re.compile(r"\b\d{8}T\d{6}Z\b")
_UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b")
_MARKER = re.compile(r"(COACHING_INSERTION_POINT_)[0-9A-Za-z]+")
_DATE = re.compile(r"\b20\d{2}-\d{2}-\d{2}\b")
# A sha256 of a file that itself carries a timestamp varies with it.
_SHA64 = re.compile(r"\b[0-9a-f]{64}\b")


def normalise(text: str, tmp: str) -> str:
    for p in sorted({tmp, os.path.realpath(tmp)}, key=len, reverse=True):
        text = text.replace(p, "<TMP>")
    text = _TS.sub("<TS>", text)
    text = _COMPACT_TS.sub("<TS>", text)
    text = _UUID.sub("<UUID>", text)
    text = _MARKER.sub(r"\1<M>", text)
    text = _SHA64.sub("<SHA>", text)
    return _DATE.sub("<DATE>", text)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def tree_digest(root: Path, tmp: str) -> dict[str, str]:
    """Every file under `root`, by relative path, to the hash of its normalised text."""
    out: dict[str, str] = {}
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            full = Path(dirpath) / name
            rel = full.relative_to(root).as_posix()
            if "__pycache__" in rel or rel.endswith((".lock", ".xlsx")):
                continue
            try:
                body = full.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                out[rel] = hashlib.sha256(full.read_bytes()).hexdigest()
                continue
            out[rel] = _sha(normalise(body, tmp))
    return dict(sorted(out.items()))


def run(argv: list[str], *, stdin: str | None = None, cwd: str | None = None) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("FS_HOST_")}
    return subprocess.run(
        [sys.executable, *argv], input=stdin, capture_output=True, text=True, cwd=cwd, env=env, check=False
    )


def result(proc: subprocess.CompletedProcess[str], tmp: str, root: Path) -> dict[str, Any]:
    return {
        "exit": proc.returncode,
        "stdout": _sha(normalise(proc.stdout, tmp)),
        "stderr": _sha(normalise(proc.stderr, tmp)),
        "files": tree_digest(root, tmp),
    }


# --- HTML writers -------------------------------------------------------------------------------


def html_argv(skill: str, script: str, work: Path, out: Path) -> list[str]:
    argv = [str(SKILLS / skill / "scripts" / script), "--dir", str(work), "-o", str(out)]
    if skill == "deck-review" and script == "visualize.py":
        argv.append("--ungated")
    return argv


def html_stdout_scenario(skill: str, script: str) -> dict[str, Any]:
    """The page printed to stdout: no `-o`, so nothing is written and the HTML is the output."""
    with tempfile.TemporaryDirectory() as td:
        work = Path(td)
        drive_compose(skill, FIXTURES / skill, work)
        argv = html_argv(skill, script, work, work / "unused.html")
        i = argv.index("-o")
        res = result(run([*argv[:i], *argv[i + 2 :]]), td, work)
        res["files"] = {}
        return res


def html_scenario(skill: str, script: str) -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as td:
        work = Path(td)
        drive_compose(skill, FIXTURES / skill, work)
        out = work / "page.html"
        proc = run(html_argv(skill, script, work, out))
        res = result(proc, td, work)
        res["files"] = {"page.html": res["files"].get("page.html", "")}
        return res


# --- insert_coaching ----------------------------------------------------------------------------

COACH_RUN = "20261007T090000Z-0a1b2c"
COACH_MARKER = "<!-- COACHING_INSERTION_POINT_feedc0de -->"
COACH_REPORT = (
    "# Example Co review\n\nThe figures are as computed.\n\n"
    + COACH_MARKER
    + "\n\n---\n*Generated by [founder skills](https://example.org) for Example Co*\n"
)


def coaching_dir(root: Path, run_id: str = COACH_RUN) -> tuple[Path, Path, Path]:
    report = root / "report.md"
    report.write_text(COACH_REPORT, encoding="utf-8")
    report_json = root / "report.json"
    report_json.write_text(json.dumps({"report_markdown": COACH_REPORT, "metadata": {"run_id": run_id}}) + "\n")
    art = root / "inputs.json"
    art.write_text(json.dumps({"metadata": {"run_id": run_id}}))
    return report, report_json, art


def coaching_argv(report: Path, report_json: Path, art: Path, marker: str = COACH_MARKER) -> list[str]:
    return [
        str(SHARED / "insert_coaching.py"),
        "--report",
        str(report),
        "--marker",
        marker,
        "--verify-artifact",
        str(art),
        "--report-json",
        str(report_json),
    ]


COACH_STDIN = json.dumps({"commentary_markdown": "Lead with the customer count; the pipeline figure is softer."})


def coaching_scenarios() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        report, rj, art = coaching_dir(root)
        out["inserted"] = result(run(coaching_argv(report, rj, art), stdin=COACH_STDIN), td, root)
        out["already_inserted"] = result(run(coaching_argv(report, rj, art), stdin=COACH_STDIN), td, root)
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        report, rj, art = coaching_dir(root)
        bad = "<!-- COACHING_INSERTION_POINT_00000000 -->"
        out["blocked_before_parity"] = result(run(coaching_argv(report, rj, art, bad), stdin=COACH_STDIN), td, root)
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        report, rj, art = coaching_dir(root)
        empty = json.dumps({"commentary_markdown": ""})
        out["blocked_after_parity"] = result(run(coaching_argv(report, rj, art), stdin=empty), td, root)
    return out


# --- per-gate answer writers and founder_context init --------------------------------------

GATE_RUN = "20261007T090000Z-5e7f91"
STAGE_BODY = {
    "gate_id": "stage_confirmation",
    "question": "Does this stage detection look right?",
    "options": ["Looks right", "Different stage", "Not sure — proceed anyway"],
    "context_summary": "Detected stage: Seed",
}


def gate_state_scenarios() -> dict[str, dict[str, Any]]:
    script = str(SKILLS / "deck-review" / "scripts" / "gate_state.py")
    out: dict[str, dict[str, Any]] = {}
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        gate = root / "gate_state.json"
        emit = ["emit", "--run-id", GATE_RUN, "--stage", "seed", "-o", str(gate)]
        out["emit"] = result(run([script, *emit], stdin=json.dumps(STAGE_BODY)), td, root)
        ans = ["answer", "--file", str(gate), "--answer", "Looks right", "--source", "founder"]
        out["answer_founder"] = result(run([script, *ans]), td, root)
        out["answer_same_again"] = result(run([script, *ans]), td, root)
        other = ["answer", "--file", str(gate), "--answer", "Different stage", "--source", "founder"]
        out["answer_refused"] = result(run([script, *other]), td, root)
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        gate = root / "gate_state.json"
        run([script, "emit", "--run-id", GATE_RUN, "--stage", "seed", "-o", str(gate)], stdin=json.dumps(STAGE_BODY))
        auto = ["answer", "--file", str(gate), "--answer", "Looks right", "--source", "auto_satisfied"]
        out["answer_auto"] = result(run([script, *auto]), td, root)
    return out


REDTEAM = {
    "metadata": {"run_id": GATE_RUN},
    "findings": [
        {
            "claim_attacked": "The share of employers the sizing uses",
            "parameter": "segment_pct",
            "what_is_true": "The published share is lower than the analysis uses.",
            "severity": "high",
        }
    ],
    "rejected": [],
}


def revision_scenarios() -> dict[str, dict[str, Any]]:
    script = str(SKILLS / "market-sizing" / "scripts" / "record_revision_answer.py")
    out: dict[str, dict[str, Any]] = {}
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "redteam.json").write_text(json.dumps(REDTEAM))
        (root / "handoff" / GATE_RUN).mkdir(parents=True)
        out["deliver_founder"] = result(
            run([script, "--dir", str(root), "--answer", "deliver", "--source", "founder"]), td, root
        )
        out["revise_no_questions"] = result(
            run([script, "--dir", str(root), "--answer", "revise", "--source", "no_questions"]), td, root
        )
        out["refused_answer"] = result(
            run([script, "--dir", str(root), "--answer", "maybe", "--source", "founder"]), td, root
        )
    return out


CT_INPUTS = {
    "company_name": "Example Co",
    "analysis_date": "2026-06-19",
    "mode": "standard",
    "metadata": {"run_id": GATE_RUN, "schema_version": "v0.5.0-inputs"},
}
CT_NOTE_BLOCKS = {
    "blocks": [
        {
            "block_type": "notes_block",
            "sheet": "N",
            "cell_range": "A2:B2",
            "column_role_map": {"A": "investor_name", "B": "principal"},
        }
    ]
}


def ct_workbook(root: Path) -> Path:
    from openpyxl import Workbook  # type: ignore[import-untyped]

    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "N"
    ws.append(["Investor", "Principal"])
    ws.append(["Lender", 250000])
    path = root / "n.xlsx"
    wb.save(path)
    return path


def freeform_scenarios() -> dict[str, dict[str, Any]]:
    script = str(SKILLS / "cap-table" / "scripts" / "extract_cap_table.py")
    out: dict[str, dict[str, Any]] = {}
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        xlsx = ct_workbook(root)
        (root / "inputs.json").write_text(json.dumps(CT_INPUTS))
        base = [script, "--mode=freeform-emit", "--xlsx", str(xlsx), "--dir", str(root), "--run-id", GATE_RUN]
        blocks = json.dumps(CT_NOTE_BLOCKS)
        out["blocked"] = result(run(base, stdin=blocks), td, root)
        answered = [*base, "--answer", "0.interest_rate_type=fixed_numeric_simple"]
        out["answered"] = result(run(answered, stdin=blocks), td, root)
    return out


def freeform_flat_scenarios() -> dict[str, dict[str, Any]]:
    """The same freeform runs from a copy of the skill with no plugin-root `scripts/` beside it."""
    import shutil

    out: dict[str, dict[str, Any]] = {}
    with tempfile.TemporaryDirectory() as flat_td:
        dest = Path(flat_td) / "skills" / "cap-table"
        shutil.copytree(SKILLS / "cap-table", dest, ignore=shutil.ignore_patterns("__pycache__"))
        script = str(dest / "scripts" / "extract_cap_table.py")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            xlsx = ct_workbook(root)
            (root / "inputs.json").write_text(json.dumps(CT_INPUTS))
            base = [script, "--mode=freeform-emit", "--xlsx", str(xlsx), "--dir", str(root), "--run-id", GATE_RUN]
            blocks = json.dumps(CT_NOTE_BLOCKS)
            out["blocked"] = result(run(base, stdin=blocks), td, root)
            answered = [*base, "--answer", "0.interest_rate_type=fixed_numeric_simple"]
            out["answered"] = result(run(answered, stdin=blocks), td, root)
    return out


def apply_corrections_scenarios() -> dict[str, dict[str, Any]]:
    script = str(SKILLS / "financial-model-review" / "scripts" / "apply_corrections.py")
    original = (FIXTURES / "financial-model-review" / "inputs.json").read_text(encoding="utf-8")
    out: dict[str, dict[str, Any]] = {}
    calls = {
        "chat_without_run_id": ["--set", "cash.current_balance=250000"],
        "chat_with_run_id": ["--set", "cash.current_balance=250000", "--run-id", GATE_RUN, "--origin", "chat"],
        "refused_origin": ["--set", "cash.current_balance=250000", "--run-id", GATE_RUN, "--origin", "bogus"],
    }
    for name, extra in calls.items():
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "inputs.json").write_text(original, encoding="utf-8")
            argv = [script, *extra, "--original", str(root / "inputs.json"), "--output-dir", str(root / "out")]
            out[name] = result(run(argv), td, root)
    return out


def founder_context_scenarios() -> dict[str, dict[str, Any]]:
    script = str(SHARED / "founder_context.py")
    out: dict[str, dict[str, Any]] = {}
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        argv = [
            script,
            "init",
            "--company-name",
            "Example Co",
            "--stage",
            "seed",
            "--sector",
            "fintech",
            "--geography",
            "US",
            "--artifacts-root",
            str(root),
            "--run-id",
            GATE_RUN,
        ]
        out["init_with_run_id"] = result(run(argv), td, root)
    return out


def _context_init(root: Path, name: str, slug: str) -> None:
    run(
        [
            str(SHARED / "founder_context.py"),
            "init",
            "--company-name",
            name,
            "--slug",
            slug,
            "--stage",
            "seed",
            "--sector",
            "fintech",
            "--geography",
            "US",
            "--artifacts-root",
            str(root),
            "--run-id",
            GATE_RUN,
        ]
    )


def founder_context_read_scenarios() -> dict[str, dict[str, Any]]:
    """`read` with one context, several (exit 2), none, and a named slug."""
    script = str(SHARED / "founder_context.py")
    out: dict[str, dict[str, Any]] = {}
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        out["none"] = result(run([script, "read", "--artifacts-root", str(root)]), td, root)
        _context_init(root, "Example Co", "example-co")
        out["single"] = result(run([script, "read", "--artifacts-root", str(root), "--pretty"]), td, root)
        _context_init(root, "Sample Labs", "sample-labs")
        out["multiple"] = result(run([script, "read", "--artifacts-root", str(root)]), td, root)
        named = [script, "read", "--artifacts-root", str(root), "--slug", "sample-labs"]
        out["named"] = result(run(named), td, root)
        missing = [script, "read", "--artifacts-root", str(root), "--slug", "nobody"]
        out["named_missing"] = result(run(missing), td, root)
    return out


def _dr_gate(path: Path, run_id: str, gate_id: str, stage: str, answer: str | None, source: str | None) -> None:
    """A gate file as `gate_state.py` writes one, written by hand so the scenario needs no ledger."""
    options = {
        "stage_confirmation": ["Looks right", "Different stage", "Not sure — proceed anyway"],
        "out_of_scope_choice": ["Stop review", "Different stage", "Proceed anyway (best-effort)"],
    }[gate_id]
    body: dict[str, Any] = {
        "metadata": {"run_id": run_id},
        "gate_id": gate_id,
        "question": "Does this stage detection look right?",
        "options": options,
        "context_summary": "Detected stage from the deck",
        "confirmed_stage": stage,
    }
    if answer is not None:
        body["answer"] = answer
    if source is not None:
        body["answer_source"] = source
    path.write_text(json.dumps(body, indent=2), encoding="utf-8")


def setup_run_scenarios() -> dict[str, dict[str, Any]]:
    """`setup_run.py`: a fresh run cleans a prior run's files; a same-run answer keeps them."""
    script = str(SKILLS / "deck-review" / "scripts" / "setup_run.py")
    gate_script = str(SKILLS / "deck-review" / "scripts" / "gate_state.py")
    out: dict[str, dict[str, Any]] = {}
    base = ["--slug", "example-co", "--run-id", GATE_RUN, "--clean"]

    def review_dir(root: Path) -> Path:
        d = root / "deck-review-example-co"
        d.mkdir(parents=True, exist_ok=True)
        (d / "deck_inventory.json").write_text(json.dumps({"metadata": {"run_id": "20261001T000000Z-prior1"}}))
        (d / "stage_profile.json").write_text(json.dumps({"metadata": {"run_id": "20261001T000000Z-prior1"}}))
        (d / "notes.txt").write_text("kept: not a pipeline artifact\n")
        return d

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        d = review_dir(root)
        _dr_gate(
            d / "gate_state.json", "20261001T000000Z-prior1", "stage_confirmation", "seed", "Looks right", "founder"
        )
        out["fresh_clean"] = result(run([script, "--artifacts-root", str(root), *base, "--pretty"]), td, root)
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        d = review_dir(root)
        gate = d / "gate_state.json"
        run(
            [gate_script, "emit", "--run-id", GATE_RUN, "--stage", "seed", "-o", str(gate)],
            stdin=json.dumps(STAGE_BODY),
        )
        out["unanswered_same_run"] = result(run([script, "--artifacts-root", str(root), *base]), td, root)
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        d = review_dir(root)
        gate = d / "gate_state.json"
        run(
            [gate_script, "emit", "--run-id", GATE_RUN, "--stage", "seed", "-o", str(gate)],
            stdin=json.dumps(STAGE_BODY),
        )
        run([gate_script, "answer", "--file", str(gate), "--answer", "Looks right", "--source", "founder"])
        out["gate_round_trip"] = result(run([script, "--artifacts-root", str(root), *base]), td, root)
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        d = review_dir(root)
        _dr_gate(d / "gate_state.json", GATE_RUN, "out_of_scope_choice", "growth", "Stop review", "founder")
        out["declined_same_run"] = result(run([script, "--artifacts-root", str(root), *base]), td, root)
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        d = review_dir(root)
        _dr_gate(d / "gate_state.json", GATE_RUN, "stage_confirmation", "seed", "Looks right", None)
        out["unauditable_same_run"] = result(run([script, "--artifacts-root", str(root), *base]), td, root)
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        d = review_dir(root)
        (d / "gate_state.json").write_text("{not json")
        out["unreadable_gate"] = result(run([script, "--artifacts-root", str(root), *base]), td, root)
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        empty = ["--artifacts-root", str(root), "--slug", "example-co", "--run-id", "", "--clean"]
        out["empty_run_id"] = result(run([script, *empty]), td, root)
    return out


DR_FIXTURE_RUN = "fixture-deck-review-001"


def dr_compose_scenarios() -> dict[str, dict[str, Any]]:
    """deck-review's compose over the fixture artifacts, through each kind of gate it reads."""
    import shutil

    script = str(SKILLS / "deck-review" / "scripts" / "compose_report.py")
    cases: dict[str, tuple[str, str, str | None, str | None] | None] = {
        "authorised": ("stage_confirmation", "seed", "Looks right", "founder"),
        "auto_satisfied": ("stage_confirmation", "seed", "Looks right", "auto_satisfied"),
        "unanswered": ("stage_confirmation", "seed", None, None),
        "intermediate": ("stage_confirmation", "seed", "Different stage", "founder"),
        "declined": ("out_of_scope_choice", "growth", "Stop review", "founder"),
        "ungated": None,
    }
    out: dict[str, dict[str, Any]] = {}
    for name, case in cases.items():
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for f in (FIXTURES / "deck-review").iterdir():
                if f.is_file():
                    shutil.copy(f, root / f.name)
            argv = [script, "--dir", str(root), "-o", str(root / "report.json"), "--write-md", str(root / "report.md")]
            if case is None:
                argv.append("--ungated")
            else:
                gate_id, stage, answer, source = case
                _dr_gate(root / "gate_state.json", DR_FIXTURE_RUN, gate_id, stage, answer, source)
                argv += ["--gate-state", str(root / "gate_state.json")]
            proc = run(argv)
            res = result(proc, td, root)
            # The receipt's byte count is the report's, and the report names its own directory, so the
            # count varies with the temp path's length: it is the one field taken out of the hash.
            res["stdout"] = _sha(re.sub(r'"bytes": ?\d+', '"bytes":<N>', normalise(proc.stdout, td)))
            out[name] = res
    return out


FMR_SCRIPTS = SKILLS / "financial-model-review" / "scripts"
FMR_TODAY = "2026-10-07"


def _fmr_inputs(*, cash: bool = True) -> str:
    data = json.loads((FIXTURES / "financial-model-review" / "inputs.json").read_text(encoding="utf-8"))
    if not cash:
        data["cash"].pop("current_balance", None)
        data["cash"].pop("balance_date", None)
    return json.dumps(data)


def fmr_producer_scenarios() -> dict[str, dict[str, Any]]:
    """unit_economics.py and runway.py, as Step 4 and the quick check call them, in a dir with no run ref."""
    out: dict[str, dict[str, Any]] = {}
    for script in ("unit_economics.py", "runway.py"):
        for name, extra, cash in (
            ("stdout", [], True),
            ("to_file", ["-o", "{dir}/out.json"], True),
            ("to_file_run_id", ["--run-id", GATE_RUN, "-o", "{dir}/out.json"], True),
            ("no_cash_run_id", ["--run-id", GATE_RUN, "-o", "{dir}/out.json"], False),
        ):
            with tempfile.TemporaryDirectory() as td:
                root = Path(td)
                argv = [str(FMR_SCRIPTS / script), "--pretty", *[a.replace("{dir}", td) for a in extra]]
                out[f"{script}/{name}"] = result(run(argv, stdin=_fmr_inputs(cash=cash)), td, root)
    return out


def _fmr_review_dir(root: Path, *, cash: bool = True) -> None:
    import shutil

    for f in (FIXTURES / "financial-model-review").iterdir():
        if f.is_file():
            shutil.copy(f, root / f.name)
    if not cash:
        (root / "inputs.json").write_text(_fmr_inputs(cash=False), encoding="utf-8")
        proc = run([str(FMR_SCRIPTS / "runway.py"), "-o", str(root / "runway.json")], stdin=_fmr_inputs(cash=False))
        assert proc.returncode == 0, proc.stderr


def _fmr_compose(root: Path) -> subprocess.CompletedProcess[str]:
    return run(
        [
            str(FMR_SCRIPTS / "compose_report.py"),
            "--dir",
            str(root),
            "--today",
            FMR_TODAY,
            "-o",
            str(root / "report.json"),
            "--write-md",
            str(root / "report.md"),
        ]
    )


def fmr_compose_scenarios() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for name, cash in (("full", True), ("no_cash", False)):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _fmr_review_dir(root, cash=cash)
            proc = _fmr_compose(root)
            res = result(proc, td, root)
            # The receipt's byte count varies with the temp path's length (the report names its dir).
            res["stdout"] = _sha(re.sub(r'"bytes": ?\d+', '"bytes":<N>', normalise(proc.stdout, td)))
            out[name] = res
    return out


def fmr_verify_scenarios() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for gate in ("1", "2"):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _fmr_review_dir(root)
            _fmr_compose(root)
            proc = run([str(FMR_SCRIPTS / "verify_review.py"), "--dir", str(root), "--gate", gate])
            out[f"gate_{gate}"] = result(proc, td, root)
    return out


def fmr_closer_scenarios() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for name, cash, extra in (("plain", True, []), ("cash_update", True, ["--cash-update"]), ("no_cash", False, [])):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _fmr_review_dir(root, cash=cash)
            _fmr_compose(root)
            argv = [
                str(FMR_SCRIPTS / "fmr_closing_message.py"),
                "--report",
                str(root / "report.json"),
                "--link",
                "path",
            ]
            argv += ["--deliverable", f"the written report={root}/report.md", *extra]
            out[name] = result(run(argv), td, root)
    return out


GROUPS: dict[str, Callable[[], dict[str, dict[str, Any]]]] = {
    "html": lambda: {f"{s}/{w}": html_scenario(s, w) for s, w, _k in HTML_WRITERS},
    "insert_coaching": coaching_scenarios,
    "gate_state": gate_state_scenarios,
    "record_revision_answer": revision_scenarios,
    "extract_cap_table": freeform_scenarios,
    "founder_context": founder_context_scenarios,
    "html_stdout": lambda: {"market-sizing/visualize.py": html_stdout_scenario("market-sizing", "visualize.py")},
    "extract_cap_table_flat": freeform_flat_scenarios,
    "apply_corrections": apply_corrections_scenarios,
    "founder_context_read": founder_context_read_scenarios,
    "setup_run": setup_run_scenarios,
    "deck_review_compose": dr_compose_scenarios,
    "fmr_producers": fmr_producer_scenarios,
    "fmr_compose": fmr_compose_scenarios,
    "fmr_verify": fmr_verify_scenarios,
    "fmr_closer": fmr_closer_scenarios,
}


def capture() -> dict[str, dict[str, dict[str, Any]]]:
    return {name: fn() for name, fn in GROUPS.items()}


def load() -> dict[str, dict[str, dict[str, Any]]]:
    data: dict[str, dict[str, dict[str, Any]]] = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    return data


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--write", action="store_true", help="overwrite the committed goldens")
    a = p.parse_args()
    data = capture()
    text = json.dumps(data, indent=2, sort_keys=True) + "\n"
    if a.write:
        GOLDEN_PATH.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
