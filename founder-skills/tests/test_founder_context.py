#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Regression tests for founder_context.py.

Run:  pytest founder-skills/tests/test_founder_context.py -v

All tests use subprocess to exercise the script exactly as agents do.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from typing import Any

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SCRIPTS_DIR = os.path.join(os.path.dirname(SCRIPT_DIR), "scripts")


def run_context(args: list[str], artifacts_root: str | None = None) -> tuple[int, dict[str, Any] | None, str]:
    """Run founder_context.py and return (exit_code, parsed_json_or_None, stderr)."""
    cmd = [sys.executable, os.path.join(SCRIPTS_DIR, "founder_context.py")]
    cmd.extend(args)
    if artifacts_root:
        cmd.extend(["--artifacts-root", artifacts_root])
    result = subprocess.run(cmd, capture_output=True, text=True)
    try:
        data: dict[str, Any] | None = json.loads(result.stdout) if result.stdout.strip() else None
    except json.JSONDecodeError:
        data = None
    return result.returncode, data, result.stderr


# --- init subcommand ---


def test_init_creates_file() -> None:
    """init with minimal fields creates valid JSON file."""
    with tempfile.TemporaryDirectory(prefix="test-ctx-") as root:
        rc, data, stderr = run_context(
            [
                "init",
                "--company-name",
                "Acme Corp",
                "--stage",
                "seed",
                "--sector",
                "fintech",
                "--geography",
                "US",
            ],
            artifacts_root=root,
        )
        assert rc == 0, f"init failed: {stderr}"
        assert data is not None
        assert data["company_name"] == "Acme Corp"
        assert data["stage"] == "seed"
        assert data["sector"] == "fintech"
        assert data["geography"] == "US"
        assert "last_updated" in data
        # File should exist on disk
        path = os.path.join(root, "founder-context-acme-corp.json")
        assert os.path.isfile(path)


def test_init_generates_slug() -> None:
    """Company name 'Acme Corp' generates slug 'acme-corp'."""
    with tempfile.TemporaryDirectory(prefix="test-ctx-") as root:
        rc, data, stderr = run_context(
            [
                "init",
                "--company-name",
                "Acme Corp",
                "--stage",
                "pre-seed",
                "--sector",
                "saas",
                "--geography",
                "EU",
            ],
            artifacts_root=root,
        )
        assert rc == 0, f"init failed: {stderr}"
        assert data is not None
        assert data["slug"] == "acme-corp"
        # File named with generated slug
        path = os.path.join(root, "founder-context-acme-corp.json")
        assert os.path.isfile(path)


# --- read subcommand ---


def test_read_existing() -> None:
    """read returns existing context."""
    with tempfile.TemporaryDirectory(prefix="test-ctx-") as root:
        # init first
        run_context(
            [
                "init",
                "--company-name",
                "Beta Inc",
                "--stage",
                "seed",
                "--sector",
                "healthtech",
                "--geography",
                "US",
            ],
            artifacts_root=root,
        )
        # read it back
        rc, data, stderr = run_context(
            ["read", "--slug", "beta-inc"],
            artifacts_root=root,
        )
        assert rc == 0, f"read failed: {stderr}"
        assert data is not None
        assert data["company_name"] == "Beta Inc"


def test_read_nonexistent() -> None:
    """read exits 1 when file does not exist."""
    with tempfile.TemporaryDirectory(prefix="test-ctx-") as root:
        rc, data, stderr = run_context(
            ["read", "--slug", "nonexistent"],
            artifacts_root=root,
        )
        assert rc == 1


# --- merge subcommand ---


def test_merge_adds_fields() -> None:
    """merge adds new fields without overwriting existing."""
    with tempfile.TemporaryDirectory(prefix="test-ctx-") as root:
        # init
        run_context(
            [
                "init",
                "--company-name",
                "Gamma Co",
                "--stage",
                "series-a",
                "--sector",
                "edtech",
                "--geography",
                "US",
            ],
            artifacts_root=root,
        )
        # merge new data
        merge_data = json.dumps({"team_size": 12, "founded_year": 2023})
        rc, data, stderr = run_context(
            ["merge", "--slug", "gamma-co", "--data", merge_data, "--source", "user"],
            artifacts_root=root,
        )
        assert rc == 0, f"merge failed: {stderr}"
        assert data is not None
        assert data["team_size"] == 12
        assert data["founded_year"] == 2023
        # original fields preserved
        assert data["company_name"] == "Gamma Co"


def test_merge_updates_last_updated() -> None:
    """merge always updates timestamp."""
    with tempfile.TemporaryDirectory(prefix="test-ctx-") as root:
        # init
        run_context(
            [
                "init",
                "--company-name",
                "Delta LLC",
                "--stage",
                "seed",
                "--sector",
                "logistics",
                "--geography",
                "US",
            ],
            artifacts_root=root,
        )
        # read initial
        _, data_before, _ = run_context(["read", "--slug", "delta-llc"], artifacts_root=root)
        assert data_before is not None
        ts_before = data_before["last_updated"]

        # merge something
        merge_data = json.dumps({"team_size": 5})
        rc, data_after, stderr = run_context(
            [
                "merge",
                "--slug",
                "delta-llc",
                "--data",
                merge_data,
                "--source",
                "user",
            ],
            artifacts_root=root,
        )
        assert rc == 0, f"merge failed: {stderr}"
        assert data_after is not None
        assert data_after["last_updated"] >= ts_before


def test_merge_does_not_overwrite_stable_fields() -> None:
    """All 5 stable identity fields preserved during merge."""
    with tempfile.TemporaryDirectory(prefix="test-ctx-") as root:
        # init
        run_context(
            [
                "init",
                "--company-name",
                "Epsilon Inc",
                "--stage",
                "seed",
                "--sector",
                "biotech",
                "--geography",
                "US",
            ],
            artifacts_root=root,
        )
        # try to overwrite stable fields
        merge_data = json.dumps(
            {
                "company_name": "CHANGED",
                "slug": "changed",
                "stage": "series-b",
                "sector": "fintech",
                "geography": "EU",
            }
        )
        rc, data, stderr = run_context(
            [
                "merge",
                "--slug",
                "epsilon-inc",
                "--data",
                merge_data,
                "--source",
                "user",
            ],
            artifacts_root=root,
        )
        assert rc == 0, f"merge failed: {stderr}"
        assert data is not None
        # All 5 stable fields should be unchanged
        assert data["company_name"] == "Epsilon Inc"
        assert data["slug"] == "epsilon-inc"
        assert data["stage"] == "seed"
        assert data["sector"] == "biotech"
        assert data["geography"] == "US"


# --- validate subcommand ---


def test_validate_valid() -> None:
    """validate exits 0 for valid schema."""
    with tempfile.TemporaryDirectory(prefix="test-ctx-") as root:
        # init creates a valid context
        run_context(
            [
                "init",
                "--company-name",
                "Zeta Co",
                "--stage",
                "seed",
                "--sector",
                "fintech",
                "--geography",
                "US",
            ],
            artifacts_root=root,
        )
        rc, data, stderr = run_context(
            ["validate", "--slug", "zeta-co"],
            artifacts_root=root,
        )
        assert rc == 0, f"validate failed: {stderr}"


def test_validate_missing_required() -> None:
    """validate exits 1 when required fields are missing."""
    with tempfile.TemporaryDirectory(prefix="test-ctx-") as root:
        # Write a context file missing required fields
        path = os.path.join(root, "founder-context-broken.json")
        with open(path, "w") as f:
            json.dump({"company_name": "Broken"}, f)
        rc, data, stderr = run_context(
            ["validate", "--slug", "broken"],
            artifacts_root=root,
        )
        assert rc == 1
        assert "slug" in stderr.lower() or "stage" in stderr.lower()


# --- auto-detect ---


def test_auto_detect_single_context() -> None:
    """When one context file exists, auto-detects slug."""
    with tempfile.TemporaryDirectory(prefix="test-ctx-") as root:
        # init one context
        run_context(
            [
                "init",
                "--company-name",
                "Solo Co",
                "--stage",
                "seed",
                "--sector",
                "ai",
                "--geography",
                "US",
            ],
            artifacts_root=root,
        )
        # read without --slug
        rc, data, stderr = run_context(
            ["read"],
            artifacts_root=root,
        )
        assert rc == 0, f"auto-detect failed: {stderr}"
        assert data is not None
        assert data["company_name"] == "Solo Co"


def test_auto_detect_multiple_contexts() -> None:
    """exit 2 when multiple context files exist without --slug."""
    with tempfile.TemporaryDirectory(prefix="test-ctx-") as root:
        # init two contexts
        run_context(
            [
                "init",
                "--company-name",
                "Alpha Co",
                "--stage",
                "seed",
                "--sector",
                "ai",
                "--geography",
                "US",
            ],
            artifacts_root=root,
        )
        run_context(
            [
                "init",
                "--company-name",
                "Bravo Co",
                "--stage",
                "seed",
                "--sector",
                "saas",
                "--geography",
                "EU",
            ],
            artifacts_root=root,
        )
        # read without --slug
        rc, data, stderr = run_context(
            ["read"],
            artifacts_root=root,
        )
        assert rc == 2
        assert "ambiguous" in stderr.lower() or "multiple" in stderr.lower()


# --- prior skill runs ---


def test_prior_skill_runs_appended() -> None:
    """merge with --add-skill-run appends to list."""
    with tempfile.TemporaryDirectory(prefix="test-ctx-") as root:
        # init
        run_context(
            [
                "init",
                "--company-name",
                "Eta Inc",
                "--stage",
                "seed",
                "--sector",
                "fintech",
                "--geography",
                "US",
            ],
            artifacts_root=root,
        )
        # merge with skill run
        merge_data = json.dumps({"team_size": 8})
        rc, data, stderr = run_context(
            [
                "merge",
                "--slug",
                "eta-inc",
                "--data",
                merge_data,
                "--source",
                "user",
                "--add-skill-run",
                "market-sizing",
            ],
            artifacts_root=root,
        )
        assert rc == 0, f"merge failed: {stderr}"
        assert data is not None
        assert "market-sizing" in data.get("prior_skill_runs", [])

        # Add another skill run (should append, not replace)
        merge_data2 = json.dumps({"team_size": 9})
        rc2, data2, stderr2 = run_context(
            [
                "merge",
                "--slug",
                "eta-inc",
                "--data",
                merge_data2,
                "--source",
                "user",
                "--add-skill-run",
                "deck-review",
            ],
            artifacts_root=root,
        )
        assert rc2 == 0, f"merge failed: {stderr2}"
        assert data2 is not None
        runs = data2.get("prior_skill_runs", [])
        assert "market-sizing" in runs
        assert "deck-review" in runs

        # Dedup: adding same skill run again should not duplicate
        merge_data3 = json.dumps({"team_size": 10})
        rc3, data3, stderr3 = run_context(
            [
                "merge",
                "--slug",
                "eta-inc",
                "--data",
                merge_data3,
                "--source",
                "user",
                "--add-skill-run",
                "market-sizing",
            ],
            artifacts_root=root,
        )
        assert rc3 == 0
        assert data3 is not None
        assert data3["prior_skill_runs"].count("market-sizing") == 1


# --- merge source provenance ---


def test_merge_requires_source() -> None:
    """merge without --source exits 1."""
    with tempfile.TemporaryDirectory(prefix="test-ctx-") as root:
        # init
        run_context(
            [
                "init",
                "--company-name",
                "Theta Co",
                "--stage",
                "seed",
                "--sector",
                "saas",
                "--geography",
                "US",
            ],
            artifacts_root=root,
        )
        merge_data = json.dumps({"team_size": 5})
        rc, data, stderr = run_context(
            ["merge", "--slug", "theta-co", "--data", merge_data],
            artifacts_root=root,
        )
        assert rc != 0  # argparse should enforce --source as required


def test_merge_records_source_provenance() -> None:
    """Merged key_metrics fields carry the source from --source."""
    with tempfile.TemporaryDirectory(prefix="test-ctx-") as root:
        # init
        run_context(
            [
                "init",
                "--company-name",
                "Iota Inc",
                "--stage",
                "seed",
                "--sector",
                "fintech",
                "--geography",
                "US",
            ],
            artifacts_root=root,
        )
        merge_data = json.dumps(
            {
                "key_metrics": {
                    "arr": {"value": 1000000, "as_of": "2026-01-01"},
                    "mrr": {"value": 83333, "as_of": "2026-01-01"},
                }
            }
        )
        rc, data, stderr = run_context(
            [
                "merge",
                "--slug",
                "iota-inc",
                "--data",
                merge_data,
                "--source",
                "user",
            ],
            artifacts_root=root,
        )
        assert rc == 0, f"merge failed: {stderr}"
        assert data is not None
        km = data.get("key_metrics", {})
        assert km["arr"]["source"] == "user"
        assert km["mrr"]["source"] == "user"


# --- protected field guards ---


def test_merge_rejects_skill_writing_protected_field() -> None:
    """merge with --source financial-model-review writing burn_monthly exits 1."""
    with tempfile.TemporaryDirectory(prefix="test-ctx-") as root:
        # init
        run_context(
            [
                "init",
                "--company-name",
                "Kappa Co",
                "--stage",
                "seed",
                "--sector",
                "fintech",
                "--geography",
                "US",
            ],
            artifacts_root=root,
        )
        merge_data = json.dumps({"key_metrics": {"burn_monthly": {"value": 50000, "as_of": "2026-01-01"}}})
        rc, data, stderr = run_context(
            [
                "merge",
                "--slug",
                "kappa-co",
                "--data",
                merge_data,
                "--source",
                "financial-model-review",
            ],
            artifacts_root=root,
        )
        assert rc == 1
        assert "refusing to merge derived value" in stderr.lower()


def test_merge_rejects_skill_writing_fundraising_current_cash() -> None:
    """merge with --source financial-model-review writing fundraising.current_cash exits 1."""
    with tempfile.TemporaryDirectory(prefix="test-ctx-") as root:
        # init
        run_context(
            [
                "init",
                "--company-name",
                "Lambda Co",
                "--stage",
                "seed",
                "--sector",
                "fintech",
                "--geography",
                "US",
            ],
            artifacts_root=root,
        )
        merge_data = json.dumps({"fundraising": {"current_cash": {"value": 2000000, "as_of": "2026-01-01"}}})
        rc, data, stderr = run_context(
            [
                "merge",
                "--slug",
                "lambda-co",
                "--data",
                merge_data,
                "--source",
                "financial-model-review",
            ],
            artifacts_root=root,
        )
        assert rc == 1
        assert "refusing to merge derived value" in stderr.lower()


def test_merge_allows_user_writing_protected_field() -> None:
    """merge with --source user writing burn_monthly exits 0."""
    with tempfile.TemporaryDirectory(prefix="test-ctx-") as root:
        # init
        run_context(
            [
                "init",
                "--company-name",
                "Mu Corp",
                "--stage",
                "seed",
                "--sector",
                "fintech",
                "--geography",
                "US",
            ],
            artifacts_root=root,
        )
        merge_data = json.dumps({"key_metrics": {"burn_monthly": {"value": 50000, "as_of": "2026-01-01"}}})
        rc, data, stderr = run_context(
            [
                "merge",
                "--slug",
                "mu-corp",
                "--data",
                merge_data,
                "--source",
                "user",
            ],
            artifacts_root=root,
        )
        assert rc == 0, f"merge failed: {stderr}"
        assert data is not None
        assert data["key_metrics"]["burn_monthly"]["value"] == 50000
        assert data["key_metrics"]["burn_monthly"]["source"] == "user"


def test_init_derives_sector_type() -> None:
    """init should derive sector_type from free-form sector."""
    with tempfile.TemporaryDirectory(prefix="test-ctx-") as root:
        rc, data, stderr = run_context(
            [
                "init",
                "--company-name",
                "SecureCo",
                "--stage",
                "seed",
                "--sector",
                "Cybersecurity SaaS",
                "--geography",
                "US",
            ],
            artifacts_root=root,
        )
        assert rc == 0
        assert data is not None
        assert data["sector_type"] == "saas"


def test_init_sector_type_override() -> None:
    """--sector-type overrides automatic derivation."""
    with tempfile.TemporaryDirectory(prefix="test-ctx-") as root:
        rc, data, stderr = run_context(
            [
                "init",
                "--company-name",
                "AIco",
                "--stage",
                "seed",
                "--sector",
                "AI Platform",
                "--geography",
                "US",
                "--sector-type",
                "ai-native",
            ],
            artifacts_root=root,
        )
        assert rc == 0
        assert data is not None
        assert data["sector_type"] == "ai-native"


def test_init_unknown_sector_type_null() -> None:
    """Unrecognizable sector should produce sector_type=null and stderr warning."""
    with tempfile.TemporaryDirectory(prefix="test-ctx-") as root:
        rc, data, stderr = run_context(
            [
                "init",
                "--company-name",
                "WeirdCo",
                "--stage",
                "seed",
                "--sector",
                "Quantum Astrology",
                "--geography",
                "US",
            ],
            artifacts_root=root,
        )
        assert rc == 0
        assert data is not None
        assert data["sector_type"] is None
        assert "sector_type" in stderr.lower() or "quantum astrology" in stderr.lower()


def test_init_ambiguous_sector_ai_saas() -> None:
    """'AI SaaS' should resolve to ai-native (AI takes precedence over SaaS)."""
    with tempfile.TemporaryDirectory(prefix="test-ctx-") as root:
        rc, data, stderr = run_context(
            [
                "init",
                "--company-name",
                "AIsaas",
                "--stage",
                "seed",
                "--sector",
                "AI SaaS Infrastructure",
                "--geography",
                "US",
            ],
            artifacts_root=root,
        )
        assert rc == 0
        assert data is not None
        assert data["sector_type"] == "ai-native", (
            f"'AI SaaS Infrastructure' should resolve to ai-native, got {data['sector_type']}"
        )


# --- update-identity subcommand ---


def test_update_identity_changes_sector() -> None:
    """update-identity --sector re-derives sector_type."""
    with tempfile.TemporaryDirectory(prefix="test-ctx-") as root:
        # First init
        run_context(
            ["init", "--company-name", "PivotCo", "--stage", "seed", "--sector", "B2B SaaS", "--geography", "US"],
            artifacts_root=root,
        )
        # Update sector
        rc, data, stderr = run_context(
            ["update-identity", "--slug", "pivotco", "--sector", "AI Infrastructure"],
            artifacts_root=root,
        )
        assert rc == 0
        assert data is not None
        assert data["sector"] == "AI Infrastructure"
        assert data["sector_type"] == "ai-native"
        # Stage and geography unchanged
        assert data["stage"] == "seed"
        assert data["geography"] == "US"


def test_update_identity_changes_stage() -> None:
    """update-identity --stage changes stage but keeps sector_type."""
    with tempfile.TemporaryDirectory(prefix="test-ctx-") as root:
        run_context(
            ["init", "--company-name", "GrowCo", "--stage", "seed", "--sector", "B2B SaaS", "--geography", "US"],
            artifacts_root=root,
        )
        rc, data, stderr = run_context(
            ["update-identity", "--slug", "growco", "--stage", "series-a"],
            artifacts_root=root,
        )
        assert rc == 0
        assert data is not None
        assert data["stage"] == "series-a"
        assert data["sector_type"] == "saas"  # unchanged


def test_update_identity_requires_at_least_one_field() -> None:
    """update-identity with no fields exits with error."""
    with tempfile.TemporaryDirectory(prefix="test-ctx-") as root:
        run_context(
            ["init", "--company-name", "NoCo", "--stage", "seed", "--sector", "SaaS", "--geography", "US"],
            artifacts_root=root,
        )
        rc, data, stderr = run_context(
            ["update-identity", "--slug", "noco"],
            artifacts_root=root,
        )
        assert rc != 0
        assert "at least one" in stderr.lower()


def test_merge_force_overrides_protection() -> None:
    """merge with --source financial-model-review --force writing burn_monthly exits 0 with warning."""
    with tempfile.TemporaryDirectory(prefix="test-ctx-") as root:
        # init
        run_context(
            [
                "init",
                "--company-name",
                "Nu Inc",
                "--stage",
                "seed",
                "--sector",
                "fintech",
                "--geography",
                "US",
            ],
            artifacts_root=root,
        )
        merge_data = json.dumps({"key_metrics": {"burn_monthly": {"value": 75000, "as_of": "2026-01-01"}}})
        rc, data, stderr = run_context(
            [
                "merge",
                "--slug",
                "nu-inc",
                "--data",
                merge_data,
                "--source",
                "financial-model-review",
                "--force",
            ],
            artifacts_root=root,
        )
        assert rc == 0, f"merge with --force failed: {stderr}"
        assert data is not None
        assert data["key_metrics"]["burn_monthly"]["value"] == 75000
        # Should have a warning on stderr
        assert "warning" in stderr.lower() or "force" in stderr.lower()


# --- stderr on resolve_slug failure ---


def test_read_no_context_files_stderr() -> None:
    """read with no context files should exit 1 and print message to stderr."""
    with tempfile.TemporaryDirectory() as td:
        rc, data, stderr = run_context(["read"], artifacts_root=td)
        assert rc == 1
        assert "no founder context files found" in stderr.lower()


def test_merge_no_context_files_stderr() -> None:
    """merge with no context files should exit 1 and print message to stderr."""
    with tempfile.TemporaryDirectory() as td:
        rc, data, stderr = run_context(
            ["merge", "--data", '{"company_name": "Test"}', "--source", "user"],
            artifacts_root=td,
        )
        assert rc == 1
        assert "no founder context files found" in stderr.lower()


def test_validate_no_context_files_stderr() -> None:
    """validate with no context files should exit 1 and print message to stderr."""
    with tempfile.TemporaryDirectory() as td:
        rc, data, stderr = run_context(["validate"], artifacts_root=td)
        assert rc == 1
        assert "no founder context files found" in stderr.lower()


def test_update_identity_no_context_files_stderr() -> None:
    """update-identity with no context files should exit 1 and print message to stderr."""
    with tempfile.TemporaryDirectory() as td:
        rc, data, stderr = run_context(
            ["update-identity", "--sector", "Fintech"],
            artifacts_root=td,
        )
        assert rc == 1
        assert "no founder context files found" in stderr.lower()
