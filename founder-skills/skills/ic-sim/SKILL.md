---
name: ic-sim
disable-model-invocation: true
description: "Simulates a realistic VC Investment Committee discussion with three partner archetypes debating a startup's merits, concerns, and deal terms, scored across 28 dimensions. Use when user asks to \"simulate an IC\", \"how would VCs discuss this\", \"IC meeting simulation\", \"investment committee practice\", \"prepare for IC\", \"VC partner discussion\", \"what will investors debate\", \"how would a fund evaluate this\", \"IC prep\", or provides startup materials for investment committee simulation. Do NOT use for pitch deck feedback (use deck-review), market sizing, or financial model analysis."
compatibility: Requires Python 3.10+ and uv for script execution.
metadata:
  author: lool-ventures
  version: "0.2.0"
imports:
  - "market-sizing:sizing.json (recommended — fund alignment and market validation)"
  - "deck-review:checklist.json (recommended — deck quality assessment)"
exports:
  - "report.json -> fundraise-readiness, dd-readiness"
---

# IC Simulation Skill

Help startup founders prepare for the conversation that happens behind closed doors — the one where VC partners debate whether to invest. Produce a realistic IC simulation with three distinct partner perspectives, scored across 28 dimensions, with specific coaching on what to prepare.

The tone is founder-first: a coaching tool for preparation, not a judgment on the startup. Every concern maps to an action — something the founder can prepare, address proactively, or have ready for Q&A.

## Why This Matters

Founders spend months preparing their pitch but rarely get to hear how investors discuss their startup internally. The IC discussion surfaces objections, concerns, and conviction points that founders never see — until it's too late. This simulation lets founders hear that conversation early and prepare accordingly.

## Input Formats

Accept any combination: pitch deck (PDF, PPTX, markdown), financial model, data room contents, text descriptions, prior market-sizing or deck-review artifacts, or just a verbal description of the business.

## Available Scripts

All scripts are at `${CLAUDE_PLUGIN_ROOT}/skills/ic-sim/scripts/`:

- **`fund_profile.py`** — Validates fund profile structure (archetypes, check size, thesis, portfolio)
- **`detect_conflicts.py`** — Validates agent-produced conflict assessments and computes summary stats
- **`score_dimensions.py`** — Scores 28 dimensions across 7 categories with conviction-based scoring
- **`compose_report.py`** — Assembles all artifacts into a final report with cross-artifact validation; supports `--strict` to exit 1 on high/medium warnings (after writing output)
- **`visualize.py`** — Generates a self-contained HTML file with SVG charts (gauge, radar, stacked bars, partner cards, conflict table). Outputs HTML (not JSON). `--pretty` accepted as no-op for compatibility

Run with: `python3 ${CLAUDE_PLUGIN_ROOT}/skills/ic-sim/scripts/<script>.py --pretty [args]`

**Path resolution:** `${CLAUDE_PLUGIN_ROOT}` is persisted by the SessionStart hook. At the start of a simulation, resolve it once:

```bash
SCRIPTS="$CLAUDE_PLUGIN_ROOT/skills/ic-sim/scripts"
REFS="$CLAUDE_PLUGIN_ROOT/skills/ic-sim/references"
# ARTIFACTS_ROOT must be in the user's persistent workspace, NOT the session root.
# In Cowork, $(pwd) is the ephemeral session scratch dir. Detect the mounted workspace:
if ls "$(pwd)"/mnt/*/ >/dev/null 2>&1; then
  ARTIFACTS_ROOT="$(ls -d "$(pwd)"/mnt/*/ | head -1)artifacts"
else
  ARTIFACTS_ROOT="$(pwd)/artifacts"
fi
echo "ARTIFACTS_ROOT=$ARTIFACTS_ROOT"
echo "$SCRIPTS"
```

If empty, fall back: run `Glob` with pattern `**/founder-skills/skills/ic-sim/scripts/score_dimensions.py`, strip to get `SCRIPTS`. Replace `/scripts` with `/references` to get `REFS`.

## Available References

These are at `${CLAUDE_PLUGIN_ROOT}/skills/ic-sim/references/`. Read each when first needed — do NOT load all upfront.

- **`partner-archetypes.md`** — Read before Step 3. Three canonical archetypes with focus areas, debate styles, red flags
- **`evaluation-criteria.md`** — Read before Step 5. 28 dimensions across 7 categories with stage-calibrated thresholds
- **`ic-dynamics.md`** — Read before Step 5d. How real VC ICs work: formats, decisions, what kills deals
- **`artifact-schemas.md`** — Consult as needed when depositing agent-written artifacts

## Artifact Pipeline

Every simulation deposits structured JSON artifacts into a working directory. The final step assembles all artifacts into a report and validates consistency. This is not optional.

| Step | Artifact | Producer |
|------|----------|----------|
| 1 | `startup_profile.json` | Sub-agent (Task) extracts from files; agent (heredoc) if text-only or fallback |
| 2 | `prior_artifacts.json` | Sub-agent (Task) imports; agent (heredoc) if text-only or fallback |
| 3 | `fund_profile.json` | Agent (heredoc) then `fund_profile.py -o` validates |
| 4 | `conflict_check.json` | Agent assesses (heredoc) then `detect_conflicts.py -o` validates |
| 5a | `partner_assessment_visionary.json` | Sub-agent (Task, general-purpose) |
| 5b | `partner_assessment_operator.json` | Sub-agent (Task, general-purpose) |
| 5c | `partner_assessment_analyst.json` | Sub-agent (Task, general-purpose) |
| 5d | `discussion.json` | Main agent (composes from 5a-5c + debate) |
| 6 | `score_dimensions.json` | `score_dimensions.py -o` |
| 7 | Report | `compose_report.py` reads all |

**Rules:**
- Deposit each artifact before proceeding to the next step
- For agent-written artifacts, consult `references/artifact-schemas.md` for the JSON schema
- If a step is not applicable, deposit a stub: `{"skipped": true, "reason": "..."}`

## Workflow

### Mode Selection

Ask the user (or infer from context):

1. **Interactive mode** — Structured pauses between partner positions and debate sections. The founder can inject responses that influence subsequent sections.
2. **Auto-pilot mode** — Runs all sections without pausing. Faster, good for initial assessment.
3. **Fund-specific mode** — Use WebSearch to research a specific fund before the simulation. Can combine with either interactive or auto-pilot.

**Working directory:** Set `SIM_DIR` at the start. Artifacts persist in the workspace `artifacts/` directory across sessions.

```bash
SIM_DIR="$ARTIFACTS_ROOT/ic-sim-{company-slug}"
mkdir -p "$SIM_DIR"
test -d "$SIM_DIR" && echo "Directory ready: $SIM_DIR"
```

### Steps 1-2: Extract Startup Profile and Import Prior Artifacts -> `startup_profile.json`, `prior_artifacts.json`

When the user provides files (PDF, PPTX, data room), spawn a `general-purpose` Task sub-agent to read the materials, extract the startup profile, and import any prior market-sizing or deck-review artifacts. The sub-agent deposits both JSON artifacts to `$SIM_DIR` and returns a summary with any missing required fields.

**Do NOT use `isolation: "worktree"`** for sub-agents — worktrees create an isolated repo copy with a separate filesystem, so files written by the sub-agent won't appear in the main agent's `$SIM_DIR`. Launch sub-agents without isolation; parallel writes to different filenames in the same directory are safe.

If missing fields are flagged, ask the user and patch the artifact.

When the user provides only text (no files), extract directly from the conversation without a sub-agent.

**Graceful degradation:** If Task tool is unavailable, extract directly (current behavior).

### Step 3: Build Fund Profile -> `fund_profile.json`

**REQUIRED — read `$REFS/partner-archetypes.md` now.** The three canonical archetypes define focus areas, debate styles, and red flags that shape the entire simulation. Do not generate the fund profile without reading this file.

**Generic mode:** Build a standard early-stage fund profile with the three canonical archetypes.

**Fund-specific mode:** Use WebSearch to research:
- Fund thesis and focus areas
- Recent investments and portfolio companies
- Partner backgrounds and public writing
- Check size range and stage preference
- Map real partners to archetype roles

**Validation constraints:** `check_size_range` must be a dict (not a string), `stage_focus` must be a non-empty array, and each source must have `url` or `title`.

Validate with `fund_profile.py`:

```bash
cat <<'FUND_EOF' | python3 "$SCRIPTS/fund_profile.py" --pretty -o "$SIM_DIR/fund_profile.json"
{...fund profile JSON...}
FUND_EOF
```

**Accepted warnings:** Add `accepted_warnings` array to `fund_profile.json` to acknowledge expected warnings (same pattern as market-sizing `methodology.json`). Each entry needs `code`, `match` (case-insensitive), and `reason`. Compose downgrades matching warnings to `"acknowledged"`.

### Step 4: Check Portfolio Conflicts -> `conflict_check.json`

Review the fund's portfolio (from `fund_profile.json`) against the startup. Assess each portfolio company for:
- **Direct conflict** — Same market, same customer, direct competition
- **Adjacent conflict** — Related market, potential customer overlap
- **Customer overlap** — Same target customer segment, different product

Use consistent company names between portfolio and conflicts. The compose script normalizes names (strips legal suffixes like "Inc.", "LLC") but exact names are preferred. Duplicates are auto-deduplicated by (company, type) pair — the same company can appear with different conflict types.

Produce your assessment, then validate with `detect_conflicts.py`:

```bash
cat <<'CONFLICT_EOF' | python3 "$SCRIPTS/detect_conflicts.py" --pretty -o "$SIM_DIR/conflict_check.json"
{
  "portfolio_size": 15,
  "conflicts": [
    {"company": "FinLedger", "type": "adjacent", "severity": "manageable", "rationale": "..."}
  ]
}
CONFLICT_EOF
```

If validation fails, the output has `summary: null` — fix the input and re-run.

### Step 5: Partner Assessments and Discussion

**Step 5a-5c: Independent Partner Assessments (Parallel Sub-Agents)**

**REQUIRED — read `$REFS/evaluation-criteria.md` now.** It defines 28 dimensions, stage calibration, SaaS metric formulas, and scoring criteria. Do not generate partner assessments without reading this file.

Spawn 3 `general-purpose` Task sub-agents **in a single message** (parallel execution, **no `isolation: "worktree"`** — see Step 1-2 note). Each sub-agent receives:
- Its archetype persona and focus areas (from `references/partner-archetypes.md`)
- The startup_profile, fund_profile, conflict_check, and prior_artifacts
- The evaluation criteria relevant to its focus categories (from `references/evaluation-criteria.md`)

Each sub-agent independently produces a `partner_assessment_{role}.json` with: partner, verdict, rationale, conviction_points, key_concerns, questions_for_founders, diligence_requirements.

Write each assessment to the artifact directory.

**Graceful degradation:** If Task tool is unavailable, fall back to sequential generation with explicit persona switching. Generate each assessment one at a time, maintaining strict persona separation. Set `assessment_mode: "sequential"` and `"assessment_mode_intentional": true` in discussion.json (the latter suppresses the SEQUENTIAL_FALLBACK compose warning).

**Step 5d: Orchestrate Discussion -> `discussion.json`**

**REQUIRED — read `$REFS/ic-dynamics.md` now.** It defines realistic IC debate structure, consensus dynamics, and what kills deals. Do not generate the discussion without reading this file.

Read all 3 partner assessments. Generate the debate:
1. Have each partner present their key position
2. Partners respond to each other's concerns and conviction points
3. Build toward consensus (or document the split)
4. Record: assessment_mode, partner_verdicts, debate_sections, consensus_verdict, key_concerns, diligence_requirements

In **interactive mode**, pause between partner positions and after the debate for founder input.

**Verdict reconciliation:** After writing the discussion, verify that each partner's `verdict` in `partner_verdicts` reflects their **final position** after the debate, not their opening position. If a partner changed their mind during the discussion (e.g., moved from `more_diligence` to `pass`), update the verdict accordingly. The compose report flags `UNANIMOUS_VERDICT_MISMATCH` when all partners unanimously contradict the consensus, indicating stale data.

**Discussion-to-Score Reconciliation:** Before scoring, re-read `discussion.json` conclusions — especially `consensus_verdict`, `key_concerns`, and any dimension debated as a dealbreaker. If the discussion identified a dimension as a fatal flaw, ensure the corresponding score reflects that severity (e.g., `dealbreaker`, not `concern`). Conversely, if a dimension drew strong conviction from all partners, score accordingly. The compose report flags `CONSENSUS_SCORE_MISMATCH` when the discussion consensus verdict and the computed score verdict diverge, so aligning them upfront avoids a preventable warning.

### Step 6: Score Dimensions -> `score_dimensions.json`

Evaluate all 28 dimensions from `references/evaluation-criteria.md`. Set each status based on the evidence from the simulation:

```bash
cat <<'SCORE_EOF' | python3 "$SCRIPTS/score_dimensions.py" --pretty -o "$SIM_DIR/score_dimensions.json"
{
  "items": [
    {"id": "team_founder_market_fit", "category": "Team", "status": "strong_conviction", "evidence": "...", "notes": "..."},
    ...all 28 items...
  ]
}
SCORE_EOF
```

### Step 7: Compose and Validate Report

```bash
python3 "$SCRIPTS/compose_report.py" --dir "$SIM_DIR" --pretty -o "$SIM_DIR/report.json"
```

Read the output file and check `validation.warnings`:
- **High-severity:** Fix the underlying artifact and re-run. Do NOT present with high-severity warnings.
- **Medium-severity:** Include in your presentation.
- **Acknowledged:** Accepted via `fund_profile.json` `accepted_warnings` — appear but don't block.
- **Low/info:** Note for completeness.

Use `--strict` to enforce a clean report — writes output first, then exits 1 if high/medium warnings remain.

**Primary deliverable:** Read `report_markdown` from the output JSON and display it to the user in full. This is the main output of the simulation — the user must see the complete written report before anything else. After the structured report, add coaching commentary:
- What are the 2-3 strongest aspects of the startup's IC readiness?
- What's the single most important thing to prepare before a real IC?
- Which partner archetype would be hardest to convince, and why?
- Specific preparation recommendations for each concern raised

### Step 8 (Optional): Generate Visual Report

Supplement (not replace) the written report with a self-contained HTML report with charts:

```bash
python3 "$SCRIPTS/visualize.py" --dir "$SIM_DIR" -o "$SIM_DIR/report.html"
```

Opens in any browser. Contains SVG charts for conviction gauge, category radar, category breakdown, partner verdict cards, and conflict summary. No external dependencies or JavaScript.

### Step 9: Deliver Artifacts

Copy the final deliverables to the workspace root for easy access:

- Extract `report_markdown` from `report.json` and save as `{Company}_IC_Simulation.md`
- `{Company}_IC_Simulation.html` — visual HTML report (if generated)
- `{Company}_IC_Simulation.json` — full structured output with validation metadata (optional, for programmatic use)

## Scoring

- 28 dimensions, each: `strong_conviction` / `moderate_conviction` / `concern` / `dealbreaker` / `not_applicable`
- Conviction score: `(strong*1.0 + moderate*0.5) / applicable * 100`
- Verdicts: `invest` (>=75%), `more_diligence` (>=50%), `pass` (<50%), `hard_pass` (any dealbreaker)
- One dealbreaker forces `hard_pass` regardless of score

## Cross-Agent Integration

This skill can import artifacts from prior market-sizing and deck-review analyses:
- **Market sizing:** TAM/SAM/SOM figures, checklist status, sensitivity results
- **Deck review:** Overall score, failed criteria, stage detection

Imported artifacts are recorded with dates. Imports older than 7 days are flagged as `STALE_IMPORT`.

## Model Considerations

This skill works best with Opus-class models due to the complexity of maintaining 3 distinct partner personas, grounding positions in evidence, and making nuanced judgment calls. Sonnet will produce adequate results but with less distinct partner voices and shallower evidence grounding.

## Troubleshooting

### Script not found
If the path resolution block cannot locate scripts:
1. Verify `${CLAUDE_PLUGIN_ROOT}` is set (SessionStart hook should set it)
2. Fall back to Glob: `**/founder-skills/skills/ic-sim/scripts/<script>.py`
3. If running in Cowork, check that the plugin cache has been populated

### Invalid JSON from script
If a script exits non-zero or outputs invalid JSON:
1. Check stderr for the specific error message
2. Ensure the JSON piped via heredoc is valid (use `python3 -m json.tool` to verify)
3. Verify required fields are present in the input payload

### Empty or missing artifacts
If compose_report.py reports missing artifacts:
1. Verify the artifact directory exists: `ls "$SIM_DIR/"`
2. Check that earlier pipeline steps completed without error
3. Re-run the failed step individually to isolate the issue

## Performance Notes
- Take your time to do this thoroughly
- Quality is more important than speed
- Do not skip validation steps or checklist items

## Progress Updates

Keep the founder informed with brief, plain-language updates at each step. Never mention file names, scripts, or JSON — describe what you're doing in terms they care about.

| Step | Say to the founder |
|------|--------------------|
| 1–2 | "Building your startup profile and importing any prior analysis..." |
| 3 | "Setting up the investment committee with fund profile and thesis..." |
| 4 | "Checking for portfolio conflicts..." |
| 5a–c | "Three IC partners are independently evaluating your company..." |
| 5d | "The partners are now discussing and debating their views..." |
| 6 | "Scoring the final assessment across 28 dimensions..." |
| 7 | "Assembling the full report and cross-checking for consistency..." |
| 8 | "Generating a visual summary with charts..." |

After each analytical step (4–6) completes, share a one-sentence finding before moving on (e.g., "No portfolio conflicts found — moving to partner assessments."). Don't wait until the end to surface findings.

## Additional Resources

### Reference Files

For detailed criteria definitions and IC dynamics, consult:
- **`references/ic-dynamics.md`** — How real ICs work
- **`references/partner-archetypes.md`** — Partner personas and debate styles
- **`references/evaluation-criteria.md`** — All 28 dimensions with thresholds
- **`references/artifact-schemas.md`** — JSON schemas for artifacts
