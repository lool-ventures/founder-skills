# Financial Model Review — Output Schemas

JSON schemas for script-produced artifacts. For input schemas (what the agent writes), see `schema-inputs.md`.

---

## model_data.json

**Producer:** `extract_model.py`

Structured extraction of the spreadsheet contents for downstream analysis.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `sheets` | object[] | yes | Per-sheet extraction |
| `source_format` | string | yes | One of: `"xlsx"`, `"csv"` |
| `source_file` | string | yes | Original filename |
| `periodicity_summary` | string | yes | One of: `"monthly"`, `"quarterly"`, `"annual"`, `"mixed"`, `"unknown"`. `"mixed"` when sheets have different periodicities. |

### sheets[] entry

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | yes | Sheet/tab name |
| `headers` | string[] | yes | Column headers detected |
| `rows` | any[][] | yes | Row data (mixed types) |
| `detected_type` | string \| null | yes | One of: `"assumptions"`, `"revenue"`, `"expenses"`, `"cash"`, `"pnl"`, `"summary"`, `"scenarios"`, or `null` if unclassified |
| `periodicity` | string | yes | One of: `"monthly"`, `"quarterly"`, `"annual"`, `"unknown"`. Detected from column headers via regex and majority vote. |
| `row_count` | integer | yes | Number of data rows |
| `col_count` | integer | yes | Number of columns |
| `pre_header_rows` | any[][] | yes | Rows before the detected header row (xlsx: rows above header containing company name, logos, etc.; csv: always empty `[]`). `validate_extraction.py` treats a missing key as `[]` for backward compatibility with older model_data files. |
| `cell_refs` | object[] | yes | List of row-level cell coordinate mappings. Each entry: `{"row_index": N, "label": "Revenue", "cols": {"Jan 2025": "B3"}}`. `row_index` is the position in `rows[]` (stable key — labels can duplicate). Only rows with numeric cells are included. xlsx: populated from openpyxl cell coordinates; csv: always `[]`. Used by `validate_extraction.py` for best-match provenance (value-based lookup, not authoritative for duplicate values). Missing key treated as `[]` for backward compatibility. |

**Example:**
```json
{
  "sheets": [
    {
      "name": "Assumptions",
      "headers": ["Parameter", "Value", "Source", "Notes"],
      "rows": [["Monthly churn", 0.03, "Industry avg", "Conservative"]],
      "detected_type": "assumptions",
      "periodicity": "monthly",
      "row_count": 45,
      "col_count": 4
    }
  ],
  "source_format": "xlsx",
  "source_file": "acme-financial-model.xlsx",
  "periodicity_summary": "monthly"
}
```

---

## checklist.json

**Producer:** `checklist.py` (from agent-provided JSON input)

### Input format (stdin to checklist.py)

```json
{
  "company": {
    "stage": "seed",
    "geography": "israel",
    "sector": "saas",
    "traits": ["multi-currency", "multi-entity"]
  },
  "items": [
    {
      "id": "STRUCT_01",
      "status": "pass",
      "evidence": "Dedicated 'Assumptions' tab with color-coded inputs",
      "notes": "All key assumptions isolated and clearly labeled"
    }
  ]
}
```

The `company` block is used for gate evaluation. Items whose gate doesn't match the company profile are auto-scored as `not_applicable` regardless of the agent's assessment.

### Output format

| Field | Type | Description |
|-------|------|-------------|
| `items` | object[] | All 46 items enriched with category and label |
| `summary` | object | Aggregate scores and status |

### items[] entry (output)

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Criterion ID (e.g., `"STRUCT_01"`) |
| `category` | string | Category name |
| `label` | string | Human-readable label |
| `status` | string | `"pass"`, `"fail"`, `"warn"`, or `"not_applicable"` |
| `evidence` | string \| null | Evidence or observation supporting the assessment |
| `notes` | string \| null | Agent's assessment notes |

### summary

| Field | Type | Description |
|-------|------|-------------|
| `total` | integer | Always 46 |
| `pass` | integer | Count of passing items |
| `fail` | integer | Count of failing items |
| `warn` | integer | Count of warning items |
| `not_applicable` | integer | Count of N/A items |
| `score_pct` | float | (pass + 0.5 * warn) / (total - not_applicable) * 100 |
| `overall_status` | string | `"strong"` (>=85%), `"solid"` (>=70%), `"needs_work"` (>=50%), `"major_revision"` (<50%) |
| `by_category` | object | Per-category counts: `{"Category Name": {"pass": 0, "fail": 0, "warn": 0, "not_applicable": 0}}` |
| `failed_items` | object[] | List of failed items with `id`, `category`, `label`, `evidence`, `notes` |
| `warned_items` | object[] | List of warned items with `id`, `category`, `label`, `evidence`, `notes` |

---

## unit_economics.json

**Producer:** `unit_economics.py`

Computed unit economics metrics with benchmark ratings.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `metrics` | object[] | yes | Array of computed metric entries |
| `summary` | object | yes | Rating distribution counts |

### metrics[] entry

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | yes | Metric name: `"cac"`, `"ltv"`, `"ltv_cac_ratio"`, `"cac_payback"`, `"burn_multiple"`, `"magic_number"`, `"gross_margin"`, `"nrr"`, `"grr"`, `"rule_of_40"`, `"arr_per_fte"` |
| `value` | number \| null | yes | Computed value, or `null` if insufficient data |
| `rating` | string | yes | One of: `"strong"`, `"acceptable"`, `"warning"`, `"fail"`, `"not_rated"`, `"contextual"`, `"not_applicable"` |
| `evidence` | string | yes | Human-readable explanation of the rating |
| `benchmark_source` | string | yes | Source of the benchmark used (empty string if none) |
| `benchmark_as_of` | string | yes | Date of the benchmark data (empty string if none) |
| `confidence` | string | no | `"exact"`, `"estimated"`, or `"mixed"`. Present only on rated metrics when `data_confidence` is not `"exact"` |

### summary

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `computed` | integer | yes | Number of metrics with non-null values |
| `strong` | integer | yes | Count of `"strong"` ratings |
| `acceptable` | integer | yes | Count of `"acceptable"` ratings |
| `warning` | integer | yes | Count of `"warning"` ratings |
| `fail` | integer | yes | Count of `"fail"` ratings |
| `not_rated` | integer | yes | Count of `"not_rated"` ratings |
| `contextual` | integer | yes | Count of `"contextual"` ratings |
| `not_applicable` | integer | yes | Count of `"not_applicable"` ratings |

---

## runway.json

**Producer:** `runway.py`

Cash runway projections across scenarios with decision-point analysis.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `company` | object | yes | Company identifier (`name`, `slug`, `stage`) |
| `baseline` | object \| null | yes | Current cash and burn snapshot (null when data insufficient) |
| `scenarios` | object[] | yes | Array of scenario projection results |
| `post_raise` | object \| null | no | Post-fundraise projections (null when no fundraising data) |
| `risk_assessment` | string | yes | Human-readable risk assessment based on base scenario |
| `limitations` | string[] | yes | Modeling limitations and assumptions |
| `warnings` | string[] | yes | Data quality or consistency warnings |
| `data_confidence` | string | no | `"exact"`, `"estimated"`, or `"mixed"`. Present only when not `"exact"` |
| `insufficient_data` | boolean | no | Present and `true` when cash/burn data is missing; all other fields will be null/empty |

### baseline

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `net_cash` | number | yes | Current cash minus debt |
| `monthly_burn` | number | yes | Monthly net burn rate |
| `monthly_revenue` | number | yes | Monthly revenue used as starting point |

### scenarios[] entry

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | yes | Scenario name |
| `growth_rate` | number | yes | Monthly revenue growth rate used |
| `burn_change` | number | yes | One-time step-up at scenario start |
| `fx_adjustment` | number | yes | FX adjustment on ILS expenses (0.0 if no FX exposure) |
| `runway_months` | integer \| null | yes | Months until cash runs out, or `null` if never within 60 months |
| `cash_out_date` | string \| null | yes | `"YYYY-MM"` projected cash-out, or `null` |
| `decision_point` | string \| null | yes | `"YYYY-MM"` date to begin fundraising (12 months before cash-out), or `null` |
| `default_alive` | boolean | yes | Whether company survives the projection window (reaches profitability OR never runs out of cash) |
| `became_profitable` | boolean | yes | Whether revenue >= expenses at any point during the projection (operational profitability, excludes grant inflows) |
| `monthly_projections` | object[] | yes | Month-by-month projection data |

### monthly_projections[] entry

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `month` | integer | yes | Month number (1-based) |
| `cash_balance` | number | yes | Projected cash balance |
| `revenue` | number | yes | Projected monthly revenue |
| `expenses` | number | yes | Projected monthly expenses |
| `net_burn` | number | yes | Expenses minus revenue |

### post_raise

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `raise_amount` | number | yes | Amount being raised |
| `new_cash` | number | yes | Post-raise cash position (net_cash + raise_amount) |
| `new_runway_months` | integer \| null | yes | Post-raise runway in months (null if never runs out) |
| `new_cash_out_date` | string \| null | yes | `"YYYY-MM"` post-raise cash-out date |
| `meets_target` | boolean | yes | Whether runway meets `bridge.runway_target_months` (default 24) |

---

## report.json

**Producer:** `compose_report.py`

Assembled report from all artifacts with cross-artifact validation.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `report_markdown` | string | yes | Complete review report in markdown format |
| `validation` | object | yes | Cross-artifact validation results |

### validation

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `status` | string | yes | One of: `"clean"`, `"warnings"` |
| `warnings` | object[] | yes | Array of validation warning entries |
| `artifacts_found` | string[] | yes | List of artifact filenames found in the directory |
| `artifacts_missing` | string[] | yes | List of artifact filenames not found |
| `model_format` | string | no | Source format from inputs. Used by `--strict` to contextualize expected warnings. |

### warnings[] entry

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `code` | string | yes | Warning code (e.g., `"MISSING_ARTIFACT"`, `"CHECKLIST_FAILURES"`) |
| `severity` | string | yes | One of: `"high"`, `"medium"`, `"low"` |
| `message` | string | yes | Human-readable warning message |

**Exit codes:**
- `0` — success
- `1` — required artifacts missing (always), or any high/medium warnings in `--strict` mode

---

## commentary.json

Agent-written narrative commentary for the interactive explorer.

```json
{
  "headline": "One-sentence financial health summary shown at top of explorer",
  "investor_talking_points": [
    "Sentence the founder can say out loud during fundraise conversation"
  ],
  "lenses": {
    "runway": {
      "callout": "Key insight about runway (shown in blue box)",
      "highlight": "Secondary observation (shown in grey box)",
      "watch_out": "Risk or concern (shown in amber box)"
    },
    "unit_economics": { "callout": "...", "highlight": "...", "watch_out": "..." },
    "stress_test": { "callout": "...", "highlight": "...", "watch_out": "..." },
    "raise_planner": { "callout": "...", "highlight": "...", "watch_out": "..." }
  }
}
```

**Required fields:**
- `headline` (string) — Required. One-sentence summary displayed at the top of the interactive explorer. If missing, `explore.py` skips commentary entirely.

**Optional fields:**
- `investor_talking_points` (string[]) — Sentences founders can use verbatim during investor conversations.
- `lenses` (object) — Per-lens commentary. Keys match explorer tabs: `runway`, `unit_economics`, `stress_test`, `raise_planner`. Each lens object can have:
  - `callout` — Primary insight (blue box)
  - `highlight` — Secondary observation (grey box)
  - `watch_out` — Risk/concern (amber box)
  All three are optional per lens. Omit a lens key entirely if its required artifacts are missing.

---

## corrections.json (v2 -- patch-based)

**Producer:** Review UI (`review_inputs.py`)
**Consumer:** `apply_corrections.py`

### Payload format (v2)

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `base_hash` | string | yes (v2) | `"sha256:<hex>"` of canonical JSON of original inputs.json. `apply_corrections` rejects patch payloads without it. |
| `changes` | object[] | yes (v2) | Ordered list of field-level patches |
| `warning_overrides` | object[] | no | Warning override entries |
| `ils_fields` | object | no | Map of field paths to `true` for ILS-denominated values |

### changes[] entry

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `path` | string | yes | Dotted path to field (e.g., `"revenue.mrr.value"`) |
| `type` | string | no | `"scalar"` (default) for field-level edits, `"replace_array"` for array mutations (row add/remove). |
| `expected_old` | any | no | For scalar: expected current value. For `replace_array`: expected array length (integer). If present and doesn't match, change is rejected as stale. |
| `new` | any | yes | For scalar: new value. For `replace_array`: the entire replacement array. |

### Legacy format (v1)

Payloads with `"corrected"` key and no `"changes"` key are handled via the legacy path for backward compatibility. The `corrected` object is used directly. This path emits a stderr warning.
