"""Drift guard for the shared skill-execution-model reference doc.

`founder-skills/references/skill-execution-model.md` used to tell readers to
stage ad-hoc files at `$REVIEW_DIR/.staging/` — advice that contradicts every
skill's actual SKILL.md Step 0, which stages scratch in a `/tmp` `$STAGING_DIR`
mktemp'd dir instead (see `test_skill_orchestration.py`'s
`test_skill_md_stages_scratch_outside_outputs`, which enforces the correct
pattern across every SKILL.md but does NOT read this reference file — no test
in the repo scanned the reference file at all before this one).

This test closes that gap: it asserts the reference file itself never
regresses back to recommending staging under the promoted `outputs/` work dir
(`$REVIEW_DIR` / `$ANALYSIS_DIR` / `$SIM_DIR`). Mirrors the
`_STAGING_UNDER_OUTPUTS` regex from `test_skill_orchestration.py`, pointed at
the reference file instead of the SKILL.md glob.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
REFERENCE_FILE = REPO_ROOT / "founder-skills" / "references" / "skill-execution-model.md"

# Mirrors test_skill_orchestration.py's _OUTPUTS_DIR_VARS / _STAGING_UNDER_OUTPUTS.
_OUTPUTS_DIR_VARS = r"(?:ANALYSIS_DIR|SIM_DIR|REVIEW_DIR)"
_STAGING_UNDER_OUTPUTS = re.compile(r"\$\{?" + _OUTPUTS_DIR_VARS + r"\}?/\.staging")


def test_reference_does_not_recommend_staging_under_outputs() -> None:
    """The reference must not recommend staging scratch under the promoted
    outputs/ work dir (`$REVIEW_DIR` / `$ANALYSIS_DIR` / `$SIM_DIR`).

    Correct advice: stage under a `/tmp` `$STAGING_DIR` mktemp'd dir.
    """
    text = REFERENCE_FILE.read_text(encoding="utf-8")
    hits: list[tuple[int, str]] = []
    for m in _STAGING_UNDER_OUTPUTS.finditer(text):
        ln = text.count("\n", 0, m.start()) + 1
        hits.append((ln, text.splitlines()[ln - 1].strip()[:90]))
    assert not hits, (
        f"{REFERENCE_FILE.relative_to(REPO_ROOT)}: recommends staging under the promoted "
        f"outputs/ work dir. Correct pattern is a /tmp $STAGING_DIR mktemp'd dir:\n"
        + "\n".join(f"  line {ln}: {txt}" for ln, txt in hits)
    )


def test_reference_clarifies_dispatch_tool_naming() -> None:
    """The SKILL.mds say "call the `Task` tool", but the dispatch tool's name is
    runtime-dependent (Claude Code/Cowork: `Task`; some newer builds: `Agent`).
    The shared reference must clarify this once — mirroring how it already notes
    the shell tool is `Bash` vs `mcp__workspace__bash` — and anchor the reader on
    the `subagent_type` pin (what actually binds) rather than the tool label."""
    text = REFERENCE_FILE.read_text(encoding="utf-8")
    assert "Agent" in text, "reference must mention the `Agent` alias for the dispatch tool"
    # The clarification must tie Task and Agent together as the same dispatch tool.
    assert re.search(r"`Task`[\s\S]{0,120}`Agent`|`Agent`[\s\S]{0,120}`Task`", text), (
        "reference must clarify that Task and Agent name the same sub-agent dispatch tool"
    )
    assert "subagent_type" in text, "reference must anchor on the subagent_type pin as the real binding"


# ---------------------------------------------------------------------------
# Truth-in-labelling guards (2026-08-31).
#
# WHY TESTS AND NOT PROSE. This file already carried a boxed retraction at
# `## Why Inline` ending "do not reintroduce it from git history" — and the
# sentence corrected below sat NINE LINES beneath it, wrong, through that
# retraction pass and every one since. A prose warning in this document is
# measured not to protect its own section. Each claim corrected in the
# 2026-08-29 external-review remediation therefore gets an assertion here.
#
# WHY WHOLE-FILE. Mirrors test_handoff_contract_ratchet.py's reasoning: a
# character-windowed negative stops checking once its target moves past the
# offset. Whole-file is safe for each token below because none of them has a
# legitimate occurrence anywhere in the document — verified before writing.
# ---------------------------------------------------------------------------


def _text() -> str:
    return REFERENCE_FILE.read_text(encoding="utf-8")


def _body(text: str | None = None) -> str:
    """The document minus its blockquote lines, flattened for prose matching.

    Retractions in this file are written as `>` blockquotes and MUST be able to
    quote the claim they retract — a retraction that cannot name its target is
    not a retraction. Scanning the whole file for a retracted phrase therefore
    fires on the correction itself, which is what happened the first time these
    tests ran. The assertive reintroduction this guards against would appear in
    body prose, not inside a block already marked as retracted.

    LIMIT, stated so nobody mistakes it for more: a reintroduction placed inside
    a blockquote is invisible here. That is a deliberate trade for letting the
    retraction quote its target, not an oversight.
    """
    src = _text() if text is None else text
    kept = [ln for ln in src.splitlines() if not ln.lstrip().startswith(">")]
    return " ".join(" ".join(kept).split()).lower()


def test_v040_incident_is_not_described_as_having_had_a_shell() -> None:
    """The v0.4.0 sub-agents had `{Read, Glob, Grep}` — the literal `Bash`
    name bound nothing (`docs/internal/cowork-architecture-and-v0.4.x-learning.md:62-63`).

    The retracted framing ("sub-agents with a working shell recipe still
    improvised") supports a stronger claim than the evidence: that correct,
    capability-backed instructions were ignored. What happened was a silent
    capability loss followed by fail-open improvisation. Those imply different
    fixes, and only the second is true.

    NEGATIVE ONLY on the retracted CLAIM, not on the word "shell" — the file
    legitimately discusses `mcp__workspace__bash` throughout `## Why Inline`.
    """
    flat = _body()
    for phrase in ("working shell recipe", "with a working shell"):
        assert phrase not in flat, (
            f"skill-execution-model.md reintroduces the retracted v0.4.0 framing ({phrase!r}). "
            "The sub-agents had no shell — the literal `Bash` name bound nothing."
        )
    assert "{read, glob, grep}" in flat, (
        "the anti-fabrication rationale must name the tool set the v0.4.0 sub-agents actually "
        "had ({Read, Glob, Grep}) — that IS the mechanism"
    )


def test_canonical_writer_claim_is_scoped_to_sub_agents() -> None:
    """ "CANONICAL artifacts are only ever written by producer scripts" was false.

    Eleven canonical artifacts across five skills are written directly by the
    MAIN THREAD via heredoc. The true, still-valuable claim is the sub-agent-scoped
    one, which `competitive-positioning/SKILL.md` already stated correctly.
    """
    flat = _body()
    assert "artifacts are only ever written by producer scripts" not in flat, (
        "skill-execution-model.md reasserts the unscoped canonical-writer claim. The main thread "
        "writes several canonical artifacts by heredoc; only the SUB-AGENT claim is true."
    )
    assert "no sub-agent writes a canonical artifact" in flat, (
        "the scoped form of the claim must be present — it is the load-bearing half"
    )
    assert "what this does not claim" in flat, (
        "the rescoped paragraph must state what it does NOT claim, or the next reader re-derives the unscoped version"
    )


def test_no_zero_reads_inputs_inlined_invariant() -> None:
    """There is no "zero reads, inputs inlined" Context A invariant.

    The three-way input rule says the opposite for under-`outputs/` artifacts
    ("Relative reads are preferred over inlining these"), and names ic-sim's
    all-inline variant as one skill's OPT-IN. The stale parenthetical was cited
    as THE mitigation for the un-gated workspace-shell escape hatch, so it
    reassured a reader about a risk it did not address.
    """
    flat = _body()
    assert "zero reads, inputs inlined" not in flat, (
        "skill-execution-model.md cites a 'zero reads, inputs inlined' Context A invariant. "
        "No such invariant exists — the three-way rule PREFERS relative reads for "
        "under-outputs artifacts. Cite the input rules instead."
    )
    assert "reachable by a relative `read` or inlined" in flat, (
        "the corrected mitigation must state the real rule (relative-read OR inlined), not a "
        "one-sided summary of it — the third input form is deliberately NOT readable"
    )


def test_write_boundary_states_that_nothing_detects_an_extra_write() -> None:
    """`check_handoff.py` exit 5 does NOT catch a stray write.

    `EXIT_PATH_MISMATCH` fires only when the receipt's ECHOED `output_path`
    fails `_paths_match`. A sub-agent that writes its hand-off file correctly
    and ALSO writes a canonical artifact echoes the right path and exits 0.

    Both the external review and two drafts of its remediation proposed the
    sentence "a stray write is caught by exit 5 rather than prevented" — which
    would have written a NEW false invariant into the document being corrected
    for false invariants. This test exists so the third attempt cannot.
    """
    flat = _body()
    assert "nothing detects an extra one" in flat, (
        "the Context A section must state that nothing detects a sub-agent's extra write — "
        "the boundary is a read-side contract, not a write-side restriction"
    )
    for wrong in ("stray write is caught by exit 5", "exit 5 catches a stray write"):
        assert wrong not in flat, (
            f"skill-execution-model.md claims exit 5 catches stray writes ({wrong!r}). It does "
            "not — exit 5 compares the RECEIPT'S ECHOED PATH, not the set of files written."
        )


def test_all_seven_gate_exit_codes_are_documented() -> None:
    """`check_handoff.py` defines seven exits; the reference documented five.

    Exit 8 is the one most worth documenting: per its own docstring it is
    reported AHEAD of exit 3 because both look identical from the file check
    yet need opposite responses (3 = the receipt may be fabricated; 8 = the
    agent complied and the path was wrong). A reader working from the stale
    table diagnoses a path bug as a lying model.

    Asserted against the SOURCE OF TRUTH rather than a hardcoded list, so a
    new exit code in the script reds this test instead of silently outdating
    the document again.
    """
    gate = REPO_ROOT / "founder-skills" / "scripts" / "check_handoff.py"
    codes = sorted(int(m) for m in re.findall(r"^EXIT_[A-Z_]+ = (\d+)$", gate.read_text(encoding="utf-8"), re.M))
    assert codes == [0, 3, 4, 5, 6, 7, 8], f"exit-code set changed: {codes}"
    flat = _body()
    for code in codes:
        if code == 0:
            continue
        assert f"exit {code}" in flat, (
            f"skill-execution-model.md does not document check_handoff.py exit {code}. "
            "Every typed exit needs a documented response — an undocumented one falls to the "
            "'any other exit -> STOP' catch-all, which is wrong for the recoverable ones."
        )
    # Matched against the whitespace-flattened body: the document wraps this phrase across a
    # line break with a two-space indent, so an exact "reported\nahead of exit 3" can never
    # match and was a dead disjunct.
    assert "ahead of exit 3" in flat, (
        "exit 8's documentation must state that it is reported ahead of exit 3, which is the "
        "whole reason it is a distinct code"
    )
