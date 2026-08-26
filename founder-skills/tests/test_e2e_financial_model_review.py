"""End-to-end smoke: drive financial-model-review against a synthetic seed model.

**Why this lane exists.** `financial-model-review` grew a top-level `score_coverage`
field on its coaching payload, and the whole argument for that field is that the coaching
sub-agent READS it and stops presenting a partial review as a clean one. Contract tests
can assert the key is emitted and that SKILL.md and the agent body both name it. Neither
can show that a real sub-agent received it and wrote usable commentary from it — and a
payload field nobody reads is precisely the defect the field was added to fix. Before
this lane, `test_e2e_deck_review.py` was the only paid lane in the repo, so two of the
three changed payload builders shipped on contract tests alone.

**Cost / wall time / auth / `-s`**: see `_e2e_harness.py`. Roughly $5-15 and 5-20 minutes.
Carries the `e2e` marker, so the default suite skips it.

    uv run pytest founder-skills/tests/test_e2e_financial_model_review.py -v -m e2e --tb=short -s
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from _e2e_harness import (
    FIXTURES,
    assert_coaching_commentary_landed,
    assert_run_id_parity,
    has_claude_auth,
    locate_review_dir,
    run_skill,
)

MODEL_FIXTURE = FIXTURES / "models" / "synthetic-seed-model.csv"


@pytest.mark.e2e
@pytest.mark.skipif(
    not has_claude_auth(),
    reason=(
        "End-to-end smoke needs Claude auth: set ANTHROPIC_API_KEY, "
        "CLAUDE_CODE_OAUTH_TOKEN, or run `claude /login` (subscription)"
    ),
)
def test_financial_model_review_smoke(tmp_path: Path) -> None:
    """Run the skill against the synthetic model; assert the delivered chain."""
    workdir = tmp_path / "workspace"
    workdir.mkdir()
    model_dst = workdir / MODEL_FIXTURE.name
    shutil.copy(MODEL_FIXTURE, model_dst)

    prompt = (
        f"Use the financial-model-review skill to review the model at {model_dst}. "
        f"It's a fictional seed-stage B2B SaaS company called Foobar Systems, based in "
        f"Israel, selling on an annual sales-led motion. Use 'foobar-systems' as the "
        f"slug. Everything you need is in the file — don't ask clarifying questions, "
        f"just run the review end to end and produce the report."
    )

    captured = run_skill(prompt, workdir, label="fmr")
    review_dir = locate_review_dir(workdir, "financial-model-review-*", captured, "financial-model-review")

    # The contract this lane exists for: the coach read the payload and wrote from it.
    payload = assert_coaching_commentary_landed(review_dir, payload_key="score_coverage")

    coverage = payload["score_coverage"]
    assert isinstance(coverage, dict), f"score_coverage is {type(coverage).__name__}, not an object"
    for key in ("not_assessed_count", "total_criteria", "unmatched_profile_fields", "complete"):
        assert key in coverage, f"score_coverage is missing {key!r}"
    # No criterion ids: this reaches a founder through the commentary.
    assert "CASH_" not in json.dumps(coverage), "score_coverage leaks criterion ids to the coach"

    # The profile in the fixture is fully resolvable (israel / saas-sales-led / seed), so a real
    # run must report complete coverage. THREE causes, not the two this comment used to name:
    # the normalization tables moved, the model mis-read the profile, or -- the one measured on
    # 2026-08-26 -- the model returned `not_applicable` for a criterion the profile says APPLIES
    # and that criterion is not on checklist.py's `_JUDGEMENT_NOT_APPLICABLE` allowlist. The
    # third is distinguishable: `unmatched_profile_fields` is EMPTY for it and non-empty for the
    # others, because self-gating is a judgement call rather than a resolution failure.
    #
    # NAME THE CRITERION. `score_coverage` deliberately carries no ids (it reaches a founder via
    # commentary), so a bare count plus a run-dir path is undiagnosable the moment the workspace
    # is gone -- which is exactly what happened: the same failure reproduced byte-identically on
    # two CI runs, passed locally, and the criterion could not be recovered from either. The ids
    # DO exist, on the machine surface built for this: report.json's CHECKLIST_SELF_GATED
    # warning puts them in `message` while the founder gets labels in `founder_message`.
    if coverage["complete"] is not True:
        gated = ""
        try:
            rj = json.loads((review_dir / "report.json").read_text(encoding="utf-8"))
            for w in rj.get("warnings") or []:
                if isinstance(w, dict) and w.get("code") == "CHECKLIST_SELF_GATED":
                    gated = f" CHECKLIST_SELF_GATED: {w.get('message')}"
                    break
            if not gated:
                gated = (
                    " (no CHECKLIST_SELF_GATED warning — the drop is a profile-resolution"
                    " failure, not a judgement call)"
                )
        except Exception as exc:  # noqa: BLE001 - diagnostic only; never mask the real assert
            gated = f" (could not read report.json for the criterion ids: {exc})"
        raise AssertionError(
            f"the fixture's profile is resolvable, so nothing should have dropped: {coverage}.{gated} "
            f"Inspect {review_dir}"
        )

    summary = payload["summary"]
    assert isinstance(summary.get("score_pct"), (int, float)), f"no score_pct in {summary}"
    assert summary.get("overall_status"), f"no overall_status in {summary}"

    # The delivered report must not carry internal criterion ids anywhere — the leak that
    # shipped inside the Validation Warnings section while a section-scoped test passed.
    md = (review_dir / "report.md").read_text(encoding="utf-8")
    assert "CASH_" not in md and "UNIT_" not in md and "STRUCT_" not in md, (
        f"criterion ids reached the founder-facing report; inspect {review_dir}"
    )

    assert_run_id_parity(
        review_dir,
        ["inputs.json", "checklist.json", "unit_economics.json", "runway.json", "report.json"],
    )
