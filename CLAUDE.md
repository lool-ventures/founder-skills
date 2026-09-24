# CLAUDE.md

> Distilled 2026-09-21 (`002fb97..91fb4d9`), from ~164 KB to ~94 KB. What came out was the
> measurement narrative behind the rules that remain, plus the harness adoption log:
> `git show d99aa0d:CLAUDE.md`. Read it when a rule here states a conclusion and you need to
> know what was measured to reach it — several were learned by a run that cost money.

## Repository Structure

- `founder-skills/` — Claude Code plugin (SDK/CLI-based)
- `founder-skills/.claude-plugin/plugin.json` — Plugin manifest
- `founder-skills/commands/feedback.md` — `/founder-skills:feedback` slash command (drafts a bug/idea/help/win report, hands the user a prefilled GitHub/`mailto:` link to submit; transmits nothing automatically)
- `founder-skills/skills/market-sizing/` — Market sizing skill with scripts and references
- `founder-skills/skills/deck-review/` — Deck review skill with scripts and references
- `founder-skills/agents/market-sizing.md` — Market sizing agent definition
- `founder-skills/agents/market-sizing-redteam.md` — RED_TEAM agent: attacks a finished sizing the way a skeptical investor would, dispatched at exactly one step after the math and validation are complete. **The fleet has SEVEN agents, not six** — and market-sizing pinning two is why the critique-corpus agent term is a UNION rather than the scalar `agents/<skill>.md`.
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
- `founder-skills/scripts/_founder_text.py` — Shared founder-facing text policy: four token types, three behaviours (humanize private enums + field names; keep stable identifiers and diagnostic codes verbatim). Every `compose_report.py` substitutes then scans with it; `insert_coaching.py` scans the commentary. `identifier_values()` is cap-table-only — its docstring says why.
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
- `founder-skills/tests/mutation_corpus.py` + `test_mutation_corpus.py` — Curated mutant corpus over cap-table's math producers: `MUST_KILL` / `KNOWN_SURVIVORS`, both SHRINK-ONLY; every kill names the test that must notice (`killed_by`, measured never guessed — a kill from anywhere else fails); a no-op control must stay PASSING. The registry lives in the non-`test_*` module deliberately — its docstring says why.
- `founder-skills/tests/test_release_gating.py` — The release chain asserted: every job in `publish-release`'s TRANSITIVE `needs` closure must run on a tag push, because in Actions a skipped dependency SKIPS the dependent (four tags once shipped with no Release). Frozen `if:` strings + a simulated-tag-push evaluator that raises on an unknown context property. Wiring only, never that a job passes. The chain is unexercised: v0.10.0 predates the `publish-release` job.
- `founder-skills/tests/cowork_async_subagent_filter.py` — Cowork sub-agent tool-name compatibility helper (skill-quality CI; v0.4.0-regression detector)
- `cowork-tests/leak_scan.py` — Founder-facing "internal plumbing" leak detector: nine syntactic classes plus the semantic `plumbing_verb`. Point it at a cassette FILE or `events.jsonl`; a directory glob finds only `*.json` and reports a silent false-clean.
- `founder-skills/tests/test_founder_facing_leaks.py` — Ratchet over `leak_scan.py` across the committed cassettes. Gates "no NEW leaks beyond `BASELINE`", not zero; ratchet the constant DOWN after a re-record (it was raised once, deliberately, and the file's comment states the obligation to ratchet back). A green does not mean clean narration: what still passes is internal vocabulary with no plumbing verb ("canonical artifacts", "schema-drift warning", bare `STOP`/`BLOCKED`, "Gate 1 passes"). Do not fix that by enumerating words — extending the classes was tried and does NOT red the suite, but an enumerated blocklist is unwinnable by the detector's own design note.
- `founder-skills/tests/compose_invocations.py` — Per-skill compose-script invocation registry (skill-quality CI)
- `founder-skills/tests/test_cowork_async_subagent_filter.py` — Helper unit tests
- `founder-skills/tests/test_cowork_invariants.py` — Per-agent persistence + dangerous-tool declaration invariants
- `founder-skills/tests/test_cowork_harness_floors.py` — Drift guards for the cowork-harness version surface: the per-site registry splitting CI SELECTORS (pinned exactly, `3.7.0`) from FLOORS (recording `>=3.6.0`, replay `^2.1.0`) — three postures, deliberately different, `uses:`-vs-`version:` major agreement (the action ref and the CLI move independently), and the derived cassette-format facts prose keeps restating wrongly. Every extraction asserts its own pattern matched, so a rotted regex reds instead of greening.
- `founder-skills/tests/test_skill_orchestration.py` — Per-SKILL.md frontmatter + sub-agent-cue-then-bash regression detector
- `founder-skills/tests/test_compose_invariants.py` — `coaching_payload` shape + `STALE_ARTIFACT` regression
- `founder-skills/tests/coaching_payload_keys.py` + `test_coaching_payload_key_coverage.py` — The coach's key list DERIVED from each `compose_report.py` by static AST (every unresolvable construct raises), asserted against agent bodies only. A lower bound in the addition direction — it does not replace `test_compose_invariants.py`'s `_COACHING_COVERAGE_KEYS` and is blind to SHAPE; `test_high_severity_warning_shape_matches_the_producer` covers that axis.
- `founder-skills/tests/test_cap_table_warning_labels.py` — cap-table may not hand the coach a raw `E_` / `W_` code under a founder-facing name. Asserts the humanizer's OUTPUT SHAPE over every code literal (not per-code coverage, which rots and gets deleted), and SEEDS a blocker + solver warning because the fixture carries none.
- `founder-skills/tests/test_insert_coaching.py` — `insert_coaching.py` suite (6-state idempotency matrix, run_id parity, single-pass write-back, adversarial commentary)
- `founder-skills/tests/test_check_handoff.py` — `check_handoff.py` suite (typed exit paths 0/3/4/5/6, adversarial file states, tolerant receipt extraction)
- `founder-skills/tests/test_merge_json.py` — `merge_json.py` suite (merge order, --set overrides, error paths)
- `founder-skills/tests/test_resolve_artifacts_root.py` — Artifacts-root resolver suite (Cowork mount signatures + agent-namespace root)
- `founder-skills/tests/dead_payload.py` — Shared analyzer for embedded-but-unread JS payload keys with three verdicts: `read`, `unread`, `unverifiable` (computed-name access — neither blanket consumption nor death).
- `founder-skills/tests/test_dead_payload.py` — Analyzer unit tests + all four embedders (three `explore.py` + `review_inputs.py`). Pins which payload objects are dynamic, so a generator switching to computed access cannot quietly reduce coverage.
- `founder-skills/tests/test_dispatch_schema_drift.py` — A dispatch template may not instruct a field nothing consumes; reads every fenced block on both prompt surfaces (json-only sees about a third). Cannot see shape-level drift (`x_axis_rationale` is both the obsolete authoring shape and a legitimate internal one), so a direct axis-shape assertion covers that.
- `founder-skills/tests/test_html_founder_text.py` — Fleet ratchet: no internal token in founder-visible text of any generated HTML. Text nodes only; attribute values and script bodies are not founder-facing prose.
- `founder-skills/tests/test_compose_invariants.py` also scans **every delivered markdown, not just `report.md`** via `_EXTRA_DELIVERABLES` (cap-table's counsel packet today), seeding one counsel item because the fixture flags none — without it the packet is boilerplate and passes with the leak present.
- `founder-skills/tests/test_delivery_coverage.py` — The fleet's delivery-defect coverage map, asserted rather than described; records the known "computed, not rendered" gap (gated only in competitive-positioning and financial-model-review) and one Gate-1 render contract as explicitly WEAK.
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
- **`_handover_check.py`** — The hand-over containment rule, in ONE place: the e2e lane and the Stop hook both ask whether the founder's message carries the printed message whole, and a rule with two copies drifts (the lane greens on one reading while the hook blocks on another). Link targets are dropped and whitespace squashed before comparing — the two runtimes render different links for the same file, and a re-typed indent is not a change. Containment, not digit-absence: a message is also wrong when it DELETES a printed line, which no digit check can see.
- **`stop_handover_check.py`** — The Stop hook's body (see **Hooks**); loads `_handover_check.py` by path, since plugin-root `scripts/` is not a package.

## Market Sizing Scripts

- **`market_sizing.py`** — TAM/SAM/SOM calculator (top-down, bottom-up, or both). Also the only place FX happens: a money input (`industry_total` / `arpu` — the only two) may declare its own source currency via `<field>_currency`, and conversion uses a rate the CALLER supplies (`--fx-rate SRC:TGT=RATE`, `--fx-as-of`, `--fx-source`). A declared foreign currency with **no** rate is a hard error, never a guess, and a rate is never inferred by inverting another pair — the sub-agent that produces these figures has no network, so FX done upstream could only come from model memory. Conversions are recorded in `sizing.json`'s `fx` block and disclosed to the founder in both `report.md` and `report.html`; the recorded `converted_value` IS the number the math consumed, which is what lets `compose_report.py` compare a founder-stated figure across the conversion.
- **`sensitivity.py`** — Stress-test assumptions with low/base/high ranges and confidence-based auto-widening. **RECONCILES rather than defers:** a range's own `confidence` used to be absolute, which let a caller tag a medium-confidence parameter `sourced` and escape widening entirely; the stricter of the declared and cross-referenced tiers now wins (it can only ever WIDEN). `confidence_source` on each scenario records where the tier came from — `range` / `validation` / `reconciled` / `default` — because "no widening happened" and "no widening was called for" were previously the same artifact.
- **`checklist.py`** — Validates 22-item self-check with pass/fail per item
- **`compose_report.py`** — Assembles report from artifacts, validates cross-artifact consistency
- **`closing_message.py`** — Prints the founder-facing hand-over message from `report.json`, and writes the same text to `handover.txt` beside the report for the check that runs after. It carries the report's own `verdict` paragraph — the words the page opens with — because a message that asked the founder to go read the verdict was measured 0/2 at hostloop: the model dropped the pointer and wrote the verdict itself, with its own rounding. Composing this message in chat is what it replaces.
- **`_upload_names.py`** — The founder's filenames as uploaded: the cloud-lane `<8-hex>-` upload prefix is stripped at RENDER time only (compose's final markdown + `verdict`, and visualize's adversarial section + verdict, where it runs BEFORE `_esc` or an escaped `'`/`&` stops matching). It is not renamed at the source, because `red_team.py` opens `<uploads-dir>/<file>` and the OCR sidecars key on it. The coaching payload keeps the raw names, and `test_upload_names.py` pins that by whole-payload equality. Stripping needs EVERY known name to be prefixed; a batch of one needs an a-f letter, since `20240115-deck.pdf` is a date; a collision keeps the prefix. The root fix is to strip while mirroring in Step 6c, but that is a SKILL.md change and cannot be exercised on the lane it targets.
- **`dispatch_prompt.py`** — Generates the RED_TEAM sub-agent dispatch from identifiers on disk: the model supplies paths and ids, every sentence comes from this file, and the e2e lane regenerates the prompt and asserts the dispatched one is byte-identical. The founder's documents are listed FIRST, before any of our artifacts — a reader who opens the analysis's reading of the deck before the deck inherits its frame, and the step exists to escape the constructor's framing.
- **`ocr_uploads.py`** — Writes a machine-read text sidecar per page of every image-only upload, so a red-team citation to a scanned page can be checked against text rather than re-read by vision. Binary-only (`pdftoppm` + `tesseract`, the cap-table pattern) with NO Python OCR dependency: when either binary is absent it exits 0 with `ocr_available: false` and writes only its receipt (no sidecars), every document citation stays `quote_verified: null`, and that is disclosed. A missing OCR binary must never block a run. It writes `<out>/receipt.json` per document as it goes, so a re-run after a timeout RESUMES; `dispatch_prompt.py` refuses (exit 2) while any image-only PDF is not covered by the receipt — an `ocr_available: false` receipt counts as covered.
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
- **`_evidence_multiple.py`** — Detects a "times" comparison an assessor's own cited figures contradict, and appends the founder-facing caveat. A sibling module because FOUR surfaces render the same assessor-written evidence and none sees the others' output (`compose_report.py` → `report.md` and the coaching payload, `visualize.py` → `report.html`, `explore.py` → `explorer.html`); the first cut lived in compose and left both HTML pages showing the unsupported number plain. Calibration is a measured false-positive rate, not a judgement: `founder-skills/tests/evidence_multiple_corpus.py` re-runs it over kept run dirs and **imports this module** rather than restating the grammar — a tool with its own copy reports a healthy rate for a detector that has stopped working, which is how an earlier attempt shipped a pattern containing a literal backspace that matched nothing. Baseline 2026-09-19: 2,854 real findings, 39 stating a comparison, 1 fire (the defect). **Re-run it as reviews accumulate**; a fire count above the number of real defects means the check is miscalibrated.
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

Rules live at **3.7.0**. Each was learned by measurement; the measurements and the version-by-version
history are archived locally beside the per-release adoption plans.

**Invoking**
- `critique` takes a POSITIONAL skill folder. Always pass `--out <skill>.json --output-format json`: `--out` alone writes TEXT, and `json.load` then fails with `Expecting value: line 1 column 1`, which reads as a corrupt report (1.24.0 warns at parse time). The index cannot attribute a critique (records `command: "skill"`, no `skill` field, `session.json` has neither `skill` nor `prompt`), so `--out` is the only provenance. `--label` lands on turn 1 only, deliberately.
- Tier prerequisites: `container` / `hostloop` need a token in the environment or in `.env` (`CLAUDE_CODE_OAUTH_TOKEN`, or `ANTHROPIC_API_KEY`) — ours lives in `cowork-tests/.env`, and `.env` is discovered from CWD only, so run from `cowork-tests/` or `doctor` reports a misleading Keychain error. The evaluator passes need `claude` on PATH (`COWORK_HARNESS_CLAUDE_BIN` overrides). Upstream docs said the opposite until 1.19.0.
- Use `--fidelity cowork` (resolved once, before either turn spawns, via the pinned baseline's loop gate; echoed `[loop] cowork → <tier>`, reported as `requestedFidelity`). The default `container` is not the tier the cassettes record at. `microvm` / `protocol` refused; `chat` refuses `cowork`. `--dotenv`: the child CLI loads that file before deciding, so a `CLAUDE_FORCE_HOST_LOOP` in `./.env` is read during resolution.
- Do NOT swap `--evaluator-model` on a fleet sweep. For document-analysis skills — every skill here — the task turn is ~61% of spend and the evaluator ~30%, so the saving is a third of its advertised size and it trades away the injection-resistance property verified for the default evaluator only. The levers are `--model` and probe scope; the default task-turn timeout is 30 min, so `--timeout` is no longer needed for a fan-out skill. The report's `cost:` line prints the evaluator share.
- `--ablate-skill` is ONE arm; with `--repeat N` it yields N ablated runs and zero treatment runs — run again without the flag. Rollups label arms (`[ABLATED — control arm]`, `[MIXED ARMS: k/n ablated]`); `evals/cap-table/run_reliability_bench.py` parses `rollups[]` and reads these defensively.
- `git add` untracked skill files first. Untracked `references/**` or the agent body → EXCLUDED and named in `evidenceBudget.corpusExcluded` — the CORRECT outcome (evaluator sees what the agent sees), and a "the skill never explains X" finding against it is properly grounded. Untracked `SKILL.md` → `skillMdStatus: "untracked"`, content withheld, forces `not-adjudicable`. A plugin-root reference shows up as `corpusOmitted[].alsoUntracked` — three-state, absent ≠ false.

**Reading a report**
- Budget from `report.costUsd.totalUsd`; `index.jsonl` omits the evaluator passes. Each critique also writes a roll-up row (`critiqueTotalUsd`), so `stats` totals are exact and label-filtered totals are not short (`unpricedRuns` says when a total is a floor). `costUsd` carries a per-pass `{input, output, cacheRead}` split. Whole-content packaging costs +5–18% per critique.
- Items carry `idea` / `recommendedAction` / `evidence` / `source`. There is no `title`.
- A `scripts/`-grounded `not-adjudicable` means "the evaluator could not SEE the code", not "the claim is false" — `scripts/` is outside the corpus by design. If a script's contract matters to how the skill is used, state it in SKILL.md or a `references/` file. Bites deck-review hardest: its gate contract lives in `gate_state.py`.
- `noSkillFilesRead` is observational. ic-sim trips it on a correct run because `evaluation-criteria.md` / `partner-archetypes.md` are inlined into `agents/ic-sim.md` (`SKILL.md:73-75`); do not add reads to silence it. Since 2.5.0 it keys on the wide `unionReferenceAccesses` (Read ∪ Grep ∪ a Bash command naming the path, main ∪ sub-agents) with a third state `referenceAccessUnobservable` that must never be read as "none". A `$VAR`-built path is an accepted detector miss, and our SKILL.mds use `"$SCRIPTS/…"` — one literal path flips the signal. The matching `reference_read` / `no_observed_reference_access` scenario keys evaluate on replay but are NOT adopted (freezing one raises the replay floor to 2.5.0).
- One critique is a sample (upstream measured 78 vs 50 extracted figures across two runs of one bug). Reproduce ≥ 2 runs. A fleet-consistency defect is out of scope for any single critique by construction; that is what the drift tests are for.
- `result.json`'s `models` can contain `<synthetic>` (a locally fabricated turn, recorded verbatim). Drop `<…>` entries before using it as provenance. After a re-record, check `provenance.model` is UNIFORM across the corpus — a corpus silently spanning two models is a real hazard (tier changes correctness) and nothing else checks it.
- A green run prints `·`-prefixed warn signals in its footer (`undelivered_deliverables`, `ended_with_question`, `scan_unavailable`, `exec_infra_error`, `prompt_asset_missing`). Read it.
- `[provenance] model=… skill=offered,invoked ablated=…` rides every verdict and `results[].provenance`. `skill=…invoked` means the Skill channel was used, NOT that the skill under test ran — `skill_triggered` is the identity assert. `offered,unknown` / `unknown` mean evidence unavailable, never "no". `--compact` / `--demo` suppress it, and `[status]`.
- Keep pre-upgrade reports: per-item verdicts are not comparable across corpus-packaging changes, but per-skill `not-adjudicable` counts on identical prompts are, paired with the `citationResolved:false` rate.

**Corpus size (`evidenceBudget`)**
- Four classes count against a 512 KiB ceiling: SKILL.md + every file under the skill's own `references/` (ANY extension — schemas and rule packs count) + every agent the skill resolves (a UNION: `agents/<skill>.md`, every pinned `subagent_type` literal, every agent whose `name:` equals the skill, and the transitive closure of pins inside those bodies — market-sizing pins two, which is why the term is a union and the fleet has SEVEN agents) + every plugin-root `references/` file the skill's own text points at. Over the ceiling, content is cut before grading and named in `evidenceBudget.corpusCuts` (`skillMdTruncated` is gone).
- A data file scripts read by path belongs in `data/`, not `references/` (`cap-table-rules.json` moved 2026-08-01). Only evaluator-citable evidence is corpus. Relocating prose between SKILL.md and `references/` is corpus-neutral.
- Measure with `tests/_critique_corpus.py` (`_corpus_bytes` in `test_skill_contract.py`) or `evidenceBudget.corpusBytes` on a real report. `lint-skill` (>=3.7.0 — earlier versions omit a whole class) prints the number only at ≥ 80% of the ceiling, so its silence is not a measurement. `test_skill_contract.py` guards the ceiling and cap-table's `> 10,000 B` margin; the margin figure has rotted in prose repeatedly — derive it.

**Scenario and cassette tooling**
- Everything the harness prints goes to STDERR; stdout is empty. Never poll with `status | grep` (exits immediately and silently) and never "fix" that with `2>&1`. Use `status <dir> --follow` or `status <dir> --output-format json`; long runs also heartbeat on stderr (`COWORK_HARNESS_NO_HEARTBEAT` / `_HEARTBEAT_MS`). `[status] <outDir>` is withheld under `--compact`/`--demo` but `status.json` is written regardless. Do not watch the outputs dir for artifacts.
- `lint` is LENIENT; the loader is STRICT. Validate ONE scenario with `record scenarios/<s>.yaml --dry-run --out /tmp/probe.cassette.json` — `--out` is mandatory, because the bare form also pre-checks the cassette DESTINATION and refuses a valid scenario with no committed cassette (exit 2 at ≤ 3.1.0, 1 at ≥ 3.2.0; `fidelity: container` is exempt). Never spend `--allow-host-inventory-fixture` on a load check. For the WHOLE corpus use the DIRECTORY arm, `record scenarios/ --dry-run --quiet` (what CI runs): 0 = all load and under cap; 1 = a scenario did not LOAD (`✗ broken:` on stderr) or a path-independent refusal (prompt policy, assert contradiction, duplicate target); 2 = the budget gate refused; some-broken + over-cap = 2 with the broken line still printed; ALL-broken + over-cap = 1 (nothing loaded, so the budget gate never ran). Anything wrapping it needs that 1-vs-2 split (`rerecord.sh` has it). Non-recursive; a file with no `prompt:` key is `· skipped:`, not broken.
- `lint --strict` alone exits 1 on INFO-only findings; CI pairs it with `--min-severity WARN`. Read the exit code, not the summary line. `strict: true` belongs on the lint step only — on replay steps it also fails on cassette staleness, which is WARN-only by design.
- `lint`'s vacuous-gate fix line is wrong for a scenario DESIGNED to fire no gates (`cap-table-lane3-freeform`): the remedy there is to drop `gate_answers_delivered`, not add a companion.
- NONE of `lint`, the bundled `scenario.py lint`, or `record --dry-run` catches a `tool_not_called` / `subagent_tool_absent` naming a tool the tier does not serve (their tier table has no `cowork` row; the refusal lives in `executeScenario`). At hostloop the shell is `mcp__workspace__bash`, so `'Bash'` there is vacuous. Our own Context A agents declare no shell tool of any name, so the corrected assert is unviolatable for agents we wrote; its live value is a dispatch we did NOT write — a `Task` with no `subagent_type` falls back to `general-purpose` with a wildcard tool surface including workspace bash. Do not delete it as vacuous. `test_cowork_invariants.py`'s per-agent tool declarations are the primary enforcement.
- After editing any `assert:` block: `replay cassettes/<s>.cassette.json --assert-from scenarios/<s>.yaml` — free, ~1 s, no Docker. It refuses on prompt drift, and that refusal means "re-record required". On every stale lane its exit 1 also carries a `skill-source drift (--fail-on-skill-drift)` line — read the per-assert lines, and never waive it with `--allow-failing`. `verify-run` is the kept-run-dir equivalent and fail-closes on a PARTIAL run.
- A recorded cassette is NOT relocatable (`scenario.session` / `scenarioSource` are directory-relative). Never rehearse on a `/tmp` copy — the copy manufactures `unverifiable-skill` / "skill dirs not resolvable" and hides the real finding.
- `semantic_matches` judges top-level `assistant_text` ONLY — no tool blocks, no sub-agent text (unless `include_subagent_text: true`). We use none; keep it that way. The key is `subagent_dispatched` (with "ed"; four upstream surfaces misspelled it). `present_files_called` is `z.literal(true)` / "at least one file", no per-file match — which is why `cowork-tests/delivery_check.py` exists. `subagent_declared_but_unused` is near-always vacuous (0 of 1091 real dispatches carry a declared tool list).
- `assertions --list` emits `{key, description}` — no replay class; read classes from `docs/scenario.md`.
- A/B a skill change with `stats <scenario> --group-by skill-hash --runs`; runs before and after an edit share a scenario dir and `stats` warns on `distinctSkillHashes`. Narrow with `--skill-hash <prefix>` or `--label`; `--since` breaks when two versions run on one day.

**Privacy gate**
- `privacy-allowlist.sh` defines a bash ARRAY, so `source` alone changes nothing: `source cowork-tests/privacy-allowlist.sh && cowork-harness verify-cassettes cowork-tests/cassettes "${ALLOW[@]}"`. Sourced-but-unexpanded reports thousands of findings and looks exactly like a broken allowlist. Every `--allow*` regex is FULL-MATCH inside the harness's own wrapping — `founder-skills:.*` clears a class, `^founder-skills:` clears zero. Over-tight fails safe; over-loose disarms a class silently. Re-count after any edit and confirm `canary/email-canary.cassette.json` still flags `[email]` — it is hand-authored, deliberately `cassetteVersion` 10, and is never re-recorded.
- Never pipe `verify-cassettes` to `tail` (deterministic `EAGAIN` crash replaces the verdict). Redirect to a file.
- The per-class header counts INFORMATIONAL classes; `findings by class: unscanned N` with exit 1 is staleness / scenario-drift, not PII. CI's privacy step passes `--skip-staleness --skip-scenario-drift` and exits 0. A `replaced-builtin` NOTE on `host-path-canary` is not a finding and not a reason to re-record.
- `host-inventory`: our own plugin's `agents[]` / `skills[]` entries are exempt because every recording declares `founder-skills` in `plugins[]` (1.19.0+; the built-in skill roster was fixed in 1.25.0 and extended for 3.6.0 — fix the roster, never allow). There is deliberately NO allow entry for them — a suppression that suppresses nothing invites misreading the gate. If a re-record reds this gate on our namespace, the cause is a missing `plugins[]` declaration, not a leak. The arrays live inside the `system` init frame in `events[]`, whose entries are JSON-ENCODED STRINGS — a walker that does not `json.loads` string leaves concludes the axis does not exist (and `scenario.skills` is a different, staleness-scoping key). The zero is structural (the axis targets `protocol`; we record at hostloop), confirmed non-vacuous by probe. This makes the CLI floor load-bearing: floor every consumer of `privacy-allowlist.sh` at `>=1.19.0` — though the **replay floor is `^2.1.0`, the RECORDING floor `>=3.6.0`, and the CI selectors are PINNED EXACTLY at `3.7.0`** (see Release Process).
- The predicates that would mean a REAL leak — `mcp_servers[].name`, `account.email` / `.organization` / `.subscriptionType`, a `mcp__<server>__…` tool naming a foreign server — return NONE across the corpus. Not covered: the command and plugin catalogs and command descriptions. A green is a backstop, not proof.

**`replay --mutate`**
- It SAMPLES — 10 per file, 50 total, per-file cap applied first — so `50/50 … CAUGHT BY NOTHING` is coverage thinness, not an assertion-failure rate, and the `(sampled N of M eligible …)` parenthetical's M is not the ratio's denominator. Aggregate over the JSON `mutation` object (`{sampled, eligible, truncatedBy, caps, uncaught}`), not stderr. Globs are anchored and case-sensitive against `outputs/…`-prefixed paths: `'**/handoff/**'`, never `'handoff/**'`; `'**/report.json'` cannot match a root-level `report.json`. Scoped to the delivered report it is exhaustive, not sampled: `--mutate-include '**/report.json' --mutate-max-per-file 500`. Reporting-only by design — a count ratchet over `report.json` would red on every legitimate re-record. `report.json` is committed body-less on `deck-review-smoke` and `ic-sim-contested`, so it is neither mutatable nor `artifact_json`-assertable there.

## Running Tests

```bash
uv run pytest                                       # all tests (e2e auto-skips without auth; cowork auto-skips without the harness CLI)
uv run pytest founder-skills/tests/ -v              # verbose
uv run pytest founder-skills/tests/ -v -m "not e2e and not mutation" # explicitly skip the paid + slow lanes
uv run pytest -m cowork                             # token-free cowork-harness cassette replay (needs `npm i -g cowork-harness@3.7.0` — exact, matching CI; no Docker/token)
uv run pytest -m mutation                           # curated mutant corpus (~3 min; deselected by default — see the WARNING below)
```

**`addopts` deselects `e2e` AND `mutation`, and a command-line `-m` OVERRIDES `addopts` rather than
adding to it.** So a bare `-m "not e2e"` silently RE-SELECTS the ~3-minute mutation corpus — and on a
working tree that is red for any unrelated reason it reports `THE NO-OP CONTROL FAILED`, which reads as
a break the contributor did not cause. Every explicit `-m` in this repo therefore says
`-m "not e2e and not mutation"`: `ci.yml`'s test job, `skill-quality.yml`'s contract-tests job,
`scripts/pre-tag.sh`, `CONTRIBUTING.md`, and the two invocations in this file. That list was wrong when
first written — it named three sites and this file itself disproved it six lines up. The mutation lane has its own `mutation-corpus` job (dispatch and tag only) and its own
preflight gate; both must pass `-m mutation`, since naming the file alone collects nothing and reports green.

**A skill's own test file is not what guards it.** `test_<skill>.py` covers the producers;
`test_<skill>_skill_contract.py` covers the SKILL.md / agent-body contracts, and there are
cross-cutting guards besides (`test_skill_contract.py` size ceilings, `test_cowork_invariants.py`
tool declarations, per-script suites like `test_backward_verifier.py`). Editing a SKILL.md or an
agent body and running only the matching `test_<skill>.py` reports green while the contract tests
fail. Run `-m "not e2e and not mutation"` before believing a skill change is done.

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
- **Stop** (`founder-skills/scripts/stop-handover-check.sh` → `stop_handover_check.py`): after the model's final turn, checks that the founder's message carries market-sizing's printed hand-over whole and adds nothing numeric; a `{"decision": "block", "reason": …}` reply sends the model back **once**. A block APPENDS — the faulted message stays on screen and the rewrite lands beneath it — so the reason dictates a follow-up the founder will read, not an internal note. Its lead (`CORRECTION_LEAD`) states provenance and which figure wins on a conflict, never that the message above was wrong: neither failure `_handover_check.py` reports establishes a wrong figure (a correct paraphrase fails containment too), and a production block once told a founder to disregard figures that were right. The wrapper is POSIX `sh` (it runs host-native on macOS at hostloop and under dash in the Cowork VM) and **fails open** when `python3` is absent: the hook enforces, the skill never depends on it. It fires at the end of EVERY turn in every session with the plugin enabled; any stop without a `closing_message.py` call since the last real user prompt exits 0 with no output, and any error exits 0 with one stderr line.
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

- **Skill re-attachment after auto-compaction has TWO budgets, and the second deletes silently.** Cite VALUES, never minified identifiers — every symbol rotates per release and one has collided destructively (`_On` meant 25,000 in one build and 5,000 in the next).
  **Cap 1 — 5,000 tokens per skill, and it is a CHARACTER cap**: the estimator is `Math.round(len/4)`, so `wc -m` measures the right unit with zero conversion error. The stored content is the `Base directory for this skill: <abs path>` prefix (101–240 chars, install-dependent) + the body with frontmatter STRIPPED; it truncates at ≥ 20,002 chars — the last safe length is **20,001**, and 19,900 is merely what survives (`slice(0,19900)` + a 100-char marker). All six of our SKILL.mds are far over, so every one truncates on every compaction, discarding 75–86% of its body — and compaction is ordinary (380 transcripts with `compact_boundary` on this machine), not rare. Truncation is head-preserving, so the base-directory line survives and a skill that OWNS A DIRECTORY is recoverable (measured 98% of truncated entries carry it). A single-file command has no recovery path at all: `commands/feedback.md` is 2,737 chars today and is the class to watch. Do NOT generalize this to "bundled/builtin skills have no base directory" — `bundled:verify` carries one; directory ownership predicts recoverability, the source prefix does not. Refinement: the predicate is directory DURABILITY — a plugin upgrade removes the version-stamped cache dir, so a session RESUMED after an upgrade holds a recovery path to a dead directory (path-death measured; the failing resume `Read` inferred, not observed). `skills[].path` is a source-qualified identifier (`plugin:cap-table`), not a location — recovery keyed on `path` fails, keyed on the content's first line succeeds; the registry's `skillPath` is renamed to `path` on the way out, so grepping transcripts for `skillPath` finds nothing.
  **Cap 2 — 25,000 tokens combined**, over post-truncation sizes (each of ours contributes exactly 5,000), most-recently-invoked first, per-agent: over budget (strict `>`), the least-recently-used skill's content is set to `""` with no marker — a "re-read if something looks missing" instruction structurally cannot fire for zeroing. Six co-invoked = one zeroed. A skill still visible in a retained attachment is skipped and consumes no budget. Sub-agent fan-out relieves the main thread.
  **Front-loading a "survival core" is WITHDRAWN** — do not re-propose the additive form: the window is fixed-size, so a prepended core evicts exactly as much from the tail (measured: it would have evicted the `STAGING_DIR` invariants it was written to protect). Reordering is not invisible to tests (`test_ic_sim_skill_contract.py` asserts step order), and the subtractive form has no cheap duplicate to harvest — the per-skill `## Skill Execution Model` sections overlap the shared reference by only 20.6–28.0%. Any front-loading or reordering attempt needs an e2e A/B (~$10) — contract tests cannot see behavioural change — and a justified `test_skill_md_does_not_grow` ceiling raise. Relocating prose to `references/` (target ≤ 20,001 chars of rendered prompt) is exempt from both caps but lands in the separate post-compaction file-restore budget: the 5 most recently read files, 5,000 tokens each, per-agent (a plain dispatch starts empty, `context: fork` copies the parent's — we use no `fork`; re-check if one is added). Neither conflicts with the retired "never move prose into `references/`" rule, which was about the 512 KiB critique corpus. Full derivation: `docs/internal/2026-08-28-skill-frontloading-plan.md` rev 2 and `docs/internal/2026-08-28-skill-compaction-budget-and-frontloading-plan.md`.
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

0. **Refresh cowork cassettes** (release cadence, paid, local): `cowork-tests/rerecord.sh`. It preflights `cowork-harness doctor --tier hostloop` (needs Docker, the `:2` agent image, and BOTH staged agent binaries — the Linux/arm64 ELF and the native Desktop host binary the hostloop agent loop spawns), records in a bounded parallel pool, prints a normalized `cowork-harness diff` per refreshed cassette (the primary drift review), and tails `stats` + `prune` (runs land in `~/.cowork-harness/runs`, so `stats` can trend reliability across re-records). `fidelity: cowork` records at native hostloop; host paths are stripped by `cowork-tests/.cowork-redact.json`, and `record` refuses a cassette whose asserts or `computer://` links redaction broke. The cowork-replay staleness gate is WARN-only, so cassettes drift between releases. Skip only if nothing under `skills/`, `scripts/`, `references/`, `agents/`, `commands/` or `plugin.json` changed since the last refresh — see "Cassettes and the assert block" below.

**cowork-harness version posture.** Three postures, per site — never collapse them into one number:

* **CI selectors are PINNED EXACTLY at `3.7.0`** — the four workflow `version:` inputs, the `skill-static-analysis` `npm i -g`, and the install lines in `CONTRIBUTING.md`, this file and `pyproject.toml`. Never a caret: a range auto-adopts upstream releases into CI with nobody choosing it, and CI steps have gone red on rules the harness added. Raise the pin in a deliberate adoption pass (write the adoption plan first, under the internal docs dir), never to chase a red.
* **RECORDING floor `>=3.6.0`** — `cowork-tests/rerecord.sh`, four sites; find the gate with `grep -n 'minor.*-ge'`, never by line number. The gate keeps the shape `-eq <major> && -ge <minor>` because the floors test's regex READS that shape — "simplifying" it blinds the guard, not the gate. The floor moves for four distinct kinds of reason, and only the first is a re-record trigger: (1) a release changes a fidelity input (emulated tool surface, spawn env, system prompt); (2) a release adds a record-time field that cannot be backfilled (`environment.harnessVersion` 1.11.0, `environment.model` + session fingerprint 3.1.0 — `rehash` migrates hash FORMATS, never fingerprint shape, and cannot cross a cassette-version boundary) or refuses pre-spend — in `executeScenario`, past the loader, so `--dry-run` never sees it — a scenario older versions accepted (2.5.0); (3) the pinned agent ELF no longer matches what Desktop stages — `doctor --tier hostloop` then reports a tolerated mismatch that a paid cassette would freeze, and recording needs `COWORK_HARNESS_ALLOW_AGENT_FALLBACK=1`; (4) a scenario asserts a key newer than the CLI — the loader HARD-REJECTS with `Unrecognized key`, `lint` on the same file exits 0, and `cassetteVersion` does not bump, so nothing warns (1.24.0, `file_absent` / `question_options`). 3.6.0 is the floor for reasons (1) and (3): it injects `CLAUDE_CODE_DESKTOP_APP_VERSION` into the spawn env (invisible to a baseline diff) and is the first release pinning the ELF Desktop 2.2553.1 stages.
* **Replay skip-guard `^2.1.0`** — `test_cowork_cassette_replay.py::_MIN_HARNESS`, the only replay-floor site. It decides whether the local replay test runs at all, not which CLI CI installs; raising it turns a below-floor developer's red into a silent skip. The one known future requirement: freezing `reference_read` / `no_observed_reference_access` into a scenario raises this floor to 2.5.0 — queued for the next re-record pass, not adopted.

`test_cowork_harness_floors.py` pins every site, this file included, and `uses:` (action) vs `version:` (CLI) major agreement — the two move independently. Read values from it; a version number in prose here has been stale on four separate occasions.

**Adopting a new harness release** — the checklist that has been wrong most often:
- Diff `src/` and `schema/` WHOLE between tags. A prefix list (`baselines/`, `src/runtime/…`) is a hand-list with extra steps; it missed a moved session fingerprint (3.2.0).
- Diff the baseline JSON leaf-by-leaf; compare `network.allowDomains` as a SET (order-only churn has read as a change three times); name what moved rather than listing what you checked (a hand-list once "verified" three keys that do not exist, and classifying the whole `provenance.*` prefix as noise missed a flipped gate — 3.0.0's `subagentPromptServerOverride` ON means no cassette can prove what sub-agent prompt text production sent). `baselines/` byte-identity is NOT "no fidelity debt" — 2.4.0 moved emulation code (`hostLoopCwds`, `container` `WebFetch` aliasing) with an identical baseline, and spawn-env changes in `src/runtime/argv.ts` (`NO_PROXY`, `CLAUDE_CODE_DESKTOP_APP_VERSION`) are invisible to any baseline diff.
- Our baseline is whatever `latest` resolves to (nothing declares `baseline:`): each cassette's `fingerprint.baseline` is what it recorded against, `latest` is the numerically highest file in the harness's `baselines/` dir. Re-derive after any `sync` or Desktop bump.
- Run every token-free surface before and after — `replay` over all cassettes, `verify-cassettes` with the expanded allowlist, `lint --strict --min-severity WARN`, `record --dry-run` (both arms), `analyze-skill --strict` (exits 0 on advisory findings; only `error` gates), `lint-skill --strict` — and diff the outputs. Settle an exit code by measuring, never by inheriting upstream prose.
- Standing risks with no cassette tripwire: (1) the elicitation-conflict gap — every SKILL.md's `AskUserQuestion` "(NOT plain chat)" directive can be silently overridden by the host's injected form guidance, unobservable by any harness run; cap-table's Step 0 hand-off gate is the one site without the fallback sentence (its fallback is scoped to a different gate). (2) The `Artifact` tool now reaches hostloop but the harness serves it at no tier; revisit when a real session shows it. (3) Real Cowork re-syncs host skills/plugins into a live session (~20 min); the harness stages once and never re-stages — a limit on what a green cassette proves. (4) `COWORK_EGRESS_PROXY` / `COWORK_DOCKER_NETWORK` never worked and were removed in 1.20.0 — do not add them from an old README (`COWORK_PROXY_IMAGE` is live).
- The upstream hook-detection fix (manifest-declared hooks) is gated to `protocol` only; our `SessionStart` hook disclosure cannot fire at hostloop. Not a bug for us; recorded so nobody expects it.

**Cassettes and the assert block** — rules, not history (the history is archived locally with the per-release adoption plans):
- Staleness is skill-scoped (each scenario's `skills:` key) but the mount is whole-plugin — narrowing the mount is what reintroduces a false-green. "Shared root" = everything NOT under `skills/<x>/`, so `commands/feedback.md` and `plugin.json` stale the fleet too. In practice every cassette is already fleet-stale on baseline drift, so "just re-record that skill's lanes" leaves the rest red. Derive corpus facts with `python cowork-tests/cassette_inventory.py` and `cowork-harness verify-cassettes cowork-tests/cassettes --skip-scenario-drift`; never from prose. Bare `rerecord.sh` refreshes only scenarios with a committed cassette (it prints what it skipped); author a new one by name. After a refresh: confirm green, commit `cassettes/` by name, then grep the new cassettes for improvised shell (`curl|wget|pip install|uv run|npx|apt-get|git clone`) — egress from bash has been live since 1.20.0 and no SKILL.md sanctions it.
- Plain `replay` evaluates the assert block FROZEN in the cassette, never the on-disk YAML. An assert added after recording is invisible to CI; one deleted after recording still runs. After any `assert:` edit, diff `json.load(cassette)["scenario"]["assert"]` against `yaml.safe_load(scenario)["assert"]` key sets.
- `replay <cassette> --assert-from <yaml> --write` persists the on-disk block for free — but `--allow-failing` disables its only drift gate, so a block written that way passes against pre-drift events, which is worse than silence (silence prompts a re-record; green does not). Do not cite those greens as evidence about current gate handling — `deck-review-gate-stop` (recorded fresh) is the evidence. Sequence a write-back with the fix, never before it. A refusal (`answers drifted`, `prompt drifted`) means a real re-record; re-derive which lanes refuse with a loop of `replay <cassette> --reassert` checking rc=2.
- `deck-review-numeric-chain` is in `_NO_CASSETTE_ALLOWLIST` and must never be recorded: a frozen recording would preserve the defects it exists to surface.
- Re-record trigger: every harness major, and any release whose changelog touches one of the three fidelity inputs. Nothing automatic flags it — the changelog is the authority. `rerecord.sh` enforces a **harness floor of `>=3.6.0`**.

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
