"""Each skill's `_out_guard.py` is a byte-identical copy of the plugin-root one.

Skill scripts run by path and cannot import across directories, and a skill may run with the plugin-root
`scripts/` absent (a flat mount), so the guard every writer calls first is carried by each skill. The
plugin-root file is the canonical copy (the canonical-to-copies shape of `test_quote_match_sync.py`).
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CANONICAL = REPO_ROOT / "founder-skills" / "scripts" / "_out_guard.py"
SKILLS = REPO_ROOT / "founder-skills" / "skills"
SKILL_NAMES = (
    "deck-review",
    "market-sizing",
    "ic-sim",
    "financial-model-review",
    "competitive-positioning",
    "cap-table",
)


@pytest.mark.parametrize("skill", SKILL_NAMES)
def test_each_skill_copy_equals_the_canonical_guard(skill: str) -> None:
    copy = SKILLS / skill / "scripts" / "_out_guard.py"
    assert copy.read_bytes() == CANONICAL.read_bytes(), f"{copy} drifted; copy the plugin-root file over it"


def test_no_skill_without_a_copy() -> None:
    """A new skill with scripts gets a copy too, or this list is wrong."""
    with_scripts = sorted(p.parent.parent.name for p in SKILLS.glob("*/scripts/compose_report.py"))
    assert with_scripts == sorted(SKILL_NAMES)
