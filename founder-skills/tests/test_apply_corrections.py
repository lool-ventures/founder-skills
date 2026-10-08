# founder-skills/tests/test_apply_corrections.py
"""Tests for apply_corrections.py — post-processing of founder review corrections."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from typing import Any

import pytest

_SCRIPTS = os.path.join(
    os.path.dirname(__file__),
    "..",
    "skills",
    "financial-model-review",
    "scripts",
)
_SCRIPT = os.path.join(_SCRIPTS, "apply_corrections.py")

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_ORIGINAL: dict[str, Any] = {
    "company": {
        "company_name": "TestCo",
        "slug": "testco",
        "stage": "seed",
        "sector": "B2B SaaS",
        "geography": "Israel",
    },
    "revenue": {
        "mrr": {"value": 50000, "as_of": "2026-01"},
        "customers": 100,
        "growth_rate_monthly": 0.1,
        "monthly": [{"month": "2026-01", "total": 50000, "actual": True}],
    },
    "cash": {"current_balance": 1000000, "monthly_net_burn": 80000, "balance_date": "2026-01"},
    "metadata": {
        "run_id": "20260309T120000Z",
        "warning_overrides": [
            {
                "code": "BURN_MULTIPLE_SUSPECT",
                "field": "",
                "reason": "Verified",
                "reviewed_by": "agent",
                "timestamp": "2026-03-09T12:00:00Z",
            }
        ],
    },
    "israel_specific": {"fx_rate_ils_usd": 3.6},
}


def _compute_hash(data: dict[str, Any]) -> str:
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()


def _run(
    corrections_data: dict[str, Any],
    original_data: dict[str, Any],
    extra_args: list[str] | None = None,
) -> tuple[int, dict[str, Any], dict[str, Any] | None, dict[str, Any] | None]:
    """Write temp files, run apply_corrections.py, return (exit_code, stdout, files)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        corr_path = os.path.join(tmpdir, "corrections.json")
        orig_path = os.path.join(tmpdir, "inputs.json")
        with open(corr_path, "w") as f:
            json.dump(corrections_data, f)
        with open(orig_path, "w") as f:
            json.dump(original_data, f)

        cmd = [sys.executable, _SCRIPT, corr_path, "--original", orig_path, "--output-dir", tmpdir]
        if extra_args:
            cmd.extend(extra_args)
        result = subprocess.run(cmd, capture_output=True, text=True)

        corrected_path = os.path.join(tmpdir, "corrected_inputs.json")
        audit_path = os.path.join(tmpdir, "extraction_corrections.json")
        corrected = None
        audit = None
        if os.path.exists(corrected_path):
            with open(corrected_path) as f:
                corrected = json.load(f)
        if os.path.exists(audit_path):
            with open(audit_path) as f:
                audit = json.load(f)

        stdout = {}
        if result.stdout.strip():
            with contextlib.suppress(json.JSONDecodeError):
                stdout = json.loads(result.stdout)

        return result.returncode, stdout, corrected, audit


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestApplyCorrections:
    def test_basic_round_trip(self) -> None:
        """Corrections applied, both files written, stdout reports success."""
        payload = {
            "corrections": [{"path": "revenue.mrr.value", "was": 50000, "now": 75000, "label": "MRR"}],
            "corrected": {
                **_ORIGINAL,
                "revenue": {**_ORIGINAL["revenue"], "mrr": {"value": "75000", "as_of": "2026-01"}},
            },
            "warning_overrides": [],
            "ils_fields": {},
        }
        rc, stdout, corrected, audit = _run(payload, _ORIGINAL)
        assert rc == 0
        assert stdout["status"] == "completed"
        assert stdout["correction_count"] == 1
        assert corrected is not None
        assert corrected["revenue"]["mrr"]["value"] == 75000  # coerced to int
        assert audit is not None
        assert audit["correction_count"] == 1

    def test_coercion_string_to_number(self) -> None:
        """String numeric values coerced to int/float."""
        payload = {
            "corrections": [],
            "corrected": {
                **_ORIGINAL,
                "cash": {**_ORIGINAL["cash"], "current_balance": "1500000", "monthly_net_burn": "90000.50"},
            },
            "warning_overrides": [],
            "ils_fields": {},
        }
        rc, stdout, corrected, audit = _run(payload, _ORIGINAL)
        assert rc == 0
        assert corrected is not None
        assert corrected["cash"]["current_balance"] == 1500000
        assert corrected["cash"]["monthly_net_burn"] == 90000.50

    def test_coercion_error_exits_nonzero(self) -> None:
        """Non-numeric string in numeric field → exit 1, no files written."""
        payload = {
            "corrections": [],
            "corrected": {**_ORIGINAL, "cash": {**_ORIGINAL["cash"], "current_balance": "not-a-number"}},
            "warning_overrides": [],
            "ils_fields": {},
        }
        rc, stdout, corrected, audit = _run(payload, _ORIGINAL)
        assert rc == 1
        assert corrected is None  # file not written
        assert "errors" in stdout

    def test_ils_normalization(self) -> None:
        """ILS-tagged fields divided by fx_rate."""
        payload = {
            "corrections": [],
            "corrected": {**_ORIGINAL, "cash": {**_ORIGINAL["cash"], "current_balance": 3600000}},
            "warning_overrides": [],
            "ils_fields": {"cash.current_balance": True},
        }
        rc, stdout, corrected, audit = _run(payload, _ORIGINAL)
        assert rc == 0
        assert corrected is not None
        assert corrected["cash"]["current_balance"] == 1000000  # 3600000 / 3.6

    def test_time_series_canonicalization(self) -> None:
        """Monthly entries sorted by month."""
        payload = {
            "corrections": [],
            "corrected": {
                **_ORIGINAL,
                "revenue": {
                    **_ORIGINAL["revenue"],
                    "monthly": [
                        {"month": "2026-03", "total": 70000, "actual": True},
                        {"month": "2026-01", "total": 50000, "actual": True},
                        {"month": "2026-02", "total": 60000, "actual": True},
                    ],
                },
            },
            "warning_overrides": [],
            "ils_fields": {},
        }
        rc, stdout, corrected, audit = _run(payload, _ORIGINAL)
        assert rc == 0
        assert corrected is not None
        months = [e["month"] for e in corrected["revenue"]["monthly"]]
        assert months == ["2026-01", "2026-02", "2026-03"]

    def test_invalid_time_series_date_exits_nonzero(self) -> None:
        """Malformed YYYY-MM in time series → exit 1."""
        payload = {
            "corrections": [],
            "corrected": {
                **_ORIGINAL,
                "revenue": {**_ORIGINAL["revenue"], "monthly": [{"month": "Jan-2026", "total": 50000, "actual": True}]},
            },
            "warning_overrides": [],
            "ils_fields": {},
        }
        rc, stdout, corrected, audit = _run(payload, _ORIGINAL)
        assert rc == 1
        assert corrected is None

    def test_override_merge_preserves_agent(self) -> None:
        """Founder override does not replace existing agent override."""
        payload = {
            "corrections": [],
            "corrected": {**_ORIGINAL},
            "warning_overrides": [
                {
                    "code": "BURN_MULTIPLE_SUSPECT",
                    "field": "",
                    "reason": "Founder says ok",
                    "reviewed_by": "founder",
                    "timestamp": "2026-03-09T13:00:00Z",
                }
            ],
            "ils_fields": {},
        }
        rc, stdout, corrected, audit = _run(payload, _ORIGINAL)
        assert rc == 0
        assert corrected is not None
        overrides = corrected["metadata"]["warning_overrides"]
        bm = [o for o in overrides if o["code"] == "BURN_MULTIPLE_SUSPECT"]
        assert len(bm) == 1
        assert bm[0]["reviewed_by"] == "agent"  # not downgraded

    def test_override_merge_adds_new(self) -> None:
        """New founder override added alongside existing agent override."""
        payload = {
            "corrections": [],
            "corrected": {**_ORIGINAL},
            "warning_overrides": [
                {
                    "code": "ARPU_SUSPECT",
                    "field": "",
                    "reason": "Checked manually",
                    "reviewed_by": "founder",
                    "timestamp": "2026-03-09T13:00:00Z",
                }
            ],
            "ils_fields": {},
        }
        rc, stdout, corrected, audit = _run(payload, _ORIGINAL)
        assert rc == 0
        assert corrected is not None
        overrides = corrected["metadata"]["warning_overrides"]
        codes = [o["code"] for o in overrides]
        assert "BURN_MULTIPLE_SUSPECT" in codes  # preserved
        assert "ARPU_SUSPECT" in codes  # added

    def test_run_id_preserved(self) -> None:
        """Original metadata.run_id preserved in output."""
        # Remove run_id from corrected to test preservation
        corrected_input: dict[str, Any] = {**_ORIGINAL, "metadata": {}}
        payload: dict[str, Any] = {
            "corrections": [],
            "corrected": corrected_input,
            "warning_overrides": [],
            "ils_fields": {},
        }
        rc, stdout, corrected, audit = _run(payload, _ORIGINAL)
        assert rc == 0
        assert corrected is not None
        assert corrected["metadata"]["run_id"] == "20260309T120000Z"

    def test_row_ids_stripped(self) -> None:
        """_row_id keys removed from array entries before saving."""
        payload = {
            "corrections": [],
            "corrected": {
                **_ORIGINAL,
                "revenue": {
                    **_ORIGINAL["revenue"],
                    "monthly": [{"month": "2026-01", "total": 50000, "actual": True, "_row_id": "abc-123"}],
                },
            },
            "warning_overrides": [],
            "ils_fields": {},
        }
        rc, stdout, corrected, audit = _run(payload, _ORIGINAL)
        assert rc == 0
        assert corrected is not None
        assert "_row_id" not in corrected["revenue"]["monthly"][0]

    def test_boolean_coercion_in_time_series(self) -> None:
        """String 'true'/'false' in actual field coerced to boolean."""
        payload = {
            "corrections": [],
            "corrected": {
                **_ORIGINAL,
                "revenue": {
                    **_ORIGINAL["revenue"],
                    "monthly": [{"month": "2026-01", "total": 50000, "actual": "true"}],
                },
            },
            "warning_overrides": [],
            "ils_fields": {},
        }
        rc, stdout, corrected, audit = _run(payload, _ORIGINAL)
        assert rc == 0
        assert corrected is not None
        assert corrected["revenue"]["monthly"][0]["actual"] is True

    def test_audit_trail_structure(self) -> None:
        """extraction_corrections.json has expected structure."""
        payload = {
            "corrections": [{"path": "revenue.mrr.value", "was": 50000, "now": 75000, "label": "MRR"}],
            "corrected": {
                **_ORIGINAL,
                "revenue": {**_ORIGINAL["revenue"], "mrr": {"value": 75000, "as_of": "2026-01"}},
            },
            "warning_overrides": [
                {
                    "code": "ARPU_SUSPECT",
                    "field": "",
                    "reason": "OK",
                    "reviewed_by": "founder",
                    "timestamp": "2026-03-09T13:00:00Z",
                }
            ],
            "ils_fields": {},
        }
        rc, stdout, corrected, audit = _run(payload, _ORIGINAL)
        assert rc == 0
        assert audit is not None
        assert "timestamp" in audit
        assert audit["source_file"] == "inputs.json"
        assert audit["correction_count"] == 1
        assert len(audit["corrections"]) == 1
        assert audit["override_count"] == 1

    def test_zero_corrections_still_writes(self) -> None:
        """Even with 0 corrections, files are written (may have overrides)."""
        payload = {
            "corrections": [],
            "corrected": {**_ORIGINAL},
            "warning_overrides": [],
            "ils_fields": {},
        }
        rc, stdout, corrected, audit = _run(payload, _ORIGINAL)
        assert rc == 0
        assert corrected is not None
        assert audit is not None
        assert audit["correction_count"] == 0


class TestIntegration:
    def test_round_trip_generate_then_apply(self) -> None:
        """Generate static HTML from inputs, simulate corrections payload, apply."""
        # Step 1: Generate static HTML (verify it works)
        with tempfile.TemporaryDirectory() as tmpdir:
            inputs_path = os.path.join(tmpdir, "inputs.json")
            output_path = os.path.join(tmpdir, "review.html")
            with open(inputs_path, "w") as f:
                json.dump(_ORIGINAL, f)
            gen_result = subprocess.run(
                [
                    sys.executable,
                    os.path.join(_SCRIPTS, "review_inputs.py"),
                    inputs_path,
                    "--static",
                    output_path,
                ],
                capture_output=True,
                text=True,
            )
            assert gen_result.returncode == 0
            with open(output_path) as f:
                html = f.read()
            assert "<!DOCTYPE html>" in html

        # Step 2: Simulate corrections payload (as founder would download)
        corrected_state = json.loads(json.dumps(_ORIGINAL))
        corrected_state["revenue"]["mrr"]["value"] = 75000
        corrected_state["revenue"]["customers"] = 150
        payload = {
            "corrections": [
                {"path": "revenue.mrr.value", "was": 50000, "now": 75000, "label": "MRR"},
                {"path": "revenue.customers", "was": 100, "now": 150, "label": "Customers"},
            ],
            "corrected": corrected_state,
            "warning_overrides": [],
            "ils_fields": {},
        }

        # Step 3: Apply corrections
        rc, stdout, corrected, audit = _run(payload, _ORIGINAL)
        assert rc == 0
        assert corrected is not None
        assert audit is not None
        assert corrected["revenue"]["mrr"]["value"] == 75000
        assert corrected["revenue"]["customers"] == 150
        assert audit["correction_count"] == 2
        assert corrected["metadata"]["run_id"] == "20260309T120000Z"

    def test_round_trip_patch_based(self) -> None:
        """Generate HTML, simulate patch-based corrections, apply."""
        # Step 1: Generate static HTML (verify it works)
        with tempfile.TemporaryDirectory() as tmpdir:
            inputs_path = os.path.join(tmpdir, "inputs.json")
            output_path = os.path.join(tmpdir, "review.html")
            with open(inputs_path, "w") as f:
                json.dump(_ORIGINAL, f)
            gen_result = subprocess.run(
                [
                    sys.executable,
                    os.path.join(_SCRIPTS, "review_inputs.py"),
                    inputs_path,
                    "--static",
                    output_path,
                ],
                capture_output=True,
                text=True,
            )
            assert gen_result.returncode == 0
            with open(output_path) as f:
                html = f.read()
            assert "<!DOCTYPE html>" in html

        # Step 2: Simulate patch-based corrections payload
        payload = {
            "base_hash": _compute_hash(_ORIGINAL),
            "changes": [
                {"path": "revenue.mrr.value", "expected_old": 50000, "new": 75000},
                {"path": "revenue.customers", "expected_old": 100, "new": 150},
            ],
            "warning_overrides": [],
            "ils_fields": {},
        }

        # Step 3: Apply corrections
        rc, stdout, corrected, audit = _run(payload, _ORIGINAL)
        assert rc == 0
        assert corrected is not None
        assert audit is not None
        assert corrected["revenue"]["mrr"]["value"] == 75000
        assert corrected["revenue"]["customers"] == 150
        assert audit["correction_count"] == 2
        assert corrected["metadata"]["run_id"] == "20260309T120000Z"


class TestPatchBasedFlow:
    def test_patch_applies_change(self) -> None:
        """Changes applied via patches, not via corrected object."""
        payload = {
            "base_hash": _compute_hash(_ORIGINAL),
            "changes": [
                {
                    "path": "revenue.mrr.value",
                    "expected_old": 50000,
                    "new": 75000,
                }
            ],
            "warning_overrides": [],
            "ils_fields": {},
        }
        rc, stdout, corrected, audit = _run(payload, _ORIGINAL)
        assert rc == 0
        assert corrected is not None
        assert corrected["revenue"]["mrr"]["value"] == 75000

    def test_patch_stale_base_hash_rejected(self) -> None:
        """Wrong base_hash -> exit 1."""
        payload = {
            "base_hash": "sha256:wrong",
            "changes": [{"path": "revenue.mrr.value", "expected_old": 50000, "new": 75000}],
            "warning_overrides": [],
            "ils_fields": {},
        }
        rc, stdout, corrected, audit = _run(payload, _ORIGINAL)
        assert rc == 1
        assert (
            "stale" in stdout.get("errors", [{}])[0].get("message", "").lower()
            or "hash" in stdout.get("errors", [{}])[0].get("message", "").lower()
        )

    def test_patch_expected_old_mismatch_rejected(self) -> None:
        """expected_old doesn't match -> exit 1."""
        payload = {
            "base_hash": _compute_hash(_ORIGINAL),
            "changes": [{"path": "revenue.mrr.value", "expected_old": 99999, "new": 75000}],
            "warning_overrides": [],
            "ils_fields": {},
        }
        rc, stdout, corrected, audit = _run(payload, _ORIGINAL)
        assert rc == 1

    def test_patch_coerces_string_values(self) -> None:
        """String 'new' values coerced to numbers."""
        payload = {
            "base_hash": _compute_hash(_ORIGINAL),
            "changes": [{"path": "cash.current_balance", "expected_old": 1000000, "new": "1500000"}],
            "warning_overrides": [],
            "ils_fields": {},
        }
        rc, stdout, corrected, audit = _run(payload, _ORIGINAL)
        assert rc == 0
        assert corrected is not None
        assert corrected["cash"]["current_balance"] == 1500000

    def test_patch_multiple_changes(self) -> None:
        """Multiple changes applied in order."""
        payload = {
            "base_hash": _compute_hash(_ORIGINAL),
            "changes": [
                {"path": "revenue.mrr.value", "expected_old": 50000, "new": 75000},
                {"path": "revenue.customers", "expected_old": 100, "new": 150},
            ],
            "warning_overrides": [],
            "ils_fields": {},
        }
        rc, stdout, corrected, audit = _run(payload, _ORIGINAL)
        assert rc == 0
        assert corrected is not None
        assert corrected["revenue"]["mrr"]["value"] == 75000
        assert corrected["revenue"]["customers"] == 150

    def test_patch_missing_base_hash_rejected(self) -> None:
        """Missing base_hash in changes[] payload -> exit 1."""
        payload = {
            "changes": [{"path": "revenue.mrr.value", "expected_old": 50000, "new": 75000}],
            "warning_overrides": [],
            "ils_fields": {},
        }
        rc, stdout, corrected, audit = _run(payload, _ORIGINAL)
        assert rc == 1
        assert stdout.get("errors", [{}])[0].get("code") == "MISSING_BASE_HASH"

    def test_legacy_corrected_payload_still_works(self) -> None:
        """Old-style payload with 'corrected' key still works."""
        payload = {
            "corrections": [{"path": "revenue.mrr.value", "was": 50000, "now": 75000}],
            "corrected": {
                **_ORIGINAL,
                "revenue": {**_ORIGINAL["revenue"], "mrr": {"value": 75000, "as_of": "2026-01"}},
            },
            "warning_overrides": [],
            "ils_fields": {},
        }
        rc, stdout, corrected, audit = _run(payload, _ORIGINAL)
        assert rc == 0
        assert corrected is not None
        assert corrected["revenue"]["mrr"]["value"] == 75000

    def test_patch_audit_trail(self) -> None:
        """Audit trail records changes, not legacy corrections."""
        payload = {
            "base_hash": _compute_hash(_ORIGINAL),
            "changes": [{"path": "revenue.mrr.value", "expected_old": 50000, "new": 75000}],
            "warning_overrides": [],
            "ils_fields": {},
        }
        rc, stdout, corrected, audit = _run(payload, _ORIGINAL)
        assert rc == 0
        assert audit is not None
        assert audit["correction_count"] == 1
        assert audit["corrections"][0]["path"] == "revenue.mrr.value"

    def test_patch_preserves_unmodified_fields(self) -> None:
        """Fields not in changes[] are preserved from original."""
        payload = {
            "base_hash": _compute_hash(_ORIGINAL),
            "changes": [{"path": "revenue.mrr.value", "expected_old": 50000, "new": 75000}],
            "warning_overrides": [],
            "ils_fields": {},
        }
        rc, stdout, corrected, audit = _run(payload, _ORIGINAL)
        assert rc == 0
        assert corrected is not None
        # Unmodified fields preserved exactly
        assert corrected["cash"]["current_balance"] == 1000000
        assert corrected["company"]["company_name"] == "TestCo"

    def test_replace_array_adds_row(self) -> None:
        """replace_array change replaces entire array (e.g., headcount row added)."""
        original_with_hc = {
            **_ORIGINAL,
            "expenses": {
                "headcount": [{"role": "Engineer", "count": 3, "salary_annual": 120000}],
            },
        }
        new_headcount = [
            {"role": "Engineer", "count": 3, "salary_annual": 120000},
            {"role": "Designer", "count": 1, "salary_annual": 100000},
        ]
        payload = {
            "base_hash": _compute_hash(original_with_hc),
            "changes": [
                {
                    "path": "expenses.headcount",
                    "type": "replace_array",
                    "expected_old": 1,  # old array length
                    "new": new_headcount,
                }
            ],
            "warning_overrides": [],
            "ils_fields": {},
        }
        rc, stdout, corrected, audit = _run(payload, original_with_hc)
        assert rc == 0
        assert corrected is not None
        assert len(corrected["expenses"]["headcount"]) == 2
        assert corrected["expenses"]["headcount"][1]["role"] == "Designer"

    def test_replace_array_removes_row(self) -> None:
        """replace_array change with fewer rows removes entries."""
        original_with_hc = {
            **_ORIGINAL,
            "expenses": {
                "headcount": [
                    {"role": "Engineer", "count": 3, "salary_annual": 120000},
                    {"role": "Designer", "count": 1, "salary_annual": 100000},
                ],
            },
        }
        new_headcount = [{"role": "Engineer", "count": 3, "salary_annual": 120000}]
        payload = {
            "base_hash": _compute_hash(original_with_hc),
            "changes": [
                {
                    "path": "expenses.headcount",
                    "type": "replace_array",
                    "expected_old": 2,
                    "new": new_headcount,
                }
            ],
            "warning_overrides": [],
            "ils_fields": {},
        }
        rc, stdout, corrected, audit = _run(payload, original_with_hc)
        assert rc == 0
        assert corrected is not None
        assert len(corrected["expenses"]["headcount"]) == 1

    def test_replace_array_stale_length_rejected(self) -> None:
        """replace_array with wrong expected_old length is rejected."""
        original_with_hc = {
            **_ORIGINAL,
            "expenses": {
                "headcount": [{"role": "Engineer", "count": 3, "salary_annual": 120000}],
            },
        }
        payload = {
            "base_hash": _compute_hash(original_with_hc),
            "changes": [
                {
                    "path": "expenses.headcount",
                    "type": "replace_array",
                    "expected_old": 5,  # wrong length
                    "new": [],
                }
            ],
            "warning_overrides": [],
            "ils_fields": {},
        }
        rc, stdout, corrected, audit = _run(payload, original_with_hc)
        assert rc == 1


class TestReadErrorHandling:
    def test_corrupt_corrections_file_yields_structured_error(self, tmp_path: Any) -> None:
        """A corrupt upload must produce the pipeline's structured JSON error,
        not a raw traceback (the agent parses stdout)."""
        bad = tmp_path / "corrections.json"
        bad.write_text("{not json")
        original = tmp_path / "inputs.json"
        original.write_text("{}")
        out_dir = tmp_path / "out"
        result = subprocess.run(
            [sys.executable, _SCRIPT, str(bad), "--original", str(original), "--output-dir", str(out_dir)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 1
        out = json.loads(result.stdout)
        assert out["status"] == "error"
        assert out["errors"][0]["code"] == "READ_ERROR"
        assert "Traceback" not in result.stderr

    def test_missing_corrections_file_yields_structured_error(self, tmp_path: Any) -> None:
        """A non-existent corrections path must produce a structured JSON error."""
        missing = tmp_path / "does_not_exist.json"
        original = tmp_path / "inputs.json"
        original.write_text("{}")
        out_dir = tmp_path / "out"
        result = subprocess.run(
            [sys.executable, _SCRIPT, str(missing), "--original", str(original), "--output-dir", str(out_dir)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 1
        out = json.loads(result.stdout)
        assert out["status"] == "error"
        assert out["errors"][0]["code"] == "READ_ERROR"
        assert "Traceback" not in result.stderr

    def test_corrupt_original_file_yields_structured_error(self, tmp_path: Any) -> None:
        """A corrupt original inputs.json must produce a structured JSON error."""
        corrections = tmp_path / "corrections.json"
        corrections.write_text("{}")
        bad_original = tmp_path / "inputs.json"
        bad_original.write_text("{not valid json")
        out_dir = tmp_path / "out"
        result = subprocess.run(
            [sys.executable, _SCRIPT, str(corrections), "--original", str(bad_original), "--output-dir", str(out_dir)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 1
        out = json.loads(result.stdout)
        assert out["status"] == "error"
        assert out["errors"][0]["code"] == "READ_ERROR"
        assert "Traceback" not in result.stderr

    def test_non_dict_corrections_file_yields_structured_error(self, tmp_path: Any) -> None:
        """Valid JSON that is not an object ([1,2,3]) must be rejected with READ_ERROR,
        not passed through to downstream logic."""
        bad = tmp_path / "corrections.json"
        bad.write_text("[1, 2, 3]")
        original = tmp_path / "inputs.json"
        original.write_text("{}")
        out_dir = tmp_path / "out"
        result = subprocess.run(
            [sys.executable, _SCRIPT, str(bad), "--original", str(original), "--output-dir", str(out_dir)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 1
        out = json.loads(result.stdout)
        assert out["status"] == "error"
        assert out["errors"][0]["code"] == "READ_ERROR"
        assert "Traceback" not in result.stderr


class TestAgentDispatchPayload:
    def test_agent_dispatch_payload_corrected_path(self) -> None:
        """The exact payload shape the INPUTS_REVIEW dispatch returns (corrected +
        corrections, no changes/base_hash) must run the deterministic path:
        exit 0, status completed, both audit artifacts written, coercion applied."""
        payload = {
            "corrected": {
                "company": {
                    "company_name": "TestCo",
                    "slug": "testco",
                    "stage": "seed",
                    "sector": "B2B SaaS",
                    "geography": "US",
                },
                "revenue": {
                    "mrr": {"value": "80000", "as_of": "2026-05"},
                    "growth_rate_monthly": 0.08,
                },
                "cash": {
                    "current_balance": 1500000,
                    "balance_date": "2026-05",
                    "monthly_net_burn": 120000,
                },
                "metadata": {"run_id": "20260610T000000Z"},
            },
            "corrections": [
                {
                    "path": "cash.current_balance",
                    "old": None,
                    "new": 1500000,
                    "reason": "extracted from Summary sheet",
                }
            ],
        }
        # Use an empty original (as the main thread writes '{}' before dispatch)
        original: dict[str, Any] = {}
        rc, stdout, corrected, audit = _run(payload, original)
        assert rc == 0, stdout
        assert stdout["status"] == "completed"
        assert corrected is not None
        assert audit is not None
        # _coerce_state must have coerced the string "80000" to a number
        assert corrected["revenue"]["mrr"]["value"] == 80000


class TestOutputConvention:
    """-o support + JSON receipt, and legacy-payload shape guard."""

    def test_dash_o_writes_file_and_emits_receipt(self, tmp_path: Any) -> None:
        """-o writes the status JSON to the file and emits a {"ok": true, ...}
        receipt on stdout (per the shared script convention)."""
        corr = tmp_path / "corrections.json"
        # Legacy 'corrected' payload (a full dict) so the run succeeds (exit 0).
        corr.write_text(json.dumps({"corrected": {"company": {"stage": "seed"}}}))
        original = tmp_path / "inputs.json"
        original.write_text(json.dumps({"company": {"stage": "seed"}}))
        out_dir = tmp_path / "out"
        status_file = tmp_path / "status.json"
        result = subprocess.run(
            [
                sys.executable,
                _SCRIPT,
                str(corr),
                "--original",
                str(original),
                "--output-dir",
                str(out_dir),
                "-o",
                str(status_file),
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        receipt = json.loads(result.stdout)
        assert receipt["ok"] is True
        assert receipt["path"] == str(status_file.resolve())
        assert receipt["bytes"] > 0
        written = json.loads(status_file.read_text())
        assert written["status"] == "completed"

    def test_legacy_corrected_non_dict_yields_structured_error(self, tmp_path: Any) -> None:
        """A legacy payload whose 'corrected' is a list/scalar must produce a
        structured {"status": "error"} JSON, not a raw traceback."""
        corr = tmp_path / "corrections.json"
        corr.write_text(json.dumps({"corrected": [1, 2, 3]}))
        original = tmp_path / "inputs.json"
        original.write_text("{}")
        out_dir = tmp_path / "out"
        result = subprocess.run(
            [sys.executable, _SCRIPT, str(corr), "--original", str(original), "--output-dir", str(out_dir)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 1
        out = json.loads(result.stdout)
        assert out["status"] == "error"
        assert out["errors"][0]["code"] == "INVALID_PAYLOAD"
        assert "Traceback" not in result.stderr


class TestRunIdOriginAndHistory:
    """`--run-id` / `--origin` stamp the audit, and every call is kept in an append-only history."""

    _RUN = "20260310T090000Z-a1b2c3"
    _HISTORY = "extraction_corrections.history.jsonl"
    _OUTPUTS = ("corrected_inputs.json", "extraction_corrections.json", _HISTORY)

    def _setup(self, tmp_path: Any) -> tuple[Any, Any]:
        original = tmp_path / "inputs.json"
        original.write_text(json.dumps(_ORIGINAL))
        out_dir = tmp_path / "out"
        return original, out_dir

    def _call(self, original: Any, out_dir: Any, args: list[str]) -> subprocess.CompletedProcess[str]:
        cmd = [sys.executable, _SCRIPT, *args, "--original", str(original), "--output-dir", str(out_dir)]
        return subprocess.run(cmd, capture_output=True, text=True)

    def _write(self, tmp_path: Any, name: str, payload: Any) -> Any:
        path = tmp_path / name
        path.write_text(json.dumps(payload))
        return path

    def _changes_file(self, tmp_path: Any) -> Any:
        return self._write(
            tmp_path,
            "corrections.json",
            {
                "base_hash": _compute_hash(_ORIGINAL),
                "changes": [{"path": "revenue.customers", "type": "scalar", "expected_old": 100, "new": 120}],
                "warning_overrides": [],
                "ils_fields": {},
            },
        )

    def _wrapper_file(self, tmp_path: Any, corrections: Any = None) -> Any:
        corrected = json.loads(json.dumps(_ORIGINAL))
        corrected["revenue"]["customers"] = 120
        if corrections is None:
            corrections = [{"path": "revenue.customers", "old": 100, "new": 120, "reason": "deck says 120"}]
        return self._write(tmp_path, "inputs_review_output.json", {"corrected": corrected, "corrections": corrections})

    def _history(self, out_dir: Any) -> list[dict[str, Any]]:
        text = (out_dir / self._HISTORY).read_text()
        entries = []
        for line in text.splitlines():
            with contextlib.suppress(json.JSONDecodeError):
                entries.append(json.loads(line))
        return entries

    def _seed(self, out_dir: Any) -> dict[str, tuple[bytes, int]]:
        """Pre-existing outputs from an earlier call, so a refusal can be shown to leave them alone."""
        out_dir.mkdir(exist_ok=True)
        (out_dir / "corrected_inputs.json").write_text(json.dumps(_ORIGINAL))
        (out_dir / "extraction_corrections.json").write_text(json.dumps({"channel": "chat", "corrections": []}))
        (out_dir / self._HISTORY).write_text(json.dumps({"seq": 1, "run_id": None}) + "\n")
        old = 1_600_000_000_000_000_000
        for name in self._OUTPUTS:
            os.utime(out_dir / name, ns=(old, old))
        return self._snapshot(out_dir)

    def _snapshot(self, out_dir: Any) -> dict[str, tuple[bytes, int]]:
        return {name: ((out_dir / name).read_bytes(), (out_dir / name).stat().st_mtime_ns) for name in self._OUTPUTS}

    def _assert_refused(self, tmp_path: Any, args: list[str], code: str) -> None:
        original, out_dir = self._setup(tmp_path)
        before = self._seed(out_dir)
        result = self._call(original, out_dir, args)
        assert result.returncode == 1, result.stdout + result.stderr
        out = json.loads(result.stdout)
        assert out["status"] == "error"
        assert out["errors"][0]["code"] == code
        assert result.stderr.strip(), "a refusal must also say so on stderr"
        assert "Traceback" not in result.stderr
        assert self._snapshot(out_dir) == before, "a refusal leaves every output byte- and mtime-identical"
        assert sorted(p.name for p in out_dir.iterdir()) == sorted(self._OUTPUTS)

    # -- refusals ---------------------------------------------------------------------------------

    def test_run_id_without_origin_is_refused(self, tmp_path: Any) -> None:
        corr = self._changes_file(tmp_path)
        self._assert_refused(tmp_path, [str(corr), "--run-id", self._RUN], "ORIGIN_REQUIRED")

    def test_malformed_run_id_is_refused(self, tmp_path: Any) -> None:
        corr = self._changes_file(tmp_path)
        for bad in (f"{self._RUN}/r2", ".hidden", "_lead", "", "x" * 65, "has space"):
            self._assert_refused(tmp_path, [str(corr), "--run-id", bad, "--origin", "upload"], "INVALID_RUN_ID")

    def test_unknown_origin_is_refused(self, tmp_path: Any) -> None:
        corr = self._changes_file(tmp_path)
        self._assert_refused(tmp_path, [str(corr), "--run-id", self._RUN, "--origin", "founder"], "INVALID_ORIGIN")

    def test_upload_origin_with_set_is_refused(self, tmp_path: Any) -> None:
        args = ["--set", "revenue.customers=120", "--run-id", self._RUN, "--origin", "upload"]
        self._assert_refused(tmp_path, args, "ORIGIN_CHANNEL_MISMATCH")

    def test_chat_origin_with_a_file_is_refused(self, tmp_path: Any) -> None:
        corr = self._changes_file(tmp_path)
        self._assert_refused(
            tmp_path, [str(corr), "--run-id", self._RUN, "--origin", "chat"], "ORIGIN_CHANNEL_MISMATCH"
        )

    def test_upload_origin_with_the_inputs_review_wrapper_is_refused(self, tmp_path: Any) -> None:
        wrapper = self._wrapper_file(tmp_path)
        self._assert_refused(
            tmp_path, [str(wrapper), "--run-id", self._RUN, "--origin", "upload"], "ORIGIN_PAYLOAD_MISMATCH"
        )

    def test_external_origin_with_the_inputs_review_wrapper_is_refused(self, tmp_path: Any) -> None:
        wrapper = self._wrapper_file(tmp_path)
        self._assert_refused(
            tmp_path, [str(wrapper), "--run-id", self._RUN, "--origin", "external"], "ORIGIN_PAYLOAD_MISMATCH"
        )

    def test_corrections_that_are_not_a_list_are_refused_whatever_the_origin(self, tmp_path: Any) -> None:
        wrapper = self._wrapper_file(tmp_path, corrections={"revenue.customers": 120})
        self._assert_refused(tmp_path, [str(wrapper)], "INVALID_CORRECTIONS")
        self._assert_refused(
            tmp_path, [str(wrapper), "--run-id", self._RUN, "--origin", "inputs_review"], "INVALID_CORRECTIONS"
        )

    def test_a_history_that_cannot_be_appended_to_refuses_and_writes_nothing(self, tmp_path: Any) -> None:
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            pytest.skip("root ignores file permissions")
        original, out_dir = self._setup(tmp_path)
        before = self._seed(out_dir)
        os.chmod(out_dir / self._HISTORY, 0o444)
        try:
            corr = self._changes_file(tmp_path)
            result = self._call(original, out_dir, [str(corr), "--run-id", self._RUN, "--origin", "upload"])
        finally:
            os.chmod(out_dir / self._HISTORY, 0o644)
        assert result.returncode == 1
        assert json.loads(result.stdout)["errors"][0]["code"] == "HISTORY_UNAVAILABLE"
        assert result.stderr.strip()
        assert self._snapshot(out_dir) == before
        assert sorted(p.name for p in out_dir.iterdir()) == sorted(self._OUTPUTS), "no temporary file is left"

    # -- allowed pairings -------------------------------------------------------------------------

    def test_each_allowed_origin_and_payload_pairing_is_accepted(self, tmp_path: Any) -> None:
        changes = self._changes_file(tmp_path)
        wrapper = self._wrapper_file(tmp_path)
        set_args = ["--set", "revenue.customers=120"]
        pairings = [
            ([str(changes)], "upload"),
            ([str(changes)], "external"),
            (set_args, "external"),
            (set_args, "chat"),
            ([str(wrapper)], "inputs_review"),
            ([str(wrapper)], None),
            ([str(changes)], None),
            (set_args, None),
        ]
        for n, (source, origin) in enumerate(pairings):
            original, _ = self._setup(tmp_path)
            out_dir = tmp_path / f"out{n}"
            args = [*source] + (["--run-id", self._RUN, "--origin", origin] if origin else [])
            result = self._call(original, out_dir, args)
            assert result.returncode == 0, (source, origin, result.stdout, result.stderr)
            [entry] = self._history(out_dir)
            assert entry["origin"] == origin
            assert entry["correction_count"] == 1 and entry["changed_count"] == 1

    def test_the_channel_is_how_the_values_arrived_and_the_origin_who_sent_them(self, tmp_path: Any) -> None:
        """`channel` keeps its meaning from before `origin` existed (a file or `--set`); `origin` says who."""
        original, _ = self._setup(tmp_path)
        cases = {
            ("--set", None): "chat",
            ("--set", "chat"): "chat",
            ("--set", "external"): "chat",
            ("file", "external"): "review_page",
            ("file", "upload"): "review_page",
        }
        for n, ((how, origin), channel) in enumerate(cases.items()):
            out_dir = tmp_path / f"channel{n}"
            source = ["--set", "revenue.customers=120"] if how == "--set" else [str(self._changes_file(tmp_path))]
            args = [*source] + (["--run-id", self._RUN, "--origin", origin] if origin else [])
            result = self._call(original, out_dir, args)
            assert result.returncode == 0, (how, origin, result.stdout, result.stderr)
            [entry] = self._history(out_dir)
            audit = json.loads((out_dir / "extraction_corrections.json").read_text())
            assert (entry["channel"], audit["channel"]) == (channel, channel), (how, origin)
            assert (entry["origin"], audit["origin"]) == (origin, origin), (how, origin)

    # -- the history ------------------------------------------------------------------------------

    def test_a_corrections_call_then_a_cash_call_keeps_both_in_the_history(self, tmp_path: Any) -> None:
        original, out_dir = self._setup(tmp_path)
        corr = self._changes_file(tmp_path)
        first = self._call(original, out_dir, [str(corr), "--run-id", self._RUN, "--origin", "upload"])
        assert first.returncode == 0, first.stdout + first.stderr

        # The second call runs against the promoted output, as the cash follow-up does.
        promoted = tmp_path / "promoted.json"
        promoted.write_text((out_dir / "corrected_inputs.json").read_text())
        second = self._call(
            promoted,
            out_dir,
            [
                "--set",
                "cash.current_balance=730000",
                "--set",
                "cash.balance_date=2026-02",
                "--run-id",
                self._RUN,
                "--origin",
                "chat",
            ],
        )
        assert second.returncode == 0, second.stdout + second.stderr
        assert json.loads(second.stdout)["history_seq"] == 2

        history = self._history(out_dir)
        assert [h["seq"] for h in history] == [1, 2]
        assert [h["origin"] for h in history] == ["upload", "chat"]
        assert [h["channel"] for h in history] == ["review_page", "chat"]
        assert [h["correction_count"] for h in history] == [1, 2]
        assert [h["changed_count"] for h in history] == [1, 2]
        on_disk = hashlib.sha256((out_dir / "corrected_inputs.json").read_bytes()).hexdigest()
        assert history[1]["corrected_sha256"] == on_disk, "the last line names the corrected file it wrote"
        assert history[0]["corrected_sha256"] != on_disk
        assert all(h["run_id"] == self._RUN for h in history)
        assert history[0]["corrections"][0]["path"] == "revenue.customers"
        assert {c["path"] for c in history[1]["corrections"]} == {"cash.current_balance", "cash.balance_date"}
        for h in history:
            assert set(h) >= {
                "seq",
                "changed_count",
                "unchanged_count",
                "corrected_sha256",
                "timestamp",
                "run_id",
                "origin",
                "channel",
                "correction_count",
                "corrections",
                "overrides_added",
            }
            assert h["timestamp"].endswith("Z") and "+" not in h["timestamp"]

        audit = json.loads((out_dir / "extraction_corrections.json").read_text())
        assert audit["origin"] == "chat" and audit["run_id"] == self._RUN and audit["channel"] == "chat"
        assert audit["timestamp"] == history[1]["timestamp"]
        assert {c["path"] for c in audit["corrections"]} == {"cash.current_balance", "cash.balance_date"}
        # The single file keeps every key it carried before.
        assert set(audit) >= {
            "timestamp",
            "source_file",
            "channel",
            "correction_count",
            "corrections",
            "override_count",
            "overrides_added",
        }

        corrected = json.loads((out_dir / "corrected_inputs.json").read_text())
        assert corrected["metadata"]["run_id"] == self._RUN
        assert corrected["cash"]["current_balance"] == 730000
        assert corrected["revenue"]["customers"] == 120
        assert sorted(p.name for p in out_dir.iterdir()) == sorted(self._OUTPUTS), "no temporary file is left"

    def test_a_correction_to_the_same_value_does_not_count(self, tmp_path: Any) -> None:
        original, out_dir = self._setup(tmp_path)
        result = self._call(
            original,
            out_dir,
            ["--set", "revenue.customers=100", "--run-id", self._RUN, "--origin", "chat"],
        )
        assert result.returncode == 0, result.stdout + result.stderr
        [entry] = self._history(out_dir)
        assert (entry["correction_count"], entry["changed_count"], entry["unchanged_count"]) == (1, 0, 1)
        audit = json.loads((out_dir / "extraction_corrections.json").read_text())
        # The single file's list and count stay as they always were; the no-op is named beside them.
        assert (audit["correction_count"], audit["changed_count"], audit["unchanged_count"]) == (1, 0, 1)
        assert audit["corrections"] == [{"path": "revenue.customers", "was": 100, "now": 100}]

    def test_history_lines_are_never_rewritten(self, tmp_path: Any) -> None:
        original, out_dir = self._setup(tmp_path)
        corr = self._changes_file(tmp_path)
        assert self._call(original, out_dir, [str(corr), "--run-id", self._RUN, "--origin", "upload"]).returncode == 0
        first_bytes = (out_dir / self._HISTORY).read_bytes()
        assert self._call(original, out_dir, [str(corr), "--run-id", self._RUN, "--origin", "external"]).returncode == 0
        assert (out_dir / self._HISTORY).read_bytes().startswith(first_bytes)

    def test_a_torn_last_line_is_kept_and_the_call_succeeds(self, tmp_path: Any) -> None:
        original, out_dir = self._setup(tmp_path)
        out_dir.mkdir()
        history = out_dir / self._HISTORY
        torn = '{"seq": 1, "run_id": null}\n{"seq": 2, "run_'
        history.write_text(torn)
        corr = self._changes_file(tmp_path)
        result = self._call(original, out_dir, [str(corr), "--run-id", self._RUN, "--origin", "upload"])
        assert result.returncode == 0, result.stdout + result.stderr
        text = history.read_text()
        assert text.startswith(torn + "\n"), "the torn text stays, and the new entry starts on its own line"
        lines = text.splitlines()
        assert len(lines) == 3
        new = json.loads(lines[2])
        assert new["seq"] == 2 and new["run_id"] == self._RUN

    def test_a_torn_earlier_line_is_skipped_and_the_call_succeeds(self, tmp_path: Any) -> None:
        original, out_dir = self._setup(tmp_path)
        out_dir.mkdir()
        history = out_dir / self._HISTORY
        seeded = '{"seq": 1}\n{"seq": 2, "ru\n{"seq": 3}\n'
        history.write_text(seeded)
        corr = self._changes_file(tmp_path)
        result = self._call(original, out_dir, [str(corr), "--run-id", self._RUN, "--origin", "upload"])
        assert result.returncode == 0, result.stdout + result.stderr
        text = history.read_text()
        assert text.startswith(seeded)
        assert json.loads(text.splitlines()[-1])["seq"] == 4

    def test_a_blank_history_starts_at_one_with_no_blank_line_added(self, tmp_path: Any) -> None:
        original, out_dir = self._setup(tmp_path)
        out_dir.mkdir()
        history = out_dir / self._HISTORY
        history.write_text("\n\n")
        corr = self._changes_file(tmp_path)
        result = self._call(original, out_dir, [str(corr)])
        assert result.returncode == 0, result.stdout + result.stderr
        text = history.read_text()
        assert text.startswith("\n\n{") and text.count("\n") == 3
        assert json.loads(text.strip())["seq"] == 1

    def test_a_call_without_run_id_still_appends_with_null_run_id(self, tmp_path: Any) -> None:
        original, out_dir = self._setup(tmp_path)
        corr = self._changes_file(tmp_path)
        result = self._call(original, out_dir, [str(corr)])
        assert result.returncode == 0, result.stdout + result.stderr
        [entry] = self._history(out_dir)
        assert entry["seq"] == 1 and entry["run_id"] is None and entry["origin"] is None
        audit = json.loads((out_dir / "extraction_corrections.json").read_text())
        assert audit["run_id"] is None and audit["origin"] is None
        # Without --run-id the original's run id is preserved, as before.
        corrected = json.loads((out_dir / "corrected_inputs.json").read_text())
        assert corrected["metadata"]["run_id"] == _ORIGINAL["metadata"]["run_id"]

    def test_origin_without_run_id_is_accepted_and_recorded(self, tmp_path: Any) -> None:
        original, out_dir = self._setup(tmp_path)
        result = self._call(original, out_dir, ["--set", "revenue.customers=120", "--origin", "chat"])
        assert result.returncode == 0, result.stdout + result.stderr
        [entry] = self._history(out_dir)
        assert entry["origin"] == "chat" and entry["run_id"] is None

    def test_a_corrected_file_that_cannot_be_replaced_refuses_loudly_and_leaves_no_tmp(self, tmp_path: Any) -> None:
        original, out_dir = self._setup(tmp_path)
        out_dir.mkdir()
        (out_dir / "corrected_inputs.json").mkdir()
        corr = self._changes_file(tmp_path)
        result = self._call(original, out_dir, [str(corr), "--run-id", self._RUN, "--origin", "upload"])
        assert result.returncode == 1, result.stdout + result.stderr
        assert json.loads(result.stdout)["errors"][0]["code"] == "WRITE_FAILED"
        assert result.stderr.strip() and "Traceback" not in result.stderr
        assert not [p.name for p in out_dir.iterdir() if ".tmp-" in p.name]
        assert (out_dir / "corrected_inputs.json").is_dir()
        assert not (out_dir / "extraction_corrections.json").exists()

    def test_stale_tmp_files_of_this_script_are_removed_and_others_kept(self, tmp_path: Any) -> None:
        original, out_dir = self._setup(tmp_path)
        out_dir.mkdir()
        stale = ["corrected_inputs.json.tmp-4242", "extraction_corrections.json.tmp-17"]
        kept = ["corrected_inputs.json.tmp-notapid", "notes.json.tmp-4242", "founder_extra.txt"]
        for name in stale + kept:
            (out_dir / name).write_text("x")
        corr = self._changes_file(tmp_path)
        result = self._call(original, out_dir, [str(corr)])
        assert result.returncode == 0, result.stdout + result.stderr
        names = {p.name for p in out_dir.iterdir()}
        assert not names & set(stale)
        assert set(kept) <= names
