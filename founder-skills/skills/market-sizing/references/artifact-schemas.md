# Artifact Schemas

JSON schemas for all analysis artifacts deposited during the market sizing workflow. Each artifact is a JSON file written to the `ANALYSIS_DIR` working directory.

## inputs.json

**Producer:** Agent (heredoc, Step 1)

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `company_name` | string | yes | Company being analyzed |
| `analysis_date` | string | yes | ISO date (YYYY-MM-DD) |
| `materials_provided` | string[] | yes | List of input materials (e.g., "pitch deck", "financial model") |
| `product_description` | string | yes | What the company sells |
| `target_customer` | string | yes | Who they sell to |
| `geography` | string | yes | Where they operate |
| `pricing_model` | string | yes | How they charge |
| `existing_claims` | object | no | Any TAM/SAM/SOM figures from the pitch deck |
| `stated_metrics` | object | no | Revenue, customer count, growth rates from materials |

**Example:**
```json
{
  "company_name": "Acme Corp",
  "analysis_date": "2026-01-15",
  "materials_provided": ["pitch deck", "financial model"],
  "product_description": "Cloud-based SMB accounting software",
  "target_customer": "Small businesses (1-50 employees)",
  "geography": "North America",
  "pricing_model": "Monthly SaaS subscription, $50-200/month",
  "existing_claims": {"tam": 50000000000, "sam": 8000000000, "som": 200000000},
  "stated_metrics": {"arr": 2000000, "customers": 500, "yoy_growth_pct": 150}
}
```

---

## methodology.json

**Producer:** Agent (heredoc, Step 2)

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `approach_chosen` | string | yes | One of: `"top_down"`, `"bottom_up"`, `"both"` |
| `rationale` | string | yes | Why this approach was chosen |
| `reference_file_read` | string[] | yes | List of reference filenames actually read (e.g., `["tam-sam-som-methodology.md", "artifact-schemas.md"]`) |
| `accepted_warnings` | object[] | no | Warning codes the analyst expects and accepts |

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
  "reference_file_read": ["tam-sam-som-methodology.md", "pitfalls-checklist.md", "artifact-schemas.md"],
  "accepted_warnings": [
    {"code": "TAM_DISCREPANCY", "reason": "Different scopes intended", "match": "differ by"}
  ]
}
```

**compose_report.py validates:** `approach_chosen` is cross-checked with sizing.json — if methodology says `"both"` but sizing.json lacks `top_down` or `bottom_up`, `APPROACH_MISMATCH` fires.

---

## validation.json

**Producer:** Agent (heredoc, Step 3)

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `sources` | object[] | yes | External sources found and used |
| `figure_validations` | object[] | yes | Validation status per market figure |
| `assumptions` | object[] | yes | All assumptions used in the analysis |

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
  ]
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

**Producer:** `market_sizing.py` (Step 4, `-o` output mode)

This is the direct output of `market_sizing.py`. Structure depends on approach used.

### Top-level keys

| Key | Present when | Description |
|-----|-------------|-------------|
| `approach` | always | `"top-down"`, `"bottom-up"`, or `"both"` |
| `currency` | always | Currency label (default `"USD"`) |
| `top_down` | approach is `"top-down"` or `"both"` | Top-down results |
| `bottom_up` | approach is `"bottom-up"` or `"both"` | Bottom-up results |
| `comparison` | approach is `"both"` | Cross-validation results |

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

**Producer:** `sensitivity.py` (Step 5, `-o` output mode)

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

**Producer:** `checklist.py` (Step 6, `-o` output mode)

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
| `overall_status` | string | `"pass"` if fail==0, else `"fail"` |
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
- `CHECKLIST_FAILURES`: `overall_status == "fail"` (high severity)
- `CHECKLIST_INCOMPLETE`: fewer than 22 items
- `LOW_CHECKLIST_COVERAGE`: more than 7 `not_applicable` items (medium severity)
