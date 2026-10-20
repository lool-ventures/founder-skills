"""A usage error that a model hits after a compaction prints the step's own command, as SKILL.md writes it.

Each script's error path keeps argparse's exit code 2 and writes nothing; the `fix:` text it adds is held to
the SKILL.md it quotes, read here by its fenced block, never by a fixed character window.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parent.parent
SKILLS = PLUGIN / "skills"
INSERT = PLUGIN / "scripts" / "insert_coaching.py"
PIPING = ("deck-review", "market-sizing", "ic-sim", "financial-model-review", "competitive-positioning")


def _run(script: Path, args: list[str], cwd: Path, stdin: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script), *args], input=stdin, capture_output=True, text=True, cwd=cwd, timeout=60
    )


def _bash_blocks(skill: str) -> list[list[str]]:
    text = (SKILLS / skill / "SKILL.md").read_text(encoding="utf-8")
    return [b.splitlines() for b in re.findall(r"^```bash\n(.*?)^```", text, flags=re.M | re.S)]


def _fix_lines(stderr: str) -> list[str]:
    lines = stderr.splitlines()
    at = next(i for i, ln in enumerate(lines) if ln.startswith("fix:"))
    return lines[at:]


def _no_files(tmp_path: Path) -> None:
    assert [p for p in tmp_path.rglob("*") if p.is_file()] == []


# --- market-sizing: there is no SENSITIVITY_TEST generator ---


def test_sensitivity_has_no_generator_and_says_where_the_template_is(tmp_path: Path) -> None:
    script = SKILLS / "market-sizing" / "scripts" / "dispatch_prompt.py"
    proc = _run(script, ["sensitivity_test", "--run-id", "r"], tmp_path)
    assert proc.returncode == 2
    fix = _fix_lines(proc.stderr)
    assert len(fix) == 1
    assert fix[0].startswith("fix: SENSITIVITY_TEST has no generator")
    assert not fix[0].startswith("CONTEXT:") and "OUTPUT_PATH:" not in fix[0]
    heading = re.search(r'"([^"]+)" heading', fix[0])
    assert heading
    skill_md = (SKILLS / "market-sizing" / "SKILL.md").read_text(encoding="utf-8")
    assert re.search(rf"^#+ {re.escape(heading.group(1))}$", skill_md, flags=re.M)
    _no_files(tmp_path)


def test_another_bad_context_adds_no_fix(tmp_path: Path) -> None:
    script = SKILLS / "market-sizing" / "scripts" / "dispatch_prompt.py"
    proc = _run(script, ["slide_reviews", "--run-id", "r"], tmp_path)
    assert proc.returncode == 2
    assert "fix:" not in proc.stderr


# --- ic-sim: --fund-mode ---


def _skill_fund_mode_line() -> str:
    for block in _bash_blocks("ic-sim"):
        if any("score_dimensions.py" in ln for ln in block):
            line = next(ln for ln in block if ln.strip().startswith("--fund-mode"))
            return line.strip().removesuffix("\\").strip()
    raise AssertionError("no score_dimensions.py block in ic-sim's SKILL.md")


@pytest.mark.parametrize("args", [["--fund-mode", "host_profile"], ["--fund-mode"]])
def test_fund_mode_error_prints_skill_mds_line(tmp_path: Path, args: list[str]) -> None:
    script = SKILLS / "ic-sim" / "scripts" / "score_dimensions.py"
    proc = _run(script, ["--run-id", "r", *args, "-o", str(tmp_path / "out.json")], tmp_path, stdin="{}")
    assert proc.returncode == 2
    fix = _fix_lines(proc.stderr)
    assert len(fix) == 1
    assert fix[0].endswith(_skill_fund_mode_line())
    assert "generic" in fix[0] and "fund_specific" in fix[0]
    _no_files(tmp_path)


# --- insert_coaching.py: the calling skill's insert form ---


def _skill_insert_lines(skill: str) -> list[str]:
    """The insert command in the skill's first bash block that runs insert_coaching.py: from the piping line (or
    the insert line) through the last continuation line."""
    for block in _bash_blocks(skill):
        at = next(
            (i for i, ln in enumerate(block) if ln.lstrip().startswith("python3") and "insert_coaching.py" in ln),
            None,
        )
        if at is None:
            continue
        start = at - 1 if at and "md_to_commentary.py" in block[at - 1] else at
        end = at
        while block[end].rstrip().endswith("\\"):
            end += 1
        return block[start : end + 1]
    raise AssertionError(f"no insert_coaching.py block in {skill}'s SKILL.md")


@pytest.mark.parametrize("skill", [*PIPING, "cap-table"])
def test_insert_usage_error_prints_the_skills_own_form(tmp_path: Path, skill: str) -> None:
    folder = tmp_path / f"{skill}-acme"
    folder.mkdir()
    proc = _run(INSERT, ["--report", str(folder / "report.md"), "--marker", "m", "--bogus", "1"], tmp_path)
    assert proc.returncode == 2
    fix = _fix_lines(proc.stderr)
    assert fix[0] == f"fix: run the insert as {skill}'s SKILL.md writes it:"
    assert fix[1:] == _skill_insert_lines(skill)
    if skill == "cap-table":
        assert "--commentary-file" in "\n".join(fix) and "md_to_commentary.py" not in "\n".join(fix)
    else:
        assert "md_to_commentary.py" in fix[1]
    assert not any(ln.startswith("CONTEXT:") or "OUTPUT_PATH:" in ln for ln in fix)
    _no_files(tmp_path)


def test_insert_usage_error_with_report_as_equals_form(tmp_path: Path) -> None:
    folder = tmp_path / "cap-table-acme"
    folder.mkdir()
    proc = _run(INSERT, [f"--report={folder / 'report.md'}", "--bogus"], tmp_path)
    assert proc.returncode == 2
    assert _fix_lines(proc.stderr)[0] == "fix: run the insert as cap-table's SKILL.md writes it:"


@pytest.mark.parametrize("args", [["--bogus"], ["--report", "/nowhere/report.md", "--bogus"]])
def test_insert_usage_error_without_a_known_skill_prints_both_forms(tmp_path: Path, args: list[str]) -> None:
    proc = _run(INSERT, args, tmp_path)
    assert proc.returncode == 2
    fix = _fix_lines(proc.stderr)
    assert len(fix) == 3
    assert fix[1].startswith("deck-review, market-sizing, ic-sim, financial-model-review, competitive-positioning:")
    assert "md_to_commentary.py" in fix[1]
    assert fix[2].startswith("cap-table:") and "--commentary-file" in fix[2]
    _no_files(tmp_path)
