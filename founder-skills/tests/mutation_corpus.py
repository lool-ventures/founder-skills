"""A curated mutant corpus for cap-table's math producers -- the registry and the harness.

The assertions over this live in `test_mutation_corpus.py`. THE SPLIT IS LOAD-BEARING, not tidiness:
`test_cap_table_guards.py`'s two ratchets ask "does any test name this diagnostic / rule_id" by bare
substring over `tests/test_*.py`, and this module's mutants have to quote the exact source text they
patch -- including error-code literals like the one the `safe_cap_missing_denominator_code_renamed`
entry renames. Inside a `test_*.py` file those payloads read to the ratchet as ASSERTIONS, so the
corpus would simultaneously record a code as an unguarded survivor and make the ratchet count it as
guarded. Two guards contradicting each other, with the corpus's own claim being the one silently
overruled. (Measured, not theorised: the first draft lived in the test file and dropped
`test_error_code_assertion_ratchet` below its baseline.) A non-`test_*` module is invisible to both
scanners, which is the correct reading -- a mutation payload is source text under test, never an
assertion about it.

WHY A CORPUS AND NOT A MUTATION SCORE.

Across the work that produced `test_cap_table_guards.py`, no new test found a bug. Every defect came
from reading output, reading code, or running mutants by hand -- mutation is the only technique here
with a demonstrated hit rate, and until now it was a hand-discipline with no record.

A full mutation run over cap-table's math producers -- `cap_state`, `safe_conversion`,
`note_conversion`, `option_pool`, `anti_dilution`, `priced_round`, `flip_scenario`, `warrant_exercise`
and `run_scenario` -- yields thousands of mutants, and each one costs a full selection run. That is
hours, which nobody will run, so it would gate nothing. And a score is the wrong number anyway, for the
same reason a coverage percentage was: it optimises an aggregate over a surface where most mutants are
equivalent or trivial.

NO CURRENT LINE COUNT APPEARS IN THAT SENTENCE, DELIBERATELY. It used to read "the nine math producers
(5,581 lines)". EVERY FIGURE IN THIS PARAGRAPH IS HISTORY, NOT A MEASUREMENT OF TODAY'S TREE -- they are
kept because they are the evidence for the rule, and a rule with its evidence deleted gets undone by the
next person who thinks it is fussy. That number was CORRECT when written and false about a day later:
measured across the 60 commits following it, the same nine files scored 5450 / 5565 / 5581 / 5672 /
5677 / 5703 / 5704 / 5707 / 5708. Worse,
two people independently tried to reconstruct it and each picked a different nine (one swapped
`rule_audit` in, one swapped `cap_state_after_round` in), so both concluded it was fabricated when it
was merely stale. Naming the files removes that ambiguity; quoting no total removes the rot. The two
numbers a reader actually wants -- how big the selection is and how long it takes -- are MEASURED AND
PRINTED by the harness on every verdict (see `_Verdict.tail`), so they cannot go stale in prose.

The eight mutants run by hand found six survivors -- a
25% kill rate that no aggregate would have communicated as sharply as the list did. (Two of those
hand-measured survivors were measured KILLED the first time this corpus ran; see the KNOWN_SURVIVORS
header. Hand-run mutation is exactly as perishable as any other undated measurement, which is the
argument for executing the list rather than writing it down.)

So this is a REGISTRY of named defects, in the pattern this repo already uses three times
(`_REJECTING_PAYLOADS`, `UNASSERTED_RULE_BASELINE`, `_NO_CASSETTE_ALLOWLIST`). Honest framing, since
the question is fair: this is defect-injection regression testing. It does not search for new mutants;
it pins the ones already found so a guard cannot silently stop being guarded -- which, given that this
work began by finding a guard added one day and unprotected the next, is the failure mode with the
best track record here.

TWO LISTS, NOT ONE. `MUST_KILL` (asserted) and `KNOWN_SURVIVORS` (recorded). A survivor list that is
silently empty is indistinguishable from one nobody wrote, and folding survivors into a count would
lose exactly the reviewability that made the hand-run list useful. Both are SHRINK-ONLY: a survivor
that starts being killed must be promoted, and the suite fails until it is.

THE NO-OP CONTROL. A mutant corpus can pass because the harness is broken -- a copy that fails to
build, a bad path, a pytest invocation that errors for an unrelated reason. Every entry would then
"fail" and every assertion would green. So the harness first applies a comment-only mutant and
requires the selection to PASS. If that control fails, every verdict is void and the module-scoped
fixture fails rather than letting the corpus report a green built on a broken instrument.

NEVER MUTATES THE WORKING TREE. Everything happens in a copy under pytest's tmp dir. This tree is
permanently dirty by design and an agent has already destroyed uncommitted work in it.

RUN IT: `uv run pytest founder-skills/tests/test_mutation_corpus.py -m mutation`. It is deselected
from the default suite by `addopts` (~3 min) and runs in its own CI job.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# Copied into the sandbox. `evals/` is here because `test_cap_table_canonicals.py` reads
# `evals/cap-table`; `pyproject.toml` because it carries pytest's rootdir, `pythonpath` and
# `addopts` -- without it the child run resolves imports differently from CI and a green means
# nothing.
#
# ENUMERATED, NOT A WHOLE-ROOT COPY WITH AN IGNORE LIST. The wider copy was considered and refused for
# one reason that outranks its convenience: `docs/internal/` is gitignored and holds private working
# notes, and a whole-root copy would replicate them into a temp dir on every run. An explicit list
# cannot pick up a directory nobody named. The cost of the choice is that a new `_SELECTION` file
# needing an uncopied root fails as the no-op control -- which is why the control message names that
# case explicitly rather than leaving it to read as a broken harness.
#
# THE LIST IS DELIBERATELY WIDER THAN `_SELECTION` NEEDS. It used to be exactly what the selection
# needed, which made the sandbox a trap for whoever widens the selection later: measured, the
# narrow list ABORTS COLLECTION on the full suite in ~4 s (`24 deselected, 2 errors`), and the
# symptom surfaces as the no-op control failing -- i.e. pointing at the harness rather than at the
# copy list. With these roots the sandbox runs the whole free suite to exactly the same result as
# the real tree, so `_SELECTION` can be widened to anything without touching this. The cost that
# buys it is 0.13 s of copying (`cowork-tests/` is 9.9 MB and 0.04 s of that), against a ~3 min run.
_COPY_DIRS = ("founder-skills", "evals", "scripts", ".github", "cowork-tests")
_COPY_FILES = ("pyproject.toml", "CLAUDE.md", "CHANGELOG.md", "CONTRIBUTING.md", "README.md")
_IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache", "artifacts", ".git", ".venv")

_SCRIPTS = "founder-skills/skills/cap-table/scripts"

# THE SELECTION IS UNIFORM ACROSS EVERY ENTRY, deliberately. A per-mutant selection would be faster,
# but a mutant is only honestly a SURVIVOR against the tests that could plausibly catch it -- narrow
# the selection and survival becomes a property of the selection rather than of the suite. Uniformity
# costs seconds and buys a claim that means something.
_SELECTION = tuple(
    f"founder-skills/tests/{name}"
    for name in (
        "test_cap_table.py",
        "test_cap_table_guards.py",
        "test_cap_table_canonicals.py",
        "test_cap_table_extraction_only.py",
        "test_cap_table_freeform.py",
        "test_cap_table_properties.py",
        "test_cap_state_after_round.py",
        "test_chain_integration_v050.py",
        "test_concise_report.py",
        "test_coupled_solver_goldens.py",
        "test_quick_check_lane.py",
        "test_solver_convergence_guards.py",
        "test_solver_warning_surfaces.py",
        "test_founder_text_keep_parity.py",
        "test_v48_hotfix_regressions.py",
        "test_verify_one.py",
        "test_visualize_cap_table.py",
    )
)


# DESELECTED FROM THE SELECTION, and both for the same reason: a COUNT RATCHET is not a defect
# detector, so letting one fail would report a mutant as killed for the wrong reason.
#
# `test_error_code_assertion_ratchet` counts how many `E_*`/`W_*` constants the producers can emit
# that no test names. A mutant that RENAMES a code changes the membership of that set -- so the
# ratchet could red on a mutant while noticing nothing about the defect, and could equally stay
# green while the defect ships. `test_rule_assertion_ratchet` has the identical shape over rule_ids.
# Neither is weakened by this: they run in the ordinary suite, where they belong.
#
# BE PRECISE ABOUT WHICH HALF OF THIS IS MEASURED, because an earlier version of this comment was
# not. The false-KILL hazard above is PROPHYLAXIS: recomputing both ratchets' quantities under all
# every entry gave the then-current baseline for all three counts, so nothing in the corpus moved
# either ratchet -- the one rename entry swaps an unasserted code for another
# unasserted code. It is a hazard the next entry can trip, not one this one did.
#
# The false-ALARM half WAS observed, twice. Both ratchets red the moment their count drifts by one
# -- an ordinary state for a working tree mid-edit -- and a red anywhere in the selection trips the
# no-op control, which then reports "the harness is broken" about a harness that is fine.
_DESELECT = (
    "founder-skills/tests/test_cap_table_guards.py::test_error_code_assertion_ratchet",
    "founder-skills/tests/test_cap_table_guards.py::test_rule_assertion_ratchet",
)


@dataclass(frozen=True)
class Mutant:
    """A named defect injected into one file by exact-text substitution.

    `find` must occur EXACTLY ONCE in `file`. Anchoring on text rather than a line number is not a
    style choice: this plan's own source cited `priced_round.py:267-269`, and by the time it was
    implemented the lines had moved. A line-anchored corpus silently mutates the wrong code and
    reports whatever that happens to do.
    """

    id: str
    file: str
    find: str
    replace: str
    rationale: str
    # The test that must be the one to notice. REQUIRED on every MUST_KILL entry (empty only for the
    # no-op control and for survivors, which by definition nothing catches): a kill from anywhere else
    # is not accepted. Without it the corpus records only THAT the selection failed, and its kill
    # detection has already been caught twice accepting the wrong reason -- a count ratchet, then a
    # collection error. "Something went red" is not the same claim as "the guard noticed", and the
    # gap between them is the whole reason this corpus exists rather than a coverage number.
    #
    # ALWAYS `Class::method`, never a bare class. A bare class name is satisfied by ANY test in it --
    # measured, `TestCapImpliedRefusesUnusableInstrumentSets` holds four tests of which only two can
    # notice their entry's mutant -- so it asserts a weaker thing than the field's name promises.
    #
    # Every value here was MEASURED by running the mutant and reading the FAILED line, never guessed
    # from the rationale. Note the harness runs with `-x`, so this records the FIRST test to notice;
    # if a new file earlier in `_SELECTION` also catches a mutant, the recorded value needs
    # re-measuring rather than the guard needing loosening.
    killed_by: str = ""


# ---------------------------------------------------------------------------------------------
# The no-op control. Comment-only, so the selection MUST still pass. See the module docstring.
# ---------------------------------------------------------------------------------------------

NO_OP = Mutant(
    id="noop_control",
    file=f"{_SCRIPTS}/safe_conversion.py",
    find="def convert_safes_cap_implied(",
    replace="# mutation-corpus no-op control\ndef convert_safes_cap_implied(",
    rationale=(
        "A comment-only edit at a real mutation site. It proves the sandbox builds, the paths "
        "resolve and the selection runs -- without it, a harness that fails for any unrelated "
        "reason makes every MUST_KILL entry pass and every survivor look guarded."
    ),
)


# ---------------------------------------------------------------------------------------------
# MUST_KILL -- the suite currently catches these and must keep catching them.
# ---------------------------------------------------------------------------------------------

MUST_KILL: tuple[Mutant, ...] = (
    Mutant(
        id="cap_implied_denominator_is_pre_financing_base",
        killed_by="TestSafeConversion::test_cap_implied_basic",
        file=f"{_SCRIPTS}/safe_conversion.py",
        find="    total = pre_financing_fd / residual",
        replace="    total = pre_financing_fd",
        rationale=(
            "Reverts the post-money SAFE's Company Capitalization to the PRE-financing share count, "
            "which omits the converting SAFEs themselves. That is the defect that shipped: one report "
            "converting one SAFE two different ways, and every cap-implied ownership overstated."
        ),
    ),
    Mutant(
        id="cap_implied_notes_guard_disabled",
        # MEASURED. The guard now sits above the arm split, so disabling it strands the priced arm
        # too -- and that test collects first. Recorded as measured rather than left at the older,
        # semantically neater attribution, which no longer describes what notices.
        killed_by="TestCapImpliedNotesGuard::test_priced_params_do_not_route_around_the_guard",
        file=f"{_SCRIPTS}/run_scenario.py",
        find='    notes = instruments.get("convertible_notes") or []\n    if notes:',
        replace='    notes = instruments.get("convertible_notes") or []\n    if False:',
        rationale=(
            "Deletes the guard that blocks a cap-implied snapshot while a convertible note is "
            "outstanding. THE ORIGINAL FINDING: this guard was added one day in response to a "
            "founder-facing defect and, the next day, deleting it left 594 tests green."
        ),
    ),
    Mutant(
        id="no_conversion_path_typo_at_the_covered_site",
        # RE-MEASURED. It was TestNoConversionPathBranch, which still notices but is no longer FIRST.
        # `note_conversion` now treats an explicit `maturity_default_treatment: null` the same as an
        # absent key (the schema permits the null and three surfaces write it), so this fixture --
        # which carries exactly that null -- moved off the fallthrough return and onto the one this
        # mutant typos. That the move happened is itself evidence the null fix was needed: a realistic
        # note fixture already in the suite was taking the wrong branch.
        killed_by="TestNoteNoConversionPathReason::test_reason_names_capitalization_denominator",
        file=f"{_SCRIPTS}/note_conversion.py",
        find=(
            "        if priced_context and cap is None and discount is None:\n"
            '            return "priced_round_no_cap_or_discount", False\n'
            '        return "no_conversion_path", mdt_absent\n'
            '    if mdt == "repay":'
        ),
        replace=(
            "        if priced_context and cap is None and discount is None:\n"
            '            return "priced_round_no_cap_or_discount", False\n'
            '        return "no_converson_path", mdt_absent\n'
            '    if mdt == "repay":'
        ),
        rationale=(
            "Typos the branch name a note with no cap, no discount and no maturity disposition falls "
            "to. The line EXECUTES on every run, so coverage saw nothing: it was covered and "
            "unasserted, the same shape as the defect that started this work."
        ),
    ),
    Mutant(
        id="benchmark_freshness_always_fresh",
        killed_by="TestRuleApplicabilityPredicates::test_stale_and_fresh_benchmarks_are_distinguished",
        file=f"{_SCRIPTS}/rule_audit.py",
        find=(
            "    if benchmark_reference is None:\n"
            '        return "unknown"\n'
            "    if start is not None and benchmark_reference < start:\n"
            '        return "stale"\n'
            "    if end is not None and benchmark_reference > end:\n"
            '        return "stale"\n'
            '    return "fresh"'
        ),
        replace='    return "fresh"',
        rationale=(
            "Collapses every benchmark -- stale, unknown, current -- into 'fresh'. A seven-year-old "
            "benchmark is then presented to a founder as current, and 'no reference date' becomes "
            "indistinguishable from 'checked and current'."
        ),
    ),
    Mutant(
        id="concise_report_writes_before_deciding",
        killed_by="TestConciseReportDoesNotClobberOnReject::test_rejected_render_leaves_the_prior_markdown_intact",
        file=f"{_SCRIPTS}/concise_report.py",
        find="    rejected = not md.strip() or not has_content",
        replace=(
            '    with open(args.output_md, "w", encoding="utf-8") as fh:\n'
            "        fh.write(md)\n"
            "    rejected = not md.strip() or not has_content"
        ),
        rationale=(
            "Restores write-then-evaluate. The exit code stays honest and the artifact does not: the "
            "founder is pointed at a file the producer itself just called empty, and the prior good "
            "answer is gone."
        ),
    ),
    Mutant(
        id="terms_only_note_blames_the_wrong_missing_field",
        killed_by="TestTermsOnlyNoteDisclosure::test_missing_date_is_not_reported_as_a_missing_principal",
        file=f"{_SCRIPTS}/cap_state.py",
        find='    if any(not (n.get("issuance_date") or "").strip() for n in _nonconvertible):\n'
        '        warnings_list.append("W_NOTE_ISSUANCE_DATE_MISSING")',
        replace='    if False:\n        warnings_list.append("W_NOTE_ISSUANCE_DATE_MISSING")',
        rationale=(
            "Collapses two causes back into one code. A note carrying a real $1M principal but no "
            "issuance date is then reported as having NO PRINCIPAL, and the founder is told to "
            "provide a figure they already provided -- a factually false statement about their own "
            "instrument, with no field named that would let them act. The note is dropped either "
            "way, so nothing in the numbers reveals it; only the words are wrong."
        ),
    ),
    Mutant(
        id="rules_boundary_drops_the_shared_keep_set",
        killed_by="test_founder_text_keep_parity.py::test_rules_boundary_keeps_the_glossary",
        file=f"{_SCRIPTS}/_rules.py",
        find="    return str(pol.substitute(s, extra_keep=cap_table_keep()))",
        replace="    return str(pol.substitute(s))",
        rationale=(
            "Restores the state three of four cap-table call sites shipped in: substitute with no "
            "keep set, so the skill's OWN glossed vocabulary is destroyed on the route that feeds "
            "HTML text nodes. `report.md` kept `structural_only`; the explorer and report.html "
            "showed `structural only`, a term matching no field and nothing a founder can look up. "
            "The asymmetry is invisible by inspection -- every call site reads as 'we apply the "
            "founder-text policy here'."
        ),
    ),
    Mutant(
        id="solver_warnings_collected_but_never_rendered",
        # MEASURED. Caught by the pre-existing report.md guard, not by the new per-surface suite --
        # the shared collector is upstream of both, so the oldest assertion reaches it first.
        killed_by="TestSolverWarningsReachTheFounder::test_mfn_counterfactual_is_labelled_as_the_agent_contract_requires",
        file=f"{_SCRIPTS}/_warning_callouts.py",
        find="    collected: list[dict] = []\n    for s in scenarios or []:",
        replace="    collected: list[dict] = []\n    for s in []:",
        rationale=(
            "Restores 'computed, then dropped' at the new chokepoint. Every founder-facing surface "
            "now reads its solver warnings through this one walk, which is the point of sharing it -- "
            "and also means one edit here silently empties all six at once. The class already has "
            "form in this skill: W_MFN_NOT_MOST_FAVORABLE was computed, written to scenarios.json "
            "and dropped before the founder for a full release, and the report is REQUIRED to label "
            "that election as a counterfactual rather than as the holder's entitlement."
        ),
    ),
    Mutant(
        id="cap_implied_notes_guard_returns_to_the_dropping_path",
        killed_by="TestCapImpliedNotesGuard::test_priced_params_do_not_route_around_the_guard",
        file=f"{_SCRIPTS}/run_scenario.py",
        find=('    notes = instruments.get("convertible_notes") or []\n    if notes:\n        return {'),
        replace=(
            '    notes = instruments.get("convertible_notes") or []\n'
            "    if notes and (priced_pre is None or priced_new is None):\n"
            "        return {"
        ),
        rationale=(
            "Restores the guard to the cap-implied arm only -- the state this blocker shipped in for "
            "a full release. With priced params supplied the function delegates with a hardcoded "
            "`notes=[]`, so the note leaves the post-money denominator and every SAFE percentage is "
            "overstated with nothing said. The blocker's own remedy used to name the params that "
            "reach that arm, so the documented fix WAS the defect. Appending to `blockers` instead "
            "of returning reproduces it just as well: the priced arm returns the solver's output and "
            "never reads that list."
        ),
    ),
    Mutant(
        id="concise_gate_ignores_whether_anything_rendered",
        killed_by="TestConciseReportDoesNotClobberOnReject::test_rejected_render_leaves_the_prior_markdown_intact",
        file=f"{_SCRIPTS}/concise_report.py",
        find="    rejected = not md.strip() or not has_content",
        replace="    rejected = not md.strip()",
        rationale=(
            "Restores the property the old predicate lost: a render that produced no fact, no warning "
            "callout and no flag is still non-empty as a STRING -- it carries a title and a footer -- so "
            "a strip()-only gate writes it and the founder is handed a heading with nothing under it. "
            "This is the half of the gate that has to survive; the half that was broken refused real "
            "answers, and a fix that only loosens would trade one silent defect for the other."
        ),
    ),
    Mutant(
        id="warrant_holder_election_defaults_to_cash",
        killed_by="TestWarrantHolderElection::test_unspecified_election_is_refused_not_guessed",
        file=f"{_SCRIPTS}/warrant_exercise.py",
        find=(
            '        if choice not in ("cash", "net_share"):\n'
            "            raise WarrantPumpError(\n"
            "                f\"E_WARRANT_HOLDER_ELECTION_UNSPECIFIED: warrants[{warrant.get('warrant_id', '?')}] \"\n"
            "                f\"holder_election_choice={choice!r}; expected 'cash' or 'net_share'.\"\n"
            "            )\n"
            '        effective = "cash_exercise" if choice == "cash" else "net_share_settlement"'
        ),
        replace='        effective = "net_share_settlement" if choice == "net_share" else "cash_exercise"',
        rationale=(
            "An unstated holder election silently settles as cash instead of being refused. Cash and "
            "net-share add different share counts, so the guess changes every founder percentage "
            "downstream and nothing says a choice was invented."
        ),
    ),
    Mutant(
        id="mfn_audit_fields_corrupted",
        killed_by="TestMfnElectionOverride::test_scenario_route_forwards_mfn_elections",
        file=f"{_SCRIPTS}/priced_round.py",
        find=(
            '            if anchor.get("post_money_valuation_cap") is not None:\n'
            '                shadow["_mfn_inherited_cap"] = anchor.get("post_money_valuation_cap")\n'
            '                shadow["_mfn_inherited_cap_type"] = "post_money"\n'
            '            elif anchor.get("pre_money_valuation_cap") is not None:\n'
            '                shadow["_mfn_inherited_cap"] = anchor.get("pre_money_valuation_cap")\n'
            '                shadow["_mfn_inherited_cap_type"] = "pre_money"\n'
            '            shadow["_mfn_inherited_discount"] = anchor.get("discount_multiplier")'
        ),
        replace=(
            '            shadow["_mfn_inherited_cap"] = None\n'
            '            shadow["_mfn_inherited_cap_type"] = None\n'
            '            shadow["_mfn_inherited_discount"] = None'
        ),
        rationale=(
            "Blanks the audit trail recording WHICH sibling's terms an MFN election inherited -- the "
            "fields that let `per_safe` distinguish two scenarios electing different siblings, which "
            "`cap_state` cannot. MEASURED CORRECTION: the plan that seeded this corpus listed this as "
            "a survivor and as non-load-bearing. It is neither -- "
            "`TestMfnElectionOverride::test_scenario_route_forwards_mfn_elections` catches it. Kept "
            "because a claim of non-load-bearing-ness that turned out false is exactly what a corpus "
            "entry should hold in place."
        ),
    ),
    Mutant(
        id="mfn_anchor_terms_not_inherited",
        killed_by="TestStackedPostMoneySAFEsGolden::test_uncapped_mfn_auto_binds_to_elected_safes_terms",
        file=f"{_SCRIPTS}/priced_round.py",
        find=(
            '            shadow["form"] = anchor["form"]\n'
            '            shadow["post_money_valuation_cap"] = anchor.get("post_money_valuation_cap")\n'
            '            shadow["pre_money_valuation_cap"] = anchor.get("pre_money_valuation_cap")\n'
            '            shadow["discount_multiplier"] = anchor.get("discount_multiplier")'
        ),
        replace='            shadow["form"] = anchor["form"]',
        rationale=(
            "An MFN-electing SAFE takes the elected sibling's FORM but none of its terms, so an "
            "instrument that was supposed to inherit a cap converts without one. Also listed as a "
            "survivor by the seeding plan and also wrong: "
            "`TestStackedPostMoneySAFEsGolden::test_uncapped_mfn_auto_binds_to_elected_safes_terms` "
            "catches it."
        ),
    ),
    Mutant(
        id="safe_cap_missing_denominator_code_renamed",
        killed_by="TestCapImpliedDenominatorRejections::test_cap_implied_rejects_a_non_positive_pre_financing_base",
        file=f"{_SCRIPTS}/safe_conversion.py",
        find='E_SAFE_CAP_MISSING_DENOMINATOR = "E_SAFE_CAP_MISSING_DENOMINATOR"',
        replace='E_SAFE_CAP_MISSING_DENOMINATOR = "E_SAFE_CAP_MISSING_DENOMINATOR_RENAMED"',
        rationale=(
            "Renames a founder-visible diagnostic emitted at four sites. It was a recorded survivor, "
            "and the reason was worse than 'nothing asserts the string': coverage over the full free "
            "suite showed only the constant DEFINITION executing -- every emit site was dead, so it "
            "survived because the code never ran. `TestCapImpliedDenominatorRejections` now reaches "
            "three of the four (the fourth is a closed-fixed-point post-condition, an algebraic "
            "identity, deliberately untested and documented as such)."
        ),
    ),
    Mutant(
        id="note_discount_non_positive_guard_removed",
        killed_by="TestNoteRejectsANonPositiveDiscount::test_zero_discount_is_rejected",
        file=f"{_SCRIPTS}/note_conversion.py",
        find=(
            "        if discount <= 0:\n"
            '            base["branch"] = "rejected"\n'
            '            base["error"] = E_NOTE_INVALID_PRICE_INPUT\n'
            '            base["reason"] = f"discount_multiplier must be > 0; got {discount!r}"\n'
            "            return base\n"
        ),
        replace="",
        rationale=(
            "Removes the reject for a non-positive discount multiplier. A zero multiplier produces a "
            "conversion price of 0 and an unbounded share count; a negative one produces a negative "
            "price. The guard existed all along -- nothing reached it through the public entry point, "
            "which is why this survived. `TestNoteRejectsANonPositiveDiscount` drives `convert_note`."
        ),
    ),
    Mutant(
        id="duplicate_safe_ids_collapse_silently",
        killed_by="TestCapImpliedRefusesUnusableInstrumentSets::test_duplicate_ids_are_refused_rather_than_collapsed",
        file=f"{_SCRIPTS}/safe_conversion.py",
        find='    ids = [s.get("id") for s in safes]',
        replace="    ids = []",
        rationale=(
            "Disables the duplicate-id refusal, restoring a measured defect: `priced` and `per_safe` "
            "are id-keyed, so two SAFEs sharing an id returned a clean `cap_implied_set` computed from "
            "one of them -- a $500k instrument absent from BOTH the denominator and the output, with "
            "no diagnostic. Found by adversarial review of this corpus, not by the corpus itself."
        ),
    ),
    Mutant(
        id="degenerate_cap_implied_denominator_not_refused",
        killed_by="TestCapImpliedRefusesUnusableInstrumentSets::test_a_numerically_degenerate_aggregate_is_refused",
        file=f"{_SCRIPTS}/safe_conversion.py",
        find="    if residual <= 1e-9:",
        replace="    if False:",
        rationale=(
            "Removes the near-degenerate-aggregate guard. `aggregate >= 1.0` is blocked; one ulp below "
            "it was not, and returned company_capitalization 7.2e22 with 3.6e22 shares per SAFE as a "
            "clean result. With a large pre-financing base the same path overflowed and raised "
            "ZeroDivisionError out of a producer whose contract is typed rejections."
        ),
    ),
    Mutant(
        id="cap_state_duplicate_ids_not_refused",
        killed_by="TestCapStateRejectsDuplicateIds::test_duplicate_founder_ids_are_refused",
        file=f"{_SCRIPTS}/cap_state.py",
        find="    for array_name, id_field, rows in arrays:",
        replace="    for array_name, id_field, rows in []:",
        rationale=(
            "Disables the artifact-level uniqueness check, restoring an entire CLASS rather than one "
            "defect: ids key every per-item output in this skill, and six consumers were measured "
            "collapsing on a repeat -- the AD CP1 snapshot (~5 percentage points of founder "
            "ownership), the note route (720,000 shares reported against a true 1,120,000), the "
            "founder breakdown, the warrant pump, rule_audit's gating map and the option-grant "
            "subscript. Two earlier commits guarded two consumers each and left the rest; this is "
            "the check that made the invariant hold for consumers nobody has written yet."
        ),
    ),
    Mutant(
        id="priced_round_duplicate_ids_collapse_silently",
        killed_by="TestPricedRoundRefusesCollapsingInstrumentIds::test_duplicate_safe_ids_block_the_round",
        file=f"{_SCRIPTS}/priced_round.py",
        find="    _dupe_blockers = _duplicate_id_blockers(safes, notes)",
        replace="    _dupe_blockers = []",
        rationale=(
            "Restores the collapse on the PRICED path, which is worse than the cap-implied one the "
            "corpus already covers: the denominator counts both instruments while `per_safe` keeps "
            "one, so a founder reads `safe_pct` 16% in the aggregate beside a single row carrying "
            "half of it -- `completeness: full`, zero blockers. Found by adversarial review after the "
            "cap-implied half shipped fixed; fixing one path had left the more confident of the two "
            "lying."
        ),
    ),
    Mutant(
        id="anti_dilution_renderer_prints_constant_prices",
        killed_by="TestComputedReachesTheRenderedReport::test_rendered_conversion_prices_are_the_computed_ones",
        file=f"{_SCRIPTS}/compose_report.py",
        find=(
            '                    ccp_before = bd.get("ccp_before", 0)\n'
            '                    ccp_after = bd.get("ccp_after", 0)'
        ),
        replace="                    ccp_before = 1.0\n                    ccp_after = 0.82",
        rationale=(
            "The per-series anti-dilution block renders constants instead of the computed conversion "
            "prices. This is the 'computed, not rendered' class the delivery-coverage map records as "
            "ungated for cap-table: a test asserting the section merely EXISTS passes against it."
        ),
    ),
)


# ---------------------------------------------------------------------------------------------
# KNOWN_SURVIVORS -- measured, unguarded, and named so each is reviewable on its own terms.
#
# SHRINK-ONLY. An entry here is a claim that the suite does not notice this defect; if one starts
# failing the selection, the claim is stale and the entry must move to MUST_KILL.
#
# THE LIST IS DOWN TO TWO, AND BOTH ARE IN THE SAME UNIMPORTED MODULE. Read that as "this corpus
# currently records no gap anyone should act on", NOT as "the fleet has no gaps" -- a near-empty
# survivor list is exactly as easy to misread as a silently empty one, which is why both halves are
# spelled out. Everything that was here and mattered has been fixed and promoted: the four kept
# entries in MUST_KILL above were survivors when the corpus was written.
#
# WHAT SEEDING AND REVIEW MEASURED. Six entries were proposed as survivors from a hand-run pass. Two
# were measured KILLED on the corpus's first execution. Two more were real gaps that adversarial
# review turned into fixes. And the flagship survivor's own rationale claimed its emit sites were
# "all executed by the suite" when coverage showed every one of them dead -- a hand-maintained list
# of "what the suite misses" drifting in the direction that shows least, since a stale survivor entry
# reads as ordinary debt and fails nothing.
KNOWN_SURVIVORS: tuple[Mutant, ...] = (
    Mutant(
        id="artifact_io_fd_sum_invariant_disabled",
        file=f"{_SCRIPTS}/_artifact_io.py",
        find='        actual_fd = int(totals.get("fully_diluted_shares", 0))\n        if expected_fd != actual_fd:',
        replace='        actual_fd = int(totals.get("fully_diluted_shares", 0))\n        if False:',
        rationale=(
            "Disables `E_FD_SUM_MISMATCH` on load: a hand-edited cap_state.json whose fully-diluted "
            "total disagrees with its own components loads clean. NOT worth a test on today's "
            "evidence -- no producer imports `_artifact_io` (only `test_chain_integration_v050.py` "
            "does), so the guard protects a path nothing takes. Recorded so that stops being true "
            "silently."
        ),
    ),
    Mutant(
        id="artifact_io_founder_shares_invariant_disabled",
        file=f"{_SCRIPTS}/_artifact_io.py",
        find='    if founders and sum(int(f.get("common_shares", 0)) for f in founders) <= 0:',
        replace="    if False:",
        rationale=(
            "Disables `E_FOUNDER_SHARES_REQUIRED` on load. Same standing as the FD-sum invariant "
            "above and for the same reason -- an unimported module -- so the two rise and fall "
            "together."
        ),
    ),
)


_ALL: tuple[Mutant, ...] = MUST_KILL + KNOWN_SURVIVORS


# ---------------------------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------------------------


@dataclass
class _Verdict:
    killed: bool
    first_failure: str
    tail: str


class _Harness:
    """A repo copy in a temp dir, plus apply/run/revert for one mutant at a time.

    Copies ONCE and reverts after each mutant rather than copying per entry: the copy is the
    expensive part, and a revert verified against the pristine source text is exact.
    """

    def __init__(self, tree: Path) -> None:
        self.tree = tree

    def _pytest(self) -> subprocess.CompletedProcess[str]:
        env = dict(os.environ)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        # A `-m` or `-p` inherited from the parent invocation would silently change what the child
        # selects, which is the difference between a verdict and a guess.
        env.pop("PYTEST_ADDOPTS", None)
        return subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                *_SELECTION,
                "-x",
                "-q",
                "--tb=no",
                # BOTH f and E: `-rf` alone omits the ERROR summary lines entirely, so the
                # collection-error check below would parse an empty list and never fire. Measured.
                "-rfE",
                "-p",
                "no:cacheprovider",
                *[arg for nodeid in _DESELECT for arg in ("--deselect", nodeid)],
            ],
            cwd=self.tree,
            capture_output=True,
            text=True,
            env=env,
        )

    def verdict(self, mutant: Mutant) -> _Verdict:
        path = self.tree / mutant.file
        assert path.exists(), f"{mutant.id}: {mutant.file} is not in the sandbox copy"
        original = path.read_text(encoding="utf-8")
        occurrences = original.count(mutant.find)
        assert occurrences == 1, (
            f"{mutant.id}: its `find` text occurs {occurrences} times in {mutant.file}, not once. "
            "The code moved under the corpus; re-anchor the entry on the current source rather than "
            "letting it mutate an unintended site (or nothing at all)."
        )
        path.write_text(original.replace(mutant.find, mutant.replace), encoding="utf-8")
        try:
            started = time.monotonic()
            proc = self._pytest()
            elapsed = time.monotonic() - started
        finally:
            path.write_text(original, encoding="utf-8")
            assert path.read_text(encoding="utf-8") == original, (
                f"{mutant.id}: the sandbox file did not revert; every later verdict is unreliable"
            )
        # ONLY 0 AND 1 ARE VERDICTS. pytest also exits 5 (nothing collected), 4 (usage error),
        # 3 (internal error) and 2 (interrupted) -- and `returncode != 0` would read every one of
        # them as "the suite noticed the defect". A mutant that breaks COLLECTION rather than a test
        # would then be recorded as killed, which is the same false-kill class the ratchet
        # deselection above guards against, arriving through the exit code instead.
        if proc.returncode not in (0, 1):
            raise AssertionError(
                f"{mutant.id}: the child pytest exited {proc.returncode}, which is not a verdict "
                "(1 = tests failed, 0 = tests passed; anything else is a collection, usage or "
                f"internal error). This mutant's result is unknowable, not a kill.\n{proc.stdout[-2000:]}"
            )
        failed = [ln for ln in proc.stdout.splitlines() if ln.startswith("FAILED ")]
        errored = [ln for ln in proc.stdout.splitlines() if ln.startswith("ERROR ")]

        # A COLLECTION ERROR IS NOT A KILL, and the exit code cannot tell you so: pytest returns 1
        # for "a module failed to import" exactly as it does for "a test failed", so a mutant that
        # produced a syntax error would be recorded as caught by a suite that never ran. Measured --
        # this is not the exit-code case above, which is why both checks exist.
        #
        # The discriminator is the `::`. A collection error names a FILE (`ERROR tests/test_x.py`);
        # a fixture blowing up inside a test names a NODE (`ERROR tests/test_x.py::TestC::test_m`),
        # and that one IS the suite noticing something. So only a run whose errors are all
        # file-level, with no `FAILED` at all, is refused.
        if not failed and errored and all("::" not in ln for ln in errored):
            raise AssertionError(
                f"{mutant.id}: the child run collected nothing to judge -- every diagnostic is a "
                "file-level collection error and no test FAILED. The mutant broke the suite's "
                "ability to run rather than being caught by it, so this is not a kill.\n" + "\n".join(errored[:5])
            )

        # MEASURED, NOT ASSERTED IN PROSE. The selection's size and cost are the two numbers a
        # reader wants when judging "is a full mutation run affordable?", and both used to live in a
        # comment, where one of them went stale within a day. Emitting them from the run that just
        # happened makes them true by construction.
        sized = next((ln for ln in reversed(proc.stdout.splitlines()) if " passed" in ln or " failed" in ln), "")
        measured = f"[selection: {sized.strip()} | {elapsed:.1f}s]"

        failures = failed + errored
        return _Verdict(
            killed=proc.returncode != 0,
            first_failure=failures[0] if failures else "",
            tail=measured + "\n" + "\n".join((proc.stdout + proc.stderr).splitlines()[-12:]),
        )
