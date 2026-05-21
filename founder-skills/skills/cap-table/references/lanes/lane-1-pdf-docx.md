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
