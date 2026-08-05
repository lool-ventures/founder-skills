"""Drift-contract tests for the competitive-positioning skill.

These tests grep SKILL.md and the agent body against the producer scripts'
actual source so dispatch prompts can never silently diverge from what the
scripts accept.

Covered contract surfaces:
1. Checklist criteria enumeration (25 IDs, 6 categories): IDs cited in
   SKILL.md + agent body exist in checklist.py's CHECKLIST_ITEMS; set-equality
   check against checklist-criteria.md's mode-gating table (all 25 IDs as
   backtick-quoted `ID` cells); count guards on every extraction pass.
2. Moat dimension enumeration: 6 canonical moat IDs in moat-definitions.md
   (backtick-quoted) must equal score_moats.py's CANONICAL_MOAT_IDS exactly;
   prose mentions in SKILL.md and agent body must be a subset.
3. Mode-based gating: checklist.py's MODE_GATING dict is the canonical source;
   SKILL.md and checklist-criteria.md document gated-items-by-mode; prose must
   cite only gated IDs that are canonical.
4. Dispatch return-shape keys: LANDSCAPE_RESEARCH, MOAT_SCORING,
   POSITIONING_SCORING, CHECKLIST templates carry the keys the consuming scripts
   read. Fence-bounded search; quoted-key checks; stop at the template's own
   closing fence.
5. No-file-writes instruction in every Context A dispatch template; Context B
   hard-rules forbid Bash.
6. Gate-required artifacts (compose_report.py REQUIRED_ARTIFACTS) have producing
   steps in SKILL.md; cleanup rm -f covers per-run pipeline artifacts; staging
   dir vacuity guard.
7. Zero shell-variable captures of python output. Real drift found and fixed:
   SKILL.md had COACHING_PAYLOAD="$(python3 ...)" — fixed to use direct print
   with "Never capture it into a shell variable" instruction (cap-table pattern).
8. Flag/choice existence: every --flag in SKILL.md bash invocations of CP scripts
   must exist in that script's argparse; forward-looking ref-doc scanner.
9. Context B / coaching payload: POST_COMPOSE_COACHING template carries all
   coaching_payload keys compose_report.py emits; fence-bounded at template's
   own Return: line; Context B success payload keys; agent run_id-parity artifact
   list equals 5 producer artifacts; two-surface schema_version sync
   (script literal vs agent body prose — N/A: agent body states keys not version).
10. EVID gating semantics: the mode-gating table in checklist-criteria.md
    correctly documents which IDs are gated in each mode; matches checklist.py
    MODE_GATING exactly; set-equality per mode.
"""

from __future__ import annotations

import contextlib
import importlib.util
import json
import re
import sys
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CP_DIR = REPO_ROOT / "founder-skills" / "skills" / "competitive-positioning"
SKILL_MD = CP_DIR / "SKILL.md"
AGENT_MD = REPO_ROOT / "founder-skills" / "agents" / "competitive-positioning.md"
SCRIPTS_DIR = CP_DIR / "scripts"
REFS_DIR = CP_DIR / "references"


# ---------------------------------------------------------------------------
# Module-loading helpers (unique sys.modules keys, sys.path cleanup)
# ---------------------------------------------------------------------------

# competitive-positioning scripts import _theme from the same dir at load time.
# We must save/restore it around each load to keep the sys.modules namespace clean.
_SCRIPTS_DIR_LOCAL_MODULES: tuple[str, ...] = ("_theme",)


def _load_script_module(script_name: str, sys_key: str) -> types.ModuleType:
    """Load a script from SCRIPTS_DIR, injecting the scripts dir on sys.path.

    sys.path is modified only for the duration of exec_module so relative
    imports resolve to the correct skill's copy. The path entry is removed
    afterwards (try/finally) to avoid polluting later imports.

    The restore logic handles two cases:
    - Modules in _SCRIPTS_DIR_LOCAL_MODULES that were PRESENT before exec are
      saved and restored (they belonged to a prior load).
    - Modules in _SCRIPTS_DIR_LOCAL_MODULES that were ABSENT before exec and
      were freshly inserted during exec are popped in the finally block so they
      don't leak into subsequent test state.
    """
    path = SCRIPTS_DIR / script_name
    scripts_dir_str = str(SCRIPTS_DIR)

    saved_helpers: dict[str, types.ModuleType] = {}
    absent_before_exec: set[str] = set()
    for name in _SCRIPTS_DIR_LOCAL_MODULES:
        if name in sys.modules:
            saved_helpers[name] = sys.modules.pop(name)
        else:
            absent_before_exec.add(name)

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
        # Restore previously-saved helpers.
        for name, saved_mod in saved_helpers.items():
            sys.modules[name] = saved_mod
        # Pop modules that were freshly inserted during exec and were absent before.
        for name in absent_before_exec:
            sys.modules.pop(name, None)

    return mod


def _load_checklist_module() -> types.ModuleType:
    return _load_script_module("checklist.py", "cp_checklist_contract")


def _load_score_moats_module() -> types.ModuleType:
    return _load_script_module("score_moats.py", "cp_score_moats_contract")


def _load_compose_report_module() -> types.ModuleType:
    return _load_script_module("compose_report.py", "cp_compose_report_contract")


def _load_validate_landscape_module() -> types.ModuleType:
    return _load_script_module("validate_landscape.py", "cp_validate_landscape_contract")


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
    """Return CP reference docs that contain sub-agent dispatch templates."""
    result: list[Path] = []
    for p in sorted(REFS_DIR.glob("*.md")):
        if "CONTEXT:" in p.read_text(encoding="utf-8"):
            result.append(p)
    return result


# ---------------------------------------------------------------------------
# Test 1: Checklist criteria enumeration — 25 IDs, 6 categories
# ---------------------------------------------------------------------------


def test_checklist_id_enumeration_population_is_independent() -> None:
    """Checklist IDs cited via '"id": "ID"' in SKILL.md + agent body must be a
    subset of checklist.py's VALID_IDS (populated independently).  Any candidate
    NOT in VALID_IDS is a phantom reported explicitly.

    Vacuity guard: at least 1 ID must be extracted.
    """
    mod = _load_checklist_module()
    valid_ids: set[str] = {item["id"] for item in mod.CHECKLIST_ITEMS}  # type: ignore[attr-defined]

    combined = SKILL_MD.read_text(encoding="utf-8") + "\n" + AGENT_MD.read_text(encoding="utf-8")
    candidates = set(re.findall(r'"id"\s*:\s*"([A-Z]+_\d+)"', combined))

    assert len(candidates) >= 1, (
        'No checklist IDs found via \'"id": "COVER_01"\' pattern in SKILL.md + agent body '
        "— extraction regex may have stopped matching or templates no longer show example IDs. "
        "Expected at least 'COVER_01'."
    )

    phantoms = candidates - valid_ids
    assert not phantoms, (
        f"SKILL.md / agent body cites checklist IDs not in checklist.py CHECKLIST_ITEMS (phantom): {sorted(phantoms)}"
    )


def test_checklist_criteria_md_mode_gating_table_ids_equal_canonical() -> None:
    """The mode-gating table in checklist-criteria.md enumerates all 25 criteria
    as backtick-quoted `COVER_01` cells.  These must match checklist.py's
    CHECKLIST_ITEMS exactly — no phantom rows, no missing rows.

    Count guard: exactly 25 IDs must be found.  A mutation that renames one
    produces a phantom; removing one produces a missing entry.
    """
    mod = _load_checklist_module()
    valid_ids: set[str] = {item["id"] for item in mod.CHECKLIST_ITEMS}  # type: ignore[attr-defined]

    criteria_text = (REFS_DIR / "checklist-criteria.md").read_text(encoding="utf-8")
    # Table cells have the form: | `COVER_01` | ... |
    table_ids = set(re.findall(r"\|\s*`([A-Z]+_\d+)`\s*\|", criteria_text))

    assert len(table_ids) == 25, (
        f"checklist-criteria.md mode-gating table has {len(table_ids)} criterion ID cells "
        f"(expected 25); count guard catches missing or extra rows"
    )

    phantom = table_ids - valid_ids
    missing = valid_ids - table_ids
    assert not phantom, (
        f"checklist-criteria.md mode-gating table has IDs not in checklist.py CHECKLIST_ITEMS "
        f"(phantom — rename or remove): {sorted(phantom)}"
    )
    assert not missing, (
        f"checklist-criteria.md mode-gating table is missing IDs from checklist.py CHECKLIST_ITEMS "
        f"(missing — add a row): {sorted(missing)}"
    )


def test_checklist_count_and_categories() -> None:
    """checklist.py CHECKLIST_ITEMS must contain exactly 25 items across 6 categories.
    SKILL.md documents '25 criteria across 6 categories' — this count guard catches
    silent additions or deletions.
    """
    from collections import Counter

    mod = _load_checklist_module()
    items: list[dict[str, str]] = mod.CHECKLIST_ITEMS  # type: ignore[attr-defined]

    assert len(items) == 25, f"checklist.py CHECKLIST_ITEMS has {len(items)} items (expected 25 per documentation)"

    expected_categories = {"COVER", "POS", "MOAT", "EVID", "NARR", "MISS"}
    by_category: Counter[str] = Counter(item["category"] for item in items)
    assert set(by_category.keys()) == expected_categories, (
        f"checklist.py categories mismatch:\n"
        f"  expected: {sorted(expected_categories)}\n"
        f"  got: {sorted(by_category.keys())}"
    )

    # Count guard per category (per documentation: COVER=5, POS=5, MOAT=4, EVID=4, NARR=4, MISS=3)
    expected_counts = {"COVER": 5, "POS": 5, "MOAT": 4, "EVID": 4, "NARR": 4, "MISS": 3}
    for cat, expected in expected_counts.items():
        actual = by_category[cat]
        assert actual == expected, f"checklist.py category '{cat}' has {actual} items (expected {expected})"

    # SKILL.md must document the 25-item count
    skill_text = SKILL_MD.read_text(encoding="utf-8")
    assert "25" in skill_text, f"{SKILL_MD.name} does not mention '25' criteria — documentation may be stale"


# ---------------------------------------------------------------------------
# Test 2: Moat dimension enumeration — moat-definitions.md vs CANONICAL_MOAT_IDS
# ---------------------------------------------------------------------------


def test_moat_definitions_md_backtick_ids_equal_canonical_moat_ids() -> None:
    """moat-definitions.md's H3 section headers (### `moat_id`) enumerate the
    6 canonical moat IDs.  These must match score_moats.py's CANONICAL_MOAT_IDS
    exactly — no phantom entries, no missing entries.

    Count guard: exactly 6 IDs must be found.
    """
    mod = _load_score_moats_module()
    canonical: set[str] = set(mod.CANONICAL_MOAT_IDS)  # type: ignore[attr-defined]

    assert len(canonical) == 6, (
        f"score_moats.py CANONICAL_MOAT_IDS has {len(canonical)} entries (expected 6); "
        f"update this test if the canonical set genuinely changed"
    )

    moat_text = (REFS_DIR / "moat-definitions.md").read_text(encoding="utf-8")
    # H3 headers have the form: ### 1. `network_effects`
    # Also handle: ### `network_effects`
    header_ids = set(re.findall(r"###[^`\n]*`([a-z][a-z0-9_]+)`", moat_text))
    # Keep only IDs that are snake_case moat names (not other code tokens)
    header_ids = {i for i in header_ids if "_" in i or i in canonical}

    assert len(header_ids) == 6, (
        f"moat-definitions.md has {len(header_ids)} H3 moat headers (expected 6). Found: {sorted(header_ids)}"
    )

    phantom = header_ids - canonical
    missing = canonical - header_ids
    assert not phantom, (
        f"moat-definitions.md has moat IDs not in score_moats.py CANONICAL_MOAT_IDS "
        f"(phantom — rename or remove): {sorted(phantom)}"
    )
    assert not missing, (
        f"moat-definitions.md is missing moat IDs from score_moats.py CANONICAL_MOAT_IDS "
        f"(missing — add a section): {sorted(missing)}"
    )


def test_moat_dimension_prose_mentions_in_skill_md_and_agent_body() -> None:
    """The MOAT_SCORING dispatch template in SKILL.md must explicitly name all 6
    canonical moat IDs, and must not name any that aren't canonical.

    Extraction is independent of the canonical set: moat IDs are harvested as
    comma-separated bare snake_case tokens from the moat-enumeration line in
    the template (the line that begins after the moat-definitions.md citation and
    lists each ID separated by commas/spaces). This produces a set that is compared
    against canonical, so `phantom = cited - canonical` is genuinely meaningful.

    The agent body MOAT_SCORING subtype uses backtick-quoted IDs; those are
    extracted independently via the backtick pattern, again compared to canonical.

    Count guards: both surfaces must cite exactly 6 moat IDs.
    """
    mod = _load_score_moats_module()
    canonical: set[str] = set(mod.CANONICAL_MOAT_IDS)  # type: ignore[attr-defined]

    assert len(canonical) == 6, f"CANONICAL_MOAT_IDS has {len(canonical)} entries (expected 6)"

    skill_text = SKILL_MD.read_text(encoding="utf-8")
    anchor = "CONTEXT: MOAT_SCORING"
    start = skill_text.find(anchor)
    assert start != -1, f"{SKILL_MD.name} has no 'CONTEXT: MOAT_SCORING' section"
    # Template is inside a code fence: the opening fence is the last \n``` before
    # the anchor; the closing fence is the first \n```\n after the anchor.
    open_fence = skill_text.rfind("\n```", 0, start)
    assert open_fence != -1, f"{SKILL_MD.name} MOAT_SCORING: no opening ``` fence before anchor"
    close_fence = skill_text.find("\n```\n", start)
    assert close_fence != -1, f"{SKILL_MD.name} MOAT_SCORING section: no closing ``` fence"
    section = skill_text[open_fence:close_fence]

    # Extract the comma-or-space-separated moat ID list from the template.
    # The list follows the moat-definitions.md citation and spans 1-2 lines of
    # comma-separated snake_case tokens.  We isolate just that block (from the
    # end of the 'moat-definitions.md:' line to the first blank line or 'Each'
    # keyword) to avoid picking up other snake_case tokens in the template such
    # as 'evidence_source' or 'run_id'.
    enum_block_match = re.search(
        r"moat-definitions\.md:[^\n]*\n((?:[^\n]+\n)*?)(?:\n|Each\b)",
        section,
        re.DOTALL,
    )
    assert enum_block_match is not None, (
        f"{SKILL_MD.name} MOAT_SCORING template: cannot find the moat-ID block after "
        f"the 'moat-definitions.md:' citation (expected comma-separated snake_case IDs)"
    )
    enum_block = enum_block_match.group(1)
    # Extract every snake_case token that looks like a moat identifier (contains '_').
    # This excludes generic one-word tokens that may appear in the block.
    cited: set[str] = {t for t in re.findall(r"\b([a-z][a-z0-9_]+)\b", enum_block) if "_" in t}

    assert len(cited) == 6, (
        f"{SKILL_MD.name} MOAT_SCORING enumeration line has {len(cited)} moat-like tokens "
        f"(expected 6); found: {sorted(cited)}"
    )

    missing = canonical - cited
    phantom = cited - canonical
    assert not missing, f"{SKILL_MD.name} MOAT_SCORING template is missing canonical moat IDs: {sorted(missing)}"
    assert not phantom, (
        f"{SKILL_MD.name} MOAT_SCORING template cites moat IDs not in CANONICAL_MOAT_IDS: {sorted(phantom)}"
    )

    # Agent body MOAT_SCORING subtype enumerates the 6 canonical IDs as
    # backtick-quoted tokens on 1-2 comma-separated lines after "canonical moat
    # dimensions:".  We isolate just those lines to avoid picking up other
    # backtick-quoted snake_case tokens in the section (e.g. 'evidence_source').
    # The enumeration ends at the first `. Each` or `. Each moat` phrase on the
    # last ID line — we capture only the text from the dimensions phrase to that
    # sentence boundary.
    agent_text = AGENT_MD.read_text(encoding="utf-8")
    agent_anchor = "#### MOAT_SCORING subtype"
    agent_start = agent_text.find(agent_anchor)
    assert agent_start != -1, f"{AGENT_MD.name} has no '#### MOAT_SCORING subtype' section"
    next_heading = agent_text.find("\n#### ", agent_start + 1)
    agent_section = (
        agent_text[agent_start:next_heading] if next_heading != -1 else agent_text[agent_start : agent_start + 2000]
    )
    # Find the "canonical moat dimensions:" phrase and capture the text up to
    # ". Each" (the sentence boundary that follows the last ID on the list line).
    agent_enum_match = re.search(
        r"canonical moat dimensions:[^\n]*\n([^.]+)\. Each\b",
        agent_section,
        re.DOTALL,
    )
    assert agent_enum_match is not None, (
        f"{AGENT_MD.name} MOAT_SCORING subtype: cannot find the moat-ID enumeration "
        f"block (expected 'canonical moat dimensions:' followed by a list ending '. Each')"
    )
    agent_enum_block = agent_enum_match.group(1)
    # Extract backtick-quoted tokens that contain underscores (moat IDs).
    agent_cited: set[str] = {t for t in re.findall(r"`([a-z][a-z0-9_]+)`", agent_enum_block) if "_" in t}

    # Compare against canonical — phantom and missing are both meaningful here
    # because agent_cited was extracted without any intersection with canonical.
    agent_canonical_hits = agent_cited & canonical
    agent_phantom = agent_cited - canonical

    assert len(agent_canonical_hits) == 6, (
        f"{AGENT_MD.name} MOAT_SCORING subtype cites {len(agent_canonical_hits)} of 6 canonical moat IDs "
        f"(expected all 6); missing: {sorted(canonical - agent_canonical_hits)}"
    )
    assert not agent_phantom, (
        f"{AGENT_MD.name} MOAT_SCORING subtype cites moat IDs not in CANONICAL_MOAT_IDS "
        f"(phantom): {sorted(agent_phantom)}"
    )


# ---------------------------------------------------------------------------
# Test 3: Mode-based gating — MODE_GATING dict vs prose
# ---------------------------------------------------------------------------


def test_mode_gating_table_in_checklist_criteria_md_matches_script() -> None:
    """The gated-items-by-mode summary in checklist-criteria.md must match
    checklist.py's MODE_GATING dict exactly, per mode.

    Extraction: the summary block lists gated IDs as backtick-quoted tokens
    after the bullet for each mode.

    Vacuity guard: at least 2 gated IDs must be extractable per mode that has
    any gated items in the script.
    """
    mod = _load_checklist_module()
    mode_gating: dict[str, set[str]] = {k: set(v) for k, v in mod.MODE_GATING.items()}  # type: ignore[attr-defined]

    criteria_text = (REFS_DIR / "checklist-criteria.md").read_text(encoding="utf-8")

    # The summary block has the form:
    #   - **`deck`**: `EVID_04` (...)
    #   - **`conversation`**: `NARR_03`, `EVID_04` (...)
    #   - **`document`**: `NARR_03` (...)
    for mode, expected_gated in mode_gating.items():
        # Find the line that starts the mode bullet
        pattern = re.compile(rf"\*\*`{re.escape(mode)}`\*\*:\s*(.+?)(?:\n|$)")
        m = pattern.search(criteria_text)
        assert m is not None, (
            f"checklist-criteria.md has no gated-items bullet for mode '{mode}' "
            f"— expected a line like '- **`{mode}`**: `NARR_03`, `EVID_04` ...'"
        )
        line = m.group(1)
        extracted_ids = set(re.findall(r"`([A-Z]+_\d+)`", line))

        assert extracted_ids == expected_gated, (
            f"checklist-criteria.md gated IDs for mode '{mode}' mismatch:\n"
            f"  criteria doc: {sorted(extracted_ids)}\n"
            f"  script MODE_GATING: {sorted(expected_gated)}\n"
            f"  phantom (in doc, not script): {sorted(extracted_ids - expected_gated)}\n"
            f"  missing (in script, not doc): {sorted(expected_gated - extracted_ids)}"
        )


def test_input_mode_choices_in_checklist_py_match_prose() -> None:
    """checklist.py accepts --input-mode choices ('deck', 'conversation', 'document').
    SKILL.md's checklist pipe documentation must reference all three modes.

    The canonical set is extracted from checklist.py's argparse choices at test time.
    """
    src = (SCRIPTS_DIR / "checklist.py").read_text(encoding="utf-8")

    # Extract choices from argparse
    m = re.search(r"choices=\(([^)]+)\)", src)
    assert m is not None, "checklist.py has no 'choices=(...)' in --input-mode argparse"
    raw_choices = re.findall(r'"([a-z]+)"', m.group(1))
    canonical_modes = frozenset(raw_choices)

    assert canonical_modes == {"deck", "conversation", "document"}, (
        f"checklist.py --input-mode choices changed: got {sorted(canonical_modes)}"
    )

    skill_text = SKILL_MD.read_text(encoding="utf-8")
    for mode in canonical_modes:
        assert f'"{mode}"' in skill_text or f"'{mode}'" in skill_text or f"`{mode}`" in skill_text, (
            f"{SKILL_MD.name} does not mention input_mode value '{mode}' — documentation may be stale"
        )


# ---------------------------------------------------------------------------
# Test 4: Dispatch return-shape keys
# ---------------------------------------------------------------------------


def test_landscape_research_dispatch_return_shape_keys() -> None:
    """The LANDSCAPE_RESEARCH dispatch template in SKILL.md must include the keys
    that the dispatch return shape requires: 'competitors', 'suggested_additions',
    'suggested_axes', 'assessment_mode', 'research_depth', 'input_mode', and
    'metadata' (for run_id parity).

    Note: 'suggested_additions' and 'suggested_axes' are consumed by the main
    thread's founder-approval merge step before piping to validate_landscape.py;
    they are not read by validate_landscape.py itself.

    The CONTEXT: LANDSCAPE_RESEARCH anchor sits inside the template's code fence.
    The opening fence is found with rfind (last fence before the anchor); the
    closing fence is found with find (first \n```\n after the anchor). This bounds
    the search to the template body only, excluding post-template prose.

    Also verified in the agent body's LANDSCAPE_RESEARCH subtype section.
    """
    required_keys = {
        "competitors",
        "suggested_additions",
        "suggested_axes",
        "assessment_mode",
        "research_depth",
        "input_mode",
        "metadata",
    }

    skill_text = SKILL_MD.read_text(encoding="utf-8")
    anchor = "CONTEXT: LANDSCAPE_RESEARCH"
    start = skill_text.find(anchor)
    assert start != -1, f"{SKILL_MD.name} has no 'CONTEXT: LANDSCAPE_RESEARCH' section"
    # Anchor is inside the template fence: opening fence is the last \n``` before
    # the anchor; closing fence is the first \n```\n after the anchor.
    open_fence = skill_text.rfind("\n```", 0, start)
    assert open_fence != -1, f"{SKILL_MD.name} LANDSCAPE_RESEARCH: no opening fence before anchor"
    close_fence = skill_text.find("\n```\n", start)
    assert close_fence != -1, f"{SKILL_MD.name} LANDSCAPE_RESEARCH: no closing fence"
    section = skill_text[open_fence:close_fence]

    # suggested_additions/suggested_axes are consumed by the main thread's
    # founder-approval merge step, not by validate_landscape.py itself.
    main_thread_keys = {"suggested_additions", "suggested_axes"}
    for key in required_keys:
        consumer = (
            "consumed by the main-thread founder-approval merge step"
            if key in main_thread_keys
            else "validate_landscape.py reads it from stdin"
        )
        assert f'"{key}"' in section, (
            f"{SKILL_MD.name} LANDSCAPE_RESEARCH return shape missing key '{key}' ({consumer})"
        )

    # Agent body LANDSCAPE_RESEARCH subtype
    agent_text = AGENT_MD.read_text(encoding="utf-8")
    agent_anchor = "#### LANDSCAPE_RESEARCH subtype"
    agent_start = agent_text.find(agent_anchor)
    assert agent_start != -1, f"{AGENT_MD.name} has no '#### LANDSCAPE_RESEARCH subtype' section"
    next_heading = agent_text.find("\n#### ", agent_start + 1)
    agent_section = (
        agent_text[agent_start:next_heading] if next_heading != -1 else agent_text[agent_start : agent_start + 1500]
    )
    for key in required_keys:
        assert f'"{key}"' in agent_section, f"{AGENT_MD.name} LANDSCAPE_RESEARCH subtype missing key '{key}'"


def test_moat_scoring_dispatch_return_shape_keys() -> None:
    """The MOAT_SCORING dispatch template in SKILL.md must include the keys
    score_moats.py reads from stdin: 'moat_assessments' and 'metadata'.

    Per-moat fields ('id', 'status', 'evidence', 'evidence_source', 'trajectory')
    appear as prose in the dispatch template (not as quoted JSON keys in the moat
    entry example), so they are checked as unquoted word-boundary tokens.

    Also verified in the agent body's MOAT_SCORING subtype section.
    """
    required_top_keys = {"moat_assessments", "metadata"}
    # These appear in the template prose (e.g. "status (strong/moderate/...)")
    # rather than as quoted JSON keys in the per-entry JSON snippet.
    required_moat_entry_prose = {"id", "status", "evidence", "evidence_source", "trajectory"}

    skill_text = SKILL_MD.read_text(encoding="utf-8")
    anchor = "CONTEXT: MOAT_SCORING"
    start = skill_text.find(anchor)
    assert start != -1, f"{SKILL_MD.name} has no 'CONTEXT: MOAT_SCORING' section"
    # Anchor is inside the template fence.
    open_fence = skill_text.rfind("\n```", 0, start)
    assert open_fence != -1, f"{SKILL_MD.name} MOAT_SCORING: no opening fence before anchor"
    close_fence = skill_text.find("\n```\n", start)
    assert close_fence != -1, f"{SKILL_MD.name} MOAT_SCORING: no closing fence"
    section = skill_text[open_fence:close_fence]

    for key in required_top_keys:
        assert f'"{key}"' in section, f"{SKILL_MD.name} MOAT_SCORING return shape missing top-level key '{key}'"
    # Per-moat entry fields appear as prose keywords, not necessarily as quoted JSON.
    # 'id' is not explicitly named in the template prose — the moat dimensions are
    # identified by their canonical names (network_effects, etc.), which implicitly
    # serve as 'id'. Only check the fields that score_moats.py validates beyond 'id'.
    required_moat_entry_prose_minus_id = required_moat_entry_prose - {"id"}
    for key in required_moat_entry_prose_minus_id:
        assert re.search(r"\b" + re.escape(key) + r"\b", section), (
            f"{SKILL_MD.name} MOAT_SCORING return shape missing per-moat field '{key}' "
            f"(checked as unquoted prose term; template uses prose for entry fields)"
        )

    # Agent body MOAT_SCORING subtype
    agent_text = AGENT_MD.read_text(encoding="utf-8")
    agent_anchor = "#### MOAT_SCORING subtype"
    agent_start = agent_text.find(agent_anchor)
    assert agent_start != -1, f"{AGENT_MD.name} has no '#### MOAT_SCORING subtype' section"
    next_heading = agent_text.find("\n#### ", agent_start + 1)
    agent_section = (
        agent_text[agent_start:next_heading] if next_heading != -1 else agent_text[agent_start : agent_start + 2000]
    )
    for key in required_top_keys:
        assert f'"{key}"' in agent_section, f"{AGENT_MD.name} MOAT_SCORING subtype missing key '{key}'"


def test_positioning_scoring_dispatch_return_shape_keys() -> None:
    """The POSITIONING_SCORING dispatch template in SKILL.md must include the keys
    score_positioning.py reads from stdin: 'views', 'differentiation_claims',
    'metadata', 'scoring_basis'. Each view must have: 'id', 'x_axis', 'y_axis',
    'points'. Each point must have: 'competitor', 'x', 'y', 'x_evidence', 'y_evidence'.

    'scoring_basis' is asserted explicitly, not just implicitly via the top-key
    set: nothing else in this suite exercises whether the dispatch template
    actually declares the field, and a return shape that documents a key without
    ever writing it produces artifacts that silently lose the field on every
    downstream re-pipe.

    Also verified in the agent body's POSITIONING_SCORING subtype section.
    """
    required_top_keys = {"views", "differentiation_claims", "metadata", "scoring_basis"}
    required_view_keys = {"id", "x_axis", "y_axis", "points"}
    required_point_keys = {"competitor", "x", "y", "x_evidence", "y_evidence"}

    skill_text = SKILL_MD.read_text(encoding="utf-8")
    anchor = "CONTEXT: POSITIONING_SCORING"
    start = skill_text.find(anchor)
    assert start != -1, f"{SKILL_MD.name} has no 'CONTEXT: POSITIONING_SCORING' section"
    # Anchor is inside the template fence.
    open_fence = skill_text.rfind("\n```", 0, start)
    assert open_fence != -1, f"{SKILL_MD.name} POSITIONING_SCORING: no opening fence before anchor"
    close_fence = skill_text.find("\n```\n", start)
    assert close_fence != -1, f"{SKILL_MD.name} POSITIONING_SCORING: no closing fence"
    section = skill_text[open_fence:close_fence]

    for key in required_top_keys:
        assert f'"{key}"' in section, f"{SKILL_MD.name} POSITIONING_SCORING return shape missing top-level key '{key}'"
    for key in required_view_keys:
        assert f'"{key}"' in section, f"{SKILL_MD.name} POSITIONING_SCORING return shape missing view key '{key}'"
    for key in required_point_keys:
        assert f'"{key}"' in section, f"{SKILL_MD.name} POSITIONING_SCORING return shape missing point key '{key}'"

    # Agent body POSITIONING_SCORING subtype
    agent_text = AGENT_MD.read_text(encoding="utf-8")
    agent_anchor = "#### POSITIONING_SCORING subtype"
    agent_start = agent_text.find(agent_anchor)
    assert agent_start != -1, f"{AGENT_MD.name} has no '#### POSITIONING_SCORING subtype' section"
    next_heading = agent_text.find("\n#### ", agent_start + 1)
    agent_section = (
        agent_text[agent_start:next_heading] if next_heading != -1 else agent_text[agent_start : agent_start + 2000]
    )
    for key in required_top_keys:
        assert f'"{key}"' in agent_section, f"{AGENT_MD.name} POSITIONING_SCORING subtype missing key '{key}'"


def test_checklist_dispatch_return_shape_keys() -> None:
    """The CHECKLIST dispatch template in SKILL.md must include 'items' (the only
    top-level key checklist.py reads) and the valid status values from VALID_STATUSES.

    Also verified in the agent body's CHECKLIST subtype.
    """
    mod = _load_checklist_module()
    valid_statuses: frozenset[str] = frozenset(mod.VALID_STATUSES)  # type: ignore[attr-defined]

    skill_text = SKILL_MD.read_text(encoding="utf-8")
    anchor = "CONTEXT: CHECKLIST"
    start = skill_text.find(anchor)
    assert start != -1, f"{SKILL_MD.name} has no 'CONTEXT: CHECKLIST' section"
    # Anchor is inside the template fence.
    open_fence = skill_text.rfind("\n```", 0, start)
    assert open_fence != -1, f"{SKILL_MD.name} CHECKLIST: no opening fence before anchor"
    close_fence = skill_text.find("\n```\n", start)
    assert close_fence != -1, f"{SKILL_MD.name} CHECKLIST: no closing fence"
    section = skill_text[open_fence:close_fence]

    assert '"items"' in section, (
        f"{SKILL_MD.name} CHECKLIST return shape must include 'items' key (checklist.py reads data['items'] from stdin)"
    )
    for status in valid_statuses:
        assert status in section, (
            f"{SKILL_MD.name} CHECKLIST template does not mention status value '{status}' "
            f"— agent must know all valid values to avoid validation errors"
        )

    # Agent body CHECKLIST subtype
    agent_text = AGENT_MD.read_text(encoding="utf-8")
    agent_anchor = "#### CHECKLIST subtype"
    agent_start = agent_text.find(agent_anchor)
    assert agent_start != -1, f"{AGENT_MD.name} has no '#### CHECKLIST subtype' section"
    next_heading = agent_text.find("\n#### ", agent_start + 1)
    agent_section = (
        agent_text[agent_start:next_heading] if next_heading != -1 else agent_text[agent_start : agent_start + 1000]
    )
    assert '"items"' in agent_section, f"{AGENT_MD.name} CHECKLIST subtype missing 'items' key"
    for status in valid_statuses:
        assert status in agent_section, f"{AGENT_MD.name} CHECKLIST subtype does not mention status value '{status}'"


def test_competitor_verification_dispatch_return_shape_keys() -> None:
    """The COMPETITOR_VERIFICATION dispatch template in SKILL.md must include the
    keys verify_competitors.py's validate() reads: top-level 'startup_characterization'
    and 'verdicts' (both unconditionally required — see fixtures/dispatch_contracts.json
    required_fields_minus_metadata), plus 'metadata'. Each verdict entry must carry
    'slug', 'verdict', 'independent_characterization', 'recommended_action' (all
    unconditionally validated) and 'reasoning' (validated for any non-'genuine'
    verdict — the show-your-work gate). 'overlap' and 'confidence' are documented
    but not read by the producer; still checked because dropping them from the
    template silently loses fields the agent body's fuller example specifies.

    The agent body's COMPETITOR_VERIFICATION subtype additionally spells out
    independent_characterization's own sub-keys (buyer, job_to_be_done, category,
    monetization, evidence_source) and the verdict/evidence_source/recommended_action
    enum values actually written there today — SKILL.md's compact template elides
    independent_characterization/overlap to `{...}`, so those sub-keys and enum
    values are only checked against the agent body, not SKILL.md.

    Anchored the same way as the four pre-existing return-shape tests: fence-bounded
    (open = last ``` before the anchor, close = first ``` after it) in SKILL.md;
    bounded to the next `#### ` heading (or a generous fallback) in the agent body.
    """
    required_top_keys = {"startup_characterization", "verdicts", "metadata"}
    required_startup_char_keys = {"buyer", "job_to_be_done", "category", "monetization", "evidence_source"}
    required_verdict_keys = {
        "slug",
        "verdict",
        "independent_characterization",
        "overlap",
        "reasoning",
        "confidence",
        "recommended_action",
    }
    # Sub-keys of independent_characterization and enum values are only spelled
    # out in the agent body's fuller example (SKILL.md elides to `{...}`).
    required_ic_keys = {"buyer", "job_to_be_done", "category", "monetization", "evidence_source"}
    required_verdict_values = {"genuine", "adjacent", "not_a_competitor"}
    required_action_values = {"keep", "reclassify_adjacent", "challenge_removal"}

    skill_text = SKILL_MD.read_text(encoding="utf-8")
    anchor = "CONTEXT: COMPETITOR_VERIFICATION"
    start = skill_text.find(anchor)
    assert start != -1, f"{SKILL_MD.name} has no 'CONTEXT: COMPETITOR_VERIFICATION' section"
    open_fence = skill_text.rfind("\n```", 0, start)
    assert open_fence != -1, f"{SKILL_MD.name} COMPETITOR_VERIFICATION: no opening fence before anchor"
    close_fence = skill_text.find("\n```\n", start)
    assert close_fence != -1, f"{SKILL_MD.name} COMPETITOR_VERIFICATION: no closing fence"
    section = skill_text[open_fence:close_fence]

    for key in required_top_keys:
        assert f'"{key}"' in section, (
            f"{SKILL_MD.name} COMPETITOR_VERIFICATION return shape missing top-level key '{key}'"
        )
    for key in required_startup_char_keys:
        assert f'"{key}"' in section, (
            f"{SKILL_MD.name} COMPETITOR_VERIFICATION return shape missing startup_characterization field '{key}'"
        )
    for key in required_verdict_keys:
        assert f'"{key}"' in section, (
            f"{SKILL_MD.name} COMPETITOR_VERIFICATION return shape missing per-verdict key '{key}'"
        )

    # Agent body COMPETITOR_VERIFICATION subtype
    agent_text = AGENT_MD.read_text(encoding="utf-8")
    agent_anchor = "#### COMPETITOR_VERIFICATION subtype"
    agent_start = agent_text.find(agent_anchor)
    assert agent_start != -1, f"{AGENT_MD.name} has no '#### COMPETITOR_VERIFICATION subtype' section"
    next_heading = agent_text.find("\n#### ", agent_start + 1)
    agent_section = (
        agent_text[agent_start:next_heading] if next_heading != -1 else agent_text[agent_start : agent_start + 2500]
    )
    for key in required_top_keys | required_verdict_keys:
        assert f'"{key}"' in agent_section, f"{AGENT_MD.name} COMPETITOR_VERIFICATION subtype missing key '{key}'"
    for key in required_ic_keys:
        assert f'"{key}"' in agent_section, (
            f"{AGENT_MD.name} COMPETITOR_VERIFICATION subtype missing independent_characterization field '{key}'"
        )
    for value in required_verdict_values:
        assert value in agent_section, (
            f"{AGENT_MD.name} COMPETITOR_VERIFICATION subtype does not mention verdict value '{value}'"
        )
    for value in required_action_values:
        assert value in agent_section, (
            f"{AGENT_MD.name} COMPETITOR_VERIFICATION subtype does not mention recommended_action value '{value}'"
        )


def test_competitor_recall_dispatch_return_shape_keys() -> None:
    """The COMPETITOR_RECALL dispatch template has no unconditionally-required
    top-level field (fixtures/dispatch_contracts.json's required_fields_minus_metadata
    is `[]` by design: diff_recall_gaps() treats missing/empty 'candidates' as a
    legitimate "found nothing" outcome, not an error). But each candidate that
    IS returned has a genuine, producer-checked shape: one missing 'name',
    'why_considered', or a non-empty 'sources' list gets silently DROPPED
    (recorded in the output's 'dropped' array, never surfaced to the founder as
    a recall gap) rather than failing the run. That silent-drop behavior is
    exactly the kind of regression that needs a contract test: a template that
    stops asking for 'sources' would not error anywhere, it would just make
    every candidate quietly vanish downstream.

    SKILL.md's dispatch template describes the candidate shape in prose ("each
    with name, slug (kebab-case), category, why_considered, and at least one
    source URL"), so the SKILL.md side is checked with word-boundary regex on the
    prose terms — the same technique the pre-existing MOAT_SCORING test uses for
    its per-moat prose fields. The agent body's subtype carries a literal ```json
    schema block with quoted keys (including the literal 'sources' key, plural,
    that the prose never spells out) and an enum-valued 'category' field, both
    checked directly.

    Since the 2026-08 remediation the SKILL.md template ALSO carries the Write
    instruction, the JSON return shape and the receipt line — it was previously
    the only one of seven dispatch templates with none of the three, and a live
    run's model hand-authored them, risking drift from the agent body's shape.
    The prose-term assertions below are unaffected (they check presence, and the
    added JSON block sits inside the same fence), so this test still guards the
    silent-drop behaviour it was written for: a candidate missing 'name',
    'why_considered' or a non-empty 'sources' is DROPPED downstream rather than
    failing the run, which is exactly the regression a template that stopped
    asking for sources would cause.
    """
    required_prose_terms = {"name", "slug", "category", "why_considered"}
    required_json_keys = {"candidates", "name", "slug", "category", "why_considered", "sources", "metadata"}
    required_category_values = {"direct", "adjacent", "do_nothing", "emerging"}

    skill_text = SKILL_MD.read_text(encoding="utf-8")
    anchor = "CONTEXT: COMPETITOR_RECALL"
    start = skill_text.find(anchor)
    assert start != -1, f"{SKILL_MD.name} has no 'CONTEXT: COMPETITOR_RECALL' section"
    open_fence = skill_text.rfind("\n```", 0, start)
    assert open_fence != -1, f"{SKILL_MD.name} COMPETITOR_RECALL: no opening fence before anchor"
    close_fence = skill_text.find("\n```\n", start)
    assert close_fence != -1, f"{SKILL_MD.name} COMPETITOR_RECALL: no closing fence"
    section = skill_text[open_fence:close_fence]

    for term in required_prose_terms:
        assert re.search(r"\b" + re.escape(term) + r"\b", section), (
            f"{SKILL_MD.name} COMPETITOR_RECALL template no longer describes candidate field '{term}' "
            f"(checked as unquoted prose term; the template documents the candidate shape in prose, "
            f"not a JSON snippet)"
        )
    # The prose never spells the literal JSON key 'sources' (plural) — it says
    # "at least one source URL" — but dropping the word 'source' entirely would
    # mean the template stopped telling the agent to cite evidence at all.
    assert re.search(r"\bsource\b", section), (
        f"{SKILL_MD.name} COMPETITOR_RECALL template no longer mentions sourcing the candidate "
        f"(diff_recall_gaps() drops any candidate with an empty 'sources' list)"
    )

    # Agent body COMPETITOR_RECALL subtype
    agent_text = AGENT_MD.read_text(encoding="utf-8")
    agent_anchor = "#### COMPETITOR_RECALL subtype"
    agent_start = agent_text.find(agent_anchor)
    assert agent_start != -1, f"{AGENT_MD.name} has no '#### COMPETITOR_RECALL subtype' section"
    next_heading = agent_text.find("\n#### ", agent_start + 1)
    agent_section = (
        agent_text[agent_start:next_heading] if next_heading != -1 else agent_text[agent_start : agent_start + 2000]
    )
    for key in required_json_keys:
        assert f'"{key}"' in agent_section, f"{AGENT_MD.name} COMPETITOR_RECALL subtype missing key '{key}'"
    for value in required_category_values:
        assert value in agent_section, (
            f"{AGENT_MD.name} COMPETITOR_RECALL subtype does not mention candidate category value '{value}'"
        )


# ---------------------------------------------------------------------------
# Test 5: No-file-writes instruction in Context A dispatch templates
# ---------------------------------------------------------------------------


def test_context_a_dispatch_templates_contain_no_write_instruction() -> None:
    """All Context A dispatch templates in SKILL.md must explicitly forbid artifact
    writes — a sub-agent writing files directly bypasses schema validation and
    run_id stamping.

    Templates checked: LANDSCAPE_RESEARCH, MOAT_SCORING, POSITIONING_SCORING,
    CHECKLIST. Each bounded at its closing ``` fence.
    """
    skill_text = SKILL_MD.read_text(encoding="utf-8")

    for context_name in ("LANDSCAPE_RESEARCH", "MOAT_SCORING", "POSITIONING_SCORING", "CHECKLIST"):
        anchor = f"CONTEXT: {context_name}"
        start = skill_text.find(anchor)
        assert start != -1, f"{SKILL_MD.name} has no '{anchor}' section"

        # All four Context A templates have the anchor inside the code fence.
        # Use rfind to locate the opening fence (last \n``` before the anchor)
        # and find for the closing fence (first \n```\n after the anchor).
        open_fence = skill_text.rfind("\n```", 0, start)
        assert open_fence != -1, f"{SKILL_MD.name} {context_name}: no opening ``` fence before anchor"
        close_fence = skill_text.find("\n```\n", start)
        assert close_fence != -1, f"{SKILL_MD.name} {context_name}: no closing ``` fence"
        section = skill_text[open_fence:close_fence]

        assert "Do NOT write" in section or "do not write" in section.lower(), (
            f"{SKILL_MD.name} {context_name} dispatch template must explicitly forbid "
            f"artifact writes (search region is the template body, bounded by its fences)"
        )


def test_agent_body_context_a_hard_rules_contain_bash_ban_and_no_write() -> None:
    """The agent body's Context A hard-rules block must forbid writing artifacts
    to disk and forbid Bash calls.

    Anchor: '### Context A' section, bounded at '### Context B'.
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

    Anchor on '**Hard rules in this context:**' subheading inside Context B.
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
    instruction. Forward-looking: fires if a reference doc gains a template
    without the instruction.
    """
    ref_docs = _ref_docs_with_dispatch_templates()
    for ref_doc in ref_docs:
        text = ref_doc.read_text(encoding="utf-8")
        for block_start_idx in [m.start() for m in re.finditer(r"CONTEXT:", text)]:
            section = text[block_start_idx : block_start_idx + 2000]
            assert "Do NOT write" in section or "do not write" in section.lower(), (
                f"{ref_doc.name}: dispatch template at char {block_start_idx} "
                f"is missing 'Do NOT write artifacts' instruction"
            )


# ---------------------------------------------------------------------------
# Test 6: Gate-required artifacts and cleanup coverage
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


def test_compose_required_artifacts_count_and_names() -> None:
    """compose_report.py REQUIRED_ARTIFACTS must contain exactly 5 entries —
    the 5 per-step producer artifacts for competitive-positioning.
    """
    mod = _load_compose_report_module()
    required: list[str] = mod.REQUIRED_ARTIFACTS  # type: ignore[attr-defined]
    expected = {
        "landscape.json",
        "positioning.json",
        "moat_scores.json",
        "positioning_scores.json",
        "checklist.json",
    }
    assert set(required) == expected, (
        f"compose_report.py REQUIRED_ARTIFACTS mismatch:\n  expected: {sorted(expected)}\n  got: {sorted(required)}"
    )


def test_overwrite_in_place_no_outputs_delete() -> None:
    """Cowork-parity: competitive-positioning must NOT bash-`rm` prior artifacts
    under `$ANALYSIS_DIR` (the promoted outputs/ tree) and must NOT stage scratch
    there. It overwrites-in-place (producers rewrite via `-o`; compose's
    STALE_ARTIFACT run_id check backstops a skipped-step leftover) and stages in
    a `/tmp` `$STAGING_DIR`. Replaces the old `rm -f` cleanup-coverage test —
    deleting under outputs/ is the regression now, not an uncovered artifact.
    """
    skill_text = SKILL_MD.read_text(encoding="utf-8")
    assert not re.search(r"\brm\b[^\n`]*\$\{?ANALYSIS_DIR\b", skill_text), (
        f"{SKILL_MD.name}: bash `rm` of $ANALYSIS_DIR (promoted outputs/) — overwrite-in-place instead"
    )
    assert not re.search(r"\$\{?ANALYSIS_DIR\}?/\.staging", skill_text), (
        f"{SKILL_MD.name}: stages scratch under $ANALYSIS_DIR — use a /tmp $STAGING_DIR"
    )
    assert re.search(r'STAGING_DIR="\$\(mktemp -d', skill_text), (
        f"{SKILL_MD.name}: expected a `$STAGING_DIR` mktemp'd under /tmp for sub-agent scratch"
    )


def test_staging_dir_is_tmp_not_outputs() -> None:
    """Sub-agent JSON staging must be a `/tmp` `$STAGING_DIR` (mktemp'd), never a
    `.staging` subdir of the promoted outputs/ work dir, and must never be `rm`'d
    (the sandbox reclaims /tmp). Inverts the old created-and-removed-under-outputs
    contract.
    """
    skill_text = SKILL_MD.read_text(encoding="utf-8")
    assert re.search(r'STAGING_DIR="\$\(mktemp -d "?\$\{TMPDIR:-/tmp\}', skill_text), (
        f"{SKILL_MD.name} must mktemp a /tmp $STAGING_DIR for sub-agent JSON staging"
    )
    assert not re.search(r"rm -rf [^\n]*\.staging", skill_text), (
        f"{SKILL_MD.name} must NOT `rm -rf` a .staging path — scratch lives in /tmp, reclaimed by the sandbox"
    )


# ---------------------------------------------------------------------------
# Test 7: No shell-variable capture of python output
# ---------------------------------------------------------------------------


def test_no_shell_variable_capture_of_python_output() -> None:
    """Each Bash call runs in a fresh shell; capturing python output into a shell
    variable makes it invisible to any subsequent Bash call. No carve-outs.

    The house pattern fires on any assignment of the form VAR="$(python3 ..." or
    VAR="$(python ...". Infrastructure captures like SCRIPTS="$(find ...)" and
    RUN_ID="$(date ...)" do NOT match (not python3/python invocations).

    Known drift that was fixed: COACHING_PAYLOAD="$(python3 -c '...')" at
    Step 7c has been replaced with a direct print + "Never capture" instruction
    matching the cap-table SKILL.md pattern.
    """
    skill_text = SKILL_MD.read_text(encoding="utf-8")
    assert not re.search(r'\w+="\$\(\s*python3?', skill_text), (
        "SKILL.md captures python output into a shell variable — print it instead. "
        "Zero carve-outs: the house-pattern regression guard fires on any match."
    )


def test_never_capture_instruction_is_present_in_step7c() -> None:
    """After the coaching_payload bash block in Step 7c, SKILL.md must have a
    'Never capture it into a shell variable' instruction (cap-table pattern).

    This test is the positive counterpart to test_no_shell_variable_capture: it
    verifies the fix is present, not just that the bad pattern is absent.
    """
    skill_text = SKILL_MD.read_text(encoding="utf-8")
    # Anchor on the Step 7c HEADING, not on the first mention of the dispatch name. The name is
    # also mentioned in the founder-facing narration rule near the top of the file, and anchoring
    # on the first occurrence silently relocated this assertion into Step 3.6 — where it failed on
    # content that was still present in Step 7c. Bound on structure, never on first-match.
    step7c = skill_text.find("**7c — Post-Compose Coaching Commentary")
    assert step7c != -1, f"{SKILL_MD.name} has no '7c — Post-Compose Coaching Commentary' heading"
    anchor = "<!-- skill-quality-ci: bash-after-subagent-ok -->"
    start = skill_text.find(anchor, step7c)
    assert start != -1, f"{SKILL_MD.name} has no 'skill-quality-ci: bash-after-subagent-ok' marker in Step 7c"
    # The instruction should appear within a few hundred chars of the marker
    section = skill_text[start : start + 500]
    assert "Never capture" in section or "never capture" in section.lower(), (
        f"{SKILL_MD.name} Step 7c is missing 'Never capture it into a shell variable' instruction "
        f"after the coaching_payload bash block (cap-table pattern required)"
    )


# ---------------------------------------------------------------------------
# Test 8: Flag/choice existence
# ---------------------------------------------------------------------------


def test_bash_flags_exist_in_scripts() -> None:
    """Every --flag used in a bash invocation of a CP script in SKILL.md must
    exist in that script's argparse add_argument definitions.

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
    """Forward-looking: every --flag used in a bash invocation of a CP script
    inside any reference doc must exist in that script's argparse.
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
                continue

            defined_flags = _collect_argparse_flags(script_path)
            phantom_flags = flags_used - defined_flags
            assert not phantom_flags, (
                f"{ref_doc.name}: {script_name} invocation uses flags not defined in argparse:\n"
                f"  phantom: {sorted(phantom_flags)}\n"
                f"  defined: {sorted(defined_flags)}"
            )


def test_producer_scripts_define_run_id_flag() -> None:
    """The producer scripts that inject run_id into output artifacts must
    define --run-id as an argparse argument.

    validate_landscape.py, score_moats.py, score_positioning.py, and checklist.py
    all stamp metadata.run_id via the --run-id CLI flag.
    """
    for script_name in ("validate_landscape.py", "score_moats.py", "score_positioning.py", "checklist.py"):
        script_path = SCRIPTS_DIR / script_name
        defined_flags = _collect_argparse_flags(script_path)
        assert "--run-id" in defined_flags, (
            f"{script_name} is missing --run-id argparse definition — run_id injection contract is broken"
        )


# ---------------------------------------------------------------------------
# Test 9: Context B / coaching payload
# ---------------------------------------------------------------------------


def test_post_compose_coaching_dispatch_includes_coaching_payload_keys() -> None:
    """The POST_COMPOSE_COACHING dispatch template in SKILL.md must list the
    coaching_payload keys the agent consumes for commentary composition.

    Search region: from the opening ``` fence of the dispatch template to the
    template's own closing ``` fence. This excludes any text after the template
    (Main-Thread Return prose) so a key present only after the template cannot
    satisfy the check.

    The payload is STAGED as a file and Read by the sub-agent (not pasted), so the template
    documents the CONSUMED keys in its procedure step; the mechanics keys
    (review_dir / report_path / insertion_marker) are documented in the agent
    body as ignore-these, and insertion_marker feeds the main thread's
    insert_coaching.py invocation after the template.
    """
    consumed_keys = {
        "summary",
        "failed_items",
        "warned_items",
        "high_severity_warnings",
        "company_name",
    }
    mechanics_keys = {"review_dir", "report_path", "insertion_marker"}

    skill_text = SKILL_MD.read_text(encoding="utf-8")

    # Find the POST_COMPOSE_COACHING dispatch template block.
    pc_anchor = "CONTEXT: POST_COMPOSE_COACHING"
    pc_start = skill_text.find(pc_anchor)
    assert pc_start != -1, f"{SKILL_MD.name} has no 'CONTEXT: POST_COMPOSE_COACHING' section"

    # The dispatch label just before the template fence. The label may carry a
    # parenthetical qualifier after the bold phrase (e.g. "... (substitute
    # `<HANDOFF_AGENT>` with ...):"), so match on the bold phrase alone.
    disp_label = "**Dispatch prompt template**"
    label_pos = skill_text.find(disp_label, max(0, pc_start - 400))
    if label_pos == -1:
        label_pos = skill_text.find(disp_label, pc_start)
    assert label_pos != -1, f"{SKILL_MD.name} POST_COMPOSE_COACHING section has no '**Dispatch prompt template**' label"
    open_fence = skill_text.find("\n```\n", label_pos)
    assert open_fence != -1, f"{SKILL_MD.name} no opening ``` fence after '**Dispatch prompt template**'"
    close_fence = skill_text.find("\n```\n", open_fence + 4)
    assert close_fence != -1, f"{SKILL_MD.name} no closing ``` fence for POST_COMPOSE_COACHING template"

    # The search region is the content inside the fence
    fence_body = skill_text[open_fence + 4 : close_fence]

    # Stop at 'Return:' line if present to avoid keys in the Return block
    # satisfying the check (market-sizing pattern)
    return_line_pos = fence_body.find("\nReturn:")
    section = fence_body[:return_line_pos] if return_line_pos != -1 else fence_body

    for key in consumed_keys:
        assert key in section, (
            f"{SKILL_MD.name} POST_COMPOSE_COACHING dispatch template is missing "
            f"coaching_payload key '{key}' — search region is the template body "
            f"before the 'Return:' line (chars {open_fence}–{close_fence})"
        )

    # insertion_marker feeds insert_coaching.py --marker in the same step;
    # bound at the next '### ' step heading.
    step_end = skill_text.find("\n### ", pc_start)
    step_section = skill_text[pc_start:step_end] if step_end != -1 else skill_text[pc_start:]
    assert "insertion_marker" in step_section, (
        f"{SKILL_MD.name} Step 7c does not reference insertion_marker for the insert_coaching.py invocation"
    )

    # Agent body Context B procedure documents the full key set
    agent_text = AGENT_MD.read_text(encoding="utf-8")
    agent_anchor = "### Context B"
    agent_start = agent_text.find(agent_anchor)
    assert agent_start != -1, f"{AGENT_MD.name} has no '### Context B' section"
    agent_section = agent_text[agent_start : agent_start + 6000]

    for key in consumed_keys | mechanics_keys:
        assert key in agent_section, f"{AGENT_MD.name} Context B procedure is missing coaching_payload key '{key}'"


def test_coaching_payload_schema_version_is_competitive_positioning() -> None:
    """compose_report.py's schema_version literal must end with
    '-competitive-positioning' (skill-specific suffix).

    Two-surface sync: the agent body's Context B procedure documents the
    coaching_payload keys it consumes but does not repeat the schema_version
    literal — so this test is single-surface (script only). The suffix check
    prevents cross-skill payload misinterpretation.
    """
    src = (SCRIPTS_DIR / "compose_report.py").read_text(encoding="utf-8")

    m_script = re.search(r'"schema_version"\s*:\s*"([^"]+)"', src)
    assert m_script, (
        'compose_report.py has no \'"schema_version": "..."\' literal — _emit_coaching_payload may have been refactored'
    )
    script_literal = m_script.group(1)

    assert script_literal.endswith("-competitive-positioning"), (
        f"compose_report.py coaching_payload schema_version '{script_literal}' "
        f"does not end with '-competitive-positioning' — wrong skill or missing suffix"
    )


def test_context_b_commentary_payload_keys() -> None:
    """The Context B receipt is EXACTLY {status, output_path} — parsed, not substring-matched.

    The commentary itself is written to OUTPUT_PATH as raw markdown; the JSON envelope is built by
    the main thread's md_to_commentary.py adapter. That "no envelope here" half is now a fleet-wide
    whole-file guard — see
    test_handoff_contract_ratchet.py::test_context_b_never_asks_for_the_json_commentary_envelope.
    It moved because the old form asserted it over a fixed 1000-char window (cap-table 2000) with a
    measured 42-73% blind zone: inserting the token past the offset left every one of the six green.

    What stays here is the per-skill SHAPE, and it PARSES the receipt rather than slicing it.
    Slicing is what kept failing — an unguarded `find` used as a slice bound is the same vacuity
    class as a fixed window. Measured on the old form: delete the receipt fence's closing backticks
    and the extracted block silently grew 71 -> 155 chars with both keys still present, GREEN.
    json.loads() cannot widen (a run-on block does not parse), and set equality catches a missing
    key AND an extra one — including commentary_markdown re-entering the receipt itself.
    """
    agent_text = AGENT_MD.read_text(encoding="utf-8")
    anchor = "#### 2. Write the commentary to OUTPUT_PATH, then return a receipt"
    start = agent_text.find(anchor)
    assert start != -1, f"{AGENT_MD.name} has no '{anchor}' section"
    # Every find() below is checked before use as an index. `find` returns -1 on a miss, and -1 as
    # a slice bound silently WIDENS the window rather than failing — measured 3109 -> 6364 chars.
    end = agent_text.find("\n## ", start + len(anchor))
    assert end != -1, f"{AGENT_MD.name}: the Context B section has no terminating heading"
    section = agent_text[start:end]

    fence = section.find("```json")
    assert fence != -1, f"{AGENT_MD.name}: the Context B section has no ```json receipt fence"
    close = section.find("```", fence + len("```json"))
    assert close != -1, f"{AGENT_MD.name}: the ```json receipt fence is never closed"

    receipt = json.loads(section[fence + len("```json") : close])
    assert set(receipt) == {"status", "output_path"}, (
        f"{AGENT_MD.name} Context B receipt keys are {sorted(receipt)}, expected "
        "['output_path', 'status'] — the receipt is the ONLY thing the sub-agent returns"
    )

    # SKILL.md Main-Thread Return section must still present the headline keys
    # (sourced from coaching_payload / producer artifacts / the receipt)
    skill_text = SKILL_MD.read_text(encoding="utf-8")
    main_thread_anchor = "## Main-Thread Return"
    mt_start = skill_text.find(main_thread_anchor)
    assert mt_start != -1, f"{SKILL_MD.name} has no '## Main-Thread Return' section"
    mt_section = skill_text[mt_start : mt_start + 2000]
    for key in {"overall_status", "high_severity_warnings", "moat_scores.json"}:
        assert key in mt_section, f"{SKILL_MD.name} Main-Thread Return section does not mention '{key}'"


def test_run_id_parity_artifact_list_matches_producer_artifacts() -> None:
    """run_id parity is verified script-side by insert_coaching.py. Two
    surfaces must list exactly the 5 producer artifacts: landscape.json,
    positioning.json, moat_scores.json, positioning_scores.json,
    checklist.json.

    1. SKILL.md Step 7c's insert_coaching.py invocation — the
       `--verify-artifact` flags (the operative gate).
    2. The agent body's Context B prose list (informational; keeps the
       agent's mental model in sync).

    report.json is excluded (compose-side aggregator with no run_id by
    design).
    """
    producer_artifacts = frozenset(
        {
            "landscape.json",
            "positioning.json",
            "moat_scores.json",
            "positioning_scores.json",
            "checklist.json",
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
    agent_artifacts = frozenset(re.findall(r"\b([a-z_]+\.json)\b", agent_text[start:close]))

    phantom = agent_artifacts - producer_artifacts
    missing = producer_artifacts - agent_artifacts

    assert not phantom, (
        f"{AGENT_MD.name} run_id parity bullet list references artifacts not among the 5 "
        f"producer artifacts (phantom): {sorted(phantom)}"
    )
    assert not missing, (
        f"{AGENT_MD.name} run_id parity bullet list is missing producer artifacts "
        f"(missing from parity check): {sorted(missing)}"
    )


# ---------------------------------------------------------------------------
# Test 10: EVID gating semantics
# ---------------------------------------------------------------------------


def test_evid_gating_mode_table_matches_script_exactly() -> None:
    """checklist.py's MODE_GATING dict is the canonical source of truth for
    which IDs are gated per mode.  checklist-criteria.md's gating table must
    match it exactly, per mode (set equality).

    This test is the set-equality companion to the subset test in
    test_mode_gating_table_in_checklist_criteria_md_matches_script — the subset
    test catches phantoms (doc has IDs not in script); this one catches both
    directions and is mutation-resistant.

    Mutation guard:
    - Add a phantom ID to the doc's gating bullet → fail (phantom in doc)
    - Remove an ID from the doc that the script still gates → fail (missing from doc)
    - Add an ID to script's MODE_GATING without updating doc → fail (missing from doc)
    """
    mod = _load_checklist_module()
    mode_gating: dict[str, set[str]] = {k: set(v) for k, v in mod.MODE_GATING.items()}  # type: ignore[attr-defined]

    criteria_text = (REFS_DIR / "checklist-criteria.md").read_text(encoding="utf-8")

    for mode, expected_gated in mode_gating.items():
        pattern = re.compile(rf"\*\*`{re.escape(mode)}`\*\*:\s*(.+?)(?:\n|$)")
        m = pattern.search(criteria_text)
        assert m is not None, f"checklist-criteria.md has no gated-items bullet for mode '{mode}'"
        line = m.group(1)
        extracted_ids = set(re.findall(r"`([A-Z]+_\d+)`", line))

        phantom = extracted_ids - expected_gated
        missing = expected_gated - extracted_ids

        assert not phantom, (
            f"checklist-criteria.md mode '{mode}' gating table has phantom IDs "
            f"not in checklist.py MODE_GATING: {sorted(phantom)}"
        )
        assert not missing, (
            f"checklist-criteria.md mode '{mode}' gating table is missing IDs "
            f"from checklist.py MODE_GATING: {sorted(missing)}"
        )


def test_checklist_criteria_md_producer_applies_gating() -> None:
    """checklist-criteria.md states that the agent assesses items and checklist.py
    validates structure and computes the score — NOT that the agent applies gating.
    This documents the producer contract: gating is applied BY the producer script
    (checklist.py), not by the sub-agent.

    The criteria doc must not be read by the sub-agent as a gating instruction.
    The doc's header must describe the agent as assessor and checklist.py as the
    validator/gater so the roles are unambiguous. The Mode Gating section must be
    present to document the mechanism.

    We check that checklist-criteria.md's header describes the agent as assessor
    and the script as validator/gater — not the agent as gater.
    """
    criteria_text = (REFS_DIR / "checklist-criteria.md").read_text(encoding="utf-8")

    # The header (first ~5 lines) should say the agent assesses and checklist.py validates
    header = criteria_text[:500]
    assert "agent" in header.lower() and "checklist.py" in header, (
        "checklist-criteria.md header must describe the agent as assessor and "
        "checklist.py as validator — producer/consumer contract documentation"
    )

    # The Mode Gating Table section title must be present — it's the mechanism doc
    assert "Mode Gating" in criteria_text or "mode gating" in criteria_text.lower(), (
        "checklist-criteria.md must have a 'Mode Gating' section describing gating rules"
    )


# ---------------------------------------------------------------------------
# Test 11: Warning code enumeration — compose_report.py WARNING_SEVERITY vs docs
# ---------------------------------------------------------------------------


def test_warning_severity_codes_match_artifact_schemas_md() -> None:
    """compose_report.py's WARNING_SEVERITY dict is the canonical source for
    warning codes.  artifact-schemas.md's Warning Severity Reference section
    enumerates codes in the severity-table rows.  Codes in table rows must exist
    in WARNING_SEVERITY.

    Extraction is restricted to the table rows in the Warning Severity Reference
    section (lines starting with '| `CODE`') to avoid false positives from
    other backtick-quoted identifiers like `ANALYSIS_DIR` or `COVER_01`.

    This is a phantom-only check (no missing check) because artifact-schemas.md
    may not enumerate every low/info code, only the reportable ones.

    Vacuity guard: at least 5 warning codes must be found in the table rows.
    """
    mod = _load_compose_report_module()
    canonical_codes: set[str] = set(mod.WARNING_SEVERITY.keys())  # type: ignore[attr-defined]

    schemas_text = (REFS_DIR / "artifact-schemas.md").read_text(encoding="utf-8")

    # Restrict extraction to table rows: lines like `| `MISSING_LANDSCAPE` | high | ... |`
    # Also pick up the inline list in item 9 (comma-separated backtick-quoted codes).
    # We search for backtick-quoted ALL_CAPS_WITH_UNDERSCORE tokens that appear
    # immediately after a `|` or `,` separator (table cell or list item).
    table_row_codes: set[str] = set()

    # Table rows: | `CODE` |  (pipe then optional space then backtick)
    table_row_codes.update(re.findall(r"\|\s*`([A-Z][A-Z0-9_]{2,})`\s*\|", schemas_text))

    # Inline prose list in item 9 and similar: `: `CODE`,` or `CODE`.` etc.
    # Pattern: backtick-quoted, preceded by space/colon/comma, followed by comma/period/space
    inline_codes = re.findall(r"[,: ]`([A-Z][A-Z0-9_]{2,})`[,. ]", schemas_text)
    # Keep only codes whose prefix matches a known warning-code prefix so that
    # infrastructure identifiers like ANALYSIS_DIR are excluded.
    _WARNING_PREFIXES = frozenset(
        {
            "MISSING_",
            "CORRUPT_",
            "STALE_",
            "UNVALIDATED_",
            "SHALLOW_",
            "VANITY_",
            "MOAT_",
            "RESEARCH_",
            "INCOMPLETE_",
            "FOUNDER_",
            "MARKER_",
            "SEQUENTIAL_",
            "CHECKLIST_",
        }
    )
    for c in inline_codes:
        if any(c.startswith(p) for p in _WARNING_PREFIXES):
            table_row_codes.add(c)

    assert len(table_row_codes) >= 5, (
        f"artifact-schemas.md has only {len(table_row_codes)} warning codes in table rows "
        f"(expected >=5). Table-row regex may have stopped matching."
    )

    phantom = table_row_codes - canonical_codes
    assert not phantom, (
        f"artifact-schemas.md references warning codes not in compose_report.py WARNING_SEVERITY "
        f"(phantom — rename or remove): {sorted(phantom)}"
    )


def test_warning_severity_high_codes_are_present() -> None:
    """compose_report.py's high-severity blocking codes must all be present in
    WARNING_SEVERITY. Count guard: at least 7 high-severity codes expected.

    The exact codes are extracted from the script at test time — never hardcoded
    — so a silent deletion triggers the count guard.
    """
    mod = _load_compose_report_module()
    warning_severity: dict[str, str] = mod.WARNING_SEVERITY  # type: ignore[attr-defined]

    high_codes = [code for code, sev in warning_severity.items() if sev == "high"]
    assert len(high_codes) >= 7, (
        f"compose_report.py has only {len(high_codes)} high-severity warning codes "
        f"(expected >=7); a silent deletion may have occurred"
    )

    # The three artifact-integrity codes drive main-thread remediation
    # instructions in SKILL.md (run_id parity, re-running producers instead of
    # hand-editing artifacts) — each must be named in the prose so the
    # executing model can map a compose warning back to its fix.
    combined = SKILL_MD.read_text(encoding="utf-8") + "\n" + AGENT_MD.read_text(encoding="utf-8")
    for code in ("STALE_ARTIFACT", "CORRUPT_ARTIFACT", "UNVALIDATED_ARTIFACT"):
        assert code in combined, (
            f"Neither SKILL.md nor agent body mentions high-severity code {code!r} — "
            f"the executing model cannot map this compose warning to its remediation"
        )


def test_landscape_research_template_stamps_sourced_fields_count() -> None:
    """CP-9: validate_landscape.py requires sourced_fields_count per competitor
    (PROVENANCE_FIELDS); the LANDSCAPE_RESEARCH dispatch template must instruct the
    sub-agent to stamp it, else the field is missing and a wasted repair dispatch results."""
    skill = SKILL_MD.read_text(encoding="utf-8")
    assert "sourced_fields_count" in skill, (
        "LANDSCAPE_RESEARCH template omits sourced_fields_count — validate_landscape.py "
        "requires it (PROVENANCE_FIELDS); the sub-agent will never stamp it"
    )


def test_step1_deck_derive_carveout_present() -> None:
    """X-5: Step 1 must NOT unconditionally gate on AskUserQuestion when the provided
    materials state name/stage/sector/geography — derive them instead, field-by-field
    (non-binary carve-out: derive the ones present, infer/ask only the missing)."""
    skill = SKILL_MD.read_text(encoding="utf-8")
    assert "derive each of the four basics" in skill and "field-by-field" in skill, (
        "Step 1 lacks the (non-binary) deck/materials carve-out (X-5): when the provided materials "
        "state the four basics, derive them field-by-field rather than always calling AskUserQuestion"
    )


# ---------------------------------------------------------------------------
# Test 11: Step 4 additions gate is slot-conditional, cap matches the validator
# ---------------------------------------------------------------------------


def test_step4_additions_gate_is_slot_conditional_and_cap_matches_validator() -> None:
    """The Step 4 suggested_additions mini-gate must never offer an option that
    cannot execute (the original defect: 'Include all' rendered even when the
    combined count exceeded the landscape maximum). The option list must
    branch on open slots, and the cap number the prose cites must be pulled
    live from validate_landscape.MAX_COMPETITORS — a hardcoded literal that
    drifts from the validator would desync silently (same principle as the
    VALID_STATUSES precedent in test_checklist_dispatch_return_shape_keys)."""
    mod = _load_validate_landscape_module()
    max_competitors: int = mod.MAX_COMPETITORS  # type: ignore[attr-defined]
    assert max_competitors > 0, "MAX_COMPETITORS must be a positive int — check validate_landscape.py"

    skill_text = SKILL_MD.read_text(encoding="utf-8")
    start = skill_text.index("### Step 4: Research & Enrich Competitors")
    end = skill_text.index("### Gate 2: Founder Validation of Axis Selection", start)
    block = skill_text[start:end]

    assert f"slots = {max_competitors} (the landscape maximum" in block, (
        f"Step 4's open-slots computation must cite {max_competitors} (validate_landscape.MAX_COMPETITORS) "
        f"— a hardcoded number here can silently drift from the validator if MAX_COMPETITORS changes."
    )

    # The option list must branch on slots — not just avoid rendering "Include all"
    # unconditionally (that string absence is not statically decidable and would be
    # a vacuous proximity check). Each row of the slot-conditional table must be present.
    for phrase in (
        "some, but not all, fit",
        "no slots are open",
        "Include top <slots>",
        "Free a slot by merging",
        "must never appear when it cannot execute",
    ):
        assert phrase in block, f"Step 4 additions gate missing slot-conditional branch text: {phrase!r}"


# ---------------------------------------------------------------------------
# Test 12: CHECKLIST dispatch reads all six artifacts NARR_03 needs
# ---------------------------------------------------------------------------


def test_checklist_dispatch_reads_all_six_artifacts_for_narr_03() -> None:
    """The CHECKLIST dispatch template (SKILL.md) and the agent body's CHECKLIST
    subtype must both instruct reading all six artifacts — landscape.json,
    positioning.json, moat_scores.json, positioning_scores.json,
    product_profile.json, and landscape_draft.json — and must name
    deck_competition_slide / deck_competitors_excluded. Without the last two
    reads and fields, NARR_03 (competition-slide alignment) has nothing to
    grade in deck mode."""
    required_reads = (
        "landscape.json",
        "positioning.json",
        "moat_scores.json",
        "positioning_scores.json",
        "product_profile.json",
        "landscape_draft.json",
    )

    skill_text = SKILL_MD.read_text(encoding="utf-8")
    anchor = "CONTEXT: CHECKLIST"
    start = skill_text.find(anchor)
    assert start != -1, f"{SKILL_MD.name} has no 'CONTEXT: CHECKLIST' section"
    open_fence = skill_text.rfind("\n```", 0, start)
    assert open_fence != -1, f"{SKILL_MD.name} CHECKLIST: no opening fence before anchor"
    close_fence = skill_text.find("\n```\n", start)
    assert close_fence != -1, f"{SKILL_MD.name} CHECKLIST: no closing fence"
    section = skill_text[open_fence:close_fence]

    for artifact in required_reads:
        assert artifact in section, f"{SKILL_MD.name} CHECKLIST dispatch template missing read of {artifact!r}"
    assert "deck_competition_slide" in section, (
        f"{SKILL_MD.name} CHECKLIST dispatch template must name deck_competition_slide (NARR_03's data source)"
    )
    assert "deck_competitors_excluded" in section, (
        f"{SKILL_MD.name} CHECKLIST dispatch template must name deck_competitors_excluded (NARR_03's data source)"
    )

    agent_text = AGENT_MD.read_text(encoding="utf-8")
    agent_anchor = "#### CHECKLIST subtype"
    agent_start = agent_text.find(agent_anchor)
    assert agent_start != -1, f"{AGENT_MD.name} has no '#### CHECKLIST subtype' section"
    next_heading = agent_text.find("\n#### ", agent_start + 1)
    agent_section = (
        agent_text[agent_start:next_heading] if next_heading != -1 else agent_text[agent_start : agent_start + 2000]
    )

    for artifact in required_reads:
        assert artifact in agent_section, f"{AGENT_MD.name} CHECKLIST subtype missing read of {artifact!r}"
    assert "deck_competition_slide" in agent_section, (
        f"{AGENT_MD.name} CHECKLIST subtype must name deck_competition_slide (NARR_03's data source)"
    )
    assert "deck_competitors_excluded" in agent_section, (
        f"{AGENT_MD.name} CHECKLIST subtype must name deck_competitors_excluded (NARR_03's data source)"
    )


# ---------------------------------------------------------------------------
# Test 13: Gate 3 (Positioning Reality Check) exists, two-step, provisional threshold
# ---------------------------------------------------------------------------


def test_gate3_positioning_reality_check_two_step_and_provisional_threshold() -> None:
    """Gate 3 must exist, follow the same chat-message-THEN-AskUserQuestion
    two-step shape Gates 1 and 2 use (not a single-step prompt), and mark the
    <25% overall-differentiation trigger as provisional — it is calibrated on
    a single observed run, and the repo's own >=2-run reproduction bar forbids
    shipping it as a settled threshold."""
    skill_text = SKILL_MD.read_text(encoding="utf-8")
    anchor = "### Gate 3: Positioning Reality Check"
    start = skill_text.find(anchor)
    assert start != -1, f"{SKILL_MD.name} has no '### Gate 3: Positioning Reality Check' section"
    end = skill_text.find("\n### Step 6", start)
    assert end != -1, f"{SKILL_MD.name}: could not find the section following Gate 3"
    block = skill_text[start:end]

    assert "Step A:" in block, "Gate 3 must have a Step A (chat message) before the question"
    assert "Step B:" in block, "Gate 3 must have a Step B (AskUserQuestion), separate from Step A"
    assert "AskUserQuestion" in block, "Gate 3's Step B must call AskUserQuestion"
    # RETARGETED. This used to assert the literal tokens "PROVISIONAL" and "25%" inside the SKILL.md
    # block — i.e. it required the threshold arithmetic to be RESTATED here, next to the sentence that
    # says "Do NOT re-derive it here". That duplication then drifted: SKILL.md described the trade-off
    # trigger's strong side as top-2 while `gate3_triggers.py` had already corrected it to top-tercile,
    # its own docstring recording top-2 as WRONG (it excludes 3rd of 11, the exact shape the trigger was
    # added for). The prose was kept in step with a test rather than with the code.
    #
    # The numbers now live only in the script, whose suite exercises them exhaustively on synthetic
    # inputs. What SKILL.md still owes the founder is the RELAY: a `provisional` trigger must be
    # presented as a soft signal, not a settled finding.
    assert "provisional" in block.lower(), (
        "Gate 3 must tell the model to relay the script's `provisional` flag — a trigger calibrated on a "
        "single observed run must reach the founder as a soft signal, not a settled finding"
    )
    assert "25%" not in block, (
        "Gate 3 must NOT restate the script's thresholds. gate3_triggers.py owns them and is "
        "exhaustively tested; a copy here is what drifted last time (SKILL.md said top-2 where the "
        "script had already moved to top-tercile). Name the triggers, not their arithmetic."
    )
