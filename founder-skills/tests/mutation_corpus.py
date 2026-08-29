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

A full mutation run over the nine math producers (5,581 lines) yields thousands of mutants at ~7 s
each: four to eight hours, which nobody will run, so it would gate nothing. And a score is the wrong
number anyway, for the same reason a coverage percentage was: it optimises an aggregate over a surface
where most mutants are equivalent or trivial. The eight mutants run by hand found six survivors -- a
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
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# Copied into the sandbox. `evals/` is here because `test_cap_table_canonicals.py` reads
# `evals/cap-table`; `pyproject.toml` because it carries pytest's rootdir, `pythonpath` and
# `addopts` -- without it the child run resolves imports differently from CI and a green means
# nothing.
_COPY_DIRS = ("founder-skills", "evals")
_COPY_FILES = ("pyproject.toml",)
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
# ratchet can red on a mutant while noticing nothing about the defect, and can equally stay green
# while the defect ships. `test_rule_assertion_ratchet` has the identical shape over rule_ids.
# Neither is weakened by this: they run in the ordinary suite, where they belong.
#
# It also removes a false alarm the corpus would otherwise raise constantly. Both ratchets red the
# moment their count drifts by one -- an ordinary state for a dirty working tree mid-edit -- and a
# red anywhere in the selection trips the no-op control, which then reports "the harness is broken"
# about a harness that is fine.
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
        file=f"{_SCRIPTS}/safe_conversion.py",
        find="    total = pre_financing_fd / (1.0 - aggregate)",
        replace="    total = pre_financing_fd",
        rationale=(
            "Reverts the post-money SAFE's Company Capitalization to the PRE-financing share count, "
            "which omits the converting SAFEs themselves. That is the defect that shipped: one report "
            "converting one SAFE two different ways, and every cap-implied ownership overstated."
        ),
    ),
    Mutant(
        id="cap_implied_notes_guard_disabled",
        file=f"{_SCRIPTS}/run_scenario.py",
        find='        notes = instruments.get("convertible_notes") or []\n        if notes:',
        replace='        notes = instruments.get("convertible_notes") or []\n        if False:',
        rationale=(
            "Deletes the guard that blocks a cap-implied snapshot while a convertible note is "
            "outstanding. THE ORIGINAL FINDING: this guard was added one day in response to a "
            "founder-facing defect and, the next day, deleting it left 594 tests green."
        ),
    ),
    Mutant(
        id="no_conversion_path_typo_at_the_covered_site",
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
        file=f"{_SCRIPTS}/concise_report.py",
        find='    rejected = not md.strip() or ("—" in md and "Founders" not in md)',
        replace=(
            '    with open(args.output_md, "w", encoding="utf-8") as fh:\n'
            "        fh.write(md)\n"
            '    rejected = not md.strip() or ("—" in md and "Founders" not in md)'
        ),
        rationale=(
            "Restores write-then-evaluate. The exit code stays honest and the artifact does not: the "
            "founder is pointed at a file the producer itself just called empty, and the prior good "
            "answer is gone."
        ),
    ),
    Mutant(
        id="warrant_holder_election_defaults_to_cash",
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
        id="anti_dilution_renderer_prints_constant_prices",
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
# Recording is not the same as endorsing. Two of these (`_artifact_io`) are in a module no PRODUCER
# imports, so their guards protect a path nothing takes; they are here because the honest report is
# "the suite would not notice", not because each is worth a test. Read the rationale before spending
# effort on one.
#
# WHAT SEEDING MEASURED, AND WHY THIS LIST IS SHORTER THAN THE PLAN'S. Six entries were proposed as
# survivors on the strength of a hand-run pass. Two -- both MFN mutants -- were measured KILLED when
# the corpus first ran, and one of those had additionally been argued to be non-load-bearing. Both are
# in MUST_KILL above. That is the corpus paying for itself on its first execution: a hand-maintained
# list of "things the suite misses" had drifted, in the direction that matters least visibly, since
# a stale survivor entry reads as ordinary debt and never fails anything.
# ---------------------------------------------------------------------------------------------

KNOWN_SURVIVORS: tuple[Mutant, ...] = (
    Mutant(
        id="safe_cap_missing_denominator_code_renamed",
        file=f"{_SCRIPTS}/safe_conversion.py",
        find='E_SAFE_CAP_MISSING_DENOMINATOR = "E_SAFE_CAP_MISSING_DENOMINATOR"',
        replace='E_SAFE_CAP_MISSING_DENOMINATOR = "E_SAFE_CAP_MISSING_DENOMINATOR_RENAMED"',
        rationale=(
            "Renames a founder-visible diagnostic emitted at four sites, all of them executed by the "
            "suite. Nothing asserts the STRING, so the rejection still happens and the code it "
            "reports is one no downstream consumer or founder-facing surface knows. This is the "
            "error-code half of `UNASSERTED_CODE_BASELINE` in `test_cap_table_guards.py`, shown "
            "concretely rather than as a count."
        ),
    ),
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
    Mutant(
        id="note_discount_non_positive_guard_removed",
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
            "Removes the reject for a non-positive discount multiplier. A zero multiplier then "
            "produces a conversion price of 0 and an unbounded share count; a negative one produces "
            "a negative price. Either reaches the founder as ownership arithmetic."
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
                "-rf",
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
            proc = self._pytest()
        finally:
            path.write_text(original, encoding="utf-8")
            assert path.read_text(encoding="utf-8") == original, (
                f"{mutant.id}: the sandbox file did not revert; every later verdict is unreliable"
            )
        failures = [ln for ln in proc.stdout.splitlines() if ln.startswith("FAILED ") or ln.startswith("ERROR ")]
        return _Verdict(
            killed=proc.returncode != 0,
            first_failure=failures[0] if failures else "",
            tail="\n".join((proc.stdout + proc.stderr).splitlines()[-12:]),
        )
