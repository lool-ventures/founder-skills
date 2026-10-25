"""competitive-positioning shows the founder's file names as uploaded, not as a cloud session stored them.

A cloud Cowork session stores each upload as `<8-hex>-<original name>`, and the outside review mirrors them
under those names. report.md, report.html and explorer.html must all show the name the founder gave the file.
The rules (every name prefixed, a batch of one needs an a-f letter, collisions keep the prefix) are
market-sizing's `_upload_names.py`, pinned in test_upload_names.py; this skill carries a byte copy."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "competitive-positioning" / "scripts"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "competitive-positioning"
RUN = "20260101T000000Z"

DECK = "85451e6d-pitch_deck (1).pdf"  # snake_case and a space: the policy rewrites `_` once stripped
STUDY = "a3b2c1d0-market & study.md"  # `&`: stripped before the page escapes it
STUDY_TEXT = "Our study counts nine hundred regional freight brokers operating in the region today."


def test_the_skill_carries_market_sizings_module_unchanged() -> None:
    ms = ROOT / "skills" / "market-sizing" / "scripts" / "_upload_names.py"
    assert (SCRIPTS / "_upload_names.py").read_bytes() == ms.read_bytes()


def _analysis(tmp_path: Path, docs: dict[str, str]) -> Path:
    d = tmp_path / "competitive-positioning-acme"
    d.mkdir(parents=True)
    for src in FIXTURES.glob("*.json"):
        if src.name == "red_team_skip.json":
            continue
        data = json.loads(src.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data.setdefault("metadata", {})["run_id"] = RUN
        if src.name == "checklist.json":
            data["items"][0]["evidence"] = f"Slide 3 of {DECK} names five competitors."
        (d / src.name).write_text(json.dumps(data), encoding="utf-8")
    mirror = d / "handoff" / RUN / "docs"
    mirror.mkdir(parents=True)
    for name, text in docs.items():
        (mirror / name).write_text(text, encoding="utf-8")
    return d


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, *args], capture_output=True, text=True, timeout=60)


def _review(d: Path, study: str = STUDY, deck: str = DECK, extra: str = "") -> None:
    finding = {
        "claim_attacked": "The analysis says no competitor covers regional freight",
        "what_is_true": f"Your own study, {study}, counts regional brokers; {deck} does not mention them.{extra}",
        "evidence_quote": "counts nine hundred regional freight brokers operating in the region",
        "source_url": f"document:{study}",
        "source_title": "Market study",
        "severity": "medium",
    }
    r = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "cp_red_team.py"),
            "--run-id",
            RUN,
            "--uploads-dir",
            str(d / "handoff" / RUN / "docs"),
            "-o",
            str(d / "redteam.json"),
        ],
        input=json.dumps({"findings": [finding], "sources_read": [study]}),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert r.returncode == 0, r.stderr[-600:]


def _skip(d: Path) -> None:
    r = _run(
        str(SCRIPTS / "record_red_team_skip.py"),
        "--reason",
        "dispatch_failed",
        "--run-id",
        RUN,
        "-o",
        str(d / "red_team_skip.json"),
    )
    assert r.returncode == 0, r.stderr


def _surfaces(d: Path) -> dict[str, str]:
    r = _run(
        str(SCRIPTS / "compose_report.py"),
        "--dir",
        str(d),
        "-o",
        str(d / "report.json"),
        "--write-md",
        str(d / "report.md"),
    )
    assert r.returncode == 0, r.stderr[-600:]
    out = {"report.md": (d / "report.md").read_text(encoding="utf-8")}
    for script, name in (("visualize.py", "report.html"), ("explore.py", "explorer.html")):
        page = _run(str(SCRIPTS / script), "--dir", str(d))
        assert page.returncode == 0, page.stderr[-600:]
        out[name] = page.stdout
    return out


def test_every_surface_shows_the_names_as_uploaded(tmp_path: Path) -> None:
    d = _analysis(tmp_path, {DECK: "deck", STUDY: STUDY_TEXT})
    _review(d)
    # The lever: the stored review and checklist really carry the prefixed names.
    stored = (d / "redteam.json").read_text(encoding="utf-8") + (d / "checklist.json").read_text(encoding="utf-8")
    assert "85451e6d-" in stored and "a3b2c1d0-" in stored
    surfaces = _surfaces(d)
    for name, text in surfaces.items():
        assert "85451e6d" not in text and "a3b2c1d0" not in text, name
    md, page, explorer = surfaces["report.md"], surfaces["report.html"], surfaces["explorer.html"]
    # report.md: the policy then writes the snake_case name in words, as it does for any such filename.
    assert "your document market & study.md" in md
    assert "(1).pdf names five competitors" in md
    assert "your document market &amp; study.md" in page
    assert "(1).pdf does not mention them" in page
    assert "(1).pdf names five competitors" in page and "(1).pdf names five competitors" in explorer
    # The review's quote is the reviewer's, byte for byte.
    assert "counts nine hundred regional freight brokers operating in the region" in md


def test_a_run_whose_review_failed_still_maps_from_its_mirror(tmp_path: Path) -> None:
    d = _analysis(tmp_path, {DECK: "deck"})
    _skip(d)
    surfaces = _surfaces(d)
    for name, text in surfaces.items():
        assert "85451e6d" not in text, name
        assert "(1).pdf names five competitors" in text, name


def test_a_batch_with_one_unprefixed_name_keeps_every_prefix(tmp_path: Path) -> None:
    d = _analysis(tmp_path, {DECK: "deck", STUDY: STUDY_TEXT, "notes.pdf": "notes"})
    _review(d)
    md = _surfaces(d)["report.md"]
    assert "a3b2c1d0-market & study.md" in md


def test_the_mapping_is_its_own_fixed_point() -> None:
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    import _upload_names  # type: ignore[import-not-found]

    mapping = _upload_names.display_map([DECK, STUDY])
    once = _upload_names.humanize(f"{DECK} and {STUDY}", mapping)
    assert once == "pitch_deck (1).pdf and market & study.md"
    assert _upload_names.humanize(once, mapping) == once


def test_humanize_tree_keeps_keys_quotes_and_corrupt_sentinels() -> None:
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    import _cp_redteam_copy  # type: ignore[import-not-found]

    mapping = {DECK: "pitch_deck (1).pdf"}
    doc: dict[str, Any] = {DECK: [DECK], "evidence_quote": DECK, "n": 3}
    assert _cp_redteam_copy.humanize_tree(doc, mapping) == {
        DECK: ["pitch_deck (1).pdf"],
        "evidence_quote": DECK,
        "n": 3,
    }
    assert _cp_redteam_copy.humanize_tree(doc, {}) is doc


def test_the_stored_review_strips_its_prose_but_never_inside_a_link(tmp_path: Path) -> None:
    plan = "c1d2e3f4-plan.pdf"
    d = _analysis(tmp_path, {DECK: "deck", STUDY: STUDY_TEXT, plan: "plan"})
    _review(d, extra=f" See {plan} and https://files.example.com/{plan} for the plan.")
    stored = json.loads((d / "redteam.json").read_text(encoding="utf-8"))
    finding = stored["findings"][0]
    assert "85451e6d" not in finding["what_is_true"]
    assert " See plan.pdf and " in finding["what_is_true"]  # prose: stripped
    assert f"https://files.example.com/{plan}" in finding["what_is_true"]  # the link: as written
    assert finding["source_url"] == f"document:{STUDY}"  # the citation keeps the stored name
