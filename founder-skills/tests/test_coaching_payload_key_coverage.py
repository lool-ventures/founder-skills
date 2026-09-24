"""The coach's key list must name every key its producer actually emits — derived, not typed.

Scope, deliberately narrow (see `coaching_payload_keys.py` for the full argument):

* **Agent bodies only.** The agent body is the coach's operative key list. For five of six skills
  the payload is STAGED AS A FILE the sub-agent Reads, so SKILL.md's copy documents a template the
  coach never parses; only deck-review inlines it. Asserting the derived set against SKILL.md too
  would force nine key names into four dispatch templates that sit exactly at an exact-match byte
  ceiling — paying six ceiling raises to document keys on a surface that, for five skills, nothing
  reads. The SKILL.md side keeps its own curated list.
* **Addition direction only.** A derived set shrinks when an emission is deleted, so this cannot
  catch a prompt naming a key the producer stopped sending. `test_compose_invariants.py`'s
  `_COACHING_COVERAGE_KEYS` pins that direction at the emission site and is NOT made redundant here.
* **Names, not shapes.** `test_high_severity_warning_shape_matches_the_producer` covers the axis
  this one is blind to — four of the six defects that motivated this file were shape drift inside
  a key that was present and correctly named.
"""

from __future__ import annotations

import ast
import pathlib
import re

import pytest
from coaching_payload_keys import EMITTERS, SKILLS_ROOT, emitted_top_level_keys

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
AGENTS = REPO_ROOT / "founder-skills" / "agents"

# Keys the COACH is not expected to read, each with the reason it is exempt. Anything not listed
# here must appear in the agent body; this set is the only place an exemption can be taken, and a
# bare name with no reason is a review smell.
NOT_FOR_THE_COACH: dict[str, str] = {
    # Plumbing: identifies which skill's schema this is. Pinned by each skill's own
    # test_coaching_payload_schema_version_is_<skill>, never written by the coach.
    "schema_version": "schema plumbing, pinned separately",
}


def _context_b(skill: str) -> str:
    """The agent body's Context B section — bounded on the next same-level heading.

    NOT a fixed character window. A 4,000-char slice in the fmr contract test failed on content
    that was still present the moment the key list above it grew, which is the failure mode
    CLAUDE.md warns about.
    """
    text = (AGENTS / f"{skill}.md").read_text(encoding="utf-8")
    # The HEADING, not the bare string: every agent body mentions "Context B" first in its YAML
    # frontmatter `description:`, and anchoring there selects ~1.3 KB of summary prose instead of
    # the key list. Measured -- it reported every key as missing on all six skills.
    start = text.find("### Context B")
    assert start != -1, f"{skill}.md has no '### Context B' heading"
    end = text.find("\n## ", start + 1)
    return text[start : end if end != -1 else len(text)]


@pytest.mark.parametrize("skill", sorted(EMITTERS))
def test_agent_body_names_every_emitted_payload_key(skill: str) -> None:
    derived = emitted_top_level_keys(skill)
    assert derived, f"{skill}: derivation returned nothing"
    section = _context_b(skill)
    missing = sorted(k for k in derived if k not in NOT_FOR_THE_COACH and k not in section)
    assert not missing, (
        f"{skill}'s compose script emits {missing} but the agent body's Context B key list does "
        "not name them. A key the coach is never told to read is a key it will not use — and if "
        "nothing should read it, add it to NOT_FOR_THE_COACH with a reason."
    )


@pytest.mark.parametrize("skill", sorted(EMITTERS))
def test_exemptions_are_actually_emitted(skill: str) -> None:
    """Guard the guard: an exemption for a key nothing emits is dead weight that hides drift."""
    derived = emitted_top_level_keys(skill)
    for key in NOT_FOR_THE_COACH:
        if key not in derived:
            pytest.skip(f"{key} not emitted by {skill}")
        assert key in derived


def _emitted_warning_fields(skill: str) -> set[str]:
    """The literal field names of the dict built inside `high_severity_warnings`."""
    path = SKILLS_ROOT / skill / "scripts" / "compose_report.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Dict)):
            continue
        for k, v in zip(node.keys, node.values, strict=False):
            if isinstance(k, ast.Constant) and k.value == "high_severity_warnings":
                for inner in ast.walk(v):
                    if isinstance(inner, ast.Dict) and inner.keys:
                        return {
                            kk.value for kk in inner.keys if isinstance(kk, ast.Constant) and isinstance(kk.value, str)
                        }
    return set()


@pytest.mark.parametrize("skill", sorted(EMITTERS))
def test_high_severity_warning_shape_matches_the_producer(skill: str) -> None:
    """The agent body must not describe a field the producer does not emit.

    This is the axis key-derivation cannot see, and it is where four of the six motivating defects
    lived: five agent bodies said `high_severity_warnings` was "(codes only)" for months while
    every one of those producers emitted objects carrying a founder-facing `label`. The coach was
    being pointed at the one string the same prompts forbid it from writing.
    """
    emitted = _emitted_warning_fields(skill)
    if not emitted:
        pytest.skip(f"{skill} does not build warning objects inline")
    section = _context_b(skill)
    line_start = section.find("`high_severity_warnings`")
    assert line_start != -1, f"{skill}.md Context B does not mention high_severity_warnings"
    described = section[line_start : line_start + 400]

    # Any field named in backticks near the bullet must be one the producer emits.
    claimed = set(re.findall(r"`([a-z_]{3,})`", described)) - {"high_severity_warnings"}
    bogus = sorted(c for c in claimed if c not in emitted and c in _ALL_KNOWN_FIELD_NAMES)
    assert not bogus, (
        f"{skill}.md describes {bogus} on high_severity_warnings but the producer emits "
        f"{sorted(emitted)}. A prompt naming a field that is not sent is how a coach ends up "
        "writing the raw code."
    )


# Field names any skill's warning objects use. Restricting the check to this vocabulary keeps
# ordinary prose words in the bullet from reading as field claims.
_ALL_KNOWN_FIELD_NAMES = {"code", "label", "message", "detail", "title", "warning_id", "severity"}
