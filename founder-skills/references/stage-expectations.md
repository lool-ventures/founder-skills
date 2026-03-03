# Stage-by-Stage Expectations

> **Shared reference.** Extracted from `fin-model-research/best-practices.md` (Post-ZIRP Edition, 2024-2026).
> Consumed by: `financial-model-review`, `metrics-benchmarker`, and other Tier 1+ skills.

---

## Context: The Post-ZIRP Shift

The financial model is no longer a fundraising decoration. Post-ZIRP investors treat it as a **signal of founder judgment** — evidence that you understand the economic machinery of your business and can tie numbers to a credible execution plan. Sequoia's 2022 materials frame this as the shift from "risk on" (story-driven) to "risk off" (reality/financials-driven), emphasizing that the connection from **story -> metrics -> financials** must be tight.

Capital efficiency expectations are materially higher than the 2020-2021 era. Kruze reports that startups averaged ~22 months of runway in 2024, while a meaningful share had <=6 months. Investors now scrutinize burn and runway as survival variables.

**Three properties of a good model:**
1. **Driver-based and milestone-oriented** — built from atomic units (customers, transactions, usage), not TAM arithmetic
2. **Cash-truthful** — runway = cash balance / monthly burn, using net cash (cash minus drawn debt); cash-flow dynamics (inventory, capex, collection lags) can make runway far shorter than P&L suggests
3. **Reviewable** — consistent with the deck, internally consistent across tabs, clear where actuals stop and projections begin

---

## Pre-Seed

### What investors expect
A simple, driver-based operating model that answers: *What happens to my money if I give it to you?* Not a sophisticated three-statement build. a16z says detailed 3-5 year projections are often not useful at this stage; they want **12-18 month milestones** and what's required to hit them.

**Format:** 1-3 tabs (assumptions, monthly P&L + cash, hiring/metrics). Google Sheets or Excel. A full 5-year model with tax schedules and working capital at this stage signals over-engineering, not sophistication.

### Minimum viable model
- **Monthly cash runway plan** (12+ months; 18+ is materially better) with a clear hiring plan and core non-payroll costs
- **Bottom-up revenue build** showing unit logic (customers x pricing x frequency), even if revenue is near-zero — never market share math
- **"Raise -> runway -> milestones" bridge:** what the round buys you, and what proof you'll have for the next round

### Key metrics to track
- Monthly burn and runway (target 12-18 months post-raise; 18-24 ideal in tight markets)
- Basic TAM/SAM as a sanity check only
- If early revenue exists: basic retention/usage and contribution economics
- LTV/CAC is a hypothesis at this stage — acceptable if grounded in assumptions, not acceptable as "LTV will be huge"

### Revenue model by type
| Model | Structure | First checks |
| --- | --- | --- |
| SaaS | MRR/ARR, customer count x pricing | Activation -> conversion; churn (non-zero); plausible gross margin |
| Transactional/fintech | GTV x take rate (1-3% common) | Volume assumptions; unit margin per transaction |
| Marketplace | GMV x take rate | Supply and demand growth; take rate; early retention both sides |
| Hardware/deep-tech | Often zero revenue; milestone-based | Milestone-plan realism; burn vs milestone cadence; capex exposure |
| Hardware + subscription (IoT/robotics) | Hardware unit sale or lease + recurring service/subscription fee | Blended gross margin (hardware vs. software); unit deployment rate; manufacturing lead times; subscription retention |

### Unit economics rigor
Directional is acceptable. "We expect 75-80% gross margin at scale, CAC in low hundreds" works if the model shows the unit view. What's not acceptable: hand-waving without showing mechanics.

### Projection realism
Projections are expected to be wrong; they must be *coherent and falsifiable*. a16z warns projections shouldn't be "vastly different" from historical data where it exists.

**Red flags:** Zero churn forever; conversion rates without a funnel; flat headcount while revenue scales; cash/runway math that doesn't reconcile; hockey-stick revenue with no sales hires.

### Presentation standards
- One "Assumptions / Inputs" area and one clean output view
- Clear distinction between actuals and projections (highlight projections, mark actuals)
- No sensitivity tables needed, but a simple scenario toggle ("base vs. conservative") earns bonus points

### The "so what" bridge
Raise $X -> monthly burn/runway -> milestones in ~12-18 months -> what is de-risked for seed. Sequoia recommends planning to raise **~12 months before** you run out of cash.

---

## Seed

### What investors expect
A model that can be diligenced in a few minutes and debated for an hour. A **driver-based spreadsheet** with monthly granularity for the operating horizon, plus longer-term shape.

**Format:** 5-10 tabs: Assumptions, Revenue Build, Headcount/OpEx, Summary/Dashboard, Scenarios. P&L + cash flow at minimum; balance sheet if you have professional CFO capacity (Kruze warns against including balance sheet/cash flow unless you can model them correctly).

### Minimum viable model
- **Monthly forecast for 18-36 months** (24-36 months in tight markets), including hiring timing and fully loaded people costs
- **Revenue build explicitly tied** to funnel/pipeline/usage drivers appropriate to the business model
- **Cash runway plan** — runway expectations are market- and investor-dependent: **18-24 months** is the standard target for many seed rounds; **24-36 months** is increasingly preferred when rounds are large or capital markets are tight (Burkland view); ~12 months is flagged as risky
- **Base case + at least one sensitivity** (e.g., CAC higher, conversion lower, sales cycle longer)

### Revenue model checks by type
| Model | First checks |
| --- | --- |
| SaaS (self-serve/PLG) | Customer acquisition realism; churn (never zero); gross margin reflects hosting/support; conversion/retention cohorts stable or improving |
| Sales-led SaaS | Pipeline mechanics, not smooth exponential curves; ramp time 60-90 days to quota |
| Marketplace | GMV retention cohorts (best-in-class supply-side: ~100% at m12; average: ~45-50% at m12); two-sided CAC |
| Usage-based / AI | Don't confuse usage revenue with recurring revenue; gross margin incorporates usage costs |
| Hardware | BOM/COGS and working-capital dynamics; inventory/capex as runway risks |
| Hardware + subscription (IoT/robotics) | Separate hardware COGS from recurring service margin; unit deployment rate tied to manufacturing capacity; subscription churn != hardware churn |

### Unit economics expectations
"We think LTV will be X" is only acceptable if you show formula inputs and clearly label assumed vs. observed. Fully-loaded CAC (including salaries/tools). Early cohort data (even n=5-10) is a strong plus. Mosaic notes LTV:CAC is often not helpful because cohorts are immature and CAC is rarely fully loaded.

### Projection realism
Constrain the model with **sales cycle and hiring ramp**. If you add 10 AEs, reflect ramp time, quota attainment (~70% typical per KeyBanc 2024), and support headcount. Growth without these constraints is "free."

**Red flags:** Hockey sticks; zero churn; headcount flat while revenue 10x; seasonality ignored; TAM-based revenue ("we'll capture 1% of $10B"); assuming 80% gross margin Day 1.

### Presentation standards
- Summary dashboard first, detail behind it
- Color-code inputs (blue = input cells)
- 2-3 scenarios (base/upside/downside) and simple sensitivity (churn +/-5%, CAC +/-20%)
- Highlight runway and next-round ARR milestone on summary

### The "so what" bridge
Raise $X -> 18-24 months runway -> $Y ARR + proven unit economics -> Series A at $Z valuation. Sequoia's heuristic: **(your goal) + 12 months** runway.

**Israel note:** Seed->A averages ~35 months in Israel (up from 18 months in 2019). A 24-30 month runway is the minimum; 30-36 months is safer. IIA grants can materially extend effective runway — highlight this in the bridge.

---

## Series A

### What investors expect
The model is a cornerstone diligence artifact and a test of repeatability. Investors are underwriting that additional capital scales a working machine, not a fragile prototype.

**Format:** Institutional-grade structure with driver tabs -> operating schedules -> financial statements -> KPI dashboards. Monthly detail for at least 24 months, with quarterly/annual roll-ups beyond. Actuals integrated and clearly separated from projections. A fully integrated 3-statement model is strongly preferred (near-mandatory if material working capital: hardware, marketplaces, fintech). For simple SaaS, clean P&L + cash forecast + lightweight balance sheet can still pass.

### Minimum viable model
- Two layers: a board-grade summary and the operational drivers behind it
- Monthly detail for >=24 months, quarterly/annual beyond
- Actuals integrated with obvious separation from projections
- At least two scenarios (base + downside); ideally credible upside
- Cohort-level retention and expansion (where revenue history exists)
- ARR waterfall: Beginning ARR -> New -> Expansion -> Contraction -> Churn -> Ending ARR

### AI-specific guidance
Bessemer's "State of AI 2025" introduces "Supernovas" (extreme scale, often low/negative margins) and "Shooting Stars" (more durable SaaS-like). They propose **Q2T3** (quadruple, quadruple, triple, triple, triple) as an updated growth benchmark for AI Shooting Stars. AI models must explicitly account for inference/compute costs in gross margin — "SaaS-like 80% GM forever" is often wrong. Sub-1x burn multiple is increasingly expected for AI-native companies.

### Revenue model checks by type
| Model | What investors check |
| --- | --- |
| SaaS | Retention/expansion (NRR) central; cohort views; sales rep productivity and quota attainment (~70-75%) |
| Marketplace | Cohort GMV retention; decreasing acquisition dependency over time; two-sided CAC and retention |
| Consumer subscription | Install -> registration -> trial -> pay conversion; retention cohorts; plan mix (monthly vs annual); CAC by channel |
| Hardware/deep-tech | Capex, COGS/BOM, working capital, milestone risk; cash burn can diverge from P&L when inventory/capex is material |
| Hardware + subscription (IoT/robotics) | Blended margin trajectory (hardware margin + service margin); manufacturing scale economics; unit deployment rate vs production capacity; subscription retention by vintage; field service / maintenance costs as COGS |
| Usage-based | Revenue tied to end-customer business metrics; ramp patterns; overage assumptions; revenue volatility risk |

### Unit economics expectations
Series A is where investors demand **evidence, not assertions**. Retention and expansion should be cohort-supported. Be careful with LTV:CAC — Mosaic says it's "rarely presented helpfully at Series A" due to immature cohorts and non-fully-loaded CAC. Investors trust NRR, CAC payback, and sales efficiency metrics more.

**Global-first startups** (common for Israeli companies): Track CAC, CAC payback, and NRR at least at a country/region level for major markets (US, UK, DACH, etc.). Country-level profitability reports are now best practice for SaaS companies selling across borders.

### Projection realism
Growth should be "aggressive but defensible" — tied to specific investments (new sales team, new geography, product launch) with ramp periods and capacity limits. Growth should decelerate naturally; headcount scales stepwise; churn 5-10%+ gross.

**Red flags:** Zero churn; linear expense assumptions; ignoring step costs; sustained 200%+ growth without structural explanation; margins expanding to 90% without explanation; burn multiple worsening with scale.

### Presentation standards
- Investor-navigable: summary first, drill-down available instantly
- Consistent across deck, model, and data room
- Scenario-ready with clear, limited driver differences
- One-page "model at a glance" for first review
- Hide complex calculations or put in appendix
- Dedicated tabs: Assumptions, Summary/Dashboard, Revenue Build, Hiring/OpEx, Scenarios/Sensitivity, Use-of-Funds

### The "so what" bridge
Raise $X at $Y pre -> 18-24 months runway -> $Z ARR + LTV/CAC >=3x + burn <1.5x -> Series B at 4-6x step-up valuation. Sequoia: plan to raise ~12 months before cash-out, with "goal + 12 months" runway logic. Explicit milestone table required.

**Israel note:** A->B averages ~30 months in Israel. Plan should either (a) target 24-30 months runway with a credible path to default-alive, or (b) clearly outline metrics needed to raise B from global investors on a shorter timeline.
