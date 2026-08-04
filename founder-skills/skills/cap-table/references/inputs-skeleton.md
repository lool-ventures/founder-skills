# inputs.json — common-case shape

The skill's SKILL.md Step 2 shows a minimal `inputs.json` heredoc that omits `founders`, `common_batches`, `preferred_series`, and `option_pool`. Those blocks are optional in `inputs.schema.json`, but **`cap_state.py` and most downstream rules need them to produce meaningful output**. Omitting the equity base entirely no longer passes silently: with instruments present and none of `founders`, `common_batches`, `preferred_series` or `option_pool`, `cap_state.py` hard-errors `E_NO_EQUITY_BASE` (exit 1) rather than computing an all-zero base for conversions to divide into. So a missing base STOPS the run — it does not produce plausible-looking zeros, and it is never a reason to invent founders or share counts. A single instrument with no surrounding cap table is the expected case for this and takes the **no-cap-base fork** in Step 2.

This reference shows the full common-case shape. Copy-and-fill for any engagement where someone actually owns shares.

## Validator strictness gotcha

`extract_cap_table.py --mode=validate` and the underlying `inputs.schema.json` do **not** declare `additionalProperties: false` at the root or on most sub-blocks. **Unknown top-level keys are silently dropped, without warning.** Common name-confusion pitfalls:

| Industry-conventional name | What this schema uses |
|---|---|
| `stakeholders[]` (Carta / Pulley) | `founders[]` |
| `option_pool.authorized_shares` | `option_pool.authorized` (bare, no `_shares`) |
| `option_pool.issued_shares` | `option_pool.issued` |
| `option_pool.unallocated_shares` | `option_pool.unallocated` |
| `option_pool.plan_type: "delaware_eip"` / `"none"` | `option_pool.plan_type: "iso"` (no enum exists for empty pool yet) |

If the validator passes but `cap_state.py` reports "founders: 0" or "preferred-as-converted: 0" against your expectation, suspect a name mismatch and re-check the keys.

## Minimal complete inputs.json (Delaware C-corp, single founder, empty pool, no preferred)

```json
{
  "company_name": "Example Corp",
  "analysis_date": "2026-05-21",
  "mode": "standard",
  "jurisdiction": {
    "structure": "delaware",
    "incorporated_date": "2024-06-01",
    "iia_grants_history": {"has_grants": false, "grant_details": []}
  },
  "event_dates": {
    "restructuring_effective_date": null,
    "restructuring_approval_date": null,
    "filing_date": null,
    "tax_position_date": null,
    "flip_closing_date": null,
    "benchmark_reference_date": null
  },
  "founders": [
    {"name": "Founder A", "founder_id": "founder_a", "common_shares": 10000000}
  ],
  "option_pool": {
    "plan_type": "iso",
    "authorized": 1500000,
    "issued": 0,
    "unallocated": 1500000
  },
  "engagement_questions": [],
  "metadata": {"run_id": "20260521T120000Z", "schema_version": "v0.5.0-inputs"}
}
```
**`incorporated_date` above is a PLACEHOLDER, not a default.** If the founder has not stated the date,
**delete that line** — `jurisdiction` has no `required` array, so omitting the key is schema-valid, while
`null` is not (the field is typed `string`). Ask for it when the engagement touches QSBS or §102 timing;
otherwise omit it and say so. A live run copied `2024-06-01` straight out of this example for a company
whose founder never gave a date, then drove a QSBS holding-period item off it — the same never-fabricate
rule as `issuance_date` applies here.

## Adding preferred-series (Series Seed BBWA, no prior AD)

Insert this block before `option_pool`:

```json
  "preferred_series": [
    {
      "series_id": "series_seed",
      "series_name": "Series Seed",
      "shares": 2000000,
      "original_issue_price": 1.00,
      "original_conversion_price": 1.00,
      "current_conversion_price": 1.00,
      "issuance_date": "2024-06-01",
      "liquidation_preference_multiple": 1.0,
      "liquidation_preference_type": "non_participating",
      "participation_cap_multiple": null,
      "anti_dilution_protection": "broad_based_weighted_average",
      "pro_rata_rights": true
    }
  ],
```

**Anti-dilution field (don't get this wrong — it drives the down-round adjustment).** The key is
`anti_dilution_protection`, and its value MUST be one of the canonical enum
`none | broad_based_weighted_average | narrow_based_weighted_average | full_ratchet` — NOT a shorthand
like `anti_dilution`/`bbwa`/`ratchet`. A wrong key or abbreviation that lands as `none` would silently
skip the anti-dilution math a founder asked for. `cap_state.py` recovers common slips and emits a
`W_ANTI_DILUTION_NONCANONICAL` warning so nothing is dropped silently, but write the canonical field
directly.

### Why three price fields

- `original_issue_price` (OIP) — per-share consideration investors paid. The NVCA model trigger is the conversion price in effect immediately prior (CP1); the OIP trigger is a charter-specific variant this pipeline uses as its soft default — counsel confirms which the charter adopts.
- `original_conversion_price` (OCP) — drives the as-converted ratio. `preferred_shares_as_converted = shares × OCP / CCP` in `cap_state.py:_compute_as_converted_totals`.
- `current_conversion_price` (CCP) — the present conversion price. Equals OCP unless anti-dilution has previously triggered (CCP then < OCP).

For a fresh issuance with no prior AD: **OIP = OCP = CCP**. All three are required.

## Adding common_batches (rare; advisor common, exercised options)

Insert this block after `founders`:

```json
  "common_batches": [
    {
      "holder_id": "advisor_jdoe",
      "shares": 100000,
      "issuance_date": "2024-09-01",
      "consideration": 100.0,
      "purpose": "restricted_stock_purchase"
    }
  ],
```

Omit the whole `common_batches` array if not applicable. `purpose` enum: `founder_issuance | restricted_stock_purchase | exercise | conversion | other`.

**Field-name discipline (avoids the recurring schema-thrash):** the holder reference is **`holder_id`** — there is **no `batch_id`** field on `common_batches` (a common mis-key; using `batch_id` is silently ignored / fails validation depending on the field). The only canonical item fields are: `holder_id`, `shares`, `issuance_date`, `consideration`, `purpose`, `common_class`, `voting_rights_multiple`. Warrants are **NOT** a top-level `inputs.json` array — they live in `instruments.json` (`warrants[]`); do not add a `warrants` key to `inputs.json`. `option_pool.plan_type` must be one of the §102/jurisdiction enums below — `iso | nso | section_102_cg | section_102_oi | section_3i | mixed` (not `102_cg` / `israeli_102` / `none`).

**`option_grants[]` — usually leave it EMPTY.** Individual option grants live in `instruments.json` `option_grants[]`, NOT `inputs.json`. You almost never need them: the **`option_pool` aggregate** (authorized / issued / unallocated) in `inputs.json` already captures the pool for cap-table math. Only populate `option_grants[]` for genuine per-grant detail (e.g. a specific §102 grant's vesting/tax analysis). In **Lane 3 (freeform)** individual grants are **not supported** — use an `option_pool_block`. If you DO build a grant, the required fields are exactly `id, holder_id, grant_date, shares_granted, strike_price, plan_type` (NOT `quantity` / `exercise_price` / `name` — those mis-keys fail validation). `strike_price` may be `null` ONLY when the source genuinely does not state it — the grant persists as a partial and `cap_state.py` emits `W_OPTION_GRANT_STRIKE_MISSING`; never fabricate a strike. When in doubt, write `"option_grants": []` and rely on the pool aggregate. **Flip carve-out:** when `mode=flip_focused` or a flip scenario is requested and the pool has issued grants, DO populate `option_grants[]` per holder with `plan_type` (tax route) and `grant_date` (+ `section_102_trustee_deposit_date` when known) even when `strike_price` is undisclosed (`null`) — §102 continuity analysis reads per-grant `plan_type`, not the pool aggregate, so an empty `option_grants[]` reports zero §102 grants. **Ordering:** populate `option_grants[]` AFTER any Lane-3 freeform emit for the same workspace — `--mode=freeform-emit` writes `instruments.json` wholesale (it does not merge existing instrument arrays), so grants authored before it are silently dropped.

## Option-pool plan_type by jurisdiction

| Jurisdiction | Typical plan_type |
|---|---|
| Delaware C-corp, ISO-eligible | `iso` |
| Delaware C-corp, NQSO-only | `nso` |
| Israeli, capital-gains track | `section_102_cg` |
| Israeli, ordinary-income track | `section_102_oi` |
| Israeli, non-employees | `section_3i` |
| Multi-track | `mixed` |

There is **no enum value for "no plan adopted yet" / "unallocated authorized"**. For a Delaware engagement with authorized-but-no-grants pool, use `iso` as the intended-tax-treatment placeholder.

## Cross-references

- Full schema: [`schemas/inputs.schema.json`](schemas/inputs.schema.json)
- Lane 1 (PDF / DOCX extraction): [`lanes/lane-1-pdf-docx.md`](lanes/lane-1-pdf-docx.md)
- Lane 4 (structured paste / conversational): [`lanes/lane-4-structured.md`](lanes/lane-4-structured.md)
- AoA extraction populates `preferred_series`: see `extract_aoa.py --inputs` for the merge path
