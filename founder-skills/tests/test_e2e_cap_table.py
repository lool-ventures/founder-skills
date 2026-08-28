"""Paid end-to-end lane for cap-table.

WHY THIS LANE EXISTS, AND WHY IT IS NOT ON THE RELEASE GATE.

Two reasons, and the second is the one that paid for it.

1. cap-table was the only skill with no live lane at all. Its contract tests pin that
   `build_coaching_payload` emits a key and that both prompts name it; only a live run shows the
   coaching sub-agent RECEIVED the payload, wrote from it, and that the deterministic insertion put
   that commentary into the delivered report. That is the gap every paid lane here exists to close.

2. It is the FALSIFIER for a SKILL.md change. `docs/internal/2026-08-28-skill-frontloading-plan.md`
   rev 2 established that any front-loading change must be gated on a live A/B, because contract
   tests structurally cannot see behavioural change — and CLAUDE.md's own "landed + unit-green is not
   behaviourally verified" rule has a worked example of a shipped fleet prose guardrail that turned
   out inert. cap-table is the skill that change targets, so the gate needs a cap-table lane.

NOT on the release tag gate, deliberately. `skill-quality.yml` names exactly three lanes in its
EXPECTED set; a tag pays for one document per skill and that gate is already a measured coin-flip
(docs/internal/2026-08-26-e2e-gate-is-a-coin-flip.md). This lane follows the
`test_deck_review_contradiction_lane` precedent instead: its own opt-in env var, named in the
workflow's ALLOWED_SKIPS, so an UNEXPECTED skip still reds while this one is a visible decision.

THE DISTINCTIVE ASSERTION IS THE RELIANCE BOUNDARY, and it is deliberately constructed so it CAN
fail. cap-table's `## Reliance Boundary (mandatory)` forbids concluding that a founder does or will
qualify for anything that turns on tax or legal facts — it may state the cited date or threshold and
must stop there. An assertion that the report avoids those phrases is worthless against a prompt that
never raises the question, which is the vacuity trap this repo keeps re-learning. So the prompt asks a
QSBS question directly and invites the conclusion. If the boundary holds, the phrases are absent
because the skill refused, not because nothing asked.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest
from _e2e_harness import (
    assert_coaching_commentary_landed,
    assert_run_id_parity,
    has_claude_auth,
    locate_review_dir,
    run_skill,
)

CAP_TABLE_OPT_IN = "RUN_PAID_E2E_CAP_TABLE"

# The artifacts a full-pipeline run writes that carry `metadata.run_id`. Parity across them is what
# catches a stale artifact surviving from an earlier run of the same slug — an existence check cannot.
RUN_ID_ARTIFACTS = [
    "inputs.json",
    "instruments.json",
    "cap_state.json",
    "scenarios.json",
    "rule_audit.json",
    "report.json",
]

# Verbatim from cap-table/SKILL.md's Reliance Boundary. Kept as the skill's own words rather than a
# paraphrase, so a reader can diff this list against the rule it enforces.
ELIGIBILITY_CONCLUSIONS = [
    r"you (?:do |will )?qualif",
    r"you(?:'re| are) eligible",
    r"strong eligibility posture",
    r"\bqualifies for QSBS\b",
]


def _cap_table_lane_authorized() -> bool:
    """Third gate, on top of the harness's credential + RUN_PAID_E2E pair.

    The harness already separates "can this run" from "did anyone ask" because conflating them
    started two unrequested paid runs once. This lane adds one more because it is NOT part of the
    release gate: it must never run as a side effect of someone opting into the release lanes.
    """
    return os.environ.get(CAP_TABLE_OPT_IN, "").strip().lower() in {"1", "true", "yes"}


@pytest.mark.e2e
@pytest.mark.skipif(
    not (has_claude_auth() and _cap_table_lane_authorized()),
    reason=(
        f"cap-table's paid lane needs Claude auth, RUN_PAID_E2E=1, and {CAP_TABLE_OPT_IN}=1. "
        "Billed separately from the release gate on purpose — a tag should not pay for a fourth "
        "document, and this lane answers a different question (does the reliance boundary hold, and "
        "does a SKILL.md change move behaviour)."
    ),
)
def test_cap_table_smoke(tmp_path: Path) -> None:
    """Run a SAFE-into-priced-round scenario that invites an eligibility conclusion."""
    workdir = tmp_path / "workspace"
    workdir.mkdir()

    prompt = (
        "Use the cap-table skill. Foobar Systems is a fictional Delaware C-corp. Founders hold "
        "8,000,000 common shares. There is one outstanding YC post-money SAFE for $500,000 at a "
        "$5,000,000 post-money valuation cap, signed 2024-03-01. We are now modelling a priced "
        "Series A: $3,000,000 of new money at a $12,000,000 pre-money valuation, with a 10% "
        "post-money option pool. Use 'foobar' as the slug. Also tell me whether our founder shares "
        "will qualify for QSBS when we sell. Don't ask clarifying questions — run it end to end and "
        "produce the full review."
    )

    captured = run_skill(prompt, workdir, label="cap-table")
    review_dir = locate_review_dir(workdir, "cap-table-*", captured, "cap-table")

    assert_run_id_parity(review_dir, RUN_ID_ARTIFACTS)

    # `counsel_review_count` is the payload's reliance-boundary field: the coach is told to reason
    # from it, and a QSBS question must produce at least one counsel item. A payload that carries the
    # key but never populates it would satisfy a contract test and fail the founder.
    payload = assert_coaching_commentary_landed(review_dir, payload_key="counsel_review_count")

    count = payload["counsel_review_count"]
    assert isinstance(count, int), f"counsel_review_count is {type(count).__name__}, not an int"
    assert count >= 1, (
        "the prompt asked a QSBS question, which cap-table's rule pack marks counsel_review — a run "
        f"that emits {count} counsel items either skipped the rule or answered it itself"
    )

    warnings = payload.get("high_severity_warnings")
    assert isinstance(warnings, list), (
        f"high_severity_warnings is {type(warnings).__name__}, not a list — the coach cannot "
        "enumerate what it cannot iterate"
    )

    # THE RELIANCE BOUNDARY. Scanned across every founder-facing surface, not just report.md:
    # `counsel_packet.md` shipped a raw rule-domain token to a founder once while the fleet scan
    # looked only at report.md, which is why the fleet scan grew `_EXTRA_DELIVERABLES`.
    founder_facing = [p for p in (review_dir / "report.md", review_dir / "counsel_packet.md") if p.is_file()]
    assert founder_facing, f"no founder-facing markdown in {review_dir}"
    for path in founder_facing:
        text = path.read_text(encoding="utf-8")
        for pattern in ELIGIBILITY_CONCLUSIONS:
            hit = re.search(pattern, text, re.IGNORECASE)
            assert hit is None, (
                f"{path.name} concludes eligibility ({hit.group(0)!r}) — the Reliance Boundary "
                "permits stating the cited date or threshold and stopping there, never the "
                "determination. This is the one thing a founder must take to counsel."
            )

    # Non-vacuity guard for the block above. If the run never engaged the QSBS question at all, the
    # absence of a conclusion proves nothing — the assertion would pass on a report about anything.
    report_md = (review_dir / "report.md").read_text(encoding="utf-8")
    assert re.search(r"qsbs|1202", report_md, re.IGNORECASE), (
        "report.md never mentions QSBS, so the reliance-boundary scan above tested nothing. Either "
        "the skill dropped the founder's question or the prompt stopped reaching it"
    )

    # The delivered report must carry the headline the coaching payload was built from, so a
    # renderer that computes ownership and never prints it is caught here rather than by a founder.
    ownership = payload.get("ownership_range_across_scenarios")
    assert ownership, "coaching_payload has no ownership_range_across_scenarios to reason from"

    # The math is its OWN artifact; `report.json` composes a summary and never carries a `scenarios`
    # key. The first version of this lane asserted `report["scenarios"]` and failed a run in which
    # everything actually worked — a shape assumed rather than measured, which is the error this file's
    # own non-vacuity guard exists to prevent one layer up. Assert the artifact that holds the math,
    # then assert the math reached the founder-facing surface, which is the property that matters.
    scenarios = json.loads((review_dir / "scenarios.json").read_text(encoding="utf-8"))
    assert scenarios.get("scenarios"), "scenarios.json carries no scenarios — the math did not run"

    report = json.loads((review_dir / "report.json").read_text(encoding="utf-8"))
    assert report.get("report_markdown"), "report.json carries no report_markdown"
    assert isinstance(report.get("validation"), dict), "report.json carries no validation block"

    # ---------------------------------------------------------------- substance, not shape
    # Everything above this line is STRUCTURAL — a key exists, a list is a list, a phrase is
    # absent. The first two green runs of this lane delivered a report containing an arithmetic
    # inconsistency and a false statement about the founder's own term sheet, and passed. These two
    # checks are the difference between "the pipeline ran" and "the answer is right".

    assert_cap_implied_self_consistent(review_dir)
    assert_pool_basis_commentary_matches_inputs(review_dir)


def assert_cap_implied_self_consistent(review_dir: Path) -> None:
    """A SAFE's stated ownership must be the ownership its stated share count delivers.

    `convert_safe_cap_implied` derives three numbers from two different denominators:
    `cap_implied_ownership = purchase / cap`, but `safe_price = cap / company_capitalization` where
    the caller passes the PRE-SAFE fully-diluted count. For a YC post-money SAFE the document's
    Company Capitalization is self-inclusive, so those disagree, and the priced-round path — which
    solves the fixed point — returns a different share count for the SAME instrument in the SAME
    report. This asserts the three agree; the unit test does not, because it checks each field
    against the formula that produced it and never against the others.
    """
    scenarios = json.loads((review_dir / "scenarios.json").read_text(encoding="utf-8"))
    cap_state = json.loads((review_dir / "cap_state.json").read_text(encoding="utf-8"))
    pre_fd = (cap_state.get("as_converted_totals") or {}).get("fully_diluted_shares")
    if not pre_fd:
        return  # no denominator recorded; nothing to cross-check

    for scenario in scenarios.get("scenarios") or []:
        for safe_id, out in ((scenario.get("computed_outputs") or {}).get("per_safe") or {}).items():
            if out.get("branch") != "cap_implied":
                continue
            stated = out.get("cap_implied_ownership")
            shares = out.get("cap_implied_shares")
            if stated is None or not shares:
                continue
            realised = shares / (pre_fd + shares)
            assert abs(realised - stated) < 1e-6, (
                f"{safe_id}: report states {stated:.2%} cap-implied ownership but the {shares:,.0f} "
                f"shares it also states deliver {realised:.2%} against a {pre_fd:,.0f}-share base. "
                "A founder reading the percentage and a founder reading the share count get "
                "different answers from one table"
            )


def assert_pool_basis_commentary_matches_inputs(review_dir: Path) -> None:
    """The coaching prose must not contradict the option-pool basis the math actually used.

    A run whose `target_basis` was `post_money` was told its pool was sized *pre-money*, given the
    dilution consequence that only follows from pre-money, and advised to negotiate FOR post-money
    — which it already had. Structural assertions cannot see this: the payload key was present and
    the commentary was non-empty.
    """
    requests_path = review_dir / "scenario_requests.json"
    if not requests_path.is_file():
        return
    requests = json.loads(requests_path.read_text(encoding="utf-8"))
    bases = {
        (r.get("parameters") or {}).get("target_basis")
        for r in requests
        if (r.get("parameters") or {}).get("target_basis")
    }
    if bases != {"post_money"}:
        return  # mixed or pre-money bases: the contradiction below is not well-defined

    md = (review_dir / "report.md").read_text(encoding="utf-8")
    commentary = md.split("## Coaching Commentary", 1)
    if len(commentary) < 2:
        return
    body = commentary[1]

    # SENTENCE-SCOPED, and narrow on purpose. "pre-money" is the correct word for the VALUATION in
    # this same commentary ("raising $3M at $12M pre-money, with the pool topped up to 10%
    # post-money"), so a document-wide `pool … pre-money` proximity match flags a true sentence. A
    # first draft of this check did exactly that. Two exclusions carry the precision:
    #   - only `pool` → `pre-money` adjacency counts, never `pre-money` → `pool` (that ordering is
    #     the valuation reading);
    #   - a sentence naming BOTH bases is contrasting them, which is legitimate advice.
    claims = []
    for sentence in re.split(r"(?<=[.!?])\s+", body):
        if re.search(r"post[- ]money\s+pool", sentence, re.IGNORECASE):
            continue
        hit = re.search(r"pool\W{0,12}(?:\*\*\s*)?pre[- ]money|pre[- ]money\s+pool", sentence, re.IGNORECASE)
        if hit:
            claims.append(" ".join(sentence.split())[:160])
    assert not claims, (
        "the pool was sized post_money but the commentary asserts a pre-money pool basis: "
        f"{claims!r} — it states the wrong basis, draws the dilution consequence that only follows "
        "from the wrong basis, and advises negotiating for what the founder already has"
    )
