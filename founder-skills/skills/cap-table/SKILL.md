---
name: cap-table
description: "Use for any cap-table number, mechanic, or date before a founder signs — even one SAFE/note/warrant described in chat, a quick 'is this dilution reasonable?' gut-check, or a single QSBS / Israeli §102 eligibility question. Reliable, source-cited deterministic math (YC, NVCA, Cooley GO) for SAFE/note conversion and the post-money 'company capitalization' denominator, priced-round dilution, anti-dilution (BBWA / narrow-based / full-ratchet), option pools, warrants, MFN chains, dual-class voting, and Israeli ↔ Delaware flips. NOT for waterfall modeling, cumulative dividends, RSUs, 83(b), 409A, SPAC, warrant repricing, or pure term-glossary definitions — see scope notes."
when_to_use: >
  Use whenever a question turns on a cap-table number, mechanic, or date —
  conversion math, the post-money denominator, dilution, anti-dilution, MFN
  chains, warrants, dual-class voting, QSBS eligibility dates, §102 timing, or
  a flip — INCLUDING a single instrument described in chat, a bare yes/no, or a
  quick gut-check, and any draft or signed SAFE, note, term sheet, option plan,
  AoA, Carta XLSX, or spreadsheet. These carry known miscalculation and reliance
  traps, so run the deterministic math rather than answer from memory. Do NOT
  use for pure glossary definitions with nothing numeric, dated, or
  eligibility-related at stake ("what is a SAFE?"), fundraising strategy ("how
  much should I raise?"), or financial-model review (use `financial-model-review`).
user-invocable: true
---

# Cap-Table Skill

Model cap-table mechanics for founders so they understand what their term sheets, SAFEs, and convertible notes actually do to their ownership — before they sign. Produce rule-pack-cited math for SAFE conversion, convertible-note conversion, priced-round dilution, option-pool top-ups, anti-dilution, and Israeli ↔ Delaware flips. Every counsel-review item links back to a primary source (YC SAFE primer, NVCA model docs, Israeli Companies Law / Income Tax Ordinance, etc.). Tone is founder-first: a candid coach who's read the documents you can't be expected to read.

## Reliance Boundary (mandatory)

For any eligibility, qualification, or status determination that turns on tax or legal facts the cap-table data cannot settle — QSBS (IRC §1202), Israeli §102 track / holding period, IIA obligations, or any rule carrying `counsel_review` — state the **cited fact** (the date window, threshold, or clock) and stop there. **Never conclude that the founder does or will qualify** ("yes, you qualify", "you're eligible", "strong eligibility posture"). The date or threshold is a fact you may assert with its citation; the *conclusion* is a counsel determination — present it as such and emit a counsel item. This holds whether the engagement runs the full pipeline, fast-assess, or a one-line directional answer: the boundary is about what you may *conclude*, not how deep the analysis went.

## Skill Metadata

- **Author:** lool-ventures
- **Version:** managed in `founder-skills/.claude-plugin/plugin.json`
- **Compatibility:** Python 3.10+ and `uv` for script execution.
- **Rule pack:** consumes `cap-table-rules.json` at script runtime.
- **Exports (full pipeline, in `cap-table-{slug}/`):**
  - `inputs.json` + `scenarios.json` → `financial-model-review` (cross-validates revenue/dilution scenarios)
  - `cap_state.json` → `ic-sim` (IC partners ask about dilution exposure)
  - `counsel_packet.json` → `fundraise-readiness` (overall readiness scorecard)
  - `report.json` → `fundraise-readiness`, future `cross-document-consistency` skill
- **Exports (fast-assess mode, in `cap-table-{slug}-fastassess/`):**
  - `fast_assess_only.json` — sentinel marking that fast-assess ran (no canonical artifacts). See [`references/sentinel-schema.md`](references/sentinel-schema.md). Future cross-skill consumers MUST check for this sentinel before treating a missing canonical artifact as "cap-table never ran."
  - `report_fast_assess.md` — founder-facing markdown deliverable
- **Imports:**
  - `market-sizing:sizing.json` — sanity-check that the planned raise + cap is consistent with modeled SAM/SOM
  - `financial-model-review:report.json` — current revenue scale + runway, to gate scenario plausibility

## Skill Execution Model (READ FIRST)

This skill runs **inline in the main thread** (not as a sub-agent). The main thread has full tool access including Bash, and is responsible for orchestrating the full pipeline: running producer scripts, persisting artifacts, and dispatching the cap-table sub-agent at specific moments.

**Two dispatch contexts for the sub-agent:**

- **Context A — Per-step analytical dispatch (Mitigation 1):** Used ONLY for document-extraction lanes. Cap-table math is fully deterministic and rule-driven, so Context A is reserved for tasks that genuinely need semantic extraction from natural-language documents:
  - `INSTRUMENT_EXTRACTION` — extract terms from a PDF/DOCX SAFE, note, term sheet, or option plan
  - `SPREADSHEET_STRUCTURE_DETECTION` — identify which cells encode founders / preferred / options / convertibles in a freeform spreadsheet that doesn't match the Carta schema

  The sub-agent returns structured JSON. The main thread pipes the JSON through the validation producer (`extract_instrument.py` / `extract_cap_table.py`), which enforces the anti-hallucination gate. The sub-agent does NOT write artifacts directly.

- **Context B — Post-compose coaching dispatch (POST_COMPOSE_COACHING):** After `compose_report.py` writes `report.md` + `report.json`, the sub-agent is dispatched with the structured `coaching_payload` inlined. It performs Grep idempotency, edits `report.md` at the per-run uuid marker to add `## Coaching Commentary`, Grep-verifies all canonical artifacts share the same `run_id`, and returns a success/blocked payload.

**Why this model:** In Cowork, sub-agents have a restricted tool allowlist (no Bash). By keeping orchestration in the main thread and dispatching sub-agents only for analytical or post-compose tasks that use only Read/Edit/Glob/Grep, the pipeline works correctly in both Claude Code (CLI) and Cowork.

**Tolerant JSON extraction protocol (Context A):** After dispatching the sub-agent, capture its final assistant message. The sub-agent should return raw JSON, but may wrap it in ` ```json ... ``` ` fences or add a prose preamble. Extract JSON tolerantly:

1. If the message is wrapped in a ` ```json ... ``` ` (or plain ` ``` ... ``` `) fence, strip the fence first.
2. Try to parse the stripped text directly as JSON.
3. If that fails, walk through the text looking for the first `{` character and try `json.JSONDecoder().raw_decode(text[i:])` — this is brace-aware and handles nested objects correctly (unlike regex, which truncates on the first `}`).
4. If extraction fails entirely, re-prompt the sub-agent with: "Your previous reply could not be parsed as JSON. Return ONLY the JSON object — no markdown fences, no prose preamble."

> See `founder-skills/references/skill-execution-model.md` for the full inline-skill execution model (3 dispatch contexts, Mitigation 1+2, producer contract, Cowork quirks, per-symptom triage).

## Input Formats — Four Lanes

Each lane produces normalized `instruments.json` and/or `cap_state.json` plus an `extraction_audit.json` trail. The main thread picks the lane from the founder's input type.

- **Lane 1 — Single instrument (PDF / DOCX).** Typical: 5–15 page SAFE, term sheet, convertible note, option plan, **or Articles of Association**. Main thread reads via the Read tool (native PDF support, up to 20 pages per call; longer docs use `pages` parameter). For SAFEs/notes/term-sheets/option-plans: dispatch Context A `INSTRUMENT_EXTRACTION`; pipe returned JSON through `extract_instrument.py`. For AoAs: dispatch Context A `ARTICLES_OF_ASSOCIATION_EXTRACTION` (see `references/lanes/lane-1-pdf-docx.md#dispatch-context-a--articles_of_association_extraction`); pipe returned JSON through `extract_aoa.py` which validates + merges preferred-series terms into `inputs.json.preferred_series[]`. User confirmation via `AskUserQuestion` before math runs.
- **Lane 2 — Carta XLSX export.** Typical: multi-sheet XLSX (Securities, Convertibles, Stakeholders). `extract_cap_table.py --mode=carta` reads the sheet-name fingerprint and maps known columns → canonical schema. User confirms ambiguous mappings. See `references/carta-pulley-mapping.md` for the column-mapping table. Pulley is not yet supported end-to-end (`--mode=pulley` is a stub that returns a structured blocker pointing to Lane 3 / `--mode=freeform-emit`); restore when a real Pulley XLSX is available to verify against. **Carta exports carry no founder identities or pool structure — Lane 2 writes `instruments.json` + `extraction_audit.json` ONLY; always build `inputs.json` from founder answers (one batched `AskUserQuestion`: founders + share counts, pool authorized/issued/unallocated).** When offering founder candidate options, EXCLUDE obvious investor vehicles — names containing `Ventures`/`Capital`/`Fund` (founders are natural persons or a clearly personal holding entity). A holder also appearing as a SAFE/note investor MAY still be a legit founder co-investor — ASK rather than auto-exclude on that alone. Present an investor vehicle as context labeled "(investor — not a founder)", never as a founder option. (`cap_state.py` emits `W_FOUNDER_LOOKS_LIKE_INVESTOR` as a backstop.)
- **Lane 3 — Freeform spreadsheet (founder's Excel).** Arbitrary structure. `extract_cap_table.py --mode=auto` confirms the workbook is freeform (prints `detected_format` + sheet names; exits non-zero for freeform by design). Then `extract_cap_table.py --mode=grid --xlsx "$XLSX_PATH"` dumps all sheets as a cell-value grid (per sheet: dimensions, cell values, merged ranges) to stdout as JSON, compacted under a byte budget so it fits the dispatch control-frame cap (large sheets are trimmed/rounded/row-elided — see `references/lanes/lane-3-freeform.md`; a `grid_too_large` blocker means split the workbook per-sheet or fall back to Lane 4). The main thread pastes that JSON into the Context A `SPREADSHEET_STRUCTURE_DETECTION` dispatch prompt to identify cell semantics (block types + column roles from the closed `references/schemas/freeform-role-map.json` vocabulary), then pipes the returned blocks through `extract_cap_table.py --mode=freeform-emit` which deterministically maps them to schema-valid `inputs.json` (equity, merged into Step 2's file) + `instruments.json` and writes both. Fields the sheet can't supply (e.g. a note's `interest_rate_type`) come back as **blockers** (a human-in-the-loop gate); resolve them with the founder and re-run with `--answer BLOCK.FIELD=VALUE`. See `references/lanes/lane-3-freeform.md` for the full invocation sequence.
- **Lane 4 — Structured JSON paste / conversational.** Founder pastes pre-built JSON or describes their cap-table in chat. Direct heredoc into `inputs.json` / `instruments.json`; still flows through `extract_cap_table.py --mode=validate` for schema enforcement.

## Available Scripts

All scripts live at `${CLAUDE_PLUGIN_ROOT}/skills/cap-table/scripts/`:

- **`extract_instrument.py`** — Validates Lane-1 sub-agent output against the per-instrument schema; anti-hallucination gate (per-field confidence; "did you find this verbatim in the document"). Accepts: `safe`, `convertible_note`, `convertible_loan_agreement` (Israeli CLA), `convertible_security` (YC pre-SAFE form), `term_sheet`, `option_plan`, `warrant`, `non_instrument`.
- **`extract_aoa.py`** — Validates Lane-1 sub-agent output for Articles of Association (separate sub-context `ARTICLES_OF_ASSOCIATION_EXTRACTION`). Per-preferred-series field gates; detects 4 Israeli AoA counsel-review items (`israeli_aoa.*` rule pack domain): drag-along < 75%, §102 plan absent, liquidation preference > 1x, full-ratchet anti-dilution. With `--inputs` flag, merges validated preferred_series block into `inputs.json.preferred_series[]` with extraction provenance stamp.
- **`extract_cap_table.py`** — Lane-2/3/4 cap-table extraction; modes: `carta`, `pulley`, `freeform`, `freeform-emit`, `validate`, `auto`, `grid`. `grid` dumps all sheets as a JSON cell-value grid for Lane-3 `SPREADSHEET_STRUCTURE_DETECTION` dispatch; `freeform-emit` deterministically maps the detected blocks (via `freeform_mapper.py` + the `freeform-role-map.json` contract) into schema-valid `inputs.json` + `instruments.json`, with founder-confirmation blockers for fields freeform can't supply. Emits `cap_state.json` + `instruments.json` + `extraction_audit.json`.
- **`cap_state.py`** — Reads `inputs.json` + `instruments.json`; computes as-converted totals; writes `cap_state.json`. Validates per the §11 schema. **Note:** the YC Company Capitalization denominator scoping (Gotcha #1) is enforced here — `as_converted_totals.*` is the pre-financing snapshot.
- **`rule_audit.py`** — Two-phase: `--phase=pre_math` writes the gating block (per-rule, per-instance status + scope + overlays) BEFORE math runs; `--phase=post_math` composes watchlist + counsel-review items AFTER math. Math producers consume the gating block.
- **`run_scenario.py`** — Solver / orchestrator (NOT a fixed chain). Builds a dependency graph; classifies independent vs coupled computations; algebraic resolution first, fixed-point iteration as fallback for non-linear systems (discount-only SAFEs). Convergence threshold + max iterations are parameterized.
- **`safe_conversion.py`** — SAFE conversion math (cap-only, cap-plus-discount, discount-only, uncapped-MFN). Binds rule-pack inputs per the §5.1 binding table (see design doc).
- **`note_conversion.py`** — Convertible-note conversion math (cap, discount, both, repay, extend, counsel-review, override branches). Binds rule-pack inputs per the §5.2 binding table.
- **`priced_round.py`** — Priced-round math (pre-money, new-money, pool top-up, anti-dilution). Coupled with SAFE/note conversion via the solver.
- **`option_pool.py`** — Option-pool top-up math (rule pack `option_pool.pre_money_topup`). Uses `target_basis` denominator.
- **`anti_dilution.py`** — BBWA / full-ratchet anti-dilution (Gotcha #2 enforced here).
- **`flip_scenario.py`** — Israeli ↔ Delaware flip mechanics (share-for-share 1:1 only — see Gotcha #7).
- **`counsel_packet.py`** — Extracts counsel-review items from `rule_audit.json` into a standalone counsel-handoff packet.
- **`compose_report.py`** — Assembles all artifacts into `report.md` + `report.json` (with embedded `coaching_payload` block). Cross-artifact validation; emits per-uuid coaching insertion marker.
- **`visualize.py`** — Generates `report.html` (self-contained, inline SVG donut + tables; no CDN). The interactive `explore.py` is the one that uses vendored Chart.js.
- **`explore.py`** — Generates `explorer.html` (polished interactive scenario tool; demo/video-friendly).
- **`sweep.py`** — Generates the optional `sweep.json`: a pre-money parametric sweep (K real solver frames, `new_money` held fixed) that powers the explorer's "drag pre-money" slider. No new math — re-runs the priced-round path across a `pre_money` range. Slider snaps to discrete frames, so every value shown is real.
- **`quick_assess.py`** — Fast-assess directional review (Step 5-fast); writes the `fast_assess_only.json` sentinel + `report_fast_assess.md`, skipping the full pipeline.
- **`verify_one.py`** — Rule-lookup mode (Step 5-lookup): `--rule-lookup <rule_id>` returns the cited constant a rule holds (e.g. the QSBS OBBBA window start) + its citations + the reliance boundary, for a bare eligibility/date question. Allowlists by data: rules without a stored constant (e.g. §102 capital-gains) return `lookup_status: "escalate"` rather than echoing a non-constant field. No solver, no artifact.
- **`concise_report.py`** — Concise mode (Step 5-concise): renders `scenarios.json` (the solver's `computed_outputs`) + optional `rule_audit.json` flags into a short cited `report_concise.md`, skipping `visualize`/`explore`/`counsel_packet`/the full `compose_report`/the coaching sub-agent. Same numbers as the full pipeline (reads the same output); for a single quick math question.
- **`evidence_verifier.py` / `invariant_checker.py` / `cross_checker.py` / `backward_verifier.py`** — Lane-1 verification stack (Step 3). Forward evidence-quote check, real-world-bounds check, multi-extractor cross-check (demote-only), and fresh-sub-agent backward re-extraction. `extract_instrument.py` invokes these by default; they are also runnable standalone.
- **`_dispatch_json.py`** — Tolerant JSON extraction for Context A returns.

Also available from `${CLAUDE_PLUGIN_ROOT}/scripts/` (shared):

- **`founder_context.py`** — Per-company context management (init/read/merge/validate)
- **`find_artifact.py`** — Resolves artifact paths by skill name, artifact filename, optional company slug

Run with: `python3 ${CLAUDE_PLUGIN_ROOT}/skills/cap-table/scripts/<script>.py --pretty [args]`

## Available References

Read as needed from `${CLAUDE_PLUGIN_ROOT}/skills/cap-table/references/`:

- **`cap-table-reference.md`** — Domain primer: SAFE mechanics, note mechanics, anti-dilution formulas, §102/3(i)/85A/104H/103K, IIA royalty mechanics, BBWA formula, counsel-review semantics. **Read before implementing any math producer.**
- **`cap-table-rules.json`** — The executable reference layer: source-cited rules across the SAFE / convertible-note / option-pool / anti-dilution / Israeli-AoA / Delaware-flip / warrants / dual-class / benchmark domains, each with formulas, inputs, outputs, source citations, date_window semantics, and behavior_target (`script_formula` / `validation_rule` / `warning_rule` / `counsel_review_flag` / `benchmark` / `source_note`). Every math producer loads this at start and stamps its `metadata.version` into provenance.
- **`cap-table-rules.schema.json`** — JSON Schema for the rule pack (Draft 2020-12). The schema description on `counsel_review` is the authoritative definition of "reliance boundary, not confidence score" (see Gotcha #9).
- **`schemas/`** — JSON Schemas (Draft 2020-12) for every artifact: `inputs.schema.json`, `instruments.schema.json`, `cap_state.schema.json`, `scenarios.schema.json`, `rule_audit.schema.json`, `counsel_packet.schema.json`, `fast_assess_only.schema.json`. Each producer script validates against the matching schema.
- **`carta-pulley-mapping.md`** — Per-vendor column-mapping table for Lane 2 extraction.

## Artifact Pipeline

Every cap-table engagement deposits structured JSON artifacts into a working directory. The final step assembles them into a report and validates consistency. This is not optional.

| Step | Artifact | Producer |
|------|----------|----------|
| 1 | founder context | `founder_context.py` read/init |
| 2 | `inputs.json` | Agent heredoc or `extract_*.py` (Lane 4 / Lanes 1–3) |
| 3 | `instruments.json` | `extract_instrument.py` (Lane 1) or `extract_cap_table.py` (Lane 2/3/4) |
| 4 | `cap_state.json` | `cap_state.py` |
| 5 | `extraction_audit.json` | `extract_*.py` trail |
| 6 | `rule_audit.json` (gating block) | `rule_audit.py --phase=pre_math` |
| 7 | `scenarios.json` | `run_scenario.py` (solver; consumes gating block from Step 6) |
| 8 | `rule_audit.json` (watchlist + counsel items) | `rule_audit.py --phase=post_math` |
| 9 | `counsel_packet.json` + `counsel_packet.md` | `counsel_packet.py` |
| 10 | `comparisons.json` (when ≥2 scenarios) | `compose_report.py` |
| 11 | `report.md` + `report.json` (with `coaching_payload` block) | `compose_report.py --write-md` |
| 12 | `report.html` | `visualize.py` |
| 13 | `sweep.json` (optional — priced rounds only) | `sweep.py` |
| 14 | `explorer.html` | `explore.py` |
| 15 | `## Coaching Commentary` appended to `report.md` | Context B sub-agent (POST_COMPOSE_COACHING) |

**Rules:**
- Deposit each artifact before proceeding to the next step.
- Math producers consume `rule_audit.json.gating[R][I]` for rule-applicability decisions — NOT the rule pack directly. The two-phase split is what makes this work.
- For producer-script artifacts, the agent supplies JSON on stdin where applicable; the script schema-validates against `references/schemas/<artifact>.schema.json`. Never write artifacts directly via `Write` or `Edit` — always pipe through the producer script so `metadata.run_id` is injected and schemas are enforced.
- `compose_report.py` enforces that all required artifacts share the same `run_id` and emits `STALE_ARTIFACT` warnings on mismatch.

Keep the founder informed with brief, plain-language updates at each step. Never mention file names, scripts, or JSON. After each major step (extraction, scenarios, counsel), share a one-sentence finding before moving on.

## Workflow

### Step 0: Path Setup

```bash
SCRIPTS="${CLAUDE_PLUGIN_ROOT}/skills/cap-table/scripts"
# In Cowork, CLAUDE_PLUGIN_ROOT substitutes to a host-side path that does not
# exist inside the session VM — self-heal by locating the plugin mount:
if [ ! -d "$SCRIPTS" ]; then
  SCRIPTS="$(find /sessions -type d -path '*/skills/cap-table/scripts' 2>/dev/null | head -1)"
fi
if [ -z "$SCRIPTS" ] || [ ! -d "$SCRIPTS" ]; then
  SCRIPTS="$(find / -type d -path '*/skills/cap-table/scripts' 2>/dev/null | head -1)"
fi
PLUGIN_ROOT="${SCRIPTS%/skills/*}"
REFS="$PLUGIN_ROOT/skills/cap-table/references"
SHARED_SCRIPTS="$PLUGIN_ROOT/scripts"
# Resolve the canonical artifacts root via a SCRIPT, not inline bash. An inline path computation is
# guidance the agent paraphrases — it lands outputs/ in one run and outputs/artifacts/ in another,
# desyncing cross-skill find_artifact.py and breaking path-based checks. The script computes the root
# deterministically (under the promoted outputs/ dir in Cowork, ./artifacts in the CLI) and creates it.
python3 "$SHARED_SCRIPTS/resolve_artifacts_root.py"   # prints ARTIFACTS_ROOT — use the printed path verbatim as ARTIFACTS_ROOT in every later block (a captured var dies in the next fresh shell)

# Per-run identifier — used by every producer's --run-id. Stays constant
# across the whole engagement (compose enforces parity).
RUN_ID="${RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)}"
```

The Step 0 block self-heals when `${CLAUDE_PLUGIN_ROOT}` doesn't resolve (Cowork). If it still comes up empty, locate the anchor manually: `find / -path '*/skills/cap-table/scripts/cap_state.py' 2>/dev/null | head -5` and derive the variables from it.

After Step 1 (when the company slug is known), derive `REVIEW_DIR`. Two modes:

- **Full pipeline** (default — when the founder shared a document, asked for the full review, counsel packet, or interactive explorer, OR when there's no existing full review for this slug): `REVIEW_DIR="$ARTIFACTS_ROOT/cap-table-$SLUG"`.
- **Fast-assess mode** (Phase O — short directional answer to a conversational question, no document attached, no explicit "full review" request): `REVIEW_DIR="$ARTIFACTS_ROOT/cap-table-$SLUG-fastassess"`. Run `quick_assess.py` (Step 5-fast) instead of Steps 2–11. Total wall-clock under 60 seconds.
- **Rule-lookup mode** (a bare eligibility/date question — QSBS, Israeli §102, IIA — with **no instruments to model and no document**): answer straight from the rule pack — no `REVIEW_DIR`, no pipeline. Run `verify_one.py --rule-lookup <rule_id>` (Step 5-lookup) and present its cited constant + the reliance boundary (state the date/threshold; never conclude eligibility — emit a counsel item). If it returns `lookup_status: "escalate"` (the rule carries no stored constant — e.g. the §102 capital-gains clock, which runs from a plan/trustee-specific date the pack does not hold), ask the founder for the specific fact it names (e.g. the trustee-deposit date) and treat as a counsel determination — never state a default like `grant_date`.
- **Concise mode** (a single quick **math** question that `quick_assess` can't shape and that isn't a pure eligibility lookup — a fully-diluted warrant count, an as-converted snapshot, a standalone anti-dilution adjustment, one note/SAFE outside a priced round): run the deterministic math, then render a short cited answer with `concise_report.py` (Step 5-concise) — **skip** `visualize`, `explore`, `counsel_packet`, the full `compose_report`, and the Context-B coaching sub-agent. The numbers are identical to the full pipeline's (it reads the same `run_scenario` output); only the production weight is dropped. Offer the full review as a follow-up. `REVIEW_DIR="$ARTIFACTS_ROOT/cap-table-$SLUG-concise"`.

**Slug discipline:** Use the slug returned by `founder_context.py` VERBATIM in directory names — never invent ad-hoc suffixes (e.g. appending `-seed`, `-round`, or any other qualifier). Downstream `find_artifact.py` lookups resolve by that slug; a mismatched directory is invisible to the cross-skill layer.

```bash
# Choose ONE based on the routing decision above.
REVIEW_DIR="${REVIEW_DIR:-$ARTIFACTS_ROOT/cap-table-$SLUG}"          # full pipeline
# REVIEW_DIR="${REVIEW_DIR:-$ARTIFACTS_ROOT/cap-table-$SLUG-fastassess}"  # fast-assess
mkdir -p "$REVIEW_DIR"
# Sub-agent JSON staging lives OUTSIDE the promoted outputs/ tree. Anything under $REVIEW_DIR is a
# user-visible deliverable in Cowork, and deleting under outputs/ is unsafe there — so stage scratch
# in a temp dir, which is safe to both create and clean up.
STAGING_DIR="$(mktemp -d "${TMPDIR:-/tmp}/cap-table-${SLUG}.staging.XXXXXX")"
```

**Routing heuristics.** In order: (1) a **bare eligibility/date question** (QSBS, §102, IIA) with no instruments and no document → **rule-lookup** (Step 5-lookup) — a cited fact, not a pipeline run. (2) A **single quick math question** that `quick_assess` can't shape (warrant fully-diluted count, as-converted snapshot, standalone anti-dilution, a lone note/SAFE outside a priced round) → **concise mode** (Step 5-concise) — the real math, short answer, no heavy tail. (3) A **priced-round gut-check** / first-touch conversational answer (no document, no "full review"/"counsel packet"/"report"/"explorer"/"deep dive") → **fast-assess**. (4) Otherwise → **full pipeline**. If an existing `cap-table-$SLUG/report.json` is present, ask via `AskUserQuestion` whether to use it or start fresh.

**Artifact-worthy boundary (write the sentinel).** If your answer presents a founder-facing ownership/dilution **table** or a **post-financing ownership %**, you MUST run a script-backed path — `quick_assess` (fast-assess; writes the `fast_assess_only.json` sentinel + `report_fast_assess.md`), `concise_report` (concise mode; writes the real `cap_state.json` + `scenarios.json` + `report_concise.md`), or the full pipeline — do NOT hand-build such an answer in chat. A one-line directional aside while gathering inputs (e.g. "≈20% to new investors") is fine in chat and writes no artifact. This keeps any quantitative ownership answer backed by the script + sentinel, so downstream consumers can detect that cap-table ran.

### Step 1: Read or Create Founder Context

```bash
python3 "$SHARED_SCRIPTS/founder_context.py" read --artifacts-root "$ARTIFACTS_ROOT" --pretty
```

**Exit 0 (found):** Use the company slug and pre-filled fields. Proceed to Step 2.

**`W_SECTOR_TYPE_UNKNOWN` is benign for cap-table engagements.** If `founder_context.py` emits a `W_SECTOR_TYPE_UNKNOWN` warning (triggered by free-text sectors such as "technology"), proceed — `sector_type` is not read by any cap-table rule or script, so this warning has no effect on cap-table math or counsel-review gating. Do not re-prompt the founder just to resolve it.

**Exit 1 (not found):** This is normal for a first run — do not treat it as an error. Use `AskUserQuestion` (NOT plain chat) to ask for company name, stage, sector, and geography. Provide at least 2 options. Then create:

```bash
python3 "$SHARED_SCRIPTS/founder_context.py" init \
  --company-name "Acme Corp" --stage seed --sector "B2B SaaS" \
  --geography "US" --artifacts-root "$ARTIFACTS_ROOT" \
  --run-id "$RUN_ID"
```

**Exit 2 (multiple):** Present the list, ask which company, re-read with `--slug`.

### Step 2: Confirm Engagement Mode + Jurisdiction → `inputs.json`

Ask the founder via `AskUserQuestion` (NOT plain chat):

1. **Mode:** "Is this a flip-focused engagement (Israeli → Delaware), or a standard cap-table modeling engagement?" Options: `standard | flip_focused`.
2. **Jurisdiction structure:** Options: `delaware | israeli | delaware_with_israeli_sub | mid_flip`.
3. **IIA grant history (Israel-context only):** "Has the Israeli entity received any IIA / OCS grants?" Options: `yes | no | not_sure`.

Then build `inputs.json` via heredoc. The skeleton below is the **minimal** shape (no founders, no pool, no preferred) — useful only for flip-focused engagements that read existing artifacts. **For any engagement where someone owns shares, also include `founders[]` and `option_pool` blocks.** **Exception — Lane 3 (freeform spreadsheet):** write the **minimal** shape (company meta only, NO `founders[]` / `option_pool` / `preferred_series`); `extract_cap_table.py --mode=freeform-emit` fills those equity sections from the sheet and would otherwise conflict with seeded placeholders. See [`references/inputs-skeleton.md`](references/inputs-skeleton.md) for the full common-case shape, the validator-strictness gotcha (unknown keys are silently dropped), and the plan_type / OIP-OCP-CCP field meanings.

**MANDATORY cap-base confirmation gate (S2).** Before any FULL-pipeline math on an engagement where someone owns shares (Lanes 1/2/4), the founder cap base — each founder + common share count, and the option pool (authorized / issued / unallocated) — MUST be founder-confirmed via one batched `AskUserQuestion` (same rule as Lane 2). NEVER assume founder share counts or pool silently, and never use generic placeholder names like `Founder A` / `Founder B`. Set `metadata.cap_base_source = "confirmed"` once confirmed (or `"assumed"` if you proceed on an unconfirmed/placeholder base). `cap_state.py` emits `W_CAP_BASE_ASSUMED` as a backstop on placeholder names or an `"assumed"` flag; `"confirmed"` suppresses it. (Lane 3 is exempt — its base is extracted from the founder's own spreadsheet, not assumed.)

```bash
cat <<INPUTS_EOF > "$REVIEW_DIR/inputs.json"
{
  "company_name": "Acme Corp",
  "analysis_date": "$(date -u +%Y-%m-%d)",
  "mode": "standard",
  "jurisdiction": {
    "structure": "delaware",
    "incorporated_date": "2024-06-01",
    "iia_grants_history": {"has_grants": false, "grant_details": []}
  },
  "event_dates": {
    "restructuring_effective_date": null,
    "restructuring_approval_date": null,
    "filing_date": null,
    "tax_position_date": null,
    "flip_closing_date": null,
    "benchmark_reference_date": null
  },
  "founders": [
    {"name": "Founder A", "founder_id": "founder_a", "common_shares": 10000000}
  ],
  "option_pool": {
    "plan_type": "iso",
    "authorized": 1500000,
    "issued": 0,
    "unallocated": 1500000
  },
  "engagement_questions": [],
  "metadata": {"run_id": "$RUN_ID", "schema_version": "v0.5.0-inputs"}
}
INPUTS_EOF
```

**`founders[]` and `option_pool` are required for any engagement with shares.** The schema marks them optional, but `cap_state.py` produces an empty pre-financing snapshot if either is missing — with no warning. Read `references/inputs-skeleton.md` if your scenario has preferred series, `common_batches`, or non-standard option-plan jurisdictions.

**`metadata.schema_version` is required** on `inputs.json` (`"v0.5.0-inputs"`), `instruments.json` (`"v0.5.0-instruments"`), and `cap_state.json` (`"v0.5.0-cap-state"`). Producer scripts inject the value when they write; founder-supplied heredoc inputs must include it explicitly or `extract_cap_table.py --mode=validate` rejects with `E_SCHEMA_VERSION_MISMATCH`. Common field-name gotchas: `preferred_series[].shares` (not `shares_outstanding`); `preferred_series[].series_name` (not `series_label`); `preferred_series[].liquidation_preference_type` (not `participation`); `founders[].common_shares` (not `shares`). `preferred_series[]` lives in `inputs.json`, NOT `instruments.json` — the instruments schema has no `preferred_series` key; an unknown top-level key in `instruments.json` is silently dropped rather than rejected, so there is no schema error to catch the mistake.

**`option_pool.plan_type` enum:** `iso` | `nso` | `section_102_cg` | `section_102_oi` | `section_3i` | `mixed`. The Israeli §102 capital-gains track is `section_102_cg` — there is no `"israeli_102"` or `"102_cg"` value; those fail validation. See `references/inputs-skeleton.md` for the jurisdiction-to-plan_type mapping table.

**Omit unknown optional fields rather than writing `null`, EXCEPT fields the skeleton explicitly shows as `null` — those are schema-nullable (`["string","null"]` or `["number","null"]`) and keeping them as `null` is correct.** Most other schema fields are typed non-nullable (e.g., `jurisdiction.incorporated_date` is `string`, not `string | null`); writing `null` for those fails validation. Fields shown in the Step 2 skeleton with values are either required or strongly recommended. `jurisdiction.incorporated_date` matters for §102/QSBS date math — ask the founder rather than omitting if the engagement touches those.

Validate immediately:

```bash
python3 "$SCRIPTS/extract_cap_table.py" --mode=validate --dir "$REVIEW_DIR"
```

### Step 3: Ingest Instruments → `instruments.json`

Route by input format. Each lane has a dedicated dispatch + validation protocol — read the matching lane reference before executing.

| Input format | Lane | Reference |
|---|---|---|
| Single PDF / DOCX (SAFE, term sheet, note, option plan, **or AoA**) | 1 | [`references/lanes/lane-1-pdf-docx.md`](references/lanes/lane-1-pdf-docx.md) |
| Carta multi-sheet XLSX export (Pulley not yet end-to-end) | 2 | [`references/lanes/lane-2-carta-pulley.md`](references/lanes/lane-2-carta-pulley.md) |
| Freeform founder spreadsheet (arbitrary structure) | 3 | [`references/lanes/lane-3-freeform.md`](references/lanes/lane-3-freeform.md) |
| Structured JSON paste or conversational reconstruction | 4 | [`references/lanes/lane-4-structured.md`](references/lanes/lane-4-structured.md) |

**Lane 1 invocation pattern** — after capturing the sub-agent's JSON reply into a shell variable or a staging file under `$STAGING_DIR`, pipe it through `extract_instrument.py` like this:

```bash
cat <<'EXTRACT_EOF' | python3 "$SCRIPTS/extract_instrument.py" \
  --instruments "$REVIEW_DIR/instruments.json" \
  --source-doc "$SOURCE_DOC_PATH" \
  --run-id "$RUN_ID" --pretty
<JSON extracted from sub-agent reply>
EXTRACT_EOF
```

`extract_instrument.py` reads the sub-agent JSON from **stdin** and updates `--instruments` **in place**. The `-o/--output` flag writes a JSON receipt confirming the write (does not change where instruments are stored). If the id already exists in the target array you'll get `E_DUPLICATE_INSTRUMENT_ID`; re-run with `--replace` to overwrite the existing entry instead.

**Dispatch independence rule (CRITICAL):** the sub-agent dispatch prompt for `INSTRUMENT_EXTRACTION` contains the document text and the GENERIC extraction rules only. NEVER include per-document hints, expected values, or pre-decided classifications in the dispatch prompt (e.g. "this doc's form is cap_plus_discount", "use issuance_date 2024-01-15") — the sub-agent's reading must be independent. The verification stack (`evidence_verifier.py` → `invariant_checker.py` → `cross_checker.py`) exists to catch divergence; a led witness cannot diverge. Generic normalization rules (e.g. '"Discount Rate is 80%" means multiplier 0.80') are field semantics, not per-document answers — those belong in the dispatch prompt.

**Verification stack** (Lane 1 and any other lane that piped through `extract_instrument.py`): forward `evidence_verifier.py` → `invariant_checker.py` → `cross_checker.py` → optional `backward_verifier.py`. All default-on; see the Lane 1 reference for the receipt schema, `attention_needed_fields` semantics, and when to run backward verification.

**EXTRACTION CONFIRM-GATE (MANDATORY):** Extractor warnings that say "confirm with note text" or "confirm with founder" are a **QUESTION GATE** — not suggestions. After any extraction (Lane 1, 2, or 3), scan all warnings. For every field flagged as assumed or left null (e.g. `qualified_financing_threshold`, `maturity_default_treatment`, `interest_converts_to_shares`, `interest_rate_type`, `capitalization_denominator`), batch ALL such fields into ONE `AskUserQuestion` call and get the founder's answers before running any math. NEVER fill them with "standard assumptions" and proceed silently. If the founder cannot confirm a field, you MUST: (a) name the assumption explicitly in the final presentation (e.g. "interest rate type assumed fixed simple — confirm with note text"), (b) emit a counsel item flagging it. The denominator field (`capitalization_denominator`) requires special care: its definition comes from the note's "Company Capitalization" clause and is note-text-specific — do not default to the cap_state fully-diluted count. Also note: `non_qualified_financing_treatment: convert_anyway` means convert at cap/discount even though the round missed the qualified financing threshold — there is no separate `convert_at_cap` enum value for this field.

**Freeform `discount` is NOT a confirm-gate field.** A freeform spreadsheet `discount` column is governed by the deterministic rate convention (`references/schemas/freeform-role-map.json` `discount_convention`: a value like `0.20`/`20` is a 20% RATE → multiplier `0.80`; multiplier-form input is unsupported). The producer's resulting conversion `warning` is a TRANSPARENCY note — surface it in the final presentation (see the Lane-3 reference's `ok:true` step), but NEVER raise a rate-vs-multiplier `AskUserQuestion` for it: the convention already decided it is a rate. (Genuinely out-of-range values — `> 100` or `≤ 0` — still surface as blockers, which is a different path.)

**Image-only PDFs (vision fallback):** if the document has no text layer, the verifier can't match values. Dispatch a FRESH sub-agent to transcribe the relevant passages, then feed that text to the verifier via `--doc-text <file> --doc-text-source model_vision`. The verifier stamps `verification_source: "model_vision"` and demotes confidence one level — surface that to the founder. (A missing PDF parser is different: it raises `E_MISSING_DEPENDENCY` and blocks, not a silent image-only pass.)

**Lane 4 instruments.json SAFE skeleton** (use when authoring by heredoc or conversational reconstruction):

```json
{
  "safes": [
    {
      "id": "safe_1",
      "investor_name": "Investor Name",
      "purchase_amount": 500000,
      "post_money_valuation_cap": 5000000,
      "discount_multiplier": null,
      "form": "yc_postmoney_cap",
      "issuance_date": "2025-06-01",
      "extraction_confidence": "high"
    }
  ],
  "convertible_notes": [],
  "warrants": [],
  "option_grants": [],
  "metadata": {"run_id": "<RUN_ID>", "schema_version": "v0.5.0-instruments"}
}
```

Field-name traps: it's `purchase_amount` (not `principal` — that's convertible notes), `post_money_valuation_cap` (not `valuation_cap`), `form` (not `safe_type`/`instrument_type`), `id` (not `safe_id`). The `form` enum values are: `yc_postmoney_cap`, `yc_postmoney_discount`, `yc_uncapped_mfn`, `cap_plus_discount`, `yc_premoney_cap_only`, `pre_money_cap_and_discount_legacy`, `other`. For a cap-AND-discount SAFE use `form: "cap_plus_discount"` with BOTH `post_money_valuation_cap` and `discount_multiplier` non-null.

**Field-name boundary — `id` vs `safe_id`:** When authoring or validating `instruments.json`, each SAFE object uses the field name **`id`** (e.g. `"id": "safe_seed_1"`). The field `safe_id` appears ONLY in `cap_state.json` output objects, where `cap_state.py` renames it for that artifact. Never write `safe_id` into `instruments.json`; the schema will reject it as an unknown key, and `cap_state.py` will raise `E_SAFE_MISSING_FIELD`.

After Step 3 completes, `instruments.json` is committed and the run proceeds to Step 4.

### Step 4: Compute Cap State → `cap_state.json`

```bash
python3 "$SCRIPTS/cap_state.py" \
  --inputs "$REVIEW_DIR/inputs.json" \
  --instruments "$REVIEW_DIR/instruments.json" \
  --run-id "$RUN_ID" \
  -o "$REVIEW_DIR/cap_state.json" --pretty
```

The script computes the pre-financing `as_converted_totals` (Gotcha #1 enforced structurally) and validates against `references/schemas/cap_state.schema.json`.

### Step 4.5: Pre-Math Rule Audit → `rule_audit.json` (gating block)

```bash
python3 "$SCRIPTS/rule_audit.py" --phase=pre_math \
  --inputs "$REVIEW_DIR/inputs.json" \
  --instruments "$REVIEW_DIR/instruments.json" \
  --cap-state "$REVIEW_DIR/cap_state.json" \
  --run-id "$RUN_ID" \
  -o "$REVIEW_DIR/rule_audit.json" --pretty
```

Math producers in Step 5 consume `rule_audit.json.gating[R][I]` — they do NOT re-evaluate rule applicability. This is the only place status is computed.

### Step 5-fast (FAST-ASSESS MODE ONLY): Run `quick_assess.py` and exit

When the routing decision in Step 0 picked fast-assess, skip the full Steps 2–11 pipeline (no cap_state / scenarios / rule_audit / counsel_packet / compose). You still author two small input files first — a minimal `inputs.json` and a bare SAFE array — directly from the founder's conversational answers (see the AskUserQuestion gate below); fast-assess does NOT run the Lane-1/2/3 extractors or the full Step 2 heredoc. Then run:

```bash
python3 "$SCRIPTS/quick_assess.py" \
  --inputs "$REVIEW_DIR/inputs.json" \
  --safes "$REVIEW_DIR/safes.json" \
  --pre-money 20000000 --new-money 5000000 \
  --review-dir "$REVIEW_DIR" \
  --run-id "$RUN_ID" \
  --founder-prompt "<the founder's raw prompt>" \
  --pretty
```

**`--safes` takes a BARE JSON ARRAY of SAFE objects** (not the `instruments.json` envelope). Write a file that starts with `[` — an array of SAFE instrument objects — not `{"safes": [...]}`. To author it, write the minimal `inputs.json` (company_name, founders, option_pool, jurisdiction) and the SAFE array straight from the founder's answers — these two files are the only artifacts fast-assess writes by hand.

**Convertible notes need a conversion date.** If the founder has notes, pass `--event-date YYYY-MM-DD` (the date the notes convert). If you omit it when notes are present, fast-assess defaults to today and discloses the assumption (an Assumptions line in the report + a sentinel `assumptions[]` entry) — the math producer itself never assumes a date.

**Never assume a pool top-up.** Pass `--target-pool-percent X --target-basis post_money` ONLY when the founder stated a pool target (or confirmed one when you asked). Otherwise run WITHOUT those flags — the report then carries an explicit "No pool top-up modeled" note, and you offer the 10% what-if as a follow-up re-run. A silently assumed pool target materially changes the founder's headline ownership; it is the founder's negotiation variable, not yours.

Inputs are built from the founder's conversational description via `AskUserQuestion` (Lane 4 only — fast-assess does NOT invoke Lane-1/2/3 extractors). **Do not skip the question gate, and do not split it:** batch everything still missing into ONE `AskUserQuestion` call before running — typically jurisdiction structure (if not obvious), IIA/OCS grant history (Israeli companies), and pool-target intent. If the founder's message already supplied everything, ask nothing and run. When you present the result, state in one line any flag choices that encode an assumption (e.g. "modeled with no pool top-up" / "modeled with the 10% post-money pool you mentioned"). The script writes:

- `${REVIEW_DIR}/fast_assess_only.json` — sentinel for downstream consumers
- `${REVIEW_DIR}/report_fast_assess.md` — 1-page founder-facing markdown

**Read `report_fast_assess.md` and present its numbers verbatim to the founder — never re-derive or reconstruct the ownership table in chat.** If you computed preliminary estimates while gathering inputs, discard them in favour of the script output. The script is the authoritative source; hand-reconstructed math will diverge from the fixed-point solver result. This includes the dilution explanation — use the share counts from the report; never re-derive top-up or conversion shares by hand. For what-if follow-ups (e.g. "what if we top up the pool to 10%?"), re-run `quick_assess.py` with the changed flag and present the new report — never estimate the answer by hand.

**Full-pipeline what-ifs (applies to both fast-assess and full reviews):** the `explorer.html` displays only precomputed scenarios (plus, when `sweep.json` exists, a pre-money slider that scrubs precomputed real solver frames — also not hand-estimated). For any scenario not yet modeled, write a new scenario request and re-run the full pipeline:
1. Add the new scenario to `scenario_requests.json`
2. Re-run `run_scenario.py` → `rule_audit.py --phase=post_math` → `compose_report.py`
3. Present the updated `report.md` numbers verbatim
Never hand-estimate a new scenario in chat.

Total wall-clock: under 60 seconds. Then jump to **Step 12: Deliver Artifacts** with the fast-assess deliverable. Offer the founder a follow-up: "I gave you the directional answer — want the full review with counsel packet and interactive explorer?"

### Step 5-lookup (RULE-LOOKUP MODE ONLY): Run `verify_one.py` and exit

For a bare eligibility/date question (QSBS, Israeli §102, IIA) — no instruments, no document — answer from the rule pack instead of running the pipeline. Pick the rule that holds the relevant fact and run:

```bash
python3 "$SCRIPTS/verify_one.py" --rule-lookup delaware_cross_border.qsbs_date_sensitive --pretty
```

- **`lookup_status: "answered"`** — present the `answer` (the cited constant + its primary source) and the `reliance_boundary` verbatim-in-spirit: state the date/threshold, then stop. Never conclude eligibility; emit a counsel item (the rule carries `counsel_review: true`).
- **`lookup_status: "escalate"`** — the rule holds no stored constant (e.g. `israel_equity_tax.section_102_capital_gains`, whose clock runs from a plan/trustee-specific date the pack does not store). Do **not** state a default. Ask the founder for the specific fact the payload names (e.g. the trustee-deposit date), and treat it as a counsel determination.
- **`lookup_status: "not_found"`** — the rule_id was wrong; pick the correct one or fall back to fast-assess / full pipeline.

This writes no artifact and runs in well under a second. If the founder then supplies instruments or asks for the full picture, route to fast-assess or the full pipeline.

### Step 5-concise (CONCISE MODE ONLY): run the math, render a short answer, skip the heavy tail

For a single quick math question, do Steps 2–3 (build `inputs.json` + `instruments.json` + a one-line `scenario_requests.json` from the founder's description, Lane 4), then run ONLY the math producers + `concise_report.py`. **Skip** `counsel_packet`, the full `compose_report`, `visualize`, `explore`, and the Context-B coaching sub-agent. The over-production in the full pipeline is the model driving ~14 sequential tool calls plus the coaching sub-agent — not the scripts (each runs in well under 0.1 s); concise mode collapses the tail to one render.

```bash
mkdir -p "$REVIEW_DIR"
python3 "$SCRIPTS/cap_state.py" --inputs "$REVIEW_DIR/inputs.json" --instruments "$REVIEW_DIR/instruments.json" --run-id "$RUN_ID" -o "$REVIEW_DIR/cap_state.json"
python3 "$SCRIPTS/rule_audit.py" --phase=pre_math --inputs "$REVIEW_DIR/inputs.json" --instruments "$REVIEW_DIR/instruments.json" --cap-state "$REVIEW_DIR/cap_state.json" --run-id "$RUN_ID" -o "$REVIEW_DIR/rule_audit.json"
python3 "$SCRIPTS/run_scenario.py" --inputs "$REVIEW_DIR/inputs.json" --instruments "$REVIEW_DIR/instruments.json" --cap-state "$REVIEW_DIR/cap_state.json" --scenarios-input "$REVIEW_DIR/scenario_requests.json" --run-id "$RUN_ID" -o "$REVIEW_DIR/scenarios.json"
python3 "$SCRIPTS/rule_audit.py" --phase=post_math --inputs "$REVIEW_DIR/inputs.json" --scenarios "$REVIEW_DIR/scenarios.json" --run-id "$RUN_ID" -o "$REVIEW_DIR/rule_audit.json"
python3 "$SCRIPTS/concise_report.py" --inputs "$REVIEW_DIR/inputs.json" --scenarios "$REVIEW_DIR/scenarios.json" --rule-audit "$REVIEW_DIR/rule_audit.json" --run-id "$RUN_ID" -o "$REVIEW_DIR/report_concise.md"
```

Present `report_concise.md` verbatim — never re-derive its numbers in chat. Concise mode writes the real `cap_state.json` + `scenarios.json` (so downstream consumers detect cap-table ran). Then jump to **Step 12: Deliver Artifacts** and offer the full review as a follow-up.

### Step 5: Determine Scenarios + Run Math → `scenarios.json`

Ask the founder via `AskUserQuestion` which scenarios to model (1–4). Common patterns:

- **Standalone SAFE conversion** (cap-implied math; no priced round): `{type: "safe_conversion", parameters: {}}`
- **Series A priced round**: `{type: "priced_round", parameters: {pre_money, new_money, target_pool_percent, target_basis}}`
- **Convertible note conversion at financing**: `{type: "note_conversion", parameters: {transaction_event_date, priced_round_new_money, qualified_financing_price}}`
- **Israeli ↔ Delaware flip** (only when mode=flip_focused or explicitly requested): `{type: "flip", parameters: {iia_grants_in_history, section_102_grants_outstanding}}`

**Canonical gate phrasing (prefer these exact strings).** To keep founder UX consistent and let the regression cassettes anchor on stable text, when you raise these recurring `AskUserQuestion` gates use the question text and option labels below verbatim — do not paraphrase or add per-run suffixes like "(Recommended)" / "(standalone)":
- **Scenario selection** — question: "Which scenarios should I model? (select all that apply)"; option labels: `Cap-implied SAFE snapshot` (→ `safe_conversion`), `Series A priced round` (→ `priced_round`), `Convertible note conversion at financing` (→ `note_conversion`), `Israeli ↔ Delaware flip` (→ `flip`). Offer only the scenarios that apply to this cap table.
- **Option pool** (when confirming pool existence — e.g. a Lane-3 sheet with no pool tab) — question: "Does the company have an employee option pool?"; option labels: `No option pool`, `Yes — I'll provide authorized / issued / unallocated`. The "Yes" label MUST keep a free-text/chat path so the founder can supply the counts in chat — the same affordance the cap-base confirmation relies on (S2, Step 2, for Lanes 1/2/4; the equivalent pool-count path here). Never collapse it to a bare yes/no.

Write the scenario-request list to a temp file:

```bash
cat <<SCENARIOS_EOF > "$REVIEW_DIR/scenario_requests.json"
[
  {"scenario_id": "base", "label": "Base case", "type": "safe_conversion", "parameters": {}},
  {"scenario_id": "series_a", "label": "Series A at \$20M pre / \$5M raise",
   "type": "priced_round",
   "parameters": {"pre_money": 20000000, "new_money": 5000000,
                  "target_pool_percent": 0.10, "target_basis": "pre_money"}}
]
SCENARIOS_EOF
```

Then run all scenarios:

```bash
python3 "$SCRIPTS/run_scenario.py" \
  --inputs "$REVIEW_DIR/inputs.json" \
  --instruments "$REVIEW_DIR/instruments.json" \
  --cap-state "$REVIEW_DIR/cap_state.json" \
  --scenarios-input "$REVIEW_DIR/scenario_requests.json" \
  --run-id "$RUN_ID" \
  -o "$REVIEW_DIR/scenarios.json" --pretty
```

`run_scenario.py` dispatches to the right math producer per scenario type and consumes the gating block from Step 4.5. After this completes, share a one-sentence finding per scenario with the founder (e.g., "Series A drops your stake from 87% to 64%; the 10% pool top-up costs you ~3pp").

**`scenarios.json` ownership shape:** per-holder ownership percentages live in `scenarios.json` → `scenarios[n].computed_outputs.aggregate_ownership_by_class` (an object keyed by class, e.g. `{"founders": 0.64, "preferred": 0.26, "option_pool": 0.10}`). Per-holder share counts and full ownership tables are always rendered in `report.md`'s Current Cap State section by `compose_report.py`: individual founders appear by name with share counts and pre-round % in both single-class and dual-class engagements. There is no `post_financing_table.rows` field in `scenarios.json` — do not look for one there.

### Step 6: Post-Math Rule Audit → `rule_audit.json` (watchlist + counsel items)

```bash
python3 "$SCRIPTS/rule_audit.py" --phase=post_math \
  --inputs "$REVIEW_DIR/inputs.json" \
  --scenarios "$REVIEW_DIR/scenarios.json" \
  --run-id "$RUN_ID" \
  -o "$REVIEW_DIR/rule_audit.json" --pretty
```

The gating block from Step 4.5 is preserved verbatim; this phase adds watchlist + counsel items. **`--inputs` and `--scenarios` are required for runtime-event counsel-rule gating** — the `anti_dilution.stale_ccp_detected`, `anti_dilution.cp2_floor_applied`, `anti_dilution.pay_to_play_provision_detected`, and four `anti_dilution.solver_*` rules each fire only when their underlying runtime event actually occurred (solver warning emitted, AoA P2P pattern detected, etc.). Without the flags, those rules default to suppressed — safe (no false positives) but produces false negatives instead. Always pass both.

### Step 7: Counsel Packet → `counsel_packet.json` + `counsel_packet.md`

```bash
python3 "$SCRIPTS/counsel_packet.py" \
  --rule-audit "$REVIEW_DIR/rule_audit.json" \
  --inputs "$REVIEW_DIR/inputs.json" \
  --scenarios "$REVIEW_DIR/scenarios.json" \
  --run-id "$RUN_ID" \
  -o "$REVIEW_DIR/counsel_packet.json" \
  --write-md "$REVIEW_DIR/counsel_packet.md" --pretty
```

### Step 8: Compose Report → `report.md` + `report.json`

```bash
python3 "$SCRIPTS/compose_report.py" \
  --dir "$REVIEW_DIR" --run-id "$RUN_ID" \
  -o "$REVIEW_DIR/report.json" \
  --write-md "$REVIEW_DIR/report.md" --pretty
```

`compose_report.py` validates run_id parity (emits `STALE_ARTIFACT` warning on mismatch) and writes the per-run uuid `insertion_marker` Context B will use in Step 11.

**Post-write verification:** `compose_report.py` exits non-zero (code 2) if the output files don't exist or are empty. If compose exits non-zero, stop and report the exact stderr — do not proceed to Step 9.

### Step 9: Generate `report.html`

```bash
python3 "$SCRIPTS/visualize.py" --dir "$REVIEW_DIR" -o "$REVIEW_DIR/report.html"
```

### Step 10: Generate `explorer.html`

When at least one `priced_round` scenario carries both `pre_money` and `new_money`, first generate the
optional pre-money sweep so the explorer renders a "drag pre-money" slider. The slider scrubs precomputed
**real solver frames** (every value shown is real math — it snaps to discrete frames, never interpolates
ownership), holding `new_money` fixed. It is optional: if `sweep.json` is absent, the explorer simply
renders no slider.

```bash
# Optional: precomputed pre-money sweep for the explorer slider (skip if no eligible priced_round scenario).
python3 "$SCRIPTS/sweep.py" --dir "$REVIEW_DIR" --run-id "$RUN_ID" -o "$REVIEW_DIR/sweep.json" || true

python3 "$SCRIPTS/explore.py" --dir "$REVIEW_DIR" -o "$REVIEW_DIR/explorer.html"
```

### Step 11: Post-Compose Coaching Commentary (Context B dispatch — POST_COMPOSE_COACHING)

**Dispatch the cap-table sub-agent in Context B.** Dispatch via the `Task` tool after `compose_report.py` has successfully written both `report.json` and `report.md`.

**Mitigation 2 protocol:** the main thread reads the structured `coaching_payload` from `report.json` and inlines it into the dispatch prompt. The sub-agent does NOT Read full `report.md` — it consumes `coaching_payload` directly.

<!-- skill-quality-ci: bash-after-subagent-ok -->
```bash
python3 -c '
import json, sys
data = json.load(open(sys.argv[1]))
print(json.dumps(data["coaching_payload"], indent=2))
' "$REVIEW_DIR/report.json"
```

The payload prints to stdout — copy it from the tool result into the dispatch
prompt below. (Never capture it into a shell variable: each Bash call runs in a
fresh shell, so the variable would be unreadable and gone.)

**Dispatch prompt template:**

```
CONTEXT: POST_COMPOSE_COACHING

You are dispatched to add coaching commentary to a cap-table report.

The compose_report.py script has finished. The structured `coaching_payload`
from report.json is:

<paste the coaching_payload JSON printed by the previous Bash command here verbatim>

Follow your agent body's Context B procedure (POST_COMPOSE_COACHING):

1. grep_idempotency_check — Grep "## Coaching Commentary" (output_mode:count)
   and Grep the EXACT coaching_payload.insertion_marker (output_mode:count)
   on coaching_payload.report_path. Apply the 6-state decision matrix.
2. Compose commentary from the inlined coaching_payload (scenario_digest,
   ownership_range_across_scenarios, top_dilution_drivers,
   counsel_review_summary, date_sensitive_summary, flip_specifics).
   Do NOT Read the full report.md.
3. edit_via_marker — single Edit on coaching_payload.report_path:
     old_string = coaching_payload.insertion_marker  (EXACT uuid string)
     new_string = "## Coaching Commentary\n\n<your commentary>"
4. self_verify_artifacts_via_grep_run_id — Grep run_id from each producer
   artifact (inputs, instruments, cap_state, scenarios, rule_audit,
   counsel_packet). All 6 must match. Re-Grep the marker (must be 0)
   and the "## Coaching Commentary" header (must be 1) on report.md.
5. Return the success payload (per agent body Context B step 5).

Stop after returning JSON. Do not narrate.
```

**After the sub-agent returns:** apply the tolerant JSON extraction protocol to obtain the success/blocked payload. If `status == "blocked"`, stop and report the reason. If `status == "complete"`, present `report_path` to the founder.

**Inline alternative (permitted but discouraged).** The Context B procedure above can also be executed by the main thread directly: read `coaching_payload` from `report.json`, compose commentary, run the same Grep idempotency check, and use Edit on the `insertion_marker`. This is functionally equivalent for outputs but **bypasses the fresh-sub-agent isolation** that protects Context A's verifier loop from Context B reasoning. Prefer the dispatched path. The privacy boundary (no investor names, no document text in coaching commentary) is enforced at compose time by `_assert_coaching_payload_privacy_clean()` in `compose_report.py` — that check runs regardless of dispatch path, so the privacy invariant holds even when inline is used.

### Step 12: Deliver Artifacts

Copy human-readable deliverables to workspace root with company-slug prefix:

```bash
SLUG_TITLE="$(echo $SLUG | sed 's/-/_/g' | awk '{for(i=1;i<=NF;i++) $i=toupper(substr($i,1,1)) substr($i,2)} 1')"
cp "$REVIEW_DIR/report.md"     "${SLUG_TITLE}_Cap_Table.md"
cp "$REVIEW_DIR/report.html"   "${SLUG_TITLE}_Cap_Table.html"
cp "$REVIEW_DIR/explorer.html" "${SLUG_TITLE}_Cap_Table_Explorer.html"
cp "$REVIEW_DIR/counsel_packet.md" "${SLUG_TITLE}_Counsel_Packet.md"
```

Do **not** delete the `/tmp` staging dir — it is ephemeral scratch the sandbox reclaims on its own.
Never issue a `rm` here: a delete command near an `outputs/` path is conservatively read as an
outputs-deletion (a Cowork-parity violation) even when its target is `/tmp`.

**Fixing a bad artifact (Cowork-safe):** to correct a wrong artifact, **overwrite it in place** by re-running the producer script that writes it (e.g., re-run `cap_state.py` / `extract_instrument.py --replace` / `compose_report.py`). Do NOT delete-and-recreate; deletion may be denied in Cowork. Writing (overwriting) is always permitted.

In flip-focused mode, the flip-impact narrative is rendered as a dedicated section inside `report.md` by the standard compose pipeline — no separate file.

The structured-artifact set (inputs.json, instruments.json, cap_state.json, scenarios.json, rule_audit.json, counsel_packet.json, report.json) stays inside `$REVIEW_DIR` for cross-skill consumption and archival.

## Gotchas

These are the cap-table-specific correctness traps. Each is a real source of math or legal-conclusion error in shipped cap-table tools. Read before implementing the corresponding script.

### 1. YC Company Capitalization denominator excludes new-money + new-pool

`safe.post_money_cap_conversion` needs `company_capitalization` as its denominator. The shipped rule (`safe.company_capitalization_yc_post_money`) defines it as `pre_financing_common_equivalents + promised_options + unissued_option_pool + converting_securities` — **specifically excluding new-money financing shares and most post-financing pool increases.** The rule pack flags any model that includes either as a hard warning.

Always bind from `cap_state.as_converted_totals.*` (the pre-financing snapshot) — never re-derive from a post-money figure. See design doc §5.1 binding table.

### 2. BBWA anti-dilution divisor uses CP1, not Original Issue Price

The Broad-Based Weighted Average formula: `CP2 = CP1 × (A + B) / (A + C)` where `B = consideration_received / CP1` (the current conversion price), **not** `consideration / original_issue_price`. Cooley GO and NVCA Model Cert §4.4.4 both use CP1; using OIP under-protects investors and mis-models down rounds.

### 3. `discount_multiplier` is the multiplier, not the percent

`0.80` means "convert at 80% of the priced-round price" (a 20% discount). `20` would mean "convert at 2,000% of the priced-round price." The field is named `_multiplier` (not `_rate` or `_percent`) to make this unambiguous; the rule `safe.discount_rate_semantics` enforces the semantic. Document extraction must convert any percent value to the multiplier form before writing to `instruments.json`.

### 4. MFN cherry-pick chains can be circular

When SAFE A's `mfn_provision.elected_against_safe_id` points to SAFE B, the founder is asking to inherit B's terms. If B is also `yc_uncapped_mfn` pointing back at A (or at another uncapped-MFN SAFE in a chain), there's no anchor price and the system has no real-valued solution. `run_scenario.py` detects this with a circular-reference guard and raises `E_SAFE_REQUIRES_CONVERSION_EVENT` for both with a "circular MFN reference" note. Don't try to resolve by picking one — fail loudly.

### 5. `maturity_conversion_price_override` ONLY applies to `convert_at_cap`

The override exists specifically to unblock the case where a note has `maturity_default_treatment = convert_at_cap` but `valuation_cap` is null (e.g., document-defined non-cap conversion). Pairing the override with `repay` / `extend` / `counsel_review` is a contract violation (`E_NOTE_OVERRIDE_BRANCH_MISMATCH`) — those treatments don't produce a conversion price, so an override price has nothing to override.

### 6. §102 trustee deposit date is NOT the same as grant_date

Section 102(b) capital-gains route requires that options be **held in trust** for 24 months from the **trustee deposit date**, which is typically a few days to weeks AFTER the grant date. Confusing the two silently breaks every §102 holding-period assertion. The `instruments.option_grants[]` schema carries `grant_date` AND `section_102_trustee_deposit_date` as separate fields for this reason.

### 7. The Israeli → Delaware flip is share-for-share ONLY

Real flips often involve share exchange ratios other than 1:1, partial roll-forward of SAFEs/CLAs, and adjustment for option-plan continuity. The skill models only the 1:1 share-for-share case; anything else exits with "flip ratio modeling deferred — counsel-review required." SAFE/CLA conversion + pricing run as a SEPARATE priced-round scenario before or after the flip, not as part of the flip math. Don't try to collapse them.

### 8. QSBS post-OBBBA start date is 2025-07-05, not 2025-07-04

Public Law 119-21 §70431 applies to stock acquired **after** July 4, 2025 (the enactment date). With the rule pack's inclusive `>= start` semantics, the first in-window day is **2025-07-05**. The off-by-one is the difference between "QSBS gain exclusion applies" and "doesn't" for stock issued on July 4 itself. Verify before applying to any issuance date in early July 2025.

### 9. `counsel_review: true` is a reliance boundary, NOT a confidence score

A rule can be `confidence: high` AND `counsel_review: true` simultaneously. `counsel_review` tells the script what it may *conclude* (flag / ask / handoff — never legal conclusion / tax classification / eligibility determination); `confidence` tells the script how strong the underlying sourcing is. Don't downgrade a well-sourced rule to medium just because it's flagged for counsel review. The schema description on `cap-table-rules.schema.json` and the "Counsel Review Semantics" section of `cap-table-reference.md` are the authoritative definitions.

### 10. Standalone cap SAFEs produce cap-implied output ONLY — not a post-financing table

A `yc_postmoney_cap` or `cap_plus_discount` SAFE standalone (no priced round) CAN produce `cap_implied_ownership`, `safe_price`, and cap-implied shares — these are deterministic from the cap and `company_capitalization` alone. It CANNOT produce a post-financing ownership table or Founder Impact Lens, because those describe dilution from new money + pool top-up that hasn't happened. Scenarios in this state get `completeness = structural_only` with `cap_implied_only` sub-flag. Render "Cap-implied ownership (pre-financing)" — never fabricate post-financing rows.

### 11. Carta and Pulley export column conventions differ

Both ship multi-sheet XLSX exports, but the sheet names, column ordering, and convertible-instrument representations are NOT interchangeable. `references/carta-pulley-mapping.md` carries the per-vendor column-mapping table; Lane 2 detects the vendor from the sheet-name fingerprint and routes accordingly. If the fingerprint doesn't match, fall back to Lane 3 (freeform). Don't assume "it looks like Carta" — verify the fingerprint.

## Main-Thread Return

This skill runs inline in the main thread (not as a sub-agent). The final outcome the main thread delivers to the founder is:

- The path to `{Company}_Cap_Table.md` in the workspace root — the primary narrative deliverable.
- The path to `{Company}_Cap_Table_Explorer.html` — the polished interactive scenario tool.
- The path to `{Company}_Counsel_Packet.md` — the counsel-handoff packet.
- The structured success payload from the Context B sub-agent (Step 11): `{status, review_dir, report_path, scenarios_modeled, counsel_review_count, completeness_breakdown, high_severity_warnings}`.

**Do NOT inline `report_markdown` in the assistant message.** The founder reads the file via the path. (Same rationale as deck-review #13: avoids ~25 KB round-trip through the parent context.)

## Feedback

If a run ends **blocked or failed**, after you report the reason to the founder, add one line:
> _If this looks wrong or didn't finish, you can flag it: `/founder-skills:feedback`._

On **unsolicited** praise or frustration, you may mention `/founder-skills:feedback` once — never routinely, never mid-workflow, never more than once per session.
