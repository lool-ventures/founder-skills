"""The IC simulation's verdict and score wording, in one place.

report.md (`compose_report.py`) and the report page (`visualize.py`) both state the committee's verdict,
its conviction score, a thin-basis note, each partner's verdict and the fund's check size. Each of those is
worded here and nowhere else, so the two deliverables cannot drift apart. The fund's kind and provenance
lines are not here: `fund_profile.founder_lines` owns them.

Standard library only, no CLI, no output. It reads the `summary` block `score_dimensions.py` writes and
decides no score or verdict: it only words what that script decided.
"""

from __future__ import annotations

from typing import Any

# VC "pass" / "hard_pass" mean DECLINE, but a bare "Pass" reads to a founder as "passes the bar". Never
# render the internal value alone; always lead with an unambiguous decision word.
VERDICT_WORD: dict[str, str] = {
    "invest": "Invest",
    "more_diligence": "More Diligence",
    "pass": "Decline",
    "hard_pass": "Decline — Hard Pass",
}

_VERDICT_SENTENCE: dict[str, str] = {
    "invest": "Invest — strong enough for a term sheet discussion",
    "more_diligence": "More Diligence — promising but needs more evidence",
    "pass": "Decline — too many concerns to proceed at this time",
    "hard_pass": "Decline — Hard Pass: fatal flaw identified",
}

# When the verdict was HELD by coverage rather than earned on the merits, the default wording is wrong in
# opposite directions: "promising but needs more evidence" flatters a floored verdict (nothing was assessed,
# so nothing is promising) and undersells a capped one (the conviction was in the invest band).
_HELD = "More Diligence — too little disclosed to reach a verdict (this is NOT a negative signal)"
_CAPPED = "More Diligence — the confirmed dimensions score well, but too much is undisclosed to underwrite"


def _norm(verdict: Any) -> str:
    return str(verdict or "").strip().lower()


def _held(summary: dict[str, Any]) -> bool:
    """`coverage_floored` and `coverage_held` share one wording: too little was disclosed to score at all."""
    return summary.get("coverage_floored") is True or summary.get("coverage_held") is True


def score_text(summary: dict[str, Any]) -> str:
    """The conviction score as report.md and the page print it, without the percent sign: one decimal at most
    and no trailing zero ("63", "63.7"), the fleet's format (a test holds it equal to `_ui.score_text`, which
    this module does not import). A value that is not a number comes back as written."""
    value = summary.get("conviction_score", 0)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return f"{value}"
    return f"{round(float(value), 1):g}"


def verdict_line(summary: dict[str, Any]) -> str:
    """The committee's verdict as a sentence, coverage-aware. An unknown verdict comes back as written; the
    whole-document founder-text pass (report.md) and the page's own pass put it into words."""
    raw = summary.get("verdict", "unknown")
    verdict = _norm(raw)
    line = _VERDICT_SENTENCE.get(verdict, raw)
    if verdict == "more_diligence":
        if _held(summary):
            line = _HELD
        elif summary.get("coverage_capped") is True:
            line = _CAPPED
    return str(line)


def thin_basis_note(summary: dict[str, Any]) -> str | None:
    """The denominator the score must never appear without when the base is thin, or None. "50.0%" off two
    applicable dimensions reads as a considered midpoint across the whole framework."""
    basis = summary.get("conviction_basis")
    basis = basis if isinstance(basis, dict) else {}
    if basis.get("sufficient") is False and basis.get("applicable"):
        return (
            f"Scored on {basis.get('applicable')} of {basis.get('total')} dimensions — "
            "too thin a base for the percentage to be meaningful. Read the breakdown below, "
            "not the headline number."
        )
    return None


def verdict_word(verdict: Any) -> str:
    """A partner's (or the committee's) verdict as its decision word. An unknown verdict comes back as
    written, for the founder-text pass to put into words."""
    word = VERDICT_WORD.get(_norm(verdict))
    if word is not None:
        return word
    return str(verdict) if verdict else "?"


def ring_tone(summary: dict[str, Any]) -> str:
    """The score ring's tone: invest is a pass; a held or floored More Diligence is neutral (it is not a
    negative signal); a capped or merits-based one is a warning; a decline is a fail; anything else neutral."""
    verdict = _norm(summary.get("verdict"))
    if verdict == "invest":
        return "pass"
    if verdict == "more_diligence":
        return "neutral" if _held(summary) else "warn"
    if verdict in ("pass", "hard_pass"):
        return "fail"
    return "neutral"


def _fmt_number(val: Any, fallback: str = "?") -> str:
    if val is None:
        return fallback
    try:
        return f"{val:,}"
    except (TypeError, ValueError):
        return str(val)


def check_size_text(fund: dict[str, Any]) -> str | None:
    """The fund's check size as "USD 500,000 - 5,000,000", or None when the profile states none."""
    check_size = fund.get("check_size_range", {})
    if not isinstance(check_size, dict) or not check_size:
        return None
    currency = check_size.get("currency", "USD")
    return f"{currency} {_fmt_number(check_size.get('min'))} - {_fmt_number(check_size.get('max'))}"
