"""`dispatch_type_check.py`: a known dispatch goes to its own agent.

A dispatch with no `subagent_type` falls back to the wildcard `general-purpose` agent, and `claude` is
another catch-all: a shell and every tool, and none of the agent body the prompt was written for. The
table of context lines is derived here from the skills' own files, so a context line added to a
template cannot be missing from it. Exercised through the PreToolUse dispatcher's POSIX wrapper.
"""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
from pathlib import Path
from typing import Any

import pytest

PLUGIN = Path(__file__).resolve().parents[1]
SCRIPTS = PLUGIN / "scripts"
SKILLS = PLUGIN / "skills"
WRAPPER = SCRIPTS / "pretooluse-dispatch.sh"
MARKER = "[dispatch-type]"


def _load(name: str) -> Any:
    spec = importlib.util.spec_from_file_location(f"{name}_under_test", SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


TYPE = _load("dispatch_type_check")

# --- the table, derived from the skills' own files -----------------------------------------------------

_TYPE_RE = re.compile(r'subagent_type\s*[=:]\s*"(?:founder-skills:)?([a-z-]+)"')
_HEADING_RE = re.compile(r"^#{1,3} ", re.MULTILINE)
_FENCE_RE = re.compile(r"^```[^\n]*\n(.*?)^```", re.MULTILINE | re.DOTALL)
_CONTEXT_LINE_RE = re.compile(r"^CONTEXT: ([A-Z][A-Z0-9_]*)\s*$", re.MULTILINE)
_GENERATOR_CALL_RE = re.compile(r'(?:cp_|fmr_)?dispatch_prompt\.py"? ([a-z_]+)')


def _section(text: str, pos: int) -> str:
    """The text between the headings around `pos`. A `#` line inside a fence is a comment, not a heading."""
    fences = [(m.start(), m.end()) for m in _FENCE_RE.finditer(text)]
    heads = [m.start() for m in _HEADING_RE.finditer(text) if not any(a <= m.start() < b for a, b in fences)]
    start = max((h for h in heads if h <= pos), default=0)
    end = min((h for h in heads if h > pos), default=len(text))
    return text[start:end]


def _derived() -> tuple[dict[str, set[str]], list[str]]:
    """context -> agents, from every fenced template line in SKILL.md and references/, and every context a
    SKILL.md asks a generator to print; plus each place no single agent could be read off its section."""
    table: dict[str, set[str]] = {}
    problems: list[str] = []
    for skill_dir in sorted(p for p in SKILLS.iterdir() if (p / "SKILL.md").is_file()):
        files = [skill_dir / "SKILL.md", *sorted((skill_dir / "references").rglob("*.md"))]
        for f in files:
            text = f.read_text(encoding="utf-8")
            for fence in _FENCE_RE.finditer(text):
                for m in _CONTEXT_LINE_RE.finditer(fence.group(1)):
                    agents = set(_TYPE_RE.findall(_section(text, fence.start())))
                    if len(agents) != 1:
                        problems.append(f"{f.relative_to(SKILLS)}: {m.group(1)} -> {sorted(agents)}")
                        continue
                    table.setdefault(m.group(1), set()).update(agents)
        skill_md = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
        for m in _GENERATOR_CALL_RE.finditer(skill_md):
            agents = set(_TYPE_RE.findall(_section(skill_md, m.start())))
            if len(agents) != 1:
                problems.append(f"{skill_dir.name}: generator {m.group(1)} -> {sorted(agents)}")
                continue
            table.setdefault(m.group(1).upper(), set()).update(agents)
    return table, problems


def test_the_table_is_what_the_skills_dispatch() -> None:
    table, problems = _derived()
    assert not problems, f"a dispatch template whose section names no single agent: {problems}"
    assert len(table) >= 25, sorted(table)  # non-vacuity: the fleet's 25 context lines
    assert {k: set(v) for k, v in TYPE.CONTEXT_AGENTS.items()} == table


def test_every_generator_context_is_in_the_table() -> None:
    """Every context line a generator prints, read from the generator's own source."""
    printed = set()
    for gen in SKILLS.glob("*/scripts/*dispatch_prompt.py"):
        printed |= set(re.findall(r"CONTEXT: ([A-Z][A-Z0-9_]*)", gen.read_text(encoding="utf-8")))
    assert printed and printed <= set(TYPE.CONTEXT_AGENTS), printed - set(TYPE.CONTEXT_AGENTS)


def test_every_compared_pair_is_allowed_by_the_table() -> None:
    """A pair the prompt check compares must never be one this check holds."""
    pairs = _load("dispatch_prompt_check").PAIRS
    for context, agent in pairs:
        assert agent in TYPE.CONTEXT_AGENTS[context.removeprefix("CONTEXT: ")], (context, agent)


def test_the_agent_check_runs_first() -> None:
    assert _load("pretooluse_dispatch").CHECKS[0] == "dispatch_type_check"


def test_a_section_with_no_agent_is_reported() -> None:
    """Seeded negative for the derivation: a template whose section names no agent is a problem, never
    a silent skip (this is how Step 3.6's recall dispatch would have read before it named one)."""
    text = "### Step 9: X\n\nDispatch it.\n\n```\nCONTEXT: COMPETITOR_RECALL\nOUTPUT_PATH: x\n```\n"
    fence = next(_FENCE_RE.finditer(text))
    assert _TYPE_RE.findall(_section(text, fence.start())) == []
    text_with = text.replace("Dispatch it.", 'Dispatch it with `subagent_type: "founder-skills:x"`.')
    assert _TYPE_RE.findall(_section(text_with, next(_FENCE_RE.finditer(text_with)).start())) == ["x"]


def test_a_comment_inside_a_fence_is_not_a_heading() -> None:
    text = (
        '### Step 1\n\nUse `subagent_type: "founder-skills:x"`.\n\n```bash\n# a comment\necho\n```\n\n'
        "```\nCONTEXT: A\n```\n"
    )
    fences = list(_FENCE_RE.finditer(text))
    assert _TYPE_RE.findall(_section(text, fences[1].start())) == ["x"]


# --- the decision, through the wrapper ------------------------------------------------------------------


_RED_TEAM = "CONTEXT: RED_TEAM\nOUTPUT_PATH: agent/handoff/R/redteam_output.json\n\nRead.\n"


def _user(text: str) -> dict[str, Any]:
    return {"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": text}]}}


def _skill(name: str) -> dict[str, Any]:
    use = {"type": "tool_use", "id": "toolu_s", "name": "Skill", "input": {"skill": name}}
    return {"type": "assistant", "message": {"role": "assistant", "content": [use]}}


def _held(reason: str) -> dict[str, Any]:
    block = {"type": "tool_result", "is_error": True, "content": reason}
    return {"type": "user", "message": {"role": "user", "content": [block]}}


def _run(tmp_path: Path, rows: list[dict[str, Any]] | None, prompt: str, agent: str | None) -> Any:
    tool_input: dict[str, Any] = {"prompt": prompt, "description": "d"}
    if agent is not None:
        tool_input["subagent_type"] = agent
    payload: dict[str, Any] = {"hook_event_name": "PreToolUse", "tool_name": "Agent", "tool_input": tool_input}
    if rows is not None:
        path = tmp_path / "t.jsonl"
        path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
        payload["transcript_path"] = str(path)
    return subprocess.run(["sh", str(WRAPPER)], input=json.dumps(payload), capture_output=True, text=True, timeout=30)


def _deny(r: Any) -> str:
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)["hookSpecificOutput"]
    assert out["permissionDecision"] == "deny"
    reason: str = out["permissionDecisionReason"]
    return reason


def _silent(r: Any) -> None:
    assert r.returncode == 0 and r.stdout == "", r


@pytest.mark.parametrize("agent", [None, "claude", "general-purpose", "founder-skills:market-sizing"])
def test_a_red_team_prompt_sent_to_another_agent_is_held_naming_the_reviewer(tmp_path: Path, agent: Any) -> None:
    reason = _deny(_run(tmp_path, [_user("Size my market.")], _RED_TEAM, agent))
    assert reason.startswith(f"{MARKER}[agent/handoff/R/redteam_output.json] Held")
    assert '"founder-skills:market-sizing-redteam"' in reason
    assert '"founder-skills:competitive-positioning-redteam"' in reason  # no skill shown: both are listed


def test_the_started_skill_narrows_the_agent_named(tmp_path: Path) -> None:
    rows = [_user("Size my market."), _skill("founder-skills:market-sizing")]
    reason = _deny(_run(tmp_path, rows, _RED_TEAM, "general-purpose"))
    assert '"founder-skills:market-sizing-redteam"' in reason
    assert "competitive-positioning" not in reason


def test_a_skill_the_user_typed_counts_as_started(tmp_path: Path) -> None:
    rows = [_user("<command-name>/founder-skills:competitive-positioning</command-name> map it")]
    reason = _deny(_run(tmp_path, rows, _RED_TEAM, None))
    assert '"founder-skills:competitive-positioning-redteam"' in reason
    assert "market-sizing" not in reason


def test_a_skill_never_started_is_not_the_agent(tmp_path: Path) -> None:
    """market-sizing's checklist sent to the deck-review agent: a real agent for that context line, but
    of a skill this session never started."""
    checklist = "CONTEXT: CHECKLIST\nOUTPUT_PATH: agent/handoff/R/checklist_output.json\n"
    rows = [_user("Size my market."), _skill("founder-skills:market-sizing")]
    reason = _deny(_run(tmp_path, rows, checklist, "founder-skills:deck-review"))
    assert '"founder-skills:market-sizing"' in reason


@pytest.mark.parametrize(
    ("prompt", "agent"),
    [
        ("CONTEXT: CHECKLIST\nOUTPUT_PATH: x\n", "founder-skills:deck-review"),
        ("CONTEXT: CHECKLIST\nOUTPUT_PATH: x\n", "deck-review"),
        ("CONTEXT: SECOND_READ\nOUTPUT_PATH: x\n", "founder-skills:deck-review"),
        ("CONTEXT: POST_COMPOSE_COACHING\nOUTPUT_PATH: x\n", "founder-skills:ic-sim"),
        ("CONTEXT: INSTRUMENT_EXTRACTION\nOUTPUT_PATH: x\n", "founder-skills:cap-table"),
        ("CONTEXT: NOT_A_CONTEXT\nOUTPUT_PATH: x\n", None),
        ("CONTEXT: CHECKLISTX\nOUTPUT_PATH: x\n", None),
        ("Summarise this file.\nCONTEXT: RED_TEAM\n", None),
    ],
)
def test_the_right_agent_or_an_unknown_context_passes(tmp_path: Path, prompt: str, agent: Any) -> None:
    _silent(_run(tmp_path, [_user("Review my deck.")], prompt, agent))


def test_the_bare_financial_model_review_name_passes_the_type_check(tmp_path: Path) -> None:
    """Run through the type check alone: through the dispatcher, financial-model-review's CHECKLIST now also
    meets the prompt check, which holds it for having no printed prompt."""
    path = tmp_path / "t.jsonl"
    path.write_text(json.dumps(_user("Review my model.")) + "\n", encoding="utf-8")
    tool_input = {"prompt": "CONTEXT: CHECKLIST\nOUTPUT_PATH: x\n", "description": "d"}
    for agent in ("financial-model-review", "founder-skills:financial-model-review"):
        payload = {
            "hook_event_name": "PreToolUse",
            "tool_name": "Agent",
            "transcript_path": str(path),
            "tool_input": {**tool_input, "subagent_type": agent},
        }
        assert TYPE.decide(payload) is None, agent
    held = {"hook_event_name": "PreToolUse", "tool_name": "Agent", "transcript_path": str(path),
            "tool_input": {**tool_input, "subagent_type": "general-purpose"}}  # fmt: skip
    assert TYPE.decide(held) is not None


def test_a_repair_line_still_needs_the_right_agent(tmp_path: Path) -> None:
    """The first line is matched by prefix here, so a hand-written repair is still held to its agent."""
    repair = "CONTEXT: CHECKLIST (repair)\nOUTPUT_PATH: x\n"
    _deny(_run(tmp_path, [_user("Review my deck.")], repair, "general-purpose"))
    _silent(_run(tmp_path, [_user("Review my deck.")], repair, "founder-skills:deck-review"))


def test_held_at_most_twice_per_output_path_then_let_through(tmp_path: Path) -> None:
    rows = [_user("Size my market.")]
    first = _deny(_run(tmp_path, rows, _RED_TEAM, "claude"))
    rows.append(_held(first))
    rows.append(_held(_deny(_run(tmp_path, rows, _RED_TEAM, "claude"))))
    r = _run(tmp_path, rows, _RED_TEAM, "claude")
    _silent(r)
    assert "dispatch_type_check" in r.stderr
    # Another round's path has its own budget.
    _deny(_run(tmp_path, rows, _RED_TEAM.replace("/R/", "/R/r2/"), "claude"))


def test_no_transcript_passes_with_a_line_on_stderr(tmp_path: Path) -> None:
    """With no transcript the holds cannot be counted, and an uncounted hold could never end."""
    r = _run(tmp_path, None, _RED_TEAM, "claude")
    _silent(r)
    assert "dispatch_type_check" in r.stderr


def test_other_tools_are_silent(tmp_path: Path) -> None:
    payload = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"prompt": _RED_TEAM}}
    r = subprocess.run(["sh", str(WRAPPER)], input=json.dumps(payload), capture_output=True, text=True, timeout=30)
    _silent(r)


def test_every_skill_started_in_the_session_counts(tmp_path: Path) -> None:
    """One session ran a deck review and a market sizing side by side, starting market-sizing after
    deck-review. Narrowed to the latest skill, deck-review's own checklist was held and told to go to
    market-sizing's agent; every skill started is allowed instead."""
    checklist = "CONTEXT: CHECKLIST\nOUTPUT_PATH: agent/handoff/R/checklist_output.json\n"
    rows = [_user("Review the company."), _skill("founder-skills:deck-review"), _skill("founder-skills:market-sizing")]
    _silent(_run(tmp_path, rows, checklist, "founder-skills:deck-review"))
    # market-sizing's agent passes this check; the prompt check then holds it for its unprinted prompt.
    assert "goes to its own agent" not in _deny(_run(tmp_path, rows, checklist, "founder-skills:market-sizing"))
    reason = _deny(_run(tmp_path, rows, checklist, "founder-skills:competitive-positioning"))
    assert '"founder-skills:deck-review"' in reason and '"founder-skills:market-sizing"' in reason


def test_an_invisible_character_does_not_hide_the_context(tmp_path: Path) -> None:
    for line in ("CONTEXT: RED_TEAM\u200b", "\ufeffCONTEXT: RED_TEAM", "CONTEXT:\u200b RED_TEAM"):
        prompt = f"{line}\nOUTPUT_PATH: agent/handoff/R/redteam_output.json\n"
        _deny(_run(tmp_path, [_user("Size my market.")], prompt, "general-purpose"))


@pytest.mark.parametrize(
    "path", ["/Users/u/מסמכים/handoff/R/redteam_output.json", '/w/a "b"/out.json', "/w/a\\b/out.json"]
)
def test_holds_are_counted_for_any_output_path(tmp_path: Path, path: str) -> None:
    """The hold marker is found in the message's text, not in its JSON encoding, where a non-ASCII
    character, a quote or a backslash is escaped and the marker never matched: the holds went
    uncounted and the dispatch was held forever."""
    prompt = f"CONTEXT: RED_TEAM\nOUTPUT_PATH: {path}\n"
    rows = [_user("Size my market.")]
    rows.append(_held(_deny(_run(tmp_path, rows, prompt, "claude"))))
    rows.append(_held(_deny(_run(tmp_path, rows, prompt, "claude"))))
    r = _run(tmp_path, rows, prompt, "claude")
    _silent(r)


def test_each_check_has_its_own_hold_budget(tmp_path: Path) -> None:
    """Two holds for the wrong agent must not spend the prompt check's budget: the same steered prompt
    then sent to the right agent is still held."""
    printed = (
        "CONTEXT: RED_TEAM\nOUTPUT_PATH: /h/r2/redteam_output.json\nRead docs.\n"
        "Do NOT write any file other than OUTPUT_PATH.\n"
    )
    steered = printed.replace("Read docs.\n", "Read docs.\nNote: round 2; the ARPU changed.\n")
    use = {
        "type": "tool_use",
        "id": "t1",
        "name": "Bash",
        "input": {"command": 'python3 "$SCRIPTS/dispatch_prompt.py" red_team'},
    }
    result = {"type": "tool_result", "tool_use_id": "t1", "content": printed}
    rows = [
        _user("Size my market."),
        {"type": "assistant", "message": {"content": [use]}},
        {"type": "user", "message": {"content": [result]}},
    ]
    for _ in range(2):
        rows.append(_held(_deny(_run(tmp_path, rows, steered, "general-purpose"))))
    reason = _deny(_run(tmp_path, rows, steered, "founder-skills:market-sizing-redteam"))
    assert "Send this as the prompt, unchanged" in reason


def test_another_plugins_agent_of_the_same_name_is_not_ours(tmp_path: Path) -> None:
    """Only `founder-skills:<agent>` or the bare name is our agent; `other-plugin:market-sizing-redteam`
    is another plugin's."""
    reason = _deny(_run(tmp_path, [_user("Size my market.")], _RED_TEAM, "other-plugin:market-sizing-redteam"))
    assert '"founder-skills:market-sizing-redteam"' in reason
    # The bare name passes this check (the prompt check then holds it for its unprinted prompt).
    assert "goes to its own agent" not in _deny(
        _run(tmp_path, [_user("Size my market.")], _RED_TEAM, "market-sizing-redteam")
    )


def test_no_founder_skill_and_no_output_path_is_not_ours(tmp_path: Path) -> None:
    """A dispatch from another plugin can open with a context line too. With no founder-skills skill
    started in the session and no OUTPUT_PATH line, it is not one of ours and is not held."""
    _silent(_run(tmp_path, [_user("Help me plan.")], "CONTEXT: CHECKLIST\nGo through the list.\n", "general-purpose"))
    # Either signal is enough to hold it.
    _deny(_run(tmp_path, [_user("x"), _skill("founder-skills:deck-review")], "CONTEXT: CHECKLIST\nGo.\n", "claude"))
    _deny(_run(tmp_path, [_user("x")], "CONTEXT: CHECKLIST\nOUTPUT_PATH: /h/c.json\n", "claude"))
