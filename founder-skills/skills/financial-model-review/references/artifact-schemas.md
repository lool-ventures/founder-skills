# Financial Model Review Artifact Schemas

JSON schemas for all artifacts deposited during the financial model review workflow. Each artifact is a JSON file written to the `REVIEW_DIR` working directory (except `model_data.json` which is produced by the extraction script and `visualize.py` which outputs HTML).

---

## Stub Format (skipped artifacts)

When a pipeline step is skipped (e.g., insufficient data for unit economics), deposit a stub instead of the full artifact:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `skipped` | boolean | yes | Always `true` |
| `reason` | string | yes | Human-readable explanation |

Example:

    {"skipped": true, "reason": "Insufficient quantitative data for unit economics computation"}

`compose_report.py` detects stubs via `_is_stub()` and renders them as informational notes in the report. Stubs are valid for: `unit_economics.json`, `runway.json`, `model_data.json`.

---

## model_data.json

**Producer:** `extract_model.py`

Structured extraction of the spreadsheet contents for downstream analysis.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `sheets` | object[] | yes | Per-sheet extraction |
| `source_format` | string | yes | One of: `"xlsx"`, `"csv"` |
| `source_file` | string | yes | Original filename |

### sheets[] entry

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | yes | Sheet/tab name |
| `headers` | string[] | yes | Column headers detected |
| `rows` | any[][] | yes | Row data (mixed types) |
| `detected_type` | string \| null | yes | One of: `"assumptions"`, `"revenue"`, `"expenses"`, `"cash"`, `"pnl"`, `"summary"`, `"scenarios"`, or `null` if unclassified |
| `row_count` | integer | yes | Number of data rows |
| `col_count` | integer | yes | Number of columns |

**Example:**
```json
{
  "sheets": [
    {
      "name": "Assumptions",
      "headers": ["Parameter", "Value", "Source", "Notes"],
      "rows": [["Monthly churn", 0.03, "Industry avg", "Conservative"]],
      "detected_type": "assumptions",
      "row_count": 45,
      "col_count": 4
    },
    {
      "name": "Revenue",
      "headers": ["Month", "New Customers", "Churned", "Active", "MRR"],
      "rows": [["2025-01", 50, 0, 50, 25000]],
      "detected_type": "revenue",
      "row_count": 36,
      "col_count": 5
    }
  ],
  "source_format": "xlsx",
  "source_file": "acme-financial-model.xlsx"
}
```

---

## inputs.json

**Producer:** Agent (heredoc, Step 1)

Canonical structured input for all downstream scripts. The `company` block is required; all other blocks are optional and populated based on what the model contains.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `company` | object | yes | Company profile |
| `revenue` | object | no | Revenue and growth data |
| `expenses` | object | no | Headcount, OpEx, COGS |
| `cash` | object | no | Cash position and fundraising |
| `unit_economics` | object | no | CAC, LTV, payback, margins |
| `scenarios` | object | no | Base/slow/crisis scenario parameters |
| `structure` | object | no | Model structural quality signals |
| `israel_specific` | object | no | Israel-specific cost and compliance data |
| `bridge` | object | no | Fundraising bridge and milestones |

### company

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `company_name` | string | yes | Company name |
| `slug` | string | yes | URL-safe identifier |
| `stage` | string | yes | One of: `"pre-seed"`, `"seed"`, `"series-a"` |
| `sector` | string | yes | Normalized sector string |
| `geography` | string | yes | Primary geography |
| `revenue_model_type` | string | yes | One of: `"saas-plg"`, `"saas-sales-led"`, `"marketplace"`, `"usage-based"`, `"ai-native"`, `"hardware"`, `"hardware-subscription"`, `"consumer-subscription"`, `"transactional-fintech"` |
| `model_format` | string | no | One of: `"spreadsheet"`, `"deck"`, `"conversational"`, `"partial"`. Defaults to `"spreadsheet"`. Controls which checklist items are applicable. |

#### `model_format` pipeline effects

| Format | Checklist | Unit economics / Runway | Report header |
|--------|-----------|------------------------|---------------|
| `spreadsheet` | All 46 items evaluated | Full computation | "Model Quality" |
| `deck` | STRUCT_01–09, CASH_20–32 auto-gated (22 items) | Agent decides (typically stubs) | "Deck Financial Readiness" |
| `conversational` | Same as `deck` | Agent decides (typically stubs) | "Deck Financial Readiness" |
| `partial` | All 46 items evaluated | Full computation | "Model Quality" |

Additional effects for `deck` / `conversational`:
- `compose_report.py`: CHECKLIST_FAILURES warning downgraded from "high" to "medium" severity
- `compose_report.py --strict`: CHECKLIST_FAILURES excluded from blocking warnings

| `data_confidence` | string | no | One of: `"exact"`, `"estimated"`, `"mixed"`. Indicates reliability of input values. |
| `traits` | string[] | no | Boolean trait flags: `"multi-currency"`, `"multi-entity"`, `"multi-market"`, `"annual-contracts"`, `"ai-powered"` — product uses AI/ML inference as a core feature (triggers AI cost scrutiny regardless of revenue model) |

### revenue

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `monthly` | object[] | no | Monthly revenue time series |
| `arr` | object | no | Annual recurring revenue snapshot |
| `mrr` | object | no | Monthly recurring revenue snapshot |
| `monthly_total` | number | no | Fallback when `mrr` is absent for non-SaaS models |
| `growth_rate_monthly` | number | no | Month-over-month growth rate (decimal) |
| `churn_monthly` | number | no | Monthly churn rate (decimal) |
| `nrr` | number | no | Net revenue retention (decimal) |
| `grr` | number | no | Gross revenue retention (decimal) |
| `expansion_model` | string | no | Description of expansion revenue mechanism |

#### monthly[] entry

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `month` | string | yes | `"YYYY-MM"` format |
| `actual` | boolean | yes | `true` for actuals, `false` for projections |
| `total` | number | yes | Total revenue for the month |
| `drivers` | object | no | Breakdown (e.g., `customers`, `arpu`) |

#### arr / mrr

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `value` | number | yes | ARR or MRR value |
| `as_of` | string | yes | `"YYYY-MM"` snapshot date |

### expenses

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `headcount` | object[] | no | Hiring plan |
| `opex_monthly` | object[] | no | Non-headcount operating expenses |
| `cogs` | object | no | Cost of goods sold breakdown |

#### headcount[] entry

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `role` | string | yes | Role title |
| `count` | integer | yes | Number of hires |
| `start_month` | string | yes | `"YYYY-MM"` start date |
| `salary_annual` | number | yes | Annual salary |
| `geography` | string | no | Role geography (for burden calculation) |
| `burden_pct` | number | no | Employer burden as decimal (e.g., 0.30) |

#### opex_monthly[] entry

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `category` | string | yes | Expense category |
| `amount` | number | yes | Monthly amount |
| `start_month` | string | yes | `"YYYY-MM"` start date |

#### cogs

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `hosting` | number | no | Cloud/hosting costs |
| `inference_costs` | number | no | AI/ML inference costs |
| `support` | number | no | Customer support costs |
| `other` | number | no | Other COGS |

### cash

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `current_balance` | number | yes | Current cash balance |
| `debt` | number | no | Outstanding debt (default 0); used for net cash calculation |
| `balance_date` | string | yes | `"YYYY-MM"` balance date |
| `monthly_net_burn` | number | yes | Net monthly burn rate |
| `fundraising` | object | no | Fundraising parameters |
| `grants` | object | no | Government grant data |

#### fundraising

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `target_raise` | number | yes | Target raise amount |
| `expected_close` | string | yes | `"YYYY-MM"` expected close date |

#### grants

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `iia_approved` | number | no | Approved IIA grant amount |
| `iia_pending` | number | no | Pending IIA grant amount |
| `iia_disbursement_months` | integer | no | Months over which to disburse IIA grant (default 12) |
| `iia_start_month` | integer | no | Month offset from balance_date to start disbursement (default 1) |
| `royalty_rate` | number | no | Royalty repayment rate (decimal) |

### unit_economics

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `cac` | object | no | Customer acquisition cost |
| `ltv` | object | no | Lifetime value |
| `payback_months` | number | no | CAC payback period in months |
| `gross_margin` | number | no | Gross margin (decimal) |
| `burn_multiple` | number | no | Optional; used as fallback when computation inputs (`monthly_net_burn`, `mrr`, `growth_rate_monthly`) are missing. When present alongside compute inputs, the computed value takes precedence |

#### cac

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `total` | number | yes | Total CAC |
| `components` | object | no | CAC breakdown by component |
| `fully_loaded` | boolean | no | Whether CAC includes all S&M costs |

#### ltv

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `value` | number | yes | LTV value |
| `method` | string | no | One of: `"formula"`, `"observed"` |
| `inputs` | object | no | Formula inputs used |
| `observed_vs_assumed` | string | no | One of: `"assumed"`, `"observed"` |

### scenarios

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `base` | object | yes | Base case parameters |
| `slow` | object | yes | Slow/downside case |
| `crisis` | object | yes | Crisis/worst case |

#### scenario entry (base / slow / crisis)

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `growth_rate` | number | yes | Monthly revenue growth rate (decimal) |
| `burn_change` | number | yes | Applied as a one-time step-up at scenario start, not monthly compounding. E.g., 0.10 means expenses are 10% higher than baseline for the entire projection |
| `fx_adjustment` | number | no | FX rate adjustment on ILS expenses (decimal, e.g., 0.1 = 10% ILS weakening) |

### structure

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `has_assumptions_tab` | boolean | no | Whether model has a dedicated assumptions tab |
| `has_scenarios` | boolean | no | Whether model has scenario toggles |
| `actuals_separated` | boolean | no | Whether actuals are visually separated from projections |
| `monthly_granularity_months` | integer | no | Number of months at monthly granularity |
| `has_version_date` | boolean | no | Whether model includes version/date |
| `formatting_quality` | string | no | One of: `"good"`, `"acceptable"`, `"poor"` |
| `structural_errors` | string[] | no | List of structural errors found |

### israel_specific

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `has_entity_structure` | boolean | no | Whether model shows entity-level breakdown |
| `fx_rate_ils_usd` | number | no | ILS/USD exchange rate used |
| `ils_expense_fraction` | number | no | Fraction of expenses denominated in ILS (default 0.5 when fx_rate_ils_usd is present) |
| `fx_sensitivity_modeled` | boolean | no | Whether FX sensitivity is modeled |
| `payroll_detail` | object | no | Israeli payroll cost breakdown |
| `iia_grants` | boolean | no | Whether IIA grants are included |
| `iia_royalties_modeled` | boolean | no | Whether IIA royalty repayment is modeled |
| `entity_cash_planned` | boolean | no | Whether entity-level cash is planned |

#### payroll_detail

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `ni_rate` | number | no | National Insurance rate (decimal) |
| `pension_rate` | number | no | Pension contribution rate (decimal) |
| `severance_rate` | number | no | Severance accrual rate (decimal) |
| `keren_hishtalmut` | boolean | no | Whether Keren Hishtalmut is included |
| `kh_rate` | number | no | Keren Hishtalmut rate (decimal) |

### bridge

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `raise_amount` | number | no | Target raise amount |
| `runway_target_months` | integer | no | Target runway in months (default 24) |
| `milestones` | string[] | no | Key milestones to hit before next round |
| `next_round_target` | string | no | Target metrics/stage for next round |

**Example:**
```json
{
  "company": {
    "company_name": "Acme Corp",
    "slug": "acme-corp",
    "stage": "seed",
    "sector": "saas",
    "geography": "israel",
    "revenue_model_type": "saas-sales-led",
    "traits": ["multi-currency", "multi-entity"]
  },
  "revenue": {
    "monthly": [
      {"month": "2025-01", "actual": true, "total": 25000, "drivers": {"customers": 50, "arpu": 500}},
      {"month": "2025-06", "actual": false, "total": 80000, "drivers": {"customers": 120, "arpu": 667}}
    ],
    "arr": {"value": 300000, "as_of": "2025-01"},
    "mrr": {"value": 25000, "as_of": "2025-01"},
    "growth_rate_monthly": 0.15,
    "churn_monthly": 0.03,
    "nrr": 1.10,
    "grr": 0.92
  },
  "expenses": {
    "headcount": [
      {"role": "Engineer", "count": 4, "start_month": "2025-01", "salary_annual": 180000, "geography": "israel", "burden_pct": 0.38}
    ],
    "opex_monthly": [
      {"category": "Cloud", "amount": 3000, "start_month": "2025-01"}
    ],
    "cogs": {"hosting": 3000, "support": 1500}
  },
  "cash": {
    "current_balance": 1200000,
    "debt": 0,
    "balance_date": "2025-01",
    "monthly_net_burn": 65000,
    "fundraising": {"target_raise": 4000000, "expected_close": "2025-06"},
    "grants": {"iia_approved": 500000, "iia_pending": 0, "royalty_rate": 0.03}
  },
  "unit_economics": {
    "cac": {"total": 8000, "components": {"ad_spend": 3000, "sales_salary": 4000, "tools": 1000}, "fully_loaded": true},
    "ltv": {"value": 20000, "method": "formula", "inputs": {"arpu": 500, "churn": 0.03, "gross_margin": 0.80}, "observed_vs_assumed": "assumed"},
    "payback_months": 16,
    "gross_margin": 0.80,
    "burn_multiple": 2.5
  },
  "scenarios": {
    "base": {"growth_rate": 0.15, "burn_change": 0.0},
    "slow": {"growth_rate": 0.08, "burn_change": 0.1},
    "crisis": {"growth_rate": 0.0, "burn_change": 0.2}
  },
  "structure": {
    "has_assumptions_tab": true,
    "has_scenarios": true,
    "actuals_separated": true,
    "monthly_granularity_months": 24,
    "has_version_date": true,
    "formatting_quality": "good",
    "structural_errors": []
  },
  "israel_specific": {
    "has_entity_structure": true,
    "fx_rate_ils_usd": 3.65,
    "fx_sensitivity_modeled": true,
    "payroll_detail": {"ni_rate": 0.0345, "pension_rate": 0.065, "severance_rate": 0.0833, "keren_hishtalmut": true, "kh_rate": 0.075},
    "iia_grants": true,
    "iia_royalties_modeled": true,
    "entity_cash_planned": true
  },
  "bridge": {
    "raise_amount": 4000000,
    "runway_target_months": 24,
    "milestones": ["$1M ARR", "100 paying customers", "NRR > 110%"],
    "next_round_target": "Series A at $3-4M ARR"
  }
}
```

## Sector & Revenue Model Mapping

### Valid `revenue_model_type` Values

| Value | Description | Examples |
|-------|-------------|----------|
| `saas-plg` | SaaS, product-led growth | Slack, Figma, Notion |
| `saas-sales-led` | SaaS, sales-led growth | Salesforce, HubSpot |
| `marketplace` | Two-sided marketplace | Airbnb, DoorDash |
| `ai-native` | AI-first, usage-based pricing | OpenAI, Jasper |
| `usage-based` | Consumption-based pricing | Twilio, Snowflake |
| `hardware` | Physical product | Peloton, Ring |
| `hardware-subscription` | Hardware with recurring revenue | Tesla FSD, Apple One |
| `consumer-subscription` | Consumer subscription | Netflix, Spotify |
| `annual-contracts` | Enterprise annual/multi-year | Workday, ServiceNow |

### Sector Gate Mapping

- `SECTOR_39` (marketplace): triggers for `marketplace`
- `SECTOR_40` (AI inference): triggers for `ai-native`, `usage-based`, `ai-powered` (via `company.traits`), or when `expenses.cogs` contains AI cost keys (`inference_costs`, `ai_infrastructure`, `ai_compute`, `gpu_costs`, `model_inference`)
- `SECTOR_41` (hardware): triggers for `hardware`, `hardware-subscription`
- `SECTOR_42` (usage-based margin): triggers for `usage-based`
- `SECTOR_43` (consumer retention): triggers for `consumer-subscription`
- `SECTOR_44` (deferred revenue): triggers for `annual-contracts`

### LTV Cap Behavior

When `unit_economics.ltv.inputs.churn_monthly` is 0%, LTV is mathematically infinite. The script caps the value at a 60-month (5-year) horizon: `arpu_monthly * gross_margin * 60`. The evidence field labels this as "capped at 5-year horizon, 0% churn assumed".

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

**Example:**
```json
{
  "items": [
    {
      "id": "STRUCT_01",
      "category": "Structure & Presentation",
      "label": "Assumptions isolated on dedicated tab",
      "status": "pass",
      "evidence": "Dedicated 'Assumptions' tab with color-coded inputs",
      "notes": "All key assumptions isolated and clearly labeled"
    },
    {
      "id": "CASH_28",
      "category": "Expenses, Cash & Runway",
      "label": "FX sensitivity modeled",
      "status": "pass",
      "evidence": "+/-15% ILS/USD sensitivity on the Scenarios tab",
      "notes": null
    },
    {
      "id": "SECTOR_39",
      "category": "Sector-Specific",
      "label": "Marketplace: two-sided mechanics",
      "status": "not_applicable",
      "evidence": null,
      "notes": "Company is not a marketplace"
    }
  ],
  "summary": {
    "total": 46,
    "pass": 28,
    "fail": 3,
    "warn": 5,
    "not_applicable": 10,
    "score_pct": 84.7,
    "overall_status": "solid",
    "by_category": {
      "Structure & Presentation": {"pass": 8, "fail": 0, "warn": 1, "not_applicable": 0},
      "Revenue & Unit Economics": {"pass": 7, "fail": 1, "warn": 2, "not_applicable": 0},
      "Expenses, Cash & Runway": {"pass": 9, "fail": 1, "warn": 1, "not_applicable": 2},
      "Metrics & Efficiency": {"pass": 2, "fail": 0, "warn": 1, "not_applicable": 0},
      "Fundraising Bridge": {"pass": 2, "fail": 0, "warn": 0, "not_applicable": 1},
      "Sector-Specific": {"pass": 0, "fail": 1, "warn": 0, "not_applicable": 5},
      "Overall": {"pass": 0, "fail": 0, "warn": 0, "not_applicable": 2}
    },
    "failed_items": [
      {"id": "UNIT_11", "category": "Revenue & Unit Economics", "label": "Churn modeled explicitly", "evidence": "0% churn assumed for all 36 months", "notes": null},
      {"id": "CASH_23", "category": "Expenses, Cash & Runway", "label": "Cash runway computed correctly", "evidence": "Runway formula uses gross burn instead of net burn", "notes": null},
      {"id": "SECTOR_40", "category": "Sector-Specific", "label": "AI: inference costs modeled", "evidence": "No inference cost line despite AI-native model", "notes": null}
    ],
    "warned_items": [
      {"id": "STRUCT_07", "category": "Structure & Presentation", "label": "Monthly granularity appropriate to stage", "evidence": "Only 18 months at monthly granularity for seed stage", "notes": null},
      {"id": "UNIT_13", "category": "Revenue & Unit Economics", "label": "Expansion revenue modeled (where applicable)", "evidence": "Expansion mentioned in notes but not modeled", "notes": null},
      {"id": "UNIT_18", "category": "Revenue & Unit Economics", "label": "Sales capacity constrains revenue", "evidence": "Simplified efficiency ratio used", "notes": null},
      {"id": "CASH_22", "category": "Expenses, Cash & Runway", "label": "Working capital modeled (where material)", "evidence": "Simplified but noted in assumptions", "notes": null},
      {"id": "METRIC_34", "category": "Metrics & Efficiency", "label": "Burn multiple tracked", "evidence": "High (3.2x) but showing improvement trend", "notes": null}
    ]
  }
}
```

---

## unit_economics.json

**Producer:** `unit_economics.py`

Computed unit economics metrics with benchmark ratings. Metrics are returned as an array (not a keyed object) so that each entry carries its own rating, evidence, and benchmark source inline.

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
| `confidence` | string | no | `"exact"`, `"estimated"`, or `"mixed"`. Present only on rated metrics (rating is not `"not_rated"` or `"not_applicable"`) when `data_confidence` is not `"exact"`. Qualifies the reliability of the metric's inputs |

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

**Example:**
```json
{
  "metrics": [
    {
      "name": "cac",
      "value": 8000,
      "rating": "not_rated",
      "evidence": "Fully loaded CAC of $8,000",
      "benchmark_source": "",
      "benchmark_as_of": ""
    },
    {
      "name": "ltv_cac_ratio",
      "value": 2.5,
      "rating": "contextual",
      "evidence": "LTV/CAC of 2.5x (based on assumed inputs); treat as directional until cohort data validates LTV",
      "benchmark_source": "Mosaic 2023 / KeyBanc 2024",
      "benchmark_as_of": "2024-Q4"
    },
    {
      "name": "burn_multiple",
      "value": 2.5,
      "rating": "acceptable",
      "evidence": "Burn multiple of 2.5x; stage benchmark strong <= 1.5x",
      "benchmark_source": "CFO Advisors 2025 / best-practices resolution",
      "benchmark_as_of": "2025-Q1"
    },
    {
      "name": "gross_margin",
      "value": 0.80,
      "rating": "strong",
      "evidence": "Gross margin of 80%; stage benchmark strong >= 75%",
      "benchmark_source": "KeyBanc SaaS Survey 2024",
      "benchmark_as_of": "2024-Q4"
    }
  ],
  "summary": {
    "computed": 4,
    "strong": 1,
    "acceptable": 1,
    "warning": 0,
    "fail": 0,
    "not_rated": 1,
    "contextual": 1,
    "not_applicable": 0
  }
}
```

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
| `data_confidence` | string | no | `"exact"`, `"estimated"`, or `"mixed"`. Present only when not `"exact"`. Passed through from `company.data_confidence` |
| `insufficient_data` | boolean | no | Present and `true` when cash/burn data is missing; all other fields will be null/empty |

### baseline

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `net_cash` | number | yes | Current cash minus debt |
| `monthly_burn` | number | yes | Monthly net burn rate |
| `monthly_revenue` | number | yes | Monthly revenue used as starting point |

### scenarios[] entry

Scenarios are returned as an array. Auto-generated scenarios are `base`, `slow`, `crisis`; user-provided scenarios pass through with any names.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | yes | Scenario name |
| `growth_rate` | number | yes | Monthly revenue growth rate used |
| `burn_change` | number | yes | One-time step-up at scenario start (e.g., 0.10 = expenses 10% above baseline for entire projection) |
| `fx_adjustment` | number | yes | FX adjustment on ILS expenses (0.0 if no FX exposure) |
| `runway_months` | integer \| null | yes | Months until cash runs out, or `null` if never within 60 months |
| `cash_out_date` | string \| null | yes | `"YYYY-MM"` projected cash-out, or `null` |
| `decision_point` | string \| null | yes | `"YYYY-MM"` date to begin fundraising (12 months before cash-out), or `null` |
| `default_alive` | boolean | yes | Whether company reaches profitability before cash-out |
| `monthly_projections` | object[] | yes | Month-by-month projection data |

### monthly_projections[] entry

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `month` | integer | yes | Month number (1-based) |
| `cash_balance` | number | yes | Projected cash balance |
| `revenue` | number | yes | Projected monthly revenue |
| `expenses` | number | yes | Projected monthly expenses (after FX adjustment if applicable) |
| `net_burn` | number | yes | Expenses minus revenue |

### post_raise

Computed when `cash.fundraising.target_raise` is provided.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `raise_amount` | number | yes | Amount being raised |
| `new_cash` | number | yes | Post-raise cash position (net_cash + raise_amount) |
| `new_runway_months` | integer \| null | yes | Post-raise runway in months (null if never runs out) |
| `new_cash_out_date` | string \| null | yes | `"YYYY-MM"` post-raise cash-out date |
| `meets_target` | boolean | yes | Whether runway meets `bridge.runway_target_months` (default 24) |

**Example:**
```json
{
  "company": {"name": "Acme Corp", "slug": "acme-corp", "stage": "seed"},
  "baseline": {
    "net_cash": 1200000,
    "monthly_burn": 65000,
    "monthly_revenue": 25000
  },
  "scenarios": [
    {
      "name": "base",
      "growth_rate": 0.15,
      "burn_change": 0.0,
      "fx_adjustment": 0.0,
      "runway_months": 18,
      "cash_out_date": "2026-07",
      "decision_point": "2025-07",
      "default_alive": false,
      "monthly_projections": [
        {"month": 1, "cash_balance": 1163750.0, "revenue": 28750.0, "expenses": 90000.0, "net_burn": 61250.0}
      ]
    },
    {
      "name": "slow",
      "growth_rate": 0.075,
      "burn_change": 0.10,
      "fx_adjustment": 0.0,
      "runway_months": 15,
      "cash_out_date": "2026-04",
      "decision_point": "2025-04",
      "default_alive": false,
      "monthly_projections": []
    },
    {
      "name": "crisis",
      "growth_rate": 0.0,
      "burn_change": 0.20,
      "fx_adjustment": 0.0,
      "runway_months": 12,
      "cash_out_date": "2026-01",
      "decision_point": "2025-01",
      "default_alive": false,
      "monthly_projections": []
    }
  ],
  "post_raise": {
    "raise_amount": 4000000,
    "new_cash": 5200000,
    "new_runway_months": null,
    "new_cash_out_date": null,
    "meets_target": true
  },
  "risk_assessment": "Elevated risk: 18 months of runway under base scenario. Fundraising should begin immediately.",
  "limitations": [
    "Projections assume constant monthly growth and burn rates (no seasonality).",
    "Does not account for one-time events (fundraise closings, large contracts, etc.).",
    "Tax obligations and working capital timing not modeled."
  ],
  "warnings": []
}
```

---

## report.json

**Producer:** `compose_report.py`

Assembled report from all artifacts with cross-artifact validation. This is the final output of the review workflow.

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
| `model_format` | string | no | Source format from inputs (e.g., `"spreadsheet"`, `"deck"`). Used by `--strict` to contextualize expected warnings. |

### warnings[] entry

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `code` | string | yes | Warning code (e.g., `"MISSING_ARTIFACT"`, `"CHECKLIST_FAILURES"`) |
| `severity` | string | yes | One of: `"high"`, `"medium"`, `"low"` |
| `message` | string | yes | Human-readable warning message |

**Exit codes:**
- `0` — success
- `1` — required artifacts missing (always), or any high/medium warnings in `--strict` mode
