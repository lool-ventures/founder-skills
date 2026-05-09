"""Per-skill compose-script invariants: coaching_payload shape, run_id parity.

The coaching_payload contract was established in v0.4.2: each compose_report.py
emits a structured block in report.json so the post-compose coaching dispatch
doesn't have to read full report.md (~9K-25K tokens saved per dispatch).

These tests use synthetic minimal artifacts to verify each compose script
emits the contract-required keys.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from compose_invocations import drive_compose

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILLS_DIR = REPO_ROOT / "founder-skills" / "skills"

# Skills with on-disk fixtures populated AND wired into compose_invocations'
# INVOKERS registry. Start with deck-review only; expand AS each skill's
# fixtures land. DO NOT list a skill here before its fixtures exist —
# `pytest.skip` on missing fixtures looks identical to "all pass" in CI,
# masking silent regressions for unfixtured skills.
#
# All 5 skills emit coaching_payload as of v0.4.2; the per-skill expansion
# is tracked separately. When you add a skill here, also add it to:
#   - compose_invocations.py: _COMPOSE_FLAGS
#   - compose_invocations.py: _RUN_ID_MUTATION_TARGET
#   - founder-skills/tests/fixtures/<skill>/   (the fixture set)
COACHING_SKILLS = [
    "deck-review",
    # "market-sizing",            # add when fixtures populated
    # "ic-sim",                   # add when fixtures populated
    # "financial-model-review",   # add when fixtures populated
    # "competitive-positioning",  # add when fixtures populated
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
