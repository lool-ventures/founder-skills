"""Shared plumbing for the LLM-driven end-to-end lanes.

Extracted when the second and third lanes were added. `test_e2e_deck_review.py` is
deliberately NOT refactored onto this module: it is the lane the release tag gates on,
it is the only one with a validated green run behind it, and a mechanical refactor of a
paid lane on the eve of a tag trades a real risk for a cosmetic gain. Fold it in after
the release, when a failure costs a re-run rather than a re-tag.

Everything here is copied from that file, comments included — in particular the
byte-stream timeout, which was learned the expensive way and applies to every lane.

**Cost**: each lane is a full skill run — roughly $5-15 on `ANTHROPIC_API_KEY`, 5-20
minutes wall time. They carry the `e2e` marker, are excluded from the default suite, and
run only from `skill-quality.yml` (tag push or manual dispatch).

**Run one with `-s`** or it looks silent for the whole run:

    uv run pytest founder-skills/tests/test_e2e_market_sizing.py -v -m e2e --tb=short -s
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_PATH = REPO_ROOT / "founder-skills"
FIXTURES = REPO_ROOT / "founder-skills" / "tests" / "fixtures"


def detect_auth_kind() -> str:
    """Which credential the SDK will pick up, for the run preamble."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "ANTHROPIC_API_KEY"
    if os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"):
        return "CLAUDE_CODE_OAUTH_TOKEN"
    if (Path.home() / ".claude" / ".credentials.json").is_file():
        return "subscription (~/.claude/.credentials.json)"
    # macOS keeps subscription credentials in the Keychain rather than on disk.
    if os.uname().sysname == "Darwin":
        return "subscription (Keychain, unverified)"
    return "none"


PAID_OPT_IN_ENV = "RUN_PAID_E2E"


def paid_run_authorized() -> bool:
    """Has anyone actually ASKED for a billed run?

    A CREDENTIAL IS A CAPABILITY, NOT AN AUTHORIZATION, and conflating the two cost real
    money. `has_claude_auth()` returns True on **any** macOS host — the Keychain cannot be
    probed cheaply, so the check was deliberately permissive — which means "can this run?"
    was answered yes on every developer machine, and nothing else was asked. An audit that
    ran the default suite started two paid market-sizing runs against a subscription
    nobody had offered.

    So the credential check stays permissive (it exists to avoid a confusing skip) and
    THIS is the gate: an explicit `RUN_PAID_E2E=1`. Deselection in `addopts` is the other
    half; two independent gates, because the failure mode is spending someone else's money
    and one of them was already shown to be missing.
    """
    return os.environ.get(PAID_OPT_IN_ENV, "").strip().lower() in {"1", "true", "yes"}


def has_claude_auth() -> bool:
    """True when ANY of the three auth paths is available AND a paid run was authorized.

    Deliberately permissive about credentials: on macOS the subscription credential lives
    in the Keychain and cannot be probed cheaply, so we let the run start and fail loudly
    rather than skip a lane the operator believes is running. That permissiveness is
    exactly why the opt-in above is required — see `paid_run_authorized`.
    """
    if not paid_run_authorized():
        return False
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"):
        return True
    if (Path.home() / ".claude" / ".credentials.json").is_file():
        return True
    return os.uname().sysname == "Darwin"


def summarize_sdk_message(msg: object) -> str:
    """One line per SDK message, for `-s` progress. Never raises."""
    try:
        kind = type(msg).__name__
        content = getattr(msg, "content", None)
        if isinstance(content, list):
            parts: list[str] = []
            for block in content:
                name = getattr(block, "name", None)
                if name:
                    parts.append(f"tool:{name}")
                    continue
                text = getattr(block, "text", None)
                if isinstance(text, str) and text.strip():
                    parts.append(text.strip().replace("\n", " ")[:90])
            if parts:
                return f"{kind} | {' | '.join(parts)[:160]}"
        return f"{kind} | {str(msg)[:120]}"
    except Exception as exc:  # pragma: no cover - diagnostics only
        return f"<unsummarizable message: {exc}>"


def build_options(workdir: Path) -> Any:
    """SDK options shared by every lane.

    See `test_e2e_deck_review.py` for the full derivation of each field; the two that
    matter and are non-obvious:

    * `CLAUDE_PLUGIN_ROOT` — SKILL.md bodies reference `${CLAUDE_PLUGIN_ROOT}`. In
      production the plugin content expander substitutes it at load time; the SDK's
      plugin loader does not run that expander, so this is the harness-side workaround.
      The production invariant (no SKILL.md may depend on the SessionStart hook) is
      enforced separately by a contract test.

    * `CLAUDE_BYTE_STREAM_IDLE_TIMEOUT_MS` — the CLI runs TWO idle timeouts. The
      message-level one is floored at 5 min; the byte-level one is separate, is NOT
      floored, and is the one that fires here. At the default, a run aborted mid-dispatch
      with `API Error: Stream idle timeout`, surfacing through the SDK as
      `Exception: Claude Code returned an error result: success` — a contradiction that
      says nothing about the cause and costs ~8 minutes to reach. Read through
      `os.environ` rather than pinning, so a caller who sets it deliberately wins.
    """
    from claude_agent_sdk import ClaudeAgentOptions

    return ClaudeAgentOptions(  # type: ignore[call-arg]
        cwd=str(workdir),
        plugins=[{"type": "local", "path": str(PLUGIN_PATH)}],
        setting_sources=[],
        skills="all",
        allowed_tools=["Bash", "Read", "Write", "Edit", "Glob", "Grep", "Task", "Skill"],
        env={
            **os.environ,
            "CLAUDE_PLUGIN_ROOT": str(PLUGIN_PATH),
            "CLAUDE_BYTE_STREAM_IDLE_TIMEOUT_MS": os.environ.get("CLAUDE_BYTE_STREAM_IDLE_TIMEOUT_MS", "600000"),
        },
    )


def run_skill(prompt: str, workdir: Path, label: str) -> list[str]:
    """Drive one skill run to completion. Returns the captured message stream."""
    from claude_agent_sdk import query

    options = build_options(workdir)
    captured: list[str] = []

    print(f"\n[e2e:{label}] Auth detected: {detect_auth_kind()}", flush=True)
    print(f"[e2e:{label}] Plugin path:   {PLUGIN_PATH}", flush=True)
    print(f"[e2e:{label}] Workdir:       {workdir}", flush=True)
    print(f"[e2e:{label}] Prompt:        {prompt[:140]}{'...' if len(prompt) > 140 else ''}", flush=True)
    print(f"[e2e:{label}] --- starting SDK query (5-20 min) ---", flush=True)

    async def _run() -> None:
        count = 0
        async for msg in query(prompt=prompt, options=options):
            count += 1
            captured.append(str(msg))
            print(f"[e2e:{label} #{count:03d}] {summarize_sdk_message(msg)}", flush=True)
        print(f"[e2e:{label}] --- SDK loop complete ({count} messages) ---", flush=True)

    asyncio.run(_run())
    return captured


def locate_review_dir(workdir: Path, glob: str, captured: list[str], skill: str) -> Path:
    """Find the artifact directory the skill produced, or fail with a usable diagnostic.

    An empty artifacts root is almost always one of four things, and the message names
    all four because the alternative is re-running a paid lane to find out which.
    """
    artifacts_root = workdir / "artifacts"
    dirs = sorted(artifacts_root.glob(glob))
    if dirs:
        return dirs[0]
    contents = sorted(str(p.relative_to(workdir)) for p in workdir.rglob("*"))
    last = "\n".join(captured[-10:]) if captured else "(no messages)"
    skill_md = PLUGIN_PATH / "skills" / skill / "SKILL.md"
    raise AssertionError(
        f"{skill} e2e produced no artifacts matching {glob!r} under {artifacts_root}.\n"
        f"\nDiagnostics:\n"
        f"  workdir contents: {contents[:30]}{' (truncated)' if len(contents) > 30 else ''}\n"
        f"  SKILL.md readable: {skill_md.is_file() and os.access(skill_md, os.R_OK)} ({skill_md})\n"
        f"  total SDK messages: {len(captured)}\n"
        f"  last 10 messages:\n{last}\n"
        f"\nLikely causes:\n"
        f"  1. Model never invoked the {skill} skill (look at the messages above)\n"
        f"  2. Plugin not discovered (check the `plugins=[...]` API of the installed SDK)\n"
        f"  3. Bash subprocess failed at path resolution (check the env merge)\n"
        f"  4. Task tool not exposed, so the Context A dispatches failed\n"
    )


def assert_run_id_parity(review_dir: Path, artifacts: list[str]) -> None:
    """Every artifact this run wrote must carry the same run_id."""
    run_ids: set[str] = set()
    for name in artifacts:
        path = review_dir / name
        if not path.is_file():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            rid = (data.get("metadata") or {}).get("run_id")
            if rid:
                run_ids.add(str(rid))
    assert len(run_ids) == 1, f"run_id parity broken; artifacts carried {sorted(run_ids)}"


def assert_coaching_commentary_landed(review_dir: Path, payload_key: str) -> dict[str, Any]:
    """The point of a paid lane: a sub-agent READ the payload and wrote from it.

    Contract tests can assert the key is emitted and that both prompts name it. Only a
    live run can show that the coaching sub-agent received it, produced commentary, and
    that the deterministic insertion put that commentary into the delivered report. That
    gap is exactly why `payload_key` is passed in rather than assumed: each skill grew a
    top-level coverage field that qualifies its own headline, and a field nobody reads is
    the defect these lanes exist to catch.
    """
    report_json = review_dir / "report.json"
    report_md = review_dir / "report.md"
    assert report_json.is_file(), f"no report.json in {review_dir}"
    assert report_md.is_file(), f"no report.md in {review_dir}"

    report = json.loads(report_json.read_text(encoding="utf-8"))
    payload = report.get("coaching_payload")
    assert isinstance(payload, dict), "report.json carries no coaching_payload"
    assert "summary" in payload, "coaching_payload has no summary"
    assert payload_key in payload, (
        f"coaching_payload is missing top-level {payload_key!r} — the agent body tells the "
        f"coach to reason from it, so the commentary silently loses that qualification"
    )

    md = report_md.read_text(encoding="utf-8")
    assert "## Coaching Commentary" in md, (
        "report.md has no '## Coaching Commentary' heading — the Context B dispatch, its "
        "file hand-off, or the deterministic insertion did not complete"
    )
    body = md.split("## Coaching Commentary", 1)[1].strip()
    assert len(body) > 200, f"coaching commentary is only {len(body)}B — the sub-agent wrote nothing usable"
    # The marker is replaced in a single write-back; a surviving uuid means insertion ran
    # against the wrong file or the marker drifted.
    assert "insertion_marker" not in md, "report.md still carries the raw insertion marker"
    return payload
