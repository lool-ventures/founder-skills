"""Tests for privacy_guard.py — the pre-commit / CI privacy leak detector.

No real company names appear here (the detector is tested with placeholder
names passed in-memory). Run: uv run pytest scripts/test_privacy_guard.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

import privacy_guard as pg  # noqa: E402

# ---- Layer 1: stray confidential documents -------------------------------


def test_doc_outside_allowlist_flagged():
    findings = pg.scan_text_and_paths(
        paths=["cowork-tests/fixtures/acme_real_captable.xlsx"],
        contents={},
        names=[],
    )
    assert any(f.layer == "document" for f in findings)


def test_doc_inside_allowlist_ok():
    findings = pg.scan_text_and_paths(
        paths=["cowork-tests/fixtures/synthetic_carta.xlsx"],
        contents={},
        names=[],
    )
    assert not findings


def test_non_doc_extension_ignored_by_layer1():
    findings = pg.scan_text_and_paths(
        paths=["founder-skills/skills/cap-table/scripts/foo.py"],
        contents={"founder-skills/skills/cap-table/scripts/foo.py": "x = 1\n"},
        names=[],
    )
    assert not findings


# ---- Layer 2: provenance / named-after-company tags ----------------------


def test_named_after_company_pattern_flagged():
    text = "handle the Acmecorp P-1 failure here"
    findings = pg.scan_text_and_paths(paths=["a.py"], contents={"a.py": text}, names=[])
    assert any(f.layer == "provenance" for f in findings)


def test_standalone_round_id_out_of_scope():
    # A bare round/case ID with no proper noun is process-provenance, not a
    # privacy leak — deliberately NOT flagged (keeps the gate high-precision).
    findings = pg.scan_text_and_paths(paths=["a.py"], contents={"a.py": "the R-5 shape\n"}, names=[])
    assert not any(f.layer == "provenance" for f in findings)


def test_generic_english_not_flagged():
    for phrase in ("the same shape", "the exact shape", "the bug shape", "the embedded-viewer case"):
        findings = pg.scan_text_and_paths(paths=["a.py"], contents={"a.py": phrase + "\n"}, names=[])
        assert not findings, f"false positive on: {phrase}"


def test_capitalized_tool_noun_not_flagged():
    # Proper noun without a round/case ID is a tool/format name, not a leak.
    for phrase in ("the JSON shape", "the Carta shape", "the Docker case"):
        findings = pg.scan_text_and_paths(paths=["a.py"], contents={"a.py": phrase + "\n"}, names=[])
        assert not any(f.layer == "provenance" for f in findings), f"false positive on: {phrase}"


def test_clean_text_no_provenance():
    findings = pg.scan_text_and_paths(
        paths=["a.py"], contents={"a.py": "compute the discount and return it\n"}, names=[]
    )
    assert not findings


# ---- Layer 3: local denylist (exact names, never committed) ---------------


def test_denylisted_name_flagged_case_insensitive():
    findings = pg.scan_text_and_paths(
        paths=["a.py"],
        contents={"a.py": "# the acmecorp deal taught us this\n"},
        names=["Acmecorp"],
    )
    assert any(f.layer == "name" for f in findings)


def test_denylist_word_boundary_no_substring_false_positive():
    findings = pg.scan_text_and_paths(
        paths=["a.py"],
        contents={"a.py": "acmecorporation is a different word\n"},
        names=["Acmecorp"],
    )
    assert not any(f.layer == "name" for f in findings)


def test_no_names_means_no_name_findings():
    findings = pg.scan_text_and_paths(paths=["a.py"], contents={"a.py": "Acmecorp everywhere\n"}, names=[])
    assert not any(f.layer == "name" for f in findings)


def test_denylisted_name_in_file_path_flagged():
    # A denylisted name in a staged PATH (e.g. a fixture named after the real
    # company) must be caught even if it never appears in file CONTENT. Separator
    # characters (_ - .) are word-bounded so the whole-word match still fires.
    for path in ("founder-skills/tests/fixtures/acmecorp_note.json", "cap-table-acmecorp/inputs.json"):
        findings = pg.scan_text_and_paths(paths=[path], contents={}, names=["Acmecorp"])
        assert any(f.layer == "name" for f in findings), f"missed name in path: {path}"


def test_synthetic_name_in_path_not_flagged():
    findings = pg.scan_text_and_paths(
        paths=["founder-skills/tests/fixtures/foobar_note.json"], contents={}, names=["Acmecorp"]
    )
    assert not any(f.layer == "name" for f in findings)


# ---- denylist file loader -------------------------------------------------


def test_load_names_skips_comments_and_blanks(tmp_path):
    p = tmp_path / "names.txt"
    p.write_text("# comment\n\nAcmecorp\n  Foobar  \n")
    names = pg.load_names(str(p))
    assert names == ["Acmecorp", "Foobar"]


def test_load_names_missing_file_returns_empty():
    assert pg.load_names("/nonexistent/path/names.txt") == []
