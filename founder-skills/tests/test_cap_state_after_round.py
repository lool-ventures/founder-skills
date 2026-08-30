"""Tests for cap_state_after_round.py — Sprint 2 derived artifact builder."""

from __future__ import annotations

import importlib.util
import pathlib
from typing import Any

SCRIPT_PATH = pathlib.Path(__file__).parent.parent / "skills" / "cap-table" / "scripts" / "cap_state_after_round.py"
spec = importlib.util.spec_from_file_location("cap_state_after_round", SCRIPT_PATH)
assert spec and spec.loader
csar = importlib.util.module_from_spec(spec)
spec.loader.exec_module(csar)


def _pre_cap_state() -> dict[str, Any]:
    return {
        "founders": [{"name": "Founder A", "common_shares": 10_000_000}],
        "preferred_series": [
            {
                "series_id": "series_seed",
                "shares": 2_000_000,
                "original_issue_price": 1.00,
                "original_conversion_price": 1.00,
                "current_conversion_price": 1.00,
                "anti_dilution_protection": "broad_based_weighted_average",
            }
        ],
        "as_converted_totals": {
            "common_shares": 10_000_000,
            "preferred_shares_as_converted": 2_000_000,
            "options_outstanding": 0,
            "options_available": 1_000_000,
            "fully_diluted_shares": 13_000_000,
        },
        "option_pool": {
            "plan_type": "iso",
            "authorized": 1_000_000,
            "issued_and_outstanding": 0,
            "available_for_grant": 1_000_000,
        },
    }


def test_no_ad_no_changes() -> None:
    """When scenario_output has no ccp_mutations, cap_state is unchanged."""
    pre = _pre_cap_state()
    post = csar.build_cap_state_after_round(
        pre, {"ccp_mutations": {}, "anti_dilution_breakdown": []}, round_id="series_a"
    )
    # Caller's pre-state unchanged (deep-copy boundary)
    assert pre["preferred_series"][0]["current_conversion_price"] == 1.00
    # Post is structurally identical when no AD events
    assert post["preferred_series"][0]["current_conversion_price"] == 1.00
    assert post["as_converted_totals"]["preferred_shares_as_converted"] == 2_000_000


def test_ad_mutation_applied() -> None:
    """Test A scenario: CCP $1.00 → $0.6667, preferred-as-converted recomputes to 3M."""
    pre = _pre_cap_state()
    # Use exact 2/3 to avoid rounding noise on the as-converted math
    cp2 = 2.0 / 3.0
    scenario_output = {
        "ccp_mutations": {"series_seed": cp2},
        "anti_dilution_breakdown": [
            {
                "series_id": "series_seed",
                "ccp_before": 1.00,
                "ccp_after": cp2,
                "rule_id": "anti_dilution.broad_based_weighted_average_coupled",
            }
        ],
    }
    post = csar.build_cap_state_after_round(pre, scenario_output, round_id="series_a")

    # CCP updated
    assert abs(post["preferred_series"][0]["current_conversion_price"] - cp2) < 1e-12
    # preferred_as_converted recomputed: 2M × $1.00 / (2/3) = 3,000,000
    assert post["as_converted_totals"]["preferred_shares_as_converted"] == 3_000_000
    # fully_diluted_shares grows by +1M (2M → 3M)
    assert post["as_converted_totals"]["fully_diluted_shares"] == 14_000_000
    # cap_table_history extended
    assert len(post["cap_table_history"]) == 1
    ev = post["cap_table_history"][0]
    assert ev["event_type"] == "anti_dilution_applied"
    assert ev["series_id"] == "series_seed"
    assert ev["previous_ccp"] == 1.00
    assert abs(ev["new_ccp"] - 2.0 / 3.0) < 1e-12
    assert ev["round_id"] == "series_a"


def test_caller_not_mutated() -> None:
    """Verify the deep-copy boundary: caller's cap_state is untouched."""
    pre = _pre_cap_state()
    csar.build_cap_state_after_round(
        pre,
        {
            "ccp_mutations": {"series_seed": 0.5},
            "anti_dilution_breakdown": [
                {
                    "series_id": "series_seed",
                    "ccp_before": 1.00,
                    "ccp_after": 0.5,
                    "rule_id": "anti_dilution.broad_based_weighted_average_coupled",
                }
            ],
        },
        round_id="series_a",
    )
    assert pre["preferred_series"][0]["current_conversion_price"] == 1.00
    assert pre["as_converted_totals"]["preferred_shares_as_converted"] == 2_000_000


def test_appends_to_existing_history() -> None:
    """When cap_table_history already exists, new events append."""
    pre = _pre_cap_state()
    pre["cap_table_history"] = [
        {
            "event_type": "anti_dilution_applied",
            "round_id": "old_round",
            "series_id": "series_seed",
            "previous_ccp": 1.00,
            "new_ccp": 0.80,
        }
    ]
    scenario_output = {
        "ccp_mutations": {"series_seed": 0.5},
        "anti_dilution_breakdown": [
            {
                "series_id": "series_seed",
                "ccp_before": 0.80,
                "ccp_after": 0.5,
                "rule_id": "anti_dilution.broad_based_weighted_average_coupled",
            }
        ],
    }
    post = csar.build_cap_state_after_round(pre, scenario_output, round_id="series_b")
    assert len(post["cap_table_history"]) == 2
    assert post["cap_table_history"][1]["round_id"] == "series_b"


def test_cli_emits_a_schema_valid_artifact_with_no_applied_at(tmp_path: pathlib.Path) -> None:
    """The CLI path, which no other test in this file exercises.

    All four tests above call `build_cap_state_after_round` directly. The defect this covers lived
    between that function and disk: `--applied-at` defaults to None, the builder wrote it into a
    field the schema types `string`, and the raw `json.dump` never checked. So the usage documented
    at the top of the producer emitted an artifact its own schema rejects, and a suite of four green
    tests could not see it.

    Two properties, because they fail differently: the artifact validates, and the run stamps its OWN
    run id rather than inheriting the pre-round one from the deep-copied metadata.
    """
    import json
    import subprocess
    import sys as _sys

    pre = {
        "as_of_date": "2024-01-01",
        "currency": "USD",
        "founders": [],
        "common_batches": [],
        "preferred_series": [
            {
                "series_id": "series_seed",
                "series_name": "Seed",
                "shares": 1000,
                "issuance_date": "2024-01-01",
                "original_issue_price": 1.0,
                "original_conversion_price": 1.0,
                "current_conversion_price": 1.0,
            }
        ],
        "option_pool": {
            "plan_type": "iso",
            "authorized": 0,
            "issued_and_outstanding": 0,
            "available_for_grant": 0,
        },
        "outstanding_options": [],
        "outstanding_safes": [],
        "outstanding_notes": [],
        "as_converted_totals": {
            "common_shares": 0,
            "preferred_shares_as_converted": 1000,
            "options_outstanding": 0,
            "options_available": 0,
            "warrants_underlying_total": 0,
            "fully_diluted_shares": 1000,
        },
        "metadata": {"run_id": "PRE_ROUND_RUN", "schema_version": "v0.5.0-cap-state"},
    }
    scenarios = {
        "scenarios": [
            {
                "scenario_id": "series_a",
                "computed_outputs": {
                    "ccp_mutations": {"series_seed": 0.8},
                    "anti_dilution_breakdown": [
                        {
                            "series_id": "series_seed",
                            "ccp_before": 1.0,
                            "ccp_after": 0.8,
                            "rule_id": "anti_dilution.broad_based_weighted_average",
                        }
                    ],
                },
            }
        ]
    }
    pre_p, scen_p, out_p = tmp_path / "cap_state.json", tmp_path / "scenarios.json", tmp_path / "out.json"
    pre_p.write_text(json.dumps(pre), encoding="utf-8")
    scen_p.write_text(json.dumps(scenarios), encoding="utf-8")

    # No --applied-at: the documented default, and the shape that used to produce invalid output.
    result = subprocess.run(
        [
            _sys.executable,
            str(SCRIPT_PATH),
            "--cap-state",
            str(pre_p),
            "--scenarios",
            str(scen_p),
            "--scenario-id",
            "series_a",
            "--run-id",
            "POST_ROUND_RUN",
            "-o",
            str(out_p),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    written = json.loads(out_p.read_text(encoding="utf-8"))

    event = (written.get("cap_table_history") or [])[0]
    assert "applied_at" not in event, (
        "an absent optional must be omitted, not written as null — the schema types it `string`, so "
        f"a null makes the artifact invalid: {event}"
    )
    assert written["metadata"]["run_id"] == "POST_ROUND_RUN", (
        "the post-round artifact inherited the run id of the run that produced its INPUT"
    )
