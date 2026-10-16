"""Each skill that renders with `_ui.py` carries a byte-identical copy of the plugin-root one.

Skill scripts run by path and cannot import across directories, and on some surfaces the plugin-root
`scripts/` is not mounted at all, so a page that loaded the shared module from there would fail to
render. Pages move onto the module one skill at a time: `ADOPTERS` lists the skills that have, and a
skill whose page renders with the module without being listed is caught too.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CANONICAL = REPO_ROOT / "founder-skills" / "scripts" / "_ui.py"
SKILLS = REPO_ROOT / "founder-skills" / "skills"
ADOPTERS = ("financial-model-review", "deck-review", "market-sizing", "ic-sim")


def test_the_canonical_module_exists() -> None:
    assert CANONICAL.is_file()


@pytest.mark.parametrize("skill", ADOPTERS)
def test_each_adopter_copy_equals_the_canonical_module(skill: str) -> None:
    copy = SKILLS / skill / "scripts" / "_ui.py"
    assert copy.is_file(), f"{skill} renders with _ui but carries no copy"
    assert copy.read_bytes() == CANONICAL.read_bytes(), f"{copy} drifted; copy the plugin-root file over it"


def test_every_copy_is_an_adopter_and_every_importer_has_a_copy() -> None:
    copies = sorted(p.parent.parent.name for p in SKILLS.glob("*/scripts/_ui.py"))
    assert copies == sorted(ADOPTERS)
    importers = sorted(
        {
            p.parent.parent.name
            for p in SKILLS.glob("*/scripts/*.py")
            if p.name != "_ui.py" and "import _ui" in p.read_text(encoding="utf-8")
        }
    )
    assert set(importers) <= set(ADOPTERS), f"importing _ui without a copy: {sorted(set(importers) - set(ADOPTERS))}"
