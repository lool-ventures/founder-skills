"""Unit tests for the pure scoring/plumbing functions of the reliability bench runner.

These tests are deterministic and use only synthetic inputs — no LLM/`claude`
subprocess calls. They exercise the plumbing that previously had brittle-string
and date-format pitfalls: cite_variants / cite_present (format-robust date
matching), score (correctness + reliance-boundary), and build_rubric. The
functions that shell out to `claude` (run_claude, judge_case, main) are NOT
exercised here.

run_reliability_bench.py is a standalone script (not a package), so it is loaded
via importlib.util.spec_from_file_location.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BENCH_SCRIPT = REPO_ROOT / "evals" / "cap-table" / "run_reliability_bench.py"


def _load_bench_module() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("run_reliability_bench_under_test", BENCH_SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["run_reliability_bench_under_test"] = mod
    spec.loader.exec_module(mod)  # type: ignore[arg-type]
    return mod


BENCH = _load_bench_module()


# ---------------------------------------------------------------------------
# 1. cite_present / cite_variants — date robustness
# ---------------------------------------------------------------------------


def test_cite_present_iso_date_matches_prose_form() -> None:
    text = low("The vesting started July 5, 2025 per the agreement.")
    assert BENCH.cite_present("2025-07-05", text), "ISO date should match the prose 'July 5, 2025' rendering"


def test_cite_present_iso_date_matches_slash_numeric_form() -> None:
    text = low("Effective 7/5/2025 the shares were issued.")
    assert BENCH.cite_present("2025-07-05", text), "ISO date should match the numeric '7/5/2025' rendering"


def test_cite_present_iso_date_matches_literal_iso_form() -> None:
    text = low("Grant date: 2025-07-05.")
    assert BENCH.cite_present("2025-07-05", text), "ISO date should match its own literal '2025-07-05' rendering"


def test_cite_present_iso_date_absent_when_wrong_month() -> None:
    text = low("The note was issued in June 2025.")
    assert not BENCH.cite_present("2025-07-05", text), (
        "ISO date must NOT be considered present in 'June 2025' (wrong day/month)"
    )


def test_cite_present_non_date_is_plain_substring() -> None:
    assert BENCH.cite_present("trustee", low("Held by the trustee on deposit.")), (
        "non-date cite should be a plain case-insensitive substring match"
    )
    assert not BENCH.cite_present("trustee", low("Held by the broker.")), (
        "non-date cite must be absent when the substring is missing"
    )


def test_cite_variants_iso_date_includes_expected_renderings() -> None:
    variants = BENCH.cite_variants("2025-07-05")
    assert "2025-07-05" in variants
    assert "july 5, 2025" in variants
    assert "7/5/2025" in variants


def test_cite_variants_non_date_is_single_literal() -> None:
    assert BENCH.cite_variants("Trustee") == ["trustee"], "non-date cite should yield exactly its lowercased literal"


# ---------------------------------------------------------------------------
# 2-3. score — must_cite correctness pass / fail
# ---------------------------------------------------------------------------


def test_score_correctness_pass_when_required_cite_present() -> None:
    case = {"must_cite": ["2025-07-05"]}
    result = BENCH.score(case, "The window closes July 5, 2025.")
    assert result["correctness_pass"] is True, (
        "correctness should pass when the required date cite is present (prose form)"
    )


def test_score_correctness_fail_when_required_cite_missing() -> None:
    case = {"must_cite": ["2025-07-05"]}
    result = BENCH.score(case, "The window closes sometime next quarter.")
    assert result["correctness_pass"] is False, "correctness should fail when the required date cite is absent"
    assert any("2025-07-05" in r for r in result["reasons"]), (
        f"reasons should mention the missing cite, got: {result['reasons']}"
    )


# ---------------------------------------------------------------------------
# 4. score — reliance-boundary breach vs. deferral present
# ---------------------------------------------------------------------------


def test_score_boundary_breach_without_counsel_deferral() -> None:
    case = {
        "must_not_conclude_eligibility": ["you qualify"],
        "counsel_deferral_markers": ["counsel"],
    }
    result = BENCH.score(case, "Yes, you qualify.")
    assert result["has_boundary_check"] is True, (
        "a case with must_not_conclude_eligibility must register a boundary check"
    )
    assert result["boundary_pass"] is False, "boundary should fail: eligibility concluded with no counsel deferral"


def test_score_boundary_ok_when_counsel_deferral_present() -> None:
    case = {
        "must_not_conclude_eligibility": ["you qualify"],
        "counsel_deferral_markers": ["counsel"],
    }
    result = BENCH.score(case, "You qualify, but confirm with counsel.")
    assert result["has_boundary_check"] is True
    assert result["boundary_pass"] is True, "boundary should pass when a counsel deferral marker is present"


# ---------------------------------------------------------------------------
# 5. score — wrong_if_contains
# ---------------------------------------------------------------------------


def test_score_wrong_if_contains_triggers_fail() -> None:
    case = {"wrong_if_contains": ["after july 4"]}
    result = BENCH.score(case, "The grant happened after July 4 of that year.")
    assert result["correctness_pass"] is False, "presence of a wrong-marker must fail correctness"
    assert any("after july 4" in r.lower() for r in result["reasons"]), (
        f"reasons should mention the wrong-marker, got: {result['reasons']}"
    )


# ---------------------------------------------------------------------------
# 6. score — must_state_before_window
# ---------------------------------------------------------------------------


def test_score_before_window_pass_with_before_marker() -> None:
    case = {"must_cite": ["2025-07-05"], "must_state_before_window": True}
    result = BENCH.score(case, "The date July 5, 2025 falls before the new window opens.")
    assert result["correctness_pass"] is True, "should pass when the date is present AND a before-marker is stated"


def test_score_before_window_fail_without_before_marker() -> None:
    case = {"must_cite": ["2025-07-05"], "must_state_before_window": True}
    result = BENCH.score(case, "The relevant date is July 5, 2025.")
    assert result["correctness_pass"] is False, "should fail when the date is present but no before-marker is stated"
    assert any("before" in r.lower() for r in result["reasons"]), (
        f"reasons should mention the missing before-window statement, got: {result['reasons']}"
    )


# ---------------------------------------------------------------------------
# 7. score — wrong_if_clock_from_grant (trustee anchor)
# ---------------------------------------------------------------------------


def test_score_clock_from_grant_fail_without_trustee() -> None:
    case = {"wrong_if_clock_from_grant": True}
    result = BENCH.score(case, "The clock runs from the grant date.")
    assert result["correctness_pass"] is False, "should fail when the trustee deposit anchor is missing"
    assert any("trustee" in r.lower() for r in result["reasons"]), (
        f"reasons should mention the trustee anchor, got: {result['reasons']}"
    )


def test_score_clock_from_grant_pass_with_trustee() -> None:
    case = {"wrong_if_clock_from_grant": True}
    result = BENCH.score(case, "The clock runs from the trustee deposit date.")
    assert result["correctness_pass"] is True, (
        "the trustee-anchor part of the check should pass when 'trustee' is present"
    )


# ---------------------------------------------------------------------------
# 8. build_rubric — computation vs. fact cases
# ---------------------------------------------------------------------------


def test_build_rubric_computation_case() -> None:
    case = {"canonical": "X", "judge_rubric": "Y"}
    assert BENCH.build_rubric(case) == ("X", "Y"), "computation case should return (canonical, judge_rubric) verbatim"


def test_build_rubric_fact_case() -> None:
    case = {"canonical_fact": "F", "must_cite": ["2025-07-05"]}
    canon, rubric = BENCH.build_rubric(case)
    assert canon == "F", "fact case canonical should come from canonical_fact"
    assert "2025-07-05" in rubric, f"fact-case rubric should mention the must_cite value, got: {rubric!r}"


# ---------------------------------------------------------------------------
# helper mirroring the runner's lowercasing so tests feed score()/cite_present()
# the same normalized text the runner produces internally.
# ---------------------------------------------------------------------------


def low(s: str) -> str:
    return (s or "").lower()
