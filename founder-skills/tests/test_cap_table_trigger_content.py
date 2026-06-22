"""Pins the cap-table skill's broadened trigger cues.

The cap-table SKILL.md frontmatter (description + when_to_use) fires on
conversational / eligibility questions — a single instrument described in
chat, a bare yes/no, a quick gut-check, or a lone QSBS / Israeli §102 date —
not only when a founder uploads a document and asks to model a round.

This test asserts those trap-topic and conversational cues are still present
in the combined description + when_to_use text, so a future budget-trim edit
cannot silently re-narrow the gate back to a document-centric phrasing while
CI stays green.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_MD = REPO_ROOT / "founder-skills" / "skills" / "cap-table" / "SKILL.md"


def _split_frontmatter(text: str) -> dict:
    """Return the parsed YAML frontmatter dict. Raises on missing frontmatter."""
    match = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    if not match:
        raise AssertionError("cap-table SKILL.md is missing YAML frontmatter")
    return yaml.safe_load(match.group(1)) or {}


def _trigger_text() -> str:
    """Combined, lowercased description + when_to_use from the cap-table SKILL.md."""
    fm = _split_frontmatter(SKILL_MD.read_text(encoding="utf-8"))
    desc = fm.get("description", "") or ""
    wtu = fm.get("when_to_use", "") or ""
    assert desc, "cap-table SKILL.md frontmatter has no 'description'"
    assert wtu, "cap-table SKILL.md frontmatter has no 'when_to_use'"
    return (desc + "\n" + wtu).lower()


# Each entry: (concept_label, substring_that_must_be_present).
# Substrings were verified present in the current SKILL.md frontmatter; they
# are the stable cues that broaden the trigger beyond document-modeling.
_TRAP_TOPIC_CUES = [
    ("QSBS eligibility", "qsbs"),
    ("Israeli §102 timing", "§102"),
    ("post-money denominator", "denominator"),
    ("anti-dilution", "anti-dilution"),
    ("MFN chains", "mfn"),
]

_CONVERSATIONAL_CUES = [
    ("quick gut-check", "gut-check"),
    ("single instrument in chat", "single instrument"),
]


@pytest.mark.parametrize("label,cue", _TRAP_TOPIC_CUES, ids=[c[0] for c in _TRAP_TOPIC_CUES])
def test_trap_topic_cue_present(label: str, cue: str) -> None:
    """The trap-topic cue must survive in description + when_to_use.

    Dropping any of these would re-narrow the skill so it no longer fires on
    the eligibility / mechanic questions that carry the worst miscalculation
    and reliance traps.
    """
    text = _trigger_text()
    assert cue in text, (
        f"cap-table trigger no longer mentions '{label}' "
        f"(missing cue {cue!r} in description + when_to_use). "
        f"The trap-topic trigger was silently re-narrowed."
    )


@pytest.mark.parametrize("label,cue", _CONVERSATIONAL_CUES, ids=[c[0] for c in _CONVERSATIONAL_CUES])
def test_conversational_cue_present(label: str, cue: str) -> None:
    """A conversational cue must survive so the gate stays chat-firable.

    These keep the skill firing on a single instrument or a quick yes/no asked
    in chat — without them the trigger collapses back to the document-centric
    'founder shares a document and asks to model a round' phrasing.
    """
    text = _trigger_text()
    assert cue in text, (
        f"cap-table trigger no longer mentions '{label}' "
        f"(missing cue {cue!r} in description + when_to_use). "
        f"The conversational trigger was silently re-narrowed to document-only."
    )


def test_gate_is_not_purely_document_centric() -> None:
    """At least one explicit conversational entry-point must be present.

    Guards against a revert to the old document-only phrasing. The trigger must
    invite a bare yes/no, a chat-described instrument, or a gut-check — not only
    an uploaded SAFE/term sheet/spreadsheet.
    """
    text = _trigger_text()
    conversational_markers = ("yes/no", "described in chat", "gut-check", "single instrument")
    present = [m for m in conversational_markers if m in text]
    assert present, (
        "cap-table trigger has no conversational entry-point cue "
        f"(none of {conversational_markers!r} found). It reads as document-centric "
        "only — the broadened, chat-firable gate was reverted."
    )
