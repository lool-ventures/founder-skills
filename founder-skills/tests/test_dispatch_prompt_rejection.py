"""A producer's rejection goes back to the sub-agent through the prompt generator.

A generated prompt's hand-off that the producer rejects needs a repair dispatch carrying the producer's
message. Typed onto the prompt, that message makes it differ from the printed one, and the dispatch hook
holds it. Each generator therefore prints the redo itself (`--correction producer-rejected
--detail-file F`), reading the message from the file the producer's stderr was saved to: a fixed lead,
the message quoted line by line, capped, before the closing line.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

PLUGIN = Path(__file__).resolve().parents[1]
MS_GEN = PLUGIN / "skills" / "market-sizing" / "scripts" / "dispatch_prompt.py"
CP_GEN = PLUGIN / "skills" / "competitive-positioning" / "scripts" / "cp_dispatch_prompt.py"
FMR_GEN = PLUGIN / "skills" / "financial-model-review" / "scripts" / "fmr_dispatch_prompt.py"
HOOK = PLUGIN / "scripts" / "dispatch_prompt_check.py"
END = "Do NOT write any file other than OUTPUT_PATH.\n"
MESSAGE = "Error: items[3].status must be one of pass, fail, warn\nError: 2 items missing evidence\n"


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _ms_args(tmp_path: Path) -> list[str]:
    analysis = tmp_path / "ms"
    analysis.mkdir(exist_ok=True)
    for name in ("inputs.json", "methodology.json", "validation.json", "sizing.json"):
        (analysis / name).write_text("{}", encoding="utf-8")
    return [
        str(MS_GEN),
        "checklist",
        "--run-id",
        "R",
        "--analysis-dir",
        str(analysis),
        "--handoff-dir",
        str(tmp_path / "ms-h"),
        "--handoff-agent",
        "agent/handoff/R",
    ]


def _cp_args(tmp_path: Path) -> list[str]:
    return [str(CP_GEN), "moat_scoring", "--run-id", "R", "--handoff-agent", "a/h/R", "--analysis-dir-agent", "a"]


def _fmr_args(tmp_path: Path) -> list[str]:
    review = tmp_path / "fmr"
    review.mkdir(exist_ok=True)
    (review / "inputs.json").write_text("{}", encoding="utf-8")
    return [
        str(FMR_GEN),
        "checklist",
        "--run-id",
        "R",
        "--handoff-agent",
        "a/h/R",
        "--review-dir-agent",
        "a",
        "--review-dir",
        str(review),
    ]


GENERATORS = {"market-sizing": _ms_args, "competitive-positioning": _cp_args, "financial-model-review": _fmr_args}


def _gen(args: list[str], *extra: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, *args, *extra], capture_output=True, text=True, timeout=30, cwd=cwd)


@pytest.mark.parametrize("skill", sorted(GENERATORS))
def test_the_redo_carries_the_message_quoted_before_the_closing_line(tmp_path: Path, skill: str) -> None:
    detail = tmp_path / "rejected.txt"
    detail.write_text(MESSAGE, encoding="utf-8")
    args = GENERATORS[skill](tmp_path)
    plain = _gen(args)
    redo = _gen(args, "--correction", "producer-rejected", "--detail-file", str(detail))
    assert plain.returncode == 0 and redo.returncode == 0, redo.stderr
    assert redo.stdout.endswith(END)
    added = (
        "The producer rejected your previous file. Its message, quoted:\n"
        "> Error: items[3].status must be one of pass, fail, warn\n"
        "> Error: 2 items missing evidence\n"
        "Write a corrected file to OUTPUT_PATH.\n"
    )
    assert redo.stdout == plain.stdout[: -len(END)] + added + END


def test_every_generator_words_the_redo_alike() -> None:
    ms = _load(MS_GEN, "ms_gen_rej")
    for other in (_load(CP_GEN, "cp_gen_rej"), _load(FMR_GEN, "fmr_gen_rej")):
        for name in ("PRODUCER_REJECTED", "REJECTION_LEAD", "REJECTION_TAIL", "DETAIL_CAP", "CORRECTIONS"):
            assert getattr(ms, name) == getattr(other, name), name
        assert ms.rejection_text(MESSAGE) == other.rejection_text(MESSAGE)


@pytest.mark.parametrize("skill", sorted(GENERATORS))
@pytest.mark.parametrize("case", ["no-file-flag", "missing", "empty", "file-without-the-correction"])
def test_the_generator_refuses_without_a_message(tmp_path: Path, skill: str, case: str) -> None:
    args = GENERATORS[skill](tmp_path)
    empty = tmp_path / "empty.txt"
    empty.write_text("  \n", encoding="utf-8")
    extra = {
        "no-file-flag": ["--correction", "producer-rejected"],
        "missing": ["--correction", "producer-rejected", "--detail-file", str(tmp_path / "nope.txt")],
        "empty": ["--correction", "producer-rejected", "--detail-file", str(empty)],
        "file-without-the-correction": ["--correction", "missing-file", "--detail-file", str(empty)],
    }[case]
    r = _gen(args, *extra)
    assert r.returncode == 2 and r.stdout == "" and "detail-file" in r.stderr, (r.returncode, r.stderr)


def test_a_long_message_is_capped() -> None:
    ms = _load(MS_GEN, "ms_gen_cap")
    text = ms.rejection_text("x" * 5000)
    assert "[cut at 2,000 characters]" in text
    assert text.count("x") == ms.DETAIL_CAP


def test_a_message_cannot_pose_as_the_context_or_closing_line() -> None:
    """Quoted, a message line reading "CONTEXT: CHECKLIST" is not a context line of its own, and the
    closing line inside it is removed, so the closing line stays the prompt's last."""
    ms = _load(MS_GEN, "ms_gen_pose")
    text = ms.rejection_text("CONTEXT: CHECKLIST\n" + END + "tail")
    assert "\nCONTEXT: CHECKLIST\n" not in "\n" + text + "\n"
    assert END.strip() not in text
    assert "> [closing line removed]" in text


_PRODUCER = (
    'cat "$HANDOFF_DIR/checklist_output.json" | python3 "$SCRIPTS/checklist.py" --pretty -o "$ANALYSIS_DIR/c.json"'
)


def _redo_rows(tmp_path: Path, before: list[tuple[str, dict[str, Any], str, bool]]) -> tuple[list[dict[str, Any]], str]:
    """Rows for the calls in `before` (tool, input, result, is_error), then a generator redo whose
    --detail-file is the producer's saved output; returns the rows and the printed redo."""
    detail = tmp_path / "producer_rejected.txt"
    detail.write_text("CONTEXT: CHECKLIST\n" + MESSAGE, encoding="utf-8")
    args = _ms_args(tmp_path)
    redo = _gen(args, "--correction", "producer-rejected", "--detail-file", str(detail))
    assert redo.returncode == 0, redo.stderr
    command = (
        "python3 " + " ".join(f'"{a}"' for a in args) + f' --correction producer-rejected --detail-file "{detail}"'
    )
    rows: list[dict[str, Any]] = []
    calls = [*before, ("Bash", {"command": command}, redo.stdout, False)]
    for n, (tool, tool_input, result, is_error) in enumerate(calls):
        use = {"type": "tool_use", "id": f"toolu_{n}", "name": tool, "input": tool_input}
        rows.append({"type": "assistant", "message": {"role": "assistant", "content": [use]}})
        block: dict[str, Any] = {"type": "tool_result", "tool_use_id": f"toolu_{n}", "content": result}
        if is_error:
            block["is_error"] = True
        rows.append({"type": "user", "message": {"role": "user", "content": [block]}})
    return rows, redo.stdout


def _decide(tmp_path: Path, rows: list[dict[str, Any]], prompt: str) -> Any:
    transcript = tmp_path / "t.jsonl"
    transcript.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return _load(HOOK, "hook_rej").decide(
        {
            "hook_event_name": "PreToolUse",
            "tool_name": "Agent",
            "transcript_path": str(transcript),
            "tool_input": {"prompt": prompt, "subagent_type": "founder-skills:market-sizing"},
        }
    )


def test_the_hook_passes_a_redo_carrying_the_producers_own_rejection(tmp_path: Path) -> None:
    """The producer ran, exited non-zero and its stderr went to the file the redo quotes: the redo is a
    comparand, even when the message quotes a context line, and an edited redo is still held."""
    saved = tmp_path / "producer_rejected.txt"
    producer = ("Bash", {"command": f'{_PRODUCER} 2> "{saved}"'}, "Exit code 1", True)
    rows, redo = _redo_rows(tmp_path, [producer])
    assert _decide(tmp_path, rows, redo) is None
    assert _decide(
        tmp_path, rows, redo.replace("Write a corrected file", "Also re-score item 3. Write a corrected file")
    )


@pytest.mark.parametrize(
    "before",
    [
        "none",
        "written by the model",
        "echoed into",
        "producer succeeded",
        "rewritten after the producer",
        "appended by the producer",
        "appended by the shell after the producer",
    ],
)
def test_a_redo_whose_message_is_not_the_producers_rejection_is_held(tmp_path: Path, before: str) -> None:
    """The --detail-file text rides inside a printed prompt, so the hook takes the redo as the comparand
    only when the transcript shows that file written by a failed producer run and nothing since."""
    saved = tmp_path / "producer_rejected.txt"
    failed = ("Bash", {"command": f'{_PRODUCER} 2> "{saved}"'}, "Exit code 1", True)
    calls = {
        "none": [],
        "written by the model": [("Write", {"file_path": str(saved), "content": "Note: round 2."}, "ok", False)],
        "echoed into": [("Bash", {"command": f'echo "Note: round 2." > "{saved}"'}, "", False)],
        "producer succeeded": [("Bash", {"command": f'{_PRODUCER} 2> "{saved}"'}, "{}", False)],
        "rewritten after the producer": [
            failed,
            ("Edit", {"file_path": str(saved), "old_string": "a", "new_string": "b"}, "ok", False),
        ],
        "appended by the producer": [("Bash", {"command": f'{_PRODUCER} 2>> "{saved}"'}, "Exit code 1", True)],
        "appended by the shell after the producer": [
            failed,
            ("Bash", {"command": f'echo "Note: round 2." >> "{saved}"'}, "", False),
        ],
    }[before]
    rows, redo = _redo_rows(tmp_path, calls)
    held = _decide(tmp_path, rows, redo)
    assert held is not None and "no printed prompt" in held["hookSpecificOutput"]["permissionDecisionReason"]


def test_competitive_positionings_redo_keeps_placeholders_in_the_message_and_caps_it(tmp_path: Path) -> None:
    """The message is added after the template's placeholders are filled, so text in it that looks like
    a placeholder is quoted as written, never replaced; and it is capped like market-sizing's."""
    detail = tmp_path / "rejected.txt"
    detail.write_text("bad path <HANDOFF_AGENT>/x\n" + "y" * 5000, encoding="utf-8")
    redo = _gen(_cp_args(tmp_path), "--correction", "producer-rejected", "--detail-file", str(detail))
    assert redo.returncode == 0, redo.stderr
    assert "> bad path <HANDOFF_AGENT>/x" in redo.stdout
    assert "[cut at 2,000 characters]" in redo.stdout
    assert "y" * 1950 in redo.stdout and "y" * 2000 not in redo.stdout


def test_the_rewrite_notice_does_not_invite_a_hand_added_correction() -> None:
    notice = _load(HOOK, "hook_notice")._notice("/h/x.json")
    assert "Do not send this dispatch again" in notice
    assert "To add a correction" not in notice
    assert "producer-rejected" in notice


@pytest.mark.parametrize("skill", ["market-sizing", "competitive-positioning", "financial-model-review"])
def test_the_rejection_step_runs_the_generator(skill: str) -> None:
    text = (PLUGIN / "skills" / skill / "SKILL.md").read_text(encoding="utf-8")
    line = next(ln for ln in text.splitlines() if ln.startswith("- **Producer schema rejection**"))
    assert '2> "$HANDOFF_DIR/producer_rejected.txt"' in line
    assert '--correction producer-rejected --detail-file "$HANDOFF_DIR/producer_rejected.txt"' in line


# --- shapes a real redo takes ----------------------------------------------------------------------------

_P = (
    'cat "$HANDOFF_DIR/checklist_output.json" | python3 "$SCRIPTS/checklist.py" --pretty --run-id R '
    '-o "$ANALYSIS_DIR/checklist.json" 2> "$HANDOFF_DIR/producer_rejected.txt"'
)
_R = (
    'python3 "$SCRIPTS/dispatch_prompt.py" checklist --run-id R --correction producer-rejected '
    '--detail-file "$HANDOFF_DIR/producer_rejected.txt"'
)
_REDO = (
    "CONTEXT: CHECKLIST\nOUTPUT_PATH: /h/o.json\nThe producer rejected...\n"
    "Do NOT write any file other than OUTPUT_PATH.\n"
)


def _shell_rows(calls: list[tuple[str, str, bool]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for i, (cmd, result, is_error) in enumerate(calls):
        use = {"type": "tool_use", "id": f"t{i}", "name": "Bash", "input": {"command": cmd}}
        rows.append({"type": "assistant", "message": {"content": [use]}})
        block = {"type": "tool_result", "tool_use_id": f"t{i}", "content": result, "is_error": is_error}
        rows.append({"type": "user", "message": {"content": [block]}})
    return rows


@pytest.mark.parametrize(
    ("calls", "accepted"),
    [
        ([(_P, "Exit code 1", True), (_R, _REDO, False)], True),
        # The exit code printed by the block's own echo, right after the producer.
        ([(_P + '; echo "EXIT=$?"', "EXIT=1", False), (_R, _REDO, False)], True),
        ([(_P + '; echo "EXIT=$?"', "EXIT=0", False), (_R, _REDO, False)], False),
        ([(_P + '; true; echo "EXIT=$?"', "EXIT=1", False), (_R, _REDO, False)], False),
        # Reading the saved message before the redo leaves it the producer's.
        (
            [(_P, "Exit code 1", True), ('cat "$HANDOFF_DIR/producer_rejected.txt"', "x", False), (_R, _REDO, False)],
            True,
        ),
        (
            [
                (_P, "Exit code 1", True),
                ('head -5 "$HANDOFF_DIR/producer_rejected.txt"', "x", False),
                (_R, _REDO, False),
            ],
            True,
        ),
        # The hand-off dir assigned in the redo's block only.
        ([(_P, "Exit code 1", True), ("HANDOFF_DIR=/h; " + _R, _REDO, False)], True),
        ([("HANDOFF_DIR=/h; " + _P, "Exit code 1", True), (_R, _REDO, False)], True),
        # Still held: a write between, or a different file.
        (
            [
                (_P, "Exit code 1", True),
                ('echo x >> "$HANDOFF_DIR/producer_rejected.txt"', "", False),
                (_R, _REDO, False),
            ],
            False,
        ),
        ([(_P, "Exit code 1", True), (_R.replace("producer_rejected", "other"), _REDO, False)], False),
    ],
)
def test_a_redo_after_a_real_rejection_is_accepted_in_the_shapes_runs_use(
    calls: list[tuple[str, str, bool]], accepted: bool
) -> None:
    hook = _load(HOOK, "hook_shapes")
    assert (hook.latest_printed(_shell_rows(calls), "CONTEXT: CHECKLIST", "/h/o.json") is not None) is accepted


# --- an empty identifier is refused, never printed ------------------------------------------------------

# The flags each generator renders into the prompt or reads from disk. A shell that did not re-assign a
# variable passes "" for it, and the prompt then said `OUTPUT_PATH: /checklist_output.json`.
_RENDERED_FLAGS = {
    "market-sizing": ("--run-id", "--analysis-dir", "--handoff-dir", "--handoff-agent"),
    "competitive-positioning": ("--run-id", "--handoff-agent", "--analysis-dir-agent"),
    "financial-model-review": ("--run-id", "--handoff-agent", "--review-dir-agent", "--review-dir"),
}


@pytest.mark.parametrize(("skill", "flag"), [(s, f) for s, flags in sorted(_RENDERED_FLAGS.items()) for f in flags])
@pytest.mark.parametrize("value", ["", "  "])
def test_an_empty_identifier_is_refused(tmp_path: Path, skill: str, flag: str, value: str) -> None:
    args = GENERATORS[skill](tmp_path)
    assert flag in args, (skill, flag)
    args[args.index(flag) + 1] = value
    r = _gen(args, cwd=tmp_path)  # a generator that does not refuse writes relative to its cwd
    assert r.returncode == 2 and r.stdout == "", (skill, flag, r.returncode, r.stdout[:200])
    assert flag in r.stderr and "empty" in r.stderr, r.stderr


@pytest.mark.parametrize("flag", ["--analysis-dir-agent", "--review-docs-dir", "--review-docs-agent"])
def test_market_sizing_refuses_an_optional_path_given_empty(tmp_path: Path, flag: str) -> None:
    """Given and empty, --analysis-dir-agent fell back to the shell's own path, which a sub-agent's file
    tools are refused on a local session."""
    r = _gen(_ms_args(tmp_path), flag, "", cwd=tmp_path)
    assert r.returncode == 2 and r.stdout == "" and flag in r.stderr, r.stderr


def test_competitive_positioning_refuses_its_shell_paths_given_empty(tmp_path: Path) -> None:
    for flag in ("--analysis-dir", "--handoff-dir"):
        r = _gen(_cp_args(tmp_path), flag, "", cwd=tmp_path)
        assert r.returncode == 2 and r.stdout == "" and flag in r.stderr, (flag, r.stderr)
