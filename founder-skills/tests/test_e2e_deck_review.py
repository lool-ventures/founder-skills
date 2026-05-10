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
  - On Claude Pro subscription: ~50+ messages per run consumed against
    the per-5-hour cap (~45 on Pro). **One e2e run can blow the entire
    Pro cap for that 5-hour window** — meaning interactive Claude Code
    use during that window will be rate-limited. Pro is NOT viable for
    per-PR CI; it's viable only for occasional manual local runs.
  - On Claude Max (~225 messages per 5-hour window): ~3-4 runs per
    window before rate-limiting. Workable for moderate PR volume but
    will rate-limit on bursty days.
  - **For sustained CI use, prefer `ANTHROPIC_API_KEY` (per-token
    billing with a spend cap) over subscription auth.** The subscription
    paths are documented for local-dev convenience; they are not the
    recommended CI auth.

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


def _has_claude_auth() -> bool:
    """True if any of the SDK's auth paths is available.

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
        "End-to-end smoke needs Claude auth: set ANTHROPIC_API_KEY, "
        "CLAUDE_CODE_OAUTH_TOKEN, or run `claude /login` (subscription) "
        "to populate ~/.claude/.credentials.json"
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

    options = ClaudeAgentOptions(
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
        },
    )

    prompt = (
        f"Use the deck-review skill to review the synthetic deck at "
        f"{deck_dst}. It's a fictional seed-stage SaaS company called "
        f"Acmecorp. Use 'acmecorp' as the slug. Don't ask clarifying "
        f"questions — just run."
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
    if a.get("all_artifacts_have_run_id"):
        run_ids = set()
        for art in [
            "deck_inventory.json",
            "stage_profile.json",
            "slide_reviews.json",
            "checklist.json",
            "report.json",
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
