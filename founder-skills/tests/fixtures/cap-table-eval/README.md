# Cap-Table Eval CI Fixtures

Synthetic, structurally-mutated extraction inputs + canonical labels for CI.
All fixtures are public-safe (anonymized; no real founder/company names).

Each fixture pair is `<scenario>__source.txt` (synthetic doc body) and
`<scenario>__label.json` (canonical extraction). Tests in
`test_extraction_eval_harness.py` run the production extractor over the
source and assert the result matches the label.

## Scenarios

### `template_blank_exclusivity`
Term sheet draft with an unfilled `__ days` exclusivity placeholder. The
Template-blank hallucination archetype: model invents "45 days" where the doc
literally has a blank. Canonical: `exclusivity_days = null` + ambiguity.

### `cap_plus_discount_clean`
A standard post-money SAFE with $20M cap + 80% discount rate. Canonical
extraction should produce form=`cap_plus_discount`.

### `pre_money_cap_only_legacy`
A legacy YC pre-money SAFE: "Valuation Cap is $10M", "Safe Capital Stock"
terminology. Canonical: form=`yc_premoney_cap_only`,
pre_money_valuation_cap=$10M.

### `gotcha3_multiplier_form_safe`
SAFE with `"Discount Rate is 80% (i.e., 20% discount)"`. Gotcha #3 trap.
Canonical: discount_multiplier=0.80, NOT 0.20.

### `gotcha3_rate_form_note`
Convertible note with `"discount equal to 25%"`. Canonical:
discount_multiplier=0.75 (rate-form: 1 - 0.25).

### `ita_section_3j_cla`
Israeli CLA referencing Section 3(j). Canonical: annual_interest_rate=null,
interest_rate_type=`statutory_ita_section_3j`.
