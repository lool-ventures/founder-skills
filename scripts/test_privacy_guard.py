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

import subprocess  # noqa: E402

FAKE_QUOTE = "the zebra ledger reconciles quarterly moonbeam invoices"  # invented 8-word line


def _fake_sources(tmp_path, extra_text: str = ""):
    private = tmp_path / "vault-alpha"
    (private / "run").mkdir(parents=True)
    (private / "run" / "report.md").write_text(
        f"Revenue was $1,111 and margin 7,777.77 with a 13.3x multiple.\n{FAKE_QUOTE}\n{extra_text}"
    )
    # an excluded copy of our own code: its figures must NOT enter the index
    (private / "skill-copy").mkdir()
    (private / "skill-copy" / "x.md").write_text("ceiling 424242 lives here\n")
    cfg = tmp_path / "sources.txt"
    cfg.write_text(f"# local only\n{private}\n!skill-copy\n")
    return cfg, private


def _index(tmp_path, own_text: str = ""):
    cfg, _ = _fake_sources(tmp_path)
    spec = pg.load_sources(str(cfg))
    return pg.build_private_index(spec, own_code_texts=[own_text], cache_dir=str(tmp_path / "cache"))


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


def test_commit_msg_mode_flags_a_private_figure(tmp_path):
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
    found = pg.scan_added({cas: [(1, f"$1,111 {FAKE_QUOTE}")]}, idx, [])
    layers = {f.layer for f in found}
    assert "figure" not in layers and "verbatim" in layers


def test_cassette_recordings_skip_figure_provenance_but_not_verbatim(tmp_path):
    """A recording narrates synthetic runs in the skills' own words ("the founder's", "the deck's")."""
    idx = _index(tmp_path)
    cas = "cowork-tests/cassettes/x.cassette.json"
    line = f"a live run printed $1,111 {FAKE_QUOTE}"
    assert pg.find_figure_provenance(cas, [(1, line)]) == []
    layers = {f.layer for f in pg.scan_added({cas: [(1, line)]}, idx, [])}
    assert "figure-provenance" not in layers and "verbatim" in layers
    assert pg.find_figure_provenance("a.py", [(1, line)])  # control: outside recordings it still fires


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
