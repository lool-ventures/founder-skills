# IC Simulation Artifact Schemas

JSON schemas for all artifacts deposited during the IC simulation workflow. Each artifact is a JSON file written to the `SIM_DIR` working directory.

**Every artifact must carry a `metadata.run_id` block** at the top level: `"metadata": {"run_id": "<RUN_ID>"}`. For agent-written artifacts (heredocs), include it inline. For producer-script artifacts (`fund_profile.py`, `detect_conflicts.py`, `score_dimensions.py`), pass `--run-id "$RUN_ID"` and the script injects the block. `compose_report.py` checks that all artifact run IDs match — a mismatch triggers a `STALE_ARTIFACT` warning. The `metadata.run_id` row and example are shown per artifact below.

## startup_profile.json

**Producer:** Agent (heredoc, Step 2)

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `metadata` | object | yes | `{run_id}` — must match the run's `RUN_ID` |
| `company_name` | string | yes | Company name |
| `simulation_date` | string | yes | ISO date (YYYY-MM-DD) |
| `stage` | string | yes | String. Expected values: `"pre_seed"`, `"seed"`, `"series_a"` (calibrated). For later-stage companies use `"series_b"` or `"growth"` — the compose report will flag these as out of calibrated scope. |
| `one_liner` | string | yes | One-sentence company description |
| `sector` | string | yes | Industry/vertical |
| `geography` | string | yes | Primary operating geography |
| `business_model` | string | yes | Revenue model (SaaS, marketplace, etc.) |
| `funding_history` | object[] | no | Prior rounds [{round, amount, date, lead_investor}] |
| `current_raise` | object | no | {amount, valuation, lead_investor} |
| `key_metrics` | object | no | Stage-relevant metrics (ARR, MRR, users, etc.) |
| `materials_provided` | string[] | yes | What the user provided (deck, data room, description, etc.) |
| `team_highlights` | string[] | no | Key team credentials extracted by sub-agent |

**Example:**
```json
{
  "company_name": "Acme Corp",
  "simulation_date": "2026-02-22",
  "stage": "seed",
  "one_liner": "Cloud accounting for SMBs that cuts bookkeeping time by 80%",
  "sector": "Fintech / Accounting",
  "geography": "United States",
  "business_model": "SaaS",
  "funding_history": [
    {"round": "pre-seed", "amount": "$500K", "date": "2025-06", "lead_investor": "Angel syndicate"}
  ],
  "current_raise": {"amount": "$4M", "valuation": "$20M pre"},
  "key_metrics": {"arr": "$800K", "mrr_growth": "15% MoM", "customers": 120, "ndr": "115%"},
  "materials_provided": ["pitch deck (PDF)", "financial model"],
  "metadata": {"run_id": "20260222T140000Z"}
}
```

---

## prior_artifacts.json

**Producer:** Agent (heredoc, Step 3, optional)

Contains imported artifacts from prior market-sizing or deck-review analyses. If no prior artifacts exist, deposit a stub: `{"imported": [], "skipped": true, "reason": "..."}`.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `metadata` | object | yes | `{run_id}` — must match the run's `RUN_ID` |
| `imported` | object[] | yes | List of imported artifact summaries |

### imported[] entry

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `source_skill` | string | yes | `"market-sizing"` or `"deck-review"` |
| `artifact_name` | string | yes | Original artifact filename |
| `import_date` | string | yes | ISO date when the artifact was produced |
| `summary` | object | yes | Key data extracted from the artifact |

**Example:**
```json
{
  "imported": [
    {
      "source_skill": "market-sizing",
      "artifact_name": "sizing.json",
      "import_date": "2026-02-20",
      "summary": {
        "approach": "both",
        "tam_bottom_up": 67500000000,
        "sam_bottom_up": 23625000000,
        "som_bottom_up": 118125000,
        "checklist_status": "pass"
      }
    },
    {
      "source_skill": "deck-review",
      "artifact_name": "checklist.json",
      "import_date": "2026-02-21",
      "summary": {
        "score_pct": 78.5,
        "overall_status": "solid",
        "key_failures": ["competition_honest", "gtm_has_proof"]
      }
    }
  ],
  "metadata": {"run_id": "20260222T140000Z"}
}
```

---

## fund_profile.json

**Producer:** `fund_profile.py` validates agent-provided JSON and injects `metadata.run_id` (Step 4)

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `metadata` | object | output | Injected by `fund_profile.py` from `--run-id`: `{run_id}` |
| `fund_name` | string | yes | Fund name (or "Generic Early-Stage Fund" for generic mode) |
| `mode` | string | yes | `"generic"` or `"fund_specific"` |
| `thesis_areas` | string[] | yes | At least 1 investment thesis area |
| `check_size_range` | object | yes | `{min: number, max: number, currency: string}` |
| `stage_focus` | string[] | yes | Stages the fund invests in |
| `archetypes` | object[] | yes | Exactly 3 partner archetypes |
| `portfolio` | object[] | conditional | Required when `mode == "fund_specific"` (a real fund's actual holdings). OPTIONAL in generic mode — a synthesized/illustrative fund has no real holdings, and forcing this field would manufacture a fabricated portfolio (and fabricated conflicts against it downstream). `fund_profile.py` and `compose_report.py` both treat it this way. |
| `sources` | object[] | conditional | Required when `mode == "fund_specific"`. Each entry is an object with at least `url` or `title`: `{url, title}` |
| `validation` | object | output | Added by `fund_profile.py`: `{status, errors}` |
| `accepted_warnings` | object[] | no | Warnings to acknowledge: `[{code, match, reason}]`. Match is case-insensitive substring. Only medium-severity codes can be accepted. |

### archetypes[] entry

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `role` | string | yes | `"visionary"`, `"operator"`, or `"analyst"` |
| `name` | string | yes | Partner name (or archetype name in generic mode) |
| `background` | string | yes | Brief background description |
| `focus_areas` | string[] | yes | Key areas this partner evaluates |

### portfolio[] entry

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | yes | Company name |
| `sector` | string | no | Industry/vertical |
| `status` | string | no | `"active"`, `"exited"`, `"written_off"` |

### sources[] entry

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `url` | string | conditional | At least one of `url` or `title` is required |
| `title` | string | conditional | At least one of `url` or `title` is required |

**Example:**
```json
{
  "fund_name": "Generic Early-Stage Fund",
  "mode": "generic",
  "thesis_areas": ["B2B SaaS", "Fintech", "Developer Tools"],
  "check_size_range": {"min": 500000, "max": 5000000, "currency": "USD"},
  "stage_focus": ["pre_seed", "seed"],
  "archetypes": [
    {"role": "visionary", "name": "The Visionary", "background": "Former founder, market analyst", "focus_areas": ["market size", "timing", "category creation"]},
    {"role": "operator", "name": "The Operator", "background": "Former operating executive", "focus_areas": ["GTM motion", "execution speed", "customer evidence"]},
    {"role": "analyst", "name": "The Analyst", "background": "Former investment banker", "focus_areas": ["unit economics", "capital efficiency", "financial modeling"]}
  ],
  "sources": [],
  "validation": {"status": "valid", "errors": []},
  "metadata": {"run_id": "20260222T140000Z"}
}
```
`portfolio` is omitted deliberately here — this example is `mode: "generic"`, and SKILL.md Step 4
instructs the agent to omit `portfolio` entirely in generic mode rather than fabricate holdings. A
`mode: "fund_specific"` profile would include a real, researched `portfolio` array instead.

---

## conflict_check.json

**Producer:** Context A dispatch (DETECT_CONFLICTS) returns conflict JSON, piped through `detect_conflicts.py`, which validates + summarizes and injects `metadata.run_id` from `--run-id` (Step 5)

### Input (agent-produced, piped to detect_conflicts.py)

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `portfolio_size` | integer | yes | Total number of portfolio companies checked |
| `conflicts` | object[] | yes | Identified conflicts (may be empty) |

### conflicts[] entry

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `company` | string | yes | Name of the conflicting portfolio company |
| `type` | string | yes | `"direct"`, `"adjacent"`, or `"customer_overlap"` |
| `severity` | string | yes | `"blocking"` or `"manageable"` |
| `rationale` | string | yes | Why this is considered a conflict |

### Output (after detect_conflicts.py validation)

Additional fields added by the script:

| Field | Type | Description |
|-------|------|-------------|
| `summary` | object | Computed summary statistics |
| `validation` | object | `{status: "valid"|"invalid", errors: [...]}` |
| `metadata` | object | Injected by `detect_conflicts.py` from `--run-id`: `{run_id}` |

### summary

| Field | Type | Description |
|-------|------|-------------|
| `total_checked` | integer | From `portfolio_size` |
| `conflict_count` | integer | `len(conflicts)` |
| `has_blocking_conflict` | boolean | Any conflict with `severity == "blocking"` |
| `overall_severity` | string | `"blocking"` > `"manageable"` > `"clear"` |

**Example:**
```json
{
  "portfolio_size": 15,
  "conflicts": [
    {
      "company": "FinLedger",
      "type": "adjacent",
      "severity": "manageable",
      "rationale": "Both serve SMB fintech but different product categories (accounting vs. payments)"
    }
  ],
  "summary": {
    "total_checked": 15,
    "conflict_count": 1,
    "has_blocking_conflict": false,
    "overall_severity": "manageable"
  },
  "validation": {"status": "valid", "errors": []},
  "metadata": {"run_id": "20260222T140000Z"}
}
```

---

## partner_assessment_{visionary|operator|analyst}.json

**Producer:** Context A dispatch (PARTNER_ANALYSIS) — the ic-sim agent dispatched three times in parallel, one per archetype; the main thread writes each return with `metadata.run_id` injected (Step 6)

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `metadata` | object | yes | `{run_id}` — injected by the main thread when writing the return |
| `partner` | string | yes | `"visionary"`, `"operator"`, or `"analyst"` |
| `verdict` | string | yes | `"invest"`, `"more_diligence"`, `"pass"`, or `"hard_pass"` |
| `rationale` | string | yes | Free-text rationale grounded in archetype's focus areas |
| `conviction_points` | string[] | yes | What this partner finds compelling |
| `key_concerns` | string[] | yes | What this partner is worried about |
| `questions_for_founders` | string[] | yes | Questions this partner would ask the founders |
| `diligence_requirements` | string[] | yes | What this partner needs to see before committing |

**Example:**
```json
{
  "partner": "operator",
  "verdict": "more_diligence",
  "rationale": "Strong product-market fit signals with 120 paying customers and 15% MoM MRR growth. However, the GTM motion is unclear — the deck mentions 'inbound and partnerships' but doesn't quantify the channel mix or CAC by channel. Need to see the sales playbook before committing.",
  "conviction_points": [
    "120 paying customers with 115% NDR — customers are expanding",
    "15% MoM growth suggests organic pull",
    "Founding team has domain expertise (ex-Intuit)"
  ],
  "key_concerns": [
    "GTM motion is described but not proven — no channel-level economics",
    "Single sales hire — unclear if the motion is repeatable beyond the founders",
    "No churn analysis shared — need to see cohort data"
  ],
  "questions_for_founders": [
    "Walk me through your last 5 customer wins — how did you find them and what closed the deal?",
    "What's your CAC by channel?",
    "What does your best customer's usage look like vs. your average customer?"
  ],
  "diligence_requirements": [
    "Channel-level unit economics",
    "Cohort retention curves (monthly, by acquisition channel)",
    "Reference calls with 3 customers"
  ],
  "metadata": {"run_id": "20260222T140000Z"}
}
```

---

## partner_rebuttal_{visionary|operator|analyst}.json

**Producer:** Context A dispatch (PARTNER_REBUTTAL) — the ic-sim agent dispatched three times in parallel, one per archetype, each shown its own round-1 assessment plus the other two's; the main thread writes each return with `metadata.run_id` injected (Step 6b). This is round 2 of the debate — round 1 is `partner_assessment_*.json` above, where the three archetypes ran with no sight of each other.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `metadata` | object | yes | `{run_id}` — injected by the main thread when writing the return |
| `partner` | string | yes | `"visionary"`, `"operator"`, or `"analyst"` — must match the archetype this dispatch was made for; `compose_discussion.py` rejects a mismatch |
| `revised_verdict` | string | yes | `"invest"`, `"more_diligence"`, `"pass"`, or `"hard_pass"` — this partner's verdict AFTER reading the other two's round-1 assessments |
| `verdict_changed` | boolean | yes | Whether `revised_verdict` differs from this partner's round-1 `verdict` |
| `changed_because` | string | conditional | Required and non-empty when `verdict_changed` is `true` — must name the specific evidence in another partner's assessment that moved this one. `compose_discussion.py` rejects `verdict_changed: true` with an empty value. |
| `responses` | object[] | yes | This partner's response to each of the other two — see below. Source of `discussion.json`'s `debate_sections`. |
| `dealbreakers` | object[] | yes | New dealbreakers raised in the rebuttal (may be empty). Round-1 `partner_assessment_*.json` has no `dealbreakers` field at all — every entry here is new. |
| `diligence_requirements` | string[] | yes | Updated diligence list after hearing the other two partners |

### responses[] entry

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `to` | string | yes | The archetype being responded to (`"visionary"`, `"operator"`, or `"analyst"`) |
| `point` | string | yes | The response itself, in this partner's own words |
| `concedes` | boolean | yes | `true` only when this specific response gives ground on the partner's own prior position |

### dealbreakers[] entry

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `dimension` | string | yes | A real dimension id from the 28-id set `score_dimensions.py` defines (imported by `compose_discussion.py`, never hardcoded) — an unrecognized id is rejected |
| `reason` | string | yes | Why this is fatal |
| `evidence` | string | yes | The specific evidence — `compose_discussion.py` rejects an empty value |

**Example:**
```json
{
  "partner": "operator",
  "revised_verdict": "more_diligence",
  "verdict_changed": false,
  "changed_because": "",
  "responses": [
    {"to": "visionary", "point": "The 15% MoM growth is encouraging but it's not GTM proof without knowing the channel mix — I'd want the same evidence before calling this repeatable.", "concedes": false},
    {"to": "analyst", "point": "Agreed on needing cohort data before committing.", "concedes": true}
  ],
  "dealbreakers": [],
  "diligence_requirements": ["Channel-level unit economics", "Cohort retention curves (monthly, by acquisition channel)"],
  "metadata": {"run_id": "20260222T140000Z"}
}
```

---

## discussion.json

**Producer:** `compose_discussion.py` (Step 7) — derives from the 3 `partner_assessment_*.json` + 3 `partner_rebuttal_*.json` files. Nothing in this artifact is authored by the main thread; every field is copied or mechanically combined from those six files.

**Consensus rule:** `consensus_verdict` is the value shared by at least 2 of the 3 partners' `revised_verdict`. With exactly three partners, a value with count >= 2 is unique whenever one exists. If all three revised verdicts are distinct (no majority), `consensus_verdict` is `"more_diligence"` — a genuine three-way split cannot be presented as a decision.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `metadata` | object | yes | `{run_id}` — must match the run's `RUN_ID` |
| `_produced_by` | string | yes | Always `"compose_discussion"` — `compose_report.py`'s `UNVALIDATED_ARTIFACT` check flags a `discussion.json` missing this stamp or carrying a different one (a hand-written or otherwise non-derived file) |
| `assessment_mode` | string | yes | `"sub-agent"` or `"sequential"`. `compose_discussion.py` always writes `"sub-agent"` — the round-2 rebuttal architecture has no main-thread-authored fallback path. |
| `assessment_mode_intentional` | boolean | no | Legacy field from the pre-rebuttal architecture; no longer written by `compose_discussion.py` but still tolerated on older artifacts |
| `partner_verdicts` | object[] | yes | Each partner's `revised_verdict` and rationale, copied from the matching `partner_rebuttal_*.json` (rationale falls back to the round-1 assessment's rationale when the verdict did not change) |
| `debate_sections` | object[] | no | Derived from every rebuttal's `responses` array, grouped by the archetype being addressed. Expected shape, and `compose_discussion.py` always composes it from real responses — but `compose_report.py`'s `REQUIRED_KEYS` for `discussion.json` does not enforce its presence, so a `discussion.json` missing it is not schema-invalid. |
| `consensus_verdict` | string | yes | `"invest"`, `"more_diligence"`, `"pass"`, or `"hard_pass"` — see the consensus rule above |
| `debated_dealbreakers` | object[] | yes | `{dimension, raised_by[], evidence[]}` per round-2 dealbreaker, deduped by **dimension id** — the channel `compose_report.py` compares against `score_dimensions.json` to label each scored dealbreaker partner-argued or scoring-only (`key_concerns` keeps only the prose `reason`, so it cannot). Scoring may legitimately flag a dimension the debate never raised; this discloses, never suppresses. Empty = none debated; **absent** (older or hand-written file) = no channel, raising `DEALBREAKER_PROVENANCE_UNVERIFIABLE` — never read as "none debated". |
| `key_concerns` | string[] | yes | Union of round-1 `key_concerns` plus round-2 dealbreaker reasons |
| `diligence_requirements` | string[] | yes | Union of the 3 rebuttals' (post-debate) diligence lists |
| `warnings` | string[] | no | `compose_discussion.py`'s own signals — currently only `"POSSIBLE_CAPITULATION"` (>=2 of 3 verdicts changed and converged on the same value; uncalibrated, never blocking — see that script's module docstring). Empty array when nothing fired. |

### partner_verdicts[] entry

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `partner` | string | yes | `"visionary"`, `"operator"`, or `"analyst"` |
| `verdict` | string | yes | This partner's `revised_verdict` from round 2 |
| `rationale` | string | yes | `changed_because` if the verdict changed, else the round-1 `rationale` |

### debate_sections[] entry

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `topic` | string | yes | `"Responses to <Archetype>"` — mechanically generated from which archetype the grouped responses addressed |
| `exchanges` | object[] | yes | Back-and-forth between partners, one entry per `responses[]` item addressed to this section's target |

### exchanges[] entry

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `partner` | string | yes | Who is speaking (the rebuttal's own `partner`) |
| `position` | string | yes | The responding partner's `point`, verbatim, with `" (concedes this point)"` appended when `concedes` was `true` |

**Example:**
```json
{
  "assessment_mode": "sub-agent",
  "partner_verdicts": [
    {"partner": "visionary", "verdict": "invest", "rationale": "Large market, clear timing..."},
    {"partner": "operator", "verdict": "more_diligence", "rationale": "Strong PMF but GTM unclear..."},
    {"partner": "analyst", "verdict": "more_diligence", "rationale": "Unit economics emerging but need cohort data..."}
  ],
  "debate_sections": [
    {
      "topic": "Responses to Visionary",
      "exchanges": [
        {"partner": "operator", "position": "The GTM story is 'inbound plus partnerships' but there's no data on channel economics..."},
        {"partner": "analyst", "position": "Growth is encouraging but I need to see if it's sustainable. What's the CAC trend?"}
      ]
    }
  ],
  "consensus_verdict": "more_diligence",
  "key_concerns": ["GTM channel economics unproven", "Need cohort retention data"],
  "diligence_requirements": ["Channel-level CAC", "6-month cohort curves", "3 customer references"],
  "warnings": [],
  "_produced_by": "compose_discussion",
  "metadata": {"run_id": "20260222T140000Z"}
}
```

---

## score_dimensions.json

**Producer:** `score_dimensions.py`, which injects `metadata.run_id` from `--run-id` (Step 8)

### Input (piped via stdin)

```json
{
  "items": [
    {
      "id": "team_founder_market_fit",
      "category": "Team",
      "status": "strong_conviction",
      "evidence": "Founders are ex-Intuit with 10+ years in SMB accounting",
      "notes": "Deep domain expertise, lived the problem firsthand"
    }
  ]
}
```

### Output

| Field | Type | Description |
|-------|------|-------------|
| `items` | object[] | All 28 items enriched with category and label |
| `summary` | object | Aggregate scores and verdict |
| `metadata` | object | Injected by `score_dimensions.py` from `--run-id`: `{run_id}` |

### summary

| Field | Type | Description |
|-------|------|-------------|
| `total` | integer | Always 28 |
| `strong_conviction` | integer | Count |
| `moderate_conviction` | integer | Count |
| `concern` | integer | Count |
| `dealbreaker` | integer | Count |
| `not_applicable` | integer | Count |
| `applicable` | integer | `total - not_applicable` |
| `conviction_score` | float | `(strong*1.0 + moderate*0.5) / applicable * 100` |
| `verdict` | string | `"invest"`, `"more_diligence"`, `"pass"`, or `"hard_pass"` |
| `by_category` | object | Per-category counts |
| `dealbreakers` | object[] | Items with `status == "dealbreaker"` |
| `top_concerns` | object[] | Items with `status == "concern"` |
| `warnings` | string[] | Warning codes (e.g., `"ZERO_APPLICABLE_DIMENSIONS"`) |

---

## Stub Artifacts

If a step is not applicable, deposit a stub:
```json
{"skipped": true, "reason": "No prior market-sizing or deck-review artifacts found"}
```

Stubs are recognized by `compose_report.py` and bypass related validation checks.
