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
UNASSERTED_CODE_BASELINE = 29


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
    suite = "\n".join(p.read_text(encoding="utf-8") for p in Path(__file__).resolve().parent.glob("test_*.py"))
    rules = _rule_pack()
    unasserted = sorted(r for r in rules if r not in suite)
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
UNASSERTED_RULE_BASELINE = 55
UNASSERTED_COUNSEL_RULE_BASELINE = 22  # same correction as above


def test_rule_assertion_ratchet() -> None:
    """How many rule_ids can be deleted from the pack without failing a test?

    Coverage says a predicate executed. This says whether anyone would notice if the rule it gates
    stopped firing -- which for a counsel-review item is the difference between a founder being told
    to consult counsel and not being told.
    """
    unasserted, counsel = _unasserted_rules()
    assert len(unasserted) <= UNASSERTED_RULE_BASELINE, (
        f"{len(unasserted)} rule_ids have no assertion (baseline {UNASSERTED_RULE_BASELINE}); "
        f"a new unguarded rule shipped: {sorted(set(unasserted))[:8]}"
    )
    assert len(counsel) <= UNASSERTED_COUNSEL_RULE_BASELINE, (
        f"{len(counsel)} COUNSEL-REVIEW rules have no assertion (baseline "
        f"{UNASSERTED_COUNSEL_RULE_BASELINE}): {counsel[:8]}"
    )
    if len(unasserted) < UNASSERTED_RULE_BASELINE or len(counsel) < UNASSERTED_COUNSEL_RULE_BASELINE:
        pytest.fail(
            f"unasserted rules down to {len(unasserted)} (baseline {UNASSERTED_RULE_BASELINE}) and "
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
