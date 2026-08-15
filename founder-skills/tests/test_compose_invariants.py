"""Per-skill compose-script invariants: coaching_payload shape, run_id parity.

The coaching_payload contract was established in v0.4.2: each compose_report.py
emits a structured block in report.json so the post-compose coaching dispatch
doesn't have to read full report.md (~9K-25K tokens saved per dispatch).

These tests use synthetic minimal artifacts to verify each compose script
emits the contract-required keys.
"""

from __future__ import annotations

import json
import re
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


# Keys that tell the coaching sub-agent how much of the review actually ran. A skill with no
# entry has no such qualification to carry; add a row when one gains it.
_COACHING_COVERAGE_KEYS: dict[str, tuple[str, ...]] = {
    "deck-review": ("design_gate",),
    "market-sizing": ("comparison_blocked",),
    "financial-model-review": ("score_coverage",),
}


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
    # Per-skill keys that carry a QUALIFICATION on the headline: how much of the review
    # actually ran. Pinned at the EMISSION site because the skill-contract tests only read
    # SKILL.md and the agent body — measured, deleting all three emission lines left the whole
    # suite green, so the prompts documented a key the producer no longer sent. Each of these
    # is deliberately TOP-LEVEL; asserting them here is what makes that argument enforceable.
    for required in _COACHING_COVERAGE_KEYS.get(skill, ()):
        assert required in payload, (
            f"{skill} coaching_payload no longer emits '{required}' — the agent body still tells "
            f"the coach to reason from it, so the commentary silently loses the qualification"
        )
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
    loaded: dict = json.loads((d / name).read_text(encoding="utf-8"))
    return loaded


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


@pytest.mark.parametrize("score", [90.0, 60.0, 30.0, 10.0])
def test_cp_one_differentiation_score_gets_one_verdict(tmp_path: Path, score: float) -> None:
    """`overall_differentiation` was banded three times with two different structures.

    The headline label used four bands (a `>=25` boundary); Key Findings used three; and the summary
    paragraph added `and defensibility in ("high","moderate")` to its top arm — directly under a comment
    stating "the label and the prose paragraph never disagree". At 90% with low defensibility the report
    said "Strong — clearly differentiated" and then "moderate differentiation" two lines below.

    Parametrised across every band so the disagreement cannot hide in the one range a fixture happens to
    sit in — 3 of the 4 eval runs scored below 25.
    """

    def mutate(d: Path) -> None:
        ps = _read(d, "positioning_scores.json")
        ps["overall_differentiation"] = score
        _write(d, "positioning_scores.json", ps)
        # Force LOW defensibility: the old top arm was gated on it, so this is the case that split
        # the label from the prose.
        ms = _read(d, "moat_scores.json")
        ms["companies"]["_startup"]["overall_defensibility"] = "low"
        _write(d, "moat_scores.json", ms)

    md = _cp_compose(tmp_path, mutate)
    headline = [ln for ln in md.splitlines() if "Overall Differentiation Score" in ln]
    assert headline, "the headline differentiation label is gone"
    assert "Startup Defensibility:** Low" in md, "the low-defensibility mutation did not take effect"
    strong_headline = "Strong —" in headline[0]

    # Each prose surface is checked SEPARATELY against the headline. An `or` across them hides the
    # defect: Key Findings said "Strong differentiation" while the summary paragraph said "moderate",
    # so a combined check is satisfied by whichever one happens to agree.
    strong_paragraph = "shows strong competitive differentiation" in md
    strong_key_finding = "Strong differentiation" in md

    assert strong_headline == strong_paragraph, (
        f"at {score}% with low defensibility the headline says strong={strong_headline} but the summary "
        f"paragraph says strong={strong_paragraph} — one score, two verdicts:\n{headline[0]}"
    )
    assert strong_headline == strong_key_finding, (
        f"at {score}% the headline says strong={strong_headline} but Key Findings says "
        f"strong={strong_key_finding} — the two chains band the same number differently"
    )


def test_cp_quality_score_verdict_matches_the_checklist_canon(tmp_path: Path) -> None:
    """`score_pct` was banded at 85/70/50 in checklist.py — matching SKILL.md's documented canon and
    deck-review for cross-skill parity — and at 80/60 here for the founder-facing prose.

    At 82% the checklist calls the run `solid`; the report called it "thorough". Read the status the
    checklist already computed instead of re-deriving it from the number with different thresholds.
    """

    def mutate(d: Path) -> None:
        cl = _read(d, "checklist.json")
        cl["summary"]["score_pct"] = 82.0
        cl["summary"]["overall_status"] = "solid"  # what checklist.py's 85/70/50 canon yields
        _write(d, "checklist.json", cl)

    md = _cp_compose(tmp_path, mutate)
    assert "82.0%" in md, "the quality score no longer reaches the report"
    assert "thorough competitive analysis" not in md, (
        "82% is 'solid' under the documented 85/70/50 canon, but the report calls it thorough — the "
        "report is re-banding the number instead of reading the computed status"
    )


def test_cp_competitor_table_shows_funding(tmp_path: Path) -> None:
    """Relative capital is researched for every competitor and reached the founder nowhere reliable.

    `landscape.json` populates `funding` on 4 of 4 measured runs. It surfaced only in the explorer and
    in whatever prose the agent happened to write (0 / 1 / 47 / 25 mentions across four reports) — so
    arguably the most decision-relevant competitive fact had no deterministic surface.

    Same argument the table's own `pricing_model` column was added on: "researching it without showing
    it is work the founder paid for and cannot see."

    The fixture carries four populated values and one null, so this covers both paths — a null must
    render as the em-dash placeholder, not as "None".
    """
    md = _cp_compose(tmp_path)
    header_lines = [ln for ln in md.splitlines() if ln.startswith("| Name |")]
    assert header_lines, "competitor table header not found"
    assert "Funding" in header_lines[0], f"no funding column: {header_lines[0]}"

    table = [ln for ln in md.splitlines() if ln.startswith("| ") and "Intuit" in ln]
    assert table, "the competitor rows no longer render"
    assert "Public company (Intuit" in table[0], f"funding value missing from the row: {table[0]}"

    # The null-funding competitor must not leak a Python repr.
    assert "| None |" not in md, "a null funding value rendered as the literal 'None'"


def test_cp_not_rankable_sentinel_never_reaches_the_founder(tmp_path: Path) -> None:
    """`score_moats.py` stamps `{"rank": -1, "total": 0}` when the STARTUP is `not_applicable` on a
    dimension — a producer sentinel meaning "not rankable", correct in the artifact. `compose_report`
    rendered it verbatim: `- **Network Effects:** Rank -1 of 0 ranked`.

    NO MUTATION NEEDED — the committed fixture already carries `rank: -1` on two dimensions, so this
    reproduces the delivered defect exactly as a founder would have received it. That is also why this
    test is non-vacuous: it fails against the code as shipped before this fix.

    `not_applicable` means the moat type does not structurally apply to this business model
    (`references/moat-definitions.md`), which is a real statement worth making — so the line is
    replaced, not dropped.
    """
    md = _cp_compose(tmp_path)
    assert "Startup Ranking by Moat Dimension" in md, "fixture no longer exercises the ranking block"
    block = md.split("Startup Ranking by Moat Dimension")[1].split("###")[0]

    assert "Rank -1" not in block, f"the not-rankable sentinel reached the founder:\n{block}"
    assert "of 0 ranked" not in block, f"a zero denominator reached the founder:\n{block}"
    # Non-vacuity: the fixture must still contain the case this test exists for.
    assert "Not applicable to this business model" in block, (
        f"expected the two `not_applicable` dimensions to render as prose; got:\n{block}"
    )
    # Real ranks must be untouched.
    assert "Rank 4 of 5 ranked" in block, f"a valid rank line changed:\n{block}"


def test_cp_no_leader_attributed_on_a_dimension_that_does_not_apply(tmp_path: Path) -> None:
    """`:1305` gated the leader note on `rank_val != 1`, which is TRUE at the -1 sentinel — so an
    unrankable dimension still got `— leader: QuickBooks Online (Moderate)` appended, offering the
    founder a comparison on a dimension where no comparison was possible.

    Second-order: the fixture also produced `— leader: QuickBooks Online (N/A)` — a "leader" whose own
    status is `not_applicable`. Leading on a dimension nobody is assessed on is not leadership.
    """
    md = _cp_compose(tmp_path)
    block = md.split("Startup Ranking by Moat Dimension")[1].split("###")[0]
    for line in block.splitlines():
        if "Not applicable to this business model" in line:
            assert "leader:" not in line, f"leader attributed on a non-applicable dimension: {line!r}"
        assert "(N/A)" not in line, f"a competitor with no assessment is rendered as the leader: {line!r}"


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
                        "overlap": {"buyer": True, "job_to_be_done": False, "category": False},
                        "confidence": "high",
                    }
                ],
                "summary": {"total": 1, "genuine": 0, "flagged": 1},
                "recall_gaps": {
                    "unmatched": [
                        {"slug": "acme-tanks", "name": "Acme Tanks", "why_considered": "commodity substitute"}
                    ],
                    "probable_duplicates": [],
                },
                "_produced_by": "verify_competitors",
                "metadata": _read(d, "landscape.json")["metadata"],
            },
        )

    md = _cp_compose(tmp_path, mutate)
    assert "## Competitor Set Verification" in md
    assert "Not a competitor" in md, "the verdict enum was not rendered (or not humanized)"
    assert "Retained despite the challenge" in md, "a kept not_a_competitor entry must be flagged"
    assert "Acme Tanks" in md, "blind-recall gaps did not reach the report"
    # The substitution test's own result and the verdict's confidence: the sub-agent is asked for both,
    # so both must be visible. "adjacent" alone does not say on WHICH dimension it overlaps.
    assert "| buyer |" in md, "the overlap dimensions were not rendered"
    assert "High" in md, "verdict confidence was not rendered"


def test_cp_gate_added_competitors_are_disclosed_as_unverified(tmp_path: Path) -> None:
    """Step 3.5 runs BEFORE Gate 1, so a competitor the founder approves at a gate is never put through
    adversarial verification — and the report presented it identically to one that was.

    Confirmed live by a prediction registered before the artifacts existed: 6 verdicts against 9
    competitors, and the three absent were exactly the three added at Gate 2. On another run the
    unverified set included the competitor the skill itself described as "directly rebuts your
    white-space claim" — the most decision-relevant company in the analysis was the one verification
    never saw.

    The section is where a founder learns what was challenged, so it is where the gap belongs. This
    does not verify them — it stops the report implying they were.
    """

    def mutate(d: Path) -> None:
        land = _read(d, "landscape.json")
        # Verification covers the drafted set only — that IS the defect's shape, so it is what the
        # fixture must model. competitor_verification.json is optional and absent by default.
        _write(
            d,
            "competitor_verification.json",
            {
                "startup_characterization": {"buyer": "b", "job_to_be_done": "j"},
                "verdicts": [
                    {
                        "slug": c["slug"],
                        "verdict": "genuine",
                        "reasoning": "Same buyer, same job.",
                        "overlap": {"buyer": True, "job_to_be_done": True, "category": True},
                        "confidence": "high",
                    }
                    for c in land["competitors"]
                ],
                "summary": {"total": len(land["competitors"]), "genuine": len(land["competitors"]), "flagged": 0},
                "recall_gaps": {"unmatched": [], "probable_duplicates": []},
                "metadata": {"run_id": "20260319T143045Z"},
            },
        )
        # Add two competitors with no verdict, exactly as a Gate 1/2 approval does.
        for slug, name in (("late-add-one", "Late Add One"), ("late-add-two", "Late Add Two")):
            land["competitors"].append(
                {
                    "name": name,
                    "slug": slug,
                    "category": "direct",
                    "description": "Added by the founder at a gate, after the verification pass ran.",
                    "key_differentiators": ["approved at a gate"],
                    "research_depth": "full",
                    "evidence_source": {"description": "researched"},
                    "sourced_fields_count": 3,
                }
            )
        _write(d, "landscape.json", land)

    md = _cp_compose(tmp_path, mutate)
    assert "## Competitor Set Verification" in md, "the verification section vanished"
    section = md.split("## Competitor Set Verification")[1].split("\n## ")[0]
    assert "Late Add One" in section and "Late Add Two" in section, (
        f"competitors that never went through verification are not disclosed as such:\n{section[-700:]}"
    )
    assert re.search(r"(?i)not (?:been )?(?:independently )?(?:challenged|verified)", section), (
        f"no wording tells the founder these were never challenged:\n{section[-700:]}"
    )


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


# ---------------------------------------------------------------------------
# Fleet-wide founder-text policy: every composed report.md is clean
# ---------------------------------------------------------------------------


# Founder-facing markdown deliverables BEYOND report.md, and how to produce each.
#
# report.md is not the only thing a founder reads. cap-table also hands over a counsel packet, and it
# shipped `delaware_cross_border` and an `item(s)` placeholder to a real founder while the fleet scan
# was looking only at report.md. A deliverable nothing scans is a deliverable that can say anything.
#
# Add a row when a skill gains another delivered document; the scan is otherwise silently narrower
# than it appears.
_EXTRA_DELIVERABLES: dict[str, list[tuple[str, list[str]]]] = {
    "cap-table": [
        (
            "counsel_packet.md",
            [
                "counsel_packet.py",
                "--rule-audit",
                "{dir}/rule_audit.json",
                "--inputs",
                "{dir}/inputs.json",
                "--scenarios",
                "{dir}/scenarios.json",
                "--run-id",
                "ratchet",
                "-o",
                "{dir}/counsel_packet.json",
                "--write-md",
                "{dir}/counsel_packet.md",
            ],
        )
    ],
}


# A flagged counsel item, shaped from a real run. The cap-table FIXTURE flags nothing, so the packet
# it produces reads "0 items flagged across: no domains" — 315 bytes of boilerplate with no domain
# name in it. Scanning that is vacuous: it passed with the `delaware_cross_border` leak reverted.
# Seeded into the temp work dir rather than into the fixture, so no other test's expectations move.
_SEED_COUNSEL_ITEM = {
    "rule_id": "delaware_cross_border.qsbs_date_sensitive",
    "domain": "delaware_cross_border",
    "title": "QSBS rules are date-sensitive",
    "applies_when": "Use when US C corporation shares may be QSBS.",
    "founder_question": "Do not conclude QSBS eligibility from cap-table data alone.",
    "counsel_question": "US QSBS eligibility is date-sensitive; flag issue date for tax counsel.",
    "documents_needed": [],
    "source_ids": ["TAXADVISER-QSBS-OBBBA"],
}


def _produce_extra_deliverables(skill: str, work_dir: Path) -> list[Path]:
    """Run each non-compose producer and return the markdown it delivered."""
    import json as _json
    import subprocess
    import sys as _sys

    if skill == "cap-table":
        audit_path = work_dir / "rule_audit.json"
        if audit_path.exists():
            audit = _json.loads(audit_path.read_text(encoding="utf-8"))
            if not audit.get("counsel_review_items"):
                audit["counsel_review_items"] = [dict(_SEED_COUNSEL_ITEM)]
                audit_path.write_text(_json.dumps(audit), encoding="utf-8")

    produced: list[Path] = []
    for name, argv in _EXTRA_DELIVERABLES.get(skill, []):
        script = SKILLS_DIR / skill / "scripts" / argv[0]
        args = [a.format(dir=str(work_dir)) for a in argv[1:]]
        result = subprocess.run([_sys.executable, str(script), *args], capture_output=True, text=True)
        assert result.returncode == 0, f"{skill}/{argv[0]} failed: {result.stderr[-300:]}"
        out = work_dir / name
        assert out.exists(), f"{skill}/{argv[0]} produced no {name}"
        produced.append(out)
    return produced


def _founder_text_module():  # type: ignore[no-untyped-def]
    import importlib.util

    path = REPO_ROOT / "founder-skills" / "scripts" / "_founder_text.py"
    spec = importlib.util.spec_from_file_location("_founder_text", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_COACHING_MARKER_RE = re.compile(r"<!--\s*COACHING_INSERTION_POINT_[0-9a-f]+\s*-->")


def _strip_coaching_marker(text: str) -> str:
    """Drop the per-run coaching insertion marker before the founder-facing scan.

    `drive_compose` runs compose ONLY -- never `insert_coaching.py` -- so the marker is an expected
    intermediate artifact here, not a leak. It also sits inside an HTML comment, which renders to
    nothing; the fleet already draws founder-facing text that way (`test_html_founder_text.py` scans
    text nodes only).

    Removing it fixes a REAL flake, not a cosmetic one. The marker is
    `COACHING_INSERTION_POINT_{uuid4().hex[:8]}`, and `_founder_text._SHOUTING_RE` requires every
    segment to be `[A-Z0-9]+` -- so it matches only when those 8 hex chars happen to contain no
    a-f, i.e. (10/16)**8 = 2.3% per skill, ~13% across this parametrization. Measured before the fix:
    4 failures in 25 local runs. A test that reds one run in seven on a random uuid teaches people to
    re-run CI until it is green, which is how a real finding gets waved through.

    This removes no coverage: a marker surviving to a DELIVERED report is caught by
    `check_handoff.py:219` (MARKER_PREFIX would double-insert) and by `test_insert_coaching.py`'s
    idempotency matrix -- both deterministic, neither dependent on the uuid's digits.
    """
    return _COACHING_MARKER_RE.sub("", text)


def _cap_table_keep() -> frozenset[str]:
    """cap-table's `_labels.py` vocabulary — the one skill that keeps its own glossed enums."""
    import importlib.util

    path = SKILLS_DIR / "cap-table" / "scripts" / "_labels.py"
    spec = importlib.util.spec_from_file_location("_labels", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return frozenset(k for m in mod.MAPS.values() for k in m)


@pytest.mark.parametrize("skill", COACHING_SKILLS)
def test_composed_report_carries_no_internal_tokens(skill: str, tmp_path: Path) -> None:
    """No composed report.md may contain a private enum, field name, or internal filename.

    This is a ZERO ratchet, not a baseline — the fleet measured 0 when it was written, so any new
    occurrence is a regression introduced by that change and is cheap to fix at authoring time.

    SCOPE, stated so a green here is not over-read: fixtures are schema-correct by construction, so
    this proves the RENDERERS emit no tokens. It cannot see a token a sub-agent writes into its
    free-text evidence at runtime (`inputs.json gtm_evidence_notes is null` was observed in a live
    market-sizing run). That residue is a dispatch-template concern, not a producer one.
    """
    ft = _founder_text_module()
    fixture_dir = REPO_ROOT / "founder-skills" / "tests" / "fixtures" / skill
    if not fixture_dir.exists():
        pytest.skip(f"No fixtures at {fixture_dir.relative_to(REPO_ROOT)}")
    work_dir = tmp_path / skill
    work_dir.mkdir(parents=True)
    drive_compose(skill, fixture_dir, work_dir)

    report_md = work_dir / "report.md"
    assert report_md.exists(), (
        f"{skill} composed no report.md — every _COMPOSE_FLAGS row must pass --write-md, or this "
        f"scan reports the skill clean without having looked at it"
    )
    text = report_md.read_text(encoding="utf-8")
    # Non-vacuity: a scan of an empty/trivial report would pass trivially.
    assert len(text) > 500, f"{skill} report.md is only {len(text)}B — too small to be a real report"

    keep = _cap_table_keep() if skill == "cap-table" else None
    for extra in _produce_extra_deliverables(skill, work_dir):
        extra_text = _strip_coaching_marker(extra.read_text(encoding="utf-8"))
        # Floor set above the empty-packet boilerplate (315B), so a packet with no flagged items
        # cannot satisfy this scan.
        assert len(extra_text) > 500, (
            f"{skill}/{extra.name} is only {len(extra_text)}B — too thin to have exercised anything"
        )
        extra_found = ft.scan(extra_text, extra_keep=keep)
        assert extra_found == {"enums": [], "filenames": []}, (
            f"{skill} delivers {extra.name} carrying internal tokens: enums={extra_found['enums']} "
            f"files={extra_found['filenames']} — report.md is not the only thing the founder reads"
        )

    found = ft.scan(_strip_coaching_marker(text), extra_keep=keep)
    assert found == {"enums": [], "filenames": []}, (
        f"{skill} report.md leaks internal tokens: enums={found['enums']} files={found['filenames']}"
    )


# A URL token: everything up to whitespace or a markdown/HTML delimiter. A URL that gets a space
# inserted into it therefore TRUNCATES under this regex, which is what makes the set comparison below
# a corruption detector rather than a formatting check.
_URL_RE = re.compile(r"https?://[^\s)\]<>\"']+")

# Skills whose reports render source URLs, so an empty URL set means the scan did not look at
# anything. Named explicitly rather than inferred: an inferred list would silently shrink to nothing
# and the test would pass by finding no URLs to check.
_URL_RENDERING_SKILLS = frozenset({"market-sizing", "competitive-positioning"})


# A producer sentinel rendered as if it were a quantity. THREE FAMILIES, not an enumerated list of
# strings — the fleet's own experience is that enumerated blocklists are unwinnable, so these match on
# the SHAPE of an impossible value reaching a founder.
#
# Calibrated before use, per the discipline that a detector and the hypothesis it serves must not share
# an author unchecked: run against all six skills' committed fixtures, it returned ZERO false positives
# and ONE true positive — financial-model-review's runway table rendering `| None | None |` for a
# default-alive scenario, fixed in the same commit that added this.
_IMPOSSIBLE_VALUE_PATTERNS: dict[str, re.Pattern[str]] = {
    # A negative rank/count/total. `score_moats.py` stamps rank -1 for "not rankable"; rendering it
    # verbatim gave founders "Rank -1 of 0 ranked".
    "negative_count": re.compile(r"(?i)\b(?:rank|position|count|total|score|of)\s*:?\s*-\d+\b"),
    # A zero denominator. "of 0 ranked" is not a comparison, it is a sentinel that escaped.
    "zero_denominator": re.compile(r"(?i)\bof\s+0\b(?!\.\d)"),
    # A Python repr. `.get(k, default)` substitutes only for an ABSENT key, so an explicit null passes
    # straight through to str() — the single most common way this class reaches a deliverable.
    "python_repr": re.compile(r"(?<![A-Za-z])(?:None|NaN|nan|null)(?![A-Za-z])"),
}


@pytest.mark.parametrize("skill", COACHING_SKILLS)
def test_composed_report_carries_no_producer_sentinels(skill: str, tmp_path: Path) -> None:
    """A value that is correct in the artifact and meaningless when rendered.

    Per-site guards close instances; this closes the class. `Rank -1 of 0 ranked` rendered from a
    COMMITTED fixture and passed every founder-facing scan the fleet had — test_compose_invariants,
    test_html_founder_text, leak_scan.py and verify_positioning's rendered checks — because each of
    those looks for internal *vocabulary*, and a sentinel is internal *arithmetic*. Nothing was looking
    for a negative rank or a zero denominator.

    Scope, stated so a green is not over-read: this scans delivered markdown for values that cannot be
    true of the thing they describe. It cannot see a sentinel that renders as a plausible number (a
    producer stamping 0 for "unknown" is invisible here), and it does not scan HTML.
    """
    fixture_dir = REPO_ROOT / "founder-skills" / "tests" / "fixtures" / skill
    if not fixture_dir.exists():
        pytest.skip(f"No fixtures at {fixture_dir.relative_to(REPO_ROOT)}")
    work_dir = tmp_path / skill
    work_dir.mkdir(parents=True)
    drive_compose(skill, fixture_dir, work_dir)

    report_md = work_dir / "report.md"
    assert report_md.exists(), f"{skill} composed no report.md"
    text = report_md.read_text(encoding="utf-8")
    assert len(text) > 500, f"{skill} report.md is only {len(text)}B — too small to have exercised anything"

    found = {name: pat.findall(text) for name, pat in _IMPOSSIBLE_VALUE_PATTERNS.items()}
    hits = {k: v for k, v in found.items() if v}
    assert not hits, (
        f"{skill} report.md renders a producer sentinel to the founder: {hits}. A value that is correct "
        f"in the artifact ('-1 means not rankable') is nonsense in prose — render what it MEANS."
    )


@pytest.mark.parametrize("skill", COACHING_SKILLS)
def test_composed_report_urls_survive_founder_text_substitution(skill: str, tmp_path: Path) -> None:
    """A founder-visible string can be malformed rather than internal, and nothing scanned for that.

    `substitute()` once found candidate tokens in a URL-stripped copy of the text and then ran the
    replacement against the ORIGINAL, so a token that also appeared inside a link was rewritten there
    too — a live report shipped `.../funding round/...` where the source had `funding_round`. The
    founder is handed a dead citation, and `scan()` reports CLEAN because a broken link carries no
    internal token. A defect that destroys its own evidence is invisible to the guard built to catch it.

    The cause is fixed and unit-tested synthetically. This is the fleet-level guard on a REAL composed
    report: substitution must be a no-op on every URL the report renders. It fires for any cause of URL
    corruption, not only the one already fixed.
    """
    ft = _founder_text_module()
    fixture_dir = REPO_ROOT / "founder-skills" / "tests" / "fixtures" / skill
    if not fixture_dir.exists():
        pytest.skip(f"No fixtures at {fixture_dir.relative_to(REPO_ROOT)}")
    work_dir = tmp_path / skill
    work_dir.mkdir(parents=True)
    drive_compose(skill, fixture_dir, work_dir)

    report_md = work_dir / "report.md"
    assert report_md.exists(), f"{skill} composed no report.md"
    text = report_md.read_text(encoding="utf-8")
    urls = set(_URL_RE.findall(text))

    if skill in _URL_RENDERING_SKILLS:
        assert urls, (
            f"{skill} renders source URLs in production but its fixture report.md has none — this scan "
            f"would pass without checking anything. Add a sourced URL to the fixture."
        )

    keep = _cap_table_keep() if skill == "cap-table" else None

    # Real report content first: whatever URLs this skill actually renders must survive untouched.
    assert set(_URL_RE.findall(ft.substitute(text, extra_keep=keep))) == urls, (
        f"{skill}: founder-text substitution altered a URL in report.md. A URL that gains a space "
        f"truncates, so the mismatch names the corrupted link. The founder gets a dead citation."
    )

    # NON-VACUITY CANARY — this is load-bearing, not belt-and-braces. Measured: every fixture URL in
    # the fleet today is underscore-free, so the check above cannot fail no matter how badly
    # substitution corrupts links. Simulating the original bug against the real fixtures changed
    # nothing. The canary carries a token substitution WOULD rewrite in prose (`gross_margin` is a
    # real field name in the policy), so if URL protection regresses, this fires even when no shipped
    # fixture happens to contain a vulnerable URL.
    canary = "https://example.com/reports/gross_margin/2026-q1"
    probed = ft.substitute(f"{text}\n\nSource: {canary} and the gross_margin figure.\n", extra_keep=keep)
    assert canary in probed, (
        f"{skill}: founder-text substitution rewrote a token INSIDE a URL — the link is now dead and "
        f"scan() cannot see it, because a broken link carries no internal token"
    )
    assert "gross_margin" not in probed.replace(canary, ""), (
        f"{skill}: URL protection over-reached — prose outside the link stopped being humanized"
    )


@pytest.mark.parametrize("skill", ["ic-sim", "market-sizing", "deck-review", "financial-model-review"])
def test_compose_does_not_use_a_data_derived_keep_set(skill: str) -> None:
    """`identifier_values` is cap-table-only.

    Elsewhere an `id` field can hold a field name — financial-model-review's
    `unit_economics.metrics[].id` is `gross_margin` — and keeping it left our vocabulary in a delivered
    report while also suppressing the warning, since the scan honours the same keep-set. Found in a live
    run, invisible to fixtures because no fixture carries such a token in prose.
    """
    body = (SKILLS_DIR / skill / "scripts" / "compose_report.py").read_text(encoding="utf-8")
    assert "_ft.identifier_values(" not in body, (  # the CALL, not a mention in a comment
        f"{skill}'s compose calls identifier_values. Only cap-table may: its ids are handles the founder "
        f"matches against their own documents, while an id elsewhere may be our name for a field."
    )


def test_cap_table_still_uses_the_keep_set_it_needs() -> None:
    """Reverse direction: cap-table's scenario ids must stay verbatim across report/explorer/packet."""
    body = (SKILLS_DIR / "cap-table" / "scripts" / "compose_report.py").read_text(encoding="utf-8")
    # Whitespace-insensitive: the formatter wraps this call across lines.
    collapsed = " ".join(body.split())
    assert "_ft.identifier_values( artifacts, include_map_keys=True" in collapsed or (
        "_ft.identifier_values(artifacts, include_map_keys=True" in collapsed
    ), "cap-table must opt into map-key harvesting — per_safe is keyed by instrument id (safe_conv)"


# ---------------------------------------------------------------------------
# An internal id must not stand in for a name the artifacts already carry
# ---------------------------------------------------------------------------

_NAME_KEYS = ("name", "investor_name", "label", "title", "company_name", "display_name")
_ID_KEYS = ("id", "slug", "safe_id", "note_id", "view_id", "competitor_slug", "criterion_id")


def _id_name_pairs(node: object, out: dict[str, str]) -> None:
    """Collect {id: name} for every record carrying both."""
    if isinstance(node, dict):
        ident = next((str(node[k]) for k in _ID_KEYS if isinstance(node.get(k), str)), None)
        name = next((str(node[k]) for k in _NAME_KEYS if isinstance(node.get(k), str)), None)
        if ident and name and ident != name:
            out.setdefault(ident, name)
        for value in node.values():
            _id_name_pairs(value, out)
    elif isinstance(node, list):
        for item in node:
            _id_name_pairs(item, out)


@pytest.mark.parametrize("skill", COACHING_SKILLS)
def test_report_does_not_show_an_id_where_a_name_exists(skill: str, tmp_path: Path) -> None:
    """A delivered cap-table report identified a SAFE as `safe_foobar` while instruments.json carried
    `investor_name: "Foobar Capital LLC"`.

    The founder-text scan structurally CANNOT catch this: the id is not a leaked token — cap-table
    keeps instrument ids deliberately, for cross-artifact traceability — the defect is that a better
    label existed and went unused. No scanner detects an absent improvement, so this asserts the
    relationship instead.

    Showing the id as WELL as the name is fine and is the intended fix; only the id ALONE is a defect.
    """
    fixture_dir = REPO_ROOT / "founder-skills" / "tests" / "fixtures" / skill
    if not fixture_dir.exists():
        pytest.skip(f"No fixtures at {fixture_dir.relative_to(REPO_ROOT)}")
    work_dir = tmp_path / skill
    work_dir.mkdir(parents=True)
    drive_compose(skill, fixture_dir, work_dir)

    pairs: dict[str, str] = {}
    for artifact in work_dir.glob("*.json"):
        try:
            _id_name_pairs(json.loads(artifact.read_text(encoding="utf-8")), pairs)
        except json.JSONDecodeError:
            continue
    assert pairs, f"{skill}: no id/name pairs in its artifacts — this scan would be vacuous"

    report = (work_dir / "report.md").read_text(encoding="utf-8")
    orphans = sorted(
        ident
        for ident, name in pairs.items()
        if re.search(rf"(?<![\w.]){re.escape(ident)}(?![\w])", report) and name not in report
    )
    assert not orphans, (
        f"{skill} report.md shows internal id(s) {orphans} without the name the artifacts carry for "
        f"them ({ {i: pairs[i] for i in orphans} }). Lead with the name; keep the id in small print if "
        f"it is needed to tie the row to another artifact."
    )


@pytest.mark.parametrize("skill", ["deck-review", "ic-sim", "market-sizing", "competitive-positioning"])
def test_a_filename_in_evidence_is_surfaced_to_the_agent(skill: str, tmp_path: Path) -> None:
    """P1 depends on the agent SEEING an uncleared leak. This tests that half — the mechanism.

    Deliberately not a test of agent compliance: that cannot be asserted in-process, and a live run
    cannot verify it either, because P2's success suppresses the trigger (if evidence stops naming
    files, the warning never fires). The compliance half is verified by reading delivered artifacts.
    """
    ft = _founder_text_module()
    fixture_dir = REPO_ROOT / "founder-skills" / "tests" / "fixtures" / skill
    if not fixture_dir.exists():
        pytest.skip(f"No fixtures at {fixture_dir.relative_to(REPO_ROOT)}")
    work_dir = tmp_path / skill
    work_dir.mkdir(parents=True)
    drive_compose(skill, fixture_dir, work_dir)

    report = (work_dir / "report.md").read_text(encoding="utf-8")
    # The leak the fleet actually shipped: an artifact filename inside founder-facing prose.
    found = ft.scan(report + "\n\nConfirmed via slide_reviews.json missing slides.\n")
    assert "slide_reviews.json" in found["filenames"], (
        f"{skill}: the scan no longer detects an artifact filename in report text, so the warning P1 "
        f"tells the agent to act on would never fire"
    )
