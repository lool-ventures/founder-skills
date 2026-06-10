"""Drift-contract tests for the financial-model-review skill.

These tests grep SKILL.md and the agent body against the producer scripts'
actual source so the dispatch prompts can never silently diverge from what
the scripts accept. Born from the 2026-06-10 pre-ship review, where the
checklist ID enumeration, the CHECKLIST return shape, and the base_hash
protocol had all drifted (see docs/internal/2026-06-10-financial-model-review-pre-ship-review.md).
"""

from __future__ import annotations

import importlib.util
import re
import sys
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
FMR_DIR = REPO_ROOT / "founder-skills" / "skills" / "financial-model-review"
SKILL_MD = FMR_DIR / "SKILL.md"
AGENT_MD = REPO_ROOT / "founder-skills" / "agents" / "financial-model-review.md"

_RANGE_TOKEN = re.compile(r"\b([A-Z]+)_(\d+)\.\.(\d+)\b")


def _load_checklist_module() -> types.ModuleType:
    path = FMR_DIR / "scripts" / "checklist.py"
    spec = importlib.util.spec_from_file_location("fmr_checklist_contract", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["fmr_checklist_contract"] = mod
    spec.loader.exec_module(mod)
    return mod


def _expand_ranges(text: str) -> set[str]:
    """Expand 'STRUCT_01..09'-style tokens, preserving zero-padding width."""
    ids: set[str] = set()
    for prefix, start, end in _RANGE_TOKEN.findall(text):
        width = len(start)
        for i in range(int(start), int(end) + 1):
            ids.add(f"{prefix}_{i:0{width}d}")
    return ids


def test_checklist_id_enumeration_matches_script() -> None:
    """Every ID-range enumeration in SKILL.md and the agent body must expand
    to exactly checklist.py's VALID_IDS — no phantom prefixes, no gaps."""
    mod = _load_checklist_module()
    valid_ids = set(mod.VALID_IDS)
    for doc in (SKILL_MD, AGENT_MD):
        text = doc.read_text(encoding="utf-8")
        expanded = _expand_ranges(text)
        if not expanded:
            continue  # no enumerations in this file
        assert expanded == valid_ids, (
            f"{doc.name} checklist ID enumeration drifted from checklist.py:\n"
            f"  phantom: {sorted(expanded - valid_ids)}\n"
            f"  missing: {sorted(valid_ids - expanded)}"
        )


def test_no_phantom_scenario_prefix() -> None:
    """SCENARIO_* checklist IDs do not exist (the canonical set uses BRIDGE_36..38)."""
    for doc in (SKILL_MD, AGENT_MD):
        assert "SCENARIO_" not in doc.read_text(encoding="utf-8"), (
            f"{doc.name} references nonexistent SCENARIO_* checklist IDs"
        )


def test_no_base_hash_in_dispatch_prompts() -> None:
    """The sub-agent has no Bash and cannot compute the canonical sha256 —
    base_hash must never appear in a dispatch prompt (regression: the patch
    protocol was dead on arrival and silently bypassed coercion)."""
    for doc in (SKILL_MD, AGENT_MD):
        lines = doc.read_text(encoding="utf-8").splitlines()
        for i, line in enumerate(lines, 1):
            if "base_hash" not in line:
                continue
            # allowed only inside an explicit "do NOT include" instruction —
            # check a 2-line window since the negation may sit on the
            # preceding line after markdown wrapping
            window = (lines[i - 2] if i >= 2 else "") + " " + line
            if "NOT" not in window and "not " not in window:
                raise AssertionError(f"{doc.name}:{i} instructs use of base_hash: {line.strip()}")


def test_no_passthrough_dispatches() -> None:
    """unit_economics.py and runway.py consume inputs.json verbatim — routing
    that JSON through a sub-agent risks silent number corruption (regression:
    the UNIT_ECONOMICS / RUNWAY_SCENARIOS pass-through dispatches)."""
    for doc in (SKILL_MD, AGENT_MD):
        text = doc.read_text(encoding="utf-8")
        assert "UNIT_ECONOMICS" not in text and "RUNWAY_SCENARIOS" not in text, (
            f"{doc.name} still contains a pass-through dispatch"
        )


def test_no_shell_variable_capture_of_python_output() -> None:
    """Each Bash call runs in a fresh shell; VAR="$(python3 ...)" captures the
    payload invisibly and the variable dies immediately (regression:
    COACHING_PAYLOAD was captured and never printed, so the dispatch prompt
    couldn't be built). Step 0's same-block ls/date captures are legitimate
    (the block is prefixed onto every Bash call), so only python output
    captures are flagged."""
    text = SKILL_MD.read_text(encoding="utf-8")
    assert not re.search(r'\w+="\$\(\s*python3?', text), (
        "SKILL.md captures python output into a shell variable — print it instead"
    )


def test_checklist_dispatch_template_includes_run_id_and_company() -> None:
    """The CHECKLIST dispatch return shape must carry metadata.run_id (else
    Context B blocks on parity) and the company block (else auto-gating
    never engages)."""
    # Anchor on the actual template/section headers — a bare "CHECKLIST"
    # search hits the Context A overview (SKILL.md line 36) and the agent
    # frontmatter, whose windows miss the template or match the wrong payload.
    anchors = {SKILL_MD: "CONTEXT: CHECKLIST", AGENT_MD: "#### CHECKLIST subtype"}
    for doc, anchor in anchors.items():
        text = doc.read_text(encoding="utf-8")
        start = text.find(anchor)
        assert start != -1, f"{doc.name} has no {anchor!r} section"
        section = text[start : start + 4000]
        assert '"metadata"' in section and '"run_id"' in section, (
            f"{doc.name} CHECKLIST return shape is missing metadata.run_id"
        )
        assert '"company"' in section, f"{doc.name} CHECKLIST return shape is missing the company block"
