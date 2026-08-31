"""Static-analysis tests on SKILL.md: Bash usage must stay in main-thread blocks.

The v0.4.0 Cowork failure was: SKILL.md instructed sub-agents to run Bash. In
Cowork sub-agent contexts, the literal name `Bash` doesn't resolve (Bash is
registered as `mcp__workspace__bash` — see cowork-architecture-and-v0.4.x-
learning.md). So producer scripts never executed. v0.4.1 inverted this:
main thread (where the literal `Bash` name DOES resolve) runs scripts;
sub-agents get JSON-only payloads using names that DO resolve in their
context (Read/Edit/Glob/Grep).

Frontmatter checks parse the YAML directly (not substring match) so they're
robust to whitespace and value-form variations (e.g.,
`disable-model-invocation: true` vs `disable-model-invocation:\\n  true`).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILLS_DIR = REPO_ROOT / "founder-skills" / "skills"

SKILL_MD_FILES = sorted(SKILLS_DIR.glob("*/SKILL.md"))


def _parse_frontmatter(path: Path) -> dict[str, Any]:
    """Return the YAML-parsed frontmatter as a dict, or {} if missing."""
    text = path.read_text()
    match = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    if not match:
        return {}
    parsed = yaml.safe_load(match.group(1))
    return parsed if isinstance(parsed, dict) else {}


@pytest.mark.parametrize("skill_md", SKILL_MD_FILES, ids=lambda p: p.parent.name)
def test_outputs_mount_append_only_guardrail(skill_md: Path) -> None:
    """Every skill must carry an append-only guardrail for the WHOLE outputs mount
    in Step 0 (before any file work): never delete anything under the mount —
    including files the agent created itself — and never stage scratch under it.

    A sub-agent once created a VM->host scratch copy at the outputs-mount ROOT and
    rm'd it as delivery hygiene, tripping the platform's mount-wide delete-deny,
    because each skill's 'never delete' rule was scoped one directory too narrow
    (the per-skill artifacts dir, not the mount).
    """
    text = skill_md.read_text(encoding="utf-8")
    assert "### Step 1" in text, (
        f"{skill_md.parent.name} SKILL.md has no '### Step 1' anchor — the guardrail "
        "scope check would silently degrade to whole-file"
    )
    step0 = text.split("### Step 1")[0]
    assert "Outputs mount is append-only" in step0, (
        f"{skill_md.parent.name} Step 0 must carry the 'Outputs mount is append-only' guardrail"
    )
    assert "including files you created" in step0, (
        f"{skill_md.parent.name} append-only rule must forbid deleting files the agent created itself"
    )
    assert "scratch anywhere under the outputs mount" in step0, (
        f"{skill_md.parent.name} append-only rule must forbid staging scratch under the outputs mount"
    )


@pytest.mark.parametrize("skill_md", SKILL_MD_FILES, ids=lambda p: p.parent.name)
def test_skill_md_has_user_invocable_frontmatter(skill_md: Path) -> None:
    """v0.4.3 invariant: every SKILL.md declares user-invocable: true."""
    fm = _parse_frontmatter(skill_md)
    assert fm, f"{skill_md.relative_to(REPO_ROOT)} has no/empty frontmatter"
    assert fm.get("user-invocable") is True, (
        f"{skill_md.relative_to(REPO_ROOT)} missing or non-boolean "
        f"`user-invocable: true` (got {fm.get('user-invocable')!r})"
    )


@pytest.mark.parametrize("skill_md", SKILL_MD_FILES, ids=lambda p: p.parent.name)
def test_skill_md_does_not_disable_model_invocation(skill_md: Path) -> None:
    """v0.4.1 invariant: no SKILL.md sets disable-model-invocation: true.

    This was set in v0.3.x, removed in v0.4.1. Setting it again would force
    the skill onto the Cowork sub-agent dispatch path (where the literal
    `Bash` name doesn't resolve in the tool registry), reproducing the
    v0.4.0 failure mode.
    """
    fm = _parse_frontmatter(skill_md)
    assert fm.get("disable-model-invocation") is not True, (
        f"{skill_md.relative_to(REPO_ROOT)} sets disable-model-invocation:"
        " true — this puts the skill on the Cowork sub-agent dispatch path"
        " where the literal `Bash` name doesn't resolve. See"
        " cowork-architecture-and-v0.4.x-learning.md."
    )


@pytest.mark.parametrize("skill_md", SKILL_MD_FILES, ids=lambda p: p.parent.name)
def test_skill_md_uses_braced_plugin_root(skill_md: Path) -> None:
    """v0.4.3 invariant: ${CLAUDE_PLUGIN_ROOT} (braced), not bare $CLAUDE_PLUGIN_ROOT.

    Bare form depends on shell-expansion timing that Claude Code doesn't
    document as a guarantee for skill subprocesses.
    """
    text = skill_md.read_text()
    # Find bare $CLAUDE_PLUGIN_ROOT not followed by `}` (i.e., not the ${...} form).
    # Negative lookahead: not preceded by `{` either.
    bare = re.findall(r"(?<!\{)\$CLAUDE_PLUGIN_ROOT(?![}])", text)
    assert not bare, (
        f"{skill_md.relative_to(REPO_ROOT)} uses bare $CLAUDE_PLUGIN_ROOT "
        f"in {len(bare)} place(s); use ${{CLAUDE_PLUGIN_ROOT}} instead."
    )


# Per gist update 2026-05-10: plugin hooks declared in plugin.json never
# fire in Cowork sessions (desktop-side scope restriction excludes plugin
# scope; only ~/.claude/settings.json hooks fire). founder-skills'
# session-setup.sh is OK because ${CLAUDE_PLUGIN_ROOT} is substituted at
# skill-load time by the plugin content expander (v0.4.3 invariant) — the
# hook is defense-in-depth only. This test guards against future SKILL.md
# changes that would re-introduce a dependency on the hook firing.
_HOOK_DEPENDENT_PATTERNS = (
    # Bash idioms that suggest the hook (or some other env-setting thing
    # that doesn't run in Cowork) populated CLAUDE_PLUGIN_ROOT before the
    # SKILL.md ran. The braced ${CLAUDE_PLUGIN_ROOT} form (substituted at
    # load time) is fine; these idioms are not.
    re.compile(r"^\s*source\s+\S*session-setup\.sh", re.MULTILINE),
    re.compile(r"^\s*\.\s+\S*session-setup\.sh", re.MULTILINE),
    re.compile(r"\bCLAUDE_ENV_FILE\b"),  # the file the hook writes to
)


@pytest.mark.parametrize("skill_md", SKILL_MD_FILES, ids=lambda p: p.parent.name)
def test_skill_md_does_not_depend_on_session_start_hook(skill_md: Path) -> None:
    """v0.4.3+ invariant: SKILL.md must not depend on session-setup.sh
    actually running (it doesn't fire in Cowork). The braced
    ${CLAUDE_PLUGIN_ROOT} form, substituted at skill-load time by the
    plugin content expander, is the portable mechanism. Sourcing
    session-setup.sh from inside SKILL.md or referencing CLAUDE_ENV_FILE
    indicates a runtime hook dependency.

    Suppression: if a SKILL.md needs to mention these patterns legitimately
    (e.g., a comment explaining why we DON'T depend on the hook), add
    `<!-- skill-quality-ci: hook-mention-ok -->` on the same line or the
    line above. Mirrors Task 4's bash-after-subagent-ok suppression
    convention.
    """
    text = skill_md.read_text()
    suppress_marker = "<!-- skill-quality-ci: hook-mention-ok -->"
    lines = text.splitlines()
    hits: list[tuple[int, str]] = []
    for pattern in _HOOK_DEPENDENT_PATTERNS:
        for m in pattern.finditer(text):
            line_num = text.count("\n", 0, m.start()) + 1
            # Suppression: marker on this line or the line above.
            this_line = lines[line_num - 1] if line_num - 1 < len(lines) else ""
            prev_line = lines[line_num - 2] if line_num - 2 >= 0 else ""
            if suppress_marker in this_line or suppress_marker in prev_line:
                continue
            hits.append((line_num, m.group(0)[:80]))
    assert not hits, (
        f"{skill_md.relative_to(REPO_ROOT)} appears to depend on the "
        f"SessionStart hook firing (it doesn't fire in Cowork — see gist "
        f"yaniv-golan/303b6213b7a33167b3f98b076a5f81ad). Use ${{CLAUDE_PLUGIN_ROOT}} "
        f"directly instead, or add `<!-- skill-quality-ci: hook-mention-ok -->` "
        f"if this is an intentional reference.\n" + "\n".join(f"  line {ln}: {txt!r}" for ln, txt in hits)
    )


# Sub-agent-affirmative cue patterns (regex). Each pattern matches an
# instruction telling the agent TO dispatch a sub-agent — not negations.
# Match is case-insensitive. The negation check is *prefix-only* (only the
# part of the line BEFORE the cue match) so "Dispatch X. Do not Y." correctly
# treats the dispatch as affirmative (the "Do not" applies to Y, not X).
#
# Design notes (rev 5):
# - The bare `task` alternative was DROPPED from the dispatch cues — it
#   matched "Dispatch the Task tool" (Task as object, not subject) which is
#   not the v0.4.0 pattern.
# - The `via Task tool` cue requires a `dispatch(...)` anchor in the same
#   line BEFORE it — otherwise documentary mentions like "the harness uses
#   Task tool internally" fire false positives.
_SUBAGENT_AFFIRMATIVE_CUES = (
    # "Dispatch a sub-agent", "Dispatch the deck-review sub-agent", etc.
    # Note: `.+?\s+agent` matches "Dispatch the X agent" generically.
    re.compile(r"\bdispatch\s+(a|the)\s+(sub-?agent|.+?\s+agent)\b", re.IGNORECASE),
    re.compile(r"\bspawn\s+(a|the)\s+sub-?agent\b", re.IGNORECASE),
    # "Dispatch X via the Task tool" — require dispatch verb in line prefix.
    re.compile(
        r"\bdispatch(?:ed|ing|es)?\b[^\n]*?\bvia\s+(?:the\s+)?`?Task`?\s+tool\b",
        re.IGNORECASE,
    ),
)

# Negation tokens. Checked only in the line PREFIX before the cue match,
# not anywhere on the line — this distinguishes "Do not dispatch X" (negates
# the dispatch) from "Dispatch X. Do not Y." (does NOT negate the dispatch).
_NEGATION_TOKEN = re.compile(
    r"\b(do\s*not|don't|never|must\s+not|skip(?:\s+the)?|without|instead\s+of)\b",
    re.IGNORECASE,
)

# v0.4.0 footgun pattern: bash inside a sub-agent prompt template that
# the sub-agent is supposed to execute. Heuristic: a bash block that
# appears INSIDE a window suspiciously close to a sub-agent dispatch
# instruction. The legitimate v0.4.1 pattern (main thread runs bash to
# extract a payload, then dispatches) is silenced via suppression marker.
_WINDOW_LINES = 10


@pytest.mark.parametrize("skill_md", SKILL_MD_FILES, ids=lambda p: p.parent.name)
def test_skill_md_subagent_blocks_have_no_bash(skill_md: Path) -> None:
    """Heuristic: a sub-agent-affirmative cue followed within 10 lines by a
    fenced ```bash block is the v0.4.0 failure pattern.

    Negation handling: a "do NOT" / "skip" / "without" / "instead of" token
    appearing in the line PREFIX before the cue match negates the cue. A
    negation token appearing AFTER the cue is irrelevant ("Dispatch X. Do
    not also do Y." is still an affirmative dispatch).

    Suppression: add `<!-- skill-quality-ci: bash-after-subagent-ok -->`
    ANYWHERE between the cue line (inclusive) and the bash fence
    (exclusive). The full window between cue and bash is scanned.

    Note on adjacent cues: a single marker placed between two cues that
    share a downstream bash block silences findings for BOTH cues.
    """
    lines = skill_md.read_text().splitlines()
    suppress_marker = "<!-- skill-quality-ci: bash-after-subagent-ok -->"
    issues: list[tuple[int, str]] = []
    for i, line in enumerate(lines):
        # Find the first cue match anywhere in the line
        cue_match = None
        for pattern in _SUBAGENT_AFFIRMATIVE_CUES:
            m = pattern.search(line)
            if m:
                cue_match = m
                break
        if cue_match is None:
            continue
        # Negation check: only the line prefix BEFORE the cue match counts.
        prefix = line[: cue_match.start()]
        if _NEGATION_TOKEN.search(prefix):
            continue
        # Look ahead _WINDOW_LINES for ```bash
        window = lines[i + 1 : i + 1 + _WINDOW_LINES]
        for j, w in enumerate(window):
            if not w.strip().startswith("```bash"):
                continue
            # Suppression marker may appear ANYWHERE between the cue line
            # (inclusive) and the bash fence (exclusive). Scan that range.
            suppression_range = [lines[i], *window[:j]]
            if any(suppress_marker in s for s in suppression_range):
                break
            issues.append((i + 1, line.strip()[:80]))
            break
    assert not issues, (
        f"{skill_md.relative_to(REPO_ROOT)}: sub-agent dispatch cue followed"
        f" by ```bash within {_WINDOW_LINES} lines (v0.4.0 failure pattern):\n"
        + "\n".join(f"  line {ln}: {txt}" for ln, txt in issues)
        + "\n\nIf this is a legitimate payload-extraction-then-dispatch "
        "pattern (main thread extracts, then dispatches), add "
        "`<!-- skill-quality-ci: bash-after-subagent-ok -->` anywhere "
        "between the cue line and the bash block."
    )


# Producer pipes that write a pipeline artifact (-o <path>.json).
_PIPE_WRITES_JSON = re.compile(r'\.py\b[^\n|]*\s-o\s+"?[^"\n]*\.json')
# Scripts that write JSON but do not mint a run_id, exempt from the stamping
# check: orchestrators / renderers / receipts, plus artifacts that are NOT in
# the Context B run_id-parity set (FMR's model_data / extraction_validation are
# pre-pipeline extraction outputs, not parity artifacts).
_RUN_ID_EXEMPT_SCRIPTS = (
    "compose_report.py",  # consumes run_ids, does not mint them
    "visualize.py",
    "explore.py",
    "find_artifact.py",
    "founder_context.py",
    "extract_model.py",  # model_data.json — not a run_id-parity artifact
    "validate_extraction.py",  # extraction_validation.json — not parity-checked
    "validate_inputs.py",  # --fix -o corrects in place; preserves the input's metadata.run_id (not minted)
    "pptx_to_text.py",  # ingestion reader for a PowerPoint upload; writes /tmp scratch, not an artifact
)
# All six skills now stamp metadata.run_id from --run-id on the producer CLI.
# Two mechanisms exist (both satisfy the Context B run_id-parity check) and the
# pipe must carry --run-id either way:
#   - CLI-stamping: producer sets metadata.run_id from --run-id.
#   - stdin passthrough + CLI override: producer propagates stdin metadata.run_id
#     but --run-id (when passed, as the SKILL.md pipes now do) takes precedence.
# Its ABSENCE deterministically BLOCKED Context B in the ic-sim / market-sizing
# regression, so every artifact-writing producer pipe must pass it.


# Cowork-parity regression (fleet-wide): the promoted outputs/ tree is
# user-visible AND read-only-after-write in Cowork — staging scratch there or
# deleting anything there is a parity violation (Cowork can deny the delete,
# and the harness verdict flags it; crucially the harness text-scan can't
# resolve a shell `$VAR` to an outputs/ path — limitation H-A — so THIS pytest
# is the real guard, not the verdict). Every skill resolves its work dir into a
# `$<X>_DIR` variable under outputs/artifacts/ (ANALYSIS_DIR / SIM_DIR /
# REVIEW_DIR). The two hazards:
#   1. `.staging` UNDER that dir (`"$REVIEW_DIR/.staging"`). Fix: stage scratch
#      in a `$STAGING_DIR` mktemp'd under /tmp. Matched by `/<>.staging` with a
#      LITERAL slash before `.staging` — so the `$STAGING_DIR` mktemp template
#      itself (`/tmp/<skill>-${SLUG}.staging.XXXXXX`, `.staging` preceded by
#      `}`) is NOT matched.
#   2. a bash `rm` whose target is one of those dir vars (the old fresh-start
#      bulk-delete). Fix: overwrite-in-place — producers rewrite via `-o`, and
#      compose's STALE_ARTIFACT (run_ids must match) catches a skipped-step
#      stale leftover. deck-review's fresh-start is a Python `os.remove` in
#      setup_run.py (invisible to a bash scan, resume-guarded) — NOT a bash rm,
#      so it's correctly not matched here.
_OUTPUTS_DIR_VARS = r"(?:ANALYSIS_DIR|SIM_DIR|REVIEW_DIR)"
_STAGING_UNDER_OUTPUTS = re.compile(r"\$\{?" + _OUTPUTS_DIR_VARS + r"\}?/\.staging")
_BASH_RM_OF_OUTPUTS = re.compile(r"\brm\b[^\n`]*\$\{?" + _OUTPUTS_DIR_VARS + r"\b")
# A `mv` whose SOURCE (first path arg) is an outputs var DELETES that outputs file — Cowork denies
# deletes under outputs/, and the live fmr sweep failed `no_delete_in_outputs` on exactly this
# (`mv "$REVIEW_DIR/corrected_inputs.json" "$REVIEW_DIR/inputs.json"`). `mv <tmp> <outputs>` (creating
# IN outputs) is fine and not matched; the safe move into outputs is `cp` (overwrite-in-place). The
# the outputs var must be the FIRST path arg (the source), so `mv <tmp> <outputs>` (a create IN outputs)
# is NOT flagged, and a backtick-wrapped prose "use `mv`" is excluded (backtick breaks the `\s+`).
_BASH_MV_FROM_OUTPUTS = re.compile(r"\bmv\b\s+(?:-\w+\s+)?\"?\$\{?" + _OUTPUTS_DIR_VARS + r"\b")


@pytest.mark.parametrize("skill_md", SKILL_MD_FILES, ids=lambda p: p.parent.name)
def test_skill_md_stages_scratch_outside_outputs(skill_md: Path) -> None:
    """No SKILL.md may stage scratch under, `rm`, or `mv`-from, the promoted
    outputs/ work dir (`$ANALYSIS_DIR` / `$SIM_DIR` / `$REVIEW_DIR`).

    All are Cowork-parity violations (outputs/ is user-visible; a delete there is
    denied and trips `no_delete_in_outputs`). Stage scratch under a `/tmp`
    `$STAGING_DIR`; overwrite-in-place with `cp` (never `mv`-from-outputs, which
    deletes the source) instead of bulk-deleting. NOTE: the harness delete scan
    also flags an `rm` token co-occurring with a literal `outputs` path in ONE
    command (`isOutputsDelete`), so never put an `rm` on a line that also
    references an outputs path — even when the `rm` targets /tmp.
    """
    text = skill_md.read_text(encoding="utf-8")
    hits: list[tuple[int, str]] = []
    for label, pat in (
        ("staging-under-outputs", _STAGING_UNDER_OUTPUTS),
        ("bash-rm-of-outputs", _BASH_RM_OF_OUTPUTS),
        ("bash-mv-from-outputs", _BASH_MV_FROM_OUTPUTS),
    ):
        for m in pat.finditer(text):
            ln = text.count("\n", 0, m.start()) + 1
            hits.append((ln, f"[{label}] {text.splitlines()[ln - 1].strip()[:90]}"))
    assert not hits, (
        f"{skill_md.relative_to(REPO_ROOT)}: Cowork-parity violation under the promoted outputs/ "
        f"work dir. Stage scratch in a /tmp $STAGING_DIR; overwrite-in-place instead of bulk-rm "
        f"(see compose's STALE_ARTIFACT backstop):\n" + "\n".join(f"  line {ln}: {txt}" for ln, txt in hits)
    )


# Dispatch-prompt templates all start with a `CONTEXT: <NAME>` header line (the
# sub-agent's dispatch envelope). A type-less Task dispatch silently falls back to
# the built-in `general-purpose` agent (tools:["*"] — workspace bash included, and
# the scoped agent's persona/rubric discarded), which fired routinely in real
# traffic. Each dispatch instruction must therefore pin the literal
# `subagent_type: "founder-skills:<skill>"`. Keyed on the CONTEXT: templates (not
# fuzzy prose cues) so it can't false-positive on descriptive mentions.
_DISPATCH_TEMPLATE_HEADER = re.compile(r"(?m)^CONTEXT:\s*\S")


@pytest.mark.parametrize("skill_md", SKILL_MD_FILES, ids=lambda p: p.parent.name)
def test_skill_md_dispatches_pin_subagent_type(skill_md: Path) -> None:
    """A skill with CONTEXT:-headed dispatch templates must pin the literal
    `subagent_type: "founder-skills:<skill>"` (C3 — closes the type-less
    `general-purpose` fallback trap: a type-less Task dispatch resolves to the
    built-in general-purpose agent with tools:["*"], discarding the scoped
    agent's allowlist AND persona/rubric).

    This is the coarse regression guard (a skill that dispatches but never pins
    the type at all). Per-dispatch coverage — including parallel dispatches that
    legitimately pin once for several templates — is verified in review, not by a
    raw pin>=template count. Dispatch-prompt reference lane files (e.g.
    cap-table/references/lanes/*.md) are folded in so a lane-file dispatch counts."""
    skill_name = skill_md.parent.name
    pin = f'subagent_type: "founder-skills:{skill_name}"'
    texts = [skill_md.read_text(encoding="utf-8")]
    ref_dir = skill_md.parent / "references"
    if ref_dir.is_dir():
        texts.extend(p.read_text(encoding="utf-8") for p in sorted(ref_dir.rglob("*.md")))
    joined = "\n".join(texts)
    if not _DISPATCH_TEMPLATE_HEADER.search(joined):
        return  # no sub-agent dispatch templates → nothing to pin
    assert pin in joined, (
        f"{skill_md.relative_to(REPO_ROOT)}: has CONTEXT: dispatch template(s) but never pins "
        f"`{pin}`. A type-less Task dispatch falls back to the wildcard general-purpose agent "
        f"(bash-capable; scoped persona/rubric discarded)."
    )


@pytest.mark.parametrize("skill_md", SKILL_MD_FILES, ids=lambda p: p.parent.name)
def test_producer_pipes_carry_run_id(skill_md: Path) -> None:
    """Every `... script.py ... -o <artifact>.json` invocation in a SKILL.md
    bash block must pass --run-id so the producer stamps metadata.run_id
    (regression guard for the ic-sim / market-sizing Context B blocker)."""
    text = skill_md.read_text(encoding="utf-8")
    offenders: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not _PIPE_WRITES_JSON.search(line):
            continue
        if any(exempt in line for exempt in _RUN_ID_EXEMPT_SCRIPTS):
            continue
        if "--run-id" not in line:
            offenders.append(line[:100])
    assert not offenders, (
        f"{skill_md.relative_to(REPO_ROOT)}: artifact-writing producer pipe(s) "
        f"missing --run-id (Context B run_id-parity will BLOCK):\n" + "\n".join(f"  {o}" for o in offenders)
    )


def test_cap_table_skill_md_runs_coverage_detection_in_numbered_step_4() -> None:
    """P3 regression guard: `detect_structure.py` must be invoked inside the
    numbered Step 4 (cap_state) section, not only documented in the side-section
    '## Coverage & Disclosure'. Before this fix the numbered Step 2->5 spine
    never called detect_structure.py at all — a reader following the numbered
    steps top-to-bottom could silently skip coverage detection and the
    hand-rolled-figure ban entirely. This asserts the closing action added to
    the end of Step 4 (before the Step 4.5 pre-math audit) survives; it fails
    if that action is later removed and detect_structure.py is left living
    only in the side-section prose."""
    skill_md = SKILLS_DIR / "cap-table" / "SKILL.md"
    text = skill_md.read_text(encoding="utf-8")
    step4_heading = re.search(r"^### Step 4:.*$", text, re.MULTILINE)
    step4_5_heading = re.search(r"^### Step 4\.5:.*$", text, re.MULTILINE)
    assert step4_heading and step4_5_heading, (
        f"{skill_md.relative_to(REPO_ROOT)}: expected '### Step 4:' and "
        "'### Step 4.5:' headings to anchor the numbered-step region on — "
        "one or both are missing."
    )
    step4_region = text[step4_heading.end() : step4_5_heading.start()]
    assert "detect_structure.py" in step4_region, (
        f"{skill_md.relative_to(REPO_ROOT)}: 'detect_structure.py' no longer appears "
        "between the Step 4 and Step 4.5 headings — coverage detection must be "
        "invoked from the numbered spine (Step 4's closing action), not only from "
        "the '## Coverage & Disclosure' side-section, or it silently gets skipped."
    )


def test_fmr_step3_branches_on_model_format_before_dispatching() -> None:
    """Step 3's INPUTS_REVIEW dispatch must branch on `model_format` FIRST.

    The dispatch template hardcodes "Read model_data.json … (the full extraction
    output)", and on a conversational/deck run that file does not exist and never
    will — nothing was extracted. Step 3 previously carried no `model_format`
    conditional at all, so the rule was not buried, it was absent. Sent anyway,
    the sub-agent is asked for a missing file and the failure is not a clean error
    but an improvisation: reconstructed values, or the main thread abandoning the
    pipeline to hand-compute.
    """
    skill_md = (SKILLS_DIR / "financial-model-review" / "SKILL.md").read_text(encoding="utf-8")
    step3 = skill_md.index("### Step 3: INPUTS_REVIEW Dispatch")
    step35 = skill_md.index("### Step 3.5:")
    block = " ".join(skill_md[step3:step35].split())

    # The branch must come before the dispatch template it guards.
    branch_at = block.index("branch on `model_format`")
    template_at = block.index("Dispatch prompt template")
    assert branch_at < template_at, "the model_format branch must precede the dispatch template"

    assert "skip the INPUTS_REVIEW dispatch entirely" in block, (
        "the conversational branch must say to skip the dispatch, not just describe the difference"
    )
    assert "there is no `model_data.json` and there never will be" in block, (
        "must state the file's permanent absence — otherwise the model waits for or invents it"
    )
    assert "Author `inputs.json` directly" in block, "must say what to do instead of dispatching"


def test_fmr_conversational_path_has_the_same_stop_as_the_file_path() -> None:
    """Path B's numbers-confirmation gate must be a STOP, exactly like Path A's.

    Path A read "This is a STOP point — do not proceed to Step 4 until the founder
    responds", with a rationale. Path B was a single unemphasised sentence with
    neither, so the founder's confirmation of the numbers before math ran on them
    was optional-by-phrasing — on the path where the numbers are LEAST verifiable.
    """
    skill_md = (SKILLS_DIR / "financial-model-review" / "SKILL.md").read_text(encoding="utf-8")
    path_b = skill_md.index("**Path B — Conversational**")
    step4 = skill_md.index("### Step 4:")
    block = " ".join(skill_md[path_b:step4].split())

    assert "This is a STOP point — do not proceed to Step 4 until the founder responds." in block, (
        "Path B must carry Path A's STOP language verbatim"
    )
    assert "last check on the numbers before math runs" in block, (
        "the STOP needs Path A's rationale too — an unexplained gate gets optimised away"
    )
    assert "It matters *more* here, not less" in block, (
        "must say why the conversational path needs the gate more, not less, than the file path"
    )


ALL_SKILLS = [
    "market-sizing",
    "financial-model-review",
    "ic-sim",
    "deck-review",
    "competitive-positioning",
    "cap-table",
]


@pytest.mark.parametrize("skill", ALL_SKILLS)
def test_no_dispatch_template_ends_a_line_promising_content_that_never_follows(skill: str) -> None:
    """A dispatch template must not dangle "… is:" with nothing after it.

    All six skills shipped the Context B template saying "The structured
    coaching_payload from report.json is:" followed by a blank line — the payload is
    STAGED as a file, never inlined, so the sentence promised content that does not
    exist. A live run filled the gap with its own judgment and added a narrative
    paragraph beside the scored figures.

    Colon-terminated lines are fine when content follows; the defect is the dangle.
    """
    text = (SKILLS_DIR / skill / "SKILL.md").read_text(encoding="utf-8")
    lines = text.splitlines()
    offenders: list[str] = []
    for i, line in enumerate(lines):
        stripped = line.rstrip()
        if not re.search(r"\b(is|are|follows)\s*:$", stripped):
            continue
        # Look at the next non-empty line. A dangle is: blank line, then something
        # that is plainly not the promised content (a new instruction/heading).
        nxt = ""
        for cand in lines[i + 1 : i + 4]:
            if cand.strip():
                nxt = cand.strip()
                break
        if lines[i + 1 : i + 2] == [""] and (nxt.startswith(("Read ", "#", "**", "Follow ")) or not nxt):
            offenders.append(f"{i + 1}: {stripped!r} -> {nxt[:60]!r}")
    assert not offenders, f"{skill}/SKILL.md has a line promising content that never follows:\n  " + "\n  ".join(
        offenders
    )


@pytest.mark.parametrize("skill", ALL_SKILLS)
def test_no_dispatch_template_hides_a_shape_behind_an_ellipsis(skill: str) -> None:
    """A dispatch template must SHOW the shape it asks a sub-agent to produce.

    Second instance of this class. The first was a colon dangling with nothing
    after it; this one was `"suggested_additions": [...newly discovered...]` — the
    sub-agent could not know the field names, invented `why_suggested` where the
    schema says `rationale`, and the producer rejected it, costing a repair
    round-trip.

    An ellipsis is fine in prose and fine for values ("description": "..."), but a
    LIST whose element shape is elided is a shape the sub-agent has to guess.
    """
    text = (SKILLS_DIR / skill / "SKILL.md").read_text(encoding="utf-8")
    offenders = [
        f"{i + 1}: {line.strip()}"
        for i, line in enumerate(text.splitlines())
        if re.match(r'^\s*"[a-z_]+":\s*\[\.\.\..*\.\.\.\]', line)
    ]
    assert not offenders, (
        f"{skill}/SKILL.md elides a list element shape a sub-agent must produce:\n  "
        + "\n  ".join(offenders)
        + "\nShow one concrete element instead — the field names are not guessable."
    )


# ---------------------------------------------------------------------------
# Per-dispatch subagent_type coverage (defect #2 in
# 2026-08-01-founder-skills-defects-found.md): the coarse pin check above only
# asserts the pin string appears SOMEWHERE in the joined text. market-sizing's
# prose at one line correctly instructs "pin subagent_type on both calls", and
# its own fenced pseudocode four lines below silently omits it on both Task(
# calls — the coarse check cannot see that, because the pin string is present
# in the PROSE sentence and the assert never looks inside the fenced block the
# model will actually copy from. The docstring above names this as
# review-only-covered ("Per-dispatch coverage ... is verified in review, not by
# a raw pin>=template count"); the coarse check's own author flagged the gap.
#
# This closes it mechanically: every `Task(` call inside a fenced code block
# must carry `subagent_type=` INSIDE THAT SAME CALL's argument list, not merely
# somewhere in the surrounding prose. A naive `Task\(...\)` regex breaks the
# moment a prompt string contains its own parenthesis (market-sizing's own
# templates interpolate free text like "<research data from validation.json>"),
# so the call's extent is found by a balanced-paren scan that treats quoted
# string contents as opaque — the same reason a hand-rolled JSON parser is
# wrong when `json.loads` exists, just for parens instead of braces.
_FENCE = re.compile(r"(?m)^```[^\n]*\n(.*?)^```", re.DOTALL)
_TASK_CALL_START = re.compile(r"\bTask\(")
_PIN_KWARG = re.compile(r"subagent_type\s*=")


def _fenced_blocks(text: str) -> list[str]:
    """Every fenced code block's inner content, in order.

    Anchored to line-start (`(?m)^```) — an earlier unanchored version matched
    the first ``` ANYWHERE, including inline prose that describes fence syntax
    literally (`` ` ```json ... ``` ` `` — cap-table's own JSON-extraction
    protocol paragraph does this to explain what a fence looks like). That
    desynchronized every open/close pairing for the rest of the file from the
    first such mention onward, producing a bogus "fenced block" spanning real
    prose and a false positive on content nowhere near a real ``` fence.
    """
    return [m.group(1) for m in _FENCE.finditer(text)]


def _extract_call_args(text: str, open_paren_index: int) -> str | None:
    """The argument-list text of a call whose `(` is at `open_paren_index`.

    Walks forward tracking paren depth, treating the contents of a single- or
    double-quoted string as opaque (an escaped quote does not close it, and a
    paren inside a string does not count toward depth) — pseudocode Task(...)
    calls embed quoted prompt strings that may themselves contain parens or
    unbalanced-looking text. Returns None if the call is never closed (should
    not happen in well-formed fenced pseudocode; treated as "nothing to check"
    rather than crashing the test on a markdown-fence edge case).
    """
    depth = 1
    i = open_paren_index + 1
    quote: str | None = None
    start = i
    n = len(text)
    while i < n:
        ch = text[i]
        if quote is not None:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = None
        elif ch == "#":
            # Skip to end of line. A `#` comment INSIDE the argument list is not
            # hypothetical: cap-table's real dispatch templates carry
            # `# REQUIRED — omitting it silently downgrades…` between kwargs, and
            # the defects doc recommends propagating that style to the skill this
            # test exists to fix. Without this branch a `)` in a comment closes
            # the call early (false positive on a CONFORMING call), and an
            # apostrophe in a comment opens a phantom string that swallows the
            # rest of the block (silent skip — a false NEGATIVE on exactly the
            # defect class this test catches).
            nl = text.find("\n", i)
            if nl == -1:
                return None
            i = nl + 1
            continue
        elif ch in "\"'":
            quote = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return text[start:i]
        i += 1
    return None


# --- unit coverage for the two helpers above, on synthetic strings ---


def test_fenced_blocks_ignores_inline_fence_syntax_in_prose() -> None:
    """Regression: an EARLIER unanchored version of `_FENCE` matched the first
    ``` occurring ANYWHERE, including inline prose that describes fence syntax
    literally — cap-table's own JSON-extraction paragraph does exactly this
    (`` ` ```json ... ``` ` ``) — which desynchronized every open/close pairing
    downstream and produced a false positive on ordinary prose nowhere near a
    real fence. Caught by running this test's assertion against real SKILL.md
    content before the anchor fix landed.
    """
    text = (
        "Some prose that says a reply may be wrapped in ` ```json ... ``` ` fences,\n"
        "or plain ` ``` ... ``` `.\n\n"
        "```\n"
        'Task(subagent_type="founder-skills:x")\n'
        "```\n"
    )
    blocks = _fenced_blocks(text)
    assert len(blocks) == 1
    assert "subagent_type" in blocks[0]


def test_extract_call_args_handles_parens_inside_quoted_strings() -> None:
    r"""The scanner must treat a paren INSIDE a quoted prompt string as opaque —
    market-sizing's own templates interpolate free text like
    "<research data (see validation.json)>", and a naive `Task\([^)]*\)` regex
    would close the call at that embedded `)` instead of the real one.
    """
    block = 'Task(description="x", prompt="<research data (see validation.json)>", subagent_type="founder-skills:x")'
    start = block.index("Task(")
    args = _extract_call_args(block, start + len("Task") + 1 - 1)
    assert args is not None
    assert "subagent_type" in args
    assert args.endswith('subagent_type="founder-skills:x"')


def test_extract_call_args_returns_none_on_unclosed_call() -> None:
    """An unclosed call must not be reported as a violation (nor crash) — that
    is a markdown-authoring defect this test is not responsible for diagnosing.
    """
    block = 'Task(description="x", prompt="unterminated'
    start = block.index("Task(")
    assert _extract_call_args(block, start + len("Task") + 1 - 1) is None


def test_fenced_task_scan_flags_missing_pin_and_clears_present_pin() -> None:
    """Direct check of the scan-and-flag logic the parametrized test drives,
    on a synthetic two-call block mirroring market-sizing's real shape: one
    call correctly pinned, one not — must flag exactly the unpinned one.
    """
    block = (
        "[\n"
        '  Task(description="a", prompt="CONTEXT: A", subagent_type="founder-skills:x"),\n'
        '  Task(description="b", prompt="CONTEXT: B"),\n'
        "]\n"
    )
    calls = list(_TASK_CALL_START.finditer(block))
    assert len(calls) == 2
    pinned = [_PIN_KWARG.search(_extract_call_args(block, m.end() - 1) or "") is not None for m in calls]
    assert pinned == [True, False]


@pytest.mark.parametrize("skill_md", SKILL_MD_FILES, ids=lambda p: p.parent.name)
def test_fenced_task_calls_pin_subagent_type_individually(skill_md: Path) -> None:
    """Every `Task(` inside a fenced pseudocode block pins `subagent_type=`
    WITHIN ITS OWN argument list — closes defect #2: the coarse check above
    only proves the pin string exists somewhere in the file, which a correctly
    worded PROSE sentence satisfies even when the fenced example right below it
    contradicts it. The model copies the fenced form, not the prose.

    Reference lane files (cap-table's references/lanes/*.md) are folded in —
    same set the coarse check above scans — since a lane file's fenced Task(
    call is exactly as copyable as one in SKILL.md itself.
    """
    skill_name = skill_md.parent.name
    sources: list[tuple[str, str]] = [(str(skill_md.relative_to(REPO_ROOT)), skill_md.read_text(encoding="utf-8"))]
    ref_dir = skill_md.parent / "references"
    if ref_dir.is_dir():
        for p in sorted(ref_dir.rglob("*.md")):
            sources.append((str(p.relative_to(REPO_ROOT)), p.read_text(encoding="utf-8")))

    offenders: list[str] = []
    for rel_path, text in sources:
        for block in _fenced_blocks(text):
            for m in _TASK_CALL_START.finditer(block):
                args = _extract_call_args(block, m.end() - 1)
                if args is None:
                    continue  # malformed/unclosed call — not this test's job to diagnose
                if not _PIN_KWARG.search(args):
                    snippet = block[m.start() : m.start() + 90].replace("\n", " ")
                    offenders.append(f"{rel_path}: {snippet}...")

    assert not offenders, (
        f"{skill_name}: fenced Task( call(s) with no `subagent_type=` in their OWN argument list "
        f"(a type-less dispatch falls back to the wildcard general-purpose agent — bash-capable, "
        f"scoped persona/rubric discarded). Prose stating the pin elsewhere in the file does not "
        f"satisfy this; the model copies the fenced example, not the sentence above it:\n  " + "\n  ".join(offenders)
    )


# Specimens for the detector above, exercised through the WHOLE chain -- fence detection, call
# detection, argument extraction, pin check -- not just the arg parser, which already has its own
# test. Every BAD form must be flagged and every OK form spared.
#
# What this guards is not cosmetic: a `Task(` with no `subagent_type=` falls back to the wildcard
# `general-purpose` agent, which is bash-capable. This fleet's Context A sub-agents are declared
# WITHOUT a shell on purpose, so a type-less dispatch silently hands one a shell and discards the
# scoped persona. The model copies the fenced example, not the prose above it.
_TASK_SPECIMENS_BAD = [
    ("bare call", '```python\nTask(description="extract", prompt="…")\n```'),
    (
        "pin in prose, not in the call",
        'Always pass `subagent_type=`.\n\n```python\nTask(description="d", prompt="p")\n```',
    ),
    (
        "pinned sibling, unpinned neighbour",
        '```python\nTask(subagent_type="founder-skills:cap-table", description="a")\n'
        'Task(description="b", prompt="p")\n```',
    ),
]
_TASK_SPECIMENS_OK = [
    ("pinned", '```python\nTask(subagent_type="founder-skills:cap-table", description="d")\n```'),
    (
        "pinned with a comment carrying a paren",
        "```python\nTask(  # REQUIRED (omitting it downgrades the agent)\n"
        '  subagent_type="founder-skills:cap-table", description="d")\n```',
    ),
    ("no fenced call at all", "Prose about Task( dispatch that is not inside a fence."),
]


def test_the_task_pin_detector_catches_an_unpinned_dispatch() -> None:
    """End-to-end specimens for the scan above — CORRECTING a premise, so it is not re-derived.

    That scan looked blind-vacuous when run alone: blinding its call-detection regex and running only
    that test leaves it green. It is NOT unguarded. Two neighbouring tests already cover its parts —
    one exercises the matcher on a synthetic block, another the fence detector — and blinding either
    reds them. Running a detector in isolation is not how the suite runs, and the isolation reading
    produced a false "vacuous" verdict that reached a written review.

    What those two do NOT cover, and what this adds, is the whole chain plus the defect class the
    scan's own docstring names: a pin stated in PROSE while the fenced call beside it omits it. The
    model copies the fence, not the sentence. That case passes through fence detection and the matcher
    individually, and only fails when they are composed.

    Stakes, since they are easy to understate: a `Task(` with no `subagent_type=` falls back to the
    wildcard general-purpose agent, which is bash-capable. This fleet's Context A sub-agents are
    declared WITHOUT a shell deliberately.
    """

    def _offenders(text: str) -> list[str]:
        out = []
        for block in _fenced_blocks(text):
            for m in _TASK_CALL_START.finditer(block):
                args = _extract_call_args(block, m.end() - 1)
                if args is None:
                    continue
                if not _PIN_KWARG.search(args):
                    out.append(block[m.start() : m.start() + 60])
        return out

    for label, text in _TASK_SPECIMENS_BAD:
        assert _offenders(text), f"an unpinned dispatch is no longer caught ({label}) — a type-less "
    for label, text in _TASK_SPECIMENS_OK:
        assert not _offenders(text), f"a conforming dispatch is flagged ({label})"


def test_extract_call_args_skips_hash_comments_inside_the_arg_list() -> None:
    """A `#` comment between kwargs must not truncate or derail the scan.

    Both failure modes found by adversarial review, and both reachable via the
    in-tree comment convention (`# REQUIRED — omitting it silently downgrades…`)
    that the defects doc recommends spreading to more dispatch templates:
      * a `)` inside the comment closed the call early -> the pin looked absent
        -> FALSE POSITIVE against a conforming call;
      * an apostrophe opened a phantom string -> scan ran off the end and
        returned None -> the call was SILENTLY SKIPPED, a false negative on the
        very defect class this guard exists to catch.
    """
    paren = 'Task(  # note ) here\n  subagent_type="founder-skills:x", description="d")'
    args = _extract_call_args(paren, paren.index("Task(") + 4)
    assert args is not None and _PIN_KWARG.search(args), "a ) inside a comment must not close the call"

    apostrophe = 'Task(  # don\'t omit this\n  subagent_type="founder-skills:x", description="d")'
    args2 = _extract_call_args(apostrophe, apostrophe.index("Task(") + 4)
    assert args2 is not None, "an apostrophe in a comment must not open a phantom string"
    assert _PIN_KWARG.search(args2)


def test_extract_call_args_still_flags_an_unpinned_call_carrying_a_comment() -> None:
    """The comment skip must not become a way to hide a missing pin."""
    block = 'Task(  # some note\n  description="d", prompt="CONTEXT: X")'
    args = _extract_call_args(block, block.index("Task(") + 4)
    assert args is not None
    assert _PIN_KWARG.search(args) is None


@pytest.mark.parametrize("skill_md", SKILL_MD_FILES, ids=lambda p: p.parent.name)
def test_leak_prone_steps_supply_the_founder_line(skill_md: Path) -> None:
    """The narration rule is stated once, far from where it is broken. Supply the line instead.

    Measured across live runs of deck-review, every founder-facing plumbing leak occurred at a
    Context A hand-off or the Context B coaching step -- "gating the hand-off and piping through
    the producer", "staging the coaching payload", "dispatching the coaching commentary
    sub-agent" -- and none anywhere else. The cause is priming, not carelessness: those sections
    are the densest plumbing in the file, so a model composing its next progress line reaches for
    the vocabulary in front of it, and a general prohibition hundreds of lines earlier loses.

    The remedy attempted here is substitution rather than more prohibition: the exact sentence
    sits next to the machinery.

    MEASURED INEFFECTIVE, and recorded as such rather than quietly kept. A verification run
    with these lines in place still emitted "Now gating and piping the hand-off through the
    producer" -- the very phrase the table four lines above the machinery replaces. Per-block
    leak rate went 15.8% / 7.1% / 6.7% before to 14.3% after: noise, not a fix. Three distinct
    prose approaches have now failed (global ban, per-step ban, supplied line), so the next
    attempt should not be a fourth phrasing -- the working hypothesis is that the model echoes
    the vocabulary it is CURRENTLY reading, which points at moving the plumbing out of the main
    thread's reading path.

    The lines are kept because they cost nothing and carry their evidence; this test guards
    them from silent deletion. It does NOT assert they work.
    """
    if skill_md.parent.name != "deck-review":
        pytest.skip("measured on deck-review; extend per skill as each is verified live")
    text = skill_md.read_text(encoding="utf-8")
    for anchor, marker in (
        ("### Context A hand-off protocol", "say exactly"),
        ("### Step 7:", "Say exactly:"),
    ):
        start = text.find(anchor)
        assert start != -1, f"anchor missing: {anchor}"
        window = text[start : start + 1500]
        assert marker.lower() in window.lower(), (
            f"{anchor} no longer supplies a verbatim founder-facing line ({marker!r}). "
            "Restate it rather than relying on the global narration rule — that rule is already "
            "in the file and these are the sites where it measurably fails."
        )


# ---------------------------------------------------------------------------
# Heredoc quoting: the fleet rule, and cap-table's documented exception.
#
# `market-sizing/SKILL.md` states the rule ("always single-quote the delimiter
# when the body may contain a `$`") because an UNQUOTED delimiter lets the shell
# expand `$`-bearing values: a literal `$8M` becomes `M` before it reaches the
# file. cap-table cannot follow it as stated -- its two templated heredocs
# interpolate `$RUN_ID` / `$(date …)` and MUST stay unquoted -- so the fleet rule
# read as a rule cap-table silently violated.
#
# This ships as a TEST and not a fourth paragraph of prose deliberately. The
# note at test_skill_md_narration_rule_is_colocated_with_dispatch records that
# three prose approaches to a *different* guardrail were measured ineffective.
# That finding is about narration-vocabulary echo, a different failure class
# from a factual quoting instruction -- but a cheap mechanical check exists here,
# so there is no reason to rely on wording at all.
# ---------------------------------------------------------------------------

# BOTH orderings occur in this repo and an earlier version matched only the first, making the
# escape check a silent no-op for three skills: `cat <<DELIM > "path"` (cap-table, ic-sim,
# market-sizing) and `cat > "path" <<DELIM` (financial-model-review:735). Delimiters may carry
# digits. Groups are normalised to (delimiter, target) by _heredocs() below.
_HEREDOC_A = re.compile(r"cat\s+<<(?P<q>')?(?P<delim>[A-Z][A-Z0-9_]*)(?(q)')\s*>\s*\"(?P<target>[^\"]+)\"")
_HEREDOC_B = re.compile(r"cat\s*>\s*\"(?P<target>[^\"]+)\"\s*<<(?P<q>')?(?P<delim>[A-Z][A-Z0-9_]*)(?(q)')")


def _heredocs(body: str) -> list[tuple[str, str, bool, int]]:
    """Every `cat`-heredoc in a SKILL.md as (delimiter, target, quoted, match_offset).

    Covers both orderings (see the note on the patterns above). `quoted` is True when the
    delimiter is single-quoted, i.e. the body does NOT interpolate and a literal `$` is safe.
    """
    found: list[tuple[str, str, bool, int]] = []
    for pattern in (_HEREDOC_A, _HEREDOC_B):
        for m in pattern.finditer(body):
            found.append((m.group("delim"), m.group("target"), m.group("q") == "'", m.start()))
    return found


def test_cap_table_documents_its_heredoc_quoting_exception() -> None:
    """cap-table must carry its own guardrail, since the fleet rule excludes it."""
    body = (SKILLS_DIR / "cap-table" / "SKILL.md").read_text(encoding="utf-8")
    assert any(not quoted for _, _, quoted, _off in _heredocs(body)), (
        "cap-table no longer has an unquoted heredoc — if the templates were converted to "
        "single-quoted delimiters, delete this test and the guardrail prose with them."
    )
    flat = " ".join(body.split()).lower()
    assert "heredoc guardrail" in flat, (
        "cap-table/SKILL.md has unquoted heredocs and no heredoc guardrail. The fleet rule lives "
        "in market-sizing/SKILL.md and is stated absolutely ('always single-quote'), which cap-table "
        "cannot follow — both its templates must interpolate. State the exception locally."
    )
    assert "unquoted" in flat and ("escape" in flat or "escaped" in flat), (
        "the guardrail must name BOTH halves: that the delimiter is unquoted on purpose, and that "
        "every literal `$` in a value must therefore be escaped"
    )


@pytest.mark.parametrize("skill", ALL_SKILLS)
def test_unquoted_heredoc_bodies_escape_literal_dollars(skill: str) -> None:
    """In an unquoted heredoc, a literal `$` in a VALUE must be written `\\$`.

    The failure is silent and lands in a producer input: `"Series A at $20M pre"`
    reaches the file as `"Series A at M pre"`, because the shell expands `$20`
    (unset) and leaves `M`. cap-table's `scenario_requests.json` label feeds the
    solver, so this is a money-path defect, not a cosmetic one.

    Legitimate interpolations are exempt by construction: `$VAR`, `${VAR}` and
    `$(cmd)` are what an unquoted delimiter is FOR. What is flagged is `$` followed
    by a digit -- a dollar amount -- which is never a shell construct anyone means.
    """
    body = (SKILLS_DIR / skill / "SKILL.md").read_text(encoding="utf-8")
    offenders: list[str] = []
    for delim, target, quoted, at in _heredocs(body):
        if quoted:
            continue  # a single-quoted delimiter does not interpolate; `$8M` is safe as written
        # From the MATCH position, not `body.index(delim)`: index() finds the delimiter's FIRST
        # occurrence anywhere in the file, so one sentence of prose naming INPUTS_EOF would move
        # the scan window silently.
        start = at
        end = body.find(f"\n{delim}\n", start)
        assert end != -1, f"{skill}: unterminated heredoc {delim} -> {target}"
        for raw in body[start:end].splitlines()[1:]:
            for hit in re.finditer(r"(?<!\\)\$(?=\d)", raw):
                offenders.append(f"{target}: {raw.strip()[:90]} (col {hit.start()})")
    assert not offenders, (
        f"{skill}/SKILL.md: unescaped literal `$<digit>` inside an UNQUOTED heredoc — the shell "
        "eats it before the file is written. Escape as `\\$`, or move the figure into a numeric "
        "field.\n  " + "\n  ".join(offenders)
    )
