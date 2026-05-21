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
- `founder-skills/skills/competitive-positioning/` — Competitive positioning skill with scripts and references
- `founder-skills/agents/competitive-positioning.md` — Competitive positioning agent definition
- `founder-skills/tests/test_competitive_positioning.py` — Competitive positioning regression tests
- `founder-skills/tests/test_visualize_competitive_positioning.py` — Competitive positioning HTML visualization tests
- `founder-skills/skills/cap-table/` — Cap-table skill (SAFE / note conversion, priced rounds, anti-dilution, Israeli ↔ Delaware flips)
- `founder-skills/agents/cap-table.md` — Cap-table agent definition (Context A extraction + Context B coaching)
- `founder-skills/tests/test_cap_table.py` — Cap-table regression tests (math producers + 11-gotcha regression suite)
- `founder-skills/tests/cowork_async_subagent_filter.py` — Cowork sub-agent tool-name compatibility helper (skill-quality CI; v0.4.0-regression detector)
- `founder-skills/tests/compose_invocations.py` — Per-skill compose-script invocation registry (skill-quality CI)
- `founder-skills/tests/test_cowork_async_subagent_filter.py` — Helper unit tests
- `founder-skills/tests/test_cowork_invariants.py` — Per-agent persistence + dangerous-tool declaration invariants
- `founder-skills/tests/test_skill_orchestration.py` — Per-SKILL.md frontmatter + sub-agent-cue-then-bash regression detector
- `founder-skills/tests/test_compose_invariants.py` — `coaching_payload` shape + `STALE_ARTIFACT` regression
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
- **`review_inputs.py`** — Dual-mode review viewer: HTTP server with live validation (Claude Code) or self-contained static HTML with JS sanity metrics (Cowork); outputs HTML
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
- **`compose_report.py`** — Assembles report.md + report.json (with embedded `coaching_payload` block, schema_version `v0.5.0-cap-table` as of Sprint 6c; v0.4.2 still accepted on input via `COMPAT_VERSIONS`)
- **`visualize.py`** — Self-contained `report.html` (inline SVG donut, no CDN)
- **`explore.py`** — Self-contained `explorer.html` (vanilla JS interactive scenario picker)
- **`extract_instrument.py`** — Lane-1 anti-hallucination validator (sub-agent does extraction; this validates returned JSON, normalizes `discount_multiplier` per Gotcha #3). Sprint 2b added `--verify` / `--verify-blocking` / `--source-doc` flags for evidence-verification wiring; Sprint 2c added ~30-field synthesized skip list.
- **`extract_cap_table.py`** — Lane-2/3/4 (validate mode + Carta/Pulley stub + freeform Context-A output validator)
- **`evidence_verifier.py`** — Sprint 2 forward verifier. Three-layer check (quote_in_doc / value_in_quote / value_in_doc) catching HALLUCINATIONS. 3.6% FPR / 100% TPR.
- **`backward_verifier.py`** — Sprint 3 backward verifier (two-phase `--phase=prompt`/`--phase=score` CLI). Catches SEMANTIC CONFUSION via fresh-sub-agent re-extraction. WARN-mode default.
- **`invariant_checker.py`** — Sprint 4 real-world-bounds checker. Per-field ranges + cross-field math invariants. 0% FPR / 63% TPR.
- **`cross_checker.py`** — Sprint 5d demote-only confidence modulator when multiple extractors disagree.
- **`_normalize.py`** — Sprint 5b shared text-normalization primitives (normalize_text, compact_form, numeric_tokens, date_tokens).
- **`extractors/`** — Sprint 5c scaffolding module: `FieldExtraction`, `SourceSpan`, `ExtractionContext`, `ExtractorProtocol` types for span-preserving extraction.

## Competitive Positioning Scripts

- **`validate_landscape.py`** — Validates competitor list structure, checks slug uniqueness, preserves provenance
- **`score_moats.py`** — Scores 6+ moat dimensions per company with aggregates and cross-company comparison
- **`score_positioning.py`** — Scores pair-centric positioning views with rank-based differentiation and vanity detection
- **`checklist.py`** — Scores ~25 quality criteria across 6 categories with mode-based gating
- **`compose_report.py`** — Assembles report with cross-artifact validation, warning system, and accepted warnings
- **`visualize.py`** — Generates self-contained HTML with SVG positioning map, moat radar, competitor table; outputs HTML (not JSON)
- **`explore.py`** — Generates interactive HTML explorer with Chart.js scatter plot (vendored, no CDN), view switching, bubble encoding controls, and company detail panels; outputs HTML (not JSON)

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

## Running Tests

```bash
uv run pytest                                       # all tests (e2e auto-skips without auth)
uv run pytest founder-skills/tests/ -v              # verbose
uv run pytest founder-skills/tests/ -v -m "not e2e" # explicitly skip the LLM-driven e2e (free, fast)
```

The deck-review e2e smoke (`tests/test_e2e_deck_review.py`) drives the SDK against a synthetic fixture. Auth options (any one):

- `ANTHROPIC_API_KEY` env var (per-token API; ~$2-5/run)
- `CLAUDE_CODE_OAUTH_TOKEN` env var (subscription, long-lived token from `claude setup-token`)
- Local subscription auth: `claude /login` populates the macOS Keychain entry `Claude Code-credentials` (or `~/.claude/.credentials.json` on Linux/Windows)

For live progress during the 60-180s e2e run, add `-s`:

```bash
uv run pytest founder-skills/tests/test_e2e_deck_review.py -v -m e2e --tb=short -s
```

Without `-s` the run looks silent (pytest captures stdout); with `-s` you see auth-detected, prompt, and per-message tool calls (`Bash`, `Read`, `Skill`, `Task`, etc.) as the SDK stream arrives.

The `e2e` marker keeps these tests out of the default per-PR `ci.yml` run; they execute only in the dedicated `skill-quality.yml` workflow.

## Internal Docs

- `docs/internal/` — Design docs and internal notes; never tracked or committed (gitignored)

## Hooks

- **SessionStart** (`founder-skills/scripts/session-setup.sh`): Persists `CLAUDE_PLUGIN_ROOT` into `CLAUDE_ENV_FILE` so scripts can locate plugin files at runtime.

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

1. Bump versions in `pyproject.toml` and `founder-skills/.claude-plugin/plugin.json` (must match)
2. Update `CHANGELOG.md`
3. `git commit -m "release: vX.Y.Z"`
4. `git push`
5. `git tag vX.Y.Z && git push --tags`
6. **Wait for `deck-review-e2e-smoke` green** in the GitHub Actions UI
   - Tag failure: `git tag -d vX.Y.Z && git push origin :refs/tags/vX.Y.Z`, fix, retag — no user impact yet (sync hasn't happened)
   - LLM-variance flake: re-run the job from the Actions UI (free retry, same SHA)
7. **Only after green:** `./scripts/sync-test-repo.sh`

`sync-test-repo.sh` is the actual user-facing distribution event; the tag itself is just a marker. Syncing before green = users pull a broken release.

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

Customize → "+" on the "Personal Plugins" list → Browse Plugins → Personal → +

Then add the marketplace repo (`lool-ventures/founder-skills`) and install the `founder-skills` plugin.

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
