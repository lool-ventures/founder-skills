"""The fleet's delivery-defect coverage map, asserted rather than described.

Four defect classes were found by hand-reading delivered artifacts. Each is covered by a different
mechanism, and two of them are covered for only some skills. Recording that in prose decays; this
module asserts it, so a gate that disappears or a skill that gains one both surface here.

  A  computed, not rendered   analysis paid for that reaches no delivery surface
  B  dead payload             a key embedded in a page's JS that the script never reads
  C  internal token           our vocabulary shown to a founder who cannot act on it
  D  stale grading            an artifact grading a version of its input that no longer exists

WHERE EACH IS COVERED

  B  fleet-wide, every embedder            test_dead_payload.py
  C  fleet-wide, report.md                 each compose's founder-text scan + test_compose_invariants
  C  fleet-wide, generated HTML            test_html_founder_text.py — STATIC TEXT ONLY. Measured
                                          text-node share: visualize 1.4-4.4%, explore 0.1-0.2%.
                                          Explorer content is JS-rendered from the payload at runtime
                                          and is NOT covered; the Cowork UI gate is what covers it.
  C  id-shown-instead-of-name              test_compose_invariants.py — the class no token scan can
                                          see, because the id is kept deliberately and the defect is
                                          an absent improvement
  C  coaching commentary                   insert_coaching.py reports findings on insert
  A  upstream half, fleet-wide             test_dispatch_schema_drift.py (a field nobody consumes)
  A  downstream half, TWO SKILLS ONLY      verify_positioning.py, verify_review.py
  A  downstream half, ONE SKILL, WEAK      test_competitive_positioning_skill_contract.py — asserts a
                                          named computed field appears in the Gate 1 template. NOT a
                                          gate and does NOT narrow the gap below: it cannot fail a
                                          run, and it is a string assertion over SKILL.md prose, so
                                          it survives any rewording that keeps the token. It catches
                                          deletion, nothing subtler.
  D  competitive-positioning               checklist fingerprint vs the scored map it graded
  D  financial-model-review                output fingerprints vs current inputs.json

THE KNOWN GAP: class A's downstream half — "this artifact field was computed and no delivery surface
shows it" — is enforced only for competitive-positioning and financial-model-review. ic-sim,
market-sizing, deck-review and cap-table have no such gate. The contract-test row above does not
change that count: a gate can fail a run, a string assertion cannot.

NOT class A, recorded here because it was found alongside one and is easy to file wrongly: a
presentation layer RE-DERIVING a judgement the producer already made. competitive-positioning's
Gate 1 selected challenges by comparing a verdict to a draft category as literal tokens, across two
DISJOINT vocabularies, so exactly one value could ever match. That is the test_dispatch_schema_drift
shape — two ends of one contract drifting — not "computed but never shown", and its remedy differs
too: the judgement moved into the producer and the prose was deleted rather than corrected.

Deliberate, for a reason worth keeping: a fixture-driven detector for it is blind by construction.
Fixtures are schema-correct, so scanning one answers "does the renderer behave on good input", which is
not the question any of these defects lived in. The highest-severity instance of class A found so far
existed *because* a dispatch template instructed a shape the reader did not expect — a fixture carrying
the correct shape could never have exposed it. The upstream half above is the cheap approximation that
does generalise; a real downstream gate needs live output, which costs a paid run per skill.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILLS_DIR = REPO_ROOT / "founder-skills" / "skills"
TESTS_DIR = REPO_ROOT / "founder-skills" / "tests"

# Skills with a real pre-delivery gate: a script whose job is to refuse to hand over an incomplete
# review. A mid-pipeline validator (verify_competitors.py) and a rule lookup (verify_one.py) are not
# gates and are deliberately absent.
_GATED_SKILLS = {
    "competitive-positioning": "verify_positioning.py",
    "financial-model-review": "verify_review.py",
}

_UNGATED_SKILLS = {"ic-sim", "market-sizing", "deck-review", "cap-table"}


@pytest.mark.parametrize(("skill", "gate"), sorted(_GATED_SKILLS.items()))
def test_the_gates_this_map_relies_on_exist(skill: str, gate: str) -> None:
    """If a gate is renamed or removed, the coverage claim above becomes false silently."""
    path = SKILLS_DIR / skill / "scripts" / gate
    assert path.is_file(), f"{skill} is recorded as gated by {gate}, which does not exist"
    body = path.read_text(encoding="utf-8")
    assert "exit" in body, f"{gate} must be able to fail a run, or it is not a gate"


def test_the_ungated_skills_are_still_ungated() -> None:
    """Reverse direction: a skill that gains a gate must update the map, not widen the gap quietly."""
    unexpected = {}
    for skill in sorted(_UNGATED_SKILLS):
        scripts = SKILLS_DIR / skill / "scripts"
        if not scripts.is_dir():
            continue
        # A gate is a script named verify_* whose purpose is publish/refuse. verify_one.py (cap-table)
        # is a cited rule lookup, not a gate, and is excluded by name for that reason.
        gates = [p.name for p in scripts.glob("verify_*.py") if p.name != "verify_one.py"]
        if gates:
            unexpected[skill] = gates
    assert not unexpected, (
        f"these skills now have a gate-shaped script: {unexpected}. If it is a real pre-delivery gate, "
        f"move the skill into _GATED_SKILLS and update the module docstring's coverage map."
    )


def test_the_gate1_render_contract_is_enforced_by_a_live_test() -> None:
    """The WEAK row above must name tests that exist AND still assert.

    Imported and CALLED, not grepped. This module's own precedent is that a name-presence check
    survives the thing being gutted: `test_skill_contract.py`'s paid-lane guard records that its
    grep version "stayed green with the gate gone" and had to switch to calling. A row in a
    coverage map is a claim, and the cheapest way for it to become false is for the test it names
    to be emptied while keeping its name.

    Calling does not make the row strong -- an emptied body still passes, which is exactly why the
    row says WEAK. It makes the row TRUE.
    """
    import importlib.util

    path = TESTS_DIR / "test_competitive_positioning_skill_contract.py"
    assert path.is_file(), "the coverage map names a contract test file that does not exist"
    spec = importlib.util.spec_from_file_location("cp_skill_contract_under_test", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    for name in (
        "test_gate1_renders_the_possible_overlap_annotation",
        "test_gate1_reads_challenge_slugs_and_does_not_rederive_it",
    ):
        fn = getattr(mod, name, None)
        assert callable(fn), f"{name} is named in the coverage map but is not a callable test"
        fn()


@pytest.mark.parametrize(
    "module",
    [
        "test_dead_payload.py",
        "test_html_founder_text.py",
        "test_dispatch_schema_drift.py",
        "test_compose_invariants.py",
    ],
)
def test_the_fleet_wide_detectors_this_map_relies_on_exist(module: str) -> None:
    assert (TESTS_DIR / module).is_file(), (
        f"the coverage map names {module} as a fleet-wide detector, and it is not present"
    )


def test_coaching_commentary_is_scanned_on_insert() -> None:
    """The commentary is not in the string compose scans, so it needs its own check."""
    body = (REPO_ROOT / "founder-skills" / "scripts" / "insert_coaching.py").read_text(encoding="utf-8")
    assert "founder_text_findings" in body, (
        "insert_coaching.py no longer reports founder-text findings, leaving the coaching commentary "
        "the one founder-visible report section that nothing scans"
    )
