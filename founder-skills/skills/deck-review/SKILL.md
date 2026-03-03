---
name: deck-review
disable-model-invocation: true
description: "Scores and strengthens startup pitch decks against 35 investor-grade criteria before founders send them to VCs. Use when user asks to \"review my deck\", \"pitch deck feedback\", \"check my slides\", \"is my deck ready\", \"review this pitch deck\", \"deck critique\", \"improve my pitch deck\", \"what's wrong with my deck\", \"pitch deck review\", \"fundraising deck feedback\", or provides a pitch deck (PDF, PPTX, markdown, or text) for evaluation. Covers pre-seed, seed, and Series A against 2026 best practices from Sequoia, DocSend, YC, a16z, and Carta data. Do NOT use for financial model review, market sizing, or general document editing."
compatibility: Requires Python 3.10+ and uv for script execution.
metadata:
  author: lool-ventures
  version: "0.2.0"
exports:
  - "checklist.json -> financial-model-review, ic-sim, fundraise-readiness"
---

# Deck Review Skill

Help startup founders strengthen their pitch decks before sending them to investors. Produce a structured, scored review with specific, actionable recommendations grounded in 2026 best practices from Sequoia, DocSend, YC, a16z, and Carta data.

The tone is founder-first: a candid coaching session, not a VC evaluation. Celebrate what works, flag what doesn't, explain *why* investors care, and show *how* to fix it.

## Why This Matters

Investors spend ~2:30 of real attention on a share deck. 78% abandon before slide 6. Founders deserve to know exactly what investors will notice, question, and remember — so they can make those 2:30 count.

## Input Formats

Accept any format the user provides: PDF, PowerPoint (PPTX), markdown, or text descriptions of slides. Adapt extraction approach to what's available.

## Available Scripts

All scripts are at `${CLAUDE_PLUGIN_ROOT}/skills/deck-review/scripts/`:

- **`checklist.py`** — Scores 35 criteria across 7 categories (pass/fail/warn/not_applicable). Computes overall score percentage and status.
- **`compose_report.py`** — Assembles all artifacts into a final markdown report with cross-artifact validation; supports `--strict` to exit 1 on high/medium warnings (after writing output).
- **`visualize.py`** — Generates a self-contained HTML file with SVG charts (gauge, radar, stacked bars, slide map). Outputs HTML (not JSON). `--pretty` accepted as no-op for compatibility

Run with: `python3 ${CLAUDE_PLUGIN_ROOT}/skills/deck-review/scripts/<script>.py --pretty [args]`

**Path resolution:** `${CLAUDE_PLUGIN_ROOT}` is persisted by the SessionStart hook. At the start of a review, resolve it once:

```bash
SCRIPTS="$CLAUDE_PLUGIN_ROOT/skills/deck-review/scripts"
REFS="$CLAUDE_PLUGIN_ROOT/skills/deck-review/references"
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

If empty, fall back: run `Glob` with pattern `**/founder-skills/skills/deck-review/scripts/checklist.py`, strip to get `SCRIPTS`. Replace `/scripts` with `/references` to get `REFS`.

## Available References

Read as needed during the review from `${CLAUDE_PLUGIN_ROOT}/skills/deck-review/references/`:

- **`deck-best-practices.md`** — Full 2026 best practices: slide frameworks, stage-specific guidelines, design rules, AI-company requirements, financial standards, common mistakes
- **`checklist-criteria.md`** — Detailed definitions for all 35 criteria with pass/fail/warn thresholds and evidence basis
- **`artifact-schemas.md`** — JSON schemas for all artifacts (inventory, stage profile, slide reviews, checklist)

## Artifact Pipeline

Every review deposits structured JSON artifacts into a working directory. The final step assembles all artifacts into a report and validates consistency. This is not optional.

**Working directory:** Set `REVIEW_DIR` at the start. Artifacts persist in the workspace `artifacts/` directory across sessions.

```bash
REVIEW_DIR="$ARTIFACTS_ROOT/deck-review-{company-slug}"
mkdir -p "$REVIEW_DIR"
test -d "$REVIEW_DIR" && echo "Directory ready: $REVIEW_DIR"
```

| Step | Artifact | Producer |
|------|----------|----------|
| 1 | `deck_inventory.json` | Agent (heredoc) |
| 2 | `stage_profile.json` | Agent (heredoc) |
| 3 | `slide_reviews.json` | Agent (heredoc) |
| 4 | `checklist.json` | `checklist.py` |
| 5 | Report | `compose_report.py` |

**Rules:**
- Deposit each artifact before proceeding to the next step
- For agent-written artifacts (Steps 1-3), consult `references/artifact-schemas.md` for the JSON schema
- If a step is not applicable, deposit a stub: `{"skipped": true, "reason": "..."}`

## Workflow

### Step 1: Ingest Deck → `deck_inventory.json`

Read the provided deck (PDF, PPTX, markdown, or text). For each slide, extract: headline, content summary, visuals description, word count estimate. Record metadata: company name, total slides, format, any claimed stage or raise amount.

### Step 2: Detect Stage → `stage_profile.json`

Determine pre-seed/seed/series-a from signals in the deck. Read `references/deck-best-practices.md` for stage-specific frameworks. Record: detected stage, confidence, evidence, whether AI company, expected slide framework, stage benchmarks.

**Stage signals:** Pre-seed: no revenue, LOIs/waitlist, prototype, <$2.5M ask. Seed: early ARR, paying customers, <$6M ask. Series A: $1M+ ARR, cohort data, repeatable GTM, $10M+ ask. Later-stage: $5M+ ARR, proven unit economics, multi-product, $15M+ ask. If detected, set detected_stage to `"series_b"` or `"growth"` — the compose report will flag this as out of calibrated scope. If ambiguous, ask the user.

### Step 3: Review Each Slide → `slide_reviews.json`

Compare each slide against the stage-specific framework and non-negotiable principles from the best practices. For each slide: identify strengths, weaknesses, and specific recommendations. Map to expected framework. Flag missing expected slides.

**Critical:** Every critique must cite a specific best-practice principle. No vague feedback.

### Step 4: Score Checklist → `checklist.json`

Evaluate all 35 criteria from `references/checklist-criteria.md`. Map slide reviews to criteria. Feed structured JSON to `checklist.py`:

```bash
cat <<'CHECKLIST_EOF' | python3 "$SCRIPTS/checklist.py" --pretty -o "$REVIEW_DIR/checklist.json"
{
  "items": [
    {"id": "purpose_clear", "status": "pass", "evidence": "Sequoia: single declarative sentence", "notes": "Clear one-liner with quantified outcome"},
    ...all 35 items...
  ]
}
CHECKLIST_EOF
```

For non-AI companies, mark all AI category items as `not_applicable`.

**Evidence required:** Always provide an `evidence` string for items with `fail` or `warn` status — the script warns on stderr when evidence is missing.

### Step 5: Compose Report

```bash
python3 "$SCRIPTS/compose_report.py" --dir "$REVIEW_DIR" --pretty -o "$REVIEW_DIR/report.json"
```

Read the output file and check `validation.warnings`. Fix high-severity warnings and re-run. Use `--strict` to enforce a clean report (writes output first, then exits 1 on high/medium warnings).

**Primary deliverable:** Read `report_markdown` from the output JSON and display it to the user in full. This is the main output of the review — the user must see the complete written report before anything else.

### Step 6 (Optional): Generate Visual Report

Supplement (not replace) the written report with a self-contained HTML report with charts:

```bash
python3 "$SCRIPTS/visualize.py" --dir "$REVIEW_DIR" -o "$REVIEW_DIR/report.html"
```

Opens in any browser. Contains SVG charts for score gauge, category radar, category breakdown, and slide map. No external dependencies or JavaScript.

### Step 7: Deliver Artifacts

Copy the final deliverables to the workspace root for easy access:

- Extract `report_markdown` from `report.json` and save as `{Company}_Deck_Review.md`
- `{Company}_Deck_Review.html` — visual HTML report (if generated)
- `{Company}_Deck_Review.json` — full structured output with validation metadata (optional, for programmatic use)

## Scoring

- Each of 35 items: pass / fail / warn / not_applicable
- `score_pct` = pass / (total - not_applicable) x 100
- Overall: "strong" (>=85%), "solid" (>=70%), "needs_work" (>=50%), "major_revision" (<50%)

## Troubleshooting

### Script not found
If the path resolution block cannot locate scripts:
1. Verify `${CLAUDE_PLUGIN_ROOT}` is set (SessionStart hook should set it)
2. Fall back to Glob: `**/founder-skills/skills/deck-review/scripts/<script>.py`
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

## Performance Notes
- Take your time to do this thoroughly
- Quality is more important than speed
- Do not skip validation steps or checklist items

## Progress Updates

Keep the founder informed with brief, plain-language updates at each step. Never mention file names, scripts, or JSON — describe what you're doing in terms they care about.

| Step | Say to the founder |
|------|--------------------|
| 1 | "Reading through your deck and cataloging each slide..." |
| 2 | "Detecting your company stage to calibrate expectations..." |
| 3 | "Reviewing each slide in detail..." |
| 4 | "Scoring your deck against 35 investor-readiness criteria..." |
| 5 | "Assembling the full review and cross-checking for consistency..." |
| 6 | "Generating a visual summary with charts..." |

After each analytical step (3–4) completes, share a one-sentence finding before moving on (e.g., "Your problem and solution slides are strong — the competitive landscape slide needs more specificity."). Don't wait until the end to surface findings.

## Additional Resources

### Reference Files

For detailed criteria definitions and best practices, consult:
- **`references/deck-best-practices.md`** — Complete 2026 best practices source
- **`references/checklist-criteria.md`** — All 35 criteria with thresholds
- **`references/artifact-schemas.md`** — JSON schemas for artifacts
