# CLAUDE.md

## Repository Structure

- `founder-skills/` — Claude Code plugin (SDK/CLI-based)
- `founder-skills/.claude-plugin/plugin.json` — Plugin manifest
- `founder-skills/commands/feedback.md` — `/founder-skills:feedback` slash command (drafts a bug/idea/help/win report, hands the user a prefilled GitHub/`mailto:` link to submit; transmits nothing automatically)
- `founder-skills/skills/market-sizing/` — Market sizing skill with scripts and references
- `founder-skills/skills/deck-review/` — Deck review skill with scripts and references
- `founder-skills/agents/market-sizing.md` — Market sizing agent definition
- `founder-skills/agents/deck-review.md` — Deck review agent definition
- `founder-skills/skills/ic-sim/` — IC simulation skill with scripts and references
- `founder-skills/agents/ic-sim.md` — IC simulation agent definition
- `founder-skills/scripts/session-setup.sh` — SessionStart hook (persists CLAUDE_PLUGIN_ROOT)
- `founder-skills/scripts/founder_context.py` — Founder context management (init/read/merge/validate)
- `founder-skills/scripts/find_artifact.py` — Artifact path discovery across skills
- `founder-skills/scripts/insert_coaching.py` — Shared Context B coaching-commentary inserter (idempotency matrix, uuid-marker replacement, run_id parity)
- `founder-skills/scripts/check_handoff.py` — Shared Context A file hand-off gate (typed exit codes for main-thread branching)
- `founder-skills/scripts/merge_json.py` — Shallow-merge of parallel sub-agent hand-off files for producer pipes
- `founder-skills/scripts/md_to_commentary.py` — Wraps a sub-agent's raw-markdown coaching commentary into the JSON envelope `insert_coaching.py` consumes (the model never hand-escapes the commentary)
- `founder-skills/scripts/resolve_artifacts_root.py` — Canonical + agent-namespace artifacts-root resolver (`--agent` for HANDOFF_AGENT derivation)
- `founder-skills/references/` — Shared reference files (benchmarks, Israel guidance, etc.)
- `founder-skills/references/brand/` — Brand tokens + Sora variable webfont (OFL) for generated HTML artifacts; embedded base64-inline so artifacts stay self-contained
- `founder-skills/tests/test_market_sizing.py` — Market sizing regression tests
- `founder-skills/tests/test_deck_review.py` — Deck review regression tests
- `founder-skills/tests/test_ic_sim.py` — IC simulation regression tests
- `founder-skills/tests/test_visualize_market_sizing.py` — Market sizing HTML visualization tests
- `founder-skills/tests/test_visualize_deck_review.py` — Deck review HTML visualization tests
- `founder-skills/tests/test_visualize_ic_sim.py` — IC simulation HTML visualization tests
- `founder-skills/skills/financial-model-review/` — Financial model review skill with scripts and references
- `founder-skills/agents/financial-model-review.md` — Financial model review agent definition
- `founder-skills/tests/test_financial_model_review.py` — Financial model review regression tests
- `founder-skills/tests/test_visualize_financial_model_review.py` — Financial model review HTML visualization tests
- `founder-skills/skills/competitive-positioning/` — Competitive positioning skill with scripts and references
- `founder-skills/agents/competitive-positioning.md` — Competitive positioning agent definition
- `founder-skills/tests/test_competitive_positioning.py` — Competitive positioning regression tests
- `founder-skills/tests/test_visualize_competitive_positioning.py` — Competitive positioning HTML visualization tests
- `founder-skills/skills/cap-table/` — Cap-table skill (SAFE / note conversion, priced rounds, anti-dilution, Israeli ↔ Delaware flips)
- `founder-skills/agents/cap-table.md` — Cap-table agent definition (Context A extraction + Context B coaching)
- `founder-skills/tests/test_cap_table.py` — Cap-table regression tests (math producers + 11-gotcha regression suite)
- `founder-skills/tests/test_cap_table_freeform.py` — Lane-3 freeform mapper tests (`freeform_mapper.map_freeform` golden maps + blockers + `--mode=freeform-emit` CLI + the `cap_state` `E_NO_EQUITY_BASE` guard)
- `founder-skills/tests/test_visualize_cap_table.py` — Cap-table HTML visualization tests
- `founder-skills/tests/cowork_async_subagent_filter.py` — Cowork sub-agent tool-name compatibility helper (skill-quality CI; v0.4.0-regression detector)
- `cowork-tests/leak_scan.py` — Shared detector for founder-facing "internal plumbing" leaks in assistant narration. Ten classes: nine syntactic (script names, `*.py`, `--flags`, `$vars`, exit codes, `W_`/`E_` codes, JSON, step/route labels, ALLCAPS-with-underscore) plus `plumbing_verb`, which is semantic. Reads a cassette or a run dir's `events.jsonl` — point it at the FILE, since a directory glob finds only `*.json` and reports a silent false-clean.
- `founder-skills/tests/test_founder_facing_leaks.py` — Ratchet over `leak_scan.py` across the committed cassettes. **Gates "no NEW leaks beyond `BASELINE`", not zero** — the cassettes predate the narration rule. Ratchet the constant DOWN after a re-record; never raise it.
  - **Scope warning — a green here still does not mean the narration is clean, but the gap is now narrower than this note used to claim.** Nine of the ten classes match on FORM (backticks, `--flags`, `$vars`, `*.py`, exit codes, `W_`/`E_` codes, JSON, a literal route-label list, ALLCAPS-with-underscore). The tenth, `plumbing_verb`, is SEMANTIC: it targets the verb+object construction that only appears when narrating internals, so "gating the hand-off", "piping it through the producer" and "dispatching the sub-agent" ARE caught (measured: 3 such leaks, and zero syntactic ones, in one live run's `events.jsonl`). **What still passes clean is internal vocabulary with no plumbing verb** — "canonical artifacts", "schema-drift warning", "gap-detection pass", bare `STOP`/`BLOCKED` (no underscore), and "Gate 1 passes". That residue is the live-run/hand-read surface; it is smaller than "every plain-English mention". Do not fix it by enumerating more words — `leak_scan.py`'s own design note says an enumerated blocklist is unwinnable, which is why the classes are class-based. **Superseded advice, recorded so it is not re-derived:** this note used to say never to extend the existing classes because doing so "raises the measured count on the committed cassettes and reds the suite". That was tried and is false — the ten-class total over the committed cassettes is **61 against `BASELINE = 144`**, green, because the nine-class count had already fallen far below its own baseline.
- `founder-skills/tests/compose_invocations.py` — Per-skill compose-script invocation registry (skill-quality CI)
- `founder-skills/tests/test_cowork_async_subagent_filter.py` — Helper unit tests
- `founder-skills/tests/test_cowork_invariants.py` — Per-agent persistence + dangerous-tool declaration invariants
- `founder-skills/tests/test_skill_orchestration.py` — Per-SKILL.md frontmatter + sub-agent-cue-then-bash regression detector
- `founder-skills/tests/test_compose_invariants.py` — `coaching_payload` shape + `STALE_ARTIFACT` regression
- `founder-skills/tests/test_insert_coaching.py` — `insert_coaching.py` suite (6-state idempotency matrix, run_id parity, single-pass write-back, adversarial commentary)
- `founder-skills/tests/test_check_handoff.py` — `check_handoff.py` suite (typed exit paths 0/3/4/5/6, adversarial file states, tolerant receipt extraction)
- `founder-skills/tests/test_merge_json.py` — `merge_json.py` suite (merge order, --set overrides, error paths)
- `founder-skills/tests/test_resolve_artifacts_root.py` — Artifacts-root resolver suite (Cowork mount signatures + agent-namespace root)
- `founder-skills/tests/test_theme_sync.py` — Brand-theme invariants: per-skill `_theme.py` copies identical, brand font present, font embeds in CSS
- `founder-skills/tests/test_e2e_deck_review.py` — End-to-end smoke; LLM-driven; carries `e2e` marker
- `founder-skills/tests/fixtures/` — Synthetic test inputs (deck-review compose-invariant fixtures + synthetic deck for e2e + golden expected file)
- `.github/workflows/skill-quality.yml` — Skill-quality CI (contract tests per-PR, e2e smoke on internal PRs only)
- `artifacts/` — Persistent working directory for skill run artifacts (gitignored, created at runtime)

## Plugin Structure

- `.claude-plugin/marketplace.json` — Marketplace manifest (root level)
- `founder-skills/.claude-plugin/plugin.json` — Plugin manifest with hooks
- marketplace.json must match Anthropic's format: only `name`, `owner`, `plugins` (each with `name`, `source`, `description`)
- Do NOT add `version` or `metadata` fields to marketplace.json

## Script Conventions

- Scripts use PEP 723 inline metadata; default to `python`, `uv run` optional
- Scripts output JSON to stdout, warnings/errors to stderr
- All scripts support `--pretty` for human-readable output and `-o <file>` to write to file (skill scripts emit a JSON receipt to stdout confirming the write)
- Skill-local scripts live in `founder-skills/skills/<skill>/scripts/`

## Shared Scripts

- **`founder_context.py`** — Per-company context management (init/read/merge/validate subcommands); protects 11 key metric fields
- **`find_artifact.py`** — Resolves artifact paths by skill name, artifact filename, and optional company slug
- **`insert_coaching.py`** — Deterministic Context B insertion: reads the sub-agent's commentary JSON, applies the 6-state idempotency matrix, replaces the per-run uuid `insertion_marker` with `## Coaching Commentary` + commentary in a single in-place write, and verifies `run_id` parity across `--verify-artifact` paths (exit 0 inserted/already_inserted; exit 1 blocked with JSON diagnostic). Every skill's POST_COMPOSE_COACHING step calls it; sub-agents only compose commentary and never edit `report.md`.
- **`check_handoff.py`** — Context A file hand-off gate: verifies a sub-agent's output file exists/parses as JSON and (optionally) that its receipt's `output_path` matches (`--agent-path` accepts the agent-namespace echo). Typed exit codes (0 ok / 3 missing-or-empty / 4 bad JSON / 5 path mismatch / 6 unparseable receipt / 7 content-shape invalid / **8 path-namespace mismatch**) for main-thread branching. Exit 8 fires when no file is at the expected path but one IS where a **doubled** agent-namespace prefix would have put it — reported ahead of exit 3 because the two are indistinguishable from the file check yet need opposite responses (3 = the receipt may be fabricated; 8 = the agent complied and the path was wrong). Its `found_at` is **diagnostic only**: never read the hand-off from it, or exit 0 stops meaning "the file is at the contracted path" for the ~50 downstream `$HANDOFF_DIR` references.
- **`merge_json.py`** — Shallow-merges multiple JSON object hand-off files (later files win; `--set key=value` overrides) into one stream for producer pipes — used when a step consumes the union of parallel sub-agent outputs (e.g. market-sizing "both").
- **`md_to_commentary.py`** — Transport envelope for Context B: the sub-agent writes coaching commentary as **plain markdown** (never JSON, never escaped), this wraps it into the payload `insert_coaching.py` reads. Quotes and line breaks in the commentary can't break the hand-off.
- **`resolve_artifacts_root.py`** — Resolves the canonical artifacts root AND the agent-namespace root (`--agent` / `--json`): in Cowork the sub-agents' file tools see the `outputs/` mount at a different prefix than the VM shell, so SKILL.mds derive `HANDOFF_AGENT` from `--agent` when building `OUTPUT_PATH` dispatch lines.

## Market Sizing Scripts

- **`market_sizing.py`** — TAM/SAM/SOM calculator (top-down, bottom-up, or both)
- **`sensitivity.py`** — Stress-test assumptions with low/base/high ranges and confidence-based auto-widening
- **`checklist.py`** — Validates 22-item self-check with pass/fail per item
- **`compose_report.py`** — Assembles report from artifacts, validates cross-artifact consistency
- **`visualize.py`** — Generates self-contained HTML with SVG charts; outputs HTML (not JSON)

## Deck Review Scripts

- **`checklist.py`** — Scores 35 criteria across 7 categories (pass/fail/warn/not_applicable) with overall score percentage
- **`compose_report.py`** — Assembles deck review artifacts into final report with cross-artifact validation
- **`visualize.py`** — Generates self-contained HTML with SVG charts; outputs HTML (not JSON)

## IC Simulation Scripts

- **`fund_profile.py`** — Validates fund profile structure (archetypes, check size, thesis, portfolio)
- **`detect_conflicts.py`** — Validates agent-produced conflict assessments and computes summary stats
- **`score_dimensions.py`** — Scores 28 dimensions across 7 categories with conviction-based scoring
- **`compose_report.py`** — Assembles IC simulation artifacts into final report with cross-artifact validation
- **`visualize.py`** — Generates self-contained HTML with SVG charts; outputs HTML (not JSON)

## Financial Model Review Scripts

- **`extract_model.py`** — Extracts structured data from Excel (.xlsx) and CSV files into model_data.json
- **`validate_extraction.py`** — Anti-hallucination gate: cross-references model_data.json against inputs.json (company name, salary, revenue, cash traceability, scale plausibility); `--fix` auto-corrects scale denomination issues (e.g., model in $000)
- **`validate_inputs.py`** — Four-layer validation of inputs.json (structural, consistency, sanity, completeness); `--fix` auto-corrects sign errors
- **`checklist.py`** — Scores 46 criteria across 7 categories with profile-based auto-gating by stage/geography/sector
- **`unit_economics.py`** — Computes and benchmarks 11 unit economics metrics against stage-appropriate targets
- **`runway.py`** — Multi-scenario runway stress-test with decision points and default-alive analysis
- **`compose_report.py`** — Assembles financial model review artifacts into final report with cross-artifact validation
- **`visualize.py`** — Generates self-contained HTML with SVG charts; outputs HTML (not JSON)
- **`explore.py`** — Generates self-contained interactive HTML explorer from review artifacts; outputs HTML (not JSON)
- **`review_inputs.py`** — Dual-mode review viewer: HTTP server with live validation (Claude Code) or self-contained static HTML with JS sanity metrics (Cowork); outputs HTML. The static/Cowork branch must stay write-back-safe: guard every `/api/*` `fetch` behind the build-time `IS_STATIC` flag with a lexical `if/else` (an early-return guard reads as unguarded to the write-back analyzer), name the fetch response `resp`/`res`/`response` and check `resp.ok`, and keep literal `<script>`/`</script>` tokens out of docstrings (the block extractor mis-reads them). The `financial-model-review-smoke` cassette's `no_lost_write_back` assert locks this in.
- **`_theme.py`** — Brand theme helper: design-token CSS + base64 @font-face from `references/brand/`; every skill's scripts dir carries an identical copy (standalone scripts can't import across skills) and all HTML generators inject `_theme.brand_css()`; `tests/test_theme_sync.py` enforces the copies stay identical — edit one, re-copy to all
- **`apply_corrections.py`** — Processes founder's downloaded corrections file: coerces, normalizes, merges overrides, writes corrected_inputs.json + extraction_corrections.json
- **`verify_review.py`** — Review completeness gate: checks artifact existence, content quality (evidence, critical fields, metrics), and cross-artifact consistency; exit 0 = publishable, exit 1 = gaps

## Cap Table Scripts

Rule-pack-driven cap-table math. Every math producer cites a `rule_id` from `cap-table-rules.json` (v0.2.8+). The pipeline is two-phase per design §9 Step 4.5 / Step 6: `rule_audit.py --phase=pre_math` writes the gating block math producers consume; `--phase=post_math` composes watchlist + counsel items after math runs.

- **`cap_state.py`** — Aggregates inputs + instruments into `cap_state.json` with `as_converted_totals` (the pre-financing snapshot the YC SAFE `company_capitalization` denominator binds to per Gotcha #1)
- **`safe_conversion.py`** — YC post-money SAFE math; all 5 forms; cap-implied + post-financing output sets; MFN cycle detection (Gotcha #4)
- **`note_conversion.py`** — Convertible-note math with full 7-branch enum (cap_conversion / discount_only / maturity_* / threshold_not_met) + override branch
- **`option_pool.py`** — Option-pool top-up math; `target_basis` enum with all 4 rule-pack values
- **`anti_dilution.py`** — BBWA (with CP1 divisor per Gotcha #2) + full ratchet
- **`priced_round.py`** — Solver/orchestrator: fixed-point iteration for coupled SAFE + note + pool + new_money + AD systems
- **`flip_scenario.py`** — Israeli ↔ Delaware flip (v0.1: 1:1 share-for-share only per Gotcha #7)
- **`rule_audit.py`** — Two-phase (`--phase=pre_math` / `--phase=post_math`); scope-aware apply contract (`legal_tax_applicability` / `benchmark_freshness` / `not_applicable`); 5 mutually exclusive statuses + 2 near-edge overlays
- **`run_scenario.py`** — Top-level scenario orchestrator (routes by `scenario.type`)
- **`counsel_packet.py`** — Counsel-handoff packet (json + md); standalone deliverable
- **`compose_report.py`** — Assembles report.md + report.json (with embedded `coaching_payload` block, schema_version `v0.5.0-cap-table`); priced-round reports carry a source-document reconciliation section (computed vs source-stated PPS / pre-money / FD from `inputs.stated_totals`)
- **`concise_report.py`** — Concise-mode report: renders the headline numbers straight from `scenarios.json` (lightweight math path; skips counsel_packet / full compose / visualize / explore / coaching)
- **`verify_one.py`** — Single-question cited rule-pack lookup (`--rule-lookup <rule_id>` → the cited constant + reliance boundary; lightweight answer path, writes no artifact)
- **`visualize.py`** — Self-contained `report.html` (inline SVG donut, no CDN)
- **`explore.py`** — Self-contained `explorer.html` (vanilla JS interactive scenario picker; number tickers, donut value-morph, Sankey transition, card slide-in, and an optional pre-money sweep slider when `sweep.json` is present)
- **`sweep.py`** — Optional `sweep.json` generator: a pre-money parametric sweep (K real priced-round solver frames, `new_money` held fixed) powering the explorer's slider; reuses the existing `run_all_scenarios` path (no new math). Slider snaps to discrete real frames.
- **`extract_instrument.py`** — Lane-1 anti-hallucination validator (sub-agent does extraction; this validates returned JSON, normalizes `discount_multiplier` per Gotcha #3). Supports `--verify` / `--verify-blocking` / `--invariants` / `--cross-check` / `--source-doc` flags, all default-on; uses `--no-<flag>` to opt out. Skips evidence checks on a ~30-field synthesized-fields list (form, jurisdiction, derived counts, etc.).
- **`extract_cap_table.py`** — Lane-2/3/4 (validate mode + Carta/Pulley stub + freeform Context-A output validator). `--mode=freeform-emit` deterministically maps Lane-3 SPREADSHEET_STRUCTURE_DETECTION blocks → schema-valid `inputs.json`+`instruments.json` (founder answers to gate blockers via repeatable `--answer BLOCK.FIELD=VALUE`).
- **`freeform_mapper.py`** — Pure `map_freeform(blocks, grid, existing_inputs, answers)` behind `--mode=freeform-emit`. Maps detected blocks via the closed `references/schemas/freeform-role-map.json` contract; off-contract roles + required-but-unsupplied fields (interest_rate_type, preferred OIP, enum plan_type) become blockers (no fabrication); per-target-array stable ids; merges equity into existing inputs (keep-existing-on-conflict). Deterministic.
- **`pdf_probe.py`** — Per-page probe of whether a cap-table PDF has a text layer or is image-only (decides if OCR/table extraction is needed vs raw text). [dep: pdfplumber]
- **`extract_pdf_tables.py`** — OCRs an image-only cap-table PDF (no text layer) into a cell grid for ingestion.
- **`_docx_text.py`** — Tracked-changes-aware `.docx` reader (stdlib `zipfile` + `xml.etree`): `detect_tracked_changes()` + `extract_text(revisions="accept")` keep `<w:ins>` and drop `<w:del>` so accepted-redline terms survive (python-docx drops both).
- **`evidence_verifier.py`** — Forward verifier. Three-layer check (quote_in_doc / value_in_quote / value_in_doc) catching HALLUCINATIONS. 3.6% FPR / 100% TPR on the private eval set.
- **`backward_verifier.py`** — Backward verifier (two-phase `--phase=prompt`/`--phase=score` CLI). Catches SEMANTIC CONFUSION via fresh-sub-agent re-extraction. WARN-mode default.
- **`invariant_checker.py`** — Real-world-bounds checker. Per-field ranges + cross-field math invariants. 0% FPR / 63% TPR.
- **`cross_checker.py`** — Demote-only confidence modulator when multiple extractors disagree.
- **`_normalize.py`** — Shared text-normalization primitives (normalize_text, compact_form, numeric_tokens, date_tokens).
- **`extractors/`** — Span-preserving extraction module: `FieldExtraction`, `SourceSpan`, `ExtractionContext`, `ExtractorProtocol` types + 5 SAFE backstop extractors (`extractors/safe/`).

## Competitive Positioning Scripts

- **`validate_landscape.py`** — Validates competitor list structure, checks slug uniqueness, preserves provenance
- **`verify_competitors.py`** — Adversarial competitor-set verification validator (Step 3.5, before Gate 1): validates the COMPETITOR_VERIFICATION sub-agent's per-competitor verdicts (genuine/adjacent/not_a_competitor), enforces the show-your-work gate (a flag must carry reasoning + independent buyer/job characterization), cross-checks landscape slug coverage, computes summary. Validator, not detector. Catches false-positive competitors (surface-level matches that don't genuinely compete)
- **`score_moats.py`** — Scores 6+ moat dimensions per company with aggregates and cross-company comparison
- **`score_positioning.py`** — Scores pair-centric positioning views with rank-based differentiation and vanity detection
- **`checklist.py`** — Scores ~25 quality criteria across 6 categories with mode-based gating
- **`compose_report.py`** — Assembles report with cross-artifact validation, warning system, and accepted warnings
- **`visualize.py`** — Generates self-contained HTML with SVG positioning map, moat radar, competitor table; outputs HTML (not JSON)
- **`explore.py`** — Generates interactive HTML explorer with Chart.js scatter plot (vendored, no CDN for the 2D view; the optional 3D View tab lazy-loads Plotly from a CDN on demand), view switching, bubble encoding controls, and company detail panels; outputs HTML (not JSON)

## Dev Setup

Install dev dependencies:

```bash
uv sync --extra dev
# or: pip install -e ".[dev]"
```

## Linting & Formatting

```bash
uv run ruff check .          # lint
uv run ruff format .         # auto-format
uv run ruff format --check . # check formatting without changes
```

## Type Checking

Scripts in different skills share filenames (`checklist.py`, `compose_report.py`), so mypy must be run per directory:

```bash
uv run mypy founder-skills/skills/market-sizing/scripts/
uv run mypy founder-skills/skills/deck-review/scripts/
uv run mypy founder-skills/skills/ic-sim/scripts/
uv run mypy founder-skills/skills/financial-model-review/scripts/
uv run mypy founder-skills/skills/competitive-positioning/scripts/
uv run mypy founder-skills/skills/cap-table/scripts/
uv run mypy founder-skills/tests/
```

## Using `cowork-harness critique` (read before trusting a grade)

Measured workarounds, current through **1.15.0**. Full detail in
`docs/internal/2026-07-27-cowork-harness-issues.md`, plus the per-release adoption plans
(`docs/internal/2026-07-31-cowork-harness-1.14.0-adoption-plan.md` and `…-1.15.0-…`).

- **Evidence budgets — FIXED UPSTREAM, and the old advice is now backwards.** `critique` used to cap
  evidence at 64 KiB per SKILL.md and **8 KiB total** across all `references/`, silently, which cost LOST
  findings (`not-adjudicable`, never a false positive). It now ships skill-authored content **whole** —
  SKILL.md + every `references/**` + `agents/<skill>.md` — under a 512 KiB ceiling across all three
  combined, and cuts loudly by name in `evidenceBudget.corpusCuts`. Measured, our worst skill is 52% of
  that. **Two reversals:** `skillMdTruncated` is gone from the report (read `evidenceBudget.corpusCuts`
  instead, empty on every real skill), and *"never fix a SKILL.md size problem by moving prose into
  `references/`"* is **retired** — with a shared ceiling and whole packaging, relocation is neutral.
- **Know your critique corpus size, and know what counts.** `critique` packages **SKILL.md + every file
  under `references/` + `agents/<skill>.md`** against a 512 KiB ceiling; over it, content is cut before
  grading. Two traps we hit: **every file under `references/` counts regardless of extension** (cap-table's
  JSON schemas and rule packs were corpus, not just its markdown), and the agent body
  counts too though it lives outside the skill dir. Measuring `**/*.md` put cap-table at 52% when it was at
  98%. **Resolved 2026-08-01: `cap-table-rules.json` (144 KB, machine-read only) moved out of
  `references/` to `skills/cap-table/data/` — scripts and sibling data dirs are NOT corpus — taking
  cap-table to ~71% (370,905 B, ~153 KB headroom).** The lesson stands for future additions: a data file
  scripts read by path belongs in `data/`, not `references/`; only evaluator-citable evidence belongs there.
  Check free with `cowork-harness lint-skill <skill-dir>` (>=1.13.2; earlier
  versions omit the agent file and under-report). `test_skill_contract.py` guards the ceiling and
  cap-table's margin; `corpusCuts` in a critique report is the final authority.
- **`git add` an untracked skill file before you critique — but know which case you are in.** Staging only
  ever delivered git-tracked files to the agent, while the packager used to read the host directory, so the
  evaluator could see material the agent never received. Two different outcomes now, and conflating them
  misreads a report:
  - **Untracked `references/**` or `agents/<skill>.md` → EXCLUDED, named in
    `evidenceBudget.corpusExcluded`, with a `::warning::`. This is the CORRECT outcome, not a degraded
    one.** The evaluator's view now matches the agent's, so a finding like *"the skill never explains X"*
    against an excluded reference is **properly grounded**. Previously the evaluator saw a file the agent
    never got and marked that true finding `already-covered`.
  - **Untracked `SKILL.md` → `skillMdStatus: "untracked"`, content withheld, forces `not-adjudicable`** —
    coverage claims cannot be judged with no skill source at all. Only this case is a downgrade.
- **`noSkillFilesRead` is observational, and for ic-sim it is expected.** The 1.13.0 signal fires when the
  graded turn Read no `references/` or `scripts/` file — main agent or sub-agent. **ic-sim trips it on a
  complete, correct run** (measured: 21 artifacts, 22 bash calls, 5 sub-agents, zero reference reads), and
  that is by design: `evaluation-criteria.md` and `partner-archetypes.md` have their operative rubrics
  **inlined into `agents/ic-sim.md`**, and `partner-archetypes.md` is fund-specific-mode only. Do not
  "fix" it by adding reads. Treat the flag as a prompt to check whether the skill's references are
  documentation or operative — for ic-sim the answer is documented at `SKILL.md:73-75`.
- **Pre-upgrade critique reports: keep them.** Per-item verdicts are not comparable across the
  whole-content change, but aggregate counts are — the `not-adjudicable` count on identical prompts is the
  measure, and archived reports are the only "before" that exists. Report **per-skill, not
  fleet-aggregate**. Pair it with the `citationResolved:false` (DROPPED) rate as the guard in the other
  direction — a much larger corpus could make the evaluator's citations sloppier and nothing else would
  surface that. `costUsd` now also carries a per-pass token split (`{input, output, cacheRead}`), which
  answers "is this money evidence or thinking?" without a sweep.
- **Budget from `report.costUsd.totalUsd`, never from `index.jsonl`.** The index omits both evaluator
  passes, so summing it under-reports a critique by ~39% (measured: $10.17 vs $16.67 across three runs). **Fixed
  upstream:** each critique now writes a roll-up row carrying `critiqueTotalUsd`, so `sum(costUsd)` across
  rows is exactly true spend. The default task-turn timeout is also now 30 min (was 10), so `--timeout` is
  no longer needed for a fan-out skill. Note whole-content packaging costs **+5% to +18%** per critique.
  **`stats` was a separate, later bug** (fixed 1.14.0): it dropped every roll-up row before any filter
  ran, so a $1.0588 critique reported as $0.368 — 65–84% light. It now reports **`totalUsd`** (plus
  `unpricedRuns`, so a total that is a floor says so); counts, rates and percentiles stay per-run and are
  unchanged. The manual-sum guidance above was always correct — the roll-up partition is exact by design.
- **Always pass `--out <skill>.json`.** The index cannot attribute a critique: it records
  `command: "skill"` (not `critique`), carries no `skill` field despite `--skill`, and `session.json` has
  neither `skill` nor `prompt`. Concurrent critiques are otherwise indistinguishable. `--label` still
  lands on turn 1 only — deliberately, since labelling the reflection turn would inject a near-always-green
  row and inflate `passRate` — but as of 1.14.0 a label-filtered **cost** total is no longer short: `stats`
  re-admits the dropped rows by shared `runId`, counting them toward cost only, never toward
  `runs`/`passRate`/percentiles.
- **There is no progress output on stdout** — logs stay at 0 bytes for the whole run, then emit the
  full report. Do NOT poll the outputs dir for artifacts (the advice that used to live here): use
  **`cowork-harness status <dir> [--follow]`**, which reads the `status.json` the harness maintains
  throughout the lifecycle. It reports `state` / `elapsedMs` / live `toolCounts`, and detects both a
  thrown error and a `SIGKILL`/OOM staleness — so `"running"` is never permanently trusted, which
  artifact-watching cannot tell you. The run prints `[status] <outDir>` to stderr at startup — **except
  under `--compact`/`--demo`**, which withhold it deliberately (it is a raw host path). `status.json` is
  written either way, and `cowork-harness status` also accepts the run-dir root.
- **A green run is no longer silent — read the verdict footer.** As of 1.14.0 it prints `warn`-severity
  signals on pass and fail alike, prefixed `·` (`undelivered_deliverables`, `ended_with_question`,
  `scan_unavailable`, `exec_infra_error`, `prompt_asset_missing`). Before that, every warn on a passing
  run reached `result.json` and no human-read surface. A single run's footer also now reports its cost.
- **A/B-ing a skill change? `stats <scenario> --group-by skill-hash --runs` is the whole comparison in
  one command** (harness 1.14.0+). Runs from before and after an edit pile up in the SAME scenario dir,
  and `stats` used to blend them into one aggregate with no warning — measured: `stats <scenario>
  --last 10` reported "5 runs" spanning three different skillHashes. That silent blend is now a
  `::warning::` driven by `distinctSkillHashes`, and `--skill-hash <prefix>` (the 12-char index prefix
  or the full hash from `result.json`, 6-char floor) and `--label <tag>` narrow it. `--group-by` also
  takes `scenario|label|fidelity`; `--runs` lists the individual runs behind each summary (timestamp,
  verdict, runId, skillHash, runLabel, fidelity, cost, duration, `(pruned)`). Rows lacking the grouped-on
  field are reported as `hashlessRuns`, never bucketed under a blank key. `--since <date>` remains only
  a proxy and still breaks the moment two versions run on one day.
- **Never pipe `verify-cassettes` to `tail`** — deterministic `EAGAIN` crash (unbuffered `writeSync` to a
  non-draining pipe) that replaces the verdict line with a stack trace. Redirect to a file instead.
- **`source cowork-tests/privacy-allowlist.sh` before the PII gate.** A bare
  `verify-cassettes cowork-tests/cassettes` reports ~7,200 findings and exit 1; with CI's class-scoped
  allowlist it is `✓ 16 cassette(s) clean`. Those are synthetic deal amounts and public citation domains,
  not leaks.
- **`--fidelity cowork`, as of harness 1.14.0.** The default is `container` — a *different* tier from
  what the cassettes record at, so an unqualified critique is not a production-parity grade. `cowork` was
  refused until 1.14.0 (the old advice here was `hostloop`, always); it is now accepted and is the better
  choice, because it resolves via the pinned baseline's loop gate instead of hardcoding a tier that can
  drift from it. Resolution happens **once, before either turn spawns**, is echoed as `[loop] cowork →
  <tier>` on stderr, and is reported as `requestedFidelity` beside the tier that ran. `microvm`/`protocol`
  stay refused; **`chat` still refuses `cowork`**. Note `--dotenv`: the child CLI loads that file before
  deciding, so a `CLAUDE_FORCE_HOST_LOOP` in `./.env` is read during resolution (read, not applied to
  critique's own env).
- Report items carry `idea` / `recommendedAction` / `evidence` / `source`. There is **no `title`**.
- **Corrected in 1.17.0 — re-check anything you concluded from the old docs.** Three of these were
  documented wrongly before, so a scenario written against the old text can be unassertable rather than
  merely wrong. **`semantic_matches` judges a much narrower document than "the union of the final
  message, the transcript, and any authored files"**: the transcript is **top-level `assistant_text`
  only** — no `tool_use`/`tool_result`, and **no sub-agent text at all**, including fork-scoped
  `Skill`/`Agent(fork)` dispatches. So a rubric claim like *"the agent used a tool to surface the file"*
  **can never grade true**, regardless of behaviour — the evidence is not in the document. Use
  `tool_called` / `present_files_called` / `subagent_dispatched` instead, or opt in to
  `semantic_matches: {include_subagent_text: true}` (new in 1.17.0; it enlarges the judged document, so
  it can re-grade an existing rubric). This fleet uses no `semantic_matches` today — keep it that way
  unless you have read this row. Also: **`subagent_dispatched`** is the real key; four upstream surfaces
  spelled it `subagent_dispatch` (no trailing "ed"), which does not exist — our scenarios use the correct
  form, verified. And `present_files_called` is **still** `z.literal(true)` / "at least one file", with no
  per-file match, re-verified against 1.17.0 — which is why `cowork-tests/delivery_check.py` still exists.

## Running Tests

```bash
uv run pytest                                       # all tests (e2e auto-skips without auth; cowork auto-skips without the harness CLI)
uv run pytest founder-skills/tests/ -v              # verbose
uv run pytest founder-skills/tests/ -v -m "not e2e" # explicitly skip the LLM-driven e2e (free, fast)
uv run pytest -m cowork                             # token-free cowork-harness cassette replay (needs `npm i -g cowork-harness@^1.17.0`; no Docker/token)
```

**A skill's own test file is not what guards it.** `test_<skill>.py` covers the producers;
`test_<skill>_skill_contract.py` covers the SKILL.md / agent-body contracts, and there are
cross-cutting guards besides (`test_skill_contract.py` size ceilings, `test_cowork_invariants.py`
tool declarations, per-script suites like `test_backward_verifier.py`). Editing a SKILL.md or an
agent body and running only the matching `test_<skill>.py` reports green while the contract tests
fail. Run `-m "not e2e"` before believing a skill change is done.

**Contract tests slice a fixed character window from an anchor** (`skill_text[start : start + N]`).
An additive edit to a dispatch template can push the tail past that boundary, so the test fails on
content that is still present. Prefer bounding on structure — the template's closing fence, the next
`##` heading — over widening N, which only defers the next break.

The `cowork` lane (`tests/test_cowork_cassette_replay.py`) replays the committed
`cowork-tests/cassettes/` through the harness's shipped pytest helper — deterministic,
no Docker or token. It is a **local-dev showcase**, not wired into `ci.yml` (the packaged
GitHub Action already replays in the `cowork-replay` workflow); it auto-skips when the
`cowork-harness` CLI is absent, so the default `uv run pytest` stays green on machines
without it.

The deck-review e2e smoke (`tests/test_e2e_deck_review.py`) drives the SDK against a synthetic fixture. Auth options (any one):

- `ANTHROPIC_API_KEY` env var (per-token API; ~$5-15/run)
- `CLAUDE_CODE_OAUTH_TOKEN` env var (subscription, long-lived token from `claude setup-token`)
- Local subscription auth: `claude /login` populates the macOS Keychain entry `Claude Code-credentials` (or `~/.claude/.credentials.json` on Linux/Windows)

For live progress during the e2e run (~5-20 min wall time), add `-s`:

```bash
uv run pytest founder-skills/tests/test_e2e_deck_review.py -v -m e2e --tb=short -s
```

Without `-s` the run looks silent (pytest captures stdout); with `-s` you see auth-detected, prompt, and per-message tool calls (`Bash`, `Read`, `Skill`, `Task`, etc.) as the SDK stream arrives.

The `e2e` marker keeps these tests out of the default per-PR `ci.yml` run; they execute only in the dedicated `skill-quality.yml` workflow.

## Internal Docs

- `docs/internal/` — Design docs and internal notes; never tracked or committed (gitignored)

## Hooks

- **SessionStart** (`founder-skills/scripts/session-setup.sh`): Persists `CLAUDE_PLUGIN_ROOT` into `CLAUDE_ENV_FILE` so scripts can locate plugin files at runtime.
- **pre-commit** (`scripts/hooks/pre-commit`): ruff format/lint on staged Python + the privacy-leak guard. Activate once per clone: `git config core.hooksPath scripts/hooks`. Bypass a confirmed false positive with `git commit --no-verify`.
- **commit-msg** (`scripts/hooks/commit-msg`): DCO gate — rejects a commit with no `Signed-off-by:` trailer matching the commit author. Validates only; it deliberately does not auto-append the trailer (a sign-off certifies that *you* have the right to submit, so a hook adding it silently would certify on your behalf).

## Committing (read before any `git commit`)

**Always commit with `git commit -s`.** This repo requires a DCO sign-off on every commit, and `DCO` is a required status check on `main` — an unsigned commit blocks any PR containing it. The `commit-msg` hook will reject an unsigned commit, but reaching that rejection means a wasted round-trip: pass `-s` the first time.

`-s` composes with everything, including the heredoc pattern used throughout this repo:

```bash
git commit -s -F - <<'EOF'
type(scope): subject
...
EOF
```

The trailer is appended to the existing trailer block, after `Co-Authored-By:` / `Claude-Session:`. Order within the block does not matter. To fix a commit already written: `git commit --amend -s`.

Historical note: 155 of the first 159 commits are unsigned, because `enforce_admins` is false on `main` and direct pushes bypass the required check. Do **not** retro-sign them — that would rewrite published history. The convention is that a DCO check only inspects the commits in a given PR, so existing history is grandfathered.

## Privacy Guard

`scripts/privacy_guard.py` blocks confidential-data leaks **without committing the names it guards**. Three layers:

- **document** — confidential doc types (`.xlsx`/`.pdf`/`.docx`/…) tracked outside the synthetic-fixture allowlist (add a new legit fixture to `ALLOWLISTED_DOCS`). Name-free.
- **provenance** — the named-after-a-company antipattern triple: a proper-noun company name + a `P-#`/`R-#` round/case ID + a failure word, together (template `the <ProperNoun> <round/case-ID> <failure-word>`). High-precision; name-free.
- **name** — exact real names from `docs/internal/privacy-denylist.txt`, which is **git-ignored and never committed** (the detection logic ships; the names don't). List only distinctive names/phrases — never bare common-word names. CI runs `--tree --no-names` (layers 1+2 only; no name list present), so nothing is disclosed.

Run manually: `uv run python scripts/privacy_guard.py --staged` (or `--tree`). Tests: `uv run pytest scripts/test_privacy_guard.py`. CI enforces layers 1+2 in the `privacy` job.

## SKILL.md Conventions

Verified against the Claude Code v2.1.120 skill runtime contract and Desktop v1.6259.1 architecture:

- **Env vars in skill bodies:** Use `${CLAUDE_PLUGIN_ROOT}` (braced form) — the plugin content expander substitutes it at load time. Bare `$CLAUDE_PLUGIN_ROOT` only resolves at Bash subprocess time and depends on `CLAUDE_ENV_FILE` being sourced; the gist flags this as unconfirmed for skill subprocesses. The braced form is the contract.
- **Frontmatter keys** must come from the documented set: `name`, `description`, `when_to_use`, `allowed-tools`, `argument-hint`, `arguments`, `context`, `agent`, `model`, `effort`, `user-invocable`, `disable-model-invocation`, `paths`, `hooks`, `shell`, `created_by`. (`version` is parsed but tagged "[Undocumented] Informational only" in gist 1 — don't rely on it.) Custom keys are silently dropped — put human-readable metadata in a `## Skill Metadata` body section instead. **Avoid undocumented nested structures** (e.g. don't add a custom `metadata: {…}` block). The documented fields that *do* take structured values (`shell.interpreter`, `hooks.PreToolUse`, `paths` list, `arguments` list) are fine — they're explicitly specified.
- **Two parsers, two discovery outcomes (important):**
  - The **CLI runtime** (when invoking a skill) reads the full documented set above via a YAML parser.
  - **Desktop's skill discovery scanner** is **regex-based**, supports `>` and `|` block scalars, and only recognises **`name`, `description`, `argument-hint`, `user-invocable`**. Per gist 2 §"Skill discovery logic", this scanner gates *whether the skill is discovered at all* in Desktop/Cowork — not just what the UI displays. A SKILL.md whose frontmatter the regex parser can't navigate may fail to register entirely.
  - **`when_to_use` is invisible to Desktop** — only the CLI runtime reads it. So mirror the key trigger phrases into `description` (which Desktop *does* read) for users browsing the Settings UI to find your skill.
  - Undocumented nested YAML (e.g. a custom `metadata: {…}` block) can confuse the regex parser — even though the keys would be dropped semantically, the parser still has to walk past them and may misparse adjacent fields. Stick to the documented set; if you need structured config, use one of the documented structured fields.
- **`description` + `when_to_use` budget:** combined length per skill ≤ 1,536 chars. Across all skills, keep the sum ≤ 6,000 chars (8,000 is the absolute fallback floor; below 20 chars/skill, the entire listing collapses to name-only). The total-listing-budget regression test enforces this.
- **No shell substitution `` !`cmd` `` or fenced `` ```! `` blocks.** Heavy work belongs in scripts the model runs via Bash tool calls — see existing `Phase 0` setup in any SKILL.md.
- **Regression test:** `founder-skills/tests/test_skill_contract.py` enforces all of the above. Run before opening a PR that touches a SKILL.md.
- **Pre-publish validation:** Run `claude plugin validate founder-skills` to validate manifests against the CLI's schemas (requires CLI v2.1.131+). CI does this automatically on every PR.

## Release Process

Tag-push triggers `deck-review-e2e-smoke` in `.github/workflows/skill-quality.yml`. The workflow's preflight step fails fast if the tag does not match both `pyproject.toml` and `founder-skills/.claude-plugin/plugin.json` versions — version-bump errors are caught before the paid SDK call (~5 sec, no cost). Per-PR e2e is off by default; opt in via manual dispatch for architectural-surface PRs (list below).

### Release ordering

0. **Refresh cowork cassettes** (release cadence): `cowork-tests/rerecord.sh` (paid/local; it preflights `cowork-harness doctor --tier hostloop` — needs Docker, the `:2` agent image, and BOTH staged agent binaries: the Linux/arm64 ELF and the native Desktop host binary the hostloop agent loop spawns) → confirm green, commit refreshed `cassettes/` by name. Since the 0.24.0 pin, `fidelity: cowork` records at **native hostloop** (real host paths in transcripts, stripped by the `cowork-tests/.cowork-redact.json` redaction policy at record time — `record` refuses to write a cassette whose asserts or `computer://` links redaction broke). `rerecord.sh` records in a bounded parallel pool, prints a normalized `cowork-harness diff` per refreshed cassette (the primary drift review), and tails `stats` + `prune`; runs land in the harness-default `~/.cowork-harness/runs` so `stats` can trend reliability across re-records. The cowork-replay staleness gate is WARN-only, so cassettes drift between releases; this re-records them against the current baseline/format. Skip only if no skill/`scripts/`/`references/`/`agents/` change landed since the last refresh. `rerecord.sh` enforces a **harness floor of `>=1.12.0`** — recording is the one operation that bakes the harness version into the artifact: **1.12.0 fixes a bug that made an upload-bearing scenario impossible to record while still spending the paid run** (the artifact↔root check measured `uploads/` artifacts against the user-visible roots, which exclude uploads, and threw *after* the agent run — five scenarios here are upload-bearing), 1.11.0 stamps `environment.harnessVersion` (never backfilled, so an older CLI records a permanently provenance-less cassette), and 1.10.0 is the first release whose sandbox declares the skill/plugin discovery SDK-MCP servers (an older CLI freezes a tool inventory five tools short of what real Cowork advertises). **Committed cassette state, re-measured at `HEAD` 2026-08-01 (`cf0277a`): 21 tracked — 19 at harness `1.16.0`, 2 at `1.12.0`** (`ic-sim-smoke`, `market-sizing-smoke`); `cassetteVersion` is 10 except the `lane: remote` one, which is v11. (This line previously said "all 16, recorded at 1.12.0" — **re-derive it after every re-record rather than trusting the number here**; it has now been wrong twice.) The v9-read-floor urgency that used to live here is spent, and so is the outstanding 1.10.0 discovery-surface refresh — that re-record happened. What remains is ordinary `skillHash` staleness, which the WARN-only gate reports and only a re-record clears. A future read-floor raise would refuse them at load time and `rehash` cannot cross a version boundary, so the next floor bump still means a re-record — but that is a future event, not a live risk. The bare form refreshes only scenarios that already have a committed cassette (it prints what it skipped); author a new cassette by name.

**Re-record trigger (beyond "a skill changed"):** re-record on every harness **major**, *and* on any release — including a minor — whose changelog reports a change to the **emulated tool surface, spawn env, or system prompt**. Those are the fidelity inputs with no automatic staleness tripwire, so nothing will tell you: the changelog is the authority. `1.10.0` was the first such minor (it added the discovery SDK-MCP servers) and **that debt is settled** — every committed cassette is at `1.12.0` or later, which necessarily carries them. The `1.14.0` trigger (`present_files` served at **hostloop**, the tier this fleet records at, where the harness previously served it only at `container`, so a recording froze a toolset one `alwaysLoad` tool short of production's) is **now discharged for 19 of 21** — see the measured note below. The two remaining `1.12.0` cassettes still carry the short toolset. (`1.15.0` adds no re-record debt: a CLI flag, a notice and docs, with `baselines/` and `schema/` byte-identical to 1.14.0.) Full analysis: `docs/internal/2026-07-31-cowork-harness-1.14.0-adoption-plan.md`.

**`1.17.0` adds no re-record debt either — verified, not assumed.** `baselines/desktop-1.24012.9.json` DID change between `v1.16.0` and `v1.17.0`, so the byte-identical test that cleared 1.15.0 does not apply; the change had to be read. Diffing the parsed baseline field-by-field: `spawn.tools`, `spawn.allowedTools`, `spawn.env`, `spawn.promptTemplate`, `spawn.subagentPrompt`, `spawn.options` and `spawn.effortDefault` are **byte-identical**. The only additions are a `hooks` object and its `$comment_hooks`, which the harness itself labels "Recorded as a DRIFT TRIPWIRE, not an emulation source — `served` marks what this harness actually installs (`PreToolUse:Task` only)". So none of the three fidelity inputs (tool surface, spawn env, system prompt) moved. **When a future release touches `baselines/`, run that field-level diff rather than a file-level one — a changed baseline is not by itself a re-record trigger.**

**The `1.14.0` `present_files` trigger is DISCHARGED and COMMITTED** (as of `cf0277a`). Measured at `HEAD` with `git show HEAD:<path>`: **21 tracked cassettes — 19 at `harnessVersion: 1.16.0`, 2 still at 1.12.0** (`ic-sim-smoke`, `market-sizing-smoke`). 1.16.0 is >= 1.14.0, so those 19 necessarily carry the hostloop `present_files` surface; the two stragglers do not, and are the remaining scope. This supersedes the older "committed cassettes are all 1.12.0 (verified across all 16)" line above — **that sentence is now wrong; re-derive rather than trusting either.**

One cassette is stale for a *different* reason that a re-record cadence will not catch: `market-sizing-remote-lane` was recorded at 1.16.0 and froze the spurious `undelivered_deliverables` warn that 1.17.0 fixes, so its warn set asserts something false about delivery. Re-record that scenario specifically (`rerecord.sh` now floors at `>=1.17.0`).
1. Bump versions in `pyproject.toml` and `founder-skills/.claude-plugin/plugin.json` (must match)
2. Update `CHANGELOG.md`
3. `git commit -m "release: vX.Y.Z"`
4. `git push`
5. `git tag vX.Y.Z && git push --tags`
6. **Wait for `deck-review-e2e-smoke` green** in the GitHub Actions UI
   - Tag failure: `git tag -d vX.Y.Z && git push origin :refs/tags/vX.Y.Z`, fix, retag — no user impact yet (sync hasn't happened)
   - LLM-variance flake: re-run the job from the Actions UI (free retry, same SHA)
7. **Only after green:** `./scripts/sync-test-repo.sh`

`sync-test-repo.sh` is a local, untracked TESTING step — it pushes the working tree to the private test repo (`yaniv-golan/founderskills-test`) so the release can be exercised in Cowork before users see it. It is NOT the user-facing distribution event: users install from the marketplace clone that tracks `main`, so `plugin.json#version` on `main` is what they actually pick up (see VERSIONING.md). Run the test sync only after the release gate is green — syncing a broken build means the test pass exercises a build you'd never ship.

**Model-tier acceptance:** when adopting or recommending a new model tier, run the cap-table reliability bench (`evals/cap-table/run_reliability_bench.py`, see its `README.md`) and record the per-tier correctness; Sonnet 4.6 is the support floor. (The bench lives at repo-root `evals/` — outside the distributed `founder-skills/` plugin — so it isn't shipped to users, mounted into cowork runs, or folded into the cassette staleness hash.)

**Already-distributed retag pitfall:** if `sync-test-repo.sh` ran before you noticed the bug, **bump to the next patch version instead of retagging** — Cowork caches by `plugin.json#version`, so retagging the same version will not refresh user caches (`cpd refresh ... --force-fetch -y` is the manual recovery, not always coordinatable across users).

### When to manually dispatch e2e on a PR

Per-PR e2e is off by default. Manually dispatch (`gh workflow run skill-quality.yml --ref <pr-branch>`) when the PR touches architectural surface that contract tests don't fully cover:

- `founder-skills/skills/*/SKILL.md` (frontmatter or trigger phrases)
- `founder-skills/agents/*.md` (tool declarations, model, frontmatter)
- `founder-skills/.claude-plugin/plugin.json`
- `founder-skills/scripts/session-setup.sh` (mutates `CLAUDE_ENV_FILE`; downstream skills depend on it)
- `founder-skills/skills/*/scripts/compose_report.py` (the `coaching_payload` contract — structurally checked by `test_compose_invariants.py`, but only e2e exercises end-to-end)
- `founder-skills/tests/test_e2e_deck_review.py` (the SDK invocation itself)
- `founder-skills/tests/cowork_async_subagent_filter.py` and `compose_invocations.py` (CI-helper meta — if these break, contract tests pass vacuously)
- `pyproject.toml` `dependencies` list or `[project.optional-dependencies]` block (any runtime dep can shift SDK behavior)

Other PRs (skill-internal scripts, fixtures, docs, contract tests): contract tests are sufficient — skip the $10.

## Installing the Plugin in Claude Cowork

Customize → Plugins → the **+** at the right of the Anthropic/Partners/**Personal** tab row →
**Add marketplace** → **Add from a repository** → pick `lool-ventures/founder-skills` in the **URL**
picker → **Sync** → then **+** on the *Founder skills* card to install.

There is no "Personal Plugins" list and no "Browse Plugins" — that was an older layout. The two `+`
buttons are distinct: tab-row `+` adds a *marketplace*, card `+` installs a *plugin*. Syncing alone
installs nothing. To refresh an installed plugin, use **Check for updates** on the marketplace's `⋯`
menu, which enables the plugin's **Update** button.

(Verified against the live UI 2026-07-29; captures under `docs/internal/cowork-ui-validation-2026-07-28/`.)

**Start a new Cowork session** after installing — already-running sessions won't pick up the plugin.

## Local CLI Testing with `--plugin-dir`

For iterating on plugin code in the standalone Claude Code CLI (host CLI, not Cowork), bypass the marketplace machinery entirely. From the repo root:

    claude --plugin-dir "$PWD/founder-skills"

This loads our plugin for the session only:
- No marketplace clone
- No `installed_plugins.json` entry
- No enabled-state in settings
- No interaction with Desktop's "Update available" badge or refresh flow
- Gone the moment the session exits

**Use for:** rapid local iteration on SKILL.md / agents / scripts when you don't want to reinstall after every change.

**Caveats:**
- Host CLI only. Cowork uses a VM-pinned binary at `~/Library/Application Support/Claude/claude-code-vm/<version>/claude` (Linux ARM64 ELF) and has no equivalent flag exposed through Desktop.
- Managed-policy block lists still apply — a blocked plugin name fails to load.
- Repeatable for multi-plugin testing: `--plugin-dir A --plugin-dir B`.

## Updating Plugin Files in Cowork Without Reinstalling

Cowork caches plugin files per-session. To hot-patch files for testing without reinstalling:

1. Find the session cache:
   ```bash
   find ~/Library/Application\ Support/Claude/local-agent-mode-sessions -name "SKILL.md" -path "*ic-sim*" 2>/dev/null
   ```

2. There are typically 4 copies per session — 2 marketplace names × (`cache/` + `marketplaces/`):
   ```
   cowork_plugins/cache/<marketplace>/<plugin>/<version>/
   cowork_plugins/marketplaces/<marketplace>/<plugin-dir>/
   ```

3. Copy modified files into all locations:
   ```bash
   SRC="founderskills"
   COWORK_BASE="$HOME/Library/Application Support/Claude/local-agent-mode-sessions/<org-id>/<session-id>/cowork_plugins"
   TARGETS=(
     "$COWORK_BASE/cache/<marketplace1>/<plugin>/<version>"
     "$COWORK_BASE/cache/<marketplace2>/<plugin>/<version>"
     "$COWORK_BASE/marketplaces/<marketplace1>/<plugin-dir>"
     "$COWORK_BASE/marketplaces/<marketplace2>/<plugin-dir>"
   )
   for target in "${TARGETS[@]}"; do
     cp "$SRC/skills/ic-sim/SKILL.md" "$target/skills/ic-sim/SKILL.md"
     # ... repeat for each modified file
   done
   ```

4. **Start a new Cowork session** — already-running sessions have already loaded skill bodies into context.

### Verifying the Marketplace Clone Actually Advanced

Cowork's "Refresh" can succeed without the local clone's git HEAD advancing — `CLAUDE_CODE_PLUGIN_KEEP_MARKETPLACE_ON_FAILURE` and the SSH↔HTTPS fallback both absorb `git pull` failures silently while still bumping `lastUpdated`. The same trap exists for the standalone Claude Code CLI's marketplace cache.

Use [`claude-plugin-doctor`](https://github.com/yaniv-golan/claude-plugin-doctor) (`cpd`) — it diagnoses drift across all six cache layers of the Claude Code / Claude Desktop plugin system, not just the marketplace clone.

```bash
npm install -g claude-plugin-doctor
```

**The full safe dev loop is:**

1. `./scripts/sync-test-repo.sh` — push your changes to the test repo.
2. **In the Cowork UI**, click Refresh on the marketplace.
3. **In your terminal**, run `cpd refresh lool-founder-skills` to confirm the clone advanced and surface any other drift.
4. If the clone is stale, run `cpd refresh lool-founder-skills --force-fetch -y` — bypasses the broken refresh path with a direct `git fetch && git reset --hard`.
5. Click Update on the plugin in Cowork (or use `cpd refresh lool-founder-skills --auto-update`).
6. Open a new Cowork task to pick up the new content.

Run `cpd refresh` after clicking Refresh in step 2 — Cowork's Refresh is async and user-triggered, so it can't be wired into `sync-test-repo.sh` automatically.

**Always run `cpd check founder-skills@lool-founder-skills` before debugging "why isn't my new SKILL.md being picked up"** — it produces a single-plugin drift report across all six cache layers (marketplace clone, install snapshot, enabled state, RPM, session mounts, content-hash sync). Half the time the answer is the clone never moved; the other half it's a different cache layer.

## Removing / Refreshing a Plugin in Claude Code / Cowork

There is no UI to remove a marketplace. Edit config files directly.

### Claude Code (CLI)

- `~/.claude/plugins/known_marketplaces.json` — delete the marketplace entry
- `~/.claude/plugins/installed_plugins.json` — delete any `pluginname@marketplace` entries
- `~/.claude/plugins/cache/<marketplace>/` — delete to reclaim disk space

### Cowork (Desktop App) — stale version troubleshooting

When Cowork won't pick up a new version, nuke all three locations:

```bash
BASE="$HOME/Library/Application Support/Claude/local-agent-mode-sessions/<org-id>/<user-id>/cowork_plugins"
rm -rf "$BASE/cache/<marketplace>"
rm -rf "$BASE/marketplaces/<marketplace>"
rm -f "$BASE/.install-manifests/<plugin>@<marketplace>.json"
```

Then remove the entries from `known_marketplaces.json` and `installed_plugins.json`, restart Cowork, and re-add the marketplace.

**Tip:** `installed_plugins.json` pins a `gitCommitSha` — compare against `git rev-parse HEAD` to check freshness.

**Pitfall:** When deleting an entry from these JSON files, ensure the preceding entry's trailing comma is removed if it becomes the last entry. A trailing comma produces invalid JSON that `JSON.parse()` rejects, causing "Failed to add marketplace" errors in Cowork.
