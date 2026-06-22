"""Unit tests for concise_report.py — the lightweight math-answer renderer.

Asserts it renders the deterministic solver's numbers (the same fields the full
pipeline reads) without requiring the heavy-tail artifacts, and that it does not
fabricate a post-financing table for cap-implied-only / blocked scenarios.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "skills" / "cap-table" / "scripts" / "concise_report.py"


def _load():
    spec = importlib.util.spec_from_file_location("concise_report", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


CR = _load()

INPUTS = {"company_name": "BenchCo"}

FULL_SCENARIO = {
    "scenarios": [
        {
            "label": "Series A",
            "computed_outputs": {
                "completeness": "full",
                "equity_financing_price": 0.875,
                "per_safe": {"safe_disc": {"conversion_price": 0.70, "conversion_shares": 1428571}},
                "aggregate_ownership_by_class": {
                    "founders_pct": 0.625,
                    "safe_pct": 0.0893,
                    "new_money_pct": 0.2857,
                    "preferred_pct": 0.0,
                },
                "post_round_fully_diluted_shares": 16000000,
            },
        }
    ]
}


def test_renders_solver_numbers_without_tail_artifacts():
    md = CR.render(INPUTS, FULL_SCENARIO, rule_audit=None)
    # the deterministic numbers come through verbatim-in-spirit
    assert "$0.8750" in md
    assert "$0.7000" in md
    assert "1,428,571 shares" in md
    assert "62.5%" in md  # founders
    assert "28.6%" in md  # new money
    assert "16,000,000 shares" in md  # FD total
    # it advertises itself as concise and offers the full review
    assert "concise" in md.lower()
    assert "full review" in md.lower()


def test_no_rule_audit_is_fine():
    # counsel_packet / rule_audit are NOT required for a concise answer
    md = CR.render(INPUTS, FULL_SCENARIO, rule_audit=None)
    assert "## Flags" not in md


def test_rule_audit_flags_and_boundary_render():
    ra = {
        "counsel_review_items": [{"rule_id": "delaware_cross_border.qsbs_date_sensitive", "title": "QSBS date"}],
        "date_sensitive_watchlist": [{"rule_id": "safe.israeli_2025_safe_harbor"}],
    }
    md = CR.render(INPUTS, FULL_SCENARIO, rule_audit=ra)
    assert "qsbs_date_sensitive" in md
    assert "israeli_2025_safe_harbor" in md
    # reliance boundary appears when counsel items are present
    assert "defer eligibility" in md.lower()


def test_cap_implied_only_does_not_fabricate_post_financing():
    doc = {
        "scenarios": [
            {
                "label": "Standalone SAFE",
                "computed_outputs": {"completeness": "cap_implied_only", "cap_implied_ownership": 0.10},
            }
        ]
    }
    md = CR.render(INPUTS, doc, rule_audit=None)
    assert "Cap-implied ownership (pre-financing)" in md
    assert "10.0%" in md
    # must NOT invent a founders/new-investor post-financing table
    assert "New investors" not in md
    assert "cap_implied_only" in md


def test_blocked_scenario_surfaces_blocker():
    doc = {
        "scenarios": [
            {
                "label": "Circular MFN",
                "computed_outputs": {"completeness": "structural_only", "blockers": [{"code": "E_SAFE_CIRCULAR_MFN"}]},
            }
        ]
    }
    md = CR.render(INPUTS, doc, rule_audit=None)
    assert "E_SAFE_CIRCULAR_MFN" in md
    assert "Blocked" in md
