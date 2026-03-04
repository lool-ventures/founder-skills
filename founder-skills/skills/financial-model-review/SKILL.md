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

Help startup founders understand how investors will evaluate their financial model — validating structure, unit economics, runway, and metrics against stage-appropriate standards. Produce a thorough review with actionable improvements. The tone is founder-first: a rigorous but supportive coaching session.

## Input Formats

Accept any format: Excel (.xlsx), CSV, Google Sheets exports, financial documents, or conversational input. For Excel files, use `extract_model.py` to parse. For other formats, extract data manually into the `inputs.json` schema.

## Available Scripts

All scripts are at `${CLAUDE_PLUGIN_ROOT}/skills/financial-model-review/scripts/`:

- **`extract_model.py`** — Extracts structured data from Excel (.xlsx) and CSV files
- **`checklist.py`** — Scores 46 criteria across 7 categories with profile-based auto-gating
- **`unit_economics.py`** — Computes and benchmarks 11 unit economics metrics
- **`runway.py`** — Multi-scenario runway stress-test with decision points
- **`compose_report.py`** — Assembles report with cross-artifact validation; `--strict` exits 1 on high/medium warnings
- **`visualize.py`** — Generates self-contained HTML with SVG charts (not JSON)

Run with: `python3 ${CLAUDE_PLUGIN_ROOT}/skills/financial-model-review/scripts/<script>.py --pretty [args]`

## Available References

Read as needed from `${CLAUDE_PLUGIN_ROOT}/skills/financial-model-review/references/`:

- **`checklist-criteria.md`** — All 46 checklist criteria with gate definitions
- **`schema-inputs.md`** — JSON schema for `inputs.json` (the artifact the agent writes)
- **`artifact-schemas.md`** — JSON schemas for script-produced output artifacts
- **`data-sufficiency.md`** — Data sufficiency gate and qualitative path

From `${CLAUDE_PLUGIN_ROOT}/references/` (shared): `stage-expectations.md`, `benchmarks.md`, `israel-guidance.md`, `revenue-model-types.md`, `common-mistakes.md`

## Artifact Pipeline

Every review deposits structured JSON artifacts into a working directory. The final step assembles all artifacts into a report and validates consistency. This is not optional.

| Step | Artifact | Producer |
|------|----------|----------|
| 1 | founder context | `founder_context.py` read/init |
| 2 | `model_data.json` | Sub-agent (Task) + `extract_model.py` (Excel/CSV) |
| 3 | `inputs.json` | Sub-agent (Task, single-pass or two-pass) or agent (heredoc) |
| 4 | `checklist.json` | Sub-agent (Task) + `checklist.py` |
| 5 | `unit_economics.json` | Sub-agent (Task) + `unit_economics.py` |
| 6 | `runway.json` | Sub-agent (Task) + `runway.py` |
| 7 | Report | `compose_report.py` reads all |
| 8 | HTML | `visualize.py` |

**Rules:**
- Deposit each artifact before proceeding to the next step
- For agent-written artifacts (Step 3), consult `references/schema-inputs.md` for the JSON schema
- If a step is not applicable, deposit a stub: `{"skipped": true, "reason": "..."}`
- **Do NOT use `isolation: "worktree"`** for sub-agents — files written in a worktree won't appear in the main `$REVIEW_DIR`

Keep the founder informed with brief, plain-language updates at each step. Never mention file names, scripts, or JSON. After each analytical step (4–6), share a one-sentence finding before moving on.

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

If `CLAUDE_PLUGIN_ROOT` is empty, fall back: run `Glob` with pattern `**/founder-skills/skills/financial-model-review/scripts/checklist.py`, strip to get `SCRIPTS`, derive `REFS` and `SHARED_SCRIPTS`.

After Step 1 (when the slug is known):

```bash
REVIEW_DIR="$ARTIFACTS_ROOT/financial-model-review-${SLUG}"
mkdir -p "$REVIEW_DIR"
```

If `REVIEW_DIR` already contains artifacts from a previous run, remove them before starting:

    rm -f "$REVIEW_DIR"/{inputs,checklist,unit_economics,runway,report,model_data}.json "$REVIEW_DIR/report.html"

### Step 1: Read or Create Founder Context

```bash
python3 "$SHARED_SCRIPTS/founder_context.py" read --artifacts-root "$ARTIFACTS_ROOT" --pretty
```

Three cases based on exit code:

**Exit 0 (found, single context):** Use the company slug and pre-filled fields.

**Exit 1 (not found):** Ask the founder for company name, stage, sector, geography. Then create:

```bash
python3 "$SHARED_SCRIPTS/founder_context.py" init \
  --company-name "Acme Corp" --stage seed --sector "B2B SaaS" \
  --geography "US" --artifacts-root "$ARTIFACTS_ROOT"
```

**Exit 2 (multiple context files):** Present the list to the founder, ask which company, then re-read with `--slug`.

### Steps 2-3: Extract Model Data and Build `inputs.json`

**When Excel (.xlsx) or CSV files are provided,** spawn a `general-purpose` Task sub-agent to handle extraction and input construction. The sub-agent receives: file path, `SCRIPTS`, `REFS`, `SHARED_REFS`, and `REVIEW_DIR` paths. **Do NOT use `isolation: "worktree"`** — files written in a worktree won't appear in the main `$REVIEW_DIR`.

The sub-agent:
1. Runs `extract_model.py` on the file → `model_data.json`
2. Reads `$REFS/schema-inputs.md` for the JSON schema
3. Reads `$REFS/data-sufficiency.md` to assess data sufficiency
4. Constructs `inputs.json` from extracted data, writing it to `$REVIEW_DIR/inputs.json`

Instruct the sub-agent to return ONLY: (1) file paths written, (2) company name/stage/sector, (3) `model_format`, (4) data sufficiency verdict (sufficient/insufficient + count of missing critical fields), and (5) any `company.traits` detected — do not echo the full JSON back.

After the sub-agent returns, use the summary to decide the qualitative vs. quantitative path and share a brief update with the founder.

**When documents (PDFs, data room dumps, Google Sheets exports) are provided,** use a two-pass sub-agent flow:

1. **Probe pass:** Spawn a `general-purpose` Task sub-agent with the file path(s), `SCRIPTS`, `REFS`, `SHARED_REFS`, and `REVIEW_DIR` paths. The sub-agent reads the document(s), reads `$REFS/schema-inputs.md` for the schema, extracts what it can, and returns ONLY: (1) partial data extracted (company name, stage, sector, any metrics found), (2) `model_format`, (3) a numbered list of specific questions for missing critical fields (e.g., "1. What is your monthly burn rate? 2. How many paying customers?"), and (4) any `company.traits` detected. Save the sub-agent's ID for resumption.

2. **Ask the founder:** Present the sub-agent's questions in plain language. Collect answers.

3. **Build pass:** Resume the same sub-agent (using `resume` with the saved agent ID — preserves full document context). Pass the founder's answers. The sub-agent reads `$REFS/data-sufficiency.md`, constructs `inputs.json`, and writes it to `$REVIEW_DIR/inputs.json`. Returns ONLY: (1) file paths written, (2) data sufficiency verdict (sufficient/insufficient + count of missing critical fields), and (3) final `model_format`.

After the sub-agent returns, use the summary to decide the qualitative vs. quantitative path and share a brief update with the founder.

**When conversational input is provided (no files):** Handle directly in the main agent — the data is already in the conversation. Ask the founder for any missing fields: revenue figures, cost structure, headcount, funding history, growth rates, key assumptions. Consult `references/schema-inputs.md` for the full schema.

```bash
cat <<'INPUTS_EOF' > "$REVIEW_DIR/inputs.json"
{...inputs JSON — see references/schema-inputs.md for format...}
INPUTS_EOF
```

**Data sufficiency:** After extracting data (whether via sub-agent or directly), consult `references/data-sufficiency.md` to determine if enough quantitative data is available. If 3+ critical fields are missing, follow the data sufficiency gate procedure.

**Setting `model_format`:** `spreadsheet` (Excel/CSV/Google Sheets), `deck` (pitch deck), `conversational` (gathered through conversation), `partial` (incomplete spreadsheet). When `model_format` is `deck` or `conversational`, structural items auto-gate to `not_applicable`.

**AI-powered products:** If the product uses AI/ML inference as a core feature, include `"ai-powered"` in `company.traits` regardless of `revenue_model_type`.

**Graceful degradation:** If Task tool is unavailable, extract directly in the main agent.

### Steps 4-6: Parallel Analysis (Checklist + Metrics & Runway)

Spawn 2 `general-purpose` Task sub-agents **in a single message** (parallel, no `isolation: "worktree"`). Each receives the expanded `SCRIPTS`, `REFS`, `SHARED_SCRIPTS`, `SHARED_REFS`, and `REVIEW_DIR` paths.

**Sub-agent A — Checklist Scorer:**

Reads `$REFS/checklist-criteria.md`, reads `$REVIEW_DIR/inputs.json`, assesses all 46 items with evidence, and runs `checklist.py`.

| Format | Assess | Auto-gated by script |
|--------|--------|---------------------|
| `spreadsheet` | All 46 items | None |
| `deck` / `conversational` | 24 business-quality items | STRUCT_01–09, CASH_20–32 (22 items) |
| `partial` | All 46 items | None |

```bash
cat <<'CHECK_EOF' | python3 "$SCRIPTS/checklist.py" --pretty -o "$REVIEW_DIR/checklist.json"
{"items": [
  {"id": "...", "status": "pass", "evidence": "...", "notes": null},
  ...all 46 items...
], "company": {...from inputs.json...}}
CHECK_EOF
```

**Evidence required:** Always provide `evidence` for `fail` or `warn` items.

Instruct Sub-agent A to return ONLY: (1) file path written, (2) `score_pct`, (3) overall rating, and (4) top 3 fail/warn items — do not echo the full assessment back.

**Sub-agent B — Metrics & Runway:**

Runs `unit_economics.py`, `runway.py`, and cross-skill lookups.

```bash
cat "$REVIEW_DIR/inputs.json" | python3 "$SCRIPTS/unit_economics.py" --pretty -o "$REVIEW_DIR/unit_economics.json"
cat "$REVIEW_DIR/inputs.json" | python3 "$SCRIPTS/runway.py" --pretty -o "$REVIEW_DIR/runway.json"
```

Cross-skill: Use `find_artifact.py` to locate prior market-sizing and deck-review artifacts. If market-sizing found, compare projected Year 3 ARR against SOM. If deck-review found, cross-reference financial claims. Record findings for coaching commentary. If neither found, note and proceed.

If the main agent indicates the **qualitative path** (data insufficient for quantitative analysis), Sub-agent B deposits stubs instead of running unit_economics/runway scripts: `{"skipped": true, "reason": "qualitative path — insufficient quantitative data"}`

Instruct Sub-agent B to return ONLY: (1) file paths written, (2) key metrics (burn rate, runway months, LTV/CAC), and (3) cross-skill findings — do not echo the full JSON back.

**Graceful degradation:** If Task tool is unavailable, run Steps 4-6 sequentially in the main agent.

After both sub-agents return, share a brief coaching update with the founder before proceeding to Step 7.

### Step 7: Compose and Validate Report

```bash
python3 "$SCRIPTS/compose_report.py" --dir "$REVIEW_DIR" --pretty -o "$REVIEW_DIR/report.json" --strict
```

Check `validation.warnings`: fix high-severity, include medium in presentation, note low/info. This is a refinement loop — fix, re-deposit, re-compose until high-severity warnings are resolved.

**Primary deliverable:** Read `report_markdown` from the output JSON, append `\n\n---\n[View visual report](report.html)\n` to it, write the result to `$REVIEW_DIR/report.md`, and display it to the user in full. Then add coaching commentary.

### Step 8: Visualize (Optional)

```bash
python3 "$SCRIPTS/visualize.py" --dir "$REVIEW_DIR" -o "$REVIEW_DIR/report.html"
```

## Scoring

- Each of 46 items: pass / fail / warn / not_applicable
- `score_pct` = (pass + 0.5 * warn) / (total - not_applicable) * 100
- Overall: "strong" (>=85%), "solid" (>=70%), "needs_work" (>=50%), "major_revision" (<50%)
