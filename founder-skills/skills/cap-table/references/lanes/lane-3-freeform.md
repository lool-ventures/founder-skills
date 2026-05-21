# Lane 3 — Freeform spreadsheet

Typical input: a founder's own Excel file with arbitrary structure — not Carta, not Pulley, no fixed schema.

## Extract the cell grid

The Python helper reads the workbook and emits the cell grid + sheet structure:

```bash
python3 "$SCRIPTS/extract_cap_table.py" --mode=freeform_extract --xlsx "$XLSX_PATH" \
  -o "$REVIEW_DIR/.staging/cell_grid.json" --pretty
```

The grid contains, per sheet: sheet name, dimensions, cell values per row, and any merged-cell ranges.

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
column_role_map, confidence, evidence, ambiguities}]} shape.
Do not write artifacts.
```

After the sub-agent returns, apply the tolerant JSON extraction protocol.

## Validate via `extract_cap_table.py --mode=freeform`

```bash
cat <<'FREEFORM_EOF' | python3 "$SCRIPTS/extract_cap_table.py" \
  --mode=freeform -o "$REVIEW_DIR/extraction_audit.json" --pretty
<JSON extracted from sub-agent reply>
FREEFORM_EOF
```

The validation gate enforces per-field confidence before commit.

## Confirm with the founder before commit

Present `low_confidence_blocks` + `ambiguities` to the founder via `AskUserQuestion`. Once confirmed, write the founder-confirmed `instruments.json` directly via heredoc — the Lane 3 confidence gate is intentionally human-in-the-loop because freeform spreadsheets are the most error-prone input format.
