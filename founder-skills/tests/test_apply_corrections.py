# founder-skills/tests/test_apply_corrections.py
"""Tests for apply_corrections.py — post-processing of founder review corrections."""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys
import tempfile

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

_ORIGINAL = {
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


def _run(corrections_data, original_data, extra_args=None):
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
    def test_basic_round_trip(self):
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

    def test_coercion_string_to_number(self):
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
        assert corrected["cash"]["current_balance"] == 1500000
        assert corrected["cash"]["monthly_net_burn"] == 90000.50

    def test_coercion_error_exits_nonzero(self):
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

    def test_ils_normalization(self):
        """ILS-tagged fields divided by fx_rate."""
        payload = {
            "corrections": [],
            "corrected": {**_ORIGINAL, "cash": {**_ORIGINAL["cash"], "current_balance": 3600000}},
            "warning_overrides": [],
            "ils_fields": {"cash.current_balance": True},
        }
        rc, stdout, corrected, audit = _run(payload, _ORIGINAL)
        assert rc == 0
        assert corrected["cash"]["current_balance"] == 1000000  # 3600000 / 3.6

    def test_time_series_canonicalization(self):
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
        months = [e["month"] for e in corrected["revenue"]["monthly"]]
        assert months == ["2026-01", "2026-02", "2026-03"]

    def test_invalid_time_series_date_exits_nonzero(self):
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

    def test_override_merge_preserves_agent(self):
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
        overrides = corrected["metadata"]["warning_overrides"]
        bm = [o for o in overrides if o["code"] == "BURN_MULTIPLE_SUSPECT"]
        assert len(bm) == 1
        assert bm[0]["reviewed_by"] == "agent"  # not downgraded

    def test_override_merge_adds_new(self):
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
        overrides = corrected["metadata"]["warning_overrides"]
        codes = [o["code"] for o in overrides]
        assert "BURN_MULTIPLE_SUSPECT" in codes  # preserved
        assert "ARPU_SUSPECT" in codes  # added

    def test_run_id_preserved(self):
        """Original metadata.run_id preserved in output."""
        payload = {
            "corrections": [],
            "corrected": {**_ORIGINAL},
            "warning_overrides": [],
            "ils_fields": {},
        }
        # Remove run_id from corrected to test preservation
        payload["corrected"]["metadata"] = {}
        rc, stdout, corrected, audit = _run(payload, _ORIGINAL)
        assert rc == 0
        assert corrected["metadata"]["run_id"] == "20260309T120000Z"

    def test_row_ids_stripped(self):
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
        assert "_row_id" not in corrected["revenue"]["monthly"][0]

    def test_boolean_coercion_in_time_series(self):
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
        assert corrected["revenue"]["monthly"][0]["actual"] is True

    def test_audit_trail_structure(self):
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
        assert "timestamp" in audit
        assert audit["source_file"] == "inputs.json"
        assert audit["correction_count"] == 1
        assert len(audit["corrections"]) == 1
        assert audit["override_count"] == 1

    def test_zero_corrections_still_writes(self):
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
    def test_round_trip_generate_then_apply(self):
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
        assert corrected["revenue"]["mrr"]["value"] == 75000
        assert corrected["revenue"]["customers"] == 150
        assert audit["correction_count"] == 2
        assert corrected["metadata"]["run_id"] == "20260309T120000Z"
