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
| `existing_claims` | object | no | Deck's TAM/SAM/SOM, flat, lowercase `tam`/`sam`/`som` (`null` if not stated); other keys are ignored and raise `EXISTING_CLAIMS_SHAPE`. |
| `existing_claims_high` | object | no | High ends of ranges, `{tam, sam, som}`. In range: no mismatch; outside: vs nearest bound. Ignored (`EXISTING_CLAIMS_SHAPE`) without a lower bound or if not above it. |
| `existing_claims_alternatives` | object | no | Per metric, `[{value, slide, label}]`: other deck figures for the same metric and date (a figure for another date goes in `existing_claims_detail`); each raises `DECK_CLAIMS_DISAGREE`. |
| `existing_claims_detail` | object \| null | no | Deck claims outside the flat shape (regional sub-SAMs, dated figures); shown as "Deck Claims (Narrative)", **not** reconciled. |
| `currency` | string | no | ISO code every money figure in the analysis is denominated in (default `"USD"`). A label, and the conversion TARGET. Nothing is converted unless a money input is in another currency **and** its rate is recorded, as an `fx_rate` entry in `validation.json` (Step 4); `--fx-rate` is refused on the reference path. No rate is a hard error, never a guess. Any conversion performed is recorded in `sizing.json`'s `fx` block and disclosed in the report. `compose_report.py` and `visualize.py` render `"USD"` as a `$` prefix and any other code as a suffix (`270.0M EUR`); a non-USD analysis that converted nothing gets an explicit no-FX disclosure, and a converted one gets the rate, its date and its source instead. Checked ahead of `sizing.json`'s own `currency`; a disagreement between the two raises `CURRENCY_MISMATCH`. |
| `sizing_basis` | string | no | Convention this analysis' figures follow: `"current_year"` (default) \| `"forecast_year"` \| `"mixed"` — see `tam-sam-som-methodology.md` §5. Carried into `sizing.json` via `market_sizing.py --sizing-basis` (Step 5). Absence means not declared; `compose_report.py` and `visualize.py` render "Not declared", never a silent default to `"current_year"`. |
| `founder_stated_inputs` | object | no | Facts the founder stated about their **own business** — today `arpu` when stated outright. A figure about the market (`customer_count`, `industry_total`, `segment_pct`, `serviceable_pct`, `share_pct`, `target_pct`) is a claim even when the deck states it and belongs in `existing_claims`/`existing_claims_detail`; recording one here raises `FOUNDER_STATED_MARKET_FIGURE` (high), because the build that consumed it restated the deck instead of testing it. `compose_report.py` compares each stated value against what the sizing consumed and raises `FOUNDER_VALUE_OVERRIDDEN` (medium) on a >0.5% divergence. Empty object = check disabled. |
| `founder_stated_inputs_period` | object | no | Per-field period a `founder_stated_inputs` figure was quoted per — `{"arpu": "month"}`; one of `year`, `quarter`, `month`, `week`. The math's `arpu` is annual, so `compose_report.py` multiplies the stated figure up before the fidelity comparison; a founder-stated $157/month against a computed $1,884 then agrees. An unrecognised value raises `FOUNDER_PERIOD_UNKNOWN` (medium) and the figure is compared as annual. |
| `founder_stated_inputs_source` | object | no | Per-field source of a `founder_stated_inputs` figure: `"chat"` or `"document:<file>#page=<n>"`. Shown beside the figure in the report. |
| `founder_stated_choice` | object | no | The founder's answer to the two-figures question, per field, in their words (`{"arpu": "<their answer>"}`). The report says "the one you chose" only when this is recorded; otherwise it says the founder was not asked which figure to use. |
| `founder_stated_alternatives` | object | no | Other figures the founder stated for one input, unused by the sizing: `{"arpu": [{"value", "period", "source", "label"}]}`. Recorded after the founder chose one (Steps 2–3); the report shows each under "Your Answers". Never compared by `FOUNDER_VALUE_OVERRIDDEN`. `label` is the page's own words (six or more); the page is named only when they are found on it, else "in your materials". A `"chat"` source is never shown. |
| `founder_stated_inputs_currency` | string | no | ISO code the `founder_stated_inputs` money figures are in. Only consulted when a money input was FX-converted: without it the comparison against the converted figure would diverge by exactly the exchange rate, so `compose_report.py` reports `COMPARISON_CURRENCY_UNKNOWN` instead of a false `FOUNDER_VALUE_OVERRIDDEN`. Declare it whenever the founder's figures are not in `currency`. |
| `existing_claims_currency` | string | no | ISO code the `existing_claims` figures are in (the deck's own, not always the analysis currency). Same rule as above: without it a converted run reports `COMPARISON_CURRENCY_UNKNOWN` rather than a false `DECK_CLAIM_MISMATCH`. |
| `existing_claims_horizon_months` | object | no | `{tam, sam, som}` — the period each stated figure represents, in months (`null` when not stated or not time-bound). Only `som` is read today: a SOM stated as a plan-year run-rate is `12`, a "by 2028" figure is the months from `analysis_date`. Compared against `capture_horizon_months`; when they differ the report says so instead of computing a delta between two periods. |
| `capture_horizon_months` | integer | no | The period the computed SOM represents — what `share_pct` / `target_pct` describe, typically 36 or 60. Required for the horizon check to run; without it the comparison behaves exactly as before. |
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
| `red_team_revision` | object | no | `{"changes": [{"field", "reason"}]}`: why a figure changed in the one revision after the adversarial review (Step 6d). Read by nothing and printed nowhere, so a `label` never carries history. The reviews themselves record what changed; nothing here licenses anything. |
| `founder_notes` | string[] | no | Founder answers given after the revision round was used; rendered under "Your Answers" instead of restated in chat. |
| `gate_defaults` | string[] | no | Questions not asked because the founder asked not to be asked; the default (option 1) was taken. Rendered under "Your Answers". |
| `red_team_skipped` | string | no | Why no adversarial review ran (Step 6c). One of exactly `founder_declined`, `dispatch_failed`, `no_network_available`, `no_subagent_dispatch` — a closed enum, because this value selects the sentence the founder reads and free text would be an un-reviewed founder-facing string. `compose_report.py` REFUSES to compose when there is neither a fresh `redteam.json` for this run nor a recognised value here; an unrecognised value is refused too. There is deliberately no value meaning "not necessary". |
| `red_team_skipped_run_id` | string | with `red_team_skipped` | The run the skip was decided in: this run's `RUN_ID`. compose accepts a skip only for the run it resolves (the id most required artifacts carry); without this field it falls back to `metadata.run_id` of this file, and a skip with neither is refused. |
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
  "rationale": "Industry reports available for top-down, company has customer/pricing data for bottom-up. Running both lets us say what drives any gap.",
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
| `name` | string | yes | This figure's own name, unique in the record. A sizing input references it by this name (`{"assumption": "<name>"}`); the name implies nothing about what it measures. |
| `label` | string | no | Human-readable display name. If omitted, falls back to title-cased `name`. |
| `value` | any | yes | The figure as its source states it |
| `unit` | string | for figures | What it measures: `money_total_per_year`, `money_per_customer`, `count`, `fraction` (0-1), `ratio`, `percent_points` (35 = 35%), `percent_change`, `years`, or `fx_rate`. A figure without one cannot be referenced by the sizing. |
| `currency` | string | money units | ISO code the source states it in. A figure in another currency than the analysis converts through an `fx_rate` entry. |
| `period` | string | `money_per_customer` | `month`, `quarter` or `year`. Never assumed; the calculator makes it annual. |
| `from` / `to` / `as_of` | string | `fx_rate` | The rate converts one `from` into `to`, as quoted on `as_of`. Must be `sourced`; never inverted or estimated. |
| `category` | string | yes | One of: `"sourced"` (cite the source: `source_title` / `source_url` naming a `sources[]` entry, or it grades as an estimate), `"derived"` (show formula), `"agent_estimate"` (flagged as unsupported) |
| `source` | string | no | Citation for sourced assumptions |
| `derivation` | string | no | Formula/logic for derived assumptions |
| `factors` | object[] | no | For `derived` assumptions: **two or more multiplicands**, each `{"factor_id": "<snake_case>", "value": <number>, "source_id": "<a sources[] title or short slug, or company_stated / agent_estimate>"}`. Percent-point parameters (`segment_pct`, `serviceable_pct`, `share_pct`, `target_pct`) store the product ×100. `compose_report.py` recomputes it and raises `FACTOR_PRODUCT_MISMATCH` (medium) beyond 2%, and reports figures the two approaches share. An entry may carry `"role": "divisor"` to itemize a ratio instead of only a product — e.g. `{"factor_id": "target_segment", "value": 15000000, "source_id": "..."}, {"factor_id": "total_market", "value": 52800000, "source_id": "...", "role": "divisor"}` narrows to 15,000,000 ÷ 52,800,000, not a nonsensical product of the two. A single entry is the value under another name, not a chain, and reads as un-itemized. A sum is not a chain either: describe it in `label` and omit `factors`; the report will say the figure is not itemized, which is true. A derived assumption with no usable `factors` raises `UNSTRUCTURED_DERIVATION` (low), aggregated into one warning naming every such figure. |

`factors` describes how a researched figure was assembled, for the founder to check. It does not feed
the math: what feeds the math is the sizing's own references (see sizing.json). Qualitative assumptions
(e.g., `market_growing`) carry no `unit` and are never referenced.

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
    {"name": "smb_accounting_market", "value": 50000000000, "unit": "money_total_per_year", "currency": "USD", "category": "sourced", "source_title": "Global SMB Accounting Software Market Report 2025"},
    {"name": "smb_share", "label": "SMB Segment Share", "value": 16, "unit": "percent_points", "category": "derived", "derivation": "SMB share of total market from BLS data",
     "factors": [{"factor_id": "has_payroll", "value": 0.40, "source_id": "BLS 2024"}, {"factor_id": "uses_accounting_software", "value": 0.40, "source_id": "company_stated"}]},
    {"name": "smb_count", "value": 4500000, "unit": "count", "category": "agent_estimate"},
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
- `FACTOR_PRODUCT_MISMATCH`: a `derived` assumption whose `factors` do not multiply to its stated value, beyond 2% (medium severity)
- `UNSTRUCTURED_DERIVATION`: `derived` assumptions carrying no `factors` (low severity; one warning per run, naming each)

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
| `comparison` | approach is `"both"` | Top-down vs bottom-up comparison |
| `fx` | only when a conversion happened | `{as_of, source, conversions: [{field, from, to, rate, original_value, converted_value}]}`. Present only when a money input declared a source currency differing from `currency` AND a rate was supplied. `converted_value` **is** the number the sizing math consumed, so `compose_report.py` can compare a founder-stated or deck-claimed figure across the conversion. Absent on every run that converted nothing — which is every run that does not opt in. |
| `metadata` | when `--run-id` passed | `{"run_id": "<RUN_ID>"}` — stamped by the producer for `STALE_ARTIFACT` detection |
| `provenance_version` | always (new runs) | `1`. A sizing without it predates inputs carrying their provenance. |
| `input_refs` | reference path | The hand-off's reference for each input, as given. `--replay` re-resolves these. |
| `input_provenance` | always (new runs) | Per input: `kind` (`assumption` / `founder_stated` / `derived` / `estimate`, or `not_checked` on the numeric path), `category`, `unit`, `value_as_recorded`, `normalisation` (period, fx, rounding steps), `value_consumed` (the number the math used), `source_title`/`source_url`, `entries` (the record entries it depends on), and for an estimate `why` and any `research_value`. |
| `projection_inputs` | growth projection used | `{growth_rate, years}` |

**Inputs by reference.** The sizing hand-off names each input's origin instead of carrying a number:
`{"assumption": "<name>"}`, `{"founder_stated": "arpu"}`, `{"derived": {"op": "multiply"|"divide"|"to_percent"|"to_fraction", "factors": [...]}}`
or `{"estimate": <n>, "unit": ..., "why": ...}`. `market_sizing.py --validation --inputs` resolves them, and
refuses an input whose unit does not fit (`industry_total` money per year, `customer_count` a count,
`arpu` money per customer, the `*_pct` inputs percentage points). A unit refusal of a directly
referenced figure is kept in `handoff/<run_id>/unit_rejections.json`. On this path currency and rates
come from the record; `--fx-rate` is refused.

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

### Provenance (stamped by the producer, re-checked at render)

`input_provenance` is written by `market_sizing.py`, the step that consumed the values. `compose_report.py`
and `visualize.py` read it through `_view.py` and never join the research record to the sizing by name.
Each figure is graded by the worst grade among its inputs (`agent_estimate` > `derived` > `sourced`; the
founder's own figure counts as sourced; a `not_checked` input grades nothing). The deck comparison
(`deck_claim`, `delta_vs_deck_pct`, ...) is in the same output block:

```json
{"provenance": {"top_down": {"tam": {"classification": "derived",
  "confidence_breakdown": {"sourced": 0, "derived": 1, "agent_estimate": 0},
  "deck_claim": 50000000000, "delta_vs_deck_pct": 35.0,
  "input_provenances": {"industry_total": "derived"}}}}}
```

Before rendering, `_view.sizing_integrity` re-resolves `input_refs` against the current record and
recomputes the figures with the calculator's own math: `SIZING_ALTERED` (the saved figures disagree;
both pages render the recomputation), `SIZING_STALE` (the record moved, before any review),
`RECORD_CHANGED_AFTER_REVIEW` (against the shown review's `inputs_reviewed`), `SIZING_UNRESOLVABLE`,
`UNIT_CHANGED_AFTER_REJECTION`. A change between the first review and the shown one is
`ANALYSIS_CHANGED_BETWEEN_REVIEWS` (medium, a disclosure).
All high. A sizing without provenance, or with `not_checked` inputs, beside a real research record is
`SIZING_NOT_CHECKED` (high); with a stub record and every input the founder's own, `INPUTS_USER_PROVIDED`
(medium).

---

## redteam.json

Written by `red_team.py` from the RED_TEAM sub-agent's hand-off (Step 6c). Optional artifact; when absent, `methodology.red_team_skipped` must say why. It carries `inputs_reviewed` (each sizing input's reference, consumed value and record entries, plus the quantitative record as it stood), written once per round; editing it is an edit of the review. `red_team.py` also writes an append-only copy per round, `handoff/<run_id>/redteam.r<N>.json` (the review plus `_review_copy: {round, handoff_sha256, inputs_at_review}`); compose and visualize render the review from that copy, so an edit to `redteam.json` changes nothing the founder reads and raises `REDTEAM_ALTERED`.

| Field | Type | Notes |
|---|---|---|
| `findings[]` | object[] | Accepted findings: `claim_attacked`, `what_is_true`, `evidence_quote`, `source_url`, `source_title`, `severity` (`high`/`medium`/`low`), `quote_verified`. |
| `findings[].source_url` | string | One of three provenances: a web address; exactly `internal:analysis` (the sentence is the analysis's own); or `document:<filename>#page=<n>` (`n` ≥ 1; required for a PDF, omitted for a file with no pages such as `.md`) — the founder's own page, where `<filename>` must be a file the founder supplied (as mirrored under the hand-off dir's `docs/`). A document citation needs a six-word quote. |
| `findings[].parameter` | string | Optional: the sizing input the claim is about (one of the seven parameter names). With `severity: high` and the input in `inputs.founder_stated_inputs`, both reports mark every row built on it with §. Unknown names are dropped from the finding, never a rejection. |
| `findings[].quote_verified` | bool or null | Document citations only: `true`/`false` when the page had text (a text layer, or an `ocr_uploads.py` sidecar) and the quote was / was not found on it; `null` when nothing on disk could check it. Web and internal findings are always `null`. |
| `rejected[]` | object[] | `{claim_attacked, reason}` for each finding that could not be shown (no source, a document not supplied, a token quoted as a sentence, an internal quote that is JSON rather than a sentence). Counted, never dropped silently. |
| `could_not_check[]` | string[] | Claims the review could not assess, each with its reason. |
| `sources_read[]` / `sources_unread[]` | string[] | Documents the red team opened / did not open, by filename, against the uploads directory. `sources_unread` non-empty raises `RED_TEAM_SOURCES_UNREAD` (high). |
| `summary` | object | `accepted`, `rejected`, `unchecked`, `sources_unread`, `by_severity`, `humanized` (how many of our file names and identifiers `red_team.py` reworded in `claim_attacked` / `what_is_true` / `source_title`; `evidence_quote` is never reworded). |

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

With `--sizing sizing.json` (the skill's path), `base` is optional: base values and grade tiers come
from the sizing's `input_provenance`, a disagreeing hand-off `base` is ignored (recorded in
`base_ignored`, with `base_source: "sizing"`), and the output carries
`graded_against: {"sizing.json": <fingerprint>}`. compose raises `SENSITIVITY_STALE` (high) when that
is not the sizing the report shows, or is missing. `checklist.py --sizing` stamps the same, and a
mismatch there is `CHECKLIST_STALE` (medium).

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
- `CHECKLIST_FAILURES`: at least one failure, but the score still reaches `solid` (**medium** severity — a content finding, acceptable via `accepted_warnings` with a stated reason). Stated as a band, like its critical counterpart below: "1–6" is the same all-22-applicable assumption, and the two lines contradicted each other whenever any item was `not_applicable`.
- `CHECKLIST_FAILURES_CRITICAL`: the score cannot reach `solid` — `pass / (pass + fail)` below 70 (high severity, never acceptable). Stated as a BAND, not a failure count: an absolute `fail > 6` assumes all 22 criteria apply, and with 7 `not_applicable` items the boundary is 5, so a checklist scoring 66.7% was filed as the acceptable warning. The band reproduces 6/7 exactly when nothing is N/A (7 of 22 caps the score at 68.2%; 6 reaches 72.7%). The two warnings are mutually exclusive.
- `CHECKLIST_INCOMPLETE`: fewer than 22 items
- `LOW_CHECKLIST_COVERAGE`: more than 7 `not_applicable` items (medium severity)
