# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- **Skill-quality CI** — new GitHub Actions workflow `.github/workflows/skill-quality.yml` runs multiple layers of defense, ordered by speed and cost:
  1. **Contract tests** (per-PR): SKILL.md frontmatter invariants enforced via YAML parse (`user-invocable: true` present, `disable-model-invocation` absent, braced `${CLAUDE_PLUGIN_ROOT}`); per-agent persistence-tool-name compatibility against Cowork's sub-agent tool registry (the v0.3.1 invariant); sub-agent-cue-followed-by-bash-block regression detector (the v0.4.0 failure pattern); SKILL.md does-not-depend-on-SessionStart-hook invariant (gist 2026-05-10: plugin hooks don't fire in Cowork).
  2. **Compose invariants** (per-PR): every skill's `compose_report.py` emits a structured `coaching_payload` block; `STALE_ARTIFACT` warning surfaces on mismatched `metadata.run_id` across artifacts. Compose invocations are dispatched via a registry (`compose_invocations.py`) so per-skill CLI variation doesn't leak into test bodies.
  3. **End-to-end smoke** (per-PR, internal only): `deck-review` runs against a synthetic seed-stage fixture deck via `claude-agent-sdk` (plugin loaded via `plugins=[{"type": "local", "path": ".../founder-skills"}]`, `CLAUDE_PLUGIN_ROOT` passed via `env=`, model invokes the skill via the `Skill` tool). Asserts artifact existence, schema validity, `score_pct` in expected range, `run_id` parity, `coaching_payload` shape.
- `founder-skills/tests/cowork_async_subagent_filter.py` — tool-name compatibility check against Cowork's sub-agent tool registry. Mechanism: the desktop-side scope exclusion removes 5 tool names (`Bash`, `NotebookEdit`, `REPL`, `JavaScript`, `WebFetch`) from the registry BEFORE the CLI's filter runs; Bash is replaced by `mcp__workspace__bash` (deferred MCP tier). Names that DO resolve in sub-agent contexts (Read/Edit/Glob/Grep/WebSearch/etc.) are listed in the helper's `COWORK_ASYNC_SUBAGENT_ALLOWLIST` constant. Explicitly NOT a Cowork environment simulator (does not model PTY, bridge transcripts, env strip, hooks, classifier pipeline, etc.) — see file header for the boundary.
- Synthetic deck fixture (`founder-skills/tests/fixtures/decks/synthetic-seed-deck.txt`) and golden expected-output file (`founder-skills/tests/fixtures/golden/deck-review/synthetic-seed-deck.expected.json`) for the deck-review e2e smoke. Deck-review compose-invariant fixture set (`founder-skills/tests/fixtures/deck-review/`) — synthetic Acmecorp seed-stage data, no real founder data per MEMORY.
- `claude-agent-sdk==0.1.80` added to dev dependencies (pinned per Task 8 — pre-1.0 SDK with API churn).
- `pythonpath = ["founder-skills/tests"]` added to `[tool.pytest.ini_options]` so test files can import sibling helper modules (`cowork_async_subagent_filter`, `compose_invocations`) by bare name.

### Changed

- `pyproject.toml` `version` bumped from `0.4.2` to `0.4.4` to match `plugin.json`. Earlier drift between the two files is fixed.
- Existing `ci.yml` test job scoped to `-m "not e2e"` to prevent the deck-review e2e smoke from running twice per PR (once here, once in `skill-quality.yml`).
- `deck-review`, `financial-model-review`, `ic-sim`, and `competitive-positioning` SKILL.md files: added `<!-- skill-quality-ci: bash-after-subagent-ok -->` suppression markers above the legitimate Context-B `coaching_payload` extraction blocks. The Task 4 heuristic now correctly identifies these as main-thread payload extraction (not v0.4.0 failure pattern).

### Notes

- The workflow has no nightly cron; Phase D (full-suite e2e for the other 4 skills) is incremental follow-up work and a cron will be added when the body exists.
- **e2e wall time + cost (calibrated against first real run, 2026-05-10):**
  - **Wall time: ~15 minutes per run** (measured: 928s / 15:28). Earlier `60-180s` projection was a guess; revised on first measurement. Realistic range: 5-20 min depending on LLM dispatch decisions. The chain is sequential `Task` dispatches (Phase A → checklist → compose → coaching), each 30-90s.
  - **Cost on `ANTHROPIC_API_KEY`: ~$5-15 per run** (revised upward from the earlier $2-5 projection based on the realistic dispatch count). Set the `ANTHROPIC_API_KEY_CI` monthly spend cap based on observed cost × expected PR volume × 1.5 safety margin.
  - **Cost on Claude Pro subscription:** ~50+ messages consumed per run against the per-5-hour cap (~45 on Pro). **One e2e run can blow the entire Pro cap for that 5-hour window** — interactive Claude Code use during that window is rate-limited. Pro is **NOT viable for per-PR CI**; only viable for occasional manual local runs.
  - **Cost on Claude Max subscription:** ~3-4 runs per 5-hour window (~225 message cap). Workable for moderate PR volume but rate-limits on bursty days.
  - **Recommended for sustained CI:** `ANTHROPIC_API_KEY` (per-token billing with spend cap). Subscription paths are documented for local-dev convenience; they are not the recommended CI auth.
- **e2e auth: three paths supported.** The smoke test accepts any of:
  1. `ANTHROPIC_API_KEY` env var (per-token API billing; recommended for CI)
  2. `CLAUDE_CODE_OAUTH_TOKEN` env var (subscription via long-lived token from `claude setup-token`; set as `CLAUDE_CODE_OAUTH_TOKEN_CI` repo secret. **Check Anthropic's ToS for automated/programmatic use at scale before relying on it for CI.**)
  3. Local subscription auth: macOS Keychain entry `Claude Code-credentials` (after `claude /login`) or `~/.claude/.credentials.json` on Linux/Windows — for local dev runs only; not applicable in CI.
- The workflow env-injects BOTH `ANTHROPIC_API_KEY_CI` and `CLAUDE_CODE_OAUTH_TOKEN_CI` if set; the SDK / `claude` CLI picks whichever it finds. Configure exactly one in repo secrets (recommend `ANTHROPIC_API_KEY_CI`).
- **End-to-end verification:** PENDING — replace with `verified against the synthetic deck-review fixture on YYYY-MM-DD; CI green on PR #N` after running Task 12 Steps 2-3 with `ANTHROPIC_API_KEY` set + a draft PR pushed. (Per plan Task 11 Step 1 convention; the line lives in the changelog as a non-deniable record once verification runs.)
- **Open gaps requiring user action before merge:**
  1. **Manual SDK verification (Task 9 Step 1):** the e2e smoke pattern (`plugins=` + `setting_sources=[]` + `skills="all"` + `env={**os.environ, ...}`) needs one manual run with `ANTHROPIC_API_KEY` set to confirm the SDK actually loads the deck-review skill and the test passes against a real LLM dispatch. Without this, the e2e test is a structurally-valid skeleton but not load-bearing.
  2. **Cowork Skill-tool probe (Task 4.5):** `docs/internal/cowork-skill-tool-probe-2026-05-09.md` (gitignored) documents the probe agent body and the manual Cowork dispatch needed to empirically verify that the literal `Skill` name resolves in Cowork sub-agent contexts. Until run, the helper's inclusion of `Skill` in `COWORK_ASYNC_SUBAGENT_ALLOWLIST` is documentation-driven, not empirically confirmed.
  3. **GitHub Actions secret:** configure ONE of `ANTHROPIC_API_KEY_CI` or `CLAUDE_CODE_OAUTH_TOKEN_CI` in repo settings before the `e2e-smoke` job runs successfully on internal PRs. See the "e2e auth: two paths supported" note above for trade-offs.

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
