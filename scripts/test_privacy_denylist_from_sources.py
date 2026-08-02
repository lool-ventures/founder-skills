"""Tests for privacy_denylist_from_sources.py — seeds the git-ignored denylist
from local source-document filenames + run-output instruments.json figures.

No real company names/figures appear here (only synthetic placeholders). The
mechanism ships in the repo; the real names it harvests never do (they land only
in the git-ignored docs/internal/privacy-denylist.txt).

Run: uv run pytest scripts/test_privacy_denylist_from_sources.py
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

import privacy_denylist_from_sources as pds  # noqa: E402

# ---- name classification (from a filename) --------------------------------


def test_camelcase_single_token_is_auto():
    auto, review = pds.classify_filename("FooBarRx - Convertible Promissory Note.pdf")
    assert "FooBarRx" in auto
    assert "FooBarRx" not in review


def test_coined_alnum_token_is_auto():
    auto, _ = pds.classify_filename("Zeta42 Cap Table (legacy xls).xls")
    assert "Zeta42" in auto


def test_allcaps_coined_token_is_auto():
    auto, _ = pds.classify_filename("QRSMOO SAFE (tracked changes).docx")
    assert "QRSMOO" in auto


def test_multiword_capitalized_phrase_is_auto():
    # A parenthesized investor phrase inside the filename.
    auto, _ = pds.classify_filename("FooBarRx - Convertible Note (Placeholder Capital II).pdf")
    assert "Placeholder Capital II" in auto


def test_plain_common_word_goes_to_review_not_auto():
    # A bare, plausibly-common single word must NOT be auto-added (would
    # false-positive as a denylist entry); it is surfaced for human review.
    auto, review = pds.classify_filename("Rivers - Series B Term Sheet.pdf")
    assert "Rivers" not in auto
    assert "Rivers" in review


def test_public_reference_name_not_emitted():
    # A publicly-referenced firm (law firm / standard body) that appears in a
    # source filename must NOT be denylisted — it is legitimately cited in the
    # repo's domain material and would false-positive there.
    auto, review = pds.classify_filename(
        "NakCo Robotics Ltd - Cap Table (Placeholder Firm 06SEP22).pdf", allowlist={"placeholder firm"}
    )
    joined = " ".join(auto | review).lower()
    assert "placeholder firm" not in joined


def test_generic_cap_table_terms_dropped_entirely():
    auto, review = pds.classify_filename("SAFE (clean).docx")
    assert auto == set()
    assert review == set()


def test_generic_terms_dropped_from_multiword():
    auto, _ = pds.classify_filename("Zed Corp - Series C Pro-Forma Cap Table.xlsx")
    # "Series", "Pro-Forma", "Cap", "Table" are generic and must not appear.
    joined = " ".join(auto)
    for g in ("Series", "Forma", "Cap", "Table"):
        assert g not in joined.split()


# ---- distinctive figures (from instruments.json) --------------------------


def test_figure_forms_emits_plain_comma_underscore():
    assert pds.figure_forms(1234567.89) == {"1234567.89", "1,234,567.89", "1_234_567.89"}


def test_integer_figure_forms():
    assert pds.figure_forms(1234567) == {"1234567", "1,234,567", "1_234_567"}


def test_distinctive_figures_keeps_cents_drops_round():
    instruments = {
        "convertible_notes": [
            {"principal": 1234567.89, "valuation_cap": 5_000_000},  # cents vs round
        ],
        "safes": [{"purchase_amount": 2_500_000}],  # round -> dropped
    }
    figs = pds.distinctive_figures(instruments)
    assert "1,234,567.89" in figs
    assert "1234567.89" in figs
    # round millions are synthetic-common -> not distinctive -> not harvested
    assert "5,000,000" not in figs
    assert "2,500,000" not in figs


def test_distinctive_figures_keeps_long_nonround_integer():
    figs = pds.distinctive_figures({"x": 1234567})  # 7 digits, non-round
    assert "1,234,567" in figs


# ---- source-root resolution (no hardcoded path) ---------------------------


def test_read_source_roots_prefers_cli_args(tmp_path):
    d = tmp_path / "srcs"
    d.mkdir()
    roots = pds.read_source_roots(cli_roots=[str(d)], config_path=str(tmp_path / "nope.txt"))
    assert roots == [str(d)]


def test_read_source_roots_reads_config_when_no_args(tmp_path):
    d = tmp_path / "srcs"
    d.mkdir()
    cfg = tmp_path / "privacy-sources.txt"
    cfg.write_text(f"# roots\n{d}\n")
    roots = pds.read_source_roots(cli_roots=[], config_path=str(cfg))
    assert roots == [str(d)]


def test_read_source_roots_none_configured_is_empty(tmp_path):
    # No CLI args, no config file -> empty (the CLI must then error, never
    # silently fall back to a hardcoded default path).
    assert pds.read_source_roots(cli_roots=[], config_path=str(tmp_path / "absent.txt")) == []


# ---- denylist merge (preserve manual, regenerate auto block) --------------


def test_merge_preserves_manual_and_is_idempotent():
    manual = "# header\nManualName\n"
    once = pds.merge_denylist(manual, auto_names={"FooBarRx"}, figures={"1,234,567.89"}, review_names={"Rivers"})
    assert "# header" in once
    assert "ManualName" in once
    assert "FooBarRx" in once
    assert "1,234,567.89" in once
    assert "#REVIEW Rivers" in once or "# REVIEW Rivers" in once
    # Regenerating over the prior output must not duplicate the auto block.
    twice = pds.merge_denylist(once, auto_names={"FooBarRx"}, figures={"1,234,567.89"}, review_names={"Rivers"})
    assert twice.count("FooBarRx") == 1
    assert twice.count("ManualName") == 1


def test_harvest_figures_from_instruments_json(tmp_path):
    root = tmp_path / "run"
    (root / "sub").mkdir(parents=True)
    (root / "sub" / "instruments.json").write_text(json.dumps({"convertible_notes": [{"principal": 1234567.89}]}))
    auto_names, review_names, figures = pds.harvest([str(root)])
    assert "1,234,567.89" in figures


def test_harvest_skips_repo_mount_segments(tmp_path):
    # instruments.json inside a mounted repo copy must NOT be harvested (else the
    # repo's own synthetic fixtures get denylisted and self-block).
    mount = tmp_path / "run" / "work" / "session" / "mnt" / ".local-plugins" / "x"
    mount.mkdir(parents=True)
    (mount / "instruments.json").write_text(json.dumps({"safes": [{"purchase_amount": 9876543.21}]}))
    _a, _r, figures = pds.harvest([str(tmp_path / "run")])
    assert "9,876,543.21" not in figures
