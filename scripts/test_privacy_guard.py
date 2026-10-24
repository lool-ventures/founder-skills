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


# ==========================================================================
# Figure / verbatim / figure-provenance layers.
#
# Every private value below is INVENTED. The private "data room" is built in tmp_path at test time
# and pointed at through a temp sources file; nothing real is read, named or committed.
# ==========================================================================

import json  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402

import pytest  # noqa: E402

FAKE_QUOTE = "the zebra ledger reconciles quarterly moonbeam invoices"  # invented 8-word line


# Invented phrases, one per founder-document format in the fake data room, and one in a kept run's
# transcript. Each is long enough for a 6-word run; none occurs anywhere else in this file's vault.
DOCX_QUOTE = "the copper heron audits seventeen velvet warehouses before dawn"
PPTX_QUOTE = "amber walrus forecasts lunar pretzel demand across nine harbors"
XLSX_ROW = "violet otter negotiates tangerine lease renewals quietly"
PDF_QUOTE = "saffron beetle underwrites polar marmalade bonds every spring"
SIDE_NOTE_QUOTE = "a teal badger drafted these diligence notes by hand"
TRANSCRIPT_QUOTE = "the plum giraffe recommends adding a closing slide here"
BREAK_FIRST, BREAK_SECOND = "crimson llama ships", "frozen kumquat crates to tundra"


def _zip(path, parts: dict[str, str]) -> None:
    import zipfile

    with zipfile.ZipFile(path, "w") as zf:
        for name, body in parts.items():
            zf.writestr(name, body)


_W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
_A = 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
_S = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'


def _write_docx(path) -> None:
    # The first word is split across two runs, as Word does: the reader must join runs with no separator.
    first, rest = DOCX_QUOTE[:7], DOCX_QUOTE[7:]
    body = (
        f"<w:document {_W}><w:body>"
        f"<w:p><w:r><w:t>{first}</w:t></w:r><w:r><w:t>{rest}</w:t></w:r></w:p>"
        f"<w:p><w:r><w:t>{BREAK_FIRST}</w:t></w:r></w:p><w:p><w:r><w:t>{BREAK_SECOND}</w:t></w:r></w:p>"
        "</w:body></w:document>"
    )
    _zip(path, {"[Content_Types].xml": "<Types/>", "word/document.xml": body})


def _write_pptx(path) -> None:
    slide = f'<p:sld {_A} xmlns:p="x"><a:p><a:r><a:t>{PPTX_QUOTE}</a:t></a:r></a:p></p:sld>'
    _zip(path, {"[Content_Types].xml": "<Types/>", "ppt/slides/slide1.xml": slide})


def _write_xlsx(path) -> None:
    # Row 1 = shared, shared, inline, shared, numeric. A shared cell's <v> is an INDEX (0, 1, 2): the
    # reader must resolve it, or the row reads "0 1 tangerine 2 4242" and the phrase is lost.
    words = XLSX_ROW.split()
    shared = [" ".join(words[0:2]), words[2], " ".join(words[4:7])]
    sst = f"<sst {_S}>" + "".join(f"<si><t>{t}</t></si>" for t in shared) + "</sst>"
    sheet = (
        f'<worksheet {_S}><sheetData><row r="1">'
        '<c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c>'
        f'<c r="C1" t="inlineStr"><is><t>{words[3]}</t></is></c>'
        '<c r="D1" t="s"><v>2</v></c><c r="E1"><v>4242</v></c>'
        "</row></sheetData></worksheet>"
    )
    _zip(path, {"[Content_Types].xml": "<Types/>", "xl/sharedStrings.xml": sst, "xl/worksheets/sheet1.xml": sheet})


def _write_pdf(path, sentence: str) -> None:
    stream = b"BT /F1 12 Tf 72 700 Td (" + sentence.encode() + b") Tj ET"
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R"
        b" /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    pdf, offsets = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offsets.append(len(pdf))
        pdf += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
    xref = len(pdf)
    pdf += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    pdf += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    pdf += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    path.write_bytes(pdf)


def _fake_sources(tmp_path, extra_text: str = ""):
    private = tmp_path / "vault-alpha"
    (private / "run").mkdir(parents=True)
    (private / "run" / "report.md").write_text(
        f"Revenue was $1,111 and margin 7,777.77 with a 13.3x multiple.\n{FAKE_QUOTE}\n{extra_text}"
    )
    # a kept run's transcript: model-written text, matched by hand-written paths only
    (private / "run" / "session.jsonl").write_text(json.dumps({"type": "assistant", "text": TRANSCRIPT_QUOTE}) + "\n")
    # the founder's data room: documents, a hand note beside them, and our report written beside them
    room = private / "dataroom"
    room.mkdir()
    _write_docx(room / "memo.docx")
    _write_pptx(room / "deck.pptx")
    _write_xlsx(room / "model.xlsx")
    _write_pdf(room / "deck.pdf", PDF_QUOTE)
    (room / "notes.md").write_text(SIDE_NOTE_QUOTE + "\n")
    (room / "report.md").write_text("our output beside it: the onyx pelican grades every slide twice\n")
    (room / "legacy.xls").write_bytes(b"\xd0\xcf\x11\xe0 not a zip")
    # an excluded copy of our own code: its figures must NOT enter the index
    (private / "skill-copy").mkdir()
    (private / "skill-copy" / "x.md").write_text("ceiling 424242 lives here\n")
    cfg = tmp_path / "sources.txt"
    cfg.write_text(f"# local only\n{private}\n!skill-copy\n")
    return cfg, private


# An allowlist path that never exists: an in-process index must not read the checkout's real allowlist.
_NO_ALLOWLIST = os.path.join(os.sep, "nonexistent", "privacy-figure-allowlist.txt")


def _index(tmp_path, own_text: str = ""):
    cfg, _ = _fake_sources(tmp_path)
    spec = pg.load_sources(str(cfg))
    return pg.build_private_index(
        spec, own_code_texts=[own_text], cache_dir=str(tmp_path / "cache"), allowlist_path=_NO_ALLOWLIST
    )


def test_figure_in_added_text_is_flagged(tmp_path):
    idx = _index(tmp_path)
    for added in ("a live report printed $1,111", "margin of 7,777.77 here", "about 13.3x the build"):
        f = pg.find_figure_leaks("notes.md", [(4, added)], idx)
        assert f and f[0].layer == "figure" and f[0].detail == "matches a figure in local private sources", added


def test_figure_matching_is_whole_token(tmp_path):
    idx = _index(tmp_path)
    for added in ("ids 11110 and 21111", "$11,110 total", "7,777.771"):
        assert pg.find_figure_leaks("a.py", [(1, added)], idx) == [], added


def test_generic_values_are_never_figures():
    toks = [t for t, _raw in pg.extract_figures("in 2019 v2.1.284 id 1234-5678-9abc costs 100 or 1,000 at 50%")]
    assert toks == [], toks


def test_excluded_subpath_does_not_enter_the_index(tmp_path):
    idx = _index(tmp_path)
    assert pg.find_figure_leaks("a.py", [(1, "ceiling 424242")], idx) == []


def test_verbatim_six_word_run_is_flagged(tmp_path):
    idx = _index(tmp_path)
    f = pg.find_verbatim_leaks("notes.md", [(2, "as seen: The Zebra Ledger reconciles quarterly moonbeam! done")], idx)
    assert f and f[0].layer == "verbatim"


def test_six_gram_that_is_also_our_own_code_is_ignored(tmp_path):
    idx = _index(tmp_path, own_text=FAKE_QUOTE)
    assert pg.find_verbatim_leaks("notes.md", [(1, FAKE_QUOTE)], idx) == []


def test_missing_sources_file_disables_the_local_layers(tmp_path):
    spec = pg.load_sources(str(tmp_path / "absent.txt"))
    assert spec is None


def test_figure_next_to_provenance_phrase_is_flagged_and_marker_accepts_it():
    hit = pg.find_figure_provenance("a.py", [(3, "# a live run printed 4,321 customers")])
    assert hit and hit[0].layer == "figure-provenance"
    assert pg.find_figure_provenance("a.py", [(3, "# a live run printed 4,321  # privacy-guard: synthetic")]) == []
    assert pg.find_figure_provenance("a.py", [(3, "# a live run printed nothing useful")]) == []
    assert pg.find_figure_provenance("a.py", [(3, "total = 4,321 customers")]) == []


def test_added_lines_are_parsed_from_a_zero_context_diff():
    diff = (
        "diff --git a/x.md b/x.md\n--- a/x.md\n+++ b/x.md\n@@ -1,0 +2,2 @@\n+first new\n+second new\n"
        "diff --git a/y.py b/y.py\n--- /dev/null\n+++ b/y.py\n@@ -0,0 +1 @@\n+only\n"
    )
    assert pg.added_lines_from_diff(diff) == {"x.md": [(2, "first new"), (3, "second new")], "y.py": [(1, "only")]}


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout


def test_range_mode_scans_added_lines_and_messages_and_never_prints_the_source(tmp_path):
    cfg, private = _fake_sources(tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "T")
    (repo / "a.md").write_text("hello\n")
    _git(repo, "add", "a.md")
    _git(repo, "commit", "-q", "-m", "init")
    (repo / "a.md").write_text("hello\nthe total was $1,111\n")
    _git(repo, "add", "a.md")
    _git(repo, "commit", "-q", "-m", f"note: {FAKE_QUOTE}")
    out = subprocess.run(
        [
            sys.executable,
            os.path.join(os.path.dirname(__file__), "privacy_guard.py"),
            "--range",
            "HEAD~1..HEAD",
            "--sources-file",
            str(cfg),
            "--cache-dir",
            str(tmp_path / "cache"),
            "--no-names",
        ],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    assert out.returncode == 1, out.stderr
    assert "[figure" in out.stderr and "[verbatim" in out.stderr and "commit message" in out.stderr
    assert str(private) not in out.stderr and "vault-alpha" not in out.stderr and "zebra" not in out.stderr.lower()


def test_commit_msg_mode_flags_a_private_figure(tmp_path, monkeypatch):
    # Outside any repo, so nothing is subtracted as our own code: run in this checkout, the guard reads its real
    # origin/main, which carries this file -- and this file's invented figure -- once it has been pushed.
    monkeypatch.chdir(tmp_path)
    cfg, _ = _fake_sources(tmp_path)
    msg = tmp_path / "MSG"
    msg.write_text("fix: handle 7,777.77 margins\n\n# comment line ignored 13.3x\nSigned-off-by: T <t@example.com>\n")
    rc = pg._main(
        ["--commit-msg", str(msg), "--sources-file", str(cfg), "--cache-dir", str(tmp_path / "c"), "--no-names"]
    )
    assert rc == 1


def test_tree_mode_figure_provenance_only_warns(tmp_path, monkeypatch):
    (tmp_path / "f.md").write_text("a live run printed 4,321 customers\n")
    monkeypatch.chdir(tmp_path)
    rc = pg._main(["f.md", "--no-names", "--provenance-warn-only"])
    assert rc == 0


def test_a_private_figure_that_is_also_in_our_own_code_is_not_a_finding(tmp_path):
    idx = _index(tmp_path, own_text="the default ceiling is 7,777.77 in our docs")
    assert pg.find_figure_leaks("a.py", [(1, "margin 7,777.77")], idx) == []
    assert pg.find_figure_leaks("a.py", [(1, "about 13.3x")], idx)  # control: other figures still found


def test_cassette_recordings_skip_the_figure_layer_but_not_verbatim(tmp_path):
    idx = _index(tmp_path)
    cas = "cowork-tests/cassettes/x.cassette.json"
    found = pg.scan_added({cas: [(1, f"$1,111 {DOCX_QUOTE}")]}, idx, [])
    layers = {f.layer for f in found}
    assert "figure" not in layers and "verbatim" in layers


def test_cassette_recordings_skip_figure_provenance_but_not_verbatim(tmp_path):
    """A recording narrates synthetic runs in the skills' own words ("the founder's", "the deck's")."""
    idx = _index(tmp_path)
    cas = "cowork-tests/cassettes/x.cassette.json"
    line = f"a live run printed $1,111 {DOCX_QUOTE}"
    assert pg.find_figure_provenance(cas, [(1, line)]) == []
    layers = {f.layer for f in pg.scan_added({cas: [(1, line)]}, idx, [])}
    assert "figure-provenance" not in layers and "verbatim" in layers
    assert pg.find_figure_provenance("a.py", [(1, line)])  # control: outside recordings it still fires


# ---- recordings: verbatim against the founder documents only ------------------------------------

CAS = "cowork-tests/cassettes/x.cassette.json"


def _as_event(text: str) -> str:
    """How a phrase sits in a cassette line: inside a JSON-encoded event string."""
    return json.dumps(json.dumps({"type": "assistant", "text": text}))


@pytest.mark.parametrize("quote", [DOCX_QUOTE, PPTX_QUOTE, XLSX_ROW, SIDE_NOTE_QUOTE])
def test_six_document_words_on_a_recording_block(tmp_path, quote):
    idx = _index(tmp_path)
    six = " ".join(quote.split()[:6])
    found = pg.scan_added({CAS: [(3, _as_event(f"as quoted: {six}, end"))]}, idx, [])
    assert [f.layer for f in found] == ["verbatim"], quote
    five = " ".join(quote.split()[:5])  # control: five words never fire
    assert pg.find_verbatim_leaks(CAS, [(3, _as_event(f"as quoted: {five}, end"))], idx) == []


@pytest.mark.skipif(not shutil.which("pdftotext"), reason="pdftotext not installed")
def test_six_pdf_words_on_a_recording_block(tmp_path):
    idx = _index(tmp_path)
    assert pg.find_verbatim_leaks(CAS, [(1, _as_event(PDF_QUOTE))], idx)


def test_a_transcript_phrase_blocks_a_hand_written_path_but_not_a_recording(tmp_path):
    idx = _index(tmp_path)
    assert pg.find_verbatim_leaks(CAS, [(1, _as_event(TRANSCRIPT_QUOTE))], idx) == []
    assert pg.find_verbatim_leaks("notes.md", [(1, TRANSCRIPT_QUOTE)], idx)
    # the kept run's report (no document in its folder) behaves the same way
    assert pg.find_verbatim_leaks(CAS, [(1, _as_event(FAKE_QUOTE))], idx) == []
    assert pg.find_verbatim_leaks("notes.md", [(1, FAKE_QUOTE)], idx)


def test_the_all_sources_count_still_sees_a_recording_collision(tmp_path):
    idx = _index(tmp_path)
    line = [(1, _as_event(TRANSCRIPT_QUOTE))]
    assert pg.find_verbatim_leaks(CAS, line, idx) == []
    assert pg.find_verbatim_leaks(CAS, line, idx, all_sources=True)


def test_which_source_files_are_founder_documents(tmp_path):
    _cfg, private = _fake_sources(tmp_path)
    (private / "loose").mkdir()
    (private / "loose" / "notes.md").write_text("no document in this folder\n")
    spec = pg.load_sources(str(_cfg))
    files = pg._source_files(spec)
    rel = {os.path.relpath(f, private) for f in pg._input_files(files)}
    assert rel == {
        "dataroom/memo.docx",
        "dataroom/deck.pptx",
        "dataroom/model.xlsx",
        "dataroom/deck.pdf",
        "dataroom/notes.md",
    }
    assert "dataroom/legacy.xls" not in {os.path.relpath(f, private) for f in files}


def test_a_binary_office_file_is_counted_in_a_note_never_named(tmp_path, capsys):
    _index(tmp_path)
    err = capsys.readouterr().err
    assert "1 .xls source file(s) skipped" in err and "legacy" not in err and "vault-alpha" not in err


def test_a_spreadsheet_shared_string_index_never_enters_the_index(tmp_path):
    text = pg._ooxml_text(str(_fake_sources(tmp_path)[1] / "dataroom" / "model.xlsx"))
    assert text.split() == XLSX_ROW.split() + ["4242"]


def test_a_document_line_break_quoted_with_a_json_escape_still_blocks(tmp_path, monkeypatch):
    """The document holds the run across a paragraph break; the recording holds it as `\\n`."""
    idx = _index(tmp_path)
    phrase = f"{BREAK_FIRST}\n{' '.join(BREAK_SECOND.split()[:3])}"  # 3 + 3 words across the break
    once = json.dumps({"text": phrase})  # one level of escaping
    twice = _as_event(phrase)  # an event string inside the cassette JSON
    for line in (once, twice):
        assert "\\n" in line
        assert pg.find_verbatim_leaks(CAS, [(1, line)], idx), line
    # lever engaged: with the escape left in, the same lines are not seen
    monkeypatch.setattr(pg, "_unescape_json", lambda text, passes=3: text)
    for line in (once, twice):
        assert pg.find_verbatim_leaks(CAS, [(1, line)], idx) == [], line


def test_line_numbering_never_blocks_a_recording_but_other_small_integers_do(tmp_path):
    """Only the `cat -n` shape (six integers, each one more than the last, at any width) is skipped, and
    only on a recording. Any other run of integers that a document holds still blocks a recording."""
    room = _fake_sources(tmp_path)[1] / "dataroom"
    (room / "numbered.csv").write_text("7,8,9,10,11,12\n")
    (room / "scores.csv").write_text("12,40,7,33,18,9\n")
    (room / "numbered_long.csv").write_text("431,432,433,434,435,436\n")
    spec = pg.load_sources(str(tmp_path / "sources.txt"))
    idx = pg.build_private_index(
        spec, own_code_texts=[""], cache_dir=str(tmp_path / "cache2"), allowlist_path=_NO_ALLOWLIST
    )
    # space-separated, so this does not depend on the unescape
    assert pg.find_verbatim_leaks(CAS, [(1, "7 8 9 10 11 12")], idx) == []
    assert pg.find_verbatim_leaks(CAS, [(1, json.dumps({"text": "7\n8\n9\n10\n11\n12"}))], idx) == []
    # a read past line 99: three-digit line numbers are the same shape
    assert pg.find_verbatim_leaks(CAS, [(1, json.dumps({"text": "431\n432\n433\n434\n435\n436"}))], idx) == []
    assert pg.find_verbatim_leaks("notes.md", [(1, "7 8 9 10 11 12")], idx)  # hand-written: unchanged
    assert pg.find_verbatim_leaks("notes.md", [(1, "431 432 433 434 435 436")], idx)
    # inverse control: non-consecutive small integers from a document still block a recording
    assert pg.find_verbatim_leaks(CAS, [(1, "12 40 7 33 18 9")], idx)
    assert pg.find_verbatim_leaks(CAS, [(1, json.dumps({"text": "12\n40\n7\n33\n18\n9"}))], idx)


def test_only_a_cassette_file_under_the_cassettes_folder_is_a_recording(tmp_path):
    idx = _index(tmp_path)
    stray = "cowork-tests/cassettes/notes.md"
    assert not pg.is_recording(stray) and pg.is_recording(CAS)
    assert pg.find_verbatim_leaks(stray, [(1, TRANSCRIPT_QUOTE)], idx)
    assert pg.find_verbatim_leaks(CAS, [(1, TRANSCRIPT_QUOTE)], idx) == []
    assert {f.layer for f in pg.scan_added({stray: [(1, "a live run printed $1,111")]}, idx, [])} >= {
        "figure",
        "figure-provenance",
    }


# ---- synthetic replay corpora: treated as recordings --------------------------------------------

CORPUS = "evals/financial-model-review/metric_claim_corpus.json"


def test_the_synthetic_corpus_skips_the_figure_layer(tmp_path):
    """Its runs are kept among the private sources, so its figures collide with themselves there."""
    idx = _index(tmp_path)
    assert pg.is_synthetic_corpus(CORPUS) and not pg.is_recording(CORPUS)
    line = [(1, json.dumps({"evidence": "margin of 7,777.77 and about 13.3x"}))]
    assert pg.find_figure_leaks(CORPUS, line, idx)  # lever engaged: the figures are in the index
    assert pg.scan_added({CORPUS: line}, idx, []) == []


def test_a_document_run_on_the_synthetic_corpus_still_blocks(tmp_path):
    idx = _index(tmp_path)
    six = " ".join(DOCX_QUOTE.split()[:6])
    found = pg.scan_added({CORPUS: [(4, json.dumps({"evidence": f"as quoted: {six}, end"}))]}, idx, [])
    assert [f.layer for f in found] == ["verbatim"]


def test_a_kept_run_phrase_does_not_block_the_synthetic_corpus(tmp_path):
    """Verbatim against the documents only: a kept run's transcript or report repeats the corpus."""
    idx = _index(tmp_path)
    for quote in (TRANSCRIPT_QUOTE, FAKE_QUOTE):
        assert pg.find_verbatim_leaks(CORPUS, [(1, json.dumps({"evidence": quote}))], idx) == []
        assert pg.find_verbatim_leaks(CORPUS, [(1, json.dumps({"evidence": quote}))], idx, all_sources=True)


def test_the_synthetic_corpus_keeps_figure_provenance(tmp_path):
    """Only the figure layer and the verbatim source set change; layer 6 still reads the corpus."""
    line = [(1, "a live run printed $1,111")]
    assert {f.layer for f in pg.scan_added({CORPUS: line}, _index(tmp_path), [])} == {"figure-provenance"}


def test_any_other_file_under_evals_is_fully_checked(tmp_path):
    idx = _index(tmp_path)
    for other in (
        "evals/financial-model-review/harvest_metric_claims.py",
        "evals/financial-model-review/other_corpus.json",
        "evals/cap-table/metric_claim_corpus.json",
        "x/evals/financial-model-review/metric_claim_corpus.json",
    ):
        assert not pg.is_synthetic_corpus(other)
        assert {f.layer for f in pg.scan_added({other: [(1, "a live run printed $1,111")]}, idx, [])} >= {
            "figure",
            "figure-provenance",
        }, other
        assert pg.find_verbatim_leaks(other, [(1, TRANSCRIPT_QUOTE)], idx), other


def test_own_code_is_subtracted_from_the_documents_set(tmp_path):
    """A document phrase that is also in our published code is ours, on a recording path too."""
    idx = _index(tmp_path, own_text=DOCX_QUOTE)
    assert pg.find_verbatim_leaks(CAS, [(1, _as_event(DOCX_QUOTE))], idx) == []
    assert pg.find_verbatim_leaks(CAS, [(1, _as_event(PPTX_QUOTE))], idx)  # control


def _encrypted_shaped_zip(path) -> None:
    """A docx whose entry carries the zip encryption flag (bit 0): reading it raises RuntimeError."""
    _write_docx(path)
    data = bytearray(path.read_bytes())
    for sig, off in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):
        i = data.find(sig)
        while i != -1:
            data[i + off] |= 0x01
            i = data.find(sig, i + 4)
    path.write_bytes(bytes(data))


def _corrupt_deflate_zip(path) -> None:
    """A valid zip directory over a deflate stream that is garbage: reading it raises zlib.error."""
    import zipfile

    body = f"<w:document {_W}><w:body><w:p><w:r><w:t>{'x' * 400}</w:t></w:r></w:p></w:body></w:document>"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("word/document.xml", body)
    data = bytearray(path.read_bytes())
    start = 30 + len("word/document.xml")
    for k in range(start, start + 20):
        data[k] = 0xFF
    path.write_bytes(bytes(data))


def test_unreadable_office_files_are_counted_never_raised_never_silent(tmp_path, capsys):
    _cfg, private = _fake_sources(tmp_path)
    bad = private / "badroom"
    bad.mkdir()
    _encrypted_shaped_zip(bad / "locked.docx")
    _corrupt_deflate_zip(bad / "broken.docx")
    (bad / "protected.xlsx").write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 504)  # OLE container
    (bad / "truncated.pptx").write_bytes(b"PK\x03\x04 truncated")
    for f in ("locked.docx", "broken.docx", "protected.xlsx", "truncated.pptx"):
        assert pg._ooxml_text(str(bad / f)) is None, f
    spec = pg.load_sources(str(_cfg))
    idx = pg.build_private_index(spec, own_code_texts=[""], cache_dir=str(tmp_path / "c"), allowlist_path=_NO_ALLOWLIST)
    err = capsys.readouterr().err
    assert "2 .docx, 1 .pptx, 1 .xlsx source file(s) unreadable (encrypted or corrupt)" in err, err
    assert "locked" not in err and "badroom" not in err and "vault-alpha" not in err
    assert pg.find_verbatim_leaks(CAS, [(1, _as_event(DOCX_QUOTE))], idx)  # the readable ones still count
    # a readable office file is "" when empty, not None
    _zip(bad / "empty.docx", {"word/document.xml": f"<w:document {_W}><w:body/></w:document>"})
    assert pg._ooxml_text(str(bad / "empty.docx")) == ""


def test_the_cache_key_changes_with_pdftotext_availability(tmp_path, monkeypatch):
    cfg, _ = _fake_sources(tmp_path)
    spec = pg.load_sources(str(cfg))
    cache = tmp_path / "keyed"

    def build_with(which):
        monkeypatch.setattr(pg, "_pdftotext_id", lambda: which)
        pg.build_private_index(spec, own_code_texts=[""], cache_dir=str(cache), allowlist_path=_NO_ALLOWLIST)
        return set(os.listdir(cache))

    first = build_with("absent")
    second = build_with("/usr/bin/pdftotext|pdftotext version 99")
    assert len(first) == 1 and len(second) == 2, (first, second)
    assert build_with("absent") == second  # same availability -> same key, reused


def test_the_cache_key_changes_with_the_document_rule(tmp_path, monkeypatch):
    cfg, _ = _fake_sources(tmp_path)
    spec = pg.load_sources(str(cfg))
    cache = tmp_path / "keyed"
    pg.build_private_index(spec, own_code_texts=[""], cache_dir=str(cache), allowlist_path=_NO_ALLOWLIST)
    monkeypatch.setattr(pg, "OUTPUT_NAME_MARKERS", (*pg.OUTPUT_NAME_MARKERS, "notes"))
    pg.build_private_index(spec, own_code_texts=[""], cache_dir=str(cache), allowlist_path=_NO_ALLOWLIST)
    assert len(os.listdir(cache)) == 2


def test_a_hand_written_path_keeps_the_escape_as_written(tmp_path):
    """Only recordings are unescaped; a hand-written line tokenises exactly as before."""
    assert pg._words("a\\nb") == ["a", "nb"]


def _scratch_repo(tmp_path):
    repo = tmp_path / "repo"
    (repo / "cowork-tests" / "cassettes").mkdir(parents=True)
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "T")
    return repo


def _staged_guard(repo, cfg, cache):
    return subprocess.run(
        [
            sys.executable,
            os.path.join(os.path.dirname(__file__), "privacy_guard.py"),
            "--staged",
            "--sources-file",
            str(cfg),
            "--cache-dir",
            str(cache),
            "--no-names",
        ],
        cwd=repo,
        capture_output=True,
        text=True,
    )


def test_staged_cli_blocks_a_document_quote_in_a_cassette_and_passes_a_transcript_echo(tmp_path):
    cfg, private = _fake_sources(tmp_path)
    repo = _scratch_repo(tmp_path)
    cas = repo / "cowork-tests" / "cassettes" / "x.cassette.json"
    cas.write_text(_as_event(f"the run said {TRANSCRIPT_QUOTE}") + "\n")
    _git(repo, "add", "-A")
    clean = _staged_guard(repo, cfg, tmp_path / "cache")
    assert clean.returncode == 0, clean.stderr
    cas.write_text(_as_event(f"the run said {TRANSCRIPT_QUOTE}") + "\n" + _as_event(f"memo: {DOCX_QUOTE}") + "\n")
    _git(repo, "add", "-A")
    hit = _staged_guard(repo, cfg, tmp_path / "cache")
    assert hit.returncode == 1 and "[verbatim" in hit.stderr and "x.cassette.json:2" in hit.stderr, hit.stderr
    assert "x.cassette.json:1" not in hit.stderr
    assert str(private) not in hit.stderr and "heron" not in hit.stderr and "giraffe" not in hit.stderr


def test_measured_alone_is_not_a_provenance_phrase():
    """Dropped: this repo's own notes say "measured" with a figure constantly, and every such line warned."""
    assert pg.find_figure_provenance("a.py", [(1, "# measured 2,854 findings on the corpus")]) == []
    assert pg.find_figure_provenance("a.py", [(1, "# a live run printed 2,854 findings")])  # control


def test_verbatim_report_prints_per_file_counts_only(tmp_path, capsys):
    cfg, private = _fake_sources(tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "T")
    (repo / "a.md").write_text("hello\n")
    _git(repo, "add", "a.md")
    _git(repo, "commit", "-q", "-m", "init")
    (repo / "a.md").write_text(f"hello\n{FAKE_QUOTE}\n")
    (repo / "b.md").write_text(f"x\n{FAKE_QUOTE}\ny\n{FAKE_QUOTE}\n")
    _git(repo, "add", "a.md", "b.md")
    _git(repo, "commit", "-q", "-m", "add")
    out = subprocess.run(
        [
            sys.executable,
            os.path.join(os.path.dirname(__file__), "privacy_guard.py"),
            "--range",
            "HEAD~1..HEAD",
            "--verbatim-report",
            "--sources-file",
            str(cfg),
            "--cache-dir",
            str(tmp_path / "cache"),
            "--no-names",
        ],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    assert out.returncode == 0, out.stderr
    rows = [ln.split() for ln in out.stdout.splitlines() if ln.strip() and not ln.startswith("total")]
    assert ["2", "b.md"] in rows and ["1", "a.md"] in rows, out.stdout
    assert "total 3" in out.stdout
    assert "zebra" not in (out.stdout + out.stderr).lower() and "vault-alpha" not in out.stdout + out.stderr


def test_a_generated_file_skips_the_figure_and_verbatim_layers_but_not_provenance(tmp_path):
    idx = _index(tmp_path)
    gen = next(iter(pg.GENERATED_FILES))
    line = f"a live run printed $1,111 {FAKE_QUOTE}"
    layers = {f.layer for f in pg.scan_added({gen: [(1, line)]}, idx, [])}
    assert "figure" not in layers and "verbatim" not in layers
    assert "figure-provenance" in layers
    # control: the same text in an unlisted JSON file is still caught by both layers
    other = {f.layer for f in pg.scan_added({"founder-skills/data/other.json": [(1, line)]}, idx, [])}
    assert {"figure", "verbatim"} <= other


def test_every_generated_file_names_a_source_and_a_sync_test_that_exist():
    """An exemption is only safe while its source is scanned and a test holds the copy equal to it."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for gen, (source, sync_test) in pg.GENERATED_FILES.items():
        if not os.path.exists(os.path.join(root, gen)):
            continue
        assert os.path.isfile(os.path.join(root, source)), source
        with open(os.path.join(root, sync_test), encoding="utf-8") as fh:
            assert os.path.basename(gen) in fh.read(), f"{sync_test} does not check {gen}"


# ==========================================================================
# Where the private lists are found: the main checkout, from a linked worktree too.
#
# Every name and figure below is INVENTED. A tmp repo carries its own git-ignored docs/internal/ with
# a sources list pointing at the fake vault above and a one-entry denylist; nothing real is read.
# ==========================================================================

from pathlib import Path  # noqa: E402
from types import SimpleNamespace  # noqa: E402

GUARD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "privacy_guard.py")
HOOKS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hooks")
FAKE_NAME = "Zorblex Kettleworks"  # invented denylist entry
COPY_ONLY_NAME = "Quillon Brackwater"  # invented, only ever in a worktree's copy
SWITCH_KEY = "founderskills.privacyLists"
_REAL_HOME = os.path.expanduser("~")


@pytest.fixture(autouse=True)
def isolated_git_env(tmp_path, monkeypatch):
    """No test reads the maintainer's git config, private lists, cache or hook environment.

    The repo-local switch of this clone is overridden by command-line config (GIT_CONFIG_COUNT), which
    outranks every config file; a test that wants the switch on sets it through `_switch`."""
    for k in list(os.environ):
        if k.startswith(("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_")) or k in {
            "GIT_CONFIG_COUNT",
            "GIT_CONFIG_PARAMETERS",
            "GIT_DIR",
            "GIT_INDEX_FILE",
            "GIT_WORK_TREE",
            "GIT_PREFIX",
            "GIT_COMMON_DIR",
            "GIT_OBJECT_DIRECTORY",
            "GIT_ALTERNATE_OBJECT_DIRECTORIES",
            "FOUNDER_SKILLS_PRIVATE_DIR",
        }:
            monkeypatch.delenv(k, raising=False)
    empty = tmp_path / "_gitconfig_empty"
    empty.write_text("")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(empty))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    _switch(monkeypatch, "optional")
    # A subprocess guard caches under HOME; uv keeps finding its real cache and this interpreter.
    monkeypatch.setenv("UV_CACHE_DIR", os.environ.get("UV_CACHE_DIR") or os.path.join(_REAL_HOME, ".cache", "uv"))
    monkeypatch.setenv(
        "UV_PYTHON_INSTALL_DIR",
        os.environ.get("UV_PYTHON_INSTALL_DIR") or os.path.join(_REAL_HOME, ".local", "share", "uv", "python"),
    )
    monkeypatch.setenv("UV_PYTHON", sys.executable)
    monkeypatch.setenv("UV_OFFLINE", "1")
    monkeypatch.setenv("UV_NO_PROGRESS", "1")
    (tmp_path / "home").mkdir(exist_ok=True)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))


def _switch(monkeypatch, value: str | None) -> None:
    """Set the switch as command-line config, or (None) remove the override so config files decide."""
    if value is None:
        for k in ("GIT_CONFIG_COUNT", "GIT_CONFIG_KEY_0", "GIT_CONFIG_VALUE_0"):
            monkeypatch.delenv(k, raising=False)
        return
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", SWITCH_KEY)
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", value)


def _clean(text: str, private) -> None:
    """Nothing private reaches the output: no vault path, no fake quote, no list entry."""
    assert str(private) not in text and "vault-alpha" not in text, text
    low = text.lower()
    assert "zebra" not in low and "zorblex" not in low and "quillon" not in low, text


def _run(args, cwd, env=None):
    return subprocess.run(
        [sys.executable, GUARD, *args], cwd=cwd, capture_output=True, text=True, env=env or os.environ.copy()
    )


def _g(cwd, *args, env=None):
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, env=env or os.environ.copy(), check=False
    )


def _repo_with_worktree(tmp_path, with_scripts: bool = False):
    """A tmp repo whose main checkout carries the private lists, a linked worktree outside it (`wt`) and
    one in-tree under .claude/worktrees (`w2`). Neither worktree has a docs/internal/."""
    cfg, private = _fake_sources(tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "T")
    (repo / ".gitignore").write_text("docs/internal/\n.claude/\n")
    (repo / "a.md").write_text("hello\n")
    names = [".gitignore", "a.md"]
    if with_scripts:
        shutil.copytree(HOOKS, repo / "scripts" / "hooks")
        shutil.copy2(GUARD, repo / "scripts" / "privacy_guard.py")
        names += ["scripts"]
    _git(repo, "add", *names)
    _git(repo, "commit", "-q", "-m", "init")
    lists = repo / "docs" / "internal"
    lists.mkdir(parents=True)
    (lists / "privacy-private-sources.txt").write_text(cfg.read_text())
    (lists / "privacy-denylist.txt").write_text(f"# invented\n{FAKE_NAME}\n")
    wt = tmp_path / "wt"
    _git(repo, "worktree", "add", "-q", "-b", "wt", str(wt))
    w2 = repo / ".claude" / "worktrees" / "w2"
    _git(repo, "worktree", "add", "-q", "-b", "w2", str(w2))
    return SimpleNamespace(repo=repo, wt=wt, w2=w2, lists=lists, private=private, cache=tmp_path / "cache")


def _stage(where, name: str, text: str) -> None:
    (Path(where) / name).write_text(text)
    _git(where, "add", name)


def test_staged_from_a_linked_worktree_reads_the_main_checkouts_lists(tmp_path):
    r = _repo_with_worktree(tmp_path)
    _stage(r.wt, "x.md", "the total was $1,111\n")
    out = _run(["--staged", "--cache-dir", str(r.cache)], r.wt)
    assert out.returncode == 1 and "[figure" in out.stderr, out.stderr
    _clean(out.stderr, r.private)


def test_commit_msg_from_a_linked_worktree_reads_the_main_checkouts_lists(tmp_path):
    r = _repo_with_worktree(tmp_path)
    msg = tmp_path / "MSG"
    msg.write_text("fix: handle 7,777.77 margins\n")
    out = _run(["--commit-msg", str(msg), "--cache-dir", str(r.cache)], r.wt)
    assert out.returncode == 1 and "[figure" in out.stderr, out.stderr
    _clean(out.stderr, r.private)


def test_range_from_a_linked_worktree_reads_the_main_checkouts_lists(tmp_path):
    r = _repo_with_worktree(tmp_path)
    _stage(r.wt, "q.md", f"{FAKE_QUOTE}\n")
    _git(r.wt, "commit", "-q", "-m", "add q")
    out = _run(["--range", "HEAD~1..HEAD", "--cache-dir", str(r.cache)], r.wt)
    assert out.returncode == 1 and "[verbatim" in out.stderr, out.stderr
    _clean(out.stderr, r.private)


def test_names_from_a_linked_worktree_read_the_main_checkouts_denylist(tmp_path):
    r = _repo_with_worktree(tmp_path)
    _stage(r.wt, "n.md", f"we met {FAKE_NAME} today\n")
    out = _run(["--staged", "--cache-dir", str(r.cache)], r.wt)
    assert out.returncode == 1 and "[name" in out.stderr, out.stderr
    _clean(out.stderr, r.private)


def test_the_in_tree_worktree_reads_the_main_checkouts_lists_too(tmp_path):
    r = _repo_with_worktree(tmp_path)
    _stage(r.w2, "x.md", "the total was $1,111\n")
    out = _run(["--staged", "--cache-dir", str(r.cache)], r.w2)
    assert out.returncode == 1 and "[figure" in out.stderr, out.stderr


def test_a_worktree_copy_is_ignored_and_counted_never_shown(tmp_path):
    r = _repo_with_worktree(tmp_path)
    (r.lists / "privacy-figure-allowlist.txt").write_text("# main\n9,999.99\n")
    copy = r.wt / "docs" / "internal"
    copy.mkdir(parents=True)
    (copy / "privacy-figure-allowlist.txt").write_text("9,999.99\n$1,111\n")
    _stage(r.wt, "x.md", "the total was $1,111\n")
    out = _run(["--staged", "--cache-dir", str(r.cache)], r.wt)
    assert out.returncode == 1 and "[figure" in out.stderr, out.stderr  # main's allowlist applies
    note = [ln for ln in out.stderr.splitlines() if "ignoring this worktree's copy" in ln]
    assert len(note) == 1, out.stderr
    assert "1 entry only in the copy" in note[0] and "Delete the copy" in note[0], note
    assert "wt/docs/internal/privacy-figure-allowlist.txt" in note[0], note
    assert "repo/docs/internal/privacy-figure-allowlist.txt" in note[0], note
    assert "9,999" not in note[0] and "1,111" not in note[0], note
    _clean(out.stderr, r.private)


def test_an_identical_or_reordered_worktree_copy_is_not_noted(tmp_path, monkeypatch):
    r = _repo_with_worktree(tmp_path)
    copy = r.wt / "docs" / "internal"
    copy.mkdir(parents=True)
    _stage(r.wt, "x.md", "plain text\n")
    shutil.copy2(r.lists / "privacy-denylist.txt", copy / "privacy-denylist.txt")
    out = _run(["--staged", "--cache-dir", str(r.cache)], r.wt)
    assert out.returncode == 0 and "ignoring this worktree's copy" not in out.stderr, out.stderr
    # same entries, other order, other comments: no note, and no refusal under the switch
    (r.lists / "privacy-figure-allowlist.txt").write_text("# a\n9,999.99\n8,888.88\n")
    (copy / "privacy-figure-allowlist.txt").write_text("8,888.88\n# rewritten\n\n9,999.99\n")
    _switch(monkeypatch, "required")
    out = _run(["--staged", "--cache-dir", str(r.cache)], r.wt)
    assert out.returncode == 0 and "ignoring this worktree's copy" not in out.stderr, out.stderr


def test_main_checkout_subdirectory_finds_the_lists(tmp_path):
    r = _repo_with_worktree(tmp_path)
    sub = r.repo / "sub"
    sub.mkdir()
    _stage(sub, "x.md", "the total was $1,111\n")
    out = _run(["--staged", "--cache-dir", str(r.cache)], sub)
    assert out.returncode == 1 and "[figure" in out.stderr, out.stderr


def test_tree_no_names_is_unchanged_and_silent(tmp_path):
    repo = _scratch_repo(tmp_path)
    (repo / "a.md").write_text("hello\n")
    _git(repo, "add", "a.md")
    out = _run(["--tree", "--no-names"], repo)
    assert out.returncode == 0 and out.stderr == "" and out.stdout == "", (out.stdout, out.stderr)


def test_missing_lists_print_one_line_and_refuse_only_under_the_switch(tmp_path, monkeypatch):
    r = _repo_with_worktree(tmp_path)
    shutil.rmtree(r.lists)
    _stage(r.wt, "x.md", "plain text\n")
    out = _run(["--staged", "--cache-dir", str(r.cache)], r.wt)
    assert out.returncode == 0, out.stderr
    lines = [ln for ln in out.stderr.splitlines() if "no private lists here" in ln]
    assert len(lines) == 1 and "normal for a public clone" in lines[0], out.stderr
    assert "privacy-denylist.txt" in lines[0] and "privacy-private-sources.txt" in lines[0], lines
    assert "allowlist" not in lines[0], lines
    _switch(monkeypatch, "required")
    out = _run(["--staged", "--cache-dir", str(r.cache)], r.wt)
    assert out.returncode == 3, out.stderr
    assert out.stderr.startswith("privacy-guard: private lists required ("), out.stderr
    assert f"git config {SWITCH_KEY} optional" in out.stderr, out.stderr


def test_the_switch_reaches_from_the_repo_config(tmp_path, monkeypatch):
    r = _repo_with_worktree(tmp_path)
    shutil.rmtree(r.lists)
    _stage(r.wt, "x.md", "plain text\n")
    _switch(monkeypatch, None)
    _git(r.repo, "config", SWITCH_KEY, "required")
    out = _run(["--staged", "--cache-dir", str(r.cache)], r.wt)
    assert out.returncode == 3, out.stderr
    first = out.stderr.splitlines()[0]
    assert first.startswith("privacy-guard: private lists required (") and "config" in first, first
    # a global `required` is overridden by a repo-local `optional`
    glob = tmp_path / "global.gitconfig"
    glob.write_text("[founderskills]\n\tprivacyLists = required\n")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(glob))
    _git(r.repo, "config", SWITCH_KEY, "optional")
    out = _run(["--staged", "--cache-dir", str(r.cache)], r.wt)
    assert out.returncode == 0 and "no private lists here" in out.stderr, out.stderr


def test_an_explicit_missing_list_in_a_hook_mode_is_named_and_obeys_the_switch(tmp_path, monkeypatch):
    r = _repo_with_worktree(tmp_path)
    _stage(r.wt, "x.md", "plain text\n")
    missing = str(tmp_path / "absent-sources.txt")
    args = ["--staged", "--sources-file", missing, "--cache-dir", str(r.cache)]
    out = _run(args, r.wt)
    assert out.returncode == 0 and "no private lists here" in out.stderr and missing in out.stderr, out.stderr
    _switch(monkeypatch, "required")
    out = _run(args, r.wt)
    assert out.returncode == 3 and out.stderr.startswith("privacy-guard: private lists required ("), out.stderr


def test_the_absence_line_names_only_lists_that_turn_a_layer_off(tmp_path):
    r = _repo_with_worktree(tmp_path)
    _stage(r.wt, "x.md", "plain text\n")
    # no allowlist anywhere: nothing to say
    out = _run(["--staged", "--cache-dir", str(r.cache)], r.wt)
    assert out.returncode == 0 and "no private lists here" not in out.stderr, out.stderr
    # denylist missing under --no-names: nothing to say
    (r.lists / "privacy-denylist.txt").unlink()
    out = _run(["--staged", "--no-names", "--cache-dir", str(r.cache)], r.wt)
    assert out.returncode == 0 and "no private lists here" not in out.stderr, out.stderr
    # both missing under --no-names: only the sources list is named, once
    (r.lists / "privacy-private-sources.txt").unlink()
    out = _run(["--staged", "--no-names", "--cache-dir", str(r.cache)], r.wt)
    assert out.stderr.count("no private lists here") == 1, out.stderr
    assert "privacy-private-sources.txt" in out.stderr and "privacy-denylist.txt" not in out.stderr, out.stderr


def test_a_lost_entry_in_a_worktree_denylist_copy_refuses_under_the_switch(tmp_path, monkeypatch):
    r = _repo_with_worktree(tmp_path)
    copy = r.wt / "docs" / "internal"
    copy.mkdir(parents=True)
    (copy / "privacy-denylist.txt").write_text(f"{FAKE_NAME}\n{COPY_ONLY_NAME}\n")
    # an allowlist copy beside it: its note must not come before the refusal's first line
    (copy / "privacy-figure-allowlist.txt").write_text("5,555.55\n")
    _stage(r.wt, "x.md", "plain text\n")
    out = _run(["--staged", "--cache-dir", str(r.cache)], r.wt)
    assert out.returncode == 0 and "1 entry only in the copy" in out.stderr, out.stderr  # a note without it
    _switch(monkeypatch, "required")
    out = _run(["--staged", "--cache-dir", str(r.cache)], r.wt)
    assert out.returncode == 3 and out.stderr.startswith("privacy-guard: private lists required ("), out.stderr
    assert "wt/docs/internal/privacy-figure-allowlist.txt" in out.stderr, out.stderr  # still noted, after it
    assert "1 entry only in the copy" in out.stderr and "Delete the copy" in out.stderr, out.stderr
    assert "wt/docs/internal/privacy-denylist.txt" in out.stderr, out.stderr
    assert "repo/docs/internal/privacy-denylist.txt" in out.stderr, out.stderr
    _clean(out.stderr, r.private)
    assert "5,555" not in out.stderr
    # the same in an allowlist copy is only a note: ignoring it makes the guard stricter
    (copy / "privacy-denylist.txt").unlink()
    (copy / "privacy-figure-allowlist.txt").write_text("4,444.44\n")
    out = _run(["--staged", "--cache-dir", str(r.cache)], r.wt)
    assert out.returncode == 0 and "1 entry only in the copy" in out.stderr, out.stderr
    assert "4,444" not in out.stderr


def test_a_copy_that_is_not_utf8_is_handled_without_a_traceback(tmp_path, monkeypatch):
    r = _repo_with_worktree(tmp_path)
    copy = r.wt / "docs" / "internal"
    copy.mkdir(parents=True)
    (copy / "privacy-denylist.txt").write_bytes(b"Caf\xe9 Invented Holdings\n")  # Latin-1, invented
    _stage(r.wt, "x.md", "plain text\n")
    out = _run(["--staged", "--cache-dir", str(r.cache)], r.wt)
    assert out.returncode == 0 and "unreadable copy" in out.stderr, out.stderr
    assert "Traceback" not in out.stderr and "Invented" not in out.stderr, out.stderr
    _switch(monkeypatch, "required")
    out = _run(["--staged", "--cache-dir", str(r.cache)], r.wt)
    assert out.returncode == 3 and out.stderr.startswith("privacy-guard: private lists required ("), out.stderr
    assert "unreadable copy" in out.stderr and "Traceback" not in out.stderr, out.stderr


def test_an_explicit_relative_list_resolves_against_the_current_directory(tmp_path):
    r = _repo_with_worktree(tmp_path)
    shutil.rmtree(r.lists)
    (r.wt / "sub").mkdir()
    (r.wt / "sub" / "x.txt").write_text((tmp_path / "sources.txt").read_text())
    _stage(r.wt, "x.md", "the total was $1,111\n")
    out = _run(["--staged", "--no-names", "--sources-file", "sub/x.txt", "--cache-dir", str(r.cache)], r.wt)
    assert out.returncode == 1 and "[figure" in out.stderr, out.stderr


def test_outside_any_repo_the_hook_modes_stay_silent(tmp_path):
    msg = tmp_path / "MSG"
    msg.write_text("fix: a plain message\n")
    out = _run(["--commit-msg", str(msg), "--cache-dir", str(tmp_path / "c")], tmp_path)
    assert out.returncode == 0 and out.stderr == "", out.stderr


def test_the_isolation_fixture_is_what_git_reads(tmp_path, monkeypatch):
    """The fixture's lever bites: a global `required` that GIT_CONFIG_GLOBAL points at refuses."""
    repo = _scratch_repo(tmp_path)
    (repo / "a.md").write_text("plain text\n")
    _git(repo, "add", "a.md")
    _switch(monkeypatch, None)
    glob = tmp_path / "global.gitconfig"
    glob.write_text("[founderskills]\n\tprivacyLists = required\n")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(glob))
    out = _run(["--staged", "--cache-dir", str(tmp_path / "c")], repo)
    assert out.returncode == 3, out.stderr
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "_gitconfig_empty"))
    out = _run(["--staged", "--cache-dir", str(tmp_path / "c")], repo)
    assert out.returncode == 0, out.stderr


def test_main_and_worktree_share_one_cache_entry(tmp_path):
    r = _repo_with_worktree(tmp_path)
    msg = tmp_path / "MSG"
    msg.write_text("fix: handle 7,777.77 margins\n")
    for where in (r.repo, r.wt):  # both read the lists and use the index, so one file means shared
        out = _run(["--commit-msg", str(msg), "--cache-dir", str(r.cache)], where)
        assert out.returncode == 1 and "[figure" in out.stderr, (where, out.stderr)
    assert len([n for n in os.listdir(r.cache) if n.startswith("index-")]) == 1


def test_a_relative_source_root_resolves_against_the_main_checkout_root(tmp_path):
    r = _repo_with_worktree(tmp_path)
    (r.lists / "privacy-private-sources.txt").write_text("# relative\n../vault-alpha\n!skill-copy\n")
    _stage(r.w2, "x.md", "the total was $1,111\n")
    out = _run(["--staged", "--no-names", "--cache-dir", str(r.cache)], r.w2)
    assert out.returncode == 1 and "[figure" in out.stderr, out.stderr
    _stage(r.repo, "y.md", "the total was $1,111\n")
    out = _run(["--staged", "--no-names", "--cache-dir", str(r.cache)], r.repo)
    assert out.returncode == 1 and "[figure" in out.stderr, out.stderr
    assert len([n for n in os.listdir(r.cache) if n.startswith("index-")]) == 1
    spec = pg.load_sources(str(r.lists / "privacy-private-sources.txt"), base=str(r.repo))
    assert spec.roots == [os.path.normpath(str(tmp_path / "vault-alpha"))]


# ---- the resolver ---------------------------------------------------------------------------------


def _real(p) -> str:
    return os.path.realpath(str(p))


def test_resolver_finds_the_main_checkout_from_every_worktree(tmp_path, monkeypatch):
    r = _repo_with_worktree(tmp_path)
    for where in (r.repo, r.wt, r.w2):
        monkeypatch.chdir(where)
        d, how = pg.private_dir()
        assert (_real(d), how) == (_real(r.lists), "main-checkout"), where
    monkeypatch.setenv("FOUNDER_SKILLS_PRIVATE_DIR", str(tmp_path / "elsewhere"))
    assert pg.private_dir() == (str(tmp_path / "elsewhere"), "env")
    monkeypatch.delenv("FOUNDER_SKILLS_PRIVATE_DIR")
    out = tmp_path / "outside"
    out.mkdir()
    monkeypatch.chdir(out)
    assert pg.private_dir() == (os.path.join("docs", "internal"), "cwd")
    assert pg._resolve_private_dir()[2] == ""  # outside a repo: no reason, nothing to warn about
    monkeypatch.setenv("GIT_DIR", str(r.repo / ".git" / "worktrees" / "wt"))
    d, how = pg.private_dir()
    assert (_real(d), how) == (_real(r.lists), "main-checkout")
    # GIT_DIR naming the main repo's .git with cwd outside: --show-toplevel then prints the CWD, which
    # the work-tree check must reject (else the cwd's docs/internal would read as the main checkout's)
    monkeypatch.setenv("GIT_DIR", str(r.repo / ".git"))
    d, how = pg.private_dir()
    assert (_real(d), how) == (_real(r.lists), "main-checkout")


def test_a_git_without_path_format_is_not_read_as_outside_a_repo(tmp_path, monkeypatch):
    """Below git 2.31 `rev-parse --path-format` fails; inside a repo that must warn, and refuse under
    the switch, never fall to the silent "outside any repository" path."""
    r = _repo_with_worktree(tmp_path)
    real_git = shutil.which("git")
    shim_dir = tmp_path / "shim"
    shim_dir.mkdir()
    shim = shim_dir / "git"
    shim.write_text(
        "#!/bin/sh\n"
        'for a in "$@"; do case "$a" in --path-format*) echo "unknown option: $a" >&2; exit 129;; esac; done\n'
        f'exec "{real_git}" "$@"\n'
    )
    shim.chmod(0o755)
    monkeypatch.setenv("PATH", f"{shim_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.chdir(r.wt)
    d, how, reason = pg._resolve_private_dir()
    assert how == "cwd" and "git >= 2.31" in reason, (d, how, reason)
    _stage(r.wt, "x.md", "plain text\n")
    out = _run(["--staged", "--cache-dir", str(r.cache)], r.wt)
    assert out.returncode == 0 and "git >= 2.31" in out.stderr, out.stderr
    _switch(monkeypatch, "required")
    out = _run(["--staged", "--cache-dir", str(r.cache)], r.wt)
    assert out.returncode == 3 and out.stderr.startswith("privacy-guard: private lists required ("), out.stderr
    assert "git >= 2.31" in out.stderr, out.stderr


def test_resolver_runs_no_worktree_listing_from_the_main_checkout(tmp_path, monkeypatch):
    r = _repo_with_worktree(tmp_path)
    calls: list[list[str]] = []
    real_run = subprocess.run

    def logging_run(cmd, *a, **kw):
        calls.append(list(cmd))
        return real_run(cmd, *a, **kw)

    monkeypatch.setattr(pg.subprocess, "run", logging_run)
    monkeypatch.chdir(r.repo)
    assert pg.private_dir()[1] == "main-checkout"
    assert calls and not any("worktree" in c for c in calls), calls
    calls.clear()
    monkeypatch.chdir(r.wt)
    assert pg.private_dir()[1] == "main-checkout"
    assert any("worktree" in c for c in calls), calls  # control: the linked worktree does list


def test_resolver_on_a_separate_git_dir(tmp_path, monkeypatch):
    main = tmp_path / "sepmain"
    _g(tmp_path, "init", "-q", "-b", "main", "--separate-git-dir", str(tmp_path / "sep.git"), str(main))
    _git(main, "-c", "user.email=t@example.com", "-c", "user.name=T", "commit", "-q", "--allow-empty", "-m", "i")
    _git(main, "worktree", "add", "-q", "-b", "w", str(tmp_path / "sepwt"))
    monkeypatch.chdir(main)
    assert pg._resolve_private_dir()[:2] == (os.path.join(_real(main), "docs", "internal"), "main-checkout")
    monkeypatch.chdir(tmp_path / "sepwt")
    d, how, reason = pg._resolve_private_dir()
    assert how == "cwd" and d == os.path.join("docs", "internal") and reason, (d, how, reason)
    msg = tmp_path / "MSG"
    msg.write_text("fix: a plain message\n")
    out = _run(["--commit-msg", str(msg), "--cache-dir", str(tmp_path / "c")], tmp_path / "sepwt")
    assert "no main checkout found" in out.stderr, out.stderr


def test_resolver_on_a_bare_repo_with_a_worktree(tmp_path, monkeypatch):
    src = _scratch_repo(tmp_path)
    (src / "a.md").write_text("x\n")
    _git(src, "add", "a.md")
    _git(src, "commit", "-q", "-m", "i")
    _g(tmp_path, "init", "-q", "--bare", "b.git")
    _git(src, "push", "-q", str(tmp_path / "b.git"), "main")
    _git(tmp_path / "b.git", "worktree", "add", "-q", str(tmp_path / "bw"), "main")
    monkeypatch.chdir(tmp_path / "bw")
    d, how, reason = pg._resolve_private_dir()
    assert how == "cwd" and reason, (d, how, reason)


def test_resolver_on_a_submodule(tmp_path, monkeypatch):
    src = _scratch_repo(tmp_path)
    (src / "a.md").write_text("x\n")
    _git(src, "add", "a.md")
    _git(src, "commit", "-q", "-m", "i")
    sup = tmp_path / "sup"
    _g(tmp_path, "init", "-q", "-b", "main", "sup")
    _git(sup, "-c", "protocol.file.allow=always", "submodule", "add", "-q", str(src), "sm")
    monkeypatch.chdir(sup / "sm")
    assert pg._resolve_private_dir()[:2] == (os.path.join(_real(sup / "sm"), "docs", "internal"), "main-checkout")
    _git(sup / "sm", "worktree", "add", "-q", "-b", "x", str(tmp_path / "smwt"))
    monkeypatch.chdir(tmp_path / "smwt")
    d, how, _reason = pg._resolve_private_dir()
    assert (_real(d), how) == (os.path.join(_real(sup / "sm"), "docs", "internal"), "main-checkout")


# ---- the release gate's switch check ---------------------------------------------------------------


def test_check_switch(tmp_path, monkeypatch):
    r = _repo_with_worktree(tmp_path)
    _switch(monkeypatch, None)
    out = _run(["--check-switch"], r.wt)
    assert out.returncode == 3 and out.stderr.startswith("privacy-guard: private lists required ("), out.stderr
    assert f"git config --global {SWITCH_KEY} required" in out.stderr, out.stderr
    assert f"git config {SWITCH_KEY} optional" in out.stderr, out.stderr
    _switch(monkeypatch, "required")
    assert _run(["--check-switch"], r.wt).returncode == 0
    _switch(monkeypatch, "optional")
    out = _run(["--check-switch"], r.wt)
    assert out.returncode == 0 and "switch deliberately off in" in out.stderr, out.stderr
    shutil.rmtree(r.lists)
    _switch(monkeypatch, None)
    out = _run(["--check-switch"], r.wt)
    assert out.returncode == 0 and "no private lists on this machine" in out.stderr, out.stderr


# ---- the hooks, through a real `git commit` / `git push` ------------------------------------------

STUB_MARKER = "STUB-GUARD-RAN"


def _commit(where, *args):
    return _g(where, "commit", "-s", "-q", *args)


def _head(where) -> str:
    return _git(where, "rev-parse", "HEAD").strip()


def test_hooks_run_the_guard_beside_them_from_main_and_from_a_worktree(tmp_path):
    r = _repo_with_worktree(tmp_path, with_scripts=True)
    _git(r.repo, "config", "core.hooksPath", str(r.repo / "scripts" / "hooks"))
    # The worktree's own guard is a stub that passes everything: only the guard beside the hooks refuses.
    (r.wt / "scripts" / "privacy_guard.py").write_text(
        f"import sys\nprint({STUB_MARKER!r}, file=sys.stderr)\nsys.exit(0)\n"
    )
    # (a) from the main checkout
    before = _head(r.repo)
    _stage(r.repo, "x.md", "the total was $1,111\n")
    out = _commit(r.repo, "-m", "add a note")
    assert out.returncode != 0 and "[figure" in out.stderr and _head(r.repo) == before, out.stderr
    # (b) from the linked worktree, a partial commit (git uses a temporary index)
    before = _head(r.wt)
    _stage(r.wt, "y.md", "the total was $1,111\n")
    out = _commit(r.wt, "-m", "add a note", "--", "y.md")
    assert out.returncode != 0 and "[figure" in out.stderr and _head(r.wt) == before, out.stderr
    assert STUB_MARKER not in out.stderr
    _git(r.wt, "reset", "-q", "y.md")
    # (c) the commit message carries the figure
    _stage(r.wt, "z.md", "plain text\n")
    out = _commit(r.wt, "-m", "fix: handle 7,777.77 margins")
    assert out.returncode != 0 and "REJECTED by the privacy guard" in out.stderr, out.stderr
    assert STUB_MARKER not in out.stderr and _head(r.wt) == before
    # (d) a push of a commit made with --no-verify
    bare = tmp_path / "remote.git"
    _g(tmp_path, "init", "-q", "--bare", str(bare))
    _stage(r.wt, "w.md", "the total was $1,111\n")
    assert _commit(r.wt, "--no-verify", "-m", "skip hooks").returncode == 0
    out = _g(r.wt, "push", "-q", str(bare), "HEAD:refs/heads/wt")
    assert out.returncode != 0 and "pre-push: REJECTED" in out.stderr, out.stderr
    assert STUB_MARKER not in out.stderr
    assert _g(bare, "rev-parse", "--verify", "-q", "refs/heads/wt").returncode != 0
    # control: the worktree's own hooks run the worktree's guard, and the stub is noticed
    _git(r.repo, "config", "core.hooksPath", "scripts/hooks")
    _stage(r.wt, "v.md", "plain text\n")
    out = _commit(r.wt, "-m", "plain")
    assert out.returncode == 0 and STUB_MARKER in out.stderr, out.stderr


def test_hooks_with_no_guard_beside_them_fall_back_to_the_work_trees_guard(tmp_path):
    r = _repo_with_worktree(tmp_path, with_scripts=True)
    git_hooks = r.repo / ".git" / "hooks"
    for layout in ("copied", "symlinked", "hookspath-symlink"):
        shutil.rmtree(git_hooks, ignore_errors=True)
        git_hooks.mkdir()
        _g(r.repo, "config", "--unset", "core.hooksPath")
        if layout == "copied":
            for h in ("pre-commit", "commit-msg"):
                shutil.copy2(r.repo / "scripts" / "hooks" / h, git_hooks / h)
        elif layout == "symlinked":
            for h in ("pre-commit", "commit-msg"):
                os.symlink(r.repo / "scripts" / "hooks" / h, git_hooks / h)
        else:
            link = tmp_path / "hooklink"
            if not link.exists():
                os.symlink(r.repo / "scripts" / "hooks", link)
            _git(r.repo, "config", "core.hooksPath", str(link))
        for where in (r.repo, r.wt):
            before = _head(where)
            _stage(where, f"{layout}.md", "the total was $1,111\n")
            out = _commit(where, "-m", "add a note")
            assert out.returncode != 0 and "[figure" in out.stderr, (layout, where, out.stderr)
            assert "can't open file" not in out.stderr and _head(where) == before, (layout, out.stderr)
            _git(where, "reset", "-q", f"{layout}.md")
