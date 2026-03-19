# Moat Type Definitions

Canonical definitions for the 6 moat types used in competitive positioning analysis. Each moat is evaluated per company (startup and competitors) with a status rating, evidence, and trajectory.

The agent MUST read this file before Step 5 (Positioning & Moat Assessment). Scripts (`score_moats.py`) validate against these definitions.

---

## Status Ratings

| Status | Meaning | Score Contribution |
|--------|---------|-------------------|
| `strong` | Clear, demonstrable moat with concrete evidence. Would take a well-funded competitor 2+ years to replicate. | Highest |
| `moderate` | Emerging moat with early evidence. Defensible advantage exists but is not yet entrenched. Could be replicated with significant effort (1-2 years). | Medium |
| `weak` | Minimal defensibility. Advantage exists on paper but is thin, easily replicable, or unproven. | Low |
| `absent` | No moat on this dimension. Company has no advantage here and is not building one. | None |
| `not_applicable` | This moat type does not structurally apply to this company's business model. Requires explicit evidence explaining why. | Excluded |

**Default to `absent`, not `not_applicable`.** A moat being weak or absent is different from it being structurally impossible. `not_applicable` is reserved for cases where the moat type genuinely cannot exist (e.g., network effects for a single-player desktop tool with no shared data). If unsure, rate it `absent` with evidence explaining why.

---

## Trajectory Values

Each moat assessment includes a trajectory indicating the direction of change:

| Trajectory | Meaning | Examples |
|-----------|---------|---------|
| `building` | Moat is actively strengthening. Investments or natural dynamics are increasing defensibility. | Growing user base creating network effects; accumulating proprietary data; increasing switching costs as customers integrate deeper. |
| `stable` | Moat strength is roughly constant. Not actively growing or shrinking. | Established brand reputation; existing regulatory license that is neither expanding nor under threat. |
| `eroding` | Moat is weakening. Competitive dynamics, technology shifts, or market changes are reducing defensibility. | Commoditizing technology; regulatory changes opening the market; competitors catching up on data scale. |

**Stage calibration for trajectory:**
- **Pre-seed:** Most moats should be `building` or `absent`. A pre-seed company claiming `stable` strong moats is suspect unless they are spinning out of an established company with existing assets.
- **Seed:** Expect a mix of `building` (primary moats) and `absent` (aspirational moats). One or two `moderate` + `building` moats is a strong signal.
- **Series A:** At least one moat should be `moderate` or `strong` with concrete evidence. All claimed moats should have measurable trajectory evidence.

---

## Canonical Moat Types

### 1. `network_effects`

**Definition:** The product becomes more valuable to each user as more users join. Value scales super-linearly with adoption. The key test: does adding one more user make the product meaningfully better for existing users?

**Strong:**
- Multi-sided marketplace where both sides benefit from scale (e.g., Uber: more drivers = shorter wait times = more riders = more drivers)
- User-generated content/data that improves the product for everyone (e.g., Waze: more drivers = better traffic data = better routes for all)
- Protocol or standard adoption where compatibility drives switching costs (e.g., Slack: team adoption makes individual switching costly)
- Quantifiable: can demonstrate that user engagement or value metrics improve with network size

**Moderate:**
- Single-sided network with some viral dynamics (e.g., productivity tool where teams benefit from shared workflows)
- Data network effects where aggregate usage improves the product but individual user value increase is modest
- Marketplace with liquidity in some segments but not others

**Weak:**
- Product has users but no evidence that more users make it better for existing ones
- "Network effects" are really just word-of-mouth referrals (growth mechanism, not value creation)
- Marketplace with low switching costs on both sides

**Absent:**
- Single-player product with no shared data, no collaboration features, no marketplace dynamics

**Common confusions:**
- **Viral growth is NOT network effects.** Viral growth is a distribution mechanism (users invite other users). Network effects are a value mechanism (the product gets better with more users). A product can go viral without having network effects (e.g., a viral mobile game where each player's experience is independent). Conversely, a product can have strong network effects with slow adoption.
- **Scale effects are NOT network effects.** Serving more customers may lower per-unit costs (cost structure moat) but does not automatically mean the product is more valuable per user. Amazon's logistics cost advantage is a cost structure moat, not a network effect. Amazon Marketplace's seller/buyer dynamics ARE network effects.
- **User count alone does not prove network effects.** The test is whether value per user increases with scale, not whether the company has many users.

---

### 2. `data_advantages`

**Definition:** The company possesses proprietary data — or a mechanism to continuously generate proprietary data — that improves its product in ways competitors cannot easily replicate. The key test: if a well-funded competitor started today with no data, how long would it take them to reach equivalent data quality/quantity, and does that gap translate to a measurably better product?

**Strong:**
- Proprietary dataset that took years or unique access to build (e.g., Bloomberg terminal data, medical imaging datasets from hospital partnerships)
- Data flywheel: product usage generates data that improves the product, which attracts more usage (e.g., Google Search: queries improve ranking → better results → more queries)
- Data that is not just large but uniquely structured or labeled (proprietary annotations, domain-specific ontologies)
- Regulatory or contractual exclusivity on data sources

**Moderate:**
- Growing proprietary dataset from product usage, but competitors could build equivalent in 12-18 months with sufficient investment
- Unique data combinations (e.g., combining publicly available datasets in a novel way that creates insight)
- First-mover data accumulation where the gap is meaningful today but shrinking

**Weak:**
- Uses publicly available data (even if processed well)
- Training data that could be replicated by a competitor with moderate effort
- "We have more data" without evidence that more data = measurably better product

**Absent:**
- No proprietary data. Product relies on publicly available information, open-source models, or data the customer provides fresh each time.

**Common confusions:**
- **Having data is NOT a data advantage.** Every company has data. The moat exists only when the data is proprietary, difficult to replicate, AND demonstrably improves the product.
- **AI model training alone is NOT a data moat.** If the model is trained on publicly available or licensable data, competitors can train equivalent models. The moat is in the data, not the model architecture (models are increasingly commoditized).
- **Customer data stored is NOT a data advantage unless it creates a flywheel.** Storing customer data creates switching costs (a different moat type), not data advantages. The data moat exists when aggregated customer data improves the product for ALL customers.

---

### 3. `switching_costs`

**Definition:** The cost — in time, money, effort, risk, or organizational disruption — that a customer incurs when moving to a competitor. High switching costs lock in customers even when alternatives exist. The key test: if a competitor offered an identical product for free, would customers still hesitate to switch?

**Strong:**
- Deep system integration (APIs, data pipelines, workflows) that would take months to replicate (e.g., Salesforce CRM embedded in a company's entire sales process)
- Proprietary data format or migration complexity (years of historical data that does not export cleanly)
- Regulatory or compliance certification tied to the specific product (re-certification would be required for a switch)
- User training investment and institutional knowledge (e.g., complex enterprise software where teams have been trained for years)
- Multi-year contracts with significant early termination penalties

**Moderate:**
- Integration exists but migration is feasible in weeks (not months)
- Data is portable but reconfiguration is needed
- Team has built workflows around the product but could adapt to alternatives
- Annual contracts with reasonable termination terms

**Weak:**
- Minimal integration depth — product operates as a standalone tool
- Data exports cleanly, standard formats used
- Users can be productive on alternatives within days
- Month-to-month contracts or easy cancellation

**Absent:**
- Zero integration, zero data lock-in, zero training investment. Customer can switch in a single session.

**Common confusions:**
- **Contractual lock-in is NOT the same as switching costs.** A 3-year contract expires. Real switching costs persist regardless of contract terms — they are structural, not contractual. Contractual lock-in is a weak form of switching cost that evaporates on renewal.
- **Habit is a weak switching cost.** Users preferring a familiar interface is real but fragile. A significantly better alternative overcomes habit quickly. Do not rate habit-based retention as `strong`.
- **Switching costs must be evaluated from the customer's perspective,** not the vendor's. "It's hard for them to leave" must be supported by evidence of what the customer would need to do, not just assertion.

---

### 4. `regulatory_barriers`

**Definition:** Government regulations, licenses, certifications, or legal frameworks that create barriers to entry or competitive advantage. The key test: does a new entrant need regulatory approval that takes significant time/money to obtain, and does the company already have it?

**Strong:**
- Licensed or regulated activity where obtaining approval takes 1+ years and significant investment (e.g., banking license, FDA approval, FCC spectrum license)
- Compliance infrastructure that took years to build and certify (SOC 2 Type II, HIPAA, PCI-DSS for complex use cases)
- Government contract incumbency with high rebid barriers
- Patent portfolio that is actively enforced and covers core product functionality

**Moderate:**
- Certifications that take 6-12 months to obtain (e.g., SOC 2 Type II, ISO 27001)
- Industry-specific compliance expertise that is learnable but takes time
- Regulatory relationships that provide early insight into rule changes
- Patents filed but not yet proven in enforcement

**Weak:**
- Compliance requirements that are standard and achievable in <6 months
- Regulatory awareness without actual certification advantage
- "We plan to get [certification]" without current status

**Absent:**
- Industry has no meaningful regulatory barriers. No licenses, certifications, or regulatory approvals required.

**Common confusions:**
- **Compliance is NOT automatically a moat.** SOC 2 certification is table stakes for enterprise SaaS, not a defensibility advantage. The moat exists when the specific regulatory requirement is genuinely hard to obtain and competitors lack it.
- **Regulation can be a threat, not just a moat.** Regulatory change can destroy a moat as easily as create one. Always assess trajectory — is the regulatory environment tightening (strengthening the moat) or opening up (eroding it)?
- **Geographic regulatory advantage is real but bounded.** A company licensed to operate in a specific market has a moat in that market, but it does not extend to other markets unless multi-market licensing is cumulative.

---

### 5. `cost_structure`

**Definition:** Structural cost advantages that allow the company to operate at lower cost than competitors, enabling better margins or more aggressive pricing. The key test: can the company sustainably offer equivalent or better value at lower cost, and is this advantage structural (not just operational efficiency)?

**Strong:**
- Proprietary technology that fundamentally changes cost economics (e.g., vertical integration, novel manufacturing process, inference optimization that reduces compute costs by 10x)
- Scale economics where unit costs decrease meaningfully with volume and the company has a significant volume lead
- Asset-light model competing against asset-heavy incumbents (e.g., software replacing hardware, marketplace replacing inventory)
- Geographic cost advantage combined with equivalent quality (e.g., R&D center in a lower-cost market without quality sacrifice)

**Moderate:**
- Meaningful cost advantage from early-mover optimization (e.g., better cloud infrastructure deals, optimized ML inference pipeline) but advantage could be replicated with investment
- Open-source core that eliminates licensing costs competitors bear
- Operational efficiency that is documented and measurable but not structural

**Weak:**
- Slightly lower costs from being smaller/leaner (no structural advantage — competitors could match by cutting costs)
- "We're more capital-efficient" without evidence of structural cost difference
- Cost advantage that depends on current scale and would evaporate at competitor scale

**Absent:**
- No meaningful cost advantage. Competing on similar economics to alternatives.

**Common confusions:**
- **Being cheaper is NOT a cost structure moat.** Charging less is a pricing strategy, not a cost advantage. The moat exists when the company can profitably offer lower prices because its costs are structurally lower.
- **Current margins do not prove cost structure moat.** Higher margins might come from premium pricing (brand moat), lower R&D investment (temporary), or accounting differences. The test is whether the cost structure is sustainably advantaged.
- **VC subsidization is NOT a cost advantage.** Offering below-cost pricing funded by venture capital is not a moat — it is a temporary strategy that burns cash. The moat exists only when unit economics are favorable without subsidy.

---

### 6. `brand_reputation`

**Definition:** Brand recognition, trust, and reputation that influence customer acquisition and retention beyond product features. The key test: would a customer choose this company over an identical-feature competitor purely because of brand trust?

**Strong:**
- Category-defining brand that customers seek out by name (e.g., "Stripe for payments" — Stripe IS the category in developers' minds)
- Measurable trust premium: customers willing to pay 20%+ more for the branded product vs. equivalent alternatives
- Thought leadership that drives inbound demand (company is the recognized authority in its space)
- Net Promoter Score significantly above category average with evidence of organic referrals

**Moderate:**
- Growing brand recognition within target segment but not yet category-defining
- Positive word-of-mouth and organic referral rate but not measurably driving pricing power
- Recognized as a credible option in the space (appears in analyst reports, buyer shortlists)
- Founder's personal brand creates meaningful distribution advantage

**Weak:**
- Some name recognition among early adopters but no evidence of influence on purchase decisions
- Brand exists but is indistinguishable from competitors in buyer perception
- Social media presence without evidence of conversion impact

**Absent:**
- No brand recognition. Company is unknown outside its current customer base.

**Common confusions:**
- **Having a website and logo is NOT brand reputation.** Brand as a moat means the brand actively influences purchase decisions and creates measurable advantage.
- **Press coverage is NOT brand moat.** Media mentions are awareness, not trust. The moat exists when brand trust changes customer behavior (willingness to pay, shortlist inclusion, reduced sales cycle).
- **Brand is hard to build but easy to destroy.** A single major incident (data breach, ethical lapse, quality failure) can erode years of brand building. Assess vulnerability alongside strength.

**Stage calibration:**
- **Pre-seed:** Brand is almost always `absent` or `weak`. Founder's personal brand may create `moderate` if they are a recognized domain expert.
- **Seed:** Brand is typically `weak` to `moderate`. Early customers may be advocates but the brand has not reached the broader market.
- **Series A:** Brand should be `moderate` within the target segment if go-to-market is working. Category-defining brand at this stage is exceptional.

---

## Custom Moat Types

When the 6 canonical types do not capture a company's defensibility, the agent may add custom moat dimensions using the `custom_{slug}` naming pattern. Examples:

| Custom ID | When to use |
|-----------|------------|
| `custom_ip_patents` | Company has a patent portfolio that is actively enforced and covers core functionality (beyond what `regulatory_barriers` captures) |
| `custom_talent_moat` | Company has exclusive access to a rare talent pool that competitors cannot easily recruit from |
| `custom_ecosystem_lock_in` | Company is deeply embedded in a platform ecosystem (e.g., Shopify app store) where the platform relationship creates unique advantage |
| `custom_geographic_monopoly` | Company has exclusive access to a geographic market through relationships, licenses, or first-mover dynamics |
| `custom_supply_chain` | Company has exclusive supplier relationships or vertically integrated supply chain that competitors cannot replicate |

**Rules for custom moats:**
1. Must use `custom_{slug}` naming pattern (kebab-case slug)
2. Must include a `definition` field explaining what the moat is and why it is distinct from canonical types
3. Must meet the same evidence standards as canonical moats (strong/moderate/weak/absent ratings with evidence)
4. Should be used sparingly — most defensibility fits within the 6 canonical types
5. `score_moats.py` passes custom moats through without validation against canonical definitions but applies the same evidence quality checks

---

## Moat Assessment Completeness

The agent MUST assess every company in the landscape (every slug in `landscape.json` plus `_startup`) on ALL 6 canonical moat types. Individual dimensions may be rated `not_applicable` but require explicit evidence explaining why.

**Example of valid `not_applicable`:**
```json
{
  "id": "network_effects",
  "status": "not_applicable",
  "evidence": "Single-player desktop productivity tool with no shared data, collaboration features, or marketplace dynamics. Network effects are structurally impossible.",
  "evidence_source": "agent_estimate",
  "trajectory": "stable"
}
```

**Example of INVALID `not_applicable`:**
```json
{
  "id": "network_effects",
  "status": "not_applicable",
  "evidence": "N/A",
  "evidence_source": "agent_estimate",
  "trajectory": "stable"
}
```

The second example would trigger `MOAT_WITHOUT_EVIDENCE` because the evidence string is too short (<20 characters) to explain why the moat type does not apply.
