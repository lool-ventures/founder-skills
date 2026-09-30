"""The gap between the two builds is stated as a factor, from the two figures, on every surface.

The producer measured the gap against the AVERAGE of the two figures ("differ by 146.7%"), which
caps at 200% and cannot be read as growth. On an e2e run the coach read the SAM delta percentage as
growth and told the founder the builds were a small multiple apart when they were an order of
magnitude apart, and made the same mistake on SOM. With the illustrative pair below (top-down
$1.2B, bottom-up $7.8B) that reads "+146.7%", i.e. 2.5x, for a pair 6.5x apart; the SOM pair is
4.6x apart, not 2.3x. A founder reading the same percentage in the hand-over makes the same
mistake. The percentage stays in sizing.json as the >30% trigger; what is shown and handed to the
coach is the factor.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

_TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(_TESTS))
from test_market_sizing import (  # noqa: E402
    _compose_md_text,
    _compose_with_sizing,
    run_script,
)

_SCRIPTS = _TESTS.parent / "skills" / "market-sizing" / "scripts"
_spec = importlib.util.spec_from_file_location("ms_params_gap", _SCRIPTS / "_params.py")
assert _spec is not None and _spec.loader is not None
_params = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_params)

# Top-down SAM $1.05B vs bottom-up SAM $23.6B: an order-of-magnitude gap.
_BOTH = [
    "--approach",
    "both",
    "--industry-total",
    "100000000000",
    "--segment-pct",
    "6",
    "--share-pct",
    "5",
    "--customer-count",
    "4500000",
    "--arpu",
    "15000",
    "--serviceable-pct",
    "35",
    "--target-pct",
    "0.5",
]


def _sizing() -> dict[str, Any]:
    rc, data, err = run_script("market_sizing.py", _BOTH)
    assert rc == 0 and data is not None, err
    return data


def _factor(sizing: dict[str, Any], metric: str) -> str:
    td, bu = sizing["top_down"][metric]["value"], sizing["bottom_up"][metric]["value"]
    return f"a factor of {max(td, bu) / min(td, bu):.1f}"


def test_the_gaps_read_as_the_factors_they_are() -> None:
    assert _params.gap_sentence("sam", 1_200_000_000, 7_800_000_000) == (
        "Top-down and bottom-up SAM differ by a factor of 6.5 (bottom-up is higher)."
    )
    assert "a factor of 4.6" in str(_params.gap_sentence("som", 9_000_000, 41_400_000))
    assert "(top-down is higher)" in str(_params.gap_sentence("tam", 13e9, 3.4e9))


def test_a_gap_with_no_positive_pair_has_no_factor() -> None:
    assert _params.gap_sentence("tam", 0, 5e9) is None
    assert _params.gap_sentence("tam", None, 5e9) is None


def test_builds_within_five_percent_are_not_given_a_factor_of_one() -> None:
    assert _params.gap_sentence("tam", 100, 104) == "Top-down and bottom-up TAM are within 5% of each other."


def test_the_producer_states_a_large_gap_as_a_factor() -> None:
    sizing = _sizing()
    c = sizing["comparison"]
    assert c["sam_delta_pct"] > 30  # still the trigger
    for metric, key in (("tam", "warning"), ("sam", "sam_warning"), ("som", "som_warning")):
        assert _factor(sizing, metric) in c[key], c[key]
        assert f"{c[f'{metric}_delta_pct']}%" not in c[key], c[key]


def test_the_verdict_and_the_warnings_state_the_factor() -> None:
    sizing = _sizing()
    rc, data, d = _compose_with_sizing(sizing)
    assert rc == 0 and data is not None
    md = _compose_md_text(Path(d))
    head = md[md.index("## Executive Summary") : md.index("| Metric | Value | Method |")]
    sam = _factor(sizing, "sam")
    assert f"{sam} on SAM" in head, head
    assert f"{sizing['comparison']['sam_delta_pct']}%" not in head, head
    msg = next(w["message"] for w in data["validation"]["warnings"] if w["code"] == "SAM_DISCREPANCY")
    assert sam in msg, msg


def test_the_coach_is_handed_the_factor_and_no_percentage_to_misread() -> None:
    sizing = _sizing()
    rc, data, _d = _compose_with_sizing(sizing)
    assert rc == 0 and data is not None
    ac = data["coaching_payload"]["approach_comparison"]
    assert _factor(sizing, "sam") in ac["sam_gap"], ac
    assert not any(k.endswith("_delta_pct") for k in ac), ac
