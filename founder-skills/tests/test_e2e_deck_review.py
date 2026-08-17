"""End-to-end smoke: drive deck-review against the synthetic fixture deck.

**Wall time: ~15 minutes** (one full Phase A → checklist → compose → coaching
chain with sequential `Task` dispatches; each dispatch is 30-90s and the
chain has 5-7 of them). Earlier docstring revisions cited 60-180s — that
was a guess; first real run measured 928s (15:28). Realistic range: 5-20
min depending on LLM dispatch decisions. Update this docstring after
calibrating across more runs.

**Cost** (calibrate empirically before pinning):
  - On `ANTHROPIC_API_KEY`: ~$5-15 per run (revise upward from earlier
    $2-5 projection based on the realistic dispatch count). Set the
    `ANTHROPIC_API_KEY_CI` monthly spend cap accordingly.
  - On a Claude subscription: a single run consumes a meaningful share
    of the per-window message budget. Subscription rate limits and
    automated-use terms change — check Anthropic's current policy
    before relying on subscription auth for sustained CI. For local-dev
    runs it's fine; for per-PR CI, the API path is the durable choice.

**Run with `-s` to see live progress** (which auth was detected, each SDK
message as it arrives, tool calls, etc.). Without `-s`, pytest captures
stdout and the test looks silent for the 5-20 min the SDK takes — but the
captured output is still printed if the test fails. Recommended invocation:

    uv run pytest founder-skills/tests/test_e2e_deck_review.py -v -m e2e --tb=short -s

Auth precedence (the SDK shells out to `claude` CLI which picks the first
available):
  1. ANTHROPIC_API_KEY env var
  2. CLAUDE_CODE_OAUTH_TOKEN env var (long-lived subscription token from
     `claude setup-token`)
  3. Local subscription auth via `~/.claude/.credentials.json` (after
     `claude /login`)

This test skips only when NONE of the three are available.

NOTE: as of v0.4.4 + claude-agent-sdk==0.1.80, the SDK invocation pattern
below is documented but has NOT been empirically verified end-to-end. The
test author should run Task 9 Step 1 (manual SDK verification) before
treating this test as load-bearing CI signal. See the plan at
docs/plans/2026-05-09-skill-quality-ci.md Task 9.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "founder-skills" / "tests" / "fixtures"
DECK_FIXTURE = FIXTURES / "decks" / "synthetic-seed-deck.txt"
GOLDEN = FIXTURES / "golden" / "deck-review" / "synthetic-seed-deck.expected.json"


def _detect_auth_kind() -> str:
    """Return a human-readable label for which auth path is active.

    Used purely for progress reporting — does not affect SDK behavior.
    """
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "ANTHROPIC_API_KEY env var (per-token API)"
    if os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"):
        return "CLAUDE_CODE_OAUTH_TOKEN env var (subscription, long-lived token)"
    if sys.platform == "darwin":
        try:
            r = subprocess.run(
                ["security", "find-generic-password", "-s", "Claude Code-credentials"],
                capture_output=True,
                timeout=5,
            )
            if r.returncode == 0:
                return "macOS Keychain entry 'Claude Code-credentials' (subscription, after `claude /login`)"
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
    if (Path.home() / ".claude" / ".credentials.json").is_file():
        return "~/.claude/.credentials.json (subscription, after `claude /login`)"
    return "(none — test should have skipped)"


def _summarize_sdk_message(msg: object) -> str:
    """One-line summary of an SDK message for live progress output.

    Defensively walks attributes so it works across SDK message-class
    variations. Falls back to truncated str(msg) if nothing matches.
    """
    type_name = type(msg).__name__
    # Common shapes: AssistantMessage / UserMessage have `content` (list of
    # content blocks). ResultMessage has `result`/`subtype`. SystemMessage
    # has `subtype`/`data`. ToolUseBlock has `name`/`input`. ToolResultBlock
    # has `tool_use_id`/`content`.
    content = getattr(msg, "content", None)
    if isinstance(content, list) and content:
        # Summarize each block in the message
        block_summaries: list[str] = []
        for block in content:
            block_type = type(block).__name__
            if block_type == "TextBlock":
                text = getattr(block, "text", "")
                snippet = text.strip().replace("\n", " ")[:100]
                block_summaries.append(f"text: {snippet}{'...' if len(text) > 100 else ''}")
            elif block_type == "ThinkingBlock":
                text = getattr(block, "thinking", "")
                snippet = text.strip().replace("\n", " ")[:80]
                block_summaries.append(f"thinking: {snippet}{'...' if len(text) > 80 else ''}")
            elif block_type == "ToolUseBlock":
                tool_name = getattr(block, "name", "?")
                tool_input = getattr(block, "input", {})
                # Extract useful per-tool field
                if tool_name == "Bash":
                    cmd = (tool_input or {}).get("command", "")[:80]
                    block_summaries.append(f"→ Bash: {cmd}{'...' if len(cmd) >= 80 else ''}")
                elif tool_name == "Read":
                    path = (tool_input or {}).get("file_path", "")
                    block_summaries.append(f"→ Read: {path}")
                elif tool_name == "Write":
                    path = (tool_input or {}).get("file_path", "")
                    block_summaries.append(f"→ Write: {path}")
                elif tool_name == "Edit":
                    path = (tool_input or {}).get("file_path", "")
                    block_summaries.append(f"→ Edit: {path}")
                elif tool_name == "Task":
                    desc = (tool_input or {}).get("description", "")[:60]
                    sub = (tool_input or {}).get("subagent_type", "?")
                    block_summaries.append(f"→ Task[{sub}]: {desc}")
                elif tool_name == "Skill":
                    skill_name = (tool_input or {}).get("name", "?")
                    block_summaries.append(f"→ Skill: {skill_name}")
                else:
                    block_summaries.append(f"→ {tool_name}")
            elif block_type == "ToolResultBlock":
                tool_id = getattr(block, "tool_use_id", "?")[:8]
                is_err = getattr(block, "is_error", False)
                marker = "✗" if is_err else "✓"
                # Tool results can be long — just note success/error
                block_summaries.append(f"← {marker} result for {tool_id}")
            else:
                block_summaries.append(f"[{block_type}]")
        return f"{type_name}: " + " | ".join(block_summaries)
    # Fallback: dig for common scalar fields
    subtype = getattr(msg, "subtype", None)
    if subtype:
        result = getattr(msg, "result", None) or getattr(msg, "data", None)
        result_snippet = str(result)[:100] if result else ""
        return f"{type_name}({subtype}){f': {result_snippet}' if result_snippet else ''}"
    return f"{type_name}: {str(msg)[:120]}"


PAID_OPT_IN_ENV = "RUN_PAID_E2E"


def _paid_run_authorized() -> bool:
    """Has anyone actually ASKED for a billed run? A credential is not permission.

    Duplicated from `_e2e_harness.paid_run_authorized` because this lane deliberately does
    not use the shared harness (it is the one the release tag gates on). The duplication is
    the failure point to watch: a gate present in one of two copies is exactly the shape of
    the incident this closes — an audit ran the default suite on a Mac and started two paid
    runs, because credential detection was the only question anyone asked.
    """
    return os.environ.get(PAID_OPT_IN_ENV, "").strip().lower() in {"1", "true", "yes"}


def _has_claude_auth() -> bool:
    """True if a paid run was authorized AND any of the SDK's auth paths is available.

    Order of preference inside the SDK matches:
      1. ANTHROPIC_API_KEY env var (per-token API billing)
      2. CLAUDE_CODE_OAUTH_TOKEN env var (subscription, long-lived token
         from `claude setup-token`)
      3. Local subscription auth (after `claude /login`):
         - macOS:        Keychain entry under service "Claude Code-credentials"
                         (queried via `security find-generic-password`; this
                         only checks attribute existence — no decryption, no
                         keychain unlock prompt)
         - Linux/Win:    ~/.claude/.credentials.json
    """
    if not _paid_run_authorized():
        return False
    if os.environ.get("ANTHROPIC_API_KEY"):
        return True
    if os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"):
        return True
    if sys.platform == "darwin":
        # macOS: Claude Code stores subscription tokens in the login Keychain
        # under service "Claude Code-credentials". `security find-generic-password`
        # exits 0 if the entry exists, non-zero otherwise — no decryption, no
        # interactive prompt.
        try:
            result = subprocess.run(
                ["security", "find-generic-password", "-s", "Claude Code-credentials"],
                capture_output=True,
                timeout=5,
            )
            if result.returncode == 0:
                return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
    # Linux / Windows / fallback: check the credentials JSON file
    creds = Path.home() / ".claude" / ".credentials.json"
    return creds.is_file()


@pytest.mark.e2e
@pytest.mark.skipif(
    not _has_claude_auth(),
    reason=(
        "Paid end-to-end smoke: set RUN_PAID_E2E=1 to authorize a billed run, AND have "
        "Claude auth (ANTHROPIC_API_KEY, CLAUDE_CODE_OAUTH_TOKEN, or `claude /login`). "
        "The opt-in is separate on purpose — a credential says a run CAN happen, not that "
        "it may."
    ),
)
def test_deck_review_smoke(tmp_path: Path) -> None:
    """Run deck-review against the synthetic fixture; assert structural signals."""
    # Imports are inside the test so test collection works without the SDK
    # installed (CI install handles it via the dev extras).
    from claude_agent_sdk import ClaudeAgentOptions, query

    # Stage a workspace; the skill creates artifacts/ under cwd.
    workdir = tmp_path / "workspace"
    workdir.mkdir()
    deck_dst = workdir / "synthetic-seed-deck.txt"
    shutil.copy(DECK_FIXTURE, deck_dst)

    plugin_path = REPO_ROOT / "founder-skills"

    options = ClaudeAgentOptions(  # type: ignore[call-arg]
        cwd=str(workdir),
        # Plugin discovery: `plugins=[{type, path}]` is the SDK's plugin loader.
        # `setting_sources` is for filesystem-based Skill discovery (~/.claude/
        # skills/ + .claude/skills/) — we set it to [] since founder-skills is
        # plugin-bundled, not filesystem-discovered.
        plugins=[{"type": "local", "path": str(plugin_path)}],
        setting_sources=[],
        # Defensively enable all loaded Skills (SDK Troubleshooting: with
        # setting_sources=[] and no skills=, no Skills may be enabled).
        skills="all",
        # Allow what the inline-skill model needs end-to-end:
        allowed_tools=["Bash", "Read", "Write", "Edit", "Glob", "Grep", "Task", "Skill"],
        # SKILL.md bodies reference ${CLAUDE_PLUGIN_ROOT} (v0.4.3 invariant).
        # In production Claude Code/Cowork, the plugin content expander
        # substitutes ${CLAUDE_PLUGIN_ROOT} at skill-load time — production
        # doesn't depend on the SessionStart hook firing. The SDK's plugin
        # loader does NOT run that expander, so we set the env var here as
        # the SDK-harness-side workaround. The production-side invariant
        # (no SKILL.md may depend on the hook firing) is enforced by Task 3's
        # test_skill_md_does_not_depend_on_session_start_hook.
        # Also merge with parent env so PATH/HOME/etc. survive — without
        # them, Bash steps in SKILL.md fail at `python3`/`cat`/`mkdir`
        # resolution.
        env={
            **os.environ,
            "CLAUDE_PLUGIN_ROOT": str(plugin_path),
            # Byte-stream idle watchdog, raised from its default to 10 minutes.
            #
            # The CLI the SDK spawns runs TWO idle timeouts. The message-level one
            # (`CLAUDE_STREAM_IDLE_TIMEOUT_MS`) is floored at 5 min. The byte-level one
            # is separate, is NOT floored, and for first-party auth resolves to its own
            # constant that a remote config gate can also lower. That is the one that
            # fires here, and an explicit value for this variable beats both the default
            # and the gate. The CLI clamps it to [1 ms, 30 min].
            #
            # Measured on this test, n=1 each way: at the default it aborted after 61
            # messages with `API Error: Stream idle timeout - partial response received`,
            # while composing the SLIDE_REVIEWS dispatch — this skill's largest tool_use
            # block, since it inlines the whole deck plus the instruction body. With this
            # value set, the same test ran to completion in 189 messages. One failure and
            # one pass is consistent with the threshold being the cause but does NOT
            # establish it; a transient upstream stall that happened to clear on the retry
            # fits the same evidence. Treat the value as cheap insurance, not a proven fix,
            # and do not weaken it on the strength of one green run.
            #
            # Without this, the failure surfaces through the SDK as
            # `Exception: Claude Code returned an error result: success` — a
            # contradiction that says nothing about the cause and costs ~8 minutes to
            # reach. The value is set here rather than left to the caller's environment
            # because CI cannot run this test, so every run is a human running it once
            # and having no reason to know any of the above.
            #
            # `**os.environ` above is spread FIRST, so a bare literal here would silently
            # override a caller who set this deliberately. Read through instead: this is a
            # default, not a pin.
            "CLAUDE_BYTE_STREAM_IDLE_TIMEOUT_MS": os.environ.get("CLAUDE_BYTE_STREAM_IDLE_TIMEOUT_MS", "600000"),
        },
    )

    # The stage is stated as MY answer, not as background colour. The gate's documented
    # auto-satisfy branch fires only when Step 1 captured a stage from the founder and the
    # detected stage matches it; a prompt that merely mentions "seed-stage" leaves the agent
    # to decide whether it has an answer, so the run exercises an ambiguous path instead of
    # the sanctioned one. `authorize()` refuses auto-satisfy against a low-confidence
    # profile, which is a legitimate refusal -- this wording makes a refusal here mean
    # "detection was not confident", not "nobody said what stage this is".
    prompt = (
        f"Use the deck-review skill to review the synthetic deck at "
        f"{deck_dst}. It's a fictional SaaS company called Acmecorp. "
        f"Use 'acmecorp' as the slug. I am the founder and the stage is "
        f"seed — treat that as my answer if you would otherwise ask. "
        f"Don't ask clarifying questions — just run."
    )

    # Capture the SDK message stream so failure diagnostics can include it.
    captured_messages: list[str] = []

    # Live progress preamble — visible with `pytest -s`. Without `-s`,
    # pytest captures stdout silently but reprints it on failure.
    print(f"\n[e2e] Auth detected: {_detect_auth_kind()}", flush=True)
    print(f"[e2e] Plugin path:   {plugin_path}", flush=True)
    print(f"[e2e] Workdir:       {workdir}", flush=True)
    print(f"[e2e] Deck fixture:  {deck_dst.name}", flush=True)
    print(f"[e2e] Prompt:        {prompt[:140]}{'...' if len(prompt) > 140 else ''}", flush=True)
    print("[e2e] --- starting SDK query (60-180s typical) ---", flush=True)

    async def run() -> None:
        msg_count = 0
        async for msg in query(prompt=prompt, options=options):
            msg_count += 1
            captured_messages.append(str(msg))
            print(f"[e2e #{msg_count:03d}] {_summarize_sdk_message(msg)}", flush=True)
        print(f"[e2e] --- SDK loop complete ({msg_count} messages) ---", flush=True)

    asyncio.run(run())

    # Locate the review directory the skill produced.
    artifacts_root = workdir / "artifacts"
    review_dirs = list(artifacts_root.glob("deck-review-*"))
    if not review_dirs:
        # Build a useful diagnostic dump — failure here is almost always one of:
        # (1) skill never invoked, (2) plugin not loaded, (3) Bash subprocess
        # crashed at path resolution, (4) Task tool not exposed.
        workdir_contents = sorted(p.relative_to(workdir) for p in workdir.rglob("*"))
        last_messages = "\n".join(captured_messages[-10:]) if captured_messages else "(no messages)"
        plugin_smd = REPO_ROOT / "founder-skills" / "skills" / "deck-review" / "SKILL.md"
        smd_readable = plugin_smd.is_file() and os.access(plugin_smd, os.R_OK)
        env_has_root = "CLAUDE_PLUGIN_ROOT" in os.environ
        truncation_note = " (truncated)" if len(workdir_contents) > 30 else ""
        raise AssertionError(
            f"deck-review smoke produced no artifacts under {artifacts_root}.\n"
            f"\n"
            f"Diagnostics:\n"
            f"  workdir contents: {workdir_contents[:30]}{truncation_note}\n"
            f"  SKILL.md readable: {smd_readable} ({plugin_smd})\n"
            f"  CLAUDE_PLUGIN_ROOT in parent env: {env_has_root}\n"
            f"  total SDK messages received: {len(captured_messages)}\n"
            f"  last 10 messages:\n{last_messages}\n"
            f"\n"
            f"Likely causes:\n"
            f"  1. Model never invoked deck-review skill (look at messages above)\n"
            f"  2. Plugin not discovered (check `plugins=[...]` API of installed SDK)\n"
            f"  3. Bash subprocess failed at path resolution (check env merge)\n"
            f"  4. Task tool not exposed (deck-review's Step 4/5/7 dispatches failed)\n"
        )
    review_dir = review_dirs[0]

    expected = json.loads(GOLDEN.read_text())
    a = expected["assertions"]

    # 1. Required outputs
    if a.get("report_json_exists"):
        assert (review_dir / "report.json").exists()
    if a.get("report_md_exists"):
        assert (review_dir / "report.md").exists()

    # 2. coaching_payload shape (Phase B already validates this on synthetic
    # artifacts; here we validate it on real LLM-driven output)
    report = json.loads((review_dir / "report.json").read_text())
    if a.get("coaching_payload_present"):
        assert "coaching_payload" in report
        assert "summary" in report["coaching_payload"]

    # 3. score_pct in expected range (LLM variation tolerated by range).
    # Per v0.4.2 producer schema parity, summary lives at
    # `coaching_payload.summary`, NOT at top-level `report["summary"]`.
    # All 5 skills' compose scripts emit the summary under coaching_payload.
    summary = report.get("coaching_payload", {}).get("summary", {})
    score = summary.get("score_pct")
    if a.get("score_pct_range"):
        lo, hi = a["score_pct_range"]
        assert score is not None and lo <= score <= hi, (
            f"score_pct {score} outside expected range [{lo}, {hi}].\n"
            f"  coaching_payload.summary keys: {sorted(summary.keys())}\n"
            f"  report.json top-level keys:    {sorted(report.keys())}\n"
            f"  review_dir for inspection:     {review_dir}"
        )

    # 4. overall_status in expected set
    if a.get("overall_status_in"):
        assert summary.get("overall_status") in a["overall_status_in"], (
            f"overall_status {summary.get('overall_status')!r} not in {a['overall_status_in']}.\n"
            f"  coaching_payload.summary keys: {sorted(summary.keys())}\n"
            f"  review_dir for inspection:     {review_dir}"
        )

    # 5. run_id parity across artifacts
    #
    # `continue` on a missing artifact is deliberate HERE and dangerous everywhere else: this
    # check is about agreement among the artifacts that exist, and existence is asserted
    # separately below. It used to be the only check over this list, which meant a run that
    # produced three artifacts instead of eight passed it by having nothing to disagree with.
    if a.get("all_artifacts_have_run_id"):
        run_ids = set()
        for art in [
            "deck_inventory.json",
            "stage_profile.json",
            "slide_reviews.json",
            "checklist.json",
            "report.json",
            "ledger.json",
            "reconciliation.json",
            "gate_state.json",
        ]:
            p = review_dir / art
            if not p.exists():
                continue
            data = json.loads(p.read_text())
            meta = data.get("metadata", {}) if isinstance(data, dict) else {}
            rid = meta.get("run_id")
            if rid:
                run_ids.add(rid)
        assert len(run_ids) == 1, f"run_id parity broken; artifacts had {sorted(run_ids)}"

    # ------------------------------------------------------------------------------
    # 6. The checks below were declared in the golden file and never evaluated, plus the
    #    gate and numeric-chain coverage this lane lacked entirely.
    #
    # COLLECT-THEN-FAIL, not assert-and-abort. This is the only paid lane that exercises
    # the gate state machine and the numeric chain against a real model, so one run has to
    # answer every question we have. An `assert` at the first problem answers one and bills
    # for the rest. Every check appends to `failures`; the test fails at the end with all of
    # them, and prints the observed values either way.
    # ------------------------------------------------------------------------------
    failures: list[str] = []
    observed: dict[str, object] = {}

    def _artifact(name: str) -> dict | None:
        path = review_dir / name
        if not path.exists():
            return None
        try:
            loaded = json.loads(path.read_text())
        except json.JSONDecodeError as exc:
            failures.append(f"{name} is not parseable JSON: {exc}")
            return None
        return loaded if isinstance(loaded, dict) else None

    # 6a. The gate was recorded, and recorded coherently.
    #
    # A false REFUSAL cannot reach here -- it stops compose, so the "no artifacts" branch
    # above fires with diagnostics. What this catches is the opposite: a report produced
    # without an authorized gate, which is the defect class that reached a founder once
    # (someone answered `Stop review` and got a report).
    gate = _artifact("gate_state.json")
    profile = _artifact("stage_profile.json")
    if gate is None:
        failures.append(
            "no gate_state.json: a report was produced without a recorded stage-confirmation "
            "gate, so nothing establishes that the profile it graded against was confirmed"
        )
    else:
        observed["gate.gate_id"] = gate.get("gate_id")
        observed["gate.answer"] = gate.get("answer")
        observed["gate.answer_source"] = gate.get("answer_source")
        observed["gate.confirmed_stage"] = gate.get("confirmed_stage")
        if gate.get("answer_source") not in ("founder", "auto_satisfied"):
            failures.append(
                f"gate answer_source is {gate.get('answer_source')!r}; a report may only be "
                "composed against an answer whose origin is recorded"
            )
        if not gate.get("answer"):
            failures.append("gate_state.json carries no answer, yet a report was composed")
        # The gate binds to the profile it confirmed. An agreeing pair is the whole point of
        # `confirmed_stage`; a disagreeing one means the report was graded against a profile
        # the founder never saw.
        if profile is not None:
            # `detected_stage`, NOT `stage` -- the field this comparison exists for, and the
            # one gate_state.schema.json names in `confirmed_stage`'s own description. Reading
            # `stage` returns None, which short-circuits the comparison and makes the check
            # pass on every input, including the defect it was written for. Both fields carry
            # the same five-token enum, verified against the two schemas.
            observed["profile.detected_stage"] = profile.get("detected_stage")
            observed["profile.confidence"] = profile.get("confidence")
            confirmed = gate.get("confirmed_stage")
            detected = profile.get("detected_stage")
            if confirmed and detected and confirmed != detected:
                failures.append(
                    f"gate confirmed_stage {confirmed!r} but the graded profile is {detected!r} "
                    "— the report was graded against a profile the gate did not confirm"
                )
            if not confirmed:
                failures.append(
                    "gate_state.json carries no confirmed_stage, so nothing binds the answer to "
                    "the profile the report was graded against"
                )

    # 6b. Steps 3.5-3.8 actually ran. Must-exist, not skipped: the numeric chain is gated on
    # the producer of its deliverable precisely because a step whose only downstream consumer
    # is a warning gets skipped in silence.
    for art in ("ledger.json", "second_read.json", "reconciliation.json"):
        if not (review_dir / art).exists():
            failures.append(f"{art} missing: the numeric chain (Steps 3.5-3.8) did not run")

    recon = _artifact("reconciliation.json")
    if recon is not None:
        status = recon.get("status")
        observed["reconciliation.status"] = status
        observed["reconciliation.relations_surfaced"] = len(recon.get("relations") or [])
        for key in ("dates_excluded", "quote_quality"):
            observed[f"reconciliation.{key}"] = recon.get(key)
        if status not in ("checked", "no_figures", "gate_failed"):
            failures.append(f"reconciliation status {status!r} is not one of the three legal values")
        # NOT asserted: that the status is `checked`. The deck states five figures, so
        # `checked` is what a good extraction yields -- but whether the sub-agent finds two
        # verifiable ones is model-dependent and has never been measured on this fixture.
        # Recorded as an observation to calibrate against, per the golden file's own rule that
        # a range is re-derived from runs rather than guessed.

    ledger = _artifact("ledger.json")
    if ledger is not None:
        observed["ledger.figures"] = len(ledger.get("figures") or [])

    # 6c. `schema_validation_passes` -- declared in the golden file, never evaluated. Validate
    # the LIVE artifacts against the same schemas the fixture sweep uses.
    if a.get("schema_validation_passes"):
        from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

        schema_dir = REPO_ROOT / "founder-skills" / "skills" / "deck-review" / "references" / "schemas"
        checked_any = False
        for schema_path in sorted(schema_dir.glob("*.schema.json")):
            artifact_path = review_dir / f"{schema_path.name.removesuffix('.schema.json')}.json"
            if not artifact_path.exists():
                continue
            checked_any = True
            errors = sorted(
                Draft202012Validator(json.loads(schema_path.read_text())).iter_errors(
                    json.loads(artifact_path.read_text())
                ),
                key=lambda e: list(e.absolute_path),
            )
            if errors:
                detail = "; ".join(f"{list(e.absolute_path) or '<root>'}: {e.message}" for e in errors[:4])
                failures.append(f"{artifact_path.name} violates its schema: {detail}")
        if not checked_any:
            failures.append("schema_validation_passes was requested but no artifact matched a schema")

    # 6d. `no_high_severity_warnings_other_than` -- declared, never evaluated. It catches a
    # rejected artifact accepted anyway (ARTIFACT_INVALID) and a stale one reused.
    #
    # It does NOT catch a gate bypassed via `--ungated`: that code is severity MEDIUM
    # (compose_report.py:137), so a severity filter steps straight over it. Checked separately
    # below rather than by promoting the code -- `--ungated` is a documented mode and its
    # severity is a product decision, not something a test should change as a side effect.
    allowed = a.get("no_high_severity_warnings_other_than")
    if allowed is not None:
        warnings = report.get("validation", {}).get("warnings", [])
        observed["validation.status"] = report.get("validation", {}).get("status")
        observed["validation.warning_codes"] = sorted({str(w.get("code")) for w in warnings if isinstance(w, dict)})
        unexpected = sorted(
            {
                str(w.get("code"))
                for w in warnings
                if isinstance(w, dict) and w.get("severity") == "high" and w.get("code") not in allowed
            }
        )
        if unexpected:
            failures.append(f"unexpected high-severity warnings: {unexpected} (allowed: {allowed})")

        # This lane exists to exercise the GATED path. A report composed with `--ungated` is a
        # legitimate product mode and a failed test objective.
        if any(isinstance(w, dict) and w.get("code") == "UNGATED_REVIEW" for w in warnings):
            failures.append(
                "report carries UNGATED_REVIEW: composed with the gate bypassed, so this run "
                "says nothing about whether gate authorization works"
            )

    # 6e. `expected_failed_categories_min_count` -- declared, never evaluated.
    min_failed = a.get("expected_failed_categories_min_count")
    if min_failed is not None:
        checklist = _artifact("checklist.json")
        if checklist is None:
            failures.append("expected_failed_categories_min_count requested but checklist.json is absent")
        else:
            # `summary.by_category`, NOT a `categories` list. Reading a key the producer does
            # not write yields an empty list, which fails a >= 3 check and reds a paid run on
            # a shape error -- the same field-name class as the numeral fuse. Verified against
            # tests/fixtures/deck-review/checklist.json before this ran.
            summary_block = checklist.get("summary") or {}
            by_category = summary_block.get("by_category") or {}
            failed = sorted(
                name
                for name, counts in by_category.items()
                if isinstance(counts, dict) and (counts.get("fail") or 0) > 0
            )
            observed["checklist.failed_categories"] = failed
            observed["checklist.failed_items"] = summary_block.get("fail")
            observed["checklist.warned_items"] = summary_block.get("warn")
            if len(failed) < min_failed:
                failures.append(
                    f"only {len(failed)} categories carry a failure ({failed}); the fixture is a "
                    f"6-slide stub covering 5 of 35 items, so at least {min_failed} were expected. "
                    f"Failed ITEMS: {summary_block.get('fail')!r} — if that number is healthy the "
                    "fixture's assertion means items, not categories, and the golden file should say so"
                )

    print("\n[e2e] ---- observed values (calibration data for this lane) ----", flush=True)
    for key in sorted(observed):
        print(f"[e2e]   {key} = {observed[key]!r}", flush=True)
    print(f"[e2e]   artifacts = {sorted(p.name for p in review_dir.glob('*.json'))}", flush=True)
    print("[e2e] -----------------------------------------------------------", flush=True)

    assert not failures, "live deck-review run failed {} check(s):\n{}\n\nreview_dir: {}".format(
        len(failures), "\n".join(f"  - {f}" for f in failures), review_dir
    )
