"""Drift-contract tests for the deck-review skill.

These tests grep SKILL.md and the agent body against the producer scripts'
actual source so the dispatch prompts can never silently diverge from what
the scripts accept.

Covered contract surfaces:
- Checklist ID enumeration: every checklist ID cited in prose must exist in
  checklist.py's canonical VALID_IDS set (populated independently of that set);
  checklist-criteria.md header IDs must equal VALID_IDS exactly (set equality).
- Dispatch return shapes: SLIDE_REVIEWS, CHECKLIST, and POST_COMPOSE_COACHING
  templates must carry the keys the consuming scripts read, including
  metadata.run_id for parity artifacts.
- No-file-writes instruction: Context A dispatch templates must forbid artifact
  writes; the agent body must also ban Bash in both contexts.
- Gate-required artifacts: every artifact compose_report.py's REQUIRED_ARTIFACTS
  list names must appear in SKILL.md with a producing step.
- Cleanup coverage: setup_run.py's _CLEANABLE_NAMES must cover every per-run
  pipeline artifact that appears in SKILL.md (including artifacts mentioned only
  in bash blocks).
- No shell-variable capture of python output: dead-variable regression guard —
  zero carve-outs (house pattern: same regex as FMR/cap-table).
- Flag existence: every --flag in bash invocations of deck-review scripts in
  SKILL.md must exist in that script's argparse add_argument definitions;
  --rebuild-stage and --confidence choice values must match argparse choices.
- gate_state: gate_id enum in SKILL.md must match the schema's enum exactly,
  including values named in the colon form (`gate_id: "value"`).
- Agent body run_id-parity artifact list must equal compose_report.py
  REQUIRED_ARTIFACTS exactly.
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
DR_DIR = REPO_ROOT / "founder-skills" / "skills" / "deck-review"
SKILL_MD = DR_DIR / "SKILL.md"
AGENT_MD = REPO_ROOT / "founder-skills" / "agents" / "deck-review.md"
SCRIPTS_DIR = DR_DIR / "scripts"
REFS_DIR = DR_DIR / "references"
SCHEMAS_DIR = REFS_DIR / "schemas"


# ---------------------------------------------------------------------------
# Module-loading helpers (unique sys.modules keys avoid cross-skill collisions)
# ---------------------------------------------------------------------------

# Helper modules that scripts in SCRIPTS_DIR import by short name. These names
# are identical across skills (same filename, different skill dir). Guard against
# cross-skill sys.modules contamination by saving and restoring any pre-existing
# binding before and after exec_module for scripts that import them.
_SCRIPTS_DIR_LOCAL_MODULES = ("_artifact_writer",)


def _load_script_module(script_name: str, sys_key: str) -> types.ModuleType:
    """Load a script from SCRIPTS_DIR, injecting the scripts dir on sys.path.

    sys.path is modified only for the duration of exec_module so that relative
    imports (e.g. ``from _artifact_writer import ...``) resolve to the correct
    skill's copy. The path entry is removed afterwards (try/finally) to avoid
    polluting later imports.

    Cross-skill contamination guard: helper module names that are identical
    across skills (listed in _SCRIPTS_DIR_LOCAL_MODULES) are saved from
    sys.modules before exec and restored after, so a prior skill's loaded copy
    does not shadow the correct one.
    """
    path = SCRIPTS_DIR / script_name
    scripts_dir_str = str(SCRIPTS_DIR)

    # Save and remove any pre-existing bindings for local helper modules so they
    # re-resolve from SCRIPTS_DIR on import rather than reusing another skill's copy.
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
        # Remove the injected path entry (may not be at index 0 if nested calls
        # pushed more entries, so search and remove).
        with contextlib.suppress(ValueError):
            sys.path.remove(scripts_dir_str)
        # Restore saved helper bindings so callers that loaded a different
        # skill's copy retain their own reference.
        for name, saved_mod in saved_helpers.items():
            sys.modules[name] = saved_mod

    return mod


def _load_checklist_module() -> types.ModuleType:
    return _load_script_module("checklist.py", "dr_checklist_contract")


def _load_compose_report_module() -> types.ModuleType:
    return _load_script_module("compose_report.py", "dr_compose_report_contract")


def _load_setup_run_module() -> types.ModuleType:
    return _load_script_module("setup_run.py", "dr_setup_run_contract")


# ---------------------------------------------------------------------------
# Flag/mode extraction helpers (shared with cap-table contract pattern)
# ---------------------------------------------------------------------------


def _collect_argparse_flags(script_path: Path) -> frozenset[str]:
    """Return all long-form --flag strings defined via add_argument in the script."""
    src = script_path.read_text(encoding="utf-8")
    return frozenset(re.findall(r'add_argument\([^)]*"(--[a-z][a-z_-]+)"', src))


def _collect_argparse_choices(script_path: Path, flag: str) -> frozenset[str]:
    """Return the choices set for a named --flag in the script's argparse block."""
    src = script_path.read_text(encoding="utf-8")
    # Match: --flag-name ... choices=[...] within one add_argument call
    # The flag name may use hyphens in the --name form but underscores in the dest
    flag_escaped = re.escape(flag)
    block_match = re.search(
        rf'add_argument\([^)]*"{flag_escaped}"[^)]*choices\s*=\s*\[([^\]]+)\]',
        src,
        re.DOTALL,
    )
    if not block_match:
        return frozenset()
    raw = block_match.group(1)
    return frozenset(re.findall(r'["\']([a-z_]+)["\']', raw))


def _collect_subparser_names(script_path: Path) -> frozenset[str]:
    """Return sub-command names registered via add_parser in the script."""
    src = script_path.read_text(encoding="utf-8")
    return frozenset(re.findall(r'add_parser\(["\']([a-z_]+)["\']', src))


def _extract_invocation_flags_from_text(text: str) -> dict[str, set[str]]:
    """Parse all bash blocks in text and return {script_name: set_of_flags}."""
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
            m = re.search(r"python3[^\|;]*?/([a-z_]+\.py)", line)
            if m:
                script_name = m.group(1)
                flags = set(re.findall(r"--[a-z][a-z_-]+", line))
                result.setdefault(script_name, set()).update(flags)
    return result


def _extract_rebuild_stage_values_from_text(text: str) -> set[str]:
    """Return all --rebuild-stage=<value> or --rebuild-stage <value> used in bash blocks."""
    bash_blocks = re.findall(r"```bash\n(.*?)```", text, re.DOTALL)
    result: set[str] = set()
    for block in bash_blocks:
        for val in re.findall(r"--rebuild-stage\s+([a-z_]+)", block):
            result.add(val)
        for val in re.findall(r"--rebuild-stage=([a-z_]+)", block):
            result.add(val)
    return result


def _extract_confidence_values_from_text(text: str) -> set[str]:
    """Return all --confidence=<value> or --confidence <value> used in bash blocks."""
    bash_blocks = re.findall(r"```bash\n(.*?)```", text, re.DOTALL)
    result: set[str] = set()
    for block in bash_blocks:
        for val in re.findall(r"--confidence\s+([a-z_]+)", block):
            result.add(val)
        for val in re.findall(r"--confidence=([a-z_]+)", block):
            result.add(val)
    return result


def _ref_docs_with_dispatch_templates() -> list[Path]:
    """Return reference docs that contain sub-agent dispatch templates.

    Reference docs are scanned; only those containing a CONTEXT: block
    are included. Deck-review reference docs currently carry no dispatch
    templates — this returns an empty list, which is expected.
    """
    result: list[Path] = []
    for p in sorted(REFS_DIR.glob("*.md")):
        if "CONTEXT:" in p.read_text(encoding="utf-8"):
            result.append(p)
    return result


# ---------------------------------------------------------------------------
# Test 1: Checklist ID enumeration — cited IDs must exist in VALID_IDS
# ---------------------------------------------------------------------------


def test_checklist_id_enumeration_population_is_independent() -> None:
    """Checklist ID candidates extracted from SKILL.md+agent prose must be a
    subset of VALID_IDS — phantom IDs in dispatch templates cause the
    sub-agent to evaluate criteria that do not exist in checklist.py.

    Extraction is independent of VALID_IDS (no intersection used as a
    pre-filter). Any candidate NOT in VALID_IDS is a phantom and the test
    reports it explicitly.

    Vacuity guard: at least 1 ID must be extracted. The CHECKLIST dispatch
    template in SKILL.md names at least ``purpose_clear`` as a sample item.
    """
    mod = _load_checklist_module()
    valid_ids: set[str] = set(mod.VALID_IDS)  # type: ignore[attr-defined]

    # Build population independently: extract "id": "some_id" from dispatch
    # prompt templates in SKILL.md and the agent body (JSON field form).
    combined = SKILL_MD.read_text(encoding="utf-8") + "\n" + AGENT_MD.read_text(encoding="utf-8")
    candidates = set(re.findall(r'"id"\s*:\s*"([a-z][a-z0-9_]+)"', combined))

    # Vacuity guard: extraction must find at least 1 ID.
    assert len(candidates) >= 1, (
        'No checklist IDs found via \'"id": "..."\' pattern in SKILL.md + agent body '
        "— extraction regex may have stopped matching or dispatch templates no longer "
        "show example IDs"
    )

    # Phantom check: every extracted candidate must be a known checklist ID.
    phantoms = candidates - valid_ids
    assert not phantoms, (
        f"SKILL.md / agent body cites checklist IDs not in checklist.py VALID_IDS (phantom): {sorted(phantoms)}"
    )


# ---------------------------------------------------------------------------
# Test 1a: CHECKLIST dispatch template enumerates ALL 35 canonical IDs (set-equality)
# ---------------------------------------------------------------------------


def test_checklist_dispatch_template_enumerates_all_canonical_ids() -> None:
    """The CHECKLIST dispatch template in SKILL.md must enumerate all 35 canonical
    checklist IDs explicitly, grouped by category.

    Extraction anchors on the CONTEXT: CHECKLIST section and reads IDs from lines
    matching ``  - id_name`` (two-space indent, dash, snake_case id). This is the
    format written into the template by Fix A.

    Set-equality check (both directions):
    - Phantom: an ID in the template not in checklist.py VALID_IDS → bad ID.
    - Missing: an ID in VALID_IDS not in the template → sub-agent won't see it.

    Mutation check contract:
    - Renaming an ID in the template: phantom check fails.
    - Dropping an ID: missing check fails.
    - Adding a spurious ID: phantom check fails.
    """
    mod = _load_checklist_module()
    valid_ids: set[str] = set(mod.VALID_IDS)  # type: ignore[attr-defined]

    skill_text = SKILL_MD.read_text(encoding="utf-8")
    anchor = "CONTEXT: CHECKLIST"
    start = skill_text.find(anchor)
    assert start != -1, f"{SKILL_MD.name} has no '{anchor}' section"
    # The CHECKLIST section ends at the next ```  fence after the dispatch block
    # Find the end of the full dispatch prompt block (closing ```)
    # Use a generous window: 4000 chars covers the 35-ID list + instructions
    section = skill_text[start : start + 4000]

    # Extract IDs from lines of the form: ``  - snake_case_id``
    # (two-space indent, dash, a valid snake_case identifier)
    enumerated_ids = set(re.findall(r"^  - ([a-z][a-z0-9_]+)$", section, re.MULTILINE))

    # Vacuity guard: must find all 35 (not just some)
    assert len(enumerated_ids) == 35, (
        f"{SKILL_MD.name} CHECKLIST dispatch template enumerates {len(enumerated_ids)} IDs "
        f"(expected 35). "
        f"Found: {sorted(enumerated_ids)}. "
        f"Missing from template: {sorted(valid_ids - enumerated_ids)}"
    )

    # Set-equality (both directions)
    phantom = enumerated_ids - valid_ids
    missing = valid_ids - enumerated_ids
    assert not phantom, (
        f"{SKILL_MD.name} CHECKLIST template lists IDs not in checklist.py VALID_IDS "
        f"(phantom — rename or remove): {sorted(phantom)}"
    )
    assert not missing, (
        f"{SKILL_MD.name} CHECKLIST template is missing IDs from checklist.py VALID_IDS "
        f"(missing — add them): {sorted(missing)}"
    )


# ---------------------------------------------------------------------------
# Test 1b: checklist-criteria.md header IDs must equal VALID_IDS exactly
# ---------------------------------------------------------------------------


def test_checklist_criteria_md_header_ids_equal_valid_ids() -> None:
    """The ``### `id` `` headers in checklist-criteria.md enumerate all 35 criteria
    IDs. They must match checklist.py's VALID_IDS exactly: no phantom headers
    (a header that no longer exists in the script), no missing headers (a script
    ID with no documentation).

    Count guard: exactly 35 headers must be found. A mutation that renames one
    header produces a phantom; removing one produces a missing entry.
    """
    mod = _load_checklist_module()
    valid_ids: set[str] = set(mod.VALID_IDS)  # type: ignore[attr-defined]

    criteria_text = (REFS_DIR / "checklist-criteria.md").read_text(encoding="utf-8")
    # Headers have the form: ### `id_token`
    header_ids = set(re.findall(r"^### `([a-z][a-z0-9_]+)`", criteria_text, re.MULTILINE))

    assert len(header_ids) == 35, (
        f"checklist-criteria.md has {len(header_ids)} ### `id` headers (expected 35); "
        f"count guard ensures a missing or extra header is caught"
    )

    phantom = header_ids - valid_ids
    missing = valid_ids - header_ids
    assert not phantom, (
        f"checklist-criteria.md has ### `id` headers not in checklist.py VALID_IDS "
        f"(phantom — rename them or remove them): {sorted(phantom)}"
    )
    assert not missing, (
        f"checklist-criteria.md is missing ### `id` headers for VALID_IDS entries "
        f"(missing — add a section for each): {sorted(missing)}"
    )


def test_ai_criteria_ids_in_skill_md_and_agent_match_checklist_py() -> None:
    """The 4 AI-company checklist IDs explicitly listed in the SKILL.md CHECKLIST
    dispatch template must exactly match the IDs in checklist.py's AI Company category.

    The population is extracted independently of the canonical set: the CHECKLIST
    dispatch template in SKILL.md names them in a parenthetical as plain snake_case
    tokens (not backtick-quoted), e.g.:
        (ai_retention_rebased, ai_cost_to_serve_shown, ...)
    A renamed or deleted ID would cause the token to not appear in ai_ids_in_script,
    making the phantom check fail.
    """
    mod = _load_checklist_module()
    checklist_items: list[dict[str, str]] = mod.CHECKLIST_ITEMS  # type: ignore[attr-defined]
    ai_ids_in_script = frozenset(i["id"] for i in checklist_items if i.get("category") == "AI Company")

    # Deck-review SKILL.md CHECKLIST template now enumerates all 35 IDs in a grouped
    # list including the 4 AI-criteria IDs. Use a 3000-char window to cover the
    # full enumerated-ID block.
    skill_text = SKILL_MD.read_text(encoding="utf-8")
    anchor = "CONTEXT: CHECKLIST"
    start = skill_text.find(anchor)
    assert start != -1, f"{SKILL_MD.name} has no '{anchor}' section"
    section = skill_text[start : start + 3000]

    # Independent extraction: find any token of the form ai_<word> that is not
    # inside a backtick-quoted file path (those end in .json/.md/.py). This
    # builds the candidate set WITHOUT referencing ai_ids_in_script.
    prose_ai_candidates = set(re.findall(r"\b(ai_[a-z_]+)\b", section))
    # Filter out file-suffix false-positives (none expected, but be safe)
    prose_ai_candidates = {t for t in prose_ai_candidates if not t.endswith((".json", ".md", ".py"))}

    # Vacuity guard: SKILL.md CHECKLIST section must name all 4 AI criteria.
    assert len(prose_ai_candidates) >= 4, (
        f"{SKILL_MD.name} CHECKLIST section names {len(prose_ai_candidates)} ai_* ID tokens "
        f"(expected all 4): got {sorted(prose_ai_candidates)}"
    )

    phantom = prose_ai_candidates - ai_ids_in_script
    missing = ai_ids_in_script - prose_ai_candidates
    assert not phantom, (
        f"{SKILL_MD.name} CHECKLIST section cites AI criteria IDs not in checklist.py: {sorted(phantom)}"
    )
    assert not missing, (
        f"{SKILL_MD.name} CHECKLIST section is missing AI criteria IDs from checklist.py: {sorted(missing)}"
    )

    # Same check on the agent body — Context A's CHECKLIST section
    agent_text = AGENT_MD.read_text(encoding="utf-8")
    agent_anchor = "For `CHECKLIST`"
    agent_start = agent_text.find(agent_anchor)
    assert agent_start != -1, f"{AGENT_MD.name} has no 'For `CHECKLIST`' section"
    agent_section = agent_text[agent_start : agent_start + 1000]
    agent_ai_candidates = set(re.findall(r"\b(ai_[a-z_]+)\b", agent_section))
    agent_ai_candidates = {t for t in agent_ai_candidates if not t.endswith((".json", ".md", ".py"))}
    agent_phantom = agent_ai_candidates - ai_ids_in_script
    assert not agent_phantom, (
        f"{AGENT_MD.name} CHECKLIST section cites AI criteria IDs not in checklist.py: {sorted(agent_phantom)}"
    )


# ---------------------------------------------------------------------------
# Test 2: SLIDE_REVIEWS dispatch return-shape keys vs slide_reviews.py
# ---------------------------------------------------------------------------


def test_slide_reviews_dispatch_return_shape_keys() -> None:
    """The SLIDE_REVIEWS return shape in SKILL.md and the agent body must include
    the top-level keys slide_reviews.py expects via its schema: reviews,
    missing_slides, overall_narrative_assessment.

    Anchor on the CONTEXT: SLIDE_REVIEWS section header; never on bare keyword.
    """
    required_keys = {"reviews", "missing_slides", "overall_narrative_assessment"}

    # SKILL.md anchor
    skill_text = SKILL_MD.read_text(encoding="utf-8")
    anchor = "CONTEXT: SLIDE_REVIEWS"
    start = skill_text.find(anchor)
    assert start != -1, f"{SKILL_MD.name} has no '{anchor}' section"
    section = skill_text[start : start + 2000]
    for key in required_keys:
        assert f'"{key}"' in section, f"{SKILL_MD.name} SLIDE_REVIEWS return shape is missing key '{key}'"

    # Agent body anchor
    agent_text = AGENT_MD.read_text(encoding="utf-8")
    # Agent uses "For `SLIDE_REVIEWS`:" section
    agent_anchor = "For `SLIDE_REVIEWS`:"
    agent_start = agent_text.find(agent_anchor)
    assert agent_start != -1, f"{AGENT_MD.name} has no '{agent_anchor}' section"
    agent_section = agent_text[agent_start : agent_start + 1000]
    for key in required_keys:
        # Keys appear as backtick-quoted tokens in this section, not JSON literals
        assert key in agent_section, f"{AGENT_MD.name} SLIDE_REVIEWS section is missing field '{key}'"


# ---------------------------------------------------------------------------
# Test 3: CHECKLIST dispatch return shape vs checklist.py
# ---------------------------------------------------------------------------


def test_checklist_dispatch_return_shape_keys() -> None:
    """The CHECKLIST dispatch return shape in SKILL.md must include 'items'
    (the only top-level key checklist.py reads from stdin), and the agent body
    must show the same shape.
    """
    # SKILL.md: the return shape appears in the CONTEXT: CHECKLIST section.
    # Use a 3000-char window to cover the full enumerated-ID block (35 IDs added
    # in Fix A push "items" beyond the old 1500-char limit).
    skill_text = SKILL_MD.read_text(encoding="utf-8")
    anchor = "CONTEXT: CHECKLIST"
    start = skill_text.find(anchor)
    assert start != -1, f"{SKILL_MD.name} has no '{anchor}' section"
    section = skill_text[start : start + 3000]
    assert '"items"' in section, (
        f"{SKILL_MD.name} CHECKLIST return shape must include 'items' key (checklist.py reads data['items'] from stdin)"
    )

    # Agent body: CHECKLIST section
    agent_text = AGENT_MD.read_text(encoding="utf-8")
    agent_anchor = "For `CHECKLIST`"
    agent_start = agent_text.find(agent_anchor)
    assert agent_start != -1, f"{AGENT_MD.name} has no 'For `CHECKLIST`' section"
    agent_section = agent_text[agent_start : agent_start + 500]
    assert '"items"' in agent_section, (
        f"{AGENT_MD.name} CHECKLIST section must show the '{{\"items\": [...]}}' return shape"
    )


# ---------------------------------------------------------------------------
# Test 4: POST_COMPOSE_COACHING dispatch — coaching_payload keys
# ---------------------------------------------------------------------------


def test_post_compose_coaching_dispatch_includes_coaching_payload_keys() -> None:
    """The POST_COMPOSE_COACHING dispatch template in SKILL.md must list the
    coaching_payload keys the agent body's Context B procedure consumes, and the
    agent body must enumerate the same keys.
    """
    # Keys compose_report.py emits into coaching_payload (from _emit_coaching_payload):
    required_keys = {
        "summary",
        "failed_items",
        "warned_items",
        "high_severity_warnings",
        "stage",
        "is_ai_company",
        "insertion_marker",
        "report_path",
        "review_dir",
    }

    skill_text = SKILL_MD.read_text(encoding="utf-8")
    anchor = "CONTEXT: POST_COMPOSE_COACHING"
    start = skill_text.find(anchor)
    assert start != -1, f"{SKILL_MD.name} has no '{anchor}' section"
    section = skill_text[start : start + 3000]

    for key in required_keys:
        assert key in section, f"{SKILL_MD.name} POST_COMPOSE_COACHING template is missing coaching_payload key '{key}'"

    # Agent body Context B section
    agent_text = AGENT_MD.read_text(encoding="utf-8")
    agent_anchor = "### Context B"
    agent_start = agent_text.find(agent_anchor)
    assert agent_start != -1, f"{AGENT_MD.name} has no '### Context B' section"
    agent_section = agent_text[agent_start : agent_start + 5000]

    for key in required_keys:
        assert key in agent_section, f"{AGENT_MD.name} Context B procedure is missing coaching_payload key '{key}'"


# ---------------------------------------------------------------------------
# Test 5: Context B success payload keys
# ---------------------------------------------------------------------------


def test_context_b_success_payload_keys() -> None:
    """The Context B success payload defined in the agent body must include the
    keys that SKILL.md's Main-Thread Return section reads from the sub-agent's
    response.
    """
    required_keys = {
        "status",
        "review_dir",
        "report_path",
        "score_pct",
        "overall_status",
        "high_severity_warnings",
    }

    agent_text = AGENT_MD.read_text(encoding="utf-8")
    anchor = "#### 5. Return success payload"
    start = agent_text.find(anchor)
    assert start != -1, f"{AGENT_MD.name} has no '#### 5. Return success payload' section"
    section = agent_text[start : start + 1000]

    for key in required_keys:
        assert f'"{key}"' in section, (
            f"{AGENT_MD.name} Context B success payload is missing key '{key}' "
            f"(SKILL.md Main-Thread Return section references it)"
        )

    # Also verify SKILL.md Main-Thread Return section mentions the same keys
    skill_text = SKILL_MD.read_text(encoding="utf-8")
    main_thread_anchor = "## Main-Thread Return"
    mt_start = skill_text.find(main_thread_anchor)
    assert mt_start != -1, f"{SKILL_MD.name} has no '## Main-Thread Return' section"
    mt_section = skill_text[mt_start : mt_start + 2000]
    for key in {"score_pct", "overall_status", "high_severity_warnings"}:
        assert key in mt_section, f"{SKILL_MD.name} Main-Thread Return section does not mention '{key}'"


# ---------------------------------------------------------------------------
# Test 6: No-file-writes instruction in Context A dispatch templates
# ---------------------------------------------------------------------------


def test_context_a_dispatch_templates_contain_no_write_instruction() -> None:
    """Both SLIDE_REVIEWS and CHECKLIST dispatch templates in SKILL.md must
    explicitly forbid artifact writes — a sub-agent that writes files directly
    bypasses schema validation and run_id stamping.
    """
    skill_text = SKILL_MD.read_text(encoding="utf-8")

    for context, anchor in (
        ("SLIDE_REVIEWS", "CONTEXT: SLIDE_REVIEWS"),
        ("CHECKLIST", "CONTEXT: CHECKLIST"),
    ):
        start = skill_text.find(anchor)
        assert start != -1, f"{SKILL_MD.name} has no '{anchor}' section"
        # Use 3000-char window: the CHECKLIST section now includes the 35-ID enumerated
        # list (Fix A), which pushes "Do NOT write" beyond the old 1500-char limit.
        section = skill_text[start : start + 3000]
        assert "Do NOT write" in section or "do not write" in section, (
            f"{SKILL_MD.name} {context} dispatch template must explicitly forbid "
            f"artifact writes (schema gate bypass risk)"
        )


def test_agent_body_context_a_contains_no_write_instruction() -> None:
    """The agent body's Context A section must forbid writing artifacts to disk
    and must forbid Bash calls.
    """
    agent_text = AGENT_MD.read_text(encoding="utf-8")
    anchor = "### Context A"
    start = agent_text.find(anchor)
    assert start != -1, f"{AGENT_MD.name} has no '### Context A' section"
    next_section = agent_text.find("\n### Context B", start)
    section = agent_text[start:next_section] if next_section != -1 else agent_text[start : start + 5000]

    assert "Do not write" in section or "do not write" in section, (
        f"{AGENT_MD.name} Context A section must explicitly say 'Do not write artifacts'"
    )
    # The hard-rules block must also ban Bash
    assert "Bash" in section and ("Do not call" in section or "do not call" in section), (
        f"{AGENT_MD.name} Context A section must forbid Bash calls"
    )


def test_agent_body_context_b_contains_bash_ban() -> None:
    """The agent body's Context B hard-rules block must explicitly forbid Bash."""
    agent_text = AGENT_MD.read_text(encoding="utf-8")
    anchor = "### Context B"
    start = agent_text.find(anchor)
    assert start != -1, f"{AGENT_MD.name} has no '### Context B' section"
    # Anchor on the hard-rules subheading inside Context B rather than a fixed
    # window — the section can grow without silently dropping the ban from range.
    rules_anchor = "**Hard rules in this context:**"
    rules_start = agent_text.find(rules_anchor, start)
    assert rules_start != -1, f"{AGENT_MD.name} Context B has no hard-rules block"
    rules_section = agent_text[rules_start : rules_start + 1500]

    assert "Do NOT call" in rules_section and "Bash" in rules_section, (
        f"{AGENT_MD.name} Context B hard rules must explicitly say 'Do NOT call `Bash`'"
    )


# ---------------------------------------------------------------------------
# Test 7: No-file-writes in reference docs with dispatch templates
# ---------------------------------------------------------------------------


def test_ref_docs_dispatch_templates_contain_no_write_instruction() -> None:
    """Reference docs that contain dispatch templates must carry the no-write
    instruction. Deck-review references currently have no dispatch templates;
    this test will fail loudly if one is added without the instruction.
    """
    ref_docs = _ref_docs_with_dispatch_templates()
    # Currently expected to be empty for deck-review
    for ref_doc in ref_docs:
        text = ref_doc.read_text(encoding="utf-8")
        for block_start_idx in [m.start() for m in re.finditer(r"CONTEXT:", text)]:
            section = text[block_start_idx : block_start_idx + 2000]
            assert "Do not write" in section or "do not write" in section, (
                f"{ref_doc.name}: dispatch template at char {block_start_idx} "
                f"is missing 'Do not write artifacts' instruction"
            )


# ---------------------------------------------------------------------------
# Test 8: Gate-required artifacts — compose_report REQUIRED_ARTIFACTS in SKILL.md
# ---------------------------------------------------------------------------


def test_required_artifacts_have_producing_steps_in_skill_md() -> None:
    """Every artifact in compose_report.py's REQUIRED_ARTIFACTS list must appear
    in SKILL.md — an artifact with no producing step means compose always fails
    the artifact-present gate.
    """
    mod = _load_compose_report_module()
    required: list[str] = mod.REQUIRED_ARTIFACTS  # type: ignore[attr-defined]

    skill_text = SKILL_MD.read_text(encoding="utf-8")
    missing = [name for name in required if name not in skill_text]
    assert not missing, f"compose_report.py REQUIRED_ARTIFACTS not mentioned in SKILL.md (no producing step): {missing}"


# ---------------------------------------------------------------------------
# Test 9: setup_run _CLEANABLE_NAMES covers every per-run pipeline artifact
# ---------------------------------------------------------------------------


def test_cleanup_names_cover_pipeline_artifacts() -> None:
    """setup_run.py's _CLEANABLE_NAMES must cover every per-run pipeline
    artifact mentioned in SKILL.md. The deck-review skill uses setup_run.py
    --clean instead of a bare rm -f list; staleness is handled via run_id
    parity (STALE_ARTIFACT warning) and setup_run.py's cleanup on fresh runs.

    Extraction covers BOTH backtick spans (``report.html``) AND artifact
    filenames appearing inside bash blocks (e.g. ``-o "$REVIEW_DIR/report.html"``),
    since the latter are invisible to the backtick regex.

    Allowlist: artifacts that are NOT per-run outputs and may legitimately be
    absent from the cleanup set. The ``[a-z_]+`` backtick extractor can never
    match hyphenated names (``artifact-schemas.md`` has a hyphen), so that
    entry is dropped from the allowlist — it would never be found by the
    extractor and its presence would be misleading.
    """
    _ALLOWLIST = frozenset(
        {
            "gate_state.json",  # cleaned separately at end-of-run (Step 9) and
            # on fresh runs by setup_run.py; its own lifecycle is documented
        }
    )
    mod = _load_setup_run_module()
    cleanable: frozenset[str] = frozenset(mod._CLEANABLE_NAMES)  # type: ignore[attr-defined]

    skill_text = SKILL_MD.read_text(encoding="utf-8")

    # Backtick-quoted names (prose and inline code)
    artifact_names = set(re.findall(r"`([a-z_]+\.(?:json|html|md))`", skill_text))

    # Artifact filenames mentioned inside bash blocks (e.g. -o "$REVIEW_DIR/report.html").
    # Exclude paths that go through .staging/ — those are transient temp files
    # deleted by ``rm -rf "$REVIEW_DIR/.staging"`` in Step 9, not per-run pipeline outputs.
    bash_blocks = re.findall(r"```bash\n(.*?)```", skill_text, re.DOTALL)
    for block in bash_blocks:
        for m in re.finditer(r'([\$/"][^\s"]*?)/([a-z_]+\.(?:json|html|md))', block):
            full_path = m.group(0)
            if ".staging" not in full_path:
                artifact_names.add(m.group(2))

    # Vacuity guard: if both extraction regexes stop matching (e.g. a prose
    # reformat drops backtick spans), the test would pass on an empty set.
    assert len(artifact_names) >= 5, (
        f"Artifact-name extraction found only {len(artifact_names)} names in "
        f"SKILL.md — the backtick/bash-block regexes may have stopped matching"
    )

    missing = sorted(
        n
        for n in artifact_names - _ALLOWLIST
        if n not in cleanable
        # Skip reference and schema files (not runtime outputs)
        and not n.endswith(".schema.json")
    )
    assert not missing, f"Pipeline artifacts in SKILL.md not covered by setup_run._CLEANABLE_NAMES: {missing}"


# ---------------------------------------------------------------------------
# Test 10: No shell-variable capture of python output
# ---------------------------------------------------------------------------


def test_no_shell_variable_capture_of_python_output() -> None:
    """Each Bash call runs in a fresh shell; capturing python output into a shell
    variable makes it invisible to any subsequent Bash call or to prose-based
    branching decisions. No carve-outs: the house-pattern zero-carve-out regex
    is the same as FMR and cap-table.

    Variables set within a bash block that are only consumed in the SAME block
    must also be eliminated — they add visual noise with no functional benefit
    and create a maintenance hazard (the next editor might consume the variable
    in prose, which is a dead-variable bug).
    """
    skill_text = SKILL_MD.read_text(encoding="utf-8")
    assert not re.search(r'\w+="\$\(\s*python3?', skill_text), (
        "SKILL.md captures python output into a shell variable — print it instead"
    )


# ---------------------------------------------------------------------------
# Test 11: Flag existence — every --flag in SKILL.md bash blocks must be in argparse
# ---------------------------------------------------------------------------


def test_bash_flags_exist_in_scripts() -> None:
    """Every --flag used in a bash invocation of a deck-review script in SKILL.md
    must exist in that script's argparse add_argument definitions.

    Subcommand invocations (e.g. gate_state.py emit) are handled separately via
    test_gate_state_subcommands_exist_in_script.
    """
    shared_scripts_dir = REPO_ROOT / "founder-skills" / "scripts"

    # Flags that are positional subcommand names, not --flags, and must be
    # excluded from the argparse flag check
    _SUBCOMMAND_TOKENS: frozenset[str] = frozenset()

    invocations = _extract_invocation_flags_from_text(SKILL_MD.read_text(encoding="utf-8"))

    for script_name, flags_used in invocations.items():
        skill_script = SCRIPTS_DIR / script_name
        shared_script = shared_scripts_dir / script_name
        if skill_script.exists():
            script_path = skill_script
        elif shared_script.exists():
            script_path = shared_script
        else:
            continue  # script outside this skill's scope

        defined_flags = _collect_argparse_flags(script_path)
        phantom_flags = flags_used - defined_flags - _SUBCOMMAND_TOKENS
        assert not phantom_flags, (
            f"{script_name}: SKILL.md uses flags not defined in argparse:\n"
            f"  phantom: {sorted(phantom_flags)}\n"
            f"  defined: {sorted(defined_flags)}"
        )


# ---------------------------------------------------------------------------
# Test 12: --rebuild-stage choice values match argparse choices
# ---------------------------------------------------------------------------


def test_rebuild_stage_values_match_argparse_choices() -> None:
    """Every --rebuild-stage value used in SKILL.md bash blocks must be a valid
    argparse choice in stage_profile.py. A phantom value causes argparse to
    error and silently breaks the gate branch that uses it.

    stage_profile.py defines choices dynamically as sorted(_STAGE_TABLE.keys()),
    so the test loads the module to resolve the actual choice set.

    Uses the shared _load_script_module helper so SCRIPTS_DIR is on sys.path
    during exec_module — stage_profile imports _artifact_writer by short name.
    """
    # Load stage_profile using the shared helper so sys.path is set correctly.
    mod = _load_script_module("stage_profile.py", "dr_stage_profile_contract")
    valid_choices: frozenset[str] = frozenset(mod._STAGE_TABLE.keys())  # type: ignore[attr-defined]
    assert valid_choices, "stage_profile.py _STAGE_TABLE is empty — check module load"

    used_values = _extract_rebuild_stage_values_from_text(SKILL_MD.read_text(encoding="utf-8"))
    if not used_values:
        # No --rebuild-stage invocations in SKILL.md — this could be legitimate if
        # they're only in prose. Skip phantom check but confirm the flag exists.
        defined_flags = _collect_argparse_flags(SCRIPTS_DIR / "stage_profile.py")
        assert "--rebuild-stage" in defined_flags, (
            "stage_profile.py does not define --rebuild-stage — SKILL.md references it"
        )
        return

    phantom = used_values - valid_choices
    assert not phantom, (
        f"SKILL.md uses --rebuild-stage values not in stage_profile.py _STAGE_TABLE:\n"
        f"  phantom: {sorted(phantom)}\n"
        f"  valid choices: {sorted(valid_choices)}"
    )


def test_confidence_values_match_argparse_choices() -> None:
    """Every --confidence value used in SKILL.md bash blocks must be a valid
    argparse choice in stage_profile.py.
    """
    valid_choices = _collect_argparse_choices(SCRIPTS_DIR / "stage_profile.py", "--confidence")
    assert valid_choices, "stage_profile.py has no --confidence argparse choices — regex may have broken"

    used_values = _extract_confidence_values_from_text(SKILL_MD.read_text(encoding="utf-8"))
    phantom = used_values - valid_choices
    assert not phantom, (
        f"SKILL.md uses --confidence values not in stage_profile.py argparse choices:\n"
        f"  phantom: {sorted(phantom)}\n"
        f"  valid choices: {sorted(valid_choices)}"
    )


# ---------------------------------------------------------------------------
# Test 13: gate_state.py subcommands exist
# ---------------------------------------------------------------------------


def test_gate_state_subcommands_exist_in_script() -> None:
    """SKILL.md invokes gate_state.py with 'emit' and 'answer' subcommands.
    Both must be registered as add_parser entries in gate_state.py.
    """
    defined_subcommands = _collect_subparser_names(SCRIPTS_DIR / "gate_state.py")
    required = {"emit", "answer"}
    missing = required - defined_subcommands
    assert not missing, (
        f"gate_state.py is missing subcommands used in SKILL.md: {sorted(missing)}\n"
        f"  defined: {sorted(defined_subcommands)}"
    )


# ---------------------------------------------------------------------------
# Test 14: gate_state gate_id enum in SKILL.md matches schema
# ---------------------------------------------------------------------------


def test_gate_state_gate_id_enum_matches_schema() -> None:
    """The gate_id values used in SKILL.md must match the schema's enum exactly.
    A gate_id not in the schema causes gate_state.py validation to reject the
    write, and the pipeline hangs silently.
    """
    schema = json.loads((SCHEMAS_DIR / "gate_state.schema.json").read_text(encoding="utf-8"))
    schema_enum = frozenset(schema["properties"]["gate_id"]["enum"])
    assert schema_enum, "gate_state.schema.json gate_id enum is empty — check schema path"

    skill_text = SKILL_MD.read_text(encoding="utf-8")
    # JSON-object form inside bash heredocs: "gate_id": "value"
    used_gate_ids = set(re.findall(r'"gate_id"\s*:\s*"([^"]+)"', skill_text))
    # Backtick token form: gate_id `value`
    used_gate_ids.update(re.findall(r"gate_id\s+`([a-z_]+)`", skill_text))
    # Colon form in backtick span: `gate_id: "value"`
    used_gate_ids.update(re.findall(r"`gate_id:\s*\"([a-z_]+)\"`", skill_text))

    assert used_gate_ids, f"{SKILL_MD.name} uses no gate_id values — regex may have broken or SKILL.md changed format"

    phantom = used_gate_ids - schema_enum
    assert not phantom, (
        f"{SKILL_MD.name} uses gate_id values not in gate_state.schema.json enum:\n"
        f"  phantom: {sorted(phantom)}\n"
        f"  valid: {sorted(schema_enum)}"
    )
    # gate_state.schema.json must cover the primary gate_id used in every
    # completed run: "stage_confirmation" must be both in the schema and in prose.
    assert "stage_confirmation" in used_gate_ids, (
        f"{SKILL_MD.name} does not reference 'stage_confirmation' gate_id — primary gate is missing from SKILL.md prose"
    )
    assert "stage_confirmation" in schema_enum, (
        "gate_state.schema.json does not include 'stage_confirmation' — schema is incomplete"
    )


# ---------------------------------------------------------------------------
# Test 15: checklist.py VALID_IDS — total count matches documented 35
# ---------------------------------------------------------------------------


def test_checklist_valid_ids_count() -> None:
    """checklist.py VALID_IDS must contain exactly 35 items.

    SKILL.md documents '35 criteria across 7 categories'; the count guard
    catches an accidental deletion or addition that skips the documentation
    update.
    """
    mod = _load_checklist_module()
    valid_ids: set[str] = set(mod.VALID_IDS)  # type: ignore[attr-defined]
    assert len(valid_ids) == 35, f"checklist.py VALID_IDS has {len(valid_ids)} entries (expected 35 per documentation)"

    checklist_items: list[dict[str, str]] = mod.CHECKLIST_ITEMS  # type: ignore[attr-defined]
    assert len(checklist_items) == 35, f"checklist.py CHECKLIST_ITEMS has {len(checklist_items)} entries (expected 35)"

    # Category breakdown: 5+8+5+5+5+4+3 = 35
    expected_categories = {
        "Narrative Flow": 5,
        "Slide Content": 8,
        "Stage Fit": 5,
        "Design & Readability": 5,
        "Common Mistakes": 5,
        "AI Company": 4,
        "Diligence Readiness": 3,
    }
    from collections import Counter

    by_category: Counter[str] = Counter(i["category"] for i in checklist_items)
    for cat, expected_count in expected_categories.items():
        assert by_category[cat] == expected_count, (
            f"checklist.py category '{cat}': expected {expected_count} items, got {by_category[cat]}"
        )


# ---------------------------------------------------------------------------
# Test 16: compose_report.py REQUIRED_ARTIFACTS count matches expected 4
# ---------------------------------------------------------------------------


def test_compose_required_artifacts_count() -> None:
    """compose_report.py's REQUIRED_ARTIFACTS must contain exactly 4 entries —
    the 4 per-step producer artifacts. A silent deletion would let compose
    succeed with missing data.
    """
    mod = _load_compose_report_module()
    required: list[str] = mod.REQUIRED_ARTIFACTS  # type: ignore[attr-defined]
    expected = {"deck_inventory.json", "stage_profile.json", "slide_reviews.json", "checklist.json"}
    assert set(required) == expected, (
        f"compose_report.py REQUIRED_ARTIFACTS mismatch:\n  expected: {sorted(expected)}\n  got: {sorted(required)}"
    )


# ---------------------------------------------------------------------------
# Test 17: Agent body run_id-parity artifact list == compose_report REQUIRED_ARTIFACTS
# ---------------------------------------------------------------------------


def test_agent_body_run_id_parity_artifact_list_matches_required_artifacts() -> None:
    """The agent body's Context B procedure lists the 4 producer artifacts it
    greps for run_id parity. That list must equal compose_report.py's
    REQUIRED_ARTIFACTS exactly.

    A divergence means the agent either skips a parity check (missing entry)
    or attempts to grep a file that compose never produced (phantom entry).
    """
    mod = _load_compose_report_module()
    required: frozenset[str] = frozenset(mod.REQUIRED_ARTIFACTS)  # type: ignore[attr-defined]

    agent_text = AGENT_MD.read_text(encoding="utf-8")

    # The Context B procedure lists the 4 files in a bullet list under
    # "self_verify_artifacts_via_grep_run_id". Extract all *.json filenames
    # from that section.
    anchor = "self_verify_artifacts_via_grep_run_id"
    start = agent_text.find(anchor)
    assert start != -1, f"{AGENT_MD.name} has no '{anchor}' section"
    # Read up to the next #### heading or end of step
    next_heading = agent_text.find("\n####", start + 1)
    section = agent_text[start:next_heading] if next_heading != -1 else agent_text[start : start + 1000]

    agent_artifacts = frozenset(re.findall(r"\b([a-z_]+\.json)\b", section))
    # Exclude metadata-only files that appear in prose but are not parity targets
    # (report.json is explicitly excluded in the agent body — it has no run_id by design)
    agent_artifacts -= frozenset({"report.json"})

    phantom = agent_artifacts - required
    missing = required - agent_artifacts
    assert not phantom, (
        f"{AGENT_MD.name} run_id parity section references artifacts not in "
        f"compose_report.REQUIRED_ARTIFACTS (phantom): {sorted(phantom)}"
    )
    assert not missing, (
        f"{AGENT_MD.name} run_id parity section is missing artifacts from "
        f"compose_report.REQUIRED_ARTIFACTS (missing): {sorted(missing)}"
    )
