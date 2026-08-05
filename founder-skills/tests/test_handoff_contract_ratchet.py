"""Ratchet the hand-off contract prose that a live run cannot yet vouch for.

WHY THIS FILE EXISTS. Five fixes in this area are *prose* — instructions in a
SKILL.md or an agent body — and prose has shipped inert here three separate times
(a coaching sub-agent narrated against an explicit "Do not narrate"; a main thread
ignored a documented exit-3 branch; a fleet-wide outputs-mount guardrail turned out
to make no difference in an A/B). Behavioural proof needs a live Cowork run.

These tests are NOT that proof and must not be mistaken for it. They assert only
that the instruction is still PRESENT and still says the load-bearing thing, so a
future edit cannot delete it silently. That is a narrower guarantee than "it works"
— and it is exactly the guarantee that was missing when the doubled-path defect
shipped under a green suite.

Each test names the failure it guards, so a reader who breaks one can decide
whether the instruction genuinely moved or is being lost.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills"
_AGENTS_DIR = Path(__file__).resolve().parent.parent / "agents"
_SHARED_REFS_DIR = Path(__file__).resolve().parent.parent / "references"

SKILLS = sorted(p.name for p in _SKILLS_DIR.iterdir() if (p / "SKILL.md").is_file())
AGENTS = sorted(p.name for p in _AGENTS_DIR.glob("*.md"))

# Documents that must never INSTRUCT a sub-agent to return the old JSON commentary envelope.
# Deliberately excludes every SKILL.md: they describe the envelope the MAIN THREAD builds, with the
# literal token, and correctly so — see financial-model-review/SKILL.md's md_to_commentary.py
# paragraph. Forbidding it there would be wrong.
COMMENTARY_ENVELOPE_GUARDED = sorted(_AGENTS_DIR.glob("*.md")) + [_SHARED_REFS_DIR / "skill-execution-model.md"]


def _skill(name: str) -> str:
    return (_SKILLS_DIR / name / "SKILL.md").read_text(encoding="utf-8")


def _agent(name: str) -> str:
    return (_AGENTS_DIR / name).read_text(encoding="utf-8")


def _flat(text: str) -> str:
    """Collapse whitespace before matching prose.

    Markdown wraps at ~100 chars, so a required phrase is routinely split across a
    newline. An exact-substring assertion then fails on a document that says exactly
    the right thing — which already happened twice in this repo. Every prose check
    below goes through this.
    """
    return " ".join(text.split()).lower()


def test_all_six_skills_present() -> None:
    """Guard the parametrization itself — a renamed dir must not silently shrink coverage."""
    assert len(SKILLS) == 6, SKILLS
    assert len(AGENTS) == 6, AGENTS
    # Same guard, same reason: an empty glob turns a parametrized test into `1 skipped` and
    # exit 0 — measured. A guard that can silently delete itself is the vacuity class this
    # whole file exists to prevent.
    assert len(COMMENTARY_ENVELOPE_GUARDED) == 7, COMMENTARY_ENVELOPE_GUARDED
    for doc in COMMENTARY_ENVELOPE_GUARDED:
        assert doc.is_file(), f"guarded document is missing: {doc}"


@pytest.mark.parametrize("doc", COMMENTARY_ENVELOPE_GUARDED, ids=lambda p: p.stem)
def test_context_b_never_asks_for_the_json_commentary_envelope(doc: Path) -> None:
    """No agent body or shared reference may ask the Context B sub-agent to return
    `{"commentary_markdown": ...}`.

    The sub-agent writes PLAIN MARKDOWN to OUTPUT_PATH; the main thread wraps it via
    `md_to_commentary.py`. The old JSON form makes the model re-emit multi-KB of commentary into
    its final message — the double-emission hazard the file hand-off exists to prevent, which
    truncates. It reds nothing; it surfaces as a mangled report.

    WHY WHOLE-FILE, AND WHY THIS FILE SET. Six per-skill tests used to assert this over a fixed
    1000-char window (cap-table 2000) anchored in the Context B section. Measured, every one of
    them had a blind zone of 42-73% of the section: inserting the token before the section's
    closing heading left all six GREEN. A negative assertion bounded by a character count stops
    checking once its target moves past the offset. Whole-file has no boundary to rename and no
    fence to unterminate.

    The file set is where the drift actually happens, not where it was previously guarded:
    `git log --all -S 'commentary_markdown' -- founder-skills/agents/` is EMPTY — the token has
    never been in an agent body. It drifted in `references/skill-execution-model.md`, which had
    no guard at all until this test.

    LIMITS, so nobody mistakes this for more than it is. It is lexical: it forbids the quoted
    `"commentary_markdown"`, so prose naming the field in backticks still passes. And all six
    agent bodies already carry the sentence one clarification away from tripping it ("A
    main-thread script (not you) wraps the raw markdown in the JSON transport envelope") — if
    someone names the key there, this fails loudly and the fix is to reword, not to widen.
    """
    assert '"commentary_markdown"' not in doc.read_text(encoding="utf-8"), (
        f"{doc.name} names the OLD Context B transport. The sub-agent writes plain markdown to "
        "OUTPUT_PATH and returns only a receipt; the main thread builds the JSON envelope via "
        "md_to_commentary.py. Asking for the envelope back reinstates the double-emission hazard."
    )


# ---------------------------------------------------------------------------
# 1. The coaching payload is STAGED as a file and READ from the agent namespace.
#
# Guards against: reverting to an inlined payload. The read is what makes a wrong
# agent-namespace prefix fail loudly BEFORE the sub-agent writes anything. An
# inlined payload gives the dispatch no required read, which is precisely how the
# doubled-path defect stayed invisible in the one dispatch that had no read.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("skill", SKILLS)
def test_coaching_payload_is_staged_to_a_file(skill: str) -> None:
    body = _skill(skill)
    assert "$HANDOFF_DIR/coaching_payload.json" in body, (
        f"{skill}: the coaching payload must be STAGED to $HANDOFF_DIR/coaching_payload.json, "
        "not printed for the model to paste into the dispatch prompt"
    )


@pytest.mark.parametrize("skill", SKILLS)
def test_context_b_reads_the_staged_payload_from_the_agent_namespace(skill: str) -> None:
    body = _skill(skill)
    assert "<HANDOFF_AGENT>/coaching_payload.json" in body, (
        f"{skill}: the Context B dispatch prompt must tell the sub-agent to Read "
        "<HANDOFF_AGENT>/coaching_payload.json — the agent namespace, not an absolute path"
    )


@pytest.mark.parametrize("skill", SKILLS)
def test_no_paste_the_payload_placeholder_remains(skill: str) -> None:
    body = _skill(skill)
    assert "paste the coaching_payload" not in body, (
        f"{skill}: a 'paste the coaching_payload' placeholder is back — the payload must travel by "
        "file so it leaves the model exactly once and the dispatch keeps its required read"
    )


# ---------------------------------------------------------------------------
# 2. A failed REQUIRED read returns BLOCKED with the attempted path.
#
# Guards against: an agent that improvises when a required read fails. That is the
# higher-severity half of the defect — it yields a complete-LOOKING deliverable
# assessed against inputs never read, which nothing downstream can detect.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("skill", SKILLS)
def test_dispatch_prompt_demands_blocked_on_unresolvable_handoff(skill: str) -> None:
    body = _skill(skill)
    assert "handoff_path_unresolvable" in body, (
        f"{skill}: the dispatch prompt must instruct a typed "
        '{"status":"blocked","reason":"handoff_path_unresolvable"} return when the payload Read fails'
    )


@pytest.mark.parametrize("agent", AGENTS)
def test_agent_body_carries_the_required_read_rule(agent: str) -> None:
    body = _agent(agent)
    assert "handoff_path_unresolvable" in body, (
        f"{agent}: the agent body must carry the required-Read failure rule with its typed reason"
    )
    flat = _flat(body)
    assert "never proceed on inferred or absent inputs" in flat, (
        f"{agent}: the rule must state the prohibition explicitly — a failed required Read may not be "
        "worked around by inferring the input"
    )


@pytest.mark.parametrize("agent", AGENTS)
def test_agent_body_forbids_glob_and_guess_recovery(agent: str) -> None:
    """Self-healing by Glob is what MASKED the defect: the agent delivered to the right
    place, echoed the literal OUTPUT_PATH, and left the wrong prefix undetected."""
    flat = _flat(_agent(agent))
    assert "do not glob for the file" in flat, (
        f"{agent}: the rule must forbid Glob-and-guess recovery — silently self-correcting hides the "
        "prefix bug instead of reporting it"
    )


# ---------------------------------------------------------------------------
# 3. The exit-8 branch exists and is DIAGNOSTIC ONLY.
#
# Guards against: someone "helpfully" making the gate read the hand-off from
# found_at. That would void the invariant behind exit 0 — "it is safe to cat
# $HANDOFF_DIR/<file>" — which every downstream producer pipe depends on.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("skill", SKILLS)
def test_exit_8_branch_present_and_read_only(skill: str) -> None:
    body = _skill(skill)
    assert "path_namespace_mismatch" in body, f"{skill}: no exit-8 branch in the hand-off state machine"
    # locate the branch text and assert it forbids reading from found_at
    idx = body.find("path_namespace_mismatch")
    branch = body[idx : idx + 900].lower()
    assert "found_at" in branch, f"{skill}: the exit-8 branch must name found_at"
    assert "do not read" in branch or "never read" in branch, (
        f"{skill}: the exit-8 branch MUST forbid reading the hand-off from found_at — it is a "
        "diagnostic, and honouring it would silently break the exit-0 path contract"
    )
    assert "re-dispatch" in branch, (
        f"{skill}: the exit-8 recovery is a re-dispatch with the corrected prefix, not a read"
    )


# ---------------------------------------------------------------------------
# 4. The Context B graceful-degrade fallback is REACHABLE.
#
# Guards against: the state it was in — instructing the main thread to stage "the
# sub-agent's raw markdown final message" while the Context B prompt told the agent
# to return only a receipt and not narrate. There was no markdown to stage, so the
# branch could never execute.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("skill", SKILLS)
def test_graceful_degrade_asks_for_the_markdown_inline(skill: str) -> None:
    body = _skill(skill)
    idx = body.rfind("hand-off-incompatible")  # Context B's, not Context A's
    if idx == -1:
        pytest.skip(f"{skill} has no message-channel fallback")
    window = _flat(body[max(0, idx - 600) : idx + 1600])
    assert "return the coaching commentary itself as your final message" in window, (
        f"{skill}: the corrective dispatch must ASK for the commentary inline, or the fallback is "
        "unreachable — the normal prompt forbids narrating and returns only a receipt"
    )


# ---------------------------------------------------------------------------
# 5. Hand-off paths come from the script, never hand-spliced.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("skill", SKILLS)
def test_agent_namespace_path_is_script_resolved(skill: str) -> None:
    body = _skill(skill)
    assert "<printed AGENT_ARTIFACTS_ROOT>" not in body, (
        f"{skill}: the agent-namespace path is hand-spliced again. Use "
        "--handoff-dir-agent / --analysis-dir-agent so the skill name, slug and run id are not "
        "three literals a paraphrasing model can get wrong"
    )
    assert "--handoff-dir-agent" in body, f"{skill}: must resolve HANDOFF_AGENT via --handoff-dir-agent"


# ---------------------------------------------------------------------------
# 6. Routing: every skill asserts why it beats answering from memory.
#
# Guards against: the observed decline, where the model agreed the trigger matched
# and answered from recollection anyway. cap-table was the only skill that framed
# this, and the only one that routed correctly.
# ---------------------------------------------------------------------------


def _frontmatter(skill: str) -> str:
    return _skill(skill).split("---")[1]


@pytest.mark.parametrize("skill", SKILLS)
def test_skill_counters_answering_from_memory(skill: str) -> None:
    fm = _flat(_frontmatter(skill))
    family = ("from memory", "recalling", "improvising", "deterministic math")
    assert any(t in fm for t in family), (
        f"{skill}: frontmatter must assert why running the skill beats answering from memory — "
        "restrictive framing alone did not prevent a decline on the canonical use case"
    )


@pytest.mark.parametrize("skill", [s for s in SKILLS if s != "cap-table"])
def test_skill_closes_the_verbosity_loophole(skill: str) -> None:
    """The observed decline cited the skill being 'heavyweight' and the user preferring
    concise answers. cap-table is exempt: it routes correctly with its own framing."""
    fm = _flat(_frontmatter(skill))
    assert "verbosity is not a reason to skip it" in fm, (
        f"{skill}: frontmatter must close the cost/verbosity loophole explicitly"
    )


@pytest.mark.parametrize("skill", SKILLS)
def test_anti_substitution_framing_is_in_description_too(skill: str) -> None:
    """`when_to_use` is read by the CLI runtime but NOT by Desktop's regex discovery
    scanner, and the observed failure was in Cowork. The framing has to be in
    `description`, which Desktop does read."""
    fm = _frontmatter(skill)
    m = re.search(r'^description:\s*"(.*?)"\s*$', fm, re.M | re.S)
    assert m, f"{skill}: description is not a single-line quoted scalar"
    desc = _flat(m.group(1))
    family = ("memory", "recalling", "improvising", "deterministic math")
    assert any(t in desc for t in family), (
        f"{skill}: the anti-substitution framing must appear in `description`, not only in "
        "`when_to_use` — Desktop's discovery scanner never reads when_to_use"
    )
