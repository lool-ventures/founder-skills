# Competitive Positioning Artifact Schemas

JSON schemas for all artifacts deposited during the competitive positioning workflow. Each artifact is a JSON file written to the `ANALYSIS_DIR` working directory.

## Schema Follow-Up Resolutions

These decisions were deferred from the design spec and are resolved here. Scripts and agent implementations must follow these exactly.

1. **Stress-tests live as top-level `differentiation_claims[]` in `positioning.json`** — claims span axes, so they are not nested under `views[]`.
2. **`suggested_axes` in the LANDSCAPE_RESEARCH return payload is informational only** — they inform the agent's axis selection but are NOT copied into `positioning.json`. Only the agent's canonical selection appears in `positioning.json`.
3. **`suggested_additions` entries carry a `merged: true/false` flag, but `merged: true` never persists on an entry.** The sub-agent always writes `merged: false` at hand-off time (promotion hasn't happened yet). After the mini-gate, the main thread — not the sub-agent — relocates each APPROVED entry into `competitors[]` and removes it from `suggested_additions[]` entirely; an approved entry is never left behind stamped `merged: true`. A DECLINED entry is left in place with its already-`false` value untouched. `validate_landscape.py` reads only the main `competitors[]` list (where approved additions have already been placed by the main thread), never `suggested_additions`.
4. **Vanity axis calculation excludes `_startup`** — the ">80% within 20% range" check counts only competitor points (not `_startup`). A lone differentiated startup should not flip the vanity metric.
5. **Rank-based differentiation uses competitor-only ranking** — `_startup` is excluded from the ranking pool. The differentiation score measures where the startup would rank among competitors on each axis. If the startup would be ranked 1st among N competitors on both axes, differentiation is high.
6. **Adjacent category alone suppresses `MISSING_DO_NOTHING`** — having at least one competitor with `category: "adjacent"` or `category: "do_nothing"` is sufficient. The warning fires only when neither category is present.
7. **`research_depth` allowed values: `full`, `partial`, `founder_provided`** — `full` = enriched in Phase A+B of research. `partial` = added via `suggested_additions` mini-gate with only gap-detection evidence. `founder_provided` = no web research was performed (search tools unavailable or agent knowledge only). `SHALLOW_COMPETITOR_PROFILE` fires for `partial` competitors with <3 `sourced_fields_count`. `RESEARCH_DEPTH_LOW` fires when the global `research_depth` is `founder_provided` AND fewer than 4 competitors have `sourced_fields_count >= 3`.
8. **Agent must score every landscape slug for moats — in `moat_scores.json`.** Every competitor in `landscape.json` (by slug), plus `_startup`, must have an entry in `moat_scores.json`'s `companies` (post-MOAT_SCORING, authoritative). Individual moat dimensions may be `not_applicable` but require explicit `evidence` explaining why (e.g., "Network effects do not apply to single-player productivity tools"). This every-slug requirement does NOT apply to `positioning.json`'s pre-dispatch `moat_assessments` block, which is optional — see that field's entry below.
9. **Warning codes by severity** — see the full Warning Severity Reference table near the end of this document for the authoritative list and triggers. High-severity (block under `--strict`): `MISSING_LANDSCAPE`, `MISSING_POSITIONING`, `MISSING_POSITIONING_SCORES`, `MISSING_MOAT_SCORES`, `MISSING_CHECKLIST`, `CORRUPT_ARTIFACT`, `STALE_ARTIFACT`, `UNVALIDATED_ARTIFACT`, `CHECKLIST_STALE_VS_POSITIONING`. Medium-severity (reportable, any can be accepted): `MISSING_DO_NOTHING`, `SHALLOW_COMPETITOR_PROFILE`, `VANITY_AXIS_WARNING`, `MOAT_WITHOUT_EVIDENCE`, `RESEARCH_DEPTH_LOW`, `MISSING_CANONICAL_MOAT`, `INCOMPLETE_SCORING`, `RESEARCHED_WITHOUT_SOURCE`, `NO_RECENT_DEVELOPMENTS`, `STALE_DEVELOPMENT`, `RATIONALE_MISSING`. Low-severity: `FOUNDER_OVERRIDE_COUNT`, `MARKER_COLLISION`. Info: `SEQUENTIAL_FALLBACK`, `CHECKLIST_ALL_PASS`.
10. **Provenance fields** — `positioning.json` points carry `x_evidence_source` and `y_evidence_source` (values: `"researched"`, `"agent_estimate"`, `"founder_override"`). Moat entries carry `evidence_source` with the same value set. `compose_report.py` counts `founder_override` occurrences and emits `FOUNDER_OVERRIDE_COUNT` as a low-severity metric. A `"researched"` value should carry a citation beside it — `source` on moat entries, a per-field `sources` dict on competitors — so the main thread can spot-check it; `score_moats.py` / `validate_landscape.py` warn (`RESEARCHED_WITHOUT_SOURCE`, medium, acceptable) rather than fail when it's missing, since a source may legitimately be a search query, not a URL.
11. **`input_mode` lives in `landscape.json`** — `validate_landscape.py` passes through `input_mode` from the LANDSCAPE_RESEARCH return payload into `landscape.json`. Values: `"deck"`, `"conversation"`, `"document"`. `checklist.py` applies mode-based gating from the `--input-mode` flag the main thread stamps (established in Steps 1-2), not from `landscape.json`.
12. **`scoring_basis` is optional and per-artifact — absence is never rendered as `"shipped"`.** `positioning.json` and `positioning_scores.json` may carry a top-level `scoring_basis` (`"shipped"` | `"roadmap_12mo"` | `"mixed"` — see `competitive-analysis-methodology.md` §7 for the convention). When the field is absent, the basis was not declared; treat it as "not declared" for display purposes, never as an implicit default. An artifact predating this field has a genuinely undefined basis, not an unstated `"shipped"` one.

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
| `deck_axes` | object[] | no | Deck-mode only: positioning axes the deck's competition slide used, captured for potential reuse as a secondary positioning view. Each entry: `{x_axis, y_axis, source_slide}`. Informational — no script reads it. See also `deck_competition_slide` below for the fuller capture of the same slide. |
| `deck_competition_slide` | object | no | Deck-mode only: a fuller, generalized capture of the deck's competition slide than `deck_axes`, so the CHECKLIST dispatch can assess `NARR_03` (competition-slide alignment) against something concrete. Two canonical shapes: **populated** — `{present: true, axes: {x, y}, plotted: [{name, category}], claimed_position, source_slide}`; **absent** — `{present: false, reason: "..."}`, the canonical form when the deck names no competitor at all (measured: a real deck ran 12 pages naming none, `NARR_03` had nothing to grade, and the run invented an unschema'd `deck_competition_slide_note` field instead — that field is retired by name; do not reintroduce it). Script-inert like `deck_axes` — read only by the CHECKLIST sub-agent dispatch (see `agents/competitive-positioning.md`). |
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

## competitor_verification.json

**Producer:** `verify_competitors.py`, fed by TWO parallel Context A hand-offs — COMPETITOR_VERIFICATION (Step 3.5, precision) and COMPETITOR_RECALL (Step 3.6, recall). An independent (fresh-context) precision check that runs BEFORE Gate 1: the sub-agent re-characterizes each competitor from its own research and judges genuine overlap against the startup on a substitution test. The producer is a **validator, not a detector** — it validates structure, enforces the show-your-work gate, cross-checks landscape slug coverage, and computes the summary; it never authors a verdict.

**Sub-agent input shape** (what the agent writes to OUTPUT_PATH):

```json
{
  "startup_characterization": {
    "buyer": "SMB field-service operators (5-50 techs)",
    "job_to_be_done": "schedule + dispatch technicians to job sites",
    "category": "field service management software",
    "monetization": "per-seat SaaS",
    "evidence_source": "founder_provided"
  },
  "verdicts": [
    {
      "slug": "calendly",
      "verdict": "not_a_competitor",
      "independent_characterization": {
        "buyer": "individual knowledge workers / sales teams",
        "job_to_be_done": "let external parties self-book a meeting",
        "category": "meeting scheduling link tool",
        "monetization": "per-seat SaaS, freemium",
        "evidence_source": "researched"
      },
      "overlap": {"buyer": false, "job_to_be_done": false, "category": false},
      "reasoning": "Shares the word 'scheduling' but schedules meetings for knowledge workers; does not dispatch field techs. No shared consideration set.",
      "confidence": "high",
      "recommended_action": "challenge_removal"
    }
  ],
  "metadata": {"run_id": "..."}
}
```

**Field rules (enforced by the producer):**
- `verdict` ∈ `genuine` | `adjacent` | `not_a_competitor`.
- `recommended_action` ∈ `keep` | `reclassify_adjacent` | `reclassify_direct` | `challenge_removal`.
- `evidence_source` ∈ `researched` | `agent_estimate` | `founder_provided`.
- **Show-your-work gate:** any verdict that is NOT `genuine` MUST carry a non-empty `reasoning` AND a populated `independent_characterization` with non-empty `buyer` and `job_to_be_done`. A flag with no independent characterization is the "stayed high-level" failure — rejected (exit 1).
- One verdict per competitor slug in `landscape_draft.json`; `--landscape` flags missing or extra slugs.

**Producer output** adds a computed `summary` (`total`, `genuine`, `adjacent`, `not_a_competitor`, `flagged`, `flagged_slugs[]`, `show_your_work_violations[]`, `category_disagreements[]`), a `validation` block (`status` ok|error, `errors[]`), and a `_produced_by` stamp. Gate 1's chat message reads `summary.flagged_slugs` + each flagged verdict's `reasoning` to present the challenges. **This artifact now reaches the deliverable.** `compose_report.py` loads it as an **optional** input and renders a `## Competitor Set Verification` section in `report.md`: per-competitor verdicts, a note naming any `not_a_competitor` entry the founder chose to keep, and the blind-recall gaps (`recall_gaps`, below). This closes a real gap — the verdicts previously existed only in chat at Gate 1, so a competitor judged `not_a_competitor` was still scored on every positioning axis, counted in every moat denominator, and tabled in the report indistinguishably from a genuine competitor.

**`recall_gaps`** — present only when `--blind-set` is passed; produced by diffing the COMPETITOR_RECALL agent's independently-derived candidate set against the drafted set. That agent is dispatched with a **redacted** product summary (no `deck_competition_slide`, `deck_axes`, or `differentiation_claims`) and never receives `ANALYSIS_DIR`, so its set is derived without sight of the draft. The diff is a deterministic slug comparison — never an agent judgment.

| Field | Meaning |
|---|---|
| `blind_set_size` | candidates that survived validation |
| `matched` | slugs present in both sets |
| `unmatched` | candidates found blind but absent from the draft — **the recall-gap signal**, carried through whole (name, why_considered, sources) so Gate 1 can show the founder the reasoning and the citation. An entry may additionally carry `possible_overlap_with`: a draft slug it might duplicate — an **annotation only**; the entry still counts as a gap (distinct from `probable_duplicates` below, which removes an entry from this list entirely). |
| `draft_only` | slugs in the draft the blind agent did not surface — **diagnostic only** |
| `dropped` | candidates rejected for missing sources or reasoning, with the reason |
| `probable_duplicates` | array of `{slug, name, matched_draft_slug, rule}` — candidates removed from `unmatched` because they duplicate a draft competitor. `rule` is `"slug_variant"` (a slug spelling variant of a competitor already in the draft) or `"constituent"` (an exact match against a cohort entry's `constituents`, see `landscape.json` below). This pass is **demote-only**: `unmatched` may shrink, never grow — a text-heuristic demotion was measured falsely hiding four real gaps in one run, including the single most valuable candidate, and hiding a real gap is worse than the duplicate it prevents. |

**`draft_only` is not a verdict and must never be presented to the founder as one.** A blind agent failing to surface a competitor is weak evidence of nothing; Step 3.5's verdicts are the instrument for "is this a real competitor," and they carry independent characterization to back it. Unsourced candidates are dropped rather than shown, on the same principle that governs the rest of this skill: an unsourced claim does not reach the founder.

**`summary.category_disagreements[]`** — additive; `flagged` and `flagged_slugs` keep their existing meaning ("not a genuine competitor") unchanged. Each entry compares a verdict to the competitor's `landscape_draft.json` category and fires in exactly two directions:

| `direction` | Fires when | What it means |
|---|---|---|
| `upgrade` | verdict `genuine`, draft category `adjacent` | Independent verification found *stronger* overlap than the draft credited — the competitor is a closer rival than the analysis assumed. This is the decision-relevant direction the plain `flagged`/`flagged_slugs` fields cannot surface, since they only ever contain non-`genuine` verdicts. |
| `downgrade` | verdict `adjacent`, draft category `direct` | Independent verification found *weaker* overlap than the draft credited. |

Deliberately does NOT fire on a draft category of `do_nothing`, `emerging`, or `custom` — those categories encode the competitor's *market role* (status quo, horizon entrant, sui generis), not its *degree of overlap*, so a `genuine` verdict against a correctly-categorized `do_nothing` or `emerging` entry is not a disagreement.

Each entry: `{slug, draft_category, verdict, direction}`. `recommended_action: "reclassify_direct"` is the `upgrade`-side counterpart to `reclassify_adjacent`.

---

## LANDSCAPE_RESEARCH sub-agent return shape

**Producer:** Research sub-agent (Step 4) or main agent in sequential mode. **Not persisted to disk** — this is the JSON the sub-agent returns to the main thread, which pipes it straight through `validate_landscape.py -o landscape.json`. There is no `landscape_enriched.json` file on disk.

Contains enriched competitor profiles with sourced evidence. The main agent merges approved `suggested_additions` into `competitors[]` before piping the payload to `validate_landscape.py`.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `competitors` | object[] | yes | Enriched competitor profiles (includes any merged suggested additions) |
| `suggested_additions` | object[] | no | Competitors discovered during gap detection; presented to the founder at the mini-gate. Approved entries are merged into `competitors[]` before the payload is piped to `validate_landscape.py` |
| `suggested_axes` | object[] | no | Additional axis pairs suggested by research findings (informational only) |
| `assessment_mode` | string | yes | `"sub-agent"` or `"sequential"` |
| `research_depth` | string | yes | Global research depth: `"full"`, `"partial"`, or `"founder_provided"` |
| `landscape_as_of` | string | yes | `YYYY-MM-DD` the research was validated as-of (`validate_landscape.py --as-of`, default today UTC). Stamped so a consumer of this artifact can tell week-old research from year-old, and used as the reference clock for the `recent_developments` recency window. |
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
| `sources` | object | no (soft-required for fields with `evidence_source: "researched"`) | Per-field citation, parallel to `evidence_source`. Keys are the same field names; values are the URL or the exact search query that produced a `"researched"` value. `validate_landscape.py` warns (`RESEARCHED_WITHOUT_SOURCE`, medium, acceptable) — not fails — when a `"researched"` field has no matching entry here. |
| `research_depth` | string | yes | Per-competitor: `"full"`, `"partial"`, or `"founder_provided"` |
| `recent_developments` | object[] | no | Discrete, DATED competitor moves. Each entry: `date` (`YYYY-MM` or `YYYY-MM-DD`, never future-dated), `type` (one of `funding`, `pricing_change`, `product_launch`, `market_move`, `acquisition`, `leadership`, `layoff`), `summary`, `source` (**URL required** — unlike moat `source`, a search query is not acceptable for a dated claim about a named company), and optional `relevance`. `evidence_source: "agent_estimate"` is REJECTED for this field: a remembered event is not a researched one. An entry dated outside the 18-month window ending at `landscape_as_of` is **not fatal** — `validate_landscape.py` moves it to `out_of_window_developments` (see `landscape.json` below) and emits a medium `STALE_DEVELOPMENT` warning instead. Every other per-entry guard (date format, no future date, no `agent_estimate`, valid `type`, non-empty `summary`, URL `source`) remains **fatal** regardless of window — only the freshness bound was downgraded. **Absent or `[]` is valid and expected** — most competitors have not visibly moved, and inventing movement is worse than reporting none. `NO_RECENT_DEVELOPMENTS` (medium) fires only when EVERY competitor is empty, which indicates shallow research rather than a static market. |
| `sourced_fields_count` | integer | yes | Number of fields with `evidence_source: "researched"` |

### suggested_additions[] entry

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | yes | Competitor name |
| `slug` | string | yes | Proposed slug |
| `category` | string | yes | Proposed category |
| `rationale` | string | yes | Why this competitor was identified during gap detection |
| `partial_profile` | object | no | Whatever evidence was gathered during detection |
| `merged` | boolean | yes | The sub-agent always writes `false` here — promotion hasn't happened yet at hand-off time. After the mini-gate, the main thread relocates each APPROVED entry into `competitors[]` and removes it from this array, so `merged: true` never appears on a persisted entry; a DECLINED entry simply stays in this array with its `false` value unchanged. |

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
      "merged": false
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
| `moat_assessments` | object | no | **Optional. DRAFT ONLY — superseded by `moat_scores.json`, which is authoritative and where every slug is required (see resolution #8 above).** When present, keyed by company slug (including `_startup`). The main thread may write `{}` or omit the key entirely rather than authoring a per-slug draft before MOAT_SCORING runs — omitting it is safe. For `FOUNDER_OVERRIDE_COUNT`, `compose_report.py` counts the **union** of `founder_override` evidence sources found in `moat_scores.json` and in this block, deduplicated by `(slug, moat_id)` — not a fallback that only reads this block when the other is unusable, which would silently drop an override recorded in only one of the two. Two edge cases make the `(slug, moat_id)` key imperfect, and both require non-compliant data to occur (`id` is schema-required on a moat entry, so a compliant artifact never hits either one): the same override recorded in both files double-counts if `id` is present on one copy and missing on the other (the key falls back to a positional index, which won't match across files); and two different id-less overridden moats at the same list index in the two files falsely dedup against each other. Do not read scores from here, and do not spend effort perfecting it — every downstream consumer (`compose_report.py`, `visualize.py`, `explore.py`) reads `moat_scores.json` for scores. Unlike `points[]`, there is deliberately no merge-back step. |
| `differentiation_claims` | object[] | yes | **DRAFT — claim text only, verdict-free.** Written in Step 5 before the POSITIONING_SCORING dispatch runs, so a compliant draft carries `claim` text but not a stress-tested verdict (assigning one before the stress-test runs would be content authoring). Only `claim` is required in this block; `verifiable`/`evidence`/`challenge`/`verdict` are populated by the POSITIONING_SCORING sub-agent and land in `positioning_scores.json`, which is **authoritative for stress-tested claims** — read verdicts from there, not from this block. See the `differentiation_claims[]` entry below for the per-field required/optional split. |
| `scoring_basis` | string | no | `"shipped"` \| `"roadmap_12mo"` \| `"mixed"` — see `competitive-analysis-methodology.md` §7. Absence means not declared; never rendered as `"shipped"` by default (resolution #12 above). |
| `accepted_warnings` | object[] | no | Warnings the agent acknowledges. Only medium-severity codes can be accepted. |
| `metadata` | object | yes | `{run_id}` |

> **⚠ Common mistake — `moat_assessments`:** When present, this MUST be a **dict keyed by company slug**, NOT an array of objects. `score_moats.py` has a compatibility shim that normalizes arrays, but canonical artifacts must use the dict format. Scoring scripts have compatibility shims, but always use canonical format — other consumers may not normalize.
> ```json
> "moat_assessments": {
>   "_startup": {"moats": [...]},
>   "competitor-slug": {"moats": [...]}
> }
> ```

### views[] entry

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | string | yes | A descriptive kebab-case slug (e.g. `firmness-x-integration-burden`) — real runs use these; nothing validates an `"primary"`/`"secondary"` enum. **The primary view is `views[0]`** — with slug ids, "the primary view" has no other referent. |
| `label` | string | no | Human-readable view name for display. **Optional — every existing artifact and test fixture lacks it; never require it.** When absent, consumers title-case the raw `id` (e.g. `firmness-x-integration-burden` → `Firmness-X-Integration-Burden`). |
| `x_axis` | object | yes | `{name, description, rationale, polarity}` — rationale explains why this axis differentiates. **`polarity`** is `"higher_is_better"` (default) or `"lower_is_better"`, and it decides what rank 1 MEANS: on a cost/friction/latency axis a low number is the good end. Omit it and scoring assumes higher-is-better — which is what keeps pre-existing artifacts scoring unchanged, and is also how a live run came to tell a founder they ranked last on price while sitting second-cheapest of nine. Set it whenever the good end is the low end. See the axis-rationale note below for the canonical nesting and the compatibility fallback. |
| `y_axis` | object | yes | `{name, description, rationale, polarity}` — same contract as `x_axis`. |
| `points` | object[] | yes | Per-competitor + `_startup` coordinate assignments |

> **⚠ Common mistake — `x_axis` / `y_axis`:** These MUST be **objects**, not bare strings. `score_positioning.py` has a compatibility shim that wraps strings, but canonical artifacts must use the object format. Scoring scripts have compatibility shims, but always use canonical format — other consumers may not normalize.
> ```json
> "x_axis": {"name": "Axis Name", "description": "What this measures", "rationale": "Why this differentiates"}
> ```

> **⚠ Axis rationale — canonical location and the compatibility fallback:** The rationale MUST be nested inside the axis object (`view["x_axis"]["rationale"]`) — that is the only canonical location. A view-level sibling field (`x_axis_rationale`, `y_axis_rationale`) is a **non-canonical shape the dispatch templates previously instructed**; producers now read it tolerantly (nested wins, sibling is a fallback) purely so existing artifacts recover — do not author new artifacts with the sibling shape. **What went wrong when this was missed:** every run that complied with the old (wrong) dispatch instruction wrote the rationale at the view level instead of nested, so every compliant run emitted an empty nested rationale — the report showed blank rationale lines, both HTML surfaces dropped the axis caption, and the checklist graded `POS_05` ("axis rationale explains differentiation value") as **pass** on text no founder could see. `score_positioning.py` now emits a medium `RATIONALE_MISSING` warning when a scored view ends up with an empty rationale after the fallback is applied.

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
| `source` | string | no (soft-required when `evidence_source` is `"researched"`) | URL or the exact search query that produced a `"researched"` value — lets the main thread spot-check the claim later. `score_moats.py` warns (`RESEARCHED_WITHOUT_SOURCE`, medium, acceptable) rather than fails when missing, since a source may legitimately be a query string, not a URL. |

### differentiation_claims[] entry

In the pre-dispatch draft (what the main thread writes into `positioning.json` in Step 5), only `claim` is required — see the DRAFT note on the top-level field above. The remaining columns describe the fully stress-tested shape as it appears in `positioning_scores.json`.

| Field | Type | Required (draft) | Description |
|-------|------|----------|-------------|
| `claim` | string | yes | The differentiation claim being tested |
| `verifiable` | boolean | no (draft) | Can this claim be independently verified? Populated by POSITIONING_SCORING; absent in the pre-dispatch draft. |
| `evidence` | string | no (draft) | Evidence supporting or challenging the claim. Populated by POSITIONING_SCORING; absent in the pre-dispatch draft. |
| `challenge` | string | no (draft) | What an investor would push on. Populated by POSITIONING_SCORING; absent in the pre-dispatch draft. |
| `verdict` | string | no (draft) | `"holds"`, `"partially_holds"`, or `"does_not_hold"`. Populated by POSITIONING_SCORING; absent in the pre-dispatch draft. **Read stress-tested verdicts from `positioning_scores.json`, not from a draft absent this field.** |

### accepted_warnings[] entry

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `code` | string | yes | Warning code. Any medium-severity code can be accepted: `MISSING_DO_NOTHING`, `SHALLOW_COMPETITOR_PROFILE`, `VANITY_AXIS_WARNING`, `MOAT_WITHOUT_EVIDENCE`, `RESEARCH_DEPTH_LOW`, `MISSING_CANONICAL_MOAT`, `INCOMPLETE_SCORING`. High-severity codes are never acceptable. |
| `match` | string | yes | Case-insensitive substring to match against warning message |
| `reason` | string | yes | Why this warning is expected/acceptable |

**Example** (final, post-merge-back state — `points[]` and `differentiation_claims[]` carry the sub-agents' scored values after the Step 5 merges; the pre-dispatch draft that the main thread writes first has placeholder `points[]` and `claim`-only `differentiation_claims[]`, and typically omits `moat_assessments` entirely):
```json
{
  "scoring_basis": "shipped",
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

**Producer:** `validate_landscape.py` (Step 4)

Validated, normalized competitor list. This is an **exported artifact** consumed by downstream skills (deck-review, fundraise-readiness). Does NOT contain `_startup` — only competitors.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `competitors` | object[] | yes | Validated competitor entries |
| `input_mode` | string | yes | `"deck"`, `"conversation"`, or `"document"` |
| `warnings` | object[] | yes | Validation warnings (may be empty) |
| `suggested_additions` | object[] | no | Passed through verbatim from whatever the main thread piped into `validate_landscape.py` (same shape as the LANDSCAPE_RESEARCH payload's `suggested_additions[]` entry, above). By the time this is piped, approved entries have already been relocated into `competitors[]` and removed from this array by the main thread — so every entry that survives to `landscape.json` is a DECLINED one, still carrying `merged: false`. This is what lets coaching commentary cite "you flagged X as not-a-competitor" without the array also carrying redundant already-merged entries. `merged: true` should never appear in this array on a canonical artifact; its presence indicates a mis-executed merge. |
| `deferred_recall_candidates` | object[] | no | Blind-recall candidates (`{name, slug, category, why_considered, sources}`) the founder declined at the competitor-set gate, retained so they can compete for the same open slots at the later additions gate instead of becoming permanently unaddable. An explicit passthrough in `validate_landscape.py` — that script's output is an allowlist, so an undocumented top-level key would otherwise be dropped. |
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
| `recent_developments` | object[] | no | Preserved from enriched; see the enriched-landscape table above for the entry shape and validation rules. |
| `out_of_window_developments` | object[] | no | Entries `recent_developments` excluded for falling outside the 18-month recency window (same entry shape: `date`, `type`, `summary`, `source`, optional `relevance`). `validate_landscape.py` MOVES an out-of-window entry here rather than failing validation, emitting a medium `STALE_DEVELOPMENT` warning. Every other per-entry guard remains fatal regardless of window — only the freshness bound was downgraded. |
| `constituents` | string[] | no | Company names a cohort entry represents, e.g. `["Rondo", "Antora", "Sunamp"]`. Per-competitor fields pass through `validate_landscape.py` wholesale via `dict(comp)`. Exists because the blind-recall duplicate check (see `competitor_verification.json`'s `recall_gaps.probable_duplicates` above) compares slugs — a company named only inside a cohort's prose read as a missing competitor. With `constituents` the check becomes an exact lookup instead of a text heuristic, which was measured falsely flagging the most valuable candidate in a real run. |
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
  "suggested_additions": [
    {
      "name": "Wallarm",
      "slug": "wallarm",
      "category": "direct",
      "rationale": "Multiple G2 reviews mention Wallarm as a Salt Security alternative in API security",
      "partial_profile": {"description": "API security and WAAP platform", "funding": "Series A, $10M"},
      "merged": false
    }
  ],
  "metadata": {"run_id": "20260319T143045Z"}
}
```

---

## moat_scores.json

**Producer:** `score_moats.py` (Step 5)

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
| `startup_rank` | object | yes | Keyed by moat ID. Each value is `{rank, total}` showing where `_startup` falls (1 = strongest). **Rendering convention:** render `Rank {rank} of {total} ranked` — `total` already counts the startup, so use it as-is (same "M = entities ranked, startup included" convention as `positioning_scores.json`'s rank fields below). `total` additionally varies per dimension because `not_applicable` companies are excluded from that dimension's ranking pool — one report was measured showing `of 10` and `of 11` on adjacent lines, which is correct, not a bug. **SENTINEL — never render verbatim:** when `_startup` is itself `not_applicable`, the producer stamps `{"rank": -1, "total": 0}`; `-1` means "not rankable", not a position. Rendering it shipped `Rank -1 of 0 ranked` to founders. Render the meaning ("Not applicable to this business model") with **no leader** — there is no comparison to lead. Related trap: `not_applicable` sorts last, so it leads only when *every* competitor is unassessed; suppress `leader: X (N/A)`. |

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

**Producer:** `score_positioning.py` (Step 5)

Per-view positioning quality scores with vanity flags and rank-based differentiation.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `views` | object[] | yes | Per-view scoring results |
| `overall_differentiation` | number | yes | 0-100 aggregate differentiation score across all views |
| `differentiation_claims` | object[] | yes | **Authoritative** — the full stress-tested claims (with `verifiable`/`evidence`/`challenge`/`verdict`) from the POSITIONING_SCORING sub-agent's hand-off, passed through by `score_positioning.py`. `positioning.json`'s pre-dispatch draft carries `claim` text only (see that file's DRAFT note) — any consumer that needs stress-tested verdicts reads them from here, not from `positioning.json`. |
| `scoring_basis` | string | no | Passed through from the hand-off. `"shipped"` \| `"roadmap_12mo"` \| `"mixed"` — see `competitive-analysis-methodology.md` §7. Absence means not declared; never rendered as `"shipped"` by default. |
| `views_fingerprint` | string | yes | sha256 hex — a stable hash of the scored map's identity (view ids, axis names, per-competitor coordinates), **excluding all prose** (evidence, rationale, provenance) so rewording an evidence string is not read as a moved map. Order-insensitive over views and over points. `checklist.py` copies this string verbatim into `checklist.json`'s `graded_against` and never recomputes it (one implementation, no drift); `compose_report.py` compares the two — see `CHECKLIST_STALE_VS_POSITIONING` in the Warning Severity Reference. |
| `warnings` | object[] | yes | Quality warnings (may be empty) |
| `metadata` | object | yes | `{run_id}` |

### views[] entry

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `view_id` | string | yes | `"primary"` or `"secondary"` |
| `x_axis_name` | string | yes | Axis name (for display) |
| `y_axis_name` | string | yes | Axis name (for display) |
| `x_axis_rationale` | string | yes | Passed through from `positioning.json`, resolved via the axis-rationale fallback (nested wins, sibling fallback) — see the `views[]` entry note under `positioning.json` above. |
| `y_axis_rationale` | string | yes | Same resolution as `x_axis_rationale`. |
| `x_axis_vanity_flag` | boolean | yes | `true` if >80% of competitors (excluding `_startup`) cluster within 20% of the X-axis range |
| `y_axis_vanity_flag` | boolean | yes | `true` if >80% of competitors cluster within 20% of Y-axis range |
| `differentiation_score` | number | yes | 0-100, rank-based. Computed from `_startup`'s rank among competitors (excluding `_startup` from ranking pool) on each axis. |
| `startup_x_rank` | integer | yes | Where `_startup` would rank among competitors on X (1 = top). `_compute_rank` counts competitors strictly ahead **+1**, so rank `competitor_count + 1` is reachable and means "behind every competitor" — a delivered report was measured rendering `Startup Rank: X=2, Y=11 (of 10 competitors)` from exactly this case. **Rendering convention:** render `Rank N of M` where `M` is the number of entities ranked, startup included — i.e. `M = competitor_count + 1`, never `competitor_count` alone. |
| `startup_y_rank` | integer | yes | Where `_startup` would rank among competitors on Y (1 = top). Same n+1 case and rendering convention as `startup_x_rank` above. |
| `competitor_count` | integer | yes | Number of competitors in this view, excluding `_startup`. For display, the ranked total is `competitor_count + 1` (see `startup_x_rank` above) — never render this value alone as "of N competitors" beside a rank. |

**Differentiation score formula:** Distance-weighted: rank contributes 50%, gap contributes 50%. For each axis: `rank_score = (N - rank + 1) / N * 50`. Gap measures how far ahead the startup is from the next-best competitor: `gap = max(0, (startup_val - next_best_val) / 100) * 50`. Per-axis score = `rank_score + gap_score`. The view's `differentiation_score` is the average of x and y axis scores, capped at 100. `overall_differentiation` is the average across all views. This distinguishes "barely ahead" (rank 1, gap 2%) from "dramatically ahead" (rank 1, gap 40%).

**Rank rendering note:** the example below shows only the ordinary case (rank 1 and rank 3 against `competitor_count: 5`) — it does not illustrate the n+1 ("behind every competitor") case described above.

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
  "scoring_basis": "shipped",
  "warnings": [],
  "metadata": {"run_id": "20260319T143045Z"}
}
```

---

## checklist.json

**Producer:** `checklist.py` (Step 6)

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
| `graded_against` | object | no | `{"views_fingerprint": "<hex>"}` — present only when `checklist.py` was given `--positioning-scores`; the hex is copied verbatim from `positioning_scores.json`. **Absent is silent** — an artifact predating this field has genuinely unknown provenance and must never be asserted fresh or stale, same principle as `scoring_basis` absence (resolution #12 above). |
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

**Producer:** `compose_report.py` (Step 7)

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
4. `## Competitor Set Verification` — optional; present only when `competitor_verification.json` was loaded. Per-competitor verdicts, a note naming any `not_a_competitor` entry the founder chose to keep, and the blind-recall gaps.
5. `## Positioning Analysis` — axis rationale, coordinate map description, differentiation scores
6. `## Moat Assessment` — per-dimension ratings for startup vs. key competitors, trajectory
7. `## Differentiation Stress-Test` — claim-by-claim results with investor challenges
8. `## Key Findings` — prioritized findings from scoring data (script-generated)
9. `## Warnings` — any quality warnings with severity and context
10. `---` (separator — agent inserts `## Coaching Commentary` before this)
11. Footer

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
    "moat_scores.json", "positioning_scores.json", "checklist.json",
    "competitor_verification.json"
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
| `MISSING_POSITIONING` | high | `positioning.json` not found | exit 1 |
| `MISSING_POSITIONING_SCORES` | high | `positioning_scores.json` not found | exit 1 |
| `MISSING_MOAT_SCORES` | high | `moat_scores.json` not found | exit 1 |
| `MISSING_CHECKLIST` | high | `checklist.json` not found | exit 1 |
| `CORRUPT_ARTIFACT` | high | Artifact exists but fails JSON parse, is not a JSON object, or fails a cross-artifact integrity check (orphan/axis mismatch) | exit 1 |
| `STALE_ARTIFACT` | high | `run_id` mismatch across artifacts | exit 1 |
| `UNVALIDATED_ARTIFACT` | high | Artifact exists but `_produced_by` does not match its producer script (written by hand instead of run through the script) | exit 1 |
| `CHECKLIST_STALE_VS_POSITIONING` | high | `checklist.json`'s `graded_against.views_fingerprint` does not match `positioning_scores.json`'s current `views_fingerprint` — the checklist graded a map that has since moved. `run_id` parity cannot detect this, since a re-score does not change the `run_id`. | exit 1 |
| `MISSING_DO_NOTHING` | medium | No `do_nothing` or `adjacent` competitor in landscape | can be accepted |
| `SHALLOW_COMPETITOR_PROFILE` | medium | Competitor with `research_depth: "partial"` and `sourced_fields_count < 3` | can be accepted |
| `VANITY_AXIS_WARNING` | medium | Axis flagged as vanity by `score_positioning.py` | can be accepted |
| `MOAT_WITHOUT_EVIDENCE` | medium | Moat rated `strong` with evidence <20 chars | can be accepted |
| `RESEARCH_DEPTH_LOW` | medium | Global `research_depth: "founder_provided"` with <4 competitors having `sourced_fields_count >= 3` | can be accepted |
| `MISSING_CANONICAL_MOAT` | medium | A company is missing one of the 6 canonical moat dimensions | can be accepted |
| `INCOMPLETE_SCORING` | medium | A landscape competitor is missing from `moat_scores` or positioning views | can be accepted |
| `RESEARCHED_WITHOUT_SOURCE` | medium | A moat entry or competitor field is stamped `evidence_source: "researched"` with no matching `source`/`sources` citation | can be accepted |
| `NO_RECENT_DEVELOPMENTS` | medium | EVERY competitor has an empty or absent `recent_developments` — a signal of shallow research, not of a static market | can be accepted |
| `STALE_DEVELOPMENT` | medium | A dated competitor move fell outside the recency window; dropped from `recent_developments`, preserved under `out_of_window_developments` | can be accepted |
| `RATIONALE_MISSING` | medium | A scored view has an empty axis rationale (after the nested/sibling fallback) | can be accepted |
| `FOUNDER_OVERRIDE_COUNT` | low | N positioning coordinates or moat ratings have `evidence_source: "founder_override"` | report only |
| `MARKER_COLLISION` | low | Report body contains the coaching-marker substring (informational; the per-run uuid prevents real collisions) | report only |
| `SEQUENTIAL_FALLBACK` | info | `assessment_mode: "sequential"` in `positioning.json` or `landscape.json` | report only |
| `CHECKLIST_ALL_PASS` | info | Every checklist item passed (flagged to review for self-grading bias) | report only |

**Accepting medium-severity warnings:** `accepted_warnings[]` can accept *any* medium-severity code, not only the five most common ones — so `MISSING_CANONICAL_MOAT` and `INCOMPLETE_SCORING` are acceptable too. High-severity codes are integrity violations and can never be accepted.
