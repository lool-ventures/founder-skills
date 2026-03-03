# Financial Model Review Checklist Criteria

46 criteria across 7 categories. Each criterion has an ID, label, pass/warn/fail definitions, and applicability gates (stage, geography, sector).

## Gate Matching Rules

Items are tagged with applicability gates that determine when they should be evaluated:

- **`all`** — always applicable.
- **`seed+`** — applicable when stage is `seed`, `series-a`, `series-b`, or `later`.
- **Single values** — exact match against `inputs.company.{stage, geography, sector_type}`.
- **Multi-match items** — arrays (not slash-separated). For each gate array, check if ANY value matches `company.geography` / `company.sector_type` OR appears in `company.traits`.
- **Company profile fields:** `inputs.company.geography` is a single normalized string. `inputs.company.sector_type` is derived from `revenue_model_type` (see checklist.py). The `multi-currency`, `multi-entity`, `multi-market`, `annual-contracts`, and `ai-powered` gates are matched via `company.traits` array.
- **Gate evaluation:** For each gate array, check if ANY value matches `company.geography` / `company.sector_type` OR appears in `company.traits`.
- Items whose gate doesn't match are auto-scored as `not_applicable`.

## Scoring Formula

- **pass** = 1 point
- **warn** = 0.5 points
- **fail** = 0 points
- **not_applicable** = excluded from denominator

Overall score = sum(points) / count(applicable items) x 100%

Thresholds: **strong** >= 85%, **solid** >= 70%, **needs_work** >= 50%, **major_revision** < 50%

---

## Category 1 — Structure & Presentation (9 items)

### `STRUCT_01`
**Label:** Assumptions isolated on dedicated tab
**Stage:** all | **Geography:** all | **Sector:** all | **Model format:** spreadsheet only
**Pass:** All inputs in one place, color-coded.
**Warn:** Assumptions scattered but findable.
**Fail:** Hardcoded numbers across output sheets.

### `STRUCT_02`
**Label:** Tab structure is navigable
**Stage:** all | **Geography:** all | **Sector:** all | **Model format:** spreadsheet only
**Pass:** Summary + detail accessible in minutes.
**Warn:** Messy but usable.
**Fail:** Investor can't find basics.

### `STRUCT_03`
**Label:** Actuals vs. projections separated
**Stage:** all | **Geography:** all | **Sector:** all | **Model format:** spreadsheet only
**Pass:** Visually distinct with clear boundary.
**Warn:** Some ambiguity.
**Fail:** Intermingled.

### `STRUCT_04`
**Label:** Scenario toggles (base/up/down)
**Stage:** all | **Geography:** all | **Sector:** all | **Model format:** spreadsheet only
**Pass:** Functional toggles driving key drivers.
**Warn:** One sensitivity only.
**Fail:** Single "best case" only.

### `STRUCT_05`
**Label:** Model matches pitch deck
**Stage:** all | **Geography:** all | **Sector:** all | **Model format:** spreadsheet only
**Pass:** Numbers align exactly.
**Warn:** Minor mismatch.
**Fail:** Material mismatch (a16z explicit red flag).

### `STRUCT_06`
**Label:** Version/date included
**Stage:** all | **Geography:** all | **Sector:** all | **Model format:** spreadsheet only
**Pass:** Model notes include date and version.
**Warn:** Some confusion.
**Fail:** Multiple versions circulating.

### `STRUCT_07`
**Label:** Monthly granularity appropriate to stage
**Stage:** all | **Geography:** all | **Sector:** all | **Model format:** spreadsheet only
**Pass:** Pre-seed 12-24mo; Seed 24-36mo; A 24-36mo+.
**Warn:** Shorter than stage requires.
**Fail:** Weekly revenue mixed with monthly costs.

### `STRUCT_08`
**Label:** No structural errors (internal reconciliation: unit economics roll into P&L/S&M spend; balance sheet assets = liabilities + equity if BS present; ending cash on CF = cash on BS; net income flows to retained earnings)
**Stage:** all | **Geography:** all | **Sector:** all | **Model format:** spreadsheet only
**Pass:** Zero circular refs, #REF!, #DIV/0!.
**Warn:** Minor issues.
**Fail:** Circulars break outputs.

### `STRUCT_09`
**Label:** Professional formatting
**Stage:** all | **Geography:** all | **Sector:** all | **Model format:** spreadsheet only
**Pass:** Standard sign conventions, grouped categories.
**Warn:** Messy but usable.
**Fail:** Unreadable.

---

## Category 2 — Revenue & Unit Economics (10 items)

### `UNIT_10`
**Label:** Revenue is bottom-up
**Stage:** all | **Geography:** all | **Sector:** all | **Model format:** all
**Pass:** Revenue = units x price x frequency (or pipeline mechanics).
**Warn:** Partial drivers.
**Fail:** Revenue as arbitrary top-line curve or TAM %.

### `UNIT_11`
**Label:** Churn modeled explicitly
**Stage:** all | **Geography:** all | **Sector:** all | **Model format:** all
**Pass:** Non-zero churn; logo and/or revenue.
**Warn:** "Too good" retention assumptions.
**Fail:** 0% churn indefinitely.

### `UNIT_12`
**Label:** Pricing logic explicit
**Stage:** all | **Geography:** all | **Sector:** all | **Model format:** all
**Pass:** Price points + ramp/discounts documented.
**Warn:** Pricing unclear.
**Fail:** Hidden/implied pricing.

### `UNIT_13`
**Label:** Expansion revenue modeled (where applicable)
**Stage:** all | **Geography:** all | **Sector:** all | **Model format:** all
**Pass:** Expansion logic for SaaS/usage-based included.
**Warn:** Mentioned but not modeled.
**Fail:** NRR >100% implied with no mechanism.

### `UNIT_14`
**Label:** COGS/margin matches model type
**Stage:** all | **Geography:** all | **Sector:** all | **Model format:** all
**Pass:** SaaS: hosting/support; AI: inference; hardware: BOM.
**Warn:** Margin assumed flat without basis.
**Fail:** Gross margin improves magically.

### `UNIT_15`
**Label:** CAC fully loaded
**Stage:** all | **Geography:** all | **Sector:** all | **Model format:** all
**Pass:** Includes S&M salaries, ad spend, tools.
**Warn:** Some costs missing.
**Fail:** Only ad spend counted.

### `UNIT_16`
**Label:** CAC payback computed
**Stage:** all | **Geography:** all | **Sector:** all | **Model format:** all
**Pass:** Method stated; within reasonable band for GTM motion.
**Warn:** Unclear method.
**Fail:** Payback not computable.

### `UNIT_17`
**Label:** LTV/CAC shown (where mature enough)
**Stage:** seed+ | **Geography:** all | **Sector:** all | **Model format:** all
**Pass:** Formula inputs shown; assumed vs. observed labeled.
**Warn:** Presented with fake precision.
**Fail:** No unit economics at all (seed+).

### `UNIT_18`
**Label:** Sales capacity constrains revenue
**Stage:** all | **Geography:** all | **Sector:** all | **Model format:** all
**Pass:** Quota, attainment (~70-75%), ramp (60-90 days) modeled.
**Warn:** Simplified efficiency.
**Fail:** Revenue scales without sales hires.

### `UNIT_19`
**Label:** Conversion rates grounded
**Stage:** all | **Geography:** all | **Sector:** all | **Model format:** all
**Pass:** Rates consistent with market or early data.
**Warn:** Optimistic but possible.
**Fail:** Absurd rates (50%+ cold outbound close rate).

---

## Category 3 — Expenses, Cash & Runway (13 items)

### `CASH_20`
**Label:** Headcount plan drives expenses
**Stage:** all | **Geography:** all | **Sector:** all | **Model format:** spreadsheet only
**Pass:** Role-based hiring plan with timing; 80%+ of OpEx.
**Warn:** Headcount exists but not costed.
**Fail:** Payroll missing or "% of revenue" only.

### `CASH_21`
**Label:** Benefits/tax burden included
**Stage:** all | **Geography:** all | **Sector:** all | **Model format:** spreadsheet only
**Pass:** Fully loaded comp (25-35% US; 30-45%+ EU).
**Warn:** Some load missing.
**Fail:** No benefits or taxes modeled.

### `CASH_22`
**Label:** Working capital modeled (where material)
**Stage:** all | **Geography:** all | **Sector:** all | **Model format:** spreadsheet only
**Pass:** AR/AP/inventory timing reflected in cash.
**Warn:** Simplified but noted.
**Fail:** Ignores working capital in cash-heavy models.

### `CASH_23`
**Label:** Cash runway computed correctly
**Stage:** all | **Geography:** all | **Sector:** all | **Model format:** spreadsheet only
**Pass:** Runway = net cash / burn; consistent monthly.
**Warn:** Some inconsistency.
**Fail:** Runway math missing or wrong.

### `CASH_24`
**Label:** Runway length adequate
**Stage:** all | **Geography:** all | **Sector:** all | **Model format:** spreadsheet only
**Pass:** Pre-seed >=18mo; Seed/A 24-36mo.
**Warn:** 12-18 months with strong rationale.
**Fail:** <12 months with no plan.

### `CASH_25`
**Label:** Cash-out date explicit
**Stage:** all | **Geography:** all | **Sector:** all | **Model format:** spreadsheet only
**Pass:** Clear month when cash hits zero.
**Warn:** Calculable but not highlighted.
**Fail:** Not computable.

### `CASH_26`
**Label:** Step costs captured
**Stage:** all | **Geography:** all | **Sector:** all | **Model format:** spreadsheet only
**Pass:** New hires, infrastructure thresholds.
**Warn:** Some missing.
**Fail:** Expenses flat while revenue scales.

### `CASH_27`
**Label:** OpEx scales with revenue
**Stage:** all | **Geography:** all | **Sector:** all | **Model format:** spreadsheet only
**Pass:** Expense growth broadly aligned.
**Warn:** Some disconnect.
**Fail:** 10x revenue with flat team.

### `CASH_28`
**Label:** FX sensitivity modeled
**Stage:** all | **Geography:** ["multi-currency"] | **Sector:** all | **Model format:** spreadsheet only
**Pass:** FX assumptions stated; +/-10-15% sensitivity on ILS/USD (or relevant pair).
**Warn:** Simplified or static rate.
**Fail:** No FX consideration despite material foreign-currency costs.

### `CASH_29`
**Label:** Entity-level cash solvent
**Stage:** all | **Geography:** ["israel", "multi-entity"] | **Sector:** all | **Model format:** spreadsheet only
**Pass:** Each entity's ending cash >=0; intercompany transfers timed.
**Warn:** Consolidated-only view noted.
**Fail:** Subsidiary can't make payroll; no entity-level view.

### `CASH_30`
**Label:** Israel statutory costs itemized
**Stage:** all | **Geography:** ["israel"] | **Sector:** all | **Model format:** spreadsheet only
**Pass:** NI + pension + severance + KH policy stated.
**Warn:** Generic "burden %" without breakdown.
**Fail:** Benefits/taxes omitted for Israeli team.

### `CASH_31`
**Label:** Government grants modeled (IIA etc.)
**Stage:** all | **Geography:** ["israel"] | **Sector:** all | **Model format:** spreadsheet only
**Pass:** Grant inflows, approval assumptions, royalty repayment liabilities.
**Warn:** Grants mentioned but not modeled.
**Fail:** IIA grants received but royalties/IP constraints omitted.

### `CASH_32`
**Label:** VAT/indirect tax cash timing
**Stage:** all | **Geography:** ["israel"] | **Sector:** all | **Model format:** spreadsheet only
**Pass:** Input VAT refund timing modeled where material; current rate reflected.
**Warn:** Simplified.
**Fail:** VAT treated as non-issue when it creates cash troughs.

---

## Category 4 — Metrics & Efficiency (3 items)

### `METRIC_33`
**Label:** KPI summary visible
**Stage:** all | **Geography:** all | **Sector:** all | **Model format:** all
**Pass:** ARR/MRR, burn, runway, GM, retention, CAC/payback on summary.
**Warn:** KPIs scattered.
**Fail:** No KPI view.

### `METRIC_34`
**Label:** Burn multiple tracked
**Stage:** seed+ | **Geography:** all | **Sector:** all | **Model format:** all
**Pass:** Computed correctly (Net Burn / Net New ARR); improving.
**Warn:** High but improving.
**Fail:** Worsening with scale; >3x.

### `METRIC_35`
**Label:** Benchmark awareness
**Stage:** all | **Geography:** all | **Sector:** all | **Model format:** all
**Pass:** Uses benchmarks as context, not proof.
**Warn:** Cherry-picking.
**Fail:** Benchmarks justify fantasy outcomes.

---

## Category 5 — Fundraising Bridge (3 items)

### `BRIDGE_36`
**Label:** Raise -> runway -> milestones -> next round
**Stage:** all | **Geography:** all | **Sector:** all | **Model format:** all
**Pass:** Clear linkage throughout.
**Warn:** Some linkage.
**Fail:** Raise amount arbitrary; no milestone plan.

### `BRIDGE_37`
**Label:** Next-round milestones identified
**Stage:** all | **Geography:** all | **Sector:** all | **Model format:** all
**Pass:** Specific KPI targets for next funding stage.
**Warn:** Vague goals.
**Fail:** No forward-looking plan.

### `BRIDGE_38`
**Label:** Dilution/ownership shown
**Stage:** seed+ | **Geography:** all | **Sector:** all | **Model format:** all
**Pass:** Cap-table impact of raise (15-25% per round typical).
**Warn:** Not included.
**Fail:** Dilution math inconsistent.

---

## Category 6 — Sector-Specific (6 items)

Mark items as `not_applicable` if the company's sector or traits don't match the gate.

### `SECTOR_39`
**Label:** Marketplace: two-sided mechanics
**Stage:** all | **Geography:** all | **Sector:** ["marketplace"] | **Model format:** all
**Pass:** CAC and retention on both sides; GMV/take-rate logic.
**Warn:** Only one side modeled.
**Fail:** Treats marketplace like one-sided SaaS.

### `SECTOR_40`
**Label:** AI: inference costs modeled
**Stage:** all | **Geography:** all | **Sector:** ["ai-native", "usage-based", "ai-powered"] | **Model format:** all
**Pass:** Gross margin incorporates model/compute costs; sensitivity on usage.
**Warn:** Weak cost calibration.
**Fail:** Ignores variable AI costs.

### `SECTOR_41`
**Label:** Hardware/deep-tech: milestones + capex
**Stage:** all | **Geography:** all | **Sector:** ["hardware", "hardware-subscription"] | **Model format:** all
**Pass:** Milestone plan + cash needs; working capital/capex considered.
**Warn:** Some milestones.
**Fail:** "SaaS-like" model applied to hardware.

### `SECTOR_42`
**Label:** Usage-based: margin at scale
**Stage:** all | **Geography:** all | **Sector:** ["usage-based"] | **Model format:** all
**Pass:** COGS scales with consumption; base vs. variable fees separated.
**Warn:** Simplified.
**Fail:** Usage costs ignored.

### `SECTOR_43`
**Label:** Consumer: retention curves
**Stage:** all | **Geography:** all | **Sector:** ["consumer-subscription"] | **Model format:** all
**Pass:** Cohort-based engagement and monetization.
**Warn:** Aggregate only.
**Fail:** No retention analysis.

### `SECTOR_44`
**Label:** Deferred revenue (if applicable)
**Stage:** all | **Geography:** all | **Sector:** ["annual-contracts"] | **Model format:** all
**Pass:** Annual upfront payments amortized correctly.
**Warn:** Simplified.
**Fail:** Cash treated as revenue.

---

## Category 7 — Overall (2 items)

### `OVERALL_45`
**Label:** "5-minute audit" possible
**Stage:** all | **Geography:** all | **Sector:** all | **Model format:** all
**Pass:** One dashboard answers: burn/runway, growth, margin, unit economics.
**Warn:** Needs hunting.
**Fail:** Investor can't orient quickly.

### `OVERALL_46`
**Label:** Country-level CAC/payback/NRR tracked (global-first)
**Stage:** all | **Geography:** ["multi-market"] | **Sector:** all | **Model format:** all
**Pass:** CAC, payback, NRR segmented by major market (US, UK, DACH, etc.).
**Warn:** Aggregate only but noted.
**Fail:** No geographic segmentation despite multi-market GTM.

---

## Canonical 46 Checklist IDs

**Structure & Presentation:** `STRUCT_01`, `STRUCT_02`, `STRUCT_03`, `STRUCT_04`, `STRUCT_05`, `STRUCT_06`, `STRUCT_07`, `STRUCT_08`, `STRUCT_09`

**Revenue & Unit Economics:** `UNIT_10`, `UNIT_11`, `UNIT_12`, `UNIT_13`, `UNIT_14`, `UNIT_15`, `UNIT_16`, `UNIT_17`, `UNIT_18`, `UNIT_19`

**Expenses, Cash & Runway:** `CASH_20`, `CASH_21`, `CASH_22`, `CASH_23`, `CASH_24`, `CASH_25`, `CASH_26`, `CASH_27`, `CASH_28`, `CASH_29`, `CASH_30`, `CASH_31`, `CASH_32`

**Metrics & Efficiency:** `METRIC_33`, `METRIC_34`, `METRIC_35`

**Fundraising Bridge:** `BRIDGE_36`, `BRIDGE_37`, `BRIDGE_38`

**Sector-Specific:** `SECTOR_39`, `SECTOR_40`, `SECTOR_41`, `SECTOR_42`, `SECTOR_43`, `SECTOR_44`

**Overall:** `OVERALL_45`, `OVERALL_46`
