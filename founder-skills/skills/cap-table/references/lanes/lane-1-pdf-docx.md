# Lane 1 — PDF / DOCX (single instrument)

Typical input: a 5–15 page SAFE, term sheet, convertible note, or option plan.

## Read the document

The main thread reads the source document via the `Read` tool (native PDF support, up to 20 pages per call; longer docs use the `pages` parameter to chunk).

## Dispatch Context A — `INSTRUMENT_EXTRACTION`

Dispatch with the `Task` tool. `OUTPUT_PATH` is the relative `$HANDOFF_AGENT` namespace — never an absolute `/sessions/...` path (the host-loop path gate denies a file-tool write there). Copy the invocation below **whole** — the `subagent_type` is part of it:

```
Task(
  subagent_type="founder-skills:cap-table",   # REQUIRED — omitting it silently downgrades the dispatch to the wildcard, shell-capable general-purpose agent
  prompt="""
CONTEXT: INSTRUMENT_EXTRACTION
OUTPUT_PATH: <HANDOFF_AGENT>/<doc_slug>_extraction_output.json
RUN_ID: <RUN_ID>

You are the cap-table agent dispatched in Context A (INSTRUMENT_EXTRACTION).
The main thread has provided the document content below. Extract the
structured terms per your agent body's Context A specification.

Document content:
<paste the document text — for PDFs, this is what the Read tool returned; for a tracked-changes DOCX, this is the `scripts/_docx_text.py "<path>" --extract` accepted-view output (NOT the raw Read-tool view), so the extractor and evidence_verifier share one revision view>

Use your Write tool to write to OUTPUT_PATH exactly the
{instrument_type, fields, confidence, ambiguities} shape. Then return ONLY the
receipt JSON in your final assistant message:
{"status": "complete", "output_path": "<echo of OUTPUT_PATH>"}
Do not write artifacts to disk anywhere else. Do not invoke producer scripts.
"""
)
```

After the sub-agent returns, gate the hand-off per the Context A hand-off protocol in SKILL.md Step 0 (`check_handoff.py`, branch on exit code) before piping.

### Sub-agent response shape (load-bearing — `extract_instrument.py` won't accept other shapes)

```json
{
  "instrument_type": "convertible_security",
  "fields": {
    "purchase_amount": 500000,
    "form": "yc_postmoney_cap",
    "post_money_valuation_cap": 10000000,
    "discount_multiplier": null,
    "issuance_date": "2024-01-15"
  },
  "confidence": {
    "purchase_amount": {
      "level": "high",
      "evidence_quote": "the Investor will pay the Company $500,000 (the \"Purchase Amount\")",
      "document_location": "page 1, second paragraph"
    },
    "post_money_valuation_cap": {
      "level": "high",
      "evidence_quote": "the Post-Money Valuation Cap is $10,000,000",
      "document_location": "page 1, Definitions"
    },
    "issuance_date": {
      "level": "high",
      "evidence_quote": "Date: January 15, 2024",
      "document_location": "page 1, top"
    }
  },
  "ambiguities": []
}
```

Notes the dispatcher MUST honor:

- **`instrument_type` is the routing key for subtype gates.** Per `extract_instrument.py`'s `valid_itypes`, accepted values are `safe`, `convertible_note`, `convertible_loan_agreement`, `convertible_security`, `term_sheet`, `option_plan`, and the non-extractable `warrant` / `non_instrument` / `amendment`. To route a YC-style convertible_security through the relaxed gate (waives `day_count_basis` / `maturity_date` / `maturity_default_treatment` / `annual_interest_rate`), set `instrument_type: "convertible_security"`. Setting `instrument_type: "convertible_note"` and putting `subtype: "convertible_security"` inside `fields` does NOT work — the strict gate fires and validation fails on missing convertible_note fields.
- **Amendment / clause-only documents** (a doc that only restates one clause of an existing instrument — e.g. the Qualified Financing definition — and leaves every other term unstated) MUST be classified `instrument_type: "amendment"`, NOT forced through the note gate. An amendment is non-extractable: it is classified and surfaced but never persisted to an instrument array (it must not land as an all-null note in `convertible_notes`). Put each amended clause in an `ambiguities` entry (e.g. `{"field": "qualified_financing", "description": "amendment restates the QF definition; base note terms not included"}`). To surface those clause deltas automatically (no hand-authoring), write the `extract_instrument.py` receipt — it carries `classified_doc_type: "amendment"` plus the `ambiguities` — to `$REVIEW_DIR/extraction_audit.json`; `compose_extraction_report.py --audit` then renders an **"Amendments (terms modified)"** section from it and still renders any co-extracted instruments.
- **Term sheets / option plans** (`instrument_type: "term_sheet"` or `"option_plan"`) have **no strict field schema** — use descriptive snake_case keys, extracted as-is; they are not persisted to a math array. Their content rides in the receipt's `terms_doc` and renders as a **"Term sheet terms (as extracted)"** table via `compose_extraction_report.py --audit` (save the receipt to `$REVIEW_DIR/extraction_audit.json`). Minimal wrapper (same envelope as any instrument — do NOT invent top-level keys like `classified_doc_type`/`extracted_fields`):
  ```json
  {"instrument_type": "term_sheet",
   "fields": {"pre_money_valuation": 20000000, "investment_amount": 5000000, "post_money_valuation": 25000000,
              "liquidation_preference_multiple": 1.0, "anti_dilution": "broad-based weighted average",
              "board_composition": "2 founder, 1 investor, 1 independent", "option_pool_pct": 0.10},
   "confidence": {"pre_money_valuation": {"level": "high", "evidence_quote": "Pre-Money Valuation: $20,000,000"}},
   "ambiguities": []}
  ```
  A terms doc **never blocks** on a verifier/invariant finding — a `value_in_doc` fail or a cross-field (pre+investment≈post) mismatch is rendered as a per-field to-confirm marker, not a hard error; a missing `--source-doc` still fails loud.
- **`confidence` is keyed by `fields` field name**, and each value is a `{level, evidence_quote, document_location?}` object. A bare string like `"confidence": "medium"` is rejected (`extract_instrument.py` will exit non-zero with a clear error rather than crashing on `.items()`). The `level` enum is `high | medium | low | absent` (use `absent` when the document is silent on a field).
- **`evidence_quote` lives inside each `confidence` entry**, NOT as a top-level `evidence` block, NOT as a per-field key inside `fields`. The forward evidence verifier (`evidence_verifier.py`) reads `confidence[fname].evidence_quote` for its three-layer check (`quote_in_doc` / `value_in_quote` / `value_in_doc`). **Every populated, non-synthesized field needs its own `confidence` entry carrying a verbatim `evidence_quote`** (or `level: "absent"` when the document is silent and the value is null) — the verifier gates on it, so a field you leave out of `confidence` renders as an unverified to-confirm row. Supply confidence for ALL extracted fields, not just a subset. **DocuSign / signed-overlay fields** (a value that appears only in the visual overlay, not the extractable text layer) will fail `value_in_doc` — extract them as `null` + `level: "absent"` + an `ambiguities` entry naming the overlay sighting, rather than claiming a quote the text layer cannot confirm.
- **Synthesized fields** (computed/classified rather than extracted — e.g., `id`, derived counts, `extraction_confidence`, the `subtype` stamp itself) do NOT need an `evidence_quote`. The verifier has a built-in skip list (~30 fields) and produces `skipped_synthesized` rather than `fail`.
- **Form-template / unexecuted-counterpart documents** (Word/PDF templates with blank investor name, amount, date) should NOT have placeholder values fabricated. For each blank field: (1) set the field to `null`; (2) set its `confidence` entry to `{"level": "absent"}` — **this is required for the relaxed gate to accept the absence; a null WITHOUT `level: "absent"` still hard-errors** (the validator relaxes only fields the extraction affirmatively documents as absent); and (3) add an `ambiguities` entry of the form `{"field": "purchase_amount", "reason": "form template — investor amount blank in source"}`. The field then persists as a partial (`completeness: "partial"`, a `W_FIELD_ABSENT_IN_DOC:<field>` warning) with the value left null, and the main thread surfaces it to the founder via `AskUserQuestion` rather than pushing fabricated data through the verifier. Relaxable fields: SAFE `purchase_amount` / `issuance_date` / `investor_name`; note `principal` / `issuance_date` / `investor_name` / `maturity_date` / `maturity_default_treatment`; warrant `exercise_price` (a warrant whose share count is confirmed but whose strike is genuinely not stated persists as a partial — its shares still count in fully-diluted, only exercise math is skipped; a null `exercise_price` WITHOUT `level: "absent"` hard-errors). Other required fields (the per-form valuation cap, `day_count_basis`, the interest fields; and for a warrant the full item shape — `shares_underlying` / `warrant_type` / `issuance_date` / `settlement_type` / `vested_flag`) still hard-error if missing.

### Full `convertible_note` shape (interest-bearing note — strict gate)

The example above is a YC-style `convertible_security` (relaxed gate). A true interest-bearing **convertible note** uses `instrument_type: "convertible_note"` and the STRICT gate, which requires the interest/maturity fields below. Field names and enums are exact — the common mistakes are `purchase_amount` (that is the SAFE field; a note uses **`principal`**), inventing an `interest_rate_type` value, and writing `day_count_basis` as a string:

```json
{
  "instrument_type": "convertible_note",
  "fields": {
    "principal": 1000000,
    "annual_interest_rate": 0.06,
    "interest_rate_type": "fixed_numeric_simple",
    "day_count_basis": 365,
    "issuance_date": "2024-01-15",
    "maturity_date": "2026-01-15",
    "maturity_default_treatment": "convert_at_cap",
    "discount_multiplier": 0.80,
    "valuation_cap": 15000000,
    "investor_name": "Foobar Capital LLC",
    "governing_law": "delaware",
    "interest_converts_to_shares": true
  }
}
```

Field conventions:

- **`principal`** (number) — the note's face amount. NOT `purchase_amount`.
- **`annual_interest_rate`** (number|null) — a **fraction**, not a percent: `0.06` = 6% (invariant bound `[0.0, 0.20]`). May be `null` only when `interest_rate_type` is `none`.
- **`interest_rate_type`** — enum, exactly one of `fixed_numeric` | `fixed_numeric_simple` | `statutory_ita_section_3j` | `none`. (`fixed_numeric_simple` = simple interest at a stated numeric rate; there is no `fixed_simple`.)
- **`day_count_basis`** (integer|null) — the interest day-count denominator, typically `365` (or `360`). An integer, never a string.
- **`maturity_default_treatment`** — enum `convert_at_cap` | `repay` | `extend` | `counsel_review` | `null`.
- **`discount_multiplier`** (number|null) — canonical multiplier per Gotcha #3: `0.80` means a **20% discount** (never store the 0.20 discount rate here).
- **`subtype`** — enum `convertible_note` | `convertible_loan_agreement` | `convertible_security` | `null`.
- Required for the strict gate: `id`, `investor_name`, `principal`, `interest_rate_type`, `issuance_date`, `extraction_confidence` (each `fields` value carries its `confidence` entry as in the example above).

## Pipe through `extract_instrument.py`

The validation script enforces schema, runs evidence verification + invariant checks against the source doc, and appends to `instruments.json`:

```bash
cat "$HANDOFF_DIR/<doc_slug>_extraction_output.json" | python3 "$SCRIPTS/extract_instrument.py" \
  --instruments "$REVIEW_DIR/instruments.json" --run-id "$RUN_ID" --pretty \
  --source-doc "$DOC_PATH"
```
<!-- skill-quality-ci: bash-after-subagent-ok -->

`--source-doc <path>` is the only verification flag you need to pass. **Evidence verification, evidence-verification blocking, and invariant checking are all default ON.** Use `--no-verify` / `--no-verify-blocking` / `--no-invariants` to opt out (rare — typically only for tests or documents the user explicitly marks as unverifiable).

**Re-piping a corrected extraction of the SAME instrument — avoid silent duplicates.** The script **appends** to the target array, assigning a fresh sequential `id` (`note_00N` / `safe_00N`) whenever the extraction carries no explicit `id`. So re-piping a corrected extraction of the same instrument does NOT overwrite the prior one — it adds a duplicate. `--replace` is an upsert keyed on `id`, and a freshly-assigned id never collides, so **passing `--replace` alone does nothing**. Before re-piping a correction for the same instrument, either **reset the target array to empty** (rewrite `instruments.json` with an empty `<array>: []`) OR set the **same `id`** in the corrected JSON **and** pass `--replace`. The script emits a `W_POSSIBLE_DUPLICATE_INSTRUMENT` receipt warning when a new entry matches an existing one on `investor_name` + `principal` + `issuance_date` — treat that warning as a signal you re-piped without resetting.

## What the verification stack checks

- **Evidence verification** (`evidence_verifier.py`): checks each extracted value against the source document and rejects extractions where claimed values don't appear in the source — the canonical hallucination pattern. Three-layer check: `quote_in_doc` / `value_in_quote` / `value_in_doc`. Calibrated at 3.6% FPR / 100% TPR on verifiable docs.
- **Invariant checking** (`invariant_checker.py`): per-field real-world bounds (SAFE `purchase_amount` ≤ $50M, `discount_multiplier` ∈ [0.5, 1.0], note interest ≤ 20%, etc.) plus cross-field math invariants (options_granted ≤ total_authorized; pre/post-money caps mutually exclusive on the same SAFE). Hard math impossibilities block; soft bounds warn-only.
- **Cross-checking** (`cross_checker.py`): demote-only confidence modulation when multiple extractors disagree on a field. Agreement keeps the minimum confidence; disagreement demotes one level.

## Handling non-zero exit from `extract_instrument.py`

- **Validation errors** (`errors` in stderr): show via `AskUserQuestion` and re-extract.
- **Evidence verification rejection** (`rejection` block in receipt with `failed_fields`): the verifier found values that don't appear in the source doc. Re-dispatch the sub-agent with the `retry_hint` text from the rejection, asking it to re-check those specific fields against the document. If the same field fails verification on a second pass, treat as low-confidence and present to the founder via `AskUserQuestion` for confirmation.
- **Invariant hard violation** (`invariant_check.n_hard_violations > 0`, stderr mentions `invariant_checker`): a math impossibility was detected (e.g., both `pre_money_valuation_cap` and `post_money_valuation_cap` set on the same SAFE). Show the violation reasons to the founder and re-extract.

## `attention_needed_fields` in the receipt

This is the union of:
- (a) low-confidence fields,
- (b) fields that triggered soft invariant warnings (out-of-range values), and
- (c) fields the evidence verifier marked unverifiable.

The dispatching agent should escalate these via `AskUserQuestion` AND, for high-stakes extractions, dispatch backward verification on this exact field subset (see below). This is the lightweight hook for selective backward-verification dispatch — no need to backward-verify every field, just the ones already flagged for attention.

## Unverifiable documents

If the source document is image-only or DocuSign-overlay (verifier returns `overall_status: "unverifiable_doc"` or `verifier_blind_demoted`, i.e. the text layer is empty / `is_doc_image_only`), the text-based verifier has nothing to match against.

**Vision fallback:** before giving up, dispatch a FRESH sub-agent — `Task(subagent_type="founder-skills:cap-table", …)` (REQUIRED; a type-less dispatch silently downgrades to the shell-capable general-purpose agent) — to transcribe the relevant passages of the image-only document into plain text, then feed that transcription back to the verifier via `--doc-text <file>` (instead of `--source`). When the document text came from model vision rather than a text layer, the verifier stamps `verification_source: "model_vision"` and demotes the field confidence one level (vision transcription is less reliable than a real text layer). Surface the demotion to the founder and ask for explicit confirmation of the extracted values before commit.

If no usable transcription is possible, surface the unverifiable status to the founder and ask for explicit confirmation of the extracted values before commit.

If the extraction surfaced ambiguities or low-confidence fields, present them via `AskUserQuestion` for confirmation before proceeding.

## Optional: backward verification (WARN-mode)

After forward verification passes, you may optionally run backward verification — an independent re-extraction by a fresh sub-agent that catches semantic-confusion errors (right value in source but wrong field; e.g., "Purchase Amount" vs "Aggregate Purchase Amount of all Safes"; pre-money vs post-money form classification). This is separate from forward verification, which catches outright hallucinations.

```bash
# Step 1 — write the document text you already read (the "Read the document" step above) to a
# staging file, then emit per-field re-extraction prompts. The prompts embed this text inline for
# the fresh sub-agent — a sub-agent's file tools cannot resolve $DOC_PATH (a main-thread/VM-shell
# path), so it is never handed a bare path to Read; the same "paste the document text" shape as
# the INSTRUMENT_EXTRACTION dispatch. Single-quoted heredoc delimiter (apostrophe-safe).
cat <<'BV_DOC_TEXT_EOF' > "$STAGING_DIR/bv_doc_text.txt"
<paste the same document text used for the INSTRUMENT_EXTRACTION dispatch above>
BV_DOC_TEXT_EOF
python3 "$SCRIPTS/backward_verifier.py" --phase=prompt \
  --extraction "$EXTRACTION_JSON" --doc-text "$STAGING_DIR/bv_doc_text.txt" > /tmp/bv_prompts.json

# Step 2 — for each prompt, spawn an independent Task sub-agent:
#   Task(subagent_type="founder-skills:cap-table", prompt=<the per-field prompt>)
#   subagent_type is REQUIRED — a type-less dispatch silently downgrades to the
#   shell-capable general-purpose agent. Repeat it on every per-field dispatch.
# Collect their {field, value, evidence_quote} responses into /tmp/bv_responses.json
# (wrap as {"responses": [...]}).

# Step 3 — score responses against the original extraction
cat /tmp/bv_responses.json | python3 "$SCRIPTS/backward_verifier.py" --phase=score \
  --extraction "$EXTRACTION_JSON" -o /tmp/bv_report.json --pretty
```

Backward verification is **informational (WARN-mode)** by default — disagreements between original and re-extracted values surface in the report but do NOT block. Present disagreements to the founder via `AskUserQuestion`. Calibration found ~7% disagreement rate on the canonical eval set, dominated by genuinely ambiguous form-classification cases (pre-money vs post-money) — too noisy for auto-rejection but valuable as a confirmation prompt.

**Recommended trigger:** run backward verification on high-stakes extractions — priced rounds, $1M+ investments, or when forward verification was marginal (high `fuzzy_ratio`, many `unverifiable` fields).

## Dispatch Context A — `ARTICLES_OF_ASSOCIATION_EXTRACTION`

For AoA documents, dispatch with the `Task` tool using the invocation below instead of the `INSTRUMENT_EXTRACTION` template above. AoAs define preferred-series structural terms (OIP, liquidation preference, anti-dilution), not investment instruments — they use a dedicated sub-context and route through `extract_aoa.py`, not `extract_instrument.py`. Copy the invocation **whole** — the `subagent_type` is part of it:

```
Task(
  subagent_type="founder-skills:cap-table",   # REQUIRED — omitting it silently downgrades the dispatch to the wildcard, shell-capable general-purpose agent
  prompt="""
CONTEXT: ARTICLES_OF_ASSOCIATION_EXTRACTION
OUTPUT_PATH: <HANDOFF_AGENT>/aoa_extraction_output.json
RUN_ID: <RUN_ID>

You are the cap-table agent dispatched in Context A (ARTICLES_OF_ASSOCIATION_EXTRACTION).
The main thread has provided the Articles of Association document content below. Extract
the per-preferred-series structural terms per your agent body's Context A specification.

Document content:
<paste the document text — for PDFs, this is what the Read tool returned; for a tracked-changes DOCX, this is the `scripts/_docx_text.py "<path>" --extract` accepted-view output (NOT the raw Read-tool view), so the extractor and evidence_verifier share one revision view>

Use your Write tool to write to OUTPUT_PATH exactly the
{extraction_type, fields, confidence, ambiguities} shape. Then return ONLY the
receipt JSON in your final assistant message:
{"status": "complete", "output_path": "<echo of OUTPUT_PATH>"}
Do not write artifacts to disk anywhere else. Do not invoke producer scripts.
"""
)
```

After the sub-agent returns, gate the hand-off per the Context A hand-off protocol in SKILL.md Step 0 (`check_handoff.py`, branch on exit code) before piping.

### Sub-agent response shape (load-bearing — `extract_aoa.py` won't accept other shapes)

```json
{
  "extraction_type": "articles_of_association",
  "fields": {
    "company_name": "Acme Technologies Ltd",
    "jurisdiction_structure": "israeli",
    "section_102_plan_reference": false,
    "drag_along_threshold_pct": 0.66,
    "preferred_series": [
      {
        "series_name": "Series Seed",
        "shares": null,
        "original_issue_price": 1.175,
        "original_conversion_price": 1.175,
        "current_conversion_price": 1.175,
        "issuance_date": "2015-09-01",
        "liquidation_preference_multiple": 1.0,
        "liquidation_preference_type": "non_participating",
        "participation_cap_multiple": null,
        "anti_dilution_protection": "broad_based_weighted_average",
        "ad_cp2_floor": null,
        "ad_a_denominator_basis": null,
        "dividend_rate_percent": 0.08,
        "dividend_cumulative": true,
        "pro_rata_rights": true
      }
    ]
  },
  "confidence": {
    "preferred_series[Series Seed].original_issue_price": {
      "level": "high",
      "evidence_quote": "\"Series Seed Original Issue Price\" means ... US$ 1.1750000",
      "document_location": "page 2, Definitions"
    },
    "drag_along_threshold_pct": {
      "level": "high",
      "evidence_quote": "holders of at least sixty-six percent (66%) of the issued Preferred Shares",
      "document_location": "page 8, Drag-Along"
    }
  },
  "ambiguities": []
}
```

Notes the dispatcher MUST honor:

- **`extraction_type` is the routing key.** Must be `"articles_of_association"` exactly. `extract_aoa.py` rejects any other value.
- **`fields.preferred_series` is the primary extraction target.** Per-series required fields at extraction time (non-null): `series_name`, `original_issue_price`, `original_conversion_price`, `current_conversion_price`. `shares` is always `null` at extraction — populated from cap-table data at ingest.
- **`liquidation_preference_type` enum**: `non_participating | participating | participating_capped`. `participating_capped` requires a non-null `participation_cap_multiple`.
- **`anti_dilution_protection` enum**: `none | broad_based_weighted_average | narrow_based_weighted_average | full_ratchet`.
- **`jurisdiction_structure` enum**: `israeli | delaware`.
- **`confidence` is keyed by dotted path**, not flat field name. Per-series fields use `preferred_series[<series_name>].<field>` (e.g. `preferred_series[Series Seed].original_issue_price`). Top-level fields use the bare field name (e.g. `drag_along_threshold_pct`). Each value is a `{level, evidence_quote, document_location?}` object; `level` ∈ `high | medium | low | absent`.
- **`shares` is intentionally null.** Do not populate it from the document — it comes from the cap table at ingest.
- **`issuance_date` is optional at extraction.** Restatement AoAs commonly amend prior series without reciting the original issuance date; leave null rather than fabricating.
- **Form-template / blank documents** — set fields to `null` and add an `ambiguities` entry; do not fabricate values.

## Pipe through `extract_aoa.py`

The validation script enforces schema, detects Israeli-AoA counsel-review items, and (when `--inputs` is passed) merges the validated `preferred_series` block into `inputs.json`:

```bash
cat "$HANDOFF_DIR/aoa_extraction_output.json" | python3 "$SCRIPTS/extract_aoa.py" \
  --run-id "$RUN_ID" \
  --inputs "$REVIEW_DIR/inputs.json" \
  --source-doc "$DOC_PATH" \
  --pretty
```
<!-- skill-quality-ci: bash-after-subagent-ok -->

`--inputs` is required whenever you want the validated `preferred_series[]` merged into `inputs.json`. Omit `--inputs` to validate-only (receipt still lists counsel items). Use `--replace-existing` if a same-named series is already present in `inputs.preferred_series[]` and you want to overwrite it in place.

## Handling non-zero exit from `extract_aoa.py`

- **Validation errors** (exit 1, `status: "validation_failed"`, `errors` array in stdout): per-field schema violations (wrong enum value, missing required field, OIP ≤ 0, etc.). Show via `AskUserQuestion` and re-extract.
- **Merge conflict** (exit 2, `status: "conflict"`): a series with the same `series_name` already exists in `inputs.preferred_series[]`. Re-run with `--replace-existing` after confirming with the founder, or instruct the sub-agent to rename the conflicting series.
- **Merge failed** (exit 1, `status: "merge_failed"`): `inputs.json` missing or unreadable. Verify `$REVIEW_DIR/inputs.json` exists before re-running.

## Counsel-review items in the receipt

`extract_aoa.py` detects four Israeli-AoA surfaces and emits them in `counsel_review_items[]` in the receipt:

- **`israeli_aoa.drag_along_threshold_below_75_percent`** — drag-along threshold < 75%; Israeli courts have flagged sub-75% thresholds. Severity: `high`.
- **`israeli_aoa.section_102_plan_absent`** — AoA does not reference a §102 plan; company may not yet have the trustee-track plan required before the first employee grant. Severity: `medium`.
- **`israeli_aoa.liquidation_preference_above_1x`** — per-series; explicit multiple > 1.0. Severity: `medium`.
- **`israeli_aoa.full_ratchet_anti_dilution`** — per-series; full-ratchet AD protection. Severity: `high`.

Pay-to-play detection (`anti_dilution.pay_to_play_provision_detected`) is also run at extraction time; if triggered it is persisted into `inputs.json.aoa_findings` and surfaces in `rule_audit.py --phase=post_math`.

After the script exits zero, present any `counsel_review_items` to the founder via `AskUserQuestion` and batch any low-confidence or ambiguous fields into a single confirmation prompt before proceeding to math.
