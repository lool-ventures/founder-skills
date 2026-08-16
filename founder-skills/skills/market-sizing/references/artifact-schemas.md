# Artifact Schemas

JSON schemas for all analysis artifacts deposited during the market sizing workflow. Each artifact is a JSON file written to the `ANALYSIS_DIR` working directory.

## inputs.json

**Producer:** Agent (heredoc, Step 2)

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `company_name` | string | yes | Company being analyzed |
| `analysis_date` | string | yes | ISO date (YYYY-MM-DD) |
| `stage` | string | yes | Funding stage (e.g., `"seed"`, `"series_a"`) |
| `sector` | string | yes | Industry / sector (e.g., `"B2B SaaS"`) |
| `materials_provided` | string[] | yes | List of input materials (e.g., "pitch deck", "financial model") |
| `product_description` | string | yes | What the company sells |
| `target_segments` | string[] | yes | Customer segments served |
| `geography` | string | yes | Where they operate |
| `pricing_model` | string | yes | How they charge |
| `revenue_model` | string | yes | Revenue model (e.g., `"subscription"`, `"usage"`) |
| `existing_claims` | object | no | Deck's TAM/SAM/SOM figures. Must be a flat object with lowercase keys `tam`, `sam`, `som` (use `null` when the deck does not state a figure). Non-canonical keys are silently ignored by reconciliation and trigger `EXISTING_CLAIMS_SHAPE`. |
| `existing_claims_detail` | object \| null | no | Narrative-only deck claims that don't fit the canonical `{tam, sam, som}` shape (regional sub-SAMs, time-anchored figures, alternative TAM frames). Rendered as a "Deck Claims (Narrative)" sub-section in the report; **not** validated, **not** reconciled. |
| `currency` | string | no | ISO code every money figure in the analysis is denominated in (default `"USD"`). A label, and the conversion TARGET. Nothing is converted unless a money input declares a different source currency (`industry_total_currency` / `arpu_currency`) **and** a rate is supplied (`--fx-rate SRC:TGT=RATE`); a declared foreign currency with no rate is a hard error, never a guess. Any conversion performed is recorded in `sizing.json`'s `fx` block and disclosed in the report. `compose_report.py` and `visualize.py` render `"USD"` as a `$` prefix and any other code as a suffix (`270.0M EUR`); a non-USD analysis that converted nothing gets an explicit no-FX disclosure, and a converted one gets the rate, its date and its source instead. Checked ahead of `sizing.json`'s own `currency`; a disagreement between the two raises `CURRENCY_MISMATCH`. |
| `sizing_basis` | string | no | Convention this analysis' figures follow: `"current_year"` (default) \| `"forecast_year"` \| `"mixed"` — see `tam-sam-som-methodology.md` §5. Carried into `sizing.json` via `market_sizing.py --sizing-basis` (Step 5). Absence means not declared; `compose_report.py` and `visualize.py` render "Not declared", never a silent default to `"current_year"`. |
| `founder_stated_inputs` | object | no | Flat object of quantitative parameters the founder **stated outright** — any of `customer_count`, `arpu`, `serviceable_pct`, `target_pct`, `industry_total`, `segment_pct`, `share_pct`. Not for researched, inferred, or estimated values. `compose_report.py` compares these against what the sizing math actually consumed and raises `FOUNDER_VALUE_OVERRIDDEN` on a >0.5% divergence, so a researched figure cannot silently replace a founder-stated one. Empty/absent disables the check. |
| `founder_stated_inputs_currency` | string | no | ISO code the `founder_stated_inputs` money figures are in. Only consulted when a money input was FX-converted: without it the comparison against the converted figure would diverge by exactly the exchange rate, so `compose_report.py` reports `COMPARISON_CURRENCY_UNKNOWN` instead of a false `FOUNDER_VALUE_OVERRIDDEN`. Declare it whenever the founder's figures are not in `currency`. |
| `existing_claims_currency` | string | no | ISO code the `existing_claims` figures are in — the deck's own currency, which is not always the analysis currency. Same rule as above: without it a converted run reports `COMPARISON_CURRENCY_UNKNOWN` rather than a false `DECK_CLAIM_MISMATCH`. |
| `competitive_landscape_notes` | string \| null | no | Summary of any competitor/competitive-positioning content found in the deck (or `null` if the deck doesn't address competition). The CHECKLIST sub-agent never reads the deck itself — it scores `competitive_landscape_acknowledged` from this field only. |
| `gtm_evidence_notes` | string \| null | no | Summary of any customer-acquisition strategy, sales-funnel metrics, or comparable-company benchmark found in the materials (or `null` if none found). The CHECKLIST sub-agent never reads the deck itself — it scores `som_backed_by_gtm` from this field only. Distinct from `projections_alignment_notes` below: this is customer-acquisition evidence, not financial-plan evidence, and one field cannot stand in for both. |
| `projections_alignment_notes` | string \| null | no | Summary of whether the materials show the SOM figure lining up with the hiring plan, sales capacity, or burn rate (or `null` if not addressed). The CHECKLIST sub-agent never reads the financial model itself — it scores `som_consistent_with_projections` from this field only. |
| `stated_metrics` | object | no | Revenue, customer count, growth rates from materials |
| `metadata` | object | yes | `{"run_id": "<RUN_ID>"}` — stamped on every artifact; `compose_report.py` fires `STALE_ARTIFACT` if run IDs across artifacts mismatch |

**Example:**
```json
{
  "company_name": "Acme Corp",
  "analysis_date": "2026-01-15",
  "stage": "seed",
  "sector": "B2B SaaS",
  "materials_provided": ["pitch deck", "financial model"],
  "product_description": "Cloud-based SMB accounting software",
  "target_segments": ["Small businesses (1-50 employees)"],
  "geography": "North America",
  "pricing_model": "Monthly SaaS subscription, $50-200/month",
  "revenue_model": "subscription",
  "sizing_basis": "current_year",
  "existing_claims": {"tam": 50000000000, "sam": 8000000000, "som": 200000000},
  "existing_claims_detail": {
    "regional_sam_north_america": 4500000000,
    "som_year_3_target": 350000000
  },
  "competitive_landscape_notes": "Deck slide 9 names 3 competitors and claims a differentiated pricing model.",
  "gtm_evidence_notes": "Deck slide 11: outbound to 40 target accounts/quarter via 2 AEs, 15% demo-to-close rate cited from a competitor's S-1.",
  "projections_alignment_notes": "Financial model shows 3 AEs hired by Q3, consistent with the SOM ramp.",
  "stated_metrics": {"arr": 2000000, "customers": 500, "yoy_growth_pct": 150},
  "metadata": {"run_id": "20260115T120000Z"}
}
```

---

## methodology.json

**Producer:** Agent (heredoc, Step 3)

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `approach_chosen` | string | yes | One of: `"top_down"`, `"bottom_up"`, `"both"` |
| `rationale` | string | yes | Why this approach was chosen |
| `accepted_warnings` | object[] | no | Warning codes the analyst expects and accepts |
| `metadata` | object | yes | `{"run_id": "<RUN_ID>"}` — stamped on every artifact (see inputs.json) |

### accepted_warnings[] entry

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `code` | string | yes | Must be a valid medium-severity WARNING_SEVERITY key (high-severity codes cannot be accepted) |
| `reason` | string | yes | Explanation of why this warning is expected |
| `match` | string | yes | Substring that must appear in the warning message for acceptance to apply (instance-scoped matching) |

**Example:**
```json
{
  "approach_chosen": "both",
  "rationale": "Industry reports available for top-down, company has customer/pricing data for bottom-up. Cross-validation preferred.",
  "accepted_warnings": [
    {"code": "TAM_DISCREPANCY", "reason": "Different scopes intended", "match": "differ by"}
  ],
  "metadata": {"run_id": "20260115T120000Z"}
}
```

**compose_report.py validates:** `approach_chosen` is cross-checked with sizing.json — if methodology says `"both"` but sizing.json lacks `top_down` or `bottom_up`, `APPROACH_MISMATCH` fires.

---

## validation.json

**Producer:** Main thread (heredoc after WebFetch/WebSearch research, Step 4)

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `sources` | object[] | yes | External sources found and used |
| `figure_validations` | object[] | yes | Validation status per market figure |
| `assumptions` | object[] | yes | All assumptions used in the analysis |
| `metadata` | object | yes | `{"run_id": "<RUN_ID>"}` — stamped on every artifact (see inputs.json) |

### sources[] entry

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `title` | string | yes | Source title |
| `publisher` | string | yes | Publisher name |
| `url` | string | no | Source URL (only if found via web) |
| `date_accessed` | string | yes | When accessed (YYYY-MM-DD) |
| `quality_tier` | string | yes | One of: `"government"`, `"analyst_firm"`, `"industry_association"`, `"academic"`, `"business_press"`, `"company_blog"` |
| `segment_match` | string | yes | How well source matches product segment: `"exact"`, `"partial"`, `"broad"` |
| `supported` | string | yes | What figure(s) this source supports |

### figure_validations[] entry

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `figure` | string | yes | Name of the figure (e.g., "TAM", "SAM", "customer_count") |
| `label` | string | no | Human-readable display name (e.g., "Passenger Count (Year 5)"). If omitted, `figure` is used as-is. |
| `status` | string | yes | One of: `"validated"` (2+ sources confirm), `"partially_supported"` (1 source), `"unsupported"` (not investigated / no sources found), `"refuted"` (investigated and disproved) |
| `source_count` | integer | yes | Number of independent sources confirming this figure |
| `refutation` | string | no | Explanation of why the figure was rejected (required when status is "refuted") |
| `notes` | string | no | Additional context |

### assumptions[] entry

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | yes | Parameter name — must match market_sizing.py / sensitivity.py parameter names for quantitative assumptions (see list below). Qualitative assumptions use descriptive names. |
| `label` | string | no | Human-readable display name. If omitted, falls back to title-cased `name`. |
| `value` | any | yes | The assumed value |
| `category` | string | yes | One of: `"sourced"` (cite the source), `"derived"` (show formula), `"agent_estimate"` (flagged as unsupported) |
| `source` | string | no | Citation for sourced assumptions |
| `derivation` | string | no | Formula/logic for derived assumptions |

**Quantitative parameter names** (must match exactly for UNSOURCED_ASSUMPTIONS check):
`customer_count`, `arpu`, `serviceable_pct`, `target_pct`, `industry_total`, `segment_pct`, `share_pct`

Qualitative assumptions (e.g., `market_growing`, `regulatory_favorable`) are exempt from the sensitivity cross-check.

**Example:**
```json
{
  "sources": [
    {
      "title": "Global SMB Accounting Software Market Report 2025",
      "publisher": "Grand View Research",
      "url": "https://example.com/report",
      "date_accessed": "2026-01-15",
      "quality_tier": "analyst_firm",
      "segment_match": "exact",
      "supported": "TAM, market growth rate"
    }
  ],
  "figure_validations": [
    {"figure": "TAM", "status": "validated", "source_count": 3},
    {"figure": "SAM", "status": "partially_supported", "source_count": 1},
    {"figure": "customer_count", "label": "SMB Customer Count", "status": "unsupported", "source_count": 0, "notes": "No public data on SMB count"}
  ],
  "assumptions": [
    {"name": "industry_total", "value": 50000000000, "category": "sourced", "source": "Grand View Research 2025"},
    {"name": "segment_pct", "label": "SMB Segment Share", "value": 16, "category": "derived", "derivation": "SMB share of total market from BLS data"},
    {"name": "customer_count", "value": 4500000, "category": "agent_estimate"},
    {"name": "market_growing", "value": true, "category": "sourced", "source": "Grand View Research 2025"}
  ],
  "metadata": {"run_id": "20260115T120000Z"}
}
```

**compose_report.py validates:**
- `UNVALIDATED_CLAIMS`: any figure with `status: "unsupported"` (high severity)
- `OVERCLAIMED_VALIDATION`: any figure with `status: "validated"` but `source_count < 2`
- `UNSOURCED_ASSUMPTIONS`: agent_estimate assumptions whose `name` is a quantitative parameter but not found in sensitivity.json scenarios with `confidence: "agent_estimate"`
- `REFUTED_CLAIMS`: any figure with `status: "refuted"` (medium severity)
- `REFUTED_MISSING_REASON`: refuted figure without `refutation` field (medium severity)

---

## sizing.json

**Producer:** `market_sizing.py` (Step 5, `-o` output mode)

This is the direct output of `market_sizing.py`. Structure depends on approach used.

### Top-level keys

| Key | Present when | Description |
|-----|-------------|-------------|
| `approach` | always | `"top-down"`, `"bottom-up"`, or `"both"` |
| `currency` | always | Currency label (default `"USD"`) |
| `sizing_basis` | when declared | `"current_year"` \| `"forecast_year"` \| `"mixed"` — passed through from `inputs.json` via `market_sizing.py --sizing-basis` (Step 5). **Absent, not defaulted, when the run never declared one** — `compose_report.py` / `visualize.py` render "Not declared" rather than assuming `"current_year"`. See `tam-sam-som-methodology.md` §5. |
| `top_down` | approach is `"top-down"` or `"both"` | Top-down results |
| `bottom_up` | approach is `"bottom-up"` or `"both"` | Bottom-up results |
| `comparison` | approach is `"both"` | Cross-validation results |
| `fx` | only when a conversion happened | `{as_of, source, conversions: [{field, from, to, rate, original_value, converted_value}]}`. Present only when a money input declared a source currency differing from `currency` AND a rate was supplied. `converted_value` **is** the number the sizing math consumed, so `compose_report.py` can compare a founder-stated or deck-claimed figure across the conversion. Absent on every run that converted nothing — which is every run that does not opt in. |
| `metadata` | when `--run-id` passed | `{"run_id": "<RUN_ID>"}` — stamped by the producer for `STALE_ARTIFACT` detection |

**Rejected runs.** `market_sizing.py` refuses an invalid input rather than writing a figure-less stub:
the diagnostic goes to stdout, a line to stderr, `-o` is left untouched, and it exits non-zero. So a
`sizing.json` carrying `validation.status == "invalid"` means a **stale or hand-edited** file, and
`compose_report.py` raises `SIZING_INVALID` at **high** severity (not acceptable-away) rather than
rendering an empty sizing table. `sensitivity.py` and `checklist.py` behave the same way; a rejected
artifact from either raises `ARTIFACT_INVALID`, also high.

**Currency comparison.** When a money input was FX-converted, a founder-stated figure or deck claim
that declares no currency cannot be compared against it — the divergence would be exactly the exchange
rate. `compose_report.py` then raises `COMPARISON_CURRENCY_UNKNOWN` (medium) instead of a
guaranteed-false `FOUNDER_VALUE_OVERRIDDEN` / `DECK_CLAIM_MISMATCH`. Declaring
`founder_stated_inputs_currency` / `existing_claims_currency` restores the real check.

### top_down / bottom_up sub-object

Each contains `tam`, `sam`, `som` objects with:
- `value` (number) — the calculated amount
- `formula` (string) — how it was calculated
- `inputs` (object) — input values used

### comparison sub-object

| Field | Type | Description |
|-------|------|-------------|
| `top_down_tam` | number | Top-down TAM value |
| `bottom_up_tam` | number | Bottom-up TAM value |
| `tam_delta_pct` | number | Percentage difference between approaches |
| `warning` | string | Present if delta > 30% |
| `note` | string | Present if delta <= 30% |

**compose_report.py validates:**
- `APPROACH_MISMATCH`: cross-checks with methodology.json `approach_chosen`
- `TAM_DISCREPANCY`: `comparison.tam_delta_pct > 30`

### Provenance (computed at render time)

Provenance is **not stored** in `sizing.json` — it is computed at render time by `compose_report.py` (persisted in output JSON) and `visualize.py` (used for chart rendering).

**How it works:**
1. Cross-references `validation.json` `assumptions[].category` with `sizing.json` figure `inputs`
2. For each TAM/SAM/SOM figure, looks up which input parameters were used and their assumption categories
3. Classifies the figure based on the "worst" category among its inputs:
   - All inputs `sourced` → figure classified as `"sourced"`
   - Any input `agent_estimate` → figure classified as `"agent_estimate"`
   - Otherwise (mix of sourced+derived, or all derived) → `"derived"`
   - No inputs found in assumption map → `"unknown"`
4. Deck claims come from `inputs.json` `existing_claims`
5. Delta vs deck is computed as `(calculated - claim) / claim * 100` (signed percentage)

**Output structure** (in `compose_report.py` output JSON, top-level `provenance` key):
```json
{
  "provenance": {
    "top_down": {
      "tam": {
        "classification": "sourced",
        "confidence_breakdown": {"sourced": 2, "derived": 0, "agent_estimate": 0},
        "deck_claim": 50000000000,
        "delta_vs_deck_pct": 35.0,
        "input_provenances": {"industry_total": "sourced", "segment_pct": "sourced"}
      }
    }
  }
}
```

Only parameters in `QUANTITATIVE_PARAMS` are matched: `customer_count`, `arpu`, `serviceable_pct`, `target_pct`, `industry_total`, `segment_pct`, `share_pct`. Intermediate keys (like `tam`, `sam`, `serviceable_customers`, `target_customers`) in figure inputs are silently skipped.

---

## sensitivity.json

**Producer:** `sensitivity.py` (Step 6a, `-o` output mode)

Direct output of `sensitivity.py` with confidence extensions.

### Input format (stdin)

```json
{
  "approach": "bottom_up",
  "base": {"customer_count": 4500000, "arpu": 15000, "serviceable_pct": 35, "target_pct": 0.5},
  "ranges": {
    "customer_count": {"low_pct": -30, "high_pct": 20, "confidence": "sourced"},
    "arpu": {"low_pct": -20, "high_pct": 15, "confidence": "agent_estimate"}
  }
}
```

**`ranges` must be an object (dict), not an array.** Keys are parameter names, values are `{low_pct, high_pct, confidence}`.

### Output format

| Key | Type | Description |
|-----|------|-------------|
| `approach` | string | `"bottom_up"`, `"top_down"`, or `"both"` |
| `base_result` | object | For single approach: `{tam, sam, som}`. For `"both"`: `{top_down: {tam, sam, som}, bottom_up: {tam, sam, som}}` |
| `scenarios` | object[] | Per-parameter sensitivity results |
| `sensitivity_ranking` | object[] | Parameters ranked by SOM impact |
| `most_sensitive` | string | Most impactful parameter name |
| `metadata` | object | `{"run_id": "<RUN_ID>"}` — stamped by the producer when `--run-id` is passed (see inputs.json) |

When `approach` is `"both"`, all 7 base params are required (`industry_total`, `segment_pct`, `share_pct`, `customer_count`, `arpu`, `serviceable_pct`, `target_pct`). Each range parameter is auto-detected to its approach (top-down or bottom-up) and sensitivity is run against that approach's calculation.

### scenarios[] entry

| Field | Type | Description |
|-------|------|-------------|
| `parameter` | string | Parameter name |
| `confidence` | string | `"sourced"`, `"derived"`, or `"agent_estimate"` |
| `original_range` | object | `{low_pct, high_pct}` as specified by agent |
| `effective_range` | object | `{low_pct, high_pct}` after auto-widening |
| `range_widened` | boolean | Whether auto-widening was applied |
| `base_value` | number | Base parameter value |
| `approach_used` | string | Present when approach is `"both"` — which sub-approach was used (`"top_down"` or `"bottom_up"`) |
| `low` | object | Low scenario results |
| `base` | object | Base scenario results |
| `high` | object | High scenario results |

**Auto-widening rules:**
- `sourced`: no minimum range (0%)
- `derived`: minimum +/-30%
- `agent_estimate`: minimum +/-50%

If the specified range is narrower than the minimum, it is widened. Wider ranges are never narrowed.

**compose_report.py validates:**
- `FEW_SENSITIVITY_PARAMS`: fewer than 3 scenarios
- `NARROW_AGENT_ESTIMATE_RANGE`: agent_estimate parameter with effective range less than +/-50%
- `UNSOURCED_ASSUMPTIONS`: cross-checks with validation.json for agent_estimate coverage

---

## checklist.json

**Producer:** `checklist.py` (Step 6b, `-o` output mode)

### Input format (stdin)

```json
{
  "items": [
    {"id": "structural_tam_gt_sam_gt_som", "status": "pass", "notes": null},
    {"id": "structural_definitions_correct", "status": "pass", "notes": null},
    ...
  ]
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `items` | object[] | yes | Array of checklist item assessments |

#### items[] entry (input)

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | string | yes | Canonical checklist item ID (see list below) |
| `status` | string | yes | One of: `"pass"`, `"fail"`, `"not_applicable"` |
| `notes` | string \| null | no | Agent's notes explaining the assessment |

All 22 canonical IDs must be present, with no duplicates and no unknown IDs. The script validates this and reports violations in the `validation` field of the JSON output (`validation.status: "invalid"`).

### Output format

Direct output of `checklist.py`.

| Key | Type | Description |
|-----|------|-------------|
| `items` | object[] | All 22 checklist items with results |
| `summary` | object | Aggregate counts and status |
| `metadata` | object | `{"run_id": "<RUN_ID>"}` — stamped by the producer when `--run-id` is passed (see inputs.json) |

### items[] entry

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Canonical item ID (see list below) |
| `category` | string | Category grouping |
| `label` | string | Human-readable label |
| `status` | string | `"pass"`, `"fail"`, or `"not_applicable"` |
| `notes` | string \| null | Agent's notes for this item |

### summary

| Field | Type | Description |
|-------|------|-------------|
| `total` | integer | Always 22 |
| `pass` | integer | Count of pass items |
| `fail` | integer | Count of fail items |
| `not_applicable` | integer | Count of N/A items |
| `score_pct` | number | `pass / (total - not_applicable) * 100`, rounded to 1 decimal; drives `coaching_payload.confidence` |
| `overall_status` | string | The fleet band the score falls in: `"strong"` (>=85), `"solid"` (>=70), `"needs_work"` (>=50), else `"major_revision"`. Same vocabulary as deck-review, financial-model-review and competitive-positioning — a founder running two skills must get grades that mean the same thing. |
| `all_pass` | boolean | `true` only when `fail == 0`. Independent of the band, not a summary of it: 21 of 22 items passing is 95.5%, a `strong` sizing that still has one item open. |
| `failed_items` | object[] | List of failed items with id, category, label, notes |

### Canonical 22 checklist IDs

**Structural Checks:** `structural_tam_gt_sam_gt_som`, `structural_definitions_correct`
**TAM Scoping:** `tam_matches_product_scope`, `source_segments_match`
**SOM Realism:** `som_share_defensible`, `som_backed_by_gtm`, `som_consistent_with_projections`
**Data Quality:** `data_current`, `sources_reputable`, `figures_triangulated`, `unsupported_figures_flagged`, `validated_used_precisely`, `assumptions_categorized`
**Methodology:** `both_approaches_used`, `approaches_reconciled`, `growth_dynamics_considered`
**Market Understanding:** `market_properly_segmented`, `competitive_landscape_acknowledged`, `sam_expansion_path_noted`
**Presentation:** `assumptions_explicit`, `formulas_shown`, `sources_cited`

**compose_report.py validates:**
- `CHECKLIST_FAILURES`: `fail` between 1 and 6 (**medium** severity — a content finding, acceptable via `accepted_warnings` with a stated reason)
- `CHECKLIST_FAILURES_CRITICAL`: the score cannot reach `solid` — `pass / (pass + fail)` below 70 (high severity, never acceptable). Stated as a BAND, not a failure count: an absolute `fail > 6` assumes all 22 criteria apply, and with 7 `not_applicable` items the boundary is 5, so a checklist scoring 66.7% was filed as the acceptable warning. The band reproduces 6/7 exactly when nothing is N/A (7 of 22 caps the score at 68.2%; 6 reaches 72.7%). The two warnings are mutually exclusive.
- `CHECKLIST_INCOMPLETE`: fewer than 22 items
- `LOW_CHECKLIST_COVERAGE`: more than 7 `not_applicable` items (medium severity)
