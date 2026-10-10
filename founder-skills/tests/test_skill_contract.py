"""Regression tests enforcing the skill frontmatter and env-var contract.

Grounded in the v2.1.120-verified gist: only ``${CLAUDE_PLUGIN_ROOT}``
(braced) is template-substituted by the plugin content expander before
shell substitution. Bare ``$CLAUDE_PLUGIN_ROOT`` resolves only at Bash
execution time and depends on ``CLAUDE_ENV_FILE`` being sourced — which
the gist flags as unconfirmed for skill shell subprocesses.

Frontmatter keys outside the documented set are silently dropped by the
parser, so we keep frontmatter minimal and move human documentation into
the body.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import _critique_corpus
import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILLS_ROOT = REPO_ROOT / "founder-skills" / "skills"

# Documented frontmatter keys per gist 1 (v2.1.120 SKILL.md table).
# `version` is explicitly tagged "[Undocumented] Informational only" in the
# gist — we exclude it from the documented set so future authors don't
# treat it as a contract.
ALLOWED_FRONTMATTER_KEYS: frozenset[str] = frozenset(
    {
        "name",
        "description",
        "when_to_use",
        "allowed-tools",
        "argument-hint",
        "arguments",
        "context",
        "agent",
        "model",
        "effort",
        "user-invocable",
        "disable-model-invocation",
        "paths",
        "hooks",
        "shell",
        "created_by",
    }
)


def _skill_md_files() -> list[Path]:
    return sorted(SKILLS_ROOT.glob("*/SKILL.md"))


def _model_listed_skill_md_files() -> list[Path]:
    """The skills the model is shown in its skill listing.

    A skill whose frontmatter sets `disable-model-invocation: true` is filtered out of that listing
    before the character budget is applied, and the Skill tool refuses it unless the user typed it
    (read from the Claude Code 2.1.289 binary). It still appears in the `/` menu. `feedback` is the
    one such skill: a founder starts it, the model never does.
    """
    out = []
    for p in _skill_md_files():
        fm, _ = _split_frontmatter(p.read_text())
        if fm.get("disable-model-invocation") is not True:
            out.append(p)
    return out


def _split_frontmatter(text: str) -> tuple[dict, str]:
    """Return (frontmatter_dict, body_text). Raises on missing frontmatter."""
    match = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.DOTALL)
    if not match:
        raise AssertionError("SKILL.md is missing YAML frontmatter")
    return yaml.safe_load(match.group(1)) or {}, match.group(2)


@pytest.mark.parametrize("skill_md", _skill_md_files(), ids=lambda p: p.parent.name)
def test_no_bare_plugin_root_in_body(skill_md: Path) -> None:
    """Bare $CLAUDE_PLUGIN_ROOT (no braces) is fragile — must use ${...}."""
    text = skill_md.read_text()
    _, body = _split_frontmatter(text)
    # Match $CLAUDE_PLUGIN_ROOT NOT preceded by '{' (i.e. bare form).
    bare = re.findall(r"(?<!\{)\$CLAUDE_PLUGIN_ROOT\b", body)
    assert not bare, (
        f"{skill_md.relative_to(REPO_ROOT)} has {len(bare)} bare "
        "$CLAUDE_PLUGIN_ROOT references. Use ${CLAUDE_PLUGIN_ROOT} so the "
        "plugin content expander substitutes it at load time, instead of "
        "depending on CLAUDE_ENV_FILE being sourced into the Bash subprocess."
    )


PLUGIN_ROOT_DIR = REPO_ROOT / "founder-skills"

# The three forms a loader may expand in place: an inline shell command (!`cmd`), a fenced
# block opened with ```! and the argument placeholder. The "!" of a spreadsheet error such as
# `#REF!` or `#DIV/0!` is followed by a CLOSING backtick, never an opening one, so the inline
# pattern requires the "!" not to end a word: `#REF!` stays legal.
_LOADER_EXPANSION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("inline shell command !`cmd`", re.compile(r"(?<![\w/])!`")),
    ("fenced ```! block", re.compile(r"^\s*```!", re.MULTILINE)),
    ("$ARGUMENTS placeholder", re.compile(r"\$\{?ARGUMENTS\b")),
)


def _loader_expanded_files() -> list[Path]:
    return sorted(
        [*SKILLS_ROOT.glob("*/SKILL.md"), *PLUGIN_ROOT_DIR.glob("commands/*.md"), *PLUGIN_ROOT_DIR.glob("agents/*.md")]
    )


def _loader_expansion_hits(text: str) -> list[str]:
    hits = []
    for label, pattern in _LOADER_EXPANSION_PATTERNS:
        for m in pattern.finditer(text):
            hits.append(f"line {text.count(chr(10), 0, m.start()) + 1}: {label}")
    return hits


def test_no_inline_shell_expansion_or_argument_placeholder_in_skill_files() -> None:
    """No skill, command or agent file may carry !`cmd`, a ```! fence, or $ARGUMENTS.

    On cloud Cowork a typed slash command whose allowed shell command fails hangs silently. And
    when a skill is the first message of a conversation, its text is expanded outside Claude Code,
    so both the inline command and the argument placeholder reach the model raw. Heavy work
    belongs in a script the model runs through the Bash tool.
    """
    files = _loader_expanded_files()
    assert len(files) >= 7 + 6, f"expected the seven skills and the agents; found {len(files)}"
    offenders = [f"{p.relative_to(REPO_ROOT)} {hit}" for p in files for hit in _loader_expansion_hits(p.read_text())]
    assert not offenders, "loader-expanded forms found:\n" + "\n".join(offenders)


def test_the_loader_expansion_matcher_sees_each_form_and_spares_spreadsheet_errors() -> None:
    """Seeded control: each form is caught, and spreadsheet error strings are not."""
    assert _loader_expansion_hits("Run !`git status` first.")
    assert _loader_expansion_hits("!`date`")
    assert _loader_expansion_hits("intro\n```!\nls\n```\n")
    assert _loader_expansion_hits("  ```!\nls\n```")
    assert _loader_expansion_hits("Topic: $ARGUMENTS")
    assert _loader_expansion_hits("Topic: ${ARGUMENTS}")
    assert not _loader_expansion_hits("broken cells (`#REF!`,\n`#DIV/0!`, and the rest)")
    assert not _loader_expansion_hits("Stop! `x` is fine, and so is ```bash\nls\n```")
    fmr_agent = (PLUGIN_ROOT_DIR / "agents" / "financial-model-review.md").read_text()
    assert "`#REF!`" in fmr_agent, "the spreadsheet-error control text moved; re-point this control"
    assert not _loader_expansion_hits(fmr_agent)


@pytest.mark.parametrize("skill_md", _skill_md_files(), ids=lambda p: p.parent.name)
def test_frontmatter_only_documented_keys(skill_md: Path) -> None:
    """Custom keys are silently dropped by the parser — keep them out."""
    text = skill_md.read_text()
    fm, _ = _split_frontmatter(text)
    unknown = set(fm.keys()) - ALLOWED_FRONTMATTER_KEYS
    assert not unknown, (
        f"{skill_md.relative_to(REPO_ROOT)} has frontmatter keys "
        f"{sorted(unknown)} that are not in the documented set "
        "(silently dropped by the parser per gist). Move them to a "
        "documentation section in the body."
    )


@pytest.mark.parametrize("skill_md", _model_listed_skill_md_files(), ids=lambda p: p.parent.name)
def test_frontmatter_has_when_to_use(skill_md: Path) -> None:
    """Regression lock: every skill must declare when_to_use.

    All 5 skills already have when_to_use on main (added in v0.4.1). This
    test prevents future authors from accidentally dropping the field in
    a refactor. when_to_use is half the model's pitch in the skill listing
    (combined with description, capped at 1,536 chars per gist 1).

    Note: Desktop's regex-based skill scanner ignores when_to_use entirely
    (per gist 2 §"Skill discovery logic" — only `name`, `description`,
    `argument-hint`, `user-invocable` are read). So when_to_use matters
    for CLI-runtime model invocation, not for Settings UI display. Trigger
    phrasing should also live in description for Desktop discoverability.
    """
    text = skill_md.read_text()
    fm, _ = _split_frontmatter(text)
    assert fm.get("when_to_use"), (
        f"{skill_md.relative_to(REPO_ROOT)} is missing 'when_to_use'. "
        "This was added in v0.4.1 — re-add it before merging."
    )


@pytest.mark.parametrize("skill_md", _skill_md_files(), ids=lambda p: p.parent.name)
def test_frontmatter_listing_budget(skill_md: Path) -> None:
    """description + when_to_use is capped at 1,536 chars per skill."""
    text = skill_md.read_text()
    fm, _ = _split_frontmatter(text)
    desc = fm.get("description", "") or ""
    wtu = fm.get("when_to_use", "") or ""
    total = len(desc) + len(wtu)
    assert total <= 1536, (
        f"{skill_md.relative_to(REPO_ROOT)}: description+when_to_use is "
        f"{total} chars, exceeds the 1,536-char per-skill listing cap."
    )


def test_total_listing_budget_under_the_cap() -> None:
    """Sum of all skills' description+when_to_use must stay under a 6,000-char cap.

    Two separate limits apply:
      - per-skill: 1,536 chars (the default per-entry cap, enforced above)
      - total: a listing budget every installed skill shares, sized as
        context window x chars per token (~3; 4 on Haiku 4.5) x 1% -- about
        6,000 chars at a 200K window, about 30,000 at 1M, 8,000 on Haiku 4.5.
        On overflow, skills drop to name-only one at a time, least recently
        used first. (Reported by skill-creator-plus, checked against CLI
        2.1.280; not measured here.)

    6,000 is the smallest of those budgets for a current model, and our
    skills share it with every other installed skill, so we hold our own
    total to it. A skill that loses the overflow keeps only its name, and the
    one most likely to lose is the one the founder has not used lately.

    If the total ever creeps near 6,000, trim description/when_to_use; do
    not raise the cap.

    Only model-listed skills count: a `disable-model-invocation` skill is not in the listing.
    """
    soft_cap = 6000
    total = 0
    breakdown: list[str] = []
    listed = _model_listed_skill_md_files()
    assert len(listed) >= 6 and "feedback" not in {p.parent.name for p in listed}, [p.parent.name for p in listed]
    for skill_md in listed:
        fm, _ = _split_frontmatter(skill_md.read_text())
        desc = fm.get("description", "") or ""
        wtu = fm.get("when_to_use", "") or ""
        n = len(desc) + len(wtu)
        total += n
        breakdown.append(f"  {skill_md.parent.name}: {n}")
    assert total <= soft_cap, (
        f"Total listing budget across {len(listed)} skills is "
        f"{total} chars, exceeds {soft_cap}-char soft cap "
        f"(the listing budget at a 200K window). Trim description/when_to_use:\n" + "\n".join(breakdown)
    )


_INTERNAL_VERSION_REF = re.compile(r"\bv0\.\d+\.\d+")


def test_the_internal_version_matcher_and_its_exemptions_work() -> None:
    """The positive case for the scan below, which cannot otherwise fail.

    Measured: blinding `_INTERNAL_VERSION_REF` to a regex that matches nothing leaves the whole file's
    158 tests green. The corpus is clean — the goal state — so its silence says nothing about the
    matcher, and a rotted pattern would read exactly like a compliant fleet.

    The exemptions get specimens too, and they are the half that matters here. Both are contractual
    identifiers that LOOK like the thing being banned: a `schema_version` pins an artifact contract,
    and the rule-pack version is data a lawyer's citation depends on. An over-broad matcher that
    swept them would push an author to delete a real contract to get green.
    """
    must_flag = [
        "This skill is v0.5.0 and expects the v0.4.2 rule pack.",
        "Added in v0.10.0.",
    ]
    must_not_flag_by_pattern = [
        "Version 1.2.3 of the NVCA model form.",  # not the v0.x plugin shape
        "See §4.4.4 of the certificate.",  # a legal citation, not a version
    ]
    exempted_by_line_rule = [
        'The artifact carries "schema_version": "v0.5.0-cap-state".',
        "The rule pack is cap-table-rules.json v0.4.9.",
    ]
    for s in must_flag:
        assert _INTERNAL_VERSION_REF.search(s), f"an internal version ref is no longer caught: {s!r}"
    for s in must_not_flag_by_pattern:
        assert not _INTERNAL_VERSION_REF.search(s), f"the matcher is too broad: {s!r}"
    for s in exempted_by_line_rule:
        assert "schema_version" in s or "cap-table-rules" in s, (
            f"specimen no longer exercises an exemption — the scan's skip rule and this list have drifted apart: {s!r}"
        )


_SCHEMA_VERSION_LITERAL = re.compile(r"\bv\d+\.\d+\.\d+-[a-z][a-z0-9-]*\b")


def test_no_internal_version_refs_in_user_facing_files() -> None:
    """Internal plugin version numbers belong in CHANGELOG / commits /
    docs/internal — never in SKILL.md, skill references, or agent bodies
    (they go stale immediately and leak release internals to users).
    Exempt: lines mentioning schema_version (contractual artifact
    identifiers) and cap-table-rules.json refs (rule-pack DATA-file version
    pin, not a plugin release ref — confirmed contractual semantics)."""
    repo = Path(__file__).resolve().parents[2] / "founder-skills"
    files = (
        list(repo.glob("skills/*/SKILL.md"))
        # `**` and the plugin-root tree, both deliberately. The flat `references/*.md` missed
        # cap-table's `references/lanes/` and `references/schemas/`; the plugin-root tree was missed
        # entirely, and cowork-harness 3.7.0 made it evaluator-visible corpus for five of six skills.
        + list(repo.glob("skills/*/references/**/*.md"))
        + list(repo.glob("references/**/*.md"))
        + list(repo.glob("agents/*.md"))
    )
    assert files, "glob found no user-facing files — path layout changed?"
    offenders = []
    for path in files:
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if "schema_version" in line or "cap-table-rules" in line:
                continue
            # A `vX.Y.Z-<skill>` literal IS a schema_version value — the contractual artifact
            # identifier this test's docstring already exempts. The word-based exemption above
            # only sees it when the line says "schema_version" too, which a TABLE ROW under a
            # `| Skill | schema_version | … |` header does not. Surfaced when the scan widened to
            # the plugin-root references, where that table lives.
            if _SCHEMA_VERSION_LITERAL.search(line):
                continue
            if _INTERNAL_VERSION_REF.search(line):
                offenders.append(f"{path.relative_to(repo)}:{i}: {line.strip()}")
    assert not offenders, "internal version refs in user-facing files:\n" + "\n".join(offenders)


# Matches `uv run mypy founder-skills/skills/<skill>/scripts/` invocations in
# either CLAUDE.md's Type Checking section or ci.yml's typecheck job.
_MYPY_SKILL_DIR = re.compile(r"uv run mypy (founder-skills/skills/[\w-]+/scripts/)")


def _mypy_skill_dirs(text: str) -> set[str]:
    return set(_MYPY_SKILL_DIR.findall(text))


def test_ci_mypy_matrix_matches_claude_md() -> None:
    """Every skill scripts dir mypy-checked per CLAUDE.md's Type Checking
    section must also be type-checked in ci.yml's typecheck job. Guards against
    a new skill being added to the docs but silently omitted from CI (the
    v0.4.3 bug class, where competitive-positioning was missing from the
    matrix, and the later recurrence with cap-table)."""
    claude_md = (REPO_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    ci_yml = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    documented = _mypy_skill_dirs(claude_md)
    in_ci = _mypy_skill_dirs(ci_yml)
    assert documented, "no `uv run mypy founder-skills/skills/.../scripts/` lines found in CLAUDE.md"

    missing = sorted(documented - in_ci)
    assert not missing, (
        "CLAUDE.md's Type Checking section lists skill scripts dirs that ci.yml's "
        "typecheck job does not run mypy on (untypechecked in CI):\n" + "\n".join(missing)
    )


# Runnable ```bash/sh/shell snippets are executed via the Cowork/hostloop workspace shell tool
# (mcp__workspace__bash), which runs /bin/sh (dash) — NOT bash. Bashisms raise
# "sh: <n>: Syntax error" and abort the snippet mid-way (leaving partial side effects).
_SHELL_FENCE_OPEN = re.compile(r"^```(bash|sh|shell)\s*$", re.IGNORECASE)
_FENCE_CLOSE = re.compile(r"^```\s*$")
_BASHISMS = [
    (re.compile(r"\b\w+\+?=\("), "bash array assignment (X=(...) / X+=(...))"),
    (re.compile(r"\$\{\w+\[[@*]\]\}"), "bash array expansion (${X[@]} / ${X[*]})"),
    (re.compile(r"\$\{\w+\[[0-9]"), "bash array index (${X[0]})"),
    (re.compile(r"\[\[ "), "bash [[ ]] test (use POSIX [ ])"),
    (re.compile(r"<\("), "process substitution <(...)"),
    (re.compile(r"\bdeclare\s+-[aA]\b"), "declare -a/-A"),
    (re.compile(r"\b(?:mapfile|readarray)\b"), "mapfile/readarray"),
    (re.compile(r"\bset\s+-o\s+pipefail\b"), "set -o pipefail (dash lacks it)"),
]


# One specimen per pattern above, so each arm is exercised against known input. A detector that only
# scans live files and asserts "no offenders" is vacuous once the files are clean -- which is the goal
# state -- and this one is proven so: blinding all eight patterns left it green. That matters more
# here than for a cosmetic guard, because a bashism reaching a runnable snippet fails at RUNTIME in
# Cowork, where the workspace shell is dash rather than bash.
_BASHISM_SPECIMENS = [
    "FILES=(a b c)",
    'echo "${FILES[@]}"',
    'echo "${FILES[0]}"',
    "if [[ -f x ]]; then :; fi",
    "diff <(sort a) <(sort b)",
    "declare -a items",
    "mapfile -t lines < f",
    "set -o pipefail",
]
# POSIX equivalents of the same intent: the patterns must not fire on the correct form, or the guard
# teaches authors to avoid shell rather than to write portable shell.
_POSIX_SPECIMENS = [
    "set -- a b c",
    'for f in "$@"; do echo "$f"; done',
    "if [ -f x ]; then :; fi",
    "sort a > /tmp/a && sort b > /tmp/b && diff /tmp/a /tmp/b",
    "set -eu",
]


def test_the_bashism_patterns_catch_bashisms_and_spare_posix() -> None:
    """The positive case for the scan below, which cannot otherwise fail.

    Each pattern is matched against a snippet that must trip it, and every POSIX form is matched
    against all patterns to confirm none fires. Without this, a rotted pattern is indistinguishable
    from a clean corpus.
    """
    assert len(_BASHISM_SPECIMENS) == len(_BASHISMS), (
        "every bashism pattern needs a specimen — a pattern added without one is unexercised"
    )
    for (pat, name), specimen in zip(_BASHISMS, _BASHISM_SPECIMENS, strict=True):
        assert pat.search(specimen), f"pattern for {name!r} no longer matches its own example: {specimen!r}"
    for ok in _POSIX_SPECIMENS:
        for pat, name in _BASHISMS:
            assert not pat.search(ok), f"{name!r} fires on POSIX-correct shell: {ok!r}"


def _shell_block_lines(text: str) -> Iterator[tuple[int, str]]:
    in_block = False
    for i, line in enumerate(text.splitlines(), 1):
        if in_block:
            if _FENCE_CLOSE.match(line):
                in_block = False
            else:
                yield i, line
        elif _SHELL_FENCE_OPEN.match(line):
            in_block = True


def test_runnable_shell_snippets_are_posix_sh() -> None:
    """Runnable snippets in ```bash/sh/shell blocks run via mcp__workspace__bash -> /bin/sh (dash),
    not bash. Keep them POSIX-sh safe: no arrays, [[ ]], <(...), declare -a, mapfile, pipefail."""
    repo = Path(__file__).resolve().parents[2] / "founder-skills"
    files = (
        list(repo.glob("skills/*/SKILL.md"))
        + list(repo.glob("skills/*/references/**/*.md"))
        # The plugin-root tree carries runnable snippets too (skill-execution-model.md), and every
        # skill points at it — so a bash-ism there reaches every lane, not one.
        + list(repo.glob("references/**/*.md"))
        + list(repo.glob("agents/*.md"))
    )
    assert files, "glob found no user-facing files — path layout changed?"
    offenders = []
    for path in files:
        for lineno, line in _shell_block_lines(path.read_text(encoding="utf-8")):
            code = line.split("#", 1)[0]  # drop trailing comment / skip comment-only lines
            if not code.strip():
                continue
            for pat, name in _BASHISMS:
                if pat.search(code):
                    offenders.append(f"{path.relative_to(repo)}:{lineno}: {name} -> {line.strip()}")
    assert not offenders, "POSIX-unsafe shell in runnable snippets (workspace shell is dash):\n" + "\n".join(offenders)


# ---------------------------------------------------------------------------
# Size guards (E2)
#
# HISTORY, because the reason changed and the tests did not: these ratchets were
# added when `cowork-harness critique` capped its evaluator evidence at 64 KiB per
# SKILL.md and 8 KiB TOTAL across all references/ files, silently. Over-budget
# content was cut, which cost LOST findings — the evaluator is told "absence from a
# truncated package is NOT evidence" and routes claims to `not-adjudicable`.
#
# The harness has since fixed that: skill-authored content (SKILL.md, every
# references/** file, and every agent the skill pins) now ships WHOLE to the
# evaluator, bounded
# only by a 512 KiB sanity ceiling across ALL FOUR classes COMBINED — and a breach is cut
# loudly and by name in `evidenceBudget.corpusCuts`, never silently. Read the live number off
# `_corpus_bytes` below; quote no figure from a comment, this one included — every one that has
# been written here went stale, twice while a test stayed green.
# The caps below are historical context only.
#
# One consequence worth stating because it reverses old guidance: relocating prose
# from SKILL.md into references/ is now NEUTRAL for grading. It used to make things
# worse (64 KiB per-file vs 8 KiB shared). Any note still saying otherwise is stale.
#
# THE RATCHETS STAY, for reasons that never depended on the harness:
#   - Desktop's regex discovery scanner and the per-skill description/when_to_use
#     budget are ours to manage regardless;
#   - context is not free — a 122 KB SKILL.md is re-read on every dispatch;
#   - unbounded growth is how a skill becomes unmaintainable, and a ratchet that
#     only ever moves down is the cheapest guard against it.
#
# So: ratchet DOWN whenever a file shrinks, never up to make a commit pass. What
# changed is the CONSEQUENCE of crossing a cap, not the value of holding the line.
LEGACY_SKILL_MD_CAP = 64 * 1024  # historical; not enforced by the harness any more
LEGACY_REFERENCES_CAP = 8 * 1024  # historical; references now ship whole

# Current sizes. Ratchet DOWN only.
# fmr + competitive-positioning were raised ~160 B each to add colloquial
# trigger phrasings to `description`. Desktop's regex scanner reads
# `description` only, so the bytes have to go there. Correcting an earlier note
# here: that change was NOT "A/B verified" — the sample was one run per skill,
# and re-running fmr three times on one prompt gives 1/3. Discovery is
# probabilistic; the change is still right, the certainty was not.
#
# All six raised ~475 B to extend the narration rule to task-tracker LABELS.
# The prose channel was already clean; the label channel was never addressed.
#
# VERIFIED LIVE (cowork-harness, hostloop, $8.10 for the treatment arm).
# Control = 24 historical pre-fix cap-table runs; treatment = 3 post-fix runs
# of the same scenario:
#     syntactic leaks   6 hits / 3 runs  ->  0 hits / 3 runs
#     semantic leaks    104/288 (36.1%)  ->  2/36 (5.6%)
# and the rule GENERALIZED rather than being copied: zero of the 36 post-fix
# labels reused the three examples the rule gives, and cap-table produced
# cap-table-specific wording ("Extract SAFE terms from your document" where it
# previously said "Extract SAFE terms via sub-agent (Lane 1)").
# The 4th bad example ("Initialize founder context") targets the only measured
# residual and is itself unverified.
# competitive-positioning raised again for the reserved no-change prefix: across four live runs the
# accept branch moved between slots while every option kept opening "Looks good", so neither position
# nor a shared prefix identifies it. One reserved prefix, on exactly one option per gate, does. The
# same pass removed a one-option gate the schema cannot render (its minimum is two) by stating the
# finding in the Step-A message instead of asking an unanswerable question — the pattern Gate 1
# already uses when additions exceed the cap.
# competitive-positioning raised again, net, to cut an UNSATISFIABLE option spec: the axis gate
# specified five options where AskUserQuestion renders at most four, so the model had to drop one on
# every run and the spec forfeited an unpredictable choice rather than adding one. The dropped
# `Other changes` was redundant regardless — the tool always offers free-text Other itself. The
# replacement prose costs more bytes than the deleted option saved, and is worth it: the constraint is
# invisible from the option list alone, which is how a five-option spec survived to production.
# competitive-positioning raised for the blind recall check (Step 3.6) and dated developments: the
# adversarial check previously tested only PRECISION (are the listed competitors real?) and never
# RECALL (who is missing?) — recall lived in Step 4's Phase B, run by the agent that had just
# enriched the draft and firing AFTER Gate 1, so it was anchored by construction and arrived after
# the founder had already validated the set. Step 3.6 adds an unanchored parallel dispatch whose
# blind is enforced structurally (a redacted product summary staged into the hand-off dir, never
# ANALYSIS_DIR) rather than by asking the agent not to look, plus Gate 1 presentation with the
# MAX_COMPETITORS slot arithmetic and the draft_only "not a verdict" rule. Step 4 also now collects
# dated, URL-sourced recent_developments.
# competitive-positioning raised again: the Step 4 promotion instruction now spells out the
# enrichment-then-merge sequence end to end instead of an instruction that violated the producer's
# own required-field check; the Step 5 merge-back also copies scoring_basis into positioning.json
# so the founder-override re-pipe through score_positioning.py doesn't silently drop it; Gate 1's
# no-challenges fallback line and Gate 3's triggers/file-pointer/option-label references were
# corrected; and the free-a-slot option is now conditional on a consolidation candidate existing.
# cap-table +142 B: the sentence carrying the founder's stage into
# `inputs.metadata.stage`. It is what makes the stage-aware branch of
# `founder_benchmarks.israel_preseed_context` REACHABLE — without it nothing
# writes the field, `_declared_stage` returns None, and the benchmark fires for
# nobody, trading a wrong note for a missing one. Trimmed first, not instead:
# 115 B came back out of the same change (prose tightened, and the JSON template
# example dropped because a copied `"stage": "seed"` would mislabel every
# company — the exact defect this fix removes). The remaining 142 B has no
# offset available: the file has zero filler phrases, and its only near-duplicate
# blocks are the per-call `SHARED_SCRIPTS` re-derivations, which the fresh-shell
# contract requires (SKILL.md:980 says so in its own comment).
# deck-review raised 392 B for `:377` `stage_choice`: the spec mandated "exactly these five" options
# where AskUserQuestion renders at most four, so the model silently forfeited one every time the gate
# fired. The fix offers four — the `--rebuild-stage` enum minus the stage the profile currently holds
# — which is sound only because reaching the gate means the founder just rejected that stage. Three
# things had to be stated, not inferred: the drop rule, why it is safe, and that on a repeat pass the
# dropped stage is the CURRENT one, not the first detected (drop the wrong one and the founder is
# re-offered what they rejected while the option they now want is missing). Trimmed first, not
# instead: 193 B came back out before this number was set. The remainder is the rule itself.
# cap-table raised 6_477 B for the gate-contract Phase 2 sweep: the Gate Catalog was missing rows for
# the founder-context basics (name/sector/geography — only stage existed), engagement mode (`:488` had
# no catalog counterpart at all), two real closed enums buried in the extraction confirm-gate
# (interest_rate_type, interest_converts_to_shares), and the §102 per-grant tax-route gate — each a
# genuinely new spec, not a reword. Trimmed first, not instead: the Sector/Geography rows point at
# Company name's explanation instead of repeating it, the Company-stage known-gap note and the
# Founder-only-fact-gates shape row were both tightened, and the Step-2 site now points at the catalog
# instead of restating three option lists inline — recovering ~800 B before this number was set. Also
# fixed the same drift class deck-review's fix names: `:489`/`:490` disagreed with the catalog's
# Jurisdiction/IIA rows on both labels AND order; they now point at the catalog instead.
# financial-model-review raised for the same sweep: two prose gates (review-page STOP, Path B
# confirmation) declared as `Options:`; the founder-context batch's stage question got the real 4-label
# set (`Pre-seed`/`Seed`/`Series A`/`Series B+`) instead of a stale 5-value `--stage` list that omitted
# series-c/series-d entirely; cash/date/burn and the Exit-2 company picker marked explicitly
# runtime-labelled so they read as a shape, not silence.
# market-sizing raised for the same sweep: the methodology-change follow-up got a real declared
# 3-option list instead of parenthetical prose; the founder-context gate's stage question got the
# real 4-label set; the data-correction follow-up marked explicitly runtime-labelled (data-dependent,
# not enumerable).
# ic-sim raised for the same sweep: the founder-context gate's stage question got the real 4-label set
# (mentions count unchanged — the edit reused the site's existing `AskUserQuestion` sentence rather than
# adding a new one).
# competitive-positioning raised for the same sweep: the founder-context gate's stage question got the
# real 4-label set; the sparse-materials gate and the "which additions by name" follow-up marked
# explicitly runtime-labelled. The scoring-basis follow-up at `:679` was tried as a declared 3-option
# list and REVERTED — it has no legitimate no-change branch (the founder just chose to change the
# basis), so declaring it collided with this skill's exactly-one reserved-prefix rule. Left as prose,
# parked for the confirm-gate marker rather than forcing a fabricated no-change option onto it.
# deck-review raised again for the same sweep: the founder-context gate's stage question got the real
# 4-label set and an explicit note distinguishing it from the unrelated `--rebuild-stage` enum
# `:377`'s own gate uses — the two look similar (both "stage") and do not share a value set.
# One more pass across all five non-cap-table skills: each stage-label edit above was initially written
# as inline prose (`**Stage is...:** \`Pre-seed\` / ...`) and did NOT parse as a declared spec — no
# `Options:` line, so `_labelled_line_specs` never saw it. Verified by running the parser BEFORE
# claiming "declared" in any report. Restructured all five into a real `Options:` line (a few extra
# bytes, one line break) so the gate is actually machine-checkable, not merely worded like it is.
# 2026-08 remediation — all six raised. One fleet-wide edit plus per-skill ones, each a fix for a
# defect that could reach a founder or silently corrupt a run:
#
# FLEET-WIDE — the plugin root is now resolved ONCE and reused. Measured, a single session mounted
# two DIFFERENT versions of this plugin at the same time (different SKILL.md, different producer
# scripts), plus host-side cache copies, one symlinking into another session's tree. Every skill's
# Step 0 self-healed with `find ... | head -1`, and each re-ran that find in two-to-three LATER
# blocks in separate shells — so one run could silently mix producer scripts across plugin versions
# with no error anywhere. Those later blocks are deleted (which SHRINKS the files) and replaced by
# the printed value; Step 0 now pipes candidates into select_plugin_root.py, which is deterministic
# and names every rejected mount on stderr. The net growth is the explanation of WHY, which is the
# part a model needs in order not to "helpfully" re-resolve the root later.
#
# competitive-positioning also carries: the axis-rationale nesting fix (its template instructed a
# shape the producer does not read, so every compliant run shipped blank rationales while the
# checklist graded POS_05 pass on text no founder could see); the 18-month recency bound, previously
# documented nowhere the sub-agent reads and fatal to the whole payload; --positioning-scores on the
# canonical checklist pipe (without it the staleness detector can never fire); NARR_03 guidance for
# a deck naming no competitor; deferred recall candidates; cohort constituents; and a per-view
# Gate-3 trade-off trigger. It also LOST the invented "Differentiation strength" band scale, which
# described a field existing in no script or artifact.
# deck-review +645 B and market-sizing +137 B for the geography guard. A live run derived company,
# stage and sector from the deck, found NO geography signal anywhere in it, and recorded "US"
# rather than asking — inferred from `$` and from two founders' ex-employers. Geography is saved for
# later reviews and a financial model review grades against it (no deck-review script reads it; a deck
# review is not graded by it, as this comment once claimed). deck-review already said to
# ask when the deck yields no signal; what was missing is that deriving THREE of the four does not
# license skipping the ask for the fourth. market-sizing's carve-out went further and named
# currency as a geography signal outright, which is unsound: `$` is also CAD, AUD and SGD.
# All six raised ~800 B for the deliverable hand-over rule. The delivery step told the model to SEND
# the files and stopped there, so how they were introduced was left to chance: measured across two
# otherwise-identical deck-review runs, one wrote "[the written report](computer://…)" per document and
# the other wrote "the files are above". Both called present_files, so the founder got the same cards —
# but in the second, unlabelled. Which is also why the delivery assertion is a coin-flip rather than a
# check of anything: it asserts a link the skill never asked for. The rule names each deliverable by
# what it IS and links it, and states that this does not license naming internal files (the founder
# reads the label, never the path) so it cannot be read as loosening the founder-text rules.
# cap-table 145,518 -> 145,844 (+326 B) on 2026-08-26, for TWO fixes in the promote block.
# cap-table 145,844 -> 146,053 (+209 B) on 2026-08-30: the scenario-selection gate now says a
# convertible note rules out `safe_conversion`, so the agent does not offer a route that refuses.
# 1. `SLUG_TITLE` was BROKEN for every multi-word company. It ran `sed 's/-/_/g'` and then capitalised
#    per awk FIELD — but after the join `acmecorp_inc` is ONE field, so only the leading letter was
#    raised: `Acmecorp_inc`. Correct for a one-word slug (`cadence` -> `Cadence`) and wrong for all
#    others. Every fixture company but one is single-word, which is why the corpus never caught it.
#    Now splits on `-` into words, capitalises each, joins with `_`: acmecorp-inc -> Acmecorp_Inc.
# 2. Three of four promote routes were `#` comments; they are now written as `cp` lines FOR LEGIBILITY
#    ONLY. This does NOT make them execute, and an earlier version of this note claimed it did: a
#    fenced ```bash block in a skill body is inert text the model may run, ignore or paraphrase, and
#    the two forms that DO execute are force-disabled under Cowork. Measured across four runs of one
#    extraction-only scenario, the suffix still drifted (_Instrument_Terms vs _Term_Sheet_Review)
#    AFTER the change, while the SLUG_TITLE half held — the model reproduces a derivation it has no
#    view on and substitutes its own judgement where it has one.
# The two shipped together because making a WRONG snippet more prominent is worse than leaving it
# commented: had the model followed it, `Acmecorp_inc_...` would have reached a founder.
# The durable fix is a PRODUCER writing the promoted file, so there is no name to retype — filed
# rather than done here, because "do four routes need four names" is a design question.
#    See docs/internal/2026-08-26-cap-table-deliverable-naming.md.
SKILL_MD_CEILING: dict[str, int] = {
    # All six lowered 2026-10-08 by 4 B: Step 1's exit-10 label reads "(which company)", since the company
    # question is now also asked with one stored context when the request names another company.
    # All six lowered 2026-10-08, each to its new size: Step 0's start paragraph gains the one sentence routing
    # exit 12 (a request that said not to ask) to a stop, paid for by trimming that paragraph and a Step 1 aside;
    # deck review also names who declined.
    # market-sizing raised to pin subagent_type on both fenced Task( calls: the prose above them already
    # instructed it, and the pseudocode four lines below omitted it on both — a type-less dispatch resolves
    # to the wildcard general-purpose agent (bash-capable, scoped persona and rubric discarded), and the
    # example is the form the model copies. Carries cap-table's inline REQUIRED comment, which travels with
    # the example rather than sitting in prose the copier skips.
    # All six raised for the v0.6.0 founder-facing-correctness pass. Two fleet-wide edits plus
    # per-skill ones; each is a fix for a defect that could reach a founder, not prose.
    #
    # FLEET-WIDE 1 — the "Nesting matters here" caveat was WRONG IN ALL SIX. It asserted the headline
    # fields live under `coaching_payload.summary`; measured against each `_emit_coaching_payload`,
    # `high_severity_warnings` is TOP LEVEL in every skill, and cap-table (3 of 3), fmr (3 of 4) and
    # ic-sim (3 of 4) had most of their named fields top-level. Following it returned null. It is now
    # stated per skill against the real shape, and the `checklist.json`/`score_pct` fallback clause is
    # dropped where those do not exist (cap-table, ic-sim).
    # FLEET-WIDE 2 — the delivery target is now anchored to `dirname "$ARTIFACTS_ROOT"` in the four
    # skills that said a bare "workspace root" (ic-sim already had the rule; fmr has no root copy).
    # cap-table and competitive-positioning additionally `cp`'d to bare relative / `./` targets, which
    # resolve to the shell cwd rather than the promoted outputs mount.
    #
    # market-sizing: + the BOTTOM_UP dispatch's missing CURRENCY block. TOP_DOWN had one and BOTTOM_UP
    # did not, so a sub-agent could convert an ILS arpu to USD and the TAM would still be LABELLED ILS
    # — nothing in the pipeline performs FX, so nothing catches it.
    # market-sizing +2,021 B for producer-side FX. The dispatch prompts used to instruct a
    # network-less sub-agent to convert currencies with no rate supplied — i.e. from memory,
    # unsourced and undated — while the agent body said "Never convert". The prompts now ask for
    # the figure as the source states it plus a currency tag; `market_sizing.py` converts with a
    # rate the MAIN thread looks up (it has web access; the sub-agent does not) and refuses when
    # no rate was supplied. The growth is the re-pipe loop and the founder-facing wording for it:
    # a rejected pipe that the model cannot recover from is worse than the defect it replaced.
    # A second pass added the currency tag to the two dispatch JSON SHAPES (it had been in the
    # surrounding prose only — and the sub-agent copies the shape, so nothing ever emitted the
    # tag, nothing converted, and nothing refused: the feature was unreachable), the
    # not-a-repair-dispatch carve-out on the FX stop, and the both-mode re-pipe warning.
    # market-sizing raised for the same rule on its CHECKLIST template, plus the coaching template's
    # "no item ids or warning codes" rule — a live run shipped three criterion ids and a filename into
    # the founder's report.
    # 88_904 -> 89_865 (PPTX): a .pptx deck is binary and Read refuses it, so market
    # figures inside a PowerPoint upload were invisible. Step now renders to PDF, or falls back
    # to text extraction and says what could not be read.
    # All three raised again (+15/+22/+18 B) to add the coverage key to each skill's MAIN-THREAD
    # RETURN. The fixes routed the new signal to report.md and to the coaching sub-agent and
    # left the chat message the founder reads FIRST still sourcing only the headline fields --
    # the same fourth-surface miss, in all three skills at once.
    # market-sizing raised 90,323 -> 90,525 (+202 B) for the Context B `comparison_blocked` field.
    # A refused cross-check is invisible in every other payload key -- the figure is present and
    # `deck_coverage` still reports it as stated -- so a coach not handed this writes as though the
    # founder's own number had been verified against ours. Deliberate.
    # market-sizing 90,547 -> 92,125 (+1,578 B) for the checklist band change, in three parts.
    # (a) The warnings block is replaced by the two-class version deck-review already carries,
    # with the discriminating test stated ("can re-running fix it?"). It also names the two codes
    # that fit NEITHER class rather than filing them wrongly: IMPLAUSIBLE_PCT_SCALE cannot tell a
    # 0.35-for-35% typo from a legitimate 0.35%, so calling it pipeline-integrity would instruct
    # the model to fix-and-re-run a possibly-correct number; UNVALIDATED_CLAIMS conflates "not
    # investigated" with "searched, nothing found". Both were previously covered by "fix
    # high-severity warnings and re-run", which is wrong advice for a true content finding.
    # (b) `--strict` is documented as blocking high AND medium, so it cannot serve as a
    # pipeline-only gate — otherwise the split above reads as if it enables one.
    # (c) The Context B payload template gains `overall_status` and `all_pass`. A payload key no
    # prompt surface names is a key the sub-agent never reads.
    # A9, all six: +1 line each — `insert_coaching.py --report-json`. Without it report.json keeps
    # the pre-coaching text and a raw uuid insertion marker (measured 5,592 B adrift on a live
    # run). Syncing rather than dropping the key, because ~200 test sites across the fleet read
    # report_markdown out of the composed JSON to inspect report content.
    # market-sizing +649 B: the SENSITIVITY_TEST dispatch now states the `sourced` tier split by the
    # assumption's own `confidence`. The old text made omission the default branch for every `sourced`
    # figure ("or omit the parameter"), and sources almost never state a range -- so the tier meant "never
    # stress-tested", silently, for a figure that may be corroborated but imprecise. Nothing downstream
    # could see the omission either. The rule has to be where the sub-agent reads it.
    # +exit-8 Context A bullet and +Context B "any other exit" catch-all, all six (2026-08-31).
    # ONE shared reason for six near-identical raises, referenced rather than repeated:
    # `check_handoff.py` defines seven typed exits; the Context A gate table documented five and
    # omitted exit 8 -- the branch the code was written for, since Context A is where OUTPUT_PATH is
    # built from $HANDOFF_AGENT and where the doubled-prefix condition occurs. Exit 8 therefore fell
    # to "Any other exit -> STOP", halting a run over a condition the gate's own diagnostic says is
    # recoverable by a prefix correction. Context B separately had no catch-all at all, so an exit 4
    # (reachable there on an IO fault) or an uncaught decode error had no documented branch.
    # Guarded by test_context_a_gate_table_documents_exit_8 in test_handoff_contract_ratchet.py.
    # SHRANK: the unscoped "canonical artifacts are producer-script-only" justification was
    # rescoped to "you never write a canonical artifact" across all 22 sites (W2 audit). The
    # instruction was always correct; the REASON given for it asserted the general claim P0-2
    # established is false — the main thread writes several canonical artifacts by heredoc.
    # market-sizing +247 B (93_719 -> 93_966): the dispatch skeleton described
    # `high_severity_warnings` as bare codes while compose has emitted {code, label, message},
    # so the coach was told to write the code we forbid it from writing; and
    # `market_size_approach` was emitted, asserted by four tests, and named on NO prompt
    # surface -- the coach could not say whether the headline figure was built top-down or
    # bottom-up, which is the distinction this skill exists to police.
    # market-sizing 93,966 -> 94,077 (+111 B): inputs.json gains existing_claims_horizon_months
    # and capture_horizon_months. The deck-claim check compared an 18-month plan-case SOM against a
    # 5-year capture SOM and told the founder they were understating themselves by several hundred percent; two
    # optional fields are what let it say "different period" instead of inventing a delta.
    # market-sizing 94,077 -> 94,292 (+215 B): the Step 8 payload template gains
    # approach_comparison. The key must appear on BOTH prompt surfaces -- the contract test reads
    # the agent body too -- or it is documented nowhere the coach reads, which is the defect it
    # was added to fix.
    # +273 B (94_292 -> 94_565): the Step 4 validation.json heredoc gains one `derived`
    # assumption carrying a two-factor `factors` list. Two factors is enough to set the shape, and
    # the sub-agent demonstrably copies the shape it is shown.
    # +2,959 B (94_565 -> 97_524): Step 6c, the adversarial-review dispatch. It is the only step
    # in this skill that dispatches a DIFFERENT agent, so the step has to say why in the body the
    # model reads -- a pin to the wrong agent silently costs the step its web search, and the
    # findings it is contractually required to source. Well past char 19,900, so it is never
    # re-attached after a compaction and evicts nothing that is.
    # +1,073 B (97_524 -> 98_597): Step 6c probes the founder's PDFs for a text layer before
    # dispatching. The red-team sub-agent has no shell, so this has to run in the main thread and
    # ride the dispatch prompt -- and it has to happen at all because a vision read of an
    # image-only page drops dense content SILENTLY, which turns "nothing found" into a claim
    # about a page nobody saw.
    # +729 B (98_597 -> 99_326): Step 6c is reworded from "optional" to "run it; its success is
    # optional". MEASURED on a paid run: the "optional" draft was skipped outright, and the step's
    # only downstream consumer is a low-severity disclosure -- the same shape deck-review's numeric
    # chain was caught by, where a step whose only consumer is a warning gets skipped in silence.
    # +903 B (99_326 -> 100_229): the three-value skip enum and why compose REFUSES without one of
    # them. The table earns its bytes -- this is the step the model has to decide about, and the
    # decision is now binary rather than a judgement call.
    # +424 B (100_229 -> 100_653): the two SOM-horizon fields were in the inputs TEMPLATE as `null`
    # and described in references/artifact-schemas.md, but no sentence in this file told the main
    # thread what to put in them. MEASURED on both live runs after the horizon check landed: null on
    # every run, so HORIZON_MISMATCH -- the fix for a founder read as understating by 5.6x -- could
    # never fire. A field the schema documents and the skill never mentions is a field the model
    # leaves null.
    # -1,902 B (100_653 -> 98_751): Step 6c's hand-filled Task( template moved into
    # scripts/dispatch_prompt.py. MEASURED on a live run, the main thread filled that template and
    # added a "Key things worth attacking" list from its own hypotheses plus an instruction not to
    # re-read the founder's documents; every red-team finding mapped onto the list. A prompt a script
    # prints can be regenerated and compared byte for byte; a prompt the model writes cannot.
    # +211 B (98_751 -> 98_962): the ocr_uploads.py call in Step 6c. Every PDF on the run that
    # motivated the adversarial step was image-only, so a red-team citation to a page could be checked
    # by nothing; one line buys a text sidecar per scanned page that red_team.py verifies quotes against.
    # +194 B (98_962 -> 99_156): one sentence saying `factors` is two or more multiplicands and a
    # sum is not a chain. MEASURED live: the one factors[] list emitted had ONE element (the value
    # under another name) and an additive decomposition was mis-encoded as a product; the schema
    # doc said "the figures the value multiplies" and the model read it as "any list".
    # +862 B (99_156 -> 100_018): the closing_message.py call after the fleet-shared delivery
    # block (which is byte-identical across six skills and cannot absorb it). MEASURED live: the
    # closing chat message called a SOM "about 2%" of the illustrative $100M (it was more than double) under a
    # rule that forbids chat arithmetic; the message is now printed from report.json and the e2e
    # lane checks every number in it exists there.
    # +203 B (100_018 -> 100_221): Step 6c mirrors the uploads into the hand-off dir and passes
    # agent-namespace paths to the generator, and the red_team.py pipe gets --uploads-dir/--ocr-dir.
    # Caught by adversarial review before a paid run: the first cut rendered VM /sessions paths to
    # a sub-agent (denied on Cowork) and never told the validator where the documents were, so every
    # page citation would have been rejected as "not supplied".
    # -673 B (100_221 -> 99_548): Step 10's hand-over paragraph shrinks to the script call plus one
    # sentence, and Main-Thread Return stops listing headline fields as what the main thread
    # "delivers" -- measured at hostloop, that instruction sat 24 lines below a step saying the
    # printed message is the delivery, and the model delivered the fields. The prohibition
    # sentence ("no ratio, no comparison, no percentage") is gone: it did not land; the e2e
    # containment assertion is the guard.
    # +289 B (99_548 -> 99_837): founder_stated_inputs is facts about the founder's OWN business
    # (arpu); a market figure the deck states is a claim and belongs in existing_claims. MEASURED
    # on a live investor run, in the analyst's own words: the deck's population and capture went
    # in as founder-stated, the value-fidelity rule then forbade the bottom-up build from departing
    # from them, and the "independent" build replayed the deck until a re-dispatch.
    # +229 B (99_837 -> 100_066): Step 6c runs ocr_uploads.py as its own call. MEASURED live (eight
    # documents, 35 pages): the bundled mirror+OCR+dispatch call hit the shell tool's 120 s limit,
    # tesseract kept running orphaned, and the prompt was generated twice before the last two
    # documents' sidecars existed -- the red team was told they had no machine-read copy. The
    # generator now refuses on an OCR receipt that does not cover a scanned PDF; the sentence says
    # why the call stands alone and that a re-run resumes.
    # -48 B (100_066 -> 100_018): `--link computer` and "(--link path in Claude Code.)" leave Step 10.
    # MEASURED in a real cloud-lane session: no link form opens there, so a SKILL.md that pins one
    # form is wrong on the default lane; closing_message.py now decides per lane (`--link auto`).
    # +129 B (fleet, one shared edit): the delivery block's hand-over sentence said the link form in
    # Cowork is `computer://` + the absolute path. MEASURED in-app on the remote lane (2026-09-21/22,
    # the default lane for new sessions and the one the market-sizing bug report came from): no link
    # form opens a file there -- computer:// is plain text and a bare path becomes a broken claude.ai
    # URL; the presented card is the delivery. The sentence now says: a link where this surface
    # renders one that opens (on a /sessions tree, computer:// + the path), otherwise the label with
    # the path stated beside it. Same edit in all six; test_delivery_block_is_identical_fleet_wide
    # is the proof.
    # +80 B (100_147 -> 100_227): the founder_stated_inputs rule no longer says "update this field"
    # when the founder agrees; it says a discrepancy is a question for the founder, never an edit,
    # and names founder_stated_inputs_period. MEASURED live: the constructor followed the old
    # sentence literally -- rewrote a founder-stated monthly figure to the model's annual one with
    # no founder in the loop -- after the check called the correct x12 an override.
    # +1,275 B (fleet, one shared edit): the Step 0 preflight and its stop. MEASURED 2026-09-22 on
    # claude.ai, which mounts skills FLAT at /mnt/skills/plugins/<plugin>:<skill>/ and serves no
    # plugin: the shared scripts were unreachable and no sub-agent could be dispatched, and
    # market-sizing ran anyway -- hand-writing every hand-off file, grading its own checklist, and
    # shipping a report with no adversarial review and no gates. One line detects it; the skill now
    # stops and says so instead of producing something that reads as checked.
    # +592 B (101_686 -> 102_278): a review is final. MEASURED on a live run, with no
    # compaction and the full SKILL.md in context: the main thread re-ran the whole pipeline three
    # times on red-team findings and then rewrote the review itself, because the text told it a
    # filename "must be removed" and gave no route but editing the review. The sentence is gone (the
    # producer now words the review); RED_TEAM_FINDINGS joins the content findings, the four review
    # codes are named, Late-edits is scoped to before Step 6c, the percent-scale question moves
    # before the review (Step 5.5), and a what-if writes to staging. The durable half is in the
    # scripts and warning messages; this is the half that says why.
    # +2,157 B (102_278 -> 104_435): Step 6d, the one founder-approved revision round. Without it a
    # true red-team finding had no sanctioned route but editing, and the measured run took three
    # unapproved rounds. The step names the trigger, both questions, the approval record the
    # producer checks, the round-2 hand-off paths (the resolver and generator refuse or misroute
    # without them -- measured in the rev-3 review), and the no-questions default. The bounds live
    # in _redteam_copy.py (rounds, FOUNDER_INPUT_REWRITTEN); this is what a model in context needs to
    # take the route instead of improvising one.
    # +714 B (104_435 -> 105_149): the two-figures question, before Step A. MEASURED on the same run:
    # the founder typed a monthly rate and the deck stated a different blended rate; with one slot for "what
    # the founder said", the main thread picked the deck's on a red-team finding's say-so and wrote
    # it over the founder's. Now the founder picks, the choice records its source, and the other
    # figure is kept and shown. Plus the no-questions default names this question too.
    # +151 B (105_149 -> 105_300): the founder's answer is recorded (founder_stated_choice) and the
    # report claims a choice only then -- MEASURED on a live run, the question was skipped and the
    # report still said "the one you chose"; and the inline `factors` rule names `role: divisor`,
    # because a live run wrote a ratio as a bare chain, hit the mismatch and gave up.
    # -1,552 B (105_300 -> 103_748), LOWERED: sizing inputs are now references to recorded figures,
    # so the dispatch templates lost their per-figure currency instructions and the pipe's FX
    # re-run recipe (currency and rates now live on the research record); Step 4 gained the unit
    # vocabulary, Steps 5/6a/6b/6d the reference contract, the --validation/--inputs/--sizing
    # flags and --replay, and Step 7 the inputs-integrity codes. Net smaller.
    # +264 B (103_748 -> 104_012): a founder figure's `label` is the page's own words, because the
    # report names the page only when they are found on it -- MEASURED on a live run, two deck
    # figures were labelled "chat" and the report told the founder they had typed them. A size
    # reduction pass over this SKILL.md is planned separately.
    # +237 B (104_012 -> 104_249): a revision's reason for changing a figure goes in the approved
    # change's unrendered `reason` -- MEASURED on a live run, the flat "labels never describe history"
    # rule was broken with the reason written into the label, and the report printed it.
    # +37 B (104_249 -> 104_286): the sensitivity pipe passes --inputs, so a founder figure left
    # without a range is varied across the founder's own other figures for it.
    # -3,475 B (104_286 -> 100_811), LOWERED: the CHECKLIST prompt template moved into
    # dispatch_prompt.py, which prints it -- the main thread rewrote it on both rounds of a live run.
    # +99 B (100_811 -> 100_910): Step 10 no longer invites "a greeting before" the printed hand-over --
    # both live evaluators read it as licence for the model's own verdict (3/3 runs) -- and says the
    # printed text already answers whether the founder's figures hold up.
    # +121 B (100_910 -> 101_031): Step 6d stops asking the model to write an approval (a live run
    # recorded one from an answer to a different question, and the page claimed a revision the founder
    # never made), and says which review is shown and that later ones are listed.
    # +1,518 B (101_013 -> 102_531): the file tools refuse a relative path, so
    # Step 0 gains the proof of the file-tool path of outputs (probe + --set-host-outputs-dir), the
    # hand-off protocol gains the `write_refused` branch (both contexts), and the degrade rule tells
    # the founder instead of noting it. The procedure itself lives once in skill-execution-model.md.
    # +218 B (102_531 -> 102_749): the exit-3 / exit-6 corrective redo of a GENERATED prompt
    # (RED_TEAM, CHECKLIST) re-runs dispatch_prompt.py with --correction; a line typed onto the
    # printed prompt is held by the dispatch hook and its correction dropped.
    # +313 B (102_749 -> 103_062): Step 6d records the revise-or-deliver answer with
    # record_revision_answer.py (both paths, including no-questions); a live run skipped the question
    # silently, and compose now discloses REVISION_NOT_OFFERED when no answer was recorded. Step 7 names it.
    # -17 B (103_062 -> 103_045): the Step-A gate example's ARPU is quoted from the deck, not "derived from
    # ARR/customers" in chat, which the Execution checkpoint forbids and a live run copied.
    # +386 B (102_926 -> 103_312): which deck figure is the one compared when a deck states several
    # (the market-size slide's, else the first), and that a figure for another date is not a rival
    # claim -- without it a today/2030 pair told the founder their materials disagree.
    # +111 B (103_312 -> 103_423): the compared figure is first the one dated to the sizing's year, so a
    # market slide headlining a future TAM is not compared against a current-year sizing.
    # 103_423 -> 103_493 (+70 B), and the same +70 B in ic-sim, financial-model-review and
    # competitive-positioning: Step 0's fallback search for earlier artifacts names its folder (`path` =
    # the printed ARTIFACTS_ROOT). Without it a cloud session searches from the home directory. The
    # pattern is also corrected to the file founder_context.py writes (founder-context-<slug>.json).
    # Guarded by test_every_instructed_file_search_names_its_folder.
    # 103,493 -> 104,745 on 2026-10-02: Step 0 tells whether this skill's text arrived with its plugin folder
    # filled in and, only when it did not (a skill started as the first message of a new conversation), finds
    # the plugin by a filesystem search and prints READ_ROOT= for the Reads and sub-agent prompts.
    # 104,745 -> 104,557 on 2026-10-03: Step 0's preflight comment is two lines, the plugin-paths paragraph is
    # shorter and plainer, a manifest-less plugin copy is kept by the search, and the block says to run it
    # with the token as shown and that PLUGIN_ROOT is for shell commands only. One reference Read directive
    # names its file under the plugin token.
    # 104,557 -> 104,509 on 2026-10-03: the CHECKLIST prompt generator no longer takes the plugin folder as
    # an argument, so its command line and the plugin-paths paragraph drop it; Step 0 says PLUGIN_ROOT never
    # goes into a sub-agent prompt. (The other four skills' SKILL.mds took the last two edits at net 0 B.)
    # 104,509 -> 104,572 (+63 B) on 2026-10-03, the same +63 B in all six: Step 0's PLUGIN_ROOT comment names it
    # the shell's path and states the one exception, a printed READ_ROOT= used in Reads and prompts.
    # 104,572 -> 104,703 on 2026-10-04: "never delete under outputs" is this skill's rule, not a platform
    # limit (newer hosts allow deletes). Step 0's append-only paragraph, the hand-off comment and the retry
    # line say so instead of claiming the host refuses.
    # 104,703 -> 104,968 on 2026-10-04: The setup block ends by printing RUN_ID, STAGING_DIR and HANDOFF_DIR (each later
    # command runs in a fresh shell); the quick-check producer reads a fill-in heredoc instead of an undefined
    # $QUICK_JSON; the overwrite note names the no-delete rule, not a host refusal.
    # 104,968 -> 105,040 on 2026-10-04: the setup print also gives the hand-off dir's file-tool path, and
    # labels the two: the shell path is for shell commands, the other for Read/Write.
    # 105,040 -> 105,301 on 2026-10-04: a producer rejection of a generated prompt's hand-off is sent back
    # through the generator (`--correction producer-rejected --detail-file`), whose output the dispatch hook
    # compares, instead of a typed repair the hook would hold.
    # 105,301 -> 105,319 on 2026-10-04: the producer's rejection is saved under the run's hand-off dir
    # (`$HANDOFF_DIR/producer_rejected.txt`), the file the dispatch hook checks the redo against.
    # 105,319 -> 105,431 (+112 B) on 2026-10-05: Step 0 no longer defines a reference
    # folder for the shell (REFS=/SHARED_REFS=, a VM path the Read tool is refused) and names the folder
    # for Reads in prose, as loaded; every read directive names its file under the plugin token, never a
    # bare relative references/ path or a printed shell value.
    # 105,431 -> 105,936 (+505 B) on 2026-10-05: a PowerPoint deck converts into the run's hand-off folder,
    # not $STAGING_DIR (refused to the Read tool on a local session), and the block prints the Read tool's
    # path to the PDF. The append-only paragraph names the exception.
    # 105,936 -> 105,949 (+13 B) on 2026-10-05: the read-directive clauses say "never the shell's path to the
    # plugin folder" instead of "never a path the shell printed", which also covered the hand-off paths the
    # shell prints for Reads.
    # 105,949 -> 106,045 (+96 B) on 2026-10-05: the conversion block makes its own LibreOffice profile folder (a later
    # block's shell has no setup variables).
    # 105,857 -> 105,980 (+123 B) on 2026-10-05: the resolver's exit 3 (no uploads
    # folder found) no longer reads as "no session tree": on the cloud lane the per-session uploads folder
    # exists only once something is attached, so the reason names both causes (nothing attached, or a host
    # that keeps uploads elsewhere) and asks for a path when documents were attached.
    # 105,980 -> 106,132 on 2026-10-05: the description says the skill starts on its own only on a clear request,
    # and that a passing question gets a short answer and an offer naming how long the run takes.
    # 106,132 -> 106,386 (+254 B) on 2026-10-05: a late edit before Step 6c re-dispatches under the same
    # RUN_ID (a fresh id on a few files leaves them the minority, so compose refuses the review after them),
    # and a recorded skip carries red_team_skipped_run_id, since compose accepts only this run's skip.
    # 106,386 -> 106,463 (+77 B) on 2026-10-05: on exit 3 the review step copies the founder documents
    # read earlier, from the path they were read at, into the hand-off docs folder, and asks for a path only
    # with none, so the review still sees them and an unattended host does not stall.
    # 106,463 -> 106,491 (+28 B) on 2026-10-05: the feedback lines tell the founder to type
    # `/founder-skills:feedback`; it is a user-started skill now, which the model cannot start.
    # 106,491 -> 107,276 (+785 B) on 2026-10-05: the Step 0 STAGING_DIR block says
    # scratch output (a redirect or a temp file) goes in $STAGING_DIR, never a fixed /tmp/<name>, because
    # /tmp is shared across sessions (+126 B). Each generator call says to run it
    # in a shell call of its own, nothing before it but assignments (a command run before it in the same
    # call leaves the dispatch hook no printed prompt to match), and the red-team generator moves out of
    # the OCR call's block. Step 10 sends the files first and runs the closer as the last tool call, its
    # printed output the entire final message, character for character: a closer run before the
    # delivery left the host's own after-delivery summary rule as the last word, and the model rewrote
    # the hand-over. Beside the closer, its printed archive offer is the only offer made, and a connected
    # folder is written to only if the founder asks.
    # 107,276 -> 106,282 (-994), LOWERED, commit 6 (gates): the three catalog sections out (-1,585); the
    # TOP_DOWN/BOTTOM_UP templates out, printed by dispatch_prompt.py (-3,779); Step 0 starts the run's
    # record, the slug block binds it, Step 1 and every question site open, ask and record, exit 10 is a
    # question at Steps 5 and 7, the quick check finishes, Step 9's page carries the run id and Step 10
    # closes the file list (+4,370).
    # 106,282 -> 106,256 (-26), LOWERED, commit 10 (O3): the compose step says to read compose_result.json on a
    # non-zero exit, paid for in the same step; "Two codes sit in neither class" loses its aside.
    # -1 B, LOWERED, commit 13: a derived stage takes its option id and no value; the sentence is shortened to pay.
    "market-sizing": 106_247,
    # fmr raised for two founder-facing-correctness items measured in a live run: the CHECKLIST
    # dispatch now forbids citing our artifact filenames in evidence (that run put `inputs.json` in 10
    # items' evidence, printed verbatim into the founder's report), and the producer pipe passes
    # --inputs so the scoring records a fingerprint of what it graded — without it that fingerprint is
    # null and staleness cannot be detected for this artifact at all.
    # fmr raised 79,279 -> 79,649 (+370 B) for the Context B `score_coverage` instruction. The
    # coaching sub-agent reasons from a CLOSED key list, so a payload field absent from the
    # dispatch is a field it never reads: without this the coach keeps writing "strong" over a
    # score whose denominator silently lost the criteria an unmatched profile field dropped.
    # Deliberate, per this test's own remedy, and the wording was tightened first.
    # A9, all six: +1 line each — `insert_coaching.py --report-json`. Without it report.json keeps
    # the pre-coaching text and a raw uuid insertion marker (measured 5,592 B adrift on a live
    # run). Syncing rather than dropping the key, because ~200 test sites across the fleet read
    # report_markdown out of the composed JSON to inspect report content.
    # All three raised for the cowork-harness 2.4.0 cwd fix, which turned three cwd-relative shell
    # paths from benign into silently wrong. 2.4.0 moves the workspace shell's cwd to the BARE SESSION
    # ROOT; `./artifacts` used to resolve to the canonical root and now lands in `/sessions/<id>/`,
    # outside `mnt/`, where nothing is delivered and nothing reports it. cp/fmr: the self-heal branch
    # said `mkdir -p ./artifacts` (market-sizing and ic-sim already said `"$ARTIFACTS_ROOT"` — this was
    # drift, fixed in 2 of 6). deck-review: the uploads listing was `... || ls -la ./mnt/uploads`, whose
    # MEANING moved with the cwd (it pointed at a path that never existed before 2.4.0 and at the real
    # mount after), so it now calls `resolve_artifacts_root.py --uploads` — one opaque command, per that
    # module's own rationale. Each sentence was tightened before raising, and deck-review NET SHRANK
    # from its first draft by rewriting a captured-variable form that violated
    # test_no_shell_variable_capture_of_python_output. Analysis:
    # docs/internal/2026-08-27-cowork-harness-2.4.0-adoption-plan.md SS3.2.
    # +exit-8 Context A bullet and +Context B "any other exit" catch-all, all six (2026-08-31).
    # ONE shared reason for six near-identical raises, referenced rather than repeated:
    # `check_handoff.py` defines seven typed exits; the Context A gate table documented five and
    # omitted exit 8 -- the branch the code was written for, since Context A is where OUTPUT_PATH is
    # built from $HANDOFF_AGENT and where the doubled-prefix condition occurs. Exit 8 therefore fell
    # to "Any other exit -> STOP", halting a run over a condition the gate's own diagnostic says is
    # recoverable by a prefix correction. Context B separately had no catch-all at all, so an exit 4
    # (reachable there on an IO fault) or an uncaught decode error had no documented branch.
    # Guarded by test_context_a_gate_table_documents_exit_8 in test_handoff_contract_ratchet.py.
    # SHRANK: the unscoped "canonical artifacts are producer-script-only" justification was
    # rescoped to "you never write a canonical artifact" across all 22 sites (W2 audit). The
    # instruction was always correct; the REASON given for it asserted the general claim P0-2
    # established is false — the main thread writes several canonical artifacts by heredoc.
    # financial-model-review 80,780 -> 81,462 (+682 B): Step 3.6 offered "I need to correct something --
    # I'll say what in chat" on the upload lane and nothing implemented it. The route now exists
    # (`apply_corrections.py --set PATH=VALUE`, same pipeline as the page download, so coercion and
    # the audit record survive), and Path A names it as a third option with the command.
    # financial-model-review 81,462 -> 81,660 (+198 B): the Context B instruction gave the coach ONE
    # cause for an incomplete score -- "because `unmatched_profile_fields` could not be matched" --
    # and that list is EMPTY for the cause that actually occurs (the assessor setting a criterion
    # aside), so the founder was being told the wrong reason. The replacement names both causes,
    # says which field distinguishes them, and says they can BOTH apply: `not_assessed_count` is
    # their sum, so an either/or reading loses the self-gated half of a mixed run.
    # financial-model-review 81,660 -> 81,685 (+25 B): a fourth medium-severity warning class
    # exists (a finding stating a "times" comparison its own cited figures contradict), and :718
    # enumerates the medium classes rather than describing them generically -- so leaving it out
    # would have made SKILL.md assert an incomplete fact about `validation.warnings`, which is the
    # same recurring shape as the `company_name` and STRUCT_08 defects.
    # +129 B (fleet, one shared edit): the delivery block's hand-over sentence said the link form in
    # Cowork is `computer://` + the absolute path. MEASURED in-app on the remote lane (2026-09-21/22,
    # the default lane for new sessions and the one the market-sizing bug report came from): no link
    # form opens a file there -- computer:// is plain text and a bare path becomes a broken claude.ai
    # URL; the presented card is the delivery. The sentence now says: a link where this surface
    # renders one that opens (on a /sessions tree, computer:// + the path), otherwise the label with
    # the path stated beside it. Same edit in all six; test_delivery_block_is_identical_fleet_wide
    # is the proof.
    # +1,275 B (fleet, one shared edit): the Step 0 preflight and its stop. MEASURED 2026-09-22 on
    # claude.ai, which mounts skills FLAT at /mnt/skills/plugins/<plugin>:<skill>/ and serves no
    # plugin: the shared scripts were unreachable and no sub-agent could be dispatched, and
    # market-sizing ran anyway -- hand-writing every hand-off file, grading its own checklist, and
    # shipping a report with no adversarial review and no gates. One line detects it; the skill now
    # stops and says so instead of producing something that reads as checked.
    # +1,485 B (83_089 -> 84_574): the file tools refuse a relative path, so Step 0 gains the proof
    # of the file-tool path of outputs (probe + --set-host-outputs-dir), the hand-off protocol gains
    # the `write_refused` branch (both contexts), and the degrade rule tells the founder instead of
    # noting it. The procedure itself lives once in skill-execution-model.md.
    # -893 B (84_574 -> 83_681): the hand-over is printed by fmr_closing_message.py; Main-Thread Return no
    # longer walks the model through restating runway and status fields in chat, which is how a live run
    # computed figures in the hand-over.
    # +1,332 B (83_680 -> 85_012): unit economics and runway now run BEFORE the checklist (Step 4), and
    # the CHECKLIST template tells the grader to grade against their figures -- planning-number runway,
    # a reference grade where one exists, warn (never not_applicable) on a deliberately withheld metric,
    # and that our figures show a figure is computable, never that the model shows it.
    # 85_012 -> 85_082 (+70 B): the Step 0 search names its folder; see market-sizing above.
    # 85,082 -> 86,561 on 2026-10-02: Step 0 tells whether this skill's text arrived with its plugin folder
    # filled in and, only when it did not (a skill started as the first message of a new conversation), finds
    # the plugin by a filesystem search and prints READ_ROOT= for the Reads and sub-agent prompts. The
    # INPUTS_REVIEW and CHECKLIST prompts gain the sub-agent fallback for a refused reference path.
    # 86,561 -> 86,384 on 2026-10-03: Step 0's preflight comment is two lines, the plugin-paths paragraph is
    # shorter and plainer, a manifest-less plugin copy is kept by the search, and the block says to run it
    # with the token as shown and that PLUGIN_ROOT is for shell commands only.
    # 86,384 -> 86,447 (+63 B) on 2026-10-03, the same +63 B in all six: Step 0's PLUGIN_ROOT comment names it
    # the shell's path and states the one exception, a printed READ_ROOT= used in Reads and prompts.
    # 86,447 -> 86,741 on 2026-10-03: Step 3.6 always builds the review page static (server mode only when
    # the founder asks for live validation in a local terminal) and sends review.html as a file, not a path.
    # 86,741 -> 86,851 on 2026-10-03: Step 3.6 sends review.html with the host's file-delivery tool where one
    # is offered and gives its absolute path in a local terminal with none; the server-mode rule names the
    # session (a local command-line terminal on the founder's own computer) rather than where the shell runs.
    # 86,851 -> 86,996 on 2026-10-04: "never delete under outputs" is this skill's rule, not a platform
    # limit (newer hosts allow deletes). Step 0's append-only paragraph, the hand-off comment and the retry
    # line say so instead of claiming the host refuses. Three more lines here blamed the host for a delete;
    # they now name the rule.
    # 86,996 -> 87,076 on 2026-10-04: The quick-check producer reads a fill-in heredoc instead of an undefined
    # $QUICK_JSON; the overwrite note names the no-delete rule, not a host refusal.
    # 87,076 -> 83,909 on 2026-10-04: the CHECKLIST prompt template moved into fmr_dispatch_prompt.py; Step 5
    # runs the generator and sends its output unchanged. The redo bullets name its --correction forms.
    # 83,909 -> 84,142 on 2026-10-04: Step 5's block sets RUN_ID, HANDOFF_AGENT, REVIEW_DIR_AGENT and
    # REVIEW_DIR again before the generator call. Each shell starts fresh, and an unset one rendered
    # `OUTPUT_PATH: /checklist_output.json`; the generator now refuses an empty value.
    # 84,142 -> 84,316 (+174 B) on 2026-10-05: Step 0 no longer defines a reference
    # folder for the shell (REFS=/SHARED_REFS=, a VM path the Read tool is refused) and names the folder
    # for Reads in prose, as loaded; every read directive names its file under the plugin token, never a
    # bare relative references/ path or a printed shell value.
    # 84,316 -> 84,329 (+13 B) on 2026-10-05: the read-directive clauses say "never the shell's path to the
    # plugin folder" instead of "never a path the shell printed", which also covered the hand-off paths the
    # shell prints for Reads.
    # 84,200 -> 84,022 on 2026-10-05: the description says the skill starts on its own only on a clear request,
    # and that a passing question gets a short answer and an offer naming how long the run takes.
    # 84,022 -> 84,050 (+28 B) on 2026-10-05: the feedback lines tell the founder to type
    # `/founder-skills:feedback`; it is a user-started skill now, which the model cannot start.
    # 84,050 -> 84,789 (+739 B) on 2026-10-05: the Step 0 STAGING_DIR block says
    # scratch output (a redirect or a temp file) goes in $STAGING_DIR, never a fixed /tmp/<name>, because
    # /tmp is shared across sessions (+126 B). The CHECKLIST generator call says to run
    # it in a shell call of its own (see market-sizing). Step 5-quick shows the minimal runway input
    # (cash and net burn, no company block) and drops a --stdin flag runway.py does not accept, which
    # failed every quick check's first call. Step 12 sends the files first and runs the closer last,
    # its output the whole final message (see market-sizing); Verification Gate 2 no longer lists file
    # paths to present, and Main-Thread Return no longer offers the HTML paths beside the hand-over.
    # 84_789 -> 85_546 on 2026-10-05: the hand-over asks for the cash balance when runway could
    # not be computed without one, so Step 12 says what to do with the reply: record it with
    # apply_corrections.py --set, promote, re-run runway and the steps after it, the closer last.
    # 85,544 -> 85,520 (-24 B) on 2026-10-07: gates wired. The catalog sections are out (the one plugin-root
    # references pointer kept); Step 0 starts the run's record, the slug block binds it, Step 1 opens its
    # questions before asking and records each, Step 3.6 is one recorded question for both input paths (open
    # before the page), exit 10 is a question at Steps 4 and 7, the pages carry the run id, Step 12 closes the
    # file list and records the cash reply. Five restatements trimmed to fit (the AskUserQuestion-fallback aside,
    # the coaching heredoc parenthetical, Step 12's repeated no-rm paragraph, a stale five-skills sentence, the
    # Path B anecdote).
    # 85,520 -> 85,517 (-3), LOWERED, commit 10 (O3): the compose step says to read compose_result.json on a non-
    # zero exit, paid for in the same step; the heredoc warning shortened, its reason kept.
    "financial-model-review": 85_475,
    # ic-sim SHRANK: the REQUIRED ic-dynamics.md read at Step 7 is deleted. Step 7 is a pure producer
    # pipe — compose_discussion.py derives discussion.json from the partners' own files and nothing
    # is authored by the main thread — so the read informed no decision while pulling a whole
    # reference into context. The Available References entry now says it is background, not a read.
    # A9, all six: +1 line each — `insert_coaching.py --report-json`. Without it report.json keeps
    # the pre-coaching text and a raw uuid insertion marker (measured 5,592 B adrift on a live
    # run). Syncing rather than dropping the key, because ~200 test sites across the fleet read
    # report_markdown out of the composed JSON to inspect report content.
    # +exit-8 Context A bullet and +Context B "any other exit" catch-all, all six (2026-08-31).
    # ONE shared reason for six near-identical raises, referenced rather than repeated:
    # `check_handoff.py` defines seven typed exits; the Context A gate table documented five and
    # omitted exit 8 -- the branch the code was written for, since Context A is where OUTPUT_PATH is
    # built from $HANDOFF_AGENT and where the doubled-prefix condition occurs. Exit 8 therefore fell
    # to "Any other exit -> STOP", halting a run over a condition the gate's own diagnostic says is
    # recoverable by a prefix correction. Context B separately had no catch-all at all, so an exit 4
    # (reachable there on an IO fault) or an uncaught decode error had no documented branch.
    # Guarded by test_context_a_gate_table_documents_exit_8 in test_handoff_contract_ratchet.py.
    # SHRANK: the unscoped "canonical artifacts are producer-script-only" justification was
    # rescoped to "you never write a canonical artifact" across all 22 sites (W2 audit). The
    # instruction was always correct; the REASON given for it asserted the general claim P0-2
    # established is false — the main thread writes several canonical artifacts by heredoc.
    # ic-sim +20 B (90_323 -> 90_343): `consensus_strength` added to the dispatch key list.
    # compose emitted it and the FINAL-SUMMARY section read it, but the coaching dispatch did
    # not name it, so commentary was composed blind to a 1-1-1 partner split and the headline
    # read as the committee's settled view.
    # +129 B (fleet, one shared edit): the delivery block's hand-over sentence said the link form in
    # Cowork is `computer://` + the absolute path. MEASURED in-app on the remote lane (2026-09-21/22,
    # the default lane for new sessions and the one the market-sizing bug report came from): no link
    # form opens a file there -- computer:// is plain text and a bare path becomes a broken claude.ai
    # URL; the presented card is the delivery. The sentence now says: a link where this surface
    # renders one that opens (on a /sessions tree, computer:// + the path), otherwise the label with
    # the path stated beside it. Same edit in all six; test_delivery_block_is_identical_fleet_wide
    # is the proof.
    # +1,275 B (fleet, one shared edit): the Step 0 preflight and its stop. MEASURED 2026-09-22 on
    # claude.ai, which mounts skills FLAT at /mnt/skills/plugins/<plugin>:<skill>/ and serves no
    # plugin: the shared scripts were unreachable and no sub-agent could be dispatched, and
    # market-sizing ran anyway -- hand-writing every hand-off file, grading its own checklist, and
    # shipping a report with no adversarial review and no gates. One line detects it; the skill now
    # stops and says so instead of producing something that reads as checked.
    # +1,574 B (91_747 -> 93_321): the file tools refuse a relative path, so Step 0 gains the proof
    # of the file-tool path of outputs (probe + --set-host-outputs-dir), the hand-off protocol gains
    # the `write_refused` branch (both contexts), and the degrade rule tells the founder instead of
    # noting it. The procedure itself lives once in skill-execution-model.md.
    # 93_281 -> 93_351 (+70 B): the Step 0 search names its folder; see market-sizing above.
    # 93,351 -> 94,596 on 2026-10-02: Step 0 tells whether this skill's text arrived with its plugin folder
    # filled in and, only when it did not (a skill started as the first message of a new conversation), finds
    # the plugin by a filesystem search and prints READ_ROOT= for the Reads and sub-agent prompts.
    # 94,596 -> 94,365 on 2026-10-03: Step 0's preflight comment is two lines, the plugin-paths paragraph is
    # shorter and plainer, a manifest-less plugin copy is kept by the search, and the block says to run it
    # with the token as shown and that PLUGIN_ROOT is for shell commands only.
    # 94,365 -> 94,428 (+63 B) on 2026-10-03, the same +63 B in all six: Step 0's PLUGIN_ROOT comment names it
    # the shell's path and states the one exception, a printed READ_ROOT= used in Reads and prompts.
    # 94,428 -> 94,559 on 2026-10-04: "never delete under outputs" is this skill's rule, not a platform
    # limit (newer hosts allow deletes). Step 0's append-only paragraph, the hand-off comment and the retry
    # line say so instead of claiming the host refuses.
    # 94,559 -> 94,770 on 2026-10-04: The setup block ends by printing RUN_ID, STAGING_DIR and HANDOFF_DIR (each later
    # command runs in a fresh shell); the overwrite note names the no-delete rule, not a host refusal.
    # 94,770 -> 94,940 (+170 B) on 2026-10-05: Step 0 no longer defines a reference
    # folder for the shell (REFS=/SHARED_REFS=, a VM path the Read tool is refused) and names the folder
    # for Reads in prose, as loaded; every read directive names its file under the plugin token, never a
    # bare relative references/ path or a printed shell value.
    # 94,940 -> 94,979 (+39 B) on 2026-10-05: the read-directive clauses say "never the shell's path to the
    # plugin folder" instead of "never a path the shell printed", which also covered the hand-off paths the
    # shell prints for Reads.
    # 94,675 -> 94,687 on 2026-10-05: the description says the skill starts on its own only on a clear request,
    # and that a passing question gets a short answer and an offer naming how long the run takes.
    # The in-skill offer names the run's duration in place of 'several minutes'.
    # 94,687 -> 94,715 (+28 B) on 2026-10-05: the feedback lines tell the founder to type
    # `/founder-skills:feedback`; it is a user-started skill now, which the model cannot start.
    # 94,715 -> 94,841 (+126 B) on 2026-10-05: the Step 0 STAGING_DIR block says
    # scratch output (a redirect or a temp file) goes in $STAGING_DIR, never a fixed /tmp/<name>, because
    # /tmp is shared across sessions.
    # 94,841 -> 94,814 (-27 B) on 2026-10-08: gates wired. The catalog sections (Skill Metadata, Available
    # Scripts, Available References) are out, their maintainer notes moved to the three reference headers; Step 0
    # starts the run's record after the run-it-now offer, the slug block binds it, Step 1 opens the shared
    # questions with the mode and fund, Step 8.5 opens the decline question by script, compose and the page
    # carry exit-10 / finished-run sentences, Step 12 closes the deliverables list. Eight restatements trimmed.
    # 94,814 -> 94,811 (-3), LOWERED, commit 10 (O3): the compose step says to read compose_result.json on a non-
    # zero exit, paid for in the same step; the heredoc warning shortened, its reason kept.
    # -5 B, LOWERED, commit 13: Step 8.5 names the GATE_UNDECIDABLE remedy (re-run Step 8, same RUN_ID), paid for
    # by two rationale clauses in the same step; a derived stage takes its option id and no value.
    "ic-sim": 94_798,
    # deck-review +1,165 B: Step 0 carried only a parenthetical fresh-shell mention buried in a code
    # comment, unlike the four skills that mint RUN_ID in a LATER block and so carry the shared banner.
    # deck-review mints RUN_ID INSIDE this re-runnable Step-0 block (like cap-table), so the shared
    # banner's remedy ("re-run the whole block") is unsafe here — it would re-mint a different RUN_ID
    # mid-engagement. Added its own fact-plus-remedy sentence instead: re-deriving the pure path vars is
    # safe, but RUN_ID is re-established from setup_run.py's printed run_id, never from re-running the
    # mint line.
    # 71_081 -> 71_498 (R1): the CHECKLIST dispatch now specifies `notes` as the
    # founder-facing fix. `notes` was previously defined nowhere, so its content was
    # run-dependent and the "priority fixes" section rendered methodology as advice.
    # 71_567 -> 73_826 (PPTX): the skill advertised PowerPoint in `when_to_use` and scored
    # Design & Readability for `input_format: "pptx"`, but nothing converted or read a .pptx --
    # Read refuses the binary. A founder uploading PowerPoint got a design score from a
    # reviewer that never saw a slide. Step 2 now converts via LibreOffice, and falls back to
    # text-only with the design criteria gated when no converter exists.
    # 71_498 -> 71_567 (R2): `score_pct` now gives a warn half credit, so the formula
    # line and the What-If rule both had to stop saying "warn/fail earn no credit".
    # R3/R6: verdict-first coaching order, and the visual-pass record (input_quality now
    # required, per-slide visual_evidence_captured, 20-page read batches).
    # 78_224 -> 87_344 (R5): the numeric chain — four new steps (3.5 ledger extraction,
    # 3.6 second read, 3.7 relation proposal, 3.8 reconcile). This is the
    # largest single increase this file has taken and it buys a capability the skill has
    # claimed for its whole life without having: `numbers_consistent` is one of the 35
    # criteria and was scored entirely on the reviewer's say-so, with no arithmetic
    # anywhere in the skill. Three of the four steps are dispatch templates, which is
    # where the bytes are; the templates are prescriptive rather than descriptive because
    # the full-scale rule and the second read's blindness are both properties of the
    # prompt, and a paraphrase of either silently disarms a gate. The last +301 B extends
    # the resume rule to cover 3.5-3.8: it named Steps 2 and 3 only, so a gate round-trip
    # would have re-run the chain's three dispatches — two of which read the deck — for an
    # identical result.
    # 87_645 -> 91_744 (R5 Phase 3): Step 3.9, a demote-only review of surviving
    # contradictions. Most of the +4,099 B is the two withdrawal grounds spelled out with
    # the layout question that decides the first, plus the explicit refusal of a third
    # ground the model will otherwise reach for — a deck writing "400%" where it means 4x
    # looks like a mis-specified relation and is measured to be a real finding. Prose is
    # the only place that instruction can live, since the producer can reject an
    # out-of-set class but cannot talk the model out of wanting one.
    # +240 B: the RELATION_PROPOSAL template now closes the `kind` enum. Measured in the
    # live run — it documented `operator`'s values and said nothing about `kind`'s, so the
    # sub-agent generalised from the one example and emitted `component_sum` for a sum of
    # cost lines. Rejected loudly and recovered on a retry, but an enum shown once by
    # example reads as a suggestion.
    # +326 B: the LEDGER_EXTRACTION template now tells the model to spell out a trailing
    # letter that is a UNIT rather than a multiplier. A real deck stated tower heights as
    # "200-400m"; bare `m` reads as millions, a space does not help, and the code CANNOT
    # decide — "32.5m businesses" recorded as 32.5 is structurally identical. Only the
    # model saw the slide, so only the model can disambiguate; the producer validates.
    # deck-review raised 92,310 -> 92,668 (+358 B) for the Context B `design_gate` field and the
    # corrected gate-count prose. `summary.not_applicable` is a bare count, so a coach handed only
    # that wrote "strong" over design criteria nobody could assess. The prose edits are net-neutral
    # digit swaps plus one clause naming `slide_count_appropriate` as deliberately still scored --
    # the gate forces 4 of the category's 5, and five sites said 5. Deliberate.
    # deck-review 92,683 -> 92,687 (+4): the second-read section's independence claims were
    # corrected. The step is not an independent or vision reading of the DECK — the reader is
    # handed the same extracted text the ledger agent got — and it corroborates a quote, not a
    # figure's value. Saying that accurately is close to length-neutral: "ledger-blind" paid for
    # most of it, and the +4 is "so a reworded sentence fails" replacing "so a paraphrase fails",
    # which was false — the matcher falls back to a fuzzy pass at 0.85, so a near-identical
    # restatement DOES pass. That nuance is documented in reconcile.py and agents/deck-review.md
    # rather than here, deliberately: telling the extracting agent what the matcher tolerates
    # invites the sloppiness the verbatim instruction exists to prevent.
    # See test_no_independence_claims.py.
    # deck-review 92,687 -> 93,208 (+521): gate answers now record where they came from, and the
    # deleted inline resume detector paid for less than half of it. Three additions, each of which
    # costs more to omit than it costs in bytes. (a) `--source` is REQUIRED on `gate_state.py
    # answer`, and an undocumented required flag is argparse exit 2 in production — this file's own
    # comment records the last time the model copied `emit`'s flags onto `answer` and hit exactly
    # that. (b) `auto_satisfied` is legal only on the `stage_confirmation` gate and only for "Looks
    # right"; without stating the restriction the model tries it on out_of_scope_choice and the
    # script refuses mid-run. (c) a third auto-satisfy condition — there must BE a Step 1 answer —
    # which IS the reported defect: a skipped form was treated as one and the gate self-answered.
    # The re-invocation section shrank: the inline `python3 -c` detector that read gate_state.json
    # directly is gone, because resume detection weighs run_id parity AND answer provenance, and a
    # second copy of that rule in shell had already drifted from setup_run.py's.
    # deck-review 93,208 -> 93,549 (+341): compose_report.py gains --gate-state, and the flag is
    # optional at the CLI (a caller with no gate must not be forced to invent one) but mandatory in
    # the pipeline. Nothing about an optional flag's own shape stops the skill from dropping it, and
    # a dropped flag is silent by construction — the report composes cleanly and simply never
    # discloses a stage confirmed on the founder's behalf. The prose says pass it even when you
    # believe the run never gated, because that belief is the failure mode.
    # deck-review 93,549 -> 93,749 (+200): the LEDGER_EXTRACTION template now says to keep the words
    # that say what the number IS. `quote` was specified only as "verbatim", which "$493K" satisfies
    # while identifying nothing — the second read matches TEXT, so a quote of nothing but the figure
    # is re-found on any slide that prints that figure. ledger.py warns on it now, and a warning the
    # extracting agent was never given the rule for is a warning nobody can act on.
    # deck-review 93,749 -> 94,262 (+513): review found that splitting resume-eligibility from
    # checkpoint-preservation inside setup_run.py bought nothing while SKILL.md still keyed its
    # "skip Steps 2 and 3" branch on `resume`. The two come apart on exactly the case the split was
    # built for — an unauditable same-run answer preserves the checkpoints and is not resumed — so
    # the preserved artifacts were re-run and overwritten, spending the three dispatches the
    # preservation exists to protect. The skip now reads `reuse_checkpoints`, and the distinction is
    # stated, because a reader who does not know the two differ reaches for the familiar one.
    # deck-review 94,262 -> 94,528 (+266): the LEDGER_EXTRACTION template said "a reworded sentence
    # fails the check and the figure is dropped", which is false — measured, the matcher accepts
    # increased/decreased, double/decline and $45B/$46B through its 0.85 fuzzy fallback. This is the
    # PRODUCTION instruction the extracting agent reads, and it was missed when the same claim was
    # corrected in the agent body, because the approved-wording guard requires only one approved
    # substring per file and cannot see a false claim in the next paragraph. It now says what the
    # gate establishes — a quote found nowhere is dropped — and says the match is not word-for-word
    # while still telling the agent to copy the wording, which is what makes the check worth running.
    # deck-review 94,528 -> 94,777 (+249): a SECOND overclaim axis, which the wording ratchet above
    # does not reach. Step 3.6 was titled "Re-Read Those Slides" and its dispatch said "transcribe
    # the slides listed below from the deck" — but the second reader is handed the SAME extracted
    # text the ledger agent got, so it can establish that a quote exists in that text and nothing
    # about whether the extraction matched the slide. A reader who believes the pass returned to the
    # file over-trusts every figure it clears. The dispatch now says what it actually receives, and
    # says it is not re-reading, because removing a false claim without stating the true one leaves
    # the sub-agent to assume.
    # deck-review 94,777 -> 95,586 (+809): setup_run.py reports `gate_action` and `gate_id`, and
    # SKILL.md was still branching on the answer STRING — the same defect as the checkpoint one, one
    # field along: the script computes the transition and the skill re-derives it. They disagree the
    # moment an answer is gate-specific, and "Seed" is exactly that (rebuild-and-re-ask on
    # stage_choice, meaningless elsewhere). The five actions are tabulated because a reader who does
    # not know `continue_if_rebuilt` exists will treat "proceed anyway" as terminal, which is the
    # defect this replaced: it authorised a report whose profile may never have been downgraded.
    # deck-review 95,586 -> 97,048 (+1,462): the gate_action table at Step 1 said one thing and the
    # OPERATIVE section a few hundred lines later still said "branch on that answer" — two
    # instructions, and the second is the one being read at the point of use. The operative branch
    # now leads with the five actions, `stop` first. It also fixes a routing hole: picking Series B
    # or Growth at `stage_choice` was re-confirmed through `stage_confirmation`, which never offers
    # `Stop review`, so a founder was told their deck is out of scope by a question giving them no
    # way to decline. Those two stages now re-emit `out_of_scope_choice`.
    # deck-review 97,048 -> 97,371 (+323): the canonical options are enforced on the FILE and the
    # founder reads the PAYLOAD, which SKILL.md retyped by hand — so a record containing "Stop
    # review" could sit beside a displayed choice that omitted it, and validation would guarantee
    # what was recorded rather than what was asked. `emit` now returns the payload and the skill
    # presents it verbatim.
    # deck-review 97,371 -> 97,920 (+549): `emit` now requires `--stage`, recording which stage the
    # gate asked about. Nothing tied a gate to the profile it confirmed, so confirming Seed,
    # rebuilding the same-run profile to Series A, and composing against the original gate produced
    # a clean report graded as Series A. The prose says to RE-EMIT after a rebuild rather than reuse
    # the record, because that is the failure the binding turns into a refusal.
    # deck-review 97,920 -> 98,706 (+786): the round-eight binding was an EQUALITY (asked stage ==
    # composed stage), which made the documented out-of-scope flow impossible — that gate asks about
    # growth and "Proceed anyway" rebuilds to series_a. It is now stated as a TRANSITION, and the
    # prose says which gate may be emitted for which stage, because `stage_confirmation` about an
    # out-of-scope deck offers the founder no way to decline. The `needs_input` note is here because
    # a hand-written summary let a founder read "Detected stage: Seed" over a record authorizing
    # Series A.
    # deck-review 98,706 -> 99,503 (+797): the option ORDER on the out-of-scope gate. `gate_state.py`
    # enforces the exact list in the exact order on the FILE, and a live run then showed a founder that
    # list REVERSED — `Proceed anyway (best-effort)` in the default slot, `Stop review` last. Every
    # artifact-based check passed, because the artifact was correct; the only wrong thing was what a
    # person saw. The existing prose anticipated a SHORTER list ("including one with no way to decline")
    # and said nothing about order, which is why it did not bind. The parent-side instruction now names
    # the order and forbids adding a recommendation, and the rationale sits with the option list rather
    # than in prose a copier skips.
    # deck-review: shrink pass 2026-08-18, 99_757 -> 97_202 (-2_555 B). The file sat EXACTLY
    # at its ceiling, so every edit tripped this ratchet. Cut in order of value: the narration
    # guidance and two of its restatements QUOTED THE LEAK PHRASES verbatim immediately before the
    # densest plumbing sections — under the recorded echo hypothesis (a model reaches for the
    # vocabulary it is currently reading) that primed the failure it forbade, so cutting bytes and
    # improving compliance pointed the same way. Then rationale essays whose operative kernel is one
    # sentence, bash comments compressed to their load-bearing clause, and a 4th restatement of
    # append-only two lines after the 3rd. Kept: every anchor string, both "Say exactly" markers and
    # the supplied-line table, all 7 dispatch templates, the fleet-identical delivery block, the
    # execution checkpoint, and every named observed-failure move. Spent 267 B on a missing failure
    # branch for Step 3.6, whose artifact the whole numeric chain consumes unconditionally.
    # deck-review: Batch 2 founder-facing corrections, 97_202 -> 99_317. Six defects measured on a
    # live run, each now pinned by a contract test in test_deck_review_skill_contract.py: A2a the
    # SLIDE_REVIEWS prompt never said how to ATTRIBUTE a principle, so the model cited the reference
    # filename it was handed; A2b the token "must be removed" with no HOW, which produced a sed edit
    # that cleaned report.md and left report.json; A4 a DESCRIBED limit ("at most one plain
    # sentence") instead of a supplied one; A5 three optional string-only fields that reject null and
    # accept omission, where only claimed_stage said so; A6 no canonical inlined text for an
    # image-rendered deck, so the two halves of one corroboration could read different
    # transcriptions; A7 a missing pointer to the schema that already answers `suppressed`.
    # Net vs the pre-shrink 99_757: -440 B — Batch 1.5 + Batch 2 together are still a cut.
    # A9, all six: +1 line each — `insert_coaching.py --report-json`. Without it report.json keeps
    # the pre-coaching text and a raw uuid insertion marker (measured 5,592 B adrift on a live
    # run). Syncing rather than dropping the key, because ~200 test sites across the fleet read
    # report_markdown out of the composed JSON to inspect report content.
    # deck-review +504 B (N3a): the RELATION_PROPOSAL prompt now names the market-slide case — two
    # dated magnitudes plus a stated growth multiple. Measured: a deck stated all four figures, the
    # ledger extracted all four, and ZERO relations were proposed, because none of the prompt's four
    # shapes reads as that. An ordinary ratio with an expected_id, expressible with no new capability.
    # deck-review +410 B: the gate-emit step now states that `context_summary` may not name another
    # stage (including quoting the deck's claim) and that the producer renders the deck/review
    # disagreement itself from `deck_inventory.claimed_stage`. Without it the author has no way to know
    # why an accurate summary is refused, and the most decision-relevant sentence at that gate gets
    # dropped rather than delegated. The optional-field paragraph also had to change with the
    # producer: it told the author `null` is REJECTED, which stopped being true once
    # deck_inventory.py normalised null to absence, and a SKILL.md that contradicts its producer
    # is worse than either state. +652 B more: auto-satisfy's conditions listed a two-way match
    # (what the founder said, what you detected) and left the deck's own claim out, so a live run
    # self-answered a gate on a deck whose title slide contradicted the stage being graded and the
    # founder was never told. The producer refuses that source now; the condition has to be stated
    # where the branch is, or the refusal reads as a bug.
    # All three raised for the cowork-harness 2.4.0 cwd fix, which turned three cwd-relative shell
    # paths from benign into silently wrong. 2.4.0 moves the workspace shell's cwd to the BARE SESSION
    # ROOT; `./artifacts` used to resolve to the canonical root and now lands in `/sessions/<id>/`,
    # outside `mnt/`, where nothing is delivered and nothing reports it. cp/fmr: the self-heal branch
    # said `mkdir -p ./artifacts` (market-sizing and ic-sim already said `"$ARTIFACTS_ROOT"` — this was
    # drift, fixed in 2 of 6). deck-review: the uploads listing was `... || ls -la ./mnt/uploads`, whose
    # MEANING moved with the cwd (it pointed at a path that never existed before 2.4.0 and at the real
    # mount after), so it now calls `resolve_artifacts_root.py --uploads` — one opaque command, per that
    # module's own rationale. Each sentence was tightened before raising, and deck-review NET SHRANK
    # from its first draft by rewriting a captured-variable form that violated
    # test_no_shell_variable_capture_of_python_output. Analysis:
    # docs/internal/2026-08-27-cowork-harness-2.4.0-adoption-plan.md SS3.2.
    # +exit-8 Context A bullet and +Context B "any other exit" catch-all, all six (2026-08-31).
    # ONE shared reason for six near-identical raises, referenced rather than repeated:
    # `check_handoff.py` defines seven typed exits; the Context A gate table documented five and
    # omitted exit 8 -- the branch the code was written for, since Context A is where OUTPUT_PATH is
    # built from $HANDOFF_AGENT and where the doubled-prefix condition occurs. Exit 8 therefore fell
    # to "Any other exit -> STOP", halting a run over a condition the gate's own diagnostic says is
    # recoverable by a prefix correction. Context B separately had no catch-all at all, so an exit 4
    # (reachable there on an IO fault) or an uncaught decode error had no documented branch.
    # Guarded by test_context_a_gate_table_documents_exit_8 in test_handoff_contract_ratchet.py.
    # SHRANK: the unscoped "canonical artifacts are producer-script-only" justification was
    # rescoped to "you never write a canonical artifact" across all 22 sites (W2 audit). The
    # instruction was always correct; the REASON given for it asserted the general claim P0-2
    # established is false — the main thread writes several canonical artifacts by heredoc.
    # deck-review raised 102,180 -> 102,786 (+606 B) for the downgrade-stanza step: the
    # interpretation dispatch used to ask the main thread to hand-transcribe each
    # contradiction's operator, operand ids and expected_id, and a slip there fails the
    # whole step. The engine prints them instead.
    # deck-review raised 102,786 -> 103,003 (+217 B) to state the third design-gate axis on
    # both prose sites: a slide the ingesting agent never rendered gates the visual criteria
    # whatever input_quality claims.
    # deck-review raised 103,003 -> 103,337 (+334 B) for verified_by on the four measurement
    # criteria: the status enum let an agent that could not observe a property score it
    # anyway, and the artifact could not tell a guess from a measurement.
    # deck-review raised 104,243 -> 104,251 (+8 B): the stanza step was missing its `python3`
    # prefix, and the scripts are committed non-executable -- so the command exited 126 and
    # the feature was inert.
    # deck-review raised 103,337 -> 104,243 (+906 B) for the at_most/per relation fields and
    # the three sites the new verdict was invisible to -- one of which would have told a
    # founder their figures line up while the report said the plan exceeds a stated limit.
    # deck-review raised 104,251 -> 104,833 (+582 B) so a deck given as a link is in scope and has
    # a branch. `when_to_use` admitted only an attached FILE, so the skill did not trigger on a link
    # at all; the branch is conditioned on what a single fetch RETURNS rather than on the input
    # being a link, because refusing every link would refuse the public ones that work.
    # deck-review 102,180 -> 102,508 (+328): the LEDGER_EXTRACTION template now says a count
    # the slide spells out in words IS a figure, recorded with the words as printed. Measured on a
    # real deck across two runs: "three production R&D organizations", "Six patent applications",
    # "Fifteen years" and "Five people" were refused by ledger.py on the first ("contains no
    # number", a repair dispatch) and silently omitted on the second, once the extractor had
    # learned to avoid the refusal. ledger.py now reads spelled-out cardinals through
    # `numeral_form`, so the instruction and the validator agree; without the sentence the model
    # keeps choosing between the two failures, and neither records what the deck says.
    # deck-review 102,508 -> 103,781 (+1,273): the PowerPoint conversion block tries two converters
    # instead of one — LibreOffice (any OS, now including the default Windows install path), then
    # Keynote on macOS — each only where it is installed, and falls through to the text-only path
    # otherwise. Claude Code hosts are laptops, and a laptop without LibreOffice is the common case;
    # measured on a Mac, the whole design category was gated to not_applicable with Keynote sitting
    # in /Applications. The Keynote path is an inline AppleScript, which is where the bytes are: a
    # converter the skill only names, without the invocation, is one the model improvises — and the
    # improvised Keynote script is what failed on the run that measured this. A PowerPoint-over-COM
    # branch for Windows was written and then dropped before merge: nothing in CI can exercise a
    # Windows host, so it would have shipped unvouched-for. It is a follow-up once it can be measured.
    # deck-review raised to 106,434 on merging the spelled-out-counts work: both sides added
    # prose to the same body, so the merged size is larger than either branch anticipated and
    # neither branch's ceiling is correct for it. The value is the measured merged size, not a
    # carried-over one.
    # deck-review raised 106,434 -> 106,663 (+229 B): the Keynote converter now quits on both
    # exits. Its own comment recorded that a Keynote left running headless answers every
    # document command with -1708 and only quitting cures it -- measured on a real run -- and
    # the block then exited without quitting, so the first conversion in a session set up the
    # exact failure the second would hit.
    # +129 B (fleet, one shared edit): the delivery block's hand-over sentence said the link form in
    # Cowork is `computer://` + the absolute path. MEASURED in-app on the remote lane (2026-09-21/22,
    # the default lane for new sessions and the one the market-sizing bug report came from): no link
    # form opens a file there -- computer:// is plain text and a bare path becomes a broken claude.ai
    # URL; the presented card is the delivery. The sentence now says: a link where this surface
    # renders one that opens (on a /sessions tree, computer:// + the path), otherwise the label with
    # the path stated beside it. Same edit in all six; test_delivery_block_is_identical_fleet_wide
    # is the proof.
    # +1,275 B (fleet, one shared edit): the Step 0 preflight and its stop. MEASURED 2026-09-22 on
    # claude.ai, which mounts skills FLAT at /mnt/skills/plugins/<plugin>:<skill>/ and serves no
    # plugin: the shared scripts were unreachable and no sub-agent could be dispatched, and
    # market-sizing ran anyway -- hand-writing every hand-off file, grading its own checklist, and
    # shipping a report with no adversarial review and no gates. One line detects it; the skill now
    # stops and says so instead of producing something that reads as checked.
    # +1,485 B (108_067 -> 109_552): the file tools refuse a relative path, so Step 0 gains the proof
    # of the file-tool path of outputs (probe + --set-host-outputs-dir), the hand-off protocol gains
    # the `write_refused` branch (both contexts), and the degrade rule tells the founder instead of
    # noting it. The procedure itself lives once in skill-execution-model.md.
    # 109,512 -> 111,001 on 2026-10-02: Step 0 tells whether this skill's text arrived with its plugin folder
    # filled in and, only when it did not (a skill started as the first message of a new conversation), finds
    # the plugin by a filesystem search and prints READ_ROOT= for the Reads and sub-agent prompts. The
    # SLIDE_REVIEWS and CHECKLIST prompts gain the sub-agent fallback for a refused reference path.
    # 111,001 -> 110,906 on 2026-10-03: Step 0's preflight comment is two lines, the plugin-paths paragraph is
    # shorter and plainer, a manifest-less plugin copy is kept by the search, and the block says to run it
    # with the token as shown and that PLUGIN_ROOT is for shell commands only. Two reference Read
    # directives name their file under the plugin token.
    # 110,906 -> 110,969 (+63 B) on 2026-10-03, the same +63 B in all six: Step 0's PLUGIN_ROOT comment names it
    # the shell's path and states the one exception, a printed READ_ROOT= used in Reads and prompts.
    # 110,969 -> 111,125 on 2026-10-03: the stage gate's execution note says the skill runs inline and asks
    # the founder itself, and that after the answer is written Step 1's setup_run.py is re-run to resume.
    # 111,125 -> 111,228 on 2026-10-03: after emitting the stage gate the skill asks the founder with
    # AskUserQuestion from the printed block, in order, instead of returning JSON to a parent agent (the
    # shape example drops the two parent-only keys); the resume re-runs setup_run.py with the RUN_ID
    # literal printed earlier and points at Step 0, where that call lives.
    # 111,228 -> 111,455 on 2026-10-04: "never delete under outputs" is this skill's rule, not a platform
    # limit (newer hosts allow deletes). Step 0's append-only paragraph, the hand-off comment and the retry
    # line say so instead of claiming the host refuses. deck-review also names `setup_run.py --clean` as the
    # one script that removes its own earlier-run checkpoints.
    # 111,455 -> 111,766 on 2026-10-04: Steps 3.6, 3.7 and 3.9 name `subagent_type: "founder-skills:deck-review"` (a
    # type-less dispatch falls back to the wildcard general-purpose agent).
    # 111,766 -> 111,765 on 2026-10-04: Step 0's append-only exception says scripts remove only their own
    # files (`setup_run.py --clean` is one; a failed atomic write removes its temp file too).
    # 111,765 -> 111,873 (+108 B) on 2026-10-05: Step 0 no longer defines a reference
    # folder for the shell (REFS=/SHARED_REFS=, a VM path the Read tool is refused) and names the folder
    # for Reads in prose, as loaded; every read directive names its file under the plugin token, never a
    # bare relative references/ path or a printed shell value.
    # 111,873 -> 112,456 (+583 B) on 2026-10-05: a PowerPoint deck converts into the run's hand-off folder,
    # not $STAGING_DIR (refused to the Read tool on a local session), and the block prints the Read tool's
    # path to the PDF. A deck the Read tool cannot reach in place is copied there; the append-only
    # paragraph names the exception.
    # 112,456 -> 112,469 (+13 B) on 2026-10-05: the read-directive clauses say "never the shell's path to the
    # plugin folder" instead of "never a path the shell printed", which also covered the hand-off paths the
    # shell prints for Reads.
    # 112,469 -> 113,327 on 2026-10-05: the conversion block makes its own LibreOffice profile folder (a later
    # block's shell has no setup variables), Keynote exports to a temp folder, a failed copy prints copy-failed
    # with its own branch, and Step 1 skims a PowerPoint deck through the text reader and a PDF by its file-tool path.
    # 113,159 -> 113,346 (+187 B) on 2026-10-05: the resolver's exit 3 (no uploads
    # folder found) no longer reads as "no session tree": on the cloud lane the per-session uploads folder
    # exists only once something is attached, so the reason names both causes (nothing attached, or a host
    # that keeps uploads elsewhere) and asks for a path when documents were attached.
    # The deck search gains the exit-3 branch it lacked: it listed a folder the resolver never printed.
    # 113,346 -> 113,479 on 2026-10-05: the description says the skill starts on its own only on a clear request,
    # and that a passing question gets a short answer and an offer naming how long the run takes.
    # The in-skill offer names the run's duration in place of 'several minutes'.
    # 113,479 -> 113,543 (+64 B) on 2026-10-05: on exit 3 the deck search uses a deck path the request already
    # names before asking for one.
    # 113,543 -> 113,571 (+28 B) on 2026-10-05: the feedback lines tell the founder to type
    # `/founder-skills:feedback`; it is a user-started skill now, which the model cannot start.
    # 113,571 -> 113,697 (+126 B) on 2026-10-05: the Step 0 STAGING_DIR block says
    # scratch output (a redirect or a temp file) goes in $STAGING_DIR, never a fixed /tmp/<name>, because
    # /tmp is shared across sessions.
    # 113,697 -> 113,688 (-9 B) on 2026-10-07: gates wired. The catalog sections (Skill Metadata, Available
    # Scripts, Available References) and the RUN_ID mint line are out; Step 0 starts the run's record, the slug
    # block binds it, Steps 1-2 open each question before asking and record it with the printed command, the
    # stage gate takes an answer the request carried, compose's exit 10 is a question, Step 8 lists the page
    # and Step 9 closes the page list. Restatements trimmed to fit (the AskUserQuestion-fallback aside, the
    # coaching heredoc's parenthetical, Step 9's now-untrue non-zero-exit clause); after review, the not-found
    # and decline exits of Step 1 and the slug block are named.
    # 113,688 -> 113,613 (-75 B) on 2026-10-07: Step 2 and the gate step document `prior_rounds` (a round
    # already closed is the producer's line, a round raised now is `claimed_stage`); the `reuse_checkpoints`
    # paragraph no longer names gate_state.json, which `--clean` can now remove while keeping this run's
    # checkpoints; two justification/history sentences removed to pay for it.
    # 113,613 -> 113,610 (-3), LOWERED, commit 10 (O3): the compose step says to read compose_result.json on a
    # non-zero exit, paid for in the same step; the heredoc warning shortened, its reason kept.
    # 113,605 -> 113,597 (-8 B), LOWERED, commit 8 (N7): Step 1's geography line no longer says geography
    # selects the guidance the whole deck review is graded against (no deck-review script reads geography); it
    # says it is saved for later reviews and a financial model review grades against it.
    # 113,597 -> 114,117 (+520 B): Step 3.7's RELATION_PROPOSAL template names the three new operators
    # (`runway` with its burn-plan `schedule`/`start`, `inverse_change` with `direction` and the closed list
    # of reciprocal pairs the engine accepts, `implied_base` with no `expected_id`), appended after the
    # operator line so the dated-magnitudes window is untouched. The "Measured: ..." history sentence in
    # that bullet was removed to pay for part of it; the measurement lives in its contract test.
    # 114,117 -> 114,252 (+135 B): a `rounding_gap` (a total its parts reach only through their own
    # rounding) reaches the founder, so Step 3.9 runs on one too and the INTERPRETATION template says the
    # same two withdrawal grounds apply to it; without that the verdict has no review path.
    # 114,252 -> 114,249 (-3 B), LOWERED: the reciprocal pairs Step 3.7 names shrink to the ones that are
    # reciprocal by definition (time/speed and latency/throughput reported disagreements that were not).
    # 114,249 -> 114,623 (+374 B): `numbers_consistent` is scored from the arithmetic. Step 5's checklist.py
    # command carries `--reconciliation` plus one sentence that a what-if rerun omits it; Step 7's coaching
    # template names `numeric_findings` and says an empty list is not an all-clear.
    "deck-review": 114_623,
    # competitive-positioning: + the merge step's "positioning_scores.json is aggregates only" claim
    # corrected. It is false — score_positioning.py passes points[] straight through — and that false
    # premise is plausibly why the merge was never cross-checked. Compose now checks it.
    # competitive-positioning SHRANK: Gate 3's four threshold bullets are deleted. They restated
    # arithmetic gate3_triggers.py owns, under a sentence saying "Do NOT re-derive it here", and the
    # copy had already drifted — SKILL.md said the trade-off trigger's strong side was top-2 where
    # the script had corrected it to top-tercile, its docstring recording top-2 as WRONG (it excludes
    # 3rd of 11, the exact shape the trigger exists for). Replaced by a relay instruction: present a
    # `provisional` trigger as a soft signal. Also NARR_03, which changed a graded score.
    # cp raised for the CHECKLIST dispatch template's evidence-wording rule. A live run put artifact
    # filenames in 13 items' evidence with the rule present only in the agent body; the dispatch
    # template is the surface that measurably changed behaviour in the sibling skill.
    # competitive-positioning +656 B: the POSITIONING_SCORING dispatch now instructs axis `polarity`.
    # This is the half of the rank-polarity fix that makes it real — `score_positioning.py` can honour
    # the field, but nothing produced it, so a script-only fix would have been inert on every live run
    # and its test could not have failed. The prose names the concrete failure (told a founder they
    # ranked last on price while second-cheapest) because "set the polarity" alone did not tell the
    # model when it matters.
    # competitive-positioning +583 B: the CHECKLIST dispatch now asks the sub-agent to echo each
    # criterion label verbatim. Measured on two archived runs, evidence landed on the wrong criterion
    # id — "Do-nothing / status quo included" carrying evidence about how many direct competitors were
    # named — and nothing could catch it, because the producer joins canonical label to sub-agent
    # evidence by id and each half looked correct alone. The echo is the second signal that makes the
    # mismatch detectable without judging the evidence text.
    # competitive-positioning +811 B: the MOAT_SCORING dispatch now offers the custom-moat path and
    # names distribution as the case the canonical six cannot express. The path already existed in
    # moat-definitions.md and was accepted by score_moats.py, but the dispatch never mentioned it —
    # measured 0 custom moats on 4 of 4 runs, while one of those runs scored a channel reaching ~80%
    # of its target market as `network_effects: absent`. Correct reasoning, lost finding.
    # competitive-positioning +374 B: the merge-back step now carries axis `polarity` across into
    # positioning.json alongside scoring_basis. The founder-coordinate-override path re-pipes
    # positioning.json through score_positioning.py, so a dropped polarity silently reverts a cost
    # axis to higher-is-better — re-inverting the rank on exactly the runs where the founder engaged
    # with the map. scoring_basis already had this carve-out for the identical reason; polarity did not.
    # A9, all six: +1 line each — `insert_coaching.py --report-json`. Without it report.json keeps
    # the pre-coaching text and a raw uuid insertion marker (measured 5,592 B adrift on a live
    # run). Syncing rather than dropping the key, because ~200 test sites across the fleet read
    # report_markdown out of the composed JSON to inspect report content.
    # competitive-positioning -36 B: Gate 1 now reads `summary.challenge_slugs` instead of re-deriving
    # it from `flagged_slugs`, and renders `possible_overlap_with` on recall-gap lines. Net shrink --
    # deleting a prose re-derivation paid for both.
    # All three raised for the cowork-harness 2.4.0 cwd fix, which turned three cwd-relative shell
    # paths from benign into silently wrong. 2.4.0 moves the workspace shell's cwd to the BARE SESSION
    # ROOT; `./artifacts` used to resolve to the canonical root and now lands in `/sessions/<id>/`,
    # outside `mnt/`, where nothing is delivered and nothing reports it. cp/fmr: the self-heal branch
    # said `mkdir -p ./artifacts` (market-sizing and ic-sim already said `"$ARTIFACTS_ROOT"` — this was
    # drift, fixed in 2 of 6). deck-review: the uploads listing was `... || ls -la ./mnt/uploads`, whose
    # MEANING moved with the cwd (it pointed at a path that never existed before 2.4.0 and at the real
    # mount after), so it now calls `resolve_artifacts_root.py --uploads` — one opaque command, per that
    # module's own rationale. Each sentence was tightened before raising, and deck-review NET SHRANK
    # from its first draft by rewriting a captured-variable form that violated
    # test_no_shell_variable_capture_of_python_output. Analysis:
    # docs/internal/2026-08-27-cowork-harness-2.4.0-adoption-plan.md SS3.2.
    # +exit-8 Context A bullet and +Context B "any other exit" catch-all, all six (2026-08-31).
    # ONE shared reason for six near-identical raises, referenced rather than repeated:
    # `check_handoff.py` defines seven typed exits; the Context A gate table documented five and
    # omitted exit 8 -- the branch the code was written for, since Context A is where OUTPUT_PATH is
    # built from $HANDOFF_AGENT and where the doubled-prefix condition occurs. Exit 8 therefore fell
    # to "Any other exit -> STOP", halting a run over a condition the gate's own diagnostic says is
    # recoverable by a prefix correction. Context B separately had no catch-all at all, so an exit 4
    # (reachable there on an IO fault) or an uncaught decode error had no documented branch.
    # Guarded by test_context_a_gate_table_documents_exit_8 in test_handoff_contract_ratchet.py.
    # +persist_agent_artifact.py pipe on the three main-thread-authored artifacts (W6). They were
    # the exact complement of compose_report.py's EXPECTED_PRODUCERS map, so a high-severity
    # provenance gate existed and was structurally blind to them.
    # SHRANK: the unscoped "canonical artifacts are producer-script-only" justification was
    # rescoped to "you never write a canonical artifact" across all 22 sites (W2 audit). The
    # instruction was always correct; the REASON given for it asserted the general claim P0-2
    # established is false — the main thread writes several canonical artifacts by heredoc.
    # Net of the 2026-08-31 adversarial pass: cap-table +uncovered_parts stringify guidance;
    # competitive-positioning -1.4 KB from de-duplicating the "Preserve _produced_by" note,
    # which had been pasted verbatim four times (twice four lines apart).
    # +129 B (fleet, one shared edit): the delivery block's hand-over sentence said the link form in
    # Cowork is `computer://` + the absolute path. MEASURED in-app on the remote lane (2026-09-21/22,
    # the default lane for new sessions and the one the market-sizing bug report came from): no link
    # form opens a file there -- computer:// is plain text and a bare path becomes a broken claude.ai
    # URL; the presented card is the delivery. The sentence now says: a link where this surface
    # renders one that opens (on a /sessions tree, computer:// + the path), otherwise the label with
    # the path stated beside it. Same edit in all six; test_delivery_block_is_identical_fleet_wide
    # is the proof.
    # +1,275 B (fleet, one shared edit): the Step 0 preflight and its stop. MEASURED 2026-09-22 on
    # claude.ai, which mounts skills FLAT at /mnt/skills/plugins/<plugin>:<skill>/ and serves no
    # plugin: the shared scripts were unreachable and no sub-agent could be dispatched, and
    # market-sizing ran anyway -- hand-writing every hand-off file, grading its own checklist, and
    # shipping a report with no adversarial review and no gates. One line detects it; the skill now
    # stops and says so instead of producing something that reads as checked.
    # +14 B (competitive-positioning only): Gate 3 gained a fifth trigger, no_edge (a competitor
    # right next to the startup and no clear lead on either axis, the crowded middle no rank trigger
    # sees), so the Gate 3 trigger list names "no clear edge" and the script summary no longer says
    # "four" triggers.
    # +1,518 B (127_427 -> 128_945): the file tools refuse a relative path, so Step 0 gains the proof
    # of the file-tool path of outputs (probe + --set-host-outputs-dir), the hand-off protocol gains
    # the `write_refused` branch (both contexts), and the degrade rule tells the founder instead of
    # noting it. The procedure itself lives once in skill-execution-model.md.
    # +9 B (competitive-positioning): the POSITIONING_SCORING verdict list names `unproven`, the
    # fourth verdict every surface renders (a claim the research could not settle either way).
    # -8,874 B (competitive-positioning): the MOAT_SCORING, POSITIONING_SCORING and CHECKLIST dispatch
    # templates moved into cp_dispatch_prompt.py, which prints them from identifiers; SKILL.md keeps
    # the command and the "send it unchanged" rule. (The +9 B for `unproven` above is kept inside it.)
    # +1,203 B (competitive-positioning): Step 4b, the STARTUP_RESEARCH dispatch that looks up the
    # startup's own public record (legal name, patents and their legal events), dispatched beside
    # LANDSCAPE_RESEARCH and piped through validate_startup_research.py.
    # +431 B (competitive-positioning): plan-stage scoring (D1). Step 2 records product_availability
    # with its quote, Gate 2 states that a pre-product startup is mapped where its plan puts it
    # (replacing the "score what's live today" default), and the scorer pipe reads the profile.
    # +640 B (competitive-positioning): Step 8's hand-over is printed by cp_closing_message.py (the
    # links, the report's verdict paragraph, the offer) and sent unchanged, as market-sizing's is.
    # +2,967 B (competitive-positioning): Step 6.5, the outside review -- its own agent, the rule that it
    # runs (compose refuses otherwise) with the four recorded skip reasons, the uploads mirror, the
    # printed prompt, the producer pipe, the skip command, "a review is final"; and Step 7's line on
    # the review's four deliver-only disclosures. +184 B more: Step 7 says compose's refusal for a run
    # with neither a review nor a recorded skip is not a stop -- do Step 6.5 and re-run -- since its
    # general "exits non-zero: stop" rule would otherwise halt the run the refusal exists to redirect.
    # +384 B (competitive-positioning): Step 7 says where a leaked file name is removed -- only in
    # positioning.json, the one file it names that the outside review does not fingerprint -- and never in
    # a file the review read (the company profile, the scores, whose evidence the scorers now reword);
    # both runs of the first live check hand-edited a scored artifact after the review.
    # +146 B (competitive-positioning): Step 3 names `candidate_axes` and Step 5 says polarity stays
    # nested as x_axis.polarity / y_axis.polarity -- a live run guessed the first and misplaced the second.
    # +104 B (competitive-positioning): Step 8's closer names both HTML pages -- the maps and the
    # interactive explorer -- where one "the interactive version" line could hand over only one of them.
    # 126_099 -> 126_169 (+70 B): the Step 0 search names its folder; see market-sizing above.
    # 126,169 -> 127,330 on 2026-10-02: Step 0 tells whether this skill's text arrived with its plugin folder
    # filled in and, only when it did not (a skill started as the first message of a new conversation), finds
    # the plugin by a filesystem search and prints READ_ROOT= for the Reads and sub-agent prompts.
    # 127,330 -> 126,862 on 2026-10-03: Step 0's preflight comment is two lines, the plugin-paths paragraph is
    # shorter and plainer, a manifest-less plugin copy is kept by the search, and the block says to run it
    # with the token as shown and that PLUGIN_ROOT is for shell commands only. The paragraph's illustrative
    # example sentence is gone.
    # 126,862 -> 126,630 on 2026-10-03: the five prompt-generator command lines no longer pass the plugin
    # folder; see market-sizing above.
    # 126,630 -> 126,693 (+63 B) on 2026-10-03, the same +63 B in all six: Step 0's PLUGIN_ROOT comment names it
    # the shell's path and states the one exception, a printed READ_ROOT= used in Reads and prompts.
    # 126,693 -> 126,824 on 2026-10-04: "never delete under outputs" is this skill's rule, not a platform
    # limit (newer hosts allow deletes). Step 0's append-only paragraph, the hand-off comment and the retry
    # line say so instead of claiming the host refuses.
    # 126,824 -> 127,426 on 2026-10-04: The setup block ends by printing RUN_ID, STAGING_DIR and HANDOFF_DIR; the quick-
    # check producer reads a fill-in heredoc instead of an undefined $QUICK_JSON; Step 6 prints the input mode back from
    # product_profile.json instead of reading a variable set in an earlier shell; the overwrite note names the no-delete
    # rule, not a host refusal.
    # 127,426 -> 127,516 on 2026-10-04: Step 3.6's recall dispatch names `subagent_type:
    # "founder-skills:competitive-positioning"` (a type-less dispatch falls back to the wildcard general-purpose
    # agent); the sentence a removed reminder had cut in half is whole again.
    # 127,516 -> 127,748 on 2026-10-04: a producer rejection of a generated prompt's hand-off is sent back
    # through its generator (`--correction producer-rejected --detail-file`); see market-sizing above.
    # 127,748 -> 127,766 on 2026-10-04: the rejection file moves under the hand-off dir; see market-sizing.
    # 127,766 -> 127,995 (+229 B) on 2026-10-05: Step 0 no longer defines a reference
    # folder for the shell (REFS=/SHARED_REFS=, a VM path the Read tool is refused) and names the folder
    # for Reads in prose, as loaded; every read directive names its file under the plugin token, never a
    # bare relative references/ path or a printed shell value.
    # 127,995 -> 128,008 (+13 B) on 2026-10-05: the read-directive clauses say "never the shell's path to the
    # plugin folder" instead of "never a path the shell printed", which also covered the hand-off paths the
    # shell prints for Reads.
    # 127,826 -> 127,949 (+123 B) on 2026-10-05: the resolver's exit 3 (no uploads
    # folder found) no longer reads as "no session tree": on the cloud lane the per-session uploads folder
    # exists only once something is attached, so the reason names both causes (nothing attached, or a host
    # that keeps uploads elsewhere) and asks for a path when documents were attached.
    # 127,949 -> 127,927 on 2026-10-05: the description says the skill starts on its own only on a clear request,
    # and that a passing question gets a short answer and an offer naming how long the run takes.
    # 127,927 -> 128,004 (+77 B) on 2026-10-05: on exit 3 the review step copies the founder documents
    # read earlier, from the path they were read at, into the hand-off docs folder, and asks for a path only
    # with none, so the review still sees them and an unattended host does not stall.
    # 128,004 -> 128,032 (+28 B) on 2026-10-05: the feedback lines tell the founder to type
    # `/founder-skills:feedback`; it is a user-started skill now, which the model cannot start.
    # 128,032 -> 129,648 (+1,616 B) on 2026-10-05: the Step 0 STAGING_DIR block says
    # scratch output (a redirect or a temp file) goes in $STAGING_DIR, never a fixed /tmp/<name>, because
    # /tmp is shared across sessions (+126 B). Each of the five generator calls
    # says to run it in a shell call of its own (see market-sizing), which splits moat/positioning into
    # two blocks and the red-team generator out of the uploads-mirror block. A declined recall candidate
    # is recorded through record_deferred_recall.py instead of a hand edit of landscape_draft.json,
    # which would lose its producer stamp. Step 8 sends the files first and runs the closer last, its
    # output the whole final message (see market-sizing); the trailing "Present the file paths"
    # instruction after the closer is gone and COMPANY_NAME is defined beside the copies that use it.
    # Main-Thread Return names the printed hand-over as the founder's message and keeps the headline
    # fields for the model's own checks, no longer offering the HTML paths beside it.
    # 129,648 -> 129,608 (-40), LOWERED, commit 8 (gates): the three catalog sections out (one shared-references
    # line kept); Step 0 starts the run's record and the slug block binds it; every question is opened, asked
    # and recorded; Gate 1 asks the question its open prints and the deferral is a script call; the scoring
    # basis is the recorded one (the parked follow-up paragraph out); exit-10 carve-outs, a re-compose after
    # delivery as a new revision, the pages' run id and the deliverables close; two restatements trimmed.
    # 129,608 -> 129,580: after a re-compose, fresh coaching under the revision's own hand-off file and the way
    # back when that compose is refused; the recall-dispatch rationale and the version-match sentence shortened.
    # 129,580 -> 129,577 (-3), LOWERED, commit 10 (O3): the compose step says to read compose_result.json on a
    # non-zero exit, paid for in the same step; the heredoc warning shortened, its reason kept.
    # -1 B, LOWERED, commit 13: a derived stage takes its option id and no value; the sentence is shortened to pay.
    "competitive-positioning": 129_568,
    # cap-table, the largest raise (+2,383 B) and the one with the most founder-visible payoff:
    #   * Main-Thread Return named THREE of the four files Step 12 copies; a live run delivered exactly
    #     three and dropped `{Company}_Cap_Table.html`. All four are now named explicitly.
    #   * Step 12 had NO mode branches, so fast-assess / concise / extraction-only jumped into a copy
    #     block naming files they never produce. Each lightweight route now has its own branch.
    #   * The extraction-only fork had no delivery step at all AND writes to
    #     `$ARTIFACTS_ROOT/cap-table-$SLUG-extraction`, which Step 12's `$REVIEW_DIR` copies cannot
    #     reach — its sole deliverable could not be handed over.
    # cap-table +13 B on top of that: the rule pack's move to skills/cap-table/data/ (out of the
    # critique corpus) retargeted its two SKILL.md location mentions (`data/`, `../data/`). The OTHER
    # ceiling here — the 524,288 B critique evidence corpus — went from 98% to ~71% with that move
    # (the post-move value, not the current one — see test_cap_table_corpus_headroom_is_tracked
    # below, which carries the live figure); the reclaimed margin is pinned there.
    # cap-table +720 B: fixed two residual defects in its bespoke fresh-shell note. (1) "Writing the
    # assignments again at the top of a block is fine too" was wrong for the RUN_ID mint line
    # specifically — qualified to say re-deriving pure path vars is fine, re-running the RUN_ID mint is
    # not. (2) The note told the model to paste RUN_ID's printed literal, but Step 0 never echoed
    # RUN_ID (only ARTIFACTS_ROOT and HANDOFF_AGENT were printed) — added an echo so the remedy is
    # satisfiable.
    # cap-table +96 B: the script catalog claimed extract_cap_table.py emits cap_state.json. It does
    # not — that is cap_state.py's output at Step 4 — and the same file said so correctly two lines
    # earlier, so a model reading the catalog was told to expect an artifact that never appears.
    # A9, all six: +1 line each — `insert_coaching.py --report-json`. Without it report.json keeps
    # the pre-coaching text and a raw uuid insertion marker (measured 5,592 B adrift on a live
    # run). Syncing rather than dropping the key, because ~200 test sites across the fleet read
    # report_markdown out of the composed JSON to inspect report content.
    # +exit-8 Context A bullet and +Context B "any other exit" catch-all, all six (2026-08-31).
    # ONE shared reason for six near-identical raises, referenced rather than repeated:
    # `check_handoff.py` defines seven typed exits; the Context A gate table documented five and
    # omitted exit 8 -- the branch the code was written for, since Context A is where OUTPUT_PATH is
    # built from $HANDOFF_AGENT and where the doubled-prefix condition occurs. Exit 8 therefore fell
    # to "Any other exit -> STOP", halting a run over a condition the gate's own diagnostic says is
    # recoverable by a prefix correction. Context B separately had no catch-all at all, so an exit 4
    # (reachable there on an IO fault) or an uncaught decode error had no documented branch.
    # Guarded by test_context_a_gate_table_documents_exit_8 in test_handoff_contract_ratchet.py.
    # +write_coverage_disclosure.py pipe on the hand-roll route (W7) and the heredoc-quoting
    # guardrail (W11): cap-table is the only skill with UNQUOTED heredoc delimiters (both
    # templates interpolate), so the fleet rule in market-sizing/SKILL.md is unfollowable here
    # and read as a rule cap-table violated. Guarded by the two heredoc tests in
    # test_skill_orchestration.py.
    # Net of the 2026-08-31 adversarial pass: cap-table +uncovered_parts stringify guidance;
    # competitive-positioning -1.4 KB from de-duplicating the "Preserve _produced_by" note,
    # which had been pasted verbatim four times (twice four lines apart).
    # cap-table 149,836 -> 149,866 (+30 B): a sentence cited `E_SCHEMA_VERSION_MISMATCH` as what
    # validate mode rejects a missing schema_version with. That code lived only in a loader nothing
    # called; measured, validate mode rejects via the schema ("required field 'schema_version'
    # missing"). The prose now says what happens.
    # +129 B (fleet, one shared edit): the delivery block's hand-over sentence said the link form in
    # Cowork is `computer://` + the absolute path. MEASURED in-app on the remote lane (2026-09-21/22,
    # the default lane for new sessions and the one the market-sizing bug report came from): no link
    # form opens a file there -- computer:// is plain text and a bare path becomes a broken claude.ai
    # URL; the presented card is the delivery. The sentence now says: a link where this surface
    # renders one that opens (on a /sessions tree, computer:// + the path), otherwise the label with
    # the path stated beside it. Same edit in all six; test_delivery_block_is_identical_fleet_wide
    # is the proof.
    # +1,275 B (fleet, one shared edit): the Step 0 preflight and its stop. MEASURED 2026-09-22 on
    # claude.ai, which mounts skills FLAT at /mnt/skills/plugins/<plugin>:<skill>/ and serves no
    # plugin: the shared scripts were unreachable and no sub-agent could be dispatched, and
    # market-sizing ran anyway -- hand-writing every hand-off file, grading its own checklist, and
    # shipping a report with no adversarial review and no gates. One line detects it; the skill now
    # stops and says so instead of producing something that reads as checked.
    # +1,571 B (151_270 -> 152_841): the file tools refuse a relative path, so Step 0 gains the proof
    # of the file-tool path of outputs (probe + --set-host-outputs-dir), the hand-off protocol gains
    # the `write_refused` branch (both contexts), and the degrade rule tells the founder instead of
    # noting it. The procedure itself lives once in skill-execution-model.md.
    # +2,603 B (152_841 -> 155_444): the option pool's basis is asked, not defaulted -- a Pool basis
    # catalog row (the three computed readings plus "ask counsel", in the order the fallback relies on),
    # the top-up intent row made basis-free, and Step 5's paragraph saying where the answer goes, which
    # flag records it, how the document's own pool sentence may be quoted, and what to do on each
    # pool-basis refusal. It replaces fast-assess's inline pre/post question rather than adding a second.
    # +85 B (cap-table): the hand-over names report.json's `report_disclosures`. The option pool's disclosures left
    # the coaching payload (the coach no longer discusses the pool's sizing), and one of them is high severity.
    # +40 B (cap-table): the Pool basis row's third option is named by what it counts ("Measured against the share
    # count before the round", not "The pool before the new money", which is how every pool works), and the
    # excluding-basis question offers "the figures that count the conversion shares", not "plain post-money".
    # +1,165 B (cap-table): Step 11 runs the option-pool claims check (`pool_claims_check.py`) on every insertion
    # path -- normal, graceful-degrade and inline -- and states its exit-9 branch (one redo inside the existing
    # budget, then `--strip`). A new pipeline step, not prose: the check writes the only file insert_coaching reads.
    # +509 B (cap-table): Step 11 runs `pool_check_release.py` before insert_coaching on all three insertion paths,
    # and states its refusal branch. A new pipeline step, not prose: the check's own file is no longer insertable,
    # so only a release whose record matches the commentary, the checked file and the run reaches the report.
    # +288 B (cap-table): Step 11's exit-9 branch says what happens with the redo budget spent (straight to
    # `--strip`) and how the redo works on the degrade and inline paths, whose scratch files move out of the
    # delivered review dir.
    # +263 B (cap-table): Step 11 states the check's exit-2 branch (it could not read this run's scenarios.json: fix
    # the path, re-run). A new refusal, not prose: failing open there let a mistyped path skip the judge.
    # 157,645 -> 158,887 on 2026-10-02: Step 0 tells whether this skill's text arrived with its plugin folder
    # filled in and, only when it did not (a skill started as the first message of a new conversation), finds
    # the plugin by a filesystem search and prints READ_ROOT= for the Reads and sub-agent prompts. The Step 3
    # lane table names each lane reference by an absolute path, since it is a Read directive.
    # 158,887 -> 158,695 on 2026-10-03: Step 0's preflight comment is two lines, the plugin-paths paragraph is
    # shorter and plainer, a manifest-less plugin copy is kept by the search, and the block says to run it
    # with the token as shown and that PLUGIN_ROOT is for shell commands only. One reference Read directive
    # names its file under the plugin token.
    # 158,695 -> 158,758 (+63 B) on 2026-10-03, the same +63 B in all six: Step 0's PLUGIN_ROOT comment names it
    # the shell's path and states the one exception, a printed READ_ROOT= used in Reads and prompts.
    # 158,758 -> 158,770 on 2026-10-03: the image-only PDF and tracked-changes DOCX guards run their helper
    # scripts through "$SCRIPTS/…" instead of a relative scripts/ path.
    # 158,770 -> 158,958 on 2026-10-04: "never delete under outputs" is this skill's rule, not a platform
    # limit (newer hosts allow deletes). Step 0's append-only paragraph, the hand-off comment and the retry
    # line say so instead of claiming the host refuses. The fixing-a-bad-artifact line names the rule, not a
    # host refusal.
    # 158,958 -> 159,356 (+398 B) on 2026-10-05: Step 0 no longer defines a reference
    # folder for the shell (REFS=/SHARED_REFS=, a VM path the Read tool is refused) and names the folder
    # for Reads in prose, as loaded; every read directive names its file under the plugin token, never a
    # bare relative references/ path or a printed shell value.
    # 159,356 -> 159,369 (+13 B) on 2026-10-05: the read-directive clauses say "never the shell's path to the
    # plugin folder" instead of "never a path the shell printed", which also covered the hand-off paths the
    # shell prints for Reads.
    # All six lowered for the trigger-phrase move: the conditions that decide when a skill applies now sit
    # in `description`, which Desktop's discovery scanner reads, and `when_to_use` keeps only what the
    # description does not already say, so the frontmatter shrank in every skill.
    # 159,095 -> 159,024 on 2026-10-05: the description says the skill starts on its own only on a clear request,
    # and that a passing question gets a short answer and an offer naming how long the run takes.
    # Fast-assess states its usual time in place of 'under 60 seconds'.
    # 159_024 -> 159_052 (+28 B) on 2026-10-05: the feedback lines tell the founder to type
    # `/founder-skills:feedback`; it is a user-started skill now, which the model cannot start.
    # 159_052 -> 159_178 (+126 B) on 2026-10-05: the Step 0 STAGING_DIR block says
    # scratch output (a redirect or a temp file) goes in $STAGING_DIR, never a fixed /tmp/<name>, because
    # /tmp is shared across sessions.
    # 159,178 -> 156,625 (-2,553 B) on 2026-10-08: gates wired. The catalog sections (Skill Metadata, Available
    # Scripts, Available References) are out; the Gate Catalog stays, "never hand-compose report_extraction_only.md"
    # moved to the no-cap-base fork and the sentinel-schema pointer to Step 5-fast. Step 0 starts the run's record
    # (the RUN_ID mint line is out), the slug block binds it; every question is opened, asked and recorded; the
    # extraction is confirmed before it is saved; the lightweight routes and the terms-only fork finish the run;
    # exit-10 carve-outs; the pages take --run-id and Step 12 closes the run's file list.
    # 156,625 unchanged, commit 10 (O3): the compose step says to read compose_result.json on a non-zero exit,
    # paid for in the same step (the Step 8 parity sentence shortened).
    # -8 B, LOWERED, commit 13: a derived stage takes its option id and no value; two clauses of the same
    # paragraph shortened.
    "cap-table": 156_609,
}


# ---------------------------------------------------------------------------
# Fresh-shell contract (P4/P5)
#
# Every Bash tool call is a fresh shell — a variable set in one call is gone in
# the next, and unset expands to empty rather than erroring, so a path quietly
# becomes e.g. `/inputs.json` instead of failing loud. All six skills must warn
# about this, but the SAFE remedy differs by skill:
#
#   - market-sizing, ic-sim, competitive-positioning, financial-model-review mint
#     RUN_ID in a LATER block than the one this banner sits in, so "re-run the
#     block below" is a safe remedy for them. They share one byte-identical
#     banner — verified, one md5 across all four.
#   - cap-table and deck-review mint RUN_ID INSIDE this same re-runnable Step-0
#     block, so re-running it would re-mint a DIFFERENT RUN_ID mid-engagement
#     (cap-table: SKILL.md's Step 0; deck-review: same shape). The shared
#     banner's remedy is UNSAFE for them, so each carries its own fact-plus-
#     remedy sentence instead — read the printed values and paste them as
#     literals — and must NOT be forced onto the shared remedy text.
# ---------------------------------------------------------------------------

FRESH_SHELL_FACT_SENTENCE = "Every Bash tool call runs in a fresh shell — variables do not persist."

# Updated 2026-08 remediation: the banner previously said "Prefix every Bash call that uses these
# paths with the variable block below, or substitute absolute paths directly" — which licensed
# re-running the block, and the block contains the plugin-root `find` self-heal. Measured, one
# session mounted two DIFFERENT plugin versions at once, so a per-call re-resolution can land on a
# different mount than Step 0 picked and silently mix producer scripts mid-pipeline. The banner now
# makes resolve-once-then-substitute-the-printed-value the instruction. Still byte-identical across
# all four skills — edit one and re-copy.
FRESH_SHELL_BANNER = (
    "**Every Bash tool call runs in a fresh shell — variables do not persist.** "
    "Run the block below exactly **once**: it resolves `$PLUGIN_ROOT` deterministically, and every "
    "later block must substitute the printed value as a literal rather than re-running the "
    "resolution — repeating the self-heal search can land on a different mount than Step 0 picked "
    "when more than one is present (see why in the block's comments)."
)

FRESH_SHELL_BANNER_SKILLS = frozenset({"market-sizing", "ic-sim", "competitive-positioning", "financial-model-review"})

FRESH_SHELL_BESPOKE_SKILLS = frozenset({"cap-table", "deck-review"})


@pytest.mark.parametrize("skill", sorted(SKILL_MD_CEILING))
def test_all_skills_carry_a_fresh_shell_warning(skill: str) -> None:
    """Every skill must warn that Bash tool calls do not share state.

    Before this, deck-review's only mention was a parenthetical inside a code
    comment ("a captured var dies in the next fresh shell") — easy to miss
    among ~122 later `$VAR` references. Loose substring check on purpose: the
    two more specific tests below pin the exact wording for each half of the
    fleet.
    """
    text = (SKILLS_ROOT / skill / "SKILL.md").read_text(encoding="utf-8")
    assert "fresh shell" in text.lower(), f"{skill}/SKILL.md carries no fresh-shell warning."


@pytest.mark.parametrize("skill", sorted(FRESH_SHELL_BANNER_SKILLS))
def test_fresh_shell_banner_byte_identical_fleet_wide(skill: str) -> None:
    """The four skills that mint RUN_ID in a LATER block share one byte-identical banner.

    Checked via exact-substring containment against one recorded constant, which is
    itself the byte-identical-across-all-four assertion: if any of the four drifted
    even by a character (reworded, re-punctuated, a different em-dash), this fails.
    """
    text = (SKILLS_ROOT / skill / "SKILL.md").read_text(encoding="utf-8")
    assert FRESH_SHELL_BANNER in text, (
        f"{skill}/SKILL.md: shared fresh-shell banner not found verbatim. This banner is shared prose "
        "across market-sizing/ic-sim/competitive-positioning/financial-model-review — edit one and "
        "re-copy to all four; do not paraphrase."
    )


@pytest.mark.parametrize("skill", sorted(FRESH_SHELL_BESPOKE_SKILLS))
def test_bespoke_fresh_shell_warning_present_without_the_shared_remedy(skill: str) -> None:
    """cap-table and deck-review need their OWN fresh-shell sentence, not the shared banner.

    Both mint RUN_ID inside the same re-runnable Step-0 block, so the shared banner's
    remedy — "re-run the block below" — would re-mint a different RUN_ID mid-engagement
    and silently split the hand-off dir / desync setup_run.py's resume decision. Each
    must still state the fresh-shell FACT (deck-review reuses that exact sentence; see
    test_deck_review_carries_the_fresh_shell_fact_sentence below) but must not carry the
    shared banner's remedy sentence verbatim.
    """
    text = (SKILLS_ROOT / skill / "SKILL.md").read_text(encoding="utf-8")
    assert "fresh shell" in text.lower(), f"{skill}/SKILL.md is missing any fresh-shell warning."
    assert FRESH_SHELL_BANNER not in text, (
        f"{skill}/SKILL.md carries the shared banner's remedy verbatim ('re-run the block below'), but "
        "that remedy is unsafe here — this skill mints RUN_ID INSIDE the re-runnable Step-0 block, so "
        "re-running it re-mints a DIFFERENT RUN_ID mid-engagement."
    )


def test_deck_review_carries_the_fresh_shell_fact_sentence() -> None:
    """deck-review's fix: state the fact sentence verbatim near Step 0's start.

    It used to carry only a parenthetical mention inside a code comment
    (`# ... a captured var dies in the next fresh shell`), easy to miss among
    ~122 later `$VAR` references in the rest of the skill.
    """
    text = (SKILLS_ROOT / "deck-review" / "SKILL.md").read_text(encoding="utf-8")
    assert FRESH_SHELL_FACT_SENTENCE in text, (
        "deck-review/SKILL.md must state the fresh-shell fact verbatim near Step 0's start."
    )


def test_cap_table_echoes_run_id_so_the_paste_remedy_is_satisfiable() -> None:
    """cap-table's note tells the model to paste RUN_ID's printed literal — so Step 0 must print it.

    Since the gates release the literal is the `run_id` the run's record (`run_status.py start`) prints, and the
    note says so; the old mint-and-echo line is gone (a re-run of it would start a second id).
    """
    text = (SKILLS_ROOT / "cap-table" / "SKILL.md").read_text(encoding="utf-8")
    assert 'run_status.py" start --skill cap-table' in text
    assert "`$RUN_ID` is the `run_id` the run's record prints below" in text
    assert 'RUN_ID="<the run_id start printed>"' in text
    assert not re.search(r'echo\s+"RUN_ID=\$RUN_ID"', text)


# competitive-positioning raised for the recall/recency schemas: recent_developments[] (dated,
# URL-sourced, agent_estimate rejected, empty-is-correct), the landscape_as_of stamp, the
# NO_RECENT_DEVELOPMENTS severity row, and the recall_gaps block — including the rule that
# draft_only is diagnostic and must never be shown to the founder as a verdict. Partly offset by
# replacing the methodology's "trajectory arrows" bullet, which promised an analysis the pipeline
# never performed and which a later session could only have "implemented" by fabricating
# historical coordinates.
# competitive-positioning raised again: the moat_assessments dedup-union wording replaced a stale
# back-compat-fallback description (with its two imperfect-key edge cases spelled out), the
# suggested_additions `merged` flag contradiction between the LANDSCAPE_RESEARCH and landscape.json
# schemas was resolved onto one model, and the methodology's Common-confusions table was trimmed to
# point at its own corollary/delta sections instead of restating them — a trim that didn't fully
# offset the schema additions.
# ic-sim raised for discussion.json's `debated_dealbreakers` row: the id-level channel that lets
# compose_report.py tell a partner-argued dealbreaker from one the scoring pass produced alone.
# Before it, key_concerns dropped the dimension ids, so nothing downstream could compare the two —
# a live run scored four dealbreakers against three the debate raised and the report narrated all
# four as "independent fatal flaws". The row has to carry the absent-vs-empty distinction, since
# reading a missing channel as "none debated" is the specific way this check goes quietly wrong.
# competitive-positioning raised 127,661 -> 136,835 for the 2026-08 remediation. Every added row
# documents a field or warning code a producer now emits, or corrects a documented shape that a live
# run proved wrong: the axis-rationale nesting rule (a compliant run emitted blank rationales while
# the checklist graded POS_05 pass on text no founder could see), the rank convention (a delivered
# report read "Y=11 (of 10 competitors)"), the recency window's downgrade from fatal to
# drop-with-warning, and NARR_03's missing band for a deck that names no competitor. Schema drift
# that ships to a founder is the expensive kind; these rows are the cheap kind.
REFERENCES_CEILING: dict[str, int] = {
    # market-sizing +813 B: artifact-schemas.md documents sizing.json's new `fx` block and
    # retracts "currency is a label only — nothing in this skill performs FX conversion", which
    # became false.
    # +370 B (42_813 -> 43_183): the `approaches_reconciled` rubric was rewritten so that the
    # two approaches agreeing is no longer a pass on its own -- the pipeline cannot tell whether
    # both builds rest on the same underlying figures, so closeness is not confirmation.
    # +771 B (43_183 -> 43_954): artifact-schemas.md documented `overall_status` as the boolean
    # ("pass" if fail==0) and CHECKLIST_FAILURES as high-severity-on-any-failure. Both statements
    # became false with the band split, and the reference is where a producer author looks.
    # +229 B (43_954 -> 44_183): the CHECKLIST_FAILURES_CRITICAL row still documented `fail > 6`.
    # That absolute cutoff assumes all 22 criteria apply; with 7 not_applicable the boundary is 5,
    # and a checklist scoring 66.7% was filed as the acceptable warning. The row now states the band
    # rule and records that it reproduces 6/7 exactly when nothing is N/A.
    # +223 B (44_183 -> 44_406): the CHECKLIST_FAILURES row still said "between 1 and 6", which is
    # the same all-22-applicable assumption its critical counterpart had just been corrected for —
    # the two adjacent lines contradicted each other whenever any item was not_applicable.
    # market-sizing 44,406 -> 45,137 (+731 B): the two horizon fields documented in
    # artifact-schemas.md's inputs.json table, including which one is read today (som only).
    # +1,050 B (45_137 -> 46_187): artifact-schemas.md documents `factors[]` on derived
    # assumptions -- the field row, the example entry, and the two warning codes that read it.
    # +515 B (46_187 -> 46_702): methodology.json's `red_team_skipped` row -- the closed enum, and
    # the fact that compose refuses without it.
    # +294 B (46_702 -> 46_996): the references stopped teaching the one term compose refuses in
    # its own labels -- the schema example FOR the rationale field said "Cross-validation
    # preferred", and a live run transcribed it almost verbatim into a founder's report. The
    # methodology section that carried the same header also contradicted this skill's own
    # checklist rubric on substance: it said only a BIG mismatch needs work, while the rubric
    # grades agreement-presented-as-confirmation a failure. Rewritten to the rubric's position.
    # +1,594 B (46_996 -> 48_590): artifact-schemas.md gains the redteam.json section it never had.
    # The hand-off gained a third provenance (`document:<file>#page=<n>`, the founder's own page),
    # `quote_verified`, and `sources_read`/`sources_unread`; a field the schema doc does not name is
    # a field the model leaves out -- the two horizon fields sat null on every live run for exactly
    # that reason.
    # +226 B (48_590 -> 48_816): the `factors` row now says two-or-more multiplicands, one entry is
    # not a chain, and a sum is described in `label` -- the live run's mis-encodings, both.
    # +303 B (48_816 -> 49_119): the optional `parameter` field on a red-team finding, which is what
    # lets the report mark every row built on a stated figure a cited source contradicts.
    # +59 B (49_119 -> 49_178): the document citation's page must be >= 1 and the file is the
    # hand-off mirror, not the raw uploads mount.
    # +68 B (49_178 -> 49_246): the page is required for a PDF and omitted for a file with no pages.
    # MEASURED live: the red team cited a markdown file, the rule demanded #page, and a real
    # finding was set aside.
    # +198 B (49_246 -> 49_444): the founder_stated_inputs row says which parameter is a fact about
    # the founder's own business and which are market claims, and names the warning.
    # +468 B (49_444 -> 49_912): the founder_stated_inputs_period row in artifact-schemas.md.
    # +24 B (49_912 -> 49_936): `no_subagent_dispatch` added to the red_team_skipped enum.
    # +1,296 B (49_936 -> 51_232): the adversarial review's new contract, in artifact-schemas.md --
    # the three methodology fields Step 6d writes (red_team_revision, founder_notes, gate_defaults),
    # the append-only review copy compose renders from, summary.humanized, and the JSON-quote reason.
    # Documented because the critique corpus cannot see scripts/: a field only the code knows is a
    # field an evaluator (and a model reading the schema) will report as undocumented.
    # +509 B (51_232 -> 51_741): the two inputs.json fields the two-figures question writes,
    # founder_stated_inputs_source and founder_stated_alternatives.
    # +330 B (51_741 -> 52_071): the `factors` row now documents the optional `"role": "divisor"`
    # entry, which lets a derived figure be itemized as a ratio (e.g. 15,000,000 / 52,800,000)
    # instead of only as a product -- the live run this fixes had itemized both numbers as plain
    # multiplicands and the mismatch warning read as a nonsensical product of the two.
    # +281 B (52_071 -> 52_352): the founder_stated_choice row -- the recorded answer that alone lets
    # the report say "the one you chose".
    # +2,911 B (52_352 -> 55_263): artifact-schemas.md documents the reference contract -- a unit,
    # currency, period and exchange-rate fields on every recorded figure; sizing.json's input_refs /
    # input_provenance / provenance_version; the stamped provenance and the checks that re-derive
    # it; the review's inputs_reviewed; and sensitivity/checklist --sizing stamps. It is the one
    # place those contracts are written down, and it replaces a section that documented the name
    # join this change removes.
    # +157 B (55_263 -> 55_420): the schema row for a founder figure's `label` states the rule SKILL.md does.
    # +99 B (55_420 -> 55_519): the red_team_revision row names the approved change's unrendered `reason`.
    # -184 B (55_519 -> 55_335), LOWERED: the red_team_revision row no longer documents an approval.
    # +90 B (55_312 -> 55_402): the existing_claims_alternatives row says an alternative is the same
    # metric AND date, and where a figure for another date goes, as SKILL.md now does.
    # 55,402 -> 55,719 (+317 B) on 2026-10-05: methodology.json's `red_team_skipped_run_id` row.
    # +395 B on 2026-10-08 (commit 13): artifact-schemas.md says the report reads the run ledger instead of
    # `founder_stated_choice` / `gate_defaults` when one exists, and documents the checklist's `inputs.json` stamp.
    "market-sizing": 56_114,
    # fmr raised to document `graded_against` on the three producer outputs that stamp it — a new
    # artifact field is not discoverable from a schema doc that omits it, and the field exists to make
    # staleness detectable at all (run_id parity cannot see corrections applied within a run).
    # fmr +667 B: the coaching_payload table was missing static_runway_months and base_runway_note —
    # two fields compose EMITS and SKILL.md instructs the model to read. It also now states that a
    # null runway_months is a RESULT (default-alive), not a gap.
    # fmr +123 B (73_628 -> 73_751): CASH_24's bands did not partition their own axis. Pass read
    # "Seed/A 24-36mo" and warn read "12-18 months", leaving 18-24mo at seed in NO band; a delivered
    # run graded a 22-month runway `pass` on evidence that said "Within seed 24-36mo target band but
    # slightly short". A rubric hole does not read as a hole to the grader — it reads as a judgement
    # call, and the nearest band wins. The rewrite closes 18-24 and >36, and states that hedged
    # evidence is a warn.
    # financial-model-review references +787 B (J5): the SaaS-vs-SaaS tiebreak justified itself by a
    # CAC-payback band it does not control (payback keys on acv_tier), between two values NO code in
    # the fleet distinguishes — a rule that documented behaviour it did not implement. Replaced with
    # what actually matters: the case where NEITHER SaaS type fits, where the default silently
    # switches on the whole SaaS metric suite for a business the taxonomy cannot express.
    # financial-model-review -209 B (74_538 -> 74_329, e2e-gate-root-cause §3.3/§3.5): STRUCT_08's
    # label promised internal reconciliation (BS ties, retained earnings) that no Pass/Warn/Fail bar
    # ever assessed and that no other criterion covers either — narrowed to the error-token half the
    # bars actually score (-122 B), which also matches checklist.py's plain "No structural errors"
    # label. Also deleted checklist-criteria.md:324's self-gating instruction, which contradicted the
    # file's own :17 (-87 B).
    # financial-model-review 74,538 -> 74,328 (-210 B): STRUCT_08's label promised internal
    # reconciliation its own pass/fail bars never covered, which handed the assessor a standing
    # reason to set the criterion aside; the label now matches the bars. Also deleted the line
    # telling the assessor to gate items itself -- the same file opens by telling it not to --
    # and the blank line it left behind.
    # financial-model-review +417 B (74_328 -> 74_745): two coaching_payload rows that disagreed
    # with the producer. `high_severity_warnings` was documented `string[]` / "warning codes" while
    # compose_report.py has emitted `{code, label, message}` — the agent body said "codes only" and
    # SKILL.md said to write the label, so one of the coach's two instructions was false either way,
    # on the surface founder prose is written from. And `score_coverage` was absent from the table
    # entirely though compose emits it top-level and both prompts instruct the model to read it: the
    # one field that says how much of the review actually ran was undocumented where a producer
    # author looks.
    # 74_745 -> 75_096 (+351 B): schema-inputs.md documents `company.unclassified_reason` and replaces
    # an instruction to "describe the model in `agent_supplied`" -- a field that holds dotted paths, so
    # the instruction could not be followed and the two `unclassified` cases were indistinguishable.
    # It names both setters and says to leave the field out when unsure (the report then hedges).
    # 75_096 -> 76_405 (+1,309 B): take-rate revenue is recorded net and the basis declared (the burn
    # multiple is graded only on net revenue); a project OEM is routed to unclassified, not hardware;
    # a fintech data-sufficiency row; payments clauses in UNIT_14 / METRIC_33 / METRIC_34.
    # +159 B (76_405 -> 76_564): METRIC_34 says what a contextual burn multiple gets (warn, or its
    # reference grade for a non-USD model), now that the grader reads the computed figure.
    # 76_564 -> 79_249: a project builder gets its own type. schema-inputs.md replaces the
    # route-to-unclassified paragraph with a decision rule (billing mechanics decide, what to leave null,
    # how to record recognised revenue) plus the enum row, table row and SECTOR_41 mapping;
    # checklist-criteria.md adds project-builder clauses to UNIT_14 / CASH_22 / SECTOR_41 and a category-6
    # note; data-sufficiency.md a row so a builder is not counted as missing MRR and growth;
    # extraction-pitfalls.md milestone and no-growth-rate sentences and a markup-on-cost item.
    # +205 B (79_249 -> 79_454): METRIC_35 had pass/warn/fail only for a model that uses benchmarks, so
    # an assessor set a model citing none aside as not_applicable. It now grades that case warn.
    # +326 B on 2026-10-08 (commit 13): report.json's ledger-only `disclosures` key is documented.
    "financial-model-review": 79_780,
    # ic-sim +1446 B: evaluation-criteria.md omitted `to_confirm` from the status table AND from the
    # scoring formula, which excluded only not_applicable. Following it changed the conviction
    # score, since score_dimensions.py excludes both. The >6 coverage cap was undocumented too.
    # ic-sim 55,805 -> 56,354 (+549 B) on 2026-10-08: the maintainer notes SKILL.md's Available References
    # carried (which file a step reads, which is documentation only, where the sub-agents' copy lives) moved
    # into the three references' headers when the catalog left SKILL.md.
    "ic-sim": 56_354,
    # 49_039 -> 50_080 (R1): artifact-schemas.md now documents the evidence/notes
    # contract and its JSON example demonstrates a fail item carrying both.
    # 50_080 -> 50_124 (R2): artifact-schemas.md documents the half-credit formula.
    # 50_124 -> 50_422 (design gate): checklist-criteria.md records that the gate covers
    # FOUR criteria, not five — slide_count_appropriate is arithmetic, not a visual
    # judgement, and stays scored whether or not anyone saw a rendered page.
    # deck-review raised 50,422 -> 51,459 (+1,037 B) so the criteria reference states the
    # two things the Design & Readability entries had stopped describing: the per-slide
    # render gate, and verified_by on the four measurement criteria.
    # 51_449 -> 51_724 (+275 B): fail-vs-warn boundary for three criteria. problem_quantified
    # fails only an abstract problem (a named buyer and pain with no number is warn);
    # why_now_has_catalyst gains the purpose_clear rule (search the whole deck and cite the
    # slide before failing; an unsourced argument is weak, not missing); ask_ties_to_milestones
    # names "no ask at all" as a fail, and several dollar raise scenarios as an ask (warn), which
    # the model otherwise failed consistently under the pass bar's "explicit ask" (+91 B).
    # 51_724 -> 51_795 (+71 B): artifact-schemas.md documents checklist.json's
    # `summary.status_by_id`, the by-id map a scenario asserts a criterion's verdict through.
    # 51_795 -> 51_834 (+39 B): market_bottom_up's Fail names a deck with no market sizing at all,
    # which every run already failed by habit while the text named only a top-down chart.
    # 51_834 -> 51_791 (-43 B): deck_inventory's `prior_rounds` row added; the `claimed_stage` and
    # `detected_stage` rows and the example's ai_evidence shortened to pay for it.
    # 51_791 -> 52_206 (+415 B): the competition check counts once. checklist-criteria.md says
    # `no_dodged_competition` carries no weight; artifact-schemas.md documents the item's
    # `weight`, the summary's `scored`, and a score taken over `scored`, not `total`.
    # 52_206 -> 52_810 (+604 B): `numbers_consistent` is scored from the arithmetic. checklist-criteria.md
    # says so on the criterion; artifact-schemas.md and checklist.schema.json declare the item's
    # `scored_by` and `reviewer_status`.
    "deck-review": 52_810,
    # competitive-positioning +474 B: artifact-schemas.md documented the `startup_rank` RENDERING
    # convention but not its SENTINEL. `score_moats.py` stamps {"rank": -1, "total": 0} when the
    # startup is not_applicable on a dimension, and compose_report.py rendered it verbatim —
    # `Rank -1 of 0 ranked — leader: X (N/A)` reached founders, and reproduces from the committed
    # fixture. A convention documented without its sentinel is what let a consumer get it wrong; the
    # per-site guard alone would leave the identical trap for the next reader.
    # competitive-positioning +491 B: artifact-schemas.md documents the `polarity` field on x_axis /
    # y_axis, including that omitting it means higher-is-better — the default that keeps every
    # pre-existing artifact scoring unchanged.
    # competitive-positioning +712 B: moat-definitions.md gains `custom_distribution_channel`. The
    # five existing custom types had no entry for channel/distribution — the nearest were ecosystem
    # lock-in and geographic monopoly, neither of which fits "a named partner reaches 80% of our
    # buyers". A documented path with no example for the case that actually arises is a path nobody takes.
    # competitive-positioning +1,890 B, in one change closing two defects that were invisible in
    # the schema doc. (a) positioning_scores views now carry resolved x/y polarity, and
    # views_fingerprint includes it: polarity decides which end of an axis is good, so flipping it
    # moved rank and differentiation_score under a byte-identical hash and a checklist graded on
    # the old orientation still read FRESH — defeating CHECKLIST_STALE_VS_POSITIONING, the only
    # detector for that class. The note records that only the non-default value is encoded, which
    # is what keeps pre-existing fingerprints stable. (b) CRITERION_MISMATCH joins the warning
    # table with the rule that it MUST carry a founder_message: its agent-facing message names a
    # criterion ID, and verify_positioning.py fails any report.md containing one, so the obvious
    # fix — register the severity and forward the message — ships an unpublishable review. A
    # contract whose violation is a delivery-gate failure has to be written down where the next
    # producer author looks.
    # +the three `**Producer:**` lines in artifact-schemas.md now naming
    # persist_agent_artifact.py: the file is the source of truth the new REQUIRED_KEYS
    # conformance tests read, so leaving it saying "Agent (main, Step 2)" would have made
    # the documentation disagree with both the pipeline and its own tests.
    # +1,423 B (competitive-positioning): artifact-schemas.md documents what the step-2 fixes added --
    # the per-view tie and geometry fields in positioning_scores.json, the three first-copy sidecars,
    # the coaching payload's positioning / claim_verdicts, CAP_DISPLACED_DIRECT, and the changed
    # FOUNDER_OVERRIDE_COUNT meaning. The same commit restores two phrases that earlier commits had
    # bent to hit this ceiling exactly ("retained or as removed", "they fall within"); those bytes
    # are in the delta too, as they should have been from the start.
    # +643 B (competitive-positioning): `unproven` defined in the methodology's verdict scale (with
    # the guidance that an abstract-only read of a detail-dependent claim is unproven) and named in
    # NARR_01 and the claim schema; `verdict_counts` documented on positioning_scores.json.
    # +1,354 B (competitive-positioning): artifact-schemas.md documents startup_research.json (the
    # startup's public record, its computed patent status and the per-office rule), its first copy,
    # and the coaching payload's startup_record.
    # +1,074 B (competitive-positioning): artifact-schemas.md documents the plan-stage fields --
    # product_availability, the startup point's planned_x/planned_y, their evidence and proof levels,
    # and the scored view's scored_point and today block.
    # +165 B (competitive-positioning): artifact-schemas.md documents the coaching payload's
    # outside_review (the review's outcome and one sentence per finding).
    # +176 B on 2026-10-08 (commit 13): who writes `deferred_recall_candidates` (the deferral script after Gate 1),
    # and that it waits for Gate 1's final answer.
    "competitive-positioning": 145_405,
    # cap-table +422 B: inputs-skeleton.md promised "no warning, and downstream artifacts that look
    # right but contain zeros" — the PRE-FIX world. cap_state.py hard-errors E_NO_EQUITY_BASE now,
    # and prose telling a model that a missing base yields plausible zeros invites it to invent one.
    # lane-2 also claimed extract_cap_table.py emits cap_state.json directly; it does not.
    #
    # cap-table +934 B: inputs-skeleton.md now documents `ad_cp2_floor`, the anti-dilution
    # conversion-price floor. Raised deliberately, because the field's ABSENCE from the authoring
    # surfaces was a founder-adverse defect, not a documentation gap: the solver consumed it and two
    # schemas declared it while no extractor, no agent field list and no skeleton mentioned it, so a
    # charter floor could not be supplied and the round math silently ignored it. A missed floor lets
    # the conversion price fall further than the charter allows and UNDERSTATES founder ownership --
    # measured 11.11% vs 5.95% on the golden-10 cap table (test_golden_10d). Prose that prevents a
    # 1.87x ownership error is worth under a kilobyte of on-demand reference content.
    #
    # cap-table +799 B: `ad_a_denominator_basis` documented (same class as the floor -- solver-consumed,
    # schema-declared, supplied by nothing; measured 0.24-0.47 pp of founder ownership), plus a
    # CORRECTION to the trigger-basis prose, which told the reader the OIP-vs-CP1 choice is
    # charter-specific and counsel-confirmed while giving them no field for the answer. Measured: the
    # choice moves nothing in 42 of 42 scenarios, because both formulas are CP1-anchored and
    # `test_golden_9` has always pinned the two bases producing identical prices. Prose that implies a
    # knob matters when it does not is worse than silence -- it invites a founder to pay counsel for
    # an answer that changes no number.
    #
    # cap-table +1,052 B: `cap_table_history` documented — how a founder records a PRIOR down round.
    # Third instance of one defect class in one day (after `ad_cp2_floor` and `ad_a_denominator_basis`):
    # schema-declared, fully consumed (`cap_state.py` passes it straight through from inputs.json, and
    # three solver sites read it), named by no authoring surface. Its absence made
    # W_STALE_CCP_SUSPECTED unfirable — the skill could not be told a conversion price was stale
    # because it could not be told the earlier adjustment happened.
    # cap-table lowered to the measured size: a local-only document pointer removed from the source list.
    "cap-table": 48_355,
}


@pytest.mark.parametrize("skill", sorted(SKILL_MD_CEILING))
def test_skill_md_does_not_grow(skill: str) -> None:
    """SKILL.md must not exceed its recorded size. Ratchet down, never up."""
    path = SKILLS_ROOT / skill / "SKILL.md"
    size = len(path.read_bytes())
    ceiling = SKILL_MD_CEILING[skill]
    assert size <= ceiling, (
        f"{skill}/SKILL.md grew to {size:,} B (ceiling {ceiling:,}). The skill body is re-read on every "
        "dispatch, so growth costs context on every run, and unbounded growth is how a skill stops being "
        "maintainable. Shrink something, or raise the ceiling deliberately with the reason recorded."
    )
    if size < ceiling:
        pytest.fail(
            f"{skill}/SKILL.md shrank to {size:,} B — good. Lower SKILL_MD_CEILING['{skill}'] to "
            f"{size:,} to lock the win in."
        )


# The feedback skill's size ratchet lives apart from SKILL_MD_CEILING because that dict's keys are the
# fleet of ANALYSIS skills: a dozen tests parametrize over them (delivery, preflight, plugin-root
# resolution, option lists), none of which a no-shell feedback skill has.
# 2,891 B on 2026-10-05: measured when the command became a skill.
# 2,891 -> 3,049 B (+158) on 2026-10-05: where the plugin token arrives unfilled, the version comes from a Glob
# for the plugin's manifest under the cloud plugins folder (exactly one match, else "unknown"), with no
# shell, so the exemption holds.
FEEDBACK_SKILL_MD_CEILING = 3_049

# Skill re-attachment after compaction stores `Base directory for this skill: <abs path>` (101-240 chars,
# install-dependent) plus the body with frontmatter stripped, and truncates at >= 20,002 chars. Kept under
# 20,001 chars with the longest prefix, the feedback skill survives a compaction whole.
_REATTACH_LAST_SAFE_CHARS = 20_001
_REATTACH_PREFIX_MAX_CHARS = 240
# A skill over the cap is truncated: the entry keeps `slice(0, 19,900)` of prefix + body plus a 100-char marker.
# Every WIRED skill is over it, so its run-start block must end by 19,900 - 240 body chars, not 20,001 - 240.
_REATTACH_RETAINED_CHARS = 19_900


def test_feedback_skill_md_does_not_grow() -> None:
    size = len((SKILLS_ROOT / "feedback" / "SKILL.md").read_bytes())
    assert size <= FEEDBACK_SKILL_MD_CEILING, (
        f"feedback/SKILL.md grew to {size:,} B (ceiling {FEEDBACK_SKILL_MD_CEILING:,}). Shrink something, or "
        "raise the ceiling deliberately with the reason recorded."
    )
    if size < FEEDBACK_SKILL_MD_CEILING:
        pytest.fail(f"feedback/SKILL.md shrank to {size:,} B — lower FEEDBACK_SKILL_MD_CEILING to lock it in.")


def test_feedback_finds_its_version_without_a_shell() -> None:
    """Where the plugin token arrives unfilled, the version comes from a Glob for the manifest, never a
    shell: the skill is exempt from the no-disable rule only because it runs none."""
    text = (SKILLS_ROOT / "feedback" / "SKILL.md").read_text(encoding="utf-8")
    assert "use `Glob` with pattern `**/founder-skills/.claude-plugin/plugin.json`" in text
    assert '"unknown"' in text
    for shell in ("Bash", "bash", "mcp__workspace__", "allowed-tools", "```sh"):
        assert shell not in text, f"feedback/SKILL.md names {shell!r}; it must stay shell-free"


@pytest.mark.parametrize("skill", sorted(SKILL_MD_CEILING))
def test_feedback_offer_tells_the_founder_to_type_the_command(skill: str) -> None:
    """The feedback skill is user-started only (`disable-model-invocation`), so an offer the model reads as
    "start it" cannot be carried out; each offer tells the founder to type it."""
    text = (SKILLS_ROOT / skill / "SKILL.md").read_text(encoding="utf-8")
    if "/founder-skills:feedback" not in text:
        return
    offers = [line for line in text.splitlines() if "/founder-skills:feedback" in line]
    for line in offers:
        assert "type `/founder-skills:feedback`" in line, f"{skill}: an offer that does not say to type it: {line}"


def test_feedback_skill_survives_compaction_whole() -> None:
    text = (SKILLS_ROOT / "feedback" / "SKILL.md").read_text(encoding="utf-8")
    assert text.startswith("---\n")
    body = text[text.index("\n---\n", 4) + len("\n---\n") :]
    stored = _REATTACH_PREFIX_MAX_CHARS + len(body)
    assert stored <= _REATTACH_LAST_SAFE_CHARS, (
        f"feedback's re-attached content would be {stored:,} chars (body {len(body):,} + a {_REATTACH_PREFIX_MAX_CHARS}"
        f"-char base-directory prefix), past the {_REATTACH_LAST_SAFE_CHARS:,} that survive a compaction whole."
    )


@pytest.mark.parametrize("skill", sorted(REFERENCES_CEILING))
def test_references_total_does_not_grow(skill: str) -> None:
    """references/ total must not grow.

    Formerly the binding evaluator budget (8 KiB shared across every file, which our
    skills oversubscribed 4x-13x). The harness now ships references whole, so this no
    longer gates grade fidelity — and the old corollary that moving prose into
    references/ makes grading worse is RETIRED. It remains a size ratchet: reference
    content is loaded on demand, so bounded growth is still worth holding.
    """
    refs = sorted((SKILLS_ROOT / skill / "references").glob("*.md"))
    size = sum(len(p.read_bytes()) for p in refs)
    ceiling = REFERENCES_CEILING[skill]
    assert size <= ceiling, (
        f"{skill}/references/ grew to {size:,} B (ceiling {ceiling:,}). Reference content is loaded on "
        "demand, so growth is cheaper here than in SKILL.md — but it is not free."
    )
    if size < ceiling:
        pytest.fail(
            f"{skill}/references/ shrank to {size:,} B — good. Lower REFERENCES_CEILING['{skill}'] to "
            f"{size:,} to lock the win in."
        )


# ---------------------------------------------------------------------------
# Critique evidence corpus — the constraint the per-file ratchets do NOT capture
#
# `cowork-harness critique` packages SKILL.md + every file under references/ +
# agents/<skill>.md as one corpus, against a 512 KiB ceiling. Over it, content is
# CUT — loudly and by name, but cut — and the grade covers less than the author
# believes.
#
# Two things make this easy to get wrong, and we got both wrong before measuring:
#
#   1. EVERY file under references/ counts, regardless of extension. The packager
#      applies no extension filter. cap-table's JSON schemas and rule packs were
#      corpus, not just its markdown. Globbing `**/*.md` put it at 52% when it
#      was at 96%. (The 144 KB rule pack has since moved to skills/cap-table/data/
#      — outside the counted set — for exactly this reason; references/ JSON is
#      now ~80 KB, all of it schemas whose prose descriptions ARE cited evidence.)
#   2. Agent bodies count too, and they are neither in the skill dir nor obvious.
#      For cap-table that file is 65 KB — 12% of the ceiling on its own. It is no
#      longer just `agents/<skill>.md`: the resolver packages every in-plugin agent
#      the skill PINS via a `subagent_type` literal, matched on the agent's declared
#      frontmatter `name:`. So corpus size is no longer a function of the files a
#      given change touches — an edit elsewhere can widen it. Read `corpusPackaged`
#      on a real report rather than predicting it.
#
# The per-file ratchets above cannot see this: SKILL.md and references/ can each
# be individually unremarkable while their sum is over. Hence a separate guard.
# ---------------------------------------------------------------------------

CRITIQUE_CORPUS_CEILING = 512 * 1024


def _declared_agent_name(path: Path) -> str:
    """The agent's frontmatter `name:`, falling back to the filename stem.

    The resolver matches on the DECLARED name, not the filename, so a file whose frontmatter
    disagrees with its stem resolves under the declared one. Falling back to the stem rather than
    skipping keeps a frontmatter-less file countable instead of silently free.
    """
    text = path.read_text(encoding="utf-8")
    m = re.search(r"^name:\s*([A-Za-z0-9_-]+)\s*$", text, re.MULTILINE)
    return m.group(1) if m else path.stem


def _pinned_agent_files(skill: str) -> list[Path]:
    """agents/<skill>.md plus every in-plugin agent this skill PINS, matched the resolver's way.

    A pin is a `subagent_type` literal in the skill's SKILL.md or any references/** file; the
    agent it names is resolved by declared frontmatter `name:`. Deliberately NOT a glob over
    agents/** — that counts agents the skill cannot dispatch, which is a different wrong number
    and not a safe one.
    """
    agents_dir = SKILLS_ROOT.parent / "agents"
    skill_dir = SKILLS_ROOT / skill
    sources = [skill_dir / "SKILL.md"]
    refs = skill_dir / "references"
    if refs.is_dir():
        sources += [p for p in refs.glob("**/*") if p.is_file()]
    pinned_names: set[str] = set()
    for src in sources:
        try:
            text = src.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        pinned_names.update(re.findall(r'subagent_type"?\s*[:=]\s*"founder-skills:([a-z0-9-]+)"', text))

    out: list[Path] = []
    namesake = agents_dir / f"{skill}.md"
    if namesake.is_file():
        out.append(namesake)
    if agents_dir.is_dir():
        for path in sorted(agents_dir.glob("*.md")):
            if path in out:
                continue
            if _declared_agent_name(path) in pinned_names:
                out.append(path)
    return out


def _corpus_bytes(skill: str) -> int:
    """What a `critique` actually packages for this skill, in bytes.

    FOUR classes since cowork-harness 3.7.0, and the three-term formula this replaced under-reported
    SILENTLY — the dangerous direction, because over the ceiling the failure mode is content cut
    before grading, with nothing louder than a `corpusCuts` entry nobody reads:

      1. `SKILL.md`
      2. every file under the skill's OWN `references/`
      3. every agent the skill RESOLVES — the union of `agents/<skill>.md`, every agent a pinned
         `subagent_type` literal names, every agent whose declared `name:` equals the skill name,
         and the transitive closure of pins inside those agent bodies
      4. every PLUGIN-ROOT `references/` file the skill's own text points at

    Class 4 is what 3.7.0 added and what this repo was blind to: worth +37,793 B to cap-table, which
    it moved from a believed 76.3% of the ceiling to a measured 83%.

    Classes 3 and 4 are delegated to `_critique_corpus`, a verbatim vendored copy of the harness's
    own resolver, rather than re-derived here — upstream cross-language-pins that logic against its
    TypeScript implementation with shared fixtures both sides execute, and a hand-rolled
    approximation inherits none of that. `test_critique_corpus_sync.py` holds the copy to the
    installed CLI's.

    The result is a FLOOR, never an exact match: upstream also packages plugin-root references an
    agent READ at runtime, which is run-dependent and cannot be resolved statically.
    """
    skill_dir = SKILLS_ROOT / skill
    total = len((skill_dir / "SKILL.md").read_bytes())
    refs = skill_dir / "references"
    if refs.is_dir():
        total += sum(len(p.read_bytes()) for p in refs.glob("**/*") if p.is_file())
    agents = _critique_corpus.resolve_agents(str(skill_dir))
    total += sum(len(Path(a).read_bytes()) for a in agents)
    total += sum(len(Path(r).read_bytes()) for r in _critique_corpus.resolve_root_references(str(skill_dir), agents))
    return total


@pytest.mark.parametrize("skill", sorted(SKILL_MD_CEILING))
def test_critique_corpus_stays_under_the_evidence_ceiling(skill: str) -> None:
    """No skill may exceed the ceiling — over it, a critique grades cut content."""
    size = _corpus_bytes(skill)
    assert size <= CRITIQUE_CORPUS_CEILING, (
        f"{skill}'s critique corpus is {size:,} B, over the {CRITIQUE_CORPUS_CEILING:,} B ceiling "
        f"({100 * size / CRITIQUE_CORPUS_CEILING:.0f}%). A critique will CUT content before grading it, "
        "so findings will cover less than the skill actually says. Shrink references/ (every file counts, "
        "not just *.md) or the agent body. Verify with: cowork-harness lint-skill <skill-dir>"
    )


def test_cap_table_corpus_headroom_is_tracked() -> None:
    """Pin cap-table's critique-evidence headroom so a large addition is a red test.

    Not a style rule — the failure mode over the ceiling is silent-until-you-read
    `corpusCuts`. The margin is the thing worth guarding, not the absolute number.
    """
    size = _corpus_bytes("cap-table")
    headroom = CRITIQUE_CORPUS_CEILING - size
    assert headroom > 0, f"cap-table is OVER the ceiling by {-headroom:,} B"
    # RESTORED to 10_000 after the slimming that was owed actually landed.
    #
    # History, because the round trip is the useful part: this tripwire fired for the first time
    # during the v0.6.0 founder-facing pass and had to be lowered to 9_500 to let delivery-correctness
    # fixes through. That was defensible only because the pre-existing headroom was 10,320 B — the
    # guard had 320 B of slack and would have fired on ANY addition — but it left a debt, recorded
    # here as "shrink the skill, do not lower this again".
    #
    # The debt is now paid, and by a much bigger lever than prose trimming: `cap-table-rules.json`
    # (144,194 B) moved out of `references/` to `skills/cap-table/data/`. The critique packager counts
    # SKILL.md + references/** + agents/<skill>.md and does NOT count scripts/ or sibling data dirs,
    # so relocating a machine-read rule pack that no evaluator needs as evidence removed 28% of the
    # corpus in one move. Headroom went 9,719 -> ~153,800 B at that point (~71% of the ceiling).
    # The assert pins the MARGIN, not any claim about it — which is why it stayed honest while the
    # percentages quoted around it went stale. Read the live number off `_corpus_bytes("cap-table")`.
    #
    # Note this is the ONE relocation that helps. Moving prose from SKILL.md INTO references/ is
    # corpus-neutral (both are packaged), which is why that older advice is retired. Only moving a
    # file OUT of the counted set changes anything.
    assert headroom >= 10_000, (
        f"cap-table's corpus headroom fell to {headroom:,} B ({100 * size / CRITIQUE_CORPUS_CEILING:.0f}% "
        "of the ceiling). Below ~10 KB an ordinary reference addition starts cutting evidence. Shrink "
        "the skill, or move a machine-read data file out of references/ — do not lower this threshold."
    )


@pytest.mark.parametrize("skill", sorted(p.parent.name for p in _skill_md_files()))
def test_description_is_regex_scanner_safe(skill: str) -> None:
    """`description` must read identically under a YAML parser and a naive regex.

    Desktop's skill-discovery scanner is REGEX-based, not a YAML parser, and it
    gates whether the skill is discovered at all — not just what the UI shows. A
    double-quoted description containing escaped quotes (\\") is valid YAML and
    still truncates under a non-greedy `"(.*?)"` match at the first inner quote.

    Measured when this was introduced: financial-model-review's description read
    484 chars anchored-to-EOL and 336 naive — the 148 lost chars were exactly the
    colloquial trigger phrasings added to fix discovery, so the fix would have been
    silently inert on the one surface it targets.

    Rather than guess which parser Desktop uses, remove the dependency: no escaped
    quotes in the value.
    """
    text = (SKILLS_ROOT / skill / "SKILL.md").read_text(encoding="utf-8")
    anchored = re.search(r'^description:\s*"(.*?)"\s*$', text, re.M)
    naive = re.search(r'^description:\s*"(.*?)"', text, re.M)
    assert anchored, f"{skill}: no double-quoted description found"
    assert naive, f"{skill}: description unreadable by a naive regex"
    assert anchored.group(1) == naive.group(1), (
        f"{skill}: description truncates under a naive regex — "
        f"{len(anchored.group(1))} chars vs {len(naive.group(1))}. An escaped quote inside the value "
        "is the usual cause. Use parentheses or commas instead; Desktop's discovery scanner is "
        "regex-based and a truncated description can cost the skill its triggers."
    )


# ---------------------------------------------------------------------------
# AskUserQuestion option-list length
# ---------------------------------------------------------------------------

# The tool schema caps `options` at 4 (minItems 2, maxItems 4). A SKILL.md that
# specifies five cannot be satisfied: the model must drop one to render the gate
# at all, so the spec silently forfeits whichever it drops. That is a skill
# defect the model cannot avoid, and it is invisible until a live run — which is
# exactly how the one instance of it survived into production.
ASKUSER_MAX_OPTIONS = 4

# The fleet declares option sets in FOUR syntactic forms, not one. An earlier
# version of this file read only the first and so checked roughly 8 of the 27
# specs that exist — blind, in particular, to the whole of cap-table's 13-row
# Gate Catalog, which is the largest set in the repo. A test that implies
# coverage it does not have is worse than no test, so every form the fleet
# actually uses is parsed here:
#
#   slash-run   `a` / `b` / `c`            after an `Options:` label
#   pipe-span   `a | b | c`                one backticked span, after `Options:`
#   json-array  "options": ["a", "b"]      deck-review's gate_state bodies
#   table-cell  `a`, `b`, `c`              the `Option labels` column of a table
#
# What is deliberately NOT parsed: option labels narrated in prose (quoted
# strings in a sentence, or an enumeration like "must offer exactly these five:
# Pre-seed (`pre_seed`), Seed (`seed`), …"). Two such specs exist —
# financial-model-review's review-page STOP gate and deck-review's stage_choice
# gate — and both are recorded in
# `docs/internal/2026-08-01-gate-contract-plan.md` §3 as convert-to-a-declared-
# form work, not as detector work. Measured before choosing: the generic shape
# for the quoted-prose form (`"…" / "…"`) matches 11 lines fleet-wide of which 1
# is a gate. That ratio is the enumerated-blocklist trap `cowork-tests/
# leak_scan.py`'s design note describes; the fix is to move the spec into a form
# the parser already reads, which the sibling gates in the same file already use.
_OPTION_ITEM = re.compile(r"\A\s*(`[^`]+`)(?:\s*/\s*(`[^`]+`))*")
_OPTION_SPLIT = re.compile(r"\s*/\s*")
_PIPE_SPAN = re.compile(r"\A\s*`([^`]*\|[^`]*)`")
# The repeated group anchors each element on its own comma. Written as
# `(?:\s*"…"\s*,?)+` the whitespace either side of an absent comma is
# ambiguous, so a line like `options: [ "" "" "" …` with no closing bracket
# backtracks exponentially (measured: 4 more repetitions is ~16x the time).
_JSON_OPTIONS = re.compile(r'\boptions\b\W{0,4}\[(\s*"(?:[^"\\]|\\.)*"(?:\s*,\s*"(?:[^"\\]|\\.)*")*[\s,]*)\]')
_JSON_STRING = re.compile(r'"((?:[^"\\]|\\.)*)"')
_TABLE_LABEL_COLUMN = "Option labels"


def _split_outside_backticks(text: str, sep: str) -> list[str]:
    """Split on `sep`, ignoring separators inside a backtick span.

    Both table forms need this. A label may itself contain the cell's column
    separator (`Yes — I'll provide authorized / issued / unallocated`) or the
    item separator (`Fully-diluted pre-financing (common + options, before new
    money)`), and a naive split turns one option into three.
    """
    parts: list[str] = []
    buf: list[str] = []
    inside = False
    for ch in text:
        if ch == "`":
            inside = not inside
        if ch == sep and not inside:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    parts.append("".join(buf))
    return parts


def _labelled_line_specs(lines: list[str]) -> Iterator[tuple[int, str, str | None, list[str]]]:
    """`Options:`-labelled lines and inline JSON `options` arrays."""
    for i, line in enumerate(lines):
        idx = line.find("Options:")
        if idx != -1:
            # Join to the end of the paragraph so a wrapped list is seen whole.
            chunk = [line[idx + len("Options:") :]]
            for nxt in lines[i + 1 :]:
                if not nxt.strip():
                    break
                chunk.append(nxt)
            joined = " ".join(chunk)
            pipes = _PIPE_SPAN.match(joined)
            if pipes:
                yield i + 1, "pipe-span", None, [f"`{p.strip()}`" for p in pipes.group(1).split("|")]
                continue
            run = _OPTION_ITEM.match(joined)
            if run:
                span = run.group(0).strip()
                yield (
                    i + 1,
                    "slash-run",
                    None,
                    [p for p in _OPTION_SPLIT.split(span) if p.startswith("`")],
                )
                continue
        arr = _JSON_OPTIONS.search(line)
        if arr:
            yield i + 1, "json-array", None, [f"`{s}`" for s in _JSON_STRING.findall(arr.group(1))]


def _table_specs(lines: list[str]) -> Iterator[tuple[int, str, str | None, list[str]]]:
    """Rows of any markdown table carrying an `Option labels` column.

    The row's first cell is used as the spec's stable name — line numbers move
    whenever anything above the table is edited, so an exemption or a report
    keyed on a line number would rot on the next unrelated commit.
    """
    column: int | None = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped.startswith("|"):
            column = None
            continue
        cells = [c.strip() for c in _split_outside_backticks(stripped.strip("|"), "|")]
        if column is None:
            if _TABLE_LABEL_COLUMN in cells:
                column = cells.index(_TABLE_LABEL_COLUMN)
            continue
        if set("".join(cells)) <= set("-: "):  # the header underline row
            continue
        if column >= len(cells):
            continue
        options = []
        for segment in _split_outside_backticks(cells[column], ","):
            first = re.search(r"`([^`]+)`", segment)
            if first:
                options.append(f"`{first.group(1)}`")
        # A zero-backtick cell is yielded, NOT skipped. An earlier version skipped it on
        # the theory that "no backticks means the row documents a shape, not labels" —
        # which is true of the one row it was written for and false as a class rule. It
        # deleted the detector for the exact defect this whole effort exists to fix: the
        # Qualified-financing row read `free-text (deal-specific — no fixed labels)`, a
        # zero-backtick cell, and under that skip it would have regressed silently. A
        # deliberate shape row belongs in ARITY_EXEMPT by name, where it is one auditable
        # line, not behind a class-wide rule that cannot tell it from a regression.
        yield i + 1, "table-cell", cells[0].strip("* "), options


def _option_specs(text: str) -> Iterator[tuple[int, str, str | None, list[str]]]:
    """Yield (1-indexed line, form, spec name or None, options) for every spec."""
    lines = text.splitlines()
    yield from _labelled_line_specs(lines)
    yield from _table_specs(lines)


def _option_lists(text: str) -> Iterator[tuple[int, list[str]]]:
    """Back-compatible view: (line, options), all forms."""
    for line_no, _form, _name, options in _option_specs(text):
        yield line_no, options


# The no-change branch must be identifiable without counting positions. Measured
# across four live competitive-positioning runs, slot 1 was the accept branch on
# two and an adds-competitors branch on two, while every option still opened
# "Looks good" — so neither position nor a shared prefix is a safe handle. A
# prefix RESERVED to the no-change branch is.
#
# The rule has two halves, and conflating them is a design error that was caught
# in review before it shipped fleet-wide:
#
#   at-most-one, EVERY skill — the token is reserved; no option that mutates
#       state may carry it. This is the whole point, and it does not require a
#       no-change branch to exist.
#   exactly-one, CONFIRM-GATES ONLY — gates that offer a proceed-unchanged path.
#
# "Exactly one, everywhere" conflates uniqueness with existence, and it is wrong
# for DATA-ENTRY gates, which have no legitimate no-change branch: cap-table's
# stage / jurisdiction / IIA rows, deck-review's `stage_choice` (every option
# mutates), financial-model-review's context batches. Asserting exactly-one on
# those makes the only route to green *inventing* a fake "No changes — " option
# on a gate that asks for a fact — the failure being prevented, inverted. It is
# latent today only because competitive-positioning's six declared gates all
# happen to be confirm-gates.
NO_CHANGE_PREFIX = "No changes — "

# `cowork-harness` reinforces at-most-one at runtime for free, which is worth
# knowing before anyone weakens it: a scripted `choose:` anchor is a
# boundary-anchored `startsWith` that is uniqueness-guarded and **fails loud when
# the anchor matches two options** (harness CHANGELOG, `--decider-model` release).
# So `choose: "No changes"` in a scenario is itself an at-most-one assertion on
# what the model emitted — the half of the invariant no file-reading test can
# observe.

# Which skills have adopted the reserved prefix. Scoped rather than fleet-wide on
# purpose: the other five have not been through the live-run measurement that
# justifies it, and asserting it on them would be a rule nobody validated.
NO_CHANGE_PREFIX_SKILLS = frozenset({"competitive-positioning"})


# The schema's lower bound is as real as its upper one: a one-option gate cannot
# render either, and one shipped. Enforced alongside the maximum, with a single
# named exemption.
ASKUSER_MIN_OPTIONS = 2

# Specs knowingly outside 2..4, by (skill, spec name). Keyed on the spec's own
# name rather than a line number so an unrelated edit above it cannot silently
# move the exemption onto a different gate.
#
# The Qualified-financing entry that used to live here is GONE — Phase 2 fixed that
# row (it now carries three bracket labels), and leaving its exemption behind would
# have masked a regression of the exact defect the fix removed. Verified by mutation:
# with the stale entry present, reverting that row to one option passed silently.
# The lesson generalises — an exemption outlives the defect it documents unless
# removing it is part of the fix.
#
# The single remaining entry is NOT a defect. It is the deliberate shape row, named
# here rather than handled by a class-wide parser rule, so that "this row documents a
# shape" is one auditable line instead of a silent skip that cannot tell a shape row
# from a regressed spec.
ARITY_EXEMPT: dict[tuple[str, str], str] = {
    ("cap-table", "Founder-only fact gates (general shape)"): (
        "not a defect and not a spec — a catalog row documenting the SHAPE shared by the "
        "founder-supplied-fact gates (a stated-value option, a different-value option, an "
        "explicit defer). Its label cell deliberately carries no backticked strings because "
        "the labels are runtime data. Exempt by name so a genuinely regressed row — one that "
        "lost its labels — still fails."
    ),
}


@pytest.mark.parametrize("skill", sorted(SKILL_MD_CEILING))
def test_askuserquestion_option_lists_fit_the_tool_schema(skill: str) -> None:
    """Every declared option spec must be renderable: 2 to 4 options.

    Reads all four declared forms (see `_option_specs`). KNOWN BLIND SPOT,
    stated rather than papered over: option labels narrated in PROSE are not
    parsed, and two such specs exist today — one of them, deck-review's
    `stage_choice`, mandates FIVE options and so is an unrenderable spec this
    test cannot see. Both are logged in the gate-contract plan for conversion
    into a declared form, which is the fix that also makes them visible here.
    Teaching this test to parse sentences is the enumerated-blocklist trap the
    repo has already lost once (`cowork-tests/leak_scan.py`'s design note).
    """
    path = SKILLS_ROOT / skill / "SKILL.md"
    bad = [
        (line_no, name, opts)
        for line_no, _form, name, opts in _option_specs(path.read_text(encoding="utf-8"))
        if not ASKUSER_MIN_OPTIONS <= len(opts) <= ASKUSER_MAX_OPTIONS and (skill, name or "") not in ARITY_EXEMPT
    ]
    assert not bad, (
        f"{skill}/SKILL.md declares an unrenderable option set at "
        + "; ".join(
            f"line {ln}{f' ({nm})' if nm else ''} — {len(o)} option(s): {' / '.join(o) or '(none)'}"
            for ln, nm, o in bad
        )
        + f". AskUserQuestion renders {ASKUSER_MIN_OPTIONS}-{ASKUSER_MAX_OPTIONS} options. Over the "
        "maximum the model must drop one, so the spec does not add a choice — it forfeits an "
        "unpredictable one; under the minimum the gate cannot be raised at all. A catch-all 'Other' "
        "is never needed: the tool always offers free-text Other of its own."
    )


def _carriers(options: list[str]) -> int:
    """How many options carry the reserved prefix.

    Dash-normalized before comparing. The prefix ends in an em-dash, and a
    hyphen or en-dash in its place is a typo, not a different rule — matching
    the exact codepoint would let one through as "carries zero" and fail, or
    pass, for the wrong reason.
    """
    return sum(1 for o in options if re.sub(r"[-–—]", "—", " ".join(o.strip("`").split())).startswith(NO_CHANGE_PREFIX))


@pytest.mark.parametrize("skill", sorted(SKILL_MD_CEILING))
def test_no_change_prefix_is_reserved_fleet_wide(skill: str) -> None:
    """AT MOST one option per gate may carry the prefix — in every skill.

    The reserved half of the rule, which needs no live-run measurement to
    justify: whatever the prefix means, two options cannot both be the
    no-change branch. Applies fleet-wide because it constrains what a *mutating*
    option may be called, and that is the same in all six skills.

    Existence (exactly-one) is a separate, stronger claim asserted only for
    skills in `NO_CHANGE_PREFIX_SKILLS` — see the note above the constant for
    why extending it to a data-entry gate is a design error.
    """
    text = (SKILLS_ROOT / skill / "SKILL.md").read_text(encoding="utf-8")
    bad = [(line_no, name, n, opts) for line_no, _form, name, opts in _option_specs(text) if (n := _carriers(opts)) > 1]
    assert not bad, (
        f"{skill}/SKILL.md: more than one option carries the reserved prefix {NO_CHANGE_PREFIX!r} at "
        + "; ".join(f"line {ln}{f' ({nm})' if nm else ''} — {n} of {len(o)}: {' / '.join(o)}" for ln, nm, n, o in bad)
        + ". The prefix is reserved to the branch that changes nothing, so a second carrier makes it "
        "useless as a handle and invites a confident wrong match — measured worse than open drift. "
        "Any option that adds, removes, re-categorises, changes an axis or changes a scoring basis is "
        "forbidden from it."
    )


# The confirm-gate marker Phase 2 deferred until a real case arrived — one now has, twice, in the same
# skill. competitive-positioning's founder-context gate now DECLARES a real stage label set (`Pre-seed`
# / `Seed` / `Series A` / `Series B+`), which is correct and valuable — but it is a DATA-ENTRY gate (it
# collects a fact; nothing about picking a stage is "no change"), so it has zero carriers and would trip
# exactly-one. The alternative — reverting the stage declaration back to unparseable prose just to keep
# this test naive — throws away real Phase 2 progress to avoid building a five-line exemption. Keyed on
# the spec's FIRST option label rather than a line number, matching `ARITY_EXEMPT`'s reasoning: line
# numbers move whenever unrelated content above them changes; a first label does not.
#
# This is NOT a general "mark every non-confirm-gate" mechanism — it is the minimal fix for the specific
# collision the stage rollout created within the one skill currently in `NO_CHANGE_PREFIX_SKILLS`. A
# skill-wide confirm/data-entry classifier is still Phase 2 design work if `NO_CHANGE_PREFIX_SKILLS`
# grows to a skill with a genuine mix — this only unblocks the skill already in scope.
NO_CHANGE_PREFIX_EXEMPT: dict[tuple[str, str], str] = {
    ("competitive-positioning", "Pre-seed"): (
        "founder-context stage question — a data-entry gate (collects a fact), not a confirm-gate "
        "(offers a proceed-unchanged path). No option here can legitimately mean 'no change'."
    ),
}


@pytest.mark.parametrize("skill", sorted(NO_CHANGE_PREFIX_SKILLS))
def test_no_change_option_is_reserved_and_unique(skill: str) -> None:
    """Exactly one option per gate carries the reserved no-change prefix.

    CONFIRM-GATES ONLY. Do not add a skill here because its labels look ready:
    every gate in the added skill must offer a proceed-unchanged path, and a
    data-entry gate does not. cap-table would red ~10 gates at once, and the
    only route back to green would be inventing a fake no-change option on a
    gate that asks for a fact. `NO_CHANGE_PREFIX_EXEMPT` above carves out the
    known data-entry gates within an already-scoped skill; it does not widen
    the scope itself. Widening `NO_CHANGE_PREFIX_SKILLS` to a skill with a
    genuine confirm/data-entry mix still needs real design work, not more
    exemption entries.
    """
    path = SKILLS_ROOT / skill / "SKILL.md"
    text = path.read_text(encoding="utf-8")
    bad: list[str] = []
    seen_any = False
    for line_no, _form, _name, opts in _option_specs(text):
        first = opts[0].strip("`") if opts else ""
        if (skill, first) in NO_CHANGE_PREFIX_EXEMPT:
            continue
        n = _carriers(opts)
        seen_any = seen_any or n > 0
        if n != 1:
            bad.append(f"line {line_no}: {n} of {len(opts)} carry it — {' / '.join(opts)}")
    assert not bad, (
        f"{skill}/SKILL.md: every gate needs EXACTLY one option prefixed "
        f"{NO_CHANGE_PREFIX!r}.\n  " + "\n  ".join(bad) + "\nZero leaves the no-change branch "
        "unidentifiable except by position, which live runs show is not stable. More than one "
        "re-creates the failure being prevented — a gate where several options read as 'no change' "
        "while some of them mutate the set. If this is a genuine data-entry gate, add it to "
        "NO_CHANGE_PREFIX_EXEMPT with a reason rather than fabricating a no-change option."
    )
    assert seen_any, f"{skill} is registered for the reserved prefix but no gate uses it."


# ---------------------------------------------------------------------------
# Gate-label coverage — REPORTED, and `unspecified` IS ENFORCED (assert unspec == 0 below).
# The header said NOT ENFORCED long after the enforcement landed, and an audit read the
# header, stopped, and filed a false 'this is unenforced' finding off it.
# ---------------------------------------------------------------------------

# Hand-read inventory of every AskUserQuestion call site in the six SKILL.mds,
# from `docs/internal/2026-08-01-gate-contract-plan.md` §3, which carries the
# file:line citation for each entry. Names, not line numbers: three sessions are
# editing these files concurrently and a line-keyed constant rots on the next
# unrelated commit.
#
# Distinguishing a call SITE from a mere mention of the tool cannot be done
# mechanically — six of the ~30 `AskUserQuestion` occurrences fleet-wide are
# prohibitions ("this is NOT an AskUserQuestion call", "NEVER raise one for it")
# and would count as sites under any grep. So this is a read, and the read is
# the authority. What the parser gives us is the other half: the specs. The two
# counts are NOT expected to match, for two structural reasons — cap-table's
# Gate Catalog is one shared spec table serving several sites (and duplicating
# two of them inline as enum tokens), and deck-review declares one gate twice
# (heredoc body plus needs_input payload).
#
# Status values — FOUR now, not three. `runtime-labelled` and `exempt` were added during Phase 2
# (`docs/internal/2026-08-01-gate-contract-plan.md` §3(c-bis)/step 8), because forcing every site into
# declared/prose/unspecified was itself dishonest: a proper noun, a dollar amount, or a founder's own
# company name cannot take a fixed label, and pretending otherwise (or leaving it "unspecified", which
# reads as "nobody looked") both misreport the real state.
#   declared         — labels given in a form `_option_specs` parses
#   prose            — labels given, but only narrated in a sentence (invisible here)
#   runtime-labelled — labels are inherently founder/document-specific data (a name, a date, a dollar
#                      figure) — no fixed label set can exist; the SHAPE (affirmative-carries-derived-
#                      value + stated-value fallback, or an explicit defer) is what's specified instead
#   exempt           — one-off, document-dependent gates the Gate Catalog's own stated policy excludes
#                      from recurring canonical phrasing (`cap-table/SKILL.md:798`); permanently out of
#                      scope, not a gap awaiting a future pass
#   unspecified      — no labels AND no documented shape; the model improvises every run
#
# Phase 2 (2026-08-01) moved most sites out of `unspecified` fleet-wide. What's left in that bucket is
# real remaining work, not a rounding error — see the per-skill notes below.
GATE_SITES: dict[str, dict[str, tuple[str, ...]]] = {
    "market-sizing": {
        "declared": (
            "methodology confirmation",
            "methodology-change follow-up",
            "founder-context init — stage",
        ),
        "prose": ("percent-scale question (Step 5.5)", "revision question (Step 6d)"),
        "runtime-labelled": (
            "founder-context init — name/sector/geography",
            "data-correction follow-up",
            "revision changes follow-up (Step 6d)",
            "two-figures question (Steps 2-3)",
        ),
        "exempt": (),
        "unspecified": (),
    },
    "deck-review": {
        "declared": (
            "stage_confirmation",
            "out_of_scope_choice",
            "founder-context init — stage",
            # Recorded gates whose words are the registry's, asked from the `needs_input` a script prints.
            "company picker (ctx_select_company)",
            "stage follow-up (ctx_stage_detail)",
            "primary deck (dr_primary_deck)",
            "deck re-request (dr_input_request x5)",
        ),
        "prose": ("stage_choice",),  # STAYS prose — runtime-selected, no static array; see §3(c-bis).
        "runtime-labelled": ("founder-context init — name/sector/geography",),
        "exempt": (),
        "unspecified": (),
    },
    "ic-sim": {
        # 2026-10-08: the mode and fund questions (Mode Selection, opened in Step 1's block) are recorded gates
        # with Options: lines; the picker and the stage follow-up are asked from the `needs_input` a script prints.
        "declared": (
            "decline-delivery confirmation",
            "founder-context init — stage",
            "mode (ic_mode)",
            "fund (ic_fund_mode)",
        ),
        "prose": (),
        "runtime-labelled": (
            "founder-context init — name/sector/geography",
            "company picker (ctx_select_company)",
            "stage follow-up (ctx_stage_detail)",
        ),
        "exempt": (),
        "unspecified": (),
    },
    "financial-model-review": {
        # 2026-10-07: the review-page STOP and the Path B confirmation are one recorded gate; the cash and
        # company questions are recorded gates too, asked from the `needs_input` a script prints.
        "declared": (
            "extracted-values review (fmr_extracted_values)",
            "founder-context init — stage",
        ),
        "prose": (),
        "runtime-labelled": (
            "founder-context init — name/sector/geography",
            "cash balance / date / burn (fmr_cash_basics)",
            "company picker (ctx_select_company)",
            "cash follow-up (fmr_cash_followup)",
        ),
        "exempt": (),
        "unspecified": (),
    },
    "competitive-positioning": {
        "declared": (
            "Gate 1 competitor set",
            "additions — fit within slots",
            "additions — partial fit",
            "additions — set full, merge candidate",
            "Gate 2 axis pair",
            "Gate 3 positioning reality check",
            "founder-context init — stage",
        ),
        # 2026-10-08: the scoring-basis follow-up (once parked as prose: a declared Options: line has no
        # no-change branch) and the documents question are recorded gates whose words are the registry's,
        # asked from the `needs_input` a script prints, as are the company and stage follow-ups.
        "prose": (),
        "runtime-labelled": (
            "founder-context init — name/sector/geography",
            "product questions (cp_product_profile x3)",
            "which-additions-by-name follow-up (cp_research_pick)",
            "consolidation merge (cp_consolidation_merge)",
            "merge pick (cp_merge_pick)",
            "scoring basis (cp_scoring_basis)",
            "outside-review documents (cp_upload_path)",
            "company picker (ctx_select_company)",
            "stage follow-up (ctx_stage_detail)",
        ),
        "exempt": (),
        "unspecified": (),
    },
    "cap-table": {
        "declared": (
            "existing-review routing",
            "engagement mode",
            "jurisdiction structure (Step 2)",
            "IIA grant history (Step 2)",
            "cap-base confirmation",
            "no-cap-base fork",
            "scenario selection",
            "tracked-changes DOCX guard",  # was prose; converted to a real Options: line
            "founder-context init — stage",
            "extraction confirm-gate batch — interest rate type / converts-to-shares",
            "fast-assess batched gate — jurisdiction / IIA / pool top-up",
            "fast-assess batched gate — pool-top-up basis follow-up",
            "§102 per-grant tax route",
            "Lane-1 pre-math confirmation",  # points at the cap-base confirm-or-correct pair
        ),
        "prose": (),
        "runtime-labelled": (
            "founder-context init — name/sector/geography",
            "missing issuance_date",
            "extraction confirm-gate batch — other assumed fields",
            "blank-template relaxed gate",
            "Lane-2 founders + pool batch",
        ),
        # EMPTY, and the emptiness is the honest answer. An earlier pass put the two Lane-1/Lane-2
        # sites above in here, citing the catalog's one-off-gate policy. Re-read, that policy names
        # "Lane-1 counsel-review, Lane-2 column mapping, Lane-3 blockers" — and neither site is any of
        # those three. Lane-2's founders+pool batch in particular RECURS in a stable three-part shape
        # (founders, share counts, pool split), which is the opposite of the policy's stated reason.
        # That was coverage-by-analogy presented as citation. The three gates the policy really names
        # live in `references/lanes/*.md`, outside this inventory's scope, so no SKILL.md site is
        # genuinely exempt. The key stays so the bucket exists if one ever is.
        "exempt": (),
        "unspecified": (),
    },
}

# Exact `AskUserQuestion` occurrence count per SKILL.md, as of the read that
# produced GATE_SITES. This is the tripwire that binds that hand-maintained
# constant to file content, and without it the coverage metric is self-certifying:
# GATE_SITES is name-keyed and structurally disconnected from the files, so a gate
# added later never enters it and a removed one never leaves. Flipping coverage to
# enforced with nothing but GATE_SITES behind it would enforce that a constant's
# tuples are empty — satisfiable without touching a SKILL.md at all.
#
# EXACT, not a floor, and deliberately so: a floor cannot catch a REMOVED gate,
# and drift in that direction is the one that silently inflates the coverage
# percentage. A red here is a reconciliation prompt, not a defect — if you added
# or removed an `AskUserQuestion` mention, update this number AND the matching
# GATE_SITES bucket in the same commit. Counting mentions rather than call sites is
# intentional: mentions are mechanical, and distinguishing a site from a
# prohibition needs a read (six of these occurrences are prohibitions).
#
# deck-review 5 -> 6: the `stage_choice` arity fix at `:377` added a MENTION, not a site — it cites
# the tool's four-option limit as the reason the gate offers a subset of the `--rebuild-stage` enum.
# Read done: `stage_choice` was already inventoried and stays in the `prose` bucket, so GATE_SITES is
# deliberately unchanged. It must STAY prose — the offered four are computed per run from the current
# profile, so there is no static array for the arity parser to read.
#
# Phase 2 sweep (2026-08-01), all six re-read against `docs/internal/2026-08-01-gate-contract-plan.md`
# §5.1 — the mention deltas below are new gate-labelling work, not drift:
#   market-sizing 6->7: the METHODOLOGY-CHANGE follow-up now names `AskUserQuestion` explicitly (it was
#     "Ask which approach they prefer (top-down / bottom-up / both)" — prose, no tool named). An earlier
#     version of this comment credited the data-correction follow-up instead; that was wrong, and the
#     count was right for the wrong reason. Both follow-ups are now real gates in GATE_SITES; only this
#     one added a mention.
#   ic-sim 4->4: unchanged — the stage-label edit reused the site's existing sentence.
#   financial-model-review 7->8: the Exit-2 company-picker site now names the tool explicitly (was
#     bare "ask which company" with no mention at all).
#   competitive-positioning 9->9: unchanged — all edits reused existing sentences or stayed prose.
#   cap-table 19->19: unchanged net — `:488`-`:490` dropped 3 restated mentions in favor of pointing at
#     the Gate Catalog, offset by mentions added across the new/expanded catalog rows and their sites.
#   deck-review 6->6: unchanged — the stage-label edit reused the site's existing sentence.
#   cap-table 19->23 (2026-08-02): +4 from the host-precedence paragraph added above the S2 gate. A live
#     Cowork run surfaced that the host's own prompt steers skill ARGUMENT COLLECTION toward an
#     elicitation widget and away from AskUserQuestion, which collides with S2 mandating it. The agent
#     resolved it correctly on judgement; the paragraph makes the precedence explicit (a mandatory
#     correctness gate uses AskUserQuestion regardless) and adds the missing no-AskUserQuestion fallback,
#     since a mandatory gate with no fallback is a hard stall. NO new gate SITE was added — GATE_SITES is
#     unchanged; these are mentions in one prose block about an existing site.
#   ALL FIVE non-cap-table skills +1 (2026-08-02): the P1 tool-unavailable fallback clause. Five
#     skills banned asking in plain chat (`(NOT plain chat)` / "never ask as plain chat text") with no
#     stated alternative, so on a host lacking AskUserQuestion a literal reading had no permitted way
#     to ask — a hard stall, i.e. no report at all. The clause is availability-keyed so the
#     tool-available ban (anti-lazy-model: do not dump questions in chat) is preserved. NO new gate
#     SITE — verified: each skill's Gate Catalog row count is unchanged; these are mentions inside
#     prose about gates that already existed.
#   market-sizing 9->10 (2026-09-24): ONE new gate SITE, Step 5.5's percent-scale question. It used
#     to be asked at Step 7, after the adversarial review had already seen the unanswered figure; asked
#     there, a changed answer revised an analysis that had been reviewed. Labels are narrated in the
#     sentence (option 1 = the value as given), so it goes in the `prose` bucket.
#   market-sizing 10->11 (2026-09-24): Step 6d, one mention, TWO new gate sites -- the revision question
#     (labels narrated: `prose`) and its follow-up listing the proposed changes (one option per change,
#     built from this run's figures: `runtime-labelled`).
#   market-sizing 11->12 (2026-09-24): ONE new gate SITE, the two-figures question before Step A --
#     one option per founder figure, each naming its source: `runtime-labelled`.
#   deck-review 7->6 (2026-10-03): a MENTION, not a site. The stage gate's execution note no longer says
#     "sub-agents in Cowork cannot reliably call AskUserQuestion" -- the skill runs inline and asks
#     itself. The gate site is unchanged; GATE_SITES is unchanged.
ASKUSER_MENTIONS: dict[str, int] = {
    "market-sizing": 12,
    # deck-review 6 -> 7 on 2026-10-03: a MENTION, not a site. The stage gate's post-emit sentence now says to
    # ask with AskUserQuestion instead of returning JSON to a parent; it is the stage_confirmation /
    # out_of_scope_choice gate already counted in GATE_SITES, which is unchanged.
    "deck-review": 7,
    "ic-sim": 5,
    "financial-model-review": 9,
    "competitive-positioning": 10,
    "cap-table": 23,
}

# Per-skill floor on how many specs the parser can see. Not a target and not an
# exact match: a floor catches the failure that made the previous version of
# this file misleading — a spec drifting into a form the parser no longer reads,
# which looks identical to a green. Additions are free; a drop is a red.
SPECS_VISIBLE_FLOOR: dict[str, int] = {
    "market-sizing": 3,
    "deck-review": 4,
    # 2 -> 3 (2026-10-08): Mode Selection's recorded gates (ic_mode, ic_fund_mode) carry Options: lists; the two
    # share one line, which the parser reads as one spec.
    "ic-sim": 3,
    # 3 -> 2 (2026-10-07): Step 3.6's two sites (the review-page STOP, the Path B confirmation) are one recorded
    # gate, fmr_extracted_values, asked with one Options: line on either path.
    "financial-model-review": 2,
    "competitive-positioning": 7,
    "cap-table": 23,
}


@pytest.mark.parametrize("skill", sorted(SKILL_MD_CEILING))
def test_declared_option_specs_stay_visible_to_the_parser(skill: str) -> None:
    """A spec must not drift into a form this file cannot read.

    The failure being guarded is not "a spec is wrong" but "a spec became
    invisible" — which presents as a passing test with less coverage than
    yesterday, and is how the Gate Catalog's 13 specs went unchecked.
    """
    text = (SKILLS_ROOT / skill / "SKILL.md").read_text(encoding="utf-8")
    found = list(_option_specs(text))
    floor = SPECS_VISIBLE_FLOOR[skill]
    assert len(found) >= floor, (
        f"{skill}/SKILL.md: {len(found)} parseable option specs, was {floor}. Either a gate was "
        "removed (lower the floor in the same commit, and say which gate) or a spec was reworded "
        "into a form the parser cannot read — the second is the dangerous one, because it looks "
        "exactly like a green. Declared forms: " + ", ".join(sorted({f for _, f, _, _ in found})),
    )


@pytest.mark.parametrize("skill", sorted(SKILL_MD_CEILING))
def test_gate_inventory_is_pinned_to_file_content(skill: str) -> None:
    """A changed gate count must force a GATE_SITES reconciliation.

    The companion to the coverage metric. `GATE_SITES` is a read, and a read
    goes stale silently — this is the only thing that makes it notice.
    """
    text = (SKILLS_ROOT / skill / "SKILL.md").read_text(encoding="utf-8")
    found = text.count("AskUserQuestion")
    expected = ASKUSER_MENTIONS[skill]
    assert found == expected, (
        f"{skill}/SKILL.md mentions `AskUserQuestion` {found} times, pinned at {expected}. This is a "
        "reconciliation prompt, not a defect: if you added or removed a gate, re-read the site and "
        "update BOTH `ASKUSER_MENTIONS` and the matching `GATE_SITES` bucket in this commit. If the "
        "change was to a MENTION and not a site (a prohibition, a cross-reference), update the count "
        "alone and say so. Do not update the count to make the suite green without doing the read — "
        "the coverage number is only worth what that read is worth."
    )


def test_gate_label_coverage_is_reported(capsys: pytest.CaptureFixture[str]) -> None:
    """Report the gate-label breakdown, AND enforce zero `unspecified` — flipped 2026-08-01.

    Phase 2 of the gate-contract plan specified the unspecified gates; this is
    the flip the plan's step 9 called for. What is enforced is narrower than it
    might look: only that `unspecified` is empty fleet-wide. `prose` and
    `runtime-labelled` are NOT failure states — deck-review's `stage_choice`
    stays prose forever by design (its options are computed per run, no static
    array exists to declare), and `runtime-labelled` gates (a founder's own
    name, a dollar figure) cannot take fixed labels by construction. Only
    `unspecified` — no labels AND no documented shape — is the thing this
    fixes. Demanding zero `prose` would be wrong; it would either force a
    fabricated declaration onto a genuinely dynamic gate, or motivate someone
    to misclassify one as `runtime-labelled` to dodge the count.

    The internal-consistency checks (every skill present, every bucket a real
    key) still run first — a silently half-filled table would make either
    number meaningless.
    """
    rows: list[tuple[str, int, int, int, int, int]] = []
    for skill in sorted(SKILL_MD_CEILING):
        assert skill in GATE_SITES, (
            f"{skill} is missing from GATE_SITES. Every skill must appear, with an empty tuple "
            "where a status has no members — a missing key reads as zero gates."
        )
        buckets = GATE_SITES[skill]
        expected_keys = {"declared", "prose", "runtime-labelled", "exempt", "unspecified"}
        assert set(buckets) == expected_keys, (
            f"{skill}: GATE_SITES buckets are {sorted(buckets)}, expected {sorted(expected_keys)}."
        )
        declared, prose, rtl, exempt, unspec = (
            len(buckets[k]) for k in ("declared", "prose", "runtime-labelled", "exempt", "unspecified")
        )
        assert unspec == 0, (
            f"{skill}: {unspec} gate site(s) still unspecified — {buckets['unspecified']}. "
            "Give each a real shape (declared labels, a documented runtime-labelled shape, or an "
            "explicit exempt classification per the Gate Catalog's one-off-gate policy) before it can "
            "leave this bucket. This is the assertion Phase 2 step 9 flipped on; it enforces only "
            "`unspecified == 0`, never `prose == 0` — see the docstring for why the two are not the "
            "same claim."
        )
        rows.append((skill, declared, prose, rtl, exempt, declared + prose + rtl + exempt + unspec))

    total_declared = sum(r[1] for r in rows)
    total_prose = sum(r[2] for r in rows)
    total_rtl = sum(r[3] for r in rows)
    total_exempt = sum(r[4] for r in rows)
    total_sites = sum(r[5] for r in rows)
    with capsys.disabled():
        print("\n  gate-label coverage (unspecified == 0 enforced fleet-wide;")
        print("  prose / runtime-labelled / exempt are NOT failure states)")
        print(f"  {'skill':<24}{'declared':>9}{'prose':>7}{'rt-lbl':>7}{'exempt':>7}{'sites':>7}")
        for skill, declared, prose, rtl, exempt, sites in rows:
            print(f"  {skill:<24}{declared:>9}{prose:>7}{rtl:>7}{exempt:>7}{sites:>7}")
        print(f"  {'FLEET':<24}{total_declared:>9}{total_prose:>7}{total_rtl:>7}{total_exempt:>7}{total_sites:>7}")
        print("  unspecified == 0 fleet-wide: enforced. Both remaining `prose` entries are deliberate:")
        print("  deck-review stage_choice is runtime-SELECTED (no static array can exist), and")
        print("  competitive-positioning's scoring-basis follow-up has no no-change branch to declare.")


# The Step 0 preflight is fleet-shared prose, for the same reason the delivery block is: it is one
# rule about the runtime, and a copy that drifts is a skill that runs where the others stop.
PREFLIGHT_LINE = (
    '[ -f "$SHARED_SCRIPTS/check_handoff.py" ] || echo "UNSUPPORTED_ENVIRONMENT: '
    "the plugin's shared scripts are not reachable from here\""
)


@pytest.mark.parametrize("skill", sorted(SKILL_MD_CEILING))
def test_every_skill_preflights_the_environment(skill: str) -> None:
    """A surface that serves the skill without its plugin must stop the run, not degrade it.

    MEASURED 2026-09-22 on claude.ai, which mounts skills flat at
    `/mnt/skills/plugins/<plugin>:<skill>/`: `${SCRIPTS%/skills/*}` yields `/mnt`, the shared
    scripts are absent and no sub-agent can be dispatched. market-sizing ran anyway -- it
    hand-wrote every hand-off file, graded its own checklist 81.8%, dispatched no adversary, and
    delivered a report that reads exactly like a checked one.
    """
    text = (SKILLS_ROOT / skill / "SKILL.md").read_text(encoding="utf-8")
    assert PREFLIGHT_LINE in text, f"{skill}/SKILL.md lost the Step 0 environment preflight"
    assert "UNSUPPORTED_ENVIRONMENT" in text.split("### Step 1")[0], (
        f"{skill}/SKILL.md must preflight in Step 0, before any work"
    )
    stop = text[text.index("UNSUPPORTED_ENVIRONMENT") :]
    assert "stop here" in stop[:2000], f"{skill}/SKILL.md prints the marker but never says to stop"


# The delivery block is fleet-shared prose. It is guarded by a test rather than by
# convention because "mirror it identically across all six" has already failed
# silently in this repo once: the narration rule is described as byte-identical
# fleet-wide and is not (measured lengths 1945-2300, every hash different, and one
# of its sentences present in only two of six skills).
DELIVERY_BLOCK_ANCHOR = "**Send the finished work to the founder — the complete set, as files.**"


DELIVERY_BLOCK_END = "nothing outside the run that made them."


def _delivery_block(text: str) -> str:
    """The shared block, INCLUDING its final sentence.

    The end marker is included deliberately. An exclusive slice left the last
    sentence outside every check, so a byte-neutral edit placed just after the
    marker -- e.g. naming a delivery tool -- passed all three tests. It could
    not survive an *additive* edit (SKILL_MD_CEILING pins size in both
    directions), but a substitution evaded the lot.
    """
    start = text.index(DELIVERY_BLOCK_ANCHOR)
    end = text.index(DELIVERY_BLOCK_END, start) + len(DELIVERY_BLOCK_END)
    return text[start:end]


@pytest.mark.parametrize("skill", sorted(SKILL_MD_CEILING))
def test_every_skill_instructs_delivery(skill: str) -> None:
    """Every skill must hand its deliverables over, not just write them.

    Before this landed, `grep -rn "SendUserFile|present_files|device_commit_files"`
    over all six SKILL.mds returned zero matches: every skill delivered by LOCATION.
    On Cowork's cloud lane -- the default for new sessions -- location delivers
    nothing, so the founder could be handed a path into a reclaimed workspace.
    """
    text = (SKILLS_ROOT / skill / "SKILL.md").read_text(encoding="utf-8")
    assert DELIVERY_BLOCK_ANCHOR in text, (
        f"{skill}/SKILL.md does not instruct delivery. Every skill must send its "
        f"finished deliverables to the founder, not merely write them to a path."
    )


def test_delivery_block_is_identical_fleet_wide() -> None:
    """The shared block must be byte-identical, not merely present."""
    blocks = {
        s: _delivery_block((SKILLS_ROOT / s / "SKILL.md").read_text(encoding="utf-8")) for s in sorted(SKILL_MD_CEILING)
    }
    reference_skill, reference = next(iter(blocks.items()))
    for skill, block in blocks.items():
        assert block == reference, (
            f"{skill}'s delivery block has drifted from {reference_skill}'s. "
            f"This block is shared prose; edit one and re-copy to all six. "
            f"({len(block)} bytes vs {len(reference)})"
        )


@pytest.mark.parametrize("skill", sorted(SKILL_MD_CEILING))
def test_delivery_block_names_no_delivery_tool(skill: str) -> None:
    """Naming either tool strands a lane, so NO SKILL.md may name either.

    Scanned over the whole file, not just the delivery block: a block-bounded
    scan left everything after the block's last sentence unchecked, so a tool
    name placed one sentence later passed. The invariant is file-wide anyway --
    there is nowhere in a SKILL.md where naming a lane-specific delivery tool
    is correct.

    Desktop-local Cowork serves `mcp__cowork__present_files`; remote/cloud Cowork
    serves the agent-native `SendUserFile`, plus an `mcp__remote-devices__` tool for
    a connected folder. A skill naming one is wrong on another surface, so the
    instruction describes the OUTCOME and lets the agent use whatever it has.
    """
    text = (SKILLS_ROOT / skill / "SKILL.md").read_text(encoding="utf-8")
    for tool in ("SendUserFile", "present_files", "device_commit_files"):
        assert tool not in text, (
            f"{skill}/SKILL.md names `{tool}`. Naming either delivery tool strands "
            f"the other lane -- describe the outcome instead."
        )


@pytest.mark.parametrize("skill", sorted(SKILL_MD_CEILING))
def test_no_step_instructs_presenting_a_path_as_the_handoff(skill: str) -> None:
    """No step may tell the model to hand the founder a PATH to a generated file.

    The shared delivery block says "the complete set, as files. Not a path, and not
    a subset." Four skills contradicted it two lines earlier: the optional
    visualize step said "**Present the HTML file path** to the user", which is the
    exact instruction behind founder-visible path-only and partial delivery. The
    delivery-block guards below could not see it -- they scan the block, and this
    sat above it.

    Presenting a path is legitimate in ONE place: the Main-Thread Return's
    host-conditional, which says a path IS the deliverable in Claude Code (where
    ./artifacts/ is durable) and files are the deliverable in Cowork. That text
    says "the path to", not "present the ... path", so it does not match here.
    """
    text = (SKILLS_ROOT / skill / "SKILL.md").read_text(encoding="utf-8")
    assert "Present the HTML file path" not in text, (
        f"{skill}/SKILL.md instructs presenting an HTML path. Generation steps must not hand work "
        f"over -- the Deliver step is the single hand-off, and it sends files, not a path."
    )


# Skills whose coaching payload has NO checklist artifact and NO score field. A shared
# "nesting matters" sentence was copy-pasted into all six Main-Thread Returns telling the
# main thread to fall back to re-reading `checklist.json` and to look for `score_pct` --
# both of which exist in three skills and in neither of these two. cap-table's score field
# is deliberately null and named `score_percent`; ic-sim's scoring output is
# `score_dimensions.json`. A main thread following it chases a file that is not there.
_NO_CHECKLIST_SKILLS = ("cap-table", "ic-sim")


@pytest.mark.parametrize("skill", _NO_CHECKLIST_SKILLS)
def test_skill_without_a_checklist_never_points_at_one(skill: str) -> None:
    """Ban the DEFECTIVE PHRASINGS, not every mention of the two tokens.

    A blanket ban was tried first and is wrong in both directions: ic-sim
    legitimately imports `deck-review:checklist.json` (namespaced, another skill's
    artifact), and the corrected caveat has to be able to SAY these fields do not
    exist here. What must not survive is the instruction itself -- telling the main
    thread the real number sits one level down, or to recover it from a checklist
    this skill never writes.
    """
    text = (SKILLS_ROOT / skill / "SKILL.md").read_text(encoding="utf-8")
    for phrase in (
        "fall back to re-reading `checklist.json`",
        "Reading `coaching_payload.score_pct`",
    ):
        assert phrase not in text, (
            f"{skill}/SKILL.md still carries the defective recovery instruction {phrase!r}. "
            f"This skill writes no checklist and no `score_pct` (cap-table emits a deliberately-null "
            f"`score_percent`; ic-sim's scoring output is `score_dimensions.json`), so a main thread "
            f"following it chases a missing file or improvises a headline number."
        )
    # A bare, un-namespaced `checklist.json` would be this skill's own artifact -- which
    # does not exist. `<other-skill>:checklist.json` is a declared cross-skill import.
    for match in re.finditer(r"(\S*)checklist\.json", text):
        assert match.group(1).endswith(":"), (
            f"{skill}/SKILL.md names a bare `checklist.json`. This skill produces none — "
            f"reference another skill's explicitly (e.g. `deck-review:checklist.json`)."
        )


# ---------------------------------------------------------------------------
# Plugin-root resolution: exactly ONE site per skill
#
# Measured in a live Cowork session: TWO different versions of this plugin were
# mounted at once (different SKILL.md, different producer scripts), plus
# host-side cache copies — one of them a symlink into a DIFFERENT session's
# plugin tree. Every skill's Step 0 self-healed with `find … | head -1`, and
# each skill re-ran that find in two-to-three LATER blocks, in separate shells.
# So one run could silently mix producer scripts across plugin versions with no
# error anywhere. The remedy is structural: resolve once, echo the value, and
# substitute the printed literal thereafter.
#
# This test is the ratchet on that. It counts `find … -path '*/skills/…/scripts'`
# occurrences and requires them all to sit in ONE resolution site. Three commands
# per site is expected and correct — the `/sessions` fast path, the cloud plugins
# folder and the `/` fallback are three branches of a single resolution, not three sites.
# ---------------------------------------------------------------------------

_FIND_SCRIPTS_RE = re.compile(r"find\s+/\S*\s+-type\s+d\s+-path\s+'\*/skills/[^']+/scripts'")

# Three = the /sessions fast path, the /root/.claude/plugins cloud folder (searched before the whole
# filesystem when the skill text arrived unfilled) and the / fallback, all inside Step 0.
PLUGIN_ROOT_FIND_COMMANDS_PER_SKILL = 3


@pytest.mark.parametrize("skill", sorted(SKILL_MD_CEILING))
def test_plugin_root_resolved_in_exactly_one_site(skill: str) -> None:
    text = (SKILLS_ROOT / skill / "SKILL.md").read_text(encoding="utf-8")
    matches = list(_FIND_SCRIPTS_RE.finditer(text))
    assert len(matches) == PLUGIN_ROOT_FIND_COMMANDS_PER_SKILL, (
        f"{skill}/SKILL.md has {len(matches)} plugin-root `find` command(s), expected "
        f"{PLUGIN_ROOT_FIND_COMMANDS_PER_SKILL} (the /sessions fast path, the cloud plugins folder and the "
        "/ fallback, all in Step 0). A find outside Step 0 re-resolves the plugin root in a fresh shell and can "
        "land on a different mount than Step 0 chose — measured, a single session had two plugin versions "
        "mounted at once. Resolve once, echo it, substitute the printed literal."
    )
    # All occurrences must be in one contiguous region: no later re-resolution.
    if len(matches) > 1:
        span = matches[-1].end() - matches[0].start()
        assert span < 2000, (
            f"{skill}/SKILL.md's plugin-root find commands are {span:,} chars apart — they are not one "
            "resolution site. A later re-resolution is the defect this test exists to prevent."
        )


@pytest.mark.parametrize("skill", sorted(SKILL_MD_CEILING))
def test_plugin_root_selection_is_deterministic(skill: str) -> None:
    """Step 0 must route candidates through the shared selector, not `head -1`.

    `head -1` on `find /` output is arbitrary when more than one plugin copy is mounted. The
    selector is deterministic, prefers an exact `--expect-version` match, and names every
    rejected mount on stderr so a duplicate install is visible rather than silent. It must
    NEVER select by highest version — a higher version in a stale host-side cache can be a tree
    the session never installed, which is reliably wrong rather than merely arbitrary.
    """
    text = (SKILLS_ROOT / skill / "SKILL.md").read_text(encoding="utf-8")
    assert "select_plugin_root.py" in text, (
        f"{skill}/SKILL.md does not route plugin-root candidates through select_plugin_root.py"
    )


# ---------------------------------------------------------------------------
# Producer provenance stamps
#
# compose_report.py's UNVALIDATED_ARTIFACT check compares an artifact's
# `_produced_by` against an expected value, so the stamp is a contract, not a
# label. One producer stamped `"verify_competitors.py"` — with the extension —
# while every sibling stamped a bare module name, and the consequence was not a
# failing test: it was that the artifact could not be provenance-checked at all
# without a special case, so it was quietly left out of the map. The fix removed
# the class rather than the instance (the stamp is derived from `__file__`), and
# this test is what stops a third spelling from appearing.
# ---------------------------------------------------------------------------

_PRODUCED_BY_RE = re.compile(r"""_produced_by"\]?\s*[:=]\s*(?:"([^"]+)"|pathlib\.Path\(__file__\)\.stem)""")


def test_producer_stamps_match_module_names() -> None:
    """Every `_produced_by` stamp must equal its own module's stem.

    A derived stamp (`pathlib.Path(__file__).stem`) satisfies this by construction and is the
    preferred form; a literal is accepted only while it matches.
    """
    offenders: list[str] = []
    checked = 0
    for script in sorted(SKILLS_ROOT.glob("*/scripts/*.py")):
        text = script.read_text(encoding="utf-8")
        m = _PRODUCED_BY_RE.search(text)
        if not m:
            continue
        checked += 1
        literal = m.group(1)
        if literal is None:
            continue  # derived from __file__ — correct by construction
        if literal != script.stem:
            offenders.append(f"{script.relative_to(SKILLS_ROOT)}: stamps {literal!r}, module stem is {script.stem!r}")

    assert checked >= 6, (
        f"only found {checked} producer stamp(s) — the regex probably stopped matching, which would "
        f"make this test pass vacuously"
    )
    assert not offenders, (
        "producer stamp(s) do not match their module name. compose_report.py's UNVALIDATED_ARTIFACT "
        "check compares against the module name, so a mismatched stamp makes the artifact "
        "un-provenance-checkable rather than merely oddly named:\n  " + "\n  ".join(offenders)
    )


@pytest.mark.parametrize("skill", sorted(SKILL_MD_CEILING))
def test_plugin_root_block_pipes_candidates_on_stdin_with_expected_version(skill: str) -> None:
    """The Step-0 resolution block must wire the selector the way the selector requires.

    Three properties, each of which failed a real check when absent:

    * candidates reach the selector on **stdin**, never argv — the host CLI path contains
      "Application Support", so an argv form word-splits on the space;
    * `--expect-version` is passed, or the selector falls back to the first `find` hit and a
      two-version mount is resolved arbitrarily again (measured: one session had 0.6.0 and 0.5.922
      mounted at once, and a hand-run of this block picks 0.6.0 ONLY because of this flag — the
      first hit was the older tree);
    * a provisional root is derived first, because `$SHARED_SCRIPTS` is only known after a root is
      chosen and the selector lives under it.

    This tests the PROSE, which is the part no unit test of the selector can reach.
    """
    text = (SKILLS_ROOT / skill / "SKILL.md").read_text(encoding="utf-8")
    assert "select_plugin_root.py" in text, f"{skill}/SKILL.md never invokes select_plugin_root.py"

    # Bound on STRUCTURE — the fenced block that actually invokes it — not on a character window
    # around the first mention. Several skills discuss the selector in prose above the block, so a
    # windowed slice lands on the prose and fails on content that is present a few lines lower.
    # This is the fixed-window anchor hazard this file warns about elsewhere; the first draft of
    # this very test walked into it.
    blocks = [b for b in text.split("```") if "select_plugin_root.py" in b]
    assert blocks, f"{skill}/SKILL.md mentions the selector but never inside a fenced block"
    block = "\n".join(blocks)

    assert "--expect-version" in block, (
        f"{skill}/SKILL.md invokes the selector without --expect-version, so a two-version mount "
        f"resolves to whichever candidate `find` happened to list first"
    )
    assert "printf" in block and "| python3" in block.replace("| \\\n  python3", "| python3"), (
        f"{skill}/SKILL.md must pipe candidates into the selector on stdin (a path containing a "
        f"space cannot be passed via argv)"
    )
    assert "PROVISIONAL_ROOT" in block, (
        f"{skill}/SKILL.md must derive a provisional root before invoking the selector — the "
        f"selector lives under the root it is choosing"
    )


# ---------------------------------------------------------------------------
# Loud producer refusal — a fleet invariant, because the defect was a fleet defect.
#
# Six producers across four skills independently had the same shape: on a validation
# error, write the error dict through `_write_output` (which honours `-o`) and return
# 0. That is the worst of both worlds — the canonical artifact is replaced by an
# analysis-free stub AND the caller gets an `{"ok":true}` receipt with exit 0, so every
# SKILL.md's "the pipe fails next" error branch is unreachable.
#
# This test is BEHAVIOURAL on purpose. The obvious structural version — "a script that
# can emit `status: invalid` must contain `_fail_invalid`, or a `sys.exit(1)`" — was
# written first and measured VACUOUS: every one of these producers already contained
# `sys.exit(1)` for malformed-JSON infrastructure errors, so the escape hatch admitted
# all three of the real offenders. Only running them proves anything.
#
# The registry is explicit rather than discovered: a rejecting payload is per-producer
# knowledge, and a generic one (`{}`) is accepted by some of these scripts.
# ---------------------------------------------------------------------------


# (skill, script, extra argv, a payload that script MUST reject[, canonical-path flag])
#
# The 5th element is OPTIONAL and defaults to "-o". It exists because the canonical artifact
# is not always written through `-o`: cap-table's `extract_instrument.py` writes the receipt
# there and its canonical `instruments.json` through `--instruments`. Hardcoding `-o` for that
# entry would have (a) failed argparse for the missing required flag, exiting non-zero and
# FALSE-GREENING this test for entirely the wrong reason, and (b) guarded the receipt file
# rather than the artifact the fleet rule is about.
def _deck_review_valid_checklist() -> str:
    """A 35-item checklist that checklist.py ACCEPTS, so an entry using it rejects on its flag alone."""
    text = (SKILLS_ROOT / "deck-review" / "scripts" / "checklist.py").read_text(encoding="utf-8")
    ids = re.findall(r'"id":\s*"(\w+)",\s*"category"', text)
    assert len(ids) == 35, ids
    return json.dumps({"items": [{"id": i, "status": "pass", "evidence": "checked"} for i in ids]})


# tuple[skill, script, extra argv, rejecting payload] plus an OPTIONAL 5th element naming the
# canonical-path flag when it is not `-o` (see the header comment above).
_REJECTING_PAYLOADS: list[tuple[str, str, list[str], str] | tuple[str, str, list[str], str, str]] = [
    # The hand-roll disclosure route. Registered because it writes a canonical artifact on
    # the route with the WEAKEST guarantees -- figures the deterministic engine could not
    # cover -- and because the 2026-07-05 incident hand-authored exactly this file with an
    # ad-hoc richer schema. The payload below is rejected for the extra-key reason, which is
    # the failure mode a required-keys-only validator cannot see.
    (
        "cap-table",
        "write_coverage_disclosure.py",
        [],
        '{"schema_version": "v0.1-coverage-disclosure", "covered": false, "computation_method":'
        ' "manual_outside_pipeline", "uncovered_parts": ["x"], "counsel_review": true,'
        ' "my_own_richer_field": {"a": 1}}',
    ),
    # persist_agent_artifact.py is the write path for competitive-positioning's three
    # main-thread-authored artifacts. It is the newest member of this registry and the reason
    # the registry exists: it writes a CANONICAL artifact, so a rejected input that clobbered
    # `-o` would destroy the prior good copy exactly as the six original offenders did.
    (
        "competitive-positioning",
        "persist_agent_artifact.py",
        ["--artifact", "positioning.json"],
        '{"not_the_required_key": 1}',
    ),
    # The draft is the canonical artifact (updated in place), so it is the file that must survive.
    ("competitive-positioning", "record_deferred_recall.py", [], '[{"name":"x"}]', "--draft"),
    ("market-sizing", "market_sizing.py", ["--stdin"], '{"approach":"top_down","industry_total":-5}'),
    ("market-sizing", "sensitivity.py", [], '{"approach":"bottom_up","base":{},"ranges":{}}'),
    ("market-sizing", "checklist.py", [], '{"notitems":1}'),
    ("market-sizing", "red_team.py", [], '{"findings":"not a list"}'),
    ("deck-review", "checklist.py", ["--run-id", "RID"], '{"items":[{"id":"bogus","status":"pass"}]}'),
    # A VALID checklist (accepted without the flag; see the control test below) and a
    # reconciliation that cannot be read: the refusal is the flag's own precondition.
    (
        "deck-review",
        "checklist.py",
        ["--run-id", "RID", "--reconciliation", "/nonexistent/reconciliation.json"],
        _deck_review_valid_checklist(),
    ),
    ("financial-model-review", "checklist.py", [], '{"notitems":1}'),
    ("financial-model-review", "unit_economics.py", [], '{"nocompany":1}'),
    # runway.py does not require `company` (a quick check states only cash and burn), so a payload
    # without it is valid; a `company` that is present and not an object is not.
    ("financial-model-review", "runway.py", [], '{"company":"x"}'),
    ("ic-sim", "score_dimensions.py", ["--run-id", "RID"], '{"items":[{"id":"bogus","status":"concern"}]}'),
    # A figure recorded at 1/1000 of what its own `raw` string says. This is THE ledger
    # failure mode: the arithmetic downstream is then flawless and wrong by a thousand.
    (
        "deck-review",
        "ledger.py",
        ["--run-id", "RID"],
        '{"figures":[{"id":"f1","value":493,"raw":"$493K","unit_kind":"money","label":"GMV",'
        '"quote":"GMV of $493K","currency":"USD"}]}',
    ),
    # reconcile.py rejects before it can reach the ledger it was pointed at.
    (
        "deck-review",
        "reconcile.py",
        ["--run-id", "RID", "--ledger", "/nonexistent/ledger.json", "--second-read", "/nonexistent/second.json"],
        '{"relations":[]}',
    ),
    # THE GATE THAT AUTHORIZES A REPORT. `emit` wrote gate_state.json and only then checked
    # whether the prose named a different stage, so a refused gate sat on disk and `answer` --
    # which only checks that a file exists -- answered it with `{"ok":true}`. `authorize()`
    # never re-checks prose, so the run proceeded on a gate the producer had rejected.
    (
        "deck-review",
        "gate_state.py",
        ["emit", "--run-id", "RID", "--stage", "pre_seed"],
        '{"gate_id":"stage_confirmation","question":"Does this look right?",'
        '"context_summary":"The deck footer reads Seed round open.",'
        '"options":["Looks right","Different stage","Not sure \u2014 proceed anyway"]}',
    ),
    # cap-table had NO entry here at all, which is why the fleet's worst instance of this class
    # went unseen. Note the 5th element: the canonical path is `--instruments`; `-o` writes only
    # the receipt, so a hardcoded `-o` would have failed argparse, exited non-zero, and
    # FALSE-GREENED this test while guarding the wrong file.
    #
    # SCOPE, stated honestly: this entry covers the FIELD-VALIDATION refusal. It does NOT reach
    # the default-ON evidence/invariant gates -- those need a well-formed instruments.json as the
    # starting artifact, and this harness deliberately seeds a `{"sentinel": true}` stub. The gate
    # path (which is where the real defect was: gates ran AFTER `write_artifact`, so a blocking
    # refusal left the hallucinated extraction on disk) is covered by
    # `test_cap_table.py::test_blocking_gate_leaves_instruments_json_untouched`, which was
    # verified to fail against the pre-fix script. Do not delete that test on the belief that
    # this registry entry subsumes it.
    (
        "cap-table",
        "extract_instrument.py",
        ["--run-id", "RID", "--no-verify", "--no-invariants", "--no-cross-check"],
        '{"instrument_type":"safe","fields":{"id":"safe_001"},"confidence":{},"ambiguities":[]}',
        "--instruments",
    ),
    # A validator that used to write its artifact unconditionally ("audit trail even on
    # validation error"), destroying a prior good artifact on a run that produced nothing usable.
    (
        "competitive-positioning",
        "verify_competitors.py",
        ["--run-id", "RID"],
        '{"startup_characterization":{},"verdicts":[{"slug":"x","verdict":"not_a_competitor"}]}',
        "--output",
    ),
    # A publication with no source cannot be shown to the founder with a way to check it.
    (
        "competitive-positioning",
        "validate_startup_research.py",
        ["--run-id", "RID"],
        '{"searches":[{"query":"q","kind":"applicant","found":true}],'
        '"publications":[{"number":"US1B1","office":"US","kind":"B1","read":"none","events":[]}]}',
    ),
    # The outside review: a hand-off with no findings array is not a review.
    (
        "competitive-positioning",
        "cp_red_team.py",
        ["--run-id", "RID"],
        '{"could_not_check": []}',
    ),
    # A skip reason off the closed list would reach the founder as a sentence nobody wrote.
    (
        "competitive-positioning",
        "record_red_team_skip.py",
        ["--run-id", "RID", "--reason", "not_needed"],
        "",
    ),
]


@pytest.mark.parametrize("entry", _REJECTING_PAYLOADS, ids=lambda e: f"{e[0]}/{e[1]}")
def test_producer_rejects_loudly_without_clobbering(entry: tuple, tmp_path: Path) -> None:
    """A rejected input must exit non-zero AND leave the canonical artifact untouched."""
    skill, script, extra, payload = entry[0], entry[1], entry[2], entry[3]
    canonical_flag = entry[4] if len(entry) > 4 else "-o"
    out = tmp_path / "artifact.json"
    out.write_text('{"sentinel": true}', encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(SKILLS_ROOT / skill / "scripts" / script), *extra, canonical_flag, str(out)],
        input=payload,
        capture_output=True,
        text=True,
    )
    where = f"{skill}/{script}"
    assert proc.returncode != 0, (
        f"{where} accepted an invalid input with exit 0. The caller cannot distinguish this from "
        f"success, so every SKILL.md's producer-error branch is unreachable. stdout={proc.stdout[:200]}"
    )
    assert proc.stderr.strip(), f"{where} rejected the input silently — nothing on stderr"
    assert json.loads(out.read_text(encoding="utf-8")) == {"sentinel": True}, (
        f"{where} overwrote the canonical artifact with an analysis-free stub on a rejected run"
    )


def test_the_deck_review_reconciliation_entry_rejects_on_the_flag_alone(tmp_path: Path) -> None:
    """Control for the `--reconciliation` entry: the same payload, without the flag, is accepted.
    Otherwise the entry could green on a payload refusal and guard nothing."""
    out = tmp_path / "checklist.json"
    proc = subprocess.run(
        [
            sys.executable,
            str(SKILLS_ROOT / "deck-review" / "scripts" / "checklist.py"),
            "--run-id",
            "RID",
            "-o",
            str(out),
        ],
        input=_deck_review_valid_checklist(),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert json.loads(out.read_text(encoding="utf-8"))["summary"]["pass"] == 34


# `_REJECTING_PAYLOADS` cannot hold these: they live outside a skill's scripts dir, or guard a file that
# is not their `-o`. Each entry builds its own fixture and returns (argv, stdin, files that must survive).
def _reject_unlisted_option(tmp: Path) -> tuple[list[str], str, list[Path]]:
    import gate_run_helpers as h

    root, run_id, _run_dir = h.start_bound(tmp, "market-sizing")
    argv = [str(h.RECORD), "answer", "--run-id", run_id, "--artifacts-root", str(root)]
    argv += ["--gate", "ctx_basics.stage", "--answer-id", "series_q"]
    return argv, "", [h.status_path(root, run_id), h.ledger_path(root, run_id)]


def _reject_bad_line_on_a_waiting_run(tmp: Path) -> tuple[list[str], str, list[Path]]:
    import gate_run_helpers as h

    root, run_id, _run_dir = h.start_bound(tmp, "market-sizing")
    opened = h.record(root, run_id, "open", "--gate", "ctx_basics.stage")
    assert opened.returncode == 0, opened.stderr
    argv = [str(h.RUN_STATUS), "start", "--skill", "market-sizing", "--artifacts-root", str(root)]
    stdin = f"FS_HOST_RUN_ID={run_id}\nFS_HOST_ANSWER ctx_basics.stage=series_q\n"
    return argv, stdin, [h.status_path(root, run_id), h.ledger_path(root, run_id)]


def _reject_final_deliverables_on_a_running_run(tmp: Path) -> tuple[list[str], str, list[Path]]:
    import gate_run_helpers as h

    root, run_id, _run_dir = h.start_bound(tmp, "deck-review")
    argv = [str(h.RUN_STATUS), "deliverables", "--run-id", run_id, "--artifacts-root", str(root), "--final"]
    return argv, "", [h.status_path(root, run_id), h.ledger_path(root, run_id)]


def _reject_unknown_origin(tmp: Path) -> tuple[list[str], str, list[Path]]:
    original = tmp / "inputs.json"
    original.write_text('{"company": {"name": "Example Co"}}', encoding="utf-8")
    out_dir = tmp / "out"
    out_dir.mkdir()
    sentinel = out_dir / "corrected_inputs.json"
    sentinel.write_text('{"sentinel": true}', encoding="utf-8")
    script = SKILLS_ROOT / "financial-model-review" / "scripts" / "apply_corrections.py"
    argv = [str(script), "--set", "company.name=Example", "--original", str(original), "--output-dir", str(out_dir)]
    argv += ["--run-id", "20261007T090000Z-4c4c4c", "--origin", "bogus"]
    return argv, "", [sentinel, original]


def _reject_read_on_another_skills_run(tmp: Path) -> tuple[list[str], str, list[Path]]:
    import gate_run_helpers as h

    root = tmp / "artifacts"
    root.mkdir()
    run_id = h.start_ok(root, "deck-review")
    (root / "founder-context-example-co.json").write_text('{"slug": "example-co"}', encoding="utf-8")
    argv = [str(h.SHARED / "founder_context.py"), "read", "--artifacts-root", str(root)]
    argv += ["--run-id", run_id, "--skill", "market-sizing"]
    return argv, "", [h.status_path(root, run_id), h.ledger_path(root, run_id)]


def _reject_another_runs_verification(tmp: Path) -> tuple[list[str], str, list[Path]]:
    draft = tmp / "landscape_draft.json"
    draft.write_text('{"competitors": [], "metadata": {"run_id": "20261008T090000Z-1a1a1a"}}', encoding="utf-8")
    ver = tmp / "competitor_verification.json"
    ver.write_text(
        '{"recall_gaps": {"unmatched": [{"name": "Example Newco", "slug": "example-newco", '
        '"why_considered": "x", "sources": ["https://example.org/a"]}]}, '
        '"metadata": {"run_id": "20260101T000000Z-2b2b2b"}}',
        encoding="utf-8",
    )
    script = SKILLS_ROOT / "competitive-positioning" / "scripts" / "record_deferred_recall.py"
    argv = [str(script), "--draft", str(draft), "--from-verification", str(ver), "--run-id", "20261008T090000Z-1a1a1a"]
    return argv, "", [draft, ver]


_REJECTING_CALLS = [
    ("record_deferred_recall.py --from-verification, another run's file", _reject_another_runs_verification),
    ("record_gate_answer.py answer, an unlisted option", _reject_unlisted_option),
    ("founder_context.py read --run-id on another skill's run", _reject_read_on_another_skills_run),
    ("run_status.py start, a bad line resuming a waiting run", _reject_bad_line_on_a_waiting_run),
    ("run_status.py deliverables --final on a run that is not complete", _reject_final_deliverables_on_a_running_run),
    ("apply_corrections.py --run-id with an unknown --origin", _reject_unknown_origin),
]


@pytest.mark.parametrize("entry", _REJECTING_CALLS, ids=lambda e: e[0])
def test_gate_scripts_reject_loudly_without_clobbering(entry: tuple, tmp_path: Path) -> None:
    """A refused call exits non-zero, says why on stdout and stderr, and leaves every file it guards as it was."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    argv, stdin, guarded = entry[1](tmp_path)
    before = {p: p.read_bytes() for p in guarded}
    proc = subprocess.run([sys.executable, *argv], input=stdin, capture_output=True, text=True)
    assert proc.returncode == 1, (entry[0], proc.returncode, proc.stdout[:300], proc.stderr[:300])
    assert proc.stderr.strip(), f"{entry[0]}: refused silently, nothing on stderr"
    assert json.loads(proc.stdout), f"{entry[0]}: no diagnostic on stdout"
    for p in guarded:
        assert p.read_bytes() == before[p], f"{entry[0]} changed {p.name}"


def test_paid_lanes_require_explicit_opt_in_not_merely_credentials() -> None:
    """A credential is a capability, not permission to spend.

    Measured cause of a real incident: plain `uv run pytest` collected all three paid e2e
    lanes (the `e2e` marker is registered but nothing deselects it by default), and
    `has_claude_auth()` returns True on **any** macOS host because the Keychain cannot be
    probed cheaply. So an audit that ran the default suite on a Mac started paid runs
    against the operator's subscription without anyone asking for them.

    Two independent gates are required and this pins both: the default run must deselect
    `e2e`, and the lanes must additionally require a deliberate opt-in.
    """
    config = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    ini_start = config.index("[tool.pytest.ini_options]")
    rest = config[ini_start + 1 :]
    next_section = rest.find("\n[tool.")
    ini = rest if next_section == -1 else rest[:next_section]

    # READ THE `addopts` LINE, NOT THE SECTION. This used to substring-test the whole
    # `[tool.pytest.ini_options]` slice, which also contains the `markers` list -- and a marker
    # DESCRIPTION that quotes the expression (`... must say -m "not e2e and not mutation"`) then
    # satisfies the check on prose. Measured: with `addopts` emptied entirely, the section-wide
    # version of this test PASSED. A guard against unauthorised spend that a docstring can satisfy
    # is not a guard, and this one is asserting about `addopts` in particular -- so it must look
    # there in particular.
    addopts_line = re.search(r"^addopts\s*=\s*(.+)$", ini, re.MULTILINE)
    assert addopts_line, "pytest has no addopts, so nothing deselects the paid lanes by default"
    addopts = addopts_line.group(1)
    assert "not e2e" in addopts, (
        f"the default pytest run does not deselect `e2e`; a plain `pytest` will start paid runs. addopts={addopts}"
    )

    harness = (REPO_ROOT / "founder-skills" / "tests" / "_e2e_harness.py").read_text(encoding="utf-8")
    assert "RUN_PAID_E2E" in harness, (
        "_e2e_harness.py gates only on credential detection. A credential says a run CAN "
        "happen, never that it MAY — add an explicit opt-in."
    )


def test_every_paid_lane_gates_on_the_opt_in() -> None:
    """All three lanes, not just the two that share a harness.

    deck-review deliberately carries its own auth check (it is the oldest lane of the paid
    release gate), so a gate added to the shared harness alone leaves it open — which is the
    exact shape of the incident: one of two copies.
    """
    import importlib.util

    # FOUR since 2026-08-28: `test_e2e_cap_table.py` joined the three release lanes. It is NOT
    # gated on by a tag (it carries its own RUN_PAID_E2E_CAP_TABLE and is named in the workflow's
    # ALLOWED_SKIPS), but it is still a paid lane, so it must satisfy the same opt-in gate — which
    # is precisely what this test exists to enforce across lanes that do not share a harness.
    lanes = sorted((REPO_ROOT / "founder-skills" / "tests").glob("test_e2e_*.py"))
    assert len(lanes) == 4, [p.name for p in lanes]

    saved = {k: os.environ.get(k) for k in ("RUN_PAID_E2E", "ANTHROPIC_API_KEY")}
    try:
        os.environ.pop("RUN_PAID_E2E", None)
        os.environ["ANTHROPIC_API_KEY"] = "sk-probe-not-a-real-key"
        for lane in lanes:
            # BEHAVIOURAL, not a grep. The first version asked whether the file MENTIONED
            # the flag; deleting the two lines that enforce it left the constant and the
            # helper behind, so the check stayed green with the gate gone. Call whatever
            # each lane actually consults.
            spec = importlib.util.spec_from_file_location(f"_lane_{lane.stem}", lane)
            assert spec and spec.loader
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            checker = getattr(module, "_has_claude_auth", None) or getattr(module, "has_claude_auth", None)
            assert checker is not None, (
                f"{lane.name} exposes no auth check, so nothing gates it — if it now reaches the "
                "shared harness under another name, teach this test that name"
            )
            assert checker() is False, f"{lane.name} authorizes a paid run on a credential alone, with no opt-in"
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def test_the_paid_opt_in_is_behaviourally_enforced_not_merely_mentioned() -> None:
    """Grepping for the flag name is not a guard, and mutation proved it.

    The first version of this check asserted `"RUN_PAID_E2E" in harness_source`. Deleting
    the two lines that ENFORCE it left the constant, the helper and the docstring in place,
    so the check stayed green while a plain credential once again authorized spending. The
    question is what the function returns, so ask it.
    """
    import importlib.util

    harness_path = REPO_ROOT / "founder-skills" / "tests" / "_e2e_harness.py"
    spec = importlib.util.spec_from_file_location("_paid_probe", harness_path)
    assert spec and spec.loader
    harness = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(harness)

    saved = {k: os.environ.get(k) for k in ("RUN_PAID_E2E", "ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN")}
    try:
        # A credential present, opt-in absent: must NOT authorize.
        os.environ.pop("RUN_PAID_E2E", None)
        os.environ["ANTHROPIC_API_KEY"] = "sk-probe-not-a-real-key"
        assert harness.has_claude_auth() is False, (
            "a credential alone authorized a paid run — that is the exact incident this closes"
        )
        # Opt-in present with a credential: authorizes, or the lane can never run.
        os.environ["RUN_PAID_E2E"] = "1"
        assert harness.has_claude_auth() is True
        # Opt-in present, no credential of any kind: still refuses on non-macOS; on macOS
        # the Keychain cannot be probed, so only assert the direction that must hold.
        os.environ.pop("ANTHROPIC_API_KEY", None)
        assert harness.paid_run_authorized() is True
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def test_the_authorized_paid_job_supplies_the_opt_in_and_fails_on_skips() -> None:
    """The local spend guard must not silently disable the release gate.

    Requiring `RUN_PAID_E2E` in both auth predicates protects a developer's machine — and
    it broke the one job that is SUPPOSED to spend. `skill-quality.yml` passes credentials
    only, so after that change every tag and manual dispatch selected three lanes, skipped
    all three, and exited green: the gate the release process waits on could no longer
    fail. A safety fix that turns its own consumer into a no-op has moved the defect, not
    removed it.

    Two things are required and both are pinned: the authorized job sets the opt-in, and
    it fails when a lane skips — otherwise the next credential mishap returns to a silent
    false green.
    """
    workflow = (REPO_ROOT / ".github" / "workflows" / "skill-quality.yml").read_text(encoding="utf-8")
    assert "RUN_PAID_E2E" in workflow, (
        "the paid job never sets RUN_PAID_E2E, so every lane skips and the release gate cannot fail"
    )
    # A skipped lane must be an error, not a pass.
    assert "skipped" in workflow.lower(), (
        "nothing in the paid job notices a SKIPPED lane; a skip and a pass exit the same way"
    )

    # AND IT MUST NAME THE LANES. "Zero skips" is not "everything ran": drop the `e2e`
    # marker from one test and it is never collected, leaving a clean report with two
    # passes and a checker that says all lanes executed. The expected set is therefore
    # explicit — and pinned here against the real test names, because a list in a workflow
    # is exactly the sort of thing that drifts silently from the code it describes.
    lane_names = set()
    for lane in sorted((REPO_ROOT / "founder-skills" / "tests").glob("test_e2e_*.py")):
        lane_names |= set(re.findall(r"^def (test_\w+_smoke)\(", lane.read_text(encoding="utf-8"), re.M))
    # FOUR since 2026-08-28. Three are in the workflow's EXPECTED set (gated on by a tag); the
    # fourth, `test_cap_table_smoke`, is in ALLOWED_SKIPS instead. The equality below still holds
    # and is still the property worth having: every lane that exists must be NAMED in the workflow,
    # whether it is gated on or deliberately skipped. A lane in neither set is the silent omission
    # this check was written to catch.
    assert len(lane_names) == 4, f"expected four paid lane tests, found {sorted(lane_names)}"
    # Quoted, not substring: renaming the workflow's entry to `test_market_sizing_smoke_2`
    # leaves the real name as a substring of it, and a bare `in` check passes while the
    # list has drifted. Mutation caught exactly that.
    listed = set(re.findall(r'"(test_\w+_smoke)"', workflow))
    assert listed == lane_names, (
        f"the paid job's expected-lane list is {sorted(listed)} but the lanes are "
        f"{sorted(lane_names)}; if a lane stops being collected the gate passes having run fewer"
    )


def test_the_release_path_runs_the_whole_free_suite() -> None:
    """The paid lane and `publish-release` both hang off `contract-tests`, which ran four
    skill-quality meta-check files. The gate authorization tests, the ledger grammar and
    the reconciliation rules live elsewhere, so a tag could go green having run none of
    them. `ci.yml` covers push and PR; it does not cover the tag path."""
    workflow = (REPO_ROOT / ".github" / "workflows" / "skill-quality.yml").read_text(encoding="utf-8")
    assert "pytest founder-skills/tests/ -q" in workflow, (
        "the job publish-release depends on does not run the full free suite"
    )


# ---------------------------------------------------------------------------
# No cwd-relative path may address the Cowork session layout
# ---------------------------------------------------------------------------

# Directory names that only mean anything relative to the SESSION TREE. A relative path naming one
# of these is resolved against the workspace shell's cwd, which is a path space we do not control
# and which HAS ALREADY MOVED underneath us once.
_SESSION_LAYOUT_DIRS = ("artifacts", "mnt", "outputs", "uploads", "handoff")

# Three shapes. Each was added because the previous set MISSED a real defect — this pattern has now
# been wrong twice, so the shapes are enumerated with the case that forced each:
#   (a) explicit `./`/`../` prefix, slash optional  -> `./artifacts`, `./mnt/uploads`
#       (the slash was once required, which missed `mkdir -p ./artifacts` — the motivating defect)
#   (b) a bare layout dir that is clearly a PATH because it carries a trailing slash -> `outputs/foo`
#   (c) a bare layout WORD as the argument of a path-taking command -> `mkdir -p artifacts`, `cd outputs`
#       (dropping the `./` is one keystroke and is exactly as broken; without (c) the test's own
#        remedy text can be "satisfied" by deleting two characters)
# A bare word outside (c) is deliberately unmatched: it appears constantly in prose.
_DIRS = "|".join(_SESSION_LAYOUT_DIRS)
_RELATIVE_LAYOUT_PATH = re.compile(
    r"(?:^|[\s\"'=(>])(?:" + rf"(?:\./|\.\./)(?:{_DIRS})(?:/|\b)" + r"|" + rf"(?:{_DIRS})/" + r")"
)
_BARE_LAYOUT_ARG = re.compile(rf"\b(?:mkdir|cd|rmdir|pushd)\s+(?:-\S+\s+)*(?:{_DIRS})\b")

# A path is exempt when it is reached through a variable or an absolute anchor.
#
# APPLIED PER SEGMENT, NEVER PER LINE. Applying it to the whole line is how this test shipped
# blind to the defect it was written for: the real deck-review line was
#   ls -la "$(dirname "$REVIEW_DIR")"/../uploads 2>/dev/null || ls -la ./mnt/uploads
# where `$REVIEW_DIR` in the FIRST command exempted the bare `./mnt/uploads` in the second. Measured
# at the time: 61% of all command lines in the fleet contained some `$VAR`, so a line-wide exemption
# blinded the majority of the surface. A mutation probe missed it too, because the probe injected a
# simplified `ls -la ./mnt/uploads` with no variable rather than the line that actually shipped —
# a probe against a strawman is not a probe.
_ANCHORED = re.compile(r"\$\{?[A-Z_]+\}?|\$\(pwd\)|\$PWD|/sessions/|<printed |<[A-Z_]+>|\$\(python")

# Shell segment separators. Anchoring is decided independently within each.
_SEGMENT = re.compile(r"\|\||&&|[;|]")

# `#` starts a comment only at line start or after whitespace — `--marker '#uuid'` is an argument,
# and splitting on it would blind the rest of a line this fleet really does write.
_COMMENT = re.compile(r"(?:^|\s)#")

# Heredoc opener; the body is DATA, not commands. 13 bash blocks in the fleet carry one, and a
# dispatch template mentioning `outputs/` inside one is not a path.
_HEREDOC = re.compile(r"<<-?\s*[\"']?(\w+)[\"']?")


def _strip_comment(line: str) -> str:
    m = _COMMENT.search(line)
    return line[: m.start()] if m else line


def _command_lines(text: str) -> list[tuple[int, str]]:
    """Every command line inside a fenced ```bash block, plus inline-code spans that look like commands.

    BOTH surfaces are required. The defect this guards against lived in an INLINE span
    (`ls -la ./mnt/uploads` inside a prose sentence), not in a fenced block — a fenced-only scan
    reports clean on the exact case that motivated the test.
    """
    out: list[tuple[int, str]] = []
    cursor = 0
    for block in re.findall(r"```bash\n(.*?)```", text, re.DOTALL):
        # Scan forward: two byte-identical blocks must not both report the first one's line numbers.
        start = text.index(block, cursor)
        cursor = start + len(block)
        base = text[:start].count("\n") + 1
        delim: str | None = None
        for i, line in enumerate(block.splitlines()):
            if delim is not None:
                if line.strip() == delim:
                    delim = None
                continue
            code = _strip_comment(line)
            if code.strip():
                out.append((base + i, code))
            opener = _HEREDOC.search(code)
            if opener:
                delim = opener.group(1)
    for m in re.finditer(r"`([^`\n]+)`", text):
        span = m.group(1)
        # Verb list, not a whitelist of two: `cd`/`find`/`sed`/`head`/`grep` were all unscanned.
        # `\[` is matched separately because `[ -d x ]` has a SPACE after the bracket, so a `\b`
        # after it can never fire — the alternative was dead code.
        if re.match(
            r"^\s*(?:\[|(?:mkdir|ls|cp|mv|cat|cd|find|sed|head|tail|grep|echo|python3?|rm|rmdir|touch|test)\b)", span
        ):
            out.append((text[: m.start()].count("\n") + 1, _strip_comment(span)))
    return out


def _offending_segments(line: str) -> list[str]:
    """Segments of one command line that name a layout dir relatively and are not anchored.

    ANCHORING IS DECIDED PER TOKEN, not per line and not per segment. Both coarser scopes have
    already shipped blind:
      * per LINE missed `... "$REVIEW_DIR" ... || ls -la ./mnt/uploads` — one variable anywhere
        exempted every path on the line, and 61% of fleet command lines contain a variable.
      * per SEGMENT still missed `python3 "$SCRIPTS/foo.py" --out ./artifacts/x.json`, where the
        anchored token and the relative one share a single segment.
    A path is its own whitespace-delimited token, so that is the unit that decides.
    """
    bad = []
    for seg in _SEGMENT.split(line):
        if not seg.strip():
            continue
        # (c) the bare-word rule needs the COMMAND, so it is judged on the whole segment.
        if _BARE_LAYOUT_ARG.search(seg) and not _ANCHORED.search(seg):
            bad.append(seg.strip())
            continue
        for token in seg.split():
            if _RELATIVE_LAYOUT_PATH.search(f" {token}") and not _ANCHORED.search(token):
                bad.append(token)
    return bad


@pytest.mark.parametrize("skill", sorted(SKILL_MD_CEILING))
def test_no_cwd_relative_path_addresses_the_session_layout(skill: str) -> None:
    """A relative path naming artifacts/mnt/outputs/uploads/handoff is a latent relocation bug.

    WHY THIS EXISTS, and why an instance fix was not enough. cowork-harness 2.4.0 corrected the
    workspace shell's cwd at hostloop from `<session>/mnt/<first-folder-else-outputs>` to the bare
    session root — upstream measured production and found the old derivation reproduced a prompt
    claim, not a behaviour. Every relative path in a skill body silently changed meaning:

      * `mkdir -p ./artifacts` resolved to the canonical artifacts root, and now resolves to
        `/sessions/<id>/artifacts` — OUTSIDE `mnt/`, where nothing is delivered and nothing says so.
      * `ls -la ./mnt/uploads` pointed at a path that never existed, and now points at the real
        uploads mount. Correct today BY ACCIDENT; a skill that only works on one harness version is
        not fixed.

    Four of six skills said `"$ARTIFACTS_ROOT"` and two said `./artifacts` — so this class had
    ALREADY been fixed once and drifted back. That is the argument for a detector over a patch:
    the fix does not hold itself.

    The remedy is always the same: resolve the path with `resolve_artifacts_root.py` (`--uploads`
    for the uploads mount) and address the printed value, per that module's opening rationale — a
    computed path in a skill body is the thing the model paraphrases away.
    """
    text = (SKILLS_ROOT / skill / "SKILL.md").read_text(encoding="utf-8")
    offenders = [
        f"  {skill}/SKILL.md:{line_no}: {seg}"
        for line_no, line in _command_lines(text)
        for seg in _offending_segments(line)
    ]
    assert not offenders, (
        f"{skill}/SKILL.md has {len(offenders)} cwd-relative path(s) addressing the session layout. "
        "These resolve against the workspace shell's cwd, which moved in cowork-harness 2.4.0 and "
        "can move again — one of these silently relocates deliverables outside the outputs mount.\n"
        + "\n".join(offenders)
        + "\n  Fix: derive the path from resolve_artifacts_root.py (--uploads for the uploads mount) "
        "and address the printed value, or anchor it on an already-resolved $VAR."
    )


# A label whose presence is CONDITIONAL on something the runtime may not have. `_option_specs`
# yields only the backticked span per comma-segment, so this marker is discarded before any
# existing test sees it -- which is why the arity test reads a collapsible row as fully populated.
_CONDITIONAL_OPTION = re.compile(r"\(\s*present only when\b", re.I)


def _unconditional_option_counts(skill: str) -> list[tuple[int, str, int, int]]:
    """(line_no, row name, declared options, options that are NOT conditionally present).

    Re-derives the `Option labels` column by scanning back to the table header: `_table_specs`
    yields the row's line number but not the column index it computed, so the cell cannot be
    recovered from `line_no` alone.
    """
    lines = (SKILLS_ROOT / skill / "SKILL.md").read_text(encoding="utf-8").splitlines()
    out: list[tuple[int, str, int, int]] = []
    for line_no, _form, name, options in _option_specs("\n".join(lines)):
        if _form != "table-cell" or not options:
            continue
        column = None
        for back in range(line_no - 1, -1, -1):
            row = lines[back].strip()
            if not row.startswith("|"):
                break
            cells = [c.strip() for c in _split_outside_backticks(row.strip("|"), "|")]
            if _TABLE_LABEL_COLUMN in cells:
                column = cells.index(_TABLE_LABEL_COLUMN)
                break
        if column is None:
            continue
        cells = [c.strip() for c in _split_outside_backticks(lines[line_no - 1].strip().strip("|"), "|")]
        if column >= len(cells):
            continue
        segments = _split_outside_backticks(cells[column], ",")
        unconditional = sum(1 for s in segments if "`" in s and not _CONDITIONAL_OPTION.search(s))
        out.append((line_no, name or "", len(options), unconditional))
    return out


@pytest.mark.parametrize("skill", sorted(SKILL_MD_CEILING))
def test_option_lists_still_render_when_a_conditional_label_is_absent(skill: str) -> None:
    """A row whose affirmative label is conditional must still leave 2 options without it.

    THE ARITY TEST CANNOT SEE THIS. It counts DECLARED options, so a row marked
    `(present only when a candidate was derived)` reads as fully populated and passes -- while the
    skill's own Notes instruct "Omit it entirely if nothing was derived", leaving ONE option.

    That is not cosmetic: `AskUserQuestion`'s 2-option floor is a hard schema bound, and the runtime
    REJECTS the whole call -- "This call included a question with fewer than 2 options, so it was
    rejected and the person never saw it." Since these gates are asked in one batched call, a single
    collapsed row costs the other questions in that call a round-trip too.

    Exemptions come from `ARITY_EXEMPT`, deliberately reused rather than re-derived: the catalog's
    general-shape row carries no backticked labels by design, and a class rule like "skip rows with
    no options" is exactly the silent skip that row's own exemption note argues against.

    KNOWN UNCOVERED SIBLING, recorded rather than chased: cap-table's **Scenario selection** row
    declares four labels and conditions them in PROSE -- "Offer only the scenarios that apply to
    this cap table" -- so it can collapse the same way and neither this scan nor the arity test can
    see it. Measured in the committed corpus: `cap-table-safe-full` rendered 2 of those options and
    `cap-table-carta-folder` rendered 3, so the conditioning is live. Teaching this test to parse
    prose conditionals is the enumerated-blocklist trap `leak_scan.py`'s design note says this repo
    has already lost once; the durable fix is to express that row's condition as a marker, at which
    point this scan covers it for free.
    """
    bad = [
        (line_no, name, declared, uncond)
        for line_no, name, declared, uncond in _unconditional_option_counts(skill)
        if uncond < ASKUSER_MIN_OPTIONS and (skill, name) not in ARITY_EXEMPT
    ]
    assert not bad, (
        f"{skill}/SKILL.md declares an option set that collapses below "
        f"{ASKUSER_MIN_OPTIONS} when a conditional label is absent:\n"
        + "\n".join(f"  line {ln} ({nm}): {d} declared, only {u} unconditional" for ln, nm, d, u in bad)
        + "\n\nAdd an explicit defer as the last option — the catalog's own general-shape row "
        "requires one, and the fleet vocabulary is `Not sure` / `Not stated`. It must go in the "
        "Option labels cell: a caveat in Notes is invisible to this check and to the runtime."
    )


def test_the_conditional_marker_scan_still_finds_the_rows_it_was_built_for() -> None:
    """Non-vacuity, keyed on row NAMES rather than a count.

    A count floor reds when one row is legitimately reshaped; a name set says which rows the
    detector was calibrated on. `ARITY_EXEMPT` is keyed the same way for the same reason.
    """
    seen = {name for line_no, name, declared, uncond in _unconditional_option_counts("cap-table") if declared > uncond}
    assert {"Company name", "Sector", "Geography"} <= seen, (
        "the conditional-presence marker is no longer detected on the rows this scan was built "
        f"for (found: {sorted(seen)}). If a row legitimately dropped its marker, remove it here; "
        "if the regex rotted, every collapsible row is now invisible."
    )


def test_corpus_counts_every_agent_the_skill_pins_not_just_its_namesake() -> None:
    """`_corpus_bytes` must apply the resolver's rule, not the scalar one it replaced.

    The harness used to derive a SINGLE agent path from the skill name. It now packages the UNION
    of `agents/<skill>.md` and every in-plugin agent a pinned `subagent_type` literal in that
    skill's SKILL.md or references/** resolves to — matched on the agent's declared frontmatter
    `name:`, not on its filename.

    So the moment any skill pins a second agent, the old formula counts a corpus SMALLER than the
    one that ships. For market-sizing that gap is immaterial against ~357 KB of headroom; the
    reason it has to be right anyway is cap-table, where the margin is thin and the failure mode
    over the ceiling is silent until someone reads `corpusCuts`. A guard that reports a number is
    worse than no guard when the number is wrong in the direction that hides a breach.

    Deliberately NOT a glob over `agents/**`: that counts agents the skill cannot dispatch, which
    is a different wrong number and not a safe one.
    """
    agents_dir = SKILLS_ROOT.parent / "agents"
    extra = sorted(p.name for p in agents_dir.glob("*.md") if p.stem != "market-sizing")
    assert extra, "no non-namesake agent files at all — the helper below would be untestable"

    # Every agent this skill actually pins must be inside the counted corpus.
    pinned = _pinned_agent_files("market-sizing")
    namesake = agents_dir / "market-sizing.md"
    assert namesake in pinned, "the skill's own agent must always be counted"

    total = _corpus_bytes("market-sizing")
    assert total >= sum(len(p.read_bytes()) for p in pinned), (
        "corpus total is smaller than the agents the skill pins — the scalar rule is back"
    )

    # Non-vacuity: the helper must actually read the pins rather than return the namesake always.
    skill_text = (SKILLS_ROOT / "market-sizing" / "SKILL.md").read_text(encoding="utf-8")
    for p in pinned:
        stem = p.stem
        assert stem == "market-sizing" or f"founder-skills:{stem}" in skill_text, (
            f"{p.name} was counted but market-sizing pins no such subagent_type"
        )


# The SHARED reference tree — `founder-skills/references/`, not any one skill's.
#
# Bounded because cowork-harness 3.7.0 made it critique evidence: every skill that points at a file
# here carries its bytes in THAT skill's corpus, so one edit spends up to six budgets at once, and
# cap-table has the least headroom (83% of the 524,288 B ceiling). Over the ceiling, content is cut
# before grading and the only signal is a `corpusCuts` entry.
#
# Measured 2026-09-21: 120,601 B across 9 files. Raise it deliberately, with the reason recorded
# here; a lowering needs none.
# Raised 2026-09-27 to 124,642 B (+4,041): skill-execution-model.md gained the Step 0 proof of the
# file-tool path of outputs (the file tools refuse a relative path), the `write_refused` blocked
# contract, and the founder disclosure on a degraded run. The procedure lives here, once, rather than
# six times in the SKILL.mds, which carry only the short block.
# Lowered 2026-09-28 to 124,496 B (-146): the dated version and confirmation stamps in
# skill-execution-model.md were removed; each fact is now stated as a current rule.
# Raised 2026-09-28 to 124,911 B (+415): the Host-Capability Matrix splits the hooks row (Stop fires on
# desktop-local and cloud; PreToolUse on desktop-local, unobserved on cloud), and Runtime Detection states
# that $CLAUDE_CODE_IS_COWORK is positive-only and adds the $CLAUDE_CODE_REMOTE signal the code uses.
# Raised 2026-09-28 to 125,350 B (+439): an agent-namespace resolver call with no proven host path now
# refuses (exit 6) instead of printing a relative root; the reference says so and gains its symptom row.
# Raised 2026-10-01 to 125,545 B (+195): benchmarks.md gives payments their own gross-margin row (no
# published benchmark; the margin depends on net vs gross booking) instead of sharing the marketplace comps.
# Raised 2026-10-01 from 125,545 to 126,584 B: a project builder gets its own type, so benchmarks.md gains its
# contextual gross-margin row (the public sector spread, no one bar) and revenue-model-types.md its section
# (progress billing, retentions, backlog conversion, concentration). Without the row an agent reading the
# shared table sees only the device bar under "Hardware", the bar the type exists to avoid.
# Raised 2026-10-01 from 126,584 to 126,609 B: the project-builder row says the sector figures are
# averages (individual companies spread wider), not a range of companies.
# Lowered 2026-10-02 from 126,609 to 126,559 B: skill-execution-model.md no longer claims the main thread
# reads references by the token on every tier; a skill started as a conversation's first message arrives
# with the token unfilled, and Step 0's READ_ROOT= replaces it.
# Lowered 2026-10-03 from 126,559 to 126,547 B: skill-execution-model.md's remaining statements that the
# token is filled on every tier now say where it is filled.
# Lowered 2026-10-03 from 126,547 to 126,335 B: skill-execution-model.md states that a generator-printed prompt
# never takes the plugin folder through the shell, and a paragraph restating the Context A path rule is cut
# to a pointer at it.
# Lowered 2026-10-03 from 126,335 to 126,315 B: skill-execution-model.md drops a stale name for the Context A
# input rule.
# Raised 2026-10-03 from 126,315 to 126,333 B: skill-execution-model.md says a sub-agent gets the workspace
# shell only when its tools: list names it, and names the real gap (a dispatch with no subagent_type).
# Raised 2026-10-03 from 126,333 to 126,392 B: skill-execution-model.md also names a dispatch to a wildcard
# built-in (general-purpose, claude) as a way a sub-agent reaches the shell.
# Raised 2026-10-04 from 126,392 to 126,593 B: skill-execution-model.md says the outputs no-delete rule is
# ours (older hosts refused deletes, newer ones allow them), and that the unfilled-token exception is a skill
# invoked on cloud before the conversation's first turn that needs a shell or file tool.
# Lowered 2026-10-05 from 126,593 to 126,590 B: skill-execution-model.md no longer names a shell reference folder.
# Raised 2026-10-05 from 126,590 to 126,603 B: skill-execution-model.md says never the shell's path to the plugin
# folder, rather than any path the shell printed.
# Raised 2026-10-05 from 126,603 to 126,745 B: skill-execution-model.md says scratch output goes in
# $STAGING_DIR, never a fixed /tmp/<name>, because /tmp is shared across sessions.
# Raised 2026-10-07 from 126,745 to 131,169 B: skill-execution-model.md gains the shared "Gates and run status"
# section every wired skill points at (start, bind, ask, exit 10, finish, resume, what a record proves). Not a
# SKILL.md ceiling: the section is the release's shared contract, written once instead of in six SKILL.mds,
# and every skill's critique corpus keeps at least 60 KB of headroom with it.
# Raised 2026-10-08 from 131,169 to 132,600 B: the "Gates and run status" section gains the rule for a request
# that says not to ask (FS_HOST_NO_ASK): no question by any means, exit 12 is a stop, nothing recorded by hand,
# the derive and wait lines, and when a run that failed for good is recorded with `run_status.py fail`. Written
# once here instead of in six SKILL.mds, which each carry only the one-sentence exit-12 route (and shrank).
ROOT_REFERENCES_CEILING = 132_600


def test_execution_model_names_every_dispatch_that_can_reach_the_shell() -> None:
    """A sub-agent has the workspace shell only when its tools list names it. The exceptions are a dispatch
    that names no agent and one that names a built-in whose tool list is a wildcard."""
    text = " ".join(
        (REPO_ROOT / "founder-skills" / "references" / "skill-execution-model.md").read_text(encoding="utf-8").split()
    )
    assert "gets the workspace shell (`mcp__workspace__bash`) only when its `tools:` names it" in text
    assert (
        "The gap is a dispatch that names no `subagent_type`, or one that names a wildcard built-in "
        "(`general-purpose`, `claude`):"
    ) in text


def test_shared_reference_tree_does_not_grow() -> None:
    """The plugin-root reference tree is bounded, because it now feeds six critique corpora."""
    root = REPO_ROOT / "founder-skills" / "references"
    files = sorted(p for p in root.rglob("*") if p.is_file())
    assert files, "no files under founder-skills/references/ — path layout changed?"
    size = sum(len(p.read_bytes()) for p in files)
    assert size <= ROOT_REFERENCES_CEILING, (
        f"founder-skills/references/ grew to {size:,} B (ceiling {ROOT_REFERENCES_CEILING:,}). This tree "
        "is shared: every skill that points at a file here carries its bytes in that skill's critique "
        "evidence corpus, so growth here spends SIX budgets at once, and cap-table has the least room. "
        "Raise the ceiling deliberately, with the reason recorded beside the constant."
    )


def test_every_opt_in_paid_lane_is_a_named_allowed_skip() -> None:
    """A paid test that is not one of the `_smoke` lanes the tag gates on runs only on its own opt-in, so a tag
    run skips it -- and the workflow reds any skip it was not told about. Every such test must be named in
    ALLOWED_SKIPS, or the first tag after adding one reds for a lane nobody meant to gate on."""
    workflow = (REPO_ROOT / ".github" / "workflows" / "skill-quality.yml").read_text(encoding="utf-8")
    start = workflow.find("ALLOWED_SKIPS = {")
    assert start != -1
    allowed = set(re.findall(r'"(test_\w+)"', workflow[start : workflow.find("}", start)]))
    opt_in = set()
    for lane in sorted((REPO_ROOT / "founder-skills" / "tests").glob("test_e2e_*.py")):
        opt_in |= {
            n
            for n in re.findall(r"^def (test_\w+)\(", lane.read_text(encoding="utf-8"), re.M)
            if not n.endswith("_smoke")
        }
    assert "test_deck_review_contradiction_lane" in opt_in  # positive control: the precedent is collected
    assert opt_in <= allowed, sorted(opt_in - allowed)


# --- the printed hand-over names every HTML page by what it is -------------------------------------
# Three skills print their hand-over from a closer that takes `--deliverable "LABEL=PATH"`. One generic
# `the interactive version=<the .html>` line cannot say which page it is, and where a skill makes two
# pages it hands the founder one of them.

_CLOSERS = {
    "financial-model-review": "fmr_closing_message.py",
    "competitive-positioning": "cp_closing_message.py",
    "market-sizing": "closing_message.py",
}


@pytest.mark.parametrize("skill", sorted(_CLOSERS))
def test_the_printed_hand_over_names_each_html_page(skill: str) -> None:
    text = (SKILLS_ROOT / skill / "SKILL.md").read_text(encoding="utf-8")
    block = re.search(rf'{re.escape(_CLOSERS[skill])}" --report.*?\n```', text, re.S)
    assert block is not None, skill
    pairs = re.findall(r'--deliverable "([^"=]+)=([^"]+)"', block.group(0))
    labels = [label for label, _ in pairs]
    assert len(labels) == len(set(labels)), pairs
    assert "the interactive version" not in labels, pairs
    pages = set(re.findall(r'-o "\$[A-Z_]+/([a-z_]+\.html)"', text))
    html_entries = [p for _, p in pairs if ".html" in p]
    assert pages and len(html_entries) == len(pages), (pages, pairs)


# --- a file search the skill instructs names the folder it searches -----------------------------------
# `Glob` and `Grep` with no `path` search the session's working folder. On a cloud session that folder is
# the home directory, so a pathless or `**/`-prefixed search walks everything under it. Every search a
# skill body, agent body or reference file tells the model to run must name its folder with the tool's
# `path` parameter. Prohibitions ("Do not Glob for it") and tool rosters ("Read/Write/Glob/Grep") are
# not instructions and are not matched.

_SEARCH_INSTRUCTION = re.compile(
    r"(?<![Nn]ot )(?<!NOT )\b(?:[Uu]se|[Rr]un|[Cc]all)\s+`?(?:Glob|Grep)\b`?|`(?:Glob|Grep)`\s+(?:with|for)\b"
)


def _instruction_surfaces() -> list[Path]:
    plugin = REPO_ROOT / "founder-skills"
    return sorted(
        [*_skill_md_files(), *(plugin / "agents").glob("*.md"), *SKILLS_ROOT.glob("*/references/**/*.md")]
        + sorted((plugin / "references").glob("**/*.md"))
    )


def _pathless_search_instructions() -> list[str]:
    hits: list[str] = []
    for path in _instruction_surfaces():
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if _SEARCH_INSTRUCTION.search(line) and "`path`" not in line:
                hits.append(f"{path.relative_to(REPO_ROOT)}:{n}: {line.strip()[:160]}")
    return hits


def test_every_instructed_file_search_names_its_folder() -> None:
    hits = _pathless_search_instructions()
    assert not hits, "a Glob/Grep instruction with no `path` parameter:\n" + "\n".join(hits)


def test_the_search_instruction_matcher_sees_both_forms() -> None:
    """Positive and negative controls, so the test above cannot pass by matching nothing."""
    assert _SEARCH_INSTRUCTION.search("Use `Glob` with pattern `x` to locate it")
    assert _SEARCH_INSTRUCTION.search("Use Grep to find the row")
    assert not _SEARCH_INSTRUCTION.search("Do not Glob for it, do not guess a different prefix")
    assert not _SEARCH_INSTRUCTION.search("Do NOT Glob for the file")
    assert not _SEARCH_INSTRUCTION.search('tools: ["Read", "Write", "Glob", "Grep"]')
    assert not _SEARCH_INSTRUCTION.search("Read/Write/Glob/Grep only")
    assert len(_instruction_surfaces()) > 20


@pytest.mark.parametrize("skill", sorted(SKILL_MD_CEILING))
def test_no_script_is_run_by_a_relative_path(skill: str) -> None:
    """A helper script is run as `python3 "$SCRIPTS/<name>.py"`, never `python3 scripts/<name>.py`.

    The shell's working folder is never the skill's folder, so a relative path fails with "No such
    file" and the guard the script implements is silently skipped.
    """
    files = [SKILLS_ROOT / skill / "SKILL.md", *sorted((SKILLS_ROOT / skill / "references").rglob("*.md"))]
    offenders = _relative_script_offenders(files)
    assert not offenders, offenders


# A helper script reached through a path relative to the shell's working folder: `python3 scripts/x.py`,
# quoted (`python3 "scripts/x.py"`), dotted (`./scripts/`, `../scripts/`), through `uv run`, or by
# changing into the folder first (`cd scripts && python3 x.py`). Case-sensitive, so `"$SCRIPTS/x.py"`
# and `"$PLUGIN_ROOT/scripts/x.py"` (the absolute forms) do not match.
_RELATIVE_SCRIPT = re.compile(
    r"(?:\bpython3?|\buv run)\s+[\"']?(?:\.{1,2}/)?scripts/" r"|\bcd\s+[\"']?(?:\.{1,2}/)?scripts\b"
)


def _relative_script_offenders(files: list[Path]) -> list[str]:
    plugin = SKILLS_ROOT.parent
    return [
        f"{p.relative_to(plugin) if p.is_relative_to(plugin) else p.name}:{n}"
        for p in files
        for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
        if _RELATIVE_SCRIPT.search(line)
    ]


@pytest.mark.parametrize(
    "line",
    [
        "python3 scripts/pdf_probe.py deck.pdf",
        "python scripts/pdf_probe.py",
        'python3 "scripts/pdf_probe.py" "$F"',
        "python3 'scripts/pdf_probe.py'",
        "python3 ./scripts/pdf_probe.py",
        "python3 ../scripts/pdf_probe.py",
        "uv run scripts/pdf_probe.py",
        "cd scripts && python3 pdf_probe.py",
        'cd "./scripts" && python3 pdf_probe.py',
    ],
)
def test_the_relative_script_check_catches_each_form(line: str, tmp_path: Path) -> None:
    """Seeded control: every way a relative script call can come back is caught by the scan."""
    seeded = tmp_path / "seeded.md"
    seeded.write_text(f"Run it first.\n\n```bash\n{line}\n```\n", encoding="utf-8")
    assert _relative_script_offenders([seeded]) == ["seeded.md:4"], line


@pytest.mark.parametrize(
    "line",
    [
        'python3 "$SCRIPTS/pdf_probe.py"',
        'python3 "$SHARED_SCRIPTS/check_handoff.py"',
        'python3 "$PROVISIONAL_ROOT/scripts/select_plugin_root.py"',
        'python3 "${CLAUDE_PLUGIN_ROOT}/scripts/founder_context.py"',
        "the helper scripts are in the skill's scripts/ folder",
    ],
)
def test_the_relative_script_check_passes_absolute_forms(line: str) -> None:
    """Negative control: the absolute forms the skills use, and prose, are not flagged."""
    assert not _RELATIVE_SCRIPT.search(line), line


def test_no_agent_command_or_shared_reference_runs_a_script_by_a_relative_path() -> None:
    """The same rule outside the six analysis skills: agent bodies, commands, the skills the per-skill
    check does not reach (`feedback`), and the shared references."""
    plugin = SKILLS_ROOT.parent
    files = [
        *sorted((plugin / "agents").glob("*.md")),
        *sorted((plugin / "commands").glob("*.md")),
        *[p for p in _skill_md_files() if p.parent.name not in SKILL_MD_CEILING],
        *sorted((plugin / "references").rglob("*.md")),
    ]
    assert len(files) > 10, f"scan reaches too few files: {files}"
    assert any(p.parent.name == "agents" for p in files) and any(p.parent.name == "feedback" for p in files)
    offenders = _relative_script_offenders(files)
    assert not offenders, offenders


_FIXED_TMP = re.compile(r"/tmp/[A-Za-z0-9_][\w.-]*")


def test_no_shipped_text_names_a_fixed_tmp_path() -> None:
    """The Cowork VM shares one /tmp across sessions, each its own Unix user, and files outlive the
    session: a fixed name an earlier session created cannot be overwritten, and reading it back reads
    THAT session's file. Scratch files go in the run's `mktemp -d` staging dir. `${TMPDIR:-/tmp}/...`
    inside a mktemp template is fine; a literal `/tmp/<name>` is not."""
    plugin = SKILLS_ROOT.parent
    files = sorted(plugin.rglob("*.md"))
    files = [p for p in files if "tests" not in p.relative_to(plugin).parts]
    assert any("lanes" in p.parts for p in files), "scan must reach nested reference dirs"
    offenders = [
        f"{p.relative_to(plugin)}:{n}: {m.group(0)}"
        for p in files
        for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
        for m in _FIXED_TMP.finditer(line)
    ]
    assert not offenders, offenders


def test_the_fixed_tmp_check_catches_a_fixed_name() -> None:
    """Negative control: the pattern the cap-table lane used to ship is flagged; a mktemp template is not."""
    assert _FIXED_TMP.search('cat /tmp/bv_responses.json | python3 "$SCRIPTS/x.py"')
    assert not _FIXED_TMP.search('mktemp -d "${TMPDIR:-/tmp}/cap-table-${SLUG}.staging.XXXXXX"')


def test_no_shipped_text_carries_a_host_answer_line_for_a_gate_a_hook_reads() -> None:
    """The dispatch hooks take an `FS_HOST_ANSWER <gate>=` or `FS_HOST_VALUE <gate>=` line in a founder's
    own message as the question answered. Where a skill's text arrives as the conversation's first message,
    an example line written in it would answer the question for the founder, so no shipped markdown may
    carry one at a line start for a gate a hook holds."""
    sys.path.insert(0, str(REPO_ROOT / "founder-skills" / "scripts"))
    import _gates  # type: ignore[import-not-found]

    names = "|".join(re.escape(g) for g in _gates.HELD_GATES)
    line = re.compile(
        r"(?m)^[ \t]*FS_HOST_(?:ANSWER|VALUE)[ \t]+(?:" + names + r")(?:\.[A-Za-z0-9][A-Za-z0-9_.+-]*)?[ \t]*="
    )
    assert line.search("Size it.\n  FS_HOST_VALUE ms_two_figures.arpu = typed | 9\n"), "control: the pattern bites"
    found = [
        str(p.relative_to(REPO_ROOT))
        for p in sorted((REPO_ROOT / "founder-skills").rglob("*.md"))
        if line.search(p.read_text(encoding="utf-8"))
    ]
    assert found == []


# --- recorded gates ----------------------------------------------------------------------------------------

# The skills whose Step 0 starts the run's record; each skill's wiring commit adds itself.
WIRED = ("deck-review", "financial-model-review", "market-sizing", "ic-sim", "competitive-positioning", "cap-table")
# cap-table's Step 0 sits past the window by construction: everything before it (Reliance Boundary, execution
# model, the four input lanes, the artifact pipeline, coverage and disclosure) is about 27 KB, and moving it is the
# withdrawn front-loading/reordering class (an e2e A/B and a ceiling raise). After a compaction the producers carry
# the instruction back: each refuses an empty --run-id (RUN_ID_REQUIRED) and an unrecorded question (exit 10).
# Pinned so it reds the day the block would fit, and the exemption is then removed.
WINDOW_EXEMPT = frozenset({"cap-table"})
# `record_gate_answer.py open` lines per SKILL.md, the companion to ASKUSER_MENTIONS: an open site added or
# removed changes this count, and the gate-site test in the skill's own contract file says which.
OPEN_LINES: dict[str, int] = {
    "deck-review": 2,
    "market-sizing": 2,
    "financial-model-review": 2,
    "ic-sim": 2,
    "competitive-positioning": 6,
    "cap-table": 10,
}


def _body_without_frontmatter(skill: str) -> str:
    text = (SKILLS_ROOT / skill / "SKILL.md").read_text(encoding="utf-8")
    return text[text.index("\n---\n", 4) + len("\n---\n") :]


@pytest.mark.parametrize("skill", WIRED)
def test_step0_starts_the_run_record_inside_the_reattached_window(skill: str) -> None:
    """`run_status.py start` sits after the artifacts-root line, the unsupported-environment stop and the
    "I can run it now" offer, and before Step 1, ending where a compaction keeps it; the old mint line is gone."""
    body = _body_without_frontmatter(skill)
    start = body.index(f'run_status.py" start --skill {skill}')
    assert "<<'FS_HOST_EOF'" in body[start : start + 300]
    assert body.index('resolve_artifacts_root.py"   # prints ARTIFACTS_ROOT') < start
    assert body.index("`UNSUPPORTED_ENVIRONMENT`, stop here") < start
    if "I can run it now" in body:
        assert body.index("I can run it now") < start
    assert start < body.index("### Step 1:")
    fence_end = body.index("```", start) + 3
    if skill in WINDOW_EXEMPT:
        assert fence_end > _REATTACH_RETAINED_CHARS - _REATTACH_PREFIX_MAX_CHARS, (
            f"{skill}'s start block now ends inside the window ({fence_end}); drop it from WINDOW_EXEMPT"
        )
    else:
        assert fence_end <= _REATTACH_RETAINED_CHARS - _REATTACH_PREFIX_MAX_CHARS, fence_end
    text = (SKILLS_ROOT / skill / "SKILL.md").read_text(encoding="utf-8")
    assert 'RUN_ID="${RUN_ID:-' not in text and "date -u +%Y%m%dT%H%M%SZ" not in text


@pytest.mark.parametrize("skill", sorted(SKILL_MD_CEILING))
def test_each_skill_opens_its_recorded_gates_a_counted_number_of_times(skill: str) -> None:
    text = (SKILLS_ROOT / skill / "SKILL.md").read_text(encoding="utf-8")
    n = text.count('record_gate_answer.py" open') + text.count("record_gate_answer.py open")
    assert n == OPEN_LINES[skill], f"{skill}: {n} open lines, expected {OPEN_LINES[skill]}"
