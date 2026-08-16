"""The second read is not an independent reading of the deck — no surface may say it is.

WHAT IS ACTUALLY TRUE. A sub-agent re-transcribes the figure-bearing slides and each ledger
figure's verbatim `quote` is matched against that transcript. The reader never saw the ledger,
so the check catches a quote that was invented or paraphrased. That is the whole of it.

WHAT IS FALSE, and what this test exists to keep out:

  * that the second reader reads the DECK. It does not. `SKILL.md`'s SECOND_READ dispatch
    inlines the main thread's own extracted text, so both readings descend from one act of
    reading. Measured on a live run: 12 of the second read's 13 transcript paragraphs were
    byte-identical substrings of the prompt it was given.
  * that it is a VISION transcription. It is not, and the calibration numbers that were
    measured against a prototype which did read by vision do not describe what ships.
  * that it corroborates FIGURES, NUMBERS or VALUES. It corroborates a quote.
    `_quote_match.py` documents that the value-token machinery is deliberately absent, so a
    figure recorded as `$45B` passes against a genuine quote reading `$46B`.

WHY A RATCHET AND NOT A ONE-TIME EDIT. Five separate passes over these surfaces each found
occurrences the previous pass missed — the count went 4 -> 11 -> 14 -> 18 -> 32 across 13
files. The claim regrows because it is a natural way to describe the step. A test is the only
thing that holds it.

WHY A TREE SCAN AND NOT A FILE LIST. A fixed manifest cannot discover a surface in a file
nobody thought to list, which is precisely how the last four occurrences were missed. This
walks the shipped tree and excludes by justified exception instead.

IT FLAGS NEGATIONS TOO, AND THAT IS DELIBERATE. Substring matching cannot tell "it is an
independent reading" from "it is not an independent reading", so a docstring that denies the
claim trips this as readily as one that makes it. That happened while these surfaces were
being corrected. Rather than teach the matcher about negation -- which is where a phrase
blocklist starts losing -- write the true statement without the phrase: "both readers are
handed the same extracted text" says it, and cannot be misread by someone skimming.
"""

from __future__ import annotations

import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

SCANNED_SUFFIXES = {".py", ".md", ".json"}

# Substrings, matched case-insensitively. Stems rather than exact phrases: an earlier
# five-phrase list missed three live variants, one of them only because it was hyphenated.
FORBIDDEN = (
    "independent second read",
    "independent read",
    "independent-read",
    "independent reading",
    "independent transcription",
    "second, separate reading",
    "corroborated twice",
    "two readings that never saw each other",
    "fresh vision",
)

# Every exclusion carries its reason. Do not add one without stating why the claim is
# permitted to survive there.
EXCLUDED_DIRS = {
    ".git",
    "__pycache__",
    ".venv",
    "node_modules",
    "docs",  # internal analysis; discusses the false claim in order to remove it
    "evals",  # not shipped; prototype and bench code
    "evals-local",  # gitignored throwaway harnesses, including the prototype this diverged from
}

EXCLUDED_FILES = {
    # A changelog records what was claimed at the time it was written. Rewriting a shipped
    # entry hides that the claim was made; the correction belongs in the next entry instead.
    "CHANGELOG.md",
    # This file names the forbidden strings in order to forbid them.
    "test_no_independence_claims.py",
    # Its companion states the contract positively, which means enumerating the claims no
    # surface may make — so it names them too, in a docstring and in a failure message. Same
    # exemption, same reason. (That this scan flagged it on the day it was added is the
    # negation limitation documented above, working exactly as described.)
    "test_second_read_claims_are_approved.py",
}


def _scan() -> list[tuple[pathlib.Path, int, str, str]]:
    found: list[tuple[pathlib.Path, int, str, str]] = []
    for path in REPO_ROOT.rglob("*"):
        if not path.is_file() or path.suffix not in SCANNED_SUFFIXES:
            continue
        if set(path.parts) & EXCLUDED_DIRS or path.name in EXCLUDED_FILES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            lowered = line.lower()
            for stem in FORBIDDEN:
                if stem in lowered:
                    found.append((path.relative_to(REPO_ROOT), lineno, stem, line.strip()))
                    break
    return found


def test_no_surface_claims_the_second_read_is_independent() -> None:
    hits = _scan()
    if hits:
        detail = "\n".join(f"  {p}:{n}  [{stem}]  {line[:100]}" for p, n, stem, line in hits)
        pytest.fail(
            f"{len(hits)} surface(s) use a phrase that claims the second read is an independent "
            f"reading of the deck:\n{detail}\n\n"
            "It reads the main thread's own extracted text, and it matches quotes, not values. "
            "Say what the check establishes: a second reader that never saw the ledger re-found "
            "the quote. See this module's docstring."
        )


# WHAT A GREEN HERE DOES NOT PROVE, stated because the failure message above used to
# over-claim it. This matches literal stems. It does not catch a noun form ("the
# independence is the whole value"), a paraphrase ("corroborates each figure" — which
# asserts the value, not the quote), or a sentence that implies the slides were read twice
# ("when I read the slides a second time"). Three such phrasings survived this scan and were
# found by hand review afterwards.
#
# Two reasons not to fix that by adding stems. A blanket "independence" stem flags a TRUE
# statement — the reader genuinely is independent OF THE LEDGER, which is the one property
# the step does have. And a blocklist long enough to catch paraphrase is the unwinnable
# design `cowork-tests/leak_scan.py` already documents.
#
# The stronger form is an allowed-wording assertion on each known founder-facing and
# contract surface, so drift has to pass a positive check rather than dodge a negative one.
# That is not built here; until it is, this test is a floor and hand review is still load-
# bearing on any edit to the second-read prose.


def test_the_scan_reaches_the_files_that_carry_the_claim() -> None:
    """Non-vacuity: the scan must actually walk the surfaces this rule is about.

    Without this, an over-broad exclusion or a suffix typo turns the ratchet into a test that
    passes because it looks at nothing — the failure mode that let an earlier guard report
    clean while the claim sat in three files it never opened.
    """
    scanned = {
        path.relative_to(REPO_ROOT)
        for path in REPO_ROOT.rglob("*")
        if path.is_file()
        and path.suffix in SCANNED_SUFFIXES
        and not (set(path.parts) & EXCLUDED_DIRS)
        and path.name not in EXCLUDED_FILES
    }
    must_reach = [
        pathlib.Path("CLAUDE.md"),
        pathlib.Path("founder-skills/agents/deck-review.md"),
        pathlib.Path("founder-skills/skills/deck-review/SKILL.md"),
        pathlib.Path("founder-skills/skills/deck-review/scripts/reconcile.py"),
        pathlib.Path("founder-skills/skills/deck-review/scripts/compose_report.py"),
        pathlib.Path("founder-skills/skills/deck-review/scripts/ledger.py"),
        pathlib.Path("founder-skills/skills/deck-review/scripts/_quote_match.py"),
        pathlib.Path("founder-skills/skills/deck-review/references/schemas/ledger.schema.json"),
        pathlib.Path("founder-skills/skills/deck-review/references/schemas/reconciliation.schema.json"),
    ]
    missing = [p for p in must_reach if p not in scanned]
    assert not missing, f"the scan does not reach: {missing}"
