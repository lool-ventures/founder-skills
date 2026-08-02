"""Per-skill compose-script invariants: coaching_payload shape, run_id parity.

The coaching_payload contract was established in v0.4.2: each compose_report.py
emits a structured block in report.json so the post-compose coaching dispatch
doesn't have to read full report.md (~9K-25K tokens saved per dispatch).

These tests use synthetic minimal artifacts to verify each compose script
emits the contract-required keys.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from compose_invocations import drive_compose, get_mutation_target, run_compose_capturing

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILLS_DIR = REPO_ROOT / "founder-skills" / "skills"

# Skills with on-disk fixtures populated AND wired into compose_invocations'
# INVOKERS registry. DO NOT list a skill here before its fixtures exist —
# `pytest.skip` on missing fixtures looks identical to "all pass" in CI,
# masking silent regressions for unfixtured skills.
#
# All 6 skills emit coaching_payload as of v0.4.2. When you add a skill here,
# also add it to:
#   - compose_invocations.py: _COMPOSE_FLAGS
#   - compose_invocations.py: _RUN_ID_MUTATION_TARGET
#   - founder-skills/tests/fixtures/<skill>/   (the fixture set)
COACHING_SKILLS = [
    "deck-review",
    "cap-table",
    "market-sizing",
    "ic-sim",
    "financial-model-review",
    "competitive-positioning",
]


@pytest.mark.parametrize("skill", COACHING_SKILLS)
def test_compose_emits_coaching_payload(tmp_path: Path, skill: str) -> None:
    """Each compose script's report.json must include a coaching_payload block.

    This test uses each skill's on-disk fixture directory to drive compose,
    then inspects report.json.
    """
    fixture_dir = REPO_ROOT / "founder-skills" / "tests" / "fixtures" / skill
    if not fixture_dir.exists():
        pytest.skip(f"No fixtures at {fixture_dir.relative_to(REPO_ROOT)}")
    # IMPORTANT: fixture_dir and work_dir must be different paths (the
    # registry's _stage_fixtures asserts this). tmp_path is fresh per-test;
    # carve out a separate work subdir to receive copies.
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    report_path = drive_compose(skill, fixture_dir, work_dir)
    report = json.loads(report_path.read_text())
    assert "coaching_payload" in report, f"{skill} compose did not emit coaching_payload"
    payload = report["coaching_payload"]
    assert isinstance(payload, dict), "coaching_payload must be a dict"
    # Verified against v0.4.4 compose scripts: every skill's
    # _emit_coaching_payload emits these two keys. There is NO "skill" key —
    # the skill is identified by the schema_version suffix (e.g.
    # "v0.4.2-deck-review"). See e.g.
    # founder-skills/skills/deck-review/scripts/compose_report.py:723-748.
    for required in ["schema_version", "summary"]:
        assert required in payload, f"{skill} coaching_payload missing required key: {required}"
    # The schema_version suffix MUST identify this skill — guards against
    # accidental cross-skill coaching dispatch.
    sv = payload["schema_version"]
    assert isinstance(sv, str) and sv.endswith(f"-{skill}"), (
        f"{skill} coaching_payload.schema_version {sv!r} does not end with '-{skill}' — possible cross-skill leakage"
    )


@pytest.mark.parametrize("skill", COACHING_SKILLS)
def test_compose_enforces_run_id_parity(tmp_path: Path, skill: str) -> None:
    """If two artifacts have different run_ids, compose must surface STALE_ARTIFACT.

    The v0.4.2 idempotency story depends on run_id parity. If compose silently
    composes mixed-run artifacts, downstream coaching payload is corrupted.

    This test allows two valid outcomes:
    1. Compose exits 0 with STALE_ARTIFACT in the warnings list.
    2. Compose exits non-zero AND its stderr/stdout names STALE_ARTIFACT
       (e.g., under --strict). We do NOT swallow arbitrary non-zero exits —
       only those that explicitly cite STALE_ARTIFACT, otherwise the test
       would silently pass when compose crashes for unrelated reasons.

    Note: deck-review's report.json puts warnings under `validation.warnings`,
    not at the top level. The test checks the validation section.
    """
    fixture_dir = REPO_ROOT / "founder-skills" / "tests" / "fixtures" / skill
    if not fixture_dir.exists():
        pytest.skip(f"No fixtures at {fixture_dir.relative_to(REPO_ROOT)}")

    # Stage fixtures into a separate work_dir. fixture_dir and work_dir MUST
    # be distinct (asserted in the registry).
    stage = tmp_path / "stage"
    stage.mkdir()
    for f in fixture_dir.iterdir():
        if f.is_file():
            shutil.copy(f, stage / f.name)

    # Mutate the per-skill registered INPUT artifact's metadata.run_id.
    target_name = get_mutation_target(skill)
    target_path = stage / target_name
    assert target_path.exists(), (
        f"{skill} fixture is missing the registered mutation target "
        f"{target_name}. Update _RUN_ID_MUTATION_TARGET or repopulate fixtures."
    )
    data = json.loads(target_path.read_text())
    meta = data.get("metadata") if isinstance(data, dict) else None
    assert isinstance(meta, dict) and "run_id" in meta, (
        f"{skill} mutation target {target_name} has no metadata.run_id field"
    )
    data["metadata"]["run_id"] = "MUTATED-FOR-TEST"
    target_path.write_text(json.dumps(data, indent=2))

    # Run compose with capture (no raise on non-zero) so we can inspect
    # both successful-with-warning and failed-with-named-warning paths.
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    result = run_compose_capturing(skill, stage, work_dir)
    combined_output = (result.stdout or "") + (result.stderr or "")

    if result.returncode != 0:
        # Non-zero is acceptable IFF the failure cites STALE_ARTIFACT.
        # Any other non-zero is a real bug we must not silently pass.
        assert "STALE_ARTIFACT" in combined_output, (
            f"{skill} compose exited {result.returncode} without naming "
            f"STALE_ARTIFACT — looks like an unrelated failure:\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        return

    # Zero-exit path: STALE_ARTIFACT must appear in the warnings list.
    # deck-review's report.json puts warnings under `validation.warnings`.
    report_path = work_dir / "report.json"
    assert report_path.exists(), f"{skill} compose succeeded but report.json missing"
    report = json.loads(report_path.read_text())
    # Try both top-level `warnings` and nested `validation.warnings` for
    # compatibility across compose-script implementations.
    warnings = report.get("warnings", []) or report.get("validation", {}).get("warnings", [])
    codes = [w.get("code") for w in warnings if isinstance(w, dict)]
    assert "STALE_ARTIFACT" in codes, (
        f"{skill} compose did not surface STALE_ARTIFACT for mismatched run_id; got warning codes: {codes}"
    )
