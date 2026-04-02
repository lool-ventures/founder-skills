# Competitive Positioning Artifact Schemas

JSON schemas for all artifacts deposited during the competitive positioning workflow. Each artifact is a JSON file written to the `ANALYSIS_DIR` working directory.

## Schema Follow-Up Resolutions

These decisions were deferred from the design spec and are resolved here. Scripts and agent implementations must follow these exactly.

1. **Stress-tests live as top-level `differentiation_claims[]` in `positioning.json`** — claims span axes, so they are not nested under `views[]`.
2. **`suggested_axes` in `landscape_enriched.json` is informational only** — they inform the agent's axis selection but are NOT copied into `positioning.json`. Only the agent's canonical selection appears in `positioning.json`.
3. **`suggested_additions` entries carry a `merged: true/false` audit trail** — after the mini-gate, approved additions have `merged: true`; declined ones have `merged: false`. Both remain in `landscape_enriched.json` for audit. `validate_landscape.py` reads only the main `competitors[]` list (where merged additions have already been placed by the agent), never `suggested_additions`.
4. **Vanity axis calculation excludes `_startup`** — the ">80% within 20% range" check counts only competitor points (not `_startup`). A lone differentiated startup should not flip the vanity metric.
5. **Rank-based differentiation uses competitor-only ranking** — `_startup` is excluded from the ranking pool. The differentiation score measures where the startup would rank among competitors on each axis. If the startup would be ranked 1st among N competitors on both axes, differentiation is high.
6. **Adjacent category alone suppresses `MISSING_DO_NOTHING`** — having at least one competitor with `category: "adjacent"` or `category: "do_nothing"` is sufficient. The warning fires only when neither category is present.
7. **`research_depth` allowed values: `full`, `partial`, `founder_provided`** — `full` = enriched in Phase A+B of research. `partial` = added via `suggested_additions` mini-gate with only gap-detection evidence. `founder_provided` = no web research was performed (search tools unavailable or agent knowledge only). `SHALLOW_COMPETITOR_PROFILE` fires for `partial` competitors with <3 `sourced_fields_count`. `RESEARCH_DEPTH_LOW` fires when the global `research_depth` is `founder_provided` AND fewer than 4 competitors have `sourced_fields_count >= 3`.
8. **Agent must score every landscape slug for moats** — every competitor in `landscape.json` (by slug) must have an entry in `positioning.json`'s `moat_assessments`. `_startup` must also be scored. Individual moat dimensions may be `not_applicable` but require explicit `evidence` explaining why (e.g., "Network effects do not apply to single-player productivity tools").
9. **High-severity warning codes** (block under `--strict`): `MISSING_LANDSCAPE`, `MISSING_POSITIONING_SCORES`, `MISSING_MOAT_SCORES`, `MISSING_CHECKLIST`, `CORRUPT_ARTIFACT`, `STALE_ARTIFACT`. Medium-severity codes (reportable, can be accepted): `MISSING_DO_NOTHING`, `SHALLOW_COMPETITOR_PROFILE`, `VANITY_AXIS_WARNING`, `MOAT_WITHOUT_EVIDENCE`, `RESEARCH_DEPTH_LOW`. Low-severity: `FOUNDER_OVERRIDE_COUNT`. Info: `SEQUENTIAL_FALLBACK`.
10. **Provenance fields** — `positioning.json` points carry `x_evidence_source` and `y_evidence_source` (values: `"researched"`, `"agent_estimate"`, `"founder_override"`). Moat entries carry `evidence_source` with the same value set. `compose_report.py` counts `founder_override` occurrences and emits `FOUNDER_OVERRIDE_COUNT` as a low-severity metric.
11. **`input_mode` lives in `landscape.json` metadata** — `validate_landscape.py` passes through `input_mode` from `landscape_enriched.json`. Values: `"deck"`, `"conversation"`, `"document"`. `checklist.py` reads `input_mode` from `landscape.json` to apply mode-based gating.

---

## Metadata Convention

Every artifact includes a `metadata` object:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `run_id` | string | yes | ISO timestamp generated once at workflow start (e.g., `"20260319T143045Z"`). All artifacts in a single run share the same `run_id`. `compose_report.py` checks consistency and emits `STALE_ARTIFACT` on mismatch. |

---

## product_profile.json

**Producer:** Agent (main, Step 2)

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `company_name` | string | yes | Company name |
| `slug` | string | yes | Kebab-case company slug (used as `_startup` identity) |
| `product_description` | string | yes | 2-3 sentence product description |
| `target_customers` | string[] | yes | Primary customer segments (e.g., `["SMB fintech companies", "Mid-market banks"]`) |
| `value_propositions` | string[] | yes | Core value propositions delivered to customers |
| `differentiation_claims` | string[] | yes | What the founder/deck claims differentiates this product |
| `stage` | string | yes | `"pre_seed"`, `"seed"`, `"series_a"`, `"series_b"`, `"growth"` |
| `sector` | string | yes | Industry/vertical |
| `business_model` | string | yes | Revenue model (SaaS, marketplace, etc.) |
| `input_mode` | string | yes | `"deck"`, `"conversation"`, or `"document"` — how the analysis was initiated |
| `source_materials` | string[] | yes | What was provided (e.g., `["pitch deck (PDF)", "founder conversation"]`) |
| `metadata` | object | yes | `{run_id}` |

**Example:**
```json
{
  "company_name": "SecureFlow",
  "slug": "secureflow",
  "product_description": "API security platform that detects and blocks anomalous API traffic in real-time using behavioral analysis.",
  "target_customers": ["Mid-market SaaS companies", "Fintech API providers"],
  "value_propositions": [
    "Detects API abuse patterns 10x faster than rule-based WAFs",
    "Zero-config deployment via SDK — no infrastructure changes"
  ],
  "differentiation_claims": [
    "Behavioral ML model trained on 2B+ API calls",
    "Sub-5ms latency — competitors add 50-200ms",
    "Only solution with native GraphQL support"
  ],
  "stage": "seed",
  "sector": "Cybersecurity / API Security",
  "business_model": "SaaS",
  "input_mode": "conversation",
  "source_materials": ["founder conversation", "product demo"],
  "metadata": {"run_id": "20260319T143045Z"}
}
```

---

## landscape_draft.json

**Producer:** Agent (main, Step 3 — before Gate 1)

Contains the initial competitor identification and candidate axis pairs. Updated after Gate 1 corrections.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `competitors` | object[] | yes | 5-7 identified competitors |
| `candidate_axes` | object[] | yes | 2-3 candidate positioning axis pairs with reasoning |
| `deck_competitors_excluded` | object[] | no | Competitors from founder's deck intentionally excluded. Each: `{name, reason}`. Referenced by NARR_03 checklist. |
| `metadata` | object | yes | `{run_id}` |

### competitors[] entry

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | yes | Competitor name |
| `slug` | string | yes | Kebab-case unique identifier (immutable after assignment) |
| `category` | string | yes | `"direct"`, `"adjacent"`, `"do_nothing"`, `"emerging"`, or `"custom"` |
| `description` | string | yes | Brief description of the competitor |
| `key_differentiators` | string[] | yes | What makes this competitor distinct |
| `why_included` | string | yes | Why this competitor is relevant to the analysis |

### candidate_axes[] entry

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `x_axis` | string | yes | X-axis name |
| `y_axis` | string | yes | Y-axis name |
| `rationale` | string | yes | Why this axis pair reveals meaningful differentiation |

**Example:**
```json
{
  "competitors": [
    {
      "name": "Salt Security",
      "slug": "salt-security",
      "category": "direct",
      "description": "API security platform using AI/ML to detect and prevent API attacks",
      "key_differentiators": ["Large enterprise focus", "API discovery", "Series D funded ($270M+)"],
      "why_included": "Market leader in API security, direct competitor for the same buyer"
    },
    {
      "name": "Manual API monitoring",
      "slug": "manual-monitoring",
      "category": "do_nothing",
      "description": "Teams manually review API logs and set rate limits using existing infrastructure",
      "key_differentiators": ["Zero cost", "Full control", "No vendor dependency"],
      "why_included": "Status quo alternative — most mid-market companies still do this"
    }
  ],
  "candidate_axes": [
    {
      "x_axis": "Deployment Complexity",
      "y_axis": "Detection Accuracy",
      "rationale": "SecureFlow's zero-config SDK vs. competitors' infrastructure requirements is the primary differentiator. Pairing with detection accuracy tests whether ease of deployment comes at the cost of protection quality."
    },
    {
      "x_axis": "Latency Impact",
      "y_axis": "Protocol Coverage",
      "rationale": "SecureFlow claims sub-5ms latency and native GraphQL support — this axis pair directly tests both claims against the competitive set."
    }
  ],
  "metadata": {"run_id": "20260319T143045Z"}
}
```

---

## landscape_enriched.json

**Producer:** Research sub-agent (Step 4) or main agent in sequential mode

Contains enriched competitor profiles with sourced evidence. The main agent merges approved `suggested_additions` into `competitors[]` before writing the final version that `validate_landscape.py` reads.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `competitors` | object[] | yes | Enriched competitor profiles (includes any merged suggested additions) |
| `suggested_additions` | object[] | no | Competitors discovered during gap detection (audit trail) |
| `suggested_axes` | object[] | no | Additional axis pairs suggested by research findings (informational only) |
| `assessment_mode` | string | yes | `"sub-agent"` or `"sequential"` |
| `research_depth` | string | yes | Global research depth: `"full"`, `"partial"`, or `"founder_provided"` |
| `input_mode` | string | yes | Passed through from `product_profile.json`: `"deck"`, `"conversation"`, `"document"` |
| `metadata` | object | yes | `{run_id}` |

### competitors[] entry (enriched)

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | yes | Competitor name |
| `slug` | string | yes | Kebab-case identifier (matches `landscape_draft.json`) |
| `category` | string | yes | `"direct"`, `"adjacent"`, `"do_nothing"`, `"emerging"`, `"custom"` |
| `description` | string | yes | Enriched description with sourced details |
| `key_differentiators` | string[] | yes | Researched differentiators |
| `pricing_model` | string | no | Pricing approach (e.g., "Usage-based, starting at $499/mo") |
| `funding` | string | no | Funding history (e.g., "Series D, $270M total raised") |
| `team_size` | string | no | Approximate team size |
| `target_customers` | string[] | no | Customer segments served |
| `strengths` | string[] | no | Competitive strengths |
| `weaknesses` | string[] | no | Competitive weaknesses |
| `evidence_source` | object | yes | Per-field evidence provenance. Keys are field names, values are `"researched"`, `"agent_estimate"`, or `"founder_provided"`. |
| `research_depth` | string | yes | Per-competitor: `"full"`, `"partial"`, or `"founder_provided"` |
| `sourced_fields_count` | integer | yes | Number of fields with `evidence_source: "researched"` |

### suggested_additions[] entry

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | yes | Competitor name |
| `slug` | string | yes | Proposed slug |
| `category` | string | yes | Proposed category |
| `rationale` | string | yes | Why this competitor was identified during gap detection |
| `partial_profile` | object | no | Whatever evidence was gathered during detection |
| `merged` | boolean | yes | `true` if founder approved and competitor was merged into `competitors[]`; `false` if declined. Set by the main agent after the mini-gate. |

### suggested_axes[] entry

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `x_axis` | string | yes | Suggested X-axis name |
| `y_axis` | string | yes | Suggested Y-axis name |
| `rationale` | string | yes | Why research findings suggest this axis pair |

**Example:**
```json
{
  "competitors": [
    {
      "name": "Salt Security",
      "slug": "salt-security",
      "category": "direct",
      "description": "Leading API security platform...",
      "key_differentiators": ["API discovery engine", "Enterprise-grade posture governance"],
      "pricing_model": "Enterprise contracts, $50K+ ACV",
      "funding": "Series D, $270M total raised (Feb 2023)",
      "team_size": "~300 employees",
      "target_customers": ["Enterprise", "Financial services"],
      "strengths": ["Market awareness", "Enterprise sales motion", "API discovery feature"],
      "weaknesses": ["Heavy deployment", "High latency overhead (100-200ms)", "No GraphQL support"],
      "evidence_source": {
        "description": "researched",
        "pricing_model": "researched",
        "funding": "researched",
        "team_size": "agent_estimate",
        "strengths": "researched",
        "weaknesses": "researched"
      },
      "research_depth": "full",
      "sourced_fields_count": 5
    }
  ],
  "suggested_additions": [
    {
      "name": "Wallarm",
      "slug": "wallarm",
      "category": "direct",
      "rationale": "Multiple G2 reviews mention Wallarm as a Salt Security alternative in API security",
      "partial_profile": {
        "description": "API security and WAAP platform",
        "funding": "Series A, $10M"
      },
      "merged": true
    }
  ],
  "suggested_axes": [
    {
      "x_axis": "API Discovery Depth",
      "y_axis": "Real-time vs. Batch Analysis",
      "rationale": "Research reveals API discovery is a key differentiator across the competitive set — some competitors discover APIs passively while others require manual cataloging"
    }
  ],
  "assessment_mode": "sub-agent",
  "research_depth": "full",
  "input_mode": "conversation",
  "metadata": {"run_id": "20260319T143045Z"}
}
```

---

## positioning.json

**Producer:** Agent (main, Step 5 — after Gate 2 corrections applied)

Contains the canonical positioning views, moat assessments, differentiation stress-tests, and accepted warnings. This is the last agent-produced artifact before scripts run.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `views` | object[] | yes | 1-2 canonical positioning views (primary + optional secondary) |
| `moat_assessments` | object | yes | Keyed by company slug (including `_startup`). Every slug in `landscape.json` must have an entry. |
| `differentiation_claims` | object[] | yes | Stress-test results for each differentiation claim (top-level, spans axes) |
| `accepted_warnings` | object[] | no | Warnings the agent acknowledges. Only medium-severity codes can be accepted. |
| `metadata` | object | yes | `{run_id}` |

> **⚠ Common mistake — `moat_assessments`:** This MUST be a **dict keyed by company slug**, NOT an array of objects. `score_moats.py` has a compatibility shim that normalizes arrays, but canonical artifacts must use the dict format. Scoring scripts have compatibility shims, but always use canonical format — other consumers may not normalize.
> ```json
> "moat_assessments": {
>   "_startup": {"moats": [...]},
>   "competitor-slug": {"moats": [...]}
> }
> ```

### views[] entry

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | string | yes | `"primary"` or `"secondary"` |
| `x_axis` | object | yes | `{name, description, rationale}` — rationale explains why this axis differentiates |
| `y_axis` | object | yes | `{name, description, rationale}` |
| `points` | object[] | yes | Per-competitor + `_startup` coordinate assignments |

> **⚠ Common mistake — `x_axis` / `y_axis`:** These MUST be **objects**, not bare strings. `score_positioning.py` has a compatibility shim that wraps strings, but canonical artifacts must use the object format. Scoring scripts have compatibility shims, but always use canonical format — other consumers may not normalize.
> ```json
> "x_axis": {"name": "Axis Name", "description": "What this measures", "rationale": "Why this differentiates"}
> ```

### points[] entry

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `competitor` | string | yes | Competitor slug or `"_startup"` |
| `x` | number | yes | 0-100 ordinal position on X-axis (relative to this competitive set) |
| `y` | number | yes | 0-100 ordinal position on Y-axis |
| `x_evidence` | string | yes | Evidence supporting the X coordinate |
| `y_evidence` | string | yes | Evidence supporting the Y coordinate |
| `x_evidence_source` | string | yes | `"researched"`, `"agent_estimate"`, or `"founder_override"` |
| `y_evidence_source` | string | yes | `"researched"`, `"agent_estimate"`, or `"founder_override"` |

> **⚠ Common mistake — `competitor`:** The field name is `competitor`, NOT `slug`. `score_positioning.py` has a compatibility shim that renames `slug`, but canonical artifacts must use `competitor`. Always use canonical format — other consumers may not normalize.

**Coordinate nature:** The 0-100 values are ordinal rankings within this specific competitive set, not cardinal measurements. "85" means "near the top of this group on this axis," not a universally calibrated score. Different runs with different competitor sets will produce different coordinates.

### moat_assessments.{slug}

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `moats` | object[] | yes | One entry per moat dimension assessed |

### moats[] entry

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | string | yes | Canonical: `network_effects`, `data_advantages`, `switching_costs`, `regulatory_barriers`, `cost_structure`, `brand_reputation`. Custom: `custom_{slug}` pattern. |
| `status` | string | yes | `"strong"`, `"moderate"`, `"weak"`, `"absent"`, or `"not_applicable"` |
| `evidence` | string | yes | Evidence supporting the rating. Required even for `not_applicable` (must explain why). |
| `evidence_source` | string | yes | `"researched"`, `"agent_estimate"`, or `"founder_override"` |
| `trajectory` | string | yes | `"building"`, `"stable"`, or `"eroding"` |

### differentiation_claims[] entry

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `claim` | string | yes | The differentiation claim being tested |
| `verifiable` | boolean | yes | Can this claim be independently verified? |
| `evidence` | string | yes | Evidence supporting or challenging the claim |
| `challenge` | string | yes | What an investor would push on |
| `verdict` | string | yes | `"holds"`, `"partially_holds"`, or `"does_not_hold"` |

### accepted_warnings[] entry

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `code` | string | yes | Warning code (medium-severity only: `MISSING_DO_NOTHING`, `SHALLOW_COMPETITOR_PROFILE`, `VANITY_AXIS_WARNING`, `MOAT_WITHOUT_EVIDENCE`, `RESEARCH_DEPTH_LOW`) |
| `match` | string | yes | Case-insensitive substring to match against warning message |
| `reason` | string | yes | Why this warning is expected/acceptable |

**Example:**
```json
{
  "views": [
    {
      "id": "primary",
      "x_axis": {
        "name": "Deployment Complexity",
        "description": "How much infrastructure change is required to deploy the solution",
        "rationale": "SecureFlow's zero-config SDK is the primary differentiator — this axis directly tests that claim"
      },
      "y_axis": {
        "name": "Detection Accuracy",
        "description": "Ability to detect real API threats with low false positive rate",
        "rationale": "Accuracy is the table-stakes dimension — without it, ease of deployment is irrelevant"
      },
      "points": [
        {
          "competitor": "_startup",
          "x": 90, "y": 75,
          "x_evidence": "SDK-based deployment, zero infrastructure changes required, 5-minute integration",
          "y_evidence": "ML model trained on 2B+ API calls, customer-reported 95% detection rate",
          "x_evidence_source": "founder_override",
          "y_evidence_source": "researched"
        },
        {
          "competitor": "salt-security",
          "x": 30, "y": 85,
          "x_evidence": "Requires reverse proxy deployment, typical integration takes 2-4 weeks",
          "y_evidence": "Industry-leading detection, validated by enterprise customers in production",
          "x_evidence_source": "researched",
          "y_evidence_source": "researched"
        },
        {
          "competitor": "manual-monitoring",
          "x": 95, "y": 15,
          "x_evidence": "No deployment — uses existing infrastructure (logs, rate limits)",
          "y_evidence": "Manual review catches <10% of sophisticated API attacks",
          "x_evidence_source": "agent_estimate",
          "y_evidence_source": "agent_estimate"
        }
      ]
    }
  ],
  "moat_assessments": {
    "_startup": {
      "moats": [
        {
          "id": "network_effects",
          "status": "not_applicable",
          "evidence": "Single-tenant API security product — no multi-sided network dynamics",
          "evidence_source": "agent_estimate",
          "trajectory": "stable"
        },
        {
          "id": "data_advantages",
          "status": "moderate",
          "evidence": "ML model trained on 2B+ API calls from beta customers. Data flywheel: more customers -> better models -> better detection. Currently small scale but growing.",
          "evidence_source": "researched",
          "trajectory": "building"
        }
      ]
    },
    "salt-security": {
      "moats": [
        {
          "id": "network_effects",
          "status": "not_applicable",
          "evidence": "Enterprise security product, no network dynamics",
          "evidence_source": "agent_estimate",
          "trajectory": "stable"
        },
        {
          "id": "data_advantages",
          "status": "strong",
          "evidence": "Processes 10B+ API calls monthly across 200+ enterprise customers. Largest training dataset in the category.",
          "evidence_source": "researched",
          "trajectory": "stable"
        }
      ]
    }
  },
  "differentiation_claims": [
    {
      "claim": "Behavioral ML model trained on 2B+ API calls",
      "verifiable": true,
      "evidence": "Founder confirmed 2B figure from beta program; however, Salt Security processes 10B+ monthly — the gap is significant",
      "challenge": "How does the model perform at this training scale vs. competitors with 5x the data? What's the accuracy delta?",
      "verdict": "partially_holds"
    },
    {
      "claim": "Sub-5ms latency vs. competitors' 50-200ms",
      "verifiable": true,
      "evidence": "SDK-based approach avoids network hop, so sub-5ms is architecturally plausible. No independent benchmark found.",
      "challenge": "This is an architectural advantage, not a measured comparison. Can you share latency benchmarks from production deployments?",
      "verdict": "holds"
    }
  ],
  "accepted_warnings": [
    {
      "code": "MOAT_WITHOUT_EVIDENCE",
      "match": "manual-monitoring",
      "reason": "Do-nothing alternative inherently has thin evidence — it is the absence of a product"
    }
  ],
  "metadata": {"run_id": "20260319T143045Z"}
}
```

---

## landscape.json

**Producer:** `validate_landscape.py` (Step 6a)

Validated, normalized competitor list. This is an **exported artifact** consumed by downstream skills (deck-review, fundraise-readiness). Does NOT contain `_startup` — only competitors.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `competitors` | object[] | yes | Validated competitor entries |
| `input_mode` | string | yes | `"deck"`, `"conversation"`, or `"document"` |
| `warnings` | object[] | yes | Validation warnings (may be empty) |
| `metadata` | object | yes | `{run_id}` |

### competitors[] entry

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | yes | Competitor name |
| `slug` | string | yes | Unique kebab-case identifier |
| `category` | string | yes | `"direct"`, `"adjacent"`, `"do_nothing"`, `"emerging"`, `"custom"` |
| `description` | string | yes | Competitor description |
| `key_differentiators` | string[] | yes | Differentiators |
| `research_depth` | string | yes | `"full"`, `"partial"`, or `"founder_provided"` (preserved from enriched) |
| `evidence_source` | object | yes | Per-field provenance (preserved from enriched) |
| `sourced_fields_count` | integer | yes | Count of researched fields (preserved from enriched) |

### warnings[] entry

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `code` | string | yes | Warning code (e.g., `MISSING_DO_NOTHING`) |
| `severity` | string | yes | `"high"`, `"medium"`, `"low"`, or `"info"` |
| `message` | string | yes | Human-readable warning message |

**Example:**
```json
{
  "competitors": [
    {
      "name": "Salt Security",
      "slug": "salt-security",
      "category": "direct",
      "description": "Leading API security platform...",
      "key_differentiators": ["API discovery engine", "Enterprise-grade posture governance"],
      "research_depth": "full",
      "evidence_source": {"description": "researched", "pricing_model": "researched"},
      "sourced_fields_count": 5
    },
    {
      "name": "Manual API monitoring",
      "slug": "manual-monitoring",
      "category": "do_nothing",
      "description": "Teams manually review API logs...",
      "key_differentiators": ["Zero cost", "Full control"],
      "research_depth": "full",
      "evidence_source": {"description": "agent_estimate"},
      "sourced_fields_count": 0
    }
  ],
  "input_mode": "conversation",
  "warnings": [],
  "metadata": {"run_id": "20260319T143045Z"}
}
```

---

## moat_scores.json

**Producer:** `score_moats.py` (Step 6b)

Per-company moat scores with aggregates and cross-company comparison.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `companies` | object | yes | Keyed by company slug (including `_startup`). Each contains scored moats and aggregates. |
| `comparison` | object | yes | Cross-company comparison by moat dimension |
| `warnings` | object[] | yes | Quality warnings (may be empty) |
| `metadata` | object | yes | `{run_id}` |

### companies.{slug}

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `moats` | object[] | yes | Scored moat entries (passed through from input with validation) |
| `moat_count` | integer | yes | Count of moats with status != `absent` and != `not_applicable` |
| `strongest_moat` | string \| null | yes | ID of the highest-rated moat, or `null` if all are absent/na |
| `overall_defensibility` | string | yes | `"high"` (2+ strong), `"moderate"` (1 strong or 2+ moderate), `"low"` (all weak/absent/na) |

### comparison

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `by_dimension` | object | yes | Keyed by moat ID. Each value is an object mapping slug to status, showing how `_startup` compares. |
| `startup_rank` | object | yes | Keyed by moat ID. Each value is `{rank, total}` showing where `_startup` falls (1 = strongest). |

### warnings[] entry

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `code` | string | yes | Warning code (e.g., `MOAT_WITHOUT_EVIDENCE`) |
| `severity` | string | yes | `"medium"` |
| `message` | string | yes | Human-readable message |
| `company` | string | no | Slug of the affected company (if applicable) |
| `moat_id` | string | no | ID of the affected moat (if applicable) |

**Example:**
```json
{
  "companies": {
    "_startup": {
      "moats": [
        {"id": "data_advantages", "status": "moderate", "evidence": "...", "evidence_source": "researched", "trajectory": "building"},
        {"id": "switching_costs", "status": "moderate", "evidence": "...", "evidence_source": "agent_estimate", "trajectory": "building"}
      ],
      "moat_count": 2,
      "strongest_moat": "data_advantages",
      "overall_defensibility": "moderate"
    },
    "salt-security": {
      "moats": [
        {"id": "data_advantages", "status": "strong", "evidence": "...", "evidence_source": "researched", "trajectory": "stable"},
        {"id": "switching_costs", "status": "strong", "evidence": "...", "evidence_source": "researched", "trajectory": "stable"}
      ],
      "moat_count": 2,
      "strongest_moat": "data_advantages",
      "overall_defensibility": "high"
    }
  },
  "comparison": {
    "by_dimension": {
      "data_advantages": {"_startup": "moderate", "salt-security": "strong", "manual-monitoring": "absent"},
      "switching_costs": {"_startup": "moderate", "salt-security": "strong", "manual-monitoring": "weak"}
    },
    "startup_rank": {
      "data_advantages": {"rank": 2, "total": 2},
      "switching_costs": {"rank": 2, "total": 2}
    }
  },
  "warnings": [],
  "metadata": {"run_id": "20260319T143045Z"}
}
```

---

## positioning_scores.json

**Producer:** `score_positioning.py` (Step 6c)

Per-view positioning quality scores with vanity flags and rank-based differentiation.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `views` | object[] | yes | Per-view scoring results |
| `overall_differentiation` | number | yes | 0-100 aggregate differentiation score across all views |
| `differentiation_claims` | object[] | yes | Passed through from `positioning.json` |
| `warnings` | object[] | yes | Quality warnings (may be empty) |
| `metadata` | object | yes | `{run_id}` |

### views[] entry

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `view_id` | string | yes | `"primary"` or `"secondary"` |
| `x_axis_name` | string | yes | Axis name (for display) |
| `y_axis_name` | string | yes | Axis name (for display) |
| `x_axis_rationale` | string | yes | Passed through from `positioning.json` |
| `y_axis_rationale` | string | yes | Passed through from `positioning.json` |
| `x_axis_vanity_flag` | boolean | yes | `true` if >80% of competitors (excluding `_startup`) cluster within 20% of the X-axis range |
| `y_axis_vanity_flag` | boolean | yes | `true` if >80% of competitors cluster within 20% of Y-axis range |
| `differentiation_score` | number | yes | 0-100, rank-based. Computed from `_startup`'s rank among competitors (excluding `_startup` from ranking pool) on each axis. |
| `startup_x_rank` | integer | yes | Where `_startup` would rank among competitors on X (1 = top) |
| `startup_y_rank` | integer | yes | Where `_startup` would rank among competitors on Y (1 = top) |
| `competitor_count` | integer | yes | Number of competitors in this view (excluding `_startup`) |

**Differentiation score formula:** Distance-weighted: rank contributes 50%, gap contributes 50%. For each axis: `rank_score = (N - rank + 1) / N * 50`. Gap measures how far ahead the startup is from the next-best competitor: `gap = max(0, (startup_val - next_best_val) / 100) * 50`. Per-axis score = `rank_score + gap_score`. The view's `differentiation_score` is the average of x and y axis scores, capped at 100. `overall_differentiation` is the average across all views. This distinguishes "barely ahead" (rank 1, gap 2%) from "dramatically ahead" (rank 1, gap 40%).

**Example:**
```json
{
  "views": [
    {
      "view_id": "primary",
      "x_axis_name": "Deployment Complexity",
      "y_axis_name": "Detection Accuracy",
      "x_axis_rationale": "SecureFlow's zero-config SDK is the primary differentiator...",
      "y_axis_rationale": "Accuracy is the table-stakes dimension...",
      "x_axis_vanity_flag": false,
      "y_axis_vanity_flag": false,
      "differentiation_score": 75.0,
      "startup_x_rank": 1,
      "startup_y_rank": 3,
      "competitor_count": 5
    }
  ],
  "overall_differentiation": 75.0,
  "differentiation_claims": [
    {
      "claim": "Sub-5ms latency vs. competitors' 50-200ms",
      "verifiable": true,
      "evidence": "...",
      "challenge": "...",
      "verdict": "holds"
    }
  ],
  "warnings": [],
  "metadata": {"run_id": "20260319T143045Z"}
}
```

---

## checklist.json

**Producer:** `checklist.py` (Step 6d)

Quality criteria evaluation for the competitive analysis.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `items` | object[] | yes | All checklist items with assessments |
| `score_pct` | number | yes | `(pass_count + 0.5 * warn_count) / (total - not_applicable) * 100` |
| `pass_count` | integer | yes | Items with status `pass` |
| `warn_count` | integer | yes | Items with status `warn` |
| `fail_count` | integer | yes | Items with status `fail` |
| `na_count` | integer | yes | Items with status `not_applicable` |
| `total` | integer | yes | Total items (including `not_applicable`) |
| `input_mode` | string | yes | Mode used for gating |
| `metadata` | object | yes | `{run_id}` |

### items[] entry

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | string | yes | Item ID (e.g., `COVER_01`) |
| `category` | string | yes | Category code (e.g., `COVER`) |
| `label` | string | yes | Human-readable label |
| `status` | string | yes | `"pass"`, `"fail"`, `"warn"`, or `"not_applicable"` |
| `evidence` | string | yes | Evidence supporting the assessment |
| `notes` | string | no | Additional notes |

**Scoring:**
- `pass` = 1 point
- `warn` = 0.5 points
- `fail` = 0 points
- `not_applicable` = excluded from denominator

**Example:**
```json
{
  "items": [
    {
      "id": "COVER_01",
      "category": "COVER",
      "label": "Minimum 5 competitors identified",
      "status": "pass",
      "evidence": "6 competitors identified across 3 categories"
    },
    {
      "id": "COVER_04",
      "category": "COVER",
      "label": "Do-nothing / status quo included",
      "status": "pass",
      "evidence": "Manual API monitoring included as do_nothing alternative"
    }
  ],
  "score_pct": 82.6,
  "pass_count": 16,
  "warn_count": 5,
  "fail_count": 2,
  "na_count": 2,
  "total": 25,
  "input_mode": "conversation",
  "metadata": {"run_id": "20260319T143045Z"}
}
```

---

## report.json

**Producer:** `compose_report.py` (Step 6e)

Final assembled report with cross-artifact validation.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `report_markdown` | string | yes | Complete markdown report ready for delivery |
| `metadata` | object | yes | See below |
| `warnings` | object[] | yes | All warnings from cross-artifact validation |
| `artifacts_loaded` | string[] | yes | List of artifact filenames successfully loaded |
| `scoring_summary` | object | yes | Summary scores for quick reference |

### metadata

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `run_id` | string | yes | From input artifacts |
| `company_name` | string | yes | From product profile |
| `analysis_date` | string | yes | ISO date |
| `input_mode` | string | yes | `"deck"`, `"conversation"`, or `"document"` |
| `competitor_count` | integer | yes | Number of competitors in landscape |
| `research_depth` | string | yes | Global research depth |
| `assessment_mode` | string | yes | `"sub-agent"` or `"sequential"` |
| `founder_override_count` | integer | yes | Number of `founder_override` evidence sources across all positioning data |

### scoring_summary

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `checklist_score_pct` | number | yes | From `checklist.json` |
| `overall_differentiation` | number | yes | From `positioning_scores.json` |
| `startup_defensibility` | string | yes | From `moat_scores.json` (`_startup`'s `overall_defensibility`) |

### warnings[] entry

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `code` | string | yes | Warning code |
| `severity` | string | yes | `"high"`, `"medium"`, `"low"`, or `"info"` |
| `message` | string | yes | Human-readable message |
| `acknowledged` | boolean | no | `true` if downgraded via `accepted_warnings` (medium-severity only) |
| `acknowledge_reason` | string | no | Reason from `accepted_warnings` (when acknowledged) |

### report_markdown sections

The `report_markdown` field contains these sections in order:

1. `# Competitive Positioning Analysis: {company_name}`
2. `## Executive Summary` — overall positioning, key strengths, primary concerns
3. `## Competitor Landscape` — competitor profiles with categories and evidence quality
4. `## Positioning Analysis` — axis rationale, coordinate map description, differentiation scores
5. `## Moat Assessment` — per-dimension ratings for startup vs. key competitors, trajectory
6. `## Differentiation Stress-Test` — claim-by-claim results with investor challenges
7. `## Key Findings` — prioritized findings from scoring data (script-generated)
8. `## Warnings` — any quality warnings with severity and context
9. `---` (separator — agent inserts `## Coaching Commentary` before this)
10. Footer

**Example:**
```json
{
  "report_markdown": "# Competitive Positioning Analysis: SecureFlow\n\n## Executive Summary\n...",
  "metadata": {
    "run_id": "20260319T143045Z",
    "company_name": "SecureFlow",
    "analysis_date": "2026-03-19",
    "input_mode": "conversation",
    "competitor_count": 6,
    "research_depth": "full",
    "assessment_mode": "sub-agent",
    "founder_override_count": 2
  },
  "warnings": [
    {
      "code": "MOAT_WITHOUT_EVIDENCE",
      "severity": "medium",
      "message": "manual-monitoring: brand_reputation rated 'strong' with insufficient evidence (12 chars)",
      "acknowledged": true,
      "acknowledge_reason": "Do-nothing alternative inherently has thin evidence"
    }
  ],
  "artifacts_loaded": [
    "product_profile.json", "landscape.json", "positioning.json",
    "moat_scores.json", "positioning_scores.json", "checklist.json"
  ],
  "scoring_summary": {
    "checklist_score_pct": 82.6,
    "overall_differentiation": 75.0,
    "startup_defensibility": "moderate"
  }
}
```

---

## Stub Artifacts

If a step is not applicable, deposit a stub:
```json
{"skipped": true, "reason": "No prior deck-review or market-sizing artifacts found"}
```

Stubs are recognized by `compose_report.py` and bypass related validation checks.

---

## `_startup` Convention

`_startup` is a reserved slug for the founder's company. It appears in:
- `positioning.json` — in `views[].points[]` and `moat_assessments`
- `moat_scores.json` — in `companies` and `comparison`
- `positioning_scores.json` — referenced for rank calculation

It does NOT appear in:
- `landscape.json` — which contains only competitors
- `landscape_draft.json` — which contains only competitors
- `landscape_enriched.json` — which contains only competitors

All downstream scripts and cross-artifact validation exempt `_startup` from competitor-matching checks. It is not an orphan. Specifically:
- `validate_landscape.py` — ignores `_startup` (it is not in the competitor list)
- `score_positioning.py` — includes `_startup` for differentiation calculations but excludes from ranking pool and vanity checks
- `score_moats.py` — scores `_startup` alongside competitors
- `compose_report.py` — skips `_startup` in "landscape competitors match scoring competitors" cross-check
- `visualize.py` — renders `_startup` with distinct styling (highlighted, labeled as the startup)

---

## Warning Severity Reference

| Code | Severity | Trigger | `--strict` |
|------|----------|---------|------------|
| `MISSING_LANDSCAPE` | high | `landscape.json` not found | exit 1 |
| `MISSING_POSITIONING_SCORES` | high | `positioning_scores.json` not found | exit 1 |
| `MISSING_MOAT_SCORES` | high | `moat_scores.json` not found | exit 1 |
| `MISSING_CHECKLIST` | high | `checklist.json` not found | exit 1 |
| `CORRUPT_ARTIFACT` | high | Artifact exists but fails JSON parse or required field missing | exit 1 |
| `STALE_ARTIFACT` | high | `run_id` mismatch across artifacts | exit 1 |
| `MISSING_DO_NOTHING` | medium | No `do_nothing` or `adjacent` competitor in landscape | can be accepted |
| `SHALLOW_COMPETITOR_PROFILE` | medium | Competitor with `research_depth: "partial"` and `sourced_fields_count < 3` | can be accepted |
| `VANITY_AXIS_WARNING` | medium | Axis flagged as vanity by `score_positioning.py` | can be accepted |
| `MOAT_WITHOUT_EVIDENCE` | medium | Moat rated `strong` with evidence <20 chars | can be accepted |
| `RESEARCH_DEPTH_LOW` | medium | Global `research_depth: "founder_provided"` with <4 competitors having `sourced_fields_count >= 3` | can be accepted |
| `FOUNDER_OVERRIDE_COUNT` | low | N positioning coordinates or moat ratings have `evidence_source: "founder_override"` | report only |
| `SEQUENTIAL_FALLBACK` | info | `assessment_mode: "sequential"` in `landscape_enriched.json` | report only |
