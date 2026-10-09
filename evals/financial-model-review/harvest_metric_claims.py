#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Harvest checklist sentences that name a ratio metric into the free replay corpus.

The financial model review warns (METRIC_SELF_CONTRADICTION) when a checklist sentence states a figure
for burn multiple, LTV/CAC, magic number or CAC payback that disagrees with the computed one. This keeps
the sentences real review runs wrote, with the computed figures they were checked against, in
`metric_claim_corpus.json`, and `founder-skills/tests/test_fmr_metric_claim_corpus.py` replays them
through the shipped check on every free test run.

Only runs of the tracked synthetic fixtures are admitted (see `gate`): the run's own `model_data.json`
(what the review extracted from the file it was given) must equal what `extract_model.py` extracts from
one of SYNTHETIC_FIXTURES today. A fixture copied beside a run of another model does not pass, and the
run id, the company name and the folder name are never read. Every other run is refused, and the reason
is printed.

    # dry run (the default): what would be added, and what the shipped check fires on the result
    python evals/financial-model-review/harvest_metric_claims.py --from-dir <kept run dir>
    python evals/financial-model-review/harvest_metric_claims.py --last 5      # CI artifacts, via gh
    python evals/financial-model-review/harvest_metric_claims.py --run <id> --write

`--write` writes the merged corpus to a temporary file, runs the privacy guard's commit-time layers over
it, and moves it into place only when they pass; on a finding the corpus is left as it was. Those layers
include figure-provenance: a harvested sentence that puts a figure beside a real-data phrase ("the
founder's stated burn of $120,000") is refused there, deliberately, as a prompt to read it. The marker
the guard accepts is line-scoped and cannot be added to a JSON evidence line, so such a row is dropped
or its evidence edited. It never edits `expected`: a person reads the replay and edits that list by hand.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
CORPUS_PATH = HERE / "metric_claim_corpus.json"
COMPOSE_PATH = REPO_ROOT / "founder-skills" / "skills" / "financial-model-review" / "scripts" / "compose_report.py"
GUARD_PATH = REPO_ROOT / "scripts" / "privacy_guard.py"

# The tracked synthetic fixtures a review run may have been given: the e2e lane's csv and the recorded
# Cowork session's workbook (founder-skills/tests/fixtures/sample_model.xlsx is byte-identical to it).
SYNTHETIC_FIXTURES = (
    "founder-skills/tests/fixtures/models/synthetic-seed-model.csv",
    "cowork-tests/fixtures/sample_model.xlsx",
)
EXTRACT_MODEL = REPO_ROOT / "founder-skills" / "skills" / "financial-model-review" / "scripts" / "extract_model.py"
CI_ARTIFACT = "e2e-review-workspaces"
_MESSAGE_RE = re.compile(r"^(\w+) is computed as .*? checklist criterion '(.*)' states ([-\d.,]+) for the same metric")
ABOUT = (
    "Checklist sentences naming a ratio metric, from review runs of tracked synthetic fixtures, with the "
    "computed figures they were checked against. Written by harvest_metric_claims.py; `expected` is "
    "edited by hand."
)


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclasses resolve their module through sys.modules
    spec.loader.exec_module(module)
    return module


def load_compose() -> Any:
    """The shipped compose script, so the dry run and the test run the same check."""
    return _load(COMPOSE_PATH, "fmr_compose_for_corpus")


def canonical_sheets(model_data: Any) -> str | None:
    """`model_data.json`'s `sheets`, as one comparable string; None when there are none."""
    sheets = model_data.get("sheets") if isinstance(model_data, dict) else None
    if not isinstance(sheets, list) or not sheets:
        return None
    return json.dumps(sheets, sort_keys=True, ensure_ascii=False)


def fixture_sheets() -> dict[str, str]:
    """{canonical sheets: tracked path}: `extract_model.py` run today over each tracked synthetic fixture."""
    out: dict[str, str] = {}
    for rel in SYNTHETIC_FIXTURES:
        tracked = subprocess.run(
            ["git", "ls-files", "--error-unmatch", rel], cwd=REPO_ROOT, capture_output=True, text=True
        )
        if tracked.returncode != 0:
            continue
        extracted = subprocess.run(
            [sys.executable, str(EXTRACT_MODEL), "--file", str(REPO_ROOT / rel)],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        key = canonical_sheets(json.loads(extracted))
        if key is not None:
            out[key] = rel
    return out


def _json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _run_id(doc: Any) -> str | None:
    meta = doc.get("metadata") if isinstance(doc, dict) else None
    rid = meta.get("run_id") if isinstance(meta, dict) else None
    return rid if isinstance(rid, str) else None


def _company(review_dir: Path) -> str | None:
    inputs = _json(review_dir / "inputs.json")
    company = inputs.get("company") if isinstance(inputs, dict) else None
    name = company.get("company_name") if isinstance(company, dict) else None
    return name if isinstance(name, str) else None


def gate(review_dir: Path, fixtures: dict[str, str]) -> tuple[str | None, str]:
    """(the tracked fixture the run reviewed, reason), or (None, why it is refused).

    Admitted only when the run's own extraction equals a tracked synthetic fixture's: that binds what
    the review graded to the fixture, where a file beside the run proves only that a fixture was there.
    """
    checklist_id = _run_id(_json(review_dir / "checklist.json"))
    ue_id = _run_id(_json(review_dir / "unit_economics.json"))
    if checklist_id is None or checklist_id != ue_id:
        return None, f"checklist and unit_economics are not from one run ({checklist_id} / {ue_id})"
    model_data = _json(review_dir / "model_data.json")
    if model_data is None:
        return None, "no readable model_data.json"
    sheets = canonical_sheets(model_data)
    tracked = fixtures.get(sheets) if sheets is not None else None
    if tracked is None:
        return None, "model_data.json sheets equal no tracked synthetic fixture's extraction"
    return tracked, f"model_data.json sheets equal the extraction of {tracked}"


def review_dirs(root: Path) -> list[Path]:
    out = []
    for dirpath, _dirnames, filenames in os.walk(root):
        if ".local-plugins" in dirpath:
            continue
        if "checklist.json" in filenames and "unit_economics.json" in filenames:
            out.append(Path(dirpath))
    return sorted(out)


def evidence_texts(checklist: Any) -> list[tuple[str, str]]:
    """(criterion, evidence) at any nesting, walked as the check walks it."""
    texts: list[tuple[str, str]] = []

    def walk(node: Any, label: str) -> None:
        if isinstance(node, dict):
            evidence = node.get("evidence")
            if isinstance(evidence, str) and evidence.strip():
                criterion = node.get("id") or node.get("criterion") or node.get("name") or label
                texts.append((str(criterion), evidence))
            for key, child in node.items():
                if key != "evidence":
                    walk(child, label)
        elif isinstance(node, list):
            for child in node:
                walk(child, label)

    walk(checklist, "checklist")
    return texts


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "run"


def extract(review_dir: Path, compose: Any, origin: str) -> tuple[dict[str, Any], list[dict[str, str]]] | None:
    """({key: run}, rows) for one admitted review dir, or None when it computed no ratio metric."""
    labels: dict[str, tuple[str, ...]] = compose._RATIO_METRIC_LABELS
    ue = _json(review_dir / "unit_economics.json")
    metrics = []
    for metric in ue.get("metrics", []) if isinstance(ue, dict) else []:
        name = metric.get("id") or metric.get("name") if isinstance(metric, dict) else None
        if name in labels:
            metrics.append(
                {
                    "id": name,
                    "value": metric.get("value"),
                    "benchmark": metric.get("benchmark"),
                    "benchmark_reference": metric.get("benchmark_reference"),
                }
            )
    if not metrics:
        return None
    metrics.sort(key=lambda m: m["id"])
    digest = hashlib.sha256(json.dumps(metrics, sort_keys=True).encode()).hexdigest()[:8]
    key = f"{_slug(_company(review_dir) or 'run')}-{digest}"
    words = [w for group in labels.values() for w in group] + ["payback"]
    rows = []
    for criterion, evidence in evidence_texts(_json(review_dir / "checklist.json")):
        lowered = evidence.lower()
        if any(w in lowered for w in words):
            rows.append({"run": key, "criterion": criterion, "evidence": evidence})
    run = {"origins": [origin], "input": "", "metrics": metrics}
    return {key: run}, rows


def merge(corpus: dict[str, Any], runs: dict[str, Any], rows: list[dict[str, str]]) -> tuple[dict[str, Any], int]:
    """The corpus with `runs` and `rows` added; rows dedup on (run, criterion, evidence). Pure."""
    out = {
        "about": corpus.get("about", ABOUT),
        "runs": {k: dict(v, origins=list(v.get("origins", []))) for k, v in corpus.get("runs", {}).items()},
        "rows": [dict(r) for r in corpus.get("rows", [])],
        "expected": [dict(e) for e in corpus.get("expected", [])],
    }
    for key, run in runs.items():
        have = out["runs"].get(key)
        if have is None:
            out["runs"][key] = dict(run, origins=list(run.get("origins", [])))
        else:
            have["origins"] += [o for o in run.get("origins", []) if o not in have["origins"]]
            have["input"] = have.get("input") or run.get("input", "")
    seen = {(r["run"], r["criterion"], r["evidence"]) for r in out["rows"]}
    added = 0
    for row in rows:
        k = (row["run"], row["criterion"], row["evidence"])
        if k not in seen:
            seen.add(k)
            out["rows"].append(dict(row))
            added += 1
    return out, added


def replay(corpus: dict[str, Any], compose: Any) -> list[dict[str, Any]]:
    """What the shipped check flags, per run: [{run, criterion, metric, claim}], claim rounded to 3."""
    flagged: list[dict[str, Any]] = []
    for key, run in corpus.get("runs", {}).items():
        unit_economics = {"metrics": [dict(m, name=m["id"]) for m in run["metrics"]]}
        items = [{"id": r["criterion"], "evidence": r["evidence"]} for r in corpus.get("rows", []) if r["run"] == key]
        for warning in compose._check_metric_self_contradiction(unit_economics, {"items": items}):
            match = _MESSAGE_RE.match(warning["message"])
            if match is None:
                raise ValueError(f"unexpected warning shape: {warning['message']!r}")
            claim = round(float(match.group(3).replace(",", "")), 3)
            flagged.append({"run": key, "criterion": match.group(2), "metric": match.group(1), "claim": claim})
    return flagged


def _ci_run_ids(last: int) -> list[str]:
    out = subprocess.run(
        ["gh", "api", f"repos/{{owner}}/{{repo}}/actions/artifacts?name={CI_ARTIFACT}&per_page=100"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    ids: list[str] = []
    for artifact in json.loads(out).get("artifacts", []):
        rid = str((artifact.get("workflow_run") or {}).get("id", ""))
        if rid and not artifact.get("expired") and rid not in ids:
            ids.append(rid)
    return ids[:last]


def _download(run_id: str, into: Path) -> Path:
    dest = into / f"ci_{run_id}"
    subprocess.run(["gh", "run", "download", run_id, "-n", CI_ARTIFACT, "-D", str(dest)], cwd=REPO_ROOT, check=True)
    return dest


def _origin_for(source: Path) -> str:
    m = re.fullmatch(r"ci_(\d+)", source.name)
    return f"ci run {m.group(1)}" if m else "local kept run"


def privacy_check(path: Path, as_path: Path = CORPUS_PATH) -> int:
    """The guard's commit-time layers (names, figures, verbatim, provenance) over the whole of `path`,
    judged as the file it will become (`as_path`, which decides the synthetic-corpus treatment)."""
    guard = _load(GUARD_PATH, "privacy_guard_for_corpus")
    os.chdir(REPO_ROOT)
    rel = str(as_path.relative_to(REPO_ROOT))
    spec = guard.load_sources(guard.DEFAULT_SOURCES_FILE)
    idx = (
        None
        if spec is None
        else guard.build_private_index(spec, None, guard.DEFAULT_CACHE_DIR, guard.DEFAULT_ALLOWLIST_FILE)
    )
    if idx is None:
        print("privacy guard: no local private-sources file; figure and verbatim layers not run", file=sys.stderr)
    lines = list(enumerate(path.read_text(encoding="utf-8").splitlines(), 1))
    findings = guard.scan_added({rel: lines}, idx, guard.load_names(guard.DEFAULT_NAMES_FILE))
    return int(guard._report(findings, set()))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--from-dir", action="append", default=[], help="kept run dir (repeatable)")
    ap.add_argument("--run", action="append", default=[], help="CI run id whose review workspaces to download")
    ap.add_argument("--last", type=int, default=0, help="the N most recent CI runs with review workspaces")
    ap.add_argument("--write", action="store_true", help="append to the corpus (default: dry run)")
    args = ap.parse_args(argv)
    if not (args.from_dir or args.run or args.last):
        ap.error("give --from-dir, --run or --last")

    compose = load_compose()
    fixtures = fixture_sheets()
    if len(fixtures) != len(SYNTHETIC_FIXTURES):
        print("refusing to harvest: a synthetic fixture is untracked or extracts to nothing", file=sys.stderr)
        return 2
    corpus = _json(CORPUS_PATH) or {"about": ABOUT, "runs": {}, "rows": [], "expected": []}
    before = replay(corpus, compose)
    sources = [Path(d) for d in args.from_dir]
    with tempfile.TemporaryDirectory() as tmp:
        for rid in list(args.run) + (_ci_run_ids(args.last) if args.last else []):
            sources.append(_download(rid, Path(tmp)))
        runs: dict[str, Any] = {}
        rows: list[dict[str, str]] = []
        for source in sources:
            for review_dir in review_dirs(source):
                fixture, reason = gate(review_dir, fixtures)
                print(f"{'ACCEPT' if fixture else 'refuse'}  {review_dir}  -- {reason}")
                if fixture is None:
                    continue
                got = extract(review_dir, compose, _origin_for(source))
                if got is None:
                    continue
                new_runs, new_rows = got
                for key, run in new_runs.items():
                    run["input"] = Path(fixture).name
                    runs.setdefault(key, run)
                    if _origin_for(source) not in runs[key]["origins"]:
                        runs[key]["origins"].append(_origin_for(source))
                rows.extend(new_rows)
    merged, added = merge(corpus, runs, rows)
    print(
        f"\nruns {len(corpus.get('runs', {}))} -> {len(merged['runs'])}; rows {len(corpus.get('rows', []))} -> "
        f"{len(merged['rows'])} (+{added})"
    )
    after = replay(merged, compose)
    print(f"shipped check flags {len(before)} before, {len(after)} after:")
    for f in after:
        print(f"  {f['run']} {f['criterion']} {f['metric']} {f['claim']}{'' if f in before else '  (new)'}")
    if merged["expected"] != after:
        print("NOTE: `expected` differs from what the check flags; read the rows and edit `expected` by hand.")
    if not args.write:
        print("dry run: nothing written (pass --write)")
        return 0
    fd, staged = tempfile.mkstemp(prefix=".metric_claim_corpus.", suffix=".json", dir=HERE)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(merged, indent=1, ensure_ascii=False) + "\n")
    try:
        if privacy_check(Path(staged)) != 0:
            print("privacy guard refused the new corpus; nothing written", file=sys.stderr)
            return 1
        os.chmod(staged, 0o644)  # mkstemp creates 0600
        os.replace(staged, CORPUS_PATH)
    finally:
        if os.path.exists(staged):
            os.unlink(staged)
    print(f"wrote {CORPUS_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
