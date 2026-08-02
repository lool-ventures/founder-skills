# Lane 3 — Freeform spreadsheet

Typical input: a founder's own Excel file with arbitrary structure — not Carta, not Pulley, no fixed schema.

## Confirm the format, then extract the cell grid

First confirm the workbook really is freeform (not a Carta/Pulley export that should take Lane 2):

```bash
python3 "$SCRIPTS/extract_cap_table.py" --mode=auto --xlsx "$XLSX_PATH" || true
```

For a freeform workbook this prints `{"ok": false, "detected_format": "freeform", "sheet_names": [...]}` and exits non-zero — that is the expected confirmation, not an error (the `|| true` keeps the expected exit code from reading as a failure). It does not write any artifact. (If it detects Carta or Pulley, switch to Lane 2.)

Then read the cell grid — per sheet: sheet name, dimensions, cell values per row, and any merged-cell ranges:

```bash
python3 "$SCRIPTS/extract_cap_table.py" --mode=grid --xlsx "$XLSX_PATH"
```

The output is JSON to stdout (`{"ok": true, "mode": "grid", "sheets": {...}, "compaction": {...}}`). **Paste this JSON VERBATIM into the dispatch prompt below — do NOT hand-condense, sample, summarize, or chunk it yourself.** `--mode=grid` has already compacted it under the control-frame budget (see below), so re-condensing it both wastes turns and risks dropping the very rows/columns the sub-agent needs. If a workbook were ever too large to compact, the script returns a `grid_too_large` blocker instead of overflowing — handle that, don't pre-empt it by trimming the grid.

### The grid is compacted to fit the control-frame cap

A whole freeform workbook can be too large to inline into a dispatch prompt (the control frame has a hard ~256 KiB ceiling). Since the grid is used **only** for structure/role detection — the deterministic `--mode=freeform-emit` step below re-reads the *full* grid straight from the file — `--mode=grid` shrinks the payload under a byte budget without losing any fidelity in the final artifacts. The `compaction.applied` list reports which tiers fired:

- **`trim`** (always) — phantom blank rows/columns beyond the real used range are dropped. Interior blanks are kept, so a cell's column position still maps to its column letter.
- **`round_floats`** — float cells are rounded to 8 significant figures (precision you don't need to detect block/column structure).
- **`elide_rows`** — for a tall block, only the first 40 and last 10 rows are kept. **When a sheet is elided it carries `"indexed": true`,** and its `rows` become objects rather than bare arrays:
  - a kept row is `{"r": <1-based spreadsheet row number>, "c": [cell, cell, ...]}`
  - the gap is one marker `{"elided": <count>, "rows": "<first>-<last>"}`

  For an `indexed` sheet, read the row number from `r` (not from array position) and assume the elided rows continue the same columns/pattern — so a holder block that visibly runs from `r: 5` through a `{"elided": 850, "rows": "55-904"}` marker to `r: 905` has `cell_range` `A5:…905`. For a non-indexed sheet, rows are positional starting at row 1 as before.

If the workbook cannot be compacted under budget, `--mode=grid` returns `{"ok": false, "blocker": "grid_too_large", ...}` (exit 1) instead of overflowing — split the workbook into per-sheet files and run `--mode=grid` on each (merge the returned blocks), or reconstruct conversationally via Lane 4.

## Dispatch Context A — `SPREADSHEET_STRUCTURE_DETECTION`

The sub-agent identifies which blocks of cells encode founders / preferred / options / convertibles, since the structure is not deterministic. `OUTPUT_PATH` is the relative `$HANDOFF_AGENT` namespace — never an absolute `/sessions/...` path. Copy the invocation below **whole** — the `subagent_type` is part of it:

```
Task(
  subagent_type="founder-skills:cap-table",   # REQUIRED — omitting it silently downgrades the dispatch to the wildcard, shell-capable general-purpose agent
  prompt="""
CONTEXT: SPREADSHEET_STRUCTURE_DETECTION
OUTPUT_PATH: <HANDOFF_AGENT>/structure_detection_output.json
RUN_ID: <RUN_ID>

You are the cap-table agent dispatched in Context A (SPREADSHEET_STRUCTURE_DETECTION).
Sheet structure + cell grid (compacted to fit the control frame):

<paste the full --mode=grid JSON — sheets + the compaction block>

The grid is size-compacted. A sheet with "indexed": true has rows as objects:
{"r": <1-based row number>, "c": [cells...]} for kept rows, plus one
{"elided": <n>, "rows": "<a>-<b>"} marker for collapsed middle rows — use `r`
for row numbers and treat an elided span as a continuation of the same block
(its cell_range spans across the marker). A sheet without "indexed" has positional
rows starting at row 1, as usual.

Use your Write tool to write to OUTPUT_PATH the {blocks: [{block_type, sheet,
cell_range, column_role_map, confidence, evidence, ambiguities}]} shape.
cell_range MUST use true spreadsheet row numbers. block_type and every
column_role_map VALUE MUST come from references/schemas/freeform-role-map.json
(closed vocabulary). SCAN THE WHOLE SHEET, top to bottom — a financing-instrument
section (Convertible Notes, SAFEs) or an option-pool block often sits BELOW the
main holder table, sometimes under a printed "Total"/"Subtotal" row. Emit a block
for every such section; do not stop at the first table. Then return ONLY the
receipt JSON in your final assistant message:
{"status": "complete", "output_path": "<echo of OUTPUT_PATH>"}
Do not write artifacts anywhere else.
"""
)
```

**Before dispatching, confirm the prompt carries the LITERAL `--mode=grid` JSON** (the `sheets` + `compaction` block from the step above), pasted verbatim — not a paraphrase, summary, or hand-retyped grid. Re-typing or condensing the grid introduces row-number errors that don't fail here but surface later as `--mode=freeform-emit` validator blockers, forcing a full repair round-trip. Paste, never retype.

After the sub-agent returns, gate the hand-off per the Context A hand-off protocol in SKILL.md Step 0 (`check_handoff.py`, branch on exit code).

**Prerequisite:** Step 2 must already have written `inputs.json` with company meta. For a
freeform sheet that carries founders/pool/preferred, write the **minimal** Step-2
`inputs.json` (company_name, analysis_date, mode, jurisdiction, metadata — NO founders /
option_pool / preferred_series): the producer below fills those equity sections from the
sheet, so seeding placeholders would just conflict.

## Map deterministically via `extract_cap_table.py --mode=freeform-emit`

Pipe the sub-agent's `{blocks:[...]}` hand-off file **verbatim on stdin** — do not reshape, re-key,
or re-summarize it. The producer builds the cell grid from the xlsx, maps each block (per the
role-map contract) to schema-valid `inputs.json` (equity, merged into the Step-2 file) +
`instruments.json` (SAFEs/notes), and writes both **only** when there are no blockers. No
heredoc-authored artifacts — the mapping is deterministic.

```bash
cat "$HANDOFF_DIR/structure_detection_output.json" | python3 "$SCRIPTS/extract_cap_table.py" \
  --mode=freeform-emit --xlsx "$XLSX_PATH" --dir "$REVIEW_DIR" --run-id "$RUN_ID" --pretty
```
<!-- skill-quality-ci: bash-after-subagent-ok -->

- `{"ok": true, "warnings": [...]}` → `inputs.json` + `instruments.json` written (schema-validated).
  **Surface any `warnings` in the output as one-line NON-blocking notes in your final presentation** — e.g.
  the discount rate→multiplier conversion (`"SAFE 'Acme Ventures': Carta discount 0.2 (= 20%) converted to
  multiplier 0.8000"`) or a sentinel issuance date — so the founder sees how each value was interpreted and
  can catch a mis-entry (a freeform `discount` is read as a RATE per the role-map convention; the freeform
  path has no separate invariant backstop on it, so this note IS the check). These are transparency notes,
  not gates — never raise an `AskUserQuestion` for them. Done.
  - The sheet's own printed grand total becomes `stated_totals.fully_diluted`, which the later reconciliation
    cross-foots against the computed fully-diluted. If that raises **`W_FD_RECONCILE_DELTA`**, first decompose
    the delta against each cap_state component (common, preferred, options, warrants) before treating it as a
    dropped/mis-entered holder: a source "Total FD" column that lists only common + preferred (excluding the
    option pool) is a **basis mismatch**, not an extraction error — attribute it as such in your presentation.
- `{"ok": false, "blockers": [...]}` → a **gate** (exit 0, nothing written). Each blocker is
  a field the sheet cannot supply deterministically (e.g. a note's `interest_rate_type`, a
  preferred series' `original_issue_price`, an option pool's enum `plan_type`) or an
  off-contract role. This is intentional — freeform is the most error-prone input, so the
  Lane-3 gate is human-in-the-loop.

## Resolve blockers with the founder, then re-emit

Batch the **blockers** into ONE `AskUserQuestion`. Any `warnings` in the same response are
transparency notes (e.g. the discount rate→multiplier conversion) — show them inline as context,
NOT as gate questions (same rule as the `ok:true` branch above). Feed the founder's answers back
as repeatable `--answer BLOCK.FIELD=VALUE` flags (the producer validates each against the field's
declared type — enum, numeric, or bool, per `answerable_blocker_fields` in
`freeform-role-map.json`) and re-run the same command — it is pure over (blocks, answers), so
re-emitting is deterministic. A numeric field (`original_issue_price`) or a `bool` field
(`pricing_unknown`) is just as answerable as an enum field — e.g.
`--answer 1.original_issue_price=1.175` or `--answer 1.pricing_unknown=true` when the founder
genuinely has no historical per-series price (see the "pricing unknown" note below):

```bash
cat <<'FREEFORM_EOF' | python3 "$SCRIPTS/extract_cap_table.py" \
  --mode=freeform-emit --xlsx "$XLSX_PATH" --dir "$REVIEW_DIR" --run-id "$RUN_ID" \
  --answer 0.interest_rate_type=fixed_numeric_simple \
  --answer 1.plan_type=iso --pretty
<JSON extracted from sub-agent reply>
FREEFORM_EOF
```

Never fabricate a blocked field to get past the gate; if the founder cannot confirm one,
name the assumption in the final presentation and emit a counsel item (per the EXTRACTION
CONFIRM-GATE in SKILL.md). Warrants and individual option grants are not mapped from
freeform (hard-blocked) — collect those via Lane 1 or conversationally.

## Pricing unknown (no historical per-series price)

A founder's own sheet often tracks share counts, not the price each series was actually
issued at. `original_issue_price` is required and must be a positive number — never
fabricate a placeholder (e.g. a silent `$1.00`) to force the block through. Instead, when
the founder confirms they genuinely don't have the historical price, resolve the blocker
with `--answer <block_index>.pricing_unknown=true`. This writes the numeric sentinel
`original_issue_price = original_conversion_price = current_conversion_price = 1.0`,
forces `anti_dilution_protection = "none"`, and stamps `pricing_unknown: true` on the
series so downstream disclosure/counsel logic can flag that (a) anti-dilution and
liquidation preference are NOT modeled for that series and (b) the conversion ratio is
assumed 1:1 (no historical down-round adjustment). Surface both points to the founder in
your final presentation — do not treat `pricing_unknown` as silently equivalent to a known
1:1 series.
