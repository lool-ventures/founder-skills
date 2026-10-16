"""The IC simulation's verdict, score and fund wording has one owner, and report.md and the page agree on it.

Two halves:

* report.md's executive summary, scorecard and fund sections, rendered in-process for the fixture and its
  variants, are byte-equal to the text frozen here by sha256. The digests are of the sections as compose writes
  them AFTER the wording moved to `_ic_view.py`. When they were taken, a render of the same variants from the
  code before the move was diffed against them, and the only differences were the two deliberate ones: the
  Partner Split line names each verdict by its decision word ("Decline", never a bare "pass"), and the
  scorecard shows each dimension's evidence whole. Each digest test also asserts the lines that matter in
  words, and on a mismatch writes the rendered section to a file it names, so a failure says what moved.
  (Digests, not committed text: the text is the report's own prose, which the privacy guard's verbatim layer
  matches against kept runs.)
* the page and report.md, built from one folder, state the same verdict and the same fund lines.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from _dom import by_attr, by_id, parse

REPO_ROOT = Path(__file__).resolve().parents[2]
TESTS = Path(__file__).resolve().parent
SCRIPTS = REPO_ROOT / "founder-skills" / "skills" / "ic-sim" / "scripts"
FIXTURE = TESTS / "fixtures" / "ic-sim"
REQUEST = TESTS / "fixtures" / "ic-sim-request" / "fund_profile_request.json"


def _load(name: str, path: Path) -> ModuleType:
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


compose = _load("ic_view_test_compose", SCRIPTS / "compose_report.py")
view = _load("ic_view_test_view", SCRIPTS / "_ic_view.py")
fund_profile = _load("ic_view_test_fund_profile", SCRIPTS / "fund_profile.py")


def _fx(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FIXTURE / name).read_text(encoding="utf-8"))
    return data


def _score(**summary: Any) -> dict[str, Any]:
    d = copy.deepcopy(_fx("score_dimensions.json"))
    d["summary"].update(summary)
    return d


def _long_evidence() -> dict[str, Any]:
    d = _score()
    d["items"][0]["evidence"] = "Long evidence. " + "x" * 190 + " | piped\nline end"
    return d


_SCORES = {
    "fixture": _score,
    "floored": lambda: _score(
        coverage_floored=True, conviction_basis={"applicable": 2, "total": 28, "sufficient": False}
    ),
    "capped": lambda: _score(coverage_capped=True),
    "hard_pass": lambda: _score(verdict="hard_pass"),
    "invest": lambda: _score(verdict="invest"),
    "pass": lambda: _score(verdict="pass"),
    "long_evidence": _long_evidence,
    "unknown": lambda: _score(verdict="some_new_token"),
}


def _request_profile() -> dict[str, Any]:
    data = json.loads(REQUEST.read_text(encoding="utf-8"))
    profile: dict[str, Any] = fund_profile.request_profile(data, "0" * 64, lambda _d: None)
    return profile


def _researched_profile() -> dict[str, Any]:
    return dict(
        copy.deepcopy(_fx("fund_profile.json")),
        mode="fund_specific",
        sources=[{"url": "https://example.com/fund", "title": "Fund site"}],
    )


_FUNDS = {"generic": lambda: _fx("fund_profile.json"), "request": _request_profile, "researched": _researched_profile}


_FROZEN = {
    "exec/fixture": "c73cd9b44eb46f70c0a04e76d74a360fa2994225f0864a57f4b05fdc26dd08d0",
    "exec/floored": "0c7635e32a13930a7ac9759895ea7678b91693b018876b13ece523a3a6c1fb8d",
    "exec/capped": "873fd5ea5e5cf6c829233510f0f1a2aec57a16c17f822a3554d9feb12eb40544",
    "exec/hard_pass": "dd57fba8c76484d1a00392c9a0c00c6a95d3a24879c341b4c3164f25875ed3c4",
    "exec/invest": "c9852978c3fb92fbc1769f39a17b6a8bb87c6458e03c4633bb53fdcb945bf6f9",
    "exec/pass": "79b71643fe90acdd72d658a5e14b0fe1ee419451c96af2c44fa989952eb270ec",
    "exec/unknown": "21b2bb67f12a7eb4441f8d5ed9701b39e3ded2a72ad777004339bb6df68192e0",
    "fund/generic": "ad0df3ef389697db3b4d3d7c6b9dc4263e72c28898ce5f27e1aefd7b3963b77a",
    "fund/request": "12d305200baca12863b04ae3b46a8bec940665008b3ba275ac2d0a0c930c2bf1",
    "fund/researched": "d03f38cc78f27a2a5a173aa807a7e98b2a6fc27c3db24b1ce5a8e198c06120e7",
    "score/fixture": "b01dc1d58cb0fd0d52e588d9334001eb872049fbe80f9e8fc45a689bd1449d7e",
    "score/long_evidence": "fbf928cbccb8d80e3e6977a24e5ba54b27cf74e9a224e8926ef8ee93b1328722",
}


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _exec(variant: str) -> str:
    text: str = compose._section_executive_summary(
        _fx("startup_profile.json"), _SCORES[variant](), _fx("discussion.json")
    )
    return text


def _assert_frozen(key: str, text: str, tmp_path: Path) -> None:
    """The digest check, with the rendered section written to a file the failure names."""
    if _sha(text) != _FROZEN[key]:
        out = tmp_path / (key.replace("/", "_") + ".md")
        out.write_text(text, encoding="utf-8")
        raise AssertionError(
            f"{key} no longer renders the frozen text; the section as rendered now is in {out}:\n{text}"
        )


# The executive summary carries no evidence, so the long-evidence variant is frozen in the scorecard only.
_EXEC_VARIANTS = sorted(v for v in _SCORES if v != "long_evidence")


@pytest.mark.parametrize("variant", _EXEC_VARIANTS)
def test_the_executive_summary_is_the_frozen_text(variant: str, tmp_path: Path) -> None:
    text = _exec(variant)
    summary = _SCORES[variant]()["summary"]
    # The lines that matter, in words, so a failure names what moved.
    assert f"**Conviction Score:** {view.score_text(summary)}% — {view.verdict_line(summary)}" in text
    assert "**Partner Split:** Visionary: Invest | Operator: More Diligence | Analyst: More Diligence" in text
    note = view.thin_basis_note(summary)
    assert (note is not None and f"*{note}*" in text) or (note is None and "Scored on" not in text)
    _assert_frozen(f"exec/{variant}", text, tmp_path)


@pytest.mark.parametrize("variant", ["fixture", "long_evidence"])
def test_the_scorecard_is_the_frozen_text(variant: str, tmp_path: Path) -> None:
    text = compose._section_scorecard(_SCORES[variant]())
    assert "| # | Category | Dimension | Status | Evidence |" in text
    assert len([line for line in text.splitlines() if re.match(r"\| \d+ \|", line)]) == 28
    _assert_frozen(f"score/{variant}", text, tmp_path)


@pytest.mark.parametrize("kind", sorted(_FUNDS))
def test_the_fund_section_is_the_frozen_text(kind: str, tmp_path: Path) -> None:
    fund = _FUNDS[kind]()
    text = compose._section_fund_profile(fund)
    for line in fund_profile.founder_lines(fund):
        assert f"\n{line}" in text
    assert f"**Check Size:** {view.check_size_text(fund)}" in text
    _assert_frozen(f"fund/{kind}", text, tmp_path)


def test_the_frozen_text_carries_the_two_deliberate_changes() -> None:
    """Non-vacuity for the freeze: the long evidence is whole (no "..."), and no Partner Split line in any
    variant carries a raw verdict value."""
    scorecard = compose._section_scorecard(_SCORES["long_evidence"]())
    long_row = next(line for line in scorecard.splitlines() if "Long evidence." in line)
    assert "x" * 190 + " \\| piped line end" in long_row and "..." not in long_row
    for variant in _SCORES:
        (split,) = [line for line in _exec(variant).splitlines() if line.startswith("**Partner Split:**")]
        assert not re.search(r":\s*(invest|more_diligence|pass|hard_pass)\b", split), (variant, split)


@pytest.mark.parametrize("verdict", ["invest", "more_diligence", "pass", "hard_pass", "PASS"])
def test_partner_split_names_every_verdict_by_its_decision_word(verdict: str) -> None:
    disc = copy.deepcopy(_fx("discussion.json"))
    for pv in disc["partner_verdicts"]:
        pv["verdict"] = verdict
    text = compose._section_executive_summary(_fx("startup_profile.json"), _score(), disc)
    (split,) = [line for line in text.splitlines() if line.startswith("**Partner Split:**")]
    word = view.VERDICT_WORD[verdict.lower()]
    assert split == f"**Partner Split:** Visionary: {word} | Operator: {word} | Analyst: {word}"
    assert not re.search(r"\bpass\b", split), split


# A raw verdict value, or a bare "pass" (not the "Hard Pass" of "Decline — Hard Pass"), anywhere, code spans
# included: a value in backticks still reads as "passes the bar".
_RAW_VERDICT = re.compile(r"(?<!\w)(hard_pass|more_diligence)(?!\w)|(?<!\w)(?<![Hh]ard )(?i:pass)(?!\w)")


def _compose_md(score: dict[str, Any], disc: dict[str, Any]) -> str:
    with tempfile.TemporaryDirectory() as td:
        work = Path(td)
        for src in FIXTURE.glob("*.json"):
            (work / src.name).write_bytes(src.read_bytes())
        (work / "score_dimensions.json").write_text(json.dumps(score), encoding="utf-8")
        (work / "discussion.json").write_text(json.dumps(disc), encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, str(SCRIPTS / "compose_report.py"), "--dir", str(work), "-o", str(work / "report.json")],
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 0, proc.stderr[-600:]
        md: str = json.loads((work / "report.json").read_text(encoding="utf-8"))["report_markdown"]
        return md


@pytest.mark.parametrize(
    ("score_verdict", "consensus", "partners"),
    [
        ("pass", "hard_pass", ("pass", "hard_pass", "more_diligence")),
        ("hard_pass", "pass", ("pass", "pass", "pass")),
        ("invest", "pass", ("invest", "invest", "invest")),
    ],
)
def test_no_raw_verdict_value_reaches_report_md(score_verdict: str, consensus: str, partners: tuple[str, ...]) -> None:
    """Anywhere in report.md, not one line: the Partner Split, the Discussion Summary's consensus and
    per-partner headings, the consensus/score note and the verdict-mismatch warnings all say the decision
    word. (The whole-document founder-text pass leaves a bare "pass" alone, so no line may print it.)"""
    score = _score(verdict=score_verdict)
    disc = copy.deepcopy(_fx("discussion.json"))
    disc["consensus_verdict"] = consensus
    for pv, verdict in zip(disc["partner_verdicts"], partners, strict=True):
        pv["verdict"] = verdict
    md = _compose_md(score, disc)
    hits = [line for line in md.splitlines() if _RAW_VERDICT.search(line)]
    assert not hits, hits
    assert f"**Consensus Verdict:** {view.verdict_word(consensus)}" in md
    assert f"### Analyst: {view.verdict_word(partners[2])}" in md


def test_the_four_verdict_words_are_distinct_and_never_a_bare_pass() -> None:
    words = list(view.VERDICT_WORD.values())
    assert len(set(words)) == len(words) == 4
    assert all(not re.fullmatch(r"(?i)pass", w) for w in words)


def test_the_ring_tone_follows_the_verdict_and_its_coverage() -> None:
    def tone(**s: Any) -> str:
        return str(view.ring_tone(s))

    assert tone(verdict="invest") == "pass"
    assert tone(verdict="INVEST") == "pass"
    assert tone(verdict="more_diligence") == "warn"
    assert tone(verdict="more_diligence", coverage_capped=True) == "warn"
    assert tone(verdict="more_diligence", coverage_floored=True) == "neutral"
    assert tone(verdict="more_diligence", coverage_held=True) == "neutral"
    assert tone(verdict="pass") == tone(verdict="hard_pass") == "fail"
    assert tone(verdict="some_new_token") == "neutral"


def test_the_verdict_line_reads_an_upper_case_verdict_as_the_producer_writes_it() -> None:
    assert view.verdict_line({"verdict": "INVEST"}) == view.verdict_line({"verdict": "invest"})
    assert view.verdict_line({"verdict": " More_Diligence ", "coverage_capped": True}) == view.verdict_line(
        {"verdict": "more_diligence", "coverage_capped": True}
    )
    assert view.verdict_line({"verdict": "some_new_token"}) == "some_new_token"


# --- page and report.md from one folder -----------------------------------------------------------------


def _render(td: Path, score: dict[str, Any] | None = None, fund: dict[str, Any] | None = None) -> tuple[str, str]:
    """(report_markdown, page html) for the fixture folder with `score` / `fund` swapped in. The page has no
    staleness check, so the fund is swapped after compose."""
    work = td / "sim"
    work.mkdir()
    for src in FIXTURE.glob("*.json"):
        (work / src.name).write_bytes(src.read_bytes())
    if score is not None:
        (work / "score_dimensions.json").write_text(json.dumps(score), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(SCRIPTS / "compose_report.py"), "--dir", str(work), "-o", str(work / "report.json")],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr[-600:]
    md = json.loads((work / "report.json").read_text(encoding="utf-8"))["report_markdown"]
    if fund is not None:
        (work / "fund_profile.json").write_text(json.dumps(fund), encoding="utf-8")
    page = subprocess.run(
        [sys.executable, str(SCRIPTS / "visualize.py"), "--dir", str(work)], capture_output=True, text=True
    )
    assert page.returncode == 0, page.stderr[-600:]
    return md, page.stdout


_PAGE_VERDICTS: dict[str, dict[str, Any]] = {
    "merits": {},
    "floored": {"coverage_floored": True, "conviction_basis": {"applicable": 2, "total": 28, "sufficient": False}},
    "capped": {"coverage_capped": True},
    "hard_pass": {"verdict": "hard_pass"},
    "unknown": {"verdict": "some_new_token"},
}


def _policy() -> ModuleType:
    return _load("ic_view_test_founder_text", REPO_ROOT / "founder-skills" / "scripts" / "_founder_text.py")


@pytest.mark.parametrize("case", sorted(_PAGE_VERDICTS))
def test_the_page_states_the_verdict_report_md_states(case: str) -> None:
    score = _score(**_PAGE_VERDICTS[case])
    with tempfile.TemporaryDirectory() as td:
        md, html = _render(Path(td), score)
    doc = parse(html)
    (verdict,) = by_attr(doc, "data-verdict")
    expected = _policy().substitute(view.verdict_line(score["summary"]))
    assert verdict.text() == expected
    assert f"**Conviction Score:** {view.score_text(score['summary'])}% — {expected}" in md
    if case == "unknown":
        assert "some_new_token" not in html and "some new token" in verdict.text()


def test_a_held_verdict_rings_neutral_and_a_merits_one_warns() -> None:
    """The tone, read from the ring's `data-tone` (never from a class name)."""
    tones = {}
    for case in ("merits", "floored"):
        with tempfile.TemporaryDirectory() as td:
            _md, html = _render(Path(td), _score(**_PAGE_VERDICTS[case]))
        (ring,) = [e for e in parse(html).iter() if e.tag == "figure" and "percent" in (e.get("aria-label") or "")]
        tones[case] = ring.get("data-tone")
    assert tones == {"merits": "warn", "floored": "neutral"}


def _fund_lines_on_page(html: str) -> list[str]:
    section = by_id(parse(html), "fund")
    assert section is not None
    return [e.text() for e in by_attr(section, "data-fund-line")]


@pytest.mark.parametrize("kind", sorted(_FUNDS))
def test_the_page_shows_the_fund_lines_report_md_shows(kind: str) -> None:
    fund = _FUNDS[kind]()
    lines = fund_profile.founder_lines(fund)
    with tempfile.TemporaryDirectory() as td:
        _md, html = _render(Path(td), fund=fund)
    assert _fund_lines_on_page(html) == lines
    section = compose._section_fund_profile(fund)
    for line in lines:
        assert f"\n{line}" in section
    text = parse(html).text()
    # Never the raw mode value as text ("generic fund" / "generic-fund persona" are the owner's words).
    assert "fund_specific" not in text and not re.search(r"\bgeneric\b(?![ -]fund)", text)
    note = fund_profile.illustrative_note(fund)
    if note is not None:
        assert f"{note[0]} {note[1]}" in " ".join(text.split())
        assert f"> **{note[0]}** {note[1]}" in section


def test_the_fund_panel_says_where_the_profile_came_from() -> None:
    with tempfile.TemporaryDirectory() as td:
        _md, html = _render(Path(td), fund=_request_profile())
    req = _fund_lines_on_page(html)
    assert req[0] == "Fund: a specific fund, profile supplied with this request"
    assert any("were supplied with this request and were not researched" in line for line in req)
    assert "No sources were listed for this fund profile." in req
    with tempfile.TemporaryDirectory() as td:
        _md, html = _render(Path(td))
    generic = _fund_lines_on_page(html)
    assert generic == ["Fund: an illustrative generic fund"]
    with tempfile.TemporaryDirectory() as td:
        _md, html = _render(Path(td), fund=_researched_profile())
    assert _fund_lines_on_page(html) == ["Fund: a specific fund, profile researched for this simulation"]
