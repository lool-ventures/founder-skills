#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Regression tests for the shared insert_coaching.py script.

Covers the full 6-state idempotency matrix, run_id parity pass/fail,
marker-collision-with-body-content, idempotent re-run, the single-pass
write-back guarantee (report untouched on any blocked exit), the
truncated-report diagnostic, and adversarial commentary content.

All tests use subprocess to exercise the script exactly as SKILL.md does.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import cast

import pytest

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SCRIPTS_DIR = os.path.join(os.path.dirname(SCRIPT_DIR), "scripts")
SCRIPT = os.path.join(SCRIPTS_DIR, "insert_coaching.py")

MARKER = "<!-- COACHING_INSERTION_POINT_a1b2c3d4 -->"
HEADING = "## Coaching Commentary"


def run_insert(
    args: list[str],
    stdin_text: str | None = None,
) -> tuple[int, dict[str, object] | None, str]:
    """Run insert_coaching.py; return (exit_code, parsed_stdout, stderr)."""
    result = subprocess.run(
        [sys.executable, SCRIPT, *args],
        input=stdin_text,
        capture_output=True,
        text=True,
    )
    parsed: dict[str, object] | None = None
    stdout = result.stdout.strip()
    if stdout:
        try:
            loaded = json.loads(stdout)
            if isinstance(loaded, dict):
                parsed = loaded
        except json.JSONDecodeError:
            parsed = None
    return result.returncode, parsed, result.stderr


def make_report(tmp_path: Path, body: str) -> Path:
    report = tmp_path / "report.md"
    report.write_text(body, encoding="utf-8")
    return report


def make_artifact(tmp_path: Path, name: str, run_id: str | None) -> Path:
    path = tmp_path / name
    data: dict[str, object] = {"payload": True}
    if run_id is not None:
        data["metadata"] = {"run_id": run_id}
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def commentary_stdin(text: str = "Solid TAM story. Fix the SAM filter.") -> str:
    return json.dumps({"commentary_markdown": text})


BASE_REPORT = f"# Report\n\nBody text.\n\n{MARKER}\n\n---\nFooter.\n"


# ---------------------------------------------------------------------------
# The 6-state idempotency matrix
# ---------------------------------------------------------------------------


class TestIdempotencyMatrix:
    def test_state_0_1_inserts(self, tmp_path: Path) -> None:
        report = make_report(tmp_path, BASE_REPORT)
        code, out, _ = run_insert(
            ["--report", str(report), "--marker", MARKER],
            commentary_stdin(),
        )
        assert code == 0
        assert out is not None and out["status"] == "inserted"
        text = report.read_text(encoding="utf-8")
        assert text.count(HEADING) == 1
        assert MARKER not in text
        assert "Solid TAM story." in text

    def test_state_1_0_noop_success(self, tmp_path: Path) -> None:
        """Already inserted (resume case): no-op success, content unchanged,
        and no commentary input is required at all."""
        body = BASE_REPORT.replace(MARKER, f"{HEADING}\n\nExisting commentary.")
        report = make_report(tmp_path, body)
        code, out, _ = run_insert(["--report", str(report), "--marker", MARKER])
        assert code == 0
        assert out is not None and out["status"] == "already_inserted"
        assert report.read_text(encoding="utf-8") == body

    def test_state_0_0_blocked_with_truncation_diagnostic(self, tmp_path: Path) -> None:
        """(0,0) can be 'compose never emitted the marker' OR a crash-mid-write
        truncated report; the diagnostic must mention the compose re-run
        recovery, not just blame compose."""
        report = make_report(tmp_path, "# Report\n\nNo marker here.\n")
        code, out, stderr = run_insert(
            ["--report", str(report), "--marker", MARKER],
            commentary_stdin(),
        )
        assert code == 1
        assert out is not None and out["status"] == "blocked"
        reason = str(out["reason"])
        assert "compose did not emit insertion marker" in reason
        assert "compose_report.py --write-md" in reason
        assert "BLOCKED" in stderr

    def test_state_1_1_partial_state_corruption(self, tmp_path: Path) -> None:
        body = BASE_REPORT + f"\n{HEADING}\n\nOrphan commentary.\n"
        report = make_report(tmp_path, body)
        code, out, _ = run_insert(
            ["--report", str(report), "--marker", MARKER],
            commentary_stdin(),
        )
        assert code == 1
        assert out is not None
        assert "partial-state corruption" in str(out["reason"])
        assert report.read_text(encoding="utf-8") == body

    def test_state_2_star_duplicate_commentary(self, tmp_path: Path) -> None:
        body = BASE_REPORT + f"\n{HEADING}\n\nOne.\n\n{HEADING}\n\nTwo.\n"
        report = make_report(tmp_path, body)
        code, out, _ = run_insert(
            ["--report", str(report), "--marker", MARKER],
            commentary_stdin(),
        )
        assert code == 1
        assert out is not None
        assert "duplicate commentary detected (count=2)" in str(out["reason"])

    def test_state_0_2_multiple_markers(self, tmp_path: Path) -> None:
        report = make_report(tmp_path, BASE_REPORT + f"\n{MARKER}\n")
        code, out, _ = run_insert(
            ["--report", str(report), "--marker", MARKER],
            commentary_stdin(),
        )
        assert code == 1
        assert out is not None
        assert "compose emitted multiple markers (count=2)" in str(out["reason"])
        assert "compose bug" in str(out["reason"])


# ---------------------------------------------------------------------------
# run_id parity
# ---------------------------------------------------------------------------


class TestRunIdParity:
    def test_parity_pass(self, tmp_path: Path) -> None:
        report = make_report(tmp_path, BASE_REPORT)
        a1 = make_artifact(tmp_path, "inputs.json", "20260704T120000Z")
        a2 = make_artifact(tmp_path, "sizing.json", "20260704T120000Z")
        code, out, _ = run_insert(
            [
                "--report",
                str(report),
                "--marker",
                MARKER,
                "--verify-artifact",
                str(a1),
                "--verify-artifact",
                str(a2),
            ],
            commentary_stdin(),
        )
        assert code == 0
        assert out is not None
        assert out["run_id"] == "20260704T120000Z"
        assert out["verified_artifacts"] == 2

    def test_parity_mismatch_blocks_and_leaves_report_untouched(self, tmp_path: Path) -> None:
        report = make_report(tmp_path, BASE_REPORT)
        a1 = make_artifact(tmp_path, "inputs.json", "20260704T120000Z")
        a2 = make_artifact(tmp_path, "sizing.json", "20260704T999999Z")
        code, out, _ = run_insert(
            [
                "--report",
                str(report),
                "--marker",
                MARKER,
                "--verify-artifact",
                str(a1),
                "--verify-artifact",
                str(a2),
            ],
            commentary_stdin(),
        )
        assert code == 1
        assert out is not None
        assert "run_id mismatch" in str(out["reason"])
        # Parity runs BEFORE the write: report must be untouched.
        assert report.read_text(encoding="utf-8") == BASE_REPORT

    def test_missing_artifact_blocks(self, tmp_path: Path) -> None:
        report = make_report(tmp_path, BASE_REPORT)
        code, out, _ = run_insert(
            [
                "--report",
                str(report),
                "--marker",
                MARKER,
                "--verify-artifact",
                str(tmp_path / "sizing.json"),
            ],
            commentary_stdin(),
        )
        assert code == 1
        assert out is not None
        assert "sizing.json not found at" in str(out["reason"])

    def test_artifact_without_run_id_blocks(self, tmp_path: Path) -> None:
        report = make_report(tmp_path, BASE_REPORT)
        art = make_artifact(tmp_path, "checklist.json", None)
        code, out, _ = run_insert(
            [
                "--report",
                str(report),
                "--marker",
                MARKER,
                "--verify-artifact",
                str(art),
            ],
            commentary_stdin(),
        )
        assert code == 1
        assert out is not None
        assert "has no metadata.run_id" in str(out["reason"])

    def test_parity_also_checked_on_already_inserted(self, tmp_path: Path) -> None:
        """The resume path still verifies artifacts before declaring success."""
        body = BASE_REPORT.replace(MARKER, f"{HEADING}\n\nExisting.")
        report = make_report(tmp_path, body)
        a1 = make_artifact(tmp_path, "inputs.json", "A")
        a2 = make_artifact(tmp_path, "sizing.json", "B")
        code, out, _ = run_insert(
            [
                "--report",
                str(report),
                "--marker",
                MARKER,
                "--verify-artifact",
                str(a1),
                "--verify-artifact",
                str(a2),
            ],
        )
        assert code == 1
        assert out is not None
        assert "run_id mismatch" in str(out["reason"])


# ---------------------------------------------------------------------------
# Marker exactness + adversarial content
# ---------------------------------------------------------------------------


class TestMarkerAndAdversarialContent:
    def test_body_containing_marker_prefix_does_not_collide(self, tmp_path: Path) -> None:
        """Body text containing the marker PREFIX substring must not confuse
        the exact-string count (the reason the uuid marker exists)."""
        body = f"# Report\n\nThe template uses `<!-- COACHING_INSERTION_POINT_` as a prefix.\n\n{MARKER}\n\n---\n"
        report = make_report(tmp_path, body)
        code, out, _ = run_insert(
            ["--report", str(report), "--marker", MARKER],
            commentary_stdin(),
        )
        assert code == 0
        assert out is not None and out["status"] == "inserted"
        text = report.read_text(encoding="utf-8")
        assert MARKER not in text
        assert "<!-- COACHING_INSERTION_POINT_` as a prefix" in text

    def test_adversarial_commentary_fences_quotes_newlines(self, tmp_path: Path) -> None:
        report = make_report(tmp_path, BASE_REPORT)
        adversarial = (
            'Fix the "SAM" filter.\n\n```json\n{"tam": 1000000}\n```\n\n'
            "Line with 'single quotes' and a | pipe and $VAR and \\ backslash."
        )
        code, out, _ = run_insert(
            ["--report", str(report), "--marker", MARKER],
            json.dumps({"commentary_markdown": adversarial}),
        )
        assert code == 0
        assert out is not None and out["status"] == "inserted"
        text = report.read_text(encoding="utf-8")
        assert '```json\n{"tam": 1000000}\n```' in text
        assert "$VAR and \\ backslash" in text

    def test_commentary_containing_heading_fails_self_check_untouched(self, tmp_path: Path) -> None:
        """Commentary that itself contains the heading would produce a
        duplicate; the post-insert self-check must block BEFORE writing."""
        report = make_report(tmp_path, BASE_REPORT)
        code, out, _ = run_insert(
            ["--report", str(report), "--marker", MARKER],
            json.dumps({"commentary_markdown": f"Nice.\n\n{HEADING}\n\nSneaky."}),
        )
        assert code == 1
        assert out is not None
        assert "post-insert self-check failed" in str(out["reason"])
        assert "NOT modified" in str(out["reason"])
        assert report.read_text(encoding="utf-8") == BASE_REPORT

    def test_idempotent_rerun(self, tmp_path: Path) -> None:
        report = make_report(tmp_path, BASE_REPORT)
        code1, out1, _ = run_insert(
            ["--report", str(report), "--marker", MARKER],
            commentary_stdin(),
        )
        assert code1 == 0 and out1 is not None and out1["status"] == "inserted"
        after_first = report.read_text(encoding="utf-8")
        code2, out2, _ = run_insert(
            ["--report", str(report), "--marker", MARKER],
            commentary_stdin(),
        )
        assert code2 == 0 and out2 is not None
        assert out2["status"] == "already_inserted"
        assert report.read_text(encoding="utf-8") == after_first


# ---------------------------------------------------------------------------
# Input handling + CLI conventions
# ---------------------------------------------------------------------------


class TestInputAndCliConventions:
    def test_commentary_file_flag(self, tmp_path: Path) -> None:
        report = make_report(tmp_path, BASE_REPORT)
        staged = tmp_path / "commentary.json"
        staged.write_text(commentary_stdin("From a staged file."), encoding="utf-8")
        code, out, _ = run_insert(
            [
                "--report",
                str(report),
                "--marker",
                MARKER,
                "--commentary-file",
                str(staged),
            ],
        )
        assert code == 0
        assert out is not None and out["status"] == "inserted"
        assert "From a staged file." in report.read_text(encoding="utf-8")

    @pytest.mark.parametrize(
        "stdin_text",
        ["", "not json", "{}", json.dumps({"commentary_markdown": "   "})],
        ids=["empty", "not-json", "missing-key", "whitespace-only"],
    )
    def test_bad_commentary_input_blocks(self, tmp_path: Path, stdin_text: str) -> None:
        report = make_report(tmp_path, BASE_REPORT)
        code, out, _ = run_insert(
            ["--report", str(report), "--marker", MARKER],
            stdin_text,
        )
        assert code == 1
        assert out is not None and out["status"] == "blocked"
        assert report.read_text(encoding="utf-8") == BASE_REPORT

    def test_missing_report_blocks(self, tmp_path: Path) -> None:
        code, out, _ = run_insert(
            ["--report", str(tmp_path / "nope.md"), "--marker", MARKER],
            commentary_stdin(),
        )
        assert code == 1
        assert out is not None
        assert "report.md not readable" in str(out["reason"])

    def test_output_flag_writes_receipt_file(self, tmp_path: Path) -> None:
        report = make_report(tmp_path, BASE_REPORT)
        receipt_path = tmp_path / "receipt.json"
        code, out, _ = run_insert(
            [
                "--report",
                str(report),
                "--marker",
                MARKER,
                "-o",
                str(receipt_path),
            ],
            commentary_stdin(),
        )
        assert code == 0
        # stdout carries the write confirmation; the receipt lands in the file.
        assert out is not None and out["written"] == str(receipt_path)
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        assert receipt["status"] == "inserted"

    def test_pretty_flag(self, tmp_path: Path) -> None:
        report = make_report(tmp_path, BASE_REPORT)
        result = subprocess.run(
            [
                sys.executable,
                SCRIPT,
                "--report",
                str(report),
                "--marker",
                MARKER,
                "--pretty",
            ],
            input=commentary_stdin(),
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert result.stdout.startswith("{\n")


# ---------------------------------------------------------------------------
# R2 coaching-transport fix: md_to_commentary.py | insert_coaching.py
#
# Proves this script's logic is untouched -- the new adapter is a pure
# transport wrapper feeding the SAME stdin contract insert_coaching.py
# already reads. The sub-agent's raw markdown never touches insert_coaching
# directly; md_to_commentary.py sits in between.
# ---------------------------------------------------------------------------

MD_TO_COMMENTARY_SCRIPT = os.path.join(SCRIPTS_DIR, "md_to_commentary.py")


class TestMdToCommentaryComposition:
    def test_pipe_inserts_raw_markdown_exactly(self, tmp_path: Path) -> None:
        report = make_report(tmp_path, BASE_REPORT)
        coaching_md = tmp_path / "coaching.md"
        raw_text = (
            "## Strongest aspects\n\n"
            'The founder\'s "unit economics" story is strong.\n\n'
            "- prep item one\n- prep item two\n"
        )
        coaching_md.write_text(raw_text, encoding="utf-8")

        adapter = subprocess.run(
            [sys.executable, MD_TO_COMMENTARY_SCRIPT, str(coaching_md)],
            capture_output=True,
            text=True,
        )
        assert adapter.returncode == 0

        inserter = subprocess.run(
            [
                sys.executable,
                SCRIPT,
                "--report",
                str(report),
                "--marker",
                MARKER,
            ],
            input=adapter.stdout,
            capture_output=True,
            text=True,
        )
        assert inserter.returncode == 0
        result_payload = json.loads(inserter.stdout)
        assert result_payload["status"] == "inserted"

        new_report = report.read_text(encoding="utf-8")
        assert MARKER not in new_report
        assert HEADING in new_report
        assert raw_text.strip() in new_report


# ---------------------------------------------------------------------------
# Founder-text scan over the coaching commentary
# ---------------------------------------------------------------------------


def test_receipt_reports_internal_tokens_in_commentary(tmp_path: Path) -> None:
    """The compose-time scan cannot see the commentary — compose emits a marker, this fills it in.

    Without a check here the Coaching Commentary is the one founder-visible section of the report that
    no scan covers, and it is model-authored prose, so it is the likeliest place for a token to appear.
    """
    marker = "<!-- COACHING_INSERTION_POINT_deadbeef -->"
    report = tmp_path / "report.md"
    report.write_text(f"# R\n\nbody\n\n{marker}\n", encoding="utf-8")
    payload = tmp_path / "c.json"
    payload.write_text(
        json.dumps({"commentary_markdown": "Your moat_count is low and model_data.json was thin."}),
        encoding="utf-8",
    )
    rc, receipt, err = run_insert(["--report", str(report), "--marker", marker, "--commentary-file", str(payload)])
    assert rc == 0, err
    assert receipt is not None
    assert receipt["status"] == "inserted"
    findings = cast(dict[str, object], receipt["founder_text_findings"])
    assert findings["enums"] == ["moat_count"]
    assert findings["filenames"] == ["model_data.json"]


def test_commentary_is_inserted_verbatim_despite_the_scan(tmp_path: Path) -> None:
    """The scan REPORTS; it must not rewrite. Commentary may quote the founder's own field names."""
    marker = "<!-- COACHING_INSERTION_POINT_cafe1234 -->"
    report = tmp_path / "report.md"
    report.write_text(f"# R\n\nbody\n\n{marker}\n", encoding="utf-8")
    payload = tmp_path / "c.json"
    payload.write_text(json.dumps({"commentary_markdown": "Your moat_count is low."}), encoding="utf-8")
    rc, _receipt, err = run_insert(["--report", str(report), "--marker", marker, "--commentary-file", str(payload)])
    assert rc == 0, err
    assert "Your moat_count is low." in report.read_text(encoding="utf-8")


def test_clean_commentary_reports_no_findings(tmp_path: Path) -> None:
    marker = "<!-- COACHING_INSERTION_POINT_0badcafe -->"
    report = tmp_path / "report.md"
    report.write_text(f"# R\n\nbody\n\n{marker}\n", encoding="utf-8")
    payload = tmp_path / "c.json"
    payload.write_text(
        json.dumps({"commentary_markdown": "Your defensibility story needs a second proof point."}),
        encoding="utf-8",
    )
    rc, receipt, err = run_insert(["--report", str(report), "--marker", marker, "--commentary-file", str(payload)])
    assert rc == 0, err
    assert receipt is not None and receipt["founder_text_findings"] == {"enums": [], "filenames": []}


# ---------------------------------------------------------------------------
# A9 — keeping report.json's `report_markdown` in step with report.md.
#
# Measured on a live run: the two diverged by 5,592 characters. `compose_report.py`
# writes both at Step 6 with the coaching marker in place; this script then wrote
# back to report.md ONLY, so on every run report.json shipped WITHOUT the coaching
# commentary and WITH a raw uuid-bearing `COACHING_INSERTION_POINT_<hex>` token --
# exactly the class `_founder_text.py` and `leak_scan.py` exist to catch. The
# compose-time scan cannot see it, because at compose time the marker is legitimate.
#
# WHY SYNC RATHER THAN DROP THE KEY. The obvious fix -- stop serializing
# `report_markdown` -- was measured to be a ~200-site test-architecture migration:
# every skill's suite inspects report CONTENT by loading report.json and reading that
# key (39 sites in market-sizing alone). Syncing is one edit in one shared script,
# touches no test, and leaves report.json CORRECT rather than silent.
#
# The cost of syncing is that two copies still exist and can drift again. That is
# what these tests are for.
# ---------------------------------------------------------------------------


def make_report_json(tmp_path: Path, markdown: str, run_id: str | None = "r1") -> Path:
    """report.json as compose writes it: report_markdown plus a coaching_payload."""
    path = tmp_path / "report.json"
    data: dict[str, object] = {
        "report_markdown": markdown,
        "coaching_payload": {"schema_version": "v1", "insertion_marker": MARKER},
        "validation": {"status": "valid", "warnings": []},
    }
    if run_id is not None:
        data["metadata"] = {"run_id": run_id}
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


def test_report_json_is_synced_with_the_inserted_markdown(tmp_path: Path) -> None:
    """The defect: report.json kept the marker and lost the commentary."""
    report = make_report(tmp_path, BASE_REPORT)
    rjson = make_report_json(tmp_path, BASE_REPORT)
    code, out, err = run_insert(
        ["--report", str(report), "--report-json", str(rjson), "--marker", MARKER],
        commentary_stdin(),
    )
    assert code == 0, err
    assert out is not None and out["status"] == "inserted"

    md = report.read_text(encoding="utf-8")
    data = json.loads(rjson.read_text(encoding="utf-8"))
    embedded = data["report_markdown"]

    assert MARKER not in embedded, (
        "report.json still carries the raw uuid insertion marker — a founder-facing internal "
        "token in a delivered artifact, and the compose-time scan cannot see it"
    )
    assert HEADING in embedded, "report.json shipped without the coaching commentary"
    assert embedded == md, (
        "report.json's report_markdown must be byte-identical to report.md — they are two "
        "copies of one document, and a live run had them 5,592 characters apart"
    )
    # Everything else in the file must survive untouched.
    assert data["coaching_payload"]["schema_version"] == "v1"
    assert data["validation"]["status"] == "valid"
    assert data["metadata"]["run_id"] == "r1"


def test_report_json_sync_is_optional(tmp_path: Path) -> None:
    """The flag is additive: every existing caller omits it and must keep working."""
    report = make_report(tmp_path, BASE_REPORT)
    code, out, err = run_insert(["--report", str(report), "--marker", MARKER], commentary_stdin())
    assert code == 0, err
    assert out is not None and out["status"] == "inserted"
    assert HEADING in report.read_text(encoding="utf-8")


def test_already_inserted_resume_also_syncs_report_json(tmp_path: Path) -> None:
    """A resume must not leave the JSON stale.

    `already_inserted` returns success WITHOUT rewriting report.md, so a naive
    implementation that syncs only on the write path leaves report.json holding the
    marker forever — the exact defect, surviving the fix, on the one path most likely
    to be hit after an interrupted run.
    """
    inserted_md = BASE_REPORT.replace(MARKER, f"{HEADING}\n\nSolid TAM story.")
    report = make_report(tmp_path, inserted_md)
    rjson = make_report_json(tmp_path, BASE_REPORT)  # JSON still pre-insertion
    code, out, err = run_insert(
        ["--report", str(report), "--report-json", str(rjson), "--marker", MARKER],
        commentary_stdin(),
    )
    assert code == 0, err
    assert out is not None and out["status"] == "already_inserted"
    embedded = json.loads(rjson.read_text(encoding="utf-8"))["report_markdown"]
    assert MARKER not in embedded and HEADING in embedded, (
        "a resume left report.json holding the marker — sync must cover the "
        "already_inserted path, not only the write path"
    )


def test_a_missing_report_json_fails_BEFORE_report_md_is_touched(tmp_path: Path) -> None:
    """Named-but-absent is fatal — and it must fail before any write, not during.

    TIGHTENED after this test passed its own mutation. The first version asserted only a
    non-zero exit and an error mentioning report-json. Both hold WITHOUT the precheck,
    because `_sync_report_json` raises its own not-readable error afterwards — so deleting
    the precheck left the test green.

    What the precheck actually buys is that the pair is never left HALF-UPDATED: without it,
    report.md is rewritten first and the sync fails second, producing exactly the divergence
    this flag exists to close, reintroduced by the fix's own error path. So assert the
    markdown is untouched.
    """
    report = make_report(tmp_path, BASE_REPORT)
    code, _, err = run_insert(
        ["--report", str(report), "--report-json", str(tmp_path / "nope.json"), "--marker", MARKER],
        commentary_stdin(),
    )
    assert code != 0
    assert "report-json" in err.lower() or "report.json" in err.lower(), err
    assert report.read_text(encoding="utf-8") == BASE_REPORT, (
        "report.md was modified before the report.json failure was detected — that is the "
        "half-updated pair the precheck exists to prevent"
    )


# ---------------------------------------------------------------------------
# One footer. The report already ends with the "Generated by founder skills" line compose writes after
# the marker; a coach that ends its commentary with the same line printed it twice.
# ---------------------------------------------------------------------------

_FOOTER = (
    "*Generated by [founder skills](https://github.com/lool-ventures/founder-skills) by "
    "[lool ventures](https://lool.vc) — Financial Model Review Agent*"
)
_REPORT_WITH_FOOTER = f"# Report\n\nBody text.\n\n{MARKER}\n\n---\n{_FOOTER}\n"


def _insert(tmp_path: Path, report_body: str, commentary: str) -> tuple[int, dict[str, object] | None, str]:
    report = make_report(tmp_path, report_body)
    rc, out, err = run_insert(["--report", str(report), "--marker", MARKER], stdin_text=commentary_stdin(commentary))
    return rc, out, report.read_text(encoding="utf-8")


def test_a_commentary_footer_is_dropped_when_the_report_already_ends_with_one(tmp_path: Path) -> None:
    rc, out, text = _insert(tmp_path, _REPORT_WITH_FOOTER, f"Fix the burn.\n\n---\n{_FOOTER}\n")
    assert rc == 0, out
    assert text.count("*Generated by [founder skills]") == 1, text
    assert "Fix the burn." in text
    assert text.index("Fix the burn.") < text.index(_FOOTER), "the report's own footer stays last"
    assert out is not None and out.get("footer_dropped") is True


def test_a_bare_footer_line_without_a_rule_is_dropped_too(tmp_path: Path) -> None:
    rc, _, text = _insert(tmp_path, _REPORT_WITH_FOOTER, f"Fix the burn.\n{_FOOTER}")
    assert rc == 0
    assert text.count("*Generated by [founder skills]") == 1, text


def test_a_commentary_footer_is_kept_when_the_report_has_none(tmp_path: Path) -> None:
    """Only a duplicate is dropped: a report without its own footer keeps the coach's."""
    rc, out, text = _insert(tmp_path, BASE_REPORT, f"Fix the burn.\n\n---\n{_FOOTER}\n")
    assert rc == 0
    assert text.count("*Generated by [founder skills]") == 1, text
    assert out is not None and out.get("footer_dropped") is False


def test_a_footer_mentioned_mid_commentary_is_not_touched(tmp_path: Path) -> None:
    """Only a TRAILING footer line is the duplicate; the coach quoting it elsewhere is its own text."""
    body = f"Note: {_FOOTER} appears at the end.\n\nFix the burn."
    rc, _, text = _insert(tmp_path, _REPORT_WITH_FOOTER, body)
    assert rc == 0
    assert f"Note: {_FOOTER} appears at the end." in text


# ---------------------------------------------------------------------------
# A report can declare that its commentary needs a passing check record
# ---------------------------------------------------------------------------
# cap-table's compose writes a declaration beside the marker: the commentary must come with the record of a check
# that passed it, for this run, over this exact text. A step the model skips cannot satisfy it, because the
# requirement lives in the report, not in a flag the model has to remember. A report with no declaration is
# handled exactly as before -- every test above runs one.

DECLARATION = "<!-- COACHING_REQUIRES_CHECK_RECORD run_id=run-7 -->"
DECLARED_REPORT = f"# Report\n\nBody text.\n\n{DECLARATION}\n{MARKER}\n\n---\nFooter.\n"
TEXT = "The new money is the largest driver."


def _record(tmp_path: Path, **over: object) -> Path:
    import hashlib

    rec: dict[str, object] = {
        "run_id": "run-7",
        "action": "clean",
        "checked_commentary_sha256": hashlib.sha256(TEXT.encode("utf-8")).hexdigest(),
    }
    rec.update(over)
    path = tmp_path / "coaching.md.pool-check.json"
    path.write_text(json.dumps(rec), encoding="utf-8")
    return path


def _envelope(record: Path | None, text: str = TEXT) -> str:
    env: dict[str, object] = {"commentary_markdown": text}
    if record is not None:
        env["check_record"] = str(record)
    return json.dumps(env)


def test_a_declared_report_refuses_commentary_with_no_check_record(tmp_path: Path) -> None:
    report = make_report(tmp_path, DECLARED_REPORT)
    code, out, err = run_insert(["--report", str(report), "--marker", MARKER], stdin_text=_envelope(None))
    assert code == 1 and out is not None and out["status"] == "blocked", (code, out)
    assert "check record" in str(out["reason"]) and err.strip()
    assert report.read_text(encoding="utf-8") == DECLARED_REPORT


@pytest.mark.parametrize(
    ("case", "over", "text"),
    [
        ("findings still open", {"action": "findings"}, TEXT),
        ("another run", {"run_id": "run-8"}, TEXT),
        ("different text", {}, "Something the check never saw."),
        ("no action", {"action": None}, TEXT),
    ],
)
def test_a_declared_report_refuses_a_record_that_does_not_pass_this_text(
    tmp_path: Path, case: str, over: dict[str, object], text: str
) -> None:
    report = make_report(tmp_path, DECLARED_REPORT)
    code, out, _err = run_insert(
        ["--report", str(report), "--marker", MARKER], stdin_text=_envelope(_record(tmp_path, **over), text)
    )
    assert code == 1 and out is not None and out["status"] == "blocked", (case, code, out)
    assert report.read_text(encoding="utf-8") == DECLARED_REPORT, case


def test_a_declared_report_refuses_a_record_that_is_not_there(tmp_path: Path) -> None:
    report = make_report(tmp_path, DECLARED_REPORT)
    code, out, _err = run_insert(
        ["--report", str(report), "--marker", MARKER], stdin_text=_envelope(tmp_path / "nope.json")
    )
    assert code == 1 and out is not None and out["status"] == "blocked"
    assert report.read_text(encoding="utf-8") == DECLARED_REPORT


def test_a_declared_report_takes_a_passing_record_and_drops_the_declaration(tmp_path: Path) -> None:
    report = make_report(tmp_path, DECLARED_REPORT)
    report_json = tmp_path / "report.json"
    report_json.write_text(json.dumps({"report_markdown": DECLARED_REPORT}), encoding="utf-8")
    code, out, err = run_insert(
        ["--report", str(report), "--marker", MARKER, "--report-json", str(report_json)],
        stdin_text=_envelope(_record(tmp_path)),
    )
    assert code == 0 and out is not None and out["status"] == "inserted", (code, out, err)
    text = report.read_text(encoding="utf-8")
    assert TEXT in text and "COACHING_REQUIRES_CHECK_RECORD" not in text, text
    assert json.loads(report_json.read_text(encoding="utf-8"))["report_markdown"] == text
    # A check that could not run passes the text through (it fails open) -- for this run only: the check reads the
    # run before it can fail, so a could-not-run record with no run was not written by it.
    report.write_text(DECLARED_REPORT, encoding="utf-8")
    code, out, _err = run_insert(
        ["--report", str(report), "--marker", MARKER],
        stdin_text=_envelope(_record(tmp_path, action="error")),
    )
    assert code == 0 and out is not None and out["status"] == "inserted", (code, out)
    report.write_text(DECLARED_REPORT, encoding="utf-8")
    code, out, _err = run_insert(
        ["--report", str(report), "--marker", MARKER],
        stdin_text=_envelope(_record(tmp_path, action="error", run_id=None)),
    )
    assert code == 1 and out is not None and out["status"] == "blocked", (code, out)
    assert report.read_text(encoding="utf-8") == DECLARED_REPORT


def test_an_undeclared_report_ignores_a_check_record(tmp_path: Path) -> None:
    """The five skills whose compose writes no declaration: a record, even a failing one, changes nothing."""
    report = make_report(tmp_path, BASE_REPORT)
    code, out, _err = run_insert(
        ["--report", str(report), "--marker", MARKER],
        stdin_text=_envelope(_record(tmp_path, action="findings")),
    )
    assert code == 0 and out is not None and out["status"] == "inserted", (code, out)


def test_only_cap_tables_compose_declares_a_check_record() -> None:
    skills = Path(SCRIPTS_DIR).parent / "skills"
    composes = sorted(skills.glob("*/scripts/compose_report.py"))
    assert len(composes) == 6, composes
    declaring = [p.parent.parent.name for p in composes if "COACHING_REQUIRES_CHECK_RECORD" in p.read_text("utf-8")]
    assert declaring == ["cap-table"], declaring
