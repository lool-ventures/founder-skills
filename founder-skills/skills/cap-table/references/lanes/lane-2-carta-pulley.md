# Lane 2 — Carta / Pulley XLSX export

Typical input: a multi-sheet XLSX export (Securities, Convertibles, Stakeholders).

## Run the extractor

```bash
python3 "$SCRIPTS/extract_cap_table.py" --mode=carta --xlsx "$XLSX_PATH" \
  -o "$REVIEW_DIR/extraction_audit.json" --pretty
```

For Pulley, swap `--mode=carta` → `--mode=pulley`.

## How vendor detection works

`extract_cap_table.py` reads the XLSX sheet-name fingerprint and column headers, then looks up the mapping in `references/carta-pulley-mapping.md`. The mapping defines per-vendor:

- Sheet names that must be present (e.g., Carta typically ships `Securities` / `Convertibles` / `Stakeholders`)
- Column header → canonical field mapping per sheet
- Convertible-instrument representation conventions (which differ between vendors)

If the fingerprint doesn't match either vendor profile, the script routes to Lane 3 (freeform) automatically — you don't need to detect this manually.

## Confirming ambiguous mappings

When the script flags a column it can't confidently map (e.g., a custom Stakeholder-class column the vendor didn't define in their default export), it returns the candidates in `extraction_audit.json.ambiguous_columns`. Present these via `AskUserQuestion` and re-run the script with `--column-overrides` (one per `sheet:column → canonical_field` pair) until the audit is clean.

## Don't assume — verify the fingerprint

Both Carta and Pulley ship multi-sheet XLSX exports, but the sheet names, column ordering, and convertible-instrument representations are NOT interchangeable. A spreadsheet that *looks* like a Carta export but uses Pulley's column conventions will silently mis-map fields under the wrong `--mode`. The script will refuse to run if the fingerprint doesn't match the declared mode.

## After ingestion

The script emits `instruments.json` + `cap_state.json` directly (no sub-agent dispatch needed for known vendor profiles). Skip ahead to **Step 4** in the main workflow (`cap_state.py` validation).
