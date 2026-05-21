"""Unit tests for evidence_verifier.py"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
EV_DIR = REPO_ROOT / "founder-skills" / "skills" / "cap-table" / "scripts"
sys.path.insert(0, str(EV_DIR))

from evidence_verifier import (  # noqa: E402
    compact_form,
    has_cid_artifacts,
    is_doc_image_only,
    normalize_text,
    quote_in_doc,
    value_token_check,
    verify_extraction,
    verify_field,
)

FIXTURES_DIR = REPO_ROOT / "founder-skills" / "tests" / "fixtures"


class TestNormalization:
    def test_smart_quotes_normalized(self):
        assert normalize_text("“hello”") == '"hello"'
        assert normalize_text("‘world’") == "'world'"

    def test_dashes_normalized(self):
        assert normalize_text("a–b—c") == "a-b-c"

    def test_cid_artifacts_stripped(self):
        # CID strip + whitespace collapse → single space between hello and world
        assert normalize_text("hello (cid:123) world") == "hello world"

    def test_hyphenation_across_linebreak(self):
        assert "antidilution" in normalize_text("anti-\ndilution")

    def test_whitespace_collapsed(self):
        assert normalize_text("foo   bar\n\nbaz") == "foo bar baz"


class TestCompactForm:
    def test_strips_non_alnum(self):
        assert compact_form("is 80%") == "is80"
        assert compact_form("$1,000,000.50") == "100000050"


class TestImageOnlyDetection:
    def test_short_doc_flagged(self):
        assert is_doc_image_only("short")

    def test_long_doc_not_flagged(self):
        assert not is_doc_image_only("x" * 1000)


class TestCidDetection:
    def test_many_cids_flagged(self):
        text = "(cid:1) (cid:2) (cid:3) (cid:4) (cid:5) (cid:6) extra text"
        assert has_cid_artifacts(text)

    def test_few_cids_not_flagged(self):
        text = "(cid:1) just one"
        assert not has_cid_artifacts(text)


class TestQuoteInDoc:
    def test_exact_substring(self):
        doc = "The post-money valuation cap is $20,000,000."
        found, kind, _ = quote_in_doc("post-money valuation cap is $20,000,000", doc)
        assert found
        assert kind == "exact"

    def test_smart_quote_normalization(self):
        doc = 'The "Post-Money Valuation Cap" is $20,000,000.'
        quote = 'The "Post-Money Valuation Cap" is $20,000,000.'  # smart quotes
        found, kind, _ = quote_in_doc(quote, doc)
        assert found
        # Either exact (if same chars) or normalized
        assert kind in ("exact", "normalized")

    def test_space_stripped_falls_back_to_compact(self):
        doc = "TheDiscountRateis80%(twentypercentoff)"
        quote = "The Discount Rate is 80%"
        found, kind, _ = quote_in_doc(quote, doc)
        assert found
        # Should fall through to compact-form fallback
        assert kind in ("compact", "fuzzy_window", "fuzzy_anchored")

    def test_hyphenation_handled(self):
        doc = "We use broad-\nbased weighted average anti-dilution."
        quote = "broad-based weighted average anti-dilution"
        found, kind, _ = quote_in_doc(quote, doc)
        assert found

    def test_not_found(self):
        doc = "Completely unrelated document text about gardens and flowers."
        quote = "The Post-Money Valuation Cap is $20,000,000."
        found, kind, _ = quote_in_doc(quote, doc)
        assert not found
        assert kind == "not_found"

    def test_empty_inputs(self):
        assert quote_in_doc("", "doc") == (False, "skipped", None)
        assert quote_in_doc("quote", "") == (False, "skipped", None)


class TestValueTokenCheck:
    def test_integer_commafied_match(self):
        passed, reason = value_token_check(20_000_000, "The Cap is $20,000,000.")
        assert passed, reason

    def test_integer_compact_match(self):
        passed, reason = value_token_check(20_000_000, "The Cap is 20000000 USD")
        assert passed, reason

    def test_percent_match(self):
        passed, reason = value_token_check(0.80, "Discount Rate is 80%")
        assert passed, reason

    def test_string_match_case_insensitive(self):
        passed, reason = value_token_check("Foobar Inc.", "issued by Foobar Inc., a Delaware corporation")
        assert passed, reason

    def test_date_year_match(self):
        passed, reason = value_token_check("2024-05-15", "issued on May 15, 2024")
        assert passed, reason

    def test_null_value_skipped(self):
        passed, reason = value_token_check(None, "anything")
        assert passed
        assert reason == "skipped_null"

    def test_value_not_in_quote_fails(self):
        # The template-blank hallucination pattern: value claimed but not in quote
        passed, reason = value_token_check(45, "During a period of  days following the date hereof")
        assert not passed
        assert "no_token_match" in reason or "value_not_in_quote" in reason


class TestTemplateBlankRegressionFixture:
    """Regression: the template-blank hallucination class must be caught."""

    def test_fixture_loads(self):
        fixture_path = FIXTURES_DIR / "cap_table_eval_hallucination_template_blank.json"
        assert fixture_path.exists()
        data = json.loads(fixture_path.read_text())
        assert data["failure_class"] == "template_blank_fill"

    def test_hallucinated_extraction_caught_by_value_in_doc_check(self):
        """The template-blank hallucination's evidence_quote fuzzy-matches the source
        (only the fabricated '45' differs from the blank), so quote_in_doc may
        pass with fuzzy_window. The hallucination is caught by value_in_doc:
        the value '45' must appear in the source doc to be real, and it doesn't.
        """
        from evidence_verifier import value_in_doc_check

        fixture = json.loads((FIXTURES_DIR / "cap_table_eval_hallucination_template_blank.json").read_text())
        source = fixture["source_excerpt"]
        bad = fixture["hallucinated_extraction"]
        # The value 45 should NOT be in the doc → value_in_doc_check fails
        vd_passed, vd_reason = value_in_doc_check(bad["value"], source)
        assert not vd_passed, f"value_in_doc should fail (45 is not in source) but passed: {vd_reason}"

    def test_canonical_extraction_passes(self):
        fixture = json.loads((FIXTURES_DIR / "cap_table_eval_hallucination_template_blank.json").read_text())
        source = fixture["source_excerpt"]
        good = fixture["canonical_extraction"]
        # The canonical evidence quote (with double space, blank text) IS in the source.
        found, kind, _ = quote_in_doc(good["evidence_quote"], source)
        assert found, f"Canonical quote should match source, kind={kind!r}"

    def test_verify_field_catches_hallucination(self):
        fixture = json.loads((FIXTURES_DIR / "cap_table_eval_hallucination_template_blank.json").read_text())
        source = fixture["source_excerpt"]
        bad = fixture["hallucinated_extraction"]
        result = verify_field("exclusivity_days", bad, source)
        assert result.overall_status == "fail", (
            f"verify_field should fail the template-blank hallucination but got {result.overall_status}; "
            f"reasons: {result.reasons}"
        )

    def test_verify_field_passes_canonical(self):
        fixture = json.loads((FIXTURES_DIR / "cap_table_eval_hallucination_template_blank.json").read_text())
        source = fixture["source_excerpt"]
        good = fixture["canonical_extraction"]
        result = verify_field("exclusivity_days", good, source)
        assert result.overall_status == "pass", (
            f"verify_field should pass the canonical extraction but got {result.overall_status}; "
            f"reasons: {result.reasons}"
        )


class TestVerifyExtractionEndToEnd:
    def test_minimal_passing_extraction(self):
        doc = (
            "This SAFE is one of a series. The Post-Money Valuation Cap is $20,000,000. The Discount Rate is 80%. " * 20
        )
        extraction = {
            "fields": {
                "post_money_valuation_cap": {
                    "value": 20_000_000,
                    "evidence_quote": "The Post-Money Valuation Cap is $20,000,000.",
                },
                "discount_multiplier": {
                    "value": 0.80,
                    "evidence_quote": "The Discount Rate is 80%.",
                },
            }
        }
        report = verify_extraction(extraction, doc)
        assert report.overall_status == "pass"
        assert report.n_passed == 2
        assert report.n_failed == 0

    def test_image_only_doc_returns_unverifiable(self):
        extraction = {"fields": {"x": {"value": 1, "evidence_quote": "foo"}}}
        report = verify_extraction(extraction, "very short")
        assert report.overall_status == "unverifiable_doc"

    def test_cid_blind_demotes_not_found(self):
        # Simulate a doc full of CID artifacts (DocuSign-style)
        cid_doc = " ".join(f"(cid:{i})" for i in range(100)) + " unrelated text after"
        # Pad to pass image-only threshold
        cid_doc = cid_doc + " filler" * 100
        extraction = {"fields": {"x": {"value": 100, "evidence_quote": "this quote is not in the cid doc"}}}
        report = verify_extraction(extraction, cid_doc)
        # The field should be demoted to unverifiable, not failed
        statuses = [f.overall_status for f in report.per_field]
        assert "unverifiable" in statuses, f"Expected unverifiable demotion under CID artifacts, got {statuses}"


class TestNonCanonicalEnumFixture:
    """Doesn't enforce enum constraints (that's earlier work's job
    via extract_instrument.py's validate_safe), but the fixture should still
    be loadable and the canonical/non_canonical distinction should be clear."""

    def test_fixture_loads(self):
        fixture_path = FIXTURES_DIR / "cap_table_eval_enum_invention.json"
        assert fixture_path.exists()
        data = json.loads(fixture_path.read_text())
        assert data["failure_class"] == "non_canonical_enum"
        assert "cap_plus_discount" in data["canonical_enum_values"]

    def test_remap_table_consistent(self):
        fixture = json.loads((FIXTURES_DIR / "cap_table_eval_enum_invention.json").read_text())
        canonical = set(fixture["canonical_enum_values"])
        for non_canon, target in fixture["remap_table"].items():
            assert target in canonical, f"Remap target {target} not in canonical set"
            assert non_canon not in canonical, f"Non-canonical {non_canon} should not be canonical"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
