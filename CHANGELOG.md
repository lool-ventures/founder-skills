# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [0.2.0] - 2026-03-03

### Highlights

New Financial Model Review agent — reviews startup financial models for investor readiness,
validating structure, unit economics, runway, and metrics against stage-appropriate standards.
Supports Excel, CSV, pitch decks, and conversational input with automatic profile-based gating
by stage, geography, and sector.

### Added

- Financial Model Review Agent with 6 scripts: `extract_model.py` (Excel/CSV parser), `checklist.py` (46-criteria scoring across 7 categories with profile-based auto-gating), `unit_economics.py` (11 benchmarked metrics), `runway.py` (multi-scenario stress-test with decision points and default-alive analysis), `compose_report.py` (report assembly with cross-artifact validation), and `visualize.py` (self-contained HTML with SVG charts).
- SKILL.md for financial model review (`/founder-skills:financial-model-review` slash command).
- Agent definition with skill preloading (`skills:` frontmatter).
- Profile-based auto-gating: checklist items gate by stage (`seed+`), geography (Israel, multi-currency, multi-entity), sector (AI-native, marketplace, usage-based, hardware, consumer, annual-contracts), and model format (spreadsheet vs. deck/conversational).
- `ai-powered` trait for AI-hybrid products: triggers AI cost scrutiny (SECTOR_40) regardless of revenue model type.
- Data sufficiency gate with qualitative fallback path for deck/conversational inputs.
- `data_confidence` qualifier (`exact`/`estimated`/`mixed`) propagated through unit economics and runway outputs.
- Cross-agent integration: financial model review exports `report.json`, `unit_economics.json`, and `runway.json` for downstream IC simulation and fundraise-readiness skills.
- 457 regression tests across all four skills.

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
