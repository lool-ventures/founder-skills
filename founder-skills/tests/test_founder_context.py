#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Regression tests for founder_context.py.

Run:  pytest founder-skills/tests/test_founder_context.py -v

All tests use subprocess to exercise the script exactly as agents do.

# Touched in this commit (Task 5 — metadata block migration):
#   founder-skills/scripts/founder_context.py  — cmd_init, cmd_merge, cmd_update_identity, sp_init --run-id
#   founder-skills/tests/test_founder_context.py — audit fixes + 2 new tests
#   Audit found zero hits in other-skill production scripts (no skill reads founder-context last_updated/run_id).
"""

from __future__ import annotations

import json
import os
import pathlib
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
        assert "last_updated" in data.get("metadata", {})
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


def test_merge_deep_merges_nested_dicts() -> None:
    """merge recurses into nested sub-dicts instead of clobbering siblings.

    Regression for shared-scripts-6: a single-level dict.update replaced the
    whole nested dict, silently discarding existing sibling keys.
    """
    with tempfile.TemporaryDirectory(prefix="test-ctx-") as root:
        run_context(
            [
                "init",
                "--company-name",
                "Nested Co",
                "--stage",
                "seed",
                "--sector",
                "saas",
                "--geography",
                "US",
            ],
            artifacts_root=root,
        )
        # Seed a nested structure with two sibling keys under fundraising.round
        seed = json.dumps({"fundraising": {"round": {"target": 5, "lead": "Acmecorp"}}})
        rc, _, stderr = run_context(
            ["merge", "--slug", "nested-co", "--data", seed, "--source", "user"],
            artifacts_root=root,
        )
        assert rc == 0, f"seed merge failed: {stderr}"

        # Merge an update to one nested key; the sibling must survive.
        upd = json.dumps({"fundraising": {"round": {"target": 7}}})
        rc, data, stderr = run_context(
            ["merge", "--slug", "nested-co", "--data", upd, "--source", "user"],
            artifacts_root=root,
        )
        assert rc == 0, f"update merge failed: {stderr}"
        assert data is not None
        round_data = data["fundraising"]["round"]
        assert round_data["target"] == 7, "updated key not applied"
        assert round_data["lead"] == "Acmecorp", "sibling nested key was clobbered"


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
        meta_before = data_before.get("metadata", {})
        ts_before: str = meta_before.get("last_updated") or data_before.get("last_updated") or ""
        assert ts_before, "Expected last_updated to be set after init"

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
        meta_after = data_after.get("metadata", {})
        ts_after: str = meta_after.get("last_updated") or data_after.get("last_updated") or ""
        assert ts_after >= ts_before


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


def test_validate_accepts_series_c_and_series_d_stage() -> None:
    """validate exits 0 for a context file with stage 'series-c' or 'series-d'."""
    for stage in ("series-c", "series-d"):
        with tempfile.TemporaryDirectory(prefix="test-ctx-") as root:
            path = os.path.join(root, f"founder-context-{stage}-co.json")
            with open(path, "w") as f:
                json.dump(
                    {
                        "company_name": f"{stage.title()} Co",
                        "slug": f"{stage}-co",
                        "stage": stage,
                        "sector": "fintech",
                        "geography": "US",
                    },
                    f,
                )
            rc, data, stderr = run_context(
                ["validate", "--slug", f"{stage}-co"],
                artifacts_root=root,
            )
            assert rc == 0, f"validate failed for stage={stage}: {stderr}"


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


def test_init_accepts_series_c_and_series_d_stage() -> None:
    """init --stage series-c / series-d is accepted by argparse choices (VALID_STAGES)."""
    for stage in ("series-c", "series-d"):
        with tempfile.TemporaryDirectory(prefix="test-ctx-") as root:
            rc, data, stderr = run_context(
                ["init", "--company-name", "LaterCo", "--stage", stage, "--sector", "B2B SaaS", "--geography", "US"],
                artifacts_root=root,
            )
            assert rc == 0, f"init failed for stage={stage}: {stderr}"
            assert data is not None
            assert data["stage"] == stage


def test_update_identity_accepts_series_c_stage() -> None:
    """update-identity --stage series-c is accepted by argparse choices (VALID_STAGES)."""
    with tempfile.TemporaryDirectory(prefix="test-ctx-") as root:
        run_context(
            ["init", "--company-name", "ScaleCo", "--stage", "series-b", "--sector", "B2B SaaS", "--geography", "US"],
            artifacts_root=root,
        )
        rc, data, stderr = run_context(
            ["update-identity", "--slug", "scaleco", "--stage", "series-c"],
            artifacts_root=root,
        )
        assert rc == 0, f"update-identity failed: {stderr}"
        assert data is not None
        assert data["stage"] == "series-c"


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


# --- metadata block ---


def test_init_writes_metadata_block_with_run_id(tmp_path: pathlib.Path) -> None:
    """init produces a metadata block with run_id, review_date, last_updated."""
    artifacts_root = str(tmp_path / "artifacts")
    script = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "scripts",
        "founder_context.py",
    )
    res = subprocess.run(
        [
            sys.executable,
            script,
            "init",
            "--company-name",
            "Acme Corp",
            "--stage",
            "seed",
            "--sector",
            "B2B SaaS",
            "--geography",
            "US",
            "--artifacts-root",
            artifacts_root,
            "--run-id",
            "20260503T120000Z",
        ],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, res.stderr
    with open(os.path.join(artifacts_root, "founder-context-acme-corp.json")) as f:
        ctx = json.load(f)
    assert "metadata" in ctx
    assert ctx["metadata"]["run_id"] == "20260503T120000Z"
    assert "review_date" in ctx["metadata"]
    assert "last_updated" in ctx["metadata"]
    # last_updated and review_date no longer at top level
    assert "last_updated" not in {k for k in ctx if k != "metadata"}


def test_init_generates_run_id_when_not_provided(tmp_path: pathlib.Path) -> None:
    """init auto-generates a run_id in ISO format when --run-id is omitted."""
    import re

    artifacts_root = str(tmp_path / "artifacts")
    script = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "scripts",
        "founder_context.py",
    )
    subprocess.run(
        [
            sys.executable,
            script,
            "init",
            "--company-name",
            "Acme",
            "--stage",
            "seed",
            "--sector",
            "saas",
            "--geography",
            "US",
            "--artifacts-root",
            artifacts_root,
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    with open(os.path.join(artifacts_root, "founder-context-acme.json")) as f:
        ctx = json.load(f)
    assert re.match(r"^\d{8}T\d{6}Z$", ctx["metadata"]["run_id"])


# ---------------------------------------------------------------------------
# Item 6 — sector_type warning lists valid values + warnings array in JSON
# ---------------------------------------------------------------------------


def test_unknown_sector_type_stderr_lists_valid_values() -> None:
    """When sector_type can't be derived, stderr includes the list of valid values."""
    with tempfile.TemporaryDirectory(prefix="test-ctx-") as root:
        rc, data, stderr = run_context(
            [
                "init",
                "--company-name",
                "WeirdCo",
                "--stage",
                "seed",
                "--sector",
                "Quantum Astrology Plus",
                "--geography",
                "US",
            ],
            artifacts_root=root,
        )
        assert rc == 0
        # stderr must list at least one canonical sector type
        assert "saas" in stderr, f"Expected 'saas' in stderr; got: {stderr!r}"
        assert "ai-native" in stderr, f"Expected 'ai-native' in stderr; got: {stderr!r}"


def test_unknown_sector_type_warnings_in_json() -> None:
    """When sector_type can't be derived, JSON output carries a warnings[] entry."""
    with tempfile.TemporaryDirectory(prefix="test-ctx-") as root:
        rc, data, stderr = run_context(
            [
                "init",
                "--company-name",
                "WeirdCo",
                "--stage",
                "seed",
                "--sector",
                "Quantum Astrology Plus",
                "--geography",
                "US",
            ],
            artifacts_root=root,
        )
        assert rc == 0
        assert data is not None
        warnings = data.get("warnings", [])
        assert len(warnings) > 0, "Expected at least one warning in JSON output"
        codes = [w.get("code") for w in warnings]
        assert "W_SECTOR_TYPE_UNKNOWN" in codes, f"Expected W_SECTOR_TYPE_UNKNOWN; got codes: {codes}"
        # The warning message should also list valid values
        msg = next(w["message"] for w in warnings if w.get("code") == "W_SECTOR_TYPE_UNKNOWN")
        assert "saas" in msg, f"Valid values not in warning message: {msg}"


def test_init_derives_retail_sector_type() -> None:
    """Free-form retail/D2C sector strings derive sector_type='retail'."""
    for sector in ("Retail", "D2C fashion brand", "E-commerce"):
        with tempfile.TemporaryDirectory(prefix="test-ctx-") as root:
            rc, data, stderr = run_context(
                [
                    "init",
                    "--company-name",
                    "ShopCo",
                    "--stage",
                    "seed",
                    "--sector",
                    sector,
                    "--geography",
                    "US",
                ],
                artifacts_root=root,
            )
            assert rc == 0
            assert data is not None
            assert data["sector_type"] == "retail", f"'{sector}' should derive retail, got {data['sector_type']!r}"


def test_init_retail_marketplace_prefers_marketplace() -> None:
    """'retail marketplace' still resolves to marketplace (precedence unchanged)."""
    with tempfile.TemporaryDirectory(prefix="test-ctx-") as root:
        rc, data, stderr = run_context(
            [
                "init",
                "--company-name",
                "MarketCo",
                "--stage",
                "seed",
                "--sector",
                "Retail Marketplace",
                "--geography",
                "US",
            ],
            artifacts_root=root,
        )
        assert rc == 0
        assert data is not None
        assert data["sector_type"] == "marketplace"


def test_sector_type_message_names_the_category_mismatch(tmp_path: pathlib.Path) -> None:
    """An unresolved sector must not read as a taxonomy gap, because it usually isn't one.

    A live run passed "Consumer social / audio" and got back "could not derive sector_type;
    valid values: [saas, marketplace, usage-based, ...]" -- which invites exactly the wrong
    repair: adding industries to a list of REVENUE MODELS. An industry does not determine a
    revenue model (the same product can be subscription, marketplace or ad-supported), so
    declining to guess is correct behaviour, and the message has to say so.
    """
    rc, data, stderr = run_context(
        [
            "init",
            "--company-name",
            "Testco",
            "--stage",
            "pre_seed",
            "--sector",
            "Consumer social / audio",
            "--geography",
            "US",
        ],
        artifacts_root=str(tmp_path),
    )
    assert rc == 0, stderr
    assert data is not None and data.get("sector_type") is None, "an industry must not resolve"

    warn = next((w for w in data.get("warnings", []) if w["code"] == "W_SECTOR_TYPE_UNKNOWN"), None)
    assert warn is not None, "an unresolved sector_type must still be reported"
    msg = warn["message"]
    assert "revenue model" in msg.lower(), "must name what sector_type actually is"
    assert "industry" in msg.lower(), "must name what the caller supplied instead"
    assert "--sector-type" in msg, "must say how to set it when the model IS known"
    # State the consequence, so a reader can judge whether to care at all.
    assert "gating is skipped" in msg or "unset is correct" in msg
    # "ad-supported" may appear as prose, but must never be offered as a settable value:
    # no ad-supported benchmarks exist, so the enum entry would gate against nothing.
    assert "ad-supported" not in msg.split("know: ")[-1]
