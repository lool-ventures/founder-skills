"""Gate records (`check_handoff.py`) and the bypass check compose uses (`_handoff_audit.py`)."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import types
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
_CHECK = _SCRIPTS / "check_handoff.py"


def _load() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("_handoff_audit", _SCRIPTS / "_handoff_audit.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


audit = _load()


def _gate(path: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(_CHECK), str(path), *extra], capture_output=True, text=True)


def test_a_passing_gate_writes_a_record_that_matches_the_file(tmp_path: Path) -> None:
    f = tmp_path / "checklist_output.json"
    f.write_text('{"items": []}', encoding="utf-8")
    result = _gate(f)
    assert result.returncode == 0, result.stdout
    assert json.loads(result.stdout)["gate_record"] == str(f) + audit.GATE_SUFFIX
    record = json.loads((tmp_path / ("checklist_output.json" + audit.GATE_SUFFIX)).read_text(encoding="utf-8"))
    assert record == {"sha256": audit.file_sha256(str(f)), "format": "json"}
    assert audit.gate_ok(str(f))


def test_a_failing_gate_writes_no_record(tmp_path: Path) -> None:
    f = tmp_path / "checklist_output.json"
    f.write_text("{not json", encoding="utf-8")
    assert _gate(f).returncode == 4
    assert not (tmp_path / ("checklist_output.json" + audit.GATE_SUFFIX)).exists()
    assert not audit.gate_ok(str(f))


def test_a_markdown_gate_records_its_format(tmp_path: Path) -> None:
    f = tmp_path / "coaching.md"
    f.write_text("The sizing holds up.\n", encoding="utf-8")
    assert _gate(f, "--format", "markdown").returncode == 0
    record = json.loads((tmp_path / ("coaching.md" + audit.GATE_SUFFIX)).read_text(encoding="utf-8"))
    assert record["format"] == "markdown"


def test_a_file_rewritten_after_its_gate_no_longer_counts(tmp_path: Path) -> None:
    f = tmp_path / "sensitivity_output.json"
    f.write_text('{"a": 1}', encoding="utf-8")
    assert _gate(f).returncode == 0
    assert audit.gate_ok(str(f))
    f.write_text('{"a": 2}', encoding="utf-8")
    assert not audit.gate_ok(str(f))


def test_a_corrupt_record_does_not_count(tmp_path: Path) -> None:
    f = tmp_path / "x_output.json"
    f.write_text("{}", encoding="utf-8")
    (tmp_path / ("x_output.json" + audit.GATE_SUFFIX)).write_text("garbage", encoding="utf-8")
    assert not audit.gate_ok(str(f))


def test_bypassed_names_only_the_steps_with_no_gated_candidate(tmp_path: Path) -> None:
    """Positive control and seeded bypass on the same run dir: the gated step is silent, the ungated one
    fires, and a requirement is satisfied by ANY of its candidates (a later round, or the first)."""
    gated = tmp_path / "top_down_output.json"
    gated.write_text("{}", encoding="utf-8")
    assert _gate(gated).returncode == 0
    (tmp_path / "r2").mkdir()
    gated_r2 = tmp_path / "r2" / "checklist_output.json"
    gated_r2.write_text("{}", encoding="utf-8")
    assert _gate(gated_r2).returncode == 0
    staged_not_gated = tmp_path / "sensitivity_output.json"
    staged_not_gated.write_text("{}", encoding="utf-8")  # present, but never passed the gate

    requirements = [
        ("sizing", ["top_down_output.json"]),
        ("checklist", ["r2/checklist_output.json", "checklist_output.json"]),
        ("sensitivity", ["sensitivity_output.json"]),
        ("review", ["redteam_output.json"]),
    ]
    assert audit.bypassed(str(tmp_path), requirements) == ["sensitivity", "review"]
    # Control: once every step is gated, nothing fires.
    assert _gate(staged_not_gated).returncode == 0
    (tmp_path / "redteam_output.json").write_text("{}", encoding="utf-8")
    assert _gate(tmp_path / "redteam_output.json").returncode == 0
    assert audit.bypassed(str(tmp_path), requirements) == []


def test_known_residual_a_step_gated_once_then_degraded_still_passes(tmp_path: Path) -> None:
    """KNOWN, NOT A GUARANTEE. The check proves a gated hand-off exists and matches its record -- not
    that the producer consumed it. A step that passed the gate on its first dispatch and then took the
    message-channel fallback on a re-dispatch within the same run still has a matching record, and is
    not disclosed. Closing this needs each producer to stamp the sha of its own input. If this test ever
    starts failing because the check got stronger, update the docstrings that state the residual."""
    first = tmp_path / "checklist_output.json"
    first.write_text('{"attempt": 1}', encoding="utf-8")
    assert _gate(first).returncode == 0
    # ...the re-dispatch degrades: its JSON is staged outside the hand-off dir and piped to the producer.
    (tmp_path / "staging_checklist_input.json").write_text('{"attempt": 2}', encoding="utf-8")
    assert audit.bypassed(str(tmp_path), [("checklist", ["checklist_output.json"])]) == []


def _load_compose(skill: str) -> types.ModuleType:
    path = _SCRIPTS.parent / "skills" / skill / "scripts" / "compose_report.py"
    sys.path.insert(0, str(path.parent))
    try:
        spec = importlib.util.spec_from_file_location(f"{skill.replace('-', '_')}_compose_for_audit", path)
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        sys.path.remove(str(path.parent))
    return mod


# Every skill's compose reports HANDOFF_BYPASSED; the list is derived, so a new skill joins the check.
_BYPASS_SKILLS = sorted(p.name for p in (_SCRIPTS.parent / "skills").iterdir() if (p / "SKILL.md").is_file())


def test_every_skill_reports_bypassed_hand_offs() -> None:
    assert len(_BYPASS_SKILLS) == 6, _BYPASS_SKILLS


def test_the_founder_wording_is_one_text_across_the_fleet() -> None:
    """The label and message are founder-facing and must say the same thing in every report. The
    wording states only what is measured -- the step was not put through the check -- because a
    missing record comes from the fallback OR from a skipped gate, and the check cannot tell which."""
    assert audit.WARNING_LABEL == "Some Steps Were Not Checked"
    assert "not put through the check" in audit.founder_message(["x"])
    assert audit.founder_message(["a", "b", "c"]).startswith("The results of a, b and c were not")
    for skill in _BYPASS_SKILLS:
        mod = _load_compose(skill)
        if not hasattr(mod, "WARNING_LABELS"):
            # cap-table builds its warnings inline and takes label and message straight from the shared
            # module (asserted by its own tests); there is no per-skill map to drift.
            assert hasattr(mod, "_handoff_bypassed"), skill
            continue
        assert mod.WARNING_LABELS["HANDOFF_BYPASSED"] == audit.WARNING_LABEL, skill
        assert mod.WARNING_SEVERITY["HANDOFF_BYPASSED"] == "medium", skill
        # A skill with an accepted_warnings mechanism must exclude the code from it; one without has
        # nothing that could clear it (financial-model-review has no post-compose acceptance).
        if hasattr(mod, "ACCEPTIBLE_SEVERITIES"):
            assert "HANDOFF_BYPASSED" in mod._UNACCEPTABLE_MEDIUM, skill
        # One copy of the text: no compose may keep its own.
        assert not hasattr(mod, "_bypass_message") and not hasattr(mod, "_BYPASS_SENTENCE"), skill


def test_the_founder_wording_does_not_vouch_for_results_it_cannot_see() -> None:
    """With the records folder gone, nothing shows how those steps ran, so the text may not claim the
    results are unaffected; it says only that the missing record is not itself a sign of error."""
    for text in (audit.VERDICT_SENTENCE, audit.founder_message(["the moat scoring"])):
        assert "unaffected" not in text
        assert "does not mean the results are wrong" in text
