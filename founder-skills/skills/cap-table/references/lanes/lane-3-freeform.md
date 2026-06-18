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

The output is JSON to stdout (`{"ok": true, "mode": "grid", "sheets": {...}}`). Paste the full JSON into the dispatch prompt below.

## Dispatch Context A — `SPREADSHEET_STRUCTURE_DETECTION`

The sub-agent identifies which blocks of cells encode founders / preferred / options / convertibles, since the structure is not deterministic.

```
CONTEXT: SPREADSHEET_STRUCTURE_DETECTION
REVIEW_DIR: <absolute path>
RUN_ID: <RUN_ID>

You are the cap-table agent dispatched in Context A (SPREADSHEET_STRUCTURE_DETECTION).
Sheet structure + cell grid:

<paste the sheet data — sheet name, dimensions, cell values per row>

Return JSON only — the {blocks: [{block_type, sheet, cell_range,
column_role_map, confidence, evidence, ambiguities}]} shape. block_type and every
column_role_map VALUE MUST come from references/schemas/freeform-role-map.json
(closed vocabulary). Do not write artifacts.
```

After the sub-agent returns, apply the tolerant JSON extraction protocol.

**Prerequisite:** Step 2 must already have written `inputs.json` with company meta. For a
freeform sheet that carries founders/pool/preferred, write the **minimal** Step-2
`inputs.json` (company_name, analysis_date, mode, jurisdiction, metadata — NO founders /
option_pool / preferred_series): the producer below fills those equity sections from the
sheet, so seeding placeholders would just conflict.

## Map deterministically via `extract_cap_table.py --mode=freeform-emit`

Pipe the sub-agent's `{blocks:[...]}` to the producer. It builds the cell grid from the
xlsx, maps each block (per the role-map contract) to schema-valid `inputs.json` (equity,
merged into the Step-2 file) + `instruments.json` (SAFEs/notes), and writes both **only**
when there are no blockers. No heredoc-authored artifacts — the mapping is deterministic.

```bash
cat <<'FREEFORM_EOF' | python3 "$SCRIPTS/extract_cap_table.py" \
  --mode=freeform-emit --xlsx "$XLSX_PATH" --dir "$REVIEW_DIR" --run-id "$RUN_ID" --pretty
<JSON extracted from sub-agent reply>
FREEFORM_EOF
```

- `{"ok": true, ...}` → `inputs.json` + `instruments.json` written (schema-validated). Done.
- `{"ok": false, "blockers": [...]}` → a **gate** (exit 0, nothing written). Each blocker is
  a field the sheet cannot supply deterministically (e.g. a note's `interest_rate_type`, a
  preferred series' `original_issue_price`, an option pool's enum `plan_type`) or an
  off-contract role. This is intentional — freeform is the most error-prone input, so the
  Lane-3 gate is human-in-the-loop.

## Resolve blockers with the founder, then re-emit

Batch the blockers (plus any `warnings`) into ONE `AskUserQuestion`. Feed the founder's
answers back as repeatable `--answer BLOCK.FIELD=VALUE` flags (the producer validates each
against the field's enum) and re-run the same command — it is pure over (blocks, answers),
so re-emitting is deterministic:

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
