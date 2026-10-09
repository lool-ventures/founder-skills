"""Replay of recorded checklist sentences through the shipped METRIC_SELF_CONTRADICTION check.

`evals/financial-model-review/metric_claim_corpus.json` holds the sentences naming a ratio metric that
review runs of the tracked synthetic fixtures wrote, with the figures each run computed. The check must
flag exactly the rows in `expected` (today one real disagreement: a burn multiple of roughly 26x
against a computed 2.14) and nothing else. The replay is the harvest script's own `replay`, so its dry
run and this test cannot disagree about a row. Free; no model is called.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
EVALS = REPO_ROOT / "evals" / "financial-model-review"
CORPUS = EVALS / "metric_claim_corpus.json"
# Below this, the corpus has lost most of what it was harvested with; a test over a near-empty corpus
# passes on silence.
MIN_ROWS = 90


def _harvest() -> Any:
    name = "harvest_metric_claims_under_test"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, EVALS / "harvest_metric_claims.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _corpus() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(CORPUS.read_text(encoding="utf-8"))
    return data


def _key(entry: dict[str, Any]) -> tuple[str, str, str, float]:
    return (entry["run"], entry["criterion"], entry["metric"], round(float(entry["claim"]), 3))


def test_the_corpus_flags_exactly_the_expected_rows() -> None:
    corpus = _corpus()
    harvest = _harvest()
    expected = sorted(_key(e) for e in corpus["expected"])
    assert expected, "`expected` must hold the corpus's real disagreement, or this test passes on silence"
    assert len(corpus["rows"]) >= MIN_ROWS
    flagged = sorted(_key(f) for f in harvest.replay(corpus, harvest.load_compose()))
    assert flagged == expected


def test_the_corpus_keeps_the_recorded_year_sentence() -> None:
    """The release-check sentence a year once read as a burn multiple of 2,026 in."""
    rows = [r for r in _corpus()["rows"] if "stops at Jun-2026 actuals" in r["evidence"]]
    assert rows and all(r["criterion"] == "BRIDGE_37" for r in rows)


def test_the_corpus_keeps_a_magic_number_in_the_producers_shape() -> None:
    """The one recorded magic-number sentence, written bare as unit_economics.py writes it."""
    assert any("magic number of 4.06 (strong)" in r["evidence"] for r in _corpus()["rows"])


def test_every_row_names_a_run_the_corpus_holds() -> None:
    corpus = _corpus()
    assert {r["run"] for r in corpus["rows"]} <= set(corpus["runs"])
    fixtures = {Path(p).name for p in _harvest().SYNTHETIC_FIXTURES}
    for run in corpus["runs"].values():
        assert run["metrics"] and run["origins"]
        assert run["input"] in fixtures, "every run must be of a tracked synthetic fixture"


def test_merge_adds_new_rows_once_and_never_touches_expected() -> None:
    harvest = _harvest()
    metrics = [{"id": "burn_multiple", "value": 0.4, "benchmark": None, "benchmark_reference": None}]
    corpus = {
        "about": "x",
        "runs": {"r1": {"origins": ["a"], "input": "m.csv", "metrics": metrics}},
        "rows": [{"run": "r1", "criterion": "C1", "evidence": "burn multiple of 0.4x"}],
        "expected": [{"run": "r1", "criterion": "C1", "metric": "burn_multiple", "claim": 7.0}],
    }
    snapshot = json.loads(json.dumps(corpus))
    new_runs = {
        "r1": {"origins": ["b"], "input": "m.csv", "metrics": metrics},
        "r2": {"origins": ["c"], "input": "m.csv", "metrics": metrics},
    }
    new_rows = [
        {"run": "r1", "criterion": "C1", "evidence": "burn multiple of 0.4x"},  # already held
        {"run": "r1", "criterion": "C2", "evidence": "burn multiple of 0.4x"},  # same text, new criterion
        {"run": "r2", "criterion": "C1", "evidence": "burn multiple of 0.4x"},  # same text, new run
        {"run": "r2", "criterion": "C1", "evidence": "burn multiple of 0.4x"},  # repeated in one batch
    ]
    merged, added = harvest.merge(corpus, new_runs, new_rows)
    assert added == 2
    assert [(r["run"], r["criterion"]) for r in merged["rows"]] == [("r1", "C1"), ("r1", "C2"), ("r2", "C1")]
    assert merged["runs"]["r1"]["origins"] == ["a", "b"]
    assert set(merged["runs"]) == {"r1", "r2"}
    assert merged["expected"] == snapshot["expected"]
    assert corpus == snapshot, "merge must not change its input"
    again, added_again = harvest.merge(merged, new_runs, new_rows)
    assert added_again == 0 and again == merged


# ---- the harvest gate -----------------------------------------------------------------------------

_FIXTURE_SHEETS: list[dict[str, str]] = []


def _fixture_sheets() -> dict[str, str]:
    if not _FIXTURE_SHEETS:
        _FIXTURE_SHEETS.append(_harvest().fixture_sheets())
    return _FIXTURE_SHEETS[0]


def _review_dir(root: Path, model_data: dict[str, Any] | None, run_ids: tuple[str, str] = ("r1", "r1")) -> Path:
    """A run dir as a review leaves it: <workspace>/artifacts/financial-model-review-<slug>/."""
    review = root / "workspace" / "artifacts" / "financial-model-review-foobar-systems"
    review.mkdir(parents=True)
    (review / "checklist.json").write_text(json.dumps({"metadata": {"run_id": run_ids[0]}, "items": []}))
    (review / "unit_economics.json").write_text(json.dumps({"metadata": {"run_id": run_ids[1]}, "metrics": []}))
    (review / "inputs.json").write_text(json.dumps({"company": {"company_name": "Foobar Systems"}}))
    if model_data is not None:
        (review / "model_data.json").write_text(json.dumps(model_data))
    return review


def _csv_model_data() -> dict[str, Any]:
    harvest = _harvest()
    csv_rel = harvest.SYNTHETIC_FIXTURES[0]
    sheets_json = next(k for k, v in _fixture_sheets().items() if v == csv_rel)
    return {"sheets": json.loads(sheets_json), "source_file": Path(csv_rel).name}


def test_the_gate_holds_one_extraction_per_fixture() -> None:
    assert sorted(_fixture_sheets().values()) == sorted(_harvest().SYNTHETIC_FIXTURES)


def test_the_gate_admits_a_run_whose_extraction_is_a_fixtures(tmp_path: Path) -> None:
    fixture, reason = _harvest().gate(_review_dir(tmp_path, _csv_model_data()), _fixture_sheets())
    assert fixture == _harvest().SYNTHETIC_FIXTURES[0], reason


def test_the_gate_refuses_a_fixture_copied_beside_another_models_run(tmp_path: Path) -> None:
    """The fixture file sits in the workspace, but the run reviewed something else."""
    harvest = _harvest()
    other = _csv_model_data()
    other["sheets"][0]["rows"][1][2] = 9001  # one cell of another model
    review = _review_dir(tmp_path, other)
    shutil.copy(REPO_ROOT / harvest.SYNTHETIC_FIXTURES[0], review.parent.parent)
    (review.parent.parent / "uploads").mkdir()
    shutil.copy(REPO_ROOT / harvest.SYNTHETIC_FIXTURES[0], review.parent.parent / "uploads")
    fixture, reason = harvest.gate(review, _fixture_sheets())
    assert fixture is None and "equal no tracked synthetic fixture" in reason


def test_the_gate_refuses_a_run_with_no_model_data(tmp_path: Path) -> None:
    harvest = _harvest()
    review = _review_dir(tmp_path, None)
    shutil.copy(REPO_ROOT / harvest.SYNTHETIC_FIXTURES[0], review.parent.parent)
    fixture, reason = harvest.gate(review, _fixture_sheets())
    assert fixture is None and "model_data.json" in reason


def test_the_gate_refuses_files_from_two_runs(tmp_path: Path) -> None:
    fixture, reason = _harvest().gate(_review_dir(tmp_path, _csv_model_data(), ("r1", "r2")), _fixture_sheets())
    assert fixture is None and "not from one run" in reason
