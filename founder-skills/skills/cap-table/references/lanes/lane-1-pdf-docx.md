# Lane 1 — PDF / DOCX (single instrument)

Typical input: a 5–15 page SAFE, term sheet, convertible note, or option plan.

## Read the document

The main thread reads the source document via the `Read` tool (native PDF support, up to 20 pages per call; longer docs use the `pages` parameter to chunk).

## Dispatch Context A — `INSTRUMENT_EXTRACTION`

Dispatch the cap-table sub-agent via the `Task` tool with the document content inlined.

```
CONTEXT: INSTRUMENT_EXTRACTION
REVIEW_DIR: <absolute path to REVIEW_DIR>
RUN_ID: <RUN_ID>

You are the cap-table agent dispatched in Context A (INSTRUMENT_EXTRACTION).
The main thread has provided the document content below. Extract the
structured terms per your agent body's Context A specification.

Document content:
<paste the document text — for PDFs, this is what the Read tool returned>

Return JSON only — exactly the {instrument_type, fields, confidence, ambiguities}
shape. Do not write artifacts to disk. Do not invoke producer scripts.
```

After the sub-agent returns, apply the [tolerant JSON extraction protocol](../../SKILL.md#skill-execution-model-read-first) to obtain the structured JSON.

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

- **`instrument_type` is the routing key for subtype gates.** Per `extract_instrument.py:434`, accepted subtype values are `convertible_loan_agreement`, `convertible_security`, and the canonical `convertible_note`. To route a YC-style convertible_security through the relaxed gate (waives `day_count_basis` / `maturity_date` / `maturity_default_treatment` / `annual_interest_rate`), set `instrument_type: "convertible_security"`. Setting `instrument_type: "convertible_note"` and putting `subtype: "convertible_security"` inside `fields` does NOT work — the strict gate fires and validation fails on missing convertible_note fields.
- **`confidence` is keyed by `fields` field name**, and each value is a `{level, evidence_quote, document_location?}` object. A bare string like `"confidence": "medium"` is rejected (`extract_instrument.py` will exit non-zero with a clear error rather than crashing on `.items()`). The `level` enum is `high | medium | low | absent` (use `absent` when the document is silent on a field).
- **`evidence_quote` lives inside each `confidence` entry**, NOT as a top-level `evidence` block, NOT as a per-field key inside `fields`. The forward evidence verifier (`evidence_verifier.py`) reads `confidence[fname].evidence_quote` for its three-layer check (`quote_in_doc` / `value_in_quote` / `value_in_doc`).
- **Synthesized fields** (computed/classified rather than extracted — e.g., `id`, derived counts, `extraction_confidence`, the `subtype` stamp itself) do NOT need an `evidence_quote`. The verifier has a built-in skip list (~30 fields) and produces `skipped_synthesized` rather than `fail`.
- **Form-template / unexecuted-counterpart documents** (Word/PDF templates with blank investor name, amount, date) should NOT have placeholder values fabricated. Set the appropriate field to `null` AND add an `ambiguities` entry of the form `{"field": "purchase_amount", "reason": "form template — investor amount blank in source"}`. The main thread will surface to the founder via `AskUserQuestion` rather than pushing fabricated data through the verifier.

## Pipe through `extract_instrument.py`

The validation script enforces schema, runs evidence verification + invariant checks against the source doc, and appends to `instruments.json`:

```bash
cat <<'EXTRACT_EOF' | python3 "$SCRIPTS/extract_instrument.py" \
  --instruments "$REVIEW_DIR/instruments.json" --run-id "$RUN_ID" --pretty \
  --source-doc "$DOC_PATH"
<JSON extracted from sub-agent reply>
EXTRACT_EOF
```

`--source-doc <path>` is the only verification flag you need to pass. **Evidence verification, evidence-verification blocking, and invariant checking are all default ON.** Use `--no-verify` / `--no-verify-blocking` / `--no-invariants` to opt out (rare — typically only for tests or documents the user explicitly marks as unverifiable).

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

If the source document is image-only or DocuSign-overlay (verifier returns `overall_status: "unverifiable_doc"` or `verifier_blind_demoted`), verification cannot run — surface this to the founder and ask for explicit confirmation of the extracted values before commit.

If the extraction surfaced ambiguities or low-confidence fields, present them via `AskUserQuestion` for confirmation before proceeding.

## Optional: backward verification (WARN-mode)

After forward verification passes, you may optionally run backward verification — an independent re-extraction by a fresh sub-agent that catches semantic-confusion errors (right value in source but wrong field; e.g., "Purchase Amount" vs "Aggregate Purchase Amount of all Safes"; pre-money vs post-money form classification). This is separate from forward verification, which catches outright hallucinations.

```bash
# Step 1 — emit per-field re-extraction prompts
python3 "$SCRIPTS/backward_verifier.py" --phase=prompt \
  --extraction "$EXTRACTION_JSON" --source-doc "$DOC_PATH" > /tmp/bv_prompts.json

# Step 2 — for each prompt, spawn an independent Task sub-agent.
# Collect their {field, value, evidence_quote} responses into /tmp/bv_responses.json
# (wrap as {"responses": [...]}).

# Step 3 — score responses against the original extraction
cat /tmp/bv_responses.json | python3 "$SCRIPTS/backward_verifier.py" --phase=score \
  --extraction "$EXTRACTION_JSON" -o /tmp/bv_report.json --pretty
```

Backward verification is **informational (WARN-mode)** by default — disagreements between original and re-extracted values surface in the report but do NOT block. Present disagreements to the founder via `AskUserQuestion`. Calibration found ~7% disagreement rate on the canonical eval set, dominated by genuinely ambiguous form-classification cases (pre-money vs post-money) — too noisy for auto-rejection but valuable as a confirmation prompt.

**Recommended trigger:** run backward verification on high-stakes extractions — priced rounds, $1M+ investments, or when forward verification was marginal (high `fuzzy_ratio`, many `unverifiable` fields).
