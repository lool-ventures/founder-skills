"""`dispatch_prompt_check.py`: the review's instructions are sent as the generator printed them.

In round 2 of both live runs that reached it, the main thread ran `dispatch_prompt.py`, then sent the
reviewer a different prompt: six extra lines naming the revision and what to look for ("Note: this is a
round-2 review after a revision. In round 1, the ARPU input was changed from $X/month…"). The
reviewer repeated it to the founder ("the revised $Y…"). Round 1 matched both times. SKILL.md says to
paste the printed text unchanged; that held 0/2 in round 2.

The comparand is the generator's output as the transcript recorded it -- the runtime writes both that
and the dispatched prompt, so nothing the model writes can make them agree. Exercised through the
PreToolUse dispatcher's POSIX wrapper, with transcripts shaped like the session JSONL.
"""

from __future__ import annotations

import itertools
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
WRAPPER = SCRIPTS / "pretooluse-dispatch.sh"
MARKER = "[dispatch-check]"

_GENERATED = (
    "CONTEXT: RED_TEAM\n"
    "OUTPUT_PATH: agent/handoff/R/r2/redteam_output.json\n"
    "RUN_ID: R\n"
    "\n"
    "Read the founder's documents first:\n"
    "  agent/docs/deck.pdf\n"
    "Then read the analysis's artifacts.\n"
    "Write your findings to OUTPUT_PATH in the shape your agent body specifies, then return ONLY\n"
    'the receipt JSON in your final assistant message:\n{"status": "complete"}\n'
    "Do NOT write any file other than OUTPUT_PATH.\n"
)
_STEERED = _GENERATED.replace(
    "Then read the analysis's artifacts.\n",
    "Then read the analysis's artifacts.\nNote: this is a round-2 review after a revision. Check the new ARPU.\n",
)


def _user(text: str) -> dict[str, Any]:
    return {"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": text}]}}


_IDS = itertools.count()
# A generator call as SKILL.md prescribes it. The comparand is only ever a result paired with such a call.
GEN_CMD = (
    'python3 "$SCRIPTS/dispatch_prompt.py" red_team --run-id "$RUN_ID" \\\n'
    '  --analysis-dir "$ANALYSIS_DIR" --handoff-dir "$HANDOFF_DIR" --handoff-agent "agent/handoff/R"'
)


def _call(name: str, tool_input: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    uid = f"toolu_{next(_IDS)}"
    row = {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [{"type": "tool_use", "id": uid, "name": name, "input": tool_input}],
        },
    }
    return uid, row


def _result(uid: str, text: str, is_error: bool = False) -> dict[str, Any]:
    block: dict[str, Any] = {"type": "tool_result", "tool_use_id": uid, "content": text}
    if is_error:
        block["is_error"] = True
    return {"type": "user", "message": {"role": "user", "content": [block]}}


def _printed(text: str, command: str = GEN_CMD, tool: str = "Bash") -> list[dict[str, Any]]:
    """A shell call running the generator, and its result."""
    uid, use = _call(tool, {"command": command})
    return [use, _result(uid, text)]


def _read(path: str, text: str) -> list[dict[str, Any]]:
    """A Read of `path`, and its result as the Read tool numbers it."""
    uid, use = _call("Read", {"file_path": path})
    return [use, _result(uid, "".join(f"{n}\t{line}\n" for n, line in enumerate(text.splitlines(), 1)))]


def _held(reason: str) -> dict[str, Any]:
    return {
        "type": "user",
        "message": {"role": "user", "content": [{"type": "tool_result", "is_error": True, "content": reason}]},
    }


def _run(tmp_path: Path, rows: list[dict[str, Any]], prompt: str, tool: str = "Agent", agent: str | None = None) -> Any:
    path = tmp_path / "t.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    payload = {
        "transcript_path": str(path),
        "cwd": str(tmp_path),
        "hook_event_name": "PreToolUse",
        "tool_name": tool,
        # The agent a real run dispatches each context to (the e2e and critique transcripts).
        "tool_input": {
            "prompt": prompt,
            "subagent_type": agent
            or (
                "founder-skills:market-sizing"
                if prompt.lstrip().startswith("CONTEXT: CHECKLIST")
                else "founder-skills:market-sizing-redteam"
            ),
        },
    }
    return subprocess.run(["sh", str(WRAPPER)], input=json.dumps(payload), capture_output=True, text=True, timeout=30)


def _deny(r: Any) -> str:
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)["hookSpecificOutput"]
    assert out["permissionDecision"] == "deny"
    reason: str = out["permissionDecisionReason"]
    return reason


def _silent(r: Any) -> None:
    assert r.returncode == 0 and r.stdout == "", r


def test_the_printed_prompt_goes_through(tmp_path: Path) -> None:
    """Positive control: round 1 on both live runs, and whitespace the model re-flowed."""
    rows = [_user("Size my market."), *_printed(_GENERATED)]
    _silent(_run(tmp_path, rows, _GENERATED))
    _silent(_run(tmp_path, rows, "  " + _GENERATED.replace("\n", "\n  ")))


def test_a_prompt_with_lines_added_is_held_with_the_printed_one(tmp_path: Path) -> None:
    reason = _deny(_run(tmp_path, [_user("Size my market."), *_printed(_GENERATED)], _STEERED))
    assert MARKER in reason
    # The reason carries the printed prompt whole, so the retry can be exactly it.
    assert "Do NOT write any file other than OUTPUT_PATH." in reason
    assert "round-2 review after a revision" not in reason


def test_a_prompt_with_lines_removed_is_held(tmp_path: Path) -> None:
    trimmed = _GENERATED.replace("Read the founder's documents first:\n  agent/docs/deck.pdf\n", "")
    _deny(_run(tmp_path, [_user("Size my market."), *_printed(_GENERATED)], trimmed))


def test_a_stale_round_sent_verbatim_to_its_own_path_passes(tmp_path: Path) -> None:
    """The comparand is the latest printed prompt for the dispatch's OWN OUTPUT_PATH. Round 1's prompt
    sent unchanged to round 1's path carries no added framing, the only class this hook stops; the
    missing round-2 hand-off then fails check_handoff for the r2 path. (This test used to expect a hold:
    the comparand was the latest printed prompt for the context, whatever its path.)"""
    round_1 = _GENERATED.replace("/r2/", "/")
    rows = [_user("Size my market."), *_printed(round_1), *_printed(_GENERATED)]
    _silent(_run(tmp_path, rows, _GENERATED))
    _silent(_run(tmp_path, rows, round_1))


def test_the_latest_printed_prompt_for_this_path_wins(tmp_path: Path) -> None:
    """Two prompts printed for the SAME path: the later one is the comparand."""
    earlier = _GENERATED.replace("Read the founder's documents first:", "Read these first:")
    rows = [_user("Size my market."), *_printed(earlier), *_printed(_GENERATED)]
    _silent(_run(tmp_path, rows, _GENERATED))
    reason = _deny(_run(tmp_path, rows, earlier))
    assert "Read the founder's documents first:" in reason


def test_no_printed_prompt_is_held_until_the_generator_runs(tmp_path: Path) -> None:
    """The remedy is to run the generator, which is what puts the comparand in the transcript."""
    reason = _deny(_run(tmp_path, [_user("Size my market.")], _GENERATED))
    assert "prompt generator" in reason


def test_a_round_is_held_at_most_twice(tmp_path: Path) -> None:
    rows = [_user("Size my market."), *_printed(_GENERATED)]
    first = _deny(_run(tmp_path, rows, _STEERED))
    rows.append(_held(first))
    second = _deny(_run(tmp_path, rows, _STEERED))
    rows.append(_held(second))
    r = _run(tmp_path, rows, _STEERED)
    _silent(r)
    assert "dispatch_prompt_check" in r.stderr


def test_holds_are_counted_per_round(tmp_path: Path) -> None:
    """Round 1's holds do not spend round 2's: the only real prompts in a run are its first and last,
    so a count per prompt spans both rounds (the adversarial review's finding on the design)."""
    round_1 = _GENERATED.replace("/r2/", "/")
    rows = [
        _user("Size my market."),
        *_printed(round_1),
        _held(f"{MARKER}[agent/handoff/R/redteam_output.json] x"),
        _held(f"{MARKER}[agent/handoff/R/redteam_output.json] x"),
        *_printed(_GENERATED),
    ]
    _deny(_run(tmp_path, rows, _STEERED))


def test_other_dispatches_and_tools_are_silent(tmp_path: Path) -> None:
    rows = [_user("x"), *_printed(_GENERATED)]
    _silent(_run(tmp_path, rows, "CONTEXT: SENSITIVITY_TEST\nOUTPUT_PATH: x\n", agent="founder-skills:market-sizing"))
    _silent(_run(tmp_path, rows, _STEERED, tool="Bash"))


def test_the_dispatcher_is_the_one_declared_hook_for_dispatches() -> None:
    manifest = json.loads((SCRIPTS.parent / ".claude-plugin" / "plugin.json").read_text())
    entries = manifest["hooks"]["PreToolUse"]
    assert len(entries) == 1
    assert set(entries[0]["matcher"].split("|")) == {"Agent", "Task"}
    assert [h["command"].rsplit("/", 1)[-1] for h in entries[0]["hooks"]] == ["pretooluse-dispatch.sh"]


def test_a_prompt_read_back_from_its_file_counts_as_printed(tmp_path: Path) -> None:
    """A run redirected the generator's output into a file and read it back with the Read tool, whose
    result numbers every line ("1\\tCONTEXT: RED_TEAM"). Round 1 matched; the check must see that it did.
    The file is paired with the generator call through the block's own assignments."""
    cmd = 'H="/w/handoff/R"\n' + GEN_CMD + ' > "$H/redteam_prompt.txt"\necho "EXIT=$?"'
    rows = [
        _user("Size my market."),
        *_printed("EXIT=0\n", command=cmd),
        *_read("/w/handoff/R/redteam_prompt.txt", _GENERATED),
    ]
    _silent(_run(tmp_path, rows, _GENERATED))
    _deny(_run(tmp_path, rows, _STEERED))


_CHECKLIST_PRINTED = (
    "CONTEXT: CHECKLIST\nOUTPUT_PATH: agent/handoff/R/checklist_output.json\nRUN_ID: R\n\n"
    "Read:\n- agent/handoff/R/checklist_view/methodology.json\nAssess all 22 items.\n"
    "Do NOT write any file other than OUTPUT_PATH.\n"
)


def test_a_checklist_dispatch_is_held_to_its_printed_prompt(tmp_path: Path) -> None:
    rows = [_user("Size my market."), *_printed(_CHECKLIST_PRINTED)]
    _silent(_run(tmp_path, rows, _CHECKLIST_PRINTED))
    steered = _CHECKLIST_PRINTED.replace("Assess all 22 items.\n", "Assess all 22 items. Round 2: score reconciled.\n")
    reason = _deny(_run(tmp_path, rows, steered))
    assert "Assess all 22 items." in reason and "Round 2" not in reason


# --- another skill's CHECKLIST is not ours (found in review, 2026-09-27) ------------------------------


# Skills whose CHECKLIST prompt opens with the same line and has NO generator. competitive-positioning
# left this list when cp_dispatch_prompt.py began printing its CHECKLIST prompt; its own pair is below.
_OTHER_SKILLS = ("deck-review", "financial-model-review")
_THEIR_CHECKLIST = "CONTEXT: CHECKLIST\nOUTPUT_PATH: agent/handoff/R/checklist_output.json\n\nScore the criteria.\n"


def test_another_skills_checklist_dispatch_is_never_held(tmp_path: Path) -> None:
    """Three other skills' CHECKLIST templates open with the same line and have no generator: matched on
    the prefix alone, each was held for a prompt that cannot exist."""
    for skill in _OTHER_SKILLS:
        _silent(_run(tmp_path, [_user("Review my deck.")], _THEIR_CHECKLIST, agent=f"founder-skills:{skill}"))


def test_another_skill_is_never_handed_market_sizings_prompt(tmp_path: Path) -> None:
    """Worse: after a market-sizing CHECKLIST earlier in the session, the other skill's dispatch was held
    with market-sizing's prompt and OUTPUT_PATH as the one to send."""
    rows = [_user("Size my market."), *_printed(_CHECKLIST_PRINTED), _user("Now review my deck.")]
    for skill in _OTHER_SKILLS:
        _silent(_run(tmp_path, rows, _THEIR_CHECKLIST, agent=f"founder-skills:{skill}"))
    # competitive-positioning now has a generator, so its unprinted dispatch IS held -- but told to run
    # its own generator, never handed market-sizing's prompt or path. Its OUTPUT_PATH is its own: the
    # comparand is scoped by path, and two skills never share a hand-off dir because the resolver names
    # each after its skill (`--dir-name <skill>-<slug>`). That per-skill dir is what this relies on.
    cp_checklist = _THEIR_CHECKLIST.replace("agent/handoff/R/", "agent/competitive-positioning-acme/handoff/R/")
    reason = _deny(_run(tmp_path, rows, cp_checklist, agent="founder-skills:competitive-positioning"))
    assert "no printed prompt" in reason
    assert "checklist_view/methodology.json" not in reason and "Assess all 22 items" not in reason


def test_market_sizings_checklist_is_still_held_under_another_namespace(tmp_path: Path) -> None:
    """Positive control: the agent is matched by name, not by the plugin prefix a runtime puts on it."""
    rows = [_user("Size my market."), *_printed(_CHECKLIST_PRINTED)]
    steered = _CHECKLIST_PRINTED.replace("Assess all 22 items.\n", "Assess all 22 items. Round 2.\n")
    _deny(_run(tmp_path, rows, steered, agent="market-sizing"))


# --- an OUTPUT_PATH containing a space ---------------------------------------
# Local-lane absolute paths contain "Application Support". The key used to be captured with `\S+`,
# so every such path became ".../Library/Application" and all rounds shared one hold budget.

_SPACED_1 = _GENERATED.replace(
    "OUTPUT_PATH: agent/handoff/R/r2/redteam_output.json",
    "OUTPUT_PATH: /Users/x/Library/Application Support/Claude/handoff/R/redteam_output.json",
)
_SPACED_2 = _SPACED_1.replace("/handoff/R/redteam_output.json", "/handoff/R/r2/redteam_output.json")


def test_paths_with_a_space_do_not_share_a_hold_budget(tmp_path: Path) -> None:
    held_1 = "[dispatch-check][/Users/x/Library/Application Support/Claude/handoff/R/redteam_output.json] x"
    steered_2 = _SPACED_2.replace("Then read the analysis's artifacts.\n", "Then read it.\nFocus on ARPU.\n")
    rows = [_user("Size my market."), *_printed(_SPACED_1), _held(held_1), _held(held_1), *_printed(_SPACED_2)]
    # Round 1's two holds must not have spent round 2's budget.
    _deny(_run(tmp_path, rows, steered_2))


def test_the_old_capture_would_have_merged_them() -> None:
    """Negative control: the previous regex reduced both paths to the same key."""
    import re

    old = re.compile(r"^OUTPUT_PATH:\s*(\S+)", re.MULTILINE)
    k1, k2 = old.search(_SPACED_1), old.search(_SPACED_2)
    assert k1 is not None and k2 is not None
    assert k1.group(1) == k2.group(1) == "/Users/x/Library/Application"


# --- the comparand is scoped by OUTPUT_PATH ----------------------------------


def test_a_prompt_printed_for_another_path_is_not_the_comparand(tmp_path: Path) -> None:
    """Another skill's (or round's) printed prompt must never be handed back as the one to send."""
    theirs = _CHECKLIST_PRINTED.replace(
        "agent/handoff/R/checklist_output.json", "other/handoff/R/checklist_output.json"
    )
    rows = [_user("Size my market."), *_printed(theirs)]
    reason = _deny(_run(tmp_path, rows, _CHECKLIST_PRINTED, agent="founder-skills:market-sizing"))
    assert "no printed prompt" in reason
    assert "other/handoff" not in reason


def test_a_template_read_from_a_skill_file_is_not_the_comparand(tmp_path: Path) -> None:
    """A Read of SKILL.md shows the template with a placeholder path. It is no generator's output, and no
    real path equals the placeholder either."""
    template = _CHECKLIST_PRINTED.replace(
        "agent/handoff/R/checklist_output.json", "<HANDOFF_AGENT>/checklist_output.json"
    )
    rows = [_user("Size my market."), *_read("/plugin/skills/market-sizing/SKILL.md", template)]
    reason = _deny(_run(tmp_path, rows, _CHECKLIST_PRINTED, agent="founder-skills:market-sizing"))
    assert "<HANDOFF_AGENT>" not in reason


def test_a_steered_dispatch_is_still_held_with_its_own_printed_prompt(tmp_path: Path) -> None:
    """Positive control: the framing guarantee is unchanged."""
    rows = [_user("Size my market."), *_printed(_GENERATED)]
    reason = _deny(_run(tmp_path, rows, _STEERED))
    assert "the review looks at the analysis" in reason


def test_a_second_skills_pair_is_independent(tmp_path: Path) -> None:
    """Two pairs sharing a context line, each checked against its own printed prompt only. A pair is
    registered in-process here (test only), exercising the table the next skill's pairs will join."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("dpc_pairs_under_test", SCRIPTS / "dispatch_prompt_check.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.PAIRS[("CONTEXT: CHECKLIST", "second-skill")] = "the second skill's reason"

    ours = _CHECKLIST_PRINTED
    theirs = _CHECKLIST_PRINTED.replace("agent/handoff/R/", "second/handoff/R/")
    transcript = tmp_path / "t.jsonl"
    transcript.write_text(
        "\n".join(json.dumps(r) for r in [_user("go"), *_printed(ours), *_printed(theirs)]) + "\n", encoding="utf-8"
    )

    def decide(prompt: str, agent: str) -> Any:
        return mod.decide(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Agent",
                "transcript_path": str(transcript),
                "tool_input": {"prompt": prompt, "subagent_type": f"founder-skills:{agent}"},
            }
        )

    assert decide(ours, "market-sizing") is None
    assert decide(theirs, "second-skill") is None
    held = decide(theirs + "Extra framing.\n", "second-skill")
    assert held is not None
    reason = held["hookSpecificOutput"]["permissionDecisionReason"]
    assert "the second skill's reason" in reason and "second/handoff" in reason and "agent/handoff" not in reason


# --- competitive-positioning's RED_TEAM: the same context line, its own agent and printed prompt ------


def _cp_red_team_prompt(tmp_path: Path) -> str:
    """The prompt as cp_dispatch_prompt.py prints it, so the check is exercised on the real output."""
    import sys

    analysis = tmp_path / "cp-analysis"
    handoff = tmp_path / "cp-handoff"
    (handoff / "docs").mkdir(parents=True)
    analysis.mkdir()
    for name in ("product_profile", "landscape", "positioning_scores", "moat_scores"):
        (analysis / f"{name}.json").write_text("{}", encoding="utf-8")
    (handoff / "docs" / "deck.md").write_text("deck", encoding="utf-8")
    gen = (
        Path(__file__).resolve().parents[1] / "skills" / "competitive-positioning" / "scripts" / "cp_dispatch_prompt.py"
    )
    r = subprocess.run(
        [
            sys.executable,
            str(gen),
            "red_team",
            "--run-id",
            "R",
            "--handoff-agent",
            "agent/competitive-positioning-acme/handoff/R",
            "--analysis-dir-agent",
            "agent/competitive-positioning-acme",
            "--analysis-dir",
            str(analysis),
            "--handoff-dir",
            str(handoff),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert r.returncode == 0, r.stderr
    return r.stdout


_CP_REDTEAM = "founder-skills:competitive-positioning-redteam"


def test_competitive_positionings_printed_red_team_prompt_goes_through(tmp_path: Path) -> None:
    ours = _cp_red_team_prompt(tmp_path)
    rows = [_user("Map my competition."), *_printed(_GENERATED), *_printed(ours)]
    _silent(_run(tmp_path, rows, ours, agent=_CP_REDTEAM))


def test_competitive_positionings_red_team_is_held_to_its_own_printed_prompt(tmp_path: Path) -> None:
    """Market-sizing's red-team prompt, printed in the same session, is never the comparand: the
    reason carries competitive-positioning's own prompt and path."""
    ours = _cp_red_team_prompt(tmp_path)
    steered = ours.replace("You are not told what to attack.", "Focus on the patent.\nYou are not told what to attack.")
    rows = [_user("Map my competition."), *_printed(_GENERATED), *_printed(ours)]
    reason = _deny(_run(tmp_path, rows, steered, agent=_CP_REDTEAM))
    assert "the review looks at the analysis" in reason
    assert "competitive-positioning-acme/handoff/R/redteam_output.json" in reason
    assert "agent/handoff/R/r2/redteam_output.json" not in reason


def test_competitive_positionings_red_team_prompt_sent_to_another_agent_is_held_for_the_reviewer(
    tmp_path: Path,
) -> None:
    """The pair is (context line, agent), so the red-team prompt sent to the scoring agent used to pass
    unchecked, reaching a reviewer that carries the rubric the review exists to escape. The agent check
    now holds it and names the reviewer."""
    ours = _cp_red_team_prompt(tmp_path)
    rows = [_user("Map my competition."), *_printed(ours)]
    reason = _deny(_run(tmp_path, rows, ours + "Extra.\n", agent="founder-skills:competitive-positioning"))
    assert '"founder-skills:competitive-positioning-redteam"' in reason


def test_a_red_team_prompt_carrying_the_reports_positions_passes_and_a_changed_one_is_held(tmp_path: Path) -> None:
    """The prompt quotes the report's "Where you stand" sentences (names, dashes, quotes): the check still
    compares it whole, so the printed prompt passes and one with a position reworded is held."""
    import shutil
    import sys

    from test_competitive_positioning import _make_valid_positioning_input

    fixtures = Path(__file__).resolve().parent / "fixtures" / "competitive-positioning"
    scripts = Path(__file__).resolve().parents[1] / "skills" / "competitive-positioning" / "scripts"
    analysis = tmp_path / "cp-analysis"
    handoff = tmp_path / "cp-handoff"
    (handoff / "docs").mkdir(parents=True)
    analysis.mkdir()
    for name in ("product_profile", "landscape", "moat_scores"):
        shutil.copy(fixtures / f"{name}.json", analysis / f"{name}.json")
    # Scored for real, so the positions carry the geometry the report's sentences are built from.
    scored = subprocess.run(
        [
            sys.executable,
            str(scripts / "score_positioning.py"),
            "--run-id",
            "R",
            "-o",
            str(analysis / "positioning_scores.json"),
        ],
        input=json.dumps(_make_valid_positioning_input()),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert scored.returncode == 0, scored.stderr
    gen = scripts / "cp_dispatch_prompt.py"
    r = subprocess.run(
        [
            sys.executable,
            str(gen),
            "red_team",
            "--run-id",
            "R",
            "--handoff-agent",
            "agent/competitive-positioning-acme/handoff/R",
            "--analysis-dir-agent",
            "agent/competitive-positioning-acme",
            "--analysis-dir",
            str(analysis),
            "--handoff-dir",
            str(handoff),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert r.returncode == 0, r.stderr
    ours = r.stdout
    assert "What the report tells the founder about where they stand" in ours, "the fixture must yield positions"
    rows = [_user("Map my competition."), *_printed(ours)]
    _silent(_run(tmp_path, rows, ours, agent=_CP_REDTEAM))
    line = next(ln for ln in ours.splitlines() if ln.startswith("  - "))
    reworded = ours.replace(line, line.replace("of ", "out of ", 1))
    assert reworded != ours
    _deny(_run(tmp_path, rows, reworded, agent=_CP_REDTEAM))


# --- a prompt printed on a local Desktop session names no plugin folder ------------------------------


def _session_prompt(tmp_path: Path, which: str) -> str:
    """The real generator output on a /sessions tree: reference files are named by how their path ends."""
    import importlib.util

    skills = Path(__file__).resolve().parents[1] / "skills"
    gen = (
        skills / "market-sizing" / "scripts" / "dispatch_prompt.py"
        if which == "market-sizing"
        else skills / "competitive-positioning" / "scripts" / "cp_dispatch_prompt.py"
    )
    spec = importlib.util.spec_from_file_location(f"session_gen_{gen.stem}", gen)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if which == "market-sizing":
        analysis = tmp_path / "ms-analysis"
        analysis.mkdir()
        for f in ("inputs.json", "methodology.json", "validation.json", "sizing.json"):
            (analysis / f).write_text("{}", encoding="utf-8")
        text: str = mod.checklist(
            "R", str(analysis), str(tmp_path / "ms-h"), "agent/handoff/R", "agent/analysis", session_tree=True
        )
    else:
        text = mod.render(
            "moat_scoring",
            run_id="R",
            handoff_agent="agent/cp/handoff/R",
            analysis_dir_agent="agent/cp",
            session_tree=True,
        )
    assert "/sessions" not in text and "the file ending skills/" in text
    return text


def test_a_session_lane_prompt_passes_verbatim_for_both_generators(tmp_path: Path) -> None:
    ms = _session_prompt(tmp_path, "market-sizing")
    _silent(_run(tmp_path, [_user("Size my market."), *_printed(ms)], ms))
    cp = _session_prompt(tmp_path, "competitive-positioning")
    _silent(
        _run(
            tmp_path, [_user("Map my competition."), *_printed(cp)], cp, agent="founder-skills:competitive-positioning"
        )
    )


def test_a_root_put_back_into_a_session_lane_prompt_is_held_twice_then_let_through(tmp_path: Path) -> None:
    """A main thread that "repairs" the pointer with a folder of its own is sent the printed prompt back,
    twice; the third attempt goes through with a line on stderr (MAX_HOLDS)."""
    printed = _session_prompt(tmp_path, "market-sizing")
    rooted = printed.replace("the file ending skills/", "/Users/x/plugin/skills/")
    rows = [_user("Size my market."), *_printed(printed)]
    first = _deny(_run(tmp_path, rows, rooted))
    assert "the file ending skills/market-sizing/references/pitfalls-checklist.md" in first
    assert "/Users/x/plugin" not in first
    rows.append(_held(first))
    rows.append(_held(_deny(_run(tmp_path, rows, rooted))))
    r = _run(tmp_path, rows, rooted)
    _silent(r)
    assert "dispatch_prompt_check" in r.stderr


# --- the comparand is only ever the generator's own output -------------------------------------------


def test_a_result_with_no_call_paired_to_it_is_not_the_comparand(tmp_path: Path) -> None:
    """A tool result is matched to the call that produced it by tool id; an orphan proves nothing."""
    orphan = {"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "content": _GENERATED}]}}
    reason = _deny(_run(tmp_path, [_user("Size my market."), orphan], _GENERATED))
    assert "no printed prompt" in reason


def test_a_file_the_model_wrote_and_read_back_is_not_the_comparand(tmp_path: Path) -> None:
    """The model writes its own prompt with the Write tool and reads it back: no generator printed it."""
    uid, write = _call("Write", {"file_path": "/w/prompt.txt", "content": _STEERED})
    rows = [_user("Size my market."), write, _result(uid, "ok"), *_read("/w/prompt.txt", _STEERED)]
    reason = _deny(_run(tmp_path, rows, _STEERED))
    assert "no printed prompt" in reason


def test_a_generator_file_rewritten_before_the_read_is_not_the_comparand(tmp_path: Path) -> None:
    """The generator wrote the file, then the model overwrote it: the Read shows the model's text."""
    cmd = GEN_CMD + " > /w/redteam_prompt.txt"
    uid, edit = _call("Write", {"file_path": "/w/redteam_prompt.txt", "content": _STEERED})
    rows = [
        _user("Size my market."),
        *_printed("", command=cmd),
        edit,
        _result(uid, "ok"),
        *_read("/w/redteam_prompt.txt", _STEERED),
    ]
    reason = _deny(_run(tmp_path, rows, _STEERED))
    assert "no printed prompt" in reason
    # Positive control: without the overwrite, the same Read is the comparand.
    clean = [_user("Size my market."), *_printed("", command=cmd), *_read("/w/redteam_prompt.txt", _GENERATED)]
    _silent(_run(tmp_path, clean, _GENERATED))


@pytest.mark.parametrize(
    "tail",
    ["; cat /w/forged.txt", "\nprintf '%s' \"$(cat /w/forged.txt)\"", " && head -40 /w/forged.txt", "\ngrep . /w/f"],
)
def test_a_text_printed_after_the_generator_in_the_same_block_is_not_the_comparand(tmp_path: Path, tail: str) -> None:
    """The search takes the last context line in a result, so `generator; cat forged.txt` would make the
    forged text the comparand. A block that prints text of its own is never accepted."""
    rows = [_user("Size my market."), *_printed(_GENERATED + "\n" + _STEERED, command=GEN_CMD + tail)]
    reason = _deny(_run(tmp_path, rows, _STEERED))
    assert "no printed prompt" in reason


def test_a_sub_agents_reply_is_not_the_comparand(tmp_path: Path) -> None:
    """A sub-agent that echoes a prompt back in its reply is not the generator."""
    uid, agent = _call("Agent", {"prompt": "x", "subagent_type": "founder-skills:market-sizing"})
    rows = [_user("Size my market."), agent, _result(uid, _STEERED)]
    reason = _deny(_run(tmp_path, rows, _STEERED))
    assert "no printed prompt" in reason


@pytest.mark.parametrize(
    "command",
    [
        GEN_CMD,
        'RUN_ID="R"\n' + GEN_CMD + '\necho "EXIT=$?"',
        'python3 "$SCRIPTS/ocr_uploads.py" --uploads-dir d --out o 2>&1 | tail -5\n' + GEN_CMD,
        'U=$(python3 /p/resolve_artifacts_root.py --uploads)\necho "mirror: $U"\n' + GEN_CMD + " 2>&1",
        'mkdir -p "$HANDOFF_DIR/docs" && cp "/u"/* "$HANDOFF_DIR/docs/"\n' + GEN_CMD,
        "cd /w && " + GEN_CMD.replace("dispatch_prompt.py", "cp_dispatch_prompt.py"),
        GEN_CMD.replace("dispatch_prompt.py", "fmr_dispatch_prompt.py"),
    ],
)
def test_the_blocks_runs_use_are_accepted(tmp_path: Path, command: str) -> None:
    """Shapes seen around the generator in kept runs: assignments, an exit-code echo, a piped `tail` on
    another script's output, the uploads mirror. Each leaves the generator's output the comparand."""
    _silent(_run(tmp_path, [_user("Size my market."), *_printed(_GENERATED, command=command)], _GENERATED))


@pytest.mark.parametrize("extra", ['echo "$NOTE"', 'echo "CONTEXT: RED_TEAM"', 'N="CONTEXT: RED_TEAM"; echo "$N"'])
def test_an_echo_of_an_unset_variable_or_a_context_line_is_text_of_its_own(tmp_path: Path, extra: str) -> None:
    rows = [_user("Size my market."), *_printed(_GENERATED, command=GEN_CMD + "\n" + extra)]
    _deny(_run(tmp_path, rows, _GENERATED))


def test_the_shell_tool_under_its_cowork_name_counts(tmp_path: Path) -> None:
    rows = [_user("Size my market."), *_printed(_GENERATED, tool="mcp__workspace__bash")]
    _silent(_run(tmp_path, rows, _GENERATED))


def test_a_cat_of_the_generators_own_file_counts(tmp_path: Path) -> None:
    """A run redirected the prompt into a file, then printed it with `cat` in a later call."""
    first = 'P="/w/redteam_prompt.txt"\n' + GEN_CMD + ' > "$P"\nwc -l "$P"'
    rows = [
        _user("Size my market."),
        *_printed("12 /w/redteam_prompt.txt\n", command=first),
        *_printed(_GENERATED, command="cat /w/redteam_prompt.txt"),
    ]
    _silent(_run(tmp_path, rows, _GENERATED))
    _deny(_run(tmp_path, rows, _STEERED))


def test_an_oversized_result_saved_to_a_file_counts_when_read(tmp_path: Path) -> None:
    """A large result reaches the transcript as a header naming the file the full output was saved to;
    the model then Reads that file."""
    saved = "/home/u/.claude/projects/p/tool-results/b1.txt"
    header = (
        f"<persisted-output>\nOutput too large (31.0KB). Full output saved to: {saved}\n\n"
        "Preview (first 2KB):\nCONTEXT: RED_TEAM\n"
    )
    rows = [_user("Size my market."), *_printed(header), *_read(saved, _GENERATED)]
    _silent(_run(tmp_path, rows, _GENERATED))
    other = [_user("Size my market."), *_printed(header), *_read("/home/u/other.txt", _GENERATED)]
    assert "no printed prompt" in _deny(_run(tmp_path, other, _GENERATED))


# --- the context line is matched whole -----------------------------------------------------------------


def test_a_repair_prompt_with_its_own_context_line_is_not_compared(tmp_path: Path) -> None:
    """A KNOWN LIMIT, pinned so it is not mistaken for a guarantee. `CONTEXT: CHECKLIST (repair)` is a
    hand-written repair, not the printed prompt, and is not compared: matched by prefix it was held for
    a prompt it never claimed to be. It still has to go to the right agent (dispatch_type_check.py)."""
    rows = [_user("Size my market."), *_printed(_CHECKLIST_PRINTED)]
    repair = _CHECKLIST_PRINTED.replace("CONTEXT: CHECKLIST\n", "CONTEXT: CHECKLIST (repair)\n")
    _silent(_run(tmp_path, rows, repair, agent="founder-skills:market-sizing"))
    _deny(_run(tmp_path, rows, repair, agent="general-purpose"))


def test_a_context_line_inside_another_line_is_not_the_comparand(tmp_path: Path) -> None:
    """The comparand's context must be a line of its own, as the generator prints it."""
    quoted = _GENERATED.replace("CONTEXT: RED_TEAM\n", "Step 6c sends CONTEXT: RED_TEAM\n")
    reason = _deny(_run(tmp_path, [_user("Size my market."), *_printed(quoted)], _GENERATED))
    assert "no printed prompt" in reason


# --- the blocks SKILL.md prescribes are accepted ---------------------------------------------------------


def _generator_fences() -> list[tuple[str, str]]:
    import re

    out = []
    for skill in ("market-sizing", "competitive-positioning", "financial-model-review"):
        text = (SCRIPTS.parent / "skills" / skill / "SKILL.md").read_text(encoding="utf-8")
        for m in re.finditer(r"^```bash\n(.*?)^```", text, re.MULTILINE | re.DOTALL):
            runs = [
                ln for ln in m.group(1).splitlines() if "dispatch_prompt.py" in ln and not ln.lstrip().startswith("#")
            ]
            if runs:  # a block that only mentions the generator in a comment runs none
                out.append((skill, m.group(1)))
    return out


def test_every_prescribed_generator_block_is_accepted() -> None:
    """Each bash block SKILL.md prescribes around a generator leaves its output the comparand, including
    the ones that run the uploads mirror or the OCR pass in the same block."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("dpc_fences", SCRIPTS / "dispatch_prompt_check.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    fences = _generator_fences()
    assert len(fences) >= 6, [skill for skill, _ in fences]
    for skill, block in fences:
        assert mod.generator_block(block)[0], (skill, block)
    # competitive-positioning's checklist pipe prints with `python3 -c`, in a block of its own.
    cp = (SCRIPTS.parent / "skills" / "competitive-positioning" / "SKILL.md").read_text(encoding="utf-8")
    assert "python3 -c" in cp
    assert not any("python3 -c" in block for _, block in fences)


# --- sending the printed prompt in place of an edited one (dormant behind REWRITE_FLOOR) ----------------


def _hook() -> Any:
    import importlib.util

    spec = importlib.util.spec_from_file_location("dpc_rewrite", SCRIPTS / "dispatch_prompt_check.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _versioned(rows: list[dict[str, Any]], version: str) -> list[dict[str, Any]]:
    return [{**r, "version": version} for r in rows]


def _decide(mod: Any, tmp_path: Path, rows: list[dict[str, Any]], tool_input: Any) -> Any:
    path = tmp_path / "t.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return mod.decide(
        {"hook_event_name": "PreToolUse", "tool_name": "Agent", "transcript_path": str(path), "tool_input": tool_input}
    )


_INPUT = {"subagent_type": "founder-skills:market-sizing-redteam", "description": "Outside review", "prompt": _STEERED}


def test_the_rewrite_is_dormant_at_the_shipped_floor(tmp_path: Path) -> None:
    """No CLI reaches the shipped floor, so a steered dispatch is held exactly as before."""
    mod = _hook()
    assert mod.REWRITE_FLOOR >= (999, 0, 0)
    rows = _versioned([_user("Size my market."), *_printed(_GENERATED)], "2.1.300")
    out = _decide(mod, tmp_path, rows, dict(_INPUT))["hookSpecificOutput"]
    assert out["permissionDecision"] == "deny" and "updatedInput" not in out


def test_at_the_floor_the_printed_prompt_replaces_only_the_prompt(tmp_path: Path, monkeypatch: Any) -> None:
    mod = _hook()
    monkeypatch.setattr(mod, "REWRITE_FLOOR", (2, 1, 290))
    rows = _versioned([_user("Size my market."), *_printed(_GENERATED)], "2.1.290")
    tool_input = {**_INPUT, "isolation": "worktree", "model": "x"}
    out = _decide(mod, tmp_path, rows, tool_input)["hookSpecificOutput"]
    assert out["permissionDecision"] == "allow"
    assert out["updatedInput"] == {**tool_input, "prompt": _GENERATED}
    assert tool_input["prompt"] == _STEERED, "the payload is not mutated"
    notice = out["additionalContext"]
    assert notice.startswith("[dispatch-rewrite][agent/handoff/R/r2/redteam_output.json]")
    assert "Do not send this dispatch again" in notice and "--correction" in notice


def test_below_the_floor_or_with_no_version_it_is_held(tmp_path: Path, monkeypatch: Any) -> None:
    mod = _hook()
    monkeypatch.setattr(mod, "REWRITE_FLOOR", (2, 1, 290))
    for rows in (
        _versioned([_user("Size my market."), *_printed(_GENERATED)], "2.1.289"),
        [_user("Size my market."), *_printed(_GENERATED)],
    ):
        out = _decide(mod, tmp_path, rows, dict(_INPUT))["hookSpecificOutput"]
        assert out["permissionDecision"] == "deny", rows[0].get("version")


@pytest.mark.parametrize("drop", ["subagent_type", "description"])
def test_a_partial_input_is_held_not_rewritten(tmp_path: Path, monkeypatch: Any, drop: str) -> None:
    mod = _hook()
    monkeypatch.setattr(mod, "REWRITE_FLOOR", (2, 1, 290))
    rows = _versioned([_user("Size my market."), *_printed(_GENERATED)], "2.1.290")
    tool_input = {k: v for k, v in _INPUT.items() if k != drop}
    if drop == "subagent_type":
        assert _decide(mod, tmp_path, rows, tool_input) is None  # not a registered pair at all
    else:
        assert _decide(mod, tmp_path, rows, tool_input)["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_no_printed_prompt_is_held_even_at_the_floor(tmp_path: Path, monkeypatch: Any) -> None:
    mod = _hook()
    monkeypatch.setattr(mod, "REWRITE_FLOOR", (2, 1, 290))
    rows = _versioned([_user("Size my market.")], "2.1.290")
    out = _decide(mod, tmp_path, rows, dict(_INPUT))["hookSpecificOutput"]
    assert out["permissionDecision"] == "deny" and "no printed prompt" in out["permissionDecisionReason"]


def test_the_rewrite_has_no_hold_budget(tmp_path: Path, monkeypatch: Any) -> None:
    """Past two holds a steered dispatch used to be let through as sent; at the floor it is rewritten."""
    mod = _hook()
    monkeypatch.setattr(mod, "REWRITE_FLOOR", (2, 1, 290))
    held = f"{MARKER}[agent/handoff/R/r2/redteam_output.json] x"
    rows = _versioned([_user("Size my market."), *_printed(_GENERATED), _held(held), _held(held)], "2.1.290")
    out = _decide(mod, tmp_path, rows, dict(_INPUT))["hookSpecificOutput"]
    assert out["permissionDecision"] == "allow" and out["updatedInput"]["prompt"] == _GENERATED


# The self-check's rows are SYNTHETIC until a live probe records the real shapes: a non-model row the
# runtime writes carrying the hook's notice, and the dispatch's result row with `toolUseResult.prompt`.
def _rewritten_rows(sent: str) -> list[dict[str, Any]]:
    mod = _hook()
    uid, use = _call("Agent", dict(_INPUT))
    notice = {"type": "attachment", "attachment": {"content": mod._notice("agent/handoff/R/r2/redteam_output.json")}}
    result = _result(uid, "done")
    result["toolUseResult"] = {"prompt": sent, "status": "completed"}
    return [_user("Size my market."), *_printed(_GENERATED), use, notice, result]


def test_a_rewrite_that_did_not_take_stops_every_later_rewrite(tmp_path: Path, monkeypatch: Any) -> None:
    mod = _hook()
    monkeypatch.setattr(mod, "REWRITE_FLOOR", (2, 1, 290))
    taken = _versioned(_rewritten_rows(_GENERATED), "2.1.290")
    assert _decide(mod, tmp_path, taken, dict(_INPUT))["hookSpecificOutput"]["permissionDecision"] == "allow"
    ignored = _versioned(_rewritten_rows(_STEERED), "2.1.290")
    out = _decide(mod, tmp_path, ignored, dict(_INPUT))["hookSpecificOutput"]
    assert out["permissionDecision"] == "deny"


def test_a_notice_the_model_printed_is_not_a_rewrite_record() -> None:
    """Only rows the runtime writes count; a tool result or a model turn carrying the text does not."""
    mod = _hook()
    rows = _rewritten_rows(_STEERED)
    forged = [r if r.get("type") != "attachment" else _result("toolu_x", json.dumps(r)) for r in rows]
    assert mod.rewrite_failed(rows) and not mod.rewrite_failed(forged)
