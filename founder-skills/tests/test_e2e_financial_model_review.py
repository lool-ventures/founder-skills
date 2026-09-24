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
import re
import shutil
from pathlib import Path

import pytest
from _e2e_harness import (
    FIXTURES,
    assert_coaching_commentary_landed,
    assert_run_id_parity,
    has_claude_auth,
    locate_review_dir,
    model_from_capture,
    run_skill,
    step_summary,
)

MODEL_FIXTURE = FIXTURES / "models" / "synthetic-seed-model.csv"


def self_gated_diagnostic(report_json: dict) -> str:
    """Name the criterion behind a coverage drop, from report.json's machine surface.

    compose_report.py writes its warnings under ``validation``, not at the top level. This read
    ``report_json["warnings"]`` from the day it was written (7a65f72), so on the first real
    failure it met -- v0.12.0's tag run -- it reported "no CHECKLIST_SELF_GATED warning" beside an
    empty ``unmatched_profile_fields``, a combination the assertion's own comment says cannot
    occur, and the criterion was lost again: the exact hole the diagnostic was added to close.
    Pinned by ``test_e2e_self_gated_diagnostic_reads_where_compose_writes`` (free lane).
    """
    warning = self_gated_warning(report_json)
    if warning is not None:
        return f" CHECKLIST_SELF_GATED: {warning.get('message')}"
    return " (no CHECKLIST_SELF_GATED warning — the drop is a profile-resolution failure, not a judgement call)"


def self_gated_warning(report_json: dict) -> dict | None:
    """The CHECKLIST_SELF_GATED warning, or None. Ids live in its ``message``."""
    for w in (report_json.get("validation") or {}).get("warnings") or []:
        if isinstance(w, dict) and w.get("code") == "CHECKLIST_SELF_GATED":
            return w
    return None


def self_gated_ids(report_json: dict) -> list[str]:
    """The criterion ids the assessor set aside, read off the machine surface.

    `compose_report.py` renders them into `message` as a Python list repr, deliberately -- the
    founder gets labels in `founder_message`. That is the only place the identity survives, which
    is what makes an identity assertion possible at all (a count cannot say WHICH criterion, and
    therefore cannot tell a one-off judgement from a systematic regression).
    """
    warning = self_gated_warning(report_json)
    if warning is None:
        return []
    return sorted(set(re.findall(r"\b[A-Z]+_\d+\b", str(warning.get("message") or ""))))


# Criteria whose `not_applicable` is DEFENSIBLE on THIS fixture, so a run that sets one aside is a
# pass provided the disclosure chain below holds. Sourced from reading each criterion's own bars in
# `references/checklist-criteria.md` against the synthetic seed model:
#   CASH_31  IIA grants        -- every bar presupposes the company HAS grants
#   CASH_32  VAT cash timing   -- its pass bar says "where material"
#   STRUCT_05 model matches deck -- no deck is supplied to this lane
#   STRUCT_01/02 tabs          -- a one-sheet CSV has no tabs to isolate
#   STRUCT_09 formatting       -- formatting of a CSV
#   CASH_29  single entity     -- one entity, nothing to consolidate
# A criterion NOT on this list appearing here is the signal: it means either its rubric has no
# branch for this company (fix the rubric, or add the id to checklist.py's
# `_JUDGEMENT_NOT_APPLICABLE`), or our own guidance produced the answer (fix the guidance). That
# decision needs the id, which is why this is a set assertion and not a count -- an assessor
# self-gating three DIFFERENT criteria every run passes any count bound ever written.
# Fixture-scoped by construction: a different model gets its own list, the way each deck-review
# golden carries its own calibration.
DEFENSIBLE_SELF_GATED = frozenset({"CASH_29", "CASH_31", "CASH_32", "STRUCT_01", "STRUCT_02", "STRUCT_05", "STRUCT_09"})


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

    # WHAT THIS ASSERTS, AND WHY IT IS NOT `complete is True`. `complete` is false whenever the
    # scoring sub-agent answered `not_applicable` for a criterion the profile says applies
    # (`checklist.py:855`). That is an LLM judgement on a fixed fixture, and this assert demanded
    # it never fire: 2 failures in 3 independent CI runs, including the one that blocked v0.12.0.
    # The pipeline is BUILT for that judgement to happen -- `checklist.py` records rather than
    # overrides it ("inventing one would be worse than reporting the gap"), and compose discloses
    # it on every founder surface. So the gate now asserts the CONTRACT: resolution is
    # deterministic, and when the judgement fires the founder is told.
    #
    report_json = json.loads((review_dir / "report.json").read_text(encoding="utf-8"))
    md = (review_dir / "report.md").read_text(encoding="utf-8")
    gated_ids = self_gated_ids(report_json)

    # Record the run's judgement BEFORE asserting on it, so a red leaves the same evidence a green
    # does. `DEFENSIBLE_SELF_GATED` can only ever be narrowed from observed ids, and observing them
    # is what has been missing.
    commentary = md.split("## Coaching Commentary", 1)[-1]
    commentary = commentary.rsplit("\n\n---\n*Generated by", 1)[0].strip()
    step_summary(
        "### financial-model-review e2e\n\n"
        f"- model: `{model_from_capture(captured)}`\n"
        f"- criteria not assessed: {coverage['not_assessed_count']}"
        f" — {gated_ids or 'none'}\n"
        f"- unmatched profile fields: {coverage['unmatched_profile_fields'] or 'none'}\n\n"
        "<details><summary>coaching commentary (first 600 chars)</summary>\n\n"
        f"```\n{commentary[:600]}\n```\n\n</details>\n"
    )

    # 1. RESOLUTION. Asserted AFTER the evidence above is recorded, so a resolution failure leaves
    #    the same step summary a pass does -- that was the whole complaint about the assert this
    #    replaces. Not a pure code contract either, and the comment should not pretend otherwise:
    #    `company.geography` is written by the INPUTS_REVIEW sub-agent, not copied from the CSV, and
    #    `_normalize_profile` matches it against a fixed 21-entry table with no enforced vocabulary.
    #    "Israel" resolves; "Tel Aviv, Israel" would not. It has held on every run so far, which is
    #    n=3, not a derivation. `CHECKLIST_PROFILE_UNRESOLVED` carries the raw string when it fails.
    assert coverage["unmatched_profile_fields"] == [], (
        f"the fixture's profile (israel / saas-sales-led / seed) must resolve, but "
        f"{coverage['unmatched_profile_fields']} did not. This is a resolution failure, NOT the "
        f"assessor's judgement. Inspect {review_dir}"
    )

    if coverage["not_assessed_count"]:
        # 2. IDENTITY, not a count.
        unexpected = sorted(set(gated_ids) - DEFENSIBLE_SELF_GATED)
        assert not unexpected, (
            f"the assessor set aside {unexpected}, which is not defensible on this fixture. "
            f"Decide deliberately (see DEFENSIBLE_SELF_GATED above): the criterion's rubric has no "
            f"branch for this company, or our own guidance produced the answer. Full coverage: "
            f"{coverage}. Inspect {review_dir}"
        )
        # 3. DISCLOSURE. Each of these is a surface a founder reads, and each is rendered by code
        #    we own -- so unlike the judgement itself, they cannot vary run to run.
        assert gated_ids, (
            f"{coverage['not_assessed_count']} criteria were not assessed but no "
            f"CHECKLIST_SELF_GATED warning names them. Either compose stopped emitting the warning "
            f"or the drop came from somewhere unaccounted for. Inspect {review_dir}"
        )
        # Exactly one. Two warnings would mean the founder is told the same thing twice with
        # possibly different numbers, and `self_gated_warning` below silently reads the first.
        self_gated_warnings = [
            w
            for w in (report_json.get("validation") or {}).get("warnings") or []
            if isinstance(w, dict) and w.get("code") == "CHECKLIST_SELF_GATED"
        ]
        assert len(self_gated_warnings) == 1, (
            f"expected exactly one CHECKLIST_SELF_GATED warning, got {len(self_gated_warnings)}. Inspect {review_dir}"
        )
        assert coverage["not_assessed_count"] == len(gated_ids), (
            f"coverage says {coverage['not_assessed_count']} not assessed, the warning names "
            f"{len(gated_ids)} ({gated_ids}). The founder is being given two different numbers."
        )
        assert "**Not assessed:**" in md, (
            f"{coverage['not_assessed_count']} criteria were set aside and report.md does not say "
            f"so under the score. That line is the founder's only in-context signal that the "
            f"percentage was computed over fewer criteria. Inspect {review_dir}"
        )
        warning = self_gated_warning(report_json)
        founder_message = str((warning or {}).get("founder_message") or "")
        assert founder_message and founder_message in md, (
            f"CHECKLIST_SELF_GATED's founder_message is not in report.md verbatim; the warnings "
            f"section is where a founder reads the cause. Inspect {review_dir}"
        )
        # 4. The optional HTML, only when the run produced it. Steps 8a-8b are marked (Optional)
        #    in SKILL.md, so asserting its existence would red a correct run that skipped them --
        #    a judgement-gated assert inside the fix for a judgement-gated assert.
        # BOTH pages, not just report.html: `explore.py` renders its own count
        # ("N not assessed") from the same artifacts, and a founder handed the explorer may never
        # open the report. Asserting one and not the other is how a second renderer drifts.
        for page in ("report.html", "explore.html"):
            path = review_dir / page
            if path.exists():
                assert "not assessed" in path.read_text(encoding="utf-8").lower(), (
                    f"{page} was generated but does not disclose the coverage gap; it is a second "
                    f"renderer of the same artifacts and a founder may read only it. "
                    f"Inspect {review_dir}"
                )
    else:
        # The clean branch asserts something too, so a spurious disclosure cannot pass.
        assert not gated_ids and "**Not assessed:**" not in md, (
            f"nothing was set aside, yet report.md discloses a coverage gap ({gated_ids}). Inspect {review_dir}"
        )

    summary = payload["summary"]
    assert isinstance(summary.get("score_pct"), (int, float)), f"no score_pct in {summary}"
    assert summary.get("overall_status"), f"no overall_status in {summary}"

    # The delivered report must not carry internal criterion ids anywhere — the leak that
    # shipped inside the Validation Warnings section while a section-scoped test passed.
    # Two of the three routes are now CONTRACTS: an id an assessor writes into its evidence or
    # notes is rewritten to the criterion's label by the producer, and the payload no longer hands
    # the coach an `id` field to copy. The third is not: `md` includes the coaching commentary, and
    # `insert_coaching.py` reports an internal token without substituting it. So this still rests
    # partly on the coach obeying prose -- less than it did, and it is worth being exact about
    # which part.
    assert "CASH_" not in md and "UNIT_" not in md and "STRUCT_" not in md, (
        f"criterion ids reached the founder-facing report; inspect {review_dir}"
    )

    assert_run_id_parity(
        review_dir,
        ["inputs.json", "checklist.json", "unit_economics.json", "runway.json", "report.json"],
    )
