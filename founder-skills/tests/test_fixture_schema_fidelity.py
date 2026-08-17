#!/usr/bin/env python3
"""Test fixtures must be shapes production can actually produce.

WHY THIS FILE EXISTS. Across two review rounds, three defects survived because a fixture I
wrote did not match what production writes, and the test built on it therefore proved
something about a shape that does not occur:

  * `_inventory_numerals` read `summary`/`content`/`text` while the schema requires
    `content_summary`, so the no-figures fuse counted zero numerals on every real deck. The
    test that was meant to prove it armed fabricated a `summary` key.
  * A gate fixture carried `confirmed_stage: "series_a"` on an `out_of_scope_choice` gate —
    a record no writer can produce, since that gate is only emitted for out-of-scope
    stages. It made an authorization rule that refused the documented flow look correct.
  * A `stage_choice` fixture offered the stage the founder had just rejected, freezing a
    broken option contract as valid.

Each was found by a reviewer reading production and comparing. That comparison is mechanical
where a schema exists, so it belongs here rather than in a habit. The rule: a fixture
representing a schema-governed artifact must validate against that schema.

This cannot catch cross-field contracts a JSON schema does not express (the gate/stage
pairing above is enforced in `gate_state.py emit` instead). It does catch every case where a
fixture names a field production does not have, which is the class that keeps recurring.

Run: uv run pytest founder-skills/tests/test_fixture_schema_fidelity.py -q
"""

from __future__ import annotations

import json
import pathlib

import pytest
from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

HERE = pathlib.Path(__file__).parent
REPO_ROOT = HERE.parent.parent
SKILLS = REPO_ROOT / "founder-skills" / "skills"

# On-disk fixture sets, mapped to the schema that governs them. Only artifacts with a schema
# are listed; a fixture with no schema has nothing to be checked against.
_FIXTURE_DIRS = sorted((HERE / "fixtures").glob("*/"))


def _schema_for(skill: str, artifact: str) -> pathlib.Path | None:
    stem = artifact.removesuffix(".json")
    candidate = SKILLS / skill / "references" / "schemas" / f"{stem}.schema.json"
    return candidate if candidate.is_file() else None


def _fixture_cases() -> list[tuple[str, pathlib.Path, pathlib.Path]]:
    cases: list[tuple[str, pathlib.Path, pathlib.Path]] = []
    for fixture_dir in _FIXTURE_DIRS:
        skill = fixture_dir.name
        if not (SKILLS / skill).is_dir():
            continue
        for artifact in sorted(fixture_dir.glob("*.json")):
            schema = _schema_for(skill, artifact.name)
            if schema is not None:
                cases.append((f"{skill}/{artifact.name}", artifact, schema))
    return cases


_CASES = _fixture_cases()


def test_the_sweep_reaches_real_fixtures() -> None:
    """Non-vacuity. A sweep that pairs nothing passes by checking nothing — which is the
    exact failure mode this file was written to close, so it must not have it."""
    assert len(_CASES) >= 12, f"only {len(_CASES)} fixture/schema pairs found: {[c[0] for c in _CASES]}"
    # Two skills today: only cap-table and deck-review publish a per-artifact schema whose
    # stem matches the fixture filename. Asserted at the real number rather than an
    # aspirational one — a non-vacuity check that is itself wrong teaches nothing.
    skills = {case[0].split("/")[0] for case in _CASES}
    assert skills == {"cap-table", "deck-review"}, (
        f"the set of schema-governed fixture dirs changed: {sorted(skills)} — if a skill gained "
        "per-artifact schemas its fixtures are now covered, which is good; update this."
    )


@pytest.mark.parametrize(("label", "fixture", "schema"), _CASES, ids=[c[0] for c in _CASES])
def test_fixture_validates_against_its_schema(label: str, fixture: pathlib.Path, schema: pathlib.Path) -> None:
    document = json.loads(fixture.read_text(encoding="utf-8"))
    validator = Draft202012Validator(json.loads(schema.read_text(encoding="utf-8")))
    errors = sorted(validator.iter_errors(document), key=lambda e: list(e.absolute_path))
    assert not errors, f"{label} does not match {schema.name}:\n" + "\n".join(
        f"  {list(e.absolute_path) or '<root>'}: {e.message}" for e in errors[:8]
    )
