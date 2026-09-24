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
import re
import shutil
from collections.abc import Sequence
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


def build_options(workdir: Path, env_extra: dict[str, str] | None = None) -> Any:
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
        # WebSearch is here for ONE dispatch: market-sizing's adversarial review, whose whole job
        # is finding a published figure that contradicts the analysis. Its agent declares the tool,
        # but this session-level list is the outer bound, so without it the lane could never
        # exercise that step -- MEASURED: a live run recorded `no_network_available` and skipped
        # it, which was the honest answer and also a permanent one. A lane that structurally
        # cannot run a step is not a smoke test of that step.
        #
        # It widens the surface for the other lanes that share this harness, which is the cost.
        # Accepted because the alternative is a market-sizing lane that green-lights a feature it
        # never touches -- and because production DOES offer it: tool allowlists are per-agent
        # there, so only the red-team agent receives it.
        allowed_tools=["Bash", "Read", "Write", "Edit", "Glob", "Grep", "Task", "Skill", "WebSearch"],
        env={
            **os.environ,
            "CLAUDE_PLUGIN_ROOT": str(PLUGIN_PATH),
            "CLAUDE_BYTE_STREAM_IDLE_TIMEOUT_MS": os.environ.get("CLAUDE_BYTE_STREAM_IDLE_TIMEOUT_MS", "600000"),
            **(env_extra or {}),
        },
    )


class RunCapture:
    """What one skill run left behind, in the shape the assertions need.

    `messages` is the stringified stream every lane already reads. `tool_uses` is the structured
    record: one entry per ToolUseBlock across every AssistantMessage, carrying the block's `id`,
    `name`, `input`, and the message's `parent_tool_use_id` -- non-null for a call a SUB-AGENT
    made, which is the only way to know what the red team actually opened rather than what it
    says it opened. `final_text` is the ResultMessage's `result`: the text the user received.

    A plain class, not a dataclass: test_skill_contract.py loads this module by file path
    without registering it in sys.modules, and a dataclass under postponed annotations cannot
    resolve its field types there.
    """

    def __init__(self) -> None:
        self.messages: list[str] = []
        self.tool_uses: list[dict[str, Any]] = []
        self.final_text: str = ""
        # Every founder-visible thing in stream order: {"kind": "text"|"tool_use"|"user", ...}.
        # `final_text` is the LAST message only; a block-then-rewrite from a Stop hook leaves the
        # first message on screen, so the lane judges everything the founder saw after a point.
        self.events: list[dict[str, Any]] = []

    def calls(self, name: str, *, parent: str | None = None) -> list[dict[str, Any]]:
        """Tool calls by name; with `parent`, only those made inside that dispatch."""
        return [
            t for t in self.tool_uses if t["name"] == name and (parent is None or t["parent_tool_use_id"] == parent)
        ]

    def text_after(self, tool_use_id: str, *, until_stop_feedback: bool = False) -> str:
        """Top-level assistant text after the named tool call, concatenated in order.

        With `until_stop_feedback`, stops at the first "Stop hook feedback:" user turn -- the
        message as the founder saw it BEFORE any hook sent the model back. Without it, the text
        after the LAST such turn: the model's latest attempt, which is what a correction is.
        (The faulted message is still on screen above it; a block appends, it does not retract.)
        """
        out: list[str] = []
        seen = False
        for ev in self.events:
            if ev["kind"] == "tool_use" and ev["id"] == tool_use_id:
                seen = True
                continue
            if not seen:
                continue
            if ev["kind"] == "user" and ev["text"].startswith("Stop hook feedback:"):
                if until_stop_feedback:
                    break
                out = []
                continue
            if ev["kind"] == "text" and ev["parent_tool_use_id"] is None:
                out.append(ev["text"])
        return "\n".join(out)

    def stop_hook_blocks(self) -> int:
        return sum(1 for ev in self.events if ev["kind"] == "user" and ev["text"].startswith("Stop hook feedback:"))


def run_skill(prompt: str, workdir: Path, label: str, uploads: Sequence[Path] = ()) -> list[str]:
    """Drive one skill run to completion. Returns the captured message stream.

    Kept for the lanes that read only the stream; `run_skill_capture` is the structured form.
    """
    return run_skill_capture(prompt, workdir, label, uploads).messages


def run_skill_capture(prompt: str, workdir: Path, label: str, uploads: Sequence[Path] = ()) -> RunCapture:
    """Drive one skill run to completion, with sub-agent tool calls attributed.

    `uploads` are copied to `<workdir>/mnt/uploads/` and `COWORK_UPLOADS_DIR` points there, which
    is the override `resolve_artifacts_root.py --uploads` honours outside a Cowork session tree.
    Without it the skill's document-reading steps run against nothing, and a lane that cannot
    attach a document cannot exercise the branch that failed live.
    """
    from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock, ToolUseBlock, UserMessage, query

    env_extra: dict[str, str] = {}
    if uploads:
        uploads_dir = workdir / "mnt" / "uploads"
        uploads_dir.mkdir(parents=True, exist_ok=True)
        for src in uploads:
            shutil.copy(src, uploads_dir / src.name)
        env_extra["COWORK_UPLOADS_DIR"] = str(uploads_dir)
    options = build_options(workdir, env_extra)
    cap = RunCapture()

    print(f"\n[e2e:{label}] Auth detected: {detect_auth_kind()}", flush=True)
    print(f"[e2e:{label}] Plugin path:   {PLUGIN_PATH}", flush=True)
    print(f"[e2e:{label}] Workdir:       {workdir}", flush=True)
    if uploads:
        print(f"[e2e:{label}] Uploads:       {', '.join(p.name for p in uploads)}", flush=True)
    print(f"[e2e:{label}] Prompt:        {prompt[:140]}{'...' if len(prompt) > 140 else ''}", flush=True)
    print(f"[e2e:{label}] --- starting SDK query (5-20 min) ---", flush=True)

    async def _run() -> None:
        count = 0
        async for msg in query(prompt=prompt, options=options):
            count += 1
            cap.messages.append(str(msg))
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, ToolUseBlock):
                        call = {
                            "id": block.id,
                            "name": block.name,
                            "input": block.input,
                            "parent_tool_use_id": msg.parent_tool_use_id,
                        }
                        cap.tool_uses.append(call)
                        cap.events.append({"kind": "tool_use", **call})
                    elif isinstance(block, TextBlock):
                        cap.events.append(
                            {"kind": "text", "text": block.text, "parent_tool_use_id": msg.parent_tool_use_id}
                        )
            elif isinstance(msg, UserMessage):
                # A Stop hook's block arrives as a user turn "Stop hook feedback:\n<reason>".
                content = msg.content
                text = (
                    content
                    if isinstance(content, str)
                    else " ".join(getattr(b, "text", "") for b in content if isinstance(getattr(b, "text", None), str))
                )
                cap.events.append({"kind": "user", "text": text, "parent_tool_use_id": msg.parent_tool_use_id})
            elif isinstance(msg, ResultMessage) and isinstance(msg.result, str):
                cap.final_text = msg.result
            print(f"[e2e:{label} #{count:03d}] {summarize_sdk_message(msg)}", flush=True)
        print(f"[e2e:{label}] --- SDK loop complete ({count} messages) ---", flush=True)

    asyncio.run(_run())
    return cap


def step_summary(text: str) -> None:
    """Append a note to GitHub's per-job summary. No-op outside Actions.

    Evidence, not decoration. Every failure of this lane so far reported a COUNT of criteria that
    were not assessed, and the runner's workspace -- the only place the identity lived -- was
    destroyed with the job, so the same failure was investigated twice and the criterion recovered
    neither time. A line here survives the job, on a surface a human already opens.
    """
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    try:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(text.rstrip() + "\n")
    except OSError:
        # Never fail a paid run over its own logging.
        pass


def model_from_capture(captured: list[str]) -> str:
    """The model the graded turn actually ran on, out of the SDK's init message.

    Not available from `summarize_sdk_message`, which truncates its PRINTED line at 120 chars --
    but `run_skill` keeps the full `str(msg)` in `captured`, so nothing in the harness has to
    change to recover it. Worth recording on every run: this lane pins no model, so a green and a
    red can come from different ones and nothing else would say so.
    """
    for line in captured:
        # Scoped to the init frame. Scanning every message would take the first `"model":` anywhere
        # -- a tool result, a JSON echo, a prompt quoting the word -- and return a wrong-but-
        # plausible answer in the one field added to say which experiment ran.
        if "subtype='init'" not in line and '"subtype": "init"' not in line:
            continue
        match = re.search(r"['\"]model['\"]:\s*['\"]([^'\"]+)['\"]", line)
        if match:
            return match.group(1)
    return "unknown"


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
    # Bound at the footer before measuring. `compose_report.py` appends ~400 chars of boilerplate
    # after the coaching marker, and `insert_coaching.py` replaces the marker in place -- so the
    # unbounded slice measured `len(commentary) + 399` and ANY commentary of one character passed
    # this check. (It could never be zero: `insert_coaching.py` refuses a missing or whitespace-only
    # `commentary_markdown` before it writes.) `rsplit`, because a `---` inside the commentary must
    # not move the boundary.
    body = md.split("## Coaching Commentary", 1)[1]
    # `rsplit` on a MISSING separator returns the whole string, which would silently restore the
    # vacuous measurement this bound exists to remove -- so the anchor is asserted, not assumed.
    # It differs per skill: fmr and market-sizing emit `\n\n---\n*Generated by`, cap-table joins
    # its footer line-by-line and emits a blank line more. Match the shortest stable form and
    # require exactly one of it.
    anchor = "---\n\n*Generated by" if md.count("---\n\n*Generated by") == 1 else "---\n*Generated by"
    assert md.count(anchor) == 1, (
        f"the report footer anchor {anchor!r} appears {md.count(anchor)} times; the commentary "
        "length below would measure the footer as commentary"
    )
    body = body.rsplit(anchor, 1)[0].strip()
    assert len(body) > 200, f"coaching commentary is only {len(body)}B — the sub-agent wrote nothing usable"
    # The marker is replaced in a single write-back; a surviving uuid means insertion ran
    # against the wrong file or the marker drifted.
    assert "insertion_marker" not in md, "report.md still carries the raw insertion marker"
    return payload
