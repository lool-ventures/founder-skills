"""End-to-end smoke: drive market-sizing through a dual-methodology run.

**Why this lane exists.** `market-sizing` grew a top-level `comparison_blocked` field on
its coaching payload. The argument for it is that `COMPARISON_CURRENCY_UNKNOWN` is a
*medium* warning, so it never reaches `high_severity_warnings` — meaning the coaching
sub-agent was handed the founder's stated figures and told the deck had been reviewed,
with nothing saying a cross-check had been refused, and could write as though the number
had been checked. Contract tests pin that the key is emitted and named on both prompts.
Only a live run shows a real sub-agent consuming it.

This lane deliberately states a TAM in the prompt without naming its currency while the
analysis is in USD. That is the shape which produces a refused cross-check on a real run —
though the pipeline only blocks when it actually converted something, so the assertion
below is written to accept either outcome and to check the SHAPE rather than force a
branch. Forcing it would mean pinning FX rates through a prompt, which tests the prompt
rather than the skill.

**Cost / wall time / auth / `-s`**: see `_e2e_harness.py`. Roughly $5-15 and 5-20 minutes.

    uv run pytest founder-skills/tests/test_e2e_market_sizing.py -v -m e2e --tb=short -s
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from _e2e_harness import (
    assert_coaching_commentary_landed,
    assert_run_id_parity,
    has_claude_auth,
    locate_review_dir,
    run_skill,
)


@pytest.mark.e2e
@pytest.mark.skipif(
    not has_claude_auth(),
    reason=(
        "End-to-end smoke needs Claude auth: set ANTHROPIC_API_KEY, "
        "CLAUDE_CODE_OAUTH_TOKEN, or run `claude /login` (subscription)"
    ),
)
def test_market_sizing_smoke(tmp_path: Path) -> None:
    """Run a both-methodologies sizing; assert the delivered chain."""
    workdir = tmp_path / "workspace"
    workdir.mkdir()

    prompt = (
        "Use the market-sizing skill. Foobar Systems is a fictional seed-stage company "
        "selling payments-reconciliation software to equipment rental marketplaces, "
        "priced per marketplace per month. Size the market top-down AND bottom-up. "
        "Our deck states a TAM of 3.2 billion. Use 'foobar-systems' as the slug and USD "
        "as the analysis currency. Don't ask clarifying questions — just run it end to "
        "end and produce the report."
    )

    captured = run_skill(prompt, workdir, label="market-sizing")
    review_dir = locate_review_dir(workdir, "market-sizing-*", captured, "market-sizing")

    payload = assert_coaching_commentary_landed(review_dir, payload_key="comparison_blocked")

    blocked = payload["comparison_blocked"]
    assert isinstance(blocked, dict), f"comparison_blocked is {type(blocked).__name__}, not an object"
    for key in ("metrics", "any", "reason"):
        assert key in blocked, f"comparison_blocked is missing {key!r}"
    assert isinstance(blocked["metrics"], list)
    assert isinstance(blocked["any"], bool)
    # Whichever branch the run took, the object must be self-consistent: a reason exactly
    # when something was blocked. An `any: true` with no reason is what would let a coach
    # know a check failed and have nothing to tell the founder about it.
    assert bool(blocked["metrics"]) == blocked["any"], f"comparison_blocked disagrees with itself: {blocked}"
    if blocked["any"]:
        assert blocked["reason"], "a refused cross-check with no reason for the coach to relay"

    # The claim about the two methodologies must not reappear. It was removed from the
    # notes, the HTML heading and the checklist label before it was removed from the
    # Methodology line, and this is the surface a founder quotes into a deck footnote.
    md = (review_dir / "report.md").read_text(encoding="utf-8")
    assert "cross-validation" not in md.lower(), (
        f"report.md claims the two approaches cross-validate each other; inspect {review_dir}"
    )

    # A converted figure must never be labelled with the wrong currency, and an unstated
    # one must not be labelled at all. Both were shipped defects.
    assert "$" not in json.dumps(payload.get("comparison_blocked")), "currency marker inside the blocked payload"

    summary = payload.get("summary")
    assert isinstance(summary, dict) and summary, "no summary in the coaching payload"
    for metric in ("tam", "sam", "som"):
        assert metric in payload, f"coaching payload is missing the headline {metric.upper()}"

    assert_run_id_parity(
        review_dir,
        ["inputs.json", "sizing.json", "validation.json", "sensitivity.json", "checklist.json", "report.json"],
    )
