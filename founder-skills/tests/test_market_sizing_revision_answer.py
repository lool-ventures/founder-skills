"""Step 6d's revise-or-deliver question, made mechanical.

A review whose accepted findings include a `high` one naming a `parameter` must be followed by the
question "deliver with the challenges shown, or revise and have it reviewed once more". A live run skipped
it silently and delivered. The answer is now recorded by `record_revision_answer.py` into the run's
hand-off dir, and compose discloses REVISION_NOT_OFFERED when a qualifying finding exists and no answer
for this run's findings was recorded. A second review round proves "revise" by construction.

RESIDUAL, pinned here so nobody reads more into a green: the record is written by a script the model
runs. It proves the question step ran the recorder, not that the question was put to the founder.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_market_sizing import (  # noqa: E402
    _VALID_CHECKLIST,
    _VALID_INPUTS,
    _VALID_METHODOLOGY,
    _VALID_SENSITIVITY,
    _VALID_SIZING,
    _VALID_VALIDATION,
    MARKET_SIZING_DIR,
)

RUN_ID = "20260929T120000Z"
CODE = "REVISION_NOT_OFFERED"

_HIGH_ON_PARAMETER = {
    "claim_attacked": "The employer share the sizing uses",
    "parameter": "segment_pct",
    "what_is_true": "The published share is 6.1%, not the 10% the analysis uses.",
    "evidence_quote": "Six point one percent of employers offered the benefit in 2025.",
    "source_url": "https://example.org/benefits-2025",
    "source_title": "Benefits Survey 2025",
    "severity": "high",
}


def _redteam(*findings: dict[str, Any]) -> dict[str, Any]:
    by = {"high": 0, "medium": 0, "low": 0}
    for f in findings:
        by[str(f.get("severity"))] += 1
    return {
        "metadata": {"run_id": RUN_ID},
        "findings": list(findings),
        "rejected": [],
        "could_not_check": [],
        "summary": {"accepted": len(findings), "rejected": 0, "unchecked": 0, "by_severity": by},
        "validation": {"status": "valid", "errors": []},
    }


def _dir(redteam: dict[str, Any] | None, *, handoff: bool = True) -> str:
    d = tempfile.mkdtemp(prefix="test-revision-")
    # With a review present, no skip is recorded; with none, compose refuses to run unless one is.
    methodology = {k: v for k, v in _VALID_METHODOLOGY.items() if k != "red_team_skipped" or redteam is None}
    arts: dict[str, Any] = {
        "inputs.json": _VALID_INPUTS,
        "methodology.json": methodology,
        "validation.json": _VALID_VALIDATION,
        "sizing.json": _VALID_SIZING,
        "checklist.json": _VALID_CHECKLIST,
        "sensitivity.json": _VALID_SENSITIVITY,
    }
    if redteam is not None:
        arts["redteam.json"] = redteam
    for name, data in arts.items():
        data = copy.deepcopy(data)
        data["metadata"] = {"run_id": RUN_ID}
        with open(os.path.join(d, name), "w", encoding="utf-8") as f:
            json.dump(data, f)
    if handoff:
        os.makedirs(os.path.join(d, "handoff", RUN_ID), exist_ok=True)
    return d


def _run(name: str, args: list[str]) -> tuple[int, dict[str, Any] | None, str]:
    r = subprocess.run([sys.executable, os.path.join(MARKET_SIZING_DIR, name), *args], capture_output=True, text=True)
    try:
        out = json.loads(r.stdout) if r.stdout.strip() else None
    except json.JSONDecodeError:
        out = None
    return r.returncode, out, r.stderr


def _codes(d: str) -> list[dict[str, Any]]:
    rc, data, err = _run("compose_report.py", ["--dir", d])
    assert rc == 0 and data is not None, err
    return [w for w in data["validation"]["warnings"] if w["code"] == CODE]


def _record(d: str, *extra: str) -> tuple[int, dict[str, Any] | None, str]:
    return _run("record_revision_answer.py", ["--dir", d, *extra])


def test_a_high_finding_on_a_parameter_with_no_recorded_answer_is_disclosed() -> None:
    d = _dir(_redteam(_HIGH_ON_PARAMETER))
    hits = _codes(d)
    assert len(hits) == 1, hits
    assert hits[0]["severity"] == "medium"
    msg = hits[0]["message"]
    assert "segment_pct" not in msg and "_" not in msg, msg  # founder-facing
    assert "revis" in msg.lower(), msg


def test_a_recorded_answer_clears_it_on_either_path() -> None:
    for extra in (("--answer", "deliver", "--source", "founder"), ("--answer", "deliver", "--source", "no_questions")):
        d = _dir(_redteam(_HIGH_ON_PARAMETER))
        rc, receipt, err = _record(d, *extra)
        assert rc == 0, err
        assert receipt is not None and receipt["parameters"] == ["segment_pct"], receipt
        assert os.path.isfile(os.path.join(d, "handoff", RUN_ID, "revision_answer.json"))
        assert _codes(d) == [], extra


def test_nothing_qualifies_so_nothing_is_disclosed() -> None:
    medium = {**_HIGH_ON_PARAMETER, "severity": "medium"}
    high_no_parameter = {k: v for k, v in _HIGH_ON_PARAMETER.items() if k != "parameter"}
    for rt in (_redteam(), _redteam(medium), _redteam(high_no_parameter), None):
        assert _codes(_dir(rt)) == [], rt


def test_a_second_review_round_is_the_answer_revise() -> None:
    """The round count comes from the review copies compose keeps (`_redteam_copy`), not from a directory;
    driven through the function compose calls with that count."""
    # By path, under its own name: every skill has a `compose_report`, and a plain import in a full-suite
    # process returns whichever one another test loaded first.
    sys.path.insert(0, MARKET_SIZING_DIR)
    try:
        spec = importlib.util.spec_from_file_location(
            "ms_compose_revision_answer", os.path.join(MARKET_SIZING_DIR, "compose_report.py")
        )
        assert spec is not None and spec.loader is not None
        compose_report = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(compose_report)
    finally:
        sys.path.pop(0)
    d = _dir(_redteam(_HIGH_ON_PARAMETER))
    assert compose_report._revision_not_offered(d, RUN_ID, _redteam(_HIGH_ON_PARAMETER), rounds=2) == []
    assert compose_report._revision_not_offered(d, RUN_ID, _redteam(_HIGH_ON_PARAMETER), rounds=1) == ["segment_pct"]


def test_a_record_from_another_run_or_other_findings_does_not_clear_it() -> None:
    d = _dir(_redteam(_HIGH_ON_PARAMETER))
    rc, _receipt, err = _record(d, "--answer", "deliver", "--source", "founder")
    assert rc == 0, err
    path = os.path.join(d, "handoff", RUN_ID, "revision_answer.json")
    with open(path, encoding="utf-8") as f:
        good = json.load(f)
    for bad in (
        {**good, "metadata": {"run_id": "20250101T000000Z"}},  # an earlier run of the same slug
        {**good, "parameters": ["arpu"]},  # an answer about a different finding
        {**good, "answer": "maybe"},  # not an answer
    ):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(bad, f)
        assert len(_codes(d)) == 1, bad


def test_accepted_warnings_cannot_clear_it() -> None:
    d = _dir(_redteam(_HIGH_ON_PARAMETER))
    path = os.path.join(d, "methodology.json")
    with open(path, encoding="utf-8") as f:
        m = json.load(f)
    m["accepted_warnings"] = [{"code": CODE, "match": "revis", "reason": "the founder said so"}]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(m, f)
    assert len(_codes(d)) == 1


def test_a_missing_handoff_dir_still_raises_it() -> None:
    """The answer record lives under `handoff/<run_id>/`, so deleting that dir can only ADD this warning.
    It used to read as "not a run" and stay silent."""
    assert [w["code"] for w in _codes(_dir(_redteam(_HIGH_ON_PARAMETER), handoff=False))] == [CODE]


def test_the_recorder_refuses_loudly_and_writes_nothing() -> None:
    cases = {
        "no qualifying finding": (_dir(_redteam({**_HIGH_ON_PARAMETER, "severity": "low"})), ["deliver", "founder"]),
        "no review": (_dir(None), ["deliver", "founder"]),
        "no hand-off dir": (_dir(_redteam(_HIGH_ON_PARAMETER), handoff=False), ["deliver", "founder"]),
        "unknown answer": (_dir(_redteam(_HIGH_ON_PARAMETER)), ["later", "founder"]),
        "unknown source": (_dir(_redteam(_HIGH_ON_PARAMETER)), ["deliver", "someone"]),
    }
    for name, (d, (answer, source)) in cases.items():
        rc, _out, err = _record(d, "--answer", answer, "--source", source)
        assert rc != 0, name
        assert err.strip(), name
        assert not os.path.exists(os.path.join(d, "handoff", RUN_ID, "revision_answer.json")), name
