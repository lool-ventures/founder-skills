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
    compose_record_problems,
    has_claude_auth,
    host_request,
    lane_run_id,
    locate_review_dir,
    pre_answer_problems,
    read_run_ledger,
    read_run_status,
    run_complete_problems,
    run_skill,
)
from _pool_sizing_claims import (
    coaching_body,
    counterfactual_lever_problems,
    increase_reading_lever_problems,
    judge_arguments,
    pool_sizing_problems,
)

CAP_TABLE_OPT_IN = "RUN_PAID_E2E_CAP_TABLE"

# The host's lines (read by test_lane_host_lines.py, which feeds them to the real `start` on every free run).
# Neither prompt states the engagement mode, which has no default, and neither lane can ask; the smoke names
# no existing option plan (the pool lane states one, so its pool question is never owed). The scenarios
# include the cap-implied SAFE snapshot because it is the one that produces the rows the substance check
# reads. Jurisdiction, the top-up and the pool basis stay in the prose: those are the stated defaults the
# assertions check.
# Each prompt states every field the cap-table schemas require of what a founder supplies (founder names and
# shares, the SAFE's investor, amount, date and form, and in the pool lane the plan's type and counts): a field
# the founder did not state is never invented, it becomes a founder-fact question with no default, and these
# unattended lanes cannot answer one. `STATED` pairs each such field with the words that state it;
# test_lane_host_lines.py holds both against the schemas. Names and figures are invented.
SMOKE_PROMPT = (
    "Use the cap-table skill. Foobar Systems is a fictional Delaware C-corp. Its two founders, Avery Foo and "
    "Blake Bar, hold 4,000,000 common shares each (8,000,000 in total). There is one outstanding YC post-money SAFE "
    "from Example Seed Fund for $500,000 at a $5,000,000 post-money valuation cap, signed 2024-03-01. We are now "
    "modelling a priced Series A: $3,000,000 of new money at a $12,000,000 pre-money valuation, with a 10% "
    "post-money option pool. Use 'foobar' as the slug. Also tell me whether our founder shares will qualify for "
    "QSBS when we sell. Don't ask clarifying questions — run it end to end and produce the full review."
)
POOL_PROMPT = (
    "Use the cap-table skill. Barbaz Labs is a fictional Delaware C-corp. Its two founders, Avery Foo and Blake "
    "Bar, hold 4,000,000 common shares each (8,000,000 in total). The existing option plan is an ISO plan with "
    "1,000,000 options authorized: 800,000 granted and outstanding, and 200,000 unallocated and available for "
    "grant. There is one outstanding YC post-money SAFE from Example Seed Fund for $500,000 at a $5,000,000 "
    "post-money valuation cap, signed 2024-03-01. We are modelling a priced Series A: $3,000,000 of new money at "
    "a $12,000,000 pre-money valuation, with a 10% post-money option pool. Use 'barbaz' as the slug. Don't ask "
    "me questions -- just run it end to end and produce the full review."
)
_COMMON_STATED = {
    "founders.name": ("Avery Foo", "Blake Bar"),
    "founders.common_shares": ("4,000,000 common shares each",),
    "safes.investor_name": ("Example Seed Fund",),
    "safes.purchase_amount": ("$500,000",),
    "safes.issuance_date": ("2024-03-01",),
    "safes.form": ("YC post-money SAFE", "$5,000,000 post-money valuation cap"),
}
STATED = {
    "smoke": dict(_COMMON_STATED),
    "pool": {
        **_COMMON_STATED,
        "option_pool.plan_type": ("ISO plan",),
        "option_pool.authorized": ("1,000,000 options authorized",),
        "option_pool.issued": ("800,000 granted and outstanding",),
        "option_pool.unallocated": ("200,000 unallocated",),
    },
}

SKILL = "cap-table"
CANARY = "lane canary 5d1b"
SMOKE_LANE = "ct"
SMOKE_ANSWERS = (
    ("ct_cap_base_confirmation", "confirmed"),
    ("ct_scenario_selection", "cap_implied_safe,priced_round"),
    ("ct_engagement_mode", "standard"),
    ("ct_option_pool", "no_pool"),
)
SMOKE_NOTES = (("ct_cap_base_confirmation", CANARY),)
POOL_LANE = "ct-pool"
POOL_ANSWERS = (
    ("ct_cap_base_confirmation", "confirmed"),
    ("ct_scenario_selection", "priced_round"),
    ("ct_engagement_mode", "standard"),
)


def _status_problems(workdir: Path, run_id: str, review_dir: Path) -> tuple[list[str], dict, dict]:
    status = read_run_status(workdir, run_id)
    ledger = read_run_ledger(workdir, run_id)
    problems = run_complete_problems(status, run_id, SKILL, review_dir)
    problems += compose_record_problems(review_dir, run_id, status)
    return problems, status, ledger


def _current(ledger: dict, gate: str) -> tuple:
    cur = ((ledger.get("gates") or {}).get(gate) or {}).get("current") or {}
    return (cur.get("answer_id"), cur.get("resolution"), cur.get("default_reason"))


POOL_READING_OPT_IN = "RUN_PAID_E2E_CAP_TABLE_POOL"

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


# A phrase above that is the object of an open question or a refusal to decide is the boundary holding, not a
# conclusion: "whether you qualify", "if you qualify", "not concluding that you qualify", "doesn't conclude that you
# qualify" (any n't contraction, straight or curly apostrophe). Only the words right
# before the phrase count, so "Whether or not the board agrees, you qualify." is still a conclusion.
_DEFERS = re.compile(
    r"(?:\bwhether|\bif|(?:\b(?:not|never|cannot)|n['\u2019]t)\s+(?:conclud|say|tell|determin)\w*(?:\s+that)?)\s+$",
    re.IGNORECASE,
)


def eligibility_conclusion(text: str) -> re.Match[str] | None:
    """The first place `text` concludes eligibility, or None."""
    for pattern in ELIGIBILITY_CONCLUSIONS:
        for hit in re.finditer(pattern, text, re.IGNORECASE):
            if not _DEFERS.search(text[: hit.start()]):
                return hit
    return None


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

    prompt = SMOKE_PROMPT

    run_id = lane_run_id(SMOKE_LANE)
    prompt = host_request(prompt, run_id, answers=SMOKE_ANSWERS, notes=SMOKE_NOTES)
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
        hit = eligibility_conclusion(text)
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
    assert_pool_backstop_engaged(review_dir)

    # ---------------------------------------------------------------- the run status a host reads
    problems, _status, ledger = _status_problems(workdir, run_id, review_dir)
    problems += pre_answer_problems(ledger, "ct_cap_base_confirmation", "confirmed", CANARY)
    picked = _current(ledger, "ct_scenario_selection")
    if set(str(picked[0] or "").split(",")) != {"cap_implied_safe", "priced_round"} or picked[1] != "answered":
        problems.append(f"ct_scenario_selection is {picked}, the request selected cap_implied_safe,priced_round")
    if _current(ledger, "ct_jurisdiction") != ("delaware", "default_taken", "stated_in_request"):
        problems.append(f"ct_jurisdiction is {_current(ledger, 'ct_jurisdiction')}, stated as Delaware in the prompt")
    assert not problems, "\n".join(problems)


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
    checked = 0

    for scenario in scenarios.get("scenarios") or []:
        outputs = scenario.get("computed_outputs") or {}
        # `per_safe` is a LIST of id-bearing rows, not a dict keyed by id. It became one when the
        # id-keyed maps were removed -- an id read out of a founder's PDF cannot be a dict key,
        # because two colliding ids drop a row while the totals keep counting both. This file was
        # ON the measured migration list and was missed anyway: `addopts` deselects `e2e`, so the
        # suite that would have caught it never collects this module, and the tag gate skips this
        # lane by name. Two independent reasons a broken assertion stayed green.
        per_safe = outputs.get("per_safe") or []
        assert isinstance(per_safe, list), (
            f"per_safe is {type(per_safe).__name__}, expected a list of id-bearing rows. If the "
            "producer went back to an id-keyed map, that is the defect this shape exists to prevent."
        )
        cap_implied = {
            row.get("id"): row for row in per_safe if isinstance(row, dict) and row.get("branch") == "cap_implied"
        }
        if not cap_implied:
            continue

        # Divide by the SET's Company Capitalization, not by `pre_fd + this SAFE's shares`. Under the
        # post-money definition every converting SAFE sits in every other SAFE's denominator, so a
        # per-instrument base is only right when there is exactly one SAFE. A first version of this
        # check used that base and would have failed a CORRECT two-SAFE run: at $500k/$5M and
        # $1M/$10M against 8M shares, each SAFE holds 10% of a 10,000,000 total, but
        # 1,000,000 / (8,000,000 + 1,000,000) reads as 11.1%.
        total = outputs.get("company_capitalization")
        assert total, (
            "cap-implied outputs carry no company_capitalization — without the denominator the "
            "stated percentages cannot be checked against the stated share counts"
        )

        for safe_id, out in cap_implied.items():
            stated = out.get("cap_implied_ownership")
            shares = out.get("cap_implied_shares")
            if stated is None or not shares:
                continue
            realised = shares / total
            checked += 1
            assert abs(realised - stated) < 1e-6, (
                f"{safe_id}: report states {stated:.2%} cap-implied ownership but the {shares:,.0f} "
                f"shares it also states deliver {realised:.2%} of the {total:,.0f}-share Company "
                "Capitalization. A founder reading the percentage and a founder reading the share "
                "count get different answers from one table"
            )

        # The fixed point must have closed: the denominator is the pre-financing base PLUS the shares
        # it produced. This is the check with content -- `shares/total == ownership` is a tautology
        # once shares are derived from total, which is the same "asserted against the formula that
        # produced it" blindness that let the original defect ship.
        cap_state = json.loads((review_dir / "cap_state.json").read_text(encoding="utf-8"))
        pre_fd = (cap_state.get("as_converted_totals") or {}).get("fully_diluted_shares")
        if pre_fd:
            closed = pre_fd + sum(v["cap_implied_shares"] for v in cap_implied.values())
            assert abs(closed - total) < 1e-6 * max(1.0, total), (
                f"the cap-implied denominator did not close: company_capitalization is {total:,.0f} "
                f"but the pre-financing base plus converting shares is {closed:,.0f}"
            )

    # THE LEVER, ENGAGED. Only the cap-implied SAFE snapshot produces `cap_implied` rows; a run that modelled
    # the priced round alone would pass every check above by having nothing to check. The request selects the
    # snapshot, so at least one row must have been checked.
    assert checked >= 1, (
        "no cap-implied SAFE row was checked: the cap-implied snapshot did not run, so this lane's substance "
        f"check tested nothing (scenario types: {[s.get('type') for s in scenarios.get('scenarios') or []]})"
    )


def assert_pool_backstop_engaged(review_dir: Path) -> None:
    """The in-pipeline backstop (`pool_claims_check.py`) ran on THIS run's commentary, and what report.md shows is
    the file it wrote. The lane still judges the delivered text itself; this proves the gate engaged, so a green
    judgement is not a coach that simply happened to stay off the topic while the check never ran."""
    report = json.loads((review_dir / "report.json").read_text(encoding="utf-8"))
    run_id = (report.get("metadata") or {}).get("run_id")
    records = [
        *review_dir.glob("handoff/*/coaching.md.pool-check.json"),
        *review_dir.glob("coaching.md.pool-check.json"),
    ]
    mine = [p for p in records if json.loads(p.read_text(encoding="utf-8")).get("run_id") == run_id]
    assert mine, f"no pool-claims check record for run {run_id} under {review_dir} (found {records})"
    record_path = mine[0]
    record = json.loads(record_path.read_text(encoding="utf-8"))
    assert record["action"] in {"clean", "stripped", "not_judged", "no_pool_target"}, record
    checked = record_path.parent / "coaching.checked.json"
    assert checked.is_file(), f"the check wrote no {checked.name}, so nothing it checked was inserted"
    inserted = coaching_body((review_dir / "report.md").read_text(encoding="utf-8")) or ""
    written = json.loads(checked.read_text(encoding="utf-8"))["checked_commentary_markdown"]
    assert " ".join(inserted.split()) == " ".join(written.split()), "report.md's commentary is not the checked file"
    print(
        f"[e2e:cap-table] pool backstop: action={record['action']} findings={len(record.get('findings') or [])}",
        flush=True,
    )


def assert_pool_basis_commentary_matches_inputs(review_dir: Path) -> None:
    """The coaching prose's option-pool sizing claims must be grounded in what the model computed.

    Judged by `_pool_sizing_claims.pool_sizing_problems`, which the free `test_pool_sizing_claims.py`
    pins on a labelled table (this lane's previous check failed correct, cited advice and passed a
    wrong statement). The other sizing's computed founders percentage comes from `scenarios.json`
    when the model produced one; without it, any advice about the other sizing is unsupported.
    """
    # This lane's prompt states a post-money pool, so every early exit is a failure: a judge that skips
    # reports green on a run it never judged.
    requests_path = review_dir / "scenario_requests.json"
    assert requests_path.is_file(), "no scenario_requests.json -- the pool-sizing judge had nothing to judge"
    requests = json.loads(requests_path.read_text(encoding="utf-8"))
    bases = {
        (r.get("parameters") or {}).get("target_basis")
        for r in requests
        if (r.get("parameters") or {}).get("target_basis")
    }
    assert bases == {"post_money"}, f"the prompt states a post-money pool; the scenarios model {bases or 'none'}"
    modeled_basis = "post_money"

    md = (review_dir / "report.md").read_text(encoding="utf-8")
    body = coaching_body(md)
    assert body is not None, "report.md has no Coaching Commentary to judge"

    scenarios = json.loads((review_dir / "scenarios.json").read_text(encoding="utf-8"))
    lever = counterfactual_lever_problems(scenarios, md)
    assert not lever, f"the pool-sizing counterfactual did not engage, so the judgement below means nothing: {lever}"

    # The run's figures, derived exactly as the in-pipeline backstop derives them.
    other_founders_pcts = judge_arguments(scenarios)["other_founders_pct"]
    # target_pct: the pool target itself is not a founders figure. It lands with the judge's rule that any mention
    # of an uncomputed new-options reading is a finding -- before that rule, the untargeted 10% was the only
    # thing that caught an invented reading.
    problems = pool_sizing_problems(
        body, modeled_basis=modeled_basis, other_founders_pct=other_founders_pcts, target_pct=10.0
    )
    assert not problems, (
        f"the pool was sized {modeled_basis} and the commentary's pool-sizing claims are not grounded in "
        f"the computed figures: {problems!r}"
    )


def _pool_reading_lane_authorized() -> bool:
    return os.environ.get(POOL_READING_OPT_IN, "").strip().lower() in {"1", "true", "yes"}


def _payload_percentages(review_dir: Path) -> list[float]:
    """Every percentage the coaching payload SHOWS the coach, as numbers: the closed world a founders figure in
    the coaching must come from."""
    payload = json.loads((review_dir / "report.json").read_text(encoding="utf-8")).get("coaching_payload") or {}
    found: list[float] = []

    def walk(o: object) -> None:
        if isinstance(o, str):
            found.extend(float(m) for m in re.findall(r"(\d{1,3}(?:\.\d+)?)\s*%", o))
        elif isinstance(o, dict):
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
        elif isinstance(o, float) and 0.0 <= o <= 1.0:
            found.append(round(o * 100, 1))

    walk(payload)
    return found


@pytest.mark.e2e
@pytest.mark.skipif(
    not (has_claude_auth() and _pool_reading_lane_authorized()),
    reason=(
        f"cap-table's pool-reading lane needs Claude auth, RUN_PAID_E2E=1, and {POOL_READING_OPT_IN}=1. "
        "It is the only run that reaches the unconfirmed pool-reading disclosure and the figure computed "
        "for it; billed on demand, never by a tag."
    ),
)
def test_cap_table_pool_reading_lane(tmp_path: Path) -> None:
    """A post-money pool target beside existing unallocated options, and a founder who says not to ask.

    Asking nothing is correct here, and the disclosure fires on any post-money pool beside unallocated options,
    so neither is what this lane tests about the model. What it tests is that the model models the basis the
    founder STATED (`post_money`) rather than writing the other reading in unasked, and that the report then
    reads the target as the pool available after the round, discloses the other reading (the percentage may
    count only the new options) and computes that reading's figure; the coach may state it only by citing it.
    No other lane reaches this path: the smoke lane's prompt names no pool, so nothing is disclosed there. THE
    VERDICT STILL NEEDS A HUMAN READ of the coaching paragraph -- the judge is a pattern matcher and cannot see
    a sentence that swaps two computed figures.
    """
    workdir = tmp_path / "workspace"
    workdir.mkdir()

    pool_prompt = POOL_PROMPT

    run_id = lane_run_id(POOL_LANE)
    pool_prompt = host_request(pool_prompt, run_id, answers=POOL_ANSWERS)
    captured = run_skill(pool_prompt, workdir, label="cap-table-pool-reading")
    review_dir = locate_review_dir(workdir, "cap-table-*", captured, "cap-table")
    assert_run_id_parity(review_dir, RUN_ID_ARTIFACTS)
    assert_coaching_commentary_landed(review_dir, payload_key="scenario_digest")

    md = (review_dir / "report.md").read_text(encoding="utf-8")
    scenarios = json.loads((review_dir / "scenarios.json").read_text(encoding="utf-8"))
    # The founder stated a post-money pool and asked not to be asked, so the only basis the model may write is the
    # stated one; the new-options-only reading written in unasked would be a reading nobody gave.
    requests = json.loads((review_dir / "scenario_requests.json").read_text(encoding="utf-8"))
    pool_bases = [
        (r.get("parameters") or {}).get("target_basis")
        for r in requests
        if (r.get("parameters") or {}).get("target_pool_percent")
    ]
    assert pool_bases and set(pool_bases) == {"post_money"}, f"modelled pool bases {pool_bases}, stated post_money"
    # The lever: disclosure fired, the reading was computed, report.md carries its line.
    lever = increase_reading_lever_problems(scenarios, md)
    assert not lever, f"the new-options-only reading did not engage, so nothing below is evidence: {lever}"
    assert "read as the pool available after the round" in md, "the disclosure is not on report.md"

    body = coaching_body(md)
    assert body is not None, "report.md has no Coaching Commentary to judge"
    # The run's figures, derived exactly as the in-pipeline backstop derives them.
    args = judge_arguments(scenarios)
    problems = pool_sizing_problems(
        body,
        modeled_basis="post_money",
        other_founders_pct=args["other_founders_pct"],
        increase_founders_pct=args["increase_founders_pct"],
        target_pct=10.0,
        # The run's own figures as well as the payload's: the comparison's and the new-options reading's figures
        # left the coaching payload for the report, and a citation of one is not an invented number.
        known_figures=[
            *_payload_percentages(review_dir),
            *(args["other_founders_pct"] or []),
            *(args["increase_founders_pct"] or []),
        ],
    )
    assert not problems, f"the coach's pool-sizing figures are not the computed ones: {problems!r}"
    assert_pool_backstop_engaged(review_dir)

    # ---------------------------------------------------------------- the run status a host reads
    # The prompt states a post-money pool and asks not to be asked, so the pool basis is the stated default.
    status_problems, _status, ledger = _status_problems(workdir, run_id, review_dir)
    if _current(ledger, "ct_pool_basis") != ("post_money", "default_taken", "stated_in_request"):
        status_problems.append(f"ct_pool_basis is {_current(ledger, 'ct_pool_basis')}, stated post-money")
    assert not status_problems, "\n".join(status_problems)
