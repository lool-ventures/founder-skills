---
name: market-sizing
disable-model-invocation: true
description: "Builds credible TAM/SAM/SOM analysis with external validation and sensitivity testing for startup fundraising. Use when user asks to \"size this market\", \"what's the TAM\", \"analyze this market\", \"validate these market numbers\", \"review the market sizing slide\", \"is this market big enough\", \"market sizing\", \"TAM/SAM/SOM\", \"stress-test market assumptions\", or provides a pitch deck, financial model, or market data for analysis. Supports top-down, bottom-up, or dual-methodology approaches. Do NOT use for general market research without sizing, competitive landscape analysis, or financial model review (use financial-model-review)."
compatibility: Requires Python 3.10+ and uv for script execution.
metadata:
  author: lool-ventures
  version: "0.2.0"
exports:
  - "sizing.json -> financial-model-review, ic-sim, fundraise-readiness"
  - "sensitivity.json -> financial-model-review"
  - "checklist.json -> ic-sim"
---

# Market Sizing Skill

Help startup founders build credible, defensible TAM/SAM/SOM analysis — the kind that earns investor trust rather than raising eyebrows. Produce a structured, validated market sizing with external sources, sensitivity testing, and a self-check against common pitfalls.

The tone is founder-first: a rigorous but supportive coaching session. Confirm what's solid, flag what's not, and always explain *why* a number matters to investors and *how* to make it defensible.

## Why This Matters

Market sizing is the slide investors scrutinize most — and the one founders most often get wrong. Inflated TAMs get picked apart in diligence. Missing bottom-up validation signals laziness. Founders deserve to know exactly which numbers will hold up under investor scrutiny, so they can present with confidence.

## Input Formats

Accept any format the user provides: pitch deck (PDF, PPTX, markdown), financial model, market data, text descriptions, or just a verbal description of the business. Adapt extraction approach to what's available.

## Available Scripts

All scripts are at `${CLAUDE_PLUGIN_ROOT}/skills/market-sizing/scripts/`:

- **`market_sizing.py`** — TAM/SAM/SOM calculator (top-down, bottom-up, or both approaches)
- **`sensitivity.py`** — Stress-test assumptions with low/base/high ranges and confidence-based auto-widening
- **`checklist.py`** — Validates 22-item self-check with pass/fail per item
- **`compose_report.py`** — Assembles report from artifacts, validates cross-artifact consistency; supports `--strict` to exit 1 on high/medium warnings (after writing output)
- **`visualize.py`** — Generates a self-contained HTML file with SVG charts (funnel, tornado, donut). Outputs HTML (not JSON). `--pretty` accepted as no-op for compatibility

Run with: `python3 ${CLAUDE_PLUGIN_ROOT}/skills/market-sizing/scripts/<script>.py --pretty [args]`

**Path resolution:** `${CLAUDE_PLUGIN_ROOT}` is persisted by the SessionStart hook. At the start of an analysis, resolve it once:

```bash
SCRIPTS="$CLAUDE_PLUGIN_ROOT/skills/market-sizing/scripts"
REFS="$CLAUDE_PLUGIN_ROOT/skills/market-sizing/references"
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

If empty, fall back: run `Glob` with pattern `**/founder-skills/skills/market-sizing/scripts/market_sizing.py`, strip to get `SCRIPTS`. Replace `/scripts` with `/references` to get `REFS`.

## Available References

Read as needed during the analysis from `${CLAUDE_PLUGIN_ROOT}/skills/market-sizing/references/`:

- **`tam-sam-som-methodology.md`** — Definitions, calculation methods, industry examples, best practices
- **`pitfalls-checklist.md`** — Self-review checklist for common mistakes
- **`artifact-schemas.md`** — JSON schemas for all analysis artifacts (inputs, validation, sizing, sensitivity, checklist)

## Artifact Pipeline

Every analysis deposits structured JSON artifacts into a working directory. The final step assembles all artifacts into a report and validates consistency. This is not optional.

**Working directory:** Set `ANALYSIS_DIR` at the start. Artifacts persist in the workspace `artifacts/` directory across sessions.

```bash
ANALYSIS_DIR="$ARTIFACTS_ROOT/market-sizing-{company-slug}"
mkdir -p "$ANALYSIS_DIR"
test -d "$ANALYSIS_DIR" && echo "Directory ready: $ANALYSIS_DIR"
```

| Step | Artifact | Producer |
|------|----------|----------|
| 1 | `inputs.json` | Agent (heredoc) |
| 2 | `methodology.json` | Agent (heredoc) |
| 3 | `validation.json` | Agent (heredoc) |
| 4 | `sizing.json` | `market_sizing.py -o` |
| 5 | `sensitivity.json` | `sensitivity.py -o` |
| 6 | `checklist.json` | `checklist.py -o` |
| 7 | Report | `compose_report.py` reads all |

**Rules:**
- Deposit each artifact before proceeding to the next step
- For agent-written artifacts (Steps 1-3), consult `references/artifact-schemas.md` for the JSON schema
- If a step is not applicable, deposit a stub: `{"skipped": true, "reason": "..."}`

## Workflow

### Step 1: Gather Inputs -> `inputs.json`

Read any materials the user provided. Extract: company name, existing market claims, product/service description, geography and segments, pricing model, customer counts, revenue, growth rates. If no materials provided, ask for the basics.

If the deck or materials include explicit TAM/SAM/SOM claims, record them in `inputs.json` under `existing_claims` (e.g., `{"tam": 50000000000, "sam": 8000000000}`). These are used by compose_report.py and visualize.py to compare deck claims against calculated figures and track provenance.

### Step 2: Read Methodology -> `methodology.json`

Read `references/tam-sam-som-methodology.md`. Choose the approach: top-down (industry reports exist), bottom-up (have customer/pricing data), or both (preferred — cross-validates). Record rationale and reference files read.

### Step 3: External Validation -> `validation.json`

Use WebSearch to find industry reports, government statistics, competitor data, and analyst figures. Triangulate key numbers with 2+ independent sources. Track every source with quality tier and segment match. Every assumption must appear in the `assumptions` array with a `name` matching the parameter used in the scripts and a `category` of `sourced`, `derived`, or `agent_estimate`. The category drives provenance classification in reports (see `artifact-schemas.md`).

**Source quality hierarchy:** Government/regulatory > Established analysts > Industry associations > Academic > Business press > Company blogs (product facts only).

### Step 4: Calculate TAM/SAM/SOM -> `sizing.json`

Run `market_sizing.py` with chosen approach. Pipe the input JSON via stdin (the script does not accept file path arguments):

```bash
cat <<'SIZING_EOF' | python3 "$SCRIPTS/market_sizing.py" --pretty -o "$ANALYSIS_DIR/sizing.json"
{...sizing input JSON — see artifact-schemas.md for format...}
SIZING_EOF
```

For "both" mode, check the comparison section — a >30% TAM discrepancy means investigating which assumptions are flawed. TAM must match the product's actual target universe (not inflated industry totals).

**Multi-vertical / platform companies:** If the company sells into multiple distinct industries or has applications at different maturity stages (e.g., commercial pilots in electrolyzers, R&D in batteries, future in quantum), the calculated TAM must reflect the full near-term opportunity — not just the beachhead:

1. **Identify all verticals** where the product has a credible value proposition. Classify each as: `commercial` (revenue or active pilots), `r_and_d` (demonstrated technical feasibility with a credible path to commercial pilots within 2-3 years), or `future` (conceptual, early research, or no clear commercialization timeline).
2. **Include `commercial` and `r_and_d` verticals in the calculated TAM.** If the top-down industry total only covers one vertical, use the bottom-up approach as the primary TAM and note the single-vertical industry figure for context only. When verticals have different economics, compute a weighted blended ARPU: `(customers_A x arpu_A + customers_B x arpu_B + ...) / total_customers` and document the per-vertical breakdown in `methodology.json` `rationale`. `Future` verticals should not be included in the calculated TAM — mention them in the coaching commentary as upside optionality.
3. **Narrow SAM and SOM appropriately:** SAM = the segments where the company has commercial traction or active R&D. SOM = beachhead only (where pilots or revenue exist today).
4. **Document your TAM scope decision** in `methodology.json` `rationale`. State which verticals are included in the TAM and why. If you intentionally scope TAM to a single vertical, explain why the other verticals were excluded.

**Decision rule:** If `inputs.json` mentions applications, customers, or use cases in 2+ distinct industries, treat it as multi-vertical and default to full-scope TAM (commercial + R&D verticals). The user can explicitly request beachhead-only scoping — if they do, document that decision in `methodology.json` `rationale`. Never narrow TAM on your own initiative.

**Single-market companies:** If the product targets one industry/segment, proceed with the standard single-set calculation as shown above.

### Step 4.5: Reality Check

Before proceeding to sensitivity analysis, pause and answer these questions. If any answer is "no" or raises a flag, go back and fix the sizing before continuing.

1. **Laugh test:** If you told an experienced VC this TAM number over coffee, would they nod or raise an eyebrow? For a seed-stage company with <5 pilots, a TAM over $1B needs strong justification.
2. **Scope match:** Does the TAM reflect ALL the `commercial` and `r_and_d` verticals listed in `inputs.json`? If `inputs.json` mentions multiple industries but `sizing.json` only sizes one, either re-do the sizing as multi-vertical (see Step 4) or explicitly document in `methodology.json` rationale why single-vertical is the right framing.
3. **Customer count sanity:** Is the customer count grounded in identifiable entities? You should be able to name a representative sample — e.g., if you claim 60 OEMs, can you name at least a third of them? If the total market has fewer than 20 buyers, can you name most of them? A count you can't substantiate with real company names is likely inflated.
4. **Convergence integrity:** If using both approaches, were the top-down and bottom-up parameters set independently? If you adjusted any parameter after seeing the other approach's result, that is convergence gaming — revert to your original estimate and accept the delta. A 40% discrepancy you can explain is more honest than a 5% delta you engineered.

This step produces no artifact. It is a gate — if it reveals problems, fix them in Steps 1-4 before proceeding.

### Step 5: Sensitivity Analysis -> `sensitivity.json`

Tag each parameter with confidence from validation: `sourced` (range stands), `derived` (min +/-30%), `agent_estimate` (min +/-50%). Include **every `agent_estimate` parameter** in the sensitivity ranges — compose_report.py flags any missing ones as `UNSOURCED_ASSUMPTIONS`. Add additional `sourced`/`derived` params as needed (3–5 total is typical).

Pipe the input JSON via stdin (the script does not accept `-i` or file path arguments):

```bash
cat <<'SENS_EOF' | python3 "$SCRIPTS/sensitivity.py" --pretty -o "$ANALYSIS_DIR/sensitivity.json"
{...sensitivity input JSON — see artifact-schemas.md for format...}
SENS_EOF
```

### Step 6: Self-Check -> `checklist.json`

**REQUIRED — read `$REFS/artifact-schemas.md` "Canonical 22 checklist IDs" section now.** It lists all 22 item IDs by category. Do not build the checklist JSON without reading this section.

Evaluate all 22 items from the pitfalls checklist. Pipe the input JSON via stdin:

```bash
cat <<'CHECK_EOF' | python3 "$SCRIPTS/checklist.py" --pretty -o "$ANALYSIS_DIR/checklist.json"
{"items": [
  {"id": "structural_tam_gt_sam_gt_som", "status": "pass", "notes": null},
  ...all 22 items...
]}
CHECK_EOF
```

### Step 7: Compose and Validate Report

Run `compose_report.py`. Fix high-severity warnings and re-run. Use `--strict` to enforce a clean report (writes output first, then exits 1 on high/medium warnings).

**Primary deliverable:** Read `report_markdown` from the output JSON and display it to the user in full. This is the main output of the analysis — the user must see the complete written report before anything else. Then add coaching commentary: what to feel confident about, the highest-leverage fix, whether the market story holds together, and which 1-2 sensitivity parameters the founder should prioritize sourcing — explain what happens to the market story if those assumptions move against them.

### Step 8 (Optional): Generate Visual Report

Supplement (not replace) the written report with a self-contained HTML report with charts:

```bash
python3 "$SCRIPTS/visualize.py" --dir "$ANALYSIS_DIR" -o "$ANALYSIS_DIR/report.html"
```

Opens in any browser. Contains SVG charts for TAM/SAM/SOM funnel, sensitivity tornado, cross-validation comparison, assumption confidence, and checklist status. No external dependencies or JavaScript.

### Step 9: Deliver Artifacts

Copy the final deliverables to the workspace root for easy access:

- Extract `report_markdown` from `report.json` and save as `{Company}_Market_Sizing.md`
- `{Company}_Market_Sizing.html` — visual HTML report (if generated)
- `{Company}_Market_Sizing.json` — full structured output with validation metadata (optional, for programmatic use)

## Scoring

- Each of 22 items: pass / fail / not_applicable
- `score_pct` = pass / (total - not_applicable) x 100
- compose_report.py validates cross-artifact consistency (assumption coverage, source quality, sensitivity ranges)

## Troubleshooting

### Script not found
If the path resolution block cannot locate scripts:
1. Verify `${CLAUDE_PLUGIN_ROOT}` is set (SessionStart hook should set it)
2. Fall back to Glob: `**/founder-skills/skills/market-sizing/scripts/<script>.py`
3. If running in Cowork, check that the plugin cache has been populated

### Invalid JSON from script
If a script exits non-zero or outputs invalid JSON:
1. Check stderr for the specific error message
2. Ensure the JSON piped via heredoc is valid (use `python3 -m json.tool` to verify)
3. Verify required fields are present in the input payload

### Empty or missing artifacts
If compose_report.py reports missing artifacts:
1. Verify the artifact directory exists: `ls "$ANALYSIS_DIR/"`
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
| 1 | "Gathering your market inputs and assumptions..." |
| 2 | "Reading up on sizing methodology for your market..." |
| 3 | "Validating your numbers against external sources..." |
| 4 | "Calculating your TAM, SAM, and SOM..." |
| 4.5 | "Sanity-checking the results..." |
| 5 | "Stress-testing your assumptions with sensitivity analysis..." |
| 6 | "Running the self-check against 22 common sizing pitfalls..." |
| 7 | "Assembling the full report and cross-checking for consistency..." |
| 8 | "Generating a visual summary with charts..." |

After each analytical step (4–6) completes, share a one-sentence finding before moving on (e.g., "Your bottom-up SOM looks well-grounded — the top-down TAM may need a tighter scope."). Don't wait until the end to surface findings.

## Additional Resources

### Reference Files

For detailed methodology and criteria definitions, consult:
- **`references/tam-sam-som-methodology.md`** — Complete TAM/SAM/SOM methodology
- **`references/pitfalls-checklist.md`** — All 22 pitfall items
- **`references/artifact-schemas.md`** — JSON schemas for artifacts
