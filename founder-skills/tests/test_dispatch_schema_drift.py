"""Guard against a dispatch template instructing a shape nothing consumes.

A sub-agent returns what its dispatch template asks for. When the template names a field that no
producer reads and no schema declares, the sub-agent does work whose result cannot reach the founder —
paid for, discarded, and invisible because the run still succeeds.

Both prompt surfaces are checked: `SKILL.md` and `agents/<skill>.md`. The agent body carries most of
the return-shape templates (43 of 48 measured across the fleet), so checking SKILL.md alone would miss
almost all of them.

TWO WAYS THIS CHECK CAN LIE, both handled:

  * A field consumed by JSON-SCHEMA validation is never named in Python. cap-table validates against
    `references/schemas/*.json`, so its `acquired_entity` is consumed without any source literal.
    Schema files therefore count as consumers.
  * Hand-off, gate-protocol and receipt fields (`output_path`, `needs_input`, `question`) are transport,
    not artifact content, and no artifact schema should describe them.

A key that survives both is either real drift or a deliberate reasoning-scaffold field — one that
informs the sub-agent's own judgement and is not meant to be rendered. The latter must be declared in
`_SCAFFOLD` below with a reason, which is what keeps this test from becoming a rubber stamp.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILLS = [
    "ic-sim",
    "market-sizing",
    "deck-review",
    "financial-model-review",
    "cap-table",
    "competitive-positioning",
]

# Transport, not artifact content.
_PROTOCOL = frozenset(
    {
        "attempted",
        "output_path",
        "needs_input",
        "question",
        "options",
        "reason",
        "gate_state_path",
        "context_summary",
        "run_id",
        "review_dir",
        "path",
        "status",
        "ok",
        "bytes",
        "error",
    }
)

# Fields a template asks for that exist to shape the SUB-AGENT's reasoning, not to be rendered or
# validated. Each needs a reason. Adding a key here is a decision, not a formality: the alternative is
# to render it or to stop asking for it.
_SCAFFOLD: dict[str, dict[str, str]] = {
    "competitive-positioning": {
        "monetization": (
            "part of the buyer/job/category/monetization characterization the substitution test runs "
            "on; rendering every characterization in full would bury the verdict it supports"
        ),
        "suggested_axes": (
            "documented informational-only in artifact-schemas.md — it informs the agent's axis "
            "selection and is deliberately not copied into positioning.json"
        ),
    },
    "cap-table": {
        "evidence": (
            "show-your-work grounding on a detected spreadsheet block; recorded for audit, not yet "
            "enforced by the mapper"
        ),
    },
}


def _template_keys(skill: str) -> set[str]:
    """Field names appearing in any JSON return-shape template on either prompt surface."""
    keys: set[str] = set()
    for path in (
        REPO_ROOT / "founder-skills" / "agents" / f"{skill}.md",
        REPO_ROOT / "founder-skills" / "skills" / skill / "SKILL.md",
    ):
        text = path.read_text(encoding="utf-8")
        for block in re.findall(r"^```json\n(.*?)^```", text, re.S | re.M):
            keys |= set(re.findall(r'"([a-z][a-z0-9_]*)"\s*:', block))
    return keys


def _consumer_names(skill: str) -> set[str]:
    """Every field name any producer script or JSON schema for this skill refers to."""
    names: set[str] = set()
    scripts = REPO_ROOT / "founder-skills" / "skills" / skill / "scripts"
    for py in scripts.glob("*.py"):
        text = py.read_text(encoding="utf-8")
        names |= set(re.findall(r'"([a-z][a-z0-9_]*)"', text))
        names |= set(re.findall(r"'([a-z][a-z0-9_]*)'", text))

    schemas = REPO_ROOT / "founder-skills" / "skills" / skill / "references" / "schemas"
    if schemas.is_dir():
        for js in schemas.glob("*.json"):
            try:
                doc = json.loads(js.read_text(encoding="utf-8"))
            except json.JSONDecodeError:  # pragma: no cover - a malformed schema is its own failure
                continue
            names |= _schema_property_names(doc)
    return names


def _schema_property_names(node: object) -> set[str]:
    out: set[str] = set()
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "properties" and isinstance(value, dict):
                out |= {k for k in value if isinstance(k, str)}
            if key == "required" and isinstance(value, list):
                out |= {v for v in value if isinstance(v, str)}
            out |= _schema_property_names(value)
    elif isinstance(node, list):
        for item in node:
            out |= _schema_property_names(item)
    return out


@pytest.mark.parametrize("skill", SKILLS)
def test_no_dispatch_template_field_is_unconsumed(skill: str) -> None:
    template = _template_keys(skill)
    # Non-vacuity: a template set that failed to parse would pass trivially.
    assert len(template) >= 10, f"{skill}: only {len(template)} template field(s) found — parsing broke"

    orphans = sorted(template - _PROTOCOL - _consumer_names(skill) - set(_SCAFFOLD.get(skill, {})))
    assert not orphans, (
        f"{skill}: dispatch template(s) ask a sub-agent for field(s) that no producer reads and no "
        f"schema declares: {orphans}. Either consume them, stop asking for them, or declare them in "
        f"_SCAFFOLD with a reason. A sub-agent doing work that cannot reach the founder is the defect "
        f"this test exists to catch."
    )


@pytest.mark.parametrize("skill", SKILLS)
def test_scaffold_declarations_are_still_needed(skill: str) -> None:
    """A declared scaffold field that is now consumed must lose its declaration.

    Otherwise `_SCAFFOLD` accumulates stale entries and starts hiding real drift.
    """
    declared = set(_SCAFFOLD.get(skill, {}))
    if not declared:
        pytest.skip(f"{skill} declares no scaffold fields")
    consumed = _consumer_names(skill) | _PROTOCOL
    stale = sorted(declared & consumed)
    assert not stale, (
        f"{skill}: _SCAFFOLD still declares {stale}, but something now consumes them. Remove the "
        f"declaration so the exemption does not outlive its reason."
    )


@pytest.mark.parametrize("skill", SKILLS)
def test_scaffold_fields_actually_appear_in_a_template(skill: str) -> None:
    """An exemption for a field no template asks for is dead weight that masks nothing."""
    declared = set(_SCAFFOLD.get(skill, {}))
    if not declared:
        pytest.skip(f"{skill} declares no scaffold fields")
    missing = sorted(declared - _template_keys(skill))
    assert not missing, f"{skill}: _SCAFFOLD declares {missing}, which no dispatch template mentions"


def test_every_scaffold_entry_carries_a_reason() -> None:
    for skill, entries in _SCAFFOLD.items():
        for field, reason in entries.items():
            assert len(reason.strip()) > 30, f"{skill}.{field} needs a real reason, got {reason!r}"
