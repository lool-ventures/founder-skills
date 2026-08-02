#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Regression tests for the shared check_handoff.py gate runner.

Covers every typed exit path (0/3/4/5/6) and adversarial file states
(missing, empty, truncated JSON, BOM, huge file), plus the tolerant
receipt extraction (fences, prose preamble, path normalization).

All tests use subprocess to exercise the script exactly as SKILL.md does.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SCRIPTS_DIR = os.path.join(os.path.dirname(SCRIPT_DIR), "scripts")
SCRIPT = os.path.join(SCRIPTS_DIR, "check_handoff.py")


def run_check(
    args: list[str],
    stdin_text: str | None = None,
) -> tuple[int, dict[str, object], str]:
    """Run check_handoff.py; return (exit_code, diagnostic, stderr).

    The script always emits a one-line JSON diagnostic on stdout.
    """
    result = subprocess.run(
        [sys.executable, SCRIPT, *args],
        input=stdin_text,
        capture_output=True,
        text=True,
    )
    diagnostic = json.loads(result.stdout.strip())
    assert isinstance(diagnostic, dict)
    return result.returncode, diagnostic, result.stderr


def receipt_for(path: str, status: str = "complete") -> str:
    return json.dumps({"status": status, "output_path": path})


@pytest.fixture()
def output_file(tmp_path: Path) -> Path:
    path = tmp_path / "step_output.json"
    path.write_text(json.dumps({"items": [1, 2, 3]}), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Exit 0 — ok
# ---------------------------------------------------------------------------


class TestOk:
    def test_valid_file_no_receipt(self, output_file: Path) -> None:
        code, diag, _ = run_check([str(output_file)])
        assert code == 0
        assert diag["code"] == "ok"
        assert diag["output_path"] == str(output_file)
        assert isinstance(diag["bytes"], int) and diag["bytes"] > 0

    def test_valid_file_with_matching_receipt_stdin(self, output_file: Path) -> None:
        code, diag, _ = run_check(
            [str(output_file), "--receipt-json", "-"],
            receipt_for(str(output_file)),
        )
        assert code == 0
        assert diag["code"] == "ok"

    def test_receipt_wrapped_in_json_fence(self, output_file: Path) -> None:
        fenced = f"```json\n{receipt_for(str(output_file))}\n```"
        code, diag, _ = run_check([str(output_file), "--receipt-json", "-"], fenced)
        assert code == 0
        assert diag["code"] == "ok"

    def test_receipt_with_prose_preamble(self, output_file: Path) -> None:
        message = f"Done! Here is the receipt:\n\n{receipt_for(str(output_file))}\n\nLet me know."
        code, diag, _ = run_check([str(output_file), "--receipt-json", "-"], message)
        assert code == 0
        assert diag["code"] == "ok"

    def test_receipt_path_normalization(self, output_file: Path) -> None:
        """A path with redundant separators still matches after normpath."""
        messy = str(output_file.parent) + "//./" + output_file.name
        code, diag, _ = run_check(
            [str(output_file), "--receipt-json", "-"],
            receipt_for(messy),
        )
        assert code == 0
        assert diag["code"] == "ok"

    def test_receipt_from_file(self, output_file: Path, tmp_path: Path) -> None:
        receipt_file = tmp_path / "receipt.txt"
        receipt_file.write_text(receipt_for(str(output_file)), encoding="utf-8")
        code, diag, _ = run_check([str(output_file), "--receipt-json", str(receipt_file)])
        assert code == 0
        assert diag["code"] == "ok"

    def test_bom_file_parses(self, tmp_path: Path) -> None:
        path = tmp_path / "bom_output.json"
        path.write_bytes(b"\xef\xbb\xbf" + json.dumps({"ok": True}).encode("utf-8"))
        code, diag, _ = run_check([str(path)])
        assert code == 0
        assert diag["code"] == "ok"

    def test_huge_file_parses(self, tmp_path: Path) -> None:
        path = tmp_path / "huge_output.json"
        payload = {"rows": [{"i": i, "text": "x" * 200} for i in range(20_000)]}
        path.write_text(json.dumps(payload), encoding="utf-8")
        assert path.stat().st_size > 4_000_000
        code, diag, _ = run_check([str(path)])
        assert code == 0
        assert diag["code"] == "ok"


# ---------------------------------------------------------------------------
# Exit 3 — missing or empty (the fabricated-receipt case)
# ---------------------------------------------------------------------------


class TestMissingOrEmpty:
    def test_missing_file(self, tmp_path: Path) -> None:
        code, diag, _ = run_check([str(tmp_path / "never_written.json")])
        assert code == 3
        assert diag["code"] == "missing_or_empty"
        assert "fabricated" in str(diag["detail"])

    def test_empty_file(self, tmp_path: Path) -> None:
        path = tmp_path / "empty.json"
        path.write_text("", encoding="utf-8")
        code, diag, _ = run_check([str(path)])
        assert code == 3
        assert diag["code"] == "missing_or_empty"

    def test_directory_at_path(self, tmp_path: Path) -> None:
        code, diag, _ = run_check([str(tmp_path)])
        assert code == 3
        assert diag["code"] == "missing_or_empty"


# ---------------------------------------------------------------------------
# Exit 4 — invalid JSON (repairable)
# ---------------------------------------------------------------------------


class TestInvalidJson:
    def test_truncated_json(self, tmp_path: Path) -> None:
        path = tmp_path / "truncated.json"
        path.write_text('{"items": [1, 2', encoding="utf-8")
        code, diag, _ = run_check([str(path)])
        assert code == 4
        assert diag["code"] == "invalid_json"
        assert diag["detail"]  # verbatim parser error for the repair prompt

    def test_not_json_at_all(self, tmp_path: Path) -> None:
        path = tmp_path / "prose.json"
        path.write_text("Here is my analysis:\n\n1. Great TAM\n", encoding="utf-8")
        code, diag, _ = run_check([str(path)])
        assert code == 4
        assert diag["code"] == "invalid_json"


# ---------------------------------------------------------------------------
# Exit 5 — receipt path mismatch (+ --agent-path second namespace)
# ---------------------------------------------------------------------------


class TestPathMismatch:
    def test_receipt_claims_different_path(self, output_file: Path, tmp_path: Path) -> None:
        elsewhere = str(tmp_path / "somewhere_else.json")
        code, diag, _ = run_check(
            [str(output_file), "--receipt-json", "-"],
            receipt_for(elsewhere),
        )
        assert code == 5
        assert diag["code"] == "path_mismatch"
        assert diag["claimed_path"] == elsewhere
        assert diag["output_path"] == str(output_file)

    def test_agent_path_accepts_agent_namespace_echo(self, output_file: Path) -> None:
        """Branch C (Cowork): the receipt echoes the agent-namespace
        OUTPUT_PATH, which differs from the main-thread path. --agent-path
        makes that echo pass."""
        agent_ns = "artifacts/market-sizing/acme/run1/handoff/step_output.json"
        code, diag, _ = run_check(
            [
                str(output_file),
                "--receipt-json",
                "-",
                "--agent-path",
                agent_ns,
            ],
            receipt_for(agent_ns),
        )
        assert code == 0
        assert diag["code"] == "ok"

    def test_agent_path_still_accepts_main_thread_echo(self, output_file: Path) -> None:
        """With --agent-path given, a receipt echoing the main-thread path
        (shared-filesystem hosts) still passes."""
        code, diag, _ = run_check(
            [
                str(output_file),
                "--receipt-json",
                "-",
                "--agent-path",
                "artifacts/x/handoff/step_output.json",
            ],
            receipt_for(str(output_file)),
        )
        assert code == 0
        assert diag["code"] == "ok"

    def test_agent_path_mismatch_still_exits_5(self, output_file: Path) -> None:
        """A receipt path matching NEITHER namespace is still exit 5, and the
        diagnostic carries both expected paths for the repair prompt."""
        agent_ns = "artifacts/x/handoff/step_output.json"
        code, diag, _ = run_check(
            [
                str(output_file),
                "--receipt-json",
                "-",
                "--agent-path",
                agent_ns,
            ],
            receipt_for("somewhere/else.json"),
        )
        assert code == 5
        assert diag["code"] == "path_mismatch"
        assert diag["agent_path"] == agent_ns
        assert diag["output_path"] == str(output_file)


# ---------------------------------------------------------------------------
# Exit 6 — receipt unparseable / malformed
# ---------------------------------------------------------------------------


class TestBadReceipt:
    def test_receipt_no_json_at_all(self, output_file: Path) -> None:
        code, diag, _ = run_check(
            [str(output_file), "--receipt-json", "-"],
            "I wrote the file as instructed. All done!",
        )
        assert code == 6
        assert diag["code"] == "receipt_unparseable"

    def test_receipt_json_without_output_path(self, output_file: Path) -> None:
        code, diag, _ = run_check(
            [str(output_file), "--receipt-json", "-"],
            json.dumps({"status": "complete"}),
        )
        assert code == 6
        assert diag["code"] == "receipt_unparseable"

    def test_receipt_file_unreadable(self, output_file: Path, tmp_path: Path) -> None:
        code, diag, _ = run_check(
            [str(output_file), "--receipt-json", str(tmp_path / "no_receipt.txt")],
        )
        assert code == 6
        assert diag["code"] == "receipt_unreadable"

    def test_gate_order_file_missing_beats_receipt_check(self, tmp_path: Path) -> None:
        """Gates run in order: a missing file exits 3 even when the receipt
        is also garbage."""
        code, diag, _ = run_check(
            [str(tmp_path / "never_written.json"), "--receipt-json", "-"],
            "garbage",
        )
        assert code == 3
        assert diag["code"] == "missing_or_empty"


# ---------------------------------------------------------------------------
# --format=markdown mode (R2 coaching-transport fix)
#
# JSON-mode (default, tested above) must remain byte-identical. Markdown
# mode skips JSON parsing of the body entirely (exit 4 is unreachable) and
# adds a content-shape gate: exit 7 for a receipt-shaped or marker-bearing
# .md body. Existence/empty (3), receipt-path echo (5), receipt-parse (6)
# checks are unchanged.
# ---------------------------------------------------------------------------

MARKER = "<!-- COACHING_INSERTION_POINT_a1b2c3d4 -->"


@pytest.fixture()
def commentary_file(tmp_path: Path) -> Path:
    path = tmp_path / "coaching.md"
    path.write_text(
        "## Strongest aspects\n\nGreat traction and a sharp founder story.\n",
        encoding="utf-8",
    )
    return path


class TestMarkdownFormatOk:
    def test_valid_markdown_no_receipt(self, commentary_file: Path) -> None:
        code, diag, _ = run_check([str(commentary_file), "--format=markdown"])
        assert code == 0
        assert diag["code"] == "ok"
        assert diag["output_path"] == str(commentary_file)

    def test_valid_markdown_with_matching_receipt(self, commentary_file: Path) -> None:
        code, diag, _ = run_check(
            [str(commentary_file), "--format=markdown", "--receipt-json", "-"],
            receipt_for(str(commentary_file)),
        )
        assert code == 0
        assert diag["code"] == "ok"

    def test_commentary_containing_a_brace_is_not_rejected(self, tmp_path: Path) -> None:
        """R1 mitigation: legit commentary that merely quotes JSON (a brace,
        or a whole fenced ```json block) must NOT trip the shape gate."""
        path = tmp_path / "coaching.md"
        path.write_text(
            'The analyst flagged this shape: `{"severity": "high"}` in the '
            "dealbreakers array.\n\n"
            '```json\n{"dimension": "market_size"}\n```\n',
            encoding="utf-8",
        )
        code, diag, _ = run_check([str(path), "--format=markdown"])
        assert code == 0
        assert diag["code"] == "ok"

    def test_commentary_mentioning_marker_word_but_not_exact_marker(self, tmp_path: Path) -> None:
        """Commentary that merely talks ABOUT markers (without the literal
        marker substring) must pass."""
        path = tmp_path / "coaching.md"
        path.write_text(
            "This report has an insertion marker mechanism, unrelated to this text.\n",
            encoding="utf-8",
        )
        code, diag, _ = run_check([str(path), "--format=markdown"])
        assert code == 0
        assert diag["code"] == "ok"


class TestMarkdownFormatMissingOrEmpty:
    def test_missing_file(self, tmp_path: Path) -> None:
        code, diag, _ = run_check([str(tmp_path / "never_written.md"), "--format=markdown"])
        assert code == 3
        assert diag["code"] == "missing_or_empty"

    def test_empty_file(self, tmp_path: Path) -> None:
        path = tmp_path / "empty.md"
        path.write_text("", encoding="utf-8")
        code, diag, _ = run_check([str(path), "--format=markdown"])
        assert code == 3
        assert diag["code"] == "missing_or_empty"

    def test_whitespace_only_file(self, tmp_path: Path) -> None:
        path = tmp_path / "whitespace.md"
        path.write_text("   \n\n\t\n", encoding="utf-8")
        code, diag, _ = run_check([str(path), "--format=markdown"])
        assert code == 3
        assert diag["code"] == "missing_or_empty"


class TestMarkdownFormatShapeGate:
    def test_receipt_shaped_file_output_path_key(self, tmp_path: Path) -> None:
        """The agent wrote its receipt into OUTPUT_PATH by mistake — the
        WHOLE file parses as a dict with an output_path key."""
        path = tmp_path / "coaching.md"
        path.write_text(receipt_for(str(path)), encoding="utf-8")
        code, diag, _ = run_check([str(path), "--format=markdown"])
        assert code == 7
        assert diag["code"] == "shape_invalid"

    def test_receipt_shaped_file_status_key(self, tmp_path: Path) -> None:
        path = tmp_path / "coaching.md"
        path.write_text(json.dumps({"status": "complete"}), encoding="utf-8")
        code, diag, _ = run_check([str(path), "--format=markdown"])
        assert code == 7
        assert diag["code"] == "shape_invalid"

    def test_marker_bearing_file(self, tmp_path: Path) -> None:
        path = tmp_path / "coaching.md"
        path.write_text(
            f"Some commentary...\n\n{MARKER}\n\nmore commentary",
            encoding="utf-8",
        )
        code, diag, _ = run_check([str(path), "--format=markdown", "--marker", MARKER])
        assert code == 7
        assert diag["code"] == "shape_invalid"

    def test_marker_bearing_file_detected_without_explicit_marker_flag(self, tmp_path: Path) -> None:
        """Even without --marker, the literal COACHING_INSERTION_POINT_
        prefix is detected on its own."""
        path = tmp_path / "coaching.md"
        path.write_text(f"commentary\n{MARKER}\nmore", encoding="utf-8")
        code, diag, _ = run_check([str(path), "--format=markdown"])
        assert code == 7
        assert diag["code"] == "shape_invalid"


class TestMarkdownFormatReceiptCheck:
    def test_path_mismatch_still_exits_5(self, commentary_file: Path, tmp_path: Path) -> None:
        elsewhere = str(tmp_path / "somewhere_else.md")
        code, diag, _ = run_check(
            [str(commentary_file), "--format=markdown", "--receipt-json", "-"],
            receipt_for(elsewhere),
        )
        assert code == 5
        assert diag["code"] == "path_mismatch"

    def test_unparseable_receipt_still_exits_6(self, commentary_file: Path) -> None:
        code, diag, _ = run_check(
            [str(commentary_file), "--format=markdown", "--receipt-json", "-"],
            "no json here at all",
        )
        assert code == 6
        assert diag["code"] == "receipt_unparseable"


class TestMarkdownFormatDoesNotChangeJsonMode:
    """Sanity: explicit --format=json behaves exactly like the (default)
    JSON-mode tests above, i.e. it still rejects non-JSON bodies with 4."""

    def test_explicit_json_format_rejects_prose(self, tmp_path: Path) -> None:
        path = tmp_path / "prose.json"
        path.write_text("Here is my analysis:\n\n1. Great TAM\n", encoding="utf-8")
        code, diag, _ = run_check([str(path), "--format=json"])
        assert code == 4
        assert diag["code"] == "invalid_json"


# ---------------------------------------------------------------------------
# Exit 8: path-namespace mismatch (a DOUBLED agent-namespace prefix).
#
# A sub-agent handed a relative OUTPUT_PATH can resolve it against the outputs
# mount instead of the session root, landing at <outputs>/<prefix>/<prefix>/...
# From gate 1 that is indistinguishable from a fabricated receipt — same "no file
# at the expected path" — but the two need OPPOSITE responses: a fabricated
# receipt needs a redo-dispatch, a misresolution needs the dispatch re-issued
# with a corrected prefix. Telling the caller "the receipt may be fabricated"
# about an agent that wrote exactly where it was told sends it down the wrong
# branch, which is what happened live.
#
# The probe is DIAGNOSTIC. It must never license reading the hand-off from
# found_at: exit 0 is what guarantees the file is at the contracted path, and
# every downstream producer pipe addresses $HANDOFF_DIR.
# ---------------------------------------------------------------------------


class TestPathNamespaceMismatch:
    TAIL = "artifacts/fmr-testco/handoff/RID/coaching.md"

    def _layout(self, tmp_path: Path, *, write_doubled: bool) -> tuple[str, str, str]:
        """Reproduce the observed topology: absolute root <outputs>/artifacts/...,
        agent prefix carrying an extra `mnt/outputs/` in front of the same tail."""
        outputs = tmp_path / "outputs"
        agent_path = "mnt/outputs/" + self.TAIL
        expected = outputs / self.TAIL
        doubled = outputs / agent_path
        expected.parent.mkdir(parents=True, exist_ok=True)
        if write_doubled:
            doubled.parent.mkdir(parents=True, exist_ok=True)
            doubled.write_text("## commentary\n", encoding="utf-8")
        return str(expected), agent_path, str(doubled)

    def test_doubled_prefix_reports_exit_8_and_found_at(self, tmp_path: Path) -> None:
        expected, agent_path, doubled = self._layout(tmp_path, write_doubled=True)
        code, diag, _ = run_check([expected, "--format=markdown", "--agent-path", agent_path])
        assert code == 8
        assert diag["code"] == "path_namespace_mismatch"
        assert diag["found_at"] == doubled

    def test_diagnostic_says_not_to_read_from_found_at(self, tmp_path: Path) -> None:
        """The whole point is that recovery is a re-dispatch, not a read from the wrong path."""
        expected, agent_path, _ = self._layout(tmp_path, write_doubled=True)
        _, diag, _ = run_check([expected, "--format=markdown", "--agent-path", agent_path])
        detail = str(diag["detail"]).lower()
        assert "re-dispatch" in detail
        assert "do not read" in detail

    def test_does_not_accuse_a_compliant_agent_of_fabricating(self, tmp_path: Path) -> None:
        expected, agent_path, _ = self._layout(tmp_path, write_doubled=True)
        _, diag, _ = run_check([expected, "--format=markdown", "--agent-path", agent_path])
        detail = str(diag["detail"]).lower()
        assert "fabricat" not in detail.replace("do not treat this as a fabricated", "")

    def test_genuinely_missing_file_still_exits_3(self, tmp_path: Path) -> None:
        """A fabricated receipt must not be reclassified — nothing is anywhere."""
        expected, agent_path, _ = self._layout(tmp_path, write_doubled=False)
        code, diag, _ = run_check([expected, "--format=markdown", "--agent-path", agent_path])
        assert code == 3
        assert diag["code"] == "missing_or_empty"

    def test_inert_without_agent_path(self, tmp_path: Path) -> None:
        """The probe needs the agent namespace to infer anything; absent it, behaviour is unchanged."""
        expected, _, _ = self._layout(tmp_path, write_doubled=True)
        code, diag, _ = run_check([expected, "--format=markdown"])
        assert code == 3
        assert diag["code"] == "missing_or_empty"

    def test_inert_when_agent_path_is_the_whole_tail(self, tmp_path: Path) -> None:
        """Host-loop / CLI: no extra prefix exists to double, so there is nothing to detect."""
        expected, _, _ = self._layout(tmp_path, write_doubled=False)
        code, diag, _ = run_check([expected, "--format=markdown", "--agent-path", self.TAIL])
        assert code == 3
        assert diag["code"] == "missing_or_empty"

    def test_inert_for_an_absolute_agent_path(self, tmp_path: Path) -> None:
        expected, _, _ = self._layout(tmp_path, write_doubled=True)
        code, _, _ = run_check([expected, "--format=markdown", "--agent-path", expected])
        assert code == 3

    def test_happy_path_unaffected(self, tmp_path: Path) -> None:
        expected, agent_path, _ = self._layout(tmp_path, write_doubled=True)
        Path(expected).write_text("## commentary\n", encoding="utf-8")
        code, _, _ = run_check([expected, "--format=markdown", "--agent-path", agent_path])
        assert code == 0
