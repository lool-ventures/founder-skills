# Financial Model Review — Input Schemas

Schemas for artifacts the agent writes during the review workflow. For output schemas (what scripts produce), see `artifact-schemas.md`.

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

## inputs.json

**Producer:** Agent (heredoc, Step 3)

Canonical structured input for all downstream scripts. The `company` block is required; all other blocks are optional and populated based on what the model contains.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `company` | object | yes | Company profile |
| `metadata` | object | no | Extraction metadata (periodicity, conversion, overrides) |
| `revenue` | object | no | Revenue and growth data |
| `expenses` | object | no | Headcount, OpEx, COGS |
| `cash` | object | no | Cash position and fundraising |
| `unit_economics` | object | no | CAC, LTV, payback, margins |
| `scenarios` | object | no | Base/slow/crisis scenario parameters |
| `structure` | object | no | Model structural quality signals |
| `israel_specific` | object | no | Israel-specific cost and compliance data |
| `bridge` | object | no | Fundraising bridge and milestones |

### metadata

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `source_periodicity` | string | no | Periodicity detected from the source model. One of: `"monthly"`, `"quarterly"`, `"annual"`, `"mixed"`, `"unknown"`. |
| `conversion_applied` | string | no | Conversion applied to flow metrics. One of: `"none"`, `"divided_by_3"`, `"divided_by_12"`. |
| `run_id` | string | no | Unique identifier for this review run (ISO timestamp or UUID). Used by `compose_report.py` to detect stale artifacts. |
| `warning_overrides` | object[] | no | Critical warnings the agent investigated and chose to proceed past. |

#### warning_overrides[] entry

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `code` | string | yes | Warning code from `validate_inputs.py` (e.g., `"BURN_MULTIPLE_SUSPECT"`) |
| `reason` | string | yes | Why the warning was overridden |
| `reviewed_by` | string | yes | One of: `"agent"`, `"founder"` |
| `timestamp` | string | yes | ISO 8601 timestamp |

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
- `compose_report.py --strict`: Only high-severity warnings (corrupt/missing artifacts) block; checklist failures are review findings, not data errors

| `data_confidence` | string | no | One of: `"exact"`, `"estimated"`, `"mixed"`. Indicates reliability of input values. |
| `traits` | string[] | no | Boolean trait flags: `"multi-currency"`, `"multi-entity"`, `"multi-market"`, `"annual-contracts"`, `"ai-powered"` — product uses AI/ML inference as a core feature (triggers AI cost scrutiny regardless of revenue model) |

### revenue

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `customers` | number | no | Current customer count. Required at seed+ when LTV inputs are provided. |
| `monthly` | object[] | no | Monthly revenue time series |
| `quarterly` | object[] | no | Quarterly revenue time series (use instead of `monthly` when source data is quarterly) |
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
| `arr` | number | no | Annualized run-rate at this point in time. When present, used for TTM burn multiple. When absent, `total * 12` is used as approximation. |
| `drivers` | object | no | Breakdown (e.g., `customers`, `arpu_monthly`) |

#### quarterly[] entry

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `quarter` | string | yes | `"YYYY-QN"` format (e.g., `"2024-Q1"`) |
| `actual` | boolean | yes | `true` for actuals, `false` for projections |
| `total` | number | yes | Total revenue for the quarter |
| `arr` | number | no | Annualized run-rate at quarter end. Used for YoY burn multiple computation. |
| `drivers` | object | no | Breakdown (e.g., `customers`, `arpu_monthly`) |

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
| `monthly_net_burn` | number | yes | Net monthly burn rate. **Sign convention: positive = cash outgoing** (e.g., if the company burns $500K/month, write `500000`, not `-500000`). The script will defensively abs() negative values, but correct sign avoids warnings. |
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
    "customers": 50,
    "monthly": [
      {"month": "2025-01", "actual": true, "total": 25000, "arr": 300000, "drivers": {"customers": 50, "arpu_monthly": 500}},
      {"month": "2025-06", "actual": false, "total": 80000, "arr": 960000, "drivers": {"customers": 120, "arpu_monthly": 667}}
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
    "ltv": {"value": 20000, "method": "formula", "inputs": {"arpu_monthly": 500, "churn_monthly": 0.03, "gross_margin": 0.80}, "observed_vs_assumed": "assumed"},
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

When `unit_economics.ltv.inputs.churn_monthly` is 0%, LTV is mathematically infinite. The script caps the value at a 60-month (5-year) horizon: `arpu_monthly * gross_margin * 60`. The evidence field labels this as "capped at 5-year horizon, 0% churn assumed". If `arpu_monthly` or `gross_margin` is missing, the cap cannot be computed — the original LTV value passes through but is marked `not_rated` with evidence noting the cap could not be applied.
