"""Unit tests for evidence_verifier.py"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
EV_DIR = REPO_ROOT / "founder-skills" / "skills" / "cap-table" / "scripts"
sys.path.insert(0, str(EV_DIR))

from _normalize import numeric_tokens  # type: ignore[import-not-found]  # noqa: E402
from evidence_verifier import (  # type: ignore[import-not-found]  # noqa: E402
    compact_form,
    has_cid_artifacts,
    is_doc_image_only,
    normalize_text,
    quote_in_doc,
    value_in_doc_check,
    value_token_check,
    verify_extraction,
    verify_field,
)

FIXTURES_DIR = REPO_ROOT / "founder-skills" / "tests" / "fixtures"


class TestNormalization:
    def test_smart_quotes_normalized(self) -> None:
        assert normalize_text("“hello”") == '"hello"'
        assert normalize_text("‘world’") == "'world'"

    def test_dashes_normalized(self) -> None:
        assert normalize_text("a–b—c") == "a-b-c"

    def test_cid_artifacts_stripped(self) -> None:
        # CID strip + whitespace collapse → single space between hello and world
        assert normalize_text("hello (cid:123) world") == "hello world"

    def test_hyphenation_across_linebreak(self) -> None:
        assert "antidilution" in normalize_text("anti-\ndilution")

    def test_whitespace_collapsed(self) -> None:
        assert normalize_text("foo   bar\n\nbaz") == "foo bar baz"


class TestCompactForm:
    def test_strips_non_alnum(self) -> None:
        assert compact_form("is 80%") == "is80"
        assert compact_form("$1,000,000.50") == "100000050"


class TestImageOnlyDetection:
    def test_short_doc_flagged(self) -> None:
        assert is_doc_image_only("short")

    def test_long_doc_not_flagged(self) -> None:
        assert not is_doc_image_only("x" * 1000)


class TestCidDetection:
    def test_many_cids_flagged(self) -> None:
        text = "(cid:1) (cid:2) (cid:3) (cid:4) (cid:5) (cid:6) extra text"
        assert has_cid_artifacts(text)

    def test_few_cids_not_flagged(self) -> None:
        text = "(cid:1) just one"
        assert not has_cid_artifacts(text)


class TestQuoteInDoc:
    def test_exact_substring(self) -> None:
        doc = "The post-money valuation cap is $20,000,000."
        found, kind, _ = quote_in_doc("post-money valuation cap is $20,000,000", doc)
        assert found
        assert kind == "exact"

    def test_smart_quote_normalization(self) -> None:
        doc = 'The "Post-Money Valuation Cap" is $20,000,000.'
        quote = 'The "Post-Money Valuation Cap" is $20,000,000.'  # smart quotes
        found, kind, _ = quote_in_doc(quote, doc)
        assert found
        # Either exact (if same chars) or normalized
        assert kind in ("exact", "normalized")

    def test_space_stripped_falls_back_to_compact(self) -> None:
        doc = "TheDiscountRateis80%(twentypercentoff)"
        quote = "The Discount Rate is 80%"
        found, kind, _ = quote_in_doc(quote, doc)
        assert found
        # Should fall through to compact-form fallback
        assert kind in ("compact", "fuzzy_window", "fuzzy_anchored")

    def test_hyphenation_handled(self) -> None:
        doc = "We use broad-\nbased weighted average anti-dilution."
        quote = "broad-based weighted average anti-dilution"
        found, kind, _ = quote_in_doc(quote, doc)
        assert found

    def test_not_found(self) -> None:
        doc = "Completely unrelated document text about gardens and flowers."
        quote = "The Post-Money Valuation Cap is $20,000,000."
        found, kind, _ = quote_in_doc(quote, doc)
        assert not found
        assert kind == "not_found"

    def test_empty_inputs(self) -> None:
        assert quote_in_doc("", "doc") == (False, "skipped", None)
        assert quote_in_doc("quote", "") == (False, "skipped", None)


class TestValueTokenCheck:
    def test_integer_commafied_match(self) -> None:
        passed, reason = value_token_check(20_000_000, "The Cap is $20,000,000.")
        assert passed, reason

    def test_integer_compact_match(self) -> None:
        passed, reason = value_token_check(20_000_000, "The Cap is 20000000 USD")
        assert passed, reason

    def test_percent_match(self) -> None:
        passed, reason = value_token_check(0.80, "Discount Rate is 80%")
        assert passed, reason

    def test_string_match_case_insensitive(self) -> None:
        passed, reason = value_token_check("Foobar Inc.", "issued by Foobar Inc., a Delaware corporation")
        assert passed, reason

    def test_date_year_match(self) -> None:
        passed, reason = value_token_check("2024-05-15", "issued on May 15, 2024")
        assert passed, reason

    def test_null_value_skipped(self) -> None:
        passed, reason = value_token_check(None, "anything")
        assert passed
        assert reason == "skipped_null"

    def test_value_not_in_quote_fails(self) -> None:
        # The template-blank hallucination pattern: value claimed but not in quote
        passed, reason = value_token_check(45, "During a period of  days following the date hereof")
        assert not passed
        assert "no_token_match" in reason or "value_not_in_quote" in reason


class TestFractionalDollarNumericTokens:
    """Regression: a non-integer float >= 1000 must generate the comma-grouped
    cents form, or value_in_doc fails against a doc printing e.g.
    "$1,234,567.89" verbatim."""

    def test_comma_grouped_cents_form_present(self) -> None:
        tokens = numeric_tokens(1234567.89)
        assert "1,234,567.89" in tokens

    def test_integer_valued_float_path_not_regressed(self) -> None:
        tokens = numeric_tokens(20_000_000.0)
        assert "20,000,000" in tokens
        assert "20M" in tokens

    def test_percent_path_not_regressed(self) -> None:
        tokens = numeric_tokens(0.80)
        assert "80%" in tokens
        assert "80" in tokens

    def test_value_in_doc_matches_fractional_dollar_amount(self) -> None:
        doc = "The purchase price paid by the Investor was $1,234,567.89."
        passed, reason = value_in_doc_check(1234567.89, doc)
        assert passed, reason
        assert "no_token_match" not in reason

    def test_no_spurious_bare_short_token(self) -> None:
        # The variant list must stay specific to this value; it must not
        # contain a bare short token (e.g. a truncated fragment) that would
        # spuriously match unrelated numbers elsewhere in a document.
        tokens = numeric_tokens(1234567.89)
        for tok in tokens:
            assert len(tok) >= 4, f"suspiciously short/generic token: {tok!r}"

    def test_does_not_match_different_comma_grouped_number(self) -> None:
        # Adversarial: a doc containing only a DIFFERENT comma-grouped
        # fractional amount must NOT verify.
        doc = "The purchase price paid by the Investor was $9,887,654.32."
        passed, reason = value_in_doc_check(1234567.89, doc)
        assert not passed
        assert "no_token_match" in reason

    def test_does_not_match_unrelated_document(self) -> None:
        # Adversarial: a doc with no comma-grouped number resembling the
        # value at all must not spuriously match.
        doc = "The parties agree to a governing law clause under Delaware law."
        passed, reason = value_in_doc_check(1234567.89, doc)
        assert not passed
        assert "no_token_match" in reason


class TestBooleanValueSkipped:
    """A boolean field (e.g. a term sheet's co_sale_rights=True) is synthesized from prose — the value
    'True' has no literal token in the doc, so value-matching must SKIP it (like a dict/list), with
    quote_in_doc as the evidence. Otherwise well-sourced booleans false-alarm as 'value not found'."""

    def test_value_in_doc_check_skips_booleans(self) -> None:
        assert value_in_doc_check(True, "The Investor shall have co-sale rights.")[0] is True
        assert value_in_doc_check(False, "irrelevant text with padding " * 5)[0] is True

    def test_boolean_field_verifies_via_quote(self) -> None:
        doc = "The Investor shall have full co-sale rights on any founder transfer of shares. " + "padding " * 40
        res = verify_field(
            "co_sale_rights",
            {
                "value": True,
                "evidence_quote": "The Investor shall have full co-sale rights on any founder transfer of shares.",
            },
            doc,
        )
        assert res.overall_status != "fail", res.reasons

    def test_boolean_does_not_open_a_hallucination_hole(self) -> None:
        # A fabricated quote (not in the doc) must STILL fail quote_in_doc, even for a boolean.
        res = verify_field(
            "co_sale_rights",
            {"value": True, "evidence_quote": "This exact sentence is nowhere in the source document at all."},
            "A completely unrelated term sheet body. " * 30,
        )
        assert res.overall_status == "fail", res.reasons


class TestTemplateBlankRegressionFixture:
    """Regression: the template-blank hallucination class must be caught."""

    def test_fixture_loads(self) -> None:
        fixture_path = FIXTURES_DIR / "cap_table_eval_hallucination_template_blank.json"
        assert fixture_path.exists()
        data = json.loads(fixture_path.read_text())
        assert data["failure_class"] == "template_blank_fill"

    def test_hallucinated_extraction_caught_by_value_in_doc_check(self) -> None:
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

    def test_canonical_extraction_passes(self) -> None:
        fixture = json.loads((FIXTURES_DIR / "cap_table_eval_hallucination_template_blank.json").read_text())
        source = fixture["source_excerpt"]
        good = fixture["canonical_extraction"]
        # The canonical evidence quote (with double space, blank text) IS in the source.
        found, kind, _ = quote_in_doc(good["evidence_quote"], source)
        assert found, f"Canonical quote should match source, kind={kind!r}"

    def test_verify_field_catches_hallucination(self) -> None:
        fixture = json.loads((FIXTURES_DIR / "cap_table_eval_hallucination_template_blank.json").read_text())
        source = fixture["source_excerpt"]
        bad = fixture["hallucinated_extraction"]
        result = verify_field("exclusivity_days", bad, source)
        assert result.overall_status == "fail", (
            f"verify_field should fail the template-blank hallucination but got {result.overall_status}; "
            f"reasons: {result.reasons}"
        )

    def test_verify_field_passes_canonical(self) -> None:
        fixture = json.loads((FIXTURES_DIR / "cap_table_eval_hallucination_template_blank.json").read_text())
        source = fixture["source_excerpt"]
        good = fixture["canonical_extraction"]
        result = verify_field("exclusivity_days", good, source)
        assert result.overall_status == "pass", (
            f"verify_field should pass the canonical extraction but got {result.overall_status}; "
            f"reasons: {result.reasons}"
        )


class TestVerifyExtractionEndToEnd:
    def test_minimal_passing_extraction(self) -> None:
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

    def test_image_only_doc_returns_unverifiable(self) -> None:
        extraction = {"fields": {"x": {"value": 1, "evidence_quote": "foo"}}}
        report = verify_extraction(extraction, "very short")
        assert report.overall_status == "unverifiable_doc"

    def test_cid_blind_demotes_not_found(self) -> None:
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

    def test_fixture_loads(self) -> None:
        fixture_path = FIXTURES_DIR / "cap_table_eval_enum_invention.json"
        assert fixture_path.exists()
        data = json.loads(fixture_path.read_text())
        assert data["failure_class"] == "non_canonical_enum"
        assert "cap_plus_discount" in data["canonical_enum_values"]

    def test_remap_table_consistent(self) -> None:
        fixture = json.loads((FIXTURES_DIR / "cap_table_eval_enum_invention.json").read_text())
        canonical = set(fixture["canonical_enum_values"])
        for non_canon, target in fixture["remap_table"].items():
            assert target in canonical, f"Remap target {target} not in canonical set"
            assert non_canon not in canonical, f"Non-canonical {non_canon} should not be canonical"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


class TestDocxTrackedChanges:
    """B2: the verifier reads the ACCEPTED-revisions view of a tracked-changes .docx (stdlib), so a
    correctly-extracted inserted final term verifies and a struck term does not — python-docx `.text`
    would have dropped BOTH."""

    _NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'

    def _redline_docx(self, tmp_path: Path) -> Path:
        body = (
            "<w:p>"
            '<w:r><w:t xml:space="preserve">cap is </w:t></w:r>'
            '<w:del w:id="1"><w:r><w:delText>$1,000,000</w:delText></w:r></w:del>'
            '<w:ins w:id="2"><w:r><w:t>$2,000,000</w:t></w:r></w:ins>'
            "</w:p>"
        )
        doc = f'<?xml version="1.0"?><w:document {self._NS}><w:body>{body}</w:body></w:document>'
        import zipfile

        p = tmp_path / "redline.docx"
        with zipfile.ZipFile(p, "w") as z:
            z.writestr("word/document.xml", doc)
        return p

    def test_load_doc_text_accepts_revisions(self, tmp_path: Path) -> None:
        from evidence_verifier import _load_doc_text  # type: ignore[import-not-found]

        text = _load_doc_text(self._redline_docx(tmp_path))
        assert "$2,000,000" in text  # inserted final term — survives
        assert "$1,000,000" not in text  # struck — excluded

    def test_inserted_term_verifies_struck_does_not(self, tmp_path: Path) -> None:
        from evidence_verifier import _load_doc_text  # type: ignore[import-not-found]

        text = _load_doc_text(self._redline_docx(tmp_path))
        found_ins, _, _ = quote_in_doc("$2,000,000", text)
        found_struck, _, _ = quote_in_doc("$1,000,000", text)
        assert found_ins is True
        assert found_struck is False
