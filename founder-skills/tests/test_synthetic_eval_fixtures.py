"""earlier work — sanity tests for the structurally-mutated synthetic eval fixtures.

These tests verify the fixtures are loadable, paired correctly, and reach
the verification pipeline cleanly. They do NOT spawn LLM sub-agents
(those are CI cost). They DO check that the static guardrails (validate_safe,
invariant_checker, evidence_verifier with --doc-text) behave correctly
against the synthetic ground truth.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES_DIR = REPO_ROOT / "founder-skills" / "tests" / "fixtures" / "cap-table-eval"
sys.path.insert(0, str(REPO_ROOT / "founder-skills" / "skills" / "cap-table" / "scripts"))


def _pair_paths() -> list[tuple[str, Path, Path]]:
    """Find all (source, label) fixture pairs."""
    pairs = []
    for src in sorted(FIXTURES_DIR.glob("*__source.txt")):
        scenario = src.name.replace("__source.txt", "")
        label = FIXTURES_DIR / f"{scenario}__label.json"
        if label.exists():
            pairs.append((scenario, src, label))
    return pairs


def test_fixtures_exist_and_pair() -> None:
    pairs = _pair_paths()
    assert len(pairs) >= 5, f"Expected at least 5 fixture pairs, found {len(pairs)}"
    for _scenario, src, label in pairs:
        assert src.exists()
        assert label.exists()


@pytest.mark.parametrize("scenario_data", _pair_paths(), ids=lambda x: x[0])
def test_label_schema_well_formed(scenario_data: tuple[str, Path, Path]) -> None:
    _scenario, _src, label_path = scenario_data
    label = json.loads(label_path.read_text())
    assert "id" in label
    assert "scenario" in label
    assert "instrument_type" in label
    assert "fields" in label
    assert isinstance(label["fields"], dict)


def test_template_blank_label_has_null_exclusivity() -> None:
    """Critical regression: exclusivity_days must be null in the template-blank
    archetype fixture. This is the canonical hallucination class."""
    label = json.loads((FIXTURES_DIR / "template_blank_exclusivity__label.json").read_text())
    assert label["fields"]["exclusivity_days"] is None


def test_cap_plus_discount_label_uses_canonical_enum() -> None:
    label = json.loads((FIXTURES_DIR / "cap_plus_discount_clean__label.json").read_text())
    assert label["fields"]["form"] == "cap_plus_discount"  # not post_money_cap_and_discount


def test_pre_money_legacy_label_uses_canonical_enum() -> None:
    label = json.loads((FIXTURES_DIR / "pre_money_cap_only_legacy__label.json").read_text())
    assert label["fields"]["form"] == "yc_premoney_cap_only"


def test_gotcha3_multiplier_form_label() -> None:
    label = json.loads((FIXTURES_DIR / "gotcha3_multiplier_form__label.json").read_text())
    # "Discount Rate is 80%" with X>=50 → multiplier form, NOT rate form
    assert label["fields"]["discount_multiplier"] == 0.80


def test_ita_3j_label_has_null_rate() -> None:
    label = json.loads((FIXTURES_DIR / "ita_section_3j__label.json").read_text())
    assert label["fields"]["annual_interest_rate"] is None
    assert label["fields"]["interest_rate_type"] == "statutory_ita_section_3j"


@pytest.mark.parametrize("scenario_data", _pair_paths(), ids=lambda x: x[0])
def test_fixture_passes_invariant_checker(scenario_data: tuple[str, Path, Path]) -> None:
    """All canonical labels must pass invariant_checker (no false positives
    against well-formed ground truth)."""
    from invariant_checker import check_instrument  # type: ignore[import-not-found]

    _scenario, _src, label_path = scenario_data
    label = json.loads(label_path.read_text())
    extraction = {
        "instrument_type": label["instrument_type"],
        "fields": label["fields"],
    }
    report = check_instrument(extraction)
    assert report.n_hard_violations == 0, (
        f"{label['scenario']}: hard invariant violation in canonical label — "
        f"either fixture is wrong or invariant_checker has a bug. "
        f"Violations: {[v.reason for v in report.violations]}"
    )


@pytest.mark.parametrize("scenario_data", _pair_paths(), ids=lambda x: x[0])
def test_fixture_evidence_quote_findable_in_source(scenario_data: tuple[str, Path, Path]) -> None:
    """For each canonical label, key numeric/string values should be findable
    in the synthetic source (evidence_verifier's value_in_doc gate)."""
    from evidence_verifier import value_in_doc_check  # type: ignore[import-not-found]

    _scenario, src_path, label_path = scenario_data
    label = json.loads(label_path.read_text())
    source = src_path.read_text()

    # Check a subset of high-stakes fields
    HIGH_STAKES = {
        "purchase_amount",
        "post_money_valuation_cap",
        "pre_money_valuation_cap",
        "discount_multiplier",
        "principal",
        "investment_amount",
        "pre_money_valuation",
    }
    for fname, value in label["fields"].items():
        if fname not in HIGH_STAKES:
            continue
        if value is None:
            continue
        passed, reason = value_in_doc_check(value, source)
        assert passed, (
            f"{label['scenario']}: value_in_doc failed for {fname}={value!r}; "
            f"reason: {reason}. Fixture may have value-source mismatch."
        )
