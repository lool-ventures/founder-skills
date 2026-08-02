# Acmecorp — the canonical capture fixture

**Everything in this directory describes ONE fictional company with ONE set of numbers.**
The landing page's gallery shows six artifacts side by side; if the deck says one revenue figure
and the model says another, the skills' own cross-artifact consistency checks will flag the
contradiction *inside the screenshots meant to prove those checks work*.

So: change a number here, change it everywhere. This file is the source of truth.

> Acmecorp is fictional. No real founder, company or deal data appears in any of these files.
> The named competitors (GitHub, Linear, Notion, Stripe, Vercel) are real companies used as
> market context — an approved choice, because a positioning map full of invented rivals reads
> as staged on a page whose whole argument is credibility.

## Company

| | |
|---|---|
| Name | **Acmecorp** |
| Product | AI-native developer tooling for indie SaaS founders — one CLI over GitHub, Linear, Stripe and Vercel |
| Stage | Seed, raising now |
| Team | 9 people; two founders, ex-Stripe (eng) and ex-Notion (product) |
| Geography | US + EU, remote |

## Traction — deck and model MUST agree

| Metric | Value | Derivation |
|---|---|---|
| MRR | **$42,000** | 140 × $300 |
| Customers | **140** | |
| ARPU | **$300/mo** | $3,600/yr |
| Growth | **11% MoM**, last 6 months | |
| ARR | **$504,000** | 42,000 × 12 |
| Gross margin | **78%** | COGS 22%, infra-heavy |
| Logo churn | **2.2%/mo** | ⇒ ~45-month average life |
| Net revenue retention | **104%** | expansion offsets churn |
| Month-18 MRR | **$183,088** | growth decaying 11% → ~7% |

Growth **decays** in the model (2.5% relative per month). Held flat at 11%, month 18 lands at
$248K — which contradicted the deck's projection on the first build of this fixture. Decay is
also simply more honest: a model assuming 11% forever is the kind of thing a reviewer should
flag, and this one should survive its own review.

## Unit economics

| Metric | Value | Derivation |
|---|---|---|
| CAC | **$2,600** | |
| LTV | **$10,530** | 300 × 0.78 × 45 |
| LTV/CAC | **4.05** | |
| CAC payback | **11.1 months** | 2,600 ÷ (300 × 0.78) |

## Cash

| Metric | Value | Derivation |
|---|---|---|
| OpEx | **$118,000/mo** | |
| Gross profit | **$32,760/mo** | 42,000 × 0.78 |
| Net burn | **$85,240/mo** | 32,760 − 118,000 |
| Cash in bank | **$980,000** | |
| Runway | **≈11.5 months** | 980,000 ÷ 85,240 |

Runway is deliberately tight. It gives the financial-model-review scenarios something real to say
(M5 needs a visible cash-out date) and it is one half of the IC-sim disagreement.

## The round

| | |
|---|---|
| Raising | **$3,000,000** |
| Pre-money | **$12,000,000** |
| Post-money | **$15,000,000** |
| Option pool | **10% post-money** (top-up) |

## Cap table, pre-round

| Holder | Shares | Note |
|---|---|---|
| Founder 1 (CEO) | 4,600,000 | common |
| Founder 2 (CTO) | 3,400,000 | common |
| Option pool (existing) | 1,000,000 | 600,000 issued / 400,000 available |
| **Fully diluted** | **9,000,000** | |

### Outstanding instruments

| Instrument | Amount | Terms | Holder |
|---|---|---|---|
| SAFE-1 | $500,000 | post-money cap **$8,000,000**, no discount | Foobar Capital LLC |
| SAFE-2 | $250,000 | post-money cap **$10,000,000**, **20% discount** | Northgate Angels LLC |
| **Total** | **$750,000** | | |

Two different caps and one discount, so the priced-round solve is real work rather than a
formality — and M4's caption promises a pre/post table with a cited rule reference.

## Why this fixture is shaped the way it is

**Contested, not weak.** M8's caption claims "two partners, one deck, opposite conclusions."
A uniformly bad company produces unanimous decline and makes that caption a lie. Acmecorp is
deliberately arguable:

- **Strong:** 11% MoM compounding, 78% gross margin, 104% NRR, credible founders, LTV/CAC 4.
- **Weak:** 11.5-month runway, a thin moat over other people's APIs (platform risk is existential
  if GitHub ships the same thing), $300 ARPU capping expansion, no enterprise motion, CAC payback
  over 11 months.

A Visionary can back the wedge and the team; an Analyst can refuse on moat and runway; an
Operator can sit in the middle on GTM. That is a real debate, not a manufactured one.

**Mid-range on the deck, on purpose.** The deck is a plausible seed deck with realistic gaps —
a top-down-only market slide, a self-flattering competition checklist, no use-of-funds. It should
land around *needs work*, not *major revision*. M3 is the flagship gallery still, and a nuanced
critique sells the product better than a bloodbath while staying honest.

## Files

| File | Used by |
|---|---|
| `acmecorp-seed-deck.txt` | deck review, competitive positioning, IC simulation, market sizing |
| `acmecorp-model.xlsx` | financial model review |
| `acmecorp-cap-table.xlsx` | cap table (holders + pool) |
| `acmecorp-safe-1.txt`, `acmecorp-safe-2.txt` | cap table (instruments) |
| `build_xlsx.py` | regenerates both spreadsheets from the constants above — **edit the script, never the .xlsx by hand** |

**Founder names are role labels, not invented people.** A cap table screenshot with plausible
human names risks colliding with someone real; "Founder 1 (CEO)" cannot. Override if you would
rather have names.
