"""The CHECKLIST prompt is generated, and the grader never reads the revision's history.

In round 2 of a live run the main thread told the grader "round 2 after a revision … down from a
mechanically-forced N% in round 1", and the grader wrote it to the founder: "the two builds now
diverge … after being set independently". Round 1's prompt was not the template either (0/2): it
dropped paragraphs and inserted a verdict ("score approaches_reconciled accordingly"). Two channels:
the prompt the main thread writes, and methodology.json's revision record, which the grader read.

`dispatch_prompt.py checklist` prints the prompt from identifiers alone -- no round, no free text --
and writes a copy of methodology.json holding only what a checklist item grades, which the prompt
names in place of the canonical file. The PreToolUse dispatcher holds a CHECKLIST dispatch that is
not the printed prompt (test_dispatch_prompt_hook.py covers the mechanism for both contexts).
"""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path
from typing import Any

import pytest

_SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "market-sizing" / "scripts"
_SKILL = _SCRIPTS.parent / "SKILL.md"
_spec = importlib.util.spec_from_file_location("ms_dispatch_prompt_cl", _SCRIPTS / "dispatch_prompt.py")
assert _spec is not None and _spec.loader is not None
dp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dp)
_cl_spec = importlib.util.spec_from_file_location("ms_checklist_cl", _SCRIPTS / "checklist.py")
assert _cl_spec is not None and _cl_spec.loader is not None
checklist_mod = importlib.util.module_from_spec(_cl_spec)
_cl_spec.loader.exec_module(checklist_mod)

_HISTORY = {
    "red_team_revision": {"approved_by_founder": True, "founder_words": "use independent estimates", "changes": []},
    "founder_notes": ["The churn figure is from Q2."],
    "gate_defaults": ["the revision question"],
    "accepted_warnings": [{"code": "TAM_DISCREPANCY", "reason": "x", "match": "differ"}],
}
_BASE = {"approach_chosen": "both", "rationale": "Both builds, as asked.", "metadata": {"run_id": "R"}}


def _analysis(tmp_path: Path, methodology: dict[str, Any]) -> tuple[Path, Path]:
    d = tmp_path / "analysis"
    h = d / "handoff" / "R" / "r2"
    h.mkdir(parents=True)
    for name in ("inputs.json", "validation.json", "sizing.json"):
        (d / name).write_text("{}")
    (d / "methodology.json").write_text(json.dumps(methodology))
    return d, h


def _prompt(d: Path, h: Path) -> str:
    out: str = dp.checklist("R", str(d), str(h), "AGENT/handoff/R/r2", "AGENT", "PLUGIN")
    return out


def test_the_prompt_does_not_change_with_the_revision_history(tmp_path: Path) -> None:
    d1, h1 = _analysis(tmp_path / "a", _BASE)
    d2, h2 = _analysis(tmp_path / "b", {**_BASE, **_HISTORY})
    assert "red_team_revision" in json.loads((d2 / "methodology.json").read_text())  # positive control
    assert _prompt(d1, h1) == _prompt(d2, h2)


def test_the_grader_reads_a_methodology_without_the_history(tmp_path: Path) -> None:
    d, h = _analysis(tmp_path, {**_BASE, **_HISTORY})
    prompt = _prompt(d, h)
    view = json.loads((h / "checklist_view" / "methodology.json").read_text())
    assert view == _BASE
    assert "AGENT/handoff/R/r2/checklist_view/methodology.json" in prompt
    assert "AGENT/methodology.json" not in prompt
    for name in ("inputs.json", "validation.json", "sizing.json"):
        assert f"AGENT/{name}" in prompt


def test_the_prompt_carries_the_contract_checklist_py_reads(tmp_path: Path) -> None:
    prompt = _prompt(*_analysis(tmp_path, _BASE))
    assert prompt.startswith("CONTEXT: CHECKLIST\nOUTPUT_PATH: AGENT/handoff/R/r2/checklist_output.json\nRUN_ID: R\n")
    assert '"items"' in prompt
    for status in checklist_mod.VALID_STATUSES:
        assert status in prompt
    assert set(re.findall(r'"id"\s*:\s*"([a-z][a-z0-9_]+)"', prompt)) == set(checklist_mod.VALID_IDS)
    assert prompt.rstrip().endswith("Do NOT write any file other than OUTPUT_PATH.")
    assert "PLUGIN/skills/market-sizing/references/pitfalls-checklist.md" in prompt
    for word in ("round", "revision", "revised"):
        assert word not in prompt.lower(), word


def test_a_missing_artifact_is_refused(tmp_path: Path) -> None:
    d, h = _analysis(tmp_path, _BASE)
    (d / "sizing.json").unlink()
    with pytest.raises(FileNotFoundError):
        _prompt(d, h)


def test_step_6b_generates_the_prompt() -> None:
    text = _SKILL.read_text(encoding="utf-8")
    section = text[text.index("#### CHECKLIST dispatch prompt template") : text.index("### Step 6c")]
    assert '"$SCRIPTS/dispatch_prompt.py" checklist' in section
    assert "CONTEXT: CHECKLIST" not in section  # the template now lives in the generator only


# --- a corrective redo is a printed prompt too ---------------------------------------------------


_END = "Do NOT write any file other than OUTPUT_PATH.\n"


@pytest.mark.parametrize("kind", ["missing-file", "receipt-only"])
def test_a_corrective_redo_is_printed_with_its_line_before_the_closing_one(tmp_path: Path, kind: str) -> None:
    """SKILL.md's exit-3 / exit-6 redo was "same prompt plus one line", typed by the main thread. The
    dispatch hook holds any prompt that is not the printed one, so that redo was held twice and its reason
    ("send the printed prompt unchanged") dropped the correction. The generator now prints the redo."""
    d, h = _analysis(tmp_path, _BASE)
    plain = _prompt(d, h)
    redo: str = dp.checklist("R", str(d), str(h), "AGENT/handoff/R/r2", "AGENT", "PLUGIN", correction=kind)
    assert redo.endswith(_END), redo[-200:]
    assert redo.replace(dp.CORRECTIONS[kind] + "\n", "", 1) == plain
    assert redo.index(dp.CORRECTIONS[kind]) < redo.index(_END)


def test_the_red_team_redo_is_printed_too(tmp_path: Path) -> None:
    d, h = _analysis(tmp_path, _BASE)
    for name in ("sizing.json", "sensitivity.json", "checklist.json"):
        (d / name).write_text("{}")
    plain: str = dp.red_team("R", str(d), str(h), "AGENT/handoff/R/r2")
    redo: str = dp.red_team("R", str(d), str(h), "AGENT/handoff/R/r2", correction="missing-file")
    assert redo.endswith(_END)
    assert redo.replace(dp.CORRECTIONS["missing-file"] + "\n", "", 1) == plain


def test_the_redo_instructions_run_the_generator_for_the_generated_contexts() -> None:
    text = _SKILL.read_text(encoding="utf-8")
    assert "--correction missing-file" in text and "--correction receipt-only" in text
