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

    (The Step-3.6 review page runs `review_inputs.py --static` in Cowork; the
    `--workspace &` server branch is Claude-Code-only — neither is an rm.)
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
    append-only outputs mount and later rm/mv it (the observed delete trigger).
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
        section = text[start : start + 2500].lower()
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
        section = text[start : start + 4000]
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
    """R2 coaching-transport fix: the Context B return payload defined in the
    agent body is now just the receipt (status + output_path) — the
    sub-agent WRITES raw markdown (not a commentary_markdown JSON key) to the
    OUTPUT_PATH hand-off file and returns the {status, output_path} receipt;
    the commentary_markdown envelope is built deterministically by the
    main-thread md_to_commentary.py adapter, not the sub-agent. The headline
    outcome fields SKILL.md's Main-Thread Return section presents are sourced
    from coaching_payload + the insert_coaching.py receipt, not the
    sub-agent."""
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
            f"(SKILL.md Step 8c stages it for insert_coaching.py)"
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
    for key in {"runway_months", "overall_status", "high_severity_warnings"}:
        assert key in mt_section, f"{SKILL_MD.name} Main-Thread Return section does not mention '{key}'"


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
    section = agent_body[idx : idx + 4000]
    assert "plain markdown" in section.lower()
    assert "do not escape anything" in section.lower() or "do not escape" in section.lower()
    assert "escaped as `\\n`" not in agent_body
    assert 'escaped as `\\"`' not in agent_body
    assert "no pretty-print" not in agent_body.lower()
