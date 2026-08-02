"""Contract for the quick-check lane.

A founder who asks a small question in conversation gets one of three things:

1. the full pipeline (slow, but honest),
2. a quick check that runs REAL producers on the inputs they gave (fast and honest),
3. a number the model computed in its head, presented under the skill's name.

(3) is what a live run actually produced, and it is the one outcome that must be
impossible: no provenance, no stress-test, no record, no artifact. The lane exists
to make (2) available so (3) is never the path of least resistance.

Four parts of cap-table's four-mode block are load-bearing, and these tests pin
each of them in every skill that carries a lane:

- a DISTINCT output directory per mode, via a slug suffix, so `find_artifact.py`
  still resolves and a quick check never lands where a full review belongs;
- an EXPLICIT list of the producers deliberately not run — a founder cannot judge
  what they got without knowing what was skipped;
- a SAME-NUMBERS guarantee, which is what makes the lane safe to offer at all:
  fewer producers, never different ones;
- closing with a STATEMENT offering the full run, never a question, because a
  question invites a "no" to something the founder would have wanted.

ic-sim and deck-review deliberately have NO lane — see the module-level note on
`SKILLS_WITHOUT_LANE` below. That exclusion is asserted too, so adding one later
is a deliberate act rather than a drive-by.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILLS_DIR = REPO_ROOT / "founder-skills" / "skills"

# Skills whose producers decompose cleanly enough that a subset answers a real
# question on its own.
SKILLS_WITH_LANE = [
    "market-sizing",
    "financial-model-review",
    "competitive-positioning",
]

# cap-table predates the pattern and carries four modes with its own vocabulary
# (fast-assess / concise / rule-lookup). It is the template, not a copy of it, so
# it is checked separately below rather than against the shared wording.
TEMPLATE_SKILL = "cap-table"

# No lane, on purpose:
#
# - ic-sim's verdict is the product of three partner analyses plus 28 scored
#   dimensions. Any subset that runs fast enough to be a "quick check" would
#   produce a verdict from a fraction of the evidence — and a verdict is exactly
#   the output a founder would over-trust. There is no honest subset.
# - deck-review scores 35 criteria from per-slide sub-agent reviews; the slide
#   reviews ARE the work, so dropping them leaves nothing but the checklist
#   scaffolding.
#
# For both, the full pipeline is the only honest answer. State the cost up front
# and let the founder decide before it runs.
SKILLS_WITHOUT_LANE = ["ic-sim", "deck-review"]


def _skill_md(skill: str) -> str:
    path = SKILLS_DIR / skill / "SKILL.md"
    assert path.is_file(), f"missing SKILL.md for {skill}"
    return path.read_text(encoding="utf-8")


def _flat(text: str) -> str:
    """Collapse whitespace so a line-wrapped phrase still matches."""
    return " ".join(text.split())


@pytest.mark.parametrize("skill", SKILLS_WITH_LANE)
def test_lane_declares_two_modes_and_routes_between_them(skill: str) -> None:
    """The block must name how many modes there are and how to pick one."""
    flat = _flat(_skill_md(skill))
    assert "**Two modes**" in flat, f"{skill}: the mode count must be stated explicitly"
    assert "pick exactly one" in flat, f"{skill}: must say the modes are exclusive"
    assert "Quick-check mode" in flat, f"{skill}: quick-check mode is not named"


@pytest.mark.parametrize("skill", SKILLS_WITH_LANE)
def test_lane_has_a_tie_break_for_the_ambiguous_case(skill: str) -> None:
    """Both bullets fit more often than the two-mode framing admits.

    A founder who supplies complete inputs conversationally matches the full bullet
    on WHAT they asked for and the quick bullet on HOW they asked. The 1.13.0 sweep
    flagged exactly that ambiguity twice, independently, on one skill — and it was
    the entire remaining `not-adjudicable` cluster there.

    The rule is: decide on the VERB, not the inputs. Complete inputs make a full run
    faster, not less wanted.
    """
    flat = _flat(_skill_md(skill))
    assert "Tie-breaker when both bullets seem to fit" in flat, (
        f"{skill}: no tie-breaker for the case where both modes match"
    )
    assert "verb, not the inputs" in flat, f"{skill}: the tie-breaker does not name the discriminator"
    # The default must be the full run: an unwanted full run costs time, an unwanted
    # quick check costs the founder the analysis they came for.
    assert "default to the **full" in flat or "default to **full analysis**" in flat, (
        f"{skill}: no stated default when the verb is absent"
    )


@pytest.mark.parametrize("skill", SKILLS_WITH_LANE)
def test_lane_uses_a_distinct_output_directory(skill: str) -> None:
    """A quick check must never write where a full run's artifacts belong.

    Both the prose and the runnable bash variant must carry the suffix: the prose
    alone is what cap-table shipped, and a model following its bash block
    literally produced the full-pipeline directory on a concise run.
    """
    text = _skill_md(skill)
    suffix = f"{skill}-${{SLUG}}-quickcheck"
    assert suffix in text, f"{skill}: quick-check dir suffix '{suffix}' absent from SKILL.md"
    # And it must appear as an assignable variant in a bash block, commented or not.
    assert f'ARTIFACTS_ROOT/{suffix}"' in text, (
        f"{skill}: the bash block offers no -quickcheck variant, so a model following it "
        "literally writes quick-check output into the full-run directory"
    )


@pytest.mark.parametrize("skill", SKILLS_WITH_LANE)
def test_lane_lists_the_producers_it_skips(skill: str) -> None:
    """A founder cannot judge a quick check without knowing what was skipped."""
    flat = _flat(_skill_md(skill))
    assert "Producers deliberately NOT run" in flat, f"{skill}: no explicit skipped-producer list"
    # The coaching dispatch and compose are skipped by every lane; naming them is
    # the minimum, and their absence means no report.md exists.
    assert "compose_report.py" in flat, f"{skill}: skipped list must name compose_report.py"
    assert "No `report.md` is written" in flat, f"{skill}: must state that no report.md is produced"


@pytest.mark.parametrize("skill", SKILLS_WITH_LANE)
def test_lane_carries_a_same_numbers_guarantee(skill: str) -> None:
    """Fewer producers, never different ones — this is what makes the lane safe."""
    flat = _flat(_skill_md(skill))
    assert "Same-numbers guarantee" in flat, f"{skill}: no same-numbers guarantee"
    assert "only the production weight is dropped" in flat.lower(), (
        f"{skill}: must state that only production weight is dropped, not accuracy"
    )


@pytest.mark.parametrize("skill", SKILLS_WITH_LANE)
def test_lane_offers_the_full_run_as_a_statement_not_a_question(skill: str) -> None:
    """A question invites a "no" to something the founder would have wanted."""
    flat = _flat(_skill_md(skill))
    assert "**statement**, never a question" in flat, f"{skill}: the close is not pinned to a statement"
    assert "say the word and I'll run it" in flat, f"{skill}: missing the offered-follow-up wording"


@pytest.mark.parametrize("skill", SKILLS_WITH_LANE)
def test_lane_forbids_answering_from_the_models_own_head(skill: str) -> None:
    """The defect the lane exists to prevent must be named, not implied.

    Without this the lane reads as an optimization, and a model under time
    pressure reaches for the cheaper option that produced the original failure:
    compute it inline, offer the real run as an opt-in.
    """
    flat = _flat(_skill_md(skill))
    assert "Running fewer producers is fine; running none is not." in flat, (
        f"{skill}: the lane must forbid answering without running a producer"
    )
    assert "Never answer" in flat, f"{skill}: no explicit prohibition on an unproduced answer"


@pytest.mark.parametrize("skill", SKILLS_WITHOUT_LANE)
def test_skills_without_a_lane_have_not_quietly_gained_one(skill: str) -> None:
    """ic-sim and deck-review have no honest fast subset — see the module note.

    If one of them gains a lane, this test should be updated in the same commit
    that argues why the subset is honest — not silently deleted.
    """
    text = _skill_md(skill)
    assert "-quickcheck" not in text, (
        f"{skill} gained a quick-check lane. Verify the subset is honest first: a verdict "
        "or a score from a fraction of the evidence is exactly what a founder over-trusts."
    )
    # Having no lane is only honest if the cost is stated BEFORE the pipeline runs.
    # Otherwise the founder either waits several minutes for something they didn't
    # ask for, or the model quietly answers from its own head instead — which is
    # the failure the lane exists to prevent, reappearing in the skills that
    # cannot have one.
    flat = _flat(text)
    assert "There is no quick-check lane here, and that is deliberate." in flat, (
        f"{skill}: must say up front that there is no fast path, and why"
    )
    assert "say up front what the full run costs" in flat, (
        f"{skill}: must instruct the model to state the cost before running"
    )


def test_template_skill_names_all_four_of_its_modes_and_their_dirs() -> None:
    """cap-table is the template; its own block must not drift out of sync.

    It shipped saying "Two modes:" above four bullets, with two of four directory
    variants in the runnable block while forbidding invented suffixes — so a model
    following it literally put concise output in the full-review directory.
    """
    text = _skill_md(TEMPLATE_SKILL)
    flat = _flat(text)
    assert "**Four modes**" in flat, "cap-table must state four modes"
    assert "Two modes:" not in flat, "cap-table has reverted to the wrong mode count"
    for variant in ("cap-table-$SLUG}", "cap-table-$SLUG-fastassess}", "cap-table-$SLUG-concise}"):
        assert (
            variant in text.replace("${REVIEW_DIR:-$ARTIFACTS_ROOT/", "").replace("$ARTIFACTS_ROOT/", "")
            or variant.rstrip("}") in text
        ), f"cap-table's bash block is missing the {variant} variant"
    assert "Rule-lookup mode has NO REVIEW_DIR" in flat, (
        "cap-table must say rule-lookup writes no artifact, or a model builds a directory for it"
    )


# ---------------------------------------------------------------------------
# Execution checkpoint
#
# The worst-looking-fine failure in the set: the skill fires, the run is clean,
# no artifacts exist, and the founder receives hand-computed arithmetic
# benchmarked against recalled figures under the skill's name. Nothing
# contradicts it because nothing was produced.
#
# These pin the PROSE only. Prose at a decision point is a salience bet, not a
# guarantee — the real proof is a cowork scenario whose asserts require the
# canonical artifacts to exist, because artifact existence IS execution proof.
# That scenario is a paid recording and rides the next cassette refresh. Until
# then this fix is landed and behaviourally unverified; do not read a green here
# as evidence the behaviour changed.
# ---------------------------------------------------------------------------

# cap-table carries the checkpoint too, in a four-mode form. It was left out of the
# first pass on the reasoning that its mode block already routed — but routing is
# not execution, and a live probe caught it invoked with `toolCounts: {"Skill": 1}`,
# hand-computing a dilution answer while `quick_assess.py`, `concise_report.py` and
# `verify_one.py` all sat unused. Its arithmetic is the most tempting in the fleet
# (post = pre + raise) and the most consequential when wrong.
ALL_PIPELINE_SKILLS = SKILLS_WITH_LANE + SKILLS_WITHOUT_LANE + [TEMPLATE_SKILL]


@pytest.mark.parametrize("skill", ALL_PIPELINE_SKILLS)
def test_step_one_ends_with_an_execution_checkpoint(skill: str) -> None:
    """The checkpoint must sit at the decision point, not in a distant section.

    It is placed at the END of Step 1 because that is where the model first has
    enough inputs to either commit to the producers or improvise — a rule in the
    frontmatter or a closing section is read too early or too late to bind here.
    """
    text = _skill_md(skill)
    assert "#### Execution checkpoint — END OF STEP 1" in text, f"{skill}: no execution checkpoint"

    step_one = text.index("### Step 1: Read or Create Founder Context")
    checkpoint = text.index("#### Execution checkpoint")
    assert checkpoint > step_one, f"{skill}: checkpoint precedes Step 1"
    # And it must fall before Step 2 — i.e. inside Step 1, not appended later.
    after = text[checkpoint:]
    next_step = after.find("\n### Step ")
    assert next_step != -1, f"{skill}: checkpoint is not followed by a later step heading"


@pytest.mark.parametrize("skill", ALL_PIPELINE_SKILLS)
def test_checkpoint_names_every_way_the_failure_actually_happened(skill: str) -> None:
    """Each clause corresponds to an observed behaviour, not a general caution.

    A vague "always run the skill" does not bind; the model needs the specific
    move named. All four of these were seen: computing in chat, benchmarking from
    memory, offering the real run as an opt-in afterwards, and finishing without
    artifacts.
    """
    flat = _flat(_skill_md(skill))
    assert "Invoking this skill is not the same as running it." in flat, (
        f"{skill}: the invocation-vs-execution distinction is not stated"
    )
    assert "Never compute a figure in chat." in flat, f"{skill}: in-chat computation not forbidden"
    assert "Never benchmark against a figure you recalled." in flat, f"{skill}: recalled benchmarks not forbidden"
    assert "Never offer the real run as an opt-in after answering." in flat, (
        f"{skill}: the opt-in-afterwards pattern is not named as the failure"
    )
    # A7: the exemption a live run actually invented. Naming the specific move
    # beats re-asserting the rule — the rule was already absolute and lost.
    assert "is NOT an exemption" in flat, f"{skill}: the what-if exemption is not closed"
    assert "re-run the producer with the alternate input" in flat, (
        f"{skill}: must give the compliant way to answer a what-if, not just forbid the wrong one"
    )
    assert "Artifact existence is the proof of execution" in flat, (
        f"{skill}: must tie completion to artifacts on disk, not to the transcript"
    )
    # A blocked run must be declarable, or the only way to comply is to improvise.
    assert "If you are blocked, say BLOCKED and say why." in flat, (
        f"{skill}: no non-terminal blocked path, so improvising is the only exit"
    )


@pytest.mark.parametrize("skill", SKILLS_WITH_LANE)
def test_checkpoint_accepts_the_quick_check_as_a_real_finish(skill: str) -> None:
    """The checkpoint and the lane must not contradict each other.

    If the checkpoint said "run the full pipeline" full stop, a model that
    correctly routed to quick-check would be violating it — and the resolution a
    model reaches for under conflicting instructions is to do neither properly.
    """
    flat = _flat(_skill_md(skill))
    assert "Two ways to finish, and only two" in flat, f"{skill}: the two legitimate finishes are not stated"
    assert "quick-check path (Step 5-quick)" in flat, (
        f"{skill}: the checkpoint does not recognise the quick-check lane as a real finish"
    )


@pytest.mark.parametrize("skill", SKILLS_WITHOUT_LANE)
def test_checkpoint_in_laneless_skills_points_only_at_the_full_pipeline(skill: str) -> None:
    """With no lane, the full pipeline is the only finish — and it must say so."""
    flat = _flat(_skill_md(skill))
    assert "there is no quick lane here" in flat, (
        f"{skill}: the checkpoint must state that the full pipeline is the only option"
    )
    assert "Step 5-quick" not in flat, f"{skill}: references a quick path it does not have"
