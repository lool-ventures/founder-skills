---
paths:
  - "founder-skills/skills/deck-review/**"
  - "founder-skills/skills/competitive-positioning/scripts/_quote_match.py"
  - "founder-skills/skills/market-sizing/scripts/_quote_match.py"
  - "founder-skills/tests/test_deck_*"
  - "founder-skills/tests/test_dr_*"
  - "founder-skills/tests/test_reconcile*"
  - "founder-skills/tests/test_ledger*"
  - "founder-skills/tests/test_ocr_*"
  - "founder-skills/tests/test_slide_reviews*"
  - "founder-skills/tests/test_quote_match_sync.py"
  - "founder-skills/tests/test_e2e_deck_review.py"
  - "founder-skills/tests/test_lane_deck_text_checks.py"
  - "founder-skills/tests/no_ledger_goldens.py"
  - "founder-skills/tests/slide_review_inputs.py"
  - "founder-skills/tests/slide_review_lint_corpus.py"
  - "founder-skills/tests/test_fixture_schema_fidelity.py"
  - "founder-skills/tests/test_folder_ownership.py"
  - "founder-skills/tests/test_founder_document_names.py"
  - "founder-skills/tests/test_gate_registry.py"
  - "founder-skills/tests/test_gate_state.py"
  - "founder-skills/tests/test_gate_writers_mirror.py"
  - "founder-skills/tests/test_lane_capture.py"
  - "founder-skills/tests/test_lane_numeric_checks.py"
  - "founder-skills/tests/test_lane_sizing_redo_checks.py"
  - "founder-skills/tests/test_no_independence_claims.py"
  - "founder-skills/tests/test_out_guard_coverage.py"
  - "founder-skills/tests/test_out_guard_wiring.py"
  - "founder-skills/tests/test_plugin_root_not_through_bash.py"
  - "founder-skills/tests/test_record_gate_answer.py"
  - "founder-skills/tests/test_resume_evidence.py"
  - "founder-skills/tests/test_run_status.py"
  - "founder-skills/tests/test_schema_validator.py"
  - "founder-skills/tests/test_score_owners.py"
  - "founder-skills/tests/test_script_hashes.py"
  - "founder-skills/tests/test_second_read.py"
  - "founder-skills/tests/test_second_read_claims_are_approved.py"
  - "founder-skills/tests/test_setup_run.py"
  - "founder-skills/tests/test_skill_orchestration.py"
  - "founder-skills/tests/test_stage_coverage.py"
  - "founder-skills/tests/test_stage_profile.py"
  - "founder-skills/tests/test_step0_paths.py"
  - "founder-skills/tests/test_superseded_deliverables.py"
  - "founder-skills/tests/test_usage_fix_lines.py"
  - "founder-skills/tests/test_visualize_deck_review.py"
---
# Deck Review Scripts

- **`checklist.py`** — Scores 35 criteria across 7 categories (pass/fail/warn/not_applicable) with overall score percentage. It reads `--inventory` before validating, so a criterion its gates force to not_applicable (AI on a `not_ai` deck, design on an unrendered one) needs no evidence or fix; ids and statuses are still checked
- **`dr_dispatch_prompt.py`** — Prints Step 5's CHECKLIST sub-agent prompt from identifiers (`checklist --run-id --handoff-agent --review-dir-agent --review-dir`, `--correction` for a redo, `producer-rejected --detail-file` for every producer rejection, `SLIDE_REVIEWS_NOT_READ` included). Prints nothing until this run's `slide_reviews.json` carries a read token (`SLIDE_REVIEWS_MISSING`, exit 1, no context line, its own `fix`: run Step 4's pipe, then the generator again), and refuses `ARTIFACT_OTHER_RUN` in a bound folder when a file the grader reads is another run's. It never reads the token: `_slide_reviews_file.py` holds the "is this run's file usable" half both it and `checklist.py` use, the generator importing only `usable`, and the token comparison stays in `checklist.py`. Every option takes a value (the dispatch hook reads the first positional after the script as the context). Registered with the dispatch-prompt hook; a scoring file.
- **`compose_report.py`** — Assembles deck review artifacts into final report with cross-artifact validation
- **`visualize.py`** — Generates self-contained HTML with SVG charts; outputs HTML (not JSON)
- **`ledger.py`** — Validates the extracted numeric ledger. Its load-bearing check is `raw` against `value`: they are two independent statements about the same figure, so their disagreement catches the scale-slip class ("$493K" recorded as 493) **without seeing the deck**. Tolerance comes from `raw`'s own significant figures, not a flat percentage — "$1.2M" legitimately covers 1.15M–1.25M and a flat 2% rejects a correct extraction. A range is accepted at either of its two numbers and no other, which is safe only because `reconcile.py` reads every range from its low end and treats a sum, difference or product of a range as a range.
- **`reconcile.py`** — The arithmetic. Corroborates each figure's quote against a second read that never saw the ledger, computes the model's proposed relations, applies the tolerance/materiality/convention rules, and **`select()` is the single place that decides what a founder sees**. `relations` in the artifact holds only the survivors; everything else is a count, so no renderer can reach past the decision. Two rules that have each already been violated once: split founder-facing output on **`verdict`** (what the engine computed), never on `kind` (what the model proposed) — they routinely differ, and the flagship finding is proposed `derived_ratio` and returns `contradiction`; and never render a `unit_kind` enum into prose ("per count" reached a rendered line). `--explain` is for maintainers: it prints every computed relation with its working and writes nothing (refused with `-o` or beside `--print-downgrade-stanza`).
- **`_quote_match.py`** — Copy of cap-table's `quote_in_doc` + normalizers (skill scripts are standalone and cannot import across skills). `tests/test_quote_match_sync.py` compares the parsed function bodies. **`value_in_doc` is deliberately NOT copied**: on decks it false-passes 5.7% cross-deck and 37% on plausible round numbers, against `quote_in_doc`'s 0.8%, so the cap-table precedent is inverted here on purpose.
- **`gate_state.py`** — The stage gate's producer and answer writer (`emit` / `answer`), one of the three writers that record their own gate. With a run ledger it opens and records `stage_confirmation` / `stage_choice` / `out_of_scope_choice` in the ledger and keeps `gate_state.json` as the mirror; `emit` applies a request's answer (`answer_source: "host"`), except a `stage_confirmation` that disagrees with the deck or (`looks_right`) a low-confidence detection, which waits `PRE_ANSWER_UNLISTED`. A stage answer is bound to the stage it confirmed. Its refusals carry the status code (`GATE_UNANSWERED`, `GATE_INTERMEDIATE`, `OUT_OF_SCOPE_UNANSWERED`, `AUTO_SATISFY_NOT_ALLOWED`, `GATE_INVALID`, `GATE_OTHER_RUN`, `PROFILE_MISMATCH`, `FOUNDER_DECLINED`). `context_summary` may carry the producer's `(Earlier rounds the deck reports: …)` line, from `deck_inventory.json`'s `prior_rounds`.
- **`setup_run.py`** — Resolves the review dir and run id. `--clean` removes earlier runs' checkpoints but keeps those stamped with this `--run-id` (and this run's gate file when it carries history); `reuse_checkpoints` is true only when a checkpoint was kept, so an unbound driver must mint a fresh id per review. A run already bound (`run_ref.json` present) is this run's: nothing is cleaned. After compose exits 10, an open stage question is reported as `gate_action: reask` with `gate_id` (ledger runs only).
- **`deck_inventory.py`** — Validates the deck inventory. `prior_rounds` (optional): rounds the deck says were already closed, each a stage token and an optional integer year (1990 to next year); a round being raised now is `claimed_stage`, never `prior_rounds`. `observations` (at most 12 notes of at most 300 characters) and a slide's `printed_label` (at most 16) are the reviewer's own notes, never deck text: capped in the producer, since the schema validator ignores `maxItems` / `maxLength`; over a cap is refused, never truncated.
- **`deck_text.py`** — Writes the run's one canonical `deck_text.md`: front matter (`run_id`, `source`, per-slide `pages_source`, `deck_sha256`, `warnings` as codes), then one `## Slide N` section per inventory slide. A PDF page's text layer, a PPTX slide in `presentation.xml` order (speaker notes from it, or from `--notes-from` for its PDF conversion), or a `.txt` / `.md` deck split on `SLIDE N` marker lines (`--staged` records a deck the main thread wrote from the founder's message as `pasted`, refused on a binary deck, `STAGED_FORMAT`); a slide with no text falls back to its inventory record, so for an image deck the inventory IS the deck text. No text is dropped: a slide count or marker that disagrees with the inventory is a warning (`PAGE_COUNT_MISMATCH`, `NO_SLIDE_MARKERS`, `DUPLICATE_SLIDE_MARKER`), never a cut. It never reads `observations` or `printed_label`.
- **`_deck_text_file.py`** — The deck text's shared helpers: the front matter closes at the file's SECOND `---` line (a markdown body may carry its own), `body_sha256` hashes what follows it, and `stamp(path, run_id)` returns that hash or a refusal (`DECK_TEXT_UNREADABLE`, `DECK_TEXT_INVALID`, `DECK_TEXT_OTHER_RUN`). Every producer that reads the deck text stamps `metadata.deck_text_sha256` through it, so editing the front matter changes no stamp and editing a slide changes every one.
- **`second_read.py`** — Step 3.6's producer: validates the SECOND_READ hand-off (`transcript`, `slides_transcribed`; `SECOND_READ_INVALID`), stamps `metadata.run_id` and, with `--deck-text`, the deck text's body hash, dropping any stamp the hand-off carried. Replaces an inline `python3 -c`. `slide_reviews.py --deck-text` (required, beside `--ledger`) stamps the same way, checked before stdin is read, without changing the read token.

- **`deck_ocr.py`** / **`ocr_check.py`** / **`_ocr_scope.py`** — Step 3.95, the machine read of image slides. `_ocr_scope` is the one scope reader (ids among the kept relations' operands and `expected_id`, not dates, on a `pages_source: inventory` slide) for the producer, the check and Step 4's gate. `deck_ocr.py` renders and tesseract-reads only those slides; `-o` is a folder (`receipt.json`, `p<N>.txt`), resumed until `"complete": true`, each call starting a new page only within `--budget-seconds` (default 30, always at least one page), a page `failed` after two attempts; a missing tool or unreadable PDF exits 0 as `unavailable`; refuses `DECK_NOT_FOUND`, `OUTPUT_NOT_DIR`, `LEDGER_UNREADABLE`, `RECONCILIATION_UNREADABLE`. `ocr_check.py` counts the figures the read found as written (reconcile's grammar, never copied) into `ocr_check.json` (status and counts only; each figure's result stays in the hand-off `figures.json`); exit 2 `OCR_NOT_RUN` / `OCR_INCOMPLETE` (also for a receipt of another deck, scope or page cap), exit 1 `OCR_OTHER_RUN`. `_reconciliation_prose.ocr_read_line` renders the counts-only sentence in both report.md and report.html; it never names a figure. No dispatch from Step 4 on reads `ocr/` or `ocr_check.json`.

**The numeric chain (Steps 3.5–3.8) is gated by `slide_reviews.py --reconciliation`, not by `MISSING_ARTIFACT`.** Step 3.95 is gated by the same producer: with `--ledger` and `--deck-text` it refuses `OCR_CHECK_MISSING` / `OCR_CHECK_OTHER_RUN` / `OCR_CHECK_STALE` (the check carries `reconciliation_sha256`) / `OCR_CHECK_WRONG_DECK` whenever a figure the kept relations use sits on an image slide; a deck with none needs no check. Measured: removing a required artifact leaves `compose_report.py` exiting **0** with a complete report, so a step whose only downstream consumer is a warning gets skipped in silence — which is exactly what happened to the removed claim-check step. The gate sits on the producer of the deliverable, and checks `run_id` parity rather than mere presence (a stale artifact from an earlier review of the same company otherwise satisfies an existence check, and `setup_run.py --clean`, which removes the skill's own earlier-run checkpoints (scripts delete under outputs only their own files; a failed atomic write also removes its temp file), tolerates a refused delete, which hosts before Desktop 2.16120.0 gave; the model never deletes there).

