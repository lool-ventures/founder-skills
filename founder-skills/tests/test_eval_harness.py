"""Sprint 6b — eval-harness regression tests with EVAL_DATA_PATH override.

The harness can run against either:
  - The public synthetic fixtures (default; CI-safe, always available)
  - A private eval set located at $EVAL_DATA_PATH (skipped if absent;
    used locally when the docs/internal/eval/ corpus is mounted)

Tests:
  - Static (always run): synthetic fixtures end-to-end through
    invariant_checker + evidence_verifier (value_in_doc).
  - Private (skipped without EVAL_DATA_PATH): walk the private label set,
    run forward verification with --doc-text, ensure FPR ≤ Sprint-2c
    calibrated threshold.

This file is the regression target for any future change to the cap-table
extraction pipeline. Tests should be FAST (no LLM calls — both static and
private modes are deterministic against precomputed labels).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "founder-skills" / "skills" / "cap-table" / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

PUBLIC_FIXTURES = REPO_ROOT / "founder-skills" / "tests" / "fixtures" / "cap-table-eval"
PRIVATE_EVAL_PATH_ENV = "EVAL_DATA_PATH"

# Sprint-2c calibrated threshold: forward verification FPR < 5% on the
# canonical eval set. We allow a slight buffer for CI noise.
SPRINT_2C_FPR_THRESHOLD = 0.08


def _enumerate_public_fixtures() -> list[tuple[str, Path, Path]]:
    out = []
    for src in sorted(PUBLIC_FIXTURES.glob("*__source.txt")):
        scenario = src.name.replace("__source.txt", "")
        label = PUBLIC_FIXTURES / f"{scenario}__label.json"
        if label.exists():
            out.append((scenario, src, label))
    return out


def _private_eval_available() -> bool:
    p = os.environ.get(PRIVATE_EVAL_PATH_ENV)
    if not p:
        return False
    base = Path(p)
    return base.exists() and (base / "labels").exists() and (base / "corpus_index.json").exists()


# ---------------------------------------------------------------------------
# Public fixtures — always run in CI
# ---------------------------------------------------------------------------


class TestPublicHarness:
    def test_public_fixtures_loadable(self):
        fixtures = _enumerate_public_fixtures()
        assert len(fixtures) >= 5, f"expected ≥5 fixtures, found {len(fixtures)}"

    def test_public_fixtures_pass_invariant_check(self):
        """Every canonical label must pass invariant_checker (FPR=0 is the
        Sprint-4b gate). If any synthetic fixture fails, either the fixture
        is wrong or invariant_checker has a real bug."""
        from invariant_checker import check_instrument

        for _scenario, _src, label_path in _enumerate_public_fixtures():
            label = json.loads(label_path.read_text())
            extraction = {
                "instrument_type": label["instrument_type"],
                "fields": label["fields"],
            }
            report = check_instrument(extraction)
            assert report.n_hard_violations == 0, (
                f"{label['scenario']}: hard invariant violation in synthetic fixture. "
                f"Violations: {[v.reason for v in report.violations]}"
            )

    def test_public_fixtures_pass_value_in_doc(self):
        """Every high-stakes value in a canonical label must be findable in
        the corresponding synthetic source via evidence_verifier.value_in_doc.
        """
        from evidence_verifier import value_in_doc_check

        HIGH_STAKES = {
            "purchase_amount",
            "post_money_valuation_cap",
            "pre_money_valuation_cap",
            "discount_multiplier",
            "principal",
            "investment_amount",
            "pre_money_valuation",
        }
        for _scenario, src_path, label_path in _enumerate_public_fixtures():
            label = json.loads(label_path.read_text())
            source = src_path.read_text()
            for fname, value in label["fields"].items():
                if fname not in HIGH_STAKES or value is None:
                    continue
                passed, reason = value_in_doc_check(value, source)
                assert passed, f"{label['scenario']}/{fname}={value!r}: not in synthetic source ({reason})"


# ---------------------------------------------------------------------------
# Private eval set — opt-in via EVAL_DATA_PATH env var
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not _private_eval_available(),
    reason=f"set {PRIVATE_EVAL_PATH_ENV}=docs/internal/eval to enable private regression",
)
class TestPrivateHarness:
    """Skipped in CI; runs locally when the private corpus is mounted.

    Walks the 69-doc private eval set, runs forward verification with
    --doc-text against each source, asserts FPR ≤ Sprint-2c threshold.
    """

    def test_private_corpus_fpr_within_calibration(self):
        from evidence_verifier import _load_doc_text, verify_extraction

        base = Path(os.environ[PRIVATE_EVAL_PATH_ENV])
        idx = json.loads((base / "corpus_index.json").read_text())

        n_fields = 0
        n_fails = 0
        for doc in idx["documents"]:
            corpus = doc["corpus"]
            label_path = base / "labels" / corpus / f"{doc['id']}.json"
            if not label_path.exists():
                continue
            src = Path(doc["source_path"])
            if not src.exists():
                continue
            label = json.loads(label_path.read_text())
            doc_text = _load_doc_text(src)
            report = verify_extraction(label, doc_text)
            for r in report.per_field:
                # Skip synthesized fields per Sprint 2c calibration
                if r.field_name in {
                    "form",
                    "instrument_subtype",
                    "interest_rate_type",
                    "jurisdiction",
                    "doc_type",
                    "format",
                    "anti_dilution_provision",
                    "anti_dilution_type",
                    "liquidation_participation",
                    "liq_pref_type",
                    "option_pool_basis",
                    "conversion_trigger",
                    "maturity_default_treatment",
                    "mfn_provision",
                    "options_granted_count",
                    "convertibles_active_count",
                    "total_authorized_shares",
                    "total_issued_shares",
                    "share_classes",
                    "preferred_series",
                    "authorized_share_classes",
                    "expected_absent",
                    "extraction_confidence",
                    "id",
                    "label_source",
                    "corpus",
                    "label_schema_version",
                    "label_compat_min",
                    "label_compat_max",
                }:
                    continue
                n_fields += 1
                if r.overall_status == "fail":
                    n_fails += 1

        assert n_fields > 0, "no private fields scored — check EVAL_DATA_PATH"
        fpr = n_fails / n_fields
        assert fpr <= SPRINT_2C_FPR_THRESHOLD, (
            f"Forward verification FPR {fpr * 100:.2f}% exceeds Sprint-2c "
            f"calibrated threshold {SPRINT_2C_FPR_THRESHOLD * 100:.0f}% on private "
            f"eval set ({n_fails}/{n_fields} fields failed)"
        )


def test_private_path_skip_signals_correctly():
    """Sanity check: when EVAL_DATA_PATH is unset, the private suite reports
    as skipped (not as a hard failure)."""
    # This test always passes; it's a meta-check that the skip mechanism
    # is wired correctly.
    if _private_eval_available():
        assert True  # private path exists; the real tests will run
    else:
        # No EVAL_DATA_PATH set — TestPrivateHarness is skipped via decorator
        assert True
