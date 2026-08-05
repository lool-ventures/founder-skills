---
name: deck-review
description: "Scores and strengthens startup pitch decks (pre-seed through Series A) against 35 investor-grade criteria grounded in Sequoia, DocSend, YC, a16z, and Carta data. Run the scored rubric rather than giving deck advice from memory."
when_to_use: >
  Use ONLY when the user has attached a pitch deck file (PDF, PPTX, markdown,
  or pasted slide text describing slide-by-slide content) AND has asked for
  review, scoring, feedback, or critique of the deck. Do not auto-invoke on
  general fundraising or pitch questions; use ONLY when there is actual
  deck content to review.
  Scoring is against 35 named criteria with source-cited benchmarks — run this rather than giving general deck advice from memory, which is not the rubric a founder is asking to be measured against. Verbosity is not a reason to skip it.
user-invocable: true
---

# Deck Review Skill

Help startup founders strengthen their pitch decks before sending them to investors. Produce a structured, scored review with specific, actionable recommendations grounded in current best practices from Sequoia, DocSend, YC, a16z, and Carta data. The tone is founder-first: a candid coaching session, not a VC evaluation.

## Skill Metadata

- **Author:** lool-ventures
- **Version:** managed in `founder-skills/.claude-plugin/plugin.json`
- **Compatibility:** Python 3.10+ and `uv` for script execution.
- **Exports:**
  - `checklist.json` → `financial-model-review`, `ic-sim`, `fundraise-readiness` (future)

## Skill Execution Model (READ FIRST)

> See `founder-skills/references/skill-execution-model.md` for the full inline-skill execution model (3 dispatch contexts, Mitigation 1+2, producer contract, Cowork quirks, per-symptom triage).

This skill runs **inline in the main thread**, not as a sub-agent — see the reference above ("Why Inline (Not Forked Sub-Agent)") for the rationale. Sub-agents are deliberately shell-free, so orchestration (producer scripts, artifact persistence) stays in the main thread.

**Two dispatch contexts for the sub-agent:**

- **Context A — Per-step analytical dispatch (Mitigation 1):** Steps 4 and 5 dispatch the deck-review agent via the `Task` tool. The agent does deep analysis, WRITES its output JSON to the `OUTPUT_PATH` given in its prompt (the `handoff/` dir), and returns a small receipt. The main thread gates the file with `check_handoff.py`, then pipes it through the producer script (`slide_reviews.py` or `checklist.py`). The sub-agent never writes canonical artifacts — only its hand-off file.
- **Context B — Post-compose coaching dispatch:** Step 7 dispatches the sub-agent after `compose_report.py` writes `report.md`. The sub-agent Reads the staged `coaching_payload.json` from the hand-off dir (Mitigation 2) — it does NOT Read the full `report.md` — composes the coaching commentary, WRITES it to the `OUTPUT_PATH` hand-off file, and returns a small receipt. The main thread gates the file (`check_handoff.py`) and inserts it via the shared `insert_coaching.py` script (idempotency matrix, uuid-marker replacement, run_id-parity verification — all deterministic). See the reference above for the full Context B contract.

**Tolerant JSON extraction protocol (Context B returns; also the Context A message-channel fallback):** capture the sub-agent's final assistant message. It should be raw JSON, but may be wrapped in ` ```json ... ``` ` fences or carry a prose preamble. Extract tolerantly:

1. If the message is wrapped in a ` ```json ... ``` ` (or plain ` ``` ... ``` `) fence, strip the fence first.
2. Try to parse the stripped text directly as JSON.
3. If that fails, walk through the text looking for the first `{` character and try `json.JSONDecoder().raw_decode(text[i:])` — this is brace-aware and handles nested objects correctly (unlike regex, which truncates on the first `}`).
4. If extraction fails entirely, re-prompt the sub-agent with: "Your previous reply could not be parsed as JSON. Return ONLY the JSON object — no markdown fences, no prose preamble."

Context A **receipts** don't need this protocol by hand — `check_handoff.py --receipt-json -` applies the same tolerant extraction internally; pass the final message verbatim.

## Input Formats

Accept any format: PDF, PowerPoint (PPTX), markdown, or text descriptions of slides.

## Available Scripts

All scripts are at `${CLAUDE_PLUGIN_ROOT}/skills/deck-review/scripts/`:

- **`setup_run.py`** — Resolves `REVIEW_DIR`, detects resume vs. fresh run, cleans stale artifacts (`--clean`)
- **`deck_inventory.py`** — Producer for `deck_inventory.json` (agent provides JSON via stdin; schema-validated)
- **`stage_profile.py`** — Producer for `stage_profile.json`; `--rebuild-stage` + `--confidence {high,low}` for founder-corrected stages
- **`gate_state.py`** — Producer (`emit`) + answer-writer (`answer`) for the stage-confirmation gate
- **`slide_reviews.py`** — Producer for `slide_reviews.json` (agent provides JSON via stdin; schema-validated)
- **`checklist.py`** — Scores 35 criteria across 7 categories (pass/fail/warn/not_applicable)
- **`compose_report.py`** — Assembles artifacts into final report with cross-artifact validation; `--strict` exits 1 on high/medium warnings
- **`visualize.py`** — Generates self-contained HTML with SVG charts (not JSON)

Also available from `${CLAUDE_PLUGIN_ROOT}/scripts/` (shared):

- **`founder_context.py`** — Per-company context management (init/read/merge/validate)

Run with: `python3 ${CLAUDE_PLUGIN_ROOT}/skills/deck-review/scripts/<script>.py --pretty [args]`

## Available References

Read as needed from `${CLAUDE_PLUGIN_ROOT}/skills/deck-review/references/`:

- **`deck-best-practices.md`** — Full best practices: slide frameworks, stage-specific guidelines, design rules, AI-company requirements
- **`checklist-criteria.md`** — Definitions for all 35 criteria with pass/fail/warn thresholds
- **`artifact-schemas.md`** — JSON schemas for all artifacts

## Artifact Pipeline

Every review deposits structured JSON artifacts into a working directory. The final step assembles all artifacts into a report and validates consistency. This is not optional.

| Step | Artifact | Producer |
|------|----------|----------|
| 1 | founder context | `founder_context.py` read/init |
| 2 | `deck_inventory.json` | `deck_inventory.py` (agent provides JSON via stdin) |
| 3 | `stage_profile.json` | `stage_profile.py` (agent provides JSON via stdin) |
| 4 | `slide_reviews.json` | `slide_reviews.py` (agent provides JSON via stdin) |
| 5 | `checklist.json` | `checklist.py` |
| 6 | Report | `compose_report.py` (writes both `report.json` and `report.md`) |

**Rules:**
- Deposit each artifact before proceeding to the next step
- For producer-script artifacts (Steps 2-4), the agent supplies JSON on stdin and the script schema-validates against `references/schemas/<artifact>.schema.json`. Never write artifacts directly via `Write` or `Edit` — always pipe through the producer script so `metadata.run_id` is injected and the schema is enforced.
- If a step is not applicable, deposit a stub: `{"skipped": true, "reason": "..."}`

Keep the founder informed with brief, plain-language updates at each step. **Narrate the founder-visible OUTCOME, never the internal step.** That is the test to apply, and it catches more than a word list can: the forbidden thing is not a syntax, it is talking about the machinery. Bad — "Gating and piping the extraction through the producer, then staging the coaching hand-off"; good — "I've checked your numbers and I'm writing up what stood out." Bad — "schema-drift warning on `coaching_payload`"; good — nothing, because the founder has no stake in it. **Never name an internal artifact, field, or token** (a payload key, a marker name, an artifact filename, a hand-off dir) even in plain prose with no backticks — a detector keyed on syntax cannot see "gated", "hand-off" or "canonical artifacts", but the founder still reads them and they still mean nothing to them. **The between-step progress lines are the primary leak vector, not the final summary.** They feel internal — you are narrating what you are about to do — but the founder reads every one of them, and this is where the leaks actually appear: *"Now gating the hand-off before piping through the checklist producer"*, *"Gate 1 passes"*, *"Running the final verification gate"*. Rewrite each pipeline transition as the founder-visible outcome: *"Checking your numbers against the 46-point review"*, *"Your inputs look consistent — moving on to unit economics"*, *"Finishing up and putting the report together"*. If a progress line would mean nothing to someone who has never seen this skill's internals, it does not belong in the channel. Also excluded, as before: file/script names, paths, `*.py`, `--flags`, `$vars`, exit codes ("Exit N", "not found"), `W_`/`E_` codes, JSON, and step/route labels ("Lane N", "Context A/B", "Phase N", "structure detection", "the grid", any `ALL_CAPS_TOKEN`). After each analytical step (4–5), share a one-sentence finding before moving on. **The task tracker is founder-visible too — the same rule governs its labels.** "Gate the inputs review handoff", "Validate inputs.json", "resolve agent namespace paths", "Initialize founder context" are leaks even though each names a real step, and even when the prose around them is clean. Label each task by the founder-visible outcome — "Check your inputs", "Score against the review", "Write up what I found" — never by a file, directory, script, or pipeline stage.

## Workflow

### Step 0: Path Setup

**Every Bash tool call runs in a fresh shell — variables do not persist.** A stale reference does not error, it silently expands to empty (a path quietly becomes `/inputs.json`). Run the block below exactly **once**: it resolves `$PLUGIN_ROOT` deterministically, and every later block must substitute the printed value as a literal rather than re-running the resolution — repeating the self-heal search can land on a different mount than Step 0 picked when more than one is present (see why in the block's comments). `$RUN_ID` is minted once below, then re-established authoritatively by `setup_run.py`'s printed `run_id` (Step 1, which decides resume-vs-fresh) — never re-run the mint line below in a later block. Read the printed values out of each Bash call's output (`PLUGIN_ROOT` and `ARTIFACTS_ROOT` here, then `review_dir`/`run_id`/`resume`/`gate_answer` after Step 1) and paste them as literals into every subsequent block; do not carry a variable forward and assume it survived.

Optional, best-effort, and via the **Read tool** (not a shell command): before the block below, Read `${CLAUDE_PLUGIN_ROOT}/.claude-plugin/plugin.json` and note its `version` field as `EXPECT_VERSION`. Passing it to `select_plugin_root.py` below lets an exact version match win over an arbitrary first hit. If the Read fails, skip it and omit `--expect-version` — selection is still deterministic without it.

```bash
SCRIPTS="${CLAUDE_PLUGIN_ROOT}/skills/deck-review/scripts"
if [ ! -d "$SCRIPTS" ]; then
  # In Cowork, CLAUDE_PLUGIN_ROOT substitutes to a host-side path absent inside
  # the session VM — self-heal by collecting EVERY candidate mount (a session can
  # have more than one at once: a stale host-side cache, a test marketplace, even
  # a symlink into a different session's tree) and handing them to
  # select_plugin_root.py, which picks ONE deterministically and names the
  # rejects — never trust `find`'s arbitrary first hit, which can silently mix
  # scripts across plugin versions mid-pipeline.
  CANDIDATES="$(find /sessions -type d -path '*/skills/deck-review/scripts' 2>/dev/null)"
  [ -n "$CANDIDATES" ] || CANDIDATES="$(find / -type d -path '*/skills/deck-review/scripts' 2>/dev/null)"
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
  SCRIPTS="$PLUGIN_ROOT/skills/deck-review/scripts"
fi
PLUGIN_ROOT="${SCRIPTS%/skills/*}"
echo "PLUGIN_ROOT=$PLUGIN_ROOT"   # resolved ONCE, here — paste this literal into every later block; never re-run this resolution
REFS="$PLUGIN_ROOT/skills/deck-review/references"
SHARED_SCRIPTS="$PLUGIN_ROOT/scripts"
# Resolve the canonical artifacts root via a SCRIPT, not inline bash. An inline path computation is
# guidance the agent paraphrases — it lands outputs/ in one run and outputs/artifacts/ in another,
# desyncing cross-skill find_artifact.py and breaking path-based checks. The script computes the root
# deterministically (under the promoted outputs/ dir in Cowork, ./artifacts in the CLI) and creates it.
python3 "$SHARED_SCRIPTS/resolve_artifacts_root.py"   # prints ARTIFACTS_ROOT — use the printed path verbatim as ARTIFACTS_ROOT in every later block (a captured var dies in the next fresh shell)

# RUN_ID — used by Step 1 (founder_context init) before slug-aware setup_run.py
# runs, then passed to setup_run via --run-id. If the caller's task prompt
# supplied a RUN_ID (resume), keep it; otherwise mint a fresh one.
RUN_ID="${RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)}"
```

Reaching the self-heal branch is normal in Cowork — `${CLAUDE_PLUGIN_ROOT}` resolves to a HOST path that does not exist inside the VM, so the `[ ! -d "$SCRIPTS" ]` test fails by design rather than by misconfiguration. It is not a sign anything is wrong, and it is not worth narrating to the founder.

**Outputs mount is append-only.** Everything under the promoted outputs mount (`.../mnt/outputs/`, not just `$REVIEW_DIR`) is write-allowed and delete-denied by the platform: never `rm`, move away, or empty anything under it — **including files you created yourself**. Never create ad-hoc scratch anywhere under the outputs mount (no `_src/` copies, no run-state note files); scratch belongs in `$STAGING_DIR` (a `/tmp` dir, defined below). Do not "clean up" the outputs folder before delivering — extra working files there are expected and harmless. The uploaded deck is already readable in place from the uploads mount; never copy it under outputs to make it readable.

**There is no quick-check lane here, and that is deliberate.** The 35 criteria are scored from per-slide sub-agent reviews — those reviews ARE the work, so dropping them leaves only the checklist scaffolding. So when the founder asks a small
conversational question, do not improvise an answer from your own reasoning under this skill's name —
an unproduced score is exactly the output a founder over-trusts. Instead, say up front what the
full run costs and let them choose: "Answering that properly means running the full deck review — it takes
several minutes and produces a scored report across all 35 criteria. I can run it now, or if you just want my read without the
scoring, say so and I'll answer outside the deck review." Naming the trade-off is honest; quietly
substituting the cheap version is not.

After Step 1 (when the slug is known) — substitute `$SLUG` below with the company slug from Step 1's printed JSON, then call `setup_run.py` to resolve `REVIEW_DIR`, detect whether this is a resume, and clean stale state in one atomic step. **Always** call `setup_run.py` with `--clean` and `--run-id "$RUN_ID"`; do not pre-read `gate_state.json` yourself. `setup_run.py` decides resume vs. fresh by comparing the answered `gate_state.json`'s `run_id` against `--run-id`, and on a fresh (non-resume) run it deletes a stale answered `gate_state.json` so a prior completed run cannot be misread as a resume:

```bash
python3 "$SCRIPTS/setup_run.py" \
  --artifacts-root "$ARTIFACTS_ROOT" \
  --slug "$SLUG" \
  --run-id "$RUN_ID" \
  --clean \
  --pretty
```

Read `review_dir`, `run_id`, `resume`, and `gate_answer` from the JSON printed by the previous Bash command. Substitute `REVIEW_DIR` with the `review_dir` value, `RUN_ID` with the `run_id` value, and `IS_RESUMING` with `1` if `resume` is true, else empty, in every subsequent bash block. Then:

```bash
# Context A hand-off dir — PER RUN: sub-agents WRITE their raw output JSON here (the audit trail —
# raw sub-agent output as returned, before producer validation). Permanent by platform design
# (outputs/ mounts are write-allowed / delete-denied); nothing in it is ever a canonical artifact.
# The $RUN_ID segment is load-bearing: it prevents a stale prior-run file from silently passing
# the hand-off gate when a dispatch fails to write.
HANDOFF_DIR="$REVIEW_DIR/handoff/$RUN_ID"
mkdir -p "$HANDOFF_DIR"
# Sub-agents address the SAME dir by a different path (their file tools are rooted at the outputs
# mount in Cowork). Resolve the FULL agent-namespace paths via the script — never hand-splice the
# printed root with a literal skill-name/slug/run-id string yourself (that string-splicing is
# exactly the non-determinism the resolver script exists to remove):
python3 "$SHARED_SCRIPTS/resolve_artifacts_root.py" --handoff-dir-agent \
  --dir-name "<basename of REVIEW_DIR>" --run-id "$RUN_ID"   # prints HANDOFF_AGENT verbatim
HANDOFF_AGENT="<printed value>"   # use verbatim in OUTPUT_PATH lines
# Sub-agent READ paths for under-outputs artifacts use the SAME agent namespace (relative — the
# sub-agent's file-tool cwd IS the outputs mount on host-loop; an absolute /sessions/... read is denied):
python3 "$SHARED_SCRIPTS/resolve_artifacts_root.py" --analysis-dir-agent \
  --dir-name "<basename of REVIEW_DIR>"   # prints the dir in the agent namespace
REVIEW_DIR_AGENT="<printed value>"   # e.g. stage_profile.json, deck_inventory.json reads
# Ad-hoc scratch (NOT sub-agent hand-off) lives OUTSIDE the promoted outputs/ tree, in a temp dir
# that is safe to both create and reclaim. Use the printed path verbatim in later steps.
STAGING_DIR="$(mktemp -d "${TMPDIR:-/tmp}/deck-review-${SLUG:-deck}.staging.XXXXXX")"
```

To resume across a gate round-trip, the caller's task prompt must supply the prior `RUN_ID` (so `RUN_ID` above is set before this block runs). Then `setup_run.py` sees the answered `gate_state.json` whose `run_id` matches and returns `resume: true` — and because resume is true, `--clean` leaves `gate_state.json`, `deck_inventory.json`, and `stage_profile.json` in place (they are same-run checkpoints for this `RUN_ID`).

Pass `RUN_ID` to every producer script via `--run-id`. Producer scripts inject it into `metadata.run_id` automatically. `compose_report.py` enforces that all required artifacts share the same `run_id` and emits a `MISSING_METADATA` (high) warning for any artifact without one. Keeping `RUN_ID` stable across the gate is what prevents a `STALE_ARTIFACT` mismatch with the pre-gate artifacts.

**On re-invocation (`$IS_RESUMING` is set):** `gate_state.json`, `deck_inventory.json`, and `stage_profile.json` all survive `--clean` (same-run artifacts are preserved on resume). Skip Steps 2 and 3 if both `deck_inventory.json` and `stage_profile.json` exist and their `metadata.run_id` matches `$RUN_ID`; otherwise re-run them with the same `RUN_ID`.

### Step 1: Read or Create Founder Context

```bash
python3 "$SHARED_SCRIPTS/founder_context.py" read --artifacts-root "$ARTIFACTS_ROOT" --pretty
```

**Exit 0 (found):** Use the company slug and pre-filled fields. Proceed to Step 2.

**Exit 1 (not found):** Expected on a first run — do NOT mention this check or its exit status to the founder; if you narrate anything first, say only "Let me grab a few basics about the company." First **skim the attached deck** (title slide, footer, contact block — a Read of the file is available now; do NOT write any artifact yet) to derive candidate values. Then use `AskUserQuestion` (NOT plain chat) to ask for company name, stage, sector, and geography, pre-filling each question's first option with the deck-derived value (company name from the title slide; sector/geography from deck signals such as customer names, currency, phone country codes), labeled as read from the deck; keep free-form options for correction. **If `AskUserQuestion` is genuinely unavailable in the host, do NOT skip the ask and do NOT assume the answer:** ask the same question in plain chat, state the options explicitly, and wait for an answer before continuing. The ban above is on asking casually WHILE the tool is available — it is not a reason to stall a host that lacks it. If the deck yields no signal for a field, ask as normal. **Deriving some of the four does not license skipping the ask.** Treat them independently: a deck that evidences company, stage and sector but says nothing about geography leaves you asking for geography — not filling it in and moving on. Never record a value the materials do not evidence, and in particular **never read geography off a currency symbol** (`$` is also CAD, AUD and SGD, and founders everywhere price in USD) or off where the team used to work (an ex-Stripe engineer is not a US company). Geography selects which regulatory and benchmark guidance the whole review is graded against, so a silent guess there is not a small one.

**Stage is the exception to deck-derived pre-filling — it has a real fixed label set, not a value to read off a slide.**
Options: `Pre-seed` / `Seed` / `Series A` / `Series B+`
→ `pre-seed | seed | series-a | series-b` (`founder_context.py`'s `VALID_STAGES` has 7 values including `series-c`/`series-d`/`later`; on a `Series B+` pick, ask a plain-text follow-up rather than defaulting to `series-b`). This is `founder_context.py`'s company-stage field, distinct from the deck-scope `--rebuild-stage` enum the later Gate uses (`pre_seed`/`seed`/`series_a`/`series_b`/`growth`, at `:377` below) — the two do not share a value set. Provide at least 2 options. Stage is re-confirmed later by the Gate, so Step 1's stage answer is a prior, not a commitment. Then create:

```bash
python3 "$SHARED_SCRIPTS/founder_context.py" init \
  --company-name "Acme Corp" --stage seed --sector "B2B SaaS" \
  --geography "US" --artifacts-root "$ARTIFACTS_ROOT" \
  --run-id "$RUN_ID"
```

**Exit 2 (multiple):** Present the list, ask which company, re-read with `--slug`.

#### Execution checkpoint — END OF STEP 1, READ BEFORE CONTINUING

You now have enough to run. **Invoking this skill is not the same as running it.** From here, every
number that reaches the founder must come out of a producer script. Concretely:

- **Never compute a figure in chat.** Not TAM, not runway, not a ratio, not a benchmark comparison —
  not even one you are confident about. An in-chat number has no provenance, no range, no artifact, and
  nothing downstream can contradict it. That is worse than a slow answer and worse than no answer.
- **Never benchmark against a figure you recalled.** Benchmarks live in the reference files and the
  producers read them. If you find yourself writing "typically around X for this stage", stop: either a
  producer sourced it or it does not go in front of the founder.
- **A what-if, a sensitivity illustration, or "roughly what would X give" is NOT an exemption.** This is
  the exemption a live run invented: having correctly produced the real figure, it then wrote *"using the
  current count would shave TAM to roughly €249M rather than €270M"* — a second number, computed in chat,
  from an input the founder never gave. An illustrative figure is read exactly as confidently as a
  computed one, and the founder cannot tell which came from the pipeline. Two ways to answer a what-if:
  **re-run the producer with the alternate input** and quote its output, or **give no number** and say
  which direction it moves. Never arithmetic in prose.
- **Never offer the real run as an opt-in after answering.** "Here's a rough estimate — I can run the
  full analysis if you want" *is* the failure. The founder cannot tell that what they just read was not
  the analysis, so they will not ask for it.
- **Two ways to finish, and only two:** run the full pipeline to completion, or run the full pipeline after stating its cost up front (there is no quick lane here). Both end
  with real artifacts on disk. Anything else is not a finished run.
- **If you are blocked, say BLOCKED and say why.** A missing input, a failed hand-off, an unreadable
  document — name it and stop. Do not substitute your own reasoning for the pipeline and present the
  result as its output.

Artifact existence is the proof of execution: if no canonical artifact was written, the skill did not
run, whatever the transcript says.

### Step 2: Ingest Deck -> `deck_inventory.json`

**Ingestion pitfalls — common issues that degrade review quality:**

1. **PDF image-only slides:** Some PDFs embed slides as images with no extractable text. If Read returns blank or garbled content, note `input_quality: "image_only"` in `deck_inventory.json` and base the review on visual description + OCR-level best effort. Flag reduced confidence in coaching commentary.
2. **PPTX speaker notes vs. slide content:** Speaker notes often contain the real narrative; slide text is abbreviated. Extract both — notes go into `content_summary`, slide text into `headline`. Do not discard notes.
3. **Multi-file submissions:** Founder sends v1 + v2, or deck + appendix as separate files. Ask which is the primary deck before proceeding. Do not merge or review both simultaneously.
4. **Partial decks:** Deck has fewer than 5 slides or is clearly a subset. Proceed but set `confidence: "low"` in stage_profile and note the limitation. Missing-slides detection still runs normally.
5. **Wrong file type:** File named `.pdf` but is actually a Word doc or image. If Read fails, try alternate format before asking the founder for a re-upload.

Read the provided deck. For each slide, extract: headline, content summary, visuals description, word count estimate. Also determine `ai_company_status` using the two sub-questions below. Then write the inventory through the producer script:

**AI company classification (mandatory — field is required):** Answer two sub-questions:
1. Does the deck make an AI claim? (tagline, "AI-native"/"AI-powered" positioning, or AI in the product description)
2. Is there evidence AI is core? Use ALL FOUR signals: ML in value prop / inference-or-training in COGS / foundation-model or fine-tuning mentions / AI-specific retention metrics.

Map to `ai_company_status`:
- Evidence present (any core-AI signal) → `"ai_core"`
- AI claim but no core-AI evidence → `"ai_claimed_unverified"`
- No AI claim and not AI → `"not_ai"`

Record what evidence or claim was found in `ai_evidence` (required for `ai_core` and `ai_claimed_unverified`; brief for `not_ai`).

`claimed_stage` holds the stage token the deck itself states (`pre_seed`, `seed`, `series_a`, `series_b`, `growth`). If the deck never states a stage, **omit the field or set it to `null` — never invent a descriptive placeholder** (a made-up value misfires the stage cross-checks downstream).

```bash
cat <<'INVENTORY_EOF' | python3 "$SCRIPTS/deck_inventory.py" --run-id "$RUN_ID" -o "$REVIEW_DIR/deck_inventory.json" --pretty
{
  "company_name": "...",
  "review_date": "YYYY-MM-DD",
  "input_format": "pdf",
  "total_slides": 12,
  "claimed_stage": "seed",
  "claimed_raise": "...",
  "ai_company_status": "...",
  "ai_evidence": "...",
  "slides": [
    {"number": 1, "headline": "...", "content_summary": "...", "visuals": "...", "word_count_estimate": 15}
  ]
}
INVENTORY_EOF
```

The script validates against `references/schemas/deck_inventory.schema.json` and injects `metadata.run_id`. **Never write `deck_inventory.json` directly via heredoc** — the schema-validation gate is what keeps the pipeline honest.

### Step 3: Detect Stage -> `stage_profile.json`

Determine pre-seed/seed/series-a from signals in the deck. Read `references/deck-best-practices.md` for stage-specific frameworks. Record: detected stage, confidence, evidence, whether AI company, expected slide framework, stage benchmarks.

**Stage signals:** Pre-seed: no revenue, LOIs/waitlist, prototype, <$2.5M ask. Seed: early ARR, paying customers, <$6M ask. Series A: $1M+ ARR, cohort data, repeatable GTM, $10M+ ask. Later-stage: set detected_stage to `"series_b"` or `"growth"` — use the Gate below. Do not ask outside the gate.

**AI company note:** `ai_company_status` was determined in Step 2 (deck inventory) and is already in `deck_inventory.json`. Set `is_ai_company` in `stage_profile.json` to `true` if `ai_company_status` is `"ai_core"` or `"ai_claimed_unverified"`, otherwise `false`. Record the same evidence in `ai_evidence`.

Then write the profile through the producer script:

```bash
cat <<'PROFILE_EOF' | python3 "$SCRIPTS/stage_profile.py" --run-id "$RUN_ID" -o "$REVIEW_DIR/stage_profile.json" --pretty
{
  "detected_stage": "seed",
  "confidence": "high",
  "evidence": ["Claims $2M ARR", "..."],
  "is_ai_company": false,
  "ai_evidence": "...",
  "expected_framework": ["..."],
  "stage_benchmarks": {"round_size_range": "...", "expected_traction": "...", "runway_expectation": "..."},
  "reference_file_read": ["deck-best-practices.md", "checklist-criteria.md", "artifact-schemas.md"]
}
PROFILE_EOF
```

### Gate: Confirm Stage and Scope

**Sub-agent execution model:** sub-agents in Cowork cannot reliably call `AskUserQuestion`. The gate uses a checkpoint-and-resume pattern — the sub-agent writes a `gate_state.json` to disk and emits a structured `needs_input` payload as its final message. The parent (main thread or invoking agent) calls `AskUserQuestion` *if available* — or otherwise asks the founder via plain text — then writes the answer back into `gate_state.json` with `gate_state.py answer` (use exactly this flag shape):

```bash
python3 "$SCRIPTS/gate_state.py" answer \
  --file "$REVIEW_DIR/gate_state.json" \
  --run-id "$RUN_ID" \
  --answer "<the founder's chosen option, verbatim>"
```

then re-invokes this sub-agent. (`--file`, `--run-id`, `--answer`; `-o`/`--output` are accepted as aliases for `--file`, and `--run-id` is checked for parity against the gate's `metadata.run_id`.) The sub-agent detects re-invocation by checking whether `gate_state.json` already has an `answer` field. (The plain-text round-trip works correctly even without `AskUserQuestion`.)

**How to detect re-invocation:** you were re-invoked if `$REVIEW_DIR/gate_state.json` exists, has a non-empty `answer`, AND its `metadata.run_id` matches `$RUN_ID`. The run_id comparison is what distinguishes a genuine gate resume from a stale answered gate left by a *prior* completed run for the same company. (`setup_run.py` already deletes that stale file on a fresh run, but verify here as well.) Skip the gate-emit and read the answer:

```bash
python3 -c 'import json,sys
g=json.load(open(sys.argv[1]))
print(g.get("answer","") if g.get("metadata",{}).get("run_id","")==sys.argv[2] else "")' "$REVIEW_DIR/gate_state.json" "$RUN_ID" 2>/dev/null || true
```

If the previous Bash command printed a non-empty value, that is the gate answer — jump to "After the gate" below.

**Auto-satisfy branch — the founder already told you the stage in Step 1.** If Step 1's `AskUserQuestion`
captured a stage and the detected stage MATCHES it, do not ask again: write that answer straight through —
`gate_state.py emit` the gate exactly as below, then immediately `gate_state.py answer` it with
`"Looks right"` — and continue to "After the gate". Re-asking a
question the founder answered two minutes ago reads as not listening, and it is the single most common
reason a founder abandons a gated run.

Two conditions, both required, and neither is optional:

- **It must MATCH.** If Step 1 says seed and detection says Series A, that disagreement is exactly what
  the gate exists to surface — emit it normally and let the founder adjudicate.
- **Say that you did it.** The founder must see "you told me seed, and the deck agrees — proceeding on
  that" rather than the step silently vanishing. A gate that self-answers invisibly is indistinguishable
  from a gate that was skipped.

Anything other than a clean match — no Step 1 answer, a mismatch, or low-confidence detection — takes the
normal path below.

**Otherwise, write `gate_state.json` via the producer script and emit a needs_input payload:**

```bash
cat <<'GATE_EOF' | python3 "$SCRIPTS/gate_state.py" emit --run-id "$RUN_ID" -o "$REVIEW_DIR/gate_state.json" --pretty
{
  "gate_id": "stage_confirmation",
  "question": "Does this stage detection look right?",
  "options": ["Looks right", "Different stage", "Not sure — proceed anyway"],
  "context_summary": "Detected stage: Seed (high confidence). Key evidence: $4.2M ARR, 3 paying enterprise customers, $5M raise ask. AI company: Yes — inference costs in COGS. Expected framework: Sequoia seed (12-15 slides). Slides in deck: 14."
}
GATE_EOF
```

The script schema-validates the body and injects `metadata.run_id`. **Never write `gate_state.json` directly via heredoc.**

Then return — as your final assistant message — a JSON object the parent agent can act on:

```json
{
  "needs_input": {
    "gate_state_path": "<absolute path to gate_state.json>",
    "question": "Does this stage detection look right?",
    "options": ["Looks right", "Different stage", "Not sure — proceed anyway"],
    "context_summary": "..."
  },
  "review_dir": "<REVIEW_DIR>",
  "run_id": "<RUN_ID>"
}
```

**For out-of-scope stages (series_b, growth):** use `gate_id: "out_of_scope_choice"`, question `"This looks out of scope. What should I do?"`, options `["Stop review", "Different stage", "Proceed anyway (best-effort)"]`.

**After the gate (when the gate-check Bash command printed a non-empty answer):** branch on the printed value:

- `Looks right`: proceed to Step 4 with the detected stage.
- `Different stage`: emit a second gate (gate_id `stage_choice`) via `gate_state.py emit` to ask which stage. The candidates, each label with the `--rebuild-stage` token it maps to: Pre-seed (`pre_seed`), Seed (`seed`), Series A (`series_a`), Series B (`series_b`), Growth (`growth`) — that is the complete enum, and anything outside it fails argparse when the answer is rebuilt below. `AskUserQuestion` renders at most four options, so offer **exactly four: the enum minus the stage `stage_profile.json` currently holds.** Reaching this gate means the founder just rejected that stage, so it can never be the answer. **On a repeat pass, drop the stage the profile holds NOW**, not the one first detected — otherwise you re-offer what they just rejected and hide the one they now want. Never add an explicit `Other` — the tool supplies one. Treat this as a fresh gate — return a new `needs_input` payload and let the parent answer it the same way. When that one comes back answered, translate the founder's pick to its token and rebuild the profile for the chosen stage at **high** confidence (the founder explicitly picked it), then re-emit the original `stage_confirmation` gate to confirm:

  ```bash
  cp "$REVIEW_DIR/stage_profile.json" "$STAGING_DIR/sp.json"
  cat "$STAGING_DIR/sp.json" | python3 "$SCRIPTS/stage_profile.py" \
    --rebuild-stage <chosen-token> --confidence high \
    --run-id "$RUN_ID" -o "$REVIEW_DIR/stage_profile.json"
  ```

- `Not sure — proceed anyway`: proceed with the detected stage at **low** confidence:

  ```bash
  cp "$REVIEW_DIR/stage_profile.json" "$STAGING_DIR/sp.json"
  cat "$STAGING_DIR/sp.json" | python3 "$SCRIPTS/stage_profile.py" \
    --rebuild-stage <detected> --confidence low \
    --run-id "$RUN_ID" -o "$REVIEW_DIR/stage_profile.json"
  ```

- `Stop review` (out-of-scope): exit. Do not run later steps.
- `Proceed anyway (best-effort)`: rebuild the profile at **low** confidence with `--rebuild-stage series_a --confidence low` (same staged-stdin invocation as above).

`stage_profile.py` requires `--run-id` and `-o`, and reads the existing profile from stdin. Stage the current `stage_profile.json` to `$STAGING_DIR/sp.json` first and pipe *that* in — never `cat` and `-o` the same file in one command, which races and truncates it.

### Context A hand-off protocol (file transport + gate)

Every Context A dispatch prompt carries an `OUTPUT_PATH:` line built from `$HANDOFF_AGENT`. The
sub-agent WRITES its output JSON to that path with its Write tool and returns only a small receipt:
`{"status": "complete", "output_path": "<echo of OUTPUT_PATH>"}`. The payload leaves the model
exactly once (into the Write call) — never re-type sub-agent JSON into a heredoc.

**`$HANDOFF_AGENT` and `$HANDOFF_DIR` name the SAME directory by two different paths — they are not
interchangeable.** `$HANDOFF_DIR` is the absolute VM path your shell uses (`python3`, `check_handoff.py`,
producer pipes). `$HANDOFF_AGENT` is the relative path a sub-agent's file tools resolve against the
outputs mount, and it is the ONLY one that goes in a dispatch prompt. Putting `$HANDOFF_DIR` in an
`OUTPUT_PATH` line hands the sub-agent an absolute `/sessions/...` path the host-loop gate denies;
putting `$HANDOFF_AGENT` in a shell command resolves it against the wrong cwd. Rule of thumb: **agent
namespace in prompts, shell namespace in bash.**

**The receipt is the ONE exemption from the never-re-type rule.** "Never re-type" governs the
*payload* — the extraction JSON, the coaching commentary, anything the founder's numbers pass through.
The receipt is a two-field acknowledgement the sub-agent returns in its final message, and reading
`output_path` out of it to pass to `check_handoff.py --agent-path` is expected, not a violation. If it
were forbidden, the hand-off could not be gated at all.

**Path idiom for dispatch prompts (host-loop path gate):** `OUTPUT_PATH` and any under-outputs artifact
READ path a sub-agent is given are **relative to the sub-agent's file-tool cwd** (the outputs mount) —
built from the `resolve_artifacts_root.py --agent` namespace (`$HANDOFF_AGENT` / `$REVIEW_DIR_AGENT`).
Never hand a sub-agent an absolute `/sessions/...` path for a file-tool Read/Write — the host-loop path
gate denies it (steering shell work to the `bash` tool instead). Bundled `references/*.md` are the one
exception: pass them as the literal `${CLAUDE_PLUGIN_ROOT}/skills/deck-review/references/...` token (it is
pre-resolved to a host-readable path); do NOT substitute a `find /sessions`-discovered `$REFS` (a shell
path a file tool can't read).

**After EVERY Context A dispatch, gate before piping** (`<step>` = the dispatch's file stem):

```bash
printf '%s' '<agent final message verbatim>' | \
  python3 "$SHARED_SCRIPTS/check_handoff.py" "$HANDOFF_DIR/<step>_output.json" \
    --agent-path "$HANDOFF_AGENT/<step>_output.json" --receipt-json -
```
<!-- skill-quality-ci: bash-after-subagent-ok -->

Branch on the exit code (complete state machine — do not improvise):

- **Exit 0** → pipe the file through the producer: `cat "$HANDOFF_DIR/<step>_output.json" | python3 "$SCRIPTS/<producer>.py" ...`
- **Exit 3** (missing/empty file — receipt may be fabricated) → **redo-dispatch**: fresh Task, same prompt plus one line: "your receipt claimed a file at `<path>` but none exists; use Write to create exactly that path."
- **Exit 4** (file exists, invalid JSON) → **repair-dispatch**: fresh Task: "Read `<OUTPUT_PATH>`; it fails JSON parsing with `<verbatim detail from the diagnostic>`; fix and rewrite it; return the receipt."
- **Exit 5** (receipt echoes a different path) → **repair-dispatch** telling the agent the exact expected OUTPUT_PATH (it wrote somewhere else).
- **Exit 6** (receipt unparseable / no `output_path` key) → **redo-dispatch** with "return ONLY the receipt JSON — no fences, no prose."
- **Producer schema rejection** (the pipe fails next) → **repair-dispatch** with the producer's stderr verbatim.
- **Any other exit** (script crash etc.) → STOP with the stderr.
- **After ANY corrective dispatch, resume from `check_handoff.py`** — never pipe to the producer unchecked.

**Retry budget:** max **2 corrective dispatches per step, of any kind, in any combination** (max 3
total dispatches). After the second corrective dispatch fails any gate: STOP and report the exact
diagnostic to the founder. The main thread MUST NOT author or patch analytical content itself —
filling in the JSON is the fabrication failure mode this architecture exists to prevent. A
`status: "blocked"` return is not a gate retry, but it is bounded: at most ONE input-fix
re-dispatch per step; a second blocked return STOPs with both reasons quoted.

**Graceful degrade (fleet heterogeneity):** if the FIRST corrective dispatch also exits 3 while the
agent's receipt claims `complete` with the correctly echoed path, treat the host's filesystem
topology as hand-off-incompatible: fall back to message-channel transport for the REST of this run
(sub-agent returns full JSON in its final message; apply the tolerant JSON extraction protocol;
stage to `$STAGING_DIR/<step>_input.json`; same producer pipe), and note the fallback in your
final summary.

Retries overwrite the same OUTPUT_PATH (the mount is write-allowed / delete-denied — never `rm`
under `$REVIEW_DIR`). Hand-off files are not canonical artifacts: producers consume them only via
the explicit pipe, and `compose_report.py` never reads `handoff/`.

Ad-hoc scratch (NOT sub-agent hand-off) still goes to `$STAGING_DIR` in `/tmp` — see the reference
(`founder-skills/references/skill-execution-model.md`). Hard rule: never stage scratch anywhere under
the outputs mount (which includes `$REVIEW_DIR`), and never delete anything under it — see the
append-only rule in Step 0.

### Step 4: Review Each Slide -> `slide_reviews.json` (Context A dispatch)

**Dispatch the deck-review sub-agent in Context A (SLIDE_REVIEWS).** Do not do the slide analysis yourself in the main thread — dispatch it. **Call the `Task` tool with `subagent_type: "founder-skills:deck-review"`** and the prompt below, so the analysis runs in the scoped agent (its `tools:` allowlist binds; a type-less dispatch falls back to the wildcard `general-purpose` agent).

**Before dispatching, substitute placeholders in the template below:** replace `<HANDOFF_AGENT>` and `<REVIEW_DIR_AGENT>` with the agent-namespace values (from `resolve_artifacts_root.py --agent` — relative paths the sub-agent's file tools resolve against the outputs mount; NOT absolute `/sessions/...` paths, which the host-loop gate denies), `<RUN_ID>` with `$RUN_ID`, and inline the deck's full text under `DECK:` (the sub-agent needs verbatim figures — do not point it at an upload path). Leave the `${CLAUDE_PLUGIN_ROOT}/...` reference paths **literal** — they are pre-resolved to a host-readable path. The sub-agent has no access to your shell variables.

**Dispatch prompt template:**

```
CONTEXT: SLIDE_REVIEWS
OUTPUT_PATH: <HANDOFF_AGENT>/slide_reviews_output.json
RUN_ID: <RUN_ID>

You are the deck-review agent dispatched in Context A (SLIDE_REVIEWS). The deck's
full text is inlined below under DECK. Read the stage profile at
<REVIEW_DIR_AGENT>/stage_profile.json. Compare each slide against the stage-specific
framework and non-negotiable principles from
${CLAUDE_PLUGIN_ROOT}/skills/deck-review/references/deck-best-practices.md and
${CLAUDE_PLUGIN_ROOT}/skills/deck-review/references/checklist-criteria.md.

DECK:
<inline the deck's full extracted text here — verbatim, all slides>


For each slide: identify strengths, weaknesses, and specific recommendations.
Map to expected framework. Flag missing expected slides. Every critique must
cite a specific best-practice principle. When you reference deck figures, quote
them verbatim from the deck content — do not paraphrase or round numbers,
percentages, dates, or named metrics.

Use your Write tool to write to OUTPUT_PATH exactly the shape expected by
slide_reviews.py (no metadata block; the producer script adds it):
{
  "reviews": [
    {"slide_number": 1, "maps_to": "...", "strengths": ["..."],
     "weaknesses": ["..."], "recommendations": ["..."],
     "best_practice_refs": ["..."]}
  ],
  "missing_slides": [
    {"expected_type": "...", "importance": "important", "recommendation": "..."}
  ],
  "overall_narrative_assessment": "..."
}
`importance` must be exactly one of `critical`, `important`, `nice_to_have`
(underscores only).
All string values must be JSON-escaped (`\n` for line breaks, `\"` for embedded
quotes); the file must parse with a strict JSON parser.
Then return ONLY the receipt JSON in your final assistant message:
{"status": "complete", "output_path": "<echo of OUTPUT_PATH>"}
Do NOT write any file other than OUTPUT_PATH — canonical artifacts are
producer-script-only; anything else you write bypasses schema validation and
run_id stamping.
```

**After the sub-agent returns:** gate the hand-off per the Context A hand-off protocol, then pipe:

```bash
cat "$HANDOFF_DIR/slide_reviews_output.json" | \
  python3 "$SCRIPTS/slide_reviews.py" --run-id "$RUN_ID" -o "$REVIEW_DIR/slide_reviews.json" --pretty
```
<!-- skill-quality-ci: bash-after-subagent-ok -->

### Step 5: Score Checklist -> `checklist.json` (Context A dispatch)

**Dispatch the deck-review sub-agent in Context A (CHECKLIST).** **Call the `Task` tool with `subagent_type: "founder-skills:deck-review"`** and the prompt below. Substitute `<HANDOFF_AGENT>` / `<REVIEW_DIR_AGENT>` with the agent-namespace values and `<RUN_ID>` with `$RUN_ID`; leave the `${CLAUDE_PLUGIN_ROOT}/...` reference path literal (same idiom as SLIDE_REVIEWS).

**Dispatch prompt template:**

```
CONTEXT: CHECKLIST
OUTPUT_PATH: <HANDOFF_AGENT>/checklist_output.json
RUN_ID: <RUN_ID>

You are the deck-review agent dispatched in Context A (CHECKLIST). Evaluate all
35 criteria from ${CLAUDE_PLUGIN_ROOT}/skills/deck-review/references/checklist-criteria.md
using the deck content (read from <REVIEW_DIR_AGENT>/slide_reviews.json for
reference), the stage profile at <REVIEW_DIR_AGENT>/stage_profile.json, and the
deck inventory at <REVIEW_DIR_AGENT>/deck_inventory.json.

Assess ALL 35 criteria including the 4 AI criteria and the 5 Design & Readability
criteria — do NOT self-gate. `checklist.py` applies deterministic AI-criteria
gating from `deck_inventory.json`'s `ai_company_status` AND deterministic
Design-criteria gating from its `input_format` (forcing Design & Readability to
`not_applicable` when the deck was described in text rather than uploaded as a
file) after you return — assess every criterion regardless of format.

Evidence quality rules:
- Every fail and warn MUST cite a specific best-practice principle or benchmark.
- Every pass MUST note what was checked.
- not_applicable items MUST include a reason.
- Before asserting a visual or design element is absent (photos, charts,
  diagrams, logos), check the `visuals` field of every relevant slide in
  `deck_inventory.json` and cite the slide number(s) you checked in the evidence.

Evaluate every one of these 35 criteria — one item per id, no omissions, no
invented ids. Grouped by category:

Narrative Flow:
  - purpose_clear
  - headlines_carry_story
  - narrative_arc_present
  - strongest_proof_early
  - story_stands_alone
Slide Content:
  - problem_quantified
  - solution_shows_workflow
  - why_now_has_catalyst
  - market_bottom_up
  - competition_honest
  - business_model_clear
  - gtm_has_proof
  - team_has_depth
Stage Fit:
  - stage_appropriate_structure
  - stage_appropriate_traction
  - stage_appropriate_financials
  - ask_ties_to_milestones
  - round_size_realistic
Design & Readability:
  - one_idea_per_slide
  - minimal_text
  - slide_count_appropriate
  - consistent_design
  - mobile_readable
Common Mistakes:
  - no_vague_purpose
  - no_nice_to_have_problem
  - no_hype_without_proof
  - no_features_over_outcomes
  - no_dodged_competition
AI Company (score all 4; the producer script gates them after you return):
  - ai_retention_rebased
  - ai_cost_to_serve_shown
  - ai_defensibility_beyond_model
  - ai_responsible_controls
Diligence Readiness:
  - numbers_consistent
  - data_room_ready
  - contact_info_present

When you cite deck figures in evidence, quote them verbatim from the deck
content — do not paraphrase or round numbers, percentages, dates, or named
metrics.

Evidence prints VERBATIM in the founder's report, so name the source the way the
founder knows it — never by our filename or a dispatch label. They saw their deck,
not `deck_inventory.json` or `deck-best-practices.md`.
  Instead of: "slide_reviews.json shows no competition slide"
  Write:      "the deck has no competition slide"
State what is true of the DECK.


Use your Write tool to write to OUTPUT_PATH the items array without a summary
(the producer script computes the summary):
{"items": [{"id": "purpose_clear", "status": "pass", "evidence": "...", "notes": "..."}, ...all 35 items...]}
All string values must be JSON-escaped (`\n` for line breaks, `\"` for embedded
quotes); the file must parse with a strict JSON parser.
Then return ONLY the receipt JSON in your final assistant message:
{"status": "complete", "output_path": "<echo of OUTPUT_PATH>"}
Do NOT write any file other than OUTPUT_PATH — canonical artifacts are
producer-script-only; anything else you write bypasses schema validation and
run_id stamping.
```

**After the sub-agent returns:** gate the hand-off per the Context A hand-off protocol, then pipe through the producer script (with `--inventory` so the producer applies deterministic AI-criteria AND Design-criteria gating from `deck_inventory.json`):

```bash
cat "$HANDOFF_DIR/checklist_output.json" | python3 "$SCRIPTS/checklist.py" --run-id "$RUN_ID" --pretty \
  --inventory "$REVIEW_DIR/deck_inventory.json" \
  -o "$REVIEW_DIR/checklist.json"
```
<!-- skill-quality-ci: bash-after-subagent-ok -->

### Step 6: Compose Report

```bash
python3 "$SCRIPTS/compose_report.py" --dir "$REVIEW_DIR" --pretty \
  -o "$REVIEW_DIR/report.json" \
  --write-md "$REVIEW_DIR/report.md"
```

`compose_report.py` writes both `report.json` and `report.md` deterministically. **Do NOT** read `report_markdown` out of `report.json` and re-write it via heredoc — heredoc re-writing can corrupt `report.json`. Compose owns the file outputs.

High-severity warnings split into two kinds — treat them differently:

- **Pipeline-integrity** warnings (`CORRUPT_ARTIFACT`, `MISSING_ARTIFACT`, `STALE_ARTIFACT`, `SCHEMA_VIOLATION`, `MISSING_METADATA`, `AI_CRITERIA_MISSING`, `UNSUPPORTED_CHECKLIST_CRITIQUE`, `CHECKLIST_VALIDATION_FAILED`) mean the run itself is broken. Fix the underlying pipeline issue and re-run compose.
- **Content findings** (`CHECKLIST_FAILURES_CRITICAL`, and medium codes like `SLIDE_COUNT_EXTREME`, `STAGE_MISMATCH`) are the review's honest verdict about the deck. Report them to the founder as-is — never re-score, re-dispatch, or otherwise make them disappear.

**A warning code not named above is still real.** Treat it by what it is, never by
silence: fix it and re-run if the run itself is broken, otherwise say what it means
for the founder in plain language. A `FOUNDER_TEXT_TOKEN` naming an internal FILE is
the one to watch — that text is still in `report.md` and must be removed before you
hand anything over.


`--strict` counts content findings too, so use it as a pipeline gate only when the checklist outcome is already known-clean.

**Post-write verification:** `compose_report.py` exits non-zero (code 2) if the declared output files don't exist or are empty after writing. If compose exits non-zero, stop and report the exact stderr — do not proceed to Step 7.

### Step 7: Post-Compose Coaching Commentary (Context B dispatch — POST_COMPOSE_COACHING)

**Dispatch the deck-review sub-agent in Context B.** **Call the `Task` tool with `subagent_type: "founder-skills:deck-review"`** after `compose_report.py` has successfully written both `report.json` and `report.md`.

**Mitigation 2 protocol:** the main thread reads the structured `coaching_payload` from `report.json` and STAGES it as a file in the hand-off dir; the sub-agent Reads it from the agent namespace (a functionally required read, so a wrong prefix fails loudly before anything is written). The sub-agent does NOT Read full `report.md` — it consumes the staged `coaching_payload.json` directly, composes the coaching commentary, and **WRITES it as plain markdown to the `OUTPUT_PATH` hand-off file (a `.md` file) with its Write tool — no JSON, no escaping — returning only a small receipt** (the same file transport as Context A — the commentary leaves the model exactly once, into the Write call; the main thread never re-types it). The main thread gates that file with `check_handoff.py --format=markdown`, transforms it into the JSON transport envelope with `md_to_commentary.py` (deterministic escaping — `json.dumps` cannot emit malformed JSON), then pipes it into the shared `insert_coaching.py` script (idempotency matrix, uuid-marker replacement, run_id-parity verification — all deterministic, unchanged). See the deck-review agent body's "Context B — Post-compose coaching dispatch (POST_COMPOSE_COACHING)" section for the full procedure.

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

You are dispatched to add coaching commentary to a deck review.

The compose_report.py script has finished. The structured `coaching_payload` has
been STAGED AS A FILE for you — it is not inlined in this prompt.

Read the coaching payload at <HANDOFF_AGENT>/coaching_payload.json.

If that Read FAILS, write NO file and return exactly:
{"status": "blocked", "reason": "handoff_path_unresolvable", "attempted": "<the path you tried>"}
Do not Glob for it, do not guess a different prefix, do not proceed from memory —
a failed Read here means the hand-off prefix is wrong and the main thread must
re-issue the dispatch. Reporting it is the correct outcome.

Follow your agent body's Context B procedure (POST_COMPOSE_COACHING):

1. Compose commentary from the STAGED coaching_payload (failed_items,
   warned_items, summary, high_severity_warnings, stage, ai_company_status).
   Do NOT Read the full report.md. Do NOT edit report.md or any canonical artifact.
   The commentary is appended to the founder's report, so write it in their language:
   never a checklist item id (`STRUCT_03`), a status enum (`major_revision`), a warning
   code, or one of our filenames. Say what the finding IS.
     Instead of: "The `major_revision` verdict reflects STRUCT_03 failing"
     Write:      "The deck needs substantial work before it is ready to send"
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
    --verify-artifact "$REVIEW_DIR/deck_inventory.json" \
    --verify-artifact "$REVIEW_DIR/stage_profile.json" \
    --verify-artifact "$REVIEW_DIR/slide_reviews.json" \
    --verify-artifact "$REVIEW_DIR/checklist.json"
```

The gate (`check_handoff.py --format=markdown`) verifies the sub-agent's hand-off file exists, is non-empty, matches the receipt's echoed path, and passes the content-shape gate (not receipt-shaped, no marker collision); `md_to_commentary.py` wraps the raw markdown in the `{"commentary_markdown": ...}` envelope (escaping by construction via `json.dumps`); `insert_coaching.py` then performs the 6-state idempotency check, replaces the marker with `## Coaching Commentary` + the commentary in a single in-place write, and verifies `run_id` parity across all 4 producer artifacts. Branch on the exit code (complete state machine — do not improvise):

- **Exit 0 from the chain** — `insert_coaching.py`'s receipt on stdout says `inserted` (or `already_inserted` on a resume). Present `report_path` to the founder and proceed.
- **`check_handoff.py` exit 3** (missing/empty file — receipt may be fabricated) → **redo-dispatch**: fresh Task, same prompt plus one line: "your receipt claimed a file at `<path>` but none exists; use Write to create exactly that path."
- **Exit 5** (receipt echoes a different path) → **repair-dispatch** telling the agent the exact expected OUTPUT_PATH.
- **Exit 6** (receipt unparseable / no `output_path` key) → **redo-dispatch** with "return ONLY the receipt JSON — no fences, no prose." (A `status: "blocked"` final message is NOT exit 6 — it was handled before the gate.)
- **Exit 7** (content-shape gate failed — receipt-shaped or marker-bearing file) → **repair-dispatch**: "your file wasn't the coaching commentary — write the coaching markdown, nothing else, to `<OUTPUT_PATH>`."
- **Exit 8** (`path_namespace_mismatch`) → the sub-agent **complied**; the agent-namespace prefix was wrong. Its relative `OUTPUT_PATH` resolved against the outputs mount instead of the session root, so the file landed at the doubled path reported in `found_at`. Do NOT treat this as a fabricated receipt, and do NOT read the hand-off from `found_at` — re-dispatch with the corrected agent-namespace prefix (re-run `resolve_artifacts_root.py --agent` and rebuild `<HANDOFF_AGENT>` from the printed value). Counts against the same 2-dispatch retry budget.
- **`insert_coaching.py` exit 1** (blocked; stdout carries `{"status": "blocked", "reason": ...}`) → stop and report the exact reason. Do NOT hand-edit `report.md` — if the reason mentions a truncated report or a missing marker, re-run `compose_report.py --write-md` and retry the chain. If the reason is `commentary_markdown missing or empty`, treat as a malformed hand-off: repair-dispatch quoting the reason.
- **After ANY corrective dispatch, resume from the gate chain** — never feed the transform+insert pipe an ungated file.

**Retry budget:** max 2 corrective dispatches (same rule as Context A). **Graceful degrade:** if the FIRST corrective dispatch also exits 3 while the receipt claims `complete` with the correctly echoed path, treat the host topology as hand-off-incompatible and fall back to message-channel transport. **The corrective dispatch MUST ask for the commentary inline for this to be reachable** — add: "the file hand-off is not working in this environment; return the coaching commentary itself as your final message, as raw markdown, with no receipt JSON and no fences." Without that line the fallback is unreachable: the normal Context B prompt instructs the agent to return ONLY the receipt and not to narrate, so its final message contains no markdown to stage. Then stage that returned markdown to `$STAGING_DIR/coaching.md` via a **single-quoted** `<<'COACHING_EOF'` heredoc (apostrophe-safe; NEVER `python -c`, NEVER the `outputs/` root — `$STAGING_DIR` is the `/tmp` scratch dir from Step 0, never the promoted outputs mount), and run the same `md_to_commentary.py "$STAGING_DIR/coaching.md" | insert_coaching.py` chain against that staged file.

### Step 8 (Optional): Generate Visual Report

```bash
python3 "$SCRIPTS/visualize.py" --dir "$REVIEW_DIR" -o "$REVIEW_DIR/report.html"
```

**Do not hand this over here** — the Deliver step below is the only place work reaches the founder, and it sends the complete set as files. A path presented here is the partial-delivery bug.

### Step 9: Deliver Artifacts

Copy final deliverables to the **workspace root — `$ARTIFACTS_ROOT/..`, i.e. the promoted outputs mount itself, NOT `$ARTIFACTS_ROOT` and NOT `$REVIEW_DIR`**: `{Company}_Deck_Review.md`, `.html` (if generated), `.json` (optional). Concretely, if `$ARTIFACTS_ROOT` is `<mount>/artifacts` then these go to `<mount>/`. That is the level the founder sees as deliverable cards; `artifacts/` below it is working state. Do not infer the level by elimination — `dirname "$ARTIFACTS_ROOT"` is the answer.

**Send the finished work to the founder — the complete set, as files.** Not a path, and not a subset.
A path is not a deliverable in Cowork — whether the workspace it names outlives the task depends on how
that task was started, so a founder who was handed only a path may end up with nothing. (That is your
reason for sending files; it is not something to tell the founder — see the no-claims rule below.) Send
every finished document you produced for them, and frame them as results you generated rather than
something they asked to look at.

**Then hand them over by name — one link per document.** Sending the files and handing them over are
different acts: a founder looking at a row of cards cannot tell which document is which. Write each
deliverable into your message as its own named link — in Cowork, `computer://` followed by the
absolute path you just copied it to — labelled by what the document IS, in the founder's words:
*"Here's your finished analysis: [the written report](…) — everything scored, with the evidence
behind it; [the interactive version](…) has the charts."* "The files are above" is not a hand-over.
This does not conflict with the never-name-a-file rule: the founder reads your label, never the path.
Never paste a report's body into the message — link it.

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

**Do not `rm` anything under `$REVIEW_DIR`** — it is the promoted `outputs/` tree in Cowork, where
deleting a user-visible path is unsafe (and the parity gate flags it). Scratch already lives in
`$STAGING_DIR` (`/tmp`, reclaimed by the sandbox). The answered `gate_state.json` is left in place; a
later fresh review of this company is not misread as a resume because `setup_run.py --clean` deletes a
stale answered gate (run_id mismatch) at the start of the next run.

## Gotchas

- **"Looks polished" bias:** A well-designed deck is not a strong deck. Score content, narrative, and evidence independently of visual quality. The checklist separates design (5 items) from content (8 items) for this reason.
- **Template / AI-generated copy:** If multiple slides use generic phrasing ("revolutionize," "disrupt," "world-class team") with no specifics, flag this in coaching commentary as a credibility risk — investors notice formulaic decks. This is not a checklist item but affects overall narrative assessment.
- **Benchmarks are medians, not gates:** A $3M seed round in a $1B TAM market is not automatically wrong — context matters. Use benchmarks from `deck-best-practices.md` as reference points, not hard pass/fail thresholds. The coaching commentary should explain deviations rather than penalize them.
- **Founder provided text, not a file:** When the founder describes slides in conversation rather than uploading a file, adapt: write `deck_inventory.json` from the conversation, set `input_format: "text"`, and note reduced confidence in visual/design assessments. This is enforced deterministically, not just by prose: `checklist.py` reads `input_format` from `deck_inventory.json` (the same `--inventory` flag that drives AI-criteria gating) and forces the 5 Design & Readability criteria to `not_applicable` whenever it is `"text"`, regardless of what the sub-agent scored them. If the founder later shares screenshots, set `input_format` to whatever format now applies (e.g. `pdf`) so the gate does not fire and Design gets scored normally.
- **Cross-skill context:** If `founder_context.py` returned prior market-sizing or financial-model-review runs, mention relevant findings in coaching commentary (e.g., "Your market sizing calculated $X TAM — your deck claims $Y"). Do not hard-fail on discrepancies; flag them for the founder.

## Main-Thread Return

This skill runs inline in the main thread (not as a sub-agent). The final outcome the main thread delivers to the founder is:

- **In Claude Code:** the path to `$REVIEW_DIR/report.md` — there the path *is* the deliverable, because
  `./artifacts/` is durable. **In Cowork:** the delivered files are the deliverable; a path
  names a workspace that may not outlive the task.
- The headline outcome fields, sourced from the `coaching_payload` staged in Step 7 (`summary.score_pct`, `summary.overall_status`, `high_severity_warnings`) plus the `insert_coaching.py` receipt (`status`, `report_path`, `run_id`). The Context B sub-agent no longer echoes these — do not source them from its return.

  **Nesting matters here, and it is mixed — read the path, not the pattern:** `score_pct` and `overall_status` sit under `coaching_payload.summary`; reading `coaching_payload.score_pct` returns null while the real number sits one level down, and a live run did exactly that. But `high_severity_warnings` is **top level** — reaching under `summary` for it returns null too, in the opposite direction.
- Optionally: the HTML report path from Step 8.

**Do NOT inline `report_markdown` in the assistant message.** The founder reads the file via the path — inlining round-trips ~25 KB of markdown through the parent context for no benefit.

## Scoring

- Each of 35 items: pass / fail / warn / not_applicable
- `score_pct` = pass / (total - not_applicable) x 100
- Overall: "strong" (>=85%), "solid" (>=70%), "needs_work" (>=50%), "major_revision" (<50%)

## What-If Recomputation Rule

If the founder asks "what's my score if I fix X" or any score recomputation question: re-run `checklist.py` with the updated item statuses (or read the Appendix evidence from report.md) and present the script's output. Never compute a revised score by mental arithmetic in the chat — the formula is non-trivial (warn/fail earn no credit; N/A items are excluded from the denominator) and off-by-one errors cause real harm.

## Feedback

If a run ends **blocked or failed**, after you report the reason to the founder, add one line:
> _If this looks wrong or didn't finish, you can flag it: `/founder-skills:feedback`._

On **unsolicited** praise or frustration, you may mention `/founder-skills:feedback` once — never routinely, never mid-workflow, never more than once per session.
