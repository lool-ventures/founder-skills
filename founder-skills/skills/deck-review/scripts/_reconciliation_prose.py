#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Founder-facing reconciliation sentences, shared by both renderers.

`report.md` and `report.html` are two renderers over one artifact set, and a sentence
present in one and absent from the other is the delivery-defect class this fleet has
shipped. One source is what keeps them honest.

`emphasis` wraps script-authored counts; `escape` wraps model- and ledger-derived text.
They are separate because a single callable would escape only the emphasised substring and
let an interpolated claim reach the page raw. compose passes `escape=str`; visualize passes
its HTML escaper.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

# The classes the "could not be settled" sentence is TRUE of: two sides that could not be
# compared, or a comparison withdrawn on review. `convention_differs` is deliberately absent
# -- see the note where it gets its own sentence.
INCONCLUSIVE_SUPPRESSION_CLASSES = ("incomparable", "downgraded")


def _as_list(value: Any) -> list[Any]:
    """Copy of compose's coercer. Sibling helpers are per-script by convention."""
    return value if isinstance(value, list) else []


def _as_dict(value: Any) -> dict[str, Any]:
    """Copy of compose's coercer. Sibling helpers are per-script by convention."""
    return value if isinstance(value, dict) else {}


def coverage_line(
    reconciliation: dict[str, Any],
    emphasis: Callable[[str], str],
    escape: Callable[[str], str] = str,
) -> str:
    """How much of the deck this actually looked at, in the founder's terms.

    Without it the section's opening sentence is true and its silence is misleading: it
    describes what was done to the figures SHOWN and says nothing about how many were read,
    how many survived corroboration, or how many comparisons were run. A founder reading a
    short list reasonably infers there was little to find.

    Deliberately counts rather than characterises. "12 could not be confirmed" is a fact
    the founder can act on -- they know which of their slides are hard to read. A
    percentage or a grade would be a judgement this has no basis for.

    THE CLOSING CLAUSE SAYS A CAREFUL READER WOULD FIND MORE, and that is measured, not
    modesty. Across seven real decks this pipeline reproduced 4 of 16 findings an expert
    had graded real on the same decks. So a short list is weak evidence of clean numbers,
    and the section has to say so or its silence does the lying.

    What it deliberately does NOT do is quantify that. The 4-of-16 is measured against a
    REPRODUCIBILITY target -- verdicts on what one frozen bench draw surfaced -- not
    against everything an expert would find, so "roughly a quarter" would state a
    precision the evidence does not support, and it would go stale the moment recall
    moves. Qualitative here is the honest register; the counts above carry what is
    actually known.
    """
    if reconciliation.get("status") != "checked":
        return ""
    total = reconciliation.get("figures_total")
    verified = reconciliation.get("figures_verified")
    computed = reconciliation.get("relations_proposed")
    if not isinstance(total, int) or not isinstance(verified, int):
        return ""
    # WHAT THE CHECK IS AGAINST. Any phrasing implying the figure was re-read from the deck
    # overstates the source: both readers are handed the SAME extracted text, so what is
    # re-found is the wording in that extraction, not the slide. A founder who reads that
    # believes the figure was looked at twice on the page; it was looked at twice in one
    # transcription. This module is a scanned claim surface -- keep the overstated phrasing
    # out of the comments too, not merely out of the strings.
    bits = [f"I read {emphasis(str(total))} figures off your deck"]
    if verified < total:
        bits.append(
            f"{emphasis(str(verified))} of them had closely matching wording returned by a second pass over "
            f"the same extracted text, made without sight of the first — the other "
            f"{emphasis(str(total - verified))} I could not confirm, so nothing below rests on them"
        )
    else:
        bits.append(
            "all of them had closely matching wording returned by a second pass over the same "
            "extracted text, made without sight of the first"
        )

    # ATTEMPTED IS NOT EVALUATED. `relations_proposed` counts every comparison the model
    # PROPOSED, including ones the engine then refused outright -- a date relation is
    # refused before any arithmetic happens. Rendering that count as "I ran N comparisons"
    # and following it with "these particular comparisons held" describes refusals as
    # successful checks, which is the opposite of what happened.
    dropped = _as_dict(reconciliation.get("suppressed")).get("dropped")
    refused = dropped if isinstance(dropped, int) else 0
    evaluated = (computed - refused) if isinstance(computed, int) else 0
    if evaluated > 0:
        bits.append(f"and I ran {emphasis(str(evaluated))} comparisons across them")
    if refused > 0:
        plural = "s" if refused != 1 else ""
        bits.append(f"{emphasis(str(refused))} further comparison{plural} could not be made at all")
    # "The comparisons that DID run held" was UNCONDITIONAL, so a report could say it and
    # then list a contradiction in the same artifact. Whether they held is a fact about the
    # verdicts; read it rather than asserting it.
    # "HELD" NEEDS POSITIVE EVIDENCE, not merely the absence of a selected contradiction.
    # `select()` withholds most verdicts from `relations`, so a run whose comparisons came
    # back `incomparable`, `downgraded` or `convention_differs` -- visible only as
    # suppressed counts -- rendered "the comparisons that ran held". None of those
    # establishes that anything held; two of them mean the comparison could not be made.
    verdicts = [str(_as_dict(r).get("verdict")) for r in _as_list(reconciliation.get("relations"))]
    disagreements = sum(1 for v in verdicts if v == "contradiction")
    exceeded = sum(1 for v in verdicts if v == "exceeds_stated_limit")
    suppressed_counts = _as_dict(reconciliation.get("suppressed"))
    # `dropped` counts comparisons that were REFUSED before any arithmetic ran; it is
    # already subtracted from `evaluated` above and reported on its own line. Including it
    # here counted it twice and produced arithmetic a founder can see is impossible — "ran
    # 1", "1 could not be made", "of those, 2 could not be settled". Unsettled means
    # evaluated-but-inconclusive, so it must exclude what was never evaluated.
    # ALLOW-LIST, not a deny-list. These are the classes the sentence below is TRUE of:
    # two sides that could not be compared, or a comparison withdrawn on review. Written as
    # `key not in ("confirmation", "restatement", "dropped")`, every other suppression class
    # inherited their explanation -- measured on a live run, `suppressed: {"derived": 2}` told
    # a founder "the two sides were not comparable", when the sides were comparable and
    # nothing was withdrawn: `select()` had withheld two derived readings for low confidence.
    # A class this line has not heard of gets no sentence; its count stays in the artifact.
    inconclusive = sum(
        int(count)
        for key, count in suppressed_counts.items()
        if key in INCONCLUSIVE_SUPPRESSION_CLASSES and isinstance(count, int)
    )
    # Withheld derivations are a separate fact and get their own words. They are not failures
    # to compare -- the arithmetic ran and produced a figure the engine would not stand behind.
    withheld_derived = int(suppressed_counts.get("derived", 0) or 0)
    agreed = (
        sum(1 for v in verdicts if v in ("confirmation", "restatement"))
        + int(suppressed_counts.get("confirmation", 0) or 0)
        + int(suppressed_counts.get("restatement", 0) or 0)
    )
    if exceeded and not disagreements:
        # ITS OWN WORDS. A plan running past a stated ceiling is not the deck disagreeing
        # with itself; describing it as a disagreement names the wrong problem.
        settled = (
            f". {emphasis(str(exceeded))} of those comparisons show a plan running past a "
            "limit your deck itself states, and they are listed below"
        )
    elif disagreements:
        settled = (
            f". {emphasis(str(disagreements))} of those comparisons disagree with a figure your deck itself "
            "states, and they are listed below"
        )
    elif inconclusive:
        settled = (
            f". Of those, {emphasis(str(inconclusive))} could not be settled either way — the two sides were "
            "not comparable, or the comparison was withdrawn on review"
        )
    elif agreed and agreed == evaluated:
        # UNIVERSAL, so it needs universal evidence. `agreed > 0` licensed "the comparisons
        # that ran held" from a single confirmation sitting beside an unproven derived
        # reading — one agreement standing in for a claim about all of them.
        settled = ". That is what was checked, and the comparisons that ran held"
    else:
        settled = ". That is what was checked"
    # ADDITIVE, NOT ALTERNATIVE. Written as another `elif`, a single contradiction suppressed
    # the unsettled count entirely -- and a run carrying both is the normal case, not an edge
    # one. The two facts are independent: what disagreed, and what could not be adjudicated.
    # `dropped` is deliberately not in the inconclusive set: it counts comparisons refused
    # before any arithmetic ran, is already excluded from `evaluated`, and reported on its
    # own line above -- counting it here produced arithmetic a founder can see is impossible.
    if exceeded and disagreements:
        settled += f". A further {emphasis(str(exceeded))} show a plan running past a limit your deck itself states"
    # ADDITIVE for the same reason the unsettled clause is. A run with a contradiction and
    # thirty withheld derived readings mentioned neither the thirty nor why -- the `elif`
    # was fixed one line above and left in place here, in the same function.
    # UNCONDITIONAL, and out of the chain entirely. Copying the `disagreements or exceeded`
    # guard from the clause above reproduced the same defect one branch over: a run with
    # inconclusive comparisons and thirty withheld readings reported the two and never the
    # thirty. Every one of these counts is an independent fact about the run.
    if withheld_derived:
        lead = ". Of those," if settled.endswith("what was checked") else ". A further"
        settled += (
            f"{lead} {emphasis(str(withheld_derived))} produced figures worked out from your "
            "numbers that I am not confident enough to report"
        )
    if inconclusive and (disagreements or exceeded):
        settled += (
            f". Separately, {emphasis(str(inconclusive))} could not be settled either way — "
            "the two sides were not comparable, or the comparison was withdrawn on review"
        )
    # A SETTLED AGREEMENT, reported as one. `convention_differs` means the comparison ran and
    # the magnitudes agreed; only the convention each side stated them under differed. It sat
    # in the inconclusive set and so was described as a comparison that could not be made,
    # which understates the deck.
    convention = int(suppressed_counts.get("convention_differs", 0) or 0)
    if convention:
        settled += (
            f". A further {emphasis(str(convention))} agreed on the figures and differed only "
            "in the convention each side stated them under"
        )
    # A NEW SENTENCE, not an appositive. Written as "— not that every number ...", this
    # qualifier parsed only after ". That is what was checked"; after every other branch
    # ending the "not that" clause had no head, and a founder read "the comparison was
    # withdrawn on review — not that every number in the deck has been verified against every
    # other". Starting a sentence makes it grammatical after all five endings.
    tail = (
        # Not "None of that means ...": the fleet sentinel scan reads a bare `None` in
        # founder-facing prose as a leaked Python repr, and it cannot tell the English word
        # from the value. A correct sentence that trips a real guard is still the wrong
        # sentence to ship.
        settled + ". It does not follow that every number in the deck has been verified against "
        "every other, or that a careful reader would find nothing more. Treat this as a first "
        "pass over your arithmetic, not a clean bill of health.\n"
    )
    return ", ".join(bits) + tail


def untested_claims_line(
    reconciliation: dict[str, Any],
    emphasis: Callable[[str], str],
    escape: Callable[[str], str] = str,
) -> str:
    """Claims the deck makes that this run could not test.

    THE COMPANION TO THE COVERAGE LINE, and it exists for the same reason. A refused
    relation is suppressed -- correctly, it establishes nothing -- but suppression is
    invisible, so with no surviving contradictions the founder is told "Your figures line
    up" about the one claim an investor probes hardest.

    That is the N1 bug pointing the other way. Before, a founder was told their numbers
    disagreed when they did not; after, they are told everything checks out when the claim
    was never checked. Saying so is an ADDITION to the report's claim, not a retreat from
    it -- and it is directly actionable, because the fix is usually one figure the deck
    does not print.

    Deliberately says what is missing rather than guessing WHY, and that is permanent rather
    than provisional. Distinguishing "your deck does not state last year" from "we could not
    read the chart" would need chart-plotted values to be readable operands, and they are
    deliberately not: a value plotted without a printed label cannot be corroborated by a
    second reader against the text, so admitting it would put an unverifiable operand into
    the one place that must not have them. Both cases are therefore the same case -- the
    figures needed are not both on the deck in a usable form -- and a vaguer true sentence
    beats a precise invented one.
    """
    claims = [str(c) for c in _as_list(reconciliation.get("untested_claims")) if str(c).strip()]
    if not claims:
        return ""
    listed = "; ".join(claims)
    plural = "claims" if len(claims) > 1 else "claim"
    return (
        f"{emphasis('One thing this review could not check.')} Your deck states {escape(listed)}, and the figures "
        f"needed to test that {plural} are not both on the deck — a growth rate needs two points "
        f"in time, and the ones here sit inside a single year. So this {plural} is neither "
        f"confirmed nor disputed below. If an investor asks, that is the number they will ask "
        f"about; adding the earlier figure makes it checkable.\n"
    )
