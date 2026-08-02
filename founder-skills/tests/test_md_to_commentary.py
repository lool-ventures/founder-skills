#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Regression tests for md_to_commentary.py (R2 coaching-transport adapter).

The adapter reads a raw markdown file (arg or stdin) and prints
`{"commentary_markdown": "<verbatim text>"}` to stdout. json.dumps does the
escaping, so the output is correct-by-construction; these tests pin an
EXACT round-trip (no trimming, no reflowing) across adversarial content:
literal newlines, quotes, backslashes, and an embedded fenced JSON block.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SCRIPTS_DIR = os.path.join(os.path.dirname(SCRIPT_DIR), "scripts")
SCRIPT = os.path.join(SCRIPTS_DIR, "md_to_commentary.py")

ADVERSARIAL_MD = (
    "## Strongest aspects\n\n"
    'The founder\'s "unit economics" story is strong — payback < 6mo.\n\n'
    "A backslash test: C:\\Users\\founder\\deck.pptx and a \\n literal-looking "
    "sequence that must NOT be interpreted as an escape.\n\n"
    "Here's the JSON shape the analyst quoted verbatim:\n\n"
    "```json\n"
    '{"dimension": "market_size", "severity": "high"}\n'
    "```\n\n"
    'Multiple\n\n\nblank lines above, and a trailing quote " at end of line.\n'
)


def run_adapter(args: list[str], stdin_text: str | None = None) -> tuple[int, str, str]:
    result = subprocess.run(
        [sys.executable, SCRIPT, *args],
        input=stdin_text,
        capture_output=True,
        text=True,
    )
    return result.returncode, result.stdout, result.stderr


class TestRoundTrip:
    def test_arg_mode_round_trips_exactly(self, tmp_path: Path) -> None:
        md_file = tmp_path / "coaching.md"
        md_file.write_text(ADVERSARIAL_MD, encoding="utf-8")

        code, stdout, _ = run_adapter([str(md_file)])
        assert code == 0

        parsed = json.loads(stdout)
        assert parsed == {"commentary_markdown": ADVERSARIAL_MD}
        assert parsed["commentary_markdown"] == ADVERSARIAL_MD  # exact, no trim/reflow

    def test_stdin_mode_round_trips_exactly(self) -> None:
        code, stdout, _ = run_adapter([], stdin_text=ADVERSARIAL_MD)
        assert code == 0
        parsed = json.loads(stdout)
        assert parsed["commentary_markdown"] == ADVERSARIAL_MD

    def test_stdin_and_arg_modes_are_equivalent(self, tmp_path: Path) -> None:
        md_file = tmp_path / "coaching.md"
        md_file.write_text(ADVERSARIAL_MD, encoding="utf-8")

        code_arg, stdout_arg, _ = run_adapter([str(md_file)])
        code_stdin, stdout_stdin, _ = run_adapter([], stdin_text=ADVERSARIAL_MD)

        assert code_arg == code_stdin == 0
        assert json.loads(stdout_arg) == json.loads(stdout_stdin)

    def test_embedded_json_fence_and_brace_are_not_mangled(self, tmp_path: Path) -> None:
        """A file containing '{' or a fenced ```json block must pass through
        untouched — the adapter must not try to parse or strip it."""
        md_file = tmp_path / "coaching.md"
        content = 'Quoting the payload: ```json\n{"a": 1}\n```\nand a bare { too.'
        md_file.write_text(content, encoding="utf-8")

        code, stdout, _ = run_adapter([str(md_file)])
        assert code == 0
        parsed = json.loads(stdout)
        assert parsed["commentary_markdown"] == content

    def test_output_is_single_line_valid_json(self, tmp_path: Path) -> None:
        md_file = tmp_path / "coaching.md"
        md_file.write_text(ADVERSARIAL_MD, encoding="utf-8")
        code, stdout, _ = run_adapter([str(md_file)])
        assert code == 0
        # Exactly one JSON object printed (trailing newline aside).
        lines = [line for line in stdout.splitlines() if line.strip()]
        assert len(lines) == 1
        json.loads(lines[0])

    def test_empty_file_round_trips_to_empty_string(self, tmp_path: Path) -> None:
        md_file = tmp_path / "empty.md"
        md_file.write_text("", encoding="utf-8")
        code, stdout, _ = run_adapter([str(md_file)])
        assert code == 0
        assert json.loads(stdout) == {"commentary_markdown": ""}

    def test_missing_file_is_an_error(self, tmp_path: Path) -> None:
        code, _stdout, stderr = run_adapter([str(tmp_path / "never_written.md")])
        assert code != 0
        assert stderr.strip()


class TestPrettyFlag:
    """Repo-wide script convention (CLAUDE.md): every script supports --pretty
    for human-readable output. md_to_commentary.py's default output must stay
    compact (single line, no added whitespace) since it's a machine pipe
    stage feeding straight into insert_coaching.py; --pretty is opt-in."""

    def test_default_output_is_compact_single_line(self, tmp_path: Path) -> None:
        md_file = tmp_path / "coaching.md"
        md_file.write_text(ADVERSARIAL_MD, encoding="utf-8")
        code, stdout, _ = run_adapter([str(md_file)])
        assert code == 0
        assert "\n  " not in stdout  # no indentation added
        assert json.loads(stdout.strip()) == {"commentary_markdown": ADVERSARIAL_MD}

    def test_pretty_flag_indents_and_preserves_content(self, tmp_path: Path) -> None:
        md_file = tmp_path / "coaching.md"
        md_file.write_text(ADVERSARIAL_MD, encoding="utf-8")
        code, stdout, _ = run_adapter([str(md_file), "--pretty"])
        assert code == 0
        assert stdout.startswith("{\n")
        assert json.loads(stdout)["commentary_markdown"] == ADVERSARIAL_MD

    def test_pretty_flag_works_with_stdin(self) -> None:
        code, stdout, _ = run_adapter(["--pretty"], stdin_text=ADVERSARIAL_MD)
        assert code == 0
        assert stdout.startswith("{\n")
        assert json.loads(stdout)["commentary_markdown"] == ADVERSARIAL_MD
