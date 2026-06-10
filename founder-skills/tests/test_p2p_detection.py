"""Sprint 3: pay-to-play detection in extract_aoa.py.

Per v3 §10 Sprint 3 + the v0.4.0 anti_dilution.pay_to_play_provision_detected
rule. P2P math is deferred to v0.5.0; this is detection-only — the rule fires
as a counsel-review flag so the founder knows v0.4.0's dilution figures may
over-protect non-participating AD holders.
"""

from __future__ import annotations

import importlib.util
import pathlib

SCRIPT_PATH = pathlib.Path(__file__).parent.parent / "skills" / "cap-table" / "scripts" / "extract_aoa.py"
spec = importlib.util.spec_from_file_location("extract_aoa", SCRIPT_PATH)
assert spec and spec.loader
extract_aoa = importlib.util.module_from_spec(spec)
spec.loader.exec_module(extract_aoa)


class TestPayToPlayDetection:
    def test_direct_term_match(self) -> None:
        assert extract_aoa.detect_pay_to_play({"source_text": "The Pay-to-Play provision shall apply..."}) is True
        assert extract_aoa.detect_pay_to_play({"source_text": "pay to play"}) is True
        assert extract_aoa.detect_pay_to_play({"source_text": "PAY-TO-PLAY"}) is True

    def test_drafting_language_failure_to_participate_forfeits(self) -> None:
        text = (
            "If any holder of Preferred Stock fails to participate in such "
            "Subsequent Financing for at least their pro-rata share, such "
            "holder shall forfeit their anti-dilution adjustment rights."
        )
        assert extract_aoa.detect_pay_to_play({"source_text": text}) is True

    def test_drafting_language_mandatory_conversion(self) -> None:
        text = (
            "Mandatory conversion to Common Stock shall apply to any "
            "Non-Participating Holder who did not participate in the Qualified "
            "Financing at full pro-rata."
        )
        assert extract_aoa.detect_pay_to_play({"source_text": text}) is True

    def test_shadow_series_pattern(self) -> None:
        text = (
            "Non-participating holders' shares shall be automatically converted "
            "to a Shadow Series with no anti-dilution protection."
        )
        assert extract_aoa.detect_pay_to_play({"source_text": text}) is True

    def test_no_match_on_unrelated_text(self) -> None:
        text = (
            "The Company shall pay dividends to Common Stock at the discretion "
            "of the Board. Players in the secondary market may purchase shares."
        )
        assert extract_aoa.detect_pay_to_play({"source_text": text}) is False

    def test_explicit_boolean_override(self) -> None:
        # Caller can flag P2P upstream without text — useful for hand-curation
        assert extract_aoa.detect_pay_to_play({"pay_to_play_present": True}) is True

    def test_empty_fields_no_false_positive(self) -> None:
        assert extract_aoa.detect_pay_to_play({}) is False
        assert extract_aoa.detect_pay_to_play({"source_text": ""}) is False
        assert extract_aoa.detect_pay_to_play({"pay_to_play_present": False}) is False

    def test_clause_text_field(self) -> None:
        # Alternative field name some extractors use
        assert extract_aoa.detect_pay_to_play({"pay_to_play_clause_text": "pay-to-play clause text here"}) is True


class TestCounselReviewItemIntegration:
    """Verify the P2P counsel-review item flows through detect_counsel_review_items."""

    def test_p2p_emits_counsel_item(self) -> None:
        fields = {
            "jurisdiction_structure": "delaware",
            "preferred_series": [],
            "source_text": "Pay-to-Play: failure to participate results in conversion to common.",
        }
        items = extract_aoa.detect_counsel_review_items(fields)
        rule_ids = {i["rule_id"] for i in items}
        assert "anti_dilution.pay_to_play_provision_detected" in rule_ids

    def test_no_p2p_no_item(self) -> None:
        fields = {
            "jurisdiction_structure": "delaware",
            "preferred_series": [],
            "source_text": "Standard Cooley-form anti-dilution provision applies.",
        }
        items = extract_aoa.detect_counsel_review_items(fields)
        rule_ids = {i["rule_id"] for i in items}
        assert "anti_dilution.pay_to_play_provision_detected" not in rule_ids
