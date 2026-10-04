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

import importlib.util
import json
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from _e2e_harness import (
    FIXTURES,
    PLUGIN_PATH,
    assert_coaching_commentary_landed,
    assert_received_prompt,
    assert_run_id_parity,
    dispatch_report,
    format_dispatch_report,
    has_claude_auth,
    locate_review_dir,
    model_from_capture,
    run_skill_capture,
    step_summary,
)

MODEL_FIXTURE = FIXTURES / "models" / "synthetic-seed-model.csv"
SCRIPTS = PLUGIN_PATH / "skills" / "financial-model-review" / "scripts"


def _load_handover_check() -> Any:
    """The containment rule the Stop hook runs, loaded by path so the lane and the hook share it."""
    spec = importlib.util.spec_from_file_location("_handover_check", PLUGIN_PATH / "scripts" / "_handover_check.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_handover = _load_handover_check()


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

# The shell tool's name: `Bash` under the SDK this lane drives; `mcp__workspace__bash` at hostloop,
# accepted so the helpers below read a cowork cassette's tool stream the same way.
_SHELL_TOOLS = frozenset({"Bash", "mcp__workspace__bash"})


def _is_checklist_dispatch(t: dict[str, Any]) -> bool:
    return (
        t["name"] in ("Task", "Agent")
        and t["parent_tool_use_id"] is None
        # lstrip: a dispatched prompt can open with a newline (every one in the hostloop cassette does).
        and str(t["input"].get("prompt", "")).lstrip().startswith("CONTEXT: CHECKLIST")
    )


def checklist_dispatches(tool_uses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Main-thread CHECKLIST dispatches, in stream order (a corrective redo is a second one)."""
    return [t for t in tool_uses if _is_checklist_dispatch(t)]


def unit_economics_before_checklist(tool_uses: list[dict[str, Any]]) -> tuple[bool, str]:
    """Did the main thread run unit_economics.py before the FIRST CHECKLIST dispatch?

    Positions are indexes into the captured tool stream, which is stream order. A re-run of the
    producer after the dispatch (e.g. after a correction) is allowed; what is not is a checklist
    that was dispatched before any computed figures existed for it to read.
    """
    ue = [
        i
        for i, t in enumerate(tool_uses)
        if t["name"] in _SHELL_TOOLS
        and t["parent_tool_use_id"] is None
        and "unit_economics.py" in str(t["input"].get("command", ""))
    ]
    ck = [i for i, t in enumerate(tool_uses) if _is_checklist_dispatch(t)]
    if not ue:
        return False, "the main thread never ran unit_economics.py"
    if not ck:
        return False, "no CHECKLIST dispatch was made"
    return ue[0] < ck[0], f"first unit_economics.py call at tool #{ue[0]}, first CHECKLIST dispatch at tool #{ck[0]}"


def regenerate_checklist(sent: str, review_dir: Path, tool_uses: list[dict[str, Any]], dispatch_id: str) -> str:
    """The CHECKLIST prompt fmr_dispatch_prompt.py prints for one dispatch, with the arguments that run used.

    The identifiers come out of the sent prompt (RUN_ID, OUTPUT_PATH, the inputs.json line), so the
    comparison does not depend on how the skill derived them. A corrective redo's `--correction` (and a
    producer-rejected redo's `--detail-file`) come from the model's last generator call before the
    dispatch; the skill writes that call with shell variables, so the two this needs are resolved here.
    """
    run_id = sent.split("RUN_ID: ", 1)[1].split("\n", 1)[0].strip()
    handoff_agent = sent.split("OUTPUT_PATH: ", 1)[1].split("/checklist_output.json", 1)[0].strip()
    review_dir_agent = sent.split("Read inputs.json at ", 1)[1].split("/inputs.json", 1)[0].strip()
    handoff_dir = review_dir / "handoff" / run_id
    position = next(i for i, t in enumerate(tool_uses) if t["id"] == dispatch_id)
    calls = [
        str(t["input"].get("command", ""))
        for t in tool_uses[:position]
        if t["name"] in _SHELL_TOOLS
        and t["parent_tool_use_id"] is None
        and "fmr_dispatch_prompt.py" in str(t["input"].get("command", ""))
    ]
    extra: list[str] = []
    if calls:
        argv = shlex.split(calls[-1])
        for flag in ("--correction", "--detail-file"):
            if flag in argv and argv.index(flag) + 1 < len(argv):
                value = argv[argv.index(flag) + 1]
                for var, local in (("HANDOFF_DIR", handoff_dir), ("REVIEW_DIR", review_dir)):
                    value = value.replace("${" + var + "}", str(local)).replace("$" + var, str(local))
                extra += [flag, value]
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "fmr_dispatch_prompt.py"),
            "checklist",
            "--run-id",
            run_id,
            "--handoff-agent",
            handoff_agent,
            "--review-dir-agent",
            review_dir_agent,
            "--review-dir",
            str(review_dir),
            *extra,
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def checklist_read_paths(tool_uses: list[dict[str, Any]]) -> list[str]:
    """Every file the CHECKLIST sub-agent(s) opened with Read -- the tool stream, not its self-report."""
    parents = {t["id"] for t in checklist_dispatches(tool_uses)}
    return [
        str(t["input"].get("file_path", ""))
        for t in tool_uses
        if t["name"] == "Read" and t["parent_tool_use_id"] in parents
    ]


def metric_self_contradictions(report_json: dict) -> list[dict]:
    """METRIC_SELF_CONTRADICTION warnings on report.json's machine surface (under `validation`)."""
    return [
        w
        for w in (report_json.get("validation") or {}).get("warnings") or []
        if isinstance(w, dict) and w.get("code") == "METRIC_SELF_CONTRADICTION"
    ]


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

    cap = run_skill_capture(prompt, workdir, label="fmr")
    captured = cap.messages
    review_dir = locate_review_dir(workdir, "financial-model-review-*", captured, "financial-model-review")

    # The CHECKLIST prompt against what fmr_dispatch_prompt.py prints: recorded before any assert, so a
    # red leaves the same evidence a green does. Report only, besides the outcome gate (off by default).
    ck_dispatches = checklist_dispatches(cap.tool_uses)
    ck_report = dispatch_report(
        cap,
        ck_dispatches,
        lambda d: regenerate_checklist(str(d["input"].get("prompt", "")), review_dir, cap.tool_uses, str(d["id"])),
    )
    ck_report_text = format_dispatch_report("CHECKLIST", ck_report)
    print(f"[e2e:fmr] dispatch report:\n{ck_report_text}", flush=True)
    step_summary(f"### financial-model-review e2e: dispatches\n\n{ck_report_text}\n")
    assert_received_prompt(ck_report, "CHECKLIST")

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

    # === The checklist grades against the computed figures (Step 4 before Step 5). ===
    # Recorded before asserting, like the evidence above, so a red names what the stream showed.
    ordered, order_why = unit_economics_before_checklist(cap.tool_uses)
    ck_reads = checklist_read_paths(cap.tool_uses)
    contradictions = metric_self_contradictions(report_json)
    print(
        f"[e2e:fmr] step order: {ordered} ({order_why}); checklist reads: {ck_reads}; "
        f"METRIC_SELF_CONTRADICTION: {len(contradictions)}",
        flush=True,
    )
    step_summary(
        f"- unit_economics before CHECKLIST: {ordered} ({order_why})\n"
        f"- METRIC_SELF_CONTRADICTION warnings: {len(contradictions)}\n"
    )
    # (a) ORDER. A CHECKLIST dispatched before unit_economics.py ran has no computed figures to
    # read, so it computes its own burn multiple / payback / LTV:CAC -- the second number the
    # founder then sees beside the computed one. Only the tool stream shows the order; the
    # artifacts look the same either way.
    assert ordered, f"Step 4 must run before the CHECKLIST dispatch: {order_why}. Inspect {review_dir}"
    # (b) THE READ. The prompt TELLS the sub-agent to read unit_economics.json; that it did is a fact
    # only the sub-agent's own Read calls (parent_tool_use_id = the dispatch) can establish.
    assert any(p.endswith("unit_economics.json") for p in ck_reads), (
        f"the CHECKLIST sub-agent never opened unit_economics.json, so its metric criteria were "
        f"graded on figures it derived itself. It read: {ck_reads}"
    )
    # (c) THE OUTCOME. The defect the reorder exists to remove: a checklist figure that disagrees
    # with the computed one. Order and Read can both hold while the evidence still restates its own
    # number; this is the founder-visible consequence, judged by compose's own check.
    assert not contradictions, (
        "the checklist states a metric value that contradicts unit_economics.json: "
        f"{[w.get('message') for w in contradictions]}. Inspect {review_dir}"
    )

    # The founder's message CONTAINS the printed hand-over, whole: the report's own verdict (rating and
    # runway) in the report's words, not restated in chat. Regenerated from the model's OWN
    # fmr_closing_message.py call (its labels and paths), so a legitimate label choice cannot fail it,
    # and judged with the Stop hook's own rule. Two readings, as in the market-sizing lane: before any
    # Stop-hook block (did the printed message hold on its own) and at the end (what stayed on screen).
    closer_calls = [t for t in cap.calls("Bash") if "fmr_closing_message.py" in str(t["input"].get("command", ""))]
    assert closer_calls, "the run never printed the hand-over message"
    argv = shlex.split(str(closer_calls[-1]["input"]["command"]))
    deliverables = [argv[i + 1] for i, a in enumerate(argv) if a == "--deliverable" and i + 1 < len(argv)]
    assert deliverables, f"no --deliverable in the model's call: {argv}"
    printed = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "fmr_closing_message.py"),
            "--report",
            str(review_dir / "report.json"),
            "--link",
            "path",
            *sum((["--deliverable", d] for d in deliverables), []),
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    call_id = str(closer_calls[-1]["id"])
    before = cap.text_after(call_id, until_stop_feedback=True)
    after = cap.text_after(call_id)
    ok_before, why_before = _handover.contained(printed, before)
    ok_after, why_after = _handover.contained(printed, after)
    blocks = cap.stop_hook_blocks()
    print(
        f"[e2e:fmr] hand-over containment: before any Stop-hook block={ok_before} ({why_before or 'clean'}); "
        f"stop-hook blocks={blocks}; on screen at the end={ok_after} ({why_after or 'clean'})",
        flush=True,
    )
    assert ok_after, f"{why_after}\nprinted: {printed}\non screen: {after[-1500:]}"
    # A block after a message that already carried the hand-over is the hook misreading the session.
    assert not (ok_before and blocks), "the Stop hook blocked a message that already carried the hand-over"
