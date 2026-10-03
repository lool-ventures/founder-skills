"""Drift-contract tests for the financial-model-review skill.

These tests grep SKILL.md and the agent body against the producer scripts'
actual source so the dispatch prompts can never silently diverge from what
the scripts accept. Born from the 2026-06-10 pre-ship review, where the
checklist ID enumeration, the CHECKLIST return shape, and the base_hash
protocol had all drifted (see docs/internal/2026-06-10-financial-model-review-pre-ship-review.md).
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
FMR_DIR = REPO_ROOT / "founder-skills" / "skills" / "financial-model-review"
SKILL_MD = FMR_DIR / "SKILL.md"
AGENT_MD = REPO_ROOT / "founder-skills" / "agents" / "financial-model-review.md"
DISPATCH_CONTRACTS = REPO_ROOT / "founder-skills" / "tests" / "fixtures" / "dispatch_contracts.json"

_RANGE_TOKEN = re.compile(r"\b([A-Z]+)_(\d+)\.\.(\d+)\b")


def _load_checklist_module() -> types.ModuleType:
    path = FMR_DIR / "scripts" / "checklist.py"
    spec = importlib.util.spec_from_file_location("fmr_checklist_contract", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["fmr_checklist_contract"] = mod
    spec.loader.exec_module(mod)
    return mod


def _load_compose_module() -> types.ModuleType:
    path = FMR_DIR / "scripts" / "compose_report.py"
    spec = importlib.util.spec_from_file_location("fmr_compose_contract", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["fmr_compose_contract"] = mod
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
    for doc in (SKILL_MD, AGENT_MD, DISPATCH_CONTRACTS):
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


def test_skill_md_produces_every_gate_required_artifact() -> None:
    """verify_review.py's required-artifact set (including the conditional
    commentary.json) must each appear in SKILL.md — a gate requirement with
    no producing step means every review fails the final gate (regression)."""
    verify_src = (FMR_DIR / "scripts" / "verify_review.py").read_text(encoding="utf-8")
    skill_text = SKILL_MD.read_text(encoding="utf-8")
    required = set(re.findall(r'"([a-z_]+\.json)"', verify_src.split("_OPTIONAL")[0]))
    required.add("commentary.json")  # the conditional gate-2 requirement
    missing = sorted(n for n in required if n not in skill_text)
    assert not missing, f"verify_review requires artifacts SKILL.md never produces: {missing}"


def test_overwrite_in_place_no_outputs_delete() -> None:
    """Cowork-parity: fmr must NOT bash-`rm` prior artifacts under `$REVIEW_DIR`
    (the promoted outputs/ tree) and must NOT stage scratch there. It
    overwrites-in-place (producers rewrite via `-o`; compose's STALE_ARTIFACT
    run_id check backstops a skipped-step leftover) and stages in a `/tmp`
    `$STAGING_DIR`. Replaces the old `rm -f` cleanup-coverage test — deleting
    under outputs/ is the regression now, not an uncovered artifact.

    (The Step-3.6 review page runs `review_inputs.py --static`; the `--workspace &`
    server branch runs only on request in a local terminal — neither is an rm.)
    """
    text = SKILL_MD.read_text(encoding="utf-8")
    assert not re.search(r"\brm\b[^\n`]*\$\{?REVIEW_DIR\b", text), (
        f"{SKILL_MD.name}: bash `rm` of $REVIEW_DIR (promoted outputs/) — overwrite-in-place instead"
    )
    assert not re.search(r"\$\{?REVIEW_DIR\}?/\.staging", text), (
        f"{SKILL_MD.name}: stages scratch under $REVIEW_DIR — use a /tmp $STAGING_DIR"
    )
    assert re.search(r'STAGING_DIR="\$\(mktemp -d', text), (
        f"{SKILL_MD.name}: expected a `$STAGING_DIR` mktemp'd under /tmp for sub-agent scratch"
    )


def test_model_derived_company_name_routes_through_staging() -> None:
    """Slug-ordering deadlock fix: when the company name comes from the model
    file, Step-1 Exit-1 must route through a /tmp `$STAGING_DIR` — extract
    FIRST, derive the name, init context + create `$REVIEW_DIR`, then `cp` the
    staged file in — never improvise a provisional dir/temp under the
    outputs mount (append-only by our rule) and later rm/mv it (the observed delete trigger).
    Without a sanctioned pre-slug extraction target the agent deadlocks and
    improvises, producing an outputs-mount delete."""
    text = SKILL_MD.read_text(encoding="utf-8")
    start = text.find("**Exit 1 (not found):**")
    assert start != -1, f"{SKILL_MD.name} has no Exit 1 branch"
    end = text.find("**Exit 2", start)
    assert end != -1, f"{SKILL_MD.name} Exit 1 branch has no Exit 2 terminator"
    section = text[start:end]

    # A model-file-name branch that stages the extraction to /tmp first.
    assert "$STAGING_DIR" in section, (
        f"{SKILL_MD.name} Exit 1 has no $STAGING_DIR staging branch for a model-file-derived company name"
    )
    ex = section.find("extract_model.py")
    init = section.find("founder_context.py")
    assert ex != -1, f"{SKILL_MD.name} Exit 1 staging branch does not run extract_model.py"
    assert init != -1, f"{SKILL_MD.name} Exit 1 lost its founder_context.py init call"
    assert ex < init, (
        f"{SKILL_MD.name} Exit 1 must stage the extraction BEFORE founder_context.py "
        "init (the name-from-model-file deadlock fix)"
    )
    # Forbid the observed improvisation explicitly.
    assert "provisional" in section.lower(), (
        f"{SKILL_MD.name} Exit 1 must forbid provisional review dirs/temps under the outputs mount"
    )


def test_askuserquestion_prescribes_two_option_construction() -> None:
    """Constraint-without-construction: the Step-1 founder-question guidance
    says AskUserQuestion needs >=2 options but never prescribes WHAT the two
    options are, so the model can emit a single free-text prompt the LLM
    decider dead-ends on (observed AskUserQuestion error). The guidance must
    prescribe a concrete two-option construction — an affirmative option
    carrying the likely value AND a 'not stated -> proceed and flag to confirm'
    fallback — so every founder question is answerable."""
    text = SKILL_MD.read_text(encoding="utf-8")
    start = text.find("**Exit 0 (found")
    end = text.find("### Step 2")
    assert start != -1, f"{SKILL_MD.name} has no Exit 0 gate paragraph"
    assert end != -1, f"{SKILL_MD.name} Step-1 gate block has no Step 2 terminator"
    low = text[start:end].lower()
    assert "proceed and flag" in low, (
        f"{SKILL_MD.name} AskUserQuestion guidance omits the "
        "'not stated -> proceed and flag to confirm' fallback option"
    )
    assert "two options" in low or "two-option" in low or "second option" in low, (
        f"{SKILL_MD.name} AskUserQuestion guidance does not prescribe a concrete two-option construction"
    )


def _checklist_section(text: str, start: int) -> str:
    """The CHECKLIST template (to its closing fence) or the agent's CHECKLIST subtype (to the next
    heading). Bounded by structure, not a character window: additions to the prose used to push the
    pinned text past a fixed slice and fail on content that was still there."""
    if text[start:].startswith("CONTEXT: CHECKLIST"):
        end = text.index("\n```", start)
    else:
        nxt = re.search(r"\n#{2,4} ", text[start + 1 :])
        end = start + 1 + nxt.start() if nxt else len(text)
    return text[start:end]


def test_checklist_dispatch_caps_pass_evidence() -> None:
    """CHECKLIST pass items only need a short 'checked X against Y' note;
    fail/warn items keep full evidence with specific values (they drive the
    score and coaching). Both the dispatch template and the agent CHECKLIST
    subtype must carry the pass-brevity cap, so passing items don't bloat the
    return with evidence that is never a coaching input."""
    checks = {SKILL_MD: "CONTEXT: CHECKLIST", AGENT_MD: "#### CHECKLIST subtype"}
    for doc, anchor in checks.items():
        text = doc.read_text(encoding="utf-8")
        start = text.find(anchor)
        assert start != -1, f"{doc.name} has no {anchor!r} section"
        section = _checklist_section(text, start).lower()
        assert "brief" in section, f"{doc.name} CHECKLIST guidance does not cap pass-item evidence to a brief note"
        assert "fail" in section and "warn" in section, (
            f"{doc.name} CHECKLIST guidance must still require full fail/warn evidence"
        )


def test_no_stale_size_claim_for_model_data() -> None:
    """The raw extraction runs to hundreds of KB / megabytes on real models, so
    the old '40-60 KB' figure understated it 10-100x and framed model_data.json
    as a small file to read whole. No KB-denominated size claim may sit on a
    line describing the extraction output."""
    kb = re.compile(r"\d+\s*(?:[-–]\s*\d+\s*)?KB", re.IGNORECASE)
    for doc in (SKILL_MD, AGENT_MD):
        for i, line in enumerate(doc.read_text(encoding="utf-8").splitlines(), 1):
            if "model_data.json" not in line and "extract_model.py" not in line:
                continue
            assert not kb.search(line), (
                f"{doc.name}:{i} carries a stale KB size claim for the extraction output: {line.strip()}"
            )


def test_step2_invocation_keeps_pretty_flag() -> None:
    """Regression lock: the Step-2 extraction must stay pretty-printed so
    model_data.json is line-navigable downstream (INPUTS_REVIEW / the validation
    cross-reference). An edit dropping --pretty re-ships a single multi-MB line."""
    text = SKILL_MD.read_text(encoding="utf-8")
    assert re.search(r"extract_model\.py[^\n]*--pretty[^\n]*model_data\.json", text), (
        f"{SKILL_MD.name} Step-2 extraction dropped --pretty (model_data.json must stay line-navigable)"
    )


def _gate_section(text: str) -> str:
    start = text.find("### Verification Gate 1")
    assert start != -1, f"{SKILL_MD.name} has no Verification Gate 1 section"
    end = text.find("### Steps 8a", start)
    assert end != -1, f"{SKILL_MD.name} gate block has no Steps 8a terminator"
    return text[start:end]


def test_gate_sections_document_honest_degradation() -> None:
    """A passing gate that carries partial/insufficient-data warnings is the
    sanctioned honest-degradation route, not a failure to fix. The gate section
    must name the producer `insufficient_data` self-declaration and point at
    data-sufficiency.md — rather than implying every non-zero gate needs a
    value invented to clear it (the observed fabrication pressure)."""
    section = _gate_section(SKILL_MD.read_text(encoding="utf-8"))
    assert "insufficient_data" in section, (
        f"{SKILL_MD.name} gate section does not name the insufficient_data honest-degradation flag"
    )
    assert "data-sufficiency.md" in section, (
        f"{SKILL_MD.name} gate section does not point at data-sufficiency.md for unfixable gate errors"
    )


def test_gate_sections_forbid_script_spelunking() -> None:
    """Debugging a gate by reading the producer / verify_review source is the
    observed scavenger-hunt failure — the gate contract lives in the
    references, and the gate section must forbid reading script source."""
    section = _gate_section(SKILL_MD.read_text(encoding="utf-8")).lower()
    assert "script source" in section, (
        f"{SKILL_MD.name} gate section does not forbid reading script source to debug a gate"
    )


def test_data_sufficiency_documents_gate_contract() -> None:
    """data-sufficiency.md is the contract of record for gate errors/warnings:
    it must document accept-with-warning semantics for BOTH producers
    (unit_economics AND runway) so the SKILL.md pointer never dangles into a
    reference that omits the producer-generic behavior."""
    ds = (FMR_DIR / "references" / "data-sufficiency.md").read_text(encoding="utf-8")
    assert "Gate contract" in ds, (
        "data-sufficiency.md has no 'Gate contract' section documenting accept-with-warning semantics"
    )
    low = ds.lower()
    assert "unit_economics" in low and "runway" in low, (
        "data-sufficiency.md Gate contract must cover BOTH producers (unit_economics and runway)"
    )
    assert "warning" in low, "data-sufficiency.md does not document accept-with-warning gate semantics"


def test_progress_tracking_batches_at_phase_boundaries() -> None:
    """Task-tracker churn (~19-36 create+update calls) inflates runtime with no
    founder benefit — the step narration is the real progress channel. The
    guidance must steer to a batched tracker updated only at phase boundaries."""
    text = SKILL_MD.read_text(encoding="utf-8")
    start = text.find("Keep the founder informed")
    assert start != -1, f"{SKILL_MD.name} has no 'Keep the founder informed' guidance"
    # Bound on the end of the narration paragraph, not a fixed byte count. This is
    # the FOURTH test in this suite to fail on correct content because a fixed
    # window shrank as prose was added above the asserted line.
    para_end = text.find("\n\n", start)
    section = (text[start:para_end] if para_end != -1 else text[start:]).lower()
    assert "phase boundaries" in section, (
        f"{SKILL_MD.name} progress guidance does not batch task updates at phase boundaries"
    )
    assert "tracker" in section or "taskcreate" in section, (
        f"{SKILL_MD.name} progress guidance does not name the task tracker it is bounding"
    )


def test_context_b_prompt_writes_raw_markdown_not_escaped_json() -> None:
    """R2 coaching-transport fix (supersedes the old JSON-escape guardrail this
    test used to assert): a raw newline or unescaped quote inside a hand-
    authored commentary_markdown JSON string used to make the file fail JSON
    parsing and force a repair round-trip (observed JSON-repair churn, ~17-22%
    of runs). The fix moves escaping out of the LLM entirely: the agent body
    must instruct the sub-agent to write RAW markdown directly with its Write
    tool (no JSON envelope, no hand-escaping) — the JSON envelope is built
    deterministically by md_to_commentary.py's json.dumps on the main thread."""
    agent = AGENT_MD.read_text(encoding="utf-8")
    anchor = "#### 2. Write the commentary to OUTPUT_PATH, then return a receipt"
    start = agent.find(anchor)
    assert start != -1, f"{AGENT_MD.name} has no '{anchor}' section"
    section = agent[start : start + 1400]
    low = section.lower()
    assert "plain markdown" in low
    assert "do not escape anything" in low or "do not escape" in low
    # The old hand-escaping instruction must not survive anywhere in the file.
    assert "escaped as `\\n`" not in agent
    assert "single pass" not in low


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
        section = _checklist_section(text, start)
        assert '"metadata"' in section and '"run_id"' in section, (
            f"{doc.name} CHECKLIST return shape is missing metadata.run_id"
        )
        assert '"company"' in section, f"{doc.name} CHECKLIST return shape is missing the company block"


def test_vendored_chartjs_in_sync_with_competitive_positioning() -> None:
    """Both skills vendor the same Chart.js bundle — if one is upgraded
    without the other, behavior silently diverges across skills."""
    import hashlib

    fmr = FMR_DIR / "scripts" / "vendor" / "chart.min.js"
    cp = REPO_ROOT / "founder-skills" / "skills" / "competitive-positioning" / "scripts" / "vendor" / "chart.min.js"
    assert fmr.exists(), "FMR vendored chart.min.js missing"

    def _sha256(p: Path) -> str:
        return hashlib.sha256(p.read_bytes()).hexdigest()

    assert _sha256(fmr) == _sha256(cp), (
        "vendored chart.min.js diverged between financial-model-review and "
        "competitive-positioning — upgrade both together"
    )


def test_qualitative_stub_carries_run_id_so_context_b_does_not_deadlock() -> None:
    """The Context B run_id-parity grep checks all four producer artifacts.
    On the qualitative path, unit_economics.json / runway.json are skipped
    stubs — so the stub contract (schema-inputs.md + data-sufficiency.md) and
    the agent's grep step must agree that stubs carry metadata.run_id, otherwise
    every qualitative review deterministically returns BLOCKED."""
    schema_inputs = (FMR_DIR / "references" / "schema-inputs.md").read_text()
    data_sufficiency = (FMR_DIR / "references" / "data-sufficiency.md").read_text()
    agent = AGENT_MD.read_text()

    # The documented stub example must include a metadata.run_id block.
    assert '"skipped": true' in schema_inputs
    assert '"run_id"' in schema_inputs, "Stub Format must document metadata.run_id"

    # The deposit commands the agent runs on the qualitative path must include it.
    for stub_line in data_sufficiency.splitlines():
        if '"skipped": true' in stub_line:
            assert '"run_id"' in stub_line, f"Qualitative-path stub deposit command omits run_id: {stub_line.strip()}"

    # The agent's run_id grep step must acknowledge stubs are verified too,
    # rather than implying a missing match always blocks.
    assert "stub" in agent.lower() and "run_id" in agent, (
        "Agent run_id-parity step must mention that stubs also carry run_id"
    )


# ---------------------------------------------------------------------------
# Context B commentary payload keys (file hand-off shape)
# ---------------------------------------------------------------------------


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

    # SKILL.md Main-Thread Return names the headline keys as the COACHING sub-agent's, never the founder
    # message's: the hand-over is printed by fmr_closing_message.py, and a model restating those fields in
    # chat is how runway figures reached a founder recomputed. Bounded on the next heading, not a window.
    skill_text = SKILL_MD.read_text(encoding="utf-8")
    main_thread_anchor = "## Main-Thread Return"
    mt_start = skill_text.find(main_thread_anchor)
    assert mt_start != -1, f"{SKILL_MD.name} has no '## Main-Thread Return' section"
    mt_end = skill_text.find("\n## ", mt_start + len(main_thread_anchor))
    assert mt_end != -1, f"{SKILL_MD.name}: Main-Thread Return has no terminating heading"
    mt_section = skill_text[mt_start:mt_end]
    for key in {"runway_months", "overall_status", "high_severity_warnings"}:
        assert key in mt_section, f"{SKILL_MD.name} Main-Thread Return section does not mention '{key}'"
    assert "printed hand-over" in mt_section and "do not restate them" in mt_section, mt_section
    assert 'python3 "$SCRIPTS/fmr_closing_message.py"' in skill_text


# ---------------------------------------------------------------------------
# Currency determinism: preserve-native rule must be prescriptive, not optional
# ---------------------------------------------------------------------------


def test_currency_preservation_prescribed_in_guidance() -> None:
    """Live verification found the skill non-deterministic on currency: the same
    model was sometimes left in its native currency and sometimes force-converted
    to USD across runs. The fix is one unambiguous rule — preserve native
    currency, never convert — and it must appear in both the SKILL.md dispatch
    prompt and the agent's INPUTS_REVIEW subtype so the two can't silently
    diverge into a coin-flip again."""
    marker = "PRESERVE the model's native currency"

    skill_text = SKILL_MD.read_text(encoding="utf-8")
    agent_text = AGENT_MD.read_text(encoding="utf-8")

    assert marker in skill_text, (
        f"{SKILL_MD.name} does not prescribe native-currency preservation with the stable marker phrase"
    )
    assert marker in agent_text, (
        f"{AGENT_MD.name} INPUTS_REVIEW subtype does not prescribe native-currency preservation"
    )
    assert "never" in skill_text[skill_text.find(marker) : skill_text.find(marker) + 200].lower()

    pitfalls_text = (FMR_DIR / "references" / "extraction-pitfalls.md").read_text(encoding="utf-8")
    assert "currency" in pitfalls_text.lower(), (
        "extraction-pitfalls.md does not document the currency preserve-vs-convert pitfall"
    )

    schema_text = (FMR_DIR / "references" / "schema-inputs.md").read_text(encoding="utf-8")
    assert "`currency`" in schema_text, "schema-inputs.md does not document the top-level `currency` field"


# ---------------------------------------------------------------------------
# R2 coaching-transport fix: raw-markdown Context-B pipe
# ---------------------------------------------------------------------------


def test_skill_md_coaching_pipe_uses_format_markdown_adapter() -> None:
    """R2 coaching-transport fix: Step 8c's Context-B pipe must gate the raw
    .md hand-off with check_handoff.py --format=markdown and transform it
    through the shared md_to_commentary.py adapter before insert_coaching.py
    — never hand the sub-agent a JSON-escaping burden."""
    skill_md = SKILL_MD.read_text(encoding="utf-8")
    start = skill_md.index("### Step 8c: Post-Compose Coaching Commentary")
    end = skill_md.index("### Step 8d")
    step8c = skill_md[start:end]
    assert "--format=markdown" in step8c
    assert "md_to_commentary.py" in step8c
    assert "OUTPUT_PATH: <HANDOFF_AGENT>/coaching.md" in step8c
    assert "coaching_commentary_output.json" not in step8c


def test_skill_md_coaching_exit7_repair_dispatch() -> None:
    """The content-shape gate's new exit 7 (shape-invalid: receipt-shaped or
    marker-bearing hand-off) must branch to a repair-dispatch, mirroring the
    other typed exits."""
    skill_md = SKILL_MD.read_text(encoding="utf-8")
    start = skill_md.index("### Step 8c: Post-Compose Coaching Commentary")
    end = skill_md.index("### Step 8d")
    step8c = skill_md[start:end]
    assert "Exit 7" in step8c
    assert "repair-dispatch" in step8c.lower()
    idx = step8c.index("Exit 7")
    window = step8c[idx : idx + 300].lower()
    assert "coaching commentary" in window or "coaching markdown" in window


def test_agent_coaching_writes_raw_markdown_no_json_escaping() -> None:
    """R2 coaching-transport fix: agents/financial-model-review.md's Context B
    section must instruct the sub-agent to write RAW markdown (no JSON
    envelope, no hand-escaping) — the escaping moves into
    md_to_commentary.py's json.dumps, which cannot emit malformed JSON."""
    agent_body = AGENT_MD.read_text(encoding="utf-8")
    idx = agent_body.index("### Context B")
    # Bound on the next same-level heading, not a character count. The 4,000-char window this
    # replaced failed on content that was still present the moment the key list above it grew --
    # the exact failure mode CLAUDE.md warns about, reproduced here.
    end = agent_body.find("\n## ", idx + 1)
    section = agent_body[idx : end if end != -1 else len(agent_body)]
    assert "plain markdown" in section.lower()
    assert "do not escape anything" in section.lower() or "do not escape" in section.lower()
    assert "escaped as `\\n`" not in agent_body
    assert 'escaped as `\\"`' not in agent_body
    assert "no pretty-print" not in agent_body.lower()


# ---------------------------------------------------------------------------
# Context B: the coaching payload's keys must be documented on BOTH surfaces.
#
# Every sibling skill has this test; financial-model-review did not, which is how
# `score_coverage` could have been emitted into the payload and consumed by nobody.
# Context B is a CLOSED key list -- the agent body tells the coach the payload
# "contains these keys", so a key absent from that list is a key the coach is never
# told to read, and the JSON carrying it is dead weight.
#
# Keys are asserted TOP-LEVEL and by name. Nesting a new field inside `summary` would
# pass this test forever (`summary` is already required) while the sub-name could be
# deleted from the agent body at any time -- a pin that cannot fail is the thing this
# guards against, not a smaller version of it.
# ---------------------------------------------------------------------------


def test_post_compose_coaching_dispatch_includes_coaching_payload_keys() -> None:
    """SKILL.md's dispatch step and the agent body must both name every consumed key."""
    consumed_keys = {
        "summary",
        "score_coverage",
        "failed_items",
        "warned_items",
        "high_severity_warnings",
        "company_name",
    }

    skill_text = SKILL_MD.read_text(encoding="utf-8")
    anchor = "POST_COMPOSE_COACHING"
    start = skill_text.find("### Step 8c")
    assert start != -1, f"{SKILL_MD.name} has no '### Step 8c' section"
    assert anchor in skill_text[start:], f"{SKILL_MD.name} Step 8c does not name {anchor}"
    # Bound on the next step heading rather than a character count: the dispatch grows,
    # and a fixed window quietly stops covering its own tail.
    step_end = skill_text.find("\n### ", start + 1)
    section = skill_text[start : step_end if step_end != -1 else len(skill_text)]

    for key in consumed_keys:
        assert key in section, (
            f"{SKILL_MD.name} Step 8c dispatch does not name coaching_payload key '{key}' — "
            "a key the sub-agent is not told to read is a key it will not use"
        )

    agent_text = AGENT_MD.read_text(encoding="utf-8")
    agent_start = agent_text.find("Context B")
    assert agent_start != -1, f"{AGENT_MD.name} has no Context B section"
    agent_section = agent_text[agent_start:]
    for key in consumed_keys:
        assert key in agent_section, f"{AGENT_MD.name} Context B key list is missing '{key}'"


def test_score_coverage_is_emitted_top_level_and_flags_a_partial_score() -> None:
    """`score_coverage` must be a TOP-LEVEL payload key, and must go false when criteria drop.

    The defect: an unmatched profile field silently shrinks the score's denominator, so
    `overall_status` reads "strong" over a review that never assessed four criteria. The
    coach reasons from this payload, so the gap has to be IN it and at a name the agent
    body lists.
    """
    mod = _load_compose_module()
    summary = {
        "score_pct": 91.2,
        "overall_status": "strong",
        "total": 46,
        "self_gated_items": ["UNIT_10"],
        "unresolved_profile_exclusions": {"geography": ["CASH_29", "CASH_30"]},
    }
    cov = mod._score_coverage(summary)
    assert cov["complete"] is False
    assert cov["not_assessed_count"] == 3
    assert cov["unmatched_profile_fields"] == ["geography"]
    # No criterion ids: this reaches a founder through the commentary.
    assert "CASH_29" not in json.dumps(cov)
    assert "UNIT_10" not in json.dumps(cov)

    clean = mod._score_coverage({"score_pct": 80.0, "total": 46})
    assert clean["complete"] is True and clean["not_assessed_count"] == 0


def test_unit_economics_and_runway_run_before_the_checklist() -> None:
    """The checklist grades against the computed figures, so they must exist when it runs. It used to
    run first, which made METRIC_34's "read the burn multiple off the computed figure" impossible and
    left the grader estimating its own (measured: a computed 2.14x "acceptable" failed on an estimate)."""
    text = SKILL_MD.read_text(encoding="utf-8")
    ue_cmd = text.index('python3 "$SCRIPTS/unit_economics.py" --pretty --run-id')
    rw_cmd = text.index('python3 "$SCRIPTS/runway.py" --pretty --run-id')
    dispatch = text.index("CONTEXT: CHECKLIST")
    assert ue_cmd < dispatch and rw_cmd < dispatch
    assert text.index("### Step 4: Unit Economics and Runway") < text.index("### Step 5: CHECKLIST Dispatch")
    table = text[text.index("## Artifact Pipeline") : text.index("**Rules:**")]
    assert table.index("`unit_economics.json`") < table.index("`checklist.json`")


@pytest.mark.parametrize("anchor_doc", ["skill", "agent"])
def test_the_grader_reads_the_computed_figures_and_the_rules_for_them(anchor_doc: str) -> None:
    doc, anchor = (SKILL_MD, "CONTEXT: CHECKLIST") if anchor_doc == "skill" else (AGENT_MD, "#### CHECKLIST subtype")
    text = doc.read_text(encoding="utf-8")
    section = re.sub(r"\s+", " ", _checklist_section(text, text.index(anchor)))
    for phrase in (
        "read unit_economics.json and runway.json",
        "do not compute your own",
        "today's-burn runway (static_runway_months)",
        "graded on that reference rating",
        "give that criterion `warn` and say why",
        "never not_applicable",
        "not_rated means the inputs do not allow the figure",
        "never that the model itself shows, highlights, summarises or explains it",
        "never copy our evidence text, our rating words, or a filename",
    ):
        assert phrase in section, (doc.name, phrase)


def test_metric_34_says_what_a_contextual_burn_multiple_gets() -> None:
    text = (FMR_DIR / "references" / "checklist-criteria.md").read_text(encoding="utf-8")
    section = text.split("### `METRIC_34`", 1)[1].split("\n### ", 1)[0]
    assert "Rated contextual with no reference grade, it was left ungraded on purpose: warn and say why." in section
    assert "With a reference grade (a non-USD model), grade on the reference." in section


def _step_36_path_a() -> str:
    text = SKILL_MD.read_text(encoding="utf-8")
    start = text.index("**Path A — File extraction**")
    end = text.index("**Path B — Conversational**", start)
    return " ".join(text[start:end].split())


def test_review_page_defaults_to_static_mode() -> None:
    """The review page is built static unless the founder asks for live validation.

    The choice used to be keyed on the product name ("In Cowork … static", "In Claude Code … server").
    A session in a cloud container cannot tell it is not Claude Code, and its localhost URL is
    unreachable from the founder's browser, so the page never opened. Static works everywhere.
    """
    block = _step_36_path_a()
    assert "In Claude Code (local terminal), use **server mode**" not in block
    assert "In Cowork (VM, no display)" not in block
    assert "Always build the page in **static mode**" in block
    static_at = block.index('--static "$REVIEW_DIR/review.html"')
    server_at = block.index('--workspace "$REVIEW_DIR"')
    assert static_at < server_at, "the static command must come first; server mode is the exception"
    server_rule = block[block.rindex("server mode", 0, server_at) - 200 : server_at]
    assert "live validation" in server_rule and "asks" in server_rule, (
        "server mode must be gated on the founder asking for live validation, not on the product name"
    )


def test_review_page_is_sent_as_a_file_before_the_question() -> None:
    """At the STOP gate the founder gets review.html as a file, not its path, and only then the question."""
    block = _step_36_path_a()
    assert "Present the `review.html` path" not in block
    send = block.index("Send `review.html` to the founder as a file")
    ask = block.index("then ask via `AskUserQuestion`")
    assert send < ask
    assert "never a bare path" in block[send:ask]


def test_review_page_delivery_names_the_tool_and_the_terminal_case() -> None:
    """The page goes out through the host's file-delivery tool; a local terminal with none gets the
    absolute path, which is what Main-Thread Return calls the deliverable there."""
    block = _step_36_path_a()
    send = block.index("Send `review.html` to the founder as a file")
    ask = block.index("then ask via `AskUserQuestion`")
    window = block[send:ask]
    assert "with the host's file-delivery tool where one is offered" in window, window
    assert "in a local terminal that offers none, give its absolute path" in window, window


SERVER_MODE_RULE = (
    "Use **server mode** only when the founder asks for live validation while editing and the session "
    "is a local command-line terminal on the founder's own computer:"
)


def test_server_mode_rule_is_pinned_and_names_no_product() -> None:
    """Server mode is keyed on the founder's request and on where the shell runs, never on a product.

    A local desktop session can run its shell in a virtual machine, where the founder's browser cannot
    reach the page's local address; a command-line terminal on their own computer is the case that works.
    """
    block = _step_36_path_a()
    assert block.count(SERVER_MODE_RULE) == 1, "the server-mode sentence changed; re-read Step 3.6"
    server_at = block.index('--workspace "$REVIEW_DIR"')
    rule_at = block.rindex("server mode", 0, server_at)
    # The block is whitespace-collapsed: the rule runs from the previous sentence's end to its command.
    sentence = block[block.rindex(". ", 0, rule_at) + 2 : server_at]
    for product in ("Claude Code", "Cowork"):
        assert product not in sentence, f"the server-mode rule names {product!r}: {sentence!r}"
