"""Unit tests for backward_verifier.py"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "founder-skills" / "skills" / "cap-table" / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from backward_verifier import (  # type: ignore[import-not-found]  # noqa: E402
    FIELD_PROMPT_TEMPLATES,
    FIELDS_BY_INSTRUMENT_TYPE,
    _select_fields,
    _values_agree,
    emit_prompts,
    score_responses,
)


class TestFieldSelection:
    def test_safe_selects_high_stakes_only(self) -> None:
        extraction = {
            "instrument_type": "safe",
            "fields": {
                "purchase_amount": 500000,
                "post_money_valuation_cap": 20000000,
                "form": "cap_plus_discount",  # synthesized — not selected
                "jurisdiction": "delaware",  # not in candidate list
                "mfn_provision": {"present": False},  # composite — not selected
            },
        }
        selected = _select_fields("safe", extraction["fields"])
        assert "purchase_amount" in selected
        assert "post_money_valuation_cap" in selected
        assert "form" not in selected
        assert "mfn_provision" not in selected

    def test_null_value_skipped(self) -> None:
        """Don't re-extract fields the original left null — there's nothing
        to verify."""
        fields = {"purchase_amount": None, "post_money_valuation_cap": 20000000}
        selected = _select_fields("safe", fields)
        assert "purchase_amount" not in selected
        assert "post_money_valuation_cap" in selected

    def test_note_uses_note_field_set(self) -> None:
        fields = {"principal": 100000, "annual_interest_rate": 0.05}
        selected = _select_fields("convertible_note", fields)
        assert "principal" in selected
        assert "annual_interest_rate" in selected

    def test_unknown_instrument_returns_empty(self) -> None:
        assert _select_fields("unknown", {"x": 1}) == []


class TestValueAgreement:
    def test_int_exact_match(self) -> None:
        ok, _ = _values_agree("purchase_amount", 500000, 500000)
        assert ok

    def test_float_epsilon_match(self) -> None:
        ok, _ = _values_agree("discount_multiplier", 0.80, 0.8000001)
        assert ok

    def test_float_relative_1pct_tolerance(self) -> None:
        # 1% tolerance for amounts when at least one side is a float (precision
        # drift from formula-derived values). Ints stay strict (no rounding
        # tolerance — $1M and $1.005M are different amounts).
        ok, _ = _values_agree("purchase_amount", 1_000_000.0, 1_005_000)
        assert ok

    def test_float_outside_tolerance_mismatch(self) -> None:
        ok, _ = _values_agree("discount_multiplier", 0.80, 0.70)
        assert not ok

    def test_int_mismatch(self) -> None:
        ok, why = _values_agree("post_money_valuation_cap", 20_000_000, 25_000_000)
        assert not ok
        assert "20000000" in why or "20" in why

    def test_string_exact_match_case_insensitive(self) -> None:
        ok, _ = _values_agree("investor_name", "Foobar Inc.", "FOOBAR INC.")
        assert ok

    def test_string_substring_match(self) -> None:
        # Re-extractor returned a longer form (e.g. with comma-suffix) — should match
        ok, _ = _values_agree("investor_name", "Foobar Capital", "Foobar Capital LLC, a Delaware limited")
        assert ok

    def test_date_format_variance(self) -> None:
        ok, _ = _values_agree("issuance_date", "2024-05-15", "2024-05-15")
        assert ok

    def test_date_mismatch_caught(self) -> None:
        ok, _ = _values_agree("issuance_date", "2024-05-15", "2025-05-15")
        assert not ok

    def test_both_null_agrees(self) -> None:
        ok, why = _values_agree("x", None, None)
        assert ok
        assert why == "both_null"

    def test_null_vs_value_mismatch(self) -> None:
        ok, _ = _values_agree("x", None, 500000)
        assert not ok


class TestPromptEmission:
    def test_emits_prompts_for_populated_fields(self) -> None:
        extraction = {
            "instrument_type": "safe",
            "fields": {
                "purchase_amount": 500000,
                "post_money_valuation_cap": 20000000,
                "discount_multiplier": 0.8,
                "form": "cap_plus_discount",
            },
        }
        prompts = emit_prompts(extraction, "/path/to/source.pdf")
        field_names = [p["field"] for p in prompts]
        assert "purchase_amount" in field_names
        assert "post_money_valuation_cap" in field_names
        assert "discount_multiplier" in field_names
        assert "form" not in field_names  # synthesized

    def test_prompt_body_includes_source_path(self) -> None:
        extraction = {"instrument_type": "safe", "fields": {"purchase_amount": 500000}}
        prompts = emit_prompts(extraction, "/some/doc.pdf")
        assert any("/some/doc.pdf" in p["prompt"] for p in prompts)

    def test_prompt_includes_field_specific_guidance(self) -> None:
        """Discount-multiplier prompt should remind about Gotcha #3."""
        extraction = {"instrument_type": "safe", "fields": {"discount_multiplier": 0.8}}
        prompts = emit_prompts(extraction, "/x.pdf")
        assert any("Gotcha #3" in p["prompt"] for p in prompts)

    def test_prompt_demands_json_output(self) -> None:
        extraction = {"instrument_type": "safe", "fields": {"purchase_amount": 100000}}
        prompts = emit_prompts(extraction, "/x.pdf")
        assert all("JSON" in p["prompt"] or "json" in p["prompt"].lower() for p in prompts)

    def test_no_prompts_for_empty_extraction(self) -> None:
        extraction = {"instrument_type": "safe", "fields": {}}
        prompts = emit_prompts(extraction, "/x.pdf")
        assert prompts == []


class TestScoreResponses:
    def test_all_agree_passes(self) -> None:
        extraction = {
            "instrument_type": "safe",
            "fields": {
                "purchase_amount": 500000,
                "post_money_valuation_cap": 20000000,
            },
        }
        responses = [
            {"field": "purchase_amount", "value": 500000, "evidence_quote": "..."},
            {"field": "post_money_valuation_cap", "value": 20000000, "evidence_quote": "..."},
        ]
        report = score_responses(extraction, responses)
        assert report.overall_status == "pass"
        assert report.n_matched == 2
        assert report.n_mismatched == 0

    def test_one_mismatch_fails(self) -> None:
        extraction = {
            "instrument_type": "safe",
            "fields": {
                "purchase_amount": 500000,
                "post_money_valuation_cap": 20000000,
            },
        }
        responses = [
            {"field": "purchase_amount", "value": 500000, "evidence_quote": "..."},
            {"field": "post_money_valuation_cap", "value": 25000000, "evidence_quote": "..."},
        ]
        report = score_responses(extraction, responses)
        assert report.overall_status == "fail"
        assert report.n_mismatched == 1
        mismatch = next(r for r in report.per_field if r.field_name == "post_money_valuation_cap")
        assert mismatch.agreement == "mismatch"
        assert "20000000" in mismatch.reason

    def test_missing_response_records_skipped(self) -> None:
        extraction = {
            "instrument_type": "safe",
            "fields": {"purchase_amount": 500000, "post_money_valuation_cap": 20000000},
        }
        responses = [{"field": "purchase_amount", "value": 500000}]
        # No response for post_money_valuation_cap
        report = score_responses(extraction, responses)
        assert report.n_skipped == 1
        skipped = next(r for r in report.per_field if r.field_name == "post_money_valuation_cap")
        assert skipped.agreement == "skipped"

    def test_responses_accepted_wrapped_in_object(self) -> None:
        extraction = {"instrument_type": "safe", "fields": {"purchase_amount": 500000}}
        responses_wrapped = {"responses": [{"field": "purchase_amount", "value": 500000}]}
        # score_responses takes the unwrapped list; the CLI handles unwrapping
        report = score_responses(extraction, responses_wrapped["responses"])
        assert report.overall_status == "pass"


class TestCliRoundTrip:
    """End-to-end CLI test: --phase=prompt → simulated responses → --phase=score."""

    @pytest.fixture
    def extraction_file(self, tmp_path: Path) -> Path:
        extraction = {
            "instrument_type": "safe",
            "fields": {
                "purchase_amount": 500000,
                "post_money_valuation_cap": 20000000,
                "discount_multiplier": 0.80,
                "form": "cap_plus_discount",
            },
            "confidence": {},
            "ambiguities": [],
        }
        p = tmp_path / "extraction.json"
        p.write_text(json.dumps(extraction))
        return p

    def test_prompt_phase_emits_structured_output(self, extraction_file: Path) -> None:
        # The re-extraction prompt carries the document TEXT inline. Handing a
        # sub-agent a path instead lets the check silently no-op when the path
        # does not resolve in its namespace — the guardrail fails closed with no
        # diagnostic, which is the failure this transport shape removes.
        doc = extraction_file.parent / "source_doc.txt"
        doc.write_text(
            "SAFE purchase amount is $500,000 at a $10,000,000 post-money valuation cap with a 20% discount.",
            encoding="utf-8",
        )
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPTS_DIR / "backward_verifier.py"),
                "--phase=prompt",
                "--extraction",
                str(extraction_file),
                "--doc-text",
                str(doc),
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        out = json.loads(result.stdout)
        assert out["n_prompts"] == 3  # 3 populated non-synthesized fields
        fields = [p["field"] for p in out["prompts"]]
        assert "purchase_amount" in fields
        assert "discount_multiplier" in fields
        # The document text must reach the prompt itself, not a path reference.
        joined = json.dumps(out)
        assert "$500,000" in joined
        assert "use the Read tool" not in joined
        assert "form" not in fields

    def test_score_phase_consumes_responses(self, extraction_file: Path) -> None:
        # Simulate sub-agent responses (agreeing)
        responses = {
            "responses": [
                {"field": "purchase_amount", "value": 500000, "evidence_quote": "..."},
                {"field": "post_money_valuation_cap", "value": 20000000, "evidence_quote": "..."},
                {"field": "discount_multiplier", "value": 0.80, "evidence_quote": "..."},
            ]
        }
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPTS_DIR / "backward_verifier.py"),
                "--phase=score",
                "--extraction",
                str(extraction_file),
            ],
            input=json.dumps(responses),
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        report = json.loads(result.stdout)
        assert report["overall_status"] == "pass"
        assert report["n_matched"] == 3

    def test_score_phase_exits_1_on_mismatch_block_mode(self, extraction_file: Path) -> None:
        responses = {
            "responses": [
                {"field": "purchase_amount", "value": 99_999, "evidence_quote": "..."},  # wrong
                {"field": "post_money_valuation_cap", "value": 20000000, "evidence_quote": "..."},
                {"field": "discount_multiplier", "value": 0.80, "evidence_quote": "..."},
            ]
        }
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPTS_DIR / "backward_verifier.py"),
                "--phase=score",
                "--mode=block",
                "--extraction",
                str(extraction_file),
            ],
            input=json.dumps(responses),
            capture_output=True,
            text=True,
        )
        assert result.returncode == 1
        report = json.loads(result.stdout)
        assert report["overall_status"] == "fail"
        assert report["n_mismatched"] == 1

    def test_score_phase_warn_mode_default_exits_0_on_mismatch(self, extraction_file: Path) -> None:
        """extraction-9: default --mode is warn — a mismatch is informational
        (exit 0), per the calibrated noisy-disagreement contract."""
        responses = {
            "responses": [
                {"field": "purchase_amount", "value": 99_999, "evidence_quote": "..."},  # wrong
                {"field": "post_money_valuation_cap", "value": 20000000, "evidence_quote": "..."},
                {"field": "discount_multiplier", "value": 0.80, "evidence_quote": "..."},
            ]
        }
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPTS_DIR / "backward_verifier.py"),
                "--phase=score",
                "--extraction",
                str(extraction_file),
            ],
            input=json.dumps(responses),
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        report = json.loads(result.stdout)
        # Status still reflects the disagreement; only the exit code is warn-mode.
        assert report["overall_status"] == "fail"
        assert report["n_mismatched"] == 1


class TestFieldTemplateCoverage:
    """Every field listed in FIELDS_BY_INSTRUMENT_TYPE must have a prompt template."""

    def test_all_safe_fields_have_templates(self) -> None:
        for f in FIELDS_BY_INSTRUMENT_TYPE["safe"]:
            assert f in FIELD_PROMPT_TEMPLATES, f"SAFE field {f!r} missing prompt template"

    def test_all_note_fields_have_templates(self) -> None:
        for f in FIELDS_BY_INSTRUMENT_TYPE["convertible_note"]:
            assert f in FIELD_PROMPT_TEMPLATES, f"Note field {f!r} missing prompt template"

    def test_all_term_sheet_fields_have_templates(self) -> None:
        for f in FIELDS_BY_INSTRUMENT_TYPE["term_sheet"]:
            assert f in FIELD_PROMPT_TEMPLATES, f"Term sheet field {f!r} missing prompt template"
