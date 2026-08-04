"""Guard against a dispatch template instructing a shape nothing consumes.

A sub-agent returns what its dispatch template asks for. When the template names a field that no
producer reads and no schema declares, the sub-agent does work whose result cannot reach the founder —
paid for, discarded, and invisible because the run still succeeds.

Both prompt surfaces are checked (`SKILL.md` and `agents/<skill>.md`), and EVERY fenced block in them,
not only ```json ones. Templates also appear untagged and inside ```bash heredocs that write an
artifact; scanning json fences alone sees about a third of the fleet's template fields and reports the
rest as clean without looking.

FOUR WAYS THIS CHECK CAN LIE, all handled:

  * A field consumed by JSON-SCHEMA validation is never named in Python. cap-table validates against
    `references/schemas/*.json`, so its `acquired_entity` is consumed without any source literal.
    Schema files therefore count as consumers.
  * A field consumed by an embedded generator's JavaScript is not a Python string literal — fmr's
    explorer reads `c.callout`. Member-access names in script sources count as consumers.
  * A field consumed by a SHARED script (`founder-skills/scripts/`) is outside the skill's own scripts
    dir. `founder_context.py` is where market-sizing's `geography` and `sector` are read.
  * Hand-off, gate-protocol and receipt fields (`output_path`, `needs_input`, `staged`) are transport,
    not artifact content, and no artifact schema should describe them.

WHAT THIS GUARD CANNOT DO, stated so it is not relied on for more than it delivers: it detects a field
NAME nobody consumes. It cannot detect a template instructing the wrong SHAPE for a name that is
consumed elsewhere. competitive-positioning is the live example — the authoring shape is nested
(`x_axis: {rationale}`) while `positioning_scores.json`'s own normalized shape is the sibling
(`x_axis_rationale`, emitted by score_positioning.py and read by compose_report.py). The sibling name is
therefore legitimately present downstream, so a template regressing to it would look consumed. Excluding
`_axis_compat.py` from the consumer set does not fix that on its own. The specific regression is caught
by a direct assertion on the templates instead (see the axis-shape test at the end of this module).

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
        "staged",
    }
)

# Modules that exist only to tolerate an obsolete shape. Excluded from the consumer set so a shim
# cannot be the sole reason a field looks consumed. Note this is necessary but not sufficient — see the
# module docstring on shape-level drift.
_COMPAT_MODULES = frozenset({"_axis_compat.py"})

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
        "merged": (
            "state flag on a gap-detection suggestion, driving the main thread's decision whether to "
            "fold it into competitors[]; not artifact content"
        ),
        "partial_profile": (
            "sketch behind that same merge decision; once merged the competitor carries a full profile "
            "whose research_depth is rendered"
        ),
    },
    "market-sizing": {
        **{
            field: (
                "founder-context field the CHECKLIST sub-agent grades against rather than a producer "
                "reading it; a real run's checklist cites these by name in its evidence"
            )
            for field in (
                "product_description",
                "target_segments",
                "pricing_model",
                "revenue_model",
                "competitive_landscape_notes",
                "gtm_evidence_notes",
                "projections_alignment_notes",
            )
        },
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
        # EVERY fence, not just ```json: templates appear untagged and inside ```bash heredocs.
        for block in re.findall(r"^```[a-z]*\n(.*?)^```", text, re.S | re.M):
            keys |= set(re.findall(r'"([a-z][a-z0-9_]*)"\s*:', block))
    return keys


def _consumer_names(skill: str) -> set[str]:
    """Every field name any producer script or JSON schema for this skill refers to."""
    names: set[str] = set()
    script_dirs = [
        REPO_ROOT / "founder-skills" / "skills" / skill / "scripts",
        REPO_ROOT / "founder-skills" / "scripts",  # shared producers
    ]
    for scripts in script_dirs:
        for py in scripts.glob("*.py"):
            if py.name in _COMPAT_MODULES:
                continue
            text = py.read_text(encoding="utf-8")
            names |= set(re.findall(r'"([a-z][a-z0-9_]*)"', text))
            names |= set(re.findall(r"'([a-z][a-z0-9_]*)'", text))
            # Member access, for fields read by an embedded generator's JavaScript.
            names |= set(re.findall(r"\.([a-z][a-z0-9_]*)\b", text))

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


# ---------------------------------------------------------------------------
# Axis rationale shape — the one drift the orphan guard structurally cannot see
# ---------------------------------------------------------------------------

_AXIS_SIBLINGS = ("x_axis_rationale", "y_axis_rationale")


def test_positioning_templates_instruct_the_nested_axis_shape() -> None:
    """Templates must ask for `x_axis: {name, rationale}`, never the flat sibling.

    Blank axis rationales in a delivered report came from templates instructing the sibling form while
    the reader expected the nested one. The orphan guard cannot catch a recurrence: the sibling name is
    the internal normalized shape of positioning_scores.json, so it reads as consumed. This asserts on
    the templates directly.
    """
    for path in (
        REPO_ROOT / "founder-skills" / "agents" / "competitive-positioning.md",
        REPO_ROOT / "founder-skills" / "skills" / "competitive-positioning" / "SKILL.md",
    ):
        text = path.read_text(encoding="utf-8")
        for block in re.findall(r"^```[a-z]*\n(.*?)^```", text, re.S | re.M):
            for sibling in _AXIS_SIBLINGS:
                assert f'"{sibling}"' not in block, (
                    f"{path.name} instructs the obsolete flat `{sibling}` in a template. The authoring "
                    f'shape is nested: "x_axis": {{"name": ..., "rationale": ...}}. Instructing the '
                    f"sibling is what left axis rationales blank in a delivered report."
                )


def test_the_nested_axis_shape_is_actually_present_in_a_template() -> None:
    """Non-vacuity: the test above passes trivially if no template mentions axes at all."""
    agent = (REPO_ROOT / "founder-skills" / "agents" / "competitive-positioning.md").read_text(encoding="utf-8")
    skill = (REPO_ROOT / "founder-skills" / "skills" / "competitive-positioning" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    combined = agent + skill
    assert '"x_axis": {"name"' in combined or '"x_axis": {' in combined, (
        "no template instructs the nested axis shape, so the sibling check above proves nothing"
    )
