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

Help startup founders build credible, defensible TAM/SAM/SOM analysis — the kind that earns investor trust rather than raising eyebrows. Produce a structured, validated market sizing with external sources, sensitivity testing, and a self-check against common pitfalls. The tone is founder-first: a rigorous but supportive coaching session.

## Input Formats

Accept any format: pitch deck (PDF, PPTX, markdown), financial model, market data, text descriptions, or verbal description of the business.

## Available Scripts

All scripts are at `${CLAUDE_PLUGIN_ROOT}/skills/market-sizing/scripts/`:

- **`market_sizing.py`** — TAM/SAM/SOM calculator (top-down, bottom-up, or both)
- **`sensitivity.py`** — Stress-test assumptions with low/base/high ranges and confidence-based auto-widening
- **`checklist.py`** — Validates 22-item self-check with pass/fail per item
- **`compose_report.py`** — Assembles report with cross-artifact validation; `--strict` exits 1 on high/medium warnings
- **`visualize.py`** — Generates self-contained HTML with SVG charts (not JSON)

Run with: `python3 ${CLAUDE_PLUGIN_ROOT}/skills/market-sizing/scripts/<script>.py --pretty [args]`

## Available References

Read as needed from `${CLAUDE_PLUGIN_ROOT}/skills/market-sizing/references/`:

- **`tam-sam-som-methodology.md`** — Definitions, calculation methods, industry examples, best practices
- **`pitfalls-checklist.md`** — Self-review checklist for common mistakes
- **`artifact-schemas.md`** — JSON schemas for all analysis artifacts

## Artifact Pipeline

Every analysis deposits structured JSON artifacts into a working directory. The final step assembles all artifacts into a report and validates consistency. This is not optional.

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

Keep the founder informed with brief, plain-language updates at each step. Never mention file names, scripts, or JSON. After each analytical step (4–6), share a one-sentence finding before moving on.

## Workflow

### Path Setup

```bash
SCRIPTS="$CLAUDE_PLUGIN_ROOT/skills/market-sizing/scripts"
REFS="$CLAUDE_PLUGIN_ROOT/skills/market-sizing/references"
if ls "$(pwd)"/mnt/*/ >/dev/null 2>&1; then
  ARTIFACTS_ROOT="$(ls -d "$(pwd)"/mnt/*/ | head -1)artifacts"
else
  ARTIFACTS_ROOT="$(pwd)/artifacts"
fi
```

If `CLAUDE_PLUGIN_ROOT` is empty, fall back: `Glob` for `**/founder-skills/skills/market-sizing/scripts/market_sizing.py`, strip to get `SCRIPTS`, derive `REFS`.

```bash
ANALYSIS_DIR="$ARTIFACTS_ROOT/market-sizing-{company-slug}"
mkdir -p "$ANALYSIS_DIR"
```

### Step 1: Gather Inputs -> `inputs.json`

Read any materials the user provided. Extract: company name, existing market claims, product/service description, geography and segments, pricing model, customer counts, revenue, growth rates. If no materials provided, ask for the basics.

If the deck includes explicit TAM/SAM/SOM claims, record them in `inputs.json` under `existing_claims`. These are used by compose_report.py and visualize.py to compare deck claims against calculated figures.

### Step 2: Read Methodology -> `methodology.json`

Read `references/tam-sam-som-methodology.md`. Choose the approach: top-down (industry reports exist), bottom-up (have customer/pricing data), or both (preferred — cross-validates). Record rationale and reference files read.

### Step 3: External Validation -> `validation.json`

Use WebSearch to find industry reports, government statistics, competitor data, and analyst figures. Triangulate key numbers with 2+ independent sources. Track every source with quality tier and segment match. Every assumption must appear in the `assumptions` array with a `name` matching script parameter names and a `category` of `sourced`, `derived`, or `agent_estimate`.

**Source quality hierarchy:** Government/regulatory > Established analysts > Industry associations > Academic > Business press > Company blogs (product facts only).

### Step 4: Calculate TAM/SAM/SOM -> `sizing.json`

```bash
cat <<'SIZING_EOF' | python3 "$SCRIPTS/market_sizing.py" --pretty -o "$ANALYSIS_DIR/sizing.json"
{...sizing input JSON — see artifact-schemas.md for format...}
SIZING_EOF
```

For "both" mode, check the comparison section — a >30% TAM discrepancy means investigating which assumptions are flawed. TAM must match the product's actual target universe (not inflated industry totals).

**Multi-vertical / platform companies:** If `inputs.json` lists applications in 2+ distinct industries:

1. **Identify verticals** — classify as `commercial` (revenue/pilots), `r_and_d` (demonstrated feasibility, 2-3yr commercialization path), or `future` (conceptual/early).
2. **Include `commercial` and `r_and_d` in TAM.** If top-down only covers one vertical, use bottom-up as primary. When verticals have different ARPUs, compute weighted blended ARPU. `Future` verticals go in coaching commentary as upside, not in the calculated TAM.
3. **Narrow SAM and SOM** — SAM = traction + active R&D segments. SOM = beachhead only.
4. **Document scope** in `methodology.json` `rationale`.

Default to full-scope TAM. Only narrow to beachhead if the user explicitly requests it.

### Step 4.5: Reality Check

Before proceeding, answer:

1. **Laugh test:** Would an experienced VC nod or raise an eyebrow? Seed + <5 pilots + >$1B TAM = explain yourself.
2. **Scope match:** Does TAM cover all `commercial` and `r_and_d` verticals from `inputs.json`?
3. **Customer count sanity:** Can you name a representative sample of the customers in your count?
4. **Convergence integrity:** Were top-down and bottom-up parameters set independently? If you adjusted one after seeing the other, revert and accept the delta.

This step produces no artifact. If it reveals problems, fix them before proceeding.

### Step 5: Sensitivity Analysis -> `sensitivity.json`

Tag each parameter with confidence from validation: `sourced` (range stands), `derived` (min +/-30%), `agent_estimate` (min +/-50%). Include **every `agent_estimate` parameter** — compose_report.py flags missing ones as `UNSOURCED_ASSUMPTIONS`.

```bash
cat <<'SENS_EOF' | python3 "$SCRIPTS/sensitivity.py" --pretty -o "$ANALYSIS_DIR/sensitivity.json"
{...sensitivity input JSON — see artifact-schemas.md for format...}
SENS_EOF
```

### Step 6: Self-Check -> `checklist.json`

Evaluate all 22 items from the pitfalls checklist. **Read `$REFS/artifact-schemas.md` "Canonical 22 checklist IDs" section first.**

```bash
cat <<'CHECK_EOF' | python3 "$SCRIPTS/checklist.py" --pretty -o "$ANALYSIS_DIR/checklist.json"
{"items": [
  {"id": "structural_tam_gt_sam_gt_som", "status": "pass", "notes": null},
  ...all 22 items...
]}
CHECK_EOF
```

### Step 7: Compose and Validate Report

```bash
python3 "$SCRIPTS/compose_report.py" --dir "$ANALYSIS_DIR" --pretty -o "$ANALYSIS_DIR/report.json"
```

Fix high-severity warnings and re-run. Use `--strict` to enforce a clean report.

**Primary deliverable:** Read `report_markdown` from the output JSON and display it to the user in full. Then add coaching commentary: what to feel confident about, the highest-leverage fix, whether the market story holds together, and which 1-2 sensitivity parameters to prioritize sourcing.

### Step 8 (Optional): Generate Visual Report

```bash
python3 "$SCRIPTS/visualize.py" --dir "$ANALYSIS_DIR" -o "$ANALYSIS_DIR/report.html"
```

### Step 9: Deliver Artifacts

Copy final deliverables to workspace root: `{Company}_Market_Sizing.md`, `.html` (if generated), `.json` (optional).

## Scoring

- Each of 22 items: pass / fail / not_applicable
- `score_pct` = pass / (total - not_applicable) x 100
- compose_report.py validates cross-artifact consistency (assumption coverage, source quality, sensitivity ranges)
