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

import json
import subprocess
from pathlib import Path
from typing import Any

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


def _printed(text: str) -> dict[str, Any]:
    return {"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "content": text}]}}


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
    rows = [_user("Size my market."), _printed(_GENERATED)]
    _silent(_run(tmp_path, rows, _GENERATED))
    _silent(_run(tmp_path, rows, "  " + _GENERATED.replace("\n", "\n  ")))


def test_a_prompt_with_lines_added_is_held_with_the_printed_one(tmp_path: Path) -> None:
    reason = _deny(_run(tmp_path, [_user("Size my market."), _printed(_GENERATED)], _STEERED))
    assert MARKER in reason
    # The reason carries the printed prompt whole, so the retry can be exactly it.
    assert "Do NOT write any file other than OUTPUT_PATH." in reason
    assert "round-2 review after a revision" not in reason


def test_a_prompt_with_lines_removed_is_held(tmp_path: Path) -> None:
    trimmed = _GENERATED.replace("Read the founder's documents first:\n  agent/docs/deck.pdf\n", "")
    _deny(_run(tmp_path, [_user("Size my market."), _printed(_GENERATED)], trimmed))


def test_a_stale_round_sent_verbatim_to_its_own_path_passes(tmp_path: Path) -> None:
    """The comparand is the latest printed prompt for the dispatch's OWN OUTPUT_PATH. Round 1's prompt
    sent unchanged to round 1's path carries no added framing, the only class this hook stops; the
    missing round-2 hand-off then fails check_handoff for the r2 path. (This test used to expect a hold:
    the comparand was the latest printed prompt for the context, whatever its path.)"""
    round_1 = _GENERATED.replace("/r2/", "/")
    rows = [_user("Size my market."), _printed(round_1), _printed(_GENERATED)]
    _silent(_run(tmp_path, rows, _GENERATED))
    _silent(_run(tmp_path, rows, round_1))


def test_the_latest_printed_prompt_for_this_path_wins(tmp_path: Path) -> None:
    """Two prompts printed for the SAME path: the later one is the comparand."""
    earlier = _GENERATED.replace("Read the founder's documents first:", "Read these first:")
    rows = [_user("Size my market."), _printed(earlier), _printed(_GENERATED)]
    _silent(_run(tmp_path, rows, _GENERATED))
    reason = _deny(_run(tmp_path, rows, earlier))
    assert "Read the founder's documents first:" in reason


def test_no_printed_prompt_is_held_until_the_generator_runs(tmp_path: Path) -> None:
    """The remedy is to run the generator, which is what puts the comparand in the transcript."""
    reason = _deny(_run(tmp_path, [_user("Size my market.")], _GENERATED))
    assert "prompt generator" in reason


def test_a_round_is_held_at_most_twice(tmp_path: Path) -> None:
    rows = [_user("Size my market."), _printed(_GENERATED)]
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
        _printed(round_1),
        _held(f"{MARKER}[agent/handoff/R/redteam_output.json] x"),
        _held(f"{MARKER}[agent/handoff/R/redteam_output.json] x"),
        _printed(_GENERATED),
    ]
    _deny(_run(tmp_path, rows, _STEERED))


def test_other_dispatches_and_tools_are_silent(tmp_path: Path) -> None:
    rows = [_user("x"), _printed(_GENERATED)]
    _silent(_run(tmp_path, rows, "CONTEXT: SENSITIVITY_TEST\nOUTPUT_PATH: x\n"))
    _silent(_run(tmp_path, rows, _STEERED, tool="Bash"))


def test_the_dispatcher_is_the_one_declared_hook_for_dispatches() -> None:
    manifest = json.loads((SCRIPTS.parent / ".claude-plugin" / "plugin.json").read_text())
    entries = manifest["hooks"]["PreToolUse"]
    assert len(entries) == 1
    assert set(entries[0]["matcher"].split("|")) == {"Agent", "Task"}
    assert [h["command"].rsplit("/", 1)[-1] for h in entries[0]["hooks"]] == ["pretooluse-dispatch.sh"]


def test_a_prompt_read_back_from_its_file_counts_as_printed(tmp_path: Path) -> None:
    """Run 1 wrote the prompt with -o and read it back with the Read tool, whose result numbers every
    line ("1\\tCONTEXT: RED_TEAM"). Round 1 matched; the check must see that it did."""
    read_back = "".join(f"{n}\t{line}\n" for n, line in enumerate(_GENERATED.splitlines(), 1))
    rows = [_user("Size my market."), _printed(read_back)]
    _silent(_run(tmp_path, rows, _GENERATED))
    _deny(_run(tmp_path, rows, _STEERED))


_CHECKLIST_PRINTED = (
    "CONTEXT: CHECKLIST\nOUTPUT_PATH: agent/handoff/R/checklist_output.json\nRUN_ID: R\n\n"
    "Read:\n- agent/handoff/R/checklist_view/methodology.json\nAssess all 22 items.\n"
    "Do NOT write any file other than OUTPUT_PATH.\n"
)


def test_a_checklist_dispatch_is_held_to_its_printed_prompt(tmp_path: Path) -> None:
    rows = [_user("Size my market."), _printed(_CHECKLIST_PRINTED)]
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
    rows = [_user("Size my market."), _printed(_CHECKLIST_PRINTED), _user("Now review my deck.")]
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
    rows = [_user("Size my market."), _printed(_CHECKLIST_PRINTED)]
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
    rows = [_user("Size my market."), _printed(_SPACED_1), _held(held_1), _held(held_1), _printed(_SPACED_2)]
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
    rows = [_user("Size my market."), _printed(theirs)]
    reason = _deny(_run(tmp_path, rows, _CHECKLIST_PRINTED, agent="founder-skills:market-sizing"))
    assert "no printed prompt" in reason
    assert "other/handoff" not in reason


def test_a_template_read_from_a_skill_file_is_not_the_comparand(tmp_path: Path) -> None:
    """A Read of SKILL.md shows the template with a placeholder path, which no real path equals."""
    template = _CHECKLIST_PRINTED.replace(
        "agent/handoff/R/checklist_output.json", "<HANDOFF_AGENT>/checklist_output.json"
    )
    rows = [_user("Size my market."), _printed(template)]
    reason = _deny(_run(tmp_path, rows, _CHECKLIST_PRINTED, agent="founder-skills:market-sizing"))
    assert "<HANDOFF_AGENT>" not in reason


def test_a_steered_dispatch_is_still_held_with_its_own_printed_prompt(tmp_path: Path) -> None:
    """Positive control: the framing guarantee is unchanged."""
    rows = [_user("Size my market."), _printed(_GENERATED)]
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
        "\n".join(json.dumps(r) for r in [_user("go"), _printed(ours), _printed(theirs)]) + "\n", encoding="utf-8"
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
            "--plugin-root-agent",
            "/p",
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
    rows = [_user("Map my competition."), _printed(_GENERATED), _printed(ours)]
    _silent(_run(tmp_path, rows, ours, agent=_CP_REDTEAM))


def test_competitive_positionings_red_team_is_held_to_its_own_printed_prompt(tmp_path: Path) -> None:
    """Market-sizing's red-team prompt, printed in the same session, is never the comparand: the
    reason carries competitive-positioning's own prompt and path."""
    ours = _cp_red_team_prompt(tmp_path)
    steered = ours.replace("You are not told what to attack.", "Focus on the patent.\nYou are not told what to attack.")
    rows = [_user("Map my competition."), _printed(_GENERATED), _printed(ours)]
    reason = _deny(_run(tmp_path, rows, steered, agent=_CP_REDTEAM))
    assert "the review looks at the analysis" in reason
    assert "competitive-positioning-acme/handoff/R/redteam_output.json" in reason
    assert "agent/handoff/R/r2/redteam_output.json" not in reason


def test_competitive_positionings_red_team_prompt_sent_to_another_agent_is_not_its_pair(tmp_path: Path) -> None:
    """A KNOWN LIMIT, pinned so it is not mistaken for a guarantee: the pair is (context line, agent),
    so the red-team prompt sent to the scoring agent is not checked at all -- the same gap market-sizing
    has. Such a dispatch would reach a reviewer carrying the rubric the review exists to escape; nothing
    here stops it. Should the check ever cover a mis-addressed dispatch, this test changes with it."""
    ours = _cp_red_team_prompt(tmp_path)
    rows = [_user("Map my competition."), _printed(ours)]
    _silent(_run(tmp_path, rows, ours + "Extra.\n", agent="founder-skills:competitive-positioning"))


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
            "--plugin-root-agent",
            "/p",
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
    rows = [_user("Map my competition."), _printed(ours)]
    _silent(_run(tmp_path, rows, ours, agent=_CP_REDTEAM))
    line = next(ln for ln in ours.splitlines() if ln.startswith("  - "))
    reworded = ours.replace(line, line.replace("of ", "out of ", 1))
    assert reworded != ours
    _deny(_run(tmp_path, rows, reworded, agent=_CP_REDTEAM))
