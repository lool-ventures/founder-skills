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
UNASSERTED_CODE_BASELINE = 30


def test_error_code_assertion_ratchet() -> None:
    """How many founder-visible diagnostics can be deleted without failing a test?

    Coverage answers "did the line run". This answers "would anyone notice if it stopped working" --
    the question that matters for a diagnostic, whose entire purpose is to fire. A code with zero
    assertions is a guard that can be removed, renamed or mis-fired silently.
    """
    suite = "\n".join(p.read_text(encoding="utf-8") for p in Path(__file__).resolve().parent.glob("test_*.py"))
    unasserted = sorted(
        code
        for codes in _all_error_codes().values()
        for code in codes
        if f'"{code}"' not in suite and f"'{code}'" not in suite
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
# them: of the rule pack's 85 rule_ids, 56 are named in no test anywhere, and 23 of those carry
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
UNASSERTED_RULE_BASELINE = 55
UNASSERTED_COUNSEL_RULE_BASELINE = 22


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
    def _artifacts(ccp_before: float, ccp_after: float) -> dict:
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
                                "floor_applied": False,
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

    def _render(self, ccp_before: float, ccp_after: float) -> str:
        import compose_report  # type: ignore[import-not-found]

        md: str = compose_report.render_report_markdown(
            artifacts=self._artifacts(ccp_before, ccp_after),
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
