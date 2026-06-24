"""Drift-contract tests for the cap-table skill.

These tests grep SKILL.md and the agent body against the producer scripts'
actual source so the dispatch prompts can never silently diverge from what
the scripts accept.

Covered contract surfaces:
- Rule-ID enumeration: every rule_id cited in prose must exist in cap-table-rules.json.
- Instrument `form` enum: values listed in prose must equal the schema's enum exactly.
- Error-code strings (E_*): every code cited in prose must appear somewhere in scripts source.
- Dispatch return-shape keys: keys shown in Context A return-shape templates must be
  the keys the consuming validator actually reads from stdin.
- No-file-writes instruction: Context A dispatch templates must include "Do not write
  artifacts to disk"; lane reference docs with sub-agent templates must also include it.
- Gate-required artifacts: every artifact in compose_report.py's REQUIRED_ARTIFACTS list
  must appear in SKILL.md.
- No shell-variable capture of python output: regression guard for a dead-variable bug
  pattern — no carve-outs permitted.
- Flag existence: every --flag used in a bash invocation of a cap-table script in
  SKILL.md and lane reference docs must appear in that script's argparse add_argument
  calls; --mode= values must match argparse choices.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CAP_TABLE_DIR = REPO_ROOT / "founder-skills" / "skills" / "cap-table"
SKILL_MD = CAP_TABLE_DIR / "SKILL.md"
AGENT_MD = REPO_ROOT / "founder-skills" / "agents" / "cap-table.md"
SCRIPTS_DIR = CAP_TABLE_DIR / "scripts"
RULES_JSON = CAP_TABLE_DIR / "references" / "cap-table-rules.json"
INSTRUMENTS_SCHEMA = CAP_TABLE_DIR / "references" / "schemas" / "instruments.schema.json"
LANES_DIR = CAP_TABLE_DIR / "references" / "lanes"


# ---------------------------------------------------------------------------
# Module-loading helpers (unique sys.modules keys to avoid cross-skill collisions)
# ---------------------------------------------------------------------------


def _load_script_module(script_name: str, sys_key: str) -> types.ModuleType:
    path = SCRIPTS_DIR / script_name
    spec = importlib.util.spec_from_file_location(sys_key, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[sys_key] = mod
    spec.loader.exec_module(mod)  # type: ignore[arg-type]
    return mod


def _load_compose_report_module() -> types.ModuleType:
    return _load_script_module("compose_report.py", "cap_table_compose_report_contract")


def _load_extract_instrument_module() -> types.ModuleType:
    return _load_script_module("extract_instrument.py", "cap_table_extract_instrument_contract")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_all_rule_ids() -> frozenset[str]:
    """Return all rule_id values from cap-table-rules.json."""
    data = json.loads(RULES_JSON.read_text(encoding="utf-8"))
    ids: set[str] = set()
    for domain_rules in data.get("domains", {}).values():
        if isinstance(domain_rules, list):
            for rule in domain_rules:
                if isinstance(rule, dict) and "rule_id" in rule:
                    ids.add(rule["rule_id"])
    return frozenset(ids)


def _load_domain_names() -> frozenset[str]:
    data = json.loads(RULES_JSON.read_text(encoding="utf-8"))
    return frozenset(data.get("domains", {}).keys())


# Allowlist: dotted backtick tokens that start with a domain prefix but are
# NOT rule_ids — data field paths, script filenames, etc.
_BACKTICK_NON_RULE_ALLOWLIST: frozenset[str] = frozenset(
    {
        # option_pool.plan_type is a JSON field path in inputs.json, not a rule_id
        "option_pool.plan_type",
    }
)


def _extract_backtick_rule_id_candidates(text: str, domains: frozenset[str]) -> set[str]:
    """Extract backtick-quoted dotted identifiers that START with a known domain name.

    This population is built INDEPENDENTLY of the canonical rule_id set so that
    a deleted or renamed rule in cap-table-rules.json makes the test fail rather
    than silently disappearing from the cited set.

    Script filenames (``anti_dilution.py``) share the domain prefix but end in
    ``.py`` — excluded. Known data field paths that share the prefix (e.g.
    ``option_pool.plan_type``) are excluded via the explicit allowlist.
    """
    # Match anything in backticks that looks like a dotted identifier
    raw = set(re.findall(r"`([a-z][a-z0-9_]*\.[a-z][a-z0-9_.]+)`", text))
    result: set[str] = set()
    for token in raw:
        # Skip script filenames (end in .py, .json, .md, .schema.json, etc.)
        if re.search(r"\.[a-z]+$", token) and any(token.endswith(ext) for ext in (".py", ".json", ".md", ".sh")):
            continue
        # Keep only tokens whose first segment is a known domain name
        first_segment = token.split(".")[0]
        if first_segment not in domains:
            continue
        # Skip known non-rule tokens
        if token in _BACKTICK_NON_RULE_ALLOWLIST:
            continue
        result.add(token)
    return result


def _collect_argparse_flags(script_path: Path) -> frozenset[str]:
    """Return all long-form ``--flag`` strings defined via add_argument in the script."""
    src = script_path.read_text(encoding="utf-8")
    return frozenset(re.findall(r'add_argument\([^)]*"(--[a-z][a-z_-]+)"', src))


def _collect_argparse_mode_choices(script_path: Path) -> frozenset[str]:
    """Return all choices listed for a --mode argument in the script's argparse block."""
    src = script_path.read_text(encoding="utf-8")
    # Match: choices=["a", "b", "c"]  (single or double quotes, any spacing)
    m = re.search(r'--mode["\'].*?choices\s*=\s*\[([^\]]+)\]', src, re.DOTALL)
    if not m:
        return frozenset()
    raw = m.group(1)
    return frozenset(re.findall(r'["\']([a-z_-]+)["\']', raw))


def _extract_invocation_flags_from_text(text: str) -> dict[str, set[str]]:
    """Parse all bash blocks in ``text`` and return {script_name: set_of_flags}."""
    bash_blocks = re.findall(r"```bash\n(.*?)```", text, re.DOTALL)

    result: dict[str, set[str]] = {}
    for block in bash_blocks:
        # Join continuation lines
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


def _extract_skill_md_invocation_flags() -> dict[str, set[str]]:
    """Parse all bash blocks in SKILL.md and return {script_name: set_of_flags}."""
    return _extract_invocation_flags_from_text(SKILL_MD.read_text(encoding="utf-8"))


def _extract_mode_values_from_text(text: str) -> dict[str, set[str]]:
    """Return {script_name: set_of_mode_values} found in --mode=<value> invocations."""
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
                for mv in re.findall(r"--mode=([a-z_-]+)", line):
                    result.setdefault(script_name, set()).add(mv)
    return result


def _lane_docs_with_dispatch_templates() -> list[Path]:
    """Return lane reference docs that contain sub-agent dispatch templates.

    Lane docs are scanned; only those that contain a dispatch template
    (indicated by a CONTEXT: ... block) are included.
    """
    result: list[Path] = []
    for p in sorted(LANES_DIR.glob("*.md")):
        if "CONTEXT:" in p.read_text(encoding="utf-8"):
            result.append(p)
    return result


# ---------------------------------------------------------------------------
# Test 1: Rule-ID enumeration — every backtick-cited rule_id must exist in JSON
# ---------------------------------------------------------------------------


def test_rule_id_references_exist_in_rules_json() -> None:
    """Every rule_id cited in SKILL.md or a lane reference doc must exist in
    cap-table-rules.json — a phantom rule_id means the rule was renamed or
    deleted and the prose is referencing a dead identifier. The population is
    built independently of the canonical set so a deleted rule cannot silently
    vanish from the check. The agent body uses prose references, not
    backtick-quoted rule_ids, so it is not scanned."""
    all_ids = _load_all_rule_ids()
    domains = _load_domain_names()

    docs = [SKILL_MD, *sorted(LANES_DIR.glob("*.md"))]
    for doc in docs:
        cited = _extract_backtick_rule_id_candidates(doc.read_text(encoding="utf-8"), domains)

        if doc is SKILL_MD:
            # Sanity: SKILL.md must cite at least a few rule_ids.
            # Known citations: safe.discount_rate_semantics,
            # safe.company_capitalization_yc_post_money, safe.post_money_cap_conversion,
            # option_pool.pre_money_topup, anti_dilution.* rules.
            assert len(cited) >= 4, (
                f"{doc.name} has fewer than 4 backtick-quoted rule_id references — "
                f"regex may have silently stopped matching (got {sorted(cited)})"
            )

        phantom = cited - all_ids
        assert not phantom, (
            f"{doc.name} cites rule_ids not present in cap-table-rules.json "
            f"(renamed or deleted rule): {sorted(phantom)}"
        )


# ---------------------------------------------------------------------------
# Test 2: Instrument `form` enum in prose must equal the JSON schema enum
# ---------------------------------------------------------------------------


def _extract_prose_form_enum(text: str) -> frozenset[str]:
    """Parse the form enum list from the 'form enum values are: ...' sentence in text."""
    m = re.search(r"The `form` enum values are:\s*([^\n.]+)", text)
    if not m:
        return frozenset()
    # Values appear as backtick-quoted tokens: `yc_postmoney_cap`, `other`, etc.
    return frozenset(re.findall(r"`([a-z_]+)`", m.group(1)))


def test_safe_form_enum_matches_instruments_schema() -> None:
    """The ``form`` enum values listed in SKILL.md and the agent body must match
    the canonical set from instruments.schema.json exactly — a drift here means
    extract_instrument.py will reject values the prose told the agent to produce
    (or silently accept values the schema no longer recognises).

    The enum list is parsed from the SKILL.md prose itself — never hardcoded —
    so a phantom value added to the prose fails the test."""
    schema = json.loads(INSTRUMENTS_SCHEMA.read_text(encoding="utf-8"))
    # schema path: properties.safes.items.properties.form.enum
    schema_enum = frozenset(schema["properties"]["safes"]["items"]["properties"]["form"]["enum"])

    skill_text = SKILL_MD.read_text(encoding="utf-8")
    prose_enum = _extract_prose_form_enum(skill_text)

    assert prose_enum, (
        f"{SKILL_MD.name} has no 'The `form` enum values are: ...' sentence — cannot verify form enum against schema"
    )

    assert schema_enum == prose_enum, (
        f"instruments.schema.json safe form enum drifted from {SKILL_MD.name} prose:\n"
        f"  phantom (schema has, prose doesn't): {sorted(schema_enum - prose_enum)}\n"
        f"  phantom (prose has, schema doesn't): {sorted(prose_enum - schema_enum)}"
    )

    # Additionally verify the agent body mentions all enum values somewhere
    agent_text = AGENT_MD.read_text(encoding="utf-8")
    for val in schema_enum - {"other"}:  # 'other' is a catch-all; prose may omit it
        assert val in agent_text, f"agent body does not mention form value '{val}' — extraction guidance is incomplete"

    # And SKILL.md mentions all values in the Lane-4 skeleton section
    for val in {"yc_postmoney_cap", "cap_plus_discount", "yc_premoney_cap_only"}:
        assert val in skill_text, f"SKILL.md does not mention form value '{val}'"


# ---------------------------------------------------------------------------
# Test 3: E_* error codes cited in prose must be defined in scripts source
# ---------------------------------------------------------------------------


def test_error_codes_in_prose_exist_in_scripts() -> None:
    """Every E_* code cited in SKILL.md (outside comments) must appear in at
    least one script's source — a phantom code means the prose references an
    error that the scripts never emit, making the recovery guidance useless."""
    skill_text = SKILL_MD.read_text(encoding="utf-8")
    cited_codes = set(re.findall(r"\bE_[A-Z_]+\b", skill_text))

    # Collect all E_* strings defined (as string literals) across all scripts
    defined_codes: set[str] = set()
    for src_file in SCRIPTS_DIR.glob("*.py"):
        src = src_file.read_text(encoding="utf-8")
        # Match both "E_FOO" (quoted) and bare E_FOO in f-strings / error messages
        defined_codes.update(re.findall(r'"(E_[A-Z_]+)"', src))
        defined_codes.update(re.findall(r"f['\"].*?(E_[A-Z_]+)", src))

    phantom = cited_codes - defined_codes
    assert not phantom, (
        f"SKILL.md cites E_* codes that are not defined in any script:\n"
        f"  phantom: {sorted(phantom)}\n"
        f"  defined: {sorted(defined_codes)}"
    )


# ---------------------------------------------------------------------------
# Test 4: INSTRUMENT_EXTRACTION return-shape keys vs extract_instrument.py reads
# ---------------------------------------------------------------------------


def test_instrument_extraction_return_shape_keys() -> None:
    """The INSTRUMENT_EXTRACTION return shape shown in the agent body must include
    the top-level keys that extract_instrument.py reads from stdin — a missing key
    means every extraction silently drops that data and the validator can't gate."""
    _load_extract_instrument_module()
    # extract_instrument.py reads these four keys from the stdin dict:
    # itype = extraction.get("instrument_type")
    # fields = extraction.get("fields", {})
    # confidence = extraction.get("confidence", {})
    # ambiguities = extraction.get("ambiguities", [])
    required_keys = {"instrument_type", "fields", "confidence", "ambiguities"}

    # Anchor on the return-shape block header directly — the sub-context section
    # header is thousands of chars before the actual JSON template.
    agent_text = AGENT_MD.read_text(encoding="utf-8")
    anchor = "**Return shape (for `INSTRUMENT_EXTRACTION`):**"
    start = agent_text.find(anchor)
    assert start != -1, f"{AGENT_MD.name} has no '{anchor}' section"
    section = agent_text[start : start + 2000]

    for key in required_keys:
        assert f'"{key}"' in section, (
            f"{AGENT_MD.name} INSTRUMENT_EXTRACTION return shape is missing key '{key}' "
            f"(extract_instrument.py reads it from stdin)"
        )


# ---------------------------------------------------------------------------
# Test 5: ARTICLES_OF_ASSOCIATION_EXTRACTION return-shape keys vs extract_aoa.py
# ---------------------------------------------------------------------------


def test_aoa_extraction_return_shape_keys() -> None:
    """The ARTICLES_OF_ASSOCIATION_EXTRACTION return shape shown in the agent body
    must include the keys that extract_aoa.py reads from stdin."""
    aoa_src = (SCRIPTS_DIR / "extract_aoa.py").read_text(encoding="utf-8")

    agent_text = AGENT_MD.read_text(encoding="utf-8")
    # Anchor directly on the return-shape block header
    anchor = "**Return shape (for `ARTICLES_OF_ASSOCIATION_EXTRACTION`):**"
    start = agent_text.find(anchor)
    assert start != -1, f"{AGENT_MD.name} has no '{anchor}' section"
    section = agent_text[start : start + 3000]

    # The return shape must include extraction_type and fields at minimum
    for key in ("extraction_type", "fields", "confidence", "ambiguities"):
        assert f'"{key}"' in section, (
            f"{AGENT_MD.name} ARTICLES_OF_ASSOCIATION_EXTRACTION return shape is missing key '{key}'"
        )

    # The return_shape example must show "preferred_series" inside fields
    assert "preferred_series" in section, (
        f"{AGENT_MD.name} ARTICLES_OF_ASSOCIATION_EXTRACTION return shape "
        f"must show preferred_series (the main extraction target)"
    )

    # Verify extract_aoa.py actually reads 'extraction_type' from the JSON
    assert "extraction_type" in aoa_src, (
        "extract_aoa.py does not reference 'extraction_type' key — "
        "AoA extraction contract may have drifted from the agent body template"
    )


# ---------------------------------------------------------------------------
# Test 5b: AoA dispatch template in lane-1-pdf-docx.md — shape + no-write
# ---------------------------------------------------------------------------


def test_lane_aoa_dispatch_template_keys_and_no_write() -> None:
    """The ARTICLES_OF_ASSOCIATION_EXTRACTION dispatch template in lane-1-pdf-docx.md
    must carry the same top-level keys as extract_aoa.py reads from stdin, and must
    include the no-write instruction.

    Mutation targets:
    - Drop a required key from the template JSON → test fails (key not found).
    - Remove 'Do not write artifacts to disk' → test_lane_dispatch_templates_contain_no_write_instruction fails.
    """
    lane_doc = LANES_DIR / "lane-1-pdf-docx.md"
    assert lane_doc.exists(), f"{lane_doc} not found"
    text = lane_doc.read_text(encoding="utf-8")

    # Anchor on the AoA dispatch template section header.
    # The AoA flow spans multiple ## sub-sections (dispatch template, pipe-through bash,
    # error handling, counsel items) — read from the anchor to end of file so all
    # sub-sections are included in the check.
    anchor = "## Dispatch Context A — `ARTICLES_OF_ASSOCIATION_EXTRACTION`"
    start = text.find(anchor)
    assert start != -1, (
        f"{lane_doc.name} has no '{anchor}' section — "
        f"dispatch template for ARTICLES_OF_ASSOCIATION_EXTRACTION is missing"
    )
    section = text[start:]

    # 1. Top-level return-shape keys (same set as extract_aoa.py reads from stdin)
    for key in ("extraction_type", "fields", "confidence", "ambiguities"):
        assert f'"{key}"' in section, (
            f"{lane_doc.name} AoA dispatch template is missing return-shape key '{key}' "
            f"— extract_aoa.py reads it from stdin; template↔script drift detected"
        )

    # 2. preferred_series must appear inside the fields example
    assert "preferred_series" in section, (
        f"{lane_doc.name} AoA dispatch template return-shape example "
        f"must include 'preferred_series' (the primary extraction target)"
    )

    # 3. extraction_type value must be "articles_of_association"
    assert '"articles_of_association"' in section, (
        f"{lane_doc.name} AoA dispatch template must show "
        f'"extraction_type": "articles_of_association" — the script rejects any other value'
    )

    # 4. CONTEXT header must appear in the dispatch prompt block
    assert "CONTEXT: ARTICLES_OF_ASSOCIATION_EXTRACTION" in section, (
        f"{lane_doc.name} AoA dispatch template is missing the "
        f"'CONTEXT: ARTICLES_OF_ASSOCIATION_EXTRACTION' header line"
    )

    # 5. No-write instruction (caught redundantly by test_lane_dispatch_templates_contain_no_write_instruction,
    #    but pin it here too for an explicit, named failure message)
    assert "Do not write" in section or "do not write" in section, (
        f"{lane_doc.name} AoA dispatch template is missing the 'Do not write artifacts to disk' instruction"
    )

    # 6. extract_aoa.py bash invocation must be present with required flags
    assert "extract_aoa.py" in section, f"{lane_doc.name} AoA section must include a bash invocation of extract_aoa.py"
    assert "--run-id" in section, f"{lane_doc.name} AoA extract_aoa.py invocation is missing required --run-id flag"
    assert "--inputs" in section, (
        f"{lane_doc.name} AoA extract_aoa.py invocation is missing --inputs flag "
        f"(merge mode; required for preferred_series to land in inputs.json)"
    )

    # 7. Cross-check: every key in the template's JSON block is a key extract_aoa.py reads
    aoa_src = (SCRIPTS_DIR / "extract_aoa.py").read_text(encoding="utf-8")
    for key in ("extraction_type", "fields", "preferred_series"):
        assert key in aoa_src, f"extract_aoa.py does not reference '{key}' — lane-doc template↔script drift"


# ---------------------------------------------------------------------------
# Test 6: POST_COMPOSE_COACHING dispatch template — coaching_payload keys
# ---------------------------------------------------------------------------


def test_post_compose_coaching_dispatch_includes_coaching_payload_keys() -> None:
    """The POST_COMPOSE_COACHING dispatch template in SKILL.md must list the
    coaching_payload keys that the agent body's Context B procedure consumes.
    A missing key in the template means the agent can't complete its procedure."""
    # compose_report.py writes these keys into coaching_payload:
    # (from build_coaching_payload())
    required_payload_keys = {
        "scenario_digest",
        "ownership_range_across_scenarios",
        "top_dilution_drivers",
        "counsel_review_summary",
        "date_sensitive_summary",
        "insertion_marker",
    }

    skill_text = SKILL_MD.read_text(encoding="utf-8")
    anchor = "CONTEXT: POST_COMPOSE_COACHING"
    start = skill_text.find(anchor)
    assert start != -1, f"{SKILL_MD.name} has no '{anchor}' section"
    section = skill_text[start : start + 3000]

    for key in required_payload_keys:
        assert key in section, f"{SKILL_MD.name} POST_COMPOSE_COACHING template is missing coaching_payload key '{key}'"

    # Verify the same keys appear in the agent body's Context B procedure
    agent_text = AGENT_MD.read_text(encoding="utf-8")
    agent_anchor = "### Context B"
    agent_start = agent_text.find(agent_anchor)
    assert agent_start != -1, f"{AGENT_MD.name} has no '### Context B' section"
    agent_section = agent_text[agent_start : agent_start + 8000]

    for key in required_payload_keys:
        assert key in agent_section, f"{AGENT_MD.name} Context B procedure is missing coaching_payload key '{key}'"


# ---------------------------------------------------------------------------
# Test 7: compose_report.py REQUIRED_ARTIFACTS are all produced in SKILL.md
# ---------------------------------------------------------------------------


def test_required_artifacts_have_producing_steps_in_skill_md() -> None:
    """Every artifact in compose_report.py's REQUIRED_ARTIFACTS list must appear
    in SKILL.md — an artifact with no producing step means compose always fails
    the artifact-present gate."""
    mod = _load_compose_report_module()
    required: list[str] = mod.REQUIRED_ARTIFACTS  # type: ignore[attr-defined]

    skill_text = SKILL_MD.read_text(encoding="utf-8")
    missing = [name for name in required if name not in skill_text]
    assert not missing, f"compose_report.py REQUIRED_ARTIFACTS not mentioned in SKILL.md (no producing step): {missing}"


# ---------------------------------------------------------------------------
# Test 8: Context A dispatch — "Do not write artifacts" instruction present
# ---------------------------------------------------------------------------


def test_context_a_dispatch_contains_no_write_instruction() -> None:
    """The agent body's Context A section must explicitly forbid artifact writes
    so sub-agents cannot produce orphaned files that bypass the anti-hallucination
    gate in extract_instrument.py / extract_cap_table.py."""
    agent_text = AGENT_MD.read_text(encoding="utf-8")
    # Anchor on the Context A section
    anchor = "### Context A"
    start = agent_text.find(anchor)
    assert start != -1, f"{AGENT_MD.name} has no '### Context A' section"
    # Check within a generous window covering all of Context A
    next_section = agent_text.find("\n### Context B", start)
    section = agent_text[start:next_section] if next_section != -1 else agent_text[start : start + 10000]

    assert "Do not write" in section or "do not write" in section, (
        f"{AGENT_MD.name} Context A section must explicitly say 'Do not write "
        f"artifacts to disk' — sub-agent must not bypass the anti-hallucination gate"
    )

    # Also check it prohibits Bash
    assert "Do not call" in section and "Bash" in section, (
        f"{AGENT_MD.name} Context A section must forbid Bash tool calls "
        f"(sub-agent has no Bash; prohibition must be explicit)"
    )


# ---------------------------------------------------------------------------
# Test 8b: Lane reference dispatch templates — "Do not write" instruction present
# ---------------------------------------------------------------------------


def test_lane_dispatch_templates_contain_no_write_instruction() -> None:
    """Lane reference docs that contain sub-agent dispatch templates must include
    the 'Do not write artifacts' instruction — regression guard for lane docs that
    carry their own dispatch templates independently of the agent body."""
    lane_docs = _lane_docs_with_dispatch_templates()
    assert lane_docs, f"No lane docs with dispatch templates found under {LANES_DIR} — check path"
    for lane_doc in lane_docs:
        text = lane_doc.read_text(encoding="utf-8")
        # Find each dispatch template block
        for block_start in [m.start() for m in re.finditer(r"CONTEXT:", text)]:
            section = text[block_start : block_start + 2000]
            assert "Do not write" in section or "do not write" in section, (
                f"{lane_doc.name}: dispatch template starting at char {block_start} "
                f"is missing 'Do not write artifacts' instruction"
            )


# ---------------------------------------------------------------------------
# Test 9: Context B dispatch — Bash ban present in agent body
# ---------------------------------------------------------------------------


def test_context_b_dispatch_contains_bash_ban() -> None:
    """The agent body's Context B section must explicitly forbid Bash — the
    sub-agent must edit report.md only via the Edit tool at the uuid marker."""
    agent_text = AGENT_MD.read_text(encoding="utf-8")
    anchor = "### Context B"
    start = agent_text.find(anchor)
    assert start != -1, f"{AGENT_MD.name} has no '### Context B' section"
    section = agent_text[start : start + 12000]

    assert "Do NOT call" in section and "Bash" in section, (
        f"{AGENT_MD.name} Context B section must explicitly forbid Bash calls with 'Do NOT call `Bash`'"
    )


# ---------------------------------------------------------------------------
# Test 10: No shell-variable capture of python output
# ---------------------------------------------------------------------------


def test_no_shell_variable_capture_of_python_output() -> None:
    """Each Bash call runs in a fresh shell; VAR=\"$(python3 ...)\" captures the
    payload invisibly and the variable dies immediately — regression guard for
    the dead-variable bug pattern. No carve-outs are permitted."""
    skill_text = SKILL_MD.read_text(encoding="utf-8")
    assert not re.search(r'\w+="\$\(\s*python3?', skill_text), (
        "SKILL.md captures python output into a shell variable — print it instead"
    )


# ---------------------------------------------------------------------------
# Test 11: Flag existence — every --flag in SKILL.md bash blocks must be
#          defined in the corresponding script's argparse
# ---------------------------------------------------------------------------


def test_bash_flags_exist_in_scripts() -> None:
    """Every --flag used in a bash invocation of a cap-table script in SKILL.md
    must exist in that script's argparse add_argument definitions — a phantom
    flag causes argparse to error and the pipeline step to fail silently."""
    # Scripts in the shared scripts dir use a separate lookup
    shared_scripts_dir = REPO_ROOT / "founder-skills" / "scripts"

    invocations = _extract_skill_md_invocation_flags()

    for script_name, flags_used in invocations.items():
        # Resolve the script path
        skill_script = SCRIPTS_DIR / script_name
        shared_script = shared_scripts_dir / script_name
        if skill_script.exists():
            script_path = skill_script
        elif shared_script.exists():
            script_path = shared_script
        else:
            # Skip scripts that live outside this skill (e.g., shared scripts
            # that may not be in scope for this test)
            continue

        defined_flags = _collect_argparse_flags(script_path)
        phantom_flags = flags_used - defined_flags
        assert not phantom_flags, (
            f"{script_name}: SKILL.md uses flags not defined in argparse:\n"
            f"  phantom: {sorted(phantom_flags)}\n"
            f"  defined: {sorted(defined_flags)}"
        )


# ---------------------------------------------------------------------------
# Test 11b: Flag existence — lane reference docs
# ---------------------------------------------------------------------------


def test_lane_bash_flags_exist_in_scripts() -> None:
    """Every --flag used in a bash invocation of a cap-table script in a lane
    reference doc must exist in that script's argparse add_argument definitions."""
    shared_scripts_dir = REPO_ROOT / "founder-skills" / "scripts"

    for lane_doc in sorted(LANES_DIR.glob("*.md")):
        invocations = _extract_invocation_flags_from_text(lane_doc.read_text(encoding="utf-8"))
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
                f"{lane_doc.name} → {script_name}: lane doc uses flags not defined in argparse:\n"
                f"  phantom: {sorted(phantom_flags)}\n"
                f"  defined: {sorted(defined_flags)}"
            )


# ---------------------------------------------------------------------------
# Test 11c: --mode= values in lane reference docs must be valid argparse choices
# ---------------------------------------------------------------------------


def test_lane_mode_values_match_argparse_choices() -> None:
    """Every --mode=<value> used in a lane reference doc's bash blocks must be
    a valid argparse choice in the corresponding script — regression guard for
    mode values that were renamed or never existed."""
    shared_scripts_dir = REPO_ROOT / "founder-skills" / "scripts"

    for lane_doc in sorted(LANES_DIR.glob("*.md")):
        mode_invocations = _extract_mode_values_from_text(lane_doc.read_text(encoding="utf-8"))
        for script_name, mode_values in mode_invocations.items():
            skill_script = SCRIPTS_DIR / script_name
            shared_script = shared_scripts_dir / script_name
            if skill_script.exists():
                script_path = skill_script
            elif shared_script.exists():
                script_path = shared_script
            else:
                continue

            valid_choices = _collect_argparse_mode_choices(script_path)
            if not valid_choices:
                continue  # script has no --mode argument

            phantom_modes = mode_values - valid_choices
            assert not phantom_modes, (
                f"{lane_doc.name} → {script_name}: lane doc uses --mode= values "
                f"not in argparse choices:\n"
                f"  phantom: {sorted(phantom_modes)}\n"
                f"  valid choices: {sorted(valid_choices)}"
            )


# ---------------------------------------------------------------------------
# Test 12: SPREADSHEET_STRUCTURE_DETECTION return shape
# ---------------------------------------------------------------------------


def test_spreadsheet_structure_detection_return_shape() -> None:
    """The SPREADSHEET_STRUCTURE_DETECTION return shape shown in the agent body must
    include the 'blocks' key that extract_cap_table.py reads from its stdin."""
    agent_text = AGENT_MD.read_text(encoding="utf-8")
    anchor = "#### Sub-context: `SPREADSHEET_STRUCTURE_DETECTION`"
    start = agent_text.find(anchor)
    assert start != -1, f"{AGENT_MD.name} has no '{anchor}' section"
    section = agent_text[start : start + 4000]

    # extract_cap_table.py --mode=freeform-emit expects {"blocks": [...]}
    assert '"blocks"' in section, (
        f"{AGENT_MD.name} SPREADSHEET_STRUCTURE_DETECTION return shape "
        f"is missing 'blocks' key (extract_cap_table.py reads blocks from stdin)"
    )

    # Verify extract_cap_table.py actually reads 'blocks'
    ext_src = (SCRIPTS_DIR / "extract_cap_table.py").read_text(encoding="utf-8")
    assert '"blocks"' in ext_src, (
        "extract_cap_table.py does not reference 'blocks' key — SPREADSHEET_STRUCTURE_DETECTION contract may be stale"
    )


# ---------------------------------------------------------------------------
# Test 13: Context B success payload keys match compose_report.py's schema
# ---------------------------------------------------------------------------


def test_context_b_success_payload_keys_match_compose() -> None:
    """The Context B success payload defined in the agent body must include all
    keys that the main thread reads from the sub-agent's return — a missing key
    causes the main thread to KeyError when unpacking the coaching result."""
    # Main-thread reads (from SKILL.md Step 11 + Main-Thread Return section):
    # status, review_dir, report_path, scenarios_modeled, counsel_review_count,
    # completeness_breakdown, high_severity_warnings
    required_return_keys = {
        "status",
        "review_dir",
        "report_path",
        "scenarios_modeled",
        "counsel_review_count",
        "completeness_breakdown",
        "high_severity_warnings",
    }

    agent_text = AGENT_MD.read_text(encoding="utf-8")
    anchor = "#### 5. Return success payload"
    start = agent_text.find(anchor)
    assert start != -1, f"{AGENT_MD.name} has no '#### 5. Return success payload' section"
    section = agent_text[start : start + 2000]

    for key in required_return_keys:
        assert f'"{key}"' in section, (
            f"{AGENT_MD.name} Context B success payload is missing key '{key}' "
            f"(SKILL.md Main-Thread Return section reads it)"
        )

    # Also verify SKILL.md Main-Thread Return section mentions the same keys
    skill_text = SKILL_MD.read_text(encoding="utf-8")
    main_thread_anchor = "## Main-Thread Return"
    mt_start = skill_text.find(main_thread_anchor)
    assert mt_start != -1, f"{SKILL_MD.name} has no '## Main-Thread Return' section"
    mt_section = skill_text[mt_start : mt_start + 2000]

    for key in {"scenarios_modeled", "counsel_review_count", "completeness_breakdown", "high_severity_warnings"}:
        assert key in mt_section, f"{SKILL_MD.name} Main-Thread Return section does not mention '{key}'"


# ---------------------------------------------------------------------------
# Test 14: instrument_type enum in extract_instrument.py matches agent body
# ---------------------------------------------------------------------------


def test_instrument_type_enum_matches_extract_instrument() -> None:
    """The instrument_type values listed in the agent body's INSTRUMENT_EXTRACTION
    section must match the valid_itypes set in extract_instrument.py — a drift means
    the agent may return a type the validator rejects (hard error) or an accepted type
    that the agent wasn't told to use."""
    _load_extract_instrument_module()
    # Reconstruct valid_itypes from the script source (the set is defined inline)
    src = (SCRIPTS_DIR / "extract_instrument.py").read_text(encoding="utf-8")
    # Extract the valid_itypes block
    block_match = re.search(r"valid_itypes\s*=\s*\{([^}]+)\}", src, re.DOTALL)
    assert block_match, "extract_instrument.py valid_itypes set not found"
    script_types = frozenset(re.findall(r'"([a-z_]+)"', block_match.group(1)))

    # Collect types mentioned in the agent body's return-shape template.
    # Note: the header uses a colon, not bold without colon.
    agent_text = AGENT_MD.read_text(encoding="utf-8")
    anchor = "**Return shape (for `INSTRUMENT_EXTRACTION`):**"
    start = agent_text.find(anchor)
    assert start != -1, f"{AGENT_MD.name} has no return-shape template for INSTRUMENT_EXTRACTION"
    section = agent_text[start : start + 2000]

    # The return shape shows the instrument_type field as a pipe-separated enum
    # e.g. "instrument_type": "safe | convertible_note | ... | non_instrument"
    prose_types_raw = re.search(r'"instrument_type"\s*:\s*"([^"]+)"', section)
    assert prose_types_raw, f"{AGENT_MD.name} INSTRUMENT_EXTRACTION return shape has no instrument_type enum"
    prose_types = frozenset(t.strip() for t in prose_types_raw.group(1).split("|") if t.strip())

    phantom = prose_types - script_types
    missing = script_types - prose_types
    assert not phantom, (
        f"{AGENT_MD.name} instrument_type enum has values not in extract_instrument.py:\n  phantom: {sorted(phantom)}"
    )
    assert not missing, (
        f"{AGENT_MD.name} instrument_type enum is missing values from extract_instrument.py:\n"
        f"  missing: {sorted(missing)}"
    )


# ---------------------------------------------------------------------------
# S2 / S3 / S5 drift-contract guards (structural, not prose-presence)
# ---------------------------------------------------------------------------

_CAP_STATE_SRC = (SCRIPTS_DIR / "cap_state.py").read_text(encoding="utf-8")
_COMPOSE_SRC = (SCRIPTS_DIR / "compose_report.py").read_text(encoding="utf-8")
# Warning callouts were extracted to a shared renderer (Issue C); compose + concise both delegate to it.
_WARNING_CALLOUTS_SRC = (SCRIPTS_DIR / "_warning_callouts.py").read_text(encoding="utf-8")
_QUICK_ASSESS_SRC = (SCRIPTS_DIR / "quick_assess.py").read_text(encoding="utf-8")
_SKILL_TEXT = SKILL_MD.read_text(encoding="utf-8")
_INPUTS_SCHEMA = json.loads((CAP_TABLE_DIR / "references" / "schemas" / "inputs.schema.json").read_text())
_FAST_ASSESS_SCHEMA = json.loads(
    (CAP_TABLE_DIR / "references" / "schemas" / "fast_assess_only.schema.json").read_text()
)


def test_s3_investor_founder_warning_wired() -> None:
    # producer emits it, the shared renderer renders it (compose delegates), SKILL documents the exclusion
    assert "W_FOUNDER_LOOKS_LIKE_INVESTOR" in _CAP_STATE_SRC
    assert "looks_like_investor_entity" in _CAP_STATE_SRC
    assert "W_FOUNDER_LOOKS_LIKE_INVESTOR" in _WARNING_CALLOUTS_SRC
    assert "_warning_callouts" in _COMPOSE_SRC  # compose delegates rendering to the shared module
    assert "investor" in _SKILL_TEXT.lower() and "founder candidate" in _SKILL_TEXT.lower()


def test_s2_cap_base_assumed_wired() -> None:
    assert "W_CAP_BASE_ASSUMED" in _CAP_STATE_SRC
    assert "W_CAP_BASE_ASSUMED" in _WARNING_CALLOUTS_SRC
    assert "_warning_callouts" in _COMPOSE_SRC  # compose delegates rendering to the shared module
    assert "cap_base_source" in _SKILL_TEXT
    # schema declares the enum (present-key enforcement)
    props = _INPUTS_SCHEMA["properties"]["metadata"]["properties"]
    assert props["cap_base_source"]["enum"] == ["confirmed", "assumed"]


def test_cap_base_reconstructed_wired() -> None:
    # provenance: producer emits the warning, the shared renderer renders it, SKILL + schema document the field
    assert "W_CAP_BASE_RECONSTRUCTED" in _CAP_STATE_SRC
    assert "W_CAP_BASE_RECONSTRUCTED" in _WARNING_CALLOUTS_SRC
    assert "cap_base_provenance" in _CAP_STATE_SRC
    assert "cap_base_provenance" in _SKILL_TEXT
    props = _INPUTS_SCHEMA["properties"]["metadata"]["properties"]
    assert "cap_base_provenance" in props and props["cap_base_provenance"]["type"] == "string"


def test_fd_reconciliation_wired() -> None:
    # A1: cap_state emits the reconcile warning, the renderer renders it, the carta extractor captures the
    # independent total, SKILL routes it, schema declares stated_totals.
    assert "W_FD_RECONCILE_DELTA" in _CAP_STATE_SRC
    assert "W_FD_RECONCILE_DELTA" in _WARNING_CALLOUTS_SRC
    assert "_extract_carta_fd_total" in (SCRIPTS_DIR / "extract_cap_table.py").read_text(encoding="utf-8")
    assert "stated_totals" in _SKILL_TEXT
    assert "stated_totals" in _INPUTS_SCHEMA["properties"]


def test_vision_image_pdf_guard_wired() -> None:
    # B0/B3: probe exists, cap_state emits the low-confidence warning, the renderer renders it, SKILL routes
    assert (SCRIPTS_DIR / "pdf_probe.py").exists()
    assert "W_VISION_EXTRACTION_LOW_CONFIDENCE" in _CAP_STATE_SRC
    assert "W_VISION_EXTRACTION_LOW_CONFIDENCE" in _WARNING_CALLOUTS_SRC
    assert "extraction_mode" in _CAP_STATE_SRC
    assert "pdf_probe" in _SKILL_TEXT and "vision_image_pdf" in _SKILL_TEXT
    props = _INPUTS_SCHEMA["properties"]["metadata"]["properties"]
    assert "extraction_mode" in props and props["extraction_mode"]["type"] == "string"


def test_s5_fast_assess_warnings_field_and_boundary() -> None:
    # sentinel schema declares warnings (optional, not required) so the render validates
    assert "warnings" in _FAST_ASSESS_SCHEMA["properties"]
    assert "warnings" not in _FAST_ASSESS_SCHEMA.get("required", [])
    assert _FAST_ASSESS_SCHEMA["additionalProperties"] is False
    # quick_assess actually surfaces cap_state warnings into the sentinel
    assert 'sentinel["warnings"]' in _QUICK_ASSESS_SRC
    # routing boundary clause present (acknowledged presence-only)
    assert "quick_assess" in _SKILL_TEXT and "post-financing ownership" in _SKILL_TEXT


# ---------------------------------------------------------------------------
# Lane-3 gate-quality guards (skill-side fixes: grid self-chunking, discount
# no-gate + conversion surfacing, canonical gate phrasing)
# ---------------------------------------------------------------------------

_LANE3_TEXT = (LANES_DIR / "lane-3-freeform.md").read_text(encoding="utf-8")


def test_lane3_grid_paste_verbatim_no_chunking() -> None:
    """#8 — the agent must be told the --mode=grid output is pre-compacted and to
    paste it verbatim, not hand-condense/chunk it (the observed wasted-turn bug)."""
    assert "hand-condense, sample, summarize, or chunk" in _LANE3_TEXT, (
        "lane-3-freeform.md must instruct the agent NOT to hand-condense/chunk the grid"
    )
    assert "VERBATIM into the dispatch prompt" in _LANE3_TEXT
    # And the freeform-emit stdin must be piped verbatim (the observed stdin-fumble bug).
    assert "verbatim on stdin" in _LANE3_TEXT


def test_lane3_ok_true_surfaces_warnings() -> None:
    """#9 — the ok:true branch must surface producer `warnings` (e.g. the discount
    rate->multiplier conversion) as non-blocking notes; this is the Lane-3 safety net
    (no invariant_checker on the freeform path) and closes the inert-warning gap."""
    # Anchor on the ok:true bullet so we test the success branch, not the blocker branch.
    anchor = '`{"ok": true, "warnings"'
    start = _LANE3_TEXT.find(anchor)
    assert start != -1, "lane-3-freeform.md ok:true bullet must surface warnings (show the warnings key)"
    section = _LANE3_TEXT[start : start + 800]
    assert "Surface any `warnings`" in section
    assert "NON-blocking notes" in section
    # tie it to the discount conversion specifically (robust to markdown line-wrapping)
    assert "discount" in section.lower() and "multiplier" in section
    # Consistency: the ok:false blocker-resolver must NOT batch warnings into the AskUserQuestion
    # (that contradicts the no-gate rule — warnings are transparency, blockers are the gate).
    assert "(plus any `warnings`)" not in _LANE3_TEXT, (
        "ok:false resolver must not batch `warnings` into the AskUserQuestion gate"
    )


def test_skill_freeform_discount_not_a_confirm_gate() -> None:
    """#9 — SKILL.md must tell the agent NOT to raise a discount rate-vs-multiplier
    AskUserQuestion on the freeform path (the convention is deterministic). The
    discount math is unchanged; this only stops the discretionary gate."""
    assert "Freeform `discount` is NOT a confirm-gate field" in _SKILL_TEXT
    assert "NEVER raise a rate-vs-multiplier" in _SKILL_TEXT
    # references the source-of-truth convention so the instruction can't drift loose
    assert "discount_convention" in _SKILL_TEXT


def test_skill_canonical_gate_phrasing_present() -> None:
    """#7 — SKILL.md must carry canonical gate phrasing for the recurring gates so
    founders + regression cassettes get stable text, and the option pool gate must
    keep the free-text affordance (cap-base chat path must not collapse to yes/no).

    Assertions are scoped to the canonical-phrasing BLOCK so they pin the new text,
    not pre-existing occurrences elsewhere in SKILL.md (e.g. the bolded scenario
    bullets above it or the S2 gate's own 'authorized / issued / unallocated')."""
    start = _SKILL_TEXT.find("Gate Catalog")
    assert start != -1, "SKILL.md must carry a 'Gate Catalog' canonical-phrasing block"
    block = _SKILL_TEXT[start : start + 3000]
    # scenario labels — within the catalog
    for label in ("Cap-implied SAFE snapshot", "Series A priced round", "Convertible note conversion at financing"):
        assert label in block, f"canonical scenario label missing from the Gate Catalog: {label!r}"
    # option-pool labels + preserved free-text affordance
    assert "No option pool" in block
    assert "authorized / issued / unallocated" in block
    # expanded catalog (Tier-2 recurring gates) must be templated
    assert "Convert at cap" in block and "Repay principal" in block, "note maturity-default labels missing"
    assert "Use existing review" in block and "Start fresh" in block, "existing-review routing labels missing"
    assert "Confirmed" in block, "cap-base confirmation label missing"
    # The note-denominator label MUST NOT carry a '(Recommended)' suffix — that suffix is what made the
    # note cassette's choose-anchor fragile (the leading 'Fully-diluted' is the stable anchor).
    assert "Fully-diluted pre-financing" in block, "canonical denominator label missing"
    denom_idx = block.find("Fully-diluted pre-financing")
    assert "(Recommended)" not in block[denom_idx : denom_idx + 120], (
        "the denominator label must not append '(Recommended)' — it breaks the cassette anchor"
    )
