"""CLAUDE.md and its reference files under `.claude/rules/`.

CLAUDE.md is loaded into every session; the files under `.claude/rules/` attach only when a session opens a
file in their `paths:` scope. So a rule that guards a destructive, public, paid or commit action is copied word
for word into CLAUDE.md's Guards section, and its source stays where it reads in context (the numbered release
steps). Two copies drift unless something holds them equal; `test_claude_md_guards_match_source` does.

The loader cuts a scoped file over its per-file limit silently when it attaches it (40k chars on a
200K-context model), and warns on CLAUDE.md over that limit. `test_instruction_file_sizes` keeps every file
under 38k chars, so a file that grows reds here first.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CLAUDE_MD = REPO_ROOT / "CLAUDE.md"
RULES_DIR = REPO_ROOT / ".claude" / "rules"
SIZE_CAP = 38_000

# (id, source file under .claude/rules/, head anchor, tail anchor, guard-only edits as (old in source, new in copy))
# Head and tail each occur once in the source; the copy is the source span from head through tail, with the
# guard-only edits applied. An edit applied to both copies is already in the source and is not listed.
GUARDS: tuple[tuple[str, str, str, str, tuple[tuple[str, str], ...]], ...] = (
    (
        "push-main",
        "release.md",
        "**Pushing `main` ships.** Users install ",
        "ist in `.claude/rules/e2e-dispatch.md`).",
        (),
    ),
    (
        "release-step-3",
        "release.md",
        '3. `git commit -s -m "release: vX.Y.Z"`,',
        "l/`,\n   `docs/plans/` or `evals-local/`.",
        (),
    ),
    (
        "release-step-5-rerun",
        "release.md",
        "   - A red lane: read the failing assert",
        "ads as LLM variance; never re-run blind.",
        (),
    ),
    (
        "release-step-5-failure",
        "release.md",
        "   - A real failure: the version has not",
        "ly once `main`\n     carries the version.",
        (),
    ),
    (
        "release-step-5-optin-deck",
        "release.md",
        "   - **The three opt-in deck-review lane",
        "e --tb=short -s --basetemp /tmp/fs-e2e`.",
        (),
    ),
    (
        "release-step-5-optin-fmr",
        "release.md",
        "   - **The opt-in financial-model-review",
        "e2e` (`--basetemp` OUTSIDE `~/.claude`).",
        (),
    ),
    (
        "release-step-5-compaction",
        "release.md",
        "   - **The market-sizing compaction lane",
        "ream fails as VOID, and is not a result.",
        (),
    ),
    (
        "release-step-6",
        "release.md",
        "6. **Green: fast-forward `main`, then ta",
        "e-tag\n     a version `main` has carried.",
        (("(step 8's command)", "(step 8 of `.claude/rules/release.md`)"),),
    ),
    (
        "release-step-7",
        "release.md",
        "7. **Delete the release branch if it sti",
        "Y.Z && git push origin :release/vX.Y.Z`.",
        (),
    ),
    (
        "release-step-8",
        "release.md",
        "8. **The GitHub Release is now created F",
        "cripts/changelog-notes.py vX.Y.Z)\n   ```",
        (),
    ),
    (
        "sync-test-repo",
        "release.md",
        "**`sync-test-repo.sh` RUNS ONLY WHEN EXP",
        " exercises a build you would never ship.",
        (),
    ),
    (
        "retag",
        "release.md",
        "**Already-distributed retag pitfall:** a",
        " not always coordinatable across users).",
        (
            ("the push in step 6 ships", "the push in step 6 of `.claude/rules/release.md` ships"),
            ("(step 6 says why)", "(step 6 there says why)"),
        ),
    ),
    (
        "harness-evaluator",
        "cowork-harness.md",
        "- Do NOT swap `--evaluator-model` on a f",
        "`cost:` line prints the evaluator share.",
        (),
    ),
    (
        "harness-run-dir",
        "cowork-harness.md",
        "- `--run-dir <fresh dir>` isolates a run",
        "Never isolate a paid re-record that way.",
        (),
    ),
    (
        "harness-eval",
        "cowork-harness.md",
        "- `eval` (4.2.0, EXPERIMENTAL upstream) ",
        "is a signal to investigate, never proof.",
        (),
    ),
    (
        "git-hooks",
        "hooks.md",
        "- **pre-commit** (`scripts/hooks/pre-com",
        "ll checked before it leaves the machine.",
        (),
    ),
)

_BLOCK = re.compile(r"<!-- guard:([\w-]+) source:(\S+) -->\n(.*?)<!-- /guard -->", re.S)


def _guard_problems(claude: str) -> list[str]:
    problems: list[str] = []
    blocks = {gid: (src, body) for gid, src, body in _BLOCK.findall(claude)}
    if len(blocks) != len(_BLOCK.findall(claude)):
        problems.append("a guard id appears twice in CLAUDE.md")
    want = {g[0] for g in GUARDS}
    if set(blocks) != want:
        problems.append(f"guard ids differ: missing {sorted(want - set(blocks))}, extra {sorted(set(blocks) - want)}")
    for gid, src_name, head, tail, pairs in GUARDS:
        if gid not in blocks:
            continue
        src_marker, body = blocks[gid]
        if src_marker != f".claude/rules/{src_name}":
            problems.append(f"{gid}: marker names {src_marker}, the table names {src_name}")
            continue
        src = (RULES_DIR / src_name).read_text(encoding="utf-8")
        for old, new in pairs:
            if src.count(old) != 1:
                problems.append(
                    f"{gid}: guard-only edit's old text {old!r} occurs {src.count(old)} times in {src_name}"
                )
            if body.count(new) != 1:
                problems.append(f"{gid}: guard-only edit's new text {new!r} occurs {body.count(new)} times in the copy")
            src = src.replace(old, new)
        if src.count(head) != 1 or src.count(tail) != 1:
            problems.append(f"{gid}: its head or tail anchor does not occur exactly once in {src_name}")
            continue
        span = src[src.index(head) : src.index(tail) + len(tail)]
        if body.rstrip("\n") != span:
            problems.append(f"{gid}: CLAUDE.md's copy differs from {src_name}; edit both together")
    return problems


def test_claude_md_guards_match_source() -> None:
    problems = _guard_problems(CLAUDE_MD.read_text(encoding="utf-8"))
    assert not problems, "\n".join(problems)


def test_a_cut_guard_copy_reds() -> None:
    """Lever: drop the last sentence of one copy; equality, not containment, must see it."""
    claude = CLAUDE_MD.read_text(encoding="utf-8")
    cut = "never re-run blind."
    assert claude.count(cut) == 1, "the lever's sentence moved; pick another"
    problems = _guard_problems(claude.replace(" " + cut, ""))
    assert any(p.startswith("release-step-5-rerun:") for p in problems), problems
    dropped = _BLOCK.sub("", claude, count=1)
    assert any("missing ['push-main']" in p for p in _guard_problems(dropped))


def _rules_files() -> list[Path]:
    files = sorted(RULES_DIR.glob("*.md"))
    assert files, "no .claude/rules/*.md"
    return files


def _paths(text: str) -> list[str]:
    m = re.match(r"---\npaths:\n((?:  - \"[^\"\n]+\"\n)+)---\n", text)
    return re.findall(r'  - "([^"\n]+)"', m.group(1)) if m else []


@pytest.mark.parametrize("path", [CLAUDE_MD, *sorted(RULES_DIR.glob("*.md"))], ids=lambda p: p.name)
def test_instruction_file_sizes(path: Path) -> None:
    n = len(path.read_text(encoding="utf-8"))
    assert n <= SIZE_CAP, (
        f"{path.relative_to(REPO_ROOT)} is {n:,} chars, over {SIZE_CAP:,}. The loader cuts a scoped file over its "
        f"per-file limit silently, and warns on CLAUDE.md. Move a section to another file (and its index line)."
    )


def test_every_rules_file_is_scoped_and_indexed() -> None:
    """A rules file with no `paths:` loads at startup and counts against the limit; one CLAUDE.md does not name
    is reachable only by opening a file in its scope."""
    claude = CLAUDE_MD.read_text(encoding="utf-8")
    for f in _rules_files():
        assert _paths(f.read_text(encoding="utf-8")), f"{f.name} has no `paths:` front matter"
        assert f.name in claude, f"CLAUDE.md's index does not name {f.name}"
