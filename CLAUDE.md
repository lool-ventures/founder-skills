# CLAUDE.md

## Repository Structure

- `founder-skills/` — Claude Code plugin (SDK/CLI-based)
- `founder-skills/.claude-plugin/plugin.json` — Plugin manifest
- `founder-skills/skills/market-sizing/` — Market sizing skill with scripts and references
- `founder-skills/skills/deck-review/` — Deck review skill with scripts and references
- `founder-skills/agents/market-sizing.md` — Market sizing agent definition
- `founder-skills/agents/deck-review.md` — Deck review agent definition
- `founder-skills/skills/ic-sim/` — IC simulation skill with scripts and references
- `founder-skills/agents/ic-sim.md` — IC simulation agent definition
- `founder-skills/scripts/session-setup.sh` — SessionStart hook (persists CLAUDE_PLUGIN_ROOT)
- `founder-skills/scripts/founder_context.py` — Founder context management (init/read/merge/validate)
- `founder-skills/scripts/find_artifact.py` — Artifact path discovery across skills
- `founder-skills/references/` — Shared reference files (benchmarks, Israel guidance, etc.)
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
- `artifacts/` — Persistent working directory for skill run artifacts (gitignored, created at runtime)

## Plugin Structure

- `.claude-plugin/marketplace.json` — Marketplace manifest (root level)
- `founder-skills/.claude-plugin/plugin.json` — Plugin manifest with hooks
- marketplace.json must match Anthropic's format: only `name`, `owner`, `plugins` (each with `name`, `source`, `description`)
- Do NOT add `version` or `metadata` fields to marketplace.json

## Script Conventions

- Scripts use PEP 723 inline metadata; default to `python`, `uv run` optional
- Scripts output JSON to stdout, warnings/errors to stderr
- All scripts support `--pretty` for human-readable output and `-o <file>` to write to file instead of stdout
- Skill-local scripts live in `founder-skills/skills/<skill>/scripts/`

## Shared Scripts

- **`founder_context.py`** — Per-company context management (init/read/merge/validate subcommands); protects 11 key metric fields
- **`find_artifact.py`** — Resolves artifact paths by skill name, artifact filename, and optional company slug

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
- **`validate_inputs.py`** — Four-layer validation of inputs.json (structural, consistency, sanity, completeness); `--fix` auto-corrects sign errors
- **`checklist.py`** — Scores 46 criteria across 7 categories with profile-based auto-gating by stage/geography/sector
- **`unit_economics.py`** — Computes and benchmarks 11 unit economics metrics against stage-appropriate targets
- **`runway.py`** — Multi-scenario runway stress-test with decision points and default-alive analysis
- **`compose_report.py`** — Assembles financial model review artifacts into final report with cross-artifact validation
- **`visualize.py`** — Generates self-contained HTML with SVG charts; outputs HTML (not JSON)

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
uv run mypy founder-skills/tests/
```

## Running Tests

```bash
uv run pytest                        # all tests
uv run pytest founder-skills/tests/ -v  # verbose
```

## Internal Docs

- `docs/internal/` — Design docs and internal notes; never tracked or committed (gitignored)

## Hooks

- **SessionStart** (`founder-skills/scripts/session-setup.sh`): Persists `CLAUDE_PLUGIN_ROOT` into `CLAUDE_ENV_FILE` so scripts can locate plugin files at runtime.

## Installing the Plugin in Claude Cowork

Customize → "+" on the "Personal Plugins" list → Browse Plugins → Personal → +

Then add the marketplace repo (`lool-ventures/founder-skills`) and install the `founder-skills` plugin.

**Start a new Cowork session** after installing — already-running sessions won't pick up the plugin.

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

## Removing a Marketplace from Claude Code / Cowork

There is no UI to remove a marketplace. Edit these config files directly:

1. **Claude Code (local):**
   - `~/.claude/plugins/known_marketplaces.json` — delete the marketplace entry
   - `~/.claude/plugins/installed_plugins.json` — delete any `pluginname@marketplace` entries
   - `~/.claude/plugins/cache/<marketplace>/` — delete to reclaim disk space

2. **Cowork (per-session):**
   - `~/Library/Application Support/Claude/local-agent-mode-sessions/<org-id>/<session-id>/cowork_plugins/known_marketplaces.json` — delete the marketplace entry
   - Same session dir `cowork_plugins/installed_plugins.json` — delete any related plugin entries if present

**Pitfall:** When deleting an entry from these JSON files, ensure the preceding entry's trailing comma is removed if it becomes the last entry. A trailing comma produces invalid JSON that `JSON.parse()` rejects, causing "Failed to add marketplace" errors in Cowork.
