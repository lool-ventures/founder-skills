"""Guards that exist in cap-table's producers and had nothing asserting them.

WHY A SEPARATE FILE.

An adversarial review of the coverage plan ran eight hand-written mutants against the 646-test
cap-table suite. Six survived. The most alarming was the guard added *the previous day* by the
cap-implied SAFE fix: deleting `E_CAP_IMPLIED_NOTES_PRESENT` left **594 tests green**. A guard written
in response to a founder-facing defect, reviewed, committed, and unprotected.

That is the defect class this whole thread is about, one level up: coverage cannot see it (the lines
execute), and the producer tests assert the happy path. The unit of work here is therefore a **named
guard whose removal changes a founder's number**, not a line range.

EVERY TEST IN THIS FILE IS MUTATION-VERIFIED. If disabling the guard it names does not fail it, it is
theatre and does not belong here.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

import pytest

CAP_TABLE = Path(__file__).resolve().parents[1] / "skills" / "cap-table"
SCRIPTS = CAP_TABLE / "scripts"
sys.path.insert(0, str(SCRIPTS))

import note_conversion  # type: ignore[import-not-found]  # noqa: E402
import run_scenario  # type: ignore[import-not-found]  # noqa: E402


def _cap_state(pre_fd: int) -> dict:
    import cap_state as cap_state_mod  # type: ignore[import-not-found]

    inputs = {
        "company_name": "Guards",
        "founders": [{"founder_id": "f1", "name": "F", "common_shares": pre_fd}],
        "metadata": {"run_id": "t", "schema_version": "v0.5.0-inputs"},
    }
    built: dict = cap_state_mod.build_cap_state(inputs, {"safes": [], "convertible_notes": []})
    return built


SAFE = {
    "id": "s1",
    "form": "yc_postmoney_cap",
    "purchase_amount": 500_000,
    "post_money_valuation_cap": 5_000_000,
}


class TestCapImpliedNotesGuard:
    """A convertible note outstanding must BLOCK the cap-implied snapshot.

    A note is a converting security, so it belongs in the post-money SAFE's Company Capitalization —
    the priced path counts it (`adj_pre_fd + safe_shares + note_shares`). The cap-implied path cannot
    price it without a round, so omitting it would understate the denominator and OVERSTATE every
    SAFE's cap-implied ownership: exactly the class of error the denominator fix was for.
    """

    def test_priced_params_do_not_route_around_the_guard(self) -> None:
        """THE DEFECT: the guard fired only on the cap-implied arm, and its own remedy named the
        params that leave that arm.

        `run_safe_conversion_scenario` reads `priced_round_pre_money` / `priced_round_new_money` and,
        when both are present, delegates to `solve_priced_round(..., notes=[])` -- a hardcoded empty
        list. So a founder who followed the remedy got no refusal and no note in the denominator:
        SAFE ownership overstated by exactly the class the blocker exists to prevent. `blockers` is
        also never read on that arm, so appending to it there is inert; the refusal needs its own
        return.
        """
        out = run_scenario.run_safe_conversion_scenario(
            {
                "scenario_id": "snap",
                "label": "snap",
                "type": "safe_conversion",
                "parameters": {"priced_round_pre_money": 12_000_000, "priced_round_new_money": 3_000_000},
            },
            instruments={
                "safes": [SAFE],
                "convertible_notes": [{"id": "n1", "principal": 1_000_000, "valuation_cap": 10_000_000}],
            },
            cap_state=_cap_state(8_000_000),
        )
        codes = {b.get("code") for b in out.get("blockers") or []}
        assert "E_CAP_IMPLIED_NOTES_PRESENT" in codes, (
            "priced params on a safe_conversion request routed around the notes guard; the note is "
            f"absent from the denominator and nothing said so. got: {out!r}"
        )
        assert not out.get("per_safe"), (
            "the refusal must not also ship per-SAFE numbers computed against a note-free denominator"
        )
        assert out.get("completeness") == "structural_only"

    def test_remedy_names_a_route_that_counts_the_note(self) -> None:
        """The remedy must not name `priced_round_pre_money` / `priced_round_new_money`.

        Those are `safe_conversion`'s own params -- following them re-enters the function that drops
        the note. The route that actually counts notes is a `priced_round` scenario, whose params are
        `pre_money` / `new_money`. (Neither `priced_round_*` name appears in SKILL.md, any agent body,
        reference or schema -- they exist only in this module and its consumers, which is why the old
        text read as authoritative and was not.)
        """
        out = run_scenario.run_safe_conversion_scenario(
            {"scenario_id": "snap", "label": "snap", "type": "safe_conversion", "parameters": {}},
            instruments={
                "safes": [SAFE],
                "convertible_notes": [{"id": "n1", "principal": 1_000_000, "valuation_cap": 10_000_000}],
            },
            cap_state=_cap_state(8_000_000),
        )
        remedy = next(b["remedy"] for b in out["blockers"] if b.get("code") == "E_CAP_IMPLIED_NOTES_PRESENT")
        assert "priced_round_pre_money" not in remedy and "priced_round_new_money" not in remedy, (
            f"remedy still names the params that route back into the note-dropping path: {remedy!r}"
        )
        assert "priced_round" in remedy, "remedy must name the scenario type that counts notes"

    def test_note_present_blocks_the_snapshot(self) -> None:
        out = run_scenario.run_safe_conversion_scenario(
            {"scenario_id": "snap", "label": "snap", "type": "safe_conversion", "parameters": {}},
            instruments={
                "safes": [SAFE],
                "convertible_notes": [{"id": "n1", "principal": 1_000_000, "valuation_cap": 10_000_000}],
            },
            cap_state=_cap_state(8_000_000),
        )
        codes = {b.get("code") for b in out.get("blockers") or []}
        assert "E_CAP_IMPLIED_NOTES_PRESENT" in codes, (
            "a convertible note is outstanding and the cap-implied snapshot produced no blocker. "
            "The note belongs in the post-money denominator; without it every SAFE's stated "
            f"ownership is overstated. blockers={out.get('blockers')!r}"
        )

    def test_blocked_snapshot_emits_no_per_safe_numbers(self) -> None:
        """Blocking must also withhold the numbers, not merely annotate them.

        A blocker beside a populated `per_safe` is the shape a renderer happily prints: the founder
        sees the ownership and never the warning.
        """
        out = run_scenario.run_safe_conversion_scenario(
            {"scenario_id": "snap", "label": "snap", "type": "safe_conversion", "parameters": {}},
            instruments={
                "safes": [SAFE],
                "convertible_notes": [{"id": "n1", "principal": 1_000_000, "valuation_cap": 10_000_000}],
            },
            cap_state=_cap_state(8_000_000),
        )
        assert not out.get("per_safe"), f"blocked snapshot still carries per-SAFE numbers: {out.get('per_safe')!r}"
        assert out.get("company_capitalization") is None

    def test_no_note_still_produces_the_snapshot(self) -> None:
        """Non-vacuity: the guard must not block the ordinary case."""
        out = run_scenario.run_safe_conversion_scenario(
            {"scenario_id": "snap", "label": "snap", "type": "safe_conversion", "parameters": {}},
            instruments={"safes": [SAFE], "convertible_notes": []},
            cap_state=_cap_state(8_000_000),
        )
        assert not out.get("blockers"), out.get("blockers")
        assert out["per_safe"]["s1"]["cap_implied_shares"] > 0


class TestNoConversionPathBranch:
    """`no_conversion_path` — the branch of the note enum with zero assertions.

    NOT a coverage gap: it is returned at `note_conversion.py:169` and `:184`, both of which execute on
    every run, and its handler is covered too. It is COVERED AND UNASSERTED — the same shape as the
    defect that started this work, which is why coverage percentage could never have surfaced it.
    Proven by mutation: typoing the branch string at the covered site left 646 tests green.
    """

    def test_note_with_no_cap_no_discount_and_no_maturity_has_no_conversion_path(self) -> None:
        branch, _ = note_conversion._classify_branch(
            {"id": "n1", "principal": 100_000},
            priced_round_new_money=None,
            qualified_financing_price=None,
        )
        assert branch == "no_conversion_path", (
            f"a note with no cap, no discount and no maturity disposition classified as {branch!r}. "
            "There is no term by which it can convert; any other branch would invent one."
        )

    def test_priced_context_without_terms_is_distinguished_from_no_conversion_path(self) -> None:
        """The neighbouring branch must not absorb it — they mean different things to a founder."""
        branch, _ = note_conversion._classify_branch(
            {"id": "n1", "principal": 100_000},
            priced_round_new_money=3_000_000,
            qualified_financing_price=1.25,
        )
        assert branch == "priced_round_no_cap_or_discount", branch


def _all_error_codes() -> dict[str, list[str]]:
    """Every `E_*`/`W_*` constant cap-table's producers can emit, by file."""
    codes: dict[str, list[str]] = {}
    for path in sorted(SCRIPTS.glob("*.py")):
        found = sorted(set(re.findall(r'"(E_[A-Z0-9_]+|W_[A-Z0-9_]+)"', path.read_text(encoding="utf-8"))))
        if found:
            codes[path.name] = found
    return codes


# Codes with no assertion anywhere in the suite. This is a RATCHET, not a target: it may only shrink.
# Recorded as a measured baseline rather than an aspiration, in the pattern this repo already uses for
# the founder-facing leak scan and the no-cassette allowlist. Shrinking it is the work; growing it
# means a new unguarded diagnostic shipped.
UNASSERTED_CODE_BASELINE = 27


def test_error_code_assertion_ratchet() -> None:
    """How many founder-visible diagnostics can be deleted without failing a test?

    Coverage answers "did the line run". This answers "would anyone notice if it stopped working" --
    the question that matters for a diagnostic, whose entire purpose is to fire. A code with zero
    assertions is a guard that can be removed, renamed or mis-fired silently.
    """
    suite = "\n".join(p.read_text(encoding="utf-8") for p in Path(__file__).resolve().parent.glob("test_*.py"))
    # DISTINCT codes, not occurrences. `_all_error_codes` dedups within a file but not across them, so
    # a code emitted from two producers used to count twice -- which meant merely MENTIONING an
    # unasserted code in a second source file raised the count and reddened this test, while the
    # docstring's question ("how many diagnostics are unguarded") had not changed. That is a baseline
    # measuring the wrong noun.
    unasserted = sorted(
        {
            code
            for codes in _all_error_codes().values()
            for code in codes
            if f'"{code}"' not in suite and f"'{code}'" not in suite
        }
    )
    assert len(unasserted) <= UNASSERTED_CODE_BASELINE, (
        f"{len(unasserted)} cap-table diagnostics have no assertion (baseline "
        f"{UNASSERTED_CODE_BASELINE}). A new unguarded code shipped: {unasserted!r}"
    )
    if len(unasserted) < UNASSERTED_CODE_BASELINE:
        pytest.fail(
            f"only {len(unasserted)} unasserted codes remain (baseline {UNASSERTED_CODE_BASELINE}) -- "
            f"good. Lower UNASSERTED_CODE_BASELINE to {len(unasserted)} to lock the win in. "
            f"Remaining: {unasserted!r}"
        )


# ---------------------------------------------------------------------------------------------
# Rule-level assertion ratchet, and the predicates that gate rules a founder must act on.
#
# The five predicates a plan originally hand-picked here were the wrong unit. Two were redundant
# emitters of rules another producer already emits with tested both-directions coverage; one gated
# three `counsel_review: false` solver diagnostics ("Aitken acceleration engaged") that this repo's
# own founder-text policy says must never reach a founder. Hand-picking cannot see that.
#
# The enumerable version is objective and self-selecting, and it found something worse than any of
# them: of the rule pack's 86 rule_ids, 56 are named in no test anywhere, and 23 of those carry
# `counsel_review: true` -- "take this to your lawyer" obligations with nothing asserting they fire.
# ---------------------------------------------------------------------------------------------

RULE_PACK = CAP_TABLE / "data" / "cap-table-rules.json"


def _rule_pack() -> dict[str, bool]:
    """rule_id -> counsel_review flag, for every rule in the pack."""
    rules: dict[str, bool] = {}

    def walk(node: object) -> None:
        if isinstance(node, dict):
            rid = node.get("rule_id")
            if isinstance(rid, str):
                rules[rid] = bool(node.get("counsel_review"))
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(json.loads(RULE_PACK.read_text(encoding="utf-8")))
    return rules


def _unasserted_rules() -> tuple[list[str], list[str]]:
    """Rules named in no NON-DOCSTRING string literal anywhere in the suite.

    The oracle used to be a raw text scan of every test file, so a comment or a docstring MENTIONING a
    rule id satisfied it. That is not a hypothetical: five rules counted as covered on prose alone,
    and the workaround -- "do not name a rule id in a docstring" -- had to be applied three times in
    one session, each time hiding the fact that the oracle was wrong rather than the docstring.

    Parsing with `ast` and considering only string literals that are not docstrings removes the
    comment channel entirely. Note what it still does NOT do: it measures MENTION, not assertion.
    Measured, 12 of the 26 rules it counts as covered appear in no `assert` statement at all -- one
    qualifies solely by being a sample string in an unrelated text-policy test. Treat the number as
    "how many rules could be deleted without any test noticing by name", not as a coverage figure.
    """
    import ast as _ast

    literals: set[str] = set()
    for path in Path(__file__).resolve().parent.glob("test_*.py"):
        try:
            tree = _ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - defensive
            continue
        docstrings = set()
        for node in _ast.walk(tree):
            if isinstance(node, (_ast.Module, _ast.ClassDef, _ast.FunctionDef, _ast.AsyncFunctionDef)):
                doc = _ast.get_docstring(node, clean=False)
                if doc is not None:
                    docstrings.add(doc)
        for node in _ast.walk(tree):
            if isinstance(node, _ast.Constant) and isinstance(node.value, str) and node.value not in docstrings:
                literals.add(node.value)
    joined = "\n".join(literals)
    rules = _rule_pack()
    unasserted = sorted(r for r in rules if r not in joined)
    return unasserted, sorted(r for r in unasserted if rules[r])


# Measured baselines. RATCHETS: they may only shrink. The counsel figure is tracked separately because
# a counsel-review rule is an obligation a founder is told to take to a lawyer -- a silently-suppressed
# one is the most expensive thing this skill can get wrong.
# 54 -> 55, a deliberate RAISE that corrects a false win rather than conceding ground. The 54 was
# earned earlier today because a counsel-packet seed named ONE rule id verbatim (deliberately not
# repeated here -- writing it would re-satisfy the very substring test this comment is about), and
# this ratchet's oracle is a bare substring test over the suite text. That seed checked
# the rule's TEXT was clean; it never checked the rule FIRES, which is what this ratchet counts. When
# the seed was replaced by a strictly stronger loop over all 86 rules, the verbatim mention vanished
# and the number went back up -- the guard improved and the metric worsened, which is the tell that
# the metric was measuring the mention, not the assertion. Ratcheting down on a substring is the
# exact failure this file was written to catch, so it is corrected here rather than preserved.
# NOT a raise of the old 55. That number came from a different instrument -- a raw text scan that
# counted comments and docstrings -- and the two are not comparable, so the constant is renamed rather
# than adjusted. Under the AST oracle the true figure is 60; the five-rule difference is the prose
# mentions the old scan was crediting.
UNASSERTED_RULE_BASELINE_AST = 60
UNASSERTED_COUNSEL_RULE_BASELINE = 22  # same correction as above


def test_rule_assertion_ratchet() -> None:
    """How many rule_ids can be deleted from the pack without failing a test?

    Coverage says a predicate executed. This says whether anyone would notice if the rule it gates
    stopped firing -- which for a counsel-review item is the difference between a founder being told
    to consult counsel and not being told.
    """
    unasserted, counsel = _unasserted_rules()
    assert len(unasserted) <= UNASSERTED_RULE_BASELINE_AST, (
        f"{len(unasserted)} rule_ids have no assertion (baseline {UNASSERTED_RULE_BASELINE_AST}); "
        f"a new unguarded rule shipped: {sorted(set(unasserted))[:8]}"
    )
    assert len(counsel) <= UNASSERTED_COUNSEL_RULE_BASELINE, (
        f"{len(counsel)} COUNSEL-REVIEW rules have no assertion (baseline "
        f"{UNASSERTED_COUNSEL_RULE_BASELINE}): {counsel[:8]}"
    )
    if len(unasserted) < UNASSERTED_RULE_BASELINE_AST or len(counsel) < UNASSERTED_COUNSEL_RULE_BASELINE:
        pytest.fail(
            f"unasserted rules down to {len(unasserted)} (baseline {UNASSERTED_RULE_BASELINE_AST}) and "
            f"counsel-review to {len(counsel)} (baseline {UNASSERTED_COUNSEL_RULE_BASELINE}) -- good. "
            "Lower the baselines to lock the win in."
        )


class TestRuleApplicabilityPredicates:
    """`_evaluate_freshness` — the one hand-picked predicate that survived review.

    The four others originally proposed were dropped: two are redundant emitters of rules
    `flip_scenario.py` already emits with tested both-directions coverage, one gates three
    `counsel_review: false` solver diagnostics that must never reach a founder anyway, and
    `_any_warrant_event_with` is a nested closure with no importable surface — a unit test of it
    could not be written, only a test of its caller.

    Both directions, because a one-directional test passes against a predicate hardcoded to the value
    it asserts. Mutation-verified: `return "fresh"` unconditionally fails this.
    """

    def test_stale_and_fresh_benchmarks_are_distinguished(self) -> None:
        from datetime import date

        import rule_audit  # type: ignore[import-not-found]

        window_start, window_end = date(2026, 1, 1), date(2026, 2, 1)
        fresh = rule_audit._evaluate_freshness(date(2026, 1, 15), window_start, window_end)
        stale = rule_audit._evaluate_freshness(date(2019, 1, 1), window_start, window_end)
        assert fresh != stale, (
            f"a benchmark dated inside the freshness window scores {fresh!r} and a seven-year-old one "
            f"scores {stale!r}. If they agree, a stale benchmark is presented to a founder as current."
        )

    def test_absent_benchmark_reference_is_its_own_state(self) -> None:
        """Unknown must not silently collapse into fresh — the failure that reads as a clean result."""
        from datetime import date

        import rule_audit  # type: ignore[import-not-found]

        unknown = rule_audit._evaluate_freshness(None, date(2026, 1, 1), date(2026, 2, 1))
        fresh = rule_audit._evaluate_freshness(date(2026, 1, 15), date(2026, 1, 1), date(2026, 2, 1))
        assert unknown != fresh, f"a benchmark with no reference date scores {unknown!r}, same as fresh"


class TestConciseReportDoesNotClobberOnReject:
    """A rejected concise run must leave the founder-facing markdown untouched.

    It used to render, WRITE, then evaluate, then return 2 — leaving a file the producer had just
    called empty at the path the founder is pointed to. Milder than the defect `_fail_invalid` exists
    for (those six wrote a stub through `-o` and returned 0) but the same shape: an honest exit code
    and a dishonest artifact.
    """

    @staticmethod
    def _run(tmp_path: Path, scenarios: dict, prior: str) -> tuple[int, str, str, str]:
        import subprocess

        inputs = {
            "company_name": "X",
            "founders": [{"founder_id": "f1", "name": "A", "common_shares": 8_000_000}],
            "metadata": {"run_id": "t", "schema_version": "v0.5.0-inputs"},
        }
        (tmp_path / "in.json").write_text(json.dumps(inputs), encoding="utf-8")
        (tmp_path / "sc.json").write_text(json.dumps(scenarios), encoding="utf-8")
        out = tmp_path / "out.md"
        out.write_text(prior, encoding="utf-8")
        r = subprocess.run(
            [
                sys.executable,
                str(SCRIPTS / "concise_report.py"),
                "--inputs",
                str(tmp_path / "in.json"),
                "--scenarios",
                str(tmp_path / "sc.json"),
                "--run-id",
                "t",
                "-o",
                str(out),
            ],
            capture_output=True,
            text=True,
        )
        return r.returncode, r.stdout, r.stderr, out.read_text(encoding="utf-8")

    def test_rejected_render_leaves_the_prior_markdown_intact(self, tmp_path: Path) -> None:
        rc, stdout, stderr, body = self._run(tmp_path, {"scenarios": [], "metadata": {"run_id": "t"}}, "PRIOR")
        assert rc != 0, "an empty concise answer must not report success"
        assert body == "PRIOR", (
            "the rejected run overwrote the founder-facing markdown. The prior good answer is gone and "
            f"what replaced it is the one the producer called empty. body={body!r}"
        )
        assert '"ok": false' in stdout.replace(" ", "").replace('"ok":false', '"ok": false'), stdout
        assert "left unchanged" in stderr, stderr

    def test_ok_render_still_writes(self, tmp_path: Path) -> None:
        """Non-vacuity: the guard must not block a real answer."""
        scenarios = {
            "metadata": {"run_id": "t"},
            "scenarios": [
                {
                    "scenario_id": "s",
                    "label": "Series A",
                    "type": "priced_round",
                    "parameters": {"pre_money": 12_000_000, "new_money": 3_000_000},
                    "computed_outputs": {
                        "completeness": "full",
                        "aggregate_ownership_by_class": {"founders_pct": 0.63, "new_money_pct": 0.20},
                        "equity_financing_price": 1.1813,
                    },
                }
            ],
        }
        rc, _stdout, _stderr, body = self._run(tmp_path, scenarios, "PRIOR")
        assert rc == 0, f"a complete scenario was rejected: {_stdout} {_stderr}"
        assert body != "PRIOR" and body.strip(), "an accepted render wrote nothing"


class TestWarrantHolderElection:
    """`holder_election` — an entire warrant settlement type with no test.

    A holder-election warrant lets the holder choose cash exercise or net-share settlement AT exercise.
    The choice changes the share count added to the cap table, so getting it wrong changes every
    founder percentage downstream. `warrant_exercise.py` is the lowest-covered cap-table file (66%) and
    this branch is the reason.
    """

    @staticmethod
    def _warrant(choice: object) -> dict:
        return {
            "warrant_id": "w1",
            "settlement_type": "holder_election",
            "holder_election_choice": choice,
            "shares_underlying": 100_000,
            "exercise_price": 1.0,
        }

    def test_election_of_cash_routes_to_cash_exercise(self) -> None:
        import warrant_exercise  # type: ignore[import-not-found]

        r = warrant_exercise.exercise_warrant(
            self._warrant("cash"), last_priced_round_pps=2.0, pre_money=None, pre_pump_fully_diluted=None
        )
        assert r["exercise_path"] == "holder_election -> cash_exercise", r

    def test_election_of_net_share_routes_to_net_share_settlement(self) -> None:
        import warrant_exercise  # type: ignore[import-not-found]

        r = warrant_exercise.exercise_warrant(
            self._warrant("net_share"), last_priced_round_pps=2.0, pre_money=None, pre_pump_fully_diluted=None
        )
        assert r["exercise_path"] == "holder_election -> net_share_settlement", r
        assert r["shares_added"] != 100_000, (
            "net-share settlement must withhold shares to cover the exercise price; adding the full "
            f"underlying count means the founder is diluted as if the holder paid cash. {r}"
        )

    def test_unspecified_election_is_refused_not_guessed(self) -> None:
        """The one that matters: an unstated choice must NOT silently default to either branch."""
        import warrant_exercise  # type: ignore[import-not-found]

        with pytest.raises(warrant_exercise.WarrantPumpError) as excinfo:
            warrant_exercise.exercise_warrant(
                self._warrant(None), last_priced_round_pps=2.0, pre_money=None, pre_pump_fully_diluted=None
            )
        assert "E_WARRANT_HOLDER_ELECTION_UNSPECIFIED" in str(excinfo.value)


class TestComputedReachesTheRenderedReport:
    """The "computed, not rendered" class — which this repo records as UNGATED for cap-table.

    `test_delivery_coverage.py` lists cap-table in `_UNGATED_SKILLS` for exactly this defect class: a
    producer computes a number and the renderer never prints it, or prints a different one. The
    per-series anti-dilution breakdown is the clearest instance — 115 statements of
    `render_report_markdown` execute in no test, so no composed `report.md` in the suite has ever
    contained this block, and the fleet's founder-text scan cannot inspect a section that never rendered.

    NOT a leak, checked: the `(rule: ...)` provenance token this block emits is a type-3 identifier
    under `_founder_text` (`_ID_KEY_SUFFIXES` includes `_id`), preserved verbatim on purpose so an id
    correlates across report.md, the explorer and the counsel packet. cap-table ships
    `_Provenance: rules:` lines in production for the same reason. Asserting it away would break
    traceability, so this asserts the NUMBERS instead.
    """

    @staticmethod
    def _artifacts(
        ccp_before: float,
        ccp_after: float,
        *,
        floor_applied: bool = False,
        unfloored: float | None = None,
    ) -> dict:
        scen = {
            "metadata": {"run_id": "t"},
            "scenarios": [
                {
                    "scenario_id": "s",
                    "label": "Series A",
                    "type": "priced_round",
                    "parameters": {"pre_money": 12_000_000, "new_money": 3_000_000},
                    "computed_outputs": {
                        "completeness": "full",
                        "aggregate_ownership_by_class": {"founders_pct": 0.63},
                        "equity_financing_price": 1.18,
                        "anti_dilution_breakdown": [
                            {
                                "series_id": "series_a",
                                "protection_type": "broad_based_weighted_average",
                                "ccp_before": ccp_before,
                                "ccp_after": ccp_after,
                                "floor_applied": floor_applied,
                                **({} if unfloored is None else {"ccp_unfloored": unfloored}),
                                "rule_id": "anti_dilution.trigger_basis_current_conversion_price",
                            }
                        ],
                    },
                }
            ],
        }
        return {
            "inputs.json": {
                "company_name": "X",
                "founders": [{"founder_id": "f1", "name": "A", "common_shares": 8_000_000}],
                "metadata": {"run_id": "t", "schema_version": "v0.5.0-inputs"},
            },
            "cap_state.json": {
                "as_converted_totals": {
                    "fully_diluted_shares": 8_000_000,
                    "common_shares": 8_000_000,
                    "preferred_shares_as_converted": 0,
                    "options_outstanding": 0,
                    "options_available": 0,
                    "warrants_underlying_total": 0,
                },
                "outstanding_safes": [],
                "metadata": {"run_id": "t"},
            },
            "scenarios.json": scen,
            "rule_audit.json": {"date_sensitive_watchlist": [], "metadata": {"run_id": "t"}},
            "counsel_packet.json": {"items": [], "metadata": {"run_id": "t"}},
        }

    def _render(
        self,
        ccp_before: float,
        ccp_after: float,
        *,
        floor_applied: bool = False,
        unfloored: float | None = None,
    ) -> str:
        import compose_report  # type: ignore[import-not-found]

        md: str = compose_report.render_report_markdown(
            artifacts=self._artifacts(ccp_before, ccp_after, floor_applied=floor_applied, unfloored=unfloored),
            validation_warnings=[],
            insertion_marker="MARKER",
        )
        return md

    def test_anti_dilution_breakdown_reaches_the_report(self) -> None:
        md = self._render(1.0, 0.82)
        assert "Anti-dilution adjustments (per series)" in md, (
            "the per-series AD breakdown was computed and never rendered. A founder whose preferred "
            "conversion price moved is not told it moved."
        )

    def test_rendered_conversion_prices_are_the_computed_ones(self) -> None:
        """Computed == rendered. The check the delivery-coverage map records as missing here.

        Asserting the section merely EXISTS would pass against a renderer printing constants; these
        are two different CCP pairs and the rendered text must track them.
        """
        for before, after in ((1.0, 0.82), (2.5, 1.25)):
            md = self._render(before, after)
            line = next((line for line in md.splitlines() if "CCP $" in line), None)
            assert line, f"no CCP line rendered for {before} -> {after}"
            assert f"${before:.4f}" in line and f"${after:.4f}" in line, (
                f"renderer printed {line!r} for a breakdown computed as CCP {before} -> {after}. "
                "The founder is reading a number the math did not produce."
            )


class TestAntiDilutionNeverRaisesTheConversionPrice:
    """Anti-dilution reduces the conversion price. Nothing asserted that it could not raise it.

    The gap this closes: `test_coupled_solver_goldens.py`'s Golden 10 pinned the CP2 floor with
    floor=0.50 under CP1=1.00, where the clamp can only raise CP2 toward a price still below CP1. A
    floor ABOVE CP1 -- schema-valid, since `ad_cp2_floor` is typed `["number", "null"]` with no
    relation to its series -- made the same clamp emit a CP2 above CP1. That is anti-dilution that
    dilutes, and the only signal was `W_CP2_FLOOR_APPLIED`, a medium warning naming the clamp rather
    than the contradiction.

    Two layers, tested separately because they fail differently: the solver REJECTS the contradictory
    input (Golden 10b/10c), and the per-series math RAISES if a ratchet-up is ever computed anyway.
    """

    @staticmethod
    def _series(**over: object) -> dict:
        s = {
            "series_id": "series_seed",
            "shares": 2_000_000,
            "original_issue_price": 1.00,
            "original_conversion_price": 1.00,
            "current_conversion_price": 1.00,
            "anti_dilution_protection": "broad_based_weighted_average",
        }
        s.update(over)  # type: ignore[arg-type]
        return s

    @staticmethod
    def _a_components() -> dict:
        return {
            "common_shares": 10_000_000,
            "preferred_shares_as_converted": 2_000_000,
            "options_outstanding": 0,
            "options_available": 1_000_000,
            "warrants_underlying_total": 0,
        }

    def test_post_condition_raises_when_a_ratchet_up_is_computed(self) -> None:
        """The second layer, reached by calling the math directly past the entry-point validation.

        Deliberately bypasses `solve_priced_round`: its input check makes this unreachable through
        the public path, which is exactly why the post-condition needs its own test. Without one, a
        future caller of `_apply_anti_dilution` -- or a regression in the entry check -- silently
        restores the original defect.
        """
        import priced_round  # type: ignore[import-not-found]

        with pytest.raises(priced_round.AntiDilutionContradiction) as exc:
            priced_round._apply_anti_dilution(
                preferred_series=[self._series(ad_cp2_floor=2.00)],
                cp1_snapshots={"series_seed": 1.00},
                new_pps=0.0667,
                consideration=5_000_000.0,
                a_components=self._a_components(),
                cap_table_history=[],
            )
        assert exc.value.code == "E_AD_RATCHET_UP_NOT_ALLOWED"
        assert exc.value.series_id == "series_seed"

    def test_a_legitimate_floor_still_clamps_and_warns(self) -> None:
        """The guard must not swallow the case the floor exists for.

        A floor BELOW CP1 is the ordinary NVCA term: it limits how far CP2 falls. If the new
        post-condition were written as `cp2 != cp1` or the entry check as `floor is not None`, this
        goes from a warned clamp to a raise or a blocked round, and the feature is gone.
        """
        import priced_round  # type: ignore[import-not-found]

        _muts, breakdown, warnings = priced_round._apply_anti_dilution(
            preferred_series=[self._series(ad_cp2_floor=0.50)],
            cp1_snapshots={"series_seed": 1.00},
            new_pps=0.0667,
            consideration=5_000_000.0,
            a_components=self._a_components(),
            cap_table_history=[],
        )
        assert breakdown[0]["floor_applied"] is True
        assert breakdown[0]["ccp_after"] == 0.50
        assert any(w["code"] == "W_CP2_FLOOR_APPLIED" for w in warnings)

    @pytest.mark.parametrize(
        ("cp1", "new_price", "consideration", "a_shares"),
        [
            (1.00, 0.50, 1_000_000.0, 10_000_000),
            (1.00, 0.01, 50_000_000.0, 1_000_000),  # brutal down round, tiny A
            (0.001, 0.0001, 10.0, 5),  # sub-cent prices, near-degenerate A
            (100.0, 99.999, 1.0, 1_000_000_000),  # barely-triggered, huge A
        ],
    )
    def test_bbwa_output_is_never_above_its_input_price(
        self, cp1: float, new_price: float, consideration: float, a_shares: int
    ) -> None:
        """The arithmetic guarantee the removed `new_shares_issued_C` override could break.

        With C derived (C = consideration / new_price), B/C == new_price/CP1 < 1 whenever the
        adjustment triggers, so (A+B)/(A+C) < 1 and CP2 < CP1 for every input. A caller-supplied C
        broke that identity -- nothing passed a disagreeing value, so the parameter bought no
        expressiveness while making the invariant a hope. These four cases span the ranges where a
        floating-point violation would show up first.
        """
        import anti_dilution  # type: ignore[import-not-found]

        r = anti_dilution.bbwa_new_conversion_price(
            current_conversion_price=cp1,
            pre_issuance_share_count_A=a_shares,
            consideration_received=consideration,
            new_issue_price=new_price,
        )
        assert r["new_conversion_price"] <= cp1, r

    def test_bbwa_refuses_a_non_positive_new_price(self) -> None:
        """A free issuance satisfies `new_price < CP1` and would divide by zero deriving C.

        Previously survivable by passing `new_shares_issued_C` explicitly; with C always derived the
        input has to be refused rather than silently producing inf/NaN and carrying it into a
        founder's post-round ownership.
        """
        import anti_dilution  # type: ignore[import-not-found]

        with pytest.raises(ValueError, match="new_issue_price"):
            anti_dilution.bbwa_new_conversion_price(
                current_conversion_price=1.0,
                pre_issuance_share_count_A=10_000_000,
                consideration_received=1_000_000,
                new_issue_price=0.0,
            )


class TestSolverWarningsReachTheFounder:
    """The solver's warnings were computed, serialised, and dropped before the report.

    `compose_report` rendered only `cap_state["warnings"]` -- a list of STRINGS -- via
    `_warning_callouts.render_warning_callouts`. The priced-round solver emits DICTS onto
    `scenarios.json`'s `computed_outputs.warnings`, and the composer read that list in exactly two
    places, both testing for one unrelated code. So `W_MFN_NOT_MOST_FAVORABLE`,
    `W_MFN_ELECTION_OVERRIDES_INSTRUMENT`, `W_CP2_FLOOR_APPLIED`, `W_STALE_CCP_SUSPECTED` and
    `W_SOLVER_AITKEN_FALLBACK` reached the founder through nothing at all.

    The MFN case is a stated contract, not just an omission: `agents/cap-table.md` says that when the
    solver emits `W_MFN_NOT_MOST_FAVORABLE` "the report should label it as such, not as the holder's
    actual entitlement." Nothing labelled it, so a counterfactual election was presented as the
    holder's entitlement.
    """

    @staticmethod
    def _artifacts(solver_warnings: list[dict]) -> dict:
        return {
            "inputs.json": {
                "company_name": "X",
                "founders": [{"founder_id": "f1", "name": "A", "common_shares": 8_000_000}],
                "metadata": {"run_id": "t", "schema_version": "v0.5.0-inputs"},
            },
            "cap_state.json": {
                "as_converted_totals": {
                    "fully_diluted_shares": 8_000_000,
                    "common_shares": 8_000_000,
                    "preferred_shares_as_converted": 0,
                    "options_outstanding": 0,
                    "options_available": 0,
                    "warrants_underlying_total": 0,
                },
                "outstanding_safes": [],
                "metadata": {"run_id": "t"},
            },
            "scenarios.json": {
                "metadata": {"run_id": "t"},
                "scenarios": [
                    {
                        "scenario_id": "s1",
                        "type": "priced_round",
                        "computed_outputs": {
                            "completeness": "full",
                            "aggregate_ownership_by_class": {"founders_pct": 0.63},
                            "equity_financing_price": 1.18,
                            "warnings": solver_warnings,
                        },
                    }
                ],
            },
            "rule_audit.json": {"date_sensitive_watchlist": [], "metadata": {"run_id": "t"}},
            "counsel_packet.json": {"items": [], "metadata": {"run_id": "t"}},
        }

    def _render(self, solver_warnings: list[dict]) -> str:
        import compose_report  # type: ignore[import-not-found]

        md: str = compose_report.render_report_markdown(
            artifacts=self._artifacts(solver_warnings),
            validation_warnings=[],
            insertion_marker="MARKER",
        )
        return md

    def test_mfn_counterfactual_is_labelled_as_the_agent_contract_requires(self) -> None:
        md = self._render(
            [
                {
                    "code": "W_MFN_NOT_MOST_FAVORABLE",
                    "instance_id": "safe_mfn_1",
                    "detail": "elected terms are not the most favourable available",
                }
            ]
        )
        assert "counterfactual" in md.lower(), (
            "the solver said this MFN election is NOT the holder's entitlement and the report did not "
            "say so. agents/cap-table.md requires the report to label it."
        )
        assert "safe_mfn_1" in md, "the founder is not told WHICH instrument the caveat is about"

    def test_floor_clamp_warning_reaches_the_report(self) -> None:
        md = self._render([{"code": "W_CP2_FLOOR_APPLIED", "series_id": "series_seed"}])
        assert "floor" in md.lower() and "series_seed" in md

    def test_an_unrecognised_solver_warning_is_still_surfaced(self) -> None:
        """Unknown codes must render, not vanish.

        Skipping them would reintroduce the exact silent-drop defect this renderer exists to fix: a
        warning family added to the solver later would be invisible until someone remembered to add a
        branch here. The code itself stays out of the prose -- it is our vocabulary, not a founder's.
        """
        md = self._render([{"code": "W_SOME_FUTURE_SOLVER_WARNING", "instance_id": "note_1"}])
        assert "worth checking" in md.lower(), "an unrecognised solver warning was dropped silently"
        assert "W_SOME_FUTURE_SOLVER_WARNING" not in md, "raw warning code leaked into founder prose"

    def test_convergence_fallback_warning_reaches_the_report(self) -> None:
        """Guards the one solver warning this renderer newly surfaces that nothing else asserted.

        It matters more than it looks: it is the solver saying its own arithmetic was hard to settle.
        A founder is entitled to know the ownership figures came out of a fallback path.
        """
        md = self._render([{"code": "W_SOLVER_AITKEN_FALLBACK"}])
        assert "fallback" in md.lower()
        assert "W_SOLVER_AITKEN_FALLBACK" not in md, "raw code leaked into founder prose"

    def test_no_solver_warnings_renders_nothing(self) -> None:
        """The block must not appear as an empty scare-callout on a clean round."""
        md = self._render([])
        assert "worth checking" not in md.lower()

    def test_the_same_warning_about_the_same_instrument_is_stated_once(self) -> None:
        dup = {"code": "W_CP2_FLOOR_APPLIED", "series_id": "series_seed"}
        md = self._render([dup, dict(dup), dict(dup)])
        assert md.lower().count("charter's price floor") == 1

    def test_malformed_entries_do_not_cost_the_founder_the_valid_ones(self) -> None:
        """This list is read back off a JSON artifact a prior step may have written loosely."""
        junk: list[Any] = ["not-a-dict", {}, {"code": ""}, {"code": "W_CP2_FLOOR_APPLIED", "series_id": "s"}]
        md = self._render(junk)
        assert "charter's price floor" in md


class TestCharterFloorIsExtractable:
    """A real charter term the skill could not read, costing the founder ownership.

    An anti-dilution conversion-price floor is a common NVCA charter term -- the rule pack says so on
    primary sourcing (the CP2-floor rule carries source_basis "primary"). Its rule_id is deliberately
    NOT written out here: `_unasserted_rules` above is a bare substring test over the suite text, so
    naming a rule in a docstring drops it out of the ratchet with no assertion behind it. That would
    be a false win in the guard whose whole purpose is counting false wins. The solver has
    consumed `ad_cp2_floor` all along, and `af4523d` hardened its edge cases. But NOTHING could
    produce it: absent from `extract_aoa.py`, from the AoA target-field list in `agents/cap-table.md`,
    and from `references/inputs-skeleton.md`, which enumerated the preferred-series fields and omitted
    it. Two schemas declared it and `cap_state.py` passed it through, so the field looked supported.

    The cost is not cosmetic and it runs AGAINST the founder. The floor limits how far the conversion
    price falls; missing it lets the price fall further, inflating preferred-as-converted. Measured on
    the golden-10 cap table: 11.11% founder ownership with a $0.50 floor honoured, 5.95% without --
    a 1.87x understatement, silently, in the skill whose job is telling founders what they own.
    (`test_golden_10d` pins those figures.)

    These tests guard the PATH, not the math: that the extractor accepts the field, that it survives
    the merge into inputs.json, and that the three authoring surfaces still document it.
    """

    def test_extractor_accepts_a_charter_floor(self) -> None:
        import extract_aoa  # type: ignore[import-not-found]

        errors = extract_aoa.validate_aoa_extraction(
            {
                "extraction_type": "articles_of_association",
                "fields": {
                    "preferred_series": [
                        {
                            "series_name": "Series Seed",
                            "original_issue_price": 1.00,
                            "original_conversion_price": 1.00,
                            "current_conversion_price": 1.00,
                            "anti_dilution_protection": "broad_based_weighted_average",
                            "ad_cp2_floor": 0.50,
                        }
                    ]
                },
            }
        )
        assert errors == [], errors

    def test_extractor_rejects_a_non_positive_floor(self) -> None:
        """A zero or negative floor is a misread, not a charter term."""
        import extract_aoa  # type: ignore[import-not-found]

        errors = extract_aoa.validate_aoa_extraction(
            {
                "extraction_type": "articles_of_association",
                "fields": {
                    "preferred_series": [
                        {
                            "series_name": "Series Seed",
                            "original_issue_price": 1.00,
                            "original_conversion_price": 1.00,
                            "current_conversion_price": 1.00,
                            "ad_cp2_floor": 0,
                        }
                    ]
                },
            }
        )
        assert any("ad_cp2_floor" in e for e in errors), errors

    def test_absent_floor_is_not_an_error(self) -> None:
        """Most charters have no floor. Absence must stay a reading of the document, not a failure."""
        import extract_aoa  # type: ignore[import-not-found]

        errors = extract_aoa.validate_aoa_extraction(
            {
                "extraction_type": "articles_of_association",
                "fields": {
                    "preferred_series": [
                        {
                            "series_name": "Series Seed",
                            "original_issue_price": 1.00,
                            "original_conversion_price": 1.00,
                            "current_conversion_price": 1.00,
                        }
                    ]
                },
            }
        )
        assert errors == [], errors

    def test_floor_survives_the_merge_into_inputs(self, tmp_path: Path) -> None:
        """The whole point is end-to-end reach: extractor -> inputs.json -> cap_state -> solver.

        Guards against a future field whitelist in `merge_into_inputs` silently dropping it, which
        would restore the defect while every extraction test stayed green.
        """
        import extract_aoa  # type: ignore[import-not-found]

        inputs_path = tmp_path / "inputs.json"
        inputs_path.write_text(
            json.dumps(
                {
                    "company_name": "X",
                    "founders": [{"founder_id": "f1", "name": "A", "common_shares": 8_000_000}],
                    "metadata": {"run_id": "t", "schema_version": "v0.5.0-inputs"},
                }
            ),
            encoding="utf-8",
        )
        extract_aoa.merge_into_inputs(
            str(inputs_path),
            [
                {
                    "series_name": "Series Seed",
                    "original_issue_price": 1.00,
                    "original_conversion_price": 1.00,
                    "current_conversion_price": 1.00,
                    "anti_dilution_protection": "broad_based_weighted_average",
                    "ad_cp2_floor": 0.50,
                }
            ],
            source_doc="aoa.pdf",
        )
        merged = json.loads(inputs_path.read_text(encoding="utf-8"))
        assert merged["preferred_series"][0]["ad_cp2_floor"] == 0.50, (
            "the charter floor was dropped between extraction and inputs.json; the solver would "
            "silently understate founder ownership"
        )

    def test_authoring_surfaces_document_the_charter_fields(self) -> None:
        """The drift guard for the defect class -- and it must check the LOAD-BEARING surface.

        The first version of this test asserted the field name appeared anywhere in three files. It
        passed on a prose bullet in `agents/cap-table.md` while BOTH JSON return-shape blocks -- the
        thing a sub-agent actually copies, one of them headed "load-bearing (`extract_aoa.py` won't
        accept other shapes)" -- omitted the field entirely. `lane-1-pdf-docx.md` was not even in the
        file list. So the guard was green with the field unsuppliable: a test that cannot fail when
        the thing it names is broken, which is the defect this file exists to catch.

        Now it parses the fenced JSON block and asserts the key is IN the object a sub-agent returns.
        """
        surfaces = {
            "agents/cap-table.md": Path(__file__).resolve().parents[1] / "agents" / "cap-table.md",
            "lanes/lane-1-pdf-docx.md": CAP_TABLE / "references" / "lanes" / "lane-1-pdf-docx.md",
            "inputs-skeleton.md": CAP_TABLE / "references" / "inputs-skeleton.md",
        }
        # The test is JSON-KEY form (`"field":`) near the other per-series keys -- not the bare name
        # anywhere in the file. That distinction IS the defect: `ad_cp2_floor` appeared only as a
        # prose bullet in agents/cap-table.md and not at all in lane-1's block, which is headed
        # "load-bearing (extract_aoa.py won't accept other shapes)". Prose tells a sub-agent the field
        # exists; the block is what it copies.
        for field in ("ad_cp2_floor", "ad_a_denominator_basis"):
            for label, path in surfaces.items():
                text = path.read_text(encoding="utf-8")
                anchors = [i for i in range(len(text)) if text.startswith('"anti_dilution_protection":', i)]
                assert anchors, f"{label} has no per-series JSON example to check"
                assert any(f'"{field}":' in text[max(0, a - 1200) : a + 1200] for a in anchors), (
                    f'{label} does not carry "{field}" as a JSON key beside the other per-series '
                    "keys. A prose mention does not make a field suppliable -- the sub-agent copies "
                    "the block, and the solver then silently uses a default the charter may contradict."
                )

        # The validator must also accept them, or a compliant extraction is rejected.
        extractor = (SCRIPTS / "extract_aoa.py").read_text(encoding="utf-8")
        for field in ("ad_cp2_floor", "ad_a_denominator_basis"):
            assert field in extractor, f"extract_aoa.py does not know about {field}"

        # `cap_table_history` is TOP-LEVEL, not a per-series key, so the proximity test above cannot
        # reach it -- but it is the same defect class (schema-declared, fully consumed, unsuppliable)
        # and needs the same guard. Checked on the two surfaces that can supply it plus the validator.
        for label, path in (
            ("agents/cap-table.md", Path(__file__).resolve().parents[1] / "agents" / "cap-table.md"),
            ("inputs-skeleton.md", CAP_TABLE / "references" / "inputs-skeleton.md"),
        ):
            text = path.read_text(encoding="utf-8")
            assert "cap_table_history" in text and "anti_dilution_applied" in text, (
                f"{label} does not document cap_table_history with its event shape. The solver reads "
                "it from three sites and the cap state passes it straight through from inputs; a "
                "surface that never names it cannot supply it, and the stale-price warning that "
                "depends on it goes back to being unfirable."
            )
        # Behaviour, not a substring: the previous form was satisfied by a COMMENT mentioning the
        # field, with the entire validation block deleted.
        import extract_aoa  # type: ignore[import-not-found]

        errs = extract_aoa.validate_aoa_extraction(
            {
                "extraction_type": "articles_of_association",
                "cap_table_history": [{"event_type": "MADE_UP", "series_id": "s1"}],
                "fields": {"preferred_series": []},
            }
        )
        assert any("event_type" in e for e in errs), (
            "extract_aoa.py does not validate cap_table_history. A field a sub-agent is told to "
            f"produce, with nothing checking its shape, is a hallucination surface. Got: {errs}"
        )


class TestClampedMagnitudeReachesTheFounder:
    """ "(floor clamped)" told the founder a clamp happened, never how much it cost.

    `ccp_unfloored` -- the conversion price the anti-dilution adjustment WOULD have produced -- has
    always been computed and written to `scenarios.json`, and was rendered by nothing. Both surfaces
    (`compose_report`'s markdown and `visualize`'s HTML) printed the bare parenthetical. The number
    that makes a floor meaningful, i.e. how much protection it removed, never reached anyone.

    This is the same shape as the solver-warning drop above: computed, serialised, discarded at the
    last step.
    """

    def test_markdown_states_what_the_adjustment_would_have_been(self) -> None:
        md = TestComputedReachesTheRenderedReport()._render(1.0, 0.50, floor_applied=True, unfloored=0.2045)
        assert "0.2045" in md, (
            "the founder is told the floor clamped but not what it clamped FROM, which is the only "
            "number that says how much protection the floor removed"
        )

    def test_missing_unfloored_value_does_not_crash_the_report(self) -> None:
        """`ccp_unfloored` is NOT in scenarios.schema.json's `required` list.

        A schema-valid breakdown may omit it, and an f-string over None would take down the entire
        report for a cosmetic field. Degrade to the plainer sentence instead.
        """
        md = TestComputedReachesTheRenderedReport()._render(1.0, 0.50, floor_applied=True, unfloored=None)
        assert "charter's floor" in md
        assert "None" not in md.split("Anti-dilution")[-1][:400]

    def test_no_floor_note_when_no_clamp_occurred(self) -> None:
        md = TestComputedReachesTheRenderedReport()._render(1.0, 0.82)
        assert "would have taken it to" not in md

    def test_html_renderer_states_the_same_magnitude(self) -> None:
        """Both renderers or neither: report.html is a second surface that has drifted before."""
        import visualize  # type: ignore[import-not-found]

        note = visualize._floor_note({"floor_applied": True, "ccp_unfloored": 0.2045})
        assert "0.2045" in note
        assert visualize._floor_note({"floor_applied": False, "ccp_unfloored": 0.2045}) == ""
        assert "0.0000" not in visualize._floor_note({"floor_applied": True})


class TestStaleConversionPriceIsReachable:
    """The stale-price warning existed for a long time and could not fire for a real founder.

    Two independent reasons, both fixed here rather than worked around:

    1. WRONG PLACE. `priced_round`'s copy sits behind three unrelated gates -- the round must carry
       anti-dilution protection, the SERIES must be protected, and the new price must be below the
       trigger. A cap table carrying the exact contradiction on an unprotected series produced
       nothing. The predicate is a property of the cap state alone, so it belongs where the cap state
       is built.
    2. NO INPUT ROUTE. It reads `cap_table_history`, which `cap_state.py` passes straight through
       from `inputs.json` and which NO authoring surface mentioned -- not SKILL.md, not the agent
       body, not the skeleton. Same shape as the `ad_cp2_floor` defect: schema-declared, fully
       consumed, unsuppliable. Documented now on both surfaces.

    What a founder gets: told that a conversion price they supplied contradicts their own recorded
    history, before every ownership percentage is computed from it.
    """

    @staticmethod
    def _build(protection: str, ccp: float, *, history: bool = True) -> dict:
        import cap_state as cap_state_mod  # type: ignore[import-not-found]

        inputs = {
            "company_name": "T",
            "founders": [{"founder_id": "f1", "name": "A", "common_shares": 8_000_000}],
            "preferred_series": [
                {
                    "series_id": "series_seed",
                    "series_name": "Seed",
                    "shares": 2_000_000,
                    "issuance_date": "2024-01-01",
                    "original_issue_price": 1.0,
                    "original_conversion_price": 1.0,
                    "current_conversion_price": ccp,
                    "anti_dilution_protection": protection,
                }
            ],
            "metadata": {"run_id": "t", "schema_version": "v0.5.0-inputs"},
        }
        if history:
            inputs["cap_table_history"] = [
                {"event_type": "anti_dilution_applied", "series_id": "series_seed", "previous_ccp": 1.0, "new_ccp": 0.8}
            ]
        built: dict = cap_state_mod.build_cap_state(inputs, {"safes": [], "convertible_notes": []})
        return built

    @staticmethod
    def _stale(built: dict) -> list[str]:
        return [w for w in (built.get("warnings") or []) if w.startswith("W_STALE_CCP_SUSPECTED")]

    def test_fires_on_an_unprotected_series(self) -> None:
        """THE case the solver-side check structurally could not reach."""
        assert self._stale(self._build("none", 1.0)), (
            "a series with no anti-dilution protection can still carry a stale conversion price from "
            "an earlier round; the old check was gated on protection and missed it entirely"
        )

    def test_fires_on_a_protected_series_too(self) -> None:
        assert self._stale(self._build("broad_based_weighted_average", 1.0))

    def test_silent_when_the_price_was_updated(self) -> None:
        """The ordinary correct state: history says adjusted, and the price reflects it."""
        assert not self._stale(self._build("none", 0.8))

    def test_silent_with_no_history(self) -> None:
        """Most companies. Absence of history is not evidence of a stale price."""
        assert not self._stale(self._build("none", 1.0, history=False))

    def test_warning_reaches_the_founder_as_prose(self) -> None:
        """A warning nothing renders is the defect one layer up — this fleet has shipped that twice."""
        import _warning_callouts  # type: ignore[import-not-found]

        built = self._build("none", 1.0)
        lines = _warning_callouts.render_warning_callouts(built.get("warnings") or [])
        blob = "\n".join(lines)
        assert "out of date" in blob, blob
        assert "series_seed" in blob
        assert "W_STALE_CCP_SUSPECTED" not in blob, "raw code leaked into founder prose"


class TestStaleCcpReachesCounselToo:
    """The founder-facing prose and the counsel item are two deliveries, and only one was wired.

    Moving the check to cap-state build made the warning fire, but `rule_audit`'s gate for
    `anti_dilution.stale_ccp_detected` still read SOLVER warnings off scenarios — the original,
    nearly-unfirable channel. So a founder saw the caveat and their lawyer was told nothing, from a
    rule whose whole purpose is `counsel_review: true`. Half-wiring a fix is harder to notice than
    not wiring it, because the visible half looks like success.
    """

    @staticmethod
    def _inputs(ccp: float) -> dict:
        return {
            "preferred_series": [
                {
                    "series_id": "series_seed",
                    "original_conversion_price": 1.0,
                    "current_conversion_price": ccp,
                }
            ],
            "cap_table_history": [
                {"event_type": "anti_dilution_applied", "series_id": "series_seed", "previous_ccp": 1.0, "new_ccp": 0.8}
            ],
        }

    def test_the_counsel_ITEM_is_produced_not_just_the_gate(self) -> None:
        """Assert the DELIVERABLE, not an intermediate.

        The first version of this class asserted `_runtime_event_predicate` returned True — and
        passed while the counsel packet stayed empty, because items are AND-gated on a separate
        static matcher that still required anti-dilution protection. Testing the gate instead of the
        item is the "computed, not rendered" defect this repo has a coverage map for.
        """
        import json as _json

        import cap_state as cap_state_mod  # type: ignore[import-not-found]
        import rule_audit  # type: ignore[import-not-found]

        rules = _json.loads((CAP_TABLE / "data" / "cap-table-rules.json").read_text(encoding="utf-8"))
        inputs = {
            "company_name": "T",
            "founders": [{"founder_id": "f1", "name": "A", "common_shares": 8_000_000}],
            "preferred_series": [
                {
                    "series_id": "series_seed",
                    "series_name": "Seed",
                    "shares": 2_000_000,
                    "issuance_date": "2024-01-01",
                    "original_issue_price": 1.0,
                    "original_conversion_price": 1.0,
                    "current_conversion_price": 1.0,
                    # UNPROTECTED — the case the whole relocation was for.
                    "anti_dilution_protection": "none",
                }
            ],
            "cap_table_history": [
                {"event_type": "anti_dilution_applied", "series_id": "series_seed", "previous_ccp": 1.0, "new_ccp": 0.8}
            ],
            "metadata": {"run_id": "t", "schema_version": "v0.5.0-inputs"},
        }
        instruments: dict = {"safes": [], "convertible_notes": []}
        state = cap_state_mod.build_cap_state(inputs, instruments)
        gating = rule_audit.build_gating_block(rules, inputs=inputs, instruments=instruments, cap_state=state)
        items = rule_audit.build_counsel_review_items(gating, rules, {"scenarios": []}, inputs)
        assert any(i["rule_id"] == "anti_dilution.stale_ccp_detected" for i in items), (
            "the founder is warned and the counsel packet is empty. Both halves of the AND-gate have "
            f"to ask the same question. Got: {[i['rule_id'] for i in items]}"
        )

    def test_counsel_gate_opens_on_a_stale_price_with_no_solver_warning(self) -> None:
        import rule_audit  # type: ignore[import-not-found]

        gate = rule_audit._runtime_event_predicate(
            "anti_dilution.stale_ccp_detected", {"scenarios": []}, self._inputs(1.0)
        )
        assert gate is True, (
            "the cap state contradicts itself and the counsel rule stayed shut. The founder gets the "
            "warning; their lawyer gets nothing."
        )

    def test_counsel_gate_stays_shut_when_the_price_was_updated(self) -> None:
        import rule_audit  # type: ignore[import-not-found]

        gate = rule_audit._runtime_event_predicate(
            "anti_dilution.stale_ccp_detected", {"scenarios": []}, self._inputs(0.8)
        )
        assert gate is False, "no contradiction, so no counsel obligation"

    def test_one_predicate_not_three(self) -> None:
        """Build, load and solve must answer this question identically.

        Two copies of it already existed and a third was nearly added. Elsewhere in this skill a
        third copy of a different derivation had already gone wrong and contradicted the rule pack
        it audits, so this is a measured hazard rather than a stylistic preference.
        """
        import _artifact_io  # type: ignore[import-not-found]
        import cap_state as cap_state_mod  # type: ignore[import-not-found]
        import priced_round  # type: ignore[import-not-found]

        # Count the DEFINING literal, not a prefix. `"_artifact_io.s"` matched
        # `_artifact_io.stale_ccp_warning` too, so a verbatim second copy of the predicate beside the
        # shared call passed this test -- the exact defect it names.
        assert callable(_artifact_io.stale_ccp_series_ids)
        for mod, call in (
            (cap_state_mod, "_artifact_io.stale_ccp_series_ids"),
            (priced_round, "_artifact_io.series_has_prior_ad_event"),
        ):
            src = Path(mod.__file__).read_text(encoding="utf-8")
            assert call in src, f"{Path(mod.__file__).name} does not call {call}"
            assert '"anti_dilution_applied"' not in src, (
                f"{Path(mod.__file__).name} names the event type itself — that is a second copy of "
                "the predicate, which is how the last three copies of a derivation drifted apart."
            )
        rule_audit_src = (SCRIPTS / "rule_audit.py").read_text(encoding="utf-8")
        assert "_artifact_io.stale_ccp_series_ids" in rule_audit_src, (
            "rule_audit's static matcher must ask the same question as the runtime gate; when it did "
            "not, the counsel item stayed shut for the unprotected series the check was moved for"
        )


class TestPriorAdEventsAreValidated:
    """A field a sub-agent is told to produce, with nothing checking its shape, is a hallucination
    surface. `agents/cap-table.md` now asks for prior anti-dilution events; this is the gate."""

    @staticmethod
    def _v(history: object) -> list[str]:
        import extract_aoa  # type: ignore[import-not-found]

        series = {
            "series_name": "S",
            "original_issue_price": 1.0,
            "original_conversion_price": 1.0,
            "current_conversion_price": 1.0,
        }
        return list(
            extract_aoa.validate_aoa_extraction(
                {
                    "extraction_type": "articles_of_association",
                    "fields": {"preferred_series": [series], "cap_table_history": history},
                }
            )
        )

    def test_accepts_a_well_formed_event(self) -> None:
        assert (
            self._v([{"event_type": "anti_dilution_applied", "series_id": "s1", "previous_ccp": 1.0, "new_ccp": 0.8}])
            == []
        )

    def test_rejects_an_upward_adjustment(self) -> None:
        """Caught at the DOCUMENT, naming the reading, rather than three artifacts downstream."""
        errs = self._v(
            [{"event_type": "anti_dilution_applied", "series_id": "s1", "previous_ccp": 0.8, "new_ccp": 1.0}]
        )
        assert any("only ever lowers" in e for e in errs), errs

    def test_rejects_an_invented_event_type(self) -> None:
        assert any("event_type" in e for e in self._v([{"event_type": "made_up", "series_id": "s1"}]))

    def test_rejects_an_event_with_no_series(self) -> None:
        assert any("series_id" in e for e in self._v([{"event_type": "anti_dilution_applied"}]))


# Measured with the CORRECTED detector below. RATCHET: may only shrink.
#
# The previous baseline was 18 and was measuring the wrong thing: its regex was `\w+\.\w+\.\w+`, so
# 17 of the 18 were NVCA Model COI subsection citations (§4.4.4, §4.4.5) and internal version strings
# -- legal references a lawyer needs, plus a real leak of a different class. A ratchet whose count is
# dominated by correct content cannot be shrunk by fixing anything, which makes it noise.
DOTTED_PATH_BASELINE = 0


def _founder_text_policy() -> Any:
    """The shared policy module, or None when it cannot be imported."""
    import importlib.util

    path = Path(__file__).resolve().parents[1] / "scripts" / "_founder_text.py"
    spec = importlib.util.spec_from_file_location("_founder_text", path)
    if not (spec and spec.loader):
        return None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# Coverage floor. A detector that scans live data and asserts "no offenders" is vacuous when the
# corpus is clean -- which is the GOAL state -- so its silence proves nothing about the matcher. It is
# also vacuous when the SCAN finds nothing, and that failure is invisible: a rotted glob, a renamed
# field, a shrunk registry all read as "clean". Measured 334 non-empty fields today; the floor pins
# that the population is still there. Shrink-only in the opposite direction to a normal ratchet: it
# may be RAISED when the pack grows, never lowered to accommodate a scan that stopped finding things.
_RULE_FIELD_FLOOR = 300


# A determiner collision -- "the the", "implementation's the" -- is what splicing a humanised token
# into a sentence leaves behind. The possessive arm EXCLUDES the common contractions, because "what's
# the exposure" and "that's a reasonable term" are correct English, and a live counsel question in
# `flip_scenario.py` uses one. Without the exclusion this arm reds on prose a lawyer should read; it
# was green only because it scanned a corpus that happened to contain no contraction. Found by the
# specimen set below, not by a reader -- which is the point of having one.
_DETERMINER_COLLISION = re.compile(
    r"\b(?:the|a|an|its|this|any)\s+(?:the|a|an)\b"
    r"|(?<!what)(?<!that)(?<!\bit)(?<!here)(?<!there)(?<!who)(?<!let)'s\s+(?:the|a|an)\b",
    re.I,
)


def _delivered_rule_fields() -> list[tuple[str, str, str]]:
    """(rule_id, field, text) for every rule field that reaches a founder or their lawyer.

    Scope matters and was previously too narrow. `rule_audit.build_counsel_review_items` maps
    `title` -> the counsel item's heading, `summary` -> `counsel_question`, `applies_when` -> a
    rendered "Applies when" line, and `warnings[0]` -> `founder_question`. Checking only two of those
    is why a module.function reference shipped in a rendered title.
    """
    import json as _json

    pack = _json.loads((CAP_TABLE / "data" / "cap-table-rules.json").read_text(encoding="utf-8"))
    out: list[tuple[str, str, str]] = []
    for rules in pack["domains"].values():
        for r in rules:
            for field in ("title", "summary", "applies_when"):
                out.append((r["rule_id"], field, str(r.get(field) or "")))
            for i, w in enumerate(r.get("warnings") or []):
                out.append((r["rule_id"], f"warnings[{i}]", str(w or "")))
    assert len(out) >= _RULE_FIELD_FLOOR, (
        f"only {len(out)} rule prose fields were collected (floor {_RULE_FIELD_FLOOR}). Every detector "
        "reading this helper just went quiet, and a quiet detector reads exactly like a clean one."
    )
    return out


def test_delivered_rule_prose_carries_no_internal_version_string() -> None:
    """Our plugin version is not a legal fact, and it was opening a counsel handoff.

    One counsel-review rule began "v0.5.0 cap-table scope: ..." (its id deliberately not written
    out -- the rule ratchet above is a substring test, and naming it here would satisfy it), and
    `rule_audit` maps `summary` straight to the question a lawyer reads. Hard-fail, not a ratchet:
    this repo already forbids internal version numbers in user-facing text, and there is no
    legitimate case for one here -- an NVCA section number is a citation, ours is an implementation
    detail.
    """
    import re as _re

    bad = [f"{rid}.{field}" for rid, field, v in _delivered_rule_fields() if _re.search(r"\bv\d+\.\d+\.\d+", v)]
    assert bad == [], f"internal version string in text delivered to a founder or counsel: {bad}"


def test_delivered_rule_prose_is_english_not_paths() -> None:
    """Rule prose is delivered verbatim to a founder and their lawyer, and the policy cannot see it.

    `_founder_text` skips any snake_case token preceded by a dot -- deliberately, because cap-table's
    rule ids are dotted and counsel cites them, so a substituter without that lookbehind would rewrite
    a legal citation into prose. The cost is that an internal path is equally invisible, to BOTH the
    scanner and the substituter. This test covers what the shared policy structurally cannot.

    THE REGEX IS THE WHOLE DESIGN. An earlier version matched a bare three-segment word pattern, which
    the NVCA subsection citations this pack is built on (§4.4.4, §4.4.5) -- a count that cannot be
    reduced by fixing anything. Anchoring on letters and underscores, with subscripts allowed, keeps
    the citations out and catches `state.outstanding_warrants[]`, which the old form missed twice over
    (two segments, and `[]` rather than `[*]`).
    """
    import json as _json
    import re as _re

    pack = _json.loads((CAP_TABLE / "data" / "cap-table-rules.json").read_text(encoding="utf-8"))
    rule_ids = {r["rule_id"] for rules in pack["domains"].values() for r in rules}
    # Letters/underscores only, subscripts allowed. Digits are excluded on purpose: every dotted
    # digit run in this pack is a legal citation or a version, and neither is an internal path.
    path_re = _re.compile(r"\b[a-z_]+(?:\[[^\]]*\])?(?:\.[a-z_]+(?:\[[^\]]*\])?)+\b")
    # Two-segment tails that are domains, not paths -- the pack cites gov.il as a primary source.
    tlds = {"il", "com", "org", "gov", "net", "io", "co", "uk", "eu"}

    hard: list[str] = []
    dotted: list[str] = []
    for rid, field, v in _delivered_rule_fields():
        if "[*]" in v or _re.search(r"\[[a-z]\]", v):
            hard.append(f"{rid}.{field}: index subscript")
        if _re.search(r"\.py\b", v):
            hard.append(f"{rid}.{field}: script filename")
        if _re.search(r"\b(\w+) \1\b", v):
            hard.append(f"{rid}.{field}: duplicated word")
        for m in path_re.findall(v):
            if m in rule_ids or m.split(".")[-1] in tlds or m in {"e.g", "i.e"}:
                continue
            dotted.append(f"{rid}.{field} -> {m}")

    assert hard == [], (
        "rule prose delivered to counsel is not English: " + "; ".join(hard[:8]) + ". These classes are "
        "zero-tolerance: an index subscript, a script filename or a duplicated word is a broken "
        "sentence, and every one seen so far came from rewriting prose by regex over token names."
    )
    assert len(dotted) <= DOTTED_PATH_BASELINE, (
        f"{len(dotted)} rule fields carry an internal path (baseline {DOTTED_PATH_BASELINE}): {dotted[:5]}"
    )
    if len(dotted) < DOTTED_PATH_BASELINE:
        pytest.fail(f"internal paths down to {len(dotted)} — lower DOTTED_PATH_BASELINE to lock it in.")


class TestCapImpliedDenominatorRejections:
    """`E_SAFE_CAP_MISSING_DENOMINATOR` — four emit sites, zero executions, zero assertions.

    The mutant corpus recorded this code as a survivor and its rationale said the sites were "all of
    them executed by the suite". Coverage over the full free suite says otherwise: only the constant
    definition runs. Every emit site is dead, so the code survived because the code never ran — a
    weaker and less honest position than "the code runs unwatched", and worth closing rather than
    recording.

    THE STRING IS WRITTEN OUT INLINE, three times, ON PURPOSE. Do NOT lift it into a module constant
    named after itself: that form reproduces the corpus mutant's `find` text byte-for-byte and trips
    `test_mutation_corpus.py::test_no_mutant_payload_lives_in_this_scanned_test_file`, whose remedy
    message then says "keep the registry in mutation_corpus.py" — wrong advice here, and the likely
    response is to weaken that guard. Repetition is the cheaper of the two costs. (Measured twice: the
    refactor trips it, and so did an earlier version of THIS PARAGRAPH, which quoted the offending
    line to warn against it. A differently-named constant is fine.)

    One site is deliberately NOT tested: the post-condition after the fixed point closes. It fires only
    if `total` and the shares derived from it disagree, which is an algebraic identity — the same shape
    as the anti-dilution post-condition above, reachable only by fabricating its precondition.
    """

    @staticmethod
    def _safe(**over: object) -> dict:
        s = {"id": "s1", "purchase_amount": 500_000, "post_money_valuation_cap": 5_000_000}
        s.update(over)  # type: ignore[arg-type]
        return s

    def test_cap_implied_rejects_a_non_positive_pre_financing_base(self) -> None:
        import safe_conversion  # type: ignore[import-not-found]

        r = safe_conversion.convert_safes_cap_implied([self._safe()], pre_financing_fd=0)
        assert r["branch"] == "rejected", r
        assert r["error"] == "E_SAFE_CAP_MISSING_DENOMINATOR", (
            "a zero pre-financing share count produced a priced answer. Every SAFE's ownership is "
            f"measured against that base, so the percentages would be meaningless. {r}"
        )

    def test_priced_round_rejects_a_missing_post_money_denominator(self) -> None:
        import safe_conversion  # type: ignore[import-not-found]

        r = safe_conversion.convert_safe_priced_round(
            form="yc_postmoney_cap",
            purchase_amount=500_000,
            post_money_valuation_cap=5_000_000,
            discount_multiplier=None,
            company_capitalization=0,
            equity_financing_price=1.0,
        )
        assert r["branch"] == "rejected", r
        assert r["error"] == "E_SAFE_CAP_MISSING_DENOMINATOR", r

    def test_priced_round_rejects_a_missing_pre_money_denominator(self) -> None:
        """The pre-money cap branch has its own denominator and its own way of being absent."""
        import safe_conversion  # type: ignore[import-not-found]

        r = safe_conversion.convert_safe_priced_round(
            form="yc_premoney_cap_only",
            purchase_amount=500_000,
            post_money_valuation_cap=None,
            pre_money_valuation_cap=5_000_000,
            discount_multiplier=None,
            company_capitalization=8_000_000,
            pre_money_fd=None,
            equity_financing_price=1.0,
        )
        assert r["branch"] == "rejected", r
        assert r["error"] == "E_SAFE_CAP_MISSING_DENOMINATOR", r


class TestCapImpliedRefusesUnusableInstrumentSets:
    """Two ways a set of SAFEs produced a confident wrong number, both found by mutation review.

    Neither is exotic. The first needs only a copy-pasted id; the second needs caps that happen to
    reserve almost the whole company, which is what a stack of aggressive SAFEs looks like.
    """

    def test_duplicate_ids_are_refused_rather_than_collapsed(self) -> None:
        """Measured before the fix: 2 SAFEs in, 1 out, and the $500k one gone from the denominator.

        The output keyed both `priced` and `per_safe` by id, so the second silently overwrote the
        first and `company_capitalization` came back as 9,142,857 — a number computed from half the
        cap table, returned as a clean `cap_implied_set` with no diagnostic. Nothing upstream prevents
        it: no schema uniqueness, no dedupe in cap_state, and the extraction-lane guard does not cover
        a hand-authored or freeform-mapped instruments.json.
        """
        import safe_conversion  # type: ignore[import-not-found]

        r = safe_conversion.convert_safes_cap_implied(
            [
                {"id": "same", "purchase_amount": 500_000, "post_money_valuation_cap": 5_000_000},
                {"id": "same", "purchase_amount": 1_000_000, "post_money_valuation_cap": 8_000_000},
            ],
            pre_financing_fd=8_000_000,
        )
        assert r["branch"] == "rejected", (
            "two SAFEs sharing an id were priced. One of them is missing from the denominator and "
            f"from the output, and every remaining ownership figure is overstated. {r}"
        )
        assert r["error"] == "E_SAFE_DUPLICATE_INSTRUMENT_ID", r
        assert "same" in r["reason"], "the founder is not told WHICH id is duplicated"

    def test_a_numerically_degenerate_aggregate_is_refused(self) -> None:
        """`aggregate >= 1.0` was blocked; `aggregate == 1 - 1.1e-16` was not.

        It returned company_capitalization 7.2e22 and 3.6e22 shares per SAFE, branch `cap_implied_set`,
        error None. The guard above reads as if it covers this and does not — the gap is one ulp wide
        and everything inside it is arithmetic no founder can use.
        """
        import math

        import safe_conversion  # type: ignore[import-not-found]

        r = safe_conversion.convert_safes_cap_implied(
            [{"id": "s1", "purchase_amount": math.nextafter(1.0, 0.0) * 1e12, "post_money_valuation_cap": 1e12}],
            pre_financing_fd=8_000_000,
        )
        assert r["branch"] == "rejected", f"a degenerate denominator produced ownership figures: {r}"
        assert r["error"] == "E_SAFE_AGGREGATE_CAP_OWNERSHIP_INFEASIBLE", r

    def test_an_overflowing_denominator_does_not_raise_out_of_a_typed_producer(self) -> None:
        """The overflow branch specifically — which needs an aggregate ABOVE the degeneracy floor.

        Measured: an earlier version of this test used `1 - 1.1e-16`, which the `residual` check
        returns on first, so `math.isfinite` was never called and this was a byte-identical twin of
        the test above it with a different `pre_financing_fd`. It asserted the right outcome for the
        wrong reason and left its own named guard unexecuted — the exact "covered and unasserted"
        shape this file exists for, one directory over.

        So the aggregate sits just ABOVE the floor (residual ~1e-9), where the division is still
        attempted and overflows to inf against a huge base. Instrumented to confirm `isfinite` is
        reached; without the guard this raises ZeroDivisionError out of a function whose entire
        contract is typed rejections.
        """
        import safe_conversion  # type: ignore[import-not-found]

        r = safe_conversion.convert_safes_cap_implied(
            [{"id": "s1", "purchase_amount": (1 - 1.0001e-9) * 1e12, "post_money_valuation_cap": 1e12}],
            pre_financing_fd=1e300,
        )
        assert r["branch"] == "rejected" and r["error"] == "E_SAFE_AGGREGATE_CAP_OWNERSHIP_INFEASIBLE", r
        assert "overflowed" in r["reason"], (
            "this test exists for the overflow branch; a reason that does not mention overflow means "
            f"the degeneracy check returned first and the isfinite guard is still unexercised. {r}"
        )

    def test_a_missing_id_is_refused_rather_than_raising(self) -> None:
        """One id-less SAFE raised KeyError; two were reported as duplicates of `None`.

        Both wrong, differently. The subscript `priced[safe["id"]]` crashes a producer whose contract
        is typed rejections — the same objection this module makes about ZeroDivisionError — and
        naming `None` as the duplicated id points the founder at a value appearing nowhere in their
        documents. A missing id and a repeated id need different fixes, so they get different codes.
        """
        import safe_conversion  # type: ignore[import-not-found]

        r = safe_conversion.convert_safes_cap_implied(
            [
                {"id": "a", "purchase_amount": 500_000, "post_money_valuation_cap": 5_000_000},
                {"purchase_amount": 250_000, "post_money_valuation_cap": 5_000_000},
            ],
            pre_financing_fd=8_000_000,
        )
        assert r["branch"] == "rejected", r
        assert r["error"] == "E_SAFE_INSTRUMENT_ID_MISSING", r
        assert "None" not in r["reason"], "the founder is pointed at a `None` id that is not in their documents"

    def test_ordinary_stacked_safes_still_price(self) -> None:
        """NO FALSE POSITIVES — which is NOT the same as non-vacuity, and the label used to say it was.

        Measured against the pre-fix producer (all guards absent) this test PASSES, so it cannot
        detect a guard being removed. What it does prove is the other direction, which is the one that
        would hurt a founder: an ordinary stack of SAFEs is not refused by any of the three checks.
        The guards' own regression coverage is the three tests above plus their corpus entries.
        """
        import safe_conversion  # type: ignore[import-not-found]

        r = safe_conversion.convert_safes_cap_implied(
            [
                {"id": "a", "purchase_amount": 500_000, "post_money_valuation_cap": 5_000_000},
                {"id": "b", "purchase_amount": 250_000, "post_money_valuation_cap": 10_000_000},
            ],
            pre_financing_fd=8_000_000,
        )
        assert r["branch"] == "cap_implied_set", r
        assert r["company_capitalization"] > 8_000_000
        assert set(r["per_safe"]) == {"a", "b"}


class TestNoteRejectsANonPositiveDiscount:
    """A zero or negative discount multiplier must be refused, not multiplied through.

    `discount_price = qualified_financing_price * discount` — at 0 the conversion price is 0 and the
    share count unbounded; negative gives a negative price. The guard exists; nothing reached it from
    the public entry point, which is what let the mutant that deletes it survive.
    """

    def test_zero_discount_is_rejected(self) -> None:
        import note_conversion  # type: ignore[import-not-found]

        r = note_conversion.convert_note(
            {
                "id": "n1",
                "principal": 100_000,
                "discount_multiplier": 0,
                "issuance_date": "2025-01-01",
                "maturity_date": "2027-01-01",
                "annual_interest_rate": 0.0,
                "maturity_default_treatment": "convert_at_cap",
            },
            conversion_event_date="2026-01-01",
            qualified_financing_price=1.25,
            priced_round_new_money=3_000_000,
        )
        assert r["branch"] == "rejected", f"a zero discount multiplier produced a conversion: {r}"
        assert r["error"] == "E_NOTE_INVALID_PRICE_INPUT", r

    def test_an_ordinary_discount_still_converts(self) -> None:
        """Non-vacuity: 0.8 is the common term and must be unaffected."""
        import note_conversion  # type: ignore[import-not-found]

        r = note_conversion.convert_note(
            {
                "id": "n1",
                "principal": 100_000,
                "discount_multiplier": 0.8,
                "issuance_date": "2025-01-01",
                "maturity_date": "2027-01-01",
                "annual_interest_rate": 0.0,
                "maturity_default_treatment": "convert_at_cap",
            },
            conversion_event_date="2026-01-01",
            qualified_financing_price=1.25,
            priced_round_new_money=3_000_000,
        )
        assert r["branch"] != "rejected", r


class TestPricedRoundRefusesCollapsingInstrumentIds:
    """The same id collapse on the PRICED path, which is the more dangerous of the two.

    `_safe_shares_at_price` / `_note_shares_at_price` key `per_safe`/`per_note` by id. The
    denominator is unaffected — `total` accumulates per iteration — so two identical SAFEs produced
    `safe_pct` 16% in the aggregate beside ONE per-instrument row carrying half of it, with
    `completeness: "full"` and zero blockers. A founder reconciling the summary against the detail
    finds an instrument missing and no warning that anything is wrong.

    That is worse than the cap-implied case fixed alongside it, which at least reported
    `structural_only`. Fixing one path and not the other left the more confident of the two lying —
    found by adversarial review, not by the suite.
    """

    @staticmethod
    def _state(fd: int) -> dict:
        import cap_state as cap_state_mod  # type: ignore[import-not-found]

        built: dict = cap_state_mod.build_cap_state(
            {
                "company_name": "X",
                "founders": [{"founder_id": "f1", "name": "F", "common_shares": fd}],
                "metadata": {"run_id": "t", "schema_version": "v0.5.0-inputs"},
            },
            {"safes": [], "convertible_notes": []},
        )
        return built

    @staticmethod
    def _safe(**over: object) -> dict:
        s = {
            "id": "s1",
            "form": "yc_postmoney_cap",
            "purchase_amount": 500_000,
            "post_money_valuation_cap": 5_000_000,
        }
        s.update(over)  # type: ignore[arg-type]
        return s

    def _solve(self, safes: list[dict], notes: list[dict] | None = None) -> dict:
        import priced_round  # type: ignore[import-not-found]

        out: dict = priced_round.solve_priced_round(
            cap_state=self._state(8_000_000),
            safes=safes,
            notes=notes or [],
            pre_money=12_000_000,
            new_money=3_000_000,
            # Supplied unconditionally so the note cases reach the id check rather than stopping at
            # `E_NOTE_NO_CONVERSION_DATE`, which fires earlier and would make the note test pass for
            # the wrong reason.
            conversion_event_date="2026-01-01",
        )
        return out

    def test_duplicate_safe_ids_block_the_round(self) -> None:
        out = self._solve([self._safe(), self._safe()])
        codes = {b["code"] for b in out.get("blockers") or []}
        assert "E_INSTRUMENT_DUPLICATE_ID" in codes, (
            "two SAFEs sharing an id were priced. Both count toward the totals while only one appears "
            f"per-instrument, so the summary and the detail disagree with no warning. {out}"
        )
        assert out["completeness"] != "full", "a round missing an instrument row must not report `full`"

    def test_duplicate_note_ids_block_the_round(self) -> None:
        """Notes collapse identically; the fix would be half-done if it covered SAFEs only."""
        note = {
            "id": "n1",
            "principal": 1_000_000,
            "valuation_cap": 10_000_000,
            "issuance_date": "2025-01-01",
            "maturity_date": "2027-01-01",
            "annual_interest_rate": 0.0,
            "capitalization_denominator": 8_000_000,
            "maturity_default_treatment": "convert_at_cap",
        }
        out = self._solve([], [note, dict(note)])
        codes = {b["code"] for b in out.get("blockers") or []}
        assert "E_INSTRUMENT_DUPLICATE_ID" in codes, out

    def test_a_missing_instrument_id_is_its_own_diagnostic(self) -> None:
        """Not folded in as a duplicate of `None` — the two need different fixes."""
        anon = self._safe()
        del anon["id"]
        out = self._solve([anon])
        codes = {b["code"] for b in out.get("blockers") or []}
        assert "E_INSTRUMENT_ID_MISSING" in codes, out
        assert "E_INSTRUMENT_DUPLICATE_ID" not in codes, (
            "one id-less instrument was reported as a duplicate; the founder is pointed at a repeated "
            "id that does not exist in their documents"
        )

    def test_distinct_ids_still_price_and_report_every_instrument(self) -> None:
        """No false positives, and the property the guard protects: one row per instrument."""
        out = self._solve([self._safe(id="s1"), self._safe(id="s2")])
        assert not (out.get("blockers") or []), out
        assert out["completeness"] == "full"
        assert set(out["per_safe"]) == {"s1", "s2"}, (
            f"two distinct SAFEs must produce two rows; got {list(out['per_safe'])}"
        )


def test_delivered_rule_prose_is_not_code_shorthand() -> None:
    """Rule prose is humanised at render time, and shorthand does not survive that.

    `counsel_packet.py` runs the whole packet through `_founder_text.substitute`, which unsnakes
    tokens. That is CORRECT for domain vocabulary -- a lawyer maps "current conversion price" onto a
    charter clause, and paraphrasing would cost them precision. It is wrong for anything that was
    never a sentence: `anti_dilution_protection=full_ratchet` becomes "anti dilution protection=full
    ratchet", and a token spliced in as a noun leaves a determiner collision behind ("This
    implementation's the broad-based denominator"). Four such strings were shipping to counsel, one
    of them on a counsel_review rule.

    WHAT THIS CANNOT SEE, stated so a green is not read as "the prose is good". The arms are shapes,
    and there are more ways to break a sentence than shapes to enumerate. Measured misses include: a
    quoted enum ("recorded as 'full_ratchet'"), colon shorthand, an enum list after a colon with no
    parentheses, verb elision ("This implementation the footnote's broader variant"), article/noun
    disagreement, a dangling conjunction, a near-duplicate sentence that is not a byte-for-byte repeat,
    and a token used as a verb. Eight measured misses against three arms — this is a regression guard
    for the shapes that have actually shipped, not a grammar checker.
    """
    import re as _re

    det = _DETERMINER_COLLISION
    # `token=token` with NO surrounding spaces, and not inside backticks. Both qualifiers are
    # load-bearing, and each was learned from a false positive:
    #   * spaced operators are formulas ("Price = cap / Company Capitalization"), which are correct
    #     and must survive;
    #   * a backticked identity ("`safe_shares = purchase / (cap / company_capitalization)`") is
    #     written FOR an implementer and reads correctly after unsnaking.
    # What shipped, and what this catches, is the unspaced bare form: `anti_dilution_protection=full_ratchet`.
    assign = _re.compile(r"(?<![`\s])[a-z0-9_]*[a-z0-9]=['\"]?[a-z][a-z0-9_]*")

    ft = _founder_text_policy()
    problems: list[str] = []
    for rid, field, raw in _delivered_rule_fields():
        if not raw:
            continue
        if assign.search(raw):
            problems.append(f"{rid}.{field}: code shorthand (token=value)")
        if ft is not None and det.search(str(ft.substitute(raw))):
            problems.append(f"{rid}.{field}: determiner collision after humanising")
        # Duplicated CLAUSE, not duplicated word. The word-level arm elsewhere missed a repeated
        # sentence introduced by a previous repair pass, which is how this one earned its place.
        clauses = [c.strip().lower().rstrip(",;") for c in raw.split(".") if len(c.strip()) > 25]
        if len(clauses) != len(set(clauses)):
            problems.append(f"{rid}.{field}: duplicated clause")
    assert problems == [], "rule prose delivered to counsel reads as code: " + "; ".join(problems[:8])


class TestCapStateRejectsDuplicateIds:
    """The id-collapse class, guarded once at the artifact instead of once per consumer.

    THE HISTORY IS THE ARGUMENT. Duplicate ids were fixed twice at the point of use -- the
    cap-implied SAFE path, then the priced path -- and SIX more consumers were still collapsing:
    `preferred_series` in the anti-dilution CP1 snapshot, `founder_id` in the post-round breakdown,
    `results_by_id` in the warrant pump, `per_note` on the note-conversion route, rule_audit's gating
    key, and the option-grant subscript. Each fix was scoped to the example a reviewer named. The
    invariant belongs to the ARTIFACT, so it is now stated once where the artifact is assembled.

    Measured before the fix, all with `completeness: "full"` and zero blockers:
      * two preferred series sharing an id -> ~5 percentage points of founder ownership;
      * two notes sharing an id -> 720,000 shares reported where the truth was 1,120,000;
      * two founders sharing an id -> one row showing 8,000,000 shares for a founder holding
        5,000,000, and the whole per-founder section suppressed because it renders only when there
        is more than one key.

    A schema `uniqueItems` was considered and does not work: `_cap_table_schema_validator.py`
    implements only type/enum/items/properties/required, so the keyword would be inert -- and the
    derived-id case below is not expressible in a schema at all, because the collision is created
    during canonicalization, after validation.
    """

    BASE = {"company_name": "X", "metadata": {"run_id": "t", "schema_version": "v0.5.0-inputs"}}
    FOUNDER = [{"founder_id": "f1", "name": "F", "common_shares": 8_000_000}]

    @staticmethod
    def _series(series_id: str | None, name: str, price: float) -> dict:
        s = {
            "series_name": name,
            "shares": 1_000_000,
            "original_issue_price": price,
            "original_conversion_price": price,
            "current_conversion_price": price,
            "anti_dilution_protection": "broad_based_weighted_average",
            "issuance_date": "2024-01-01",
        }
        if series_id:
            s["series_id"] = series_id
        return s

    @staticmethod
    def _note(note_id: str, principal: float) -> dict:
        return {
            "id": note_id,
            "principal": principal,
            "issuance_date": "2025-01-01",
            "maturity_date": "2027-01-01",
            "annual_interest_rate": 0.0,
            "valuation_cap": 10_000_000,
            "capitalization_denominator": 8_000_000,
        }

    @staticmethod
    def _safe(safe_id: str, amount: float) -> dict:
        return {
            "id": safe_id,
            "form": "yc_postmoney_cap",
            "purchase_amount": amount,
            "post_money_valuation_cap": 5_000_000,
            "issuance_date": "2025-01-01",
        }

    @staticmethod
    def _warrant(warrant_id: str) -> dict:
        return {
            "id": warrant_id,
            "warrant_type": "common",
            "shares_underlying": 1_000,
            "exercise_price": 1.0,
            "issuance_date": "2024-01-01",
            "settlement_type": "cash_exercise",
        }

    def _build(self, inputs_extra: dict, instruments: dict) -> dict:
        import cap_state  # type: ignore[import-not-found]

        built: dict = cap_state.build_cap_state(
            {**self.BASE, "founders": self.FOUNDER, **inputs_extra},
            {"safes": [], "convertible_notes": [], **instruments},
        )
        return built

    def _refuses(self, inputs_extra: dict, instruments: dict) -> str:
        import cap_state  # type: ignore[import-not-found]

        with pytest.raises(cap_state.CapStateInvariantError) as exc:
            self._build(inputs_extra, instruments)
        assert "E_DUPLICATE_ID_IN_CAP_TABLE" in str(exc.value), exc.value
        return str(exc.value)

    def test_duplicate_founder_ids_are_refused(self) -> None:
        import cap_state  # type: ignore[import-not-found]

        with pytest.raises(cap_state.CapStateInvariantError) as exc:
            cap_state.build_cap_state(
                {
                    **self.BASE,
                    "founders": [
                        {"founder_id": "f1", "name": "Alice", "common_shares": 5_000_000},
                        {"founder_id": "f1", "name": "Bob", "common_shares": 3_000_000},
                    ],
                },
                {"safes": [], "convertible_notes": []},
            )
        assert "E_DUPLICATE_ID_IN_CAP_TABLE" in str(exc.value)

    def test_duplicate_series_ids_are_refused(self) -> None:
        self._refuses(
            {"preferred_series": [self._series("a", "Series A", 1.0), self._series("a", "Series A2", 2.0)]}, {}
        )

    def test_series_ids_DERIVED_into_a_collision_are_refused(self) -> None:
        """The case nobody can see coming: no duplicate is typed anywhere.

        `series_id` is derived from `series_name.lower().replace(" ", "_")` when the document does
        not state one -- which is what the freeform lane produces. Two series named "Series A" and
        "series a" therefore collide, and the anti-dilution snapshot runs both against one CP1.
        """
        message = self._refuses(
            {"preferred_series": [self._series(None, "Series A", 1.0), self._series(None, "series a", 2.0)]}, {}
        )
        assert "DERIVED" in message, (
            "a collision the founder never typed must say so; otherwise the remedy reads as "
            "'stop repeating an id' about ids they did not write"
        )

    def test_duplicate_note_ids_are_refused(self) -> None:
        self._refuses({}, {"convertible_notes": [self._note("n1", 500_000), self._note("n1", 900_000)]})

    def test_duplicate_safe_ids_are_refused(self) -> None:
        self._refuses({}, {"safes": [self._safe("s1", 500_000), self._safe("s1", 900_000)]})

    def test_duplicate_warrant_ids_are_refused(self) -> None:
        self._refuses({}, {"warrants": [self._warrant("w1"), self._warrant("w1")]})

    def test_duplicate_grant_ids_are_refused(self) -> None:
        self._refuses(
            {},
            {
                "option_grants": [
                    {"id": "g1", "shares": 1_000, "status": "outstanding"},
                    {"id": "g1", "shares": 2_000, "status": "outstanding"},
                ]
            },
        )

    def test_the_check_reads_the_CANONICAL_rows_not_the_raw_input(self) -> None:
        """Behavioural replacement for a grep test that could not fail.

        The version here before greped the source for `("convertible_notes", "note_id"` tuples. That
        passes when the guard is deleted outright (measured: 7 behavioural tests fail, the grep test
        passes) AND when the rows argument is swapped to the raw input — which is precisely the
        vacuous-guard defect its docstring claimed it existed to catch. It was theatre, and the
        commit message credited it with a catch the per-array behavioural tests actually made.

        This asserts the property instead. `preferred_series` ids are DERIVED during canonicalization
        when the document states none, so a check reading the raw input cannot see a derived
        collision. Two series named "Series A" and "series a" carry no duplicate in the input and a
        duplicate in the canonical rows; only a check on the canonical rows refuses them.
        """
        import cap_state  # type: ignore[import-not-found]

        raw = [self._series(None, "Series A", 1.0), self._series(None, "series a", 2.0)]
        assert len({s["series_name"] for s in raw}) == 2, "the raw input carries no duplicate"
        with pytest.raises(cap_state.CapStateInvariantError) as exc:
            self._build({"preferred_series": raw}, {})
        assert "E_DUPLICATE_ID_IN_CAP_TABLE" in str(exc.value), (
            "the collision exists only after canonicalization, so a guard reading the raw input "
            f"would pass here: {exc.value}"
        )

    def test_distinct_ids_across_every_array_still_build(self) -> None:
        """No false positives: a populated, well-formed cap table must be unaffected."""
        built = self._build(
            {
                "founders": [
                    {"founder_id": "f1", "name": "A", "common_shares": 5_000_000},
                    {"founder_id": "f2", "name": "B", "common_shares": 3_000_000},
                ],
                "preferred_series": [self._series("a1", "Series A", 1.0), self._series("a2", "Series B", 2.0)],
            },
            {
                "safes": [self._safe("s1", 500_000), self._safe("s2", 250_000)],
                "convertible_notes": [self._note("n1", 500_000), self._note("n2", 900_000)],
                "warrants": [self._warrant("w1"), self._warrant("w2")],
                "option_grants": [
                    {"id": "g1", "shares": 1_000, "status": "outstanding"},
                    {"id": "g2", "shares": 2_000, "status": "outstanding"},
                ],
            },
        )
        assert built["as_converted_totals"]["fully_diluted_shares"] > 0
        assert len(built["outstanding_notes"]) == 2, "both notes must survive a clean build"

    def test_absent_ids_are_not_treated_as_duplicates_of_each_other(self) -> None:
        """`None` is not an id. Two id-less rows are two missing ids, not one repeated one.

        Reporting them as duplicates of `None` points the founder at a value appearing nowhere in
        their documents -- the required-field checks already name the real defect.
        """
        import cap_state  # type: ignore[import-not-found]

        with pytest.raises(cap_state.CapStateInvariantError) as exc:
            self._build({}, {"option_grants": [{"shares": 1_000}, {"shares": 2_000}]})
        assert "E_DUPLICATE_ID_IN_CAP_TABLE" not in str(exc.value), (
            f"two id-less grants were reported as sharing an id: {exc.value}"
        )


class TestNullMeansUnsuppliedEverywhere:
    """An explicit null and an absent key must mean the same thing, on every nullable field.

    This class exists because the same construction has now produced two separate defects in one
    skill. `.get(key, default)` returns the NULL when the key is present with a null value, so a
    field the schema types nullable — and that the authoring surfaces explicitly tell an extractor to
    write as null — silently skips its default.

    The first instance crashed the solver on the anti-dilution denominator basis. The second is worse
    because it is silent: a convertible note whose maturity treatment was written as null took a
    different CONVERSION BRANCH than the identical note with the key omitted, and the warning that
    exists to tell a founder the treatment was assumed was suppressed on exactly that input. Three
    surfaces write that null, including the Carta importer, so this is a real founder's note.
    """

    @staticmethod
    def _note(**over: object) -> dict:
        n = {
            "id": "n1",
            "principal": 500_000,
            "issuance_date": "2023-01-01",
            "maturity_date": "2024-01-01",
            "annual_interest_rate": 0.05,
            "interest_rate_type": "simple",
            "valuation_cap": 8_000_000,
            "capitalization_denominator": 10_000_000,
        }
        n.update(over)  # type: ignore[arg-type]
        return n

    def test_null_maturity_treatment_takes_the_same_branch_as_an_absent_one(self) -> None:
        import note_conversion  # type: ignore[import-not-found]

        absent = note_conversion.convert_note(self._note(), conversion_event_date="2024-06-01")
        null = note_conversion.convert_note(
            self._note(maturity_default_treatment=None), conversion_event_date="2024-06-01"
        )
        assert null["branch"] == absent["branch"], (
            f"an explicit null took branch {null['branch']!r} where an omitted key takes "
            f"{absent['branch']!r} — the schema permits the null and the lane docs instruct writing it"
        )

    def test_null_maturity_treatment_still_discloses_the_assumption(self) -> None:
        """The disclosure is the whole point: the founder is told we assumed a treatment."""
        import note_conversion  # type: ignore[import-not-found]

        r = note_conversion.convert_note(
            self._note(maturity_default_treatment=None), conversion_event_date="2024-06-01"
        )
        codes = [w.get("code") for w in (r.get("warnings") or [])]
        assert "maturity_default_treatment_defaulted" in codes, (
            "the treatment was assumed and the founder was not told. A present null is precisely the "
            f"case that needs the disclosure, and it was the case that lost it. Got: {codes}"
        )

    def test_a_supplied_treatment_is_still_honoured_and_undisclosed(self) -> None:
        """Guards the over-correction: `or` must not swallow a real value."""
        import note_conversion  # type: ignore[import-not-found]

        r = note_conversion.convert_note(
            self._note(maturity_default_treatment="repay"), conversion_event_date="2024-06-01"
        )
        assert r["branch"] == "maturity_repay"
        assert "maturity_default_treatment_defaulted" not in [w.get("code") for w in (r.get("warnings") or [])], (
            "nothing was assumed, so nothing should be disclosed"
        )


# Specimens for the three rule-prose detectors above. Every BAD entry is a string that ACTUALLY
# SHIPPED to a founder or their lawyer this session -- not a construction, because inventing examples
# from the defects already in hand is how the matchers came to catch only those defects. Every OK
# entry is live prose that must survive, so broadening an arm cannot be done by matching everything.
_PROSE_BAD = {
    "version string": "v0.5.0 cap-table scope: warrants with their own clause are out of scope.",
    "code shorthand": "Default when anti_dilution_protection=broad_based_weighted_average.",
    "quoted shorthand": "has anti_dilution_protection='full_ratchet'. Detected by the reader.",
    "determiner collision": "This implementation's the broad-based denominator A counts common stock.",
    "duplicated clause": (
        "The narrow denominator counts common and preferred only, excluding options and warrants. "
        "The narrow denominator counts common and preferred only, excluding options and warrants."
    ),
    "internal path": "Use when the cap-table state.aoa_findings.dividend_provisions_present is true.",
    "script filename": "Detected by extract_aoa.py during the reading pass.",
}
_PROSE_OK = {
    # Legal citations the pack is built on — these are what a lawyer needs, and an earlier baseline
    # was 94% composed of them, which is how a ratchet came to measure noise.
    "NVCA subsection": "The NVCA Model COI §4.4.4 trigger compares the new issuance price.",
    "backticked identity": ("The load-bearing identity is `safe_ownership_i = purchase_amount_i / post_money_cap_i`."),
    "spaced formula": "Price = cap / Company Capitalization, computed per series.",
    "domain vocabulary": "Compare the current conversion price against the original issue price.",
    "possessive english": "Does the flip require IP migration, and what's the transfer-pricing exposure?",
}


def test_the_prose_matchers_catch_what_shipped_and_spare_what_must_survive() -> None:
    """The positive case for the three rule-prose detectors, which are otherwise unfalsifiable.

    Each asserts "no offenders in the pack". The pack is clean, so each passes with its matcher
    blinded to a regex that matches nothing — measured, all three did. The matchers are therefore
    exercised here against strings that shipped, in both directions.

    The OK set is the half that stops the fix becoming its own defect: every one of these was, at some
    point today, either flagged by an over-broad arm or nearly rewritten by a sweep. A legal citation
    rewritten into prose is worse than the shorthand it replaced.
    """
    import re as _re

    version = _re.compile(r"\bv\d+\.\d+\.\d+")
    assign = _re.compile(r"(?<![`\s])[a-z0-9_]*[a-z0-9]=['\"]?[a-z][a-z0-9_]*")
    det = _DETERMINER_COLLISION
    path = _re.compile(r"\b[a-z_]+(?:\[[^\]]*\])?(?:\.[a-z_]+(?:\[[^\]]*\])?)+\b")
    pyfile = _re.compile(r"\.py\b")

    def _clauses_repeat(s: str) -> bool:
        c = [x.strip().lower().rstrip(",;") for x in s.split(".") if len(x.strip()) > 25]
        return len(c) != len(set(c))

    def _flagged(s: str) -> bool:
        if version.search(s) or assign.search(s) or det.search(s) or pyfile.search(s):
            return True
        if _clauses_repeat(s):
            return True
        # A dotted rule id is a legitimate citation counsel uses; an internal path is not. The real
        # detector distinguishes them by pack membership, so this does too.
        rule_ids = set(_rule_pack())
        return any(m not in rule_ids and m.split(".")[-1] not in {"il", "com", "org"} for m in path.findall(s))

    for label, s in _PROSE_BAD.items():
        assert _flagged(s), f"a matcher stopped catching {label!r}, which shipped: {s[:70]}"

    # The OK set is checked against every arm EXCEPT the path arm, which legitimately fires on
    # dotted rule ids and is scoped by the pack membership check in the real detector.
    for label, s in _PROSE_OK.items():
        tripped = [
            n
            for n, hit in (
                ("version", version.search(s)),
                ("shorthand", assign.search(s)),
                ("determiner", det.search(s)),
                ("filename", pyfile.search(s)),
                ("duplicate", _clauses_repeat(s)),
            )
            if hit
        ]
        assert tripped == [], f"{label!r} is correct prose and would be flagged by {tripped}: {s[:70]}"


class TestAoaMergeRefusesWithinPayloadDuplicates:
    """A collapse UPSTREAM of the artifact guard, which the artifact guard structurally cannot see.

    `merge_into_inputs` snapshots `existing_index` from the pre-loop series list and then MUTATES
    that same index as it appends. So two entries in one AoA payload sharing a `series_name` take the
    "already present" branch on the second iteration and overwrite the first — even with
    `replace_existing=False`, which this function documents as an atomic no-write.

    Measured: a payload of "Series A" 1,000,000 and "Series A" 2,000,000 persisted ONE row of
    2,000,000 and reported `added_count: 1, replaced_count: 1` against a file with no preferred
    series at all. Founder ownership then rendered 80.0% where the truth was 72.7%.

    `cap_state`'s uniqueness guard could not catch it: by the time the artifact is built there
    genuinely IS only one series. A guard downstream of a collapse cannot detect the collapse — which
    is the lesson this class exists to record, not just the bug.

    Note the two checks catch DIFFERENT things and neither subsumes the other. `cap_state` derives
    ids case-insensitively, so it catches "Series A" vs "series a"; this one is an exact-name match,
    so it catches the identical repeat — the likelier extraction artifact of the two.
    """

    @staticmethod
    def _series(name: str, shares: int) -> dict:
        return {
            "series_name": name,
            "shares": shares,
            "original_issue_price": 1.0,
            "original_conversion_price": 1.0,
            "current_conversion_price": 1.0,
            "anti_dilution_protection": "broad_based_weighted_average",
        }

    @staticmethod
    def _inputs(tmp_path: Path) -> Path:
        p = tmp_path / "inputs.json"
        p.write_text(
            json.dumps(
                {
                    "company_name": "X",
                    "founders": [{"founder_id": "f1", "name": "F", "common_shares": 8_000_000}],
                    "metadata": {"run_id": "t", "schema_version": "v0.5.0-inputs"},
                }
            ),
            encoding="utf-8",
        )
        return p

    def test_a_repeated_series_name_in_one_payload_writes_nothing(self, tmp_path: Path) -> None:
        import extract_aoa  # type: ignore[import-not-found]

        path = self._inputs(tmp_path)
        receipt = extract_aoa.merge_into_inputs(
            str(path), [self._series("Series A", 1_000_000), self._series("Series A", 2_000_000)], source_doc="a.pdf"
        )
        assert receipt["status"] == "conflict", (
            f"a payload with two 'Series A' rows was merged. One series' shares are gone from the cap "
            f"table while the totals move, and nothing downstream can tell. {receipt}"
        )
        assert "Series A" in (receipt.get("conflicts") or []), receipt
        merged = json.loads(path.read_text(encoding="utf-8"))
        assert not merged.get("preferred_series"), (
            "the refusal must be atomic — this function documents a no-flag conflict as writing "
            f"nothing: {merged.get('preferred_series')}"
        )

    def test_distinct_series_names_still_merge_with_every_share_kept(self, tmp_path: Path) -> None:
        """Non-vacuity, and it pins the number the collapse got wrong."""
        import extract_aoa  # type: ignore[import-not-found]

        path = self._inputs(tmp_path)
        receipt = extract_aoa.merge_into_inputs(
            str(path), [self._series("Series A", 1_000_000), self._series("Series B", 2_000_000)], source_doc="a.pdf"
        )
        assert receipt["status"] == "merged", receipt
        merged = json.loads(path.read_text(encoding="utf-8"))
        assert len(merged["preferred_series"]) == 2
        assert sum(s["shares"] for s in merged["preferred_series"]) == 3_000_000, (
            "both series' shares must survive the merge; the collapse reported 2,000,000 of 3,000,000"
        )


class TestBlankIdsAreNotIds:
    """A blank id is PRESENT but is not an id — the gap a founder-facing wrong number lived in.

    Three checks disagreed about the same value. `cap_state`'s required-field tests asked
    `"id" not in row`, so `""` PASSED them. `_check_unique_ids` skipped blanks. Only
    `safe_conversion` and `priced_round` treated `in (None, "")` as missing, which was the correct
    call. The gap between them is exactly the width of the empty string, and two convertible notes
    with `id: ""` fell into it: **720,000 shares reported against a true 1,120,000**, one row for
    two notes, `completeness: "full"`, zero blockers.

    `_artifact_io.id_missing` is now the single definition and every site imports it. These tests
    pin the two layers SEPARATELY and deliberately: the second exists precisely for callers that
    bypass the first, which is not hypothetical — the scenario math routes read raw
    `instruments.json` and never the canonical arrays, so the artifact check does not cover them.
    """

    NOTE = {
        "principal": 500_000,
        "issuance_date": "2025-01-01",
        "maturity_date": "2027-01-01",
        "annual_interest_rate": 0.0,
        "valuation_cap": 10_000_000,
        "capitalization_denominator": 8_000_000,
        "maturity_default_treatment": "convert_at_cap",
    }
    INPUTS = {
        "company_name": "X",
        "founders": [{"founder_id": "f1", "name": "F", "common_shares": 8_000_000}],
        "metadata": {"run_id": "t", "schema_version": "v0.5.0-inputs"},
    }

    @classmethod
    def _note(cls, note_id: object, principal: float) -> dict:
        n = dict(cls.NOTE)
        n["principal"] = principal
        if note_id is not None:
            n["id"] = note_id
        return n

    # -- layer 1: the canonical artifact ------------------------------------------------------

    def test_blank_note_id_is_refused_at_canonicalization(self) -> None:
        import cap_state  # type: ignore[import-not-found]

        with pytest.raises(cap_state.CapStateInvariantError) as exc:
            cap_state.build_cap_state(
                self.INPUTS,
                {"safes": [], "convertible_notes": [self._note("", 500_000), self._note("", 900_000)]},
            )
        assert "MISSING_FIELD" in str(exc.value), (
            f"a blank id must read as a MISSING id, not as a present one: {exc.value}"
        )

    def test_blank_founder_id_is_refused_even_though_no_builder_rejects_it(self) -> None:
        """`founder_id` mints only on an ABSENT key, so a blank one reaches the uniqueness check.

        This is why `_check_unique_ids` must RAISE on blank rather than skip: founders and
        preferred series are the two arrays that get here without passing an id-rejecting builder.
        """
        import cap_state  # type: ignore[import-not-found]

        with pytest.raises(cap_state.CapStateInvariantError) as exc:
            cap_state.build_cap_state(
                {
                    **self.INPUTS,
                    "founders": [
                        {"founder_id": "", "name": "Alice", "common_shares": 5_000_000},
                        {"founder_id": "", "name": "Bob", "common_shares": 3_000_000},
                    ],
                },
                {"safes": [], "convertible_notes": []},
            )
        assert "E_BLANK_ID_IN_CAP_TABLE" in str(exc.value), exc.value

    def test_blank_derived_series_id_is_refused(self) -> None:
        """Site 6: `series_id` is DERIVED from `series_name`, so an empty name derives a blank id.

        Two such series then shared one CP1 snapshot in the anti-dilution math — a founder-ownership
        error with `completeness: "full"`. No duplicate is typed by anyone to reach it.
        """
        import cap_state  # type: ignore[import-not-found]

        series = {
            "series_name": "",
            "shares": 1_000_000,
            "original_issue_price": 1.0,
            "original_conversion_price": 1.0,
            "current_conversion_price": 1.0,
            "anti_dilution_protection": "broad_based_weighted_average",
            "issuance_date": "2024-01-01",
        }
        with pytest.raises(cap_state.CapStateInvariantError) as exc:
            cap_state.build_cap_state(
                {**self.INPUTS, "preferred_series": [dict(series), dict(series)]},
                {"safes": [], "convertible_notes": []},
            )
        assert "E_BLANK_ID_IN_CAP_TABLE" in str(exc.value), exc.value

    # -- layer 2: the raw-instrument consumer, which layer 1 does not cover -------------------

    @staticmethod
    def _clean_cap_state() -> dict:
        import cap_state  # type: ignore[import-not-found]

        built: dict = cap_state.build_cap_state(
            TestBlankIdsAreNotIds.INPUTS,
            {"safes": [], "convertible_notes": [TestBlankIdsAreNotIds._note("n1", 500_000)]},
        )
        return built

    @staticmethod
    def _run(notes: list[dict]) -> dict:
        import run_scenario  # type: ignore[import-not-found]

        out: dict = run_scenario.run_note_conversion_scenario(
            {
                "scenario_id": "s",
                "label": "s",
                "type": "note_conversion",
                "parameters": {
                    "transaction_event_date": "2026-01-01",
                    "qualified_financing_price": 1.25,
                    "priced_round_new_money": 3_000_000,
                },
            },
            instruments={"safes": [], "convertible_notes": notes},
            cap_state=TestBlankIdsAreNotIds._clean_cap_state(),
        )
        return out

    def test_the_note_route_refuses_blank_ids_against_a_CLEAN_artifact(self) -> None:
        """The measured bypass: a clean cap_state plus dirty raw instruments.

        This is the case the artifact-level check structurally cannot see, and it is the one that
        produced the 720,000. If this ever passes again, the point-of-use guard is gone.
        """
        out = self._run([self._note("", 500_000), self._note("", 900_000)])
        codes = {b["code"] for b in out.get("blockers") or []}
        assert "E_INSTRUMENT_ID_MISSING" in codes, f"blank note ids reached the math against a clean artifact: {out}"
        assert out["completeness"] != "full"
        assert not out.get("per_note")

    def test_the_note_route_refuses_duplicate_ids_against_a_CLEAN_artifact(self) -> None:
        out = self._run([self._note("d", 500_000), self._note("d", 900_000)])
        codes = {b["code"] for b in out.get("blockers") or []}
        assert "E_INSTRUMENT_DUPLICATE_ID" in codes, out

    def test_a_note_with_no_id_key_is_refused_rather_than_raising(self) -> None:
        """`n["id"]` in the filter was a bare KeyError — an untyped crash from a typed route."""
        out = self._run([self._note(None, 500_000)])
        codes = {b["code"] for b in out.get("blockers") or []}
        assert "E_INSTRUMENT_ID_MISSING" in codes, out

    def test_distinct_note_ids_still_convert_and_the_total_is_right(self) -> None:
        """Non-vacuity, pinning the number the collapse got wrong: 1,120,000, not 720,000."""
        out = self._run([self._note("n1", 500_000), self._note("n2", 900_000)])
        assert not (out.get("blockers") or []), out
        assert out["completeness"] == "full"
        per_note = out["per_note"]
        assert len(per_note) == 2, f"both notes must be reported separately: {list(per_note)}"
        total = sum((v or {}).get("conversion_shares") or 0 for v in per_note.values())
        assert round(total) == 1_120_000, f"expected 1,120,000 shares, got {total:,.0f}"


class TestScenarioIdsMustBeUniqueAndPresent:
    """A scenario id collapse costs a founder-visible ROW, not a number — which is why it survived.

    Measured before the guard: two priced-round scenarios sharing a `scenario_id` both compute and
    both come back, so the math looks untouched and no count anywhere reads wrong. The loss is in
    `rule_audit`'s gating map, keyed `f"scenario:{scenario_id or 'global'}"` — two scenarios, one
    gating entry, one `date_sensitive_watchlist` row instead of two. That row is rendered into
    `report.md`, so a financing date's sensitivity status (inside or outside a legal window)
    vanishes silently. Two blank ids collapse the same way, onto `scenario:global`.

    Found by measuring a site nobody had checked, not by a test failing. Unlike instrument ids a
    `scenario_id` is authored by the caller rather than read out of a document, so this raises
    rather than returning blockers: it is a programming error in the request, not a defect in the
    founder's paperwork.
    """

    INPUTS = {
        "company_name": "X",
        "founders": [{"founder_id": "f1", "name": "F", "common_shares": 8_000_000}],
        "metadata": {"run_id": "t", "schema_version": "v0.5.0-inputs"},
    }

    @staticmethod
    def _scenario(scenario_id: str, pre_money: int) -> dict:
        return {
            "scenario_id": scenario_id,
            "label": f"pre {pre_money}",
            "type": "priced_round",
            "parameters": {"pre_money": pre_money, "new_money": 3_000_000},
        }

    def _run(self, ids: list[str]) -> list[dict]:
        import cap_state  # type: ignore[import-not-found]
        import run_scenario  # type: ignore[import-not-found]

        state = cap_state.build_cap_state(self.INPUTS, {"safes": [], "convertible_notes": []})
        out: list[dict] = run_scenario.run_all_scenarios(
            inputs=self.INPUTS,
            instruments={"safes": [], "convertible_notes": []},
            cap_state=state,
            scenario_requests=[self._scenario(ids[0], 12_000_000), self._scenario(ids[1], 20_000_000)],
        )
        return out

    def test_duplicate_scenario_ids_are_refused(self) -> None:
        with pytest.raises(ValueError, match="E_SCENARIO_ID_DUPLICATE"):
            self._run(["s1", "s1"])

    def test_blank_scenario_ids_are_refused(self) -> None:
        """Both blank ids land on the same `scenario:global` gating key — same collapse, no repeat typed."""
        with pytest.raises(ValueError, match="E_SCENARIO_ID_MISSING"):
            self._run(["", ""])

    def test_distinct_scenario_ids_still_run(self) -> None:
        """Non-vacuity: two ordinary scenarios must both compute and keep their own parameters."""
        out = self._run(["s1", "s2"])
        assert [s.get("scenario_id") for s in out] == ["s1", "s2"]
        assert [s["parameters"]["pre_money"] for s in out] == [12_000_000, 20_000_000]
