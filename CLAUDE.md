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
- `founder-skills/scripts/_founder_text.py` — Shared founder-facing text policy: which internal tokens may reach a founder and how they render. Four token types, three behaviours (humanize private enums + field names; keep stable identifiers and diagnostic codes verbatim). Every skill's `compose_report.py` substitutes then scans with it; `insert_coaching.py` scans the coaching commentary. `identifier_values()` is **cap-table-only** — elsewhere an `id` field can hold a field name (fmr's `unit_economics.metrics[].id` is `gross_margin`), and keeping it leaves our vocabulary in the report *and* silences the warning.
- `founder-skills/scripts/resolve_artifacts_root.py` — Canonical + agent-namespace artifacts-root resolver (`--agent` for HANDOFF_AGENT derivation)
- `founder-skills/references/` — Shared reference files (benchmarks, Israel guidance, etc.)
- `founder-skills/references/brand/` — Brand tokens + Sora variable webfont (OFL) for generated HTML artifacts; embedded base64-inline so artifacts stay self-contained
- `founder-skills/tests/test_market_sizing.py` — Market sizing regression tests
- `founder-skills/tests/test_deck_review.py` — Deck review regression tests
- `founder-skills/tests/test_reconcile.py` — The numeric engine's 60 judgement calls, each pinned to a real corpus line
- `founder-skills/tests/test_reconcile_producer.py` — The engine's producer layer: the gate, the three statuses, and that only `select()` decides founder-visible output
- `founder-skills/tests/test_ledger.py` — Ledger validation, chiefly the `raw`-vs-`value` scale check
- `founder-skills/tests/test_quote_match_sync.py` — deck-review's copy of cap-table's matcher must not drift
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
  - **Scope warning — a green here still does not mean the narration is clean, but the gap is now narrower than this note used to claim.** Nine of the ten classes match on FORM (backticks, `--flags`, `$vars`, `*.py`, exit codes, `W_`/`E_` codes, JSON, a literal route-label list, ALLCAPS-with-underscore). The tenth, `plumbing_verb`, is SEMANTIC: it targets the verb+object construction that only appears when narrating internals, so "gating the hand-off", "piping it through the producer" and "dispatching the sub-agent" ARE caught (measured: 3 such leaks, and zero syntactic ones, in one live run's `events.jsonl`). **What still passes clean is internal vocabulary with no plumbing verb** — "canonical artifacts", "schema-drift warning", "gap-detection pass", bare `STOP`/`BLOCKED` (no underscore), and "Gate 1 passes". That residue is the live-run/hand-read surface; it is smaller than "every plain-English mention". Do not fix it by enumerating more words — `leak_scan.py`'s own design note says an enumerated blocklist is unwinnable, which is why the classes are class-based. **Superseded advice, recorded so it is not re-derived:** this note used to say never to extend the existing classes because doing so "raises the measured count on the committed cassettes and reds the suite". That was tried and is false — the ten-class total over the committed cassettes is **61 against the then-current `BASELINE = 144`**, green, because the nine-class count had already fallen far below its own baseline. (`BASELINE` is now **59** — measured 2026-08-06 at `test_founder_facing_leaks.py:74`. It went 144 → 64 → 55, then was **RAISED 55 → 59**, which breaks the ratchet-down rule deliberately and once; the file's own comment states the obligation to fix the narration leak, re-record, and ratchet back below **55**, not to it. Read the constant from the file, never from this line — it has now been stale twice.)
- `founder-skills/tests/compose_invocations.py` — Per-skill compose-script invocation registry (skill-quality CI)
- `founder-skills/tests/test_cowork_async_subagent_filter.py` — Helper unit tests
- `founder-skills/tests/test_cowork_invariants.py` — Per-agent persistence + dangerous-tool declaration invariants
- `founder-skills/tests/test_cowork_harness_floors.py` — Drift guards for the cowork-harness version surface: the per-site registry splitting CI SELECTORS (pinned exactly, `2.4.0`) from FLOORS (recording `>=2.4.0`, replay `^2.1.0`) — three postures, deliberately different, `uses:`-vs-`version:` major agreement (the action ref and the CLI move independently), and the derived cassette-format facts prose keeps restating wrongly. Every extraction asserts its own pattern matched, so a rotted regex reds instead of greening.
- `founder-skills/tests/test_skill_orchestration.py` — Per-SKILL.md frontmatter + sub-agent-cue-then-bash regression detector
- `founder-skills/tests/test_compose_invariants.py` — `coaching_payload` shape + `STALE_ARTIFACT` regression
- `founder-skills/tests/test_insert_coaching.py` — `insert_coaching.py` suite (6-state idempotency matrix, run_id parity, single-pass write-back, adversarial commentary)
- `founder-skills/tests/test_check_handoff.py` — `check_handoff.py` suite (typed exit paths 0/3/4/5/6, adversarial file states, tolerant receipt extraction)
- `founder-skills/tests/test_merge_json.py` — `merge_json.py` suite (merge order, --set overrides, error paths)
- `founder-skills/tests/test_resolve_artifacts_root.py` — Artifacts-root resolver suite (Cowork mount signatures + agent-namespace root)
- `founder-skills/tests/dead_payload.py` — Shared analyzer for embedded-but-unread JS payload keys. Three verdicts, because two cannot express what is known: `read`, `unread`, and **`unverifiable`** (the script indexes the payload by computed name, so no read can be attributed to a specific key). Treating dynamic access as blanket consumption hides real dead keys; treating it as death reports false ones.
- `founder-skills/tests/test_dead_payload.py` — Analyzer unit tests + all four embedders (three `explore.py` + `review_inputs.py`). Pins which payload objects are dynamic, so a generator switching to computed access cannot quietly reduce coverage.
- `founder-skills/tests/test_dispatch_schema_drift.py` — Guards a dispatch template instructing a field nothing consumes. Reads **every** fenced block on both prompt surfaces (templates also appear untagged and in `bash` heredocs; json-only sees about a third). Consumers include shared scripts, JSON schemas, and JS member access. **Cannot** detect shape-level drift for a name consumed elsewhere — `x_axis_rationale` is the obsolete authoring shape *and* the legitimate internal shape of `positioning_scores.json` — so a direct axis-shape assertion covers that regression.
- `founder-skills/tests/test_html_founder_text.py` — Fleet ratchet: no internal token in founder-visible text of any generated HTML. Text nodes only; attribute values and script bodies are not founder-facing prose.
- `founder-skills/tests/test_compose_invariants.py` also scans **every delivered markdown, not just `report.md`** — `_EXTRA_DELIVERABLES` names the non-compose producers (cap-table's counsel packet today). A deliverable nothing scans can say anything: `counsel_packet.md` shipped a raw rule-domain token to a founder while the fleet scan looked only at `report.md`. The cap-table fixture flags **zero** counsel items, so the scan seeds one — without it the packet is 315 B of boilerplate and passes with the leak present.
- `founder-skills/tests/test_delivery_coverage.py` — The fleet's delivery-defect coverage map, asserted rather than described. Records the known gap: the downstream half of "computed, not rendered" is gated only in competitive-positioning and financial-model-review — a third row records a Gate-1 render contract as explicitly WEAK (a string assertion over SKILL.md prose, which cannot fail a run), and does not narrow that count.
- `founder-skills/tests/test_theme_sync.py` — Brand-theme invariants: per-skill `_theme.py` copies identical, brand font present, font embeds in CSS
- `founder-skills/tests/test_e2e_deck_review.py`, `test_e2e_financial_model_review.py`,
  `test_e2e_market_sizing.py` — the three paid end-to-end lanes; LLM-driven; carry the `e2e` marker.
  Shared plumbing in `tests/_e2e_harness.py` — deck-review deliberately does NOT use it (it is the
  lane the release tag gates on; fold it in when a failure costs a re-run rather than a re-tag).
  **One lane per changed coaching-payload builder is the rule**: contract tests pin that a payload
  key is emitted and named on both prompts, and structurally cannot show a sub-agent reading it.
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
- **A producer that rejects its input MUST fail loudly: diagnostic to stdout, a line to stderr, `-o` left untouched, exit non-zero.** Six producers across four skills independently got this wrong — they wrote a `{"validation": {"status": "invalid"}}` stub *through* `-o` and returned 0, which both destroyed the prior good artifact and made every SKILL.md's "the pipe fails next" error branch unreachable; the only downstream signal was a *medium* warning naming a symptom. Use the `_fail_invalid` helper (canonical copy: `skills/market-sizing/scripts/market_sizing.py`). Stamp `metadata`/`graded_against` **before** calling it, so the diagnostic still carries provenance. `tests/test_skill_contract.py::test_producer_rejects_loudly_without_clobbering` runs each producer against a rejecting payload and asserts all three properties — deliberately behavioural, because the structural version ("must contain `_fail_invalid` or a `sys.exit(1)`") was measured **vacuous**: every one of these scripts already had `sys.exit(1)` for malformed-JSON errors. Add new producers to that registry.
- **The audit trail does not require clobbering, and a sidecar needs a downstream reader.** A producer may keep a rejected artifact beside the canonical one as `<canonical-filename>.rejected.json` (appended, so `competitor_verification.json.rejected.json` — not a replaced extension), leaving `-o` untouched. `verify_competitors.py` does this. **If it does, something downstream MUST key on the sidecar**: for an OPTIONAL artifact, absence otherwise reads as "the run skipped this step" and the deliverable presents unchecked analysis exactly as it presents checked analysis. Two ways for that signal to go missing, both measured here — key it on absence alone and a prior run's file silences it, so compare run_ids; and a *medium* code naming a symptom (`STALE_ARTIFACT`) is not the signal, because the founder needs the cause. `compose_report.py`'s `VERIFICATION_REJECTED` is high and does both.
- Compose scripts pair with it: a canonical artifact carrying `validation.status == "invalid"` raises `ARTIFACT_INVALID` (or `SIZING_INVALID` in market-sizing) at **high** severity, so it cannot be accepted away via `accepted_warnings`.

## Shared Scripts

- **`founder_context.py`** — Per-company context management (init/read/merge/validate subcommands); protects 11 key metric fields
- **`find_artifact.py`** — Resolves artifact paths by skill name, artifact filename, and optional company slug
- **`insert_coaching.py`** — Deterministic Context B insertion: reads the sub-agent's commentary JSON, applies the 6-state idempotency matrix, replaces the per-run uuid `insertion_marker` with `## Coaching Commentary` + commentary in a single in-place write, and verifies `run_id` parity across `--verify-artifact` paths (exit 0 inserted/already_inserted; exit 1 blocked with JSON diagnostic). Every skill's POST_COMPOSE_COACHING step calls it; sub-agents only compose commentary and never edit `report.md`.
- **`check_handoff.py`** — Context A file hand-off gate: verifies a sub-agent's output file exists/parses as JSON and (optionally) that its receipt's `output_path` matches (`--agent-path` accepts the agent-namespace echo). Typed exit codes (0 ok / 3 missing-or-empty / 4 bad JSON / 5 path mismatch / 6 unparseable receipt / 7 content-shape invalid / **8 path-namespace mismatch**) for main-thread branching. Exit 8 fires when no file is at the expected path but one IS where a **doubled** agent-namespace prefix would have put it — reported ahead of exit 3 because the two are indistinguishable from the file check yet need opposite responses (3 = the receipt may be fabricated; 8 = the agent complied and the path was wrong). Its `found_at` is **diagnostic only**: never read the hand-off from it, or exit 0 stops meaning "the file is at the contracted path" for the ~50 downstream `$HANDOFF_DIR` references.
- **`merge_json.py`** — Shallow-merges multiple JSON object hand-off files (later files win; `--set key=value` overrides) into one stream for producer pipes — used when a step consumes the union of parallel sub-agent outputs (e.g. market-sizing "both").
- **`md_to_commentary.py`** — Transport envelope for Context B: the sub-agent writes coaching commentary as **plain markdown** (never JSON, never escaped), this wraps it into the payload `insert_coaching.py` reads. Quotes and line breaks in the commentary can't break the hand-off.
- **`resolve_artifacts_root.py`** — Resolves the canonical artifacts root AND the agent-namespace root (`--agent` / `--json`): in Cowork the sub-agents' file tools see the `outputs/` mount at a different prefix than the VM shell, so SKILL.mds derive `HANDOFF_AGENT` from `--agent` when building `OUTPUT_PATH` dispatch lines. Warns (never fails) when `--dir-name` names a directory with no mirror under the canonical root: a mistyped name still yields a well-formed path, and the symptom — every hand-off failing `check_handoff.py` exit 3 — reads as a fabricated receipt rather than a bad path, so the state machine spends its retry budget on redo-dispatches that cannot succeed.

## Market Sizing Scripts

- **`market_sizing.py`** — TAM/SAM/SOM calculator (top-down, bottom-up, or both). Also the only place FX happens: a money input (`industry_total` / `arpu` — the only two) may declare its own source currency via `<field>_currency`, and conversion uses a rate the CALLER supplies (`--fx-rate SRC:TGT=RATE`, `--fx-as-of`, `--fx-source`). A declared foreign currency with **no** rate is a hard error, never a guess, and a rate is never inferred by inverting another pair — the sub-agent that produces these figures has no network, so FX done upstream could only come from model memory. Conversions are recorded in `sizing.json`'s `fx` block and disclosed to the founder in both `report.md` and `report.html`; the recorded `converted_value` IS the number the math consumed, which is what lets `compose_report.py` compare a founder-stated figure across the conversion.
- **`sensitivity.py`** — Stress-test assumptions with low/base/high ranges and confidence-based auto-widening. **RECONCILES rather than defers:** a range's own `confidence` used to be absolute, which let a caller tag a medium-confidence parameter `sourced` and escape widening entirely; the stricter of the declared and cross-referenced tiers now wins (it can only ever WIDEN). `confidence_source` on each scenario records where the tier came from — `range` / `validation` / `reconciled` / `default` — because "no widening happened" and "no widening was called for" were previously the same artifact.
- **`checklist.py`** — Validates 22-item self-check with pass/fail per item
- **`compose_report.py`** — Assembles report from artifacts, validates cross-artifact consistency
- **`visualize.py`** — Generates self-contained HTML with SVG charts; outputs HTML (not JSON)

## Deck Review Scripts

- **`checklist.py`** — Scores 35 criteria across 7 categories (pass/fail/warn/not_applicable) with overall score percentage
- **`compose_report.py`** — Assembles deck review artifacts into final report with cross-artifact validation
- **`visualize.py`** — Generates self-contained HTML with SVG charts; outputs HTML (not JSON)
- **`ledger.py`** — Validates the extracted numeric ledger. Its load-bearing check is `raw` against `value`: they are two independent statements about the same figure, so their disagreement catches the scale-slip class ("$493K" recorded as 493) **without seeing the deck**. Tolerance comes from `raw`'s own significant figures, not a flat percentage — "$1.2M" legitimately covers 1.15M–1.25M and a flat 2% rejects a correct extraction.
- **`reconcile.py`** — The arithmetic. Corroborates each figure's quote against a second read that never saw the ledger, computes the model's proposed relations, applies the tolerance/materiality/convention rules, and **`select()` is the single place that decides what a founder sees**. `relations` in the artifact holds only the survivors; everything else is a count, so no renderer can reach past the decision. Two rules that have each already been violated once: split founder-facing output on **`verdict`** (what the engine computed), never on `kind` (what the model proposed) — they routinely differ, and the flagship finding is proposed `derived_ratio` and returns `contradiction`; and never render a `unit_kind` enum into prose ("per count" reached a rendered line).
- **`_quote_match.py`** — Copy of cap-table's `quote_in_doc` + normalizers (skill scripts are standalone and cannot import across skills). `tests/test_quote_match_sync.py` compares the parsed function bodies. **`value_in_doc` is deliberately NOT copied**: on decks it false-passes 5.7% cross-deck and 37% on plausible round numbers, against `quote_in_doc`'s 0.8%, so the cap-table precedent is inverted here on purpose.

**The numeric chain (Steps 3.5–3.8) is gated by `slide_reviews.py --reconciliation`, not by `MISSING_ARTIFACT`.** Measured: removing a required artifact leaves `compose_report.py` exiting **0** with a complete report, so a step whose only downstream consumer is a warning gets skipped in silence — which is exactly what happened to the removed claim-check step. The gate sits on the producer of the deliverable, and checks `run_id` parity rather than mere presence (a stale artifact from an earlier review of the same company otherwise satisfies an existence check, and in Cowork the cleanup delete is denied and tolerated).

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
- **`checklist.py`** — Scores 46 criteria across 7 categories with profile-based auto-gating by stage/geography/sector; `--inputs <path>` supplies the document to fingerprint (the sub-agent's payload carries `company`, not the whole inputs, so without it the fingerprint is null and staleness is undetectable for this artifact)
- **`unit_economics.py`** — Computes and benchmarks 11 unit economics metrics against stage-appropriate targets
- **`runway.py`** — Multi-scenario runway stress-test with decision points and default-alive analysis
- **`compose_report.py`** — Assembles financial model review artifacts into final report with cross-artifact validation
- **`visualize.py`** — Generates self-contained HTML with SVG charts; outputs HTML (not JSON)
- **`explore.py`** — Generates self-contained interactive HTML explorer from review artifacts; outputs HTML (not JSON)
- **`review_inputs.py`** — Dual-mode review viewer: HTTP server with live validation (Claude Code) or self-contained static HTML with JS sanity metrics (Cowork); outputs HTML. The static/Cowork branch must stay write-back-safe: guard every `/api/*` `fetch` behind the build-time `IS_STATIC` flag with a lexical `if/else` (an early-return guard reads as unguarded to the write-back analyzer), name the fetch response `resp`/`res`/`response` and check `resp.ok`, and keep literal `<script>`/`</script>` tokens out of docstrings (the block extractor mis-reads them). The `financial-model-review-smoke` cassette's `no_lost_write_back` assert locks this in.
- **`_theme.py`** — Brand theme helper: design-token CSS + base64 @font-face from `references/brand/`; every skill's scripts dir carries an identical copy (standalone scripts can't import across skills) and all HTML generators inject `_theme.brand_css()`; `tests/test_theme_sync.py` enforces the copies stay identical — edit one, re-copy to all
- **`apply_corrections.py`** — Processes founder's downloaded corrections file: coerces, normalizes, merges overrides, writes corrected_inputs.json + extraction_corrections.json
- **`_fingerprint.py`** — Stable fingerprints of a producer's inputs, so a stale output is detectable. `run_id` parity cannot see this class: `apply_corrections.py` rewrites `inputs.json` **within** a run, so pre- and post-correction outputs share a run_id. `checklist.py` / `unit_economics.py` / `runway.py` stamp `graded_against`; `verify_review.py` recomputes the current `inputs.json` hash and compares. Comparing outputs to each other is insufficient — they agree while all are stale.
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
- **`extract_instrument.py`** — Lane-1 anti-hallucination validator (sub-agent does extraction; this validates returned JSON, normalizes `discount_multiplier` per Gotcha #3). Supports `--verify` / `--verify-blocking` / `--invariants` / `--cross-check` / `--source-doc` flags, all default-on; uses `--no-<flag>` to opt out. Skips evidence checks on a ~30-field synthesized-fields list (form, jurisdiction, derived counts, etc.). The blocking gates run **before** `write_artifact`, so a refusal leaves `--instruments` untouched rather than persisting the extraction it just rejected. `--instruments` itself is a checked precondition: unreadable, non-object, a non-list array, a non-dict `metadata`, or an object carrying none of the four instrument arrays (i.e. the wrong file) are refused with `E_INSTRUMENTS_FILE_UNUSABLE`. It APPENDS, so a wrong-path write is unrecoverable — and the schema cannot stand in for the check, since the validator ignores `additionalProperties`.
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
- **`verify_competitors.py`** — Adversarial competitor-set verification validator (Step 3.5, before Gate 1): validates the COMPETITOR_VERIFICATION sub-agent's per-competitor verdicts (genuine/adjacent/not_a_competitor), enforces the show-your-work gate (a flag must carry reasoning + independent buyer/job characterization), cross-checks landscape slug coverage, computes summary. Validator, not detector. Catches false-positive competitors (surface-level matches that don't genuinely compete). Emits `summary.challenge_slugs` — the subset of `flagged_slugs` that actually challenges the draft — so Gate 1 reads a judgement rather than re-deriving one across two disjoint vocabularies. On rejection it leaves `-o` untouched and keeps the artifact in a `.rejected.json` sidecar; `compose_report.py` raises `VERIFICATION_REJECTED` (high) on it, keyed on run_id so a prior run's file cannot silence a fresh refusal.
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

- **`critique`'s tier prerequisites were misstated upstream until 1.19.0 backfilled the correction.**
  `critique --help` and `docs/critique.md` said the `container` and `hostloop` tiers need an
  authenticated `claude` CLI on PATH. They do not: they need a **token in the environment or `.env`**
  (`CLAUDE_CODE_OAUTH_TOKEN`, or `ANTHROPIC_API_KEY` as a CI fallback), because the graded turns run the
  staged agent binary, not the host CLI. It is the **evaluator passes** that require `claude` on PATH,
  overridable with `COWORK_HARNESS_CLAUDE_BIN`. (Our token lives in `cowork-tests/.env`, discovered from
  CWD only.)
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
- **`--out <skill>.json` writes TEXT unless you also pass `--output-format json`.** The format is
  decided by a *different* flag whose default is `text`, so the flag most likely to be scripted
  against silently produces something `json.load()` rejects with `Expecting value: line 1 column 1`
  — which reads as a corrupt or missing report, not a format mismatch. 1.24.0 warns about the
  mismatch at argument-parse time, **before** the four workloads spawn (deliberately a warning, not
  extension inference). Pass both flags. This matters here because the budget guidance above tells
  you to read `report.costUsd.totalUsd` out of that file.
- **The "evaluator passes dominate spend" ratio INVERTS for the skills in this fleet.** `--help` and
  `docs/critique.md` said the two evaluator passes are ~3/4 of an end-to-end total; that holds for a
  trivial probe. Measured on a real document-analysis run — which is every skill here — it is **task
  turn ~61%, evaluator ~30%**, because evaluator cost is roughly fixed (bounded by the evidence
  package) while the graded task turn is unbounded. **Consequence: do NOT swap `--evaluator-model` on
  a fleet sweep.** That trades the injection-resistance property, which is verified for the DEFAULT
  evaluator only, for a saving a third of its advertised size. When the task turn dominates the levers
  are `--model`, `--timeout` and probe scope. As of 1.24.0 the report's `cost:` line prints the
  evaluator's share of the total, so a single run corrects this guidance itself.
- **A `scripts/`-grounded `not-adjudicable` means "the evaluator could not SEE the code", not "the
  claim is false".** `scripts/` is outside the critique corpus by design — it grades authored
  guidance. We read one such verdict on a claim about our own `gate_state.py` and treated it as
  unproven; it was a verified product bug. 1.24.0 appends a note saying so. The documented remedy is
  to state a script's contract in `SKILL.md` or a `references/` file if it matters to how the skill
  is used. Note this bites deck-review hardest: the gate contract lives in `gate_state.py`, invisible
  to every critique ever run against that skill.
- **A fleet-consistency defect is out of scope for ANY single critique, by construction** (the graded
  agent mounts the whole plugin; the evaluator's corpus is one skill). That is what the per-skill
  drift tests are for. And **one critique is a sample**: upstream measured two runs of one skill over
  one document producing 78 vs 50 extracted figures and 12 vs 0 first-pass errors from the same real
  bug — the same discipline as the local rig's >=2-run reproduction bar.
- **`assertions --list` does NOT emit a replay class.** Its output is `{key, description}`. A `jq`
  selector written against a class field selects on something that has never existed; read replay
  classes from the catalog tables in `docs/scenario.md`.
- **`result.json`'s `models` array can contain `<synthetic>`** — the agent's own marker for a turn it
  fabricated locally with no API call, recorded verbatim. Two runs of the SAME pinned model can differ
  on this array purely by whether such a turn occurred. Drop any `<…>`-wrapped entry before using
  `models` as run provenance (this touches the skill-latency methodology).
- **`--ablate-skill` is ONE arm, not a paired experiment.** Composed with `--repeat N` it produces N
  *ablated* runs and zero treatment runs. Run the prompt again without the flag for the other arm.
  **As of 1.25.0 the tool enforces this rather than leaving it to the reader:** the rollup verdict
  reads `repeat "<skill>": PASS [ABLATED — control arm] — 5/5 passed (100%)`, a hand-assembled mixed
  batch reads `[MIXED ARMS: 2/3 ablated]`, and a normal batch carries no tag. **This lands on a
  surface we DO read** — `evals/cap-table/run_reliability_bench.py` shells `run --repeat N
  --output-format json` and parses `rollups[]`, and the release process makes that bench mandatory for
  a model-tier change. Both the arm label and the new aggregate `provenance:` row are additive, and
  the bench reads defensively, so nothing breaks.
- **A recorded cassette is NOT relocatable.** It rewrites `scenario.session` and `scenarioSource`
  relative to its OWN directory at record time, so any move — a different `--out`, a `git mv`, a copy
  into another repo — leaves them unresolvable and `verify-cassettes` reports `unverifiable-skill`
  (exit 3) until a re-record. **Practical consequence for debugging:** never rehearse
  `replay --assert-from` on a `/tmp` copy. A copied cassette reports `skill dirs not resolvable from
  the cassette location`, which is NOT skill-content drift — it is this, induced by the copy. Both
  exit 1 and read alike, so a copy manufactures a finding and hides the real one. 1.24.0 adds a
  pre-spend `record` preflight that warns when a cassette would be written outside the scenario tree.
- **Always pass `--out <skill>.json`.** The index cannot attribute a critique: it records
  `command: "skill"` (not `critique`), carries no `skill` field despite `--skill`, and `session.json` has
  neither `skill` nor `prompt`. Concurrent critiques are otherwise indistinguishable. `--label` still
  lands on turn 1 only — deliberately, since labelling the reflection turn would inject a near-always-green
  row and inflate `passRate` — but as of 1.14.0 a label-filtered **cost** total is no longer short: `stats`
  re-admits the dropped rows by shared `runId`, counting them toward cost only, never toward
  `runs`/`passRate`/percentiles.
- **Everything the harness prints goes to STDERR; stdout is empty.** Verified on `run`, `replay` and
  `status` at 1.17.0. Two consequences. First, a wrapper that captures only stdout gets an empty
  log — which is where the older "no progress output" note came from. Second, and this one bites:
  the obvious poll `until ! cowork-harness status "$D" | grep -q '● running'` **exits immediately
  and silently** (grep sees nothing on stdout, returns 1, `!` inverts it). **Do not "fix" it with
  `2>&1` — that is the worst of the three options.** Two stdout forms already exist and are the right
  answer: **`status <dir> --follow`** (the harness owns the poll loop and exits at a terminal state —
  prefer this) and **`status <dir> --output-format json`** (one envelope on stdout carrying `state`
  and `stale`). A long run also self-reports on stderr — `… still running (450s · 52 tools)` —
  documented in `run --help` under "Long runs", with `COWORK_HARNESS_NO_HEARTBEAT` /
  `_HEARTBEAT_MS` to disable or tune. That heartbeat is NOT new in 1.17.0; the older note here was
  wrong when written, and reading `run --help` would have caught it. Do NOT poll the outputs dir for artifacts (the advice that used to live here): use
  **`cowork-harness status <dir> [--follow]`**, which reads the `status.json` the harness maintains
  throughout the lifecycle. It reports `state` / `elapsedMs` / live `toolCounts`, and detects both a
  thrown error and a `SIGKILL`/OOM staleness — so `"running"` is never permanently trusted, which
  artifact-watching cannot tell you. The run prints `[status] <outDir>` to stderr at startup — **except
  under `--compact`/`--demo`**, which withhold it deliberately (it is a raw host path). `status.json` is
  written either way, and `cowork-harness status` also accepts the run-dir root.
- **`[provenance]` (1.25.0) answers "which experiment actually ran?" for free — and `model` is the
  part that is new to us.** Every run verdict, passing or failing, replay lane included, now prints
  `[provenance] model=… skill=offered,invoked ablated=…`, and the same object rides
  `results[].provenance` in the JSON envelope. **Measured across all committed cassettes (22 AT THE TIME; the corpus was cut to 10 on 2026-08-24 — re-derive, never inherit):
  `claude-sonnet-4-6` and `offered,invoked`, uniform.** Record that: a corpus silently spanning two
  models is a real hazard here (the model-tier acceptance rule exists because tier changes
  correctness), and nothing checked it before. **Do NOT read `skill=…invoked` as proof the skill under
  test ran** — `provenance.ts:52-57` says it is deliberately "was the Skill channel used at all" and
  that identity belongs to `skill_triggered`, which this fleet already asserts on **22/22** cassettes.
  `offered,unknown`/`unknown` mean evidence-UNAVAILABLE, never "no". `--compact`/`--demo` suppress the
  line, matching `[status]`.
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
- **After editing any `assert:` block, run `replay --assert-from` BEFORE paying for a re-record.**
  `cowork-harness replay cassettes/<s>.cassette.json --assert-from scenarios/<s>.yaml` re-checks the
  on-disk assertions against the committed cassette — token-free, no Docker, ~1 second. Measured: it
  reports a bad assertion as `✗ only 0 gate answer(s) confirmed delivered, need ≥ 1`, the exact
  failure that later cost **two paid runs (~$6.70)** to discover. It refuses (correctly) when the
  **prompt** drifted — the frozen events no longer correspond to the scenario — and that refusal is
  itself the answer: a prompt change requires a re-record and cannot be pre-checked. `verify-run`
  is the equivalent against a kept run dir, but it **fail-closes on a PARTIAL run**, so a run that
  died on an unanswered gate cannot vouch for anything.
- **`lint` is LENIENT; the loader is STRICT — a clean lint does not mean the scenario loads.**
  Measured: deleting the last rule under `answers:` left the key parsing as `None`, which `lint`
  passed as *"1 scenario(s) clean"* while the runtime rejected the file outright. It was caught only
  by `rerecord.sh`'s budget preflight, which silently **omitted the broken scenario from its list**
  rather than announcing it. Validate with **`cowork-harness record scenarios/<s>.yaml --dry-run`**
  (free, no token, no Docker) — a broken file prints `✗ broken:` and exits non-zero.
- **A `gate_answers_delivered` that lint flags as vacuous has TWO valid remedies, and lint only names
  one.** Its fix line says to pair it with `gate_answer_count_min: 1` / `question_asked` /
  `tool_called`. That is wrong for a scenario **designed** to fire no gates: there the remedy is to
  **drop `gate_answers_delivered`**. `cap-table-lane3-freeform` is gate-clean by design (its cap base
  is `deterministic_mapped`, which SKILL.md exempts from the confirmation gate) and its own header
  says so; adding the companion there asserted a gate the skill correctly never raises. Check whether
  the scenario expects a gate before taking lint's advice.
- **Never pipe `verify-cassettes` to `tail`** — deterministic `EAGAIN` crash (unbuffered `writeSync` to a
  non-draining pipe) that replaces the verdict line with a stack trace. Redirect to a file instead.
- **The PII gate needs the allowlist EXPANDED, not merely sourced — and every `--allow*` regex is
  FULL-MATCH.** `privacy-allowlist.sh` defines a bash **array**, so `source` alone changes nothing;
  the gate is `source cowork-tests/privacy-allowlist.sh && cowork-harness verify-cassettes
  cowork-tests/cassettes "${ALLOW[@]}"`. Sourced-but-not-expanded reports ~7,200 findings and exit 1
  (synthetic deal amounts and public citation domains, not leaks) — which reads exactly like the
  allowlist breaking. Expanded it is **0 PII findings across the whole corpus** — re-measured 2026-08-27 at 10 cassettes; the count in this line has been 16, then 21, and is now stale by construction (the count was 16 when this
  line was written; re-derive it, don't trust it). Full-match matters when editing an entry:
  `founder-skills:.*` clears the host-inventory class, the tighter-looking `^founder-skills:` clears
  **zero**, because an explicit anchor lands inside the harness's own wrapping. An over-tight regex
  fails safe (findings stay); an over-loose one disarms a whole class with no signal — so re-count
  findings after any edit, and confirm `canary/email-canary.cassette.json` still flags `[email]`.
- **`host-inventory`: 1.18.0 flagged our own plugin's agents; 1.19.0 fixed it, and the allow entry is
  GONE.** The class catches a recording machine's MCP servers / account / agents / skills frozen into a
  cassette by a host-inheriting tier — our tier. At 1.18.0 it reported **240 findings, all
  `agents[] — founder-skills:<skill>`**: the six agents of the plugin under test, i.e. the fixture. We
  suppressed them with `--allow-host-inventory 'founder-skills:.*'`. **1.19.0 exempts them
  automatically** — an `agents[]`/`skills[]` entry namespaced `<plugin>:<name>` whose plugin the same
  recording declares in `plugins[]` is not host inventory. The exemption is derived from the cassette,
  so it applied to every existing recording with **no re-record**: measured 240 → 0, with
  `verify-cassettes` output byte-identical to the run that still carried the allow. The entry was
  **deleted**, not kept: a suppression that suppresses nothing invites misreading the gate.
  **This makes the CLI floor load-bearing** — on 1.18.0 the current allowlist reds on 240 non-findings
  (measured, `npx cowork-harness@1.18.0`: exactly 240, exit 1). Floor every consumer of
  `privacy-allowlist.sh` at `>=1.19.0` — though the **replay floor is `^2.1.0`, the RECORDING floor `>=2.4.0`, and the CI selectors are PINNED EXACTLY at `2.4.0`** — see the 2.x section below. 1.24.0 was an earlier repo-wide floor, raised because the
  scenarios stop LOADING below it (`deck-review-gate-stop` asserts `file_absent` + `question_options`;
  measured, a 1.23.0 `record --dry-run` reports `Unrecognized key`, while `lint` on the same file exits
  0 — the loader catches it and lint does not). See the 1.24.0 adoption plan. Keep both numbers: 1.19.0 is what
  *this file* needs, and is the level to fall back to if the repo floor is ever lowered.
  **Standing risk:** the green now depends on `plugins[]` carrying
  `founder-skills` in every future recording — strip `plugins[]` from one cassette and it alone yields
  18 findings. If a re-record ever reds this gate en masse on our own namespace, the cause is a missing
  `plugins[]` declaration, not a leak; do not re-add an allow.
  **New axis (1.19.0): `skills[]`**, same two exemptions (the agent's built-ins — currently just
  `deep-research` — plus a declared plugin's own). All **22** cassettes carry a populated `skills[]`; 7
  names, 0 flagged (re-measured 2026-08-20 — the count was 21 when written).
  **Where to look, because this has now cost one wrong finding:** the array is inside the `system`
  init frame in `events[]`, and **`events[]` entries are JSON-ENCODED STRINGS**. A recursive walk that
  does not `json.loads` every string leaf finds nothing and will conclude the axis does not exist —
  an adoption-plan draft did exactly that, then mistook `scenario.skills` (the per-cassette
  single-element STALENESS-SCOPING key, corpus union 6) for this axis and proposed rewriting this
  paragraph as false. It is not false. **That zero is structural, not earned**: the axis targets the `protocol` tier, where
  the harness keeps the operator's real `CLAUDE_CONFIG_DIR`; we record at hostloop, which does not. A
  population count does NOT prove the axis works — every name we carry is exempt by construction, so a
  no-op would produce the same zero. Non-vacuity was confirmed by **probe**: inject a foreign skill name
  into a cassette copy and it fires. Note the scan is tier-gated, so `skills[]` is *present* in 21/21 but
  *read* in 21/22 (`host-path-canary` records at `container`).
  **1.25.0 fixed the built-in roster** — it held one name (`deep-research`) while the agent had grown
  fourteen more, so a fresh `protocol` recording reported 14 false host-inventory findings, the exact
  push toward a blanket `--allow-host-inventory`. **Measured impact on us: 0 → 0**, because our one
  bare name was already in the old roster. It would matter the moment we record at `protocol`.
  The three predicates that would mean a **real** leak — `mcp_servers[].name`,
  `account.email`/`.organization`/`.subscriptionType`, and a `mcp__<server>__…` tool naming a foreign
  server — return **NONE** across the corpus (22 when measured, 10 today — the verdict held at both). Not covered by the class (upstream's `docs/cassette.md`): the
  **command and plugin** catalogs and command descriptions. (The *skill* catalog used to be on that list
  and no longer is — see the new axis above. `plugins[].name` is deliberately not an axis: it is the
  harness's own declaration channel.) A green is a backstop, not proof.
- **`verify-cassettes` opens with a per-class rollup (1.19.0) — and it counts INFORMATIONAL classes
  too.** e.g. `findings by class: unscanned 54`. Our current corpus reads exactly that and still
  **exits 1** — from staleness + scenario-drift, not privacy. A non-empty header is not a privacy
  failure; a header showing only `unscanned` means the PII gate is clean (the CI privacy step skips
  both non-PII classes and exits 0). The rollup is additive — every per-file row still prints. JSON
  consumers already had `findings[].cls`.
- **`replay --mutate` SAMPLES — never read its ratio as an assertion-failure rate.** It reports e.g.
  `50/50 perturbation(s) CAUGHT BY NOTHING`, which parses as "50 of your 50 fields". It is not.
  **There are TWO caps, not one: 10 per file and 50 in total, and the PER-FILE cap is applied first.**
  (The single-cap reading is what produced a wrong "`--mutate-max-total 25000` perturbs everything"
  claim — measured, it yields 2,567 of 21,478, because per-file still binds.) On our corpus **19**
  cassettes report `50/50` and **two** (`cap-table-fast-assess`, `host-path-canary`) report `35/35`;
  1,020 = 19×50 + 2×35. As of 1.19.0 the caps are documented in `--help`, the changelog **and**
  `docs/`, and the report appends the eligible total and names the binding cap:
  `(sampled 35 of 55 eligible value(s); per-file cap 10 reached on 2 file(s))`. **`55` is the eligible
  total, NOT the ratio's denominator** — reading the new parenthetical back into the ratio is the same
  conflation in a new costume. JSON carries it as `mutation` = `{sampled, eligible, truncatedBy, caps,
  uncaught}`; aggregate over that, not over stderr text.
  Measured fleet-wide: **1,020 sampled of 21,478 eligible = 4.75% coverage**, all uncaught. That is
  **coverage thinness, not assertion failure**. Of the uncaught, **31%** sit under `handoff/` — the
  older note here said "most", which was generalized from one cassette and is false (range 0 to 31 of
  50). Scoped to the delivered report (`--mutate-include '**/report.json' --mutate-max-per-file 500`)
  the pass is **exhaustive**, not sampled: **1,221 of 1,221 values across 16 scenarios guarded by no
  *value* assertion** (some scenarios do carry `exists: true` asserts, which are structurally
  insensitive to a perturbation). Reporting-only by design and deliberately NOT a CI gate — a count
  ratchet over `report.json` would red on every legitimate re-record.
  Two glob traps: the matcher is **anchored and case-sensitive**, so `--mutate-exclude 'handoff/**'`
  (the form upstream's own `--help` and `docs/` print) matches **nothing** against our `outputs/…`-
  prefixed paths — use `'**/handoff/**'` (measured 1,236 → 1,141 on `cap-table-acquisition`); and
  `'**/report.json'` cannot match a root-level `report.json`. Also: `report.json` is committed
  **body-less** on `deck-review-smoke` and `ic-sim-contested`, so it is neither mutatable nor
  `artifact_json`-assertable there.
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
uv run pytest -m cowork                             # token-free cowork-harness cassette replay (needs `npm i -g cowork-harness@2.4.0` — exact, matching CI; no Docker/token)
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

The three e2e smokes drive the SDK against synthetic fixtures. Auth options (any one):

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

0. **Refresh cowork cassettes** (release cadence): `cowork-tests/rerecord.sh` (paid/local; it preflights `cowork-harness doctor --tier hostloop` — needs Docker, the `:2` agent image, and BOTH staged agent binaries: the Linux/arm64 ELF and the native Desktop host binary the hostloop agent loop spawns) → confirm green, commit refreshed `cassettes/` by name. Since the 0.24.0 pin, `fidelity: cowork` records at **native hostloop** (real host paths in transcripts, stripped by the `cowork-tests/.cowork-redact.json` redaction policy at record time — `record` refuses to write a cassette whose asserts or `computer://` links redaction broke). `rerecord.sh` records in a bounded parallel pool, prints a normalized `cowork-harness diff` per refreshed cassette (the primary drift review), and tails `stats` + `prune`; runs land in the harness-default `~/.cowork-harness/runs` so `stats` can trend reliability across re-records. The cowork-replay staleness gate is WARN-only, so cassettes drift between releases; this re-records them against the current baseline/format. Skip only if no skill/`scripts/`/`references/`/`agents/` change landed since the last refresh. **Staleness is skill-scoped, and knowing that bounds the refresh:** every scenario declares a `skills:` key (`competitive-positioning-smoke.yaml:5` — "scope the staleness hash to this skill + shared roots"), so an edit under `skills/<skill>/` stales only that skill's cassettes. The mount stays whole-plugin either way — narrowing it is what reintroduces a false-green. **"Shared root" means everything NOT under `skills/<x>/`**, per the harness (`docs/cassette.md`), and the cassette `fileSigs` confirm it: `competitive-positioning-smoke` hashes `.claude-plugin`, `LICENSE`, `agents`, `commands`, `references`, `scripts` alongside its own skill dir. So `commands/feedback.md` and `plugin.json` stale the fleet too — do not read the shared set as just `scripts/`/`references/`/`agents/`.

**CURRENT STATE (2.x). Read this before any per-release note below it — those are floor history and several of their numbers are superseded here.**

* **Three postures, per site, not one number — and two of them are no longer floors at all.**
  **CI selectors are PINNED EXACTLY at `2.4.0`** (the four workflow `version:` inputs, the
  `skill-static-analysis` `npm i -g`, and the three install instructions in `CONTRIBUTING.md`,
  `CLAUDE.md` and `pyproject.toml`). Carets auto-adopted every upstream release into CI with nobody
  choosing it — 2.4.0 was live in our gates before its adoption plan was written — and five CI steps
  red on rules the harness adds. Raise them deliberately, in an adoption pass, never to chase a red.
  `test_cowork_harness_floors.py` gates all of them, `CLAUDE.md` included (it was ungated until
  2026-08-27). Recording: **`>= 2.4.0`** (`rerecord.sh`'s gate — the numeric
  test and its FATAL message are ADJACENT lines; find them with `grep -n 'minor.*-ge'`, never by line
  number, which has been wrong here before). Replay floor: **`^2.1.0` at exactly ONE site now** —
  `test_cowork_cassette_replay.py::_MIN_HARNESS`. The other sites this line used to name (the four
  workflow `version:` inputs, the `skill-static-analysis` install, `pyproject.toml`'s marker) became
  exact CI pins on 2026-08-27 and are no longer floors. `_MIN_HARNESS` is a SKIP GUARD, not a
  selector: it decides whether the replay test runs at all, not which CLI CI installs — which is why
  it does not track the pin. It is deliberately NOT at 2.2.0 or above:
  measured, there is no requirement, and raising `_MIN_HARNESS` converts a below-floor developer's red
  into a silent skip. `test_cowork_harness_floors.py` pins every site.
* **`uses:` pins the ACTION, `version:` pins the CLI, and they move independently** — a workflow on
  `@v1` installs a 2.x CLI perfectly happily, which is how the wrapper pin sat a major behind. Keep the
  majors in step; a test enforces it.
* **Corpus and cassette format are DERIVED, not restated.** Run `python
  cowork-tests/cassette_inventory.py`. Every cassette in `cowork-tests/cassettes/` is `cassetteVersion`
  **12**; `MIN_SUPPORTED_CASSETTE_VERSION` is **9**; the hand-authored email canary is deliberately
  **v10**. Any count in prose elsewhere in this file is stale by construction — the corpus was cut on
  2026-08-24 and prose has been wrong about it repeatedly.
* **`2.4.0` moves NO baseline leaf, but DOES add re-record debt — the two are different things.**
  `baselines/` is byte-identical `v2.3.0..v2.4.0`, so a baseline diff shows nothing. The change is in
  the harness's own EMULATION code, which the baseline does not describe: (a) hostloop's workspace
  bash now starts at the **bare session root** `/sessions/<id>` (`hostLoopCwds`), not
  `<session>/mnt/<first-folder-else-outputs>` — upstream measured production on 2026-08-27 and the
  replaced derivation reproduced a prompt claim, not a behaviour; (b) `container` no longer offers the
  built-in `WebFetch` under `run`/`record` (aliased to `mcp__workspace__web_fetch`; `microvm` and
  `chat` unchanged). Both are emulated-tool-surface triggers by our own rule, hence the 2.4.0
  recording floor. **Blast radius here, measured:** `resolve_artifacts_root.py` flips from branch 2 to
  branch 3 and returns **identical** roots (the branches converge on purpose — do not let them
  diverge); zero `tool_not_called`/`WebFetch` anywhere in the scenario corpus; 27 of 27 scenarios
  already declare `fidelity:`, so the new `fidelity-defaulted` deprecation is pre-satisfied. What it
  DID surface: two SKILL.mds ran `mkdir -p ./artifacts` (now `"$ARTIFACTS_ROOT"`) and deck-review
  located uploads via a cwd-relative `./mnt/uploads` (now `resolve_artifacts_root.py --uploads`).
  `verify-cassettes` gained a `replaced-builtin` NOTE (not a finding, does not affect exit code) that
  fires on `host-path-canary`; upstream says explicitly it is not a reason to re-record. Full
  analysis: `docs/internal/2026-08-27-cowork-harness-2.4.0-adoption-plan.md`.
* **`2.2.0` adds no re-record debt and changes no replay verdict.** Measured against a pinned 2.1.0:
  every token-free surface byte-identical on this repo (`replay` ×10, `verify-cassettes` + allowlist,
  `lint --strict`, `record --dry-run` over all scenarios, `analyze-skill --strict`, `lint-skill
  --strict`), and `baselines/` byte-identical between the two releases, so no fidelity input moved.
  Our baseline is whatever `latest` resolves to (nothing declares `baseline:`) — re-derive after any
  `sync` or Desktop bump.
* **What 2.2.0 DOES change, and it is the reason the recording floor moved:** `present_files_called`
  takes presence from `RunResult.presentFilesCalls`, a count of `present_files` invocations carrying a
  well-formed `file_path`, read from the tool_use input's SHAPE. Below that floor it reads the
  classified `presentedFiles` list, which drops a non-absolute path — and at hostloop every presented
  path is a host path that `cowork-tests/.cowork-redact.json` rewrites, so the assert flips false under
  redaction and `record` refuses to write. **The count is RE-DERIVED from frozen events at replay, not
  stored in the cassette**, so it evaluates on recordings made before the field existed: measured, all
  seven delivering lanes fail the key under 2.1.0 and pass under 2.2.0 on their *existing* cassettes.
  Those seven now carry the assert on disk; it freezes at their next re-record (plain `replay` reads the
  frozen block, so it gates nothing until then).
* **`analyze-skill --strict` does not exit 1 on an advisory finding** — measured 2 advisory
  `artifact-write-back-suspect` findings, exit 0, under both 2.1.0 and 2.2.0. Only `error` severity
  gates.
* **Two behaviour changes in 2.2.0 that are inert HERE but would not be everywhere:**
  `no_scratchpad_leak` can now genuinely fail at container (we assert it nowhere), and a baseline with
  no `spawn` block is refused at the sandbox tiers (ours has one).

**In principle a single-skill fix is a single-skill re-record. In practice, right now, it is not** — measured 2026-08-15, all committed cassettes are ALREADY fleet-stale on two counts that no skill edit can avoid: a baseline move (now `1.24012.9 → 1.32352.0`), and shared-root changes since record. Zero cassettes are stale for skill-local reasons alone. So scoping tells you what a change *adds* to the backlog, not that the backlog is small; until the next full refresh clears the baseline drift, "just re-record that skill's four" leaves everything else red. Re-derive with `cowork-harness verify-cassettes cowork-tests/cassettes --skip-scenario-drift` rather than trusting this paragraph. `rerecord.sh` enforces a **harness floor of `>=1.24.0`** (see its own header for why each floor moved; the numeric gate and its message are ADJACENT LINES — locate them with `grep -n 'minor.*-ge' cowork-tests/rerecord.sh`, because editing the string alone leaves the gate a minor behind, and the line numbers quoted here have already been wrong once) — recording is the one operation that bakes the harness version into the artifact: **1.12.0 fixes a bug that made an upload-bearing scenario impossible to record while still spending the paid run** (the artifact↔root check measured `uploads/` artifacts against the user-visible roots, which exclude uploads, and threw *after* the agent run — five scenarios here are upload-bearing), 1.11.0 stamps `environment.harnessVersion` (never backfilled, so an older CLI records a permanently provenance-less cassette), and 1.10.0 is the first release whose sandbox declares the skill/plugin discovery SDK-MCP servers (an older CLI freezes a tool inventory five tools short of what real Cowork advertises). **Committed cassette state — SUPERSEDED, kept only because the paragraph's MECHANISM is still right. Re-measured 2026-08-27: 27 scenarios / 10 cassettes. The 2026-08-18 reading below (26 scenarios / 22 cassettes — 4 uncassetted)** (`competitive-positioning-deck-no-slide`, `competitive-positioning-recall-adoption`, `deck-review-numeric-chain` — the last deliberately, see `_NO_CASSETTE_ALLOWLIST` — and `market-sizing-fx-conversion`). Three were re-recorded at 1.19.0 for 0.7.0 (`ic-sim-smoke`, `competitive-positioning-smoke`, `financial-model-review-smoke`); the rest are older and stale-but-accepted; `cassetteVersion` is 10 except the `lane: remote` one, which is v11. (This line previously said "all 16, recorded at 1.12.0" — **re-derive it after every re-record rather than trusting the number here**; it has now been wrong twice.) The v9-read-floor urgency that used to live here is spent, and so is the outstanding 1.10.0 discovery-surface refresh — that re-record happened. What remains is *mostly* ordinary `skillHash` staleness, which the WARN-only gate reports and only a re-record clears — the one exception is `market-sizing-smoke`, whose on-disk `present_files_called` assert postdates its 1.12.0 recording and so never runs under plain `replay` at all (see the mechanism note below — it is NOT the "evaluated but vacuous" case this line used to describe). A future read-floor raise would refuse them at load time and `rehash` cannot cross a version boundary, so the next floor bump still means a re-record — but that is a future event, not a live risk. The bare form refreshes only scenarios that already have a committed cassette (it prints what it skipped); author a new cassette by name.

**Re-record trigger (beyond "a skill changed"):** re-record on every harness **major**, *and* on any release — including a minor — whose changelog reports a change to the **emulated tool surface, spawn env, or system prompt**. Those are the fidelity inputs with no automatic staleness tripwire, so nothing will tell you: the changelog is the authority. `1.10.0` was the first such minor (it added the discovery SDK-MCP servers) and **that debt is settled** — every committed cassette is at `1.12.0` or later, which necessarily carries them. The `1.14.0` trigger (`present_files` served at **hostloop**, the tier this fleet records at, where the harness previously served it only at `container`, so a recording froze a toolset one `alwaysLoad` tool short of production's) is **now discharged for 20 of 21** — see the measured note below. The one remaining `1.12.0` cassette (`market-sizing-smoke`) still carries the short toolset. (`1.15.0` adds no re-record debt: a CLI flag, a notice and docs, with `baselines/` and `schema/` byte-identical to 1.14.0.) Full analysis: `docs/internal/2026-07-31-cowork-harness-1.14.0-adoption-plan.md`.

**`1.17.0` adds no re-record debt either — verified, not assumed.** `baselines/desktop-1.24012.9.json` DID change between `v1.16.0` and `v1.17.0`, so the byte-identical test that cleared 1.15.0 does not apply; the change had to be read. Diffing the parsed baseline field-by-field: `spawn.tools`, `spawn.allowedTools`, `spawn.env`, `spawn.promptTemplate`, `spawn.subagentPrompt`, `spawn.options` and `spawn.effortDefault` are **byte-identical**. The only additions are a `hooks` object and its `$comment_hooks`, which the harness itself labels "Recorded as a DRIFT TRIPWIRE, not an emulation source — `served` marks what this harness actually installs (`PreToolUse:Task` only)". So none of the three fidelity inputs (tool surface, spawn env, system prompt) moved. **When a future release touches `baselines/`, run that field-level diff rather than a file-level one — a changed baseline is not by itself a re-record trigger.**

**`1.18.0` DOES add re-record debt, and the field-level diff is what sized it.** Default baseline moves to `desktop-1.25927.0` (the installed Desktop), and the proactive skill-suggest gate now models **ON** — a **server-side** rollout, so it reads ON on earlier Desktop versions too; `suggest_skills` therefore declares a proactive description plus an optional `trigger` param by default. That is a **tool-surface** change, hence a trigger. Diffing `desktop-1.24012.9` (what the committed cassettes recorded against) → `1.25927.0` field by field, the only moving fidelity inputs are the **agent ELF (2.1.219 → 2.1.221)** and **`spawn.env.MCP_TOOL_TIMEOUT` (60000 → 180000)**. Everything else holds: `spawn.tools`, `allowedTools`, `promptTemplate`, `subagentPrompt`, `options`, `effortDefault`, `settings`, `guest`, `platform` byte-identical; `network.allowDomains` differs in **order only** (added `[]`, removed `[]` — a naive first-element comparison reads as a change and is not one); the `mountLayout` `projects` row's `rw`→`r` correction is documented **in the baseline itself** as "consumed by nothing". Upstream reports its own cassettes replay clean across this move and were **re-stamped, not re-recorded**. Verdict: real debt, materially smaller than the 1.14.0 `present_files` trigger, and **folded into the existing re-record batch rather than treated as a new one** — every cassette is already `skillHash`-stale anyway. `rerecord.sh`'s floor is now `>=1.18.0`, because a 1.17.0 recording would freeze the pre-rollout tool surface and carry no gate-label fingerprint. Full analysis: `docs/internal/2026-08-06-cowork-harness-1.18.0-adoption-plan.md`.

**`1.20.0` adds NO re-record debt from its baseline, but IS the floor — and the two facts are separate.** Default baseline moves `desktop-1.25927.0` → `desktop-1.26832.0` (agent ELF 2.1.221 → **2.1.222**). An **exhaustive recursive** leaf diff — not a hand-list — leaves every fidelity input byte-identical: `spawn.tools`, `allowedTools`, `env` (21 keys), `promptTemplate`, `subagentAppend`, `subagentAppendHostLoop`, `hooks`, `effortDefault`, `settings`, `guest`, `platform`, `mountLayout`, plus top-level `bgEnvStrip` / `requireFullVmSandbox`. Only the ELF, `capturedAt` and `provenance.*` move. **`network.allowDomains` differs in ORDER ONLY** (set-difference empty both ways) — that trap has now fired **three times** (1.18.0, 1.20.0, 1.24.0). Treat it as a standing rule, not a per-release discovery: **always compare `allowDomains` as a SET.** `provenance.spawnEnvKeys` gains `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC` (spread 29 → 30) but it is **not** in `spawn.env`: allowlisted, not pinned. Two gate movements the upstream changelog names, both inert here: `scheduledTaskToolsApprovableByAutoMode` flips force-on (Cowork spawns `CLAUDE_CODE_DISABLE_CRON=1` regardless — verified in the new baseline's `spawn.env`), and `coworkRuntimeConfig` begins serving `skillsSyncIntervalMs`/`pluginsSyncIntervalMs` (20 min) + `pluginsFullSyncStalenessMs` (1 h). **Use the hand-list trap as a warning:** a first pass at this diff "verified" `spawn.subagentPrompt`, `spawn.options` and `coworkSyspromptMap` as IDENTICAL when **none of those keys exists** — three vacuous passes in the check whose entire job is to detect movement. Diff every leaf, then name what moved.

**Why 1.20.0 is nonetheless the floor:** our Desktop stages **only** agent 2.1.222. On a 1.19.0 CLI, `doctor --tier hostloop` records but reports `sha256 ✗ vs baseline` / `parity mount: patch-tolerated (pinned 2.1.221, using 2.1.222)`; at 1.20.0 the same check reads `sha256 ✓`. Recording at 1.19.0 freezes a tolerated ELF mismatch into every cassette. Separately, the **harness-side spawn env** did move in ways no baseline diff can see — `NO_PROXY`/`no_proxy=localhost,127.0.0.1,::1` added (`src/runtime/argv.ts:173-174`), and the hostloop `bash` sidecar's empty literal env replaced by the computed proxy env, restoring egress that had been dead since v0.21.0. By our own trigger rule that is a spawn-env change; **measured blast radius for this fleet is zero** (no script makes a network call from bash; no SKILL.md shells out to the network; the one localhost server, `review_inputs.py --workspace`, is Claude-Code-only and the Cowork lane asserts `transcript_not_matches: "--workspace"`; cassettes freeze no spawn env). Folded into the existing batch, not treated as new debt. **Watch item:** a re-recorded agent can now improvise a shell command no SKILL.md mentions, and its failure mode changed (allowlist `403` vs DNS error) — measured zero hits for `curl|wget|pip install|uv run|npx|apt-get|git clone` across all 21 committed cassettes, so the risk is real but small.

**`1.20.0` tooling changes that alter how we validate.** `record --dry-run` now **refuses what the real `record` refuses** — `assert-contradiction` and `on_unanswered: prompt`, the latter previously enforced in the single-file arm only and never in a directory batch — reports **every** offender rather than stopping at the first, and prints the batch cost estimate **on stderr** without needing a `--max-budget-usd` bisect (JSON carries `estimatedCostUsd` + `unpricedScenarios` on stdout). Both dry-run fixes came from this repo's pre-release review. `lint`'s `vacuous-gate-assert` was wrong four ways, two of them silent false-greens (`gate_answer_count_min: 0` accepted as a presence companion though `delivered >= 0` always holds; a wrong-case `tool_called` glob silencing the rule), and `assert-contradiction` (ERROR) is new. **Our CI lint step therefore gained `strict: true`** — measured, a WARN-class finding exits 0 without it and 1 with it, so the rule 1.20.0 just fixed was ungated here; ERROR-class reds either way. Do **not** copy `strict: true` onto the replay steps: there it also fails on cassette staleness, which is WARN-only by design. Also new and worth knowing: upstream's `docs/fidelity-gaps.md` now documents that real Cowork **re-syncs host skills/plugins into a live session** (~20 min), while the harness stages once per run and never re-stages — a deliberate divergence, and a limit on what a green cassette proves. Full analysis: `docs/internal/2026-08-07-cowork-harness-1.20.0-adoption-plan.md`.

**`1.21.0`–`1.24.0`: real but tiny re-record debt, and the floor moves for a DIFFERENT reason.** Default baseline moves `desktop-1.26832.0` → **`desktop-1.32352.0`** (agent ELF 2.1.222 → **2.1.229**), spanning four releases with no adoption pass between them. **Exhaustive recursive leaf diff, 2026-08-18:** `spawn.tools`, `allowedTools`, `promptTemplate`, `subagentAppend`, `subagentAppendHostLoop`, `hooks`, `effortDefault`, `effortByModel`, `permissionMode`, `settingSources`, `maxThinkingTokens`, `configDirInGuest`, and top-level `settings` / `guest` / `platform` / `mountLayout` / `bgEnvStrip` / `requireFullVmSandbox` are **byte-identical**. Exactly one pinned spawn-env key is added — **`CLAUDE_PREVIEW_CLASSIFIER_FLOOR: "1"`** — which is a spawn-env change and therefore a re-record trigger by our own rule, with a blast radius of approximately nothing. `provenance.spawnEnvKeys` 60 → 63 (the other two are **allowlisted, not pinned**), plus four gate sentinels and a `coworkWebFetchDedupTtlMs` bump. `allowDomains` order-only again (see the standing rule above). Fold into the existing batch; every cassette is already stale.

**The floor is `>=1.24.0` for a reason unrelated to fidelity: the scenarios stop LOADING below it.** `deck-review-gate-stop` now asserts `file_absent` and `question_options`. Measured against `npx cowork-harness@1.23.0`: `record --dry-run` (the loader) HARD-REJECTS with `Unrecognized key: "file_absent"`, while `lint` on the same file exits 0 with `0 error(s)` — the lenient-vs-strict split, live. The same applies to `replay` once a key is frozen into a cassette, and **`cassetteVersion` does NOT bump** (stays 10), so the version field gives no warning. (A developer pinned below the floor gets a SKIP, not a red: `_require_harness` calls `pytest.skip` for a below-floor version as well as an absent CLI. Raising `_MIN_HARNESS` therefore converts a loud red into a silent skip for exactly the developer it warns.)

**Two fidelity gaps that are NOT re-record debt and need watching.** (1) **The elicitation CONFLICT gap** — because the host's injected form guidance is absent here, so is every conflict between it and a skill's own instructions. All six SKILL.mds carry a literal `AskUserQuestion` "(NOT plain chat)" directive, and **all six also carry the host-override fallback sentence** — an earlier claim here that two skills lacked it was WRONG and is corrected: `financial-model-review:270` is covered at `:279`, `cap-table:518` at `:526`. The one uncovered site is **`cap-table:451`** (the Step 0 gate, 75 lines from `:526`, whose text is scoped to "this gate"). This class is structurally unobservable by any harness run — a skill can ship a directive production silently overrides with every cassette green, so do not expect a cassette to prove a fix. (2) **The `Artifact` tool** — 1.24.0 records that the frame-artifacts predicate dropped its `!isHostLoop` term, so `Artifact` now reaches the hostloop tier this fleet records at, while the harness serves it at **no** tier and the selecting flag is server-delivered and not locally observable (off by default today). Revisit trigger: a real session showing `Artifact` in its tool list. Full analysis: `docs/internal/2026-08-18-cowork-harness-1.24.0-adoption-plan.md`.

**Two `COWORK_*` env vars were REMOVED in 1.20.0 and never worked:** `COWORK_EGRESS_PROXY` and `COWORK_DOCKER_NETWORK` sat behind values the caller always supplies, so the env branch could not execute in any tier. Neither appears anywhere in this repo, so there is nothing to migrate — recorded only so nobody adds them from an old README. `COWORK_PROXY_IMAGE`, in the same upstream bullet, is genuinely live.

**The `1.14.0` `present_files` trigger is DISCHARGED and COMMITTED** (as of `cf0277a`). Re-measured across every committed cassette on 2026-08-06: **21 tracked cassettes — 14 at 1.16.0, 3 at 1.17.0 (`cap-table-safe-full`, `market-sizing-remote-lane`, `competitive-positioning-false-positive`), 3 at 1.19.0 (`ic-sim-smoke`, `financial-model-review-smoke`, `competitive-positioning-smoke`), and exactly ONE still at 1.12.0 — `market-sizing-smoke`.** Everything >= 1.14.0 necessarily carries the hostloop `present_files` surface, so `market-sizing-smoke` is the entire remaining scope. **This supersedes BOTH earlier counts in this file** — "all 16 at 1.12.0" and "19 at 1.16.0, 2 still at 1.12.0 (`ic-sim-smoke`, `market-sizing-smoke`)" are each wrong; `ic-sim-smoke` was re-recorded at 1.19.0. Derive the distribution by reading `environment.harnessVersion` out of the cassettes; this line has now been wrong twice.

`market-sizing-smoke` is not merely "stale". Its on-disk scenario asserts `present_files_called: true`, the frozen 1.12.0 cassette contains no `present_files` call, and a plain `replay` nonetheless returns `✓ success` — only `replay --assert-from` surfaces the failure. Treat it as a guard that reads live in the repo and gates nothing in CI, not as ordinary drift.

**The MECHANISM is not what this note said until 2026-08-15, and the difference decides where else to look.** The old text called the assert "vacuously" green — evaluated, and trivially true against a cassette with no `present_files` call. It is not evaluated at all. **The cassette's frozen scenario carries 16 asserts and `present_files_called` is not among them**: the assert was added to the on-disk YAML *after* the 1.12.0 recording, and `replay` reads the frozen copy (`cowork-replay.yml` says so in its own comments — "`replay` evaluates the scenario FROZEN in each cassette and never reads the on-disk YAML"). Measured on harness 1.23.0, 2026-08-15:

```
replay cassettes/market-sizing-smoke.cassette.json                    -> exit 0, "✓ success"
replay ... --assert-from scenarios/market-sizing-smoke.yaml           -> exit 1
   ✗ present_files_called: no file was delivered via present_files (the tool was never called)
   ✗ skill-source drift (--fail-on-skill-drift): skills/market-sizing changed since record
```

**Generalize it, because this is not about one cassette — measured, it is about most of them.** ANY assert added to a scenario YAML after its cassette was recorded is invisible to plain `replay`: CI reports on the assert set frozen at record time, not the one in the repo. `replay --assert-from` evaluates the on-disk block (which is why "run `--assert-from` BEFORE paying for a re-record" appears in the `critique` section above) — **and `--write` then persists it back into the cassette for free.**

Comparing every on-disk `assert:` key against its cassette's frozen `scenario.assert` — **re-measured 2026-08-20: still 2 lanes, down from 13** (the free `--assert-from --write` remedy was applied to the rest), but **both key lists grew by `artifact_text`**, added in `d9297dc` after the last write-back — so the divergence is not static and a stable lane COUNT does not mean a stable key SET. `market-sizing-smoke` (`artifact_text`, `gate_answer_count_min`, `gate_answers_delivered`, `present_files_called` authored but never evaluated) and `cap-table-acquisition` (`artifact_text`, `gate_answer_count_min`; its write-back REFUSES on answer drift, so only a re-record clears it). **Re-derive rather than trusting either number** — the historical table below is kept because the MECHANISM it teaches is permanent, not because the counts are current:

| direction | key | lanes |
|---|---|---|
| authored in the repo, **never evaluated** in CI | `gate_answer_count_min` | **12** |
| " | `gate_answers_delivered` | 10 |
| " | `present_files_called` | 1 (`market-sizing-smoke`) |
| **deleted** from the repo, **still evaluated** in CI | `gate_answers_delivered` | 1 (`cap-table-lane3-freeform`) |

That first row is the quantified form of the vacuous-gate hole this file discusses under `lint`: `gate_answer_count_min` is authored on 12 lanes and evaluated on **zero**. The last row is the mirror hazard and the less obvious one — deleting a wrong assert does not stop CI running it either, so lane3 still asserts in CI the very gate its own header explains the skill correctly never raises.

**THE REMEDY IS FREE BUT NOT SOUND — read this before using it again (added 2026-08-20, verified at
upstream source).** `--assert-from --write` has exactly one drift protection, the verdict gate
(`writeReassertedAssertBlock`, `src/run/cassette.ts:4092`), and **`--allow-failing` skips it** with no
staleness re-check anywhere downstream. You reach for `--allow-failing` *because* the asserts are
failing — that is why you are re-asserting — so **the flag added for the expected failure silently
disables the protection the forced drift gate exists to provide.** Measured: **11 of 11 write-back
lanes show drift today**, so every block `10396cb` persisted was validated against a drifted recording.
What that commit actually froze is two keys — `gate_answer_count_min` (10 lanes) and
`gate_answers_delivered` (9) — which now pass against **pre-authorization-change** `controlOut`. **Do
not cite those greens as evidence about current gate handling**; `deck-review-gate-stop` (recorded
fresh at 1.23.0) is the evidence. The 11 lanes went from *authored-but-never-evaluated* (CI silent) to
*evaluated-against-stale-events* (CI green), and for a regression guard **green-against-old-events is
worse than silence, because silence prompts a re-record and green does not.** A full re-record clears
it. **Not the same as "the block is meaningless":** the M1 evaluability guard (`:4081-4089`) still
refuses keys that would freeze as silent no-ops and is NOT skipped by `--allow-failing`, so the written
asserts do evaluate — they just evaluate against the wrong events. Upstream documents this at the flag
as of the unreleased `--help`. Full exchange: cowork-harness#118.

**The remedy is FREE, and an earlier version of this note got that wrong — do not re-derive the pessimistic version.** It claimed editing an `assert:` block "buys nothing until a re-record", which would make the 13 lanes above a ~$60 re-record backlog. They are not. `replay <cassette> --assert-from <scenario.yaml> --write --allow-failing` rewrites the frozen block in place, no paid run. Measured 2026-08-15 on a scratch copy of `market-sizing-smoke`: frozen asserts **16 → 19** (`present_files_called`, `gate_answer_count_min`, `gate_answers_delivered` all now present), `environment.harnessVersion` still `1.12.0` (nothing re-recorded), and plain `replay` afterwards correctly **FAILS** on `present_files_called`.

Two limits, both measured across the 13 divergent lanes:

- **`--assert-from` hard-fails on recording-shaping drift**, so the write-back is unavailable where the recording no longer corresponds to the scenario. **Re-measured 2026-08-20 across the then-22 cassettes (corpus is 10 as of 2026-08-24 — re-derive): TWO refuse outright (rc=2), not one** — `cap-table-acquisition` (*"answers drifted from the recording"*) and `deck-review-smoke` (*"prompt drifted"*). Both need a real re-record. The older "12 of 13 accept it; exactly one refuses" was scoped to the then-divergent lanes and reads as a corpus-wide count, which it never was; `deck-review-smoke` refuses for a different reason (prompt, not answers) and was outside that set. **Re-derive, do not inherit** — a loop of `replay <cassette> --reassert` checking for rc=2.
- **Writing the block back turns a green lane red** wherever the guard genuinely fails, which is the honest state but is a decision, not a free win. Sequence it with the fix, not before it.

And **a green CI replay is evidence about the *recorded* scenario**: read the frozen `scenario.assert` array out of the cassette before concluding a guard is live. The one-liner that produces the table above is a `json.load(cassette)["scenario"]["assert"]` vs `yaml.safe_load(scenario)["assert"]` key-set diff — cheap enough to re-run after any `assert:` edit.

**Do NOT generalize this into "never record a scenario whose asserts are not yet written."** That rule was stated here and is wrong in the one place it was aimed at. `deck-review-numeric-chain` is not "not yet recorded" — it is in `test_cowork_cassette_replay.py`'s `_NO_CASSETTE_ALLOWLIST` and must **never** be recorded: most of what it verifies is PROSE, and *"a cassette freezes one past agent's behaviour and re-asserts it, which is the opposite of what this lane is for; it already found one defect (an invented `kind` value) that a frozen recording would have preserved rather than surfaced."* Writing its asserts unlocks no recording, because no recording is wanted. Its missing case-asserts are a real and separate defect in a LIVE lane — see the numeric-chain note — and gate nothing about tagging.

**DISCHARGED — do not re-record for this reason.** This note used to say `market-sizing-remote-lane` had frozen the spurious `undelivered_deliverables` warn that 1.17.0 fixes, and needed a targeted re-record. That re-record happened: the committed cassette is `harnessVersion: 1.17.0`, `cassetteVersion: 11`, and contains **zero** occurrences of `undelivered_deliverables` (measured 2026-08-06). The stale "the committed cassette is `harnessVersion: 1.16.0` … re-record this scenario" note still sits in `cowork-tests/scenarios/market-sizing-remote-lane.yaml` around lines 40-41 and 60-61 and is likewise spent — a reader who trusts it will pay for a re-record that is already done.
0.5. **Run the gates `pytest` does not.** A green `uv run pytest` is NOT a green CI. Two separate
   gates have to pass before you tag, and neither is reachable from the test suite:
   - **mypy over all SEVEN directories** — the six `skills/*/scripts/` dirs **and
     `founder-skills/tests/`** (`ci.yml:33`; it is easy to miss by reading only the first few
     `- run:` lines). **The steps run under `-e`, so the first failure MASKS every later one**:
     clearing one error does not turn the job green, it advances it to the next failing step. v0.7.0
     burned two tags on exactly this — a `verify_positioning.py` shadowed-variable error hid 8 errors
     in `tests/`.
   - **`uv run ruff format --check .` and `uv run ruff check .`**.
   Run all of them, then bump. A retag is cheap (step 6 documents it) but each one costs a full
   paid e2e run.
1. Bump versions in `pyproject.toml` and `founder-skills/.claude-plugin/plugin.json` (must match)
2. Update `CHANGELOG.md` — and **read the diffs, not the commit messages**. The v0.7.0 pass found a
   duplicated entry, four script filenames in user-facing text (0.6.0 names zero `.py` to users), and
   three internal war stories. Match the format the previous release established (titled release +
   `### Highlights`, then Added / Changed / Fixed) rather than dumping bullets under `Fixed`.
3. `git commit -m "release: vX.Y.Z"`
4. `git push`
5. `git tag vX.Y.Z && git push --tags`
6. **Wait for `deck-review-e2e-smoke` green** in the GitHub Actions UI
   - Tag failure: `git tag -d vX.Y.Z && git push origin :refs/tags/vX.Y.Z`, fix, retag — no user impact yet (no Release exists, so nothing advertises the tag)
   - LLM-variance flake: re-run the job from the Actions UI (free retry, same SHA)
7. **The GitHub Release is now created FOR you — do not run `gh release create` by hand.**
   `publish-release` in `skill-quality.yml` fires on a tag PUSH (and only a push — a
   `workflow_dispatch` on a tag ref is excluded, or dispatching the rehearsal would publish), after
   the paid gate is green. It builds the notes and the title from `CHANGELOG.md` via
   `.github/scripts/changelog-notes.py`, which emits exactly `vX.Y.Z — <title>` to match the
   releases published by hand before it existed.

   **Running it manually now races the workflow**; whichever loses reds on "release already exists"
   (there is no `--clobber` and no existence check). If you need to publish by hand — the automation
   failed, or you are backfilling an old tag — this is the command it replaces:

   ```bash
   # notes = that version's CHANGELOG section; title = the section's own "— <title>" text
   gh release create vX.Y.Z --verify-tag --latest \
     --title "vX.Y.Z — <changelog title>" -F <(python3 .github/scripts/changelog-notes.py vX.Y.Z)
   ```

   **Rehearse the notes without tagging** (free, publishes nothing):
   `gh workflow run skill-quality.yml -f verify_release_notes_for=vX.Y.Z`.

   A **tag** and a **Release** are different objects: a Release is created only by `gh release create`
   or the web UI. Because this step was never written down, **four tags shipped with no Release**
   (v0.3.1, v0.6.0, v0.7.0, v0.7.1) and the repo's "Latest" badge sat on **v0.4.7 for two months** while
   the project kept shipping — a public repo advertising itself as stale on the day it released.
   Backfilled 2026-08-07; v0.3.1 deliberately left alone. Nothing was broken by the omission (users
   install from the marketplace clone tracking `main`, so `plugin.json#version` there is what they get)
   — the cost is entirely perception, which is why nothing failed and it drifted for four releases.

   **The release ENDS here.** `sync-test-repo.sh` is deliberately NOT a release step — see below.

   Two mechanics worth knowing: `--verify-tag` aborts if the tag isn't on the remote (catches a
   forgotten `git push --tags`), and **"Latest" is computed, not chronological** — when backfilling
   several, create them oldest-first with `--latest=false` and pass `--latest` only on the newest, or
   the badge lands on whichever GitHub decides. Reversible: a Release can be deleted without touching
   the tag.

**`sync-test-repo.sh` RUNS ONLY WHEN EXPLICITLY ASKED FOR. It is not part of shipping, and "ship vX.Y.Z" is not a request for it.** It is a local, untracked TESTING convenience: it rsyncs `founder-skills/` into a SEPARATE and PUBLIC repo (`yaniv-golan/founderskills-test`) and pushes, so a build can be exercised in Cowork by hand. Nothing in the release depends on it and no user is waiting on it — users install from the marketplace clone that tracks `main`, so `plugin.json#version` on `main` is what they actually pick up (see VERSIONING.md).

It used to be numbered step 7 of the release, which read as "do this to finish shipping" and is wrong twice over: it publishes the working tree — not the tag — into a second public history, and it is a push to a repo the release process has no business touching unattended. If you do run it, run it only after the release gate is green: syncing a broken build means the manual test pass exercises a build you would never ship.

**Model-tier acceptance:** when adopting or recommending a new model tier, run the cap-table reliability bench (`evals/cap-table/run_reliability_bench.py`, see its `README.md`) and record the per-tier correctness; Sonnet 4.6 is the support floor. (The bench lives at repo-root `evals/` — outside the distributed `founder-skills/` plugin — so it isn't shipped to users, mounted into cowork runs, or folded into the cassette staleness hash.)

**Already-distributed retag pitfall:** if you had separately run `sync-test-repo.sh` before noticing the bug, **bump to the next patch version instead of retagging** — Cowork caches by `plugin.json#version`, so retagging the same version will not refresh user caches (`cpd refresh ... --force-fetch -y` is the manual recovery, not always coordinatable across users).

### When to manually dispatch e2e on a PR

Per-PR e2e is off by default. Manually dispatch (`gh workflow run skill-quality.yml --ref <pr-branch>`) when the PR touches architectural surface that contract tests don't fully cover:

- `founder-skills/skills/*/SKILL.md` (frontmatter or trigger phrases)
- `founder-skills/agents/*.md` (tool declarations, model, frontmatter)
- `founder-skills/.claude-plugin/plugin.json`
- `founder-skills/scripts/session-setup.sh` (mutates `CLAUDE_ENV_FILE`; downstream skills depend on it)
- `founder-skills/skills/*/scripts/compose_report.py`, **but only when the change reaches the payload builder** — `_emit_coaching_payload` in five skills, `build_coaching_payload` in cap-table (which also runs `_assert_coaching_payload_privacy_clean` over the result; grep for the name rather than assuming, this differs per skill). That function IS the `coaching_payload` contract. `test_compose_invariants.py` checks its *shape* against synthetic fixtures; only e2e exercises the thing that shape exists for, namely a sub-agent reading the payload and writing usable commentary from it. **The check:** does the diff touch the payload builder or anything in its call graph? If yes, dispatch. If the change only alters how a section renders into `report.md`/`report.json`, the contract tests are sufficient and e2e buys nothing.
  This bullet used to name the whole file, which over-triggered: a rendering-only fix would read as needing a $10 paid run it cannot possibly exercise. Two such commits landed under the narrowed reading — a `-1` rank sentinel reaching founders, and a moat-radar caption — both rendering-only, both covered by contract tests, neither dispatched. **Watch the shared-helper case**: `report.md` prose and the payload can call the same helper, and a change there does reach the contract even though the diff looks like rendering. That is exactly why the trigger is the call graph and not the file.
- any of the three `founder-skills/tests/test_e2e_*.py` lanes, or `tests/_e2e_harness.py` (the SDK invocation itself)
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
