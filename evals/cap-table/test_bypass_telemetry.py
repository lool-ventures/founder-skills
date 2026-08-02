"""Unit tests for bypass_telemetry.py — the pipeline-bypass detector.

Synthetic fixtures only (no real company artifacts — privacy rule). Mirrors the
cowork-harness run-dir layout: <run>/<slug>/<session>/work/session/mnt/outputs/.
"""

from __future__ import annotations

import json
from pathlib import Path

import bypass_telemetry as bt


def _make_run(
    root: Path,
    *,
    canonical: list[str] | None = None,
    adhoc: list[str] | None = None,
    model: str | None = "claude-sonnet-4-6",
    slug: str = "cap-table-testco",
    session: str = "sess-x",
    make_outputs: bool = True,
) -> Path:
    """Build a fake harness run dir. `canonical` artifacts land in
    outputs/artifacts/<slug>/; `adhoc` files land directly in outputs/."""
    run = root
    base = run / "skill-founder-skills" / session / "work" / "session" / "mnt"
    if make_outputs:
        outputs = base / "outputs"
        outputs.mkdir(parents=True, exist_ok=True)
        if canonical:
            adir = outputs / "artifacts" / slug
            adir.mkdir(parents=True, exist_ok=True)
            for name in canonical:
                p = adir / name
                p.write_text("{}" if name.endswith(".json") else "# stub\n")
        for name in adhoc or []:
            (outputs / name).write_text("# hand-rolled\n")
    # events.jsonl carrying the model id
    sess_dir = run / "skill-founder-skills" / session
    sess_dir.mkdir(parents=True, exist_ok=True)
    if model:
        (sess_dir / "events.jsonl").write_text(json.dumps({"type": "assistant", "message": {"model": model}}) + "\n")
    return run


CANONICAL_FULL = [
    "inputs.json",
    "instruments.json",
    "cap_state.json",
    "scenarios.json",
    "rule_audit.json",
    "counsel_packet.json",
    "report.json",
    "report.md",
]


def test_classify_pipeline_ran(tmp_path):
    run = _make_run(tmp_path / "r", canonical=CANONICAL_FULL)
    res = bt.classify_run(str(run))
    assert res["classification"] == "pipeline_ran"
    assert res["model"] == "claude-sonnet-4-6"
    assert not res["canonical_missing"]


def test_classify_bypassed(tmp_path):
    # empty artifacts dir + an ad-hoc hand-rolled markdown in outputs/
    run = _make_run(tmp_path / "r", canonical=[], adhoc=["TestCo_Analysis.md"], model="claude-opus-4-8")
    res = bt.classify_run(str(run))
    assert res["classification"] == "bypassed"
    assert res["model"] == "claude-opus-4-8"
    assert "TestCo_Analysis.md" in res["adhoc_outputs"]


def test_classify_flip_variant_counts_as_ran(tmp_path):
    # flip runs emit flip_scenario.json instead of (or with) scenarios.json
    flip_set = ["inputs.json", "cap_state.json", "flip_scenario.json", "rule_audit.json", "report.json"]
    run = _make_run(tmp_path / "r", canonical=flip_set)
    res = bt.classify_run(str(run))
    assert res["classification"] == "pipeline_ran"


def test_classify_partial(tmp_path):
    run = _make_run(tmp_path / "r", canonical=["inputs.json", "cap_state.json"])
    res = bt.classify_run(str(run))
    assert res["classification"] == "partial"
    assert "report.json" in res["canonical_missing"]


def test_classify_no_output(tmp_path):
    run = _make_run(tmp_path / "r", canonical=[], adhoc=[])
    res = bt.classify_run(str(run))
    assert res["classification"] == "no_output"


def test_aggregate_bypass_rate_by_model(tmp_path):
    runs = [
        _make_run(tmp_path / "a", canonical=CANONICAL_FULL, model="claude-sonnet-4-6"),
        _make_run(tmp_path / "b", canonical=CANONICAL_FULL, model="claude-sonnet-4-6"),
        _make_run(tmp_path / "c", canonical=CANONICAL_FULL, model="claude-opus-4-8"),
        _make_run(tmp_path / "d", canonical=[], adhoc=["x.md"], model="claude-opus-4-8"),
    ]
    classifications = [bt.classify_run(str(r)) for r in runs]
    agg = bt.aggregate(classifications)
    son = agg["by_model"]["claude-sonnet-4-6"]
    opus = agg["by_model"]["claude-opus-4-8"]
    assert son["total"] == 2 and son["bypassed"] == 0 and son["bypass_rate"] == 0.0
    assert opus["total"] == 2 and opus["bypassed"] == 1 and opus["bypass_rate"] == 0.5
    # no_output / error are excluded from the bypass-rate denominator
    assert "bypass_rate" in agg["overall"]
