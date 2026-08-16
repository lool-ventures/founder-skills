"""Every surface that describes the second read must say one of the approved things.

THE COMPANION TO `test_no_independence_claims.py`, AND THE STRONGER HALF. That test forbids
a list of phrases; this one requires specific approved wording. The difference matters
because a blocklist can only catch what someone thought to list, and measurably did not:
across five passes over these same surfaces, the stem sweep missed a noun form
("the independence is the whole value"), a paraphrase ("corroborates each figure", which
asserts the VALUE rather than the quote), an implied re-read ("when I read the slides a
second time"), and a claim that was false on a different axis entirely ("a paraphrase
fails" — untrue, because matching falls back to a fuzzy pass at 0.85). Each was found by
hand afterwards. A positive assertion cannot be dodged that way: drift fails, and the
author has to come here and make a deliberate claim.

WHAT THE SECOND READ ACTUALLY ESTABLISHES, which is the contract this file pins:

  * A reader that never saw the ledger looked for the figure's quoted wording in the same
    extracted deck text, and found it.

WHAT IT DOES NOT ESTABLISH, and what no surface may imply:

  * NOT an independent reading of the deck. The reader receives the main thread's own
    extraction (`SKILL.md`'s SECOND_READ dispatch inlines it), so both readings descend
    from one act of reading. Measured on a live run: 12 of the second read's 13 transcript
    paragraphs were byte-identical substrings of the prompt it was given.
  * NOT a re-reading of the slides. The slides were read once; the text was read twice.
  * NOT anything about the VALUE. `_quote_match.py` documents that value binding is
    deliberately absent, so `raw="$45B"` passes against a genuine quote reading `$46B`.
  * NOT slide identity. `verify()` matches against the whole transcript without consulting
    `Figure.slide`, so a quote can be found on a slide the figure does not claim.
  * NOT that a paraphrase fails. Matching falls back to fuzzy at 0.85, so a near-identical
    restatement passes. A genuinely reworded sentence does fail.

WHEN THIS TEST FAILS. Either the wording drifted, or you improved it. If you improved it,
update the expected string here **and** satisfy yourself that the new wording claims
nothing from the second list. That deliberate step is the entire value of this file; do
not update it mechanically to make a red suite green.

Founder-facing strings additionally may not contain pipeline vocabulary — the founder has
no stake in an artifact name, a script, or a step label.
"""

from __future__ import annotations

import pathlib
import re

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
DECK_REVIEW = REPO_ROOT / "founder-skills" / "skills" / "deck-review"

# (label, path, required substring, audience)
#
# `audience` is "founder" when the string is rendered into a report a founder reads, and
# "contract" when it instructs an agent or documents the gate for a maintainer. Founder
# strings carry the extra vocabulary check below.
APPROVED: list[tuple[str, pathlib.Path, str, str]] = [
    (
        "coverage line, partial",
        DECK_REVIEW / "scripts" / "compose_report.py",
        # Branch-specific on purpose. A bare "had their wording checked back against your
        # deck" is a SUBSTRING of the all-verified line below, so it would keep passing
        # while this branch drifted. Caught by mutating the branch and watching the suite
        # stay green — an anchor that another anchor subsumes asserts nothing of its own.
        "of them had their wording checked back against your deck — the other ",
        "founder",
    ),
    (
        "coverage line, all verified",
        DECK_REVIEW / "scripts" / "compose_report.py",
        "all of them had their wording checked back against your deck",
        "founder",
    ),
    (
        "numbers section preamble",
        DECK_REVIEW / "scripts" / "compose_report.py",
        "had its wording checked back against ",
        "founder",
    ),
    (
        "numbers section, dropped figures",
        DECK_REVIEW / "scripts" / "compose_report.py",
        "Figures whose wording could not be found again were dropped rather than guessed at.",
        "founder",
    ),
    (
        "agent contract, quote is verbatim",
        REPO_ROOT / "founder-skills" / "agents" / "deck-review.md",
        "A second reader, who never sees your ledger, looks for that",
        "contract",
    ),
    (
        # CORRECTED. This anchor used to be "a reworded sentence fails it", and that claim
        # is false — the same defect the rest of this file exists to catch, committed by
        # the file itself. Measured against `_quote_match.quote_in_doc`:
        #     "ARR increased 40%"          vs "ARR decreased 40%"      -> passes (fuzzy)
        #     "Revenue will double"        vs "Revenue will decline"   -> passes (fuzzy)
        #     "Market size of $45 billion" vs "... of $46 billion"     -> passes (fuzzy)
        # After the exact and normalised passes it falls back to a similarity ratio at
        # 0.85, so rewordings — including negations, directional reversals and changed
        # numbers — survive it. The agent body now states what the gate does establish:
        # a quote that is not found AT ALL is dropped.
        "agent contract, matching is not exact",
        REPO_ROOT / "founder-skills" / "agents" / "deck-review.md",
        "it never checks the figure's value",
        "contract",
    ),
    (
        "drop reason, quote absent",
        DECK_REVIEW / "scripts" / "reconcile.py",
        'f.drop_reason = "quote not found in the second read"',
        "contract",
    ),
    (
        "refusal reason, stated side uncorroborated",
        DECK_REVIEW / "scripts" / "reconcile.py",
        '"the stated figure was not corroborated by the second read"',
        "contract",
    ),
    (
        "gate docstring, quote not value",
        DECK_REVIEW / "scripts" / "reconcile.py",
        'this QUOTE invented?" -- not whether the VALUE is right',
        "contract",
    ),
    (
        "ledger extraction instruction",
        DECK_REVIEW / "SKILL.md",
        "re-found by a ledger-blind reader in the same extracted text",
        "contract",
    ),
]

# Vocabulary that means nothing to a founder. Deliberately short: this guards the specific
# strings above, not prose generally — `cowork-tests/leak_scan.py` is the general detector.
PIPELINE_WORDS = (
    "second_read",
    "reconcile",
    "ledger",
    "artifact",
    "producer",
    "hand-off",
    "handoff",
    "sub-agent",
    "dispatch",
    "gate",
    "transcript",
)


@pytest.mark.parametrize(
    ("label", "path", "expected", "audience"),
    APPROVED,
    ids=[row[0] for row in APPROVED],
)
def test_approved_wording_is_present(label: str, path: pathlib.Path, expected: str, audience: str) -> None:
    assert path.is_file(), f"{label}: {path} does not exist"
    text = path.read_text(encoding="utf-8")
    if expected not in text:
        pytest.fail(
            f"{label}: the approved wording is gone from {path.relative_to(REPO_ROOT)}.\n\n"
            f"  expected to find: {expected!r}\n\n"
            "Either it drifted or you improved it. If you improved it, update the expected\n"
            "string here — and check the new wording claims none of: an independent reading\n"
            "of the deck, a re-reading of the slides, anything about the figure's VALUE,\n"
            "slide identity, or that a paraphrase fails. See this module's docstring."
        )


@pytest.mark.parametrize(
    ("label", "expected"),
    [(row[0], row[2]) for row in APPROVED if row[3] == "founder"],
    ids=[row[0] for row in APPROVED if row[3] == "founder"],
)
def test_founder_facing_wording_carries_no_pipeline_vocabulary(label: str, expected: str) -> None:
    lowered = expected.lower()
    hits = [w for w in PIPELINE_WORDS if w in lowered]
    assert not hits, f"{label}: founder-facing text names internal machinery: {hits}"


def test_the_pinned_strings_are_not_trivially_satisfiable() -> None:
    """Non-vacuity: a pinned string must be specific enough to fail when the claim changes.

    A one-word anchor would pass against almost any rewrite, which would make the whole
    file decorative — the exact failure mode of the blocklist this test exists to
    strengthen. Nothing here may be shorter than a clause.
    """
    for label, _path, expected, _audience in APPROVED:
        assert len(expected) >= 25, f"{label}: anchor {expected!r} is too short to be meaningful"
        assert len(expected.split()) >= 4, f"{label}: anchor {expected!r} is not a clause"


def test_every_approved_source_file_exists_and_is_covered() -> None:
    """The three files that carry the founder-facing and contract claims are all pinned.

    Guards against a surface being added to the pipeline and silently going unasserted —
    which is how the last four occurrences of the false claim were missed.
    """
    covered = {row[1].resolve() for row in APPROVED}
    must_cover = {
        (DECK_REVIEW / "scripts" / "compose_report.py").resolve(),
        (DECK_REVIEW / "scripts" / "reconcile.py").resolve(),
        (DECK_REVIEW / "SKILL.md").resolve(),
        (REPO_ROOT / "founder-skills" / "agents" / "deck-review.md").resolve(),
    }
    missing = must_cover - covered
    assert not missing, f"surfaces with no approved-wording anchor: {sorted(str(p) for p in missing)}"


def test_the_quote_matcher_still_falls_back_to_fuzzy() -> None:
    """The reason "a paraphrase fails" is NOT an approved claim.

    Pinned because the claim was false for the whole life of the feature and was corrected
    only after a reviewer probed the matcher. If the fuzzy fallback is ever removed, the
    stricter wording becomes true and this test should be updated together with it.
    """
    quote_match = (DECK_REVIEW / "scripts" / "_quote_match.py").read_text(encoding="utf-8")
    assert re.search(r"DEFAULT_FUZZY_THRESHOLD\s*=\s*0\.8", quote_match), (
        "the fuzzy fallback is gone or its threshold moved — re-check every surface that "
        "describes what the match tolerates, including agents/deck-review.md"
    )


def test_what_the_matcher_actually_accepts_is_pinned_behaviourally() -> None:
    """The structural pin above sees the threshold constant; this sees the consequence.

    A constant can stay put while the surrounding passes change, and the claim these
    files make is about behaviour, not about a number. Each case below was measured
    against the shipped matcher and each one is a reworded sentence that PASSES — which
    is why "a reworded sentence fails it" had to be withdrawn from the agent body.

    If any of these starts failing the matcher has been hardened, which is good news: the
    stricter wording becomes available and every surface describing the match should be
    revisited in the same change.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location("_qm_probe", DECK_REVIEW / "scripts" / "_quote_match.py")
    assert spec and spec.loader
    qm = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(qm)

    accepted_rewordings = [
        ("ARR increased 40% year over year in 2024", "ARR decreased 40% year over year in 2024"),
        ("Revenue will double over the next twelve months", "Revenue will decline over the next twelve months"),
        ("Total market size of $45 billion by 2030", "Total market size of $46 billion by 2030"),
    ]
    for quote, doc in accepted_rewordings:
        found, _how, _ratio = qm.quote_in_doc(quote, doc)
        assert found, (
            f"the matcher now REJECTS {quote!r} against {doc!r}. It has been hardened — revisit "
            "agents/deck-review.md, which currently tells the agent the match is not word-for-word."
        )

    # The floor the gate does hold: text absent from the document is not found.
    absent, _how, _ratio = qm.quote_in_doc("Gross margin of 82% on enterprise contracts", "Nothing of the sort here.")
    assert not absent, "the matcher accepts a quote with no counterpart in the document at all"


# The blocklist half. The approved-wording anchors above check that each surface says the
# right thing SOMEWHERE; they cannot see a false claim in the next paragraph, and the
# per-file coverage rule is satisfied by one hit. Measured cost of that gap: after the
# agent body was corrected, `SKILL.md`, `ledger.schema.json` and `reconcile.py`'s module
# docstring all still said a reworded quote or a paraphrase fails the gate — three live
# surfaces, one of them the production extraction instruction, all green.
#
# Stems, not whole phrases, for the reason the independence sweep uses them: the same claim
# was written three different ways.
# Only stems that cannot appear inside a TRUE statement. "word for word" was tried and
# withdrawn: the corrected agent body says the match "is not enforced word for word", so
# the stem flagged the fix. A blocklist that fires on the correction teaches the next
# author to delete the correction.
_OVERCLAIM_STEMS = (
    "reworded sentence fails",
    "a reworded one",
    "paraphrase defeats",
    "paraphrase fails",
    "exact wording in the same",
)

_CLAIM_SURFACES = (
    DECK_REVIEW / "SKILL.md",
    DECK_REVIEW / "scripts" / "reconcile.py",
    DECK_REVIEW / "scripts" / "ledger.py",
    DECK_REVIEW / "scripts" / "_quote_match.py",
    DECK_REVIEW / "references" / "schemas" / "ledger.schema.json",
    DECK_REVIEW / "references" / "schemas" / "reconciliation.schema.json",
    REPO_ROOT / "founder-skills" / "agents" / "deck-review.md",
)


def test_no_surface_claims_the_match_is_stricter_than_it_is() -> None:
    """Sweep every surface, not just the one whose anchor was being edited."""
    hits: list[str] = []
    for path in _CLAIM_SURFACES:
        assert path.exists(), f"claim surface has moved or been renamed: {path}"
        lowered = path.read_text(encoding="utf-8").lower()
        hits += [f"{path.name}: {stem!r}" for stem in _OVERCLAIM_STEMS if stem in lowered]
    assert not hits, "surfaces overstating what the quote match establishes:\n  " + "\n  ".join(hits)


def test_the_overclaim_sweep_reaches_real_files() -> None:
    """Non-vacuity: a sweep over a mistyped path list passes by finding nothing."""
    assert len(_CLAIM_SURFACES) >= 6
    corpus = "\n".join(p.read_text(encoding="utf-8") for p in _CLAIM_SURFACES)
    assert corpus.count("quote") > 20, "the sweep is not reading the files that discuss quoting"
