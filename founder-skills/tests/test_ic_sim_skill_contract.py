"""Drift-contract tests for the ic-sim skill.

These tests grep SKILL.md and the agent body against the producer scripts'
actual source so the dispatch prompts can never silently diverge from what
the scripts accept.

Covered contract surfaces:
1. Dimension-ID enumeration: every dimension ID cited in prose must exist in
   score_dimensions.py's canonical DIMENSION_ITEMS; evaluation-criteria.md
   category/dimension table IDs must equal the canonical set exactly.
2. Archetype enumeration: the 3 partner roles (visionary, operator, analyst) in
   SKILL.md and agent body must match fund_profile.py's VALID_ROLES; dispatch
   dispatch templates for PARTNER_ANALYSIS name each archetype explicitly.
3. Dispatch return-shape keys: DETECT_CONFLICTS, PARTNER_ANALYSIS, and
   SCORE_DIMENSIONS templates carry the keys the consuming scripts read from
   stdin; PARTNER_ANALYSIS includes verdict enum values; SCORE_DIMENSIONS
   includes status enum values.
   3a. DETECT_CONFLICTS type/severity enum values in dispatch templates must match
       detect_conflicts.py's VALID_TYPES and VALID_SEVERITIES exactly (pinned — not
       just subset; rename in script OR in template → fail).
4. No-file-writes instruction: every Context A dispatch template (DETECT_CONFLICTS,
   PARTNER_ANALYSIS, SCORE_DIMENSIONS) and the agent body's Context A section must
   explicitly forbid artifact writes; reference docs with dispatch templates carry the
   same; Context B hard-rules block must ban Bash.
5. Gate-required artifacts: compose_report.py REQUIRED_ARTIFACTS each have a
   producing step in SKILL.md; cleanup rm -f list covers per-run pipeline artifacts
   (run_id parity is the staleness guard — both extraction passes have vacuity guards).
6. No shell-variable capture of python output: each Bash call runs in a fresh shell,
   so a captured value is invisible to later calls and prose branching. Zero carve-outs.
7. Flag/choice existence: every --flag in SKILL.md bash invocations of ic-sim scripts
   must exist in that script's argparse add_argument definitions; --run-id is required
   for producer scripts; forward-looking flag scanner covers reference docs too.
8. Context B / coaching payload: POST_COMPOSE_COACHING dispatch template carries all
   coaching_payload keys compose_report.py emits (search region bounded at template's
   closing code fence so keys in Main-Thread Return prose do NOT satisfy the check);
   Context B success payload keys match what SKILL.md's Main-Thread Return section
   expects; agent body run_id-parity artifact list equals the 4 producer artifacts in
   compose_report.py's REQUIRED_ARTIFACTS.
   8a. coaching_payload schema_version: extracted from compose_report.py source at
       test time — must end with '-ic-sim' AND match the version stated in the agent
       body prose.  Two-surface sync: changing either surface alone → fail.
"""

from __future__ import annotations

import contextlib
import importlib.util
import re
import sys
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
IC_SIM_DIR = REPO_ROOT / "founder-skills" / "skills" / "ic-sim"
SKILL_MD = IC_SIM_DIR / "SKILL.md"
AGENT_MD = REPO_ROOT / "founder-skills" / "agents" / "ic-sim.md"
SCRIPTS_DIR = IC_SIM_DIR / "scripts"
REFS_DIR = IC_SIM_DIR / "references"


# ---------------------------------------------------------------------------
# Module-loading helpers (unique sys.modules keys, sys.path cleanup)
# ---------------------------------------------------------------------------

# No cross-skill helper modules in ic-sim scripts (no _artifact_writer etc.)
_SCRIPTS_DIR_LOCAL_MODULES: tuple[str, ...] = ()


def _load_script_module(script_name: str, sys_key: str) -> types.ModuleType:
    """Load a script from SCRIPTS_DIR, injecting the scripts dir on sys.path.

    sys.path is modified only for the duration of exec_module so relative
    imports resolve to the correct skill's copy. The path entry is removed
    afterwards (try/finally) to avoid polluting later imports.
    """
    path = SCRIPTS_DIR / script_name
    scripts_dir_str = str(SCRIPTS_DIR)

    saved_helpers: dict[str, types.ModuleType] = {}
    for name in _SCRIPTS_DIR_LOCAL_MODULES:
        if name in sys.modules:
            saved_helpers[name] = sys.modules.pop(name)

    sys.path.insert(0, scripts_dir_str)
    try:
        spec = importlib.util.spec_from_file_location(sys_key, path)
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        sys.modules[sys_key] = mod
        spec.loader.exec_module(mod)  # type: ignore[arg-type]
    finally:
        with contextlib.suppress(ValueError):
            sys.path.remove(scripts_dir_str)
        for name, saved_mod in saved_helpers.items():
            sys.modules[name] = saved_mod

    return mod


def _load_score_dimensions_module() -> types.ModuleType:
    return _load_script_module("score_dimensions.py", "ic_sim_score_dimensions_contract")


def _load_fund_profile_module() -> types.ModuleType:
    return _load_script_module("fund_profile.py", "ic_sim_fund_profile_contract")


def _load_detect_conflicts_module() -> types.ModuleType:
    return _load_script_module("detect_conflicts.py", "ic_sim_detect_conflicts_contract")


def _load_compose_report_module() -> types.ModuleType:
    return _load_script_module("compose_report.py", "ic_sim_compose_report_contract")


def _load_compose_discussion_module() -> types.ModuleType:
    return _load_script_module("compose_discussion.py", "ic_sim_compose_discussion_contract")


# ---------------------------------------------------------------------------
# Flag extraction helpers
# ---------------------------------------------------------------------------


def _collect_argparse_flags(script_path: Path) -> frozenset[str]:
    """Return all long-form --flag strings defined via add_argument in the script."""
    src = script_path.read_text(encoding="utf-8")
    return frozenset(re.findall(r'add_argument\([^)]*"(--[a-z][a-z_-]+)"', src))


def _extract_invocation_flags_from_text(text: str) -> dict[str, set[str]]:
    """Parse all bash blocks in text and return {script_name: set_of_flags}.

    Handles backslash continuation lines.
    """
    bash_blocks = re.findall(r"```bash\n(.*?)```", text, re.DOTALL)
    result: dict[str, set[str]] = {}
    for block in bash_blocks:
        lines = block.splitlines()
        joined_lines: list[str] = []
        current = ""
        for line in lines:
            stripped = line.rstrip()
            if stripped.endswith("\\"):
                current += " " + stripped[:-1].strip()
            else:
                current += " " + stripped.strip()
                if current.strip():
                    joined_lines.append(current.strip())
                current = ""
        if current.strip():
            joined_lines.append(current.strip())

        for line in joined_lines:
            # Attribute flags per pipe segment, not per line — a pipeline like
            # `python3 md_to_commentary.py ... | python3 insert_coaching.py --report ...`
            # must not attribute insert_coaching.py's flags to md_to_commentary.py.
            for segment in line.split("|"):
                m = re.search(r"python3[^;]*?/([a-z_]+\.py)", segment)
                if m:
                    script_name = m.group(1)
                    flags = set(re.findall(r"--[a-z][a-z_-]+", segment))
                    result.setdefault(script_name, set()).update(flags)
    return result


def _ref_docs_with_dispatch_templates() -> list[Path]:
    """Return ic-sim reference docs that contain sub-agent dispatch templates."""
    result: list[Path] = []
    for p in sorted(REFS_DIR.glob("*.md")):
        if "CONTEXT:" in p.read_text(encoding="utf-8"):
            result.append(p)
    return result


# ---------------------------------------------------------------------------
# Test 1: Dimension-ID enumeration — cited IDs must exist in DIMENSION_ITEMS
# ---------------------------------------------------------------------------


def test_dimension_id_enumeration_population_is_independent() -> None:
    """Dimension IDs cited in SKILL.md and agent body as JSON field values
    (``"id": "team_founder_market_fit"``) must all exist in score_dimensions.py's
    canonical DIMENSION_ITEMS set.

    Population is built INDEPENDENTLY of DIMENSION_ITEMS — a renamed ID in the
    script becomes a phantom the test reports explicitly.

    ic-sim's dispatch templates only show one example ID (team_founder_market_fit)
    rather than enumerating all 28 — the full enumeration lives in evaluation-criteria.md
    (tested separately by test_evaluation_criteria_md_dimension_ids_equal_canonical).
    Vacuity guard: at least 1 ID must be extracted.
    """
    mod = _load_score_dimensions_module()
    valid_ids: set[str] = {item["id"] for item in mod.DIMENSION_ITEMS}  # type: ignore[attr-defined]

    combined = SKILL_MD.read_text(encoding="utf-8") + "\n" + AGENT_MD.read_text(encoding="utf-8")
    # Extract "id": "some_snake_case_id" patterns (JSON field form in dispatch templates)
    candidates = set(re.findall(r'"id"\s*:\s*"([a-z][a-z0-9_]+)"', combined))

    assert len(candidates) >= 1, (
        'No dimension IDs found via \'"id": "..."\' pattern in SKILL.md + agent body '
        "— extraction regex may have stopped matching or templates no longer show example IDs. "
        "Expected at least 'team_founder_market_fit'."
    )

    phantoms = candidates - valid_ids
    assert not phantoms, (
        f"SKILL.md / agent body cites dimension IDs not in score_dimensions.py DIMENSION_ITEMS "
        f"(phantom): {sorted(phantoms)}"
    )


# ---------------------------------------------------------------------------
# Test 1b: evaluation-criteria.md dimension IDs must equal DIMENSION_ITEMS exactly
# ---------------------------------------------------------------------------


def test_evaluation_criteria_md_dimension_ids_equal_canonical() -> None:
    """The evaluation-criteria.md reference doc enumerates all 28 dimension IDs as
    backtick-quoted values in table rows. These must match score_dimensions.py's
    DIMENSION_ITEMS exactly — no phantom rows (ID no longer in the script),
    no missing rows (script ID with no documentation).

    Count guard: exactly 28 IDs must be found. A mutation that renames one
    produces a phantom; removing one produces a missing entry.

    The backtick-quoted table rows also include status-value rows (`concern`,
    `dealbreaker`, etc.) and SaaS metric formulas — these are filtered by
    requiring the ID to start with a known category prefix (team_, market_, etc.)
    so only actual dimension IDs are counted.
    """
    mod = _load_score_dimensions_module()
    valid_ids: set[str] = {item["id"] for item in mod.DIMENSION_ITEMS}  # type: ignore[attr-defined]

    # Extract the canonical category prefixes from DIMENSION_ITEMS
    category_prefixes = frozenset(
        item["id"].split("_")[0] + "_"
        for item in mod.DIMENSION_ITEMS  # type: ignore[attr-defined]
    )

    criteria_text = (REFS_DIR / "evaluation-criteria.md").read_text(encoding="utf-8")
    # Rows look like: | `team_founder_market_fit` | Founder-Market Fit | ...
    all_backtick_ids = set(re.findall(r"\|\s*`([a-z][a-z0-9_]+)`\s*\|", criteria_text))
    # Filter to only dimension IDs (start with a known prefix like team_, market_, etc.)
    header_ids = {i for i in all_backtick_ids if any(i.startswith(p) for p in category_prefixes)}

    assert len(header_ids) == 28, (
        f"evaluation-criteria.md has {len(header_ids)} dimension ID table rows "
        f"(expected 28); count guard catches missing or extra rows. "
        f"Prefix filter: {sorted(category_prefixes)}"
    )

    phantom = header_ids - valid_ids
    missing = valid_ids - header_ids
    assert not phantom, (
        f"evaluation-criteria.md has dimension IDs not in score_dimensions.py DIMENSION_ITEMS "
        f"(phantom — rename or remove): {sorted(phantom)}"
    )
    assert not missing, (
        f"evaluation-criteria.md is missing dimension IDs from score_dimensions.py DIMENSION_ITEMS "
        f"(missing — add a row for each): {sorted(missing)}"
    )


# ---------------------------------------------------------------------------
# Test 1c: Dimension count and category breakdown in score_dimensions.py
# ---------------------------------------------------------------------------


def test_score_dimensions_count_and_categories() -> None:
    """score_dimensions.py DIMENSION_ITEMS must contain exactly 28 items across
    7 categories with 4 items each. SKILL.md and agent body both document '28
    dimensions across 7 categories' — this count guard catches silent additions
    or deletions.
    """
    from collections import Counter

    mod = _load_score_dimensions_module()
    items: list[dict[str, str]] = mod.DIMENSION_ITEMS  # type: ignore[attr-defined]

    assert len(items) == 28, (
        f"score_dimensions.py DIMENSION_ITEMS has {len(items)} items (expected 28 per documentation)"
    )

    expected_categories = {"Team", "Market", "Product", "Business Model", "Financials", "Risk", "Fund Fit"}
    by_category: Counter[str] = Counter(item["category"] for item in items)
    assert set(by_category.keys()) == expected_categories, (
        f"score_dimensions.py categories mismatch:\n"
        f"  expected: {sorted(expected_categories)}\n"
        f"  got: {sorted(by_category.keys())}"
    )
    for cat, count in by_category.items():
        assert count == 4, f"score_dimensions.py category '{cat}' has {count} items (expected 4)"

    # SKILL.md and agent body both mention '28 dimensions across 7 categories'
    for doc, text in ((SKILL_MD, SKILL_MD.read_text()), (AGENT_MD, AGENT_MD.read_text())):
        assert "28" in text, f"{doc.name} does not mention '28' dimensions — documentation may be stale"


# ---------------------------------------------------------------------------
# Test 2: Archetype enumeration — VALID_ROLES in prose match fund_profile.py
# ---------------------------------------------------------------------------


def test_archetype_roles_in_skill_md_match_fund_profile_valid_roles() -> None:
    """The 3 partner archetype roles cited in SKILL.md and agent body must match
    fund_profile.py's VALID_ROLES exactly.

    Population extracted independently: the PARTNER_ANALYSIS dispatch template
    in SKILL.md names each archetype in its ``archetype: visionary|operator|analyst``
    form. The agent body's PARTNER_ANALYSIS subtype section names them as backtick
    tokens. Both are extracted and validated against VALID_ROLES.

    Vacuity guard: all 3 roles must be found in SKILL.md's dispatch template section.
    """
    mod = _load_fund_profile_module()
    valid_roles: frozenset[str] = frozenset(mod.VALID_ROLES)  # type: ignore[attr-defined]

    assert valid_roles == {"visionary", "operator", "analyst"}, (
        f"fund_profile.py VALID_ROLES is not the expected 3-archetype set: {sorted(valid_roles)}"
    )

    skill_text = SKILL_MD.read_text(encoding="utf-8")
    anchor = "CONTEXT: PARTNER_ANALYSIS"
    start = skill_text.find(anchor)
    assert start != -1, f"{SKILL_MD.name} has no 'CONTEXT: PARTNER_ANALYSIS' section"
    section = skill_text[start : start + 1000]

    # Extract role names from "archetype: visionary|operator|analyst" form
    # and from direct mentions
    prose_roles = set(re.findall(r"\b(visionary|operator|analyst)\b", section))

    assert len(prose_roles) == 3, (
        f"{SKILL_MD.name} PARTNER_ANALYSIS section mentions {len(prose_roles)} archetype roles "
        f"(expected all 3 visionary/operator/analyst): got {sorted(prose_roles)}"
    )

    phantom = prose_roles - valid_roles
    assert not phantom, (
        f"{SKILL_MD.name} PARTNER_ANALYSIS section cites roles not in fund_profile.py VALID_ROLES: {sorted(phantom)}"
    )

    # Also verify agent body's PARTNER_ANALYSIS subtype section names all 3
    agent_text = AGENT_MD.read_text(encoding="utf-8")
    agent_anchor = "#### PARTNER_ANALYSIS subtype"
    agent_start = agent_text.find(agent_anchor)
    assert agent_start != -1, f"{AGENT_MD.name} has no 'PARTNER_ANALYSIS subtype' section"
    agent_section = agent_text[agent_start : agent_start + 1500]
    agent_roles = set(re.findall(r"\b(visionary|operator|analyst)\b", agent_section))
    agent_phantom = agent_roles - valid_roles
    assert not agent_phantom, (
        f"{AGENT_MD.name} PARTNER_ANALYSIS subtype cites roles not in fund_profile.py VALID_ROLES: "
        f"{sorted(agent_phantom)}"
    )
    assert len(agent_roles) == 3, (
        f"{AGENT_MD.name} PARTNER_ANALYSIS subtype only mentions {sorted(agent_roles)}, expected all 3"
    )


def test_parallel_dispatch_recipe_names_all_three_archetypes() -> None:
    """SKILL.md's parallel dispatch recipe (Step 5b-d) must name all 3 archetype roles
    explicitly — one Task call per archetype. The dispatch is the novel ic-sim-specific
    contract (3 simultaneous sub-agent calls in a single assistant turn).

    Anchor: the Pseudocode block for the parallel dispatch.
    """
    skill_text = SKILL_MD.read_text(encoding="utf-8")
    anchor = "Pseudocode for the dispatch"
    start = skill_text.find(anchor)
    assert start != -1, f"{SKILL_MD.name} has no 'Pseudocode for the dispatch' section"
    # 1000-char window: the OUTPUT_PATH hand-off lines lengthened each Task call.
    section = skill_text[start : start + 1000]

    for role in ("visionary", "operator", "analyst"):
        assert role in section, f"{SKILL_MD.name} parallel dispatch pseudocode does not name archetype '{role}'"


# ---------------------------------------------------------------------------
# Test 3: Dispatch return-shape keys
# ---------------------------------------------------------------------------


def test_detect_conflicts_enum_values_match_script() -> None:
    """The 'type' and 'severity' enum values shown in the DETECT_CONFLICTS dispatch
    template (pipe-separated placeholder: 'direct|adjacent|customer_overlap') must
    match detect_conflicts.py's VALID_TYPES and VALID_SEVERITIES exactly — both
    surfaces must stay in sync.

    Two-surface sync test (mutation-resistant):
    - Rename a value in the script's VALID_TYPES or VALID_SEVERITIES → fail
      (phantom in the template's cited set, or missing from template).
    - Rename a value in the template's pipe-separated placeholder → fail
      (phantom not in the script's canonical sets).

    Extraction: the template shows placeholder values as a pipe-separated string
    inside the JSON field value position, e.g. "type": "direct|adjacent|customer_overlap".
    The test extracts these from the pipe-separated form found in the DETECT_CONFLICTS
    section of SKILL.md and the agent body (DETECT_CONFLICTS subtype section).

    Vacuity guard: at least 2 type values and at least 2 severity values must be
    extracted from each surface.
    """
    mod = _load_detect_conflicts_module()
    canonical_types: frozenset[str] = frozenset(mod.VALID_TYPES)  # type: ignore[attr-defined]
    canonical_severities: frozenset[str] = frozenset(mod.VALID_SEVERITIES)  # type: ignore[attr-defined]

    assert len(canonical_types) >= 2, "detect_conflicts.py VALID_TYPES has fewer than 2 entries — check module load"
    assert len(canonical_severities) >= 2, (
        "detect_conflicts.py VALID_SEVERITIES has fewer than 2 entries — check module load"
    )

    def _extract_pipe_enum(text: str, field_name: str) -> set[str]:
        """Extract values from '"field_name": "a|b|c"' pipe-separated placeholder."""
        m = re.search(rf'"{re.escape(field_name)}"\s*:\s*"([^"]+)"', text)
        if not m:
            return set()
        raw = m.group(1)
        return {v.strip() for v in raw.split("|") if v.strip()}

    # --- SKILL.md DETECT_CONFLICTS section ---
    skill_text = SKILL_MD.read_text(encoding="utf-8")
    anchor = "CONTEXT: DETECT_CONFLICTS"
    start = skill_text.find(anchor)
    assert start != -1, f"{SKILL_MD.name} has no '{anchor}' section"
    section = skill_text[start : start + 2000]

    skill_types = _extract_pipe_enum(section, "type")
    skill_severities = _extract_pipe_enum(section, "severity")

    assert len(skill_types) >= 2, (
        f"{SKILL_MD.name} DETECT_CONFLICTS section: extracted {len(skill_types)} type values "
        f"from pipe-separated placeholder (expected >=2); check extraction regex or template format"
    )
    assert len(skill_severities) >= 2, (
        f"{SKILL_MD.name} DETECT_CONFLICTS section: extracted {len(skill_severities)} severity values "
        f"from pipe-separated placeholder (expected >=2); check extraction regex or template format"
    )

    assert skill_types == canonical_types, (
        f"{SKILL_MD.name} DETECT_CONFLICTS type enum mismatch vs detect_conflicts.py VALID_TYPES:\n"
        f"  template: {sorted(skill_types)}\n"
        f"  script:   {sorted(canonical_types)}\n"
        f"  phantom (in template, not script): {sorted(skill_types - canonical_types)}\n"
        f"  missing (in script, not template): {sorted(canonical_types - skill_types)}"
    )
    assert skill_severities == canonical_severities, (
        f"{SKILL_MD.name} DETECT_CONFLICTS severity enum mismatch vs detect_conflicts.py VALID_SEVERITIES:\n"
        f"  template: {sorted(skill_severities)}\n"
        f"  script:   {sorted(canonical_severities)}\n"
        f"  phantom (in template, not script): {sorted(skill_severities - canonical_severities)}\n"
        f"  missing (in script, not template): {sorted(canonical_severities - skill_severities)}"
    )

    # --- Agent body DETECT_CONFLICTS subtype section ---
    agent_text = AGENT_MD.read_text(encoding="utf-8")
    agent_anchor = "#### DETECT_CONFLICTS subtype"
    agent_start = agent_text.find(agent_anchor)
    assert agent_start != -1, f"{AGENT_MD.name} has no '#### DETECT_CONFLICTS subtype' section"
    agent_section = agent_text[agent_start : agent_start + 1500]

    agent_types = _extract_pipe_enum(agent_section, "type")
    agent_severities = _extract_pipe_enum(agent_section, "severity")

    assert len(agent_types) >= 2, (
        f"{AGENT_MD.name} DETECT_CONFLICTS subtype: extracted {len(agent_types)} type values "
        f"from pipe-separated placeholder (expected >=2)"
    )
    assert len(agent_severities) >= 2, (
        f"{AGENT_MD.name} DETECT_CONFLICTS subtype: extracted {len(agent_severities)} severity values "
        f"from pipe-separated placeholder (expected >=2)"
    )

    assert agent_types == canonical_types, (
        f"{AGENT_MD.name} DETECT_CONFLICTS subtype type enum mismatch vs detect_conflicts.py VALID_TYPES:\n"
        f"  template: {sorted(agent_types)}\n"
        f"  script:   {sorted(canonical_types)}"
    )
    assert agent_severities == canonical_severities, (
        f"{AGENT_MD.name} DETECT_CONFLICTS subtype severity enum mismatch vs detect_conflicts.py VALID_SEVERITIES:\n"
        f"  template: {sorted(agent_severities)}\n"
        f"  script:   {sorted(canonical_severities)}"
    )


def test_detect_conflicts_dispatch_return_shape_keys() -> None:
    """The DETECT_CONFLICTS dispatch template in SKILL.md and the agent body must
    include the keys detect_conflicts.py reads from stdin: portfolio_size and
    conflicts (top-level), and each conflict entry's required fields:
    company, type, severity, rationale.

    Anchor on 'CONTEXT: DETECT_CONFLICTS' in SKILL.md and the DETECT_CONFLICTS
    subtype heading in the agent body.
    """
    required_keys = {"portfolio_size", "conflicts"}
    conflict_entry_fields = {"company", "type", "severity", "rationale"}

    skill_text = SKILL_MD.read_text(encoding="utf-8")
    anchor = "CONTEXT: DETECT_CONFLICTS"
    start = skill_text.find(anchor)
    assert start != -1, f"{SKILL_MD.name} has no '{anchor}' section"
    section = skill_text[start : start + 2000]
    for key in required_keys:
        assert f'"{key}"' in section, (
            f"{SKILL_MD.name} DETECT_CONFLICTS return shape missing key '{key}' "
            f"(detect_conflicts.py reads it from stdin)"
        )
    for field in conflict_entry_fields:
        assert f'"{field}"' in section, (
            f"{SKILL_MD.name} DETECT_CONFLICTS return shape missing conflict entry field '{field}'"
        )

    agent_text = AGENT_MD.read_text(encoding="utf-8")
    agent_anchor = "#### DETECT_CONFLICTS subtype"
    agent_start = agent_text.find(agent_anchor)
    assert agent_start != -1, f"{AGENT_MD.name} has no 'DETECT_CONFLICTS subtype' section"
    agent_section = agent_text[agent_start : agent_start + 1500]
    for key in required_keys:
        assert f'"{key}"' in agent_section, f"{AGENT_MD.name} DETECT_CONFLICTS subtype missing key '{key}'"


def test_partner_analysis_dispatch_return_shape_keys() -> None:
    """The PARTNER_ANALYSIS dispatch template must include the partner assessment
    object's required keys: partner, verdict, rationale, conviction_points,
    key_concerns, questions_for_founders, diligence_requirements.

    Also verifies verdict enum values (invest|more_diligence|pass|hard_pass)
    appear in the template — a renamed enum value causes compose to emit
    UNANIMOUS_VERDICT_MISMATCH warnings on every run.

    Anchor on the full PARTNER_ANALYSIS dispatch prompt template in SKILL.md.
    """
    required_keys = {
        "partner",
        "verdict",
        "rationale",
        "conviction_points",
        "key_concerns",
        "questions_for_founders",
        "diligence_requirements",
    }
    verdict_values = {"invest", "more_diligence", "pass", "hard_pass"}

    skill_text = SKILL_MD.read_text(encoding="utf-8")
    anchor = "Full dispatch prompt template"
    start = skill_text.find(anchor)
    assert start != -1, f"{SKILL_MD.name} has no 'Full dispatch prompt template' section for PARTNER_ANALYSIS"
    section = skill_text[start : start + 1500]

    for key in required_keys:
        assert f'"{key}"' in section, f"{SKILL_MD.name} PARTNER_ANALYSIS return shape missing key '{key}'"
    for val in verdict_values:
        assert val in section, f"{SKILL_MD.name} PARTNER_ANALYSIS return shape does not mention verdict value '{val}'"

    # Agent body PARTNER_ANALYSIS subtype return shape
    agent_text = AGENT_MD.read_text(encoding="utf-8")
    agent_anchor = "#### PARTNER_ANALYSIS subtype"
    agent_start = agent_text.find(agent_anchor)
    assert agent_start != -1, f"{AGENT_MD.name} has no '#### PARTNER_ANALYSIS subtype' section"
    next_heading = agent_text.find("\n#### ", agent_start + 1)
    if next_heading != -1:
        agent_section = agent_text[agent_start:next_heading]
    else:
        agent_section = agent_text[agent_start : agent_start + 2000]
    for key in required_keys:
        assert f'"{key}"' in agent_section, f"{AGENT_MD.name} PARTNER_ANALYSIS subtype return shape missing key '{key}'"


def test_score_dimensions_dispatch_return_shape_keys() -> None:
    """The SCORE_DIMENSIONS dispatch template must include the items array and
    each item's required fields (id, category, status, evidence), and must
    enumerate the status values score_dimensions.py accepts.

    Anchor on 'CONTEXT: SCORE_DIMENSIONS' in SKILL.md and the SCORE_DIMENSIONS
    subtype heading in the agent body.
    """
    mod = _load_score_dimensions_module()
    valid_statuses: set[str] = set(mod.VALID_STATUSES)  # type: ignore[attr-defined]

    skill_text = SKILL_MD.read_text(encoding="utf-8")
    anchor = "CONTEXT: SCORE_DIMENSIONS"
    start = skill_text.find(anchor)
    assert start != -1, f"{SKILL_MD.name} has no '{anchor}' section"
    # Bound on the template's own closing fence, not a character count — the
    # dispatch grows as inputs are added, and a fixed window silently starts
    # excluding the tail it is meant to be checking.
    fence = skill_text.find("\n```", start)
    section = skill_text[start : fence if fence != -1 else start + 4000]

    for key in ('"items"', '"id"', '"status"', '"evidence"'):
        assert key in section, f"{SKILL_MD.name} SCORE_DIMENSIONS return shape missing key {key}"

    # All status enum values must appear (pipe-separated or individual mentions)
    for status in valid_statuses:
        assert status in section, f"{SKILL_MD.name} SCORE_DIMENSIONS return shape does not mention status '{status}'"

    # Agent body SCORE_DIMENSIONS subtype
    agent_text = AGENT_MD.read_text(encoding="utf-8")
    agent_anchor = "#### SCORE_DIMENSIONS subtype"
    agent_start = agent_text.find(agent_anchor)
    assert agent_start != -1, f"{AGENT_MD.name} has no '#### SCORE_DIMENSIONS subtype' section"
    next_heading = agent_text.find("\n#### ", agent_start + 1)
    if next_heading != -1:
        agent_section = agent_text[agent_start:next_heading]
    else:
        agent_section = agent_text[agent_start : agent_start + 2000]
    assert '"items"' in agent_section, f"{AGENT_MD.name} SCORE_DIMENSIONS subtype missing 'items' key in return shape"
    for status in valid_statuses:
        assert status in agent_section, (
            f"{AGENT_MD.name} SCORE_DIMENSIONS subtype does not mention status value '{status}'"
        )


# ---------------------------------------------------------------------------
# Test 4: No-file-writes instruction in Context A dispatch templates
# ---------------------------------------------------------------------------


def test_context_a_dispatch_templates_contain_no_write_instruction() -> None:
    """All three Context A dispatch templates in SKILL.md must explicitly
    forbid artifact writes — a sub-agent that writes files directly bypasses
    schema validation and run_id stamping.

    All three templates are fence-bounded to ensure no-write instruction is
    checked within the template body itself regardless of template length.

    DETECT_CONFLICTS: 'CONTEXT: DETECT_CONFLICTS' anchor, fence-bounded.
    SCORE_DIMENSIONS: 'CONTEXT: SCORE_DIMENSIONS' anchor, fence-bounded
      (template grew when full ID enumeration was added — fixed-window check
      was replaced with fence-bounded to remain robust to template growth).
    PARTNER_ANALYSIS: anchored on 'Full dispatch prompt template (used for each
      archetype' — the full template heading — rather than the first 'CONTEXT:
      PARTNER_ANALYSIS' occurrence (which appears inside a pseudocode block).
    """
    skill_text = SKILL_MD.read_text(encoding="utf-8")

    # DETECT_CONFLICTS: fence-bounded search
    dc_anchor = "CONTEXT: DETECT_CONFLICTS"
    dc_start = skill_text.find(dc_anchor)
    assert dc_start != -1, f"{SKILL_MD.name} has no '{dc_anchor}' section"
    dc_open_fence = skill_text.rfind("\n```\n", 0, dc_start)
    assert dc_open_fence != -1, f"{SKILL_MD.name} DETECT_CONFLICTS: no opening fence before CONTEXT: line"
    dc_close_fence = skill_text.find("\n```\n", dc_start)
    assert dc_close_fence != -1, f"{SKILL_MD.name} DETECT_CONFLICTS: no closing fence"
    dc_section = skill_text[dc_open_fence:dc_close_fence]
    assert "Do NOT write" in dc_section or "do not write" in dc_section.lower(), (
        f"{SKILL_MD.name} DETECT_CONFLICTS dispatch template must explicitly forbid "
        f"artifact writes (schema gate bypass risk)"
    )

    # SCORE_DIMENSIONS: fence-bounded search (template now enumerates all 28 ids)
    sd_anchor = "CONTEXT: SCORE_DIMENSIONS"
    sd_start = skill_text.find(sd_anchor)
    assert sd_start != -1, f"{SKILL_MD.name} has no '{sd_anchor}' section"
    sd_open_fence = skill_text.rfind("\n```\n", 0, sd_start)
    assert sd_open_fence != -1, f"{SKILL_MD.name} SCORE_DIMENSIONS: no opening fence before CONTEXT: line"
    sd_close_fence = skill_text.find("\n```\n", sd_start)
    assert sd_close_fence != -1, f"{SKILL_MD.name} SCORE_DIMENSIONS: no closing fence"
    sd_section = skill_text[sd_open_fence:sd_close_fence]
    assert "Do NOT write" in sd_section or "do not write" in sd_section.lower(), (
        f"{SKILL_MD.name} SCORE_DIMENSIONS dispatch template must explicitly forbid "
        f"artifact writes (schema gate bypass risk)"
    )

    # PARTNER_ANALYSIS: anchor on the full-template heading so template growth
    # cannot push the no-write line outside the search window.
    pa_template_anchor = "Full dispatch prompt template"
    pa_start = skill_text.find(pa_template_anchor)
    assert pa_start != -1, (
        f"{SKILL_MD.name} has no '{pa_template_anchor}' heading for PARTNER_ANALYSIS — "
        f"re-anchor the no-write check if the heading text changed"
    )
    # Find the closing ``` fence of the template block
    pa_open_fence = skill_text.find("\n```\n", pa_start)
    assert pa_open_fence != -1, f"{SKILL_MD.name} PARTNER_ANALYSIS full template: no opening fence after heading"
    pa_close_fence = skill_text.find("\n```\n", pa_open_fence + 4)
    assert pa_close_fence != -1, f"{SKILL_MD.name} PARTNER_ANALYSIS full template: no closing fence"
    pa_section = skill_text[pa_start:pa_close_fence]
    assert "Do NOT write" in pa_section or "do not write" in pa_section.lower(), (
        f"{SKILL_MD.name} PARTNER_ANALYSIS full dispatch template must explicitly forbid "
        f"artifact writes (schema gate bypass risk)"
    )


def test_agent_body_context_a_hard_rules_contain_bash_ban_and_no_write() -> None:
    """The agent body's Context A section must:
    - Forbid writing artifacts to disk ('Do not write' or 'do not write')
    - Forbid Bash calls ('Do not call' + 'Bash')

    Anchor: '**Hard rules in Context A:**' or the equivalent in the agent body.
    """
    agent_text = AGENT_MD.read_text(encoding="utf-8")
    anchor = "### Context A"
    start = agent_text.find(anchor)
    assert start != -1, f"{AGENT_MD.name} has no '### Context A' section"
    next_section = agent_text.find("\n### Context B", start)
    section = agent_text[start:next_section] if next_section != -1 else agent_text[start : start + 6000]

    assert "do not write" in section.lower() or "Do not write" in section, (
        f"{AGENT_MD.name} Context A section must say 'Do not write artifacts'"
    )
    assert "Bash" in section and ("Do not call" in section or "do not call" in section.lower()), (
        f"{AGENT_MD.name} Context A section must forbid Bash calls"
    )


def test_agent_body_context_b_hard_rules_forbid_edits() -> None:
    """The agent body's Context B hard-rules block must forbid editing
    report.md (insertion is main-thread-only via insert_coaching.py) and
    forbid reading the full report.

    Anchor on the '**Hard rules in this context:**' subheading inside Context B
    rather than a fixed window — the section can grow without silently dropping
    the rules from range.
    """
    agent_text = AGENT_MD.read_text(encoding="utf-8")
    anchor = "### Context B"
    start = agent_text.find(anchor)
    assert start != -1, f"{AGENT_MD.name} has no '### Context B' section"

    rules_anchor = "**Hard rules in this context:**"
    rules_start = agent_text.find(rules_anchor, start)
    assert rules_start != -1, f"{AGENT_MD.name} Context B has no '**Hard rules in this context:**' block"
    rules_section = agent_text[rules_start : rules_start + 1500]

    assert "Do NOT" in rules_section, f"{AGENT_MD.name} Context B hard rules lost the 'Do NOT' phrasing"
    assert "edit_report_md" in rules_section, (
        f"{AGENT_MD.name} Context B hard rules must forbid `edit_report_md` "
        f"(insertion is script-side via insert_coaching.py)"
    )
    assert "read_full_report_md" in rules_section, (
        f"{AGENT_MD.name} Context B hard rules must forbid `read_full_report_md`"
    )


def test_ref_docs_dispatch_templates_contain_no_write_instruction() -> None:
    """Reference docs that contain dispatch templates must carry the no-write
    instruction. This test will fail loudly if a reference doc gains a dispatch
    template without the instruction.
    """
    ref_docs = _ref_docs_with_dispatch_templates()
    for ref_doc in ref_docs:
        text = ref_doc.read_text(encoding="utf-8")
        for block_start_idx in [m.start() for m in re.finditer(r"CONTEXT:", text)]:
            section = text[block_start_idx : block_start_idx + 2000]
            assert "Do NOT write" in section or "do not write" in section.lower(), (
                f"{ref_doc.name}: dispatch template at char {block_start_idx} "
                f"is missing 'Do not write artifacts' instruction"
            )


# ---------------------------------------------------------------------------
# Test 5: Gate-required artifacts and cleanup coverage
# ---------------------------------------------------------------------------


def test_required_artifacts_have_producing_steps_in_skill_md() -> None:
    """Every artifact in compose_report.py REQUIRED_ARTIFACTS must appear in
    SKILL.md — an artifact with no producing step means compose always fails
    the artifact-present gate.
    """
    mod = _load_compose_report_module()
    required: list[str] = mod.REQUIRED_ARTIFACTS  # type: ignore[attr-defined]

    skill_text = SKILL_MD.read_text(encoding="utf-8")
    missing = [name for name in required if name not in skill_text]
    assert not missing, f"compose_report.py REQUIRED_ARTIFACTS not mentioned in SKILL.md (no producing step): {missing}"


def test_compose_required_artifacts_count() -> None:
    """compose_report.py REQUIRED_ARTIFACTS must contain exactly 5 entries —
    the 5 per-step producer artifacts.
    """
    mod = _load_compose_report_module()
    required: list[str] = mod.REQUIRED_ARTIFACTS  # type: ignore[attr-defined]
    expected = {
        "startup_profile.json",
        "fund_profile.json",
        "conflict_check.json",
        "discussion.json",
        "score_dimensions.json",
    }
    assert set(required) == expected, (
        f"compose_report.py REQUIRED_ARTIFACTS mismatch:\n  expected: {sorted(expected)}\n  got: {sorted(required)}"
    )


def test_overwrite_in_place_no_outputs_delete() -> None:
    """Cowork-parity: ic-sim must NOT bash-`rm` prior artifacts under `$SIM_DIR`
    (the promoted outputs/ tree) and must NOT stage scratch there. It
    overwrites-in-place (producers rewrite via `-o`; compose's STALE_ARTIFACT
    run_id check backstops a skipped-step leftover) and stages in a `/tmp`
    `$STAGING_DIR`. Replaces the old `rm -f` cleanup-coverage test — deleting
    under outputs/ is the regression now, not an uncovered artifact.
    """
    skill_text = SKILL_MD.read_text(encoding="utf-8")
    assert not re.search(r"\brm\b[^\n`]*\$\{?SIM_DIR\b", skill_text), (
        f"{SKILL_MD.name}: bash `rm` of $SIM_DIR (promoted outputs/) — overwrite-in-place instead"
    )
    assert not re.search(r"\$\{?SIM_DIR\}?/\.staging", skill_text), (
        f"{SKILL_MD.name}: stages scratch under $SIM_DIR — use a /tmp $STAGING_DIR"
    )
    assert re.search(r'STAGING_DIR="\$\(mktemp -d', skill_text), (
        f"{SKILL_MD.name}: expected a `$STAGING_DIR` mktemp'd under /tmp for sub-agent scratch"
    )


# ---------------------------------------------------------------------------
# Test 6: No shell-variable capture of python output
# ---------------------------------------------------------------------------


def test_no_shell_variable_capture_of_python_output() -> None:
    """Each Bash call runs in a fresh shell; capturing python output into a shell
    variable makes it invisible to any subsequent Bash call. No carve-outs.

    The regression: COACHING_PAYLOAD="$(python3 ...)" at Step 9 was fixed by
    this test suite — the pattern must not return.

    The <!-- skill-quality-ci: bash-after-subagent-ok --> marker is allowed to
    remain above the Bash block as a CI marker (it is not a capture pattern).
    """
    skill_text = SKILL_MD.read_text(encoding="utf-8")
    assert not re.search(r'\w+="\$\(\s*python3?', skill_text), (
        "SKILL.md captures python output into a shell variable — print it instead. "
        "Zero carve-outs: the house-pattern regression guard fires on any match."
    )


# ---------------------------------------------------------------------------
# Test 7: Flag existence — every --flag in SKILL.md bash blocks must be defined
# ---------------------------------------------------------------------------


def test_bash_flags_exist_in_scripts() -> None:
    """Every --flag used in a bash invocation of an ic-sim script in SKILL.md
    must exist in that script's argparse add_argument definitions.

    Shared scripts (founder_context.py) are resolved from the shared scripts dir.
    Scripts outside either directory are skipped (not this skill's scope).
    """
    shared_scripts_dir = REPO_ROOT / "founder-skills" / "scripts"

    invocations = _extract_invocation_flags_from_text(SKILL_MD.read_text(encoding="utf-8"))

    for script_name, flags_used in invocations.items():
        skill_script = SCRIPTS_DIR / script_name
        shared_script = shared_scripts_dir / script_name
        if skill_script.exists():
            script_path = skill_script
        elif shared_script.exists():
            script_path = shared_script
        else:
            continue

        defined_flags = _collect_argparse_flags(script_path)
        phantom_flags = flags_used - defined_flags
        assert not phantom_flags, (
            f"{script_name}: SKILL.md uses flags not defined in argparse:\n"
            f"  phantom: {sorted(phantom_flags)}\n"
            f"  defined: {sorted(defined_flags)}"
        )


def test_bash_flags_in_ref_docs_exist_in_scripts() -> None:
    """Forward-looking: every --flag used in a bash invocation of an ic-sim
    script inside any reference doc (founder-skills/skills/ic-sim/references/*.md)
    must exist in that script's argparse add_argument definitions.

    Regression guard: ic-sim reference docs currently contain no ```bash blocks
    with script invocations (all invocations are in SKILL.md only), so this test
    is vacuous today.  If a future reference doc gains a bash block that invokes
    a script with a phantom flag, this test will catch it automatically — the
    scanner structure mirrors the SKILL.md scanner above.
    """
    shared_scripts_dir = REPO_ROOT / "founder-skills" / "scripts"

    for ref_doc in sorted(REFS_DIR.glob("*.md")):
        text = ref_doc.read_text(encoding="utf-8")
        invocations = _extract_invocation_flags_from_text(text)

        for script_name, flags_used in invocations.items():
            skill_script = SCRIPTS_DIR / script_name
            shared_script = shared_scripts_dir / script_name
            if skill_script.exists():
                script_path = skill_script
            elif shared_script.exists():
                script_path = shared_script
            else:
                continue  # script outside this skill's scope; skip

            defined_flags = _collect_argparse_flags(script_path)
            phantom_flags = flags_used - defined_flags
            assert not phantom_flags, (
                f"{ref_doc.name}: {script_name} invocation uses flags not defined in argparse:\n"
                f"  phantom: {sorted(phantom_flags)}\n"
                f"  defined: {sorted(defined_flags)}"
            )


def test_producer_scripts_require_run_id_flag() -> None:
    """The three producer scripts that inject run_id into output artifacts must
    define --run-id as a required argparse argument.

    score_dimensions.py, fund_profile.py, and detect_conflicts.py all call
    result["metadata"] = {"run_id": args.run_id} — if --run-id were missing
    from argparse, every producer invocation would fail at argparse.
    """
    for script_name in ("score_dimensions.py", "fund_profile.py", "detect_conflicts.py"):
        script_path = SCRIPTS_DIR / script_name
        defined_flags = _collect_argparse_flags(script_path)
        assert "--run-id" in defined_flags, (
            f"{script_name} is missing --run-id argparse definition — run_id injection contract is broken"
        )


# ---------------------------------------------------------------------------
# Test 8: Context B / coaching payload
# ---------------------------------------------------------------------------


def test_post_compose_coaching_dispatch_includes_coaching_payload_keys() -> None:
    """The POST_COMPOSE_COACHING dispatch template in SKILL.md must list the
    coaching_payload keys the agent consumes for commentary composition
    (the payload itself is pasted verbatim from report.json, so the template
    documents the consumed keys in its procedure step). The agent body must
    enumerate the full key set including the mechanics keys it is told to
    ignore (insertion_marker / report_path / review_dir).

    The insertion_marker must also appear in the Step 9 section AFTER the
    template — it feeds the main thread's insert_coaching.py invocation.
    """
    # Keys the agent reasons from when composing commentary:
    consumed_keys = {
        "summary",
        "dealbreakers",
        "concerns",
        "high_severity_warnings",
        "company_name",
    }
    # Mechanics keys: documented in the agent body (as ignore-these), and
    # insertion_marker is used by the main thread's script invocation.
    mechanics_keys = {"insertion_marker", "report_path", "review_dir"}

    skill_text = SKILL_MD.read_text(encoding="utf-8")
    anchor = "CONTEXT: POST_COMPOSE_COACHING"
    start = skill_text.find(anchor)
    assert start != -1, f"{SKILL_MD.name} has no '{anchor}' section"
    section = skill_text[start : start + 3000]

    for key in consumed_keys:
        assert key in section, f"{SKILL_MD.name} POST_COMPOSE_COACHING template is missing coaching_payload key '{key}'"

    # insertion_marker feeds insert_coaching.py --marker in the same step;
    # bound at the next '### ' step heading.
    step_end = skill_text.find("\n### ", start)
    step_section = skill_text[start:step_end] if step_end != -1 else skill_text[start:]
    assert "insertion_marker" in step_section, (
        f"{SKILL_MD.name} Step 9 does not reference insertion_marker for the insert_coaching.py invocation"
    )

    # Agent body Context B section documents the full key set
    agent_text = AGENT_MD.read_text(encoding="utf-8")
    agent_anchor = "### Context B"
    agent_start = agent_text.find(agent_anchor)
    assert agent_start != -1, f"{AGENT_MD.name} has no '### Context B' section"
    agent_section = agent_text[agent_start : agent_start + 6000]

    for key in consumed_keys | mechanics_keys:
        assert key in agent_section, f"{AGENT_MD.name} Context B procedure is missing coaching_payload key '{key}'"


def test_coaching_payload_schema_version_is_ic_sim() -> None:
    """Two-surface sync: compose_report.py's schema_version literal must
    (a) end with '-ic-sim' (skill-specific suffix — prevents cross-skill payload
    misinterpretation), AND (b) equal the version stated in the agent body prose.

    Extraction strategy — independent on both surfaces:
    - Script literal: first '"schema_version": "..."' match inside compose_report.py;
      changing the literal to a non-ic-sim value fails the suffix check.
    - Agent prose: the agent body states the version in prose as
      'schema_version v<version>' (e.g. 'schema_version v0.4.2-ic-sim'); regex
      extracts the version token following 'schema_version '.

    Mutation-test guarantees:
    - Change the agent prose version (e.g. 'v0.4.2-ic-sim' → 'v0.4.3-ic-sim') → fail
      (prose_version != script_literal).
    - Change the script literal (e.g. 'v0.4.2-ic-sim' → 'v0.4.2-generic') → fail
      (suffix check fails AND prose_version != script_literal).
    """
    src = (SCRIPTS_DIR / "compose_report.py").read_text(encoding="utf-8")

    # Extract the schema_version literal from the script source
    m_script = re.search(r'"schema_version"\s*:\s*"([^"]+)"', src)
    assert m_script, (
        'compose_report.py has no \'"schema_version": "..."\' literal — _emit_coaching_payload may have been refactored'
    )
    script_literal = m_script.group(1)

    # (a) suffix check — must be ic-sim-specific
    assert script_literal.endswith("-ic-sim"), (
        f"compose_report.py coaching_payload schema_version '{script_literal}' "
        f"does not end with '-ic-sim' — wrong skill or missing suffix"
    )

    # (b) two-surface sync: agent body must state the same version
    agent_text = AGENT_MD.read_text(encoding="utf-8")
    # Matches: "schema_version v0.4.2-ic-sim" (prose form in agent body)
    m_prose = re.search(r"schema_version\s+(v[\w.\-]+)", agent_text)
    assert m_prose, (
        f"{AGENT_MD.name} does not state 'schema_version v...' in prose — "
        f"the agent body must document the expected schema_version for Context B to validate"
    )
    prose_version = m_prose.group(1)

    assert prose_version == script_literal, (
        f"schema_version drift: compose_report.py emits '{script_literal}' "
        f"but {AGENT_MD.name} states '{prose_version}' — both surfaces must agree"
    )


def test_context_b_commentary_payload_keys() -> None:
    """R2 coaching-transport fix: the Context B return payload defined in the
    agent body is now just the receipt (status + output_path) — the
    commentary text itself is written to OUTPUT_PATH as RAW MARKDOWN, not a
    commentary_markdown JSON key (that envelope is built deterministically by
    the main-thread md_to_commentary.py adapter, not the sub-agent). The
    headline outcome fields SKILL.md's Main-Thread Return section presents
    are sourced from coaching_payload + the insert_coaching.py receipt, not
    the sub-agent.
    """
    required_keys = {
        "status",
        "output_path",
    }

    agent_text = AGENT_MD.read_text(encoding="utf-8")
    anchor = "#### 2. Write the commentary to OUTPUT_PATH, then return a receipt"
    start = agent_text.find(anchor)
    assert start != -1, f"{AGENT_MD.name} has no '{anchor}' section"
    section = agent_text[start : start + 1000]

    for key in required_keys:
        assert f'"{key}"' in section, (
            f"{AGENT_MD.name} Context B commentary payload is missing key '{key}' "
            f"(SKILL.md Step 10 stages it for insert_coaching.py)"
        )
    # commentary_markdown must NOT appear here anymore -- the sub-agent writes
    # plain markdown, not a JSON envelope; the key belongs to the adapter now.
    assert '"commentary_markdown"' not in section

    # SKILL.md Main-Thread Return section must still present the headline keys
    # (sourced from coaching_payload / the insert_coaching.py receipt)
    skill_text = SKILL_MD.read_text(encoding="utf-8")
    main_thread_anchor = "## Main-Thread Return"
    mt_start = skill_text.find(main_thread_anchor)
    assert mt_start != -1, f"{SKILL_MD.name} has no '## Main-Thread Return' section"
    mt_section = skill_text[mt_start : mt_start + 2000]
    for key in {"decision", "consensus_strength", "key_concerns", "high_severity_warnings"}:
        assert key in mt_section, f"{SKILL_MD.name} Main-Thread Return section does not mention '{key}'"


def test_run_id_parity_artifact_list_matches_producer_artifacts() -> None:
    """run_id parity is verified script-side by insert_coaching.py. Two
    surfaces must list exactly the 4 producer-script artifacts that inject
    run_id via --run-id: fund_profile.json, conflict_check.json,
    discussion.json, score_dimensions.json.

    1. SKILL.md Step 9's insert_coaching.py invocation — the
       `--verify-artifact` flags (the operative gate).
    2. The agent body's Context B prose list (informational; keeps the
       agent's mental model in sync).

    startup_profile.json is agent-written (not producer-script output) so it
    does NOT carry metadata.run_id and is NOT in the parity check set.
    report.json is excluded (compose-side aggregator with no run_id).
    """
    producer_artifacts = frozenset(
        {
            "fund_profile.json",
            "conflict_check.json",
            "discussion.json",
            "score_dimensions.json",
        }
    )

    # Surface 1: SKILL.md --verify-artifact flags
    skill_text = SKILL_MD.read_text(encoding="utf-8")
    verify_artifacts = frozenset(re.findall(r'--verify-artifact\s+"\$[A-Z_]+/([a-z_]+\.json)"', skill_text))
    assert verify_artifacts, f"{SKILL_MD.name} has no --verify-artifact flags (insert_coaching.py invocation missing?)"
    assert verify_artifacts == producer_artifacts, (
        f"{SKILL_MD.name} insert_coaching.py --verify-artifact list != producer artifacts:\n"
        f"  phantom: {sorted(verify_artifacts - producer_artifacts)}\n"
        f"  missing: {sorted(producer_artifacts - verify_artifacts)}"
    )

    # Surface 2: agent body prose list
    agent_text = AGENT_MD.read_text(encoding="utf-8")
    anchor = "run_id-parity verification (across"
    start = agent_text.find(anchor)
    assert start != -1, f"{AGENT_MD.name} Context B has no 'run_id-parity verification (across ...)' prose list"
    close = agent_text.find(")", start)
    assert close != -1, f"{AGENT_MD.name} run_id-parity prose list has no closing paren"
    prose_artifacts = frozenset(re.findall(r"\b([a-z_]+\.json)\b", agent_text[start:close]))
    assert prose_artifacts == producer_artifacts, (
        f"{AGENT_MD.name} run_id-parity prose list != producer artifacts:\n"
        f"  phantom: {sorted(prose_artifacts - producer_artifacts)}\n"
        f"  missing: {sorted(producer_artifacts - prose_artifacts)}"
    )


def test_main_thread_headline_renders_verdict_never_bare_enum() -> None:
    """The agent's own chat headline must render the verdict the way
    compose_report.py renders it in the report (``Decline``/``Invest``/...),
    NEVER the raw internal enum (``pass``/``hard_pass`` read to a founder as
    'passed the bar' when they mean DECLINE).

    Two-surface sync (mutation-resistant, mirrors the schema_version test):
    - compose_report.py owns the canonical verdict_label mapping.
    - SKILL.md's Main-Thread Return section must carry those SAME rendering
      strings, so the main thread headlines the human rendering, not the token
      it pulls from ``coaching_payload.decision`` (= ``summary.verdict``).
    - The section must also explicitly forbid surfacing the bare token.

    The compose-side rendering fix alone is too narrow: it fixes the report
    artifact but leaves the deliver step free to echo the raw enum in chat.
    """
    compose_src = (SCRIPTS_DIR / "compose_report.py").read_text(encoding="utf-8")

    # Extract compose's canonical verdict -> label mapping (the source of truth).
    labels = dict(
        re.findall(
            r'"(invest|more_diligence|pass|hard_pass)"\s*:\s*"([^"]+)"',
            compose_src,
        )
    )
    assert set(labels) == {"invest", "more_diligence", "pass", "hard_pass"}, (
        "compose_report.py verdict_label mapping not found or incomplete — "
        f"got {sorted(labels)} (rendering refactored?)"
    )

    skill_text = SKILL_MD.read_text(encoding="utf-8")
    mt_start = skill_text.find("## Main-Thread Return")
    assert mt_start != -1, f"{SKILL_MD.name} has no '## Main-Thread Return' section"
    # Bound the section at the next top-level heading so the assertion is local
    # to the deliver/headline guidance, not the whole file.
    next_h2 = skill_text.find("\n## ", mt_start + 1)
    mt_section = skill_text[mt_start : next_h2 if next_h2 != -1 else len(skill_text)]

    # (a) The human rendering for every DECLINE verdict must appear in the
    #     Main-Thread Return guidance (so the headline can't be a bare token).
    for verdict in ("pass", "hard_pass"):
        assert labels[verdict] in mt_section, (
            f"{SKILL_MD.name} Main-Thread Return section does not carry compose's "
            f"'{verdict}' rendering ({labels[verdict]!r}) — the chat headline can still "
            f"leak the raw '{verdict}' token"
        )
    # 'invest' rendering too, so the positive path is equally unambiguous.
    assert labels["invest"] in mt_section, (
        f"{SKILL_MD.name} Main-Thread Return section does not carry compose's 'invest' rendering ({labels['invest']!r})"
    )

    # (b) The section must explicitly prohibit surfacing the bare enum in chat.
    section_lower = mt_section.lower()
    assert "never" in section_lower and ("`pass`" in mt_section or "raw" in section_lower or "bare" in section_lower), (
        f"{SKILL_MD.name} Main-Thread Return section does not explicitly forbid "
        f"surfacing the bare 'pass'/'hard_pass' token in the chat headline"
    )


# ---------------------------------------------------------------------------
# Test 8b: SCORE_DIMENSIONS dispatch template enumerates ALL canonical ids
#
# Note: FMR (financial-model-review) and competitive-positioning enumerate via
# systematic PREFIX_NN ranges and are covered by their own range-expansion
# checks — the asymmetry here (explicit list vs. range) is intentional.
# ---------------------------------------------------------------------------


def test_score_dimensions_dispatch_template_enumerates_all_canonical_ids() -> None:
    """The SCORE_DIMENSIONS dispatch template in SKILL.md must enumerate every
    canonical dimension ID as a JSON ``"id"`` field value — no omissions, no phantoms.

    Set-equality test (both directions):
    - Template IDs ⊆ canonical: no invented IDs in the template.
    - Canonical IDs ⊆ template IDs: no ID silently absent from the template.

    Search region: bounded within the SCORE_DIMENSIONS dispatch template fence
    (from the 'CONTEXT: SCORE_DIMENSIONS' block) so only the enumerated list
    satisfies the check, not surrounding prose.

    Count guard: exactly 28 ``"id"`` values must appear in the template.

    Mutation-check: rename any id in the template → phantom check fails;
    restore → passes.
    """
    mod = _load_score_dimensions_module()
    canonical_ids: set[str] = set(mod.VALID_IDS)  # type: ignore[attr-defined]
    assert len(canonical_ids) == 28, (
        f"score_dimensions.py VALID_IDS has {len(canonical_ids)} items (expected 28) — "
        f"update this test if the canonical set genuinely changed"
    )

    skill_text = SKILL_MD.read_text(encoding="utf-8")

    # Bound search to the SCORE_DIMENSIONS dispatch template fence
    anchor = "CONTEXT: SCORE_DIMENSIONS"
    start = skill_text.find(anchor)
    assert start != -1, f"{SKILL_MD.name} has no '{anchor}' section"
    # The anchor is inside the fence; find the opening fence that precedes it
    # by searching backwards from the anchor for the nearest \n```\n
    open_fence_pos = skill_text.rfind("\n```\n", 0, start)
    assert open_fence_pos != -1, f"{SKILL_MD.name} SCORE_DIMENSIONS: no opening fence before CONTEXT: line"
    close_fence = skill_text.find("\n```\n", start)
    assert close_fence != -1, f"{SKILL_MD.name} SCORE_DIMENSIONS: no closing fence after CONTEXT: line"
    template_body = skill_text[open_fence_pos:close_fence]

    # Extract all "id": "some_id" values from the template body
    template_ids = set(re.findall(r'"id"\s*:\s*"([a-z][a-z0-9_]+)"', template_body))

    assert len(template_ids) == 28, (
        f"{SKILL_MD.name} SCORE_DIMENSIONS dispatch template enumerates {len(template_ids)} ids "
        f"(expected 28); count guard catches omissions or duplicates.\n"
        f"  found: {sorted(template_ids)}"
    )

    phantom = template_ids - canonical_ids
    missing = canonical_ids - template_ids

    assert not phantom, (
        f"{SKILL_MD.name} SCORE_DIMENSIONS dispatch template contains ids not in "
        f"score_dimensions.py VALID_IDS (phantom — invented or renamed): {sorted(phantom)}"
    )
    assert not missing, (
        f"{SKILL_MD.name} SCORE_DIMENSIONS dispatch template is missing ids from "
        f"score_dimensions.py VALID_IDS (missing — sub-agent will invent them): {sorted(missing)}"
    )


# ---------------------------------------------------------------------------
# Test 9: conviction score formula documented correctly in prose
# ---------------------------------------------------------------------------


def test_conviction_score_thresholds_match_script() -> None:
    """The verdict thresholds documented in SKILL.md's Scoring section and
    evaluation-criteria.md must match the `conviction_score >=` comparisons in
    score_dimensions.py — the thresholds are extracted from the script source,
    never hardcoded here, so a script-side change with stale prose fails."""
    script_src = (SCRIPTS_DIR / "score_dimensions.py").read_text(encoding="utf-8")
    thresholds = re.findall(r"conviction_score >= (\d+)", script_src)
    assert len(thresholds) == 2, (
        f"expected two conviction_score >= comparisons in score_dimensions.py, found {thresholds}"
    )

    skill_text = SKILL_MD.read_text(encoding="utf-8")
    scoring_anchor = "## Scoring"
    start = skill_text.find(scoring_anchor)
    assert start != -1, f"{SKILL_MD.name} has no '## Scoring' section"
    # Bound on the next heading, not a fixed character count. A fixed window
    # silently shrinks the assertion's reach as the section grows: adding a
    # sentence above the thresholds pushed them past a 500-char cutoff and the
    # test failed on prose that was correct.
    next_heading = skill_text.find("\n## ", start + len(scoring_anchor))
    section = skill_text[start:next_heading] if next_heading != -1 else skill_text[start:]

    for pct in thresholds:
        assert f"{pct}%" in section, f"{SKILL_MD.name} Scoring section missing threshold {pct}%"
    assert "hard_pass" in section, f"{SKILL_MD.name} Scoring section missing hard_pass verdict"
    assert "dealbreaker" in section, f"{SKILL_MD.name} Scoring section missing dealbreaker mention"

    # evaluation-criteria.md also documents the thresholds
    criteria_text = (REFS_DIR / "evaluation-criteria.md").read_text(encoding="utf-8")
    for pct in thresholds:
        assert f"{pct}%" in criteria_text, f"evaluation-criteria.md missing threshold {pct}%"
    assert "hard_pass" in criteria_text, "evaluation-criteria.md missing hard_pass verdict"


# ---------------------------------------------------------------------------
# Verdict-enum rendering must govern ALL founder-facing narration, not only the
# final headline (IC-2b residual: a mid-run progress line leaked "verdict pass").
# ---------------------------------------------------------------------------


def test_narration_bans_raw_verdict_enum() -> None:
    """The 'Keep the founder informed' narration paragraph must forbid the bare
    pass/hard_pass/invest/more_diligence verdict enum in progress updates and require
    rendering it in words — else a mid-workflow status line leaks "verdict pass" (the
    IC-2 misread) even though the final headline is guarded by Main-Thread Return."""
    text = SKILL_MD.read_text(encoding="utf-8")
    para = text[text.index("Keep the founder informed") :].split("\n\n", 1)[0]
    assert "hard_pass" in para, "narration paragraph must name the raw verdict enum it forbids"
    assert "in words" in para, "narration paragraph must require rendering the verdict in words"


def test_consensus_disposition_renders_verdict_in_words() -> None:
    """The CONSENSUS_SCORE_MISMATCH disposition is an active prompt to narrate the verdict
    mid-run ('Present the mechanical verdict as the headline'); it must require rendering it
    in words, not the bare enum (the likely origin of the narration leak)."""
    text = SKILL_MD.read_text(encoding="utf-8")
    region = text[text.index("CONSENSUS_SCORE_MISMATCH disposition") :][:700]
    assert "in words" in region, (
        "the CONSENSUS_SCORE_MISMATCH disposition must render the verdict in words, not present the bare enum"
    )


def test_agent_coaching_renders_verdict_in_words() -> None:
    """The Context-B coaching sub-agent receives coaching_payload.summary.verdict (the raw
    enum) and writes founder-facing commentary spliced into report.md; its compose section
    must require rendering the verdict in words, never the raw pass/hard_pass enum."""
    text = AGENT_MD.read_text(encoding="utf-8")
    region = text[text.index("Compose commentary from") :][:1200]
    assert "in words" in region and "hard_pass" in region, (
        "agent Context-B compose section must instruct rendering the verdict in words (not the raw enum)"
    )


def test_step7_partner_verdict_narration_rendered_in_words() -> None:
    """Live verify (63c1d84) showed the agent narrates PARTNER verdicts raw ("operator →
    pass, analyst → pass") when combining the 3 assessments — the sharpest IC-2 misread
    surface. Step 7 (Compose Discussion) must carry a point-of-use guard to render partner
    verdicts in words, never the raw enum. Best-effort: prose guardrails bind unreliably here
    (2/3 leaked live) — this locks the point-of-use guidance so it can't silently drop."""
    text = SKILL_MD.read_text(encoding="utf-8")
    step7 = text[text.index("### Step 7: Compose Discussion") : text.index("### Step 8")]
    assert "in words" in step7 and "hard_pass" in step7, (
        "Step 7 must guard founder-facing partner-verdict narration (render in words, not the raw enum)"
    )


# ---------------------------------------------------------------------------
# Test 10: Step 6b (PARTNER_REBUTTAL) — the real second debate round
# ---------------------------------------------------------------------------


def test_step6b_precedes_step7_and_step7_pipes_through_compose_discussion() -> None:
    """Step 6b must exist between Step 6 and Step 7, and Step 7 must invoke
    compose_discussion.py rather than author discussion.json directly — the
    architectural fix this whole round-2 dispatch exists to deliver."""
    text = SKILL_MD.read_text(encoding="utf-8")
    step6_pos = text.index("### Step 6: Partner Assessments")
    step6b_pos = text.index("### Step 6b: Partner Rebuttals")
    step7_pos = text.index("### Step 7: Compose Discussion")
    step8_pos = text.index("### Step 8: Score Dimensions")
    assert step6_pos < step6b_pos < step7_pos < step8_pos, "Step ordering must be Step 6 -> Step 6b -> Step 7 -> Step 8"

    step7 = text[step7_pos:step8_pos]
    assert "compose_discussion.py" in step7, "Step 7 must invoke compose_discussion.py"
    assert "cat <<" not in step7, (
        "Step 7 must no longer author discussion.json via heredoc — that is exactly the "
        "main-thread-authorship failure mode compose_discussion.py exists to close"
    )


def test_step6b_no_longer_licenses_main_thread_verdict_authorship() -> None:
    """The old 'Verdict reconciliation: Ensure each partner's verdict ... reflects
    their final position' licence must be gone from SKILL.md — verdict revision is
    now the PARTNER_REBUTTAL sub-agent's job (Step 6b), not something the main
    thread infers and writes into discussion.json by hand."""
    text = SKILL_MD.read_text(encoding="utf-8")
    assert "Ensure each partner's verdict in `partner_verdicts` reflects their" not in text
    assert "final position after debate" not in text


def _partner_rebuttal_full_template_section(skill_text: str) -> str:
    """Return the FULL PARTNER_REBUTTAL dispatch prompt template body (not the
    pseudocode block, which also contains 3 'CONTEXT: PARTNER_REBUTTAL' lines
    ahead of it). The full template is the LAST 'CONTEXT: PARTNER_REBUTTAL'
    occurrence inside the Step 6b section — anchoring on the last occurrence
    rather than a heading string keeps this robust to prose changes around it."""
    step6b_start = skill_text.index("### Step 6b: Partner Rebuttals")
    step7_start = skill_text.index("### Step 7: Compose Discussion")
    step6b_text = skill_text[step6b_start:step7_start]
    anchor = "CONTEXT: PARTNER_REBUTTAL"
    rel_start = step6b_text.rfind(anchor)
    assert rel_start != -1, f"Step 6b has no '{anchor}' occurrence at all"
    start = step6b_start + rel_start
    fence = skill_text.find("\n```", start)
    return skill_text[start : fence if fence != -1 else start + 3000]


def test_partner_rebuttal_dispatch_return_shape_keys() -> None:
    """The PARTNER_REBUTTAL dispatch template (Step 6b) and the agent body's
    PARTNER_REBUTTAL subtype must include the rebuttal object's required keys,
    and the same 4-value verdict enum as PARTNER_ANALYSIS."""
    required_keys = {
        "partner",
        "revised_verdict",
        "verdict_changed",
        "changed_because",
        "responses",
        "dealbreakers",
        "diligence_requirements",
    }
    verdict_values = {"invest", "more_diligence", "pass", "hard_pass"}

    skill_text = SKILL_MD.read_text(encoding="utf-8")
    section = _partner_rebuttal_full_template_section(skill_text)

    for key in required_keys:
        assert f'"{key}"' in section, f"{SKILL_MD.name} PARTNER_REBUTTAL return shape missing key '{key}'"
    for val in verdict_values:
        assert val in section, f"{SKILL_MD.name} PARTNER_REBUTTAL return shape does not mention verdict value '{val}'"

    agent_text = AGENT_MD.read_text(encoding="utf-8")
    agent_anchor = "#### PARTNER_REBUTTAL subtype"
    agent_start = agent_text.find(agent_anchor)
    assert agent_start != -1, f"{AGENT_MD.name} has no '#### PARTNER_REBUTTAL subtype' section"
    next_heading = agent_text.find("\n#### ", agent_start + 1)
    agent_section = agent_text[agent_start:next_heading] if next_heading != -1 else agent_text[agent_start:]
    for key in required_keys:
        assert f'"{key}"' in agent_section, f"{AGENT_MD.name} PARTNER_REBUTTAL subtype return shape missing key '{key}'"


def test_partner_rebuttal_dispatch_template_forbids_writes() -> None:
    """The PARTNER_REBUTTAL dispatch template must explicitly forbid artifact
    writes, same as every other Context A dispatch template."""
    skill_text = SKILL_MD.read_text(encoding="utf-8")
    section = _partner_rebuttal_full_template_section(skill_text)
    assert "Do NOT write" in section or "do not write" in section.lower(), (
        f"{SKILL_MD.name} PARTNER_REBUTTAL dispatch template must explicitly forbid artifact writes"
    )


def test_parallel_rebuttal_dispatch_recipe_names_all_three_archetypes() -> None:
    """Step 6b's rebuttal pseudocode block must name all 3 archetypes explicitly,
    same guard as Step 6's PARTNER_ANALYSIS dispatch."""
    skill_text = SKILL_MD.read_text(encoding="utf-8")
    anchor = "Pseudocode for the rebuttal dispatch"
    start = skill_text.find(anchor)
    assert start != -1, f"{SKILL_MD.name} has no '{anchor}' section"
    section = skill_text[start : start + 1200]
    for role in ("visionary", "operator", "analyst"):
        assert role in section, f"{SKILL_MD.name} rebuttal dispatch pseudocode does not name archetype '{role}'"


def test_partner_rebuttal_hold_position_rule_present_in_both_surfaces() -> None:
    """The 'hold your position unless new evidence' rule — the whole point of
    this being a real debate round rather than a rubber stamp — must appear in
    both SKILL.md's Step 6b and the agent body's PARTNER_REBUTTAL subtype."""
    skill_text = SKILL_MD.read_text(encoding="utf-8")
    step6b = skill_text[skill_text.index("### Step 6b: Partner Rebuttals") : skill_text.index("### Step 7")]
    step6b_low = step6b.lower()
    assert "hold" in step6b_low and "evidence" in step6b_low
    assert "manufactures" in step6b_low and "agreement" in step6b_low

    agent_text = AGENT_MD.read_text(encoding="utf-8")
    rebuttal_section = agent_text[
        agent_text.index("#### PARTNER_REBUTTAL subtype") : agent_text.index("#### SCORE_DIMENSIONS subtype")
    ]
    assert "hold" in rebuttal_section.lower() and "evidence" in rebuttal_section.lower()


def test_compose_discussion_producer_stamp_matches_compose_report_check() -> None:
    """Two-surface sync: compose_discussion.py's own '_produced_by' literal
    must equal the string compose_report.py's UNVALIDATED_ARTIFACT check
    expects for discussion.json — a rename on either side silently breaks the
    provenance gate compose_discussion.py exists to enable."""
    discussion_src = (SCRIPTS_DIR / "compose_discussion.py").read_text(encoding="utf-8")
    m_stamp = re.search(r'"_produced_by"\s*:\s*"([^"]+)"', discussion_src)
    assert m_stamp, "compose_discussion.py has no '_produced_by' literal in its output"
    stamp = m_stamp.group(1)

    report_src = (SCRIPTS_DIR / "compose_report.py").read_text(encoding="utf-8")
    m_expected = re.search(r'"discussion\.json"\s*:\s*"([^"]+)"', report_src)
    assert m_expected, (
        "compose_report.py has no 'discussion.json': '<producer>' entry in its "
        "EXPECTED_PRODUCERS map — the UNVALIDATED_ARTIFACT check may have been refactored"
    )
    expected = m_expected.group(1)

    assert stamp == expected, (
        f"compose_discussion.py stamps _produced_by={stamp!r} but compose_report.py's "
        f"UNVALIDATED_ARTIFACT check expects {expected!r} for discussion.json"
    )


def test_compose_discussion_dimension_ids_imported_not_hardcoded() -> None:
    """compose_discussion.py must import score_dimensions.py's dimension-id set
    rather than hardcoding its own copy — a renamed/added/removed id in the
    canonical script must propagate automatically."""
    mod = _load_compose_discussion_module()
    canonical = _load_score_dimensions_module()
    assert frozenset(canonical.VALID_IDS) == mod.VALID_DIMENSION_IDS  # type: ignore[attr-defined]


def test_compose_discussion_verdict_enum_matches_score_dimensions_and_partner_analysis() -> None:
    """compose_discussion.py's VALID_VERDICTS must be the same 4-value enum
    used everywhere else in this skill (score_dimensions.py's verdict field,
    the PARTNER_ANALYSIS/PARTNER_REBUTTAL dispatch templates)."""
    mod = _load_compose_discussion_module()
    assert frozenset({"invest", "more_diligence", "pass", "hard_pass"}) == mod.VALID_VERDICTS


def test_agent_orchestration_boundary_matches_context_b_procedure() -> None:
    """The Orchestration boundary summary must match the Context B procedure: the
    coaching_payload is STAGED AS A FILE and Read by the sub-agent (never inlined
    into the dispatch prompt); the sub-agent writes PLAIN-MARKDOWN commentary to
    OUTPUT_PATH and returns only a small JSON receipt (JSON is the receipt, never
    the commentary); and the sub-agent never edits report.md directly (the main
    thread wraps the markdown via md_to_commentary.py and inserts it via
    insert_coaching.py). A summary that says the payload is 'inlined' AND that the
    commentary is 'returned as JSON' is the most substantive of the three stale
    orchestration-boundary defects: an agent following the stale text would return
    commentary in chat and write no file, failing the check_handoff.py gate and
    burning a retry.
    """
    agent_text = AGENT_MD.read_text(encoding="utf-8")
    anchor = "## Orchestration boundary"
    start = agent_text.find(anchor)
    assert start != -1, f"{AGENT_MD.name} has no '{anchor}' section"
    end = agent_text.find("\n## ", start + len(anchor))
    assert end != -1, f"{AGENT_MD.name} Orchestration boundary section has no terminator"
    section = agent_text[start:end]
    normalized = " ".join(section.split()).lower()

    assert "Edit report.md" not in section, (
        f"{AGENT_MD.name} Orchestration boundary wrongly says Context B edits report.md; "
        "Context B writes a plain-markdown hand-off to OUTPUT_PATH and never touches report.md"
    )
    assert "OUTPUT_PATH" in section, (
        f"{AGENT_MD.name} Orchestration boundary must describe the OUTPUT_PATH hand-off write"
    )
    assert "plain markdown" in normalized or "plain-markdown" in normalized, (
        f"{AGENT_MD.name} Orchestration boundary must describe Context B's commentary as plain "
        "markdown — JSON is only the receipt, never the commentary"
    )
    for stale_phrase in ("commentary as json", "commentary json", "return it as json", "returns it as json"):
        assert stale_phrase not in normalized, (
            f"{AGENT_MD.name} Orchestration boundary wrongly says Context B's commentary is "
            f"returned as JSON (found {stale_phrase!r}); the commentary is plain markdown written "
            "to OUTPUT_PATH, and JSON is only the small receipt"
        )
    assert "main thread inlines" not in normalized, (
        f"{AGENT_MD.name} Orchestration boundary wrongly says the coaching_payload is inlined into "
        "the dispatch prompt; it is STAGED AS A FILE and Read by the sub-agent from the hand-off path"
    )
