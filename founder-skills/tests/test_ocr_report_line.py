"""What a founder is told about Step 3.95's machine read, in report.md and report.html.

Each case is the owner's wording (option B, "selectable text"), pinned exactly. The line never calls a figure
wrong, never names one, and appears only when this run's check was made for this reconciliation.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "skills" / "deck-review" / "scripts"
SKILL_MD = HERE.parent / "skills" / "deck-review" / "SKILL.md"
sys.path[:0] = [str(SCRIPTS)]
import _reconciliation_prose as P  # type: ignore[import-not-found]  # noqa: E402

RUN = "RID"
SHA = "a" * 64
LEAD_2 = "Slides 4 and 7 carry little or no selectable text, so the figures this section uses from them were read "
LEAD_2 += "from how the slides look."
_FORBIDDEN = ("wrong", "incorrect", "error", "mistake", "OCR", "tesseract", "machine-read figures")


def _check(status: str, *, checked: int = 0, found: int = 0, not_checked: int = 0, read: Any = (4, 7)) -> dict:
    return {
        "status": status,
        "counts": {"in_scope": checked + not_checked, "checked": checked, "found": found, "not_checked": not_checked},
        "pages_machine_read": list(read),
        "slides": list(read),
        "metadata": {"run_id": RUN, "reconciliation_sha256": SHA},
    }


def _line(check: dict | None, image_only: bool = False) -> str:
    return str(P.ocr_read_line(check, reconciliation_sha256=SHA, run_id=RUN, image_only_deck=image_only))


def test_all_found() -> None:
    assert _line(_check("checked", checked=3, found=3)) == (
        f"{LEAD_2} A separate machine read of those slides found all 3 of them as written."
    )


def test_one_slide_one_figure_is_singular() -> None:
    assert _line(_check("checked", checked=1, found=1, read=(4,))) == (
        "Slide 4 carries little or no selectable text, so the figures this section uses from them were read from "
        "how the slides look. A separate machine read of that slide found it as written."
    )


def test_some_not_found_with_three_or_more() -> None:
    assert _line(_check("checked", checked=5, found=4)) == (
        f"{LEAD_2} A separate machine read of those slides found 4 of those 5 figures as written. Machine reads "
        "often miss numbers in charts and styled text, so a figure it did not find may well be right; if one matters "
        "to you, compare it with the slide itself."
    )


def test_some_not_found_under_three_prints_only_the_lead_on_a_mixed_deck() -> None:
    assert _line(_check("checked", checked=2, found=1)) == LEAD_2
    assert _line(_check("checked", checked=2, found=1), image_only=True) == ""


@pytest.mark.parametrize("status", ["low_match", "unavailable", "none_read"])
def test_no_count_shown_says_only_how_the_figures_were_read(status: str) -> None:
    assert _line(_check(status)) == LEAD_2
    assert _line(_check(status), image_only=True) == "", "the deck's own image note already says it"


def test_not_read_figures_are_added() -> None:
    line = _line(_check("checked", checked=3, found=3, not_checked=2))
    assert line.endswith(" 2 were not machine-read.")
    assert _line(_check("checked", checked=3, found=3, not_checked=1)).endswith(" 1 was not machine-read.")


@pytest.mark.parametrize("status", ["not_applicable", "no_figures"])
def test_nothing_new_otherwise(status: str) -> None:
    assert _line(_check(status)) == ""


def test_another_runs_or_a_stale_check_says_nothing() -> None:
    check = _check("checked", checked=3, found=3)
    assert P.ocr_read_line(check, reconciliation_sha256=SHA, run_id="other", image_only_deck=False) == ""
    assert P.ocr_read_line(check, reconciliation_sha256="b" * 64, run_id=RUN, image_only_deck=False) == ""


def test_no_line_calls_a_figure_wrong_or_names_the_tooling() -> None:
    lines = [
        _line(_check("checked", checked=c, found=f, not_checked=k))
        for c, f, k in ((3, 3, 0), (5, 2, 1), (1, 1, 0), (2, 1, 0))
    ] + [_line(_check(s)) for s in ("low_match", "unavailable", "none_read")]
    for line in lines:
        for word in _FORBIDDEN:
            assert not re.search(rf"\b{re.escape(word)}", line, re.I), (word, line)


# --- through both renderers -----------------------------------------------------------------------------------


def test_report_md_and_the_page_show_the_same_line(tmp_path: Path) -> None:
    sys.path.insert(0, str(HERE))
    from compose_invocations import drive_compose

    fixtures = HERE / "fixtures" / "deck-review"
    stage = tmp_path / "stage"
    shutil.copytree(fixtures, stage)
    recon = json.loads((stage / "reconciliation.json").read_text())
    run_id = recon["metadata"]["run_id"]
    sha = hashlib.sha256((stage / "reconciliation.json").read_bytes()).hexdigest()
    check = _check("checked", checked=3, found=3)
    check["metadata"] = {"run_id": run_id, "reconciliation_sha256": sha}
    (stage / "ocr_check.json").write_text(json.dumps(check))
    work = tmp_path / "work"
    work.mkdir()
    drive_compose("deck-review", stage, work)
    md = (work / "report.md").read_text()
    want = f"{LEAD_2} A separate machine read of those slides found all 3 of them as written."
    assert want in md
    page = work / "page.html"
    proc = subprocess.run(
        [sys.executable, str(SCRIPTS / "visualize.py"), "--dir", str(work), "-o", str(page), "--ungated"],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert f'data-note="machine-read">{want}</p>' in page.read_text()
    for raw in ("$493K", "493"):
        assert raw not in want


def test_no_template_from_step_4_on_names_the_machine_read() -> None:
    """Independence: OCR text never reaches a later sub-agent, so no dispatch from Step 4 on names its files."""
    after = SKILL_MD.read_text(encoding="utf-8").split("### Step 4: Review Each Slide", 1)[1]
    templates = [b for b in re.findall(r"```(?:text)?\n(.*?)```", after, re.S) if "OUTPUT_PATH" in b]
    assert templates, "no dispatch template found after Step 4: the scan reads nothing"
    for block in templates:
        assert "ocr/" not in block and "ocr_check" not in block, block[:200]
    prompt = (SCRIPTS / "dr_dispatch_prompt.py").read_text(encoding="utf-8")
    assert "ocr_check" not in prompt and "/ocr/" not in prompt
