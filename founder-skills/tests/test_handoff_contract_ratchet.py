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


# Anchors bounding the Context A gate branch table. VERIFIED across all six before
# being written here, which is the step two drafts of this change skipped:
#   * `_CTX_A_OPEN` is present in all six. cap-table's copy is UNBOLDED while the other
#     five are bolded, so the pattern must not require `**`.
#   * The heading `### Context A hand-off protocol (file transport + gate)` is NOT usable:
#     it exists in five and cap-table has none (its only match is a cross-reference). A
#     naive `^#` fallback there matches bash comments inside a fenced block.
#   * `_CTX_A_CLOSE` occurs twice per file (Context A and Context B); the FIRST occurrence
#     after the open anchor is the Context A one.
_CTX_A_OPEN = re.compile(r"After EVERY Context A dispatch, gate before piping")
_CTX_A_CLOSE = re.compile(r"\*\*Retry budget:\*\*")


def _context_a_gate_block(body: str, skill: str) -> str:
    """The Context A gate branch table, bounded by two verified anchors.

    Block-bounded rather than character-windowed (see the whole-file note above:
    a fixed offset stops checking once its target moves) and rather than
    whole-file (the token being asserted already occurs in Context B, so a
    whole-file positive would pass pre-fix — measured).
    """
    lines = body.splitlines()
    opens = [i for i, ln in enumerate(lines) if _CTX_A_OPEN.search(ln)]
    assert len(opens) == 1, f"{skill}: expected exactly 1 Context A gate anchor, found {len(opens)}"
    closes = [i for i, ln in enumerate(lines) if i > opens[0] and _CTX_A_CLOSE.search(ln)]
    assert closes, f"{skill}: no `**Retry budget:**` after the Context A gate anchor"
    block = "\n".join(lines[opens[0] : closes[0]])
    # A guard that can silently empty itself is the vacuity class this file exists to
    # prevent: assert the block is substantive, not merely that it was located.
    assert len(block.splitlines()) >= 10, f"{skill}: Context A gate block is only {len(block.splitlines())} lines"
    assert "check_handoff.py" in block, f"{skill}: located block is not the gate table"
    return block


@pytest.mark.parametrize("skill", SKILLS)
def test_context_a_gate_table_documents_exit_8(skill: str) -> None:
    """Exit 8 must have a branch in the CONTEXT A table, not only in Context B.

    Exit 8 is the branch Context A was written for: Context A is where `OUTPUT_PATH`
    is built from `$HANDOFF_AGENT`, i.e. where the doubled-agent-namespace-prefix
    condition actually occurs. Measured before this test existed, all six Context A
    tables listed 0/3/4/5/6 and stopped — so a Context A exit 8 fell through to
    `- **Any other exit** ... -> STOP with the stderr`, halting the run over a
    condition `check_handoff.py`'s own diagnostic says is recoverable ("the agent
    complied; re-dispatch with the corrected prefix").

    Exit 7's absence from Context A is CORRECT and deliberately not asserted here:
    `EXIT_SHAPE_INVALID` is raised only inside `if args.format == "markdown"`, which
    is Context B's invocation.
    """
    block = _context_a_gate_block(_skill(skill), skill).lower()
    assert "exit 8" in block, (
        f"{skill}: the Context A gate table does not document exit 8. It is the branch this "
        "code path exists for, and without a row it falls to 'any other exit -> STOP'."
    )
    assert "found_at" in block, f"{skill}: the Context A exit-8 branch must name found_at"
    assert "do not read" in block or "never read" in block, (
        f"{skill}: the Context A exit-8 branch MUST forbid reading the hand-off from found_at"
    )


@pytest.mark.parametrize("skill", SKILLS)
def test_exit_8_branch_present_and_read_only(skill: str) -> None:
    """Every exit-8 branch in the file must forbid reading the hand-off from `found_at`.

    REWRITTEN 2026-08-31. This used to do `body.find("path_namespace_mismatch")` and
    slice a 900-char window from the FIRST occurrence. That was safe only while the
    token appeared exactly once per file (Context B). Adding the Context A branch made
    `find()` return the new, earlier occurrence — so the test would either red, or
    (worse) pass while silently ceasing to check the Context B branch it was written
    to guard. It now iterates EVERY occurrence, which is also what removes the
    fixed-offset window this file's own whole-file note argues against.
    """
    body = _skill(skill)
    starts = [m.start() for m in re.finditer("path_namespace_mismatch", body)]
    assert len(starts) >= 2, f"{skill}: expected an exit-8 branch in BOTH Context A and Context B, found {len(starts)}"
    for n, idx in enumerate(starts, 1):
        branch = body[idx : idx + 900].lower()
        assert "found_at" in branch, f"{skill}: exit-8 branch #{n} must name found_at"
        assert "do not read" in branch or "never read" in branch, (
            f"{skill}: exit-8 branch #{n} MUST forbid reading the hand-off from found_at — it is a "
            "diagnostic, and honouring it would silently break the exit-0 path contract"
        )
        assert "re-dispatch" in branch, (
            f"{skill}: exit-8 branch #{n} recovery is a re-dispatch with the corrected prefix, not a read"
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


# Context B's gate table. Its heading is NOT stable across the six (competitive-positioning
# uses "### Step 7: Compose, Validate, and Post-Compose Coaching", step numbers run 7/8/8c/10/11,
# and market-sizing punctuates POST_COMPOSE_COACHING differently), so bound on the invocation
# itself, which every skill shares.
_CTX_B_OPEN = re.compile(r"check_handoff\.py --format=markdown|--format=markdown`\) verifies")
_CTX_B_CLOSE = re.compile(r"\*\*Retry budget:\*\*")


def _context_b_gate_block(body: str, skill: str) -> str:
    lines = body.splitlines()
    opens = [i for i, ln in enumerate(lines) if _CTX_B_OPEN.search(ln)]
    assert opens, f"{skill}: no Context B gate anchor (`--format=markdown`)"
    start = opens[-1]
    closes = [i for i, ln in enumerate(lines) if i > start and _CTX_B_CLOSE.search(ln)]
    assert closes, f"{skill}: no `**Retry budget:**` after the Context B gate anchor"
    block = "\n".join(lines[start : closes[0]])
    assert len(block.splitlines()) >= 5, f"{skill}: Context B gate block is only {len(block.splitlines())} lines"
    assert "insert_coaching.py" in block, f"{skill}: located block is not the Context B gate table"
    return block


@pytest.mark.parametrize("skill", SKILLS)
def test_context_b_gate_table_has_a_catch_all(skill: str) -> None:
    """Context B must carry an `Any other exit` row. Context A always had one; Context B had none.

    Two exits reach Context B with no dedicated row, and both were undocumented there:

      * exit 4 (`EXIT_BAD_JSON`) is raised in the `except OSError` around the file READ, which
        sits BEFORE the `--format` split -- so it is not json-mode-only, as the `--format` help
        text can be misread to imply. Gate 1 has already confirmed the file exists and is
        non-empty, so it fires on an IO/permission fault on a file that just stat'd clean.
      * invalid UTF-8 raises `UnicodeDecodeError`, which nothing catches at all: it surfaces as a
        traceback, i.e. an exit no typed row describes.

    An exit-4 row alone would not cover the second. The catch-all covers both, which is why the
    remediation chose it over the narrower edit.
    """
    block = _context_b_gate_block(_skill(skill), skill).lower()
    assert "any other exit" in block, (
        f"{skill}: the Context B gate table has no catch-all row. Context A's table ends with one; "
        "without it, an exit with no dedicated row (exit 4 on an IO fault, or an uncaught decode "
        "error) leaves the main thread with no documented branch at all."
    )


@pytest.mark.parametrize("doc", COMMENTARY_ENVELOPE_GUARDED, ids=lambda p: p.stem)
def test_no_document_asserts_the_unscoped_canonical_writer_claim(doc: Path) -> None:
    """No agent body or shared reference may say canonical artifacts are producer-script-only.

    The claim is FALSE as a statement about the system: the main thread writes several canonical
    artifacts by heredoc (market-sizing's methodology/validation, ic-sim's startup_profile and
    prior_artifacts, cap-table's inputs and scenario_requests, fmr's commentary). It appeared in
    22 places as the JUSTIFICATION for a correct sub-agent instruction ("write only OUTPUT_PATH"),
    which is how a false general claim survives review — the rule it supports is right, so nobody
    re-reads the reason.

    The sub-agent-scoped form ("you never write a canonical artifact") is true and is what the
    instruction actually needs. This guards the file set where the claim can do damage: agent
    bodies, which a sub-agent loads wholesale, and the shared reference, which contributors read
    as the source of truth. It deliberately does NOT scan SKILL.md dispatch templates — the same
    rescoping was applied there, but a fleet-wide ban would red on any future legitimate
    discussion of the producer contract in main-thread prose.
    """
    assert "producer-script-only" not in doc.read_text(encoding="utf-8"), (
        f"{doc.name} asserts that canonical artifacts are producer-script-only. They are not — "
        "the main thread writes several by heredoc. Scope the claim to the sub-agent instead: "
        '"you never write a canonical artifact".'
    )
