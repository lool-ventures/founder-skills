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


# ---------------------------------------------------------------------------
# competitive-positioning: rendering contracts added in the 2026-08 remediation
#
# Every test below guards a defect that shipped to a real founder in a live run:
# a rank of "11 of 10 competitors", raw enum tokens, a competitor slug, the
# adversarial verdicts never reaching the deliverable at all, and a checklist
# graded against a positioning map that had since moved.
# ---------------------------------------------------------------------------

CP_FIXTURES = REPO_ROOT / "founder-skills" / "tests" / "fixtures" / "competitive-positioning"


def _cp_compose(tmp_path: Path, mutate: object = None) -> str:
    """Stage the competitive-positioning fixtures, optionally mutate them, compose, return report.md.

    `mutate` is called with the staged work dir before compose runs.
    """
    if not CP_FIXTURES.exists():
        pytest.skip("No competitive-positioning fixtures")
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    stage = tmp_path / "stage"
    shutil.copytree(CP_FIXTURES, stage)
    if callable(mutate):
        mutate(stage)
    drive_compose("competitive-positioning", stage, work_dir)
    return (work_dir / "report.md").read_text(encoding="utf-8")


def _read(d: Path, name: str) -> dict:
    return json.loads((d / name).read_text(encoding="utf-8"))


def _write(d: Path, name: str, obj: dict) -> None:
    (d / name).write_text(json.dumps(obj, indent=2), encoding="utf-8")


def test_cp_rank_denominator_counts_ranked_entities_not_competitors(tmp_path: Path) -> None:
    """`_compute_rank` returns competitor_count+1 when the startup is behind all competitors, so
    rendering that against competitor_count produced the literal nonsense "Y=11 (of 10
    competitors)" in a delivered report. The denominator must be the number of entities ranked."""

    def mutate(d: Path) -> None:
        ps = _read(d, "positioning_scores.json")
        # startup behind every competitor on Y: rank == competitor_count + 1
        ps["views"][0]["startup_y_rank"] = ps["views"][0]["competitor_count"] + 1
        _write(d, "positioning_scores.json", ps)

    md = _cp_compose(tmp_path, mutate)
    assert "(of 6 ranked)" in md, f"expected 'of 6 ranked' (competitor_count 5 + startup); got:\n{md[:2000]}"
    assert "competitors)" not in md.split("## Moat")[0], "positioning section still renders 'of N competitors'"


def test_cp_moat_rank_wording_matches_positioning_convention(tmp_path: Path) -> None:
    """The moat section's denominator already includes the startup. One report must not carry two
    meanings of 'of N' — the wording is unified on 'ranked'."""
    md = _cp_compose(tmp_path)
    if "Startup Ranking by Moat Dimension" in md:
        moat_block = md.split("Startup Ranking by Moat Dimension")[1]
        assert "ranked" in moat_block, "moat rank lines no longer say 'ranked'"


def test_cp_claim_verdicts_are_humanized(tmp_path: Path) -> None:
    """Raw underscored enum tokens (`partially_holds`) reached a founder's report 8 times."""
    md = _cp_compose(tmp_path)
    assert "**Verdict:** partially_holds" not in md
    assert "**Verdict:** does_not_hold" not in md
    assert "Partially holds" in md or "Does not hold" in md


def test_cp_moat_leader_renders_name_not_slug(tmp_path: Path) -> None:
    """`— leader: trane-calmac` shipped a slug to the founder; render the display name."""
    md = _cp_compose(tmp_path)
    if "— leader:" in md:
        for line in md.splitlines():
            if "— leader:" in line:
                leader = line.split("— leader:")[1].split("(")[0].strip()
                assert "-" not in leader or " " in leader, f"leader looks like a slug: {leader!r}"


def test_cp_view_label_preferred_over_title_cased_id(tmp_path: Path) -> None:
    """Descriptive slug ids get title-cased into headings like
    '### Firmness-X-Integration-Burden View'. An explicit label wins when present."""

    def mutate(d: Path) -> None:
        ps = _read(d, "positioning_scores.json")
        ps["views"][0]["label"] = "Capacity firmness vs integration burden"
        _write(d, "positioning_scores.json", ps)

    md = _cp_compose(tmp_path, mutate)
    assert "### Capacity firmness vs integration burden View" in md


def test_cp_verification_verdicts_reach_the_report(tmp_path: Path) -> None:
    """The adversarial competitor-set verdicts previously reached the founder only in chat: a
    competitor judged `not_a_competitor` was scored, ranked and tabled indistinguishably from a
    genuine one, and the verdict appeared nowhere in the artifact."""

    def mutate(d: Path) -> None:
        ls = _read(d, "landscape.json")
        first = ls["competitors"][0]["slug"]
        _write(
            d,
            "competitor_verification.json",
            {
                "startup_characterization": {"buyer": "b", "job_to_be_done": "j"},
                "verdicts": [
                    {
                        "slug": first,
                        "verdict": "not_a_competitor",
                        "reasoning": "Sells to a different buyer for a different job entirely.",
                    }
                ],
                "summary": {"total": 1, "genuine": 0, "flagged": 1},
                "recall_gaps": {
                    "unmatched": [
                        {"slug": "acme-tanks", "name": "Acme Tanks", "why_considered": "commodity substitute"}
                    ],
                    "probable_duplicates": [],
                },
                "_produced_by": "verify_competitors.py",
                "metadata": _read(d, "landscape.json")["metadata"],
            },
        )

    md = _cp_compose(tmp_path, mutate)
    assert "## Competitor Set Verification" in md
    assert "Not a competitor" in md, "the verdict enum was not rendered (or not humanized)"
    assert "Retained despite the challenge" in md, "a kept not_a_competitor entry must be flagged"
    assert "Acme Tanks" in md, "blind-recall gaps did not reach the report"


def test_cp_verification_section_absent_when_artifact_absent(tmp_path: Path) -> None:
    """The artifact is optional — a run that skipped verification must not gain an empty section."""
    md = _cp_compose(tmp_path)
    assert "## Competitor Set Verification" not in md


def test_cp_checklist_stale_vs_positioning_fires_on_fingerprint_mismatch(tmp_path: Path) -> None:
    """A re-score without re-running the checklist is invisible to run_id parity (the run_id does
    not change), so the fingerprint comparison is the only detector. POS_04 reads rank data
    directly, so a mismatch means a graded criterion describes a map that no longer exists."""

    def mutate(d: Path) -> None:
        ps = _read(d, "positioning_scores.json")
        ps["views_fingerprint"] = "a" * 64
        _write(d, "positioning_scores.json", ps)
        cl = _read(d, "checklist.json")
        cl["graded_against"] = {"views_fingerprint": "b" * 64}
        _write(d, "checklist.json", cl)

    work_dir = tmp_path / "work"
    work_dir.mkdir()
    stage = tmp_path / "stage"
    shutil.copytree(CP_FIXTURES, stage)
    mutate(stage)
    result = run_compose_capturing("competitive-positioning", stage, work_dir)
    assert "CHECKLIST_STALE_VS_POSITIONING" in result.stdout + result.stderr


def test_cp_checklist_stale_silent_when_fingerprints_match(tmp_path: Path) -> None:
    def mutate(d: Path) -> None:
        ps = _read(d, "positioning_scores.json")
        ps["views_fingerprint"] = "c" * 64
        _write(d, "positioning_scores.json", ps)
        cl = _read(d, "checklist.json")
        cl["graded_against"] = {"views_fingerprint": "c" * 64}
        _write(d, "checklist.json", cl)

    work_dir = tmp_path / "work"
    work_dir.mkdir()
    stage = tmp_path / "stage"
    shutil.copytree(CP_FIXTURES, stage)
    mutate(stage)
    result = run_compose_capturing("competitive-positioning", stage, work_dir)
    assert "CHECKLIST_STALE_VS_POSITIONING" not in result.stdout + result.stderr


def test_cp_checklist_stale_silent_when_either_side_absent(tmp_path: Path) -> None:
    """Absent is silent, never inferred — an artifact predating the field has unknown provenance."""

    def mutate(d: Path) -> None:
        ps = _read(d, "positioning_scores.json")
        ps["views_fingerprint"] = "d" * 64
        _write(d, "positioning_scores.json", ps)
        # checklist.json deliberately carries no graded_against

    work_dir = tmp_path / "work"
    work_dir.mkdir()
    stage = tmp_path / "stage"
    shutil.copytree(CP_FIXTURES, stage)
    mutate(stage)
    result = run_compose_capturing("competitive-positioning", stage, work_dir)
    assert "CHECKLIST_STALE_VS_POSITIONING" not in result.stdout + result.stderr
