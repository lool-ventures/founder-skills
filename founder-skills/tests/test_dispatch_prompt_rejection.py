"""A producer's rejection goes back to the sub-agent through the prompt generator.

A generated prompt's hand-off that the producer rejects needs a repair dispatch carrying the producer's
message. Typed onto the prompt, that message makes it differ from the printed one, and the dispatch hook
holds it. Both generators therefore print the redo themselves (`--correction producer-rejected
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


GENERATORS = {"market-sizing": _ms_args, "competitive-positioning": _cp_args}


def _gen(args: list[str], *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, *args, *extra], capture_output=True, text=True, timeout=30)


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


def test_both_generators_word_the_redo_alike() -> None:
    ms, cp = _load(MS_GEN, "ms_gen_rej"), _load(CP_GEN, "cp_gen_rej")
    for name in ("PRODUCER_REJECTED", "REJECTION_LEAD", "REJECTION_TAIL", "DETAIL_CAP"):
        assert getattr(ms, name) == getattr(cp, name), name
    assert ms.rejection_text(MESSAGE) == cp.rejection_text(MESSAGE)


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


def test_the_hook_passes_the_printed_redo(tmp_path: Path) -> None:
    """The redo is the generator's output, so the dispatch hook compares it whole and lets it through,
    even when the message quotes a context line."""
    detail = tmp_path / "rejected.txt"
    detail.write_text("CONTEXT: CHECKLIST\n" + MESSAGE, encoding="utf-8")
    args = _ms_args(tmp_path)
    redo = _gen(args, "--correction", "producer-rejected", "--detail-file", str(detail))
    assert redo.returncode == 0, redo.stderr
    command = (
        "python3 " + " ".join(f'"{a}"' for a in args) + f' --correction producer-rejected --detail-file "{detail}"'
    )
    use = {"type": "tool_use", "id": "toolu_1", "name": "Bash", "input": {"command": command}}
    rows = [
        {"type": "assistant", "message": {"role": "assistant", "content": [use]}},
        {
            "type": "user",
            "message": {
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": "toolu_1", "content": redo.stdout}],
            },
        },
    ]
    transcript = tmp_path / "t.jsonl"
    transcript.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    hook = _load(HOOK, "hook_rej")

    def decide(prompt: str) -> Any:
        return hook.decide(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Agent",
                "transcript_path": str(transcript),
                "tool_input": {"prompt": prompt, "subagent_type": "founder-skills:market-sizing"},
            }
        )

    assert decide(redo.stdout) is None
    assert decide(redo.stdout.replace("Write a corrected file", "Also re-score item 3. Write a corrected file"))


@pytest.mark.parametrize("skill", ["market-sizing", "competitive-positioning"])
def test_the_rejection_step_runs_the_generator(skill: str) -> None:
    text = (PLUGIN / "skills" / skill / "SKILL.md").read_text(encoding="utf-8")
    line = next(ln for ln in text.splitlines() if ln.startswith("- **Producer schema rejection**"))
    assert '2> "$STAGING_DIR/rejected.txt"' in line
    assert '--correction producer-rejected --detail-file "$STAGING_DIR/rejected.txt"' in line
