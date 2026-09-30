"""Sensitivity and checklist can be graded against the sizing they were produced from.

Before this, sensitivity.py's `base` values came from the sub-agent's hand-off on stdin — a THIRD
copy of every input that nothing compared against `sizing.json` — and neither sensitivity.py nor
checklist.py recorded which sizing they were run against. That let a sensitivity table silently
disagree with the sizing the founder sees, and let a self-check pass against an earlier sizing.

`--sizing PATH` on both producers closes this: a v1-stamped `sizing.json` (as `market_sizing.py`'s
references path writes it) becomes the source of truth for base values (sensitivity.py) and the
thing `graded_against` records (both). See the two scripts' module docstrings and CLAUDE.md's
"Market Sizing Scripts" entries for the shape of `input_provenance`.

These tests run the real scripts via subprocess, the same way test_market_sizing_provenance.py
does; the small helpers below are copied from it rather than imported (skill scripts and their
tests are standalone).
"""

from __future__ import annotations

import importlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

_SCRIPTS = Path(__file__).resolve().parent.parent / "skills" / "market-sizing" / "scripts"
sys.path.insert(0, str(_SCRIPTS))
_provenance = importlib.import_module("_provenance")


# --- copied helpers (see test_market_sizing_provenance.py) --------------------------------------

_SRC = {"title": "Government survey 2025", "url": "https://example.gov/survey"}


def _record(*entries: dict[str, Any], sources: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {"assumptions": list(entries), "sources": sources or []}


def _sourced(name: str, value: float, unit: str, **extra: Any) -> dict[str, Any]:
    return {
        "name": name,
        "value": value,
        "unit": unit,
        "category": "sourced",
        "source_title": _SRC["title"],
        "source_url": _SRC["url"],
        **extra,
    }


def _write(tmp_path: Path, name: str, doc: dict[str, Any]) -> Path:
    p = tmp_path / name
    p.write_text(json.dumps(doc))
    return p


# --- local helpers --------------------------------------------------------------------------------


def _build_sizing(tmp_path: Path, *, arpu_founder_stated: bool = False) -> tuple[Path, dict[str, Any]]:
    """Run market_sizing.py on the references path to produce a real v1-stamped sizing.json.

    bottom_up approach: customer_count ("accounts") and target_pct ("target_pct_rec") are sourced
    assumptions; serviceable_pct is an `estimate` (kind="estimate", category="agent_estimate" —
    the stamped-agent_estimate case tests (b) needs); arpu is a sourced assumption ("price") unless
    ``arpu_founder_stated``, in which case it is `{"founder_stated": "arpu"}` (the founder_stated
    case test (c) needs) sourced from inputs.json's founder_stated_inputs.
    """
    record = _record(
        _sourced("accounts", 12_000, "count"),
        _sourced("price", 500, "money_per_customer", currency="USD", period="year"),
        _sourced("target_pct_rec", 10, "percent_points"),
        sources=[_SRC],
    )
    v = _write(tmp_path, "validation.json", record)
    inputs: dict[str, Any] = {"currency": "USD"}
    if arpu_founder_stated:
        inputs["founder_stated_inputs"] = {"arpu": 500}
        inputs["founder_stated_inputs_period"] = {"arpu": "year"}
    i = _write(tmp_path, "inputs.json", inputs)
    refs: dict[str, Any] = {
        "approach": "bottom_up",
        "customer_count": {"assumption": "accounts"},
        "arpu": {"founder_stated": "arpu"} if arpu_founder_stated else {"assumption": "price"},
        "serviceable_pct": {"estimate": 40, "unit": "percent_points", "why": "rough guess, no research done"},
        "target_pct": {"assumption": "target_pct_rec"},
    }
    out = tmp_path / "sizing.json"
    proc = subprocess.run(
        [
            sys.executable,
            str(_SCRIPTS / "market_sizing.py"),
            "--stdin",
            "--validation",
            str(v),
            "--inputs",
            str(i),
            "-o",
            str(out),
        ],
        input=json.dumps(refs),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    sizing: dict[str, Any] = json.loads(out.read_text())
    return out, sizing


def _run_sensitivity(stdin: dict[str, Any], *extra: str) -> tuple[int, str, str]:
    proc = subprocess.run(
        [sys.executable, str(_SCRIPTS / "sensitivity.py"), *extra],
        input=json.dumps(stdin),
        capture_output=True,
        text=True,
    )
    return proc.returncode, proc.stdout, proc.stderr


_CHECKLIST_IDS = [
    "structural_tam_gt_sam_gt_som",
    "structural_definitions_correct",
    "tam_matches_product_scope",
    "source_segments_match",
    "som_share_defensible",
    "som_backed_by_gtm",
    "som_consistent_with_projections",
    "data_current",
    "sources_reputable",
    "figures_triangulated",
    "unsupported_figures_flagged",
    "validated_used_precisely",
    "assumptions_categorized",
    "both_approaches_used",
    "approaches_reconciled",
    "growth_dynamics_considered",
    "market_properly_segmented",
    "competitive_landscape_acknowledged",
    "sam_expansion_path_noted",
    "assumptions_explicit",
    "formulas_shown",
    "sources_cited",
]


def _checklist_stdin() -> dict[str, Any]:
    return {"items": [{"id": i, "status": "not_applicable"} for i in _CHECKLIST_IDS]}


def _run_checklist(stdin: dict[str, Any], *extra: str) -> tuple[int, str, str]:
    proc = subprocess.run(
        [sys.executable, str(_SCRIPTS / "checklist.py"), *extra],
        input=json.dumps(stdin),
        capture_output=True,
        text=True,
    )
    return proc.returncode, proc.stdout, proc.stderr


_FULL_BASE = {"customer_count": 100.0, "arpu": 10.0, "serviceable_pct": 10.0, "target_pct": 10.0}


# --- (a) a disagreeing hand-off base is ignored, not rejected ------------------------------------


def test_a_disagreeing_hand_off_base_is_ignored_in_favour_of_the_sizing(tmp_path: Path) -> None:
    sizing_path, sizing = _build_sizing(tmp_path)
    prov = sizing["input_provenance"]
    stdin = {
        "approach": "bottom_up",
        # Only customer_count is given, and it disagrees with the sizing's 12,000 — the other
        # three params are entirely absent from 'base', which --sizing must tolerate.
        "base": {"customer_count": 1},
        "ranges": {"customer_count": {"low_pct": -10, "high_pct": 10, "confidence": "sourced"}},
    }
    rc, stdout, stderr = _run_sensitivity(stdin, "--sizing", str(sizing_path))
    assert rc == 0, stdout + stderr
    result = json.loads(stdout)

    assert result["base_source"] == "sizing"
    assert result["base_ignored"] == {"customer_count": 1.0}

    cc_scenario = next(s for s in result["scenarios"] if s["parameter"] == "customer_count")
    assert cc_scenario["base_value"] == prov["customer_count"]["value_consumed"]
    assert cc_scenario["base_value"] != 1

    expected_tam = prov["customer_count"]["value_consumed"] * prov["arpu"]["value_consumed"]
    assert result["base_result"]["tam"] == pytest.approx(expected_tam)
    assert cc_scenario["base"]["tam"] == pytest.approx(expected_tam)
    # The low/high scenario numbers are also computed off the sizing's value, not the hand-off's 1.
    assert cc_scenario["low"]["value"] == pytest.approx(prov["customer_count"]["value_consumed"] * 0.9)


# --- (b) a stamped agent_estimate input whose range claims "sourced" is widened ------------------


def test_a_stamped_agent_estimate_input_declared_sourced_is_widened(tmp_path: Path) -> None:
    sizing_path, sizing = _build_sizing(tmp_path)
    assert sizing["input_provenance"]["serviceable_pct"]["category"] == "agent_estimate"
    assert sizing["input_provenance"]["serviceable_pct"]["kind"] == "estimate"

    stdin = {
        "approach": "bottom_up",
        "base": {},
        "ranges": {"serviceable_pct": {"low_pct": -5, "high_pct": 5, "confidence": "sourced"}},
    }
    rc, stdout, stderr = _run_sensitivity(stdin, "--sizing", str(sizing_path))
    assert rc == 0, stdout + stderr
    result = json.loads(stdout)

    scenario = result["scenarios"][0]
    assert scenario["parameter"] == "serviceable_pct"
    assert scenario["confidence"] == "agent_estimate"
    assert scenario["confidence_source"] == "reconciled"
    assert scenario["range_widened"] is True
    assert scenario["effective_range"] == {"low_pct": -50, "high_pct": 50}


# --- (c) founder_stated maps to the sourced tier --------------------------------------------------


def test_founder_stated_maps_to_the_sourced_tier(tmp_path: Path) -> None:
    sizing_path, sizing = _build_sizing(tmp_path, arpu_founder_stated=True)
    assert sizing["input_provenance"]["arpu"]["kind"] == "founder_stated"

    stdin = {
        "approach": "bottom_up",
        "base": {},
        # No explicit confidence: the range is cross-referenced against the merged
        # validation_confidence map, which is exactly what exercises the founder_stated mapping.
        "ranges": {"arpu": {"low_pct": -5, "high_pct": 5}},
    }
    rc, stdout, stderr = _run_sensitivity(stdin, "--sizing", str(sizing_path))
    assert rc == 0, stdout + stderr
    result = json.loads(stdout)

    scenario = result["scenarios"][0]
    assert scenario["parameter"] == "arpu"
    assert scenario["confidence"] == "sourced"
    assert scenario["confidence_source"] == "validation"
    # "sourced" widens nothing, so a tight 5% range is left alone.
    assert scenario["range_widened"] is False
    assert scenario["effective_range"] == {"low_pct": -5.0, "high_pct": 5.0}


# --- (d) graded_against equals the sizing's fingerprint, for both producers ----------------------


def test_graded_against_equals_the_sizing_fingerprint_for_both_producers(tmp_path: Path) -> None:
    sizing_path, sizing = _build_sizing(tmp_path)
    expected_fp = _provenance.sizing_fingerprint(sizing)
    assert expected_fp is not None

    sens_stdin = {
        "approach": "bottom_up",
        "base": {},
        "ranges": {"customer_count": {"low_pct": -10, "high_pct": 10, "confidence": "sourced"}},
    }
    rc, stdout, stderr = _run_sensitivity(sens_stdin, "--sizing", str(sizing_path))
    assert rc == 0, stdout + stderr
    sens_result = json.loads(stdout)
    assert sens_result["graded_against"] == {"sizing.json": expected_fp}

    rc, stdout, stderr = _run_checklist(_checklist_stdin(), "--sizing", str(sizing_path))
    assert rc == 0, stdout + stderr
    checklist_result = json.loads(stdout)
    assert checklist_result["graded_against"] == {"sizing.json": expected_fp}

    # A second, real sizing fingerprints differently — graded_against isn't a constant.
    sizing_path2, sizing2 = _build_sizing(tmp_path, arpu_founder_stated=True)
    fp2 = _provenance.sizing_fingerprint(sizing2)
    assert fp2 != expected_fp
    rc, stdout, stderr = _run_checklist(_checklist_stdin(), "--sizing", str(sizing_path2))
    assert rc == 0, stdout + stderr
    assert json.loads(stdout)["graded_against"] == {"sizing.json": fp2}


# --- (e) a legacy (unstamped) sizing fails loudly, for both producers ----------------------------


def _legacy_sizing(tmp_path: Path) -> Path:
    # No provenance_version / input_provenance at all — what a sizing.json looked like before
    # this feature existed.
    return _write(
        tmp_path,
        "legacy_sizing.json",
        {
            "approach": "bottom-up",
            "bottom_up": {"tam": {"value": 6_000_000}},
            "validation": {"status": "valid", "errors": []},
        },
    )


def test_a_legacy_unstamped_sizing_fails_loudly_sensitivity(tmp_path: Path) -> None:
    legacy = _legacy_sizing(tmp_path)
    out = tmp_path / "sens_out.json"
    out.write_text("SENTINEL-SENS")
    stdin = {
        "approach": "bottom_up",
        "base": _FULL_BASE,
        "ranges": {"customer_count": {"low_pct": -10, "high_pct": 10, "confidence": "sourced"}},
    }
    rc, stdout, stderr = _run_sensitivity(stdin, "--sizing", str(legacy), "-o", str(out))
    assert rc != 0
    assert stderr.strip() != ""
    assert "E_SIZING_NOT_STAMPED" in stdout
    assert out.read_text() == "SENTINEL-SENS"


def test_a_legacy_unstamped_sizing_fails_loudly_checklist(tmp_path: Path) -> None:
    legacy = _legacy_sizing(tmp_path)
    out = tmp_path / "checklist_out.json"
    out.write_text("SENTINEL-CHECKLIST")
    rc, stdout, stderr = _run_checklist(_checklist_stdin(), "--sizing", str(legacy), "-o", str(out))
    assert rc != 0
    assert stderr.strip() != ""
    assert "E_SIZING_NOT_STAMPED" in stdout
    assert out.read_text() == "SENTINEL-CHECKLIST"


def test_an_unreadable_sizing_path_fails_loudly(tmp_path: Path) -> None:
    missing = tmp_path / "does_not_exist.json"
    stdin = {
        "approach": "bottom_up",
        "base": _FULL_BASE,
        "ranges": {"customer_count": {"low_pct": -10, "high_pct": 10, "confidence": "sourced"}},
    }
    rc, stdout, stderr = _run_sensitivity(stdin, "--sizing", str(missing))
    assert rc != 0
    assert stderr.strip() != ""
    assert "E_SIZING_NOT_STAMPED" in stdout


# --- (f) without --sizing, behaviour (and output shape) is unchanged -----------------------------


def test_without_sizing_output_carries_no_stamp_keys(tmp_path: Path) -> None:
    stdin = {
        "approach": "bottom_up",
        "base": _FULL_BASE,
        "ranges": {"customer_count": {"low_pct": -10, "high_pct": 10, "confidence": "sourced"}},
    }
    rc, stdout, stderr = _run_sensitivity(stdin)
    assert rc == 0, stdout + stderr
    result = json.loads(stdout)
    assert "graded_against" not in result
    assert "base_source" not in result
    assert "base_ignored" not in result

    rc, stdout, stderr = _run_checklist(_checklist_stdin())
    assert rc == 0, stdout + stderr
    assert "graded_against" not in json.loads(stdout)


# --- mutation-targeted: a param the sizing has no value for falls back to the hand-off -----------


def test_a_param_absent_from_the_sizing_keeps_the_hand_off_value(tmp_path: Path) -> None:
    """`--sizing` overrides only the params it actually carries a numeric value_consumed for.

    Guards against a broad implementation that clears every required param's hand-off value
    outright rather than reading it from the sizing per-param.
    """
    sizing_path, sizing = _build_sizing(tmp_path)
    prov = dict(sizing["input_provenance"])
    del prov["target_pct"]
    sizing["input_provenance"] = prov
    stripped = tmp_path / "sizing_no_target_pct.json"
    stripped.write_text(json.dumps(sizing))

    stdin = {
        "approach": "bottom_up",
        "base": {"target_pct": 7},
        "ranges": {"target_pct": {"low_pct": -10, "high_pct": 10, "confidence": "sourced"}},
    }
    rc, stdout, stderr = _run_sensitivity(stdin, "--sizing", str(stripped))
    assert rc == 0, stdout + stderr
    result = json.loads(stdout)
    assert result["base_ignored"] == {}
    scenario = result["scenarios"][0]
    assert scenario["base_value"] == 7.0


def test_the_hand_off_the_skill_now_dispatches_carries_no_base_at_all(tmp_path: Path) -> None:
    """The SENSITIVITY_TEST template asks only for approach and ranges: the base values are the
    sizing's. A hand-off with no `base` key must work with --sizing, or every real run is refused."""
    path, sizing = _build_sizing(tmp_path)
    stdin = {
        "approach": "bottom_up",
        "ranges": {"customer_count": {"low_pct": -30, "high_pct": 20, "confidence": "sourced"}},
    }
    rc, out, err = _run_sensitivity(stdin, "--sizing", str(path))
    assert rc == 0, out + err
    result = json.loads(out)
    assert result["base_source"] == "sizing"
    base = {s["parameter"]: s["base_value"] for s in result["scenarios"]}
    assert base["customer_count"] == sizing["input_provenance"]["customer_count"]["value_consumed"]
    # Without --sizing a hand-off with no base is still refused, as before.
    rc, _, _ = _run_sensitivity(stdin)
    assert rc != 0


# --- (c2) the founder's own figure is always stress-tested ----------------------------------------


def _arpu_scenario(result: dict[str, Any]) -> dict[str, Any] | None:
    return next((s for s in result["scenarios"] if s["parameter"] == "arpu"), None)


def test_a_founder_figure_left_without_a_range_is_varied_anyway(tmp_path: Path) -> None:
    """On two of three live runs the founder's ARPU was never varied: the founder's own figure
    grades as sourced, and a sourced figure may be left out. It was the figure the red team disputed
    on every run. A figure nobody checked against research is varied at least as widely as a derived one."""
    sizing_path, _ = _build_sizing(tmp_path, arpu_founder_stated=True)
    stdin = {"approach": "bottom_up", "base": {}, "ranges": {"serviceable_pct": {"low_pct": -50, "high_pct": 50}}}
    rc, stdout, stderr = _run_sensitivity(stdin, "--sizing", str(sizing_path))
    assert rc == 0, stdout + stderr
    arpu = _arpu_scenario(json.loads(stdout))
    assert arpu is not None
    assert arpu["confidence_source"] == "founder_stated"
    assert arpu["effective_range"] == {"low_pct": -30.0, "high_pct": 30.0}


def test_the_founders_other_figures_set_the_range_when_wider(tmp_path: Path) -> None:
    """The founder's materials stated other figures for the same input; the range spans them."""
    sizing_path, _ = _build_sizing(tmp_path, arpu_founder_stated=True)
    inputs = tmp_path / "inputs_with_alternatives.json"
    inputs.write_text(
        json.dumps(
            {
                "founder_stated_inputs": {"arpu": 500},
                "founder_stated_inputs_period": {"arpu": "year"},
                "founder_stated_alternatives": {
                    "arpu": [{"value": 400, "period": "year"}, {"value": 70, "period": "month"}]
                },
            }
        )
    )
    stdin = {"approach": "bottom_up", "base": {}, "ranges": {"serviceable_pct": {"low_pct": -50, "high_pct": 50}}}
    rc, stdout, stderr = _run_sensitivity(stdin, "--sizing", str(sizing_path), "--inputs", str(inputs))
    assert rc == 0, stdout + stderr
    arpu = _arpu_scenario(json.loads(stdout))
    assert arpu is not None
    # 400/yr is -20% (inside the -30% floor); 70/month is 840/yr, +68%.
    assert arpu["effective_range"] == {"low_pct": -30.0, "high_pct": 68.0}


def test_a_sourced_figure_left_without_a_range_is_not_varied_by_this(tmp_path: Path) -> None:
    """Positive control: the added range is for the founder's own figure only."""
    sizing_path, _ = _build_sizing(tmp_path, arpu_founder_stated=False)
    stdin = {"approach": "bottom_up", "base": {}, "ranges": {"serviceable_pct": {"low_pct": -50, "high_pct": 50}}}
    rc, stdout, stderr = _run_sensitivity(stdin, "--sizing", str(sizing_path))
    assert rc == 0, stdout + stderr
    assert _arpu_scenario(json.loads(stdout)) is None


def test_the_skill_pipes_the_founders_figures_to_the_sensitivity_producer() -> None:
    """Without --inputs the range is the ±30% floor alone and never spans the founder's other figures."""
    skill = (_SCRIPTS.parent / "SKILL.md").read_text(encoding="utf-8")
    call = skill[skill.index('python3 "$SCRIPTS/sensitivity.py"') :]
    call = call[: call.index("\n```")]
    assert '--inputs "$ANALYSIS_DIR/inputs.json"' in call


def test_a_range_named_for_no_parameter_is_refused_not_dropped(tmp_path: Path) -> None:
    """A live hand-off named every range `top_down.industry_total`, `bottom_up.arpu`, … and the producer
    dropped all seven as irrelevant: the table had one row (the founder figure it adds itself) and six
    parameters were reported as never stress-tested. A name that is no approach's parameter is a
    malformed hand-off, refused so the step is redone -- not a parameter for the other approach."""
    sizing_path, _ = _build_sizing(tmp_path)
    stdin = {
        "approach": "bottom_up",
        "base": {},
        "ranges": {"bottom_up.serviceable_pct": {"low_pct": -30, "high_pct": 30, "confidence": "derived"}},
    }
    out = tmp_path / "sensitivity.json"
    out.write_text('{"sentinel": true}')
    rc, stdout, stderr = _run_sensitivity(stdin, "--sizing", str(sizing_path), "-o", str(out))
    assert rc != 0
    assert "bottom_up.serviceable_pct" in stdout and "serviceable_pct" in stdout
    assert json.loads(out.read_text()) == {"sentinel": True}


def test_the_other_approachs_parameter_is_still_ignored_on_a_single_approach_run(tmp_path: Path) -> None:
    """Positive control: a top-down parameter on a bottom-up run stays a warning, as before."""
    sizing_path, _ = _build_sizing(tmp_path)
    stdin = {
        "approach": "bottom_up",
        "base": {},
        "ranges": {
            "serviceable_pct": {"low_pct": -30, "high_pct": 30, "confidence": "derived"},
            "segment_pct": {"low_pct": -30, "high_pct": 30, "confidence": "derived"},
        },
    }
    rc, stdout, stderr = _run_sensitivity(stdin, "--sizing", str(sizing_path))
    assert rc == 0, stdout + stderr
