"""Drift-contract tests for the market-sizing skill.

These tests grep SKILL.md and the agent body against the producer scripts'
actual source so the dispatch prompts can never silently diverge from what
the scripts accept.

Covered contract surfaces:
1. Checklist ID enumeration: every checklist ID cited in prose must exist in
   checklist.py's canonical VALID_IDS set (populated independently of that set);
   pitfalls-checklist.md section IDs must equal VALID_IDS exactly (set equality);
   artifact-schemas.md "Canonical 22 checklist IDs" section IDs must also match.
   Count guards: exactly 22 IDs expected in every enumeration source.
2. Dispatch return shapes: TOP_DOWN_METHODOLOGY, BOTTOM_UP_METHODOLOGY,
   SENSITIVITY_TEST, CHECKLIST, and POST_COMPOSE_COACHING templates must carry
   the keys the consuming scripts read, including metadata.run_id parity.
   Fence-bounded search region for POST_COMPOSE_COACHING.
3. Confidence enum values: sensitivity.py CONFIDENCE_MIN_RANGE keys are the
   canonical confidence values; prose in SKILL.md and agent body must cite them
   all; dispatch templates must show all three values (pipe-separated or explicit).
4. No-file-writes instruction: every Context A dispatch template in SKILL.md
   must forbid artifact writes; agent body must ban Bash and writing in both
   Context A and Context B.
5. Gate-required artifacts: compose_report.py REQUIRED_ARTIFACTS each have a
   producing step in SKILL.md; cleanup rm -f list covers per-run pipeline
   artifacts; vacuity guards on all extraction passes.
6. No shell-variable capture of python output: house regex zero-carve-outs.
7. Flag/choice existence: every --flag in SKILL.md bash invocations of
   market-sizing scripts must exist in that script's argparse add_argument;
   forward-looking scanner covers reference docs.
8. Context B / coaching payload: POST_COMPOSE_COACHING template in SKILL.md
   carries all keys from _emit_coaching_payload + tam/sam/som added by the
   main thread; fence-bounded search region ends at closing code fence so keys
   in Main-Thread Return prose cannot satisfy the check; Context B success
   payload keys match SKILL.md Main-Thread Return; agent body run_id-parity
   list equals the 6 producer artifacts; two-surface schema_version sync
   (script literal vs SKILL.md dispatch template).
9. Web-research contract: main-thread-only research ordering rule
   greppable in both SKILL.md and agent body prose.
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
MS_DIR = REPO_ROOT / "founder-skills" / "skills" / "market-sizing"
SKILL_MD = MS_DIR / "SKILL.md"
AGENT_MD = REPO_ROOT / "founder-skills" / "agents" / "market-sizing.md"
SCRIPTS_DIR = MS_DIR / "scripts"
REFS_DIR = MS_DIR / "references"


# ---------------------------------------------------------------------------
# Module-loading helpers (unique sys.modules keys, sys.path cleanup)
# ---------------------------------------------------------------------------

# Market-sizing scripts have no shared helper modules imported by short name.
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


def _load_checklist_module() -> types.ModuleType:
    return _load_script_module("checklist.py", "ms_checklist_contract")


def _load_sensitivity_module() -> types.ModuleType:
    return _load_script_module("sensitivity.py", "ms_sensitivity_contract")


def _load_compose_report_module() -> types.ModuleType:
    return _load_script_module("compose_report.py", "ms_compose_report_contract")


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
            # `python3 merge_json.py ... | python3 producer.py --stdin` must
            # not attribute the producer's flags to merge_json.py.
            for segment in line.split("|"):
                m = re.search(r"python3[^;]*?/([a-z_]+\.py)", segment)
                if m:
                    script_name = m.group(1)
                    flags = set(re.findall(r"--[a-z][a-z_-]+", segment))
                    result.setdefault(script_name, set()).update(flags)
    return result


def _ref_docs_with_dispatch_templates() -> list[Path]:
    """Return market-sizing reference docs that contain sub-agent dispatch templates."""
    result: list[Path] = []
    for p in sorted(REFS_DIR.glob("*.md")):
        if "CONTEXT:" in p.read_text(encoding="utf-8"):
            result.append(p)
    return result


# ---------------------------------------------------------------------------
# Test 1: Checklist ID enumeration — cited IDs in prose must exist in VALID_IDS
# ---------------------------------------------------------------------------


def _fenced_block_after(text: str, anchor: str) -> str:
    """Return the ``` fenced block that follows `anchor`, whole.

    A fixed character window (the old `text[start : start + 1500]`) silently
    shrinks the assertion's reach as the template grows: adding a paragraph
    above the JSON shape pushed a required key past the cutoff and the test
    failed on a template that was in fact correct. Bound on the fence instead,
    so the check covers exactly the block regardless of length.
    """
    start = text.find(anchor)
    assert start != -1, f"anchor not found: {anchor}"
    fence_open = text.find("```", start)
    assert fence_open != -1, f"no fenced block after anchor: {anchor}"
    fence_close = text.find("```", fence_open + 3)
    assert fence_close != -1, f"unterminated fenced block after anchor: {anchor}"
    return text[start:fence_close]


def test_checklist_id_enumeration_population_is_independent() -> None:
    """Checklist ID candidates extracted from SKILL.md + agent prose must be a
    subset of checklist.py's VALID_IDS. The extraction is independent of VALID_IDS
    — any candidate NOT in VALID_IDS is a phantom and the test reports it explicitly.

    The CHECKLIST dispatch template in SKILL.md names at least one example ID
    (``structural_tam_gt_sam_gt_som``) in the items array. Vacuity guard: at
    least 1 ID must be extracted.
    """
    mod = _load_checklist_module()
    valid_ids: set[str] = set(mod.VALID_IDS)  # type: ignore[attr-defined]

    combined = SKILL_MD.read_text(encoding="utf-8") + "\n" + AGENT_MD.read_text(encoding="utf-8")
    # Extract "id": "some_id" patterns (JSON field form in dispatch templates)
    candidates = set(re.findall(r'"id"\s*:\s*"([a-z][a-z0-9_]+)"', combined))

    assert len(candidates) >= 1, (
        'No checklist IDs found via \'"id": "..."\' pattern in SKILL.md + agent body '
        "— extraction regex may have stopped matching or dispatch templates no longer "
        "show example IDs. Expected at least 'structural_tam_gt_sam_gt_som'."
    )

    phantoms = candidates - valid_ids
    assert not phantoms, (
        f"SKILL.md / agent body cites checklist IDs not in checklist.py VALID_IDS (phantom): {sorted(phantoms)}"
    )


# ---------------------------------------------------------------------------
# Test 1b: pitfalls-checklist.md section IDs must equal VALID_IDS exactly
# ---------------------------------------------------------------------------


def test_pitfalls_checklist_md_header_ids_equal_valid_ids() -> None:
    """The ``### `id` `` headers in pitfalls-checklist.md enumerate all 22 checklist
    IDs. They must match checklist.py's VALID_IDS exactly: no phantom headers
    (a header that no longer exists in the script), no missing headers (a script
    ID with no documentation).

    Count guard: exactly 22 headers must be found. A mutation that renames one
    header produces a phantom; removing one produces a missing entry.
    """
    mod = _load_checklist_module()
    valid_ids: set[str] = set(mod.VALID_IDS)  # type: ignore[attr-defined]

    checklist_text = (REFS_DIR / "pitfalls-checklist.md").read_text(encoding="utf-8")
    # Headers have the form: ### `id_token`
    header_ids = set(re.findall(r"^### `([a-z][a-z0-9_]+)`", checklist_text, re.MULTILINE))

    assert len(header_ids) == 22, (
        f"pitfalls-checklist.md has {len(header_ids)} ### `id` headers (expected 22); "
        f"count guard ensures a missing or extra header is caught"
    )

    phantom = header_ids - valid_ids
    missing = valid_ids - header_ids
    assert not phantom, (
        f"pitfalls-checklist.md has ### `id` headers not in checklist.py VALID_IDS "
        f"(phantom — rename or remove): {sorted(phantom)}"
    )
    assert not missing, (
        f"pitfalls-checklist.md is missing ### `id` headers for VALID_IDS entries "
        f"(missing — add a section for each): {sorted(missing)}"
    )


# ---------------------------------------------------------------------------
# Test 1c: artifact-schemas.md "Canonical 22 checklist IDs" must equal VALID_IDS
# ---------------------------------------------------------------------------


def test_artifact_schemas_md_checklist_ids_equal_valid_ids() -> None:
    """The 'Canonical 22 checklist IDs' section in artifact-schemas.md enumerates
    all 22 IDs as backtick-quoted tokens. These must match checklist.py's VALID_IDS
    exactly — this is the reference document the agent reads during CHECKLIST dispatch.

    Count guard: exactly 22 IDs must be found in the canonical-IDs section.
    Extraction is prefix-filtered (structural_, tam_, som_, data_, both_, approaches_,
    growth_, market_, competitive_, sam_, assumptions_, formulas_, sources_,
    validated_, unsupported_, figures_) to distinguish checklist IDs from other
    backtick tokens in the file.
    """
    mod = _load_checklist_module()
    valid_ids: set[str] = set(mod.VALID_IDS)  # type: ignore[attr-defined]

    # All canonical checklist ID prefixes (derived from checklist.py at test time)
    canonical_prefixes = frozenset(item["id"].split("_")[0] + "_" for item in mod.CHECKLIST_ITEMS)  # type: ignore[attr-defined]

    schemas_text = (REFS_DIR / "artifact-schemas.md").read_text(encoding="utf-8")

    # Locate the "Canonical 22 checklist IDs" section
    anchor = "Canonical 22 checklist IDs"
    start = schemas_text.find(anchor)
    assert start != -1, (
        f"artifact-schemas.md has no '{anchor}' section — agent cannot find checklist IDs during CHECKLIST dispatch"
    )
    # The section ends at the next markdown heading (##) or at end of file
    end_match = re.search(r"\n##", schemas_text[start + 1 :])
    end = start + 1 + end_match.start() if end_match else len(schemas_text)
    section = schemas_text[start:end]

    # Backtick-quoted IDs in this section
    all_backtick_ids = set(re.findall(r"`([a-z][a-z0-9_]+)`", section))
    # Filter to canonical checklist ID prefixes only
    section_ids = {i for i in all_backtick_ids if any(i.startswith(p) for p in canonical_prefixes)}

    assert len(section_ids) == 22, (
        f"artifact-schemas.md 'Canonical 22 checklist IDs' section contains "
        f"{len(section_ids)} IDs (expected 22). "
        f"Prefix filter: {sorted(canonical_prefixes)}"
    )

    phantom = section_ids - valid_ids
    missing = valid_ids - section_ids
    assert not phantom, (
        f"artifact-schemas.md Canonical IDs section has IDs not in checklist.py VALID_IDS (phantom): {sorted(phantom)}"
    )
    assert not missing, (
        f"artifact-schemas.md Canonical IDs section is missing IDs from checklist.py VALID_IDS "
        f"(missing): {sorted(missing)}"
    )


# ---------------------------------------------------------------------------
# Test 1d: Checklist count and category breakdown
# ---------------------------------------------------------------------------


def test_checklist_count_and_categories() -> None:
    """checklist.py CHECKLIST_ITEMS must contain exactly 22 items across 7 categories.
    SKILL.md documents '22-item self-check' and '22 items'; this count guard catches
    silent additions or deletions.
    """
    from collections import Counter

    mod = _load_checklist_module()
    items: list[dict[str, str]] = mod.CHECKLIST_ITEMS  # type: ignore[attr-defined]

    assert len(items) == 22, f"checklist.py CHECKLIST_ITEMS has {len(items)} items (expected 22 per documentation)"

    expected_categories = {
        "Structural Checks",
        "TAM Scoping",
        "SOM Realism",
        "Data Quality",
        "Methodology",
        "Market Understanding",
        "Presentation",
    }
    by_category: Counter[str] = Counter(item["category"] for item in items)
    assert set(by_category.keys()) == expected_categories, (
        f"checklist.py categories mismatch:\n"
        f"  expected: {sorted(expected_categories)}\n"
        f"  got: {sorted(by_category.keys())}"
    )

    # SKILL.md must document the 22-item count in the Scoring section or in the
    # checklist.py description line — scoped so that a stray "22" elsewhere does
    # not satisfy the check but removing the count from all relevant prose fails it.
    skill_text = SKILL_MD.read_text(encoding="utf-8")
    scoring_anchor = "## Scoring"
    scoring_start = skill_text.find(scoring_anchor)
    assert scoring_start != -1, f"{SKILL_MD.name} has no '## Scoring' section"
    scoring_section = skill_text[scoring_start : scoring_start + 300]

    # Also check the Available Scripts description line for checklist.py
    scripts_anchor = "checklist.py"
    scripts_pos = skill_text.find(scripts_anchor)
    assert scripts_pos != -1, f"{SKILL_MD.name} has no checklist.py description line"
    scripts_line = skill_text[scripts_pos : scripts_pos + 100]

    assert "22" in scoring_section or "22" in scripts_line, (
        f"{SKILL_MD.name} does not mention '22' items in the Scoring section or the "
        f"checklist.py description line — both surfaces document the item count"
    )


# ---------------------------------------------------------------------------
# Test 2: TOP_DOWN_METHODOLOGY dispatch return-shape keys
# ---------------------------------------------------------------------------


def test_top_down_dispatch_return_shape_keys() -> None:
    """The TOP_DOWN_METHODOLOGY dispatch template in SKILL.md must include the keys
    market_sizing.py reads from --stdin for approach 'top_down':
    approach, industry_total, segment_pct, share_pct.

    The agent body's TOP_DOWN_METHODOLOGY subtype must also show the same keys.

    Anchor on '**Full dispatch prompt template (TOP_DOWN_METHODOLOGY):**' in SKILL.md
    (not 'CONTEXT: TOP_DOWN_METHODOLOGY' — that string first appears in a compact
    dispatch-list example, before the actual full template section)
    and on '#### TOP_DOWN_METHODOLOGY subtype' in the agent body.
    """
    required_keys = {"approach", "industry_total", "segment_pct", "share_pct"}

    # SKILL.md — anchor on the bold full-template label, not the CONTEXT: line,
    # because the compact dispatch-list example contains the same CONTEXT: text first.
    skill_text = SKILL_MD.read_text(encoding="utf-8")
    anchor = "**Full dispatch prompt template (TOP_DOWN_METHODOLOGY):**"
    assert anchor in skill_text, f"{SKILL_MD.name} has no '{anchor}' label"
    section = _fenced_block_after(skill_text, anchor)
    for key in required_keys:
        assert f'"{key}"' in section, (
            f"{SKILL_MD.name} TOP_DOWN_METHODOLOGY return shape missing key '{key}' (market_sizing.py --stdin reads it)"
        )

    # Agent body subtype section
    agent_text = AGENT_MD.read_text(encoding="utf-8")
    agent_anchor = "#### TOP_DOWN_METHODOLOGY subtype"
    agent_start = agent_text.find(agent_anchor)
    assert agent_start != -1, f"{AGENT_MD.name} has no '#### TOP_DOWN_METHODOLOGY subtype' section"
    next_heading = agent_text.find("\n#### ", agent_start + 1)
    agent_section = (
        agent_text[agent_start:next_heading] if next_heading != -1 else agent_text[agent_start : agent_start + 800]
    )
    for key in required_keys:
        assert f'"{key}"' in agent_section, (
            f"{AGENT_MD.name} TOP_DOWN_METHODOLOGY subtype return shape missing key '{key}'"
        )


# ---------------------------------------------------------------------------
# Test 3: BOTTOM_UP_METHODOLOGY dispatch return-shape keys
# ---------------------------------------------------------------------------


def test_bottom_up_dispatch_return_shape_keys() -> None:
    """The BOTTOM_UP_METHODOLOGY dispatch template in SKILL.md must include the keys
    market_sizing.py reads from --stdin for approach 'bottom_up':
    approach, customer_count, arpu, serviceable_pct, target_pct.

    The agent body's BOTTOM_UP_METHODOLOGY subtype must also show the same keys.

    Anchor on '**Full dispatch prompt template (BOTTOM_UP_METHODOLOGY):**' (same
    reason as TOP_DOWN — 'CONTEXT: BOTTOM_UP_METHODOLOGY' appears in the compact
    dispatch-list example before the actual full template).
    """
    required_keys = {"approach", "customer_count", "arpu", "serviceable_pct", "target_pct"}

    # SKILL.md — anchor on the bold full-template label.
    skill_text = SKILL_MD.read_text(encoding="utf-8")
    anchor = "**Full dispatch prompt template (BOTTOM_UP_METHODOLOGY):**"
    assert anchor in skill_text, f"{SKILL_MD.name} has no '{anchor}' label"
    section = _fenced_block_after(skill_text, anchor)
    for key in required_keys:
        assert f'"{key}"' in section, (
            f"{SKILL_MD.name} BOTTOM_UP_METHODOLOGY return shape missing key '{key}' "
            f"(market_sizing.py --stdin reads it)"
        )

    # Agent body subtype section
    agent_text = AGENT_MD.read_text(encoding="utf-8")
    agent_anchor = "#### BOTTOM_UP_METHODOLOGY subtype"
    agent_start = agent_text.find(agent_anchor)
    assert agent_start != -1, f"{AGENT_MD.name} has no '#### BOTTOM_UP_METHODOLOGY subtype' section"
    next_heading = agent_text.find("\n#### ", agent_start + 1)
    agent_section = (
        agent_text[agent_start:next_heading] if next_heading != -1 else agent_text[agent_start : agent_start + 800]
    )
    for key in required_keys:
        assert f'"{key}"' in agent_section, (
            f"{AGENT_MD.name} BOTTOM_UP_METHODOLOGY subtype return shape missing key '{key}'"
        )


# ---------------------------------------------------------------------------
# Test 4: SENSITIVITY_TEST dispatch return-shape keys
# ---------------------------------------------------------------------------


def test_sensitivity_dispatch_return_shape_keys() -> None:
    """The SENSITIVITY_TEST dispatch template in SKILL.md must include the keys
    sensitivity.py reads from stdin: approach, base, ranges.
    Each ranges entry must carry low_pct, high_pct, confidence.

    The agent body's SENSITIVITY_TEST subtype must show the same shape.

    Confidence values in the template must match sensitivity.py's canonical
    CONFIDENCE_MIN_RANGE keys (sourced, derived, agent_estimate).
    """
    mod = _load_sensitivity_module()
    canonical_confidence: frozenset[str] = frozenset(mod.CONFIDENCE_MIN_RANGE.keys())  # type: ignore[attr-defined]
    assert len(canonical_confidence) == 3, (
        "sensitivity.py CONFIDENCE_MIN_RANGE has unexpected number of keys — check module load"
    )

    required_top_keys = {"approach", "base", "ranges"}
    required_range_keys = {"low_pct", "high_pct", "confidence"}

    skill_text = SKILL_MD.read_text(encoding="utf-8")
    anchor = "CONTEXT: SENSITIVITY_TEST"
    start = skill_text.find(anchor)
    assert start != -1, f"{SKILL_MD.name} has no '{anchor}' section"
    section = skill_text[start : start + 1500]

    for key in required_top_keys:
        assert f'"{key}"' in section, (
            f"{SKILL_MD.name} SENSITIVITY_TEST return shape missing key '{key}' (sensitivity.py reads it from stdin)"
        )
    for key in required_range_keys:
        assert f'"{key}"' in section, f"{SKILL_MD.name} SENSITIVITY_TEST return shape missing range key '{key}'"
    # All 3 confidence values must appear in the template (pipe-separated or explicit)
    for conf in canonical_confidence:
        assert conf in section, (
            f"{SKILL_MD.name} SENSITIVITY_TEST template does not show confidence value '{conf}' — "
            f"agent must know the full set to tag parameters correctly"
        )

    # Agent body SENSITIVITY_TEST subtype
    agent_text = AGENT_MD.read_text(encoding="utf-8")
    agent_anchor = "#### SENSITIVITY_TEST subtype"
    agent_start = agent_text.find(agent_anchor)
    assert agent_start != -1, f"{AGENT_MD.name} has no '#### SENSITIVITY_TEST subtype' section"
    next_heading = agent_text.find("\n#### ", agent_start + 1)
    agent_section = (
        agent_text[agent_start:next_heading] if next_heading != -1 else agent_text[agent_start : agent_start + 1500]
    )
    for key in required_top_keys:
        assert f'"{key}"' in agent_section, f"{AGENT_MD.name} SENSITIVITY_TEST subtype missing key '{key}'"
    for conf in canonical_confidence:
        assert conf in agent_section, (
            f"{AGENT_MD.name} SENSITIVITY_TEST subtype does not mention confidence value '{conf}'"
        )


# ---------------------------------------------------------------------------
# Test 5: CHECKLIST dispatch return-shape keys
# ---------------------------------------------------------------------------


def test_checklist_dispatch_return_shape_keys() -> None:
    """The CHECKLIST dispatch template in SKILL.md must include 'items' (the only
    top-level key checklist.py reads from stdin), and status values
    (pass/fail/not_applicable) from checklist.py's VALID_STATUSES.

    The agent body's CHECKLIST subtype must show the same return shape.
    """
    mod = _load_checklist_module()
    valid_statuses: frozenset[str] = frozenset(mod.VALID_STATUSES)  # type: ignore[attr-defined]

    skill_text = SKILL_MD.read_text(encoding="utf-8")
    anchor = "CONTEXT: CHECKLIST"
    assert anchor in skill_text, f"{SKILL_MD.name} has no '{anchor}' section"
    # Bound on the enclosing fence, not a fixed byte count — the third time a
    # fixed window has failed on correct content after a paragraph was added above
    # the asserted line.
    fence_end = skill_text.index("```", skill_text.index(anchor))
    section = skill_text[skill_text.index(anchor) : fence_end]

    assert '"items"' in section, (
        f"{SKILL_MD.name} CHECKLIST return shape must include 'items' key (checklist.py reads data['items'] from stdin)"
    )
    # Status enum values must appear in the template
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
    assert '"items"' in agent_section, f"{AGENT_MD.name} CHECKLIST subtype missing 'items' key in return shape"
    for status in valid_statuses:
        assert status in agent_section, f"{AGENT_MD.name} CHECKLIST subtype does not mention status value '{status}'"


# ---------------------------------------------------------------------------
# Test 6: Confidence enum values — sourced/derived/agent_estimate in all surfaces
# ---------------------------------------------------------------------------


def test_confidence_enum_values_match_sensitivity_script() -> None:
    """The three confidence values from sensitivity.py's CONFIDENCE_MIN_RANGE
    (sourced, derived, agent_estimate) must all appear in:
    - The SENSITIVITY_TEST dispatch template in SKILL.md (tested in Test 4 above, but
      this test checks the validation.json schema section of SKILL.md as well)
    - The validation.json assumptions schema in SKILL.md (which defines assumption
      categories that feed into sensitivity confidence)
    - The artifact-schemas.md definition of assumption.category

    Vacuity guard: all 3 confidence values must be extracted from script.
    """
    mod = _load_sensitivity_module()
    canonical_confidence: frozenset[str] = frozenset(mod.CONFIDENCE_MIN_RANGE.keys())  # type: ignore[attr-defined]

    assert len(canonical_confidence) == 3, (
        f"sensitivity.py CONFIDENCE_MIN_RANGE has {len(canonical_confidence)} keys (expected 3). "
        f"Keys: {sorted(canonical_confidence)}"
    )

    # SKILL.md must mention all 3 confidence values (in assumptions descriptions)
    skill_text = SKILL_MD.read_text(encoding="utf-8")
    for conf in canonical_confidence:
        assert conf in skill_text, (
            f"{SKILL_MD.name} does not mention confidence value '{conf}' — "
            f"this value appears in sensitivity.py CONFIDENCE_MIN_RANGE"
        )

    # Agent body must mention all 3 confidence values
    agent_text = AGENT_MD.read_text(encoding="utf-8")
    for conf in canonical_confidence:
        assert conf in agent_text, (
            f"{AGENT_MD.name} does not mention confidence value '{conf}' — "
            f"this value appears in sensitivity.py CONFIDENCE_MIN_RANGE"
        )

    # artifact-schemas.md must document the same assumption categories
    schemas_text = (REFS_DIR / "artifact-schemas.md").read_text(encoding="utf-8")
    for conf in canonical_confidence:
        assert conf in schemas_text, (
            f"artifact-schemas.md does not mention confidence/category value '{conf}' — "
            f"agents reading this doc will not know the valid values"
        )


# ---------------------------------------------------------------------------
# Test 7: No-file-writes instruction in Context A dispatch templates
# ---------------------------------------------------------------------------


def test_context_a_dispatch_templates_contain_no_write_instruction() -> None:
    """All four Context A dispatch templates in SKILL.md must explicitly forbid
    artifact writes — a sub-agent that writes files directly bypasses schema
    validation and run_id stamping.

    Contexts checked: TOP_DOWN_METHODOLOGY, BOTTOM_UP_METHODOLOGY,
    SENSITIVITY_TEST, CHECKLIST.

    Each is bounded by its closing ``` fence to prevent the next template's
    no-write instruction from satisfying the check.

    For TOP_DOWN and BOTTOM_UP, anchor on the bold full-template label (not
    'CONTEXT: ...' which first appears in the compact dispatch-list example that
    has no no-write instruction).
    """
    skill_text = SKILL_MD.read_text(encoding="utf-8")

    # Anchors that uniquely identify the full template block (not the compact list example).
    # TOP_DOWN and BOTTOM_UP use bold full-template labels; SENSITIVITY_TEST and CHECKLIST
    # use section heading labels that appear only once in SKILL.md.
    contexts = [
        ("TOP_DOWN_METHODOLOGY", "**Full dispatch prompt template (TOP_DOWN_METHODOLOGY):**"),
        ("BOTTOM_UP_METHODOLOGY", "**Full dispatch prompt template (BOTTOM_UP_METHODOLOGY):**"),
        ("SENSITIVITY_TEST", "#### SENSITIVITY_TEST dispatch prompt template"),
        ("CHECKLIST", "#### CHECKLIST dispatch prompt template"),
    ]

    for context_name, anchor in contexts:
        start = skill_text.find(anchor)
        assert start != -1, f"{SKILL_MD.name} has no '{anchor}' section"

        # Bound the search at the closing ``` fence of this template block.
        # Find the first opening ``` fence after the anchor, then the matching close.
        open_fence = skill_text.find("\n```\n", start)
        assert open_fence != -1, f"{SKILL_MD.name} {context_name}: no opening ``` fence after anchor"
        close_fence = skill_text.find("\n```\n", open_fence + 4)
        assert close_fence != -1, f"{SKILL_MD.name} {context_name}: no closing ``` fence"
        section = skill_text[start:close_fence]

        assert "Do NOT write" in section or "do not write" in section.lower(), (
            f"{SKILL_MD.name} {context_name} dispatch template must explicitly forbid "
            f"artifact writes (search region ends at closing ``` fence, char {close_fence})"
        )


def test_agent_body_context_a_hard_rules_contain_bash_ban_and_no_write() -> None:
    """The agent body's Context A hard-rules block must:
    - Forbid writing artifacts to disk ('Do not write' or equivalent)
    - Forbid Bash calls ('Do not call' + 'Bash')

    Anchor: '**Hard rules in Context A:**' inside the Context A section.
    """
    agent_text = AGENT_MD.read_text(encoding="utf-8")
    anchor = "### Context A"
    start = agent_text.find(anchor)
    assert start != -1, f"{AGENT_MD.name} has no '### Context A' section"
    next_section = agent_text.find("\n### Context B", start)
    section = agent_text[start:next_section] if next_section != -1 else agent_text[start : start + 6000]

    assert "do not write" in section.lower() or "Do not write" in section, (
        f"{AGENT_MD.name} Context A section must forbid writing artifacts to disk"
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
    instruction. Market-sizing reference docs currently contain no CONTEXT: blocks;
    this test will fail loudly if a reference doc gains a dispatch template without
    the no-write instruction.
    """
    ref_docs = _ref_docs_with_dispatch_templates()
    # Currently expected to be empty for market-sizing
    for ref_doc in ref_docs:
        text = ref_doc.read_text(encoding="utf-8")
        for block_start_idx in [m.start() for m in re.finditer(r"CONTEXT:", text)]:
            section = text[block_start_idx : block_start_idx + 2000]
            assert "Do NOT write" in section or "do not write" in section.lower(), (
                f"{ref_doc.name}: dispatch template at char {block_start_idx} "
                f"is missing 'Do not write artifacts' instruction"
            )


# ---------------------------------------------------------------------------
# Test 8: Gate-required artifacts and cleanup coverage
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
    """compose_report.py REQUIRED_ARTIFACTS must contain exactly 6 entries —
    the 6 per-step producer artifacts for market-sizing. A silent deletion
    would let compose succeed with missing data.
    """
    mod = _load_compose_report_module()
    required: list[str] = mod.REQUIRED_ARTIFACTS  # type: ignore[attr-defined]
    expected = {
        "inputs.json",
        "methodology.json",
        "validation.json",
        "sizing.json",
        "checklist.json",
        "sensitivity.json",
    }
    assert set(required) == expected, (
        f"compose_report.py REQUIRED_ARTIFACTS mismatch:\n  expected: {sorted(expected)}\n  got: {sorted(required)}"
    )


def test_overwrite_in_place_no_outputs_delete() -> None:
    """Cowork-parity: market-sizing must NOT bash-`rm` prior artifacts under
    `$ANALYSIS_DIR` (the promoted outputs/ tree) and must NOT stage scratch
    there. It overwrites-in-place (producers rewrite via `-o`; compose's
    STALE_ARTIFACT run_id check backstops a skipped-step leftover) and stages in
    a `/tmp` `$STAGING_DIR`. Replaces the old `rm -f` cleanup-coverage test —
    deleting under outputs/ is the regression now, not an uncovered artifact.
    """
    skill_text = SKILL_MD.read_text(encoding="utf-8")
    # No bash rm targeting the outputs work dir.
    assert not re.search(r"\brm\b[^\n`]*\$\{?ANALYSIS_DIR\b", skill_text), (
        f"{SKILL_MD.name}: bash `rm` of $ANALYSIS_DIR (promoted outputs/) — overwrite-in-place instead"
    )
    # No `.staging` UNDER the outputs dir (the /tmp $STAGING_DIR template, '.staging.XXXXXX', is fine).
    assert not re.search(r"\$\{?ANALYSIS_DIR\}?/\.staging", skill_text), (
        f"{SKILL_MD.name}: stages scratch under $ANALYSIS_DIR — use a /tmp $STAGING_DIR"
    )
    # Positive: a /tmp $STAGING_DIR is mktemp'd at setup.
    assert re.search(r'STAGING_DIR="\$\(mktemp -d', skill_text), (
        f"{SKILL_MD.name}: expected a `$STAGING_DIR` mktemp'd under /tmp for sub-agent scratch"
    )


# ---------------------------------------------------------------------------
# Test 9: No shell-variable capture of python output
# ---------------------------------------------------------------------------


def test_no_shell_variable_capture_of_python_output() -> None:
    """Each Bash call runs in a fresh shell; capturing python output into a shell
    variable makes it invisible to any subsequent Bash call. No carve-outs.

    The house pattern fires on any assignment of the form VAR="$(python3 ..." or
    VAR="$(python ...". Infrastructure captures like SCRIPTS="$(find ...)" and
    RUN_ID="$(date ...)" do NOT match (not python3/python invocations).

    The <!-- skill-quality-ci: bash-after-subagent-ok --> marker (if present) is
    a CI marker, not a capture pattern, and is not matched by this regex.
    """
    skill_text = SKILL_MD.read_text(encoding="utf-8")
    assert not re.search(r'\w+="\$\(\s*python3?', skill_text), (
        "SKILL.md captures python output into a shell variable — print it instead. "
        "Zero carve-outs: the house-pattern regression guard fires on any match."
    )


# ---------------------------------------------------------------------------
# Test 10: Flag/choice existence
# ---------------------------------------------------------------------------


def test_bash_flags_exist_in_scripts() -> None:
    """Every --flag used in a bash invocation of a market-sizing script in SKILL.md
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
            continue  # script outside this skill's scope; skip

        defined_flags = _collect_argparse_flags(script_path)
        phantom_flags = flags_used - defined_flags
        assert not phantom_flags, (
            f"{script_name}: SKILL.md uses flags not defined in argparse:\n"
            f"  phantom: {sorted(phantom_flags)}\n"
            f"  defined: {sorted(defined_flags)}"
        )


def test_bash_flags_in_ref_docs_exist_in_scripts() -> None:
    """Forward-looking: every --flag used in a bash invocation of a market-sizing
    script inside any reference doc (*.md) must exist in that script's argparse.

    Market-sizing reference docs currently contain no ```bash blocks with script
    invocations, so this test is vacuous today. If a future reference doc gains
    a bash block that invokes a script with a phantom flag, this test will catch
    it automatically.
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


def test_producer_scripts_define_run_id_flag() -> None:
    """The three producer scripts that inject run_id into output artifacts must
    define --run-id as an argparse argument.

    market_sizing.py, sensitivity.py, and checklist.py all stamp
    result["metadata"] = {"run_id": args.run_id} — if --run-id were missing from
    argparse, every producer invocation would fail.
    """
    for script_name in ("market_sizing.py", "sensitivity.py", "checklist.py"):
        script_path = SCRIPTS_DIR / script_name
        defined_flags = _collect_argparse_flags(script_path)
        assert "--run-id" in defined_flags, (
            f"{script_name} is missing --run-id argparse definition — run_id injection contract is broken"
        )


# ---------------------------------------------------------------------------
# Test 10b: Methodology enum — VALID_APPROACHES from sensitivity.py pinned
# ---------------------------------------------------------------------------


def test_methodology_enum_values_pinned() -> None:
    """sensitivity.py's VALID_APPROACHES is the canonical set for the approach
    enum used throughout the pipeline.  Every prose surface that enumerates
    methodology values must:
    - cite only values that exist in VALID_APPROACHES (no phantoms), and
    - include all three canonical values on at least one enumeration surface.

    Mutation guard: adding a phantom value to a prose surface fails the phantom
    check; removing a canonical value from all surfaces fails the presence check.
    """
    mod = _load_sensitivity_module()
    canonical: frozenset[str] = frozenset(mod.VALID_APPROACHES)  # type: ignore[attr-defined]
    assert len(canonical) == 3, (
        f"sensitivity.py VALID_APPROACHES has {len(canonical)} values (expected 3); "
        f"update this test if the canonical set genuinely changed"
    )

    # Prose surfaces that enumerate approach values: SKILL.md pipe-separated enum
    # lines and agent body pipe-separated enum lines.
    skill_text = SKILL_MD.read_text(encoding="utf-8")
    agent_text = AGENT_MD.read_text(encoding="utf-8")

    # Collect every pipe-separated token sequence that contains at least one
    # known approach value — these are the enumeration sites in templates and prose.
    # Pattern: word1|word2|word3 (as used in e.g. "bottom_up|top_down|both")
    pipe_tokens: set[str] = set()
    for m in re.finditer(r"[a-z_]+(?:\|[a-z_]+)+", skill_text + "\n" + agent_text):
        for tok in m.group(0).split("|"):
            if tok in canonical:
                pipe_tokens.update(m.group(0).split("|"))

    # Any token that appears in an enumeration site and is NOT in canonical is a phantom.
    enum_phantoms = pipe_tokens - canonical
    assert not enum_phantoms, (
        f"SKILL.md/agent body pipe-separated methodology enum contains values not "
        f"in sensitivity.py VALID_APPROACHES (phantom): {sorted(enum_phantoms)}"
    )

    # All canonical values must appear on at least one prose surface.
    combined = skill_text + "\n" + agent_text
    for val in canonical:
        assert val in combined, (
            f"sensitivity.py VALID_APPROACHES value '{val}' does not appear in "
            f"SKILL.md or agent body — add it to the relevant dispatch template or "
            f"methodology prose"
        )


# ---------------------------------------------------------------------------
# Test 10c: Confidence thresholds — score_pct >= N from compose_report.py pinned
# ---------------------------------------------------------------------------


def test_confidence_level_thresholds_match_script() -> None:
    """compose_report.py computes confidence from score_pct >= N comparisons.
    SKILL.md's Step 8 area must state both thresholds.

    Thresholds are extracted from compose_report.py source via regex at test
    time — never hardcoded — so a script-side change with stale prose fails.

    Mutation guard: changing a threshold value in the script makes the
    extracted number disagree with the prose value → fail.
    """
    src = (SCRIPTS_DIR / "compose_report.py").read_text(encoding="utf-8")
    thresholds = re.findall(r"score_pct >= (\d+)", src)
    assert len(thresholds) == 2, (
        f"compose_report.py: expected exactly two 'score_pct >= N' comparisons, "
        f"found {thresholds} — update extractor regex if the expression form changed"
    )

    # SKILL.md's Step 8 section (which describes the confidence derivation) must
    # state both threshold values.
    skill_text = SKILL_MD.read_text(encoding="utf-8")
    step8_anchor = "### Step 8"
    step8_start = skill_text.find(step8_anchor)
    assert step8_start != -1, f"{SKILL_MD.name} has no '{step8_anchor}' section"
    # Include the full Step 8 prose up to the next ### section or end of file
    next_h3 = skill_text.find("\n### ", step8_start + 1)
    step8_section = skill_text[step8_start:next_h3] if next_h3 != -1 else skill_text[step8_start:]

    for thr in thresholds:
        assert thr in step8_section, (
            f"{SKILL_MD.name} Step 8 section does not mention threshold '{thr}' "
            f"(compose_report.py uses 'score_pct >= {thr}' to derive confidence)"
        )


# ---------------------------------------------------------------------------
# Test 11: Context B / coaching payload — POST_COMPOSE_COACHING template
# ---------------------------------------------------------------------------


def test_post_compose_coaching_dispatch_includes_coaching_payload_keys() -> None:
    """The POST_COMPOSE_COACHING dispatch template in SKILL.md must list all
    coaching_payload keys the Context B agent consumes, in their quoted JSON form.

    All required keys below are emitted directly by compose_report.py's
    _emit_coaching_payload (the compose-side output): summary, failed_items,
    warned_items, high_severity_warnings, company_name, methodology, confidence,
    deck_coverage, tam, sam, som, review_dir, report_path, insertion_marker.
    (schema_version is pinned separately by
    test_coaching_payload_schema_version_is_market_sizing.)

    tam/sam/som used to be documented as keys the SKILL.md *main thread* added
    from sizing.json after compose — but compose_report.py never put a scalar
    tam/sam/som anywhere in sizing.json's reach for a main thread to copy (the
    real values are nested at top_down.tam.value / bottom_up.tam.value etc.), so
    that step never actually ran. _emit_coaching_payload now resolves the nested
    path itself (see _resolve_headline_market_size in compose_report.py) and
    emits tam/sam/som directly, so they belong with the rest of the compose-side
    keys, not in a separate "added by the main thread" bucket.

    Search region: from the opening ``` fence of the dispatch template to the
    template's own "Return:" line.  This excludes the Return block (which repeats
    some keys) and the post-fence Main-Thread prose, so every required key must
    appear in the coaching_payload object body only — a deletion from the payload
    body is caught even when that key still lives in the Return block.

    Keys are checked in quoted form (f'"{key}"') to avoid substring collisions
    (e.g. "tam" matching "stamping").
    """
    # Keys emitted by _emit_coaching_payload (compose-side). schema_version is
    # deliberately absent: the agent body's Context B key list documents only
    # the content keys the coach consumes, and the version literal itself is
    # pinned two-surface by test_coaching_payload_schema_version_is_market_sizing.
    required_keys = {
        "summary",
        "failed_items",
        "warned_items",
        "high_severity_warnings",
        "company_name",
        "methodology",
        "confidence",
        "deck_coverage",
        # A refused cross-check is invisible in every other key: the figure is present and
        # `deck_coverage` still reports it as stated, so a coach not handed this writes as
        # though it had been verified. COMPARISON_CURRENCY_UNKNOWN is medium, so it never
        # arrives via high_severity_warnings.
        "comparison_blocked",
        "tam",
        "sam",
        "som",
        "review_dir",
        "report_path",
        "insertion_marker",
    }

    skill_text = SKILL_MD.read_text(encoding="utf-8")

    # The POST_COMPOSE_COACHING dispatch template block in SKILL.md:
    #   **Dispatch prompt template:**
    #   ```
    #   CONTEXT: POST_COMPOSE_COACHING
    #   ...coaching_payload: { ... }
    #   Return:           ← upper bound; excludes the Return JSON block
    #   { ... }
    #   ```
    step8_anchor = "### Step 8"
    start = skill_text.find(step8_anchor)
    assert start != -1, f"{SKILL_MD.name} has no '{step8_anchor}' section"

    assert "CONTEXT: POST_COMPOSE_COACHING" in skill_text[start:], (
        f"{SKILL_MD.name} Step 8 section has no 'CONTEXT: POST_COMPOSE_COACHING' block"
    )

    disp_label = "**Dispatch prompt template:**"
    label_pos = skill_text.find(disp_label, start)
    assert label_pos != -1, (
        f"{SKILL_MD.name} POST_COMPOSE_COACHING section has no '**Dispatch prompt template:**' label"
    )
    open_fence = skill_text.find("\n```\n", label_pos)
    assert open_fence != -1, f"{SKILL_MD.name} no opening ``` fence after '**Dispatch prompt template:**'"
    close_fence = skill_text.find("\n```\n", open_fence + 4)
    assert close_fence != -1, f"{SKILL_MD.name} no closing ``` fence for POST_COMPOSE_COACHING template"

    # The template has a "Return:" paragraph after the coaching_payload object.
    # Bound search to just the payload body by stopping at the first "\nReturn:" line
    # inside the fence (so the Return: block cannot satisfy the key checks).
    fence_body = skill_text[open_fence + 4 : close_fence]
    return_line_pos = fence_body.find("\nReturn:")
    assert return_line_pos != -1, (
        f"{SKILL_MD.name} POST_COMPOSE_COACHING template has no 'Return:' line — "
        f"expected inside the dispatch template fence"
    )
    # Search region: fence body up to (not including) the Return: line
    section = fence_body[:return_line_pos]

    for key in required_keys:
        assert f'"{key}"' in section, (
            f"{SKILL_MD.name} POST_COMPOSE_COACHING dispatch template is missing "
            f"quoted coaching_payload key '\"{key}\"' — search region is the "
            f"coaching_payload body before the 'Return:' line (so the Return block "
            f"cannot satisfy this check)"
        )

    # Agent body Context B section must also reference all these keys
    agent_text = AGENT_MD.read_text(encoding="utf-8")
    agent_anchor = "### Context B"
    agent_start = agent_text.find(agent_anchor)
    assert agent_start != -1, f"{AGENT_MD.name} has no '### Context B' section"
    agent_section = agent_text[agent_start : agent_start + 8000]

    for key in required_keys:
        assert key in agent_section, f"{AGENT_MD.name} Context B section is missing coaching_payload key '{key}'"


def test_coaching_payload_schema_version_is_market_sizing() -> None:
    """Two-surface sync: compose_report.py's schema_version literal must
    (a) end with '-market-sizing' (skill-specific suffix), AND
    (b) equal the version stated in SKILL.md's POST_COMPOSE_COACHING dispatch template.

    Extraction strategy — independent on both surfaces:
    - Script literal: first '"schema_version": "..."' match in compose_report.py source.
    - SKILL.md template: first '"schema_version": "..."' match in the
      POST_COMPOSE_COACHING section (bounded within the template block fence).

    Mutation-test guarantees:
    - Change the script literal suffix (e.g. '-market-sizing' → '-ic-sim') → fails suffix check.
    - Change the SKILL.md template version (e.g. v0.4.2 → v0.4.3) → fails two-surface sync.
    """
    src = (SCRIPTS_DIR / "compose_report.py").read_text(encoding="utf-8")

    m_script = re.search(r'"schema_version"\s*:\s*"([^"]+)"', src)
    assert m_script, (
        'compose_report.py has no \'"schema_version": "..."\' literal — _emit_coaching_payload may have been refactored'
    )
    script_literal = m_script.group(1)

    # (a) suffix check
    assert script_literal.endswith("-market-sizing"), (
        f"compose_report.py coaching_payload schema_version '{script_literal}' "
        f"does not end with '-market-sizing' — wrong skill suffix or missing suffix"
    )

    # (b) two-surface sync: SKILL.md dispatch template must state the same version.
    # Anchor on "### Step 8" (the enclosing section) because '**Dispatch prompt template:**'
    # appears 35 chars BEFORE 'CONTEXT: POST_COMPOSE_COACHING' (which is inside the block).
    skill_text = SKILL_MD.read_text(encoding="utf-8")
    step8_anchor = "### Step 8"
    start = skill_text.find(step8_anchor)
    assert start != -1, f"{SKILL_MD.name} has no '{step8_anchor}' section"

    # Bound to template block fence
    disp_label = "**Dispatch prompt template:**"
    label_pos = skill_text.find(disp_label, start)
    assert label_pos != -1, f"{SKILL_MD.name}: no '**Dispatch prompt template:**' label in POST_COMPOSE_COACHING"
    open_fence = skill_text.find("\n```\n", label_pos)
    assert open_fence != -1, f"{SKILL_MD.name}: no opening fence after '**Dispatch prompt template:**'"
    close_fence = skill_text.find("\n```\n", open_fence + 4)
    assert close_fence != -1, f"{SKILL_MD.name}: no closing fence for POST_COMPOSE_COACHING template"
    template_region = skill_text[start:close_fence]

    m_skill = re.search(r'"schema_version"\s*:\s*"([^"]+)"', template_region)
    assert m_skill, (
        f"{SKILL_MD.name} POST_COMPOSE_COACHING dispatch template has no "
        f'"schema_version" key — it must match compose_report.py\'s literal'
    )
    skill_version = m_skill.group(1)

    assert skill_version == script_literal, (
        f"schema_version drift: compose_report.py emits '{script_literal}' "
        f"but {SKILL_MD.name} POST_COMPOSE_COACHING template states '{skill_version}' "
        f"— both surfaces must agree"
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
    # (sourced from coaching_payload / the insert_coaching.py receipt)
    skill_text = SKILL_MD.read_text(encoding="utf-8")
    main_thread_anchor = "## Main-Thread Return"
    mt_start = skill_text.find(main_thread_anchor)
    assert mt_start != -1, f"{SKILL_MD.name} has no '## Main-Thread Return' section"
    mt_section = skill_text[mt_start : mt_start + 1000]
    for key in {"tam", "sam", "som", "methodology", "confidence", "high_severity_warnings"}:
        assert key in mt_section, f"{SKILL_MD.name} Main-Thread Return section does not mention '{key}'"


def test_run_id_parity_artifact_list_matches_required_artifacts() -> None:
    """run_id parity is verified script-side by insert_coaching.py. Two
    surfaces must list exactly compose_report.py's REQUIRED_ARTIFACTS:

    1. SKILL.md Step 8's insert_coaching.py invocation — the
       `--verify-artifact` flags (the operative gate).
    2. The agent body's Context B prose list (informational; keeps the
       agent's mental model in sync).

    report.json is excluded on both surfaces (compose-side aggregator, no
    run_id by design).
    """
    mod = _load_compose_report_module()
    required: frozenset[str] = frozenset(mod.REQUIRED_ARTIFACTS)  # type: ignore[attr-defined]

    # Surface 1: SKILL.md --verify-artifact flags
    skill_text = SKILL_MD.read_text(encoding="utf-8")
    verify_artifacts = frozenset(re.findall(r'--verify-artifact\s+"\$[A-Z_]+/([a-z_]+\.json)"', skill_text))
    assert verify_artifacts, f"{SKILL_MD.name} has no --verify-artifact flags (insert_coaching.py invocation missing?)"
    assert verify_artifacts == required, (
        f"{SKILL_MD.name} insert_coaching.py --verify-artifact list != "
        f"compose_report.REQUIRED_ARTIFACTS:\n"
        f"  phantom: {sorted(verify_artifacts - required)}\n"
        f"  missing: {sorted(required - verify_artifacts)}"
    )

    # Surface 2: agent body prose list
    agent_text = AGENT_MD.read_text(encoding="utf-8")
    anchor = "run_id-parity verification (across"
    start = agent_text.find(anchor)
    assert start != -1, f"{AGENT_MD.name} Context B has no 'run_id-parity verification (across ...)' prose list"
    close = agent_text.find(")", start)
    assert close != -1, f"{AGENT_MD.name} run_id-parity prose list has no closing paren"
    prose_artifacts = frozenset(re.findall(r"\b([a-z_]+\.json)\b", agent_text[start:close]))
    assert prose_artifacts == required, (
        f"{AGENT_MD.name} run_id-parity prose list != compose_report.REQUIRED_ARTIFACTS:\n"
        f"  phantom: {sorted(prose_artifacts - required)}\n"
        f"  missing: {sorted(required - prose_artifacts)}"
    )


# ---------------------------------------------------------------------------
# Test 12: Web-research contract — main-thread-only research ordering
# ---------------------------------------------------------------------------


def test_webfetch_before_dispatch_ordering_in_skill_md() -> None:
    """SKILL.md must state that the main thread performs web research BEFORE
    dispatching sub-agents, and that this skill's sub-agent allowlist includes
    no network tools (a design choice — NOT a platform limitation; WebSearch
    resolves for any sub-agent that declares it, Cowork included).

    Tightened: the ordering sentence in the Skill Execution Model section must
    contain the word "BEFORE" (case-sensitive) immediately in the sentence that
    describes the research-before-dispatch pattern — replacing "BEFORE" with
    "AFTER" must make this test fail.  The Step 4 ban on sub-agent dispatch must
    also be present.
    """
    skill_text = SKILL_MD.read_text(encoding="utf-8")

    # Locate the "Research-before-dispatch pattern" sentence in the Skill
    # Execution Model section and verify it contains "BEFORE dispatching" —
    # inversion to "AFTER dispatching" must fail this check.
    pattern_anchor = "Research-before-dispatch pattern"
    assert pattern_anchor in skill_text, (
        f"{SKILL_MD.name} must contain a '**Research-before-dispatch pattern:**' "
        f"heading in the Skill Execution Model section"
    )
    # Extract the sentence(s) starting at the anchor (up to 300 chars) and verify
    # the ordering word is BEFORE, not some other ordering term.
    anchor_pos = skill_text.find(pattern_anchor)
    ordering_sentence = skill_text[anchor_pos : anchor_pos + 300]
    assert "BEFORE dispatching" in ordering_sentence, (
        f"{SKILL_MD.name} research-before-dispatch sentence must say 'BEFORE dispatching' "
        f"(not 'AFTER dispatching' or any other inversion) — found: {ordering_sentence[:120]!r}"
    )

    # Step 4 must forbid dispatching a sub-agent for research.
    step4_anchor = "Step 4: External Validation"
    step4_start = skill_text.find(step4_anchor)
    assert step4_start != -1, f"{SKILL_MD.name} has no '{step4_anchor}' section"
    step4_section = skill_text[step4_start : step4_start + 500]
    assert "Do NOT dispatch a sub-agent" in step4_section, (
        f"{SKILL_MD.name} '{step4_anchor}' must explicitly say 'Do NOT dispatch a sub-agent' — "
        f"research must stay in the main thread"
    )


def test_webfetch_before_dispatch_ordering_in_agent_body() -> None:
    """The agent body must state that it does NOT have network access for Context A
    dispatches — the main thread provides research data inline in the dispatch prompt.

    This is the agent-side complement to the web-research contract: the agent must
    know it cannot and should not attempt WebFetch/WebSearch.
    """
    agent_text = AGENT_MD.read_text(encoding="utf-8")

    # The agent body must describe the main thread performing research before
    # dispatch — a bare "research" mention is too weak to count.
    assert "WebFetch" in agent_text or "web research" in agent_text.lower(), (
        f"{AGENT_MD.name} must mention the research-before-dispatch pattern (WebFetch/WebSearch)"
    )

    # The agent body must state it does not need network access for Context A
    assert "network access" in agent_text.lower() or "WebFetch" in agent_text, (
        f"{AGENT_MD.name} must state that Context A dispatches do not require network access"
    )


# ---------------------------------------------------------------------------
# Test 12b: CHECKLIST dispatch template enumerates ALL canonical IDs
#
# Note: FMR (financial-model-review) and competitive-positioning enumerate via
# systematic PREFIX_NN ranges and are covered by their own range-expansion
# checks — the asymmetry here (explicit list vs. range) is intentional.
# ---------------------------------------------------------------------------


def test_checklist_dispatch_template_enumerates_all_canonical_ids() -> None:
    """The CHECKLIST dispatch template in SKILL.md must enumerate every canonical
    checklist ID as a JSON ``"id"`` field value — no omissions, no phantoms.

    Set-equality test (both directions):
    - Template IDs ⊆ canonical: no invented IDs accepted by the template.
    - Canonical IDs ⊆ template IDs: no ID silently absent from the template.

    Search region: bounded within the CHECKLIST dispatch template fence so only
    the enumerated list (not surrounding prose) satisfies the check.

    Count guard: exactly 22 ``"id"`` values must appear in the template.

    Mutation-check: rename any id in the template → phantom check fails;
    restore → passes.
    """
    mod = _load_checklist_module()
    canonical_ids: set[str] = set(mod.VALID_IDS)  # type: ignore[attr-defined]
    assert len(canonical_ids) == 22, (
        f"checklist.py VALID_IDS has {len(canonical_ids)} items (expected 22) — "
        f"update this test if the canonical set genuinely changed"
    )

    skill_text = SKILL_MD.read_text(encoding="utf-8")

    # Bound search to the CHECKLIST dispatch template fence
    anchor = "#### CHECKLIST dispatch prompt template"
    start = skill_text.find(anchor)
    assert start != -1, f"{SKILL_MD.name} has no '{anchor}' section"
    open_fence = skill_text.find("\n```\n", start)
    assert open_fence != -1, f"{SKILL_MD.name} CHECKLIST: no opening fence after section anchor"
    close_fence = skill_text.find("\n```\n", open_fence + 4)
    assert close_fence != -1, f"{SKILL_MD.name} CHECKLIST: no closing fence"
    template_body = skill_text[open_fence:close_fence]

    # Extract all "id": "some_id" values from the template body
    template_ids = set(re.findall(r'"id"\s*:\s*"([a-z][a-z0-9_]+)"', template_body))

    assert len(template_ids) == 22, (
        f"{SKILL_MD.name} CHECKLIST dispatch template enumerates {len(template_ids)} ids "
        f"(expected 22); count guard catches omissions or duplicates.\n"
        f"  found: {sorted(template_ids)}"
    )

    phantom = template_ids - canonical_ids
    missing = canonical_ids - template_ids

    assert not phantom, (
        f"{SKILL_MD.name} CHECKLIST dispatch template contains ids not in "
        f"checklist.py VALID_IDS (phantom — invented or renamed): {sorted(phantom)}"
    )
    assert not missing, (
        f"{SKILL_MD.name} CHECKLIST dispatch template is missing ids from "
        f"checklist.py VALID_IDS (missing — sub-agent will invent them): {sorted(missing)}"
    )


# ---------------------------------------------------------------------------
# Test 13: Checklist VALID_STATUSES — no 'warn' status in market-sizing
# ---------------------------------------------------------------------------


def test_checklist_valid_statuses_has_no_warn() -> None:
    """Market-sizing's checklist has no 'warn' status — only pass/fail/not_applicable.
    This is explicitly called out in compose_report.py, SKILL.md, and the agent body.

    The test verifies:
    - checklist.py VALID_STATUSES does NOT include 'warn'
    - SKILL.md and the agent body explicitly state warned_items is always []
    """
    mod = _load_checklist_module()
    valid_statuses: frozenset[str] = frozenset(mod.VALID_STATUSES)  # type: ignore[attr-defined]

    assert "warn" not in valid_statuses, (
        "checklist.py VALID_STATUSES includes 'warn' — market-sizing uses only "
        "pass/fail/not_applicable; if 'warn' was added, update prose documentation"
    )
    assert valid_statuses == {"pass", "fail", "not_applicable"}, (
        f"checklist.py VALID_STATUSES is not the expected 3-status set: {sorted(valid_statuses)}"
    )

    # SKILL.md must contain a line that has both "warned_items" and "[]" — scoped to
    # a single line so that a stray "[]" on a different line cannot satisfy the check,
    # and removing "[]" from all warned_items lines fails it.
    skill_text = SKILL_MD.read_text(encoding="utf-8")
    wi_lines_with_bracket = [line for line in skill_text.splitlines() if "warned_items" in line and "[]" in line]
    assert wi_lines_with_bracket, (
        f"{SKILL_MD.name} has no line that mentions both 'warned_items' and '[]' — "
        f"the always-empty claim must appear on the same line as the key name"
    )

    # Agent body: the sentence that says warned_items is always [] must say both
    # "warned_items" and "always" within 200 chars (sentence proximity).
    agent_text = AGENT_MD.read_text(encoding="utf-8")
    agent_wi_pos = agent_text.find("warned_items")
    assert agent_wi_pos != -1, f"{AGENT_MD.name} does not mention 'warned_items'"
    # Search a window of 200 chars around the first warned_items occurrence for "always"
    agent_wi_window = agent_text[max(0, agent_wi_pos - 20) : agent_wi_pos + 200]
    assert "always" in agent_wi_window, (
        f"{AGENT_MD.name} the 'warned_items' sentence must say 'always' (indicating "
        f"it is always [] for market-sizing) — found window: {agent_wi_window!r}"
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


def test_agent_orchestration_boundary_matches_context_b_procedure() -> None:
    """The Orchestration boundary summary must match the Context B procedure: the
    coaching_payload is STAGED AS A FILE and Read by the sub-agent (never inlined
    into the dispatch prompt); the sub-agent writes PLAIN-MARKDOWN commentary to
    OUTPUT_PATH and returns only a small JSON receipt (JSON is the receipt, never
    the commentary); and the sub-agent never edits report.md directly (the main
    thread wraps the markdown via md_to_commentary.py and inserts it via
    insert_coaching.py). A summary that says the commentary is returned 'as JSON',
    that the payload is 'inlined', or that Context B 'edits report.md' contradicts
    the procedure defined elsewhere in this file (the grammatically-broken
    "rather than the dispatch prompt instead of reading the full report.md. You
    return the commentary as JSON" defect).
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


def test_agent_final_message_contract_context_a_is_receipt_only() -> None:
    """The '## Final-message contract' section must state that Context A's final
    assistant message is the receipt ONLY, with the message-channel fallback (no
    OUTPUT_PATH: line in the dispatch prompt) named as the one explicit exception.
    A section that unconditionally says 'the JSON shape matches the relevant
    producer script's input' contradicts the Context A hard rules earlier in this
    file, which mandate the file Write to OUTPUT_PATH always happens and gate the
    final message on the receipt shape — the real consequence of the contradiction
    is check_handoff.py exit 6 (unparseable receipt), costing a retry.
    """
    agent_text = AGENT_MD.read_text(encoding="utf-8")
    anchor = "## Final-message contract"
    start = agent_text.find(anchor)
    assert start != -1, f"{AGENT_MD.name} has no '{anchor}' section"
    end = agent_text.find("\n## ", start + len(anchor))
    section = agent_text[start:end] if end != -1 else agent_text[start:]
    normalized = " ".join(section.split()).lower()

    context_a_idx = normalized.find("in context a:")
    assert context_a_idx != -1, f"{AGENT_MD.name} Final-message contract has no 'In Context A:' clause"
    context_b_idx = normalized.find("in context b:")
    assert context_b_idx != -1, f"{AGENT_MD.name} Final-message contract has no 'In Context B:' clause"
    context_a_clause = normalized[context_a_idx:context_b_idx]

    assert "status" in context_a_clause and "complete" in context_a_clause and "output_path" in context_a_clause, (
        f"{AGENT_MD.name} Final-message contract's Context A clause must state the final message is "
        "the {'status': 'complete', 'output_path': ...} receipt"
    )
    assert "message-channel fallback" in context_a_clause or "no output_path:" in context_a_clause, (
        f"{AGENT_MD.name} Final-message contract's Context A clause must name the message-channel "
        "fallback (no OUTPUT_PATH: line) as the one exception to the receipt-only rule"
    )


def test_sensitivity_dispatch_emits_validation_confidence_backstop() -> None:
    """The SENSITIVITY_TEST dispatch must ask for `validation_confidence`.

    `sensitivity.py` grew an optional `validation_confidence` map so a range that
    omits its own `confidence` still gets the right widening floor (derived +/-30%,
    agent_estimate +/-50%) instead of silently defaulting to `sourced`, which widens
    nothing. That producer change is INERT unless the dispatch actually emits the
    key -- nothing else in the pipeline constructs it, and this repo has shipped a
    guardrail inert before. This pins the wiring, not the producer.
    """
    text = SKILL_MD.read_text(encoding="utf-8")
    assert "validation_confidence" in text, (
        "market-sizing/SKILL.md no longer asks the SENSITIVITY_TEST sub-agent for "
        "`validation_confidence`. Without it, a range missing its own `confidence` falls back "
        "to `sourced` and a derived/agent_estimate parameter loses its widening floor silently."
    )
