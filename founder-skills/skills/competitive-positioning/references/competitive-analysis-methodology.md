# Competitive Analysis Methodology

Reference for the competitive positioning agent. Covers axis selection, competitor categorization, stress-testing claims, investor expectations, and common mistakes. The agent MUST read this file before Step 3 (Competitor Identification) and Step 5 (Positioning & Moat Assessment).

---

## 1. Competitor Categorization

Every competitive landscape should include competitors across multiple categories. The category determines how the competitor is analyzed and presented.

### Categories

| Category | Definition | Examples | Analysis Focus |
|----------|-----------|----------|---------------|
| `direct` | Same problem, same customer, same approach. Head-to-head competitors. | Stripe vs. Braintree for payment processing | Feature parity, pricing, market share, switching costs |
| `adjacent` | Same customer, different approach. Alternative ways to solve the problem. | Spreadsheets vs. project management software | Why the customer would switch approaches, friction of change |
| `do_nothing` | The status quo. What customers do today without a dedicated solution. | Manual processes, internal tools, hiring more people | Cost of inaction, trigger events that force change |
| `emerging` | New entrants building toward the same market. May not be direct competitors yet. | Startups in adjacent spaces that could pivot, new products from established companies | Trajectory, funding, speed of convergence |
| `custom` | Does not fit standard categories. Use sparingly with justification. | Platform providers that could build the feature, regulatory bodies | Specific to the competitive dynamic at hand |

### How many competitors?

**Target: 5-7 competitors.** This range provides:
- Enough diversity to show market understanding (direct, adjacent, do-nothing, emerging)
- Not so many that the analysis becomes shallow
- `validate_landscape.py` enforces bounds: minimum 3, maximum 10

**Composition guidance:**
- 2-3 direct competitors (the ones investors will immediately think of)
- 1-2 adjacent alternatives (shows the founder thinks beyond obvious competitors)
- 1 do-nothing / status quo (the most honest competitor for early-stage)
- 0-1 emerging entrants (shows the founder watches the horizon)

### The "Do Nothing" Alternative

**Why it matters:** For most early-stage startups, the biggest competitor is not another startup — it is customer inertia. The status quo costs money (in time, errors, missed revenue), but changing behavior has its own costs (learning curves, migration, organizational friction).

**How to model it:**
- Name it concretely: not just "Do Nothing" but "Manual process using Excel + email" or "Hire an additional analyst"
- Quantify the status quo cost where possible: "Engineering team spends 20 hours/month on manual API monitoring"
- Identify trigger events that make the status quo untenable: regulatory change, scale threshold, competitor pressure
- Position it on the map honestly: the status quo typically scores high on "deployment complexity" (zero) and low on "capability"

**When to omit:** Rarely. Valid reasons include:
- Regulated markets where the status quo is illegal (e.g., new compliance requirement mandates a solution)
- Markets where a tool is already universally adopted and the competition is between tools, not between tool-vs-no-tool
- In these cases, use `accepted_warnings` with code `MISSING_DO_NOTHING` and a specific reason

### Handling Deck Competitors Not in Analysis

When the founder's pitch deck lists competitors that are not included in the formal landscape analysis, the agent must explicitly acknowledge them. Valid reasons for exclusion include:

- **Too small / early:** The competitor is pre-product or has negligible market presence, making meaningful comparison impossible.
- **Different market segment:** The competitor serves a fundamentally different buyer (e.g., enterprise vs. SMB) with no overlap in the target market.
- **Redundant:** The competitor is functionally identical to another included competitor and would not add analytical value.
- **Acqui-hired / shutdown:** The competitor no longer operates independently.

**What to do:**

1. Record excluded deck competitors in `landscape_draft.json` under `deck_competitors_excluded` with name and reason.
2. In the final report, include a note: "The deck's competition slide includes [X, Y, Z] which were not included in this analysis because [reasons]."
3. This prevents the NARR_03 checklist item ("Competition narrative aligns with deck claims") from failing without explanation. The checklist assessor can mark NARR_03 as `pass` with evidence citing the explicit exclusion rationale.

**When NOT to exclude:** If the deck mentions a competitor that investors will immediately recognize as relevant (e.g., the market leader), include it even if the founder considers it a different segment. Investors will ask about it.

---

## 2. Positioning Axis Selection

The positioning map is the centerpiece of the competitive analysis. Axis selection determines whether the map reveals genuine competitive dynamics or obscures them.

### Principles

1. **Axes must differentiate.** A good axis is one where competitors spread across the range. If 80%+ of competitors cluster in the same area, the axis does not differentiate (vanity axis).

2. **Axes must matter to the buyer.** An axis that differentiates competitors but is irrelevant to the purchase decision is useless. "Number of programming languages supported" might differentiate but may not influence which tool a buyer chooses.

3. **Axes should be measurable or at least rankable.** "Quality" is too vague. "Time to first value" or "False positive rate" is concrete enough to rank competitors.

4. **Axes should be independent.** Two highly correlated axes (e.g., "Feature count" and "Product maturity") do not add information. Choose axes that reveal different dimensions of competition.

5. **The startup should be differentiated on at least one axis.** If the map shows the startup in the middle of the pack on both axes, either the axes are wrong or the startup genuinely lacks differentiation (which is a finding, not a map failure).

### When the Deck Already Has Axes

If the founder's pitch deck includes a competition slide with its own positioning axes, you face a choice: use the deck's axes or propose better ones.

**Use the deck's axes when:**
- They follow the principles above (differentiate, matter to buyer, measurable)
- The founder has built their narrative around them and investors have seen them
- Changing axes would undermine an otherwise strong competition slide

**Propose new axes when:**
- The deck uses vanity axes (startup is alone in a quadrant by construction)
- The deck axes don't differentiate (all competitors cluster together)
- Research reveals a more meaningful competitive frame the founder hasn't considered

**How to frame the difference:** At Gate 1, present both: "Your deck uses [X vs Y]. I'd recommend [A vs B] because [reason]. We can analyze both — the primary map uses the stronger axes, and a secondary view uses your deck's axes for comparison."

This preserves the founder's existing narrative while adding analytical value. Never silently replace deck axes without discussing it.

### Good Axis Examples by Sector

| Sector | X-Axis | Y-Axis | Why it works |
|--------|--------|--------|-------------|
| **API Security** | Deployment complexity (low-touch vs. high-touch) | Detection accuracy (false positive rate) | Reveals the core trade-off: ease vs. effectiveness. Buyers care about both. |
| **Dev Tools** | Time to first value (minutes vs. weeks) | Customizability (opinionated vs. flexible) | Captures the PLG vs. enterprise divide. Startups often win on time-to-value. |
| **Fintech / Payments** | Geographic coverage (single market vs. global) | Integration depth (API-only vs. full platform) | Reveals whether competitors are point solutions or platforms. |
| **Healthcare SaaS** | Regulatory readiness (HIPAA/SOC2 certified vs. not) | Clinical workflow integration (standalone vs. embedded in EHR) | Both dimensions directly gate purchase decisions in healthcare. |
| **AI / ML Tools** | Model customizability (off-the-shelf vs. fine-tunable) | Data privacy level (cloud-only vs. on-premises capable) | Enterprise AI buyers care deeply about both. |
| **Marketplace** | Supply density (sparse vs. saturated in target geo) | Trust/verification depth (self-reported vs. verified) | Both sides of the marketplace care about these dimensions. |

### Vanity Axes to Avoid

A **vanity axis** is one chosen specifically because the startup scores uniquely well on it, rather than because it reveals competitive dynamics. Common patterns:

| Vanity Axis | Why it fails | Better alternative |
|-------------|-------------|-------------------|
| "AI-powered" vs. "Non-AI" | Binary axis. Startup in top-right, everyone else in bottom-left. No nuance. | "Automation depth" (what percentage of workflow is automated) — competitors will spread. |
| "Founded year" or "Product maturity" | Correlates with everything. Does not reveal a strategic choice. | "Time to first value" — captures what maturity actually gives the buyer. |
| "Price" as the only differentiator | If the startup's only advantage is being cheaper, the positioning is fragile. | "Total cost of ownership" (includes implementation, training, migration) — more defensible. |
| "Number of features" | Feature count is not value. Incumbents always win on feature count. | "Buyer-relevant capability depth" in a specific workflow — focuses on what matters. |
| "Customer satisfaction" | Self-reported, unverifiable, and every company claims high satisfaction. | "Net retention rate" or "reference customer willingness" — measurable proxies. |

**Detection:** `score_positioning.py` flags an axis as vanity when >80% of competitors (excluding `_startup`) cluster within 20% of the axis range. This is a quantitative check, but the agent should also apply qualitative judgment — an axis can pass the quantitative test while still being strategically meaningless.

### Candidate Axis Selection Process

1. **List 5-8 candidate axes** based on: buyer decision criteria, competitor differentiation patterns, founder's claimed advantages, research findings
2. **Filter for independence:** remove axes that are highly correlated with each other
3. **Filter for differentiation:** remove axes where competitors would cluster
4. **Filter for buyer relevance:** remove axes that differentiate but do not influence purchase decisions
5. **Propose 2-3 pairs** with rationale for each
6. **Present to founder** at Gate 1 for validation — the founder may have insight into which dimensions buyers actually weigh

---

## 3. Stress-Testing Differentiation Claims

Every differentiation claim must be tested before it enters the report. The stress-test asks three questions:

### The Three Questions

1. **Is it verifiable?** Can the claim be independently confirmed through public data, customer testimony, benchmarks, or third-party analysis? Claims that are only verifiable by the founder ("we're 10x faster") are weaker than those that can be externally validated.

2. **Is it sustainable?** Will this advantage persist for 12-24 months? A feature advantage is temporary — an incumbent can ship the same feature. A data advantage or network effect is more durable. The stress-test should assess how long before a well-funded competitor could match the claim.

3. **Does it matter to the buyer?** A technically impressive capability that does not influence purchase decisions is not a competitive advantage. "Our ML model is 2% more accurate" matters less than "Our solution reduces false alerts by 80%, saving 10 engineering hours per week."

### Verdict Scale

| Verdict | Meaning | Investor Impact |
|---------|---------|----------------|
| `holds` | Claim is verifiable, sustainable, and buyer-relevant. Evidence supports it. | Strong — use in competitive narrative |
| `partially_holds` | Claim has merit but needs qualification. Partially verifiable, or sustainable for limited time, or relevant to some buyers. | Moderate — use with honest qualification |
| `does_not_hold` | Claim fails one or more tests. Not verifiable, not sustainable, or not buyer-relevant. | Weak — either reframe or drop from narrative |

### Common Claim Failures

| Claim Pattern | Typical Failure | Reframing |
|--------------|----------------|-----------|
| "We're 10x faster/cheaper/better" | Unverifiable. Based on internal benchmarks against an unspecified baseline. | "Our architecture eliminates [specific bottleneck], which in customer X's case reduced [metric] by [amount]" |
| "We use AI" | Not a differentiator in 2026. Everyone uses AI. | "Our model is trained on [proprietary dataset] that competitors cannot access because [reason]" |
| "First mover" | First mover advantage is historically weak. Being first does not create a moat. | "We have [X months] of customer data and [Y] integrations that a new entrant would need [Z months] to replicate" |
| "Better UX" | Subjective and unverifiable without data. | "Our onboarding flow takes 5 minutes vs. competitors' 2 weeks, as measured by [customer cohort data]" |
| "Proprietary technology" | Often overstated. Patents ≠ moats unless actively enforced. | "Our [specific technology] produces [measurable outcome] that competitors have not replicated in [time period] despite attempting to" |
| "Bigger team" | Team size is not a competitive advantage — it is a cost. | "Our team includes [specific expertise] that is directly relevant to [specific challenge], specifically [names/credentials]" |

---

## 4. Investor Expectations for Competition Analysis

### What Investors Want to See

1. **Market awareness.** The founder knows who the competitors are, what they do well, and where they are vulnerable. Missing an obvious competitor is a red flag.

2. **Honest assessment.** Acknowledging competitor strengths signals maturity. "Salt Security has better enterprise penetration, but we win on deployment speed for mid-market" is stronger than "Salt Security is irrelevant."

3. **Defensible positioning.** Not just "where we are today" but "why we will win and how we will defend our position." This connects to moat assessment.

4. **Dynamic thinking.** How will the competitive landscape evolve? Who will enter? Who will pivot? What happens when the incumbent responds? Static analysis is incomplete.

5. **Specific differentiators.** Not "better product" but "3x faster deployment because of our SDK approach vs. their reverse-proxy architecture." Concrete, verifiable, and connected to buyer value.

### What Investors Push On

Based on common VC due diligence patterns:

| Question | What they are really asking | How to prepare |
|----------|---------------------------|---------------|
| "Who are your competitors?" | "Do you know your market? Did you miss anyone obvious?" | Have 5-7 ready, categorized. Know the top 3 cold. |
| "Why won't [big company] just build this?" | "Is your position defensible against someone with 100x your resources?" | Identify specific moats. "They could build it, but it would take [X] because [moat]." |
| "What happens when they copy your feature?" | "Is your advantage sustainable or temporary?" | Distinguish feature advantages (temporary) from structural advantages (moats). |
| "Why will customers choose you over [competitor]?" | "Have you actually talked to buyers? Do you know the decision criteria?" | Cite specific customer conversations, win/loss data, or buyer decision criteria. |
| "What if [competitor] raises $100M?" | "Can you survive a well-funded competitor targeting your market?" | Show moats that money alone cannot buy (data, network effects, switching costs). |

### The 88% Rule

DocSend data shows that VCs spend 88% more time on the competition section of successful decks compared to unsuccessful ones. This does not mean more slides — it means more substance. Investors engage deeply with competitive analysis that shows genuine market understanding and honest positioning.

### Beyond the 2x2 Matrix

The traditional 2x2 competitive matrix (four quadrants, startup in top-right) is outdated. Investors have seen thousands of these and recognize the pattern: founders choose axes that put themselves in the "best" quadrant. What works better:

- **Dynamic positioning** that shows how positions are shifting over time (trajectory arrows)
- **Multiple views** that show the landscape from different buyer perspectives
- **Evidence-backed positions** where each coordinate has a specific data point, not just a gut-feel placement
- **Honest trade-offs** that show where competitors genuinely win (and why it does not matter to the target buyer, or how the startup plans to close the gap)

---

## 5. Common Mistakes

### Mistake 1: "We Have No Competitors"

**Why it happens:** Founders genuinely believe their product is novel, or they define "competitor" too narrowly (only direct, same-feature competitors).

**Why it is wrong:** Every product competes with alternatives. At minimum:
- The status quo (do nothing, manual process, hiring people)
- Adjacent solutions (different approach to the same problem)
- Generic tools (Excel, email, custom scripts)

**What investors hear:** "This founder does not understand their market" or "This founder is being dishonest about the competitive landscape."

**How to fix:** Expand the definition of competition. The question is not "who has the same features?" but "what does the customer do today instead of using this product?"

### Mistake 2: Feature Checkbox Matrix

**Why it happens:** Founders are proud of their features and want to show they have more green checkmarks than competitors.

**Why it is wrong:**
- Incumbents will always win on feature count
- Features without buyer-value context are meaningless
- Investors care about defensibility, not feature lists
- The matrix implies that more features = better, which is not how buyers decide

**What to do instead:** Focus on 2-3 dimensions that matter to the buyer's decision. Show why the startup wins on those dimensions and why those dimensions matter more than feature count.

### Mistake 3: Ignoring Incumbents

**Why it happens:** Founders focus on other startups (similar stage, similar funding) and ignore large established companies that serve the same buyer.

**Why it is wrong:** The incumbent is often the real competitor. "We're not competing with Salesforce" is almost always wrong if the buyer's alternative is staying with Salesforce.

**How to handle:** Include the incumbent with honest positioning. Acknowledge their strengths (brand, distribution, existing relationships) and position against their weaknesses (slow innovation, expensive, poor UX for specific use case).

### Mistake 4: Static Analysis

**Why it happens:** The analysis describes the current state but does not consider how the landscape will evolve.

**Why it is wrong:** Investors are funding the future, not the present. "We win today on deployment speed" matters less if competitors are releasing SDK-based deployments next quarter.

**What to do:** Include trajectory assessment for each competitor and each moat dimension. Identify which advantages are widening and which are narrowing.

### Mistake 5: Positioning for Vanity

**Why it happens:** Founders (or agents) choose positioning axes specifically to make the startup look uniquely positioned, rather than axes that reveal real competitive dynamics.

**How to detect:**
- The startup is alone in a quadrant while all competitors cluster together
- The axes would not appear in a buyer's evaluation criteria
- The axes are binary (AI vs. non-AI) rather than continuous spectrums
- `score_positioning.py` flags axes where >80% of competitors cluster within 20% of the range

**What to do:** Choose axes that matter to the buyer's purchase decision, even if the startup does not win on both. A map that shows the startup winning on deployment speed but trailing on detection accuracy is more credible than one that shows the startup alone in the "best" quadrant.

### Mistake 6: Confusing Distribution with Product Advantage

**Why it happens:** Founders assume that having a better product guarantees winning. They underestimate distribution, brand, and switching costs.

**Reality:** In enterprise markets especially, the best product does not always win. Distribution advantages (existing sales relationships, marketplace presence, partner channels) often trump product advantages. The competitive analysis should assess distribution strength alongside product strength.

---

## 6. Research Methodology

### Information Needed Per Competitor

The research sub-agent (or main agent in sequential mode) should gather:

| Category | Data Points | Priority |
|----------|------------|----------|
| **Product** | What they do, key features, technical approach, product roadmap signals | High |
| **Customers** | Who they serve, customer segments, notable logos, case studies | High |
| **Pricing** | Pricing model, price points, free tier, enterprise pricing | Medium |
| **Funding** | Total raised, last round, investors, implied valuation | Medium |
| **Team** | Size, key hires, founder background, hiring signals | Medium |
| **Positioning** | How they describe themselves, marketing claims, category creation attempts | High |
| **Sentiment** | User reviews (G2, Capterra), community discussions, complaints | Medium |
| **Trajectory** | Recent product launches, market expansion, pivots, layoffs | Medium |

### Research Quality Indicators

| Indicator | Research Quality |
|-----------|----------------|
| Pricing sourced from company website or recent review | High — current and verifiable |
| Funding sourced from Crunchbase, press release, or SEC filing | High — factual |
| Product claims sourced from user reviews or case studies | Medium-high — buyer perspective |
| Product claims sourced from company marketing | Medium — potentially biased |
| Data sourced from agent training data | Low — may be outdated or incorrect |
| Data estimated by agent without source | Lowest — must be clearly labeled |

### Structured Research Protocol

To prevent raw search results from accumulating in context:

1. **Phase A (Broad scan):** For each competitor, run targeted searches. After ALL Phase A searches complete, summarize findings into structured competitor profiles. Discard raw search results.

2. **Phase B (Targeted cross-referencing):** Using Phase A profiles, run comparative and validation queries. Summarize findings and update profiles. Discard raw search results.

3. **Evidence tagging:** For each data point in the final profile, record whether it was `researched` (found via search), `agent_estimate` (inferred from training data), or `founder_provided` (stated by the founder).

---

## Sources

- DocSend — "What We Learned from 200 Startups Who Raised $360M" — competition section engagement data, 88% more time on competition in successful decks
- Underscore VC — "Startup Competitive Analysis" — moving beyond 2x2 matrices, dynamic competitive positioning
- Vestbee — "How to Do Competitive Analysis for Startups" — investor expectations, common mistakes
- Qubit Capital — "How to Do a Competitive Analysis for a Startup" — 44% of companies have zero competitor visibility
- Sequoia — "Writing a Business Plan" — competition section guidance
- a16z — Due diligence patterns, "what VCs look for in competition slides"
