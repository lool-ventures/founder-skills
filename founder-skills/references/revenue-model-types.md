# Revenue Model Types

> **Shared reference.** Extracted from `fin-model-research/best-practices.md` (Post-ZIRP Edition, 2024-2026).
> Consolidated from per-stage "Revenue model by type" and "Revenue model checks by type" tables.
> Consumed by: `financial-model-review`, `metrics-benchmarker`, and other Tier 1+ skills.

---

## SaaS (Self-Serve / PLG)

### Structure
MRR/ARR, customer count x pricing.

### Checks by stage

| Stage | What to check |
| --- | --- |
| Pre-Seed | Activation -> conversion; churn (non-zero); plausible gross margin |
| Seed | Customer acquisition realism; churn (never zero); gross margin reflects hosting/support; conversion/retention cohorts stable or improving |
| Series A | Retention/expansion (NRR) central; cohort views; sales rep productivity and quota attainment (~70-75%) |

---

## SaaS (Sales-Led)

### Structure
Pipeline-driven revenue build with quota-based sales capacity.

### Checks by stage

| Stage | What to check |
| --- | --- |
| Seed | Pipeline mechanics, not smooth exponential curves; ramp time 60-90 days to quota |
| Series A | Retention/expansion (NRR) central; cohort views; sales rep productivity and quota attainment (~70-75%) |

---

## Transactional / Fintech

### Structure
GTV x take rate (1-3% common).

### Checks by stage

| Stage | What to check |
| --- | --- |
| Pre-Seed | Volume assumptions; unit margin per transaction |

---

## Marketplace

### Structure
GMV x take rate.

### Checks by stage

| Stage | What to check |
| --- | --- |
| Pre-Seed | Supply and demand growth; take rate; early retention both sides |
| Seed | GMV retention cohorts (best-in-class supply-side: ~100% at m12; average: ~45-50% at m12); two-sided CAC |
| Series A | Cohort GMV retention; decreasing acquisition dependency over time; two-sided CAC and retention |

---

## Hardware / Deep-Tech

### Structure
Often zero revenue at pre-seed; milestone-based. At later stages, BOM/COGS + capex-driven.

### Checks by stage

| Stage | What to check |
| --- | --- |
| Pre-Seed | Milestone-plan realism; burn vs milestone cadence; capex exposure |
| Seed | BOM/COGS and working-capital dynamics; inventory/capex as runway risks |
| Series A | Capex, COGS/BOM, working capital, milestone risk; cash burn can diverge from P&L when inventory/capex is material |

---

## Hardware + Subscription (IoT / Robotics)

### Structure
Hardware unit sale or lease + recurring service/subscription fee.

### Checks by stage

| Stage | What to check |
| --- | --- |
| Pre-Seed | Blended gross margin (hardware vs. software); unit deployment rate; manufacturing lead times; subscription retention |
| Seed | Separate hardware COGS from recurring service margin; unit deployment rate tied to manufacturing capacity; subscription churn != hardware churn |
| Series A | Blended margin trajectory (hardware margin + service margin); manufacturing scale economics; unit deployment rate vs production capacity; subscription retention by vintage; field service / maintenance costs as COGS |

---

## Usage-Based / AI

### Structure
Revenue tied to consumption or usage metrics; may include base fee + variable component.

### Checks by stage

| Stage | What to check |
| --- | --- |
| Seed | Don't confuse usage revenue with recurring revenue; gross margin incorporates usage costs |
| Series A | Revenue tied to end-customer business metrics; ramp patterns; overage assumptions; revenue volatility risk |

### AI-specific guidance
Bessemer's "State of AI 2025" introduces "Supernovas" (extreme scale, often low/negative margins) and "Shooting Stars" (more durable SaaS-like). They propose **Q2T3** (quadruple, quadruple, triple, triple, triple) as an updated growth benchmark for AI Shooting Stars. AI models must explicitly account for inference/compute costs in gross margin — "SaaS-like 80% GM forever" is often wrong. Sub-1x burn multiple is increasingly expected for AI-native companies.

---

## Consumer Subscription

### Structure
Install -> registration -> trial -> pay conversion funnel with plan mix (monthly vs annual).

### Checks by stage

| Stage | What to check |
| --- | --- |
| Series A | Install -> registration -> trial -> pay conversion; retention cohorts; plan mix (monthly vs annual); CAC by channel |
