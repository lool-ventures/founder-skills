# Lane 4 — Structured JSON paste / conversational

Typical inputs:
- The founder pastes pre-built JSON describing their cap-table (rare but happens with technical founders or when porting from another tool).
- The founder describes their cap-table conversationally and the main thread reconstructs the structure via targeted `AskUserQuestion`s.

## Path A — Founder pasted JSON

Write directly to `$REVIEW_DIR/instruments.json` via heredoc, then validate:

```bash
cat <<'INSTRUMENTS_EOF' > "$REVIEW_DIR/instruments.json"
<the JSON the founder pasted>
INSTRUMENTS_EOF

python3 "$SCRIPTS/extract_cap_table.py" --mode=validate --dir "$REVIEW_DIR"
```

If validation fails, surface the errors to the founder via `AskUserQuestion` and iterate.

## Path B — Conversational reconstruction

Build the structure via targeted `AskUserQuestion` calls. The minimum field set per instrument type is documented in `references/schemas/instruments.schema.json`. Common conversational patterns:

- **Founders + common stock**: ask name, share count, vesting status. Multiple founders → repeat.
- **SAFE**: ask form (cap-only / cap+discount / discount-only / uncapped-MFN / pre-money legacy), `purchase_amount`, `valuation_cap`, `discount_multiplier`, `issuance_date`, `investor_name`.
- **Convertible note**: `principal_amount`, `interest_rate` (or statutory ITA Section 3(j) for Israeli notes), `maturity_date`, `valuation_cap`, `discount_multiplier`, `maturity_default_treatment`.
- **Option pool**: total authorized, options granted, options available, plan_type (`section_102_*` / `section_3i` for Israel; `iso` / `nso` for US).

Heredoc the result and validate as in Path A.

## Why Lane 4 exists

Many founders don't have a clean Carta export and don't want to dig out the PDF. The conversational path is the lowest-friction onboarding — keep it sympathetic: ask only what the next scenario actually needs, not the full schema. The `priced_round` scenario, for instance, needs the option-pool numbers but not vesting schedules.
