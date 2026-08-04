---
name: competitive-positioning
description: "Maps a startup's competitive landscape, scores moat strength across 6+ dimensions, and generates an investor-ready competition narrative with positioning map. Run the verified scoring rather than assessing positioning from memory. Also covers plain-language questions with no brief attached — 'who else is doing this?', 'who are my competitors?', 'is that a real moat?' — which run verified research instead of recalled competitor names."
when_to_use: >
  Use ONLY when the user has asked for competitive landscape mapping,
  moat analysis, or positioning evaluation AND has provided enough
  context (a deck, a list of competitors, or a clearly named startup).
  Do not auto-invoke on general questions about competition or strategy.
  Moat scores and the competitor set are adversarially verified, which is what catches a plausible-looking competitor that does not actually compete — run this rather than assessing positioning from memory. Verbosity is not a reason to skip it.
user-invocable: true
---

# Competitive Positioning Skill

Help startup founders see their competitive landscape clearly — who the real competitors are, where they're differentiated, how defensible that differentiation is, and how to present it to investors. Produce a competitive analysis with positioning maps, moat scorecards, and an investor-ready narrative. The tone is founder-first: a coaching tool for preparation, not a judgment.

## Skill Metadata

- **Author:** lool-ventures
- **Version:** managed in `founder-skills/.claude-plugin/plugin.json`
- **Compatibility:** Python 3.10+ and `uv` for script execution.
- **Imports (optional):**
  - `deck-review:checklist.json` — competition slide claims for cross-validation
  - `market-sizing:sizing.json` — validate market claims in positioning
- **Exports:**
  - `landscape.json` → `deck-review`, `fundraise-readiness`
  - `report.json` → `ic-sim`, `fundraise-readiness`, `cross-document-consistency`

## Skill Execution Model (READ FIRST)

> See `founder-skills/references/skill-execution-model.md` for the full inline-skill execution model (3 dispatch contexts, Mitigation 1+2, producer contract, Cowork quirks, per-symptom triage).

This skill runs **inline in the main thread**, not as a sub-agent — see the reference above ("Why Inline (Not Forked Sub-Agent)") for the rationale. Sub-agents are deliberately shell-free, so orchestration (producer scripts, artifact persistence) stays in the main thread. **Network note:** this skill's Context A sub-agent declares `WebSearch` in its own tool allowlist and performs its own live competitor research (LANDSCAPE_RESEARCH, MOAT_SCORING, POSITIONING_SCORING) — the main thread does NOT need a research-before-dispatch pass; pass founder-provided context inline and let the sub-agent research.

**Two dispatch contexts for the sub-agent:**

- **Context A — Per-step analytical dispatch (Mitigation 1):** Steps 4 (LANDSCAPE_RESEARCH), 5 (MOAT_SCORING + POSITIONING_SCORING), and 6 (CHECKLIST) dispatch the competitive-positioning agent via the `Task` tool. The agent does deep analysis (including its own WebSearch research), WRITES its output JSON to the `OUTPUT_PATH` given in its prompt (the `handoff/` dir), and returns a small receipt. The main thread gates the file with `check_handoff.py`, then pipes it through the producer script (`validate_landscape.py`, `score_moats.py`, `score_positioning.py`, or `checklist.py`). The sub-agent never writes canonical artifacts — only its hand-off file.
- **Context B — Post-compose coaching dispatch:** Step 7 dispatches the sub-agent after `compose_report.py` writes `report.md`. The sub-agent Reads the staged `coaching_payload.json` from the hand-off dir (Mitigation 2) — it does NOT read the full `report.md` — composes the coaching commentary, WRITES it to the `OUTPUT_PATH` hand-off file, and returns a small receipt. The main thread gates the file (`check_handoff.py`) and inserts it via the shared `insert_coaching.py` script (idempotency matrix, uuid-marker replacement, run_id-parity verification — all deterministic). See the reference above for the full Context B contract.

**Tolerant JSON extraction protocol (Context B returns; also the Context A message-channel fallback):** capture the sub-agent's final assistant message. It should be raw JSON, but may be wrapped in ` ```json ... ``` ` fences or carry a prose preamble. Extract tolerantly:

1. If the message is wrapped in a ` ```json ... ``` ` (or plain ` ``` ... ``` `) fence, strip the fence first.
2. Try to parse the stripped text directly as JSON.
3. If that fails, walk through the text looking for the first `{` character and try `json.JSONDecoder().raw_decode(text[i:])` — this is brace-aware and handles nested objects correctly (unlike regex, which truncates on the first `}`).
4. If extraction fails entirely, re-prompt the sub-agent with: "Your previous reply could not be parsed as JSON. Return ONLY the JSON object — no markdown fences, no prose preamble."

Context A **receipts** don't need this protocol by hand — `check_handoff.py --receipt-json -` applies the same tolerant extraction internally; pass the final message verbatim.

## Input Formats

Accept any combination: pitch deck (PDF), competitive analysis document, text description of the product and market, prior deck-review or market-sizing artifacts, or conversational input. If a pitch deck is provided, extract competitor claims from the competition slide for validation.

## Available Scripts

All scripts are at `${CLAUDE_PLUGIN_ROOT}/skills/competitive-positioning/scripts/`:

- **`validate_landscape.py`** — Validates and normalizes competitor landscape; checks slug uniqueness, category distribution, research depth; emits warnings for quality issues
- **`verify_competitors.py`** — Validates the COMPETITOR_VERIFICATION sub-agent's per-competitor verdicts (genuine/adjacent/not_a_competitor); enforces the show-your-work gate (a flag must carry reasoning + independent buyer/job characterization), cross-checks landscape slug coverage, computes summary. Validator, not detector. `--blind-set` additionally diffs the COMPETITOR_RECALL agent's independently-derived set against the draft and emits `recall_gaps` (deterministic slug comparison; unsourced candidates dropped)
- **`score_moats.py`** — Validates per-company moat assessments, computes aggregates (moat_count, strongest_moat, overall_defensibility), produces cross-company comparison by moat dimension
- **`score_positioning.py`** — Scores positioning views with rank-based differentiation, detects vanity axes, passes through stress-test results
- **`checklist.py`** — Scores 25 criteria across 6 categories (pass/fail/warn/not_applicable) with mode-based gating by input_mode
- **`compose_report.py`** — Assembles report with cross-artifact validation; `--strict` exits 1 on high-severity warnings
- **`visualize.py`** — Generates self-contained HTML with SVG charts (not JSON)
- **`explore.py`** — Generates interactive HTML explorer with Chart.js scatter plot, view switching, bubble encoding controls, and company detail panels (not JSON)

Also available from `${CLAUDE_PLUGIN_ROOT}/scripts/` (shared):

- **`founder_context.py`** — Per-company context management (init/read/merge/validate)
- **`find_artifact.py`** — Resolves artifact paths by skill name and filename (for cross-skill lookups)

Run with: `python3 ${CLAUDE_PLUGIN_ROOT}/skills/competitive-positioning/scripts/<script>.py --pretty [args]`

## Available References

Read each when first needed — do NOT load all upfront. At `${CLAUDE_PLUGIN_ROOT}/skills/competitive-positioning/references/`:

- **`competitive-analysis-methodology.md`** — Read before Step 3. Axis selection, competitor categorization, stress-testing, investor expectations
- **`moat-definitions.md`** — Read before Step 5. Six canonical moat dimensions with scoring rubrics and stage-calibrated expectations
- **`checklist-criteria.md`** — Read before Step 6. All 25 checklist criteria with category definitions and mode-based gating rules
- **`artifact-schemas.md`** — Consult as needed when depositing agent-written artifacts

From `${CLAUDE_PLUGIN_ROOT}/references/` (shared): `stage-expectations.md`, `benchmarks.md`, `israel-guidance.md`

## Artifact Pipeline

Every analysis deposits structured JSON artifacts into a working directory. The final step assembles all artifacts into a report and validates consistency. This is not optional.

| Step | Artifact | Producer |
|------|----------|----------|
| 2 | `product_profile.json` | Agent (main) |
| 3 | `landscape_draft.json` | Agent (main) |
| 3.5 + 3.6 | `competitor_verification.json` | Parallel Context A dispatches: COMPETITOR_VERIFICATION (precision) + COMPETITOR_RECALL (recall) → one `verify_competitors.py` call |
| 4 | `landscape.json` | Context A dispatch: LANDSCAPE_RESEARCH → `validate_landscape.py` |
| 5a | `positioning.json` | Agent (main — views, moats, stress-tests) |
| 5b | `moat_scores.json` | Context A dispatch: MOAT_SCORING → `score_moats.py` |
| 5c | `positioning_scores.json` | Context A dispatch: POSITIONING_SCORING → `score_positioning.py` |
| 6 | `checklist.json` | Context A dispatch: CHECKLIST → `checklist.py` |
| 7 | `report.json` | `compose_report.py` reads all |
| 7d | `report.html` | `visualize.py` |
| 7e | `explore.html` | `explore.py` |

**Rules:**
- Deposit each artifact before proceeding to the next step
- For agent-written artifacts, consult `references/artifact-schemas.md` for the JSON schema
- If a step is not applicable, deposit a stub: `{"skipped": true, "reason": "..."}`
- **Do NOT use `isolation: "worktree"`** for sub-agents — files written in a worktree won't appear in the main `$ANALYSIS_DIR`

Keep the founder informed with brief, plain-language updates at each step. **Narrate the founder-visible OUTCOME, never the internal step.** That is the test to apply, and it catches more than a word list can: the forbidden thing is not a syntax, it is talking about the machinery. Bad — "Gating and piping the extraction through the producer, then staging the coaching hand-off"; good — "I've checked your numbers and I'm writing up what stood out." Bad — "schema-drift warning on `coaching_payload`"; good — nothing, because the founder has no stake in it. **Never name an internal artifact, field, or token** (a payload key, a marker name, an artifact filename, a hand-off dir) even in plain prose with no backticks — a detector keyed on syntax cannot see "gated", "hand-off" or "canonical artifacts", but the founder still reads them and they still mean nothing to them. **The between-step progress lines are the primary leak vector, not the final summary.** They feel internal — you are narrating what you are about to do — but the founder reads every one of them, and this is where the leaks actually appear: *"Now gating the hand-off before piping through the checklist producer"*, *"Gate 1 passes"*, *"Running the final verification gate"*. Rewrite each pipeline transition as the founder-visible outcome: *"Checking your numbers against the 46-point review"*, *"Your inputs look consistent — moving on to unit economics"*, *"Finishing up and putting the report together"*. If a progress line would mean nothing to someone who has never seen this skill's internals, it does not belong in the channel. Also excluded, as before: file/script names, paths, `*.py`, `--flags`, `$vars`, exit codes ("Exit N", "not found"), `W_`/`E_` codes, JSON, and step/route labels ("Lane N", "Context A/B", "Phase N", "structure detection", "the grid", any `ALL_CAPS_TOKEN`). After each analytical step (4-6), share a one-sentence finding before moving on. **The task tracker is founder-visible too — the same rule governs its labels.** "Gate the inputs review handoff", "Validate inputs.json", "resolve agent namespace paths", "Initialize founder context" are leaks even though each names a real step, and even when the prose around them is clean. Label each task by the founder-visible outcome — "Check your inputs", "Score against the review", "Write up what I found" — never by a file, directory, script, or pipeline stage. **The Coaching Commentary section appended to the report is founder-visible too — the same rule governs its text.** A checklist criterion ID (`NARR_03`) or an internal field name (`moat_count`) means exactly as little to a founder there as it does in a progress line, backticked or not — see the post-compose coaching dispatch template (Step 7c) for the specific instruction.

## Workflow

### Step 0: Path Setup

**Every Bash tool call runs in a fresh shell — variables do not persist.** Run the block below exactly **once**: it resolves `$PLUGIN_ROOT` deterministically, and every later block must substitute the printed value as a literal rather than re-running the resolution — repeating the self-heal search can land on a different mount than Step 0 picked when more than one is present (see why in the block's comments).

Optional, best-effort, and via the **Read tool** (not a shell command): before the block below, Read `${CLAUDE_PLUGIN_ROOT}/.claude-plugin/plugin.json` and note its `version` field as `EXPECT_VERSION`. Passing it to `select_plugin_root.py` below lets an exact version match win over an arbitrary first hit. If the Read fails, skip it and omit `--expect-version` — selection is still deterministic without it.

```bash
SCRIPTS="${CLAUDE_PLUGIN_ROOT}/skills/competitive-positioning/scripts"
if [ ! -d "$SCRIPTS" ]; then
  # In Cowork, CLAUDE_PLUGIN_ROOT substitutes to a host-side path absent inside
  # the session VM — self-heal by collecting EVERY candidate mount (a session can
  # have more than one at once: a stale host-side cache, a test marketplace, even
  # a symlink into a different session's tree) and handing them to
  # select_plugin_root.py, which picks ONE deterministically and names the
  # rejects — never trust `find`'s arbitrary first hit, which can silently mix
  # scripts across plugin versions mid-pipeline.
  CANDIDATES="$(find /sessions -type d -path '*/skills/competitive-positioning/scripts' 2>/dev/null)"
  [ -n "$CANDIDATES" ] || CANDIDATES="$(find / -type d -path '*/skills/competitive-positioning/scripts' 2>/dev/null)"
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
  SCRIPTS="$PLUGIN_ROOT/skills/competitive-positioning/scripts"
fi
PLUGIN_ROOT="${SCRIPTS%/skills/*}"
echo "PLUGIN_ROOT=$PLUGIN_ROOT"   # resolved ONCE, here — paste this literal into every later block; never re-run this resolution
REFS="$PLUGIN_ROOT/skills/competitive-positioning/references"
SHARED_SCRIPTS="$PLUGIN_ROOT/scripts"
SHARED_REFS="$PLUGIN_ROOT/references"
# Resolve the canonical artifacts root via a SCRIPT, not inline bash (the agent paraphrases inline
# path computations → outputs/ vs outputs/artifacts/ drift across runs). Deterministic + creates it.
python3 "$SHARED_SCRIPTS/resolve_artifacts_root.py"   # prints ARTIFACTS_ROOT — use the printed path verbatim as ARTIFACTS_ROOT in every later block (a captured var dies in the next fresh shell)
```

Reaching the self-heal branch is normal in Cowork — `${CLAUDE_PLUGIN_ROOT}` resolves to a HOST path that does not exist inside the VM, so the `[ ! -d "$SCRIPTS" ]` test fails by design rather than by misconfiguration. It is not a sign anything is wrong, and it is not worth narrating to the founder.

**Outputs mount is append-only.** Everything under the promoted outputs mount (`.../mnt/outputs/`, not just `$ANALYSIS_DIR`) is write-allowed and delete-denied by the platform: never `rm`, move away, or empty anything under it — **including files you created yourself**. Never create ad-hoc scratch anywhere under the outputs mount (no `_src/` copies, no run-state note files); scratch belongs in `$STAGING_DIR` (a `/tmp` dir, defined below). Do not "clean up" the outputs folder before delivering — extra working files there are expected and harmless.

**If `ARTIFACTS_ROOT` resolves to `./artifacts` but no `artifacts/` directory exists at `$(pwd)`:** The workspace may not be mounted yet. Use `Glob` with pattern `**/artifacts/founder_context.json` to locate existing artifacts, and derive `ARTIFACTS_ROOT` from the result. If nothing is found, `mkdir -p ./artifacts` and proceed.

After Step 1 (when the slug is known), derive `ANALYSIS_DIR`. **Two modes** — pick exactly one:

- **Full analysis** (default — the founder asked for a competitive analysis, a positioning map, a
  moat assessment, or a report, OR there is no existing full analysis for this slug): run Steps 2–10.
  `ANALYSIS_DIR="$ARTIFACTS_ROOT/competitive-positioning-${SLUG}"`.
- **Quick-check mode** — a single directional question in conversation with no request for an
  analysis ("who else is doing this?", "is 'we have better UX' a real moat?"). Run Step 5-quick
  instead of Steps 2–10.
  `ANALYSIS_DIR="$ARTIFACTS_ROOT/competitive-positioning-${SLUG}-quickcheck"`.

**Tie-breaker when both bullets seem to fit.** Decide on the **verb, not the inputs**: a request for the
work product ("map our competitive landscape, score our moats, build the competition slide") is a **full run** even when every number is already in hand, while a request for a
read ("who else is doing this, is that a real moat, ballpark") is a **quick check** even when materials are attached. Complete inputs make the full run
faster, not less wanted. When the verb is genuinely absent, default to the **full run** and say you did —
an unwanted full run costs time, an unwanted quick check costs the founder the analysis they came for.

**Never answer from your own recollection of the market.** Quick-check exists because the alternative
a model reaches for — listing competitors from memory and offering the real analysis as an opt-in —
produces an unverified competitor set under this skill's name, and a wrong competitor set is the one
error this skill exists to prevent. Running fewer producers is fine; running none is not.

#### Step 5-quick: the quick-check path

Run only the producer the question needs, on a landscape you actually researched:

```bash
# "Who competes with us?" -> research the landscape, then validate it.
printf '%s' "$QUICK_JSON" | python3 "$SCRIPTS/validate_landscape.py" --pretty \
  --run-id "$RUN_ID" -o "$ANALYSIS_DIR/landscape.json"
# "Is X a real moat?" -> score_moats.py on the single dimension in question.
```

**Producers deliberately NOT run:** `verify_competitors.py` (both the adversarial competitor-set check and the blind recall diff),
`score_positioning.py`, `checklist.py`, `compose_report.py`, `visualize.py`, `explore.py`, and the
Context-B coaching dispatch. No `report.md` is written.

**Same-numbers guarantee.** Whatever is scored is scored by the same producer the full analysis uses,
so the grades match — only the production weight is dropped, never the accuracy. What you do *not*
get is what the skipped producers add, and here the omission is unusually load-bearing: **the
competitor set has NOT been adversarially verified**, so a surface-level match that doesn't genuinely
compete can survive. Say so explicitly rather than letting the list read as vetted.

**Presenting it.** Label it a quick check, not an analysis. Then close with a **statement**, never a
question: "The full analysis adversarially verifies each competitor, scores six moat dimensions, and
produces a positioning map — say the word and I'll run it." A question invites a "no" to something the
founder would have wanted.

```bash
ANALYSIS_DIR="${ANALYSIS_DIR:-$ARTIFACTS_ROOT/competitive-positioning-${SLUG}}"              # full analysis
# ANALYSIS_DIR="${ANALYSIS_DIR:-$ARTIFACTS_ROOT/competitive-positioning-${SLUG}-quickcheck}"  # quick check
mkdir -p "$ANALYSIS_DIR"
RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
# Context A hand-off dir — PER RUN: sub-agents WRITE their raw output JSON here (the audit trail —
# raw sub-agent output as returned, before producer validation). Permanent by platform design
# (outputs/ mounts are write-allowed / delete-denied); nothing in it is ever a canonical artifact.
# The $RUN_ID segment is load-bearing: it prevents a stale prior-run file from silently passing
# the hand-off gate when a dispatch fails to write.
HANDOFF_DIR="$ANALYSIS_DIR/handoff/$RUN_ID"
mkdir -p "$HANDOFF_DIR"
# Sub-agents address the SAME dir by a different path (their file tools are rooted at the outputs
# mount in Cowork). Resolve the FULL agent-namespace paths via the script — never hand-splice the
# printed root with a literal skill-name/slug/run-id string yourself (that string-splicing is
# exactly the non-determinism the resolver script exists to remove):
python3 "$SHARED_SCRIPTS/resolve_artifacts_root.py" --handoff-dir-agent \
  --dir-name "competitive-positioning-${SLUG}" --run-id "$RUN_ID"   # prints HANDOFF_AGENT verbatim
HANDOFF_AGENT="<printed value>"   # use verbatim in OUTPUT_PATH lines
# Sub-agent READ paths for under-outputs artifacts use the SAME agent namespace (relative — the
# sub-agent's file-tool cwd IS the outputs mount on host-loop; an absolute /sessions/... read is denied):
python3 "$SHARED_SCRIPTS/resolve_artifacts_root.py" --analysis-dir-agent \
  --dir-name "competitive-positioning-${SLUG}"   # prints ANALYSIS_DIR_AGENT verbatim
ANALYSIS_DIR_AGENT="<printed value>"   # e.g. landscape_draft.json, positioning.json reads
# Ad-hoc scratch (NOT sub-agent hand-off) lives OUTSIDE the promoted outputs/ tree, in a temp dir
# that is safe to both create and reclaim. Use the printed path verbatim in later steps.
STAGING_DIR="$(mktemp -d "${TMPDIR:-/tmp}/competitive-positioning-${SLUG:-co}.staging.XXXXXX")"
```

Pass `RUN_ID` to all sub-agents. Every artifact must include `"metadata": {"run_id": "$RUN_ID"}`. `compose_report.py` checks run_id consistency — a mismatch triggers `STALE_ARTIFACT`. Its sibling integrity checks emit `CORRUPT_ARTIFACT` (artifact file is not valid JSON) and `UNVALIDATED_ARTIFACT` (artifact exists but was written directly instead of through its producer script — the `_produced_by` stamp is missing or wrong). All three are high-severity: fix the artifact by re-running the producer; never hand-edit it to silence the warning.

**Overwrite-in-place — do NOT delete prior artifacts under `$ANALYSIS_DIR`.** It is the promoted
`outputs/` tree in Cowork, where deleting a user-visible path is unsafe (Cowork can deny it; the parity
gate flags it). Each producer writes its artifact fresh via `-o` every run, and `RUN_ID` is minted fresh
per run — so if a prior run left an artifact a later step doesn't regenerate, `compose_report.py`'s
`STALE_ARTIFACT` check (run_ids must match) catches the mismatch. No bulk `rm` is needed or wanted.

### Step 1: Read or Create Founder Context

```bash
python3 "$SHARED_SCRIPTS/founder_context.py" read --artifacts-root "$ARTIFACTS_ROOT" --pretty
```

**Exit 0 (found):** Use the company slug and pre-filled fields. Proceed to Step 2.

**Exit 1 (not found):** Expected on a first run — do NOT mention this check or its exit status to the founder; if you narrate anything first, say only "Let me grab a few basics about the company." **Deck/materials carve-out — derive field-by-field, never all-or-nothing (do not ask for what you were already given):** if the founder provided materials (a deck, or a sufficiently detailed description), derive each of the four basics — company name, stage, sector, geography — that the materials state, and skip the gate entirely when all four are in hand. Treat the four **independently**: deriving three and missing one does NOT send you back to asking for all four. Before gating on a still-missing field, try to **infer** it from a clear signal in the materials and proceed (noting it as inferred, not founder-stated, so it isn't presented as confirmed): geography from a phone country code, office address, or currency (e.g. a `+972` number → Israel); stage from an ambiguous fundraise signal (a named round, round size, or "raising our seed" language → the matching `--stage` value); sector from the product category and ICP. Use `AskUserQuestion` (NOT plain chat) **only for** the specific field(s) that genuinely have no derivable or inferable signal — and ask for only those, stating the values you already derived so the founder confirms or corrects rather than re-supplying everything. **If `AskUserQuestion` is genuinely unavailable in the host, do NOT skip the ask and do NOT assume the answer:** ask the same question in plain chat, state the options explicitly, and wait for an answer before continuing. The ban above is on asking casually WHILE the tool is available — it is not a reason to stall a host that lacks it. (If none of the four can be derived at all, that reduces to asking for all four.)

**Stage is the one field with a real fixed label set — use it verbatim if asking.**
Options: `Pre-seed` / `Seed` / `Series A` / `Series B+`
→ `pre-seed | seed | series-a | series-b` (`founder_context.py`'s `VALID_STAGES` has 7 values including `series-c`/`series-d`/`later`; on a `Series B+` pick, ask a plain-text follow-up for the specific stage rather than defaulting to `series-b`). Company name, sector and geography cannot take fixed labels — shape each as an affirmative option carrying the derived value plus a stated-value fallback. Provide at least 2 options. Note in the report metadata that no cross-skill validation was performed. Then create:

`--stage` is enum-validated (hyphenated, lowercase) — one of: `pre-seed`, `seed`, `series-a`,
`series-b`, `series-c`, `series-d`, `later`. Passing a non-canonical token (e.g. `seriesa`,
`pre_seed`) is an argparse error and forces a retry — map the founder's answer to one of these
7 values before calling `init`.

`--sector-type` is an optional override (also enum-validated, hyphenated): one of `saas`,
`ai-native`, `marketplace`, `hardware`, `hardware-subscription`, `consumer-subscription`,
`usage-based`, `transactional-fintech`, `retail`. When omitted, `founder_context.py` auto-derives
it from `--sector` via a small alias table (e.g. "B2B SaaS" -> `saas`); if the sector doesn't match
a known alias, the script emits a runtime warning asking you to set `--sector-type` explicitly —
pick the closest value from the enum above rather than waiting for that warning.

```bash
python3 "$SHARED_SCRIPTS/founder_context.py" init \
  --company-name "Acme Corp" --stage seed --sector "B2B SaaS" \
  --geography "US" --artifacts-root "$ARTIFACTS_ROOT"
  # Add --sector-type <value> if the auto-derivation warning fires or the sector
  # doesn't map cleanly to one of the 9 canonical sector-type values above.
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
- **Two ways to finish, and only two:** run the full pipeline to completion, or run the quick-check path (Step 5-quick), which still runs a real producer. Both end
  with real artifacts on disk. Anything else is not a finished run.
- **If you are blocked, say BLOCKED and say why.** A missing input, a failed hand-off, an unreadable
  document — name it and stop. Do not substitute your own reasoning for the pipeline and present the
  result as its output.

Artifact existence is the proof of execution: if no canonical artifact was written, the skill did not
run, whatever the transcript says.

### Step 2: Build Product Profile -> `product_profile.json`

Extract from the founder's materials or conversation: company name, product description, target customers, value propositions, differentiation claims, stage, sector, business model, and input_mode (`"deck"`, `"conversation"`, or `"document"`).

**For deck mode:** Read ALL pages of the deck systematically — not just the competition slide. Problem, solution, traction, and team slides contain competitive claims and differentiation context that inform the analysis. If the deck has a competition slide, record it in `product_profile.json` under `deck_competition_slide` — `{axes: {x, y}, plotted: [{name, category}], claimed_position, source_slide}` — capturing the axis pair, which companies the slide plots and how it categorizes them, where it places the startup, and which slide number it came from; this generalises the earlier `deck_axes` field and is what makes the later competition-slide cross-check and the report's basis-vs-deck delta note possible. **If the deck has NO competition slide at all**, write the documented absent form instead of leaving the field out or inventing an unschema'd note field: `deck_competition_slide: {present: false, reason: "..."}`, stating plainly why (e.g. "12-page deck; no slide named or shaped as competition"). This is what lets the CHECKLIST dispatch grade the competition-slide cross-check as a **warn** with a real reason, instead of having nothing at all to check against — never `not_applicable`, which would drop it out of the score denominator and hide the finding. **Decks over ~10 pages:** the Read tool requires an explicit page range for PDFs beyond that length (max 20 pages per call) — read in page-range chunks (e.g. `pages: "1-10"`, then `"11-20"`) rather than one call for the whole file.

**Check the deck's vintage.** If a footer date, copyright year, event slide, or embedded metadata shows the materials are noticeably older than today (a rule of thumb: more than ~12 months), flag this to the founder before proceeding — competitor pricing, funding, and positioning claims from a stale deck may already be outdated. Note the observed vintage in `product_profile.json`'s `source_materials` (e.g. `"pitch deck (PDF, copyright 2024)"`).

Write `product_profile.json` to `$ANALYSIS_DIR`. Consult `references/artifact-schemas.md` for the schema. Set `INPUT_MODE` to the chosen mode (`deck`, `conversation`, or `document`) — Step 6's checklist pipe passes it to `checklist.py --input-mode` so mode gating is applied correctly:

```bash
INPUT_MODE="deck"   # or "conversation" / "document"
```

If materials are sparse, use `AskUserQuestion` to gather missing fields. At minimum: product description, target customers, and what the founder believes differentiates them. All three are necessarily runtime-labelled — open-ended founder-specific answers, not a set of labels a fixed list could offer — so each question needs an affirmative option carrying any partial signal already derived, plus a free-text fallback (same shape as the founder-context basics above), not a literal bracket list.

### Step 3: Identify Competitors -> `landscape_draft.json`

**REQUIRED — read `${CLAUDE_PLUGIN_ROOT}/skills/competitive-positioning/references/competitive-analysis-methodology.md` now.**

Identify 5-7 competitors across categories: 2-3 direct, 1-2 adjacent, 1 do-nothing, 0-1 emerging. For each competitor, record: name, slug, category, description, key differentiators, and why included.

**When one entry represents several companies as a cohort** (e.g. "PCM/next-gen entrants (Rondo, Antora, Sunamp)"), record the member company names in an optional `constituents: ["Rondo", "Antora", "Sunamp"]` array on that entry. This turns the blind-recall duplicate check (Step 3.6) from a text heuristic into an exact lookup — without it, a recall candidate that IS one of the cohort's named members can misread as a genuine gap.

Select 2-3 candidate positioning axis pairs with rationale for each. Follow the axis selection principles from the methodology reference — axes must differentiate, matter to the buyer, and be measurable.

If the founder's deck mentions competitors you are excluding from the formal landscape (e.g., too small, different market segment, or redundant with an included competitor), note them with reasons in `landscape_draft.json` under a `deck_competitors_excluded` field. These will be referenced in the report to maintain deck alignment and prevent the NARR_03 checklist item from failing without explanation.

Write `landscape_draft.json` to `$ANALYSIS_DIR`.

### Step 3.5: Adversarial Competitor Verification -> `competitor_verification.json` (Context A: COMPETITOR_VERIFICATION dispatch)

Before asking the founder to validate the set, independently challenge its **precision** — catch companies that landed in the draft on surface-level similarity ("both do scheduling") but don't actually compete. This runs as a **fresh, independent** Context A dispatch so the challenge is not self-review: the verification agent re-characterizes each competitor from its own WebSearch (deliberately NOT trusting the draft's `description`) and judges genuine overlap against the startup on a substitution test.

**Dispatch the competitive-positioning sub-agent in Context A (COMPETITOR_VERIFICATION).** **Call the `Task` tool with `subagent_type: "founder-skills:competitive-positioning"`.**

**Dispatch prompt template:**

```
CONTEXT: COMPETITOR_VERIFICATION
OUTPUT_PATH: <HANDOFF_AGENT>/competitor_verification_output.json
RUN_ID: <RUN_ID>

You are the competitive-positioning agent dispatched in Context A (COMPETITOR_VERIFICATION).
Read landscape_draft.json at <ANALYSIS_DIR_AGENT>/landscape_draft.json and
product_profile.json at <ANALYSIS_DIR_AGENT>/product_profile.json.

Follow your agent body's COMPETITOR_VERIFICATION subtype procedure: characterize
the startup once; then for EACH competitor in landscape_draft.json, use WebSearch
to independently establish its real buyer, job-to-be-done, category, and
monetization — do NOT trust the draft's description field. Apply the substitution
test (would the same buyer put both in the same consideration set for the same
job?). Shared category words are NOT sufficient. Assign verdict
genuine/adjacent/not_a_competitor. Every non-genuine verdict MUST carry non-empty
reasoning and a populated independent_characterization (buyer + job_to_be_done).

Use your Write tool to write to OUTPUT_PATH the JSON matching verify_competitors.py:
{
  "startup_characterization": {"buyer": "...", "job_to_be_done": "...", "category": "...", "monetization": "...", "evidence_source": "founder_provided"},
  "verdicts": [ {"slug": "...", "verdict": "...", "independent_characterization": {...}, "overlap": {...}, "reasoning": "...", "confidence": "...", "recommended_action": "..."} ],
  "metadata": {"run_id": "<RUN_ID>"}
}
One verdict per competitor slug in landscape_draft.json; no extras.
Then return ONLY the receipt JSON in your final assistant message:
{"status": "complete", "output_path": "<echo of OUTPUT_PATH>"}
Do NOT write any file other than OUTPUT_PATH.
```

**After the sub-agent returns:** gate the hand-off per the Context A hand-off protocol (defined below — `check_handoff.py`, branch on exit codes). **Do not pipe yet** — Step 3.6 dispatches in parallel with this one, and both hand-offs go through a single `verify_competitors.py` call there, producing one artifact for Gate 1 to read. `--landscape` will point at `landscape_draft.json` (the set as drafted; enrichment has not run yet).

If the producer exits 1 on a show-your-work violation (a flag with no reasoning or no independent buyer/job), re-dispatch per the retry budget with one added line: "your flagged verdict for `<slug>` had no reasoning / no independent buyer+job — re-characterize it from your own research." Never hand-author a verdict.

### Step 3.6: Blind Recall Check -> `recall_gaps` (Context A: COMPETITOR_RECALL dispatch)

Step 3.5 challenges the competitors that ARE on the list. This is its mirror: it asks who is
**missing**. Both run against the same draft, so **dispatch them in parallel — two `Task` calls in
one message**, exactly as Step 5 does for MOAT_SCORING + POSITIONING_SCORING. The recall result is
consumed after both return.

**Why a separate dispatch rather than one more instruction to an existing one.** Step 4's Phase B
also looks for missing competitors, but it runs inside the dispatch that just spent its whole context
enriching the draft, and it fires *after* Gate 1 — so it is anchored by construction and arrives
after the founder has already validated the set. This dispatch is unanchored and lands before the
decision.

**The blind is enforced by what the agent is given, not by asking it not to look.** Stage a
**redacted** product summary and pass that path — never `$ANALYSIS_DIR`:

```bash
python3 - "$ANALYSIS_DIR/product_profile.json" "$HANDOFF_DIR/recall_input.json" <<'PY'
import json, sys
src, dst = sys.argv[1], sys.argv[2]
p = json.load(open(src, encoding="utf-8"))
# Drop every field that carries a competitor set or the founder's framing of one.
# deck_competition_slide.plotted[] is literally a competitor list with categories.
for k in ("deck_competition_slide", "deck_axes", "differentiation_claims", "competitors"):
    p.pop(k, None)
json.dump(p, open(dst, "w", encoding="utf-8"), indent=2)
PY
```

Redacting `differentiation_claims` is deliberate: "unlike the big platforms, we…" names a competitor
class even when it names no company, and the point is an agent that reaches the market on its own.

**Dispatch prompt template:**

```
CONTEXT: COMPETITOR_RECALL
OUTPUT_PATH: <HANDOFF_AGENT>/competitor_recall_output.json
RUN_ID: <RUN_ID>

You are the competitive-positioning agent dispatched in Context A (COMPETITOR_RECALL).
Read ONLY <HANDOFF_AGENT>/recall_input.json. It is the only file you may read.

Follow your agent body's COMPETITOR_RECALL subtype procedure: establish the buyer
and job-to-be-done from that summary alone, then use WebSearch to find who that
buyer would realistically put in a consideration set for that job — direct
substitutes, adjacent tools, the incumbent, and the do-nothing/manual alternative.
Apply the substitution test.

Return 5-10 candidates, each with name, slug (kebab-case), category,
why_considered, and at least one source URL you actually retrieved. Return fewer
rather than padding — unsourced candidates are dropped downstream anyway.

Use your Write tool to write to OUTPUT_PATH:
{
  "candidates": [
    {"name": "...", "slug": "...", "category": "direct|adjacent|do_nothing|emerging",
     "why_considered": "why THIS buyer would weigh this for THIS job",
     "sources": ["https://..."]}
  ],
  "metadata": {"run_id": "<RUN_ID>"}
}
Then return ONLY the receipt JSON in your final assistant message:
{"status": "complete", "output_path": "<echo of OUTPUT_PATH>"}
Do NOT write any file other than OUTPUT_PATH.
```

**After both sub-agents return:** gate each hand-off per the Context A hand-off protocol, then pipe
BOTH through the one producer — the diff belongs with the verdicts, in one artifact, so Gate 1 reads
a single file:

```bash
cat "$HANDOFF_DIR/competitor_verification_output.json" | \
  python3 "$SCRIPTS/verify_competitors.py" --pretty --run-id "$RUN_ID" \
    --landscape "$ANALYSIS_DIR/landscape_draft.json" \
    --blind-set "$HANDOFF_DIR/competitor_recall_output.json" \
    -o "$ANALYSIS_DIR/competitor_verification.json"
```
<!-- skill-quality-ci: bash-after-subagent-ok -->

**If the recall dispatch fails or returns nothing usable, continue without it** — pipe without
`--blind-set` and proceed to Gate 1. A missing recall check degrades the analysis; it must never
block a run that is otherwise complete.

### Gate 1: Founder Validation of Competitor Set

**MANDATORY STOP — TWO SEPARATE STEPS. DO NOT COMBINE THEM.**

**Step A: Output a chat message** with the competitor list and candidate axes. Use a markdown table or formatted list. This is a normal assistant message — NOT an AskUserQuestion call.

**Include the Step 3.5 challenges.** Read `competitor_verification.json`. If `summary.flagged` > 0, add a **"Companies I'd challenge"** block under the list — for each slug in `summary.flagged_slugs` **whose verdict does NOT match its draft category**, one line drawn from that verdict's `reasoning`: `• <name> — I don't think this genuinely competes: <reasoning>. Keep it, drop it, or call it adjacent?`. **Skip a flagged slug whose verdict matches its draft category** (e.g. a draft-adjacent entry independently confirmed adjacent) — that entry was correctly categorized, so the "I don't think this genuinely competes" framing is wrong for it and it needs no line here. If nothing remains to challenge after that filter, the line depends on WHY nothing remains — these are not interchangeable: if `summary.flagged` is 0 (nothing was ever flagged), add: "All <N> look like genuine competitors — none flagged." If `summary.flagged` is greater than 0 but every flagged entry was filtered out because its verdict matched its draft category (correctly categorized, not actually a challenge), add instead: "<summary.flagged> came up for a second look during verification, but each held up under independent research — nothing to challenge." Using the "none flagged" line in the second case is false — a competitor WAS flagged, it just turned out to be correctly categorized already.

**Include re-categorizations, in both directions.** Read `summary.category_disagreements`. Each entry pairs a competitor's drafted category against what independent research found, tagged `upgrade` (research says it's a stronger, more genuine competitor than drafted) or `downgrade` (research says it's weaker or less relevant than drafted). If any exist, add a **"Companies I'd re-categorise"** block under the challenges — one line per entry: for an upgrade, `• <name> — I drafted this as <drafted category>, but research says it's a more direct competitor than that.`; for a downgrade, the mirror: `• <name> — I drafted this as <drafted category>, but research says the overlap is weaker than that.` **An upgrade cuts against the startup — a competitor turning out stronger than drafted — so it must never be presented more quietly than a downgrade;** give both the same visibility and phrasing weight.

**Include the Step 3.6 recall gaps.** Read `recall_gaps` from the same file. If `unmatched` is non-empty, add a **"Companies you may be missing"** block — one line per entry: `• <name> — <why_considered> (<first source>)`. Frame these as candidates found by an independent search that never saw your list, not as omissions the founder got wrong.

Two rules on this block. **Never present `draft_only` as a challenge** — the blind agent failing to surface a competitor is weak evidence of nothing, and Step 3.5's verdicts are the instrument for that question. And **respect the cap**: the set may hold at most 10 competitors (`validate_landscape.py`'s `MAX_COMPETITORS`). Count the current draft; if adding every candidate would exceed 10, say so plainly in this block — `I found <N> more, but the set is full at 10 — which matter most?` — rather than offering additions that cannot be applied.

**Step B: AFTER the chat message, call `AskUserQuestion`** with a short question that **names what's being confirmed** so the founder isn't confirming blind. The question is plain text — still ONE SENTENCE, NO markdown/tables/bullets — but it MUST carry the key facts: the competitor **count**, any names you'd **challenge**, and any **upgrades** from the re-categorization check (downgrades stay in the Step-A message only — they don't change the risk picture the way an upgrade does).

Question (substitute `<N>`, the flagged names, and any upgraded names; drop each parenthetical that has nothing to report): `Found <N> competitors (I'd challenge: <names>) (stronger than drafted: <upgraded names>) — does this set look right?`
Options: `No changes — looks good as drafted` / `Missing competitors` / `Remove some` / `Change axes`

**The no-change option carries the reserved prefix `No changes — `, and exactly one option may.** Whichever slot it lands in, that is the branch a founder picks to leave things as they are, and it must be identifiable without counting positions. Any option that adds, removes, or re-categorises a competitor, changes an axis, or changes the scoring basis is FORBIDDEN from using the prefix. The tail after the dash is yours — name the actual candidates, that is what makes these gates good. Measured across live runs, slot 1 was the accept branch on some runs and an *adds-two-competitors* branch on others while every option still opened "Looks good": position is not a safe handle and neither is a shared prefix that mutating options also carry. This one is safe because it is reserved.

**CRITICAL: the question must be self-contained on the decision (count + flagged names + upgrades), as ONE plain-text sentence. The full table/rationale stays in the Step-A chat message — do NOT put a table or markdown in the question.**

If founder requests changes, apply corrections and repeat Steps A+B.

Apply all corrections to `landscape_draft.json` before proceeding. **This is also how an approved recall candidate enters the set** — add it to `landscape_draft.json` as a draft entry (name, slug, category, description, `key_differentiators`, plus `why_included` citing the recall check), and Step 4 then enriches it like any other draft entry. Do not route it through Step 4's `suggested_additions` promotion path: that path operates on the *Step 4 output's* additions and does not exist yet at this point in the run. Never exceed `MAX_COMPETITORS` (10) — if the founder approves more than the remaining slots, ask which to keep rather than silently truncating.

**A recall candidate the founder does NOT approve is not simply dropped.** Write it into `landscape_draft.json`'s top-level `deferred_recall_candidates[]` array — `{name, slug, category, why_considered, sources}`, copied from how the recall dispatch returned it — rather than discarding it. Step 4's additions gate below draws candidates from this array too, so a declined recall candidate stays reachable if the analysis later needs it, instead of becoming permanently unaddable the moment Step 4's own `suggested_additions` fill the remaining slots.

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
built from the `resolve_artifacts_root.py --agent` namespace (`$HANDOFF_AGENT` / `$ANALYSIS_DIR_AGENT`).
Never hand a sub-agent an absolute `/sessions/...` path for a file-tool Read/Write — the host-loop path
gate denies it (steering shell work to the `bash` tool instead). Bundled `references/*.md` are the one
exception: pass them as the literal `${CLAUDE_PLUGIN_ROOT}/skills/competitive-positioning/references/...` token (it is
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

**Mechanical fix vs. content authoring (the carve-out to the rule above):** "must not author or
patch analytical content" means the main thread never invents a finding, evidence string, score, or
verdict the sub-agent didn't produce. It does NOT forbid **mechanical** operations that move or
rename data the sub-agent already produced, unchanged in substance:

- Renaming a near-miss field to its canonical name (e.g. auto-normalizing a schema-adjacent key)
  when the producer script does it deterministically — you are not authoring content, the script is
  normalizing a name.
- Merging the sub-agent's own gated hand-off content into a canonical artifact per an explicit
  SKILL.md instruction (e.g. the Step 5 points merge below, or merging approved
  `suggested_additions` in Step 4) — you are relocating data the sub-agent wrote, not writing new
  data yourself.

**Promoting an approved `suggested_addition` into `competitors[]` — enrichment is the promotion path.**
Moving the entry is a relocation (permitted above), but the target shape has a field the suggestion
does not: `key_differentiators`. A suggestion that was never enriched has none, and writing one is
content authoring — so promotion cannot happen by stub-filling the field. **Re-dispatch
`LANDSCAPE_RESEARCH`, scoped to the approved addition(s) by name**, and let the sub-agent enrich them
the same way it enriched the original draft: real `key_differentiators`, `research_depth`,
`sourced_fields_count`, and `evidence_source` per field, each sourced. Then promote the enriched
result — copy `name` / `slug` / `category` / `partial_profile` across along with the newly-researched
fields. (The producer accepts `key_differentiators: []` only when `research_depth` is `"partial"`; it
rejects an empty list when `research_depth` is `"full"`, so a thin re-dispatch still needs at least a
partial research pass before it can be promoted.)

If you find yourself typing a NEW evidence string, score, or verdict that didn't come from a gated
sub-agent artifact, that is content authoring and is forbidden — repair-dispatch instead.

**Graceful degrade (fleet heterogeneity):** if the FIRST corrective dispatch also exits 3 while the
agent's receipt claims `complete` with the correctly echoed path, treat the host's filesystem
topology as hand-off-incompatible: fall back to message-channel transport for the REST of this run
(sub-agent returns full JSON in its final message; stage to `$STAGING_DIR/<step>_input.json`; same
producer pipe), and note the fallback in your final summary.

Retries overwrite the same OUTPUT_PATH (the mount is write-allowed / delete-denied — never `rm`
under `$ANALYSIS_DIR`). Hand-off files are not canonical artifacts: producers ignore them except
via the explicit pipe, and `compose_report.py` never reads `handoff/`.

Ad-hoc scratch (NOT sub-agent hand-off) still goes to `$STAGING_DIR` in `/tmp` — see the reference
(`founder-skills/references/skill-execution-model.md`, "STAGING_DIR pattern for ad-hoc/scratch
files"). Hard rule: never stage scratch anywhere under the outputs mount (which includes `$ANALYSIS_DIR`), and never delete anything under it — see the append-only rule in Step 0.

### Step 4: Research & Enrich Competitors -> `landscape.json` (Context A: LANDSCAPE_RESEARCH dispatch)

**Dispatch the competitive-positioning sub-agent in Context A (LANDSCAPE_RESEARCH).** The sub-agent declares `WebSearch` in its tool allowlist and performs the research itself. **Call the `Task` tool with `subagent_type: "founder-skills:competitive-positioning"`** so the research runs in an isolated context.

**Dispatch prompt template:**

```
CONTEXT: LANDSCAPE_RESEARCH
OUTPUT_PATH: <HANDOFF_AGENT>/landscape_research_output.json
RUN_ID: <RUN_ID>

You are the competitive-positioning agent dispatched in Context A (LANDSCAPE_RESEARCH).
Read landscape_draft.json at <ANALYSIS_DIR_AGENT>/landscape_draft.json and
product_profile.json at <ANALYSIS_DIR_AGENT>/product_profile.json.

You do NOT need to carry landscape_draft.json's deferred_recall_candidates array
through — the producer reads it directly. Ignore that field.

Phase A — Enrich existing competitors: For each competitor in landscape_draft.json,
use WebSearch to find pricing model, funding history, team size, target customers,
strengths, weaknesses. Issue separate searches per competitor as needed. Record
evidence_source per field: "researched" only when the value came from a WebSearch
result; "agent_estimate" when you fell back to training-cutoff knowledge.
Set research_depth per competitor — MUST be one of: full, partial, or
founder_provided. Set sourced_fields_count per competitor = the number of that
competitor's fields you stamped evidence_source:"researched" (an integer);
validate_landscape.py requires this field. Separately, compose_report.py's
SHALLOW_COMPETITOR_PROFILE warning fires for a "partial" competitor with fewer
than 3 sourced fields. For every field stamped
evidence_source:"researched", also add a matching entry in a "sources" object
(same field-name keys) citing the URL or the exact search query that produced it
— the main thread never sees your WebSearch results, only this artifact, so an
unsourced "researched" claim can't be spot-checked later. validate_landscape.py
warns (does not fail) on a "researched" field with no matching "sources" entry.

Also capture recent_developments[] per competitor where you find them: discrete DATED
moves (funding, pricing_change, product_launch, market_move, acquisition, leadership,
layoff) each with date (YYYY-MM or YYYY-MM-DD), summary, a source URL, and optional
relevance. A URL is required — a search query is not a valid source for a dated claim
about a named company — and evidence_source "agent_estimate" is rejected for this field.
An EMPTY ARRAY IS CORRECT for a competitor that has not visibly moved; do not stretch to
fill it. A present-tense fact is enrichment, not a development — only a dated change.
**recent_developments[] has an 18-month recency window** (validate_landscape.py rejects
anything dated more than 18 months before the as-of date, though it now retains a
rejected entry separately rather than failing the run). If a real, sourced, relevant
event falls outside that window, do NOT stretch to include it here — give it a legal
home instead: fold it into that competitor's top-level `description` or `weaknesses`
prose, where there is no recency bound. Dropping an older-but-relevant fact entirely is
the failure this note exists to prevent.

Phase B — Gap detection: After enriching, check for missing competitor categories.
Use WebSearch ("<product category> competitors", "<adjacent category> tools", etc.)
to discover competitors absent from the draft. Add them to suggested_additions[]
with merged: false. Do NOT add to competitors[] — only to suggested_additions[].

Use your Write tool to write to OUTPUT_PATH — exactly the shape expected by
validate_landscape.py:
{
  "competitors": [
    {"...": "...enriched fields, NOT new competitors...",
     "research_depth": "full",
     "sourced_fields_count": 4,
     "evidence_source": {"pricing_model": "researched", "funding": "agent_estimate"},
     "sources": {"pricing_model": "https://example.com/pricing OR the exact search query used"}}
  ],
  "suggested_additions": [
    {"name": "Wallarm", "slug": "wallarm", "category": "direct",
     "rationale": "why this belongs — the field is `rationale`, NOT `why_suggested`",
     "partial_profile": {"description": "...", "funding": "..."},
     "merged": false}
  ],
  "suggested_axes": [],
  "assessment_mode": "sub-agent",
  "research_depth": "full",
  "input_mode": "<from product_profile>",
  "metadata": {"run_id": "<RUN_ID>"}
}
Then return ONLY the receipt JSON in your final assistant message:
{"status": "complete", "output_path": "<echo of OUTPUT_PATH>"}
Do NOT write any file other than OUTPUT_PATH — canonical artifacts are
producer-script-only; anything else you write bypasses schema validation and
run_id stamping.
```

**After the sub-agent returns:** gate the hand-off per the Context A hand-off protocol. Read `suggested_additions` from the gated file, and read `deferred_recall_candidates` from `landscape_draft.json` (declined Gate-1 recall candidates — see Gate 1 above). **The two compete for the same open slots — build one candidate pool as `suggested_additions[]` ∪ `deferred_recall_candidates[]`.** **If that pool is empty, skip straight to piping below — there is nothing to gate.** If it is non-empty:

**Before the gate, compute the open slots:** `slots = 10 (the landscape maximum from the methodology reference) - len(competitors)`, counting only entries already in `competitors[]`. This is what makes the gate's options runnable — an option that cannot execute must never be offered.

**MANDATORY STOP — TWO SEPARATE STEPS, same pattern as Gates 1 and 2.** This is a real decision point, not a formality — do not conflate the two steps or skip either one.

**Step A: Output a chat message** listing each candidate in the pool — a `suggested_additions[]` entry with its name, category, and gap-detection rationale, or a `deferred_recall_candidates[]` entry with its name, category, and `why_considered`. **If the number of candidates exceeds the open slots, say so plainly** — e.g. "You're already at <len(competitors)> of the 10 I can track, so at most <slots> of these can be added" — so the founder understands the constraint before choosing. **Also note that including any of these means another research pass, a couple of minutes** — so the choice is informed on cost as well as value.

**Consolidation merges — when research shows two already-confirmed competitors are now one company.** Research sometimes finds that two entries already in `competitors[]` have become a single corporate entity (an acquisition or merger, not a new competitor). This is report-only by default — never merge automatically. If it comes up, add a line to the Step-A chat message naming both entries, the finding, and its citation (e.g. "My research also found that <A> and <B> are now one company as of <date>, per <source> — want me to combine them?"). Only on founder approval, execute the merge by **re-dispatching `LANDSCAPE_RESEARCH`** with an instruction to combine the two named competitors into one sourced, cited entry — never by hand-editing either entry's fields in the main thread, which is content authoring, not the mechanical relocation the carve-out above permits. This is also the mechanism behind the `Free a slot by merging` option below.

**Step B: AFTER the chat message, call `AskUserQuestion`** — plain text, one sentence, no markdown/tables. Pick the question and options by comparing the number of suggested additions to the open slots:
- **suggestions fit within the open slots:** `Found <N> more competitors during research — include any?` Options: `Include all` / `Include some` / `No changes — skip these`.
- **some, but not all, fit:** `Found <N> more competitors during research, but only <slots> more fit — include any?` Options: `Include top <slots>` / `Include some` / `No changes — skip these`.
- **no slots are open, and a consolidation candidate exists:** `Found <N> more competitors during research, but the set is already full — want to free up a slot?` Options: `No changes — skip these` / `Free a slot by merging`. Offer this **only** when a consolidation candidate exists (see "Consolidation merges" above).
- **no slots are open and there is no consolidation candidate: do NOT ask.** Every branch would land on the same outcome, and `AskUserQuestion` cannot render a one-option gate — it requires at least two. Instead say it plainly in the Step-A message, exactly as Gate 1 does when additions would exceed the cap: name the competitors research found, state that the set is full at 10 and nothing can be added without removing something, and continue. **Naming them is not optional** — dropping the gate is fine, dropping the finding is not, and a founder who is never told what research surfaced is worse off than one asked a broken question.

`Include all` must never appear when it cannot execute (suggestions exceed the open slots), and never render `Include top 0` — that case collapses into the no-slots-open row above. If "Include some" or "Include top <slots>," follow up asking which by name. The labels are runtime data — the candidates are whatever research surfaced or the founder previously declined — so build them from the pool (`suggested_additions[]` ∪ `deferred_recall_candidates[]`): **one option per candidate, labelled with that competitor's name**, capped at the open slots (never offer more than can be added), plus a final `None of these` when fewer than four candidates fill the list. Never ask this as bare free text: a name typed from memory can miss the slug the enrichment re-dispatch needs.

**A raw `suggested_additions` entry cannot be piped into `competitors[]` as-is.** It has no `key_differentiators`, no `research_depth`, and its `description` sits inside `partial_profile` — piping it verbatim hits `validate_landscape.py`'s required-field check and fails. If the founder approves additions, promote them via the enrichment path (see "Promoting an approved `suggested_addition` into `competitors[]`" in the Context A hand-off protocol above), in this order:

1. **Re-dispatch `LANDSCAPE_RESEARCH`, scoped to the approved addition(s) by name**, to a fresh `OUTPUT_PATH` (e.g. `<HANDOFF_AGENT>/landscape_research_enrichment_output.json`). The sub-agent enriches each approved addition the same way it enriched the original draft — real `research_depth`, `key_differentiators`, per-field `evidence_source`/`sources`, and a top-level `description`.
2. Gate that hand-off per the Context A hand-off protocol, same as any other dispatch.
3. Write a merged copy to `$STAGING_DIR/landscape_input.json`: start from the original hand-off file's contents, and for each approved addition replace its `suggested_additions[]` entry with the corresponding enriched entry from step 1, relocated into `competitors[]`.
4. Pipe `$STAGING_DIR/landscape_input.json` through `validate_landscape.py` — this replaces the bash block below for this branch. **Pass the same `--carry-deferred` / `--derive-deferred` flags the block below uses**, so a declined candidate survives this branch too.

**Why those two flags exist rather than an instruction.** Declined recall candidates used to reach
`landscape.json` by being written into `landscape_draft.json` at Gate 1 and copied through by the
research sub-agent. Measured across two live runs, BOTH hops failed — in one the sub-agent dropped
the field, in the other the main thread created the key and left it empty — so the producer now reads
the draft itself, and falls back to deriving the set from the blind-recall diff (a candidate still
absent from `competitors[]` was not adopted; adoption is the only way one leaves). Nothing about this
depends on a model remembering to copy a field it has no other reason to touch.

**Promoting a `deferred_recall_candidates[]` entry uses this same enrichment re-dispatch path, unchanged** — a declined recall candidate approved later has no `suggested_additions[]` entry to replace in step 3, so relocate the enriched result directly into `competitors[]` instead, and remove the promoted candidate from `landscape_draft.json`'s `deferred_recall_candidates[]` so it is not offered again on a future run.

With no approved additions (or none suggested), pipe the hand-off file directly, unchanged — that is the bash block below.

**Retain the declined ones — do not discard them.** Any suggested addition the founder does NOT approve stays in `suggested_additions[]` with `merged: false` (leave the entry in place; only approved entries move to `competitors[]`). This preserves the gap-detection knowledge in `landscape.json` and lets the coaching commentary note "you flagged X as not-a-competitor" rather than silently losing what research surfaced. The same applies to `deferred_recall_candidates[]`: any entry not promoted this round stays in `landscape_draft.json` for exactly the reason Gate 1 put it there — reachable for a later run, not lost.

```bash
cat "$HANDOFF_DIR/landscape_research_output.json" | \
  python3 "$SCRIPTS/validate_landscape.py" --pretty --run-id "$RUN_ID" \
    --carry-deferred "$ANALYSIS_DIR/landscape_draft.json" \
    --derive-deferred "$ANALYSIS_DIR/competitor_verification.json" \
    -o "$ANALYSIS_DIR/landscape.json"
```
<!-- skill-quality-ci: bash-after-subagent-ok -->

Fix any errors (exit 1) and re-run. Warnings are acceptable — address medium-severity ones in the report.

### Gate 2: Founder Validation of Axis Selection

**MANDATORY STOP — TWO SEPARATE STEPS, same pattern as Gate 1.**

At this point no competitor coordinates exist yet — those are produced in Step 5 (POSITIONING_SCORING) and written to `positioning.json`. Gate 2 validates **which axis pair(s)** to plot on and **which competitors** belong on the map, NOT coordinate positions.

**Step A: Output a chat message** with the chosen axis pair(s) (the candidate axes from Step 3, with their rationale) and the confirmed competitor set that will be positioned. **State the scoring basis this run will use** — by default, positions reflect what the startup has actually shipped and can demonstrate today, not its roadmap. Say so in plain language (e.g. "I'll score based on what's live today, not the full roadmap — let me know if you'd rather I score against where the product is headed").

**Step B: AFTER the chat message, call `AskUserQuestion`** with a short question that **names the axis pair** so the founder isn't confirming blind. Plain text, one sentence, no markdown/tables — this question is about axes only; the scoring basis was stated in the Step-A message and is offered as an option below, not folded into the question text.

Question (substitute the two chosen axis names): `I'll plot competitors on <axis-X> × <axis-Y> — do these axes look right?`
Options: `No changes — proceed to scoring` / `Change axes` / `Adjust competitor set` / `Change scoring basis`

**Four options, never five — `AskUserQuestion` accepts at most four.** A fifth cannot be rendered, so specifying one does not add a choice; it silently forfeits whichever the model drops. There is also no need for an `Other changes` catch-all: the tool always offers the founder a free-text **Other** of its own, so spending a slot on one buys nothing and costs a real option.

If the founder changes an axis pair or the competitor set, apply the change before proceeding to Step 5. If the founder picks `Change scoring basis`, ask a short follow-up for which basis (shipped / 12-month roadmap / mixed) and carry the answer into the POSITIONING_SCORING dispatch below as `SCORING_BASIS`. **Deliberately left as prose, not declared:** this follow-up has no legitimate no-change branch (the founder just chose to change the basis), so declaring it would either fail this skill's exactly-one reserved-prefix rule or force a fabricated no-change option onto a gate that shouldn't have one — the same class of case §4.1's split exists to prevent, one level down. Converting it needs the confirm-gate marker Phase 2 deferred until a real non-confirm case arrived within an adopted skill; this is that case, parked rather than improvised. Founder adjustments to individual coordinates happen later — at the Step 5 founder-override flow, after coordinates have been assigned.

### Step 5: Positioning & Moat Assessment -> `positioning.json` + Dispatch Moat/Positioning Scoring (Context A)

**REQUIRED — read `${CLAUDE_PLUGIN_ROOT}/skills/competitive-positioning/references/moat-definitions.md` now.**

Write `positioning.json` to `$ANALYSIS_DIR` (consult `references/artifact-schemas.md` for the schema). **`moat_assessments` in this draft is optional — write `{}` or omit the key rather than authoring a full per-competitor draft.** It is superseded by `moat_scores.json` once MOAT_SCORING returns below, and nothing reads the draft block for scoring, so drafting one for every slug is effort with no consumer. Then dispatch the sub-agent **twice in parallel** (two Task calls in one message, both with `subagent_type: "founder-skills:competitive-positioning"`) — once for MOAT_SCORING and once for POSITIONING_SCORING.

**MOAT_SCORING dispatch prompt:**

```
CONTEXT: MOAT_SCORING
OUTPUT_PATH: <HANDOFF_AGENT>/moat_scoring_output.json
RUN_ID: <RUN_ID>

You are the competitive-positioning agent dispatched in Context A (MOAT_SCORING).
Read positioning.json at <ANALYSIS_DIR_AGENT>/positioning.json, landscape.json at
<ANALYSIS_DIR_AGENT>/landscape.json, and product_profile.json at
<ANALYSIS_DIR_AGENT>/product_profile.json. You are scoring _startup among the others, and
product_profile.json is the ONLY source for what the startup actually does — positioning.json's
pre-dispatch block carries placeholder evidence, so without it you would be scoring the startup
from nothing.

Score every slug (including _startup) across the 6 canonical moat dimensions from
${CLAUDE_PLUGIN_ROOT}/skills/competitive-positioning/references/moat-definitions.md:
network_effects, data_advantages, switching_costs, regulatory_barriers,
cost_structure, brand_reputation.

Each moat: status (strong/moderate/weak/absent/not_applicable), evidence (required),
evidence_source (researched/agent_estimate/founder_override), trajectory
(building/stable/eroding).

trajectory is a DIFFERENT enum from status — it is one of building/stable/eroding only. Never write
a status value (strong/moderate/weak/absent/not_applicable) into trajectory: the producer rejects it
and the whole file comes back for repair, costing a round-trip.

For trajectory and any moat where landscape.json evidence is thin, use WebSearch
to find recent (last 12 months) signals — funding rounds, M&A, hiring, executive
changes, patent filings, product launches. Stamp evidence_source: "researched"
only when the signal came from a WebSearch result. Whenever you stamp
evidence_source: "researched", also add a "source" field on that same moat
entry — the URL or the exact search query that produced the signal. The main
thread never sees your WebSearch results, only this artifact, so an unsourced
"researched" claim (e.g. a dated funding/M&A event) can't be spot-checked
later. score_moats.py warns (does not fail) on a "researched" moat with no
"source".

Use your Write tool to write to OUTPUT_PATH — exactly the shape expected by
score_moats.py:
{
  "moat_assessments": {
    "_startup": {"moats": [{"id": "...", "status": "...", "evidence": "...",
      "evidence_source": "researched", "source": "https://... OR the exact search query used",
      "trajectory": "..."}]},
    "<slug>": {"moats": [...]},
    ...
  },
  "metadata": {"run_id": "<RUN_ID>"}
}
Then return ONLY the receipt JSON in your final assistant message:
{"status": "complete", "output_path": "<echo of OUTPUT_PATH>"}
Do NOT write any file other than OUTPUT_PATH — canonical artifacts are
producer-script-only; anything else you write bypasses schema validation and
run_id stamping.
```

**POSITIONING_SCORING dispatch prompt:**

```
CONTEXT: POSITIONING_SCORING
OUTPUT_PATH: <HANDOFF_AGENT>/positioning_scoring_output.json
RUN_ID: <RUN_ID>
SCORING_BASIS: <shipped|roadmap_12mo|mixed — default "shipped" unless Gate 2 recorded a change>

You are the competitive-positioning agent dispatched in Context A (POSITIONING_SCORING).
Read positioning.json at <ANALYSIS_DIR_AGENT>/positioning.json and product_profile.json at
<ANALYSIS_DIR_AGENT>/product_profile.json (the only source for what the startup actually does —
you are placing _startup on the map alongside researched competitors).

Position every competitor and _startup according to SCORING_BASIS: "shipped" means
score only what is live and verifiable today, ignoring roadmap claims; "roadmap_12mo"
means score the startup's stated 12-month roadmap as if already delivered; "mixed"
means score today's shipped surface, but call out roadmap-only capabilities
separately in the evidence text rather than folding them into the coordinate. A
startup that ranks low under "shipped" because its stack is still roadmap is a
finding about stage, not a defect — say so in the evidence, don't just place the dot.

For each view in positioning.json, assign coordinates (0-100) for every competitor
and _startup on both axes. Every point needs x_evidence, y_evidence, and provenance.
Assess differentiation claims: verifiable (boolean), evidence, challenge, verdict
(holds/partially_holds/does_not_hold).

The axes themselves drive the search queries — when an axis is "customer support
depth" or "pricing transparency," issue WebSearch queries targeting that specific
dimension per competitor. Stamp x_evidence_source / y_evidence_source as
"researched" only when the coordinate came from a WebSearch result. For each
differentiation_claim, use WebSearch to find supporting or contradicting evidence
before assigning a verdict.

Use your Write tool to write to OUTPUT_PATH — exactly the shape expected by
score_positioning.py:
{
  "scoring_basis": "<echo of SCORING_BASIS>",
  "views": [
    {
      "id": "...", "x_axis": {"name": "...", "rationale": "..."}, "y_axis": {"name": "...", "rationale": "..."},
      "points": [
        {"competitor": "...", "x": 0-100, "y": 0-100,
         "x_evidence": "...", "y_evidence": "...",
         "x_evidence_source": "researched|agent_estimate",
         "y_evidence_source": "researched|agent_estimate"}
      ]
    }
  ],
  "differentiation_claims": [...],
  "metadata": {"run_id": "<RUN_ID>"}
}
Then return ONLY the receipt JSON in your final assistant message:
{"status": "complete", "output_path": "<echo of OUTPUT_PATH>"}
Do NOT write any file other than OUTPUT_PATH — canonical artifacts are
producer-script-only; anything else you write bypasses schema validation and
run_id stamping.
```

**After both sub-agents return:** gate EACH hand-off per the Context A hand-off protocol (run `check_handoff.py` per file, branch on exit codes). Then pipe each file through its producer:

```bash
cat "$HANDOFF_DIR/moat_scoring_output.json" | \
  python3 "$SCRIPTS/score_moats.py" --pretty --run-id "$RUN_ID" -o "$ANALYSIS_DIR/moat_scores.json"
```
<!-- skill-quality-ci: bash-after-subagent-ok -->

```bash
cat "$HANDOFF_DIR/positioning_scoring_output.json" | \
  python3 "$SCRIPTS/score_positioning.py" --pretty --run-id "$RUN_ID" -o "$ANALYSIS_DIR/positioning_scores.json"
```
<!-- skill-quality-ci: bash-after-subagent-ok -->

**Merge the scored coordinates back into `positioning.json` (required, not optional).** The
`positioning.json` you wrote earlier in this step had placeholder/draft points — the
POSITIONING_SCORING sub-agent's gated hand-off file (`positioning_scoring_output.json`) now carries
the real, evidence-grounded coordinates. `compose_report.py`, `visualize.py`, and `explore.py` all
read points from `positioning.json`, so nothing downstream sees the real coordinates until you copy
them over. (`positioning_scores.json` is **not** "aggregates only" — `score_positioning.py` passes
each input view's `points[]` straight through, so it carries the authoritative post-scoring
coordinates too. That is exactly why compose can and does cross-check the two: skipping this merge is
detected, not silently rendered.) For
each view in the gated hand-off file, overwrite the corresponding view's `points[]` in
`positioning.json` with the hand-off file's `points[]` for that `view.id` — copy the coordinates and
evidence fields verbatim, changing nothing else in `positioning.json`. This is a **mechanical**
merge (see the carve-out above) — you are relocating the sub-agent's own output, not authoring new
scores or evidence.

**Also copy `scoring_basis` into `positioning.json` in this same pass.** The hand-off file's
top-level `scoring_basis` (echoed from `SCORING_BASIS` in the dispatch) needs to land in
`positioning.json` too, not just in `positioning_scores.json` — the founder coordinate-override flow
below re-pipes `positioning.json` itself through `score_positioning.py`, which only passes
`scoring_basis` through when its stdin carries it. Skip this and the refreshed
`positioning_scores.json` from an override silently loses the field, and every renderer falls back
to "Not declared" precisely on the runs where the founder engaged with the map. Set
`positioning.json`'s top-level `scoring_basis` to the hand-off file's `scoring_basis` value alongside
the points merge.

**The same merge applies to `differentiation_claims`.** The `positioning.json` you wrote earlier in this step carries claim text only, with no verdict yet — the sub-agent's gated hand-off file is where the real `verdict` / `evidence` / `challenge` per claim get assigned. Overwrite `positioning.json`'s `differentiation_claims[]` with the hand-off file's `differentiation_claims[]`, matched by claim text — the same mechanical relocation as the points merge above. Do this regardless of whether anything downstream currently reads it: `positioning.json` is the canonical artifact this step is responsible for keeping internally consistent, and it is what downstream consumers and re-pipes fall back to — leaving points scored but claims still draft-text-only is exactly the kind of partial merge the "changing nothing else" mechanical-relocation rule exists to prevent.

### Gate 3: Positioning Reality Check (conditional)

**CONDITIONAL — only stop when one of the triggers below fires. An unconditional stop here would tax every run.** After the merge above, check **every view** in `positioning_scores.json` — vanity flags, rank, and `overall_differentiation` live there, not in `positioning.json`. **Primary view = `views[0]`** — real runs use descriptive slug ids rather than the documented `primary`/`secondary`, so do not look for those literal strings when deciding which view is primary; a `views[]` entry may also carry an optional `label` field used for display, which is not a signal of which view is primary either. Evaluate every trigger below **per view, not on the primary view alone** — a trade-off or flattering shape on a secondary view is invisible if only the primary view is checked:

- `_startup`'s rank (`startup_x_rank` / `startup_y_rank`) is in the bottom half of the competitive set on BOTH axes, on any view. **This trigger is PROVISIONAL** — like the differentiation trigger below, it is calibrated on a single observed run, not a validated threshold. Treat it as a soft prompt to look again, not a settled bound.
- `_startup` is top-2 on BOTH axes (by rank) AND both vanity-axis flags (`x_axis_vanity_flag` / `y_axis_vanity_flag`) on that view are false, on any view — the suspiciously-flattering pattern the methodology reference warns about, not a genuine strong result.
- **Trade-off shape** — `_startup` is in the bottom quartile (roughly the worst 25%) on ONE axis AND top-2 on the OTHER axis, on any view. **This trigger is PROVISIONAL**, added after a live run the bottom-half-on-both trigger above could not see (rank 10 of 11 on one axis, 3 of 11 on the other). The mean-based `overall_differentiation` trigger below caught that run only incidentally, because its 50/50 rank-and-gap blend happened to average out below 25% — a genuine one-axis trade-off can just as easily average out to something unremarkable, so this trigger checks the two axes directly instead of relying on the mean to notice.
- `overall_differentiation` is below 25%, on any view. **This trigger is PROVISIONAL** — it is calibrated on a single observed run, not a validated threshold. Treat it as a soft prompt to look again, not a settled bound.

If none fire on any view, skip this gate silently and continue.

If one fires: **Step A: Output a chat message** naming which pattern triggered, in plain language, alongside the scored position and — when available — the position the deck's own competition slide claimed, for comparison.

**Step B: AFTER the chat message, call `AskUserQuestion`**, plain text, one sentence, no markdown/tables: `The scored position <plain-language description of the trigger> — keep it, dig deeper, or reconsider how it's scored?` Options: `No changes — keep the scoring` / `Re-score with founder facts` / `Change scoring basis` / `Show both positions`.

If the founder picks `Re-score with founder facts`, gather the additional detail and re-dispatch POSITIONING_SCORING (and MOAT_SCORING if the new facts bear on a moat) before re-merging into `positioning.json`. **Then re-run Step 6's checklist pipe too** (with `--positioning-scores` pointed at the refreshed `positioning_scores.json`) — `score_positioning.py`'s rank and differentiation numbers just moved, and POS_04 reads that data directly, so a checklist graded before this re-score no longer matches the map it is grading. If `Change scoring basis`, follow the same basis-change mechanism as Gate 2. If `Show both positions`, note both the scored map and the deck's claimed position in the report rather than picking one.

**Founder coordinate-override flow (optional):** Now that competitor coordinates exist, present the positioned map to the founder if they ask to adjust positions in chat, or if Gate 3 above triggered and the founder picked `Re-score with founder facts`. If the founder corrects a specific coordinate, update the corresponding point in `positioning.json` and re-run `score_positioning.py`, stamping `x_evidence_source` / `y_evidence_source: "founder_override"` on the changed coordinate so `compose_report.py` records it via `FOUNDER_OVERRIDE_COUNT`. Re-pipe the updated `positioning.json` views through `score_positioning.py` to refresh `positioning_scores.json` — **then re-run Step 6's checklist pipe as well**, so `checklist.json`'s recorded fingerprint matches the map the founder just changed, not the one from before the override.

### Step 6: Score Checklist -> `checklist.json` (Context A: CHECKLIST dispatch)

**REQUIRED — read `${CLAUDE_PLUGIN_ROOT}/skills/competitive-positioning/references/checklist-criteria.md` now.**

**Dispatch the competitive-positioning sub-agent in Context A (CHECKLIST).** **Call the `Task` tool with `subagent_type: "founder-skills:competitive-positioning"`.**

**Dispatch prompt template:**

```
CONTEXT: CHECKLIST
OUTPUT_PATH: <HANDOFF_AGENT>/checklist_output.json
RUN_ID: <RUN_ID>

You are the competitive-positioning agent dispatched in Context A (CHECKLIST).
Read landscape.json, positioning.json, moat_scores.json, positioning_scores.json,
product_profile.json, and landscape_draft.json from <ANALYSIS_DIR_AGENT>. Also read
${CLAUDE_PLUGIN_ROOT}/skills/competitive-positioning/references/checklist-criteria.md.
product_profile.json's deck_competition_slide field (deck mode) and
landscape_draft.json's deck_competitors_excluded field are what the
competition-slide cross-check item (NARR_03) needs — without them it has
nothing to grade. When deck_competition_slide.present is false (the deck had
no competition slide at all), grade NARR_03 not_applicable using the stated
reason as your evidence — do not treat the field's absence as "nothing to
grade" once a present:false record with a reason exists.

Assess all 25 checklist items (COVER_01..05, POS_01..05, MOAT_01..04,
EVID_01..04, NARR_01..04, MISS_01..03). Mode-based gating applies: when
input_mode is conversation, research-dependent items auto-gate to not_applicable.

Evidence is MANDATORY for every item: every fail and warn MUST have a non-empty
evidence string citing specific findings. Every pass MUST have evidence noting
what was checked.

Use your Write tool to write to OUTPUT_PATH — the items array without a
summary (the producer script computes the summary):
{"items": [{"id": "COVER_01", "status": "pass", "evidence": "...", "notes": "..."}, ...all 25 items...]}
Then return ONLY the receipt JSON in your final assistant message:
{"status": "complete", "output_path": "<echo of OUTPUT_PATH>"}
Do NOT write any file other than OUTPUT_PATH — canonical artifacts are
producer-script-only; anything else you write bypasses schema validation and
run_id stamping.
```

**After the sub-agent returns:** gate the hand-off per the Context A hand-off protocol, then pipe through the producer script. The sub-agent writes items only — pass the real input mode and run_id on the CLI so `checklist.py` gates the right items and stamps `metadata.run_id`:

```bash
cat "$HANDOFF_DIR/checklist_output.json" | python3 "$SCRIPTS/checklist.py" --pretty \
  --input-mode "$INPUT_MODE" --run-id "$RUN_ID" \
  --positioning-scores "$ANALYSIS_DIR/positioning_scores.json" -o "$ANALYSIS_DIR/checklist.json"
```
<!-- skill-quality-ci: bash-after-subagent-ok -->

`$INPUT_MODE` is the mode established in Steps 1-2 (`deck`, `conversation`, or `document`). Without `--input-mode`, deck/document runs silently default to `conversation` and mis-gate NARR_03/EVID_04; without `--run-id`, `checklist.json` carries no run_id and the Step 7c verifier blocks. `--positioning-scores` records which scored positioning map this checklist graded (a `views_fingerprint` copied verbatim from `positioning_scores.json`), so a later `compose_report.py` run can detect a checklist that was graded against a map that has since moved — this is the ONLY place `checklist.json` is produced on a normal run, so omitting the flag here means the whole staleness check can never fire.

### Step 7: Compose, Validate, and Post-Compose Coaching

**7a — Compose report JSON (two-pass pattern):**

**Pass 1 (discovery):** Run compose WITHOUT `--strict` and WITHOUT `accepted_warnings` in `positioning.json`:

```bash
python3 "$SCRIPTS/compose_report.py" --dir "$ANALYSIS_DIR" --pretty \
  -o "$ANALYSIS_DIR/report.json" \
  --write-md "$ANALYSIS_DIR/report.md"
```

`compose_report.py` writes both `report.json` and `report.md` deterministically. **Do NOT** read `report_markdown` out of `report.json` and re-write it via heredoc.

Inspect the warnings in the output. Fix any high-severity warnings (missing artifacts, stale run_id, corrupt JSON, artifacts not written by their producer script) and re-run Pass 1.

**Pass 2 (with acceptances):** If any medium-severity warnings should be accepted, add `accepted_warnings` to `positioning.json` with the warning code, match pattern, and reason. Then re-run with `--strict`:

```bash
python3 "$SCRIPTS/compose_report.py" --dir "$ANALYSIS_DIR" --strict --pretty \
  -o "$ANALYSIS_DIR/report.json" \
  --write-md "$ANALYSIS_DIR/report.md"
```

**Post-write verification:** `compose_report.py` exits non-zero (code 2) if the declared output files don't exist or are empty after writing. If compose exits non-zero, stop and report the exact stderr — do not proceed.

**7b — Cross-skill lookups:** Use `find_artifact.py` to locate prior deck-review and market-sizing artifacts. If found, note findings for inclusion in coaching commentary. Example (resolve the market-sizing sizing artifact for this company):

```bash
python3 "$SHARED_SCRIPTS/find_artifact.py" --skill market-sizing --artifact sizing.json \
  --slug "$SLUG" --artifacts-root "$ARTIFACTS_ROOT" --pretty
# deck-review: --skill deck-review --artifact checklist.json
```

**7c — Post-Compose Coaching Commentary (Context B dispatch — POST_COMPOSE_COACHING):**

**Dispatch the competitive-positioning sub-agent in Context B.** **Call the `Task` tool with `subagent_type: "founder-skills:competitive-positioning"`** after `compose_report.py` has successfully written both `report.json` and `report.md`.

**Mitigation 2 protocol:** the main thread reads the structured `coaching_payload` from `report.json` and STAGES it as a file in the hand-off dir; the sub-agent Reads it from the agent namespace (a functionally required read, so a wrong prefix fails loudly before anything is written). The sub-agent does NOT Read full `report.md` — it consumes the staged `coaching_payload.json` directly, composes the coaching commentary, and **WRITES it as plain markdown to the `OUTPUT_PATH` hand-off file (a `.md` file) with its Write tool — no JSON, no escaping — returning only a small receipt** (the same file transport as Context A — the commentary leaves the model exactly once, into the Write call; the main thread never re-types it). The main thread gates that file with `check_handoff.py --format=markdown`, transforms it into the JSON transport envelope with `md_to_commentary.py` (deterministic escaping — `json.dumps` cannot emit malformed JSON), then pipes it into the shared `insert_coaching.py` script (idempotency matrix, uuid-marker replacement, run_id-parity verification — all deterministic, unchanged). See the competitive-positioning agent body's "Context B — Post-compose coaching dispatch (POST_COMPOSE_COACHING)" section for the full procedure.

<!-- skill-quality-ci: bash-after-subagent-ok -->
```bash
python3 -c '
import json, sys
data = json.load(open(sys.argv[1]))
json.dump(data["coaching_payload"], open(sys.argv[2], "w"), indent=2)
print(json.dumps({"staged": sys.argv[2]}))
' "$ANALYSIS_DIR/report.json" "$HANDOFF_DIR/coaching_payload.json"
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

You are dispatched to add coaching commentary to a competitive positioning review.

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
   warned_items, summary, high_severity_warnings, company_name).
   Do NOT Read the full report.md. Do NOT edit report.md or any canonical artifact.
   No WebSearch in this context — commentary is payload-grounded only.
   Write for the founder, not for someone debugging the pipeline: never use a
   checklist criterion ID (e.g. NARR_03), an internal field name (e.g.
   moat_count), or any other internal label in the commentary text, backticked
   or not — say what the finding actually IS, in plain language, the same rule
   that governs every other founder-visible message in this skill.
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
# Use the PLUGIN_ROOT Step 0 printed, verbatim — substitute the absolute path directly.
# Do NOT re-run find here: a fresh find in this fresh shell can land on a different
# plugin-root mount than the one Step 0 selected, mixing scripts across versions
# mid-pipeline (that non-determinism is what select_plugin_root.py in Step 0 exists to kill).
SHARED_SCRIPTS="<PLUGIN_ROOT printed by Step 0>/scripts"
printf '%s' '<agent final message verbatim>' | \
  python3 "$SHARED_SCRIPTS/check_handoff.py" "$HANDOFF_DIR/coaching.md" \
    --format=markdown --agent-path "$HANDOFF_AGENT/coaching.md" --receipt-json - \
    --marker '<EXACT insertion_marker string from report.json coaching_payload>'
```

**On gate exit 0**, transform the gated hand-off FILE into the JSON transport envelope and insert (feed the file, never re-type the message):

<!-- skill-quality-ci: bash-after-subagent-ok -->
```bash
# Use the PLUGIN_ROOT Step 0 printed, verbatim — substitute the absolute path directly.
# Do NOT re-run find here — same reasoning as the block above.
SHARED_SCRIPTS="<PLUGIN_ROOT printed by Step 0>/scripts"
python3 "$SHARED_SCRIPTS/md_to_commentary.py" "$HANDOFF_DIR/coaching.md" | \
  python3 "$SHARED_SCRIPTS/insert_coaching.py" \
    --report "$ANALYSIS_DIR/report.md" \
    --marker '<EXACT insertion_marker string from report.json coaching_payload>' \
    --verify-artifact "$ANALYSIS_DIR/landscape.json" \
    --verify-artifact "$ANALYSIS_DIR/positioning.json" \
    --verify-artifact "$ANALYSIS_DIR/moat_scores.json" \
    --verify-artifact "$ANALYSIS_DIR/positioning_scores.json" \
    --verify-artifact "$ANALYSIS_DIR/checklist.json"
```

The gate (`check_handoff.py --format=markdown`) verifies the sub-agent's hand-off file exists, is non-empty, matches the receipt's echoed path, and passes the content-shape gate (not receipt-shaped, no marker collision); `md_to_commentary.py` wraps the raw markdown in the `{"commentary_markdown": ...}` envelope (escaping by construction via `json.dumps`); `insert_coaching.py` then performs the 6-state idempotency check, replaces the marker with `## Coaching Commentary` + the commentary in a single in-place write, and verifies `run_id` parity across all 5 producer artifacts. Branch on the exit code (complete state machine — do not improvise):

- **Exit 0 from the chain** — `insert_coaching.py`'s receipt on stdout says `inserted` (or `already_inserted` on a resume). Present `report_path` to the founder and proceed.
- **`check_handoff.py` exit 3** (missing/empty file — receipt may be fabricated) → **redo-dispatch**: fresh Task, same prompt plus one line: "your receipt claimed a file at `<path>` but none exists; use Write to create exactly that path."
- **Exit 5** (receipt echoes a different path) → **repair-dispatch** telling the agent the exact expected OUTPUT_PATH.
- **Exit 6** (receipt unparseable / no `output_path` key) → **redo-dispatch** with "return ONLY the receipt JSON — no fences, no prose." (A `status: "blocked"` final message is NOT exit 6 — it was handled before the gate.)
- **Exit 7** (content-shape gate failed — receipt-shaped or marker-bearing file) → **repair-dispatch**: "your file wasn't the coaching commentary — write the coaching markdown, nothing else, to `<OUTPUT_PATH>`."
- **Exit 8** (`path_namespace_mismatch`) → the sub-agent **complied**; the agent-namespace prefix was wrong. Its relative `OUTPUT_PATH` resolved against the outputs mount instead of the session root, so the file landed at the doubled path reported in `found_at`. Do NOT treat this as a fabricated receipt, and do NOT read the hand-off from `found_at` — re-dispatch with the corrected agent-namespace prefix (re-run `resolve_artifacts_root.py --agent` and rebuild `<HANDOFF_AGENT>` from the printed value). Counts against the same 2-dispatch retry budget.
- **`insert_coaching.py` exit 1** (blocked; stdout carries `{"status": "blocked", "reason": ...}`) → stop and report the exact reason. Do NOT hand-edit `report.md` — if the reason mentions a truncated report or a missing marker, re-run `compose_report.py --write-md` and retry the chain. If the reason is `commentary_markdown missing or empty`, treat as a malformed hand-off: repair-dispatch quoting the reason.
- **After ANY corrective dispatch, resume from the gate chain** — never feed the transform+insert pipe an ungated file.

**Retry budget:** max 2 corrective dispatches (same rule as Context A). **Graceful degrade:** if the FIRST corrective dispatch also exits 3 while the receipt claims `complete` with the correctly echoed path, treat the host topology as hand-off-incompatible and fall back to message-channel transport. **The corrective dispatch MUST ask for the commentary inline for this to be reachable** — add: "the file hand-off is not working in this environment; return the coaching commentary itself as your final message, as raw markdown, with no receipt JSON and no fences." Without that line the fallback is unreachable: the normal Context B prompt instructs the agent to return ONLY the receipt and not to narrate, so its final message contains no markdown to stage. Then stage that returned markdown to `$STAGING_DIR/coaching.md` via a **single-quoted** `<<'COACHING_EOF'` heredoc (apostrophe-safe; NEVER `python -c`, NEVER the `outputs/` root — `$STAGING_DIR` is the `/tmp` scratch dir from Step 0, never the promoted outputs mount), and run the same `md_to_commentary.py "$STAGING_DIR/coaching.md" | insert_coaching.py` chain against that staged file.

**7d — Visualize (optional):**

```bash
python3 "$SCRIPTS/visualize.py" --dir "$ANALYSIS_DIR" -o "$ANALYSIS_DIR/report.html"
```

**Do not hand this over here** — the Deliver step below is the only place work reaches the founder, and it sends the complete set as files. A path presented here is the partial-delivery bug.

**7e — Explorer (optional):**

```bash
python3 "$SCRIPTS/explore.py" --dir "$ANALYSIS_DIR" -o "$ANALYSIS_DIR/explore.html"
```

**Do not hand this over here** — the Deliver step below is the only place work reaches the founder, and it sends the complete set as files. A path presented here is the partial-delivery bug.

### Step 8: Deliver Artifacts

Copy final deliverables to the **workspace root — `$ARTIFACTS_ROOT/..`, i.e. the promoted outputs mount
itself, NOT `$ARTIFACTS_ROOT` and NOT `$ANALYSIS_DIR`**. Concretely, if `$ARTIFACTS_ROOT` is
`<mount>/artifacts` then these go to `<mount>/`. That is the level the founder sees as deliverable
cards; `artifacts/` below it is working state. Do not infer the level by elimination —
`dirname "$ARTIFACTS_ROOT"` is the answer, and a bare `./` target is not: it lands in whatever the
shell's cwd happens to be.

```bash
OUT="$(dirname "$ARTIFACTS_ROOT")"
cp "$ANALYSIS_DIR/report.md" "$OUT/${COMPANY_NAME}_Competitive_Positioning.md"
cp "$ANALYSIS_DIR/report.html" "$OUT/${COMPANY_NAME}_Competitive_Positioning.html" 2>/dev/null
cp "$ANALYSIS_DIR/explore.html" "$OUT/${COMPANY_NAME}_Competitive_Explorer.html" 2>/dev/null
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

Scratch lives in `$STAGING_DIR` (`/tmp`, reclaimed by the sandbox) — no cleanup needed. **Do not `rm`
anything under `$ANALYSIS_DIR`** — it is the promoted `outputs/` tree in Cowork, where deleting a
user-visible path is unsafe (and the parity gate flags it).

Where `COMPANY_NAME` is the company name with spaces replaced by underscores (e.g., "Acme Corp" -> "Acme_Corp"). Present the file paths to the user.

**Presenting the report to the founder:**
- Answer placement and moat questions **from the points/evidence tables in report.md** — never re-derive or restate coordinates from memory.
- If the founder disputes a coordinate (e.g., "we're faster than you placed us"), use the **founder coordinate-override flow** (Step 5): update the specific point in `positioning.json` with `x_evidence_source: "founder_override"` and re-run `score_positioning.py` to refresh `positioning_scores.json`, then re-run the Step 6 checklist pipe (so `checklist.json`'s recorded fingerprint matches the changed map) and `compose_report.py`. Do NOT re-explain a placement from chat context.
- For what-if competitive scenarios (e.g., "what if we added this moat?"), note the gap and invite the founder to re-run the full skill after updating the relevant data.
- **If the scoring basis diverges from the deck's own competition slide, say so explicitly rather than letting the scored map silently contradict it** — follow the delta rule in `competitive-analysis-methodology.md` §7 ("When the basis diverges from the founder's deck").

## Scoring

### Moat Scoring
- 6 canonical dimensions per company, each: `strong` / `moderate` / `weak` / `absent` / `not_applicable`
- Moat count = dimensions with **any** status other than `absent` / `not_applicable` — so a `weak`
  moat still counts. It measures how many dimensions are in play at all, not how many are good.
- Overall defensibility: `high` (2+ strong), `moderate` (1 strong or 2+ moderate), `low` (all else)
- **The two are independent, and a low-quality company reads as contradictory unless you say so.**
  Two `weak` moats give `moat_count: 2` with `overall_defensibility: "low"` — that is correct, not a
  scoring bug. When presenting both, state the count and the grade together ("2 moats identified, both
  weak — overall defensibility low"), never the count alone.

### Positioning Scoring
- Distance-weighted differentiation: rank contributes 50% (where the startup ranks among competitors) + gap contributes 50% (how far ahead of the next-best competitor). This distinguishes "barely ahead" from "dramatically ahead" at the same rank.
- Vanity axis detection: >80% of competitors within 20% range on either axis

### Checklist Scoring
- 25 items, each: pass / fail / warn / not_applicable
- `score_pct` = (pass + 0.5 * warn) / (total - not_applicable) * 100
- Overall: "strong" (>=85%), "solid" (>=70%), "needs_work" (>=50%), "major_revision" (<50%)

## Cross-Agent Integration

This skill imports artifacts from prior deck-review (competition slide claims) and market-sizing (market scope validation) analyses. Imported artifacts are recorded with dates so cross-skill findings can be cited with their provenance.

## Main-Thread Return

This skill runs inline in the main thread (not as a sub-agent). The final outcome the main thread delivers to the founder is:

- **In Claude Code:** the path to `$ANALYSIS_DIR/report.md` — there the path *is* the deliverable, because
  `./artifacts/` is durable. **In Cowork:** the delivered files are the deliverable; a path
  names a workspace that may not outlive the task.
- The headline outcome fields, sourced from the `coaching_payload` staged in Step 7c (`summary.overall_status`, `high_severity_warnings`) and the producer artifacts (`moat_scores.json` for top moats), plus the `insert_coaching.py` receipt (`status`, `report_path`, `run_id`). The Context B sub-agent no longer echoes these — do not source them from its return.

  **Nesting matters here, and it is mixed — read the path, not the pattern:** `overall_status` sits under `coaching_payload.summary` (which also carries `score_pct`); reading `coaching_payload.score_pct` returns null while the real number sits one level down, and a live run did exactly that. But `high_severity_warnings` is **top level** — reaching under `summary` for it returns null too, in the opposite direction.
- Optionally: the HTML report paths from Steps 7d and 7e.

**Do NOT inline `report_markdown` in the assistant message.** The founder reads the file via the path.

## Feedback

If a run ends **blocked or failed**, after you report the reason to the founder, add one line:
> _If this looks wrong or didn't finish, you can flag it: `/founder-skills:feedback`._

On **unsolicited** praise or frustration, you may mention `/founder-skills:feedback` once — never routinely, never mid-workflow, never more than once per session.
