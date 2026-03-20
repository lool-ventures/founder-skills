# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [0.3.0] - 2026-03-20

### Highlights

New Competitive Positioning & Moat Analyzer — maps a startup against competitors across product,
distribution, data, pricing, and defensibility dimensions. Scores moat strength across 6+ types
(network effects, data advantages, switching costs, regulatory barriers, cost structure, brand)
with extensible custom dimensions. Generates an investor-ready competition narrative with
positioning map, moat radar chart, and defensibility timeline.

### Added

- Competitive Positioning Agent with 6 scripts: `validate_landscape.py` (competitor list validation with slug uniqueness and provenance preservation), `score_moats.py` (6+ moat dimensions per company with aggregates and cross-company comparison), `score_positioning.py` (pair-centric positioning views with rank-based differentiation and vanity axis detection), `checklist.py` (25-criteria scoring across 6 categories with mode-based gating), `compose_report.py` (report assembly with cross-artifact validation, warning system, and accepted warnings), `visualize.py` (self-contained HTML with SVG positioning map, moat radar, competitor table, and defensibility timeline).
- SKILL.md for competitive positioning (`/founder-skills:competitive-positioning` slash command).
- Agent definition with 3 trigger examples and 5 gotchas.
- Two-gate founder validation: Gate 1 validates competitor list and product understanding; Gate 2 validates positioning axes and moat assessments before final report.
- Research sub-agent with two-phase research (broad scan then targeted cross-referencing) and graceful degradation when Task tool is unavailable.
- Suggested additions mini-gate: research sub-agent can propose new competitors; founder approves before inclusion.
- 4 reference files: artifact schemas (resolving 11 design follow-ups), moat type definitions, 25-item checklist criteria with mode gating, competitive analysis methodology.
- Cross-agent integration: ic-sim imports `report.json` for partner debate enrichment; deck-review imports `landscape.json` for competition slide cross-validation.
- 70 new regression tests (816 total across all 5 skills).

### Changed

- IC Simulation: added optional `competitive-positioning:report.json` import with per-partner enrichment (Visionary: market timing, Operator: GTM differentiation, Analyst: moat strength).
- Deck Review: added optional `competitive-positioning:landscape.json` import for competition slide cross-validation.

---

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
