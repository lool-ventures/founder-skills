---
name: financial-model-review
disable-model-invocation: true
description: "Reviews startup financial models for investor readiness — validating unit economics, stress-testing runway scenarios, and benchmarking metrics against stage-appropriate targets. Use when user asks to \"review my financial model\", \"check my projections\", \"validate my unit economics\", \"stress-test my runway\", \"analyze my burn rate\", \"review my spreadsheet model\", or provides an Excel spreadsheet, CSV, or financial projections for evaluation. Supports Excel (.xlsx), CSV, Google Sheets exports, documents, and conversational input. Do NOT use for market sizing (use market-sizing), pitch deck feedback (use deck-review), or general spreadsheet editing, accounting, or tax preparation."
compatibility: Requires Python 3.10+ and uv for script execution. openpyxl required for Excel parsing.
metadata:
  author: lool-ventures
  version: "0.2.0"
imports:
  - "market-sizing:sizing.json (optional — validate revenue-to-SOM consistency)"
  - "deck-review:checklist.json (optional — cross-check model-to-deck number alignment)"
exports:
  - "report.json -> ic-sim, fundraise-readiness, dd-readiness"
  - "unit_economics.json -> metrics-benchmarker, ic-sim"
  - "runway.json -> fundraise-readiness"
---

# Financial Model Review Skill

Help startup founders understand how investors will evaluate their financial model — validating structure, unit economics, runway, and metrics against stage-appropriate standards. Produce a thorough review with actionable improvements.

The tone is founder-first: a rigorous but supportive coaching session. Confirm what's solid, flag what needs work, and explain *why* each issue matters to investors and *how* to fix it.

## Why This Matters

Financial models are the second artifact investors scrutinize most (after the deck). A model with structural errors, missing unit economics, or unrealistic runway projections signals either inexperience or wishful thinking. Founders deserve to know exactly which areas will hold up under investor scrutiny, so they can present with confidence.

## Input Formats

Accept any format the user provides: Excel (.xlsx), CSV, Google Sheets exports, financial documents, or conversational input. For Excel files, use `extract_model.py` to parse. For other formats, extract data manually into the `inputs.json` schema.

## Available Scripts

All scripts are at `${CLAUDE_PLUGIN_ROOT}/skills/financial-model-review/scripts/`:

- **`extract_model.py`** — Extracts structured data from Excel (.xlsx) and CSV files
- **`checklist.py`** — Scores 46 criteria across 7 categories (pass/fail/warn/not_applicable) with profile-based auto-gating
- **`unit_economics.py`** — Computes and benchmarks 11 unit economics metrics against stage-appropriate targets
- **`runway.py`** — Multi-scenario runway stress-test with decision points and default-alive analysis
- **`compose_report.py`** — Assembles report from artifacts with cross-artifact validation; supports `--strict` to exit 1 on high/medium warnings (after writing output)
- **`visualize.py`** — Generates a self-contained HTML file with SVG charts. Outputs HTML (not JSON). `--pretty` accepted as no-op for compatibility

Run with: `python3 ${CLAUDE_PLUGIN_ROOT}/skills/financial-model-review/scripts/<script>.py --pretty [args]`

**Path resolution:** `${CLAUDE_PLUGIN_ROOT}` is persisted by the SessionStart hook. Copy the path variables from Step 0 into each Bash invocation.

If empty, fall back: run `Glob` with pattern `**/founder-skills/skills/financial-model-review/scripts/checklist.py`, strip to get `SCRIPTS`. Replace `/scripts` with `/references` to get `REFS`.

## Available References

Read as needed during the review from `${CLAUDE_PLUGIN_ROOT}/skills/financial-model-review/references/`:

- **`checklist-criteria.md`** — All 46 checklist criteria with gate definitions
- **`artifact-schemas.md`** — JSON schemas for all artifacts

From `${CLAUDE_PLUGIN_ROOT}/references/` (shared):

- **`stage-expectations.md`** — Stage-appropriate targets
- **`benchmarks.md`** — Industry benchmark data
- **`israel-guidance.md`** — Israel-specific compliance
- **`revenue-model-types.md`** — Revenue model classifications
- **`common-mistakes.md`** — Common financial model errors

## Artifact Pipeline

Every review deposits structured JSON artifacts into a working directory. The final step assembles all artifacts into a report and validates consistency. This is not optional.

**Working directory:** Set `REVIEW_DIR` at the start. Artifacts persist in the workspace `artifacts/` directory across sessions.

```bash
REVIEW_DIR="$ARTIFACTS_ROOT/financial-model-review-{company-slug}"
mkdir -p "$REVIEW_DIR"
test -d "$REVIEW_DIR" && echo "Directory ready: $REVIEW_DIR"
```

If `REVIEW_DIR` already contains artifacts from a previous run, remove them before starting:

    rm -f "$REVIEW_DIR"/{inputs,checklist,unit_economics,runway,report,model_data}.json "$REVIEW_DIR/report.html"

| Step | Artifact | Producer |
|------|----------|----------|
| 1 | founder context | `founder_context.py` read/init |
| 2 | `model_data.json` | `extract_model.py` (Excel/CSV only) |
| 3 | `inputs.json` | Agent (heredoc) |
| 4 | `checklist.json` | `checklist.py` |
| 5 | `unit_economics.json` | `unit_economics.py` |
| 6 | `runway.json` | `runway.py` |
| 7 | Report | `compose_report.py` reads all |
| 8 | HTML | `visualize.py` |

**Rules:**
- Deposit each artifact before proceeding to the next step
- For agent-written artifacts (Step 3), consult `references/artifact-schemas.md` for the JSON schema
- If a step is not applicable, deposit a stub: `{"skipped": true, "reason": "..."}`

## Performance Notes
- Take your time to do this thoroughly
- Quality is more important than speed
- Do not skip validation steps or checklist items

## Progress Updates

Keep the founder informed with brief, plain-language updates at each step. Never mention file names, scripts, or JSON — describe what you're doing in terms they care about.

| Step | Say to the founder |
|------|--------------------|
| 1 | "Setting up your company profile..." |
| 2 | "Reading your financial model..." |
| 3 | "Organizing the numbers for analysis..." |
| 4 | "Evaluating your model against 46 investor-readiness criteria..." |
| 5 | "Benchmarking your unit economics against stage-appropriate targets..." |
| 6 | "Stress-testing your runway under base, slow-growth, and crisis scenarios..." |
| 7 | "Assembling the full review and cross-checking for consistency..." |
| 8 | "Generating a visual summary with charts..." |

After each analytical step (4–6) completes, share a one-sentence finding before moving on (e.g., "Your unit economics look strong on gross margin and payback — burn multiple needs attention."). Don't wait until the end to surface findings.

## Workflow

### Step 0: Path Setup

Define these variables at the start of every Bash invocation:

```bash
SCRIPTS="${CLAUDE_PLUGIN_ROOT}/skills/financial-model-review/scripts"
REFS="${CLAUDE_PLUGIN_ROOT}/skills/financial-model-review/references"
SHARED_SCRIPTS="${CLAUDE_PLUGIN_ROOT}/scripts"
SHARED_REFS="${CLAUDE_PLUGIN_ROOT}/references"
if ls "$(pwd)"/mnt/*/ >/dev/null 2>&1; then
  ARTIFACTS_ROOT="$(ls -d "$(pwd)"/mnt/*/ | head -1)artifacts"
else
  ARTIFACTS_ROOT="./artifacts"
fi
```

After Step 1 (when the slug is known), also include:

```bash
REVIEW_DIR="$ARTIFACTS_ROOT/financial-model-review-${SLUG}"
mkdir -p "$REVIEW_DIR"
```

### Step 1: Read or Create Founder Context

Check for an existing founder context file:

```bash
python3 "$SHARED_SCRIPTS/founder_context.py" read --artifacts-root "$ARTIFACTS_ROOT" --pretty
```

Three cases based on exit code:

**Exit 0 (found, single context):** Use the company slug and pre-filled fields. Proceed to Step 2.

**Exit 1 (not found):** Ask the founder for:
- Company name (-> slug)
- Stage (pre-seed / seed / series-a / series-b / later)
- Sector
- Geography

Then create it:

```bash
python3 "$SHARED_SCRIPTS/founder_context.py" init \
  --company-name "Acme Corp" --stage seed --sector "B2B SaaS" \
  --geography "US" --artifacts-root "$ARTIFACTS_ROOT"
```

**Exit 2 (multiple context files):** Present the list to the founder and ask which company this session is for. Then re-read with explicit `--slug`:

```bash
python3 "$SHARED_SCRIPTS/founder_context.py" read --slug "<chosen-slug>" --artifacts-root "$ARTIFACTS_ROOT" --pretty
```

### Step 2: Model Intake

Detect the format of the user's financial model.

**For Excel (.xlsx) or CSV files:** Run `extract_model.py` to parse the spreadsheet into structured data:

```bash
python3 "$SCRIPTS/extract_model.py" --file "$MODEL_FILE" --pretty -o "$REVIEW_DIR/model_data.json"
```

**For documents, Google Sheets exports, or conversational input:** Extract data manually from the provided materials into the `inputs.json` schema (Step 3).

If no materials are provided, ask the founder for: revenue figures, cost structure, headcount, funding history, growth rates, and key assumptions.

### Data Sufficiency Gate

After extracting available data, count critical fields missing from source material.

**Core fields (all revenue models):** `current_balance`, `monthly_net_burn`, `gross_margin`

**Model-specific fields:**
- SaaS / AI-native / usage-based: `mrr`, `growth_rate_monthly`, `cac`
- Marketplace: `gmv` or `take_rate`, `growth_rate_monthly`
- Hardware / hardware-subscription: `unit_cost`, `asp`, `growth_rate_monthly`
- Consumer-subscription: `mrr` or `subscriber_count`, `growth_rate_monthly`, `cac`

Count = missing core fields + missing model-specific fields (using `sector_type` to select the set).

If **3+ total fields are missing** AND `model_format` is `deck` or `conversational`:

**If running non-interactively** (invoked as a command with a file argument, or founder is not in the conversation):
- Proceed directly to the Qualitative Path below — do NOT estimate missing financial values.

**If running interactively** (conversation with founder):
1. List the missing fields to the founder
2. Ask: "Can you provide these numbers, even rough estimates?"
3. If yes → founder provides data, set `data_confidence: "mixed"` in `inputs.json` (some fields from source, some founder-supplied)
4. If no → proceed with qualitative path (see below)

### Qualitative Path (insufficient quantitative data)

When the founder cannot provide missing critical data:

- **checklist.py**: Always run (qualitative assessment works without financials)
- **unit_economics.py**: Deposit stub: `{"skipped": true, "reason": "Insufficient quantitative data for unit economics computation"}`
- **runway.py**: Deposit stub: `{"skipped": true, "reason": "Insufficient quantitative data for runway projection"}`
- **compose_report.py** and **visualize.py**: Handle stubs gracefully (already supported via `_is_stub()`)

Always set `data_confidence: "estimated"` in `inputs.json` (agent-estimated values from indirect signals). Stubs carry no `data_confidence` — it lives in `inputs.json` and compose_report reads it from there.

### Step 3: Build `inputs.json`

Construct the `inputs.json` artifact from extracted data (either from `model_data.json` or directly from conversation/documents). Consult `references/artifact-schemas.md` for the full schema.

```bash
cat <<'INPUTS_EOF' > "$REVIEW_DIR/inputs.json"
{...inputs JSON — see references/artifact-schemas.md for format...}
INPUTS_EOF
```

**Setting `model_format`:** Determine the format based on what the founder provided:
- `spreadsheet` -- Excel (.xlsx), CSV, or Google Sheets with structured tabs
- `deck` -- Pitch deck or presentation with financial data
- `conversational` -- Financial data gathered through conversation
- `partial` -- Incomplete spreadsheet model (e.g., revenue-only, no expense tabs)

When `model_format` is `deck` or `conversational`, structural checklist items (Structure & Presentation, Expenses/Cash/Runway) auto-gate to `not_applicable`, and the score reflects only business-quality items.

**AI-powered products:** If the product uses AI/ML inference as a core feature (not just internal tooling), include `"ai-powered"` in `company.traits` regardless of `revenue_model_type`. This ensures AI cost scrutiny (SECTOR_40) is triggered even for SaaS-priced products.

**Estimation guidance (interactive only):** When the founder provides partial data in conversation, use the conservative end of ranges (e.g., if burn is "under $30K/mo", use $30K). Set `data_confidence: "mixed"`.

### Step 4: Run Checklist -> `checklist.json`

**REQUIRED — read `$REFS/checklist-criteria.md` now.** It defines all 46 item IDs by category. Do not build the checklist JSON without reading this section.

#### Items to assess by model_format

| Format | Assess | Auto-gated by script (submit stubs) |
|--------|--------|-------------------------------------|
| `spreadsheet` | All 46 items | None |
| `deck` / `conversational` | UNIT_10–19, METRIC_33–35, BRIDGE_36–38, SECTOR_39–44, OVERALL_45–46 (24 items) | STRUCT_01–09, CASH_20–32 (22 items) |
| `partial` | All 46 items (assess what's available) | None |

For auto-gated items, submit a minimal stub — the script overrides them regardless:
`{"id": "STRUCT_01", "status": "not_applicable", "evidence": "auto-gated", "notes": null}`

Evaluate the applicable items for your `model_format` (see table above). For auto-gated items, submit minimal stubs. Pipe the input JSON via stdin:

```bash
cat <<'CHECK_EOF' | python3 "$SCRIPTS/checklist.py" --pretty -o "$REVIEW_DIR/checklist.json"
{"items": [
  {"id": "...", "status": "pass", "evidence": "...", "notes": null},
  ...all 46 items...
], "company": {...from inputs.json...}}
CHECK_EOF
```

### Step 5: Unit Economics -> `unit_economics.json`

Compute and benchmark the 11 unit economics metrics against stage-appropriate targets:

```bash
cat "$REVIEW_DIR/inputs.json" | python3 "$SCRIPTS/unit_economics.py" --pretty -o "$REVIEW_DIR/unit_economics.json"
```

### Step 6: Runway Stress-Test -> `runway.json`

Run multi-scenario runway analysis with decision points and default-alive assessment:

```bash
cat "$REVIEW_DIR/inputs.json" | python3 "$SCRIPTS/runway.py" --pretty -o "$REVIEW_DIR/runway.json"
```

### Step 7: Compose and Validate Report

Run the report composer and save to file:

```bash
python3 "$SCRIPTS/compose_report.py" --dir "$REVIEW_DIR" --pretty -o "$REVIEW_DIR/report.json" --strict
```

Read the output file and check `validation.warnings`:
- **High-severity warnings:** Fix the underlying artifact, re-run compose, and re-read the output. Do NOT present a report with high-severity warnings.
- **Medium-severity warnings:** Include them in your presentation to the user.
- **Low/info:** Note for completeness.

This is a refinement loop — fix, re-deposit artifacts, re-compose until high-severity warnings are resolved.

**Primary deliverable:** Read `report_markdown` from the output JSON and display it to the user in full. This is the main output of the review — the user must see the complete written report before anything else. Then add coaching commentary: what to feel confident about, the highest-leverage fix, whether the model story holds together, and which 1-2 metrics the founder should prioritize improving.

### Step 8: Visualize (Optional)

Supplement (not replace) the written report with a self-contained HTML report with charts:

```bash
python3 "$SCRIPTS/visualize.py" --dir "$REVIEW_DIR" -o "$REVIEW_DIR/report.html"
```

Opens in any browser. Contains SVG charts for checklist status, unit economics benchmarks, runway scenarios, and overall score. No external dependencies or JavaScript.

## Scoring

- Each of 46 items: pass / fail / warn / not_applicable
- `score_pct` = (pass + 0.5 * warn) / (total - not_applicable) * 100
- Unit economics: individual metric ratings against stage benchmarks
- Overall: "strong" (>=85%), "solid" (>=70%), "needs_work" (>=50%), "major_revision" (<50%)

## Troubleshooting

### Script not found
If the path resolution block cannot locate scripts:
1. Verify `${CLAUDE_PLUGIN_ROOT}` is set (SessionStart hook should set it)
2. Fall back to Glob: `**/founder-skills/skills/financial-model-review/scripts/<script>.py`
3. If running in Cowork, check that the plugin cache has been populated

### Invalid JSON from script
If a script exits non-zero or outputs invalid JSON:
1. Check stderr for the specific error message
2. Ensure the JSON piped via heredoc is valid (use `python3 -m json.tool` to verify)
3. Verify required fields are present in the input payload

### Empty or missing artifacts
If compose_report.py reports missing artifacts:
1. Verify the artifact directory exists: `ls "$REVIEW_DIR/"`
2. Check that earlier pipeline steps completed without error
3. Re-run the failed step individually to isolate the issue

### openpyxl import error
If `extract_model.py` fails with an import error for openpyxl:
1. Install with: `pip install openpyxl` or `uv pip install openpyxl`
2. Verify the installation: `python3 -c "import openpyxl; print(openpyxl.__version__)"`

## Additional Resources

### Reference Files

For detailed criteria definitions and benchmark data, consult:
- **`references/checklist-criteria.md`** — All 46 checklist criteria with gate definitions
- **`references/artifact-schemas.md`** — JSON schemas for all artifacts
- **Shared references:** `stage-expectations.md`, `benchmarks.md`, `israel-guidance.md`, `revenue-model-types.md`, `common-mistakes.md`
