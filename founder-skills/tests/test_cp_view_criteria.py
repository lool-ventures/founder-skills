"""competitive-positioning's checklist wording (`_cp_view.criterion_text` and its neighbours).

report.md's "Analysis checklist" section and both pages show the assessor's evidence through one owner. These
pin what that owner does to it: ids become labels, our dispatch-context words become plain words, and a
sentence naming a file by an internal-looking filename is dropped with a marker that never says whose file it
was. And that it fails closed: with the policy unreachable, no evidence is shown at all.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

HERE = Path(__file__).resolve().parent
PLUGIN = HERE.parent
SCRIPTS = PLUGIN / "skills" / "competitive-positioning" / "scripts"
CRITERIA_MD = PLUGIN / "skills" / "competitive-positioning" / "references" / "checklist-criteria.md"
FIXTURE = HERE / "fixtures" / "competitive-positioning" / "checklist.json"


def _load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


VIEW = _load("_cp_view_criteria_test", SCRIPTS / "_cp_view.py")
LABELS = {"POS_05": "Positioning claims are stress-tested", "COVER_01": "Minimum 5 competitors identified"}


def test_category_names_equal_the_reference_headings() -> None:
    headings = re.findall(r"^## Category \d+ — (.+?) \(([A-Z]+)\)", CRITERIA_MD.read_text(encoding="utf-8"), re.M)
    assert len(headings) == 6
    assert {code: name.casefold() for name, code in headings} == {
        code: name.casefold() for code, name in VIEW.CATEGORY_NAMES.items()
    }


def test_the_id_pattern_equals_the_delivery_gates() -> None:
    sys.path.insert(0, str(SCRIPTS))
    try:
        verify = _load("_cp_verify_criteria_test", SCRIPTS / "verify_positioning.py")
    finally:
        sys.path.remove(str(SCRIPTS))
    assert VIEW.CRITERION_ID_RE.pattern == verify._CRITERION_ID_RE.pattern


def test_context_words_cover_every_competitive_positioning_context() -> None:
    table = _load("_cp_dispatch_type_test", PLUGIN / "scripts" / "dispatch_type_check.py").CONTEXT_AGENTS
    ours = {ctx for ctx, agents in table.items() if any(a.startswith("competitive-positioning") for a in agents)}
    assert ours, "no competitive-positioning context found: the table's shape changed"
    assert ours <= set(VIEW.CONTEXT_WORDS)


def test_every_fixture_id_maps_to_its_own_label() -> None:
    items = json.loads(FIXTURE.read_text(encoding="utf-8"))["items"]
    labels = VIEW.criterion_labels(items)
    assert labels == {i["id"]: " ".join(i["label"].split()) for i in items}
    for item in items:
        assert VIEW.criterion_text(f"See {item['id']}.", labels) == f"See “{labels[item['id']]}”."


def test_an_unknown_id_becomes_neutral_words() -> None:
    """An id the run's checklist does not carry has no label; the delivery gate fails on a bare id in report.md,
    and a founder cannot look it up, so it reads as plain words."""
    assert VIEW.criterion_text("As MOAT_99 notes, this holds.", LABELS) == "As another check notes, this holds."


def test_context_words_become_plain_words() -> None:
    out = VIEW.criterion_text("The POSITIONING_SCORING step and RED_TEAM agree.", LABELS)
    assert out == "The positioning scoring step and the outside review agree."
    assert VIEW.criterion_text("So the CHECKLIST passes.", LABELS) == "So the quality check passes."


def test_a_sentence_naming_an_internal_file_is_dropped_and_its_neighbour_kept() -> None:
    out = VIEW.criterion_text("Five rivals are named. The set is in landscape.json. Pricing is public.", LABELS)
    assert "landscape.json" not in out
    assert out == (
        "Five rivals are named. Pricing is public. (One sentence was left out because it named a file by its filename.)"
    )


def test_two_dropped_sentences_are_counted() -> None:
    out = VIEW.criterion_text("A holds. See landscape.json. Also moat_scores.json agrees.", LABELS)
    assert out == "A holds. (2 sentences were left out because they named a file by its filename.)"


@pytest.mark.parametrize(
    ("text", "want"),
    [
        ("A RED_TEAM pass ran.", "An outside review pass ran."),
        ("Our CHECKLIST ran.", "Our quality check ran."),
        ("An LANDSCAPE_RESEARCH step.", "A competitor research step."),
    ],
)
def test_a_determiner_before_a_context_word_is_kept_once(text: str, want: str) -> None:
    assert VIEW.criterion_text(text, LABELS) == want


def test_an_unknown_id_opening_a_sentence_is_capitalised_and_stays_its_own_sentence() -> None:
    assert VIEW.criterion_text("COVER_99 was skipped. Fine.", LABELS) == "Another check was skipped. Fine."
    out = VIEW.criterion_text("See landscape.json. COVER_99 was skipped.", LABELS)
    assert out.startswith("Another check was skipped."), out


def test_a_capitalised_internal_file_is_dropped_too() -> None:
    out = VIEW.criterion_text("Landscape.json lists six. Good spread.", LABELS)
    assert "Landscape.json" not in out and out.startswith("Good spread.")


def test_a_mode_gated_row_reads_in_plain_words() -> None:
    out = VIEW.criterion_text("Auto-gated: not applicable in conversation mode", LABELS)
    assert out == "Not applicable: this analysis was run from a conversation, with no document."


def test_a_row_whose_only_sentence_is_dropped_prints_the_empty_note() -> None:
    assert VIEW.criterion_text("Read positioning_scores.json for this.", LABELS) == VIEW.EVIDENCE_DROPPED_ALL


@pytest.mark.parametrize(
    "text",
    [
        "Rivals, e.g. a rival with scale, were named.",
        "Rivals, E.g. a rival with scale, were named.",
        "Rival A vs. Rival B is close.",
        "Example Inc. sells it.",
    ],
)
def test_the_splitter_keeps_abbreviations_whole(text: str) -> None:
    assert VIEW.split_sentences(text) == [text]


def test_a_founder_pdf_survives_and_a_markdown_file_is_dropped_neutrally() -> None:
    assert VIEW.criterion_text("Prices come from pricing.pdf, page 2.", LABELS) == (
        "Prices come from pricing.pdf, page 2."
    )
    out = VIEW.criterion_text("The founder's notes are in competitors.md. Two rivals overlap.", LABELS)
    assert "competitors.md" not in out
    assert out.endswith("(One sentence was left out because it named a file by its filename.)")
    for marker in (out, VIEW.EVIDENCE_DROPPED_ALL):
        assert "our" not in marker.split() and "internal" not in marker


def test_private_tokens_are_humanized() -> None:
    assert "research_depth" not in VIEW.criterion_text("The research_depth was thin.", LABELS)


def test_it_fails_closed_when_the_policy_cannot_be_loaded(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delitem(sys.modules, "_founder_text", raising=False)
    monkeypatch.setattr(VIEW, "_POLICY_PATH", str(tmp_path / "missing" / "_founder_text.py"))
    items: list[dict[str, Any]] = json.loads(FIXTURE.read_text(encoding="utf-8"))["items"]
    rows = [row for group in VIEW.checklist_groups({"items": items}) for row in group["items"]]
    # A mode-gated row shows our own note, which needs no check; every row of assessor text shows none of it.
    assessed = [row for row, item in zip(rows, items, strict=True) if not item["evidence"].startswith("Auto-gated")]
    assert assessed and all(row["evidence"] == VIEW.EVIDENCE_UNCHECKED for row in assessed)
    assert "_founder_text" not in sys.modules


def test_groups_follow_the_category_order_and_count_passes() -> None:
    checklist = json.loads(FIXTURE.read_text(encoding="utf-8"))
    groups = VIEW.checklist_groups(checklist)
    codes = [g["code"] for g in groups]
    assert codes == [c for c in VIEW.CATEGORY_NAMES if c in codes]
    for group in groups:
        mine = [i for i in checklist["items"] if i["category"] == group["code"]]
        assert [row["criterion"] for row in group["items"]] == [i["id"] for i in mine]
        applicable = [i for i in mine if i["status"] != "not_applicable"]
        passed = sum(i["status"] == "pass" for i in mine)
        assert group["count_text"] == (f"{passed}/{len(applicable)} pass" if applicable else "Not applicable")
