"""Tests for competitive-positioning's delivery gate.

The gate exists because three of this skill's worst defects were the same shape — analysis
computed, paid for, and never rendered — and each was found only by reading a live run's
artifacts by hand against what reached the founder. Every check below corresponds to a defect
that actually shipped, so a test that stops failing on its own defect is a regression in the
gate, not a cleanup opportunity.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "founder-skills" / "skills" / "competitive-positioning" / "scripts" / "verify_positioning.py"


def _run(dir_path: Path, *args: str) -> tuple[int, dict[str, Any] | None, str]:
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--dir", str(dir_path), *args],
        capture_output=True,
        text=True,
    )
    try:
        data = json.loads(proc.stdout) if proc.stdout.strip() else None
    except json.JSONDecodeError:
        data = None
    return proc.returncode, data, proc.stderr


def _write(d: Path, name: str, obj: Any) -> None:
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(json.dumps(obj, indent=2) if not isinstance(obj, str) else obj, encoding="utf-8")


RATIONALE_X = "Firmness is what gets a capacity number into the site design."
RATIONALE_Y = "Integration burden decides whether a live site will touch it at all."


def _publishable(d: Path) -> None:
    """Write a minimal artifact set that the gate should pass."""
    _write(
        d,
        "landscape.json",
        {"competitors": [{"slug": "acme-co", "name": "Acme Co"}], "metadata": {"run_id": "R"}},
    )
    _write(d, "positioning.json", {"views": [], "metadata": {"run_id": "R"}})
    _write(
        d,
        "moat_scores.json",
        {"companies": {"_startup": {}, "acme-co": {}}, "metadata": {"run_id": "R"}},
    )
    _write(
        d,
        "positioning_scores.json",
        {
            "views": [
                {
                    "view_id": "v1",
                    "x_axis_rationale": RATIONALE_X,
                    "y_axis_rationale": RATIONALE_Y,
                    "startup_x_rank": 1,
                    "startup_y_rank": 2,
                    "competitor_count": 1,
                    "points": [{"competitor": "_startup"}, {"competitor": "acme-co"}],
                }
            ],
            "views_fingerprint": "f" * 64,
            "metadata": {"run_id": "R"},
        },
    )
    _write(d, "checklist.json", {"items": [], "graded_against": {"views_fingerprint": "f" * 64}})
    _write(d, "report.json", {"ok": True})
    _write(d, "report.md", f"# Report\n\n- Rationale: {RATIONALE_X}\n- Rationale: {RATIONALE_Y}\n")


def test_minimal_publishable_set_passes(tmp_path: Path) -> None:
    _publishable(tmp_path)
    rc, data, stderr = _run(tmp_path)
    assert rc == 0, f"expected publishable, got gaps: {stderr}"
    assert data is not None and data["status"] == "publishable"


def test_blank_axis_rationale_is_a_gap(tmp_path: Path) -> None:
    """The measured defect: every compliant run emitted blank rationales while the checklist
    graded POS_05 as a pass on text no founder could see."""
    _publishable(tmp_path)
    ps = json.loads((tmp_path / "positioning_scores.json").read_text())
    ps["views"][0]["x_axis_rationale"] = ""
    _write(tmp_path, "positioning_scores.json", ps)
    rc, _, stderr = _run(tmp_path)
    assert rc == 1
    assert "empty X-axis rationale" in stderr


def test_rationale_present_but_not_rendered_is_a_gap(tmp_path: Path) -> None:
    """Computed-and-not-rendered is the whole point of this gate: a rationale that exists in the
    scores but never reaches report.md is invisible to the founder and to every unit test."""
    _publishable(tmp_path)
    _write(tmp_path, "report.md", "# Report\n\n- Rationale: \n- Rationale: \n")
    rc, _, stderr = _run(tmp_path)
    assert rc == 1
    assert "does not appear in report.md" in stderr


def test_raw_enum_token_in_report_is_a_gap(tmp_path: Path) -> None:
    _publishable(tmp_path)
    md = (tmp_path / "report.md").read_text() + "\n- **Verdict:** partially_holds\n"
    _write(tmp_path, "report.md", md)
    rc, _, stderr = _run(tmp_path)
    assert rc == 1
    assert "partially_holds" in stderr


def test_internal_field_name_in_report_is_a_gap(tmp_path: Path) -> None:
    _publishable(tmp_path)
    _write(tmp_path, "report.md", (tmp_path / "report.md").read_text() + "\nFive dimensions (moat_count: 5).\n")
    rc, _, stderr = _run(tmp_path)
    assert rc == 1
    assert "moat_count" in stderr


def test_criterion_id_in_coaching_commentary_is_a_gap(tmp_path: Path) -> None:
    """Measured on a real delivered report: NARR_01/NARR_03/NARR_04 in the commentary."""
    _publishable(tmp_path)
    md = (tmp_path / "report.md").read_text() + "\n## Coaching Commentary\n\nThe NARR_03 warning matters.\n"
    _write(tmp_path, "report.md", md)
    rc, _, stderr = _run(tmp_path)
    assert rc == 1
    assert "NARR_03" in stderr


def test_criterion_id_anywhere_founder_facing_is_a_gap(tmp_path: Path) -> None:
    """Inverted from "only the commentary is held to the rule".

    That exemption assumed a checklist section that legitimately named criterion IDs. The current
    report has no such section — its headings are Executive Summary, Competitor Landscape, What's
    Changed Recently, Competitor Set Verification, Positioning Analysis, Moat Assessment,
    Differentiation Stress-Test, Key Findings, Warnings, Coaching Commentary. So there is no legitimate
    source of a bare ID in the body, while delivered reports from 2026-08-01 carried COVER_02/03/04 and
    NARR_01 outside the commentary, where this check never looked.

    The founder-text scan cannot cover this: its candidate rule is lowercase-only, so ALLCAPS ids are
    invisible to it. Hence the dedicated regex.
    """
    _publishable(tmp_path)
    _write(tmp_path, "report.md", (tmp_path / "report.md").read_text() + "\n| NARR_03 | warn |\n")
    rc, out, stderr = _run(tmp_path)
    assert rc == 1, stderr
    assert "criterion ID 'NARR_03'" in json.dumps(out)


def test_unrendered_verification_verdicts_are_a_gap(tmp_path: Path) -> None:
    """The adversarial verdicts reached no renderer, so a competitor judged not-a-competitor was
    tabled indistinguishably from a genuine one."""
    _publishable(tmp_path)
    _write(
        tmp_path,
        "competitor_verification.json",
        {"verdicts": [{"slug": "acme-co", "verdict": "genuine"}], "recall_gaps": {}},
    )
    rc, _, stderr = _run(tmp_path)
    assert rc == 1
    assert "no verification section" in stderr


def test_kept_not_a_competitor_must_be_named(tmp_path: Path) -> None:
    _publishable(tmp_path)
    md = (tmp_path / "report.md").read_text() + "\n## Competitor Set Verification\n\nA table.\n"
    _write(tmp_path, "report.md", md)
    _write(
        tmp_path,
        "competitor_verification.json",
        {"verdicts": [{"slug": "acme-co", "verdict": "not_a_competitor"}], "recall_gaps": {}},
    )
    rc, _, stderr = _run(tmp_path)
    assert rc == 1
    assert "was judged not_a_competitor and kept" in stderr
    assert "acme-co" in stderr


def test_checklist_graded_against_a_stale_map_is_a_gap(tmp_path: Path) -> None:
    """run_id parity cannot detect this: a re-score does not change the run_id."""
    _publishable(tmp_path)
    _write(tmp_path, "checklist.json", {"items": [], "graded_against": {"views_fingerprint": "a" * 64}})
    rc, _, stderr = _run(tmp_path)
    assert rc == 1
    assert "different positioning map" in stderr


def test_absent_fingerprint_is_silent(tmp_path: Path) -> None:
    """Back-compat: an artifact predating the field has unknown provenance, never asserted stale."""
    _publishable(tmp_path)
    _write(tmp_path, "checklist.json", {"items": []})
    rc, _, stderr = _run(tmp_path)
    assert rc == 0, stderr


def test_competitor_missing_from_scoring_is_a_gap(tmp_path: Path) -> None:
    _publishable(tmp_path)
    ls = json.loads((tmp_path / "landscape.json").read_text())
    ls["competitors"].append({"slug": "ghost-co", "name": "Ghost Co"})
    _write(tmp_path, "landscape.json", ls)
    rc, _, stderr = _run(tmp_path)
    assert rc == 1
    assert "ghost-co" in stderr


def test_rank_beyond_the_ranked_set_is_a_gap(tmp_path: Path) -> None:
    """The delivered report once read 'Y=11 (of 10 competitors)'."""
    _publishable(tmp_path)
    ps = json.loads((tmp_path / "positioning_scores.json").read_text())
    ps["views"][0]["startup_y_rank"] = 99
    _write(tmp_path, "positioning_scores.json", ps)
    rc, _, stderr = _run(tmp_path)
    assert rc == 1
    assert "exceeds" in stderr


def test_lost_recall_candidate_is_reported(tmp_path: Path) -> None:
    """Set comparison, not emptiness: a deferred list holding one of several candidates would
    otherwise suppress the finding while the rest were silently lost."""
    _publishable(tmp_path)
    ls = json.loads((tmp_path / "landscape.json").read_text())
    ls["deferred_recall_candidates"] = [{"slug": "kept-one"}]
    _write(tmp_path, "landscape.json", ls)
    _write(
        tmp_path,
        "competitor_verification.json",
        {
            "verdicts": [],
            "recall_gaps": {"unmatched": [{"slug": "kept-one"}, {"slug": "lost-one"}]},
        },
    )
    rc, _, stderr = _run(tmp_path)
    assert "lost-one" in stderr
    assert "kept-one" not in stderr.replace("kept-one'", "")  # only the lost one is named


def test_deferred_absent_entirely_is_silent(tmp_path: Path) -> None:
    """Absent (rather than empty) means a pre-gate artifact — never asserted against."""
    _publishable(tmp_path)
    _write(
        tmp_path,
        "competitor_verification.json",
        {"verdicts": [], "recall_gaps": {"unmatched": [{"slug": "someone"}]}},
    )
    rc, _, stderr = _run(tmp_path)
    assert rc == 0, stderr
    assert "someone" not in stderr


def test_explorer_dead_payload_key_is_a_gap(tmp_path: Path) -> None:
    """The explorer embedded the whole scored layer and read none of it."""
    _publishable(tmp_path)
    _write(
        tmp_path,
        "explore.html",
        '<html><script>const DATA = {"views": [], "view_scores": {}};\nvar a = DATA.views;</script></html>',
    )
    rc, _, stderr = _run(tmp_path)
    assert rc == 1
    assert "view_scores" in stderr


def test_gate_1_skips_the_rendered_checks(tmp_path: Path) -> None:
    """Mid-pipeline the report does not exist yet; demanding it would be noise."""
    _publishable(tmp_path)
    os.remove(tmp_path / "report.md")
    os.remove(tmp_path / "report.json")
    rc, _, stderr = _run(tmp_path, "--gate", "1")
    assert rc == 0, stderr


def test_missing_required_artifact_is_a_gap(tmp_path: Path) -> None:
    _publishable(tmp_path)
    os.remove(tmp_path / "checklist.json")
    rc, _, stderr = _run(tmp_path)
    assert rc == 1
    assert "checklist.json" in stderr


def test_receipt_shape_with_output_flag(tmp_path: Path) -> None:
    _publishable(tmp_path)
    out = tmp_path / "verify.json"
    rc, data, _ = _run(tmp_path, "-o", str(out))
    assert rc == 0
    assert data is not None and data["ok"] is True and data["status"] == "publishable"
    assert json.loads(out.read_text())["_produced_by"] == "verify_positioning"


def test_a_slug_identical_to_its_display_name_is_not_a_leak(tmp_path: Path) -> None:
    """Measured false positive on a live run: a competitor literally named 'n8n' has slug 'n8n', so
    the founder is already seeing the name. Flagging it told the operator to fix something correct.

    The comparison is on a normalized form, so 'Acme Co' / 'acme-co' is still caught."""
    _publishable(tmp_path)
    _write(
        tmp_path,
        "landscape.json",
        {"competitors": [{"slug": "n8n", "name": "n8n"}], "metadata": {"run_id": "R"}},
    )
    _write(
        tmp_path,
        "moat_scores.json",
        {"companies": {"_startup": {}, "n8n": {}}, "metadata": {"run_id": "R"}},
    )
    ps = json.loads((tmp_path / "positioning_scores.json").read_text())
    ps["views"][0]["points"] = [{"competitor": "_startup"}, {"competitor": "n8n"}]
    _write(tmp_path, "positioning_scores.json", ps)
    md = (tmp_path / "report.md").read_text() + "\n- [~] **Researched Without Source:** n8n: no source\n"
    _write(tmp_path, "report.md", md)
    rc, _, stderr = _run(tmp_path)
    assert rc == 0, f"a slug identical to its name must not be flagged: {stderr}"


def test_a_slug_differing_from_its_name_is_still_a_leak(tmp_path: Path) -> None:
    """The counterpart — the normalization must not weaken the real check."""
    _publishable(tmp_path)
    md = (tmp_path / "report.md").read_text() + "\n- [~] **Shallow Competitor Profile:** acme-co: thin\n"
    _write(tmp_path, "report.md", md)
    rc, _, stderr = _run(tmp_path)
    assert rc == 1
    assert "acme-co" in stderr


def test_gate_flags_an_internal_artifact_filename_in_the_report(tmp_path: Path) -> None:
    """Sub-agent evidence is printed verbatim; a sibling skill's live run put inputs.json in ten items."""
    _publishable(tmp_path)
    md = (tmp_path / "report.md").read_text()
    (tmp_path / "report.md").write_text(md + "\n- **COVER_01**: landscape.json reports input_mode: deck\n")
    rc, out, _err = _run(tmp_path)
    msgs = json.dumps(out)
    assert "names the internal file 'landscape.json'" in msgs, "an artifact filename in the report was not flagged"
    assert rc == 1, "a founder-facing filename must fail the delivery gate"


def test_gate_does_not_flag_a_founder_supplied_filename(tmp_path: Path) -> None:
    _publishable(tmp_path)
    md = (tmp_path / "report.md").read_text()
    (tmp_path / "report.md").write_text(md + "\n- the deck you sent, acme_pitch.xlsx, names no competitor\n")
    _rc, out, _err = _run(tmp_path)
    assert "names the internal file" not in json.dumps(out)


def test_gate_flags_a_filename_in_checklist_evidence_even_when_unrendered(tmp_path: Path) -> None:
    """Artifact level, not just the rendered report.

    A live run produced 11 items citing artifact filenames in evidence while report.md scanned clean —
    this skill renders checklist evidence nowhere. Checking only the report reports a compliance that
    does not exist.
    """
    _publishable(tmp_path)
    checklist = json.loads((tmp_path / "checklist.json").read_text())
    # The publishable fixture carries no items; add one so the scan has something to look at.
    checklist["items"] = [{"id": "COVER_02", "status": "fail", "evidence": "landscape.json reports input_mode: deck"}]
    (tmp_path / "checklist.json").write_text(json.dumps(checklist))
    rc, out, _err = _run(tmp_path)
    msgs = json.dumps(out)
    assert "cites the internal file 'landscape.json'" in msgs
    assert rc == 0, "unrendered evidence is not founder-facing yet, so it must not block hand-over"
    assert out is not None and out["summary"]["error_count"] == 0
    assert out["summary"]["warning_count"] >= 1
