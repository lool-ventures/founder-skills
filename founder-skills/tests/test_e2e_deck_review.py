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

The SDK version is pinned in pyproject.toml's dev extra; this lane builds its own
options and message loop rather than using `_e2e_harness.py`.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

# What this lane takes from the shared harness: account connectors off, and the post-run check that they
# were (a safety control is not a place for a second copy that can drift); and the pure readers of the run
# status a host sees (no SDK, no options). Those it RECORDS rather than failing on: it is the release gate,
# and a run status not yet complete beside a correct report would red a tag on model pacing. Harden after
# two tagged releases. It also folds the stream into a RunCapture for the CHECKLIST dispatch report, whose
# two dispatch assertions are GATED, as on the FMR and market-sizing lanes, along with a PreToolUse response
# for every CHECKLIST dispatch (see `_record_checklist_dispatches`).
from _e2e_harness import (
    CONNECTOR_ISOLATION_ENV,
    RunCapture,
    SdkStreamFile,
    assert_dispatch_outcomes,
    assert_no_account_connectors,
    assert_received_prompt,
    compose_record_problems,
    connector_isolation_options,
    dispatch_report,
    format_dispatch_report,
    host_request,
    is_hook_hold,
    lane_run_id,
    mirror_problems,
    read_run_ledger,
    read_run_status,
    record_message,
    run_complete_problems,
    run_status_path,
    same_prompt,
    step_summary,
)

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
                elif tool_name in ("Task", "Agent"):
                    desc = (tool_input or {}).get("description", "")[:60]
                    sub = (tool_input or {}).get("subagent_type", "?")
                    block_summaries.append(f"→ {tool_name}[{sub}]: {desc}")
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

# The first two decks this file drives, by the company name each prompt states (the numeric-operators
# deck's is beside its lane, below).
SMOKE_COMPANY = "Acmecorp"
CONTRADICTION_COMPANY = "Foobar Systems"


def lane_prompt(deck_path: Path | str, company: str, slug: str) -> str:
    """The request a deck-review lane sends, before the host's lines.

    The stage is stated as MY answer, not as background colour. The gate's documented
    auto-satisfy branch fires only when Step 1 captured a stage from the founder and the
    detected stage matches it; a prompt that merely mentions "seed-stage" leaves the agent
    to decide whether it has an answer, so the run exercises an ambiguous path instead of
    the sanctioned one. `authorize()` refuses auto-satisfy against a low-confidence
    profile, which is a legitimate refusal -- this wording makes a refusal here mean
    "detection was not confident", not "nobody said what stage this is".
    """
    return (
        f"Use the deck-review skill to review the synthetic deck at "
        f"{deck_path}. It's a fictional company called {company}. "
        f"Use '{slug}' as the slug. I am the founder and the stage is "
        f"seed — treat that as my answer if you would otherwise ask. "
        f"Don't ask clarifying questions — just run."
    )


def host_values(company: str) -> tuple[tuple[str, str, str], ...]:
    """The host's value lines for a deck-review lane: the company name only, which `lane_prompt` states
    verbatim (the skill types it again from the prose, and a typed value that differs from the recorded
    one is refused). test_lane_host_lines.py pins both."""
    return (("ctx_basics.company_name", "different", company),)


def _paid_run_authorized() -> bool:
    """Has anyone actually ASKED for a billed run? A credential is not permission.

    Duplicated from `_e2e_harness.paid_run_authorized` because this lane deliberately does
    not use the shared harness (it is the oldest lane of the paid release gate). The duplication is
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


CONTRADICTION_DECK = FIXTURES / "decks" / "synthetic-contradiction-deck.txt"
CONTRADICTION_GOLDEN = FIXTURES / "golden" / "deck-review" / "synthetic-contradiction-deck.expected.json"

# The contradiction lane bills SEPARATELY from the release gate, and that is the point.
# `test_deck_review_smoke` is what a release spends on; adding a second deck to it would double
# the cost of every release for a lane that answers a different question. This variable is
# the opt-in, and the CI skip-check names the lane as a deliberate opt-out so a skip here
# still cannot pass for a run.
CONTRADICTION_OPT_IN_ENV = "RUN_PAID_E2E_CONTRADICTION"


def _contradiction_lane_authorized() -> bool:
    return _has_claude_auth() and os.environ.get(CONTRADICTION_OPT_IN_ENV, "").strip().lower() in {
        "1",
        "true",
        "yes",
    }


def _deck_review_options(workdir: Path, plugin_path: Path) -> Any:
    """The SDK options this lane runs with. A function so a free test can check what they contain."""
    from claude_agent_sdk import ClaudeAgentOptions

    return ClaudeAgentOptions(  # type: ignore[call-arg]
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
        # Hook lifecycle events in the stream, as the shared harness asks for: the CHECKLIST dispatch gate
        # reads each dispatch's PreToolUse response, so without them it could pass with the hook never run.
        include_hook_events=True,
        # SKILL.md bodies reference ${CLAUDE_PLUGIN_ROOT} (v0.4.3 invariant).
        # The SDK lane fills it into the skill text at load time, as
        # production does (measured: the token arrives substituted), so
        # production doesn't depend on the SessionStart hook firing. The env
        # var set here only lets bash see the value the text already
        # carries. The production-side invariant
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
            # block when it inlined the whole deck (it now names the deck-text file) plus the
            # instruction body. With this
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
            # Account connectors off; written last, so a caller's environment cannot turn them back on.
            **CONNECTOR_ISOLATION_ENV,
        },
        **connector_isolation_options(),
    )


def _drive_deck_review_lane(
    tmp_path: Path,
    *,
    deck_fixture: Path,
    golden_path: Path,
    company: str,
    slug: str,
    extra_checks: Callable[..., None] | None = None,
    lane: str = "dr",
) -> None:
    """Drive deck-review against one deck fixture and check it against one golden file.

    EXTRACTED so a second deck does not mean a second copy of the SDK setup. This file
    already carries one deliberate duplication (the auth gate, noted above as "the failure
    point to watch"); a third copy of 200 lines of options, streaming and assertions would be
    the same mistake at ten times the size. The release gate's test function keeps its exact
    name -- CI matches paid lanes BY NAME -- and becomes a two-line caller.
    """
    # Imports are inside the test so test collection works without the SDK
    # installed (CI install handles it via the dev extras).
    from claude_agent_sdk import SystemMessage, query

    # Stage a workspace; the skill creates artifacts/ under cwd.
    workdir = tmp_path / "workspace"
    workdir.mkdir()
    deck_dst = workdir / deck_fixture.name
    shutil.copy(deck_fixture, deck_dst)

    plugin_path = REPO_ROOT / "founder-skills"

    options = _deck_review_options(workdir, plugin_path)

    prompt = lane_prompt(deck_dst, company, slug)
    # The host names the run, as an unattended host does, and sends the company's name, which the prompt
    # states verbatim. Nothing else is pre-answered: the deck states no sector or location, so those stay
    # the run's to derive, and the stage is the founder's stated answer above, which the gate may take as
    # its default (a host stage line would neither enable nor disable the stage gate's auto-satisfy).
    run_id = lane_run_id(lane)
    prompt = host_request(prompt, run_id, values=host_values(company))

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

    session_tools: list[str] = []
    mcp_servers: list[Any] = []
    tool_call_names: list[str] = []
    # The structured record for the CHECKLIST dispatch report. A message that cannot be folded never stops the
    # run, so the stream file stays complete; it fails the lane after the run instead (`_fold_failures`).
    cap = RunCapture()
    capture_errors: list[str] = []

    async def run() -> None:
        msg_count = 0
        with SdkStreamFile(workdir, lane) as stream:
            async for msg in query(prompt=prompt, options=options):
                msg_count += 1
                stream.write(msg)
                captured_messages.append(str(msg))
                try:
                    record_message(cap, msg)
                except Exception as e:  # noqa: BLE001 -- kept, and a failure once the run has ended
                    capture_errors.append(repr(e))
                if isinstance(msg, SystemMessage) and msg.subtype == "init":
                    session_tools.extend(str(t) for t in msg.data.get("tools") or [])
                    mcp_servers.extend(msg.data.get("mcp_servers") or [])
                for block in getattr(msg, "content", None) or []:
                    if type(block).__name__ == "ToolUseBlock":
                        tool_call_names.append(str(getattr(block, "name", "")))
                print(f"[e2e #{msg_count:03d}] {_summarize_sdk_message(msg)}", flush=True)
        print(f"[e2e] --- SDK loop complete ({msg_count} messages) ---", flush=True)

    asyncio.run(run())
    assert_no_account_connectors(session_tools, tool_call_names, mcp_servers)

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

    expected = json.loads(golden_path.read_text())
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

    # 6b''. Every deck-reading step read the one deck text. Its producer wrote deck_text.md, and the three
    # pipes stamped the same body hash, so no step worked from another version of the text. A stamp says
    # which file was on disk at pipe time, not what a sub-agent read; the per-dispatch record below shows that.
    deck_text = review_dir / "deck_text.md"
    if not deck_text.is_file():
        failures.append("deck_text.md missing: Step 2's deck_text.py did not run")
    stamps = {
        name: ((_artifact(name) or {}).get("metadata") or {}).get("deck_text_sha256")
        for name in ("ledger.json", "second_read.json", "slide_reviews.json")
    }
    observed["deck_text.stamps_equal"] = len(set(stamps.values())) == 1 and None not in stamps.values()
    if not observed["deck_text.stamps_equal"]:
        failures.append(f"the deck-text stamps do not all match: {stamps}")
    # Each dispatch that reads the deck names the file, carries no retyped copy of it (the fixture's first
    # slide line), and Reads it. Gated since 0.24, on the dispatches that succeeded only.
    # A text fixture's first slide line; for a PDF, the first line of this run's deck text, which is what a
    # dispatch would have retyped (an image deck has no text of its own to compare against).
    if deck_fixture.suffix.lower() in (".txt", ".md"):
        source_lines = deck_fixture.read_text(encoding="utf-8").splitlines()[1:]
    else:
        body = deck_text.read_text(encoding="utf-8").split("\n---\n", 1)[-1] if deck_text.is_file() else ""
        source_lines = [ln for ln in body.splitlines() if not ln.startswith("## ")]
    slide_one = next((line.strip() for line in source_lines if line.strip()), "")
    text_failures, dispatch_notes, child_calls = deck_text_dispatch_problems(cap, slide_one)
    failures.extend(text_failures)
    observed["deck_text.dispatch_child_calls"] = child_calls
    observed["deck_text.dispatch_checks"] = (text_failures + dispatch_notes) or "pass"

    # 6b'. Step 5 graded THIS run's slide reviews. checklist.py -o refuses a grade that does not echo
    # slide_reviews.json's read token and stamps the token it accepted, so the two must agree. A mismatch or
    # a missing stamp means the checklist was written without the check (or Step 4 ran again after it).
    slide_reviews = _artifact("slide_reviews.json")
    checklist_art = _artifact("checklist.json")
    if slide_reviews is not None and checklist_art is not None:
        sr_token = (slide_reviews.get("metadata") or {}).get("read_token")
        graded = ((checklist_art.get("graded_against") or {}).get("slide_reviews") or {}).get("read_token")
        observed["checklist.graded_against_slide_reviews"] = bool(graded) and graded == sr_token
        if not sr_token:
            failures.append("slide_reviews.json carries no metadata.read_token: Step 4's producer did not write it")
        elif graded != sr_token:
            failures.append(
                "checklist.json's graded_against.slide_reviews.read_token does not equal slide_reviews.json's "
                "metadata.read_token: Step 5 wrote the checklist without a grade that read this run's slide reviews"
            )

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

    # 6f. Step 5's CHECKLIST dispatches against the prompt dr_dispatch_prompt.py printed -- GATED, as on the FMR
    # and market-sizing lanes (see `_record_checklist_dispatches`), beside 6b' above. A stream message that could
    # not be folded fails too: the report would be built from a partial record.
    observed["checklist_dispatch.capture_errors"] = capture_errors[:3]
    failures.extend(_fold_failures(capture_errors))
    _record_checklist_dispatches(cap, review_dir, run_id, observed, failures)

    # 7. The run status a host reads -- recorded and printed, never a failure on this lane (see the import).
    try:
        status_file = run_status_path(workdir, run_id)
        observed["run_status.exists"] = status_file.is_file()
        if status_file.is_file():
            status = read_run_status(workdir, run_id)
            observed["run_status.status"] = status.get("status")
            observed["run_status.code"] = status.get("code")
            observed["run_status.deliverables_status"] = status.get("deliverables_status")
            observed["run_status.complete_problems"] = run_complete_problems(status, run_id, "deck-review", review_dir)
            observed["compose_result.problems"] = compose_record_problems(review_dir, run_id, status)
            run_ledger = read_run_ledger(workdir, run_id)
            stage = ((run_ledger.get("gates") or {}).get("stage_confirmation") or {}).get("current") or {}
            observed["ledger.stage_confirmation"] = (stage.get("resolution"), stage.get("default_reason"))
            if gate is not None:
                observed["gate_state.mirror_problems"] = mirror_problems(gate, run_ledger)
    except Exception as e:  # noqa: BLE001 -- recorded, never a failure on the release gate
        observed["run_status.error"] = repr(e)

    if extra_checks is not None:
        extra_checks(review_dir=review_dir, report=report, assertions=a, observed=observed, failures=failures)

    print("\n[e2e] ---- observed values (calibration data for this lane) ----", flush=True)
    for key in sorted(observed):
        print(f"[e2e]   {key} = {observed[key]!r}", flush=True)
    print(f"[e2e]   artifacts = {sorted(p.name for p in review_dir.glob('*.json'))}", flush=True)
    print("[e2e] -----------------------------------------------------------", flush=True)

    assert not failures, "live deck-review run failed {} check(s):\n{}\n\nreview_dir: {}".format(
        len(failures), "\n".join(f"  - {f}" for f in failures), review_dir
    )


DECK_TEXT_CONTEXTS = ("LEDGER_EXTRACTION", "SECOND_READ", "SLIDE_REVIEWS")


def deck_text_dispatch_problems(cap: RunCapture, slide_one: str) -> tuple[list[str], list[str], int]:
    """(failures, notes, child calls) for the three dispatches that read the deck.

    Only a dispatch whose result arrived and is not an error counts, so a hook hold or a failed attempt
    followed by a good retry is not a failure; each context needs at least one such dispatch. Every one
    must name deck_text.md and carry no retyped copy of the deck (its first slide line), and must Read
    the file. When no succeeded dispatch recorded a tool call of its own the instrument is blind: the Read
    checks are skipped and that is a note, never a failure.
    """
    failures: list[str] = []
    notes: list[str] = []
    child_calls = 0
    succeeded: list[tuple[str, dict[str, Any]]] = []
    for context in DECK_TEXT_CONTEXTS:
        rows = [r for r in _dispatch_rows(cap, f"CONTEXT: {context}") if _dispatch_succeeded(cap, r)]
        if not rows:
            failures.append(f"no {context} dispatch succeeded")
        for row in rows:
            prompt = str((row.get("input") or {}).get("prompt", ""))
            child_calls += sum(1 for c in cap.tool_uses if c["parent_tool_use_id"] == row["id"])
            if "deck_text.md" not in prompt:
                failures.append(f"a {context} dispatch does not name deck_text.md")
            if slide_one and slide_one in prompt:
                failures.append(f"a {context} dispatch inlines the deck's text ({slide_one!r})")
            succeeded.append((context, row))
    if child_calls == 0:
        notes.append("child calls not captured: no deck-reading dispatch recorded a tool call of its own")
        return failures, notes, child_calls
    for context, row in succeeded:
        reads = cap.calls("Read", parent=str(row["id"]))
        if not any(str((r.get("input") or {}).get("file_path", "")).endswith("deck_text.md") for r in reads):
            failures.append(f"a {context} dispatch never Read deck_text.md")
    return failures, notes, child_calls


def _dispatch_succeeded(cap: RunCapture, row: dict[str, Any]) -> bool:
    """The dispatch's result arrived and is not an error (a hook hold is one)."""
    result = cap.result(str(row["id"]))
    return result is not None and not result.get("is_error") and not is_hook_hold(result)


def _dispatch_rows(cap: RunCapture, context: str) -> list[dict[str, Any]]:
    """The main thread's dispatches whose prompt opens with `context` (a suffix such as "(repair)" included)."""
    out = []
    for call in cap.tool_uses:
        if call["name"] not in ("Agent", "Task") or call["parent_tool_use_id"] is not None:
            continue
        prompt = str((call.get("input") or {}).get("prompt", ""))
        first = next((line.strip() for line in prompt.splitlines() if line.strip()), "")
        if first == context or first.startswith(context + " "):
            out.append(call)
    return out


def _row_index(cap: RunCapture, *, tool_use_id: str, result: bool) -> int | None:
    """Where in the transcript-shaped rows a call was made (or its result arrived)."""
    for index, row in enumerate(cap.rows):
        if row.get("isSidechain"):
            continue
        content = (row.get("message") or {}).get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if result and block.get("type") == "tool_result" and block.get("tool_use_id") == tool_use_id:
                return index
            if not result and block.get("type") == "tool_use" and block.get("id") == tool_use_id:
                return index
    return None


def _regenerated_checklist(prompt: str, review_dir: Path, run_id: str) -> str | None:
    """Step 5's prompt printed again after the run, from the identifiers the dispatched prompt carries: the only
    check that sees a run in which no print was ever vouched for (the hook's comparand then does not exist).

    A corrective redo is printed again WITH its correction, read back from the prompt's added line (for a producer
    rejection, the quoted message, unquoted into a file), so a redo the hook could not vouch for is compared with
    the redo the generator prints, not with the plain prompt. A message the generator cut at its cap is not
    reproduced and stays unequal."""
    import re
    import tempfile

    output = re.search(r"^OUTPUT_PATH:\s*(.+?)\s*$", prompt, re.MULTILINE)
    review_agent = re.search(r"using the slide reviews at (\S+)/slide_reviews\.json", " ".join(prompt.split()))
    if output is None or review_agent is None:
        return None
    generator = REPO_ROOT / "founder-skills" / "skills" / "deck-review" / "scripts" / "dr_dispatch_prompt.py"
    args = ["checklist", "--run-id", run_id, "--handoff-agent", os.path.dirname(output.group(1))]
    args += ["--review-dir-agent", review_agent.group(1), "--review-dir", str(review_dir)]
    gen = _generator_module(generator)
    with tempfile.TemporaryDirectory() as tmp:
        for kind, line in gen.CORRECTIONS.items():
            if line in prompt:
                args += ["--correction", kind]
                break
        else:
            if gen.REJECTION_LEAD in prompt and gen.REJECTION_TAIL in prompt:
                quoted = prompt.split(gen.REJECTION_LEAD, 1)[1].split(gen.REJECTION_TAIL, 1)[0].strip("\n")
                lines = [
                    ln[2:] if ln.startswith("> ") else ln[1:] if ln.startswith(">") else ln
                    for ln in quoted.splitlines()
                ]
                detail = Path(tmp) / "producer_rejected.txt"
                detail.write_text("\n".join(lines) + "\n", encoding="utf-8")
                args += ["--correction", gen.PRODUCER_REJECTED, "--detail-file", str(detail)]
        r = subprocess.run([sys.executable, str(generator), *args], capture_output=True, text=True, timeout=60)
    return r.stdout if r.returncode == 0 else None


def _generator_module(path: Path) -> Any:
    """The CHECKLIST generator, loaded by path for its correction wording (never re-typed here, so it cannot drift)."""
    import importlib.util

    scripts = str(path.parent)
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    spec = importlib.util.spec_from_file_location("_e2e_dr_dispatch_prompt", path)
    assert spec is not None and spec.loader is not None, path
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _fold_failures(capture_errors: list[str]) -> list[str]:
    """The lane's failure line for stream messages the capture could not fold, naming the first error."""
    if not capture_errors:
        return []
    return [f"{len(capture_errors)} stream message(s) could not be folded: {capture_errors[0]}"]


_PRETOOLUSE_DISPATCH = ("PreToolUse:Agent", "PreToolUse:Task")


def _hook_decision(response: dict[str, Any]) -> str:
    """What a PreToolUse response decided, read from its stdout: `deny`, `rewrite` (an allow carrying
    `updatedInput`), `allow` (an explicit allow, or no output with exit 0), else `unknown`. Exit 2 is a deny."""
    if response.get("exit_code") == 2:
        return "deny"
    stdout = str(response.get("stdout") or "").strip()
    if not stdout:
        return "allow" if response.get("exit_code") in (0, None) else "unknown"
    try:
        out = (json.loads(stdout).get("hookSpecificOutput") or {}) if stdout.startswith("{") else {}
    except (ValueError, AttributeError):
        return "unknown"
    decision = out.get("permissionDecision") if isinstance(out, dict) else None
    if decision == "deny":
        return "deny"
    if decision == "allow":
        return "rewrite" if "updatedInput" in out else "allow"
    return "unknown"


def _pretooluse_decisions(cap: RunCapture) -> dict[str, str]:
    """Each dispatch's PreToolUse response, by dispatch id, as the decision it made.

    The stream carries no tool id on a hook event, so the pairing goes by position: every dispatch (Agent or
    Task, in stream order) takes the next unclaimed `PreToolUse:Agent|Task` response that arrived after it and
    belongs to the same thread (`parent_tool_use_id`, None on the main thread), so a sub-agent's own dispatch
    never lends its response to a main-thread one. Kept streams show each dispatch's response right after its
    call; calls batched in one message come first and their responses follow in call order. A dispatch whose
    hook never ran is left out."""
    responses = [
        h for h in cap.hook_events if h.get("subtype") == "hook_response" and h.get("name") in _PRETOOLUSE_DISPATCH
    ]
    claimed = [False] * len(responses)
    out: dict[str, str] = {}
    for at, event in enumerate(cap.events):
        if event.get("kind") != "tool_use" or event.get("name") not in ("Agent", "Task"):
            continue
        for index, response in enumerate(responses):
            if claimed[index] or response["at"] <= at:
                continue
            if response.get("parent_tool_use_id") != event.get("parent_tool_use_id"):
                continue
            claimed[index] = True
            out[str(event["id"])] = _hook_decision(response)
            break
    return out


def _assert_hook_ran(checklists: list[dict[str, Any]], decisions: dict[str, str]) -> None:
    missing = [str(c["id"]) for c in checklists if str(c["id"]) not in decisions]
    assert not missing, (
        f"CHECKLIST dispatch(es) {missing} have no PreToolUse hook response: the plugin's hook may not have run, "
        "so no other dispatch check here says anything about it (or the CLI no longer names hook responses "
        "`PreToolUse:<tool>`, which reds every dispatch at once)"
    )


_DECK_AGENTS = ("deck-review", "founder-skills:deck-review")


def _assert_checklist_agent(checklists: list[dict[str, Any]], report: dict[str, Any]) -> None:
    """Every CHECKLIST dispatch that went through ran on the deck-review agent. The type check lets a wrong agent
    through after two holds, and nothing else on the lane would see it."""
    by_id = {str(c["id"]): c for c in checklists}
    wrong = [
        (row["id"], (by_id[str(row["id"])].get("input") or {}).get("subagent_type"))
        for row in report["dispatches"]
        if row["status"] == "succeeded"
        and (by_id[str(row["id"])].get("input") or {}).get("subagent_type") not in _DECK_AGENTS
    ]
    assert not wrong, f"CHECKLIST dispatch(es) went through on another agent: {wrong}"


def _record_checklist_dispatches(
    cap: RunCapture, review_dir: Path, run_id: str, observed: dict[str, Any], failures: list[str]
) -> None:
    """Step 5's CHECKLIST dispatches judged against the prompt the generator printed, GATED as on the FMR and
    market-sizing lanes: each failing assertion appends a line to `failures` (and is recorded in `observed`, the
    job summary and the run log). Each line carries `equals_offline_regeneration` and the held count, so the
    release's rule for a red lane (variance or a real failure) can be applied in one read.

    Gated: no CHECKLIST dispatch failed with an error that is not a hold, and no hold caught the printed prompt
    (a `[dispatch-type]` hold judges the agent, so it never counts); every dispatch that went through delivered
    the printed prompt, or, where the hook found no comparand, the lane's own offline regeneration of it; every
    CHECKLIST dispatch has a PreToolUse response. A report that cannot be built fails too. Recorded only: the
    count, holds, rewrites, parallel dispatches, the offline comparison and each dispatch's hook decision.

    Known misattribution: when the hook's holds run out and checklist.py refuses a blind grade, the gated stamp
    check (6b') is skipped, not failed, because checklist.json does not exist, and the lane reds on the missing
    artifact. The received-prompt failure here now reds alongside it and names the right cause."""
    try:
        checklists = _dispatch_rows(cap, "CONTEXT: CHECKLIST")
        slide_reviews = _dispatch_rows(cap, "CONTEXT: SLIDE_REVIEWS")
        report = dispatch_report(cap, checklists)
        text = format_dispatch_report("CHECKLIST", report)
        observed["checklist_dispatch.count"] = len(checklists)
        observed["checklist_dispatch.held"] = report["held"]
        observed["checklist_dispatch.rewrites"] = report["rewrites"]
        # Parallel: a CHECKLIST dispatched before a SLIDE_REVIEWS dispatch's result had arrived.
        parallel = []
        for c in checklists:
            made = _row_index(cap, tool_use_id=str(c["id"]), result=False)
            for sr in slide_reviews:
                done = _row_index(cap, tool_use_id=str(sr["id"]), result=True)
                if made is not None and (done is None or made < done):
                    parallel.append(c["id"])
                    break
        observed["checklist_dispatch.beside_slide_reviews"] = parallel
        regenerated: list[bool | None] = []
        offline: dict[str, str] = {}
        for c in checklists:
            res = cap.result(str(c["id"])) or {}
            received = (res.get("tool_use_result") or {}).get("prompt") if isinstance(res, dict) else None
            prompt = received if isinstance(received, str) else str((c.get("input") or {}).get("prompt", ""))
            again = _regenerated_checklist(prompt, review_dir, run_id)
            regenerated.append(None if again is None else same_prompt(prompt, again))
            if again is not None:
                offline[str(c["id"])] = again
        observed["checklist_dispatch.equals_offline_regeneration"] = regenerated
        decisions = _pretooluse_decisions(cap)
        observed["checklist_dispatch.hook_decisions"] = [decisions.get(str(c["id"])) for c in checklists]
        for name, check in (
            ("outcomes", lambda: assert_dispatch_outcomes(report, "CHECKLIST")),
            ("received_prompt", lambda: assert_received_prompt(report, "CHECKLIST", fallback=offline)),
            ("hook_ran", lambda: _assert_hook_ran(checklists, decisions)),
            ("agent", lambda: _assert_checklist_agent(checklists, report)),
        ):
            try:
                check()
                observed[f"checklist_dispatch.{name}"] = "pass"
            except AssertionError as e:
                first = str(e).splitlines()[0]
                observed[f"checklist_dispatch.{name}"] = "FAIL: " + first
                failures.append(
                    f"CHECKLIST dispatch {name}: {first} "
                    f"(equals_offline_regeneration={regenerated}, held={report['held']})"
                )
        print("[e2e] " + text.replace("\n", "\n[e2e] "), flush=True)
        step_summary("### deck-review CHECKLIST dispatches\n" + text)
    except Exception as e:  # noqa: BLE001 -- a report that cannot be built fails the lane, by name
        observed["checklist_dispatch.error"] = repr(e)
        failures.append(f"CHECKLIST dispatch report could not be built: {e!r}")


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
    """The release gate. One deck, the thin-stub fixture; a release spends on exactly this."""
    _drive_deck_review_lane(
        tmp_path,
        deck_fixture=DECK_FIXTURE,
        golden_path=GOLDEN,
        company=SMOKE_COMPANY,
        slug="acmecorp",
    )


def _check_contradictions(
    *,
    review_dir: Path,
    report: dict,
    assertions: dict,
    observed: dict,
    failures: list,
) -> None:
    """The whole reason this lane exists: a contradiction has to reach the founder.

    The stub lane surfaced ZERO relations, so `select()`, the tolerance and materiality
    rules, the ordering by relative wrongness and the rendering were all untested against a
    real model. Everything here is about the FOUNDER-VISIBLE half — the engine's own
    arithmetic is covered offline, and this cannot re-derive it.
    """
    recon_path = review_dir / "reconciliation.json"
    if not recon_path.exists():
        failures.append("reconciliation.json absent, so the contradiction path cannot be judged")
        return
    recon = json.loads(recon_path.read_text())

    wanted = assertions.get("reconciliation_status_in")
    if wanted and recon.get("status") not in wanted:
        failures.append(f"reconciliation status {recon.get('status')!r} not in {wanted}")

    relations = [r for r in (recon.get("relations") or []) if isinstance(r, dict)]
    # Split on VERDICT, never `kind`: `kind` is what the model proposed and `verdict` is what
    # the engine computed, and the flagship finding is proposed `derived_ratio` and returns
    # `contradiction`.
    contradictions = [r for r in relations if r.get("verdict") == "contradiction"]
    observed["surfaced_contradictions"] = len(contradictions)
    observed["surfaced_rendered"] = [r.get("rendered") for r in contradictions]
    observed["reconciliation.suppressed"] = recon.get("suppressed")

    floor = assertions.get("surfaced_contradictions_min")
    if floor is not None and len(contradictions) < floor:
        failures.append(
            f"only {len(contradictions)} contradiction(s) surfaced, expected >= {floor}. The deck "
            f"states an MRR its own customer count and ARPU refute by ~78% and a TAM its own "
            f"inputs refute by ~20%; suppressed={recon.get('suppressed')!r}"
        )

    # A surfaced contradiction must actually be RENDERED to the founder. The artifact holding
    # it is not the deliverable, and a founder reads report.md.
    md_path = review_dir / "report.md"
    if contradictions and md_path.exists():
        md = md_path.read_text()
        if "What Your Numbers Say About Each Other" not in md:
            failures.append("a contradiction survived select() but report.md has no numbers section")
        unrendered = [
            r.get("rendered")
            for r in contradictions
            if r.get("rendered") and str(r.get("rendered")).split("=")[0].strip() not in md
        ]
        if unrendered:
            failures.append(f"contradictions surfaced but absent from report.md: {unrendered}")

    # THE CRITERION IS SCORED FROM THE ARITHMETIC. A surfaced contradiction fails
    # `numbers_consistent` whatever the reviewer read, and the stamp proves Step 5 passed
    # `--reconciliation` (without it the reviewer's status stands and nothing else notices).
    wanted_nc = assertions.get("numbers_consistent_status")
    if wanted_nc is not None:
        checklist_path = review_dir / "checklist.json"
        if not checklist_path.exists():
            failures.append("numbers_consistent_status requested but checklist.json is absent")
        else:
            items = json.loads(checklist_path.read_text()).get("items") or []
            nc = next((i for i in items if isinstance(i, dict) and i.get("id") == "numbers_consistent"), {})
            observed["checklist.numbers_consistent"] = (
                nc.get("status"),
                nc.get("scored_by"),
                nc.get("reviewer_status"),
            )
            if nc.get("scored_by") != "arithmetic":
                failures.append(
                    "numbers_consistent carries no scored_by: arithmetic, so Step 5 ran checklist.py "
                    "without --reconciliation and the reviewer's reading decided it"
                )
            if nc.get("status") != wanted_nc:
                failures.append(f"numbers_consistent is {nc.get('status')!r}, expected {wanted_nc!r}")

    # THE COACH SEES WHAT THE ARITHMETIC FOUND. This lane and the numeric-operators lane are the only ones
    # where `numeric_findings` can be non-empty, so they are the live tests of the payload the coach reads.
    findings_floor = assertions.get("numeric_findings_min")
    if findings_floor is not None:
        findings = (report.get("coaching_payload") or {}).get("numeric_findings") or []
        observed["coaching_payload.numeric_findings"] = len(findings)
        if len(findings) < findings_floor:
            failures.append(
                f"coaching_payload.numeric_findings has {len(findings)} entries, expected >= {findings_floor}"
            )

    # ORDERING, asserted only when there are two to order — with one, order is not a claim.
    if len(contradictions) >= 2:

        def wrongness(rel: dict) -> float:
            expected, computed = rel.get("expected_value"), rel.get("computed")
            if not isinstance(expected, (int, float)) or not isinstance(computed, (int, float)) or not expected:
                return -1.0
            return abs(computed - expected) / abs(expected)

        scores = [wrongness(r) for r in contradictions]
        observed["surfaced_wrongness"] = [round(x, 3) for x in scores]
        if any(x < 0 for x in scores):
            failures.append(f"a surfaced contradiction carries no comparable magnitude: {scores}")
        elif scores != sorted(scores, reverse=True):
            failures.append(
                f"contradictions are not ordered most-wrong-first: {[round(x, 3) for x in scores]}. "
                "A 78% discrepancy has to reach the founder before a 20% one"
            )


@pytest.mark.e2e
@pytest.mark.skipif(
    not _contradiction_lane_authorized(),
    reason=(
        "Contradiction lane: needs RUN_PAID_E2E=1 AND RUN_PAID_E2E_CONTRADICTION=1 plus Claude "
        "auth. Billed separately from the release gate on purpose — a release should not pay for "
        "two decks, and this one answers a different question."
    ),
)
def test_deck_review_contradiction_lane(tmp_path: Path) -> None:
    """A deck that contradicts itself must tell the founder so, most-wrong-first."""
    _drive_deck_review_lane(
        tmp_path,
        deck_fixture=CONTRADICTION_DECK,
        golden_path=CONTRADICTION_GOLDEN,
        company=CONTRADICTION_COMPANY,
        slug="foobar",
        extra_checks=_check_contradictions,
        lane="dr-contra",
    )


IMAGE_DECK = FIXTURES / "decks" / "synthetic-image-deck.pdf"
IMAGE_GOLDEN = FIXTURES / "golden" / "deck-review" / "synthetic-image-deck.expected.json"
IMAGE_COMPANY = "Larkspur Kilns"

# The image-deck lane bills separately too, and runs on the same `extra_deck_lanes` dispatch: it is the only paid
# run that reaches Step 3.95 (every other deck lane is text). The dispatch installs tesseract and poppler first.
IMAGE_OPT_IN_ENV = "RUN_PAID_E2E_OCR"


def _image_lane_authorized() -> bool:
    return _has_claude_auth() and os.environ.get(IMAGE_OPT_IN_ENV, "").strip().lower() in {"1", "true", "yes"}


def _check_machine_read(
    *,
    review_dir: Path,
    report: dict,
    assertions: dict,
    observed: dict,
    failures: list,
) -> None:
    """Step 3.95 ran on the image slides and the founder line is the one its counts imply."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "deck-review" / "scripts"))
    import _reconciliation_prose  # type: ignore[import-not-found]

    path = review_dir / "ocr_check.json"
    if not path.exists():
        failures.append("ocr_check.json absent: Step 3.95 did not run on an image-only deck")
        return
    check = json.loads(path.read_text())
    counts = check.get("counts") or {}
    observed["ocr_status"], observed["ocr_counts"] = check.get("status"), counts
    if check.get("status") not in assertions.get("ocr_status_in", []):
        failures.append(f"ocr_check status {check.get('status')!r} not in {assertions.get('ocr_status_in')}")
        return
    if int(counts.get("in_scope") or 0) < assertions.get("ocr_in_scope_min", 0):
        failures.append(f"ocr_check in_scope {counts.get('in_scope')} under {assertions.get('ocr_in_scope_min')}")
    if check.get("status") != "checked":
        return
    recon = json.loads((review_dir / "reconciliation.json").read_text())
    inventory = json.loads((review_dir / "deck_inventory.json").read_text())
    want = _reconciliation_prose.ocr_read_line_for(str(review_dir), check, recon, inventory)
    md = (review_dir / "report.md").read_text()
    if want and want not in md:
        failures.append(f"report.md lacks the machine-read line its counts imply: {want!r}")
    if not want and "carry little or no selectable text" in md:
        failures.append("report.md carries a machine-read line where its counts imply none")


@pytest.mark.e2e
@pytest.mark.skipif(
    not _image_lane_authorized(),
    reason=(
        "Image-deck lane: needs RUN_PAID_E2E=1 AND RUN_PAID_E2E_OCR=1 plus Claude auth. Without tesseract and "
        "poppler on PATH it runs and fails (the read is unavailable). Billed separately; the only paid run that "
        "reaches Step 3.95."
    ),
)
def test_deck_review_image_deck_lane(tmp_path: Path) -> None:
    """An image-only deck: the figures the numbers section uses are machine-read, and the founder is told how many
    were found."""
    _drive_deck_review_lane(
        tmp_path,
        deck_fixture=IMAGE_DECK,
        golden_path=IMAGE_GOLDEN,
        company=IMAGE_COMPANY,
        slug="larkspur",
        extra_checks=_check_machine_read,
        lane="dr-image",
    )


NUMERIC_DECK = FIXTURES / "decks" / "synthetic-numeric-operators-deck.txt"
NUMERIC_GOLDEN = FIXTURES / "golden" / "deck-review" / "synthetic-numeric-operators-deck.expected.json"
NUMERIC_COMPANY = "Kestrelline"

# The numeric-operators lane bills separately too, for the contradiction lane's reason: it answers a
# question a release does not ask -- does the MODEL propose `runway` over a burn plan, `inverse_change`
# and `implied_base` from a real deck -- and it is the only live test of that. Its own opt-in.
NUMERIC_OPT_IN_ENV = "RUN_PAID_E2E_NUMERIC"

# The operators the engine replay reports on: the three this lane exists for, and the flat division a
# runway may retire.
_NUMERIC_TARGET_OPERATORS = ("runway", "inverse_change", "implied_base", "ratio")


def _numeric_lane_authorized() -> bool:
    return _has_claude_auth() and os.environ.get(NUMERIC_OPT_IN_ENV, "").strip().lower() in {"1", "true", "yes"}


def _relation_proposals(review_dir: Path, run_id: str | None) -> tuple[list[dict], str | None]:
    """The Step 3.7 hand-off -- what the MODEL proposed -- or the reason it cannot be read.

    `reconciliation.json` carries only the relations `select()` kept and a count of the rest, so it cannot
    say whether an operator was proposed; the proposer's own file is the only record. Read from this run's
    hand-off dir when the run id is known, else from the one dir there is.
    """
    candidates = sorted(review_dir.glob("handoff/*/relations_output.json"))
    if run_id:
        candidates = [p for p in candidates if p.parent.name == run_id] or candidates
    if len(candidates) != 1:
        return [], f"expected one handoff/<run_id>/relations_output.json, found {[str(p) for p in candidates]}"
    try:
        data = json.loads(candidates[0].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [], f"{candidates[0]} is unreadable: {exc}"
    relations = data.get("relations") if isinstance(data, dict) else None
    if not isinstance(relations, list):
        return [], f"{candidates[0]} carries no `relations` list"
    return [r for r in relations if isinstance(r, dict)], None


def _engine_replay(review_dir: Path, proposals: list[dict]) -> list[dict] | str:
    """Re-run the engine over the run's own ledger, second read and proposals: each target relation's
    verdict and the engine's stated reasons, for diagnosis only.

    `reconciliation.json` records suppressed relations as counts with no reasons, so a proposed runway that
    came back `incomparable` (a burn with no period, a start month outside the plan) is otherwise
    undiagnosable after a billed run. Never an assertion: the artifact is what the founder got, and this is
    a second computation beside it.
    """
    import importlib.util  # noqa: PLC0415

    try:
        ledger = json.loads((review_dir / "ledger.json").read_text(encoding="utf-8"))
        second = json.loads((review_dir / "second_read.json").read_text(encoding="utf-8"))
        scripts = REPO_ROOT / "founder-skills" / "skills" / "deck-review" / "scripts"
        if str(scripts) not in sys.path:
            sys.path.insert(0, str(scripts))
        rec = sys.modules.get("_numeric_lane_reconcile")
        if rec is None:
            spec = importlib.util.spec_from_file_location("_numeric_lane_reconcile", scripts / "reconcile.py")
            assert spec and spec.loader
            rec = importlib.util.module_from_spec(spec)
            # Registered BEFORE exec: the module's dataclasses resolve their annotations through it.
            sys.modules[spec.name] = rec
            spec.loader.exec_module(rec)
        figures, alias = rec.merge_range_twins(rec.load_figures(ledger))
        rec.verify(figures, str(second.get("transcript") or ""), rec.quote_in_doc)
        by_id = {f.id: f for f in figures}
        computed = [rec.compute({**proposal, "_alias": alias}, by_id) for proposal in proposals]
        rec.supersede(computed)
    except Exception as exc:  # noqa: BLE001 -- a diagnostic that cannot run says so; it never fails the lane
        return f"engine replay could not run: {exc!r}"
    return [
        {
            "operator": r.operator,
            "operands": r.operands,
            "expected_id": r.expected_id,
            "verdict": "dropped" if r.dropped else r.verdict,
            "confidence": r.confidence,
            "rendered": r.rendered,
            "reasons": r.reasons,
        }
        for r in computed
        if r.operator in _NUMERIC_TARGET_OPERATORS
    ]


def _check_numeric_operators(
    *,
    review_dir: Path,
    report: dict,
    assertions: dict,
    observed: dict,
    failures: list,
) -> None:
    """Did the model PROPOSE the three operators, and did the founder get what the engine makes of them?

    Two kinds of check, kept apart. What the model proposed is read from its hand-off and is the test --
    nothing else shows these operators proposed from a real deck. What the engine decided is read from
    `reconciliation.json` and is fixed once the proposal is right (test_lane_numeric_checks.py runs this
    deck's figures through the real engine for free); a gap there is diagnosed by replaying the engine over
    the run's own artifacts rather than guessed at.
    """
    recon_path = review_dir / "reconciliation.json"
    recon: dict = {}
    if recon_path.exists():
        try:
            loaded = json.loads(recon_path.read_text(encoding="utf-8"))
            recon = loaded if isinstance(loaded, dict) else {}
        except json.JSONDecodeError as exc:
            failures.append(f"reconciliation.json is not parseable JSON: {exc}")
    else:
        failures.append("reconciliation.json absent, so no operator's outcome can be judged")
    meta = recon.get("metadata")
    run_id = meta.get("run_id") if isinstance(meta, dict) else None

    wanted = assertions.get("reconciliation_status_in")
    if wanted and recon and recon.get("status") not in wanted:
        failures.append(f"reconciliation status {recon.get('status')!r} not in {wanted}")

    # 1. WHAT THE MODEL PROPOSED -- the test.
    proposals, why_not = _relation_proposals(review_dir, run_id)
    proposed_ops = sorted({str(p.get("operator")) for p in proposals})
    observed["numeric.proposed_operators"] = proposed_ops
    observed["numeric.proposals"] = len(proposals)
    if why_not:
        failures.append(f"the proposer's hand-off cannot be read, so nothing it proposed can be judged: {why_not}")
    else:
        for op in assertions.get("proposed_operators_required") or []:
            if op not in proposed_ops:
                failures.append(
                    f"the model never proposed `{op}` (proposed: {proposed_ops}). This lane's deck is built so "
                    f"that `{op}` is a relation an analyst would run; a proposer that skips it leaves the "
                    "operator unreached in production"
                )
        if assertions.get("runway_proposed_with_schedule"):
            runways = [p for p in proposals if p.get("operator") == "runway"]
            if runways and not any(isinstance(p.get("schedule"), list) and p.get("schedule") for p in runways):
                failures.append(
                    "the model proposed `runway` without a `schedule`, so the deck's burn PLAN was read as one "
                    "flat burn -- the division the plan exists to replace"
                )

    # 2. WHAT THE ENGINE DECIDED -- fixed once the proposal is right.
    relations = [r for r in (recon.get("relations") or []) if isinstance(r, dict)]
    # Split on VERDICT, never `kind`: `kind` is the model's framing, `verdict` is the engine's answer.
    contradictions = [r for r in relations if r.get("verdict") == "contradiction"]
    raw_suppressed = recon.get("suppressed")
    suppressed: dict = raw_suppressed if isinstance(raw_suppressed, dict) else {}
    observed["numeric.surfaced"] = [(r.get("operator"), r.get("verdict")) for r in relations]
    observed["numeric.suppressed"] = suppressed
    observed["numeric.superseded"] = suppressed.get("superseded", 0)
    observed["numeric.implied_base_surfaced"] = [
        r.get("rendered") for r in relations if r.get("operator") == "implied_base"
    ]
    surfaced_ops = {str(r.get("operator")) for r in contradictions}
    for op in assertions.get("surfaced_contradiction_operators_required") or []:
        if op not in surfaced_ops:
            how = "was proposed but" if op in proposed_ops else "was never proposed, so it"
            failures.append(
                f"no `{op}` contradiction reached the founder: it {how} did not surface. "
                "numeric.engine_replay below carries the engine's own reason"
            )

    if assertions.get("runway_stated_longer_than_computed"):
        for r in contradictions:
            computed, stated = r.get("computed"), r.get("expected_value")
            if (
                r.get("operator") == "runway"
                and isinstance(computed, (int, float))
                and isinstance(stated, (int, float))
                and computed >= stated
            ):
                failures.append(
                    f"a runway contradiction computes {computed:.1f} months against a stated {stated}: every "
                    "cash the deck names gives LESS runway than it states, so what was counted as cash is "
                    f"not cash -- {r.get('rendered')!r}"
                )

    # A FLAT DIVISION NEVER STANDS BESIDE THE RUNWAY THAT REPLACES IT. `supersede()` retires a flat `ratio`
    # against the same stated figure whose two operands are both among a compared runway's; one that
    # survives beside the runway is two readings of one claim shown to a founder as two findings.
    if assertions.get("flat_runway_ratio_never_beside_runway"):
        runways_shown = [r for r in relations if r.get("operator") == "runway"]
        for flat in relations:
            if flat.get("operator") != "ratio" or not flat.get("expected_id"):
                continue
            for rw in runways_shown:
                if rw.get("expected_id") == flat.get("expected_id") and set(flat.get("operands") or []) <= set(
                    rw.get("operands") or []
                ):
                    failures.append(
                        f"a flat division {flat.get('rendered')!r} surfaced beside the runway over the plan "
                        f"{rw.get('rendered')!r}; supersede() should have retired it"
                    )

    blocked = set(assertions.get("no_downgrade_of_operators") or [])
    raw_interpretation = recon.get("interpretation")
    interpretation: dict = raw_interpretation if isinstance(raw_interpretation, dict) else {}
    downgraded = [d for d in (interpretation.get("downgraded") or []) if isinstance(d, dict)]
    observed["numeric.downgraded"] = [(d.get("operator"), d.get("class")) for d in downgraded]
    for d in downgraded:
        if d.get("operator") in blocked:
            failures.append(
                f"the interpretation pass withdrew a `{d.get('operator')}` contradiction as {d.get('class')!r} "
                f"({d.get('reason')!r}); neither withdrawal class describes this deck's figures"
            )

    # The founder reads report.md, not the artifact.
    md_path = review_dir / "report.md"
    if contradictions and md_path.exists():
        md = md_path.read_text(encoding="utf-8")
        unrendered = [
            r.get("rendered")
            for r in contradictions
            if r.get("rendered") and str(r.get("rendered")).split("=")[0].strip() not in md
        ]
        if unrendered:
            failures.append(f"contradictions surfaced but absent from report.md: {unrendered}")

    # 3. The scored criterion and the coach, as in the contradiction lane.
    wanted_nc = assertions.get("numbers_consistent_status")
    if wanted_nc is not None:
        checklist_path = review_dir / "checklist.json"
        if not checklist_path.exists():
            failures.append("numbers_consistent_status requested but checklist.json is absent")
        else:
            items = json.loads(checklist_path.read_text(encoding="utf-8")).get("items") or []
            nc = next((i for i in items if isinstance(i, dict) and i.get("id") == "numbers_consistent"), {})
            observed["checklist.numbers_consistent"] = (nc.get("status"), nc.get("scored_by"))
            if nc.get("scored_by") != "arithmetic":
                failures.append(
                    "numbers_consistent carries no scored_by: arithmetic, so Step 5 ran checklist.py "
                    "without --reconciliation and the reviewer's reading decided it"
                )
            if nc.get("status") != wanted_nc:
                failures.append(f"numbers_consistent is {nc.get('status')!r}, expected {wanted_nc!r}")
    findings_floor = assertions.get("numeric_findings_min")
    if findings_floor is not None:
        findings = (report.get("coaching_payload") or {}).get("numeric_findings") or []
        observed["coaching_payload.numeric_findings"] = len(findings)
        if len(findings) < findings_floor:
            failures.append(
                f"coaching_payload.numeric_findings has {len(findings)} entries, expected >= {findings_floor}"
            )

    # Diagnosis, printed with the observed values: the engine's verdict and reason per target relation.
    if proposals:
        observed["numeric.engine_replay"] = _engine_replay(review_dir, proposals)


@pytest.mark.e2e
@pytest.mark.skipif(
    not _numeric_lane_authorized(),
    reason=(
        "Numeric-operators lane: needs RUN_PAID_E2E=1 AND RUN_PAID_E2E_NUMERIC=1 plus Claude auth. Billed "
        "separately from the release gate on purpose -- it asks whether the model proposes the runway, "
        "inverse_change and implied_base operators, which a release does not."
    ),
)
def test_deck_review_numeric_operators_lane(tmp_path: Path) -> None:
    """A deck with a burn plan, a reciprocal pair and a share of a total: the model must propose all three
    operators, and the founder must get the runway and reciprocal disagreements."""
    _drive_deck_review_lane(
        tmp_path,
        deck_fixture=NUMERIC_DECK,
        golden_path=NUMERIC_GOLDEN,
        company=NUMERIC_COMPANY,
        slug="kestrelline",
        extra_checks=_check_numeric_operators,
        lane="dr-numeric",
    )
