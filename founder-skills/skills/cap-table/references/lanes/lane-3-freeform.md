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
