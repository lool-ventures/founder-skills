# Model Structure and Formatting Standards

> **Shared reference.** Extracted from `fin-model-research/best-practices.md` (Post-ZIRP Edition, 2024-2026).
> Used by `extract_model.py` for structural validation.
> Consumed by: `financial-model-review`, `metrics-benchmarker`, and other Tier 1+ skills.

---

## Tab Organization

| Tab | Purpose |
| --- | --- |
| Cover / Dashboard | Executive summary, key KPIs, funding ask, cap table summary |
| Assumptions (Inputs) | All changeable variables in one place — growth rates, pricing, hiring dates, salaries, tax rates |
| Revenue Build | Bottom-up revenue model with driver mechanics |
| Headcount / OpEx | Role-based hiring plan driving payroll, benefits, and operational costs |
| Financial Statements | P&L, cash flow, balance sheet (if appropriate for stage) |
| KPIs & Charts | Visual summary of key metrics — burn, runway, growth, unit economics |
| Scenarios | Base/upside/downside toggles; sensitivity tables at seed/Series A |

### Additional tabs for Israel / multi-entity startups

| Tab | Purpose |
| --- | --- |
| Entities & FX | Reporting currency, FX assumptions + scenarios, entity cash waterfalls, intercompany transfers |
| Geo Payroll Calculator | Comp by geography, statutory burdens per geography, benefits policy (KH yes/no, Section 14, etc.) |

---

## Formatting Rules

- **Color coding:** Blue text = hardcoded inputs; black text = formulas; green text = cross-sheet links
- **No merged cells** — use "Center Across Selection" instead
- **Inputs isolated** — a reviewer should never hunt through calculation sheets to find a variable
- **Time series alignment** — columns represent the same period across all tabs
- **Monthly granularity** — at minimum for the operating horizon (12-24 months pre-seed; 24-36 months seed/Series A)
- **Actuals vs. projections** clearly delineated (visual separator, color change, or label)
- **Version and date** on the model
- **Standard sign conventions** — consistent use of positive/negative throughout

---

## Internal Consistency Checks

These are the cross-validations investors run on first pass:

| Check | What must reconcile |
| --- | --- |
| Revenue vs. customer math | Revenue = customers x ARPU; new ARR reconciles to pipeline x sales capacity x attainment |
| Headcount vs. expenses | Salaries, taxes, benefits tie directly to headcount by role and geography |
| Cash vs. burn/runway | Ending cash = prior cash + net cash flow; runway = cash / monthly net burn |
| Unit economics vs. P&L | CAC/LTV tabs roll to total revenue, COGS, and S&M spend |
| Balance sheet (if present) | Assets = Liabilities + Equity; ending cash on CF = cash on BS; net income flows to retained earnings |
| Working capital | AR/AP changes reflected in cash flow; collection/payment timing modeled where material |
| Metrics vs. model | Burn multiple, Rule of 40, payback, NRR computed from model are internally consistent |

### Additional consistency checks for multi-entity / Israel startups

- **FX check:** USD burn reconciles to local payroll x FX rate; scenario toggle changes cash runway mechanically
- **Entity solvency check:** Each entity's ending cash stays >=0 (especially Israel sub payroll)
