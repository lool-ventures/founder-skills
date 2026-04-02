# Competitive Positioning Checklist Criteria

25 criteria across 6 categories. Each criterion has an ID, category, label, pass/fail/warn thresholds, and mode gating. The agent assesses each item; `checklist.py` validates structure and computes the score.

## Scoring Formula

- **pass** = 1 point
- **warn** = 0.5 points
- **fail** = 0 points
- **not_applicable** = excluded from denominator

Overall score = `(pass_count + 0.5 * warn_count) / (total - na_count) * 100`

---

## Mode Gating Table

Items are auto-gated to `not_applicable` based on `input_mode` (from `landscape.json`). The agent should not waste effort assessing gated items.

| ID | Label | `deck` | `conversation` | `document` |
|----|-------|--------|----------------|------------|
| `COVER_01` | Minimum 5 competitors identified | active | active | active |
| `COVER_02` | Category diversity (direct + adjacent/do-nothing) | active | active | active |
| `COVER_03` | Emerging entrants considered | active | active | active |
| `COVER_04` | Do-nothing / status quo included | active | active | active |
| `COVER_05` | No obvious incumbents missing | active | active | active |
| `POS_01` | Primary axis pair is meaningful | active | active | active |
| `POS_02` | Axes are non-vanity | active | active | active |
| `POS_03` | Coordinates are evidence-backed | active | active | active |
| `POS_04` | Startup is differentiated on at least one axis | active | active | active |
| `POS_05` | Axis rationale explains differentiation value | active | active | active |
| `MOAT_01` | All 6 canonical moat types evaluated | active | active | active |
| `MOAT_02` | Moat evidence meets quality floor | active | active | active |
| `MOAT_03` | Trajectory included for each moat | active | active | active |
| `MOAT_04` | Custom moats justified (if present) | active | active | active |
| `EVID_01` | Per-competitor research depth recorded | active | active | active |
| `EVID_02` | Majority of competitors have sourced evidence | active | active | active |
| `EVID_03` | Evidence sources distinguished (researched vs. estimated) | active | active | active |
| `EVID_04` | Competitor financials/pricing sourced | **gated** | **gated** | active |
| `NARR_01` | Differentiation claims stress-tested | active | active | active |
| `NARR_02` | Investor-ready competitive framing | active | active | active |
| `NARR_03` | Competition slide alignment (deck cross-check) | active | **gated** | **gated** |
| `NARR_04` | Defensibility roadmap articulated | active | active | active |
| `MISS_01` | No "we have no competitors" claim | active | active | active |
| `MISS_02` | No vanity axes selected | active | active | active |
| `MISS_03` | No feature-checkbox thinking | active | active | active |

**Gated items by mode:**
- **`deck`**: `EVID_04` (deck rarely contains competitor financials)
- **`conversation`**: `NARR_03` (no deck to cross-check), `EVID_04` (conversation mode typically lacks competitor financial detail)
- **`document`**: `NARR_03` (no deck to cross-check)

---

## Category 1 — Competitor Coverage (COVER) — 5 items

### `COVER_01`
**Label:** Minimum 5 competitors identified
**Pass:** 5 or more competitors in the landscape (across all categories).
**Fail:** Fewer than 4 competitors identified.
**Warn:** Exactly 4 competitors — below the recommended 5-7 range but not critically thin.
**Basis:** Investors expect to see 5-7 competitors to believe the founder understands the market. Fewer suggests either a nascent market (justify) or blind spots.

### `COVER_02`
**Label:** Category diversity (direct + adjacent/do-nothing)
**Pass:** Landscape includes at least one `direct` competitor AND at least one `adjacent` or `do_nothing` competitor. Multiple categories represented.
**Fail:** All competitors are the same category (e.g., all `direct`). No recognition that competition includes alternatives and status quo.
**Warn:** Two categories present but heavily skewed (e.g., 5 direct, 1 adjacent).
**Basis:** Investors who see only direct competitors suspect the founder is thinking too narrowly. The "do nothing" alternative is often the real competitor for early-stage startups.

### `COVER_03`
**Label:** Emerging entrants considered
**Pass:** At least one `emerging` competitor identified, OR explicit statement that no emerging threats were found with supporting reasoning.
**Fail:** No `emerging` competitors and no discussion of emerging threats. Suggests the founder is not watching the horizon.
**Warn:** Emerging threats mentioned qualitatively but not included in the formal landscape.
**Basis:** VCs ask "who else is working on this?" — having an answer (even "no one yet, because...") shows market awareness.

### `COVER_04`
**Label:** Do-nothing / status quo included
**Pass:** A `do_nothing` or `adjacent` alternative is explicitly modeled in the landscape with differentiation rationale.
**Fail:** No `do_nothing` and no `adjacent` competitor. The status quo is ignored entirely.
**Warn:** Status quo is mentioned in analysis but not formally included as a landscape entry.
**Basis:** For most early-stage startups, the biggest competitor is inertia. Investors want to see that the founder understands why customers would change behavior.

### `COVER_05`
**Label:** No obvious incumbents missing
**Pass:** Major known players in the space are represented. No glaring omissions that an investor would immediately notice.
**Fail:** A well-known direct competitor (top 3 in the space by market share or funding) is absent without explanation.
**Warn:** A notable player is absent but the omission is acknowledged with reasoning (e.g., "Oracle has an offering but targets a completely different buyer").
**Basis:** Missing an obvious competitor signals either ignorance or avoidance — both are red flags for investors.

---

## Category 2 — Positioning Quality (POS) — 5 items

### `POS_01`
**Label:** Primary axis pair is meaningful
**Pass:** Both axes represent dimensions where (a) competitors meaningfully differ AND (b) the difference matters to the buyer's purchase decision. Rationale explains why these axes were chosen.
**Fail:** Axes are generic ("Quality" vs. "Price") or irrelevant to the buyer's decision process. No rationale for axis selection.
**Warn:** One axis is meaningful, the other is generic or weakly justified.
**Basis:** The positioning map is only useful if the axes reveal real competitive dynamics. Generic axes produce maps that look professional but tell investors nothing.

### `POS_02`
**Label:** Axes are non-vanity
**Pass:** Neither axis is flagged as vanity by `score_positioning.py` (i.e., competitors are spread across the axis range, not clustered).
**Fail:** Both axes are vanity — competitors cluster together, making the map meaningless for differentiation.
**Warn:** One axis is flagged as vanity. The other shows genuine spread.
**Basis:** A vanity axis is one where everyone scores similarly — it does not differentiate. Choosing vanity axes signals the founder picked dimensions that make them look good rather than dimensions that reveal competitive dynamics.

### `POS_03`
**Label:** Coordinates are evidence-backed
**Pass:** 80%+ of coordinate assignments have `evidence_source: "researched"` or `"founder_override"` (not `"agent_estimate"`). Evidence strings are specific, not generic.
**Fail:** More than 50% of coordinates are `agent_estimate` without supporting evidence. Positions are asserted, not demonstrated.
**Warn:** 50-80% of coordinates are evidence-backed. Some positions are well-supported, others are estimates.
**Basis:** A positioning map built on guesses is not investor-ready. Evidence-backed positions survive due diligence scrutiny.

### `POS_04`
**Label:** Startup is differentiated on at least one axis
**Pass:** `_startup` ranks in the top 2 among competitors on at least one axis (per `score_positioning.py` rank data). The differentiation is supported by evidence.
**Fail:** `_startup` ranks in the bottom half on both axes. The positioning map actually argues against the startup's competitive position.
**Warn:** `_startup` is mid-pack on both axes — not clearly differentiated but not badly positioned.
**Basis:** The entire point of positioning analysis is to identify where the startup wins. If the map shows the startup losing on all dimensions, the axes are wrong or the positioning needs work.

### `POS_05`
**Label:** Axis rationale explains differentiation value
**Pass:** Both axis rationales connect the dimension to buyer value — explaining not just what the axis measures but why it matters for purchase decisions.
**Fail:** Rationales are missing or merely restate the axis name without explaining relevance to buyers.
**Warn:** Rationales exist but are thin — they describe the axis without connecting to buyer impact.
**Basis:** "Deployment Speed" as an axis is meaningless without "...because mid-market buyers evaluate 3 tools in a 2-week trial window, and the fastest-to-deploy tool wins 70% of evaluations."

---

## Category 3 — Moat Assessment (MOAT) — 4 items

### `MOAT_01`
**Label:** All 6 canonical moat types evaluated
**Pass:** Every company in the landscape (plus `_startup`) has been assessed on all 6 canonical moat types (`network_effects`, `data_advantages`, `switching_costs`, `regulatory_barriers`, `cost_structure`, `brand_reputation`). `not_applicable` with evidence is acceptable.
**Fail:** One or more companies are missing moat assessments for canonical types. Incomplete coverage.
**Warn:** All companies assessed but some `not_applicable` ratings lack substantive evidence (<20 characters).
**Basis:** Completeness is non-negotiable for an investor-ready moat assessment. Skipping moat types suggests the analyst did not consider all dimensions of defensibility.

### `MOAT_02`
**Label:** Moat evidence meets quality floor
**Pass:** All moats rated `strong` or `moderate` have evidence strings of 20+ characters that cite specific facts (not generic assertions).
**Fail:** Multiple `strong` or `moderate` ratings have empty or generic evidence ("Good moat", "Strong advantage"). `MOAT_WITHOUT_EVIDENCE` warnings present.
**Warn:** Most evidence is substantive but 1-2 entries are thin.
**Basis:** A moat rating without evidence is an opinion, not an assessment. Investors will challenge every moat claim — the evidence must be ready.

### `MOAT_03`
**Label:** Trajectory included for each moat
**Pass:** Every moat assessment includes a trajectory (`building`, `stable`, `eroding`) with reasoning. Trajectory matches the evidence (e.g., growing user base + `building` for network effects).
**Fail:** Trajectories are missing or all set to `stable` without analysis (default-filling).
**Warn:** Trajectories present but reasoning is thin for some entries.
**Basis:** Moats are not static. Investors want to know which moats are strengthening and which are at risk. A `strong` moat that is `eroding` is very different from a `moderate` moat that is `building`.

### `MOAT_04`
**Label:** Custom moats justified (if present)
**Pass:** Any custom moat dimensions (`custom_{slug}`) include a clear definition explaining why the canonical 6 types are insufficient, with evidence meeting the same quality floor as canonical moats.
**Fail:** Custom moats added without justification, or custom moat duplicates a canonical type (e.g., `custom_patents` when `regulatory_barriers` already covers it).
**Warn:** Custom moat is justified but evidence is thinner than canonical moat assessments.
**Basis:** Custom moats should be rare. Adding unnecessary custom dimensions dilutes the analysis. They must earn their place with a clear argument for why the canonical taxonomy is insufficient.

---

## Category 4 — Evidence Quality (EVID) — 4 items

### `EVID_01`
**Label:** Per-competitor research depth recorded
**Pass:** Every competitor has a `research_depth` field (`full`, `partial`, or `founder_provided`) and `sourced_fields_count` in `landscape.json`. Provenance is transparent.
**Fail:** Research depth metadata is missing for most competitors. No way to assess evidence quality.
**Warn:** Research depth recorded for some competitors but not all.
**Basis:** Investors and the agent itself need to know how much of the analysis is researched vs. estimated. Provenance metadata enables honest qualification of claims.

### `EVID_02`
**Label:** Majority of competitors have sourced evidence
**Pass:** 60%+ of competitors have `research_depth: "full"` (enriched via web research with multiple sourced fields).
**Fail:** Fewer than 40% of competitors have sourced evidence. Analysis is primarily based on agent knowledge or founder claims.
**Warn:** 40-60% of competitors have sourced evidence. Mixed research quality.
**Basis:** An analysis built primarily on agent knowledge (training data) is less reliable than one built on current research. Investors value current, sourced data.
**Mode gating:** Auto-gated to `not_applicable` in `deck` mode (deck-sourced analyses rely on deck claims as primary input).

### `EVID_03`
**Label:** Evidence sources distinguished (researched vs. estimated)
**Pass:** `evidence_source` fields are populated throughout positioning and moat data. Clear distinction between `researched`, `agent_estimate`, and `founder_override` provenance.
**Fail:** Evidence source fields are missing or all set to the same value (suggesting they were not genuinely tracked).
**Warn:** Evidence sources present but inconsistently applied (some entries have provenance, others do not).
**Basis:** Distinguishing researched facts from agent estimates is intellectual honesty. The report should make clear what is verified vs. inferred.

### `EVID_04`
**Label:** Competitor financials/pricing sourced
**Pass:** For competitors where pricing or funding data is included, it has `evidence_source: "researched"` with specific sourcing (not just "agent knowledge").
**Fail:** Pricing/funding data is presented as fact but sourced from agent estimates. Stale or fabricated financial data.
**Warn:** Some financial data is sourced, some is estimated but labeled as such.
**Basis:** Competitor financials change frequently. Stale pricing data from training data is worse than no data — it creates false confidence.
**Mode gating:** Auto-gated to `not_applicable` in `deck` and `conversation` modes (these modes typically lack detailed competitor financials).

---

## Category 5 — Narrative Readiness (NARR) — 4 items

### `NARR_01`
**Label:** Differentiation claims stress-tested
**Pass:** Every differentiation claim in `positioning.json` has been stress-tested with a `verifiable` assessment, `evidence`, and `challenge` (what an investor would push on). At least one claim has verdict `holds`.
**Fail:** No stress-testing performed, or all claims have verdict `does_not_hold`. The competitive narrative has no defensible differentiation.
**Warn:** Stress-testing performed but most claims are `partially_holds` — differentiation exists but is not strong.
**Basis:** Investors will push on every differentiation claim. The founder must know which claims hold up under scrutiny and which need qualification.

### `NARR_02`
**Label:** Investor-ready competitive framing
**Pass:** The analysis frames competition constructively: acknowledges strong competitors without dismissing them, positions the startup's advantages clearly, and addresses "why will you win?" with evidence. Suitable for inclusion in an investor deck or data room.
**Fail:** Analysis is either dismissive of competitors ("they're not a real threat") or defeatist ("they're too far ahead"). Neither is investor-ready.
**Warn:** Framing is reasonable but could be stronger — some competitors are insufficiently analyzed or the "why we win" argument lacks evidence.
**Basis:** The output of this skill feeds directly into investor materials. The competitive narrative must be honest, evidence-backed, and constructive.

### `NARR_03`
**Label:** Competition slide alignment (deck cross-check)
**Pass:** If a pitch deck was provided, the competitive analysis aligns with the competition slide. Discrepancies (competitors omitted from deck, different positioning claims) are flagged and explained.
**Fail:** Significant discrepancies between the deck's competition slide and the analysis, with no acknowledgment. Investor would see contradictions.
**Warn:** Minor discrepancies acknowledged (e.g., deck omits one competitor that the analysis includes) with reasonable explanation.
**Basis:** If the founder is using this analysis to improve their deck, the two must be consistent. An investor who sees the deck AND a competitive analysis expects alignment.
**Mode gating:** Auto-gated to `not_applicable` in `conversation` and `document` modes (no deck to cross-check).

### `NARR_04`
**Label:** Defensibility roadmap articulated
**Pass:** Analysis includes a forward-looking view of which moats to build and in what order, based on current strengths and trajectory. Specific actions tied to moat-building.
**Fail:** No forward-looking defensibility discussion. Analysis is purely backward-looking (current state only).
**Warn:** Some forward-looking discussion but vague or not tied to specific moat dimensions.
**Basis:** Investors invest in trajectory, not just current state. A startup with `weak` moats but a clear, credible plan to build `moderate`+ moats is more attractive than one with no plan.

---

## Category 6 — Common Mistakes (MISS) — 3 items

### `MISS_01`
**Label:** No "we have no competitors" claim
**Pass:** The analysis acknowledges competition honestly. Even in novel markets, alternatives (do-nothing, adjacent solutions) are identified.
**Fail:** The analysis concludes or implies "no real competitors" without substantiation. This is the single most common red flag VCs cite.
**Warn:** Competition is acknowledged but minimized ("they're not a serious threat" without evidence).
**Basis:** "We have no competitors" is the fastest way to lose investor credibility. Every product competes with alternatives — at minimum, the status quo. This check exists because the founder may push the agent toward this claim at Gate 1 or Gate 2.

### `MISS_02`
**Label:** No vanity axes selected
**Pass:** Positioning axes were selected to reveal genuine competitive dynamics, not to make the startup look uniquely positioned. No vanity flags from `score_positioning.py`.
**Fail:** Both positioning axes are vanity — selected to put the startup alone in a quadrant rather than to reveal real market dynamics. The classic "we chose axes where only we score high."
**Warn:** One vanity axis detected. The map partially reveals dynamics but one axis is suspect.
**Basis:** The "vanity quadrant" (choose two axes where you score uniquely high and competitors cluster elsewhere) is the competitive positioning equivalent of an inflated TAM. Sophisticated investors see through it immediately.

### `MISS_03`
**Label:** No feature-checkbox thinking
**Pass:** Competitive analysis focuses on dimensions that matter to buyers (speed, cost, outcomes, trust, switching effort) rather than feature checklists. Differentiation is expressed in terms of customer value.
**Fail:** Analysis is a feature comparison matrix ("we have X, they don't have X"). Features without buyer-value context. The classic "we have 12 features, they only have 8" thinking.
**Warn:** Mostly value-focused but some analysis sections devolve into feature comparisons.
**Basis:** Feature parity is a losing game — incumbents will copy features. Sustainable differentiation comes from structural advantages (moats), not feature lists. Investors care about defensible positioning, not feature counts.
