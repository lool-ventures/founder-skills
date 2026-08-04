# Evaluation Criteria

28 dimensions across 7 categories for scoring a startup's IC readiness. Each dimension is evaluated by the agent (LLM) based on available evidence, then scored computationally by `score_dimensions.py`.

## Status Values

Each dimension receives one of 5 statuses:

| Status | Meaning | Score Weight |
|--------|---------|-------------|
| `strong_conviction` | Clear evidence of strength. Partners would cite this as a reason to invest. | 1.0 |
| `moderate_conviction` | Adequate evidence. Not a standout but not a concern either. | 0.5 |
| `concern` | Weakness identified. Partners would raise this in discussion. | 0.0 |
| `dealbreaker` | Fatal flaw. Any single dealbreaker forces a `hard_pass` verdict. | 0.0 (forces hard_pass) |
| `not_applicable` | Dimension doesn't apply to this company's stage or model. | excluded |
| `to_confirm` | The materials don't disclose the data to judge this dimension — UNKNOWN, not weak. | excluded |

**`to_confirm` vs `concern` vs `not_applicable` — this drives the verdict.** Use `to_confirm` ONLY
when the data is simply undisclosed and the founder could supply it; it is neutral, so honest
non-disclosure never drags the score to a false decline. Use `concern` when the evidence you DO have
is weak or negative — **absence that is itself evidence of weakness is NOT `to_confirm`** (no traction
at a large ask, no unit economics at Series A: the absence is the finding). Use `not_applicable` only
when the dimension structurally cannot apply, e.g. a SaaS metric for a hardware company.

## Scoring Formula

```
applicable = count of items where status is neither "not_applicable" nor "to_confirm"
conviction_score = (strong*1.0 + moderate*0.5) / applicable * 100
```

Both excluded statuses leave the denominator. `to_confirm` in particular must not deflate the score:
a dimension the materials never addressed is not a weakness, and counting it as one would penalise a
founder for a question nobody asked.

**Coverage cap.** More than 6 `to_confirm` dimensions holds the verdict at `more_diligence` in BOTH
directions — capped down from `invest` (thin coverage cannot earn conviction) and floored up from
`pass` (you cannot decline a company on the grounds that you weren't told anything).

### Verdicts

| Score Range | Verdict | Meaning |
|-------------|---------|---------|
| >= 75% | `invest` | Strong enough for a term sheet discussion |
| >= 50% | `more_diligence` | Promising but needs more evidence on key dimensions |
| < 50% | `pass` | Too many concerns to proceed at this time |
| any dealbreaker | `hard_pass` | Fatal flaw identified — cannot proceed regardless of score |

### Zero-Applicable Edge Case

If all 28 dimensions are marked `not_applicable` (or no items provided), the score is `0.0` and the verdict is `more_diligence` with a `ZERO_APPLICABLE_DIMENSIONS` warning. This prevents false positives from empty evaluations.

## Categories and Dimensions

### Team (4 dimensions)

| ID | Dimension | Description |
|----|-----------|-------------|
| `team_founder_market_fit` | Founder-Market Fit | Do the founders have unique insight, domain expertise, or unfair advantage in this market? Have they lived the problem they're solving? |
| `team_complementary_skills` | Complementary Skills | Does the founding team cover the critical bases (technical, commercial, domain)? Are there obvious gaps that need to be filled? |
| `team_execution_speed` | Execution Speed | Is the team shipping fast relative to their resources? Evidence of rapid iteration, quick pivots, and bias toward action. |
| `team_coachability` | Coachability | Does the founding team take feedback well? Evidence of adapting based on customer/investor/advisor input. Defensiveness is a red flag. |

**Stage calibration:**
- **Pre-seed:** Founder-market fit and coachability matter most. Team gaps are expected and acceptable.
- **Seed:** Complementary skills become important. Solo founders need a plan to build the team.
- **Series A:** Full team evaluation. Execution speed must be demonstrated, not just claimed.

### Market (4 dimensions)

| ID | Dimension | Description |
|----|-----------|-------------|
| `market_size_credibility` | Size Credibility | Is the stated market size credible and well-sourced? Bottom-up > top-down. Segment-specific > total industry. |
| `market_timing` | Timing | Is there a clear macro catalyst (regulatory, technological, behavioral) that makes now the right time? |
| `market_growth_trajectory` | Growth Trajectory | Is the market growing, stable, or shrinking? What's the CAGR? Are tailwinds accelerating? |
| `market_entry_barriers` | Entry Barriers | How hard is it for new competitors to enter? Regulatory barriers, network effects, switching costs, or technical complexity. |

**Stage calibration:**
- **Pre-seed:** Market insight matters more than precise sizing. A compelling "why now" can compensate for loose TAM.
- **Seed:** Market size should be bottom-up sourced. Timing argument should be concrete.
- **Series A:** Market must be large enough for fund-returning outcomes. Growth trajectory must be validated with data.

### Product (4 dimensions)

| ID | Dimension | Description |
|----|-----------|-------------|
| `product_differentiation` | Differentiation | What makes this product meaningfully different from alternatives? Feature parity is not differentiation. |
| `product_traction_evidence` | Traction Evidence | Concrete proof of product-market fit: revenue, users, engagement metrics, LOIs, waitlist size. Stage-appropriate. |
| `product_technical_moat` | Technical Moat | Is there something technically difficult to replicate? Proprietary data, unique architecture, patents, or deep domain-specific engineering. |
| `product_user_love` | User Love | Do users/customers actively love the product? NPS, unsolicited referrals, retention data, customer quotes. |

**Stage calibration:**
- **Pre-seed:** Differentiation and early signal (waitlist, LOIs) suffice. Technical moat can be a plan.
- **Seed:** Traction evidence must be concrete (paying customers). User love should be demonstrable.
- **Series A:** All four dimensions should show strength. Technical moat must be built, not planned.

### Business Model (4 dimensions)

| ID | Dimension | Description |
|----|-----------|-------------|
| `biz_unit_economics` | Unit Economics | Are per-unit economics positive or trending positive? LTV/CAC, contribution margin, payback period. |
| `biz_pricing_power` | Pricing Power | Can the company raise prices without losing customers? Evidence of value-based pricing vs. cost-plus. |
| `biz_scalability` | Scalability | Does the business model scale without proportional cost increases? Marginal cost of serving the next customer. |
| `biz_gross_margins` | Gross Margins | Are gross margins appropriate for the business type? Software: >70%. Services: >40%. Hardware: >30%. |

**Stage calibration:**
- **Pre-seed:** Business model hypothesis is sufficient. Pricing experiments are a plus.
- **Seed:** Unit economics should be emerging. Pricing should be tested with real customers.
- **Series A:** Unit economics must be proven and improving. Gross margins should be at or approaching target.

### Financials (4 dimensions)

| ID | Dimension | Description |
|----|-----------|-------------|
| `fin_capital_efficiency` | Capital Efficiency | How much value is created per dollar spent? Revenue per dollar raised, headcount efficiency. |
| `fin_runway_plan` | Runway Plan | Does current/planned funding provide enough runway to hit milestones for the next round? |
| `fin_path_to_next_round` | Path to Next Round | Are the milestones for the next funding round clearly defined and achievable within the runway? |
| `fin_revenue_quality` | Revenue Quality | Is revenue recurring, predictable, and diversified? Or lumpy, one-time, and concentrated? |

**Stage calibration:**
- **Pre-seed:** Capital efficiency is about burn rate discipline. Revenue quality is N/A.
- **Seed:** Runway plan should cover 18-24 months. Revenue quality should be emerging.
- **Series A:** All financial dimensions should be well-evidenced. Revenue quality is critical.

### Risk (4 dimensions)

| ID | Dimension | Description |
|----|-----------|-------------|
| `risk_single_point_failure` | Single Point of Failure | Is the business dependent on one customer, one supplier, one platform, one regulation, or one person? |
| `risk_regulatory` | Regulatory Risk | Is the business exposed to regulatory change? How well-prepared is the team for regulatory shifts? |
| `risk_competitive_response` | Competitive Response | What happens when incumbents or well-funded startups respond? How defensible is the position? |
| `risk_customer_concentration` | Customer Concentration | Is revenue diversified across customers? Top customer <20% of revenue at seed, <10% at Series A. |

**Stage calibration:**
- **Pre-seed:** Some concentration is expected. Key risk: founder dependency (no team backup).
- **Seed:** Concentration should be decreasing. Regulatory awareness should be evident.
- **Series A:** No single point of failure should remain unaddressed. Customer diversification is expected.

### Fund Fit (4 dimensions)

| ID | Dimension | Description |
|----|-----------|-------------|
| `fit_thesis_alignment` | Thesis Alignment | Does this investment align with the fund's stated investment thesis and focus areas? |
| `fit_portfolio_conflict` | Portfolio Conflict | Does the fund already have a conflicting investment? Direct overlap, customer overlap, or adjacent market. |
| `fit_stage_match` | Stage Match | Is this company at the right stage for the fund's typical investment? Check size, ownership targets, support model. |
| `fit_value_add` | Value-Add Potential | Can the fund add meaningful value beyond capital? Relevant portfolio companies, domain expertise, key relationships. |

**Stage calibration:**
- Applies equally across all stages
- In generic mode: evaluate against the validated generic `fund_profile.json` — canonical archetypes
  and a stated early-stage thesis. **Never invent a hypothetical fund thesis, in either mode**;
  `FUND_PROFILE` is an input, not something the model authors.
- In fund-specific mode: evaluate against the researched fund's actual thesis, portfolio, and focus

---

## Appendix: SaaS Metrics Reference

Canonical formulas and thresholds for SaaS-specific metrics referenced in evaluations. Use these definitions exactly — do not improvise alternative formulas.

**If required inputs for a metric are not available from the startup's materials, state this explicitly — do not estimate or assume values.**

| Metric | Formula | Key Thresholds | Stage Relevance |
|--------|---------|---------------|-----------------|
| Magic Number | `(Qtr Rev - Prev Qtr Rev) * 4 / Prev Qtr S&M` | >1.0 efficient, 0.5–1.0 moderate, <0.5 inefficient | Meaningful at Series A with quarterly revenue data. Pre-seed/seed: rarely available, do not require. |
| Burn Multiple | `Net Burn / Net New ARR` | <1.5x good, 1.5–2.0x acceptable early, >3.0x red flag | Useful at seed with ARR trajectory. Pre-seed: typically N/A (no ARR). |
| Rule of 40 | `Rev Growth % + Profit Margin %` | >40% strong, 20–40% acceptable early, <20% concerning | Series A and later. Pre-seed/seed: growth should dominate; margin is secondary. Note: some firms use "Rule of X" (`Growth % × 2 + FCF Margin %`) which weights growth more heavily — do not substitute without stating which variant is used. |
| CAC | `Total S&M / New Customers` | Varies by ACV; break down by channel at Series A | Seed: blended CAC is useful. Series A: channel-level CAC expected. Pre-seed: too early. |
| New CAC Ratio | `S&M / New Customer ARR` | <$1.50 good, $1.50–$2.00 acceptable, >$2.00 expensive (2025 median $2.00) | Series A+. Isolates pure acquisition cost from expansion revenue. Use alongside Blended CAC Ratio. |
| Blended CAC Ratio | `S&M / (New Customer ARR + Expansion ARR)` | Lower is better; compare to New CAC Ratio to see expansion leverage | Series A+. Shows how expansion revenue amortizes acquisition cost. |
| LTV/CAC | `(ARPA × Gross Margin / Churn) / CAC` | >3.0x healthy, <1.0x unsustainable | Seed: directional estimate acceptable. Series A: must be computed with real data. Pre-seed: N/A. |
| NDR (Net Dollar Retention) | `(Beg ARR + Expansion - Contraction - Churn) / Beg ARR` | >130% elite, 110–130% good, <100% concerning | Meaningful at seed with 6+ months of cohort data. Series A: expected. Pre-seed: N/A. Always pair with GRR — high NDR can mask high base churn if expansion from a few large accounts dominates. |
| GRR (Gross Revenue Retention) | `(Beg ARR - Churn - Contraction) / Beg ARR` | >95% elite, 90–95% strong, 85–90% acceptable, <85% concerning | Same as NDR: meaningful at seed with 6+ months of cohort data. Series A: expected alongside NDR. Pre-seed: N/A. Shows the "leaky bucket" baseline — churn and contraction only, no expansion. |
| CAC Payback | `CAC / (ARPA × Gross Margin)` | <12mo excellent, 12–18mo good, >24mo concerning (enterprise ACV may tolerate up to 24mo due to high LTV and low churn) | Seed: useful if data available. Series A: expected. Pre-seed: too early. |
| ARR per Employee | `Total ARR / Headcount` | >$150K good early-stage, $200K–$300K+ at scale (AI-native companies often 4–5× higher) | Seed onward as a capital-efficiency signal. Pre-seed: team too small for this to be meaningful. |
| Gross Margin | (cross-ref `biz_gross_margins` dimension) | SaaS >70% (top-tier >75%), marketplace >60%, services >40%. AI-native companies may run 25–60% due to inference/infra costs — flag but do not penalize if acknowledged with a path to improvement. | All stages. Pre-seed: target margins acceptable. Seed+: actual margins expected. |

---

## Appendix: Concern vs. Dealbreaker Thresholds

When evaluating a dimension, the boundary between `concern` and `dealbreaker` determines whether the startup gets a "work on this" signal or a hard pass. The following guidance covers the highest-impact dimensions per category.

**General rule:** When uncertain, default to `concern`. A dealbreaker is a finding so severe that no amount of strength in other areas can compensate — it makes the investment fundamentally unworkable.

| Category | Dimension | Dealbreaker if... |
|----------|-----------|-------------------|
| **Team** | `team_founder_market_fit` | Founders have zero relevant domain experience AND cannot articulate a credible "why me" — no lived experience, no unfair insight, no relevant network. |
| **Team** | `team_coachability` | Founders are actively hostile to feedback or have a documented pattern of ignoring advisor/investor input across multiple interactions. |
| **Market** | `market_size_credibility` | The addressable market is provably too small for fund-returning outcomes (e.g., niche with <$100M SAM and no plausible expansion path). |
| **Product** | `product_traction_evidence` | At seed+: zero paying customers AND no credible pipeline (LOIs, pilots, waitlist) after 6+ months of effort. Pre-seed: this dimension is rarely a dealbreaker. |
| **Business Model** | `biz_unit_economics` | At Series A: unit economics are negative with no improvement trend AND the business model has no structural path to positive unit economics. |
| **Financials** | `fin_runway_plan` | Runway is <6 months with no funding pipeline and milestones are unachievable within remaining capital. |
| **Risk** | `risk_single_point_failure` | Business depends entirely on a single customer (>80% revenue), single platform (no migration path), or single regulation that is actively under threat. |
| **Risk** | `risk_regulatory` | The core business activity is illegal in key target markets or faces imminent regulatory prohibition with no pivot path. |
| **Fund Fit** | `fit_portfolio_conflict` | Direct, blocking portfolio conflict — the fund already has an investment in a direct competitor in the same market segment. |
