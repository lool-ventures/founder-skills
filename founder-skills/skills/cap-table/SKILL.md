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
- **Rule pack:** consumes `data/cap-table-rules.json` at script runtime.
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

> See `founder-skills/references/skill-execution-model.md` for the full inline-skill execution model (3 dispatch contexts, Mitigation 1+2, producer contract, Cowork quirks, per-symptom triage).

This skill runs **inline in the main thread**, not as a sub-agent — see the reference above ("Why Inline (Not Forked Sub-Agent)") for the rationale. Sub-agents are deliberately shell-free, so orchestration (producer scripts, artifact persistence) stays in the main thread.

**Two dispatch contexts for the sub-agent:**

- **Context A — Per-step analytical dispatch (Mitigation 1):** Used ONLY for document-extraction lanes. Cap-table math is fully deterministic and rule-driven — the reference's Context A section carries this as cap-table's dedicated exception (no analytical/judgment work in the math layer requires a sub-agent) — so Context A is reserved for tasks that genuinely need semantic extraction from natural-language documents:
  - `INSTRUMENT_EXTRACTION` — extract terms from a PDF/DOCX SAFE, note, term sheet, or option plan
  - `SPREADSHEET_STRUCTURE_DETECTION` — identify which cells encode founders / preferred / options / convertibles in a freeform spreadsheet that doesn't match the Carta schema

  The sub-agent returns structured JSON. The main thread pipes the JSON through the validation producer (`extract_instrument.py` / `extract_cap_table.py`), which enforces the anti-hallucination gate. The sub-agent does NOT write artifacts directly.

- **Context B — Post-compose coaching dispatch (POST_COMPOSE_COACHING):** After `compose_report.py` writes `report.md` + `report.json`, the sub-agent Reads the staged `coaching_payload.json` from the hand-off dir (Mitigation 2) — it does NOT read the full `report.md` — composes the coaching commentary, WRITES it to the `OUTPUT_PATH` hand-off file, and returns a small receipt. The main thread gates the file (`check_handoff.py`) and inserts it via the shared `insert_coaching.py` script (idempotency matrix, uuid-marker replacement, run_id-parity verification — all deterministic). See the reference above for the full Context B contract.

**Tolerant JSON extraction protocol (Context A):** After dispatching the sub-agent, capture its final assistant message. The sub-agent should return raw JSON, but may wrap it in ` ```json ... ``` ` fences or add a prose preamble. Extract JSON tolerantly:

1. If the message is wrapped in a ` ```json ... ``` ` (or plain ` ``` ... ``` `) fence, strip the fence first.
2. Try to parse the stripped text directly as JSON.
3. If that fails, walk through the text looking for the first `{` character and try `json.JSONDecoder().raw_decode(text[i:])` — this is brace-aware and handles nested objects correctly (unlike regex, which truncates on the first `}`).
4. If extraction fails entirely, re-prompt the sub-agent with: "Your previous reply could not be parsed as JSON. Return ONLY the JSON object — no markdown fences, no prose preamble."

## Input Formats — Four Lanes

Each lane produces normalized `instruments.json` and/or `cap_state.json` plus an `extraction_audit.json` trail. The main thread picks the lane from the founder's input type. **Founder-facing:** lanes, grids, and structure-detection are internal — to the founder this is just "reading your cap table" (or "reading your spreadsheet"); never announce the lane number, "the grid", "structure detection", or a script/flag as you work through the steps below.

- **Lane 1 — Single instrument (PDF / DOCX).** Typical: 5–15 page SAFE, term sheet, convertible note, option plan, **or Articles of Association**. Main thread reads via the Read tool (native PDF support, up to 20 pages per call; longer docs use `pages` parameter). For SAFEs/notes/term-sheets/option-plans: dispatch Context A `INSTRUMENT_EXTRACTION`; pipe returned JSON through `extract_instrument.py`. For AoAs: dispatch Context A `ARTICLES_OF_ASSOCIATION_EXTRACTION` (see `references/lanes/lane-1-pdf-docx.md#dispatch-context-a--articles_of_association_extraction`); pipe returned JSON through `extract_aoa.py` which validates + merges preferred-series terms into `inputs.json.preferred_series[]`. User confirmation via `AskUserQuestion` before math runs — present the extracted terms in the question body and confirm with the Gate Catalog's *Cap-base confirmation* labels (the same confirm-or-correct pair); never put document values in an option label.
- **Image-only PDF guard (any `.pdf` source).** Before you rely on a cap-table read from a `.pdf` by the Read tool (vision), run `python3 scripts/pdf_probe.py "<path>"`. Text PDFs (`image_only: false`) read normally. If `image_only: true` (no text layer — dense tables are under-read by vision), prefer OCR over vision:
  - **Try OCR first** (the full-parity agent image ships `tesseract` + `pdftoppm`): `python3 scripts/extract_pdf_tables.py "<path>"` rasterizes + OCRs the pages into a `--mode=grid` payload (same shape Lane 3 consumes). Paste that grid into the Lane-3 `SPREADSHEET_STRUCTURE_DETECTION` dispatch and run `--mode=freeform-emit` (the normal Lane-3 path). Set `metadata.extraction_mode = "ocr_image_pdf"`. **A3:** if the OCR grid shows a printed grand fully-diluted total (a "Total"/"Fully Diluted" row), copy it into `inputs.json` `stated_totals` so `cap_state.py` cross-foots it (`W_FD_RECONCILE_DELTA`). OCR is lossy — confirm the cap base with the founder before math.
  - **If OCR is unavailable or fails** (binaries absent / `extract_pdf_tables` errors): fall back to vision — set `metadata.extraction_mode = "vision_image_pdf"` (so `cap_state.py` emits `W_VISION_EXTRACTION_LOW_CONFIDENCE` and the artifacts carry the caveat), tell the founder the cap table is LOW-CONFIDENCE / directional, and PROCEED (degraded-but-honest — never silently present vision numbers as authoritative).
  - **RTL / reversed-Hebrew text layer.** `pdf_probe.py` also reports an `rtl` block; when `rtl.rtl_suspect` is true (a Hebrew-locale export — common in this corpus — even one that HAS a text layer), do not transcribe tables from a vision read alone: extract the raw text (pdfplumber), check line direction, and if `rtl.rtl_reversed_likely` reverse each line before reading labels (digits inside an RTL line usually stay LTR — verify against a printed total / `stated_totals` before math). Warning only; lane routing is unchanged.
- **Tracked-changes DOCX guard (any `.docx` source).** Before relying on a `.docx` read, run `python3 scripts/_docx_text.py "<path>" --detect`. If `has_tracked_changes: true`, the file is a **redline / unsigned draft under negotiation** — the operative terms are ambiguous (struck vs inserted). Do NOT silently extract. Raise an `AskUserQuestion` BEFORE extraction: "This document has tracked changes — it's a redline / unsigned draft, not a final executed version. How should I proceed?" Options: `Upload the clean / final executed version` / `Proceed on the accepted (final-proposed) terms — I understand it's a draft`. **This gate message is the PRIMARY draft caveat** (it reaches the founder even for a standalone instrument that never builds a cap base). On "proceed": get the accepted-view text with `python3 scripts/_docx_text.py "<path>" --extract` and (a) paste **that** output as the document text in the Context-A `INSTRUMENT_EXTRACTION` dispatch — NOT the raw Read-tool view — so the extractor and `evidence_verifier` read the SAME accepted-revisions view (else a correct inserted-term extraction can't be verified); and (b) set `inputs.metadata.source_markup = "tracked_changes_accepted"` so `cap_state.py` emits `W_REDLINE_DRAFT` and the report persists the caveat. (`_docx_text` reads the accepted view stdlib-only — works in the sandbox, which omits `office_convert`.)
- **Lane 2 — Carta XLSX export.** Typical: multi-sheet XLSX (Securities, Convertibles, Stakeholders). `extract_cap_table.py --mode=carta` reads the sheet-name fingerprint and maps known columns → canonical schema. User confirms ambiguous mappings. See `references/carta-pulley-mapping.md` for the column-mapping table. Pulley is not yet supported end-to-end (`--mode=pulley` is a stub that returns a structured blocker pointing to Lane 3 / `--mode=freeform-emit`); restore when a real Pulley XLSX is available to verify against. **Carta exports carry no founder identities or pool structure — Lane 2 writes `instruments.json` + `extraction_audit.json` ONLY; always build `inputs.json` from founder answers (one batched `AskUserQuestion`: founders + share counts, pool authorized/issued/unallocated).** When offering founder candidate options, EXCLUDE obvious investor vehicles — names containing `Ventures`/`Capital`/`Fund` (founders are natural persons or a clearly personal holding entity). A holder also appearing as a SAFE/note investor MAY still be a legit founder co-investor — ASK rather than auto-exclude on that alone. Present an investor vehicle as context labeled "(investor — not a founder)", never as a founder option. (`cap_state.py` emits `W_FOUNDER_LOOKS_LIKE_INVESTOR` as a backstop.) **Reconciliation:** if the carta receipt's `summary.fully_diluted` is present (Carta's printed grand total — independent of the rows you rebuild), copy it into `inputs.json` `stated_totals` `{ "fully_diluted": <n>, "source": "carta_summary" }`. `cap_state.py` cross-foots the rebuilt cap base against it and emits `W_FD_RECONCILE_DELTA` if they diverge > 0.1% — catching a holder/class dropped during the manual rebuild.
- **Lane 3 — Freeform spreadsheet (founder's Excel).** Arbitrary structure — no fixed schema, unlike Lanes 1/2/4.

  1. `extract_cap_table.py --mode=auto` confirms the workbook is freeform (prints `detected_format` + sheet names; exits non-zero for freeform by design).
  2. `extract_cap_table.py --mode=grid --xlsx "$XLSX_PATH"` dumps all sheets as a cell-value grid (per sheet: dimensions, cell values, merged ranges) to stdout as JSON, compacted under a byte budget so it fits the dispatch control-frame cap (large sheets are trimmed/rounded/row-elided — see `references/lanes/lane-3-freeform.md`; a `grid_too_large` blocker means split the workbook per-sheet or fall back to Lane 4).
  3. The main thread pastes that JSON into the Context A `SPREADSHEET_STRUCTURE_DETECTION` dispatch prompt to identify cell semantics (block types + column roles from the closed `references/schemas/freeform-role-map.json` vocabulary).
  4. Pipe the returned blocks through `extract_cap_table.py --mode=freeform-emit`, which deterministically maps them to schema-valid `inputs.json` (equity, merged into Step 2's file) + `instruments.json` and writes both.
  5. Fields the sheet can't supply (e.g. a note's `interest_rate_type`) come back as **blockers** (a human-in-the-loop gate); resolve them with the founder and re-run with `--answer BLOCK.FIELD=VALUE`.

  See `references/lanes/lane-3-freeform.md` for the full invocation sequence.

  **`SPREADSHEET_STRUCTURE_DETECTION` stated-total requirement:** alongside `blocks`, the structure sub-agent must also report a top-level `stated_total` field = the sheet's printed grand fully-diluted total for the current/most-recent snapshot column (the cell the sheet itself labels "Total Fully Diluted", "TFD", or equivalent — pool-inclusive, as-converted basis).
  - Report it **only** when such a cell is unambiguously present.
  - Omit the field entirely if the sheet's grand total is labeled "Issued"/"Outstanding" (pool-excluded), is as-issued rather than as-converted, or the basis is ambiguous — an issued-only total diverges from the fully-diluted count by the whole unallocated pool, so a wrong-basis stamp would fire a false `W_FD_RECONCILE_DELTA` on a correct sheet.
  - Use only a total the sheet itself prints; never report a sum the skill computed (non-circularity).
- **Lane 4 — Structured JSON paste / conversational.** Founder pastes pre-built JSON or describes their cap-table in chat. Direct heredoc into `inputs.json` / `instruments.json`; still flows through `extract_cap_table.py --mode=validate` for schema enforcement.

  **Lane 4 has no document to fall back on, so a field the founder did not state must NOT be invented.**
  Lanes 1–3 have the absent-field protocol (leave `null`, `confidence.level: "absent"`, an `ambiguities`
  entry, `completeness: "partial"`) precisely because a document can be silent on a field. A conversation
  can be silent too, and the same rule applies with more force: there is no source to re-read later.

  Concretely — a SAFE or note **`issuance_date` the founder never gave**. Do not fill in a plausible date:
  it flows into the date-sensitive watchlist and a founder-facing status table, where it is
  indistinguishable from one they supplied. Instead **ask** — the date is one `AskUserQuestion` away, shaped
  per the Gate Catalog's *Founder-only fact gates* row (a stated-value option plus an explicit defer), and it
  changes QSBS, §102 and maturity math — or record it absent per the protocol above and say in the report
  that the timing rows are unresolved pending that date. The same holds for any relaxable field:
  `purchase_amount` / `principal` / `investor_name` / `maturity_date`.

  A fabricated date is worse than a missing one. A missing one stops the founder; a fabricated one gives
  them a QSBS clock that is wrong by however far you guessed.
- **Anything not matching a lane above** (e.g. a multi-page PDF export of a pro-forma cap table, a scanned ledger, an unfamiliar tool export). No dedicated lane exists yet — reconstruct via **Lane 4** from the document + founder confirmation: read/transcribe what you can, hand-build `inputs.json` / `instruments.json`, and flow through `--mode=validate`. This is a **sanctioned fallback** (see Coverage & Disclosure), not an improvisation — stamp `metadata.cap_base_provenance = "model_reconstructed"` and apply the cap-base confirmation gate as normal.

## Available Scripts

All scripts live at `${CLAUDE_PLUGIN_ROOT}/skills/cap-table/scripts/`:

- **`extract_instrument.py`** — Validates Lane-1 sub-agent output against the per-instrument schema; anti-hallucination gate (per-field confidence; "did you find this verbatim in the document"). Accepts: `safe`, `convertible_note`, `convertible_loan_agreement` (Israeli CLA), `convertible_security` (YC pre-SAFE form), `term_sheet`, `option_plan`, `warrant`, `non_instrument`, `amendment`. The last three are non-extractable — classified and surfaced but not persisted to an instrument array; an `amendment` restates one clause of an existing instrument (its other terms legitimately absent), so its clause deltas surface from the receipt `ambiguities` rather than being forced through the note gate. **`term_sheet` / `option_plan` are terms-docs:** no strict field schema, not persisted to a math array — their extracted `fields` ride in the receipt's `terms_doc`. Both cases render from the receipt: write it to `extraction_audit.json` and pass `compose_extraction_report.py --audit`, which emits an "Amendments (terms modified)" section and a "Term sheet terms (as extracted)" table. Piping a term sheet / option plan through `extract_instrument.py` and saving the `--audit` receipt is mandatory; never hand-compose `report_extraction_only.md`. Terms docs never block on a verifier/invariant finding (those surface as per-field to-confirm markers), but a missing `--source-doc` or other input-integrity error still fails loud. **The full pipeline saves the receipt the same way** (Step 3's Lane-1 invocation always passes `-o "$REVIEW_DIR/extraction_audit.json"`), and `compose_report.py` reads it directly — no `--audit` flag there, since `compose_extraction_report.py` is the no-cap-base fork's renderer.
- **`extract_aoa.py`** — Validates Lane-1 sub-agent output for Articles of Association (separate sub-context `ARTICLES_OF_ASSOCIATION_EXTRACTION`). Per-preferred-series field gates; detects 4 Israeli AoA counsel-review items (`israeli_aoa.*` rule pack domain): drag-along < 75%, §102 plan absent, liquidation preference > 1x, full-ratchet anti-dilution. With `--inputs` flag, merges validated preferred_series block into `inputs.json.preferred_series[]` with extraction provenance stamp.
- **`extract_cap_table.py`** — Lane-2/3/4 cap-table extraction; modes: `carta`, `pulley`, `freeform-emit`, `validate`, `auto`, `grid`. `grid` dumps all sheets as a JSON cell-value grid for Lane-3 `SPREADSHEET_STRUCTURE_DETECTION` dispatch; `freeform-emit` deterministically maps the detected blocks (via `freeform_mapper.py` + the `freeform-role-map.json` contract) into schema-valid `inputs.json` + `instruments.json`, with founder-confirmation blockers for fields freeform can't supply. Emits `instruments.json` + `extraction_audit.json` (plus `inputs.json` on the freeform-emit path). NOT `cap_state.json` — that is `cap_state.py`'s output at Step 4.
- **`cap_state.py`** — Reads `inputs.json` + `instruments.json`; computes as-converted totals; writes `cap_state.json`. Validates per the §11 schema. **Note:** the YC Company Capitalization denominator scoping (Gotcha #1) is enforced here — `as_converted_totals.*` is the pre-financing snapshot.
- **`detect_structure.py`** — Signal-based coverage detector. Reads `inputs.json` + `instruments.json`; emits `required_primitives`, `covered` (bool), `uncovered_parts`, and `route.scenario_requests` for covered deals. Deterministic (no NLP). Run before any math to determine whether the deterministic pipeline covers the deal. See `## Coverage & Disclosure`.
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
- **`../data/cap-table-rules.json`** — The executable reference layer: source-cited rules across the SAFE / convertible-note / option-pool / anti-dilution / Israeli-AoA / Delaware-flip / warrants / dual-class / benchmark domains, each with formulas, inputs, outputs, source citations, date_window semantics, and behavior_target (`script_formula` / `validation_rule` / `warning_rule` / `counsel_review_flag` / `benchmark` / `source_note`). Every math producer loads this at start and stamps its `metadata.version` into provenance.
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

Keep the founder informed with brief, plain-language updates at each step. **Narrate the founder-visible OUTCOME, never the internal step.** That is the test to apply, and it catches more than a word list can: the forbidden thing is not a syntax, it is talking about the machinery. Bad — "Gating and piping the extraction through the producer, then staging the coaching hand-off"; good — "I've checked your numbers and I'm writing up what stood out." Bad — "schema-drift warning on `coaching_payload`"; good — nothing, because the founder has no stake in it. **Never name an internal artifact, field, or token** (a payload key, a marker name, an artifact filename, a hand-off dir) even in plain prose with no backticks — a detector keyed on syntax cannot see "gated", "hand-off" or "canonical artifacts", but the founder still reads them and they still mean nothing to them. **The between-step progress lines are the primary leak vector, not the final summary.** They feel internal — you are narrating what you are about to do — but the founder reads every one of them, and this is where the leaks actually appear: *"Now gating the hand-off before piping through the checklist producer"*, *"Gate 1 passes"*, *"Running the final verification gate"*. Rewrite each pipeline transition as the founder-visible outcome: *"Checking your numbers against the 46-point review"*, *"Your inputs look consistent — moving on to unit economics"*, *"Finishing up and putting the report together"*. If a progress line would mean nothing to someone who has never seen this skill's internals, it does not belong in the channel. Also excluded, as before: file/script names, paths, `*.py`, `--flags`, `$vars`, exit codes ("Exit N", "not found"), `W_`/`E_` codes, JSON, and step/route labels ("Lane N", "Context A/B", "Phase N", "structure detection", "the grid", any `ALL_CAPS_TOKEN`). After each major step (extraction, scenarios, counsel), share a one-sentence finding before moving on. **The task tracker is founder-visible too — the same rule governs its labels.** "Gate the inputs review handoff", "Validate inputs.json", "resolve agent namespace paths", "Initialize founder context" are leaks even though each names a real step, and even when the prose around them is clean. Label each task by the founder-visible outcome — "Check your inputs", "Score against the review", "Write up what I found" — never by a file, directory, script, or pipeline stage.

## Coverage & Disclosure

Before running cap-table math in a full-pipeline engagement, determine whether the deal structure falls within the validated engine's coverage. **Never substitute mental arithmetic for a covered script path** — the fixed-point solver enforces rule-pack gotchas that hand-rolled estimates miss silently.

### Detect coverage after instruments are committed

After `instruments.json` and `cap_state.json` are written (Steps 3–4), run:

```bash
python3 "$SCRIPTS/detect_structure.py" \
  --inputs "$REVIEW_DIR/inputs.json" \
  --instruments "$REVIEW_DIR/instruments.json" \
  --run-id "$RUN_ID" \
  -o "$REVIEW_DIR/coverage_result.json" --pretty
```

The script emits:
- `required_primitives` — mechanics the deal requires
- `covered` (bool) — whether the deterministic pipeline covers all required primitives
- `uncovered_parts` — any primitives the pipeline cannot handle
- `route.scenario_requests` — a ready-to-run scenario list (populated only when `covered: true`)

### If `covered: true` — use the deterministic pipeline

Populate `scenario_requests.json` from `route.scenario_requests` (the detection output) instead of authoring it by hand. **The route gives you the scenario SHAPE, not a runnable request** — ids, types, chaining order, and whatever parameters are derivable from the artifacts. It CANNOT supply terms that live with the founder rather than in `inputs.json`/`instruments.json`: a `priced_round` comes back needing `pre_money` and `new_money`, a `flip` needing the IIA / §102 answers (each request names its own gaps in `parameters_required`). Fill those in from the founder's stated deal at Step 5 — see the confirm/extend instruction there — and never run a request with them missing: `run_scenario.py` returns a `E_MISSING_PARAMETER` blocker rather than a result. This is about ROUND TERMS only; the hand-rolled-math ban below is unaffected and still absolute. Proceed to Step 4.5 and Step 5 as normal. **Never hand-roll or mentally estimate a covered deal** — not as a sanity check, not as a directional figure alongside the solver result. The solver is the authoritative source; any hand-rolled estimate will diverge from the fixed-point result.

For covered deals, `compose_report.py` writes `coverage_disclosure.json` (with `covered: true`, `computation_method: deterministic_pipeline`) and any reconciliation banner automatically — no agent action required.

### If `covered: false` — hand-roll with mandatory disclosure

When `uncovered_parts` is non-empty, the deal combines primitives the engine does not fully handle. You may produce numbers manually, but:

1. **Build manually from rule-pack formulas** — cite each `rule_id` explicitly so the math is traceable.
2. **Write `coverage_disclosure.json`** into `$REVIEW_DIR/` by heredoc:
   ```json
   {
     "schema_version": "v0.1-coverage-disclosure",
     "covered": false,
     "computation_method": "manual_outside_pipeline",
     "required_primitives": ["<from detection output>"],
     "uncovered_parts": ["<from detection output>"],
     "counsel_review": true
   }
   ```
3. **Prepend the provisional banner** to the report:
   `> ⚠️ **Computed outside the validated cap-table engine.** This deal combines primitives the deterministic pipeline does not fully cover; figures are provisional — confirm with counsel.`
4. **Emit a counsel item** for every uncovered primitive, regardless of confidence in the manual calculation.

Never present hand-rolled figures without the banner and the `coverage_disclosure.json` artifact.

**Input-format fallback (document matched no lane).** The `covered:` axis above is about MATH primitives. Input FORMAT is a separate axis: when the document is genuinely readable but matches none of the four lanes and you hand-rebuild the cap base from it, that is a sanctioned fallback, not an improvisation — set `metadata.cap_base_provenance = "model_reconstructed"` (fires `W_CAP_BASE_RECONSTRUCTED`), apply the cap-base confirmation gate as normal, and note the unmatched source format in the report's methodology line. Math coverage stays whatever `detect_structure.py` reports; there is no `coverage_disclosure.json` schema change for the input-format axis.

**Scripts that require `cap_state.json`.** `rule_audit.py --phase=pre_math`, `run_scenario.py`, and `compose_report.py` all require `cap_state.json` and are unusable when no cap state can be produced (e.g. the no-cap-base fork above, or a hand-roll before cap state exists). To cite a rule-pack constant for a hand-rolled figure without running the pipeline, use `verify_one.py --rule-lookup <rule_id>` against `cap-table-rules.json`.

### Acquisition inputs (`inputs.acquisition`) — counsel-reviewable

When the deal includes a negotiated-% share acquisition concurrent with or immediately prior to a priced round, populate `inputs.acquisition` in `inputs.json`:

```json
"acquisition": {
  "acquired_entity": "Target Co",
  "consideration_pct": 0.05,
  "consideration_form": "shares",
  "acquisition_timing": "concurrent_with_round"
}
```

`acquisition_timing` enum:
- `concurrent_with_round` — consideration shares are excluded from the YC SAFE Company Capitalization denominator; they dilute the SAFE via post-close fully-diluted only.
- `pre_round_closed` — acquisition stock is outstanding immediately prior; included in Company Capitalization (protects the SAFE from consideration dilution).

All three acquisition rules (`acquisition.consideration_shares`, `acquisition.pool_consideration_basis`, `acquisition.timing`) carry `counsel_review: true` — the consideration formula, pool-denominator treatment, and timing classification each require counsel confirmation before the founder relies on the computed figures. `detect_structure.py` automatically detects the acquisition block and includes `acquisition_consideration` and `priced_round` in `required_primitives`.

### Priced-round scenario parameters — counsel-reviewable

Two parameters on a `priced_round` scenario require counsel confirmation before applying:

- **`pre_money_basis`** — whether converting SAFE shares count toward the pre-money denominator. Enum: `includes_safe_conversion` (default) | `excludes_safe_conversion`. A negotiated term; do not silently apply the default and present it as the only valid convention.
- **`pool_consideration_basis`** — when a concurrent acquisition is present, whether consideration shares count toward the post-money pool-sizing denominator. Enum: `include` (default) | `exclude`. Negotiable per Cooley pricing conventions (`acquisition.pool_consideration_basis` rule).

When neither the term sheet nor the AoA settles these questions, batch them into the founder confirm gate and emit a counsel item for each.

## Workflow

### Step 0: Path Setup

**EVERY BASH CALL IS A FRESH SHELL — no variable set here survives into the next block.** This is the single most likely place a run silently drifts, because `$SCRIPTS`, `$REVIEW_DIR`, `$RUN_ID` and `$HANDOFF_DIR` do not error when they are unset: they expand to the empty string, so a path quietly becomes `/inputs.json` and a `--run-id` quietly becomes blank (which then fails compose's run_id-parity check, several steps and one sub-agent dispatch later, far from the cause). Two lines below already say this individually for `ARTIFACTS_ROOT` and `HANDOFF_AGENT`; it is true of all of them.

**So: read the printed values out of Step 0's output and paste them as literals into every later block that uses them.** Do not carry a variable forward and assume it survived. `$PLUGIN_ROOT` — and everything derived from it (`$SCRIPTS`, `$REFS`, `$SHARED_SCRIPTS`) — is resolved via `select_plugin_root.py` exactly ONCE, below: re-running that self-heal search in a later block can land on a DIFFERENT candidate mount than Step 0 picked when more than one is present (see why in the block's comments), so paste the printed `PLUGIN_ROOT` literal rather than re-deriving it. `$ARTIFACTS_ROOT` stays fine to recompute from a pasted `$SHARED_SCRIPTS` literal — once the plugin root is fixed it is a deterministic filesystem lookup with no state. `$RUN_ID` is the one exception with a different failure mode: it is minted once, below, and must stay constant for the whole engagement (compose enforces parity) — re-running that mint line in a later block re-mints a DIFFERENT value in the fresh shell and silently splits the hand-off dir mid-run. Paste the `RUN_ID` literal the block below prints instead of re-running the line that made it. What is NOT fine, either way, is referencing `$REVIEW_DIR` in Step 6 because Step 0 set it.

Optional, best-effort, and via the **Read tool** (not a shell command): before the block below, Read `${CLAUDE_PLUGIN_ROOT}/.claude-plugin/plugin.json` and note its `version` field as `EXPECT_VERSION`. Passing it to `select_plugin_root.py` below lets an exact version match win over an arbitrary first hit. If the Read fails, skip it and omit `--expect-version` — selection is still deterministic without it.

```bash
SCRIPTS="${CLAUDE_PLUGIN_ROOT}/skills/cap-table/scripts"
if [ ! -d "$SCRIPTS" ]; then
  # In Cowork, CLAUDE_PLUGIN_ROOT substitutes to a host-side path absent inside
  # the session VM — self-heal by collecting EVERY candidate mount (a session can
  # have more than one at once: a stale host-side cache, a test marketplace, even
  # a symlink into a different session's tree) and handing them to
  # select_plugin_root.py, which picks ONE deterministically and names the
  # rejects — never trust `find`'s arbitrary first hit, which can silently mix
  # scripts across plugin versions mid-pipeline.
  CANDIDATES="$(find /sessions -type d -path '*/skills/cap-table/scripts' 2>/dev/null)"
  [ -n "$CANDIDATES" ] || CANDIDATES="$(find / -type d -path '*/skills/cap-table/scripts' 2>/dev/null)"
  PROVISIONAL_ROOT="$(printf '%s\n' "$CANDIDATES" | head -1)"
  PROVISIONAL_ROOT="${PROVISIONAL_ROOT%/skills/*}"
  # Bootstrap order: $SHARED_SCRIPTS isn't known until a root is chosen, so use the
  # provisional root's OWN copy of the selector; an older plugin copy without one
  # falls back to the provisional root unchanged.
  SELECTOR="$PROVISIONAL_ROOT/scripts/select_plugin_root.py"
  if [ -f "$SELECTOR" ]; then
    if [ -n "$EXPECT_VERSION" ]; then
      PLUGIN_ROOT="$(printf '%s\n' "$CANDIDATES" | python3 "$SELECTOR" --expect-version "$EXPECT_VERSION")"
    else
      PLUGIN_ROOT="$(printf '%s\n' "$CANDIDATES" | python3 "$SELECTOR")"
    fi
  else
    PLUGIN_ROOT="$PROVISIONAL_ROOT"
  fi
  SCRIPTS="$PLUGIN_ROOT/skills/cap-table/scripts"
fi
PLUGIN_ROOT="${SCRIPTS%/skills/*}"
echo "PLUGIN_ROOT=$PLUGIN_ROOT"   # resolved ONCE, here — paste this literal into every later block; never re-run this resolution
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
echo "RUN_ID=$RUN_ID"   # prints RUN_ID — paste this literal into every later block; never re-run this mint line, or a fresh shell mints a DIFFERENT run_id and silently splits the hand-off dir mid-run
```

Reaching the self-heal branch is normal in Cowork — `${CLAUDE_PLUGIN_ROOT}` resolves to a HOST path that does not exist inside the VM, so the `[ ! -d "$SCRIPTS" ]` test fails by design rather than by misconfiguration. It is not a sign anything is wrong, and it is not worth narrating to the founder.

**Outputs mount is append-only.** Everything under the promoted outputs mount (`.../mnt/outputs/`, not just `$REVIEW_DIR`) is write-allowed and delete-denied by the platform: never `rm`, move away, or empty anything under it — **including files you created yourself**. Never create ad-hoc scratch anywhere under the outputs mount (no `_src/` copies, no run-state note files); scratch belongs in `$STAGING_DIR` (a `/tmp` dir, defined below). Do not "clean up" the outputs folder before delivering — extra working files there are expected and harmless. The uploaded document is already readable in place from the uploads mount; never copy it under outputs to make it readable.

After Step 1 (when the company slug is known), derive `REVIEW_DIR`. **Four modes** — pick exactly one:

- **Full pipeline** (default — when the founder shared a document, asked for the full review, counsel packet, or interactive explorer, OR when there's no existing full review for this slug): `REVIEW_DIR="$ARTIFACTS_ROOT/cap-table-$SLUG"`.
- **Fast-assess mode** (Phase O — short directional answer to a conversational question, no document attached, no explicit "full review" request): `REVIEW_DIR="$ARTIFACTS_ROOT/cap-table-$SLUG-fastassess"`. Run `quick_assess.py` (Step 5-fast) instead of Steps 2–11. Total wall-clock under 60 seconds.
- **Rule-lookup mode** (a bare eligibility/date question — QSBS, Israeli §102, IIA — with **no instruments to model and no document**): answer straight from the rule pack — no `REVIEW_DIR`, no pipeline. Run `verify_one.py --rule-lookup <rule_id>` (Step 5-lookup) and present its cited constant + the reliance boundary (state the date/threshold; never conclude eligibility — emit a counsel item). If it returns `lookup_status: "escalate"` (the rule carries no stored constant — e.g. the §102 capital-gains clock, which runs from a plan/trustee-specific date the pack does not hold), ask the founder for the specific fact it names (e.g. the trustee-deposit date) and treat as a counsel determination — never state a default like `grant_date`.
- **Concise mode** (a single quick **math** question that `quick_assess` can't shape and that isn't a pure eligibility lookup — a fully-diluted warrant count, an as-converted snapshot, a standalone anti-dilution adjustment, one note/SAFE outside a priced round): run the deterministic math, then render a short cited answer with `concise_report.py` (Step 5-concise) — **skip** `visualize`, `explore`, `counsel_packet`, the full `compose_report`, and the Context-B coaching sub-agent. The numbers are identical to the full pipeline's (it reads the same `run_scenario` output); only the production weight is dropped. Offer the full review as a follow-up. `REVIEW_DIR="$ARTIFACTS_ROOT/cap-table-$SLUG-concise"`.

**Slug discipline:** Use the slug returned by `founder_context.py` VERBATIM in directory names — never invent ad-hoc suffixes (e.g. appending `-seed`, `-round`, or any other qualifier). Downstream `find_artifact.py` lookups resolve by that slug; a mismatched directory is invisible to the cross-skill layer.

```bash
# Choose ONE based on the routing decision above. These are the ONLY permitted
# values — the slug-discipline rule above forbids inventing any other suffix, so
# every mode that needs a REVIEW_DIR must appear here or it cannot be built.
REVIEW_DIR="${REVIEW_DIR:-$ARTIFACTS_ROOT/cap-table-$SLUG}"                # full pipeline
# REVIEW_DIR="${REVIEW_DIR:-$ARTIFACTS_ROOT/cap-table-$SLUG-fastassess}"  # fast-assess
# REVIEW_DIR="${REVIEW_DIR:-$ARTIFACTS_ROOT/cap-table-$SLUG-concise}"     # concise
# Rule-lookup mode has NO REVIEW_DIR and writes no artifact — skip this block entirely.
mkdir -p "$REVIEW_DIR"
# Context A hand-off dir — PER RUN: sub-agents WRITE their raw extraction JSON here (the audit
# trail — raw sub-agent output as returned, before validator gating). Permanent by platform design
# (outputs/ mounts are write-allowed / delete-denied); nothing in it is ever a canonical artifact.
# The $RUN_ID segment is load-bearing: it prevents a stale prior-run file from silently passing
# the hand-off gate when a dispatch fails to write.
HANDOFF_DIR="$REVIEW_DIR/handoff/$RUN_ID"
mkdir -p "$HANDOFF_DIR"
# Sub-agents address the SAME dir by a different path (their file tools are rooted at the outputs
# mount in Cowork). Resolve the FULL agent-namespace path via the script — never hand-splice the
# printed root with a literal skill-name/slug/run-id string yourself (that string-splicing is
# exactly the non-determinism the resolver script exists to remove):
python3 "$SHARED_SCRIPTS/resolve_artifacts_root.py" --handoff-dir-agent \
  --dir-name "cap-table-$SLUG" --run-id "$RUN_ID"   # prints HANDOFF_AGENT verbatim
HANDOFF_AGENT="<printed value>"   # use verbatim in OUTPUT_PATH lines
# Ad-hoc scratch (NOT sub-agent hand-off) lives OUTSIDE the promoted outputs/ tree, in a temp dir
# that is safe to both create and clean up.
STAGING_DIR="$(mktemp -d "${TMPDIR:-/tmp}/cap-table-${SLUG}.staging.XXXXXX")"
```

**Context A hand-off protocol (file transport + gate).** Every Context A dispatch is a
`Task(subagent_type="founder-skills:cap-table", …)` call — the `subagent_type` is **REQUIRED** on the
original AND on every corrective dispatch below; omitting it silently downgrades to the wildcard,
shell-capable `general-purpose` agent (a containment defect). Every Context A dispatch prompt carries an
`OUTPUT_PATH:` line built from `$HANDOFF_AGENT` (the lane references show the exact `Task(...)`
templates). The sub-agent WRITES its extraction JSON to that path with its Write tool and returns only a
small receipt: `{"status": "complete", "output_path": "<echo of OUTPUT_PATH>"}`. The payload leaves the
model exactly once (into the Write call) — never re-type sub-agent JSON into a heredoc.

**`$HANDOFF_AGENT` and `$HANDOFF_DIR` name the SAME directory by two different paths — they are not
interchangeable.** `$HANDOFF_DIR` is the absolute VM path your shell uses (`python3`,
`check_handoff.py`, producer pipes). `$HANDOFF_AGENT` is the relative path a sub-agent's file tools
resolve against the outputs mount, and it is the ONLY one that goes in a dispatch prompt. Putting
`$HANDOFF_DIR` in an `OUTPUT_PATH` line hands the sub-agent an absolute `/sessions/...` path the
host-loop gate denies; putting `$HANDOFF_AGENT` in a shell command resolves it against the wrong cwd.
Rule of thumb: **agent namespace in prompts, shell namespace in bash.**

**The receipt is the ONE exemption from the never-re-type rule.** "Never re-type" governs the
*payload* — the extraction JSON, the coaching commentary, anything the founder's numbers pass
through. The receipt is a two-field acknowledgement the sub-agent returns in its final message, and
reading `output_path` out of it to pass to `check_handoff.py --agent-path` is expected, not a
violation. If it were forbidden, the hand-off could not be gated at all.

**Path idiom for dispatch prompts (host-loop path gate):** `OUTPUT_PATH` and any under-outputs artifact
READ path a sub-agent is given are **relative to the sub-agent's file-tool cwd** (the outputs mount) —
built from the `resolve_artifacts_root.py --agent` namespace (`$HANDOFF_AGENT`, or the equivalent
agent-namespace path for any other under-outputs artifact a dispatch prompt reads). Never hand a
sub-agent an absolute `/sessions/...` path for a file-tool Read/Write — the host-loop path gate denies
it (steering shell work to the `bash` tool instead). Bundled `references/*.md` are the one exception:
pass them as the literal `${CLAUDE_PLUGIN_ROOT}/skills/cap-table/references/...` token (it is
pre-resolved to a host-readable path); do NOT substitute a `find /sessions`-discovered `$REFS` (a shell
path a file tool can't read).

After EVERY Context A dispatch, gate before piping (`<step>` = the dispatch's file stem):

```bash
printf '%s' '<agent final message verbatim>' | \
  python3 "$SHARED_SCRIPTS/check_handoff.py" "$HANDOFF_DIR/<step>_output.json" \
    --agent-path "$HANDOFF_AGENT/<step>_output.json" --receipt-json -
```
<!-- skill-quality-ci: bash-after-subagent-ok -->

Branch on the exit code (complete state machine — do not improvise). *Every corrective **redo-dispatch**
/ **repair-dispatch** below is a full `Task(subagent_type="founder-skills:cap-table", …)` — a "fresh
Task, same prompt" must carry the `subagent_type`; dropping it on a retry is the same containment defect
as omitting it originally:*

- **Exit 0** → pipe the file through the validator (`cat "$HANDOFF_DIR/<step>_output.json" | python3 "$SCRIPTS/<validator>.py" ...`).
- **Exit 3** (missing/empty file — receipt may be fabricated) → **redo-dispatch**: fresh Task, same prompt plus one line: "your receipt claimed a file at `<path>` but none exists; use Write to create exactly that path."
- **Exit 4** (file exists, invalid JSON) → **repair-dispatch**: fresh Task: "Read `<OUTPUT_PATH>`; it fails JSON parsing with `<verbatim detail>`; fix and rewrite it; return the receipt."
- **Exit 5** (receipt echoes a different path) → **repair-dispatch** with the exact expected OUTPUT_PATH.
- **Exit 6** (receipt unparseable / no `output_path` key) → **redo-dispatch** with "return ONLY the receipt JSON — no fences, no prose."
- **Validator schema rejection** (the pipe fails next) → **repair-dispatch** with the validator's stderr verbatim. (Evidence-verifier rejections keep their OWN lane-specific protocol — `retry_hint` re-dispatch — which is a content correction, not a transport correction, and does not consume the transport retry budget.)
- **Any other exit** (script crash etc.) → STOP with the stderr.
- **After ANY corrective dispatch, resume from `check_handoff.py`** — never pipe unchecked.

**Retry budget:** max **2 corrective transport dispatches per step, of any kind** (max 3 total).
After the second corrective dispatch fails any gate: STOP and report the exact diagnostic. The main
thread MUST NOT author or patch extraction content itself — that is the fabrication failure mode
this architecture exists to prevent. A `status: "blocked"` return is bounded separately: at most
ONE input-fix re-dispatch per step; a second blocked return STOPs with both reasons quoted.

**Graceful degrade (fleet heterogeneity):** if the FIRST corrective dispatch also exits 3 while the
agent's receipt claims `complete` with the correctly echoed path, treat the host's filesystem
topology as hand-off-incompatible: fall back to message-channel transport for the REST of this run
(sub-agent returns full JSON in its final message; apply the tolerant JSON extraction protocol;
stage to `$STAGING_DIR/<step>_input.json`; same validator pipe), and note the fallback in your
final summary.

Retries overwrite the same OUTPUT_PATH (the mount is write-allowed / delete-denied — never `rm`
under `$REVIEW_DIR`). Hand-off files are not canonical artifacts: validators consume them only via
the explicit pipe, and `compose_report.py` never reads `handoff/`.

**Routing heuristics.** In order: (1) a **bare eligibility/date question** (QSBS, §102, IIA) with no instruments and no document → **rule-lookup** (Step 5-lookup) — a cited fact, not a pipeline run. (2) A **single quick math question** that `quick_assess` can't shape (warrant fully-diluted count, as-converted snapshot, standalone anti-dilution, a lone note/SAFE outside a priced round) → **concise mode** (Step 5-concise) — the real math, short answer, no heavy tail. (3) A **priced-round gut-check** / first-touch conversational answer (no document, no "full review"/"counsel packet"/"report"/"explorer"/"deep dive") → **fast-assess**. (4) Otherwise → **full pipeline**. If an existing `cap-table-$SLUG/report.json` is present, ask via `AskUserQuestion` whether to use it or start fresh. **Extraction-only is NOT a route you select here.** A single uploaded instrument still routes to (4) full pipeline; the extraction-only path is entered ONLY via the Step-2 no-cap-base fork, after extraction has confirmed there is genuinely no equity base. Never choose extraction-only at Step 0 — nothing has been extracted yet, so "no base" cannot be known, and routing to it here would skip the fork that lets the founder supply a base they do have.

**Artifact-worthy boundary (write the sentinel).** If your answer presents a founder-facing ownership/dilution **table** or a **post-financing ownership %**, you MUST run a script-backed path — `quick_assess` (fast-assess; writes the `fast_assess_only.json` sentinel + `report_fast_assess.md`), `concise_report` (concise mode; writes the real `cap_state.json` + `scenarios.json` + `report_concise.md`), or the full pipeline — do NOT hand-build such an answer in chat. A one-line directional aside while gathering inputs (e.g. "≈20% to new investors") is fine in chat and writes no artifact. This keeps any quantitative ownership answer backed by the script + sentinel, so downstream consumers can detect that cap-table ran.

### Step 1: Read or Create Founder Context

```bash
python3 "$SHARED_SCRIPTS/founder_context.py" read --artifacts-root "$ARTIFACTS_ROOT" --pretty
```

**Exit 0 (found):** Use the company slug and pre-filled fields. Proceed to Step 2.

**`W_SECTOR_TYPE_UNKNOWN` is benign for cap-table engagements.** If `founder_context.py` emits a `W_SECTOR_TYPE_UNKNOWN` warning (triggered by free-text sectors such as "technology"), proceed — `sector_type` is not read by any cap-table rule or script, so this warning has no effect on cap-table math or counsel-review gating. Do not re-prompt the founder just to resolve it.

**Exit 1 (not found):** Expected on a first run — do NOT mention this check or its exit status to the founder; if you narrate anything first, say only "Let me grab a few basics about the company." Use `AskUserQuestion` (NOT plain chat) to ask for company name, stage, sector, and geography — the Gate Catalog rows *Company name*, *Company stage*, *Sector*, *Geography* below give the phrasing and option shape for each (stage is a fixed 4-label set; name/sector/geography are runtime-labelled — an affirmative option carrying whatever was derived from the conversation or materials, plus a stated-value fallback). **Carry the stage into `inputs.metadata.stage`** — stage-scoped benchmarks read it there, and withhold rather than guess when it is absent. Then create:

```bash
python3 "$SHARED_SCRIPTS/founder_context.py" init \
  --company-name "Acme Corp" \
  --stage <pre-seed | seed | series-a | series-b | series-c | series-d | later> \
  --sector "B2B SaaS" \
  --geography "US" --artifacts-root "$ARTIFACTS_ROOT" \
  --run-id "$RUN_ID"
```

**Exit 2 (multiple):** Present the list, ask which company, re-read with `--slug`.

#### Execution checkpoint — END OF STEP 1, READ BEFORE CONTINUING

You now have enough to route. **Invoking this skill is not the same as running it.** Cap-table has the
sharpest version of that risk in the fleet, because the arithmetic here looks easy. Post-money is pre plus raise;
the investor's share is the raise over post. A model can produce a confident dilution answer in one turn
without opening a single script — and a founder will take that number into a negotiation.

**Every number that reaches the founder comes out of a producer.** There are four modes and all four run
something:

- **Full pipeline** — `run_scenario.py` and the rest.
- **Fast-assess** — `quick_assess.py`. Under 60 seconds, still a real calculation.
- **Concise** — the real solver, then `concise_report.py`.
- **Rule-lookup** — `verify_one.py --rule-lookup`, which returns the cited constant and its reliance
  boundary.

There is no fifth mode where you do the arithmetic yourself. If a question seems too small for any of
these, it is a **rule-lookup** or a **fast-assess**, not a mental calculation.

- **Never compute a figure in chat.** Not ownership, not dilution, not a post-money, not a share count,
  not a price per share — not even the one-line ones. A hand-computed cap-table number has no rule citation, no gotcha check, no
  audit trail, and no artifact — and it is indistinguishable, to the founder, from one that has all four.
- **Never benchmark against a figure you recalled.** And never state a cap-table rule from memory. Every rule has an id in the rule pack and `verify_one.py`
  will cite it. "Pools are usually carved out pre-money" is exactly the kind of usually that is wrong for
  a specific term sheet.
- **Splitting an aggregate the producer emitted is still computing in chat.** Apportioning the founders'
  block by pre-round ratios to give each founder a post-round number is arithmetic you did, not output you
  read, and a disclosure like *"(split proportionally within the founders' 63.3% block)"* does not convert
  it into one. It is also the number a founder is most likely to quote in a partner conversation.
  **You no longer have to decline the question.** A priced round now emits per-holder post-round ownership
  at `scenarios[n].computed_outputs.aggregate_ownership_by_class.founders_by_holder` (keyed by
  `founder_id`, carrying `name`, `common_shares`, and `pct`), and `report.md` renders it under
  *"each founder, post-round"*. **Read those figures; never derive them.** Two boundaries still hold: the
  map is absent on a scenario the solver rejected (say so rather than reconstructing it), and it covers
  `founders[]` only — a holder whose shares sit in `common_batches[]` is in the totals but not broken out,
  so do not present the list as every shareholder.
- **A what-if, a sensitivity illustration, or "roughly what would X give" is NOT an exemption.** This is
  the most natural request in cap-table — *"what if the pool were 15%?"*, *"what if we raised 3M
  instead?"* — and it is where the temptation is strongest, because the delta feels like small
  arithmetic on a number you already produced properly. It is not: the same solver coupling that makes
  the first number non-trivial applies to the second. **re-run the producer with the alternate input**
  and quote its output, or **give no number** and say which direction it moves. Never arithmetic in
  prose. The explorer's sweep exists for exactly this.
- **Never offer the real run as an opt-in after answering.** "Here's the rough math — share your cap table
  if you want the full picture" is the failure, not the courtesy. The founder cannot tell that what they
  just read was not the analysis.
- **If you are blocked, say BLOCKED and say why.** A missing instrument, an unreadable document, an
  ambiguous term — name it and stop.

Artifact existence is the proof of execution: if no artifact was written, the skill did not run, whatever
the transcript says.

### Step 2: Confirm Engagement Mode + Jurisdiction → `inputs.json`

Ask the founder via `AskUserQuestion` (NOT plain chat). **Take all three question texts and option labels from the Gate Catalog rows below, verbatim and in the row's order** — they are deliberately not repeated here, because a second copy is exactly what drifted last time. The arrows map each row's labels, in order, onto the enum written to `inputs.json`:

1. **Mode** — row *Engagement mode* → `standard | flip_focused`.
2. **Jurisdiction structure** — row *Jurisdiction structure* → `israeli | delaware | mid_flip | delaware_with_israeli_sub`.
3. **IIA grant history (Israel-context only)** — row *IIA / OCS grants* → `no | yes | not_sure`.

Then build `inputs.json` via heredoc. The skeleton below is the **minimal** shape (no founders, no pool, no preferred) — useful only for flip-focused engagements that read existing artifacts. **For any engagement where someone owns shares, also include `founders[]` and `option_pool` blocks.** **Exception — Lane 3 (freeform spreadsheet):** write the **minimal** shape (company meta only, NO `founders[]` / `option_pool` / `preferred_series`); `extract_cap_table.py --mode=freeform-emit` fills those equity sections from the sheet and would otherwise conflict with seeded placeholders. See [`references/inputs-skeleton.md`](references/inputs-skeleton.md) for the full common-case shape, the validator-strictness gotcha (unknown keys are silently dropped), and the plan_type / OIP-OCP-CCP field meanings.

**If the host tells you to collect input another way, this gate still uses `AskUserQuestion`.** Cowork's own prompt guidance steers skill ARGUMENT COLLECTION toward an elicitation widget and away from `AskUserQuestion`; that guidance is about gathering arguments, and this is not that. S2 is a correctness control — it confirms the skill's INTERPRETATION of the founder's numbers before any math binds to them, and a mis-mapped holder caught here is a wrong report avoided. A batched `AskUserQuestion` is what makes the options explicit and the answer auditable, so prefer it for every mandatory gate in the Gate Catalog. If `AskUserQuestion` is genuinely unavailable in the host, do NOT skip the gate and do NOT assume the base: ask the same question in plain chat, state the options, and wait for an explicit confirmation before running math. (This precedence applies to every skill's mandatory gates, not only cap-table's.)

**MANDATORY cap-base confirmation gate (S2).** Before any FULL-pipeline math on an engagement where someone owns shares (Lanes 1/2/4), the founder cap base — each founder + common share count, and the option pool (authorized / issued / unallocated) — MUST be founder-confirmed via one batched `AskUserQuestion` (same rule as Lane 2). Raise this gate EVEN when the founder states the full base inline — it confirms your INTERPRETATION of their numbers (which founder owns which class, the pool split), catching mapping errors before downstream math binds to them; do NOT treat inline-stated data as pre-confirmed. NEVER assume founder share counts or pool silently, and never use generic placeholder names like `Founder A` / `Founder B`. Set `metadata.cap_base_source = "confirmed"` once confirmed. `cap_state.py` defaults to ASSUMED: it emits `W_CAP_BASE_ASSUMED` on any engagement with an equity base UNLESS `cap_base_source = "confirmed"` — so you must affirmatively set `"confirmed"` to suppress the directional caveat (the compliance burden is on the safe side). (Lane 3 is exempt — the freeform emit stamps `cap_base_source = "confirmed"`, since the base is extracted from the founder's own spreadsheet.) **Provenance:** when you hand-build `inputs.json` directly (Lanes 1/2/4 — a PDF/Carta read, a manual rebuild, or pasted data the deterministic freeform mapper did not produce), also set `metadata.cap_base_provenance = "model_reconstructed"`. The freeform emit auto-stamps `cap_base_provenance = "deterministic_mapped"` — do NOT override it. `cap_state.py` emits `W_CAP_BASE_RECONSTRUCTED` for any `confirmed` base that is not `deterministic_mapped`, so a hand-built base is flagged as not-mechanically-verified even when confirmed.

**No-cap-base fork (standalone instrument).** If, after extraction, the upload is a single financing instrument (SAFE/note/term sheet/option plan) with NO equity base anywhere — none of `founders[]`, `option_pool`, `preferred_series`, or `common_batches` — then `cap_state.py` cannot run (it hard-errors `E_NO_EQUITY_BASE`), the cap-base confirmation gate has nothing to confirm, and `rule_audit.py`/`run_scenario.py`/`compose_report.py` are all unusable (each requires `cap_state.json`). Raise ONE `AskUserQuestion` — the **No-cap-base fork** gate (canonical phrasing below) — offering the founder a choice: provide the cap base for a full review, or proceed with an instrument-terms-only extraction. **Carry the material extraction findings INTO this gate message.** This gate can END the
engagement: a founder who picks neither option — or who stops here to go fetch their cap table — may
never see a report at all. So state, in the gate message itself, before the options:

- **Any field that is blank or absent in the document but BINDING if signed** — an exclusivity /
  no-shop period, confidentiality, a standstill. Name the field and say it is blank. NEVER supply a
  plausible value for it, and never let the blank pass silently because the number is missing.
- **Any `ambiguities[]` entry** the extraction flagged for confirmation.

Same reasoning as the tracked-changes gate above, which is the PRIMARY draft caveat precisely because it
reaches a founder whose engagement never builds a cap base. A finding that exists only in
`extraction_audit.json` has not reached the founder. Concretely: a term sheet whose exclusivity clause
reads "During a period of ___ days" is a binding restriction of unknown length — that is the single most
important thing to say, and it must not be displaced by the request for cap-base data.

**This fork is mandatory — do NOT silently choose extraction-only**, because "no base found" can also mean the base failed to extract (e.g. an image-only PDF the vision path missed), and the founder must get the chance to supply a base they actually have. On **provide the cap base**: collect founders + pool and continue the full pipeline. On **instrument terms only**: run the extraction-only renderer —

```bash
# --audit surfaces the extract_instrument receipt. For a term sheet / option plan / amendment the
# receipt IS the founder-facing content (a "Term sheet terms (as extracted)" / "Amendments" section),
# so for those doc types you MUST save that receipt to "$REVIEW_DIR/extraction_audit.json" (its -o output)
# and pass --audit — without it the report is empty. A Lane-2/3 pass also writes this file.
# For a pure SAFE/note the file may be absent; the renderer degrades gracefully.
# POSIX sh: use "$@" for the optional flag (the workspace shell is /bin/sh, not bash — no arrays).
set --
[ -f "$REVIEW_DIR/extraction_audit.json" ] && set -- --audit "$REVIEW_DIR/extraction_audit.json"
python3 "$SCRIPTS/compose_extraction_report.py" \
  --inputs "$REVIEW_DIR/inputs.json" \
  --instruments "$REVIEW_DIR/instruments.json" \
  --review-dir "$ARTIFACTS_ROOT/cap-table-$SLUG-extraction" \
  "$@" \
  --run-id "$RUN_ID" --pretty
```

— which writes `report_extraction_only.md` (an instrument-terms report carrying a prominent "instrument terms only — no cap base modeled" banner), the `extraction_only.json` sentinel, and `coverage_disclosure.json` (`computation_method: "extraction_only"`), and does NOT invoke `cap_state.py`/`rule_audit.py`/`compose_report.py`. To cite a specific rule for the instrument without the pipeline, use `verify_one.py --rule-lookup <rule_id>`.

**Then jump to Step 12, extraction-only branch.** `report_extraction_only.md` is this route's ONLY deliverable — finishing without handing it over leaves the founder nothing. Its source dir is `$ARTIFACTS_ROOT/cap-table-$SLUG-extraction`, **not** `$REVIEW_DIR`.

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

**`incorporated_date` in the skeleton above is a PLACEHOLDER, not a default.** A live run copied `2024-06-01` straight out of this example for a company whose founder never stated an incorporation date, and then drove a QSBS holding-period counsel item off it. **If the founder has not told you the date, delete the `incorporated_date` line entirely** — the field is optional (`jurisdiction` has no `required` array), so omitting it is schema-valid, while `null` is NOT (the field is typed `string`). Ask for it via a founder-only fact gate when the engagement touches QSBS or §102 timing; otherwise omit and say you omitted it. **Never carry the example date through** — a fabricated legal date is worse than an absent one, exactly as with `issuance_date`.

**`founders[]` and `option_pool` are required for any engagement with shares.** The schema marks them optional. When the equity base is absent entirely — none of `founders[]`, `option_pool`, `preferred_series`, or `common_batches` present — while instruments exist, `cap_state.py` hard-errors (`E_NO_EQUITY_BASE`, exit 1) rather than computing an all-zero base into which conversions would divide (an empty `option_pool: {}` counts as absent; a declared pool or any preferred/common batch counts as present). A single uploaded instrument (a SAFE/note) with no surrounding cap base is the expected case for this — it takes the **no-cap-base fork** in Step 2 below, not the full pipeline. Read `references/inputs-skeleton.md` if your scenario has preferred series, `common_batches`, or non-standard option-plan jurisdictions.

**`metadata.schema_version` is required** on `inputs.json` (`"v0.5.0-inputs"`), `instruments.json` (`"v0.5.0-instruments"`), and `cap_state.json` (`"v0.5.0-cap-state"`). Producer scripts inject the value when they write; founder-supplied heredoc inputs must include it explicitly or `extract_cap_table.py --mode=validate` rejects with `E_SCHEMA_VERSION_MISMATCH`. Common field-name gotchas: `preferred_series[].shares` (not `shares_outstanding`); `preferred_series[].series_name` (not `series_label`); `preferred_series[].liquidation_preference_type` (not `participation`); `founders[].common_shares` (not `shares`). **`issuance_date` is required as a KEY but its allowed VALUES differ by instrument type** — the distinction is not guessable from the skeleton, which shows a real date everywhere. On `safes[]` and `convertible_notes[]` the type is `["string", "null"]`: when the founder has not given a date, write `null` — never a fabricated one. On `warrants[]` it is `"string"` only, so `null` is INVALID there and a real date must be obtained. One math consequence to disclose when you write `null` on a note: `cap_state.py` demotes a note with no usable date to non-convertible (terms recorded, conversion not modeled), so the founder should know the note is being carried but not converted. `preferred_series[]` lives in `inputs.json`, NOT `instruments.json` — the instruments schema has no `preferred_series` key; an unknown top-level key in `instruments.json` is silently dropped rather than rejected, so there is no schema error to catch the mistake.

**`option_pool.plan_type` enum:** `iso` | `nso` | `section_102_cg` | `section_102_oi` | `section_3i` | `mixed`. The Israeli §102 capital-gains track is `section_102_cg` — there is no `"israeli_102"` or `"102_cg"` value; those fail validation. See `references/inputs-skeleton.md` for the jurisdiction-to-plan_type mapping table.

**Omit unknown optional fields rather than writing `null`, EXCEPT fields the skeleton explicitly shows as `null` — those are schema-nullable (`["string","null"]` or `["number","null"]`) and keeping them as `null` is correct.** Most other schema fields are typed non-nullable (e.g., `jurisdiction.incorporated_date` is `string`, not `string | null`); writing `null` for those fails validation. Fields shown in the Step 2 skeleton with values are either required or strongly recommended. `jurisdiction.incorporated_date` matters for §102/QSBS date math — **ask the founder for it via a founder-only fact gate rather than omitting, if the engagement touches those. If they do not know it, OMIT the key and say you omitted it — never write a plausible date, and never keep the skeleton's example value.** The same never-fabricate rule as `issuance_date`: a made-up incorporation date silently drives a QSBS holding-period conclusion a founder may act on, and a live run did exactly that by copying the skeleton's date. Omission is schema-valid here (`jurisdiction` has no `required` array); `null` is not.

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

**Lane 1 invocation pattern** — after gating the sub-agent's hand-off file per the Context A
hand-off protocol (Step 0), pipe it through `extract_instrument.py` like this:

```bash
cat "$HANDOFF_DIR/<doc_slug>_extraction_output.json" | python3 "$SCRIPTS/extract_instrument.py" \
  --instruments "$REVIEW_DIR/instruments.json" \
  --source-doc "$SOURCE_DOC_PATH" \
  --run-id "$RUN_ID" -o "$REVIEW_DIR/extraction_audit.json" --pretty
```
<!-- skill-quality-ci: bash-after-subagent-ok -->

`extract_instrument.py` reads the sub-agent JSON from **stdin** and updates `--instruments` **in place**. The `-o/--output` flag writes a JSON receipt confirming the write (does not change where instruments are stored) — **always pass it, in the full pipeline too, not only the no-cap-base fork below.** For a `term_sheet` / `option_plan` / `amendment` this receipt is the ONLY place that document's content lives (their `fields` never enter `instruments.json`): `compose_report.py` reads `extraction_audit.json` when present and renders a "Term sheet terms (as extracted)" / "Amendments (terms modified)" section, so the content still reaches the delivered `report.md` even on an engagement that otherwise has a real cap base. If the id already exists in the target array you'll get `E_DUPLICATE_INSTRUMENT_ID`; re-run with `--replace` to overwrite the existing entry instead. Multiple Lane-1 documents in one engagement share this single file — a second `-o` call overwrites the first's receipt (same limitation as the no-cap-base fork's `--audit`, not new here).

**Dispatch independence rule (CRITICAL):** the sub-agent dispatch prompt for `INSTRUMENT_EXTRACTION` contains the document text and the GENERIC extraction rules only. NEVER include per-document hints, expected values, or pre-decided classifications in the dispatch prompt (e.g. "this doc's form is cap_plus_discount", "use issuance_date 2024-01-15") — the sub-agent's reading must be independent. The verification stack (`evidence_verifier.py` → `invariant_checker.py` → `cross_checker.py`) exists to catch divergence; a led witness cannot diverge. Generic normalization rules (e.g. '"Discount Rate is 80%" means multiplier 0.80') are field semantics, not per-document answers — those belong in the dispatch prompt.

**Verification stack** (Lane 1 and any other lane that piped through `extract_instrument.py`): forward `evidence_verifier.py` → `invariant_checker.py` → `cross_checker.py` → optional `backward_verifier.py`. All default-on; see the Lane 1 reference for the receipt schema, `attention_needed_fields` semantics, and when to run backward verification.

### EXTRACTION CONFIRM-GATE (MANDATORY)

**Trigger.** Extractor warnings that say "confirm with note text" or "confirm with founder" are a **QUESTION GATE** — not suggestions. After any extraction (Lane 1, 2, or 3), scan all warnings for any field flagged as assumed or left null (e.g. `qualified_financing_threshold`, `maturity_default_treatment`, `interest_converts_to_shares`, `interest_rate_type`, `capitalization_denominator`).

**Required action.** Batch ALL such fields into ONE `AskUserQuestion` call and get the founder's answers before running any math. NEVER fill them with "standard assumptions" and proceed silently. Two of these fields have real closed enums with catalog phrasing — use the Gate Catalog rows *Interest rate type (note)* and *Interest converts to shares (note)* verbatim rather than improvising labels; `maturity_default_treatment` and `capitalization_denominator` are already catalogued as *Note maturity default* and *Note "Company Capitalization" denominator*. Any remaining assumed/null field in the batch is founder-specific data — shape it per the *Founder-only fact gates* row (a stated-value option plus an explicit defer). If the founder cannot confirm a field, you MUST:
- (a) name the assumption explicitly in the final presentation (e.g. "interest rate type assumed fixed simple — confirm with note text");
- (b) emit a counsel item flagging it.

**Special cases.**
- The denominator field (`capitalization_denominator`) requires special care: its definition comes from the note's "Company Capitalization" clause and is note-text-specific — do not default to the cap_state fully-diluted count.
- `non_qualified_financing_treatment: convert_anyway` means convert at cap/discount even though the round missed the qualified financing threshold — there is no separate `convert_at_cap` enum value for this field.

**Exception — blank/template fields (relaxed gate).** If a required field is absent because the source is an unfilled template (or the value lives in a companion doc, e.g. a note principal in a Schedule of Lenders) AND the founder cannot supply it, proceed-degraded instead of stopping — WITHOUT fabricating a value:
1. Leave the field `null`, set its `confidence` entry to `{"level": "absent"}`, and add an `ambiguities` entry naming it (see `references/lanes/lane-1-pdf-docx.md`). A null WITHOUT `level: "absent"` still hard-errors; relaxable fields are SAFE `purchase_amount` / `issuance_date` / `investor_name` and note `principal` / `issuance_date` / `investor_name` / `maturity_date` / `maturity_default_treatment`. The instrument persists as a partial (`completeness: "partial"`, a `W_FIELD_ABSENT_IN_DOC:<field>` warning) and is recorded terms-only / non-convertible when the absent field is math-consumed (`purchase_amount` / `principal`).
2. Present the extracted terms in the report, rendering each absent field as "not stated in document; confirm" (never a fabricated stand-in), and state that conversion math for that instrument requires the missing amount.
3. When the founder later supplies a value, re-dispatch the corrected extraction **reusing the same `id` and passing `--replace`** — do NOT let it append a fresh-id duplicate (the duplicate-content guard cannot detect a re-pipe whose fields were null).

Do not end the turn on the question for a blank template; raise `AskUserQuestion` as the primary path, shaped per the Gate Catalog's *Founder-only fact gates* row, but use proceed-degraded when the founder confirms the amount is not yet available. When you present the extracted terms and stop (no math), end with: "If you'd like the full cap-table review — saved artifacts, dilution scenarios, and a counsel packet — just say 'review my cap table' or 'model the round'."

### SOURCE-OVERRIDE DECLARATION (MANDATORY)

**Trigger.** Distinct from a null/assumed field: whenever you treat a value the source actually STATES as wrong, superseded, or a formula artifact — or make any non-obvious judgment that CHANGES the numbers. Examples:
- "the Convertibles sheet's outstanding column is a formula error, so these SAFEs are already converted";
- "ignored row N as a sum/subtotal artifact";
- "reinterpreted negative-price cells".

**Required action.** You MUST:
- (a) name the override explicitly in the final presentation ("treated X as Y because Z — confirm against the source") AND flag it there as an explicit assumptions/diligence caveat;
- (b) include it in the cap-base confirmation gate so the founder confirms the INTERPRETATION, not just the resulting numbers.

**Not a substitute path.** Do NOT expect to "add a counsel item" for it — `counsel_packet` items are rule-pack-generated from matched rules; the model cannot author one. The override's home is the report narrative's assumptions/caveats + the confirm gate, both of which you DO control. A confident reinterpretation baked silently into a `confirmed`, zero-warning base is the failure this prevents — never let a judgment call disappear into clean-looking output. (This is an instruction, not a script gate; `W_CAP_BASE_RECONSTRUCTED` already flags a hand-built base as model-reconstructed, but it does not name the specific override — that naming is on you here.)

**Freeform `discount` is NOT a confirm-gate field.** A freeform spreadsheet `discount` column is governed by the deterministic rate convention (`references/schemas/freeform-role-map.json` `discount_convention`: a value like `0.20`/`20` is a 20% RATE → multiplier `0.80`; multiplier-form input is unsupported). The producer's resulting conversion `warning` is a TRANSPARENCY note — surface it in the final presentation (see the Lane-3 reference's `ok:true` step), but NEVER raise a rate-vs-multiplier `AskUserQuestion` for it: the convention already decided it is a rate. (Genuinely out-of-range values — `> 100` or `≤ 0` — still surface as blockers, which is a different path.)

**Freeform multi-snapshot column self-check (Lane 3).** A founder's spreadsheet often has several date columns representing successive closing snapshots (e.g. "Seed closing", "Bridge closing", "Current"). When the `SPREADSHEET_STRUCTURE_DETECTION` dispatch identifies more than one snapshot or closing column, you MUST do both of the following in the confirm-gate before any math runs: (a) **name the column you used** as the current/outstanding share count — state it explicitly (e.g. "I used the 'Current' column dated 2025-03-31 as the outstanding share count"); and (b) **cross-check your per-holder sums** against that column's printed subtotal or total cell for each series — if the sheet shows a "Total Preferred" or "Fully Diluted" cell for that column, sum the holders you mapped and compare; surface any mismatch in the confirm-gate (e.g. "My mapped holders sum to 4,800,000 preferred shares; the sheet's total cell shows 5,000,000 — please confirm which holders I may have missed"). This is an LLM-process self-check, not a deterministic guarantee; the goal is to catch a missed holder or misread column before the math binds. If the sheet has no printed total cell for the chosen column, note that the cross-check was not possible. **Stated-total stamp (both Lane-3 paths):** whenever a same-basis printed grand fully-diluted total is available (pool-inclusive, as-converted — e.g. a "Total Fully Diluted"/"TFD" cell for the chosen column), stamp it into `inputs.stated_totals` so `cap_state.py` can cross-foot the rebuilt cap base and emit `W_FD_RECONCILE_DELTA` if they diverge — mirroring Lane 2 (`carta_summary`) and the OCR path. Two paths: (a) **freeform-emit path** — include `stated_total: <n>` at the top level of the `SPREADSHEET_STRUCTURE_DETECTION` response JSON (the mapper carries it through `--mode=freeform-emit` into `inputs.stated_totals` mechanically); (b) **direct-build path** (mapper bypassed, `inputs.json` assembled by hand from the grid) — write `"stated_totals": { "fully_diluted": <n>, "source": "freeform_grid" }` into `inputs.json` directly. **Basis-match rule (prevents false positives):** stamp ONLY a total that is explicitly fully-diluted and pool-inclusive; omit the stamp when the sheet's grand total is labeled "Issued"/"Outstanding" (pool-excluded), is as-issued rather than as-converted, or the basis is ambiguous — a wrong-basis stamp fires `W_FD_RECONCILE_DELTA` on a correct sheet (a cry-wolf warning is worse than no warning). Better no cross-foot than a false positive. Non-circularity: use only a total the sheet itself prints; never a sum the skill computed.

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

**Scan `cap_state.json.warnings[]`.** A `W_ANTI_DILUTION_NONCANONICAL` / `W_ANTI_DILUTION_UNRECOGNIZED` warning means a founder's anti-dilution intent was written under a non-canonical key (e.g. `anti_dilution` / `bbwa`) and was recovered (or flagged) rather than silently dropped — the report renderers now surface it, but you MUST also confirm the recovered term with the founder before relying on the down-round math (it changes the conversion).

**Closing action — detect coverage before the pre-math audit.** Instruments are committed by Step 3, so run `detect_structure.py` → `coverage_result.json` here (it reads `inputs.json` + `instruments.json`, not `cap_state.json`), and populate `scenario_requests.json` from `route.scenario_requests` when `covered: true`. See `## Coverage & Disclosure` above for the full contract and the hand-rolled-figure ban — never let a deal reach Step 4.5 without this check.

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

**Never assume a pool top-up — and never assume its basis.** Pass `--target-pool-percent X --target-basis <pre_money|post_money>` ONLY when the founder stated a pool target (or confirmed one when you asked), and pass the basis they actually stated — `--target-basis` is NOT always `post_money`; a term sheet just as often sizes the pool pre-money. If the founder gave a percent without saying which denominator, add it to the same batched `AskUserQuestion` below rather than defaulting silently. Otherwise run WITHOUT those flags — the report then carries an explicit "No pool top-up modeled" note, and you offer the 10% what-if as a follow-up re-run. A silently assumed pool target — or a silently assumed basis — materially changes the founder's headline ownership; both are the founder's negotiation variables, not yours.

Inputs are built from the founder's conversational description via `AskUserQuestion` (Lane 4 only — fast-assess does NOT invoke Lane-1/2/3 extractors). **Do not skip the question gate, and do not split it:** batch everything still missing into ONE `AskUserQuestion` call before running — typically jurisdiction structure (Gate Catalog row *Jurisdiction structure*, if not obvious), IIA/OCS grant history (Gate Catalog row *IIA / OCS grants*, Israeli companies), and pool-target intent. **The catalog's *Pool top-up intent* row covers whether/how-much (post-money only, 4 labels — pre-money and post-money together would exceed the tool's 4-option max); it does NOT cover basis.** If the founder picks a top-up amount, ask basis as a second question in the SAME batched call rather than defaulting silently — the paragraph above states why a silently assumed basis materially changes their headline ownership.
Options: `Pre-money` / `Post-money` / `Not sure — use post-money`

If the founder's message already supplied everything, ask nothing and run. When you present the result, state in one line any flag choices that encode an assumption (e.g. "modeled with no pool top-up" / "modeled with the 10% post-money pool you mentioned"). The script writes:

- `${REVIEW_DIR}/fast_assess_only.json` — sentinel for downstream consumers
- `${REVIEW_DIR}/report_fast_assess.md` — 1-page founder-facing markdown

**Read `report_fast_assess.md` and present its numbers verbatim to the founder — never re-derive or reconstruct the ownership table in chat.** If you computed preliminary estimates while gathering inputs, discard them in favour of the script output. The script is the authoritative source; hand-reconstructed math will diverge from the fixed-point solver result. This includes the dilution explanation — use the share counts from the report; never re-derive top-up or conversion shares by hand. For what-if follow-ups (e.g. "what if we top up the pool to 10%?"), re-run `quick_assess.py` with the changed flag and present the new report — never estimate the answer by hand.

**Full-pipeline what-ifs (applies to both fast-assess and full reviews):** the `explorer.html` displays only precomputed scenarios (plus, when `sweep.json` exists, a pre-money slider that scrubs precomputed real solver frames — also not hand-estimated). For any scenario not yet modeled, write a new scenario request and re-run the full pipeline:
1. Add the new scenario to `scenario_requests.json`
2. Re-run `run_scenario.py` → `rule_audit.py --phase=post_math` → `compose_report.py`
3. Present the updated `report.md` numbers verbatim
Never hand-estimate a new scenario in chat.

Total wall-clock: under 60 seconds. Then jump to **Step 12: Deliver Artifacts** with the fast-assess deliverable. Close with a STATEMENT offering the next step, not a trailing question (a final turn ending in a bare "?" with no tool call is a stall) — e.g. "That's the directional answer. If you'd like the full cap-table review — saved artifacts, dilution scenarios, and a counsel packet — just say 'review my cap table' or 'model the round'."

### Step 5-lookup (RULE-LOOKUP MODE ONLY): Run `verify_one.py` and exit

For a bare eligibility/date question (QSBS, Israeli §102, IIA) — no instruments, no document — answer from the rule pack instead of running the pipeline. Pick the rule that holds the relevant fact and run:

```bash
python3 "$SCRIPTS/verify_one.py" --rule-lookup delaware_cross_border.qsbs_date_sensitive --pretty
```

- **`lookup_status: "answered"`** — present the `answer` (the cited constant + its primary source) and the `reliance_boundary` verbatim-in-spirit: state the date/threshold, then stop. Never conclude eligibility; emit a counsel item (the rule carries `counsel_review: true`).
- **`lookup_status: "escalate"`** — the rule holds no stored constant (e.g. `israel_equity_tax.section_102_capital_gains`, whose clock runs from a plan/trustee-specific date the pack does not store). Do **not** state a default. Ask the founder for the specific fact the payload names (e.g. the trustee-deposit date), and treat it as a counsel determination.
- **`lookup_status: "not_found"`** — the rule_id was wrong; pick the correct one or fall back to fast-assess / full pipeline.

This writes no artifact and runs in well under a second. End your response with: "If you'd like the full cap-table review — saved artifacts, dilution scenarios, and a counsel packet — just say 'review my cap table' or 'model the round'." If the founder then supplies instruments or asks for the full picture, route to fast-assess or the full pipeline.

### Step 5-concise (CONCISE MODE ONLY): run the math, render a short answer, skip the heavy tail

For a single quick math question, do Steps 2–3 (build `inputs.json` + `instruments.json` + a one-line `scenario_requests.json` from the founder's description, Lane 4), then run ONLY the math producers + `concise_report.py`. **Skip** `counsel_packet`, the full `compose_report`, `visualize`, `explore`, and the Context-B coaching sub-agent. The over-production in the full pipeline is the model driving ~14 sequential tool calls plus the coaching sub-agent — not the scripts (each runs in well under 0.1 s); concise mode collapses the tail to one render.

```bash
mkdir -p "$REVIEW_DIR"
python3 "$SCRIPTS/cap_state.py" --inputs "$REVIEW_DIR/inputs.json" --instruments "$REVIEW_DIR/instruments.json" --run-id "$RUN_ID" -o "$REVIEW_DIR/cap_state.json"
python3 "$SCRIPTS/rule_audit.py" --phase=pre_math --inputs "$REVIEW_DIR/inputs.json" --instruments "$REVIEW_DIR/instruments.json" --cap-state "$REVIEW_DIR/cap_state.json" --run-id "$RUN_ID" -o "$REVIEW_DIR/rule_audit.json"
python3 "$SCRIPTS/run_scenario.py" --inputs "$REVIEW_DIR/inputs.json" --instruments "$REVIEW_DIR/instruments.json" --cap-state "$REVIEW_DIR/cap_state.json" --scenarios-input "$REVIEW_DIR/scenario_requests.json" --run-id "$RUN_ID" -o "$REVIEW_DIR/scenarios.json"
python3 "$SCRIPTS/rule_audit.py" --phase=post_math --inputs "$REVIEW_DIR/inputs.json" --scenarios "$REVIEW_DIR/scenarios.json" --run-id "$RUN_ID" -o "$REVIEW_DIR/rule_audit.json"
python3 "$SCRIPTS/concise_report.py" --inputs "$REVIEW_DIR/inputs.json" --scenarios "$REVIEW_DIR/scenarios.json" --rule-audit "$REVIEW_DIR/rule_audit.json" --cap-state "$REVIEW_DIR/cap_state.json" --run-id "$RUN_ID" -o "$REVIEW_DIR/report_concise.md"
```

Pass `--cap-state` so the concise answer surfaces any anti-dilution recovery warning — a standalone anti-dilution question routes here, and without it the recovery is silently dropped on this route.

Present `report_concise.md` verbatim — never re-derive its numbers in chat. Concise mode writes the real `cap_state.json` + `scenarios.json` (so downstream consumers detect cap-table ran). Then jump to **Step 12: Deliver Artifacts** and close with a STATEMENT offering the full review as a follow-up (not a trailing question — a final turn ending in a bare "?" with no tool call is a stall), e.g. "If you'd like the full cap-table review — saved artifacts, dilution scenarios, and a counsel packet — just say 'review my cap table' or 'model the round'."

### Step 5: Determine Scenarios + Run Math → `scenarios.json`

Ask the founder via `AskUserQuestion` which scenarios to model (1–4). Common patterns:

- **Standalone SAFE conversion** (cap-implied math; no priced round): `{type: "safe_conversion", parameters: {}}`
- **Series A priced round**: `{type: "priced_round", parameters: {pre_money, new_money, target_pool_percent, target_basis}}`
- **Convertible note conversion at financing**: `{type: "note_conversion", parameters: {transaction_event_date, priced_round_new_money, qualified_financing_price}}`
- **Israeli ↔ Delaware flip** (only when mode=flip_focused or explicitly requested): `{type: "flip", parameters: {iia_grants_in_history, section_102_grants_outstanding}}`. `section_102_grants_outstanding` is derived from `cap_state.outstanding_options` (count of grants whose `plan_type` starts with `section_102`), so on a flip where `option_grants[]` is empty but the pool has issued options, first collect per-grant tax-route data (per holder: `plan_type` + `grant_date`; strike optional) via one batched `AskUserQuestion`, shaped per the Gate Catalog's *§102 per-grant tax route* row — never pass `0` merely because grants weren't captured (an empty grant list otherwise reports zero §102 exposure).

**Note-conversion parameter key (avoids a wasted round-trip):** the note-conversion date parameter in a scenario request is **`transaction_event_date`** (matching the `note_conversion` shape above), NOT `conversion_event_date` — the latter is only the internal `priced_round.py` signature / CLI-flag name (`--conversion-date`); the scenario request the orchestrator reads uses `transaction_event_date`.

**Notes in a priced round — author ONE request, not two.** When `detect_structure.py`'s `required_primitives` lists BOTH `note_conversion` and `priced_round` for the same round, author only the **`priced_round`** scenario request. The priced-round solver couples and converts the notes internally via its fixed-point iteration, so a standalone `note_conversion` request for the same round is redundant (and is not what `detect_structure.py`'s `route.scenario_requests` emits).

**Stated round terms — PPS and pre-money stamp.** When a source document (term sheet, pro-forma cap table, Carta export) prints a round price-per-share and/or a pre-money valuation as a headline term, capture those values into `inputs.stated_totals` alongside the existing `fully_diluted` entry, so `compose_report.py` can include a reconciliation row comparing the document's stated figures against the skill's computed ones:

```json
"stated_totals": {
  "price_per_share": 2.50,
  "pre_money": 20000000,
  "source": "term_sheet"
}
```

**Non-circularity rule — read this carefully.** Capture ONLY a figure the source document itself PRINTS as a headline term (e.g., "Series A Share Price: $2.50" or "Pre-Money Valuation: $20,000,000"). NEVER populate `price_per_share` or `pre_money` from a value the skill computed — if you do, `compose_report.py`'s reconciliation cross-foot trivially matches and silently hides a real divergence between the document's terms and the skill's math (a false green — the worst failure mode). If the source document does not print a PPS or pre-money figure, omit those fields entirely; do not back-fill them from the model or from `scenarios.json`. A missing stamp means the reconciliation row is absent (a silent miss — degraded, not wrong); that is far preferable to a circular cross-foot. This is an instruction the agent must follow — there is no deterministic script guard enforcing it.

**Founder-only gates must offer an escape.** When a recurring gate asks for a fact only the founder knows and the documents don't settle, make the **last option an explicit defer** — e.g. `Not sure` / `Not sure yet` / `Don't have the terms handy` / `Different — I'll correct it in chat` — so an unattended or automated answerer can decline rather than fabricate a fact it cannot know. **One exception:** when a gate's option labels map to a typed downstream enum (the jurisdiction-structure gate below is the only such case), keep the closed option set and accept the residual risk — an out-of-enum "not sure" can't serialize cleanly and would change which downstream rules fire.

**Gate Catalog — canonical phrasing (use these exact strings).** To keep founder UX consistent and let the regression cassettes anchor on a stable substring, when you raise these recurring `AskUserQuestion` gates use the question text and option labels below verbatim — do not paraphrase or add per-run suffixes like "(Recommended)" / "(standalone)" / "— no priced round assumed". **NEVER append run-specific text to a catalog label** — no founder names, share counts, sector, or "(Recommended)"; that context belongs in the question body or an option `description`, never the option `label`. (Worked example of the violation to avoid: render the cap-base confirm label as the catalog's `Confirmed`, NOT `Confirmed — Alice, Bob, Carol`.) (One-off, document-dependent gates — Lane-1 counsel-review, Lane-2 column mapping, Lane-3 blockers — stay as loose intent; they don't recur in a stable shape.)

| Gate | When | Question | Option labels | Notes |
|---|---|---|---|---|
| **Scenario selection** | any run | "Which scenarios should I model? (select all that apply)" | `Cap-implied SAFE snapshot` (→ `safe_conversion`), `Series A priced round` (→ `priced_round`), `Convertible note conversion at financing` (→ `note_conversion`), `Israeli ↔ Delaware flip` (→ `flip`) | Offer only the scenarios that apply to this cap table. |
| **Option pool** | confirming pool existence (e.g. Lane-3 sheet with no pool tab) | "Does the company have an employee option pool?" | `No option pool`, `Yes — I'll provide authorized / issued / unallocated` | The "Yes" label MUST keep a free-text/chat path (same affordance as S2, Step 2). Never collapse to bare yes/no. |
| **Cap-base confirmation** | S2 | "Please confirm [Company]'s cap-table base — I'll use exactly these numbers for all the math:" | `Confirmed`, `Different — I'll correct it in chat` | — |
| **No-cap-base fork** | standalone instrument, no equity base found after extraction | "No cap base found in your document(s). How should I proceed?" | `Provide the cap base — full review`, `Instrument terms only` | Mandatory fork before extraction-only. NEVER auto-pick `Instrument terms only` — "no base" can be a failed extraction, so the founder must get the chance to supply a base. |
| **Note "Company Capitalization" denominator** | S3 | "What does the note's 'Company Capitalization' clause define as the conversion denominator?" | `Fully-diluted pre-financing (common + options + as-converted SAFEs/notes, before new money)`, `Issued-and-outstanding only (common + issued options, no unallocated pool)`, `I'd need to check the note text` | Do NOT append "(Recommended)" — leading `Fully-diluted` is the stable cassette anchor. |
| **Note maturity default** | S3 | "If the note reaches maturity before a qualified financing, what happens?" | `Convert at cap`, `Repay principal`, `Extend maturity`, `Counsel review / unclear` | — |
| **Qualified-financing threshold** | S3 | "What dollar amount triggers the note's automatic conversion (its 'qualified financing' threshold)?" | `Same as this round's total new money`, `A different specific amount — I'll state it`, `I'd need to check the note text` | The dollar figure is deal-specific and cannot be a fixed label; these brackets cover the real cases and the tool's built-in **Other** carries the exact amount. Do NOT invent a "market-standard" figure as a fourth option — none is cited in this skill's references. |
| **Existing-review routing** | S0 | "I found an existing cap-table review for [Company]. Use it, or start fresh?" | `Use existing review`, `Start fresh` | — |
| **Pool top-up intent** | fast-assess / priced round | "Are you planning to top up your option pool as part of this round?" | `No top-up planned`, `Top up to 10% post-money`, `Top up to 15% post-money`, `Not sure yet` | — |
| **Engagement mode** | S2 | "Is this a flip-focused engagement (Israeli → Delaware), or a standard cap-table modeling engagement?" | `Standard cap-table modeling`, `Flip-focused (Israeli → Delaware)` | → `standard \| flip_focused`. Added here because Step 2's mode question was the sole spec for this gate with no catalog row to anchor it; that step now names this row and carries the enum mapping only. |
| **Company name** | S0/S2 company-context, first run | "What's the company's name?" | `Use "<name>" — as it appeared in the conversation / on the deck` (present only when a candidate was derived), `A different name — I'll state it` | RUNTIME-LABELLED — the affirmative label carries whatever was derived (a deck title, a conversational mention), never a placeholder. Omit it entirely if nothing was derived. |
| **Company stage** | S0/S2 company-context | "What stage is [Company] at?" | `Pre-seed`, `Seed`, `Series A`, `Series B+` | Stage only, never with sector (NOT `Seed / B2B SaaS`). **Write the ENUM, not the label** — `Pre-seed`→`pre-seed`, `Seed`→`seed`, `Series A`→`series-a`; the displayed label fails `metadata.stage` validation. **`Series B+` has no enum value**: it collapses `series-b`/`-c`/`-d`/`later` to fit the 4-option max, so on that pick ask a plain-text follow-up and write the specific stage — never default to `series-b`. |
| **Sector** | S0/S2 company-context | "What sector best describes [Company]?" | `Use "<sector>" — as derived from the materials` (present only when a candidate was derived), `A different sector — I'll state it` | RUNTIME-LABELLED, same shape as Company name — sector maps to `sector_type` via `founder_context.py:_SECTOR_ALIASES`, not a closed enum. |
| **Geography** | S0/S2 company-context | "Where is [Company] based?" | `Use "<geography>" — as derived from the materials` (present only when a candidate was derived), `A different location — I'll state it` | RUNTIME-LABELLED, same shape as Company name — geography is open (country/region). |
| **Jurisdiction structure** | S2 company-context | "What is [Company]'s jurisdiction structure?" | `Israeli company`, `Delaware (already flipped)`, `Mid-flip`, `Delaware with Israeli subsidiary` | → `israeli \| delaware \| mid_flip \| delaware_with_israeli_sub` enum, in that order. Use verbatim — do NOT reword to `Israeli company (IL only)` etc. Step 2's jurisdiction question names this row and carries the enum mapping only; it previously restated a different label set in a different order (`delaware`-first), which is the drift this row now prevents. |
| **IIA / OCS grants** | Israeli company-context | "Has [Company] received any IIA (Israel Innovation Authority / OCS) grants?" | `No IIA grants`, `Yes, has IIA grants`, `Not sure` | Step 2's IIA question names this row and carries the enum mapping only, for the same reason as Jurisdiction structure above. |
| **Interest rate type (note)** | extraction confirm-gate | "What kind of interest does the note carry?" | `Fixed rate (a stated numeric %)`, `Fixed rate, simple interest only`, `Israeli statutory rate (ITA §3(j))`, `No interest` | → `fixed_numeric \| fixed_numeric_simple \| statutory_ita_section_3j \| none` (`references/schemas/freeform-role-map.json:131`). A real closed enum — not a *Founder-only fact gates* case. |
| **Interest converts to shares (note)** | extraction confirm-gate | "Does accrued interest on the note convert into shares along with principal?" | `Yes — interest converts too`, `No — interest is paid in cash / forgiven` | `instruments.schema.json:59`, boolean. Defaults `true` if never asked; asking removes that silent default. |
| **SAFE terms** | Lane-2/3, sheet shows amounts but not cap/discount | "Do you know the valuation cap and/or discount on the SAFEs? The spreadsheet shows amounts but not the terms." | `Yes — I'll share the terms in chat`, `Uncapped MFN SAFEs`, `Don't have the terms handy` | — |
| **§102 per-grant tax route** | flip scenario, `option_grants[]` empty but pool has issued options | "I need per-grant tax-route data to model §102 exposure on the flip — do you have plan type and grant date for each holder's options?" | `Yes — I'll share plan type + grant date per holder`, `Some, not all — I'll share what I have`, `Don't have this — proceed without §102 detail` | Third option is the §796 escape: never pass `0` silently, but a founder without the data must be able to proceed. |
| **Founder-only fact gates (general shape)** | any founder-supplied fact a document doesn't settle (missing issuance_date, extraction confirm-gate batch fields, blank-template relaxed-gate amounts, fast-assess conversational batch) | varies by field | not a literal label set — see Notes | RUNTIME-LABELLED: dollar amounts, dates, per-instrument facts that can't carry fixed brackets. Shape: a stated-value option (or derived-value affirmative), a different-value option, an explicit defer per §796. Gives the extraction confirm-gate, the blank-template relaxed gate, the fast-assess batch and the missing-`issuance_date` ask a shape to point at; deliberately no backticked strings here. |

Write the scenario-request list to a temp file. **If `scenario_requests.json` was already populated from the coverage route in Step 4, confirm/extend it with the founder's answers here — do NOT re-author it from scratch**, or the heredoc below will silently clobber the coverage route's output:

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

**Dispatch the cap-table sub-agent in Context B.** **Call the `Task` tool with `subagent_type: "founder-skills:cap-table"`** after `compose_report.py` has successfully written both `report.json` and `report.md`.

**Mitigation 2 protocol:** the main thread reads the structured `coaching_payload` from `report.json` and STAGES it as a file in the hand-off dir. The sub-agent Reads it from the agent namespace (a required read, so a wrong prefix fails loudly before anything is written), does NOT Read full `report.md`, and **WRITES its commentary as plain markdown to `OUTPUT_PATH` — no JSON, no escaping — returning only a receipt**. The main thread then gates that file with `check_handoff.py --format=markdown`, wraps it via `md_to_commentary.py` (deterministic escaping), and pipes it into `insert_coaching.py`. Full procedure: the cap-table agent body's Context B section.

<!-- skill-quality-ci: bash-after-subagent-ok -->
```bash
python3 -c '
import json, sys
data = json.load(open(sys.argv[1]))
json.dump(data["coaching_payload"], open(sys.argv[2], "w"), indent=2)
print(json.dumps({"staged": sys.argv[2]}))
' "$REVIEW_DIR/report.json" "$HANDOFF_DIR/coaching_payload.json"
```

This STAGES the payload as a file and prints only a small receipt.
**Never capture it into a shell variable** — each Bash call runs in a fresh
shell, so the variable would be unreadable and gone. The sub-agent Reads the staged file from
the agent namespace; the payload is no longer pasted into the dispatch prompt.

Two reasons it is a file and not an inlined blob:

1. **It gives the dispatch a functionally REQUIRED read in the agent namespace.**
   A sub-agent that must Read before it can Write cannot silently misresolve its
   prefix — a wrong prefix fails the Read loudly, before anything is written. The
   one dispatch that survived a wrong prefix in practice survived for exactly
   this reason: it had a mandatory under-outputs read first. A read the agent does
   not need is a read the agent can skip, so the probe has to BE the payload.
2. **The payload stops passing through the model.** Same principle as the
   commentary: it leaves the model exactly once, and a re-typed JSON blob can be
   truncated or re-indented in ways that change its meaning.

**Dispatch prompt template** (substitute `<HANDOFF_AGENT>` with the Step-0 agent-namespace value — the same rule as every Context A dispatch; the sub-agent has no shell vars, so paste the printed value):

```
CONTEXT: POST_COMPOSE_COACHING
OUTPUT_PATH: <HANDOFF_AGENT>/coaching.md

You are dispatched to add coaching commentary to a cap-table report.

The compose_report.py script has finished. The structured `coaching_payload` has
been STAGED AS A FILE for you — it is not inlined in this prompt.

Read the coaching payload at <HANDOFF_AGENT>/coaching_payload.json.

If that Read FAILS, write NO file and return exactly:
{"status": "blocked", "reason": "handoff_path_unresolvable", "attempted": "<the path you tried>"}
Do not Glob for it, do not guess a different prefix, do not proceed from memory —
a failed Read here means the hand-off prefix is wrong and the main thread must
re-issue the dispatch. Reporting it is the correct outcome.

Follow your agent body's Context B procedure (POST_COMPOSE_COACHING):

1. Compose commentary from the STAGED coaching_payload (scenario_digest,
   ownership_range_across_scenarios, top_dilution_drivers,
   counsel_review_summary, date_sensitive_summary, flip_specifics).
   Do NOT Read the full report.md. Do NOT edit report.md or any canonical artifact.
2. Use your Write tool to write to OUTPUT_PATH exactly the coaching commentary
   as plain markdown — do NOT wrap it in JSON, do NOT escape anything (your
   Write tool handles newlines and quotes). WITHOUT a '## Coaching Commentary'
   heading and WITHOUT the insertion_marker string.
   Do NOT write any file other than OUTPUT_PATH — insertion into report.md is the
   main thread's job, via the shared md_to_commentary.py + insert_coaching.py scripts.
3. Return:
   {"status": "complete", "output_path": "<echo of OUTPUT_PATH>"}
   OR, if the payload is unusable (write no file):
   {"status": "blocked", "reason": "<specific gap>"}

Stop after returning the receipt JSON. Do not narrate.
```

**After the sub-agent returns:** if its final message is a `{"status": "blocked", "reason": ...}` object, stop and report the reason to the founder — do not run the gate. Otherwise gate the hand-off, then (on gate exit 0) transform and insert deterministically. **The commentary leaves the model exactly once (into the sub-agent's Write call) — NEVER re-type the sub-agent's markdown into a heredoc or a `python -c` argument.**

<!-- skill-quality-ci: bash-after-subagent-ok -->
```bash
# Step 0 already resolved PLUGIN_ROOT once, deterministically — reuse its printed
# value here rather than re-running the self-heal search in this fresh shell.
SHARED_SCRIPTS="<printed PLUGIN_ROOT>/scripts"
printf '%s' '<agent final message verbatim>' | \
  python3 "$SHARED_SCRIPTS/check_handoff.py" "$HANDOFF_DIR/coaching.md" \
    --format=markdown --agent-path "$HANDOFF_AGENT/coaching.md" --receipt-json - \
    --marker '<EXACT insertion_marker string from report.json coaching_payload>'
```

**On gate exit 0**, transform the gated hand-off FILE into the JSON transport envelope and insert (feed the file, never re-type the message):

<!-- skill-quality-ci: bash-after-subagent-ok -->
```bash
SHARED_SCRIPTS="<printed PLUGIN_ROOT>/scripts"
python3 "$SHARED_SCRIPTS/md_to_commentary.py" "$HANDOFF_DIR/coaching.md" | \
  python3 "$SHARED_SCRIPTS/insert_coaching.py" \
    --report "$REVIEW_DIR/report.md" \
    --marker '<EXACT insertion_marker string from report.json coaching_payload>' \
    --verify-artifact "$REVIEW_DIR/inputs.json" \
    --verify-artifact "$REVIEW_DIR/instruments.json" \
    --verify-artifact "$REVIEW_DIR/cap_state.json" \
    --verify-artifact "$REVIEW_DIR/scenarios.json" \
    --verify-artifact "$REVIEW_DIR/rule_audit.json" \
    --verify-artifact "$REVIEW_DIR/counsel_packet.json"
```

The gate (`check_handoff.py --format=markdown`) verifies the sub-agent's hand-off file exists, is non-empty, matches the receipt's echoed path, and passes the content-shape gate (not receipt-shaped, no marker collision); `md_to_commentary.py` wraps the raw markdown in the `{"commentary_markdown": ...}` envelope (escaping by construction via `json.dumps`); `insert_coaching.py` then performs the 6-state idempotency check, replaces the marker with `## Coaching Commentary` + the commentary in a single in-place write, and verifies `run_id` parity across all 6 producer artifacts. Branch on the exit code (complete state machine — do not improvise):

- **Exit 0 from the chain** — `insert_coaching.py`'s receipt on stdout says `inserted` (or `already_inserted` on a resume). Proceed to Step 12.
- **`check_handoff.py` exit 3** (missing/empty file — receipt may be fabricated) → **redo-dispatch**: fresh Task, same prompt plus one line: "your receipt claimed a file at `<path>` but none exists; use Write to create exactly that path."
- **Exit 5** (receipt echoes a different path) → **repair-dispatch** telling the agent the exact expected OUTPUT_PATH.
- **Exit 6** (receipt unparseable / no `output_path` key) → **redo-dispatch** with "return ONLY the receipt JSON — no fences, no prose." (A `status: "blocked"` final message is NOT exit 6 — it was handled before the gate.)
- **Exit 7** (content-shape gate failed — receipt-shaped or marker-bearing file) → **repair-dispatch**: "your file wasn't the coaching commentary — write the coaching markdown, nothing else, to `<OUTPUT_PATH>`."
- **Exit 8** (`path_namespace_mismatch`) → the sub-agent **complied**; the agent-namespace prefix was wrong. Its relative `OUTPUT_PATH` resolved against the outputs mount instead of the session root, so the file landed at the doubled path reported in `found_at`. Do NOT treat this as a fabricated receipt, and do NOT read the hand-off from `found_at` — re-dispatch with the corrected agent-namespace prefix (re-run `resolve_artifacts_root.py --agent` and rebuild `<HANDOFF_AGENT>` from the printed value). Counts against the same 2-dispatch retry budget.
- **`insert_coaching.py` exit 1** (blocked; stdout carries `{"status": "blocked", "reason": ...}`) → stop and report the exact reason. Do NOT hand-edit `report.md` — if the reason mentions a truncated report or a missing marker, re-run `compose_report.py --write-md` and retry the chain. If the reason is `commentary_markdown missing or empty`, treat as a malformed hand-off: repair-dispatch quoting the reason.
- **After ANY corrective dispatch, resume from the gate chain** — never feed the transform+insert pipe an ungated file.

**Retry budget:** max 2 corrective dispatches (same rule as Context A). **Graceful degrade:** if the FIRST corrective dispatch also exits 3 while the receipt claims `complete` with the correctly echoed path, treat the host topology as hand-off-incompatible and fall back to message-channel transport. **The corrective dispatch MUST ask for the commentary inline for this to be reachable** — add: "the file hand-off is not working in this environment; return the coaching commentary itself as your final message, as raw markdown, with no receipt JSON and no fences." Without that line the fallback is unreachable: the normal Context B prompt instructs the agent to return ONLY the receipt and not to narrate, so its final message contains no markdown to stage. Then stage that returned markdown to `$STAGING_DIR/coaching.md` via a **single-quoted** `<<'COACHING_EOF'` heredoc (apostrophe-safe; NEVER `python -c`, NEVER the `outputs/` root — `$STAGING_DIR` is the `/tmp` scratch dir from Step 0, never the promoted outputs mount), and run the same `md_to_commentary.py "$STAGING_DIR/coaching.md" | insert_coaching.py` chain against that staged file.

**Inline alternative (permitted but discouraged).** The main thread may compose the commentary itself (from the same `coaching_payload`, following the agent body's content guidance including the no-legal-conclusions rule) instead of dispatching. It then stages the commentary to `$REVIEW_DIR/coaching_commentary.json` via the quoted `<<'COACHING_EOF'` heredoc (the same graceful-degrade file above; single-quoted → apostrophe-safe; NEVER `python -c`, NEVER the `outputs/` root) and runs the SAME `insert_coaching.py --commentary-file "$REVIEW_DIR/coaching_commentary.json"` invocation — the script is the single insertion path regardless of who composed. Never Edit the marker by hand. This bypasses the fresh-sub-agent isolation that protects Context A's verifier loop from Context B reasoning — prefer the dispatched path. The privacy boundary (no investor names, no document text in coaching commentary) is enforced at compose time by `_assert_coaching_payload_privacy_clean()` in `compose_report.py` — that check runs regardless of which path composed, so the privacy invariant holds even when inline is used.

### Step 12: Deliver Artifacts

Copy deliverables to the **workspace root — `$ARTIFACTS_ROOT/..`, the promoted outputs mount itself,
NOT `$ARTIFACTS_ROOT` and NOT `$REVIEW_DIR`**: that is the level the founder sees as deliverable cards.
`dirname "$ARTIFACTS_ROOT"` is the answer; a bare relative target is not (it lands in the shell's cwd).

**Copy only what your route produced.** The full pipeline makes four files; each lightweight route
makes ONE, under its own name, and extraction-only writes to a different directory.

```bash
SLUG_TITLE="$(echo $SLUG | sed 's/-/_/g' | awk '{for(i=1;i<=NF;i++) $i=toupper(substr($i,1,1)) substr($i,2)} 1')"
OUT="$(dirname "$ARTIFACTS_ROOT")"
# FULL PIPELINE — all four:
cp "$REVIEW_DIR/report.md"         "$OUT/${SLUG_TITLE}_Cap_Table.md"
cp "$REVIEW_DIR/report.html"       "$OUT/${SLUG_TITLE}_Cap_Table.html"
cp "$REVIEW_DIR/explorer.html"     "$OUT/${SLUG_TITLE}_Cap_Table_Explorer.html"
cp "$REVIEW_DIR/counsel_packet.md" "$OUT/${SLUG_TITLE}_Counsel_Packet.md"
# FAST-ASSESS instead: report_fast_assess.md      -> ${SLUG_TITLE}_Cap_Table_Fast_Assess.md
# CONCISE instead:     report_concise.md          -> ${SLUG_TITLE}_Cap_Table_Summary.md
# EXTRACTION-ONLY:     $ARTIFACTS_ROOT/cap-table-$SLUG-extraction/report_extraction_only.md
#                                                 -> ${SLUG_TITLE}_Instrument_Terms.md
```

**Send the finished work to the founder — the complete set, as files.** Not a path, and not a subset.
A path is not a deliverable in Cowork — whether the workspace it names outlives the task depends on how
that task was started, so a founder who was handed only a path may end up with nothing. (That is your
reason for sending files; it is not something to tell the founder — see the no-claims rule below.) Send
every finished document you produced for them, and frame them as results you generated rather than
something they asked to look at.

**Then offer the working data — once, in one sentence.** For example: *"If you want to keep the working
data behind this — to pick it up later, or feed it into another analysis — say so and I'll send it as a
single archive."* Make **no claim about whether anything persists**, in either direction: that depends on
how the task was started, and it is not something to assert. If a folder is connected to the task, offer
to write the full set there instead.

If the founder says yes, **assemble the archive in your working scratch but write the finished file
into the same directory as the deliverables**, and send it from there. (Your reason, not something to
tell the founder: a scratch path cannot be handed over at all, and attempting it fails the *entire*
delivery — taking the real deliverables down with it. The scratch dir stays where it is; only the
finished archive moves.) Include only the reusable
inputs — the validated figures and extractions this analysis was built from, plus the composed report
data. Never include pipeline hand-off files, receipts, coaching payloads, or gate state: they mean
nothing outside the run that made them.

Do **not** delete the `/tmp` staging dir — it is ephemeral scratch the sandbox reclaims on its own.
Never issue a `rm` here: a delete command near an `outputs/` path is conservatively read as an
outputs-deletion (a Cowork-parity violation) even when its target is `/tmp`.

**Fixing a bad artifact (Cowork-safe):** to correct a wrong artifact, **overwrite it in place** by re-running the producer script that writes it (e.g., re-run `cap_state.py` / `extract_instrument.py --replace` / `compose_report.py`). Do NOT delete-and-recreate; deletion may be denied in Cowork. Writing (overwriting) is always permitted.

In flip-focused mode, the flip-impact narrative is rendered as a dedicated section inside `report.md` by the standard compose pipeline — no separate file.

The structured-artifact set (inputs.json, instruments.json, cap_state.json, scenarios.json, rule_audit.json, counsel_packet.json, report.json) stays inside `$REVIEW_DIR`. It is available for cross-skill consumption **wherever the artifacts root is durable** — Claude Code's `./artifacts/`, or a Cowork task whose workspace outlives it. Do not describe it to the founder as archived: on a cloud task it is not, which is what the archive offer above exists for.

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

- **On paths generally:** in Claude Code a path *is* the deliverable, because `./artifacts/` is
  durable. In Cowork the delivered files are the deliverable; a path names a workspace that may
  not outlive the task, so hand the files over rather than pointing at them.
- **Name all four files Step 12 produced** (naming three is how a live run dropped the fourth):
  `{Company}_Cap_Table.md`, `{Company}_Cap_Table.html` (**the one that goes missing**),
  `{Company}_Cap_Table_Explorer.html`, `{Company}_Counsel_Packet.md`. On a lightweight route, name that
  route's single deliverable instead.
- The headline outcome fields, sourced from the `coaching_payload` staged in Step 11 (`scenario_digest`, `counsel_review_summary`, `high_severity_warnings`) plus the `insert_coaching.py` receipt (`status`, `report_path`, `run_id`). The Context B sub-agent no longer echoes these — do not source them from its return.

  **Nesting — for cap-table all three are TOP LEVEL** on `coaching_payload`: `scenario_digest`, `counsel_review_summary`, `high_severity_warnings`. Do not reach under `.summary` (it holds only scenario counts and a deliberately-null `score_percent`). There is no checklist and no score to fall back to — if a field is null read `report.json`, never invent a number.

**Do NOT inline `report_markdown` in the assistant message.** The founder reads the file via the path. (Same rationale as deck-review #13: avoids ~25 KB round-trip through the parent context.)

## Feedback

If a run ends **blocked or failed**, after you report the reason to the founder, add one line:
> _If this looks wrong or didn't finish, you can flag it: `/founder-skills:feedback`._

On **unsolicited** praise or frustration, you may mention `/founder-skills:feedback` once — never routinely, never mid-workflow, never more than once per session.
