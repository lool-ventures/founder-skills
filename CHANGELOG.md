# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.5.1] - 2026-06-18 — Fleet-wide hardening: audit remediation, brand theme, self-sufficient reports

### Highlights

A broad correctness, observability, and presentation pass across all six skills following 0.5.0's
cap-table introduction. The headline work: a full-repo audit remediation hardening every skill and
the shared scripts; the lool brand theme applied to every generated HTML artifact; self-sufficient
reports that read standalone without the chat context; a founder feedback channel; deterministic
`run_id` stamping and artifacts-root resolution; and a large cap-table extraction- and
math-correctness pass. New drift-contract and renderer-key-coverage test suites lock each skill's
prose to its producers so these fixes can't silently regress.

### Added — feedback channel

- `/founder-skills:feedback` command — drafts a bug report, idea, help request, or "founder win"
  and hands the user a prefilled GitHub Issue / Discussion link (or a private `mailto:` to
  founder-skills@lool.vc) to submit themselves. The plugin transmits nothing automatically; a
  privacy hard-stop keeps company names, numbers, file paths, and transcript data out of the draft.
- Every generated report (Markdown + HTML) now carries a "Share feedback" link in its footer,
  routing to the Ideas & Feedback discussion category.
- Skills surface `/founder-skills:feedback` on a blocked/failed run and on unsolicited sentiment
  (once per session, never routine).
- cap-table report footer harmonized with the other five skills (now links back to the repo and
  lool ventures; drops the internal rule-pack version line).

### Added — self-sufficient reports

- Every skill's report (Markdown + HTML) now stands alone — it carries the context, definitions, and
  provenance needed to be read and shared without the originating chat session. Rolled out across
  all six skills (deck-review, market-sizing, ic-sim, competitive-positioning,
  financial-model-review, cap-table).

### Added — lool brand theme

- The lool visual identity is applied to every generated HTML artifact across all six skills:
  design-token CSS plus the Sora variable font (OFL) embedded base64-inline so artifacts stay
  self-contained, with a footer credit. A theme-sync contract test keeps each skill's `_theme.py`
  copy identical.

### Added — other

- **cap-table cowork-harness replay gate.** Token-free **replay** PR gate
  (`.github/workflows/cowork-replay.yml`) over committed cassettes that exercise the cap-table skill
  under Claude Cowork's runtime via `cowork-harness`. Recording is live (staged agent + Docker);
  replay/verify run token- and agent-free in stock CI. Six scenarios cover Lane 1/2/4 extraction,
  anti-hallucination, priced-round + BBWA anti-dilution, and fast-assess routing, plus a
  `verify-cassettes` privacy + staleness scan over synthetic-only fixtures.
- **cap-table:** Articles-of-Association extraction dispatch template (Lane 1); `--mode=grid` dumps
  the Lane-3 cell grid deterministically; vision fallback for image-only documents in the evidence
  verifier.
- **deck-review:** resume now preserves same-run pipeline artifacts across the stage-gate
  round-trip.

### Changed — determinism & observability

- **Unified `run_id` stamping.** All producers now inject `metadata.run_id` via a required
  `--run-id` CLI flag, so every artifact in a run shares one identifier and compose can enforce
  parity. Applied across ic-sim, market-sizing, competitive-positioning, deck-review,
  financial-model-review, and cap-table; a static orchestration guard asserts CLI-stamping producer
  pipes carry `--run-id`.
- **Deterministic artifacts-root resolution.** The inline `ARTIFACTS_ROOT` path computation in each
  SKILL.md Step 0 block was guidance the agent paraphrased, not code it ran verbatim — it kept the
  intent ("under `outputs/`") but dropped the detection, landing `outputs/` in one run and
  `outputs/artifacts/` in another, desyncing cross-skill `find_artifact.py` resolution and
  path-based assertions. All six skills now invoke a shared `scripts/resolve_artifacts_root.py`
  (fixed resolution order, deterministic, creates the dir) as one opaque command. cap-table
  additionally stages sub-agent JSON in a `/tmp` mktemp dir instead of under the promoted `outputs/`
  tree, since deletes under `outputs/` are unsafe or denied in Cowork.
- **CI version-bump filter** now requires in-plugin Markdown bumps, matching the documented
  versioning policy.

### Fixed — fleet-wide audit remediation

A full-repo audit hardened all six skills and the shared scripts. By area:

- **cap-table:** math correctness (conversion-cap-price fallback, anti-dilution baseline, donut
  palette, summary counts); extraction correctness (AoA merge, Carta fabrication guard, share-suffix
  parsing); pre-money SAFE now honors the document's two conversion branches and a pool-inclusive
  denominator; warrants join the broad-based anti-dilution base and the rule text matches the NVCA
  charter it cites; the solver flags economically impossible rounds instead of returning garbage;
  note conversion surfaces as a dilution driver; anti-dilution meta keys excluded from the explorer
  donut/legend; `pdfplumber` declared so a missing parser blocks the hallucination gate rather than
  silently degrading; rule-pack version single-sourced and bound into every producer; the dead
  ITA-SAFE citation replaced with live gov.il primary sources and honest Carta provenance.
- **financial-model-review:** burn multiple was divided by net-new ARR instead of monthly ΔMRR (a
  12× overstatement) — fixed, plus three more 12× period-mismatch bugs and a GRR sanity guard;
  partial models now evaluate all 46 checklist items and data rows survive header detection; the
  extracted-values review is a hard stop gate rather than a drive-by; stops overstating a
  default-alive company as "on track to profitability"; magic number uses the full S&M base and
  Rule of 40 uses realized YoY with honest benchmark labels (dead Mosaic citations retired); the
  checklist sub-agent no longer self-gates (gating belongs to the producer); MARKER_COLLISION
  pre-scan before status render; present-but-null numeric fields guarded in math and validators.
- **market-sizing:** unit-aware sensitivity parameter values — the Value column holds the input
  parameter (currency / count / percent), so the old USD-for-low/high, raw-number-for-base rendering
  printed percentages and counts as dollars; a new `_fmt_param_value` formats each cell by parameter
  name. Also: tolerates non-numeric deck claims and null notes; compose reordered so
  MARKER_COLLISION reflects in both status and the Warnings section.
- **deck-review:** 3-value `ai_company_status` with producer-applied AI-criteria gating and verbatim
  pass-through; canonical scoring IDs enumerated in dispatch templates; `checklist.py` omits null
  evidence/notes, requires `--run-id`, and fails closed on `-o` validation errors; `gate_state`
  answer handling survives corrupt files; resume detection moved into `setup_run.py`; visualize
  legend color and gauge fixes.
- **ic-sim:** derives `consensus_strength`, fixes warnings ordering, guards renderers against
  malformed artifacts; resolves cross-owned straggler findings shared with market-sizing.
- **competitive-positioning:** `EVID_02` mode-gating prose corrected; scripts hardened against
  malformed artifacts; `checklist.py` gains `--input-mode`/`--run-id` flags; all three
  artifact-integrity warning codes named in SKILL.md.
- **shared scripts:** `find_artifact.py` conformed to the `--pretty` / `-o` / JSON-stdout script
  convention; `founder_context.py` now performs a real recursive deep merge; `marketplace.json`
  drops the top-level `description` to match the documented format.

### Tests

- **Drift-contract suites** pin each skill's SKILL.md prose to its script source across all six
  skills, and surfaced/fixed several dead `coaching_payload` shell-variable captures and an
  input-mode attribution bug.
- **Renderer key-coverage** tests across all six skills assert every produced key is either rendered
  or explicitly excluded.
- Regression suites added for the cap-table extraction and math fixes.

### Docs

- README adds the cap-table skill section and documents six agents and Python 3.10+; CONTRIBUTING and
  SECURITY include cap-table; VERSIONING clarifies that tags gate releases and reconciles the
  no-bump cases; CLAUDE.md sync-test-repo framing and e2e figures corrected.

## [0.5.0] - 2026-06-10 — New skill: cap-table; financial-model-review hardening

### Highlights

This release ships the cap-table skill for the first time and completes a pre-distribution hardening
pass on financial-model-review. Users upgrading from 0.4.7 get both skills in their first-ever
stable form — neither was available in any prior distributed release.

*Versions 0.4.8–0.4.11 were internal development versions and were never distributed; all of their
changes ship in 0.5.0.*

### Added — new skill: cap-table

The cap-table skill extracts structured terms from SAFEs, convertible notes, term sheets, articles
of association, and Carta XLSX exports, then runs a layered math pipeline to produce a
counsel-handoff packet and founder-readable report.

#### Extraction

Four lanes share a common anti-hallucination validator:

- **Lane 1 — unstructured instruments (PDF/DOCX).** A sub-agent extracts; the validator enforces
  form-dependent required-field gates, normalizes the discount-rate multiplier-vs-rate trap, and
  routes warrants and non-instruments to clean classification. Accepted instrument types include
  all five YC SAFE forms (post-money cap, uncapped MFN, cap-and-discount, pre-money legacy cap,
  pre-money legacy cap-and-discount), convertible notes, convertible loan agreements (Israeli
  CLA/CIA), YC convertible securities, term sheets, option plans, and warrants.
- **Lane 2 — Carta XLSX exports.** Verified sheet-name fingerprint, Convertible Ledger parsing,
  discount normalization, and cancelled-record skipping. `--mode=pulley` routes to freeform with a
  structured blocker until a verified Pulley workbook fingerprint is available.
- **Lane 3 — freeform spreadsheets.** Sub-agent identifies cell semantics; validator gates per-field
  confidence.
- **Lane 4 — structured JSON paste / conversational.** Pre-built JSON or chat-described cap tables
  still flow through `--mode=validate` for schema enforcement.

A four-layer verification stack runs by default on every Lane-1 extraction:

- **Forward verification** — three-layer check catches hallucinated values not present in the source
  document. Calibrated at 3.6% FPR / 100% TPR on verifiable docs; handles 8 PDF
  extraction-artifact patterns (CID-encoded fonts, image-only PDFs, DocuSign overlays, etc.).
- **Invariant checking** — per-field real-world bounds and cross-field math invariants. 0% FPR /
  63% TPR on ×1000 unit-error perturbations. Hard math impossibilities block; soft bounds warn-only.
- **Deterministic backstop extractors** — regex-based span-preserving extractors for SAFEs
  (`purchase_amount`, `discount_multiplier`, `valuation_cap`, `issuance_date`, `investor_name`).
- **Cross-check** — demote-only confidence modulator when sub-agent and backstop disagree.
  Agreement never bumps; informational only.

An optional fifth layer (backward verification via fresh-sub-agent re-extraction) catches
semantic-confusion errors and is dispatched when the `attention_needed_fields[]` receipt signals
high-stakes ambiguity.

#### Math pipeline

Cap state → SAFE/note conversion → option-pool top-up → coupled priced-round solver with
anti-dilution → flip scenarios → report assembly.

- **SAFE conversion** — all five YC forms including the pre-money (legacy) family. Post-money forms
  lock `purchase/cap` of Company Capitalization measured immediately prior to the equity financing
  (= existing shares + pre-existing unissued pool + all converting securities), then are diluted by
  the new-money round like all other holders — per the YC post-money SAFE definition and rule
  `safe.company_capitalization_yc_post_money`; pre-money forms use the pre-financing FD as
  denominator — the two families produce materially different cap tables.
  MFN auto-bind: when an uncapped MFN SAFE has `mfn_provision.elected_against_safe_id` pointing to
  a resolved sibling, the election is pre-resolved before iteration. Transitive MFN chains resolve
  to a fixed point (bounded by `len(safes)` iterations). Genuinely uncapped MFNs still hit the
  cycle guard.
- **Note conversion** — seven-branch enum (`cap_conversion` / `discount_only` /
  `maturity_floor_conversion` / `maturity_discount_only` / `maturity_outstanding` /
  `maturity_forgiven` / `threshold_not_met`) plus override branch. Accepted subtypes: standard
  convertible note, Israeli CLA, YC convertible security.
- **Option-pool top-up** — four `target_basis` modes. When `pre_money` basis produces a zero top-up
  because the existing pool already meets target, the skill issues a clarifying question so the
  founder confirms pre-money vs post-close-unallocated intent.
- **Coupled priced-round solver** — fixed-point iteration couples SAFE conversion, note conversion,
  pool top-up, new-money issuance, and anti-dilution (BBWA and full ratchet) in a single Banach
  loop. Per-series knobs: `ad_trigger_basis`, `ad_a_denominator_basis`, `ad_cp2_floor`,
  `ad_carve_outs`. Convergence guards: sign-flip damping (α=0.5), Aitken Δ² acceleration,
  fallback fence, 200-iteration hard cap. When anti-dilution fires, the report renders a three-way
  founder-ownership narrative: pre-AD baseline / coupled post-AD headline / delta in pp.
- **Warrants as first-class instruments.** Vested outstanding warrants are included in
  `fully_diluted_shares`; unvested are surfaced separately and excluded per the YC primer narrow
  `company_capitalization` convention. A deterministic pre-round pump applies cash-exercise or
  net-share settlement for warrants whose exercise date precedes the transaction date. Preferred-stock
  warrants route into the matching series. Three settlement variants are explicitly rejected with
  structured errors: debt cancellation, share-for-share exchange, VWAP-cashless.
- **Dual-class / super-voting.** When any holder carries `voting_rights_multiple != 1.0`, the report
  adds a voting-pct column to the cap-table summary.
- **AoA-only engagements.** The skill accepts an Articles of Association with no
  SAFEs/notes/grants. The AoA extractor populates `preferred_series[]` and `aoa_findings` (9
  findings: drag-along threshold, Section 102 plan, liquidation preference above 1×, participation,
  dividend provisions, protective provisions, bring-along threshold, pay-to-play detection, full
  ratchet presence). The report renders an AoA-summary view.
- **Fast-assess mode.** A 1-page founder-facing markdown report in under 60 seconds for
  conversational queries that don't need the full pipeline. Step 0 routes between fast-assess and
  full pipeline based on whether a document is attached.
- **Israeli ↔ Delaware flip analysis.** `flip_scenario.py` models the 1:1 share-for-share flip.
  QSBS eligibility gates against the post-flip Delaware C-corp issuance date (`flip_closing_date`),
  not the pre-flip Israeli date.
- **Counsel-handoff packet.** Standalone JSON + Markdown deliverable (`counsel_packet.py`).

#### Rule pack and counsel items

~75 rules across 10 domains, citing NVCA Model COI §4.4.4/§4.4.5, YC SAFE primer, Cooley GO
down-round article, and ITA §102. The `counsel_review` flag is a reliance boundary — a rule can be
`confidence: high` and `counsel_review: true` simultaneously. The rule-audit pipeline runs in two
phases: `--phase=pre_math` writes a gating block before math runs; `--phase=post_math` composes
watchlist and counsel items after. The founder-facing report splits the watchlist into "Active"
(applies to this engagement) and "For-Reference Annotations" (tracked but not currently applicable).
Per-scenario completeness lines expand the bare enum value into plain language so founders know
whether legal/tax math ran.

#### Scope and explicitly rejected inputs

The following are rejected with structured errors or surfaced as counsel items rather than silently
mis-modeled: RSU grants (`E_RSU_NOT_MODELED`), cumulative-preferred dividend math
(`E_DIVIDEND_FIELDS_REMOVED` — dividend provisions surface in `aoa_findings` for counsel-handoff),
warrant repricing under issuer AD clauses, three exotic warrant settlement variants (debt
cancellation / share-for-share exchange / VWAP-cashless), non-1:1 flip ratios, non-unity preferred
voting (surfaces `W_PREFERRED_VOTING_NON_UNITY_NOT_MODELED`), Pulley XLSX (structured blocker routes
to freeform), LLC structures and profits-interests, SPAC/de-SPAC mechanics, multi-class liquidation
waterfalls at exit, 409A valuations, pro-rata side-letter exercise, cumulative preferred dividends,
83(b) elections.

#### Engineering reliability

Every consumer reads artifacts through a typed loader (`_artifact_io.py`) that validates
`schema_version` stamps and re-runs 14 semantic invariants at the load boundary, including FD-sum
equality, CCP ≤ OCP ratchet-down, warrant vested_flag / exercise_event_date parity, and
mirrored-field drift detection. Solver convergence guards (damping, Aitken acceleration, fallback
fence) ensure deterministic outputs. 1,588 non-e2e tests pass. The property-based solver
convergence harness and fresh-AI replay tests are scheduled as a v0.5.1 follow-up.

### Fixed — all skills

- **Claude Cowork in-VM script discovery.** `${CLAUDE_PLUGIN_ROOT}` substitutes to a host-side
  path that does not exist inside the Cowork session VM — non-empty but invalid — so the documented
  Glob fallback never fired and agents hit "No such file" with no cue to fall back. The fallback
  condition in all six SKILL.md files now also fires when the resolved path does not exist.
  (Developed internally as v0.4.11; first ships here — satisfies downstream skills declaring
  `requires founder-skills ≥ v0.4.11`.)
- **Version-ref policy (fleet-wide).** Removed internal release markers, sprint labels, and
  audit-cycle references from SKILL.md files, agent bodies, schema descriptions, rule pack fields,
  and inline comments across all skills. A new contract test
  (`test_no_internal_version_refs_in_user_facing_files`) enforces this policy on every PR.

### financial-model-review: pre-ship hardening

A focused pre-distribution hardening pass carried in this release. All changes are in `founder-skills/skills/financial-model-review/` and its tests.

#### Orchestration contract fixes

- **CHECKLIST dispatch shape corrected.** The sub-agent return shape now includes `company` (copied verbatim from `inputs.json`) and `metadata: {"run_id": "<RUN_ID>"}` alongside `items`. This ensures `checklist.py` can apply profile-based auto-gating (stage/geography/sector/model_format) and that `checklist.json` carries a `run_id` consistent with the other three producer artifacts. Context B coaching dispatch was structurally blocked on every run due to the missing `run_id`; that is now fixed.
- **Checklist ID enumeration corrected (`BRIDGE_36..38`).** SKILL.md and the agent body both previously referenced non-existent `SCENARIO_36..38` IDs while double-booking positions 36–38. The canonical set from `checklist.py` is `METRIC_33..35, BRIDGE_36..38, SECTOR_39..44, OVERALL_45..46`. Sub-agents following the corrected prompt will no longer emit unknown IDs that `checklist.py` rejects.
- **`commentary.json` authoring step added.** `verify_review.py --gate 2` requires `commentary.json` for quantitative reviews, but no workflow step produced it. Added an explicit agent-authored heredoc step (after Step 7, before Step 8b) with schema reference. Cleanup list extended to cover this and other previously missing artifacts (`extraction_validation.json`, `corrected_inputs.json`, `extraction_corrections.json`, `corrections_from_agent.json`, `commentary.json`, `explore.html`, `review.html`).
- **`coaching_payload` now printed, not captured.** The `COACHING_PAYLOAD="$( ... )"` assignment wrapped the extraction in command substitution, sending output to a shell variable that neither persisted between Bash calls nor reached the tool result. Changed to a bare `python3 -c '...'` invocation so the payload prints directly to stdout.
- **UE and runway dispatches replaced with direct pipes.** `UNIT_ECONOMICS` and `RUNWAY_SCENARIOS` sub-agent dispatches were pure pass-through round-trips (read `inputs.json`, return `inputs.json`), exposing multi-KB financial figures to LLM transcription errors. Both steps now use `cat "$REVIEW_DIR/inputs.json" | python3 "$SCRIPTS/<producer>.py" ...` directly from the main thread.
- **INPUTS_REVIEW dispatch uses deterministic corrected-payload path.** Sub-agent return shape now explicitly excludes `changes` and `base_hash` keys, routing through the deterministic `corrected`-shaped path in `apply_corrections.py`. The broken `base_hash`-verification patch path (which always errored because the sub-agent has no Bash) is avoided.
- **`dispatch_contracts.json` fixtures updated.** Synced with the direct-pipe UE/runway change and the `overall_status` field rename.

#### `verify_review.py` fix — default-alive companies

Gate 2 no longer blocks publication for profitable or default-alive companies. Previously any review where no scenario had `runway_months` (correct for a company that never runs out of cash) caused exit 1. Fixed to: only error if no runway **and** no scenario is default-alive.

#### `coaching_payload` field fixes

- **`runway_months` added.** `_emit_coaching_payload` in `compose_report.py` now extracts the base-scenario `runway_months` (may be `null` for default-alive companies) and includes it in the payload.
- **`overall_status` rename.** The agent success payload field was renamed from `unit_economics_status` to `overall_status`, correctly mapped to `coaching_payload.summary.overall_status` (the checklist overall status). Dispatch-contract fixtures updated to match.

#### HTML self-containment and escaping

- **Chart.js vendored into `explore.py`.** The explorer previously loaded Chart.js from a CDN. The Cowork iframe sandbox blocks external fetches; offline `file://` viewing also broke. Copied the vendored `chart.min.js` (already used by `competitive-positioning/scripts/explore.py`) into `financial-model-review/scripts/vendor/` and switched to inline embedding.
- **`</script>` injection hardening.** Founder-document-derived data (company names, LLM-extracted strings) embedded as JSON in `<script>` blocks now has `<` escaped to `\u003c` at every embed site in both `explore.py` and `review_inputs.py`.
- **HTML escaping for warning/commentary fields.** Extraction-warning `candidates` and `untraceable[*].role` strings in `review_inputs.py` are now wrapped with `html.escape()`. Commentary fields (`callout`, `highlight`, `watch_out`) in `explore.py` are assigned via `textContent`/`createTextNode` instead of HTML string concatenation.
- **Scenario labels and banner title escaped** via the shared `_esc()` helper throughout the explorer.

#### `review_inputs.py` hardening

- **Kill-port guard targets only own instances.** `_kill_port` previously sent SIGTERM to whatever process owned the port; now checks the process command line contains `review_inputs.py` before signalling.
- **`GET /api/feedback` returns 405.** The handler previously returned the stored corrections payload to any local caller; changed to an explicit 405.
- **Static-mode receipt carries `ok` and `bytes` keys**, aligned with the receipt shape used by `visualize.py` and `explore.py`.

#### Input-pipeline robustness

- **Structured `READ_ERROR` on corrupt corrections upload.** `apply_corrections.py` previously produced a raw Python traceback when the uploaded corrections file was corrupt; now emits `{"status": "error", "errors": [{"code": "READ_ERROR", ...}]}` consistent with every other error path.
- **BOM-tolerant CSV reading.** `extract_model.py` now opens CSV files with `encoding="utf-8-sig"`, so Windows Excel exports parse correctly instead of producing a `"﻿Month"` header that silently fails column matching.
- **Root-dir write guard in `validate_extraction.py`.** Added the same output-path root-directory guard that every sibling script already has.

#### Heuristic guards

- **Scale-fix requires ≥ 2 corroborating fields.** `validate_extraction.py --fix` previously applied a ×1000 scale correction if any scale indicator was present and values appeared implausible, even when only one monetary field was populated (insufficient evidence for majority vote). Now requires at least 2 monetary fields.
- **Post-fix plausibility check.** After applying a scale correction, `validate_extraction.py --fix` verifies the corrected values are plausible before writing; skips and warns if the corrected values are still implausible.
- **Mixed/unknown periodicity uses multi-multiplier scan.** Traceability checks on models where `periodicity_summary` is `"mixed"` or `"unknown"` previously scaled as monthly (×1), producing spurious `REVENUE_TRACEABILITY` warnings on quarterly or annual models. Now tries ×3 and ×12 for `"mixed"`, and skips periodicity-aware scaling for `"unknown"`.

#### Analysis fixes

- **`monthly_total` fallback in expense-coverage check.** `validate_inputs.py` `EXPENSE_COVERAGE_SUSPECT` now reads `revenue.monthly_total` when `revenue.mrr.value` is absent, avoiding false-positive critical warnings for companies that express revenue via monthly total rather than MRR.
- **Sub-score `None` semantics for inapplicable categories.** `checklist.py` `business_quality_pct` previously returned `0.0` when zero business items were applicable; now mirrors the `None` pattern used by `model_maturity_pct` so downstream display code treats it as "not computed" rather than "zero quality."
- **Near-zero cash warning guard.** `compose_report.py` `RUNWAY_INCONSISTENCY` check now requires `abs(inputs_cash) >= 1000` before computing a delta percentage, avoiding false positives near zero.
- **Breakeven note.** `runway.py` now emits a human-readable note when `monthly_net_burn = 0` (breakeven), instead of "Infinite" for every row of the burn-sensitivity table.
- **Negative USD formatting.** `visualize.py` `_fmt_usd` now handles negative values with `"-" + _fmt_usd(-value)`, producing `"-$200K"` instead of `"$-200,000.00"` (which overflowed SVG label slots on the runway chart's Y-axis).
- **`bench` initialized to `None`.** `unit_economics.py` declared `bench` as annotation-only; initialized to prevent potential `UnboundLocalError` on refactoring paths.

#### Version-ref policy cleanup (fleet-wide)

A new contract test (`test_no_internal_version_refs_in_user_facing_files`) now enforces the version-ref policy fleet-wide on every PR. As part of this pass: removed internal version markers from the financial-model-review SKILL.md and agent body; converted the agent-body changelog section into present-tense instructions; cleaned up garbled arithmetic in the agent body; applied the same removal to `agents/deck-review.md` (had one stale reference).

#### Schema-doc drift fixes

- `references/schema-inputs.md`: `company.stage` enum now lists all five values; both `revenue_model_type` enum tables now list all 10 canonical values; `model_format` pipeline-effects subsection moved below the `company` field table; `--strict` semantics note corrected (blocks on high-severity warnings only).
- SKILL.md: `--sector-type` valid-values list extended to include `transactional-fintech`; stale Context B preamble replaced with accurate description; `metadata.run_id` requirement scoped to the four producer artifacts.

#### CI registry wiring

- `financial-model-review` added to `compose_invocations.py` registry (`_COMPOSE_FLAGS` and `_RUN_ID_MUTATION_TARGET`).
- `financial-model-review` added to `COACHING_SKILLS` in `test_compose_invariants.py`.
- Fixture directory `tests/fixtures/financial-model-review/` populated with `inputs.json`, `checklist.json`, `unit_economics.json`, `runway.json` — the shared `coaching_payload` + `STALE_ARTIFACT` invariant suite now exercises this skill.
- New `test_fmr_skill_contract.py`: CHECKLIST ID enumeration, SKILL.md/agent body ID consistency, fleet-wide internal-version-ref policy enforcement.

### Out of scope for v0.5.0

Surfaces-based counsel-packet rendering and tag backfill across the existing ~70 rules, property-based solver convergence harness, fresh-AI replay tests. All three are scheduled for v0.5.1 follow-ups; the internal contract spec lays out the design.

## [0.4.7] - 2026-05-19

### Highlights

Gives `competitive-positioning`'s research sub-agent the `WebSearch` tool it was always dispatched to use, so competitor research and moat-trajectory evidence are honest rather than guessed from training data.

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

### Highlights

Fixes a `market-sizing` gap where deck TAM/SAM/SOM figures stated under non-canonical keys silently bypassed deck-vs-computed reconciliation, and adds a narrative escape hatch for deck claims that don't fit the canonical shape.

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

### Highlights

Adds a skill-quality CI pipeline — contract tests, compose invariants, and a deck-review end-to-end smoke — that runs on every PR and gates releases on tag-push.

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

### Highlights

Retires the single-purpose `verify-cowork-clone.sh` in favor of `claude-plugin-doctor`, which diagnoses drift across all cache layers rather than just the marketplace clone HEAD.

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

### Highlights

Coaching commentary now reasons from a structured `coaching_payload` block in `report.json` instead of re-reading the full report, saving tokens and aligning producer schemas across skills.

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

### Highlights

Skills now run inline in the main thread so they work end-to-end on Cowork, with heavy analytical steps dispatched to sub-agents and coaching commentary appended via a post-compose dispatch.

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

### Highlights

Replaces `deck-review`'s heredoc-written JSON with validating Python producer scripts that schema-check every artifact, and moves the stage gate to a checkpoint-and-resume flow.

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

### Highlights

Gives every founder-skills sub-agent a persistence path (`Write`/`Edit`) that survives Cowork's `Bash` filtering, so sub-agents write their JSON/HTML artifacts instead of degrading to prose narration.

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
