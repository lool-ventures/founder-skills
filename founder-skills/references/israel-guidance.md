# Israel Guidance

> **Shared reference.** Extracted from `fin-model-research/best-practices.md` (Post-ZIRP Edition, 2024-2026), Israel Addendum.
> Consumed by: `financial-model-review`, `metrics-benchmarker`, and other Tier 1+ skills.

---

Israel is not just a "cheaper engineers" line item — it is a **structure + currency + compliance + incentives** modeling problem. Israeli startups competing for global capital are benchmarked against US/global standards, but their models must reflect the operational realities of "Israel R&D + global GTM."

---

## Corporate Structure

Most Israeli startups targeting global markets operate as a **Delaware C-Corp parent with an Israeli subsidiary** (the "flip"). This dual-entity structure has direct modeling implications:

- **Investor view:** Consolidated model in **USD** (most global rounds are USD-denominated)
- **Operator reality:** Add an **Entity Cash** view that tracks:
  - US parent cash (where fundraise lands)
  - Israel subsidiary cash (where the bulk of payroll burns)
  - Intercompany transfer cadence (monthly/quarterly) and banking/FX fees
- **Why it matters:** It is common to appear solvent on a consolidated dashboard while the Israeli subsidiary is about to miss payroll due to transfer lag

At early stages, keep the investor model consolidated (ignore intercompany revenue) but maintain an entity-level cash plan with "intercompany funding" lines.

---

## Multi-Currency Sensitivity (USD / ILS)

Israeli startups raise in USD but pay R&D salaries in ILS. This creates an "invisible" runway risk.

**Required model elements:**
- In Assumptions: **FX rate** (ILS/USD), with sensitivity **+/-10-15%**
- In Hiring/OpEx: Salaries and rent in local currency, converted to USD using the FX assumption
- In Cash: Conversion timing and bank fees

A 10-15% ILS strengthening (fewer shekels per dollar) can shave 2-4 months off runway without any operational change. Models should include a "currency shock" scenario.

---

## Israel Payroll Fully Loaded Cost Stack

The generic "25-35% burden" heuristic is correct but hides the components. For Israeli R&D teams, model explicitly:

| Component | Employer rate | Notes |
| --- | --- | --- |
| National Insurance + Health | 3.55% (up to threshold) / 7.6% (above) | Tiered on salary. Threshold ~7,522 ILS/mo (2025). Rates increased 0.8% in Jan 2025. |
| Mandatory pension | 6.5% | Employer contribution to pension fund |
| Severance accrual | 8.33% | Monthly accrual (equivalent to 1 month/year). Can top up to full Section 14 coverage. |
| Keren Hishtalmut (training fund) | Up to 7.5% | Not mandatory but standard in tech. State whether offered. |
| **Total mandatory** | **~19-23%** | NI + pension + severance |
| **Total with KH + misc** | **~25-35%** | Recruiting fees (1-2 months salary for senior roles), meal/transport allowances |

**Recruiting costs matter:** Israeli R&D headhunters charge 1-2 months' salary for senior engineers. This is a step-cost that belongs in the hiring tab, not a percentage assumption.

**Travel budget:** For global-first startups, founder/exec travel (TLV <-> NYC/SF) is not a rounding error. Budget $50-100K/year as a dedicated line item for sync weeks and customer visits.

---

## VAT and Indirect Taxes (Cash Timing)

Israel VAT is **18%** (effective January 1, 2025, raised from 17%).

- For export-heavy startups (selling to non-Israeli customers), revenue may be **zero-rated** for VAT, but **input VAT on local spend** still impacts cash timing — refund processing can take weeks/months
- For startups with domestic Israeli revenue, VAT affects pricing and collections
- This is a **cash flow** issue, not a P&L issue. Model the timing impact where material.

---

## Israel Innovation Authority (IIA) Grants

IIA grants are a major differentiator for Israeli startups — non-dilutive capital that can materially extend runway and de-risk R&D milestones.

### Startup Fund grant rates (2024-2025)

| Stage | Grant as % of round | Cap |
| --- | --- | --- |
| Pre-Seed | Up to 60% | ~NIS 1.5M (~$400K) |
| Seed | Up to 50% | ~NIS 5M |
| Series A | Up to 30% | ~NIS 15M |

Preferred companies (underrepresented founders, periphery-based) receive an additional 10%.

**R&D Fund grants:** 20-50% of approved R&D budget (up to 75-85% for certain programs).

### Modeling rules
- Treat grants as **direct offset to R&D/OpEx** (reduces net burn) or "grant income"
- Include **grant approval sensitivity** (with/without approval scenarios)
- Model **royalty repayment**: 3-5% of relevant revenues, payable once product is commercialized, until full grant + interest is repaid (cap varies by program, often 100% of grant + SOFR interest)
- For acquisitions/IP transfers abroad: repayment can be **accelerated** and may substantially exceed the original grant amount. This is a critical diligence item.
- Highlight in "so what" bridge: "Grant leverage extends runway X months and de-risks R&D milestones"

**IP transfer constraints:** IIA-funded companies face restrictions on transferring know-how/IP outside Israel. This must be disclosed in the data room and understood by investors — it can affect M&A terms.

---

## Preferred Enterprise Tax Regime

Israel corporate tax rate is **23%** (2025-2026). However, qualifying tech companies can access the **Preferred Enterprise** regime with effective rates of **7.5-16%** depending on location and conditions.

- Ignore taxes at pre-seed unless profitable
- Introduce tax only if you can model it correctly (or have professional help)
- **Section 102** equity plans provide tax-efficient employee option structures — common and expected by Israeli employees

---

## Israel-Specific Round Timing

Funding cycles in Israel have lengthened materially:
- **Seed -> Series A:** Average ~35 months (up from 18 months in 2019)
- **Series A -> Series B:** Average ~30 months

This makes 24-36 month runway guidance *especially* critical for Israeli teams. The Seed "so what" bridge should not assume a 12-18 month gap to Series A.

---

## Additional Model Tabs for Israel / Multi-Entity Startups

Add to the standard tab structure:

| Tab | Purpose |
| --- | --- |
| Entities & FX | Reporting currency, FX assumptions + scenarios, entity cash waterfalls, intercompany transfers |
| Geo Payroll Calculator | Comp by geography, statutory burdens per geography, benefits policy (KH yes/no, Section 14, etc.) |

### Additional consistency checks
- **FX check:** USD burn reconciles to local payroll x FX rate; scenario toggle changes cash runway mechanically
- **Entity solvency check:** Each entity's ending cash stays >=0 (especially Israel sub payroll)

---

## Modeling pattern: Hardware + subscription Israeli startups

Israeli startups combining hardware deployment with recurring subscription revenue (IoT, robotics, agtech, medtech devices) hit nearly every "hard" modeling pattern in this guide simultaneously. These companies are common in the Israeli ecosystem and require special attention.

**Key modeling challenges:**

| Challenge | What the model must handle |
| --- | --- |
| **Hardware + subscription hybrid** | Separate hardware COGS (BOM, logistics, deployment) from recurring service margin. Track blended gross margin trajectory as the subscription base grows relative to new deployments. |
| **Manufacturing working capital** | Units must be manufactured before deployment — inventory accumulation drains cash before revenue recognition. Each hardware iteration changes the BOM. |
| **Israel R&D + global operations** | R&D and manufacturing in Israel; customers primarily abroad. Classic dual-entity structure with all the FX and entity-cash implications above. |
| **Grant dependencies** | IIA and/or EU grants fund early R&D. Must model grant inflows, royalty repayment (3–5% of revenue), and IP transfer constraints. |
| **Multi-currency manufacturing** | Production costs in ILS; revenue in USD. FX sensitivity directly impacts per-unit production cost and blended margin. |
| **Unit economics complexity** | LTV must account for hardware deployment cost, ongoing service costs (field maintenance, connectivity), and subscription retention by deployment vintage. |
| **Milestone-based scaling** | Each hardware generation improves economics. Model must tie manufacturing iterations to margin improvement and deployment rate to production capacity. |
| **Seasonality** | Many hardware verticals (agtech, construction, energy) have seasonal deployment windows that affect revenue timing and cash flow. |

**Key model questions investors will ask:**
1. What is the per-unit gross margin on hardware deployment vs. the recurring subscription margin?
2. How does manufacturing scale change BOM cost? (Show the iteration improvement curve.)
3. What is the subscription retention rate by deployment vintage?
4. How do grant royalties affect long-term gross margin as revenue scales?
5. What is the FX sensitivity on per-unit production cost (ILS manufacturing → USD revenue)?
6. What happens to cash if multiple production cycles of inventory must be pre-funded before a seasonal deployment window?

SaaS benchmarks (NRR, magic number, burn multiple) don't map cleanly onto hardware + subscription models. For these companies, the model must center on **unit economics per deployed device**, **blended margin trajectory**, **manufacturing cash cycle**, and **seasonal deployment capacity** — alongside the standard Israel-specific requirements (FX, entity cash, grant royalties).

---

## Key Sources

| Source | Date |
| --- | --- |
| Startup Nation Central, "Israeli Tech Funding 2025" | H1 2025 |
| Israel Innovation Authority, program guidelines | 2024-2025 |
| Bituach Leumi (National Insurance Institute) | 2025-2026 |
| PwC Tax Summaries, Israel | 2025-2026 |
| CWS Israel, "2025 Israeli Payroll Updates" | 2025 |
| Knesset press release (VAT increase) | Dec 2024 |
