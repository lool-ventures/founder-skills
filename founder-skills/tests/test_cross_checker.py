"""Unit tests for cross_checker.py"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "founder-skills" / "skills" / "cap-table" / "scripts"))

from cross_checker import _values_compatible, cross_check, cross_check_all  # noqa: E402


class TestValuesCompatible:
    def test_exact_int_match(self):
        assert _values_compatible(500_000, 500_000)

    def test_int_relative_tolerance(self):
        # 0.5% diff — within 1%
        assert _values_compatible(1_000_000, 1_005_000)

    def test_int_outside_tolerance(self):
        assert not _values_compatible(1_000_000, 1_020_000)  # 2% diff

    def test_string_substring_match(self):
        assert _values_compatible("Foobar Inc.", "Foobar Inc., a Delaware corp")

    def test_string_mismatch(self):
        assert not _values_compatible("Foobar Inc.", "Different Inc.")

    def test_null_equality(self):
        assert _values_compatible(None, None)
        assert not _values_compatible(None, 0)


class TestCrossCheck:
    def test_single_source_no_disagreement(self):
        result = cross_check(
            "purchase_amount",
            [
                {"value": 500_000, "confidence": "high", "extractor_id": "subagent"},
            ],
        )
        assert result["disagreement"] is False
        assert result["agreed_value"] == 500_000
        assert result["confidence_modulated"] == "high"

    def test_two_sources_agree_keeps_min_confidence(self):
        # Two sources both say 500_000, one high + one medium → keeps "medium"
        result = cross_check(
            "purchase_amount",
            [
                {"value": 500_000, "confidence": "high", "extractor_id": "subagent"},
                {"value": 500_000, "confidence": "medium", "extractor_id": "regex"},
            ],
        )
        assert result["disagreement"] is False
        assert result["confidence_modulated"] == "medium"

    def test_two_sources_disagree_demotes_one_level(self):
        # Disagreement demotes: min was "medium" → demoted to "low"
        result = cross_check(
            "purchase_amount",
            [
                {"value": 500_000, "confidence": "high", "extractor_id": "subagent"},
                {"value": 600_000, "confidence": "medium", "extractor_id": "regex"},
            ],
        )
        assert result["disagreement"] is True
        assert result["confidence_modulated"] == "low"
        assert result["agreed_value"] is None

    def test_disagreement_at_low_demotes_to_absent(self):
        result = cross_check(
            "x",
            [
                {"value": 1, "confidence": "low", "extractor_id": "a"},
                {"value": 2, "confidence": "low", "extractor_id": "b"},
            ],
        )
        assert result["confidence_modulated"] == "absent"

    def test_empty_returns_absent(self):
        result = cross_check("x", [])
        assert result["confidence_modulated"] == "absent"
        assert result["n_sources"] == 0

    def test_string_agreement_via_substring(self):
        # Both say "Foobar Inc." in some form → no disagreement
        result = cross_check(
            "investor_name",
            [
                {"value": "Foobar Inc.", "confidence": "high", "extractor_id": "subagent"},
                {"value": "Foobar Inc., a Delaware corp", "confidence": "high", "extractor_id": "regex"},
            ],
        )
        assert result["disagreement"] is False


class TestCrossCheckAll:
    def test_aggregate(self):
        report = cross_check_all(
            {
                "purchase_amount": [
                    {"value": 500_000, "confidence": "high", "extractor_id": "subagent"},
                    {"value": 500_000, "confidence": "high", "extractor_id": "regex"},
                ],
                "post_money_valuation_cap": [
                    {"value": 20_000_000, "confidence": "high", "extractor_id": "subagent"},
                    {"value": 25_000_000, "confidence": "high", "extractor_id": "regex"},  # disagrees
                ],
            }
        )
        assert report["n_fields"] == 2
        assert report["n_disagreements"] == 1
        assert report["per_field"]["post_money_valuation_cap"]["confidence_modulated"] == "medium"
