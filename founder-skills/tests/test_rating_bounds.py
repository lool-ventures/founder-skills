#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""A higher-is-better metric must be able to say "that is not a real number."

`unit_economics.py` rates several metrics on a "higher is better" scale via
`_rate_higher_is_better()`. That scale has no natural stopping point: anything
above `strong` rates `strong`, so a decimal-point or units error (500% NRR, an
800% gross margin) reads as an excellent result instead of a red flag --
exactly where a mis-scaled input is most likely to hide. `_IMPLAUSIBLE_ABOVE`
+ `_implausibility_note()` close that gap for the metrics they cover. This
test makes sure every metric actually rated via `_rate_higher_is_better()` is
covered -- either by a declared ceiling, or by a reason named in this file's
own `EXEMPT_HIGHER_IS_BETTER` -- so a newly-covered metric can't silently
inherit unbounded behaviour.

Run: pytest founder-skills/tests/test_rating_bounds.py -v
"""

from __future__ import annotations

import copy
import importlib.util
import json
import os
import subprocess
import sys
from typing import Any

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
FMR_SCRIPTS_DIR = os.path.join(os.path.dirname(SCRIPT_DIR), "skills", "financial-model-review", "scripts")


def _load_unit_economics_module() -> Any:
    path = os.path.join(FMR_SCRIPTS_DIR, "unit_economics.py")
    spec = importlib.util.spec_from_file_location("fmr_unit_economics_module_ratingbounds", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["fmr_unit_economics_module_ratingbounds"] = mod
    spec.loader.exec_module(mod)
    return mod


def run_script(
    name: str, args: list[str] | None = None, stdin_data: str | None = None
) -> tuple[int, dict[str, Any], str]:
    """Run a financial-model-review script and return (exit_code, parsed_json, stderr)."""
    cmd = [sys.executable, os.path.join(FMR_SCRIPTS_DIR, name)]
    if args:
        cmd.extend(args)
    result = subprocess.run(cmd, input=stdin_data, capture_output=True, text=True)
    try:
        data = json.loads(result.stdout) if result.stdout.strip() else {}
    except json.JSONDecodeError:
        data = {}
    return result.returncode, data, result.stderr


# ---------------------------------------------------------------------------
# The metrics actually rated via _rate_higher_is_better(). Derived by reading
# every `_rate_higher_is_better(` call site in unit_economics.py
# (`grep -n '_rate_higher_is_better(' unit_economics.py`) and following each
# one back to the `_metric(...)` call that names it -- NOT lifted from
# _IMPLAUSIBLE_ABOVE itself, which would make the coverage check below
# vacuous by construction. Re-derive this list the same way if
# unit_economics.py grows a new call site; this test cannot discover one on
# its own.
# ---------------------------------------------------------------------------
HIGHER_IS_BETTER_METRICS: tuple[str, ...] = (
    "ltv_cac_ratio",
    "magic_number",
    "gross_margin",
    "nrr",
    "grr",
    "rule_of_40",
)

# Metrics judged to have NO achievable ceiling -- a very high value is
# genuinely possible for that metric, not a units/sign error. Keep this empty
# unless a metric earns a real, stated reason. Do NOT add an entry just to
# make the coverage test below pass -- that silently undoes the point of it.
EXEMPT_HIGHER_IS_BETTER: dict[str, str] = {
    "rule_of_40": (
        "No achievable ceiling. Rule of 40 sums annualized growth and margin, and the growth "
        "term is unbounded for a small revenue base -- 20%/month compounds to ~791% annualized, "
        "so a score in the hundreds is a real early-stage outcome rather than a mis-scaled input. "
        "A ceiling here would fire on exactly the companies the metric is meant to reward."
    ),
}


def test_every_higher_is_better_metric_has_a_ceiling_or_a_named_exemption() -> None:
    """Every metric rated via _rate_higher_is_better() must be covered by
    unit_economics._IMPLAUSIBLE_ABOVE or by this file's EXEMPT_HIGHER_IS_BETTER.
    Silence -- neither list mentioning the metric -- must not be the default,
    because silence is exactly what lets an absurd value read as a strength.
    """
    mod = _load_unit_economics_module()
    uncovered = [
        metric_id
        for metric_id in HIGHER_IS_BETTER_METRICS
        if metric_id not in mod._IMPLAUSIBLE_ABOVE and metric_id not in EXEMPT_HIGHER_IS_BETTER
    ]
    assert not uncovered, (
        "these metrics are rated on a higher-is-better scale -- an absurd value rates "
        "'strong' with nothing else checking it -- but have neither an implausibility "
        "ceiling in unit_economics._IMPLAUSIBLE_ABOVE nor a named exemption in this "
        f"test's EXEMPT_HIGHER_IS_BETTER: {uncovered}. A newly-covered metric must force "
        "a decision: add a ceiling to _IMPLAUSIBLE_ABOVE, or name the exemption here and "
        "say why no ceiling is achievable."
    )


def test_named_exemptions_carry_a_real_reason() -> None:
    """An exemption has to be a stated justification, not a bare name. Currently
    vacuous (EXEMPT_HIGHER_IS_BETTER is empty) -- this guards whatever gets added
    there in the future."""
    for metric_id, reason in EXEMPT_HIGHER_IS_BETTER.items():
        assert isinstance(reason, str) and len(reason.strip()) >= 15, (
            f"{metric_id!r}: exemption reason is missing or too thin to be a real justification: {reason!r}"
        )


def test_ceiling_flags_a_value_above_it_and_clears_a_value_below() -> None:
    """For every declared ceiling, a value comfortably above it must produce an
    implausibility note, and a value comfortably below it must not."""
    mod = _load_unit_economics_module()
    assert mod._IMPLAUSIBLE_ABOVE, "no ceilings declared in _IMPLAUSIBLE_ABOVE -- nothing for this test to check"
    for metric_id, ceiling in mod._IMPLAUSIBLE_ABOVE.items():
        above = ceiling * 1.5 if ceiling > 0 else ceiling + 1.0
        below = ceiling * 0.5
        note_above = mod._implausibility_note(metric_id, above, pct=False)
        note_below = mod._implausibility_note(metric_id, below, pct=False)
        assert note_above is not None, (
            f"{metric_id!r}: {above} is above its declared ceiling ({ceiling}) but produced no note"
        )
        assert note_below is None, (
            f"{metric_id!r}: {below} is below its declared ceiling ({ceiling}) but was flagged: {note_below!r}"
        )


def test_implausible_nrr_is_not_rated_strong_through_the_full_cli() -> None:
    """Wiring check for the whole path, not just _implausibility_note() in isolation:
    an implausible NRR fed through the real unit_economics.py CLI must not come out
    rated 'strong'."""
    inputs = {
        "company": {
            "company_name": "TestCo",
            "stage": "seed",
            "sector": "B2B SaaS",
            "revenue_model_type": "saas-sales-led",
        },
        "revenue": {"nrr": 5.0},  # 500% net retention -- reads as a units/decimal error
    }
    rc, data, stderr = run_script("unit_economics.py", ["--pretty"], stdin_data=json.dumps(inputs))
    assert rc == 0, stderr
    nrr_metric = next(m for m in data["metrics"] if m["id"] == "nrr")
    assert nrr_metric["rating"] not in ("strong", "acceptable", "warning", "fail"), (
        f"a 500% NRR was graded {nrr_metric['rating']!r} instead of withheld: {nrr_metric}"
    )
    assert nrr_metric["rating"] == "not_rated"
    assert "units or sign error" in nrr_metric["evidence"] or "not a real figure" in nrr_metric["evidence"].lower()


def test_plausible_nrr_still_grades_normally_through_the_full_cli() -> None:
    """Companion to the implausible-NRR check: the ceiling must not swallow a real,
    in-range value -- a healthy 110% NRR should grade normally, not fall to
    not_rated."""
    inputs = copy.deepcopy(
        {
            "company": {
                "company_name": "TestCo",
                "stage": "seed",
                "sector": "B2B SaaS",
                "revenue_model_type": "saas-sales-led",
            },
            "revenue": {"nrr": 1.10},
        }
    )
    rc, data, stderr = run_script("unit_economics.py", ["--pretty"], stdin_data=json.dumps(inputs))
    assert rc == 0, stderr
    nrr_metric = next(m for m in data["metrics"] if m["id"] == "nrr")
    assert nrr_metric["rating"] in ("strong", "acceptable", "warning", "fail")


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
