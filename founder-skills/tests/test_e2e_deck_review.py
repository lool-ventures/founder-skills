"""End-to-end smoke: drive deck-review against the synthetic fixture deck.

Costs ~$2-5 per run (calibrate empirically — see Task 9 Step 4 in the plan).
Skipped if no API key.

NOTE: as of v0.4.4 + claude-agent-sdk==0.1.80, the SDK invocation pattern
below is documented but has NOT been empirically verified end-to-end. The
test author should run Task 9 Step 1 (manual SDK verification with API key)
before treating this test as load-bearing CI signal. See the plan at
docs/plans/2026-05-09-skill-quality-ci.md Task 9.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "founder-skills" / "tests" / "fixtures"
DECK_FIXTURE = FIXTURES / "decks" / "synthetic-seed-deck.txt"
GOLDEN = FIXTURES / "golden" / "deck-review" / "synthetic-seed-deck.expected.json"


@pytest.mark.e2e
@pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY required for end-to-end smoke",
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

    async def run() -> None:
        async for msg in query(prompt=prompt, options=options):
            captured_messages.append(str(msg))

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

    # 3. score_pct in expected range (LLM variation tolerated by range)
    summary = report.get("summary", {})
    score = summary.get("score_pct")
    if a.get("score_pct_range"):
        lo, hi = a["score_pct_range"]
        assert score is not None and lo <= score <= hi, f"score_pct {score} outside expected range [{lo}, {hi}]"

    # 4. overall_status in expected set
    if a.get("overall_status_in"):
        assert summary.get("overall_status") in a["overall_status_in"]

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
