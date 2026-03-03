# Consolidated Review Checklist

> **Shared reference.** Extracted from `fin-model-research/best-practices.md` (Post-ZIRP Edition, 2024-2026).
> **Source of truth** for `checklist.py` item definitions (46 items across 7 categories).
> Consumed by: `financial-model-review` and other Tier 1+ skills.

---

## Structure and Presentation (items 1-9)

| # | ID | Criterion | Pass | Warning | Fail |
| --- | --- | --- | --- | --- | --- |
| 1 | `STRUCT_ASSUMPTIONS_ISOLATED` | Assumptions isolated on dedicated tab | All inputs in one place, color-coded | Assumptions scattered but findable | Hardcoded numbers across output sheets |
| 2 | `STRUCT_TAB_NAVIGABLE` | Tab structure is navigable | Summary + detail accessible in minutes | Messy but usable | Investor can't find basics |
| 3 | `STRUCT_ACTUALS_SEPARATED` | Actuals vs. projections separated | Visually distinct with clear boundary | Some ambiguity | Intermingled |
| 4 | `STRUCT_SCENARIOS` | Scenario toggles (base/up/down) | Functional toggles driving key drivers | One sensitivity only | Single "best case" only |
| 5 | `STRUCT_DECK_MATCH` | Model matches pitch deck | Numbers align exactly | Minor mismatch | Material mismatch (a16z explicit red flag) |
| 6 | `STRUCT_VERSION_DATE` | Version/date included | Model notes include date and version | Some confusion | Multiple versions circulating |
| 7 | `STRUCT_MONTHLY_GRANULARITY` | Monthly granularity appropriate to stage | Pre-seed 12-24mo; Seed 24-36mo; A 24-36mo+ | Shorter than stage requires | Weekly revenue mixed with monthly costs |
| 8 | `STRUCT_NO_ERRORS` | No structural errors | Zero circular refs, #REF!, #DIV/0! | Minor issues | Circulars break outputs |
| 9 | `STRUCT_FORMATTING` | Professional formatting | Standard sign conventions, grouped categories | Messy but usable | Unreadable |

---

## Revenue and Unit Economics (items 10-19)

| # | ID | Criterion | Pass | Warning | Fail |
| --- | --- | --- | --- | --- | --- |
| 10 | `REV_BOTTOM_UP` | Revenue is bottom-up | Revenue = units x price x frequency (or pipeline mechanics) | Partial drivers | Revenue as arbitrary top-line curve or TAM % |
| 11 | `REV_CHURN_MODELED` | Churn modeled explicitly | Non-zero churn; logo and/or revenue | "Too good" retention assumptions | 0% churn indefinitely |
| 12 | `REV_PRICING_EXPLICIT` | Pricing logic explicit | Price points + ramp/discounts documented | Pricing unclear | Hidden/implied pricing |
| 13 | `REV_EXPANSION` | Expansion revenue modeled (where applicable) | Expansion logic for SaaS/usage-based included | Mentioned but not modeled | NRR >100% implied with no mechanism |
| 14 | `REV_COGS_MATCHES_TYPE` | COGS/margin matches model type | SaaS: hosting/support; AI: inference; hardware: BOM | Margin assumed flat without basis | Gross margin improves magically |
| 15 | `REV_CAC_LOADED` | CAC fully loaded | Includes S&M salaries, ad spend, tools | Some costs missing | Only ad spend counted |
| 16 | `REV_CAC_PAYBACK` | CAC payback computed | Method stated; within reasonable band for GTM motion | Unclear method | Payback not computable |
| 17 | `REV_LTV_CAC` | LTV/CAC shown (where mature enough) | Formula inputs shown; assumed vs. observed labeled | Presented with fake precision | No unit economics at all (seed+) |
| 18 | `REV_SALES_CAPACITY` | Sales capacity constrains revenue | Quota, attainment (~70-75%), ramp (60-90 days) modeled | Simplified efficiency | Revenue scales without sales hires |
| 19 | `REV_CONVERSION_GROUNDED` | Conversion rates grounded | Rates consistent with market or early data | Optimistic but possible | Absurd rates (50%+ cold outbound close rate) |

---

## Expenses, Cash, and Runway (items 20-32)

| # | ID | Criterion | Pass | Warning | Fail |
| --- | --- | --- | --- | --- | --- |
| 20 | `CASH_HEADCOUNT_DRIVES` | Headcount plan drives expenses | Role-based hiring plan with timing; 80%+ of OpEx | Headcount exists but not costed | Payroll missing or "% of revenue" only |
| 21 | `CASH_BENEFITS_INCLUDED` | Benefits/tax burden included | Fully loaded comp (25-35% US; 30-45%+ EU) | Some load missing | No benefits or taxes modeled |
| 22 | `CASH_WORKING_CAPITAL` | Working capital modeled (where material) | AR/AP/inventory timing reflected in cash | Simplified but noted | Ignores working capital in cash-heavy models |
| 23 | `CASH_RUNWAY_CORRECT` | Cash runway computed correctly | Runway = net cash / burn; consistent monthly | Some inconsistency | Runway math missing or wrong |
| 24 | `CASH_RUNWAY_LENGTH` | Runway length adequate | Pre-seed >=18mo; Seed/A 24-36mo | 12-18 months with strong rationale | <12 months with no plan |
| 25 | `CASH_CASHOUT_DATE` | Cash-out date explicit | Clear month when cash hits zero | Calculable but not highlighted | Not computable |
| 26 | `CASH_STEP_COSTS` | Step costs captured | New hires, infrastructure thresholds | Some missing | Expenses flat while revenue scales |
| 27 | `CASH_OPEX_SCALES` | OpEx scales with revenue | Expense growth broadly aligned | Some disconnect | 10x revenue with flat team |
| 28 | `CASH_FX_SENSITIVITY` | FX sensitivity modeled (multi-currency) | FX assumptions stated; +/-10-15% sensitivity on ILS/USD (or relevant pair) | Simplified or static rate | No FX consideration despite material foreign-currency costs |
| 29 | `CASH_ENTITY_SOLVENT` | Entity-level cash solvent (multi-entity) | Each entity's ending cash >=0; intercompany transfers timed | Consolidated-only view noted | Subsidiary can't make payroll; no entity-level view |
| 30 | `CASH_IL_STATUTORY` | Israel statutory costs itemized | NI + pension + severance + KH policy stated | Generic "burden %" without breakdown | Benefits/taxes omitted for Israeli team |
| 31 | `CASH_GRANTS_MODELED` | Government grants modeled (IIA etc.) | Grant inflows, approval assumptions, royalty repayment liabilities | Grants mentioned but not modeled | IIA grants received but royalties/IP constraints omitted |
| 32 | `CASH_VAT_TIMING` | VAT/indirect tax cash timing | Input VAT refund timing modeled where material; current rate reflected | Simplified | VAT treated as non-issue when it creates cash troughs |

---

## Metrics and Efficiency (items 33-35)

| # | ID | Criterion | Pass | Warning | Fail |
| --- | --- | --- | --- | --- | --- |
| 33 | `METRICS_KPI_VISIBLE` | KPI summary visible | ARR/MRR, burn, runway, GM, retention, CAC/payback on summary | KPIs scattered | No KPI view |
| 34 | `METRICS_BURN_MULTIPLE` | Burn multiple tracked (seed+) | Computed correctly (Net Burn / Net New ARR); improving | High but improving | Worsening with scale; >3x |
| 35 | `METRICS_BENCHMARK_AWARE` | Benchmark awareness | Uses benchmarks as context, not proof | Cherry-picking | Benchmarks justify fantasy outcomes |

---

## Fundraising Bridge (items 36-38)

| # | ID | Criterion | Pass | Warning | Fail |
| --- | --- | --- | --- | --- | --- |
| 36 | `FUND_RAISE_BRIDGE` | Raise -> runway -> milestones -> next round | Clear linkage throughout | Some linkage | Raise amount arbitrary; no milestone plan |
| 37 | `FUND_NEXT_MILESTONES` | Next-round milestones identified | Specific KPI targets for next funding stage | Vague goals | No forward-looking plan |
| 38 | `FUND_DILUTION_SHOWN` | Dilution/ownership shown (seed+) | Cap-table impact of raise (15-25% per round typical) | Not included | Dilution math inconsistent |

---

## Sector-Specific Checks (items 39-44)

| # | ID | Criterion | Pass | Warning | Fail |
| --- | --- | --- | --- | --- | --- |
| 39 | `SECTOR_MARKETPLACE` | Marketplace: two-sided mechanics | CAC and retention on both sides; GMV/take-rate logic | Only one side modeled | Treats marketplace like one-sided SaaS |
| 40 | `SECTOR_AI_INFERENCE` | AI: inference costs modeled | Gross margin incorporates model/compute costs; sensitivity on usage | Weak cost calibration | Ignores variable AI costs |
| 41 | `SECTOR_HARDWARE` | Hardware/deep-tech: milestones + capex | Milestone plan + cash needs; working capital/capex considered | Some milestones | "SaaS-like" model applied to hardware |
| 42 | `SECTOR_USAGE_MARGIN` | Usage-based: margin at scale | COGS scales with consumption; base vs. variable fees separated | Simplified | Usage costs ignored |
| 43 | `SECTOR_CONSUMER_RETENTION` | Consumer: retention curves | Cohort-based engagement and monetization | Aggregate only | No retention analysis |
| 44 | `SECTOR_DEFERRED_REVENUE` | Deferred revenue (if applicable) | Annual upfront payments amortized correctly | Simplified | Cash treated as revenue |

---

## Overall (items 45-46)

| # | ID | Criterion | Pass | Warning | Fail |
| --- | --- | --- | --- | --- | --- |
| 45 | `OVERALL_5MIN_AUDIT` | "5-minute audit" possible | One dashboard answers: burn/runway, growth, margin, unit economics | Needs hunting | Investor can't orient quickly |
| 46 | `OVERALL_GEO_SEGMENTED` | Country-level CAC/payback tracked (global-first) | CAC, payback, NRR segmented by major market (US, UK, DACH, etc.) | Aggregate only but noted | No geographic segmentation despite multi-market GTM |

---

## Gate Definitions

Items are tagged with applicability gates that determine when they should be evaluated:

### Stage gates
- **all**: Applies at all stages (pre-seed, seed, Series A)
- **seed+**: Applies at seed and Series A only (items 17, 34, 38)
- **series_a**: Applies at Series A only

### Sector gates
- **marketplace**: Items 39
- **ai**: Items 40
- **hardware**: Items 41
- **usage_based**: Items 42
- **consumer**: Items 43
- **deferred_revenue**: Items 44 (any model with annual upfront payments)

### Context gates
- **multi_currency**: Items 28 (FX sensitivity)
- **multi_entity**: Items 29 (entity-level solvency)
- **israel**: Items 30 (statutory costs), 31 (IIA grants), 32 (VAT timing)
- **global_first**: Items 46 (geographic segmentation)

### Scoring
- **pass** = 1 point
- **warn** = 0.5 points
- **fail** = 0 points
- **not_applicable** = excluded from denominator

Overall score = sum(points) / count(applicable items) x 100%

Items 28-32 and 39-44 and 46 are conditionally applicable based on the startup's context (geography, sector, business model). The reviewing agent determines applicability before scoring.
