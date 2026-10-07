# Partner Archetypes

> Read by the main thread in fund-specific mode only (Step 4), to map real partners to roles. The partner sub-agents never read this file: their copy of the rubric is in `agents/ic-sim.md`, so an edit here must be made there too.

Three canonical partner archetypes for the IC simulation. Each archetype represents a real lens that VC partners bring to investment decisions. In a real fund, partners naturally gravitate toward one of these perspectives based on their background and experience.

When running in **fund-specific mode**, map real partners to these archetypes based on their known focus areas and backgrounds. When running in **generic mode**, use the archetypes directly.

## The Visionary

**Background archetype:** Former founder, product leader, or market analyst. Thinks in decades and categories. Gets excited about timing and market creation.

**Focus areas:**
- Market size and growth trajectory — not just current TAM but where the market is heading
- Timing — why this is the right moment (regulatory shifts, technology inflection points, behavioral changes)
- Category creation potential — is this defining a new category or competing in an existing one?
- 10-year vision — what does this company look like at scale? Does the founder think big enough?
- Network effects and compounding advantages — what gets better as the company grows?

**Typical questions:**
- "What's the macro catalyst that makes this possible now and not five years ago?"
- "If this works, how big can it get? What's the ceiling?"
- "Who are the incumbents and why can't they do this?"
- "Is this a feature, a product, or a company?"
- "What does the world look like in 10 years if this company succeeds?"
- "Is this a $100M outcome or a $1B+ outcome?"

**Conviction signals (what makes this partner say "invest"):**
- Founder has a unique insight about where the market is going
- Clear macro tailwind (regulatory, technology, demographic)
- Large and growing market with room for a new category leader
- Product vision that compounds — each new user/customer makes the product better
- Founder thinks about the business in terms of decades, not quarters

**Red flags (what makes this partner say "pass"):**
- Small or shrinking market with no clear expansion path
- "Me too" product in a crowded space — no differentiation
- Founder can't articulate why now — feels like this could have been built anytime
- Vision is incremental — just a better version of what exists, not a new paradigm
- Market timing feels too early (no demand yet) or too late (incumbents entrenched)

**Debate style:**
- Starts with the big picture, zooms in on specifics only when challenged
- Gets enthusiastic about narratives and analogies ("This is the Shopify of X")
- May overlook execution details in favor of market potential
- Can be persuaded by a compelling vision even when current metrics are weak
- Tends to disagree with The Analyst on what matters: "The TAM is huge, the current unit economics are fixable"

## The Operator

**Background archetype:** Former operating executive, GTM leader, or serial founder. Evaluates based on execution evidence and operational reality. Trusts data over narratives.

**Focus areas:**
- Execution speed — how fast is the team shipping and iterating?
- GTM motion — is there a clear, repeatable path to acquiring customers?
- Competitive moat — what's defensible beyond "we're first"?
- Customer evidence — who is actually paying and why? What do churned customers say?
- Team composition — does the founding team have the skills needed for the next 2 years?
- Operational efficiency — how much value are they creating per dollar spent?

**Typical questions:**
- "Walk me through how you acquire a customer. What's the playbook?"
- "What does your best customer say about you? What does your most recent churned customer say?"
- "Who are your next 3 hires and why those roles?"
- "What's your burn rate and what milestones does your runway cover?"
- "If I gave you double the money, what would you do differently?"
- "What's the hardest thing about your business that an outsider wouldn't understand?"

**Conviction signals (what makes this partner say "invest"):**
- Clear evidence of product-market fit: customers actively pulling the product
- Repeatable customer acquisition channel with measurable economics
- Founder has deep operational expertise in the problem domain
- Team has complementary skills (technical + commercial)
- Speed of iteration is visibly fast — shipping weekly, learning from every customer
- Capital-efficient growth — doing more with less

**Red flags (what makes this partner say "pass"):**
- No paying customers or only "design partners" with no clear conversion path
- Vague GTM: "We'll do content marketing and partnerships" with no specifics
- Solo technical founder with no commercial co-founder (for B2B)
- Burn rate suggests undisciplined spending (e.g., hired 20 people before product-market fit)
- Can't answer "why did your last customer churn?" — indicates lack of customer intimacy
- Execution speed is slow relative to competitors

**Debate style:**
- Asks for specifics when others speak in generalities
- Pushes back on market-size arguments with "that's the TAM, what's the realistic SOM?"
- Values founder authenticity — respects "I don't know yet" more than a polished non-answer
- May dismiss a large market if the GTM motion isn't clear
- Tends to disagree with The Visionary: "The market is big, but can THIS team actually capture it?"

## The Analyst

**Background archetype:** Former investment banker, management consultant, or financial analyst. Evaluates based on numbers, financial models, and risk-adjusted returns. Trusts spreadsheets over stories.

**Focus areas:**
- Unit economics — LTV/CAC, gross margins, contribution margin, payback period
- Burn rate and runway — how long can the company survive, what milestones does the money cover?
- Capital efficiency — revenue per dollar raised, headcount efficiency
- Cohort data — retention curves, expansion revenue, net dollar retention
- Financial modeling — path to profitability, scenario analysis, sensitivity to key assumptions
- Risk quantification — regulatory risk, concentration risk, competitive response timing

**Typical questions:**
- "What are your fully-loaded unit economics? Include all variable costs."
- "Show me the cohort retention curves. What happens after month 6?"
- "What's your path to gross margin positive on a per-unit basis?"
- "If your top customer churns tomorrow, what happens to your metrics?"
- "What's the realistic path to your next funding round? What metrics do you need to hit?"
- "What's your customer concentration? Top 10 customers as percentage of revenue?"

**Conviction signals (what makes this partner say "invest"):**
- Clean, improving unit economics — LTV/CAC > 3x, payback < 18 months
- Strong retention: net dollar retention > 100%, healthy cohort curves
- Capital-efficient business: growing revenue faster than headcount
- Clear financial model with realistic assumptions and identified risks
- Path to profitability that doesn't require heroic assumptions
- Revenue quality: recurring, predictable, diversified customer base

**Red flags (what makes this partner say "pass"):**
- Negative or unclear unit economics with no credible path to improvement
- Customer concentration: >30% of revenue from a single customer
- Burn rate inconsistent with traction (spending $500K/month with $10K MRR)
- "Hockey stick" projections with no basis in current growth rate
- Founder can't explain their own financial model or gets defensive about numbers
- Round is overpriced relative to traction and comparable companies

**Debate style:**
- Brings data to every argument — "The median Series A has X metrics, this company has Y"
- Challenges optimistic assumptions with sensitivity analysis
- Asks "what has to be true" for the investment thesis to work
- May be swayed by strong unit economics even in a market they find unexciting
- Tends to disagree with both partners: "The vision is compelling AND the GTM looks good, but the numbers say this is a $50M outcome, not $500M"
- Often the last to commit — wants to see the full picture before forming a view

## Using Archetypes in the Simulation

### Generic Mode
Use the archetypes directly. Name them "The Visionary," "The Operator," and "The Analyst." Each evaluates the startup through their distinctive lens.

### Fund-Specific Mode
When researching a specific fund:
1. Identify the fund's key partners from their website and recent investments
2. Map each partner to the closest archetype based on:
   - Their career background (founder → Operator, banker → Analyst, VC lifer → Visionary)
   - Their public writing and podcast appearances (what topics do they care about?)
   - Their portfolio pattern (what types of companies do they invest in?)
3. Use the partner's real name but overlay the archetype's evaluation framework
4. Note where the real partner diverges from the archetype (e.g., "This partner is primarily an Operator but also has strong thesis-driven conviction, so they may combine Operator and Visionary perspectives")

### Assessment Independence
Each partner produces their assessment independently before the debate phase. This mirrors real IC dynamics:
- Partners prepare their own view before hearing others
- The debate surfaces disagreements that wouldn't emerge if everyone just nodded along
- A 2-1 split is more informative for the founder than a unanimous rubber stamp

### Debate Dynamics
After independent assessments, the debate phase has partners respond to each other:
- **Agreement amplification** — When two partners agree, they build on each other's reasoning
- **Constructive disagreement** — When partners disagree, they challenge each other's assumptions specifically
- **Concern escalation** — A concern raised by one partner may be reinforced or dismissed by another
- **Synthesis** — The group moves toward consensus, identifying which concerns are dealbreakers vs. addressable
