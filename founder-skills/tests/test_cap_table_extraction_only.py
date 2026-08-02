"""Tests for the cap-table extraction-only render path.

Covers `compose_extraction_report.py` — the lightweight renderer used when a
founder uploads a single financing instrument (SAFE/note/warrant) with no
surrounding equity base, so the full pipeline (cap_state.py / rule_audit.py /
compose_report.py) has no cap base to build from.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import Any

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPTS = os.path.join(_REPO, "founder-skills", "skills", "cap-table", "scripts")
SCHEMAS = os.path.join(_REPO, "founder-skills", "skills", "cap-table", "references", "schemas")

sys.path.insert(0, SCRIPTS)

import compose_extraction_report as cer  # type: ignore[import-not-found]  # noqa: E402

# ---------------------------------------------------------------------------
# Fixtures — minimal inputs.json (company meta only, NO founders/pool/preferred)
# and a single SAFE instrument.
# ---------------------------------------------------------------------------

_MINIMAL_INPUTS: dict[str, Any] = {
    "company_name": "Acmecorp",
    "analysis_date": "2026-05-19",
    "mode": "standard",
    "jurisdiction": {
        "structure": "delaware",
        "incorporated_date": "2024-01-01",
        "iia_grants_history": {"has_grants": False, "grant_details": []},
    },
    "metadata": {"run_id": "test", "schema_version": "v0.5.0-inputs"},
}

_SAFE_ONLY: dict[str, Any] = {
    "id": "safe_001",
    "investor_name": "Angel A",
    "purchase_amount": 500_000,
    "post_money_valuation_cap": 8_000_000,
    "pre_money_valuation_cap": None,
    "discount_multiplier": None,
    "mfn_provision": None,
    "pro_rata_side_letter": None,
    "issuance_date": "2025-01-01",
    "form": "yc_postmoney_cap",
    "conversion_price_override": None,
    "source_document": None,
    "extraction_confidence": "high",
}

_INSTRUMENTS_ONE_SAFE: dict[str, Any] = {
    "safes": [_SAFE_ONLY],
    "convertible_notes": [],
    "warrants": [],
    "option_grants": [],
    "metadata": {"run_id": "test", "schema_version": "v0.5.0-instruments"},
}


def _run_cli(inputs_path: str, instruments_path: str, review_dir: str) -> tuple[int, str, str]:
    res = subprocess.run(
        [
            sys.executable,
            os.path.join(SCRIPTS, "compose_extraction_report.py"),
            "--inputs",
            inputs_path,
            "--instruments",
            instruments_path,
            "--review-dir",
            review_dir,
            "--run-id",
            "testrun01",
            "--pretty",
        ],
        capture_output=True,
        text=True,
    )
    return res.returncode, res.stdout, res.stderr


class TestExtractionOnlyCLI:
    def test_cli_writes_all_four_outputs_plus_input_copies(self, tmp_path: Any) -> None:
        inputs_path = tmp_path / "inputs.json"
        instr_path = tmp_path / "instruments.json"
        inputs_path.write_text(json.dumps(_MINIMAL_INPUTS))
        instr_path.write_text(json.dumps(_INSTRUMENTS_ONE_SAFE))

        review_dir = tmp_path / "cap-table-acmecorp-extraction"
        rc, stdout, stderr = _run_cli(str(inputs_path), str(instr_path), str(review_dir))
        assert rc == 0, f"stderr: {stderr}"

        report_md = review_dir / "report_extraction_only.md"
        sentinel_json = review_dir / "extraction_only.json"
        coverage_json = review_dir / "coverage_disclosure.json"
        inputs_copy = review_dir / "inputs.json"
        instruments_copy = review_dir / "instruments.json"

        for p in (report_md, sentinel_json, coverage_json, inputs_copy, instruments_copy):
            assert p.exists(), f"expected {p} to exist"

        # Copies must be self-contained (readable JSON, matching source content).
        assert json.loads(inputs_copy.read_text()) == _MINIMAL_INPUTS
        assert json.loads(instruments_copy.read_text()) == _INSTRUMENTS_ONE_SAFE

        # Receipt shape (mirrors quick_assess's receipt).
        receipt = json.loads(stdout)
        assert receipt["mode"] == "extraction_only"
        assert receipt["company_name"] == "Acmecorp"
        assert set(receipt["wrote"].keys()) == {
            "extraction_report_md",
            "sentinel_json",
            "coverage_disclosure_json",
            "inputs_json",
            "instruments_json",
        }
        for path_str in receipt["wrote"].values():
            assert os.path.isabs(path_str)
            assert os.path.exists(path_str)

    def test_report_has_banner_and_safe_cap_and_no_ownership_math_language(self, tmp_path: Any) -> None:
        inputs_path = tmp_path / "inputs.json"
        instr_path = tmp_path / "instruments.json"
        inputs_path.write_text(json.dumps(_MINIMAL_INPUTS))
        instr_path.write_text(json.dumps(_INSTRUMENTS_ONE_SAFE))

        review_dir = tmp_path / "cap-table-acmecorp-extraction"
        rc, _stdout, stderr = _run_cli(str(inputs_path), str(instr_path), str(review_dir))
        assert rc == 0, f"stderr: {stderr}"

        report_md = (review_dir / "report_extraction_only.md").read_text()

        assert (
            "⚠ **Instrument terms only — no cap base modeled.** No ownership %, dilution, or "
            "fully-diluted math was computed; provide the founder/pool cap base for a full "
            "cap-table review." in report_md
        )
        # The SAFE's cap must be rendered (post_money_valuation_cap == 8_000_000 -> "$8.00M").
        assert "$8.00M" in report_md
        assert "Angel A" in report_md

        # Must NOT contain ownership/dilution/holder-table math — there is no equity base.
        assert "Fully Diluted" not in report_md
        assert "Ownership %" not in report_md
        assert "Cap Table" not in report_md

    def test_no_instruments_still_produces_all_outputs(self, tmp_path: Any) -> None:
        """Zero instruments is a degenerate-but-valid input; the renderer must not crash."""
        empty_instruments = {
            "safes": [],
            "convertible_notes": [],
            "warrants": [],
            "option_grants": [],
            "metadata": {"run_id": "test", "schema_version": "v0.5.0-instruments"},
        }
        inputs_path = tmp_path / "inputs.json"
        instr_path = tmp_path / "instruments.json"
        inputs_path.write_text(json.dumps(_MINIMAL_INPUTS))
        instr_path.write_text(json.dumps(empty_instruments))

        review_dir = tmp_path / "cap-table-acmecorp-extraction"
        rc, _stdout, stderr = _run_cli(str(inputs_path), str(instr_path), str(review_dir))
        assert rc == 0, f"stderr: {stderr}"
        assert (review_dir / "extraction_only.json").exists()
        assert (review_dir / "report_extraction_only.md").exists()


class TestNullFieldRendering:
    """F2a — a null field must never render as an affirmative claim of absence."""

    def test_cap_implying_safe_form_with_null_cap_shows_neutral_marker_not_uncapped(self, tmp_path: Any) -> None:
        safe = dict(_SAFE_ONLY)
        safe["post_money_valuation_cap"] = None
        safe["pre_money_valuation_cap"] = None
        safe["form"] = "yc_postmoney_cap"  # cap-implying form
        instruments = {
            "safes": [safe],
            "convertible_notes": [],
            "warrants": [],
            "option_grants": [],
            "metadata": {"run_id": "test", "schema_version": "v0.5.0-instruments"},
        }
        inputs_path = tmp_path / "inputs.json"
        instr_path = tmp_path / "instruments.json"
        inputs_path.write_text(json.dumps(_MINIMAL_INPUTS))
        instr_path.write_text(json.dumps(instruments))

        review_dir = tmp_path / "cap-table-acmecorp-extraction"
        rc, _stdout, stderr = _run_cli(str(inputs_path), str(instr_path), str(review_dir))
        assert rc == 0, f"stderr: {stderr}"

        report_md = (review_dir / "report_extraction_only.md").read_text()
        assert cer.NEUTRAL_MARKER in report_md
        assert "uncapped" not in report_md.lower()

    def test_uncapped_mfn_safe_form_with_null_cap_shows_affirmative_uncapped(self, tmp_path: Any) -> None:
        safe = dict(_SAFE_ONLY)
        safe["post_money_valuation_cap"] = None
        safe["pre_money_valuation_cap"] = None
        safe["form"] = "yc_uncapped_mfn"
        # Non-null discount so the neutral-marker assertion below is isolated
        # to the cap column (the discount column is null-rendered elsewhere).
        safe["discount_multiplier"] = 0.8
        instruments = {
            "safes": [safe],
            "convertible_notes": [],
            "warrants": [],
            "option_grants": [],
            "metadata": {"run_id": "test", "schema_version": "v0.5.0-instruments"},
        }
        inputs_path = tmp_path / "inputs.json"
        instr_path = tmp_path / "instruments.json"
        inputs_path.write_text(json.dumps(_MINIMAL_INPUTS))
        instr_path.write_text(json.dumps(instruments))

        review_dir = tmp_path / "cap-table-acmecorp-extraction"
        rc, _stdout, stderr = _run_cli(str(inputs_path), str(instr_path), str(review_dir))
        assert rc == 0, f"stderr: {stderr}"

        report_md = (review_dir / "report_extraction_only.md").read_text()
        assert "uncapped (per form)" in report_md
        assert cer.NEUTRAL_MARKER not in report_md

    def test_note_with_null_cap_shows_neutral_marker_never_uncapped(self, tmp_path: Any) -> None:
        note = {
            "id": "note_001",
            "investor_name": "Bridge Fund",
            "principal": 250_000,
            "annual_interest_rate": 0.06,
            "interest_rate_type": "fixed_numeric",
            "interest_converts_to_shares": True,
            "issuance_date": "2025-02-01",
            "valuation_cap": None,
            "discount_multiplier": None,
            "maturity_date": None,
            "extraction_confidence": "high",
        }
        instruments = {
            "safes": [],
            "convertible_notes": [note],
            "warrants": [],
            "option_grants": [],
            "metadata": {"run_id": "test", "schema_version": "v0.5.0-instruments"},
        }
        inputs_path = tmp_path / "inputs.json"
        instr_path = tmp_path / "instruments.json"
        inputs_path.write_text(json.dumps(_MINIMAL_INPUTS))
        instr_path.write_text(json.dumps(instruments))

        review_dir = tmp_path / "cap-table-acmecorp-extraction"
        rc, _stdout, stderr = _run_cli(str(inputs_path), str(instr_path), str(review_dir))
        assert rc == 0, f"stderr: {stderr}"

        report_md = (review_dir / "report_extraction_only.md").read_text()
        assert "uncapped" not in report_md.lower()
        assert '"none"' not in report_md
        # neutral marker must appear at least 3x: cap, discount, maturity
        assert report_md.count(cer.NEUTRAL_MARKER) >= 3

    def test_null_discount_shows_neutral_marker_not_none(self, tmp_path: Any) -> None:
        safe = dict(_SAFE_ONLY)  # discount_multiplier already None
        instruments = {
            "safes": [safe],
            "convertible_notes": [],
            "warrants": [],
            "option_grants": [],
            "metadata": {"run_id": "test", "schema_version": "v0.5.0-instruments"},
        }
        inputs_path = tmp_path / "inputs.json"
        instr_path = tmp_path / "instruments.json"
        inputs_path.write_text(json.dumps(_MINIMAL_INPUTS))
        instr_path.write_text(json.dumps(instruments))

        review_dir = tmp_path / "cap-table-acmecorp-extraction"
        rc, _stdout, stderr = _run_cli(str(inputs_path), str(instr_path), str(review_dir))
        assert rc == 0, f"stderr: {stderr}"

        report_md = (review_dir / "report_extraction_only.md").read_text()
        assert cer.NEUTRAL_MARKER in report_md
        # The old rendering put a bare "none" in the discount cell; that must
        # be gone (the neutral marker's own text doesn't contain "none").
        assert "| none |" not in report_md.lower()


class TestAuditEnrichment:
    """F2b — optional --audit enrichment; must be graceful when absent/invalid."""

    def test_audit_ambiguity_reason_appears_next_to_null_field(self, tmp_path: Any) -> None:
        safe = dict(_SAFE_ONLY)
        safe["post_money_valuation_cap"] = None
        safe["pre_money_valuation_cap"] = None
        safe["form"] = "yc_postmoney_cap"
        instruments = {
            "safes": [safe],
            "convertible_notes": [],
            "warrants": [],
            "option_grants": [],
            "metadata": {"run_id": "test", "schema_version": "v0.5.0-instruments"},
        }
        inputs_path = tmp_path / "inputs.json"
        instr_path = tmp_path / "instruments.json"
        inputs_path.write_text(json.dumps(_MINIMAL_INPUTS))
        instr_path.write_text(json.dumps(instruments))

        audit_path = tmp_path / "extraction_audit.json"
        reason = "defined in a separate Purchase Agreement not included in this upload"
        audit_path.write_text(json.dumps({"ambiguities": [{"field": "valuation_cap", "reason": reason}]}))

        review_dir = tmp_path / "cap-table-acmecorp-extraction"
        res = subprocess.run(
            [
                sys.executable,
                os.path.join(SCRIPTS, "compose_extraction_report.py"),
                "--inputs",
                str(inputs_path),
                "--instruments",
                str(instr_path),
                "--review-dir",
                str(review_dir),
                "--run-id",
                "testrun01",
                "--audit",
                str(audit_path),
                "--pretty",
            ],
            capture_output=True,
            text=True,
        )
        assert res.returncode == 0, f"stderr: {res.stderr}"

        report_md = (review_dir / "report_extraction_only.md").read_text()
        assert cer.NEUTRAL_MARKER in report_md
        assert reason in report_md

    def test_missing_audit_flag_still_succeeds_with_neutral_marker(self, tmp_path: Any) -> None:
        """Without --audit, the renderer must still succeed (F2a stands alone)."""
        safe = dict(_SAFE_ONLY)
        safe["post_money_valuation_cap"] = None
        safe["pre_money_valuation_cap"] = None
        safe["form"] = "yc_postmoney_cap"
        instruments = {
            "safes": [safe],
            "convertible_notes": [],
            "warrants": [],
            "option_grants": [],
            "metadata": {"run_id": "test", "schema_version": "v0.5.0-instruments"},
        }
        inputs_path = tmp_path / "inputs.json"
        instr_path = tmp_path / "instruments.json"
        inputs_path.write_text(json.dumps(_MINIMAL_INPUTS))
        instr_path.write_text(json.dumps(instruments))

        review_dir = tmp_path / "cap-table-acmecorp-extraction"
        rc, _stdout, stderr = _run_cli(str(inputs_path), str(instr_path), str(review_dir))
        assert rc == 0, f"stderr: {stderr}"

        report_md = (review_dir / "report_extraction_only.md").read_text()
        assert cer.NEUTRAL_MARKER in report_md

    def test_nonexistent_audit_path_does_not_hard_fail(self, tmp_path: Any) -> None:
        inputs_path = tmp_path / "inputs.json"
        instr_path = tmp_path / "instruments.json"
        inputs_path.write_text(json.dumps(_MINIMAL_INPUTS))
        instr_path.write_text(json.dumps(_INSTRUMENTS_ONE_SAFE))

        review_dir = tmp_path / "cap-table-acmecorp-extraction"
        res = subprocess.run(
            [
                sys.executable,
                os.path.join(SCRIPTS, "compose_extraction_report.py"),
                "--inputs",
                str(inputs_path),
                "--instruments",
                str(instr_path),
                "--review-dir",
                str(review_dir),
                "--run-id",
                "testrun01",
                "--audit",
                str(tmp_path / "does-not-exist.json"),
                "--pretty",
            ],
            capture_output=True,
            text=True,
        )
        assert res.returncode == 0, f"stderr: {res.stderr}"
        assert (review_dir / "report_extraction_only.md").exists()

    def test_malformed_audit_json_does_not_hard_fail(self, tmp_path: Any) -> None:
        inputs_path = tmp_path / "inputs.json"
        instr_path = tmp_path / "instruments.json"
        inputs_path.write_text(json.dumps(_MINIMAL_INPUTS))
        instr_path.write_text(json.dumps(_INSTRUMENTS_ONE_SAFE))

        audit_path = tmp_path / "extraction_audit.json"
        audit_path.write_text("{not valid json")

        review_dir = tmp_path / "cap-table-acmecorp-extraction"
        res = subprocess.run(
            [
                sys.executable,
                os.path.join(SCRIPTS, "compose_extraction_report.py"),
                "--inputs",
                str(inputs_path),
                "--instruments",
                str(instr_path),
                "--review-dir",
                str(review_dir),
                "--run-id",
                "testrun01",
                "--audit",
                str(audit_path),
                "--pretty",
            ],
            capture_output=True,
            text=True,
        )
        assert res.returncode == 0, f"stderr: {res.stderr}"

    def test_audit_file_with_no_ambiguities_key_is_noop(self, tmp_path: Any) -> None:
        inputs_path = tmp_path / "inputs.json"
        instr_path = tmp_path / "instruments.json"
        inputs_path.write_text(json.dumps(_MINIMAL_INPUTS))
        instr_path.write_text(json.dumps(_INSTRUMENTS_ONE_SAFE))

        audit_path = tmp_path / "extraction_audit.json"
        audit_path.write_text(json.dumps({"something_else": []}))

        review_dir = tmp_path / "cap-table-acmecorp-extraction"
        res = subprocess.run(
            [
                sys.executable,
                os.path.join(SCRIPTS, "compose_extraction_report.py"),
                "--inputs",
                str(inputs_path),
                "--instruments",
                str(instr_path),
                "--review-dir",
                str(review_dir),
                "--run-id",
                "testrun01",
                "--audit",
                str(audit_path),
                "--pretty",
            ],
            capture_output=True,
            text=True,
        )
        assert res.returncode == 0, f"stderr: {res.stderr}"


class TestExtractionOnlySentinelSchema:
    def test_sentinel_validates_against_extraction_only_schema(self) -> None:
        try:
            import jsonschema  # type: ignore[import-untyped]
        except ImportError:
            pytest.skip("jsonschema not installed")

        sentinel = cer.compose_extraction_report(
            company_name="Acmecorp",
            inputs=_MINIMAL_INPUTS,
            instruments=_INSTRUMENTS_ONE_SAFE,
            run_id_override="testrun01",
        )
        sentinel.pop("_report_md", None)
        sentinel.pop("_coverage_disclosure", None)
        sentinel["extraction_report_path"] = "/tmp/test_report_extraction_only.md"

        assert sentinel["schema_version"] == "v0.1.0-cap-table-extraction-only"
        assert sentinel["mode"] == "extraction_only"
        assert sentinel["produces_canonical_artifacts"] is False
        assert sentinel["instruments_summary"] == {"safes": 1, "convertible_notes": 0, "warrants": 0}

        schema_path = os.path.join(SCHEMAS, "extraction_only.schema.json")
        with open(schema_path) as f:
            schema = json.load(f)
        jsonschema.validate(instance=sentinel, schema=schema)

    def test_coverage_disclosure_validates_against_extended_schema(self) -> None:
        try:
            import jsonschema  # type: ignore[import-untyped]
        except ImportError:
            pytest.skip("jsonschema not installed")

        sentinel = cer.compose_extraction_report(
            company_name="Acmecorp",
            inputs=_MINIMAL_INPUTS,
            instruments=_INSTRUMENTS_ONE_SAFE,
            run_id_override="testrun01",
        )
        coverage_disclosure = sentinel["_coverage_disclosure"]
        assert coverage_disclosure["computation_method"] == "extraction_only"
        assert coverage_disclosure["covered"] is False
        assert coverage_disclosure["counsel_review"] is True
        assert coverage_disclosure["uncovered_parts"] == ["equity_base"]

        schema_path = os.path.join(SCHEMAS, "coverage-disclosure.schema.json")
        with open(schema_path) as f:
            schema = json.load(f)
        jsonschema.validate(instance=coverage_disclosure, schema=schema)

    def test_extraction_only_schema_and_coverage_schema_are_valid_json(self) -> None:
        for name in ("extraction_only.schema.json", "coverage-disclosure.schema.json"):
            with open(os.path.join(SCHEMAS, name)) as f:
                json.load(f)  # must not raise
