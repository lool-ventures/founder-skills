# Data Sufficiency Gate

After extracting available data, count critical fields missing from source material.

**Core fields (all revenue models):** `current_balance`, `monthly_net_burn`, `gross_margin`

**Model-specific fields:**
- SaaS / AI-native / usage-based: `mrr`, `growth_rate_monthly`, `cac`
- Marketplace: `gmv` or `take_rate`, `growth_rate_monthly`
- Hardware / hardware-subscription: `unit_cost`, `asp`, `growth_rate_monthly`
- Consumer-subscription: `mrr` or `subscriber_count`, `growth_rate_monthly`, `cac`

Count = missing core fields + missing model-specific fields (using `sector_type` to select the set).

If **3+ total fields are missing** AND `model_format` is `deck` or `conversational`:

**If running non-interactively** (invoked as a command with a file argument, or founder is not in the conversation):
- Proceed directly to the Qualitative Path below — do NOT estimate missing financial values.

**If running interactively** (conversation with founder):
1. List the missing fields to the founder
2. Ask: "Can you provide these numbers, even rough estimates?"
3. If yes → founder provides data, set `data_confidence: "mixed"` in `inputs.json`
4. If no → proceed with qualitative path (see below)

## Qualitative Path (insufficient quantitative data)

When the founder cannot provide missing critical data:

- **checklist.py**: Always run (qualitative assessment works without financials)
- **unit_economics.py**: Deposit stub: `{"skipped": true, "reason": "Insufficient quantitative data for unit economics computation"}`
- **runway.py**: Deposit stub: `{"skipped": true, "reason": "Insufficient quantitative data for runway projection"}`
- **compose_report.py** and **visualize.py**: Handle stubs gracefully (already supported via `_is_stub()`)

Always set `data_confidence: "estimated"` in `inputs.json` (agent-estimated values from indirect signals). Stubs carry no `data_confidence` — it lives in `inputs.json` and compose_report reads it from there.
