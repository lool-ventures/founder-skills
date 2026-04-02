# Deck Review Artifact Schemas

JSON schemas for all artifacts deposited during the deck review workflow. Each artifact is a JSON file written to the `REVIEW_DIR` working directory.

## deck_inventory.json

**Producer:** Agent (heredoc, Step 2)

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `company_name` | string | yes | Company name (from deck or user) |
| `review_date` | string | yes | ISO date (YYYY-MM-DD) |
| `input_format` | string | yes | One of: `"pdf"`, `"pptx"`, `"markdown"`, `"text"` |
| `total_slides` | integer | yes | Total number of slides |
| `claimed_stage` | string | no | Stage claimed in deck (if any) |
| `claimed_raise` | string | no | Fundraising amount claimed (if any) |
| `slides` | object[] | yes | Per-slide extraction |

### slides[] entry

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `number` | integer | yes | Slide number (1-indexed) |
| `headline` | string | yes | Slide headline/title as written |
| `content_summary` | string | yes | Brief summary of slide content (2-3 sentences) |
| `visuals` | string | no | Description of charts, screenshots, diagrams |
| `word_count_estimate` | integer | no | Approximate word count on the slide |

**Example:**
```json
{
  "company_name": "Acme Corp",
  "review_date": "2026-02-20",
  "input_format": "pdf",
  "total_slides": 12,
  "claimed_stage": "seed",
  "claimed_raise": "$4M",
  "slides": [
    {
      "number": 1,
      "headline": "Acme Corp — Cloud Accounting for SMBs",
      "content_summary": "Company name, one-line description, logo. States '$2M ARR, 500 customers'.",
      "visuals": "Company logo, simple background",
      "word_count_estimate": 15
    }
  ]
}
```

---

## stage_profile.json

**Producer:** Agent (heredoc, Step 3)

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `detected_stage` | string | yes | String. Expected values: `"pre_seed"`, `"seed"`, `"series_a"` (calibrated). For later-stage companies use `"series_b"` or `"growth"` — the compose report will flag these as out of calibrated scope. |
| `confidence` | string | yes | One of: `"high"`, `"medium"`, `"low"` |
| `evidence` | string[] | yes | List of signals used to determine stage |
| `is_ai_company` | boolean | yes | Whether the company is AI-first |
| `ai_evidence` | string | no | Why classified as AI or not |
| `expected_framework` | string[] | yes | Expected slide types for this stage (from best practices) |
| `stage_benchmarks` | object | yes | Key benchmarks for the detected stage |
| `reference_file_read` | string[] | yes | Reference files read before analysis |
| `accepted_warnings` | object[] | no | Warning codes the reviewer expects and accepts |

### accepted_warnings[] entry

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `code` | string | yes | Must be a valid medium-severity warning code |
| `reason` | string | yes | Why this warning is expected |
| `match` | string | yes | Substring that must appear in warning message |

### stage_benchmarks

| Field | Type | Description |
|-------|------|-------------|
| `round_size_range` | string | Typical round size range (e.g., "$2M-$6M") |
| `expected_traction` | string | What traction is expected (e.g., "$300K-$500K ARR signals") |
| `runway_expectation` | string | Expected runway planning (e.g., "18-24 months") |

**Example:**
```json
{
  "detected_stage": "seed",
  "confidence": "high",
  "evidence": [
    "Claims $2M ARR",
    "500 paying customers",
    "Raising $4M",
    "Has repeatable sales motion"
  ],
  "is_ai_company": false,
  "ai_evidence": "No AI/ML product mentioned",
  "expected_framework": [
    "purpose_traction", "problem", "solution_product", "traction_kpis",
    "market", "competition", "business_model_pricing", "gtm",
    "unit_economics", "team", "financials", "ask_milestones"
  ],
  "stage_benchmarks": {
    "round_size_range": "$2M-$6M",
    "expected_traction": "$300K-$500K ARR signals",
    "runway_expectation": "18-24 months"
  },
  "reference_file_read": ["deck-best-practices.md", "checklist-criteria.md", "artifact-schemas.md"]
}
```

---

## slide_reviews.json

**Producer:** Agent (heredoc, Step 4)

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `reviews` | object[] | yes | Per-slide review |
| `missing_slides` | object[] | yes | Expected slides not found in deck |
| `overall_narrative_assessment` | string | yes | Brief assessment of overall narrative flow |

### reviews[] entry

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `slide_number` | integer | yes | Slide number from inventory |
| `maps_to` | string | yes | Which expected framework slide this corresponds to (or `"extra"` / `"appendix"`) |
| `strengths` | string[] | yes | Specific strengths of this slide |
| `weaknesses` | string[] | yes | Specific weaknesses of this slide |
| `recommendations` | string[] | yes | Actionable recommendations for improvement |
| `best_practice_refs` | string[] | yes | Which best-practice principles each critique cites |

### missing_slides[] entry

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `expected_type` | string | yes | The framework slide type that's missing |
| `importance` | string | yes | `"critical"`, `"important"`, or `"nice_to_have"` |
| `recommendation` | string | yes | What to add |

**Example:**
```json
{
  "reviews": [
    {
      "slide_number": 1,
      "maps_to": "purpose_traction",
      "strengths": ["Clear one-sentence purpose", "Includes proof point (ARR)"],
      "weaknesses": ["Could be more specific about ICP"],
      "recommendations": ["Add ICP specificity: 'for SMBs with 10-50 employees'"],
      "best_practice_refs": ["Sequoia: define company in single declarative sentence"]
    }
  ],
  "missing_slides": [
    {
      "expected_type": "why_now",
      "importance": "important",
      "recommendation": "Add a why-now slide with a genuine macro catalyst"
    }
  ],
  "overall_narrative_assessment": "Strong problem-solution flow but traction is buried too deep. Move traction slide before market sizing to hook investors by slide 4."
}
```

---

## checklist.json

**Producer:** `checklist.py` (Step 5, from agent-provided JSON input)

### Input format (stdin to checklist.py)

```json
{
  "items": [
    {
      "id": "purpose_clear",
      "status": "pass",
      "evidence": "Sequoia: define company in single declarative sentence",
      "notes": "Clear one-liner: 'Cloud accounting for SMBs that cuts bookkeeping time by 80%'"
    }
  ]
}
```

### Output format

| Field | Type | Description |
|-------|------|-------------|
| `items` | object[] | All 35 items enriched with category and label |
| `summary` | object | Aggregate scores and status |

### items[] entry (output)

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Criterion ID |
| `category` | string | Category name |
| `label` | string | Human-readable label |
| `status` | string | `"pass"`, `"fail"`, `"warn"`, or `"not_applicable"` |
| `evidence` | string \| null | Best-practice principle cited |
| `notes` | string \| null | Agent's assessment notes |

### summary

| Field | Type | Description |
|-------|------|-------------|
| `total` | integer | Always 35 |
| `pass` | integer | Count of passing items |
| `fail` | integer | Count of failing items |
| `warn` | integer | Count of warning items |
| `not_applicable` | integer | Count of N/A items |
| `score_pct` | float | pass / (total - not_applicable) * 100 |
| `overall_status` | string | `"strong"` (>=85%), `"solid"` (>=70%), `"needs_work"` (>=50%), `"major_revision"` (<50%) |
| `by_category` | object | Per-category counts (pass, fail, warn, not_applicable) |
| `failed_items` | object[] | List of failed items |
| `warned_items` | object[] | List of warned items |

### Canonical 35 checklist IDs

**Narrative Flow:** `purpose_clear`, `headlines_carry_story`, `narrative_arc_present`, `strongest_proof_early`, `story_stands_alone`

**Slide Content:** `problem_quantified`, `solution_shows_workflow`, `why_now_has_catalyst`, `market_bottom_up`, `competition_honest`, `business_model_clear`, `gtm_has_proof`, `team_has_depth`

**Stage Fit:** `stage_appropriate_structure`, `stage_appropriate_traction`, `stage_appropriate_financials`, `ask_ties_to_milestones`, `round_size_realistic`

**Design & Readability:** `one_idea_per_slide`, `minimal_text`, `slide_count_appropriate`, `consistent_design`, `mobile_readable`

**Common Mistakes:** `no_vague_purpose`, `no_nice_to_have_problem`, `no_hype_without_proof`, `no_features_over_outcomes`, `no_dodged_competition`

**AI Company:** `ai_retention_rebased`, `ai_cost_to_serve_shown`, `ai_defensibility_beyond_model`, `ai_responsible_controls`

**Diligence Readiness:** `numbers_consistent`, `data_room_ready`, `contact_info_present`
