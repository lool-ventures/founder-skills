# Market Sizing Pitfalls Checklist

Use this checklist to review your market sizing analysis before presenting it. Each item corresponds to a common mistake that undermines credibility with investors.

## Structural Checks (2 items)

### `structural_tam_gt_sam_gt_som`
**Label:** TAM > SAM > SOM
**Pass:** The three values are properly nested — SOM is a subset of SAM, which is a subset of TAM.
**Fail:** Any value breaks this hierarchy, indicating the definitions are being confused.

### `structural_definitions_correct`
**Label:** Definitions used correctly
**Pass:** TAM = total market if 100% share; SAM = portion you can serve given constraints; SOM = what you can realistically capture near-term.
**Fail:** Definitions are misused or confused. Misusing these signals lack of strategic clarity.

## TAM Scoping (2 items)

### `tam_matches_product_scope`
**Label:** TAM matches product scope
**Pass:** TAM is scoped to the product's actual target market. If the product targets SMBs, TAM is the SMB market for that category, not the total industry including enterprise/government/military.
**Fail:** TAM uses an inflated industry total that doesn't match the product. If a segment-specific TAM figure isn't available, use bottom-up as primary TAM and note the total industry only for context.

### `source_segments_match`
**Label:** Source segments match product segments
**Pass:** Every cited market share, market size, or growth figure matches the product's segment, geography, and time period.
**Fail:** Sources reference broader or mismatched segments. "Worldwide endpoint security share" is not valid for "NA SMB cybersecurity." If only broader data exists, explicitly note the mismatch.

## SOM Realism (3 items)

### `som_share_defensible`
**Label:** SOM share is defensible
**Pass:** SOM share is realistic for the startup's stage and market structure. In concentrated verticals or geographies (e.g., biotech targeting 10 hospitals, niche B2B with few buyers) higher shares can be realistic — but with explanation.
**Fail:** SOM above 5% of SAM in the first few years in a broad market without strong justification. Claiming 10%+ in a fragmented market without compelling evidence is a red flag.

### `som_backed_by_gtm`
**Label:** SOM backed by go-to-market plan
**Pass:** The SOM figure connects to specific customer acquisition strategies, funnel metrics, or analogous company benchmarks.
**Fail:** SOM is just a percentage pulled from thin air with no GTM justification.
**Evidence source:** This step never reads the deck or model directly — score from `inputs.json`'s
`gtm_evidence_notes` field (carried forward from materials extraction in Steps 2-3). If
`gtm_evidence_notes` is `null` or absent, treat as no GTM evidence was found in the materials (fail),
not as "not investigated."

### `som_consistent_with_projections`
**Label:** SOM consistent with financial projections
**Pass:** SOM revenue figure aligns with the startup's hiring plan, sales capacity, and burn rate.
**Fail:** Disconnects between SOM and business plan destroy credibility. If SOM implies $10M revenue, but the team/ops can't support that, it fails.
**Evidence source:** This step never reads the financial model directly — score from `inputs.json`'s
`projections_alignment_notes` field (carried forward from materials extraction in Steps 2-3). If
`projections_alignment_notes` is `null` or absent, treat as no alignment evidence was found in the
materials (fail), not as "not investigated." Distinct from `gtm_evidence_notes` above — GTM evidence
is about customer acquisition, this is about hiring/capacity/burn; one field can't serve both.

## Data Quality (6 items)

### `data_current`
**Label:** Data is current
**Pass:** Market figures are from the last 2 years. In slower-moving or regulated sectors (healthcare, infrastructure, defense) older benchmark datasets may be acceptable — but explicitly note the data age and explain why it's still applicable.
**Fail:** Data is outdated for the sector. In fast-moving sectors (tech, crypto, AI) older data is unreliable.

### `sources_reputable`
**Label:** Sources are reputable
**Pass:** Prioritizes government statistics, regulatory filings, industry associations, established analyst firms (Gartner, IDC, Statista, IBISWorld).
**Fail:** Relies on company blogs and vendor marketing for market-size baselines.

### `figures_triangulated`
**Label:** Key figures triangulated
**Pass:** Critical numbers are corroborated by 2+ independent sources.
**Fail:** A figure can only be found in one place. Mark it as "weakly supported."

### `unsupported_figures_flagged`
**Label:** Unsupported figures flagged
**Pass:** Any number that cannot be externally validated is explicitly marked as "unsupported" or "estimate" with stated reasoning.
**Fail:** Unsupported figures are presented as facts without flagging.

### `validated_used_precisely`
**Label:** "Validated" used precisely
**Pass:** A figure is "validated" only when 2+ independent public sources confirm it. One source = "partially supported." Zero sources = "unsupported" or "agent estimate."
**Fail:** Claims "all figures validated" when figures don't meet the 2-source bar.

### `assumptions_categorized`
**Label:** Assumptions categorized
**Pass:** Every assumption is labeled as "sourced" (with citation), "derived" (with formula), or "agent estimate" (flagged as unsupported). No unlabeled assumptions.
**Fail:** Assumptions are not categorized or all presented as sourced when they aren't.

## Methodology (3 items)

### `both_approaches_used`
**Label:** Both approaches used
**Pass:** The analysis uses both top-down and bottom-up methods where data allows.
**Fail:** Only one approach is used. Top-down alone is coarse; bottom-up alone may miss the big picture.

### `approaches_reconciled`
**Label:** Gap between the two approaches is explained
**Pass:** Whatever the gap, the analysis says what drives it — which inputs differ and why.
**Fail:** The gap is unexplained, or agreement is presented as confirmation.

Agreement is **not** a pass on its own. The pipeline does not track where each input came from, so it
cannot tell whether the two builds are independent; a small delta may simply mean both rest on the
same underlying figures. Awarding a point for closeness rewards exactly that. What earns the point is
an explanation of the gap, in either direction.

### `growth_dynamics_considered`
**Label:** Market growth dynamics considered
**Pass:** Includes CAGR or growth trends. Notes whether the market is growing, shrinking, or being disrupted.
**Fail:** Static figures only, ignoring a critical dimension.

## Market Understanding (3 items)

### `market_properly_segmented`
**Label:** Market properly segmented
**Pass:** SAM is derived from specific segments (geography, customer type, use case).
**Fail:** SAM is just a hand-wavy percentage of TAM without segment-specific justification.

### `competitive_landscape_acknowledged`
**Label:** Competitive landscape acknowledged
**Pass:** SOM accounts for existing competitors with realistic positioning.
**Fail:** Ignores competition or claims "no competitors."
**Evidence source:** This step never reads the deck directly — score from `inputs.json`'s
`competitive_landscape_notes` field (carried forward from deck extraction in Steps 2-3). If
`competitive_landscape_notes` is `null` or absent, treat as no competitive content was found in
the deck (fail), not as "not investigated."

### `sam_expansion_path_noted`
**Label:** SAM expansion path noted
**Pass:** Analysis mentions how SAM could grow over time (new geographies, segments, product lines). This shows strategic thinking.
**Fail:** No expansion path discussed.

## Presentation (3 items)

### `assumptions_explicit`
**Label:** Assumptions explicit
**Pass:** Every key assumption is stated clearly, not buried in the math. An investor should be able to challenge any individual assumption.
**Fail:** Assumptions are hidden or implicit.

### `formulas_shown`
**Label:** Formulas shown
**Pass:** The calculation steps are transparent (TAM = X customers x $Y ARPU), not just final numbers.
**Fail:** Only final numbers with no visible methodology.

### `sources_cited`
**Label:** Sources cited
**Pass:** Every external data point has a source attribution.
**Fail:** Numbers presented without sources.
