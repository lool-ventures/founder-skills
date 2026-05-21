# Lane 2 — Carta XLSX export

Typical input: a multi-sheet Carta XLSX export (Securities, Convertibles, Stakeholders).

> **Pulley note:** `--mode=pulley` is a stub that returns a structured blocker. Pulley extraction is not yet supported end-to-end (no real Pulley exports available to verify field mappings against). Pulley-style exports route to `--mode=freeform` (Lane 3) instead.

## Run the extractor

```bash
python3 "$SCRIPTS/extract_cap_table.py" --mode=carta --xlsx "$XLSX_PATH" \
  -o "$REVIEW_DIR/extraction_audit.json" --pretty
```

## How vendor detection works

`extract_cap_table.py` reads the XLSX sheet-name fingerprint and column headers and looks up the mapping in `references/carta-pulley-mapping.md`. Carta exports ship `Securities` / `Convertibles` / `Stakeholders` sheets with a specific column convention; the mapping table documents the column-header → canonical-field map.

If the fingerprint doesn't match Carta, the script routes to Lane 3 (freeform) automatically — you don't need to detect this manually. Pulley XLSX exports will route to freeform until the Pulley path is verified end-to-end.

## Confirming ambiguous mappings

When the script flags a column it can't confidently map (e.g., a custom Stakeholder-class column outside the default Carta export), it returns the candidates in `extraction_audit.json.ambiguous_columns`. Present these via `AskUserQuestion` and re-run the script with `--column-overrides` (one per `sheet:column → canonical_field` pair) until the audit is clean.

## Don't assume — verify the fingerprint

The script will refuse to run if the fingerprint doesn't match the declared `--mode`. Carta sheet-name and column conventions are non-trivially distinct from other vendors, so silent mis-mapping is a real risk under the wrong mode.

## After ingestion

The script emits `instruments.json` + `cap_state.json` directly (no sub-agent dispatch needed for Carta). Skip ahead to **Step 4** in the main workflow (`cap_state.py` validation).
