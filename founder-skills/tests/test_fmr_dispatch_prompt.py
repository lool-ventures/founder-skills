"""financial-model-review's CHECKLIST prompt is printed by a script, not copied out of SKILL.md.

`fmr_dispatch_prompt.py checklist` prints the prompt from identifiers alone: the paths, the run id, and
whether the review has a model_data.json, which decides the one condition the template carried. Only
the sentence that applies is printed. The prompt ends with the dispatch hook's closing line, and a
corrective redo is printed by the same script (`--correction`), so nothing is typed into it.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

PLUGIN = Path(__file__).resolve().parents[1]
GEN = PLUGIN / "skills" / "financial-model-review" / "scripts" / "fmr_dispatch_prompt.py"
HOOK = PLUGIN / "scripts" / "dispatch_prompt_check.py"
GOLDEN = PLUGIN / "tests" / "fixtures" / "dispatch_prompts" / "financial-model-review.checklist.txt"
ROOT_MARK = "@PLUGIN_ROOT@"
END = "Do NOT write any file other than OUTPUT_PATH.\n"
PRESENT = "Also read model_data.json at /agent/review/model_data.json: its"
ABSENT = "This review has no model_data.json (a conversational or deck-described model)."


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _review(tmp_path: Path, *, model_data: bool) -> Path:
    d = tmp_path / ("with" if model_data else "without")
    d.mkdir(exist_ok=True)
    (d / "inputs.json").write_text("{}", encoding="utf-8")
    if model_data:
        (d / "model_data.json").write_text("{}", encoding="utf-8")
    return d


def _gen(review: Path, *extra: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    args = ["checklist", "--run-id", "R", "--handoff-agent", "/agent/handoff/R", "--review-dir-agent", "/agent/review"]
    return subprocess.run(
        [sys.executable, str(GEN), *args, "--review-dir", str(review), *extra],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=cwd,
    )


def test_the_prompt_is_the_golden_text(tmp_path: Path) -> None:
    """Off a /sessions tree (CLI, cloud), with no model_data.json: the golden text, the root placeholder set
    to the generator's own folder. A prompt change is a deliberate re-copy of the fixture."""
    r = _gen(_review(tmp_path, model_data=False), cwd=tmp_path)
    assert r.returncode == 0 and r.stderr == "", r.stderr
    golden = GOLDEN.read_text(encoding="utf-8")
    assert golden.count(ROOT_MARK) == 1
    assert r.stdout == golden.replace(ROOT_MARK, str(PLUGIN))


@pytest.mark.parametrize("model_data", [True, False])
def test_only_the_model_data_arm_that_applies_is_printed(tmp_path: Path, model_data: bool) -> None:
    out = _gen(_review(tmp_path, model_data=model_data), cwd=tmp_path).stdout
    assert (PRESENT in out, ABSENT in out) == (model_data, not model_data)
    # Each arm names the criterion's only evidence; only the absent arm rules it not applicable.
    assert "`structural_errors` tally is the only evidence for the structural-error criterion" in out
    assert ("mark that criterion not_applicable rather than guessing a pass" in out) is not model_data
    assert "when it exists" not in out  # the reader is never left to decide the condition


@pytest.mark.parametrize("model_data", [True, False])
def test_the_prompt_ends_with_the_hooks_closing_line_once(tmp_path: Path, model_data: bool) -> None:
    out = _gen(_review(tmp_path, model_data=model_data), cwd=tmp_path).stdout
    hook_end = _load(HOOK, "hook_end_fmr").END
    assert END.strip() == hook_end
    assert out.endswith(END) and out.count(hook_end) == 1
    assert out.startswith("CONTEXT: CHECKLIST\nOUTPUT_PATH: /agent/handoff/R/checklist_output.json\nRUN_ID: R\n")
    assert "<" + "REVIEW_DIR_AGENT>" not in out and "<RUN_ID>" not in out and "<MODEL_DATA_LINES>" not in out


def test_the_computed_figures_are_named_in_the_review_folder(tmp_path: Path) -> None:
    """The line before them names the plugin's reference file, so "in the same directory" pointed there."""
    out = _gen(_review(tmp_path, model_data=False), cwd=tmp_path).stdout
    assert "Also read unit_economics.json and runway.json at /agent/review when they exist:" in out
    assert "in the same directory" not in out


@pytest.mark.parametrize(
    ("correction", "line"),
    [
        (
            "missing-file",
            "Your previous receipt claimed a file at OUTPUT_PATH but none exists; use Write to create exactly "
            "that path.\n",
        ),
        ("receipt-only", "Return ONLY the receipt JSON -- no fences, no prose.\n"),
    ],
)
def test_a_corrective_redo_adds_one_printed_line_before_the_closing_line(
    tmp_path: Path, correction: str, line: str
) -> None:
    review = _review(tmp_path, model_data=True)
    plain = _gen(review, cwd=tmp_path).stdout
    redo = _gen(review, "--correction", correction, cwd=tmp_path)
    assert redo.returncode == 0, redo.stderr
    assert redo.stdout == plain[: -len(END)] + line + END


def test_a_producer_rejected_redo_quotes_the_saved_message(tmp_path: Path) -> None:
    review = _review(tmp_path, model_data=False)
    detail = tmp_path / "producer_rejected.txt"
    detail.write_text("Error: items[3].status must be one of pass, fail, warn\n", encoding="utf-8")
    plain = _gen(review, cwd=tmp_path).stdout
    redo = _gen(review, "--correction", "producer-rejected", "--detail-file", str(detail), cwd=tmp_path)
    assert redo.returncode == 0, redo.stderr
    added = (
        "The producer rejected your previous file. Its message, quoted:\n"
        "> Error: items[3].status must be one of pass, fail, warn\n"
        "Write a corrected file to OUTPUT_PATH.\n"
    )
    assert redo.stdout == plain[: -len(END)] + added + END


def test_no_inputs_json_is_refused(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    r = _gen(empty, cwd=tmp_path)
    assert r.returncode == 2 and r.stdout == "" and "inputs.json" in r.stderr


def test_on_a_session_tree_the_reference_is_named_by_its_tail() -> None:
    mod = _load(GEN, "fmr_gen_session")
    out = mod.checklist(run_id="R", handoff_agent="/h", review_dir_agent="/a", has_model_data=True, session_tree=True)
    assert "the file ending skills/financial-model-review/references/checklist-criteria.md" in out
    assert "/skills/financial-model-review/references/" not in out
    assert mod._POINTER.strip() in out and mod._FALLBACK.strip() not in out


def test_the_agent_body_carries_the_full_reference_path() -> None:
    """The pointer sends the sub-agent to the full path its CHECKLIST subtype gives."""
    text = (PLUGIN / "agents" / "financial-model-review.md").read_text(encoding="utf-8")
    section = text[text.index("#### CHECKLIST subtype") :]
    assert "`${CLAUDE_PLUGIN_ROOT}/skills/financial-model-review/references/checklist-criteria.md`" in section


def _step5_generator_block() -> str:
    import re

    text = (PLUGIN / "skills" / "financial-model-review" / "SKILL.md").read_text(encoding="utf-8")
    step = text[text.index("### Step 5: CHECKLIST Dispatch") : text.index("### Step 7:")]
    return next(b for b in re.findall(r"^```bash\n(.*?)^```", step, re.MULTILINE | re.DOTALL) if GEN.name in b)


def test_step_5_sets_every_variable_the_generator_call_uses() -> None:
    """Each shell starts fresh: a variable Step 0 set is empty here unless this block sets it again, and
    the generator refuses an empty one. SCRIPTS is the exception the dispatch hook needs: it trusts
    `$SCRIPTS/<generator>` only when SCRIPTS was set in an earlier block."""
    import re

    block = _step5_generator_block()
    call = block[block.index("python3 ") :]
    used = set(re.findall(r'"\$([A-Z_]+)', call)) - {"SCRIPTS"}
    assert used == {"RUN_ID", "HANDOFF_AGENT", "REVIEW_DIR_AGENT", "REVIEW_DIR"}, used
    for name in used:
        assert re.search(rf"^{name}=\"", block[: block.index("python3 ")], re.MULTILINE), name


def test_step_5s_block_stays_the_hooks_comparand() -> None:
    """The assignments are on the hook's allow-list, so the generator's output is still the comparand."""
    hook = _load(HOOK, "hook_step5_fmr")
    prints, _files = hook.generator_block(_step5_generator_block())
    assert prints


@pytest.mark.parametrize(
    ("model_format", "present"),
    [("deck", False), ("conversational", False), ("spreadsheet", True), ("partial", True), (None, True)],
)
def test_the_arm_follows_this_runs_model_format_not_a_leftover_file(
    tmp_path: Path, model_format: str | None, present: bool
) -> None:
    """The review folder is per company and reused, and model_data.json carries no run id: a spreadsheet
    review's extraction is still there when the same company is reviewed again from a deck. inputs.json is
    this run's, so a deck or conversational model gets the no-extraction sentence whatever is on disk.
    A missing model_format is a spreadsheet, as the producers read it."""
    import json

    review = _review(tmp_path, model_data=True)
    company = {"company_name": "Acme"} if model_format is None else {"model_format": model_format}
    (review / "inputs.json").write_text(json.dumps({"company": company}), encoding="utf-8")
    out = _gen(review, cwd=tmp_path).stdout
    assert (PRESENT in out, ABSENT in out) == (present, not present), out[:600]


def test_an_unreadable_inputs_json_is_refused(tmp_path: Path) -> None:
    review = _review(tmp_path, model_data=True)
    (review / "inputs.json").write_text("{not json", encoding="utf-8")
    r = _gen(review, cwd=tmp_path)
    assert r.returncode == 2 and r.stdout == "" and "inputs.json" in r.stderr
