# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [0.3.0] - Unreleased 

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
- Deck Review expanded from 142 to 253 lines with: 5-item ingestion pitfalls guide (image-only PDFs, PPTX speaker notes, multi-file submissions, partial decks, wrong file types); explicit AI company detection signals for `is_ai_company`; full evidence quality rules for checklist scoring (fail/warn/pass/not_applicable each have specific requirements); Gotchas section covering polished-deck bias, AI-generated copy, benchmarks as medians, text-only input, and cross-skill context. Stale step numbers in `artifact-schemas.md` fixed to match current pipeline table. "2026" removed from description and body (kept in reference files where it is factual).
- Market Sizing and IC Simulation now include explicit sub-agent failure recovery guidance — after each sub-agent dispatch point, the agent verifies expected artifacts exist in the working directory and re-runs the failed sub-agent before proceeding if any are missing.
- Market Sizing, Deck Review, and IC Simulation now integrate `founder_context.py` as a first step — each skill reads (or creates) a persistent founder identity before starting analysis, matching the pattern already in Financial Model Review and Competitive Positioning. The company slug from founder context drives the skill-specific working directory name (`market-sizing-${SLUG}`, etc.), so artifact directories align across skills automatically. Path setup is now a two-phase process: base paths are set immediately, while the skill directory and `RUN_ID` are deferred until the slug is known. `SHARED_SCRIPTS` added to path setup and Glob fallbacks in all three skills.
- Deck Review now inserts a mandatory founder confirmation gate (two-step: chat summary then `AskUserQuestion`) between stage detection and slide review — agent presents detected stage, confidence, evidence, and expected framework before evaluating slides against stage-specific criteria. Out-of-scope stages (`series_b`/`growth`) surface a distinct gate with stop/proceed options.
- Market Sizing now inserts a mandatory founder confirmation gate between input extraction / methodology selection and external validation research — agent presents methodology, key inputs table, and missing fields before spawning research sub-agents. Founder can approve, switch methodology, or correct/add data; gate repeats until confirmed.
- `score_moats.py`, `score_positioning.py`: accept and normalize common LLM output shape mismatches — array-of-objects normalized to dict-keyed format for moat assessments; bare strings wrapped as `{name, description, rationale}` objects for axes; `slug` accepted as alias for `competitor` in positioning points.
- Validation error messages now include expected shape hints.
- stderr summary lines added to scoring scripts for batch visibility.

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
