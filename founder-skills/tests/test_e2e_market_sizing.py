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

import importlib.util
import json
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from _e2e_harness import (
    PLUGIN_PATH,
    assert_coaching_commentary_landed,
    assert_run_id_parity,
    has_claude_auth,
    locate_review_dir,
    run_skill_capture,
)

# A two-page IMAGE-ONLY synthetic deck. Attached so the run exercises the branch that failed live:
# every one of the founder's PDFs on that run had no text layer, and the red team never opened them.
SCANNED_DECK = Path(__file__).resolve().parent / "fixtures" / "market-sizing" / "synthetic-deck-scanned.pdf"
SCRIPTS = PLUGIN_PATH / "skills" / "market-sizing" / "scripts"

_HANDOVER_CHECK = PLUGIN_PATH / "scripts" / "_handover_check.py"


def _load_handover_check() -> Any:
    """The containment rule the Stop hook runs, loaded by path so the lane and the hook share it."""
    spec = importlib.util.spec_from_file_location("_handover_check", _HANDOVER_CHECK)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_handover = _load_handover_check()


def _squash(text: str) -> str:
    """Whitespace-normalised: an added sentence or a dropped line still differs; a re-typed
    indent or a trailing newline does not."""
    return " ".join(text.split())


def _script(name: str, args: list[str]) -> str:
    r = subprocess.run([sys.executable, str(SCRIPTS / name), *args], capture_output=True, text=True, check=True)
    return r.stdout


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

    # The attached deck is Foobar HEALTH (a synthetic eldercare care-management company), and its
    # page 2 says the recurring rate rests on n=17 patient-months. The prompt states the same figure
    # on n=47 -- the misread from the run that motivated all of this -- so a red team that reads the
    # page has something to cite. The TAM is stated without a currency on purpose (see the module
    # docstring: that is the comparison_blocked shape).
    prompt = (
        "Use the market-sizing skill. Foobar Health is a fictional seed-stage company delivering "
        "clinician-led care management to seniors, distributed through employer benefit programs and "
        "reimbursed under care-management codes, priced per patient per month. Our deck is attached as "
        "a scanned PDF. Our recurring net-collectible rate is $203 per patient-month, measured over 47 "
        "patient-months from 30 patients. Our deck states a TAM of 3.2 billion. Size the market "
        "top-down AND bottom-up. Use 'foobar-health' as the slug and USD as the analysis currency. "
        "Don't ask clarifying questions — just run it end to end and produce the report."
    )

    cap = run_skill_capture(prompt, workdir, label="market-sizing", uploads=[SCANNED_DECK])
    captured = cap.messages
    review_dir = locate_review_dir(workdir, "market-sizing-*", captured, "market-sizing")

    # === The three boundaries the boundary-control work put under script control. ===
    #
    # (a0) The scored steps were DISPATCHED, not inlined. MEASURED 2026-09-22 on a surface that
    # serves the skill without its plugin (claude.ai, flat skill mount): every Context A step ran
    # inline, the model hand-wrote each hand-off file, and it graded its own 22-item checklist
    # 81.8% -- a report indistinguishable from a checked one. Step 0's preflight stops that surface;
    # this is the guard for a surface where dispatch EXISTS and the model inlines the step anyway,
    # which no artifact can show (a hand-off file looks the same whoever wrote it). The checklist is
    # the one that matters: it is the skill's own self-assessment, so a self-graded one is a score
    # with no second party in it at all.
    contexts = [
        str(t["input"].get("prompt", "")).split("\n", 1)[0] for t in cap.tool_uses if t["name"] in ("Task", "Agent")
    ]
    assert "CONTEXT: CHECKLIST" in contexts, (
        f"the checklist was not dispatched -- a self-graded score is not a score. Dispatched: {contexts}"
    )

    # (a) The red-team prompt is the GENERATED one, byte for byte. On the live run that motivated
    # this, the main thread hand-filled the template and added a "Key things worth attacking"
    # list from its own hypotheses; every finding mapped onto it. A sentinel check would let a
    # steer through in the middle; equality with a regeneration does not.
    dispatches = [
        t
        for t in cap.tool_uses
        if t["name"] in ("Task", "Agent") and t["input"].get("subagent_type") == "founder-skills:market-sizing-redteam"
    ]
    assert len(dispatches) == 1, f"expected one red-team dispatch, saw {len(dispatches)}"
    rt_dispatch = dispatches[0]
    dispatched = str(rt_dispatch["input"].get("prompt", ""))
    assert dispatched.startswith("CONTEXT: RED_TEAM\n"), dispatched[:200]
    # Regenerate from what the prompt itself declares plus the on-disk hand-off dir. The agent-
    # namespace forms are read back out of the prompt (OUTPUT_PATH, the inputs.json line), so the
    # comparison does not depend on how the skill derived them.
    run_id = dispatched.split("RUN_ID: ", 1)[1].split("\n", 1)[0]
    handoff_agent = dispatched.split("OUTPUT_PATH: ", 1)[1].split("/redteam_output.json", 1)[0]
    inputs_line = next(ln.strip() for ln in dispatched.splitlines() if ln.strip().endswith("/inputs.json"))
    analysis_dir_agent = inputs_line[: -len("/inputs.json")]
    handoff_dir = review_dir / "handoff" / run_id
    regenerated = _script(
        "dispatch_prompt.py",
        [
            "red_team",
            "--run-id",
            run_id,
            "--analysis-dir",
            str(review_dir),
            "--handoff-dir",
            str(handoff_dir),
            "--analysis-dir-agent",
            analysis_dir_agent,
            "--handoff-agent",
            handoff_agent,
        ],
    )
    assert _squash(dispatched) == _squash(regenerated), (
        "the dispatched red-team prompt is not the generated one -- something was added, removed or "
        "rewritten between the script and the Task call"
    )

    # (b) The red team actually OPENED the deck, and opened it BEFORE the artifacts -- SDK evidence,
    # not the self-report. "Documents first" is a sentence in the prompt; the tool stream is the fact.
    rt_reads = cap.calls("Read", parent=rt_dispatch["id"])
    read_paths = [str(t["input"].get("file_path", "")) for t in rt_reads]
    deck_idx = next((i for i, p in enumerate(read_paths) if SCANNED_DECK.name in p), None)
    artifact_idx = next((i for i, p in enumerate(read_paths) if p.endswith(".json")), None)
    assert deck_idx is not None, f"the red team never opened the deck; it read {read_paths}"
    assert artifact_idx is None or deck_idx < artifact_idx, (
        f"the red team read the artifacts before the deck: {read_paths}"
    )
    redteam = json.loads((review_dir / "redteam.json").read_text(encoding="utf-8"))
    # THE INVARIANT, not the outcome. `sources_unread == []` alone passes whether the review
    # DECLARED the deck read or the producer reconciled it from a citation, and on 2026-09-24 the
    # two runs differed: the first declared nothing (report told the founder four times that the
    # review never opened a file it quoted on page 2, once at high severity and once in the verdict
    # paragraph that carried the citation), the second declared correctly. So the gate could not
    # say which path produced its green. What must hold either way: a document a finding CITES was
    # opened, so it cannot be listed unopened.
    cited = {
        str(f["source_url"]).split("document:", 1)[1].split("#", 1)[0]
        for f in redteam["findings"]
        if str(f.get("source_url", "")).startswith("document:")
    }
    contradicted = sorted(cited & set(redteam["sources_unread"]))
    assert not contradicted, f"the report says these were never opened while a finding quotes them: {contradicted}"
    assert redteam["sources_unread"] == [], redteam["sources_unread"]
    assert SCANNED_DECK.name in redteam["sources_read"], redteam["sources_read"]
    # Which path produced the pass -- printed, never asserted, because both are legitimate. An
    # empty list means the review declared honestly and the reconciliation was not exercised; a
    # non-empty one means it fired and is the only live evidence that it works.
    print(
        "[e2e:market-sizing] sources_read reconciled from a citation: "
        f"{redteam['summary'].get('sources_read_from_citation')} "
        "(empty = the review declared them itself, so the reconciliation was NOT exercised)",
        flush=True,
    )
    # Evidence, not a gate: is the page misread cited? Printed so the write-up can quote it.
    doc_findings = [f for f in redteam["findings"] if str(f.get("source_url", "")).startswith("document:")]
    print(
        f"[e2e:market-sizing] document citations: {len(doc_findings)} -> "
        f"{[(f['source_url'], f['quote_verified']) for f in doc_findings]}",
        flush=True,
    )

    # (c) The founder's message CONTAINS the printed hand-over, whole, and carries nothing with a
    # digit outside it. Containment, not digit-absence: at hostloop the model kept one printed
    # line of four, rewrote two (one of them digit-free) and deleted one -- deletion and rewriting
    # are what a digit check cannot see. Regenerated from the model's OWN closing_message.py call
    # (its labels and paths), so a legitimate label choice cannot fail the check.
    cm_calls = [t for t in cap.calls("Bash") if "closing_message.py" in str(t["input"].get("command", ""))]
    assert cm_calls, "the run never printed the hand-over message"
    argv = shlex.split(str(cm_calls[-1]["input"]["command"]))
    deliverables = [argv[i + 1] for i, a in enumerate(argv) if a == "--deliverable" and i + 1 < len(argv)]
    assert deliverables, f"no --deliverable in the model's call: {argv}"
    printed = _script(
        "closing_message.py",
        [
            "--report",
            str(review_dir / "report.json"),
            "--link",
            "path",
            *sum((["--deliverable", d] for d in deliverables), []),
        ],
    )
    # The founder sees EVERY top-level assistant text after that call, not only the last message:
    # tool calls (present_files, TaskUpdate) routinely sit between the call and the final text,
    # and a Stop-hook block APPENDS a corrected message under the one it faulted -- it does not
    # retract it. Two readings, printed for the write-up: clean before any block (the printed
    # verdict alone held) and clean after the last block (the correction landed). The gate is
    # the second; the first is the number that says whether the hook was needed.
    call_id = str(cm_calls[-1]["id"])
    before = cap.text_after(call_id, until_stop_feedback=True)
    after = cap.text_after(call_id)
    ok_before, why_before = _handover.contained(printed, before)
    ok_after, why_after = _handover.contained(printed, after)
    blocks = cap.stop_hook_blocks()
    print(
        f"[e2e:market-sizing] hand-over containment: before any Stop-hook block={ok_before} "
        f"({why_before or 'clean'}); stop-hook blocks={blocks}; on screen at the end={ok_after} "
        f"({why_after or 'clean'})",
        flush=True,
    )
    # Print-only: the harness cuts message text at 90 chars, which hides whether a correction's
    # lead sentence arrived as dictated. Not a gate -- the lead's wording is the hook's to pin.
    if blocks:
        print(f"[e2e:market-sizing] on screen after the block: {after[:400]!r}", flush=True)
    assert ok_after, f"{why_after}\nprinted: {printed}\non screen: {after[-1500:]}"
    # ...and the verdict those figures belong to is the first paragraph of the report.
    report_md = json.loads((review_dir / "report.json").read_text(encoding="utf-8"))["report_markdown"]
    head = report_md[report_md.index("## Executive Summary") : report_md.index("| Metric | Value | Method |")]
    assert "An outside review" in head or "No adversarial review ran" in head, head

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

    # REMOVED: a scan of the whole report.md for the word "cross-validation".
    #
    # It read as a guard on compose's own vocabulary, but report.md carries four model-authored
    # free-text channels -- methodology.rationale, accepted_warnings[].reason, checklist item
    # notes, and the coaching commentary -- and the scan could not tell them apart from compose's
    # labels. So it gated a paid release on a model's word choice, and did it badly in both
    # directions: it failed a run whose rationale said "cross-validation", and passed one whose
    # rationale said "cross-check ... from two independent directions", which asserts exactly the
    # independence the term is banned for claiming.
    #
    # Measured over the deduplicated live-run corpus, about a third of rationales carry the exact
    # spelling and most state the idea some other way, so this was a coin-flip on every run.
    # `524619c` removed the same shape from the financial-model-review lane after it failed 2 of 3
    # CI runs.
    #
    # Compose's own labels are guarded for free, on every PR, by
    # test_market_sizing.py::test_methodology_never_claims_the_two_builds_validate_each_other and
    # ::test_a_rationale_passes_through_verbatim_while_compose_labels_stay_clean -- the second of
    # which pins the SPLIT this assert conflated. The real detector for the underlying claim is
    # not a word list at all: `_shared_input_values` decides independence from value identity and
    # factor overlap, and reaches report.md, report.html and the coaching payload.

    # A converted figure must never be labelled with the wrong currency, and an unstated
    # one must not be labelled at all. Both were shipped defects.
    assert "$" not in json.dumps(payload.get("comparison_blocked")), "currency marker inside the blocked payload"

    summary = payload.get("summary")
    assert isinstance(summary, dict) and summary, "no summary in the coaching payload"
    for metric in ("tam", "sam", "som"):
        assert metric in payload, f"coaching payload is missing the headline {metric.upper()}"

    # The band and the boolean, on the surface the sub-agent actually reads. The contract
    # tests pin that these keys are emitted and named on both prompts; only a live run can
    # show them arriving in a payload a coach then works from. Without these assertions this
    # lane is green whether or not the change landed, and a paid run proves nothing about it.
    assert payload["schema_version"] == "v0.7.0-market-sizing", (
        f"coaching payload is at {payload.get('schema_version')!r}; the band change bumped it"
    )
    assert summary.get("overall_status") in {"strong", "solid", "needs_work", "major_revision"}, (
        f"overall_status is {summary.get('overall_status')!r}, not a fleet band — the boolean "
        "vocabulary is what the band change replaced"
    )
    assert isinstance(summary.get("all_pass"), bool), (
        f"all_pass is {summary.get('all_pass')!r}; the coach cannot tell whether anything is "
        "still outstanding without it"
    )
    # The two must be independently derived, not one computed from the other: `all_pass` is
    # true exactly when nothing failed, whatever band the score lands in.
    assert summary["all_pass"] == (summary.get("fail") == 0), f"all_pass disagrees with the failure count: {summary}"

    # The checklist warnings are mutually exclusive and split on the failure count. Both
    # present would show a founder the same failures twice under opposite acceptance rules.
    report = json.loads((review_dir / "report.json").read_text(encoding="utf-8"))
    codes = [w.get("code") for w in report.get("validation", {}).get("warnings", [])]
    assert not ("CHECKLIST_FAILURES" in codes and "CHECKLIST_FAILURES_CRITICAL" in codes), (
        f"both checklist warnings fired: {codes}"
    )
    for warning in report.get("validation", {}).get("warnings", []):
        if warning.get("code") == "CHECKLIST_FAILURES":
            assert warning.get("severity") in {"medium", "acknowledged"}, (
                "CHECKLIST_FAILURES is high again, so a content finding cannot be accepted "
                "with a stated reason and the only way past it is to re-run until it goes away"
            )
        if warning.get("code") == "CHECKLIST_FAILURES_CRITICAL":
            assert warning.get("severity") == "high", warning

    # THE SEVERITY CHECKS ABOVE ONLY RUN IF A WARNING HAPPENS TO APPEAR, so on a clean run
    # they assert nothing and reverting to the old absolute cutoff would still pass. This
    # is the unconditional half: whatever the run scored, the band and the warning must
    # agree about whether the checklist could reach `solid`.
    summary_fail = summary.get("fail")
    summary_pass = summary.get("pass")
    assert isinstance(summary_fail, int) and isinstance(summary_pass, int), summary
    applicable = summary_pass + summary_fail
    below_solid = applicable > 0 and (summary_pass / applicable) * 100 < 70.0
    assert ("CHECKLIST_FAILURES_CRITICAL" in codes) == below_solid, (
        f"the critical warning and the band disagree: pass={summary_pass} fail={summary_fail} "
        f"applicable={applicable} below_solid={below_solid} codes={codes}"
    )
    assert ("CHECKLIST_FAILURES" in codes) == (summary_fail > 0 and not below_solid), (
        f"the acceptable warning does not match the failure count: {summary} {codes}"
    )

    assert_run_id_parity(
        review_dir,
        ["inputs.json", "sizing.json", "validation.json", "sensitivity.json", "checklist.json", "report.json"],
    )
