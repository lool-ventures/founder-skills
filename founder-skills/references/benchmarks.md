# Benchmarks

> **Shared reference.** Extracted from `fin-model-research/best-practices.md` (Post-ZIRP Edition, 2024-2026).
> Consumed by: `financial-model-review`, `metrics-benchmarker`, and other Tier 1+ skills.
> **Source dates included for staleness checking.**

---

## Seed-Stage Key Metrics and Benchmarks

| Metric | Benchmark | Source context |
| --- | --- | --- |
| Growth rate (<$1M ARR) | Median ~59% YoY; 75th percentile ~106% | SaaS Capital 2024 (2023 YoY growth), by ARR band |
| Growth rate ($1-3M ARR) | Median ~35% YoY; 75th percentile ~56% | SaaS Capital 2024 |
| Growth rate ($3-5M ARR) | Median ~35% YoY; 75th percentile ~52% | SaaS Capital 2024 |
| Burn multiple | <2.0x pass; <=1.5x top-tier; 2.0-3.0x warning; >3.0x fail unless pre-PMF | SaaS Capital/Craft 2024 |
| Magic number | >0.75 acceptable; >=1.0 strong | KeyBanc/Sapphire 2024 |
| CAC payback | <18 months (SMB); <24 months (enterprise) | Benchmarkit/KeyBanc 2024 |
| Gross margin (SaaS) | >=70% trajectory (target 75%+; AI -5 pts acceptable) | KeyBanc/Sapphire 2024 (median ~72%) |
| NRR | >100% emerging as differentiator; median ~104% at $1-5M ARR | ChartMogul 2024, High Alpha 2025 |
| LTV/CAC | >=2.5-3x projected (hypothesis + early data) | Use as sanity check; anchor on payback and burn multiple |

---

## Series A Key Metrics and Benchmarks

| Metric | Target / good | Excellent | Warning / fail | Source |
| --- | --- | --- | --- | --- |
| ARR growth | 100-200% YoY | 200%+ (with proof) | <50% YoY | Bessemer 2024, SaaS Capital |
| Burn multiple | <2.0x | <1.0x (AI-native often sub-1x) | >2.5x without path down | Craft/CFO Advisors 2025 (median 1.6x) |
| Gross margin | 70-80% | >80% (pure software) | <60% (without explanation) | KeyBanc 2024 (median ~72%; top quartile ~81%) |
| NRR | 100-110% | 110-130% | <90% | Mosaic 2023, ChartMogul 2024 |
| GRR | 85-90% | >90% | <80% | ChartMogul 2024 |
| CAC payback | 12-18 months | <12 months (3-9 months per Mosaic "excellent") | >24 months | Mosaic/KeyBanc 2024 (varies significantly by ACV) |
| Magic number | ~0.7 (median) | >=1.0 | <0.5 | KeyBanc/Sapphire 2024 |
| Rule of 40 | >=30 (growth % + FCF margin %) | >=40 | <20 | Increasingly referenced at Series A |
| ARR per FTE | $100-150K | >$150K | <$75K | Benchmarkit 2025 |

### CAC payback by ACV tier (calibrate benchmarks accordingly)
- SMB / <$5K ACV: median ~9 months
- Mid-market / $10-25K ACV: median ~15 months
- Enterprise / $25-50K ACV: median ~20 months
- Large enterprise / >$100K ACV: median ~24 months

---

## Where Sources Disagree

### Burn multiple thresholds
- **CFO Advisors 2025:** Median 1.6x; <1.5x good; <1.0x excellent (AI-native)
- **Older sources:** <2x tolerance was standard
- **Resolution:** Post-ZIRP bar is tighter. Treat <1.5x as good, <1.0x as excellent, 1.5-2.0x as acceptable, 2.0-2.5x as warning, >2.5x as fail without credible improvement path.

### CAC payback expectations
- **Mosaic (Series A):** "Excellent" = 3-9 months; "Good" = 9-18 months
- **KeyBanc 2024 survey:** Median ~20 months; top quartile ~14 months
- **Resolution:** Highly ACV-dependent. Mosaic represents venture-quality mid-market SaaS ideal; KeyBanc reflects broader market reality. Always calibrate by ACV and GTM motion — enterprise field sales naturally has longer payback.

### LTV/CAC importance
- **Traditional SaaS playbooks:** >=3:1 as primary metric
- **Current consensus (Mosaic, multiple practitioners):** LTV:CAC fragile and often mis-computed at early stage; burn multiple, CAC payback, NRR/GRR, magic number are primary
- **Resolution:** Treat LTV:CAC as secondary sanity check. Anchor decisions on CAC payback, NRR, and burn multiple. The >=3:1 rule remains useful as a reference but should not be a hard pass/fail.

### Growth benchmarks
- **SaaS Capital 2024:** Overall median ~30% YoY (includes many non-venture/mature companies)
- **Bessemer cloud portfolio:** ~200% ARR growth at $1-10M ARR
- **Resolution:** SaaS Capital reflects median private company reality. Bessemer reflects venture-quality outliers. Use SaaS Capital to flag fantasy (if far above even high percentiles without driver explanation); use Bessemer/Mosaic for "venture-scale" expectations.

### Model horizon length
- **OpenVC:** "3 years minimum when speaking with professional investors"
- **a16z:** Detailed 3-5 year projections often not expected for early-stage; prefer 12-18 month milestones
- **Resolution:** Stage-dependent. Pre-seed: 18-24 months monthly. Seed: 24-36 months monthly. Series A: 36 months monthly with optional quarterly/annual roll-forward. Carta's seed-to-A median is ~2.1 years, making a 24-month model barely sufficient.

### 3-statement models at Series A
- **ConsulteFC/AscentCFO/Gemini:** Push full 3-statement for institutional diligence
- **Kruze:** "Unnecessary complexity for most" until later stages
- **Resolution:** P&L + cash flow + cohorts sufficient for ~80% of investors. Prepare full 3-statement if raising from growth funds or have complex operations (marketplace/hardware/fintech).

---

## Hiring Cost Benchmarks

A frequently underestimated area. Benefits/tax burden on top of base salary:

| Region | Typical burden | Notes |
| --- | --- | --- |
| US (lean) | 15-25% | Narrow definition: payroll taxes + basic benefits |
| US (full) | 25-35% | All-in: 401k match, health insurance, payroll taxes, recruiting |
| Europe | 30-45%+ | Employer social charges vary widely (Belgium ~53%, Germany/France ~47%) |
| Israel (mandatory) | 19-25% | National Insurance (~3.55-7.6% tiered), pension (6.5%), severance accrual (8.33%) |
| Israel (full) | 25-35% | Mandatory + Keren Hishtalmut (up to 7.5%), recruiting, misc benefits |

**Israel payroll detail:** Statutory employer costs (NI + pension + severance) are typically ~19-23% of gross salary. With Keren Hishtalmut (common in tech — up to 7.5% employer) and other benefits, the all-in burden reaches 25-35%. For modeling, treating fully-loaded Israeli comp as **1.25-1.35x gross salary** is a reasonable rule of thumb. Founders must state whether KH is included.

Founder must specify what's included in all geographies. Models that omit benefits/taxes entirely are a fail.

---

## Geographic Nuances

Financial models cannot be evaluated in a geographical vacuum.

| Region | Valuation context | Modeling implications |
| --- | --- | --- |
| US | Highest velocity/ARR targets; benchmarks in this document are US-centric | Aggressive T2D3 growth trajectories structurally supported by market size and follow-on capital |
| Europe | 34% valuation discount at pre-seed; up to 52% at seed (Equidam 2024-25) | Longer sales cycles; higher localization OPEX; adjust growth expectations -10-20% vs US benchmarks |
| Israel (global-facing) | Valuations competitive with US/Europe for global-facing cyber, AI, SaaS, deep-tech; strong US VC participation. Some ARR-multiple discount vs Bay Area but closing fast. | Model in USD. Assume US-style efficiency benchmarks. Plan for longer inter-round gaps: Seed->A averages ~35 months; A->B ~30 months (Startup Nation Central 2025). Target 24-36 months runway. Add FX sensitivity (ILS payroll vs USD). Model IIA grants explicitly if applicable. |
| Emerging markets (LatAm, Africa) | Lowest regional valuations ($2.60-2.69M median pre-seed) | Extreme capital efficiency required; accelerated path to cash-flow breakeven; volatile follow-on availability |

**Dilution benchmarks** (Carta 2024): Seed median ~20.1%; Series A ~20.5%. Pre-seed SAFEs: median ~15.6% for $1-2M raises, ~23.7% for $5M+ raises. Note: exact figures are bracket-dependent; Carta shows different medians depending on granularity of round-size brackets used.

Israeli cap tables at Seed/A often resemble US cap tables once global funds are involved, but angel/friends-and-family rounds can be more fragmented. Ensure dead equity and legacy notes are cleaned up before institutional rounds.

---

## Key Sources

| Source | Date | Focus |
| --- | --- | --- |
| SaaS Capital, "2024 Benchmarking Private SaaS Growth Rates" | Sep 2024 | Growth percentiles by ARR band (1,500+ companies) |
| KeyBanc/Sapphire, "2024 SaaS Survey" | Oct 2024 | Magic number, CAC payback, gross margin, ARR/employee |
| ChartMogul, "SaaS Retention Report" | Sep 2024 | NRR benchmarks by ARR/ARPA |
| Bessemer, "Scaling to $100M" | Updated 2024 | Benchmark tables by ARR band |
| Bessemer, "State of AI 2025" | 2025 | AI growth benchmarks, Q2T3, AI gross margins |
| Craft Ventures, burn multiple framework | 2024 | Burn multiple tiers and interpretation |
| CFO Advisors, "2025 Burn Multiple Benchmarks" | Feb 2026 | Burn multiple by stage, AI-native comparison |
| Mosaic, "Series A Diligence" | Feb 2023 | LTV:CAC, CAC payback, benchmark ranges |
| Benchmarkit, "2025 SaaS Performance Metrics" | 2025 | ARR per FTE, efficiency metrics |
| High Alpha, "2025 SaaS Benchmarks Report" | 2025 | NRR by ARR band, growth metrics |
| Carta, fundraising insights | 2024-2026 | Dilution benchmarks, time between rounds |
| Equidam, "Global Startup Markets" | Mid-2025 | Geographic valuation discounts |
| Startup Nation Central, "Israeli Tech Funding 2025" | H1 2025 | Israel round timing, deal volume, sector breakdown |
