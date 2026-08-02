"""Drift guard for the shared skill-execution-model reference doc.

`founder-skills/references/skill-execution-model.md` used to tell readers to
stage ad-hoc files at `$REVIEW_DIR/.staging/` — advice that contradicts every
skill's actual SKILL.md Step 0, which stages scratch in a `/tmp` `$STAGING_DIR`
mktemp'd dir instead (see `test_skill_orchestration.py`'s
`test_skill_md_stages_scratch_outside_outputs`, which enforces the correct
pattern across every SKILL.md but does NOT read this reference file — no test
in the repo scanned the reference file at all before this one).

This test closes that gap: it asserts the reference file itself never
regresses back to recommending staging under the promoted `outputs/` work dir
(`$REVIEW_DIR` / `$ANALYSIS_DIR` / `$SIM_DIR`). Mirrors the
`_STAGING_UNDER_OUTPUTS` regex from `test_skill_orchestration.py`, pointed at
the reference file instead of the SKILL.md glob.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
REFERENCE_FILE = REPO_ROOT / "founder-skills" / "references" / "skill-execution-model.md"

# Mirrors test_skill_orchestration.py's _OUTPUTS_DIR_VARS / _STAGING_UNDER_OUTPUTS.
_OUTPUTS_DIR_VARS = r"(?:ANALYSIS_DIR|SIM_DIR|REVIEW_DIR)"
_STAGING_UNDER_OUTPUTS = re.compile(r"\$\{?" + _OUTPUTS_DIR_VARS + r"\}?/\.staging")


def test_reference_does_not_recommend_staging_under_outputs() -> None:
    """The reference must not recommend staging scratch under the promoted
    outputs/ work dir (`$REVIEW_DIR` / `$ANALYSIS_DIR` / `$SIM_DIR`).

    Correct advice: stage under a `/tmp` `$STAGING_DIR` mktemp'd dir.
    """
    text = REFERENCE_FILE.read_text(encoding="utf-8")
    hits: list[tuple[int, str]] = []
    for m in _STAGING_UNDER_OUTPUTS.finditer(text):
        ln = text.count("\n", 0, m.start()) + 1
        hits.append((ln, text.splitlines()[ln - 1].strip()[:90]))
    assert not hits, (
        f"{REFERENCE_FILE.relative_to(REPO_ROOT)}: recommends staging under the promoted "
        f"outputs/ work dir. Correct pattern is a /tmp $STAGING_DIR mktemp'd dir:\n"
        + "\n".join(f"  line {ln}: {txt}" for ln, txt in hits)
    )


def test_reference_clarifies_dispatch_tool_naming() -> None:
    """The SKILL.mds say "call the `Task` tool", but the dispatch tool's name is
    runtime-dependent (Claude Code/Cowork: `Task`; some newer builds: `Agent`).
    The shared reference must clarify this once — mirroring how it already notes
    the shell tool is `Bash` vs `mcp__workspace__bash` — and anchor the reader on
    the `subagent_type` pin (what actually binds) rather than the tool label."""
    text = REFERENCE_FILE.read_text(encoding="utf-8")
    assert "Agent" in text, "reference must mention the `Agent` alias for the dispatch tool"
    # The clarification must tie Task and Agent together as the same dispatch tool.
    assert re.search(r"`Task`[\s\S]{0,120}`Agent`|`Agent`[\s\S]{0,120}`Task`", text), (
        "reference must clarify that Task and Agent name the same sub-agent dispatch tool"
    )
    assert "subagent_type" in text, "reference must anchor on the subagent_type pin as the real binding"
