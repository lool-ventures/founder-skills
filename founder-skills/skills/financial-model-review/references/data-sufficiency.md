# Data Sufficiency Gate

After extracting available data, count critical fields missing from source material.

**Core fields (all revenue models):** `current_balance`, `monthly_net_burn`, `gross_margin`

**Model-specific fields:**
- SaaS / AI-native / usage-based: `mrr`, `growth_rate_monthly`, `cac`
- Marketplace: `gmv` or `take_rate`, `growth_rate_monthly`
- Hardware / hardware-subscription: `unit_cost`, `asp`, `growth_rate_monthly`
- Consumer-subscription: `mrr` or `subscriber_count`, `growth_rate_monthly`, `cac`

Count = missing core fields + missing model-specific fields (using `sector_type` to select the set).

If **3+ total fields are missing** and, after genuinely looking, the source (any `model_format` — `deck`, `conversational`, or a `spreadsheet` that simply lacks them) verifiably does not contain them:

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
- **unit_economics.py**: Deposit stub: `{"skipped": true, "reason": "Insufficient quantitative data for unit economics computation", "metadata": {"run_id": "<RUN_ID>"}}`
- **runway.py**: Deposit stub: `{"skipped": true, "reason": "Insufficient quantitative data for runway projection", "metadata": {"run_id": "<RUN_ID>"}}`
- **compose_report.py** and **visualize.py**: Handle stubs gracefully (already supported via `_is_stub()`)

Always set `data_confidence: "estimated"` in `inputs.json` (agent-estimated values from indirect signals). Stubs carry no `data_confidence` — it lives in `inputs.json` and compose_report reads it from there.

## Gate contract

This file — **not the script source** — is the contract of record for what `verify_review.py`'s gate errors and warnings mean. Both quantitative producers self-declare insufficiency, and the gate treats that self-declaration as **accept-with-warning**, not as a failure:

- **unit_economics.py** — when fewer than two metrics are computable it sets `insufficient_data: true`; the gate then passes (exit 0) with a partial-data **warning**. A hard "too few computed metrics" **error** means the artifact predates that flag (stale / hand-authored) — re-run the producer from `inputs.json`.
- **runway.py** — when no scenario has a non-null `runway_months` it sets its insufficiency flag; the gate passes with a **warning**. A hard "no runway scenario" **error** likewise means a stale artifact — re-run the producer.

Accept-with-warning is the honest-degradation route: record the warning in the report narrative and proceed. **Never fabricate a value to clear a gate, and never read the producer or `verify_review.py` source to debug one** — re-run the producer, or fall back to the Qualitative Path above.
