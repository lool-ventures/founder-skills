"""Drift guard for the reliability bench's computation-case canonical numbers.

The bench's ``computation_cases[*].canonical_values`` are derived from the
deterministic producers by ``evals/cap-table/build_canonicals.py`` rather than hand-typed.
This test, for each case carrying a ``canonical_values`` block:

1. Re-runs the same producer recipe (importing build_canonicals.py so recipe
   logic is never duplicated) and asserts the freshly-derived numbers match the
   recorded values within tolerance — this catches a solver/rule-pack change
   silently moving a canonical.
2. Asserts the recorded values also match the KNOWN-CORRECT targets, so a wrong
   recipe can never lock in a wrong number.

For the circular-MFN case it asserts the producer fails loudly (emits the
E_SAFE_CIRCULAR_MFN blocker and no conversion price) rather than returning a
price. The recipes run the real producers; they are fast and deterministic.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
EVALS_DIR = REPO_ROOT / "evals" / "cap-table"
BUILD_CANONICALS = EVALS_DIR / "build_canonicals.py"
BENCH_PATH = EVALS_DIR / "reliability-bench.json"

# Tolerances: prices/fractions to 1e-3 absolute; share counts within 1 share.
PRICE_TOL = 1e-3
SHARE_TOL = 1

# Known-correct targets (independent of the recipe) — a wrong recipe can't lock
# in a wrong number because both the recorded value AND the freshly-derived value
# are checked against these.
KNOWN_TARGETS: dict[str, dict[str, object]] = {
    "comp_discount_only_iterative": {
        "equity_financing_price": 0.875,
        "safe_conversion_price": 0.70,
        "safe_conversion_shares": 1428571,
        "founders_pct": 0.625,
        "safe_pct": 0.0893,
        "new_money_pct": 0.2857,
    },
    "comp_stacked_safes": {
        "total_given_away": 0.2354,
        "founders_retained": 0.7646,
    },
    "comp_pool_shuffle": {
        "price_per_share": 1.75,
        "pool_shares": 1428571,
    },
    "comp_bbwa_downround": {"cp2": 1.786},
    "comp_full_ratchet": {"cp2": 1.00},
    "comp_mfn_circular": {
        "raises_circular": True,
        "has_conversion_price": False,
    },
}

# Keys that are share counts (compare with ±1); everything else numeric uses PRICE_TOL.
SHARE_KEYS = {"safe_conversion_shares", "pool_shares"}


def _load_build_canonicals() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("cap_build_canonicals", BUILD_CANONICALS)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["cap_build_canonicals"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def derived() -> dict[str, dict[str, object]]:
    mod = _load_build_canonicals()
    return mod.derive_canonicals()  # type: ignore[no-any-return]


@pytest.fixture(scope="module")
def bench_cases() -> dict[str, dict[str, object]]:
    bench = json.loads(BENCH_PATH.read_text(encoding="utf-8"))
    return {c["id"]: c for c in bench["computation_cases"]}


def _assert_close(key: str, actual: object, expected: object) -> None:
    """Numeric keys compared with tolerance; non-numeric compared for equality."""
    if isinstance(expected, bool) or isinstance(actual, bool):
        assert actual == expected, f"{key}: {actual!r} != {expected!r}"
        return
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        tol = SHARE_TOL if key in SHARE_KEYS else PRICE_TOL
        assert abs(float(actual) - float(expected)) <= tol, f"{key}: {actual} not within {tol} of {expected}"
        return
    assert actual == expected, f"{key}: {actual!r} != {expected!r}"


def test_every_computation_case_has_canonical_values(bench_cases):
    """All six computation cases must carry a derived canonical_values block."""
    missing = [cid for cid in KNOWN_TARGETS if "canonical_values" not in bench_cases.get(cid, {})]
    assert not missing, f"cases missing canonical_values: {missing}"


@pytest.mark.parametrize("case_id", sorted(KNOWN_TARGETS))
def test_recorded_matches_known_target(case_id, bench_cases):
    """The recorded canonical_values must match the known-correct targets.

    Guards against a wrong recipe locking in a wrong number.
    """
    recorded = bench_cases[case_id]["canonical_values"]
    for key, target in KNOWN_TARGETS[case_id].items():
        _assert_close(key, recorded[key], target)


@pytest.mark.parametrize("case_id", sorted(KNOWN_TARGETS))
def test_fresh_derivation_matches_recorded(case_id, derived, bench_cases):
    """Re-deriving from the producers must reproduce the recorded values.

    This is the drift guard: a solver/rule-pack change that moves a canonical
    fails here.
    """
    fresh = derived[case_id]
    recorded = bench_cases[case_id]["canonical_values"]
    # Every recorded numeric/boolean leaf must be reproduced by a fresh run.
    for key, recorded_val in recorded.items():
        assert key in fresh, f"{case_id}: fresh derivation missing key {key!r}"
        fresh_val = fresh[key]
        if isinstance(recorded_val, dict):
            for sub_key, sub_val in recorded_val.items():
                _assert_close(f"{key}.{sub_key}", fresh_val[sub_key], sub_val)
        else:
            _assert_close(key, fresh_val, recorded_val)


def test_mfn_circular_fails_loud(derived):
    """The circular-MFN producer must block, not return a conversion price."""
    out = derived["comp_mfn_circular"]
    assert out["raises_circular"] is True
    assert out["blocker_code"] == "E_SAFE_CIRCULAR_MFN"
    assert out["has_conversion_price"] is False
