# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- **New skill: `cap-table`.** Extracts structured terms from cap-table source documents (SAFEs, convertible notes, term sheets, articles of association, Carta/Pulley XLSX exports), runs them through a layered math pipeline (cap state → SAFE/note conversions → option-pool top-up → anti-dilution → priced-round solver → flip scenarios), and produces a counsel-handoff packet + human-readable report. Designed for founders preparing for priced rounds, secondary sales, or jurisdiction flips.

  Three extraction lanes share a common validator (`extract_instrument.py` / `extract_cap_table.py`):

  - **Lane 1** — Unstructured instruments (PDF/DOCX SAFEs, convertibles, term sheets). Sub-agent extracts; the validator enforces form-dependent required-field gates, normalizes the discount-rate multiplier-vs-rate trap, and routes warrants / non-instruments to clean classification rather than forcing them into a SAFE shape.
  - **Lane 2** — Carta XLSX exports. Verified against real Carta exports across multiple companies; sheet-name fingerprint, Convertible Ledger parsing, discount normalization, and cancelled-record skipping.
  - **Lane 3** — Freeform spreadsheets. Sub-agent identifies cell semantics; validator gates per-field confidence.

  A four-layer verification stack runs by default on every Lane-1 extraction (`extract_instrument.py --source-doc <path>` — verification flags all default-on; use `--no-<flag>` to opt out):

  - **Forward verification** (`evidence_verifier.py`) — three-layer check (`quote_in_doc` / `value_in_quote` / `value_in_doc`) catches the hallucination class where the model fabricates a value not present in the source. Calibrated against a private eval set at 3.6% FPR / 100% TPR on verifiable docs. Handles 8 PDF extraction-artifact patterns: CID-encoded fonts, image-only PDFs, space-stripping, hyphenation across line breaks, footnote markers, DocuSign overlays, non-Latin scripts, XLSX cell-reference quotes.
  - **Invariant checking** (`invariant_checker.py`) — per-field real-world bounds (SAFE `purchase_amount` ≤ $50M; `discount_multiplier ∈ [0.5, 1.0]`; note `annual_interest_rate ≤ 20%`; etc.) plus cross-field math invariants (`options_granted ≤ total_authorized`; SAFE pre/post-money caps mutually exclusive; term-sheet `pre + investment ≈ post` within 2%). Hard math impossibilities block; soft bounds warn-only. 0% FPR against canonical labels; 63% TPR on ×1000 unit-error perturbations.
  - **Deterministic backstop extractors** for SAFEs (`extractors/safe/`): regex-based `purchase_amount`, `discount_multiplier`, `valuation_cap`, `issuance_date`, `investor_name`. Span-preserved via the `FieldExtraction` / `SourceSpan` types in `extractors/types.py`. `discount_multiplier` refuses to decide the multiplier-vs-rate semantic when tiered or conditional clauses are present (emits ambiguity signals instead). `valuation_cap` handles hybrid-terminology SAFEs where the defined term is bare "Valuation Cap" but the Safe Price / Liquidity Price formulas reference "Post-Money Valuation Cap".
  - **Cross-check** (`cross_checker.py`) — pipes sub-agent extractions and deterministic backstops through a demote-only confidence modulator. Agreement never bumps; disagreement demotes one level (`high → medium → low → absent`). Ambiguity-tagged backstop results treated as non-disagreement. Informational — never blocks.

  Optional fifth layer dispatched by the SKILL.md when warranted:

  - **Backward verification** (`backward_verifier.py`) — two-phase CLI (`--phase=prompt` → `--phase=score`) that catches semantic-confusion errors (right value, wrong field; e.g., extracting cap from a referenced prior SAFE instead of the current one) via fresh-sub-agent re-extraction. WARN-mode by default; ~7% disagreement rate against canonical labels makes it valuable as a confirmation prompt for high-stakes fields but too noisy for auto-rejection.

  The receipt surfaces an `attention_needed_fields[]` array (union of low-confidence fields, soft invariant warnings, unverifiable evidence fields, and cross-check disagreements) that the dispatching agent uses to scope `AskUserQuestion` escalation and optional backward verification.

  Math producers cite a `rule_id` from `cap-table-rules.json`. The two-phase `rule_audit.py` writes a gating block before math runs and composes watchlist + counsel items after. Counsel-handoff packet is a standalone deliverable; the compose-report stage assembles `report.md` + `report.json` with an embedded `coaching_payload` block (schema `v0.5.0-cap-table`).

  Self-contained HTML output: `visualize.py` produces a report dashboard with inline SVG charts (no CDN); `explore.py` produces an interactive scenario picker (vanilla JS).

  Six anonymized synthetic source/label pairs ship as public CI fixtures under `founder-skills/tests/fixtures/cap-table-eval/`, covering the template-blank hallucination archetype, canonical SAFE forms, legacy YC pre-money form, the multiplier-vs-rate discount trap, and the ITA Section 3(j) statutory-interest case. The `test_eval_harness.py` fixture runs these in CI; an `EVAL_DATA_PATH` env-var override enables an additional regression pass against a private 69-doc corpus locally.

### Added

- **`cap-table`: convertible-instrument aliases (CLA + convertible_security).** Commit #6 of the post-J audit sweep. `extract_instrument.py` now accepts two new `instrument_type` values in addition to the standard six:
  - `convertible_loan_agreement` — Israeli CLA / CIA (GKH / Herzog / Meitar templates with "Investment Amount" / "Investors" terminology). Mathematically identical to a standard convertible note; routes through the same `validate_note` gate with full canonical fields required.
  - `convertible_security` — YC's pre-SAFE convertible security form (GS-Cap Table etc.). SAFE-equivalent: no interest, no maturity. Per-subtype gate via `CONVERTIBLE_SUBTYPE_GATES["convertible_security"]` waives `maturity_date`, `maturity_default_treatment`, `day_count_basis`, and `annual_interest_rate` (any may be null). Defaults `interest_rate_type` to `"none"` when extraction left it unset.

  Both types normalize to canonical `instrument_type=convertible_note` on storage, with the original classification preserved in the new `subtype` field for provenance. Math producers (`note_conversion.py`) consume the canonical shape regardless of subtype; subtype informs counsel-review framing ("Israeli CLA terms..." vs "convertible security (SAFE-equivalent)..."). `instruments.schema.json` notes block extended: `subtype` enum added; `maturity_date`/`maturity_default_treatment`/`day_count_basis`/`qualified_financing_threshold` moved from strict `required` to optional with `null` allowed (subtype gates now enforce them where applicable, replacing the schema-level requirement).

  Agent body updated: enum mapping table directs CLAs → `convertible_loan_agreement`, YC convertible securities → `convertible_security`, with field-population guidance per subtype. Israeli statutory ITA Section 3(j) interest stays at `interest_rate_type="statutory_ita_section_3j"` + `annual_interest_rate=null`.

  Test coverage: 5 new tests in `TestExtractInstrument` — CLA subtype validates as standard note; convertible_security waives maturity; unknown subtype falls back to standard gate; end-to-end CLI routing for CLA (lands in instruments.notes[] with subtype tag); end-to-end CLI routing for convertible_security (null maturity preserved). 1,454 tests pass total.

  **Eval calibration deferred.** The 10 real convertibles at `~/private-corpus/convertible/` (Acmecorp CLA 2014/2019, Hotelcorp note, Foxtrotcorp convertible_security, Golfcorp bridge + promissory, Indiacorp, Julietcorp, plus others) are NOT processed in this commit — calibration via opus subagent dispatch is tracked as a follow-up. The synthetic-fixture tests cover the validator logic; eval calibration verifies extraction accuracy against real PDFs.

- **`cap-table`: fast-assess entry mode.** New `scripts/quick_assess.py` produces a 1-page founder-facing markdown report in under 60 seconds for conversational queries that don't need the full 13-step pipeline. Writes to a separate `cap-table-{slug}-fastassess/` directory (single-dash suffix, pinned for `find_artifact.py` slug-parser compatibility) containing only `report_fast_assess.md` + a `fast_assess_only.json` sentinel. Sentinel contract documented at `references/sentinel-schema.md` with JSON Schema at `references/schemas/fast_assess_only.schema.json`. The sentinel carries `inputs_fingerprint` (sha256 of founder prompt + attached doc paths), `rule_pack_version`, denormalized `headline_data` mirroring `coaching_payload` field names, and `produces_canonical_artifacts: false` so future cross-skill consumers (`financial-model-review`, `ic-sim`, `fundraise-readiness`) can detect fast-assess mode and either use the headline data directly or prompt for a full re-run. SKILL.md Step 0 routes between fast-assess and full pipeline based on whether the founder has attached a document or explicitly asked for the full review.
- **`cap-table`: MFN auto-bind to elected SAFE's terms.** When an `yc_uncapped_mfn` SAFE has `mfn_provision.elected_against_safe_id` pointing to a sibling with a resolved cap, the priced-round solver now pre-resolves the election (inherits form + cap + discount) before iteration. Previously required a `conversion_price_override` even when MFN election was unambiguous — needless friction. Truly uncapped MFNs (no election, or unresolvable election chains) still hit the cycle guard correctly (Gotcha #4).
- **`cap-table`: pool-basis clarifying question.** When `option_pool.required_topup` runs with `target_basis="pre_money"` and the existing pool already meets the target (silent 0-topup no-op), the script now emits a structured `clarifying_question` in the receipt. The dispatching agent escalates via `AskUserQuestion` so the founder confirms whether they meant literal pre-money basis (no top-up) or industry-norm post-close unallocated (real top-up). Phase M+S — addresses the eval-3 ambiguity finding.
- **`cap-table`: watchlist active vs for-reference split.** Founder-facing `report.md` now splits the date-sensitive watchlist into "Active" (rules whose `applies_when_matched=true` for this engagement) and "For-Reference Annotations" (rules that don't apply in the current state but are tracked in case the engagement evolves). Founders no longer see 50 unfiltered items including inapplicable Israeli rules in a Delaware-only engagement.
- **`cap-table`: structural_only completeness legibility.** The per-scenario `**Completeness:**` line in `report.md` now expands the bare enum value into a plain-language explanation (e.g., `structural_only` becomes "schema and rule-applicability checks passed, but no share-producing math ran"). Founders previously saw "0 blockers, converged" and didn't register that legal/tax math wasn't modeled.

### Fixed

- **`cap-table`: math edge cases + privacy false-positive (post-J audit cleanup).** Bundle of small fixes surfaced by the 5-reviewer + 1-meta-reviewer audit:
  - **MFN chain auto-bind (was single-hop).** `_resolve_mfn_elections` now iterates to a fixed point, so A→B→C MFN chains resolve transitively. Bounded by `len(safes)` iterations. Previously a chain where B itself hadn't resolved yet on the first pass would leave A unresolved and cause `E_SAFE_REQUIRES_CONVERSION_EVENT` even when the chain ultimately anchored at a capped SAFE.
  - **`_mfn_inherited_from` provenance propagation.** The shadow record's inheritance marker now flows through to the `per_safe` result so downstream counsel-review reporting can phrase "Investor X's MFN-inherited terms from Investor Y."
  - **Privacy assertion word-boundary + length threshold.** `_assert_coaching_payload_privacy_clean` previously used a bare substring `in` check with length threshold >2, which caused false positives on short / common investor-name fragments ("SAFE", "Inc", "Capital", "LLC") inside legitimate template prose (e.g., `branch_summary="cap_plus_discount"`). Now uses `\b` regex with `re.escape(name)` and raised the threshold to >8 chars. Genuine investor names like "Sequoia Capital Operations" still fire correctly.
  - **`option_pool` ZeroDivisionError guard (M7).** Library callers passing `pre_topup_fully_diluted_shares=0` would crash in the warning's `existing / pre_fd` format string. Now guarded.
  - **`option_pool` clarifying_question gating (M8).** The "pool target already met" clarifying_question now only fires when the post-money interpretation produces a NONZERO top-up. If both pre-money and post-money interpretations yield 0 (pool is legitimately oversized), the warning is noise — now suppressed.
  - **`priced_round.py` docstring corrected (M6).** Removed false claim about a "closed-form path" that never existed in code. Iteration runs always; convergence is typically 3-7 iterations.
  - **`priced_round.py` defensive `rel_change` init (R4 LOW.a).** Initialize `rel_change = float("inf")` so degenerate `max_iterations=0` doesn't NameError when reporting non-convergence.
  - **`compose_report.py` defensive `computed_outputs` get (R4 LOW.b).** `failed_items` collection now uses `s.get("computed_outputs", {}) or {}` matching the convention elsewhere in the file; previously would KeyError if a scenario lacked the field.
  - **`quick_assess.py` driver sign convention (R4 LOW.c).** `headline_data.drivers[].impact_pct` now emitted as positive dilution magnitudes (not sign-flipped negatives that the renderer un-negated). The sentinel JSON exposed to external consumers now agrees with the markdown display.

  Test coverage: +11 new tests across `TestStackedPostMoneySAFEsGolden` (3-hop MFN chain, missing election target, inheritance provenance), `TestOptionPool` (clarifying-question positive + negative + suppression + pre_fd=0 guard), and new `TestPrivacyAssertion` class (positive leak detection, clean passthrough, short-name false-positive prevention, word-boundary substring check). 1,446 tests pass total. Rule pack bumped 0.3.0 → 0.3.1 (a `safe.pre_money_cap_conversion` rule was added in the prior commit).

- **`cap-table`: pre-money (legacy) SAFE form dispatch — math regression introduced by post-money fix.** The earlier post-money fix (commit `8642db5`) corrected math for current YC SAFEs but applied the same denominator-handling universally — `convert_safe_priced_round` was rejecting pre-money form SAFEs (`yc_premoney_cap_only`, `pre_money_cap_and_discount_legacy`) at the cap branch because they have `post_money_valuation_cap=None`. Pre-Oct-2018 YC SAFE conversions silently failed with `E_SAFE_REQUIRES_CONVERSION_EVENT`. Fix: route `convert_safe_priced_round` on `form` to pick the correct cap field and denominator. Post-money forms use `post_money_valuation_cap / company_capitalization` (post-money FD); pre-money (legacy) forms use `pre_money_valuation_cap / pre_money_fd` (pre-financing FD, constant). The two SAFE families produce materially different cap tables: post-money locks `purchase/cap` of post-money; pre-money locks `purchase/cap` of pre-money and dilutes with new money + pool refresh. Verified via independent first-principles triangulation: for the canonical scenario (10M founders + 1M pool, $500k @ $5M cap, $5M Series A at $5M pre), pre-money math produces founder 41.32% / safe 4.55% / new money 50%, materially different from the post-money form's founder 36.36% / safe 10% / new money 50%. New golden tests at `tests/test_cap_table.py::TestLegacyPreMoneySAFEs` (3 tests including a mixed-form scenario that exercises form-dispatch routing). Rule pack `safe.pre_money_cap_conversion` added (v0.3.1) with full formula + YC primer source citation + multi-SAFE denominator ambiguity note. RULE_PACK_VERSION bumped 0.3.0 → 0.3.1 atomically across 8 math producers.

- **`cap-table`: math correctness for stacked YC post-money cap SAFEs.** Prior pre-release behavior over-stated founder ownership by ~6 percentage points on a routine Series A with three stacked post-money cap SAFEs. Root cause: `priced_round.py` passed the pre-financing fully-diluted snapshot as `company_capitalization` to `safe_conversion.convert_safe_priced_round`, which applied the pre-money YC SAFE formula (`cap_price = cap / pre_fd`) to post-money instruments. Each post-money SAFE's locked ownership must be `purchase_amount / post_money_valuation_cap` of the FULL post-money FD (the YC primer's marketing identity, equivalent to `safe.stacked_post_money_caps` in the rule pack); the bugged denominator under-allocated SAFE shares by `1 - new_money_pct`. Fix: solver now iterates `company_capitalization` toward the converged post-money FD (including new-money shares). Verified against a 4-way triangulation (two independent opus reviewers, a baseline subagent's first-principles derivation, and a dedicated triangulation subagent) — all four arrive at the same golden values: founder 53.33% / aggregate SAFE 16.67% / PPS $1.3333 / total post-money FD 18,750,000 for the canonical eval-2 scenario. Golden test coverage at `tests/test_cap_table.py::TestStackedPostMoneySAFEsGolden` (7 tests including ownership-sum-to-1 cross-check and aggregate-equals-sum-of-per-safe assertion). Rule pack bumped 0.2.8 → 0.3.0 with a clarifying note on the load-bearing identity to prevent re-implementers from replicating the same denominator confusion. Math producers' `RULE_PACK_VERSION` constants updated atomically.

### Changed

- **`cap-table`: agent body sync (H5 enum + H6 privacy + H7 inline-Context-B + M4 type literals).** Post-J audit cleanup. (1) **H5 enum collapsed to validator-accepted set**: dropped `convertible_loan_agreement`, `convertible_security`, `spa`, `articles_of_association` from `agents/cap-table.md:376` `INSTRUMENT_EXTRACTION` return shape. The validator (`extract_instrument.py:361`) only accepts {safe, convertible_note, term_sheet, option_plan, warrant, non_instrument}; the prior 4 extra values silently died at validation. Added enum mapping table directing Israeli CLAs → `convertible_note`, convertible_security → `convertible_note` with `interest_rate_type=none`, SPAs → `term_sheet`. AoA dispatch path deferred to commit #7 with its own ARTICLES_OF_ASSOCIATION_EXTRACTION sub-context; ~60 lines of stale AoA extraction guidance (corpus-derived 8-point list + AoA return shape JSON) removed from the agent body to be rebuilt against the schema-canonical field names in #7. (2) **H6 privacy assertion extended to founder names**: `_assert_coaching_payload_privacy_clean` now takes an `inputs` parameter and walks `inputs.founders[].name` in addition to `instruments.{safes,notes}[].investor_name`. Two carve-outs prevent false positives: company-name overlap (founder "Acme Holdings Founder Trust" at "Acme Holdings"), and founder-becomes-investor (common in Israeli market — founder anchors their own SAFE round; treated as investor for the duplicate-name check). Agent body's privacy boundary claim narrowed from "investor + founder + document text" to "investor + founder" (document text isn't structurally in the payload). (3) **H7 inline-Context-B acknowledgment**: agent body Context B intro now explicitly permits the inline execution path (privacy enforced at compose time regardless of dispatch). (4) **M4 integer-typed return-payload fields un-quoted**: `agents/cap-table.md:567` template was emitting `"scenarios_modeled": "<number>"`; literal-minded sub-agents would return strings. Now `<integer>` placeholder convention; added a type-literal note.

  Test coverage: 3 new tests in `TestPrivacyAssertion` (founder name leak detection, company-name carve-out, founder-becomes-investor carve-out). 1,449 tests pass total.

- **`cap-table`: Pulley XLSX path scoped down.** Removed Pulley promises from the SKILL.md description, `when_to_use`, Lane-2 reference, Carta/Pulley vendor doc, and trigger-eval queries until a real Pulley XLSX is available to verify mappings against. `--mode=pulley` remains a stub returning a structured blocker routing to `--mode=freeform`. Don't promise what we don't ship.
- **`cap-table`: Context B (POST_COMPOSE_COACHING) inline alternative.** The fresh-sub-agent dispatch contract for Context B coaching commentary was load-bearing for context isolation (preventing Context A verifier bleed) but not strictly required for privacy (the `coaching_payload` is already scrubbed by `build_coaching_payload`). SKILL.md Step 11 now explicitly permits inline execution as an alternative, with the privacy boundary enforced at compose time via a new `_assert_coaching_payload_privacy_clean()` assertion in `compose_report.py` that walks every string in the payload and asserts no investor names from `instruments.json` leak through. Defense-in-depth; fires regardless of dispatch path.

## [0.4.7] - 2026-05-19

### Fixed

- **`competitive-positioning`: sub-agent had no network tools but was dispatched to research competitors.** SKILL.md Steps 4 (LANDSCAPE_RESEARCH), 5a (MOAT_SCORING), and 5b (POSITIONING_SCORING) dispatch the sub-agent with prompts asking for `evidence_source: researched | agent_estimate` (and Step 5a's `trajectory: building/stable/eroding`, which is inherently research-dependent). The agent's `tools:` allowlist was `["Read", "Edit", "Glob", "Grep"]` — no network access — and Step 4 explicitly forbade the main thread from doing the research either. Net effect since the skill shipped: every `evidence_source: "researched"` stamp was a training-cutoff guess wearing a research label. CHECKLIST (Step 6) is unaffected (artifact grading only, no research).

### Changed

- **`competitive-positioning` agent now declares `WebSearch`** in its `tools:` allowlist. Cowork's named-sub-agent dispatch is strict allowlist mode — empirically verified via a probe (a sub-agent declared with `tools: [Read, Edit, Glob, Grep]` receives exactly those four names; no MCP leakage, no default-toolset injection). With `WebSearch` declared, Phase A enrichment, moat trajectory scoring, and positioning-axis evidence become honest.
- **`competitive-positioning` SKILL.md dispatch prompts** (Steps 4, 5a, 5b) now reference `WebSearch` explicitly. The "Do not do the landscape research yourself in the main thread" instruction in Step 4 is retained — research now runs in the sub-agent's isolated context, where it belongs. Phase B (gap detection) is also instructed to use `WebSearch` for discovering missing competitor categories.
- **Producer-script JSON schemas unchanged.** The dishonesty was upstream of `validate_landscape.py` / `score_moats.py` / `score_positioning.py`; the schemas themselves were always correct.

### Added

- **`tests/test_cowork_invariants.py::test_research_agents_declare_websearch`** — new regression detector. Agents in `_AGENTS_REQUIRING_WEBSEARCH` (currently `{"competitive-positioning"}`) must declare `WebSearch`. Future refactors that strip it from the allowlist will fail CI. The docstring of `test_agent_declares_no_dangerous_tools` is updated to reflect that the "all agents declare exactly Read/Edit/Glob/Grep" property no longer holds — WebSearch is an intentional addition.

### Notes

- The fix corrects a real defect but the diff is small (one `tools:` addition + four dispatch-prompt clarifications). The original v0.4.7 plan considered the "main-thread does research, sub-agent structures the data" pattern used by `market-sizing` and `ic-sim`, but a sub-agent probe in Cowork (`/tmp/cowork-tool-probe/` locally) settled that `WebSearch` *is* available to sub-agents — only `WebFetch` (the plain name; `mcp__workspace__web_fetch` IS available) and `Bash` (replaced by `mcp__workspace__bash` in the default sub-agent toolset, not via deferred MCP tier as the allowlist file's comment suggested) follow the documented exclusion model. A separate follow-up will correct the false-premise comments in `cowork_async_subagent_filter.py` and the sibling skill docs.
- **No artifact schema bump.** `schema_version` strings for competitive-positioning artifacts are unchanged — consumer plugins downstream of this skill will not see a version-pin break.

## [0.4.6] - 2026-05-13

### Fixed

- **`market-sizing`: non-canonical `existing_claims` keys silently bypassed deck-vs-computed reconciliation.** When a deck stated TAM/SAM/SOM figures under non-canonical keys (e.g., `SAM_Israel_only`, `TAM_global`), both the `DECK_CLAIM_MISMATCH` warning and the report's provenance section's `deck_claim` / `delta_vs_deck_pct` columns silently returned `None` — `compose_report.py` and `visualize.py` look up `tam`/`sam`/`som` by exact lowercase name via `dict.get()`. The skill produced a complete report with no signal that comparison had been short-circuited, allowing downstream framing to treat a missing deck figure as a wrong deck figure.

### Added

- **`EXISTING_CLAIMS_SHAPE` warning** (medium severity, code #17 in `compose_report.py validate_artifacts()`) surfaces non-canonical keys or non-dict types in `inputs.existing_claims`. Acceptable via `accepted_warnings`; does not block the report.
- **`existing_claims_detail` field** in `inputs.json` — escape hatch for deck claims that don't fit the canonical `{tam, sam, som}` flat shape (regional sub-SAMs, time-anchored figures, alternative TAM frames). Documented in `artifact-schemas.md`; rendered as a new "Deck Claims (Narrative)" sub-section in the report (between sizing-table and assumptions). Does NOT participate in reconciliation.
- **`deck_coverage` field** in `coaching_payload` — nullable structured signal indicating which canonical figures the deck stated vs left null. Shape: `null` when no canonical figure was stated, otherwise `{"deck_reviewed": true, "stated": [...], "missing": [...]}`. Additive in `v0.4.2-market-sizing` (schema_version unchanged — three literal pins would break for zero consumer benefit).
- **Coaching framing guidance** in `agents/market-sizing.md` and `SKILL.md`: when `deck_coverage.missing` is non-empty, frame as "deck should also show {missing}" — explicitly NOT "understatement." When `EXISTING_CLAIMS_SHAPE` is present, do not trust `deck_coverage = null` as "deck wasn't reviewed"; branch coaching around the warning and the new narrative section instead.
- 21 new regression tests in `tests/test_market_sizing.py`: 10 `EXISTING_CLAIMS_SHAPE` cases (incl. non-dict types, uppercase canonical, canonical-null happy path), 2 `_compute_provenance` lock-in tests with tripwire docstrings documenting the contracted division of labor (warning = shape signal; provenance = numerical signal, stays neutral on shape errors), 3 narrative renderer cases, 6 `deck_coverage` cases.

### Changed

- `SKILL.md` heredoc template for `inputs.json` writes `"existing_claims": {"tam": null, "sam": null, "som": null}` + `"existing_claims_detail": null` (was `"existing_claims": {}`). Backward-compatible: empty-dict legacy templates continue to pass without warning.
- `WARNING_SEVERITY` totality test updated 19 → 20 codes.

## [0.4.5] - 2026-05-10

### Added

- **Skill-quality CI** — new GitHub Actions workflow `.github/workflows/skill-quality.yml` runs three layers, ordered by speed:
  1. **Contract tests** (per-PR): SKILL.md frontmatter invariants enforced via YAML parse (`user-invocable: true` present, `disable-model-invocation` absent, braced `${CLAUDE_PLUGIN_ROOT}`); per-agent persistence-tool-name compatibility against Cowork's sub-agent tool registry; sub-agent-cue-followed-by-bash-block regression detector; SKILL.md does-not-depend-on-SessionStart-hook invariant (Cowork plugin hooks don't fire).
  2. **Compose invariants** (per-PR): every skill's `compose_report.py` emits a structured `coaching_payload` block; `STALE_ARTIFACT` warning surfaces on mismatched `metadata.run_id` across artifacts. Compose invocations are dispatched via a registry (`compose_invocations.py`) so per-skill CLI variation doesn't leak into test bodies.
  3. **End-to-end smoke** (`deck-review-e2e-smoke`): `deck-review` runs against a synthetic seed-stage fixture deck via `claude-agent-sdk`. Asserts artifact existence, schema validity, score in expected range, `run_id` parity, `coaching_payload` shape. Triggered on `push: tags: ['v*']` and `workflow_dispatch`; not on `pull_request`. See "Release Process" in CLAUDE.md for the opt-in dispatch list and the required tag → wait-for-green → sync ordering.
- `founder-skills/tests/cowork_async_subagent_filter.py` — tool-name compatibility check against Cowork's sub-agent tool registry. The desktop-side scope exclusion removes 5 tool names (`Bash`, `NotebookEdit`, `REPL`, `JavaScript`, `WebFetch`) from the registry before the CLI's filter runs; `Bash` is replaced by `mcp__workspace__bash`. Names that DO resolve in sub-agent contexts (`Read`, `Edit`, `Glob`, `Grep`, `WebSearch`, etc.) are listed in `COWORK_ASYNC_SUBAGENT_ALLOWLIST`.
- Synthetic deck fixture and golden expected-output under `founder-skills/tests/fixtures/` for the deck-review e2e smoke and compose-invariant tests.
- `claude-agent-sdk==0.1.80` pinned in dev dependencies (pre-1.0 SDK with API churn).
- `pythonpath = ["founder-skills/tests"]` added to `[tool.pytest.ini_options]` so test files can import sibling helper modules by bare name.

### Changed

- `pyproject.toml` `version` aligned with `plugin.json` (earlier drift between the two is fixed).
- `ci.yml` test job scoped to `-m "not e2e"` to prevent the deck-review e2e smoke from running twice per PR.
- `deck-review`, `financial-model-review`, `ic-sim`, and `competitive-positioning` SKILL.md files: added `<!-- skill-quality-ci: bash-after-subagent-ok -->` suppression markers above the legitimate coaching-payload extraction blocks so the regression detector doesn't false-positive on them.
- **`deck-review-e2e-smoke` moved from per-PR push to tag-push + workflow_dispatch.** Runs on every release tag and is opt-in via manual dispatch for architectural-surface PRs. Tag-time preflight verifies the tag matches both `pyproject.toml` and `founder-skills/.claude-plugin/plugin.json` (fails in <5 sec). See CLAUDE.md "Release Process" for the required tag → wait-for-green → `sync-test-repo.sh` ordering and the opt-in dispatch trigger list.

### Notes

- **e2e wall time:** 5-20 min per run depending on LLM dispatch decisions.
- **e2e auth: three paths supported.** The smoke test accepts any of:
  1. `ANTHROPIC_API_KEY` env var
  2. `CLAUDE_CODE_OAUTH_TOKEN` env var (subscription via long-lived token from `claude setup-token`; set as `CLAUDE_CODE_OAUTH_TOKEN_CI` repo secret if you choose this path)
  3. Local subscription auth: macOS Keychain entry `Claude Code-credentials` (after `claude /login`) or `~/.claude/.credentials.json` on Linux/Windows — for local dev only; not applicable in CI.
  The workflow env-injects both `ANTHROPIC_API_KEY_CI` and `CLAUDE_CODE_OAUTH_TOKEN_CI` if set; whichever is present is used. Configure exactly one in repo secrets.

## [0.4.4] - 2026-05-09

### Removed

- `scripts/verify-cowork-clone.sh` — superseded by [`claude-plugin-doctor`](https://github.com/yaniv-golan/claude-plugin-doctor) (`cpd`), which diagnoses drift across all six cache layers instead of just the marketplace clone HEAD. Install with `npm install -g claude-plugin-doctor`.

## [0.4.3] - 2026-05-09

### Highlights

Skill, plugin, and dev-workflow alignment with the documented Claude Code v2.1.131 + Desktop v1.6259.1 contracts. Fixes a fragile env-var pattern in 3 skills, migrates inert custom frontmatter into body documentation, and adds CI-level manifest validation plus a script that catches Cowork's silent-marketplace-refresh trap.

### Fixed

- Bare `$CLAUDE_PLUGIN_ROOT` (no braces) in fenced bash blocks across `deck-review`, `ic-sim`, and `market-sizing` SKILL.md files — these resolved only at Bash subprocess time and depended on `CLAUDE_ENV_FILE` being sourced into the shell, which Claude Code does not document as a guarantee for skill subprocesses. Switched all 10 occurrences (deck-review×3, ic-sim×3, market-sizing×4) to `${CLAUDE_PLUGIN_ROOT}` (braced form), which the plugin content expander substitutes at skill load time. `session-setup.sh` stays as defense-in-depth.
- `competitive-positioning/scripts/` was silently missing from CI's typecheck matrix despite having Python files alongside the other four skills.

### Added

- `claude plugin validate` runs in CI on every PR, catching plugin and marketplace manifest drift before users hit it. CLI pinned to exact v2.1.138.
- `founder-skills/tests/test_skill_contract.py` — regression tests enforcing: only `${CLAUDE_PLUGIN_ROOT}` (braced) in skill bodies; only documented frontmatter keys; `when_to_use` declared on every skill; description+when_to_use within both per-skill (1,536-char) and total (6,000-char) listing budgets.
- `scripts/verify-cowork-clone.sh` — verifies the Cowork marketplace clone advanced to upstream HEAD after a Refresh. Cowork's marketplace refresh can return success and bump `known_marketplaces.json#lastUpdated` without the local git clone actually advancing — silent `git pull` failures are absorbed when `CLAUDE_CODE_PLUGIN_KEEP_MARKETPLACE_ON_FAILURE` is set or by the SSH↔HTTPS transport fallback. bash 3.2-compatible, macOS-only, cross-checks `installed_plugins.json` `gitCommitSha` against clone HEAD.
- Explicit `user-invocable: true` on all 5 SKILL.md frontmatters — Desktop's regex scanner reads this key (it doesn't read `disable-model-invocation`), so making the user-invocable intent legible to the scanner is one line of insurance.
- `homepage`, `repository`, `license: Apache-2.0`, `keywords`, and `author.url` in `founder-skills/.claude-plugin/plugin.json` — discoverability metadata surfaced in the Settings UI.
- CLAUDE.md sections covering: SKILL.md conventions (env-vars, frontmatter, the two-parsers / two-discovery-outcomes asymmetry between CLI runtime and Desktop's regex scanner), the marketplace-refresh-verification workflow, and `--plugin-dir` for fast local CLI iteration without going through the marketplace.

### Changed

- Removed inert custom frontmatter (`compatibility`, `metadata`, `imports`, `exports`) from all 5 SKILL.md files. These were silently dropped by the parser and posed a regex-parser fragility risk in Desktop's skill scanner. Migrated to a clearly-labeled `## Skill Metadata` section in each skill body. Plugin version stays in `plugin.json` (single source of truth) — `metadata.version` removed.
- `dev` extras in `pyproject.toml` add `pyyaml` and `types-PyYAML` (for the new SKILL.md frontmatter regression test).

## [0.4.2] - 2026-05-04

### Changed

- **Coaching commentary now reads structured data instead of the full report.** Each skill's `compose_report.py` emits a structured `coaching_payload` block in `report.json` (per-skill schema, with summary stats and failed/warned items). The post-compose coaching sub-agent reasons from this payload directly and inserts `## Coaching Commentary` at a per-run marker (`<!-- COACHING_INSERTION_POINT_<8-hex> -->`) via `Edit`, instead of re-reading `report.md`. Empirical: ~9K tokens saved per coaching run on `deck-review`; larger savings expected on `financial-model-review` (its `report.md` is typically ~3× larger).
- **Producer schema parity across the four checklist-based skills.** `competitive-positioning`'s `checklist.py` now emits a `summary` block with `failed_items`/`warned_items` arrays alongside its existing flat top-level fields (additive — backward-compat preserved). `financial-model-review`'s `failed_items` and `warned_items` entries gain a per-item `severity` (high/medium/low), used to truncate large coaching payloads to the top 15 high + top 15 medium when items exceed 30. `market-sizing` keeps its pass/fail/not-applicable model (no `warn` status). `ic-sim`'s coaching payload uses a distinct dimension-based shape (dealbreakers + concerns) instead of the checklist shape.
- **Tighter coaching-agent integrity checks.** The coaching agent runs an idempotency check before editing — re-running the dispatch against the same review now returns success without duplicating the section. After editing, it verifies all canonical artifacts share the same `metadata.run_id` (using grep-based extraction so the check is robust to where `metadata` sits in each file). The agent matches the *exact* per-run insertion marker — never the prefix substring — so deck content that legitimately contains `<!-- COACHING_INSERTION_POINT_` can't cause a false block.
- **`ic-sim` compose simplification.** Removed the static `## Founder Coaching` section that compose previously generated; the (richer) coaching commentary covers the same ground.
- **Staging files moved to a per-review subdirectory.** Skills that buffer large sub-agent JSON to disk before piping it to a producer script now do so in `$REVIEW_DIR/.staging/` (or the skill-specific equivalent), created at setup.

### Added

- `founder-skills/references/skill-execution-model.md` — committed reference doc explaining how skills run inline in the main thread, when sub-agents are dispatched, the producer-script contract, per-skill payload schemas, and runtime constraints to be aware of. Cross-referenced from each `SKILL.md`.
- Tests covering coaching payload shapes, marker placement and collision handling, severity-sorted truncation, idempotency, and cross-skill dispatch contracts.

## [0.4.1] - 2026-05-03

### Changed

- **Skills run inline in the main thread.** All five skills (`deck-review`, `competitive-positioning`, `financial-model-review`, `ic-sim`, `market-sizing`) drop `disable-model-invocation: true` from their frontmatter. Invoke via the `Skill` tool or the `/<skill-name>` slash command. Heavy analytical steps within each skill dispatch sub-agents (with `Read`/`Edit`/`Glob`/`Grep`) for context isolation; the main thread continues to run the producer scripts that validate and persist canonical artifacts. **BREAKING** for any caller that depended on directly invoking the skill's companion agent — companion agents are now used only as dispatched sub-agents within a skill run.
- **Coaching commentary moves to a post-compose dispatch.** `compose_report.py` now writes `report.md` directly (via `--write-md`); the coaching commentary is then appended by a dispatched sub-agent that reads the report, edits in the commentary, verifies all canonical artifacts on disk, and returns a structured success payload. Replaces the prior pattern of the agent receiving `report_markdown` as JSON and hand-writing the file.
- **Tolerant JSON extraction from sub-agent replies.** Sub-agents may wrap JSON in markdown fences or include prose preambles/footers; the calling skill now robustly extracts the first valid JSON object from the reply.
- **Compose scripts verify outputs after writing.** `compose_report.py` exits non-zero if any declared output file is missing or empty after the run.
- **`deck-review` companion agent split into two dispatch contexts.** Per-step analytical dispatches return JSON matching the producer schemas; the post-compose coaching dispatch returns a structured `{status, review_dir, report_path, score_pct, overall_status, high_severity_warnings}` payload. Tool surface narrowed to `Read`/`Edit`/`Glob`/`Grep`.

### Fixed

- Skills can now run end-to-end on Cowork. Earlier versions broke because Cowork strips `Bash` from sub-agent dispatches at runtime; v0.4.1 inverts the model so orchestration runs in the main thread (where `Bash` is available) and sub-agents handle only work that fits within their (`Bash`-stripped) tool surface.

### Added

- `founder-skills/tests/fixtures/dispatch_contracts.json` and `tests/test_agent_dispatch_contracts.py` — track which sub-agent dispatches each skill makes and what shape each is expected to return; flag drift between agent body documentation and producer-script schemas.
- Per-skill regression tests for compose-script output verification and tolerant JSON extraction.

## [0.4.0] - 2026-05-03

### Changed

- **`deck-review` artifacts are now produced by validating Python scripts.** New scripts (`deck_inventory.py`, `stage_profile.py`, `slide_reviews.py`, `gate_state.py`, `setup_run.py`) replace heredoc-written JSON. `compose_report.py` schema-validates every input and refuses to compose if any required artifact lacks `metadata.run_id`. JSON schemas live in `references/schemas/*.schema.json`. **BREAKING** for any caller writing artifacts directly — they must go through the producer scripts.
- **`deck-review` stage gate uses checkpoint-and-resume.** Instead of `AskUserQuestion` (parent-only) inside a sub-agent dispatch, the sub-agent returns `{needs_input: ...}`; the parent asks the user, writes the answer back via `gate_state.py`, then re-invokes the sub-agent. The sub-agent rehydrates `RUN_ID` from `gate_state.json` so artifacts produced before and after the gate share one run identity.
- **`deck-review` sub-agent return contract.** Coaching dispatch now returns a structured `{status, review_dir, report_path, html_path, score_pct, overall_status, high_severity_warnings}` payload — no inline `report_markdown` in the assistant message.
- **`compose_report.py --write-md`** writes `report.md` directly to disk, eliminating prior fragility where the agent had to extract `report_markdown` from JSON and hand-write the file.
- **`setup_run.py`** replaces ad-hoc bash setup. Resolves the review directory, generates `RUN_ID`, and on `--clean` removes stale artifacts (preserving `gate_state.json` across re-invocation).
- **New compose warnings**: `SCHEMA_VIOLATION` (artifact violates JSON schema), `MISSING_METADATA` (artifact lacks `metadata.run_id`), `NAME_DRIFT` (case variants and near-miss spellings of the canonical company name detected in slide content).
- **`founder_context.py init` writes a `metadata` block** with `run_id`, `review_date`, `last_updated`. Existing context files without `metadata` remain readable; the block is added on first touch.

### Fixed

Hardens `deck-review` against several issues surfaced in real Cowork runs:

- `checklist.py` is no longer bypassed via heredoc-written `checklist.json` — `compose_report.py` validates checklist shape before composing.
- `report.json` is now always valid JSON.
- `stage_profile.json` schema is enforced (no more stage-prefixed keys or missing `reference_file_read`).
- The review-directory resolution works across both host and Cowork mount layouts.
- Sub-agents can resume after the stage gate (previously `AskUserQuestion` was parent-only and blocked the dispatch).
- Schema definitions are machine-readable JSON Schema files (previously embedded in markdown).
- The "Different stage" path no longer asks the agent to mutate the artifact directly — `stage_profile.py --rebuild-stage` does it.

## [0.3.1] - 2026-04-29

### Fixed

- Sub-agents in Cowork could not persist artifacts because the async dispatch path filters `Bash` out of every sub-agent's tool set, regardless of what the agent's `tools:` frontmatter declares. Result: founder-skills sub-agents collapsed to `{Read, Glob, Grep}` and silently degraded to prose narration instead of writing the JSON/HTML artifacts each skill produces. Adding `Write` and `Edit` to the `tools:` declaration of every founder-skills agent (`competitive-positioning`, `deck-review`, `financial-model-review`, `ic-sim`, `market-sizing`) gives sub-agents a persistence path that survives the filter. `Bash` and `Task` are kept in the declaration so they remain available in non-Cowork environments where they aren't filtered.

## [0.3.0] - 2026-04-21

### Highlights

New Competitive Positioning Agent — maps a startup's competitive landscape, scores differentiation
and moat strength, and stress-tests positioning claims to produce investor-ready competitive analysis.
Also adds resilience improvements across all scoring scripts so common LLM output shape variations
are accepted and normalized rather than rejected.

### Added

- Competitive Positioning Agent with 7 scripts: `validate_landscape.py` (competitor list validation with slug uniqueness and provenance), `score_moats.py` (6 moat dimensions per company with aggregates and cross-company comparison), `score_positioning.py` (pair-centric positioning views with rank-based differentiation and vanity axis detection), `checklist.py` (25-item quality checklist across 6 categories with mode-based gating), `compose_report.py` (report assembly with cross-artifact validation and accepted warnings), `visualize.py` (self-contained HTML with SVG positioning map, moat radar, and competitor table), and `explore.py` (interactive HTML explorer with Chart.js scatter plot, view switching, bubble encoding controls, and company detail panels).
- SKILL.md for competitive positioning (`/founder-skills:competitive-positioning` slash command).
- Deck review now imports competitive positioning landscape for cross-validation.
- IC simulation now imports competitive positioning report.
- Hard validation gates with script provenance stamps and self-grading detection.
- Axis rationale captions and label readability improvements in visualizations.

### Changed

- Market Sizing, Deck Review, and IC Simulation now track `RUN_ID` across all artifacts — `compose_report.py` flags a `STALE_ARTIFACT` high-severity warning if artifacts from different runs are mixed, blocking delivery under `--strict`. Each skill's path setup now includes `rm -f` cleanup of stale artifacts from prior runs before starting. Cowork permission guidance included.
- Deck Review expanded with: 5-item ingestion pitfalls guide (image-only PDFs, PPTX speaker notes, multi-file submissions, partial decks, wrong file types); explicit AI company detection signals for `is_ai_company`; full evidence quality rules for checklist scoring (fail/warn/pass/not_applicable each have specific requirements); Gotchas section covering polished-deck bias, AI-generated copy, benchmarks as medians, text-only input, and cross-skill context. Stale step numbers in `artifact-schemas.md` fixed to match current pipeline table. "2026" removed from description and body (kept in reference files where it is factual).
- Market Sizing and IC Simulation now include explicit sub-agent failure recovery guidance — after each sub-agent dispatch point, the agent verifies expected artifacts exist in the working directory and re-runs the failed sub-agent before proceeding if any are missing.
- Market Sizing, Deck Review, and IC Simulation now integrate `founder_context.py` as a first step — each skill reads (or creates) a persistent founder identity before starting analysis, matching the pattern already in Financial Model Review and Competitive Positioning. The company slug from founder context drives the skill-specific working directory name (`market-sizing-${SLUG}`, etc.), so artifact directories align across skills automatically. Path setup is now a two-phase process: base paths are set immediately, while the skill directory and `RUN_ID` are deferred until the slug is known. `SHARED_SCRIPTS` added to path setup and Glob fallbacks in all three skills.
- Deck Review now inserts a mandatory founder confirmation gate (two-step: chat summary then `AskUserQuestion`) between stage detection and slide review — agent presents detected stage, confidence, evidence, and expected framework before evaluating slides against stage-specific criteria. Out-of-scope stages (`series_b`/`growth`) surface a distinct gate with stop/proceed options.
- Market Sizing now inserts a mandatory founder confirmation gate between input extraction / methodology selection and external validation research — agent presents methodology, key inputs table, and missing fields before spawning research sub-agents. Founder can approve, switch methodology, or correct/add data; gate repeats until confirmed.
- `score_moats.py`, `score_positioning.py`: accept and normalize common LLM output shape mismatches — array-of-objects normalized to dict-keyed format for moat assessments; bare strings wrapped as `{name, description, rationale}` objects for axes; `slug` accepted as alias for `competitor` in positioning points.
- Financial Model Review extraction pitfalls (8 items) moved from inline SKILL.md to `extraction-pitfalls.md` reference file — reduces SKILL.md by ~22 lines while keeping the guidance available via `$REFS` pointer. Added to Available References list.
- Competitive Positioning `explore.py` now embeds Chart.js 4.4.9 from a vendored local file instead of loading via CDN — generated HTML is fully self-contained (no network required). Plotly 3D remains CDN-loaded (lazy, larger).
- Validation error messages now include expected shape hints.
- stderr summary lines added to scoring scripts for batch visibility.
- Tightened skill descriptions across all 5 skills (competitive-positioning, deck-review, financial-model-review, ic-sim, market-sizing) — dropped trigger-phrase litanies and `Do NOT use` clauses that were dead weight under `disable-model-invocation: true`. Cuts ~70% of description length each.
- Tightened agent descriptions across all 5 companion agents — dropped weakest example per agent, removed redundant `<commentary>` blocks, and rewrote openers as concise "what + when" statements. Preserves 2 distinct-capability examples per agent for reliable triggering; cuts ~45% of description length on average.

## [0.2.0] - 2026-03-18

### Highlights

New Financial Model Review agent — reviews startup financial models for investor readiness,
validating structure, unit economics, runway, and metrics against stage-appropriate standards.
Supports Excel, CSV, pitch decks, and conversational input with automatic profile-based gating
by stage, geography, and sector.

### Added

- Financial Model Review Agent with 10 scripts: `extract_model.py` (Excel/CSV parser with cell coordinate provenance and `pre_header_rows`), `validate_extraction.py` (anti-hallucination gate — 5 cross-reference checks with `--fix` for auto-correcting scale denomination), `validate_inputs.py` (4-layer structural/consistency/sanity/completeness validation), `review_inputs.py` (dual-mode review viewer with extraction warning banners and comma-formatted inputs), `apply_corrections.py` (patch-based corrections with SHA256 base_hash staleness detection), `checklist.py` (46-criteria scoring across 7 categories with profile-based auto-gating), `unit_economics.py` (11 benchmarked metrics), `runway.py` (multi-scenario stress-test with decision points and default-alive analysis), `compose_report.py` (report assembly with cross-artifact validation), `visualize.py` (self-contained HTML with SVG charts and label collision avoidance), and `explore.py` (interactive HTML explorer with editable slider values and unit labels).
- SKILL.md for financial model review (`/founder-skills:financial-model-review` slash command).
- Agent definition with skill preloading (`skills:` frontmatter).
- Profile-based auto-gating: checklist items gate by stage (`seed+`), geography (Israel, multi-currency, multi-entity), sector (AI-native, marketplace, usage-based, hardware, consumer, annual-contracts), and model format (spreadsheet vs. deck/conversational).
- `ai-powered` trait for AI-hybrid products: triggers AI cost scrutiny (SECTOR_40) regardless of revenue model type.
- Data sufficiency gate with qualitative fallback path for deck/conversational inputs.
- `data_confidence` qualifier (`exact`/`estimated`/`mixed`) propagated through unit economics and runway outputs.
- Cross-agent integration: financial model review exports `report.json`, `unit_economics.json`, and `runway.json` for downstream IC simulation and fundraise-readiness skills.
- 746 regression tests across all four skills.

### Changed

- Sub-agents for Market Sizing skill: extraction sub-agent for Steps 1-2 (file reading + methodology), parallel top-down/bottom-up research sub-agents for Step 3, and parallel sensitivity + checklist sub-agents for Steps 5-6 — all with constrained return contracts and graceful degradation.
- Sub-agents for Financial Model Review skill: extraction sub-agent for Steps 2-3 (with two-pass resume flow for documents), and parallel checklist + metrics/runway sub-agents for Steps 4-6.
- Output size contracts for IC Simulation partner sub-agents — return only verdict and one-sentence rationale instead of full assessments.
- Context reduction (~87 KB): slimmed agent definitions, condensed SKILL.md files, split FMR schemas into separate reference files.
- JSON receipt emitted to stdout when scripts write to file via `-o`, enabling programmatic artifact tracking.

## [0.1.0] - 2026-02-22

### Highlights

First release of founder-skills — a Claude Cowork plugin with three AI coaching agents
for startup founders. Market Sizing builds defensible TAM/SAM/SOM analysis with external
validation and sensitivity testing. Deck Review scores pitch decks against 35 best-practice
criteria calibrated by fundraising stage. IC Simulation recreates a VC Investment Committee
discussion with three partner archetypes debating the startup across 28 scored dimensions.

### Added

- Market Sizing Agent with 4 scripts: `market_sizing.py` (TAM/SAM/SOM calculator), `sensitivity.py` (assumption stress-testing with confidence-based auto-widening), `checklist.py` (22-item self-check), and `compose_report.py` (report assembly with cross-artifact validation).
- Deck Review Agent with 2 scripts: `checklist.py` (35-criteria scoring across 7 categories) and `compose_report.py` (report assembly with cross-artifact validation).
- IC Simulation Agent with 4 scripts: `fund_profile.py` (fund profile validation), `detect_conflicts.py` (portfolio conflict validation), `score_dimensions.py` (28-dimension conviction scoring across 7 categories), and `compose_report.py` (report assembly with 13 cross-artifact validation checks).
- Three partner archetypes (Visionary, Operator, Analyst) with independent sub-agent assessments and orchestrated debate.
- Fund-specific mode with WebSearch-backed fund research and real partner mapping.
- Cross-agent integration: IC simulation imports prior market-sizing and deck-review artifacts with staleness detection.
- SKILL.md files for all three skills (`/founder-skills:market-sizing`, `/founder-skills:deck-review`, `/founder-skills:ic-sim` slash commands).
- Agent skill preloading (`skills:` frontmatter) for all three agents.
- SessionStart hook for environment setup (`CLAUDE_PLUGIN_ROOT` persistence).
- Dev tooling: ruff (lint + format), mypy (type checking), pytest (testing), GitHub Actions CI, pre-commit hooks.
- 123 regression tests across all three skills.
