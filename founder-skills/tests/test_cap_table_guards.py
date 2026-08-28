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
UNASSERTED_CODE_BASELINE = 31


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
