# Sprint 1.7 Audit Summary (anonymized)

A systematic audit of an LLM-generated label set used for evaluating the
cap-table extraction skill, conducted in May 2026. The label set covers 69
private legal instruments (SAFEs, convertible notes, articles of association,
term sheets, and cap-table workbooks). Documents and labels themselves are
private; this summary records only the counts and failure classes for future
sprint context.

## Results

| Category                                                  | Count |
|-----------------------------------------------------------|------:|
| Labels audited                                            | 69    |
| Confirmed value hallucinations                            | **1** |
| Non-canonical form enum strings                           | **17**|
| Evidence-quote unverified (PDF extraction limitations)    | ~144  |
| Substantive errors after extraction-artifact filtering    | **0** (beyond the 1 hallucination above) |

## Failure classes (one fixture each in this directory)

1. **Template-blank fill** (`cap_table_eval_hallucination_template_blank.json`) —
   1 case. Model invented a numeric default ("45 days") for a draft term sheet
   blank that literally reads "During a period of  days" (two spaces, no number).
   Archetypal case for Sprint 2's evidence_verifier value-token check.

2. **Non-canonical enum invention** (`cap_table_eval_enum_invention.json`) —
   17 cases. Model returned descriptively-correct SAFE form enum strings
   ("post_money_cap_and_discount", "discount_only", etc.) outside the canonical
   set in `SAFE_FORM_GATES` (extract_instrument.py). Remap table embedded in the
   fixture; corrected via auto-canonicalization with audit trail.

## PDF extraction limitations surfaced (for Sprint 2 design)

The ~144 unverified evidence quotes resolved to 8 distinct extraction artifact
patterns, none of which were value errors:

- CID-encoded PDF (font subset → pdfplumber returns tokens)
- Image-only PDFs (no text layer)
- Space-stripping (run-together words: `is80%`)
- Hyphenation across line breaks
- Footnote markers attached to numbers
- Handwritten / form-fill fields not in text layer
- XLSX cell-reference style quotes (descriptive, not verbatim text)
- Non-Latin script segments

Sprint 2's `evidence_verifier.py` design must handle all 8.

## Aggregate accuracy

After filtering extraction artifacts, the LLM-labeled set was ~99.9%
substantively correct on a 645+ informative-field corpus. Validates LLM-
subagent labeling as a viable ground-truth methodology when paired with
programmatic evidence-quote verification.
